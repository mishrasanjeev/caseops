from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import CompanyMembership, CustomRole, MembershipRole
from caseops_api.schemas.custom_roles import (
    CapabilityCatalogResponse,
    CapabilityRecord,
    CustomRoleCreateRequest,
    CustomRoleListResponse,
    CustomRoleRecord,
    CustomRoleUpdateRequest,
    EmployeeCustomRoleAssignRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import (
    bump_membership_sessions,
    custom_role_capabilities_allowed,
    known_capabilities,
    owner_only_capabilities,
    validate_custom_role_permissions,
)
from caseops_api.services.identity import SessionContext

_GROUP_LABELS: dict[str, str] = {
    "matters": "Matters",
    "conflicts": "Conflicts",
    "invoices": "Billing",
    "payments": "Billing",
    "time_entries": "Billing",
    "company": "Workspace",
    "workspace": "Workspace",
    "teams": "Workspace",
    "matter_access": "Workspace",
    "documents": "Documents",
    "contracts": "Contracts",
    "outside_counsel": "Outside counsel",
    "drafts": "Drafting",
    "hearing_packs": "Hearings",
    "court_sync": "Hearings",
    "recommendations": "Recommendations",
    "strategy": "Recommendations",
    "ai": "Recommendations",
    "authorities": "Research",
    "audit": "Audit",
    "intake": "Intake",
    "clients": "Clients",
    "communications": "Communications",
    "email_templates": "Communications",
    "portal": "External portal",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower().strip()).strip("-")
    return slug or "custom-role"


def _unique_slug(
    session: Session,
    *,
    company_id: str,
    name: str,
    exclude_id: str | None = None,
) -> str:
    base = _slugify(name)
    slug = base
    suffix = 2
    while True:
        query = select(CustomRole.id).where(
            CustomRole.company_id == company_id,
            CustomRole.slug == slug,
        )
        if exclude_id is not None:
            query = query.where(CustomRole.id != exclude_id)
        existing = session.scalar(query)
        if existing is None:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


def _record(role: CustomRole, assigned_count: int = 0) -> CustomRoleRecord:
    return CustomRoleRecord(
        id=role.id,
        company_id=role.company_id,
        name=role.name,
        slug=role.slug,
        description=role.description,
        base_role=role.base_role,  # type: ignore[arg-type]
        permissions=sorted(str(item) for item in role.permissions_json),
        is_system=role.is_system,
        is_active=role.is_active and role.revoked_at is None,
        assigned_count=assigned_count,
        created_by_membership_id=role.created_by_membership_id,
        updated_by_membership_id=role.updated_by_membership_id,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def _load_role(
    session: Session,
    *,
    company_id: str,
    role_id: str,
    include_inactive: bool = False,
) -> CustomRole:
    query = select(CustomRole).where(
        CustomRole.id == role_id,
        CustomRole.company_id == company_id,
    )
    if not include_inactive:
        query = query.where(CustomRole.is_active.is_(True), CustomRole.revoked_at.is_(None))
    role = session.scalar(query)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom role not found.",
        )
    return role


def _assigned_counts(session: Session, *, company_id: str) -> dict[str, int]:
    rows = session.execute(
        select(CompanyMembership.custom_role_id, func.count(CompanyMembership.id))
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.custom_role_id.is_not(None),
        )
        .group_by(CompanyMembership.custom_role_id)
    ).all()
    return {str(role_id): int(count) for role_id, count in rows if role_id is not None}


def list_capability_catalog() -> CapabilityCatalogResponse:
    owner_only = owner_only_capabilities()
    delegable = custom_role_capabilities_allowed()
    rows: list[CapabilityRecord] = []
    for capability in sorted(known_capabilities()):
        prefix = capability.split(":", 1)[0]
        group = _GROUP_LABELS.get(prefix, prefix.replace("_", " ").title())
        label = capability.split(":", 1)[-1].replace("_", " ").replace(":", " ")
        is_owner_only = capability in owner_only
        is_delegable = capability in delegable
        if is_delegable:
            protected_reason: str | None = None
        elif is_owner_only:
            protected_reason = (
                "Reserved for the fixed Owner role; cannot be granted via a custom role."
            )
        else:
            protected_reason = (
                "Non-delegable administrative capability; the backend will reject any "
                "custom role that includes it."
            )
        rows.append(
            CapabilityRecord(
                capability=capability,
                group=group,
                label=label,
                owner_only=is_owner_only,
                custom_role_delegable=is_delegable,
                protected_reason=protected_reason,
            )
        )
    return CapabilityCatalogResponse(capabilities=rows)


def list_custom_roles(
    session: Session,
    *,
    context: SessionContext,
    include_inactive: bool = False,
) -> CustomRoleListResponse:
    query = select(CustomRole).where(CustomRole.company_id == context.company.id)
    if not include_inactive:
        query = query.where(CustomRole.is_active.is_(True), CustomRole.revoked_at.is_(None))
    roles = list(session.scalars(query.order_by(CustomRole.name.asc(), CustomRole.id.asc())))
    counts = _assigned_counts(session, company_id=context.company.id)
    return CustomRoleListResponse(
        roles=[_record(role, counts.get(role.id, 0)) for role in roles]
    )


def get_custom_role(
    session: Session,
    *,
    context: SessionContext,
    role_id: str,
) -> CustomRoleRecord:
    role = _load_role(session, company_id=context.company.id, role_id=role_id)
    counts = _assigned_counts(session, company_id=context.company.id)
    return _record(role, counts.get(role.id, 0))


