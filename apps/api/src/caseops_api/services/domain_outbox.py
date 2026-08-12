from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    DomainConsumerEffect,
    DomainConsumerEffectState,
    DomainOutboxEvent,
    DomainOutboxState,
)
from caseops_api.db.session import serialize_sqlite_writer
from caseops_api.services.audit import record_from_context
from caseops_api.services.idempotency import canonical_json_bytes, canonical_json_sha256
from caseops_api.services.session_context import SessionContext

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|password|passwd|secret|token|api[_-]?key|"
    r"private[_-]?key|session[_-]?id|raw[_-]?(?:body|content|document|prompt))",
    re.IGNORECASE,
)
_SENSITIVE_ERROR_VALUE = re.compile(
    r"(?i)(?:bearer\s+[^\s,;]+|(?:authorization|cookie|password|passwd|"
    r"secret|token|api[_-]?key|private[_-]?key)\s*[:=]\s*"
    r"(?:bearer\s+)?[^\s,;]+)"
)
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]+")
_MAX_PAYLOAD_BYTES = 65_536
_DEAD_LETTER_REASONS = {
    "consumer_permanent_failure",
    "operator_dead_letter",
    "poison_event",
    "retry_limit_exhausted",
    "schema_rejected",
}


@dataclass(frozen=True, slots=True)
class DomainEventContract:
    required_payload_fields: frozenset[str]
    consumers: tuple[str, ...]
    confidentiality: str
    aggregate_payload_field: str


# Runtime admission is deliberately code-owned. The matching governance
# catalog is validated separately; an arbitrary caller cannot invent an event
# name, schema version, consumer set, or confidentiality classification.
# ``required_payload_fields`` is exactly the catalogue payload schema. Company,
# time, correlation, aggregate, producer, and source identity are immutable
# envelope columns and must not be duplicated as payload contract fields.
_EVENT_CONTRACTS: dict[tuple[str, int], DomainEventContract] = {
    ("ip.legal_state.lifecycle_changed", 1): DomainEventContract(
        required_payload_fields=frozenset(
            {
                "target_type",
                "target_id",
                "from_state",
                "to_state",
                "lifecycle_version",
            }
        ),
        consumers=(
            "ip-portfolio-projection",
            "notification-intent-adapter",
            "operational-deadline-projection",
        ),
        confidentiality="privileged",
        aggregate_payload_field="target_id",
    ),
    ("ip.docket_event.recorded", 1): DomainEventContract(
        required_payload_fields=frozenset(
            {
                "ip_docket_event_id",
                "target_id",
                "event_type",
                "event_version",
                "source_evidence_id",
            }
        ),
        consumers=("access-filtered-timeline", "deadline-calculation-adapter"),
        confidentiality="privileged",
        aggregate_payload_field="ip_docket_event_id",
    ),
    ("ip.deadline.calculation_committed", 1): DomainEventContract(
        required_payload_fields=frozenset(
            {
                "ip_deadline_id",
                "target_id",
                "due_at",
                "rule_version_id",
                "engine_version",
                "calculation_version",
            }
        ),
        consumers=(
            "notification-intent-adapter",
            "operational-deadline-projection",
        ),
        confidentiality="privileged",
        aggregate_payload_field="ip_deadline_id",
    ),
    ("bulk_import.operation_state_changed", 1): DomainEventContract(
        required_payload_fields=frozenset(
            {
                "bulk_import_job_id",
                "from_state",
                "to_state",
                "operation_version",
                "safe_counts",
            }
        ),
        consumers=("audit-evidence", "bulk-operation-status"),
        confidentiality="confidential",
        aggregate_payload_field="bulk_import_job_id",
    ),
}


def domain_event_contract_snapshot() -> tuple[dict[str, object], ...]:
    """Expose a stable, detached view for governance admission checks."""

    return tuple(
        {
            "name": event_type,
            "version": version,
            "required_payload_fields": tuple(sorted(contract.required_payload_fields)),
            "consumers": contract.consumers,
            "confidentiality": contract.confidentiality,
            "aggregate_payload_field": contract.aggregate_payload_field,
        }
        for (event_type, version), contract in sorted(_EVENT_CONTRACTS.items())
    )


class OutboxEventKeyReusedError(RuntimeError):
    """A stable event key was reused for different immutable event data."""


class StaleOutboxLeaseError(RuntimeError):
    """The caller's event lease/fence no longer owns the row."""


class NonterminalConsumerEffectError(RuntimeError):
    """An outbox event cannot succeed while one of its effects is in flight."""


class ConsumerEffectKeyReusedError(RuntimeError):
    """A consumer effect identity was reused for a different event."""


class StaleConsumerEffectLeaseError(RuntimeError):
    """The caller's consumer-effect lease/fence no longer owns the row."""


