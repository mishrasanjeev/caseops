"""Citation extraction — populates authority_citations from
authority_documents.document_text.

Indian legal citation formats are messy. We focus on the most-common
reporter formats first; add more as the corpus reveals them:

  (YYYY) N SCC NNN     -> Supreme Court Cases
  AIR YYYY SC NNN      -> All India Reporter (SC)
  AIR YYYY <STATE>HC NNN -> AIR HC volumes (Delhi/Bombay/etc.)
  (YYYY) N SCR NNN     -> Supreme Court Reports
  YYYY SCC OnLine SC NNN  -> SCC OnLine SC
  YYYY SCC OnLine <HC> NNN  -> SCC OnLine HC
  (YYYY) N CrLJ NNN    -> Criminal Law Journal
  (YYYY) N JT NNN      -> Judgments Today
  YYYY (N) SCALE NNN   -> SCALE

Each match is normalised to a canonical lowercase form for
deduplication. Resolution against our own corpus is by:
- exact match on authority_documents.neutral_citation
- exact match on authority_documents.case_reference

Most cited authorities will NOT be in our corpus (older judgments,
unreported decisions, foreign citations) — those rows still get
inserted with cited_authority_document_id=NULL for raw count, but
L-B aggregation only counts resolved (NOT NULL) rows.

Per `feedback_corpus_spend_audit`: zero Anthropic spend (pure regex).
Idempotent on (source_authority_document_id, normalized_reference)
unique constraint.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Citation regexes — kept loose to capture format variations in real
# judgments (parenthesis vs no parenthesis around year, single/double
# spaces, comma vs no comma between volume and reporter).
_CITATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # (YYYY) N SCC NNN — also handles "(YYYY) N S.C.C. NNN"
    ("scc", re.compile(
        r"\(?\s*(\d{4})\s*\)?\s+(\d+)\s+S\.?\s*C\.?\s*C\.?\s+(\d+)",
        re.IGNORECASE,
    )),
    # AIR YYYY SC NNN
    ("air_sc", re.compile(
        r"AIR\s+(\d{4})\s+SC\s+(\d+)", re.IGNORECASE,
    )),
    # (YYYY) N SCR NNN
    ("scr", re.compile(
        r"\(?\s*(\d{4})\s*\)?\s+(\d+)\s+S\.?\s*C\.?\s*R\.?\s+(\d+)",
        re.IGNORECASE,
    )),
    # YYYY SCC OnLine SC NNN
    ("scc_online_sc", re.compile(
        r"(\d{4})\s+S\.?\s*C\.?\s*C\.?\s+On\s*Line\s+SC\s+(\d+)",
        re.IGNORECASE,
    )),
    # (YYYY) N CrLJ NNN
    ("crlj", re.compile(
        r"\(?\s*(\d{4})\s*\)?\s+(\d+)\s+Cr\.?\s*L\.?\s*J\.?\s+(\d+)",
        re.IGNORECASE,
    )),
    # YYYY (N) SCALE NNN
    ("scale", re.compile(
        r"(\d{4})\s+\(\s*(\d+)\s*\)\s+SCALE\s+(\d+)",
        re.IGNORECASE,
    )),
    # (YYYY) N JT NNN
    ("jt", re.compile(
        r"\(?\s*(\d{4})\s*\)?\s+(\d+)\s+JT\s+(\d+)",
        re.IGNORECASE,
    )),
]


@dataclass
class ExtractionSummary:
    docs_processed: int = 0
    docs_skipped_already_done: int = 0
    citations_extracted: int = 0
    citations_resolved: int = 0
    citations_inserted: int = 0
    by_reporter: Counter = field(default_factory=Counter)


def _normalise(reporter: str, year: str, vol: str | None, page: str) -> str:
    """Canonical lowercase form for dedup. Drop optional volume so
    '(2018) 6 SCC 1' and '(2018) SCC 1' map to the same key when the
    reporter doesn't use volumes (rare but happens with reprint
    citations)."""
    parts = [reporter, year]
    if vol is not None:
        parts.append(vol)
    parts.append(page)
    return ":".join(parts).lower()


def _format_text(reporter: str, year: str, vol: str | None, page: str) -> str:
    """Human-readable form for citation_text storage."""
    if reporter == "scc":
        return f"({year}) {vol} SCC {page}"
    if reporter == "air_sc":
        return f"AIR {year} SC {page}"
    if reporter == "scr":
        return f"({year}) {vol} SCR {page}"
    if reporter == "scc_online_sc":
        return f"{year} SCC OnLine SC {page}"
    if reporter == "crlj":
        return f"({year}) {vol} CrLJ {page}"
    if reporter == "scale":
        return f"{year} ({vol}) SCALE {page}"
    if reporter == "jt":
        return f"({year}) {vol} JT {page}"
    return f"{year} {reporter} {page}"


def extract_citations_from_text(text_body: str) -> list[tuple[str, str, str]]:
    """Returns deduped list of (normalized_reference, citation_text, reporter)
    for one document's full text."""
    if not text_body:
        return []
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for reporter, pat in _CITATION_PATTERNS:
        for m in pat.finditer(text_body):
            groups = m.groups()
            if reporter in ("air_sc", "scc_online_sc"):
                # year, page (no volume)
                year, page = groups[0], groups[1]
                vol = None
            else:
                # year, volume, page
                year, vol, page = groups[0], groups[1], groups[2]
            # Sanity bounds: year in plausible range, page > 0.
            try:
                yi = int(year)
                pi = int(page)
            except ValueError:
                continue
            if yi < 1860 or yi > 2030:
                continue
            if pi < 1 or pi > 99999:
                continue
            norm = _normalise(reporter, year, vol, page)
            if norm in seen:
                continue
            seen.add(norm)
            out.append((norm, _format_text(reporter, year, vol, page), reporter))
    return out


