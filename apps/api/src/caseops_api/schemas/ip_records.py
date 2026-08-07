from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from caseops_api.services.ip_records import normalize_ip_identifier, validate_identifier_owner


class IpIdentifierCreate(BaseModel):
    identifier_kind: Literal[
        "application", "registration", "opposition", "rectification", "appeal", "court"
    ]
    raw_value: str = Field(min_length=1, max_length=160)
    office: str = Field(min_length=1, max_length=80)
    jurisdiction: str = Field(min_length=2, max_length=40)
    source: str = Field(min_length=2, max_length=120)
    effective_from: date
    effective_until: date | None = None
    is_primary: bool = False
    application_id: str | None = None
    proceeding_id: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> IpIdentifierCreate:
        validate_identifier_owner(
            identifier_kind=self.identifier_kind,
            application_id=self.application_id,
            proceeding_id=self.proceeding_id,
        )
        if self.effective_until is not None and self.effective_until < self.effective_from:
            raise ValueError("effective_until cannot precede effective_from")
        if not normalize_ip_identifier(self.raw_value):
            raise ValueError("identifier must contain at least one Unicode letter or number")
        return self

    @property
    def normalized_value(self) -> str:
        return normalize_ip_identifier(self.raw_value)


class IpIdentifierCorrectionCreate(IpIdentifierCreate):
    supersedes_identifier_id: str
    correction_reason: str = Field(min_length=5, max_length=500)
