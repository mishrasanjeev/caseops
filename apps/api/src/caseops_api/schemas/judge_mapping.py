from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JudgeMappingCandidateRecord(BaseModel):
    id: str
    full_name: str
    court_id: str


class JudgeMappingReviewRecord(BaseModel):
    id: str
    authority_document_id: str
    authority_title: str
    court_id: str | None
    court_name: str | None
    raw_judge_name: str
    source_ordinal: int
    reason: str
    status: str
    resolver_version: str
    candidates: list[JudgeMappingCandidateRecord] = Field(default_factory=list)
    resolved_judge_id: str | None
    resolution_note: str | None
    record_version: int
    created_at: datetime
    updated_at: datetime


class JudgeMappingReviewListResponse(BaseModel):
    reviews: list[JudgeMappingReviewRecord]
    returned_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    has_more: bool


class JudgeMappingReviewResolveRequest(BaseModel):
    judge_id: str = Field(min_length=1, max_length=36)
    expected_record_version: int = Field(ge=0)
    note: str = Field(min_length=8, max_length=1000)

    @field_validator("note", mode="before")
    @classmethod
    def strip_note(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class JudgeAliasCreateRequest(BaseModel):
    alias_text: str = Field(min_length=2, max_length=255)
    source: Literal["manual_curator", "official_court", "source_correction"]
    source_url: str | None = Field(default=None, max_length=500)
    source_evidence_text: str | None = Field(default=None, max_length=2000)

    @field_validator("alias_text", "source_url", "source_evidence_text", mode="before")
    @classmethod
    def strip_strings(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class BenchAliasCreateRequest(BaseModel):
    alias_text: str = Field(min_length=2, max_length=255)
    source: Literal["manual_curator", "official_court", "source_correction"]
    source_url: str | None = Field(default=None, max_length=500)

    @field_validator("alias_text", "source_url", mode="before")
    @classmethod
    def strip_strings(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class CatalogAliasRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alias_text: str
    alias_normalised: str
    source: str
    source_url: str | None
    is_active: bool
    record_version: int


class JudgeMergeRequest(BaseModel):
    destination_judge_id: str = Field(min_length=1, max_length=36)
    expected_source_version: int = Field(ge=0)
    expected_destination_version: int = Field(ge=0)
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class JudgeIdentityRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    court_id: str
    full_name: str
    source_name: str | None
    source_url: str | None
    source_reference: str | None
    identity_version: int
    record_version: int
    merged_into_judge_id: str | None
    is_active: bool


class JudgeCatalogListResponse(BaseModel):
    judges: list[JudgeIdentityRecord]
    returned_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    has_more: bool


class BenchIdentityRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    court_id: str
    name: str
    source_name: str | None
    source_url: str | None
    source_reference: str | None
    record_version: int


class BenchCatalogListResponse(BaseModel):
    benches: list[BenchIdentityRecord]
    returned_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    has_more: bool


class AuthorityRemapResponse(BaseModel):
    authority_document_id: str
    mapped: int = Field(ge=0)
    inserted: int = Field(ge=0)
    collisions: int = Field(ge=0)
    unresolved: int = Field(ge=0)
    review_ids: list[str] = Field(default_factory=list)
