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


class AuthorityCorpusStats(BaseModel):
    document_count: int
    chunk_count: int
    embedded_chunk_count: int
    forum_counts: dict[str, int]
    last_ingested_at: datetime | None


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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "018f1234-dead-beef-cafe-0123456789ab",
                    "company_id": "018f0000-0000-0000-0000-000000000001",
                    "authority_document_id": "d4ad579f-9b50-49bf-af02-755f14326c55",
                    "created_by_membership_id": "018f1111-2222-3333-4444-555555555555",
                    "kind": "flag",
                    "title": "Parity precedent for bail",
                    "body": "Cite alongside the triple-test paragraph in every bail brief.",
                    "is_archived": False,
                    "created_at": "2026-04-18T13:00:00Z",
                    "updated_at": "2026-04-18T13:00:00Z",
                }
            ]
        }
    }


class AuthorityAnnotationListResponse(BaseModel):
    annotations: list[AuthorityAnnotationRecord]


class AuthorityAnnotationCreateRequest(BaseModel):
    kind: AuthorityAnnotationKindLiteral
    title: str = Field(min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=8000)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "kind": "note",
                    "title": "Useful for triple-test framing",
                    "body": (
                        "The ratio at paragraphs 17-21 is the cleanest summary "
                        "of BNSS s.483 requirements we have seen."
                    ),
                }
            ]
        }
    }


class AuthorityAnnotationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=8000)
    is_archived: bool | None = None
