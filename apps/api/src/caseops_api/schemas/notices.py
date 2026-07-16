from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NoticeDirection = Literal["received", "sent"]
NoticeSourceKind = Literal["standalone", "legacy_attachment"]
_MAX_BIGINT = 9_223_372_036_854_775_807

_OPTIONAL_TEXT_FIELDS = (
    "type",
    "authority",
    "received_from",
    "department",
    "mode",
    "summary",
    "remarks",
    "response",
    "internal_spoc",
    "internal_remarks",
    "counsel_engaged",
)


def _clean_optional_text(value: object) -> object:
    if not isinstance(value, str):
        return value
    cleaned = value.strip()
    return cleaned or None


def _clean_matter_ids(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_id in value:
        matter_id = raw_id.strip()
        if not matter_id:
            raise ValueError("matter_ids cannot contain blank identifiers")
        if matter_id not in seen:
            seen.add(matter_id)
            cleaned.append(matter_id)
    return cleaned


class NoticeMatterLinkSummary(BaseModel):
    matter_id: str
    matter_code: str
    matter_title: str


class NoticeOwnerOption(BaseModel):
    membership_id: str
    name: str
    email: str


class NoticeRecord(BaseModel):
    id: str
    source_kind: NoticeSourceKind
    read_only: bool
    direction: NoticeDirection
    subject: str
    type: str | None = None
    status: str
    authority: str | None = None
    received_from: str | None = None
    department: str | None = None
    mode: str | None = None
    owner_membership_id: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    received_on: date | None = None
    sent_on: date | None = None
    reply_due_on: date | None = None
    reply_required: bool
    reply_sent: bool
    reply_sent_on: date | None = None
    summary: str | None = None
    remarks: str | None = None
    response: str | None = None
    internal_spoc: str | None = None
    internal_remarks: str | None = None
    counsel_engaged: str | None = None
    currency: str
    amount_minor: int | None = None
    dispute_amount_minor: int | None = None
    recovered_amount_minor: int | None = None
    matter_links: list[NoticeMatterLinkSummary] = Field(default_factory=list)
    filename: str | None = None
    has_file: bool
    content_type: str | None = None
    size_bytes: int | None = None
    created_at: datetime
    updated_at: datetime


class NoticeListResponse(BaseModel):
    notices: list[NoticeRecord]
    total: int
    next_cursor: str | None = None


class NoticeListFilters(BaseModel):
    query: str | None = Field(default=None, max_length=500)
    direction: NoticeDirection | None = None
    status: str | None = Field(default=None, max_length=80)
    matter_id: str | None = Field(default=None, max_length=36)
    owner_membership_id: str | None = Field(default=None, max_length=36)
    due_from: date | None = None
    due_to: date | None = None
    cursor: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=100, ge=1, le=100)

    @field_validator(
        "query",
        "status",
        "matter_id",
        "owner_membership_id",
        "cursor",
        mode="before",
    )
    @classmethod
    def clean_filter_text(cls, value: object) -> object:
        return _clean_optional_text(value)


class NoticeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: NoticeDirection = "received"
    subject: str = Field(min_length=1, max_length=500)
    type: str | None = Field(default=None, max_length=120)
    status: str = Field(default="Open", min_length=1, max_length=80)
    authority: str | None = Field(default=None, max_length=255)
    received_from: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=160)
    mode: str | None = Field(default=None, max_length=80)
    owner_membership_id: str | None = Field(default=None, max_length=36)
    received_on: date | None = None
    sent_on: date | None = None
    reply_due_on: date | None = None
    reply_required: bool = False
    reply_sent: bool = False
    reply_sent_on: date | None = None
    summary: str | None = Field(default=None, max_length=6000)
    remarks: str | None = Field(default=None, max_length=4000)
    response: str | None = Field(default=None, max_length=4000)
    internal_spoc: str | None = Field(default=None, max_length=160)
    internal_remarks: str | None = Field(default=None, max_length=4000)
    counsel_engaged: str | None = Field(default=None, max_length=255)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    amount_minor: int | None = Field(default=None, ge=0, le=_MAX_BIGINT)
    dispute_amount_minor: int | None = Field(default=None, ge=0, le=_MAX_BIGINT)
    recovered_amount_minor: int | None = Field(default=None, ge=0, le=_MAX_BIGINT)
    matter_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("subject", "status", mode="before")
    @classmethod
    def clean_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(*_OPTIONAL_TEXT_FIELDS, mode="before")
    @classmethod
    def clean_optional_text(cls, value: object) -> object:
        return _clean_optional_text(value)

    @field_validator("owner_membership_id", mode="before")
    @classmethod
    def clean_owner_membership_id(cls, value: object) -> object:
        return _clean_optional_text(value)

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return currency

    @field_validator("matter_ids")
    @classmethod
    def clean_matter_ids(cls, value: list[str]) -> list[str]:
        return _clean_matter_ids(value)

    @model_validator(mode="after")
    def validate_reply_state(self) -> Self:
        if self.direction == "received" and self.sent_on is not None:
            raise ValueError("sent_on is only valid for sent notices")
        if self.direction == "sent":
            if self.received_on is not None:
                raise ValueError("received_on is only valid for received notices")
            if self.received_from is not None:
                raise ValueError("received_from is only valid for received notices")
            if (
                self.reply_due_on is not None
                or self.reply_required
                or self.reply_sent
                or self.reply_sent_on is not None
            ):
                raise ValueError("reply tracking is only valid for received notices")
        if self.reply_due_on is not None:
            self.reply_required = True
        if self.reply_sent_on is not None:
            self.reply_sent = True
            self.reply_required = True
        if self.reply_sent:
            self.reply_required = True
        return self


class NoticeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime
    direction: NoticeDirection | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    type: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, min_length=1, max_length=80)
    authority: str | None = Field(default=None, max_length=255)
    received_from: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=160)
    mode: str | None = Field(default=None, max_length=80)
    owner_membership_id: str | None = Field(default=None, max_length=36)
    received_on: date | None = None
    sent_on: date | None = None
    reply_due_on: date | None = None
    reply_required: bool | None = None
    reply_sent: bool | None = None
    reply_sent_on: date | None = None
    summary: str | None = Field(default=None, max_length=6000)
    remarks: str | None = Field(default=None, max_length=4000)
    response: str | None = Field(default=None, max_length=4000)
    internal_spoc: str | None = Field(default=None, max_length=160)
    internal_remarks: str | None = Field(default=None, max_length=4000)
    counsel_engaged: str | None = Field(default=None, max_length=255)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    amount_minor: int | None = Field(default=None, ge=0, le=_MAX_BIGINT)
    dispute_amount_minor: int | None = Field(default=None, ge=0, le=_MAX_BIGINT)
    recovered_amount_minor: int | None = Field(default=None, ge=0, le=_MAX_BIGINT)
    matter_ids: list[str] | None = Field(default=None, max_length=100)

    @field_validator("subject", "status", mode="before")
    @classmethod
    def clean_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(*_OPTIONAL_TEXT_FIELDS, mode="before")
    @classmethod
    def clean_optional_text(cls, value: object) -> object:
        return _clean_optional_text(value)

    @field_validator("owner_membership_id", mode="before")
    @classmethod
    def clean_owner_membership_id(cls, value: object) -> object:
        return _clean_optional_text(value)

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter alphabetic code")
        return currency

    @field_validator("matter_ids")
    @classmethod
    def clean_matter_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_matter_ids(value)

    @model_validator(mode="after")
    def validate_patch_state(self) -> Self:
        required_non_null = {
            "expected_updated_at",
            "direction",
            "subject",
            "status",
            "currency",
            "matter_ids",
            "reply_required",
            "reply_sent",
        }
        for field_name in required_non_null & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null when supplied")
        if self.direction == "received" and self.sent_on is not None:
            raise ValueError("sent_on is only valid for sent notices")
        if self.direction == "sent":
            if self.received_on is not None:
                raise ValueError("received_on is only valid for received notices")
            if self.received_from is not None:
                raise ValueError("received_from is only valid for received notices")
            if (
                self.reply_due_on is not None
                or self.reply_required is True
                or self.reply_sent is True
                or self.reply_sent_on is not None
            ):
                raise ValueError("reply tracking is only valid for received notices")
        if self.reply_required is False and (
            self.reply_due_on is not None
            or self.reply_sent is True
            or self.reply_sent_on is not None
        ):
            raise ValueError("reply fields cannot be set when reply_required is false")
        if (
            "reply_sent" in self.model_fields_set
            and self.reply_sent is False
            and "reply_sent_on" in self.model_fields_set
            and self.reply_sent_on is not None
        ):
            raise ValueError("reply_sent_on cannot be set when reply_sent is false")
        return self


__all__ = [
    "NoticeCreateRequest",
    "NoticeDirection",
    "NoticeListFilters",
    "NoticeListResponse",
    "NoticeMatterLinkSummary",
    "NoticeOwnerOption",
    "NoticeRecord",
    "NoticeSourceKind",
    "NoticeUpdateRequest",
]
