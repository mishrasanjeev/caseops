from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

BulkMatterImportManifestFormat = Literal["csv", "json", "xlsx"]
BulkMatterImportRowStatus = Literal["valid", "invalid", "created", "failed"]
BulkMatterImportJobStatus = Literal[
    "validated",
    "importing",
    "completed",
    "completed_with_errors",
    "cancelled",
    "failed",
    "expired",
]
BulkMatterImportDocumentReferenceStatus = Literal[
    "available",
    "missing",
    "invalid",
    "unchecked",
]


class BulkMatterImportDuplicateCandidate(BaseModel):
    matter_id: str
    matter_code: str
    title: str
    client_name: str | None = None


class BulkMatterImportDocumentReference(BaseModel):
    filename: str
    category: str | None = None
    status: BulkMatterImportDocumentReferenceStatus


class BulkMatterImportRowPlan(BaseModel):
    row_number: int
    status: Literal["valid", "invalid"]
    matter_code: str | None = None
    title: str | None = None
    matter_type: str | None = None
    practice_area: str | None = None
    matter_status: str | None = None
    description: str | None = None
    client_name: str | None = None
    client_code: str | None = None
    client_contact_number: str | None = None
    client_email: str | None = None
    opposing_party_name: str | None = None
    opposing_counsel: str | None = None
    forum_level: str | None = None
    court_name: str | None = None
    court_forum_number: str | None = None
    case_number: str | None = None
    filing_number: str | None = None
    filing_date: date | None = None
    owner_email: str | None = None
    owner_membership_id: str | None = None
    team_slug: str | None = None
    team_id: str | None = None
    responsible_lawyer_email: str | None = None
    responsible_lawyer_membership_id: str | None = None
    document_references: list[BulkMatterImportDocumentReference] = Field(
        default_factory=list,
    )
    duplicate_candidates: list[BulkMatterImportDuplicateCandidate] = Field(
        default_factory=list,
    )
    errors: list[str] = Field(default_factory=list)


class BulkMatterImportDryRunSummary(BaseModel):
    dry_run: bool = True
    commit_supported: bool = False
    manifest_format: BulkMatterImportManifestFormat
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_candidate_rows: int
    document_reference_count: int
    unsupported_document_reference_count: int
    available_document_count: int
    will_create_matter_count: int = 0
    will_create_attachment_count: int = 0
    storage_writes: int = 0
    corpus_jobs_queued: int = 0


class BulkMatterImportDryRunResponse(BaseModel):
    company_id: str
    summary: BulkMatterImportDryRunSummary
    rows: list[BulkMatterImportRowPlan]
    limitations: list[str] = Field(default_factory=list)


class MatterImportRowRecord(BaseModel):
    id: str
    row_number: int
    status: BulkMatterImportRowStatus
    normalized: dict[str, object] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    created_matter_id: str | None = None


class MatterImportJobResponse(BaseModel):
    id: str
    company_id: str
    filename: str
    content_type: str | None = None
    manifest_format: BulkMatterImportManifestFormat
    file_size_bytes: int
    source_sha256: str
    status: BulkMatterImportJobStatus
    total_rows: int
    valid_rows: int
    invalid_rows: int
    created_count: int
    failed_count: int
    validation_error_count: int
    error_message: str | None = None
    uploaded_by_membership_id: str | None = None
    uploaded_by_name: str | None = None
    uploaded_by_email: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    imported_at: datetime | None = None
    cancelled_at: datetime | None = None
    rows: list[MatterImportRowRecord] = Field(default_factory=list)


class MatterImportCommitResponse(BaseModel):
    job: MatterImportJobResponse
    created_matter_ids: list[str] = Field(default_factory=list)


class MatterImportHistoryResponse(BaseModel):
    imports: list[MatterImportJobResponse] = Field(default_factory=list)
    total: int
