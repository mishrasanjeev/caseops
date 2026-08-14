"""IPLF-032A bulk IP portfolio import (UJ-02).

Ownership: `bulk_import_jobs` is the **neutral** import owner tagged by domain;
`ip_import_rows` is the typed IP staging table. The legacy
`matter_bulk_import_jobs` and `employee_bulk_import_jobs` owners are untouched
and remain canonical for their domains. No `ip_import_jobs` table exists, and
Matter row-commit logic is not reused as generic orchestration.

Commit materialises records through the existing `create_ip_docket` writer
rather than inserting docket rows directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_hex
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import BulkImportJob, IpImportRow, Matter
from caseops_api.schemas.ip_imports import (
    IpImportCommitRequest,
    IpImportCommitResponse,
    IpImportJobCreateRequest,
    IpImportJobRecord,
    IpImportPreviewResponse,
    IpImportRowRecord,
)
from caseops_api.schemas.ip_operations import IpDocketCreateRequest
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_operations import create_ip_docket
from caseops_api.services.session_context import SessionContext

DOMAIN = "ip_trademark"
PREVIEW_TTL = timedelta(minutes=30)
REQUIRED_FIELDS = ("title", "mark_text", "class_number", "applicant_name")
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


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
    for item in payload.rows:
        normalized, errors = _validate_row(session, context=context, values=item.values)
        if errors:
            invalid += 1
        else:
            valid += 1
        session.add(
            IpImportRow(
                company_id=context.company.id,
                job_id=job.id,
                row_number=item.row_number,
                raw_json=item.values,
                normalized_json=normalized,
                validation_status="invalid" if errors else "valid",
                errors_json=errors,
                commit_status="pending",
            )
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
    """UJ-02-EXC-01 — refresh an expired preview against current data."""

    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)
    if job.status in {"committed", "committed_with_errors", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A terminal import job cannot be revalidated.",
        )
    valid = invalid = 0
    for row in _rows(session, job):
        normalized, errors = _validate_row(session, context=context, values=row.raw_json)
        row.normalized_json = normalized
        row.errors_json = errors
        row.validation_status = "invalid" if errors else "valid"
        if errors:
            invalid += 1
        else:
            valid += 1
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


def _particulars_for(normalized: dict[str, Any]) -> dict[str, Any]:
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
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
        "agent": None,
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
    if not job.preview_token or payload.preview_token != job.preview_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Import preview changed; preview again."
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

    # The canonical docket writer commits per call, so each row's outcome is
    # persisted immediately. UJ-02-EXC-02: a later row that fails and rolls back
    # its own partial write cannot discard an already-recorded sibling result.
    committed = failed = 0
    plan = [
        (row.id, row.validation_status, dict(row.normalized_json or {}))
        for row in _rows(session, job)
    ]
    for row_id, validation_status, normalized in plan:
        if validation_status != "valid":
            _set_row_outcome(session, row_id=row_id, commit_status="skipped")
            continue
        try:
            docket = create_ip_docket(
                session,
                context=context,
                payload=IpDocketCreateRequest(
                    title=normalized["title"],
                    matter_id=normalized.get("matter_id"),
                    restricted=False,
                    particulars=_particulars_for(normalized),
                ),
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
            failed += 1
            continue
        _set_row_outcome(session, row_id=row_id, commit_status="committed", docket_id=docket.id)
        committed += 1

    job = _job_or_404(session, context=context, job_id=job_id, for_update=True)

    job.committed_rows = committed
    job.failed_rows = failed
    job.status = "committed_with_errors" if failed else "committed"
    job.committed_at = _now()
    job.idempotency_key = payload.idempotency_key
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
    "preview_ip_import_job",
    "revalidate_ip_import_job",
]
