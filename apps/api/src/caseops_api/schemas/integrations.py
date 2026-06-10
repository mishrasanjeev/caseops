from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConnectorStatus = Literal[
    "healthy",
    "degraded",
    "blocked",
    "disabled",
    "configured",
    "missing_config",
    "connected",
    "token_expired",
    "scope_missing",
    "rate_limited",
    "provider_outage",
    "blocked_by_policy",
]


class TenantConnectorRecord(BaseModel):
    key: str
    name: str
    category: str
    provider: str
    status: ConnectorStatus
    enabled: bool
    configured: bool
    blocked: bool
    healthy: bool
    degraded: bool
    last_success: datetime | None = None
    last_failure: datetime | None = None
    next_run: datetime | None = None
    webhook_status: str | None = None
    polling_status: str | None = None
    rate_limit_status: str | None = None
    token_expiry: datetime | None = None
    token_refresh_status: str | None = None
    required_scopes: list[str] = Field(default_factory=list)
    granted_scopes: list[str] = Field(default_factory=list)
    missing_scopes: list[str] = Field(default_factory=list)
    error_category: str | None = None
    disabled_reason: str | None = None
    last_checked_at: datetime | None = None
    operational_alerts: list[str] = Field(default_factory=list)
    setup_actions: list[str] = Field(default_factory=list)
    required_config_names: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    runbook_link: str | None = None
    provider_operations_link: str | None = None


class ConnectorRecord(TenantConnectorRecord):
    internal_cost_label: str | None = None
    risk_label: str | None = None
    platform_notes: list[str] = Field(default_factory=list)


class TenantConnectorRegistryResponse(BaseModel):
    connectors: list[TenantConnectorRecord]


class ConnectorRegistryResponse(BaseModel):
    connectors: list[ConnectorRecord]


class ConnectorHealthRecord(BaseModel):
    id: str
    company_id: str
    provider: str
    configured_state: ConnectorStatus
    connected_state: ConnectorStatus
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    error_category: str | None = None
    required_scopes: list[str] = Field(default_factory=list)
    granted_scopes: list[str] = Field(default_factory=list)
    missing_scopes: list[str] = Field(default_factory=list)
    token_expires_at: datetime | None = None
    token_refresh_status: str | None = None
    webhook_status: str | None = None
    polling_status: str | None = None
    rate_limit_status: str | None = None
    next_retry_at: datetime | None = None
    disabled_reason: str | None = None
    last_checked_at: datetime | None = None
    operational_alerts: list[str] = Field(default_factory=list)
    setup_actions: list[str] = Field(default_factory=list)
    provider_operations_link: str | None = None
    created_at: datetime
    updated_at: datetime


class ConnectorHealthListResponse(BaseModel):
    health: list[ConnectorHealthRecord]


class ConnectorHealthCheckResponse(BaseModel):
    checked_at: datetime
    health: list[ConnectorHealthRecord]
