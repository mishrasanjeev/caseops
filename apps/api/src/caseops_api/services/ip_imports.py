"""IPLF-032A bulk IP portfolio import (UJ-02).

Ownership: `bulk_import_jobs` is the **neutral** import owner tagged by domain;
`ip_import_rows` is the typed IP staging table. The legacy
`matter_bulk_import_jobs` and `employee_bulk_import_jobs` owners are untouched
and remain canonical for their domains. ARCH-OPS-23 forbids an IP-specific job
table, so no such table is introduced here, and Matter row-commit logic is not
reused as generic orchestration.

Commit materialises records through the existing `create_ip_docket` writer
rather than inserting docket rows directly.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from secrets import token_hex
from threading import Lock
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    BulkImportJob,
    IpAsset,
    IpDocketRecord,
    IpIdentifier,
    IpImportRow,
    Matter,
    TrademarkApplication,
)
from caseops_api.schemas.ip_imports import (
    IpImportCommitRequest,
    IpImportCommitResponse,
    IpImportJobCreateRequest,
    IpImportJobRecord,
    IpImportPreviewResponse,
    IpImportReconciliationRequest,
    IpImportRowRecord,
)
from caseops_api.schemas.ip_operations import IpDocketCreateRequest
from caseops_api.schemas.ip_records import (
    IpApplicationNumberCreate,
    IpAssetCreateRequest,
    TrademarkApplicationCreateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.csv_security import csv_safe_mapping
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.ip_operations import create_ip_docket
from caseops_api.services.ip_records import create_ip_asset, create_trademark_application
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

DOMAIN = "ip_trademark"
PREVIEW_TTL = timedelta(minutes=30)
REQUIRED_FIELDS = ("title", "mark_text", "class_number", "applicant_name")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
IMPORT_MATERIALIZATION_ACTION = "ip_docket.source_materialized"


@dataclass
class _LocalLockEntry:
    lock: Lock
    users: int = 0


_LOCAL_IMPORT_LOCKS_GUARD = Lock()
_LOCAL_IMPORT_LOCKS: dict[str, _LocalLockEntry] = {}


@contextmanager
def _local_import_locks(resources: tuple[str, ...]) -> Iterator[None]:
    """Serialize SQLite/local import tests across the writer's inner commits."""

    entries: list[tuple[str, _LocalLockEntry]] = []
    with _LOCAL_IMPORT_LOCKS_GUARD:
        for resource in resources:
            entry = _LOCAL_IMPORT_LOCKS.get(resource)
            if entry is None:
                entry = _LocalLockEntry(lock=Lock())
                _LOCAL_IMPORT_LOCKS[resource] = entry
            entry.users += 1
            entries.append((resource, entry))

    acquired: list[tuple[str, _LocalLockEntry]] = []
    try:
        for resource, entry in entries:
            entry.lock.acquire()
            acquired.append((resource, entry))
        yield
    finally:
        for _resource, entry in reversed(acquired):
            entry.lock.release()
        with _LOCAL_IMPORT_LOCKS_GUARD:
            for resource, entry in entries:
                entry.users -= 1
                if entry.users == 0 and _LOCAL_IMPORT_LOCKS.get(resource) is entry:
                    del _LOCAL_IMPORT_LOCKS[resource]


