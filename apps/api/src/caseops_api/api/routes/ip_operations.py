from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.ip_operations import (
    IpCostItemCreateRequest,
    IpDeadlineCoverageCreateRequest,
    IpDeadlineCoverageReassignRequest,
    IpDeadlineIncidentCreateRequest,
    IpDeadlineIncidentVerifyRequest,
    IpDocketControlReport,
    IpDocketCreateRequest,
    IpDocketListResponse,
    IpDocketRecordResponse,
    IpDocketVersionCreateRequest,
    IpNoticeLinkCreateRequest,
    IpTitleInterestCreateRequest,
)
from caseops_api.services.ip_operations import (
    add_ip_cost_item,
    add_ip_deadline_coverage,
    add_ip_deadline_incident,
    add_ip_notice_link,
    add_ip_title_interest,
    append_ip_docket_version,
    create_ip_docket,
    get_ip_docket,
    ip_docket_control_report,
    list_ip_dockets,
    reassign_ip_deadline_coverage,
    verify_ip_deadline_incident,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
IpViewer = Annotated[SessionContext, Depends(require_capability("ip:view"))]
IpWriter = Annotated[SessionContext, Depends(require_capability("ip:write"))]
IpReviewer = Annotated[SessionContext, Depends(require_capability("ip:review"))]
IpFinance = Annotated[SessionContext, Depends(require_capability("ip:finance"))]


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


@router.post("/dockets/{docket_id}/cost-items", response_model=IpDocketRecordResponse)
async def post_ip_cost_item(
    docket_id: str,
    payload: IpCostItemCreateRequest,
    context: IpFinance,
    session: DbSession,
) -> IpDocketRecordResponse:
    return add_ip_cost_item(session, context=context, docket_id=docket_id, payload=payload)


@router.get("/reports/docket-control", response_model=IpDocketControlReport)
async def get_ip_docket_control_report(
    context: IpViewer,
    session: DbSession,
) -> IpDocketControlReport:
    return ip_docket_control_report(session, context=context)
