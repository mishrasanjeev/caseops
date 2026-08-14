"""IPLF-030A trademark portfolio listing contract.

The portfolio is read-only in this slice. A row is one **jurisdiction /
application** record joined to the mark (asset) it belongs to, so one mark with
filings in several offices produces several rows (IP-PORT-05). Grid and
saved-view presentations, column configuration, bulk actions, and export are
IPLF-030B and are deliberately absent here.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IpPortfolioFilters(BaseModel):
    """Server-owned filter scope for one portfolio query (IP-PORT-02)."""

    query: str | None = Field(default=None, max_length=200)
    matter_id: str | None = Field(default=None, max_length=36)
    asset_kind: list[str] = Field(default_factory=list)
    jurisdiction: list[str] = Field(default_factory=list)
    office: list[str] = Field(default_factory=list)
    filing_phase: list[str] = Field(default_factory=list)
    docket_status: list[str] = Field(default_factory=list)
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
    registry_sync_state: str = "unavailable"


class IpPortfolioListResponse(BaseModel):
    rows: list[IpPortfolioRow]
    counts: IpPortfolioCounts
    filters: IpPortfolioFilters
    limit: int
    next_cursor: str | None = None
