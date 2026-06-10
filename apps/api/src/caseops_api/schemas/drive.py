from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DriveProviderLiteral = Literal["google_drive", "onedrive_sharepoint"]
DriveConnectionStatusLiteral = Literal["connected", "revoked", "error"]
DriveCandidateStatusLiteral = Literal[
    "new",
    "ignored",
    "linked_metadata",
    "content_import_requested",
    "content_imported",
    "failed",
]
DriveCandidateReviewActionLiteral = Literal[
    "link_metadata",
    "import_file",
    "ignore",
    "retry",
]


class GoogleDriveConnectionRecord(BaseModel):
    id: str
    company_id: str
    membership_id: str
    provider: DriveProviderLiteral = "google_drive"
    provider_account_id: str | None
    display_email: str | None
    status: DriveConnectionStatusLiteral
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None = None
    last_list_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class GoogleDriveStatusResponse(BaseModel):
    provider: DriveProviderLiteral = "google_drive"
    configured: bool
    missing_config_names: list[str] = Field(default_factory=list)
    connections: list[GoogleDriveConnectionRecord]


class GoogleDriveConnectionStartResponse(BaseModel):
    provider: DriveProviderLiteral = "google_drive"
    provider_available: bool
    auth_url: str | None = None
    unavailable_reason: str | None = None


class GoogleDriveConnectionCallbackResponse(BaseModel):
    provider: DriveProviderLiteral = "google_drive"
    connected: bool
    connection: GoogleDriveConnectionRecord


class GoogleDriveFileRecord(BaseModel):
    provider_file_id: str
    name: str
    mime_type: str | None = None
    size_bytes: int | None = None
    modified_time: datetime | None = None
    web_url: str | None = None


class GoogleDriveFileListResponse(BaseModel):
    provider: DriveProviderLiteral = "google_drive"
    connection_id: str
    files: list[GoogleDriveFileRecord]


class DriveSyncControlRecord(BaseModel):
    id: str
    company_id: str
    provider: DriveProviderLiteral
    allowed_folders: list[str] = Field(default_factory=list)
    blocked_folders: list[str] = Field(default_factory=list)
    max_file_size_bytes: int = Field(ge=1)
    allowed_mime_types: list[str] = Field(default_factory=list)
    mode: Literal["auto_suggest", "review_import"] = "review_import"
    auto_import_enabled: bool = False
    created_at: datetime
    updated_at: datetime


class DriveSyncControlUpdateRequest(BaseModel):
    allowed_folders: list[str] | None = None
    blocked_folders: list[str] | None = None
    max_file_size_bytes: int | None = Field(default=None, ge=1)
    allowed_mime_types: list[str] | None = None
    mode: Literal["auto_suggest", "review_import"] | None = None
    auto_import_enabled: bool | None = None


class DriveCandidateRecord(BaseModel):
    id: str
    company_id: str
    provider: DriveProviderLiteral
    provider_file_id: str
    provider_version: str
    name: str
    mime_type: str | None = None
    size_bytes: int | None = None
    owner_display: str | None = None
    modified_time: datetime | None = None
    folder_path: str | None = None
    web_url: str | None = None
    suggested_matter_id: str | None = None
    linked_matter_id: str | None = None
    confidence: float | None = None
    status: DriveCandidateStatusLiteral
    imported_attachment_id: str | None = None
    provenance: dict | None = None
    last_error_redacted: str | None = None
    created_at: datetime
    updated_at: datetime


class DriveCandidateListResponse(BaseModel):
    candidates: list[DriveCandidateRecord]
    pending_count: int = Field(ge=0)


class DriveCandidateSyncRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)


class DriveCandidateSyncResponse(BaseModel):
    provider: DriveProviderLiteral
    examined_count: int = Field(ge=0)
    created_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    candidates: list[DriveCandidateRecord]


class DriveCandidateReviewRequest(BaseModel):
    action: DriveCandidateReviewActionLiteral
    matter_id: str | None = Field(default=None, min_length=1, max_length=36)


class DriveCandidateReviewResponse(BaseModel):
    candidate: DriveCandidateRecord
    imported_attachment_id: str | None = None
