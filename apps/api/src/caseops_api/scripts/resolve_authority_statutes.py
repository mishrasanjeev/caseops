"""Slice S3 (MOD-TS-017) — Cloud Run Job entrypoint.

Walks every AuthorityDocument with sections_cited_json but no
authority_statute_references yet, parses each section string,
inserts FK rows.

CLI: ``python -m caseops_api.scripts.resolve_authority_statutes``
"""
from __future__ import annotations

import logging
import sys

from caseops_api.db.session import get_session_factory
from caseops_api.services.statute_resolver import (
    resolve_all_unprocessed_authorities,
)

logger = logging.getLogger("resolve_authority_statutes")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Loop until no more candidates remain. The inner function caps at
    # batch_size=500 candidates per call (a hard LIMIT in the SQL); the
    # outer loop here drains the remaining 86k+ docs in one job
    # execution instead of requiring 170+ separate Cloud Run job runs.
    totals = {
        "authorities_seen": 0, "matched": 0, "unmatched": 0,
        "skipped_existing": 0, "errors": 0, "iterations": 0,
    }
    with get_session_factory()() as session:
        while True:
            summary = resolve_all_unprocessed_authorities(
                session, batch_size=500,
            )
            totals["iterations"] += 1
            for k in ("authorities_seen", "matched", "unmatched",
                      "skipped_existing", "errors"):
                totals[k] += summary[k]
            logger.info(
                "iteration %d: %s (running totals: matched=%d, unmatched=%d)",
                totals["iterations"], summary,
                totals["matched"], totals["unmatched"],
            )
            if summary["authorities_seen"] == 0:
                break
    logger.info("resolve_authority_statutes COMPLETE: %s", totals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
