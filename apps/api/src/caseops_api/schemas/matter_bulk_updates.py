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
