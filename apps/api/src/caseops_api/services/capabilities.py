from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import CompanyMembership, CustomRole, MembershipRole

_NON_DELEGABLE_CUSTOM_ROLE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "workspace:admin",
        "company:manage_profile",
        "matter_access:manage",
        "teams:manage",
        "email_templates:manage",
        "portal:invite",
        "portal:manage_grants",
    }
)
_OWNER_DELEGABLE_ADMIN_CAPABILITIES: frozenset[str] = frozenset(
    {
        "company:manage_users",
    }
)


def _catalog() -> dict[str, frozenset[MembershipRole]]:
    from caseops_api.api.dependencies import CAPABILITY_ROLES

    return CAPABILITY_ROLES


def known_capabilities() -> set[str]:
    return set(_catalog())


def owner_only_capabilities() -> set[str]:
    return {
        capability
        for capability, roles in _catalog().items()
        if roles == frozenset({MembershipRole.OWNER})
    }


def custom_role_capabilities_allowed() -> set[str]:
    known = known_capabilities()
    return (
        known
        - owner_only_capabilities()
        - _NON_DELEGABLE_CUSTOM_ROLE_CAPABILITIES
    ) | (_OWNER_DELEGABLE_ADMIN_CAPABILITIES & known)


def static_capabilities_for_role(role: str | MembershipRole) -> set[str]:
    try:
        membership_role = MembershipRole(role)
    except ValueError:
        return set()
    return {
        capability
        for capability, roles in _catalog().items()
        if membership_role in roles
    }


def list_static_capabilities(roles: Iterable[MembershipRole]) -> list[str]:
    role_set = frozenset(roles)
    return sorted(cap for cap, rs in _catalog().items() if role_set & rs)


def validate_custom_role_permissions(
    session: Session,
    actor_membership: CompanyMembership,
    permissions: Iterable[str],
) -> list[str]:
    """Validate and canonicalize custom-role permissions.

    V1 custom roles are templates over approved non-owner capabilities only.
    Owner-only capabilities remain tied to the fixed owner role, so owners
    themselves cannot accidentally delegate audit export or invoice voiding.
    """

    known = known_capabilities()
    allowed = custom_role_capabilities_allowed()
    try:
        actor_role = MembershipRole(actor_membership.role)
    except ValueError:
        actor_role = None
    if actor_role == MembershipRole.OWNER:
        delegable = allowed
    else:
        delegable = resolve_membership_capabilities(session, actor_membership) & (
            allowed - _OWNER_DELEGABLE_ADMIN_CAPABILITIES
        )
    cleaned: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    protected: list[str] = []
    not_delegable: list[str] = []
    for raw in permissions:
        if not isinstance(raw, str):
            invalid.append(str(raw))
            continue
        permission = raw.strip()
        if not permission or permission not in known:
            invalid.append(raw)
            continue
        if permission not in allowed:
            protected.append(permission)
            continue
        if permission not in delegable:
            not_delegable.append(permission)
            continue
        if permission not in seen:
            cleaned.append(permission)
            seen.add(permission)

    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or malformed capabilities: {sorted(invalid)}",
        )
    if protected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Custom roles cannot include protected capabilities: "
                + ", ".join(sorted(protected))
            ),
        )
    if not_delegable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You cannot delegate capabilities you do not hold or that are "
                "not delegable: "
                + ", ".join(sorted(not_delegable))
            ),
        )
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Custom roles require at least one approved capability.",
        )
    return sorted(cleaned)


def can_assign_capabilities(
    session: Session,
    actor_membership: CompanyMembership,
    permissions: Iterable[str],
) -> bool:
    try:
        validate_custom_role_permissions(session, actor_membership, permissions)
    except HTTPException:
        return False
    return True


def custom_role_permissions_are_valid(permissions: object) -> bool:
    if not isinstance(permissions, list):
        return False
    known = known_capabilities()
    allowed = custom_role_capabilities_allowed()
    for item in permissions:
        if not isinstance(item, str):
            return False
        permission = item.strip()
        if not permission or permission not in known or permission not in allowed:
            return False
    return True


def resolve_membership_capabilities(
    session: Session,
    membership: CompanyMembership,
) -> set[str]:
    if not membership.is_active:
        return set()

    try:
        role = MembershipRole(membership.role)
    except ValueError:
        return set()

    static = static_capabilities_for_role(role)
    try:
        from caseops_api.services.platform_admin import platform_capabilities_for_user

        static = static | platform_capabilities_for_user(session, membership.user_id)
    except Exception:
        # Platform-admin capability resolution must never make ordinary tenant
        # sessions unusable. The platform routes still enforce their own DB gate.
        static = set(static)
    if role == MembershipRole.OWNER:
        return static

    custom_role_id = getattr(membership, "custom_role_id", None)
    if not custom_role_id:
        return static

    custom_role = getattr(membership, "custom_role", None)
    if custom_role is None:
        custom_role = session.scalar(
            select(CustomRole).where(
                CustomRole.id == custom_role_id,
                CustomRole.company_id == membership.company_id,
            )
        )
    if (
        custom_role is None
        or custom_role.company_id != membership.company_id
        or not custom_role.is_active
        or custom_role.revoked_at is not None
        or not custom_role_permissions_are_valid(custom_role.permissions_json)
    ):
        return set()
    return {str(permission).strip() for permission in custom_role.permissions_json}


def membership_has_capability(
    session: Session,
    membership: CompanyMembership,
    capability: str,
) -> bool:
    if capability not in known_capabilities():
        return False
    return capability in resolve_membership_capabilities(session, membership)


def bump_membership_sessions(membership: CompanyMembership) -> None:
    membership.sessions_valid_after = datetime.now(UTC)
