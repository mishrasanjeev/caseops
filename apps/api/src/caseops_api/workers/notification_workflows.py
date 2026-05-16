from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable

from caseops_api.services.durable_workflows import durable_workflow_status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caseops-notification-workflow-worker",
        description=(
            "Check the CaseOps durable notification-workflow foundation. "
            "This entrypoint does not deliver notifications or schedule reminders."
        ),
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Emit redacted workflow configuration status and exit.",
    )
    parser.add_argument(
        "--require-available",
        action="store_true",
        help="Return a non-zero exit code when the durable workflow backend is unavailable.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _ = args.check_config
    status = durable_workflow_status()
    payload = {
        "service": "caseops-notification-workflow-worker",
        "delivery_enabled": False,
        "reminder_scheduling_enabled": False,
        "external_provider_calls_enabled": False,
        "status": status.public_dict(),
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    if args.require_available and not status.available:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
