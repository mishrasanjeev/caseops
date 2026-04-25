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
    with get_session_factory()() as session:
        # Pull a generous batch each run; the backfill job is idempotent
        # so multiple runs converge on the full corpus.
        summary = resolve_all_unprocessed_authorities(
            session, batch_size=500,
        )
    logger.info("resolve_authority_statutes: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
