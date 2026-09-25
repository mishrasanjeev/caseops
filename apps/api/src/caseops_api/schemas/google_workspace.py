from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from caseops_api.schemas.oauth_redirect import oauth_redirect_error

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


# Google matches a redirect URI as an exact string: scheme, host, path, case and
# trailing slash all count. The three values below are the only callback paths
# CaseOps serves, so an admin who mistypes one, adds a trailing slash, or pastes
# the Drive URI into the Gmail field must fail here rather than after a user has
# already granted consent. ``tests/test_20260925_google_oauth_redirect_validation``
# pins them to the mounted routes. The host stays free: each deployment and each
# self-hosted tenant registers its own origin.
GOOGLE_OAUTH_CALLBACK_PATHS: dict[str, str] = {
    "calendar_redirect_uri": "/api/calendar/connections/google-calendar/callback",
    "gmail_redirect_uri": "/api/mailbox/gmail/callback",
    "drive_redirect_uri": "/api/drive/google/callback",
}
def google_oauth_redirect_error(field: str, value: str) -> str | None:
    """Return an actionable message when a redirect URI is not one Google can call.

    Shared by the admin form and the read path so a row written before this rule
    existed cannot present itself as configured.
    """

    return oauth_redirect_error(
        value,
        label=field.removesuffix("_redirect_uri"),
        provider="Google",
        expected_path=GOOGLE_OAUTH_CALLBACK_PATHS[field],
    )


def google_oauth_redirect_is_valid(field: str, value: str | None) -> bool:
    return bool(value) and google_oauth_redirect_error(field, str(value)) is None



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

    @field_validator(
        "calendar_redirect_uri",
        "gmail_redirect_uri",
        "drive_redirect_uri",
    )
    @classmethod
    def exact_connector_callback(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        problem = google_oauth_redirect_error(str(info.field_name), value)
        if problem:
            raise ValueError(problem)
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
