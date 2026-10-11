"""One bounded iteration of the existing court queue, independent of API CPU."""

from __future__ import annotations

import argparse

from caseops_api.core.settings import get_settings

COURT_SYNC_WORKER_ADMISSION_PROTOCOL_VERSION = 1


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="caseops-court-sync-worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--batch-size",
        type=int,
        choices=range(1, 26),
        default=settings.court_sync_worker_batch_size,
    )
    parser.add_argument("--skip-migrations", action="store_true")
    parser.add_argument("--admission-disabled", action="store_true")
    args = parser.parse_args(argv)
    if not args.once:
        parser.error("court sync worker requires --once")
    if type(args.batch_size) is not int or not 1 <= args.batch_size <= 25:
        parser.error("court sync batch size must be between 1 and 25")
    protocol = getattr(settings, "court_sync_worker_admission_protocol_version", 0)
    admission = getattr(settings, "court_sync_worker_admission_enabled", None)
    if type(protocol) is not int or protocol != COURT_SYNC_WORKER_ADMISSION_PROTOCOL_VERSION:
        parser.error("court sync worker requires explicit admission protocol 1")
    if type(admission) is not bool:
        parser.error("court sync worker requires explicit Boolean admission")
    if args.admission_disabled or not admission:
        print(
            "CaseOps court sync worker: admission_protocol=1 admission=disabled "
            "recovered=0 attempted=0 completed=0 failed=0 unfinalized=0",
            flush=True,
        )
        return 0
    age = settings.court_sync_stale_after_minutes
    if type(age) is not int or not 1 <= age <= 1440:
        parser.error("court sync recovery age must be between 1 and 1440 minutes")

    # Import the SQL services only after admission. Migrations are release-owned.
    from caseops_api.services.court_sync_jobs import (
        drain_matter_court_sync_jobs,
        recover_stale_matter_court_sync_jobs,
    )

    recovered = recover_stale_matter_court_sync_jobs(
        stale_after_minutes=age,
        limit=args.batch_size,
    )
    outcomes: dict[str, int] = {}
    attempted = drain_matter_court_sync_jobs(limit=args.batch_size, outcomes=outcomes)
    print(
        "CaseOps court sync worker: admission_protocol=1 admission=enabled "
        f"recovered={recovered} attempted={attempted} "
        f"completed={outcomes.get('completed', 0)} failed={outcomes.get('failed', 0)} "
        f"unfinalized={outcomes.get('unfinalized', 0)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
