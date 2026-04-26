"""Bench-strategy Phase 4 service (MOD-TS-018).

Surfaces L-A/L-B/L-C analysis layers as a matter-scoped read API:

  GET /api/matters/{matter_id}/bench-strategy

Returns top-N authorities the bench has cited, top-N statute sections
the bench engages with, total decisions covered (evidence_quality
bucket), and the no-legal-advice disclaimer.

Per the user's 2026-04-26 PRD edits, predictive surfaces (judge
tendencies, predicted_disposition) are authorized — those land in the
follow-up commit once outcome-classification (L-E) ships. This first
slice is the citation-grounded view (no prediction yet) + evidence_quality
chip so the UI can render the limitation note when bench history is thin.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_DISCLAIMER = (
    "Statistical analysis based on indexed decisions only. Not legal "
    "advice. Verify against primary sources before relying in any "
    "submission."
)


@dataclass
class BenchStrategyAuthority:
    authority_id: str
    title: str | None
    citation_count: int
    last_year: int | None
    sample_judgment_id: str | None


@dataclass
class BenchStrategyStatuteRef:
    statute_section_id: str
    statute_id: str
    section_number: str
    section_label: str | None
    citation_count: int
    last_year: int | None
    sample_judgment_id: str | None


@dataclass
class BenchStrategyResponse:
    matter_id: str
    bench_judge_ids: list[str]
    total_decisions_indexed: int
    evidence_quality: str  # "strong" | "partial" | "weak" | "insufficient"
    top_authorities: list[BenchStrategyAuthority] = field(default_factory=list)
    top_statute_sections: list[BenchStrategyStatuteRef] = field(default_factory=list)
    disclaimer: str = _DISCLAIMER


def _evidence_bucket(total: int) -> str:
    """Per PRD §5 evidence_quality enum."""
    if total >= 20:
        return "strong"
    if total >= 5:
        return "partial"
    if total >= 1:
        return "weak"
    return "insufficient"


def _resolve_bench_judge_ids(
    session: Session, matter_id: str, company_id: str,
) -> list[str]:
    """Resolve the matter's most-recent listing → bench judges.

    Reads the same matter_cause_list_entries.judges_json that
    backfill_hc_judges_from_corpus + bench_resolver use, then maps
    to judge_ids via judge_aliases.
    """
    # Tenant-scoped: matter_id must belong to the company.
    rows = session.execute(
        text(
            "SELECT mce.judges_json, m.court_id "
            "FROM matter_cause_list_entries mce "
            "JOIN matters m ON m.id = mce.matter_id "
            "WHERE mce.matter_id = :mid "
            "AND m.company_id = :cid "
            "AND mce.judges_json IS NOT NULL "
            "ORDER BY mce.listing_date DESC NULLS LAST, mce.created_at DESC "
            "LIMIT 1"
        ),
        {"mid": matter_id, "cid": company_id},
    ).fetchone()
    if not rows:
        return []
    judges_raw, court_id = rows[0], rows[1]
    if not court_id:
        return []
    import json
    try:
        names = (
            judges_raw if isinstance(judges_raw, list)
            else json.loads(judges_raw)
        )
    except Exception:
        return []
    if not isinstance(names, list):
        return []
    from caseops_api.services.judge_aliases import match_candidates
    judge_ids: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str):
            continue
        matches = match_candidates(session, raw_text=name, court_id=court_id)
        if not matches:
            continue
        jid = matches[0].judge_id
        if jid not in seen:
            seen.add(jid)
            judge_ids.append(jid)
    return judge_ids


def build_bench_strategy(
    session: Session,
    *,
    matter_id: str,
    company_id: str,
    bench_judge_ids: list[str] | None = None,
    authority_limit: int = 10,
    statute_limit: int = 10,
) -> BenchStrategyResponse:
    """Build the bench-strategy payload for one matter.

    If ``bench_judge_ids`` is None, the bench is auto-resolved from
    the matter's next/most-recent listing (tenant-scoped).
    """
    if bench_judge_ids is None:
        bench_judge_ids = _resolve_bench_judge_ids(session, matter_id, company_id)

    if not bench_judge_ids:
        return BenchStrategyResponse(
            matter_id=matter_id,
            bench_judge_ids=[],
            total_decisions_indexed=0,
            evidence_quality="insufficient",
            top_authorities=[],
            top_statute_sections=[],
        )

    total = int(session.scalar(
        text(
            "SELECT COUNT(*) FROM judge_decision_index "
            "WHERE judge_id = ANY(:ids)"
        ),
        {"ids": bench_judge_ids},
    ) or 0)

    # Top authorities — sum citation_count across all bench judges.
    auth_rows = session.execute(
        text(
            "SELECT jaa.cited_authority_document_id, "
            "  ad.title, "
            "  SUM(jaa.citation_count) AS total_citations, "
            "  MAX(jaa.last_year) AS last_year, "
            "  (array_agg(jaa.sample_judgment_id "
            "    ORDER BY jaa.citation_count DESC NULLS LAST))[1] "
            "    AS sample_judgment_id "
            "FROM judge_authority_affinity jaa "
            "LEFT JOIN authority_documents ad "
            "  ON ad.id = jaa.cited_authority_document_id "
            "WHERE jaa.judge_id = ANY(:ids) "
            "GROUP BY jaa.cited_authority_document_id, ad.title "
            "ORDER BY total_citations DESC LIMIT :lim"
        ),
        {"ids": bench_judge_ids, "lim": authority_limit},
    ).fetchall()

    # Top statute sections.
    stat_rows = session.execute(
        text(
            "SELECT jsf.statute_section_id, ss.statute_id, "
            "  ss.section_number, ss.section_label, "
            "  SUM(jsf.citation_count) AS total_citations, "
            "  MAX(jsf.last_year) AS last_year, "
            "  (array_agg(jsf.sample_judgment_id "
            "    ORDER BY jsf.citation_count DESC NULLS LAST))[1] "
            "    AS sample_judgment_id "
            "FROM judge_statute_focus jsf "
            "JOIN statute_sections ss ON ss.id = jsf.statute_section_id "
            "WHERE jsf.judge_id = ANY(:ids) "
            "GROUP BY jsf.statute_section_id, ss.statute_id, "
            "  ss.section_number, ss.section_label "
            "ORDER BY total_citations DESC LIMIT :lim"
        ),
        {"ids": bench_judge_ids, "lim": statute_limit},
    ).fetchall()

    return BenchStrategyResponse(
        matter_id=matter_id,
        bench_judge_ids=bench_judge_ids,
        total_decisions_indexed=total,
        evidence_quality=_evidence_bucket(total),
        top_authorities=[
            BenchStrategyAuthority(
                authority_id=r[0],
                title=r[1],
                citation_count=int(r[2] or 0),
                last_year=int(r[3]) if r[3] is not None else None,
                sample_judgment_id=r[4],
            )
            for r in auth_rows
        ],
        top_statute_sections=[
            BenchStrategyStatuteRef(
                statute_section_id=r[0],
                statute_id=r[1],
                section_number=r[2],
                section_label=r[3],
                citation_count=int(r[4] or 0),
                last_year=int(r[5]) if r[5] is not None else None,
                sample_judgment_id=r[6],
            )
            for r in stat_rows
        ],
    )
