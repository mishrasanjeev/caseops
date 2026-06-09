from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingMarginSimulation,
    BillingPlanPrice,
    BillingPlanVersion,
    PlatformAdminMembership,
    ProviderCostCategory,
    ProviderCostProfile,
)
from caseops_api.schemas.provider_costs import (
    MarginReadinessResponse,
    MarginReadinessScenarioStatus,
    MarginSimulationRecord,
    MarginSimulationRunRequest,
    ProviderCostProfileCreateRequest,
    ProviderCostProfileRecord,
    ProviderCostProfileUpdateRequest,
)

CATALOG_VERSION = "2026.05.v1"
CASE_REFRESH_WARNING_MINOR = 10
MONEY_COST_CATEGORIES = {
    ProviderCostCategory.CASE_REFRESH,
    ProviderCostCategory.BULK_CASE_REFRESH,
    ProviderCostCategory.LLM,
    ProviderCostCategory.LLM_INPUT,
    ProviderCostCategory.LLM_OUTPUT,
    ProviderCostCategory.EMBEDDING,
    ProviderCostCategory.DOCUMENT_PROCESSING,
    ProviderCostCategory.OCR_PAGE,
    ProviderCostCategory.STORAGE,
    ProviderCostCategory.BANDWIDTH_EXPORT,
    ProviderCostCategory.PAYMENT_FIXED_FEE,
    ProviderCostCategory.PAYMENT_REFUND_FEE,
    ProviderCostCategory.PAYMENT_CHARGEBACK_FEE,
    ProviderCostCategory.EMAIL,
    ProviderCostCategory.SMS,
    ProviderCostCategory.WHATSAPP,
    ProviderCostCategory.MANUAL_SUPPORT,
}
BPS_COST_CATEGORIES = {ProviderCostCategory.PAYMENT_MDR}
REQUIRED_MARGIN_SCENARIOS: tuple[tuple[str, str], ...] = (
    ("solo_light_user", "Solo light user"),
    ("solo_heavy_court_user", "Solo heavy court user"),
    ("small_law_office_heavy_litigation", "Small law office heavy litigation"),
    ("large_law_firm_many_tracked_cases", "Large law firm many tracked cases"),
    ("corporate_gc_heavy_document_workload", "Corporate GC heavy document workload"),
    ("abusive_usage_pattern", "Abusive usage pattern"),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _profile_record(row: ProviderCostProfile) -> ProviderCostProfileRecord:
    return ProviderCostProfileRecord(
        id=row.id,
        category=row.category,  # type: ignore[arg-type]
        provider=row.provider,
        currency=row.currency,  # type: ignore[arg-type]
        unit_amount_minor=row.unit_amount_minor,
        unit_amount_bps=row.unit_amount_bps,
        unit_label=row.unit_label,
        effective_from=row.effective_from,
        effective_until=row.effective_until,
        status=row.status,  # type: ignore[arg-type]
        source=row.source,
        tax_fee_notes=row.tax_fee_notes,
        cost_basis=row.cost_basis,  # type: ignore[arg-type]
        confidence_level=row.confidence_level,  # type: ignore[arg-type]
        evidence_ref=row.evidence_ref,
        founder_approval_status=row.founder_approval_status,  # type: ignore[arg-type]
        approved_at=row.approved_at,
        approved_by_platform_admin_id=row.approved_by_platform_admin_id,
        notes=row.notes,
        created_by_platform_admin_id=row.created_by_platform_admin_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_provider_cost_profiles(session: Session) -> list[ProviderCostProfileRecord]:
    rows = session.scalars(
        select(ProviderCostProfile).order_by(
            ProviderCostProfile.category.asc(),
            ProviderCostProfile.provider.asc(),
            ProviderCostProfile.effective_from.desc(),
        )
    )
    return [_profile_record(row) for row in rows]


def _validate_profile_payload(
    *,
    category: str,
    unit_amount_minor: int | None,
    unit_amount_bps: int | None,
) -> None:
    if category in BPS_COST_CATEGORIES:
        if unit_amount_bps is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{category} requires unit_amount_bps.",
            )
        return
    if category in MONEY_COST_CATEGORIES:
        if unit_amount_minor is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{category} requires unit_amount_minor.",
            )
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported provider cost category: {category}.",
    )


