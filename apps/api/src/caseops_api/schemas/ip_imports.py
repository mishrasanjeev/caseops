"""IPLF-032A bulk IP import contracts (UJ-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class IpImportRowInput(BaseModel):
    """One staged portfolio row as supplied by the operator."""

    row_number: int = Field(ge=1)
    values: dict[str, Any] = Field(default_factory=dict)


class IpImportJobCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    rows: list[IpImportRowInput] = Field(min_length=1, max_length=1000)


class IpImportRowRecord(BaseModel):
    id: str
    row_number: int
    validation_status: str
    errors: list[dict[str, Any]] = Field(default_factory=list)
    commit_status: str
    commit_error_code: str | None = None
    created_docket_id: str | None = None
    normalized: dict[str, Any] = Field(default_factory=dict)
    duplicate_candidates: list[dict[str, Any]] = Field(default_factory=list)
    reconciliation_decision: Literal["create_separate", "link_existing", "skip"] | None = None
    reconciled_target_docket_id: str | None = None


class IpImportJobRecord(BaseModel):
    id: str
    domain: str
    filename: str
    source_sha256: str
    status: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    committed_rows: int
    failed_rows: int
    preview_token: str | None
    preview_expires_at: datetime | None
    committed_at: datetime | None
    creator_label_snapshot: str
    version: int
    created_at: datetime


class IpImportPreviewResponse(BaseModel):
    job: IpImportJobRecord
    rows: list[IpImportRowRecord]
    preview_expired: bool = False


class IpImportCommitRequest(BaseModel):
    preview_token: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class IpImportCommitResponse(BaseModel):
    job: IpImportJobRecord
    rows: list[IpImportRowRecord]
    replayed: bool = False


class IpImportReconciliationDecision(BaseModel):
    row_id: str
    decision: Literal["create_separate", "link_existing", "skip"]
    target_docket_id: str | None = None


class IpImportReconciliationRequest(BaseModel):
    expected_job_version: int = Field(ge=1)
    decisions: list[IpImportReconciliationDecision] = Field(min_length=1, max_length=1000)


class IpImportJobListResponse(BaseModel):
    jobs: list[IpImportJobRecord] = Field(default_factory=list)