@contextmanager
def _import_commit_locks(session: Session, *resources: str) -> Iterator[None]:
    """Hold import locks across the canonical writer's transaction boundaries.

    ``create_ip_docket`` intentionally commits each accepted row. A normal
    ``FOR UPDATE`` lock therefore protects only the first row and used to let a
    concurrent commit materialise the same remaining rows. PostgreSQL advisory
    transaction locks live on a dedicated connection, so they remain held while
    the request session commits its row transactions. SQLite is local/test-only
    and uses the equivalent in-process keyed locks.
    """

    ordered = tuple(sorted(set(resources)))
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        engine = getattr(bind, "engine", bind)
        with engine.connect() as lock_connection, lock_connection.begin():
            for resource in ordered:
                lock_connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:resource, 0))"),
                    {"resource": resource},
                )
            yield
        return

    with _local_import_locks(ordered):
        yield


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _neutralize(value: Any) -> Any:
    """Formula-injection protection for spreadsheet round-trips.

    A leading formula trigger is prefixed so a re-exported cell is inert in
    Excel/Sheets. The displayed value keeps its original characters.
    """

    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _validate_row(
    session: Session,
    *,
    context: SessionContext,
    values: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    normalized: dict[str, Any] = {}

    for field in REQUIRED_FIELDS:
        raw = values.get(field)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            errors.append({"field": field, "code": "required"})
            continue
        normalized[field] = _neutralize(raw.strip() if isinstance(raw, str) else raw)

    class_number = normalized.get("class_number")
    if class_number is not None:
        try:
            parsed = int(class_number)
        except (TypeError, ValueError):
            errors.append({"field": "class_number", "code": "not_an_integer"})
        else:
            if not 1 <= parsed <= 45:
                errors.append({"field": "class_number", "code": "out_of_range"})
            else:
                normalized["class_number"] = parsed

    for field, default in (("jurisdiction", "IN"), ("office", "IP India")):
        raw = values.get(field)
        normalized[field] = (
            _neutralize(raw.strip()) if isinstance(raw, str) and raw.strip() else default
        )
    for field in ("specification", "application_number", "representation_kind", "agent_name"):
        raw = values.get(field)
        if isinstance(raw, str) and raw.strip():
            normalized[field] = _neutralize(raw.strip())

    matter_id = values.get("matter_id")
    if matter_id:
        matter = session.scalar(
            select(Matter).where(
                Matter.id == str(matter_id),
                Matter.company_id == context.company.id,
            )
        )
        if matter is None:
            # UJ-02-EXC-04: an id belonging to another tenant and an id that
            # does not exist produce the identical error. Nothing discloses
            # that the referenced record exists elsewhere.
            errors.append({"field": "matter_id", "code": "unknown_reference"})
        else:
            normalized["matter_id"] = matter.id

    return normalized, errors


def _duplicate_candidates(
    session: Session,
    *,
    context: SessionContext,
    normalized: dict[str, Any],
) -> list[dict[str, Any]]:
    application_number = normalized.get("application_number")
    exact_identifier_dockets: set[str] = set()
    if isinstance(application_number, str):
        exact_identifier_dockets = set(
            session.scalars(
                select(IpIdentifier.docket_id).where(
                    IpIdentifier.company_id == context.company.id,
                    IpIdentifier.identifier_kind == "application",
                    IpIdentifier.normalized_value == normalize_ip_identifier(application_number),
                    IpIdentifier.effective_until.is_(None),
                )
            ).all()
        )
    title = str(normalized.get("mark_text") or normalized.get("title") or "").strip()
    statement = (
        select(IpDocketRecord, IpAsset)
        .outerjoin(
            IpAsset,
            (IpAsset.docket_id == IpDocketRecord.id)
            & (IpAsset.company_id == IpDocketRecord.company_id),
        )
        .where(
            IpDocketRecord.company_id == context.company.id,
            visible_ip_dockets_filter(session, context=context),
            IpDocketRecord.is_active.is_(True),
            or_(
                IpDocketRecord.id.in_(exact_identifier_dockets),
                func.lower(IpDocketRecord.title) == title.casefold(),
                func.lower(func.coalesce(IpAsset.title, "")) == title.casefold(),
            ),
        )
        .order_by(IpDocketRecord.updated_at.desc())
        .limit(10)
    )
    candidates = []
    for docket, asset in session.execute(statement):
        reasons = []
        if docket.id in exact_identifier_dockets:
            reasons.append("exact_application_number")
        if title and (docket.title.casefold() == title.casefold()):
            reasons.append("exact_mark")
        if title and asset and asset.title.casefold() == title.casefold():
            reasons.append("exact_mark")
        candidates.append(
            {
                "docket_id": docket.id,
                "title": asset.title if asset else docket.title,
                "match_reasons": sorted(set(reasons)),
            }
        )
    return candidates


def _staged_duplicate_candidates(rows: list[IpImportRow]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[tuple[str, object], list[IpImportRow]] = {}
    for row in rows:
        normalized = row.normalized_json or {}
        application_number = normalized.get("application_number")
        if isinstance(application_number, str):
            key = ("application_number", normalize_ip_identifier(application_number))
        else:
            key = (
                "mark_class",
                (
                    str(normalized.get("mark_text", "")).casefold(),
                    normalized.get("class_number"),
                ),
            )
        groups.setdefault(key, []).append(row)
    result: dict[str, list[dict[str, Any]]] = {}
    for grouped in groups.values():
        if len(grouped) < 2:
            continue
        for row in grouped:
            result[row.id] = [
                {
                    "staged_row_id": other.id,
                    "row_number": other.row_number,
                    "title": (other.normalized_json or {}).get("title"),
                    "match_reasons": ["same_import"],
                }
                for other in grouped
                if other.id != row.id
            ]
    return result


def _job_record(job: BulkImportJob) -> IpImportJobRecord:
    return IpImportJobRecord(
        id=job.id,
        domain=job.domain,
        filename=job.filename,
        source_sha256=job.source_sha256,
        status=job.status,
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        committed_rows=job.committed_rows,
        failed_rows=job.failed_rows,
        preview_token=job.preview_token,
        preview_expires_at=job.preview_expires_at,
        committed_at=job.committed_at,
        creator_label_snapshot=job.creator_label_snapshot,
        version=job.version,
        created_at=job.created_at,
    )


def _row_record(row: IpImportRow) -> IpImportRowRecord:
    return IpImportRowRecord(
        id=row.id,
        row_number=row.row_number,
        validation_status=row.validation_status,
        errors=list(row.errors_json or []),
        commit_status=row.commit_status,
        commit_error_code=row.commit_error_code,
        created_docket_id=row.created_docket_id,
        normalized=dict(row.normalized_json or {}),
        duplicate_candidates=list(row.duplicate_candidates_json or []),
        reconciliation_decision=row.reconciliation_decision,
        reconciled_target_docket_id=row.reconciled_target_docket_id,
    )


def _rows(session: Session, job: BulkImportJob) -> list[IpImportRow]:
    return list(
        session.scalars(
            select(IpImportRow)
            .where(IpImportRow.job_id == job.id, IpImportRow.company_id == job.company_id)
            .order_by(IpImportRow.row_number)
        ).all()
    )


def _job_or_404(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    for_update: bool = False,
) -> BulkImportJob:
    statement = select(BulkImportJob).where(
        BulkImportJob.id == job_id,
        BulkImportJob.company_id == context.company.id,
        BulkImportJob.domain == DOMAIN,
    )
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found.")
    return job


def create_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    payload: IpImportJobCreateRequest,
) -> IpImportPreviewResponse:
    """Stage and validate rows; nothing is written to the portfolio yet."""

    numbers = [row.row_number for row in payload.rows]
    if len(set(numbers)) != len(numbers):
        raise HTTPException(status_code=422, detail="Duplicate row numbers in import.")

    digest = sha256(
        "|".join(f"{row.row_number}:{sorted(row.values.items())}" for row in payload.rows).encode()
    ).hexdigest()
    now = _now()
    job = BulkImportJob(
        company_id=context.company.id,
        domain=DOMAIN,
        filename=payload.filename,
        source_sha256=digest,
        status="preview_ready",
        total_rows=len(payload.rows),
        preview_token=token_hex(16),
        preview_expires_at=now + PREVIEW_TTL,
        created_by_membership_id=context.membership.id,
        creator_label_snapshot=context.user.full_name or context.user.email,
        version=1,
    )
    session.add(job)
    session.flush()

    valid = invalid = 0
    staged_rows: list[IpImportRow] = []
    for item in payload.rows:
        normalized, errors = _validate_row(session, context=context, values=item.values)
        if errors:
            invalid += 1
        else:
            valid += 1
        row = IpImportRow(
            company_id=context.company.id,
            job_id=job.id,
            row_number=item.row_number,
            raw_json=item.values,
            normalized_json=normalized,
            validation_status="invalid" if errors else "valid",
            errors_json=errors,
            duplicate_candidates_json=(
                _duplicate_candidates(session, context=context, normalized=normalized)
                if not errors
                else []
            ),
            commit_status="pending",
        )
        session.add(row)
        staged_rows.append(row)
    session.flush()
    staged_duplicates = _staged_duplicate_candidates(staged_rows)
    for row in staged_rows:
        row.duplicate_candidates_json = list(row.duplicate_candidates_json or []) + list(
            staged_duplicates.get(row.id, [])
        )
    job.valid_rows = valid
    job.invalid_rows = invalid

    record_from_context(
        session,
        context,
        action="ip.import.staged",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={
            "domain": DOMAIN,
            "filename": payload.filename,
            "total_rows": job.total_rows,
            "valid_rows": valid,
            "invalid_rows": invalid,
        },
    )
    session.commit()
    session.refresh(job)
    return IpImportPreviewResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        preview_expired=False,
    )


