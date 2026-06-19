from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from caseops_api.db.models import (
    PlatformAdminAuditEvent as PlatformAuditRow,
)
from caseops_api.db.models import (
    PlatformAdminMembership,
)
from caseops_api.services.session_context import SessionContext


def record_platform_audit(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    company_id: str | None = None,
    result: str = "success",
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PlatformAuditRow:
    event = PlatformAuditRow(
        platform_admin_id=platform_admin.id if platform_admin else None,
        actor_user_id=context.user.id if context.user else None,
        actor_membership_id=context.membership.id,
        company_id=company_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        reason=reason,
        metadata_json=metadata,
    )
    session.add(event)
    session.flush()
    return event
