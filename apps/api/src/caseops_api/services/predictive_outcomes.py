"""Source-bound outcome classification and aggregate snapshots for LI-S7B.

The backfill path classifies only source documents/orders with usable text.
Deterministic rules handle obvious orders first. Optional LLM assistance may
map source text into controlled labels, but never creates probabilities.
Predictive probabilities remain aggregate-derived with sample size, confidence
band, and evidence IDs.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    JudgeDecisionIndex,
    Matter,
    MatterCourtOrder,
    ModelRun,
    PredictiveOutcomeAggregateSnapshot,
    PredictiveOutcomeClassification,
)
from caseops_api.services.authority_sources import list_predictive_aggregate_authority_source_keys
from caseops_api.services.llm import (
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMResponseFormatError,
    build_provider,
    generate_structured,
)

CONTROLLED_OUTCOME_LABELS = {
    "interim_relief_granted",
    "interim_relief_denied",
    "stay_granted",
    "stay_denied",
    "notice_issued",
    "notice_refused",
    "bail_granted",
    "bail_denied",
    "adjourned",
    "dismissed",
    "allowed",
    "partly_allowed",
    "remanded",
    "settlement_recorded",
    "procedural_default",
    "insufficient_signal",
}

PREDICTIVE_SIGNAL_TYPES = {
    "interim_relief_likelihood",
    "stay_likelihood",
    "notice_issuance_likelihood",
    "adjournment_likelihood",
    "disposal_delay_risk",
    "adverse_order_risk",
    "settlement_inclination_signal",
    "bench_party_side_tendency",
    "forum_practice_pattern",
}

MIN_AGGREGATE_SAMPLE_SIZE = 5
MAX_AGGREGATE_EVIDENCE = 10
PURPOSE = "predictive_outcome_classification"

_POSITIVE_BY_SIGNAL = {
    "interim_relief_likelihood": {"interim_relief_granted"},
    "stay_likelihood": {"stay_granted"},
    "notice_issuance_likelihood": {"notice_issued"},
    "adjournment_likelihood": {"adjourned"},
    "disposal_delay_risk": {"adjourned", "procedural_default"},
    "adverse_order_risk": {
        "interim_relief_denied",
        "stay_denied",
        "notice_refused",
        "bail_denied",
        "dismissed",
        "procedural_default",
    },
    "settlement_inclination_signal": {"settlement_recorded"},
    "bench_party_side_tendency": {"allowed", "partly_allowed", "bail_granted"},
    "forum_practice_pattern": {
        "notice_issued",
        "adjourned",
        "procedural_default",
        "settlement_recorded",
    },
}
_NEGATIVE_BY_SIGNAL = {
    "interim_relief_likelihood": {"interim_relief_denied"},
    "stay_likelihood": {"stay_denied"},
    "notice_issuance_likelihood": {"notice_refused"},
    "adjournment_likelihood": set(),
    "disposal_delay_risk": {"allowed", "partly_allowed"},
    "adverse_order_risk": {"allowed", "partly_allowed", "bail_granted"},
    "settlement_inclination_signal": set(),
    "bench_party_side_tendency": {"dismissed", "bail_denied"},
    "forum_practice_pattern": set(),
}
_SIGNALS_FOR_LABEL = {
    "interim_relief_granted": ("interim_relief_likelihood",),
    "interim_relief_denied": ("interim_relief_likelihood", "adverse_order_risk"),
    "stay_granted": ("stay_likelihood",),
    "stay_denied": ("stay_likelihood", "adverse_order_risk"),
    "notice_issued": ("notice_issuance_likelihood", "forum_practice_pattern"),
    "notice_refused": ("notice_issuance_likelihood", "adverse_order_risk"),
    "bail_granted": ("bench_party_side_tendency",),
    "bail_denied": ("bench_party_side_tendency", "adverse_order_risk"),
    "adjourned": ("adjournment_likelihood", "disposal_delay_risk", "forum_practice_pattern"),
    "dismissed": ("bench_party_side_tendency", "adverse_order_risk"),
    "allowed": ("bench_party_side_tendency",),
    "partly_allowed": ("bench_party_side_tendency",),
    "remanded": ("bench_party_side_tendency",),
    "settlement_recorded": ("settlement_inclination_signal", "forum_practice_pattern"),
    "procedural_default": ("disposal_delay_risk", "adverse_order_risk", "forum_practice_pattern"),
    "insufficient_signal": ("insufficient_signal",),
}

_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "interim_relief_denied",
        ("interim relief", "interim application", "injunction", "ad-interim"),
        ("denied", "refused", "rejected", "dismissed"),
    ),
    (
        "interim_relief_granted",
        ("interim relief", "interim application", "injunction", "ad-interim"),
        ("granted", "allowed", "status quo", "restrained"),
    ),
    ("stay_denied", ("stay",), ("denied", "refused", "vacated", "no stay")),
    ("stay_granted", ("stay", "status quo"), ("granted", "continued", "ordered")),
    ("notice_refused", ("notice",), ("refused", "not issued", "no notice")),
    ("notice_issued", ("notice",), ("issued", "issue notice", "returnable")),
    ("bail_denied", ("bail",), ("denied", "rejected", "refused", "dismissed")),
    ("bail_granted", ("bail",), ("granted", "released", "enlarged")),
    ("partly_allowed", ("partly allowed", "partially allowed"), ()),
    ("allowed", ("allowed", "petition succeeds", "appeal succeeds"), ()),
    ("dismissed", ("dismissed", "petition fails", "appeal fails"), ()),
    ("remanded", ("remanded", "remit", "remitted"), ()),
    ("settlement_recorded", ("settlement", "settled", "compromise", "consent terms"), ()),
    ("procedural_default", ("non-prosecution", "default", "non appearance"), ()),
    ("adjourned", ("adjourned", "renotify", "re-notify", "list on"), ()),
)
_PROBABILITY_RE = re.compile(
    r"(\b\d{1,3}\s*%|\bprobab(?:ility|le)\b|\bchance\b|\bodds\b)",
    re.IGNORECASE,
)


def official_predictive_authority_sources() -> tuple[str, ...]:
    """Authority source IDs permitted for public predictive aggregate jobs."""
    return list_predictive_aggregate_authority_source_keys()


@dataclass(frozen=True)
class ClassificationStats:
    processed: int = 0
    classified: int = 0
    skipped: int = 0
    quarantined: int = 0
    dry_run: bool = False
    aggregate_snapshots: int = 0
    estimated_llm_cost_usd: float = 0.0


@dataclass(frozen=True)
class _SourceContext:
    source_type: str
    source_id: str
    text: str
    court_name: str | None
    forum_level: str | None
    judge_ids: tuple[str, ...]
    matter_type: str | None
    party_side: str | None
    decision_year: int | None
    company_id: str | None = None
    matter_id: str | None = None


@dataclass(frozen=True)
class _Candidate:
    label: str
    rationale_snippet: str | None
    confidence: float


@dataclass
class _AggregationGroup:
    scope_type: str
    scope_key: str
    signal_type: str
    court_name: str | None = None
    forum_level: str | None = None
    judge_id: str | None = None
    matter_type: str | None = None
    party_side: str | None = None
    year_start: int | None = None
    year_end: int | None = None
    company_id: str | None = None
    matter_id: str | None = None
    rows: list[PredictiveOutcomeClassification] = field(default_factory=list)


class _LLMOutcomeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    rationale_snippet: str = Field(min_length=1, max_length=500)

    @field_validator("label")
    @classmethod
    def _controlled_label(cls, value: str) -> str:
        if value not in CONTROLLED_OUTCOME_LABELS:
            raise ValueError("unsupported predictive outcome label")
        return value

    @field_validator("rationale_snippet")
    @classmethod
    def _no_probability_language(cls, value: str) -> str:
        if _PROBABILITY_RE.search(value):
            raise ValueError("probability language is not permitted")
        return value


class _LLMOutcomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcomes: list[_LLMOutcomeItem] = Field(default_factory=list, max_length=8)


def classify_authority_document(
    session: Session,
    document: AuthorityDocument,
    *,
    use_llm: bool = False,
    force: bool = False,
    only_unclassified: bool = True,
    provider: LLMProvider | None = None,
) -> list[PredictiveOutcomeClassification]:
    text = _usable_authority_text(document)
    if text is None:
        return []
    if force:
        _delete_source_classifications(session, "authority_document", document.id)
    elif only_unclassified and _source_already_classified(
        session, "authority_document", document.id
    ):
        return []

    judge_ids = tuple(
        session.scalars(
            select(JudgeDecisionIndex.judge_id).where(
                JudgeDecisionIndex.authority_document_id == document.id
            )
        )
    )
    source = _SourceContext(
        source_type="authority_document",
        source_id=document.id,
        text=text,
        court_name=document.court_name,
        forum_level=document.forum_level,
        judge_ids=judge_ids,
        matter_type=_derive_matter_type(document.title, document.summary, text),
        party_side=_infer_party_side(text),
        decision_year=document.decision_date.year if document.decision_date else None,
    )
    candidates = _deterministic_candidates(text)
    if not candidates and use_llm:
        candidates, model_run_id, error = _llm_candidates(
            session,
            source=source,
            provider=provider,
        )
        if error is not None:
            return [_store_quarantine(session, source, model_run_id, error)]
        return _store_candidates(
            session,
            source,
            candidates,
            method="llm",
            model_run_id=model_run_id,
        )
    return _store_candidates(session, source, candidates, method="deterministic")


def classify_matter_court_order(
    session: Session,
    order: MatterCourtOrder,
    *,
    matter: Matter,
    use_llm: bool = False,
    force: bool = False,
    only_unclassified: bool = True,
    provider: LLMProvider | None = None,
) -> list[PredictiveOutcomeClassification]:
    text = _usable_order_text(order)
    if text is None:
        return []
    if force:
        _delete_source_classifications(session, "matter_court_order", order.id)
    elif only_unclassified and _source_already_classified(session, "matter_court_order", order.id):
        return []

    source = _SourceContext(
        source_type="matter_court_order",
        source_id=order.id,
        text=text,
        court_name=matter.court_name,
        forum_level=matter.forum_level,
        judge_ids=(),
        matter_type=_normalise_matter_type(matter.practice_area),
        party_side=_infer_party_side(text),
        decision_year=order.order_date.year,
        company_id=matter.company_id,
        matter_id=matter.id,
    )
    candidates = _deterministic_candidates(text)
    if not candidates and use_llm:
        candidates, model_run_id, error = _llm_candidates(
            session,
            source=source,
            provider=provider,
        )
        if error is not None:
            return [_store_quarantine(session, source, model_run_id, error)]
        return _store_candidates(
            session,
            source,
            candidates,
            method="llm",
            model_run_id=model_run_id,
        )
    return _store_candidates(session, source, candidates, method="deterministic")


def backfill_predictive_outcomes(
    session: Session,
    *,
    forum_level: str | None = None,
    court_name: str | None = None,
    year_range: tuple[int, int] | None = None,
    judge_id: str | None = None,
    matter_type: str | None = None,
    limit: int | None = None,
    batch_size: int = 100,
    dry_run: bool = False,
    budget_usd: float | None = None,
    use_llm: bool = False,
    force: bool = False,
    only_unclassified: bool = True,
) -> ClassificationStats:
    documents = _select_authority_documents(
        session,
        forum_level=forum_level,
        court_name=court_name,
        year_range=year_range,
        judge_id=judge_id,
        matter_type=matter_type,
        limit=limit,
        only_unclassified=only_unclassified and not force,
    )
    if dry_run:
        return ClassificationStats(
            processed=len(documents),
            skipped=len(documents),
            dry_run=True,
        )

    processed = classified = skipped = quarantined = 0
    estimated_cost = 0.0
    for offset in range(0, len(documents), max(1, batch_size)):
        for document in documents[offset : offset + max(1, batch_size)]:
            if use_llm and budget_usd is not None and estimated_cost + 0.002 > budget_usd:
                skipped += 1
                continue
            rows = classify_authority_document(
                session,
                document,
                use_llm=use_llm,
                force=force,
                only_unclassified=only_unclassified and not force,
            )
            processed += 1
            if rows:
                classified += sum(1 for row in rows if row.status == "classified")
                quarantined += sum(1 for row in rows if row.status == "quarantined")
            else:
                skipped += 1
            if use_llm:
                estimated_cost += 0.002
        session.commit()

    snapshots = refresh_predictive_aggregate_snapshots(
        session,
        court_name=court_name,
        forum_level=forum_level,
        judge_id=judge_id,
        matter_type=_normalise_matter_type(matter_type) if matter_type else None,
        year_range=year_range,
        include_private=False,
    )
    session.commit()
    return ClassificationStats(
        processed=processed,
        classified=classified,
        skipped=skipped,
        quarantined=quarantined,
        dry_run=False,
        aggregate_snapshots=snapshots,
        estimated_llm_cost_usd=round(estimated_cost, 6),
    )


def refresh_predictive_aggregate_snapshots(
    session: Session,
    *,
    court_name: str | None = None,
    forum_level: str | None = None,
    judge_id: str | None = None,
    matter_type: str | None = None,
    party_side: str | None = None,
    year_range: tuple[int, int] | None = None,
    include_private: bool = False,
) -> int:
    rows = _select_classifications_for_aggregation(
        session,
        court_name=court_name,
        forum_level=forum_level,
        judge_id=judge_id,
        matter_type=matter_type,
        party_side=party_side,
        year_range=year_range,
        include_private=include_private,
    )
    groups = _aggregation_groups(rows, year_range=year_range)
    scoped_refresh = bool(court_name or forum_level or judge_id)
    regenerated_scope_keys = {
        key
        for key, group in groups.items()
        if not (scoped_refresh and group.scope_type == "matter_type")
    }
    _delete_stale_aggregate_snapshots(
        session,
        regenerated_scope_keys=regenerated_scope_keys,
        court_name=court_name,
        forum_level=forum_level,
        judge_id=judge_id,
        matter_type=matter_type,
        party_side=party_side,
        year_range=year_range,
        include_private=include_private,
    )
    refreshed = 0
    for group in groups.values():
        if scoped_refresh and group.scope_type == "matter_type":
            continue
        snapshot = _build_snapshot(group)
        existing = session.scalar(
            select(PredictiveOutcomeAggregateSnapshot).where(
                PredictiveOutcomeAggregateSnapshot.scope_key == snapshot.scope_key
            )
        )
        if existing is None:
            session.add(snapshot)
        else:
            _copy_snapshot(existing, snapshot)
        refreshed += 1
    session.flush()
    return refreshed


def load_predictive_aggregate_snapshots_for_matter(
    session: Session,
    *,
    matter: Matter,
    judge_ids: tuple[str, ...],
) -> list[PredictiveOutcomeAggregateSnapshot]:
    candidates: list[PredictiveOutcomeAggregateSnapshot] = []
    if judge_ids:
        candidates.extend(
            session.scalars(
                select(PredictiveOutcomeAggregateSnapshot)
                .where(
                    PredictiveOutcomeAggregateSnapshot.company_id.is_(None),
                    PredictiveOutcomeAggregateSnapshot.matter_id.is_(None),
                    PredictiveOutcomeAggregateSnapshot.scope_type == "judge",
                    PredictiveOutcomeAggregateSnapshot.judge_id.in_(judge_ids),
                )
                .order_by(PredictiveOutcomeAggregateSnapshot.sample_size.desc())
            )
        )
    if matter.court_name or matter.forum_level:
        stmt = select(PredictiveOutcomeAggregateSnapshot).where(
            PredictiveOutcomeAggregateSnapshot.company_id.is_(None),
            PredictiveOutcomeAggregateSnapshot.matter_id.is_(None),
            PredictiveOutcomeAggregateSnapshot.scope_type == "court_forum",
        )
        if matter.court_name:
            stmt = stmt.where(PredictiveOutcomeAggregateSnapshot.court_name == matter.court_name)
        if matter.forum_level:
            stmt = stmt.where(PredictiveOutcomeAggregateSnapshot.forum_level == matter.forum_level)
        candidates.extend(
            session.scalars(stmt.order_by(PredictiveOutcomeAggregateSnapshot.sample_size.desc()))
        )
    candidates.extend(
        session.scalars(
            select(PredictiveOutcomeAggregateSnapshot)
            .where(
                PredictiveOutcomeAggregateSnapshot.company_id == matter.company_id,
                PredictiveOutcomeAggregateSnapshot.matter_id == matter.id,
            )
            .order_by(PredictiveOutcomeAggregateSnapshot.sample_size.desc())
        )
    )
    return _dedupe_snapshots(candidates)


def _select_authority_documents(
    session: Session,
    *,
    forum_level: str | None,
    court_name: str | None,
    year_range: tuple[int, int] | None,
    judge_id: str | None,
    matter_type: str | None,
    limit: int | None,
    only_unclassified: bool,
) -> list[AuthorityDocument]:
    allowed_sources = official_predictive_authority_sources()
    if not allowed_sources:
        return []
    stmt = select(AuthorityDocument).where(
        AuthorityDocument.document_text.is_not(None),
        AuthorityDocument.source.in_(allowed_sources),
    )
    if forum_level:
        stmt = stmt.where(AuthorityDocument.forum_level == forum_level)
    if court_name:
        stmt = stmt.where(AuthorityDocument.court_name == court_name)
    if year_range:
        start, end = year_range
        stmt = stmt.where(
            AuthorityDocument.decision_date >= date(start, 1, 1),
            AuthorityDocument.decision_date <= date(end, 12, 31),
        )
    if judge_id:
        stmt = stmt.join(
            JudgeDecisionIndex,
            JudgeDecisionIndex.authority_document_id == AuthorityDocument.id,
        ).where(JudgeDecisionIndex.judge_id == judge_id)
    if matter_type:
        token = f"%{matter_type.lower()}%"
        stmt = stmt.where(
            AuthorityDocument.title.ilike(token)
            | AuthorityDocument.summary.ilike(token)
            | AuthorityDocument.document_text.ilike(token)
        )
    if only_unclassified:
        classified_ids = select(PredictiveOutcomeClassification.source_id).where(
            PredictiveOutcomeClassification.source_type == "authority_document"
        )
        stmt = stmt.where(AuthorityDocument.id.not_in(classified_ids))
    stmt = stmt.order_by(
        AuthorityDocument.decision_date.desc().nullslast(),
        AuthorityDocument.created_at.desc(),
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def _select_classifications_for_aggregation(
    session: Session,
    *,
    court_name: str | None,
    forum_level: str | None,
    judge_id: str | None,
    matter_type: str | None,
    party_side: str | None,
    year_range: tuple[int, int] | None,
    include_private: bool,
) -> list[PredictiveOutcomeClassification]:
    stmt = select(PredictiveOutcomeClassification).where(
        PredictiveOutcomeClassification.status == "classified",
        PredictiveOutcomeClassification.signal_type.in_(PREDICTIVE_SIGNAL_TYPES),
    )
    if not include_private:
        allowed_sources = official_predictive_authority_sources()
        if not allowed_sources:
            return []
        stmt = stmt.join(
            AuthorityDocument,
            and_(
                PredictiveOutcomeClassification.source_type == "authority_document",
                PredictiveOutcomeClassification.source_id == AuthorityDocument.id,
            ),
        )
        stmt = stmt.where(
            PredictiveOutcomeClassification.company_id.is_(None),
            PredictiveOutcomeClassification.matter_id.is_(None),
            AuthorityDocument.source.in_(allowed_sources),
            AuthorityDocument.document_text.is_not(None),
        )
    if court_name:
        stmt = stmt.where(PredictiveOutcomeClassification.court_name == court_name)
    if forum_level:
        stmt = stmt.where(PredictiveOutcomeClassification.forum_level == forum_level)
    if matter_type:
        stmt = stmt.where(PredictiveOutcomeClassification.matter_type == matter_type)
    if party_side:
        stmt = stmt.where(PredictiveOutcomeClassification.party_side == party_side)
    if year_range:
        start, end = year_range
        stmt = stmt.where(
            PredictiveOutcomeClassification.decision_year >= start,
            PredictiveOutcomeClassification.decision_year <= end,
        )
    rows = list(session.scalars(stmt))
    if judge_id:
        rows = [row for row in rows if judge_id in _json_list(row.judge_ids_json)]
    return rows


def _delete_stale_aggregate_snapshots(
    session: Session,
    *,
    regenerated_scope_keys: set[str],
    court_name: str | None,
    forum_level: str | None,
    judge_id: str | None,
    matter_type: str | None,
    party_side: str | None,
    year_range: tuple[int, int] | None,
    include_private: bool,
) -> None:
    stmt = select(PredictiveOutcomeAggregateSnapshot)
    if not include_private:
        stmt = stmt.where(
            PredictiveOutcomeAggregateSnapshot.company_id.is_(None),
            PredictiveOutcomeAggregateSnapshot.matter_id.is_(None),
        )
    if matter_type:
        stmt = stmt.where(PredictiveOutcomeAggregateSnapshot.matter_type == matter_type)
    if party_side:
        stmt = stmt.where(PredictiveOutcomeAggregateSnapshot.party_side == party_side)
    if year_range:
        start, end = year_range
        stmt = stmt.where(
            PredictiveOutcomeAggregateSnapshot.year_start == start,
            PredictiveOutcomeAggregateSnapshot.year_end == end,
        )

    scope_clauses = []
    if judge_id:
        scope_clauses.append(
            and_(
                PredictiveOutcomeAggregateSnapshot.scope_type == "judge",
                PredictiveOutcomeAggregateSnapshot.judge_id == judge_id,
            )
        )
    if court_name or forum_level:
        court_clause = PredictiveOutcomeAggregateSnapshot.scope_type.in_(
            ("court_forum", "judge")
        )
        if court_name:
            court_clause = and_(
                court_clause,
                PredictiveOutcomeAggregateSnapshot.court_name == court_name,
            )
        if forum_level:
            court_clause = and_(
                court_clause,
                PredictiveOutcomeAggregateSnapshot.forum_level == forum_level,
            )
        scope_clauses.append(court_clause)
    if court_name or forum_level or judge_id:
        scope_clauses.append(
            PredictiveOutcomeAggregateSnapshot.scope_type == "matter_type"
        )
    if scope_clauses:
        stmt = stmt.where(or_(*scope_clauses))

    for snapshot in session.scalars(stmt):
        if not _snapshot_matches_refresh_scope(
            snapshot,
            court_name=court_name,
            forum_level=forum_level,
            judge_id=judge_id,
        ):
            continue
        if snapshot.scope_key not in regenerated_scope_keys:
            session.delete(snapshot)
    session.flush()


def _snapshot_matches_refresh_scope(
    snapshot: PredictiveOutcomeAggregateSnapshot,
    *,
    court_name: str | None,
    forum_level: str | None,
    judge_id: str | None,
) -> bool:
    if snapshot.scope_type != "matter_type":
        return True
    if not (court_name or forum_level or judge_id):
        return True

    feature_summary = _json_object(snapshot.feature_summary_json)
    if court_name and court_name not in _feature_string_set(
        feature_summary,
        "source_court_names",
    ):
        return False
    if forum_level and forum_level not in _feature_string_set(
        feature_summary,
        "source_forum_levels",
    ):
        return False
    if judge_id and judge_id not in _feature_string_set(
        feature_summary,
        "source_judge_ids",
    ):
        return False
    return True


def _deterministic_candidates(text: str) -> list[_Candidate]:
    haystack = _normalise_text(text)
    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for label, include_tokens, context_tokens in _RULES:
        if label in seen:
            continue
        if label == "allowed" and (
            "partly allowed" in haystack or "partially allowed" in haystack
        ):
            continue
        if not any(_token_present(haystack, token) for token in include_tokens):
            continue
        if context_tokens and not any(_token_present(haystack, token) for token in context_tokens):
            continue
        seen.add(label)
        candidates.append(
            _Candidate(
                label=label,
                rationale_snippet=_snippet(text, include_tokens[0]),
                confidence=0.88,
            )
        )
    return candidates


def _llm_candidates(
    session: Session,
    *,
    source: _SourceContext,
    provider: LLMProvider | None,
) -> tuple[list[_Candidate], str | None, str | None]:
    llm = provider or build_provider(purpose="metadata_extract")
    messages = _classification_messages(source)
    model_run: ModelRun | None = None
    context = LLMCallContext(
        tenant_id=source.company_id,
        matter_id=source.matter_id,
        purpose=PURPOSE,
        metadata={"source_type": source.source_type, "source_id": source.source_id},
    )

    def on_model_run(
        completion: LLMCompletion,
        call_context: LLMCallContext,
        prompt_messages: list[LLMMessage],
    ) -> None:
        nonlocal model_run
        model_run = _write_model_run(
            session,
            completion=completion,
            context=call_context,
            messages=prompt_messages,
            status_label="ok",
            error=None,
        )

    last_error: str | None = None
    for _attempt in range(2):
        try:
            response, _completion = generate_structured(
                llm,
                schema=_LLMOutcomeResponse,
                messages=messages,
                context=context,
                temperature=0.0,
                max_tokens=700,
                on_model_run=on_model_run,
                session=session,
            )
            candidates = [
                _Candidate(
                    label=item.label,
                    rationale_snippet=item.rationale_snippet,
                    confidence=0.72,
                )
                for item in response.outcomes
                if item.label != "insufficient_signal"
            ]
            return candidates, model_run.id if model_run else None, None
        except (LLMResponseFormatError, ValueError) as exc:
            last_error = f"malformed_output:{type(exc).__name__}"
            if model_run is not None:
                model_run.status = "malformed_output"
                model_run.error = last_error
            else:
                model_run = _write_error_model_run(
                    session,
                    provider=llm,
                    context=context,
                    messages=messages,
                    status_label="malformed_output",
                    error=last_error,
                )
        except Exception as exc:
            last_error = f"provider_error:{type(exc).__name__}"
            if model_run is None:
                model_run = _write_error_model_run(
                    session,
                    provider=llm,
                    context=context,
                    messages=messages,
                    status_label="error",
                    error=last_error,
                )
            else:
                model_run.status = "error"
                model_run.error = last_error
            break
    return [], model_run.id if model_run else None, last_error or "malformed_output"


def _store_candidates(
    session: Session,
    source: _SourceContext,
    candidates: list[_Candidate],
    *,
    method: str,
    model_run_id: str | None = None,
) -> list[PredictiveOutcomeClassification]:
    if not candidates:
        candidates = [
            _Candidate(
                label="insufficient_signal",
                rationale_snippet="No controlled source-backed outcome marker was found.",
                confidence=0.0,
            )
        ]
    rows: list[PredictiveOutcomeClassification] = []
    for candidate in candidates:
        for signal_type in _SIGNALS_FOR_LABEL[candidate.label]:
            row = _classification_row(
                source,
                label=candidate.label,
                signal_type=signal_type,
                rationale_snippet=candidate.rationale_snippet,
                method=method,
                status="insufficient_signal"
                if candidate.label == "insufficient_signal"
                else "classified",
                confidence=candidate.confidence,
                model_run_id=model_run_id,
            )
            existing = _existing_classification(session, row)
            if existing is not None:
                rows.append(existing)
                continue
            session.add(row)
            rows.append(row)
    session.flush()
    return rows


def _store_quarantine(
    session: Session,
    source: _SourceContext,
    model_run_id: str | None,
    error: str,
) -> PredictiveOutcomeClassification:
    row = _classification_row(
        source,
        label="insufficient_signal",
        signal_type="insufficient_signal",
        rationale_snippet="LLM output could not be validated into controlled labels.",
        method="llm",
        status="quarantined",
        confidence=0.0,
        model_run_id=model_run_id,
        error_message=error,
    )
    existing = _existing_classification(session, row)
    if existing is not None:
        existing.status = "quarantined"
        existing.error_message = error
        return existing
    session.add(row)
    session.flush()
    return row


def _classification_row(
    source: _SourceContext,
    *,
    label: str,
    signal_type: str,
    rationale_snippet: str | None,
    method: str,
    status: str,
    confidence: float,
    model_run_id: str | None = None,
    error_message: str | None = None,
) -> PredictiveOutcomeClassification:
    return PredictiveOutcomeClassification(
        source_type=source.source_type,
        source_id=source.source_id,
        source_hash=_source_hash(source.text),
        company_id=source.company_id,
        matter_id=source.matter_id,
        classification_label=label,
        signal_type=signal_type,
        court_name=source.court_name,
        forum_level=source.forum_level,
        judge_ids_json=json.dumps(list(source.judge_ids)),
        matter_type=source.matter_type,
        party_side=source.party_side,
        decision_year=source.decision_year,
        rationale_snippet=rationale_snippet,
        method=method,
        status=status,
        confidence=confidence,
        model_run_id=model_run_id,
        error_message=error_message,
    )


def _aggregation_groups(
    rows: list[PredictiveOutcomeClassification],
    *,
    year_range: tuple[int, int] | None,
) -> dict[str, _AggregationGroup]:
    groups: dict[str, _AggregationGroup] = {}
    for row in rows:
        year_start, year_end = year_range or _year_window(row.decision_year)
        keys: list[_AggregationGroup] = []
        context_pairs = _context_pairs(row.matter_type, row.party_side)
        if row.court_name or row.forum_level:
            for matter_type, party_side in context_pairs:
                keys.append(
                    _make_group(
                        "court_forum",
                        row.signal_type,
                        court_name=row.court_name,
                        forum_level=row.forum_level,
                        matter_type=matter_type,
                        party_side=party_side,
                        year_start=year_start,
                        year_end=year_end,
                        company_id=row.company_id,
                        matter_id=row.matter_id,
                    )
                )
        for judge_id in _json_list(row.judge_ids_json):
            for matter_type, party_side in context_pairs:
                keys.append(
                    _make_group(
                        "judge",
                        row.signal_type,
                        court_name=row.court_name,
                        forum_level=row.forum_level,
                        judge_id=judge_id,
                        matter_type=matter_type,
                        party_side=party_side,
                        year_start=year_start,
                        year_end=year_end,
                        company_id=row.company_id,
                        matter_id=row.matter_id,
                    )
                )
        if row.matter_type:
            for party_side in tuple(dict.fromkeys((None, row.party_side))):
                keys.append(
                    _make_group(
                        "matter_type",
                        row.signal_type,
                        matter_type=row.matter_type,
                        party_side=party_side,
                        year_start=year_start,
                        year_end=year_end,
                        company_id=row.company_id,
                        matter_id=row.matter_id,
                    )
                )
        for group in keys:
            existing = groups.setdefault(group.scope_key, group)
            existing.rows.append(row)
    return groups


def _context_pairs(
    matter_type: str | None,
    party_side: str | None,
) -> tuple[tuple[str | None, str | None], ...]:
    pairs = [(None, None)]
    if matter_type:
        pairs.append((matter_type, None))
    if party_side:
        pairs.append((None, party_side))
    if matter_type and party_side:
        pairs.append((matter_type, party_side))
    return tuple(dict.fromkeys(pairs))


def _make_group(
    scope_type: str,
    signal_type: str,
    *,
    court_name: str | None = None,
    forum_level: str | None = None,
    judge_id: str | None = None,
    matter_type: str | None = None,
    party_side: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    company_id: str | None = None,
    matter_id: str | None = None,
) -> _AggregationGroup:
    parts = {
        "scope": scope_type,
        "signal": signal_type,
        "court": court_name or "",
        "forum": forum_level or "",
        "judge": judge_id or "",
        "matter_type": matter_type or "",
        "party_side": party_side or "",
        "year_start": year_start or "",
        "year_end": year_end or "",
        "company": company_id or "",
        "matter": matter_id or "",
    }
    scope_key = "|".join(f"{key}:{value}" for key, value in parts.items())
    return _AggregationGroup(
        scope_type=scope_type,
        scope_key=scope_key,
        signal_type=signal_type,
        court_name=court_name,
        forum_level=forum_level,
        judge_id=judge_id,
        matter_type=matter_type,
        party_side=party_side,
        year_start=year_start,
        year_end=year_end,
        company_id=company_id,
        matter_id=matter_id,
    )


def _build_snapshot(group: _AggregationGroup) -> PredictiveOutcomeAggregateSnapshot:
    positive = negative = neutral = 0
    evidence: list[dict[str, str]] = []
    for row in group.rows:
        polarity = _polarity(row.signal_type, row.classification_label)
        if polarity == "positive":
            positive += 1
        elif polarity == "negative":
            negative += 1
        else:
            neutral += 1
        if len(evidence) < MAX_AGGREGATE_EVIDENCE:
            evidence.append(
                {
                    "classification_id": row.id,
                    "source_type": row.source_type,
                    "source_id": row.source_id,
                }
            )
    sample_size = len(group.rows)
    consistency = max(positive, negative, neutral) / sample_size if sample_size else 0.0
    low, high = _wilson_band(positive, sample_size)
    status = "supported" if sample_size >= MIN_AGGREGATE_SAMPLE_SIZE else "insufficient_evidence"
    confidence_label = _aggregate_confidence_label(sample_size, consistency)
    return PredictiveOutcomeAggregateSnapshot(
        scope_type=group.scope_type,
        scope_key=group.scope_key,
        company_id=group.company_id,
        matter_id=group.matter_id,
        court_name=group.court_name,
        forum_level=group.forum_level,
        judge_id=group.judge_id,
        matter_type=group.matter_type,
        party_side=group.party_side,
        year_start=group.year_start,
        year_end=group.year_end,
        signal_type=group.signal_type,
        sample_size=sample_size,
        positive_count=positive,
        negative_count=negative,
        neutral_count=neutral,
        consistency=round(consistency, 4),
        confidence_label=confidence_label if status == "supported" else "insufficient",
        confidence_band_low=round(low, 4) if status == "supported" else None,
        confidence_band_high=round(high, 4) if status == "supported" else None,
        evidence_source_ids_json=json.dumps(evidence),
        feature_summary_json=json.dumps(
            {
                "method": "source_outcome_label_frequency",
                "positive_count": positive,
                "negative_count": negative,
                "neutral_count": neutral,
                "consistency": round(consistency, 4),
                "source_court_names": sorted(
                    {row.court_name for row in group.rows if row.court_name}
                ),
                "source_forum_levels": sorted(
                    {row.forum_level for row in group.rows if row.forum_level}
                ),
                "source_judge_ids": sorted(
                    {
                        judge_id
                        for row in group.rows
                        for judge_id in _json_list(row.judge_ids_json)
                    }
                ),
            }
        ),
        status=status,
    )


def _copy_snapshot(
    target: PredictiveOutcomeAggregateSnapshot,
    source: PredictiveOutcomeAggregateSnapshot,
) -> None:
    for attr in (
        "scope_type",
        "company_id",
        "matter_id",
        "court_name",
        "forum_level",
        "judge_id",
        "matter_type",
        "party_side",
        "year_start",
        "year_end",
        "signal_type",
        "sample_size",
        "positive_count",
        "negative_count",
        "neutral_count",
        "consistency",
        "confidence_label",
        "confidence_band_low",
        "confidence_band_high",
        "evidence_source_ids_json",
        "feature_summary_json",
        "status",
    ):
        setattr(target, attr, getattr(source, attr))


def _write_model_run(
    session: Session,
    *,
    completion: LLMCompletion,
    context: LLMCallContext,
    messages: list[LLMMessage],
    status_label: str,
    error: str | None,
) -> ModelRun:
    run = ModelRun(
        company_id=context.tenant_id,
        matter_id=context.matter_id,
        purpose=PURPOSE,
        provider=completion.provider,
        model=completion.model,
        prompt_hash=_prompt_hash(messages),
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
        status=status_label,
        error=error,
    )
    session.add(run)
    session.flush()
    return run


def _write_error_model_run(
    session: Session,
    *,
    provider: LLMProvider,
    context: LLMCallContext,
    messages: list[LLMMessage],
    status_label: str,
    error: str,
) -> ModelRun:
    run = ModelRun(
        company_id=context.tenant_id,
        matter_id=context.matter_id,
        purpose=PURPOSE,
        provider=getattr(provider, "name", "unknown"),
        model=getattr(provider, "model", "unknown"),
        prompt_hash=_prompt_hash(messages),
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
        status=status_label,
        error=error,
    )
    session.add(run)
    session.flush()
    return run


def _classification_messages(source: _SourceContext) -> list[LLMMessage]:
    labels = ", ".join(sorted(CONTROLLED_OUTCOME_LABELS))
    return [
        LLMMessage(
            role="system",
            content=(
                "You classify legal source text into controlled outcome labels. "
                "Use only the provided source text. Do not infer probabilities, "
                "odds, win/loss predictions, emotions, or legal advice."
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                "Respond with JSON matching this shape exactly: "
                '{"outcomes":[{"label":"<controlled_label>",'
                '"rationale_snippet":"<short copied source phrase>"}]}.\n'
                f"Allowed labels: {labels}.\n"
                "If the source does not clearly support a label, return "
                '{"outcomes":[{"label":"insufficient_signal",'
                '"rationale_snippet":"no controlled outcome marker found"}]}.\n'
                f"SOURCE_TYPE: {source.source_type}\n"
                f"SOURCE_ID: {source.source_id}\n"
                f"SOURCE_TEXT:\n{source.text[:6000]}"
            ),
        ),
    ]


def _usable_authority_text(document: AuthorityDocument) -> str | None:
    text = document.document_text
    if not text or len(text.strip()) < 40:
        return None
    return text


def _usable_order_text(order: MatterCourtOrder) -> str | None:
    text = order.order_text
    if not text or len(text.strip()) < 40:
        return None
    return text


def _delete_source_classifications(session: Session, source_type: str, source_id: str) -> None:
    session.execute(
        delete(PredictiveOutcomeClassification).where(
            PredictiveOutcomeClassification.source_type == source_type,
            PredictiveOutcomeClassification.source_id == source_id,
        )
    )
    session.flush()


def _source_already_classified(session: Session, source_type: str, source_id: str) -> bool:
    return session.scalar(
        select(PredictiveOutcomeClassification.id)
        .where(
            PredictiveOutcomeClassification.source_type == source_type,
            PredictiveOutcomeClassification.source_id == source_id,
        )
        .limit(1)
    ) is not None


def _existing_classification(
    session: Session,
    row: PredictiveOutcomeClassification,
) -> PredictiveOutcomeClassification | None:
    return session.scalar(
        select(PredictiveOutcomeClassification)
        .where(
            PredictiveOutcomeClassification.source_type == row.source_type,
            PredictiveOutcomeClassification.source_id == row.source_id,
            PredictiveOutcomeClassification.classification_label == row.classification_label,
            PredictiveOutcomeClassification.signal_type == row.signal_type,
        )
        .limit(1)
    )


def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prompt_hash(messages: list[LLMMessage]) -> str:
    h = hashlib.sha256()
    for message in messages:
        h.update(message.role.encode("utf-8"))
        h.update(b"\x00")
        h.update(message.content.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _derive_matter_type(*parts: str | None) -> str:
    text = _normalise_text(" ".join(part for part in parts if part))
    mapping = {
        "bail": "criminal",
        "criminal": "criminal",
        "arbitration": "arbitration",
        "writ": "writ",
        "cheque": "commercial",
        "insolvency": "commercial",
        "company": "commercial",
        "commercial": "commercial",
        "family": "family",
        "divorce": "family",
        "consumer": "consumer",
    }
    for token, matter_type in mapping.items():
        if token in text:
            return matter_type
    return "general"


def _normalise_matter_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower().replace(" ", "_")


def _infer_party_side(text: str) -> str | None:
    lowered = _normalise_text(text)
    for side in ("petitioner", "appellant", "applicant", "respondent"):
        if side in lowered:
            return side
    return None


def _normalise_text(text: str) -> str:
    return " ".join(text.lower().split())


def _token_present(haystack: str, token: str) -> bool:
    return token.lower() in haystack


def _snippet(text: str, token: str, limit: int = 360) -> str:
    lowered = text.lower()
    index = lowered.find(token.lower())
    if index < 0:
        compact = " ".join(text.split())
        return compact[:limit]
    start = max(0, index - 120)
    end = min(len(text), index + len(token) + 220)
    return " ".join(text[start:end].split())[:limit]


def _json_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(item for item in payload if isinstance(item, str) and item)


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _feature_string_set(payload: dict[str, Any], key: str) -> set[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _year_window(year: int | None) -> tuple[int | None, int | None]:
    if year is None:
        return (None, None)
    return (year - 4, year)


def _polarity(signal_type: str, label: str) -> str:
    if label in _POSITIVE_BY_SIGNAL.get(signal_type, set()):
        return "positive"
    if label in _NEGATIVE_BY_SIGNAL.get(signal_type, set()):
        return "negative"
    return "neutral"


def _aggregate_confidence_label(sample_size: int, consistency: float) -> str:
    if sample_size < MIN_AGGREGATE_SAMPLE_SIZE:
        return "insufficient"
    if sample_size >= 20 and consistency >= 0.75:
        return "high"
    if sample_size >= 10 and consistency >= 0.6:
        return "medium"
    return "low"


def _wilson_band(successes: int, sample_size: int) -> tuple[float, float]:
    if sample_size <= 0:
        return (0.0, 0.0)
    z = 1.96
    phat = successes / sample_size
    denominator = 1 + (z**2 / sample_size)
    centre = (phat + (z**2 / (2 * sample_size))) / denominator
    margin = (
        z
        * math.sqrt((phat * (1 - phat) + (z**2 / (4 * sample_size))) / sample_size)
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _dedupe_snapshots(
    snapshots: list[PredictiveOutcomeAggregateSnapshot],
) -> list[PredictiveOutcomeAggregateSnapshot]:
    by_key: dict[str, PredictiveOutcomeAggregateSnapshot] = {}
    for snapshot in snapshots:
        existing = by_key.get(snapshot.scope_key)
        if existing is None or snapshot.sample_size > existing.sample_size:
            by_key[snapshot.scope_key] = snapshot
    by_signal: dict[str, PredictiveOutcomeAggregateSnapshot] = {}
    for snapshot in by_key.values():
        existing = by_signal.get(snapshot.signal_type)
        if existing is None or _snapshot_rank(snapshot) > _snapshot_rank(existing):
            by_signal[snapshot.signal_type] = snapshot
    return list(by_signal.values())


def _snapshot_rank(snapshot: PredictiveOutcomeAggregateSnapshot) -> tuple[int, int]:
    scope_score = {"judge": 3, "court_forum": 2, "matter_type": 1}.get(
        snapshot.scope_type,
        0,
    )
    return (scope_score, snapshot.sample_size)


def stats_to_dict(stats: ClassificationStats) -> dict[str, Any]:
    return {
        "processed": stats.processed,
        "classified": stats.classified,
        "skipped": stats.skipped,
        "quarantined": stats.quarantined,
        "dry_run": stats.dry_run,
        "aggregate_snapshots": stats.aggregate_snapshots,
        "estimated_llm_cost_usd": stats.estimated_llm_cost_usd,
    }


__all__ = [
    "CONTROLLED_OUTCOME_LABELS",
    "PREDICTIVE_SIGNAL_TYPES",
    "backfill_predictive_outcomes",
    "classify_authority_document",
    "classify_matter_court_order",
    "load_predictive_aggregate_snapshots_for_matter",
    "official_predictive_authority_sources",
    "refresh_predictive_aggregate_snapshots",
    "stats_to_dict",
]
