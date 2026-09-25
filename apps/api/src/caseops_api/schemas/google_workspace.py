from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationInfo, field_validator

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
_LOCAL_OAUTH_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


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
        expected_path = GOOGLE_OAUTH_CALLBACK_PATHS[str(info.field_name)]
        connector = str(info.field_name).removesuffix("_redirect_uri")
        parts = urlsplit(value)
        host = parts.hostname or ""
        advice = (
            f"The {connector} redirect URI must be the address Google sends the user back to, "
            f"ending in {expected_path}"
        )
        if parts.scheme not in {"http", "https"} or not host:
            raise ValueError(f"{advice}. Enter a full https address including the host.")
        if parts.scheme != "https" and host not in _LOCAL_OAUTH_HOSTS:
            raise ValueError(f"{advice}. Google accepts https only, except on localhost.")
        if parts.username or parts.password:
            raise ValueError(f"{advice}. Remove the username or password from the address.")
        if parts.query or parts.fragment:
            raise ValueError(f"{advice}. Remove the query string or fragment.")
        if parts.path != expected_path:
            raise ValueError(
                f"{advice}. It currently ends in {parts.path or '/'}, which Google will reject "
                "as a redirect_uri mismatch. Check for a trailing slash, a typo, or another "
                "connector's address pasted into this field."
            )
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
