from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from caseops_api.schemas.billing import InvoiceRecord, TimeEntryRecord
from caseops_api.schemas.document_processing import DocumentProcessingJobRecord

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


class MatterCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    matter_code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9-_/]+$")
    client_name: str | None = Field(default=None, min_length=2, max_length=255)
    opposing_party: str | None = Field(default=None, min_length=2, max_length=255)
    status: MatterStatusLiteral = "intake"
    practice_area: str = Field(min_length=2, max_length=120)
    forum_level: MatterForumLevelLiteral
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    next_hearing_on: date | None = None

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
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    next_hearing_on: date | None = None
    is_active: bool | None = None
    # Sprint 8c: optional team assignment. Pass null to detach; omit
    # the field to leave unchanged.
    team_id: str | None = None


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
    court_name: str | None
    judge_name: str | None
    description: str | None
    next_hearing_on: date | None
    is_active: bool
    team_id: str | None = None
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


class MatterCourtSyncImportRequest(BaseModel):
    source: str = Field(min_length=2, max_length=120)
    summary: str | None = Field(default=None, max_length=4000)
    cause_list_entries: list[MatterCauseListSyncItem] = Field(default_factory=list, max_length=10)
    orders: list[MatterCourtOrderSyncItem] = Field(default_factory=list, max_length=10)


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
    synced_at: datetime
    created_at: datetime


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
    created_at: datetime


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
