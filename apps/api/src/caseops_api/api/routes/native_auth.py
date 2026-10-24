"""Native handoff uses browser authority once; token endpoints never do."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.core.console_auth import CONSOLE_SESSION_COOKIE
from caseops_api.core.cookies import PORTAL_SESSION_COOKIE, SESSION_COOKIE
from caseops_api.core.rate_limit import limiter, login_rate_limit
from caseops_api.schemas.native_auth import (
    NativeAuthorizeRequest,
    NativeAuthorizeResponse,
    NativeRefreshRequest,
    NativeSessionsResponse,
    NativeTokenRequest,
    NativeTokenResponse,
)
from caseops_api.services import native_auth
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


def _token_only(request: Request) -> None:
    if request.headers.get("authorization") is not None or any(
        request.cookies.get(name)
        for name in (SESSION_COOKIE, PORTAL_SESSION_COOKIE, CONSOLE_SESSION_COOKIE)
    ):
        raise HTTPException(
            401, "Native token requests must not include browser or bearer authority."
        )


@router.post("/authorize", response_model=NativeAuthorizeResponse)
@limiter.limit(login_rate_limit)
def authorize(
    request: Request,
    payload: NativeAuthorizeRequest,
    context: CurrentContext,
    session: DbSession,
) -> NativeAuthorizeResponse:
    if not request.cookies.get(SESSION_COOKIE) or request.headers.get("authorization") is not None:
        raise HTTPException(401, "Use the authenticated browser session for native sign-in.")
    return native_auth.authorize(session, context, payload)


@router.post("/token", response_model=NativeTokenResponse, dependencies=[Depends(_token_only)])
@limiter.limit(login_rate_limit)
def token(request: Request, payload: NativeTokenRequest, session: DbSession) -> NativeTokenResponse:
    return native_auth.exchange(session, payload)


@router.post("/refresh", response_model=NativeTokenResponse, dependencies=[Depends(_token_only)])
@limiter.limit(login_rate_limit)
def refresh(
    request: Request,
    payload: NativeRefreshRequest,
    session: DbSession,
) -> NativeTokenResponse:
    return native_auth.rotate(session, payload.refresh_token)


@router.post("/logout", status_code=204, dependencies=[Depends(_token_only)])
@limiter.limit(login_rate_limit)
def logout(request: Request, payload: NativeRefreshRequest, session: DbSession) -> Response:
    native_auth.logout(session, payload.refresh_token)
    return Response(status_code=204)


@router.get("/sessions", response_model=NativeSessionsResponse)
def sessions(
    request: Request,
    context: CurrentContext,
    session: DbSession,
) -> NativeSessionsResponse:
    return native_auth.list_sessions(
        session,
        context,
        getattr(request.state, "native_session_id", None),
    )


@router.delete("/sessions/{session_id}", status_code=204)
def revoke(session_id: str, context: CurrentContext, session: DbSession) -> Response:
    native_auth.revoke_session(session, context, session_id)
    return Response(status_code=204)
