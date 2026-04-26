"""CLI: refresh L-A / L-B / L-C bench-strategy analysis layers.

Per docs/PRD_BENCH_STRATEGY_2026-04-26.md §4.4. Pure SQL aggregation —
zero Anthropic spend. Suitable for nightly cron.

CLI:
    python -m caseops_api.scripts.refresh_bench_analysis_layers
    python -m caseops_api.scripts.refresh_bench_analysis_layers --batch-size 200
    python -m caseops_api.scripts.refresh_bench_analysis_layers --layer L-A
"""
from __future__ import annotations

import argparse
import logging
import sys

from caseops_api.db.session import get_session_factory
from caseops_api.services.bench_analysis_layers import (
    RefreshSummary,
    refresh_all_layers,
    refresh_judge_authority_affinity,
    refresh_judge_decision_index,
    refresh_judge_statute_focus,
)

logger = logging.getLogger("refresh_bench_analysis_layers")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="caseops-refresh-bench-analysis-layers",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="L-A batch size (per court_id resolution + per-judge match).",
    )
    parser.add_argument(
        "--layer", choices=["L-A", "L-B", "L-C", "all"], default="all",
        help="Restrict to one layer (default: all three in dep order).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    factory = get_session_factory()
    summary: RefreshSummary
    with factory() as session:
        if args.layer == "L-A":
            summary = refresh_judge_decision_index(
                session, batch_size=args.batch_size,
            )
        elif args.layer == "L-B":
            summary = RefreshSummary()
            refresh_judge_authority_affinity(session, summary=summary)
        elif args.layer == "L-C":
            summary = RefreshSummary()
            refresh_judge_statute_focus(session, summary=summary)
        else:
            summary = refresh_all_layers(session, batch_size=args.batch_size)

    print()
    print("=" * 78)
    print("Bench-strategy analysis layers refresh summary")
    print("=" * 78)
    p = print
    p(f"  L-A processed   : {summary.judge_decision_index_rows:>8,}")
    p(f"  L-A inserted    : {summary.judge_decision_index_inserted:>8,}")
    p(f"  L-A unmatched   : {summary.skipped_unmatched_judges:>8,}")
    p(f"  L-B affinity    : {summary.judge_authority_affinity_rows:>8,}")
    p(f"  L-C statute     : {summary.judge_statute_focus_rows:>8,}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
