"""Separate native token realm. Platform is client-reported, not device attestation."""

import re
from datetime import datetime
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException
from jwt import InvalidTokenError

from caseops_api.core.security import TokenValidationError
from caseops_api.core.settings import get_settings, is_non_local_env

NATIVE_ACCESS_PREFIX = "cnat_"
NATIVE_AUDIENCE = "caseops-native-tenant"
NATIVE_ISSUER = "caseops-native"
LOCAL_REDIRECT = "caseops://oauth/callback"


def _production_signing_secret_ready(secret: str) -> bool:
    # Encoding/placeholder checks cannot prove entropy; provisioning must use
    # a CSPRNG, e.g. secrets.token_hex(32), rather than a copied configuration.
    if not re.fullmatch(r"[0-9a-f]{64,256}", secret) or len(secret) % 2 or len(set(secret)) < 8:
        return False
    return not any(
        len(secret) % width == 0 and secret == secret[:width] * (len(secret) // width)
        for width in range(1, len(secret) // 2 + 1)
    )


def signing_key() -> str:
    settings = get_settings()
    if settings.native_signing_secret is not None:
        secret = settings.native_signing_secret.get_secret_value()
        if is_non_local_env(settings.env) and not _production_signing_secret_ready(secret):
            raise TokenValidationError("Native signing is not configured.")
        return secret
    if not is_non_local_env(settings.env):
        return settings.auth_secret + ":native-development-only"
    raise TokenValidationError("Native signing is not configured.")


def require_native_issuance(redirect_uri: str | None = None) -> None:
    settings = get_settings()
    non_local = is_non_local_env(settings.env)
    if non_local and not (
        settings.native_auth_enabled
        and settings.native_signing_enabled
        and settings.native_signing_secret is not None
        and _production_signing_secret_ready(settings.native_signing_secret.get_secret_value())
        and settings.native_redirect_uris
        and settings.native_signing_secret.get_secret_value() != settings.auth_secret
    ):
        raise HTTPException(503, "Native sign-in is not enabled for this environment.")
    if non_local and any(not _registered_https_uri(uri) for uri in settings.native_redirect_uris):
        raise HTTPException(503, "Native redirect registration is not configured.")
    if redirect_uri is None:
        return
    allowed = settings.native_redirect_uris if non_local else [LOCAL_REDIRECT]
    if redirect_uri not in allowed or (non_local and not _registered_https_uri(redirect_uri)):
        raise HTTPException(400, "Native redirect is not registered.")


def _registered_https_uri(uri: str) -> bool:
    try:
        parsed = urlsplit(uri)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.path
            and not any((parsed.username, parsed.password, parsed.fragment, parsed.query))
            and parsed.port in (None, 443)
            and not any(char.isspace() for char in uri)
        )
    except ValueError:
        return False


def create_native_access_token(
    *,
    session_id: str,
    user_id: str,
    membership_id: str,
    company_id: str,
    issued_at: datetime,
    expires_at: datetime,
) -> str:
    return NATIVE_ACCESS_PREFIX + jwt.encode(
        {
            "kind": "native_access",
            "aud": NATIVE_AUDIENCE,
            "iss": NATIVE_ISSUER,
            "sid": session_id,
            "sub": user_id,
            "membership_id": membership_id,
            "company_id": company_id,
            "iat": issued_at,
            "exp": expires_at,
        },
        signing_key(),
        algorithm="HS256",
    )


def decode_native_access_token(token: str) -> dict:
    if not token.startswith(NATIVE_ACCESS_PREFIX):
        raise TokenValidationError("Invalid native session.")
    try:
        payload = jwt.decode(
            token[len(NATIVE_ACCESS_PREFIX) :],
            signing_key(),
            algorithms=["HS256"],
            audience=NATIVE_AUDIENCE,
            issuer=NATIVE_ISSUER,
            options={
                "require": ["kind", "sid", "sub", "membership_id", "company_id", "iat", "exp"]
            },
        )
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise TokenValidationError("Invalid native session.") from exc
    if payload.get("kind") != "native_access" or any(
        not isinstance(payload.get(key), str) or not payload[key]
        for key in ("sid", "sub", "membership_id", "company_id")
    ):
        raise TokenValidationError("Invalid native session.")
    return payload
