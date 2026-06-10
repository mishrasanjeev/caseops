from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

FORBIDDEN_TENANT_STRINGS = (
    "estimated_internal_cost",
    "gross_profit",
    "gross_margin",
    "payment_gateway_cost",
    "provider_fee",
    "platform_notes",
    "manual_research_cost",
)


@dataclass(frozen=True)
class Check:
    name: str
    method: str
    path: str
    expected_statuses: tuple[int, ...]
    tenant_leak_scan: bool = False


CHECKS = (
    Check("Platform admin", "GET", "/api/platform-admin/overview", (200, 403)),
    Check("Platform admin profit", "GET", "/api/platform-admin/profit-report", (200, 403)),
    Check("Platform admin costs", "GET", "/api/platform-admin/cost-profiles", (200, 403)),
    Check("Platform integrations", "GET", "/api/platform-admin/integrations", (200, 403)),
    Check("Provider events", "GET", "/api/platform-admin/provider-events", (200, 403)),
    Check("Tenant billing current plan", "GET", "/api/billing/current", (200,), True),
    Check("Credit ledger export", "GET", "/api/billing/credit-ledger/export", (200, 403), True),
    Check("Payment export", "GET", "/api/billing/payments/export", (200, 403), True),
    Check("Spend export", "GET", "/api/billing/reports/spend/export", (200, 403), True),
)


def _base_url() -> str:
    value = os.environ.get("CASEOPS_SMOKE_API_BASE", "http://localhost:8000").strip()
    return value.rstrip("/") + "/"


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json,text/csv,*/*"}
    token = os.environ.get("CASEOPS_SMOKE_BEARER_TOKEN")
    cookie = os.environ.get("CASEOPS_SMOKE_COOKIE")
    if token:
        headers["Authorization"] = "Bearer " + token
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _request(method: str, path: str) -> tuple[int, bytes]:
    request = Request(
        urljoin(_base_url(), path.lstrip("/")),
        method=method,
        headers=_headers(),
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read(1_000_000)
    except HTTPError as exc:
        return exc.code, exc.read(100_000)
    except URLError as exc:
        return 0, str(exc.reason).encode("utf-8", errors="replace")


def main() -> int:
    if not (os.environ.get("CASEOPS_SMOKE_BEARER_TOKEN") or os.environ.get("CASEOPS_SMOKE_COOKIE")):
        print("FAIL: set CASEOPS_SMOKE_BEARER_TOKEN or CASEOPS_SMOKE_COOKIE")
        return 2
    ok = True
    for check in CHECKS:
        status, body = _request(check.method, check.path)
        text = body.decode("utf-8", errors="ignore")
        leak = check.tenant_leak_scan and any(value in text for value in FORBIDDEN_TENANT_STRINGS)
        passed = status in check.expected_statuses and not leak
        ok = ok and passed
        print(f"{'PASS' if passed else 'FAIL'}: {check.name} status={status}")
        if leak:
            print("  Observed tenant-facing internal finance field leak.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
