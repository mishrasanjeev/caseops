from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.core.cookies import (
    clear_session_cookies,
    issue_session_cookies,
)
from caseops_api.core.rate_limit import limiter, login_rate_limit
from caseops_api.core.settings import get_settings
from caseops_api.schemas.auth import AuthContextResponse, AuthSessionResponse, LoginRequest
from caseops_api.services.identity import (
    SessionContext,
    authenticate_user,
    build_auth_context,
    refresh_auth_session,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


def _ttl_seconds() -> int:
    return get_settings().access_token_ttl_minutes * 60


@router.post("/login", response_model=AuthSessionResponse, summary="Login with email and password")
@limiter.limit(login_rate_limit)
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    session: DbSession,
) -> AuthSessionResponse:
    auth = authenticate_user(
        session,
        email=str(payload.email),
        password=payload.password,
        company_slug=payload.company_slug,
    )
    # EG-001: set the HttpOnly session cookie + JS-readable CSRF
    # cookie. The body still carries access_token for one release so
    # SDKs / automation that already use Bearer auth keep working
    # while the web client transitions to the cookie path.
    settings = get_settings()
    issue_session_cookies(
        response,
        access_token=auth.access_token,
        ttl_seconds=_ttl_seconds(),
        env=settings.env,
    )
    return auth


@router.get("/me", response_model=AuthContextResponse, summary="Get the current auth context")
async def me(context: CurrentContext) -> AuthContextResponse:
    return build_auth_context(context)


@router.post(
    "/refresh",
    response_model=AuthSessionResponse,
    summary="Issue a fresh access token for the current session",
)
async def refresh(response: Response, context: CurrentContext) -> AuthSessionResponse:
    """Extend an active session by issuing a new bearer token.

    Requires a currently-valid token (the `CurrentContext` dependency
    rejects expired ones). The web client calls this on a timer before
    expiry and also on a 401 retry path so users are not stranded
    mid-session.
    """
    refreshed = refresh_auth_session(context)
    settings = get_settings()
    issue_session_cookies(
        response,
        access_token=refreshed.access_token,
        ttl_seconds=_ttl_seconds(),
        env=settings.env,
    )
    return refreshed


@router.post(
    "/logout",
    status_code=204,
    summary="Clear the cookie-bound session.",
)
async def logout(response: Response) -> Response:
    """Clear ``caseops_session`` + ``caseops_csrf`` cookies.

    Idempotent — safe to call without a current session. Bearer-token
    callers do not need this endpoint; they simply discard the token.
    A future revision will also revoke the underlying session row in
    the DB so a stolen token (in the bearer path) becomes worthless
    immediately rather than at next refresh.
    """
    settings = get_settings()
    clear_session_cookies(response, env=settings.env)
    response.status_code = 204
    return response
