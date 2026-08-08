from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.core.settings import get_settings
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
from caseops_api.services.ip_capability_catalog import ip_workspace_readiness
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
from caseops_api.services.session_context import SessionContext

router = APIRouter()
IpViewer = Annotated[SessionContext, Depends(require_capability("ip:read"))]
IpWriter = Annotated[SessionContext, Depends(require_capability("ip:write"))]
IpReviewer = Annotated[SessionContext, Depends(require_capability("ip:approve"))]
IpFinance = Annotated[SessionContext, Depends(require_capability("ip:fees_manage"))]
IpWorkspaceAdmin = Annotated[
    SessionContext,
    Depends(require_capability("ip:taxonomy_admin")),
]


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
        duplicate_candidates=[
            IpIdentifierResponse.model_validate(row) for row in duplicates
        ],
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
        duplicate_candidates=[
            IpIdentifierResponse.model_validate(row) for row in duplicates
        ],
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
        duplicate_candidates=[
            IpIdentifierResponse.model_validate(row) for row in duplicates
        ],
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
