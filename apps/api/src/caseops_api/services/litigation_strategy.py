"""MOD-LSE-2 (2026-05-03) — Litigation Strategy and Escalation Planner.

Generates a citation-grounded, lawyer-reviewed strategy for a matter.
Distinct from the four classical recommendation types
(``forum``/``authority``/``remedy``/``next_best_action``) because:

- The output is a *route plan*, not a list of options. Each route is
  a sequence of forum steps + supporting drafts + limitation flags.
- Escalation to Supreme Court is first-class. Routes surface SLPs,
  reviews, curative petitions when they are legally plausible.
- Recommended drafts deep-link into the existing ``DraftTemplateType``
  drafting flow.

Hard product rules (PRD §2):

- Always ``review_required=True``.
- Refuse / fail-closed on zero verified citations (HTTP 422).
- Never emit ``perfect strategy``, ``guaranteed``, ``will win``,
  ``certain outcome``, ``no lawyer needed``, ``replace advocate``.
  ``assert_no_forbidden_phrases`` enforces this AFTER LLM generation
  but BEFORE persistence.
- Missing facts are listed, not invented.
- Authorities, dates, forum names, remedies are not invented.

The pipeline mirrors ``services/recommendations.generate_recommendation``
to keep the audit / model-run / review-required invariants
identical:

    matter context + retrieval
    → prompt assembly
    → LLM generation (structured JSON, validated against
      ``LitigationStrategyPayload``)
    → forbidden-phrase scan
    → citation verification (fail-closed on zero)
    → persistence (Recommendation row + strategy_payload_json)
    → audit row
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuthorityDocument,
    Matter,
    MatterAttachment,
    MatterCauseListEntry,
    MatterCourtOrder,
    MatterHearing,
    MatterStatuteReference,
    ModelRun,
    Recommendation,
    RecommendationOption,
    Statute,
    StatuteSection,
)
from caseops_api.schemas.drafting_templates import (
    DraftTemplateType,
    list_template_schemas,
)
from caseops_api.schemas.litigation_strategy import (
    ForumStep,
    LimitationFlag,
    LitigationStrategyPayload,
    NextBestAction,
    RecommendedDraft,
    StrategyRisk,
    StrategyRoute,
    assert_no_forbidden_phrases,
    assert_no_probability_language,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.authorities import search_authority_catalog
from caseops_api.services.citations import (
    Claim,
    SourceDoc,
    VerificationReport,
    verify_citations,
)
from caseops_api.services.llm import (
    PURPOSE_RECOMMENDATIONS,
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponseFormatError,
    build_provider,
    generate_structured,
)
from caseops_api.services.llm_http import provider_failure_http_exception
from caseops_api.services.session_context import SessionContext
from caseops_api.services.template_recommender import (
    TemplateRecommendation,
    recommend_templates,
)

logger = logging.getLogger(__name__)

CONFIDENCE_LEVELS = ("low", "medium", "high")


@dataclass
class RetrievedAuthority:
    identifier: str
    text: str
    aliases: tuple[str, ...] = ()


_OUTCOME_BIAS: dict[str, dict[str, tuple[str, ...]]] = {
    "criminal": {
        "preferred": ("allowed", "granted", "quashed", "acquitted"),
        "against": ("dismissed", "rejected", "denied", "convicted"),
    },
    "bail": {
        "preferred": ("granted", "allowed", "bail allowed"),
        "against": ("denied", "dismissed", "rejected"),
    },
    "civil": {
        "preferred": ("allowed", "decreed", "partly allowed"),
        "against": ("dismissed",),
    },
    "commercial": {
        "preferred": ("allowed", "decreed", "partly allowed"),
        "against": ("dismissed",),
    },
    "employment": {
        "preferred": ("allowed", "granted", "reinstated"),
        "against": ("dismissed", "rejected"),
    },
    "family": {
        "preferred": ("allowed", "granted", "decreed"),
        "against": ("dismissed", "rejected"),
    },
    "intellectual_property": {
        "preferred": ("allowed", "granted", "injunction granted"),
        "against": ("dismissed", "rejected"),
    },
    "real_estate": {
        "preferred": ("allowed", "decreed", "specific performance"),
        "against": ("dismissed",),
    },
    "constitutional": {
        "preferred": ("allowed", "struck down", "directions issued"),
        "against": ("dismissed",),
    },
}


# ---------------------------------------------------------------
# Pydantic shape the LLM must respond with. We deliberately re-use
# ``LitigationStrategyPayload`` instead of inventing a parallel model
# so the persisted JSON column and the wire format are the same
# shape, validated by the same code.
# ---------------------------------------------------------------


class _StrategyOption(BaseModel):
    """Mirror of ``StrategyRoute`` shape for the LLM JSON. Kept narrow
    so generate_structured does not have to teach the model the
    nuances of pydantic discriminators — the LLM emits this, we
    re-coerce to ``StrategyRoute`` after citation verification."""

    label: str = Field(min_length=2, max_length=400)
    rationale: str = Field(min_length=2, max_length=4000)
    confidence: str = "low"
    availability: str = "uncertain"
    supporting_citations: list[str] = Field(default_factory=list, max_length=20)
    risk_notes: str | None = None


class _LLMStrategyResponse(BaseModel):
    """The LLM's structured response. Note that we ALSO accept the
    ``LitigationStrategyPayload`` fields directly so the payload
    persisted on the Recommendation row is faithful to what the LLM
    produced. ``recommended_route`` and ``alternative_routes`` use the
    narrow ``_StrategyOption`` shape so citation verification can
    rewrite ``supporting_citations`` in place."""

    title: str = Field(min_length=2, max_length=400)
    current_posture: str = Field(min_length=2, max_length=2000)
    recommended_route: _StrategyOption
    alternative_routes: list[_StrategyOption] = Field(
        default_factory=list, max_length=4,
    )
    forum_sequence: list[dict] = Field(min_length=1, max_length=10)
    limitation_flags: list[dict] = Field(default_factory=list, max_length=10)
    required_documents: list[str] = Field(default_factory=list, max_length=20)
    missing_facts: list[str] = Field(default_factory=list, max_length=20)
    risks: list[dict] = Field(default_factory=list, max_length=10)
    # Round-2 P1 #4: structured next_best_actions so each action's
    # procedural basis can be cited and verified. We accept either
    # ``[str]`` (legacy) or ``[{"action": str, "supporting_citations": [...]}]``
    # so an LLM that hasn't picked up the new schema doesn't 502 the
    # whole strategy. The post-processor coerces both forms into
    # ``list[NextBestAction]`` before persistence.
    next_best_actions: list[str | dict] = Field(default_factory=list, max_length=10)
    rationale: str = Field(min_length=2, max_length=8000)
    confidence: str = "low"
    next_action: str | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    disclaimer: str = Field(
        default=(
            "Strategy outputs are citation-grounded but require lawyer "
            "review before any filing. CaseOps does not promise outcomes."
        ),
        min_length=2,
        max_length=2000,
    )


# ---------------------------------------------------------------
# Context assembly. We keep this read-only; the strategy planner
# does NOT mutate the matter, hearings, or document attachments.
# ---------------------------------------------------------------


@dataclass
class _AttachmentSnippet:
    title: str
    excerpt: str


@dataclass
class _StatuteSnippet:
    statute_name: str
    section_number: str
    section_label: str | None
    section_text: str | None
    relevance: str  # 'cited' | 'opposing' | 'context'


@dataclass
class _CourtOrderSnippet:
    title: str
    order_date: str
    summary: str
    order_text_excerpt: str | None
    source: str


@dataclass
class _StrategyContext:
    matter: Matter
    hearings: list[MatterHearing]
    template_recommendations: list[TemplateRecommendation]
    sc_route_plausible: bool
    attachment_snippets: list[_AttachmentSnippet]
    statute_snippets: list[_StatuteSnippet]
    cause_list_snippets: list[MatterCauseListEntry]
    # Round-3 P2 #R3-4: court-sync orders are first-class matter
    # records and escalation strategy depends on impugned/interim
    # orders. The Round-2 context block did not include them.
    court_order_snippets: list[_CourtOrderSnippet]


# Round-2 P2 #6 budget knobs. The PR's prompt already runs ~3000 chars
# per matter; we cap each new context block so a doc-rich matter does
# not blow the LLM's context window.
_MAX_ATTACHMENT_DOCS = 6
_MAX_ATTACHMENT_EXCERPT_CHARS = 600
_MAX_STATUTE_REFS = 8
_MAX_STATUTE_SECTION_TEXT_CHARS = 600
_MAX_CAUSE_LIST_ENTRIES = 4
# Round-3 P2 #R3-4 budget knobs. order_text can be very long — the
# bounded excerpt keeps a doc-rich matter from blowing the prompt
# window.
_MAX_COURT_ORDERS = 5
_MAX_COURT_ORDER_SUMMARY_CHARS = 200
_MAX_COURT_ORDER_TEXT_CHARS = 500


def _assemble_context(session: Session, matter: Matter) -> _StrategyContext:
    """Pull the matter context the strategy planner needs.

    We fetch:
      - the upcoming + past hearings to surface stage context
      - the template recommender's matrix output (drafts panel seed)
      - Round-2 P2 #6: matter attachments (titles + bounded excerpts),
        linked statute references with section text, and recent
        bench/cause-list entries. This is the context the brief said
        was missing — without it the strategy planner could only see
        the matter description and hearings, leaving uploaded orders /
        statute references / next-bench information out of scope.

    Each new block is bounded so a doc-rich matter does not blow the
    prompt budget.
    """
    hearings = list(
        session.scalars(
            select(MatterHearing)
            .where(MatterHearing.matter_id == matter.id)
            .order_by(MatterHearing.hearing_on.desc())
            .limit(20)
        )
    )
    template_recs = recommend_templates(
        forum_level=matter.forum_level or "",
        practice_area=matter.practice_area or "",
    )

    # Attachments — only those whose extraction succeeded so we feed
    # text the LLM can actually read. Most-recent first.
    attachments = list(
        session.scalars(
            select(MatterAttachment)
            .where(MatterAttachment.matter_id == matter.id)
            .where(MatterAttachment.extracted_text.is_not(None))
            .order_by(MatterAttachment.created_at.desc())
            .limit(_MAX_ATTACHMENT_DOCS)
        )
    )
    attachment_snippets: list[_AttachmentSnippet] = []
    for att in attachments:
        excerpt = (att.extracted_text or "").strip()
        if not excerpt:
            continue
        attachment_snippets.append(
            _AttachmentSnippet(
                title=att.original_filename,
                excerpt=excerpt[:_MAX_ATTACHMENT_EXCERPT_CHARS],
            )
        )

    # Statutes — joined with the section + parent statute so we can
    # render 'BNSS s.528' style identifiers + a bounded slice of
    # section_text where indexed.
    statute_rows = list(
        session.execute(
            select(MatterStatuteReference, StatuteSection, Statute)
            .join(
                StatuteSection,
                StatuteSection.id == MatterStatuteReference.section_id,
            )
            .join(Statute, Statute.id == StatuteSection.statute_id)
            .where(MatterStatuteReference.matter_id == matter.id)
            .order_by(MatterStatuteReference.created_at.desc())
            .limit(_MAX_STATUTE_REFS)
        )
    )
    statute_snippets: list[_StatuteSnippet] = []
    for ref, section, statute in statute_rows:
        text = (section.section_text or "").strip() or None
        if text and len(text) > _MAX_STATUTE_SECTION_TEXT_CHARS:
            text = text[:_MAX_STATUTE_SECTION_TEXT_CHARS] + "…"
        statute_snippets.append(
            _StatuteSnippet(
                statute_name=statute.short_name,
                section_number=section.section_number,
                section_label=section.section_label,
                section_text=text,
                relevance=ref.relevance,
            )
        )

    # Cause-list / next-bench entries — bench_name + listing_date is
    # the procedurally relevant context. Older than current is OK; we
    # just want the next few listings ordered desc.
    cause_list_entries = list(
        session.scalars(
            select(MatterCauseListEntry)
            .where(MatterCauseListEntry.matter_id == matter.id)
            .order_by(MatterCauseListEntry.listing_date.desc())
            .limit(_MAX_CAUSE_LIST_ENTRIES)
        )
    )

    # Round-3 P2 #R3-4: court-sync orders. The most recent N
    # impugned/interim orders are critical for escalation strategy —
    # an SLP's substantial-question hook usually flows from the HC
    # order being challenged. order_text is bounded so a long judgment
    # does not blow the prompt window.
    court_order_rows = list(
        session.scalars(
            select(MatterCourtOrder)
            .where(MatterCourtOrder.matter_id == matter.id)
            .order_by(
                MatterCourtOrder.order_date.desc(),
                MatterCourtOrder.created_at.desc(),
            )
            .limit(_MAX_COURT_ORDERS)
        )
    )
    court_order_snippets: list[_CourtOrderSnippet] = []
    for order in court_order_rows:
        summary = (order.summary or "").strip()
        if len(summary) > _MAX_COURT_ORDER_SUMMARY_CHARS:
            summary = summary[:_MAX_COURT_ORDER_SUMMARY_CHARS] + "…"
        excerpt: str | None = None
        if order.order_text:
            text = order.order_text.strip()
            if text:
                if len(text) > _MAX_COURT_ORDER_TEXT_CHARS:
                    text = text[:_MAX_COURT_ORDER_TEXT_CHARS] + "…"
                excerpt = text
        court_order_snippets.append(
            _CourtOrderSnippet(
                title=order.title,
                order_date=order.order_date.isoformat(),
                summary=summary,
                order_text_excerpt=excerpt,
                source=order.source,
            )
        )

    # SC plausibility is a coarse heuristic on the matter forum_level
    # plus the practice area. Routes that escalate to SC are surfaced
    # only when this gate is open. The LLM can still REFUSE to
    # recommend an SC route on the facts; this gate just stops it
    # from inventing one when no path exists.
    forum = (matter.forum_level or "").strip().lower()
    sc_plausible = forum in {
        "high_court",
        "supreme_court",
        "tribunal",
        "high_court_division_bench",
        "high_court_single_bench",
    }
    return _StrategyContext(
        matter=matter,
        hearings=hearings,
        template_recommendations=template_recs,
        sc_route_plausible=sc_plausible,
        attachment_snippets=attachment_snippets,
        statute_snippets=statute_snippets,
        cause_list_snippets=cause_list_entries,
        court_order_snippets=court_order_snippets,
    )


def _build_prompt(
    *,
    ctx: _StrategyContext,
    authorities: list[RetrievedAuthority],
) -> list[LLMMessage]:
    """Build the system + user messages for the strategy LLM call.

    The system prompt is the GUARDRAILS surface — every hard product
    rule in PRD §2 is restated here verbatim. The model is instructed
    to refuse before inventing facts, and to set
    ``alternative_routes=[]`` rather than fabricating one that is not
    grounded.
    """
    matter = ctx.matter
    template_block = "\n".join(
        f"- {tr.template_type.value}: {tr.relevance} — {tr.reason}"
        for tr in ctx.template_recommendations
    ) or "(template recommender returned no defaults; do not invent.)"
    hearing_block = "\n".join(
        f"- {h.hearing_on.isoformat()} {h.forum_name}: {h.purpose} ({h.status})"
        for h in ctx.hearings[:10]
    ) or "(no scheduled hearings on file.)"
    authority_block = "\n".join(
        f"[{i}] CITATION: {a.identifier}\n    EXCERPT: {a.text[:600]}"
        for i, a in enumerate(authorities, start=1)
    ) or "(no authorities retrieved)"

    # Round-2 P2 #6 — additional context blocks. When any block is
    # empty we explicitly say "none on file" so the model knows the
    # absence is data, not omission, and lists the gap under
    # `missing_facts` per the prompt rule.
    if ctx.attachment_snippets:
        attachment_block = "\n".join(
            f"- {snip.title}: {snip.excerpt}"
            for snip in ctx.attachment_snippets
        )
    else:
        attachment_block = (
            "(no matter attachments on file. If the strategy depends on "
            "uploaded orders / pleadings, list 'matter attachments' "
            "under `missing_facts`.)"
        )
    if ctx.statute_snippets:
        statute_lines: list[str] = []
        for snip in ctx.statute_snippets:
            label = (
                f" — {snip.section_label}"
                if snip.section_label
                else ""
            )
            text_block = (
                f"\n    TEXT: {snip.section_text}"
                if snip.section_text
                else ""
            )
            statute_lines.append(
                f"- [{snip.relevance}] {snip.statute_name} "
                f"s.{snip.section_number}{label}{text_block}"
            )
        statute_block = "\n".join(statute_lines)
    else:
        statute_block = (
            "(no linked statute references on file. If the strategy "
            "depends on a statute, list 'linked statutes' under "
            "`missing_facts`.)"
        )
    if ctx.cause_list_snippets:
        cause_lines: list[str] = []
        for entry in ctx.cause_list_snippets:
            bench_str = (
                f" before {entry.bench_name}"
                if entry.bench_name
                else ""
            )
            stage_str = f" — {entry.stage}" if entry.stage else ""
            cause_lines.append(
                f"- {entry.listing_date.isoformat()} {entry.forum_name}"
                f"{bench_str}{stage_str}"
            )
        cause_list_block = "\n".join(cause_lines)
    else:
        cause_list_block = (
            "(no recent cause-list entries on file. If the strategy "
            "depends on the next-listing bench composition, list "
            "'cause-list / next bench' under `missing_facts`.)"
        )

    # Round-3 P2 #R3-4 — court orders. Most-recent first, bounded
    # excerpts. When the matter is at a stage where an impugned order
    # is the natural anchor (HC / tribunal / SC) and zero orders are
    # on file, prompt the model to surface 'impugned order' under
    # missing_facts.
    if ctx.court_order_snippets:
        order_lines: list[str] = []
        for order in ctx.court_order_snippets:
            base = (
                f"- [{order.order_date}] {order.title} "
                f"(source: {order.source})\n"
                f"    SUMMARY: {order.summary}"
            )
            if order.order_text_excerpt:
                base += f"\n    EXCERPT: {order.order_text_excerpt}"
            order_lines.append(base)
        court_orders_block = "\n".join(order_lines)
    else:
        # Heuristic: at HC / SC / tribunal forums an impugned order is
        # almost always the anchor, so an empty corpus is a flag the
        # model should surface in missing_facts.
        forum_lower = (matter.forum_level or "").strip().lower()
        appellate_forums = {
            "high_court",
            "supreme_court",
            "tribunal",
            "high_court_division_bench",
            "high_court_single_bench",
        }
        if forum_lower in appellate_forums:
            court_orders_block = (
                "(no court orders synced for this matter. The current "
                "forum_level normally requires an impugned/interim "
                "order to anchor the strategy — list 'impugned order' "
                "under `missing_facts` and proceed cautiously.)"
            )
        else:
            court_orders_block = (
                "(no court orders synced for this matter. The current "
                "forum_level does not necessarily require one yet.)"
            )
    sc_clause = (
        "SUPREME COURT routes (SLP under Article 136, Article 132/133/134 "
        "appeals, review under Article 137, curative under the Rupa Ashok "
        "Hurra framework) MAY be recommended IF the facts plausibly "
        "support them and at least one supplied authority grounds the "
        "route. Otherwise omit SC routes entirely."
        if ctx.sc_route_plausible
        else "DO NOT recommend a Supreme Court route on this matter — the "
        "current forum level does not support escalation. Stay within the "
        "subordinate / high court / tribunal pathways."
    )

    system = (
        "You are CaseOps, a legal operations assistant for Indian law "
        "firms. You produce a CITATION-GROUNDED, LAWYER-REVIEWED "
        "litigation strategy. You must respond ONLY with JSON matching "
        "the schema described by the user.\n\n"
        "ABSOLUTE RULES (do not violate any):\n"
        " 1. Every route, remedy, limitation flag, forum, and "
        "    statutory basis you cite MUST be supported by at least "
        "    one authority from the RETRIEVED_AUTHORITIES list, "
        "    referenced VERBATIM by its bracket tag (e.g. [1], [2]) "
        "    plus the citation text from that line. This rule applies "
        "    to `recommended_route.supporting_citations`, "
        "    `alternative_routes[*].supporting_citations`, "
        "    `forum_sequence[*].supporting_citations`, "
        "    `limitation_flags[*].supporting_citations`, "
        "    `next_best_actions[*].supporting_citations` AND any "
        "    `risks[*].supporting_citations` you choose to emit. "
        "    Each `next_best_actions` entry MUST be the structured "
        "    object `{\"action\": str, \"supporting_citations\": [str]}` "
        "    — never a bare string. A bare string action is treated "
        "    as an UNVERIFIED legal claim by the post-processor.\n"
        " 2. NEVER use the phrases: 'perfect strategy', 'guaranteed', "
        "    'will win', 'will succeed', 'will be granted', 'certain "
        "    outcome', 'no lawyer needed', 'replace advocate', "
        "    'replace your lawyer'. The CaseOps post-processor "
        "    rejects any output containing these and the user sees a "
        "    refusal.\n"
        " 3. NEVER invent facts, dates, citations, party names, "
        "    forum names, or remedies. If you do not have a fact, "
        "    list it under `missing_facts`.\n"
        " 4. Strategy is about ROUTES, RISKS, PROCEDURAL POSTURE, "
        "    and EVIDENCE GAPS — NOT outcome prediction. Do NOT use "
        "    percentage-based outcome language ('70% chance', '40% "
        "    likelihood of success', 'odds of winning'), do NOT use "
        "    'likely to win' / 'likelihood of success' / 'probability "
        "    of success' / 'chance of success' phrasing, and do NOT "
        "    rank routes on outcome probability.\n"
        " 5. The output ALWAYS requires lawyer review — say so in "
        "    the disclaimer.\n"
        f" 6. {sc_clause}\n"
        " 7. The strategy must list at least ONE forum step in "
        "    `forum_sequence`. The first step is the CURRENT forum. "
        "    `forum_sequence` is for LEGAL FORUM TRANSITIONS ONLY "
        "    (e.g. trial court → first appeal, HC writ → SLP). EVERY "
        "    forum_sequence entry MUST carry at least one verified "
        "    `supporting_citations` entry; uncited forum steps are "
        "    dropped by the post-processor. Operational items "
        "    (filing fees, certified copy procurement, notice "
        "    service) belong in `next_best_actions`, not in "
        "    `forum_sequence`.\n"
        " 8. Recommended drafts MUST come from the supplied "
        "    AVAILABLE_TEMPLATES list. Do not invent template "
        "    identifiers. If a draft you would normally recommend is "
        "    not in the list, omit it rather than invent a slug.\n"
        " 9. Limitation flags must NEVER fabricate a deadline date. "
        "    If the limitation date depends on a fact you do not "
        "    have, leave `deadline_iso` null and explain in "
        "    `description` what fact is missing.\n"
        "10. For `risks`, emit `supporting_citations` ONLY when the "
        "    risk is a legal/procedural claim (parallel-proceedings "
        "    bar, counterclaim exposure under a specific section, "
        "    res-judicata risk). Pure operational risks (cost, "
        "    client withdrawal, reputational fallout) take an empty "
        "    `supporting_citations: []`.\n"
        "CITATION RULES (HARD): each `supporting_citations` entry "
        "MUST start with the bracket tag from RETRIEVED_AUTHORITIES "
        "(e.g. \"[1]\") followed by the citation text from that "
        "line. The verifier rejects citations without bracket tags. "
        "If no authority supports a route, set "
        "`supporting_citations: []`, lower `confidence` to 'low', "
        "and explain in `risk_notes`.\n"
    )
    user = (
        "Respond with json. Produce a litigation strategy.\n\n"
        f"MATTER_TITLE: {matter.title}\n"
        f"FORUM: {matter.forum_level or 'unknown'}\n"
        f"COURT: {matter.court_name or 'unknown'}\n"
        f"PRACTICE_AREA: {matter.practice_area or 'unknown'}\n"
        f"CLIENT: {matter.client_name or 'unknown'}\n"
        f"OPPOSING_PARTY: {matter.opposing_party or 'unknown'}\n"
        f"DESCRIPTION: {(matter.description or '').strip() or 'none'}\n"
        f"STAGE: {matter.status or 'unknown'}\n\n"
        f"HEARINGS_RECENT_AND_UPCOMING:\n{hearing_block}\n\n"
        f"MATTER_ATTACHMENTS (recent uploads, bounded excerpts):\n"
        f"{attachment_block}\n\n"
        f"LINKED_STATUTE_REFERENCES (matter-specific statutes; "
        f"relevance is 'cited' / 'opposing' / 'context'):\n"
        f"{statute_block}\n\n"
        f"CAUSE_LIST_NEXT_BENCH (recent listings):\n{cause_list_block}\n\n"
        f"RECENT_COURT_ORDERS (most-recent impugned/interim orders, "
        f"bounded excerpts):\n{court_orders_block}\n\n"
        f"AVAILABLE_TEMPLATES (use only these template_type slugs in "
        f"recommended_drafts):\n{_available_templates_block()}\n\n"
        f"TEMPLATE_RECOMMENDER_DEFAULTS (starting suggestions, you may "
        f"override or add):\n{template_block}\n\n"
        f"RETRIEVED_AUTHORITIES:\n{authority_block}\n\n"
        "SCHEMA: {\"title\": str, \"current_posture\": str, "
        "\"recommended_route\": {\"label\": str, \"rationale\": str, "
        "\"confidence\": \"low|medium|high\", \"availability\": "
        "\"available|uncertain|not_available\", "
        "\"supporting_citations\": [str], \"risk_notes\": str | null}, "
        "\"alternative_routes\": [<recommended_route>], "
        "\"forum_sequence\": [{\"forum_level\": "
        "\"lower_court|tribunal|high_court_single_bench|high_court_division_bench"
        "|supreme_court|supreme_court_review|supreme_court_curative|arbitration"
        "|executive|other\", \"stage_label\": str, \"forum_name\": "
        "str | null, \"rationale\": str, \"statutory_basis\": [str], "
        "\"expected_filings\": [str], \"supporting_citations\": [str]}], "
        "\"limitation_flags\": "
        "[{\"label\": str, \"description\": str, \"statutory_basis\": "
        "str | null, \"deadline_iso\": str | null, \"severity\": "
        "\"info|warning|critical\", \"supporting_citations\": [str]}], "
        "\"required_documents\": [str], "
        "\"missing_facts\": [str], \"risks\": [{\"label\": str, "
        "\"description\": str, \"severity\": \"low|medium|high\", "
        "\"mitigation\": str | null, \"supporting_citations\": [str]}], "
        "\"next_best_actions\": [{\"action\": str, "
        "\"supporting_citations\": [str]}], "
        "\"rationale\": str, \"confidence\": \"low|medium|high\", "
        "\"next_action\": str | null, \"assumptions\": [str], "
        "\"disclaimer\": str}"
    )
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def _available_templates_block() -> str:
    """Render the full template registry as a tagged list. The model
    is instructed to pick only from this list — anything outside is
    rejected post-generation."""
    return "\n".join(
        f"- {schema.template_type}: {schema.display_name}"
        for schema in list_template_schemas()
    )


def _prompt_hash(messages: list[LLMMessage]) -> str:
    joined = "\n".join(f"{m.role}::{m.content}" for m in messages)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _cap_confidence(current: str, verified_count: int) -> str:
    current = current if current in CONFIDENCE_LEVELS else "low"
    if verified_count == 0:
        return "low"
    if verified_count < 2 and current == "high":
        return "medium"
    return current


def _write_model_run(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
    purpose: str,
    completion: LLMCompletion,
    prompt_hash: str,
    status_label: str = "ok",
    error: str | None = None,
) -> ModelRun:
    run = ModelRun(
        company_id=context.company.id,
        matter_id=matter_id,
        actor_membership_id=context.membership.id,
        purpose=purpose,
        provider=completion.provider,
        model=completion.model,
        prompt_hash=prompt_hash,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
        status=status_label,
        error=error,
    )
    session.add(run)
    session.flush()
    return run


def _load_matter(session: Session, *, context: SessionContext, matter_id: str) -> Matter:
    from caseops_api.services.matter_access import assert_access

    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if not matter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _rerank_by_outcome_bias(session: Session, results, *, matter: Matter) -> list:
    if not results:
        return results
    practice = (matter.practice_area or "").lower()
    bias = _OUTCOME_BIAS.get(practice)
    if not bias:
        return list(results)

    doc_ids = [r.authority_document_id for r in results]
    rows = session.execute(
        select(AuthorityDocument.id, AuthorityDocument.outcome_label).where(
            AuthorityDocument.id.in_(doc_ids)
        )
    ).all()
    outcome_by_id = {row.id: (row.outcome_label or "").lower() for row in rows}
    preferred = bias["preferred"]
    against = bias["against"]

    def score(result) -> int:
        label = outcome_by_id.get(result.authority_document_id, "")
        if any(token in label for token in preferred):
            return 1
        if any(token in label for token in against):
            return -1
        return 0

    return sorted(results, key=score, reverse=True)


def _gather_authorities(
    session: Session,
    *,
    query: str,
    forum_level: str | None,
    matter: Matter | None = None,
    limit: int = 6,
) -> list[RetrievedAuthority]:
    filter_forum = forum_level if forum_level == "supreme_court" else None
    fetch_limit = max(limit * 3, limit)
    try:
        results = search_authority_catalog(
            session,
            query=query,
            limit=fetch_limit,
            forum_level=filter_forum,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Authority retrieval failed - refusing to proceed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authority retrieval is temporarily unavailable. Strategy "
                "generation is refused until retrieval recovers."
            ),
        ) from exc

    if matter is not None:
        results = _rerank_by_outcome_bias(session, results, matter=matter)

    picked: list[RetrievedAuthority] = []
    for result in results[:limit]:
        identifier = result.case_reference or result.title or result.authority_document_id
        text = "\n".join(
            part for part in [result.title, result.summary, result.snippet] if part
        )
        aliases: list[str] = []
        if result.title and result.title != identifier:
            aliases.append(result.title)
        if result.source_reference and result.source_reference != identifier:
            aliases.append(result.source_reference)
        picked.append(
            RetrievedAuthority(
                identifier=identifier,
                text=text,
                aliases=tuple(dict.fromkeys(aliases)),
            )
        )
    return picked


def _build_retrieval_query(matter: Matter, rec_type: str) -> str:
    parts = [matter.title]
    if matter.practice_area:
        parts.append(matter.practice_area)
    if matter.description:
        parts.append(matter.description[:400])
    if rec_type == "litigation_strategy":
        parts.append(
            "litigation strategy escalation forum sequence "
            "appeal special leave petition Article 136 review "
            "Article 137 curative limitation condonation interim "
            "stay status quo"
        )
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------
# Citation verification — same shape the recommendations service
# uses, but applied to recommended_route + alternative_routes.
# ---------------------------------------------------------------


def _verify_routes(
    options: list[_StrategyOption], retrieved: list[RetrievedAuthority]
) -> tuple[list[_StrategyOption], VerificationReport]:
    """Verify citations across recommended_route + alternatives.

    Mirrors ``recommendations._filter_and_verify_options`` so a strategy
    route's ``supporting_citations`` end up canonicalised and
    verified-only — the UI displays the canonical SourceDoc identifier,
    not the raw model paraphrase / bracket prefix.
    """
    sources = [
        SourceDoc(identifier=a.identifier, text=a.text, aliases=a.aliases)
        for a in retrieved
    ]
    claims: list[Claim] = []
    citation_to_options: dict[str, list[int]] = {}
    for idx, option in enumerate(options):
        for citation in option.supporting_citations:
            claims.append(
                Claim(citation=citation, proposition=option.rationale[:400])
            )
            citation_to_options.setdefault(citation, []).append(idx)
    report = verify_citations(claims, sources)
    canonical_for: dict[str, str] = {}
    for check in report.checks:
        if check.verified and check.source is not None:
            canonical_for[check.claim.citation] = check.source.identifier
    cleaned: list[_StrategyOption] = []
    for option in options:
        seen: set[str] = set()
        per_option: list[str] = []
        for citation in option.supporting_citations:
            canonical = canonical_for.get(citation)
            if canonical and canonical not in seen:
                per_option.append(canonical)
                seen.add(canonical)
        cleaned.append(
            option.model_copy(update={"supporting_citations": per_option})
        )
    return cleaned, report


def _verify_item_citations(
    raw_citations: list[str], retrieved: list[RetrievedAuthority]
) -> list[str]:
    """Round-2 P1 #4 helper. Run a list of raw citation strings through
    the verifier and return only the canonical, verified survivors
    (deduplicated, in original order)."""
    if not raw_citations:
        return []
    sources = [
        SourceDoc(identifier=a.identifier, text=a.text, aliases=a.aliases)
        for a in retrieved
    ]
    claims = [
        Claim(citation=citation, proposition="strategy item citation")
        for citation in raw_citations
    ]
    report = verify_citations(claims, sources)
    canonical_for: dict[str, str] = {}
    for check in report.checks:
        if check.verified and check.source is not None:
            canonical_for[check.claim.citation] = check.source.identifier
    seen: set[str] = set()
    verified: list[str] = []
    for citation in raw_citations:
        canonical = canonical_for.get(citation)
        if canonical and canonical not in seen:
            verified.append(canonical)
            seen.add(canonical)
    return verified


# ---------------------------------------------------------------
# Recommended-draft panel hydration.
#
# The LLM picks template_type slugs from AVAILABLE_TEMPLATES; we
# enrich each with the registry's display_name and an availability
# flag based on the matter's forum_level. The frontend disables /
# greys out unavailable drafts but still shows the entry so the
# strategy stays explicit about what would be needed if the matter
# were at the right stage.
# ---------------------------------------------------------------


def _build_recommended_drafts(
    *,
    matter: Matter,
    template_slugs: list[str],
) -> list[RecommendedDraft]:
    """Build the recommended-drafts panel for the persisted strategy.

    Round-5 follow-up #2 (2026-05-03 prod incident on PR #7): the
    panel was empty for sparse-retrieval matters because the LLM
    emitted no ``expected_filings`` (or only registry-unknown slugs).
    The deterministic ``template_recommender`` matrix already encodes
    a sensible default pack per (forum_level, practice_area) — fall
    back to it when the LLM-derived slug list is empty so the
    Strategy tab always offers at least the universal accompaniments
    (vakalatnama / affidavit / SC pack at SC stage). The fallback path
    is logged so operations can correlate with thin-retrieval matters.
    """
    schemas = {s.template_type: s for s in list_template_schemas()}
    forum = (matter.forum_level or "").strip().lower()
    practice_area = getattr(matter, "practice_area", None)

    # Dedupe input slugs while preserving order.
    seen: set[str] = set()
    ordered_slugs: list[str] = []
    for slug in template_slugs:
        if slug not in seen:
            ordered_slugs.append(slug)
            seen.add(slug)

    # Filter to slugs the registry recognises BEFORE slicing the
    # render list. Two prior bugs were caught in PR #8 review:
    #
    #   (1) 2026-05-03 first cut: fallback slugs were APPENDED after
    #   the unknown LLM slugs, and ``ordered_slugs[:12]`` then sliced
    #   the unknowns first, dropping the fallback. Fixed by replacing
    #   on the all-unknown path.
    #
    #   (2) 2026-05-03 second review: the all-unknown gate
    #   (``known_count == 0``) didn't catch the MIXED case — 16 fake
    #   slugs followed by ``vakalatnama`` (one known) gave
    #   ``known_count == 1`` so the fallback didn't fire, and the
    #   ``[:12]`` slice still consumed the first 12 unknowns and left
    #   the panel empty.
    #
    # Final shape: filter ``ordered_slugs`` down to known templates
    # FIRST, then either fall back when the filtered list is empty
    # or slice it to the panel cap. The unknown LLM slugs are dead
    # weight in every case (they would have failed ``schemas.get``
    # at render time), so dropping them up front is correct AND
    # makes the [:12] slice meaningful.
    known_slugs = [s for s in ordered_slugs if s in schemas]
    if not known_slugs:
        try:
            fallback = recommend_templates(
                forum_level=matter.forum_level or "",
                practice_area=practice_area,
            )
        except Exception:
            logger.exception(
                "litigation_strategy: template_recommender fallback "
                "failed for matter %s; recommended_drafts will be empty",
                getattr(matter, "id", "?"),
            )
            fallback = []
        fallback_seen: set[str] = set()
        for tr in fallback:
            slug = (
                tr.template_type.value
                if hasattr(tr.template_type, "value")
                else str(tr.template_type)
            )
            if slug not in fallback_seen and slug in schemas:
                known_slugs.append(slug)
                fallback_seen.add(slug)
        if known_slugs:
            logger.info(
                "litigation_strategy: LLM emitted no recognised template "
                "slugs for matter %s — using template_recommender fallback "
                "(%d slugs)",
                getattr(matter, "id", "?"),
                len(known_slugs),
            )

    drafts: list[RecommendedDraft] = []
    for slug in known_slugs[:12]:  # bound the panel
        schema = schemas[slug]  # already validated above; can't miss
        available, reason = _is_template_available(slug, forum)
        drafts.append(
            RecommendedDraft(
                template_type=slug,
                display_name=schema.display_name,
                purpose=(schema.summary or schema.display_name)[:600],
                available=available,
                reason_unavailable=None if available else reason,
            )
        )
    return drafts


# Templates that are SC-only (or SC-overwhelmingly) get an explicit
# unavailable flag for matters not at the SC stage. This keeps the
# strategy honest: we acknowledge the SC route in `forum_sequence`
# but make it obvious the user can't draft an SLP today on a lower-
# court matter.
_SC_ONLY_TEMPLATES = frozenset(
    {
        DraftTemplateType.SPECIAL_LEAVE_PETITION.value
        if hasattr(DraftTemplateType, "SPECIAL_LEAVE_PETITION")
        else "special_leave_petition",
        "supreme_court_appeal",
        "review_petition",
        "curative_petition",
        "transfer_petition",
        "synopsis_list_of_dates",
        "filing_index_checklist",
        "exemption_application",
    }
)


def _is_template_available(
    template_slug: str, forum_level: str
) -> tuple[bool, str]:
    # Round-2 fix (P1 #2, 2026-05-03): the SC-allowlist must mirror
    # ``_assemble_context.sc_route_plausible``. Appellate tribunals
    # (NCLAT, AFT, APTEL, etc.) appeal to the Supreme Court under
    # Article 136 (and statute-specific provisions), so a tribunal
    # matter that just received SC-escalation strategy MUST also be
    # able to draft the SLP / synopsis / list-of-dates pack. Excluding
    # ``tribunal`` here was the inconsistency that left tribunal users
    # with the SC route in their forum_sequence but no draft buttons.
    if template_slug in _SC_ONLY_TEMPLATES and forum_level not in {
        "supreme_court",
        "high_court",
        "high_court_single_bench",
        "high_court_division_bench",
        "tribunal",
    }:
        return (
            False,
            "This draft is for the Supreme Court / High Court / appellate "
            "tribunal stage. Move the matter to the appropriate forum first.",
        )
    return True, ""


# ---------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------


def generate_litigation_strategy(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    provider: LLMProvider | None = None,
) -> Recommendation:
    """Generate a citation-grounded litigation strategy for ``matter_id``.

    Pipeline:
      1. Load the matter (tenant-scoped, matter-access-checked).
      2. Assemble strategy context (hearings + template recommender).
      3. Retrieve grounding authorities.
      4. Build the prompt and call the LLM (single retry on
         malformed JSON, same-provider).
      5. Verify citations on every route. Fail closed (422) on zero
         verified.
      6. Scan EVERY user-visible string for forbidden phrases.
      7. Persist as a Recommendation row + strategy_payload_json,
         always ``review_required=True``.
      8. Audit row.
    """
    matter = _load_matter(session, context=context, matter_id=matter_id)

    # Per-statement timeout to keep retrieval from blowing the
    # request budget on a busy day. Same pattern as
    # ``services/recommendations.generate_recommendation``.
    from sqlalchemy import text as _sa_text

    try:
        session.execute(_sa_text("SET LOCAL statement_timeout = '60000'"))
    except Exception:  # noqa: BLE001
        pass

    retrieved = _gather_authorities(
        session,
        query=_build_retrieval_query(matter, "litigation_strategy"),
        forum_level=matter.forum_level,
        matter=matter,
        limit=8,
    )

    ctx = _assemble_context(session, matter)
    messages = _build_prompt(ctx=ctx, authorities=retrieved)
    prompt_hash = _prompt_hash(messages)

    llm = provider or build_provider(purpose=PURPOSE_RECOMMENDATIONS)
    settings = get_settings()
    call_context = LLMCallContext(
        tenant_id=context.company.id,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        purpose="recommendation:litigation_strategy",
    )

    def _invoke(active: LLMProvider) -> tuple[_LLMStrategyResponse, LLMCompletion]:
        return generate_structured(
            active,
            session=session,
            schema=_LLMStrategyResponse,
            messages=messages,
            context=call_context,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_output_tokens_recommendations,
        )

    try:
        parsed, completion = _invoke(llm)
    except LLMResponseFormatError as exc:
        logger.warning(
            "litigation_strategy: primary LLM %s returned malformed JSON; "
            "retrying once. detail=%s",
            getattr(llm, "model", "<unknown>"),
            str(exc)[:300],
        )
        try:
            parsed, completion = _invoke(llm)
        except LLMProviderError as retry_exc:
            raise provider_failure_http_exception(
                noun="strategy",
                exc=retry_exc,
            ) from retry_exc
    except LLMProviderError as exc:
        raise provider_failure_http_exception(
            noun="strategy",
            exc=exc,
        ) from exc

    # Verify citations on the recommended route + alternatives.
    all_routes = [parsed.recommended_route, *parsed.alternative_routes]
    cleaned_routes, _report = _verify_routes(all_routes, retrieved)
    cleaned_recommended = cleaned_routes[0]
    # Round-3 fix (P1 #R3-1, 2026-05-03): drop uncited alternative
    # routes entirely. Persisting an alternative with
    # ``supporting_citations=[]`` and ``available=...`` would surface an
    # uncited route to the lawyer as an available legal strategy. The
    # only fail-closed answer is: if an alternative has no verified
    # citation, it is not a "supported alternative" — drop it.
    cleaned_alternatives = [
        alt for alt in cleaned_routes[1:] if alt.supporting_citations
    ]
    primary_verified = len(cleaned_recommended.supporting_citations)
    total_verified = primary_verified + sum(
        len(r.supporting_citations) for r in cleaned_alternatives
    )

    # Round-2 fix (P1 #1, 2026-05-03): citation verification is
    # PER-ROUTE on the primary, not summed across alternatives. A
    # primary route with zero verified citations cannot ride on an
    # alternative's authority — the persisted recommendation would
    # surface a top-of-screen route the corpus does not support. Fail
    # closed when the primary has zero, even if alternatives carry one.
    if primary_verified == 0:
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose="recommendation:litigation_strategy",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="rejected_primary_route_uncited",
            error=(
                "Primary recommended route has zero verified citations; "
                "alternatives carried "
                f"{total_verified - primary_verified}."
            ),
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "The recommended primary route has no verified authority "
                "to stand on. CaseOps refuses strategies whose primary "
                "route is uncited even if an alternative carries a "
                "citation. Widen the matter description so retrieval "
                "covers the primary route, or accept an alternative-only "
                "answer by re-running with that posture."
            ),
            headers={"X-Model-Run-Id": run.id},
        )

    if total_verified == 0:
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose="recommendation:litigation_strategy",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="rejected_no_verified_citations",
            error="Strategy citations all failed verification.",
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "No grounding authorities were verified for this strategy. "
                "Strategy outputs require at least one verified citation. "
                "Add more detail to the matter description (forum, "
                "practice area, key facts) or check corpus coverage and "
                "retry."
            ),
            headers={"X-Model-Run-Id": run.id},
        )

    # Build the persisted strategy payload. We re-coerce the LLM's
    # narrow ``_StrategyOption`` shape into the full
    # ``LitigationStrategyPayload`` model so the persisted JSON is
    # validated against the contract that the API returns.

    # Round-2 fix (P1 #4): also verify citations on forum_sequence,
    # limitation_flags, risks, and next_best_actions. Items whose
    # citations don't verify keep their narrative content (so the user
    # still sees the substantive strategy) but are flagged
    # ``unverified=True`` AND have their citations stripped from the
    # persisted payload. The frontend renders an unverified badge so
    # the partner reviewer knows what to vet.
    forum_steps_payload = _build_forum_steps(parsed.forum_sequence, retrieved)

    # Round-5 R5 #1 (2026-05-03): all-forum-steps-dropped fail-closed.
    # Round-4 tightened ``_build_forum_steps`` to drop every step that
    # lacks a verified citation. That can leave ``forum_steps_payload``
    # empty when the model emitted a ladder but no step's citation
    # verified. The Pydantic model requires ``forum_sequence``
    # min_length=1, so falling through would raise a ValidationError
    # → 502 schema-malformed path. That's the wrong shape: the data
    # IS valid, the model just produced no grounded forum step.
    # Fail-closed with a clean 422 + X-Model-Run-Id header so the
    # partner-reviewer (and the audit ledger) see this as a
    # legal-grounding refusal, not a server bug.
    if parsed.forum_sequence and not forum_steps_payload:
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose="recommendation:litigation_strategy",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="rejected_no_verified_forum_steps",
            error=(
                "every forum_sequence step the model emitted was "
                "dropped during citation verification; no grounded "
                "forum ladder remains to persist"
            ),
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "The strategy could not be persisted because no forum "
                "step in the proposed ladder carried a citation that "
                "verified against the retrieved authorities. Please "
                "retry the strategy; if the problem persists, widen "
                "the matter description so the retriever has more "
                "context to work with."
            ),
            headers={"X-Model-Run-Id": run.id},
        )

    # Round-4 R4 #3 (2026-05-03): forum_sequence coherence.
    # The system prompt promises that forum_sequence[0] is the
    # CURRENT forum / posture. After the per-step citation filter,
    # the original first step may have been dropped. A ladder that
    # silently begins at the second forum (e.g. "HC dropped, ladder
    # now starts at SC") is incoherent — it tells the lawyer the
    # matter is already at the SC when it is not. Fail closed: if
    # the first step survived filtering OR every step in the model
    # output was dropped, the ladder is internally consistent. If
    # the first step was dropped while a later step survived, refuse
    # the strategy with HTTP 422.
    if (
        parsed.forum_sequence
        and forum_steps_payload
        and not _first_step_survived(parsed.forum_sequence, forum_steps_payload)
    ):
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose="recommendation:litigation_strategy",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="incoherent_forum_sequence",
            error=(
                "first forum_sequence step was dropped during citation "
                "verification while later steps survived; ladder no "
                "longer starts at the current forum"
            ),
        )
        session.commit()
        # Round-5: include X-Model-Run-Id and use the non-deprecated
        # status constant (was HTTP_422_UNPROCESSABLE_ENTITY).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Strategy ladder lost its starting forum after citation "
                "verification. The first forum step must always be the "
                "current matter forum; please retry the strategy and "
                "verify the recommended starting point."
            ),
            headers={"X-Model-Run-Id": run.id},
        )

    limitation_flags_payload = _build_limitation_flags(
        parsed.limitation_flags, retrieved
    )
    risks_payload = _build_risks(parsed.risks, retrieved)
    next_best_actions_payload = _build_next_best_actions(
        parsed.next_best_actions, retrieved
    )

    try:
        payload = LitigationStrategyPayload(
            current_posture=parsed.current_posture,
            recommended_route=StrategyRoute(
                label=cleaned_recommended.label,
                rationale=cleaned_recommended.rationale,
                confidence=_normalise_confidence(cleaned_recommended.confidence),
                availability=_normalise_availability(
                    cleaned_recommended.availability
                ),
                supporting_citations=cleaned_recommended.supporting_citations,
                risk_notes=cleaned_recommended.risk_notes,
            ),
            alternative_routes=[
                StrategyRoute(
                    label=alt.label,
                    rationale=alt.rationale,
                    confidence=_normalise_confidence(alt.confidence),
                    availability=_normalise_availability(alt.availability),
                    supporting_citations=alt.supporting_citations,
                    risk_notes=alt.risk_notes,
                )
                for alt in cleaned_alternatives
            ],
            forum_sequence=forum_steps_payload,
            limitation_flags=limitation_flags_payload,
            required_documents=parsed.required_documents,
            missing_facts=parsed.missing_facts,
            risks=risks_payload,
            next_best_actions=next_best_actions_payload,
            disclaimer=parsed.disclaimer,
            recommended_drafts=_build_recommended_drafts(
                matter=matter,
                template_slugs=_extract_template_slugs(parsed),
            ),
        )
    except ValidationError as exc:
        # The model returned shape-mismatched data. Fail closed —
        # never persist a half-validated payload.
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose="recommendation:litigation_strategy",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="rejected_schema_violation",
            error=str(exc)[:500],
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Strategy generation produced a malformed structured "
                "response. Please retry — if this persists, widen the "
                "matter description so the model has more context."
            ),
            headers={"X-Model-Run-Id": run.id},
        ) from exc

    # Forbidden-language sweep. We concatenate every string field on
    # the persisted payload and reject the whole strategy if anything
    # forbidden slipped through. Easier than per-field whitelisting
    # and matches the structural test in
    # tests/test_litigation_strategy.py.
    haystack = json.dumps(payload.model_dump(), default=str)
    try:
        assert_no_forbidden_phrases(haystack)
    except ValueError as exc:
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose="recommendation:litigation_strategy",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="rejected_forbidden_phrase",
            error=str(exc)[:500],
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Strategy generation produced disallowed outcome-promising "
                "language and was refused. Please retry."
            ),
            headers={"X-Model-Run-Id": run.id},
        ) from exc

    # Round-2 P2 #5: scan the narrative fields specifically for
    # outcome-PROBABILITY phrasing ('70% chance', 'likelihood of
    # success'). The forbidden-phrase scanner above catches outcome
    # GUARANTEES; this layer catches probability framing. Scoped to
    # specific fields so a statute name like 'Limitation Act' or an
    # excerpt with the word 'likely' inside it doesn't false-positive.
    try:
        assert_no_probability_language(payload)
    except ValueError as exc:
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose="recommendation:litigation_strategy",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="rejected_probability_language",
            error=str(exc)[:500],
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Strategy generation used outcome-probability language "
                "('likely to win', 'X% chance of success', etc.) and "
                "was refused. Strategy outputs are about routes, risks, "
                "procedural posture, and evidence gaps — not outcome "
                "probability. Please retry."
            ),
            headers={"X-Model-Run-Id": run.id},
        ) from exc

    # Persist the Recommendation row. The ``options`` collection
    # surfaces the recommended route + alternatives so the existing
    # /recommendations API + decision flow keep working.
    confidence = _cap_confidence(parsed.confidence, total_verified)
    run = _write_model_run(
        session,
        context=context,
        matter_id=matter.id,
        purpose="recommendation:litigation_strategy",
        completion=completion,
        prompt_hash=prompt_hash,
    )

    recommendation = Recommendation(
        company_id=context.company.id,
        matter_id=matter.id,
        created_by_membership_id=context.membership.id,
        type="litigation_strategy",
        title=parsed.title[:400],
        rationale=parsed.rationale,
        primary_option_index=0,
        assumptions_json=json.dumps(parsed.assumptions[:20]),
        missing_facts_json=json.dumps(parsed.missing_facts[:20]),
        confidence=confidence,
        review_required=True,
        next_action=parsed.next_action,
        model_run_id=run.id,
        retrieved_authorities_json=json.dumps(
            [a.identifier for a in retrieved]
        ),
        strategy_payload_json=payload.model_dump_json(),
    )
    # Recommended route → option rank 0; alternatives → 1, 2, ...
    for rank, route in enumerate([cleaned_recommended, *cleaned_alternatives]):
        recommendation.options.append(
            RecommendationOption(
                rank=rank,
                label=route.label[:400],
                rationale=route.rationale,
                confidence=_cap_confidence(
                    _normalise_confidence(route.confidence),
                    len(route.supporting_citations),
                ),
                supporting_citations_json=json.dumps(route.supporting_citations),
                risk_notes=route.risk_notes,
            )
        )
    session.add(recommendation)
    session.flush()
    record_from_context(
        session,
        context,
        action="recommendation.generated",
        target_type="recommendation",
        target_id=recommendation.id,
        matter_id=matter.id,
        metadata={
            "type": "litigation_strategy",
            "forum_steps": len(payload.forum_sequence),
            "alternative_routes": len(payload.alternative_routes),
            "verified_citations": total_verified,
            "recommended_drafts": len(payload.recommended_drafts),
            "confidence": confidence,
        },
    )
    session.commit()
    refreshed = session.scalar(
        select(Recommendation)
        .options(selectinload(Recommendation.options))
        .where(Recommendation.id == recommendation.id)
    )
    assert refreshed is not None
    return refreshed


def _normalise_confidence(value: str | None) -> str:
    """Squash an LLM-emitted confidence string into the supported set
    so a typo from the model doesn't blow pydantic validation."""
    if not value:
        return "low"
    cleaned = value.strip().lower()
    if cleaned not in CONFIDENCE_LEVELS:
        return "low"
    return cleaned


