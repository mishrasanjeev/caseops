from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.auth import AuthContextResponse
from caseops_api.schemas.companies import (
    CompanyProfileResponse,
    CompanyProfileUpdateRequest,
    CompanyUserCreateRequest,
    CompanyUserRecord,
    CompanyUsersResponse,
    CompanyUserUpdateRequest,
)
from caseops_api.services.identity import (
    SessionContext,
    build_auth_context,
    create_company_user,
    get_company_profile,
    list_company_users,
    update_company_profile,
    update_company_user,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get(
    "/current",
    response_model=AuthContextResponse,
    summary="Get the current company context",
)
async def current_company(context: CurrentContext) -> AuthContextResponse:
    return build_auth_context(context)


@router.get(
    "/current/profile",
    response_model=CompanyProfileResponse,
    summary="Get the current company profile",
)
async def current_company_profile(context: CurrentContext) -> CompanyProfileResponse:
    return get_company_profile(context)


@router.patch(
    "/current/profile",
    response_model=CompanyProfileResponse,
    summary="Update the current company profile",
)
async def patch_current_company_profile(
    payload: CompanyProfileUpdateRequest,
    context: CurrentContext,
    session: DbSession,
) -> CompanyProfileResponse:
    return update_company_profile(session, context=context, payload=payload)


@router.get(
    "/current/users",
    response_model=CompanyUsersResponse,
    summary="List users for the current company",
)
async def current_company_users(
    context: CurrentContext,
    session: DbSession,
) -> CompanyUsersResponse:
    return list_company_users(session, context)


@router.post(
    "/current/users",
    response_model=CompanyUserRecord,
    summary="Create a user in the current company",
)
async def create_current_company_user(
    payload: CompanyUserCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> CompanyUserRecord:
    return create_company_user(session, context=context, payload=payload)


@router.patch(
    "/current/users/{membership_id}",
    response_model=CompanyUserRecord,
    summary="Update a company user's role or active status",
)
async def update_current_company_user(
    membership_id: str,
    payload: CompanyUserUpdateRequest,
    context: CurrentContext,
    session: DbSession,
) -> CompanyUserRecord:
    return update_company_user(
        session,
        context=context,
        membership_id=membership_id,
        payload=payload,
    )
