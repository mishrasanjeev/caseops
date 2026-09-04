from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

BillingInterval = Literal["month", "year", "one_time", "custom"]
CheckoutType = Literal["new_subscription", "renewal", "upgrade", "topup", "addon", "manual_invoice"]


class BillingPriceRecord(BaseModel):
    id: str
    amount_minor: int | None
    currency: str
    interval: str
    tax_behavior: str
    tax_rate_bps: int


class BillingPlanRecord(BaseModel):
    id: str
    plan_code: str
    version: str
    segment: str
    display_name: str
    description: str | None
    publicly_visible: bool
    trial_eligible: bool
    prices: list[BillingPriceRecord]
    entitlements: dict[str, Any]


class BillingPlansResponse(BaseModel):
    version: str
    plans: list[BillingPlanRecord]
    add_ons: list[BillingPlanRecord]


class BillingAccountRecord(BaseModel):
    id: str
    company_id: str
    billing_email: str | None
    billing_name: str | None
    billing_phone: str | None
    gstin: str | None
    billing_address: dict[str, Any] | None
    tax_treatment: str | None


class BillingSubscriptionRecord(BaseModel):
    id: str
    plan_code: str | None
    plan_name: str | None
    status: str
    segment: str
    billing_interval: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    trial_end: datetime | None
    cancel_at_period_end: bool
    externally_billable: bool
    source: str


class BillingUsageSnapshot(BaseModel):
    ai_credits_included: int | None = None
    ai_credits_used: int = 0
    ai_credits_remaining: int | None = None
    topup_credits_available: int = 0
    tracked_cases_used: int = 0
    tracked_cases_limit: int | None = None
    manual_refreshes_used_today: int = 0
    manual_refreshes_limit_daily: int | None = None
    storage_used_bytes: int = 0
    storage_limit_bytes: int | None = None
    users_internal_used: int = 0
    users_internal_limit: int | None = None
    users_viewer_used: int = 0
    users_viewer_limit: int | None = None
    matters_active_used: int = 0
    matters_active_limit: int | None = None


class BillingCurrentResponse(BaseModel):
    billing_account: BillingAccountRecord | None
    subscription: BillingSubscriptionRecord | None
    entitlements: dict[str, Any]
    usage: BillingUsageSnapshot
    payment_provider: dict[str, Any]


class BillingCheckoutRequest(BaseModel):
    plan_code: str | None = None
    interval: BillingInterval = "month"
    checkout_type: CheckoutType = "new_subscription"
    quantity: int = Field(default=1, ge=1, le=1000)
    success_url: str | None = Field(default=None, max_length=1000)
    cancel_url: str | None = Field(default=None, max_length=1000)
    coupon_code: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddOnCheckoutRequest(BaseModel):
    add_on_code: str
    quantity: int = Field(default=1, ge=1, le=1000)
    success_url: str | None = Field(default=None, max_length=1000)
    cancel_url: str | None = Field(default=None, max_length=1000)


class BillingCheckoutResponse(BaseModel):
    id: str
    checkout_type: str
    status: str
    amount_minor: int
    tax_amount_minor: int
    total_amount_minor: int
    currency: str
    provider: str | None
    provider_checkout_url: str | None
    provider_order_id: str | None
    provider_disabled: bool
    next_action: str
    created_at: datetime
    expires_at: datetime | None


class BillingCreditLedgerRecord(BaseModel):
    id: str
    credit_bucket: str
    event_type: str
    delta: int
    balance_after: int
    reason: str | None
    source_object_type: str | None
    source_object_id: str | None
    expires_at: datetime | None
    created_at: datetime


class BillingCreditLedgerResponse(BaseModel):
    rows: list[BillingCreditLedgerRecord]


class BillingUsageBreakdownRow(BaseModel):
    key: str
    label: str
    quantity: int
    credits: int


class BillingProviderSpendRow(BaseModel):
    provider_key: str
    label: str
    spent_minor: int = Field(ge=0)
    monthly_limit_minor: int | None = Field(default=None, ge=0)
    remaining_minor: int | None = Field(default=None, ge=0)
    unlimited: bool
    currency: str = "INR"
    policy_source: str