def _normalise_availability(value: str | None) -> str:
    if not value:
        return "uncertain"
    cleaned = value.strip().lower()
    if cleaned in {"available", "uncertain", "not_available"}:
        return cleaned
    return "uncertain"


def _extract_template_slugs(parsed: _LLMStrategyResponse) -> list[str]:
    """Walk the LLM response for template slugs.

    The strategy prompt asks the model to populate
    ``forum_sequence[*].expected_filings`` with template slugs. We
    union those with any direct ``recommended_drafts`` field the model
    chose to include (some models emit it; the field is optional in
    our schema). Order is preserved so the user sees the SLP first
    when escalation is the recommended route.
    """
    slugs: list[str] = []
    seen: set[str] = set()
    for step in parsed.forum_sequence:
        if not isinstance(step, dict):
            continue
        for slug in step.get("expected_filings", []) or []:
            if not isinstance(slug, str):
                continue
            if slug in seen:
                continue
            slugs.append(slug)
            seen.add(slug)
    return slugs


def _first_step_survived(
    parsed_steps: list[dict], surviving: list[ForumStep]
) -> bool:
    """Round-4 R4 #3 — ladder coherence.

    Returns True iff the first entry in the LLM-emitted ``forum_sequence``
    survived the per-step citation filter in ``_build_forum_steps``. The
    rule: a strategy ladder must begin at the current forum / posture;
    if filtering kept later steps but dropped the first, we have a
    'starts mid-route' ladder and the caller fails closed.

    Identity is approximate (we don't have stable IDs on LLM steps): we
    consider the first step preserved iff a ``ForumStep`` exists in
    ``surviving`` whose ``stage_label`` and ``forum_level`` match the
    first parsed entry. That's a tight-enough match for the use case —
    the ladder is short (<=10 steps) and the LLM rarely emits identical
    (label, forum_level) pairs.
    """
    if not parsed_steps:
        return True
    first = parsed_steps[0]
    if not isinstance(first, dict):
        return True
    first_label = str(first.get("stage_label", "Stage"))
    first_forum = first.get("forum_level", "other")
    return any(
        s.stage_label == first_label and s.forum_level == first_forum
        for s in surviving
    )


