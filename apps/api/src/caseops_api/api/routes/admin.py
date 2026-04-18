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

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from caseops_api.api.dependencies import (
    DbSession,
    require_capability,
)
from caseops_api.db.models import AuditEvent
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext

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
