from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.db.models import BillingEnrollment, PlatformAdminMembership
from caseops_api.schemas.integrations import (
    ConnectorHealthListResponse,
    ConnectorRegistryResponse,
)
from caseops_api.schemas.production_safety import (
    CaseTrackingSupportMatrixCreateRequest,
    CaseTrackingSupportMatrixResponse,
    CaseTrackingSupportMatrixUpdateRequest,
    CreditNoteCreateRequest,
    FinanceListResponse,
    FinanceRecordRequest,
    PasswordResetReadinessResponse,
    PineLabsActivationDecisionRequest,
    PineLabsUATEvidenceRequest,
    PineLabsUATReadinessResponse,
    PineLabsUATRunCreateRequest,
    PlatformOperationalReadinessEvidenceRequest,
    PlatformOperationalReadinessRecord,
    PlatformProductionReadinessResponse,
    ProductionBillingSignoffEvidenceRequest,
    ProductionBillingSignoffResponse,
    SecretRotationEvidenceListResponse,
    SecretRotationEvidenceRequest,
    SettlementImportRequest,
    SettlementImportResponse,
    TDSReconciliationCreateRequest,
)
from caseops_api.schemas.provider_costs import (
    MarginReadinessResponse,
    MarginSimulationListResponse,
    MarginSimulationRecord,
    MarginSimulationRunRequest,
    ProviderCostProfileCreateRequest,
    ProviderCostProfileListResponse,
    ProviderCostProfileRecord,
    ProviderCostProfileUpdateRequest,
)
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
from caseops_api.services.connector_health import list_platform_connector_health
from caseops_api.services.identity import SessionContext
from caseops_api.services.integrations import connector_registry
from caseops_api.services.platform_admin import (
    record_platform_audit,
    require_platform_admin,
)
from caseops_api.services.production_safety import (
    create_chargeback_record,
    create_credit_note,
    create_refund_record,
    create_support_matrix_row,
    create_tds_row,
    finance_export_csv,
    import_settlement_rows,
    latest_or_create_uat_run,
    list_finance_rows,
    list_operational_readiness_evidence,
    list_secret_rotation_evidence,
    list_support_matrix,
    password_reset_readiness,
    pine_labs_uat_readiness,
    production_billing_signoff_status,
    production_readiness_status,
    record_operational_readiness_evidence,
    record_pine_labs_activation_decision,
    record_pine_labs_uat_evidence,
    record_production_billing_signoff_evidence,
    record_secret_rotation_evidence,
    support_matrix_admin_record,
    update_support_matrix_row,
)
from caseops_api.services.provider_costs import (
    create_provider_cost_profile,
    list_margin_simulations,
    list_provider_cost_profiles,
    margin_readiness,
    run_margin_simulation,
    update_provider_cost_profile,
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
from caseops_api.services.security import require_recent_step_up

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
PlatformUsageViewer = Annotated[
    PlatformRouteContext,
    Depends(require_platform_capability("platform:usage_view")),
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


@router.get("/integrations", response_model=ConnectorRegistryResponse)
def get_platform_integrations(
    context: PlatformContext,
    session: DbSession,
) -> ConnectorRegistryResponse:
    platform_admin = require_platform_admin(session, context, capability="platform:usage_view")
    connectors = connector_registry(session, context=context, platform=True)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.integrations.viewed",
        target_type="connector_registry",
        metadata={"connector_count": len(connectors)},
    )
    session.commit()
    return ConnectorRegistryResponse(connectors=connectors)


@router.get("/integrations/health", response_model=ConnectorHealthListResponse)
def get_platform_integrations_health(
    context: PlatformContext,
    session: DbSession,
) -> ConnectorHealthListResponse:
    platform_admin = require_platform_admin(session, context, capability="platform:usage_view")
    response = list_platform_connector_health(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.integrations.health_viewed",
        target_type="connector_health",
        metadata={"record_count": len(response.health)},
    )
    session.commit()
    return response


@router.get("/cost-profiles", response_model=ProviderCostProfileListResponse)
def get_provider_cost_profiles(
    context: PlatformContext,
    session: DbSession,
) -> ProviderCostProfileListResponse:
    platform_admin = require_platform_admin(session, context, capability="platform:usage_view")
    profiles = list_provider_cost_profiles(session)
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.cost_profiles.viewed",
        target_type="provider_cost_profile",
        metadata={"profile_count": len(profiles)},
    )
    session.commit()
    return ProviderCostProfileListResponse(cost_profiles=profiles)


