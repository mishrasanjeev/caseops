"""Sprint P3 — rule-based case-to-court-and-bench matcher.

Given a Matter, suggest:

1. the likely court (resolving the freeform ``court_name`` to a master
   ``courts.id`` when possible),
2. the likely bench size (single / division / three-judge / constitution),
3. the most relevant sitting judges at that court, optionally reordered
   by whose past judgments overlap with the matter's practice area.

This is *not* favorability scoring — it tells a lawyer what composition
to expect on the filing, not who to prefer. The judge re-rank uses the
Layer-2-derived practice_area histogram from ``courts.py``, so a matter
tagged "Bail / Custody" will surface judges with a measurable share of
bail authorities first.

Design notes:

- Rules come from §7.1 of the PRD (forum level + practice area) plus
  standard Indian court composition conventions (SC Art. 145(3) for
  constitution benches, HC single-judge for fresh writs, etc).
- We deliberately avoid predicting *which specific judge* will list the
  matter — the registrar decides that. We surface the active roster.
- Confidence falls out of the rules: high when court resolves via FK +
  description contains a triggering phrase; medium when practice area
  alone drives it; low when we're defaulting.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    Court,
    Judge,
    Matter,
)
from caseops_api.services.identity import SessionContext

# Bench-size values. Kept as string literals (not an enum) because they
# ship straight through the API to the web, and clients already read
# string codes for practice_area and forum_level.
BENCH_SIZE_SINGLE = "single_judge"
BENCH_SIZE_DIVISION = "division_bench"
BENCH_SIZE_THREE = "three_judge_bench"
BENCH_SIZE_CONSTITUTION = "constitution_bench"

_CONFIDENCE_HIGH = "high"
_CONFIDENCE_MEDIUM = "medium"
_CONFIDENCE_LOW = "low"

# Practice-area mapping, mirrored from courts.py ``_PRACTICE_AREAS``.
# Kept as a local copy so the matcher can classify a matter's
# description without importing a route module (services should not
# depend on routes). When the central list grows, update both.
_PRACTICE_AREAS: list[tuple[str, re.Pattern[str]]] = [
    ("Bail / Custody", re.compile(
        r"\b(?:bail|438|439|437|482|483|bnss\s+sec(?:tion)?\s+(?:43[789]|48[23])|"
        r"crpc\s+sec(?:tion)?\s+(?:43[789]|48[23]))\b",
        re.IGNORECASE,
    )),
    ("Criminal (other)", re.compile(
        r"\b(?:ipc|bns\b|indian\s+penal\s+code|bharatiya\s+nyaya|"
        r"pocso|ndps|pmla|uapa|mcoca)\b",
        re.IGNORECASE,
    )),
    ("Civil / Contract", re.compile(
        r"\b(?:specific\s+relief|indian\s+contract\s+act|transfer\s+of\s+property|"
        r"cpc|civil\s+procedure)\b",
        re.IGNORECASE,
    )),
    ("Constitutional", re.compile(
        r"\b(?:art(?:icle)?\s*(?:14|19|21|32|226|227)|constitution\s+of\s+india)\b",
        re.IGNORECASE,
    )),
    ("Commercial / Arbitration", re.compile(
        r"\b(?:arbitration|commercial\s+courts|companies\s+act|ibc|"
        r"insolvency\s+and\s+bankruptcy)\b",
        re.IGNORECASE,
    )),
    ("Family / Matrimonial", re.compile(
        r"\b(?:hindu\s+marriage|special\s+marriage|domestic\s+violence|"
        r"guardian|cpc\s+sec(?:tion)?\s+125|498a|498\-?a)\b",
        re.IGNORECASE,
    )),
    ("Tax / Revenue", re.compile(
        r"\b(?:income\s+tax|gst|customs|excise|service\s+tax)\b",
        re.IGNORECASE,
    )),
    ("Service / Employment", re.compile(
        r"\b(?:service\s+rules|industrial\s+disputes|id\s+act|"
        r"cat|central\s+administrative\s+tribunal)\b",
        re.IGNORECASE,
    )),
    ("Writ / PIL", re.compile(
        r"\b(?:writ\s+petition|public\s+interest\s+litigation|pil)\b",
        re.IGNORECASE,
    )),
    ("Property / Land", re.compile(
        r"\b(?:land\s+acquisition|ceiling\s+act|registration\s+act|"
        r"benami|evacuee\s+property)\b",
        re.IGNORECASE,
    )),
]

# Phrases that signal a Constitution Bench reference (5-judge under Art.
# 145(3)). Kept deliberately narrow to avoid false positives: every
# Art. 226 petition mentions "Constitution of India" in the header.
_CONSTITUTION_BENCH_RX = re.compile(
    r"(?:\bconstitution\s+bench\b|\bsubstantial\s+question\s+of\s+law\s+"
    r"as\s+to\s+the\s+interpretation\b|\barticle\s+145\s*\(\s*3\s*\))",
    re.IGNORECASE,
)

# Phrases that signal a larger (3-judge) reference — conflicting
# precedents, reference to a larger bench, doctrinal re-examination.
_THREE_JUDGE_RX = re.compile(
    r"\b(?:three[\s-]judge\s+bench|larger\s+bench|reference\s+to\s+a\s+"
    r"larger\s+bench|overrule\s+\w+(\s+\w+)?\s+v\.?\s)\b",
    re.IGNORECASE,
)

# High-court DB triggers — matters that, by convention, are listed before
# a Division Bench on first hearing rather than a single judge.
_HC_DIVISION_PRACTICE_AREAS = frozenset({
    "Tax / Revenue",
    "Constitutional",
    "Writ / PIL",
    "Service / Employment",
})
_HC_DIVISION_RX = re.compile(
    r"\b(?:division\s+bench|letters\s+patent\s+appeal|lpa|"
    r"writ\s+appeal|tax\s+appeal|criminal\s+appeal|contempt)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class JudgeStub:
    id: str
    full_name: str
    honorific: str | None
    current_position: str | None
    # How many of this judge's indexed authorities match the matter's
    # practice area. Zero when we have no Layer-2 coverage for them yet.
    practice_area_authority_count: int


@dataclass(frozen=True)
class BenchSuggestion:
    court_id: str | None
    court_name: str | None
    court_short_name: str | None
    forum_level: str | None
    bench_size: str
    bench_size_rationale: str
    practice_area_inferred: str | None
    suggested_judges: list[JudgeStub]
    confidence: str
    reasoning: list[str]


def suggest_bench_for_matter_id(
    *,
    session: Session,
    context: SessionContext,
    matter_id: str,
    judge_limit: int = 5,
) -> BenchSuggestion:
    """Tenancy-safe public entry point for the API layer.

    Resolves the matter under the caller's company and rejects anything
    outside the tenant scope. Keeps the route handler trivial.
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
    return suggest_bench(session=session, matter=matter, judge_limit=judge_limit)


