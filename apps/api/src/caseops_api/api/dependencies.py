from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC
from datetime import datetime as _datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from caseops_api.core.cookies import PORTAL_SESSION_COOKIE, SESSION_COOKIE
from caseops_api.core.native_auth import NATIVE_ACCESS_PREFIX, decode_native_access_token
from caseops_api.core.observability import set_tenant_context
from caseops_api.core.security import (
    TokenValidationError,
    decode_access_token,
    decode_portal_session_token,
)
from caseops_api.db.models import MembershipRole, PortalUser
from caseops_api.db.session import get_db_session
from caseops_api.services.capabilities import (
    list_static_capabilities,
    membership_has_capability,
)
from caseops_api.services.capability_catalog import CAPABILITY_ROLES
from caseops_api.services.identity import get_session_context
from caseops_api.services.security import enforce_login_mfa_if_required
from caseops_api.services.session_context import SessionContext

bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db_session)]


def get_current_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
) -> SessionContext:
    # EG-001 (2026-04-23): cookie-first auth. ``Authorization: Bearer
    # ...`` is still accepted as a fallback so SDKs, automation, the
    # E2E suite, and any in-flight web bundle from the previous deploy
    # keep working. The cookie wins when both are present so a refresh
    # immediately pivots an existing session to the new flow.
    cookie_token = request.cookies.get(SESSION_COOKIE)
    native_token = credentials is not None and credentials.credentials.startswith(
        NATIVE_ACCESS_PREFIX
    )
    if native_token:
        if (
            cookie_token
            or request.url.path.startswith(("/api/platform-", "/api/portal/"))
            or (
                request.url.path.startswith("/api/auth/")
                and request.url.path
                not in {
                    "/api/auth/me",
                    "/api/auth/security",
                    "/api/auth/native/sessions",
                }
                and not request.url.path.startswith("/api/auth/native/sessions/")
            )
        ):
            raise HTTPException(
                401, "Native credentials cannot authorize this authentication realm."
            )
        from caseops_api.services.native_auth import native_context

        try:
            claims = decode_native_access_token(credentials.credentials)
        except TokenValidationError as exc:
            raise HTTPException(401, "Invalid native session.") from exc
        # Security exit/revocation remains available to an older client. The
        # platform is taken from its validated device row, never from headers.
        security_operation = (
            (request.method == "GET" and request.url.path in {
                "/api/auth/security", "/api/auth/native/sessions",
            })
            or (request.method == "DELETE" and request.url.path.startswith(
                "/api/auth/native/sessions/"
            ))
        )
        versions = request.headers.getlist("x-caseops-client-version")
        context = native_context(
            session, claims,
            client_version=versions[0] if len(versions) == 1 else None,
            enforce_client_compatibility=not security_operation,
        )
        request.state.native_session_id = claims["sid"]
        set_tenant_context(
            tenant_id=context.company.id,
            user_id=context.user.id,
            membership_id=context.membership.id,
        )
        return context
    if cookie_token:
        token = cookie_token
    elif credentials is not None:
        token = credentials.credentials
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session cookie or bearer token.",
        )

    try:
        claims = decode_access_token(token)
    except TokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    context = get_session_context(
        session,
        claims["membership_id"],
        token_issued_at=float(claims["issued_at_precise"]),
    )
    enforce_login_mfa_if_required(session, context=context, path=request.url.path)
    # Plant tenant identifiers into the request's logging context so
    # every downstream log line (services, worker background tasks
    # spawned within the request, DB query logs) auto-inherits them.
    set_tenant_context(
        tenant_id=context.company.id,
        user_id=context.user.id if context.user is not None else None,
        membership_id=context.membership.id,
    )
    return context


# ---------------------------------------------------------------------------
# Role and capability gates (§6.2)
#
# Route authors used to hand-roll a `if context.membership.role not in
# (owner, admin): raise 403` on every mutating endpoint. That's a
# correctness footgun — you forget once and you ship a permission leak.
# The two dependencies below are the single way any route checks roles
# going forward. A lint-style pytest sweep (tests/test_role_guards.py)
# enforces that every mutating endpoint is guarded.
# ---------------------------------------------------------------------------


