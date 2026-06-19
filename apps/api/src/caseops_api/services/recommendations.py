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
import re
import time
from dataclasses import dataclass

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditResult,
    AuthorityCitation,
    AuthorityDocument,
    Judge,
    Matter,
    MatterActivity,
    MatterAttachment,
    MatterAttachmentChunk,
    MatterCauseListEntry,
    MatterCourtOrder,
    MatterHearing,
    MatterStatuteReference,
    ModelRun,
    Recommendation,
    RecommendationDecision,
    RecommendationOption,
    Statute,
    StatuteSection,
)
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

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {
    "forum",
    "authority",
    "remedy",
    "next_best_action",
    # MOD-LSE-1 (2026-05-03). Strategy generation runs through a
    # dedicated service (``services/litigation_strategy.py``) but the
    # type lands here so the supported-type validator + listing API
    # stay unified. ``generate_recommendation`` dispatches to the
    # strategy service when ``rec_type == 'litigation_strategy'``.
    "litigation_strategy",
}
CONFIDENCE_LEVELS = ("low", "medium", "high")
SUPPORTED_OBJECTIVE_CONTEXTS = {
    "litigation_strategy",
    "settlement_strategy",
    "compliance_risk",
    "contract_risk",
    "case_preparation",
    "appeal_strategy",
    "custom_goal",
}


@dataclass(frozen=True)
class RecommendationObjective:
    context: str | None = None
    custom_goal: str | None = None
    custom_goal_source: str | None = None

    @property
    def audit_context(self) -> str:
        return self.context or "default_matter_status"

    def custom_goal_metadata(self) -> dict[str, object]:
        if not self.custom_goal:
            return {"present": False}
        return {
            "present": True,
            "sha256": hashlib.sha256(self.custom_goal.encode("utf-8")).hexdigest(),
            "length": len(self.custom_goal),
            "source": self.custom_goal_source or "custom_goal",
        }


_OBJECTIVE_FRAMING: dict[str, str] = {
    "litigation_strategy": (
        "Frame the recommendation around litigation posture, procedural options, "
        "source-backed risks, and lawyer-review next steps."
    ),
    "settlement_strategy": (
        "Frame the recommendation around settlement posture, negotiation levers, "
        "missing information, and risks for lawyer review. Do not estimate odds "
        "or settlement probability."
    ),
    "compliance_risk": (
        "Frame the recommendation around compliance gaps, regulatory exposure, "
        "evidence needs, and mitigations for lawyer review."
    ),
    "contract_risk": (
        "Frame the recommendation around contractual risk, clause posture, "
        "document gaps, and possible drafting or negotiation actions for lawyer review."
    ),
    "case_preparation": (
        "Frame the recommendation around case-preparation tasks, source readiness, "
        "missing facts, witness/document gaps, and hearing-preparation actions."
    ),
    "appeal_strategy": (
        "Frame the recommendation around appeal readiness, grounds completeness, "
        "limitation or procedural gaps, and source-backed options for lawyer review. "
        "Do not predict appeal success."
    ),
    "custom_goal": (
        "Frame the recommendation around the approved custom lawyer-review goal "
        "while preserving the same source-grounding and safety boundaries."
    ),
}

_OBJECTIVE_RETRIEVAL_HINTS: dict[str, str] = {
    "litigation_strategy": "litigation strategy procedural posture evidence gaps",
    "settlement_strategy": "settlement negotiation compromise consent terms risk",
    "compliance_risk": "compliance regulatory obligation penalty mitigation",
    "contract_risk": "contract clause breach indemnity termination liability",
    "case_preparation": "case preparation evidence witness document readiness",
    "appeal_strategy": "appeal grounds limitation review appellate procedure",
    "custom_goal": "custom lawyer review objective source-backed recommendation",
}

