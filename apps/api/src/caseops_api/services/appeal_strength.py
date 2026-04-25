"""MOD-TS-001-A (Sprint P, 2026-04-25) — Appeal Strength Analyzer.

Per-ground argument-completeness analysis on an appeal_memorandum
draft. Pure-read; no LLM call; deterministic scoring on existing
DB state.

What this answers:

- Which grounds in the draft are anchored by cited authorities?
- Which grounds rely only on uncited propositions?
- For each ground, what's the supporting authority's precedential
  weight (SC binds; HC peer; lower = persuasive only)?
- Does the bench-strategy-context show this judge / bench has
  decided similar issues, and which of the candidate's indexed
  authorities back this ground?
- What concrete edits would strengthen the weakest grounds?

What this DOES NOT do — bench-aware drafting hard rules:

- No win/lose probability
- No outcome prediction
- No "favourable" / "usually grants" / "tendency" language anywhere
- No reputation claims about the judge or bench

The analyzer's free-text output (suggestions) is structurally
constrained: a single _FORBIDDEN_PHRASES tuple gates every string
the analyzer emits, and a unit test asserts the gate at runtime.

Frame is **argument completeness**, not winnability.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    Draft,
    DraftVersion,
    Matter,
)
from caseops_api.services.bench_strategy_context import (
    BenchStrategyContext,
    build_bench_strategy_context,
)
from caseops_api.services.identity import SessionContext

# Hard rule: every string this module ever emits in `suggestions` /
# `weak_evidence_paths` / `recommended_edits` is filtered against this
# list. The structural test in tests/test_appeal_strength.py asserts
# no occurrence in any service output. If a phrase needs to be added
# here, also update the test.
_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "win", "lose", "loss", "winnable", "winnability",
    "favourable", "favorable", "favour", "favor",
    "tendency", "tends to", "usually grants", "usually rules",
    "probability", "chance of success", "likely to succeed",
    "predict", "prediction", "outcome",
)


# Per Indian court hierarchy, used to label authority strength.
# Mirrors `services/authorities._FORUM_PRECEDENT_BOOSTS` but exposed
# as a label rather than a numeric boost so the UI can color-code.
_FORUM_STRENGTH_LABEL: dict[str, str] = {
    "supreme_court": "binding",
    "high_court": "peer",
    "lower_court": "persuasive",
    "tribunal": "persuasive",
    "arbitration": "persuasive",
    "advisory": "persuasive",
}


# Citation pattern matching the drafting service's expected inline
# format: square-bracketed neutral citation or case reference,
# e.g. [2024:BHC:123], [(2022) 10 SCC 51], [APPL 9/2024]. Conservative:
# we only count an inline reference as "supporting" when it bracket-
# wraps something that LOOKS like a citation, not arbitrary text.
_CITATION_BRACKET_RE = re.compile(
    r"\[(?P<cite>(?:\d{4}:[A-Z]+:\d+)|"
    r"(?:\(\d{4}\)\s*\d+\s+[A-Z]+\s*\d+)|"
    r"(?:[A-Z]+\.?\s*[A-Z]*\.?\s*\d+/\d{4})|"
    r"(?:[A-Z]+\s*\(?[A-Z\.]*\)?\s+\d+\s*/\s*\d{4}))\]",
    re.IGNORECASE,
)
# Bracketed gap markers the drafter inserts when authority is missing.
_GAP_MARKER_RE = re.compile(r"\[(?:citation needed|____|\?\?\?)\]", re.IGNORECASE)


# Numbered-ground splitter. Matches "1.", "2.", … at line start (with
# optional leading whitespace). Tuned to the appeal-memorandum prompt
# which numbers grounds in the body.
_NUMBERED_GROUND_RE = re.compile(
    r"(?m)^\s*(?P<n>\d{1,2})\.\s+(?P<text>.+?)(?=^\s*\d{1,2}\.\s+|\Z)",
    re.DOTALL,
)


@dataclass(frozen=True)
class AuthorityRef:
    """A citation found in a ground's text. Resolved against the
    authorities table when possible; ``forum_level`` + ``strength_label``
    are populated only when the resolution succeeds. Unresolved
    citations stay in the analyzer output but with strength="unknown".
    """

    citation: str
    resolved_authority_id: str | None
    title: str | None
    forum_level: str | None
    strength_label: str  # "binding" | "peer" | "persuasive" | "unknown"


@dataclass(frozen=True)
class GroundAssessment:
    ordinal: int
    summary: str
    citation_coverage: str  # "supported" | "partial" | "uncited"
    supporting_authorities: list[AuthorityRef] = field(default_factory=list)
    bench_history_match_count: int = 0
    suggestions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AppealStrengthReport:
    matter_id: str
    draft_id: str | None
    overall_strength: str  # "strong" | "moderate" | "weak"
    ground_assessments: list[GroundAssessment] = field(default_factory=list)
    weak_evidence_paths: list[str] = field(default_factory=list)
    recommended_edits: list[str] = field(default_factory=list)
    bench_context_quality: str = "none"
    has_draft: bool = False


_FORBIDDEN_PATTERN = re.compile(
    # Word-boundary alternation. Matches each token only as a whole
    # word (or whole multi-word phrase), so "closed" doesn't trip
    # "lose" and "discloses" doesn't trip "loss". `(?:^|\W)` and
    # `(?=$|\W)` are explicit boundaries because Python's `\b` is
    # weird around hyphens and apostrophes.
    r"(?:^|\W)(?:" + "|".join(re.escape(p) for p in (
        "win", "lose", "loss", "winnable", "winnability",
        "favourable", "favorable", "favour", "favor",
        "tendency", "tends to", "usually grants", "usually rules",
        "probability", "chance of success", "likely to succeed",
        "predict", "prediction", "outcome",
    )) + r")(?=$|\W)",
    re.IGNORECASE,
)


def _check_phrase(s: str) -> str:
    """Defense-in-depth on every analyzer-emitted string. Asserts at
    debug-time; in prod just returns the string. Combined with the
    structural unit test this gives two layers of protection.

    Word-boundary match — substrings inside legitimate words (e.g.
    "closed", "discloses") do NOT trip the gate.
    """
    m = _FORBIDDEN_PATTERN.search(s)
    assert m is None, (
        f"forbidden token {m.group(0).strip()!r} would leak from "
        f"analyzer: {s!r}"
    )
    return s


def analyze_appeal_strength(
    *,
    session: Session,
    context: SessionContext,
    matter_id: str,
    draft_id: str | None = None,
) -> AppealStrengthReport:
    """Analyze the appeal-strength of a matter's appeal-memorandum
    draft.

    If ``draft_id`` is supplied: analyze that draft's latest version
    body. If omitted: pick the most-recent appeal_memorandum draft on
    the matter; if none exists, return a "no draft yet" report based
    on the bench strategy context alone.

    Tenancy: cross-tenant matter returns 404 (same shape as other
    matter routes).
    """
    matter = session.scalar(
        select(Matter)
        .where(Matter.id == matter_id)
        .where(Matter.company_id == context.company.id)
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )

    bench_ctx = build_bench_strategy_context(
        session=session, context=context, matter_id=matter.id,
    )

    draft = _resolve_draft(
        session, matter=matter, draft_id=draft_id,
    )
    if draft is None:
        return _no_draft_report(matter, bench_ctx)

    # Pull the latest draft version body. Drafts may have multiple
    # versions; we always analyze the highest-revision one.
    latest = session.scalar(
        select(DraftVersion)
        .where(DraftVersion.draft_id == draft.id)
        .order_by(DraftVersion.revision.desc())
        .limit(1)
    )
    if latest is None or not latest.body:
        return _no_draft_report(matter, bench_ctx, draft_id=draft.id)

    grounds_text = _extract_numbered_grounds(latest.body)
    if not grounds_text:
        # Couldn't parse numbered grounds → return a weak-evidence
        # report telling the lawyer to renumber.
        return AppealStrengthReport(
            matter_id=matter.id,
            draft_id=draft.id,
            overall_strength="weak",
            ground_assessments=[],
            weak_evidence_paths=[
                _check_phrase(
                    "Could not parse numbered grounds from the draft "
                    "body. Number each ground (e.g. '1.', '2.') so the "
                    "analyzer can score citation coverage per ground."
                ),
            ],
            recommended_edits=[
                _check_phrase(
                    "Restructure the grounds section as a numbered "
                    "list so each proposition is independently "
                    "anchored to authority."
                ),
            ],
            bench_context_quality=bench_ctx.context_quality,
            has_draft=True,
        )

    # Resolve authorities from bench context for fast lookup.
    bench_authority_index = _build_authority_index(
        session, bench_ctx,
    )
    bench_recurring_phrases = {
        rt.phrase.lower(): rt for rt in bench_ctx.recurring_tests
    }

    assessments: list[GroundAssessment] = []
    for ordinal, ground in grounds_text:
        assessments.append(
            _assess_ground(
                ordinal=ordinal,
                ground_text=ground,
                bench_index=bench_authority_index,
                bench_recurring=bench_recurring_phrases,
                bench_ctx=bench_ctx,
                session=session,
            )
        )

    overall = _overall_strength(assessments, bench_ctx)
    weak_paths = [
        _check_phrase(p)
        for p in _collect_weak_paths(assessments, bench_ctx)
    ]
    recommended = [
        _check_phrase(e)
        for e in _collect_recommended_edits(assessments, bench_ctx)
    ]

    return AppealStrengthReport(
        matter_id=matter.id,
        draft_id=draft.id,
        overall_strength=overall,
        ground_assessments=assessments,
        weak_evidence_paths=weak_paths,
        recommended_edits=recommended,
        bench_context_quality=bench_ctx.context_quality,
        has_draft=True,
    )


# ---------- internals ----------


def _resolve_draft(
    session: Session, *, matter: Matter, draft_id: str | None,
) -> Draft | None:
    if draft_id is not None:
        d = session.scalar(
            select(Draft)
            .where(Draft.id == draft_id)
            .where(Draft.matter_id == matter.id)
        )
        return d
    # Pick the most-recent appeal-memorandum draft on this matter.
    # No archived-state filter — DraftStatus has no ARCHIVED value.
    return session.scalar(
        select(Draft)
        .where(Draft.matter_id == matter.id)
        .where(Draft.template_type == "appeal_memorandum")
        .order_by(Draft.created_at.desc())
        .limit(1)
    )


def _no_draft_report(
    matter: Matter,
    bench_ctx: BenchStrategyContext,
    *,
    draft_id: str | None = None,
) -> AppealStrengthReport:
    """When there's no appeal-memorandum draft yet, fall back to a
    bench-context-only report. Tells the lawyer they need to start
    a draft before per-ground analysis is possible."""
    weak: list[str] = []
    if bench_ctx.context_quality in ("low", "none"):
        weak.append(_check_phrase(
            "Bench-history evidence is sparse for this matter — when "
            "you start the appeal draft, anchor every ground to a "
            "cited authority and add a visible limitation note in the "
            "grounds section."
        ))
    weak.append(_check_phrase(
        "No appeal-memorandum draft exists on this matter yet. The "
        "per-ground analyzer needs draft text to score citation "
        "coverage."
    ))
    return AppealStrengthReport(
        matter_id=matter.id,
        draft_id=draft_id,
        overall_strength="weak",
        ground_assessments=[],
        weak_evidence_paths=weak,
        recommended_edits=[
            _check_phrase(
                "Start an appeal-memorandum draft on this matter to "
                "see per-ground argument-completeness analysis."
            ),
        ],
        bench_context_quality=bench_ctx.context_quality,
        has_draft=False,
    )


def _extract_numbered_grounds(body: str) -> list[tuple[int, str]]:
    """Pull numbered grounds (1., 2., …) from the draft body. Returns
    [(ordinal, text), …] in body order. Empty list when no numbered
    structure is detected."""
    # Look for the GROUNDS section first; the prompt requires the
    # appeal to have a numbered grounds section. Heuristic: anchor on
    # the literal "GROUNDS" heading, fall back to top-of-body parse.
    grounds_section = body
    upper = body.upper()
    for marker in ("GROUNDS OF APPEAL", "GROUNDS:", "GROUNDS"):
        idx = upper.find(marker)
        if idx >= 0:
            grounds_section = body[idx + len(marker):]
            break

    out: list[tuple[int, str]] = []
    for m in _NUMBERED_GROUND_RE.finditer(grounds_section):
        ordinal = int(m.group("n"))
        text = m.group("text").strip()
        # Skip suspiciously short matches (e.g. "1. Yes.")
        if len(text) < 10:
            continue
        out.append((ordinal, text))
    return out


def _build_authority_index(
    session: Session, bench_ctx: BenchStrategyContext,
) -> dict[str, AuthorityDocument]:
    """Index the bench context's authorities by neutral_citation +
    case_reference so a ground's inline citation looks up in O(1)."""
    out: dict[str, AuthorityDocument] = {}
    if not bench_ctx.similar_authorities:
        return out
    ids = [a.id for a in bench_ctx.similar_authorities]
    rows = list(session.scalars(
        select(AuthorityDocument).where(AuthorityDocument.id.in_(ids))
    ))
    for r in rows:
        if r.neutral_citation:
            out[_normalize_citation(r.neutral_citation)] = r
        if r.case_reference:
            out[_normalize_citation(r.case_reference)] = r
    return out


