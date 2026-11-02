"""Read contract for the WIPO Nice class catalogue."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NiceClassRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1, le=45)
    kind: Literal["goods", "services"]
    heading: str = Field(min_length=1)
    note: str | None = None


class NiceClassCatalogueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edition: str
    in_force_from: date
    source_url: str
    source_data_url: str
    retrieved_on: date
    headings_sha256: str = Field(min_length=64, max_length=64)
    attribution: str
    classes: list[NiceClassRecord] = Field(min_length=45, max_length=45)
