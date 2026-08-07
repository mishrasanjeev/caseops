from __future__ import annotations

from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator

DeadlineKind = Literal[
    "legal_deadline",
    "internal_target",
    "task_date",
    "hearing",
    "renewal",
    "client_instruction",
    "reminder",
]
CalendarMethod = Literal[
    "calendar_days",
    "business_days",
    "month_anniversary",
    "year_anniversary",
]


class LegalCalendarSnapshot(BaseModel):
    calendar_version_id: str
    timezone: str
    weekend_days: list[int] = Field(default_factory=lambda: [5, 6])
    holidays: list[date] = Field(default_factory=list)
    exceptional_working_days: list[date] = Field(default_factory=list)
    source_reference: str = Field(min_length=1, max_length=512)
    source_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_calendar(self) -> LegalCalendarSnapshot:
        if any(day < 0 or day > 6 for day in self.weekend_days):
            raise ValueError("weekend days must be integers from 0 through 6")
        if len(self.weekend_days) != len(set(self.weekend_days)):
            raise ValueError("weekend days cannot contain duplicates")
        if set(self.holidays) & set(self.exceptional_working_days):
            raise ValueError("a date cannot be both a holiday and an exceptional working day")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return self


class IpDeadlineCalculationRequest(BaseModel):
    deadline_kind: DeadlineKind
    trigger_kind: str = Field(min_length=1, max_length=80)
    base_date: date | None
    base_date_certainty: Literal["certain", "uncertain", "conflicting", "unknown"]
    duration_value: int = Field(ge=0, le=10000)
    duration_unit: Literal["days", "months", "years"]
    calendar_method: CalendarMethod
    direction: Literal["after", "before"] = "after"
    include_base_date: bool = False
    next_working_day: bool = True
    extension_days: int = Field(default=0, ge=0, le=3650)
    rule_version_id: str
    rule_citation: str = Field(min_length=1, max_length=512)
    source_version: str = Field(min_length=1, max_length=120)
    engine_version: str = Field(min_length=1, max_length=80)
    calendar: LegalCalendarSnapshot

    @model_validator(mode="after")
    def validate_method_unit(self) -> IpDeadlineCalculationRequest:
        expected_unit = {
            "calendar_days": "days",
            "business_days": "days",
            "month_anniversary": "months",
            "year_anniversary": "years",
        }[self.calendar_method]
        if self.duration_unit != expected_unit:
            raise ValueError(f"{self.calendar_method} calculations require {expected_unit}")
        return self


class IpDeadlineCalculationResult(BaseModel):
    state: Literal["provisional", "candidate"]
    result_on: date | None
    certainty: Literal["certain", "uncertain", "conflicting", "unknown"]
    explanation: str
    inputs: dict
    trace: list[dict]


class ResponsibilityEvidence(BaseModel):
    membership_id: str
    role: Literal["primary", "backup", "supervisor", "docketing"]
    accepted: bool
    active: bool = True