def create_provider_cost_profile(
    session: Session,
    *,
    payload: ProviderCostProfileCreateRequest,
    platform_admin: PlatformAdminMembership,
) -> ProviderCostProfileRecord:
    effective_from = payload.effective_from or _now()
    _validate_profile_payload(
        category=payload.category,
        unit_amount_minor=payload.unit_amount_minor,
        unit_amount_bps=payload.unit_amount_bps,
    )
    row = ProviderCostProfile(
        category=payload.category,
        provider=payload.provider,
        currency=payload.currency,
        unit_amount_minor=payload.unit_amount_minor,
        unit_amount_bps=payload.unit_amount_bps,
        unit_label=payload.unit_label,
        effective_from=effective_from,
        effective_until=payload.effective_until,
        status="active",
        source=payload.source,
        tax_fee_notes=payload.tax_fee_notes,
        cost_basis=payload.cost_basis,
        confidence_level=payload.confidence_level,
        evidence_ref=payload.evidence_ref,
        founder_approval_status=payload.founder_approval_status,
        approved_at=(
            _now()
            if payload.founder_approval_status == "approved"
            and payload.cost_basis == "actual"
            else None
        ),
        approved_by_platform_admin_id=(
            platform_admin.id
            if payload.founder_approval_status == "approved"
            and payload.cost_basis == "actual"
            else None
        ),
        notes=payload.notes,
        created_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    return _profile_record(row)


def update_provider_cost_profile(
    session: Session,
    *,
    profile_id: str,
    payload: ProviderCostProfileUpdateRequest,
    platform_admin: PlatformAdminMembership | None = None,
) -> ProviderCostProfileRecord:
    row = session.get(ProviderCostProfile, profile_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider cost profile not found.",
        )
    update = payload.model_dump(exclude_unset=True)
    for key, value in update.items():
        setattr(row, key, value)
    if row.founder_approval_status == "approved" and row.cost_basis == "actual":
        row.approved_at = row.approved_at or _now()
        if platform_admin is not None:
            row.approved_by_platform_admin_id = platform_admin.id
    elif row.founder_approval_status != "approved":
        row.approved_at = None
        row.approved_by_platform_admin_id = None
    _validate_profile_payload(
        category=row.category,
        unit_amount_minor=row.unit_amount_minor,
        unit_amount_bps=row.unit_amount_bps,
    )
    row.updated_at = _now()
    session.add(row)
    session.flush()
    return _profile_record(row)


def _fallback_minor(category: str) -> int:
    settings = get_settings()
    if category == ProviderCostCategory.CASE_REFRESH:
        return settings.billing_case_refresh_cost_minor
    if category == ProviderCostCategory.LLM:
        return settings.billing_llm_cost_minor_per_credit
    if category == ProviderCostCategory.STORAGE:
        return settings.billing_storage_cost_minor_per_gb_month
    if category == ProviderCostCategory.PAYMENT_FIXED_FEE:
        return settings.pine_labs_fixed_fee_minor
    if category == ProviderCostCategory.BULK_CASE_REFRESH:
        return settings.billing_case_refresh_cost_minor
    if category == ProviderCostCategory.OCR_PAGE:
        return settings.billing_llm_cost_minor_per_credit
    if category == ProviderCostCategory.LLM_INPUT:
        return settings.billing_llm_cost_minor_per_credit
    if category == ProviderCostCategory.LLM_OUTPUT:
        return settings.billing_llm_cost_minor_per_credit
    if category == ProviderCostCategory.BANDWIDTH_EXPORT:
        return 0
    if category == ProviderCostCategory.EMAIL:
        return 0
    if category == ProviderCostCategory.PAYMENT_REFUND_FEE:
        return 0
    if category == ProviderCostCategory.PAYMENT_CHARGEBACK_FEE:
        return 0
    return 0


def _fallback_bps(category: str) -> int:
    settings = get_settings()
    if category == ProviderCostCategory.PAYMENT_MDR:
        return max(
            settings.billing_payment_gateway_fee_bps,
            settings.pine_labs_mdr_bps_upi,
            settings.pine_labs_mdr_bps_card,
            settings.pine_labs_mdr_bps_netbanking,
        )
    return 0


def _active_profile(
    session: Session,
    *,
    category: str,
    provider: str = "default",
    currency: str = "INR",
    at: datetime | None = None,
) -> ProviderCostProfile | None:
    effective_at = at or _now()
    provider_key = (provider or "default").strip().lower()
    candidates = list(
        session.scalars(
            select(ProviderCostProfile).where(
                ProviderCostProfile.category == category,
                ProviderCostProfile.currency == currency,
                ProviderCostProfile.status == "active",
                ProviderCostProfile.effective_from <= effective_at,
            )
        )
    )
    candidates = [
        row
        for row in candidates
        if row.effective_until is None or row.effective_until > effective_at
    ]
    candidates.sort(
        key=lambda row: (
            1 if row.provider == provider_key else 0,
            1 if row.provider == "default" else 0,
            row.effective_from,
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def effective_cost_minor(
    session: Session,
    *,
    category: str,
    provider: str = "default",
    currency: str = "INR",
    at: datetime | None = None,
) -> tuple[int, str]:
    row = _active_profile(
        session,
        category=category,
        provider=provider,
        currency=currency,
        at=at,
    )
    if row is not None and row.unit_amount_minor is not None:
        return int(row.unit_amount_minor), "configured"
    return _fallback_minor(category), "fallback_default"


def _cost_readiness(row: ProviderCostProfile | None, source: str) -> tuple[bool, str]:
    if row is None or source == "fallback_default":
        return True, "fallback_default"
    if row.cost_basis != "actual":
        return True, "estimated_cost"
    if row.founder_approval_status != "approved":
        return True, "unapproved_cost"
    return False, "approved_actual"


def effective_cost_bps(
    session: Session,
    *,
    category: str,
    provider: str = "default",
    currency: str = "INR",
    at: datetime | None = None,
) -> tuple[int, str]:
    row = _active_profile(
        session,
        category=category,
        provider=provider,
        currency=currency,
        at=at,
    )
    if row is not None and row.unit_amount_bps is not None:
        return int(row.unit_amount_bps), "configured"
    return _fallback_bps(category), "fallback_default"


def estimate_payment_gateway_cost_minor(
    session: Session,
    *,
    amount_minor: int,
    payment_count: int = 1,
    provider: str = "pine_labs_plural",
    currency: str = "INR",
    at: datetime | None = None,
) -> int:
    bps, _ = effective_cost_bps(
        session,
        category=ProviderCostCategory.PAYMENT_MDR,
        provider=provider,
        currency=currency,
        at=at,
    )
    fixed, _ = effective_cost_minor(
        session,
        category=ProviderCostCategory.PAYMENT_FIXED_FEE,
        provider=provider,
        currency=currency,
        at=at,
    )
    return round(max(amount_minor, 0) * bps / 10_000) + max(payment_count, 0) * fixed


def case_refresh_guardrail_warnings(session: Session) -> list[dict[str, object]]:
    row = _active_profile(
        session,
        category=ProviderCostCategory.CASE_REFRESH,
        provider="case_tracking",
    )
    if (
        row is None
        or row.unit_amount_minor is None
        or row.unit_amount_minor < CASE_REFRESH_WARNING_MINOR
    ):
        return []
    return [
        {
            "type": "case_refresh_cost_guardrail",
            "severity": "warning",
            "category": ProviderCostCategory.CASE_REFRESH,
            "provider": row.provider,
            "unit_amount_minor": row.unit_amount_minor,
            "message": (
                "Actual tracked-case refresh cost is INR 0.10 or more. "
                "Pause public high-volume fixed-price bundles or require founder quote review."
            ),
        }
    ]


def _plan_revenue_minor(
    session: Session,
    *,
    plan_code: str,
    interval: str,
) -> int:
    row = session.scalar(
        select(BillingPlanPrice)
        .join(BillingPlanVersion, BillingPlanPrice.plan_version_id == BillingPlanVersion.id)
        .where(
            BillingPlanVersion.plan_code == plan_code,
            BillingPlanVersion.version == CATALOG_VERSION,
            BillingPlanPrice.interval == interval,
        )
    )
    if row is None or row.amount_minor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Plan price is unavailable for this margin simulation.",
        )
    return int(row.amount_minor)


def _cost_line(
    session: Session,
    *,
    category: str,
    units: int,
    provider: str = "default",
    currency: str = "INR",
) -> dict[str, object]:
    active = _active_profile(
        session,
        category=category,
        provider=provider,
        currency=currency,
    )
    if active is not None and active.unit_amount_minor is not None:
        unit_minor = int(active.unit_amount_minor)
        source = "configured"
    else:
        unit_minor = _fallback_minor(category)
        source = "fallback_default"
    unapproved, readiness_reason = _cost_readiness(active, source)
    return {
        "category": category,
        "provider": provider,
        "units": units,
        "unit_amount_minor": unit_minor,
        "cost_minor": max(units, 0) * unit_minor,
        "source": source,
        "cost_basis": active.cost_basis if active else "estimated",
        "confidence_level": active.confidence_level if active else "low",
        "founder_approval_status": active.founder_approval_status if active else "pending",
        "readiness_blocking": unapproved,
        "readiness_reason": readiness_reason,
    }


def run_margin_simulation(
    session: Session,
    *,
    payload: MarginSimulationRunRequest,
    platform_admin: PlatformAdminMembership,
) -> MarginSimulationRecord:
    revenue_minor = payload.revenue_minor
    if revenue_minor is None and payload.plan_code:
        revenue_minor = _plan_revenue_minor(
            session,
            plan_code=payload.plan_code,
            interval=payload.billing_interval,
        )
    assert revenue_minor is not None
    payment_amount_minor = payload.payment_amount_minor or revenue_minor
    payment_cost = estimate_payment_gateway_cost_minor(
        session,
        amount_minor=payment_amount_minor,
        payment_count=payload.payment_count,
        currency=payload.currency,
    )
    payment_mdr_bps, payment_mdr_source = effective_cost_bps(
        session,
        category=ProviderCostCategory.PAYMENT_MDR,
        provider="pine_labs_plural",
        currency=payload.currency,
    )
    payment_fixed_minor, payment_fixed_source = effective_cost_minor(
        session,
        category=ProviderCostCategory.PAYMENT_FIXED_FEE,
        provider="pine_labs_plural",
        currency=payload.currency,
    )
    payment_mdr_profile = _active_profile(
        session,
        category=ProviderCostCategory.PAYMENT_MDR,
        provider="pine_labs_plural",
        currency=payload.currency,
    )
    payment_fixed_profile = _active_profile(
        session,
        category=ProviderCostCategory.PAYMENT_FIXED_FEE,
        provider="pine_labs_plural",
        currency=payload.currency,
    )
    payment_mdr_unapproved, payment_mdr_readiness = _cost_readiness(
        payment_mdr_profile,
        payment_mdr_source,
    )
    payment_fixed_unapproved, payment_fixed_readiness = _cost_readiness(
        payment_fixed_profile,
        payment_fixed_source,
    )
    lines = [
        {
            "category": ProviderCostCategory.PAYMENT_MDR,
            "provider": "pine_labs_plural",
            "units": payment_amount_minor,
            "unit_amount_bps": payment_mdr_bps,
            "cost_minor": payment_cost - payment_fixed_minor * payload.payment_count,
            "source": payment_mdr_source,
            "cost_basis": payment_mdr_profile.cost_basis if payment_mdr_profile else "estimated",
            "confidence_level": (
                payment_mdr_profile.confidence_level if payment_mdr_profile else "low"
            ),
            "founder_approval_status": (
                payment_mdr_profile.founder_approval_status
                if payment_mdr_profile
                else "pending"
            ),
            "readiness_blocking": payment_mdr_unapproved,
            "readiness_reason": payment_mdr_readiness,
        },
        {
            "category": ProviderCostCategory.PAYMENT_FIXED_FEE,
            "provider": "pine_labs_plural",
            "units": payload.payment_count,
            "unit_amount_minor": payment_fixed_minor,
            "cost_minor": payment_fixed_minor * payload.payment_count,
            "source": payment_fixed_source,
            "cost_basis": (
                payment_fixed_profile.cost_basis if payment_fixed_profile else "estimated"
            ),
            "confidence_level": (
                payment_fixed_profile.confidence_level if payment_fixed_profile else "low"
            ),
            "founder_approval_status": (
                payment_fixed_profile.founder_approval_status
                if payment_fixed_profile
                else "pending"
            ),
            "readiness_blocking": payment_fixed_unapproved,
            "readiness_reason": payment_fixed_readiness,
        },
        _cost_line(
            session,
            category=ProviderCostCategory.CASE_REFRESH,
            provider="case_tracking",
            units=payload.tracked_case_refreshes,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.BULK_CASE_REFRESH,
            provider="case_tracking",
            units=payload.bulk_case_refreshes,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.LLM,
            provider="llm",
            units=payload.ai_credits,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.LLM_INPUT,
            provider="llm",
            units=payload.llm_input_units,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.LLM_OUTPUT,
            provider="llm",
            units=payload.llm_output_units,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.EMBEDDING,
            provider="embedding",
            units=payload.embedding_units,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.DOCUMENT_PROCESSING,
            provider="document_processing",
            units=payload.document_pages,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.OCR_PAGE,
            provider="ocr",
            units=payload.ocr_pages,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.STORAGE,
            provider="storage",
            units=payload.storage_gb_months,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.BANDWIDTH_EXPORT,
            provider="export",
            units=payload.bandwidth_export_gb,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.EMAIL,
            provider="email",
            units=payload.email_messages,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.SMS,
            provider="sms",
            units=payload.sms_messages,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.WHATSAPP,
            provider="whatsapp",
            units=payload.whatsapp_messages,
            currency=payload.currency,
        ),
        _cost_line(
            session,
            category=ProviderCostCategory.MANUAL_SUPPORT,
            provider="manual_support",
            units=payload.manual_support_minutes,
            currency=payload.currency,
        ),
    ]
    total_cost_minor = sum(int(line["cost_minor"]) for line in lines)
    gross_profit_minor = revenue_minor - total_cost_minor
    gross_margin_bps = round(gross_profit_minor * 10_000 / revenue_minor) if revenue_minor else None
    warnings: list[dict[str, object]] = case_refresh_guardrail_warnings(session)
    minimum_gross_margin_bps = (
        payload.minimum_gross_margin_bps
        if payload.minimum_gross_margin_bps is not None
        else get_settings().billing_minimum_gross_margin_bps
    )
    uses_unapproved_estimated_costs = any(
        bool(line.get("readiness_blocking")) for line in lines
    )
    if uses_unapproved_estimated_costs:
        warnings.append(
            {
                "type": "unapproved_estimated_costs",
                "severity": "critical",
                "message": "Simulation uses fallback, estimated, or unapproved cost inputs.",
            }
        )
    if gross_profit_minor < 0:
        warnings.append(
            {
                "type": "negative_gross_profit",
                "severity": "critical",
                "message": "Simulation produces negative gross profit.",
            }
        )
    elif gross_margin_bps is not None and gross_margin_bps < minimum_gross_margin_bps:
        warnings.append(
            {
                "type": "low_gross_margin",
                "severity": "warning",
                "message": "Simulation gross margin is below the founder threshold.",
            }
        )
    readiness_blocked = uses_unapproved_estimated_costs or (
        gross_margin_bps is not None and gross_margin_bps < minimum_gross_margin_bps
    )

    input_json = payload.model_dump(mode="json")
    result: dict[str, Any] = {
        "currency": payload.currency,
        "revenue_minor": revenue_minor,
        "total_variable_cost_minor": total_cost_minor,
        "gross_profit_minor": gross_profit_minor,
        "gross_margin_bps": gross_margin_bps,
        "cost_breakdown": lines,
    }
    row = BillingMarginSimulation(
        scenario_name=payload.scenario_name,
        currency=payload.currency,
        input_json=input_json,
        result_json=result,
        warnings_json=warnings,
        plan_code=payload.plan_code,
        scenario_code=payload.scenario_code,
        minimum_gross_margin_bps=minimum_gross_margin_bps,
        uses_unapproved_estimated_costs=uses_unapproved_estimated_costs,
        readiness_blocked=readiness_blocked,
        founder_approval_status="pending",
        run_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    return _simulation_record(row)


def _simulation_record(row: BillingMarginSimulation) -> MarginSimulationRecord:
    return MarginSimulationRecord(
        id=row.id,
        scenario_name=row.scenario_name,
        plan_code=row.plan_code,
        scenario_code=row.scenario_code,
        currency=row.currency,  # type: ignore[arg-type]
        input=dict(row.input_json or {}),
        result=dict(row.result_json or {}),
        warnings=list(row.warnings_json or []),
        minimum_gross_margin_bps=row.minimum_gross_margin_bps,
        uses_unapproved_estimated_costs=row.uses_unapproved_estimated_costs,
        readiness_blocked=row.readiness_blocked,
        founder_approval_status=row.founder_approval_status,  # type: ignore[arg-type]
        approved_at=row.approved_at,
        approved_by_platform_admin_id=row.approved_by_platform_admin_id,
        run_by_platform_admin_id=row.run_by_platform_admin_id,
        created_at=row.created_at,
    )


def list_margin_simulations(
    session: Session,
    *,
    limit: int = 100,
) -> list[MarginSimulationRecord]:
    rows = session.scalars(
        select(BillingMarginSimulation)
        .order_by(BillingMarginSimulation.created_at.desc())
        .limit(limit)
    )
    return [_simulation_record(row) for row in rows]


def margin_readiness(session: Session) -> MarginReadinessResponse:
    scenario_statuses: list[MarginReadinessScenarioStatus] = []
    blocked = False
    for code, label in REQUIRED_MARGIN_SCENARIOS:
        row = session.scalar(
            select(BillingMarginSimulation)
            .where(BillingMarginSimulation.scenario_code == code)
            .order_by(BillingMarginSimulation.created_at.desc())
            .limit(1)
        )
        missing = row is None
        if missing or (row is not None and row.readiness_blocked):
            blocked = True
        scenario_statuses.append(
            MarginReadinessScenarioStatus(
                scenario_code=code,
                label=label,
                latest_simulation_id=row.id if row else None,
                latest_gross_margin_bps=(
                    int((row.result_json or {}).get("gross_margin_bps"))
                    if row and (row.result_json or {}).get("gross_margin_bps") is not None
                    else None
                ),
                readiness_blocked=True if row is None else row.readiness_blocked,
                uses_unapproved_estimated_costs=(
                    True if row is None else row.uses_unapproved_estimated_costs
                ),
                missing=missing,
            )
        )
    return MarginReadinessResponse(
        minimum_gross_margin_bps=get_settings().billing_minimum_gross_margin_bps,
        required_scenarios=scenario_statuses,
        blocked=blocked,
    )