def _normalize_citation(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _assess_ground(
    *,
    ordinal: int,
    ground_text: str,
    bench_index: dict[str, AuthorityDocument],
    bench_recurring: dict[str, object],
    bench_ctx: BenchStrategyContext,
    session: Session,
) -> GroundAssessment:
    """Score a single numbered ground."""
    # Find inline citations.
    refs: list[AuthorityRef] = []
    citation_matches = list(_CITATION_BRACKET_RE.finditer(ground_text))
    gap_matches = list(_GAP_MARKER_RE.finditer(ground_text))

    for m in citation_matches:
        cite = m.group("cite").strip()
        norm = _normalize_citation(cite)
        match = bench_index.get(norm)
        if match is not None:
            label = _FORUM_STRENGTH_LABEL.get(
                (match.forum_level or "").lower(), "persuasive"
            )
            refs.append(AuthorityRef(
                citation=cite,
                resolved_authority_id=match.id,
                title=match.title,
                forum_level=match.forum_level,
                strength_label=label,
            ))
        else:
            # Citation not found in the bench-context authorities. Try
            # a wider DB lookup so we still tag SC vs HC vs lower if
            # the cite resolves to ANY known authority.
            wider = session.scalar(
                select(AuthorityDocument).where(
                    (AuthorityDocument.neutral_citation == cite)
                    | (AuthorityDocument.case_reference == cite)
                ).limit(1)
            )
            if wider is not None:
                label = _FORUM_STRENGTH_LABEL.get(
                    (wider.forum_level or "").lower(), "persuasive"
                )
                refs.append(AuthorityRef(
                    citation=cite,
                    resolved_authority_id=wider.id,
                    title=wider.title,
                    forum_level=wider.forum_level,
                    strength_label=label,
                ))
            else:
                refs.append(AuthorityRef(
                    citation=cite,
                    resolved_authority_id=None,
                    title=None,
                    forum_level=None,
                    strength_label="unknown",
                ))

    # Coverage: supported = >=1 cited authority + no [citation needed]
    # gap markers; partial = cited + gaps; uncited = no cited + has
    # gaps OR no cited at all.
    has_citations = bool(refs)
    has_gaps = bool(gap_matches)
    if has_citations and not has_gaps:
        coverage = "supported"
    elif has_citations and has_gaps:
        coverage = "partial"
    else:
        coverage = "uncited"

    # Bench-history match: count how many recurring phrases from the
    # bench context appear in this ground's text. Cheap signal — the
    # phrase "balance of convenience" turning up in a stay ground
    # paired with a 4x recurrence in the bench's prior judgments is a
    # legitimate "the bench has emphasized this" signal.
    text_lower = ground_text.lower()
    bench_match = sum(
        1 for phrase in bench_recurring if phrase in text_lower
    )

    suggestions = _suggestions_for_ground(
        ordinal=ordinal,
        coverage=coverage,
        refs=refs,
        gap_count=len(gap_matches),
        bench_match=bench_match,
        bench_ctx=bench_ctx,
    )

    summary = _ground_summary(ground_text)
    return GroundAssessment(
        ordinal=ordinal,
        summary=summary,
        citation_coverage=coverage,
        supporting_authorities=refs,
        bench_history_match_count=bench_match,
        suggestions=[_check_phrase(s) for s in suggestions],
    )


def _ground_summary(text: str) -> str:
    """One-line summary of a ground for the UI. Picks the first
    sentence (≤ 200 chars) so the panel can render compact rows."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    # First sentence break.
    m = re.search(r"[.!?]\s", cleaned)
    if m and m.end() < 200:
        return cleaned[: m.end()].strip()
    return cleaned[:200] + ("…" if len(cleaned) > 200 else "")


def _suggestions_for_ground(
    *,
    ordinal: int,
    coverage: str,
    refs: list[AuthorityRef],
    gap_count: int,
    bench_match: int,
    bench_ctx: BenchStrategyContext,
) -> list[str]:
    """Concrete edit suggestions for one ground. Each suggestion is
    actionable and uses NEUTRAL phrasing only — no win/lose, no
    favorability, no probability."""
    out: list[str] = []
    if coverage == "uncited":
        out.append(
            f"Ground {ordinal} has no cited authority. Add at least "
            "one citable authority anchoring the legal proposition, "
            "or rephrase the ground to remove the unsupported claim."
        )
    elif coverage == "partial":
        out.append(
            f"Ground {ordinal} has {gap_count} citation-needed "
            "marker(s). Replace each with a citable authority before "
            "submission, or drop the unsupported sub-proposition."
        )

    has_binding = any(r.strength_label == "binding" for r in refs)
    has_peer = any(r.strength_label == "peer" for r in refs)
    if refs and not has_binding and not has_peer:
        out.append(
            f"Ground {ordinal} relies only on persuasive authorities. "
            "Strengthen by adding a Supreme Court or High Court "
            "decision on the same point if one exists."
        )

    if (
        bench_ctx.context_quality in ("medium", "high")
        and bench_match == 0
        and bench_ctx.recurring_tests
    ):
        # The bench has emphasized something; this ground hasn't
        # invoked it. Surface as a strengthen-with hint.
        nearest = bench_ctx.recurring_tests[0]
        out.append(
            f"The indexed decisions for the candidate bench show "
            f"recurring use of '{nearest.phrase}' "
            f"({nearest.occurrences}× across the bench's prior "
            "judgments). Consider invoking it in this ground if it "
            "fits the facts; cite at least one supporting authority "
            "from the bench context."
        )

    return out


def _overall_strength(
    assessments: list[GroundAssessment],
    bench_ctx: BenchStrategyContext,
) -> str:
    """Roll up per-ground coverage + bench context quality into a
    single label. Conservative: 'strong' requires every ground
    supported AND non-low bench context."""
    if not assessments:
        return "weak"
    supported = sum(
        1 for a in assessments if a.citation_coverage == "supported"
    )
    uncited = sum(
        1 for a in assessments if a.citation_coverage == "uncited"
    )
    total = len(assessments)
    if uncited > 0:
        return "weak"
    if supported == total and bench_ctx.context_quality in ("medium", "high"):
        return "strong"
    return "moderate"


def _collect_weak_paths(
    assessments: Iterable[GroundAssessment],
    bench_ctx: BenchStrategyContext,
) -> list[str]:
    out: list[str] = []
    for a in assessments:
        if a.citation_coverage == "uncited":
            out.append(
                f"Ground {a.ordinal} ({a.summary[:60]}…) has no cited "
                "authority — submission risk."
            )
        elif a.citation_coverage == "partial":
            out.append(
                f"Ground {a.ordinal} has citation-needed gaps that "
                "must be closed before submission."
            )
    if bench_ctx.context_quality in ("low", "none"):
        out.append(
            "Bench-history evidence is sparse for this matter — "
            "do not rely on bench-specific framing in any ground."
        )
    return out


def _collect_recommended_edits(
    assessments: Iterable[GroundAssessment],
    bench_ctx: BenchStrategyContext,
) -> list[str]:
    out: list[str] = []
    for a in assessments:
        for s in a.suggestions:
            out.append(s)
    if bench_ctx.unsupported_gaps:
        out.append(
            "The bench-strategy-context flagged "
            f"{len(bench_ctx.unsupported_gaps)} unsupported gap(s) "
            "in the bench history; treat any related claims as "
            "anecdotal rather than as a pattern."
        )
    return out


__all__ = [
    "AppealStrengthReport",
    "AuthorityRef",
    "GroundAssessment",
    "analyze_appeal_strength",
]
