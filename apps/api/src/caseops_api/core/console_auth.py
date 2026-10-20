"""Cookie and JWT realm for reports-only platform principals, never tenants."""

from __future__ import annotations

from datetime import datetime

import jwt
from jwt import InvalidTokenError
from starlette.responses import Response

from caseops_api.core.cookies import _cookie_domain, _cookie_secure
from caseops_api.core.security import TokenValidationError
from caseops_api.core.settings import get_settings

CONSOLE_SESSION_COOKIE = "caseops_console_session"
CONSOLE_CSRF_COOKIE = "caseops_console_csrf"
CONSOLE_CSRF_HEADER = "X-Console-CSRF-Token"
CONSOLE_PATH = "/api/platform-console"
CONSOLE_AUDIENCE = "caseops-platform-reports"
CONSOLE_ISSUER = "caseops-platform-console"
CONSOLE_KIND = "platform_report_session"
CONSOLE_PURPOSES = frozenset({"mfa_enrollment_required", "mfa_challenge_required", "authenticated"})


def create_console_token(
    *,
    user_id: str,
    admin_id: str,
    secret: str,
    purpose: str,
    issued_at: datetime,
    expires_at: datetime,
) -> str:
    if purpose not in CONSOLE_PURPOSES:
        raise ValueError("Invalid console session purpose.")
    return jwt.encode(
        {
            "sub": user_id,
            "admin_id": admin_id,
            "jti": secret,
            "purpose": purpose,
            "kind": CONSOLE_KIND,
            "aud": CONSOLE_AUDIENCE,
            "iss": CONSOLE_ISSUER,
            "iat": issued_at,
            "exp": expires_at,
        },
        get_settings().auth_secret,
        algorithm="HS256",
    )


def decode_console_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            get_settings().auth_secret,
            algorithms=["HS256"],
            audience=CONSOLE_AUDIENCE,
            issuer=CONSOLE_ISSUER,
            options={"require": ["sub", "admin_id", "jti", "purpose", "kind", "iat", "exp"]},
        )
    except InvalidTokenError as exc:
        raise TokenValidationError("Invalid console session.") from exc
    if (
        payload.get("kind") != CONSOLE_KIND
        or payload.get("aud") != CONSOLE_AUDIENCE
        or payload.get("purpose") not in CONSOLE_PURPOSES
        or any(
            not isinstance(payload.get(key), str) or not payload[key]
            for key in ("sub", "admin_id", "jti")
        )
        or any(key in payload for key in ("company_id", "membership_id", "role"))
    ):
        raise TokenValidationError("Invalid console realm.")
    return payload


def issue_console_cookies(
    response: Response,
    *,
    token: str,
    csrf: str,
    ttl_seconds: int,
) -> None:
    env = get_settings().env
    response.set_cookie(
        CONSOLE_SESSION_COOKIE,
        token,
        max_age=ttl_seconds,
        httponly=True,
        secure=_cookie_secure(env),
        samesite="lax",
        path=CONSOLE_PATH,
    )
    response.set_cookie(
        CONSOLE_CSRF_COOKIE,
        csrf,
        max_age=ttl_seconds,
        httponly=False,
        secure=_cookie_secure(env),
        samesite="lax",
        path="/",
        domain=_cookie_domain(env),
    )


def clear_console_cookies(response: Response) -> None:
    env = get_settings().env
    response.delete_cookie(
        CONSOLE_SESSION_COOKIE,
        path=CONSOLE_PATH,
        secure=_cookie_secure(env),
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        CONSOLE_CSRF_COOKIE,
        path="/",
        domain=_cookie_domain(env),
        secure=_cookie_secure(env),
        samesite="lax",
    )
