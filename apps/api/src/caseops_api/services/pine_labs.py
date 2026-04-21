from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock

import httpx
from fastapi import HTTPException, status

from caseops_api.core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class PineLabsCreatePaymentLinkResult:
    provider_order_id: str | None
    payment_url: str | None
    provider_reference: str | None
    status: str
    raw_payload: dict[str, object]


@dataclass
class PineLabsPaymentStatusResult:
    provider_order_id: str | None
    provider_reference: str | None
    status: str
    amount_received_minor: int
    raw_payload: dict[str, object]


def _normalize_status(status_value: str | None) -> str:
    normalized = (status_value or "").strip().lower()
    if normalized in {"created", "initiated"}:
        return "created"
    if normalized in {"pending", "processing", "in_progress"}:
        return "pending"
    if normalized in {"partial", "partially_paid"}:
        return "partially_paid"
    if normalized in {"paid", "success", "captured", "completed", "authorized"}:
        return "paid"
    if normalized in {"failed", "declined"}:
        return "failed"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized in {"expired"}:
        return "expired"
    return "unknown"


def _extract_first(payload: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        resolved = str(value).strip()
        if resolved:
            return resolved
    return None


def _extract_amount_minor(payload: dict[str, object]) -> int:
    for key in ("amount_received_minor", "paid_amount_minor", "amount_minor", "amount"):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return round(value)
        text_value = str(value).strip()
        if not text_value:
            continue
        try:
            if "." in text_value:
                return round(float(text_value) * 100)
            return int(text_value)
        except ValueError:
            continue
    return 0


class WebhookSecretNotConfigured(RuntimeError):
    """Raised when the Pine Labs webhook secret has not been configured."""


def verify_pine_labs_signature(*, raw_body: bytes, signature: str | None) -> bool:
    secret = get_settings().pine_labs_webhook_secret
    if not secret:
        raise WebhookSecretNotConfigured(
            "Pine Labs webhook secret is not configured; refusing to accept webhooks.",
        )
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "card_number",
        "card_cvv",
        "cvv",
        "cvv2",
        "upi_vpa",
        "vpa",
        "customer_email",
        "customer_phone",
        "phone",
        "personal_id",
        "pan",
        "aadhaar",
        "aadhar",
        "otp",
        "cvc",
    },
)
REDACTION_MASK = "[redacted]"


def redact_provider_payload(payload: dict[str, object]) -> dict[str, object]:
    def _redact(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: (REDACTION_MASK if key.lower() in SENSITIVE_PAYLOAD_KEYS else _redact(inner))
                for key, inner in value.items()
            }
        if isinstance(value, list):
            return [_redact(item) for item in value]
        return value

    redacted = _redact(payload)
    assert isinstance(redacted, dict)
    return redacted


class _BearerTokenCache:
    """Cache the Plural V2 OAuth bearer token in-memory with a small
    safety margin before the declared expiry. Thread-safe for the
    simple single-process Cloud Run model; if we ever go multi-worker
    the token endpoint is cheap enough that per-worker caching is fine.
    """
    _lock = Lock()
    _token: str | None = None
    _expires_at: datetime | None = None

    @classmethod
    def get(cls, fetcher) -> str:
        with cls._lock:
            now = datetime.now(UTC)
            if (
                cls._token
                and cls._expires_at
                and cls._expires_at - now > timedelta(seconds=60)
            ):
                return cls._token
            token, expires_at = fetcher()
            cls._token = token
            cls._expires_at = expires_at
            return token

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._token = None
            cls._expires_at = None


