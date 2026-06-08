from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConnectorStatus = Literal["healthy", "degraded", "blocked", "disabled", "configured"]


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
    token_expiry: datetime | None = None
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
