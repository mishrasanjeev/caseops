from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from caseops_api.schemas.calendar import OUTLOOK_OAUTH_CALLBACK_PATH
from caseops_api.schemas.oauth_redirect import oauth_redirect_error

# The only Microsoft OAuth callback CaseOps serves: the Outlook Calendar
# sign-in. No sign-in reads the Microsoft 365 configuration yet; pinning its
# Redirect URI here keeps one Entra app registration valid for both pages.
MICROSOFT365_OAUTH_CALLBACK_PATH = OUTLOOK_OAUTH_CALLBACK_PATH

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DOMAIN = re.compile(
    r"^(?=.{4,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)
_MULTI_TENANT_MODES = {"common", "organizations", "consumers"}


def microsoft365_tenant_id_error(value: str) -> str | None:
    """Directory (tenant) ID: the firm's own Entra directory, as a GUID or domain."""

    if value.casefold() in _MULTI_TENANT_MODES:
        return (
            f"'{value}' is a sign-in mode, not your directory. Enter the Directory "
            "(tenant) ID from the Overview page of your app registration in the "
            "Microsoft Entra admin center, or a verified domain such as "
            "yourfirm.onmicrosoft.com."
        )
    if _GUID.match(value) or _DOMAIN.match(value):
        return None
    return (
        "The Directory (tenant) ID must be a GUID such as "
        "72f988bf-86f1-41af-91ab-2d7cd011db47, or a verified domain such as "
        "yourfirm.onmicrosoft.com. Copy it from the Overview page of your app "
        "registration in the Microsoft Entra admin center."
    )


def microsoft365_client_id_error(value: str) -> str | None:
    if _GUID.match(value):
        return None
    return (
        "The Application (client) ID must be a GUID such as "
        "00000000-1111-2222-3333-444444444444. Copy it from the Overview page of "
        "your app registration in the Microsoft Entra admin center."
    )

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


class Microsoft365GraphPermission(BaseModel):
    scope: str
    kind: Literal["delegated"] = "delegated"
    purpose: str


class Microsoft365TenantConfigurationResponse(BaseModel):
    """The workspace's saved Microsoft 365 app-registration values and approvals.

    Saving or testing them calls no Microsoft service and connects no account.
    Today only connector health reads them (Microsoft 365 readiness); Outlook
    Calendar is connected through the Outlook configuration and its sign-in,
    and Outlook Mail and OneDrive/SharePoint have no sign-in yet.
    """

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
    # Setup guidance, all computed on the server. The redirect URI is the exact
    # address the Outlook Calendar sign-in on this deployment sends and serves.
    registration_model: Literal["customer_entra_app_registration"] = (
        "customer_entra_app_registration"
    )
    expected_redirect_uri: str
    callback_path: str = MICROSOFT365_OAUTH_CALLBACK_PATH
    saved_redirect_uri: str | None = None
    redirect_uri_matches_expected: bool = False
    client_id: str | None = None
    tenant_id: str | None = None
    secret_saved: bool = False
    required_permissions: list[Microsoft365GraphPermission] = Field(default_factory=list)


def microsoft365_oauth_redirect_error(value: str) -> str | None:
    # No Microsoft 365 sign-in exists; the one Microsoft callback CaseOps
    # serves is Outlook Calendar's, so a registration recorded here must list
    # it to be reusable on the Outlook calendar page.
    return oauth_redirect_error(
        value,
        label="Microsoft 365",
        provider="Microsoft",
        expected_path=MICROSOFT365_OAUTH_CALLBACK_PATH,
    )


def microsoft365_oauth_redirect_is_valid(value: str | None) -> bool:
    return bool(value) and microsoft365_oauth_redirect_error(str(value)) is None


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

    @field_validator("redirect_uri")
    @classmethod
    def usable_microsoft365_redirect(cls, value: str | None) -> str | None:
        if value is None:
            return None
        problem = microsoft365_oauth_redirect_error(value)
        if problem:
            raise ValueError(problem)
        return value

    @field_validator("tenant_id")
    @classmethod
    def usable_microsoft365_tenant(cls, value: str | None) -> str | None:
        if value is None:
            return None
        problem = microsoft365_tenant_id_error(value)
        if problem:
            raise ValueError(problem)
        return value

    @field_validator("client_id")
    @classmethod
    def usable_microsoft365_client(cls, value: str | None) -> str | None:
        if value is None:
            return None
        problem = microsoft365_client_id_error(value)
        if problem:
            raise ValueError(problem)
        return value


class Microsoft365ReadinessCheckResult(BaseModel):
    key: str
    label: str
    status: Microsoft365ReadinessStatusLiteral
    detail: str | None = None


class Microsoft365ReadinessTestResponse(BaseModel):
    """Whether every Microsoft 365 value and approval is saved and well formed.

    Checked in CaseOps only: no Microsoft call is made, so a wrong secret or
    consent not granted in Microsoft Entra is not detected, and no account is
    connected.
    """

    provider: Literal["microsoft_365"] = "microsoft_365"
    status: Microsoft365ReadinessStatusLiteral
    checks: list[Microsoft365ReadinessCheckResult]
    readiness: Microsoft365ReadinessLiteral
    tested_at: datetime
