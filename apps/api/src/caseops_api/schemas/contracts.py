from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from caseops_api.schemas.document_processing import DocumentProcessingJobRecord

ContractStatusLiteral = Literal[
    "draft",
    "under_review",
    "negotiation",
    "executed",
    "expired",
    "terminated",
]
ContractClauseRiskLevelLiteral = Literal["low", "medium", "high"]
ContractObligationStatusLiteral = Literal["pending", "in_progress", "completed", "waived"]
ContractObligationPriorityLiteral = Literal["low", "medium", "high"]
ContractPlaybookSeverityLiteral = Literal["low", "medium", "high"]
ContractPlaybookHitStatusLiteral = Literal["matched", "flagged", "missing"]


class ContractCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    contract_code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9-_/]+$")
    linked_matter_id: str | None = None
    owner_membership_id: str | None = None
    counterparty_name: str | None = Field(default=None, min_length=2, max_length=255)
    contract_type: str = Field(min_length=2, max_length=120)
    status: ContractStatusLiteral = "draft"
    jurisdiction: str | None = Field(default=None, min_length=2, max_length=255)
    effective_on: date | None = None
    expires_on: date | None = None
    renewal_on: date | None = None
    auto_renewal: bool = False
    currency: str = Field(default="INR", min_length=3, max_length=8)
    total_value_minor: int | None = Field(default=None, ge=0)
    summary: str | None = Field(default=None, max_length=4000)


class ContractUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    linked_matter_id: str | None = None
    owner_membership_id: str | None = None
    counterparty_name: str | None = Field(default=None, min_length=2, max_length=255)
    contract_type: str | None = Field(default=None, min_length=2, max_length=120)
    status: ContractStatusLiteral | None = None
    jurisdiction: str | None = Field(default=None, min_length=2, max_length=255)
    effective_on: date | None = None
    expires_on: date | None = None
    renewal_on: date | None = None
    auto_renewal: bool | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    total_value_minor: int | None = Field(default=None, ge=0)
    summary: str | None = Field(default=None, max_length=4000)


class ContractRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    linked_matter_id: str | None
    owner_membership_id: str | None
    title: str
    contract_code: str
    counterparty_name: str | None
    contract_type: str
    status: ContractStatusLiteral
    jurisdiction: str | None
    effective_on: date | None
    expires_on: date | None
    renewal_on: date | None
    auto_renewal: bool
    currency: str
    total_value_minor: int | None
    summary: str | None
    created_at: datetime
    updated_at: datetime


class ContractListResponse(BaseModel):
    company_id: str
    contracts: list[ContractRecord]


class ContractWorkspaceMembership(BaseModel):
    membership_id: str
    user_id: str
    full_name: str
    email: str
    role: str
    is_active: bool


class ContractLinkedMatterRecord(BaseModel):
    id: str
    matter_code: str
    title: str
    status: str
    forum_level: str


class ContractAttachmentRecord(BaseModel):
    id: str
    contract_id: str
    uploaded_by_membership_id: str | None
    uploaded_by_name: str | None
    original_filename: str
    content_type: str | None
    size_bytes: int
    sha256_hex: str
    processing_status: Literal["pending", "indexed", "needs_ocr", "failed"]
    extracted_char_count: int
    extraction_error: str | None
    processed_at: datetime | None
    latest_job: DocumentProcessingJobRecord | None
    created_at: datetime


class ContractClauseCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    clause_type: str = Field(min_length=2, max_length=120)
    clause_text: str = Field(min_length=5, max_length=10000)
    risk_level: ContractClauseRiskLevelLiteral = "medium"
    notes: str | None = Field(default=None, max_length=4000)


class ContractClauseRecord(BaseModel):
    id: str
    contract_id: str
    created_by_membership_id: str | None
    created_by_name: str | None
    title: str
    clause_type: str
    clause_text: str
    risk_level: ContractClauseRiskLevelLiteral
    notes: str | None
    created_at: datetime


class ContractObligationCreateRequest(BaseModel):
    owner_membership_id: str | None = None
    title: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    due_on: date | None = None
    status: ContractObligationStatusLiteral = "pending"
    priority: ContractObligationPriorityLiteral = "medium"


class ContractObligationRecord(BaseModel):
    id: str
    contract_id: str
    owner_membership_id: str | None
    owner_name: str | None
    title: str
    description: str | None
    due_on: date | None
    status: ContractObligationStatusLiteral
    priority: ContractObligationPriorityLiteral
    completed_at: datetime | None
    created_at: datetime


class ContractPlaybookRuleCreateRequest(BaseModel):
    rule_name: str = Field(min_length=2, max_length=255)
    clause_type: str = Field(min_length=2, max_length=120)
    expected_position: str = Field(min_length=5, max_length=4000)
    severity: ContractPlaybookSeverityLiteral = "medium"
    keyword_pattern: str | None = Field(default=None, min_length=2, max_length=255)
    fallback_text: str | None = Field(default=None, max_length=4000)


class ContractPlaybookRuleRecord(BaseModel):
    id: str
    contract_id: str
    created_by_membership_id: str | None
    created_by_name: str | None
    rule_name: str
    clause_type: str
    expected_position: str
    severity: ContractPlaybookSeverityLiteral
    keyword_pattern: str | None
    fallback_text: str | None
    created_at: datetime


class ContractPlaybookHitRecord(BaseModel):
    rule_id: str
    rule_name: str
    clause_type: str
    severity: ContractPlaybookSeverityLiteral
    expected_position: str
    keyword_pattern: str | None
    fallback_text: str | None
    matched_clause_id: str | None
    matched_clause_title: str | None
    status: ContractPlaybookHitStatusLiteral
    detail: str


class ContractActivityRecord(BaseModel):
    id: str
    contract_id: str
    actor_membership_id: str | None
    actor_name: str | None
    event_type: str
    title: str
    detail: str | None
    created_at: datetime


class ContractWorkspaceResponse(BaseModel):
    contract: ContractRecord
    linked_matter: ContractLinkedMatterRecord | None
    owner: ContractWorkspaceMembership | None
    available_owners: list[ContractWorkspaceMembership]
    attachments: list[ContractAttachmentRecord]
    clauses: list[ContractClauseRecord]
    obligations: list[ContractObligationRecord]
    playbook_rules: list[ContractPlaybookRuleRecord]
    playbook_hits: list[ContractPlaybookHitRecord]
    activity: list[ContractActivityRecord]
