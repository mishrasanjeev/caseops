from __future__ import annotations

from datetime import UTC, datetime
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
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.core.settings import get_settings
from caseops_api.schemas.audit import IpDocketAuditListResponse
from caseops_api.schemas.ip_access import (
    IpAccessApplyRequest,
    IpAccessChangeRequest,
    IpAccessChangeResponse,
    IpAccessPanelResponse,
    IpAccessPreviewResponse,
    RecordAccessFoundationContract,
    RecordAccessReconciliationReport,
)
from caseops_api.schemas.ip_deadlines import (
    IpCompanyRulePolicyRecord,
    IpCompanyRuleSelectionRequest,
    IpDeadlineCompleteRequest,
    IpDeadlineConfirmRequest,
    IpDeadlineDependencyResponse,
    IpDeadlineImpactResponse,
    IpDeadlineOverrideRequest,
    IpDeadlineProposalRequest,
    IpDeadlineRecalculateRequest,
    IpDeadlineRecord,
    IpDeadlineWorkspaceResponse,
    IpNotificationPreviewRequest,
    IpNotificationPreviewResponse,
    IpNotificationStatusResponse,
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
from caseops_api.schemas.ip_imports import (
    IpImportCommitRequest,
    IpImportCommitResponse,
    IpImportJobCreateRequest,
    IpImportJobListResponse,
    IpImportPreviewResponse,
    IpImportReconciliationRequest,
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
    IpAssignedCoverageListResponse,
    IpCalendarDriftRecord,
    IpCalendarDriftResponse,
    IpCalendarReconciliationCandidateListResponse,
    IpCalendarReconciliationCandidateRecord,
    IpCalendarReconciliationDecisionRequest,
    IpControlReviewCreateRequest,
    IpControlReviewExceptionDecisionRequest,
    IpControlReviewExportRequest,
    IpControlReviewListResponse,
    IpControlReviewRecord,
    IpControlReviewSampleRequest,
    IpControlReviewSignOffRequest,
    IpCostItemCreateRequest,
    IpCostReconciliationReport,
    IpCoverageBulkAcknowledgeRequest,
    IpCoverageBulkAcknowledgeResponse,
    IpCoverageBulkReassignRequest,
    IpCoverageBulkReassignResponse,
    IpCoverageReassignPreviewRequest,
    IpCoverageReassignPreviewResponse,
    IpCoverageReassignProposeRequest,
    IpCoverageReplacementDecisionRequest,
    IpCoverageTransfersAwaitingResponse,
    IpDailyDocketResponse,
    IpDeadlineCoverageCreateRequest,
    IpDeadlineCoverageReassignRequest,
    IpDeadlineIncidentActionRequest,
    IpDeadlineIncidentCreateRequest,
    IpDeadlineIncidentImpactScanRequest,
    IpDeadlineIncidentNotificationDecisionRequest,
    IpDeadlineIncidentVerifyRequest,
    IpDocketControlReport,
    IpDocketCreateRequest,
    IpDocketListResponse,
    IpDocketQueueListResponse,
    IpDocketQueueRecord,
    IpDocketQueueSaveRequest,
    IpDocketRecordResponse,
    IpDocketVersionCreateRequest,
    IpEvidenceCandidateReviewRequest,
    IpEvidenceDiscoveryResponse,
    IpIncidentKillSwitchReleaseRequest,
    IpNoticeLinkCreateRequest,
    IpRelatedRightObligationCompleteRequest,
    IpRelatedRightObligationCreateRequest,
    IpTitleInterestCreateRequest,
    IpWorkspaceReadinessResponse,
    ManualTrademarkApplicationCreateRequest,
    ManualTrademarkApplicationCreateResponse,
)
from caseops_api.schemas.ip_oppositions import (
    IpOppositionApplicantActionRequest,
    IpOppositionApplicantDeadlineProposalRequest,
    IpOppositionApplicantDeadlineRecord,
    IpOppositionApplicantWorkflowResponse,
    IpOppositionOpponentActionRequest,
    IpOppositionOpponentDeadlineProposalRequest,
    IpOppositionOpponentDeadlineRecord,
    IpOppositionOpponentWorkflowResponse,
    IpOppositionWorkspaceResponse,
    IpOppositionWorkspaceUpsertRequest,
)
from caseops_api.schemas.ip_portfolio import (
    IpPortfolioExportCreate,
    IpPortfolioExportListResponse,
    IpPortfolioExportPreview,
    IpPortfolioExportPreviewRequest,
    IpPortfolioExportRecord,
    IpPortfolioFamilyResponse,
    IpPortfolioFilters,
    IpPortfolioListResponse,
    IpPortfolioSavedViewCreate,
    IpPortfolioSavedViewListResponse,
    IpPortfolioSavedViewRecord,
    IpPortfolioSavedViewUpdate,
)
from caseops_api.schemas.ip_records import (
    IpAssetCreateRequest,
    IpAssetResponse,
    IpCoreRecordResponse,
    IpDuplicatePreviewResponse,
    IpDuplicateResolutionRequest,
    IpDuplicateResolutionResponse,
    IpIdentifierCorrectionCreate,
    IpIdentifierCreate,
    IpIdentifierMutationResponse,
    IpIdentifierResponse,
    IpOppositionStageTransitionRequest,
    IpOppositionStageTransitionResponse,
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
from caseops_api.schemas.ip_renewals import (
    IpClientInstructionAcknowledgeRequest,
    IpClientInstructionCreateRequest,
    IpRenewalFoundationContract,
    IpRenewalPortfolioResponse,
    IpRenewalReminderScheduleRequest,
    IpRenewalReminderScheduleResponse,
    IpRenewalTermCreateRequest,
    IpRenewalTermListResponse,
    IpRenewalTermRecord,
    IpRenewalTermTransitionRequest,
)
from caseops_api.schemas.ip_reports import (
    IpReportFoundationContract,
    IpReportPreviewRequest,
    IpReportPreviewResponse,
)
from caseops_api.schemas.shared_work import (
    IpOperationalDeadlineCreateRequest,
    IpOperationalDeadlineListResponse,
    IpOperationalDeadlineRecord,
    IpOperationalDeadlineTransitionRequest,
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
    deadline_dependencies,
    deadline_impact,
    deadline_notification_status,
    deadline_workspace,
    list_company_rule_policies,
    override_deadline,
    preview_deadline_notifications,
    propose_calendar_version,
    propose_deadline,
    propose_rule_version,
    recalculate_deadline,
    rule_impact,
    select_company_rule_version,
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
from caseops_api.services.ip_import_files import MAX_IMPORT_BYTES, parse_ip_import_file
from caseops_api.services.ip_imports import (
    commit_ip_import_job,
    create_ip_import_job,
    ip_import_error_report,
    list_ip_import_jobs,
    preview_ip_import_job,
    reconcile_ip_import_job,
    revalidate_ip_import_job,
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
    active_ip_incident_kill_switches,
    add_ip_cost_item,
    add_ip_deadline_coverage,
    add_ip_deadline_incident,
    add_ip_notice_link,
    add_ip_related_right_obligation,
    add_ip_title_interest,
    append_ip_docket_version,
    bulk_acknowledge_ip_coverage,
    bulk_reassign_ip_deadline_coverages,
    complete_ip_related_right_obligation,
    create_ip_control_review,
    create_ip_docket,
    decide_ip_control_review_exception,
    decide_ip_coverage_replacement,
    decide_ip_deadline_incident_notification,
    delete_ip_docket_queue,
    discover_ip_evidence_candidates,
    get_ip_control_review,
    get_ip_docket,
    ip_daily_docket,
    ip_docket_control_report,
    list_ip_assigned_coverage,
    list_ip_control_reviews,
    list_ip_coverage_transfers_awaiting,
    list_ip_docket_queues,
    list_ip_dockets,
    preview_ip_coverage_reassignment,
    propose_ip_coverage_reassignment,
    reassign_ip_deadline_coverage,
    reconcile_ip_cost_items,
    record_ip_control_review_export,
    record_ip_control_review_sample,
    record_ip_deadline_incident_action,
    record_ip_deadline_incident_impact_scan,
    release_ip_incident_kill_switch,
    retain_ip_deadline_incident,
    review_ip_evidence_candidate,
    save_ip_docket_queue,
    sign_off_ip_control_review,
    verify_ip_deadline_incident,
)
from caseops_api.services.ip_opposition_applicant import (
    get_applicant_workflow,
    propose_applicant_deadline,
    record_applicant_action,
)
from caseops_api.services.ip_opposition_opponent import (
    get_opponent_workflow,
    propose_opponent_deadline,
    record_opponent_action,
)
from caseops_api.services.ip_opposition_workspace import (
    get_opposition_workspace,
    save_opposition_workspace,
)
from caseops_api.services.ip_oppositions import transition_opposition_stage
from caseops_api.services.ip_portfolio import (
    list_ip_portfolio,
    list_ip_portfolio_families,
)
from caseops_api.services.ip_portfolio_workflow import (
    create_saved_view,
    delete_saved_view,
    enqueue_portfolio_export,
    get_portfolio_export,
    list_portfolio_exports,
    list_saved_views,
    preview_portfolio_export,
    read_portfolio_export,
    retry_portfolio_export,
    run_portfolio_export_job,
    update_saved_view,
)
from caseops_api.services.ip_records import (
    correct_ip_identifier,
    create_ip_asset,
    create_ip_identifier,
    create_ip_proceeding,
    create_manual_trademark_application,
    create_trademark_application,
    list_ip_core_records,
    preview_ip_identifier_duplicates,
    resolve_ip_identifier_duplicate,
    search_ip_identifiers,
    update_trademark_application_phase,
)
from caseops_api.services.ip_renewals import (
    acknowledge_client_instruction,
    create_client_instruction,
    create_renewal_term,
    list_renewal_portfolio,
    list_renewal_terms,
    renewal_foundation_contract,
    schedule_renewal_instruction_reminders,
    transition_renewal_term,
)
from caseops_api.services.ip_reports import (
    ip_report_foundation_contract,
    preview_ip_report,
)
from caseops_api.services.ip_workspace import (
    enable_ip_workspace,
    get_ip_workspace_configuration_status,
    run_ip_workspace_test,
    upsert_ip_workspace_configuration,
)
from caseops_api.services.matter_access import (
    apply_ip_access_change,
    get_ip_access_panel,
    preview_ip_access_change,
    reconcile_record_access,
    record_access_foundation_contract,
)
from caseops_api.services.security import require_recent_step_up
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
    transition_ip_covered_operational_deadline,
    update_ip_operational_deadline,
    update_ip_shared_hearing,
    update_ip_shared_task,
)

router = APIRouter()
IpViewer = Annotated[SessionContext, Depends(require_capability("ip:read"))]
IpWriter = Annotated[SessionContext, Depends(require_capability("ip:write"))]
IpApprover = Annotated[SessionContext, Depends(require_capability("ip:approve"))]
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
    "/dockets/{docket_id}/access",
    response_model=IpAccessPanelResponse,
    summary="Inspect internal IP access grants, ethical walls, and policy history",
)
async def get_ip_docket_access_panel(
    docket_id: str,
    context: IpAccessManager,
    session: DbSession,
) -> IpAccessPanelResponse:
    return get_ip_access_panel(
        session,
        context=context,
        docket_id=docket_id,
    )


@router.post(
    "/dockets/{docket_id}/access/preview",
    response_model=IpAccessPreviewResponse,
    summary="Preview an internal IP access-policy change without mutation",
)
async def post_ip_docket_access_preview(
    docket_id: str,
    payload: IpAccessChangeRequest,
    context: IpAccessManager,
    session: DbSession,
) -> IpAccessPreviewResponse:
    return preview_ip_access_change(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/access/apply",
    response_model=IpAccessChangeResponse,
    summary="Apply a previewed internal IP access-policy change",
)
async def post_ip_docket_access_change(
    docket_id: str,
    payload: IpAccessApplyRequest,
    context: IpAccessManager,
    session: DbSession,
) -> IpAccessChangeResponse:
    require_recent_step_up(
        session,
        context=context,
        purpose="record_access_change",
    )
    return apply_ip_access_change(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )


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
    return update_ip_shared_task(session, context=context, task_id=task_id, payload=payload)


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


@router.post(
    "/operational-deadlines/{deadline_id}/terminalize",
    response_model=IpOperationalDeadlineRecord,
)
async def post_ip_covered_deadline_terminalization(
    deadline_id: str,
    payload: IpOperationalDeadlineTransitionRequest,
    context: IpWriter,
    session: DbSession,
) -> IpOperationalDeadlineRecord:
    return transition_ip_covered_operational_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        payload=payload,
    )


