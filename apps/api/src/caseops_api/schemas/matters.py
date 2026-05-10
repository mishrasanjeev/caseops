from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from caseops_api.schemas.billing import InvoiceRecord, TimeEntryRecord
from caseops_api.schemas.document_processing import DocumentProcessingJobRecord
from caseops_api.schemas.matter_tags import MatterTagRecord

MatterStatusLiteral = Literal["intake", "active", "on_hold", "closed"]
MatterForumLevelLiteral = Literal[
    "lower_court",
    "high_court",
    "supreme_court",
    "tribunal",
    "arbitration",
    "advisory",
]
MatterTaskStatusLiteral = Literal["todo", "in_progress", "blocked", "completed"]
MatterTaskPriorityLiteral = Literal["low", "medium", "high", "urgent"]
MatterCourtOrderKindLiteral = Literal[
    "daily_order",
    "interim_order",
    "stay_order",
    "final_judgment",
    "other",
]
MatterStayStatusLiteral = Literal[
    "none",
    "granted",
    "continued",
    "modified",
    "vacated",
    "unknown",
]
MatterDocumentTypeLiteral = Literal[
    "complaint_petition",
    "notice",
    "vakalatnama",
    "pleading_reply",
    "affidavit",
    "evidence",
    "written_submission",
    "interim_application",
    "order_judgment",
    "correspondence",
    "research",
    "billing",
    "other",
]
MatterLifecycleStageLiteral = Literal[
    "initiation",
    "pleadings",
    "interim_applications",
    "evidence",
    "arguments",
    "orders",
    "post_order",
    "administrative",
    "other",
]
MatterTimelineEventTypeLiteral = Literal[
    "hearing",
    "court_order",
    "document",
    "deadline",
    "task",
    "activity",
]
_CLAIM_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def _normalize_claim_currency(value: object) -> str:
    if value is None:
        raise ValueError("claim_currency must not be null")
    if not isinstance(value, str):
        raise ValueError("claim_currency must be a 3-letter currency code")
    normalized = value.strip().upper()
    if not _CLAIM_CURRENCY_PATTERN.fullmatch(normalized):
        raise ValueError("claim_currency must be a 3-letter currency code")
    return normalized


def _clean_judge_names(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    cleaned = [str(name).strip() for name in value if str(name).strip()]
    return cleaned or None


class MatterCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    matter_code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9-_/]+$")
    client_name: str | None = Field(default=None, min_length=2, max_length=255)
    opposing_party: str | None = Field(default=None, min_length=2, max_length=255)
    status: MatterStatusLiteral = "intake"
    practice_area: str = Field(min_length=2, max_length=120)
    forum_level: MatterForumLevelLiteral
    court_id: str | None = Field(default=None, max_length=36)
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    forum_catalog_entry_id: str | None = Field(default=None, max_length=120)
    forum_state: str | None = Field(default=None, max_length=120)
    forum_district: str | None = Field(default=None, max_length=120)
    forum_city: str | None = Field(default=None, max_length=120)
    forum_consumer_level: Literal["national", "state", "district"] | None = None
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    next_hearing_on: date | None = None
    claim_amount_minor: int | None = Field(default=None, ge=0)
    claim_currency: str = Field(default="INR", min_length=3, max_length=3)
    claim_amount_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("claim_currency", mode="before")
    @classmethod
    def normalize_claim_currency(cls, value: object) -> str:
        return _normalize_claim_currency(value)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "Bail application — Rahul Verma",
                    "matter_code": "CR-2026-014",
                    "client_name": "Rahul Verma",
                    "opposing_party": "State of NCT of Delhi",
                    "status": "intake",
                    "practice_area": "criminal",
                    "forum_level": "high_court",
                    "court_name": "Delhi High Court",
                    "description": (
                        "FIR No. 145/2025, P.S. Connaught Place — "
                        "BNS ss.318/319/336/340. Seeking regular bail "
                        "under BNSS s.483."
                    ),
                    "next_hearing_on": "2026-05-02",
                }
            ]
        }
    }


class MatterUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    assignee_membership_id: str | None = None
    client_name: str | None = Field(default=None, min_length=2, max_length=255)
    opposing_party: str | None = Field(default=None, min_length=2, max_length=255)
    status: MatterStatusLiteral | None = None
    practice_area: str | None = Field(default=None, min_length=2, max_length=120)
    forum_level: MatterForumLevelLiteral | None = None
    court_id: str | None = Field(default=None, max_length=36)
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    forum_catalog_entry_id: str | None = Field(default=None, max_length=120)
    forum_state: str | None = Field(default=None, max_length=120)
    forum_district: str | None = Field(default=None, max_length=120)
    forum_city: str | None = Field(default=None, max_length=120)
    forum_consumer_level: Literal["national", "state", "district"] | None = None
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    next_hearing_on: date | None = None
    claim_amount_minor: int | None = Field(default=None, ge=0)
    claim_currency: str | None = Field(default=None, min_length=3, max_length=3)
    claim_amount_notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    # Sprint 8c: optional team assignment. Pass null to detach; omit
    # the field to leave unchanged.
    team_id: str | None = None
    # Phase C-3c (MOD-TS-016, 2026-04-25): per-matter cross-counsel
    # visibility flag. When True, every outside-counsel portal user
    # on this matter sees every other OC's submitted work product,
    # invoices, and time entries. Default False — each OC sees only
    # their own.
    oc_cross_visibility_enabled: bool | None = None

    @field_validator("claim_currency", mode="before")
    @classmethod
    def normalize_claim_currency(cls, value: object) -> str:
        return _normalize_claim_currency(value)


class MatterRecord(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "018f0abc-1234-5678-9abc-def012345678",
                    "company_id": "018f0000-0000-0000-0000-000000000001",
                    "assignee_membership_id": None,
                    "title": "Bail application — Rahul Verma",
                    "matter_code": "CR-2026-014",
                    "client_name": "Rahul Verma",
                    "opposing_party": "State of NCT of Delhi",
                    "status": "intake",
                    "practice_area": "criminal",
                    "forum_level": "high_court",
                    "court_name": "Delhi High Court",
                    "judge_name": None,
                    "description": (
                        "FIR No. 145/2025, P.S. Connaught Place — "
                        "BNS ss.318/319/336/340. Seeking regular bail "
                        "under BNSS s.483."
                    ),
                    "next_hearing_on": "2026-05-02",
                    "is_active": True,
                    "created_at": "2026-04-18T05:00:00Z",
                    "updated_at": "2026-04-18T05:00:00Z",
                }
            ]
        },
    )

    id: str
    company_id: str
    assignee_membership_id: str | None
    title: str
    matter_code: str
    client_name: str | None
    opposing_party: str | None
    status: MatterStatusLiteral
    practice_area: str
    forum_level: MatterForumLevelLiteral
    court_id: str | None = None
    court_name: str | None
    forum_catalog_entry_id: str | None = None
    forum_state: str | None = None
    forum_district: str | None = None
    forum_city: str | None = None
    forum_consumer_level: str | None = None
    judge_name: str | None
    description: str | None
    next_hearing_on: date | None
    claim_amount_minor: int | None = None
    claim_currency: str = "INR"
    claim_amount_notes: str | None = None
    tags: list[MatterTagRecord] = Field(default_factory=list)
    # LW-S1 keeps a stable list column for the LW-S2 stay/order work
    # without inventing stay state before the order model lands.
    has_stay: bool = False
    has_interim_order: bool = False
    is_active: bool
    team_id: str | None = None
    # Phase C-3c (MOD-TS-016, 2026-04-25). See MatterUpdateRequest for
    # semantics. Read-side default mirrors the DB default (False).
    oc_cross_visibility_enabled: bool = False
    created_at: datetime
    updated_at: datetime


class MatterListResponse(BaseModel):
    company_id: str
    matters: list[MatterRecord]
    # Opaque cursor to fetch the next page. Null when there is no next
    # page. Clients pass it back unchanged in `cursor=` on subsequent
    # calls. Keeping it opaque means we can change the encoding later
    # without breaking clients.
    next_cursor: str | None = None


class MatterListFilters(BaseModel):
    q: str | None = Field(default=None, max_length=255)
    client_name: str | None = Field(default=None, max_length=255)
    opposing_party: str | None = Field(default=None, max_length=255)
    forum_level: MatterForumLevelLiteral | None = None
    court_id: str | None = Field(default=None, max_length=36)
    status: MatterStatusLiteral | None = None
    created_from: date | None = None
    created_to: date | None = None
    next_hearing_from: date | None = None
    next_hearing_to: date | None = None
    tag: str | None = Field(default=None, max_length=120)
    has_stay: bool | None = None
    min_claim_amount_minor: int | None = Field(default=None, ge=0)
    max_claim_amount_minor: int | None = Field(default=None, ge=0)