def preview_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> IpImportPreviewResponse:
    job = _job_or_404(session, context=context, job_id=job_id)
    expires = _aware(job.preview_expires_at)
    return IpImportPreviewResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        preview_expired=bool(expires and expires <= _now()),
    )


def revalidate_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> IpImportPreviewResponse:
    """Refresh an expired preview while excluding a concurrent commit."""

    resource = f"ip-import-job:{context.company.id}:{job_id}"
    with _import_commit_locks(session, resource):
        return _revalidate_ip_import_job_locked(
            session,
            context=context,
            job_id=job_id,
        )


def _revalidate_ip_import_job_locked(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> IpImportPreviewResponse:
    """UJ-02-EXC-01 — refresh an expired preview against current data."""

    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)
    if job.status in {"committed", "committed_with_errors", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A terminal import job cannot be revalidated.",
        )
    if job.status == "staged" and job.idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_import_commit_claimed",
                "message": (
                    "This import is being committed or awaits recovery; retry commit "
                    "with its original idempotency key."
                ),
            },
        )
    valid = invalid = 0
    rows = _rows(session, job)
    for row in rows:
        normalized, errors = _validate_row(session, context=context, values=row.raw_json)
        row.normalized_json = normalized
        row.errors_json = errors
        row.validation_status = "invalid" if errors else "valid"
        row.duplicate_candidates_json = (
            _duplicate_candidates(session, context=context, normalized=normalized)
            if not errors
            else []
        )
        row.reconciliation_decision = None
        row.reconciled_target_docket_id = None
        if errors:
            invalid += 1
        else:
            valid += 1
    staged_duplicates = _staged_duplicate_candidates(rows)
    for row in rows:
        row.duplicate_candidates_json = list(row.duplicate_candidates_json or []) + list(
            staged_duplicates.get(row.id, [])
        )
    job.valid_rows = valid
    job.invalid_rows = invalid
    job.status = "preview_ready"
    job.preview_token = token_hex(16)
    job.preview_expires_at = _now() + PREVIEW_TTL
    job.version += 1

    record_from_context(
        session,
        context,
        action="ip.import.revalidated",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={"valid_rows": valid, "invalid_rows": invalid, "version": job.version},
    )
    session.commit()
    session.refresh(job)
    return IpImportPreviewResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        preview_expired=False,
    )