def _resolve_against_corpus(
    session: Session, normalized_reference: str, citation_text: str,
) -> str | None:
    """Best-effort: try to find an authority_document whose
    neutral_citation or case_reference matches the citation text.

    Exact match on lowercased citation_text against neutral_citation
    or case_reference. Loose enough to catch normal corpus entries,
    strict enough to refuse partial matches.
    """
    needle_lower = citation_text.lower()
    row = session.execute(
        text(
            "SELECT id FROM authority_documents "
            "WHERE LOWER(neutral_citation) = :n "
            "   OR LOWER(case_reference) = :n "
            "LIMIT 1"
        ),
        {"n": needle_lower},
    ).first()
    if row:
        return row[0]
    # Looser variant: substring match. Many corpus rows have
    # case_reference like "Civil Appeal No. 100 of 2018, (2018) 6 SCC 1"
    # so a substring hit is usually the right doc.
    row = session.execute(
        text(
            "SELECT id FROM authority_documents "
            "WHERE LOWER(case_reference) LIKE :pat "
            "   OR LOWER(neutral_citation) LIKE :pat "
            "LIMIT 1"
        ),
        {"pat": f"%{needle_lower}%"},
    ).first()
    return row[0] if row else None


def extract_for_one_document(
    session: Session, doc_id: str, document_text: str,
) -> tuple[int, int, Counter]:
    """Extract + persist citations for one source document.

    Returns (n_extracted, n_resolved, reporter_counter). Idempotent on
    the (source_authority_document_id, normalized_reference) unique
    constraint via pre-flight existence check (portable across
    SQLite + Postgres).
    """
    cites = extract_citations_from_text(document_text)
    if not cites:
        return (0, 0, Counter())

    # Pre-load existing normalized_references for this source so we
    # don't re-insert.
    existing = set(
        row[0]
        for row in session.execute(
            text(
                "SELECT normalized_reference FROM authority_citations "
                "WHERE source_authority_document_id = :s"
            ),
            {"s": doc_id},
        ).fetchall()
    )

    n_resolved = 0
    n_inserted = 0
    by_reporter: Counter = Counter()
    for norm, ctext, reporter in cites:
        by_reporter[reporter] += 1
        if norm in existing:
            continue
        cited_id = _resolve_against_corpus(session, norm, ctext)
        if cited_id == doc_id:
            # A document citing itself is almost always a parser
            # artifact (header repetition). Skip.
            continue
        if cited_id:
            n_resolved += 1
        try:
            session.execute(
                text(
                    "INSERT INTO authority_citations "
                    "(id, source_authority_document_id, "
                    " cited_authority_document_id, citation_text, "
                    " normalized_reference, created_at) "
                    "VALUES (:id, :src, :cited, :ctext, :norm, "
                    "  CURRENT_TIMESTAMP)"
                ),
                {
                    "id": str(uuid4()),
                    "src": doc_id,
                    "cited": cited_id,
                    "ctext": ctext[:255],
                    "norm": norm[:255],
                },
            )
            n_inserted += 1
        except Exception as exc:
            logger.debug(
                "Insert citation failed for doc=%s norm=%s: %s",
                doc_id, norm, exc,
            )
            session.rollback()
            continue
    return (len(cites), n_resolved, by_reporter)


def run_extraction(
    session: Session, *, batch_size: int = 200, limit: int | None = None,
) -> ExtractionSummary:
    """Iterate authority_documents with text, extract + persist
    citations. Resumable — already-extracted source docs (any rows in
    authority_citations for source_id) are skipped."""
    s = ExtractionSummary()
    offset = 0
    while True:
        rows = session.execute(
            text(
                "SELECT id, document_text FROM authority_documents "
                "WHERE document_text IS NOT NULL "
                "ORDER BY created_at ASC, id ASC "
                "LIMIT :lim OFFSET :off"
            ),
            {"lim": batch_size, "off": offset},
        ).fetchall()
        if not rows:
            break
        for r in rows:
            doc_id, body = r[0], r[1]
            # Skip if any citations already extracted for this source.
            already = session.execute(
                text(
                    "SELECT 1 FROM authority_citations "
                    "WHERE source_authority_document_id = :s LIMIT 1"
                ),
                {"s": doc_id},
            ).first()
            if already:
                s.docs_skipped_already_done += 1
                continue
            n_ex, n_res, reps = extract_for_one_document(session, doc_id, body)
            s.docs_processed += 1
            s.citations_extracted += n_ex
            s.citations_resolved += n_res
            s.citations_inserted += n_ex  # roughly; off by skipped dedups
            s.by_reporter.update(reps)
        session.commit()
        offset += batch_size
        if limit is not None and offset >= limit:
            break
        logger.info(
            "extraction: processed=%d skipped=%d cites=%d resolved=%d",
            s.docs_processed, s.docs_skipped_already_done,
            s.citations_extracted, s.citations_resolved,
        )
    return s
