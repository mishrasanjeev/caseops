"""Admin-scoped routes (PRD §10).

Right now: audit-export only. As §10.1/§10.2/§10.5 land they all hang
off this module under the `admin` tag.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from caseops_api.api.dependencies import (
    DbSession,
    require_capability,
)
from caseops_api.db.models import AuditEvent, AuditExportJob
from caseops_api.schemas.ai_token_governance import (
    AITokenGovernancePatchRequest,
    AITokenGovernanceSummary,
)
from caseops_api.schemas.audit import (
    AuditExportAsyncRequest,
    AuditExportJobListResponse,
    AuditExportJobRecord,
)
from caseops_api.schemas.calendar import (
    OutlookReadinessTestResponse,
    OutlookTenantConfigurationResponse,
    OutlookTenantConfigurationUpdateRequest,
)
from caseops_api.schemas.storage_governance import (
    FirmStorageQuotaPatchRequest,
    FirmStorageUsageSummary,
)
from caseops_api.services.ai_token_governance import (
    get_ai_token_governance_summary,
    update_ai_token_governance,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.audit_exports import (
    enqueue_export,
    get_export_job,
    list_export_jobs,
    read_export_bytes,
    run_export_job,
)
from caseops_api.services.calendar_sync import (
    outlook_tenant_configuration_status,
    test_outlook_tenant_configuration,
    update_outlook_tenant_configuration,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.storage_governance import (
    get_firm_storage_summary,
    update_firm_storage_quota,
)

router = APIRouter()
# Capability gate: the dependency itself rejects with 403 before the
# handler runs, so the handler receives an already-authorised context.
AuditExporter = Annotated[SessionContext, Depends(require_capability("audit:export"))]


def _parse_iso(value: str | None, *, field: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} must be an ISO-8601 timestamp.",
        ) from exc


_AUDIT_COLUMNS = [
    "id",
    "created_at",
    "company_id",
    "actor_type",
    "actor_membership_id",
    "actor_label",
    "matter_id",
    "action",
    "target_type",
    "target_id",
    "result",
    "metadata",
    "request_id",
]


def _event_row(event: AuditEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "created_at": event.created_at.isoformat(),
        "company_id": event.company_id,
        "actor_type": event.actor_type,
        "actor_membership_id": event.actor_membership_id,
        "actor_label": event.actor_label,
        "matter_id": event.matter_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "result": event.result,
        "metadata": (
            json.loads(event.metadata_json) if event.metadata_json else None
        ),
        "request_id": event.request_id,
    }


@router.get(
    "/audit/export",
    summary="Stream the tenant audit trail as JSONL or CSV",
    response_class=StreamingResponse,
)
def export_audit_trail(
    context: AuditExporter,
    session: DbSession,
    since: str | None = None,
    until: str | None = None,
    action: str | None = None,
    limit: int | None = None,
    format: Literal["jsonl", "csv"] = "jsonl",
) -> StreamingResponse:
    since_dt = _parse_iso(since, field="since")
    until_dt = _parse_iso(until, field="until")
    if since_dt is None and until_dt is None:
        # Default to the last 30 days so accidental clicks don't stream
        # the entire history of a busy tenant.
        until_dt = datetime.now(UTC)
        since_dt = until_dt - timedelta(days=30)

    stmt = (
        select(AuditEvent)
        .where(AuditEvent.company_id == context.company.id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    if since_dt is not None:
        stmt = stmt.where(AuditEvent.created_at >= since_dt)
    if until_dt is not None:
        stmt = stmt.where(AuditEvent.created_at <= until_dt)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if limit is not None and limit > 0:
        stmt = stmt.limit(min(limit, 100_000))

    events = list(session.scalars(stmt))

    # Record the export itself so compliance can see who downloaded what.
    record_from_context(
        session,
        context,
        action="audit.exported",
        target_type="audit_export",
        target_id=None,
        metadata={
            "since": since_dt.isoformat() if since_dt else None,
            "until": until_dt.isoformat() if until_dt else None,
            "action_filter": action,
            "row_count": len(events),
            "format": format,
        },
        commit=True,
    )

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    filename_base = f"audit-{context.company.slug}-{stamp}"

    if format == "csv":
        def iter_csv():
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=_AUDIT_COLUMNS)
            writer.writeheader()
            yield buffer.getvalue().encode("utf-8")
            for event in events:
                buffer.seek(0)
                buffer.truncate()
                row = _event_row(event)
                row["metadata"] = (
                    json.dumps(row["metadata"], separators=(",", ":"))
                    if row["metadata"] is not None
                    else ""
                )
                writer.writerow(row)
                yield buffer.getvalue().encode("utf-8")

        return StreamingResponse(
            iter_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.csv"'
            },
        )

    def iter_jsonl():
        for event in events:
            yield (
                json.dumps(_event_row(event), separators=(",", ":")) + "\n"
            ).encode("utf-8")

    return StreamingResponse(
        iter_jsonl(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_base}.jsonl"'
        },
    )


# ---------------------------------------------------------------------------
# Async export (§10.4)
# ---------------------------------------------------------------------------


def _job_record(job: AuditExportJob) -> AuditExportJobRecord:
    return AuditExportJobRecord(
        id=job.id,
        company_id=job.company_id,
        status=job.status,  # type: ignore[arg-type]
        format=job.format,  # type: ignore[arg-type]
        since=job.since,
        until=job.until,
        action_filter=job.action_filter,
        row_limit=job.row_limit,
        row_count=job.row_count,
        size_bytes=job.size_bytes,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        download_ready=bool(job.storage_key) and job.status == "completed",
    )


@router.post(
    "/audit/export/async",
    response_model=AuditExportJobRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue an async audit-trail export job",
    description=(
        "Creates an `AuditExportJob` row and schedules the worker. "
        "Respond with `202 Accepted` and the fresh job record. "
        "Poll `GET /api/admin/audit/export/jobs/{id}` for status; "
        "download with `GET /api/admin/audit/export/jobs/{id}/download` "
        "once `download_ready=true`. Use this path for tenants with "
        "millions of rows — the streaming sync endpoint stays the "
        "default for small exports."
    ),
)
def enqueue_audit_export(
    payload: AuditExportAsyncRequest,
    context: AuditExporter,
    session: DbSession,
    background_tasks: BackgroundTasks,
) -> AuditExportJobRecord:
    since_dt = payload.since
    until_dt = payload.until
    if since_dt is None and until_dt is None:
        until_dt = datetime.now(UTC)
        since_dt = until_dt - timedelta(days=30)
    job = enqueue_export(
        session,
        context=context,
        fmt=payload.format,
        since=since_dt,
        until=until_dt,
        action_filter=payload.action,
        row_limit=payload.row_limit,
    )
    # BackgroundTasks runs after the response is returned. A separate
    # caseops-audit-exporter CLI (or Cloud Tasks / Temporal) can also
    # drive run_export_job against the same row.
    background_tasks.add_task(run_export_job, job.id)
    return _job_record(job)


@router.get(
    "/audit/export/jobs",
    response_model=AuditExportJobListResponse,
    summary="List this tenant's audit-export jobs",
)
def list_audit_export_jobs(
    context: AuditExporter,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> AuditExportJobListResponse:
    jobs = list_export_jobs(session, context=context, limit=limit)
    return AuditExportJobListResponse(jobs=[_job_record(j) for j in jobs])


@router.get(
    "/audit/export/jobs/{job_id}",
    response_model=AuditExportJobRecord,
    summary="Get the status of an audit-export job",
)
def get_audit_export_job(
    job_id: str,
    context: AuditExporter,
    session: DbSession,
) -> AuditExportJobRecord:
    job = get_export_job(session, context=context, job_id=job_id)
    return _job_record(job)


@router.get(
    "/audit/export/jobs/{job_id}/download",
    response_class=StreamingResponse,
    summary="Stream the artifact of a completed audit-export job",
)
def download_audit_export_job(
    job_id: str,
    context: AuditExporter,
    session: DbSession,
) -> StreamingResponse:
    job = get_export_job(session, context=context, job_id=job_id)
    stream = read_export_bytes(job)
    ext = (job.format or "jsonl").lower()
    media = "text/csv" if ext == "csv" else "application/x-ndjson"
    filename = f"audit-{job.id}.{ext}"
    return StreamingResponse(
        stream,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Tenant AI policy (PG-107) — workspace owner/admin can flip the
# predictive-bench-strategy gate. Default = false (evidence-only).
# ---------------------------------------------------------------------------


from pydantic import BaseModel  # noqa: E402

from caseops_api.db.models import TenantAIPolicy  # noqa: E402

WorkspaceAdmin = Annotated[
    SessionContext, Depends(require_capability("workspace:admin"))
]


@router.get(
    "/outlook-configuration",
    response_model=OutlookTenantConfigurationResponse,
    summary=(
        "Read the tenant Outlook provider readiness gate without exposing "
        "credential values."
    ),
)
def get_outlook_configuration(
    context: WorkspaceAdmin,
    session: DbSession,
) -> OutlookTenantConfigurationResponse:
    return outlook_tenant_configuration_status(session, context=context)


@router.patch(
    "/outlook-configuration",
    response_model=OutlookTenantConfigurationResponse,
    summary=(
        "Configure tenant Outlook OAuth readiness. Values are accepted from "
        "workspace admins but never echoed back."
    ),
)
def patch_outlook_configuration(
    payload: OutlookTenantConfigurationUpdateRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> OutlookTenantConfigurationResponse:
    return update_outlook_tenant_configuration(
        session,
        context=context,
        payload=payload,
    )


@router.post(
    "/outlook-configuration/test",
    response_model=OutlookReadinessTestResponse,
    summary=(
        "Run a safe Outlook provider readiness probe for the current "
        "workspace admin."
    ),
)
def post_outlook_configuration_test(
    context: WorkspaceAdmin,
    session: DbSession,
) -> OutlookReadinessTestResponse:
    return test_outlook_tenant_configuration(session, context=context)


@router.get(
    "/storage-governance",
    response_model=FirmStorageUsageSummary,
    summary="Read firm storage usage, quota, and matter/file rollups.",
)
def get_storage_governance(
    context: WorkspaceAdmin,
    session: DbSession,
) -> FirmStorageUsageSummary:
    return get_firm_storage_summary(
        session,
        company_id=context.company.id,
        context=context,
    )


@router.patch(
    "/storage-governance",
    response_model=FirmStorageUsageSummary,
    summary="Update this firm's storage quota. Null quota means unlimited.",
)
def patch_storage_governance(
    payload: FirmStorageQuotaPatchRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> FirmStorageUsageSummary:
    return update_firm_storage_quota(
        session,
        context=context,
        quota_bytes=payload.quota_bytes,
    )


@router.get(
    "/ai-token-governance",
    response_model=AITokenGovernanceSummary,
    summary="Read firm AI token usage, quota, and ModelRun rollups.",
)
def get_ai_token_governance(
    context: WorkspaceAdmin,
    session: DbSession,
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
) -> AITokenGovernanceSummary:
    period_start = _parse_iso(since, field="since")
    period_end = _parse_iso(until, field="until")
    if period_start is not None and period_end is not None and period_start >= period_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since must be earlier than until.",
        )
    return get_ai_token_governance_summary(
        session,
        company_id=context.company.id,
        period_start=period_start,
        period_end=period_end,
    )


@router.patch(
    "/ai-token-governance",
    response_model=AITokenGovernanceSummary,
    summary="Update monthly AI token quotas. Null quota means unlimited.",
)
def patch_ai_token_governance(
    payload: AITokenGovernancePatchRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> AITokenGovernanceSummary:
    return update_ai_token_governance(
        session,
        context=context,
        firm_quota_tokens=payload.firm_quota_tokens,
        user_quota_tokens=payload.user_quota_tokens,
        warning_threshold_percent=payload.warning_threshold_percent,
    )


class TenantAIPolicyResponse(BaseModel):
    company_id: str
    predictive_bench_strategy_enabled: bool
    # PG-005 Sprint 11 (2026-05-01) — admin-disabled drafting templates.
    disabled_template_types: list[str] = []


class TenantAIPolicyPatchRequest(BaseModel):
    predictive_bench_strategy_enabled: bool | None = None
    disabled_template_types: list[str] | None = None


def _ensure_policy_row(session, company_id: str) -> TenantAIPolicy:
    row = session.scalar(
        select(TenantAIPolicy).where(TenantAIPolicy.company_id == company_id)
    )
    if row is None:
        row = TenantAIPolicy(company_id=company_id)
        session.add(row)
        session.flush()
    return row


def _parse_disabled_templates(raw: str | None) -> list[str]:
    import json

    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [
        str(x) for x in parsed if isinstance(x, str)
    ] if isinstance(parsed, list) else []


@router.get(
    "/tenant-ai-policy",
    response_model=TenantAIPolicyResponse,
    summary="Read this workspace's AI policy (PG-107 + Sprint 11 governance).",
)
def get_tenant_ai_policy(
    context: WorkspaceAdmin,
    session: DbSession,
) -> TenantAIPolicyResponse:
    row = _ensure_policy_row(session, context.company.id)
    return TenantAIPolicyResponse(
        company_id=row.company_id,
        predictive_bench_strategy_enabled=bool(
            getattr(row, "predictive_bench_strategy_enabled", False)
        ),
        disabled_template_types=_parse_disabled_templates(
            getattr(row, "disabled_template_types_json", None)
        ),
    )


@router.patch(
    "/tenant-ai-policy",
    response_model=TenantAIPolicyResponse,
    summary=(
        "Toggle predictive bench analytics + admin-disabled templates "
        "for this workspace (PG-107 + Sprint 11). Owner/admin only."
    ),
)
def patch_tenant_ai_policy(
    payload: TenantAIPolicyPatchRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> TenantAIPolicyResponse:
    import json

    row = _ensure_policy_row(session, context.company.id)
    audit_metadata: dict = {}

    if payload.predictive_bench_strategy_enabled is not None:
        before = bool(getattr(row, "predictive_bench_strategy_enabled", False))
        row.predictive_bench_strategy_enabled = bool(
            payload.predictive_bench_strategy_enabled
        )
        audit_metadata["predictive_bench_strategy_enabled"] = {
            "before": before,
            "after": bool(payload.predictive_bench_strategy_enabled),
        }

    if payload.disabled_template_types is not None:
        before_list = _parse_disabled_templates(
            getattr(row, "disabled_template_types_json", None)
        )
        # Validate each value against the canonical DraftTemplateType set
        # so a typo can't silently disable nothing.
        from caseops_api.schemas.drafting_templates import DraftTemplateType

        valid_types = {t.value for t in DraftTemplateType}
        cleaned: list[str] = []
        for t in payload.disabled_template_types:
            if t in valid_types and t not in cleaned:
                cleaned.append(t)
        row.disabled_template_types_json = json.dumps(cleaned)
        audit_metadata["disabled_template_types"] = {
            "before": before_list,
            "after": cleaned,
        }

    session.flush()
    if audit_metadata:
        record_from_context(
            session,
            context,
            action="tenant_ai_policy.updated",
            target_type="tenant_ai_policy",
            target_id=row.id,
            metadata=audit_metadata,
        )
    session.commit()
    return TenantAIPolicyResponse(
        company_id=row.company_id,
        predictive_bench_strategy_enabled=bool(
            row.predictive_bench_strategy_enabled
        ),
        disabled_template_types=_parse_disabled_templates(
            getattr(row, "disabled_template_types_json", None)
        ),
    )
