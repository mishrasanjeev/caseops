from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DriveProviderLiteral = Literal["google_drive"]
DriveConnectionStatusLiteral = Literal["connected", "revoked", "error"]


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
