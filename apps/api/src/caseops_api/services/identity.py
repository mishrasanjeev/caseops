from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.password_policy import WeakPasswordError, enforce_password_policy
from caseops_api.core.security import create_access_token, hash_password, verify_password
from caseops_api.db.models import Company, CompanyMembership, CompanyType, MembershipRole, User
from caseops_api.schemas.auth import AuthContextResponse, AuthSessionResponse
from caseops_api.schemas.companies import (
    BootstrapCompanyRequest,
    CompanyProfileResponse,
    CompanyProfileUpdateRequest,
    CompanyUserCreateRequest,
    CompanyUserRecord,
    CompanyUsersResponse,
    CompanyUserUpdateRequest,
)
from caseops_api.services.assignment_memberships import (
    has_other_active_company_memberships,
    lock_company_memberships_for_assignment,
    lock_user_for_membership_deactivation,
)
from caseops_api.services.employee_deactivation import (
    assert_no_operational_ip_work_before_deactivation,
    tombstone_membership_calendar_syncs_before_deactivation,
)
from caseops_api.services.session_context import SessionContext


def _raise_conflict(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def _raise_bad_request(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _raise_forbidden(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def _raise_unauthorized(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


def _resolved_capabilities(session: Session, context: SessionContext) -> list[str]:
    from caseops_api.services.capabilities import resolve_membership_capabilities

    return sorted(resolve_membership_capabilities(session, context.membership))


def _build_auth_response(session: Session, context: SessionContext) -> AuthSessionResponse:
    token = create_access_token(
        user_id=context.user.id,
        company_id=context.company.id,
        membership_id=context.membership.id,
        role=context.membership.role,
    )
    return AuthSessionResponse(
        access_token=token,
        token_type="bearer",
        company=context.company,
        user=context.user,
        membership=context.membership,
        capabilities=_resolved_capabilities(session, context),
    )


def _token_precedes_membership_cutoff(
    membership: CompanyMembership,
    *,
    token_issued_at: float,
) -> bool:
    valid_after = membership.sessions_valid_after
    if valid_after is None:
        return False
    if valid_after.tzinfo is None:
        valid_after = valid_after.replace(tzinfo=UTC)
    return token_issued_at < valid_after.timestamp()


def issue_auth_session_under_fence(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
    submitted_password: str | None = None,
    source_token_issued_at: float | None = None,
) -> AuthSessionResponse:
    """Mint a session only while holding the canonical identity fence.

    The earlier authentication/context lookup is advisory. A password reset,
    offboarding, or generic membership deactivation can commit after that
    lookup. Re-lock and populate-refresh Membership -> User immediately before
    resolving capabilities and minting the JWT so the response is serialized
    against those cutoffs.

    Login supplies ``submitted_password`` so a reset that wins the fence also
    changes the refreshed hash and makes the stale login fail. Refresh supplies
    ``source_token_issued_at`` so a cutoff that wins cannot be bypassed by
    minting a newer token from an already-revoked session.
    """

    membership = lock_company_memberships_for_assignment(
        session,
        company_id=company_id,
        membership_ids=(membership_id,),
    ).get(membership_id)
    if membership is None:
        _raise_unauthorized("The current session is no longer valid.")

    user = lock_user_for_membership_deactivation(session, membership=membership)
    company = session.scalar(
        select(Company)
        .where(Company.id == membership.company_id)
        .execution_options(populate_existing=True)
    )
    if company is None:
        _raise_unauthorized("The current session is no longer valid.")
    if not membership.is_active or not user.is_active or not company.is_active:
        _raise_forbidden("The current session is no longer active.")
    if submitted_password is not None and not verify_password(
        submitted_password,
        user.password_hash,
    ):
        _raise_unauthorized("Invalid email or password.")
    if source_token_issued_at is not None and _token_precedes_membership_cutoff(
        membership,
        token_issued_at=source_token_issued_at,
    ):
        _raise_unauthorized("This session has been revoked. Please sign in again.")

    return _build_auth_response(
        session,
        SessionContext(company=company, user=user, membership=membership),
    )


def build_auth_context(session: Session, context: SessionContext) -> AuthContextResponse:
    return AuthContextResponse(
        company=context.company,
        user=context.user,
        membership=context.membership,
        capabilities=_resolved_capabilities(session, context),
    )


def refresh_auth_session(session: Session, context: SessionContext) -> AuthSessionResponse:
    """Issue a fresh access token for a still-authenticated caller.

    Requires a valid current token (enforced by the dependency layer) so
    only live sessions can extend themselves; once a token has hard-
    expired, the client must sign in again.
    """
    if context.token_issued_at is None:
        _raise_unauthorized("The source session is missing its issuance timestamp.")
    return issue_auth_session_under_fence(
        session,
        company_id=context.company.id,
        membership_id=context.membership.id,
        source_token_issued_at=context.token_issued_at,
    )


def _require_policy_compliant_password(password: str) -> None:
    try:
        enforce_password_policy(password)
    except WeakPasswordError as exc:
        _raise_bad_request(str(exc))


def register_company_owner(
    session: Session,
    payload: BootstrapCompanyRequest,
) -> AuthSessionResponse:
    _require_policy_compliant_password(payload.owner_password)
    normalized_slug = payload.company_slug.lower().strip()
    existing_company = session.scalar(select(Company).where(Company.slug == normalized_slug))
    if existing_company:
        _raise_conflict("A company with this slug already exists.")

    existing_user = session.scalar(select(User).where(User.email == payload.owner_email.lower()))
    if existing_user:
        _raise_conflict("An account with this email already exists.")

    company = Company(
        name=payload.company_name.strip(),
        slug=normalized_slug,
        company_type=CompanyType(payload.company_type),
        tenant_key=normalized_slug,
    )
    user = User(
        email=payload.owner_email.lower(),
        full_name=payload.owner_full_name.strip(),
        password_hash=hash_password(payload.owner_password),
    )
    membership = CompanyMembership(role=MembershipRole.OWNER)
    membership.company = company
    membership.user = user

    session.add_all([company, user, membership])
    session.commit()
    session.refresh(company)
    session.refresh(user)
    session.refresh(membership)
    from caseops_api.services.platform_admin import ensure_configured_platform_super_admin

    ensure_configured_platform_super_admin(session)
    session.commit()

    return _build_auth_response(
        session,
        SessionContext(company=company, user=user, membership=membership),
    )


def authenticate_user(
    session: Session,
    *,
    email: str,
    password: str,
    company_slug: str | None = None,
) -> AuthSessionResponse:
    user = session.scalar(select(User).where(User.email == email.lower()))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        _raise_unauthorized("Invalid email or password.")

    membership_query = (
        select(CompanyMembership)
        .options(
            joinedload(CompanyMembership.company),
            joinedload(CompanyMembership.user),
            joinedload(CompanyMembership.employee_profile),
        )
        .where(CompanyMembership.user_id == user.id, CompanyMembership.is_active.is_(True))
    )

    memberships = list(session.scalars(membership_query))
    memberships = [
        membership
        for membership in memberships
        if membership.company.is_active and membership.user.is_active
    ]

    if company_slug:
        memberships = [
            membership
            for membership in memberships
            if membership.company.slug == company_slug
        ]

    if not memberships:
        _raise_forbidden("No active company membership matched this login request.")

    if len(memberships) > 1:
        _raise_bad_request("Multiple company memberships found. Please specify a company slug.")

    membership = memberships[0]
    # P1-1: the employee.login audit row + last_login stamp used to be
    # written here (synchronous INSERT + UPDATE + commit on the login
    # critical path). It is now deferred to a FastAPI BackgroundTask in
    # the /auth/login route (record_employee_login_async, fresh session).
    # Only the optional configured-founder platform-admin seed may mutate here.
    from caseops_api.services.platform_admin import ensure_configured_platform_super_admin

    ensure_configured_platform_super_admin(session)
    session.commit()
    return issue_auth_session_under_fence(
        session,
        company_id=membership.company_id,
        membership_id=membership.id,
        submitted_password=password,
    )


def get_session_context(
    session: Session,
    membership_id: str,
    *,
    token_issued_at: float | None = None,
) -> SessionContext:
    membership = session.scalar(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.company), joinedload(CompanyMembership.user))
        .where(CompanyMembership.id == membership_id)
    )
    if not membership:
        _raise_unauthorized("The current session is no longer valid.")

    if (
        not membership.is_active
        or not membership.user.is_active
        or not membership.company.is_active
    ):
        _raise_forbidden("The current session is no longer active.")

    if token_issued_at is not None and _token_precedes_membership_cutoff(
        membership,
        token_issued_at=token_issued_at,
    ):
        _raise_unauthorized("This session has been revoked. Please sign in again.")

    return SessionContext(
        company=membership.company,
        user=membership.user,
        membership=membership,
        token_issued_at=token_issued_at,
    )


def _revoke_membership_sessions(
    session: Session,
    *,
    membership: CompanyMembership,
    commit: bool = False,
) -> None:
    membership.sessions_valid_after = datetime.now(UTC)
    session.add(membership)
    if commit:
        session.commit()


def revoke_user_sessions(session: Session, *, user_id: str) -> None:
    memberships = list(
        session.scalars(
            select(CompanyMembership).where(CompanyMembership.user_id == user_id)
        )
    )
    for membership in memberships:
        _revoke_membership_sessions(session, membership=membership)
    session.commit()


def list_company_users(session: Session, context: SessionContext) -> CompanyUsersResponse:
    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(CompanyMembership.company_id == context.company.id)
            .order_by(CompanyMembership.created_at.asc())
        )
    )

    users = [
        CompanyUserRecord(
            membership_id=membership.id,
            role=membership.role,
            membership_active=membership.is_active,
            user_id=membership.user.id,
            email=membership.user.email,
            full_name=membership.user.full_name,
            user_active=membership.user.is_active,
            created_at=membership.created_at,
        )
        for membership in memberships
    ]
    return CompanyUsersResponse(
        company_id=context.company.id,
        company_slug=context.company.slug,
        users=users,
    )


