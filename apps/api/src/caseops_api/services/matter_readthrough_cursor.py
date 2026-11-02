"""Opaque, purpose-separated read continuations. A cursor is never an access grant."""

import base64
import json
import os
from datetime import UTC, datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException

from caseops_api.core.settings import get_settings

TTL_SECONDS = 3600
AUDIENCE = "caseops-matter-readthrough-v1"
KINDS = {
    "recommendations",
    "recommendation_options",
    "recommendation_decisions",
    "hearing_pack_items",
}
_FIELDS = {
    "v",
    "aud",
    "company",
    "member",
    "user",
    "role",
    "matter",
    "lifecycle",
    "kind",
    "parent",
    "limit",
    "id",
    "key",
    "iat",
    "exp",
}
_AAD = AUDIENCE.encode("ascii")


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def record_id(value):
    # Existing source keys are String(36), including retained non-UUID identities.
    if (
        type(value) is not str
        or not 1 <= len(value) <= 36
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Invalid source identity.")
    return value


def _cipher():
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"caseops/matter-readthrough/cursor/v1",
        info=b"authenticated-read-continuation-only",
    ).derive(get_settings().auth_secret.encode("utf-8"))
    return AESGCM(key)


def cursor_scope(context, scope, kind, parent_id, limit):
    if (
        scope.company_id != context.company.id
        or kind not in KINDS
        or type(limit) is not int
        or not 1 <= limit <= 25
    ):
        raise ValueError("Invalid read page scope.")
    return {
        "v": 1,
        "aud": AUDIENCE,
        "company": scope.company_id,
        "member": context.membership.id,
        "user": context.user.id,
        "role": str(getattr(context.membership.role, "value", context.membership.role)),
        "matter": scope.matter_id,
        "lifecycle": scope.matter_lifecycle_version,
        "kind": kind,
        "parent": parent_id,
        "limit": limit,
    }


def encode_cursor(context, scope, kind, parent_id, limit, row_id, key, *, now=None):
    issued = int(utc(now or datetime.now(UTC)).timestamp())
    payload = {
        **cursor_scope(context, scope, kind, parent_id, limit),
        "id": record_id(row_id),
        "key": key,
        "iat": issued,
        "exp": issued + TTL_SECONDS,
    }
    nonce = os.urandom(12)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(nonce + _cipher().encrypt(nonce, raw, _AAD)).decode("ascii")


def decode_cursor(value, context, scope, kind, parent_id, limit, *, now=None):
    """The optional clock applies only here, never to authentication/JWT decoding."""
    try:
        if type(value) is not str or not 1 <= len(value) <= 4000:
            raise ValueError
        raw = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        if len(raw) <= 28 or base64.urlsafe_b64encode(raw).decode("ascii") != value:
            raise ValueError
        payload = json.loads(_cipher().decrypt(raw[:12], raw[12:], _AAD))
        expected = cursor_scope(context, scope, kind, parent_id, limit)
        if (
            type(payload) is not dict
            or set(payload) != _FIELDS
            or any(payload[k] != v for k, v in expected.items() if k != "lifecycle")
        ):
            raise ValueError
        if any(type(payload[k]) is not int for k in ["v", "lifecycle", "limit", "iat", "exp"]):
            raise ValueError
        stamp = utc(now or datetime.now(UTC)).timestamp()
        if (
            payload["exp"] - payload["iat"] != TTL_SECONDS
            or not payload["iat"] <= stamp < payload["exp"]
        ):
            raise ValueError
        if payload["lifecycle"] != scope.matter_lifecycle_version:
            raise HTTPException(
                409,
                detail={
                    "code": "matter_read_cursor_stale",
                    "message": "Matter changed. Reload the first page.",
                },
            )
        record_id(payload["id"])
        if kind in {"recommendation_options", "hearing_pack_items"}:
            if type(payload["key"]) is not int:
                raise ValueError
        else:
            if type(payload["key"]) is not str:
                raise ValueError
            parsed = datetime.fromisoformat(payload["key"])
            if (
                parsed.tzinfo is None
                or parsed.utcoffset() is None
                or utc(parsed).isoformat(timespec="microseconds") != payload["key"]
            ):
                raise ValueError
        return payload
    except (InvalidTag, ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        raise HTTPException(
            400,
            detail={
                "code": "matter_read_cursor_invalid",
                "message": "Invalid continuation. Reload the first page.",
            },
        ) from exc
