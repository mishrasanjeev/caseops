"""Citation treatment classifier — PG-006 Phase 1A.

Given a passage of text from a citing case + the literal citation
substring inside it, this returns the *treatment* the citing case
gives the cited authority:

    followed | distinguished | overruled | doubted |
    reversed | dissented | considered | neutral

The classifier is rule-based on cue verbs in the surrounding 200
characters. We use a tiered cue list — explicit overrules and
reversals win over softer cues like "considered" — and emit a
confidence in [0, 1] derived from how many cues fire. Zero LLM
spend; the LLM-assisted pass for uncertain rows is Phase 1C.

This module is deliberately surgical: it stays out of the regex
extraction path in ``citation_extraction.py`` and is invoked by it
once per insertion. Backfill calls the same classifier from a
script.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from caseops_api.db.models import AuthorityCitationTreatment

CONTEXT_WINDOW_CHARS = 200


@dataclass(frozen=True)
class TreatmentResult:
    treatment: AuthorityCitationTreatment
    confidence: float
    evidence_text: str | None


# Cue patterns — ordered by treatment priority. The first matching tier
# wins so explicit overrules don't get masked by an earlier "considered"
# in the same window.
#
# Patterns intentionally tolerate Indian English variants and the
# common "we [verb]" / "is hereby [verb]" / "we are inclined to
# [verb]" framings seen in real judgments.
_OVERRULED_CUES = re.compile(
    r"\b(over[-\s]?rul(?:e|ed|es|ing)|stands?\s+overruled|"
    r"is\s+(?:hereby\s+)?overruled|no\s+longer\s+good\s+law)\b",
    re.IGNORECASE,
)
_REVERSED_CUES = re.compile(
    r"\b(revers(?:e|ed|es|ing)|set\s+aside|set\s+at\s+naught|"
    r"is\s+(?:hereby\s+)?reversed)\b",
    re.IGNORECASE,
)
_DOUBTED_CUES = re.compile(
    r"\b(doubt(?:ed|s|ing)?|cast(?:s|ing)?\s+doubt|"
    r"questioned?\s+the\s+correctness|with\s+respect[,]?\s+we\s+doubt)\b",
    re.IGNORECASE,
)
_DISTINGUISHED_CUES = re.compile(
    r"\b(distinguish(?:ed|es|ing)?|distinguishable|"
    r"facts\s+(?:are|of\s+the\s+present\s+case)\s+(?:are\s+)?different|"
    r"not\s+applicable\s+to\s+the\s+facts|of\s+no\s+assistance|"
    r"has\s+no\s+application)\b",
    re.IGNORECASE,
)
_DISSENTED_CUES = re.compile(
    r"\b(dissent(?:ed|ing)?\s+(?:opinion|view|judgment)|"
    r"per\s+(?:the\s+)?dissent(?:ing)?|in\s+(?:his|her|the)\s+dissent)\b",
    re.IGNORECASE,
)
_FOLLOWED_CUES = re.compile(
    r"\b(follow(?:ed|s|ing)?|approv(?:e|ed|es|ing)|"
    r"relied\s+(?:up)?on|reaffirm(?:ed|s|ing)?|in\s+line\s+with|"
    r"(?:we\s+)?(?:respectfully\s+)?agree(?:\s+with)?|"
    r"appl(?:y|ied|ies|ying))\b",
    re.IGNORECASE,
)
_CONSIDERED_CUES = re.compile(
    r"\b(considered|noticed|adverted\s+to|referred\s+to|"
    r"(?:had|has)\s+occasion\s+to\s+observe)\b",
    re.IGNORECASE,
)


def _confidence(num_cues: int) -> float:
    """Map cue-count to a confidence in [0.5, 0.95].

    A single cue is enough to fire the treatment but not enough to
    block a later LLM-assisted re-classification. Two-plus cues in the
    same window read as strong (0.85-0.95) — at that point the citing
    judge has spelled out their treatment.
    """
    if num_cues <= 0:
        return 0.0
    if num_cues == 1:
        return 0.6
    if num_cues == 2:
        return 0.85
    return 0.95


def classify_citation_treatment(
    document_text: str,
    citation_text: str,
    *,
    window_chars: int = CONTEXT_WINDOW_CHARS,
) -> TreatmentResult:
    """Classify treatment of one citation occurrence.

    `document_text` is the full citing-case text; `citation_text` is
    the literal citation substring that was extracted (e.g. ``(2020) 7
    SCC 1``). We look at a window of ``window_chars`` BEFORE and AFTER
    the citation occurrence — most cue verbs ("followed", "overruled
    in") sit before the citation in Indian judgments, but distinguishing
    language often follows.

    Returns ``TreatmentResult(NEUTRAL, 0.0, None)`` when no cue fires.
    """
    if not document_text or not citation_text:
        return TreatmentResult(
            AuthorityCitationTreatment.NEUTRAL, 0.0, None,
        )

    idx = document_text.lower().find(citation_text.lower())
    if idx == -1:
        return TreatmentResult(
            AuthorityCitationTreatment.NEUTRAL, 0.0, None,
        )

    start = max(0, idx - window_chars)
    end = min(len(document_text), idx + len(citation_text) + window_chars)
    window = document_text[start:end]

    # Tier ordering: explicit bad-law cues win, then mildly negative,
    # then positive, then weak. A window can fire multiple tiers — we
    # keep the first hit for `treatment` but accumulate cues across
    # tiers for the confidence score.
    tiers: list[tuple[AuthorityCitationTreatment, re.Pattern[str]]] = [
        (AuthorityCitationTreatment.OVERRULED, _OVERRULED_CUES),
        (AuthorityCitationTreatment.REVERSED, _REVERSED_CUES),
        (AuthorityCitationTreatment.DOUBTED, _DOUBTED_CUES),
        (AuthorityCitationTreatment.DISTINGUISHED, _DISTINGUISHED_CUES),
        (AuthorityCitationTreatment.DISSENTED, _DISSENTED_CUES),
        (AuthorityCitationTreatment.FOLLOWED, _FOLLOWED_CUES),
        (AuthorityCitationTreatment.CONSIDERED, _CONSIDERED_CUES),
    ]

    chosen: AuthorityCitationTreatment | None = None
    evidence_match: re.Match[str] | None = None
    total_cue_hits = 0
    for treatment, pattern in tiers:
        for m in pattern.finditer(window):
            total_cue_hits += 1
            if chosen is None:
                chosen = treatment
                evidence_match = m

    if chosen is None or evidence_match is None:
        return TreatmentResult(
            AuthorityCitationTreatment.NEUTRAL, 0.0, None,
        )

    # Trim evidence to a 120-char snippet around the cue verb.
    cue_start = evidence_match.start()
    cue_end = evidence_match.end()
    snippet_start = max(0, cue_start - 40)
    snippet_end = min(len(window), cue_end + 60)
    evidence = window[snippet_start:snippet_end].strip()

    return TreatmentResult(
        treatment=chosen,
        confidence=_confidence(total_cue_hits),
        evidence_text=evidence[:500] or None,
    )


__all__ = ["TreatmentResult", "classify_citation_treatment"]
