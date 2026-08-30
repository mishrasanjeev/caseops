from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EvidenceStatusLiteral = Literal["pending", "pass", "fail", "blocked", "not_applicable"]
ReadinessClassificationLiteral = Literal[
    "live",
    "review-first",
    "provider-gated",
    "founder-only",
    "disabled until UAT",
    "planned",
]
SecretRotationStatusLiteral = Literal[
    "pending",
    "blocked",
    "rotated",
    "revoked",
    "validated",
    "not_applicable",
]

PineLabsUATScenarioLiteral = Literal[
    "plan_payment_success",
    "top_up_success",
    "failed_payment",
    "pending_payment",
    "cancelled_expired_payment",
    "duplicate_webhook",
    "tampered_webhook",
    "stale_webhook",
    "refund_processed",
    "refund_failed",
    "subscription_charged",
    "subscription_cancelled",
    "settlement_report_import",
]

ProductionBillingSignoffCheckLiteral = Literal[
    "platform_admin",
    "platform_admin_profit",
    "platform_admin_costs",
    "platform_admin_integrations",
    "platform_admin_provider_events",
    "tenant_billing_current_plan",
    "invoice_download",
    "statement_download",
    "credit_ledger_export",
    "payment_export",
    "spend_export",
    "disabled_pine_checkout_behavior",
    "tenant_no_leak_checks",
]

MachineReadinessEvidenceKind = Literal[
    "billing_check",
    "operational_gate",
    "pine_labs_uat",
]
MachineReadinessConclusion = Literal["pass", "fail", "blocked"]


class MachineReadinessEvidenceItem(BaseModel):
    kind: MachineReadinessEvidenceKind
    subject: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9_:-]+$")
    conclusion: MachineReadinessConclusion
    evidence_ref: str = Field(min_length=3, max_length=500)
    target_run_id: str | None = Field(default=None, min_length=3, max_length=80)

    @model_validator(mode="after")
    def _target_run_only_for_pine(self) -> MachineReadinessEvidenceItem:
        if self.kind == "pine_labs_uat" and not self.target_run_id:
            raise ValueError("pine_labs_uat evidence requires target_run_id")
        if self.kind != "pine_labs_uat" and self.target_run_id is not None:
            raise ValueError("target_run_id is valid only for pine_labs_uat evidence")
        return self


class MachineReadinessEvidenceWriteRequest(BaseModel):
    schema_name: Literal["caseops.machine-readiness-write/v1"] = Field(alias="schema")
    producer: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9_./-]+$")
    release_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    run_id: str = Field(
        min_length=3,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]+$",
    )
    items: list[MachineReadinessEvidenceItem] = Field(min_length=1, max_length=64)

    @field_validator("items")
    @classmethod
    def _unique_items(
        cls,
        items: list[MachineReadinessEvidenceItem],
    ) -> list[MachineReadinessEvidenceItem]:
        keys = [(item.kind, item.subject, item.target_run_id) for item in items]
        if len(keys) != len(set(keys)):
            raise ValueError("machine readiness evidence items must be unique")
        return items


class MachineReadinessEvidenceWriteResponse(BaseModel):
    release_sha: str
    producer: str
    run_id: str
    recorded_count: int
    evidence_digest: str


class PineLabsUATScenarioStatus(BaseModel):
    scenario_code: PineLabsUATScenarioLiteral
    label: str
    required: bool
    result_status: EvidenceStatusLiteral
    provider_order_id: str | None = None
    webhook_id: str | None = None
    observed_at: datetime | None = None
    operator_notes: str | None = None
    attachment_refs: list[str] = Field(default_factory=list)


class PineLabsUATReadinessResponse(BaseModel):
    run_id: str
    run_status: str
    provider_mode: str
    environment: str
    scenarios: list[PineLabsUATScenarioStatus]
    complete: bool
    missing_required_scenarios: list[PineLabsUATScenarioLiteral]
    activation_prerequisites_met: bool
    production_activation_blocked: bool
    activation_blockers: list[str] = Field(default_factory=list)
    latest_decision: dict[str, object] | None = None