class MatterWorkspaceMembership(BaseModel):
    membership_id: str
    user_id: str
    full_name: str
    email: str
    role: str
    is_active: bool


class MatterNoteCreateRequest(BaseModel):
    body: str = Field(min_length=2, max_length=4000)


class MatterNoteRecord(BaseModel):
    id: str
    matter_id: str
    author_membership_id: str
    author_name: str
    author_role: str
    body: str
    created_at: datetime


class MatterTaskCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    owner_membership_id: str | None = None
    due_on: date | None = None
    status: MatterTaskStatusLiteral = "todo"
    priority: MatterTaskPriorityLiteral = "medium"


class MatterTaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    owner_membership_id: str | None = None
    due_on: date | None = None
    status: MatterTaskStatusLiteral | None = None
    priority: MatterTaskPriorityLiteral | None = None


class MatterTaskRecord(BaseModel):
    id: str
    matter_id: str
    created_by_membership_id: str | None
    created_by_name: str | None
    owner_membership_id: str | None
    owner_name: str | None
    title: str
    description: str | None
    due_on: date | None
    status: MatterTaskStatusLiteral
    priority: MatterTaskPriorityLiteral
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MatterHearingCreateRequest(BaseModel):
    hearing_on: date
    forum_name: str = Field(min_length=2, max_length=255)
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    purpose: str = Field(min_length=2, max_length=255)
    status: Literal["scheduled", "completed", "adjourned"] = "scheduled"
    outcome_note: str | None = Field(default=None, max_length=4000)


class MatterHearingUpdateRequest(BaseModel):
    status: Literal["scheduled", "completed", "adjourned"] | None = None
    outcome_note: str | None = Field(default=None, max_length=4000)
    hearing_on: date | None = None
    # When set, the caller is explicitly asking the server to schedule
    # the default follow-up task generated on completion. Defaults to
    # True so a vanilla `status: completed` always produces a task —
    # surprising the lawyer with a missing task is worse than a
    # surprising extra one.
    create_follow_up: bool | None = None


class MatterHearingRecord(BaseModel):
    id: str
    matter_id: str
    hearing_on: date
    forum_name: str
    judge_name: str | None
    purpose: str
    status: Literal["scheduled", "completed", "adjourned"]
    outcome_note: str | None
    created_at: datetime


class MatterActivityRecord(BaseModel):
    id: str
    matter_id: str
    actor_membership_id: str | None
    actor_name: str | None
    event_type: str
    title: str
    detail: str | None
    created_at: datetime