def get_company_profile(context: SessionContext) -> CompanyProfileResponse:
    return CompanyProfileResponse.model_validate(context.company)


def update_company_profile(
    session: Session,
    *,
    context: SessionContext,
    payload: CompanyProfileUpdateRequest,
) -> CompanyProfileResponse:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        _raise_forbidden("Only owners and admins can update the company profile.")

    updates = payload.model_dump(exclude_unset=True)
    if "website_url" in updates and updates["website_url"] is not None:
        updates["website_url"] = str(updates["website_url"])
    for field_name, value in updates.items():
        setattr(context.company, field_name, value)

    session.add(context.company)
    session.flush()
    # IAM-adjacent audit — company profile edits are material for
    # compliance (primary contact email rotates the system-of-record
    # for legal notices).
    from caseops_api.services.audit import record_from_context

    record_from_context(
        session,
        context,
        action="company_profile.updated",
        target_type="company",
        target_id=context.company.id,
        metadata={"fields": sorted(updates.keys())},
    )
    session.commit()
    session.refresh(context.company)
    return CompanyProfileResponse.model_validate(context.company)


def create_company_user(
    session: Session,
    *,
    context: SessionContext,
    payload: CompanyUserCreateRequest,
) -> CompanyUserRecord:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        _raise_forbidden("Only owners and admins can create company users.")

    if context.membership.role == MembershipRole.ADMIN and payload.role != MembershipRole.MEMBER:
        _raise_forbidden("Admins can only create members.")

    _require_policy_compliant_password(payload.password)
    from caseops_api.services.saas_billing import assert_user_limit

    assert_user_limit(session, context=context, role=MembershipRole(payload.role))

    existing_user = session.scalar(select(User).where(User.email == payload.email.lower()))
    if existing_user:
        _raise_conflict("An account with this email already exists.")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
    )
    membership = CompanyMembership(
        company_id=context.company.id,
        role=MembershipRole(payload.role),
    )
    membership.user = user

    session.add_all([user, membership])
    session.flush()
    from caseops_api.db.models import EmployeeEmploymentStatus, EmployeeProfile

    profile = EmployeeProfile(
        company_id=context.company.id,
        membership_id=membership.id,
        employment_status=EmployeeEmploymentStatus.ACTIVE,
        force_password_change=False,
        setup_completed_at=membership.created_at,
    )
    session.add(profile)
    session.flush()
    from caseops_api.services.audit import record_from_context

    record_from_context(
        session,
        context,
        action="company_user.created",
        target_type="company_membership",
        target_id=membership.id,
        metadata={
            "email": user.email,
            "role": membership.role,
        },
    )
    session.commit()
    session.refresh(user)
    session.refresh(membership)

    return CompanyUserRecord(
        membership_id=membership.id,
        role=membership.role,
        membership_active=membership.is_active,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        user_active=user.is_active,
        created_at=membership.created_at,
    )


