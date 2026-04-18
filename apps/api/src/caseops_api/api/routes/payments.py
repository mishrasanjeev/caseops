from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.billing import (
    InvoicePaymentAttemptRecord,
    PaymentLinkCreateRequest,
    PaymentWebhookAckResponse,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.payments import (
    create_invoice_payment_link,
    handle_pine_labs_webhook,
    sync_invoice_payment_link,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
PaymentLinkIssuer = Annotated[
    SessionContext, Depends(require_capability("invoices:send_payment_link"))
]
PaymentSyncer = Annotated[SessionContext, Depends(require_capability('payments:sync'))]


@router.post(
    "/matters/{matter_id}/invoices/{invoice_id}/pine-labs/link",
    response_model=InvoicePaymentAttemptRecord,
    summary="Create a Pine Labs payment link for an invoice",
)
async def create_current_company_invoice_payment_link(
    matter_id: str,
    invoice_id: str,
    payload: PaymentLinkCreateRequest,
    context: PaymentLinkIssuer,
    session: DbSession,
) -> InvoicePaymentAttemptRecord:
    return create_invoice_payment_link(
        session,
        context=context,
        matter_id=matter_id,
        invoice_id=invoice_id,
        payload=payload,
    )


@router.post(
    "/matters/{matter_id}/invoices/{invoice_id}/pine-labs/sync",
    response_model=InvoicePaymentAttemptRecord,
    summary="Sync the latest Pine Labs payment attempt for an invoice",
)
async def sync_current_company_invoice_payment_link(
    matter_id: str,
    invoice_id: str,
    context: PaymentSyncer,
    session: DbSession,
) -> InvoicePaymentAttemptRecord:
    return sync_invoice_payment_link(
        session,
        context=context,
        matter_id=matter_id,
        invoice_id=invoice_id,
    )


@router.post(
    "/pine-labs/webhook",
    response_model=PaymentWebhookAckResponse,
    summary="Receive Pine Labs webhook events",
)
async def pine_labs_webhook(
    request: Request,
    session: DbSession,
) -> PaymentWebhookAckResponse:
    return await handle_pine_labs_webhook(session, request=request)
