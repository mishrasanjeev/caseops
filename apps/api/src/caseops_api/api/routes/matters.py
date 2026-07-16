from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

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
from caseops_api.schemas.affidavit_intelligence import AffidavitIntelligenceResponse
from caseops_api.schemas.audit import MatterAuditListResponse
from caseops_api.schemas.billing import (
    InvoiceCreateRequest,
    InvoiceRecord,
    TimeEntryCreateRequest,
    TimeEntryRecord,
)
from caseops_api.schemas.compliance import (
    ComplianceItemUpdateRequest,
    ComplianceListResponse,
    ComplianceRetryResponse,
)
from caseops_api.schemas.drafting_data import (
    DraftingDataExtractionResponse,
    DraftingDataFieldRecord,
    DraftingDataReviewRequest,
)
from caseops_api.schemas.drafts import (
    DraftCreateRequest,
    DraftEditRequest,
    DraftGenerateRequest,
    DraftListResponse,
    DraftRecord,
    DraftReviewRequest,
)
from caseops_api.schemas.google_drive_imports import (
    GoogleDriveImportDryRunRequest,
    GoogleDriveImportDryRunResponse,
    GoogleDriveProviderConfigStatus,
)
from caseops_api.schemas.hearing_coach import (
    HearingCoachReportResponse,
    HearingCoachRunRequest,
    HearingCoachStatusResponse,
)
from caseops_api.schemas.hearing_packs import (
    HearingPackGenerateRequest,
    HearingPackRecord,
)
from caseops_api.schemas.legal_knowledge_graph import LegalKnowledgeGraphResponse
from caseops_api.schemas.litigation_intelligence import (
    LitigationIntelligenceReviewMutationRequest,
    LitigationIntelligenceReviewMutationResponse,
    LitigationIntelligenceReviewResponse,
)
from caseops_api.schemas.matter_access import (
    EthicalWallCreateRequest,
    EthicalWallRecord,
    MatterAccessGrantCreateRequest,
    MatterAccessGrantRecord,
    MatterAccessPanelResponse,
    MatterRestrictedAccessRequest,
)
from caseops_api.schemas.matter_imports import BulkMatterImportDryRunResponse
from caseops_api.schemas.matter_tags import (
    MatterBulkTagAssignRequest,
    MatterBulkTagAssignResponse,
    MatterTagAssignmentCreateRequest,
    MatterTagAssignmentRecord,
    MatterTagSuggestionsResponse,
)
from caseops_api.schemas.matters import (
    MatterAttachmentMetadataUpdateRequest,
    MatterAttachmentRecord,
    MatterCourtOrderCreateRequest,
    MatterCourtOrderRecord,
    MatterCourtOrderUpdateRequest,
    MatterCourtSyncImportRequest,
    MatterCourtSyncJobRecord,
    MatterCourtSyncPullRequest,
    MatterCourtSyncRunRecord,
    MatterCreateRequest,
    MatterDeadlineCreateRequest,
    MatterDeadlineListResponse,
    MatterDeadlineRecord,
    MatterDeadlineUpdateRequest,
    MatterDocumentTypeLiteral,
    MatterHearingCreateRequest,
    MatterHearingRecord,
    MatterHearingUpdateRequest,
    MatterLifecycleStageLiteral,
    MatterLifecycleStatusRequest,
    MatterListFilters,
    MatterListResponse,
    MatterNextHearingHistoryResponse,
    MatterNextHearingSuggestionActionRequest,
    MatterNoteCreateRequest,
    MatterNoteRecord,
    MatterRecord,
    MatterTaskCreateRequest,
    MatterTaskListResponse,
    MatterTaskRecord,
    MatterTaskUpdateRequest,
    MatterTimelineResponse,
    MatterUpdateRequest,
    MatterWorkspaceResponse,
)
from caseops_api.schemas.mock_hearing import (
    MockHearingListResponse,
    MockHearingResponseCreateRequest,
    MockHearingSessionRecord,
    MockHearingStartRequest,
)
from caseops_api.schemas.predictive_intelligence import PredictiveIntelligenceResponse
from caseops_api.schemas.proceeding_intelligence import ProceedingIntelligenceResponse
from caseops_api.services.audit import record_from_context
from caseops_api.services.bench_matcher import (
    BenchSuggestion as BenchSuggestionDC,
)
from caseops_api.services.bench_matcher import (
    JudgeStub as JudgeStubDC,
)
from caseops_api.services.bench_matcher import (
    suggest_bench_for_matter_id,
)
from caseops_api.services.compliance_extraction import (
    _item_record,
    _run_record,
    list_compliance,
    retry_order_compliance_extraction,
    update_compliance_item,
)
from caseops_api.services.court_sync_jobs import (
    create_matter_court_sync_job,
    run_matter_court_sync_job,
)
from caseops_api.services.csv_security import csv_safe_mapping
from caseops_api.services.deadlines import (
    create_deadline,
    deadline_record,
    list_deadline_records,
    update_deadline,
)
from caseops_api.services.document_jobs import run_document_processing_job
from caseops_api.services.draft_compare import (
    DraftCompareResult,
    compare_versions_in_db,
)
from caseops_api.services.draft_pdf_export import render_version_pdf
from caseops_api.services.drafting import (
    create_draft,
    edit_draft_version,
    generate_draft_version,
    get_draft,
    list_drafts,
    load_draft_record,
    render_version_docx,
    transition_draft,
)
from caseops_api.services.drafting_data_extraction import (
    extract_drafting_data,
    list_drafting_data,
    review_drafting_data_field,
)
from caseops_api.services.filing_bundle import render_filing_bundle
from caseops_api.services.filing_checklist import build_filing_checklist
from caseops_api.services.google_drive_imports import (
    dry_run_google_drive_import,
    google_drive_provider_config_status,
)
from caseops_api.services.hearing_packs import (
    generate_hearing_pack,
    get_latest_hearing_pack,
    mark_hearing_pack_reviewed,
)
from caseops_api.services.hearing_reminders import (
    list_reminders_for_matter,
)
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
from caseops_api.services.matter_audit import (
    export_matter_audit_events,
    list_matter_audit_events,
    matter_audit_event_dict,
)
from caseops_api.services.matter_imports import (
    MATTER_IMPORT_DOCUMENT_ARCHIVE_MAX_BYTES,
    MATTER_IMPORT_DOCUMENT_MANIFEST_MAX_BYTES,
    MATTER_IMPORT_MAPPING_MAX_BYTES,
    dry_run_bulk_matter_import,
    parse_matter_import_document_archive,
    parse_matter_import_document_manifest,
    parse_matter_import_mapping,
)
from caseops_api.services.matter_summary import (
    MatterExecutiveSummary,
    generate_matter_summary,
)
from caseops_api.services.matter_summary_export import (
    render_summary_docx,
    render_summary_pdf,
)
from caseops_api.services.matter_tags import (
    assign_tag_to_matter,
    bulk_assign_tag,
    remove_tag_from_matter,
    suggest_tags_for_matter,
)
from caseops_api.services.matter_timeline import (
    build_matter_timeline_by_id,
    parse_timeline_types,
    timeline_response,
    timeline_source_limit,
)
from caseops_api.services.matters import (
    create_matter,
    create_matter_attachment,
    create_matter_court_order,
    create_matter_court_sync_import,
    create_matter_hearing,
    create_matter_invoice,
    create_matter_note,
    create_matter_task,
    create_time_entry,
    get_matter,
    get_matter_attachment_bulk_download,
    get_matter_attachment_download,
    get_matter_invoice_pdf,
    get_matter_workspace,
    list_matter_tasks,
    list_matters,
    matter_code_available,
    request_matter_attachment_processing,
    transition_matter_lifecycle_status,
    update_matter,
    update_matter_attachment_metadata,
    update_matter_court_order,
    update_matter_hearing,
    update_matter_task,
)
from caseops_api.services.next_hearing import (
    decide_next_hearing_suggestion,
    list_next_hearing_history,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.today_view import build_matter_next_action

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
MatterArchiver = Annotated[SessionContext, Depends(require_capability("matters:archive"))]
DraftCreator = Annotated[SessionContext, Depends(require_capability("drafts:create"))]
DraftEditor = Annotated[SessionContext, Depends(require_capability("drafts:edit"))]
DraftGenerator = Annotated[SessionContext, Depends(require_capability("drafts:generate"))]
DraftReviewer = Annotated[SessionContext, Depends(require_capability("drafts:review"))]
DraftFinalizer = Annotated[SessionContext, Depends(require_capability("drafts:finalize"))]
HearingPackGenerator = Annotated[
    SessionContext, Depends(require_capability("hearing_packs:generate"))
]
HearingPackReviewer = Annotated[SessionContext, Depends(require_capability("hearing_packs:review"))]
CourtSyncRunner = Annotated[SessionContext, Depends(require_capability("court_sync:run"))]
InvoiceIssuer = Annotated[SessionContext, Depends(require_capability("invoices:issue"))]
TimeEntryWriter = Annotated[SessionContext, Depends(require_capability("time_entries:write"))]
DocumentUploader = Annotated[SessionContext, Depends(require_capability("documents:upload"))]
DocumentManager = Annotated[SessionContext, Depends(require_capability("documents:manage"))]
MatterAccessManager = Annotated[SessionContext, Depends(require_capability("matter_access:manage"))]
MatterAuditExporter = Annotated[SessionContext, Depends(require_capability("audit:export"))]
MatterBulkImporter = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]


