"""Corpus quality backfill for pre-Layer-2 documents.

Two jobs:

1. Rewrite stale titles and stale dates on the existing ~13.6 K
   authority_documents. No LLM cost — pure Python.
   - Titles: re-run ``_derive_title`` on ``document_text`` (skips
     reporter banners, prefers "X v. Y" lines).
   - Dates: blank ``decision_date`` when it's Jan 1 (the old default)
     AND the text has no parseable date. Honest nulls > fake precision.

2. Run the Layer-2 structured extraction pass on documents whose
   ``structured_version`` is NULL or below the current pipeline
   version. One Haiku call per document.

Run modes::

    # Pure-code pass (no LLM cost) — title + date cleanup
    caseops-backfill-corpus-quality --stage clean

    # Layer-2 structured extraction (Haiku cost) — 13.6 K docs at
    # ~\$0.003/doc = ~\$40 for the full corpus.
    caseops-backfill-corpus-quality --stage structured --limit 100

    # Full run (clean then structured)
    caseops-backfill-corpus-quality --stage all
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_ingest import (
    _derive_title,
    _guess_decision_date,
)
from caseops_api.services.corpus_structured import (
    STRUCTURED_VERSION,
    extract_and_persist_structured,
)

logger = logging.getLogger("caseops.backfill")


def _clean_titles_and_dates(session: Session, *, dry_run: bool) -> tuple[int, int]:
    """Rewrite titles/dates on every doc whose text is available.

    Returns (titles_updated, dates_blanked).
    """
    titles_updated = 0
    dates_blanked = 0
    stmt = (
        select(AuthorityDocument)
        .where(AuthorityDocument.document_text.is_not(None))
    )
    docs = session.scalars(stmt).all()
    logger.info("scanning %d docs for title/date cleanup", len(docs))
    for doc in docs:
        text = doc.document_text or ""
        new_title = _derive_title(_FakePath(doc.source_reference or doc.id), text)
        if new_title and new_title != doc.title:
            doc.title = new_title[:255]
            titles_updated += 1
        # Date: if current date is Jan 1 (likely synthetic) and we
        # can't parse anything better, blank it.
        dd = doc.decision_date
        if dd is not None and dd.month == 1 and dd.day == 1:
            default_year = dd.year
            parsed = _guess_decision_date(text, default_year=default_year)
            if parsed is None or (
                parsed.month == 1 and parsed.day == 1 and parsed.year == default_year
            ):
                doc.decision_date = None
                dates_blanked += 1
            else:
                doc.decision_date = parsed
    if not dry_run:
        session.flush()
    return titles_updated, dates_blanked


class _FakePath:
    """Tiny shim so ``_derive_title`` (which wants a Path) works with
    just a source_reference string. We only need ``stem``."""

    def __init__(self, reference: str) -> None:
        self._ref = reference

    @property
    def stem(self) -> str:
        name = self._ref.rsplit("/", 1)[-1]
        if name.endswith(".pdf"):
            name = name[:-4]
        return name


def _structured_pass(
    session: Session, *, limit: int | None, dry_run: bool
) -> int:
    """Run structured extraction on every doc whose
    ``structured_version`` is older than the current pipeline.
    """
    # Descending chronological order so the most-cited recent years
    # get structured first; if the budget or credit runs out, what's
    # left unannotated is the historical long-tail, not current work.
    # ``nulls_last`` keeps docs with unknown dates at the bottom.
    stmt = (
        select(AuthorityDocument)
        .where(
            (AuthorityDocument.structured_version.is_(None))
            | (AuthorityDocument.structured_version < STRUCTURED_VERSION)
        )
        .order_by(
            AuthorityDocument.decision_date.desc().nulls_last(),
            AuthorityDocument.ingested_at.desc(),
        )
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    docs = session.scalars(stmt).all()
    logger.info(
        "structured extraction on %d docs (version target=%d)",
        len(docs), STRUCTURED_VERSION,
    )
    done = 0
    t0 = time.time()
    for i, doc in enumerate(docs, start=1):
        try:
            summary = extract_and_persist_structured(session, document=doc)
        except Exception:
            logger.exception("structured extraction failed for %s", doc.id)
            session.rollback()
            continue
        done += 1
        if not dry_run:
            session.commit()
        if i % 10 == 0:
            rate = i / max(time.time() - t0, 1e-6)
            logger.info(
                "%d/%d docs done (%.1f/s, last provider=%s model=%s)",
                i, len(docs), rate, summary.provider, summary.model,
            )
    return done


def run(
    *,
    stage: str,
    limit: int | None,
    dry_run: bool,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    Session = get_session_factory()
    with Session() as session:
        if stage in ("clean", "all"):
            titles, dates = _clean_titles_and_dates(session, dry_run=dry_run)
            sys.stdout.write(
                f"clean-pass: titles_updated={titles} dates_blanked={dates}\n"
            )
            if not dry_run:
                session.commit()
        if stage in ("structured", "all"):
            done = _structured_pass(session, limit=limit, dry_run=dry_run)
            sys.stdout.write(f"structured-pass: {done} docs annotated\n")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-backfill-corpus-quality")
    parser.add_argument(
        "--stage",
        choices=["clean", "structured", "all"],
        default="all",
        help=(
            "clean = rewrite titles + blank fake dates (no LLM). "
            "structured = run the Haiku structured-extraction pass. "
            "all = both, in order."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the structured pass to N docs (useful for budget-gated runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute rewrites / annotations but do not commit.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(stage=args.stage, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
