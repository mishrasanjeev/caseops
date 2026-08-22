"""Neutral read contract for canonical and legacy bulk-import jobs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BulkImportDomain = Literal["ip_trademark", "matter", "employee"]
BulkImportLifecycle = Literal[
    "staged",
    "preview_ready",
    "in_progress",
    "committed",
    "committed_with_errors",
    "failed",
    "cancelled",
    "expired",
]
BulkImportSourceOwner = Literal[
    "bulk_import_jobs",
    "matter_bulk_import_jobs",
    "employee_bulk_import_jobs",
]


class BulkImportJobSummary(BaseModel):
    id: str
    domain: BulkImportDomain
    source_owner: BulkImportSourceOwner
    read_only_adapter: bool
    filename: str
    content_type: str | None = None
    source_sha256: str | None = None
    source_status: str
    status: BulkImportLifecycle
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    committed_rows: int = 0
    failed_rows: int = 0
    created_by_membership_id: str | None = None
    creator_label: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    completed_at: datetime | None = None
    manifest_url: str
    error_report_url: str


class BulkImportHistoryResponse(BaseModel):
    jobs: list[BulkImportJobSummary] = Field(default_factory=list)
    accessible_domains: list[BulkImportDomain] = Field(default_factory=list)


class BulkImportManifest(BaseModel):
    schema_version: Literal["bulk-import-manifest-v1"] = "bulk-import-manifest-v1"
    compatibility_mode: Literal["canonical", "read_only_adapter"]
    job: BulkImportJobSummary
    file_size_bytes: int | None = None
    manifest_format: str | None = None
    limitations: list[str] = Field(default_factory=list)
