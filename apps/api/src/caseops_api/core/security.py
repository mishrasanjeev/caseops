from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from jwt import InvalidTokenError

from caseops_api.core.settings import get_settings


class TokenValidationError(ValueError):
    """Raised when a bearer token cannot be trusted."""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${derived_key.hex()}"


def verify_password(password: str, encoded_password: str) -> bool:
    algorithm, salt_hex, key_hex = encoded_password.split("$", maxsplit=2)
    if algorithm != "scrypt":
        return False

    salt = bytes.fromhex(salt_hex)
    expected_key = bytes.fromhex(key_hex)
    candidate_key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return hmac.compare_digest(candidate_key, expected_key)


def create_access_token(*, user_id: str, company_id: str, membership_id: str, role: str) -> str:
    settings = get_settings()
    issued_at = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "company_id": company_id,
        "membership_id": membership_id,
        "role": role,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, str]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.auth_secret, algorithms=["HS256"])
    except InvalidTokenError as exc:
        raise TokenValidationError("Invalid bearer token.") from exc

    required_claims = {"sub", "company_id", "membership_id", "role", "iat"}
    if not required_claims.issubset(payload):
        raise TokenValidationError("Bearer token is missing required claims.")

    return {
        "user_id": str(payload["sub"]),
        "company_id": str(payload["company_id"]),
        "membership_id": str(payload["membership_id"]),
        "role": str(payload["role"]),
        "issued_at": str(payload["iat"]),
    }


# ---------------------------------------------------------------
# Phase C-1 (2026-04-24) — portal session tokens.
#
# A separate codec from create_access_token / decode_access_token
# because portal sessions carry portal_user_id + company_id only,
# never a Membership identity. Mixing the two payload shapes in one
# codec invites the wrong dependency reading the wrong claim and
# silently authorising a portal user as an internal Membership.
# ---------------------------------------------------------------

PORTAL_SESSION_TTL_MINUTES = 60 * 24 * 7  # 7 days
PORTAL_TOKEN_KIND = "portal_session"


def create_portal_session_token(
    *, portal_user_id: str, company_id: str, role: str
) -> str:
    settings = get_settings()
    issued_at = datetime.now(UTC)
    payload = {
        "kind": PORTAL_TOKEN_KIND,
        "sub": portal_user_id,
        "company_id": company_id,
        "role": role,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=PORTAL_SESSION_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_portal_session_token(token: str) -> dict[str, str]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.auth_secret, algorithms=["HS256"])
    except InvalidTokenError as exc:
        raise TokenValidationError("Invalid portal session token.") from exc

    if payload.get("kind") != PORTAL_TOKEN_KIND:
        # Reject internal-session JWTs presented to the portal endpoint
        # so a stolen /app token cannot satisfy /api/portal/* auth.
        raise TokenValidationError("Token is not a portal session.")

    required_claims = {"sub", "company_id", "role", "iat"}
    if not required_claims.issubset(payload):
        raise TokenValidationError(
            "Portal session token is missing required claims.",
        )

    return {
        "portal_user_id": str(payload["sub"]),
        "company_id": str(payload["company_id"]),
        "role": str(payload["role"]),
        "issued_at": str(payload["iat"]),
    }
