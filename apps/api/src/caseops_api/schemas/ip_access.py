from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

IpAccessSubjectType = Literal["membership", "team"]
IpAccessChangeAction = Literal[
    "set_restricted",
    "grant",
    "revoke_grant",
    "add_wall",
    "revoke_wall",
]


class RecordAccessFoundationContract(BaseModel):
    contract_version: Literal["record-access-v1"] = "record-access-v1"
    canonical_writer: Literal[
        "MatterAccessGrant/EthicalWall via services/matter_access.py"
    ] = "MatterAccessGrant/EthicalWall via services/matter_access.py"
    supported_targets: list[Literal["matter", "ip_docket"]]
    supported_subjects: list[Literal["membership", "team"]]
    owner_bypass: dict[str, bool]
    forbidden_parallel_owners: list[str]
    excluded_persistence: list[str]


class RecordAccessReconciliationReport(BaseModel):
    generated_at: datetime
    company_id: str
    legacy_tail_count: int
    invalid_target_count: int
    invalid_subject_count: int
    target_company_mismatch_count: int
    subject_company_mismatch_count: int
    uncorrelated_ip_audit_count: int
    healthy: bool


class IpAccessGrantRecord(BaseModel):
    id: str
    subject_type: IpAccessSubjectType
    subject_id: str
    subject_label: str
    access_level: Literal["member"]
    reason: str | None
    effective_from: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    granted_by_membership_id: str | None
    revoked_by_membership_id: str | None
    record_version: int
    created_at: datetime


class IpEthicalWallRecord(BaseModel):
    id: str
    subject_type: IpAccessSubjectType
    subject_id: str
    subject_label: str
    reason: str | None
    effective_from: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_by_membership_id: str | None
    revoked_by_membership_id: str | None
    record_version: int
    created_at: datetime


class IpAccessPanelResponse(BaseModel):
    docket_id: str
    docket_title: str
    restricted: bool
    access_policy_version: int
    linked_matter_id: str | None
    grants: list[IpAccessGrantRecord]
    walls: list[IpEthicalWallRecord]
    active_internal_membership_count: int
    queued_delivery_count: int
    excluded_persistence: list[str] = Field(
        default_factory=lambda: [
            "portal_grants",
            "access_review_campaigns",
            "emergency_access_sessions",
        ]
    )


class IpAccessChangeRequest(BaseModel):
    action: IpAccessChangeAction
    expected_access_policy_version: int = Field(ge=0)
    reason: str = Field(min_length=5, max_length=2000)
    subject_type: IpAccessSubjectType | None = None
    subject_id: str | None = Field(default=None, min_length=1, max_length=36)
    grant_id: str | None = Field(default=None, min_length=1, max_length=36)
    wall_id: str | None = Field(default=None, min_length=1, max_length=36)
    restricted: bool | None = None
    effective_from: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_action_fields(self) -> IpAccessChangeRequest:
        if self.action in {"grant", "add_wall"}:
            if self.subject_type is None or self.subject_id is None:
                raise ValueError("subject_type and subject_id are required for this action")
        if self.action == "revoke_grant" and self.grant_id is None:
            raise ValueError("grant_id is required for revoke_grant")
        if self.action == "revoke_wall" and self.wall_id is None:
            raise ValueError("wall_id is required for revoke_wall")
        if self.action == "set_restricted" and self.restricted is None:
            raise ValueError("restricted is required for set_restricted")
        if self.expires_at is not None:
            start = self.effective_from or datetime.now(UTC)
            normalized_start = (
                start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
            )
            normalized_expiry = (
                self.expires_at.replace(tzinfo=UTC)
                if self.expires_at.tzinfo is None
                else self.expires_at.astimezone(UTC)
            )
            if normalized_expiry <= normalized_start:
                raise ValueError("expires_at must be later than effective_from")
        return self


class IpAccessApplyRequest(IpAccessChangeRequest):
    preview_token: str = Field(min_length=64, max_length=64)


class IpAccessAffectedMembership(BaseModel):
    membership_id: str
    label: str
    before_visible: bool
    after_visible: bool
    linked_matter_visible: bool | None


class IpAccessPreviewResponse(BaseModel):
    docket_id: str
    access_policy_version: int
    action: IpAccessChangeAction
    preview_token: str
    affected_memberships: list[IpAccessAffectedMembership]
    visibility_gain_count: int
    visibility_loss_count: int
    queued_delivery_recheck_count: int
    document_count: int
    linked_matter_id: str | None
    linked_matter_mismatch: bool
    warnings: list[str]
    requires_step_up: Literal[True] = True


class IpAccessChangeResponse(BaseModel):
    action: IpAccessChangeAction
    invalidation_operation_id: str
    visibility_gain_count: int
    visibility_loss_count: int
    queued_delivery_recheck_count: int
    panel: IpAccessPanelResponse