@router.get("/", response_model=MatterListResponse, summary="List matters for the current company")
async def current_company_matters(
    context: CurrentContext,
    session: DbSession,
    filters: Annotated[MatterListFilters, Depends()],
    limit: int | None = None,
    cursor: str | None = None,
) -> MatterListResponse:
    return list_matters(
        session,
        context=context,
        limit=limit,
        cursor=cursor,
        filters=filters,
    )


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


@router.post(
    "/imports/dry-run",
    response_model=BulkMatterImportDryRunResponse,
    summary="Dry-run a bulk matter import mapping without creating records",
    description=(
        "Parses a CSV, JSON, or XLSX matter mapping file and returns a "
        "tenant-scoped validation plan. Optional document manifests or ZIP "
        "archives are inspected for filenames only. The endpoint writes no "
        "matter rows, attachment rows, storage objects, OCR jobs, corpus jobs, "
        "or embeddings; it records only a redacted audit summary."
    ),
)
async def dry_run_current_company_matter_import(
    context: MatterBulkImporter,
    session: DbSession,
    mapping_file: Annotated[
        UploadFile,
        File(
            description=(
                "CSV, JSON, or XLSX mapping file. Read in memory for validation "
                "only and not stored."
            ),
        ),
    ],
    document_manifest: Annotated[
        UploadFile | None,
        File(
            description=(
                "Optional JSON, CSV, or text manifest of folder/ZIP filenames. "
                "Filenames are used only for dry-run reference validation."
            ),
        ),
    ] = None,
    document_archive: Annotated[
        UploadFile | None,
        File(
            description=(
                "Optional ZIP archive scanned for entry names only. File payloads "
                "are not extracted, stored, OCRed, or embedded."
            ),
        ),
    ] = None,
) -> BulkMatterImportDryRunResponse:
    mapping_content = await mapping_file.read(MATTER_IMPORT_MAPPING_MAX_BYTES + 1)
    parsed_import = parse_matter_import_mapping(
        filename=mapping_file.filename or "matters.csv",
        content_type=mapping_file.content_type,
        content=mapping_content,
    )
    document_filenames: list[str] = []
    if document_manifest is not None:
        manifest_content = await document_manifest.read(
            MATTER_IMPORT_DOCUMENT_MANIFEST_MAX_BYTES + 1
        )
        document_filenames.extend(
            parse_matter_import_document_manifest(
                filename=document_manifest.filename or "documents.txt",
                content=manifest_content,
            )
        )
    if document_archive is not None:
        archive_content = await document_archive.read(MATTER_IMPORT_DOCUMENT_ARCHIVE_MAX_BYTES + 1)
        document_filenames.extend(
            parse_matter_import_document_archive(
                filename=document_archive.filename or "documents.zip",
                content_type=document_archive.content_type,
                content=archive_content,
            )
        )
    return dry_run_bulk_matter_import(
        session,
        context=context,
        parsed_import=parsed_import,
        available_document_filenames=document_filenames,
    )


@router.get(
    "/imports/drive/provider-config",
    response_model=GoogleDriveProviderConfigStatus,
    summary="Report Google Drive manual-import provider config status",
    description=(
        "Returns whether the Google Drive provider is configured. Reports "
        "missing environment variable NAMES only — never client IDs, "
        "client secrets, redirect URIs, OAuth tokens, refresh tokens, or "
        "Drive payloads. Fails closed when any required setting is unset."
    ),
)
async def get_google_drive_provider_config_status(
    context: CurrentContext,
    session: DbSession,
) -> GoogleDriveProviderConfigStatus:
    return google_drive_provider_config_status(session, context=context)


@router.post(
    "/{matter_id}/imports/drive/dry-run",
    response_model=GoogleDriveImportDryRunResponse,
    summary="Dry-run a manual Google Drive folder import for a matter",
    description=(
        "Validates user-supplied Google Drive folder/file metadata against "
        "the matter's storage rules and returns a per-file import plan. "
        "Does not contact Google. Writes no attachments, storage objects, "
        "OCR jobs, corpus jobs, or embeddings. Stores no OAuth tokens or "
        "Drive payloads. Records a redacted audit summary only."
    ),
)
async def dry_run_current_company_matter_google_drive_import(
    matter_id: str,
    payload: GoogleDriveImportDryRunRequest,
    context: DocumentUploader,
    session: DbSession,
) -> GoogleDriveImportDryRunResponse:
    return dry_run_google_drive_import(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


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


@router.post(
    "/bulk-tags",
    response_model=MatterBulkTagAssignResponse,
    summary="Assign one tag to multiple visible matters",
)
async def post_current_company_matter_bulk_tags(
    payload: MatterBulkTagAssignRequest,
    context: MatterEditor,
    session: DbSession,
) -> MatterBulkTagAssignResponse:
    result = bulk_assign_tag(session, context=context, payload=payload)
    session.commit()
    return result


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
        session,
        company_id=context.company.id,
        matter_id=matter.id,
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
                "scheduled_for": r.scheduled_for.isoformat() if r.scheduled_for else None,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
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
    "/{matter_id}/audit-events",
    response_model=MatterAuditListResponse,
    summary="List AuditEvent rows scoped to one visible matter",
)
async def get_current_company_matter_audit_events(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
    since: datetime | None = None,
    until: datetime | None = None,
    actor: str | None = Query(default=None, max_length=255),
    action: str | None = Query(default=None, max_length=120),
    keyword: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MatterAuditListResponse:
    return list_matter_audit_events(
        session,
        context=context,
        matter_id=matter_id,
        since=since,
        until=until,
        actor=actor,
        action=action,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{matter_id}/audit-events/export",
    summary="Export AuditEvent rows scoped to one visible matter",
)
async def export_current_company_matter_audit_events(
    matter_id: str,
    context: MatterAuditExporter,
    session: DbSession,
    since: datetime | None = None,
    until: datetime | None = None,
    actor: str | None = Query(default=None, max_length=255),
    action: str | None = Query(default=None, max_length=120),
    keyword: str | None = Query(default=None, max_length=255),
    format: Literal["jsonl", "csv"] = "jsonl",
    limit: int = Query(default=10_000, ge=1, le=10_000),
) -> StreamingResponse:
    events = export_matter_audit_events(
        session,
        context=context,
        matter_id=matter_id,
        since=since,
        until=until,
        actor=actor,
        action=action,
        keyword=keyword,
        limit=limit,
    )
    exported_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    record_from_context(
        session,
        context,
        action="matter.audit.exported",
        target_type="matter",
        target_id=matter_id,
        matter_id=matter_id,
        metadata={
            "format": format,
            "row_count": len(events),
            "filters": {
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None,
                "actor": actor,
                "action": action,
                "keyword": keyword,
                "limit": limit,
            },
        },
    )
    session.commit()
    filename = f"matter-audit-{matter_id}-{exported_at}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "id",
                "created_at",
                "company_id",
                "matter_id",
                "actor_type",
                "actor_membership_id",
                "actor_label",
                "action",
                "target_type",
                "target_id",
                "result",
                "request_id",
                "metadata",
            ],
        )
        writer.writeheader()
        for event in events:
            row = matter_audit_event_dict(event)
            row["metadata"] = json.dumps(row.get("metadata") or {}, sort_keys=True)
            writer.writerow(csv_safe_mapping(row))
        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers=headers,
        )
    lines = "\n".join(json.dumps(matter_audit_event_dict(event)) for event in events)
    if lines:
        lines += "\n"
    return StreamingResponse(
        iter([lines]),
        media_type="application/x-ndjson",
        headers=headers,
    )


