"""Machine-enforced boundaries preventing test traffic from spending provider credits."""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from fastapi import HTTPException, status

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.core.settings import get_settings
from caseops_api.services.session_context import SessionContext

_PAID_PROVIDER_HOSTS = frozenset(
    {
        "api.indiankanoon.org",
        "webapi.ecourtsindia.com",
    }
)
_SYNTHETIC_TENANT_TOKENS = frozenset(
    {
        "demo",
        "e2e",
        "qa",
        "debug",
        "probe",
        "smoke",
        "test",
        "verify",
    }
)


def _configured_blocked_slugs() -> set[str]:
    return {
        item.strip().lower()
        for item in re.split(r"[,;]", get_settings().paid_provider_blocked_company_slugs)
        if item.strip()
    }


def paid_provider_test_tenant_reason(context: SessionContext) -> str | None:
    slug = context.company.slug.strip().lower()
    if slug in _configured_blocked_slugs():
        return "configured_test_tenant"
    tokens = {token for token in re.split(r"[^a-z0-9]+", slug) if token}
    if tokens & _SYNTHETIC_TENANT_TOKENS:
        return "synthetic_test_tenant"
    return None


def paid_provider_block_reason(
    *,
    context: SessionContext,
    provider: str,
    base_url: str | None,
    transport_is_mocked: bool = False,
) -> str | None:
    """Return a stable reason before a paid network request can be attempted."""

    if transport_is_mocked:
        return None
    hostname = urlsplit((base_url or "").strip()).hostname
    if (hostname or "").lower() not in _PAID_PROVIDER_HOSTS:
        return None
    tenant_reason = paid_provider_test_tenant_reason(context)
    # The explicit automation marker is authoritative in every environment.
    # Production Playwright uses the real tenant, so coupling this boundary to
    # the runtime environment or a test-looking slug would allow routine
    # verification to spend provider credits as soon as the tenant is enabled.
    if paid_providers_blocked_for_request():
        return "automated_test_request"
    if tenant_reason is not None:
        return tenant_reason
    # A leaked live provider configuration must not turn a local pytest run
    # into a bill. Injected MockTransport clients remain fully testable.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "automated_test_process"
    return None


def assert_paid_provider_call_allowed(
    *,
    context: SessionContext,
    provider: str,
    base_url: str | None,
    transport_is_mocked: bool = False,
) -> None:
    reason = paid_provider_block_reason(
        context=context,
        provider=provider,
        base_url=base_url,
        transport_is_mocked=transport_is_mocked,
    )
    if reason is None:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "paid_provider_blocked_for_test",
            "message": (
                "Paid provider calls are disabled for automated tests and test tenants. "
                "Use the deterministic provider fixture; no external request was made."
            ),
            "provider": provider,
            "reason": reason,
        },
    )


__all__ = [
    "assert_paid_provider_call_allowed",
    "paid_provider_block_reason",
    "paid_provider_test_tenant_reason",
]