@router.post("/cost-profiles", response_model=ProviderCostProfileRecord)
def create_platform_cost_profile(
    payload: ProviderCostProfileCreateRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> ProviderCostProfileRecord:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="cost_profile_change",
        platform_admin=route_context.platform_admin,
    )
    profile = create_provider_cost_profile(
        session,
        payload=payload,
        platform_admin=route_context.platform_admin,
    )
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.cost_profile.created",
        target_type="provider_cost_profile",
        target_id=profile.id,
        metadata={
            "category": profile.category,
            "provider": profile.provider,
            "currency": profile.currency,
        },
    )
    session.commit()
    return profile


@router.patch("/cost-profiles/{profile_id}", response_model=ProviderCostProfileRecord)
def patch_platform_cost_profile(
    profile_id: str,
    payload: ProviderCostProfileUpdateRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> ProviderCostProfileRecord:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="cost_profile_change",
        platform_admin=route_context.platform_admin,
    )
    profile = update_provider_cost_profile(
        session,
        profile_id=profile_id,
        payload=payload,
        platform_admin=route_context.platform_admin,
    )
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.cost_profile.updated",
        target_type="provider_cost_profile",
        target_id=profile.id,
        metadata={
            "category": profile.category,
            "provider": profile.provider,
            "currency": profile.currency,
            "status": profile.status,
        },
    )
    session.commit()
    return profile


@router.get("/margin-simulations", response_model=MarginSimulationListResponse)
def get_margin_simulations(
    route_context: PlatformUsageViewer,
    session: DbSession,
) -> MarginSimulationListResponse:
    simulations = list_margin_simulations(session)
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.margin_simulations.viewed",
        target_type="billing_margin_simulation",
        metadata={"simulation_count": len(simulations)},
    )
    session.commit()
    return MarginSimulationListResponse(simulations=simulations)


@router.get("/margin-readiness", response_model=MarginReadinessResponse)
def get_margin_readiness(
    route_context: PlatformUsageViewer,
    session: DbSession,
) -> MarginReadinessResponse:
    readiness = margin_readiness(session)
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.margin_readiness.viewed",
        target_type="billing_margin_simulation",
        metadata={"blocked": readiness.blocked},
    )
    session.commit()
    return readiness


@router.post("/margin-simulations/run", response_model=MarginSimulationRecord)
def run_platform_margin_simulation(
    payload: MarginSimulationRunRequest,
    route_context: PlatformUsageViewer,
    session: DbSession,
) -> MarginSimulationRecord:
    simulation = run_margin_simulation(
        session,
        payload=payload,
        platform_admin=route_context.platform_admin,
    )
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.margin_simulation.ran",
        target_type="billing_margin_simulation",
        target_id=simulation.id,
        metadata={
            "scenario_name": simulation.scenario_name,
            "warning_count": len(simulation.warnings),
        },
    )
    session.commit()
    return simulation


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


@router.post("/pine-labs/uat-runs", response_model=PineLabsUATReadinessResponse)
def create_pine_labs_uat_run(
    payload: PineLabsUATRunCreateRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> PineLabsUATReadinessResponse:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="payment_activation_change",
        platform_admin=route_context.platform_admin,
    )
    latest_or_create_uat_run(
        session,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )
    readiness = pine_labs_uat_readiness(
        session,
        platform_admin=route_context.platform_admin,
    )
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.pine_labs_uat_run.created",
        target_type="pine_labs_uat_run",
        target_id=readiness.run_id,
        metadata={"environment": payload.environment, "provider_mode": payload.provider_mode},
    )
    session.commit()
    return readiness


@router.get("/pine-labs/uat-readiness", response_model=PineLabsUATReadinessResponse)
def get_pine_labs_uat_readiness(
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> PineLabsUATReadinessResponse:
    readiness = pine_labs_uat_readiness(
        session,
        platform_admin=route_context.platform_admin,
    )
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.pine_labs_uat_readiness.viewed",
        target_type="pine_labs_uat_run",
        target_id=readiness.run_id,
        metadata={"complete": readiness.complete},
    )
    session.commit()
    return readiness


