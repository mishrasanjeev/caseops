from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PrivateRetrievalSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=400)
    source_types: list[
        Literal["client", "matter", "matter_document", "ip_docket", "ip_document"]
    ] = Field(default_factory=list, max_length=5)
    scope_ids: dict[Literal["client", "matter", "ip_docket"], list[str]] = Field(
        default_factory=dict,
        max_length=3,
    )
    locale: str = Field(default="en-IN", min_length=2, max_length=20)
    limit: int = Field(default=10, ge=1, le=20)


class PrivateRetrievalResultRecord(BaseModel):
    projection_id: str
    source_type: str
    source_id: str
    source_version: str
    label: str
    content: str
    score: float


class PrivateRetrievalSearchResponse(BaseModel):
    items: list[PrivateRetrievalResultRecord]


class PrivateRetrievalIntegrityResponse(BaseModel):
    state: Literal["ready", "blocked", "disabled"]
    activation_reason: str
    active_generation_id: str | None
    live_projection_count: int
    tombstoned_projection_count: int
    pending_event_count: int
    failed_event_count: int
    oldest_pending_lag_seconds: int | None
    orphan_scope_count: int
    stale_source_count: int
    unsafe_tombstone_count: int
    generation_manifest_matches: bool
    release_blocked: bool
    blockers: list[str]


__all__ = [
    "PrivateRetrievalIntegrityResponse",
    "PrivateRetrievalResultRecord",
    "PrivateRetrievalSearchRequest",
    "PrivateRetrievalSearchResponse",
]