class StaleDeadLetterDispositionError(RuntimeError):
    """The dead-letter row changed before an operator disposition was stored."""


class ConsumerEffectClaimOutcome(StrEnum):
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class DomainEventEnvelope:
    id: str
    company_id: str
    event_key: str
    event_type: str
    schema_version: int
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    payload_hash: str
    expected_consumers: tuple[str, ...]
    max_attempts: int


@dataclass(frozen=True, slots=True)
class EnqueuedDomainEvent:
    event: DomainEventEnvelope
    created: bool


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    event_id: str
    company_id: str
    event_key: str
    lease_token: str
    fence_version: int
    attempts: int


@dataclass(frozen=True, slots=True)
class ConsumerEffectClaim:
    outcome: ConsumerEffectClaimOutcome
    effect: DomainConsumerEffect
    lease_token: str | None = None
    fence_version: int | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _event_lock_statement(
    session: Session,
    statement: Select[tuple[DomainOutboxEvent]],
    *,
    skip_locked: bool = False,
) -> Select[tuple[DomainOutboxEvent]]:
    if session.get_bind().dialect.name == "postgresql":
        return statement.with_for_update(
            of=DomainOutboxEvent,
            skip_locked=skip_locked,
        )
    return statement


def _effect_lock_statement(
    session: Session,
    statement: Select[tuple[DomainConsumerEffect]],
) -> Select[tuple[DomainConsumerEffect]]:
    if session.get_bind().dialect.name == "postgresql":
        return statement.with_for_update(of=DomainConsumerEffect)
    return statement


def _required(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required.")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters.")
    return normalized


