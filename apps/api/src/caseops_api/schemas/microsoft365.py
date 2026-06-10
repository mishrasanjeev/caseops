from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Microsoft365ReadinessStatusLiteral = Literal["passed", "blocked", "not_run"]
Microsoft365ReadinessLiteral = Literal[
    "blocked_pending_admin_configuration",
    "ready_for_review_first_workflows",
]


class Microsoft365ConfigurationItemStatus(BaseModel):
    name: str
    configured: bool


class Microsoft365ApprovalItemStatus(BaseModel):
    key: str
    label: str
    approved: bool


class Microsoft365TenantConfigurationResponse(BaseModel):
    provider: Literal["microsoft_365"] = "microsoft_365"
    configured: bool
    enabled: bool
    required_config: list[Microsoft365ConfigurationItemStatus]
    required_approvals: list[Microsoft365ApprovalItemStatus]
    approved_scopes: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    missing_approval_keys: list[str] = Field(default_factory=list)
    mail_enabled: bool
    calendar_enabled: bool
    drive_enabled: bool
    connection_count: int = Field(ge=0)
    connected_account_count: int = Field(ge=0)
    last_test_status: Microsoft365ReadinessStatusLiteral = "not_run"
    last_tested_at: datetime | None = None
    last_error_redacted: str | None = None
    readiness: Microsoft365ReadinessLiteral


class Microsoft365TenantConfigurationUpdateRequest(BaseModel):
    client_id: str | None = Field(default=None, max_length=255)
    client_secret: str | None = Field(default=None, max_length=4096)
    tenant_id: str | None = Field(default=None, max_length=255)
    redirect_uri: str | None = Field(default=None, max_length=500)
    scopes: list[str] | None = None
    admin_consent_approved: bool = False
    scopes_approved: bool = False
    mail_enabled: bool = True
    calendar_enabled: bool = True
    drive_enabled: bool = True
    enabled: bool = True

    @field_validator("client_id", "client_secret", "tenant_id", "redirect_uri", mode="before")
    @classmethod
    def blank_string_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class Microsoft365ReadinessCheckResult(BaseModel):
    key: str
    label: str
    status: Microsoft365ReadinessStatusLiteral
    detail: str | None = None


class Microsoft365ReadinessTestResponse(BaseModel):
    provider: Literal["microsoft_365"] = "microsoft_365"
    status: Microsoft365ReadinessStatusLiteral
    checks: list[Microsoft365ReadinessCheckResult]
    readiness: Microsoft365ReadinessLiteral
    tested_at: datetime