class PineLabsGatewayClient:
    # Plural V2 OAuth token endpoint — relative to ``pine_labs_api_base_url``.
    _TOKEN_PATH = "/api/auth/v1/token"

    def __init__(self) -> None:
        self.settings = get_settings()

    def _build_url(self, path: str | None, *, provider_order_id: str | None = None) -> str:
        if not self.settings.pine_labs_api_base_url or not path:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Pay Link isn't available — the payment gateway "
                    "isn't configured on this environment. Please "
                    "contact support to enable online payments."
                ),
            )
        resolved_path = path
        if provider_order_id:
            # Pine Labs Plural V2 uses ``{payment_link_id}``; older
            # configs used our generic ``{provider_order_id}``. Support
            # both so admins can paste Pine Labs' native path spec
            # verbatim.
            resolved_path = resolved_path.replace(
                "{payment_link_id}", provider_order_id,
            ).replace(
                "{provider_order_id}", provider_order_id,
            )
        return f"{self.settings.pine_labs_api_base_url.rstrip('/')}/{resolved_path.lstrip('/')}"

    def _fetch_bearer_token(self) -> tuple[str, datetime]:
        """POST /api/auth/v1/token → bearer access_token.

        Plural V2 uses an OAuth ``client_credentials`` grant: send
        ``client_id`` + ``client_secret`` + ``merchant_id`` in JSON
        body (header auth is NOT accepted despite common examples).
        """
        if (
            not self.settings.pine_labs_api_key
            or not self.settings.pine_labs_api_secret
            or not self.settings.pine_labs_merchant_id
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Pay Link isn't available — the payment gateway "
                    "credentials are incomplete on this environment. "
                    "Please contact support."
                ),
            )
        token_url = (
            self.settings.pine_labs_api_base_url.rstrip("/") + self._TOKEN_PATH
        )
        response = httpx.post(
            token_url,
            json={
                "grant_type": "client_credentials",
                "client_id": self.settings.pine_labs_api_key,
                "client_secret": self.settings.pine_labs_api_secret,
                "merchant_id": self.settings.pine_labs_merchant_id,
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=self.settings.pine_labs_request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        expires_at_raw = payload.get("expires_at") or ""
        try:
            expires_at = datetime.fromisoformat(
                expires_at_raw.replace("Z", "+00:00"),
            )
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
        except ValueError:
            # Fallback: token is typically valid ~2h; assume 30 min
            # so we refresh well before any real expiry.
            expires_at = datetime.now(UTC) + timedelta(minutes=30)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Pay Link is temporarily unavailable — the payment "
                    "gateway did not return a valid auth token. Please "
                    "try again in a few minutes."
                ),
            )
        return token, expires_at

    def _build_headers(self) -> dict[str, str]:
        token = _BearerTokenCache.get(self._fetch_bearer_token)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Plural V2 requires a unique per-request id + timestamp
            # on mutating endpoints. Emitting them on every request
            # is safe and simplifies the client.
            "Request-ID": str(uuid.uuid4()),
            "Request-Timestamp": (
                datetime.now(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            ),
        }

    def create_payment_link(
        self,
        *,
        merchant_order_id: str,
        amount_minor: int,
        currency: str,
        customer_name: str | None,
        customer_email: str | None,
        customer_phone: str | None,
        description: str | None,
        return_url: str,
        webhook_url: str,
    ) -> PineLabsCreatePaymentLinkResult:
        # Plural V2 paymentlink schema: amount nested as
        # ``{"value": <paisa>, "currency": "<ISO>"}``. Customer uses
        # ``email`` + ``phone_number`` (NOT email_id/mobile_number).
        # ``callback_url`` is the success-redirect; webhook is wired
        # via the merchant dashboard out-of-band, not per-request.
        # Reference field is ``merchant_payment_link_reference``.
        expire_by = (
            datetime.now(UTC) + timedelta(days=60)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        customer_block = {}
        if customer_email:
            customer_block["email"] = customer_email
        if customer_phone:
            customer_block["phone_number"] = customer_phone
        if customer_name:
            # Plural stores customer id as a free-form token; use the
            # name as a stable-ish identifier when present.
            customer_block["id"] = customer_name[:60]
        payload = {
            "amount": {"value": amount_minor, "currency": currency},
            "description": description or "",
            "merchant_payment_link_reference": merchant_order_id,
            "allowed_payment_methods": ["CARD", "UPI", "NETBANKING"],
            "callback_url": return_url,
            "expire_by": expire_by,
        }
        if customer_block:
            payload["customer"] = customer_block
        _ = webhook_url  # wired via Plural merchant dashboard, not per-request
        response = httpx.post(
            self._build_url(self.settings.pine_labs_payment_link_path),
            json=payload,
            headers=self._build_headers(),
            timeout=self.settings.pine_labs_request_timeout_seconds,
        )
        if response.status_code == 401:
            # Bearer token probably expired between our cache check
            # and the real call — blow away the cache and try once.
            _BearerTokenCache.clear()
            response = httpx.post(
                self._build_url(self.settings.pine_labs_payment_link_path),
                json=payload,
                headers=self._build_headers(),
                timeout=self.settings.pine_labs_request_timeout_seconds,
            )
        response.raise_for_status()
        data = response.json()
        # Pine Labs Plural V2 returns nested payloads under ``data`` or
        # ``result`` on success. Try the nested envelope first, then
        # fall through to the flat top-level.
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        if not isinstance(inner, dict):
            inner = data
        return PineLabsCreatePaymentLinkResult(
            provider_order_id=_extract_first(
                inner,
                "payment_link_id",  # Pine Labs Plural V2 native
                "provider_order_id",
                "order_id",
                "payment_id",
            ),
            payment_url=_extract_first(
                inner,
                "payment_link",  # Plural V2 native (2026-04-21)
                "payment_link_url",
                "short_url",
                "payment_url",
                "checkout_url",
                "redirect_url",
            ),
            provider_reference=_extract_first(
                inner,
                "merchant_payment_link_reference",  # Plural V2 native
                "reference_id",
                "provider_reference",
            ),
            status=_normalize_status(
                _extract_first(inner, "status", "payment_link_status", "payment_status"),
            ),
            raw_payload=data,
        )

    def fetch_payment_status(self, *, provider_order_id: str) -> PineLabsPaymentStatusResult:
        response = httpx.get(
            self._build_url(
                self.settings.pine_labs_payment_status_path,
                provider_order_id=provider_order_id,
            ),
            headers=self._build_headers(),
            timeout=self.settings.pine_labs_request_timeout_seconds,
        )
        if response.status_code == 401:
            _BearerTokenCache.clear()
            response = httpx.get(
                self._build_url(
                    self.settings.pine_labs_payment_status_path,
                    provider_order_id=provider_order_id,
                ),
                headers=self._build_headers(),
                timeout=self.settings.pine_labs_request_timeout_seconds,
            )
        response.raise_for_status()
        data = response.json()
        inner = data.get("data") if isinstance(data.get("data"), dict) else data
        if not isinstance(inner, dict):
            inner = data
        return PineLabsPaymentStatusResult(
            provider_order_id=_extract_first(
                inner,
                "payment_link_id",
                "provider_order_id",
                "order_id",
                "payment_id",
            ),
            provider_reference=_extract_first(
                inner, "reference_id", "provider_reference",
            ),
            status=_normalize_status(
                _extract_first(inner, "payment_link_status", "status", "payment_status"),
            ),
            amount_received_minor=_extract_amount_minor(inner),
            raw_payload=data,
        )

    def parse_webhook_payload(self, payload: dict[str, object]) -> PineLabsPaymentStatusResult:
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(inner, dict):
            inner = payload
        return PineLabsPaymentStatusResult(
            provider_order_id=_extract_first(
                inner,
                "payment_link_id",
                "provider_order_id",
                "order_id",
                "payment_id",
                "merchant_order_id",
            ),
            provider_reference=_extract_first(
                inner, "reference_id", "provider_reference",
            ),
            status=_normalize_status(
                _extract_first(inner, "payment_link_status", "status", "payment_status"),
            ),
            amount_received_minor=_extract_amount_minor(inner),
            raw_payload=payload,
        )


def dump_provider_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
