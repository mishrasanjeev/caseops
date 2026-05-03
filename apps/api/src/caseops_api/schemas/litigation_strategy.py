"""MOD-LSE (2026-05-03) — litigation strategy planner schemas.

The strategy planner reuses the existing ``Recommendation`` table for
identity, audit, and decisions, and stores its richer structured
output in ``recommendations.strategy_payload_json`` (added by the
``20260503_0001_litigation_strategy_payload`` alembic migration).

This module is the single source of truth for that payload's shape.
Both the service that generates it AND the API layer that returns it
validate against ``LitigationStrategyPayload``.

Design notes:

- Every list is bounded so a runaway LLM cannot blow the JSON column
  past a sensible size.
- Every string has a max length; a strategy is a one-screen brief, not
  a treatise.
- Every field that names a "route" or a "draft" or a "limitation flag"
  is structured, not free text — so the UI can render it without a
  second LLM call to parse it back.
- ``review_required`` is NOT on the payload because the
  ``Recommendation`` row carries it. Strategy rows are ALWAYS
  ``review_required=true`` (enforced at the service layer).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The 11 SC + escalation drafts ship in this branch alongside the 20
# pre-existing templates. The recommended_drafts panel uses the same
# string identifiers — see ``schemas/drafting_templates.py`` and
# ``services/drafting_prompts.py``. Free-text identifiers are allowed
# so strategies can also recommend any of the 20 pre-existing
# templates without this Literal having to enumerate every one.
RecommendedDraftType = str

# Forum levels we accept on a forum_sequence step. Mirrors the
# ``Matter.forum_level`` field but kept separate because the SC
# escalation ladder also models "tribunal" / "registrar" / "review"
# stages that are not a Matter forum_level.
ForumStepLevel = Literal[
    "lower_court",
    "tribunal",
    "high_court_single_bench",
    "high_court_division_bench",
    "supreme_court",
    "supreme_court_review",
    "supreme_court_curative",
    "arbitration",
    "executive",
    "other",
]

RouteAvailability = Literal["available", "uncertain", "not_available"]
LimitationSeverity = Literal["info", "warning", "critical"]
RiskSeverity = Literal["low", "medium", "high"]


class StrategyRoute(BaseModel):
    """One end-to-end route from current posture to terminal relief.

    Each route is independently citable: the rationale must reference
    at least one verified authority OR plead an explicit "no
    grounding" risk note that the verifier honours. The list of
    citations is the same shape the recommendation pipeline uses.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=2, max_length=400)
    rationale: str = Field(min_length=2, max_length=4000)
    confidence: Literal["low", "medium", "high"] = "low"
    availability: RouteAvailability = "uncertain"
    supporting_citations: list[str] = Field(default_factory=list, max_length=20)
    risk_notes: str | None = Field(default=None, max_length=2000)


class ForumStep(BaseModel):
    """One node on the escalation ladder.

    Order is meaningful — the list is the route through forums in
    chronological order. ``stage_label`` is a short tag the UI shows on
    the step (e.g. "First appeal", "SLP", "Review").

    Round-2 P1 #4: the forum step's statutory / jurisdictional basis is
    a legal claim and must be cited. ``supporting_citations`` is the
    list of citations that the verifier confirmed against the retrieved
    authority set. ``unverified=True`` is set when the LLM either
    emitted no citation for this step or every citation it emitted
    failed verification.
    """

    model_config = ConfigDict(extra="forbid")

    forum_level: ForumStepLevel
    stage_label: str = Field(min_length=2, max_length=120)
    forum_name: str | None = Field(default=None, max_length=255)
    rationale: str = Field(min_length=2, max_length=2000)
    statutory_basis: list[str] = Field(default_factory=list, max_length=10)
    expected_filings: list[RecommendedDraftType] = Field(
        default_factory=list, max_length=10,
    )
    supporting_citations: list[str] = Field(default_factory=list, max_length=10)
    unverified: bool = False


class RecommendedDraft(BaseModel):
    """A drafting template the user can launch from the strategy.

    ``template_type`` matches a ``DraftTemplateType`` enum value — the
    UI deep-links to ``/app/matters/{id}/drafts/new?type=<value>`` and
    the stepper validates the type itself. ``available`` flips to
    false for templates the user cannot complete (e.g. SC drafts on a
    matter that is not yet at the SC stage); the UI greys out the
    button + shows the reason.
    """

    model_config = ConfigDict(extra="forbid")

    template_type: RecommendedDraftType = Field(min_length=2, max_length=80)
    display_name: str = Field(min_length=2, max_length=200)
    purpose: str = Field(min_length=2, max_length=600)
    available: bool = True
    reason_unavailable: str | None = Field(default=None, max_length=400)


