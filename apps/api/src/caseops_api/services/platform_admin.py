from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CompanyMembership,
    PlatformAdminMembership,
    User,
)
from caseops_api.db.models import (
    PlatformAdminAuditEvent as PlatformAuditRow,
)
from caseops_api.services.identity import SessionContext

PLATFORM_SUPER_ADMIN_CAPABILITIES = [
    "platform:admin",
    "platform:billing_view",
    "platform:billing_manage",
    "platform:payment_reconcile",
    "platform:plan_manage",
    "platform:usage_view",
    "platform:manual_override",
]


def _configured_founder_user(session: Session) -> User | None:
    email = (get_settings().platform_super_admin_email or "").strip().lower()
    if not email:
        return None
    return session.scalar(
        select(User)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(
            func.lower(User.email) == email,
            User.is_active.is_(True),
            CompanyMembership.role == "owner",
            CompanyMembership.is_active.is_(True),
        )
        .limit(1)
    )


def _revoke_non_founders(session: Session, *, founder_user_id: str | None) -> None:
    now = datetime.now(UTC)
    rows = session.scalars(select(PlatformAdminMembership))
    for row in rows:
        if row.user_id == founder_user_id:
            continue
        if row.status == "active":
            row.status = "revoked"
            row.updated_at = now


def ensure_configured_platform_super_admin(session: Session) -> PlatformAdminMembership | None:
    """Seed exactly the configured founder/company-owner platform admin.

    The user must already exist. This keeps the seed safe for empty
    environments and lets bootstrap/login create the platform identity as
    soon as the configured founder account appears.
    """
    user = _configured_founder_user(session)
    if user is None:
        _revoke_non_founders(session, founder_user_id=None)
        session.flush()
        return None

    now = datetime.now(UTC)
    row = session.scalar(
        select(PlatformAdminMembership).where(PlatformAdminMembership.user_id == user.id)
    )
    if row is None:
        grace_until = now + timedelta(days=get_settings().mfa_existing_user_grace_days)
        row = PlatformAdminMembership(
            user_id=user.id,
            role="super_admin",
            capabilities_json=list(PLATFORM_SUPER_ADMIN_CAPABILITIES),
            status="active",
            mfa_required=True,
            mfa_enforced_at=grace_until,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.role = "super_admin"
        row.capabilities_json = list(PLATFORM_SUPER_ADMIN_CAPABILITIES)
        row.status = "active"
        row.mfa_required = True
        if row.mfa_enforced_at is None:
            row.mfa_enforced_at = now + timedelta(days=get_settings().mfa_existing_user_grace_days)
        row.updated_at = now

    # Launch rule: no second active platform admin. Keep historical rows but
    # revoke them if they are not the configured founder.
    _revoke_non_founders(session, founder_user_id=user.id)
    session.flush()
    return row


def platform_capabilities_for_user(session: Session, user_id: str) -> set[str]:
    founder = ensure_configured_platform_super_admin(session)
    if founder is None or founder.user_id != user_id:
        return set()
    row = session.scalar(
        select(PlatformAdminMembership).where(
            PlatformAdminMembership.user_id == user_id,
            PlatformAdminMembership.status == "active",
        )
    )
    if row is None:
        return set()
    return {str(cap).strip() for cap in (row.capabilities_json or []) if str(cap).strip()}


def require_platform_admin(
    session: Session,
    context: SessionContext,
    *,
    capability: str = "platform:admin",
) -> PlatformAdminMembership:
    founder = ensure_configured_platform_super_admin(session)
    row = session.scalar(
        select(PlatformAdminMembership).where(
            PlatformAdminMembership.user_id == context.user.id,
            PlatformAdminMembership.status == "active",
        )
    )
    if (
        founder is None
        or row is None
        or row.user_id != founder.user_id
        or capability not in (row.capabilities_json or [])
    ):
        session.add(
            PlatformAuditRow(
                platform_admin_id=row.id if row else None,
                actor_user_id=context.user.id,
                actor_membership_id=context.membership.id,
                company_id=context.company.id,
                action="platform.access_denied",
                target_type="platform_admin",
                result="denied",
                reason=f"missing capability {capability}",
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Founder-only platform administrator access is required.",
        )
    from caseops_api.services.security import enforce_platform_mfa

    enforce_platform_mfa(session, context=context, platform_admin=row)
    return row


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


def platform_admin_summary(row: PlatformAdminMembership) -> dict[str, object]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "role": row.role,
        "capabilities": list(row.capabilities_json or []),
        "status": row.status,
        "mfa_required": row.mfa_required,
        "mfa_enforced_at": row.mfa_enforced_at,
    }


def membership_user_id(membership: CompanyMembership) -> str:
    return str(membership.user_id)
