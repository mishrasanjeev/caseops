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
    ProviderCostCategory.LLM,
    ProviderCostCategory.EMBEDDING,
    ProviderCostCategory.DOCUMENT_PROCESSING,
    ProviderCostCategory.STORAGE,
    ProviderCostCategory.PAYMENT_FIXED_FEE,
    ProviderCostCategory.SMS,
    ProviderCostCategory.WHATSAPP,
    ProviderCostCategory.MANUAL_SUPPORT,
}
BPS_COST_CATEGORIES = {ProviderCostCategory.PAYMENT_MDR}


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
        effective_from=row.effective_from,
        effective_until=row.effective_until,
        status=row.status,  # type: ignore[arg-type]
        source=row.source,
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
        effective_from=effective_from,
        effective_until=payload.effective_until,
        status="active",
        source=payload.source,
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
    unit_minor, source = effective_cost_minor(
        session,
        category=category,
        provider=provider,
        currency=currency,
    )
    return {
        "category": category,
        "provider": provider,
        "units": units,
        "unit_amount_minor": unit_minor,
        "cost_minor": max(units, 0) * unit_minor,
        "source": source,
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
    lines = [
        {
            "category": ProviderCostCategory.PAYMENT_MDR,
            "provider": "pine_labs_plural",
            "units": payment_amount_minor,
            "unit_amount_bps": payment_mdr_bps,
            "cost_minor": payment_cost - payment_fixed_minor * payload.payment_count,
            "source": payment_mdr_source,
        },
        {
            "category": ProviderCostCategory.PAYMENT_FIXED_FEE,
            "provider": "pine_labs_plural",
            "units": payload.payment_count,
            "unit_amount_minor": payment_fixed_minor,
            "cost_minor": payment_fixed_minor * payload.payment_count,
            "source": payment_fixed_source,
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
            category=ProviderCostCategory.LLM,
            provider="llm",
            units=payload.ai_credits,
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
            category=ProviderCostCategory.STORAGE,
            provider="storage",
            units=payload.storage_gb_months,
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
    if gross_profit_minor < 0:
        warnings.append(
            {
                "type": "negative_gross_profit",
                "severity": "critical",
                "message": "Simulation produces negative gross profit.",
            }
        )
    elif gross_margin_bps is not None and gross_margin_bps < 4000:
        warnings.append(
            {
                "type": "low_gross_margin",
                "severity": "warning",
                "message": "Simulation gross margin is below 40%.",
            }
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
        run_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    return _simulation_record(row)


def _simulation_record(row: BillingMarginSimulation) -> MarginSimulationRecord:
    return MarginSimulationRecord(
        id=row.id,
        scenario_name=row.scenario_name,
        currency=row.currency,  # type: ignore[arg-type]
        input=dict(row.input_json or {}),
        result=dict(row.result_json or {}),
        warnings=list(row.warnings_json or []),
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