class LimitationFlag(BaseModel):
    """A limitation / drop-dead deadline the matter must meet.

    ``deadline_iso`` is an ISO yyyy-mm-dd date when the model can
    compute it from facts. When it cannot, we DO NOT invent one —
    ``deadline_iso`` stays None and ``description`` calls out the
    missing fact (e.g. "limitation runs from impugned-order date,
    which is not on file").

    Round-2 P1 #4: a limitation flag is a legal claim about a statutory
    deadline. ``supporting_citations`` carries the verifier-confirmed
    citations; ``unverified=True`` is set when the cited statute /
    case did not verify against the retrieved authority set.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=1000)
    statutory_basis: str | None = Field(default=None, max_length=200)
    deadline_iso: str | None = Field(default=None, max_length=10)
    severity: LimitationSeverity = "info"
    supporting_citations: list[str] = Field(default_factory=list, max_length=10)
    unverified: bool = False


class StrategyRisk(BaseModel):
    """One downside the lawyer must factor in before pursuing the
    recommended route. Risks are deliberately distinct from
    ``risk_notes`` on a route — those are per-route; these are
    cross-cutting risks (cost, reputational, parallel proceedings,
    counterclaim exposure).

    Round-2 P1 #4: risks are sometimes purely factual (cost, client
    withdrawal, reputational fallout) and need no citation. Other
    times they are legal/procedural claims (parallel-proceedings bar,
    counterclaim exposure under a specific section). When the LLM
    chooses to emit ``supporting_citations`` for a risk, we run them
    through the verifier; if every emitted citation fails, we set
    ``unverified=True`` and drop the citations from the persisted
    payload. Empty ``supporting_citations`` is the factual-risk path
    and does not flip ``unverified``.
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=2000)
    severity: RiskSeverity = "medium"
    mitigation: str | None = Field(default=None, max_length=1000)
    supporting_citations: list[str] = Field(default_factory=list, max_length=10)
    unverified: bool = False


class NextBestAction(BaseModel):
    """A concrete next step the lawyer should take. Round-2 P1 #4
    structurised this from a free string list so each action's
    procedural basis can be cited and verified. ``unverified=True`` is
    set when the LLM emitted a citation for the action that did not
    verify against the retrieved authority set, OR when the action
    makes a legal claim with no citation. Purely operational actions
    (``"call the client back"``) are emitted with no citations and
    ``unverified=False``.
    """

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=2, max_length=600)
    supporting_citations: list[str] = Field(default_factory=list, max_length=10)
    unverified: bool = False


class LitigationStrategyPayload(BaseModel):
    """The structured output the strategy planner produces.

    Pinned to ``recommendations.strategy_payload_json`` and validated
    on every read and write. ``review_required`` is NOT on this model
    because the parent ``Recommendation`` row carries it — strategy
    rows are ALWAYS review_required=true.
    """

    model_config = ConfigDict(extra="forbid")

    current_posture: str = Field(min_length=2, max_length=2000)
    recommended_route: StrategyRoute
    alternative_routes: list[StrategyRoute] = Field(
        default_factory=list, max_length=4,
    )
    forum_sequence: list[ForumStep] = Field(min_length=1, max_length=10)
    recommended_drafts: list[RecommendedDraft] = Field(
        default_factory=list, max_length=12,
    )
    limitation_flags: list[LimitationFlag] = Field(
        default_factory=list, max_length=10,
    )
    required_documents: list[str] = Field(default_factory=list, max_length=20)
    missing_facts: list[str] = Field(default_factory=list, max_length=20)
    risks: list[StrategyRisk] = Field(default_factory=list, max_length=10)
    next_best_actions: list[NextBestAction] = Field(
        default_factory=list, max_length=10,
    )
    disclaimer: str = Field(min_length=2, max_length=2000)


# Shared — the structural test in tests/test_litigation_strategy.py
# scans every generated payload + every test fixture for these
# substrings. They are FORBIDDEN per the product rule. Update with
# care; loosening this list is a product-policy change, not a code
# change.
FORBIDDEN_OUTCOME_PHRASES: tuple[str, ...] = (
    "perfect strategy",
    "guaranteed",
    "guarantee success",
    "will win",
    "will succeed",
    "will be granted",
    "certain outcome",
    "certain to succeed",
    "no lawyer needed",
    "replace advocate",
    "replace your lawyer",
    "without a lawyer",
)

# Round-2 P2 #5: outcome-PROBABILITY phrases. Strategy is about
# routes / risks / procedural posture / evidence gaps — never about
# outcome probability. The user-experience problem is real for legal
# products: 'high likelihood of success' phrasing reads as a guarantee
# to a non-lawyer reader. We scan the route rationale + risk-notes /
# description fields specifically (not the whole payload) so legitimate
# uses of words like 'likely' inside an authority excerpt or a
# limitation description don't trip the gate. Each entry is a regex
# pattern (case-insensitive) — we keep them strict to minimise false
# positives.

