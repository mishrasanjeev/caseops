from __future__ import annotations

from datetime import UTC, datetime
from json import JSONDecodeError

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterInvoice,
    MatterInvoicePaymentAttempt,
    MembershipRole,
    PaymentAttemptStatus,
    PaymentWebhookEvent,
)
from caseops_api.schemas.billing import (
    InvoicePaymentAttemptRecord,
    PaymentLinkCreateRequest,
    PaymentWebhookAckResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matters import _append_activity
from caseops_api.services.pine_labs import (
    PineLabsGatewayClient,
    PineLabsPaymentStatusResult,
    WebhookSecretNotConfigured,
    dump_provider_payload,
    redact_provider_payload,
    verify_pine_labs_signature,
)


def _payment_attempt_record(attempt: MatterInvoicePaymentAttempt) -> InvoicePaymentAttemptRecord:
    return InvoicePaymentAttemptRecord(
        id=attempt.id,
        invoice_id=attempt.invoice_id,
        initiated_by_membership_id=attempt.initiated_by_membership_id,
        initiated_by_name=(
            attempt.initiated_by_membership.user.full_name
            if attempt.initiated_by_membership and attempt.initiated_by_membership.user
            else None
        ),
        provider=attempt.provider,
        merchant_order_id=attempt.merchant_order_id,
        provider_order_id=attempt.provider_order_id,
        status=attempt.status,
        amount_minor=attempt.amount_minor,
        amount_received_minor=attempt.amount_received_minor,
        currency=attempt.currency,
        customer_name=attempt.customer_name,
        customer_email=attempt.customer_email,
        customer_phone=attempt.customer_phone,
        payment_url=attempt.payment_url,
        provider_reference=attempt.provider_reference,
        last_webhook_at=attempt.last_webhook_at,
        created_at=attempt.created_at,
        updated_at=attempt.updated_at,
    )


def _get_gateway_client() -> PineLabsGatewayClient:
    return PineLabsGatewayClient()


def _get_invoice(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    invoice_id: str,
) -> MatterInvoice:
    invoice = session.scalar(
        select(MatterInvoice)
        .options(
            joinedload(MatterInvoice.issued_by_membership).joinedload(CompanyMembership.user),
            selectinload(MatterInvoice.payment_attempts)
            .joinedload(MatterInvoicePaymentAttempt.initiated_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(MatterInvoice.line_items),
        )
        .join(Matter, Matter.id == MatterInvoice.matter_id)
        .where(
            MatterInvoice.id == invoice_id,
            MatterInvoice.matter_id == matter_id,
            Matter.company_id == company_id,
        )
    )
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    return invoice


def _update_invoice_collection_state(invoice: MatterInvoice, *, amount_received_minor: int) -> None:
    invoice.amount_received_minor = max(invoice.amount_received_minor, amount_received_minor)
    invoice.balance_due_minor = max(invoice.total_amount_minor - invoice.amount_received_minor, 0)
    if invoice.balance_due_minor == 0:
        invoice.status = "paid"
    elif invoice.amount_received_minor > 0:
        invoice.status = "partially_paid"
    elif invoice.status == "draft":
        invoice.status = "issued"


def create_invoice_payment_link(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    invoice_id: str,
    payload: PaymentLinkCreateRequest,
) -> InvoicePaymentAttemptRecord:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and admins can start Pine Labs payment collection.",
        )

    invoice = _get_invoice(
        session,
        company_id=context.company.id,
        matter_id=matter_id,
        invoice_id=invoice_id,
    )
    if invoice.status == "void":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Void invoices cannot be sent to Pine Labs for collection.",
        )
    if invoice.balance_due_minor <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invoice has no balance due for collection.",
        )

    amount_minor = payload.amount_minor or invoice.balance_due_minor
    merchant_order_id = (
        f"{context.company.slug}-{invoice.invoice_number}-{len(invoice.payment_attempts) + 1}"
    )
    attempt = MatterInvoicePaymentAttempt(
        company_id=context.company.id,
        invoice_id=invoice.id,
        initiated_by_membership_id=context.membership.id,
        merchant_order_id=merchant_order_id,
        amount_minor=amount_minor,
        currency=invoice.currency,
        customer_name=payload.customer_name or invoice.client_name,
        customer_email=payload.customer_email,
        customer_phone=payload.customer_phone,
        status=PaymentAttemptStatus.PENDING,
    )
    session.add(attempt)
    session.flush()

    settings = get_settings()
    gateway_client = _get_gateway_client()
    return_url = f"{settings.public_app_url}/billing/invoices/{invoice.id}"
    webhook_url = f"{settings.public_app_url}/api/payments/pine-labs/webhook"

    try:
        gateway_result = gateway_client.create_payment_link(
            merchant_order_id=attempt.merchant_order_id,
            amount_minor=attempt.amount_minor,
            currency=attempt.currency,
            customer_name=attempt.customer_name,
            customer_email=attempt.customer_email,
            customer_phone=attempt.customer_phone,
            description=payload.description or invoice.notes,
            return_url=return_url,
            webhook_url=webhook_url,
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Pine Labs payment link creation failed: {exc}",
        ) from exc

    attempt.provider_order_id = gateway_result.provider_order_id
    attempt.payment_url = gateway_result.payment_url
    attempt.provider_reference = gateway_result.provider_reference
    attempt.provider_payload_json = dump_provider_payload(
        redact_provider_payload(gateway_result.raw_payload),
    )
    attempt.status = gateway_result.status
    invoice.pine_labs_payment_url = gateway_result.payment_url
    invoice.pine_labs_order_id = gateway_result.provider_order_id or attempt.merchant_order_id
    if invoice.status == "draft":
        invoice.status = "issued"
    session.add_all([attempt, invoice])
    _append_activity(
        session,
        matter_id=matter_id,
        actor_membership_id=context.membership.id,
        event_type="pine_labs_payment_link_created",
        title="Pine Labs payment link created",
        detail=f"{invoice.invoice_number} is ready for collection.",
    )
    session.flush()
    record_from_context(
        session,
        context,
        action="invoice.payment_link_issued",
        target_type="invoice",
        target_id=invoice.id,
        matter_id=matter_id,
        metadata={
            "invoice_number": invoice.invoice_number,
            "attempt_id": attempt.id,
            "amount_minor": invoice.total_amount_minor,
            "currency": invoice.currency,
        },
    )
    session.commit()
    refreshed_attempt = session.scalar(
        select(MatterInvoicePaymentAttempt)
        .options(
            joinedload(MatterInvoicePaymentAttempt.initiated_by_membership).joinedload(
                CompanyMembership.user
            ),
        )
        .where(MatterInvoicePaymentAttempt.id == attempt.id)
    )
    assert refreshed_attempt is not None
    return _payment_attempt_record(refreshed_attempt)


