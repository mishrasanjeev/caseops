from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse

from caseops_api.api.dependencies import DbSession, get_current_context, require_capability
from caseops_api.db.models import BillingEnrollment, Company
from caseops_api.schemas.companies import BootstrapCompanyRequest
from caseops_api.schemas.saas_billing import (
    AddOnCheckoutRequest,
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingCreditLedgerResponse,
    BillingCurrentResponse,
    BillingInvoiceListResponse,
    BillingPlansResponse,
    BillingUsageReportResponse,
    DemoRequest,
    DemoRequestResponse,
    SubscriptionActionResponse,
    TrialStartRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext, register_company_owner
from caseops_api.services.saas_billing import (
    assert_trial_start_allowed,
    cancel_subscription,
    create_checkout,
    create_demo_request,
    credit_ledger,
    credit_ledger_csv,
    current_billing_state,
    get_checkout,
    invoice_download_json,
    invoice_download_pdf,
    list_invoices,
    list_plan_catalog,
    payments_csv,
    reactivate_subscription,
    spend_csv,
    start_trial_for_company,
    statement_csv,
    statement_pdf,
    sync_checkout,
    usage_report,
)
from caseops_api.services.security import require_recent_step_up

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
BillingAdmin = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]


def _download_response(content: bytes, *, filename: str, media_type: str) -> StreamingResponse:
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/plans", response_model=BillingPlansResponse)
def get_billing_plans(session: DbSession) -> BillingPlansResponse:
    return list_plan_catalog(session, public_only=True)


@router.get("/current", response_model=BillingCurrentResponse)
def get_current_billing(context: CurrentContext, session: DbSession) -> BillingCurrentResponse:
    state = current_billing_state(session, context)
    session.commit()
    return BillingCurrentResponse(**state)


@router.post("/checkout", response_model=BillingCheckoutResponse)
def create_billing_checkout(
    payload: BillingCheckoutRequest,
    context: BillingAdmin,
    session: DbSession,
) -> BillingCheckoutResponse:
    return create_checkout(session, context=context, payload=payload)


@router.get("/checkout/{session_id}", response_model=BillingCheckoutResponse)
def get_billing_checkout(
    session_id: str,
    context: CurrentContext,
    session: DbSession,
) -> BillingCheckoutResponse:
    return get_checkout(session, context=context, session_id=session_id)


@router.post("/checkout/{session_id}/sync", response_model=BillingCheckoutResponse)
def sync_billing_checkout(
    session_id: str,
    context: BillingAdmin,
    session: DbSession,
) -> BillingCheckoutResponse:
    return sync_checkout(session, context=context, session_id=session_id)


@router.post("/subscription/cancel", response_model=SubscriptionActionResponse)
def cancel_current_subscription(
    context: BillingAdmin,
    session: DbSession,
) -> SubscriptionActionResponse:
    subscription = cancel_subscription(session, context=context)
    return SubscriptionActionResponse(subscription=subscription)


@router.post("/subscription/reactivate", response_model=SubscriptionActionResponse)
def reactivate_current_subscription(
    context: BillingAdmin,
    session: DbSession,
) -> SubscriptionActionResponse:
    subscription = reactivate_subscription(session, context=context)
    return SubscriptionActionResponse(subscription=subscription)


@router.get("/usage", response_model=BillingUsageReportResponse)
def get_billing_usage(
    context: CurrentContext,
    session: DbSession,
) -> BillingUsageReportResponse:
    report = usage_report(session, context=context)
    session.commit()
    return report


@router.get("/credit-ledger", response_model=BillingCreditLedgerResponse)
def get_credit_ledger(
    context: CurrentContext,
    session: DbSession,
) -> BillingCreditLedgerResponse:
    response = credit_ledger(session, context=context)
    session.commit()
    return response


@router.get("/credit-ledger/export")
def export_credit_ledger(context: BillingAdmin, session: DbSession) -> StreamingResponse:
    require_recent_step_up(session, context=context, purpose="billing_export")
    content = credit_ledger_csv(session, context=context)
    record_from_context(
        session,
        context,
        action="billing.credit_ledger.exported",
        target_type="billing_credit_ledger",
    )
    session.commit()
    return _download_response(
        content,
        filename="caseops-credit-ledger.csv",
        media_type="text/csv; charset=utf-8",
    )


@router.get("/invoices", response_model=BillingInvoiceListResponse)
def get_billing_invoices(
    context: CurrentContext,
    session: DbSession,
) -> BillingInvoiceListResponse:
    return list_invoices(session, context=context)


