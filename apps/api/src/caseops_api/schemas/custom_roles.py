from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from caseops_api.schemas.companies import AssignableRoleLiteral


class CapabilityRecord(BaseModel):
    capability: str
    group: str
    label: str
    owner_only: bool = False
    # True when this capability can be granted via a custom role.
    # False covers both owner-only and the non-delegable administrative
    # capabilities (workspace:admin, email_templates:manage, etc.) that the
    # backend will reject in `validate_custom_role_permissions`. The UI
    # uses this to disable selection before submit. Defaults to True so
    # older clients reading the field don't accidentally lock the matrix.
    custom_role_delegable: bool = True
    # Human-readable explanation for why a capability is undelegable.
    # `None` when the capability can be assigned via a custom role.
    protected_reason: str | None = None


class CapabilityCatalogResponse(BaseModel):
    capabilities: list[CapabilityRecord]


class CustomRoleRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    name: str
    slug: str
    description: str | None
    base_role: AssignableRoleLiteral | None
    permissions: list[str]
    is_system: bool
    is_active: bool
    assigned_count: int = 0
    created_by_membership_id: str | None
    updated_by_membership_id: str | None
    created_at: datetime
    updated_at: datetime


class CustomRoleListResponse(BaseModel):
    roles: list[CustomRoleRecord]


class CustomRoleCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    base_role: AssignableRoleLiteral | None = None
    permissions: list[str] = Field(min_length=1, max_length=80)

    @field_validator("name", "description", mode="before")
    @classmethod
    def _clean_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None


class CustomRoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    base_role: AssignableRoleLiteral | None = None
    permissions: list[str] | None = Field(default=None, min_length=1, max_length=80)
    is_active: bool | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def _clean_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None


class EmployeeCustomRoleAssignRequest(BaseModel):
    custom_role_id: str | None = Field(default=None, min_length=1)
