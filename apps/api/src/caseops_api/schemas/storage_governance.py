from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StorageQuotaState = Literal["unlimited", "ok", "warning", "hard_limit"]


class StorageUploadPolicy(BaseModel):
    company_id: str
    used_bytes: int
    quota_bytes: int | None
    remaining_bytes: int | None
    max_upload_size_bytes: int
    state: StorageQuotaState
    warning_threshold_percent: int


class StorageMatterUsage(BaseModel):
    matter_id: str
    matter_code: str
    matter_title: str
    used_bytes: int
    attachment_count: int


class StorageLargestFile(BaseModel):
    attachment_id: str
    matter_id: str
    matter_code: str
    matter_title: str
    original_filename: str
    size_bytes: int


class StorageArchiveCandidate(BaseModel):
    matter_id: str
    matter_code: str
    matter_title: str
    used_bytes: int
    attachment_count: int
    reason: str


class FirmStorageUsageSummary(StorageUploadPolicy):
    usage_by_matter: list[StorageMatterUsage]
    largest_files: list[StorageLargestFile]
    archive_candidates: list[StorageArchiveCandidate]


class FirmStorageQuotaPatchRequest(BaseModel):
    quota_bytes: int | None = Field(ge=0)
