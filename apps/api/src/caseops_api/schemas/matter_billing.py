from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

BillingModeLiteral = Literal["hourly", "fixed_fee", "milestone", "mixed"]
BillingRateScopeLiteral = Literal["user", "role", "practice_area", "default"]


class MatterBillingRateCreateRequest(BaseModel):
    rate_scope: BillingRateScopeLiteral = "default"
    membership_id: str | None = Field(default=None, max_length=36)
    role: str | None = Field(default=None, max_length=32)
    practice_area: str | None = Field(default=None, max_length=120)
    currency: str = Field(default="INR", min_length=3, max_length=8)
    amount_minor_per_hour: int = Field(ge=0)
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool = True

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value


class MatterBillingProfileCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    is_default: bool = False
    currency: str = Field(default="INR", min_length=3, max_length=8)
    firm_legal_name: str | None = Field(default=None, max_length=255)
    firm_address: str | None = Field(default=None, max_length=4000)
    firm_gstin: str | None = Field(default=None, max_length=32)
    firm_pan: str | None = Field(default=None, max_length=16)
    default_place_of_supply: str | None = Field(default=None, max_length=120)
    default_sac_hsn: str | None = Field(default=None, max_length=32)
    gst_applicable: bool = False
    gstin_state_code: str | None = Field(default=None, min_length=2, max_length=2)
    cgst_rate_bps: int = Field(default=0, ge=0, le=10000)
    sgst_rate_bps: int = Field(default=0, ge=0, le=10000)
    igst_rate_bps: int = Field(default=0, ge=0, le=10000)
    tax_rate_bps: int = Field(default=0, ge=0, le=10000)
    invoice_prefix: str = Field(default="INV", min_length=1, max_length=40)
    next_invoice_sequence: int = Field(default=1, ge=1)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    billing_mode: BillingModeLiteral = "hourly"
    default_rate_minor_per_hour: int | None = Field(default=None, ge=0)
    notes_template: str | None = Field(default=None, max_length=4000)
    footer_text: str | None = Field(default=None, max_length=4000)
    expense_categories: list[str] = Field(default_factory=list, max_length=50)
    retainer_adjustments_enabled: bool = False

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator(
        "name",
        "firm_legal_name",
        "firm_address",
        "firm_gstin",
        "firm_pan",
        "default_place_of_supply",
        "default_sac_hsn",
        "gstin_state_code",
        "invoice_prefix",
        "notes_template",
        "footer_text",
        mode="before",
    )
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class MatterBillingProfileUpdateRequest(MatterBillingProfileCreateRequest):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    is_default: bool | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    gst_applicable: bool | None = None
    cgst_rate_bps: int | None = Field(default=None, ge=0, le=10000)
    sgst_rate_bps: int | None = Field(default=None, ge=0, le=10000)
    igst_rate_bps: int | None = Field(default=None, ge=0, le=10000)
    tax_rate_bps: int | None = Field(default=None, ge=0, le=10000)
    invoice_prefix: str | None = Field(default=None, min_length=1, max_length=40)
    next_invoice_sequence: int | None = Field(default=None, ge=1)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    billing_mode: BillingModeLiteral | None = None
    default_rate_minor_per_hour: int | None = Field(default=None, ge=0)
    expense_categories: list[str] | None = Field(default=None, max_length=50)
    retainer_adjustments_enabled: bool | None = None


class MatterBillingRateRecord(BaseModel):
    id: str
    company_id: str
    billing_profile_id: str
    rate_scope: str
    membership_id: str | None
    role: str | None
    practice_area: str | None
    currency: str
    amount_minor_per_hour: int
    effective_from: date | None
    effective_to: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MatterBillingProfileRecord(BaseModel):
    id: str
    company_id: str
    name: str
    is_default: bool
    currency: str
    firm_legal_name: str | None
    firm_address: str | None
    firm_gstin: str | None
    firm_pan: str | None
    default_place_of_supply: str | None
    default_sac_hsn: str | None
    gst_applicable: bool
    gstin_state_code: str | None
    cgst_rate_bps: int
    sgst_rate_bps: int
    igst_rate_bps: int
    tax_rate_bps: int
    invoice_prefix: str
    next_invoice_sequence: int
    payment_terms_days: int
    billing_mode: str
    default_rate_minor_per_hour: int | None
    notes_template: str | None
    footer_text: str | None
    expense_categories: list[str]
    retainer_adjustments_enabled: bool
    created_at: datetime
    updated_at: datetime
    rates: list[MatterBillingRateRecord] = Field(default_factory=list)


class MatterBillingProfileListResponse(BaseModel):
    profiles: list[MatterBillingProfileRecord]


class InvoiceNumberPreviewResponse(BaseModel):
    invoice_number: str
    next_invoice_sequence: int
