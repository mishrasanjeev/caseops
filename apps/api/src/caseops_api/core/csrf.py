"""EG-001 (2026-04-23) — double-submit CSRF middleware.

Pairs with the ``caseops_csrf`` cookie issued from
``core.cookies.issue_session_cookies``. The web client reads the
cookie value (it is *not* HttpOnly) and echoes it as the
``X-CSRF-Token`` header on every state-changing request. The
middleware compares the two in constant time.

Why this guards what it does:

- A cross-origin attacker can cause the browser to *send* the
  ``caseops_csrf`` cookie (even with ``SameSite=Lax``, top-level
  navigation triggers it). They cannot *read* the cookie value
  because cross-origin script access is blocked, so they cannot set
  the matching header. The double-submit pattern fails closed.
- The bearer-auth path (Authorization: Bearer ...) is exempt — the
  attacker would need the bearer token, which is itself the secret.
  This keeps SDKs, automation, and the E2E suite working without
  knowing about CSRF.
- Auth bootstrap endpoints (/login, /refresh, /bootstrap/company)
  are exempt because the cookie does not exist yet on the first
  request.

Failure mode: 403 with a problem-detail body. Keep the response shape
identical to the rest of the API so the web client surfaces an
actionable toast via the existing ``apiErrorMessage`` helper.
"""
from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from caseops_api.core.cookies import CSRF_COOKIE, CSRF_HEADER

# State-changing methods. GET / HEAD / OPTIONS / TRACE are exempt by
# RFC and by browser convention.
_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Routes exempt from CSRF: pre-auth endpoints (no cookie yet) and
# server-to-server webhooks (signed by their own provider secret).
# Match by exact path, by prefix, or by suffix.
_EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/bootstrap/company",
})
_EXEMPT_PREFIXES = (
    # Catches any path under /api/webhooks/* if added in the future.
    "/api/webhooks/",
)
# Provider-signed webhooks (PineLabs, SendGrid event hooks, etc.)
# have their own integrity check; CSRF would only break them. The
# convention is that the route path ends with ``/webhook``, e.g.
# /api/payments/pine-labs/webhook. Matching by suffix means a new
# provider integration can be added without touching this exempt
# list — as long as the route ends in /webhook.
_EXEMPT_SUFFIXES = ("/webhook",)


def _path_is_exempt(path: str) -> bool:
    if path in _EXEMPT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
        return True
    return any(path.endswith(suffix) for suffix in _EXEMPT_SUFFIXES)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests whose ``X-CSRF-Token`` header
    does not match the ``caseops_csrf`` cookie.

    Order matters: install AFTER ``CORSMiddleware`` (so preflight is
    handled before we touch the request) but BEFORE the route
    handlers (so a bad request is rejected before the DB session
    opens).
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        if request.method not in _PROTECTED_METHODS:
            return await call_next(request)
        if _path_is_exempt(request.url.path):
            return await call_next(request)
        # Bearer-auth callers (SDKs, automation) carry their own
        # secret; CSRF does not apply to them.
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return await call_next(request)
        # Cookie-auth path → require the matching CSRF header. Both
        # values must be present AND equal.
        cookie_value = request.cookies.get(CSRF_COOKIE, "")
        header_value = request.headers.get(CSRF_HEADER, "")
        if not cookie_value or not header_value:
            return _csrf_failure("Missing CSRF token.")
        # Constant-time compare so an attacker cannot infer the cookie
        # value via timing on a probe.
        if not hmac.compare_digest(cookie_value, header_value):
            return _csrf_failure("CSRF token mismatch.")
        return await call_next(request)


def _csrf_failure(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "type": "https://caseops.ai/errors/csrf",
            "title": "Forbidden",
            "status": 403,
            "detail": detail,
        },
    )


__all__ = ["CSRFMiddleware"]
