from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuditEvent, Matter
from caseops_api.schemas.audit import MatterAuditEventRecord, MatterAuditListResponse
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access


def _load_visible_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _metadata(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    return decoded if isinstance(decoded, dict) else {"value": decoded}


def matter_audit_record(event: AuditEvent) -> MatterAuditEventRecord:
    return MatterAuditEventRecord(
        id=event.id,
        company_id=event.company_id,
        actor_type=event.actor_type,
        actor_membership_id=event.actor_membership_id,
        actor_label=event.actor_label,
        matter_id=event.matter_id,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        result=event.result,
        metadata=_metadata(event.metadata_json),
        request_id=event.request_id,
        created_at=event.created_at,
    )


def matter_audit_event_dict(event: AuditEvent) -> dict[str, Any]:
    return matter_audit_record(event).model_dump(mode="json")


def _audit_filters(
    *,
    context: SessionContext,
    matter_id: str,
    since: datetime | None,
    until: datetime | None,
    actor: str | None,
    action: str | None,
    keyword: str | None,
) -> list[Any]:
    filters: list[Any] = [
        AuditEvent.company_id == context.company.id,
        AuditEvent.matter_id == matter_id,
    ]
    if since is not None:
        filters.append(AuditEvent.created_at >= since)
    if until is not None:
        filters.append(AuditEvent.created_at <= until)
    if actor:
        pattern = f"%{actor.strip()}%"
        filters.append(
            or_(
                AuditEvent.actor_membership_id == actor.strip(),
                AuditEvent.actor_label.ilike(pattern),
            )
        )
    if action:
        filters.append(AuditEvent.action == action.strip())
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                AuditEvent.action.ilike(pattern),
                AuditEvent.target_type.ilike(pattern),
                AuditEvent.target_id.ilike(pattern),
                AuditEvent.actor_label.ilike(pattern),
                AuditEvent.metadata_json.ilike(pattern),
            )
        )
    return filters


def list_matter_audit_events(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
    actor: str | None = None,
    action: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> MatterAuditListResponse:
    matter = _load_visible_matter(session, context=context, matter_id=matter_id)
    safe_limit = min(max(limit, 1), 200)
    safe_offset = max(offset, 0)
    filters = _audit_filters(
        context=context,
        matter_id=matter.id,
        since=since,
        until=until,
        actor=actor,
        action=action,
        keyword=keyword,
    )
    total = session.scalar(select(func.count(AuditEvent.id)).where(*filters)) or 0
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(safe_limit)
            .offset(safe_offset)
        )
    )
    return MatterAuditListResponse(
        matter_id=matter.id,
        events=[matter_audit_record(event) for event in events],
        total=int(total),
        limit=safe_limit,
        offset=safe_offset,
    )


def export_matter_audit_events(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
    actor: str | None = None,
    action: str | None = None,
    keyword: str | None = None,
    limit: int = 10_000,
) -> list[AuditEvent]:
    matter = _load_visible_matter(session, context=context, matter_id=matter_id)
    safe_limit = min(max(limit, 1), 10_000)
    filters = _audit_filters(
        context=context,
        matter_id=matter.id,
        since=since,
        until=until,
        actor=actor,
        action=action,
        keyword=keyword,
    )
    return list(
        session.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            .limit(safe_limit)
        )
    )
