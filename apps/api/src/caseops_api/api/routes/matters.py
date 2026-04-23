from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.core.rate_limit import (
    ai_route_rate_limit,
    limiter,
    tenant_aware_key,
)
from caseops_api.schemas.billing import (
    InvoiceCreateRequest,
    InvoiceRecord,
    TimeEntryCreateRequest,
    TimeEntryRecord,
)
from caseops_api.schemas.drafts import (
    DraftCreateRequest,
    DraftGenerateRequest,
    DraftListResponse,
    DraftRecord,
    DraftReviewRequest,
)
from caseops_api.schemas.hearing_packs import (
    HearingPackGenerateRequest,
    HearingPackRecord,
)
from caseops_api.schemas.matter_access import (
    EthicalWallCreateRequest,
    EthicalWallRecord,
    MatterAccessGrantCreateRequest,
    MatterAccessGrantRecord,
    MatterAccessPanelResponse,
    MatterRestrictedAccessRequest,
)
from caseops_api.schemas.matters import (
    MatterAttachmentRecord,
    MatterCourtSyncImportRequest,
    MatterCourtSyncJobRecord,
    MatterCourtSyncPullRequest,
    MatterCourtSyncRunRecord,
    MatterCreateRequest,
    MatterHearingCreateRequest,
    MatterHearingRecord,
    MatterHearingUpdateRequest,
    MatterListResponse,
    MatterNoteCreateRequest,
    MatterNoteRecord,
    MatterRecord,
    MatterTaskCreateRequest,
    MatterTaskRecord,
    MatterTaskUpdateRequest,
    MatterUpdateRequest,
    MatterWorkspaceResponse,
)
from caseops_api.services.bench_matcher import (
    BenchSuggestion as BenchSuggestionDC,
)
from caseops_api.services.bench_matcher import (
    JudgeStub as JudgeStubDC,
)
from caseops_api.services.bench_matcher import (
    suggest_bench_for_matter_id,
)
from caseops_api.services.court_sync_jobs import (
    create_matter_court_sync_job,
    run_matter_court_sync_job,
)
from caseops_api.services.document_jobs import run_document_processing_job
from caseops_api.services.drafting import (
    create_draft,
    generate_draft_version,
    get_draft,
    list_drafts,
    load_draft_record,
    render_version_docx,
    transition_draft,
)
from caseops_api.services.hearing_packs import (
    generate_hearing_pack,
    get_latest_hearing_pack,
    mark_hearing_pack_reviewed,
)
from caseops_api.services.hearing_reminders import (
    list_reminders_for_matter,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import (
    add_access_grant,
    add_ethical_wall,
    list_access_panel,
    remove_access_grant,
    remove_ethical_wall,
    set_restricted_access,
)
from caseops_api.services.matter_attachment_annotations import (
    AnnotationKindLiteral,
    AnnotationRecord,
    archive_annotation,
    create_annotation,
    list_annotations,
)
from caseops_api.services.matter_summary import (
    MatterExecutiveSummary,
    generate_matter_summary,
)
from caseops_api.services.matter_summary_export import (
    render_summary_docx,
    render_summary_pdf,
)
from caseops_api.services.matter_timeline import build_matter_timeline_by_id
from caseops_api.services.matters import (
    create_matter,
    create_matter_attachment,
    create_matter_court_sync_import,
    create_matter_hearing,
    create_matter_invoice,
    create_matter_note,
    create_matter_task,
    create_time_entry,
    get_matter,
    get_matter_attachment_download,
    get_matter_workspace,
    list_matters,
    matter_code_available,
    request_matter_attachment_processing,
    update_matter,
    update_matter_hearing,
    update_matter_task,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]

# Capability-gated aliases used below. MatterWrite is the
# authenticated-tenant-with-any-role bar; the per-matter ACL in
# services/matter_access is the real gate on who can see each matter.
# Narrower capabilities are used where the action carries extra risk
# (approving a draft, granting access, issuing an invoice).
MatterCreator = Annotated[SessionContext, Depends(require_capability("matters:create"))]
MatterWriter = Annotated[SessionContext, Depends(require_capability("matters:write"))]
MatterEditor = Annotated[SessionContext, Depends(require_capability("matters:edit"))]
DraftCreator = Annotated[SessionContext, Depends(require_capability("drafts:create"))]
DraftGenerator = Annotated[SessionContext, Depends(require_capability("drafts:generate"))]
DraftReviewer = Annotated[SessionContext, Depends(require_capability("drafts:review"))]
DraftFinalizer = Annotated[SessionContext, Depends(require_capability("drafts:finalize"))]
HearingPackGenerator = Annotated[
    SessionContext, Depends(require_capability("hearing_packs:generate"))
]
HearingPackReviewer = Annotated[
    SessionContext, Depends(require_capability("hearing_packs:review"))
]
CourtSyncRunner = Annotated[
    SessionContext, Depends(require_capability("court_sync:run"))
]
InvoiceIssuer = Annotated[
    SessionContext, Depends(require_capability("invoices:issue"))
]
TimeEntryWriter = Annotated[
    SessionContext, Depends(require_capability("time_entries:write"))
]
DocumentUploader = Annotated[
    SessionContext, Depends(require_capability("documents:upload"))
]
DocumentManager = Annotated[
    SessionContext, Depends(require_capability("documents:manage"))
]
MatterAccessManager = Annotated[
    SessionContext, Depends(require_capability("matter_access:manage"))
]


@router.get("/", response_model=MatterListResponse, summary="List matters for the current company")
async def current_company_matters(
    context: CurrentContext,
    session: DbSession,
    limit: int | None = None,
    cursor: str | None = None,
) -> MatterListResponse:
    return list_matters(session, context=context, limit=limit, cursor=cursor)


@router.post(
    "/",
    response_model=MatterRecord,
    summary="Create a matter in the current company",
    description=(
        "Creates a tenant-scoped matter record — the primary unit of "
        "work in CaseOps. `matter_code` is unique per company and "
        "stable (appears on filings and invoices). `practice_area` "
        "drives retrieval seed-query selection during drafting. "
        "Ethical walls / matter ACLs are applied to every subsequent "
        "access — the creator is implicitly granted."
    ),
)
async def create_current_company_matter(
    payload: MatterCreateRequest,
    context: MatterCreator,
    session: DbSession,
) -> MatterRecord:
    return create_matter(session, context=context, payload=payload)


@router.get(
    "/code-available",
    summary="Check whether a matter_code is available for the current tenant",
    description=(
        "Pre-submit guard for the intake → matter promotion dialog "
        "(BUG-021 / Strict Ledger #3). Returns ``{available: bool, "
        "suggestion: str | None}``. The suggestion is the next "
        "lexically-bumped variant when the queried code is taken "
        "(e.g. ``CR-001 → CR-002``); the frontend uses it as a "
        "one-click 'Try this' affordance. Tenant-scoped — codes from "
        "other companies never leak."
    ),
)
async def check_matter_code_available(
    code: str,
    context: CurrentContext,
    session: DbSession,
) -> dict:
    return matter_code_available(session, context=context, code=code)


@router.get(
    "/{matter_id}/reminders",
    summary="List hearing reminders for a single matter",
    description=(
        "Strict Ledger #5 (BUG-013 in-app visibility, 2026-04-22). "
        "Per-matter view of the queued/sent/delivered/failed "
        "reminder rows the worker is going to send (or has sent) "
        "for hearings on this matter. Tenant-scoped + matter-access-"
        "scoped: anyone with `matters:read` who can see the matter "
        "can see its reminders. Mirrors the data the admin "
        "notifications dashboard surfaces but filtered to the "
        "matter the user is already looking at."
    ),
)
async def list_current_company_matter_reminders(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> dict:
    # get_matter enforces tenant + matter-ACL gates; raises 404 if the
    # caller can't see the matter.
    matter = get_matter(session, context=context, matter_id=matter_id)
    rows = list_reminders_for_matter(
        session, company_id=context.company.id, matter_id=matter.id,
    )
    return {
        "matter_id": matter.id,
        "reminders": [
            {
                "id": r.id,
                "hearing_id": r.hearing_id,
                "recipient_email": r.recipient_email,
                "channel": r.channel,
                "status": r.status,
                "scheduled_for": r.scheduled_for.isoformat()
                if r.scheduled_for else None,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                "delivered_at": r.delivered_at.isoformat()
                if r.delivered_at else None,
                "last_error": r.last_error,
                "attempts": r.attempts,
            }
            for r in rows
        ],
    }


@router.get("/{matter_id}", response_model=MatterRecord, summary="Get a matter by id")
async def get_current_company_matter(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterRecord:
    return get_matter(session, context=context, matter_id=matter_id)


@router.get(
    "/{matter_id}/workspace",
    response_model=MatterWorkspaceResponse,
    summary="Get the full workspace for a matter",
)
async def get_current_company_matter_workspace(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterWorkspaceResponse:
    return get_matter_workspace(session, context=context, matter_id=matter_id)


@router.get(
    "/{matter_id}/summary",
    response_model=MatterExecutiveSummary,
    summary=(
        "AI-generated executive summary of a matter (overview, key "
        "facts, timeline, legal issues, sections cited)."
    ),
)
async def get_current_company_matter_summary(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterExecutiveSummary:
    return generate_matter_summary(
        session, context=context, matter_id=matter_id
    )


@router.post(
    "/{matter_id}/summary/regenerate",
    response_model=MatterExecutiveSummary,
    summary=(
        "Force a fresh Haiku pass for the matter summary. Same "
        "response shape as GET /summary; used by the cockpit "
        "'Regenerate' button."
    ),
)
@limiter.limit(ai_route_rate_limit, key_func=tenant_aware_key)
async def post_current_company_matter_summary_regenerate(
    request: Request,
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterExecutiveSummary:
    # The service currently computes on demand every call — there's no
    # persisted cache yet. The POST shape is in place so the web UI can
    # wire a distinct button now; when we add `Matter.executive_summary`
    # JSONB caching (Q-follow-up), the GET returns the cached value and
    # this POST invalidates + recomputes.
    return generate_matter_summary(
        session, context=context, matter_id=matter_id
    )


@router.get(
    "/{matter_id}/summary.docx",
    summary="Download the matter executive summary as DOCX (Sprint Q7).",
    response_class=Response,
)
async def get_current_company_matter_summary_docx(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> Response:
    summary = generate_matter_summary(
        session, context=context, matter_id=matter_id
    )
    timeline = build_matter_timeline_by_id(
        session=session, context=context, matter_id=matter_id
    )
    # Loading the matter twice is cheap (SELECT by PK + tenant) and
    # keeps the service layer trivially unit-testable.
    from caseops_api.services.matters import _get_matter_model

    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    body, filename = render_summary_docx(
        matter_title=matter.title,
        matter_code=matter.matter_code,
        summary=summary,
        timeline=timeline,
    )
    return Response(
        content=body,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml"
            ".document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/{matter_id}/summary.pdf",
    summary="Download the matter executive summary as PDF (Sprint Q7 PDF slice).",
    response_class=Response,
)
async def get_current_company_matter_summary_pdf(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> Response:
    summary = generate_matter_summary(
        session, context=context, matter_id=matter_id
    )
    timeline = build_matter_timeline_by_id(
        session=session, context=context, matter_id=matter_id
    )
    from caseops_api.services.matters import _get_matter_model

    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    body, filename = render_summary_pdf(
        matter_title=matter.title,
        matter_code=matter.matter_code,
        summary=summary,
        timeline=timeline,
    )
    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# Sprint Q10 — attachment annotations -------------------------


class AnnotationResponse(BaseModel):
    id: str
    matter_attachment_id: str
    kind: str
    page: int
    bbox: list[float] | None = None
    quoted_text: str | None = None
    body: str | None = None
    color: str | None = None


class AnnotationListResponse(BaseModel):
    annotations: list[AnnotationResponse]


class AnnotationCreateRequest(BaseModel):
    kind: AnnotationKindLiteral = "highlight"
    page: int
    bbox: list[float] | None = None
    quoted_text: str | None = None
    body: str | None = None
    color: str | None = None


def _annotation_to_response(record: AnnotationRecord) -> AnnotationResponse:
    return AnnotationResponse(
        id=record.id,
        matter_attachment_id=record.matter_attachment_id,
        kind=record.kind,
        page=record.page,
        bbox=record.bbox,
        quoted_text=record.quoted_text,
        body=record.body,
        color=record.color,
    )


@router.get(
    "/{matter_id}/attachments/{attachment_id}/annotations",
    response_model=AnnotationListResponse,
    summary="Sprint Q10 — list annotations on a matter attachment.",
)
async def get_attachment_annotations(
    matter_id: str,
    attachment_id: str,
    context: CurrentContext,
    session: DbSession,
) -> AnnotationListResponse:
    records = list_annotations(
        session=session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
    )
    return AnnotationListResponse(
        annotations=[_annotation_to_response(r) for r in records],
    )


@router.post(
    "/{matter_id}/attachments/{attachment_id}/annotations",
    response_model=AnnotationResponse,
    summary=(
        "Sprint Q10 — add an annotation (highlight / note / flag) on a "
        "matter attachment. bbox is pdfjs text-layer coords; page is "
        "1-based."
    ),
)
async def post_attachment_annotation(
    matter_id: str,
    attachment_id: str,
    payload: AnnotationCreateRequest,
    context: MatterWriter,
    session: DbSession,
) -> AnnotationResponse:
    record = create_annotation(
        session=session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
        kind=payload.kind,
        page=payload.page,
        bbox=payload.bbox,
        quoted_text=payload.quoted_text,
        body=payload.body,
        color=payload.color,
    )
    return _annotation_to_response(record)


@router.delete(
    "/{matter_id}/attachments/{attachment_id}/annotations/{annotation_id}",
    status_code=204,
    summary="Sprint Q10 — archive (soft-delete) an attachment annotation.",
)
async def delete_attachment_annotation(
    matter_id: str,
    attachment_id: str,
    annotation_id: str,
    context: MatterWriter,
    session: DbSession,
) -> Response:
    archive_annotation(
        session=session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
        annotation_id=annotation_id,
    )
    return Response(status_code=204)


class BenchMatchJudge(BaseModel):
    id: str
    full_name: str
    honorific: str | None = None
    current_position: str | None = None
    practice_area_authority_count: int


class BenchMatchResponse(BaseModel):
    court_id: str | None
    court_name: str | None
    court_short_name: str | None
    forum_level: str | None
    bench_size: str
    bench_size_rationale: str
    practice_area_inferred: str | None
    confidence: str
    reasoning: list[str]
    suggested_judges: list[BenchMatchJudge]


@router.get(
    "/{matter_id}/bench-match",
    response_model=BenchMatchResponse,
    summary=(
        "Rule-based bench suggestion: likely court, bench size and "
        "sitting judges for this matter (not favorability)."
    ),
)
async def get_current_company_matter_bench_match(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> BenchMatchResponse:
    dc = suggest_bench_for_matter_id(
        session=session, context=context, matter_id=matter_id
    )
    return _bench_suggestion_to_response(dc)


def _bench_suggestion_to_response(dc: BenchSuggestionDC) -> BenchMatchResponse:
    return BenchMatchResponse(
        court_id=dc.court_id,
        court_name=dc.court_name,
        court_short_name=dc.court_short_name,
        forum_level=dc.forum_level,
        bench_size=dc.bench_size,
        bench_size_rationale=dc.bench_size_rationale,
        practice_area_inferred=dc.practice_area_inferred,
        confidence=dc.confidence,
        reasoning=list(dc.reasoning),
        suggested_judges=[_judge_stub_to_response(j) for j in dc.suggested_judges],
    )


def _judge_stub_to_response(stub: JudgeStubDC) -> BenchMatchJudge:
    return BenchMatchJudge(
        id=stub.id,
        full_name=stub.full_name,
        honorific=stub.honorific,
        current_position=stub.current_position,
        practice_area_authority_count=stub.practice_area_authority_count,
    )


@router.patch("/{matter_id}", response_model=MatterRecord, summary="Update a matter")
async def patch_current_company_matter(
    matter_id: str,
    payload: MatterUpdateRequest,
    context: MatterEditor,
    session: DbSession,
) -> MatterRecord:
    return update_matter(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/notes",
    response_model=MatterNoteRecord,
    summary="Add an internal note to a matter",
)
async def post_current_company_matter_note(
    matter_id: str,
    payload: MatterNoteCreateRequest,
    context: MatterWriter,
    session: DbSession,
) -> MatterNoteRecord:
    return create_matter_note(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/tasks",
    response_model=MatterTaskRecord,
    summary="Add a task to a matter workspace",
)
async def post_current_company_matter_task(
    matter_id: str,
    payload: MatterTaskCreateRequest,
    context: MatterWriter,
    session: DbSession,
) -> MatterTaskRecord:
    return create_matter_task(session, context=context, matter_id=matter_id, payload=payload)


@router.patch(
    "/{matter_id}/tasks/{task_id}",
    response_model=MatterTaskRecord,
    summary="Update a matter task",
)
async def patch_current_company_matter_task(
    matter_id: str,
    task_id: str,
    payload: MatterTaskUpdateRequest,
    context: MatterWriter,
    session: DbSession,
) -> MatterTaskRecord:
    return update_matter_task(
        session,
        context=context,
        matter_id=matter_id,
        task_id=task_id,
        payload=payload,
    )


@router.post(
    "/{matter_id}/time-entries",
    response_model=TimeEntryRecord,
    summary="Log a time entry against a matter",
)
async def post_current_company_matter_time_entry(
    matter_id: str,
    payload: TimeEntryCreateRequest,
    context: TimeEntryWriter,
    session: DbSession,
) -> TimeEntryRecord:
    return create_time_entry(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/hearings",
    response_model=MatterHearingRecord,
    summary="Add a hearing entry to a matter",
)
async def post_current_company_matter_hearing(
    matter_id: str,
    payload: MatterHearingCreateRequest,
    context: MatterWriter,
    session: DbSession,
) -> MatterHearingRecord:
    return create_matter_hearing(session, context=context, matter_id=matter_id, payload=payload)


@router.patch(
    "/{matter_id}/hearings/{hearing_id}",
    response_model=MatterHearingRecord,
    summary="Update a hearing entry (status, outcome, reschedule)",
)
async def patch_current_company_matter_hearing(
    matter_id: str,
    hearing_id: str,
    payload: MatterHearingUpdateRequest,
    context: MatterWriter,
    session: DbSession,
) -> MatterHearingRecord:
    return update_matter_hearing(
        session,
        context=context,
        matter_id=matter_id,
        hearing_id=hearing_id,
        payload=payload,
    )


@router.post(
    "/{matter_id}/court-sync/import",
    response_model=MatterCourtSyncRunRecord,
    summary="Import cause list and court order data into a matter workspace",
)
async def import_current_company_matter_court_sync(
    matter_id: str,
    payload: MatterCourtSyncImportRequest,
    context: CourtSyncRunner,
    session: DbSession,
) -> MatterCourtSyncRunRecord:
    return create_matter_court_sync_import(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


@router.post(
    "/{matter_id}/court-sync/pull",
    response_model=MatterCourtSyncJobRecord,
    summary="Queue a live court-data pull for the selected matter",
)
async def pull_current_company_matter_court_sync(
    matter_id: str,
    payload: MatterCourtSyncPullRequest,
    background_tasks: BackgroundTasks,
    context: CourtSyncRunner,
    session: DbSession,
) -> MatterCourtSyncJobRecord:
    job = create_matter_court_sync_job(
        session,
        context=context,
        matter_id=matter_id,
        source=payload.source,
        source_reference=payload.source_reference,
    )
    background_tasks.add_task(run_matter_court_sync_job, job.id)
    return job


@router.post(
    "/{matter_id}/invoices",
    response_model=InvoiceRecord,
    summary="Create a matter invoice",
)
async def post_current_company_matter_invoice(
    matter_id: str,
    payload: InvoiceCreateRequest,
    context: InvoiceIssuer,
    session: DbSession,
) -> InvoiceRecord:
    return create_matter_invoice(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/attachments",
    response_model=MatterAttachmentRecord,
    summary="Upload an attachment into a matter workspace",
)
async def post_current_company_matter_attachment(
    matter_id: str,
    file: Annotated[UploadFile, File(...)],
    background_tasks: BackgroundTasks,
    context: DocumentUploader,
    session: DbSession,
) -> MatterAttachmentRecord:
    attachment, job_id = create_matter_attachment(
        session,
        context=context,
        matter_id=matter_id,
        filename=file.filename or "document",
        content_type=file.content_type,
        stream=file.file,
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.post(
    "/{matter_id}/attachments/{attachment_id}/retry",
    response_model=MatterAttachmentRecord,
    summary="Retry matter attachment processing",
)
async def retry_current_company_matter_attachment_processing(
    matter_id: str,
    attachment_id: str,
    background_tasks: BackgroundTasks,
    context: DocumentManager,
    session: DbSession,
) -> MatterAttachmentRecord:
    attachment, job_id = request_matter_attachment_processing(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
        action="retry",
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.post(
    "/{matter_id}/attachments/{attachment_id}/reindex",
    response_model=MatterAttachmentRecord,
    summary="Reindex a matter attachment",
)
async def reindex_current_company_matter_attachment(
    matter_id: str,
    attachment_id: str,
    background_tasks: BackgroundTasks,
    context: DocumentManager,
    session: DbSession,
) -> MatterAttachmentRecord:
    attachment, job_id = request_matter_attachment_processing(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
        action="reindex",
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.get(
    "/{matter_id}/attachments/{attachment_id}/download",
    response_class=FileResponse,
    summary="Download a matter attachment",
)
async def download_current_company_matter_attachment(
    matter_id: str,
    attachment_id: str,
    context: CurrentContext,
    session: DbSession,
) -> FileResponse:
    attachment, storage_path = get_matter_attachment_download(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
    )
    return FileResponse(
        path=storage_path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@router.post(
    "/{matter_id}/hearings/{hearing_id}/pack",
    response_model=HearingPackRecord,
    summary="Generate a hearing pack for this hearing",
)
@limiter.limit(ai_route_rate_limit, key_func=tenant_aware_key)
async def post_current_company_matter_hearing_pack(
    request: Request,
    matter_id: str,
    hearing_id: str,
    payload: HearingPackGenerateRequest,
    context: HearingPackGenerator,
    session: DbSession,
) -> HearingPackRecord:
    # `payload` is accepted for future hooks (focus_note, etc.) but is not
    # used yet; keeping the POST body non-empty gives us room to grow.
    _ = payload
    pack = generate_hearing_pack(
        session,
        context=context,
        matter_id=matter_id,
        hearing_id=hearing_id,
    )
    return HearingPackRecord.model_validate(pack)


@router.post(
    "/{matter_id}/pack",
    response_model=HearingPackRecord,
    summary="Generate a hearing pack for the matter's next hearing",
)
async def post_current_company_matter_pack(
    matter_id: str,
    payload: HearingPackGenerateRequest,
    context: HearingPackGenerator,
    session: DbSession,
) -> HearingPackRecord:
    _ = payload
    pack = generate_hearing_pack(
        session,
        context=context,
        matter_id=matter_id,
        hearing_id=None,
    )
    return HearingPackRecord.model_validate(pack)


@router.get(
    "/{matter_id}/hearings/{hearing_id}/pack",
    response_model=HearingPackRecord | None,
    summary="Fetch the latest generated pack for this hearing",
)
async def get_current_company_matter_hearing_pack(
    matter_id: str,
    hearing_id: str,
    context: CurrentContext,
    session: DbSession,
) -> HearingPackRecord | None:
    pack = get_latest_hearing_pack(
        session,
        context=context,
        matter_id=matter_id,
        hearing_id=hearing_id,
    )
    if pack is None:
        return None
    return HearingPackRecord.model_validate(pack)


@router.post(
    "/{matter_id}/hearing-packs/{pack_id}/review",
    response_model=HearingPackRecord,
    summary="Mark a hearing pack as reviewed by the current user",
)
async def post_current_company_hearing_pack_review(
    matter_id: str,
    pack_id: str,
    context: HearingPackReviewer,
    session: DbSession,
) -> HearingPackRecord:
    pack = mark_hearing_pack_reviewed(
        session,
        context=context,
        matter_id=matter_id,
        pack_id=pack_id,
    )
    return HearingPackRecord.model_validate(pack)


@router.post(
    "/{matter_id}/drafts",
    response_model=DraftRecord,
    summary="Create a new draft shell on a matter",
)
async def post_current_company_matter_draft(
    matter_id: str,
    payload: DraftCreateRequest,
    context: DraftCreator,
    session: DbSession,
) -> DraftRecord:
    draft = create_draft(
        session,
        context=context,
        matter_id=matter_id,
        title=payload.title,
        draft_type=payload.draft_type,
        template_type=payload.template_type,
        facts=payload.facts,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.get(
    "/{matter_id}/drafts",
    response_model=DraftListResponse,
    summary="List drafts for this matter",
)
async def get_current_company_matter_drafts(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> DraftListResponse:
    drafts = list_drafts(session, context=context, matter_id=matter_id)
    records = [DraftRecord.model_validate(load_draft_record(d)) for d in drafts]
    return DraftListResponse(drafts=records, next_cursor=None)


@router.get(
    "/{matter_id}/drafts/{draft_id}",
    response_model=DraftRecord,
    summary="Get a specific draft with its version and review history",
)
async def get_current_company_matter_draft(
    matter_id: str,
    draft_id: str,
    context: CurrentContext,
    session: DbSession,
) -> DraftRecord:
    draft = get_draft(
        session, context=context, matter_id=matter_id, draft_id=draft_id
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/generate",
    response_model=DraftRecord,
    summary="Generate a new draft version using the LLM",
    description=(
        "Retrieves relevant authorities via multi-query hybrid search, "
        "(optionally) reranks them with a cross-encoder, and asks the "
        "configured LLM provider to emit a structured "
        "`{body, citations, summary}` JSON payload. The body is "
        "validated against the citation verifier; only authorities the "
        "tenant actually holds survive. Post-generation validators "
        "(statute confusion, UUID leakage, citation coverage) append "
        "findings to the summary so the reviewing partner sees them. "
        "Finalized drafts refuse regeneration with 409."
    ),
)
@limiter.limit(ai_route_rate_limit, key_func=tenant_aware_key)
async def post_current_company_matter_draft_generate(
    request: Request,
    matter_id: str,
    draft_id: str,
    payload: DraftGenerateRequest,
    context: DraftGenerator,
    session: DbSession,
) -> DraftRecord:
    draft = generate_draft_version(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        focus_note=payload.focus_note,
        template_key=payload.template_key,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/submit",
    response_model=DraftRecord,
    summary="Submit a draft for partner review",
)
async def post_current_company_matter_draft_submit(
    matter_id: str,
    draft_id: str,
    payload: DraftReviewRequest,
    context: DraftReviewer,
    session: DbSession,
) -> DraftRecord:
    draft = transition_draft(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        action="submit",
        notes=payload.notes,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/request-changes",
    response_model=DraftRecord,
    summary="Reviewer requests changes on the draft",
)
async def post_current_company_matter_draft_request_changes(
    matter_id: str,
    draft_id: str,
    payload: DraftReviewRequest,
    context: DraftReviewer,
    session: DbSession,
) -> DraftRecord:
    draft = transition_draft(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        action="request_changes",
        notes=payload.notes,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/approve",
    response_model=DraftRecord,
    summary="Approve an in-review draft (fails closed without verified citations)",
)
async def post_current_company_matter_draft_approve(
    matter_id: str,
    draft_id: str,
    payload: DraftReviewRequest,
    context: DraftReviewer,
    session: DbSession,
) -> DraftRecord:
    draft = transition_draft(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        action="approve",
        notes=payload.notes,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/finalize",
    response_model=DraftRecord,
    summary="Finalize an approved draft (terminal state)",
)
async def post_current_company_matter_draft_finalize(
    matter_id: str,
    draft_id: str,
    payload: DraftReviewRequest,
    context: DraftFinalizer,
    session: DbSession,
) -> DraftRecord:
    draft = transition_draft(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        action="finalize",
        notes=payload.notes,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.get(
    "/{matter_id}/drafts/{draft_id}/export.docx",
    summary="Download the current (or a specific) draft version as DOCX",
)
async def get_current_company_matter_draft_docx(
    matter_id: str,
    draft_id: str,
    context: CurrentContext,
    session: DbSession,
    version_id: str | None = None,
) -> Response:
    body, filename = render_version_docx(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        version_id=version_id,
    )
    return Response(
        content=body,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{matter_id}/access",
    response_model=MatterAccessPanelResponse,
    summary="List access grants + ethical walls on the matter (admin/owner)",
)
async def get_current_company_matter_access(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterAccessPanelResponse:
    matter, grants, walls = list_access_panel(
        session, context=context, matter_id=matter_id
    )
    return MatterAccessPanelResponse(
        matter_id=matter.id,
        restricted_access=matter.restricted_access,
        grants=[MatterAccessGrantRecord.model_validate(g) for g in grants],
        walls=[EthicalWallRecord.model_validate(w) for w in walls],
    )


@router.post(
    "/{matter_id}/access/restricted",
    summary="Toggle restricted_access on the matter (admin/owner)",
)
async def post_current_company_matter_restricted(
    matter_id: str,
    payload: MatterRestrictedAccessRequest,
    context: MatterAccessManager,
    session: DbSession,
) -> dict[str, object]:
    matter = set_restricted_access(
        session,
        context=context,
        matter_id=matter_id,
        restricted=payload.restricted,
    )
    return {"matter_id": matter.id, "restricted_access": matter.restricted_access}


@router.post(
    "/{matter_id}/access/grants",
    response_model=MatterAccessGrantRecord,
    summary="Add a matter access grant (admin/owner)",
)
async def post_current_company_matter_grant(
    matter_id: str,
    payload: MatterAccessGrantCreateRequest,
    context: MatterAccessManager,
    session: DbSession,
) -> MatterAccessGrantRecord:
    grant = add_access_grant(
        session,
        context=context,
        matter_id=matter_id,
        membership_id=payload.membership_id,
        access_level=payload.access_level,
        reason=payload.reason,
    )
    return MatterAccessGrantRecord.model_validate(grant)


@router.delete(
    "/{matter_id}/access/grants/{grant_id}",
    status_code=204,
    summary="Remove a matter access grant (admin/owner)",
)
async def delete_current_company_matter_grant(
    matter_id: str,
    grant_id: str,
    context: MatterAccessManager,
    session: DbSession,
) -> None:
    remove_access_grant(
        session,
        context=context,
        matter_id=matter_id,
        grant_id=grant_id,
    )


@router.post(
    "/{matter_id}/access/walls",
    response_model=EthicalWallRecord,
    summary="Add an ethical wall (admin/owner)",
)
async def post_current_company_matter_wall(
    matter_id: str,
    payload: EthicalWallCreateRequest,
    context: MatterAccessManager,
    session: DbSession,
) -> EthicalWallRecord:
    wall = add_ethical_wall(
        session,
        context=context,
        matter_id=matter_id,
        excluded_membership_id=payload.excluded_membership_id,
        reason=payload.reason,
    )
    return EthicalWallRecord.model_validate(wall)


@router.delete(
    "/{matter_id}/access/walls/{wall_id}",
    status_code=204,
    summary="Remove an ethical wall (admin/owner)",
)
async def delete_current_company_matter_wall(
    matter_id: str,
    wall_id: str,
    context: MatterAccessManager,
    session: DbSession,
) -> None:
    remove_ethical_wall(
        session,
        context=context,
        matter_id=matter_id,
        wall_id=wall_id,
    )
