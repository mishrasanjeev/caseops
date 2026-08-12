from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import ApiIdempotencyRecord, ApiIdempotencyState
from caseops_api.db.session import serialize_sqlite_writer

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HTTP_METHOD = re.compile(r"^[A-Z]{1,12}$")
_OPERATION = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_JSON_SAFE_INTEGER_MAX = 9_007_199_254_740_991
_DEFAULT_MINIMUM_RETENTION = timedelta(days=7)
_LEGAL_MINIMUM_RETENTION = timedelta(days=365)
_LEGAL_OPERATION_PREFIXES = (
    "ip.",
    "ip_document.",
    "bulk_import.",
    "billing.",
    "notification.",
    "payment.",
    "payments.",
    "provider.",
)


class IdempotencyClaimOutcome(StrEnum):
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    REPLAY = "replay"
    KEY_REUSED = "key_reused"


class StaleIdempotencyClaimError(RuntimeError):
    """The caller no longer owns the processing claim."""


@dataclass(frozen=True, slots=True)
class CanonicalFilePart:
    field_name: str
    file_name: str
    media_type: str
    size_bytes: int
    content_sha256: str
    representation_version: str | None = None

    def as_payload(self) -> dict[str, object]:
        if not self.field_name.strip():
            raise ValueError("File field_name is required.")
        if not self.file_name.strip():
            raise ValueError("File file_name is required.")
        if not self.media_type.strip():
            raise ValueError("File media_type is required.")
        if self.size_bytes < 0:
            raise ValueError("File size_bytes cannot be negative.")
        _validate_sha256(self.content_sha256, field="content_sha256")
        return {
            "field_name": self.field_name.strip(),
            "file_name": self.file_name,
            "media_type": self.media_type.strip().lower(),
            "size_bytes": self.size_bytes,
            "content_sha256": self.content_sha256,
            "representation_version": self.representation_version,
        }


@dataclass(frozen=True, slots=True)
class IdempotencyRecordSnapshot:
    id: str
    company_id: str
    actor_scope: str
    actor_membership_id: str | None
    http_method: str
    operation: str
    idempotency_key: str
    request_hash: str
    state: str
    claim_generation: int
    response_status: int | None
    result_type: str | None
    result_id: str | None
    finished_at: datetime | None
    expires_at: datetime
    created_at: datetime


