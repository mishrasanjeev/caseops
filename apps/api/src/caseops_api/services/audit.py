"""Unified audit service (PRD §15.4 / §17.2).

Every tenant-affecting write goes through `record_audit`. The API is
intentionally minimal so callers compose rich metadata via the
`metadata` dict rather than inventing new columns.

Invariants:

- We only INSERT. No code path UPDATEs or DELETEs audit rows.
- `company_id` is always set; events without a tenant belong in
  structured logs, not here.
- `metadata` is JSON-encoded once, at write-time, so downstream
  readers (audit export) don't have to handle provider-specific
  serialisation differences.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from caseops_api.db.models import AuditActorType, AuditEvent, AuditResult
from caseops_api.services.identity import SessionContext

logger = logging.getLogger(__name__)


def record_audit(
    session: Session,
    *,
    company_id: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    actor_type: str = AuditActorType.HUMAN,
    actor_membership_id: str | None = None,
    actor_label: str | None = None,
    matter_id: str | None = None,
    result: str = AuditResult.SUCCESS,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    commit: bool = False,
) -> AuditEvent:
    """Write an audit row. The caller owns the transaction — by default
    we only `add` + `flush` so the row is visible to the same session
    without committing prematurely. Pass `commit=True` when the caller
    is outside a request scope (background jobs, CLI paths)."""
    event = AuditEvent(
        company_id=company_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_type=actor_type,
        actor_membership_id=actor_membership_id,
        actor_label=actor_label,
        matter_id=matter_id,
        result=result,
        metadata_json=json.dumps(metadata, default=str) if metadata else None,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
        created_at=datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    if commit:
        session.commit()
    return event


def record_from_context(
    session: Session,
    context: SessionContext,
    *,
    action: str,
    target_type: str,
    target_id: str | None = None,
    matter_id: str | None = None,
    result: str = AuditResult.SUCCESS,
    metadata: dict[str, Any] | None = None,
    actor_label: str | None = None,
    commit: bool = False,
) -> AuditEvent:
    """Convenience wrapper for the common request-scope path: actor is
    the signed-in membership on `context`."""
    label = actor_label
    if label is None and context.user is not None:
        full_name = getattr(context.user, "full_name", None)
        email = getattr(context.user, "email", None)
        label = full_name or email
    return record_audit(
        session,
        company_id=context.company.id,
        actor_type=AuditActorType.HUMAN,
        actor_membership_id=context.membership.id,
        actor_label=label,
        matter_id=matter_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        metadata=metadata,
        commit=commit,
    )


__all__ = [
    "record_audit",
    "record_from_context",
]
