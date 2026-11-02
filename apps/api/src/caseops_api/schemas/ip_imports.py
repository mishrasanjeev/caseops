"""IPLF-032A bulk IP import contracts (UJ-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from caseops_api.schemas.ip_operations import (
    IpDocketCreateRequest,
    TrademarkParticularPayload,
    TrademarkParty,
)


class IpImportClassScope(BaseModel):
    class_number: int = Field(ge=1, le=45)
    specification: str = Field(default="", max_length=4000)


class IpImportParticularPayload(TrademarkParticularPayload):
    """Source-incomplete drafts, never a substitute for filing readiness.

    Missing facts stay empty. The import writer supplies unresolved required
    manifest items so the canonical writer retains its draft/legal fences.
    Interactive filing contracts remain unchanged.
    """

    classes: list[IpImportClassScope] = Field(default_factory=list, max_length=45)
    parties: list[TrademarkParty] = Field(default_factory=list, max_length=30)

    incomplete_class_rows_allowed: ClassVar[bool] = True


class IpImportDocketCreateRequest(IpDocketCreateRequest):
    particulars: IpImportParticularPayload


class IpImportDocketVersionCreateRequest(IpImportParticularPayload):
    expected_current_version: int = Field(ge=1)
    finalize: Literal[False] = False


class IpImportRowInput(BaseModel):
    """One staged portfolio row as supplied by the operator."""

    row_number: int = Field(ge=1)
    values: dict[str, Any] = Field(default_factory=dict)


class IpImportJobCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    rows: list[IpImportRowInput] = Field(min_length=1, max_length=1000)


class IpParsedImportJobCreateRequest(IpImportJobCreateRequest):
    source_sha256: str = Field(min_length=64, max_length=64)


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
    recovery_available: bool = False
    commit_batch_size: int = Field(default=50, ge=1, le=50)


class IpImportPreviewResponse(BaseModel):
    job: IpImportJobRecord
    rows: list[IpImportRowRecord]
    preview_expired: bool = False


class IpImportCommitRequest(BaseModel):
    preview_token: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class IpImportResumeRequest(BaseModel):
    expected_job_version: int = Field(ge=1)
    preview_token: str | None = None


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