def reconcile_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    payload: IpImportReconciliationRequest,
) -> IpImportPreviewResponse:
    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)
    if job.status != "preview_ready":
        raise HTTPException(
            status_code=409,
            detail="Only a preview-ready import can be reconciled.",
        )
    if job.version != payload.expected_job_version:
        raise HTTPException(status_code=409, detail="The import preview changed; reload it.")
    decision_ids = [decision.row_id for decision in payload.decisions]
    if len(decision_ids) != len(set(decision_ids)):
        raise HTTPException(status_code=422, detail="Each import row may be decided once.")
    rows = {row.id: row for row in _rows(session, job)}
    for decision in payload.decisions:
        row = rows.get(decision.row_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Import row not found.")
        if not row.duplicate_candidates_json:
            raise HTTPException(status_code=409, detail="This row has no duplicate candidates.")
        if decision.decision == "link_existing":
            allowed_targets = {
                candidate.get("docket_id")
                for candidate in row.duplicate_candidates_json
                if candidate.get("docket_id")
            }
            if decision.target_docket_id not in allowed_targets:
                raise HTTPException(
                    status_code=409,
                    detail="The selected target is not an accessible duplicate candidate.",
                )
            target = session.scalar(
                select(IpDocketRecord).where(
                    IpDocketRecord.id == decision.target_docket_id,
                    IpDocketRecord.company_id == context.company.id,
                    visible_ip_dockets_filter(session, context=context),
                )
            )
            if target is None:
                raise HTTPException(status_code=404, detail="Duplicate target not found.")
            row.reconciled_target_docket_id = target.id
        elif decision.target_docket_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Only link_existing accepts a target docket.",
            )
        else:
            row.reconciled_target_docket_id = None
        row.reconciliation_decision = decision.decision
    job.preview_token = token_hex(16)
    job.preview_expires_at = _now() + PREVIEW_TTL
    job.version += 1
    record_from_context(
        session,
        context,
        action="ip.import.duplicates_reconciled",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={
            "decision_count": len(payload.decisions),
            "job_version": job.version,
        },
    )
    session.commit()
    session.refresh(job)
    return IpImportPreviewResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        preview_expired=False,
    )


