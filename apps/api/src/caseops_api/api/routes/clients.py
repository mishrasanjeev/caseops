"""Clients CRUD routes (MOD-TS-009 / Sprint S1+S2)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.clients import (
    ClientCreateRequest,
    ClientKycDocumentListResponse,
    ClientKycDocumentRecord,
    ClientListResponse,
    ClientRecord,
    ClientUpdateRequest,
    ClientVerificationUpdateRequest,
    KycDocumentTypeLiteral,
    KycRejectRequest,
    KycSubmitRequest,
    KycVerifyRequest,
    MatterClientAssignmentRecord,
    MatterClientAssignRequest,
    MatterClientVerificationListResponse,
    MatterClientVerificationRecord,
)
from caseops_api.services.client_kyc_documents import (
    KYC_FILE_RESPONSE_HEADERS,
    get_client_kyc_document_download,
    kyc_display_filename,
    list_client_kyc_documents,
    remove_client_kyc_document,
    upload_client_kyc_document,
)
from caseops_api.services.clients import (
    archive_client,
    assign_client_to_matter,
    create_client,
    get_client,
    list_clients,
    list_matter_client_verifications,
    reject_client_kyc,
    remove_client_from_matter,
    submit_client_kyc,
    unarchive_client,
    update_client,
    update_matter_client_verification,
    verify_client_kyc,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()

ClientViewer = Annotated[SessionContext, Depends(require_capability("clients:view"))]
ClientCreator = Annotated[SessionContext, Depends(require_capability("clients:create"))]
ClientEditor = Annotated[SessionContext, Depends(require_capability("clients:edit"))]
ClientArchiver = Annotated[SessionContext, Depends(require_capability("clients:archive"))]
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get("/", response_model=ClientListResponse, summary="List clients")
def get_current_company_clients(
    context: ClientViewer,
    session: DbSession,
) -> ClientListResponse:
    return list_clients(session, context=context)


@router.post("/", response_model=ClientRecord, summary="Create a client")
def post_current_company_client(
    payload: ClientCreateRequest,
    context: ClientCreator,
    session: DbSession,
) -> ClientRecord:
    return create_client(session, context=context, payload=payload)


@router.get(
    "/{client_id}",
    response_model=ClientRecord,
    summary="Fetch a client profile",
)
def get_current_company_client(
    client_id: str,
    context: ClientViewer,
    session: DbSession,
) -> ClientRecord:
    return get_client(session, context=context, client_id=client_id)


@router.patch(
    "/{client_id}",
    response_model=ClientRecord,
    summary="Update a client",
)
def patch_current_company_client(
    client_id: str,
    payload: ClientUpdateRequest,
    context: ClientEditor,
    session: DbSession,
) -> ClientRecord:
    return update_client(
        session, context=context, client_id=client_id, payload=payload,
    )


@router.delete(
    "/{client_id}",
    response_model=ClientRecord,
    summary="Archive a client (soft-delete)",
)
def archive_current_company_client(
    client_id: str,
    context: ClientArchiver,
    session: DbSession,
) -> ClientRecord:
    return archive_client(session, context=context, client_id=client_id)


@router.post(
    "/{client_id}/unarchive",
    response_model=ClientRecord,
    summary="Restore an archived client (BUG-025).",
)
def unarchive_current_company_client(
    client_id: str,
    context: ClientArchiver,
    session: DbSession,
) -> ClientRecord:
    # Same capability as archive — only the staff role-set that can
    # archive a client can put one back. Phase B / BUG-025.
    return unarchive_client(session, context=context, client_id=client_id)


# Phase B M11 slice 3 — KYC lifecycle (US-037 / FT-049 / MOD-TS-013).

KycSubmitter = Annotated[
    SessionContext, Depends(require_capability("clients:kyc_submit")),
]
KycReviewer = Annotated[
    SessionContext, Depends(require_capability("clients:kyc_review")),
]


@router.post(
    "/{client_id}/kyc/submit",
    response_model=ClientRecord,
    summary="Submit a KYC pack for review (moves status to submitted).",
)
def submit_current_company_client_kyc(
    client_id: str,
    payload: KycSubmitRequest,
    context: KycSubmitter,
    session: DbSession,
) -> ClientRecord:
    return submit_client_kyc(
        session, context=context, client_id=client_id, payload=payload,
    )


@router.post(
    "/{client_id}/kyc/verify",
    response_model=ClientRecord,
    summary="Approve a submitted KYC pack (staff only).",
)
def verify_current_company_client_kyc(
    client_id: str,
    payload: KycVerifyRequest,
    context: KycReviewer,
    session: DbSession,
) -> ClientRecord:
    return verify_client_kyc(
        session, context=context, client_id=client_id, payload=payload,
    )


@router.post(
    "/{client_id}/kyc/reject",
    response_model=ClientRecord,
    summary="Reject a submitted KYC pack with a reason (staff only).",
)
def reject_current_company_client_kyc(
    client_id: str,
    payload: KycRejectRequest,
    context: KycReviewer,
    session: DbSession,
) -> ClientRecord:
    return reject_client_kyc(
        session, context=context, client_id=client_id, payload=payload,
    )


# BUG-003: uploaded KYC files. Upload / remove need clients:kyc_submit;
# listing and opening need clients:kyc_submit or clients:kyc_review
# (checked in the service). Every miss across tenant or client is a 404.


@router.get(
    "/{client_id}/kyc/documents",
    response_model=ClientKycDocumentListResponse,
    summary="List a client's current KYC files and the KYC requirements they meet",
)
def get_current_company_client_kyc_documents(
    client_id: str,
    context: ClientViewer,
    session: DbSession,
) -> ClientKycDocumentListResponse:
    return list_client_kyc_documents(session, context=context, client_id=client_id)


@router.post(
    "/{client_id}/kyc/documents",
    response_model=ClientKycDocumentRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a KYC file (PDF or image, virus-scanned) for a client",
)
def post_current_company_client_kyc_document(
    client_id: str,
    context: KycSubmitter,
    session: DbSession,
    document_type: Annotated[KycDocumentTypeLiteral, Form()],
    file: Annotated[UploadFile, File(...)],
    label: Annotated[str | None, Form(max_length=120)] = None,
) -> ClientKycDocumentRecord:
    return upload_client_kyc_document(
        session,
        context=context,
        client_id=client_id,
        document_type=document_type,
        label=label,
        filename=file.filename or "document",
        content_type=file.content_type,
        stream=file.file,
    )


@router.get(
    "/{client_id}/kyc/documents/{document_id}/download",
    response_class=FileResponse,
    summary="Open or download a client KYC file (audited)",
)
def download_current_company_client_kyc_document(
    client_id: str,
    document_id: str,
    context: ClientViewer,
    session: DbSession,
    inline: bool = Query(default=False),
) -> FileResponse:
    doc, path, media_type, disposition = get_client_kyc_document_download(
        session,
        context=context,
        client_id=client_id,
        document_id=document_id,
        inline=inline,
    )
    return FileResponse(
        path=path,
        media_type=media_type,
        filename=kyc_display_filename(doc),
        content_disposition_type=disposition,
        headers=dict(KYC_FILE_RESPONSE_HEADERS),
    )


@router.delete(
    "/{client_id}/kyc/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a KYC file from the client's current pack",
)
def delete_current_company_client_kyc_document(
    client_id: str,
    document_id: str,
    context: KycSubmitter,
    session: DbSession,
) -> Response:
    remove_client_kyc_document(
        session, context=context, client_id=client_id, document_id=document_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------
# Per-matter assignment — mounted under /api/matters/… via
# the same router include. Kept here so the full clients surface
# lives in one file.
# ---------------------------------------------------------------


matter_scoped_router = APIRouter()


@matter_scoped_router.post(
    "/{matter_id}/clients",
    response_model=MatterClientAssignmentRecord,
    summary="Link a client to a matter",
)
def post_matter_client_assignment(
    matter_id: str,
    payload: MatterClientAssignRequest,
    context: ClientEditor,
    session: DbSession,
) -> MatterClientAssignmentRecord:
    return assign_client_to_matter(
        session, context=context, matter_id=matter_id, payload=payload,
    )


@matter_scoped_router.delete(
    "/{matter_id}/clients/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a client from a matter",
)
def delete_matter_client_assignment(
    matter_id: str,
    client_id: str,
    context: ClientEditor,
    session: DbSession,
) -> Response:
    remove_client_from_matter(
        session, context=context, matter_id=matter_id, client_id=client_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@matter_scoped_router.get(
    "/{matter_id}/client-verification",
    response_model=MatterClientVerificationListResponse,
    summary="List client verification status for a matter",
)
def get_matter_client_verification(
    matter_id: str,
    context: ClientViewer,
    session: DbSession,
) -> MatterClientVerificationListResponse:
    return list_matter_client_verifications(
        session, context=context, matter_id=matter_id,
    )


@matter_scoped_router.patch(
    "/{matter_id}/client-verification/{client_id}",
    response_model=MatterClientVerificationRecord,
    summary="Update a matter client's verification workflow",
)
def patch_matter_client_verification(
    matter_id: str,
    client_id: str,
    payload: ClientVerificationUpdateRequest,
    context: KycReviewer,
    session: DbSession,
) -> MatterClientVerificationRecord:
    return update_matter_client_verification(
        session,
        context=context,
        matter_id=matter_id,
        client_id=client_id,
        payload=payload,
    )
