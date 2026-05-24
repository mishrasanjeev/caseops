from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

GoogleDriveImportFileStatus = Literal[
    "valid",
    "invalid",
    "skipped_duplicate",
    "unsupported_mime",
]


class GoogleDriveProviderConfigStatus(BaseModel):
    provider: Literal["google_drive"] = "google_drive"
    configured: bool
    missing_config_names: list[str] = Field(default_factory=list)


class GoogleDriveFileMetadata(BaseModel):
    provider_file_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    mime_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=0)
    modified_time: datetime | None = None
    parent_folder_id: str | None = Field(default=None, max_length=200)
    parent_folder_name: str | None = Field(default=None, max_length=500)


class GoogleDriveImportDryRunRequest(BaseModel):
    folder_id: str | None = Field(default=None, max_length=200)
    folder_name: str | None = Field(default=None, max_length=500)
    files: list[GoogleDriveFileMetadata] = Field(default_factory=list)


class GoogleDriveImportFilePlan(BaseModel):
    provider_file_id: str
    name: str
    safe_name: str | None = None
    mime_type: str
    size_bytes: int
    modified_time: datetime | None = None
    category: str | None = None
    status: GoogleDriveImportFileStatus
    errors: list[str] = Field(default_factory=list)


class GoogleDriveImportDryRunSummary(BaseModel):
    dry_run: bool = True
    commit_supported: bool = False
    total_files: int
    valid_files: int
    invalid_files: int
    duplicate_files: int
    unsupported_mime_files: int
    will_create_attachment_count: int = 0
    storage_writes: int = 0
    corpus_jobs_queued: int = 0


class GoogleDriveImportDryRunResponse(BaseModel):
    company_id: str
    matter_id: str
    folder_id: str | None = None
    folder_name: str | None = None
    summary: GoogleDriveImportDryRunSummary
    files: list[GoogleDriveImportFilePlan]
    limitations: list[str] = Field(default_factory=list)