def sync_invoice_payment_link(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    invoice_id: str,
) -> InvoicePaymentAttemptRecord:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and admins can sync Pine Labs payment status.",
        )

    invoice = _get_invoice(
        session,
        company_id=context.company.id,
        matter_id=matter_id,
        invoice_id=invoice_id,
    )
    latest_attempt = invoice.payment_attempts[0] if invoice.payment_attempts else None
    if not latest_attempt or not latest_attempt.provider_order_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Pine Labs payment attempt was found for this invoice.",
        )

    gateway_client = _get_gateway_client()
    try:
        result = gateway_client.fetch_payment_status(
            provider_order_id=latest_attempt.provider_order_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Pine Labs payment status sync failed: {exc}",
        ) from exc

    _apply_payment_result(
        session,
        invoice=invoice,
        attempt=latest_attempt,
        result=result,
        actor_membership_id=context.membership.id,
        event_type="pine_labs_payment_status_synced",
        title="Pine Labs payment status synced",
    )
    session.commit()
    refreshed_attempt = session.scalar(
        select(MatterInvoicePaymentAttempt).options(
            joinedload(MatterInvoicePaymentAttempt.initiated_by_membership).joinedload(
                CompanyMembership.user
            )
        )
        .where(MatterInvoicePaymentAttempt.id == latest_attempt.id)
    )
    assert refreshed_attempt is not None
    return _payment_attempt_record(refreshed_attempt)