@router.post("/pine-labs/uat-evidence", response_model=PineLabsUATReadinessResponse)
def post_pine_labs_uat_evidence(
    payload: PineLabsUATEvidenceRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> PineLabsUATReadinessResponse:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="payment_activation_change",
        platform_admin=route_context.platform_admin,
    )
    return record_pine_labs_uat_evidence(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.post("/pine-labs/production-activation")
def post_pine_labs_production_activation_decision(
    payload: PineLabsActivationDecisionRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> dict[str, object]:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="payment_activation_change",
        platform_admin=route_context.platform_admin,
    )
    return record_pine_labs_activation_decision(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.get("/billing-signoff", response_model=ProductionBillingSignoffResponse)
def get_production_billing_signoff(
    route_context: PlatformBillingManager,
    session: DbSession,
) -> ProductionBillingSignoffResponse:
    response = production_billing_signoff_status(
        session,
        platform_admin=route_context.platform_admin,
    )
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.production_billing_signoff.viewed",
        target_type="production_billing_signoff",
        target_id=response.signoff_id,
        metadata={"complete": response.complete},
    )
    session.commit()
    return response


@router.get("/password-reset-readiness", response_model=PasswordResetReadinessResponse)
def get_password_reset_readiness(
    route_context: PlatformBillingManager,
    session: DbSession,
) -> PasswordResetReadinessResponse:
    response = password_reset_readiness()
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.password_reset_readiness.viewed",
        target_type="password_reset_readiness",
        metadata={
            "reset_link_domain": response.reset_link_domain,
            "provider_configured": response.provider_configured,
        },
    )
    session.commit()
    return response


@router.get("/production-readiness", response_model=PlatformProductionReadinessResponse)
def get_platform_production_readiness(
    route_context: PlatformBillingManager,
    session: DbSession,
) -> PlatformProductionReadinessResponse:
    response = production_readiness_status(
        session,
        platform_admin=route_context.platform_admin,
    )
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.production_readiness.viewed",
        target_type="platform_production_readiness",
        metadata={"ready": response.ready, "not_ready_count": len(response.not_ready_reasons)},
    )
    session.commit()
    return response


@router.get(
    "/secret-rotation-readiness",
    response_model=SecretRotationEvidenceListResponse,
)
def get_secret_rotation_readiness(
    route_context: PlatformBillingManager,
    session: DbSession,
) -> SecretRotationEvidenceListResponse:
    response = list_secret_rotation_evidence(session)
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.secret_rotation_readiness.viewed",
        target_type="connector_secret_rotation_evidence",
        metadata={"complete": response.complete, "record_count": len(response.records)},
    )
    session.commit()
    return response


@router.post(
    "/secret-rotation-readiness/evidence",
    response_model=SecretRotationEvidenceListResponse,
)
def post_secret_rotation_readiness_evidence(
    payload: SecretRotationEvidenceRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> SecretRotationEvidenceListResponse:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="connector_credential_change",
        platform_admin=route_context.platform_admin,
    )
    return record_secret_rotation_evidence(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.get(
    "/production-readiness/evidence",
    response_model=list[PlatformOperationalReadinessRecord],
)
def get_platform_operational_readiness_evidence(
    route_context: PlatformBillingManager,
    session: DbSession,
) -> list[PlatformOperationalReadinessRecord]:
    rows = list_operational_readiness_evidence(session)
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.operational_readiness_evidence.viewed",
        target_type="platform_operational_readiness_evidence",
        metadata={"record_count": len(rows)},
    )
    session.commit()
    return rows


