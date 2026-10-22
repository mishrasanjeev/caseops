from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)


def _persisted_utc(value: datetime) -> datetime:
    # These billing fields are persisted as UTC; SQLite drops their timezone.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


PersistedUTCTimestamp = Annotated[datetime, AfterValidator(_persisted_utc)]


class ConsoleDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ConsoleEmptyRequest(ConsoleDTO):
    pass


class ConsoleLoginRequest(ConsoleDTO):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024, repr=False)


class ConsoleTokenCompleteRequest(ConsoleDTO):
    token: str = Field(min_length=32, max_length=256, repr=False)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class ConsoleInviteCompleteRequest(ConsoleTokenCompleteRequest):
    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]


class ConsoleResetStartRequest(ConsoleDTO):
    email: EmailStr


class ConsoleInviteRequest(ConsoleDTO):
    email: EmailStr
    reinvite_revoked: bool = Field(default=False, strict=True)
    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]


class ConsoleRevokeRequest(ConsoleDTO):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    expected_version: int | None = Field(default=None, ge=1, strict=True)


class ConsoleVersionRequest(ConsoleDTO):
    expected_version: int = Field(ge=1, strict=True)


class ConsoleRemoveRequest(ConsoleVersionRequest):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ConsoleMFAVerifyRequest(ConsoleDTO):
    code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    recovery_code: str | None = Field(default=None, min_length=8, max_length=64)

    @model_validator(mode="after")
    def exactly_one_factor(self) -> ConsoleMFAVerifyRequest:
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("Supply exactly one MFA code or recovery code.")
        return self


class ConsoleAdminSelf(ConsoleDTO):
    id: str
    email: str
    full_name: str
    role: Literal["manager", "viewer"]


class ConsoleAuthState(ConsoleDTO):
    state: Literal["mfa_enrollment_required", "mfa_challenge_required", "authenticated"]
    admin: ConsoleAdminSelf | None
    expires_at: datetime
    recovery_codes: list[str] | None = Field(default=None, repr=False)


class ConsoleAdminRecord(ConsoleAdminSelf):
    status: Literal["pending", "active", "revoked"]
    created_at: datetime


class ConsoleAdminsResponse(ConsoleDTO):
    items: list[ConsoleAdminRecord]
    next_cursor: str | None


class ConsoleManagedAdminRecord(ConsoleAdminRecord):
    can_manage: bool
    version: int
    removed_at: datetime | None


class ConsoleManagedAdminsResponse(ConsoleDTO):
    items: list[ConsoleManagedAdminRecord]
    next_cursor: str | None


class ConsoleInvitationResponse(ConsoleDTO):
    admin: ConsoleAdminRecord
    delivery_status: Literal["pending", "accepted", "failed", "outcome_unknown"]


class ConsoleMFAEnrollmentResponse(ConsoleDTO):
    secret: str
    otpauth_url: str


class ConsoleAcceptedResponse(ConsoleDTO):
    status: Literal["accepted"] = "accepted"


class ConsoleOKResponse(ConsoleDTO):
    status: Literal["complete"] = "complete"


class ConsoleLogoutResponse(ConsoleDTO):
    status: Literal["signed_out"] = "signed_out"


class ConsoleUsageRecord(ConsoleDTO):
    company_id: str
    feature_key: str
    quantity: int
    credits: int
    estimated_internal_cost_minor: int


class ConsoleProfitRecord(ConsoleDTO):
    company_id: str
    company_name: str | None
    period_start: PersistedUTCTimestamp
    period_end: PersistedUTCTimestamp
    gross_revenue_minor: int
    recognized_revenue_minor: int
    tax_minor: int
    tax_collected_minor: int
    discounts_minor: int
    discount_minor: int
    payment_provider_cost_minor: int
    payment_gateway_cost_minor: int
    llm_cost_minor: int
    embedding_cost_minor: int
    case_refresh_cost_minor: int
    document_processing_cost_minor: int
    storage_cost_minor: int
    manual_support_cost_minor: int
    manual_research_cost_minor: int
    total_variable_cost_minor: int
    gross_profit_minor: int
    gross_margin_bps: int | None
    status: str


class ConsoleRevenueRecord(ConsoleDTO):
    paid_at: PersistedUTCTimestamp | None
    company_id: str
    merchant_reference: str
    amount_paid_minor: int
    tax_amount_minor: int


class ConsoleReportPage(ConsoleDTO):
    items: list[
        ConsoleUsageRecord | ConsoleProfitRecord | ConsoleRevenueRecord | ConsoleCompanyProfitRecord
    ]
    generated_at: datetime
    next_cursor: str | None
    has_more: bool
    coverage: Literal["recorded_usage", "recorded_rollups", "recorded_payments"]


class ConsoleCompanyProfitRecord(ConsoleDTO):
    company_id: str
    company_name: str
    rollup_count: int
    gross_revenue_minor: int | None
    recognized_revenue_minor: int | None
    tax_minor: int | None
    discounts_minor: int | None
    payment_provider_cost_minor: int | None
    payment_gateway_cost_minor: int | None
    llm_cost_minor: int | None
    embedding_cost_minor: int | None
    case_refresh_cost_minor: int | None
    document_processing_cost_minor: int | None
    storage_cost_minor: int | None
    manual_support_cost_minor: int | None
    manual_research_cost_minor: int | None
    total_variable_cost_minor: int | None
    gross_profit_minor: int | None
    gross_margin_bps: int | None
    loss_risk: bool | None


class ConsoleMarginAlert(ConsoleDTO):
    company_id: str
    gross_margin_bps: int | None
    gross_profit_minor: int


class ConsoleCostGuardrailAlert(ConsoleDTO):
    type: Literal["case_refresh_cost_guardrail"]
    severity: Literal["warning"]
    category: str
    provider: str
    unit_amount_minor: int
    message: str


class ConsoleOverviewResponse(ConsoleDTO):
    generated_at: datetime
    coverage: Literal["recorded_rollups"] = "recorded_rollups"
    rollup_count: int
    mrr_minor: int
    arr_minor: int
    active_subscriptions: int
    trial_count: int
    failed_payments: int
    gross_revenue_minor: int | None
    recognized_revenue_minor: int | None
    total_variable_cost_minor: int | None
    gross_profit_minor: int | None
    gross_margin_bps: int | None
    margin_alerts: list[ConsoleMarginAlert | ConsoleCostGuardrailAlert]
    margin_alerts_has_more: bool