def suggest_bench(
    *, session: Session, matter: Matter, judge_limit: int = 5,
) -> BenchSuggestion:
    """Suggest a bench composition for ``matter``.

    Pure function over ``matter`` and the current DB state. No writes,
    no side effects. Callers (the route layer) enforce the tenancy
    check on the Matter lookup before calling this.
    """
    reasoning: list[str] = []
    court = _resolve_court(matter=matter, session=session, reasoning=reasoning)

    practice_area_inferred = _infer_practice_area(matter, reasoning)

    bench_size, bench_rationale = _infer_bench_size(
        matter=matter,
        court=court,
        practice_area=practice_area_inferred,
        reasoning=reasoning,
    )

    suggested_judges: list[JudgeStub] = []
    if court is not None:
        suggested_judges = _rank_judges(
            session=session,
            court=court,
            practice_area=practice_area_inferred,
            limit=judge_limit,
        )
        if suggested_judges:
            reasoning.append(
                f"{len(suggested_judges)} sitting judges returned for "
                f"{court.short_name or court.name}."
            )

    confidence = _score_confidence(
        court=court,
        bench_size_rationale=bench_rationale,
        suggested_judges=suggested_judges,
    )

    return BenchSuggestion(
        court_id=court.id if court is not None else None,
        court_name=court.name if court is not None else matter.court_name,
        court_short_name=court.short_name if court is not None else None,
        forum_level=court.forum_level if court is not None else matter.forum_level,
        bench_size=bench_size,
        bench_size_rationale=bench_rationale,
        practice_area_inferred=practice_area_inferred,
        suggested_judges=suggested_judges,
        confidence=confidence,
        reasoning=reasoning,
    )


