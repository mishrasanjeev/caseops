from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CheckResult:
    name: str
    url: str
    expected: str
    ok: bool
    detail: str


def _base_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise argparse.ArgumentTypeError("Base URL cannot be blank.")
    return cleaned.rstrip("/") + "/"


def _url(base: str, path: str) -> str:
    return urljoin(base, path.lstrip("/"))


def _get(url: str, *, timeout: float) -> tuple[int, bytes, str]:
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json,text/html,text/plain,*/*",
            "User-Agent": "caseops-prod-billing-safe-smoke/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read(1_000_000), response.headers.get(
                "content-type",
                "",
            )
    except HTTPError as exc:
        return exc.code, exc.read(100_000), exc.headers.get("content-type", "")
    except URLError as exc:
        return 0, str(exc.reason).encode("utf-8", errors="replace"), ""


def _json(body: bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _check_api_health(api_base: str, timeout: float) -> CheckResult:
    url = _url(api_base, "/api/health")
    status, body, _ = _get(url, timeout=timeout)
    parsed = _json(body)
    ok = status == 200 and parsed is not None and parsed.get("status") == "ok"
    return CheckResult(
        name="API health",
        url=url,
        expected="HTTP 200 JSON with status=ok",
        ok=ok,
        detail=f"status={status}, body_status={parsed.get('status') if parsed else None}",
    )


def _check_billing_plans(api_base: str, timeout: float) -> CheckResult:
    url = _url(api_base, "/api/billing/plans")
    status, body, _ = _get(url, timeout=timeout)
    parsed = _json(body)
    plans = parsed.get("plans") if parsed else None
    ok = status == 200 and isinstance(plans, list) and len(plans) > 0
    return CheckResult(
        name="Billing plans",
        url=url,
        expected="HTTP 200 JSON with a non-empty plans list",
        ok=ok,
        detail=f"status={status}, plan_count={len(plans) if isinstance(plans, list) else None}",
    )


def _check_pricing_page(web_base: str, timeout: float) -> CheckResult:
    url = _url(web_base, "/pricing")
    status, body, content_type = _get(url, timeout=timeout)
    text = body.decode("utf-8", errors="ignore").lower()
    ok = status == 200 and ("pricing" in text or "caseops" in text)
    return CheckResult(
        name="Pricing page",
        url=url,
        expected="HTTP 200 HTML containing pricing or CaseOps text",
        ok=ok,
        detail=f"status={status}, content_type={content_type or 'unknown'}",
    )


def _check_platform_admin_unauth(api_base: str, timeout: float) -> CheckResult:
    url = _url(api_base, "/api/platform-admin/overview")
    status, _, _ = _get(url, timeout=timeout)
    ok = status == 401
    return CheckResult(
        name="Unauthenticated platform admin API",
        url=url,
        expected="HTTP 401 with no cookie or bearer token",
        ok=ok,
        detail=f"status={status}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run production-safe unauthenticated billing smoke checks. "
            "No credentials are accepted, no evidence is saved, and no "
            "payment-provider calls are made."
        )
    )
    parser.add_argument(
        "--api-base",
        type=_base_url,
        default="https://api.caseops.ai/",
        help="Production API base URL.",
    )
    parser.add_argument(
        "--web-base",
        type=_base_url,
        default="https://caseops.ai/",
        help="Production web base URL.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    checks = [
        _check_api_health(args.api_base, args.timeout),
        _check_billing_plans(args.api_base, args.timeout),
        _check_pricing_page(args.web_base, args.timeout),
        _check_platform_admin_unauth(args.api_base, args.timeout),
    ]
    for check in checks:
        status_label = "PASS" if check.ok else "FAIL"
        print(f"{status_label}: {check.name}")
        print(f"  URL: {check.url}")
        print(f"  Expected: {check.expected}")
        print(f"  Observed: {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())

