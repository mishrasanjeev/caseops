from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MatterTagColorKeyLiteral = Literal["slate", "red", "amber", "green", "blue", "violet"]
MatterTagAssignmentSourceLiteral = Literal["manual", "suggested", "bulk", "import"]


class MatterTagCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=120,
        pattern=r"^[a-z0-9-]+$",
    )
    color_key: MatterTagColorKeyLiteral | None = None


class MatterTagUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    color_key: MatterTagColorKeyLiteral | None = None


class MatterTagRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    name: str
    slug: str
    color_key: str | None
    created_at: datetime


class MatterTagListResponse(BaseModel):
    tags: list[MatterTagRecord]


class MatterTagAssignmentCreateRequest(BaseModel):
    tag_id: str = Field(min_length=1)
    source: MatterTagAssignmentSourceLiteral = "manual"


class MatterTagAssignmentRecord(BaseModel):
    id: str
    matter_id: str
    tag: MatterTagRecord
    source: MatterTagAssignmentSourceLiteral
    created_at: datetime


class MatterBulkTagAssignRequest(BaseModel):
    matter_ids: list[str] = Field(min_length=1, max_length=200)
    tag_id: str = Field(min_length=1)
    source: MatterTagAssignmentSourceLiteral = "bulk"


class MatterBulkTagAssignResponse(BaseModel):
    assigned_count: int
    skipped_count: int
    assignments: list[MatterTagAssignmentRecord]


class MatterTagSuggestionRecord(BaseModel):
    name: str
    slug: str
    source: Literal["client_name", "opposing_party", "known_client"]
    existing_tag_id: str | None = None


class MatterTagSuggestionsResponse(BaseModel):
    matter_id: str
    suggestions: list[MatterTagSuggestionRecord]
