"""EG-001 (2026-04-23) — HttpOnly cookie session for the browser.

Why cookies, not localStorage:

The web app previously stashed the access token in ``window.localStorage``.
Any successful XSS injection into a CaseOps page (vulnerable third-party
script, prompt-injected content rendered without escaping, leaked
extension permissions) could read that token and exfiltrate it. An
``HttpOnly`` cookie sidesteps the JavaScript surface entirely — the
browser sends it on every request to the API host but JS cannot read,
copy, or forward the value.

The CSRF cookie is intentionally *not* HttpOnly: the web client must
read it and echo the value as the ``X-CSRF-Token`` header on
state-changing requests. The pairing (cookie + header) defeats CSRF
because a cross-origin attacker can cause the cookie to be sent (with
``SameSite=Lax``) but cannot read the cookie's value to set the header.

BUG-011 (2026-04-24, Ram) cross-subdomain cookie scope:

The web app is served from ``caseops.ai`` and the API from
``api.caseops.ai``. Without an explicit ``Domain=`` on Set-Cookie,
the browser scopes the cookie to the request host (api.caseops.ai)
and ``document.cookie`` on caseops.ai cannot read it. The web client
needs to read the CSRF cookie to echo it as the X-CSRF-Token header
on every mutating request — when the cookie is invisible, every
mutating request lands without the header and the CSRF middleware
returns 403 "Missing CSRF token." Setting ``Domain=.caseops.ai``
in production widens the scope to the parent domain so both
subdomains can read it. Local dev (no parent domain) skips Domain.
"""
from __future__ import annotations

import os
import secrets

from starlette.responses import Response

from caseops_api.core.settings import is_non_local_env

# Cookie names. Kept short and prefix-namespaced so you can grep prod
# logs / browser devtools without ambiguity.
SESSION_COOKIE = "caseops_session"
CSRF_COOKIE = "caseops_csrf"

# Header the web client echoes back on state-changing requests. The
# CSRF middleware compares against the cookie of the same name in
# constant time.
CSRF_HEADER = "X-CSRF-Token"


def _cookie_secure(env: str | None) -> bool:
    """In production we MUST set Secure so the cookie never travels
    plaintext. In local dev (http://localhost:3000) Secure prevents
    the cookie from being set at all, so we relax there."""
    return is_non_local_env(env)


def _cookie_domain(env: str | None) -> str | None:
    """BUG-011 fix. Returns the parent domain to set on Set-Cookie so
    both api.caseops.ai (server) and caseops.ai (web client) can see
    the cookie. Local dev returns None (host-only cookie on
    localhost). Operators can override via CASEOPS_COOKIE_DOMAIN —
    necessary if the parent domain ever changes (e.g. a custom
    enterprise white-label like example-firm.caseops.ai needs
    Domain=.example-firm.caseops.ai)."""
    explicit = os.environ.get("CASEOPS_COOKIE_DOMAIN", "").strip()
    if explicit:
        return explicit
    if not is_non_local_env(env):
        return None
    return ".caseops.ai"


def issue_session_cookies(
    response: Response,
    *,
    access_token: str,
    ttl_seconds: int,
    env: str | None,
) -> None:
    """Set the session + CSRF cookies on ``response``.

    Called from /api/auth/login, /api/auth/refresh, and
    /api/bootstrap/company — every endpoint that mints a fresh access
    token. Both cookies expire together so a stale CSRF token can
    never outlive its session.
    """
    secure = _cookie_secure(env)
    domain = _cookie_domain(env)
    # Session token. HttpOnly so JS cannot read it; Lax SameSite so
    # cross-site navigations (e.g. inbound email link to caseops.ai)
    # still send it but cross-site forms / fetches do not.
    response.set_cookie(
        key=SESSION_COOKIE,
        value=access_token,
        max_age=ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        domain=domain,
    )
    # CSRF token. JS-readable so the web client can echo it as a
    # request header. The cookie alone is meaningless without the
    # matching header, which an attacker on a different origin cannot
    # set because they cannot read the cookie value.
    response.set_cookie(
        key=CSRF_COOKIE,
        value=secrets.token_urlsafe(32),
        max_age=ttl_seconds,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
        domain=domain,
    )


def clear_session_cookies(response: Response, *, env: str | None) -> None:
    """Wipe the session + CSRF cookies on ``response``. Called from
    /api/auth/logout. We mirror the original Secure flag AND Domain
    so the browser actually overwrites the cookie (a Set-Cookie with
    a different Secure or Domain value is treated as a different
    cookie and leaves the original behind)."""
    secure = _cookie_secure(env)
    domain = _cookie_domain(env)
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.set_cookie(
            key=name,
            value="",
            max_age=0,
            httponly=name == SESSION_COOKIE,
            secure=secure,
            samesite="lax",
            path="/",
            domain=domain,
        )


# Phase C-1 (2026-04-24) — Portal session cookie. DELIBERATELY a
# different name from SESSION_COOKIE so the same browser on the same
# domain can hold both an internal /app session and a /portal session
# at once without either accidentally satisfying the other surface's
# auth check. The portal dependency only ever reads PORTAL_SESSION_COOKIE.
PORTAL_SESSION_COOKIE = "caseops_portal_session"

# Codex H1 (2026-04-24): portal CSRF — paired cookie + header for the
# C-2 write endpoints (POST /api/portal/matters/{id}/communications,
# /kyc, and any future portal mutations). Same double-submit pattern
# as the internal CSRF gate but on a separate cookie name so the two
# surfaces don't collide. The portal CSRF cookie is JS-readable
# (HttpOnly=False) so the web client can echo it as
# ``X-Portal-CSRF-Token``.
PORTAL_CSRF_COOKIE = "caseops_portal_csrf"
PORTAL_CSRF_HEADER = "X-Portal-CSRF-Token"


def issue_portal_session_cookie(
    response: Response,
    *,
    access_token: str,
    ttl_seconds: int,
    env: str | None,
) -> None:
    secure = _cookie_secure(env)
    domain = _cookie_domain(env)
    response.set_cookie(
        key=PORTAL_SESSION_COOKIE,
        value=access_token,
        max_age=ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        domain=domain,
    )
    # Codex H1: paired CSRF cookie. Same TTL as the session so a
    # stale CSRF token can never outlive its session.
    response.set_cookie(
        key=PORTAL_CSRF_COOKIE,
        value=secrets.token_urlsafe(32),
        max_age=ttl_seconds,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
        domain=domain,
    )


def clear_portal_session_cookie(response: Response, *, env: str | None) -> None:
    secure = _cookie_secure(env)
    domain = _cookie_domain(env)
    for name, http_only in (
        (PORTAL_SESSION_COOKIE, True),
        (PORTAL_CSRF_COOKIE, False),
    ):
        response.set_cookie(
            key=name,
            value="",
            max_age=0,
            httponly=http_only,
            secure=secure,
            samesite="lax",
            path="/",
            domain=domain,
        )


__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "PORTAL_CSRF_COOKIE",
    "PORTAL_CSRF_HEADER",
    "PORTAL_SESSION_COOKIE",
    "SESSION_COOKIE",
    "clear_portal_session_cookie",
    "clear_session_cookies",
    "issue_portal_session_cookie",
    "issue_session_cookies",
]
