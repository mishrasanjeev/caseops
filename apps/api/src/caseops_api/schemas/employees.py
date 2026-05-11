from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from caseops_api.schemas.companies import AssignableRoleLiteral, MembershipRoleLiteral

EmploymentStatusLiteral = Literal["invited", "active", "inactive", "offboarding"]
EmployeeImportJobStatusLiteral = Literal[
    "previewed",
    "committing",
    "committed",
    "cancelled",
    "failed",
]
EmployeeImportRowStatusLiteral = Literal["valid", "invalid", "created", "failed"]


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class EmployeeRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: str
    membership_id: str
    user_id: str
    email: EmailStr
    full_name: str
    role: MembershipRoleLiteral
    custom_role_id: str | None = None
    custom_role_name: str | None = None
    membership_active: bool
    user_active: bool
    mobile: str | None
    designation: str | None
    department: str | None
    employee_code: str | None
    manager_membership_id: str | None
    manager_name: str | None = None
    joined_on: date | None
    employment_status: EmploymentStatusLiteral
    last_login_at: datetime | None
    setup_sent_at: datetime | None
    setup_completed_at: datetime | None
    password_reset_sent_at: datetime | None
    force_password_change: bool
    created_at: datetime
    updated_at: datetime


class EmployeeTokenDelivery(BaseModel):
    delivered: bool
    delivery_error: str | None = None
    expires_at: datetime
    debug_token: str | None = None


class EmployeeCreateResponse(BaseModel):
    employee: EmployeeRecord
    setup: EmployeeTokenDelivery


class EmployeeListResponse(BaseModel):
    employees: list[EmployeeRecord]


class EmployeeOffboardingRequest(BaseModel):
    reassign_to_membership_id: str | None = Field(default=None, min_length=1)
    deactivate: bool = True
    revoke_sessions: bool = True
    notify: bool = False
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("reassign_to_membership_id", "notes", mode="before")
    @classmethod
    def _clean_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        return _blank_to_none(value)


class EmployeeOffboardingObject(BaseModel):
    object_type: str
    id: str
    label: str
    relation: str
    supported: bool
    matter_id: str | None = None


class EmployeeOffboardingPreviewResponse(BaseModel):
    employee: EmployeeRecord
    reassign_to: EmployeeRecord | None = None
    supported_objects: list[EmployeeOffboardingObject]
    unsupported_objects: list[EmployeeOffboardingObject]
    supported_counts: dict[str, int]
    unsupported_counts: dict[str, int]
    blockers: list[str]
    can_commit: bool


class EmployeeOffboardingCommitResponse(BaseModel):
    employee: EmployeeRecord
    reassigned_to: EmployeeRecord
    preview: EmployeeOffboardingPreviewResponse
    deactivated: bool
    sessions_revoked: bool


class EmployeeAuditEventRecord(BaseModel):
    id: str
    action: str
    actor_membership_id: str | None = None
    actor_label: str | None = None
    target_type: str
    target_id: str | None = None
    result: str
    metadata: dict[str, object]
    created_at: datetime


class EmployeeAuditResponse(BaseModel):
    employee: EmployeeRecord
    events: list[EmployeeAuditEventRecord]


class EmployeeImportRowPreview(BaseModel):
    id: str
    row_number: int
    raw: dict[str, object]
    normalized: dict[str, object]
    errors: list[str]
    status: EmployeeImportRowStatusLiteral
    created_membership_id: str | None = None


class EmployeeImportJobResponse(BaseModel):
    id: str
    company_id: str
    filename: str
    content_type: str | None
    status: EmployeeImportJobStatusLiteral
    total_rows: int
    valid_rows: int
    invalid_rows: int
    created_count: int
    failed_count: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    committed_at: datetime | None = None
    cancelled_at: datetime | None = None
    rows: list[EmployeeImportRowPreview] = []


class EmployeeImportCommitResponse(BaseModel):
    job: EmployeeImportJobResponse
    created_employees: list[EmployeeCreateResponse]


class EmployeeCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    role: AssignableRoleLiteral = "member"
    mobile: str | None = Field(default=None, max_length=40)
    designation: str | None = Field(default=None, max_length=160)
    department: str | None = Field(default=None, max_length=160)
    employee_code: str | None = Field(default=None, max_length=80)
    manager_membership_id: str | None = Field(default=None, min_length=1)
    joined_on: date | None = None

    @field_validator(
        "full_name",
        "mobile",
        "designation",
        "department",
        "employee_code",
        "manager_membership_id",
        mode="before",
    )
    @classmethod
    def _clean_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None


class EmployeeUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: AssignableRoleLiteral | None = None
    mobile: str | None = Field(default=None, max_length=40)
    designation: str | None = Field(default=None, max_length=160)
    department: str | None = Field(default=None, max_length=160)
    employee_code: str | None = Field(default=None, max_length=80)
    manager_membership_id: str | None = Field(default=None, min_length=1)
    joined_on: date | None = None
    employment_status: EmploymentStatusLiteral | None = None

    @field_validator(
        "full_name",
        "mobile",
        "designation",
        "department",
        "employee_code",
        "manager_membership_id",
        mode="before",
    )
    @classmethod
    def _clean_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        return _blank_to_none(value)


class EmployeeDirectoryFilters(BaseModel):
    q: str | None = None
    role: MembershipRoleLiteral | None = None
    status: EmploymentStatusLiteral | None = None
    department: str | None = None


class AccountSetupCompleteRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)
    password: str = Field(min_length=12, max_length=128)


class PasswordResetStartRequest(BaseModel):
    company_slug: str = Field(min_length=2, max_length=80)
    email: EmailStr


class PasswordResetStartResponse(BaseModel):
    delivered: bool = True
    debug_token: str | None = None


# BUG-048 (Hari 2026-05-11): admin UI for matter-level access control.
# Backend grants exist (MatterAccessGrant) but the Admin > Employees
# page never surfaced them. These records power the Edit Employee
# dialog's "Matter access" section.
class EmployeeMatterAccessRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    matter_id: str
    matter_code: str
    matter_title: str
    restricted_access: bool
    has_grant: bool
    grant_id: str | None = None
    is_assignee: bool
    is_walled: bool


class EmployeeMatterAccessResponse(BaseModel):
    membership_id: str
    matters: list[EmployeeMatterAccessRow]
