from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

from caseops_api.core.settings import get_settings


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


class PineLabsGatewayClient:
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

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.pine_labs_api_key:
            headers["X-Api-Key"] = self.settings.pine_labs_api_key
        if self.settings.pine_labs_api_secret:
            headers["X-Api-Secret"] = self.settings.pine_labs_api_secret
        if self.settings.pine_labs_merchant_id:
            headers["X-Merchant-Id"] = self.settings.pine_labs_merchant_id
        return headers

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
        payload = {
            "merchant_id": self.settings.pine_labs_merchant_id,
            "merchant_order_id": merchant_order_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone,
            "description": description,
            "return_url": return_url,
            "webhook_url": webhook_url,
        }
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
                "payment_link_url",  # Pine Labs Plural V2 native
                "short_url",
                "payment_url",
                "checkout_url",
                "redirect_url",
            ),
            provider_reference=_extract_first(
                inner, "reference_id", "provider_reference",
            ),
            status=_normalize_status(
                _extract_first(inner, "payment_link_status", "status", "payment_status"),
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
