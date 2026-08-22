"""Synchronous IP report definitions for the IPLF-038 foundation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from caseops_api.schemas.ip_portfolio import IpPortfolioFilters
from caseops_api.schemas.ip_renewals import RenewalState

IpReportKind = Literal[
    "portfolio_register",
    "deadline_control",
    "renewal",
    "data_quality",
]
IpReportFreshnessStatus = Literal["current", "mixed", "unavailable"]


class IpReportPortfolioFilters(IpPortfolioFilters):
    """Report filters reject misspellings instead of silently widening scope."""

    model_config = ConfigDict(extra="forbid")


class IpReportDefinitionRecord(BaseModel):
    key: IpReportKind
    schema_version: str
    canonical_sources: list[str]
    synchronous_preview: bool = True
    background_execution: bool = False
    scheduled_delivery: bool = False


class IpReportFoundationContract(BaseModel):
    contract_version: Literal["iplf-038a-v1"] = "iplf-038a-v1"
    persistence: Literal["none"] = "none"
    execution_mode: Literal["synchronous"] = "synchronous"
    artifact_storage: Literal["none"] = "none"
    delivery: Literal["not_available"] = "not_available"
    audience: Literal["internal"] = "internal"
    hidden_restricted_count_policy: Literal["omit_without_count"] = "omit_without_count"
    definitions: list[IpReportDefinitionRecord]


class IpReportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_kind: IpReportKind
    filters: IpReportPortfolioFilters = Field(default_factory=IpReportPortfolioFilters)
    renewal_states: list[RenewalState] = Field(default_factory=list, max_length=10)
    row_limit: int = Field(default=200, ge=1, le=200)
    audience: Literal["internal"] = "internal"
    confidentiality: Literal["internal", "restricted"] = "internal"


class IpReportFreshness(BaseModel):
    status: IpReportFreshnessStatus
    generated_at: datetime
    source_cutoffs: dict[str, datetime | None]
    unavailable_sources: list[str] = Field(default_factory=list)


class IpReportPreviewResponse(BaseModel):
    report_kind: IpReportKind
    schema_version: str
    generated_at: datetime
    timezone: Literal["UTC"] = "UTC"
    audience: Literal["internal"] = "internal"
    confidentiality: Literal["internal", "restricted"]
    filters: dict[str, Any]
    freshness: IpReportFreshness
    hidden_restricted_count_policy: Literal["omit_without_count"] = "omit_without_count"
    row_count: int
    truncated: bool
    summary: dict[str, Any]
    rows: list[dict[str, Any]]
    snapshot_sha256: str = Field(min_length=64, max_length=64)


__all__ = [name for name in globals() if name.startswith("IpReport")]
