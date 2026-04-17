from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class SessionContext:
    company: Company
    user: User
    membership: CompanyMembership


def _raise_conflict(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def _raise_bad_request(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _raise_forbidden(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def _raise_unauthorized(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


def _build_auth_response(context: SessionContext) -> AuthSessionResponse:
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
    )


def build_auth_context(context: SessionContext) -> AuthContextResponse:
    return AuthContextResponse(
        company=context.company,
        user=context.user,
        membership=context.membership,
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

    return _build_auth_response(SessionContext(company=company, user=user, membership=membership))


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
        .options(joinedload(CompanyMembership.company), joinedload(CompanyMembership.user))
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
    return _build_auth_response(
        SessionContext(company=membership.company, user=membership.user, membership=membership)
    )


def get_session_context(
    session: Session,
    membership_id: str,
    *,
    token_issued_at: int | None = None,
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

    if token_issued_at is not None and membership.sessions_valid_after is not None:
        valid_after = membership.sessions_valid_after
        if valid_after.tzinfo is None:
            valid_after = valid_after.replace(tzinfo=UTC)
        if token_issued_at < int(valid_after.timestamp()):
            _raise_unauthorized("This session has been revoked. Please sign in again.")

    return SessionContext(company=membership.company, user=membership.user, membership=membership)


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

    if context.membership.id == membership.id and payload.is_active is False:
        _raise_bad_request("You cannot deactivate your own active session membership.")

    if membership.role == MembershipRole.OWNER:
        _raise_forbidden("Owner memberships cannot be modified through this endpoint.")

    if context.membership.role == MembershipRole.ADMIN:
        _raise_forbidden("Only owners can update company memberships.")

    if payload.role is not None:
        membership.role = MembershipRole(payload.role)

    if payload.is_active is not None:
        membership.is_active = payload.is_active
        membership.user.is_active = payload.is_active
        if payload.is_active is False:
            membership.sessions_valid_after = datetime.now(UTC)

    session.add(membership)
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
