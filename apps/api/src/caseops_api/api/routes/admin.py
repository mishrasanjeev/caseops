"""Admin-scoped routes (PRD §10).

Right now: audit-export only. As §10.1/§10.2/§10.5 land they all hang
off this module under the `admin` tag.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.db.models import AuditEvent, MembershipRole
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


def _require_admin(context: SessionContext) -> None:
    """workspace:admin maps to owner or admin roles in capabilities.ts.
    Keep the server-side check inline here so a later refactor to the
    capability table doesn't silently open the endpoint up."""
    role = context.membership.role
    if role not in (MembershipRole.OWNER, MembershipRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Audit export requires admin or owner role.",
        )


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


@router.get(
    "/audit/export",
    summary="Stream the tenant audit trail as JSONL",
    response_class=StreamingResponse,
)
def export_audit_trail(
    context: CurrentContext,
    session: DbSession,
    since: str | None = None,
    until: str | None = None,
    action: str | None = None,
    limit: int | None = None,
) -> StreamingResponse:
    _require_admin(context)

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
        },
        commit=True,
    )

    def iter_jsonl():
        for event in events:
            payload = {
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
                "metadata": json.loads(event.metadata_json) if event.metadata_json else None,
                "request_id": event.request_id,
            }
            yield (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

    filename = (
        f"audit-{context.company.slug}-{datetime.now(UTC).strftime('%Y%m%d')}.jsonl"
    )
    return StreamingResponse(
        iter_jsonl(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
