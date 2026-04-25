"""BAAD-001 slice 2 (Sprint P5, 2026-04-25).

Builds an evidence-cited bench-history context for a matter, suitable
for injection into appeal-draft generation. Pure-read service — no
side effects on the DB.

What this answers:

- Which judge / bench will likely hear the appeal?
- Which indexed prior judgments from that judge or bench touch the same
  practice area / forum?
- What recurring legal tests has that judge / bench emphasised in those
  judgments? (evidence phrasing only)
- Which authorities does that judge / bench cite frequently?
- Where is the evidence thin, so the drafter can fall back?

What this DOES NOT do — bench-aware drafting hard rules:

- No favorability scoring, win/loss prediction, reputation claims, or
  uncited "judge tendency" language anywhere.
- Every observation is grounded in indexed authorities the caller can
  cite back. When there are fewer than 3 supporting authorities for a
  pattern, the pattern is suppressed (returned in `unsupported_gaps`).
- When `context_quality == "low"` or `"none"`, the calling drafting
  service must fall back to plain appeal drafting with a visible
  limitation note.

Design constraints:

- Tenant-scoped: caller's `SessionContext` resolves the matter; foreign
  matters return 404.
- Structured-first: `AuthorityDocument.judges_json` matches when
  Layer-2 has run on the document; `bench_name` ILIKE is the fallback
  with explicit confidence labelling.
- Same query path the existing `services/courts.py` judge profile uses
  so retrieval semantics stay consistent across surfaces.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    Court,
    Judge,
    Matter,
)
from caseops_api.services.bench_matcher import (
    BenchSuggestion,
    suggest_bench,
)
from caseops_api.services.identity import SessionContext


# Honorific stripper duplicated from `api/routes/courts.py` so this
# service stays route-independent. Both must update together if the
# pattern grows. ((Same regex; tested upstream.))
_HONORIFIC_RE = re.compile(
    r"^(?:Hon'?ble\s+)?(?:Mr\.|Ms\.|Mrs\.|Dr\.|The\s+)?\s*"
    r"(?:Chief\s+Justice|Justice|J\.\s+|J)\s*",
    flags=re.IGNORECASE,
)
_J_SUFFIX_RE = re.compile(r"[,\s]+J\.?$", flags=re.IGNORECASE)


def _strip_honorific(name: str) -> str:
    if not name:
        return ""
    out = _HONORIFIC_RE.sub("", name).strip()
    out = _J_SUFFIX_RE.sub("", out).strip()
    return out


# Minimum supporting authorities before we'll surface a pattern as a
# legitimate observation rather than as an unsupported_gap. Set
# conservatively: 3 keeps a coincidence from being framed as a trend.
_MIN_AUTHORITIES_FOR_PATTERN = 3
# Hard cap on context payload — keeps the context block small enough
# that the appeal prompt isn't overwhelmed and so the response stays
# easy to render in the UI.
_DEFAULT_AUTHORITY_LIMIT = 12


@dataclass(frozen=True)
class CitableAuthority:
    id: str
    title: str
    decision_date: str | None
    case_reference: str | None
    neutral_citation: str | None
    bench_name: str | None
    forum_level: str | None
    structured_match: bool


@dataclass(frozen=True)
class JudgeCandidate:
    judge_id: str
    full_name: str
    structured_authority_count: int
    fallback_authority_count: int


@dataclass(frozen=True)
class PracticeAreaPattern:
    """Aggregate observation about how often this judge/bench has
    decided cases in a practice area. Always cites the supporting
    authorities so the calling prompt can quote them — no opinionated
    text in the field.
    """

    area: str
    authority_count: int
    sample_authority_ids: tuple[str, ...]


@dataclass(frozen=True)
class RecurringTest:
    """A legal test or doctrine the judge/bench has cited repeatedly.
    `phrase` is the surfaced doctrine name; the calling prompt is
    REQUIRED to attribute it to the supporting authorities and not
    assert preference.
    """

    phrase: str
    occurrences: int
    sample_authority_ids: tuple[str, ...]


@dataclass(frozen=True)
class CitedAuthority:
    citation: str
    occurrences: int


@dataclass(frozen=True)
class BenchStrategyContext:
    matter_id: str
    court_name: str | None
    bench_match: BenchSuggestion | None
    judge_candidates: list[JudgeCandidate] = field(default_factory=list)
    structured_match_coverage_percent: int = 0
    context_quality: str = "none"  # "high" | "medium" | "low" | "none"
    similar_authorities: list[CitableAuthority] = field(default_factory=list)
    practice_area_patterns: list[PracticeAreaPattern] = field(default_factory=list)
    recurring_tests: list[RecurringTest] = field(default_factory=list)
    authorities_frequently_cited: list[CitedAuthority] = field(default_factory=list)
    drafting_cautions: list[str] = field(default_factory=list)
    unsupported_gaps: list[str] = field(default_factory=list)


# Recurring legal-test phrases we look for in each authority's
# title + summary. Conservative on purpose — better to surface a known
# doctrine 5x than to mis-fire on novel phrasing. Each is a tuple of
# (display_phrase, regex). Add cautiously; every entry can become a
# falsely-claimed "trend" if the regex is too loose.
_DOCTRINE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("triple test for bail", re.compile(r"\btriple\s+test\b", re.IGNORECASE)),
    ("Sibbia / Sushila Aggarwal anticipatory-bail line", re.compile(
        r"\b(?:gurbaksh\s+singh\s+sibbia|sushila\s+aggarwal)\b", re.IGNORECASE
    )),
    ("Arnesh Kumar / s.41A safeguards", re.compile(
        r"\barnesh\s+kumar\b|\bs\.?\s*41A\b", re.IGNORECASE
    )),
    ("Order XLI Rule 5 stay-pending-appeal test", re.compile(
        r"\border\s+xli\s+rule\s+5\b|\border\s+41\s+rule\s+5\b", re.IGNORECASE
    )),
    ("Order XLI Rule 27 additional evidence", re.compile(
        r"\border\s+xli\s+rule\s+27\b|\border\s+41\s+rule\s+27\b", re.IGNORECASE
    )),
    ("Wednesbury / proportionality review", re.compile(
        r"\bwednesbury\b|\bproportionality\b", re.IGNORECASE
    )),
    ("locus standi", re.compile(r"\blocus\s+standi\b", re.IGNORECASE)),
    ("balance of convenience", re.compile(
        r"\bbalance\s+of\s+convenience\b", re.IGNORECASE
    )),
    ("prima facie case", re.compile(r"\bprima\s+facie\s+case\b", re.IGNORECASE)),
    ("limitation / condonation of delay", re.compile(
        r"\bcondonation\s+of\s+delay\b|\bsec(?:tion)?\s*5\s+limitation\b",
        re.IGNORECASE,
    )),
    ("error apparent on the face of the record", re.compile(
        r"\berror\s+apparent\s+on\s+the\s+face\b", re.IGNORECASE
    )),
]


def build_bench_strategy_context(
    *,
    session: Session,
    context: SessionContext,
    matter_id: str,
    judge_limit: int = 5,
    authority_limit: int = _DEFAULT_AUTHORITY_LIMIT,
) -> BenchStrategyContext:
    """Build the BenchStrategyContext for the calling tenant's matter.

    Tenancy: the matter must belong to `context.company.id` — foreign
    matters raise 404 (same shape as other matter endpoints).
    Pure-read; no DB writes.
    """
    matter = session.scalar(
        select(Matter)
        .where(Matter.id == matter_id)
        .where(Matter.company_id == context.company.id)
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found."
        )

    # Step 1: pick the judges we have something to say about.
    judge_candidates, court_name = _resolve_judge_candidates(
        session=session, matter=matter, judge_limit=judge_limit,
    )
    bench_match: BenchSuggestion | None = None
    if not matter.judge_name:
        # No specific judge on the matter — fall back to the bench
        # matcher. Catches the common case where the appeal is filed
        # but listing hasn't happened yet.
        bench_match = suggest_bench(
            session=session, matter=matter, judge_limit=judge_limit,
        )

    # Step 2: gather citable authorities across the candidates.
    similar_authorities, structured_count, total_count = _collect_authorities(
        session=session,
        candidates=judge_candidates,
        limit=authority_limit,
    )
    coverage_pct = (
        int(round(100 * structured_count / total_count))
        if total_count else 0
    )

    # Step 3: derive observation patterns. Suppress anything below
    # _MIN_AUTHORITIES_FOR_PATTERN as unsupported.
    practice_patterns, area_gaps = _derive_practice_area_patterns(
        similar_authorities
    )
    recurring_tests, doctrine_gaps = _derive_recurring_tests(similar_authorities)
    authorities_cited = _derive_frequently_cited(similar_authorities)

    # Step 4: assemble cautions + gaps for the drafting prompt.
    drafting_cautions = _drafting_cautions(
        coverage_percent=coverage_pct,
        authority_count=len(similar_authorities),
    )
    unsupported_gaps = list(area_gaps) + list(doctrine_gaps)
    if not similar_authorities:
        unsupported_gaps.append(
            "No indexed prior judgments matched the candidate judge(s) for "
            "this matter — the appeal draft must NOT cite bench-specific "
            "tendencies and should fall back to general appellate framing."
        )

    quality = _score_quality(
        coverage_percent=coverage_pct,
        authority_count=len(similar_authorities),
        candidate_count=len(judge_candidates),
    )

    return BenchStrategyContext(
        matter_id=matter.id,
        court_name=court_name,
        bench_match=bench_match,
        judge_candidates=judge_candidates,
        structured_match_coverage_percent=coverage_pct,
        context_quality=quality,
        similar_authorities=similar_authorities,
        practice_area_patterns=practice_patterns,
        recurring_tests=recurring_tests,
        authorities_frequently_cited=authorities_cited,
        drafting_cautions=drafting_cautions,
        unsupported_gaps=unsupported_gaps,
    )


# ---------- internal helpers ----------


def _resolve_judge_candidates(
    *, session: Session, matter: Matter, judge_limit: int,
) -> tuple[list[JudgeCandidate], str | None]:
    """Returns ([candidates], court_name). Order: exact judge_name match
    first; otherwise sitting judges of the resolved court (capped)."""
    court_name = matter.court_name
    candidates: list[JudgeCandidate] = []

    # Exact judge_name on the matter — best signal.
    if matter.judge_name:
        stripped = _strip_honorific(matter.judge_name)
        json_pattern = f'%"{stripped}%'
        bench_pattern = f"%{stripped}%"
        struct_count = int(session.scalar(
            select(_count_distinct_doc_id())
            .where(AuthorityDocument.judges_json.ilike(json_pattern))
        ) or 0)
        fallback_count = int(session.scalar(
            select(_count_distinct_doc_id())
            .where(AuthorityDocument.bench_name.ilike(bench_pattern))
            .where(~AuthorityDocument.judges_json.ilike(json_pattern))
        ) or 0)
        # Try to resolve the Judge row by full_name match for downstream
        # callers that want a deep link. Doesn't affect the count.
        judge_row = session.scalar(
            select(Judge).where(Judge.full_name == matter.judge_name)
        )
        candidates.append(JudgeCandidate(
            judge_id=judge_row.id if judge_row else "",
            full_name=matter.judge_name,
            structured_authority_count=struct_count,
            fallback_authority_count=fallback_count,
        ))
        return candidates, court_name

    # No specific judge — fall back to sitting judges of the matter's
    # court (when the FK resolves). Capped by judge_limit so the
    # context payload doesn't bloat.
    if matter.court_id:
        sitting = list(session.scalars(
            select(Judge)
            .where(Judge.court_id == matter.court_id)
            .where(Judge.is_active.is_(True))
            .order_by(Judge.full_name)
            .limit(judge_limit)
        ))
        for j in sitting:
            stripped = _strip_honorific(j.full_name)
            json_pattern = f'%"{stripped}%'
            bench_pattern = f"%{stripped}%"
            struct_count = int(session.scalar(
                select(_count_distinct_doc_id())
                .where(AuthorityDocument.judges_json.ilike(json_pattern))
            ) or 0)
            fallback_count = int(session.scalar(
                select(_count_distinct_doc_id())
                .where(AuthorityDocument.bench_name.ilike(bench_pattern))
                .where(~AuthorityDocument.judges_json.ilike(json_pattern))
            ) or 0)
            candidates.append(JudgeCandidate(
                judge_id=j.id,
                full_name=j.full_name,
                structured_authority_count=struct_count,
                fallback_authority_count=fallback_count,
            ))
        court = session.scalar(select(Court).where(Court.id == matter.court_id))
        if court:
            court_name = court.name

    return candidates, court_name


def _count_distinct_doc_id():
    from sqlalchemy import func as _func

    return _func.count(AuthorityDocument.id.distinct())


def _collect_authorities(
    *,
    session: Session,
    candidates: list[JudgeCandidate],
    limit: int,
) -> tuple[list[CitableAuthority], int, int]:
    """Returns (citable_authorities, structured_count, total_count).

    Pulls authorities for ALL candidates, deduplicates by doc id, and
    keeps the most-recent `limit`. Each authority is tagged with
    structured_match=True when it came from `judges_json` (high
    confidence) vs False when only `bench_name` ILIKE matched.
    """
    if not candidates:
        return [], 0, 0

    structured_filters = []
    fallback_filters = []
    for c in candidates:
        stripped = _strip_honorific(c.full_name)
        if not stripped:
            continue
        structured_filters.append(
            AuthorityDocument.judges_json.ilike(f'%"{stripped}%')
        )
        fallback_filters.append(
            AuthorityDocument.bench_name.ilike(f"%{stripped}%")
        )
    if not structured_filters and not fallback_filters:
        return [], 0, 0

    combined = or_(*structured_filters, *fallback_filters)
    rows = list(session.execute(
        select(
            AuthorityDocument.id,
            AuthorityDocument.title,
            AuthorityDocument.decision_date,
            AuthorityDocument.case_reference,
            AuthorityDocument.neutral_citation,
            AuthorityDocument.bench_name,
            AuthorityDocument.forum_level,
            AuthorityDocument.judges_json,
        )
        .where(combined)
        .order_by(AuthorityDocument.decision_date.desc().nulls_last())
        .limit(limit * 2)  # over-fetch so the citable filter has room
    ).all())

    citable: list[CitableAuthority] = []
    structured_count = 0
    seen_ids: set[str] = set()
    for r in rows:
        if r.id in seen_ids:
            continue
        seen_ids.add(r.id)
        # Citable authority = has at least one of neutral_citation /
        # case_reference. Per the brief, prefer citable.
        if not (r.neutral_citation or r.case_reference):
            continue
        # Match-type tag: structured if any candidate's stripped name
        # appears in judges_json, fallback otherwise. Cheap check.
        is_structured = False
        if r.judges_json:
            for c in candidates:
                stripped = _strip_honorific(c.full_name)
                if stripped and stripped in r.judges_json:
                    is_structured = True
                    break
        if is_structured:
            structured_count += 1
        citable.append(CitableAuthority(
            id=r.id,
            title=r.title,
            decision_date=(
                r.decision_date.isoformat() if r.decision_date else None
            ),
            case_reference=r.case_reference,
            neutral_citation=r.neutral_citation,
            bench_name=r.bench_name,
            forum_level=r.forum_level,
            structured_match=is_structured,
        ))
        if len(citable) >= limit:
            break

    total_count = len(citable)
    return citable, structured_count, total_count


def _derive_practice_area_patterns(
    authorities: Iterable[CitableAuthority],
) -> tuple[list[PracticeAreaPattern], list[str]]:
    """Lightweight bucketing on the title alone — the catalog routes
    use the chunks-table path for finer granularity, but at this
    surface (drafting context) the title is enough and avoids loading
    chunk text. Returns (patterns_with_>=3, gaps_for_<3)."""
    # Re-use the same labels the routes file uses, but classify on
    # title to keep this hermetic + cheap.
    from caseops_api.services.bench_matcher import _PRACTICE_AREAS

    bucket_to_ids: dict[str, list[str]] = {}
    for a in authorities:
        text = a.title or ""
        for area, rx in _PRACTICE_AREAS:
            if rx.search(text):
                bucket_to_ids.setdefault(area, []).append(a.id)
                break

    patterns: list[PracticeAreaPattern] = []
    gaps: list[str] = []
    for area, ids in sorted(
        bucket_to_ids.items(), key=lambda kv: len(kv[1]), reverse=True
    ):
        if len(ids) >= _MIN_AUTHORITIES_FOR_PATTERN:
            patterns.append(PracticeAreaPattern(
                area=area,
                authority_count=len(ids),
                sample_authority_ids=tuple(ids[:5]),
            ))
        else:
            gaps.append(
                f"Only {len(ids)} indexed decisions match practice area "
                f"'{area}' for these candidates — too thin to assert as a "
                "pattern. Treat as anecdotal."
            )
    return patterns, gaps


def _derive_recurring_tests(
    authorities: Iterable[CitableAuthority],
) -> tuple[list[RecurringTest], list[str]]:
    """Scan title + bench_name for known doctrine phrases. Same
    `>= 3 supporting` rule as practice areas."""
    bucket_to_ids: dict[str, list[str]] = {}
    for a in authorities:
        haystack = " ".join(p for p in [a.title, a.bench_name] if p)
        for phrase, rx in _DOCTRINE_PATTERNS:
            if rx.search(haystack):
                bucket_to_ids.setdefault(phrase, []).append(a.id)

    tests: list[RecurringTest] = []
    gaps: list[str] = []
    for phrase, ids in sorted(
        bucket_to_ids.items(), key=lambda kv: len(kv[1]), reverse=True
    ):
        if len(ids) >= _MIN_AUTHORITIES_FOR_PATTERN:
            tests.append(RecurringTest(
                phrase=phrase,
                occurrences=len(ids),
                sample_authority_ids=tuple(ids[:5]),
            ))
        else:
            gaps.append(
                f"Doctrine '{phrase}' appeared in {len(ids)} of the "
                "candidate's authorities — below the 3-authority floor; "
                "the draft should not frame this as a bench tendency."
            )
    return tests, gaps


def _derive_frequently_cited(
    authorities: Iterable[CitableAuthority],
) -> list[CitedAuthority]:
    """Cheap proxy: count how often each (neutral_citation OR
    case_reference) appears across the candidate's authorities. This
    surfaces self-citation clusters; deeper cross-citation analysis
    needs Layer-2's authority-graph table which we don't query here.
    """
    counter: Counter[str] = Counter()
    for a in authorities:
        cite = a.neutral_citation or a.case_reference
        if cite:
            counter[cite] += 1
    return [
        CitedAuthority(citation=c, occurrences=n)
        for c, n in counter.most_common(8)
        if n >= 2  # 1 = baseline; 2+ = repeat reliance
    ]


def _drafting_cautions(
    *, coverage_percent: int, authority_count: int
) -> list[str]:
    """Plain-language cautions the drafting prompt MUST surface to the
    lawyer-reviewer. Order: most-actionable first."""
    out: list[str] = []
    if authority_count == 0:
        out.append(
            "No bench-history evidence available — draft without "
            "bench-specific framing and add a visible limitation note "
            "in the grounds section."
        )
        return out
    if coverage_percent < 40:
        out.append(
            f"Only {coverage_percent}% of the bench-history matches come "
            "from structured judges_json — the rest are bench_name "
            "string matches and may include misattributions. Treat "
            "patterns as suggestive, not authoritative."
        )
    if authority_count < 5:
        out.append(
            f"Only {authority_count} citable indexed decisions match the "
            "candidate judge(s). Patterns are thin; do not generalise."
        )
    return out


def _score_quality(
    *,
    coverage_percent: int,
    authority_count: int,
    candidate_count: int,
) -> str:
    """Maps numeric signal to the four context_quality labels the
    drafting service reads."""
    if candidate_count == 0 or authority_count == 0:
        return "none"
    if coverage_percent >= 60 and authority_count >= 5:
        return "high"
    if authority_count >= 2:
        return "medium"
    return "low"


__all__ = [
    "BenchStrategyContext",
    "CitableAuthority",
    "CitedAuthority",
    "JudgeCandidate",
    "PracticeAreaPattern",
    "RecurringTest",
    "build_bench_strategy_context",
]