def _apply_payment_result(
    session: Session,
    *,
    invoice: MatterInvoice,
    attempt: MatterInvoicePaymentAttempt,
    result: PineLabsPaymentStatusResult,
    actor_membership_id: str | None,
    event_type: str,
    title: str,
) -> None:
    attempt.provider_order_id = result.provider_order_id or attempt.provider_order_id
    attempt.provider_reference = result.provider_reference
    attempt.amount_received_minor = max(attempt.amount_received_minor, result.amount_received_minor)
    attempt.status = result.status
    attempt.provider_payload_json = dump_provider_payload(
        redact_provider_payload(result.raw_payload),
    )
    attempt.last_webhook_at = datetime.now(UTC)

    if result.status in {
        PaymentAttemptStatus.PAID,
        PaymentAttemptStatus.PARTIALLY_PAID,
        "paid",
        "partially_paid",
    }:
        received_amount = result.amount_received_minor
        if received_amount == 0 and result.status in {PaymentAttemptStatus.PAID, "paid"}:
            received_amount = attempt.amount_minor
        _update_invoice_collection_state(
            invoice,
            amount_received_minor=received_amount,
        )
    elif invoice.status == "draft":
        invoice.status = "issued"

    invoice.pine_labs_order_id = attempt.provider_order_id or attempt.merchant_order_id
    invoice.pine_labs_payment_url = attempt.payment_url
    session.add_all([attempt, invoice])
    _append_activity(
        session,
        matter_id=invoice.matter_id,
        actor_membership_id=actor_membership_id,
        event_type=event_type,
        title=title,
        detail=f"{invoice.invoice_number} is now {invoice.status}.",
    )


def _extract_provider_event_id(payload: dict[str, object]) -> str | None:
    for key in ("event_id", "webhook_event_id", "id", "notification_id", "reference_id"):
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _load_attempt_with_company(
    session: Session,
    *,
    provider_order_id: str | None,
) -> MatterInvoicePaymentAttempt | None:
    if not provider_order_id:
        return None
    return session.scalar(
        select(MatterInvoicePaymentAttempt)
        .options(
            joinedload(MatterInvoicePaymentAttempt.invoice)
            .joinedload(MatterInvoice.matter)
            .joinedload(Matter.company),
        )
        .where(
            (MatterInvoicePaymentAttempt.provider_order_id == provider_order_id)
            | (MatterInvoicePaymentAttempt.merchant_order_id == provider_order_id)
        )
    )


async def handle_pine_labs_webhook(
    session: Session,
    *,
    request: Request,
) -> PaymentWebhookAckResponse:
    raw_body = await request.body()
    signature = request.headers.get(get_settings().pine_labs_webhook_signature_header)
    try:
        signature_valid = verify_pine_labs_signature(raw_body=raw_body, signature=signature)
    except WebhookSecretNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if not signature_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Pine Labs webhook signature.",
        )

    try:
        payload = await request.json()
    except (JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must be valid JSON.",
        ) from exc

    gateway_client = _get_gateway_client()
    result = gateway_client.parse_webhook_payload(payload)
    provider_event_id = _extract_provider_event_id(payload)

    if provider_event_id:
        existing_event = session.scalar(
            select(PaymentWebhookEvent).where(
                PaymentWebhookEvent.provider == "pine_labs",
                PaymentWebhookEvent.provider_event_id == provider_event_id,
            )
        )
        if existing_event:
            return PaymentWebhookAckResponse(
                accepted=True,
                provider="pine_labs",
                provider_order_id=result.provider_order_id,
                already_processed=True,
            )

    event = PaymentWebhookEvent(
        provider="pine_labs",
        provider_event_id=provider_event_id,
        provider_order_id=result.provider_order_id,
        event_type=str(payload.get("event_type", "payment_status")),
        signature=signature,
        payload_json=dump_provider_payload(redact_provider_payload(payload)),
        processing_status="received",
    )
    session.add(event)

    attempt = _load_attempt_with_company(
        session,
        provider_order_id=result.provider_order_id,
    )
    if not attempt:
        event.processing_status = "ignored"
        session.add(event)
        session.commit()
        return PaymentWebhookAckResponse(
            accepted=True,
            provider="pine_labs",
            provider_order_id=result.provider_order_id,
        )

    merchant_order_id = attempt.merchant_order_id or ""
    company_slug = attempt.invoice.matter.company.slug if attempt.invoice else ""
    if not merchant_order_id.startswith(f"{company_slug}-"):
        event.processing_status = "cross_tenant_rejected"
        session.add(event)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Webhook tenant does not match the invoice tenant.",
        )

    invoice = session.scalar(
        select(MatterInvoice)
        .options(
            selectinload(MatterInvoice.payment_attempts),
            selectinload(MatterInvoice.line_items),
        )
        .where(MatterInvoice.id == attempt.invoice_id)
    )
    assert invoice is not None
    _apply_payment_result(
        session,
        invoice=invoice,
        attempt=attempt,
        result=result,
        actor_membership_id=None,
        event_type="pine_labs_webhook_received",
        title="Pine Labs webhook processed",
    )
    event.processing_status = "processed"
    session.add(event)
    session.commit()
    return PaymentWebhookAckResponse(
        accepted=True,
        provider="pine_labs",
        provider_order_id=result.provider_order_id,
    )