def list_ip_import_jobs(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 50,
) -> list[IpImportJobRecord]:
    jobs = session.scalars(
        select(BulkImportJob)
        .where(
            BulkImportJob.company_id == context.company.id,
            BulkImportJob.domain == DOMAIN,
            BulkImportJob.created_by_membership_id == context.membership.id,
        )
        .order_by(BulkImportJob.created_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return [_job_record(job) for job in jobs]


def ip_import_error_report(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> bytes:
    job = _job_or_404(session, context=context, job_id=job_id)
    if job.created_by_membership_id != context.membership.id:
        raise HTTPException(status_code=404, detail="Import job not found.")
    output = io.StringIO(newline="")
    fieldnames = [
        "row_number",
        "validation_status",
        "validation_errors",
        "duplicate_candidates",
        "reconciliation_decision",
        "commit_status",
        "commit_error_code",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in _rows(session, job):
        writer.writerow(
            csv_safe_mapping(
                {
                    "row_number": row.row_number,
                    "validation_status": row.validation_status,
                    "validation_errors": "; ".join(
                        f"{error.get('field')}:{error.get('code')}"
                        for error in row.errors_json or []
                    ),
                    "duplicate_candidates": "; ".join(
                        str(candidate.get("docket_id") or candidate.get("staged_row_id"))
                        for candidate in row.duplicate_candidates_json or []
                    ),
                    "reconciliation_decision": row.reconciliation_decision or "",
                    "commit_status": row.commit_status,
                    "commit_error_code": row.commit_error_code or "",
                }
            )
        )
    record_from_context(
        session,
        context,
        action="ip.import.error_report_downloaded",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={"total_rows": job.total_rows},
    )
    session.commit()
    return output.getvalue().encode("utf-8-sig")


def _particulars_for(normalized: dict[str, Any]) -> dict[str, Any]:
    mark_kind = str(normalized.get("representation_kind") or "word")
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": mark_kind,
        "representation": {
            "text": normalized["mark_text"],
            "evidence_reference": f"import:{normalized['mark_text']}",
        },
        "classes": [
            {
                "class_number": normalized["class_number"],
                "specification": normalized.get("specification") or "Imported specification",
            }
        ],
        "use_priority": None,
        "parties": [{"role": "applicant", "name": normalized["applicant_name"]}],
        "agent": (
            {"name": normalized["agent_name"]}
            if normalized.get("agent_name")
            else None
        ),
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Imported mark representation",
                "required": True,
                "evidence_reference": f"import:{normalized['mark_text']}",
            }
        ],
    }


def _set_row_outcome(
    session: Session,
    *,
    row_id: str,
    commit_status: str,
    error_code: str | None = None,
    docket_id: str | None = None,
) -> None:
    """Persist one row's commit outcome in its own transaction."""

    row = session.get(IpImportRow, row_id)
    assert row is not None
    row.commit_status = commit_status
    row.commit_error_code = error_code
    row.created_docket_id = docket_id
    session.commit()


def _import_docket_id(row_id: str) -> str:
    """Stable materialization id derived from the durable staging-row owner."""

    return str(uuid5(NAMESPACE_URL, f"caseops:ip-import-row:{row_id}"))


def _recover_materialized_docket(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
) -> IpDocketRecord | None:
    """Reuse a docket committed before its staging-row outcome was recorded.

    The deterministic docket id and source audit event are committed in the
    canonical writer's transaction. Seeing both proves that this exact import
    row materialized the docket; a same-key retry can therefore repair the row
    outcome without invoking the writer again.
    """

    docket_id = _import_docket_id(row_id)
    docket = session.scalar(
        select(IpDocketRecord).where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
    )
    if docket is None:
        return None
    provenance = session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.company_id == context.company.id,
            AuditEvent.action == IMPORT_MATERIALIZATION_ACTION,
            AuditEvent.target_type == "ip_import_row",
            AuditEvent.target_id == row_id,
            AuditEvent.ip_docket_id == docket.id,
        )
    )
    if provenance is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_import_materialization_provenance_missing",
                "message": "A reserved docket exists without matching import provenance.",
            },
        )
    return docket


