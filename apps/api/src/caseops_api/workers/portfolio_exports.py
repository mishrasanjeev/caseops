"""Bounded recovery for durable export admissions, separate from request CPU."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from caseops_api.db.models import IpPortfolioExportJob
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_portfolio_workflow import (
    list_recoverable_portfolio_exports,
    run_portfolio_export_job,
)


def legacy_unresolved_exports() -> tuple[int, bool]:
    with get_session_factory()() as session:
        rows = session.scalars(
            select(IpPortfolioExportJob.id)
            .where(
                IpPortfolioExportJob.dispatch_protocol_version == 0,
                IpPortfolioExportJob.status.in_(("pending", "running")),
            )
            .order_by(IpPortfolioExportJob.created_at, IpPortfolioExportJob.id)
            .limit(6)
        ).all()
    return min(len(rows), 5), len(rows) > 5


def run_once(*, limit: int) -> dict:
    if not 1 <= limit <= 5:
        raise ValueError("Portfolio export recovery accepts one to five jobs.")
    jobs = list_recoverable_portfolio_exports(limit=limit)
    if len(jobs) > limit or len(set(jobs)) != len(jobs):
        raise RuntimeError("Portfolio export recovery returned an invalid inventory.")
    outcomes = {"completed": 0, "busy": 0, "terminal": 0, "missing": 0}
    for job_id in jobs:
        outcome = run_portfolio_export_job(job_id)
        if outcome not in outcomes:
            raise RuntimeError("Portfolio export worker returned an unknown outcome.")
        outcomes[outcome] += 1
    legacy_count, legacy_truncated = legacy_unresolved_exports()
    return {
        "schema": "caseops.portfolio-export-recovery/v1",
        "status": "ok",
        "selected": len(jobs),
        "outcomes": outcomes,
        "legacy_unresolved_capped_count": legacy_count,
        "legacy_scan_truncated": legacy_truncated,
        "legacy_rows_claimed": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recover at most five protocol1 portfolio exports."
    )
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--batch-size", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args(argv)
    print(json.dumps(run_once(limit=args.batch_size), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
