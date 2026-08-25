"""Typed contracts for Madrid international registrations and designations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrademarkInternationalRecordCreateRequest(BaseModel):
    docket_id: str | None = None
    docket_title: str | None = Field(default=None, min_length=2, max_length=255)
    restricted: bool = False
    record_kind: Literal["international_registration", "international_designation"]
    direction: Literal["outbound", "inbound"]
    parent_registration_id: str | None = None
    basic_application_id: str | None = None
    international_application_number: str | None = Field(default=None, max_length=120)
    ir_number: str | None = Field(default=None, max_length=120)
    wipo_reference: str = Field(min_length=2, max_length=255)
    holder_name: str = Field(min_length=1, max_length=500)
    mark_name: str = Field(min_length=1, max_length=500)
    office_of_origin: str | None = Field(default=None, max_length=120)
    designated_member_code: str | None = Field(default=None, max_length=20)
    designated_office: str | None = Field(default=None, max_length=120)
    jurisdiction: str | None = Field(default=None, max_length=40)
    designation_kind: Literal["original", "subsequent"] | None = None
    classes: list[int] = Field(default_factory=list, max_length=45)
    goods_services: dict[str, str] = Field(default_factory=dict)
    priority_claims: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    form_kind: str | None = Field(default=None, max_length=40)
    wipo_status: str | None = Field(default=None, max_length=120)
    national_status: str | None = Field(default=None, max_length=120)
    local_agent_name: str | None = Field(default=None, max_length=500)
    source_url: str = Field(min_length=8, max_length=800)
    source_reference: str = Field(min_length=2, max_length=500)
    source_retrieved_at: datetime
    application_date: date | None = None
    international_registration_date: date | None = None
    designation_effective_date: date | None = None
    notification_date: date | None = None
    publication_date: date | None = None
    statement_date: date | None = None
    dependency_end_date: date | None = None
    renewal_due_date: date | None = None

    @model_validator(mode="after")
    def validate_record_boundary(self) -> TrademarkInternationalRecordCreateRequest:
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("Madrid source URL must use HTTP or HTTPS.")
        if self.source_retrieved_at.utcoffset() is None:
            raise ValueError("Madrid source retrieval time must include a timezone.")
        if self.docket_id is not None and self.docket_title is not None:
            raise ValueError("Docket title is only valid when creating a new Madrid docket.")
        if len(set(self.classes)) != len(self.classes) or any(
            value < 1 or value > 45 for value in self.classes
        ):
            raise ValueError("Madrid classes must be unique Nice class numbers from 1 to 45.")
        if set(self.goods_services) != {str(value) for value in self.classes}:
            raise ValueError("Goods/services must provide exactly one entry for every class.")
        if any(not value.strip() for value in self.goods_services.values()):
            raise ValueError("Goods/services entries cannot be blank.")

        designation_fields = (
            self.parent_registration_id,
            self.designated_member_code,
            self.jurisdiction,
            self.designation_kind,
            self.designation_effective_date,
        )
        if self.record_kind == "international_registration":
            if any(value is not None for value in designation_fields):
                raise ValueError("An international registration cannot contain designation fields.")
            if self.direction == "outbound" and self.basic_application_id is None:
                raise ValueError(
                    "An outbound Madrid registration requires a basic Indian application."
                )
        else:
            if any(value is None for value in designation_fields):
                raise ValueError(
                    "A Madrid designation requires its parent, member, jurisdiction, kind and date."
                )
            if self.basic_application_id is not None:
                raise ValueError(
                    "Only the international registration may own the basic application link."
                )
            if self.ir_number is not None:
                raise ValueError("IR number belongs to the parent international registration.")
        return self


class TrademarkInternationalRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    record_kind: Literal["international_registration", "international_designation"]
    direction: Literal["outbound", "inbound"]
    parent_registration_id: str | None
    basic_application_id: str | None
    international_application_number: str | None
    ir_number: str | None
    wipo_reference: str
    holder_name: str
    mark_name: str
    office_of_origin: str | None
    designated_member_code: str | None
    designated_office: str | None
    jurisdiction: str | None
    designation_kind: Literal["original", "subsequent"] | None
    classes_json: list[int]
    goods_services_json: dict[str, str]
    priority_claims_json: list[dict[str, Any]]
    form_kind: str | None
    wipo_status: str | None
    national_status: str | None
    local_agent_name: str | None
    source_url: str
    source_reference: str
    source_retrieved_at: datetime
    application_date: date | None
    international_registration_date: date | None
    designation_effective_date: date | None
    notification_date: date | None
    publication_date: date | None
    statement_date: date | None
    dependency_end_date: date | None
    renewal_due_date: date | None
    version: int
    created_by_membership_id: str
    updated_by_membership_id: str
    created_at: datetime
    updated_at: datetime


class TrademarkInternationalRecordPageResponse(BaseModel):
    items: list[TrademarkInternationalRecordResponse]
    total: int
    limit: int
    offset: int