@router.post(
    "/{matter_id}/tags",
    response_model=MatterTagAssignmentRecord,
    summary="Assign a tenant-scoped tag to a matter",
)
async def post_current_company_matter_tag(
    matter_id: str,
    payload: MatterTagAssignmentCreateRequest,
    context: MatterEditor,
    session: DbSession,
) -> MatterTagAssignmentRecord:
    result = assign_tag_to_matter(session, context=context, matter_id=matter_id, payload=payload)
    session.commit()
    return result


@router.delete(
    "/{matter_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a tenant-scoped tag from a matter",
)
async def delete_current_company_matter_tag(
    matter_id: str,
    tag_id: str,
    context: MatterEditor,
    session: DbSession,
) -> Response:
    remove_tag_from_matter(session, context=context, matter_id=matter_id, tag_id=tag_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{matter_id}/tag-suggestions",
    response_model=MatterTagSuggestionsResponse,
    summary="Return deterministic tenant-scoped tag suggestions",
)
async def get_current_company_matter_tag_suggestions(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterTagSuggestionsResponse:
    return suggest_tags_for_matter(session, context=context, matter_id=matter_id)


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
    "/{matter_id}/timeline",
    response_model=MatterTimelineResponse,
    summary="LegalWorkspace LW-S2 matter timeline",
)
async def get_current_company_matter_timeline(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    types: str | None = None,
    sort: Literal["asc", "desc"] = "asc",
    limit: int = 100,
    cursor: str | None = None,
) -> MatterTimelineResponse:
    timeline = build_matter_timeline_by_id(
        session=session,
        context=context,
        matter_id=matter_id,
        sort=sort,
        from_date=from_date,
        to_date=to,
        event_types=parse_timeline_types(types),
        source_limit=timeline_source_limit(limit=limit, cursor=cursor),
    )
    return timeline_response(timeline, limit=limit, cursor=cursor)


