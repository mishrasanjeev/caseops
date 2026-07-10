from __future__ import annotations
import argparse, json, sys
from caseops_api.db.session import get_session_factory
from caseops_api.services.activity_reports import build_activity_report, send_activity_report

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    with get_session_factory()() as session:
        report = build_activity_report(session)
    status = "dry_run" if args.dry_run else send_activity_report(report)
    print(json.dumps({"status": status, "report": report}, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
