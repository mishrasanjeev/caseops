from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
from caseops_api.services.session_context import SessionContext

PLATFORM_SUPER_ADMIN_CAPABILITIES = [
    "platform:admin",
    "platform:billing_view",
    "platform:billing_manage",
    "platform:payment_reconcile",
    "platform:plan_manage",
    "platform:usage_view",
    "platform:manual_override",
    "platform:catalog_manage",
]


def _configured_founder_user_id(
    session: Session,
    *,
    user_id: str | None = None,
) -> str | None:
    email = (get_settings().platform_super_admin_email or "").strip().lower()
    if not email:
        return None
    predicates = [
        func.lower(User.email) == email,
        User.is_active.is_(True),
        CompanyMembership.role == "owner",
        CompanyMembership.is_active.is_(True),
    ]
    if user_id is not None:
        predicates.append(User.id == user_id)
    return session.scalar(
        select(User.id)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(*predicates)
        .limit(1)
    )


def _revoke_non_founders(session: Session, *, founder_user_id: str | None) -> bool:
    now = datetime.now(UTC)
    changed = False
    rows = session.scalars(select(PlatformAdminMembership))
    for row in rows:
        if row.user_id == founder_user_id:
            continue
        if row.status == "active":
            row.status = "revoked"
            row.updated_at = now
            changed = True
    return changed


def ensure_configured_platform_super_admin(session: Session) -> PlatformAdminMembership | None:
    """Seed exactly the configured founder/company-owner platform admin.

    The user must already exist. This keeps the seed safe for empty
    environments and lets bootstrap/login create the platform identity as
    soon as the configured founder account appears.
    """
    founder_user_id = _configured_founder_user_id(session)
    if founder_user_id is None:
        if _revoke_non_founders(session, founder_user_id=None):
            session.flush()
        return None

    now = datetime.now(UTC)
    changed = False
    row = session.scalar(
        select(PlatformAdminMembership).where(
            PlatformAdminMembership.user_id == founder_user_id
        )
    )
    # Revoke any prior founder before activating or inserting the configured
    # founder, otherwise the one-active-admin constraint can reject the flush.
    if _revoke_non_founders(session, founder_user_id=founder_user_id):
        session.flush()
    if row is None:
        grace_until = now + timedelta(days=get_settings().mfa_existing_user_grace_days)
        row = PlatformAdminMembership(
            user_id=founder_user_id,
            role="super_admin",
            capabilities_json=list(PLATFORM_SUPER_ADMIN_CAPABILITIES),
            status="active",
            mfa_required=True,
            mfa_enforced_at=grace_until,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        changed = True
    else:
        desired_capabilities = list(PLATFORM_SUPER_ADMIN_CAPABILITIES)
        if row.role != "super_admin":
            row.role = "super_admin"
            changed = True
        if row.capabilities_json != desired_capabilities:
            row.capabilities_json = desired_capabilities
            changed = True
        if row.status != "active":
            row.status = "active"
            changed = True
        if not row.mfa_required:
            row.mfa_required = True
            changed = True
        if row.mfa_enforced_at is None:
            row.mfa_enforced_at = now + timedelta(days=get_settings().mfa_existing_user_grace_days)
            changed = True

    if changed:
        row.updated_at = now
        session.flush()
    return row


def platform_capabilities_for_user(session: Session, user_id: str) -> set[str]:
    """Resolve platform capabilities without mutating the request transaction."""

    founder_user_id = _configured_founder_user_id(session, user_id=user_id)
    if founder_user_id != user_id:
        return set()
    capabilities = session.scalar(
        select(PlatformAdminMembership.capabilities_json).where(
            PlatformAdminMembership.user_id == user_id,
            PlatformAdminMembership.status == "active",
        )
    )
    if capabilities is None:
        return set()
    return {str(cap).strip() for cap in capabilities if str(cap).strip()}


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
