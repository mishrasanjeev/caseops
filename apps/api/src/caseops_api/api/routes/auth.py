from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.core.cookies import (
    clear_session_cookies,
    issue_session_cookies,
)
from caseops_api.core.rate_limit import limiter, login_rate_limit
from caseops_api.core.security import create_access_token
from caseops_api.core.settings import get_settings
from caseops_api.schemas.auth import AuthContextResponse, AuthSessionResponse, LoginRequest
from caseops_api.schemas.employees import (
    AccountSetupCompleteRequest,
    PasswordResetStartRequest,
    PasswordResetStartResponse,
)
from caseops_api.services.employees import (
    complete_account_setup,
    complete_password_reset,
    start_password_reset,
)
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


def _session_response(session: DbSession, context: SessionContext) -> AuthSessionResponse:
    from caseops_api.services.capabilities import resolve_membership_capabilities

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
        capabilities=sorted(resolve_membership_capabilities(session, context.membership)),
    )


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


@router.post(
    "/account-setup/complete",
    response_model=AuthSessionResponse,
    summary="Complete a one-time employee account setup link",
)
@limiter.limit(login_rate_limit)
async def account_setup_complete(
    request: Request,
    response: Response,
    payload: AccountSetupCompleteRequest,
    session: DbSession,
) -> AuthSessionResponse:
    context = complete_account_setup(session, payload=payload)
    auth = _session_response(session, context)
    issue_session_cookies(
        response,
        access_token=auth.access_token,
        ttl_seconds=_ttl_seconds(),
        env=get_settings().env,
    )
    return auth


@router.post(
    "/password-reset/start",
    response_model=PasswordResetStartResponse,
    summary="Request a password-reset link without revealing account existence",
)
@limiter.limit(login_rate_limit)
async def password_reset_start(
    request: Request,
    payload: PasswordResetStartRequest,
    session: DbSession,
) -> PasswordResetStartResponse:
    return start_password_reset(
        session,
        company_slug=payload.company_slug,
        email=str(payload.email),
    )


@router.post(
    "/password-reset/complete",
    response_model=AuthSessionResponse,
    summary="Complete a one-time employee password reset link",
)
@limiter.limit(login_rate_limit)
async def password_reset_complete(
    request: Request,
    response: Response,
    payload: AccountSetupCompleteRequest,
    session: DbSession,
) -> AuthSessionResponse:
    context = complete_password_reset(session, payload=payload)
    auth = _session_response(session, context)
    issue_session_cookies(
        response,
        access_token=auth.access_token,
        ttl_seconds=_ttl_seconds(),
        env=get_settings().env,
    )
    return auth


@router.get("/me", response_model=AuthContextResponse, summary="Get the current auth context")
async def me(context: CurrentContext, session: DbSession) -> AuthContextResponse:
    return build_auth_context(session, context)


@router.post(
    "/refresh",
    response_model=AuthSessionResponse,
    summary="Issue a fresh access token for the current session",
)
async def refresh(
    response: Response,
    context: CurrentContext,
    session: DbSession,
) -> AuthSessionResponse:
    """Extend an active session by issuing a new bearer token.

    Requires a currently-valid token (the `CurrentContext` dependency
    rejects expired ones). The web client calls this on a timer before
    expiry and also on a 401 retry path so users are not stranded
    mid-session.
    """
    refreshed = refresh_auth_session(session, context)
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
