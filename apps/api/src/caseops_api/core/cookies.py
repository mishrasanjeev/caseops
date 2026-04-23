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
"""
from __future__ import annotations

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
    )


def clear_session_cookies(response: Response, *, env: str | None) -> None:
    """Wipe the session + CSRF cookies on ``response``. Called from
    /api/auth/logout. We mirror the original Secure flag so the
    browser actually overwrites the cookie (a Set-Cookie with a
    different Secure value is treated as a different cookie)."""
    secure = _cookie_secure(env)
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.set_cookie(
            key=name,
            value="",
            max_age=0,
            httponly=name == SESSION_COOKIE,
            secure=secure,
            samesite="lax",
            path="/",
        )


__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "clear_session_cookies",
    "issue_session_cookies",
]
