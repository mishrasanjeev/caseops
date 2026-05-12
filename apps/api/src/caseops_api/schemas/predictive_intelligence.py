from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PredictionStatusLiteral = Literal["supported", "insufficient_evidence"]
BenchContextStatusLiteral = Literal[
    "supported",
    "limited_context",
    "insufficient_evidence",
]
PredictionConfidenceLabel = Literal["high", "medium", "low", "insufficient"]
PredictionFeatureDirection = Literal["supports", "weakens", "neutral", "unknown"]
PredictiveEvidenceSourceType = Literal[
    "authority_document",
    "matter_court_order",
    "matter_cause_list_entry",
    "matter_document",
    "aggregate_snapshot",
    "unavailable",
]


class PredictionConfidence(BaseModel):
    label: PredictionConfidenceLabel
    sample_size: int = Field(ge=0)
    confidence_band_low: float | None = Field(default=None, ge=0, le=1)
    confidence_band_high: float | None = Field(default=None, ge=0, le=1)
    method: str
    limitations: list[str] = Field(default_factory=list)


class PredictiveEvidence(BaseModel):
    id: str
    source_type: PredictiveEvidenceSourceType
    source_id: str
    title: str | None = None
    source_reference: str | None = None
    excerpt: str | None = None
    source_date: str | None = None
    weight: float = 1.0


class PredictionFeatureContribution(BaseModel):
    feature_key: str
    label: str
    direction: PredictionFeatureDirection
    weight: float = 0.0
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


class PredictiveSignal(BaseModel):
    signal_type: str
    label: str
    status: PredictionStatusLiteral
    estimate_label: str | None = None
    sample_size: int = Field(ge=0)
    confidence: PredictionConfidence
    evidence: list[PredictiveEvidence] = Field(default_factory=list)
    features: list[PredictionFeatureContribution] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    limitation_note: str
    human_review_required: bool = True
    decision_support_label: str = "decision support, not legal advice"
    disclaimer: str


class BenchPredictiveSummary(BaseModel):
    matter_id: str
    bench_judge_ids: list[str] = Field(default_factory=list)
    evidence_quality: str
    signals: list[PredictiveSignal] = Field(default_factory=list)
    disclaimer: str


class BenchContextScope(BaseModel):
    court_name: str | None = None
    forum_level: str | None = None
    bench_name: str | None = None
    judge_ids: list[str] = Field(default_factory=list)
    judge_names: list[str] = Field(default_factory=list)
    matter_type: str | None = None
    year_start: int | None = None
    year_end: int | None = None


class ObservedSignalDistribution(BaseModel):
    signal_type: str
    label: str
    sample_size: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    neutral_count: int = Field(ge=0)
    year_start: int | None = None
    year_end: int | None = None


class CalibratedSignalScope(BaseModel):
    scope_type: str | None = None
    scope_key: str | None = None
    court_name: str | None = None
    forum_level: str | None = None
    judge_id: str | None = None
    matter_type: str | None = None
    party_side: str | None = None
    year_start: int | None = None
    year_end: int | None = None


class CalibratedPredictiveSignal(BaseModel):
    signal_type: str
    label: str
    status: BenchContextStatusLiteral
    scope: CalibratedSignalScope
    sample_size: int = Field(ge=0)
    observed_rate: float | None = Field(default=None, ge=0, le=1)
    positive_count: int = Field(default=0, ge=0)
    negative_count: int = Field(default=0, ge=0)
    neutral_count: int = Field(default=0, ge=0)
    confidence: PredictionConfidence
    calibration_level: PredictionConfidenceLabel
    evidence_quality: str
    evidence: list[PredictiveEvidence] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    limitation_note: str
    aggregate_snapshot_id: str | None = None
    generated_at: datetime | None = None
    human_review_required: bool = True
    decision_support_label: str = "decision support, not legal advice"
    disclaimer: str


class BenchContextSummary(BaseModel):
    matter_id: str
    status: BenchContextStatusLiteral
    scope: BenchContextScope
    sample_size: int = Field(ge=0)
    evidence_quality: str
    confidence: PredictionConfidence
    observed_distribution: list[ObservedSignalDistribution] = Field(default_factory=list)
    evidence: list[PredictiveEvidence] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    limitation_note: str
    human_review_required: bool = True
    decision_support_label: str = "decision support, not legal advice"
    disclaimer: str


class MatterRiskSummary(BaseModel):
    matter_id: str
    status: PredictionStatusLiteral
    risk_band: str | None = None
    confidence: PredictionConfidence
    signals: list[PredictiveSignal] = Field(default_factory=list)
    features: list[PredictionFeatureContribution] = Field(default_factory=list)
    evidence: list[PredictiveEvidence] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    limitation_note: str
    human_review_required: bool = True
    decision_support_label: str = "decision support, not legal advice"
    disclaimer: str


class HearingPrepScorecard(BaseModel):
    matter_id: str
    status: PredictionStatusLiteral
    overall_band: str | None = None
    confidence: PredictionConfidence
    observable_metrics: list[PredictionFeatureContribution] = Field(default_factory=list)
    evidence: list[PredictiveEvidence] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    prohibited_inferences: list[str] = Field(default_factory=list)
    limitation_note: str
    human_review_required: bool = True
    decision_support_label: str = "decision support, not legal advice"
    disclaimer: str


class PredictiveIntelligenceResponse(BaseModel):
    matter_id: str
    mode: Literal["predictive"]
    tenant_policy_enabled: bool
    generated_at: datetime
    run_id: str
    bench_summary: BenchPredictiveSummary
    bench_context: BenchContextSummary
    calibrated_signals: list[CalibratedPredictiveSignal] = Field(default_factory=list)
    matter_risk_summary: MatterRiskSummary
    hearing_prep_scorecard: HearingPrepScorecard
    disclaimer: str
