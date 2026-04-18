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
_ALL_ROLES = frozenset(
    {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}
)
_STAFF = frozenset({MembershipRole.OWNER, MembershipRole.ADMIN})
_OWNER_ONLY = frozenset({MembershipRole.OWNER})


CAPABILITY_ROLES: dict[str, frozenset[MembershipRole]] = {
    # --- matter and workspace core ---
    "matters:create": _ALL_ROLES,
    "matters:edit": _ALL_ROLES,
    "matters:archive": _STAFF,
    "matters:write": _ALL_ROLES,  # catch-all: per-matter authenticated write
    # --- money ---
    "invoices:issue": _STAFF,
    "invoices:send_payment_link": _STAFF,
    "invoices:void": _OWNER_ONLY,
    "payments:sync": _STAFF,
    "time_entries:write": _ALL_ROLES,
    # --- company / IAM ---
    "company:manage_profile": _STAFF,
    "company:manage_users": _STAFF,
    # --- documents + processing ---
    "documents:upload": _ALL_ROLES,
    "documents:manage": _STAFF,
    # --- contracts ---
    "contracts:create": _ALL_ROLES,
    "contracts:edit": _ALL_ROLES,
    "contracts:delete": _STAFF,
    "contracts:manage_rules": _STAFF,
    # --- outside counsel ---
    "outside_counsel:manage": _STAFF,
    "outside_counsel:recommend": _ALL_ROLES,
    # --- drafting ---
    "drafts:create": _ALL_ROLES,
    "drafts:generate": _ALL_ROLES,
    "drafts:review": _STAFF,
    "drafts:finalize": _STAFF,
    # --- hearing packs ---
    "hearing_packs:generate": _ALL_ROLES,
    "hearing_packs:review": _STAFF,
    # --- court sync ---
    "court_sync:run": _STAFF,
    # --- recommendations + AI ---
    "recommendations:generate": _ALL_ROLES,
    "recommendations:decide": _ALL_ROLES,
    "ai:generate": _ALL_ROLES,
    # --- authority corpus + tenant overlay ---
    "authorities:search": _ALL_ROLES,
    "authorities:ingest": _STAFF,
    "authorities:annotate": _ALL_ROLES,
    # --- governance ---
    "workspace:admin": _STAFF,
    "audit:export": _OWNER_ONLY,
    "matter_access:manage": _STAFF,
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