def create_custom_role(
    session: Session,
    *,
    context: SessionContext,
    payload: CustomRoleCreateRequest,
) -> CustomRoleRecord:
    permissions = validate_custom_role_permissions(
        session,
        context.membership,
        payload.permissions,
    )
    now = _now()
    role = CustomRole(
        company_id=context.company.id,
        name=payload.name.strip(),
        slug=_unique_slug(session, company_id=context.company.id, name=payload.name),
        description=payload.description,
        base_role=payload.base_role,
        permissions_json=permissions,
        is_system=False,
        is_active=True,
        created_by_membership_id=context.membership.id,
        updated_by_membership_id=context.membership.id,
        created_at=now,
        updated_at=now,
    )
    session.add(role)
    session.flush()
    record_from_context(
        session,
        context,
        action="custom_role.created",
        target_type="custom_role",
        target_id=role.id,
        metadata={
            "name": role.name,
            "base_role": role.base_role,
            "permissions": permissions,
        },
    )
    session.commit()
    session.refresh(role)
    return _record(role)


def update_custom_role(
    session: Session,
    *,
    context: SessionContext,
    role_id: str,
    payload: CustomRoleUpdateRequest,
) -> CustomRoleRecord:
    role = _load_role(
        session,
        company_id=context.company.id,
        role_id=role_id,
        include_inactive=True,
    )
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System roles cannot be edited.",
        )
    before = _record(role, _assigned_counts(session, company_id=context.company.id).get(role.id, 0))
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return before

    if payload.name is not None:
        role.name = payload.name.strip()
        role.slug = _unique_slug(
            session,
            company_id=context.company.id,
            name=payload.name,
            exclude_id=role.id,
        )
    if "description" in updates:
        role.description = payload.description
    if "base_role" in updates:
        role.base_role = payload.base_role
    if payload.permissions is not None:
        role.permissions_json = validate_custom_role_permissions(
            session,
            context.membership,
            payload.permissions,
        )
    else:
        validate_custom_role_permissions(session, context.membership, role.permissions_json)
    if payload.is_active is not None:
        role.is_active = payload.is_active
        if not payload.is_active:
            role.revoked_at = _now()
        elif role.revoked_at is not None:
            role.revoked_at = None
    role.updated_by_membership_id = context.membership.id
    role.updated_at = _now()
    session.flush()
    affected = _invalidate_assigned_memberships(session, context=context, role_id=role.id)
    after = _record(role, affected)
    record_from_context(
        session,
        context,
        action="custom_role.updated",
        target_type="custom_role",
        target_id=role.id,
        metadata={
            "before": before.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
            "affected_memberships": affected,
        },
    )
    session.commit()
    session.refresh(role)
    return _record(role, affected)


def delete_custom_role(
    session: Session,
    *,
    context: SessionContext,
    role_id: str,
) -> CustomRoleRecord:
    role = _load_role(
        session,
        company_id=context.company.id,
        role_id=role_id,
        include_inactive=True,
    )
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System roles cannot be revoked.",
        )
    role.is_active = False
    role.revoked_at = _now()
    role.updated_by_membership_id = context.membership.id
    role.updated_at = _now()
    affected = _invalidate_assigned_memberships(
        session,
        context=context,
        role_id=role.id,
    )
    record_from_context(
        session,
        context,
        action="custom_role.revoked",
        target_type="custom_role",
        target_id=role.id,
        metadata={
            "affected_memberships": affected,
            "name": role.name,
            "retained_assignments_fail_closed": True,
        },
    )
    session.commit()
    session.refresh(role)
    return _record(role, 0)


def _invalidate_assigned_memberships(
    session: Session,
    *,
    context: SessionContext,
    role_id: str,
    clear_assignment: bool = False,
) -> int:
    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.custom_role_id == role_id,
            )
        )
    )
    for membership in memberships:
        bump_membership_sessions(membership)
        if clear_assignment:
            membership.custom_role_id = None
        session.add(membership)
    return len(memberships)


def assign_employee_custom_role(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    payload: EmployeeCustomRoleAssignRequest,
) -> CustomRoleRecord | None:
    membership = session.scalar(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user), joinedload(CompanyMembership.custom_role))
        .where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == context.company.id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found.",
        )
    if membership.role == MembershipRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner memberships cannot receive custom roles.",
        )
    role: CustomRole | None = None
    if payload.custom_role_id is None:
        if context.membership.role != MembershipRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners can clear custom role assignments.",
            )
    else:
        role = _load_role(
            session,
            company_id=context.company.id,
            role_id=payload.custom_role_id,
        )
        validate_custom_role_permissions(session, context.membership, role.permissions_json)
    before_custom_role_id = membership.custom_role_id
    membership.custom_role_id = role.id if role is not None else None
    bump_membership_sessions(membership)
    session.flush()
    record_from_context(
        session,
        context,
        action=(
            "employee.custom_role.assigned"
            if role is not None
            else "employee.custom_role.unassigned"
        ),
        target_type="employee",
        target_id=membership.id,
        metadata={
            "email": membership.user.email,
            "before_custom_role_id": before_custom_role_id,
            "after_custom_role_id": membership.custom_role_id,
        },
    )
    session.commit()
    if role is None:
        return None
    session.refresh(role)
    return _record(role, _assigned_counts(session, company_id=context.company.id).get(role.id, 0))
