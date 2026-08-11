"""Audit export schemas (§10.4)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AuditExportFormat = Literal["jsonl", "csv"]
AuditExportJobStatusLiteral = Literal["pending", "running", "completed", "failed"]


class AuditExportAsyncRequest(BaseModel):
    format: AuditExportFormat = "jsonl"
    since: datetime | None = None
    until: datetime | None = None
    action: str | None = Field(default=None, max_length=120)
    row_limit: int | None = Field(default=None, ge=1, le=500_000)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "format": "csv",
                    "since": "2026-04-01T00:00:00Z",
                    "until": "2026-04-18T23:59:59Z",
                    "action": "draft.approve",
                    "row_limit": 50000,
                }
            ]
        }
    }


class AuditExportJobRecord(BaseModel):
    id: str
    company_id: str
    status: AuditExportJobStatusLiteral
    format: AuditExportFormat
    since: datetime | None
    until: datetime | None
    action_filter: str | None
    row_limit: int | None
    row_count: int | None
    size_bytes: int | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    download_ready: bool


class AuditExportJobListResponse(BaseModel):
    jobs: list[AuditExportJobRecord]


class MatterAuditEventRecord(BaseModel):
    id: str
    company_id: str
    actor_type: str
    actor_membership_id: str | None
    actor_label: str | None
    matter_id: str | None
    ip_docket_id: str | None = None
    action: str
    target_type: str
    target_id: str | None
    result: str
    metadata: dict[str, Any] | None = None
    request_id: str | None = None
    created_at: datetime


class MatterAuditListResponse(BaseModel):
    matter_id: str
    events: list[MatterAuditEventRecord]
    total: int
    limit: int
    offset: int


class IpDocketAuditListResponse(BaseModel):
    ip_docket_id: str
    events: list[MatterAuditEventRecord]
    total: int
    limit: int
    offset: int
