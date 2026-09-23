from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MatterBulkUpdateRowStatus = Literal["valid", "invalid", "unchanged", "changed", "applied", "failed"]


class MatterBulkUpdateRow(BaseModel):
    row_number: int
    matter_id: str | None = None
    matter_code: str | None = None
    status: MatterBulkUpdateRowStatus
    errors: list[str] = Field(default_factory=list)
    changes: dict[str, dict[str, object]] = Field(default_factory=dict)
    expected_updated_at: datetime | None = None


class MatterBulkUpdateSummary(BaseModel):
    total_rows: int
    matched_rows: int
    changed_rows: int
    unchanged_rows: int
    invalid_rows: int


class MatterBulkUpdatePreviewResponse(BaseModel):
    preview_token: str
    headers: list[str]
    summary: MatterBulkUpdateSummary
    rows: list[MatterBulkUpdateRow]


class MatterBulkUpdateApplyResponse(BaseModel):
    preview_token: str
    applied_rows: int
    failed_rows: int
    rows: list[MatterBulkUpdateRow]
    operation_id: str


class MatterBulkUpdateHistoryRecord(BaseModel):
    id: str
    filename: str
    format: Literal["csv", "xlsx"]
    status: Literal["completed", "completed_with_errors", "stale"]
    total_rows: int
    changed_rows: int
    invalid_rows: int
    applied_rows: int
    failed_rows: int
    uploader_membership_id: str | None = None
    uploader_name: str | None = None
    uploader_email: str | None = None
    created_at: datetime


class MatterBulkUpdateHistoryResponse(BaseModel):
    operations: list[MatterBulkUpdateHistoryRecord]
    total: int