def _build_forum_steps(
    raw_steps: list[dict], retrieved: list[RetrievedAuthority]
) -> list[ForumStep]:
    """Round-2 P1 #4 + Round-3 P2 #R3-3. Coerce LLM forum_sequence dicts
    into ForumStep models with verified citations and ``unverified``
    flags.

    Round-3 fix (P2 #R3-3, 2026-05-03): a forum step that emits
    ``statutory_basis`` is making a legal claim about jurisdictional or
    statutory authority. An unverified legal claim about *which
    forum has jurisdiction* is too risky to surface.

    Round-3 fix (P2 #R3-3): drop forum steps where the LLM emitted a
    non-empty ``statutory_basis`` but no citation survived verification.

    Round-4 fix (R4 #1, 2026-05-03): the Round-3 gate was too narrow.
    A model can omit ``statutory_basis`` while still expressing a
    legal claim via ``stage_label``, ``rationale``, ``forum_level``,
    or ``expected_filings`` ("SLP if HC declines" with no statute
    field populated). The amber-badge UX is too weak for those — they
    still appear in the main escalation ladder.

    The rule now: ``forum_sequence`` is for **legal forum transitions
    only**, and every legal forum transition must carry at least one
    verified citation. Drop ANY forum step with zero verified
    citations. Operational/administrative actions (filing fees,
    certified-copy procurement, etc.) belong in ``next_best_actions``,
    not in the forum ladder; the system prompt also instructs the
    model to route them there.
    """
    out: list[ForumStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        raw_citations = raw.get("supporting_citations") or []
        if not isinstance(raw_citations, list):
            raw_citations = []
        verified = _verify_item_citations(
            [c for c in raw_citations if isinstance(c, str)], retrieved
        )
        statutory_basis = [
            s for s in (raw.get("statutory_basis") or []) if isinstance(s, str)
        ][:10]
        # Round-4 R4 #1: every forum_sequence entry is a legal forum
        # transition; if no citation survives, drop it. This is
        # fail-closed regardless of whether the LLM populated
        # ``statutory_basis`` (the Round-3 gate let through "SLP if
        # HC declines"-style steps that omitted the field).
        if len(verified) == 0:
            continue
        try:
            step = ForumStep(
                forum_level=raw.get("forum_level", "other"),
                stage_label=str(raw.get("stage_label", "Stage")),
                forum_name=raw.get("forum_name"),
                rationale=str(raw.get("rationale", "")),
                statutory_basis=statutory_basis,
                expected_filings=[
                    s for s in (raw.get("expected_filings") or []) if isinstance(s, str)
                ][:10],
                supporting_citations=verified,
                unverified=False,
            )
        except ValidationError:
            # Skip a malformed step rather than fail the whole strategy
            # — the surviving steps still represent a usable plan.
            continue
        out.append(step)
    return out


def _build_limitation_flags(
    raw_flags: list[dict], retrieved: list[RetrievedAuthority]
) -> list[LimitationFlag]:
    """Round-2 P1 #4 + Round-3 P2 #R3-3. Limitation flags claim a
    statutory deadline.

    Round-3 fix (P2 #R3-3, 2026-05-03): an unverified limitation
    deadline is the most dangerous output a planner can produce. A
    lawyer-facing UI rendering an "Unverified" badge next to a
    deadline date still anchors on the date. Drop unverified
    limitation flags entirely (option (a) from the brief).
    """
    out: list[LimitationFlag] = []
    for raw in raw_flags:
        if not isinstance(raw, dict):
            continue
        raw_citations = raw.get("supporting_citations") or []
        if not isinstance(raw_citations, list):
            raw_citations = []
        verified = _verify_item_citations(
            [c for c in raw_citations if isinstance(c, str)], retrieved
        )
        # Round-3 P2 #R3-3: fail-closed on unverified limitation flags.
        # No citation survived → don't show the flag at all.
        if not verified:
            continue
        try:
            flag = LimitationFlag(
                label=str(raw.get("label", "Limitation")),
                description=str(raw.get("description", "")),
                statutory_basis=raw.get("statutory_basis"),
                deadline_iso=raw.get("deadline_iso"),
                severity=raw.get("severity", "info"),
                supporting_citations=verified,
                unverified=False,
            )
        except ValidationError:
            continue
        out.append(flag)
    return out


def _build_risks(
    raw_risks: list[dict], retrieved: list[RetrievedAuthority]
) -> list[StrategyRisk]:
    """Round-2 P1 #4. Risks are the most heterogeneous of the four —
    some are factual (cost, client withdrawal, reputation) and need no
    citation; others are legal/procedural claims and do.

    Convention: if the LLM emitted ``supporting_citations`` for a risk,
    treat it as a legal claim and verify. If at least one survives,
    keep those + ``unverified=False``. If none survive, keep narrative
    + flag ``unverified=True`` (the LLM TRIED to ground a legal claim
    and missed). Empty ``supporting_citations`` is the factual-risk
    path — keep ``unverified=False``.
    """
    out: list[StrategyRisk] = []
    for raw in raw_risks:
        if not isinstance(raw, dict):
            continue
        raw_citations = raw.get("supporting_citations") or []
        if not isinstance(raw_citations, list):
            raw_citations = []
        cleaned_raw = [c for c in raw_citations if isinstance(c, str)]
        verified = _verify_item_citations(cleaned_raw, retrieved)
        # Only flag unverified when the LLM emitted citations and none verified.
        unverified_flag = len(cleaned_raw) > 0 and len(verified) == 0
        try:
            risk = StrategyRisk(
                label=str(raw.get("label", "Risk")),
                description=str(raw.get("description", "")),
                severity=raw.get("severity", "medium"),
                mitigation=raw.get("mitigation"),
                supporting_citations=verified,
                unverified=unverified_flag,
            )
        except ValidationError:
            continue
        out.append(risk)
    return out


def _build_next_best_actions(
    raw_actions: list[str | dict],
    retrieved: list[RetrievedAuthority],
) -> list[NextBestAction]:
    """Round-2 P1 #4 + Round-3 P1 #R3-2. Convert the LLM next_best_actions
    into structured ``NextBestAction`` records with verified citations.

    Accepts either ``[str]`` (legacy) or ``[{"action": str,
    "supporting_citations": [str]}]``.

    Round-3 fix (P1 #R3-2, 2026-05-03): a bare-string entry like ``"File
    SLP within 60 days"`` is a legal/procedural claim with no citation
    attached. Persisting it as ``unverified=False`` made the LLM's
    free-text legal claims look corpus-grounded. Coerce bare strings to
    ``unverified=True`` so the frontend's amber Unverified badge appears
    and the partner-reviewer knows to vet the claim. The structured
    form (``{"action": ..., "supporting_citations": [...]}``) is the
    schema we instruct the model to emit; it follows the same rule as
    forum steps — at least one citation must survive verification,
    otherwise ``unverified=True``.
    """
    out: list[NextBestAction] = []
    for raw in raw_actions:
        if isinstance(raw, str):
            # Round-3 P1 #R3-2: bare-string actions bypass citation
            # verification entirely. Mark them unverified so the UX is
            # honest about what the corpus did NOT support.
            try:
                out.append(
                    NextBestAction(
                        action=raw,
                        supporting_citations=[],
                        unverified=True,
                    )
                )
            except ValidationError:
                continue
            continue
        if not isinstance(raw, dict):
            continue
        action_text = str(raw.get("action", "")).strip()
        if not action_text:
            continue
        raw_citations = raw.get("supporting_citations") or []
        if not isinstance(raw_citations, list):
            raw_citations = []
        cleaned_raw = [c for c in raw_citations if isinstance(c, str)]
        verified = _verify_item_citations(cleaned_raw, retrieved)
        # Round-4 R4 #2 (2026-05-03): a structured action with empty
        # ``supporting_citations`` is a citation-bypass — the model
        # ships a legal/procedural claim ("File SLP within 60 days")
        # but offers no source the verifier can check. Round-3's
        # rule-of-thumb (empty cleaned_raw == operational action
        # stays verified=True) was too generous; in practice the
        # model frequently emits time-bound legal advice in this
        # shape. Conservative rule: ANY structured action with zero
        # verified citations is unverified, so the partner-reviewer
        # sees the amber Unverified badge regardless of whether the
        # LLM emitted citations or not. Lawyers can still mark the
        # action as a factual / operational reminder if it is one.
        unverified_flag = len(verified) == 0
        try:
            out.append(
                NextBestAction(
                    action=action_text,
                    supporting_citations=verified,
                    unverified=unverified_flag,
                )
            )
        except ValidationError:
            continue
    return out


__all__ = [
    "generate_litigation_strategy",
]
