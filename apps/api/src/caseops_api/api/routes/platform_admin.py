from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.db.models import BillingEnrollment, PlatformAdminMembership
from caseops_api.schemas.saas_billing import (
    PlatformCouponCreateRequest,
    PlatformGrantCreditsRequest,
    PlatformManualInvoiceCreateRequest,
    PlatformManualInvoicePaidRequest,
    PlatformOveragePolicyRequest,
    PlatformOverviewResponse,
    PlatformReasonRequest,
    PlatformSubscriptionMutation,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.platform_admin import (
    record_platform_audit,
    require_platform_admin,
)
from caseops_api.services.saas_billing import (
    platform_company_billing_detail,
    platform_company_profitability,
    platform_create_coupon,
    platform_create_manual_invoice,
    platform_grant_credits,
    platform_list_coupons,
    platform_mark_manual_invoice_paid,
    platform_mutate_subscription,
    platform_overview,
    platform_profit_csv,
    platform_profit_report,
    platform_provider_events,
    platform_revenue_csv,
    platform_set_overage_policy,
    platform_usage_report,
)

router = APIRouter()
PlatformContext = Annotated[SessionContext, Depends(get_current_context)]


@dataclass(frozen=True)
class PlatformRouteContext:
    context: SessionContext
    platform_admin: PlatformAdminMembership


def require_platform_capability(platform_capability: str):
    def _dep(context: PlatformContext, session: DbSession) -> PlatformRouteContext:
        return PlatformRouteContext(
            context=context,
            platform_admin=require_platform_admin(
                session,
                context,
                capability=platform_capability,
            ),
        )

    return _dep


PlatformBillingManager = Annotated[
    PlatformRouteContext,
    Depends(require_platform_capability("platform:billing_manage")),
]
PlatformManualOverride = Annotated[
    PlatformRouteContext,
    Depends(require_platform_capability("platform:manual_override")),
]
PlatformPaymentReconciler = Annotated[
    PlatformRouteContext,
    Depends(require_platform_capability("platform:payment_reconcile")),
]
PlatformPlanManager = Annotated[
    PlatformRouteContext,
    Depends(require_platform_capability("platform:plan_manage")),
]


def _download_response(content: bytes, *, filename: str) -> StreamingResponse:
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/overview", response_model=PlatformOverviewResponse)
def get_platform_overview(context: PlatformContext, session: DbSession) -> PlatformOverviewResponse:
    platform_admin = require_platform_admin(
        session,
        context,
        capability="platform:billing_view",
    )
    response = platform_overview(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.overview.viewed",
        target_type="platform_overview",
    )
    session.commit()
    return response


@router.get("/enrollments")
def list_platform_enrollments(context: PlatformContext, session: DbSession) -> dict[str, object]:
    platform_admin = require_platform_admin(session, context, capability="platform:billing_view")
    rows = list(
        session.scalars(
            select(BillingEnrollment).order_by(BillingEnrollment.created_at.desc()).limit(250)
        )
    )
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.enrollments.viewed",
        target_type="billing_enrollment",
    )
    session.commit()
    return {
        "enrollments": [
            {
                "id": row.id,
                "company_id": row.company_id,
                "contact_name": row.contact_name,
                "contact_email": row.contact_email,
                "company_name": row.company_name,
                "segment": row.segment,
                "selected_plan": row.selected_plan,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@router.get("/companies/profitability")
def get_company_profitability(context: PlatformContext, session: DbSession) -> dict[str, object]:
    platform_admin = require_platform_admin(session, context, capability="platform:usage_view")
    rows = platform_company_profitability(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.company_profitability.viewed",
        target_type="billing_profit_rollup",
    )
    session.commit()
    return {"companies": rows}


@router.get("/companies/{company_id}/billing")
def get_company_billing_detail(
    company_id: str,
    context: PlatformContext,
    session: DbSession,
) -> dict[str, object]:
    platform_admin = require_platform_admin(session, context, capability="platform:billing_view")
    response = platform_company_billing_detail(session, company_id)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.company_billing.viewed",
        target_type="company",
        target_id=company_id,
        company_id=company_id,
    )
    session.commit()
    return response


@router.post("/companies/{company_id}/subscription")
def mutate_company_subscription(
    company_id: str,
    payload: PlatformSubscriptionMutation,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> dict[str, object]:
    return platform_mutate_subscription(
        session,
        company_id=company_id,
        payload=payload,
        platform_admin=route_context.platform_admin,
        context=route_context.context,
    )


@router.post("/companies/{company_id}/subscription/suspend")
def suspend_company_subscription(
    company_id: str,
    payload: PlatformReasonRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> dict[str, object]:
    return platform_mutate_subscription(
        session,
        company_id=company_id,
        payload=PlatformSubscriptionMutation(status="suspended", reason=payload.reason),
        platform_admin=route_context.platform_admin,
        context=route_context.context,
    )


@router.post("/companies/{company_id}/subscription/resume")
def resume_company_subscription(
    company_id: str,
    payload: PlatformReasonRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> dict[str, object]:
    return platform_mutate_subscription(
        session,
        company_id=company_id,
        payload=PlatformSubscriptionMutation(status="active", reason=payload.reason),
        platform_admin=route_context.platform_admin,
        context=route_context.context,
    )


@router.post("/companies/{company_id}/credits/grant")
def grant_company_credits(
    company_id: str,
    payload: PlatformGrantCreditsRequest,
    route_context: PlatformManualOverride,
    session: DbSession,
) -> dict[str, object]:
    return platform_grant_credits(
        session,
        company_id=company_id,
        payload=payload,
        platform_admin=route_context.platform_admin,
        context=route_context.context,
    )


@router.post("/manual-invoices")
def create_manual_invoice(
    payload: PlatformManualInvoiceCreateRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> dict[str, object]:
    return platform_create_manual_invoice(
        session,
        payload=payload,
        platform_admin=route_context.platform_admin,
        context=route_context.context,
    )


@router.post("/manual-invoices/{invoice_id}/mark-paid")
def mark_manual_invoice_paid(
    invoice_id: str,
    payload: PlatformManualInvoicePaidRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> dict[str, object]:
    return platform_mark_manual_invoice_paid(
        session,
        invoice_id=invoice_id,
        payload=payload,
        platform_admin=route_context.platform_admin,
        context=route_context.context,
    )


@router.get("/provider-events")
def search_provider_events(
    context: PlatformContext,
    session: DbSession,
    q: str | None = None,
) -> dict[str, object]:
    platform_admin = require_platform_admin(
        session,
        context,
        capability="platform:payment_reconcile",
    )
    rows = platform_provider_events(session, q=q)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.provider_events.viewed",
        target_type="billing_provider_event",
        metadata={"q": q},
    )
    session.commit()
    return {"events": rows}


@router.post("/provider-events/{event_id}/reprocess")
def reprocess_provider_event(
    event_id: str,
    payload: PlatformReasonRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> dict[str, object]:
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.provider_event.reprocess_requested",
        target_type="billing_provider_event",
        target_id=event_id,
        reason=payload.reason,
    )
    session.commit()
    return {"id": event_id, "status": "queued_for_manual_reprocess"}


@router.get("/usage-report")
def get_platform_usage_report(context: PlatformContext, session: DbSession) -> dict[str, object]:
    platform_admin = require_platform_admin(session, context, capability="platform:usage_view")
    rows = platform_usage_report(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.usage_report.viewed",
        target_type="billing_usage_attribution",
    )
    session.commit()
    return {"rows": rows}


@router.get("/profit-report")
def get_platform_profit_report(context: PlatformContext, session: DbSession) -> dict[str, object]:
    platform_admin = require_platform_admin(session, context, capability="platform:usage_view")
    rows = platform_profit_report(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.profit_report.viewed",
        target_type="billing_profit_rollup",
    )
    session.commit()
    return {"rows": rows}


@router.get("/profit/export")
def export_platform_profit(context: PlatformContext, session: DbSession) -> StreamingResponse:
    platform_admin = require_platform_admin(session, context, capability="platform:usage_view")
    content = platform_profit_csv(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.profit_report.exported",
        target_type="billing_profit_rollup",
    )
    session.commit()
    return _download_response(content, filename="caseops-platform-profit.csv")


@router.get("/revenue/export")
def export_platform_revenue(context: PlatformContext, session: DbSession) -> StreamingResponse:
    platform_admin = require_platform_admin(session, context, capability="platform:billing_view")
    content = platform_revenue_csv(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.revenue_report.exported",
        target_type="billing_payment_order",
    )
    session.commit()
    return _download_response(content, filename="caseops-platform-revenue.csv")


@router.get("/coupons")
def list_coupons(context: PlatformContext, session: DbSession) -> dict[str, object]:
    platform_admin = require_platform_admin(session, context, capability="platform:plan_manage")
    rows = platform_list_coupons(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.coupons.viewed",
        target_type="billing_coupon",
    )
    session.commit()
    return {"coupons": rows}


@router.post("/coupons")
def create_coupon(
    payload: PlatformCouponCreateRequest,
    route_context: PlatformPlanManager,
    session: DbSession,
) -> dict[str, object]:
    return platform_create_coupon(
        session,
        payload=payload,
        platform_admin=route_context.platform_admin,
        context=route_context.context,
    )


@router.put("/companies/{company_id}/overage-policy")
def set_overage_policy(
    company_id: str,
    payload: PlatformOveragePolicyRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> dict[str, object]:
    return platform_set_overage_policy(
        session,
        company_id=company_id,
        payload=payload,
        platform_admin=route_context.platform_admin,
        context=route_context.context,
    )


@router.get("/margin-alerts")
def get_margin_alerts(context: PlatformContext, session: DbSession) -> dict[str, object]:
    platform_admin = require_platform_admin(session, context, capability="platform:usage_view")
    overview = platform_overview(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.margin_alerts.viewed",
        target_type="billing_profit_rollup",
    )
    session.commit()
    return {"alerts": overview.margin_alerts}
