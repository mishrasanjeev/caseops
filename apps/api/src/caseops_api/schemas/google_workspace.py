from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

GoogleWorkspaceProviderLiteral = Literal["google_workspace"]
GoogleWorkspaceConfigurationSourceLiteral = Literal[
    "tenant_admin",
    "environment",
    "missing",
]
GoogleWorkspaceReadinessItemStatusLiteral = Literal[
    "passed",
    "failed",
    "blocked",
    "not_run",
]
GoogleWorkspaceReadinessLiteral = Literal[
    "blocked_pending_admin_configuration",
    "ready_for_user_connections",
]


class GoogleWorkspaceConfigurationItemStatus(BaseModel):
    name: str
    configured: bool


class GoogleWorkspaceApprovalItemStatus(BaseModel):
    key: str
    label: str
    approved: bool


class GoogleWorkspaceMachineReadinessControlStatus(BaseModel):
    key: str
    label: str
    version: str
    status: GoogleWorkspaceReadinessItemStatusLiteral
    detail: str | None = None


class GoogleWorkspaceConnectionCounts(BaseModel):
    calendar_connection_count: int = Field(ge=0)
    gmail_connection_count: int = Field(ge=0)
    drive_connection_count: int = Field(ge=0)
    connected_calendar_account_count: int = Field(ge=0)
    connected_gmail_account_count: int = Field(ge=0)
    connected_drive_account_count: int = Field(ge=0)


class GoogleWorkspaceTenantConfigurationResponse(BaseModel):
    provider: GoogleWorkspaceProviderLiteral = "google_workspace"
    configured: bool
    config_source: GoogleWorkspaceConfigurationSourceLiteral
    enabled: bool
    calendar_enabled: bool
    gmail_enabled: bool
    drive_enabled: bool
    required_config: list[GoogleWorkspaceConfigurationItemStatus]
    required_approvals: list[GoogleWorkspaceApprovalItemStatus]
    machine_control_version: str
    machine_controls: list[GoogleWorkspaceMachineReadinessControlStatus]
    approved_scopes: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    missing_approval_keys: list[str] = Field(default_factory=list)
    missing_machine_control_keys: list[str] = Field(default_factory=list)
    connection_counts: GoogleWorkspaceConnectionCounts
    last_test_status: GoogleWorkspaceReadinessItemStatusLiteral = "not_run"
    last_tested_at: datetime | None = None
    last_error_redacted: str | None = None
    readiness: GoogleWorkspaceReadinessLiteral


class GoogleWorkspaceTenantConfigurationUpdateRequest(BaseModel):
    client_id: str | None = Field(default=None, max_length=255)
    client_secret: str | None = Field(default=None, max_length=4096)
    calendar_redirect_uri: str | None = Field(default=None, max_length=500)
    gmail_redirect_uri: str | None = Field(default=None, max_length=500)
    drive_redirect_uri: str | None = Field(default=None, max_length=500)
    scopes: list[str] | None = None
    oauth_consent_model_approved: bool = False
    scopes_approved: bool = False
    calendar_enabled: bool = True
    gmail_enabled: bool = True
    drive_enabled: bool = True
    enabled: bool = True

    @field_validator(
        "client_id",
        "client_secret",
        "calendar_redirect_uri",
        "gmail_redirect_uri",
        "drive_redirect_uri",
        mode="before",
    )
    @classmethod
    def blank_string_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class GoogleWorkspaceReadinessCheckResult(BaseModel):
    key: str
    label: str
    status: GoogleWorkspaceReadinessItemStatusLiteral
    detail: str | None = None


class GoogleWorkspaceReadinessTestResponse(BaseModel):
    provider: GoogleWorkspaceProviderLiteral = "google_workspace"
    status: GoogleWorkspaceReadinessItemStatusLiteral
    checks: list[GoogleWorkspaceReadinessCheckResult]
    machine_control_version: str
    readiness: GoogleWorkspaceReadinessLiteral
    tested_at: datetime
