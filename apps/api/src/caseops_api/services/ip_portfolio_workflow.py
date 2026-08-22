"""Personal portfolio views and access-rechecked background exports."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    IpPortfolioExportJob,
    IpPortfolioSavedView,
    TeamMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_portfolio import (
    IpPortfolioExportCreate,
    IpPortfolioExportPreview,
    IpPortfolioExportPreviewRequest,
    IpPortfolioExportRecord,
    IpPortfolioFilters,
    IpPortfolioSavedViewCreate,
    IpPortfolioSavedViewRecord,
    IpPortfolioSavedViewUpdate,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.csv_security import csv_safe_mapping
from caseops_api.services.document_storage import (
    persist_workspace_attachment,
    resolve_storage_path,
)
from caseops_api.services.ip_portfolio import list_ip_portfolio
from caseops_api.services.notification_delivery import redact_provider_error
from caseops_api.services.session_context import SessionContext

logger = logging.getLogger(__name__)

MAX_SAVED_VIEWS = 50
DEFAULT_EXPORT_COLUMNS = [
    "mark",
    "application_numbers",
    "opposition_numbers",
    "classes",
    "jurisdiction",
    "office",
    "status",
    "phase",
    "proprietors",
    "agents",
    "client",
    "responsible_lawyer",
    "team",
    "deadlines",
    "created_at",
    "updated_at",
    "provenance",
]
EXPORT_COLUMNS = {
    "mark": ("Mark", lambda row: row.asset_title or row.docket_title),
    "representation": ("Representation types", lambda row: " | ".join(row.representation_kinds)),
    "application_numbers": ("Application numbers", lambda row: " | ".join(row.application_numbers)),
    "opposition_numbers": ("Opposition numbers", lambda row: " | ".join(row.opposition_numbers)),
    "classes": ("Nice classes", lambda row: " | ".join(str(value) for value in row.nice_classes)),
    "goods_services": ("Goods and services", lambda row: " | ".join(row.goods_services)),
    "jurisdiction": ("Jurisdiction", lambda row: row.jurisdiction or ""),
    "office": ("Office", lambda row: row.office or ""),
    "status": ("Status", lambda row: row.docket_status),
    "phase": ("Filing phase", lambda row: row.filing_phase),
    "proprietors": ("Proprietors", lambda row: " | ".join(row.proprietors)),
    "agents": ("Agents", lambda row: " | ".join(row.agents)),
    "client": ("Client", lambda row: row.client_name or ""),
    "responsible_lawyer": (
        "Responsible lawyer",
        lambda row: row.responsible_lawyer or "",
    ),
    "team": ("Team", lambda row: row.team_name or ""),
    "deadlines": (
        "Open / unconfirmed / overdue deadlines",
        lambda row: (
            f"{row.open_deadline_count} / {row.unconfirmed_deadline_count} / "
            f"{row.overdue_deadline_count}"
        ),
    ),
    "data_quality": (
        "Data quality",
        lambda row: "Complete"
        if row.record_complete
        else "Incomplete: " + ", ".join(row.incomplete_reasons),
    ),
    "registry_sync": ("Registry sync", lambda row: row.registry_sync_state),
    "created_at": ("Application created at", lambda row: row.application_created_at.isoformat()),
    "updated_at": ("Updated at", lambda row: row.updated_at.isoformat()),
    "provenance": ("Provenance", lambda row: " | ".join(row.provenance)),
}


def validate_portfolio_columns(columns: list[str]) -> list[str]:
    selected = columns or DEFAULT_EXPORT_COLUMNS
    normalized: list[str] = []
    for column in selected:
        if column not in EXPORT_COLUMNS:
            raise HTTPException(status_code=400, detail=f"Unsupported portfolio column: {column}")
        if column not in normalized:
            normalized.append(column)
    if not normalized:
        raise HTTPException(status_code=400, detail="Select at least one portfolio column.")
    return normalized


def _saved_view_record(
    row: IpPortfolioSavedView,
    *,
    membership_id: str,
) -> IpPortfolioSavedViewRecord:
    return IpPortfolioSavedViewRecord(
        id=row.id,
        name=row.name,
        filters=IpPortfolioFilters.model_validate(row.filters_json or {}),
        columns=list(row.columns_json or []),
        is_default=row.is_default,
        scope=row.scope,
        team_id=row.team_id,
        editable=row.membership_id == membership_id,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_saved_views(
    session: Session, *, context: SessionContext
) -> list[IpPortfolioSavedViewRecord]:
    team_ids = select(TeamMembership.team_id).where(
        TeamMembership.membership_id == context.membership.id
    )
    rows = session.scalars(
        select(IpPortfolioSavedView)
        .where(
            IpPortfolioSavedView.company_id == context.company.id,
            or_(
                IpPortfolioSavedView.membership_id == context.membership.id,
                (
                    (IpPortfolioSavedView.scope == "team")
                    & IpPortfolioSavedView.team_id.in_(team_ids)
                ),
            ),
        )
        .order_by(IpPortfolioSavedView.is_default.desc(), IpPortfolioSavedView.name.asc())
    ).all()
    return [
        _saved_view_record(row, membership_id=context.membership.id)
        for row in rows
    ]


def _assert_team_member(
    session: Session,
    *,
    context: SessionContext,
    team_id: str | None,
) -> None:
    if team_id is None:
        raise HTTPException(status_code=422, detail="A team view requires a team.")
    membership = session.scalar(
        select(TeamMembership.id).where(
            TeamMembership.team_id == team_id,
            TeamMembership.membership_id == context.membership.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Team not found.")


def _clear_default(session: Session, *, context: SessionContext, except_id: str | None) -> None:
    rows = session.scalars(
        select(IpPortfolioSavedView).where(
            IpPortfolioSavedView.company_id == context.company.id,
            IpPortfolioSavedView.membership_id == context.membership.id,
            IpPortfolioSavedView.is_default.is_(True),
        )
    ).all()
    for row in rows:
        if row.id != except_id:
            row.is_default = False
            row.version += 1


def create_saved_view(
    session: Session,
    *,
    context: SessionContext,
    payload: IpPortfolioSavedViewCreate,
) -> IpPortfolioSavedViewRecord:
    count = session.scalar(
        select(func.count())
        .select_from(IpPortfolioSavedView)
        .where(
            IpPortfolioSavedView.company_id == context.company.id,
            IpPortfolioSavedView.membership_id == context.membership.id,
        )
    )
    if int(count or 0) >= MAX_SAVED_VIEWS:
        raise HTTPException(status_code=409, detail="A user can save at most 50 portfolio views.")
    columns = validate_portfolio_columns(payload.columns)
    if payload.scope == "team":
        _assert_team_member(session, context=context, team_id=payload.team_id)
        if payload.is_default:
            raise HTTPException(status_code=422, detail="Only personal views can be default.")
        duplicate = session.scalar(
            select(IpPortfolioSavedView.id).where(
                IpPortfolioSavedView.company_id == context.company.id,
                IpPortfolioSavedView.scope == "team",
                IpPortfolioSavedView.team_id == payload.team_id,
                func.lower(IpPortfolioSavedView.name) == payload.name.strip().lower(),
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="That team already has this view name.")
    elif payload.team_id is not None:
        raise HTTPException(status_code=422, detail="A personal view cannot name a team.")
    if payload.is_default:
        _clear_default(session, context=context, except_id=None)
    row = IpPortfolioSavedView(
        company_id=context.company.id,
        membership_id=context.membership.id,
        scope=payload.scope,
        team_id=payload.team_id,
        name=payload.name.strip(),
        filters_json=payload.filters.model_dump(mode="json"),
        columns_json=columns,
        is_default=payload.is_default,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A saved view with that name already exists."
        ) from exc
    record_from_context(
        session,
        context,
        action="ip_portfolio.saved_view.created",
        target_type="ip_portfolio_saved_view",
        target_id=row.id,
        metadata={"columns": columns, "is_default": row.is_default},
    )
    session.commit()
    session.refresh(row)
    return _saved_view_record(row, membership_id=context.membership.id)


def update_saved_view(
    session: Session,
    *,
    context: SessionContext,
    view_id: str,
    payload: IpPortfolioSavedViewUpdate,
) -> IpPortfolioSavedViewRecord:
    row = session.scalar(
        select(IpPortfolioSavedView)
        .where(
            IpPortfolioSavedView.id == view_id,
            IpPortfolioSavedView.company_id == context.company.id,
            IpPortfolioSavedView.membership_id == context.membership.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Portfolio saved view not found.")
    if row.version != payload.expected_version:
        raise HTTPException(
            status_code=409, detail="The saved view changed; reload before updating."
        )
    columns = validate_portfolio_columns(payload.columns)
    if payload.scope == "team":
        _assert_team_member(session, context=context, team_id=payload.team_id)
        if payload.is_default:
            raise HTTPException(status_code=422, detail="Only personal views can be default.")
        duplicate = session.scalar(
            select(IpPortfolioSavedView.id).where(
                IpPortfolioSavedView.company_id == context.company.id,
                IpPortfolioSavedView.scope == "team",
                IpPortfolioSavedView.team_id == payload.team_id,
                func.lower(IpPortfolioSavedView.name) == payload.name.strip().lower(),
                IpPortfolioSavedView.id != row.id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="That team already has this view name.")
    elif payload.team_id is not None:
        raise HTTPException(status_code=422, detail="A personal view cannot name a team.")
    if payload.is_default:
        _clear_default(session, context=context, except_id=row.id)
    row.name = payload.name.strip()
    row.filters_json = payload.filters.model_dump(mode="json")
    row.columns_json = columns
    row.is_default = payload.is_default
    row.scope = payload.scope
    row.team_id = payload.team_id
    row.version += 1
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="A saved view with that name already exists."
        ) from exc
    record_from_context(
        session,
        context,
        action="ip_portfolio.saved_view.updated",
        target_type="ip_portfolio_saved_view",
        target_id=row.id,
        metadata={"version": row.version, "columns": columns, "is_default": row.is_default},
    )
    session.commit()
    session.refresh(row)
    return _saved_view_record(row, membership_id=context.membership.id)


def delete_saved_view(session: Session, *, context: SessionContext, view_id: str) -> None:
    row = session.scalar(
        select(IpPortfolioSavedView).where(
            IpPortfolioSavedView.id == view_id,
            IpPortfolioSavedView.company_id == context.company.id,
            IpPortfolioSavedView.membership_id == context.membership.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Portfolio saved view not found.")
    record_from_context(
        session,
        context,
        action="ip_portfolio.saved_view.deleted",
        target_type="ip_portfolio_saved_view",
        target_id=row.id,
        metadata={"version": row.version},
    )
    session.delete(row)
    session.commit()


def _export_record(row: IpPortfolioExportJob) -> IpPortfolioExportRecord:
    return IpPortfolioExportRecord(
        id=row.id,
        status=row.status,
        format=row.format,
        columns=list(row.columns_json or []),
        row_limit=row.row_limit,
        row_count=row.row_count,
        size_bytes=row.size_bytes,
        error=row.error,
        download_ready=row.status == "completed" and bool(row.storage_key),
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _export_preview(
    session: Session,
    *,
    context: SessionContext,
    payload: IpPortfolioExportPreviewRequest,
) -> IpPortfolioExportPreview:
    columns = validate_portfolio_columns(payload.columns)
    rows = []
    cursor: str | None = None
    total = 0
    while len(rows) < payload.row_limit:
        page = list_ip_portfolio(
            session,
            context=context,
            filters=payload.filters,
            limit=min(200, payload.row_limit - len(rows)),
            cursor=cursor,
        )
        total = page.counts.total
        rows.extend(page.rows)
        cursor = page.next_cursor
        if not cursor:
            break
    canonical = json.dumps(
        {
            "company_id": context.company.id,
            "membership_id": context.membership.id,
            "filters": payload.filters.model_dump(mode="json"),
            "columns": columns,
            "row_limit": payload.row_limit,
            "manifest": [
                [row.application_id, row.updated_at.isoformat()]
                for row in rows
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    token = hmac.new(
        get_settings().auth_secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    return IpPortfolioExportPreview(
        columns=columns,
        row_limit=payload.row_limit,
        row_count=len(rows),
        truncated=total > payload.row_limit,
        preview_token=token,
    )


def preview_portfolio_export(
    session: Session,
    *,
    context: SessionContext,
    payload: IpPortfolioExportPreviewRequest,
) -> IpPortfolioExportPreview:
    preview = _export_preview(session, context=context, payload=payload)
    record_from_context(
        session,
        context,
        action="ip_portfolio.export.previewed",
        target_type="ip_portfolio_export",
        target_id=preview.preview_token,
        metadata={
            "row_count": preview.row_count,
            "row_limit": preview.row_limit,
            "truncated": preview.truncated,
        },
    )
    session.commit()
    return preview


def enqueue_portfolio_export(
    session: Session,
    *,
    context: SessionContext,
    payload: IpPortfolioExportCreate,
) -> IpPortfolioExportRecord:
    preview = _export_preview(session, context=context, payload=payload)
    if not hmac.compare_digest(preview.preview_token, payload.preview_token):
        raise HTTPException(
            status_code=409,
            detail="The portfolio changed after preview; review the export again.",
        )
    columns = preview.columns
    row = IpPortfolioExportJob(
        company_id=context.company.id,
        requested_by_membership_id=context.membership.id,
        status="pending",
        format=payload.format,
        filters_json=payload.filters.model_dump(mode="json"),
        columns_json=columns,
        row_limit=payload.row_limit,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_portfolio.export.enqueued",
        target_type="ip_portfolio_export_job",
        target_id=row.id,
        metadata={"format": row.format, "columns": columns, "row_limit": row.row_limit},
    )
    session.commit()
    session.refresh(row)
    return _export_record(row)


def retry_portfolio_export(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> IpPortfolioExportRecord:
    row = _get_export_job(session, context=context, job_id=job_id)
    if row.status != "failed":
        raise HTTPException(status_code=409, detail="Only a failed export can be retried.")
    row.status = "pending"
    row.error = None
    row.started_at = None
    row.completed_at = None
    record_from_context(
        session,
        context,
        action="ip_portfolio.export.retry_enqueued",
        target_type="ip_portfolio_export_job",
        target_id=row.id,
        metadata={"row_limit": row.row_limit},
    )
    session.commit()
    session.refresh(row)
    return _export_record(row)


def _get_export_job(
    session: Session, *, context: SessionContext, job_id: str
) -> IpPortfolioExportJob:
    row = session.scalar(
        select(IpPortfolioExportJob).where(
            IpPortfolioExportJob.id == job_id,
            IpPortfolioExportJob.company_id == context.company.id,
            IpPortfolioExportJob.requested_by_membership_id == context.membership.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Portfolio export job not found.")
    return row


def get_portfolio_export(
    session: Session, *, context: SessionContext, job_id: str
) -> IpPortfolioExportRecord:
    return _export_record(_get_export_job(session, context=context, job_id=job_id))


def list_portfolio_exports(
    session: Session, *, context: SessionContext, limit: int = 25
) -> list[IpPortfolioExportRecord]:
    rows = session.scalars(
        select(IpPortfolioExportJob)
        .where(
            IpPortfolioExportJob.company_id == context.company.id,
            IpPortfolioExportJob.requested_by_membership_id == context.membership.id,
        )
        .order_by(IpPortfolioExportJob.created_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return [_export_record(row) for row in rows]


def read_portfolio_export(
    session: Session, *, context: SessionContext, job_id: str
) -> tuple[IpPortfolioExportJob, Iterator[bytes]]:
    row = _get_export_job(session, context=context, job_id=job_id)
    if row.status != "completed" or not row.storage_key:
        raise HTTPException(status_code=409, detail="The portfolio export is not ready.")
    path = resolve_storage_path(row.storage_key)
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Portfolio export artifact is missing.")
    record_from_context(
        session,
        context,
        action="ip_portfolio.export.downloaded",
        target_type="ip_portfolio_export_job",
        target_id=row.id,
        metadata={"row_count": row.row_count, "size_bytes": row.size_bytes},
    )
    session.commit()

    def chunks() -> Iterator[bytes]:
        with open(path, "rb") as stream:
            while chunk := stream.read(64 * 1024):
                yield chunk

    return row, chunks()


def _csv_stream(rows: list, columns: list[str]) -> io.BytesIO:
    text = io.StringIO(newline="")
    headers = [EXPORT_COLUMNS[column][0] for column in columns]
    writer = csv.DictWriter(text, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        values = {EXPORT_COLUMNS[column][0]: EXPORT_COLUMNS[column][1](row) for column in columns}
        writer.writerow(csv_safe_mapping(values))
    return io.BytesIO(text.getvalue().encode("utf-8-sig"))


def run_portfolio_export_job(job_id: str) -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        job = session.get(IpPortfolioExportJob, job_id)
        if job is None or job.status not in {"pending", "failed"}:
            return
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error = None
        session.commit()
        try:
            membership = session.get(CompanyMembership, job.requested_by_membership_id)
            company = session.get(Company, job.company_id)
            user = session.get(User, membership.user_id) if membership else None
            if (
                membership is None
                or company is None
                or user is None
                or membership.company_id != company.id
                or not membership.is_active
            ):
                raise RuntimeError(
                    "Portfolio export requester is no longer an active tenant member."
                )
            context = SessionContext(company=company, membership=membership, user=user)
            filters = IpPortfolioFilters.model_validate(job.filters_json or {})
            rows = []
            cursor: str | None = None
            while len(rows) < job.row_limit:
                page = list_ip_portfolio(
                    session,
                    context=context,
                    filters=filters,
                    limit=min(200, job.row_limit - len(rows)),
                    cursor=cursor,
                )
                rows.extend(page.rows)
                cursor = page.next_cursor
                if not cursor:
                    break
            stream = _csv_stream(rows, list(job.columns_json or []))
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            stored = persist_workspace_attachment(
                company_id=job.company_id,
                workspace_id="ip-portfolio-exports",
                attachment_id=job.id,
                filename=f"trademark-portfolio-{stamp}.csv",
                stream=stream,
                namespace="exports",
            )
            job.storage_key = stored.storage_key
            job.size_bytes = stored.size_bytes
            job.row_count = len(rows)
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            record_audit(
                session,
                company_id=job.company_id,
                actor_membership_id=job.requested_by_membership_id,
                actor_label=user.full_name or user.email,
                action="ip_portfolio.export.completed",
                target_type="ip_portfolio_export_job",
                target_id=job.id,
                metadata={"row_count": len(rows), "size_bytes": stored.size_bytes},
            )
            session.commit()
        except Exception as exc:  # noqa: BLE001 - durable worker failure state
            logger.exception("portfolio export job %s failed", job.id)
            job.status = "failed"
            job.error = redact_provider_error(exc)
            job.completed_at = datetime.now(UTC)
            session.commit()


__all__ = [
    "create_saved_view",
    "delete_saved_view",
    "enqueue_portfolio_export",
    "get_portfolio_export",
    "list_portfolio_exports",
    "list_saved_views",
    "preview_portfolio_export",
    "read_portfolio_export",
    "run_portfolio_export_job",
    "retry_portfolio_export",
    "update_saved_view",
    "validate_portfolio_columns",
]
