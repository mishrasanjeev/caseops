from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

AuthorityForumLevelLiteral = Literal["high_court", "supreme_court"]
AuthorityDocumentTypeLiteral = Literal["judgment", "order", "practice_direction", "notice"]


class AuthoritySourceRecord(BaseModel):
    source: str
    label: str
    description: str
    court_name: str
    forum_level: AuthorityForumLevelLiteral
    document_type: AuthorityDocumentTypeLiteral


class AuthoritySourceListResponse(BaseModel):
    sources: list[AuthoritySourceRecord]


class AuthorityIngestionRequest(BaseModel):
    source: str = Field(min_length=2, max_length=120)
    max_documents: int = Field(default=8, ge=1, le=20)


class AuthorityIngestionRunRecord(BaseModel):
    id: str
    requested_by_membership_id: str | None
    requested_by_name: str | None
    source: str
    adapter_name: str | None
    status: Literal["completed", "failed"]
    summary: str | None
    imported_document_count: int
    started_at: datetime
    completed_at: datetime


class AuthorityDocumentRecord(BaseModel):
    id: str
    source: str
    adapter_name: str
    court_name: str
    forum_level: AuthorityForumLevelLiteral
    document_type: AuthorityDocumentTypeLiteral
    title: str
    case_reference: str | None
    bench_name: str | None
    neutral_citation: str | None
    decision_date: date
    source_reference: str | None
    summary: str
    extracted_char_count: int
    ingested_at: datetime
    updated_at: datetime


class AuthorityDocumentListResponse(BaseModel):
    documents: list[AuthorityDocumentRecord]


class AuthoritySearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)
    forum_level: AuthorityForumLevelLiteral | None = None
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    document_type: AuthorityDocumentTypeLiteral | None = None


class AuthoritySearchResult(BaseModel):
    authority_document_id: str
    title: str
    court_name: str
    forum_level: AuthorityForumLevelLiteral
    document_type: AuthorityDocumentTypeLiteral
    decision_date: date
    case_reference: str | None
    bench_name: str | None
    summary: str
    source: str
    source_reference: str | None
    snippet: str
    score: int
    matched_terms: list[str]


class AuthoritySearchResponse(BaseModel):
    query: str
    provider: str
    generated_at: datetime
    results: list[AuthoritySearchResult]


AuthorityAnnotationKindLiteral = Literal["note", "flag", "tag"]


class AuthorityAnnotationRecord(BaseModel):
    id: str
    company_id: str
    authority_document_id: str
    created_by_membership_id: str | None
    kind: AuthorityAnnotationKindLiteral
    title: str
    body: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class AuthorityAnnotationListResponse(BaseModel):
    annotations: list[AuthorityAnnotationRecord]


class AuthorityAnnotationCreateRequest(BaseModel):
    kind: AuthorityAnnotationKindLiteral
    title: str = Field(min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=8000)


class AuthorityAnnotationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=8000)
    is_archived: bool | None = None
