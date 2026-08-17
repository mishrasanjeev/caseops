from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.core.cookies import (
    clear_session_cookies,
    issue_session_cookies,
)
from caseops_api.core.rate_limit import limiter, login_rate_limit
from caseops_api.core.settings import get_settings
from caseops_api.schemas.auth import AuthContextResponse, AuthSessionResponse, LoginRequest
from caseops_api.schemas.employees import (
    AccountSetupCompleteRequest,
    PasswordResetStartRequest,
    PasswordResetStartResponse,
)
from caseops_api.schemas.security import (
    MFADisableRequest,
    MFADisableResponse,
    MFAEnrollmentStartResponse,
    MFAEnrollmentVerifyResponse,
    MFARecoveryCodesResponse,
    MFASecurityStatusResponse,
    MFAStepUpRequest,
    MFAStepUpResponse,
    MFAVerifyRequest,
)
from caseops_api.services.employees import (
    complete_account_setup,
    complete_password_reset,
    record_employee_login_async,
    start_password_reset,
)
from caseops_api.services.identity import (
    SessionContext,
    authenticate_user,
    build_auth_context,
    get_session_context,
    issue_auth_session_under_fence,
    refresh_auth_session,
)
from caseops_api.services.security import (
    complete_step_up,
    disable_mfa,
    login_mfa_challenge_state,
    mfa_security_status,
    regenerate_recovery_codes,
    start_mfa_enrollment,
    verify_mfa_enrollment,
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
    background: BackgroundTasks,
) -> AuthSessionResponse:
    auth = authenticate_user(
        session,
        email=str(payload.email),
        password=payload.password,
        company_slug=payload.company_slug,
    )
    # P1-1: defer the employee.login audit + last_login write off the
    # login hot path. Runs after the response is sent, on its own fresh
    # DB session (record_employee_login_async opens one via
    # get_session_factory) — never the request session.
    background.add_task(record_employee_login_async, auth.membership.id)
    context = get_session_context(session, auth.membership.id)
    mfa_state = login_mfa_challenge_state(session, context=context)
    auth.mfa_required = bool(mfa_state["mfa_required"])
    auth.mfa_challenge_required = bool(mfa_state["mfa_challenge_required"])
    auth.mfa_enrollment_required = bool(mfa_state["mfa_enrollment_required"])
    auth.mfa_challenge_reason = (
        str(mfa_state["mfa_challenge_reason"])
        if mfa_state["mfa_challenge_reason"] is not None
        else None
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
    auth = issue_auth_session_under_fence(
        session,
        company_id=context.company.id,
        membership_id=context.membership.id,
    )
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
    auth = issue_auth_session_under_fence(
        session,
        company_id=context.company.id,
        membership_id=context.membership.id,
    )
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


@router.get(
    "/security",
    response_model=MFASecurityStatusResponse,
    summary="Get account security and MFA status.",
)
async def security_status(
    context: CurrentContext,
    session: DbSession,
) -> MFASecurityStatusResponse:
    return mfa_security_status(session, context=context)


@router.post(
    "/mfa/enroll",
    response_model=MFAEnrollmentStartResponse,
    summary="Start TOTP MFA enrollment.",
)
async def mfa_enroll(
    context: CurrentContext,
    session: DbSession,
) -> MFAEnrollmentStartResponse:
    return start_mfa_enrollment(session, context=context)


@router.post(
    "/mfa/enroll/verify",
    response_model=MFAEnrollmentVerifyResponse,
    summary="Verify TOTP MFA enrollment and return one-time recovery codes.",
)
async def mfa_enroll_verify(
    payload: MFAVerifyRequest,
    context: CurrentContext,
    session: DbSession,
) -> MFAEnrollmentVerifyResponse:
    return verify_mfa_enrollment(session, context=context, code=payload.code)


@router.post(
    "/mfa/step-up",
    response_model=MFAStepUpResponse,
    summary="Complete MFA step-up for high-risk actions.",
)
async def mfa_step_up(
    payload: MFAStepUpRequest,
    context: CurrentContext,
    session: DbSession,
) -> MFAStepUpResponse:
    return complete_step_up(
        session,
        context=context,
        code=payload.code,
        purpose=payload.purpose,
        method=payload.method,
    )


@router.post(
    "/mfa/recovery-codes/regenerate",
    response_model=MFARecoveryCodesResponse,
    summary="Regenerate single-use MFA recovery codes.",
)
async def mfa_recovery_codes_regenerate(
    context: CurrentContext,
    session: DbSession,
) -> MFARecoveryCodesResponse:
    return regenerate_recovery_codes(session, context=context)


@router.post(
    "/mfa/disable",
    response_model=MFADisableResponse,
    summary="Disable MFA after step-up verification.",
)
async def mfa_disable(
    payload: MFADisableRequest,
    context: CurrentContext,
    session: DbSession,
) -> MFADisableResponse:
    disable_mfa(
        session,
        context=context,
        reason=payload.reason,
        code=payload.code,
    )
    return MFADisableResponse(status="disabled")


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
