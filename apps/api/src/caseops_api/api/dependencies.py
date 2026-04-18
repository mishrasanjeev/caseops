from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from caseops_api.core.security import TokenValidationError, decode_access_token
from caseops_api.db.models import MembershipRole
from caseops_api.db.session import get_db_session
from caseops_api.services.identity import SessionContext, get_session_context

bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db_session)]


def get_current_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
) -> SessionContext:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    try:
        claims = decode_access_token(credentials.credentials)
    except TokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    return get_session_context(
        session,
        claims["membership_id"],
        token_issued_at=int(claims["issued_at"]),
    )


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


# Capability → set of roles that satisfy it. Mirrors
# apps/web/lib/capabilities.ts — the TS table is the client-side UX
# gate; this table is the server's source of truth. Any drift is a
# bug; the test sweep asserts the two stay in lock-step.
CAPABILITY_ROLES: dict[str, frozenset[MembershipRole]] = {
    "matters:create": frozenset(
        {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}
    ),
    "matters:archive": frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    "invoices:issue": frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    "invoices:send_payment_link": frozenset(
        {MembershipRole.OWNER, MembershipRole.ADMIN}
    ),
    "invoices:void": frozenset({MembershipRole.OWNER}),
    "company:manage_profile": frozenset(
        {MembershipRole.OWNER, MembershipRole.ADMIN}
    ),
    "company:manage_users": frozenset(
        {MembershipRole.OWNER, MembershipRole.ADMIN}
    ),
    "contracts:create": frozenset(
        {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}
    ),
    "contracts:delete": frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    "outside_counsel:manage": frozenset(
        {MembershipRole.OWNER, MembershipRole.ADMIN}
    ),
    "recommendations:generate": frozenset(
        {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}
    ),
    "workspace:admin": frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    "audit:export": frozenset({MembershipRole.OWNER}),
    "matter_access:manage": frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
}


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
        raise RuntimeError(
            f"Unknown capability {capability!r}; add it to CAPABILITY_ROLES."
        )

    def _dep(
        context: Annotated[SessionContext, Depends(get_current_context)],
    ) -> SessionContext:
        if context.membership.role not in roles:
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


def list_capabilities(roles: Iterable[MembershipRole]) -> list[str]:
    """Helper for sanity checks / tests."""
    role_set = frozenset(roles)
    return sorted(cap for cap, rs in CAPABILITY_ROLES.items() if role_set & rs)
