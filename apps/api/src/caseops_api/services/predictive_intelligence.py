"""Controlled predictive litigation intelligence foundation.

LI-S7A is a data-contract and API foundation. It is deliberately
deterministic: no LLM is asked to estimate probabilities, and every
supported signal must carry source IDs, sample size, confidence band,
feature explanation, limitation note, tenant policy gate, and audit.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    Judge,
    JudgeDecisionIndex,
    Matter,
    MatterCauseListEntry,
    MatterCourtOrder,
    PredictiveOutcomeAggregateSnapshot,
    PredictiveOutcomeClassification,
    PredictiveSignalEvidence,
    PredictiveSignalItem,
    PredictiveSignalRun,
)
from caseops_api.schemas.predictive_intelligence import (
    BenchContextScope,
    BenchContextSummary,
    BenchPredictiveSummary,
    CalibratedPredictiveSignal,
    CalibratedSignalScope,
    HearingPrepScorecard,
    MatterRiskSummary,
    ObservedSignalDistribution,
    PredictionConfidence,
    PredictionFeatureContribution,
    PredictiveEvidence,
    PredictiveIntelligenceResponse,
    PredictiveSignal,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.authority_sources import is_source_allowed_for_predictive_aggregates
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.predictive_outcomes import (
    load_predictive_aggregate_snapshots_for_matter,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.tenant_ai_policy import resolve_tenant_policy

DISCLAIMER = (
    "Predictive intelligence is statistical decision support based on indexed "
    "sources only, not legal advice. Verify against primary sources and apply "
    "lawyer review before relying on it."
)
LIMITATION_NOTE = (
    "This signal reflects only the indexed source sample available to CaseOps "
    "for this tenant-scoped matter. It is not a legal-advice opinion and must "
    "be reviewed by a lawyer before use."
)
MIN_SAMPLE_SIZE = 5
MAX_EVIDENCE_PER_SIGNAL = 10

_POSITIVE_OUTCOME_TOKENS = (
    "allowed",
    "allow",
    "granted",
    "grant",
    "relief granted",
    "quashed",
    "set aside",
    "accepted",
    "partly allowed",
    "partly granted",
)
_ADVERSE_OUTCOME_TOKENS = (
    "dismissed",
    "dismiss",
    "rejected",
    "reject",
    "refused",
    "denied",
    "adverse",
)
_SETTLEMENT_TOKENS = ("settled", "settlement", "compromise", "mediation", "consent")
_INTERIM_TOKENS = ("interim", "temporary", "ad-interim", "injunction", "status quo")
_NOTICE_TOKENS = ("notice", "issue notice", "notice issued")
_ADJOURNMENT_TOKENS = ("adjourn", "adjourned", "renotify", "re-notify")
_STAY_TOKENS = ("stay", "stayed", "status quo")
_AGGREGATE_SIGNAL_LABELS = {
    "bench_outcome_tendency": "Bench/forum outcome tendency",
    "interim_relief_likelihood": "Interim relief likelihood",
    "stay_likelihood": "Stay likelihood",
    "notice_issuance_likelihood": "Notice issuance likelihood",
    "adjournment_likelihood": "Adjournment likelihood",
    "disposal_delay_risk": "Disposal/delay risk",
    "adverse_order_risk": "Adverse order risk",
    "settlement_inclination_signal": "Settlement inclination signal",
    "bench_party_side_tendency": "Bench/party-side tendency",
    "forum_practice_pattern": "Forum practice pattern",
}
_AGGREGATE_SIGNAL_ORDER = tuple(_AGGREGATE_SIGNAL_LABELS)


@dataclass(frozen=True)
class _BenchDocument:
    document: AuthorityDocument
    judge_id: str


@dataclass(frozen=True)
class _OutcomeStats:
    sample_size: int
    positive_count: int
    adverse_count: int
    neutral_count: int
    docs: tuple[AuthorityDocument, ...]


def build_predictive_intelligence(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> PredictiveIntelligenceResponse:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)

    policy = resolve_tenant_policy(session, company_id=context.company.id)
    if not policy.predictive_bench_strategy_enabled:
        record_from_context(
            session,
            context,
            action="predictive_intelligence.viewed",
            target_type="matter",
            target_id=matter.id,
            matter_id=matter.id,
            result="denied",
            metadata={"reason": "tenant_policy_disabled"},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Predictive intelligence is disabled by tenant AI policy.",
        )

    matter = require_operational_matter(
        session,
        matter=matter,
        operation="build predictive intelligence",
        lock_for_write=False,
    )
    bench_judge_ids = _resolve_bench_judge_ids(session, matter)
    aggregate_snapshots = load_predictive_aggregate_snapshots_for_matter(
        session,
        matter=matter,
        judge_ids=bench_judge_ids,
    )
    signals = _build_aggregate_signals(
        session,
        matter=matter,
        snapshots=aggregate_snapshots,
    )
    calibrated_signals = _build_calibrated_signals(
        session,
        matter=matter,
        snapshots=aggregate_snapshots,
    )
    bench_context = _build_bench_context_summary(
        session,
        matter=matter,
        bench_judge_ids=bench_judge_ids,
        snapshots=aggregate_snapshots,
        signals=signals,
    )
    evidence_quality = _evidence_quality(
        max((signal.sample_size for signal in signals), default=0)
    )
    matter_risk = _build_matter_risk_summary(matter.id, signals)
    hearing_scorecard = _build_hearing_scorecard(matter.id)

    matter = require_operational_matter(
        session,
        matter=matter,
        operation="build predictive intelligence",
    )
    run = _persist_run(
        session,
        context=context,
        matter=matter,
        evidence_quality=evidence_quality,
        signals=signals,
        matter_risk=matter_risk,
        hearing_scorecard=hearing_scorecard,
    )

    record_from_context(
        session,
        context,
        action="predictive_intelligence.generated",
        target_type="predictive_signal_run",
        target_id=run.id,
        matter_id=matter.id,
        metadata={
            "supported_signal_types": [
                signal.signal_type for signal in signals if signal.status == "supported"
            ],
            "insufficient_signal_types": [
                signal.signal_type
                for signal in signals
                if signal.status == "insufficient_evidence"
            ],
            "sample_size": run.sample_size,
            "evidence_quality": evidence_quality,
            "supported_calibrated_signal_types": [
                signal.signal_type
                for signal in calibrated_signals
                if signal.status == "supported"
            ],
        },
    )
    session.commit()

    return PredictiveIntelligenceResponse(
        matter_id=matter.id,
        mode="predictive",
        tenant_policy_enabled=True,
        generated_at=run.created_at,
        run_id=run.id,
        bench_summary=BenchPredictiveSummary(
            matter_id=matter.id,
            bench_judge_ids=list(bench_judge_ids),
            evidence_quality=evidence_quality,
            signals=signals,
            disclaimer=DISCLAIMER,
        ),
        bench_context=bench_context,
        calibrated_signals=calibrated_signals,
        matter_risk_summary=matter_risk,
        hearing_prep_scorecard=hearing_scorecard,
        disclaimer=DISCLAIMER,
    )


def _resolve_bench_judge_ids(session: Session, matter: Matter) -> tuple[str, ...]:
    entries = list(
        session.scalars(
            select(MatterCauseListEntry)
            .where(MatterCauseListEntry.matter_id == matter.id)
            .order_by(
                MatterCauseListEntry.listing_date.desc(),
                MatterCauseListEntry.created_at.desc(),
            )
            .limit(20)
        )
    )
    resolved: list[str] = []
    for entry in entries:
        for judge_id in _judge_ids_from_json(entry.judges_json):
            if judge_id not in resolved:
                resolved.append(judge_id)
        if resolved:
            return tuple(resolved)

    if matter.judge_name:
        stmt = select(Judge.id).where(Judge.full_name == matter.judge_name)
        if matter.court_id:
            stmt = stmt.where(Judge.court_id == matter.court_id)
        judge_id = session.scalar(stmt.limit(1))
        if judge_id:
            return (judge_id,)
    return ()


def _judge_ids_from_json(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    ids: list[str] = []
    for item in parsed:
        if isinstance(item, dict) and isinstance(item.get("judge_id"), str):
            ids.append(item["judge_id"])
    return tuple(ids)


def _load_bench_documents(
    session: Session,
    bench_judge_ids: Sequence[str],
) -> tuple[_BenchDocument, ...]:
    if not bench_judge_ids:
        return ()
    rows = session.execute(
        select(JudgeDecisionIndex, AuthorityDocument)
        .join(
            AuthorityDocument,
            AuthorityDocument.id == JudgeDecisionIndex.authority_document_id,
        )
        .where(JudgeDecisionIndex.judge_id.in_(bench_judge_ids))
        .where(JudgeDecisionIndex.is_analytics_eligible.is_(True))
        .order_by(
            AuthorityDocument.decision_date.desc().nullslast(),
            AuthorityDocument.created_at.desc(),
        )
        .limit(200)
    ).all()
    seen_docs: set[str] = set()
    docs: list[_BenchDocument] = []
    for index_row, document in rows:
        if document.id in seen_docs:
            continue
        if not is_source_allowed_for_predictive_aggregates(document.source):
            continue
        seen_docs.add(document.id)
        docs.append(_BenchDocument(document=document, judge_id=index_row.judge_id))
    return tuple(docs)


def _load_court_orders(session: Session, matter_id: str) -> tuple[MatterCourtOrder, ...]:
    return tuple(
        session.scalars(
            select(MatterCourtOrder)
            .where(MatterCourtOrder.matter_id == matter_id)
            .order_by(
                MatterCourtOrder.order_date.desc(),
                MatterCourtOrder.created_at.desc(),
            )
            .limit(200)
        )
    )


def _load_cause_list_entries(
    session: Session,
    matter_id: str,
) -> tuple[MatterCauseListEntry, ...]:
    return tuple(
        session.scalars(
            select(MatterCauseListEntry)
            .where(MatterCauseListEntry.matter_id == matter_id)
            .order_by(
                MatterCauseListEntry.listing_date.desc(),
                MatterCauseListEntry.created_at.desc(),
            )
            .limit(200)
        )
    )


def _build_bench_context_summary(
    session: Session,
    *,
    matter: Matter,
    bench_judge_ids: Sequence[str],
    snapshots: Sequence[PredictiveOutcomeAggregateSnapshot],
    signals: Sequence[PredictiveSignal],
) -> BenchContextSummary:
    judge_names = _judge_names(session, bench_judge_ids)
    bench_documents = _load_bench_documents(session, bench_judge_ids)
    distributions = _observed_distributions(snapshots)
    supported_signals = [signal for signal in signals if signal.status == "supported"]
    evidence = _dedupe_evidence(
        [item for signal in supported_signals for item in signal.evidence]
    )
    if not evidence and bench_documents:
        evidence = _evidence_from_authority_docs(
            [item.document for item in bench_documents[:MAX_EVIDENCE_PER_SIGNAL]]
        )

    sample_size = max(
        [len(bench_documents), *(distribution.sample_size for distribution in distributions)],
        default=0,
    )
    years = _bench_context_year_window(bench_documents, snapshots)
    scope = BenchContextScope(
        court_name=matter.court_name,
        forum_level=matter.forum_level,
        bench_name=matter.judge_name or ", ".join(judge_names) or None,
        judge_ids=list(bench_judge_ids),
        judge_names=judge_names,
        matter_type=matter.practice_area,
        year_start=years[0],
        year_end=years[1],
    )

    missing_data: list[str] = []
    if not bench_judge_ids:
        missing_data.append("Resolved bench or judge IDs for this matter.")
    if sample_size < MIN_SAMPLE_SIZE:
        missing_data.append("At least five indexed source judgments/orders for this bench.")
    if not distributions:
        missing_data.append("LI-S7B outcome aggregate snapshots for the matched bench/forum.")
    if not evidence:
        missing_data.append("Cited source judgment/order IDs for bench context evidence.")

    if supported_signals and evidence and distributions:
        status_label = "supported"
        confidence = _strongest_signal_confidence(supported_signals)
        limitation = (
            "Bench context is derived from indexed source classifications and cited "
            "judgments/orders. It is decision support only, not legal advice or a "
            "personal reputation claim."
        )
    elif evidence:
        status_label = "limited_context"
        confidence = _insufficient_confidence(sample_size)
        limitation = (
            "Bench context is limited to source-linked indexed judgments/orders. "
            "No supported predictive distribution is available for this matter yet."
        )
    else:
        status_label = "insufficient_evidence"
        confidence = _insufficient_confidence(sample_size)
        limitation = (
            "Bench context cannot be generated until source-linked bench history "
            "and aggregate outcome evidence are available."
        )

    return BenchContextSummary(
        matter_id=matter.id,
        status=status_label,  # type: ignore[arg-type]
        scope=scope,
        sample_size=sample_size,
        evidence_quality=_evidence_quality(sample_size),
        confidence=confidence,
        observed_distribution=distributions,
        evidence=evidence,
        missing_data=missing_data,
        limitation_note=limitation,
        disclaimer=DISCLAIMER,
    )


def _judge_names(session: Session, judge_ids: Sequence[str]) -> list[str]:
    if not judge_ids:
        return []
    rows = session.execute(
        select(Judge.id, Judge.full_name).where(Judge.id.in_(judge_ids))
    ).all()
    by_id = {row.id: row.full_name for row in rows}
    return [by_id[judge_id] for judge_id in judge_ids if judge_id in by_id]


def _observed_distributions(
    snapshots: Sequence[PredictiveOutcomeAggregateSnapshot],
) -> list[ObservedSignalDistribution]:
    distributions: list[ObservedSignalDistribution] = []
    for snapshot in snapshots:
        if snapshot.status != "supported":
            continue
        distributions.append(
            ObservedSignalDistribution(
                signal_type=snapshot.signal_type,
                label=_AGGREGATE_SIGNAL_LABELS.get(
                    snapshot.signal_type,
                    _format_signal_label(snapshot.signal_type),
                ),
                sample_size=snapshot.sample_size,
                positive_count=snapshot.positive_count,
                negative_count=snapshot.negative_count,
                neutral_count=snapshot.neutral_count,
                year_start=snapshot.year_start,
                year_end=snapshot.year_end,
            )
        )
    distributions.sort(key=lambda item: (-item.sample_size, item.signal_type))
    return distributions


def _bench_context_year_window(
    bench_documents: Sequence[_BenchDocument],
    snapshots: Sequence[PredictiveOutcomeAggregateSnapshot],
) -> tuple[int | None, int | None]:
    years: list[int] = []
    for item in bench_documents:
        if item.document.decision_date:
            years.append(item.document.decision_date.year)
    for snapshot in snapshots:
        if snapshot.year_start is not None:
            years.append(snapshot.year_start)
        if snapshot.year_end is not None:
            years.append(snapshot.year_end)
    if not years:
        return (None, None)
    return (min(years), max(years))


def _dedupe_evidence(evidence: Sequence[PredictiveEvidence]) -> list[PredictiveEvidence]:
    seen: set[tuple[str, str]] = set()
    out: list[PredictiveEvidence] = []
    for item in evidence:
        key = (item.source_type, item.source_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= MAX_EVIDENCE_PER_SIGNAL:
            break
    return out


def _strongest_signal_confidence(signals: Sequence[PredictiveSignal]) -> PredictionConfidence:
    ordered = {"high": 3, "medium": 2, "low": 1, "insufficient": 0}
    return max(
        (signal.confidence for signal in signals),
        key=lambda item: (ordered.get(item.label, 0), item.sample_size),
    )


def _format_signal_label(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("_") if part)


def _build_aggregate_signals(
    session: Session,
    *,
    matter: Matter,
    snapshots: Sequence[PredictiveOutcomeAggregateSnapshot],
) -> list[PredictiveSignal]:
    by_signal: dict[str, PredictiveOutcomeAggregateSnapshot] = {
        snapshot.signal_type: snapshot for snapshot in snapshots
    }
    if "bench_party_side_tendency" in by_signal:
        by_signal["bench_outcome_tendency"] = by_signal["bench_party_side_tendency"]

    signals: list[PredictiveSignal] = []
    for signal_type in _AGGREGATE_SIGNAL_ORDER:
        snapshot = by_signal.get(signal_type)
        if snapshot is None or snapshot.status != "supported":
            sample_size = snapshot.sample_size if snapshot is not None else 0
            signals.append(
                _insufficient_signal(
                    signal_type=signal_type,
                    label=_AGGREGATE_SIGNAL_LABELS[signal_type],
                    sample_size=sample_size,
                    missing_data=[
                        (
                            "Stored LI-S7B aggregate snapshots with at least "
                            "five source classifications."
                        ),
                        "Source judgment/order IDs for every aggregate evidence row.",
                    ],
                )
            )
            continue
        signals.append(_signal_from_aggregate_snapshot(session, matter, signal_type, snapshot))
    return signals


def _signal_from_aggregate_snapshot(
    session: Session,
    matter: Matter,
    signal_type: str,
    snapshot: PredictiveOutcomeAggregateSnapshot,
) -> PredictiveSignal:
    evidence = _evidence_from_aggregate_snapshot(session, matter, snapshot)
    if not evidence:
        return _insufficient_signal(
            signal_type=signal_type,
            label=_AGGREGATE_SIGNAL_LABELS[signal_type],
            sample_size=snapshot.sample_size,
            missing_data=[
                "Aggregate snapshot exists but has no resolvable source evidence IDs.",
                "Re-run LI-S7B backfill to rebuild source lineage.",
            ],
        )
    evidence_ids = [item.id for item in evidence]
    direction = _aggregate_direction(snapshot)
    return PredictiveSignal(
        signal_type=signal_type,
        label=_AGGREGATE_SIGNAL_LABELS[signal_type],
        status="supported",
        estimate_label=_aggregate_estimate_label(snapshot),
        sample_size=snapshot.sample_size,
        confidence=PredictionConfidence(
            label=snapshot.confidence_label,  # type: ignore[arg-type]
            sample_size=snapshot.sample_size,
            confidence_band_low=snapshot.confidence_band_low,
            confidence_band_high=snapshot.confidence_band_high,
            method="classified_source_outcome_frequency_wilson_95",
            limitations=[
                "Confidence bands describe historical indexed source classifications only.",
                "No LLM-only or intuition-only estimate is used.",
                "Source mix, forum assignment, pleadings, and law may differ in the live matter.",
            ],
        ),
        evidence=evidence,
        features=[
            PredictionFeatureContribution(
                feature_key="classified_outcome_distribution",
                label="Classified outcome distribution",
                direction=direction,
                weight=1.0,
                explanation=(
                    "Stored LI-S7B classifications were grouped by source-backed "
                    "outcome labels for the matching bench/forum context."
                ),
                evidence_ids=evidence_ids,
            )
        ],
        limitation_note=LIMITATION_NOTE,
        disclaimer=DISCLAIMER,
    )


def _build_calibrated_signals(
    session: Session,
    *,
    matter: Matter,
    snapshots: Sequence[PredictiveOutcomeAggregateSnapshot],
) -> list[CalibratedPredictiveSignal]:
    by_signal: dict[str, PredictiveOutcomeAggregateSnapshot] = {
        snapshot.signal_type: snapshot for snapshot in snapshots
    }
    if "bench_party_side_tendency" in by_signal:
        by_signal["bench_outcome_tendency"] = by_signal["bench_party_side_tendency"]

    calibrated: list[CalibratedPredictiveSignal] = []
    for signal_type in _AGGREGATE_SIGNAL_ORDER:
        snapshot = by_signal.get(signal_type)
        if snapshot is None:
            calibrated.append(
                _insufficient_calibrated_signal(
                    signal_type=signal_type,
                    label=_AGGREGATE_SIGNAL_LABELS[signal_type],
                    sample_size=0,
                    scope=CalibratedSignalScope(
                        court_name=matter.court_name,
                        forum_level=matter.forum_level,
                        matter_type=matter.practice_area,
                    ),
                    missing_data=[
                        "Stored LI-S7B aggregate snapshot for this signal and matter scope.",
                        "Source judgment/order IDs for aggregate evidence.",
                    ],
                )
            )
            continue
        calibrated.append(
            _calibrated_signal_from_snapshot(
                session,
                matter=matter,
                signal_type=signal_type,
                snapshot=snapshot,
            )
        )
    return calibrated


def _calibrated_signal_from_snapshot(
    session: Session,
    *,
    matter: Matter,
    signal_type: str,
    snapshot: PredictiveOutcomeAggregateSnapshot,
) -> CalibratedPredictiveSignal:
    scope = _calibrated_scope(snapshot)
    evidence = _evidence_from_aggregate_snapshot(session, matter, snapshot)
    missing_data: list[str] = []
    if snapshot.sample_size < MIN_SAMPLE_SIZE:
        missing_data.append(
            f"At least {MIN_SAMPLE_SIZE} source classifications for calibrated output."
        )
    if not evidence:
        missing_data.append("Resolvable source evidence IDs for this aggregate snapshot.")
    if snapshot.status != "supported":
        missing_data.append("Supported aggregate snapshot status.")

    if snapshot.status == "supported" and snapshot.sample_size >= MIN_SAMPLE_SIZE and evidence:
        status_label = "supported"
        observed_rate = round(snapshot.positive_count / snapshot.sample_size, 4)
        confidence = PredictionConfidence(
            label=snapshot.confidence_label,  # type: ignore[arg-type]
            sample_size=snapshot.sample_size,
            confidence_band_low=snapshot.confidence_band_low,
            confidence_band_high=snapshot.confidence_band_high,
            method="calibrated_classified_source_frequency_wilson_95",
            limitations=[
                "Observed rates are historical indexed-source distributions only.",
                (
                    "No LLM-only estimate, uncited bench-profile claim, "
                    "or legal-advice conclusion is used."
                ),
                "Calibration depends on source coverage, matter type, forum, and year window.",
            ],
        )
        limitation = (
            "Calibrated signal is computed from stored LI-S7B outcome classifications "
            "and aggregate snapshot counts. It is an observed historical pattern for "
            "source-backed decision support, not legal advice."
        )
    elif evidence:
        status_label = "limited_context"
        observed_rate = None
        confidence = _insufficient_confidence(snapshot.sample_size)
        limitation = (
            "Calibrated context has source links but does not meet the supported "
            "sample or aggregate-status threshold."
        )
    else:
        status_label = "insufficient_evidence"
        observed_rate = None
        confidence = _insufficient_confidence(snapshot.sample_size)
        limitation = (
            "Calibrated signal cannot be shown until the aggregate snapshot has "
            "sufficient sample size and source evidence IDs."
        )

    return CalibratedPredictiveSignal(
        signal_type=signal_type,
        label=_AGGREGATE_SIGNAL_LABELS.get(signal_type, _format_signal_label(signal_type)),
        status=status_label,  # type: ignore[arg-type]
        scope=scope,
        sample_size=snapshot.sample_size,
        observed_rate=observed_rate,
        positive_count=snapshot.positive_count,
        negative_count=snapshot.negative_count,
        neutral_count=snapshot.neutral_count,
        confidence=confidence,
        calibration_level=confidence.label,
        evidence_quality=_evidence_quality(snapshot.sample_size),
        evidence=evidence,
        missing_data=missing_data,
        limitation_note=limitation,
        aggregate_snapshot_id=snapshot.id,
        generated_at=snapshot.refreshed_at,
        disclaimer=DISCLAIMER,
    )


def _calibrated_scope(snapshot: PredictiveOutcomeAggregateSnapshot) -> CalibratedSignalScope:
    return CalibratedSignalScope(
        scope_type=snapshot.scope_type,
        scope_key=snapshot.scope_key,
        court_name=snapshot.court_name,
        forum_level=snapshot.forum_level,
        judge_id=snapshot.judge_id,
        matter_type=snapshot.matter_type,
        party_side=snapshot.party_side,
        year_start=snapshot.year_start,
        year_end=snapshot.year_end,
    )


def _insufficient_calibrated_signal(
    *,
    signal_type: str,
    label: str,
    sample_size: int,
    scope: CalibratedSignalScope,
    missing_data: list[str],
) -> CalibratedPredictiveSignal:
    return CalibratedPredictiveSignal(
        signal_type=signal_type,
        label=label,
        status="insufficient_evidence",
        scope=scope,
        sample_size=sample_size,
        observed_rate=None,
        confidence=_insufficient_confidence(sample_size),
        calibration_level="insufficient",
        evidence_quality=_evidence_quality(sample_size),
        missing_data=missing_data,
        limitation_note=(
            "Calibrated signal requires stored source-backed aggregate snapshots "
            "with sample size, confidence band, and evidence IDs."
        ),
        disclaimer=DISCLAIMER,
    )


def _evidence_from_aggregate_snapshot(
    session: Session,
    matter: Matter,
    snapshot: PredictiveOutcomeAggregateSnapshot,
) -> list[PredictiveEvidence]:
    evidence_refs = _snapshot_evidence_refs(snapshot.evidence_source_ids_json)
    if not evidence_refs:
        return []
    classification_ids = [
        ref["classification_id"]
        for ref in evidence_refs
        if isinstance(ref.get("classification_id"), str)
    ]
    if not classification_ids:
        return []
    rows = list(
        session.scalars(
            select(PredictiveOutcomeClassification).where(
                PredictiveOutcomeClassification.id.in_(classification_ids)
            )
        )
    )
    by_id = {row.id: row for row in rows}
    evidence: list[PredictiveEvidence] = []
    for ref in evidence_refs:
        row = by_id.get(str(ref.get("classification_id")))
        if row is None:
            continue
        if row.source_type == "authority_document":
            doc = session.get(AuthorityDocument, row.source_id)
            if doc is None:
                continue
            evidence.append(
                PredictiveEvidence(
                    id=f"predictive_outcome_classification:{row.id}",
                    source_type="authority_document",
                    source_id=doc.id,
                    title=doc.title,
                    source_reference=(
                        doc.source_reference or doc.neutral_citation or doc.case_reference
                    ),
                    excerpt=row.rationale_snippet or _trim(doc.document_text),
                    source_date=doc.decision_date.isoformat() if doc.decision_date else None,
                    weight=1.0,
                )
            )
        elif row.source_type == "matter_court_order" and row.matter_id == matter.id:
            order = session.get(MatterCourtOrder, row.source_id)
            if order is None:
                continue
            evidence.append(
                PredictiveEvidence(
                    id=f"predictive_outcome_classification:{row.id}",
                    source_type="matter_court_order",
                    source_id=order.id,
                    title=order.title,
                    source_reference=order.source_reference,
                    excerpt=row.rationale_snippet or _trim(order.order_text),
                    source_date=order.order_date.isoformat(),
                    weight=1.0,
                )
            )
    return evidence


def _snapshot_evidence_refs(raw: str | None) -> list[dict[str, object]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _aggregate_direction(snapshot: PredictiveOutcomeAggregateSnapshot) -> str:
    if snapshot.positive_count > snapshot.negative_count:
        return "supports"
    if snapshot.negative_count > snapshot.positive_count:
        return "weakens"
    return "neutral"


def _aggregate_estimate_label(snapshot: PredictiveOutcomeAggregateSnapshot) -> str:
    if snapshot.positive_count > snapshot.negative_count:
        return "higher historical positive source-label band"
    if snapshot.negative_count > snapshot.positive_count:
        return "higher historical adverse source-label band"
    return "mixed historical source-label band"


def _build_bench_signals(
    *,
    matter_id: str,
    bench_documents: Sequence[_BenchDocument],
    court_orders: Sequence[MatterCourtOrder],
    cause_entries: Sequence[MatterCauseListEntry],
) -> list[PredictiveSignal]:
    outcome_stats = _outcome_stats(bench_documents)
    return [
        _build_outcome_signal(outcome_stats),
        _build_keyword_document_signal(
            signal_type="interim_relief_likelihood",
            label="Interim relief likelihood",
            docs=[item.document for item in bench_documents],
            tokens=_INTERIM_TOKENS,
            missing_data=[
                (
                    "At least five indexed bench decisions or matter orders "
                    "with interim-relief markers."
                ),
                "Outcome labels or order-kind metadata from official/licensed sources.",
            ],
        ),
        _build_keyword_document_signal(
            signal_type="notice_issuance_likelihood",
            label="Notice issuance likelihood",
            docs=[item.document for item in bench_documents],
            tokens=_NOTICE_TOKENS,
            missing_data=[
                "At least five indexed bench decisions or orders with notice-issuance markers.",
                "Source-linked cause-list/order data for the same forum context.",
            ],
        ),
        _build_adjournment_signal(cause_entries),
        _build_stay_interim_frequency_signal(court_orders),
        _build_disposal_delay_signal(cause_entries),
        _build_keyword_document_signal(
            signal_type="settlement_inclination_signal",
            label="Settlement inclination signal",
            docs=[item.document for item in bench_documents],
            tokens=_SETTLEMENT_TOKENS,
            missing_data=[
                (
                    "At least five source-linked matters or orders with "
                    "settlement, mediation, or consent markers."
                ),
                "Matter-type-normalized outcome labels from official/licensed sources.",
            ],
        ),
    ]


def _outcome_stats(bench_documents: Sequence[_BenchDocument]) -> _OutcomeStats:
    docs: list[AuthorityDocument] = []
    positive = 0
    adverse = 0
    neutral = 0
    for item in bench_documents:
        label = _normalise(item.document.outcome_label)
        if not label:
            continue
        docs.append(item.document)
        if _contains_any(label, _POSITIVE_OUTCOME_TOKENS):
            positive += 1
        elif _contains_any(label, _ADVERSE_OUTCOME_TOKENS):
            adverse += 1
        else:
            neutral += 1
    return _OutcomeStats(
        sample_size=len(docs),
        positive_count=positive,
        adverse_count=adverse,
        neutral_count=neutral,
        docs=tuple(docs),
    )


def _build_outcome_signal(stats: _OutcomeStats) -> PredictiveSignal:
    if stats.sample_size < MIN_SAMPLE_SIZE:
        return _insufficient_signal(
            signal_type="bench_outcome_tendency",
            label="Bench/forum outcome tendency",
            sample_size=stats.sample_size,
            missing_data=[
                "At least five indexed bench decisions with structured outcome labels.",
                "Source judgment/order IDs from official/licensed sources.",
            ],
        )

    successes = stats.positive_count
    low, high = _wilson_band(successes, stats.sample_size)
    evidence = _evidence_from_authority_docs(stats.docs[:MAX_EVIDENCE_PER_SIGNAL])
    evidence_ids = [item.id for item in evidence]
    if stats.positive_count > stats.adverse_count:
        estimate_label = "higher historical favorable-outcome label band"
        direction = "supports"
        explanation = (
            "Indexed bench decisions in this source sample contain more favorable "
            "than adverse structured outcome labels."
        )
    elif stats.adverse_count > stats.positive_count:
        estimate_label = "higher historical adverse-outcome label band"
        direction = "weakens"
        explanation = (
            "Indexed bench decisions in this source sample contain more adverse "
            "than favorable structured outcome labels."
        )
    else:
        estimate_label = "mixed historical outcome-label band"
        direction = "neutral"
        explanation = (
            "Indexed bench decisions in this source sample are mixed across "
            "favorable, adverse, and neutral structured outcome labels."
        )

    return PredictiveSignal(
        signal_type="bench_outcome_tendency",
        label="Bench/forum outcome tendency",
        status="supported",
        estimate_label=estimate_label,
        sample_size=stats.sample_size,
        confidence=_confidence(
            sample_size=stats.sample_size,
            low=low,
            high=high,
            limitations=[
                "Outcome labels are historical descriptors, not predictions of this matter.",
                "The band is calculated only from indexed, source-linked decisions.",
            ],
        ),
        evidence=evidence,
        features=[
            PredictionFeatureContribution(
                feature_key="structured_outcome_label_distribution",
                label="Structured outcome label distribution",
                direction=direction,
                weight=1.0,
                explanation=explanation,
                evidence_ids=evidence_ids,
            )
        ],
        limitation_note=LIMITATION_NOTE,
        disclaimer=DISCLAIMER,
    )


def _build_keyword_document_signal(
    *,
    signal_type: str,
    label: str,
    docs: Sequence[AuthorityDocument],
    tokens: Sequence[str],
    missing_data: list[str],
) -> PredictiveSignal:
    sample = [doc for doc in docs if _document_has_any(doc, tokens)]
    if len(sample) < MIN_SAMPLE_SIZE:
        return _insufficient_signal(
            signal_type=signal_type,
            label=label,
            sample_size=len(sample),
            missing_data=missing_data,
        )
    low, high = _wilson_band(len(sample), len(docs) or len(sample))
    evidence = _evidence_from_authority_docs(sample[:MAX_EVIDENCE_PER_SIGNAL])
    return PredictiveSignal(
        signal_type=signal_type,
        label=label,
        status="supported",
        estimate_label="historical source-marker frequency band",
        sample_size=len(sample),
        confidence=_confidence(
            sample_size=len(sample),
            low=low,
            high=high,
            limitations=[
                "Keyword markers are conservative deterministic evidence features.",
                "This LI-S7A slice does not classify full outcomes or infer unstated intent.",
            ],
        ),
        evidence=evidence,
        features=[
            PredictionFeatureContribution(
                feature_key="source_marker_frequency",
                label="Source marker frequency",
                direction="supports",
                weight=1.0,
                explanation=(
                    "The cited source sample contains repeated structured text markers "
                    f"for {label.lower()}."
                ),
                evidence_ids=[item.id for item in evidence],
            )
        ],
        limitation_note=LIMITATION_NOTE,
        disclaimer=DISCLAIMER,
    )


def _build_adjournment_signal(
    cause_entries: Sequence[MatterCauseListEntry],
) -> PredictiveSignal:
    sample = [
        entry
        for entry in cause_entries
        if _contains_any(_normalise(entry.stage, entry.notes), _ADJOURNMENT_TOKENS)
    ]
    if len(cause_entries) < MIN_SAMPLE_SIZE or len(sample) < MIN_SAMPLE_SIZE:
        return _insufficient_signal(
            signal_type="adjournment_likelihood",
            label="Adjournment likelihood",
            sample_size=len(sample),
            missing_data=[
                "At least five source-linked cause-list entries with adjournment markers.",
                "Listing stage/notes from official/licensed proceeding-sheet sources.",
            ],
        )
    low, high = _wilson_band(len(sample), len(cause_entries))
    evidence = _evidence_from_cause_entries(sample[:MAX_EVIDENCE_PER_SIGNAL])
    return PredictiveSignal(
        signal_type="adjournment_likelihood",
        label="Adjournment likelihood",
        status="supported",
        estimate_label="historical adjournment-marker frequency band",
        sample_size=len(sample),
        confidence=_confidence(sample_size=len(sample), low=low, high=high),
        evidence=evidence,
        features=[
            PredictionFeatureContribution(
                feature_key="cause_list_adjournment_markers",
                label="Cause-list adjournment markers",
                direction="supports",
                weight=1.0,
                explanation="Source-linked cause-list entries contain adjournment markers.",
                evidence_ids=[item.id for item in evidence],
            )
        ],
        limitation_note=LIMITATION_NOTE,
        disclaimer=DISCLAIMER,
    )


def _build_stay_interim_frequency_signal(
    court_orders: Sequence[MatterCourtOrder],
) -> PredictiveSignal:
    sample = [order for order in court_orders if _is_stay_or_interim_order(order)]
    if len(court_orders) < MIN_SAMPLE_SIZE or len(sample) < MIN_SAMPLE_SIZE:
        return _insufficient_signal(
            signal_type="stay_interim_order_frequency",
            label="Stay/interim order frequency",
            sample_size=len(sample),
            missing_data=[
                "At least five source-linked court orders with stay/interim markers.",
                "Order-kind and stay-status metadata from official/licensed sources.",
            ],
        )
    low, high = _wilson_band(len(sample), len(court_orders))
    evidence = _evidence_from_court_orders(sample[:MAX_EVIDENCE_PER_SIGNAL])
    return PredictiveSignal(
        signal_type="stay_interim_order_frequency",
        label="Stay/interim order frequency",
        status="supported",
        estimate_label="historical stay/interim order frequency band",
        sample_size=len(sample),
        confidence=_confidence(sample_size=len(sample), low=low, high=high),
        evidence=evidence,
        features=[
            PredictionFeatureContribution(
                feature_key="order_kind_and_stay_status",
                label="Order-kind and stay-status markers",
                direction="supports",
                weight=1.0,
                explanation="Cited court orders include interim-order or stay-status markers.",
                evidence_ids=[item.id for item in evidence],
            )
        ],
        limitation_note=LIMITATION_NOTE,
        disclaimer=DISCLAIMER,
    )


def _build_disposal_delay_signal(
    cause_entries: Sequence[MatterCauseListEntry],
) -> PredictiveSignal:
    delayed = [
        entry
        for entry in cause_entries
        if _contains_any(_normalise(entry.stage, entry.notes), _ADJOURNMENT_TOKENS)
    ]
    if len(cause_entries) < MIN_SAMPLE_SIZE or len(delayed) < MIN_SAMPLE_SIZE:
        return _insufficient_signal(
            signal_type="disposal_delay_risk",
            label="Disposal/delay risk",
            sample_size=len(delayed),
            missing_data=[
                "At least five proceeding-sheet entries with delay or adjournment markers.",
                "Forum/session-level listing history from official/licensed sources.",
            ],
        )
    low, high = _wilson_band(len(delayed), len(cause_entries))
    evidence = _evidence_from_cause_entries(delayed[:MAX_EVIDENCE_PER_SIGNAL])
    return PredictiveSignal(
        signal_type="disposal_delay_risk",
        label="Disposal/delay risk",
        status="supported",
        estimate_label="historical delay-marker frequency band",
        sample_size=len(delayed),
        confidence=_confidence(
            sample_size=len(delayed),
            low=low,
            high=high,
            limitations=[
                "Delay markers do not decide merits and may reflect routine listing constraints.",
            ],
        ),
        evidence=evidence,
        features=[
            PredictionFeatureContribution(
                feature_key="proceeding_sheet_delay_markers",
                label="Proceeding-sheet delay markers",
                direction="weakens",
                weight=1.0,
                explanation="Source-linked proceeding-sheet entries contain delay markers.",
                evidence_ids=[item.id for item in evidence],
            )
        ],
        limitation_note=LIMITATION_NOTE,
        disclaimer=DISCLAIMER,
    )


def _build_matter_risk_summary(
    matter_id: str,
    signals: Sequence[PredictiveSignal],
) -> MatterRiskSummary:
    outcome_signal = next(
        (signal for signal in signals if signal.signal_type == "adverse_order_risk"),
        None,
    )
    if outcome_signal is None or outcome_signal.status != "supported":
        outcome_signal = next(
            (signal for signal in signals if signal.signal_type == "bench_outcome_tendency"),
            outcome_signal,
        )
    if outcome_signal is None or outcome_signal.status != "supported":
        return MatterRiskSummary(
            matter_id=matter_id,
            status="insufficient_evidence",
            risk_band=None,
            confidence=_insufficient_confidence(
                outcome_signal.sample_size if outcome_signal else 0
            ),
            missing_data=[
                "A supported bench/forum outcome tendency signal is required.",
                "Later LI-S7B backfills must add matter-type and issue-specific outcome labels.",
            ],
            limitation_note=LIMITATION_NOTE,
            disclaimer=DISCLAIMER,
        )

    feature_direction = (
        outcome_signal.features[0].direction if outcome_signal.features else "neutral"
    )
    if feature_direction == "weakens":
        risk_band = "higher adverse-source-context band"
    elif feature_direction == "supports":
        risk_band = "lower adverse-source-context band"
    else:
        risk_band = "mixed source-context band"
    return MatterRiskSummary(
        matter_id=matter_id,
        status="supported",
        risk_band=risk_band,
        confidence=outcome_signal.confidence,
        signals=[outcome_signal],
        features=list(outcome_signal.features),
        evidence=list(outcome_signal.evidence),
        limitation_note=LIMITATION_NOTE,
        disclaimer=DISCLAIMER,
    )


def _build_hearing_scorecard(matter_id: str) -> HearingPrepScorecard:
    metrics = [
        PredictionFeatureContribution(
            feature_key="response_consistency",
            label="Response consistency",
            direction="unknown",
            explanation="Requires mock-hearing transcript turns to compare repeated answers.",
        ),
        PredictionFeatureContribution(
            feature_key="source_support_rate",
            label="Source support rate",
            direction="unknown",
            explanation="Requires answers linked to cited record or authority references.",
        ),
        PredictionFeatureContribution(
            feature_key="unsupported_new_fact_rate",
            label="Unsupported new fact rate",
            direction="unknown",
            explanation="Requires transcript review against matter record facts.",
        ),
        PredictionFeatureContribution(
            feature_key="response_timing_discipline",
            label="Response timing discipline",
            direction="unknown",
            explanation="Requires observable session timing metadata, not biometric inference.",
        ),
    ]
    return HearingPrepScorecard(
        matter_id=matter_id,
        status="insufficient_evidence",
        overall_band=None,
        confidence=_insufficient_confidence(0),
        observable_metrics=metrics,
        missing_data=[
            "No source-linked mock-hearing transcript turns are available in LI-S7A.",
            "No observable session timing metadata has been captured.",
        ],
        prohibited_inferences=[
            "medical_or_mental_health_diagnosis",
            "personality_assessment",
            "biometric_or_voice_stress_inference",
        ],
        limitation_note=(
            "Hearing-prep scoring may evaluate observable answer consistency, source "
            "support, unsupported-new-fact rate, and timing discipline only. It must "
            "not diagnose or infer mental health, personality, or biometric state."
        ),
        disclaimer=DISCLAIMER,
    )


def _persist_run(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    evidence_quality: str,
    signals: Sequence[PredictiveSignal],
    matter_risk: MatterRiskSummary,
    hearing_scorecard: HearingPrepScorecard,
) -> PredictiveSignalRun:
    run = PredictiveSignalRun(
        company_id=context.company.id,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        status="completed",
        mode="predictive",
        sample_size=max((signal.sample_size for signal in signals), default=0),
        evidence_quality=evidence_quality,
        disclaimer=DISCLAIMER,
        limitation_note=LIMITATION_NOTE,
    )
    session.add(run)
    session.flush()

    for signal in [*signals, *_signals_from_summaries(matter_risk, hearing_scorecard)]:
        item = PredictiveSignalItem(
            run_id=run.id,
            company_id=context.company.id,
            matter_id=matter.id,
            signal_type=signal.signal_type,
            status=signal.status,
            label=signal.label,
            estimate_label=signal.estimate_label,
            sample_size=signal.sample_size,
            confidence_label=signal.confidence.label,
            confidence_band_low=signal.confidence.confidence_band_low,
            confidence_band_high=signal.confidence.confidence_band_high,
            limitation_note=signal.limitation_note,
            features_json=json.dumps(
                [feature.model_dump(mode="json") for feature in signal.features],
                default=str,
            ),
            missing_data_json=json.dumps(signal.missing_data, default=str),
        )
        session.add(item)
        session.flush()
        for evidence in signal.evidence:
            session.add(
                PredictiveSignalEvidence(
                    run_id=run.id,
                    item_id=item.id,
                    company_id=context.company.id,
                    matter_id=matter.id,
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    title=evidence.title,
                    source_reference=evidence.source_reference,
                    excerpt=evidence.excerpt,
                    source_date=evidence.source_date,
                    weight=evidence.weight,
                )
            )
    session.flush()
    return run


def _signals_from_summaries(
    matter_risk: MatterRiskSummary,
    hearing_scorecard: HearingPrepScorecard,
) -> tuple[PredictiveSignal, ...]:
    risk_signal = PredictiveSignal(
        signal_type="matter_risk_score",
        label="Matter risk score",
        status=matter_risk.status,
        estimate_label=matter_risk.risk_band,
        sample_size=matter_risk.confidence.sample_size,
        confidence=matter_risk.confidence,
        evidence=matter_risk.evidence,
        features=matter_risk.features,
        missing_data=matter_risk.missing_data,
        limitation_note=matter_risk.limitation_note,
        disclaimer=matter_risk.disclaimer,
    )
    hearing_signal = PredictiveSignal(
        signal_type="mock_hearing_performance_scoring",
        label="Mock-hearing performance scoring",
        status=hearing_scorecard.status,
        estimate_label=hearing_scorecard.overall_band,
        sample_size=hearing_scorecard.confidence.sample_size,
        confidence=hearing_scorecard.confidence,
        evidence=hearing_scorecard.evidence,
        features=hearing_scorecard.observable_metrics,
        missing_data=hearing_scorecard.missing_data,
        limitation_note=hearing_scorecard.limitation_note,
        disclaimer=hearing_scorecard.disclaimer,
    )
    return (risk_signal, hearing_signal)


def _insufficient_signal(
    *,
    signal_type: str,
    label: str,
    sample_size: int,
    missing_data: list[str],
) -> PredictiveSignal:
    return PredictiveSignal(
        signal_type=signal_type,
        label=label,
        status="insufficient_evidence",
        sample_size=sample_size,
        confidence=_insufficient_confidence(sample_size),
        missing_data=missing_data,
        limitation_note=LIMITATION_NOTE,
        disclaimer=DISCLAIMER,
    )


def _confidence(
    *,
    sample_size: int,
    low: float,
    high: float,
    limitations: list[str] | None = None,
) -> PredictionConfidence:
    return PredictionConfidence(
        label=_confidence_label(sample_size),
        sample_size=sample_size,
        confidence_band_low=round(low, 4),
        confidence_band_high=round(high, 4),
        method="deterministic_source_frequency_wilson_95",
        limitations=limitations
        or [
            "Source-frequency confidence bands describe historical indexed samples only.",
            "No LLM-only or intuition-only estimate is used.",
        ],
    )


def _insufficient_confidence(sample_size: int) -> PredictionConfidence:
    return PredictionConfidence(
        label="insufficient",
        sample_size=sample_size,
        confidence_band_low=None,
        confidence_band_high=None,
        method="insufficient_source_sample",
        limitations=[
            f"Minimum sample size is {MIN_SAMPLE_SIZE}.",
            "Prediction surfaces degrade to insufficient_evidence below the threshold.",
        ],
    )


def _confidence_label(sample_size: int) -> str:
    if sample_size >= 20:
        return "high"
    if sample_size >= 10:
        return "medium"
    if sample_size >= MIN_SAMPLE_SIZE:
        return "low"
    return "insufficient"


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


def _evidence_quality(sample_size: int) -> str:
    if sample_size >= 20:
        return "strong"
    if sample_size >= 10:
        return "moderate"
    if sample_size >= MIN_SAMPLE_SIZE:
        return "thin"
    return "insufficient"


def _evidence_from_authority_docs(
    docs: Sequence[AuthorityDocument],
) -> list[PredictiveEvidence]:
    return [
        PredictiveEvidence(
            id=f"authority_document:{doc.id}",
            source_type="authority_document",
            source_id=doc.id,
            title=doc.title,
            source_reference=doc.source_reference or doc.neutral_citation or doc.case_reference,
            excerpt=_trim(doc.document_text),
            source_date=doc.decision_date.isoformat() if doc.decision_date else None,
            weight=1.0,
        )
        for doc in docs
    ]


def _evidence_from_court_orders(
    orders: Sequence[MatterCourtOrder],
) -> list[PredictiveEvidence]:
    return [
        PredictiveEvidence(
            id=f"matter_court_order:{order.id}",
            source_type="matter_court_order",
            source_id=order.id,
            title=order.title,
            source_reference=order.source_reference,
            excerpt=_trim(order.order_text),
            source_date=order.order_date.isoformat(),
            weight=1.0,
        )
        for order in orders
    ]


def _evidence_from_cause_entries(
    entries: Sequence[MatterCauseListEntry],
) -> list[PredictiveEvidence]:
    return [
        PredictiveEvidence(
            id=f"matter_cause_list_entry:{entry.id}",
            source_type="matter_cause_list_entry",
            source_id=entry.id,
            title=entry.stage or entry.bench_name or entry.forum_name,
            source_reference=entry.source_reference,
            excerpt=_trim(entry.notes),
            source_date=entry.listing_date.isoformat(),
            weight=1.0,
        )
        for entry in entries
    ]


def _document_has_any(doc: AuthorityDocument, tokens: Sequence[str]) -> bool:
    if not doc.document_text or len(doc.document_text.strip()) < 40:
        return False
    haystack = _normalise(
        doc.outcome_label,
        doc.title,
        doc.document_text[:4000] if doc.document_text else None,
    )
    return _contains_any(haystack, tokens)


def _is_stay_or_interim_order(order: MatterCourtOrder) -> bool:
    haystack = _normalise(
        order.order_kind,
        order.stay_status,
        order.title,
        order.order_text,
    )
    return bool(order.is_interim_order) or _contains_any(
        haystack,
        (*_STAY_TOKENS, *_INTERIM_TOKENS),
    )


def _normalise(*parts: str | None) -> str:
    return " ".join(part.strip().lower() for part in parts if part and part.strip())


def _contains_any(haystack: str, tokens: Iterable[str]) -> bool:
    return any(token in haystack for token in tokens)


def _trim(value: str | None, limit: int = 500) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "."


__all__ = ["build_predictive_intelligence"]
