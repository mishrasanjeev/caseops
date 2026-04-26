"""Build a (normalized_reference -> authority_document_id) map by
scanning each judgment's header text for the citation forms it
carries about itself.

Per the 2026-04-26 Track B finding: my citation extractor produces
SCC-format citations like '(2018) 6 SCC 1', but our corpus stores
neutral_citation in the newer INSC format ('2023 INSC 677') and
case_reference as docket numbers. The two formats never match, so
99.97% of extracted citations cannot resolve to a corpus document.

This script closes the gap WITHOUT a schema change: it extracts SCC
patterns from the FIRST 2000 chars of each authority_document's text
(where the citation form typically appears in the header), then
backfills authority_citations.cited_authority_document_id by
matching normalized_reference.

CLI:
    python -m caseops_api.scripts.backfill_self_citation_map
    python -m caseops_api.scripts.backfill_self_citation_map --batch-size 500
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import text

from caseops_api.db.session import get_session_factory
from caseops_api.services.citation_extraction import extract_citations_from_text

logger = logging.getLogger("backfill_self_citation_map")


def run(*, batch_size: int = 500) -> int:
    factory = get_session_factory()
    # Step 1: build the (normalized_reference -> doc_id) map by scanning
    # the FIRST 4000 chars of each doc (the header where the
    # judgment's own citation typically appears, e.g. 'Reportable:
    # (2018) 6 SCC 1' or 'Citation: AIR 2020 SC 145').
    citation_to_doc: dict[str, str] = {}
    docs_scanned = 0
    docs_with_self_citation = 0
    offset = 0
    with factory() as session:
        while True:
            rows = session.execute(
                text(
                    "SELECT id, LEFT(document_text, 4000) AS header "
                    "FROM authority_documents "
                    "WHERE document_text IS NOT NULL "
                    "ORDER BY id ASC LIMIT :lim OFFSET :off"
                ),
                {"lim": batch_size, "off": offset},
            ).fetchall()
            if not rows:
                break
            for r in rows:
                docs_scanned += 1
                doc_id, header = r[0], r[1]
                cites = extract_citations_from_text(header or "")
                if cites:
                    docs_with_self_citation += 1
                for norm, _ctext, _reporter in cites:
                    # First-write-wins: if two judgments declare the
                    # same citation, keep the older one (more likely
                    # the original; later docs probably cite back to it
                    # in their reasoning).
                    if norm not in citation_to_doc:
                        citation_to_doc[norm] = doc_id
            offset += batch_size
            logger.info(
                "scan: %d docs processed, %d with self-citations, %d unique citations indexed",
                docs_scanned, docs_with_self_citation, len(citation_to_doc),
            )

    logger.info(
        "INDEX BUILT: %d docs scanned, %d with self-citation, "
        "%d unique normalized_references mapped to corpus docs",
        docs_scanned, docs_with_self_citation, len(citation_to_doc),
    )

    # Step 2: backfill authority_citations.cited_authority_document_id
    # for rows whose normalized_reference is in the map.
    backfilled = 0
    skipped_self = 0
    with factory() as session:
        for norm, target_doc_id in citation_to_doc.items():
            res = session.execute(
                text(
                    "UPDATE authority_citations "
                    "SET cited_authority_document_id = :target "
                    "WHERE normalized_reference = :norm "
                    "  AND cited_authority_document_id IS NULL "
                    "  AND source_authority_document_id != :target"
                ),
                {"target": target_doc_id, "norm": norm},
            )
            backfilled += res.rowcount or 0
            # Track self-citations (a doc citing its own header
            # repetition) — these are filtered by the != condition.
            res2 = session.execute(
                text(
                    "SELECT COUNT(*) FROM authority_citations "
                    "WHERE normalized_reference = :norm "
                    "  AND source_authority_document_id = :target"
                ),
                {"norm": norm, "target": target_doc_id},
            ).scalar()
            skipped_self += int(res2 or 0)
        session.commit()

    print()
    print("=" * 70)
    print("Self-citation map backfill summary")
    print("=" * 70)
    print(f"  docs scanned                   : {docs_scanned:>8,}")
    print(f"  docs w/ at least 1 self-cite   : {docs_with_self_citation:>8,}")
    print(f"  unique citations -> doc_id map : {len(citation_to_doc):>8,}")
    print(f"  authority_citations backfilled : {backfilled:>8,}")
    print(f"  self-citation rows skipped     : {skipped_self:>8,}")

    # Quick sanity: how many resolved citations now exist?
    with factory() as session:
        r = session.execute(
            text(
                "SELECT COUNT(*), COUNT(*) FILTER (WHERE cited_authority_document_id IS NOT NULL) "
                "FROM authority_citations"
            )
        ).fetchone()
        print(f"  authority_citations: total={r[0]:,}  resolved={r[1]:,}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(prog="caseops-backfill-self-citation-map")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(batch_size=args.batch_size)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
