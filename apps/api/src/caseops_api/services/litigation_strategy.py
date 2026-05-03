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
    Matter,
    MatterHearing,
    Recommendation,
    RecommendationOption,
)
from caseops_api.schemas.drafting_templates import (
    DraftTemplateType,
    list_template_schemas,
)
from caseops_api.schemas.litigation_strategy import (
    LitigationStrategyPayload,
    RecommendedDraft,
    StrategyRoute,
    assert_no_forbidden_phrases,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.citations import (
    Claim,
    SourceDoc,
    VerificationReport,
    verify_citations,
)
from caseops_api.services.identity import SessionContext
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
from caseops_api.services.recommendations import (
    CONFIDENCE_LEVELS,
    RetrievedAuthority,
    _build_retrieval_query,
    _cap_confidence,
    _gather_authorities,
    _load_matter,
    _write_model_run,
)
from caseops_api.services.template_recommender import (
    TemplateRecommendation,
    recommend_templates,
)

logger = logging.getLogger(__name__)


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
    next_best_actions: list[str] = Field(default_factory=list, max_length=10)
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
class _StrategyContext:
    matter: Matter
    hearings: list[MatterHearing]
    template_recommendations: list[TemplateRecommendation]
    sc_route_plausible: bool


def _assemble_context(session: Session, matter: Matter) -> _StrategyContext:
    """Pull the matter context the strategy planner needs.

    We fetch the upcoming + past hearings to surface stage context,
    and the template recommender's matrix output as a starting point
    for the recommended-drafts panel. The model can override / add to
    this list, but starting from the canonical recommender keeps the
    SC pack consistent across matters.
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
        "    plus the citation text from that line.\n"
        " 2. NEVER use the phrases: 'perfect strategy', 'guaranteed', "
        "    'will win', 'will succeed', 'will be granted', 'certain "
        "    outcome', 'no lawyer needed', 'replace advocate', "
        "    'replace your lawyer'. The CaseOps post-processor "
        "    rejects any output containing these and the user sees a "
        "    refusal.\n"
        " 3. NEVER invent facts, dates, citations, party names, "
        "    forum names, or remedies. If you do not have a fact, "
        "    list it under `missing_facts`.\n"
        " 4. NEVER promise an outcome. Strategy is about ROUTES + "
        "    PROBABILITIES, not guarantees.\n"
        " 5. The output ALWAYS requires lawyer review — say so in "
        "    the disclaimer.\n"
        f" 6. {sc_clause}\n"
        " 7. The strategy must list at least ONE forum step in "
        "    `forum_sequence`. The first step is the CURRENT forum.\n"
        " 8. Recommended drafts MUST come from the supplied "
        "    AVAILABLE_TEMPLATES list. Do not invent template "
        "    identifiers. If a draft you would normally recommend is "
        "    not in the list, omit it rather than invent a slug.\n"
        " 9. Limitation flags must NEVER fabricate a deadline date. "
        "    If the limitation date depends on a fact you do not "
        "    have, leave `deadline_iso` null and explain in "
        "    `description` what fact is missing.\n"
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
        "\"expected_filings\": [str]}], \"limitation_flags\": "
        "[{\"label\": str, \"description\": str, \"statutory_basis\": "
        "str | null, \"deadline_iso\": str | null, \"severity\": "
        "\"info|warning|critical\"}], \"required_documents\": [str], "
        "\"missing_facts\": [str], \"risks\": [{\"label\": str, "
        "\"description\": str, \"severity\": \"low|medium|high\", "
        "\"mitigation\": str | null}], \"next_best_actions\": [str], "
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
    schemas = {s.template_type: s for s in list_template_schemas()}
    forum = (matter.forum_level or "").strip().lower()
    drafts: list[RecommendedDraft] = []
    for slug in template_slugs[:12]:  # bound the panel
        schema = schemas.get(slug)
        if schema is None:
            continue  # silently drop slugs the registry doesn't know
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
    if template_slug in _SC_ONLY_TEMPLATES and forum_level not in {
        "supreme_court",
        "high_court",
        "high_court_single_bench",
        "high_court_division_bench",
    }:
        return (
            False,
            "This draft is for the Supreme Court / High Court appellate "
            "stage. Move the matter to the appropriate forum first.",
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
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"Could not generate the strategy: "
                    f"{type(retry_exc).__name__}: {retry_exc}. Please "
                    f"retry in a minute."
                ),
            ) from retry_exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Could not generate the strategy: "
                f"{type(exc).__name__}: {exc}. Please retry in a minute."
            ),
        ) from exc

    # Verify citations on the recommended route + alternatives.
    all_routes = [parsed.recommended_route, *parsed.alternative_routes]
    cleaned_routes, _report = _verify_routes(all_routes, retrieved)
    cleaned_recommended = cleaned_routes[0]
    cleaned_alternatives = cleaned_routes[1:]
    primary_verified = len(cleaned_recommended.supporting_citations)
    total_verified = sum(
        len(r.supporting_citations) for r in cleaned_routes
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
            forum_sequence=parsed.forum_sequence,  # validated by pydantic
            limitation_flags=parsed.limitation_flags,
            required_documents=parsed.required_documents,
            missing_facts=parsed.missing_facts,
            risks=parsed.risks,
            next_best_actions=parsed.next_best_actions,
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


__all__ = [
    "generate_litigation_strategy",
]