def require_role(*roles: MembershipRole) -> Callable[..., SessionContext]:
    """FastAPI dependency — require the signed-in membership to be in
    one of `roles`. Returns the `SessionContext` so the route handler
    can use it without reclaiming `get_current_context` itself."""
    allowed: frozenset[MembershipRole] = frozenset(roles)
    if not allowed:
        raise RuntimeError("require_role needs at least one role")

    def _dep(
        context: Annotated[SessionContext, Depends(get_current_context)],
    ) -> SessionContext:
        if context.membership.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Requires role in {sorted(r.value for r in allowed)}; "
                    f"you are {context.membership.role!r}."
                ),
            )
        return context

    return _dep


def require_capability(
    capability: str,
) -> Callable[..., SessionContext]:
    """FastAPI dependency — require the signed-in membership to hold
    `capability`. Capability table lives in `CAPABILITY_ROLES` above."""
    roles = CAPABILITY_ROLES.get(capability)
    if roles is None:
        raise RuntimeError(f"Unknown capability {capability!r}; add it to CAPABILITY_ROLES.")

    def _dep(
        context: Annotated[SessionContext, Depends(get_current_context)],
        session: DbSession,
    ) -> SessionContext:
        if not membership_has_capability(session, context.membership, capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Capability {capability!r} requires role in "
                    f"{sorted(r.value for r in roles)}; you are "
                    f"{context.membership.role!r}."
                ),
            )
        return context

    return _dep


def require_all_capabilities(*capabilities: str) -> Callable[..., SessionContext]:
    """FastAPI dependency requiring every listed capability."""
    if not capabilities:
        raise RuntimeError("require_all_capabilities needs at least one capability")
    for capability in capabilities:
        if CAPABILITY_ROLES.get(capability) is None:
            raise RuntimeError(f"Unknown capability {capability!r}; add it to CAPABILITY_ROLES.")

    def _dep(
        context: Annotated[SessionContext, Depends(get_current_context)],
        session: DbSession,
    ) -> SessionContext:
        missing = [
            capability
            for capability in capabilities
            if not membership_has_capability(session, context.membership, capability)
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Requires all capabilities {sorted(capabilities)}; missing {sorted(missing)}."
                ),
            )
        return context

    return _dep


def require_any_capability(*capabilities: str) -> Callable[..., SessionContext]:
    """FastAPI dependency requiring at least one listed capability."""
    if not capabilities:
        raise RuntimeError("require_any_capability needs at least one capability")
    for capability in capabilities:
        if CAPABILITY_ROLES.get(capability) is None:
            raise RuntimeError(f"Unknown capability {capability!r}; add it to CAPABILITY_ROLES.")

    def _dep(
        context: Annotated[SessionContext, Depends(get_current_context)],
        session: DbSession,
    ) -> SessionContext:
        if not any(
            membership_has_capability(session, context.membership, capability)
            for capability in capabilities
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires any capability in {sorted(capabilities)}.",
            )
        return context

    return _dep


def list_capabilities(roles: Iterable[MembershipRole]) -> list[str]:
    """Helper for sanity checks / tests."""
    return list_static_capabilities(roles)


# ---------------------------------------------------------------
# Phase C-1 (2026-04-24, MOD-TS-014) — portal user dependency.
#
# Portal sessions ride on a SEPARATE cookie (PORTAL_SESSION_COOKIE) so
# the same browser can hold both a /app session and a /portal session
# without either accidentally satisfying the other surface's auth. This
# dependency reads ONLY the portal cookie and decodes ONLY portal-kind
# JWTs — an internal /app session token presented here will be rejected
# at the JWT-kind check inside ``decode_portal_session_token``.
# ---------------------------------------------------------------


def get_current_portal_user(
    request: Request,
    session: DbSession,
) -> PortalUser:
    cookie_token = request.cookies.get(PORTAL_SESSION_COOKIE)
    if not cookie_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to the portal to continue.",
        )
    try:
        claims = decode_portal_session_token(cookie_token)
    except TokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    portal_user = session.get(PortalUser, claims["portal_user_id"])
    if portal_user is None or not portal_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal user is no longer active.",
        )

    # Honour ``sessions_valid_after`` so a workspace owner can revoke
    # portal access immediately and a stale cookie cannot keep working.
    if portal_user.sessions_valid_after is not None:
        issued_at_raw = int(claims["issued_at"])
        issued_at = _datetime.fromtimestamp(issued_at_raw, tz=UTC)
        valid_after = portal_user.sessions_valid_after
        if valid_after.tzinfo is None:
            valid_after = valid_after.replace(tzinfo=UTC)
        if issued_at < valid_after:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Portal session was revoked. Sign in again.",
            )
    return portal_user
