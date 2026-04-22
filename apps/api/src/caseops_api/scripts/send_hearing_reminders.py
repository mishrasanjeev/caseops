"""CLI entry point for the hearing-reminders worker.

Intended for Cloud Scheduler → Cloud Run Job on a ~5 minute cadence:

    caseops-send-hearing-reminders            # auto: obeys the flag
    caseops-send-hearing-reminders --dry-run  # never send, even if on
    caseops-send-hearing-reminders --live     # force send; fail loudly
                                                if provider unset

See ``services/hearing_reminders.py`` for the state machine and
``memory/feedback_fix_vs_mitigation.md`` for why this ships
dark-launched (persist intent, send later).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterable
from typing import Literal

from caseops_api.db.session import get_session_factory
from caseops_api.services.hearing_reminders import run_reminder_worker


def run(
    *, mode: Literal["auto", "dry_run", "live"] = "auto", limit: int = 100,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        report = run_reminder_worker(session, mode=mode, limit=limit)
    # Machine-readable output for Cloud Scheduler → Cloud Run Job logs.
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="caseops-send-hearing-reminders",
        description=(
            "Drain QUEUED hearing reminders whose scheduled_for has passed."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "dry_run", "live"),
        default="auto",
        help=(
            "auto: send only if the feature flag + SendGrid creds are set; "
            "otherwise log 'would send' and leave rows QUEUED. "
            "dry_run: never send. "
            "live: force send; fail loudly if the provider is unset."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=100, help="Max rows to process per run.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(mode=args.mode, limit=args.limit)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