@router.get("/invoices/{invoice_id}/download", response_model=None)
def download_billing_invoice(
    invoice_id: str,
    context: BillingAdmin,
    session: DbSession,
    format: Literal["pdf", "json"] = Query(default="pdf"),
) -> Response:
    require_recent_step_up(session, context=context, purpose="billing_export")
    if format == "json":
        content = invoice_download_json(session, context=context, invoice_id=invoice_id)
        media_type = "application/json"
        filename = f"caseops-invoice-{invoice_id}.json"
    else:
        content = invoice_download_pdf(session, context=context, invoice_id=invoice_id)
        media_type = "application/pdf"
        filename = f"caseops-invoice-{invoice_id}.pdf"
    record_from_context(
        session,
        context,
        action="billing.invoice.downloaded",
        target_type="billing_manual_invoice",
        target_id=invoice_id,
    )
    session.commit()
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/payments/export")
def export_payments(context: BillingAdmin, session: DbSession) -> StreamingResponse:
    require_recent_step_up(session, context=context, purpose="billing_export")
    content = payments_csv(session, context=context)
    record_from_context(
        session,
        context,
        action="billing.payments.exported",
        target_type="billing_payment_order",
    )
    session.commit()
    return _download_response(
        content,
        filename="caseops-payments.csv",
        media_type="text/csv; charset=utf-8",
    )


@router.get("/statement", response_model=None)
def download_billing_statement(
    context: BillingAdmin,
    session: DbSession,
    format: Literal["csv", "pdf"] = Query(default="csv"),
) -> Response:
    require_recent_step_up(session, context=context, purpose="billing_export")
    if format == "pdf":
        content = statement_pdf(session, context=context)
        media_type = "application/pdf"
        filename = "caseops-billing-statement.pdf"
    else:
        content = statement_csv(session, context=context)
        media_type = "text/csv; charset=utf-8"
        filename = "caseops-billing-statement.csv"
    record_from_context(
        session,
        context,
        action="billing.statement.downloaded",
        target_type="billing_statement",
    )
    session.commit()
    if format == "pdf":
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return _download_response(
        content,
        filename=filename,
        media_type=media_type,
    )


@router.get("/reports/spend", response_model=BillingUsageReportResponse)
def get_spend_report(context: CurrentContext, session: DbSession) -> BillingUsageReportResponse:
    report = usage_report(session, context=context)
    session.commit()
    return report


@router.get("/reports/spend/export")
def export_spend_report(context: BillingAdmin, session: DbSession) -> StreamingResponse:
    require_recent_step_up(session, context=context, purpose="billing_export")
    content = spend_csv(session, context=context)
    record_from_context(
        session,
        context,
        action="billing.spend_report.exported",
        target_type="billing_usage_report",
    )
    session.commit()
    return _download_response(
        content,
        filename="caseops-spend-report.csv",
        media_type="text/csv; charset=utf-8",
    )


@router.get("/add-ons", response_model=BillingPlansResponse)
def get_billing_add_ons(session: DbSession) -> BillingPlansResponse:
    catalog = list_plan_catalog(session, public_only=True)
    return BillingPlansResponse(version=catalog.version, plans=[], add_ons=catalog.add_ons)


@router.post("/add-ons/checkout", response_model=BillingCheckoutResponse)
def create_add_on_checkout(
    payload: AddOnCheckoutRequest,
    context: BillingAdmin,
    session: DbSession,
) -> BillingCheckoutResponse:
    return create_checkout(session, context=context, payload=payload)


@router.post("/trials")
def start_trial(payload: TrialStartRequest, session: DbSession) -> dict[str, object]:
    assert_trial_start_allowed(session, payload)
    auth = register_company_owner(
        session,
        BootstrapCompanyRequest(
            company_name=payload.company_name,
            company_slug=payload.company_slug,
            company_type=payload.company_type,
            owner_full_name=payload.owner_full_name,
            owner_email=payload.owner_email,
            owner_password=payload.owner_password,
        ),
    )
    company = session.get(Company, auth.company.id)
    assert company is not None
    subscription = start_trial_for_company(
        session,
        company=company,
        selected_plan=payload.selected_plan,
        coupon_code=payload.coupon_code,
    )
    session.add(
        BillingEnrollment(
            company_id=company.id,
            contact_name=payload.owner_full_name,
            contact_email=str(payload.owner_email).lower(),
            contact_mobile=payload.mobile,
            company_name=payload.company_name,
            segment=payload.company_type,
            selected_plan=payload.selected_plan,
            source=payload.source,
            status="trial_started",
            gstin=payload.gstin,
            coupon_code=payload.coupon_code,
        )
    )
    session.commit()
    return {
        "auth": auth.model_dump(mode="json"),
        "subscription_id": subscription.id,
        "trial_end": subscription.trial_end.isoformat() if subscription.trial_end else None,
    }


@router.post("/enrollments/demo-request", response_model=DemoRequestResponse)
def create_enrollment_demo_request(payload: DemoRequest, session: DbSession) -> DemoRequestResponse:
    return create_demo_request(session, payload)
