from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BulkMatterImportManifestFormat = Literal["csv", "json", "xlsx"]
BulkMatterImportRowStatus = Literal["valid", "invalid"]
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
    status: BulkMatterImportRowStatus
    matter_code: str | None = None
    title: str | None = None
    client_name: str | None = None
    practice_area: str | None = None
    matter_type: str | None = None
    matter_status: str | None = None
    forum_level: str | None = None
    court_name: str | None = None
    owner_email: str | None = None
    team_slug: str | None = None
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
