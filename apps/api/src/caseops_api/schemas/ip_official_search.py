"""Assisted IP India official search: upload, review and link contracts (IPLF-052D)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IpOfficialSearchSourceKind = Literal[
    "ipindia_estatus", "ipindia_eregister", "ipindia_public_search"
]


class IpOfficialSearchUploadMetadata(BaseModel):
    """What the lawyer searched for on IP India; sent beside the saved page."""

    model_config = ConfigDict(extra="forbid")

    source_kind: IpOfficialSearchSourceKind
    application_number: str | None = Field(default=None, max_length=20)
    word_mark: str | None = Field(default=None, max_length=200)
    nice_class: int | None = Field(default=None, ge=1, le=45)

    @model_validator(mode="after")
    def validate_query(self) -> IpOfficialSearchUploadMetadata:
        if self.application_number is not None:
            self.application_number = re.sub(r"\s+", "", self.application_number)
            if not re.fullmatch(r"\d{1,8}", self.application_number):
                raise ValueError("An IP India application number is digits only.")
        if self.word_mark is not None:
            self.word_mark = " ".join(self.word_mark.split()) or None
        if self.source_kind == "ipindia_public_search":
            if not self.word_mark or self.nice_class is None:
                raise ValueError("A public search needs the word mark and its class.")
            if self.application_number is not None:
                raise ValueError("A public search is by word mark and class, not number.")
        else:
            if not self.application_number:
                raise ValueError("A status or register search needs the application number.")
            if self.word_mark is not None or self.nice_class is not None:
                raise ValueError("A status or register search is by application number only.")
        return self

    def search_query(self) -> dict[str, Any]:
        return self.model_dump(exclude={"source_kind"}, exclude_none=True)


class IpOfficialSearchReviewItem(BaseModel):
    field: str
    reason: str


class IpOfficialSearchMatch(BaseModel):
    docket_id: str
    docket_title: str
    application_id: str
    application_number: str


class IpOfficialSearchImportRecord(BaseModel):
    id: str
    source_kind: IpOfficialSearchSourceKind
    official_url: str
    search_query: dict[str, Any]
    original_filename: str
    content_kind: Literal["html", "pdf"]
    byte_size: int
    file_sha256: str
    parser_version: str
    parse_status: Literal["parsed", "needs_review", "unreadable"]
    fields: dict[str, Any]
    published_values: dict[str, str]
    review_items: list[IpOfficialSearchReviewItem]
    attribution: str
    resolution_status: Literal["pending", "linked", "staged_new_record", "dismissed"]
    resolution_reason: str | None
    linked_docket_id: str | None
    linked_application_id: str | None
    registry_snapshot_id: str | None
    import_job_id: str | None
    uploaded_by_membership_id: str
    uploaded_by_label: str | None
    uploaded_at: datetime
    resolved_at: datetime | None
    version: int
    matches: list[IpOfficialSearchMatch] = Field(default_factory=list)


class IpOfficialSearchUploadResponse(BaseModel):
    record: IpOfficialSearchImportRecord
    duplicate_upload: bool = False


class IpOfficialSearchImportPage(BaseModel):
    records: list[IpOfficialSearchImportRecord]
    total: int
    limit: int
    offset: int


class IpOfficialSearchLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    application_id: str = Field(min_length=1, max_length=36)


class IpOfficialSearchLinkResponse(BaseModel):
    record: IpOfficialSearchImportRecord
    registry_link_id: str
    diff_count: int
    no_change: bool


class IpOfficialSearchStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=255)


class IpOfficialSearchDismissRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
