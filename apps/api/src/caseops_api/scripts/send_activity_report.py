from __future__ import annotations

import argparse
import json
import sys

from caseops_api.db.session import get_session_factory
from caseops_api.services.activity_reports import (
    build_activity_report,
    send_activity_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    with get_session_factory()() as session:
        report = build_activity_report(session)
    status = "dry_run" if args.dry_run else send_activity_report(report)
    segments = report.get("segments", {})
    account_count = sum(
        int(segment.get("company_count", 0)) for segment in segments.values()
    )
    # Cloud Run job logs are an operational surface, not a report delivery
    # channel. Never emit the tenant names, IDs, activity, or financial values
    # contained in ``report``. The bounded summary is sufficient for alerting.
    print(
        json.dumps(
            {
                "account_count": account_count,
                "generated_at": report.get("generated_at"),
                "status": status,
            },
            sort_keys=True,
        )
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())
