from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.core.rate_limit import limiter, login_rate_limit
from caseops_api.schemas.auth import AuthContextResponse, AuthSessionResponse, LoginRequest
from caseops_api.services.identity import SessionContext, authenticate_user, build_auth_context

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.post("/login", response_model=AuthSessionResponse, summary="Login with email and password")
@limiter.limit(login_rate_limit)
async def login(
    request: Request,
    payload: LoginRequest,
    session: DbSession,
) -> AuthSessionResponse:
    return authenticate_user(
        session,
        email=str(payload.email),
        password=payload.password,
        company_slug=payload.company_slug,
    )


@router.get("/me", response_model=AuthContextResponse, summary="Get the current auth context")
async def me(context: CurrentContext) -> AuthContextResponse:
    return build_auth_context(context)