class MatterCauseListSyncItem(BaseModel):
    listing_date: date
    forum_name: str = Field(min_length=2, max_length=255)
    bench_name: str | None = Field(default=None, min_length=2, max_length=255)
    courtroom: str | None = Field(default=None, min_length=1, max_length=120)
    item_number: str | None = Field(default=None, min_length=1, max_length=64)
    stage: str | None = Field(default=None, min_length=2, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    source_reference: str | None = Field(default=None, max_length=500)


class MatterCourtOrderSyncItem(BaseModel):
    order_date: date
    title: str = Field(min_length=2, max_length=255)
    summary: str = Field(min_length=2, max_length=6000)
    order_text: str | None = Field(default=None, max_length=12000)
    source_reference: str | None = Field(default=None, max_length=500)
    bench_name: str | None = Field(default=None, min_length=2, max_length=255)
    judge_names: list[str] | None = Field(default=None, max_length=12)
    order_attachment_id: str | None = Field(default=None, max_length=36)
    order_kind: MatterCourtOrderKindLiteral = "daily_order"
    is_interim_order: bool = False
    stay_status: MatterStayStatusLiteral = "none"
    stay_effective_until: date | None = None

    @field_validator("judge_names", mode="before")
    @classmethod
    def clean_judge_names(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("judge_names must be a list of names")
        return _clean_judge_names(value)


class MatterCourtSyncImportRequest(BaseModel):
    source: str = Field(min_length=2, max_length=120)
    summary: str | None = Field(default=None, max_length=4000)
    cause_list_entries: list[MatterCauseListSyncItem] = Field(default_factory=list, max_length=10)
    orders: list[MatterCourtOrderSyncItem] = Field(default_factory=list, max_length=10)


class ResolvedBenchMember(BaseModel):
    """Slice B (MOD-TS-001-C, 2026-04-25). One member of a resolved
    bench — surfaces on /app/matters/{id}/hearings as a clickable
    link to the judge profile. judge_id is the canonical Judge.id;
    matched_alias preserves the original spelling for display."""

    judge_id: str
    matched_alias: str
    confidence: str  # 'exact' | 'initial_surname'


class MatterCauseListEntryRecord(BaseModel):
    id: str
    matter_id: str
    sync_run_id: str | None
    listing_date: date
    forum_name: str
    bench_name: str | None
    courtroom: str | None
    item_number: str | None
    stage: str | None
    notes: str | None
    source: str
    source_reference: str | None
    synced_at: datetime
    created_at: datetime
    # Slice B (MOD-TS-001-C, 2026-04-25). Bench resolved into
    # canonical Judge FK rows by services.bench_resolver. NULL when
    # the resolver hasn't processed this row yet; [] when processed
    # but no judge cleared the high-quality confidence floor; populated
    # when at least one judge resolved.
    resolved_bench: list[ResolvedBenchMember] | None = None


class MatterCourtOrderRecord(BaseModel):
    id: str
    matter_id: str
    sync_run_id: str | None
    order_date: date
    title: str
    summary: str
    order_text: str | None
    source: str
    source_reference: str | None
    bench_name: str | None = None
    judge_names: list[str] | None = None
    order_attachment_id: str | None = None
    order_kind: MatterCourtOrderKindLiteral | None = None
    is_interim_order: bool = False
    stay_status: MatterStayStatusLiteral | None = None
    stay_effective_until: date | None = None
    synced_at: datetime
    created_at: datetime


class MatterCourtOrderUpdateRequest(BaseModel):
    bench_name: str | None = Field(default=None, min_length=2, max_length=255)
    judge_names: list[str] | None = Field(default=None, max_length=12)
    order_attachment_id: str | None = Field(default=None, max_length=36)
    order_kind: MatterCourtOrderKindLiteral | None = None
    is_interim_order: bool | None = None
    stay_status: MatterStayStatusLiteral | None = None
    stay_effective_until: date | None = None

    @field_validator("judge_names", mode="before")
    @classmethod
    def clean_judge_names(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("judge_names must be a list of names")
        return _clean_judge_names(value)


# BUG-032 (Hari 2026-05-09) — manual court-order create. The hearings
# page Orders-on-file card needs an explicit Add-order affordance;
# court-sync is the only path that creates ``MatterCourtOrder`` rows
# today, so an order produced by a hand-uploaded PDF or a scanned
# remarks summary cannot exist without first running a sync.
#
# Required fields mirror the backing model's NOT NULL columns
# (``order_date``, ``title``, ``summary``, ``source``); the optional
# fields mirror ``MatterCourtOrderUpdateRequest`` so the create + edit
# surfaces stay aligned. ``source`` defaults to ``"manual_upload"``;
# the frontend may set ``"manual_remarks"`` for orders entered without
# a PDF.
class MatterCourtOrderCreateRequest(BaseModel):
    order_date: date
    title: str = Field(min_length=2, max_length=255)
    summary: str = Field(min_length=2, max_length=4000)
    source: str = Field(default="manual_upload", min_length=2, max_length=120)
    source_reference: str | None = Field(default=None, max_length=500)
    order_text: str | None = Field(default=None, max_length=20000)
    bench_name: str | None = Field(default=None, min_length=2, max_length=255)
    judge_names: list[str] | None = Field(default=None, max_length=12)
    # An attachment uploaded ahead of this call (the dialog uploads
    # the file via the existing ``POST /attachments`` route first,
    # then passes the returned ID here). Validated against the same
    # matter to prevent cross-tenant linkability.
    order_attachment_id: str | None = Field(default=None, max_length=36)
    order_kind: MatterCourtOrderKindLiteral | None = None
    is_interim_order: bool | None = None
    stay_status: MatterStayStatusLiteral | None = None
    stay_effective_until: date | None = None

    @field_validator("judge_names", mode="before")
    @classmethod
    def clean_judge_names(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("judge_names must be a list of names")
        return _clean_judge_names(value)

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or value
        return value


class MatterTimelineLinkRecord(BaseModel):
    matter: str
    document: str | None = None


class MatterTimelineItemRecord(BaseModel):
    id: str
    event_type: MatterTimelineEventTypeLiteral
    event_date: date
    event_time: datetime | None = None
    title: str
    status: str | None = None
    summary: str | None = None
    source_type: str
    source_id: str | None = None
    badges: list[str] = Field(default_factory=list)
    links: MatterTimelineLinkRecord
    order_kind: MatterCourtOrderKindLiteral | None = None
    is_interim_order: bool = False
    stay_status: MatterStayStatusLiteral | None = None
    stay_effective_until: date | None = None
    linked_attachment_id: str | None = None
    metadata: dict[str, str | bool | int | None] = Field(default_factory=dict)


class MatterTimelineResponse(BaseModel):
    matter_id: str
    sort: Literal["asc", "desc"]
    items: list[MatterTimelineItemRecord]
    next_cursor: str | None = None
    generated_at: datetime


class MatterCourtSyncRunRecord(BaseModel):
    id: str
    matter_id: str
    triggered_by_membership_id: str | None
    triggered_by_name: str | None
    source: str
    status: Literal["completed", "failed"]
    summary: str | None
    imported_cause_list_count: int
    imported_order_count: int
    started_at: datetime
    completed_at: datetime


class MatterCourtSyncPullRequest(BaseModel):
    # Optional — when omitted, the server derives the adapter key from
    # the matter's court_name via services.court_sync_sources
    # .resolve_source_for_court. This lets the web "Run Sync" button
    # work with no UI picker for matters where the court is already
    # known; a client explicitly passing ``source`` still wins.
    source: str | None = Field(default=None, min_length=2, max_length=120)
    source_reference: str | None = Field(default=None, max_length=500)


class MatterCourtSyncJobRecord(BaseModel):
    id: str
    matter_id: str
    requested_by_membership_id: str | None
    requested_by_name: str | None
    sync_run_id: str | None
    source: str
    source_reference: str | None
    adapter_name: str | None
    status: Literal["queued", "processing", "completed", "failed"]
    imported_cause_list_count: int
    imported_order_count: int
    error_message: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class MatterAttachmentRecord(BaseModel):
    id: str
    matter_id: str
    uploaded_by_membership_id: str | None
    uploaded_by_name: str | None
    original_filename: str
    content_type: str | None
    size_bytes: int
    sha256_hex: str
    processing_status: Literal["pending", "indexed", "needs_ocr", "failed"]
    extracted_char_count: int
    extraction_error: str | None
    processed_at: datetime | None
    latest_job: DocumentProcessingJobRecord | None
    document_type: MatterDocumentTypeLiteral | None = None
    lifecycle_stage: MatterLifecycleStageLiteral | None = None
    document_date: date | None = None
    sequence_index: int | None = None
    linked_court_order_id: str | None = None
    created_at: datetime


class MatterAttachmentMetadataUpdateRequest(BaseModel):
    document_type: MatterDocumentTypeLiteral | None = None
    lifecycle_stage: MatterLifecycleStageLiteral | None = None
    document_date: date | None = None
    sequence_index: int | None = Field(default=None, ge=0)
    linked_court_order_id: str | None = Field(default=None, max_length=36)


class MatterWorkspaceResponse(BaseModel):
    matter: MatterRecord
    assignee: MatterWorkspaceMembership | None
    available_assignees: list[MatterWorkspaceMembership]
    tasks: list[MatterTaskRecord]
    cause_list_entries: list[MatterCauseListEntryRecord]
    court_orders: list[MatterCourtOrderRecord]
    court_sync_runs: list[MatterCourtSyncRunRecord]
    court_sync_jobs: list[MatterCourtSyncJobRecord]
    attachments: list[MatterAttachmentRecord]
    time_entries: list[TimeEntryRecord]
    invoices: list[InvoiceRecord]
    notes: list[MatterNoteRecord]
    hearings: list[MatterHearingRecord]
    activity: list[MatterActivityRecord]
