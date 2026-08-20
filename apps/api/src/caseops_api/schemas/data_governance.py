"""Typed, dry-run-only contracts for IPLF-028A records governance.

These schemas are deliberately internal until the later user-workflow slice
has an approved rollout, authorization model, and production restore/export
evidence.  In particular, none of them represents an executable data action.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

DataOperationType = Literal[
    "tenant_export",
    "retention_purge",
    "tenant_offboarding",
    "restore_validation",
]
DataOperationItemStatus = Literal["pending", "eligible", "held", "blocked"]
DataOperationDryRunApprovalStatus = Literal["not_requested", "requested", "rejected"]


class TenantDataOperationItemInput(BaseModel):
    """An opaque target in a future data-operation dry run.

    ``target_reference_hash`` deliberately replaces a raw tenant/client/matter
    identifier so an operation manifest cannot become a second confidential
    record store.
    """

    data_class_id: str = Field(min_length=1, max_length=160)
    target_type: str = Field(min_length=1, max_length=80)
    target_reference_hash: str = Field(min_length=64, max_length=64)
    candidate_record_count: int = Field(default=0, ge=0)
    estimated_bytes: int = Field(default=0, ge=0)
    detail_redacted: str | None = Field(default=None, max_length=500)

    @field_validator("target_reference_hash")
    @classmethod
    def _hash_is_lower_hex(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("target_reference_hash must be a lowercase SHA-256 digest")
        return normalized


class TenantDataOperationDryRunRequest(BaseModel):
    """Request for an internal, non-executable manifest calculation."""

    operation_type: DataOperationType
    request_evidence_ref: str = Field(min_length=1, max_length=512)
    items: list[TenantDataOperationItemInput] = Field(min_length=1, max_length=500)
    retention_policy_version_id: str | None = Field(default=None, max_length=36)
    # DATA-GOV-06 point-in-time scope. Optional so existing callers keep working;
    # omitted means "as of now", which is recorded explicitly rather than left
    # implicit, because a manifest with no instant cannot be compared to another.
    as_of: datetime | None = Field(default=None)


class TenantDataOperationItemRecord(BaseModel):
    id: str
    data_class_id: str
    target_type: str
    target_reference_hash: str
    item_status: DataOperationItemStatus
    candidate_record_count: int
    estimated_bytes: int
    legal_hold_id: str | None
    safe_to_execute: Literal[False]
    detail_redacted: str | None


class TenantDataOperationExclusion(BaseModel):
    """A category the export withholds, and what the recipient can still ask for."""

    category: str
    reason: str
    reference_metadata: str


class TenantDataOperationUnsatisfiedDependency(BaseModel):
    """A table that references purge scope without being in it."""

    table: str
    references: str
    detail: str


class TenantDataOperationDependencyPlan(BaseModel):
    """DATA-GOV-08 dependency plan: what is removed, in what order."""

    schema_version: int
    deletion_order: list[str]
    unsatisfied_dependencies: list[TenantDataOperationUnsatisfiedDependency]
    # Non-empty means the deletion order could not account for every foreign key
    # touching the scope, so it must not be executed as though complete.
    unresolved_cycles: list[str]
    order_is_complete: bool


class TenantDataOperationOffboardingCategory(BaseModel):
    """One access surface an offboarding would revoke, stop, or preserve."""

    category: str
    disposition: Literal["revoke", "stop", "preserve", "unenumerable"]
    # None means the category has no tenant-scoped store to count, which is
    # reported rather than shown as zero.
    record_count: int | None
    detail: str


class TenantDataOperationDryRunRecord(BaseModel):
    id: str
    operation_type: DataOperationType
    execution_mode: Literal["dry_run"]
    status: Literal["dry_run_complete"]
    approval_status: DataOperationDryRunApprovalStatus
    rejection_reason: str | None
    request_scope_hash: str
    manifest_hash: str
    request_evidence_ref: str
    completed_at: datetime
    as_of: datetime
    dependency_plan: TenantDataOperationDependencyPlan | None
    offboarding_plan: list[TenantDataOperationOffboardingCategory]
    exclusions: list[TenantDataOperationExclusion]
    items: list[TenantDataOperationItemRecord]


class TenantDataOperationDryRunSummary(BaseModel):
    """Bounded discovery record for a tenant-owned dry-run manifest.

    The list endpoint deliberately omits items, exclusions, and other
    manifest detail. Operators use the exact-ID endpoint to review one
    immutable manifest after selecting it; a history listing must not become a
    second high-volume data-export surface.
    """

    id: str
    operation_type: DataOperationType
    execution_mode: Literal["dry_run"]
    status: Literal["dry_run_complete"]
    approval_status: DataOperationDryRunApprovalStatus
    rejection_reason: str | None
    request_scope_hash: str
    manifest_hash: str
    request_evidence_ref: str
    completed_at: datetime
    as_of: datetime


class TenantDataOperationDryRunListResponse(BaseModel):
    """A bounded, newest-first page of reviewable dry-run manifests."""

    operations: list[TenantDataOperationDryRunSummary]
