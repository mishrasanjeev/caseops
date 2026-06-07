from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CauseListSourceLiteral = Literal["hearings", "cause_list_entries", "both"]
CauseListSortLiteral = Literal["hearing_date", "court", "lawyer", "serial"]


class CauseListPreviewRequest(BaseModel):
    date: date_type | None = None
    date_from: date_type | None = None
    date_to: date_type | None = None
    court: str | None = Field(default=None, max_length=255)
    lawyer_membership_id: str | None = Field(default=None, max_length=36)
    practice_area: str | None = Field(default=None, max_length=120)
    matter_status: str | None = Field(default=None, max_length=24)
    include_disposed: bool = False
    source: CauseListSourceLiteral = "both"
    sort: CauseListSortLiteral = "hearing_date"

    @model_validator(mode="after")
    def normalize_dates(self) -> CauseListPreviewRequest:
        if self.date is not None:
            self.date_from = self.date
            self.date_to = self.date
        if self.date_from is None or self.date_to is None:
            raise ValueError("Provide date or date_from/date_to.")
        if self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to.")
        return self


class CauseListRow(BaseModel):
    serial_number: int
    file_number: str
    court_name: str
    case_number: str
    case_title: str
    judge_name: str
    court_number: str
    item_number: str
    lawyers_appearing: str
    hearing_date: date_type
    source: str
    source_ref: str | None = None
    missing_field_warnings: list[str] = Field(default_factory=list)


class CauseListPreviewResponse(BaseModel):
    generated_at: datetime
    filters: dict[str, object]
    rows: list[CauseListRow]


class CauseListDownloadResponse(BaseModel):
    file_name: str
    checksum: str
    row_count: int
