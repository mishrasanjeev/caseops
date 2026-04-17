from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

OutsideCounselPanelStatusLiteral = Literal["active", "preferred", "inactive"]
OutsideCounselAssignmentStatusLiteral = Literal["proposed", "approved", "active", "closed"]
OutsideCounselSpendStatusLiteral = Literal[
    "submitted",
    "approved",
    "partially_approved",
    "disputed",
    "paid",
]


class OutsideCounselCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    primary_contact_name: str | None = Field(default=None, min_length=2, max_length=255)
    primary_contact_email: str | None = Field(default=None, min_length=5, max_length=320)
    primary_contact_phone: str | None = Field(default=None, min_length=8, max_length=40)
    firm_city: str | None = Field(default=None, min_length=2, max_length=255)
    jurisdictions: list[str] = Field(default_factory=list, max_length=12)
    practice_areas: list[str] = Field(default_factory=list, max_length=12)
    panel_status: OutsideCounselPanelStatusLiteral = "active"
    internal_notes: str | None = Field(default=None, max_length=4000)


class OutsideCounselUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    primary_contact_name: str | None = Field(default=None, min_length=2, max_length=255)
    primary_contact_email: str | None = Field(default=None, min_length=5, max_length=320)
    primary_contact_phone: str | None = Field(default=None, min_length=8, max_length=40)
    firm_city: str | None = Field(default=None, min_length=2, max_length=255)
    jurisdictions: list[str] | None = Field(default=None, max_length=12)
    practice_areas: list[str] | None = Field(default=None, max_length=12)
    panel_status: OutsideCounselPanelStatusLiteral | None = None
    internal_notes: str | None = Field(default=None, max_length=4000)


class OutsideCounselAssignmentCreateRequest(BaseModel):
    matter_id: str
    counsel_id: str
    role_summary: str | None = Field(default=None, min_length=2, max_length=255)
    budget_amount_minor: int | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=8)
    status: OutsideCounselAssignmentStatusLiteral = "approved"
    internal_notes: str | None = Field(default=None, max_length=4000)


class OutsideCounselSpendRecordCreateRequest(BaseModel):
    matter_id: str
    counsel_id: str
    assignment_id: str | None = None
    invoice_reference: str | None = Field(default=None, min_length=2, max_length=120)
    stage_label: str | None = Field(default=None, min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=500)
    currency: str = Field(default="INR", min_length=3, max_length=8)
    amount_minor: int = Field(ge=0)
    approved_amount_minor: int | None = Field(default=None, ge=0)
    status: OutsideCounselSpendStatusLiteral = "submitted"
    billed_on: date | None = None
    due_on: date | None = None
    paid_on: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class OutsideCounselRecord(BaseModel):
    id: str
    company_id: str
    name: str
    primary_contact_name: str | None
    primary_contact_email: str | None
    primary_contact_phone: str | None
    firm_city: str | None
    jurisdictions: list[str]
    practice_areas: list[str]
    panel_status: OutsideCounselPanelStatusLiteral
    internal_notes: str | None
    total_matters_count: int
    active_matters_count: int
    total_spend_minor: int
    approved_spend_minor: int
    created_at: datetime
    updated_at: datetime


class OutsideCounselAssignmentRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str
    matter_title: str
    matter_code: str
    counsel_id: str
    counsel_name: str
    assigned_by_membership_id: str | None
    assigned_by_name: str | None
    role_summary: str | None
    budget_amount_minor: int | None
    currency: str
    status: OutsideCounselAssignmentStatusLiteral
    internal_notes: str | None
    created_at: datetime
    updated_at: datetime


class OutsideCounselSpendRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str
    matter_title: str
    matter_code: str
    counsel_id: str
    counsel_name: str
    assignment_id: str | None
    recorded_by_membership_id: str | None
    recorded_by_name: str | None
    invoice_reference: str | None
    stage_label: str | None
    description: str
    currency: str
    amount_minor: int
    approved_amount_minor: int
    status: OutsideCounselSpendStatusLiteral
    billed_on: date | None
    due_on: date | None
    paid_on: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class OutsideCounselPortfolioSummary(BaseModel):
    company_id: str
    total_counsel_count: int
    preferred_panel_count: int
    active_assignment_count: int
    total_budget_minor: int
    total_spend_minor: int
    approved_spend_minor: int
    disputed_spend_minor: int
    collected_invoice_minor: int
    outstanding_invoice_minor: int
    profitability_signal_minor: int


class OutsideCounselWorkspaceResponse(BaseModel):
    summary: OutsideCounselPortfolioSummary
    profiles: list[OutsideCounselRecord]
    assignments: list[OutsideCounselAssignmentRecord]
    spend_records: list[OutsideCounselSpendRecord]


class OutsideCounselRecommendationRequest(BaseModel):
    matter_id: str
    limit: int = Field(default=5, ge=1, le=10)


class OutsideCounselRecommendationRecord(BaseModel):
    counsel_id: str
    counsel_name: str
    panel_status: OutsideCounselPanelStatusLiteral
    score: float
    total_matters_count: int
    active_matters_count: int
    approved_spend_minor: int
    evidence: list[str]


class OutsideCounselRecommendationResponse(BaseModel):
    matter_id: str
    matter_title: str
    matter_code: str
    generated_at: datetime
    results: list[OutsideCounselRecommendationRecord]