class PineLabsUATRunCreateRequest(BaseModel):
    environment: Literal["mock", "uat"] = "uat"
    provider_mode: str = Field(default="mock", max_length=40)
    notes: str | None = Field(default=None, max_length=4000)


class PineLabsActivationDecisionRequest(BaseModel):
    run_id: str | None = None
    founder_go_no_go: Literal["go", "no_go"]
    notes: str = Field(min_length=3, max_length=4000)


class ProductionBillingSignoffCheckStatus(BaseModel):
    check_code: ProductionBillingSignoffCheckLiteral
    label: str
    result_status: EvidenceStatusLiteral
    evidence_ref: str | None = None
    operator_notes: str | None = None
    recorded_at: datetime | None = None


class ProductionBillingSignoffResponse(BaseModel):
    signoff_id: str
    status: str
    complete: bool
    missing_required_checks: list[ProductionBillingSignoffCheckLiteral]
    checks: list[ProductionBillingSignoffCheckStatus]
    signed_off_at: datetime | None = None
    notes: str | None = None


class PasswordResetReadinessResponse(BaseModel):
    reset_link_domain: str
    reset_path: str
    public_app_url: str
    email_provider: Literal["sendgrid"]
    provider_configured: bool
    sender_email_configured: bool
    sender_name: str
    template_kind: Literal["employee_password_reset_plain_text"]
    subject_template: str
    token_ttl_minutes: int
    debug_tokens_allowed: bool
    non_prod_debug_tokens_only: bool
    secrets_exposed: Literal[False] = False


class SecretRotationEvidenceRecord(BaseModel):
    id: str
    provider: str
    affected_app: str
    credential_label: str
    status: SecretRotationStatusLiteral
    old_credential_revoked: bool
    validation_performed: bool
    rotation_completed_at: datetime | None = None
    evidence_ref: str | None = None
    residual_risk: str | None = None
    operator_notes: str | None = None
    last_evidence_at: datetime
    recorded_by_platform_admin_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SecretRotationEvidenceRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=120)
    affected_app: str = Field(min_length=2, max_length=160)
    credential_label: str = Field(min_length=2, max_length=160)
    status: SecretRotationStatusLiteral = "pending"
    old_credential_revoked: bool = False
    validation_performed: bool = False
    rotation_completed_at: datetime | None = None
    evidence_ref: str | None = Field(default=None, max_length=500)
    residual_risk: str | None = Field(default=None, max_length=4000)
    operator_notes: str | None = Field(default=None, max_length=4000)


class SecretRotationEvidenceListResponse(BaseModel):
    complete: bool
    not_ready_reasons: list[str] = Field(default_factory=list)
    records: list[SecretRotationEvidenceRecord]


class PlatformOperationalReadinessRecord(BaseModel):
    id: str | None = None
    category: str
    gate_code: str
    label: str
    status: EvidenceStatusLiteral
    readiness_classification: ReadinessClassificationLiteral
    blocker_reason: str | None = None
    evidence_ref: str | None = None
    evidence: dict[str, object] | None = None
    last_evidence_at: datetime | None = None
    owner_label: str | None = None


class PlatformProductionReadinessGate(BaseModel):
    category: str
    gate_code: str
    label: str
    status: EvidenceStatusLiteral
    readiness_classification: ReadinessClassificationLiteral
    ready: bool
    not_ready_reason: str | None = None
    evidence_ref: str | None = None
    last_evidence_at: datetime | None = None


class PlatformProductionReadinessResponse(BaseModel):
    ready: bool
    not_ready_reasons: list[str]
    gates: list[PlatformProductionReadinessGate]
    secret_rotation: SecretRotationEvidenceListResponse
    operational_evidence: list[PlatformOperationalReadinessRecord]


