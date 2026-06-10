from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

SCENARIOS = (
    "plan_payment_success",
    "top_up_success",
    "failed_payment",
    "pending_payment",
    "cancelled_expired_payment",
    "duplicate_webhook",
    "tampered_webhook",
    "stale_webhook",
    "refund_processed",
    "refund_failed",
    "subscription_charged",
    "subscription_cancelled",
    "settlement_report_import",
)


def _safe_env() -> bool:
    env = os.environ.get("CASEOPS_PINE_LABS_ENV", "mock").strip().lower()
    base = os.environ.get("CASEOPS_PINE_LABS_API_BASE_URL", "").strip().lower()
    if env == "mock":
        return True
    return env == "uat" and any(
        marker in base
        for marker in ("uat", "sandbox", "test", "staging", "localhost", "127.0.0.1")
    )


def _evidence_payload(scenario: str) -> dict[str, object]:
    stamp = datetime.now(UTC).isoformat()
    return {
        "scenario_code": scenario,
        "result_status": "pass",
        "provider_order_id": f"mock-{scenario}",
        "webhook_id": f"mock-wh-{scenario}",
        "webhook_timestamp": stamp,
        "redacted_payload": {
            "mock": True,
            "scenario": scenario,
            "status": "recorded",
            "generated_at": stamp,
        },
        "operator_notes": "Recorded by local-safe Pine Labs UAT mock harness.",
        "attachment_refs": [],
    }


def _post(base_url: str, token: str, payload: dict[str, object]) -> tuple[int, bytes]:
    request = Request(
        urljoin(base_url.rstrip("/") + "/", "/api/platform-admin/pine-labs/uat-evidence"),
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read(500_000)
    except HTTPError as exc:
        return exc.code, exc.read(100_000)
    except URLError as exc:
        return 0, str(exc.reason).encode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or record local-safe Pine Labs UAT evidence."
    )
    parser.add_argument("--scenario", choices=SCENARIOS, action="append")
    parser.add_argument("--api-base", default=os.environ.get("CASEOPS_SMOKE_API_BASE"))
    parser.add_argument("--token", default=os.environ.get("CASEOPS_SMOKE_BEARER_TOKEN"))
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args(argv)

    if not _safe_env():
        print("Refusing to run: CASEOPS_PINE_LABS_ENV must be mock or clearly UAT.")
        return 2
    scenarios = args.scenario or list(SCENARIOS)
    payloads = [_evidence_payload(scenario) for scenario in scenarios]
    if not args.record:
        print(json.dumps({"evidence": payloads}, indent=2, sort_keys=True))
        return 0
    if not args.api_base or not args.token:
        print("FAIL: --record needs --api-base and --token or matching env vars.")
        return 2
    ok = True
    for payload in payloads:
        status, body = _post(args.api_base, args.token, payload)
        passed = status == 200
        ok = ok and passed
        print(f"{'PASS' if passed else 'FAIL'}: {payload['scenario_code']} status={status}")
        if not passed:
            print(body.decode("utf-8", errors="ignore")[:500])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