def _resolve_court(
    *, matter: Matter, session: Session, reasoning: list[str],
) -> Court | None:
    # Fast path — FK populated.
    if matter.court_id:
        court = session.scalar(select(Court).where(Court.id == matter.court_id))
        if court is not None:
            reasoning.append(
                f"Court resolved via matter.court_id → {court.short_name or court.name}."
            )
            return court

    # Freeform match. ILIKE on both name and short_name so "Delhi HC",
    # "Delhi High Court" and "High Court of Delhi" all land.
    if matter.court_name:
        needle = f"%{matter.court_name.strip()}%"
        court = session.scalar(
            select(Court)
            .where(Court.is_active.is_(True))
            .where(or_(Court.name.ilike(needle), Court.short_name.ilike(needle)))
            .order_by(func.length(Court.name))
        )
        if court is not None:
            reasoning.append(
                f"Court resolved via fuzzy match on '{matter.court_name}' "
                f"→ {court.short_name or court.name}."
            )
            return court

    # Forum-level fallback for matters with no court hint at all. A
    # useful enough answer to show bench-size reasoning; judge
    # suggestions will be empty since we don't know the bench.
    if matter.forum_level:
        court = session.scalar(
            select(Court)
            .where(Court.is_active.is_(True))
            .where(Court.forum_level == matter.forum_level)
            .order_by(Court.name)
        )
        if court is not None:
            reasoning.append(
                f"No court specified — defaulting to first active "
                f"{matter.forum_level} court for bench-size inference; "
                f"judge list will not be court-specific."
            )
            # Return None — we don't want to suggest judges for a court
            # the user never picked. But let the caller know.
            return None

    reasoning.append("No court could be resolved from the matter record.")
    return None


def _infer_practice_area(matter: Matter, reasoning: list[str]) -> str | None:
    # Explicit practice_area on the matter wins — human-entered truth.
    if matter.practice_area:
        reasoning.append(f"Practice area from matter record: '{matter.practice_area}'.")
        return matter.practice_area

    # Otherwise classify the description against _PRACTICE_AREAS.
    text = matter.description or ""
    if not text:
        return None
    for area, rx in _PRACTICE_AREAS:
        if rx.search(text):
            reasoning.append(
                f"Practice area inferred from description: '{area}'."
            )
            return area
    return None


def _infer_bench_size(
    *,
    matter: Matter,
    court: Court | None,
    practice_area: str | None,
    reasoning: list[str],
) -> tuple[str, str]:
    forum_level = (court.forum_level if court is not None else matter.forum_level) or ""
    description = (matter.description or "") + " " + (matter.title or "")

    # Supreme Court — three size tiers.
    if forum_level == "supreme_court":
        if _CONSTITUTION_BENCH_RX.search(description) or _matches_constitutional(practice_area):
            rationale = (
                "Supreme Court + substantial question as to the interpretation "
                "of the Constitution → Constitution Bench (Art. 145(3))."
            )
            reasoning.append(rationale)
            return BENCH_SIZE_CONSTITUTION, rationale
        if _THREE_JUDGE_RX.search(description):
            rationale = (
                "Supreme Court + reference to a larger bench / precedent "
                "re-examination → three-judge bench."
            )
            reasoning.append(rationale)
            return BENCH_SIZE_THREE, rationale
        rationale = "Supreme Court default → Division Bench (two judges)."
        reasoning.append(rationale)
        return BENCH_SIZE_DIVISION, rationale

    # High Courts — single vs division vs three-judge.
    if forum_level == "high_court":
        if _THREE_JUDGE_RX.search(description):
            rationale = (
                "High Court + explicit three-judge reference → three-judge bench."
            )
            reasoning.append(rationale)
            return BENCH_SIZE_THREE, rationale
        if _HC_DIVISION_RX.search(description) or _matches_hc_division(practice_area):
            rationale = (
                "High Court + appeal / tax / writ-appeal / Service / Constitutional "
                "matter → Division Bench."
            )
            reasoning.append(rationale)
            return BENCH_SIZE_DIVISION, rationale
        rationale = (
            "High Court default (fresh writ / bail / revision) → single judge."
        )
        reasoning.append(rationale)
        return BENCH_SIZE_SINGLE, rationale

    # District / Sessions / Tribunal — always a single bench.
    rationale = "Trial / appellate tier below High Court → single judge."
    reasoning.append(rationale)
    return BENCH_SIZE_SINGLE, rationale