@router.post(
    "/production-readiness/evidence",
    response_model=list[PlatformOperationalReadinessRecord],
)
def post_platform_operational_readiness_evidence(
    payload: PlatformOperationalReadinessEvidenceRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> list[PlatformOperationalReadinessRecord]:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="billing_export",
        platform_admin=route_context.platform_admin,
    )
    return record_operational_readiness_evidence(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.post("/billing-signoff/evidence", response_model=ProductionBillingSignoffResponse)
def post_production_billing_signoff_evidence(
    payload: ProductionBillingSignoffEvidenceRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> ProductionBillingSignoffResponse:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="billing_export",
        platform_admin=route_context.platform_admin,
    )
    return record_production_billing_signoff_evidence(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.post("/finance/settlement-imports", response_model=SettlementImportResponse)
def post_settlement_import(
    payload: SettlementImportRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> SettlementImportResponse:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="billing_export",
        platform_admin=route_context.platform_admin,
    )
    return import_settlement_rows(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.get("/finance/{report}", response_model=FinanceListResponse)
def get_finance_report(
    report: str,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> FinanceListResponse:
    rows = list_finance_rows(session, kind=report)
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.finance_report.viewed",
        target_type="billing_finance_report",
        target_id=report,
        metadata={"row_count": len(rows)},
    )
    session.commit()
    return FinanceListResponse(rows=rows)


@router.get("/finance/{report}/export")
def export_finance_report(
    report: str,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> StreamingResponse:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="billing_export",
        platform_admin=route_context.platform_admin,
    )
    content = finance_export_csv(session, report=report)
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.finance_report.exported",
        target_type="billing_finance_report",
        target_id=report,
    )
    session.commit()
    return _download_response(content, filename=f"caseops-{report}.csv")


@router.post("/finance/refunds")
def post_refund_record(
    payload: FinanceRecordRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> dict[str, object]:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="billing_export",
        platform_admin=route_context.platform_admin,
    )
    return create_refund_record(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.post("/finance/credit-notes")
def post_credit_note(
    payload: CreditNoteCreateRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> dict[str, object]:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="billing_export",
        platform_admin=route_context.platform_admin,
    )
    return create_credit_note(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.post("/finance/chargebacks")
def post_chargeback_record(
    payload: FinanceRecordRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> dict[str, object]:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="billing_export",
        platform_admin=route_context.platform_admin,
    )
    return create_chargeback_record(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.post("/finance/tds")
def post_tds_reconciliation_row(
    payload: TDSReconciliationCreateRequest,
    route_context: PlatformPaymentReconciler,
    session: DbSession,
) -> dict[str, object]:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="billing_export",
        platform_admin=route_context.platform_admin,
    )
    return create_tds_row(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )


@router.get("/case-tracking/support-matrix", response_model=CaseTrackingSupportMatrixResponse)
def get_platform_case_tracking_support_matrix(
    route_context: PlatformUsageViewer,
    session: DbSession,
) -> CaseTrackingSupportMatrixResponse:
    rows = list_support_matrix(session)
    record_platform_audit(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        action="platform.case_tracking_support_matrix.viewed",
        target_type="case_tracking_support_matrix",
        metadata={"row_count": len(rows)},
    )
    session.commit()
    return CaseTrackingSupportMatrixResponse(
        rows=[support_matrix_admin_record(row) for row in rows]
    )


@router.post("/case-tracking/support-matrix", response_model=CaseTrackingSupportMatrixResponse)
def post_platform_case_tracking_support_matrix(
    payload: CaseTrackingSupportMatrixCreateRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> CaseTrackingSupportMatrixResponse:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="cost_profile_change",
        platform_admin=route_context.platform_admin,
    )
    row = create_support_matrix_row(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        payload=payload,
    )
    return CaseTrackingSupportMatrixResponse(rows=[row])


@router.patch(
    "/case-tracking/support-matrix/{row_id}",
    response_model=CaseTrackingSupportMatrixResponse,
)
def patch_platform_case_tracking_support_matrix(
    row_id: str,
    payload: CaseTrackingSupportMatrixUpdateRequest,
    route_context: PlatformBillingManager,
    session: DbSession,
) -> CaseTrackingSupportMatrixResponse:
    require_recent_step_up(
        session,
        context=route_context.context,
        purpose="cost_profile_change",
        platform_admin=route_context.platform_admin,
    )
    row = update_support_matrix_row(
        session,
        context=route_context.context,
        platform_admin=route_context.platform_admin,
        row_id=row_id,
        payload=payload,
    )
    return CaseTrackingSupportMatrixResponse(rows=[row])