class EnterpriseIdentityReadinessResponse(BaseModel):
    provider: Literal["enterprise_identity"] = "enterprise_identity"
    readiness_classification: ReadinessClassificationLiteral = "planned"
    oidc_status: str
    saml_status: str
    scim_status: str
    sso_enforcement_status: str
    enabled: bool
    not_enabled_reason: str
    last_test_status: str
    last_tested_at: datetime | None = None
    required_evidence: list[str] = Field(default_factory=list)


class AgentTrustReadinessResponse(BaseModel):
    provider: Literal["agent_trust_plane"] = "agent_trust_plane"
    readiness_classification: ReadinessClassificationLiteral = "planned"
    autonomous_execution_enabled: Literal[False] = False
    grant_count: int
    active_grant_count: int
    execution_count: int
    blocked_execution_count: int
    not_enabled_reason: str


class AIGovernanceReadinessResponse(BaseModel):
    provider: Literal["ai_governance"] = "ai_governance"
    readiness_classification: ReadinessClassificationLiteral = "review-first"
    approved_policy_count: int
    pending_policy_count: int
    blocked_policy_count: int
    legal_disclaimer_required: bool
    regression_gates_required: bool


class TenantEnterpriseReadinessResponse(BaseModel):
    enterprise_identity: EnterpriseIdentityReadinessResponse
    agent_trust_plane: AgentTrustReadinessResponse
    ai_governance: AIGovernanceReadinessResponse


class SettlementImportRowRequest(BaseModel):
    provider_order_id: str | None = Field(default=None, max_length=255)
    provider_payment_id: str | None = Field(default=None, max_length=255)
    amount_minor: int = Field(default=0)
    provider_fee_minor: int = Field(default=0)
    tax_minor: int = Field(default=0)
    net_settlement_minor: int = Field(default=0)
    currency: Literal["INR"] = "INR"
    settled_on: date | None = None
    status: str | None = Field(default=None, max_length=40)
    raw: dict[str, object] = Field(default_factory=dict)


class SettlementImportRequest(BaseModel):
    provider: str = Field(default="pine_labs_plural", max_length=40)
    source_filename: str | None = Field(default=None, max_length=255)
    settlement_period_start: date | None = None
    settlement_period_end: date | None = None
    rows: list[SettlementImportRowRequest] = Field(default_factory=list, min_length=1)
    notes: str | None = Field(default=None, max_length=4000)


class SettlementImportResponse(BaseModel):
    id: str
    status: str
    row_count: int
    matched_count: int
    exception_count: int


class FinanceRecordRequest(BaseModel):
    provider: str = Field(default="pine_labs_plural", max_length=40)
    provider_reference_id: str | None = Field(default=None, max_length=255)
    provider_order_id: str | None = Field(default=None, max_length=255)
    payment_order_id: str | None = Field(default=None, max_length=36)
    company_id: str | None = Field(default=None, max_length=36)
    subscription_id: str | None = Field(default=None, max_length=36)
    status: str = Field(default="recorded", max_length=32)
    reason: str | None = Field(default=None, max_length=4000)
    amount_minor: int = Field(default=0, ge=0)
    provider_fee_minor: int = Field(default=0, ge=0)
    tax_minor: int = Field(default=0, ge=0)
    currency: Literal["INR"] = "INR"
    occurred_at: datetime | None = None
    payload: dict[str, object] | None = None


class CreditNoteCreateRequest(BaseModel):
    company_id: str = Field(max_length=36)
    subscription_id: str | None = Field(default=None, max_length=36)
    payment_order_id: str | None = Field(default=None, max_length=36)
    refund_record_id: str | None = Field(default=None, max_length=36)
    credit_note_number: str = Field(min_length=2, max_length=80)
    status: str = Field(default="issued", max_length=32)
    reason: str | None = Field(default=None, max_length=4000)
    amount_minor: int = Field(default=0, ge=0)
    tax_amount_minor: int = Field(default=0, ge=0)
    tds_adjustment_minor: int = Field(default=0, ge=0)
    issued_on: date | None = None
    evidence_ref: str | None = Field(default=None, max_length=500)


