#!/usr/bin/env python3
"""Write exact-release readiness evidence through the machine-only boundary."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from caseops_api.core.machine_readiness_auth import machine_readiness_signature  # noqa: E402

WRITE_PATH = "/api/internal/machine-readiness/evidence"
VALID_CONCLUSIONS = frozenset({"pass", "fail", "blocked"})


def _item(kind: str, value: str, evidence_ref: str) -> dict[str, str]:
    try:
        subject, conclusion = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{kind} values must use subject=pass|fail|blocked"
        ) from exc
    if not subject or conclusion not in VALID_CONCLUSIONS:
        raise argparse.ArgumentTypeError(f"{kind} values must use subject=pass|fail|blocked")
    return {
        "kind": kind,
        "subject": subject,
        "conclusion": conclusion,
        "evidence_ref": evidence_ref,
    }


def _pine_item(value: str, evidence_ref: str) -> dict[str, str]:
    try:
        result, target_run_id = value.rsplit("@", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "pine values must use subject=pass|fail|blocked@target-run-id"
        ) from exc
    item = _item("pine_labs_uat", result, evidence_ref)
    if not target_run_id:
        raise argparse.ArgumentTypeError("pine target-run-id must not be empty")
    item["target_run_id"] = target_run_id
    return item


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--producer", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--evidence-ref", required=True)
    parser.add_argument("--billing", action="append", default=[])
    parser.add_argument("--operational", action="append", default=[])
    parser.add_argument("--pine", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    secret = os.environ.get("CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET", "")
    if len(secret) < 32:
        raise SystemExit(
            "CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET must be configured with 32+ bytes"
        )

    try:
        items = [
            *(_item("billing_check", value, args.evidence_ref) for value in args.billing),
            *(_item("operational_gate", value, args.evidence_ref) for value in args.operational),
            *(_pine_item(value, args.evidence_ref) for value in args.pine),
        ]
    except argparse.ArgumentTypeError as exc:
        _parser().error(str(exc))
    if not items:
        _parser().error("at least one evidence item is required")

    payload = {
        "schema": "caseops.machine-readiness-write/v1",
        "producer": args.producer,
        "release_sha": args.release_sha,
        "run_id": args.run_id,
        "items": items,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = machine_readiness_signature(
        secret=secret,
        timestamp=timestamp,
        body=body,
    )
    request = urllib.request.Request(
        args.api_base.rstrip("/") + WRITE_PATH,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-CaseOps-Machine-Timestamp": timestamp,
            "X-CaseOps-Machine-Signature": signature,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2_048).decode("utf-8", errors="replace")
        raise SystemExit(f"machine evidence write failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"machine evidence write failed: {exc.reason}") from exc

    expected = {
        "release_sha": args.release_sha,
        "producer": args.producer,
        "run_id": args.run_id,
        "recorded_count": len(items),
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise SystemExit("machine evidence response did not match the submitted envelope")
    print(
        "Recorded "
        f"{len(items)} exact-release machine evidence item(s); "
        f"digest={result.get('evidence_digest', 'missing')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
