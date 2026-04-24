"""Lint-style sweep over the live FastAPI app: every mutating route
MUST pass through ``require_capability`` or ``require_role`` before
its handler runs, unless it's on the deliberate public allowlist
(``/api/auth/*``, ``/api/bootstrap/*``, payment webhook, health).

The hand-rolled ``if role not in (...)`` pattern the codebase used to
ship is a correctness footgun — one forgotten guard is a permission
leak at enterprise scale. This lint is the single source of truth.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.routing import APIRoute

from caseops_api.api.dependencies import require_capability, require_role
from caseops_api.main import create_application

MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


# Intentionally unauthenticated or their own-auth'd path. Each entry is
# a (method, path_prefix) tuple; an exact match or prefix match
# exempts the route. Additions require founder-level review.
PUBLIC_MUTATING_ROUTES: set[tuple[str, str]] = {
    ("POST", "/api/auth/login"),
    # Refresh takes the current-valid bearer token via get_current_context
    # and re-issues a new one; no role / capability gate makes sense since
    # every authenticated user may extend their own session. Hard-expired
    # tokens fall through to 401 and the web client redirects to sign-in.
    ("POST", "/api/auth/refresh"),
    # EG-001 (2026-04-23) — logout clears the session cookie.
    # Anyone may log themselves out; idempotent server-side.
    ("POST", "/api/auth/logout"),
    ("POST", "/api/bootstrap/company"),
    # Pine Labs payment notifications — their own signature is the
    # auth layer; the handler enforces cross-tenant + idempotency.
    ("POST", "/api/payments/pine-labs/webhook"),
    # Demo-request form on the marketing site; rate-limited, emails out.
    ("POST", "/api/demo-request"),
    # Compute-only recompute of an existing matter summary; the only
    # effect is an LLM call whose response is returned to the caller.
    # No tenant data is mutated. Access is already scoped by the
    # tenancy check inside generate_matter_summary.
    ("POST", "/api/matters/{matter_id}/summary/regenerate"),
    # Sprint R4 stepper preview — pure compute, no persistence, no
    # tenant data mutated. The route reads only ``template_type``
    # (global catalogue) and user-provided ``facts`` (not stored).
    # The session context is consumed for auth only.
    ("POST", "/api/drafting/preview"),
    # SendGrid event webhook (BUG-013) — signed by SendGrid's own
    # ECDSA key, verified server-side via _verify_sendgrid_signature
    # against ``CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY``. Tenancy is
    # implicit: events are matched back to ``hearing_reminders`` rows
    # by ``sg_message_id``, and rows are written only from the
    # worker's authenticated send path. No session context available
    # (SendGrid is a third party), so a role/capability guard would
    # reject every legitimate event.
    ("POST", "/api/webhooks/sendgrid/events"),
    # Phase C-1 (2026-04-24, MOD-TS-014) — portal sign-in surface.
    # request-link is intentionally unauthenticated and returns the
    # same response on hit/miss to defeat email enumeration.
    ("POST", "/api/portal/auth/request-link"),
    # verify-link consumes a one-time token; the token IS the auth.
    ("POST", "/api/portal/auth/verify-link"),
    # logout clears the portal session cookie; idempotent.
    ("POST", "/api/portal/auth/logout"),
    # Phase C-2 (2026-04-24, MOD-TS-015) — client portal mutations.
    # These ride on get_current_portal_user (cookie-based) + a
    # MatterPortalGrant scope check; require_capability would be the
    # wrong gate because PortalUser is intentionally NOT a Membership
    # (D1 in PHASE_C_KICKOFF_2026-04-24.md). Per-route auth is
    # exercised by tests/test_portal_matters.py.
    ("POST", "/api/portal/matters/{matter_id}/communications"),
    ("POST", "/api/portal/matters/{matter_id}/kyc"),
    # Phase C-3 (2026-04-25, MOD-TS-016) — outside-counsel portal
    # mutations. Same justification as the C-2 entries above:
    # get_current_portal_user + role='outside_counsel' grant gate
    # in services/portal_outside_counsel._assert_oc_grant. Per-route
    # auth is exercised by tests/test_portal_outside_counsel.py
    # (FT-074, FT-075, role gate, tenant iso, CSRF, cross-counsel iso).
    ("POST", "/api/portal/oc/matters/{matter_id}/work-product"),
    ("POST", "/api/portal/oc/matters/{matter_id}/invoices"),
    ("POST", "/api/portal/oc/matters/{matter_id}/time-entries"),
}


def _is_guarded(route: APIRoute) -> bool:
    """True iff the route's dependency chain includes require_role or
    require_capability at some level."""
    for dep in route.dependant.dependencies:
        call = getattr(dep, "call", None)
        if call is None:
            continue
        # Both require_role and require_capability return an inner
        # closure named `_dep`. Identify them by their __closure__
        # contents — this is brittle across decorators but matches the
        # simple closures we ship in apps/api/src/caseops_api/api/
        # dependencies.py.
        if getattr(call, "__name__", "") == "_dep":
            closure = call.__closure__ or ()
            vals = {c.cell_contents for c in closure if _hashable(c.cell_contents)}
            if "allowed" in (call.__code__.co_freevars or ()) or "roles" in (
                call.__code__.co_freevars or ()
            ):
                return True
            del vals  # unused — keep for debugging
    return False


def _hashable(value: object) -> bool:
    try:
        hash(value)
        return True
    except TypeError:
        return False


def _route_is_public(method: str, path: str) -> bool:
    if (method, path) in PUBLIC_MUTATING_ROUTES:
        return True
    for ex_method, ex_prefix in PUBLIC_MUTATING_ROUTES:
        if ex_method == method and path.startswith(ex_prefix):
            return True
    return False


@pytest.fixture(scope="module")
def _app():
    return create_application()


def test_every_mutating_api_route_is_role_or_capability_guarded(_app) -> None:
    missing: list[str] = []
    for route in _app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not path.startswith("/api/"):
            continue
        for method in sorted(route.methods or set()):
            if method not in MUTATING_METHODS:
                continue
            if _route_is_public(method, path):
                continue
            if not _is_guarded(route):
                missing.append(f"{method} {path}")

    assert not missing, (
        "The following /api mutating routes have no require_role / "
        "require_capability guard. Either gate them or add them to "
        "PUBLIC_MUTATING_ROUTES with a written justification:\n  - "
        + "\n  - ".join(missing)
    )


# Sanity: the check itself should recognise a guarded dependency.
def test_guard_detection_recognises_require_capability():
    # Build a standalone wrapper and confirm _is_guarded would flag it.
    guard = require_capability("matters:create")
    # _is_guarded only runs against APIRoute objects, so verify the
    # closure shape directly: the inner _dep captures 'roles'.
    assert guard.__name__ == "_dep"
    assert "roles" in guard.__code__.co_freevars


def test_guard_detection_recognises_require_role():
    from caseops_api.db.models import MembershipRole

    guard = require_role(MembershipRole.OWNER)
    assert guard.__name__ == "_dep"
    assert "allowed" in guard.__code__.co_freevars


def test_no_stray_inspect_use():
    # Keeps the linter honest — if someone moves create_application
    # into a lazy import, we'd still want this test to be importable.
    assert inspect.isfunction(create_application)