class BillingUsageReportResponse(BaseModel):
    period_start: datetime | None
    period_end: datetime | None
    snapshot: BillingUsageSnapshot
    by_feature: list[BillingUsageBreakdownRow]
    by_user: list[BillingUsageBreakdownRow]
    by_matter: list[BillingUsageBreakdownRow]
    by_tracked_case: list[BillingUsageBreakdownRow]
    daily: list[BillingUsageBreakdownRow]
    by_provider: list[BillingProviderSpendRow] = Field(default_factory=list)
    blocked_events: list[BillingUsageBreakdownRow] = []


class BillingInvoiceRecord(BaseModel):
    id: str
    invoice_number: str
    invoice_type: str
    amount_minor: int
    tax_amount_minor: int
    total_amount_minor: int
    amount_received_minor: int
    currency: str
    status: str
    issued_on: date | None
    due_on: date | None
    paid_on: date | None


class BillingInvoiceListResponse(BaseModel):
    invoices: list[BillingInvoiceRecord]


class TrialStartRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=255)
    company_slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    company_type: Literal["law_firm", "corporate_legal", "solo"]
    owner_full_name: str = Field(min_length=2, max_length=255)
    owner_email: EmailStr
    owner_password: str = Field(min_length=12, max_length=128)
    mobile: str | None = Field(default=None, max_length=40)
    gstin: str | None = Field(default=None, max_length=20)
    selected_plan: str | None = Field(default=None, max_length=80)
    source: str = Field(default="pricing_page", max_length=40)
    coupon_code: str | None = Field(default=None, max_length=80)


class DemoRequest(BaseModel):
    contact_name: str = Field(min_length=2, max_length=255)
    contact_email: EmailStr
    contact_mobile: str | None = Field(default=None, max_length=40)
    company_name: str | None = Field(default=None, max_length=255)
    segment: Literal["solo", "firm", "gc"]
    selected_plan: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)
    source: str = Field(default="demo", max_length=40)


class DemoRequestResponse(BaseModel):
    id: str
    status: str


class SubscriptionActionResponse(BaseModel):
    subscription: BillingSubscriptionRecord


class PlatformAdminMeResponse(BaseModel):
    platform_admin: dict[str, Any]


class PlatformOverviewResponse(BaseModel):
    mrr_minor: int
    arr_minor: int
    active_subscriptions: int
    trial_count: int
    failed_payments: int
    gross_revenue_minor: int
    recognized_revenue_minor: int
    total_variable_cost_minor: int
    gross_profit_minor: int
    gross_margin_bps: int | None
    margin_alerts: list[dict[str, Any]]


class PlatformSubscriptionMutation(BaseModel):
    plan_code: str | None = None
    billing_interval: str = "month"
    status: str = "manual_active"
    reason: str = Field(min_length=3, max_length=1000)


class PlatformReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class PlatformGrantCreditsRequest(BaseModel):
    credits: int = Field(gt=0, le=1_000_000)
    reason: str = Field(min_length=3, max_length=1000)


class PlatformManualInvoiceCreateRequest(BaseModel):
    company_id: str
    subscription_id: str | None = None
    invoice_number: str = Field(min_length=2, max_length=80)
    po_number: str | None = Field(default=None, max_length=120)
    amount_minor: int = Field(ge=0)
    tax_amount_minor: int = Field(default=0, ge=0)
    due_on: date | None = None
    reason: str = Field(min_length=3, max_length=1000)


class PlatformManualInvoicePaidRequest(BaseModel):
    amount_received_minor: int = Field(ge=0)
    tds_deducted_minor: int = Field(default=0, ge=0)
    payment_reference: str = Field(min_length=2, max_length=255)
    paid_on: date | None = None
    reason: str = Field(min_length=3, max_length=1000)


class PlatformCouponCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    description: str | None = None
    discount_type: Literal["percent", "fixed_amount"]
    discount_value: int = Field(gt=0)
    currency: str | None = "INR"
    duration: Literal["once", "first_period", "repeating", "forever"] = "once"
    duration_periods: int | None = None
    max_redemptions: int | None = None
    valid_until: datetime | None = None
    reason: str = Field(min_length=3, max_length=1000)


class PlatformOveragePolicyRequest(BaseModel):
    overage_allowed: bool
    unit_prices: dict[str, int] = Field(default_factory=dict)
    cap_amount_minor: int | None = Field(default=None, ge=0)
    ends_at: datetime | None = None
    reason: str = Field(min_length=3, max_length=1000)
