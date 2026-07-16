"""Pydantic schemas for matter conflict-check requests/responses (PG-001)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConflictCheckRunRequest(BaseModel):
    """Run a fresh conflict check on a matter.

    `opposing_party_name` is required (most matters have one).
    `related_party_names` is the list of additional party names to scan
    (witnesses, related entities, beneficiaries, parent companies, etc.).
    The scanner intersects every name across clients/matters/contacts.
    """

    opposing_party_name: str = Field(min_length=1, max_length=255)
    related_party_names: list[str] = Field(default_factory=list, max_length=20)


class ConflictCheckResolveRequest(BaseModel):
    status: Literal["cleared", "conflicted", "waived"]
    resolution_note: str | None = Field(default=None, max_length=4000)


class ConflictCandidate(BaseModel):
    """A potential overlap surfaced by the scanner.

    `kind` names the source table; `id` is the row id; `name` is the
    string that overlapped; `overlap_reason` is human-readable.
    `similarity` is in [0, 1] — 1.0 = exact normalised match.
    """

    kind: Literal["client", "matter", "contact"]
    id: str
    name: str
    overlap_reason: str
    similarity: float


class ConflictCheckRecord(BaseModel):
    id: str
    matter_id: str
    opposing_party_name: str
    related_party_names: list[str]
    candidates: list[ConflictCandidate]
    status: Literal["pending", "cleared", "conflicted", "waived"]
    resolution_note: str | None
    resolved_by_membership_id: str | None
    resolved_at: datetime | None
    ran_by_membership_id: str | None
    matter_lifecycle_version: int = 0
    ran_at: datetime
    created_at: datetime


class ConflictCheckListResponse(BaseModel):
    matter_id: str
    checks: list[ConflictCheckRecord]
