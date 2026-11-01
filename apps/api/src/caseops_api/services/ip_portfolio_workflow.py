"""Personal portfolio views and access-rechecked background exports."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from caseops_api.core.redaction import redact_provider_error
from caseops_api.core.settings import get_settings
from caseops_api.db.connection_safety import migration_connect_args
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    IpDocketRecord,
    IpPortfolioExportJob,
    IpPortfolioSavedView,
    Matter,
    TeamMembership,
    TrademarkApplication,
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
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.csv_security import csv_safe_mapping
from caseops_api.services.document_storage import (
    persist_workspace_attachment,
    resolve_storage_path,
)
from caseops_api.services.ip_portfolio import portfolio_export_manifest, portfolio_export_page
from caseops_api.services.session_context import SessionContext

logger = logging.getLogger(__name__)

MAX_SAVED_VIEWS = 50
EXPORT_DISPATCH_PROTOCOL = 1
EXPORT_LEASE_SECONDS = 300
# One work clock includes storage and final checks. Bounded connect/commit
# tails plus failure persistence retain headroom inside the 120-second HTTP limit.
EXPORT_WORK_SECONDS = 90.0
EXPORT_STORAGE_SECONDS = 10.0
EXPORT_FAILURE_SECONDS = 10.0
EXPORT_CONNECT_SECONDS = 3
EXPORT_COMMIT_SECONDS = 5.0
EXPORT_PAGE_SIZE = 200
MAX_EXPORT_RECOVERY = 25
MAX_UNRESOLVED_EXPORTS = 5
DEFAULT_EXPORT_COLUMNS = [
    "mark",
    "application_date",
    "renewal_due_date",
    "application_numbers",
    "opposition_numbers",
    "classes",
    "jurisdiction",
    "office",
    "status",
    "record_status",
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
    "application_date": (
        "Application Date",
        lambda row: row.source_application_on.isoformat() if row.source_application_on else "",
    ),
    "renewal_due_date": (
        "Renewal Due Date",
        lambda row: row.source_renewal_due_on.isoformat() if row.source_renewal_due_on else "",
    ),
    "mark": ("Mark", lambda row: row.asset_title or row.docket_title),
    "representation": ("Representation types", lambda row: " | ".join(row.representation_kinds)),
    "application_numbers": ("Application numbers", lambda row: " | ".join(row.application_numbers)),
    "opposition_numbers": ("Opposition numbers", lambda row: " | ".join(row.opposition_numbers)),
    "classes": ("Nice classes", lambda row: " | ".join(str(value) for value in row.nice_classes)),
    "goods_services": ("Goods and services", lambda row: " | ".join(row.goods_services)),
    "jurisdiction": ("Jurisdiction", lambda row: row.jurisdiction or ""),
    "office": ("Office", lambda row: row.office or ""),
    "status": ("Status", lambda row: portfolio_status_text(row)),
    "record_status": ("Record status", lambda row: row.docket_status),
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


_IMPORT_PHASE_RANK = {"draft": 0, "pre_filing": 1, "filed": 2}
_PHASE_LABELS = {"draft": "Draft", "pre_filing": "Pre-filing", "filed": "Filed"}


def source_status_is_ahead(row: Any) -> bool:
    """Whether an import's source status says more than the filing phase.

    B4-ADJ-11: a mark the source calls Registered imports in the filed phase,
    and wording the mapping does not recognise imports as draft. The source
    wording is then the mark's headline status, marked unverified, so neither
    reads as Draft. Once a lifecycle event moves the phase on, the phase leads.
    """

    phase = getattr(row, "filing_phase", None)
    if not getattr(row, "source_status_text", None) or phase not in _IMPORT_PHASE_RANK:
        return False
    declared = getattr(row, "source_declared_status", None)
    return declared is None or _IMPORT_PHASE_RANK.get(declared, 3) > _IMPORT_PHASE_RANK[phase]


def portfolio_status_text(row: Any) -> str:
    """The Status column: the filing phase, or the unverified source status."""

    if source_status_is_ahead(row):
        return f"{row.source_status_text} (source, unverified)"
    phase = str(row.filing_phase)
    return _PHASE_LABELS.get(phase, phase.replace("_", " ").capitalize())


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
    manifest, truncated = portfolio_export_manifest(
        session, context=context, filters=payload.filters, row_limit=payload.row_limit
    )
    canonical = json.dumps(
        {
            "company_id": context.company.id,
            "membership_id": context.membership.id,
            "filters": payload.filters.model_dump(mode="json"),
            "columns": columns,
            "row_limit": payload.row_limit,
            "manifest": [
                [application_id, updated_at.isoformat()]
                for application_id, updated_at in manifest
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
        row_count=len(manifest),
        truncated=truncated,
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
    _lock_export_company(session, company_id=context.company.id)
    _assert_export_queue_capacity(session, context=context)
    columns = preview.columns
    row = IpPortfolioExportJob(
        company_id=context.company.id,
        requested_by_membership_id=context.membership.id,
        status="pending",
        dispatch_protocol_version=EXPORT_DISPATCH_PROTOCOL,
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
    _lock_export_company(session, company_id=context.company.id)
    row = session.scalar(
        select(IpPortfolioExportJob).where(
            IpPortfolioExportJob.id == job_id,
            IpPortfolioExportJob.company_id == context.company.id,
            IpPortfolioExportJob.requested_by_membership_id == context.membership.id,
        ).with_for_update().execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Portfolio export job not found.")
    if row.status != "failed":
        raise HTTPException(status_code=409, detail="Only a failed export can be retried.")
    _assert_export_queue_capacity(session, context=context)
    row.status = "pending"
    row.dispatch_protocol_version = EXPORT_DISPATCH_PROTOCOL
    row.worker_claim_token = None
    row.worker_claim_expires_at = None
    row.storage_key = None
    row.row_count = None
    row.size_bytes = None
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


def _csv_stream(
    rows: list, columns: list[str], *, deadline: float | None = None
) -> io.BytesIO:
    text = io.StringIO(newline="")
    headers = [EXPORT_COLUMNS[column][0] for column in columns]
    writer = csv.DictWriter(text, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        if deadline is not None:
            _remaining_export_seconds(deadline)
        values = {EXPORT_COLUMNS[column][0]: EXPORT_COLUMNS[column][1](row) for column in columns}
        writer.writerow(csv_safe_mapping(values))
    return io.BytesIO(text.getvalue().encode("utf-8-sig"))


@dataclass(frozen=True)
class _ExportClaim:
    job_id: str
    company_id: str
    membership_id: str
    token: str
    filters: dict[str, object]
    columns: list[str]
    row_limit: int


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _remaining_export_seconds(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Portfolio export exceeded its bounded work budget; retry explicitly.")
    return remaining


@contextmanager
def _export_session(deadline: float) -> Iterator[Session]:
    """Bound every SQL statement, including SQL inside page/authorization helpers."""
    _remaining_export_seconds(deadline)
    with get_session_factory()() as session:
        owned_engine = None
        try:
            bind = session.get_bind()
            if bind.dialect.name == "postgresql":
                remaining = _remaining_export_seconds(deadline)
                settings = get_settings()
                # No shared-pool checkout/reconnect tail outside the HTTP budget.
                # Keep the normal Session class and canonical URL/TLS/options.
                owned_engine = create_engine(
                    bind.url, poolclass=NullPool,
                    connect_args=migration_connect_args(
                        bind.url.render_as_string(hide_password=False),
                        connect_timeout_seconds=max(1, min(EXPORT_CONNECT_SECONDS, int(remaining))),
                        statement_timeout_ms=max(1, int(remaining * 1000)),
                        lock_timeout_ms=max(1, min(5000, int(remaining * 1000))),
                        idle_transaction_timeout_ms=settings.db_idle_transaction_timeout_ms,
                    ),
                )
                session.bind = owned_engine
            connection = session.connection()

            def budget_sql(_connection, cursor, _statement, _params, _context, _many):
                milliseconds = max(1, int(_remaining_export_seconds(deadline) * 1000))
                if connection.dialect.name == "postgresql":
                    # Direct DBAPI execution avoids recursively invoking this listener.
                    cursor.execute(
                        "SELECT set_config('statement_timeout', %s, true), "
                        "set_config('lock_timeout', %s, true)",
                        (str(milliseconds), str(min(milliseconds, 5000))),
                    )

            event.listen(connection, "before_cursor_execute", budget_sql)
            try:
                yield session
            finally:
                event.remove(connection, "before_cursor_execute", budget_sql)
        finally:
            # In particular, a failed flush must not poison durable failure recording.
            try:
                session.rollback()
            finally:
                try:
                    session.close()
                finally:
                    if owned_engine is not None:
                        owned_engine.dispose()


def _commit_export(session: Session, *, deadline: float) -> None:
    remaining = _remaining_export_seconds(deadline)
    if session.get_bind().dialect.name == "postgresql":
        milliseconds = str(max(1, int(min(remaining, EXPORT_COMMIT_SECONDS) * 1000)))
        session.scalar(select(func.set_config(
            "statement_timeout", milliseconds, True
        )))
    _remaining_export_seconds(deadline)
    session.commit()


def _export_now(session: Session) -> datetime:
    if session.get_bind().dialect.name == "postgresql":
        return _utc(session.scalar(select(func.clock_timestamp())))
    return datetime.now(UTC)


def _lock_export_company(session: Session, *, company_id: str) -> Company | None:
    if session.get_bind().dialect.name == "sqlite":
        session.serialize_sqlite_writer()
    return session.scalar(
        select(Company).where(Company.id == company_id).with_for_update()
        .execution_options(populate_existing=True)
    )


def _locked_export_job(
    session: Session, *, company_id: str, job_id: str
) -> IpPortfolioExportJob | None:
    _lock_export_company(session, company_id=company_id)
    return session.scalar(
        select(IpPortfolioExportJob).where(
            IpPortfolioExportJob.id == job_id,
            IpPortfolioExportJob.company_id == company_id,
        ).with_for_update().execution_options(populate_existing=True)
    )


def _assert_export_queue_capacity(session: Session, *, context: SessionContext) -> None:
    unresolved = session.scalars(
        select(IpPortfolioExportJob.id).where(
            IpPortfolioExportJob.company_id == context.company.id,
            IpPortfolioExportJob.requested_by_membership_id == context.membership.id,
            IpPortfolioExportJob.dispatch_protocol_version == EXPORT_DISPATCH_PROTOCOL,
            IpPortfolioExportJob.status.in_(["pending", "running"]),
        ).limit(MAX_UNRESOLVED_EXPORTS)
    ).all()
    if len(unresolved) >= MAX_UNRESOLVED_EXPORTS:
        raise HTTPException(
            status_code=429,
            detail="You already have five pending or running portfolio exports. "
            "Wait for an export to finish before requesting or retrying another.",
        )


def _export_delivery_result(job: IpPortfolioExportJob | None) -> str:
    if job is None:
        return "missing"
    if job.status == "completed":
        return "completed"
    if job.status == "failed" or job.dispatch_protocol_version != EXPORT_DISPATCH_PROTOCOL:
        return "terminal"
    return "busy"


def _claim_portfolio_export(job_id: str, *, deadline: float) -> _ExportClaim | str:
    with _export_session(deadline) as session:
        company_id = session.scalar(
            select(IpPortfolioExportJob.company_id).where(IpPortfolioExportJob.id == job_id)
        )
        if company_id is None:
            return "missing"
        job = _locked_export_job(session, company_id=company_id, job_id=job_id)
        result = _export_delivery_result(job)
        if result != "busy":
            return result
        now = _export_now(session)
        if job.status != "pending" and not (
            job.status == "running"
            and job.worker_claim_expires_at is not None
            and _utc(job.worker_claim_expires_at) <= now
        ):
            return "busy"
        token = str(uuid4())
        job.status = "running"
        job.worker_claim_token = token
        job.worker_claim_expires_at = now + timedelta(seconds=EXPORT_LEASE_SECONDS)
        job.started_at = now
        job.completed_at = None
        job.error = None
        # Capture only scalars: no expired ORM read may open a transaction at storage.
        claim = _ExportClaim(
            job_id=job.id, company_id=job.company_id,
            membership_id=job.requested_by_membership_id, token=token,
            filters=job.filters_json or {}, columns=list(job.columns_json or []),
            row_limit=job.row_limit,
        )
        record_audit(
            session, company_id=claim.company_id, actor_type="system",
            actor_membership_id=claim.membership_id,
            action="ip_portfolio.export.attempt_claimed",
            target_type="ip_portfolio_export_job", target_id=claim.job_id,
            metadata={
                "attempt_id": claim.token,
                "dispatch_protocol_version": EXPORT_DISPATCH_PROTOCOL,
                "planned_storage_key": (
                    f"{claim.company_id}/exports/ip-portfolio-exports/{claim.token}.csv"
                ),
                "lease_expires_at": job.worker_claim_expires_at.isoformat(),
            },
        )
        _remaining_export_seconds(deadline)
        _commit_export(session, deadline=deadline)
        return claim


def _export_context(session: Session, *, claim: _ExportClaim, lock: bool = False) -> SessionContext:
    def fresh(model, identity):
        statement = (
            select(model).where(model.id == identity).execution_options(populate_existing=True)
        )
        return session.scalar(statement.with_for_update() if lock else statement)

    company = fresh(Company, claim.company_id)
    membership = fresh(CompanyMembership, claim.membership_id)
    user = fresh(User, membership.user_id) if membership is not None else None
    if (
        company is None or membership is None or user is None
        or membership.company_id != claim.company_id
        or not company.is_active or not membership.is_active or not user.is_active
    ):
        raise RuntimeError("Portfolio export requester is no longer an active tenant member.")
    if not membership_has_capability(session, membership, "ip:read"):
        raise RuntimeError("Portfolio export requester no longer has IP read permission.")
    return SessionContext(company=company, membership=membership, user=user)


def _manifest_identity(manifest) -> list[tuple[str, datetime]]:
    return [(application_id, _utc(updated_at)) for application_id, updated_at in manifest]


def _lock_export_sources(session: Session, *, claim: _ExportClaim, manifest) -> None:
    application_ids = [application_id for application_id, _updated_at in manifest]
    if not application_ids:
        return
    parents = []
    for offset in range(0, len(application_ids), EXPORT_PAGE_SIZE):
        parents.extend(session.execute(
            select(TrademarkApplication.docket_id, IpDocketRecord.matter_id)
            .join(IpDocketRecord, IpDocketRecord.id == TrademarkApplication.docket_id)
            .where(
                TrademarkApplication.company_id == claim.company_id,
                IpDocketRecord.company_id == claim.company_id,
                TrademarkApplication.id.in_(application_ids[offset:offset + EXPORT_PAGE_SIZE]),
            )
        ).all())
    # Match lifecycle's parent-before-child ordering, without locking nullable joins.
    for model, identities in (
        (Matter, sorted({matter_id for _docket_id, matter_id in parents if matter_id})),
        (IpDocketRecord, sorted({docket_id for docket_id, _matter_id in parents})),
        (TrademarkApplication, sorted(application_ids)),
    ):
        for offset in range(0, len(identities), EXPORT_PAGE_SIZE):
            session.scalars(
                select(model.id).where(
                    model.company_id == claim.company_id,
                    model.id.in_(identities[offset:offset + EXPORT_PAGE_SIZE]),
                )
                .order_by(model.id).with_for_update(of=model)
            ).all()


def _owns_export_claim(
    session: Session, job: IpPortfolioExportJob | None, claim: _ExportClaim
) -> bool:
    return bool(
        job is not None and job.status == "running"
        and job.company_id == claim.company_id
        and job.requested_by_membership_id == claim.membership_id
        and job.dispatch_protocol_version == EXPORT_DISPATCH_PROTOCOL
        and job.worker_claim_token == claim.token
        and job.worker_claim_expires_at is not None
        and _utc(job.worker_claim_expires_at) > _export_now(session)
    )


def _export_claim_update(session: Session, *, claim: _ExportClaim, **values) -> bool:
    now = (
        func.clock_timestamp()
        if session.get_bind().dialect.name == "postgresql" else _export_now(session)
    )
    result = session.execute(
        update(IpPortfolioExportJob).where(
            IpPortfolioExportJob.id == claim.job_id,
            IpPortfolioExportJob.company_id == claim.company_id,
            IpPortfolioExportJob.requested_by_membership_id == claim.membership_id,
            IpPortfolioExportJob.dispatch_protocol_version == EXPORT_DISPATCH_PROTOCOL,
            IpPortfolioExportJob.status == "running",
            IpPortfolioExportJob.worker_claim_token == claim.token,
            IpPortfolioExportJob.worker_claim_expires_at > now,
        ).values(**values, worker_claim_token=None, worker_claim_expires_at=None)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _fail_portfolio_export(claim: _ExportClaim, exc: Exception) -> str:
    # Always use a fresh session after rollback, never the failed statement's session.
    deadline = monotonic() + EXPORT_FAILURE_SECONDS
    with _export_session(deadline) as session:
        job = _locked_export_job(session, company_id=claim.company_id, job_id=claim.job_id)
        if not _owns_export_claim(session, job, claim):
            return _export_delivery_result(job)
        if not _export_claim_update(
            session, claim=claim, status="failed", error=redact_provider_error(exc),
            completed_at=_export_now(session), storage_key=None, row_count=None, size_bytes=None,
        ):
            return "busy"
        record_audit(
            session, company_id=claim.company_id, actor_type="system",
            actor_membership_id=claim.membership_id,
            action="ip_portfolio.export.attempt_failed",
            target_type="ip_portfolio_export_job", target_id=claim.job_id,
            metadata={"attempt_id": claim.token, "error_type": type(exc).__name__},
        )
        _commit_export(session, deadline=deadline)
        return "terminal"


def list_recoverable_portfolio_exports(limit: int = 5) -> list[str]:
    """Read-only discovery; claiming and all current authorization stay in the worker."""
    with _export_session(monotonic() + EXPORT_FAILURE_SECONDS) as session:
        now = _export_now(session)
        return list(session.scalars(
            select(IpPortfolioExportJob.id).where(
                IpPortfolioExportJob.dispatch_protocol_version == EXPORT_DISPATCH_PROTOCOL,
                or_(
                    IpPortfolioExportJob.status == "pending",
                    (IpPortfolioExportJob.status == "running")
                    & (IpPortfolioExportJob.worker_claim_expires_at <= now),
                ),
            ).order_by(IpPortfolioExportJob.created_at, IpPortfolioExportJob.id)
            .limit(max(1, min(limit, MAX_EXPORT_RECOVERY)))
        ))


def list_legacy_unresolved_portfolio_exports(limit: int = 5) -> list[str]:
    """Report old non-CAS writers separately, without adopting or mutating their jobs."""
    with _export_session(monotonic() + EXPORT_FAILURE_SECONDS) as session:
        return list(session.scalars(
            select(IpPortfolioExportJob.id).where(
                IpPortfolioExportJob.dispatch_protocol_version == 0,
                IpPortfolioExportJob.status.in_(["pending", "running"]),
            ).order_by(IpPortfolioExportJob.created_at, IpPortfolioExportJob.id)
            .limit(max(1, min(limit, MAX_EXPORT_RECOVERY)))
        ))


def _export_rows(
    session: Session, *, claim: _ExportClaim, context: SessionContext,
    filters: IpPortfolioFilters, columns: list[str], deadline: float,
) -> list:
    rows = []
    cursor = None
    for _page in range((claim.row_limit + EXPORT_PAGE_SIZE - 1) // EXPORT_PAGE_SIZE):
        _remaining_export_seconds(deadline)
        remaining = min(EXPORT_PAGE_SIZE, claim.row_limit - len(rows))
        page_rows, next_cursor = portfolio_export_page(
            session, context=context, filters=filters, columns=columns,
            limit=remaining, cursor=cursor,
        )
        if len(page_rows) > remaining:
            raise RuntimeError("Portfolio export page exceeded its requested bound.")
        rows.extend(page_rows)
        if not next_cursor or len(rows) == claim.row_limit:
            break
        if not page_rows or next_cursor == cursor:
            raise RuntimeError("Portfolio export continuation did not advance.")
        cursor = next_cursor
    return rows


def run_portfolio_export_job(job_id: str) -> str:
    """Deliver once, or recover an expired protocol-1 claim; failed jobs need explicit retry."""
    deadline = monotonic() + EXPORT_WORK_SECONDS
    claim = _claim_portfolio_export(job_id, deadline=deadline)
    if isinstance(claim, str):
        return claim
    try:
        filters = IpPortfolioFilters.model_validate(claim.filters)
        columns = validate_portfolio_columns(claim.columns)
        if not 1 <= claim.row_limit <= 50000:
            raise ValueError("Portfolio export row limit is outside the supported bound.")
        with _export_session(deadline) as session:
            context = _export_context(session, claim=claim)
            manifest, truncated = portfolio_export_manifest(
                session, context=context, filters=filters, row_limit=claim.row_limit
            )
            rows = _export_rows(
                session, claim=claim, context=context, filters=filters,
                columns=columns, deadline=deadline,
            )
            expected = _manifest_identity(manifest)
            prepared = _manifest_identity([(row.application_id, row.updated_at) for row in rows])
            if prepared != expected:
                raise RuntimeError(
                    "Portfolio sources changed while preparing export; retry explicitly."
                )
        with _csv_stream(rows, columns, deadline=deadline) as stream:
            _remaining_export_seconds(deadline)
            frozen_csv_hash = hashlib.sha256(stream.getbuffer()).hexdigest()
            stored = persist_workspace_attachment(
                company_id=claim.company_id, workspace_id="ip-portfolio-exports",
                attachment_id=claim.token,
                filename=f"trademark-portfolio-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv",
                stream=stream, namespace="exports", storage_timeout_seconds=EXPORT_STORAGE_SECONDS,
            )
        with _export_session(deadline) as session:
            job = _locked_export_job(session, company_id=claim.company_id, job_id=claim.job_id)
            if not _owns_export_claim(session, job, claim):
                return _export_delivery_result(job)
            context = _export_context(session, claim=claim, lock=True)
            _lock_export_sources(session, claim=claim, manifest=expected)
            current_manifest, current_truncated = portfolio_export_manifest(
                session, context=context, filters=filters, row_limit=claim.row_limit
            )
            if _manifest_identity(current_manifest) != expected or current_truncated != truncated:
                raise RuntimeError(
                    "Portfolio sources or access changed during export; retry explicitly."
                )
            # Asset/particular presentation can change without updating the
            # application's timestamp. Recheck the actual authorized CSV too.
            current_rows = _export_rows(
                session, claim=claim, context=context, filters=filters,
                columns=columns, deadline=deadline,
            )
            with _csv_stream(current_rows, columns, deadline=deadline) as current_csv:
                if hashlib.sha256(current_csv.getbuffer()).hexdigest() != frozen_csv_hash:
                    raise RuntimeError(
                        "Portfolio source values changed during export; retry explicitly."
                    )
            if not _export_claim_update(
                session, claim=claim, status="completed", error=None,
                storage_key=stored.storage_key, size_bytes=stored.size_bytes,
                row_count=len(rows), completed_at=_export_now(session),
            ):
                return "busy"
            record_audit(
                session, company_id=claim.company_id, actor_membership_id=claim.membership_id,
                actor_label=context.user.full_name or context.user.email,
                action="ip_portfolio.export.completed", target_type="ip_portfolio_export_job",
                target_id=claim.job_id,
                metadata={
                    "row_count": len(rows), "size_bytes": stored.size_bytes,
                    "attempt_id": claim.token,
                },
            )
            _remaining_export_seconds(deadline)
            _commit_export(session, deadline=deadline)
            return "completed"
    except Exception as exc:  # noqa: BLE001 - durable worker failure state
        logger.warning(
            "CASEOPS_PORTFOLIO_EXPORT worker_failed job_id=%s error_type=%s",
            claim.job_id, type(exc).__name__,
        )
        # Unpublished objects are claim-unique and never reused or deleted here:
        # a lost commit acknowledgement must not delete a completed artifact.
        return _fail_portfolio_export(claim, exc)


__all__ = [
    "create_saved_view",
    "delete_saved_view",
    "enqueue_portfolio_export",
    "get_portfolio_export",
    "list_portfolio_exports",
    "list_recoverable_portfolio_exports",
    "list_legacy_unresolved_portfolio_exports",
    "list_saved_views",
    "preview_portfolio_export",
    "read_portfolio_export",
    "run_portfolio_export_job",
    "retry_portfolio_export",
    "update_saved_view",
    "validate_portfolio_columns",
]
