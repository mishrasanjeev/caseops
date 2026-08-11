from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import ValidationError

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.core.settings import get_settings
from caseops_api.schemas.audit import IpDocketAuditListResponse
from caseops_api.schemas.ip_access import (
    RecordAccessFoundationContract,
    RecordAccessReconciliationReport,
)
from caseops_api.schemas.ip_deadlines import (
    IpDeadlineCompleteRequest,
    IpDeadlineConfirmRequest,
    IpDeadlineImpactResponse,
    IpDeadlineOverrideRequest,
    IpDeadlineProposalRequest,
    IpDeadlineRecalculateRequest,
    IpDeadlineRecord,
    IpDeadlineWorkspaceResponse,
    IpRuleActivationRequest,
    IpRuleImpactResponse,
    IpRuleTransitionRequest,
    IpRuleVersionProposalRequest,
    IpRuleVersionRecord,
    LegalCalendarActivationRequest,
    LegalCalendarVersionProposalRequest,
    LegalCalendarVersionRecord,
)
from caseops_api.schemas.ip_documents import (
    IpDocumentAddLinksRequest,
    IpDocumentAliasImportRequest,
    IpDocumentAliasImportResponse,
    IpDocumentBulkApplyRequest,
    IpDocumentBulkPreviewRequest,
    IpDocumentBulkPreviewResponse,
    IpDocumentFoundationContract,
    IpDocumentListResponse,
    IpDocumentNamingPreviewRequest,
    IpDocumentNamingPreviewResponse,
    IpDocumentNewVersionMetadata,
    IpDocumentPolicyActionRequest,
    IpDocumentPolicyActionResponse,
    IpDocumentPolicyResponse,
    IpDocumentRecord,
    IpDocumentStateTransitionRequest,
    IpDocumentTaxonomyEntryRecord,
    IpDocumentTaxonomyResponse,
    IpDocumentTaxonomyUpsertRequest,
    IpDocumentUploadMetadata,
    IpDocumentUploadResponse,
)
from caseops_api.schemas.ip_lifecycle import (
    IpDocketEventCreateRequest,
    IpDocketEventPreviewResponse,
    IpDocketEventResponse,
    IpLifecyclePreviewResponse,
    IpLifecycleTransitionRequest,
    IpLifecycleTransitionResponse,
    IpProsecutionWorkspaceResponse,
)
from caseops_api.schemas.ip_operations import (
    IpCostItemCreateRequest,
    IpCostReconciliationReport,
    IpCoverageBulkReassignRequest,
    IpCoverageBulkReassignResponse,
    IpDeadlineCoverageCreateRequest,
    IpDeadlineCoverageReassignRequest,
    IpDeadlineIncidentCreateRequest,
    IpDeadlineIncidentVerifyRequest,
    IpDocketControlReport,
    IpDocketCreateRequest,
    IpDocketListResponse,
    IpDocketRecordResponse,
    IpDocketVersionCreateRequest,
    IpEvidenceCandidateReviewRequest,
    IpEvidenceDiscoveryResponse,
    IpNoticeLinkCreateRequest,
    IpRelatedRightObligationCompleteRequest,
    IpRelatedRightObligationCreateRequest,
    IpTitleInterestCreateRequest,
    IpWorkspaceReadinessResponse,
)
from caseops_api.schemas.ip_records import (
    IpAssetCreateRequest,
    IpAssetResponse,
    IpCoreRecordResponse,
    IpIdentifierCorrectionCreate,
    IpIdentifierCreate,
    IpIdentifierMutationResponse,
    IpIdentifierResponse,
    IpProceedingCreateRequest,
    IpProceedingResponse,
    IpWorkspaceConfigurationStatusResponse,
    IpWorkspaceConfigurationUpsertRequest,
    IpWorkspaceEnableRequest,
    IpWorkspaceTestResultResponse,
    IpWorkspaceTestRunRequest,
    TrademarkApplicationCreateRequest,
    TrademarkApplicationMutationResponse,
    TrademarkApplicationPhaseUpdateRequest,
    TrademarkApplicationResponse,
)
from caseops_api.schemas.shared_work import (
    IpOperationalDeadlineCreateRequest,
    IpOperationalDeadlineListResponse,
    IpOperationalDeadlineRecord,
    IpOperationalDeadlineUpdateRequest,
    IpSharedHearingCreateRequest,
    IpSharedHearingListResponse,
    IpSharedHearingRecord,
    IpSharedHearingUpdateRequest,
    IpSharedTaskCreateRequest,
    IpSharedTaskListResponse,
    IpSharedTaskRecord,
    IpSharedTaskUpdateRequest,
    SharedWorkFoundationContract,
    SharedWorkReconciliationReport,
)
from caseops_api.services.document_jobs import run_document_processing_job
from caseops_api.services.document_storage import resolve_storage_path
from caseops_api.services.ip_audit import list_ip_docket_audit_events
from caseops_api.services.ip_capability_catalog import ip_workspace_readiness
from caseops_api.services.ip_deadline_workflow import (
    activate_calendar_version,
    activate_rule_version,
    complete_deadline,
    confirm_deadline,
    deadline_impact,
    deadline_workspace,
    override_deadline,
    propose_calendar_version,
    propose_deadline,
    propose_rule_version,
    recalculate_deadline,
    rule_impact,
    transition_rule_version,
)
from caseops_api.services.ip_document_workflow import (
    add_ip_document_links,
    apply_ip_document_bulk_update,
    authorize_ip_document_action,
    get_ip_document,
    get_ip_document_policy,
    get_ip_document_version_for_download,
    import_ip_document_aliases,
    list_ip_documents,
    preview_ip_document_bulk_update,
    transition_ip_document_state,
    upload_ip_document,
    upload_ip_document_version,
)
from caseops_api.services.ip_documents import (
    get_ip_document_taxonomy,
    ip_document_foundation_contract,
    preview_ip_document_name,
    seed_ip_document_taxonomy,
    upsert_ip_document_taxonomy_entry,
)
from caseops_api.services.ip_lifecycle import (
    append_ip_docket_event,
    get_ip_prosecution_workspace,
    list_ip_docket_events,
    preview_ip_docket_event,
    preview_ip_docket_lifecycle,
    transition_ip_docket_lifecycle,
)
from caseops_api.services.ip_operations import (
    add_ip_cost_item,
    add_ip_deadline_coverage,
    add_ip_deadline_incident,
    add_ip_notice_link,
    add_ip_related_right_obligation,
    add_ip_title_interest,
    append_ip_docket_version,
    bulk_reassign_ip_deadline_coverages,
    complete_ip_related_right_obligation,
    create_ip_docket,
    discover_ip_evidence_candidates,
    get_ip_docket,
    ip_docket_control_report,
    list_ip_dockets,
    reassign_ip_deadline_coverage,
    reconcile_ip_cost_items,
    review_ip_evidence_candidate,
    verify_ip_deadline_incident,
)
from caseops_api.services.ip_records import (
    correct_ip_identifier,
    create_ip_asset,
    create_ip_identifier,
    create_ip_proceeding,
    create_trademark_application,
    list_ip_core_records,
    search_ip_identifiers,
    update_trademark_application_phase,
)
from caseops_api.services.ip_workspace import (
    enable_ip_workspace,
    get_ip_workspace_configuration_status,
    run_ip_workspace_test,
    upsert_ip_workspace_configuration,
)
from caseops_api.services.matter_access import (
    reconcile_record_access,
    record_access_foundation_contract,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.shared_work import (
    create_ip_operational_deadline,
    create_ip_shared_hearing,
    create_ip_shared_task,
    list_ip_operational_deadlines,
    list_ip_shared_hearings,
    list_ip_shared_tasks,
    reconcile_shared_work_owners,
    shared_work_foundation_contract,
    update_ip_operational_deadline,
    update_ip_shared_hearing,
    update_ip_shared_task,
)

router = APIRouter()
IpViewer = Annotated[SessionContext, Depends(require_capability("ip:read"))]
IpWriter = Annotated[SessionContext, Depends(require_capability("ip:write"))]
IpReviewer = Annotated[SessionContext, Depends(require_capability("ip:approve"))]
IpRuleProposer = Annotated[
    SessionContext,
    Depends(require_capability("ip:rules_propose")),
]
IpRuleActivator = Annotated[
    SessionContext,
    Depends(require_capability("ip:rules_activate")),
]
IpFinance = Annotated[SessionContext, Depends(require_capability("ip:fees_manage"))]
IpWorkspaceAdmin = Annotated[
    SessionContext,
    Depends(require_capability("ip:taxonomy_admin")),
]
IpAccessManager = Annotated[
    SessionContext,
    Depends(require_capability("matter_access:manage")),
]


@router.get(
    "/shared-work/foundation-contract",
    response_model=SharedWorkFoundationContract,
)
async def get_shared_work_foundation_contract(
    context: IpViewer,
) -> SharedWorkFoundationContract:
    del context
    return shared_work_foundation_contract()


@router.get(
    "/access/foundation-contract",
    response_model=RecordAccessFoundationContract,
)
async def get_record_access_foundation_contract(
    context: IpViewer,
) -> RecordAccessFoundationContract:
    del context
    return record_access_foundation_contract()


@router.get(
    "/access/reconciliation",
    response_model=RecordAccessReconciliationReport,
)
async def get_record_access_reconciliation(
    context: IpAccessManager,
    session: DbSession,
) -> RecordAccessReconciliationReport:
    return reconcile_record_access(session, context=context)


@router.get(
    "/shared-work/reconciliation",
    response_model=SharedWorkReconciliationReport,
)
async def get_shared_work_reconciliation(
    context: IpViewer,
    session: DbSession,
) -> SharedWorkReconciliationReport:
    return reconcile_shared_work_owners(session, context=context)


@router.get("/tasks", response_model=IpSharedTaskListResponse)
async def get_ip_shared_tasks(
    context: IpViewer,
    session: DbSession,
    docket_id: Annotated[str, Query()],
    include_completed: Annotated[bool, Query()] = True,
) -> IpSharedTaskListResponse:
    return list_ip_shared_tasks(
        session,
        context=context,
        docket_id=docket_id,
        include_completed=include_completed,
    )


@router.post("/tasks", response_model=IpSharedTaskRecord, status_code=status.HTTP_201_CREATED)
async def post_ip_shared_task(
    payload: IpSharedTaskCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpSharedTaskRecord:
    return create_ip_shared_task(session, context=context, payload=payload)


@router.patch("/tasks/{task_id}", response_model=IpSharedTaskRecord)
async def patch_ip_shared_task(
    task_id: str,
    payload: IpSharedTaskUpdateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpSharedTaskRecord:
    return update_ip_shared_task(
        session, context=context, task_id=task_id, payload=payload
    )


@router.get("/hearings", response_model=IpSharedHearingListResponse)
async def get_ip_shared_hearings(
    context: IpViewer,
    session: DbSession,
    docket_id: Annotated[str, Query()],
) -> IpSharedHearingListResponse:
    return list_ip_shared_hearings(session, context=context, docket_id=docket_id)


@router.post(
    "/hearings",
    response_model=IpSharedHearingRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_shared_hearing(
    payload: IpSharedHearingCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpSharedHearingRecord:
    return create_ip_shared_hearing(session, context=context, payload=payload)


@router.patch("/hearings/{hearing_id}", response_model=IpSharedHearingRecord)
async def patch_ip_shared_hearing(
    hearing_id: str,
    payload: IpSharedHearingUpdateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpSharedHearingRecord:
    return update_ip_shared_hearing(
        session, context=context, hearing_id=hearing_id, payload=payload
    )


@router.get(
    "/operational-deadlines",
    response_model=IpOperationalDeadlineListResponse,
)
async def get_ip_operational_deadlines(
    context: IpViewer,
    session: DbSession,
    docket_id: Annotated[str, Query()],
    include_done: Annotated[bool, Query()] = False,
) -> IpOperationalDeadlineListResponse:
    return list_ip_operational_deadlines(
        session,
        context=context,
        docket_id=docket_id,
        include_done=include_done,
    )


@router.post(
    "/operational-deadlines",
    response_model=IpOperationalDeadlineRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_operational_deadline(
    payload: IpOperationalDeadlineCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpOperationalDeadlineRecord:
    return create_ip_operational_deadline(session, context=context, payload=payload)


@router.patch(
    "/operational-deadlines/{deadline_id}",
    response_model=IpOperationalDeadlineRecord,
)
async def patch_ip_operational_deadline(
    deadline_id: str,
    payload: IpOperationalDeadlineUpdateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpOperationalDeadlineRecord:
    return update_ip_operational_deadline(
        session, context=context, deadline_id=deadline_id, payload=payload
    )


@router.get(
    "/documents/foundation-contract",
    response_model=IpDocumentFoundationContract,
)
async def get_ip_document_foundation_contract(
    context: IpViewer,
) -> IpDocumentFoundationContract:
    del context
    return ip_document_foundation_contract()


@router.post(
    "/documents/naming-preview",
    response_model=IpDocumentNamingPreviewResponse,
)
async def post_ip_document_naming_preview(
    payload: IpDocumentNamingPreviewRequest,
    context: IpViewer,
) -> IpDocumentNamingPreviewResponse:
    del context
    return preview_ip_document_name(payload)


@router.get("/documents", response_model=IpDocumentListResponse)
async def get_ip_documents(
    context: IpViewer,
    session: DbSession,
) -> IpDocumentListResponse:
    return list_ip_documents(session, context=context)


@router.post("/documents/upload", response_model=IpDocumentUploadResponse)
async def post_ip_document_upload(
    background_tasks: BackgroundTasks,
    context: IpWriter,
    session: DbSession,
    metadata_json: Annotated[str, Form()],
    upload: Annotated[UploadFile, File()],
) -> IpDocumentUploadResponse:
    try:
        metadata = IpDocumentUploadMetadata.model_validate_json(metadata_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    response, job_id = upload_ip_document(
        session,
        context=context,
        metadata=metadata,
        filename=upload.filename or "document",
        content_type=upload.content_type,
        stream=upload.file,
    )
    if job_id is not None:
        background_tasks.add_task(run_document_processing_job, job_id)
    return response


@router.post("/documents/bulk-preview", response_model=IpDocumentBulkPreviewResponse)
async def post_ip_document_bulk_preview(
    payload: IpDocumentBulkPreviewRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocumentBulkPreviewResponse:
    return preview_ip_document_bulk_update(session, context=context, payload=payload)


@router.post("/documents/bulk-apply", response_model=IpDocumentListResponse)
async def post_ip_document_bulk_apply(
    payload: IpDocumentBulkApplyRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocumentListResponse:
    return apply_ip_document_bulk_update(session, context=context, payload=payload)


@router.get("/documents/{document_id}", response_model=IpDocumentRecord)
async def get_ip_document_route(
    document_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpDocumentRecord:
    return get_ip_document(session, context=context, document_id=document_id)


@router.post("/documents/{document_id}/links", response_model=IpDocumentRecord)
async def post_ip_document_links(
    document_id: str,
    payload: IpDocumentAddLinksRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocumentRecord:
    return add_ip_document_links(
        session,
        context=context,
        document_id=document_id,
        payload=payload,
    )


@router.get("/documents/{document_id}/policy", response_model=IpDocumentPolicyResponse)
async def get_ip_document_policy_route(
    document_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpDocumentPolicyResponse:
    return get_ip_document_policy(session, context=context, document_id=document_id)


@router.post(
    "/documents/{document_id}/authorize-action",
    response_model=IpDocumentPolicyActionResponse,
)
async def post_ip_document_authorize_action(
    document_id: str,
    payload: IpDocumentPolicyActionRequest,
    context: IpViewer,
    session: DbSession,
) -> IpDocumentPolicyActionResponse:
    return authorize_ip_document_action(
        session,
        context=context,
        document_id=document_id,
        payload=payload,
    )


@router.post(
    "/documents/{document_id}/versions/{version_number}/transition",
    response_model=IpDocumentRecord,
)
async def post_ip_document_state_transition(
    document_id: str,
    version_number: int,
    payload: IpDocumentStateTransitionRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocumentRecord:
    return transition_ip_document_state(
        session,
        context=context,
        document_id=document_id,
        version_number=version_number,
        payload=payload,
    )


@router.post(
    "/documents/{document_id}/new-version",
    response_model=IpDocumentUploadResponse,
)
async def post_ip_document_version_upload(
    document_id: str,
    background_tasks: BackgroundTasks,
    context: IpWriter,
    session: DbSession,
    metadata_json: Annotated[str, Form()],
    upload: Annotated[UploadFile, File()],
) -> IpDocumentUploadResponse:
    try:
        metadata = IpDocumentNewVersionMetadata.model_validate_json(metadata_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    response, job_id = upload_ip_document_version(
        session,
        context=context,
        document_id=document_id,
        metadata=metadata,
        filename=upload.filename or "document",
        content_type=upload.content_type,
        stream=upload.file,
    )
    if job_id is not None:
        background_tasks.add_task(run_document_processing_job, job_id)
    return response


@router.get("/documents/{document_id}/versions/{version_number}/download")
async def get_ip_document_download(
    document_id: str,
    version_number: int,
    context: IpViewer,
    session: DbSession,
) -> FileResponse:
    version = get_ip_document_version_for_download(
        session,
        context=context,
        document_id=document_id,
        version_number=version_number,
    )
    storage_path = resolve_storage_path(version.storage_key)
    if not storage_path.exists():
        raise HTTPException(status_code=404, detail="Document file is no longer available.")
    return FileResponse(
        storage_path,
        filename=version.original_filename,
        media_type=version.content_type or "application/octet-stream",
    )


@router.get(
    "/document-taxonomy",
    response_model=IpDocumentTaxonomyResponse,
)
async def get_ip_document_taxonomy_route(
    context: IpViewer,
    session: DbSession,
) -> IpDocumentTaxonomyResponse:
    return get_ip_document_taxonomy(session, context=context)


@router.post(
    "/document-taxonomy/seed",
    response_model=IpDocumentTaxonomyResponse,
)
async def post_ip_document_taxonomy_seed(
    context: IpWorkspaceAdmin,
    session: DbSession,
) -> IpDocumentTaxonomyResponse:
    return seed_ip_document_taxonomy(session, context=context)


@router.put(
    "/document-taxonomy/{key}",
    response_model=IpDocumentTaxonomyEntryRecord,
)
async def put_ip_document_taxonomy_entry(
    key: str,
    payload: IpDocumentTaxonomyUpsertRequest,
    context: IpWorkspaceAdmin,
    session: DbSession,
) -> IpDocumentTaxonomyEntryRecord:
    return upsert_ip_document_taxonomy_entry(
        session,
        context=context,
        key=key,
        payload=payload,
    )


@router.post(
    "/document-taxonomy/import-aliases",
    response_model=IpDocumentAliasImportResponse,
)
async def post_ip_document_alias_import(
    payload: IpDocumentAliasImportRequest,
    context: IpWorkspaceAdmin,
    session: DbSession,
) -> IpDocumentAliasImportResponse:
    return import_ip_document_aliases(session, context=context, payload=payload)


@router.get(
    "/dockets/{docket_id}/deadline-workspace",
    response_model=IpDeadlineWorkspaceResponse,
)
async def get_ip_deadline_workspace(
    docket_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpDeadlineWorkspaceResponse:
    return deadline_workspace(session, context=context, docket_id=docket_id)


@router.post(
    "/deadline-rules",
    response_model=IpRuleVersionRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_deadline_rule(
    payload: IpRuleVersionProposalRequest,
    context: IpRuleProposer,
    session: DbSession,
) -> IpRuleVersionRecord:
    return propose_rule_version(session, context=context, payload=payload)


@router.get(
    "/deadline-rules/{rule_version_id}/impact",
    response_model=IpRuleImpactResponse,
)
async def get_ip_deadline_rule_impact(
    rule_version_id: str,
    context: IpRuleActivator,
    session: DbSession,
) -> IpRuleImpactResponse:
    return rule_impact(session, context=context, rule_version_id=rule_version_id)


@router.post(
    "/deadline-rules/{rule_version_id}/activate",
    response_model=IpRuleVersionRecord,
)
async def post_ip_deadline_rule_activation(
    rule_version_id: str,
    payload: IpRuleActivationRequest,
    context: IpRuleActivator,
    session: DbSession,
) -> IpRuleVersionRecord:
    return activate_rule_version(
        session,
        context=context,
        rule_version_id=rule_version_id,
        payload=payload,
    )


@router.post(
    "/deadline-rules/{rule_version_id}/transition",
    response_model=IpRuleVersionRecord,
)
async def post_ip_deadline_rule_transition(
    rule_version_id: str,
    payload: IpRuleTransitionRequest,
    context: IpRuleActivator,
    session: DbSession,
) -> IpRuleVersionRecord:
    return transition_rule_version(
        session,
        context=context,
        rule_version_id=rule_version_id,
        payload=payload,
    )


@router.post(
    "/working-calendars",
    response_model=LegalCalendarVersionRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_working_calendar(
    payload: LegalCalendarVersionProposalRequest,
    context: IpRuleProposer,
    session: DbSession,
) -> LegalCalendarVersionRecord:
    return propose_calendar_version(session, context=context, payload=payload)


@router.post(
    "/working-calendars/{calendar_version_id}/activate",
    response_model=LegalCalendarVersionRecord,
)
async def post_ip_working_calendar_activation(
    calendar_version_id: str,
    payload: LegalCalendarActivationRequest,
    context: IpRuleActivator,
    session: DbSession,
) -> LegalCalendarVersionRecord:
    return activate_calendar_version(
        session,
        context=context,
        calendar_version_id=calendar_version_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/deadlines",
    response_model=IpDeadlineRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_deadline_proposal(
    docket_id: str,
    payload: IpDeadlineProposalRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDeadlineRecord:
    return propose_deadline(session, context=context, docket_id=docket_id, payload=payload)


@router.get(
    "/deadlines/{deadline_id}/impact",
    response_model=IpDeadlineImpactResponse,
)
async def get_ip_deadline_impact(
    deadline_id: str,
    context: IpReviewer,
    session: DbSession,
) -> IpDeadlineImpactResponse:
    return deadline_impact(session, context=context, deadline_id=deadline_id)


@router.post("/deadlines/{deadline_id}/confirm", response_model=IpDeadlineRecord)
async def post_ip_deadline_confirmation(
    deadline_id: str,
    payload: IpDeadlineConfirmRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDeadlineRecord:
    return confirm_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        payload=payload,
    )


@router.post("/deadlines/{deadline_id}/override", response_model=IpDeadlineRecord)
async def post_ip_deadline_override(
    deadline_id: str,
    payload: IpDeadlineOverrideRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDeadlineRecord:
    return override_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        payload=payload,
    )


@router.post("/deadlines/{deadline_id}/recalculate", response_model=IpDeadlineRecord)
async def post_ip_deadline_recalculation(
    deadline_id: str,
    payload: IpDeadlineRecalculateRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDeadlineRecord:
    return recalculate_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        payload=payload,
    )


@router.post("/deadlines/{deadline_id}/complete", response_model=IpDeadlineRecord)
async def post_ip_deadline_completion(
    deadline_id: str,
    payload: IpDeadlineCompleteRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDeadlineRecord:
    return complete_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        payload=payload,
    )


@router.get("/readiness", response_model=IpWorkspaceReadinessResponse)
async def get_ip_workspace_readiness(
    context: IpViewer,
    session: DbSession,
) -> IpWorkspaceReadinessResponse:
    decisions = ip_workspace_readiness(
        session,
        context=context,
        settings=get_settings(),
    )
    configuration_status = get_ip_workspace_configuration_status(session, context=context)
    configuration = configuration_status.configuration
    features: list[dict[str, object]] = []
    for decision in decisions:
        available = decision.available
        reason = decision.reason
        if available:
            if configuration is None:
                available = False
                reason = "workspace_not_configured"
            elif not configuration.workspace_enabled:
                available = False
                reason = "tenant_disabled"
            elif decision.feature_id in {
                "registry_sync",
                "deadline_automation",
                "notification_automation",
            }:
                if decision.feature_id not in configuration.enabled_automations_json:
                    available = False
                    reason = "tenant_disabled"
                elif any(
                    blocker.startswith(f"{decision.feature_id}:")
                    for blocker in configuration_status.enablement_blockers
                ):
                    available = False
                    reason = "readiness_test_failed"
        features.append(
            {
                "feature_id": decision.feature_id,
                "available": available,
                "reason": reason,
                "owner": decision.owner,
                "required_capabilities": list(decision.required_capabilities),
                "missing_capabilities": list(decision.missing_capabilities),
                "entitlement_key": decision.entitlement_key,
                "entitled": decision.entitled,
                "rollout_flag": decision.rollout_flag,
                "rollout_enabled": decision.rollout_enabled,
                "rollout_expires_at": decision.rollout_expires_at,
                "manual_fallback_feature_id": decision.manual_fallback_feature_id,
            }
        )
    by_id = {feature["feature_id"]: feature for feature in features}
    return IpWorkspaceReadinessResponse(
        timezone=context.company.timezone,
        workspace_available=bool(by_id["workspace_core"]["available"]),
        manual_docketing_available=bool(by_id["manual_docketing"]["available"]),
        configuration_status=configuration_status,
        features=features,
    )


@router.get(
    "/workspace/configuration",
    response_model=IpWorkspaceConfigurationStatusResponse,
)
async def get_ip_workspace_configuration(
    context: IpWorkspaceAdmin,
    session: DbSession,
) -> IpWorkspaceConfigurationStatusResponse:
    return get_ip_workspace_configuration_status(session, context=context)


@router.put(
    "/workspace/configuration",
    response_model=IpWorkspaceConfigurationStatusResponse,
)
async def put_ip_workspace_configuration(
    payload: IpWorkspaceConfigurationUpsertRequest,
    context: IpWorkspaceAdmin,
    session: DbSession,
) -> IpWorkspaceConfigurationStatusResponse:
    return upsert_ip_workspace_configuration(session, context=context, payload=payload)


@router.post(
    "/workspace/tests",
    response_model=IpWorkspaceTestResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_workspace_test(
    payload: IpWorkspaceTestRunRequest,
    context: IpWorkspaceAdmin,
    session: DbSession,
) -> IpWorkspaceTestResultResponse:
    return IpWorkspaceTestResultResponse.model_validate(
        run_ip_workspace_test(session, context=context, payload=payload)
    )


@router.post(
    "/workspace/enable",
    response_model=IpWorkspaceConfigurationStatusResponse,
)
async def post_ip_workspace_enablement(
    payload: IpWorkspaceEnableRequest,
    context: IpWorkspaceAdmin,
    session: DbSession,
) -> IpWorkspaceConfigurationStatusResponse:
    return enable_ip_workspace(session, context=context, payload=payload)


@router.get(
    "/identifiers/search",
    response_model=list[IpIdentifierResponse],
)
async def get_ip_identifier_search(
    context: IpViewer,
    session: DbSession,
    query: Annotated[str, Query(alias="q", min_length=1, max_length=160)],
) -> list[IpIdentifierResponse]:
    return [
        IpIdentifierResponse.model_validate(row)
        for row in search_ip_identifiers(session, context=context, query=query)
    ]


@router.get("/dockets", response_model=IpDocketListResponse)
async def get_ip_dockets(context: IpViewer, session: DbSession) -> IpDocketListResponse:
    return list_ip_dockets(session, context=context)


@router.post(
    "/dockets",
    response_model=IpDocketRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_docket(
    payload: IpDocketCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocketRecordResponse:
    return create_ip_docket(session, context=context, payload=payload)


@router.get("/dockets/{docket_id}", response_model=IpDocketRecordResponse)
async def get_ip_docket_record(
    docket_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return get_ip_docket(session, context=context, docket_id=docket_id)


@router.get(
    "/dockets/{docket_id}/audit",
    response_model=IpDocketAuditListResponse,
)
async def get_ip_docket_audit(
    docket_id: str,
    context: IpViewer,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> IpDocketAuditListResponse:
    return list_ip_docket_audit_events(
        session,
        context=context,
        docket_id=docket_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/dockets/{docket_id}/prosecution",
    response_model=IpProsecutionWorkspaceResponse,
)
async def get_ip_docket_prosecution_workspace(
    docket_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpProsecutionWorkspaceResponse:
    return get_ip_prosecution_workspace(
        session,
        context=context,
        docket_id=docket_id,
    )


@router.get(
    "/dockets/{docket_id}/events",
    response_model=list[IpDocketEventResponse],
)
async def get_ip_docket_events(
    docket_id: str,
    context: IpViewer,
    session: DbSession,
) -> list[IpDocketEventResponse]:
    return [
        IpDocketEventResponse.model_validate(row)
        for row in list_ip_docket_events(
            session,
            context=context,
            docket_id=docket_id,
        )
    ]


@router.post(
    "/dockets/{docket_id}/events/preview",
    response_model=IpDocketEventPreviewResponse,
)
async def post_ip_docket_event_preview(
    docket_id: str,
    payload: IpDocketEventCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocketEventPreviewResponse:
    return preview_ip_docket_event(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/events",
    response_model=IpDocketEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_docket_event(
    docket_id: str,
    payload: IpDocketEventCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocketEventResponse:
    return IpDocketEventResponse.model_validate(
        append_ip_docket_event(
            session,
            context=context,
            docket_id=docket_id,
            payload=payload,
        )
    )


@router.post(
    "/dockets/{docket_id}/lifecycle/preview",
    response_model=IpLifecyclePreviewResponse,
)
async def post_ip_docket_lifecycle_preview(
    docket_id: str,
    payload: IpLifecycleTransitionRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpLifecyclePreviewResponse:
    return preview_ip_docket_lifecycle(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/lifecycle",
    response_model=IpLifecycleTransitionResponse,
)
async def post_ip_docket_lifecycle_transition(
    docket_id: str,
    payload: IpLifecycleTransitionRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpLifecycleTransitionResponse:
    docket, event = transition_ip_docket_lifecycle(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )
    return IpLifecycleTransitionResponse(
        docket_id=docket.id,
        status=docket.status,
        is_active=docket.is_active,
        lifecycle_version=docket.lifecycle_version,
        successor_docket_id=docket.successor_docket_id,
        event=IpDocketEventResponse.model_validate(event),
    )


@router.get(
    "/dockets/{docket_id}/core-records",
    response_model=IpCoreRecordResponse,
)
async def get_ip_docket_core_records(
    docket_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpCoreRecordResponse:
    return IpCoreRecordResponse.model_validate(
        list_ip_core_records(session, context=context, docket_id=docket_id)
    )


@router.post(
    "/dockets/{docket_id}/assets",
    response_model=IpAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_asset(
    docket_id: str,
    payload: IpAssetCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpAssetResponse:
    return IpAssetResponse.model_validate(
        create_ip_asset(session, context=context, docket_id=docket_id, payload=payload)
    )


@router.post(
    "/dockets/{docket_id}/applications",
    response_model=TrademarkApplicationMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_trademark_application(
    docket_id: str,
    payload: TrademarkApplicationCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> TrademarkApplicationMutationResponse:
    application, identifier, duplicates = create_trademark_application(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )
    return TrademarkApplicationMutationResponse(
        application=TrademarkApplicationResponse.model_validate(application),
        identifier=(
            IpIdentifierResponse.model_validate(identifier) if identifier is not None else None
        ),
        duplicate_candidates=[IpIdentifierResponse.model_validate(row) for row in duplicates],
    )


@router.patch(
    "/applications/{application_id}/filing-phase",
    response_model=TrademarkApplicationResponse,
)
async def patch_trademark_application_phase(
    application_id: str,
    payload: TrademarkApplicationPhaseUpdateRequest,
    context: IpWriter,
    session: DbSession,
) -> TrademarkApplicationResponse:
    return TrademarkApplicationResponse.model_validate(
        update_trademark_application_phase(
            session,
            context=context,
            application_id=application_id,
            payload=payload,
        )
    )


@router.post(
    "/dockets/{docket_id}/proceedings",
    response_model=IpProceedingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_proceeding(
    docket_id: str,
    payload: IpProceedingCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpProceedingResponse:
    return IpProceedingResponse.model_validate(
        create_ip_proceeding(
            session,
            context=context,
            docket_id=docket_id,
            payload=payload,
        )
    )


@router.post(
    "/dockets/{docket_id}/identifiers",
    response_model=IpIdentifierMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_identifier(
    docket_id: str,
    payload: IpIdentifierCreate,
    context: IpWriter,
    session: DbSession,
) -> IpIdentifierMutationResponse:
    identifier, duplicates = create_ip_identifier(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )
    return IpIdentifierMutationResponse(
        identifier=IpIdentifierResponse.model_validate(identifier),
        duplicate_candidates=[IpIdentifierResponse.model_validate(row) for row in duplicates],
    )


@router.post(
    "/dockets/{docket_id}/identifiers/{identifier_id}/corrections",
    response_model=IpIdentifierMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_identifier_correction(
    docket_id: str,
    identifier_id: str,
    payload: IpIdentifierCorrectionCreate,
    context: IpWriter,
    session: DbSession,
) -> IpIdentifierMutationResponse:
    identifier, duplicates = correct_ip_identifier(
        session,
        context=context,
        docket_id=docket_id,
        identifier_id=identifier_id,
        payload=payload,
    )
    return IpIdentifierMutationResponse(
        identifier=IpIdentifierResponse.model_validate(identifier),
        duplicate_candidates=[IpIdentifierResponse.model_validate(row) for row in duplicates],
    )


@router.post("/dockets/{docket_id}/versions", response_model=IpDocketRecordResponse)
async def post_ip_docket_version(
    docket_id: str,
    payload: IpDocketVersionCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocketRecordResponse:
    return append_ip_docket_version(session, context=context, docket_id=docket_id, payload=payload)


@router.post("/dockets/{docket_id}/notice-links", response_model=IpDocketRecordResponse)
async def post_ip_notice_link(
    docket_id: str,
    payload: IpNoticeLinkCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocketRecordResponse:
    return add_ip_notice_link(session, context=context, docket_id=docket_id, payload=payload)


@router.post(
    "/dockets/{docket_id}/evidence/discover",
    response_model=IpEvidenceDiscoveryResponse,
)
async def post_ip_evidence_discovery(
    docket_id: str,
    context: IpReviewer,
    session: DbSession,
) -> IpEvidenceDiscoveryResponse:
    return discover_ip_evidence_candidates(
        session,
        context=context,
        docket_id=docket_id,
    )


@router.post(
    "/dockets/{docket_id}/evidence/{candidate_id}/review",
    response_model=IpDocketRecordResponse,
)
async def post_ip_evidence_review(
    docket_id: str,
    candidate_id: str,
    payload: IpEvidenceCandidateReviewRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return review_ip_evidence_candidate(
        session,
        context=context,
        docket_id=docket_id,
        candidate_id=candidate_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/deadline-coverages",
    response_model=IpDocketRecordResponse,
)
async def post_ip_deadline_coverage(
    docket_id: str,
    payload: IpDeadlineCoverageCreateRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return add_ip_deadline_coverage(session, context=context, docket_id=docket_id, payload=payload)


@router.post(
    "/dockets/{docket_id}/deadline-coverages/{coverage_id}/reassign",
    response_model=IpDocketRecordResponse,
)
async def post_ip_deadline_coverage_reassignment(
    docket_id: str,
    coverage_id: str,
    payload: IpDeadlineCoverageReassignRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return reassign_ip_deadline_coverage(
        session,
        context=context,
        docket_id=docket_id,
        coverage_id=coverage_id,
        payload=payload,
    )


@router.post(
    "/deadline-coverages/bulk-reassign",
    response_model=IpCoverageBulkReassignResponse,
)
async def post_ip_deadline_coverage_bulk_reassignment(
    payload: IpCoverageBulkReassignRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpCoverageBulkReassignResponse:
    return bulk_reassign_ip_deadline_coverages(
        session,
        context=context,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/deadline-incidents",
    response_model=IpDocketRecordResponse,
)
async def post_ip_deadline_incident(
    docket_id: str,
    payload: IpDeadlineIncidentCreateRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return add_ip_deadline_incident(session, context=context, docket_id=docket_id, payload=payload)


@router.post(
    "/dockets/{docket_id}/deadline-incidents/{incident_id}/verify",
    response_model=IpDocketRecordResponse,
)
async def post_ip_deadline_incident_verification(
    docket_id: str,
    incident_id: str,
    payload: IpDeadlineIncidentVerifyRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return verify_ip_deadline_incident(
        session,
        context=context,
        docket_id=docket_id,
        incident_id=incident_id,
        payload=payload,
    )


@router.post("/dockets/{docket_id}/title-interests", response_model=IpDocketRecordResponse)
async def post_ip_title_interest(
    docket_id: str,
    payload: IpTitleInterestCreateRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return add_ip_title_interest(session, context=context, docket_id=docket_id, payload=payload)


@router.post(
    "/dockets/{docket_id}/related-right-obligations",
    response_model=IpDocketRecordResponse,
)
async def post_ip_related_right_obligation(
    docket_id: str,
    payload: IpRelatedRightObligationCreateRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return add_ip_related_right_obligation(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/related-right-obligations/{obligation_id}/complete",
    response_model=IpDocketRecordResponse,
)
async def post_ip_related_right_obligation_completion(
    docket_id: str,
    obligation_id: str,
    payload: IpRelatedRightObligationCompleteRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return complete_ip_related_right_obligation(
        session,
        context=context,
        docket_id=docket_id,
        obligation_id=obligation_id,
        payload=payload,
    )


@router.post("/dockets/{docket_id}/cost-items", response_model=IpDocketRecordResponse)
async def post_ip_cost_item(
    docket_id: str,
    payload: IpCostItemCreateRequest,
    context: IpFinance,
    session: DbSession,
) -> IpDocketRecordResponse:
    return add_ip_cost_item(session, context=context, docket_id=docket_id, payload=payload)


@router.post(
    "/dockets/{docket_id}/cost-items/reconcile",
    response_model=IpCostReconciliationReport,
)
async def post_ip_cost_reconciliation(
    docket_id: str,
    context: IpFinance,
    session: DbSession,
) -> IpCostReconciliationReport:
    return reconcile_ip_cost_items(
        session,
        context=context,
        docket_id=docket_id,
    )


@router.get("/reports/docket-control", response_model=IpDocketControlReport)
async def get_ip_docket_control_report(
    context: IpViewer,
    session: DbSession,
) -> IpDocketControlReport:
    return ip_docket_control_report(session, context=context)