_UNSAFE_CUSTOM_GOAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "outcome_prediction",
        re.compile(
            r"\b(success probability|win probability|loss probability|odds of "
            r"(?:winning|losing)|chance of (?:winning|success)|predict(?:ed)? "
            r"outcome|will win|will lose|guarante(?:e|ed|es))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "judge_shopping",
        re.compile(
            r"\b(best judge|most suitable judge|best bench|most suitable bench|"
            r"best court|judge shopping|bench shopping|judge reputation|"
            r"favo[u]?rable judge|judge likes|judge dislikes)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "illegal_or_unethical",
        re.compile(
            r"\b(bribe|fabricate evidence|destroy evidence|hide evidence|"
            r"mislead (?:the )?court|perjury|false affidavit|forge|forged|"
            r"backdate|tamper)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "legal_advice_as_final_instruction",
        re.compile(
            r"\b(give legal advice|legal advice:|advise (?:me|us|the client) to|"
            r"tell (?:me|us|the client) (?:exactly )?what to do)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "emotion_biometric_psychological",
        re.compile(
            r"\b(emotion|emotional|biometric|psychological|mental[- ]health|"
            r"voice scoring|lie detection|stress analysis|personality score)\b",
            re.IGNORECASE,
        ),
    ),
)

_UNSAFE_OUTPUT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    _UNSAFE_CUSTOM_GOAL_PATTERNS[0],
    _UNSAFE_CUSTOM_GOAL_PATTERNS[1],
    _UNSAFE_CUSTOM_GOAL_PATTERNS[4],
    (
        "legal_advice_as_final_instruction",
        re.compile(
            r"\b(legal advice:|(?:i\s+)?advise (?:you|the client) to|"
            r"you should (?:file|settle|withdraw|appeal|sue))\b",
            re.IGNORECASE,
        ),
    ),
)

_LOG_CONTROL_CHARS = re.compile(r"[\r\n\t]+")


def _safe_log_value(value: object, *, limit: int = 160) -> str:
    return _LOG_CONTROL_CHARS.sub(" ", str(value))[:limit]


class _LLMOption(BaseModel):
    # Bounds widened 2026-04-28 (BUG-035) — Haiku + GPT-5.1 routinely
    # generate longer rationales and 6+ options on richly-described
    # matters; the prior tight bounds tripped pydantic ValidationError
    # and surfaced as 502s with no actionable detail.
    label: str = Field(min_length=2, max_length=600)
    rationale: str = Field(min_length=2, max_length=10000)
    confidence: str = Field(default="low")
    supporting_citations: list[str] = Field(default_factory=list)
    risk_notes: str | None = None


class _LLMAnalysis(BaseModel):
    recommendation: str = Field(min_length=1, max_length=5000)
    risk_analysis: list[str] = Field(default_factory=list, max_length=12)
    legal_impact: list[str] = Field(default_factory=list, max_length=12)
    suggested_actions: list[str] = Field(default_factory=list, max_length=12)
    confidence_score: str = "low"
    confidence_explanation: str = Field(default="", max_length=2000)


class _LLMResponse(BaseModel):
    title: str = Field(min_length=2, max_length=600)
    options: list[_LLMOption] = Field(min_length=1, max_length=10)
    primary_recommendation_label: str | None = None
    rationale: str = Field(min_length=2, max_length=15000)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    missing_facts: list[str] = Field(default_factory=list, max_length=50)
    confidence: str = "low"
    next_action: str | None = None
    analysis: _LLMAnalysis | None = None


@dataclass
class RetrievedAuthority:
    identifier: str
    text: str
    aliases: tuple[str, ...] = ()
    rerank_explanation: str | None = None


@dataclass(frozen=True)
class BenchCitationRerankTrace:
    status: str
    policy_enabled: bool
    sample_size: int = 0
    recall_at_10: str = "not-measured"
    explanation: str = ""
    candidate_authority_ids: tuple[str, ...] = ()
    boosted_authority_ids: tuple[str, ...] = ()
    source_authority_ids: tuple[str, ...] = ()
    per_authority_explanations: dict[str, str] | None = None

    def metadata(self) -> dict[str, object]:
        return {
            "status": self.status,
            "policy_enabled": self.policy_enabled,
            "sample_size_band": f"n={self.sample_size}, recall@10={self.recall_at_10}",
            "candidate_authority_ids": list(self.candidate_authority_ids),
            "boosted_authority_ids": list(self.boosted_authority_ids),
            "source_authority_ids": list(self.source_authority_ids),
        }


# Per the 2026-04-20 bias directive
# (memory/feedback_user_bias_in_recommendations.md) CaseOps recommendations
# should favor authorities whose outcome_label supports the user's
# typical position. For most practice areas the user in CaseOps is the
# lawyer for the moving party (accused seeking bail, petitioner
# seeking relief, plaintiff seeking decree). So "preferred" outcomes
# here are the grant / allow / decree side.
#
# The dictionary is keyed by the lowercased `Matter.practice_area`.
# Values:
#   preferred — case-insensitive substrings we want at the top
#   against   — case-insensitive substrings we want demoted
# Anything not listed falls back to neutral (no bias applied).
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

_BENCH_CITATION_MIN_SAMPLE = 5
_BENCH_RERANK_PURPOSE = "authority_rerank:bench_citation_relevance"
_BENCH_RERANK_MODEL = "bench-citation-relevance-rerank-v1"
_APPROVING_TREATMENTS = {"followed"}


def _normalize_bench_token(value: str | None) -> str:
    if not value:
        return ""
    value = value.lower()
    value = re.sub(r"\bhon'?ble\b", " ", value)
    value = re.sub(r"\b(?:mr|ms|mrs|dr)\.?\b", " ", value)
    value = re.sub(r"\b(?:chief\s+justice|justice|j)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _json_bench_values(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    values: list[str] = []
    for item in parsed:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            for key in ("judge_id", "full_name", "matched_alias", "name"):
                val = item.get(key)
                if isinstance(val, str) and val.strip():
                    values.append(val)
    return values


def _matter_bench_terms(session: Session, matter: Matter) -> set[str]:
    values: list[str] = []
    hearings = session.scalars(
        select(MatterHearing)
        .where(MatterHearing.matter_id == matter.id)
        .where(MatterHearing.judge_name.is_not(None))
        .order_by(MatterHearing.hearing_on.asc())
    ).all()
    values.extend(h.judge_name or "" for h in hearings)

    listings = session.scalars(
        select(MatterCauseListEntry)
        .where(MatterCauseListEntry.matter_id == matter.id)
        .order_by(MatterCauseListEntry.listing_date.desc())
    ).all()
    judge_ids: set[str] = set()
    for listing in listings:
        values.append(listing.bench_name or "")
        for val in _json_bench_values(listing.judges_json):
            values.append(val)
            if len(val) == 36:
                judge_ids.add(val)
    if judge_ids:
        judges = session.scalars(select(Judge).where(Judge.id.in_(judge_ids))).all()
        values.extend(j.full_name for j in judges)

    return {
        normalized
        for normalized in (_normalize_bench_token(v) for v in values)
        if normalized
    }


def _authority_matches_bench(doc: AuthorityDocument, bench_terms: set[str]) -> bool:
    values = [doc.bench_name or ""]
    values.extend(_json_bench_values(doc.judges_json))
    for value in values:
        normalized = _normalize_bench_token(value)
        if not normalized:
            continue
        for term in bench_terms:
            if term == normalized or term in normalized or normalized in term:
                return True
    return False


def _approving_bench_citation_sources(
    session: Session,
    *,
    candidate_ids: list[str],
    bench_terms: set[str],
) -> dict[str, list[str]]:
    if not candidate_ids:
        return {}
    rows = session.execute(
        select(AuthorityCitation, AuthorityDocument)
        .join(
            AuthorityDocument,
            AuthorityCitation.source_authority_document_id == AuthorityDocument.id,
        )
        .where(AuthorityCitation.cited_authority_document_id.in_(candidate_ids))
        .where(AuthorityCitation.treatment.in_(_APPROVING_TREATMENTS))
    ).all()
    out: dict[str, list[str]] = {}
    for citation, source_doc in rows:
        if not _authority_matches_bench(source_doc, bench_terms):
            continue
        cited_id = citation.cited_authority_document_id
        if cited_id:
            out.setdefault(cited_id, []).append(source_doc.id)
    return out


def _apply_bench_citation_rerank(
    session: Session,
    results,
    *,
    context: SessionContext,
    matter: Matter,
) -> tuple[list, BenchCitationRerankTrace]:
    candidate_ids = [r.authority_document_id for r in results]
    from caseops_api.services.tenant_ai_policy import resolve_tenant_policy

    policy = resolve_tenant_policy(session, company_id=context.company.id)
    if not policy.predictive_bench_strategy_enabled:
        return list(results), BenchCitationRerankTrace(
            status="policy_disabled",
            policy_enabled=False,
            candidate_authority_ids=tuple(candidate_ids),
            explanation=(
                "Tenant bench-citation rerank policy is disabled; "
                "general relevance order kept."
            ),
        )

    if not results:
        return [], BenchCitationRerankTrace(
            status="no_candidates",
            policy_enabled=True,
            explanation="No retrieved authorities were available for bench rerank.",
        )

    bench_terms = _matter_bench_terms(session, matter)
    if not bench_terms:
        return list(results), BenchCitationRerankTrace(
            status="no_bench_context",
            policy_enabled=True,
            candidate_authority_ids=tuple(candidate_ids),
            explanation="No hearing or cause-list bench was assigned to this matter.",
        )

    docs = session.scalars(
        select(AuthorityDocument).where(AuthorityDocument.id.in_(candidate_ids))
    ).all()
    doc_by_id = {doc.id: doc for doc in docs}
    authored_ids = {
        doc_id
        for doc_id, doc in doc_by_id.items()
        if _authority_matches_bench(doc, bench_terms)
    }
    approving_sources = _approving_bench_citation_sources(
        session,
        candidate_ids=candidate_ids,
        bench_terms=bench_terms,
    )
    source_ids = set(authored_ids)
    for ids in approving_sources.values():
        source_ids.update(ids)
    sample_size = len(source_ids)
    sample_band = f"n={sample_size}, recall@10=not-measured"
    if sample_size < _BENCH_CITATION_MIN_SAMPLE:
        return list(results), BenchCitationRerankTrace(
            status="insufficient_bench_history",
            policy_enabled=True,
            sample_size=sample_size,
            candidate_authority_ids=tuple(candidate_ids),
            source_authority_ids=tuple(sorted(source_ids)),
            explanation=(
                "Insufficient bench-citation history for rerank "
                f"({sample_band}); general relevance order kept."
            ),
        )

    scores: dict[str, int] = {}
    explanations: dict[str, str] = {}
    for doc_id in candidate_ids:
        boost_sources: list[str] = []
        reasons: list[str] = []
        if doc_id in authored_ids:
            scores[doc_id] = max(scores.get(doc_id, 0), 2)
            boost_sources.append(doc_id)
            reasons.append("bench_authored")
        if approving_sources.get(doc_id):
            scores[doc_id] = max(scores.get(doc_id, 0), 1)
            boost_sources.extend(approving_sources[doc_id])
            reasons.append("approvingly_cited_by_bench")
        if reasons:
            unique_sources = tuple(dict.fromkeys(boost_sources))
            explanations[doc_id] = (
                "bench-citation relevance rerank: "
                f"{sample_band}; reason={'+'.join(reasons)}; "
                f"source_ids={','.join(unique_sources)}"
            )

    reranked = sorted(
        list(results),
        key=lambda r: scores.get(r.authority_document_id, 0),
        reverse=True,
    )
    boosted_ids = [doc_id for doc_id in candidate_ids if scores.get(doc_id, 0) > 0]
    return reranked, BenchCitationRerankTrace(
        status="applied",
        policy_enabled=True,
        sample_size=sample_size,
        candidate_authority_ids=tuple(candidate_ids),
        boosted_authority_ids=tuple(boosted_ids),
        source_authority_ids=tuple(sorted(source_ids)),
        per_authority_explanations=explanations,
        explanation=(
            "Applied bench-citation relevance rerank using citation-grounded source IDs "
            f"({sample_band})."
        ),
    )


def _record_bench_citation_rerank(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    trace: BenchCitationRerankTrace,
) -> ModelRun:
    metadata = trace.metadata()
    prompt_hash = hashlib.sha256(
        json.dumps(metadata, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    completion = LLMCompletion(
        text=trace.explanation,
        provider="internal",
        model=_BENCH_RERANK_MODEL,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
    )
    run = _write_model_run(
        session,
        context=context,
        matter_id=matter.id,
        purpose=_BENCH_RERANK_PURPOSE,
        completion=completion,
        prompt_hash=prompt_hash,
        status_label=trace.status,
    )
    from caseops_api.services.audit import record_from_context

    record_from_context(
        session,
        context,
        action="authority_rerank.bench_citation_relevance",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={**metadata, "model_run_id": run.id},
    )
    return run


def _rerank_by_outcome_bias(
    session: Session, results, *, matter
) -> list:
    """Reorder retrieval results so authorities with outcome_labels
    favourable to the user's position come first.

    Fetches outcome_label for each doc in one SQL query, scores
    +1 / -1 / 0 on the _OUTCOME_BIAS mapping for the matter's
    practice_area, then does a stable-sort descending. Non-biased
    practice areas fall through unchanged.
    """
    if not results:
        return results
    practice = (matter.practice_area or "").lower()
    bias = _OUTCOME_BIAS.get(practice)
    if not bias:
        return results

    doc_ids = [r.authority_document_id for r in results]
    rows = session.execute(
        select(AuthorityDocument.id, AuthorityDocument.outcome_label)
        .where(AuthorityDocument.id.in_(doc_ids))
    ).all()
    outcome_by_id = {row.id: (row.outcome_label or "").lower() for row in rows}

    preferred = bias["preferred"]
    against = bias["against"]

    def score(r) -> int:
        label = outcome_by_id.get(r.authority_document_id, "")
        if any(token in label for token in preferred):
            return 1
        if any(token in label for token in against):
            return -1
        return 0

    # Stable sort: ties preserve the cross-encoder reranker's ordering.
    return sorted(results, key=score, reverse=True)


def _gather_authorities(
    session: Session,
    *,
    query: str,
    forum_level: str | None,
    matter=None,
    limit: int = 6,
) -> list[RetrievedAuthority]:
    authorities, _trace = _gather_authorities_with_trace(
        session,
        query=query,
        forum_level=forum_level,
        matter=matter,
        limit=limit,
    )
    return authorities


def _gather_authorities_with_trace(
    session: Session,
    *,
    query: str,
    forum_level: str | None,
    matter=None,
    context: SessionContext | None = None,
    enable_bench_citation_rerank: bool = False,
    limit: int = 6,
) -> tuple[list[RetrievedAuthority], BenchCitationRerankTrace | None]:
    # Precedent cascades: a High Court matter can (and typically should) rely
    # on Supreme Court precedent. Only filter by forum when the matter is at
    # the Supreme Court itself — otherwise broaden the search.
    filter_forum = forum_level if forum_level == "supreme_court" else None
    # Over-fetch 3x so the outcome-bias rerank has material to work
    # with. Without over-fetch, a top-6 dominated by against-outcomes
    # has nothing better to promote — we'd just be reshuffling noise.
    fetch_limit = max(limit * 3, limit)
    # Do NOT catch-and-swallow here. An embedding provider outage, a
    # pgvector index corruption, or a DB timeout is a 503, not a
    # legitimate empty retrieval.
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
        logger.exception("Authority retrieval failed — refusing to proceed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authority retrieval is temporarily unavailable. "
                "Recommendation generation is refused until retrieval recovers."
            ),
        ) from exc

    # Bias step — promote authorities whose outcome_label supports the
    # user's likely position. Skipped when no matter context is passed
    # (legacy callers) or when the practice area isn't in the bias
    # mapping.
    if matter is not None:
        results = _rerank_by_outcome_bias(session, results, matter=matter)
    trace: BenchCitationRerankTrace | None = None
    if enable_bench_citation_rerank and context is not None and matter is not None:
        results, trace = _apply_bench_citation_rerank(
            session,
            results,
            context=context,
            matter=matter,
        )
    results = results[:limit]
    explanations = trace.per_authority_explanations if trace else {}

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
                rerank_explanation=(
                    explanations.get(result.authority_document_id)
                    if explanations
                    else None
                ),
            )
        )
    return picked, trace


def _normalize_custom_goal(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _classify_unsafe_text(
    value: str | None,
    *,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> str | None:
    if not value:
        return None
    for category, pattern in patterns:
        if pattern.search(value):
            return category
    return None


def _record_blocked_objective(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    rec_type: str,
    objective: RecommendationObjective,
    reason_category: str,
) -> None:
    from caseops_api.services.audit import record_from_context

    record_from_context(
        session,
        context,
        action="recommendation.objective_blocked",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        result=AuditResult.DENIED,
        metadata={
            "type": rec_type,
            "recommendation_context": objective.audit_context,
            "reason_category": reason_category,
            "custom_goal": objective.custom_goal_metadata()
            if objective.custom_goal_source == "custom_goal"
            else {"present": False},
            "lawyer_thinking": objective.custom_goal_metadata()
            if objective.custom_goal_source == "lawyer_thinking"
            else {"present": False},
        },
    )
    session.commit()


def _resolve_objective(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    rec_type: str,
    recommendation_context: str | None,
    custom_goal: str | None,
    lawyer_thinking: str | None = None,
) -> RecommendationObjective:
    normalized_lawyer_thinking = _normalize_custom_goal(lawyer_thinking)
    normalized_custom_goal = _normalize_custom_goal(custom_goal)
    normalized_goal = normalized_lawyer_thinking or normalized_custom_goal
    goal_source = (
        "lawyer_thinking"
        if normalized_lawyer_thinking
        else "custom_goal"
        if normalized_custom_goal
        else None
    )
    objective_context = recommendation_context
    if objective_context is None and normalized_goal:
        objective_context = "custom_goal"
    if objective_context is not None and objective_context not in SUPPORTED_OBJECTIVE_CONTEXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Recommendation context {objective_context!r} is not supported. "
                f"Supported contexts: {sorted(SUPPORTED_OBJECTIVE_CONTEXTS)}"
            ),
        )
    if objective_context != "custom_goal" and goal_source != "lawyer_thinking":
        normalized_goal = None
        goal_source = None

    objective = RecommendationObjective(
        context=objective_context,
        custom_goal=normalized_goal,
        custom_goal_source=goal_source,
    )
    if objective_context == "custom_goal" and not normalized_goal:
        _record_blocked_objective(
            session,
            context=context,
            matter=matter,
            rec_type=rec_type,
            objective=objective,
            reason_category="missing_custom_goal",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A custom recommendation goal is required for custom_goal context.",
        )
    reason = _classify_unsafe_text(
        normalized_goal,
        patterns=_UNSAFE_CUSTOM_GOAL_PATTERNS,
    )
    if reason is not None:
        _record_blocked_objective(
            session,
            context=context,
            matter=matter,
            rec_type=rec_type,
            objective=objective,
            reason_category=reason,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "The custom recommendation goal is unsupported. Reframe it as "
                "source-backed decision support for lawyer review without outcome "
                "prediction, judge selection, illegal conduct, or final legal advice."
            ),
        )
    return objective