def _optional(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters.")
    return normalized


def _safe_error(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = _SENSITIVE_ERROR_VALUE.sub("[REDACTED]", value)
    sanitized = _CONTROL_CHARACTER.sub(" ", sanitized)
    sanitized = sanitized.strip()
    return sanitized[:500] or None


def _reject_sensitive_payload_keys(value: object, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and _SENSITIVE_KEY.search(key):
                raise ValueError(f"Domain event payload field {path}.{key} is not allowlisted.")
            _reject_sensitive_payload_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_payload_keys(nested, path=f"{path}[{index}]")


def _validate_contract_payload(
    payload: dict[str, object],
    *,
    contract: DomainEventContract,
    aggregate_id: str,
) -> None:
    payload_fields = set(payload)
    missing_fields = sorted(contract.required_payload_fields.difference(payload_fields))
    if missing_fields:
        raise ValueError(
            "Domain event payload is missing catalog-required fields: " + ", ".join(missing_fields)
        )
    _reject_sensitive_payload_keys(payload)
    unexpected_fields = sorted(payload_fields.difference(contract.required_payload_fields))
    if unexpected_fields:
        raise ValueError(
            "Domain event payload contains catalog-unadmitted fields: "
            + ", ".join(unexpected_fields)
        )

    version_fields = {
        "lifecycle_version",
        "event_version",
        "calculation_version",
        "operation_version",
    }
    for field, value in payload.items():
        if field in version_fields:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise TypeError(f"Domain event payload field {field} must be a version.")
        elif field == "safe_counts":
            if not isinstance(value, Mapping) or any(
                not isinstance(key, str)
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
                for key, count in value.items()
            ):
                raise TypeError("Domain event safe_counts must contain nonnegative integers.")
        elif field in contract.required_payload_fields and (
            not isinstance(value, str) or not value.strip()
        ):
            raise TypeError(f"Domain event payload field {field} must be a string.")

    if payload[contract.aggregate_payload_field] != aggregate_id:
        raise ValueError("Domain event aggregate identity does not match its payload.")


def _event_envelope(event: DomainOutboxEvent) -> DomainEventEnvelope:
    return DomainEventEnvelope(
        id=event.id,
        company_id=event.company_id,
        event_key=event.event_key,
        event_type=event.event_type,
        schema_version=event.schema_version,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        aggregate_version=event.aggregate_version,
        payload_hash=event.payload_hash,
        expected_consumers=tuple(event.expected_consumers_json),
        max_attempts=event.max_attempts,
    )


def _immutable_event_identity(event: DomainOutboxEvent) -> tuple[object, ...]:
    return (
        event.event_type,
        event.schema_version,
        event.aggregate_type,
        event.aggregate_id,
        event.aggregate_version,
        _aware(event.occurred_at),
        _aware(event.effective_at),
        event.source_command_id,
        event.source_event_id,
        event.producer,
        event.producer_revision,
        event.confidentiality,
        event.correlation_id,
        event.causation_id,
        event.payload_hash,
        tuple(event.expected_consumers_json),
        event.max_attempts,
    )


def _fence_processing_effects(
    session: Session,
    *,
    event: DomainOutboxEvent,
    now: datetime,
    error: str,
) -> None:
    """Terminalize children before their parent abandons an attempt."""

    statement = select(DomainConsumerEffect).where(
        DomainConsumerEffect.company_id == event.company_id,
        DomainConsumerEffect.outbox_event_id == event.id,
        DomainConsumerEffect.state == DomainConsumerEffectState.PROCESSING,
    )
    effects = list(session.scalars(_effect_lock_statement(session, statement)).all())
    safe_error = _safe_error(error) or "Parent outbox attempt was fenced."
    for effect in effects:
        effect.state = DomainConsumerEffectState.FAILED
        effect.lease_owner = None
        effect.lease_token = None
        effect.lease_expires_at = None
        effect.fence_version += 1
        effect.outbox_fence_version = event.fence_version
        effect.result_type = None
        effect.result_id = None
        effect.result_hash = None
        effect.last_error_redacted = safe_error
        effect.completed_at = None
        effect.failed_at = now
        effect.updated_at = now


def enqueue_domain_event(
    session: Session,
    *,
    company_id: str,
    event_key: str,
    event_type: str,
    schema_version: int,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
    occurred_at: datetime,
    effective_at: datetime,
    source_command_id: str | None,
    source_event_id: str | None,
    producer: str,
    confidentiality: str,
    correlation_id: str,
    payload: dict[str, object],
    producer_revision: str | None = None,
    causation_id: str | None = None,
    max_attempts: int = 5,
    now: datetime | None = None,
) -> EnqueuedDomainEvent:
    """Insert one immutable event in the caller's transaction.

    The function deliberately does not commit or invoke a consumer.
    """

    current_time = _aware(now or _now())
    company_id = _required(company_id, field="company_id", maximum=36)
    event_key = _required(event_key, field="event_key", maximum=200)
    event_type = _required(event_type, field="event_type", maximum=120)
    aggregate_type = _required(aggregate_type, field="aggregate_type", maximum=80)
    aggregate_id = _required(aggregate_id, field="aggregate_id", maximum=160)
    producer = _required(producer, field="producer", maximum=120)
    correlation_id = _required(correlation_id, field="correlation_id", maximum=160)
    source_command_id = _optional(source_command_id, field="source_command_id", maximum=160)
    source_event_id = _optional(source_event_id, field="source_event_id", maximum=160)
    producer_revision = _optional(producer_revision, field="producer_revision", maximum=64)
    causation_id = _optional(causation_id, field="causation_id", maximum=160)
    if source_command_id is None and source_event_id is None:
        raise ValueError("A source command or source event ID is required.")
    if schema_version <= 0:
        raise ValueError("schema_version must be positive.")
    if aggregate_version < 0:
        raise ValueError("aggregate_version cannot be negative.")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive.")
    if confidentiality not in {"internal", "confidential", "privileged"}:
        raise ValueError("Unsupported event confidentiality.")
    if not isinstance(payload, dict):
        raise TypeError("Domain event payload must be a JSON object.")

    contract = _EVENT_CONTRACTS.get((event_type, schema_version))
    if contract is None:
        raise ValueError("Event type and schema version are not admitted by the catalog.")
    if confidentiality != contract.confidentiality:
        raise ValueError("Event confidentiality does not match the catalog contract.")
    occurred_at = _aware(occurred_at)
    effective_at = _aware(effective_at)
    _validate_contract_payload(
        payload,
        contract=contract,
        aggregate_id=aggregate_id,
    )
    payload_bytes = canonical_json_bytes(payload)
    if len(payload_bytes) > _MAX_PAYLOAD_BYTES:
        raise ValueError(f"Domain event payload exceeds {_MAX_PAYLOAD_BYTES} canonical bytes.")
    payload_hash = canonical_json_sha256(payload)
    persisted_payload = json.loads(payload_bytes.decode("utf-8"))
    expected_consumers = sorted(set(contract.consumers))
    candidate = DomainOutboxEvent(
        company_id=company_id,
        event_key=event_key,
        event_type=event_type,
        schema_version=schema_version,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        occurred_at=occurred_at,
        effective_at=effective_at,
        source_command_id=source_command_id,
        source_event_id=source_event_id,
        producer=producer,
        producer_revision=producer_revision,
        confidentiality=confidentiality,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload_hash=payload_hash,
        payload_json=persisted_payload,
        expected_consumers_json=expected_consumers,
        state=DomainOutboxState.QUEUED,
        attempts=0,
        max_attempts=max_attempts,
        fence_version=0,
        created_at=current_time,
        updated_at=current_time,
    )
    serialize_sqlite_writer(session)
    statement = select(DomainOutboxEvent).where(
        DomainOutboxEvent.company_id == company_id,
        DomainOutboxEvent.event_key == event_key,
    )
    existing = session.scalar(_event_lock_statement(session, statement))
    if existing is None:
        if session.get_bind().dialect.name == "sqlite":
            # Serialization was acquired before the absent-row lookup.  Avoid
            # a SAVEPOINT as the first SQLite write because a deferred driver
            # BEGIN can make RELEASE SAVEPOINT escape the caller's rollback.
            session.add(candidate)
            session.flush()
            return EnqueuedDomainEvent(event=_event_envelope(candidate), created=True)
        try:
            with session.begin_nested():
                session.add(candidate)
                session.flush()
        except IntegrityError:
            existing = session.scalar(_event_lock_statement(session, statement))
            if existing is None:
                # A genuine event-key race leaves its winner visible.  Preserve
                # unrelated FK/check failures instead of disguising them.
                raise
        else:
            return EnqueuedDomainEvent(event=_event_envelope(candidate), created=True)

    if _immutable_event_identity(existing) != _immutable_event_identity(candidate):
        raise OutboxEventKeyReusedError(
            "Domain event key is already bound to different immutable data."
        )
    return EnqueuedDomainEvent(event=_event_envelope(existing), created=False)


def claim_outbox_events(
    session: Session,
    *,
    lease_owner: str,
    limit: int = 25,
    lease_for: timedelta = timedelta(minutes=5),
    company_id: str | None = None,
    now: datetime | None = None,
) -> list[OutboxClaim]:
    """Claim a disjoint due batch; PostgreSQL uses ``SKIP LOCKED``."""

    current_time = _aware(now or _now())
    lease_owner = _required(lease_owner, field="lease_owner", maximum=120)
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200.")
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive.")

    serialize_sqlite_writer(session)

    eligible = or_(
        and_(
            DomainOutboxEvent.state.in_(
                (DomainOutboxState.QUEUED, DomainOutboxState.RETRY_SCHEDULED)
            ),
            or_(
                DomainOutboxEvent.next_attempt_at.is_(None),
                DomainOutboxEvent.next_attempt_at <= current_time,
            ),
        ),
        and_(
            DomainOutboxEvent.state == DomainOutboxState.PROCESSING,
            DomainOutboxEvent.lease_expires_at <= current_time,
        ),
    )
    statement = (
        select(DomainOutboxEvent)
        .where(eligible)
        .order_by(
            func.coalesce(
                DomainOutboxEvent.next_attempt_at,
                DomainOutboxEvent.created_at,
            ),
            DomainOutboxEvent.created_at,
            DomainOutboxEvent.id,
        )
        .limit(limit)
    )
    if company_id is not None:
        statement = statement.where(DomainOutboxEvent.company_id == company_id)
    rows = list(session.scalars(_event_lock_statement(session, statement, skip_locked=True)).all())
    claims: list[OutboxClaim] = []
    for event in rows:
        if event.attempts >= event.max_attempts:
            # A worker may disappear after claiming the final permitted
            # attempt.  Once that lease expires, fence it and converge the row
            # to dead letter instead of leaving it stuck in ``processing``.
            event.state = DomainOutboxState.DEAD_LETTER
            event.lease_owner = None
            event.lease_token = None
            event.lease_expires_at = None
            event.next_attempt_at = None
            event.completed_at = None
            event.dead_lettered_at = current_time
            event.dead_letter_reason = "retry_limit_exhausted"
            event.dead_letter_resolution = "pending"
            event.dead_letter_resolved_at = None
            event.fence_version += 1
            if event.last_error_redacted is None:
                event.last_error_redacted = "Worker lease expired at retry limit."
            event.updated_at = current_time
            _fence_processing_effects(
                session,
                event=event,
                now=current_time,
                error="Parent outbox event reached its retry limit.",
            )
            continue
        token = uuid4().hex
        event.state = DomainOutboxState.PROCESSING
        event.attempts += 1
        event.fence_version += 1
        event.lease_owner = lease_owner
        event.lease_token = token
        event.lease_expires_at = current_time + lease_for
        event.next_attempt_at = None
        event.dead_letter_reason = None
        event.dead_letter_resolution = None
        event.dead_letter_resolved_at = None
        event.updated_at = current_time
        claims.append(
            OutboxClaim(
                event_id=event.id,
                company_id=event.company_id,
                event_key=event.event_key,
                lease_token=token,
                fence_version=event.fence_version,
                attempts=event.attempts,
            )
        )
    session.flush()
    return claims


def _owned_outbox_event(
    session: Session,
    *,
    company_id: str,
    event_id: str,
    lease_token: str,
    fence_version: int,
    now: datetime,
) -> DomainOutboxEvent:
    serialize_sqlite_writer(session)
    statement = select(DomainOutboxEvent).where(
        DomainOutboxEvent.id == event_id,
        DomainOutboxEvent.company_id == company_id,
    )
    event = session.scalar(_event_lock_statement(session, statement))
    if (
        event is None
        or event.state != DomainOutboxState.PROCESSING
        or event.lease_token != lease_token
        or event.fence_version != fence_version
        or event.lease_expires_at is None
        or _aware(event.lease_expires_at) <= now
    ):
        raise StaleOutboxLeaseError("Outbox lease or fencing token is stale.")
    return event


def renew_outbox_lease(
    session: Session,
    *,
    claim: OutboxClaim,
    lease_for: timedelta,
    now: datetime | None = None,
) -> DomainOutboxEvent:
    current_time = _aware(now or _now())
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive.")
    event = _owned_outbox_event(
        session,
        company_id=claim.company_id,
        event_id=claim.event_id,
        lease_token=claim.lease_token,
        fence_version=claim.fence_version,
        now=current_time,
    )
    event.lease_expires_at = current_time + lease_for
    event.updated_at = current_time
    session.flush()
    return event


def complete_outbox_event(
    session: Session,
    *,
    claim: OutboxClaim,
    now: datetime | None = None,
) -> DomainOutboxEvent:
    current_time = _aware(now or _now())
    event = _owned_outbox_event(
        session,
        company_id=claim.company_id,
        event_id=claim.event_id,
        lease_token=claim.lease_token,
        fence_version=claim.fence_version,
        now=current_time,
    )
    effects = list(
        session.scalars(
            _effect_lock_statement(
                session,
                select(DomainConsumerEffect).where(
                    DomainConsumerEffect.company_id == event.company_id,
                    DomainConsumerEffect.outbox_event_id == event.id,
                ),
            )
        ).all()
    )
    expected_consumers = set(event.expected_consumers_json)
    effect_by_consumer = {effect.consumer_name: effect for effect in effects}
    actual_consumers = set(effect_by_consumer)
    if actual_consumers != expected_consumers or any(
        effect_by_consumer[consumer].state != DomainConsumerEffectState.COMPLETED
        for consumer in expected_consumers.intersection(actual_consumers)
    ):
        missing = len(expected_consumers.difference(actual_consumers))
        nonterminal = sum(
            effect.state != DomainConsumerEffectState.COMPLETED
            for effect in effects
            if effect.consumer_name in expected_consumers
        )
        unexpected = len(actual_consumers.difference(expected_consumers))
        raise NonterminalConsumerEffectError(
            "Outbox event consumer set is incomplete "
            f"(missing={missing}, nonterminal={nonterminal}, unexpected={unexpected})."
        )
    event.state = DomainOutboxState.SUCCEEDED
    event.lease_owner = None
    event.lease_token = None
    event.lease_expires_at = None
    event.next_attempt_at = None
    event.completed_at = current_time
    event.dead_lettered_at = None
    event.dead_letter_reason = None
    event.dead_letter_resolution = None
    event.dead_letter_resolved_at = None
    event.last_error_redacted = None
    event.updated_at = current_time
    session.flush()
    return event


def record_outbox_failure(
    session: Session,
    *,
    claim: OutboxClaim,
    last_error_redacted: str,
    retry_at: datetime | None,
    dead_letter_reason: str = "retry_limit_exhausted",
    now: datetime | None = None,
) -> DomainOutboxEvent:
    current_time = _aware(now or _now())
    error = _safe_error(last_error_redacted)
    if error is None:
        raise ValueError("A redacted failure description is required.")
    reason = _required(dead_letter_reason, field="dead_letter_reason", maximum=160)
    if reason not in _DEAD_LETTER_REASONS:
        raise ValueError("dead_letter_reason is not an admitted safe reason code.")
    event = _owned_outbox_event(
        session,
        company_id=claim.company_id,
        event_id=claim.event_id,
        lease_token=claim.lease_token,
        fence_version=claim.fence_version,
        now=current_time,
    )
    event.lease_owner = None
    event.lease_token = None
    event.lease_expires_at = None
    event.last_error_redacted = error
    event.completed_at = None
    if retry_at is not None and event.attempts < event.max_attempts:
        retry_at = _aware(retry_at)
        if retry_at <= current_time:
            raise ValueError("retry_at must be in the future.")
        event.state = DomainOutboxState.RETRY_SCHEDULED
        event.next_attempt_at = retry_at
        event.dead_lettered_at = None
        event.dead_letter_reason = None
        event.dead_letter_resolution = None
        event.dead_letter_resolved_at = None
    else:
        event.state = DomainOutboxState.DEAD_LETTER
        event.next_attempt_at = None
        event.dead_lettered_at = current_time
        event.dead_letter_reason = reason
        event.dead_letter_resolution = "pending"
        event.dead_letter_resolved_at = None
        event.fence_version += 1
    _fence_processing_effects(
        session,
        event=event,
        now=current_time,
        error="Parent outbox attempt failed and fenced its consumer effects.",
    )
    event.updated_at = current_time
    session.flush()
    return event


def _dead_letter_for_operator(
    session: Session,
    *,
    context: SessionContext,
    event_id: str,
    expected_fence_version: int,
) -> DomainOutboxEvent:
    membership = context.membership
    if (
        membership.company_id != context.company.id
        or membership.user_id != context.user.id
        or not membership.is_active
        or membership.role not in {"owner", "admin"}
    ):
        raise PermissionError("An active tenant owner or admin must disposition dead letters.")
    serialize_sqlite_writer(session)
    statement = select(DomainOutboxEvent).where(
        DomainOutboxEvent.id == event_id,
        DomainOutboxEvent.company_id == context.company.id,
    )
    event = session.scalar(_event_lock_statement(session, statement))
    if (
        event is None
        or event.state != DomainOutboxState.DEAD_LETTER
        or event.fence_version != expected_fence_version
    ):
        raise StaleDeadLetterDispositionError(
            "Dead-letter event is missing, no longer terminal, or has a stale version."
        )
    return event


def replay_dead_letter_event(
    session: Session,
    *,
    context: SessionContext,
    event_id: str,
    expected_fence_version: int,
    reason: str,
    now: datetime | None = None,
) -> DomainOutboxEvent:
    """Requeue one tenant-owned dead letter and append operator evidence."""

    current_time = _aware(now or _now())
    safe_reason = _safe_error(reason)
    if safe_reason is None:
        raise ValueError("A bounded replay reason is required.")
    event = _dead_letter_for_operator(
        session,
        context=context,
        event_id=event_id,
        expected_fence_version=expected_fence_version,
    )
    previous_reason = event.dead_letter_reason
    previous_attempts = event.attempts
    previous_fence = event.fence_version
    event.fence_version += 1
    _fence_processing_effects(
        session,
        event=event,
        now=current_time,
        error="Operator replay fenced a stale consumer effect.",
    )
    event.state = DomainOutboxState.QUEUED
    event.attempts = 0
    event.next_attempt_at = None
    event.lease_owner = None
    event.lease_token = None
    event.lease_expires_at = None
    event.last_error_redacted = None
    event.dead_letter_reason = None
    event.dead_lettered_at = None
    event.dead_letter_resolution = None
    event.dead_letter_resolved_at = None
    event.completed_at = None
    event.updated_at = current_time
    record_from_context(
        session,
        context,
        action="domain_outbox.dead_letter.replayed",
        target_type="domain_outbox_event",
        target_id=event.id,
        metadata={
            "reason": safe_reason,
            "previous_dead_letter_reason": previous_reason,
            "previous_attempts": previous_attempts,
            "previous_fence_version": previous_fence,
            "new_fence_version": event.fence_version,
            "event_type": event.event_type,
        },
    )
    session.flush()
    return event


def resolve_dead_letter_event(
    session: Session,
    *,
    context: SessionContext,
    event_id: str,
    expected_fence_version: int,
    resolution: str,
    reason: str,
    now: datetime | None = None,
) -> DomainOutboxEvent:
    """Persist an audited ``ignored`` or ``resolved`` operator decision."""

    if resolution not in {"ignored", "resolved"}:
        raise ValueError("resolution must be ignored or resolved.")
    current_time = _aware(now or _now())
    safe_reason = _safe_error(reason)
    if safe_reason is None:
        raise ValueError("A bounded dead-letter resolution reason is required.")
    event = _dead_letter_for_operator(
        session,
        context=context,
        event_id=event_id,
        expected_fence_version=expected_fence_version,
    )
    previous_resolution = event.dead_letter_resolution
    previous_fence = event.fence_version
    event.dead_letter_resolution = resolution
    event.dead_letter_resolved_at = current_time
    event.fence_version += 1
    event.updated_at = current_time
    record_from_context(
        session,
        context,
        action=f"domain_outbox.dead_letter.{resolution}",
        target_type="domain_outbox_event",
        target_id=event.id,
        metadata={
            "reason": safe_reason,
            "previous_resolution": previous_resolution,
            "previous_fence_version": previous_fence,
            "new_fence_version": event.fence_version,
            "event_type": event.event_type,
        },
    )
    session.flush()
    return event


def _claim_effect_row(
    effect: DomainConsumerEffect,
    *,
    consumer_version: str,
    event: DomainOutboxEvent,
    lease_owner: str,
    lease_for: timedelta,
    now: datetime,
) -> ConsumerEffectClaim:
    token = uuid4().hex
    effect.consumer_version = consumer_version
    effect.state = DomainConsumerEffectState.PROCESSING
    effect.attempts += 1
    effect.outbox_fence_version = event.fence_version
    effect.lease_owner = lease_owner
    effect.lease_token = token
    effect.lease_expires_at = min(now + lease_for, _aware(event.lease_expires_at))
    effect.fence_version += 1
    effect.result_type = None
    effect.result_id = None
    effect.result_hash = None
    effect.last_error_redacted = None
    effect.completed_at = None
    effect.failed_at = None
    effect.updated_at = now
    return ConsumerEffectClaim(
        outcome=ConsumerEffectClaimOutcome.CLAIMED,
        effect=effect,
        lease_token=token,
        fence_version=effect.fence_version,
    )


def claim_consumer_effect(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    consumer_name: str,
    consumer_version: str,
    effect_key: str,
    lease_owner: str,
    lease_for: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
) -> ConsumerEffectClaim:
    """Claim a per-consumer effect while the caller owns its source event."""

    current_time = _aware(now or _now())
    consumer_name = _required(consumer_name, field="consumer_name", maximum=120)
    consumer_version = _required(consumer_version, field="consumer_version", maximum=64)
    effect_key = _required(effect_key, field="effect_key", maximum=200)
    lease_owner = _required(lease_owner, field="lease_owner", maximum=120)
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive.")
    event = _owned_outbox_event(
        session,
        company_id=outbox_claim.company_id,
        event_id=outbox_claim.event_id,
        lease_token=outbox_claim.lease_token,
        fence_version=outbox_claim.fence_version,
        now=current_time,
    )
    if consumer_name not in set(event.expected_consumers_json):
        raise ValueError("Consumer is not admitted by this event's catalog snapshot.")

    statement = select(DomainConsumerEffect).where(
        DomainConsumerEffect.company_id == event.company_id,
        DomainConsumerEffect.consumer_name == consumer_name,
        or_(
            DomainConsumerEffect.effect_key == effect_key,
            DomainConsumerEffect.outbox_event_id == event.id,
        ),
    )
    matches = list(session.scalars(_effect_lock_statement(session, statement)).all())
    if len(matches) > 1:
        raise ConsumerEffectKeyReusedError(
            "Consumer event and effect identities resolve to different rows."
        )
    effect = matches[0] if matches else None
    if effect is None:
        token = uuid4().hex
        effect = DomainConsumerEffect(
            company_id=event.company_id,
            outbox_event_id=event.id,
            consumer_name=consumer_name,
            consumer_version=consumer_version,
            effect_key=effect_key,
            state=DomainConsumerEffectState.PROCESSING,
            attempts=1,
            outbox_fence_version=event.fence_version,
            lease_owner=lease_owner,
            lease_token=token,
            lease_expires_at=min(
                current_time + lease_for,
                _aware(event.lease_expires_at),
            ),
            fence_version=1,
            created_at=current_time,
            updated_at=current_time,
        )
        if session.get_bind().dialect.name == "sqlite":
            session.add(effect)
            session.flush()
            return ConsumerEffectClaim(
                outcome=ConsumerEffectClaimOutcome.CLAIMED,
                effect=effect,
                lease_token=token,
                fence_version=1,
            )
        try:
            with session.begin_nested():
                session.add(effect)
                session.flush()
        except IntegrityError:
            matches = list(session.scalars(_effect_lock_statement(session, statement)).all())
            if len(matches) != 1:
                # A genuine uniqueness race leaves exactly one matching effect.
                # Propagate tenant/FK/check violations unchanged.
                raise
            effect = matches[0]
        else:
            return ConsumerEffectClaim(
                outcome=ConsumerEffectClaimOutcome.CLAIMED,
                effect=effect,
                lease_token=token,
                fence_version=1,
            )

    if effect.outbox_event_id != event.id or effect.effect_key != effect_key:
        raise ConsumerEffectKeyReusedError(
            "Consumer effect key is already bound to a different event."
        )
    if effect.state == DomainConsumerEffectState.COMPLETED:
        return ConsumerEffectClaim(
            outcome=ConsumerEffectClaimOutcome.REPLAY,
            effect=effect,
        )
    if (
        effect.state == DomainConsumerEffectState.PROCESSING
        and effect.outbox_fence_version == event.fence_version
        and effect.lease_expires_at is not None
        and _aware(effect.lease_expires_at) > current_time
    ):
        return ConsumerEffectClaim(
            outcome=ConsumerEffectClaimOutcome.IN_PROGRESS,
            effect=effect,
        )
    claimed = _claim_effect_row(
        effect,
        consumer_version=consumer_version,
        event=event,
        lease_owner=lease_owner,
        lease_for=lease_for,
        now=current_time,
    )
    session.flush()
    return claimed


def _owned_consumer_effect(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    effect_id: str,
    effect_lease_token: str,
    effect_fence_version: int,
    now: datetime,
) -> tuple[DomainOutboxEvent, DomainConsumerEffect]:
    event = _owned_outbox_event(
        session,
        company_id=outbox_claim.company_id,
        event_id=outbox_claim.event_id,
        lease_token=outbox_claim.lease_token,
        fence_version=outbox_claim.fence_version,
        now=now,
    )
    statement = select(DomainConsumerEffect).where(
        DomainConsumerEffect.id == effect_id,
        DomainConsumerEffect.company_id == event.company_id,
        DomainConsumerEffect.outbox_event_id == event.id,
    )
    effect = session.scalar(_effect_lock_statement(session, statement))
    if (
        effect is None
        or effect.state != DomainConsumerEffectState.PROCESSING
        or effect.lease_token != effect_lease_token
        or effect.fence_version != effect_fence_version
        or effect.outbox_fence_version != event.fence_version
        or effect.lease_expires_at is None
        or _aware(effect.lease_expires_at) <= now
    ):
        raise StaleConsumerEffectLeaseError("Consumer effect lease or fencing token is stale.")
    return event, effect


def renew_consumer_effect_lease(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    effect_id: str,
    effect_lease_token: str,
    effect_fence_version: int,
    lease_for: timedelta,
    now: datetime | None = None,
) -> DomainConsumerEffect:
    """Renew one owned effect without outliving its source-event lease."""

    current_time = _aware(now or _now())
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive.")
    event, effect = _owned_consumer_effect(
        session,
        outbox_claim=outbox_claim,
        effect_id=effect_id,
        effect_lease_token=effect_lease_token,
        effect_fence_version=effect_fence_version,
        now=current_time,
    )
    event_lease_expires_at = event.lease_expires_at
    if event_lease_expires_at is None:
        raise StaleConsumerEffectLeaseError(
            "Source-event lease expired before consumer-effect renewal."
        )
    effect.lease_expires_at = min(
        current_time + lease_for,
        _aware(event_lease_expires_at),
    )
    effect.updated_at = current_time
    session.flush()
    return effect


def complete_consumer_effect(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    effect_id: str,
    effect_lease_token: str,
    effect_fence_version: int,
    result_type: str | None = None,
    result_id: str | None = None,
    result_hash: str | None = None,
    now: datetime | None = None,
) -> DomainConsumerEffect:
    current_time = _aware(now or _now())
    if (result_type is None) != (result_id is None):
        raise ValueError("result_type and result_id must be supplied together.")
    if result_hash is not None and not _SHA256.fullmatch(result_hash):
        raise ValueError("result_hash must be a lowercase SHA-256 digest.")
    _, effect = _owned_consumer_effect(
        session,
        outbox_claim=outbox_claim,
        effect_id=effect_id,
        effect_lease_token=effect_lease_token,
        effect_fence_version=effect_fence_version,
        now=current_time,
    )
    effect.state = DomainConsumerEffectState.COMPLETED
    effect.lease_owner = None
    effect.lease_token = None
    effect.lease_expires_at = None
    effect.result_type = result_type
    effect.result_id = result_id
    effect.result_hash = result_hash
    effect.last_error_redacted = None
    effect.completed_at = current_time
    effect.failed_at = None
    effect.updated_at = current_time
    session.flush()
    return effect


def fail_consumer_effect(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    effect_id: str,
    effect_lease_token: str,
    effect_fence_version: int,
    last_error_redacted: str,
    now: datetime | None = None,
) -> DomainConsumerEffect:
    current_time = _aware(now or _now())
    error = _safe_error(last_error_redacted)
    if error is None:
        raise ValueError("A redacted failure description is required.")
    _, effect = _owned_consumer_effect(
        session,
        outbox_claim=outbox_claim,
        effect_id=effect_id,
        effect_lease_token=effect_lease_token,
        effect_fence_version=effect_fence_version,
        now=current_time,
    )
    effect.state = DomainConsumerEffectState.FAILED
    effect.lease_owner = None
    effect.lease_token = None
    effect.lease_expires_at = None
    effect.result_type = None
    effect.result_id = None
    effect.result_hash = None
    effect.last_error_redacted = error
    effect.completed_at = None
    effect.failed_at = current_time
    effect.updated_at = current_time
    session.flush()
    return effect


__all__ = (
    "ConsumerEffectClaim",
    "ConsumerEffectClaimOutcome",
    "ConsumerEffectKeyReusedError",
    "DomainEventEnvelope",
    "EnqueuedDomainEvent",
    "NonterminalConsumerEffectError",
    "OutboxClaim",
    "OutboxEventKeyReusedError",
    "StaleConsumerEffectLeaseError",
    "StaleDeadLetterDispositionError",
    "StaleOutboxLeaseError",
    "claim_consumer_effect",
    "claim_outbox_events",
    "complete_consumer_effect",
    "complete_outbox_event",
    "domain_event_contract_snapshot",
    "enqueue_domain_event",
    "fail_consumer_effect",
    "record_outbox_failure",
    "replay_dead_letter_event",
    "resolve_dead_letter_event",
    "renew_consumer_effect_lease",
    "renew_outbox_lease",
)