def _record_snapshot(record: ApiIdempotencyRecord) -> IdempotencyRecordSnapshot:
    return IdempotencyRecordSnapshot(
        id=record.id,
        company_id=record.company_id,
        actor_scope=record.actor_scope,
        actor_membership_id=record.actor_membership_id,
        http_method=record.http_method,
        operation=record.operation,
        idempotency_key=record.idempotency_key,
        request_hash=record.request_hash,
        state=record.state,
        claim_generation=record.claim_generation,
        response_status=record.response_status,
        result_type=record.result_type,
        result_id=record.result_id,
        finished_at=record.finished_at,
        expires_at=record.expires_at,
        created_at=record.created_at,
    )


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    outcome: IdempotencyClaimOutcome
    record: IdempotencyRecordSnapshot
    claim_token: str | None = None
    claim_generation: int | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _validate_sha256(value: str, *, field: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest.")


def _validate_json_value(value: object, *, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError(f"JSON string at {path} contains an unpaired surrogate.")
        return
    if isinstance(value, int):
        if abs(value) > _JSON_SAFE_INTEGER_MAX:
            raise ValueError(
                f"JSON integer at {path} exceeds the interoperable safe range."
            )
        return
    if isinstance(value, float):
        raise TypeError(
            f"Floating-point JSON number at {path} is not canonical. "
            "Encode decimal values as contract-defined strings or scaled integers."
        )
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Canonical JSON object key at {path} must be a string.")
            if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                raise ValueError(
                    f"Canonical JSON object key at {path} contains an unpaired surrogate."
                )
            _validate_json_value(nested, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _validate_json_value(nested, path=f"{path}[{index}]")
        return
    raise TypeError(
        f"Unsupported canonical JSON value at {path}: {type(value).__name__}. "
        "Serialize dates, decimals, UUIDs, and models explicitly first."
    )


def _utf16_sort_key(value: str) -> bytes:
    """Match ECMAScript/JCS object-key ordering by UTF-16 code units."""

    return value.encode("utf-16-be")


def _ordered_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _ordered_json_value(value[key])
            for key in sorted(value, key=_utf16_sort_key)
        }
    if isinstance(value, (list, tuple)):
        return [_ordered_json_value(item) for item in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON-compatible value using the CaseOps stable JSON form.

    Callers must first convert typed values to their public JSON representation.
    Rejecting implicit ``str()`` conversion prevents a backend refactor from
    silently changing request identity.  Integers are limited to the exact
    JavaScript/Python interoperable range and floating-point values are rejected
    because their textual forms are not portable canonical decimal evidence.
    """

    _validate_json_value(value)
    return json.dumps(
        _ordered_json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def canonical_request_hash(
    payload: object,
    *,
    files: Sequence[CanonicalFilePart] = (),
) -> str:
    """Hash canonical JSON plus ordered multipart evidence, without file bytes."""

    envelope = {
        "payload": payload,
        "files": [part.as_payload() for part in files],
    }
    return canonical_json_sha256(envelope)


def _lock_statement(
    session: Session,
    statement: Select[tuple[ApiIdempotencyRecord]],
) -> Select[tuple[ApiIdempotencyRecord]]:
    if session.get_bind().dialect.name == "postgresql":
        return statement.with_for_update(of=ApiIdempotencyRecord)
    return statement


def _scope_statement(
    *,
    company_id: str,
    actor_scope: str,
    http_method: str,
    operation: str,
    idempotency_key: str,
) -> Select[tuple[ApiIdempotencyRecord]]:
    return select(ApiIdempotencyRecord).where(
        ApiIdempotencyRecord.company_id == company_id,
        ApiIdempotencyRecord.actor_scope == actor_scope,
        ApiIdempotencyRecord.http_method == http_method,
        ApiIdempotencyRecord.operation == operation,
        ApiIdempotencyRecord.idempotency_key == idempotency_key,
    )


def _new_claim_token() -> str:
    return uuid4().hex


def idempotency_retention_for_operation(operation: str) -> timedelta:
    """Return the server-owned retry-evidence window for an operation."""

    normalized = operation.strip().lower()
    if not normalized:
        raise ValueError("operation is required for idempotency retention.")
    if normalized.startswith(_LEGAL_OPERATION_PREFIXES):
        return _LEGAL_MINIMUM_RETENTION
    return _DEFAULT_MINIMUM_RETENTION


def _claim_existing(
    record: ApiIdempotencyRecord,
    *,
    now: datetime,
    claim_ttl: timedelta,
    expires_at: datetime,
) -> IdempotencyClaim:
    record.state = ApiIdempotencyState.PROCESSING
    record.claim_token = _new_claim_token()
    record.claim_generation += 1
    record.expires_at = max(_aware(record.expires_at), expires_at)
    record.claim_expires_at = min(now + claim_ttl, record.expires_at)
    record.response_status = None
    record.result_type = None
    record.result_id = None
    record.finished_at = None
    record.updated_at = now
    return IdempotencyClaim(
        outcome=IdempotencyClaimOutcome.CLAIMED,
        record=_record_snapshot(record),
        claim_token=record.claim_token,
        claim_generation=record.claim_generation,
    )


def claim_idempotency(
    session: Session,
    *,
    company_id: str,
    actor_scope: str,
    http_method: str,
    operation: str,
    idempotency_key: str,
    request_hash: str,
    actor_membership_id: str | None = None,
    claim_ttl: timedelta = timedelta(minutes=15),
    now: datetime | None = None,
) -> IdempotencyClaim:
    """Claim or classify one scoped idempotency key without committing."""

    current_time = _aware(now or _now())
    company_id = company_id.strip()
    actor_scope = actor_scope.strip()
    http_method = http_method.strip().upper()
    operation = operation.strip().lower()
    idempotency_key = idempotency_key.strip()
    if not company_id or not actor_scope or not operation or not idempotency_key:
        raise ValueError("Company, actor scope, operation, and idempotency key are required.")
    if len(company_id) > 36:
        raise ValueError("company_id exceeds the persisted contract.")
    if not _HTTP_METHOD.fullmatch(http_method):
        raise ValueError("A bounded HTTP method is required.")
    if not _OPERATION.fullmatch(operation):
        raise ValueError("Operation must use the normalized operation-name contract.")
    if len(actor_scope) > 160 or len(operation) > 160 or len(idempotency_key) > 200:
        raise ValueError("Idempotency scope exceeds the persisted contract.")
    if actor_membership_id is not None:
        actor_membership_id = actor_membership_id.strip()
        if not actor_membership_id or len(actor_membership_id) > 36:
            raise ValueError("actor_membership_id exceeds the persisted contract.")
        if actor_scope != f"membership:{actor_membership_id}":
            raise ValueError(
                "Membership idempotency scope must identify the supplied membership."
            )
    elif not actor_scope.startswith("system:") or not actor_scope.removeprefix(
        "system:"
    ).strip():
        raise ValueError("A typed membership or named system actor scope is required.")
    _validate_sha256(request_hash, field="request_hash")
    if claim_ttl <= timedelta(0):
        raise ValueError("claim_ttl must be positive.")
    expires_at = current_time + idempotency_retention_for_operation(operation)

    scope = _scope_statement(
        company_id=company_id,
        actor_scope=actor_scope,
        http_method=http_method,
        operation=operation,
        idempotency_key=idempotency_key,
    )
    serialize_sqlite_writer(session)
    record = session.scalar(_lock_statement(session, scope))
    if record is None:
        token = _new_claim_token()
        record = ApiIdempotencyRecord(
            company_id=company_id,
            actor_scope=actor_scope,
            actor_membership_id=actor_membership_id,
            actor_company_id=company_id if actor_membership_id else None,
            http_method=http_method,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            state=ApiIdempotencyState.PROCESSING,
            claim_token=token,
            claim_generation=1,
            claim_expires_at=min(current_time + claim_ttl, expires_at),
            expires_at=expires_at,
            created_at=current_time,
            updated_at=current_time,
        )
        if session.get_bind().dialect.name == "sqlite":
            # Serialization was acquired before the absent-row lookup.  Avoid
            # a SAVEPOINT as the first SQLite write: Python's deferred BEGIN
            # can otherwise make RELEASE SAVEPOINT commit outside the caller's
            # transaction.
            session.add(record)
            session.flush()
            return IdempotencyClaim(
                outcome=IdempotencyClaimOutcome.CLAIMED,
                record=_record_snapshot(record),
                claim_token=token,
                claim_generation=1,
            )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError:
            # Another request won the unique scope while this transaction was
            # waiting.  The savepoint preserves the caller's outer transaction.
            record = session.scalar(_lock_statement(session, scope))
            if record is None:
                # Do not misclassify tenant/FK/check violations as a uniqueness
                # race.  A genuine race always leaves the scoped winner visible.
                raise
        else:
            return IdempotencyClaim(
                outcome=IdempotencyClaimOutcome.CLAIMED,
                record=_record_snapshot(record),
                claim_token=token,
                claim_generation=1,
            )

    if record.request_hash != request_hash:
        return IdempotencyClaim(
            outcome=IdempotencyClaimOutcome.KEY_REUSED,
            record=_record_snapshot(record),
        )
    if record.state == ApiIdempotencyState.COMPLETED:
        return IdempotencyClaim(
            outcome=IdempotencyClaimOutcome.REPLAY,
            record=_record_snapshot(record),
        )
    if (
        record.state == ApiIdempotencyState.PROCESSING
        and record.claim_expires_at is not None
        and _aware(record.claim_expires_at) > current_time
    ):
        return IdempotencyClaim(
            outcome=IdempotencyClaimOutcome.IN_PROGRESS,
            record=_record_snapshot(record),
        )

    claimed = _claim_existing(
        record,
        now=current_time,
        claim_ttl=claim_ttl,
        expires_at=expires_at,
    )
    session.flush()
    return claimed


def _owned_processing_record(
    session: Session,
    *,
    company_id: str,
    record_id: str,
    claim_token: str,
    claim_generation: int,
    now: datetime,
) -> ApiIdempotencyRecord:
    serialize_sqlite_writer(session)
    statement = select(ApiIdempotencyRecord).where(
        ApiIdempotencyRecord.id == record_id,
        ApiIdempotencyRecord.company_id == company_id,
    )
    record = session.scalar(_lock_statement(session, statement))
    if (
        record is None
        or record.state != ApiIdempotencyState.PROCESSING
        or record.claim_token != claim_token
        or record.claim_generation != claim_generation
        or record.claim_expires_at is None
        or _aware(record.claim_expires_at) <= now
    ):
        raise StaleIdempotencyClaimError("Idempotency processing claim is stale.")
    return record


def complete_idempotency(
    session: Session,
    *,
    company_id: str,
    record_id: str,
    claim_token: str,
    claim_generation: int,
    response_status: int,
    result_type: str | None = None,
    result_id: str | None = None,
    now: datetime | None = None,
) -> ApiIdempotencyRecord:
    current_time = _aware(now or _now())
    if not 100 <= response_status <= 599:
        raise ValueError("response_status must be a valid HTTP status.")
    if (result_type is None) != (result_id is None):
        raise ValueError("result_type and result_id must be supplied together.")
    record = _owned_processing_record(
        session,
        company_id=company_id,
        record_id=record_id,
        claim_token=claim_token,
        claim_generation=claim_generation,
        now=current_time,
    )
    record.state = ApiIdempotencyState.COMPLETED
    record.claim_token = None
    record.claim_expires_at = None
    record.response_status = response_status
    record.result_type = result_type
    record.result_id = result_id
    record.finished_at = current_time
    record.updated_at = current_time
    session.flush()
    return record


def fail_idempotency(
    session: Session,
    *,
    company_id: str,
    record_id: str,
    claim_token: str,
    claim_generation: int,
    response_status: int | None = None,
    now: datetime | None = None,
) -> ApiIdempotencyRecord:
    current_time = _aware(now or _now())
    if response_status is not None and not 100 <= response_status <= 599:
        raise ValueError("response_status must be a valid HTTP status.")
    record = _owned_processing_record(
        session,
        company_id=company_id,
        record_id=record_id,
        claim_token=claim_token,
        claim_generation=claim_generation,
        now=current_time,
    )
    record.state = ApiIdempotencyState.FAILED
    record.claim_token = None
    record.claim_expires_at = None
    record.response_status = response_status
    record.result_type = None
    record.result_id = None
    record.finished_at = current_time
    record.updated_at = current_time
    session.flush()
    return record


__all__ = (
    "CanonicalFilePart",
    "IdempotencyClaim",
    "IdempotencyClaimOutcome",
    "IdempotencyRecordSnapshot",
    "StaleIdempotencyClaimError",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "canonical_request_hash",
    "claim_idempotency",
    "complete_idempotency",
    "fail_idempotency",
    "idempotency_retention_for_operation",
)
