"""Purpose-only rate identity. Never grants authentication or capabilities."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import time
from dataclasses import dataclass, field

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from caseops_api.core.settings import Settings, get_settings
from caseops_api.schemas.rate_identity import RateIdentityReadinessResponse

EDGE_IP = "x-caseops-edge-client-ip"
EDGE_TOKEN = "x-caseops-edge-attestation"
FORWARD_IP = "x-caseops-rate-client-ip"
FORWARD_TIME = "x-caseops-rate-timestamp"
FORWARD_MAC = "x-caseops-rate-signature"
FORWARD_TARGETS = frozenset(
    {
        ("POST", "/api/billing/enrollments/demo-request"),
        ("GET", "/api/health/rate-identity"),
    }
)
_HEX = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_TIME = re.compile(r"[1-9][0-9]{9}\Z", re.ASCII)
MAX_AGE_SECONDS = 30
MAX_FUTURE_SECONDS = 5


class InvalidRateIdentity(ValueError):
    def __init__(self):
        super().__init__("Invalid rate identity claims.")


@dataclass(frozen=True)
class RateIdentity:
    client_ip: str = field(repr=False)
    provenance: str = "socket"


def strict_ip(value: str) -> str:
    if not 1 <= len(value) <= 45 or value != value.strip() or "%" in value:
        raise InvalidRateIdentity()
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            return address.ipv4_mapped.compressed
        return address.compressed
    except ValueError:
        raise InvalidRateIdentity() from None


def _key(settings: Settings) -> str | None:
    secret = settings.rate_identity_edge_secret
    value = secret.get_secret_value() if secret else None
    if value is not None and not _HEX.fullmatch(value):
        raise InvalidRateIdentity()
    return value


def validate_rate_identity_settings(settings: Settings) -> None:
    try:
        key = _key(settings)
    except InvalidRateIdentity:
        raise RuntimeError("Rate identity configuration is invalid.") from None
    if settings.rate_identity_required and (not key or not settings.rate_identity_edge_https):
        raise RuntimeError("Required rate identity edge configuration is unavailable.")
    if key and any(
        hmac.compare_digest(key.encode("ascii"), value.encode("utf-8"))
        for value in (
            settings.auth_secret,
            settings.machine_readiness_evidence_secret or "",
        )
    ):
        raise RuntimeError("Rate identity requires its own purpose-only key.")


def _one(request: Request, name: str) -> str | None:
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise InvalidRateIdentity()
    return values[0] if values else None


def signed_message(method: str, path: str, client_ip: str, timestamp: str) -> bytes:
    return f"caseops-rate-v1\n{method}\n{path}\n{client_ip}\n{timestamp}".encode("ascii")


def resolve_rate_identity(request: Request) -> RateIdentity:
    settings = get_settings()
    edge_ip, token = (_one(request, name) for name in (EDGE_IP, EDGE_TOKEN))
    forwarded_ip, timestamp, mac = (
        _one(request, name) for name in (FORWARD_IP, FORWARD_TIME, FORWARD_MAC)
    )
    edge = None
    key = _key(settings)
    if edge_ip is not None or token is not None:
        if (
            not key
            or token is None
            or not _HEX.fullmatch(token)
            or not hmac.compare_digest(token, key)
        ):
            raise InvalidRateIdentity()
        if edge_ip is None:
            raise InvalidRateIdentity()
        edge = strict_ip(edge_ip)
    if any(value is not None for value in (forwarded_ip, timestamp, mac)):
        method, path = request.method, request.scope["path"]
        if (method, path) not in FORWARD_TARGETS or request.scope.get("query_string", b""):
            raise InvalidRateIdentity()
        if request.scope.get("raw_path", path.encode("ascii")) != path.encode("ascii"):
            raise InvalidRateIdentity()
        if not key or forwarded_ip is None or timestamp is None or mac is None:
            raise InvalidRateIdentity()
        if not _TIME.fullmatch(timestamp) or not _HEX.fullmatch(mac):
            raise InvalidRateIdentity()
        now = int(time.time())
        if not -MAX_FUTURE_SECONDS <= now - int(timestamp) <= MAX_AGE_SECONDS:
            raise InvalidRateIdentity()
        canonical = strict_ip(forwarded_ip)
        if canonical != forwarded_ip:
            raise InvalidRateIdentity()
        expected = hmac.new(
            key.encode("ascii"), signed_message(method, path, canonical, timestamp), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, mac):
            raise InvalidRateIdentity()
        # The API's ALB sees the web service's egress, not the browser. The
        # narrowly bound web signature therefore takes precedence over edge IP.
        return RateIdentity(canonical, "web-forward")
    if edge is not None:
        return RateIdentity(edge, "edge")
    peer = request.client.host if request.client else "127.0.0.1"
    return RateIdentity(peer)


def request_rate_identity(request: Request) -> RateIdentity:
    return request.scope.get("caseops.rate_identity") or resolve_rate_identity(request)


class RateIdentityMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            identity = resolve_rate_identity(Request(scope))
            if (
                get_settings().rate_identity_required
                and (scope["method"], scope["path"])
                == ("POST", "/api/billing/enrollments/demo-request")
                and identity.provenance == "socket"
            ):
                raise InvalidRateIdentity()
        except InvalidRateIdentity:
            if scope["path"] == "/api/health/rate-identity":
                sha = get_settings().release_sha or ""
                body = RateIdentityReadinessResponse(
                    ready=False,
                    provenance="unavailable",
                    release_sha=sha if re.fullmatch(r"[0-9a-f]{40}", sha) else "unavailable",
                ).model_dump()
            else:
                body = {"detail": "Verified rate identity is unavailable."}
            response = JSONResponse(body, status_code=403, headers={"Cache-Control": "no-store"})
            await response(scope, receive, send)
            return
        scope["caseops.rate_identity"] = identity
        if identity.provenance != "socket" and get_settings().rate_identity_edge_https:
            scope["scheme"] = "https"
        await self.app(scope, receive, send)