@router.get(
    "/{matter_id}/proceeding-intelligence",
    response_model=ProceedingIntelligenceResponse,
    summary="LI-S1 proceeding/order-sheet intelligence for a matter",
)
async def get_current_company_matter_proceeding_intelligence(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> ProceedingIntelligenceResponse:
    from caseops_api.services.proceeding_intelligence import (
        list_proceeding_intelligence,
    )

    return list_proceeding_intelligence(
        session,
        context=context,
        matter_id=matter_id,
    )


@router.get(
    "/{matter_id}/litigation-intelligence/review",
    response_model=LitigationIntelligenceReviewResponse,
    summary="LI-S6 source-backed litigation intelligence review queue",
)
async def get_current_company_matter_litigation_intelligence_review(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> LitigationIntelligenceReviewResponse:
    from caseops_api.services.litigation_intelligence_review import (
        build_litigation_intelligence_review,
    )

    return build_litigation_intelligence_review(
        session,
        context=context,
        matter_id=matter_id,
    )


@router.post(
    "/{matter_id}/litigation-intelligence/review/actions",
    response_model=LitigationIntelligenceReviewMutationResponse,
    summary="LI-S9 mutate a source-backed litigation intelligence review item",
)
async def post_current_company_matter_litigation_intelligence_review_action(
    matter_id: str,
    payload: LitigationIntelligenceReviewMutationRequest,
    context: HearingPackReviewer,
    session: DbSession,
) -> LitigationIntelligenceReviewMutationResponse:
    from caseops_api.services.litigation_intelligence_review import (
        mutate_litigation_intelligence_review_item,
    )

    return mutate_litigation_intelligence_review_item(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


@router.get(
    "/{matter_id}/legal-knowledge-graph",
    response_model=LegalKnowledgeGraphResponse,
    summary="LI-S11 source-backed legal knowledge graph for a matter",
)
async def get_current_company_matter_legal_knowledge_graph(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> LegalKnowledgeGraphResponse:
    from caseops_api.services.legal_knowledge_graph import (
        get_legal_knowledge_graph,
    )

    return get_legal_knowledge_graph(
        session,
        context=context,
        matter_id=matter_id,
    )


@router.post(
    "/{matter_id}/legal-knowledge-graph/materialize",
    response_model=LegalKnowledgeGraphResponse,
    summary="Materialize LI-S11 source-backed legal knowledge graph for a matter",
)
async def post_current_company_matter_legal_knowledge_graph_materialize(
    matter_id: str,
    context: MatterWriter,
    session: DbSession,
) -> LegalKnowledgeGraphResponse:
    from caseops_api.services.legal_knowledge_graph import (
        materialize_legal_knowledge_graph,
    )

    return materialize_legal_knowledge_graph(
        session,
        context=context,
        matter_id=matter_id,
    )


@router.post(
    "/{matter_id}/court-orders/{order_id}/proceeding-intelligence/extract",
    response_model=ProceedingIntelligenceResponse,
    summary="Extract LI-S1 proceeding signals from a source-backed court order",
)
async def post_current_company_matter_order_proceeding_intelligence_extract(
    matter_id: str,
    order_id: str,
    context: MatterWriter,
    session: DbSession,
) -> ProceedingIntelligenceResponse:
    from caseops_api.services.proceeding_intelligence import (
        extract_order_proceeding_intelligence,
    )

    return extract_order_proceeding_intelligence(
        session,
        context=context,
        matter_id=matter_id,
        order_id=order_id,
    )


@router.get(
    "/{matter_id}/affidavit-intelligence",
    response_model=AffidavitIntelligenceResponse,
    summary="LI-S2 affidavit hearing-prep intelligence for a matter",
)
async def get_current_company_matter_affidavit_intelligence(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> AffidavitIntelligenceResponse:
    from caseops_api.services.affidavit_intelligence import (
        list_affidavit_intelligence,
    )

    return list_affidavit_intelligence(
        session,
        context=context,
        matter_id=matter_id,
    )


@router.post(
    "/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
    response_model=AffidavitIntelligenceResponse,
    summary="Analyze a source-backed affidavit attachment for hearing prep",
)
async def post_current_company_matter_attachment_affidavit_intelligence_analyze(
    matter_id: str,
    attachment_id: str,
    context: HearingPackGenerator,
    session: DbSession,
) -> AffidavitIntelligenceResponse:
    from caseops_api.services.affidavit_intelligence import (
        analyze_affidavit_attachment,
    )

    return analyze_affidavit_attachment(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
    )


@router.post(
    "/{matter_id}/mock-hearings",
    response_model=MockHearingSessionRecord,
    summary="Start a text-first mock hearing session from affidavit questions",
)
async def post_current_company_matter_mock_hearing(
    matter_id: str,
    payload: MockHearingStartRequest,
    context: HearingPackGenerator,
    session: DbSession,
) -> MockHearingSessionRecord:
    from caseops_api.services.mock_hearing import start_mock_hearing

    return start_mock_hearing(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


@router.get(
    "/{matter_id}/mock-hearings",
    response_model=MockHearingListResponse,
    summary="List mock hearing sessions for a matter",
)
async def get_current_company_matter_mock_hearings(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MockHearingListResponse:
    from caseops_api.services.mock_hearing import list_mock_hearings

    return list_mock_hearings(
        session,
        context=context,
        matter_id=matter_id,
    )


@router.get(
    "/{matter_id}/mock-hearings/{session_id}",
    response_model=MockHearingSessionRecord,
    summary="Get one mock hearing session",
)
async def get_current_company_matter_mock_hearing(
    matter_id: str,
    session_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MockHearingSessionRecord:
    from caseops_api.services.mock_hearing import get_mock_hearing

    return get_mock_hearing(
        session,
        context=context,
        matter_id=matter_id,
        session_id=session_id,
    )


@router.get(
    "/{matter_id}/hearing-coach",
    response_model=HearingCoachStatusResponse,
    summary="LI-S13 transcript-first hearing coach readiness",
)
async def get_current_company_matter_hearing_coach(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> HearingCoachStatusResponse:
    from caseops_api.services.hearing_coach import get_hearing_coach_status

    return get_hearing_coach_status(
        session,
        context=context,
        matter_id=matter_id,
    )


@router.post(
    "/{matter_id}/mock-hearings/{session_id}/coach",
    response_model=HearingCoachReportResponse,
    summary="LI-S13 generate consent-gated transcript-first hearing coach report",
)
async def post_current_company_matter_mock_hearing_coach(
    matter_id: str,
    session_id: str,
    payload: HearingCoachRunRequest,
    context: HearingPackGenerator,
    session: DbSession,
) -> HearingCoachReportResponse:
    from caseops_api.services.hearing_coach import generate_hearing_coach_report

    return generate_hearing_coach_report(
        session,
        context=context,
        matter_id=matter_id,
        session_id=session_id,
        payload=payload,
    )


@router.post(
    "/{matter_id}/mock-hearings/{session_id}/responses",
    response_model=MockHearingSessionRecord,
    summary="Record a typed mock hearing response and deterministic feedback",
)
async def post_current_company_matter_mock_hearing_response(
    matter_id: str,
    session_id: str,
    payload: MockHearingResponseCreateRequest,
    context: HearingPackGenerator,
    session: DbSession,
) -> MockHearingSessionRecord:
    from caseops_api.services.mock_hearing import record_mock_hearing_response

    return record_mock_hearing_response(
        session,
        context=context,
        matter_id=matter_id,
        session_id=session_id,
        payload=payload,
    )


@router.post(
    "/{matter_id}/mock-hearings/{session_id}/complete",
    response_model=MockHearingSessionRecord,
    summary="Complete a mock hearing session",
)
async def post_current_company_matter_mock_hearing_complete(
    matter_id: str,
    session_id: str,
    context: HearingPackGenerator,
    session: DbSession,
) -> MockHearingSessionRecord:
    from caseops_api.services.mock_hearing import complete_mock_hearing

    return complete_mock_hearing(
        session,
        context=context,
        matter_id=matter_id,
        session_id=session_id,
    )


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
    return generate_matter_summary(session, context=context, matter_id=matter_id)


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
    # EG-005 (2026-04-23): the service caches on the matter row.
    # GET / DOCX / PDF reuse the cached payload; this POST forces a
    # fresh LLM call and overwrites the cache.
    return generate_matter_summary(
        session, context=context, matter_id=matter_id, force_refresh=True
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
    summary = generate_matter_summary(session, context=context, matter_id=matter_id)
    timeline = build_matter_timeline_by_id(session=session, context=context, matter_id=matter_id)
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
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
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
    summary = generate_matter_summary(session, context=context, matter_id=matter_id)
    timeline = build_matter_timeline_by_id(session=session, context=context, matter_id=matter_id)
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


# PG-004 (2026-05-01) — per-matter Next-action card.
class NextActionResponse(BaseModel):
    kind: str  # "hearing" | "task" | "draft" | "invoice" | "deadline"
    label: str
    detail: str
    severity: str  # "urgent" | "soon" | "normal"
    href: str
    due_on_iso: str | None = None


@router.get(
    "/{matter_id}/next-action",
    response_model=NextActionResponse | None,
    summary=(
        "Highest-priority item demanding attention on this matter "
        "(PG-004, 2026-05-01). Returns null when nothing is queued."
    ),
)
async def get_matter_next_action(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> NextActionResponse | None:
    # Tenant scoping is enforced inside build_matter_next_action via
    # Matter.company_id checks on every join. We don't pre-load the
    # matter here — a matter that doesn't belong to the tenant just
    # produces zero candidates and returns null.
    action = build_matter_next_action(
        session,
        context=context,
        matter_id=matter_id,
    )
    if action is None:
        return None
    return NextActionResponse(
        kind=action.kind,
        label=action.label,
        detail=action.detail,
        severity=action.severity,
        href=action.href,
        due_on_iso=action.due_on_iso,
    )


# PG-005 Sprint 6 (2026-05-01) — draft revision compare response shape.
class DraftDiffLineResponse(BaseModel):
    kind: str  # "equal" | "insert" | "delete" | "replace"
    prev_line_number: int | None = None
    next_line_number: int | None = None
    text: str


class DraftDiffHunkResponse(BaseModel):
    prev_start: int
    prev_length: int
    next_start: int
    next_length: int
    lines: list[DraftDiffLineResponse]


class DraftCompareResponse(BaseModel):
    draft_id: str
    prev_revision: int
    next_revision: int
    prev_version_id: str
    next_version_id: str
    hunks: list[DraftDiffHunkResponse]
    citations_added: list[str]
    citations_removed: list[str]
    citations_kept: list[str]
    lines_added: int
    lines_removed: int
    summary: str


@router.get(
    "/{matter_id}/drafts/{draft_id}/compare",
    response_model=DraftCompareResponse,
    summary=(
        "Structured diff between two revisions of the same draft (PG-005 Sprint 6, 2026-05-01)."
    ),
)
async def get_current_company_matter_draft_compare(
    matter_id: str,
    draft_id: str,
    prev_revision: int,
    next_revision: int,
    context: CurrentContext,
    session: DbSession,
    context_lines: int = 3,
) -> DraftCompareResponse:
    """Returns line-level diff hunks + citation deltas between two
    versions of the same draft. Pure-function compute (no LLM call).
    Use ``?prev_revision=N&next_revision=M&context_lines=K``.
    """
    if context_lines < 0 or context_lines > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="context_lines must be between 0 and 10.",
        )
    result: DraftCompareResult = compare_versions_in_db(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        prev_revision=prev_revision,
        next_revision=next_revision,
        context_lines=context_lines,
    )
    return DraftCompareResponse(
        draft_id=result.draft_id,
        prev_revision=result.prev_revision,
        next_revision=result.next_revision,
        prev_version_id=result.prev_version_id,
        next_version_id=result.next_version_id,
        hunks=[
            DraftDiffHunkResponse(
                prev_start=h.prev_start,
                prev_length=h.prev_length,
                next_start=h.next_start,
                next_length=h.next_length,
                lines=[
                    DraftDiffLineResponse(
                        kind=ln.kind,
                        prev_line_number=ln.prev_line_number,
                        next_line_number=ln.next_line_number,
                        text=ln.text,
                    )
                    for ln in h.lines
                ],
            )
            for h in result.hunks
        ],
        citations_added=result.citations_added,
        citations_removed=result.citations_removed,
        citations_kept=result.citations_kept,
        lines_added=result.lines_added,
        lines_removed=result.lines_removed,
        summary=result.summary,
    )


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
    dc = suggest_bench_for_matter_id(session=session, context=context, matter_id=matter_id)
    return _bench_suggestion_to_response(dc)


# BAAD-001 slice 4 (Sprint P5, 2026-04-25). Bench strategy context
# read endpoint. Same auth + tenancy gate as the rest of /api/matters.
class BenchContextCitableAuthorityResponse(BaseModel):
    id: str
    title: str
    decision_date: str | None
    case_reference: str | None
    neutral_citation: str | None
    bench_name: str | None
    forum_level: str | None
    structured_match: bool


class BenchContextJudgeCandidateResponse(BaseModel):
    judge_id: str
    full_name: str
    structured_authority_count: int
    fallback_authority_count: int


class BenchContextPracticeAreaPatternResponse(BaseModel):
    area: str
    authority_count: int
    sample_authority_ids: list[str]


class BenchContextRecurringTestResponse(BaseModel):
    phrase: str
    occurrences: int
    sample_authority_ids: list[str]


class BenchContextCitedAuthorityResponse(BaseModel):
    citation: str
    occurrences: int


class BenchSpecificAuthorityResponse(BaseModel):
    """Slice C (MOD-TS-001-D) — authority authored by the SPECIFIC
    bench resolved for the matter's next listing."""

    id: str
    title: str
    decision_date: str | None
    case_reference: str | None
    neutral_citation: str | None
    bench_name: str | None
    forum_level: str | None
    matched_judge_ids: list[str]
    relevance: str  # 'practice_area' | 'general'


class PredictiveSummaryResponse(BaseModel):
    sample_size: int
    favorable_count: int
    adverse_count: int
    neutral_count: int
    top_outcome_label: str | None
    practice_area_key: str


class BenchStrategyContextResponse(BaseModel):
    matter_id: str
    court_name: str | None
    structured_match_coverage_percent: int
    context_quality: str
    judge_candidates: list[BenchContextJudgeCandidateResponse]
    similar_authorities: list[BenchContextCitableAuthorityResponse]
    practice_area_patterns: list[BenchContextPracticeAreaPatternResponse]
    recurring_tests: list[BenchContextRecurringTestResponse]
    authorities_frequently_cited: list[BenchContextCitedAuthorityResponse]
    drafting_cautions: list[str]
    unsupported_gaps: list[str]
    # Slice C (MOD-TS-001-D, 2026-04-25). Bench-specific block.
    bench_specific_authorities: list[BenchSpecificAuthorityResponse] = Field(default_factory=list)
    bench_specific_limitation_note: str | None = None
    # Echo of the resolved next-listing ID so the UI knows which
    # listing the bench-specific block was anchored to. None when the
    # caller didn't pass one or when no upcoming listing exists.
    next_listing_id: str | None = None
    # PG-107 (2026-05-01) — tenant policy gate. "evidence_only" by default;
    # "predictive" when the workspace has opted in to predictive bench
    # analytics. UI surfaces a mode badge + disclaimer when predictive.
    mode: str = "evidence_only"
    disclaimer: str | None = None
    # PG-107 v2 (2026-05-01) — descriptive stats on the bench's
    # indexed decisions; emitted only when mode=predictive AND
    # sample_size ≥5.
    predictive_summary: PredictiveSummaryResponse | None = None


@router.get(
    "/{matter_id}/bench-strategy-context",
    response_model=BenchStrategyContextResponse,
    summary=(
        "Evidence-cited bench history context for the matter. "
        "Read-only. Used by the appeal-drafting flow + UI context "
        "card. No favorability scoring."
    ),
)
async def get_current_company_matter_bench_strategy_context(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
    judge_limit: int = 5,
    authority_limit: int = 12,
) -> BenchStrategyContextResponse:
    from datetime import date as _date

    from caseops_api.db.models import Matter, MatterCauseListEntry
    from caseops_api.services.bench_strategy_context import (
        build_bench_strategy_context,
    )

    # Resolve the matter's next upcoming listing so the service can
    # pull bench-specific authorities (Slice C). Tenancy is enforced
    # inside build_bench_strategy_context (matter scoped to caller's
    # company); we only read the listing_id here.
    next_listing_id = session.scalar(
        select(MatterCauseListEntry.id)
        .join(Matter, Matter.id == MatterCauseListEntry.matter_id)
        .where(MatterCauseListEntry.matter_id == matter_id)
        .where(Matter.company_id == context.company.id)
        .where(MatterCauseListEntry.listing_date >= _date.today())
        .order_by(MatterCauseListEntry.listing_date.asc())
        .limit(1)
    )

    ctx = build_bench_strategy_context(
        session=session,
        context=context,
        matter_id=matter_id,
        judge_limit=judge_limit,
        authority_limit=authority_limit,
        next_listing_id=next_listing_id,
    )
    return BenchStrategyContextResponse(
        matter_id=ctx.matter_id,
        court_name=ctx.court_name,
        structured_match_coverage_percent=ctx.structured_match_coverage_percent,
        context_quality=ctx.context_quality,
        judge_candidates=[
            BenchContextJudgeCandidateResponse(
                judge_id=j.judge_id,
                full_name=j.full_name,
                structured_authority_count=j.structured_authority_count,
                fallback_authority_count=j.fallback_authority_count,
            )
            for j in ctx.judge_candidates
        ],
        similar_authorities=[
            BenchContextCitableAuthorityResponse(
                id=a.id,
                title=a.title,
                decision_date=a.decision_date,
                case_reference=a.case_reference,
                neutral_citation=a.neutral_citation,
                bench_name=a.bench_name,
                forum_level=a.forum_level,
                structured_match=a.structured_match,
            )
            for a in ctx.similar_authorities
        ],
        practice_area_patterns=[
            BenchContextPracticeAreaPatternResponse(
                area=p.area,
                authority_count=p.authority_count,
                sample_authority_ids=list(p.sample_authority_ids),
            )
            for p in ctx.practice_area_patterns
        ],
        recurring_tests=[
            BenchContextRecurringTestResponse(
                phrase=t.phrase,
                occurrences=t.occurrences,
                sample_authority_ids=list(t.sample_authority_ids),
            )
            for t in ctx.recurring_tests
        ],
        authorities_frequently_cited=[
            BenchContextCitedAuthorityResponse(
                citation=c.citation,
                occurrences=c.occurrences,
            )
            for c in ctx.authorities_frequently_cited
        ],
        drafting_cautions=list(ctx.drafting_cautions),
        unsupported_gaps=list(ctx.unsupported_gaps),
        bench_specific_authorities=[
            BenchSpecificAuthorityResponse(
                id=ba.id,
                title=ba.title,
                decision_date=ba.decision_date,
                case_reference=ba.case_reference,
                neutral_citation=ba.neutral_citation,
                bench_name=ba.bench_name,
                forum_level=ba.forum_level,
                matched_judge_ids=list(ba.matched_judge_ids),
                relevance=ba.relevance,
            )
            for ba in (ctx.bench_specific_authorities or [])
        ],
        bench_specific_limitation_note=ctx.bench_specific_limitation_note,
        next_listing_id=next_listing_id,
        mode=ctx.mode,
        disclaimer=ctx.disclaimer,
        predictive_summary=(
            PredictiveSummaryResponse(
                sample_size=ctx.predictive_summary.sample_size,
                favorable_count=ctx.predictive_summary.favorable_count,
                adverse_count=ctx.predictive_summary.adverse_count,
                neutral_count=ctx.predictive_summary.neutral_count,
                top_outcome_label=ctx.predictive_summary.top_outcome_label,
                practice_area_key=ctx.predictive_summary.practice_area_key,
            )
            if ctx.predictive_summary is not None
            else None
        ),
    )


# MOD-TS-018 (2026-04-26). Bench-Strategy Phase 4 read endpoint.
# Surfaces L-A/L-B/L-C analysis layers as a tenant-scoped per-matter
# read. Citation-grounded view first; predictive layer (judge tendencies
# + predicted_disposition) lands when L-E ships.


class BenchStrategyAuthorityResponse(BaseModel):
    authority_id: str
    title: str | None
    citation_count: int
    last_year: int | None
    sample_judgment_id: str | None


class BenchStrategyStatuteResponse(BaseModel):
    statute_section_id: str
    statute_id: str
    section_number: str
    section_label: str | None
    citation_count: int
    last_year: int | None
    sample_judgment_id: str | None


class BenchStrategyResponse(BaseModel):
    matter_id: str
    bench_judge_ids: list[str]
    total_decisions_indexed: int
    evidence_quality: str
    top_authorities: list[BenchStrategyAuthorityResponse]
    top_statute_sections: list[BenchStrategyStatuteResponse]
    disclaimer: str


@router.get(
    "/{matter_id}/bench-strategy",
    response_model=BenchStrategyResponse,
    summary=(
        "Bench-strategy panel data for the matter (MOD-TS-018). "
        "Returns top authorities + top statute sections that the "
        "matter's bench has cited, plus an evidence_quality chip and "
        "a not-legal-advice disclaimer. Tenant-scoped via matter_id."
    ),
)
async def get_current_company_matter_bench_strategy(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
    authority_limit: int = 10,
    statute_limit: int = 10,
) -> BenchStrategyResponse:
    from caseops_api.services.bench_strategy import build_bench_strategy

    payload = build_bench_strategy(
        session=session,
        matter_id=matter_id,
        company_id=context.company.id,
        authority_limit=authority_limit,
        statute_limit=statute_limit,
    )
    return BenchStrategyResponse(
        matter_id=payload.matter_id,
        bench_judge_ids=list(payload.bench_judge_ids),
        total_decisions_indexed=payload.total_decisions_indexed,
        evidence_quality=payload.evidence_quality,
        top_authorities=[
            BenchStrategyAuthorityResponse(
                authority_id=a.authority_id,
                title=a.title,
                citation_count=a.citation_count,
                last_year=a.last_year,
                sample_judgment_id=a.sample_judgment_id,
            )
            for a in payload.top_authorities
        ],
        top_statute_sections=[
            BenchStrategyStatuteResponse(
                statute_section_id=s.statute_section_id,
                statute_id=s.statute_id,
                section_number=s.section_number,
                section_label=s.section_label,
                citation_count=s.citation_count,
                last_year=s.last_year,
                sample_judgment_id=s.sample_judgment_id,
            )
            for s in payload.top_statute_sections
        ],
        disclaimer=payload.disclaimer,
    )


@router.get(
    "/{matter_id}/predictive-intelligence",
    response_model=PredictiveIntelligenceResponse,
    summary=(
        "Controlled predictive litigation intelligence for a visible matter. "
        "Requires tenant opt-in and source-backed confidence bands."
    ),
)
async def get_current_company_matter_predictive_intelligence(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> PredictiveIntelligenceResponse:
    from caseops_api.services.predictive_intelligence import (
        build_predictive_intelligence,
    )

    return build_predictive_intelligence(
        session,
        context=context,
        matter_id=matter_id,
    )


# MOD-TS-001-A (Sprint P, 2026-04-25). Appeal Strength Analyzer.
# Per-ground argument-completeness analysis. Frame is "argument
# completeness", NOT outcome prediction. No win/lose/probability/
# favourable/tendency language — enforced structurally in the service.
class AppealStrengthAuthorityRefResponse(BaseModel):
    citation: str
    resolved_authority_id: str | None = None
    title: str | None = None
    forum_level: str | None = None
    strength_label: str  # binding | peer | persuasive | unknown


class AppealStrengthGroundResponse(BaseModel):
    ordinal: int
    summary: str
    citation_coverage: str  # supported | partial | uncited
    supporting_authorities: list[AppealStrengthAuthorityRefResponse]
    bench_history_match_count: int
    suggestions: list[str]


class AppealStrengthReportResponse(BaseModel):
    matter_id: str
    draft_id: str | None = None
    overall_strength: str  # strong | moderate | weak
    bench_context_quality: str
    has_draft: bool
    ground_assessments: list[AppealStrengthGroundResponse]
    weak_evidence_paths: list[str]
    recommended_edits: list[str]
    # PG-107 (2026-05-01) — tenant policy gate echo.
    mode: str = "evidence_only"
    disclaimer: str | None = None


@router.get(
    "/{matter_id}/appeal-strength",
    response_model=AppealStrengthReportResponse,
    summary=(
        "Per-ground argument-completeness analysis for an appeal "
        "draft. Frame: argument completeness, not outcome prediction. "
        "Strict no-favorability rule applies."
    ),
)
async def get_current_company_matter_appeal_strength(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
    draft_id: str | None = None,
) -> AppealStrengthReportResponse:
    from caseops_api.services.appeal_strength import (
        analyze_appeal_strength,
    )

    rep = analyze_appeal_strength(
        session=session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
    )
    return AppealStrengthReportResponse(
        matter_id=rep.matter_id,
        draft_id=rep.draft_id,
        overall_strength=rep.overall_strength,
        bench_context_quality=rep.bench_context_quality,
        has_draft=rep.has_draft,
        ground_assessments=[
            AppealStrengthGroundResponse(
                ordinal=g.ordinal,
                summary=g.summary,
                citation_coverage=g.citation_coverage,
                supporting_authorities=[
                    AppealStrengthAuthorityRefResponse(
                        citation=ref.citation,
                        resolved_authority_id=ref.resolved_authority_id,
                        title=ref.title,
                        forum_level=ref.forum_level,
                        strength_label=ref.strength_label,
                    )
                    for ref in g.supporting_authorities
                ],
                bench_history_match_count=g.bench_history_match_count,
                suggestions=list(g.suggestions),
            )
            for g in rep.ground_assessments
        ],
        weak_evidence_paths=list(rep.weak_evidence_paths),
        recommended_edits=list(rep.recommended_edits),
        mode=rep.mode,
        disclaimer=rep.disclaimer,
    )


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


@router.patch(
    "/{matter_id}/lifecycle/status",
    response_model=MatterRecord,
    summary="Dispose or reopen a matter with concurrency guards",
)
async def patch_current_company_matter_lifecycle_status(
    matter_id: str,
    payload: MatterLifecycleStatusRequest,
    context: MatterArchiver,
    session: DbSession,
) -> MatterRecord:
    return transition_matter_lifecycle_status(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


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


@router.get(
    "/{matter_id}/tasks",
    response_model=MatterTaskListResponse,
    summary="List matter tasks",
)
async def get_current_company_matter_tasks(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
    include_completed: bool = Query(True),
) -> MatterTaskListResponse:
    return MatterTaskListResponse(
        matter_id=matter_id,
        tasks=list_matter_tasks(
            session,
            context=context,
            matter_id=matter_id,
            include_completed=include_completed,
        ),
    )


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


@router.get(
    "/{matter_id}/deadlines",
    response_model=MatterDeadlineListResponse,
    summary="List matter deadlines",
)
async def get_current_company_matter_deadlines(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
    include_done: bool = Query(True),
) -> MatterDeadlineListResponse:
    return MatterDeadlineListResponse(
        matter_id=matter_id,
        deadlines=list_deadline_records(
            session,
            context=context,
            matter_id=matter_id,
            include_done=include_done,
        ),
    )


@router.post(
    "/{matter_id}/deadlines",
    response_model=MatterDeadlineRecord,
    summary="Create a matter deadline",
)
async def post_current_company_matter_deadline(
    matter_id: str,
    payload: MatterDeadlineCreateRequest,
    context: MatterWriter,
    session: DbSession,
) -> MatterDeadlineRecord:
    deadline = create_deadline(
        session,
        context=context,
        matter_id=matter_id,
        source=payload.source,
        kind=payload.kind,
        title=payload.title,
        due_on=payload.due_on,
        notes=payload.notes,
        assignee_membership_id=payload.assignee_membership_id,
    )
    return deadline_record(deadline)


@router.patch(
    "/{matter_id}/deadlines/{deadline_id}",
    response_model=MatterDeadlineRecord,
    summary="Update a matter deadline",
)
async def patch_current_company_matter_deadline(
    matter_id: str,
    deadline_id: str,
    payload: MatterDeadlineUpdateRequest,
    context: MatterWriter,
    session: DbSession,
) -> MatterDeadlineRecord:
    return deadline_record(
        update_deadline(
            session,
            context=context,
            matter_id=matter_id,
            deadline_id=deadline_id,
            payload=payload,
        )
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


@router.get(
    "/{matter_id}/next-hearing/history",
    response_model=MatterNextHearingHistoryResponse,
    summary="List next-hearing provenance history and review suggestions",
)
async def get_current_company_matter_next_hearing_history(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterNextHearingHistoryResponse:
    history, suggestions = list_next_hearing_history(
        session,
        context=context,
        matter_id=matter_id,
    )
    return MatterNextHearingHistoryResponse(history=history, suggestions=suggestions)


@router.post(
    "/{matter_id}/next-hearing/suggestions/{suggestion_id}",
    response_model=MatterNextHearingHistoryResponse,
    summary="Accept or reject a next-hearing review suggestion",
)
async def decide_current_company_matter_next_hearing_suggestion(
    matter_id: str,
    suggestion_id: str,
    payload: MatterNextHearingSuggestionActionRequest,
    context: MatterWriter,
    session: DbSession,
) -> MatterNextHearingHistoryResponse:
    decide_next_hearing_suggestion(
        session,
        context=context,
        matter_id=matter_id,
        suggestion_id=suggestion_id,
        action=payload.action,
    )
    history, suggestions = list_next_hearing_history(
        session,
        context=context,
        matter_id=matter_id,
    )
    return MatterNextHearingHistoryResponse(history=history, suggestions=suggestions)


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
    "/{matter_id}/court-orders",
    response_model=MatterCourtOrderRecord,
    summary=(
        "Create a court order on a matter manually (BUG-032). "
        "Optional pre-uploaded attachment is referenced by ID."
    ),
)
async def post_current_company_matter_court_order(
    matter_id: str,
    payload: MatterCourtOrderCreateRequest,
    context: MatterEditor,
    session: DbSession,
) -> MatterCourtOrderRecord:
    """Manual create path for ``MatterCourtOrder``. Mirrors the
    PATCH endpoint's tenant + matter-access guard via the
    ``MatterEditor`` capability and the
    ``_get_matter_model`` helper inside the service. Optional file
    upload is handled by calling the existing
    ``POST /api/matters/{matter_id}/attachments`` first and passing
    the resulting attachment ID as ``order_attachment_id`` in this
    request body — keeps file validation, ClamAV scan, and
    storage-backend handling in one place.
    """
    return create_matter_court_order(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


@router.patch(
    "/{matter_id}/court-orders/{order_id}",
    response_model=MatterCourtOrderRecord,
    summary="Update court order metadata, interim flag, and stay status",
)
async def patch_current_company_matter_court_order(
    matter_id: str,
    order_id: str,
    payload: MatterCourtOrderUpdateRequest,
    context: MatterEditor,
    session: DbSession,
) -> MatterCourtOrderRecord:
    return update_matter_court_order(
        session,
        context=context,
        matter_id=matter_id,
        order_id=order_id,
        payload=payload,
    )


@router.get(
    "/{matter_id}/compliance",
    response_model=ComplianceListResponse,
    summary="List review-required court-order compliance items for a matter",
)
async def get_current_company_matter_compliance(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> ComplianceListResponse:
    runs, items = list_compliance(session, context=context, matter_id=matter_id)
    return ComplianceListResponse(runs=runs, items=items)


@router.patch(
    "/{matter_id}/compliance/{item_id}",
    response_model=ComplianceListResponse,
    summary="Confirm, reject, waive, complete, or edit a compliance item",
)
async def patch_current_company_matter_compliance_item(
    matter_id: str,
    item_id: str,
    payload: ComplianceItemUpdateRequest,
    context: MatterWriter,
    session: DbSession,
) -> ComplianceListResponse:
    update_compliance_item(
        session,
        context=context,
        matter_id=matter_id,
        item_id=item_id,
        action=payload.action,
        updates=payload.model_dump(exclude_unset=True, exclude={"action"}),
    )
    runs, items = list_compliance(session, context=context, matter_id=matter_id)
    return ComplianceListResponse(runs=runs, items=items)


@router.post(
    "/{matter_id}/court-orders/{order_id}/compliance/retry",
    response_model=ComplianceRetryResponse,
    summary="Retry compliance extraction for a court order",
)
async def retry_current_company_matter_order_compliance(
    matter_id: str,
    order_id: str,
    context: MatterWriter,
    session: DbSession,
) -> ComplianceRetryResponse:
    run, items = retry_order_compliance_extraction(
        session,
        context=context,
        matter_id=matter_id,
        order_id=order_id,
    )
    return ComplianceRetryResponse(
        run=_run_record(run),
        items=[_item_record(item) for item in items],
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


@router.get(
    "/{matter_id}/invoices/{invoice_id}/download",
    summary="Download a server-rendered matter invoice PDF",
)
async def download_current_company_matter_invoice_pdf(
    matter_id: str,
    invoice_id: str,
    context: InvoiceIssuer,
    session: DbSession,
) -> Response:
    body, filename, checksum = get_matter_invoice_pdf(
        session,
        context=context,
        matter_id=matter_id,
        invoice_id=invoice_id,
    )
    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-CaseOps-Checksum": checksum,
        },
    )


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
    document_type: Annotated[MatterDocumentTypeLiteral | None, Form()] = None,
    lifecycle_stage: Annotated[MatterLifecycleStageLiteral | None, Form()] = None,
    document_date: Annotated[date | None, Form()] = None,
    notice_source: Annotated[str | None, Form(max_length=255)] = None,
    notice_subject: Annotated[str | None, Form(max_length=500)] = None,
    notice_received_on: Annotated[date | None, Form()] = None,
    notice_response: Annotated[str | None, Form(max_length=4000)] = None,
    notice_direction: Annotated[str | None, Form(max_length=16)] = None,
    notice_type: Annotated[str | None, Form(max_length=120)] = None,
    notice_mode: Annotated[str | None, Form(max_length=80)] = None,
    notice_authority: Annotated[str | None, Form(max_length=255)] = None,
    notice_received_from: Annotated[str | None, Form(max_length=120)] = None,
    notice_summary: Annotated[str | None, Form(max_length=6000)] = None,
    notice_remarks: Annotated[str | None, Form(max_length=4000)] = None,
    notice_status: Annotated[str | None, Form(max_length=80)] = None,
    notice_department: Annotated[str | None, Form(max_length=160)] = None,
    notice_internal_spoc: Annotated[str | None, Form(max_length=160)] = None,
    notice_internal_remarks: Annotated[str | None, Form(max_length=4000)] = None,
    notice_amount_minor: Annotated[int | None, Form(ge=0)] = None,
    notice_dispute_amount_minor: Annotated[int | None, Form(ge=0)] = None,
    notice_recovered_amount_minor: Annotated[int | None, Form(ge=0)] = None,
    notice_currency: Annotated[str | None, Form(min_length=3, max_length=3)] = None,
    notice_reply_due_on: Annotated[date | None, Form()] = None,
    notice_reply_required: Annotated[bool | None, Form()] = None,
    notice_reply_sent: Annotated[bool | None, Form()] = None,
    notice_reply_sent_on: Annotated[date | None, Form()] = None,
    notice_sent_on: Annotated[date | None, Form()] = None,
    notice_counsel_engaged: Annotated[str | None, Form(max_length=255)] = None,
    notice_parent_attachment_id: Annotated[str | None, Form(max_length=36)] = None,
    notice_document_role: Annotated[str | None, Form(max_length=24)] = None,
    sequence_index: Annotated[int | None, Form(ge=0)] = None,
    linked_court_order_id: Annotated[str | None, Form(max_length=36)] = None,
    hearing_id: Annotated[str | None, Form(max_length=36)] = None,
) -> MatterAttachmentRecord:
    attachment, job_id = create_matter_attachment(
        session,
        context=context,
        matter_id=matter_id,
        filename=file.filename or "document",
        content_type=file.content_type,
        stream=file.file,
        document_type=document_type,
        lifecycle_stage=lifecycle_stage,
        document_date=document_date,
        notice_source=notice_source,
        notice_subject=notice_subject,
        notice_received_on=notice_received_on,
        notice_response=notice_response,
        notice_direction=notice_direction,
        notice_type=notice_type,
        notice_mode=notice_mode,
        notice_authority=notice_authority,
        notice_received_from=notice_received_from,
        notice_summary=notice_summary,
        notice_remarks=notice_remarks,
        notice_status=notice_status,
        notice_department=notice_department,
        notice_internal_spoc=notice_internal_spoc,
        notice_internal_remarks=notice_internal_remarks,
        notice_amount_minor=notice_amount_minor,
        notice_dispute_amount_minor=notice_dispute_amount_minor,
        notice_recovered_amount_minor=notice_recovered_amount_minor,
        notice_currency=notice_currency,
        notice_reply_due_on=notice_reply_due_on,
        notice_reply_required=notice_reply_required,
        notice_reply_sent=notice_reply_sent,
        notice_reply_sent_on=notice_reply_sent_on,
        notice_sent_on=notice_sent_on,
        notice_counsel_engaged=notice_counsel_engaged,
        notice_parent_attachment_id=notice_parent_attachment_id,
        notice_document_role=notice_document_role,
        sequence_index=sequence_index,
        linked_court_order_id=linked_court_order_id,
        hearing_id=hearing_id,
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.patch(
    "/{matter_id}/attachments/{attachment_id}/metadata",
    response_model=MatterAttachmentRecord,
    summary="Update document lifecycle metadata for a matter attachment",
)
async def patch_current_company_matter_attachment_metadata(
    matter_id: str,
    attachment_id: str,
    payload: MatterAttachmentMetadataUpdateRequest,
    context: DocumentManager,
    session: DbSession,
) -> MatterAttachmentRecord:
    return update_matter_attachment_metadata(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
        payload=payload,
    )


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
    "/{matter_id}/attachments/bulk-download",
    response_class=Response,
    summary="Download selected matter attachments as a ZIP archive",
)
async def download_current_company_matter_attachments_bulk(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
    attachment_ids: Annotated[list[str], Query(min_length=1)],
) -> Response:
    archive_body, filename, attachment_count = get_matter_attachment_bulk_download(
        session,
        context=context,
        matter_id=matter_id,
        attachment_ids=attachment_ids,
    )
    return Response(
        content=archive_body,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-CaseOps-Attachment-Count": str(attachment_count),
        },
    )


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
    "/{matter_id}/drafting-data/extract",
    response_model=DraftingDataExtractionResponse,
    summary="Extract drafting data suggestions from existing matter documents",
    description=(
        "Deterministic, matter-scoped dry extraction from already-indexed or "
        "extracted uploaded document text. This does not read storage objects, "
        "run OCR, run embeddings, or call an LLM. Suggested fields require "
        "lawyer review before draft generation can use them."
    ),
)
async def post_current_company_matter_drafting_data_extract(
    matter_id: str,
    context: DraftEditor,
    session: DbSession,
) -> DraftingDataExtractionResponse:
    return extract_drafting_data(session, context=context, matter_id=matter_id)


@router.get(
    "/{matter_id}/drafting-data",
    response_model=DraftingDataExtractionResponse,
    summary="List reviewed drafting data suggestions for a matter",
)
async def get_current_company_matter_drafting_data(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> DraftingDataExtractionResponse:
    return list_drafting_data(session, context=context, matter_id=matter_id)


@router.patch(
    "/{matter_id}/drafting-data/{field_id}",
    response_model=DraftingDataFieldRecord,
    summary="Confirm, override, or reject a drafting data suggestion",
)
async def patch_current_company_matter_drafting_data_field(
    matter_id: str,
    field_id: str,
    payload: DraftingDataReviewRequest,
    context: DraftEditor,
    session: DbSession,
) -> DraftingDataFieldRecord:
    return review_drafting_data_field(
        session,
        context=context,
        matter_id=matter_id,
        field_id=field_id,
        payload=payload,
    )


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
    draft = get_draft(session, context=context, matter_id=matter_id, draft_id=draft_id)
    return DraftRecord.model_validate(load_draft_record(draft))


@router.patch(
    "/{matter_id}/drafts/{draft_id}",
    response_model=DraftRecord,
    summary="Save manual edits as a new draft revision",
    description=(
        "Creates a new version from the lawyer-edited body, keeps finalized "
        "drafts immutable, and resets review_required so any prior approval "
        "does not silently carry over to changed text."
    ),
)
async def patch_current_company_matter_draft(
    matter_id: str,
    draft_id: str,
    payload: DraftEditRequest,
    context: DraftEditor,
    session: DbSession,
) -> DraftRecord:
    draft = edit_draft_version(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        body=payload.body,
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
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{matter_id}/drafts/{draft_id}/export.pdf",
    summary="Download the current (or a specific) draft version as filing-grade PDF",
)
async def get_current_company_matter_draft_pdf(
    matter_id: str,
    draft_id: str,
    context: CurrentContext,
    session: DbSession,
    version_id: str | None = None,
    court_profile: str | None = None,
) -> Response:
    """PG-005 Sprint 3 (2026-05-01) — court-format-aware PDF export.

    The optional ``court_profile`` query param overrides the auto-
    resolution from the matter's ``court_name``. Known keys:
    ``supreme_court``, ``delhi_hc``, ``bombay_hc``, ``generic``.
    Unknown key → 422.
    """
    (
        body,
        filename,
        profile_key,
        profile_category,
        missing_required_field_count,
    ) = render_version_pdf(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        version_id=version_id,
        court_profile_key=court_profile,
    )
    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-CaseOps-Court-Profile": profile_key,
            "X-CaseOps-Court-Profile-Category": profile_category,
            "X-CaseOps-Missing-Required-Fields": str(missing_required_field_count),
        },
    )


@router.get(
    "/{matter_id}/drafts/{draft_id}/filing-bundle.zip",
    summary=(
        "Download a filing-grade ZIP bundle for the draft: index + "
        "memorandum PDF + vakalat (auto-resolved) + e-stamp placeholder "
        "+ matter exhibits"
    ),
)
async def get_current_company_matter_draft_filing_bundle(
    matter_id: str,
    draft_id: str,
    context: CurrentContext,
    session: DbSession,
    version_id: str | None = None,
    court_profile: str | None = None,
    vakalat_draft_id: str | None = None,
    attachment_ids: str | None = None,
) -> Response:
    """PG-005 Sprint 4 (2026-05-01) — court-filing bundle ZIP.

    Auto-resolves the court profile from ``Matter.court_name`` (override
    via ``court_profile``); auto-picks the newest VAKALATNAMA-typed
    draft on the same matter (override via ``vakalat_draft_id``); and
    includes every attachment on the matter (narrow via
    ``attachment_ids`` — comma-separated).
    """
    selected_attachment_ids: list[str] | None = None
    if attachment_ids:
        selected_attachment_ids = [
            a.strip() for a in attachment_ids.split(",") if a.strip()
        ] or None

    result = render_filing_bundle(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        version_id=version_id,
        court_profile_key=court_profile,
        vakalat_draft_id=vakalat_draft_id,
        attachment_ids=selected_attachment_ids,
    )

    return Response(
        content=result.zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-CaseOps-Court-Profile": result.profile_key,
            "X-CaseOps-Vakalat-Source": result.vakalat_source,
            "X-CaseOps-Exhibit-Count": str(result.exhibit_count),
        },
    )


# PG-005 Sprint 8 (2026-05-01) — pre-filing checklist response shape.
class FilingChecklistItemResponse(BaseModel):
    id: str
    label: str
    description: str
    category: str  # "document" | "fee" | "procedure" | "service"
    required: bool
    auto_satisfied: bool
    auto_satisfied_reason: str | None = None


class FilingRequiredFieldFindingResponse(BaseModel):
    key: str
    label: str
    description: str
    required: bool
    satisfied: bool
    source: str | None = None


class FilingChecklistResponse(BaseModel):
    matter_id: str
    draft_id: str
    template_type: str
    court_profile_key: str
    court_display_name: str
    items: list[FilingChecklistItemResponse]
    court_fee_note: str
    limitation_note: str | None = None
    copies_required: int
    required_field_findings: list[FilingRequiredFieldFindingResponse]
    missing_required_field_count: int


@router.get(
    "/{matter_id}/drafts/{draft_id}/filing-checklist",
    response_model=FilingChecklistResponse,
    summary=(
        "Pre-filing checklist for the draft — required documents, "
        "court fee, copies, limitation reminder (PG-005 Sprint 8, "
        "2026-05-01)."
    ),
)
async def get_current_company_matter_draft_filing_checklist(
    matter_id: str,
    draft_id: str,
    context: CurrentContext,
    session: DbSession,
    court_profile: str | None = None,
) -> FilingChecklistResponse:
    """Returns the pre-filing checklist for the draft. Optional
    ``court_profile`` overrides the auto-resolution from the matter's
    ``court_name``.
    """
    # Reuse the load helpers from the drafting service (tenant-scoped).
    from caseops_api.services.drafting import _load_draft, _load_matter

    matter = _load_matter(session, context, matter_id)
    draft = _load_draft(session, matter, draft_id)

    try:
        checklist = build_filing_checklist(
            session,
            matter_id=matter.id,
            draft=draft,
            court_profile_key=court_profile,
            court_name=matter.court_name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return FilingChecklistResponse(
        matter_id=checklist.matter_id,
        draft_id=checklist.draft_id,
        template_type=checklist.template_type,
        court_profile_key=checklist.court_profile_key,
        court_display_name=checklist.court_display_name,
        items=[
            FilingChecklistItemResponse(
                id=item.id,
                label=item.label,
                description=item.description,
                category=item.category,
                required=item.required,
                auto_satisfied=item.auto_satisfied,
                auto_satisfied_reason=item.auto_satisfied_reason,
            )
            for item in checklist.items
        ],
        court_fee_note=checklist.court_fee_note,
        limitation_note=checklist.limitation_note,
        copies_required=checklist.copies_required,
        required_field_findings=[
            FilingRequiredFieldFindingResponse(
                key=finding.key,
                label=finding.label,
                description=finding.description,
                required=finding.required,
                satisfied=finding.satisfied,
                source=finding.source,
            )
            for finding in checklist.required_field_findings
        ],
        missing_required_field_count=checklist.missing_required_field_count,
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
    matter, grants, walls = list_access_panel(session, context=context, matter_id=matter_id)
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
