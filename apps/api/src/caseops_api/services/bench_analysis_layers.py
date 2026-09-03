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

All three are pure SQL — zero hosted LLM spend. Suitable for nightly
cron.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument
from caseops_api.services.judge_mapping import rebuild_authority_mapping

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
    """L-A: deterministically rebuild source-backed judge mappings.

    Uses the canonical Court/Judge/Alias owner, records collisions and
    unresolved evidence for curators, and never chooses the first ambiguous
    match. Keyset pagination bounds memory and avoids OFFSET degradation.
    """
    summary = RefreshSummary()
    cursor: str | None = None
    while True:
        query = (
            select(AuthorityDocument.id)
            .where(AuthorityDocument.judges_json.is_not(None))
            .order_by(AuthorityDocument.id)
            .limit(batch_size)
        )
        if cursor is not None:
            query = query.where(AuthorityDocument.id > cursor)
        authority_ids = list(session.scalars(query))
        if not authority_ids:
            break
        for authority_id in authority_ids:
            result = rebuild_authority_mapping(
                session, authority_document_id=authority_id, commit=False
            )
            summary.judge_decision_index_rows += (
                result.mapped + result.collisions + result.unresolved
            )
            summary.judge_decision_index_inserted += result.inserted
            summary.skipped_unmatched_judges += result.collisions + result.unresolved
        session.commit()
        cursor = authority_ids[-1]
        logger.info(
            "L-A: processed through %s (mapped %d, review-required %d)",
            cursor,
            summary.judge_decision_index_inserted,
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
            "  AND jdi.is_analytics_eligible IS TRUE "
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
            "WHERE jdi.is_analytics_eligible IS TRUE "
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
