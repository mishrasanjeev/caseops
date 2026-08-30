from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime

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
        "operator_notes": "Generated local fixture only; not production-readiness evidence.",
        "attachment_refs": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate local-safe Pine Labs UAT fixture output. This helper cannot "
            "record production-readiness evidence."
        )
    )
    parser.add_argument("--scenario", choices=SCENARIOS, action="append")
    args = parser.parse_args(argv)

    if not _safe_env():
        print("Refusing to run: CASEOPS_PINE_LABS_ENV must be mock or clearly UAT.")
        return 2
    scenarios = args.scenario or list(SCENARIOS)
    payloads = [_evidence_payload(scenario) for scenario in scenarios]
    print(json.dumps({"fixtures": payloads}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
