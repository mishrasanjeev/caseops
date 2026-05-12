"""Backfill predictive outcome classifications and aggregate snapshots.

Examples:
    python -m caseops_api.scripts.backfill_predictive_outcomes --forum-level high_court
    python -m caseops_api.scripts.backfill_predictive_outcomes \
        --court-name "Delhi High Court" --year-range 2022-2026
    python -m caseops_api.scripts.backfill_predictive_outcomes --limit 100 --dry-run --no-llm
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from caseops_api.db.session import get_session_factory
from caseops_api.services.predictive_outcomes import (
    backfill_predictive_outcomes,
    stats_to_dict,
)

logger = logging.getLogger("backfill_predictive_outcomes")


def parse_year_range(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    parts = value.split("-", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("year range must be START-END, e.g. 2020-2026")
    try:
        start = int(parts[0])
        end = int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("year range must contain integer years") from exc
    if start > end:
        raise argparse.ArgumentTypeError("year range start must be <= end")
    return (start, end)


def run(
    *,
    forum_level: str | None,
    court_name: str | None,
    year_range: tuple[int, int] | None,
    judge_id: str | None,
    matter_type: str | None,
    limit: int | None,
    batch_size: int,
    dry_run: bool,
    budget_usd: float | None,
    use_llm: bool,
    force: bool,
    only_unclassified: bool,
) -> dict[str, object]:
    factory = get_session_factory()
    with factory() as session:
        stats = backfill_predictive_outcomes(
            session,
            forum_level=forum_level,
            court_name=court_name,
            year_range=year_range,
            judge_id=judge_id,
            matter_type=matter_type,
            limit=limit,
            batch_size=batch_size,
            dry_run=dry_run,
            budget_usd=budget_usd,
            use_llm=use_llm,
            force=force,
            only_unclassified=only_unclassified,
        )
        payload = stats_to_dict(stats)
    logger.info("Predictive outcome backfill complete: %s", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forum-level", default=None)
    parser.add_argument("--court-name", default=None)
    parser.add_argument("--year-range", type=parse_year_range, default=None)
    parser.add_argument("--judge-id", default=None)
    parser.add_argument("--matter-type", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--budget-usd", type=float, default=None)
    llm = parser.add_mutually_exclusive_group()
    llm.add_argument("--use-llm", dest="use_llm", action="store_true")
    llm.add_argument("--no-llm", dest="use_llm", action="store_false")
    parser.set_defaults(use_llm=False)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only-unclassified", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    payload = run(
        forum_level=args.forum_level,
        court_name=args.court_name,
        year_range=args.year_range,
        judge_id=args.judge_id,
        matter_type=args.matter_type,
        limit=args.limit,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        budget_usd=args.budget_usd,
        use_llm=args.use_llm,
        force=args.force,
        only_unclassified=args.only_unclassified or not args.force,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