def _matches_constitutional(practice_area: str | None) -> bool:
    return practice_area == "Constitutional"


def _matches_hc_division(practice_area: str | None) -> bool:
    return practice_area in _HC_DIVISION_PRACTICE_AREAS


def _rank_judges(
    *,
    session: Session,
    court: Court,
    practice_area: str | None,
    limit: int,
) -> list[JudgeStub]:
    judges = list(
        session.scalars(
            select(Judge)
            .where(Judge.court_id == court.id, Judge.is_active.is_(True))
            .order_by(Judge.full_name)
        )
    )
    if not judges:
        return []

    # If we don't have a practice area to score against, return the
    # roster in name order with zero counts.
    if not practice_area or practice_area not in {a for a, _ in _PRACTICE_AREAS}:
        return [_to_stub(j, authority_count=0) for j in judges[:limit]]

    # Otherwise count, per judge, how many authorities this court has
    # where the judge sat on the bench AND the sections-cited blob
    # matches the practice_area regex. One cheap pass over the chunks
    # table; no pre-computed cache needed.
    rx_pattern = _pattern_for_area(practice_area)
    if rx_pattern is None:
        return [_to_stub(j, authority_count=0) for j in judges[:limit]]

    rows = session.execute(
        select(
            AuthorityDocument.id,
            AuthorityDocument.judges_json,
            AuthorityDocument.bench_name,
            func.string_agg(
                AuthorityDocumentChunk.sections_cited_json, " "
            ).label("sections_blob"),
        )
        .join(
            AuthorityDocumentChunk,
            AuthorityDocumentChunk.authority_document_id == AuthorityDocument.id,
        )
        .where(AuthorityDocument.court_name == court.name)
        .where(AuthorityDocumentChunk.sections_cited_json.is_not(None))
        .group_by(AuthorityDocument.id)
    ).all()

    tally: Counter[str] = Counter()
    for _doc_id, judges_json, bench_name, blob in rows:
        if not blob or not rx_pattern.search(blob):
            continue
        hay = (judges_json or "") + " " + (bench_name or "")
        for judge in judges:
            last = judge.full_name.split()[-1] if judge.full_name else ""
            if last and last in hay:
                tally[judge.id] += 1

    ranked = sorted(
        judges,
        key=lambda j: (-tally.get(j.id, 0), j.full_name),
    )
    return [_to_stub(j, authority_count=tally.get(j.id, 0)) for j in ranked[:limit]]


def _pattern_for_area(area: str) -> re.Pattern[str] | None:
    for name, rx in _PRACTICE_AREAS:
        if name == area:
            return rx
    return None


def _to_stub(judge: Judge, *, authority_count: int) -> JudgeStub:
    return JudgeStub(
        id=judge.id,
        full_name=judge.full_name,
        honorific=judge.honorific,
        current_position=judge.current_position,
        practice_area_authority_count=authority_count,
    )


def _score_confidence(
    *,
    court: Court | None,
    bench_size_rationale: str,
    suggested_judges: list[JudgeStub],
) -> str:
    if court is None:
        return _CONFIDENCE_LOW
    if suggested_judges and (
        "Constitution Bench" in bench_size_rationale
        or "three-judge" in bench_size_rationale
        or "Division Bench" in bench_size_rationale
    ):
        return _CONFIDENCE_HIGH
    if suggested_judges:
        return _CONFIDENCE_MEDIUM
    return _CONFIDENCE_LOW
