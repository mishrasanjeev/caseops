from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
ContractTypeKeyLiteral = Literal[
    "agreement",
    "nda",
    "addendum",
    "purchase_order",
    "master_services_agreement",
    "statement_of_work",
    "lease",
    "employment",
    "settlement",
    "amendment",
    "other",
]
ContractLegalReferenceSourceLiteral = Literal["manual", "ai_suggested", "imported"]
ContractReviewStatusLiteral = Literal["suggested", "accepted", "rejected"]
ContractAttachmentRoleLiteral = Literal[
    "primary_contract",
    "amendment",
    "addendum",
    "annexure",
    "email_approval",
    "board_resolution",
    "purchase_order",
    "statement_of_work",
    "supporting_document",
    "other",
]


def _blank_to_none(value: object) -> object:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


class ContractCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    contract_code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9-_/]+$")
    linked_matter_id: str | None = None
    owner_membership_id: str | None = None
    counterparty_name: str | None = Field(default=None, min_length=2, max_length=255)
    contract_type: str = Field(min_length=2, max_length=120)
    contract_type_key: ContractTypeKeyLiteral | None = None
    contract_type_notes: str | None = Field(default=None, max_length=1000)
    status: ContractStatusLiteral = "draft"
    jurisdiction: str | None = Field(default=None, min_length=2, max_length=255)
    effective_on: date | None = None
    expires_on: date | None = None
    renewal_on: date | None = None
    auto_renewal: bool = False
    currency: str = Field(default="INR", min_length=3, max_length=8)
    total_value_minor: int | None = Field(default=None, ge=0)
    summary: str | None = Field(default=None, max_length=4000)

    @field_validator("contract_type_key", "contract_type_notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return _blank_to_none(value)


class ContractUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    linked_matter_id: str | None = None
    owner_membership_id: str | None = None
    counterparty_name: str | None = Field(default=None, min_length=2, max_length=255)
    contract_type: str | None = Field(default=None, min_length=2, max_length=120)
    contract_type_key: ContractTypeKeyLiteral | None = None
    contract_type_notes: str | None = Field(default=None, max_length=1000)
    status: ContractStatusLiteral | None = None
    jurisdiction: str | None = Field(default=None, min_length=2, max_length=255)
    effective_on: date | None = None
    expires_on: date | None = None
    renewal_on: date | None = None
    auto_renewal: bool | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    total_value_minor: int | None = Field(default=None, ge=0)
    summary: str | None = Field(default=None, max_length=4000)

    @field_validator("contract_type_key", "contract_type_notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return _blank_to_none(value)


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
    contract_type_key: ContractTypeKeyLiteral | None = None
    contract_type_notes: str | None = None
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
    next_cursor: str | None = None


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
    attachment_role: ContractAttachmentRoleLiteral | None = None
    parent_attachment_id: str | None = None
    document_date: date | None = None
    notes: str | None = None
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


class ContractMetadataUpdateRequest(BaseModel):
    contract_type: str | None = Field(default=None, min_length=2, max_length=120)
    contract_type_key: ContractTypeKeyLiteral | None = None
    contract_type_notes: str | None = Field(default=None, max_length=1000)
    effective_on: date | None = None
    expires_on: date | None = None
    renewal_on: date | None = None
    auto_renewal: bool | None = None

    @field_validator("contract_type_key", "contract_type_notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return _blank_to_none(value)


class ContractLegalReferenceCreateRequest(BaseModel):
    act_name: str = Field(min_length=2, max_length=255)
    section_label: str | None = Field(default=None, max_length=120)
    clause_label: str | None = Field(default=None, max_length=120)
    authority_id: str | None = Field(default=None, max_length=36)
    statute_id: str | None = Field(default=None, max_length=64)
    source: ContractLegalReferenceSourceLiteral = "manual"
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_attachment_id: str | None = Field(default=None, max_length=36)
    evidence_quote: str | None = Field(default=None, max_length=1000)
    status: ContractReviewStatusLiteral | None = None

    @field_validator(
        "section_label",
        "clause_label",
        "authority_id",
        "statute_id",
        "evidence_attachment_id",
        "evidence_quote",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return _blank_to_none(value)


class ContractLegalReferenceUpdateRequest(BaseModel):
    act_name: str | None = Field(default=None, min_length=2, max_length=255)
    section_label: str | None = Field(default=None, max_length=120)
    clause_label: str | None = Field(default=None, max_length=120)
    authority_id: str | None = Field(default=None, max_length=36)
    statute_id: str | None = Field(default=None, max_length=64)
    source: ContractLegalReferenceSourceLiteral | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_attachment_id: str | None = Field(default=None, max_length=36)
    evidence_quote: str | None = Field(default=None, max_length=1000)
    status: ContractReviewStatusLiteral | None = None

    @field_validator(
        "section_label",
        "clause_label",
        "authority_id",
        "statute_id",
        "evidence_attachment_id",
        "evidence_quote",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return _blank_to_none(value)


class ContractLegalReferenceRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    contract_id: str
    act_name: str
    section_label: str | None
    clause_label: str | None
    authority_id: str | None
    statute_id: str | None
    source: ContractLegalReferenceSourceLiteral
    confidence: float | None
    evidence_attachment_id: str | None
    evidence_attachment_name: str | None = None
    evidence_quote: str | None
    status: ContractReviewStatusLiteral
    created_by_membership_id: str | None
    reviewed_by_membership_id: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContractTermSuggestionCreateRequest(BaseModel):
    source_attachment_id: str | None = Field(default=None, max_length=36)
    suggested_effective_on: date | None = None
    suggested_expires_on: date | None = None
    suggested_renewal_on: date | None = None
    suggested_duration_months: int | None = Field(default=None, ge=0, le=1200)
    evidence_json: dict[str, object] = Field(default_factory=dict)

    @field_validator("source_attachment_id", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def require_suggested_term(self) -> ContractTermSuggestionCreateRequest:
        if not any(
            (
                self.suggested_effective_on,
                self.suggested_expires_on,
                self.suggested_renewal_on,
                self.suggested_duration_months is not None,
            )
        ):
            raise ValueError("At least one suggested contract term is required.")
        return self


class ContractTermSuggestionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    contract_id: str
    source_attachment_id: str | None
    source_attachment_name: str | None = None
    suggested_effective_on: date | None
    suggested_expires_on: date | None
    suggested_renewal_on: date | None
    suggested_duration_months: int | None
    evidence_json: dict[str, object]
    status: ContractReviewStatusLiteral
    created_by_membership_id: str | None
    reviewed_by_membership_id: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContractAttachmentMetadataUpdateRequest(BaseModel):
    attachment_role: ContractAttachmentRoleLiteral | None = None
    parent_attachment_id: str | None = Field(default=None, max_length=36)
    document_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("parent_attachment_id", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        return _blank_to_none(value)


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
    legal_references: list[ContractLegalReferenceRecord] = Field(default_factory=list)
    term_suggestions: list[ContractTermSuggestionRecord] = Field(default_factory=list)
    activity: list[ContractActivityRecord]


# --- Sprint 5 BG-011: contract intelligence responses ------------------


class ClauseExtractionResponse(BaseModel):
    contract_id: str
    inserted: int
    removed: int
    provider: str
    model: str


class ObligationExtractionResponse(BaseModel):
    contract_id: str
    inserted: int
    removed: int
    provider: str
    model: str


class PlaybookInstallResponse(BaseModel):
    contract_id: str
    installed: int


class PlaybookComparisonFindingRecord(BaseModel):
    rule_id: str
    rule_name: str
    clause_type: str
    severity: str
    status: str
    found_clause_id: str | None = None
    summary: str


class PlaybookComparisonResponse(BaseModel):
    contract_id: str
    findings: list[PlaybookComparisonFindingRecord]
    provider: str
    model: str


class RedlineChangeRecord(BaseModel):
    index: int
    kind: str
    author: str | None
    timestamp: str | None
    text: str
    paragraph_index: int
    context_before: str
    context_after: str


class RedlineParseResponse(BaseModel):
    attachment_id: str
    attachment_name: str
    paragraph_count: int
    insertion_count: int
    deletion_count: int
    author_counts: dict[str, int]
    changes: list[RedlineChangeRecord]
