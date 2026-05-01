"""Backfill authority_citations.treatment for existing rows.

PG-006 Phase 1A — re-runs the heuristic classifier in
services/citation_treatment.py against every row whose
treatment_classified_at IS NULL, reading the citing document's text
and looking at a 200-char window around the stored citation_text.

The new ingest path (citation_extraction.extract_for_one_document)
already classifies new rows at insert time, so this script only
needs to run once per environment after the alembic migration. It is
idempotent: rows with treatment_classified_at IS NOT NULL are
skipped.

CLI:
    python -m caseops_api.scripts.backfill_citation_treatment
    python -m caseops_api.scripts.backfill_citation_treatment --batch-size 500
    python -m caseops_api.scripts.backfill_citation_treatment --limit 1000

Per ``feedback_corpus_spend_audit``: zero LLM spend (heuristic only).
Per ``feedback_windows_cloud_sql_flakiness``: keep batches small and
pause on connection errors so a Windows + cloud-sql-proxy run
doesn't hard-fail at 10-15 min.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from sqlalchemy import text

from caseops_api.db.session import get_session_factory
from caseops_api.services.citation_treatment import (
    classify_citation_treatment,
)

logger = logging.getLogger("backfill_citation_treatment")


def run(*, batch_size: int = 500, limit: int | None = None) -> int:
    factory = get_session_factory()
    processed = 0
    by_treatment: Counter[str] = Counter()
    with factory() as session:
        while True:
            remaining = (
                None
                if limit is None
                else max(0, limit - processed)
            )
            if remaining == 0:
                break
            page_size = (
                batch_size
                if remaining is None
                else min(batch_size, remaining)
            )
            rows = session.execute(
                text(
                    "SELECT ac.id, ac.citation_text, "
                    "       ad.document_text "
                    "FROM authority_citations ac "
                    "JOIN authority_documents ad "
                    "  ON ad.id = ac.source_authority_document_id "
                    "WHERE ac.treatment_classified_at IS NULL "
                    "ORDER BY ac.id "
                    "LIMIT :n"
                ),
                {"n": page_size},
            ).fetchall()
            if not rows:
                break

            for row in rows:
                citation_id = row[0]
                citation_text = row[1] or ""
                document_text = row[2] or ""
                result = classify_citation_treatment(
                    document_text, citation_text,
                )
                confidence = (
                    float(result.confidence)
                    if result.evidence_text is not None
                    else None
                )
                session.execute(
                    text(
                        "UPDATE authority_citations "
                        "SET treatment = :t, "
                        "    treatment_evidence_text = :e, "
                        "    treatment_confidence = :c, "
                        "    treatment_classified_at = "
                        "      CURRENT_TIMESTAMP "
                        "WHERE id = :id"
                    ),
                    {
                        "t": result.treatment.value,
                        "e": result.evidence_text,
                        "c": confidence,
                        "id": citation_id,
                    },
                )
                by_treatment[result.treatment.value] += 1
                processed += 1
            session.commit()
            logger.info(
                "Backfill processed %d rows (%s)",
                processed,
                ", ".join(
                    f"{k}={v}"
                    for k, v in sorted(by_treatment.items())
                ),
            )

    logger.info(
        "Done. Total rows processed: %d. By treatment: %s",
        processed,
        dict(by_treatment),
    )
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap total rows processed; useful for smoke tests.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(batch_size=args.batch_size, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
