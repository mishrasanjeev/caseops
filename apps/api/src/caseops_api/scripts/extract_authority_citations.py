"""CLI: extract Indian-legal citations from authority_documents.document_text
and populate authority_citations.

Per docs/PRD_BENCH_STRATEGY_2026-04-26.md §4.4 — citation extraction
unblocks L-B (judge_authority_affinity) so the bench-strategy panel
can surface top_authorities. Pure regex; zero Anthropic spend.

CLI:
    python -m caseops_api.scripts.extract_authority_citations
    python -m caseops_api.scripts.extract_authority_citations --batch-size 100
    python -m caseops_api.scripts.extract_authority_citations --limit 1000
"""
from __future__ import annotations

import argparse
import logging
import sys

from caseops_api.db.session import get_session_factory
from caseops_api.services.citation_extraction import run_extraction


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(prog="caseops-extract-authority-citations")
    parser.add_argument(
        "--batch-size", type=int, default=200,
        help="Documents per commit. Default 200.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N documents (testing aid).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    factory = get_session_factory()
    with factory() as session:
        summary = run_extraction(
            session, batch_size=args.batch_size, limit=args.limit,
        )

    print()
    print("=" * 70)
    print("Citation extraction summary")
    print("=" * 70)
    print(f"  docs processed   : {summary.docs_processed:>8,}")
    print(f"  docs skipped     : {summary.docs_skipped_already_done:>8,}")
    print(f"  citations found  : {summary.citations_extracted:>8,}")
    print(f"  citations resolved: {summary.citations_resolved:>8,}")
    print(f"  citations inserted: {summary.citations_inserted:>8,}")
    print()
    print("By reporter:")
    for rep, n in summary.by_reporter.most_common():
        print(f"  {rep:20} {n:>8,}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
