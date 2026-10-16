"""Source-date tracker contracts; these dates do not acquire legal authority."""

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DateState = Literal["missing", "manual", "imported_unverified", "verified"]
TrackerCategory = Literal["upcoming", "active", "due_today", "overdue", "missing", "failed"]
TrackerStatus = Literal[
    "scheduled", "active", "sent", "failed", "missing_date", "overdue", "cancelled"
]


class IpPortfolioDatesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=5, max_length=500)
    application_date: date | None = None
    renewal_due_date: date | None = None

    @field_validator("application_date", "renewal_due_date", mode="before")
    @classmethod
    def iso_date_only(cls, value):
        if value is None or type(value) is date:
            return value
        if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
            raise ValueError("Use an ISO calendar date (YYYY-MM-DD), or null to clear it.")
        return date.fromisoformat(value)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("A correction reason is required.")
        return value

    @model_validator(mode="after")
    def require_date_key(self) -> Self:
        if not self.model_fields_set & {"application_date", "renewal_due_date"}:
            raise ValueError(
                "Supply application_date or renewal_due_date; null explicitly clears it."
            )
        return self


class IpPortfolioDatesRecord(BaseModel):
    docket_id: str
    current_version: int
    source_application_on: date | None = None
    source_renewal_due_on: date | None = None
    source_application_state: DateState = "missing"
    source_renewal_state: DateState = "missing"


class IpRenewalTrackerRow(IpPortfolioDatesRecord):
    docket_title: str
    docket_operational: bool
    application_numbers: list[str] = Field(default_factory=list)
    nice_classes: list[int] = Field(default_factory=list)
    reminder_start_on: date | None = None
    next_reminder_at: datetime | None = None
    timezone: str
    cadence_days: int
    delivery_time: str
    days_remaining: int | None = None
    status: TrackerStatus
    last_attempt_at: datetime | None = None
    delivered_at: datetime | None = None
    last_error: str | None = None


class IpPortfolioDatesResponse(IpPortfolioDatesRecord):
    tracker: IpRenewalTrackerRow


class IpRenewalTrackerResponse(BaseModel):
    rows: list[IpRenewalTrackerRow]
    counts: dict[TrackerCategory, int]
    limit: int
    next_cursor: str | None = None
