"""IPLF-030A trademark portfolio listing contract.

The portfolio is read-only in this slice. A row is one **jurisdiction /
application** record joined to the mark (asset) it belongs to, so one mark with
filings in several offices produces several rows (IP-PORT-05). Grid and
saved-view presentations, column configuration, bulk actions, and export are
IPLF-030B and are deliberately absent here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class IpPortfolioFilters(BaseModel):
    """Server-owned filter scope for one portfolio query (IP-PORT-02)."""

    query: str | None = Field(default=None, max_length=200)
    matter_id: str | None = Field(default=None, max_length=36)
    client: list[str] = Field(default_factory=list)
    proprietor: list[str] = Field(default_factory=list)
    nice_class: list[Annotated[int, Field(ge=1, le=45)]] = Field(default_factory=list)
    responsible_membership_id: list[str] = Field(default_factory=list)
    team_id: list[str] = Field(default_factory=list)
    asset_kind: list[str] = Field(default_factory=list)
    jurisdiction: list[str] = Field(default_factory=list)
    office: list[str] = Field(default_factory=list)
    filing_phase: list[str] = Field(default_factory=list)
    docket_status: list[str] = Field(default_factory=list)
    deadline_state: list[str] = Field(default_factory=list)
    opposition_only: bool = False
    registry_sync_state: list[Literal["current", "stale", "failed", "unavailable"]] = Field(
        default_factory=list
    )
    include_inactive: bool = False


class IpPortfolioRow(BaseModel):
    """One jurisdiction/application record with its owning mark."""

    application_id: str
    docket_id: str
    matter_id: str | None
    asset_id: str | None
    asset_kind: str | None
    asset_title: str | None
    asset_jurisdiction: str | None
    docket_title: str
    docket_status: str
    primary_identifier: str | None
    application_numbers: list[str] = Field(default_factory=list)
    opposition_numbers: list[str] = Field(default_factory=list)
    nice_classes: list[int] = Field(default_factory=list)
    goods_services: list[str] = Field(default_factory=list)
    representation_kinds: list[str] = Field(default_factory=list)
    proprietors: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    client_name: str | None = None
    responsible_lawyer: str | None = None
    responsible_membership_id: str | None = None
    team_name: str | None = None
    team_id: str | None = None
    office: str | None
    jurisdiction: str | None
    filing_phase: str
    is_active: bool
    lifecycle_version: int
    pending_identifier_allocation: bool
    record_complete: bool
    incomplete_reasons: list[str] = Field(default_factory=list)
    open_deadline_count: int = 0
    unconfirmed_deadline_count: int = 0
    overdue_deadline_count: int = 0
    registry_sync_state: Literal["current", "stale", "failed", "unavailable"] = "unavailable"
    registry_last_success_at: datetime | None = None
    provenance: list[str] = Field(default_factory=list)
    application_created_at: datetime
    updated_at: datetime


class IpPortfolioCounts(BaseModel):
    """Data-quality split for the current filter scope.

    ``registry_sync_state`` is deliberately ``unavailable`` rather than zero:
    IP-office synchronisation is an M5 capability, so a sync-failure count
    cannot be reported truthfully yet.
    """

    total: int
    complete_records: int
    incomplete_records: int
    unconfirmed_deadline_records: int
    overdue_records: int
    stale_sync_records: int = 0
    sync_failure_records: int | None = None
    registry_sync_state: Literal["available", "unavailable"] = "unavailable"


class IpPortfolioListResponse(BaseModel):
    rows: list[IpPortfolioRow]
    counts: IpPortfolioCounts
    filters: IpPortfolioFilters
    limit: int
    next_cursor: str | None = None


class IpPortfolioFamilyMember(BaseModel):
    """One jurisdiction/application inside a family, with its own identity."""

    application_id: str
    docket_id: str
    asset_id: str | None
    office: str | None
    jurisdiction: str | None
    filing_phase: str
    lifecycle_version: int
    primary_identifier: str | None
    open_deadline_count: int = 0
    overdue_deadline_count: int = 0


class IpPortfolioFamily(BaseModel):
    """A grouping of related applications.

    Grouping is presentational only. IP-PROS-11 requires each member to keep
    independent identifiers, events, rules and lifecycle, so a family exposes no
    shared phase, deadline, or identifier of its own.
    """

    grouping: str
    family_key: str
    label: str
    member_count: int
    distinct_jurisdictions: list[str] = Field(default_factory=list)
    distinct_filing_phases: list[str] = Field(default_factory=list)
    members: list[IpPortfolioFamilyMember] = Field(default_factory=list)


class IpPortfolioFamilyResponse(BaseModel):
    grouping: str
    families: list[IpPortfolioFamily] = Field(default_factory=list)
    ungrouped_member_count: int = 0
    limit: int
    next_cursor: str | None = None


class IpPortfolioSavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: IpPortfolioFilters = Field(default_factory=IpPortfolioFilters)
    columns: list[str] = Field(default_factory=list, max_length=24)
    is_default: bool = False
    scope: Literal["personal", "team"] = "personal"
    team_id: str | None = None


class IpPortfolioSavedViewUpdate(IpPortfolioSavedViewCreate):
    expected_version: int = Field(ge=1)


class IpPortfolioSavedViewRecord(BaseModel):
    id: str
    name: str
    filters: IpPortfolioFilters
    columns: list[str]
    is_default: bool
    scope: Literal["personal", "team"]
    team_id: str | None
    editable: bool
    version: int
    created_at: datetime
    updated_at: datetime


class IpPortfolioSavedViewListResponse(BaseModel):
    views: list[IpPortfolioSavedViewRecord] = Field(default_factory=list)


class IpPortfolioExportPreviewRequest(BaseModel):
    format: Literal["csv"] = "csv"
    filters: IpPortfolioFilters = Field(default_factory=IpPortfolioFilters)
    columns: list[str] = Field(default_factory=list, max_length=24)
    row_limit: int = Field(default=10000, ge=1, le=50000)


class IpPortfolioExportCreate(IpPortfolioExportPreviewRequest):
    preview_token: str = Field(min_length=64, max_length=64)


class IpPortfolioExportPreview(BaseModel):
    format: Literal["csv"] = "csv"
    columns: list[str]
    row_limit: int
    row_count: int
    truncated: bool
    omitted_restricted_count: None = None
    preview_token: str


class IpPortfolioExportRecord(BaseModel):
    id: str
    status: Literal["pending", "running", "completed", "failed"]
    format: Literal["csv"]
    columns: list[str]
    row_limit: int
    row_count: int | None
    size_bytes: int | None
    error: str | None
    download_ready: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class IpPortfolioExportListResponse(BaseModel):
    jobs: list[IpPortfolioExportRecord] = Field(default_factory=list)
