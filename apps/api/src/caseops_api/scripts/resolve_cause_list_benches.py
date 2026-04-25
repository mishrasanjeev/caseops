"""Slice B (MOD-TS-001-C) — resolve every unprocessed
matter_cause_list_entries.bench_name into Judge FK references.

Idempotent: only touches rows where judges_json IS NULL.

CLI:
    python -m caseops_api.scripts.resolve_cause_list_benches
"""
from __future__ import annotations

import logging
import sys

from caseops_api.db.session import get_session_factory
from caseops_api.services.bench_resolver import resolve_all_unprocessed

logger = logging.getLogger("resolve_cause_list_benches")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    with get_session_factory()() as session:
        summary = resolve_all_unprocessed(session)
    logger.info("resolve_cause_list_benches: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
