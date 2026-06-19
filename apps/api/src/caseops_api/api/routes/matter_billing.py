from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.matter_billing import (
    InvoiceNumberPreviewResponse,
    MatterBillingProfileCreateRequest,
    MatterBillingProfileListResponse,
    MatterBillingProfileRecord,
    MatterBillingProfileUpdateRequest,
    MatterBillingRateCreateRequest,
    MatterBillingRateRecord,
)
from caseops_api.services.matter_billing import (
    add_billing_rate,
    create_billing_profile,
    list_billing_profiles,
    preview_invoice_number,
    update_billing_profile,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
BillingAdmin = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]


@router.get(
    "",
    response_model=MatterBillingProfileListResponse,
    summary="List tenant matter billing profiles and rates",
)
async def get_matter_billing_profiles(
    context: BillingAdmin,
    session: DbSession,
) -> MatterBillingProfileListResponse:
    return MatterBillingProfileListResponse(
        profiles=list_billing_profiles(session, context=context),
    )


@router.post(
    "",
    response_model=MatterBillingProfileRecord,
    summary="Create a tenant matter billing profile",
)
async def post_matter_billing_profile(
    payload: MatterBillingProfileCreateRequest,
    context: BillingAdmin,
    session: DbSession,
) -> MatterBillingProfileRecord:
    return create_billing_profile(session, context=context, payload=payload)


@router.patch(
    "/{profile_id}",
    response_model=MatterBillingProfileRecord,
    summary="Update a tenant matter billing profile",
)
async def patch_matter_billing_profile(
    profile_id: str,
    payload: MatterBillingProfileUpdateRequest,
    context: BillingAdmin,
    session: DbSession,
) -> MatterBillingProfileRecord:
    return update_billing_profile(
        session,
        context=context,
        profile_id=profile_id,
        payload=payload,
    )


@router.post(
    "/{profile_id}/rates",
    response_model=MatterBillingRateRecord,
    summary="Add a rate rule to a matter billing profile",
)
async def post_matter_billing_rate(
    profile_id: str,
    payload: MatterBillingRateCreateRequest,
    context: BillingAdmin,
    session: DbSession,
) -> MatterBillingRateRecord:
    return add_billing_rate(
        session,
        context=context,
        profile_id=profile_id,
        payload=payload,
    )


@router.get(
    "/invoice-number-preview",
    response_model=InvoiceNumberPreviewResponse,
    summary="Preview the next matter invoice number",
)
async def get_matter_invoice_number_preview(
    context: BillingAdmin,
    session: DbSession,
    profile_id: str | None = None,
) -> InvoiceNumberPreviewResponse:
    return preview_invoice_number(session, context=context, profile_id=profile_id)
