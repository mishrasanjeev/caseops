from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ProviderCostCategoryLiteral = Literal[
    "case_refresh",
    "bulk_case_refresh",
    "llm",
    "llm_input",
    "llm_output",
    "embedding",
    "document_processing",
    "ocr_page",
    "storage",
    "bandwidth_export",
    "payment_mdr",
    "payment_fixed_fee",
    "payment_refund_fee",
    "payment_chargeback_fee",
    "email",
    "sms",
    "whatsapp",
    "manual_support",
    "legal_source_search",
    "legal_source_document",
    "legal_source_original_document",
    "legal_source_fragment",
    "legal_source_metadata",
]
ProviderCostProfileStatus = Literal["active", "inactive"]
ProviderCostBasisLiteral = Literal["estimated", "actual"]
ProviderCostConfidenceLiteral = Literal["low", "medium", "high"]
FounderApprovalStatusLiteral = Literal["pending", "approved", "rejected"]


class ProviderCostProfileRecord(BaseModel):
    id: str
    category: ProviderCostCategoryLiteral
    provider: str
    currency: Literal["INR"]
    unit_amount_minor: int | None = None
    unit_amount_bps: int | None = None
    unit_label: str | None = None
    effective_from: datetime
    effective_until: datetime | None = None
    status: ProviderCostProfileStatus
    source: str | None = None
    tax_fee_notes: str | None = None
    cost_basis: ProviderCostBasisLiteral
    confidence_level: ProviderCostConfidenceLiteral
    evidence_ref: str | None = None
    founder_approval_status: FounderApprovalStatusLiteral
    approved_at: datetime | None = None
    approved_by_platform_admin_id: str | None = None
    notes: str | None = None
    created_by_platform_admin_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ProviderCostProfileListResponse(BaseModel):
    cost_profiles: list[ProviderCostProfileRecord]


class ProviderCostProfileCreateRequest(BaseModel):
    category: ProviderCostCategoryLiteral
    provider: str = Field(default="default", min_length=1, max_length=80)
    currency: Literal["INR"] = "INR"
    unit_amount_minor: int | None = Field(default=None, ge=0)
    unit_amount_bps: int | None = Field(default=None, ge=0)
    unit_label: str | None = Field(default=None, max_length=80)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    source: str | None = Field(default=None, max_length=160)
    tax_fee_notes: str | None = Field(default=None, max_length=4000)
    cost_basis: ProviderCostBasisLiteral = "estimated"
    confidence_level: ProviderCostConfidenceLiteral = "low"
    evidence_ref: str | None = Field(default=None, max_length=500)
    founder_approval_status: FounderApprovalStatusLiteral = "pending"
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() or "default"
        return value

    @model_validator(mode="after")
    def validate_amounts(self) -> ProviderCostProfileCreateRequest:
        if self.unit_amount_minor is None and self.unit_amount_bps is None:
            raise ValueError("unit_amount_minor or unit_amount_bps is required.")
        if (
            self.effective_until
            and self.effective_from
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("effective_until must be after effective_from.")
        return self


class ProviderCostProfileUpdateRequest(BaseModel):
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    currency: Literal["INR"] | None = None
    unit_amount_minor: int | None = Field(default=None, ge=0)
    unit_amount_bps: int | None = Field(default=None, ge=0)
    unit_label: str | None = Field(default=None, max_length=80)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    status: ProviderCostProfileStatus | None = None
    source: str | None = Field(default=None, max_length=160)
    tax_fee_notes: str | None = Field(default=None, max_length=4000)
    cost_basis: ProviderCostBasisLiteral | None = None
    confidence_level: ProviderCostConfidenceLiteral | None = None
    evidence_ref: str | None = Field(default=None, max_length=500)
    founder_approval_status: FounderApprovalStatusLiteral | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() or "default"
        return value

    @model_validator(mode="after")
    def validate_effective_window(self) -> ProviderCostProfileUpdateRequest:
        if (
            self.effective_until
            and self.effective_from
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("effective_until must be after effective_from.")
        return self


class MarginSimulationRunRequest(BaseModel):
    scenario_name: str | None = Field(default=None, max_length=160)
    scenario_code: str | None = Field(default=None, max_length=80)
    plan_code: str | None = Field(default=None, max_length=80)
    billing_interval: Literal["month", "year", "one_time", "custom"] = "month"
    revenue_minor: int | None = Field(default=None, ge=0)
    payment_amount_minor: int | None = Field(default=None, ge=0)
    payment_count: int = Field(default=1, ge=0, le=100_000)
    tracked_case_refreshes: int = Field(default=0, ge=0, le=10_000_000)
    bulk_case_refreshes: int = Field(default=0, ge=0, le=10_000_000)
    ai_credits: int = Field(default=0, ge=0, le=10_000_000)
    llm_input_units: int = Field(default=0, ge=0, le=100_000_000)
    llm_output_units: int = Field(default=0, ge=0, le=100_000_000)
    embedding_units: int = Field(default=0, ge=0, le=100_000_000)
    document_pages: int = Field(default=0, ge=0, le=100_000_000)
    ocr_pages: int = Field(default=0, ge=0, le=100_000_000)
    storage_gb_months: int = Field(default=0, ge=0, le=10_000_000)
    bandwidth_export_gb: int = Field(default=0, ge=0, le=10_000_000)
    email_messages: int = Field(default=0, ge=0, le=10_000_000)
    sms_messages: int = Field(default=0, ge=0, le=10_000_000)
    whatsapp_messages: int = Field(default=0, ge=0, le=10_000_000)
    manual_support_minutes: int = Field(default=0, ge=0, le=10_000_000)
    minimum_gross_margin_bps: int | None = Field(default=None, ge=0, le=10_000)
    currency: Literal["INR"] = "INR"

    @model_validator(mode="after")
    def require_revenue_source(self) -> MarginSimulationRunRequest:
        if self.revenue_minor is None and not self.plan_code:
            raise ValueError("Either revenue_minor or plan_code is required.")
        return self


class MarginSimulationRecord(BaseModel):
    id: str
    scenario_name: str | None
    plan_code: str | None = None
    scenario_code: str | None = None
    currency: Literal["INR"]
    input: dict[str, object]
    result: dict[str, object]
    warnings: list[dict[str, object]]
    minimum_gross_margin_bps: int
    uses_unapproved_estimated_costs: bool
    readiness_blocked: bool
    founder_approval_status: FounderApprovalStatusLiteral
    approved_at: datetime | None = None
    approved_by_platform_admin_id: str | None = None
    run_by_platform_admin_id: str | None
    created_at: datetime


class MarginSimulationListResponse(BaseModel):
    simulations: list[MarginSimulationRecord]


class MarginReadinessScenarioStatus(BaseModel):
    scenario_code: str
    label: str
    latest_simulation_id: str | None = None
    latest_gross_margin_bps: int | None = None
    readiness_blocked: bool
    uses_unapproved_estimated_costs: bool
    missing: bool = False


class MarginReadinessResponse(BaseModel):
    minimum_gross_margin_bps: int
    required_scenarios: list[MarginReadinessScenarioStatus]
    blocked: bool
