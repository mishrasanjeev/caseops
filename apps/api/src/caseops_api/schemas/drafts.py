from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DraftStatusLiteral = Literal[
    "draft",
    "in_review",
    "changes_requested",
    "approved",
    "finalized",
    "filed",
    "filing_rejected",
    "served",
]
DraftTypeLiteral = Literal["brief", "notice", "reply", "memo", "other"]
DraftReviewActionLiteral = Literal[
    "edit",
    "submit",
    "request_changes",
    "approve",
    "finalize",
    "file",
    "reject_filing",
    "serve",
]


class DraftCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    draft_type: DraftTypeLiteral = "brief"
    # R-UI stepper passthrough — the template the user picked and the
    # structured facts they filled in. Both optional so the legacy
    # "empty shell" path (title + draft_type only) keeps working.
    template_type: str | None = Field(default=None, max_length=60)
    facts: dict | None = None


class DraftGenerateRequest(BaseModel):
    """Body is empty today; kept to give room for future options —
    e.g. template selection, tone steering, focus issues. Having the
    POST body already in place means adding the knob later doesn't
    force a breaking API bump."""

    template_key: str | None = Field(default=None, max_length=120)
    focus_note: str | None = Field(default=None, max_length=4000)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "focus_note": (
                        "Draft a regular bail application under BNSS s.483 "
                        "(earlier CrPC s.439) before the Delhi High Court. "
                        "Cover: cause-title; memo of parties; brief facts; "
                        "triple-test grounds (flight risk, tampering, "
                        "repetition); parity with co-accused already on "
                        "bail; period of custody; applicant's undertakings; "
                        "prayer; verification."
                    )
                }
            ]
        }
    }


class DraftReviewRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


class IpDraftLifecycleRequest(BaseModel):
    reference: str = Field(min_length=1, max_length=255)
    occurred_at: datetime | None = None
    method: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=4000)


class DraftEditRequest(BaseModel):
    body: str = Field(min_length=1, max_length=524_288)


class DraftVersionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    draft_id: str
    revision: int
    body: str
    citations: list[str]
    verified_citation_count: int
    summary: str | None
    generated_by_membership_id: str | None
    model_run_id: str | None
    template_manifest: dict
    context_manifest: dict
    source_manifest: list[dict]
    created_at: datetime


class DraftReviewRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    draft_id: str
    version_id: str | None
    actor_membership_id: str | None
    action: DraftReviewActionLiteral
    notes: str | None
    metadata: dict
    created_at: datetime


class DraftRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    matter_id: str | None
    ip_docket_id: str | None
    ip_proceeding_id: str | None
    created_by_membership_id: str | None
    title: str
    draft_type: DraftTypeLiteral
    template_type: str | None
    status: DraftStatusLiteral
    review_required: bool
    current_version_id: str | None
    versions: list[DraftVersionRecord]
    reviews: list[DraftReviewRecord]
    created_at: datetime
    updated_at: datetime


class DraftListResponse(BaseModel):
    drafts: list[DraftRecord]
    next_cursor: str | None = None


class IpPleadingTemplateRecord(BaseModel):
    key: str
    label: str
    version: str
    draft_type: DraftTypeLiteral
    allowed_sides: list[str]
    allowed_stages: list[str]
    jurisdictions: list[str]
    format_profile: str


class IpPleadingTemplateListResponse(BaseModel):
    templates: list[IpPleadingTemplateRecord]


class IpPleadingDraftCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    template_key: str = Field(min_length=3, max_length=60)
    facts: dict | None = None


class IpDraftValidationFindingRecord(BaseModel):
    code: str
    severity: Literal["warning", "blocker"]
    message: str
    references: list[str]


class IpDraftValidationReportRecord(BaseModel):
    draft_id: str
    version_id: str
    revision: int
    evaluated_at: datetime
    blocker_count: int
    warning_count: int
    placeholder_count: int
    source_count: int
    source_anchor_count: int
    exhibit_anchor_count: int
    can_approve: bool
    can_file: bool
    findings: list[IpDraftValidationFindingRecord]


class DraftDiffLineRecord(BaseModel):
    kind: Literal["equal", "insert", "delete", "replace"]
    prev_line_number: int | None
    next_line_number: int | None
    text: str


class DraftDiffHunkRecord(BaseModel):
    prev_start: int
    prev_length: int
    next_start: int
    next_length: int
    lines: list[DraftDiffLineRecord]


class DraftCompareRecord(BaseModel):
    draft_id: str
    prev_revision: int
    next_revision: int
    prev_version_id: str
    next_version_id: str
    hunks: list[DraftDiffHunkRecord]
    citations_added: list[str]
    citations_removed: list[str]
    citations_kept: list[str]
    lines_added: int
    lines_removed: int
    summary: str
