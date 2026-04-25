"""Slice D backfill — generate canonical aliases for every Judge.

Idempotent. Run after seed_sci_judges.py + seed_hc_judges.py have
populated the judges table; re-run after each new judge is added.

CLI:
    python -m caseops_api.scripts.backfill_judge_aliases
"""
from __future__ import annotations

import logging
import sys

from caseops_api.db.session import get_session_factory
from caseops_api.services.judge_aliases import backfill_canonical_aliases

logger = logging.getLogger("backfill_judge_aliases")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    with get_session_factory()() as session:
        inserted, skipped = backfill_canonical_aliases(session)
    logger.info(
        "backfill_judge_aliases: inserted=%d skipped_existing=%d",
        inserted, skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
