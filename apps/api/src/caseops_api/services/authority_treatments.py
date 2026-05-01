"""Authority-treatment aggregation — PG-006 Phase 1B.

Reads from `authority_citations.treatment` (populated by Phase 1A's
heuristic classifier) and produces per-authority summaries used by:

- `GET /api/authorities/{id}/treatments` (research surface)
- `check_adverse_treatment` validator wired into the drafting service

The summary returns one row per treatment category with a count and
the strongest sample evidence_text. Adverse treatments (overruled /
reversed / doubted) are surfaced explicitly so the caller can:

- show a red "no longer good law" badge in research,
- emit a DraftFinding when the draft cites an authority with any
  adverse incoming citation,
- skip authorities with adverse treatment from automatic
  recommendations.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityCitationTreatment

# Adverse treatments — the "be careful before citing" set.
ADVERSE_TREATMENTS: frozenset[str] = frozenset({
    AuthorityCitationTreatment.OVERRULED.value,
    AuthorityCitationTreatment.REVERSED.value,
    AuthorityCitationTreatment.DOUBTED.value,
})


@dataclass(frozen=True)
class TreatmentSample:
    """One sample citing-case row for a treatment summary."""
    citing_authority_document_id: str
    citing_title: str | None
    citing_neutral_citation: str | None
    citation_text: str
    treatment: str
    confidence: float | None
    evidence_text: str | None


@dataclass(frozen=True)
class TreatmentBucket:
    """All citing cases that gave one authority a particular treatment."""
    treatment: str
    count: int
    samples: list[TreatmentSample] = field(default_factory=list)


@dataclass(frozen=True)
class AuthorityTreatmentSummary:
    """Per-authority good-law signal."""
    authority_document_id: str
    total_incoming: int
    adverse_count: int
    has_adverse_treatment: bool
    worst_treatment: str | None  # one of the eight enum values, or None
    buckets: list[TreatmentBucket]


# Adverse-priority order: overruled is the strongest "bad law" signal,
# then reversed (limited to the original holding), then doubted (a
# warning).
_ADVERSE_PRIORITY = [
    AuthorityCitationTreatment.OVERRULED.value,
    AuthorityCitationTreatment.REVERSED.value,
    AuthorityCitationTreatment.DOUBTED.value,
]


def summarize_treatments(
    session: Session,
    authority_document_id: str,
    *,
    samples_per_bucket: int = 3,
) -> AuthorityTreatmentSummary:
    """Aggregate incoming citations for one authority by treatment."""
    rows = session.execute(
        text(
            "SELECT ac.treatment, ac.citation_text, "
            "       ac.treatment_confidence, ac.treatment_evidence_text, "
            "       ad.id, ad.title, ad.neutral_citation "
            "FROM authority_citations ac "
            "LEFT JOIN authority_documents ad "
            "  ON ad.id = ac.source_authority_document_id "
            "WHERE ac.cited_authority_document_id = :id "
            "ORDER BY "
            "  CASE ac.treatment "
            "    WHEN 'overruled' THEN 0 "
            "    WHEN 'reversed' THEN 1 "
            "    WHEN 'doubted' THEN 2 "
            "    WHEN 'distinguished' THEN 3 "
            "    WHEN 'dissented' THEN 4 "
            "    WHEN 'considered' THEN 5 "
            "    WHEN 'followed' THEN 6 "
            "    ELSE 7 END, "
            "  ac.treatment_confidence DESC NULLS LAST, "
            "  ac.created_at ASC"
        ),
        {"id": authority_document_id},
    ).fetchall()

    buckets_by_treatment: dict[str, list[TreatmentSample]] = {}
    counts: dict[str, int] = {}
    for row in rows:
        treatment = row[0] or AuthorityCitationTreatment.NEUTRAL.value
        counts[treatment] = counts.get(treatment, 0) + 1
        bucket_samples = buckets_by_treatment.setdefault(treatment, [])
        if len(bucket_samples) < samples_per_bucket:
            bucket_samples.append(
                TreatmentSample(
                    citing_authority_document_id=row[4] or "",
                    citing_title=row[5],
                    citing_neutral_citation=row[6],
                    citation_text=row[1] or "",
                    treatment=treatment,
                    confidence=(
                        float(row[2]) if row[2] is not None else None
                    ),
                    evidence_text=row[3],
                )
            )

    buckets = [
        TreatmentBucket(
            treatment=t,
            count=counts[t],
            samples=buckets_by_treatment.get(t, []),
        )
        for t in counts
    ]

    adverse_count = sum(
        c for t, c in counts.items() if t in ADVERSE_TREATMENTS
    )
    worst: str | None = None
    for candidate in _ADVERSE_PRIORITY:
        if counts.get(candidate, 0) > 0:
            worst = candidate
            break

    return AuthorityTreatmentSummary(
        authority_document_id=authority_document_id,
        total_incoming=sum(counts.values()),
        adverse_count=adverse_count,
        has_adverse_treatment=adverse_count > 0,
        worst_treatment=worst,
        buckets=buckets,
    )


def compute_search_result_treatments(
    session: Session,
    authority_document_ids: list[str],
) -> dict[str, tuple[str | None, int]]:
    """Bulk lookup for the search-result badge.

    Returns ``{authority_id: (worst_treatment_or_None, adverse_count)}``
    for every authority in the page. One DB roundtrip regardless of
    page size, so /api/authorities/search stays fast.
    """
    if not authority_document_ids:
        return {}
    stmt = text(
        "SELECT cited_authority_document_id, treatment, COUNT(*) "
        "FROM authority_citations "
        "WHERE cited_authority_document_id IN :ids "
        "  AND treatment IN ('overruled', 'reversed', 'doubted') "
        "GROUP BY cited_authority_document_id, treatment"
    ).bindparams(bindparam("ids", expanding=True))
    rows = session.execute(
        stmt, {"ids": authority_document_ids},
    ).fetchall()

    counts_by_id: dict[str, dict[str, int]] = {}
    for row in rows:
        aid = row[0]
        treat = row[1]
        cnt = int(row[2])
        counts_by_id.setdefault(aid, {})[treat] = cnt

    out: dict[str, tuple[str | None, int]] = {}
    for aid, counts in counts_by_id.items():
        adverse_count = sum(counts.values())
        worst: str | None = None
        for cand in _ADVERSE_PRIORITY:
            if counts.get(cand, 0) > 0:
                worst = cand
                break
        out[aid] = (worst, adverse_count)
    return out


def find_authorities_with_adverse_treatment(
    session: Session,
    citation_strings: list[str],
) -> dict[str, AuthorityTreatmentSummary]:
    """Resolve each citation string to an authority and return a
    summary for the authorities with adverse incoming treatments.

    Citation strings are matched against ``authority_documents.neutral_citation``
    and ``authority_documents.case_reference`` (case-insensitive,
    whitespace-tolerant). Authorities not present in the corpus are
    silently skipped — they cannot have a treatment record.
    """
    if not citation_strings:
        return {}
    normalised = [s.strip() for s in citation_strings if s and s.strip()]
    if not normalised:
        return {}

    rows = session.execute(
        text(
            "SELECT id, neutral_citation, case_reference "
            "FROM authority_documents "
            "WHERE neutral_citation IS NOT NULL "
            "   OR case_reference IS NOT NULL"
        ),
    ).fetchall()
    # Build a (lowercased citation -> authority_id) map and resolve.
    by_text: dict[str, str] = {}
    for row in rows:
        for col in (row[1], row[2]):
            if col:
                by_text[col.strip().lower()] = row[0]

    results: dict[str, AuthorityTreatmentSummary] = {}
    seen: set[str] = set()
    for cit in normalised:
        match = by_text.get(cit.lower())
        if not match or match in seen:
            continue
        seen.add(match)
        summary = summarize_treatments(session, match)
        if summary.has_adverse_treatment:
            results[match] = summary
    return results


__all__ = [
    "ADVERSE_TREATMENTS",
    "AuthorityTreatmentSummary",
    "TreatmentBucket",
    "TreatmentSample",
    "compute_search_result_treatments",
    "find_authorities_with_adverse_treatment",
    "summarize_treatments",
]