def _materialize_import_row(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
    normalized: dict[str, Any],
) -> IpDocketRecord:
    docket = _recover_materialized_docket(
        session,
        context=context,
        row_id=row_id,
    )
    if docket is None:
        created = create_ip_docket(
            session,
            context=context,
            payload=IpDocketCreateRequest(
                title=normalized["title"],
                matter_id=normalized.get("matter_id"),
                primary_identifier=normalized.get("application_number"),
                restricted=False,
                particulars=_particulars_for(normalized),
            ),
            docket_id=_import_docket_id(row_id),
            source_provenance=("ip_import_row", row_id),
        )
        docket = session.get(IpDocketRecord, created.id)
        assert docket is not None
    asset = session.scalar(
        select(IpAsset).where(
            IpAsset.company_id == context.company.id,
            IpAsset.docket_id == docket.id,
        )
    )
    if asset is None:
        asset = create_ip_asset(
            session,
            context=context,
            docket_id=docket.id,
            payload=IpAssetCreateRequest(
                jurisdiction=normalized["jurisdiction"],
                title=normalized["mark_text"],
            ),
        )
    application_number = normalized.get("application_number")
    application = session.scalar(
        select(TrademarkApplication).where(
            TrademarkApplication.company_id == context.company.id,
            TrademarkApplication.docket_id == docket.id,
            TrademarkApplication.asset_id == asset.id,
        )
    )
    if application is None:
        create_trademark_application(
            session,
            context=context,
            docket_id=docket.id,
            payload=TrademarkApplicationCreateRequest(
                asset_id=asset.id,
                office=normalized["office"],
                jurisdiction=normalized["jurisdiction"],
                filing_phase="filed" if application_number else "draft",
                application_number=(
                    IpApplicationNumberCreate(
                        raw_value=application_number,
                        source="portfolio_import",
                        effective_from=date.today(),
                    )
                    if application_number
                    else None
                ),
            ),
        )
    return docket


def commit_ip_import_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    payload: IpImportCommitRequest,
) -> IpImportCommitResponse:
    """Materialise valid rows through the canonical docket writer.

    Idempotent by ``idempotency_key``: a repeated commit returns the original
    terminal result without creating a second record (UJ-02-EXC-03).
    """

    job_resource = f"ip-import-job:{context.company.id}:{job_id}"
    key_resource = f"ip-import-key:{context.company.id}:{DOMAIN}:{payload.idempotency_key}"
    with _import_commit_locks(session, job_resource, key_resource):
        return _commit_ip_import_job_locked(
            session,
            context=context,
            job_id=job_id,
            payload=payload,
        )