FORBIDDEN_PROBABILITY_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\b\d{1,3}\s*%\s*(?:chance|likelihood|probability|odds|"
        r"likely|likely\s+to\s+win|likelihood\s+of\s+success)",
        "percentage-based outcome ('30% chance', '70% likelihood')",
    ),
    (
        r"\b\d{1,3}\s*percent\s+(?:chance|likelihood|probability|odds)",
        "percent-based outcome ('30 percent chance')",
    ),
    (
        r"\blikely\s+to\s+win\b",
        "'likely to win'",
    ),
    (
        r"\blikelihood\s+of\s+success\b",
        "'likelihood of success'",
    ),
    (
        r"\bprobability\s+of\s+success\b",
        "'probability of success'",
    ),
    (
        r"\bchance(?:s)?\s+of\s+success\b",
        "'chance(s) of success'",
    ),
    (
        r"\bodds\s+of\s+(?:winning|succeeding|success)\b",
        "'odds of winning/succeeding/success'",
    ),
    (
        r"\bhigh(?:ly)?\s+likely\s+to\s+(?:win|succeed|prevail)\b",
        "'highly likely to win/succeed/prevail'",
    ),
)

# Fields on the persisted strategy payload that the probability scan
# walks. We deliberately avoid scanning ``required_documents``,
# ``missing_facts``, and ``recommended_drafts.purpose`` because those
# come from the registry / matter facts, not from the LLM's outcome
# framing. We also DO NOT scan ``forum_sequence[*].statutory_basis``
# entries (statute names like 'Limitation Act' — false positives).
_PROBABILITY_SCAN_FIELDS: tuple[str, ...] = (
    "current_posture",
    "recommended_route.rationale",
    "recommended_route.risk_notes",
    "alternative_routes[].rationale",
    "alternative_routes[].risk_notes",
    "forum_sequence[].rationale",
    "limitation_flags[].description",
    "risks[].description",
    "risks[].mitigation",
    "next_best_actions[].action",
    "disclaimer",
)


def _walk_probability_scan_fields(payload: LitigationStrategyPayload) -> list[str]:
    """Yield the strings on ``payload`` that the probability scan
    walks. Centralised so test_litigation_strategy can assert the same
    fields the runtime scan covers."""
    out: list[str] = [payload.current_posture, payload.disclaimer]
    if payload.recommended_route.rationale:
        out.append(payload.recommended_route.rationale)
    if payload.recommended_route.risk_notes:
        out.append(payload.recommended_route.risk_notes)
    for alt in payload.alternative_routes:
        if alt.rationale:
            out.append(alt.rationale)
        if alt.risk_notes:
            out.append(alt.risk_notes)
    for step in payload.forum_sequence:
        if step.rationale:
            out.append(step.rationale)
    for flag in payload.limitation_flags:
        if flag.description:
            out.append(flag.description)
    for risk in payload.risks:
        if risk.description:
            out.append(risk.description)
        if risk.mitigation:
            out.append(risk.mitigation)
    for nba in payload.next_best_actions:
        if nba.action:
            out.append(nba.action)
    return out


def assert_no_forbidden_phrases(text: str) -> None:
    """Raise ``ValueError`` if any forbidden phrase appears in
    ``text`` (case-insensitive). Callers either pass the full strategy
    JSON or a concatenation of every user-visible string field.

    Used both as a runtime gate (after generation, before persistence)
    AND as a unit-test assertion.
    """
    haystack = text.lower()
    for needle in FORBIDDEN_OUTCOME_PHRASES:
        if needle in haystack:
            raise ValueError(
                f"Strategy text contained forbidden phrase {needle!r}. "
                "Strategy outputs must not promise outcomes."
            )


def assert_no_probability_language(payload: LitigationStrategyPayload) -> None:
    """Round-2 P2 #5. Scan the narrative fields on a built strategy
    payload for outcome-probability phrasing and raise ``ValueError``
    on the first hit. Called after assert_no_forbidden_phrases as a
    second layer.
    """
    for value in _walk_probability_scan_fields(payload):
        lowered = value.lower()
        for pattern, description in FORBIDDEN_PROBABILITY_PATTERNS:
            if re.search(pattern, lowered):
                raise ValueError(
                    "Strategy text used outcome-probability language "
                    f"({description}). Strategy outputs are about routes, "
                    "risks, procedural posture, and evidence gaps — not "
                    "outcome probability. Rewrite without the probability "
                    "framing."
                )


__all__ = [
    "FORBIDDEN_OUTCOME_PHRASES",
    "FORBIDDEN_PROBABILITY_PATTERNS",
    "ForumStep",
    "ForumStepLevel",
    "LimitationFlag",
    "LimitationSeverity",
    "LitigationStrategyPayload",
    "NextBestAction",
    "RecommendedDraft",
    "RecommendedDraftType",
    "RouteAvailability",
    "StrategyRisk",
    "StrategyRoute",
    "RiskSeverity",
    "assert_no_forbidden_phrases",
    "assert_no_probability_language",
]