class TDSReconciliationCreateRequest(BaseModel):
    company_id: str | None = Field(default=None, max_length=36)
    subscription_id: str | None = Field(default=None, max_length=36)
    invoice_id: str | None = Field(default=None, max_length=36)
    credit_note_id: str | None = Field(default=None, max_length=36)
    payer_name: str | None = Field(default=None, max_length=255)
    payer_pan: str | None = Field(default=None, max_length=20)
    certificate_number: str | None = Field(default=None, max_length=120)
    financial_year: str | None = Field(default=None, max_length=20)
    gross_amount_minor: int = Field(default=0, ge=0)
    tds_deducted_minor: int = Field(default=0, ge=0)
    tds_deposited_minor: int = Field(default=0, ge=0)
    status: str = Field(default="open", max_length=24)
    evidence_ref: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)


class FinanceListResponse(BaseModel):
    rows: list[dict[str, object]]


class CaseTrackingSupportMatrixBase(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    court: str = Field(min_length=1, max_length=255)
    bench_jurisdiction: str | None = Field(default=None, max_length=255)
    lookup_method: str = Field(min_length=1, max_length=120)
    rate_limit: str | None = Field(default=None, max_length=160)
    freshness_sla: str | None = Field(default=None, max_length=160)
    legal_tos_status: str = Field(default="unknown", max_length=80)
    failure_code_mapping: dict[str, object] | None = None
    enabled: bool = False
    tenant_visible: bool = True
    status_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("provider", "court", "lookup_method", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CaseTrackingSupportMatrixCreateRequest(CaseTrackingSupportMatrixBase):
    refresh_cost_minor: int = Field(default=0, ge=0)
    bulk_refresh_cost_minor: int = Field(default=0, ge=0)
    evidence_ref: str | None = Field(default=None, max_length=500)


class CaseTrackingSupportMatrixUpdateRequest(BaseModel):
    court: str | None = Field(default=None, min_length=1, max_length=255)
    bench_jurisdiction: str | None = Field(default=None, max_length=255)
    lookup_method: str | None = Field(default=None, min_length=1, max_length=120)
    refresh_cost_minor: int | None = Field(default=None, ge=0)
    bulk_refresh_cost_minor: int | None = Field(default=None, ge=0)
    rate_limit: str | None = Field(default=None, max_length=160)
    freshness_sla: str | None = Field(default=None, max_length=160)
    legal_tos_status: str | None = Field(default=None, max_length=80)
    failure_code_mapping: dict[str, object] | None = None
    enabled: bool | None = None
    tenant_visible: bool | None = None
    status_notes: str | None = Field(default=None, max_length=4000)
    evidence_ref: str | None = Field(default=None, max_length=500)


class CaseTrackingSupportMatrixAdminRecord(CaseTrackingSupportMatrixBase):
    id: str
    refresh_cost_minor: int
    bulk_refresh_cost_minor: int
    currency: Literal["INR"]
    evidence_ref: str | None = None
    created_at: datetime
    updated_at: datetime


class CaseTrackingSupportMatrixTenantRecord(BaseModel):
    id: str
    provider: str
    court: str
    bench_jurisdiction: str | None = None
    lookup_method: str
    rate_limit: str | None = None
    freshness_sla: str | None = None
    legal_tos_status: str
    failure_code_mapping: dict[str, object] | None = None
    enabled: bool
    status_notes: str | None = None


class CaseTrackingSupportMatrixResponse(BaseModel):
    rows: list[CaseTrackingSupportMatrixAdminRecord]


class CaseTrackingTenantSupportMatrixResponse(BaseModel):
    rows: list[CaseTrackingSupportMatrixTenantRecord]