@router.get(
    "/renewals/foundation-contract",
    response_model=IpRenewalFoundationContract,
)
async def get_ip_renewal_foundation_contract(
    context: IpViewer,
) -> IpRenewalFoundationContract:
    del context
    return renewal_foundation_contract()


@router.get(
    "/renewals/portfolio",
    response_model=IpRenewalPortfolioResponse,
)
async def get_ip_renewal_portfolio(
    context: IpViewer,
    session: DbSession,
) -> IpRenewalPortfolioResponse:
    return list_renewal_portfolio(session, context=context)


@router.get(
    "/dockets/{docket_id}/renewal-terms",
    response_model=IpRenewalTermListResponse,
)
async def get_ip_renewal_terms(
    docket_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpRenewalTermListResponse:
    return list_renewal_terms(session, context=context, docket_id=docket_id)


@router.post(
    "/dockets/{docket_id}/renewal-terms",
    response_model=IpRenewalTermRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_renewal_term(
    docket_id: str,
    payload: IpRenewalTermCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpRenewalTermRecord:
    return create_renewal_term(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/renewal-terms/{term_id}/instruction-reminders",
    response_model=IpRenewalReminderScheduleResponse,
)
async def post_ip_renewal_instruction_reminders(
    docket_id: str,
    term_id: str,
    payload: IpRenewalReminderScheduleRequest,
    context: IpWriter,
    session: DbSession,
) -> IpRenewalReminderScheduleResponse:
    return schedule_renewal_instruction_reminders(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/renewal-terms/{term_id}/instructions",
    response_model=IpRenewalTermRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_client_instruction(
    docket_id: str,
    term_id: str,
    payload: IpClientInstructionCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpRenewalTermRecord:
    return create_client_instruction(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/renewal-terms/{term_id}/instructions/"
    "{instruction_id}/acknowledge",
    response_model=IpRenewalTermRecord,
)
async def post_ip_client_instruction_acknowledgement(
    docket_id: str,
    term_id: str,
    instruction_id: str,
    payload: IpClientInstructionAcknowledgeRequest,
    context: IpWriter,
    session: DbSession,
) -> IpRenewalTermRecord:
    return acknowledge_client_instruction(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        instruction_id=instruction_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/renewal-terms/{term_id}/transition",
    response_model=IpRenewalTermRecord,
)
async def post_ip_renewal_term_transition(
    docket_id: str,
    term_id: str,
    payload: IpRenewalTermTransitionRequest,
    context: IpWriter,
    session: DbSession,
) -> IpRenewalTermRecord:
    return transition_renewal_term(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        payload=payload,
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


@router.get(
    "/rule-policies",
    response_model=list[IpCompanyRulePolicyRecord],
)
async def get_ip_rule_policies(
    context: IpRuleProposer,
    session: DbSession,
) -> list[IpCompanyRulePolicyRecord]:
    return list_company_rule_policies(session, context=context)


@router.put(
    "/rule-policies",
    response_model=IpCompanyRulePolicyRecord,
)
async def put_ip_rule_policy(
    payload: IpCompanyRuleSelectionRequest,
    context: IpRuleActivator,
    session: DbSession,
) -> IpCompanyRulePolicyRecord:
    return select_company_rule_version(session, context=context, payload=payload)


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


@router.get(
    "/deadlines/{deadline_id}/dependencies",
    response_model=IpDeadlineDependencyResponse,
)
async def get_ip_deadline_dependencies(
    deadline_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpDeadlineDependencyResponse:
    return deadline_dependencies(session, context=context, deadline_id=deadline_id)


@router.post(
    "/deadlines/{deadline_id}/notification-preview",
    response_model=IpNotificationPreviewResponse,
)
async def post_ip_deadline_notification_preview(
    deadline_id: str,
    payload: IpNotificationPreviewRequest,
    context: IpViewer,
    session: DbSession,
) -> IpNotificationPreviewResponse:
    return preview_deadline_notifications(
        session, context=context, deadline_id=deadline_id, payload=payload
    )


@router.get(
    "/deadlines/{deadline_id}/notifications",
    response_model=IpNotificationStatusResponse,
)
async def get_ip_deadline_notifications(
    deadline_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpNotificationStatusResponse:
    return deadline_notification_status(session, context=context, deadline_id=deadline_id)


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
    incident_kill_switches = active_ip_incident_kill_switches(
        session, company_id=context.company.id
    )
    features: list[dict[str, object]] = []
    for decision in decisions:
        available = decision.available
        reason = decision.reason
        blocked_by_incident_id = incident_kill_switches.get(decision.feature_id)
        if blocked_by_incident_id is not None:
            available = False
            reason = "incident_kill_switch"
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
                "blocked_by_incident_id": blocked_by_incident_id,
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


@router.post(
    "/imports",
    response_model=IpImportPreviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_import_job(
    payload: IpImportJobCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpImportPreviewResponse:
    return create_ip_import_job(session, context=context, payload=payload)


@router.post(
    "/imports/upload",
    response_model=IpImportPreviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_import_file(
    file: UploadFile,
    context: IpWriter,
    session: DbSession,
) -> IpImportPreviewResponse:
    payload = parse_ip_import_file(
        filename=file.filename or "portfolio.csv",
        content=await file.read(MAX_IMPORT_BYTES + 1),
    )
    return create_ip_import_job(session, context=context, payload=payload)


@router.get("/imports/history", response_model=IpImportJobListResponse)
async def get_ip_import_history(
    context: IpViewer,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> IpImportJobListResponse:
    return IpImportJobListResponse(
        jobs=list_ip_import_jobs(session, context=context, limit=limit)
    )


@router.get("/imports/{job_id}", response_model=IpImportPreviewResponse)
async def get_ip_import_job(
    job_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpImportPreviewResponse:
    return preview_ip_import_job(session, context=context, job_id=job_id)


@router.post("/imports/{job_id}/revalidate", response_model=IpImportPreviewResponse)
async def post_ip_import_revalidation(
    job_id: str,
    context: IpWriter,
    session: DbSession,
) -> IpImportPreviewResponse:
    return revalidate_ip_import_job(session, context=context, job_id=job_id)


@router.post("/imports/{job_id}/reconcile", response_model=IpImportPreviewResponse)
async def post_ip_import_reconciliation(
    job_id: str,
    payload: IpImportReconciliationRequest,
    context: IpWriter,
    session: DbSession,
) -> IpImportPreviewResponse:
    return reconcile_ip_import_job(
        session,
        context=context,
        job_id=job_id,
        payload=payload,
    )


@router.get("/imports/{job_id}/errors")
async def get_ip_import_errors(
    job_id: str,
    context: IpViewer,
    session: DbSession,
) -> StreamingResponse:
    content = ip_import_error_report(
        session,
        context=context,
        job_id=job_id,
    )
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ip-import-{job_id}-errors.csv"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/imports/{job_id}/commit", response_model=IpImportCommitResponse)
async def post_ip_import_commit(
    job_id: str,
    payload: IpImportCommitRequest,
    context: IpWriter,
    session: DbSession,
) -> IpImportCommitResponse:
    return commit_ip_import_job(session, context=context, job_id=job_id, payload=payload)


@router.get("/portfolio/views", response_model=IpPortfolioSavedViewListResponse)
async def get_ip_portfolio_saved_views(
    context: IpViewer,
    session: DbSession,
) -> IpPortfolioSavedViewListResponse:
    return IpPortfolioSavedViewListResponse(views=list_saved_views(session, context=context))


@router.post(
    "/portfolio/views",
    response_model=IpPortfolioSavedViewRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_portfolio_saved_view(
    payload: IpPortfolioSavedViewCreate,
    context: IpViewer,
    session: DbSession,
) -> IpPortfolioSavedViewRecord:
    return create_saved_view(session, context=context, payload=payload)


@router.put("/portfolio/views/{view_id}", response_model=IpPortfolioSavedViewRecord)
async def put_ip_portfolio_saved_view(
    view_id: str,
    payload: IpPortfolioSavedViewUpdate,
    context: IpViewer,
    session: DbSession,
) -> IpPortfolioSavedViewRecord:
    return update_saved_view(
        session,
        context=context,
        view_id=view_id,
        payload=payload,
    )


@router.delete("/portfolio/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ip_portfolio_saved_view(
    view_id: str,
    context: IpViewer,
    session: DbSession,
) -> None:
    delete_saved_view(session, context=context, view_id=view_id)


@router.post(
    "/portfolio/exports/preview",
    response_model=IpPortfolioExportPreview,
)
async def post_ip_portfolio_export_preview(
    payload: IpPortfolioExportPreviewRequest,
    context: IpViewer,
    session: DbSession,
) -> IpPortfolioExportPreview:
    return preview_portfolio_export(session, context=context, payload=payload)


@router.post(
    "/portfolio/exports",
    response_model=IpPortfolioExportRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_ip_portfolio_export(
    payload: IpPortfolioExportCreate,
    background_tasks: BackgroundTasks,
    context: IpViewer,
    session: DbSession,
) -> IpPortfolioExportRecord:
    job = enqueue_portfolio_export(session, context=context, payload=payload)
    background_tasks.add_task(run_portfolio_export_job, job.id)
    return job


@router.post(
    "/portfolio/exports/{job_id}/retry",
    response_model=IpPortfolioExportRecord,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_ip_portfolio_export_retry(
    job_id: str,
    background_tasks: BackgroundTasks,
    context: IpViewer,
    session: DbSession,
) -> IpPortfolioExportRecord:
    job = retry_portfolio_export(session, context=context, job_id=job_id)
    background_tasks.add_task(run_portfolio_export_job, job.id)
    return job


@router.get("/portfolio/exports", response_model=IpPortfolioExportListResponse)
async def get_ip_portfolio_exports(
    context: IpViewer,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> IpPortfolioExportListResponse:
    return IpPortfolioExportListResponse(
        jobs=list_portfolio_exports(session, context=context, limit=limit)
    )


@router.get("/portfolio/exports/{job_id}", response_model=IpPortfolioExportRecord)
async def get_ip_portfolio_export(
    job_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpPortfolioExportRecord:
    return get_portfolio_export(session, context=context, job_id=job_id)


@router.get("/portfolio/exports/{job_id}/download")
async def download_ip_portfolio_export(
    job_id: str,
    context: IpViewer,
    session: DbSession,
) -> StreamingResponse:
    _job, stream = read_portfolio_export(
        session,
        context=context,
        job_id=job_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="trademark-portfolio-{job_id}.csv"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/portfolio/families", response_model=IpPortfolioFamilyResponse)
async def get_ip_portfolio_families(
    context: IpViewer,
    session: DbSession,
    grouping: Annotated[str, Query(pattern="^(mark|client)$")] = "mark",
    query: Annotated[str | None, Query(max_length=200)] = None,
    matter_id: Annotated[str | None, Query(max_length=36)] = None,
    client: Annotated[list[str] | None, Query()] = None,
    proprietor: Annotated[list[str] | None, Query()] = None,
    nice_class: Annotated[list[int] | None, Query()] = None,
    responsible_membership_id: Annotated[list[str] | None, Query()] = None,
    team_id: Annotated[list[str] | None, Query()] = None,
    asset_kind: Annotated[list[str] | None, Query()] = None,
    jurisdiction: Annotated[list[str] | None, Query()] = None,
    office: Annotated[list[str] | None, Query()] = None,
    filing_phase: Annotated[list[str] | None, Query()] = None,
    docket_status: Annotated[list[str] | None, Query()] = None,
    deadline_state: Annotated[list[str] | None, Query()] = None,
    opposition_only: bool = False,
    registry_sync_state: Annotated[list[str] | None, Query()] = None,
    include_inactive: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> IpPortfolioFamilyResponse:
    filters = IpPortfolioFilters(
        query=query,
        matter_id=matter_id,
        client=client or [],
        proprietor=proprietor or [],
        nice_class=nice_class or [],
        responsible_membership_id=responsible_membership_id or [],
        team_id=team_id or [],
        asset_kind=asset_kind or [],
        jurisdiction=jurisdiction or [],
        office=office or [],
        filing_phase=filing_phase or [],
        docket_status=docket_status or [],
        deadline_state=deadline_state or [],
        opposition_only=opposition_only,
        registry_sync_state=registry_sync_state or [],
        include_inactive=include_inactive,
    )
    return list_ip_portfolio_families(
        session,
        context=context,
        grouping=grouping,
        filters=filters,
        limit=limit,
        cursor=cursor,
    )


@router.post("/docket-queues", response_model=IpDocketQueueRecord, status_code=201)
async def post_ip_docket_queue(
    payload: IpDocketQueueSaveRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocketQueueRecord:
    return save_ip_docket_queue(session, context=context, payload=payload)


@router.get("/docket-queues", response_model=IpDocketQueueListResponse)
async def get_ip_docket_queues(
    context: IpWriter,
    session: DbSession,
) -> IpDocketQueueListResponse:
    return list_ip_docket_queues(session, context=context)


@router.delete("/docket-queues/{queue_id}", status_code=204)
async def delete_ip_docket_queue_route(
    queue_id: str,
    context: IpWriter,
    session: DbSession,
) -> None:
    delete_ip_docket_queue(session, context=context, queue_id=queue_id)


@router.post(
    "/deadline-coverages/bulk-acknowledge",
    response_model=IpCoverageBulkAcknowledgeResponse,
)
async def post_ip_coverage_bulk_acknowledge(
    payload: IpCoverageBulkAcknowledgeRequest,
    context: IpWriter,
    session: DbSession,
) -> IpCoverageBulkAcknowledgeResponse:
    return bulk_acknowledge_ip_coverage(session, context=context, payload=payload)


@router.post(
    "/calendar-projections/drift-check",
    response_model=IpCalendarDriftResponse,
)
async def post_ip_calendar_drift_check(
    context: IpWriter,
    session: DbSession,
) -> IpCalendarDriftResponse:
    from caseops_api.services.calendar_sync import check_ip_calendar_projection_drift

    decision = next(
        item
        for item in ip_workspace_readiness(
            session,
            context=context,
            settings=get_settings(),
        )
        if item.feature_id == "manual_docketing"
    )
    if not decision.available:
        # Authorization, entitlement and rollout are independent. `IpWriter`
        # proves authorization; this server-side check prevents a direct API
        # caller from bypassing a disabled, unentitled or expired rollout and
        # triggering provider reads or drift-state writes.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ip_manual_docketing_unavailable",
                "feature_id": decision.feature_id,
                "reason": decision.reason,
                "rollout_flag": decision.rollout_flag,
            },
        )

    findings = check_ip_calendar_projection_drift(session, context=context)
    return IpCalendarDriftResponse(
        checked_at=datetime.now(UTC),
        findings=[IpCalendarDriftRecord(**vars(finding)) for finding in findings],
    )


def _calendar_reconciliation_candidate_record(row) -> IpCalendarReconciliationCandidateRecord:
    return IpCalendarReconciliationCandidateRecord(
        id=row.id,
        calendar_event_sync_id=row.calendar_event_sync_id,
        calendar_connection_id=row.calendar_connection_id,
        source_type=row.source_type,
        source_id=row.source_id,
        ip_docket_id=row.ip_docket_id,
        drift_status=row.drift_status,
        snapshot_schema_version=row.snapshot_schema_version,
        expected_snapshot=dict(row.expected_snapshot_json or {}),
        observed_snapshot=dict(row.observed_snapshot_json or {}),
        snapshot_sha256=row.snapshot_sha256,
        status=row.status,
        detected_by_membership_id=row.detected_by_membership_id,
        decided_by_membership_id=row.decided_by_membership_id,
        decision_evidence_reference=row.decision_evidence_reference,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )


@router.get(
    "/calendar-projections/reconciliation-candidates",
    response_model=IpCalendarReconciliationCandidateListResponse,
)
async def get_ip_calendar_reconciliation_candidates(
    context: IpViewer,
    session: DbSession,
    include_resolved: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> IpCalendarReconciliationCandidateListResponse:
    from caseops_api.services.calendar_sync import (
        list_ip_calendar_projection_reconciliation_candidates,
    )

    rows = list_ip_calendar_projection_reconciliation_candidates(
        session,
        context=context,
        include_resolved=include_resolved,
        limit=limit,
    )
    return IpCalendarReconciliationCandidateListResponse(
        candidates=[_calendar_reconciliation_candidate_record(row) for row in rows]
    )


@router.post(
    "/calendar-projections/reconciliation-candidates/{candidate_id}/decision",
    response_model=IpCalendarReconciliationCandidateRecord,
)
async def post_ip_calendar_reconciliation_decision(
    candidate_id: str,
    payload: IpCalendarReconciliationDecisionRequest,
    context: IpApprover,
    session: DbSession,
) -> IpCalendarReconciliationCandidateRecord:
    from caseops_api.services.calendar_sync import (
        decide_ip_calendar_projection_reconciliation_candidate,
    )

    row = decide_ip_calendar_projection_reconciliation_candidate(
        session,
        context=context,
        candidate_id=candidate_id,
        action=payload.action,
        evidence_reference=payload.evidence_reference,
        expected_snapshot_sha256=payload.expected_snapshot_sha256,
    )
    return _calendar_reconciliation_candidate_record(row)


@router.get(
    "/deadline-coverages/mine",
    response_model=IpAssignedCoverageListResponse,
)
async def get_ip_assigned_coverage(
    context: IpWriter,
    session: DbSession,
    unacknowledged_only: bool = False,
) -> IpAssignedCoverageListResponse:
    return list_ip_assigned_coverage(
        session, context=context, unacknowledged_only=unacknowledged_only
    )


@router.get(
    "/deadline-coverages/awaiting-me",
    response_model=IpCoverageTransfersAwaitingResponse,
)
async def get_ip_coverage_transfers_awaiting(
    context: IpWriter,
    session: DbSession,
) -> IpCoverageTransfersAwaitingResponse:
    return list_ip_coverage_transfers_awaiting(session, context=context)


@router.post(
    "/deadline-coverages/reassign-preview",
    response_model=IpCoverageReassignPreviewResponse,
)
async def post_ip_coverage_reassign_preview(
    payload: IpCoverageReassignPreviewRequest,
    context: IpWriter,
    session: DbSession,
) -> IpCoverageReassignPreviewResponse:
    return preview_ip_coverage_reassignment(session, context=context, payload=payload)


@router.post(
    "/deadline-coverages/reassign-propose",
    response_model=IpCoverageReassignPreviewResponse,
)
async def post_ip_coverage_reassign_propose(
    payload: IpCoverageReassignProposeRequest,
    context: IpWriter,
    session: DbSession,
) -> IpCoverageReassignPreviewResponse:
    return propose_ip_coverage_reassignment(session, context=context, payload=payload)


@router.post(
    "/deadline-coverages/{coverage_id}/replacement-decision",
    response_model=IpDocketRecordResponse,
)
async def post_ip_coverage_replacement_decision(
    coverage_id: str,
    payload: IpCoverageReplacementDecisionRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDocketRecordResponse:
    return decide_ip_coverage_replacement(
        session, context=context, coverage_id=coverage_id, payload=payload
    )


@router.get("/daily-docket", response_model=IpDailyDocketResponse)
async def get_ip_daily_docket(
    context: IpViewer,
    session: DbSession,
    team: Annotated[str | None, Query(max_length=120)] = None,
    stale_source: Annotated[list[str] | None, Query()] = None,
) -> IpDailyDocketResponse:
    return ip_daily_docket(
        session,
        context=context,
        filters={"team": team} if team else {},
        stale_sources=stale_source or [],
    )


@router.post(
    "/control-reviews",
    response_model=IpControlReviewRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_control_review(
    payload: IpControlReviewCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> IpControlReviewRecord:
    return create_ip_control_review(session, context=context, payload=payload)


@router.get("/control-reviews", response_model=IpControlReviewListResponse)
async def get_ip_control_reviews(
    context: IpViewer,
    session: DbSession,
) -> IpControlReviewListResponse:
    return list_ip_control_reviews(session, context=context)


@router.get("/control-reviews/{review_id}", response_model=IpControlReviewRecord)
async def get_ip_control_review_detail(
    review_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpControlReviewRecord:
    return get_ip_control_review(session, context=context, review_id=review_id)


@router.post("/control-reviews/{review_id}/export", response_model=IpControlReviewRecord)
async def post_ip_control_review_export(
    review_id: str,
    payload: IpControlReviewExportRequest,
    context: IpWriter,
    session: DbSession,
) -> IpControlReviewRecord:
    return record_ip_control_review_export(
        session, context=context, review_id=review_id, payload=payload
    )


@router.post(
    "/control-reviews/{review_id}/exceptions/{docket_id}/{exception_kind}/decision",
    response_model=IpControlReviewRecord,
)
async def post_ip_control_review_exception_decision(
    review_id: str,
    docket_id: str,
    exception_kind: str,
    payload: IpControlReviewExceptionDecisionRequest,
    context: IpWriter,
    session: DbSession,
) -> IpControlReviewRecord:
    return decide_ip_control_review_exception(
        session,
        context=context,
        review_id=review_id,
        docket_id=docket_id,
        exception_kind=exception_kind,
        payload=payload,
    )


@router.post(
    "/control-reviews/{review_id}/samples",
    response_model=IpControlReviewRecord,
)
async def post_ip_control_review_sample(
    review_id: str,
    payload: IpControlReviewSampleRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpControlReviewRecord:
    return record_ip_control_review_sample(
        session,
        context=context,
        review_id=review_id,
        payload=payload,
    )


@router.post("/control-reviews/{review_id}/sign-off", response_model=IpControlReviewRecord)
async def post_ip_control_review_sign_off(
    review_id: str,
    payload: IpControlReviewSignOffRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpControlReviewRecord:
    return sign_off_ip_control_review(
        session, context=context, review_id=review_id, payload=payload
    )


@router.get("/dockets", response_model=IpDocketListResponse)
async def get_ip_dockets(context: IpViewer, session: DbSession) -> IpDocketListResponse:
    return list_ip_dockets(session, context=context)


@router.get("/portfolio", response_model=IpPortfolioListResponse)
async def get_ip_portfolio(
    context: IpViewer,
    session: DbSession,
    query: Annotated[str | None, Query(max_length=200)] = None,
    matter_id: Annotated[str | None, Query(max_length=36)] = None,
    client: Annotated[list[str] | None, Query()] = None,
    proprietor: Annotated[list[str] | None, Query()] = None,
    nice_class: Annotated[list[int] | None, Query()] = None,
    responsible_membership_id: Annotated[list[str] | None, Query()] = None,
    team_id: Annotated[list[str] | None, Query()] = None,
    asset_kind: Annotated[list[str] | None, Query()] = None,
    jurisdiction: Annotated[list[str] | None, Query()] = None,
    office: Annotated[list[str] | None, Query()] = None,
    filing_phase: Annotated[list[str] | None, Query()] = None,
    docket_status: Annotated[list[str] | None, Query()] = None,
    deadline_state: Annotated[list[str] | None, Query()] = None,
    opposition_only: bool = False,
    registry_sync_state: Annotated[list[str] | None, Query()] = None,
    include_inactive: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> IpPortfolioListResponse:
    filters = IpPortfolioFilters(
        query=query,
        matter_id=matter_id,
        client=client or [],
        proprietor=proprietor or [],
        nice_class=nice_class or [],
        responsible_membership_id=responsible_membership_id or [],
        team_id=team_id or [],
        asset_kind=asset_kind or [],
        jurisdiction=jurisdiction or [],
        office=office or [],
        filing_phase=filing_phase or [],
        docket_status=docket_status or [],
        deadline_state=deadline_state or [],
        opposition_only=opposition_only,
        registry_sync_state=registry_sync_state or [],
        include_inactive=include_inactive,
    )
    return list_ip_portfolio(
        session,
        context=context,
        filters=filters,
        limit=limit,
        cursor=cursor,
    )


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


@router.post(
    "/trademark-applications/manual",
    response_model=ManualTrademarkApplicationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_manual_trademark_application(
    payload: ManualTrademarkApplicationCreateRequest,
    context: IpWriter,
    session: DbSession,
) -> ManualTrademarkApplicationCreateResponse:
    docket_id, asset, application, identifier, duplicates = (
        create_manual_trademark_application(
            session,
            context=context,
            payload=payload,
        )
    )
    return ManualTrademarkApplicationCreateResponse(
        docket=get_ip_docket(session, context=context, docket_id=docket_id),
        asset=IpAssetResponse.model_validate(asset),
        application=TrademarkApplicationResponse.model_validate(application),
        identifier=(
            IpIdentifierResponse.model_validate(identifier) if identifier is not None else None
        ),
        duplicate_candidates=[
            IpIdentifierResponse.model_validate(row) for row in duplicates
        ],
    )


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
    "/dockets/{docket_id}/proceedings/{proceeding_id}/stage",
    response_model=IpOppositionStageTransitionResponse,
)
async def post_ip_opposition_stage_transition(
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionStageTransitionRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpOppositionStageTransitionResponse:
    proceeding, event = transition_opposition_stage(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        payload=payload,
    )
    return IpOppositionStageTransitionResponse(
        proceeding=IpProceedingResponse.model_validate(proceeding),
        event=IpDocketEventResponse.model_validate(event),
    )


@router.get(
    "/dockets/{docket_id}/proceedings/{proceeding_id}/opposition-workspace",
    response_model=IpOppositionWorkspaceResponse,
)
async def get_ip_opposition_workspace(
    docket_id: str,
    proceeding_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpOppositionWorkspaceResponse:
    return get_opposition_workspace(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
    )


@router.put(
    "/dockets/{docket_id}/proceedings/{proceeding_id}/opposition-workspace",
    response_model=IpOppositionWorkspaceResponse,
)
async def put_ip_opposition_workspace(
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionWorkspaceUpsertRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpOppositionWorkspaceResponse:
    return save_opposition_workspace(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        payload=payload,
    )


@router.get(
    "/dockets/{docket_id}/proceedings/{proceeding_id}/applicant-workflow",
    response_model=IpOppositionApplicantWorkflowResponse,
)
async def get_ip_opposition_applicant_workflow(
    docket_id: str,
    proceeding_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpOppositionApplicantWorkflowResponse:
    return get_applicant_workflow(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
    )


@router.post(
    "/dockets/{docket_id}/proceedings/{proceeding_id}/applicant-actions",
    response_model=IpOppositionApplicantWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_ip_opposition_applicant_action(
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionApplicantActionRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpOppositionApplicantWorkflowResponse:
    return record_applicant_action(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/proceedings/{proceeding_id}/applicant-deadlines",
    response_model=IpOppositionApplicantDeadlineRecord,
    status_code=status.HTTP_201_CREATED,
)
def post_ip_opposition_applicant_deadline(
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionApplicantDeadlineProposalRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpOppositionApplicantDeadlineRecord:
    return propose_applicant_deadline(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        payload=payload,
    )


@router.get(
    "/dockets/{docket_id}/proceedings/{proceeding_id}/opponent-workflow",
    response_model=IpOppositionOpponentWorkflowResponse,
)
async def get_ip_opposition_opponent_workflow(
    docket_id: str,
    proceeding_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpOppositionOpponentWorkflowResponse:
    return get_opponent_workflow(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
    )


@router.post(
    "/dockets/{docket_id}/proceedings/{proceeding_id}/opponent-actions",
    response_model=IpOppositionOpponentWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_ip_opposition_opponent_action(
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionOpponentActionRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpOppositionOpponentWorkflowResponse:
    return record_opponent_action(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/proceedings/{proceeding_id}/opponent-deadlines",
    response_model=IpOppositionOpponentDeadlineRecord,
    status_code=status.HTTP_201_CREATED,
)
def post_ip_opposition_opponent_deadline(
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionOpponentDeadlineProposalRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpOppositionOpponentDeadlineRecord:
    return propose_opponent_deadline(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        payload=payload,
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


@router.get(
    "/dockets/{docket_id}/identifiers/{identifier_id}/duplicates",
    response_model=IpDuplicatePreviewResponse,
)
async def get_ip_identifier_duplicates(
    docket_id: str,
    identifier_id: str,
    context: IpViewer,
    session: DbSession,
) -> IpDuplicatePreviewResponse:
    return preview_ip_identifier_duplicates(
        session,
        context=context,
        docket_id=docket_id,
        identifier_id=identifier_id,
    )


@router.post(
    "/dockets/{docket_id}/identifiers/{identifier_id}/reconcile",
    response_model=IpDuplicateResolutionResponse,
)
async def post_ip_identifier_reconciliation(
    docket_id: str,
    identifier_id: str,
    payload: IpDuplicateResolutionRequest,
    context: IpWriter,
    session: DbSession,
) -> IpDuplicateResolutionResponse:
    return resolve_ip_identifier_duplicate(
        session,
        context=context,
        docket_id=docket_id,
        identifier_id=identifier_id,
        payload=payload,
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
    "/dockets/{docket_id}/deadline-incidents/{incident_id}/impact-scan",
    response_model=IpDocketRecordResponse,
)
async def post_ip_deadline_incident_impact_scan(
    docket_id: str,
    incident_id: str,
    payload: IpDeadlineIncidentImpactScanRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return record_ip_deadline_incident_impact_scan(
        session,
        context=context,
        docket_id=docket_id,
        incident_id=incident_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/deadline-incidents/{incident_id}/actions",
    response_model=IpDocketRecordResponse,
)
async def post_ip_deadline_incident_action(
    docket_id: str,
    incident_id: str,
    payload: IpDeadlineIncidentActionRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return record_ip_deadline_incident_action(
        session,
        context=context,
        docket_id=docket_id,
        incident_id=incident_id,
        payload=payload,
    )


@router.post(
    "/dockets/{docket_id}/deadline-incidents/{incident_id}/notification-decisions",
    response_model=IpDocketRecordResponse,
)
async def post_ip_deadline_incident_notification_decision(
    docket_id: str,
    incident_id: str,
    payload: IpDeadlineIncidentNotificationDecisionRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return decide_ip_deadline_incident_notification(
        session,
        context=context,
        docket_id=docket_id,
        incident_id=incident_id,
        payload=payload,
    )


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


@router.post(
    "/dockets/{docket_id}/deadline-incidents/{incident_id}/kill-switches/{feature_id}/release",
    response_model=IpDocketRecordResponse,
)
async def post_ip_deadline_incident_kill_switch_release(
    docket_id: str,
    incident_id: str,
    feature_id: str,
    payload: IpIncidentKillSwitchReleaseRequest,
    context: IpReviewer,
    session: DbSession,
) -> IpDocketRecordResponse:
    return release_ip_incident_kill_switch(
        session,
        context=context,
        docket_id=docket_id,
        incident_id=incident_id,
        feature_id=feature_id,
        payload=payload,
    )


@router.delete("/dockets/{docket_id}/deadline-incidents/{incident_id}")
async def delete_ip_deadline_incident(
    docket_id: str,
    incident_id: str,
    context: IpReviewer,
    session: DbSession,
) -> None:
    retain_ip_deadline_incident(
        session,
        context=context,
        docket_id=docket_id,
        incident_id=incident_id,
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


@router.get(
    "/reports/foundation-contract",
    response_model=IpReportFoundationContract,
)
async def get_ip_report_foundation_contract(
    context: IpViewer,
) -> IpReportFoundationContract:
    del context
    return ip_report_foundation_contract()


@router.post("/reports/preview", response_model=IpReportPreviewResponse)
async def post_ip_report_preview(
    payload: IpReportPreviewRequest,
    context: IpViewer,
    session: DbSession,
) -> IpReportPreviewResponse:
    return preview_ip_report(session, context=context, payload=payload)
