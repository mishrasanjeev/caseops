from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# EH-SGR-02: must admit every InvoiceStatus member. `needs_review` is written by
# the outside-counsel portal on invoice submission; omitting it here made the
# owning matter permanently unreadable rather than merely failing validation.
InvoiceStatusLiteral = Literal[
    "draft",
    "needs_review",
    "issued",
    "partially_paid",
    "paid",
    "void",
]
PaymentAttemptStatusLiteral = Literal[
    "pending",
    "created",
    "partially_paid",
    "paid",
    # EH-SGR-02: services/pine_labs.py maps a refund_processed webhook to
    # "refunded" and services/payments.py assigns it straight onto the attempt.
    "refunded",
    "failed",
    "cancelled",
    "expired",
    "unknown",
]


class TimeEntryCreateRequest(BaseModel):
    work_date: date
    description: str = Field(min_length=2, max_length=500)
    duration_minutes: int = Field(ge=1, le=1440)
    billable: bool = True
    rate_currency: str = Field(default="INR", min_length=3, max_length=8)
    rate_amount_minor: int | None = Field(default=None, ge=0)


class TimeEntryRecord(BaseModel):
    id: str
    matter_id: str
    author_membership_id: str | None
    author_name: str | None
    work_date: date
    description: str
    duration_minutes: int
    billable: bool
    rate_currency: str
    rate_amount_minor: int | None
    billing_rate_id: str | None = None
    rate_source: str | None = None
    total_amount_minor: int
    is_invoiced: bool
    created_at: datetime


class InvoiceManualItemCreateRequest(BaseModel):
    description: str = Field(min_length=2, max_length=500)
    amount_minor: int = Field(ge=0)
    category: str | None = Field(default=None, max_length=80)
    sac_hsn: str | None = Field(default=None, max_length=32)


class InvoiceCreateRequest(BaseModel):
    invoice_number: str | None = Field(
        default=None,
        min_length=2,
        max_length=80,
        pattern=r"^[A-Za-z0-9-_/]+$",
    )
    issued_on: date
    due_on: date | None = None
    client_name: str | None = Field(default=None, min_length=2, max_length=255)
    client_billing_name: str | None = Field(default=None, min_length=2, max_length=255)
    client_billing_address: str | None = Field(default=None, max_length=4000)
    client_gstin: str | None = Field(default=None, max_length=32)
    place_of_supply: str | None = Field(default=None, max_length=120)
    sac_hsn: str | None = Field(default=None, max_length=32)
    status: InvoiceStatusLiteral = "draft"
    notes: str | None = Field(default=None, max_length=4000)
    tax_amount_minor: int = Field(default=0, ge=0)
    tds_deducted_minor: int = Field(default=0, ge=0)
    payment_adjustment_minor: int = Field(default=0)
    include_uninvoiced_time_entries: bool = True
    manual_items: list[InvoiceManualItemCreateRequest] = Field(default_factory=list)


class InvoiceLineItemRecord(BaseModel):
    id: str
    invoice_id: str
    time_entry_id: str | None
    description: str
    duration_minutes: int | None
    unit_rate_amount_minor: int | None
    line_total_amount_minor: int
    category: str | None = None
    sac_hsn: str | None = None
    created_at: datetime


class PaymentLinkCreateRequest(BaseModel):
    customer_name: str | None = Field(default=None, min_length=2, max_length=255)
    customer_email: str | None = Field(default=None, min_length=5, max_length=320)
    customer_phone: str | None = Field(default=None, min_length=8, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    amount_minor: int | None = Field(default=None, ge=1)


class InvoicePaymentAttemptRecord(BaseModel):
    id: str
    invoice_id: str
    initiated_by_membership_id: str | None
    initiated_by_name: str | None
    provider: str
    merchant_order_id: str
    provider_order_id: str | None
    status: PaymentAttemptStatusLiteral
    amount_minor: int
    amount_received_minor: int
    currency: str
    customer_name: str | None
    customer_email: str | None
    customer_phone: str | None
    payment_url: str | None
    provider_reference: str | None
    last_webhook_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoiceRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str
    issued_by_membership_id: str | None
    issued_by_name: str | None
    invoice_number: str
    client_name: str | None
    client_billing_name: str | None = None
    client_billing_address: str | None = None
    client_gstin: str | None = None
    place_of_supply: str | None = None
    sac_hsn: str | None = None
    firm_legal_name: str | None = None
    firm_address: str | None = None
    firm_gstin: str | None = None
    firm_pan: str | None = None
    status: InvoiceStatusLiteral
    currency: str
    subtotal_amount_minor: int
    taxable_value_minor: int = 0
    cgst_amount_minor: int = 0
    sgst_amount_minor: int = 0
    igst_amount_minor: int = 0
    tax_amount_minor: int
    total_amount_minor: int
    amount_received_minor: int
    tds_deducted_minor: int = 0
    payment_adjustment_minor: int = 0
    balance_due_minor: int
    issued_on: date
    due_on: date | None
    notes: str | None
    pine_labs_payment_url: str | None
    pine_labs_order_id: str | None
    created_at: datetime
    updated_at: datetime
    line_items: list[InvoiceLineItemRecord]
    payment_attempts: list[InvoicePaymentAttemptRecord]


class PaymentWebhookAckResponse(BaseModel):
    accepted: bool
    provider: str
    provider_order_id: str | None
    already_processed: bool = False
