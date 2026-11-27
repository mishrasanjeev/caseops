"""ENH-001: firm branding settings and public billing-document verification."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.core.rate_limit import document_verification_rate_limit, limiter
from caseops_api.schemas.document_branding import (
    BillingDocumentVerificationResponse,
    BrandingImageKind,
    DocumentBrandingRecord,
    DocumentBrandingUpdateRequest,
)
from caseops_api.services.billing_document_verification import verify_billing_document
from caseops_api.services.document_branding import (
    branding_image_bytes,
    get_document_branding,
    remove_branding_image,
    update_document_branding,
    upload_branding_image,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
public_router = APIRouter()
BrandingAdmin = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]


@router.get(
    "",
    response_model=DocumentBrandingRecord,
    summary="Read the firm branding printed on billing PDFs",
)
def get_branding(context: BrandingAdmin, session: DbSession) -> DocumentBrandingRecord:
    return get_document_branding(session, context=context)


@router.patch(
    "",
    response_model=DocumentBrandingRecord,
    summary="Update the authorised signatory and watermark for billing PDFs",
)
def patch_branding(
    payload: DocumentBrandingUpdateRequest,
    context: BrandingAdmin,
    session: DbSession,
) -> DocumentBrandingRecord:
    return update_document_branding(session, context=context, payload=payload)


@router.put(
    "/{kind}",
    response_model=DocumentBrandingRecord,
    summary="Upload the firm logo or authorised signature (PNG or JPEG)",
)
def put_branding_image(
    kind: BrandingImageKind,
    context: BrandingAdmin,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> DocumentBrandingRecord:
    return upload_branding_image(
        session,
        context=context,
        kind=kind,
        filename=file.filename or "",
        content_type=file.content_type,
        stream=file.file,
    )


@router.delete(
    "/{kind}",
    response_model=DocumentBrandingRecord,
    summary="Remove the firm logo or authorised signature",
)
def delete_branding_image(
    kind: BrandingImageKind,
    context: BrandingAdmin,
    session: DbSession,
) -> DocumentBrandingRecord:
    return remove_branding_image(session, context=context, kind=kind)


@router.get(
    "/{kind}",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
    summary="Fetch the stored logo or signature for the settings preview",
)
def get_branding_image(
    kind: BrandingImageKind, context: BrandingAdmin, session: DbSession
) -> Response:
    return Response(
        content=branding_image_bytes(session, context=context, kind=kind),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@public_router.get(
    "/billing-documents/{token}",
    response_model=BillingDocumentVerificationResponse,
    summary="Verify a billing PDF from the code printed on it (public, minimal)",
)
@limiter.limit(document_verification_rate_limit)
def get_billing_document_verification(
    token: str,
    request: Request,
    response: Response,
    session: DbSession,
) -> BillingDocumentVerificationResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return verify_billing_document(session, token=token)
