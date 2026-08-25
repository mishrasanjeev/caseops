from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse

from caseops_api.api.dependencies import (
    DbSession,
    get_current_portal_user,
    require_capability,
)
from caseops_api.db.models import PortalUser
from caseops_api.schemas.portal_ip import (
    PortalDocumentPublicationCreate,
    PortalGrantRevokeRequest,
    PortalInstructionAcknowledgeRequest,
    PortalInstructionListResponse,
    PortalInstructionRecord,
    PortalInstructionSubmitRequest,
    PortalIpGrantListResponse,
    PortalIpGrantRecord,
    PortalIpRecord,
    PortalIpRecordListResponse,
    PortalPublicationListResponse,
    PortalPublicationRecord,
    PortalReportPublicationCreate,
)
from caseops_api.services.document_storage import resolve_storage_path
from caseops_api.services.portal_ip import (
    acknowledge_portal_instruction,
    get_portal_ip_record,
    get_portal_publication,
    list_admin_ip_grants,
    list_firm_portal_instructions,
    list_portal_ip_records,
    list_portal_publications,
    portal_document_download,
    publish_document_to_portal,
    publish_report_to_portal,
    revoke_ip_grant,
    submit_portal_instruction,
)
from caseops_api.services.session_context import SessionContext

public_router = APIRouter()
admin_router = APIRouter()
internal_router = APIRouter()

CurrentPortalUser = Annotated[PortalUser, Depends(get_current_portal_user)]
PortalGrantManager = Annotated[SessionContext, Depends(require_capability("portal:manage_grants"))]
IpApprover = Annotated[SessionContext, Depends(require_capability("ip:approve"))]
IpWriter = Annotated[SessionContext, Depends(require_capability("ip:write"))]


@public_router.get("/ip-records", response_model=PortalIpRecordListResponse)
async def get_portal_ip_records(
    portal_user: CurrentPortalUser,
    session: DbSession,
) -> PortalIpRecordListResponse:
    return list_portal_ip_records(session, portal_user=portal_user)


@public_router.get("/ip-records/{docket_id}", response_model=PortalIpRecord)
async def get_portal_ip_record_route(
    docket_id: str,
    portal_user: CurrentPortalUser,
    session: DbSession,
) -> PortalIpRecord:
    return get_portal_ip_record(session, portal_user=portal_user, docket_id=docket_id)


@public_router.get("/publications", response_model=PortalPublicationListResponse)
async def get_portal_publications(
    portal_user: CurrentPortalUser,
    session: DbSession,
) -> PortalPublicationListResponse:
    return list_portal_publications(session, portal_user=portal_user)


@public_router.get("/publications/{publication_id}", response_model=PortalPublicationRecord)
async def get_portal_publication_route(
    publication_id: str,
    portal_user: CurrentPortalUser,
    session: DbSession,
) -> PortalPublicationRecord:
    return get_portal_publication(session, portal_user=portal_user, publication_id=publication_id)


@public_router.get("/publications/{publication_id}/document", response_model=None)
async def download_portal_publication_document(
    publication_id: str,
    portal_user: CurrentPortalUser,
    session: DbSession,
) -> FileResponse:
    version = portal_document_download(
        session, portal_user=portal_user, publication_id=publication_id
    )
    path: Path = resolve_storage_path(version.storage_key)
    return FileResponse(
        path=path,
        filename=version.display_name,
        media_type=version.content_type or "application/octet-stream",
    )


@public_router.post(
    "/publications/{publication_id}/instructions",
    response_model=PortalInstructionRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_portal_publication_instruction(
    publication_id: str,
    payload: PortalInstructionSubmitRequest,
    portal_user: CurrentPortalUser,
    session: DbSession,
) -> PortalInstructionRecord:
    return submit_portal_instruction(
        session,
        portal_user=portal_user,
        publication_id=publication_id,
        payload=payload,
    )


@admin_router.get("/portal/ip-grants", response_model=PortalIpGrantListResponse)
async def get_admin_portal_ip_grants(
    context: PortalGrantManager,
    session: DbSession,
) -> PortalIpGrantListResponse:
    return list_admin_ip_grants(session, context=context)


@admin_router.post("/portal/ip-grants/{grant_id}/revoke", response_model=PortalIpGrantRecord)
async def post_admin_portal_ip_grant_revoke(
    grant_id: str,
    payload: PortalGrantRevokeRequest,
    context: PortalGrantManager,
    session: DbSession,
) -> PortalIpGrantRecord:
    return revoke_ip_grant(session, context=context, grant_id=grant_id, payload=payload)


@internal_router.post(
    "/portal/report-publications",
    response_model=PortalPublicationRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_portal_report_publication(
    payload: PortalReportPublicationCreate,
    context: PortalGrantManager,
    _approval: IpApprover,
    session: DbSession,
) -> PortalPublicationRecord:
    return publish_report_to_portal(session, context=context, payload=payload)


@internal_router.post(
    "/portal/document-publications",
    response_model=PortalPublicationRecord,
    status_code=status.HTTP_201_CREATED,
)
async def post_ip_portal_document_publication(
    payload: PortalDocumentPublicationCreate,
    context: PortalGrantManager,
    _approval: IpApprover,
    session: DbSession,
) -> PortalPublicationRecord:
    return publish_document_to_portal(session, context=context, payload=payload)


@internal_router.get("/portal/client-instructions", response_model=PortalInstructionListResponse)
async def get_ip_portal_client_instructions(
    context: IpWriter,
    session: DbSession,
) -> PortalInstructionListResponse:
    return list_firm_portal_instructions(session, context=context)


@internal_router.post(
    "/portal/client-instructions/{instruction_id}/acknowledge",
    response_model=PortalInstructionRecord,
)
async def post_ip_portal_client_instruction_acknowledgement(
    instruction_id: str,
    payload: PortalInstructionAcknowledgeRequest,
    context: IpWriter,
    session: DbSession,
) -> PortalInstructionRecord:
    return acknowledge_portal_instruction(
        session,
        context=context,
        instruction_id=instruction_id,
        payload=payload,
    )
