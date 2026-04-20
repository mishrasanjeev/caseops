"""Recommendation pipeline.

Pipeline (PRD §11.3):

    matter context
    → retrieval (authorities + internal precedents)
    → prompt assembly
    → LLM generation (structured JSON)
    → citation verification (fail-closed)
    → persistence with review_required

The service is intentionally narrow for v1 — two recommendation types land
here: ``forum`` (which bench/route to pursue) and ``authority`` (which
precedents best support the matter). Both share the pipeline and the
guardrails.

Guardrails that ship with v1:

- Every option must cite at least one authority that survives verification,
  unless the option is an explicit "do nothing / settle" fallback.
- The recommendation is always created with ``review_required=True`` — no
  output is treated as a final answer (PRD §6.3, §11.5).
- Confidence is capped by the number of verified citations: zero verified
  citations caps at ``low``.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Matter,
    ModelRun,
    Recommendation,
    RecommendationDecision,
    RecommendationOption,
)
from caseops_api.services.authorities import search_authority_catalog
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
    LLMResponseFormatError,
    build_provider,
    generate_structured,
)

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"forum", "authority", "remedy", "next_best_action"}
CONFIDENCE_LEVELS = ("low", "medium", "high")


class _LLMOption(BaseModel):
    label: str = Field(min_length=2, max_length=400)
    rationale: str = Field(min_length=2, max_length=4000)
    confidence: str = Field(default="low")
    supporting_citations: list[str] = Field(default_factory=list)
    risk_notes: str | None = None


class _LLMResponse(BaseModel):
    title: str = Field(min_length=2, max_length=400)
    options: list[_LLMOption] = Field(min_length=1, max_length=5)
    primary_recommendation_label: str | None = None
    rationale: str = Field(min_length=2, max_length=6000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    missing_facts: list[str] = Field(default_factory=list, max_length=20)
    confidence: str = "low"
    next_action: str | None = None


@dataclass
class RetrievedAuthority:
    identifier: str
    text: str
    aliases: tuple[str, ...] = ()


def _gather_authorities(
    session: Session, *, query: str, forum_level: str | None, limit: int = 6
) -> list[RetrievedAuthority]:
    # Precedent cascades: a High Court matter can (and typically should) rely
    # on Supreme Court precedent. Only filter by forum when the matter is at
    # the Supreme Court itself — otherwise broaden the search.
    filter_forum = forum_level if forum_level == "supreme_court" else None
    # Do NOT catch-and-swallow here. An embedding provider outage, a
    # pgvector index corruption, or a DB timeout is a 503, not a
    # legitimate empty retrieval. The earlier fail-open collapsed both
    # signals into results=[] — which then paid the LLM to produce a
    # confident refusal that masked the real outage. Propagate unknown
    # failures so the caller sees a 503 and the LLM is never called.
    try:
        results = search_authority_catalog(
            session,
            query=query,
            limit=limit,
            forum_level=filter_forum,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Authority retrieval failed — refusing to proceed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authority retrieval is temporarily unavailable. "
                "Recommendation generation is refused until retrieval recovers."
            ),
        ) from exc

    picked: list[RetrievedAuthority] = []
    for result in results[:limit]:
        identifier = (
            result.case_reference or result.title or result.authority_document_id
        )
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


_TYPE_FRAMING: dict[str, str] = {
    "forum": (
        "Recommend which forum (court, bench, jurisdiction) the client "
        "should pursue. Each option is a specific forum with the "
        "procedural or strategic reason it fits."
    ),
    "authority": (
        "Recommend which authorities (judgments, statutes) best support "
        "the client's position. Each option is a specific authority or "
        "small cluster of authorities with the legal proposition they "
        "establish."
    ),
    "remedy": (
        "Recommend which reliefs the client can credibly seek. Each "
        "option is a distinct remedy (injunction, declaration, damages "
        "quantum, specific performance, rescission, costs) with the "
        "legal basis for claiming it on these facts."
    ),
    "next_best_action": (
        "Recommend the immediate next procedural step on this matter. "
        "Each option is a concrete action — file an application, serve "
        "notice, seek interlocutory relief, settle, wait for a specific "
        "listing — with why it is the highest-leverage move right now."
    ),
}


def _build_prompt(
    *,
    rec_type: str,
    matter: Matter,
    authorities: list[RetrievedAuthority],
) -> list[LLMMessage]:
    framing = _TYPE_FRAMING.get(rec_type, _TYPE_FRAMING["authority"])
    system = (
        "You are CaseOps, a legal operations assistant for Indian law firms and "
        "corporate legal teams. You must respond only with JSON matching the "
        "schema described by the user. Every option must cite at least one "
        "supporting authority from the provided list. If no authority in the "
        "list supports the option, say so in missing_facts and reduce "
        "confidence; do not invent citations.\n\n"
        f"TASK: {framing}"
    )
    authority_block = "\n".join(
        f"- CITATION: {a.identifier}\n  EXCERPT: {a.text[:600]}"
        for a in authorities
    ) or "(no authorities retrieved)"
    user = (
        "Respond with json. Produce a CaseOps recommendation object.\n\n"
        f"RECOMMENDATION_TYPE: {rec_type}\n"
        f"MATTER_TITLE: {matter.title}\n"
        f"FORUM: {matter.forum_level or 'unknown'}\n"
        f"COURT: {matter.court_name or 'unknown'}\n"
        f"CLIENT: {matter.client_name or 'unknown'}\n"
        f"OPPOSING_PARTY: {matter.opposing_party or 'unknown'}\n"
        f"PRACTICE_AREA: {matter.practice_area or 'unknown'}\n"
        f"DESCRIPTION: {(matter.description or '').strip() or 'none'}\n\n"
        "RETRIEVED_AUTHORITIES:\n"
        f"{authority_block}\n\n"
        "SCHEMA: {\"title\": str, \"options\": [{"
        "\"label\": str, \"rationale\": str, \"confidence\": "
        "\"low|medium|high\", \"supporting_citations\": [str], "
        "\"risk_notes\": str | null}], \"primary_recommendation_label\": str, "
        "\"rationale\": str, \"assumptions\": [str], \"missing_facts\": [str], "
        "\"confidence\": \"low|medium|high\", \"next_action\": str | null}"
    )
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def _cap_confidence(current: str, verified_count: int) -> str:
    current = current if current in CONFIDENCE_LEVELS else "low"
    if verified_count == 0:
        return "low"
    if verified_count < 2 and current == "high":
        return "medium"
    return current


def _prompt_hash(messages: list[LLMMessage]) -> str:
    joined = "\n".join(f"{m.role}::{m.content}" for m in messages)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


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
            Matter.id == matter_id, Matter.company_id == context.company.id
        )
    )
    if not matter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _validate_type(rec_type: str) -> str:
    if rec_type not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Recommendation type {rec_type!r} is not supported in v1. "
                f"Supported types: {sorted(SUPPORTED_TYPES)}"
            ),
        )
    return rec_type


def _filter_and_verify_options(
    options: list[_LLMOption], retrieved: list[RetrievedAuthority]
) -> tuple[list[_LLMOption], VerificationReport]:
    sources = [
        SourceDoc(identifier=a.identifier, text=a.text, aliases=a.aliases)
        for a in retrieved
    ]
    # Flatten all citations across options for one verification pass.
    # A single citation can appear under multiple options — the
    # attribution mapping must therefore be one-to-many, else the last
    # option to cite it silently wins and earlier options appear
    # unsupported even though they claimed the same authority.
    claims: list[Claim] = []
    citation_to_options: dict[str, list[int]] = {}
    for idx, option in enumerate(options):
        for citation in option.supporting_citations:
            claims.append(
                Claim(citation=citation, proposition=option.rationale[:400])
            )
            citation_to_options.setdefault(citation, []).append(idx)
    report = verify_citations(claims, sources)
    # Keep only citations that verified, preserving per-option order by
    # re-walking the original option citations and filtering.
    verified_citations = {
        check.claim.citation for check in report.checks if check.verified
    }
    per_option_verified: dict[int, list[str]] = {i: [] for i in range(len(options))}
    for idx, option in enumerate(options):
        seen: set[str] = set()
        for citation in option.supporting_citations:
            if citation in verified_citations and citation not in seen:
                per_option_verified[idx].append(citation)
                seen.add(citation)
    cleaned: list[_LLMOption] = []
    for idx, option in enumerate(options):
        cleaned.append(
            option.model_copy(
                update={
                    "supporting_citations": per_option_verified.get(idx, [])
                }
            )
        )
    return cleaned, report


def _pick_primary(options: list[_LLMOption], preferred_label: str | None) -> int:
    if preferred_label:
        for idx, option in enumerate(options):
            if option.label.strip().lower() == preferred_label.strip().lower():
                return idx
    for idx, option in enumerate(options):
        if option.supporting_citations:
            return idx
    return 0


def generate_recommendation(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    rec_type: str,
    provider: LLMProvider | None = None,
) -> Recommendation:
    _validate_type(rec_type)
    matter = _load_matter(session, context=context, matter_id=matter_id)
    retrieved = _gather_authorities(
        session,
        query=_build_retrieval_query(matter, rec_type),
        forum_level=matter.forum_level,
    )

    llm = provider or build_provider(purpose=PURPOSE_RECOMMENDATIONS)
    messages = _build_prompt(rec_type=rec_type, matter=matter, authorities=retrieved)
    prompt_hash = _prompt_hash(messages)

    settings = get_settings()
    try:
        parsed, completion = generate_structured(
            llm,
            session=session,
            schema=_LLMResponse,
            messages=messages,
            context=LLMCallContext(
                tenant_id=context.company.id,
                matter_id=matter.id,
                purpose=f"recommendation:{rec_type}",
            ),
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_output_tokens,
        )
    except LLMResponseFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    cleaned_options, report = _filter_and_verify_options(parsed.options, retrieved)
    total_verified_citations = sum(
        len(opt.supporting_citations) for opt in cleaned_options
    )
    # PRD §6.1 / §17.4: legal recommendations must be citation-grounded
    # or refused. Two fail paths reach zero verified citations — either
    # retrieval was empty (no authorities in scope) or retrieval hit
    # candidates the model ignored / fabricated. Both cases fail closed.
    if total_verified_citations == 0:
        if retrieved:
            error_msg = "All citations failed verification."
            detail = (
                "The model did not produce any verifiable citations. "
                "Refusing to surface this recommendation."
            )
        else:
            error_msg = "Retrieval returned no authorities."
            detail = (
                "No authorities were retrieved for this matter. Refusing to "
                "surface an ungrounded recommendation; widen the matter "
                "description or expand the corpus before retrying."
            )
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose=f"recommendation:{rec_type}",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="rejected_no_verified_citations",
            error=error_msg,
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{detail} model_run_id={run.id}",
        )

    confidence = _cap_confidence(parsed.confidence, total_verified_citations)
    run = _write_model_run(
        session,
        context=context,
        matter_id=matter.id,
        purpose=f"recommendation:{rec_type}",
        completion=completion,
        prompt_hash=prompt_hash,
    )

    primary_idx = _pick_primary(cleaned_options, parsed.primary_recommendation_label)
    recommendation = Recommendation(
        company_id=context.company.id,
        matter_id=matter.id,
        created_by_membership_id=context.membership.id,
        type=rec_type,
        title=parsed.title[:400],
        rationale=parsed.rationale,
        primary_option_index=primary_idx,
        assumptions_json=json.dumps(parsed.assumptions[:20]),
        missing_facts_json=json.dumps(parsed.missing_facts[:20]),
        confidence=confidence,
        review_required=True,
        next_action=parsed.next_action,
        model_run_id=run.id,
    )
    for rank, option in enumerate(cleaned_options):
        recommendation.options.append(
            RecommendationOption(
                rank=rank,
                label=option.label[:400],
                rationale=option.rationale,
                confidence=_cap_confidence(
                    option.confidence, len(option.supporting_citations)
                ),
                supporting_citations_json=json.dumps(option.supporting_citations),
                risk_notes=option.risk_notes,
            )
        )
    session.add(recommendation)
    session.flush()
    from caseops_api.services.audit import record_from_context

    record_from_context(
        session,
        context,
        action="recommendation.generated",
        target_type="recommendation",
        target_id=recommendation.id,
        matter_id=matter.id,
        metadata={
            "type": rec_type,
            "option_count": len(cleaned_options),
            "verified_citations": total_verified_citations,
            "confidence": confidence,
        },
    )
    session.commit()
    session.refresh(recommendation)
    # Eager-load options for the response.
    recommendation = session.scalar(
        select(Recommendation)
        .options(selectinload(Recommendation.options))
        .where(Recommendation.id == recommendation.id)
    )
    assert recommendation is not None
    return recommendation


def _build_retrieval_query(matter: Matter, rec_type: str) -> str:
    parts = [matter.title]
    if matter.practice_area:
        parts.append(matter.practice_area)
    if matter.description:
        parts.append(matter.description[:400])
    # Sprint 9 BG-023: per-type query expansion so retrieval pulls the
    # authorities most useful for each recommendation kind. Forum asks
    # "which bench", remedy asks "what reliefs are available", and
    # next_best_action asks "what procedural step unblocks this".
    if rec_type == "forum":
        parts.append("jurisdiction forum choice of court bench")
    elif rec_type == "remedy":
        parts.append(
            "relief reliefs remedy damages injunction specific performance "
            "quantum compensation costs"
        )
    elif rec_type == "next_best_action":
        parts.append(
            "procedural step next hearing filing deadline notice "
            "interlocutory application adjournment"
        )
    return " ".join(p for p in parts if p)


def list_matter_recommendations(
    session: Session, *, context: SessionContext, matter_id: str
) -> list[Recommendation]:
    _load_matter(session, context=context, matter_id=matter_id)
    return list(
        session.scalars(
            select(Recommendation)
            .options(
                selectinload(Recommendation.options),
                selectinload(Recommendation.decisions),
            )
            .where(
                Recommendation.company_id == context.company.id,
                Recommendation.matter_id == matter_id,
            )
            .order_by(Recommendation.created_at.desc())
        )
    )


def _load_recommendation(
    session: Session, *, context: SessionContext, recommendation_id: str
) -> Recommendation:
    recommendation = session.scalar(
        select(Recommendation)
        .options(
            selectinload(Recommendation.options),
            selectinload(Recommendation.decisions),
        )
        .where(
            Recommendation.id == recommendation_id,
            Recommendation.company_id == context.company.id,
        )
    )
    if not recommendation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found.",
        )
    return recommendation


def record_recommendation_decision(
    session: Session,
    *,
    context: SessionContext,
    recommendation_id: str,
    decision: str,
    selected_option_index: int | None,
    notes: str | None,
) -> Recommendation:
    if decision not in {"accepted", "rejected", "edited", "deferred"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be one of: accepted, rejected, edited, deferred.",
        )
    recommendation = _load_recommendation(
        session, context=context, recommendation_id=recommendation_id
    )
    if selected_option_index is not None and (
        selected_option_index < 0 or selected_option_index >= len(recommendation.options)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="selected_option_index is out of range.",
        )
    recommendation.decisions.append(
        RecommendationDecision(
            actor_membership_id=context.membership.id,
            decision=decision,
            selected_option_index=selected_option_index,
            notes=notes,
        )
    )
    if decision == "accepted":
        recommendation.status = "accepted"
    elif decision == "rejected":
        recommendation.status = "rejected"
    elif decision == "edited":
        recommendation.status = "edited"
    else:
        recommendation.status = "deferred"
    session.flush()
    from caseops_api.services.audit import record_from_context

    record_from_context(
        session,
        context,
        action="recommendation.decided",
        target_type="recommendation",
        target_id=recommendation.id,
        matter_id=recommendation.matter_id,
        metadata={
            "decision": decision,
            "selected_option_index": selected_option_index,
            "status": recommendation.status,
        },
    )
    session.commit()
    refreshed = session.scalar(
        select(Recommendation)
        .options(
            selectinload(Recommendation.options),
            selectinload(Recommendation.decisions),
        )
        .where(Recommendation.id == recommendation.id)
    )
    assert refreshed is not None
    return refreshed


def parse_assumptions(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data if isinstance(item, str)]


def parse_citations(raw: str) -> list[str]:
    return parse_assumptions(raw)


__all__ = [
    "SUPPORTED_TYPES",
    "generate_recommendation",
    "list_matter_recommendations",
    "parse_assumptions",
    "parse_citations",
    "record_recommendation_decision",
]