def update_company_user(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    payload: CompanyUserUpdateRequest,
) -> CompanyUserRecord:
    membership = session.scalar(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user), joinedload(CompanyMembership.company))
        .where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == context.company.id,
        )
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company user not found.")

    actor_membership = context.membership
    if payload.role is not None or payload.is_active is not None:
        locked_memberships = lock_company_memberships_for_assignment(
            session,
            company_id=context.company.id,
            membership_ids=(membership.id, context.membership.id),
        )
        membership = locked_memberships.get(membership.id)
        actor_membership = locked_memberships.get(context.membership.id)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company user not found.",
            )
        if (
            actor_membership is None
            or not actor_membership.is_active
            or not actor_membership.user.is_active
        ):
            _raise_forbidden("Your company membership is no longer active.")

    if actor_membership.id == membership.id and payload.is_active is False:
        _raise_bad_request("You cannot deactivate your own active session membership.")

    if membership.role == MembershipRole.OWNER:
        _raise_forbidden("Owner memberships cannot be modified through this endpoint.")

    if actor_membership.role != MembershipRole.OWNER:
        _raise_forbidden("Only owners can update company memberships.")

    if payload.is_active is False:
        lock_user_for_membership_deactivation(session, membership=membership)
        assert_no_operational_ip_work_before_deactivation(
            session,
            context=context,
            membership=membership,
        )
        tombstone_membership_calendar_syncs_before_deactivation(
            session,
            company_id=context.company.id,
            membership_id=membership.id,
        )

    if payload.role is not None:
        membership.role = MembershipRole(payload.role)

    if payload.is_active is not None:
        membership.is_active = payload.is_active
        if payload.is_active is False:
            membership.sessions_valid_after = datetime.now(UTC)
            membership.user.is_active = has_other_active_company_memberships(
                session,
                membership=membership,
            )
        else:
            membership.user.is_active = True
        from caseops_api.db.models import EmployeeEmploymentStatus, EmployeeProfile

        profile = session.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.company_id == context.company.id,
                EmployeeProfile.membership_id == membership.id,
            )
        )
        if profile is not None:
            profile.employment_status = (
                EmployeeEmploymentStatus.ACTIVE
                if payload.is_active
                else EmployeeEmploymentStatus.INACTIVE
            )

    session.add(membership)
    session.flush()
    from caseops_api.services.audit import record_from_context

    record_from_context(
        session,
        context,
        action="company_user.updated",
        target_type="company_membership",
        target_id=membership.id,
        metadata={
            "target_user_email": membership.user.email,
            "role": membership.role,
            "is_active": membership.is_active,
            "suspended_session": payload.is_active is False,
        },
    )
    session.commit()
    session.refresh(membership)
    session.refresh(membership.user)

    return CompanyUserRecord(
        membership_id=membership.id,
        role=membership.role,
        membership_active=membership.is_active,
        user_id=membership.user.id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        user_active=membership.user.is_active,
        created_at=membership.created_at,
    )
