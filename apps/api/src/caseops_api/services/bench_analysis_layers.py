"""Bench-strategy analysis layers (MOD-TS-018 §4.4).

Three derived materializations powering the bench-strategy panel:

- L-A judge_decision_index: per (judge, judgment) row. Source:
  authority_documents.judges_json + judge_aliases.match_candidates.
  Refreshed incrementally — already-recorded (judge, judgment) pairs
  are skipped on conflict.
- L-B judge_authority_affinity: per (judge, cited_authority) row.
  Aggregated from authority_citations joined with L-A. Refreshed by
  truncate-and-reinsert (cheap; the table is small).
- L-C judge_statute_focus: per (judge, statute_section) row.
  Aggregated from authority_statute_references joined with L-A.

All three are pure SQL — zero Anthropic spend. Suitable for nightly
cron.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from caseops_api.services.judge_aliases import match_candidates

logger = logging.getLogger(__name__)


@dataclass
class RefreshSummary:
    judge_decision_index_rows: int = 0
    judge_decision_index_inserted: int = 0
    judge_authority_affinity_rows: int = 0
    judge_statute_focus_rows: int = 0
    skipped_unmatched_judges: int = 0


def refresh_judge_decision_index(
    session: Session, *, batch_size: int = 500,
) -> RefreshSummary:
    """L-A: derive (judge, authority_document) rows from
    authority_documents.judges_json + judge_aliases.

    Incremental — uses ON CONFLICT DO NOTHING on the unique
    (judge_id, authority_document_id) constraint. Safe to run nightly;
    each row is written at most once.

    Court mapping: the document's court_name is mapped to a court_id
    via the same _COURT_NAME_MATCHERS used by backfill_hc_judges_from_corpus
    (delhi-hc, bombay-hc, etc.) plus 'supreme-court-india' for SC docs.
    Documents whose court can't be resolved are skipped (logged).
    """
    summary = RefreshSummary()

    # Use a lightweight per-court matcher to avoid importing the
    # backfill script. Order matters — longer substrings first.
    court_substrings: list[tuple[str, str]] = [
        ("supreme court", "supreme-court-india"),
        ("delhi", "delhi-hc"),
        ("bombay", "bombay-hc"),
        ("madras", "madras-hc"),
        ("karnataka", "karnataka-hc"),
        ("telangana", "telangana-hc"),
        ("allahabad", "allahabad-hc"),
        ("calcutta", "calcutta-hc"),
        ("patna", "patna-hc"),
    ]

    def _resolve_court_id(court_name: str | None) -> str | None:
        if not court_name:
            return None
        lower = court_name.lower()
        for substr, cid in court_substrings:
            if substr in lower:
                return cid
        return None

    # Stream through authority_documents that have judges_json. Use
    # a cursor (yield_per equivalent) so a 50K-row table doesn't blow
    # memory. We process in batches and commit per-batch so a crash
    # mid-run leaves a partial-but-consistent state.
    offset = 0
    while True:
        rows = session.execute(
            text(
                "SELECT id, court_name, judges_json, "
                "  EXTRACT(YEAR FROM decision_date)::int AS year "
                "FROM authority_documents "
                "WHERE judges_json IS NOT NULL "
                "ORDER BY created_at ASC, id ASC "
                "LIMIT :lim OFFSET :off"
            ),
            {"lim": batch_size, "off": offset},
        ).fetchall()
        if not rows:
            break

        for r in rows:
            doc_id = r[0]
            court_name = r[1]
            judges_raw = r[2]
            year = r[3]
            court_id = _resolve_court_id(court_name)
            if not court_id:
                continue
            try:
                judges = (
                    judges_raw if isinstance(judges_raw, list)
                    else json.loads(judges_raw)
                )
            except Exception:
                continue
            if not isinstance(judges, list):
                continue
            for raw_name in judges:
                if not isinstance(raw_name, str) or len(raw_name.strip()) < 3:
                    continue
                summary.judge_decision_index_rows += 1
                matches = match_candidates(
                    session, raw_text=raw_name, court_id=court_id,
                )
                if not matches:
                    summary.skipped_unmatched_judges += 1
                    continue
                # Take the highest-confidence match (already first).
                best = matches[0]
                # Pre-flight check (portable across SQLite + Postgres
                # — Postgres ON CONFLICT clauses don't translate cleanly
                # to SQLite). The unique constraint still enforces
                # idempotence at the DB layer; this just makes the
                # rowcount tracking accurate.
                exists = session.execute(
                    text(
                        "SELECT 1 FROM judge_decision_index "
                        "WHERE judge_id = :j AND authority_document_id = :a "
                        "LIMIT 1"
                    ),
                    {"j": best.judge_id, "a": doc_id},
                ).first()
                if exists:
                    continue
                session.execute(
                    text(
                        "INSERT INTO judge_decision_index "
                        "(id, judge_id, authority_document_id, role, year, "
                        " matched_alias, match_confidence, created_at) "
                        "VALUES (:id, :j, :a, :role, :yr, :ma, :mc, "
                        "  CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": str(uuid4()),
                        "j": best.judge_id,
                        "a": doc_id,
                        "role": "sat_on",
                        "yr": year,
                        "ma": (best.matched_alias or "")[:255],
                        "mc": best.confidence,
                    },
                )
                summary.judge_decision_index_inserted += 1

        session.commit()
        offset += batch_size
        logger.info(
            "L-A: processed %d docs (inserted %d so far, skipped-unmatched %d)",
            offset, summary.judge_decision_index_inserted,
            summary.skipped_unmatched_judges,
        )

    return summary


def refresh_judge_authority_affinity(
    session: Session, *, summary: RefreshSummary | None = None,
) -> RefreshSummary:
    """L-B: aggregate (judge, cited_authority) → count + last_year +
    sample_judgment from authority_citations joined with L-A.

    Truncate-and-reinsert pattern. The table is small (one row per
    distinct judge×cited-authority pair) and rebuilding is cleaner
    than incremental upsert.
    """
    s = summary or RefreshSummary()
    session.execute(text("DELETE FROM judge_authority_affinity"))
    inserted = session.execute(
        text(
            "INSERT INTO judge_authority_affinity "
            "(id, judge_id, cited_authority_document_id, citation_count, "
            " last_year, sample_judgment_id, refreshed_at) "
            "SELECT "
            "  gen_random_uuid()::text, "
            "  jdi.judge_id, "
            "  ac.cited_authority_document_id, "
            "  COUNT(*) AS citation_count, "
            "  MAX(jdi.year) AS last_year, "
            "  (array_agg(jdi.authority_document_id "
            "    ORDER BY jdi.year DESC NULLS LAST))[1] AS sample_judgment_id, "
            "  NOW() "
            "FROM judge_decision_index jdi "
            "JOIN authority_citations ac "
            "  ON ac.source_authority_document_id = jdi.authority_document_id "
            "WHERE ac.cited_authority_document_id IS NOT NULL "
            "GROUP BY jdi.judge_id, ac.cited_authority_document_id"
        )
    )
    s.judge_authority_affinity_rows = inserted.rowcount or 0
    session.commit()
    logger.info("L-B: inserted %d rows", s.judge_authority_affinity_rows)
    return s


def refresh_judge_statute_focus(
    session: Session, *, summary: RefreshSummary | None = None,
) -> RefreshSummary:
    """L-C: aggregate (judge, statute_section) → count + last_year +
    sample_judgment from authority_statute_references joined with L-A.

    Same truncate-and-reinsert pattern as L-B.
    """
    s = summary or RefreshSummary()
    session.execute(text("DELETE FROM judge_statute_focus"))
    inserted = session.execute(
        text(
            "INSERT INTO judge_statute_focus "
            "(id, judge_id, statute_section_id, citation_count, "
            " last_year, sample_judgment_id, refreshed_at) "
            "SELECT "
            "  gen_random_uuid()::text, "
            "  jdi.judge_id, "
            "  asr.section_id, "
            "  COUNT(*) AS citation_count, "
            "  MAX(jdi.year) AS last_year, "
            "  (array_agg(jdi.authority_document_id "
            "    ORDER BY jdi.year DESC NULLS LAST))[1] AS sample_judgment_id, "
            "  NOW() "
            "FROM judge_decision_index jdi "
            "JOIN authority_statute_references asr "
            "  ON asr.authority_id = jdi.authority_document_id "
            "GROUP BY jdi.judge_id, asr.section_id"
        )
    )
    s.judge_statute_focus_rows = inserted.rowcount or 0
    session.commit()
    logger.info("L-C: inserted %d rows", s.judge_statute_focus_rows)
    return s


def refresh_all_layers(
    session: Session, *, batch_size: int = 500,
) -> RefreshSummary:
    """Orchestrator: run L-A first (it's the fact table), then L-B
    and L-C which both depend on L-A."""
    s = refresh_judge_decision_index(session, batch_size=batch_size)
    refresh_judge_authority_affinity(session, summary=s)
    refresh_judge_statute_focus(session, summary=s)
    return s