def _commit_ip_import_job_locked(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    payload: IpImportCommitRequest,
) -> IpImportCommitResponse:
    """Commit while the job and tenant/idempotency-key locks are held."""

    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)

    if job.status in {"committed", "committed_with_errors"}:
        if job.idempotency_key and job.idempotency_key == payload.idempotency_key:
            return IpImportCommitResponse(
                job=_job_record(job),
                rows=[_row_record(row) for row in _rows(session, job)],
                replayed=True,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This import job has already been committed.",
        )
    if job.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Import job is cancelled.")

    key_owner = session.scalar(
        select(BulkImportJob).where(
            BulkImportJob.company_id == context.company.id,
            BulkImportJob.domain == DOMAIN,
            BulkImportJob.idempotency_key == payload.idempotency_key,
            BulkImportJob.id != job.id,
        )
    )
    if key_owner is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_import_idempotency_key_reused",
                "message": "This idempotency key belongs to a different import job.",
            },
        )

    resuming = job.status == "staged" and bool(job.idempotency_key)
    if resuming:
        if job.idempotency_key != payload.idempotency_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This import is already claimed by a different idempotency key.",
            )
    else:
        if job.status != "preview_ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This import job is not ready to commit.",
            )
        if not job.preview_token or payload.preview_token != job.preview_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Import preview changed; preview again.",
            )
        expires = _aware(job.preview_expires_at)
        if expires and expires <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_import_preview_expired",
                    "message": "The import preview expired and must be revalidated.",
                },
            )

        unresolved_duplicates = [
            row.row_number
            for row in _rows(session, job)
            if row.validation_status == "valid"
            and row.duplicate_candidates_json
            and row.reconciliation_decision is None
        ]
        if unresolved_duplicates:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_import_duplicate_decision_required",
                    "message": "Resolve every duplicate suggestion before committing.",
                    "row_numbers": unresolved_duplicates,
                },
            )

        # Persist the ownership claim before the canonical row writer starts
        # committing. If the worker exits between rows, the same key can resume
        # rows whose outcomes are still pending; a different key cannot.
        job.status = "staged"
        job.idempotency_key = payload.idempotency_key
        job.preview_token = None
        job.preview_expires_at = None
        job.version += 1
        session.commit()

    # The canonical docket writer commits per call, so each row's outcome is
    # persisted immediately. UJ-02-EXC-02: a later row that fails and rolls back
    # its own partial write cannot discard an already-recorded sibling result.
    plan = [
        (
            row.id,
            row.validation_status,
            row.commit_status,
            dict(row.normalized_json or {}),
            row.reconciliation_decision,
            row.reconciled_target_docket_id,
        )
        for row in _rows(session, job)
    ]
    for (
        row_id,
        validation_status,
        commit_status,
        normalized,
        reconciliation_decision,
        _reconciled_target_docket_id,
    ) in plan:
        if commit_status in {"committed", "failed", "skipped"}:
            continue
        if validation_status != "valid":
            _set_row_outcome(session, row_id=row_id, commit_status="skipped")
            continue
        if reconciliation_decision == "skip":
            _set_row_outcome(session, row_id=row_id, commit_status="skipped")
            continue
        if reconciliation_decision == "link_existing":
            _set_row_outcome(
                session,
                row_id=row_id,
                commit_status="committed",
                docket_id=None,
            )
            continue
        try:
            docket = _materialize_import_row(
                session,
                context=context,
                row_id=row_id,
                normalized=normalized,
            )
        except HTTPException as exc:
            # Discard any partial write the rejected call had flushed.
            session.rollback()
            _set_row_outcome(
                session,
                row_id=row_id,
                commit_status="failed",
                error_code=(
                    str(exc.detail.get("code", "commit_rejected"))
                    if isinstance(exc.detail, dict)
                    else "commit_rejected"
                ),
            )
            continue
        _set_row_outcome(session, row_id=row_id, commit_status="committed", docket_id=docket.id)

    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)

    final_rows = _rows(session, job)
    committed = sum(row.commit_status == "committed" for row in final_rows)
    failed = sum(row.commit_status == "failed" for row in final_rows)

    job.committed_rows = committed
    job.failed_rows = failed
    job.status = "committed_with_errors" if failed else "committed"
    job.committed_at = _now()
    job.preview_token = None
    job.version += 1

    record_from_context(
        session,
        context,
        action="ip.import.committed",
        target_type="bulk_import_job",
        target_id=job.id,
        metadata={
            "committed_rows": committed,
            "failed_rows": failed,
            "skipped_rows": job.invalid_rows,
            "idempotency_key": payload.idempotency_key,
            "status": job.status,
        },
    )
    session.commit()
    session.refresh(job)
    return IpImportCommitResponse(
        job=_job_record(job),
        rows=[_row_record(row) for row in _rows(session, job)],
        replayed=False,
    )


__all__ = [
    "commit_ip_import_job",
    "create_ip_import_job",
    "ip_import_error_report",
    "list_ip_import_jobs",
    "preview_ip_import_job",
    "reconcile_ip_import_job",
    "revalidate_ip_import_job",
]