def _response_text_parts(parsed: _LLMResponse) -> list[str]:
    parts = [
        parsed.title,
        parsed.rationale,
        parsed.primary_recommendation_label or "",
        parsed.next_action or "",
    ]
    parts.extend(parsed.assumptions)
    parts.extend(parsed.missing_facts)
    if parsed.analysis is not None:
        parts.extend(
            [
                parsed.analysis.recommendation,
                parsed.analysis.confidence_explanation,
                *parsed.analysis.risk_analysis,
                *parsed.analysis.legal_impact,
                *parsed.analysis.suggested_actions,
            ]
        )
    for option in parsed.options:
        parts.extend(
            [
                option.label,
                option.rationale,
                option.risk_notes or "",
            ]
        )
    return parts


def _classify_unsafe_response(parsed: _LLMResponse) -> str | None:
    return _classify_unsafe_text(
        "\n".join(_response_text_parts(parsed)),
        patterns=_UNSAFE_OUTPUT_PATTERNS,
    )


def _bounded_context_text(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    return text[:max_length]


def _append_context_line(lines: list[str], label: str, value: object, *, limit: int) -> None:
    text = _bounded_context_text(value, max_length=limit)
    if text:
        lines.append(f"- {label}: {text}")


def _build_matter_intelligence_context(session: Session, matter: Matter) -> str:
    """Bounded matter context for recommendation prompts.

    The matter has already been loaded through tenant-scoped access checks. Every
    query below is constrained to that matter id and uses deterministic limits so
    prompt growth is predictable.
    """
    lines: list[str] = ["Matter metadata:"]
    _append_context_line(lines, "title", matter.title, limit=240)
    _append_context_line(lines, "client", matter.client_name, limit=160)
    _append_context_line(lines, "opposing party", matter.opposing_party, limit=160)
    _append_context_line(lines, "practice area", matter.practice_area, limit=120)
    _append_context_line(lines, "forum", matter.forum_level, limit=80)
    _append_context_line(lines, "court", matter.court_name, limit=160)
    _append_context_line(lines, "judge", matter.judge_name, limit=160)
    _append_context_line(lines, "status", matter.status, limit=80)
    _append_context_line(
        lines,
        "next hearing",
        matter.next_hearing_on.isoformat() if matter.next_hearing_on else None,
        limit=40,
    )
    _append_context_line(lines, "description", matter.description, limit=800)

    hearings = list(
        session.scalars(
            select(MatterHearing)
            .where(MatterHearing.matter_id == matter.id)
            .order_by(MatterHearing.hearing_on.desc(), MatterHearing.created_at.desc())
            .limit(5)
        )
    )
    if hearings:
        lines.append("Recent hearings:")
        for hearing in hearings:
            _append_context_line(
                lines,
                hearing.hearing_on.isoformat(),
                " | ".join(
                    part
                    for part in (
                        hearing.forum_name,
                        hearing.judge_name or "",
                        hearing.purpose,
                        hearing.status,
                        hearing.outcome_note or "",
                    )
                    if part
                ),
                limit=420,
            )

    orders = list(
        session.scalars(
            select(MatterCourtOrder)
            .where(MatterCourtOrder.matter_id == matter.id)
            .order_by(MatterCourtOrder.order_date.desc(), MatterCourtOrder.created_at.desc())
            .limit(5)
        )
    )
    if orders:
        lines.append("Recent court orders:")
        for order in orders:
            excerpt = order.summary
            if order.order_text:
                excerpt = f"{order.summary} | excerpt: {order.order_text[:900]}"
            _append_context_line(
                lines,
                f"{order.order_date.isoformat()} {order.title}",
                excerpt,
                limit=900,
            )

    statute_rows = list(
        session.execute(
            select(MatterStatuteReference, StatuteSection, Statute)
            .join(StatuteSection, StatuteSection.id == MatterStatuteReference.section_id)
            .join(Statute, Statute.id == StatuteSection.statute_id)
            .where(MatterStatuteReference.matter_id == matter.id)
            .order_by(
                Statute.short_name,
                StatuteSection.ordinal,
                StatuteSection.section_number,
            )
            .limit(8)
        )
    )
    if statute_rows:
        lines.append("Linked statute references:")
        for ref, section, statute in statute_rows:
            section_summary = " | ".join(
                part
                for part in (
                    statute.short_name,
                    section.section_number,
                    section.section_label or "",
                    f"relevance={ref.relevance}",
                    ref.notes or "",
                    section.section_text or "",
                )
                if part
            )
            _append_context_line(lines, "statute", section_summary, limit=700)

    attachments = list(
        session.scalars(
            select(MatterAttachment)
            .where(MatterAttachment.matter_id == matter.id)
            .order_by(MatterAttachment.created_at.desc())
            .limit(4)
        )
    )
    if attachments:
        lines.append("Processed matter attachments:")
        for attachment in attachments:
            text = _bounded_context_text(attachment.extracted_text, max_length=700)
            if not text:
                chunks = list(
                    session.scalars(
                        select(MatterAttachmentChunk)
                        .where(MatterAttachmentChunk.attachment_id == attachment.id)
                        .order_by(MatterAttachmentChunk.chunk_index.asc())
                        .limit(2)
                    )
                )
                text = _bounded_context_text(
                    " ".join(chunk.content for chunk in chunks),
                    max_length=700,
                )
            descriptor = " | ".join(
                part
                for part in (
                    attachment.original_filename,
                    attachment.document_type or "",
                    attachment.processing_status,
                    text or "",
                )
                if part
            )
            _append_context_line(lines, "attachment", descriptor, limit=900)

    activities = list(
        session.scalars(
            select(MatterActivity)
            .where(MatterActivity.matter_id == matter.id)
            .order_by(MatterActivity.created_at.desc())
            .limit(6)
        )
    )
    if activities:
        lines.append("Recent matter activity:")
        for item in activities:
            _append_context_line(
                lines,
                item.created_at.isoformat(),
                " | ".join(
                    part
                    for part in (item.event_type, item.title, item.detail or "")
                    if part
                ),
                limit=420,
            )

    return "\n".join(lines)


def _analysis_json(parsed: _LLMResponse, *, confidence: str) -> str:
    analysis = parsed.analysis
    if analysis is None:
        primary = parsed.options[0] if parsed.options else None
        analysis = _LLMAnalysis(
            recommendation=(
                parsed.primary_recommendation_label
                or (primary.label if primary else parsed.title)
            ),
            risk_analysis=[
                text
                for text in [primary.risk_notes if primary else None, *parsed.missing_facts[:3]]
                if text
            ],
            legal_impact=[parsed.rationale[:1200]],
            suggested_actions=[item for item in [parsed.next_action] if item],
            confidence_score=confidence,
            confidence_explanation=(
                "Confidence reflects verified citation coverage and missing facts."
            ),
        )
    payload = {
        "recommendation": _bounded_context_text(analysis.recommendation, max_length=5000)
        or parsed.title,
        "risk_analysis": [
            item
            for item in (
                _bounded_context_text(value, max_length=1000)
                for value in analysis.risk_analysis
            )
            if item
        ][:12],
        "legal_impact": [
            item
            for item in (
                _bounded_context_text(value, max_length=1000)
                for value in analysis.legal_impact
            )
            if item
        ][:12],
        "suggested_actions": [
            item
            for item in (
                _bounded_context_text(value, max_length=1000)
                for value in analysis.suggested_actions
            )
            if item
        ][:12],
        "confidence_score": (
            analysis.confidence_score
            if analysis.confidence_score in CONFIDENCE_LEVELS
            else confidence
        ),
        "confidence_explanation": _bounded_context_text(
            analysis.confidence_explanation,
            max_length=2000,
        )
        or "Confidence reflects verified citations and missing facts.",
    }
    return json.dumps(payload)


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
    objective: RecommendationObjective | None = None,
    matter_intelligence_context: str | None = None,
) -> list[LLMMessage]:
    framing = _TYPE_FRAMING.get(rec_type, _TYPE_FRAMING["authority"])
    objective = objective or RecommendationObjective()
    objective_context = objective.context or "default_matter_status"
    objective_framing = (
        _OBJECTIVE_FRAMING.get(objective.context or "", "")
        or "Frame the recommendation from matter status, posture, and retrieved sources."
    )
    custom_goal_line = (
        objective.custom_goal
        if objective.custom_goal and objective.custom_goal_source == "custom_goal"
        else "none"
    )
    lawyer_thinking_line = (
        objective.custom_goal
        if objective.custom_goal and objective.custom_goal_source == "lawyer_thinking"
        else None
    )
    matter_context = matter_intelligence_context or "\n".join(
        [
            "Matter metadata:",
            f"- title: {matter.title}",
            f"- practice area: {matter.practice_area or 'unknown'}",
            f"- forum: {matter.forum_level or 'unknown'}",
            f"- court: {matter.court_name or 'unknown'}",
            f"- status: {matter.status or 'unknown'}",
            f"- description: {(matter.description or '').strip() or 'none'}",
        ]
    )
    # BUG-024 / BUG-033 / BUG-034 (Ram + Hari 2026-04-27): explicit
    # constraint to use the EXACT citation text from the numbered list.
    # Prior wording ("do not invent citations") was too loose — the
    # model would paraphrase identifiers and the verifier rejected the
    # paraphrase as unmatched. Numbered list + "verbatim" instruction
    # collapses ambiguity.
    system = (
        "You are CaseOps, a legal operations assistant for Indian law firms and "
        "corporate legal teams. You must respond only with JSON matching the "
        "schema described by the user. Every option must cite at least one "
        "supporting authority from the RETRIEVED_AUTHORITIES list below.\n\n"
        "CITATION RULES (HARD):\n"
        "1. Each entry in `supporting_citations` MUST start with the bracket "
        "tag from the RETRIEVED_AUTHORITIES list (e.g. \"[1]\", \"[2]\") "
        "followed by the citation text from that line. Example: "
        "\"[1] Arnesh Kumar v. State of Bihar, AIR 2014 SC 2756\". The "
        "bracket tag is required — it is how the verifier resolves the "
        "citation. Never invent a tag that is not in the list.\n"
        "2. Do NOT invent citations or omit the bracket tag. If you are "
        "unsure which listed authority supports your point, omit the "
        "citation entirely and note the gap in `missing_facts`.\n"
        "3. If no listed authority supports an option, set "
        "`supporting_citations: []`, lower `confidence` to \"low\", and "
        "explain in `missing_facts`.\n\n"
        "SAFETY RULES (HARD):\n"
        "1. This is decision support for lawyer review, not a final instruction.\n"
        "2. Do not provide success probability, win/loss odds, guaranteed outcomes, "
        "judge-shopping guidance, best-judge/best-bench recommendations, judge "
        "reputation scores, or emotion/biometric/psychological/voice analysis.\n"
        "3. Do not tell the lawyer or client exactly what to do. Use possible "
        "actions for lawyer review, source-backed observations, missing information, "
        "and risks or uncertainties.\n\n"
        "LAWYER-THINKING ANALYSIS RULES:\n"
        "1. If LAWYER_THINKING is present, analyze that planned action, assumption, "
        "concern, or strategy against the matter context and retrieved sources.\n"
        "2. If the planned action is risky, identify safer alternatives for lawyer "
        "review instead of instructing the lawyer to take one path.\n"
        "3. If evidence is insufficient, lower confidence and name missing facts.\n\n"
        "OUTPUT ORGANIZATION:\n"
        "- Put `Source-backed observations`, `Possible next actions for lawyer "
        "review`, `Missing information`, and `Risks/uncertainties` sections in "
        "`rationale` where the evidence supports them.\n"
        "- Populate `analysis` with dedicated Recommendation, Risk analysis, "
        "Legal impact, Suggested actions, Confidence score, and confidence "
        "explanation fields.\n"
        "- Keep every option review-required and source-grounded.\n\n"
        f"TASK: {framing}"
    )
    # Numbered citations make verbatim-copy unambiguous + give the model
    # a stable handle to reference. The verifier still matches on the
    # full identifier text; the [N] number is just a UX cue for the
    # model.
    authority_lines: list[str] = []
    for i, authority in enumerate(authorities, start=1):
        line = f"[{i}] CITATION: {authority.identifier}\n    EXCERPT: {authority.text[:600]}"
        if authority.rerank_explanation:
            line += f"\n    RERANK_EXPLANATION: {authority.rerank_explanation}"
        authority_lines.append(line)
    authority_block = "\n".join(authority_lines) or "(no authorities retrieved)"
    user = (
        "Respond with json. Produce a CaseOps recommendation object.\n\n"
        f"RECOMMENDATION_TYPE: {rec_type}\n"
        f"RECOMMENDATION_CONTEXT: {objective_context}\n"
        f"OBJECTIVE_FRAMING: {objective_framing}\n"
        f"CUSTOM_GOAL: {custom_goal_line}\n"
        + (
            f"LAWYER_THINKING: {lawyer_thinking_line}\n"
            if lawyer_thinking_line
            else ""
        )
        + (
            "MATTER_INTELLIGENCE_CONTEXT:\n"
            f"{matter_context}\n\n"
        )
        +
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
        "\"confidence\": \"low|medium|high\", \"next_action\": str | null, "
        "\"analysis\": {\"recommendation\": str, \"risk_analysis\": [str], "
        "\"legal_impact\": [str], \"suggested_actions\": [str], "
        "\"confidence_score\": \"low|medium|high\", "
        "\"confidence_explanation\": str}}"
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
    # Map the model's raw citation string → the canonical SourceDoc.identifier
    # so the UI shows the clean canonical form (no "[1]" prefix, no
    # paraphrase). Dedup is by canonical so two raw spellings of the same
    # source collapse to one.
    canonical_for: dict[str, str] = {}
    for check in report.checks:
        if check.verified and check.source is not None:
            canonical_for[check.claim.citation] = check.source.identifier
    per_option_verified: dict[int, list[str]] = {i: [] for i in range(len(options))}
    for idx, option in enumerate(options):
        seen: set[str] = set()
        for citation in option.supporting_citations:
            canonical = canonical_for.get(citation)
            if canonical and canonical not in seen:
                per_option_verified[idx].append(canonical)
                seen.add(canonical)
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
    recommendation_context: str | None = None,
    custom_goal: str | None = None,
    lawyer_thinking: str | None = None,
    provider: LLMProvider | None = None,
) -> Recommendation:
    # BUG-015 (Ram 2026-04-26 Critical reopen) deep dive: prior fix
    # attempts (per-purpose timeout, fallback constructors) did NOT
    # close the bug — Playwright still hits 504 Gateway Timeout at
    # Cloud Run's 300s. Add per-stage timing logs so the next failure
    # reproduction reveals where the time actually goes (retrieval?
    # LLM call? citation verification? DB persist?).
    _t0 = time.perf_counter()
    _t = _t0
    def _stage(name: str) -> None:
        nonlocal _t
        now = time.perf_counter()
        logger.warning(
            "BUG015_TIMING %s rec_type=%s matter_id=%s stage=%s "
            "stage_ms=%.0f total_ms=%.0f",
            "[generate_recommendation]",
            _safe_log_value(rec_type),
            _safe_log_value(matter_id),
            _safe_log_value(name),
            (now - _t) * 1000, (now - _t0) * 1000,
        )
        _t = now

    _validate_type(rec_type)
    _stage("validate_type")
    # MOD-LSE-1 (2026-05-03): strategy generation has its own service.
    # Dispatch immediately so the existing forum/authority/remedy/
    # next_best_action paths below stay byte-for-byte unchanged.
    if rec_type == "litigation_strategy":
        from caseops_api.services.litigation_strategy import (
            generate_litigation_strategy,
        )

        return generate_litigation_strategy(
            session,
            context=context,
            matter_id=matter_id,
            provider=provider,
        )
    matter = _load_matter(session, context=context, matter_id=matter_id)
    _stage("load_matter")
    objective = _resolve_objective(
        session,
        context=context,
        matter=matter,
        rec_type=rec_type,
        recommendation_context=recommendation_context,
        custom_goal=custom_goal,
        lawyer_thinking=lawyer_thinking,
    )
    _stage("resolve_objective")
    # BUG-015 deep dive: prior reproductions showed _gather_authorities
    # hangs for 5+ minutes under heavy concurrent corpus INSERT load
    # (citation extraction + EN sweep TITLES both writing
    # authority_document_chunks rows, contending with the HNSW vector
    # query). Apply a per-statement timeout so retrieval fails fast
    # with an actionable 503 instead of consuming Cloud Run's 300s
    # request budget. Postgres SET LOCAL only affects this transaction.
    from sqlalchemy import text as _sa_text
    try:
        session.execute(_sa_text("SET LOCAL statement_timeout = '60000'"))
    except Exception:
        # SQLite tests etc. — no-op
        pass
    retrieved, bench_rerank_trace = _gather_authorities_with_trace(
        session,
        query=_build_retrieval_query(matter, rec_type, objective=objective),
        forum_level=matter.forum_level,
        matter=matter,
        context=context,
        enable_bench_citation_rerank=(rec_type == "authority"),
    )
    _stage("gather_authorities")
    if bench_rerank_trace is not None:
        _record_bench_citation_rerank(
            session,
            context=context,
            matter=matter,
            trace=bench_rerank_trace,
        )
        session.commit()
        _stage("record_bench_rerank")

    matter_intelligence_context = _build_matter_intelligence_context(session, matter)
    _stage("build_matter_intelligence_context")
    llm = provider or build_provider(purpose=PURPOSE_RECOMMENDATIONS)
    messages = _build_prompt(
        rec_type=rec_type,
        matter=matter,
        authorities=retrieved,
        objective=objective,
        matter_intelligence_context=matter_intelligence_context,
    )
    prompt_hash = _prompt_hash(messages)
    _stage("build_prompt")

    settings = get_settings()
    _call_context = LLMCallContext(
        tenant_id=context.company.id,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        purpose=f"recommendation:{rec_type}",
    )

    def _invoke(active: LLMProvider) -> tuple[_LLMResponse, LLMCompletion]:
        return generate_structured(
            active,
            session=session,
            schema=_LLMResponse,
            messages=messages,
            context=_call_context,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_output_tokens_recommendations,
        )

    # 2026-04-30: gpt-5.1-only path. The prior Anthropic→Haiku→OpenAI
    # ladder burned ~3x tokens per click; with Anthropic credits gone
    # and the OpenAI bill now the single line item, one primary call is
    # all we want. LLMProviderError covers quota / 5xx / format / timeout.
    #
    # Ram BUG-029 (2026-05-01) — recommendations 502 reopen, GPT-5.1
    # occasionally returns malformed JSON (~1-2% of long structured
    # outputs). Without a fallback ladder a single transient format
    # error puts the user on a 502. Single retry on LLMResponseFormatError
    # specifically — same provider, same model, same prompt. Most format
    # errors clear on retry because the model's JSON output is non-
    # deterministic at temperature > 0. Quota / 5xx / timeout still 502
    # immediately (retry won't help upstream outages).
    try:
        parsed, completion = _invoke(llm)
        _stage(f"llm_primary({getattr(llm, 'model', '?')})")
    except LLMResponseFormatError as exc:
        logger.warning(
            "recommendation %s: primary LLM %s returned malformed JSON; "
            "retrying once. detail=%s",
            _safe_log_value(rec_type),
            _safe_log_value(getattr(llm, "model", "<unknown>")),
            _safe_log_value(exc, limit=300),
        )
        try:
            parsed, completion = _invoke(llm)
            _stage(f"llm_retry({getattr(llm, 'model', '?')})")
        except LLMProviderError as retry_exc:
            logger.warning(
                "recommendation %s: retry on %s also failed (%s)",
                _safe_log_value(rec_type),
                _safe_log_value(getattr(llm, "model", "<unknown>")),
                _safe_log_value(type(retry_exc).__name__),
            )
            raise provider_failure_http_exception(
                noun="recommendation",
                exc=retry_exc,
            ) from retry_exc
    except LLMProviderError as exc:
        logger.warning(
            "recommendation %s: primary LLM %s failed (%s)",
            _safe_log_value(rec_type),
            _safe_log_value(getattr(llm, "model", "<unknown>")),
            _safe_log_value(type(exc).__name__),
        )
        raise provider_failure_http_exception(
            noun="recommendation",
            exc=exc,
        ) from exc

    unsafe_output_category = _classify_unsafe_response(parsed)
    if unsafe_output_category is not None:
        run = _write_model_run(
            session,
            context=context,
            matter_id=matter.id,
            purpose=f"recommendation:{rec_type}",
            completion=completion,
            prompt_hash=prompt_hash,
            status_label="rejected_unsafe_output",
            error=f"unsafe_recommendation_output:{unsafe_output_category}",
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "The recommendation output was refused because it used unsupported "
                "wording. Reframe the objective for source-backed lawyer review. "
                "No recommendation was saved."
            ),
            headers={"X-Model-Run-Id": run.id},
        )

    cleaned_options, report = _filter_and_verify_options(parsed.options, retrieved)
    _stage("filter_and_verify")
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
                "The model returned citations, but none matched verified "
                "authorities in the corpus. Try again — if this persists, "
                "widen the matter description so retrieval has more "
                "context to ground on."
            )
        else:
            error_msg = "Retrieval returned no authorities."
            detail = (
                "No grounding authorities were retrieved for this matter. "
                "Add more detail to the matter description (facts, "
                "sections, forum) or check corpus coverage before "
                "retrying. Recommendations require at least one verified "
                "citation per PRD §6.1."
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
        # User-facing ``detail`` stays clean; the model_run_id ends up on
        # ``ModelRun`` + is still discoverable via audit for debugging.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=detail,
            headers={"X-Model-Run-Id": run.id},
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
    # PG-109 (2026-05-01) — capture the full retrieved-authorities list
    # so the UI can show "considered M, cited N". The set we save is
    # the canonical identifiers the LLM was given (post-rerank, pre-
    # truncation to top-K), not the raw S3 ids.
    retrieved_identifiers = [a.identifier for a in retrieved]
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
        retrieved_authorities_json=json.dumps(retrieved_identifiers),
        analysis_json=_analysis_json(parsed, confidence=confidence),
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
            "recommendation_context": objective.audit_context,
            "custom_goal": objective.custom_goal_metadata()
            if objective.custom_goal_source == "custom_goal"
            else {"present": False},
            "lawyer_thinking": objective.custom_goal_metadata()
            if objective.custom_goal_source == "lawyer_thinking"
            else {"present": False},
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


def _build_retrieval_query(
    matter: Matter,
    rec_type: str,
    objective: RecommendationObjective | None = None,
) -> str:
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
    elif rec_type == "litigation_strategy":
        # MOD-LSE-1: query expansion for strategy retrieval. Pulls
        # authorities on forum-choice, escalation ladder, limitation,
        # interim relief, and the highest-frequency SC routes (SLP /
        # review / curative). Without this expansion the retrieval
        # leans only on practice-area facts and misses the procedural
        # backbone the strategy needs.
        parts.append(
            "litigation strategy escalation forum sequence "
            "appeal special leave petition Article 136 review "
            "Article 137 curative limitation condonation interim "
            "stay status quo"
        )
    objective = objective or RecommendationObjective()
    if objective.context:
        parts.append(_OBJECTIVE_RETRIEVAL_HINTS.get(objective.context, ""))
    if objective.custom_goal:
        parts.append(objective.custom_goal[:300])
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
    _load_matter(session, context=context, matter_id=recommendation.matter_id)
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

    # Round-2 fix (P1 #3, 2026-05-03). The PR set review_required=True
    # on every litigation_strategy row but the decision endpoint only
    # changed status; review_required stayed True forever. As a result
    # the Strategy page kept showing the "Partner review required"
    # badge even after a partner accepted the strategy. Acceptance is
    # the decision that completes review, so clear the flag on
    # ``accepted``. ``rejected`` / ``edited`` / ``deferred`` keep the
    # flag — those are not approvals.
    if decision == "accepted":
        recommendation.review_required = False
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
