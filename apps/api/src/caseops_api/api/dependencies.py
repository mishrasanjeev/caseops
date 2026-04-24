from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC
from datetime import datetime as _datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from caseops_api.core.cookies import PORTAL_SESSION_COOKIE, SESSION_COOKIE
from caseops_api.core.observability import set_tenant_context
from caseops_api.core.security import (
    TokenValidationError,
    decode_access_token,
    decode_portal_session_token,
)
from caseops_api.db.models import MembershipRole, PortalUser
from caseops_api.db.session import get_db_session
from caseops_api.services.identity import SessionContext, get_session_context

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
        token_issued_at=int(claims["issued_at"]),
    )
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


# Capability → set of roles that satisfy it. Mirrors
# apps/web/lib/capabilities.ts — the TS table is the client-side UX
# gate; this table is the server's source of truth. Any drift is a
# bug; the test sweep asserts the two stay in lock-step.
#
# Sprint 8b widened the role taxonomy to six: owner, admin, partner,
# member, paralegal, viewer. The named groups below capture the most
# common coverage buckets; individual capabilities compose them.
#
#   - owner       → everything
#   - admin       → everything except OWNER_ONLY (void invoices, audit export)
#   - partner     → senior fee-earner; STAFF minus workspace/IAM
#   - member      → general fee-earner (former default)
#   - paralegal   → member minus finance, finalize-approvals, and ops commands
#   - viewer      → read-only; only read-oriented caps

_OWNER = MembershipRole.OWNER
_ADMIN = MembershipRole.ADMIN
_PARTNER = MembershipRole.PARTNER
_MEMBER = MembershipRole.MEMBER
_PARALEGAL = MembershipRole.PARALEGAL
_VIEWER = MembershipRole.VIEWER

_ALL_FEE_EARNERS = frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL})
_STAFF = frozenset({_OWNER, _ADMIN, _PARTNER})
_OWNER_ADMIN = frozenset({_OWNER, _ADMIN})
_OWNER_ONLY = frozenset({_OWNER})
_ALL_AUTHENTICATED = frozenset(
    {_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL, _VIEWER}
)
# Legacy alias — preserved so any existing references keep resolving;
# new capabilities should pick from _ALL_FEE_EARNERS / _STAFF / etc.
_ALL_ROLES = _ALL_FEE_EARNERS


CAPABILITY_ROLES: dict[str, frozenset[MembershipRole]] = {
    # --- matter and workspace core ---
    "matters:create": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER}),
    "matters:edit": _ALL_FEE_EARNERS,  # paralegals can edit matter metadata
    "matters:archive": _STAFF,
    "matters:write": _ALL_FEE_EARNERS,
    # --- money --- paralegals + viewers stay out of finance
    "invoices:issue": _STAFF,
    "invoices:send_payment_link": _STAFF,
    "invoices:void": _OWNER_ONLY,
    "payments:sync": _STAFF,
    "time_entries:write": _ALL_FEE_EARNERS,
    # --- company / IAM --- workspace admin stays narrow
    "company:manage_profile": _OWNER_ADMIN,
    "company:manage_users": _OWNER_ADMIN,
    # --- documents + processing ---
    "documents:upload": _ALL_FEE_EARNERS,
    "documents:manage": _STAFF,
    # --- contracts ---
    "contracts:create": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER}),
    "contracts:edit": _ALL_FEE_EARNERS,
    "contracts:delete": _STAFF,
    "contracts:manage_rules": _STAFF,
    # --- outside counsel ---
    "outside_counsel:manage": _STAFF,
    "outside_counsel:recommend": _ALL_FEE_EARNERS,
    # --- drafting --- paralegals can draft but not review/finalize
    "drafts:create": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL}),
    "drafts:generate": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL}),
    "drafts:review": _STAFF,
    "drafts:finalize": _STAFF,
    # --- hearing packs ---
    "hearing_packs:generate": _ALL_FEE_EARNERS,
    "hearing_packs:review": _STAFF,
    # --- court sync --- ops action, not for paralegals
    "court_sync:run": _STAFF,
    # --- recommendations + AI ---
    "recommendations:generate": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER}),
    "recommendations:decide": _STAFF,
    "ai:generate": frozenset({_OWNER, _ADMIN, _PARTNER, _MEMBER, _PARALEGAL}),
    # --- authority corpus + tenant overlay --- viewer can read-search only
    "authorities:search": _ALL_AUTHENTICATED,
    "authorities:ingest": _STAFF,
    "authorities:annotate": _ALL_FEE_EARNERS,
    # --- governance ---
    "workspace:admin": _OWNER_ADMIN,
    "audit:export": _OWNER_ONLY,
    "matter_access:manage": _OWNER_ADMIN,
    # --- intake (Sprint 8b BG-025) ---
    # Submit: anyone authenticated so a business-unit manager with
    # only a viewer role can still file a request. Triage + assign:
    # staff (owner/admin/partner). Promote to matter: staff.
    "intake:submit": _ALL_AUTHENTICATED,
    "intake:triage": _STAFF,
    "intake:promote": _STAFF,
    # --- teams (Sprint 8c BG-026) ---
    # Create/edit teams + toggle team_scoping is governance work;
    # everyone authenticated can read who's on what team so staffing
    # and assignment flows don't need a separate gate.
    "teams:manage": _OWNER_ADMIN,
    # --- clients (Sprint S1 MOD-TS-009) ---
    # Anyone authenticated can view the client list (same bar as
    # matters). Create / edit / archive is a fee-earner action —
    # paralegals included; viewers stay read-only.
    "clients:view": _ALL_AUTHENTICATED,
    "clients:create": _ALL_FEE_EARNERS,
    "clients:edit": _ALL_FEE_EARNERS,
    "clients:archive": _STAFF,
    # --- communications log (Phase B / J12 / M11) ---
    # Anyone authenticated can read a matter's communication history
    # (same bar as matters themselves). Write access is fee-earner-
    # gated — paralegals included so they can log a client call —
    # but viewers stay read-only. Slice 2 will keep the same gate
    # for the SendGrid send action.
    "communications:view": _ALL_AUTHENTICATED,
    "communications:write": _ALL_FEE_EARNERS,
    # Email template catalogue is workspace-admin work — same gate
    # as company:manage_users etc. The Compose & send action itself
    # rides on communications:write so any fee-earner can SEND
    # using the templates an admin created.
    "email_templates:manage": _OWNER_ADMIN,
    # KYC lifecycle (Phase B M11 slice 3 — US-037 / FT-049).
    # Submit: any fee-earner can collect docs from a client they
    # know. Review (verify / reject): staff only — partner / admin /
    # owner — to keep a four-eyes pattern between the lawyer who
    # collected the pack and the reviewer who approves it.
    "clients:kyc_submit": _ALL_FEE_EARNERS,
    "clients:kyc_review": _STAFF,
    # Phase C-1 (2026-04-24, MOD-TS-014). Inviting an external party
    # into the workspace is a workspace-admin act — same gate as
    # company:manage_users. Listing/revoking grants follows the same.
    "portal:invite": _OWNER_ADMIN,
    "portal:manage_grants": _OWNER_ADMIN,
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
