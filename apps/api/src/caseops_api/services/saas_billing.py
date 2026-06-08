from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditResult,
    BillingAccount,
    BillingCheckoutSession,
    BillingCheckoutStatus,
    BillingCoupon,
    BillingCreditLedger,
    BillingCreditLedgerEventType,
    BillingEnrollment,
    BillingManualInvoice,
    BillingOveragePolicy,
    BillingPaymentOrder,
    BillingPaymentOrderStatus,
    BillingPlanPrice,
    BillingPlanVersion,
    BillingProfitRollup,
    BillingProviderEvent,
    BillingSubscription,
    BillingSubscriptionItem,
    BillingSubscriptionStatus,
    BillingUsageAttribution,
    BillingUsageEvent,
    Company,
    CompanyMembership,
    Matter,
    MatterAttachment,
    MatterStatus,
    MembershipRole,
    PlatformAdminMembership,
    TrackedCase,
    TrackedCaseBookmark,
)
from caseops_api.schemas.saas_billing import (
    AddOnCheckoutRequest,
    BillingAccountRecord,
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingCreditLedgerRecord,
    BillingCreditLedgerResponse,
    BillingInvoiceListResponse,
    BillingInvoiceRecord,
    BillingPlanRecord,
    BillingPlansResponse,
    BillingPriceRecord,
    BillingSubscriptionRecord,
    BillingUsageBreakdownRow,
    BillingUsageReportResponse,
    BillingUsageSnapshot,
    DemoRequest,
    DemoRequestResponse,
    PlatformCouponCreateRequest,
    PlatformGrantCreditsRequest,
    PlatformManualInvoiceCreateRequest,
    PlatformManualInvoicePaidRequest,
    PlatformOveragePolicyRequest,
    PlatformOverviewResponse,
    PlatformSubscriptionMutation,
    TrialStartRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.pine_labs import (
    PineLabsGatewayClient,
    PineLabsPaymentStatusResult,
    redact_provider_payload,
)
from caseops_api.services.platform_admin import record_platform_audit
from caseops_api.services.provider_costs import (
    case_refresh_guardrail_warnings,
    effective_cost_minor,
    estimate_payment_gateway_cost_minor,
)

CATALOG_VERSION = "2026.05.v1"
GRANDFATHERED_PLAN_CODE = "grandfathered_free"
ACTIVE_SUBSCRIPTION_STATUSES = {
    BillingSubscriptionStatus.ACTIVE,
    BillingSubscriptionStatus.TRIALING,
    BillingSubscriptionStatus.GRACE,
    BillingSubscriptionStatus.MANUAL_ACTIVE,
}
TERMINAL_ORDER_STATUSES = {
    BillingPaymentOrderStatus.PAID,
    BillingPaymentOrderStatus.CANCELLED,
    BillingPaymentOrderStatus.REFUNDED,
}
PLAN_CHECKOUT_TYPES = {"new_subscription", "renewal", "upgrade"}
TOPUP_CHECKOUT_TYPES = {"topup", "addon"}
FREE_TRIAL_DOMAIN_EXEMPTIONS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _to_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _period_end(start: datetime, interval: str) -> datetime:
    if interval == "year":
        return start + timedelta(days=365)
    if interval == "one_time":
        return start
    return start + timedelta(days=31)


def _month_window(value: datetime | None = None) -> tuple[datetime, datetime]:
    current = value or _now()
    start = datetime(current.year, current.month, 1, tzinfo=UTC)
    if current.month == 12:
        end = datetime(current.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(current.year, current.month + 1, 1, tzinfo=UTC)
    return start, end


def _coerce_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _plan_entitlements(plan: BillingPlanVersion | None) -> dict[str, Any]:
    if plan is None:
        return {}
    values: dict[str, Any] = {}
    for entitlement in plan.entitlements:
        values[entitlement.entitlement_key] = entitlement.value_json
    return values


def _merge_entitlements(base: dict[str, Any], delta: dict[str, Any], *, quantity: int = 1) -> None:
    for key, value in delta.items():
        if key == "expires_after_months":
            continue
        if isinstance(value, bool):
            base[key] = bool(base.get(key)) or value
            continue
        int_value = _coerce_int(value)
        if int_value is not None:
            base[key] = int(base.get(key) or 0) + int_value * quantity
            continue
        base[key] = value


def _plan_record(row: BillingPlanVersion) -> BillingPlanRecord:
    return BillingPlanRecord(
        id=row.id,
        plan_code=row.plan_code,
        version=row.version,
        segment=row.segment,
        display_name=row.display_name,
        description=row.description,
        publicly_visible=row.publicly_visible,
        trial_eligible=row.trial_eligible,
        prices=[
            BillingPriceRecord(
                id=price.id,
                amount_minor=price.amount_minor,
                currency=price.currency,
                interval=price.interval,
                tax_behavior=price.tax_behavior,
                tax_rate_bps=price.tax_rate_bps,
            )
            for price in sorted(
                row.prices,
                key=lambda item: (item.interval, item.amount_minor or 0),
            )
        ],
        entitlements=_plan_entitlements(row),
    )


def list_plan_catalog(session: Session, *, public_only: bool = True) -> BillingPlansResponse:
    filters = [
        BillingPlanVersion.version == CATALOG_VERSION,
        BillingPlanVersion.status == "active",
    ]
    if public_only:
        filters.append(BillingPlanVersion.publicly_visible.is_(True))
    rows = list(
        session.scalars(
            select(BillingPlanVersion)
            .options(
                selectinload(BillingPlanVersion.prices),
                selectinload(BillingPlanVersion.entitlements),
            )
            .where(*filters)
            .order_by(BillingPlanVersion.segment.asc(), BillingPlanVersion.display_name.asc())
        )
    )
    plans = [_plan_record(row) for row in rows if row.segment != "add_on"]
    add_ons = [_plan_record(row) for row in rows if row.segment == "add_on"]
    return BillingPlansResponse(version=CATALOG_VERSION, plans=plans, add_ons=add_ons)


def _get_plan(
    session: Session,
    plan_code: str,
    *,
    version: str = CATALOG_VERSION,
    for_update: bool = False,
) -> BillingPlanVersion:
    statement = (
        select(BillingPlanVersion)
        .options(
            selectinload(BillingPlanVersion.prices),
            selectinload(BillingPlanVersion.entitlements),
        )
        .where(
            BillingPlanVersion.plan_code == plan_code,
            BillingPlanVersion.version == version,
            BillingPlanVersion.status == "active",
        )
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing plan not found.")
    return row


def _select_price(plan: BillingPlanVersion, interval: str) -> BillingPlanPrice:
    for price in plan.prices:
        if price.interval == interval and price.amount_minor is not None:
            return price
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Selected billing interval is not available for this plan.",
    )


def ensure_billing_account(session: Session, company: Company) -> BillingAccount:
    account = session.scalar(
        select(BillingAccount).where(BillingAccount.company_id == company.id).with_for_update()
    )
    if account is None:
        account = BillingAccount(
            company_id=company.id,
            billing_email=company.billing_contact_email or company.primary_contact_email,
            billing_name=company.billing_contact_name or company.name,
        )
        session.add(account)
        session.flush()
    return account


def _latest_subscription(session: Session, company_id: str) -> BillingSubscription | None:
    rows = list(
        session.scalars(
            select(BillingSubscription)
            .options(
                selectinload(BillingSubscription.items),
                selectinload(BillingSubscription.plan_version).selectinload(
                    BillingPlanVersion.entitlements
                ),
                selectinload(BillingSubscription.plan_version).selectinload(
                    BillingPlanVersion.prices
                ),
            )
            .where(BillingSubscription.company_id == company_id)
            .order_by(BillingSubscription.created_at.desc())
        )
    )
    for row in rows:
        if row.status in ACTIVE_SUBSCRIPTION_STATUSES:
            return row
    return rows[0] if rows else None


def ensure_grandfathered_subscription(session: Session, company: Company) -> BillingSubscription:
    account = ensure_billing_account(session, company)
    subscription = _latest_subscription(session, company.id)
    if subscription is not None:
        return subscription
    plan = _get_plan(session, GRANDFATHERED_PLAN_CODE)
    now = _now()
    subscription = BillingSubscription(
        company_id=company.id,
        billing_account_id=account.id,
        plan_version_id=plan.id,
        status=BillingSubscriptionStatus.MANUAL_ACTIVE,
        segment=plan.segment,
        billing_interval="custom",
        current_period_start=now,
        current_period_end=None,
        source="grandfathered_runtime",
        externally_billable=False,
    )
    session.add(subscription)
    session.flush()
    session.add(
        BillingSubscriptionItem(
            subscription_id=subscription.id,
            item_code=plan.plan_code,
            item_type="base_plan",
            quantity=1,
            amount_minor=0,
            currency="INR",
            interval="custom",
            status="active",
        )
    )
    session.flush()
    return subscription


def _subscription_for_gate(session: Session, company: Company) -> BillingSubscription | None:
    try:
        return ensure_grandfathered_subscription(session, company)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return None
        raise


def resolve_entitlements(session: Session, subscription: BillingSubscription) -> dict[str, Any]:
    entitlements = _plan_entitlements(subscription.plan_version)
    active_items = [item for item in subscription.items if item.status == "active"]
    add_on_codes = {
        item.item_code
        for item in active_items
        if item.item_type == "add_on" and item.item_code != subscription.plan_version.plan_code
    }
    add_on_rows: dict[str, BillingPlanVersion] = {}
    if add_on_codes:
        add_on_rows = {
            row.plan_code: row
            for row in session.scalars(
                select(BillingPlanVersion)
                .options(selectinload(BillingPlanVersion.entitlements))
                .where(
                    BillingPlanVersion.version == CATALOG_VERSION,
                    BillingPlanVersion.plan_code.in_(add_on_codes),
                )
            )
        }
    for item in active_items:
        if item.item_type != "add_on":
            continue
        row = add_on_rows.get(item.item_code)
        if row is not None:
            _merge_entitlements(entitlements, _plan_entitlements(row), quantity=item.quantity)
    if subscription.entitlement_overrides_json:
        entitlements.update(subscription.entitlement_overrides_json)
    return entitlements


def _storage_used_bytes(session: Session, company_id: str) -> int:
    value = session.scalar(
        select(func.coalesce(func.sum(MatterAttachment.size_bytes), 0))
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(Matter.company_id == company_id)
    )
    return int(value or 0)


def _active_matter_count(session: Session, company_id: str) -> int:
    value = session.scalar(
        select(func.count(Matter.id)).where(
            Matter.company_id == company_id,
            Matter.is_active.is_(True),
            Matter.status.in_(
                [MatterStatus.INTAKE, MatterStatus.ACTIVE, MatterStatus.ON_HOLD]
            ),
        )
    )
    return int(value or 0)


def _tracked_case_count(session: Session, company_id: str) -> int:
    value = session.scalar(
        select(func.count(func.distinct(TrackedCaseBookmark.tracked_case_id))).where(
            TrackedCaseBookmark.company_id == company_id,
            TrackedCaseBookmark.is_archived.is_(False),
            TrackedCaseBookmark.active_scope_key.is_not(None),
        )
    )
    return int(value or 0)


def _membership_counts(session: Session, company_id: str) -> tuple[int, int]:
    rows = list(
        session.execute(
            select(CompanyMembership.role, func.count(CompanyMembership.id))
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.is_active.is_(True),
            )
            .group_by(CompanyMembership.role)
        )
    )
    internal = 0
    viewers = 0
    for role, count in rows:
        if role == MembershipRole.VIEWER:
            viewers += int(count or 0)
        else:
            internal += int(count or 0)
    return internal, viewers


def _today_start() -> datetime:
    current = _now()
    return datetime.combine(current.date(), time.min, tzinfo=UTC)


def _manual_refreshes_today(session: Session, company_id: str) -> int:
    value = session.scalar(
        select(func.coalesce(func.sum(BillingUsageAttribution.provider_units), 0)).where(
            BillingUsageAttribution.company_id == company_id,
            BillingUsageAttribution.feature_key == "case_tracking_manual_refresh",
            BillingUsageAttribution.created_at >= _today_start(),
            BillingUsageAttribution.tenant_visible.is_(True),
        )
    )
    return int(value or 0)


def _latest_credit_balance(session: Session, company_id: str) -> int:
    row = session.scalar(
        select(BillingCreditLedger)
        .where(BillingCreditLedger.company_id == company_id)
        .order_by(BillingCreditLedger.created_at.desc(), BillingCreditLedger.id.desc())
        .limit(1)
    )
    return int(row.balance_after if row else 0)


def _append_credit_ledger(
    session: Session,
    *,
    company_id: str,
    subscription_id: str | None,
    credit_bucket: str,
    event_type: str,
    delta: int,
    reason: str | None = None,
    source_object_type: str | None = None,
    source_object_id: str | None = None,
    actor_membership_id: str | None = None,
    platform_admin_id: str | None = None,
    expires_at: datetime | None = None,
) -> BillingCreditLedger:
    current_balance = _latest_credit_balance(session, company_id)
    balance_after = current_balance + delta
    if balance_after < 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="AI credit balance is insufficient for this action.",
        )
    row = BillingCreditLedger(
        company_id=company_id,
        subscription_id=subscription_id,
        credit_bucket=credit_bucket,
        event_type=event_type,
        delta=delta,
        balance_after=balance_after,
        reason=reason,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        actor_membership_id=actor_membership_id,
        platform_admin_id=platform_admin_id,
        expires_at=expires_at,
    )
    session.add(row)
    session.flush()
    return row


def expire_due_ai_credits(session: Session, *, company_id: str) -> None:
    now = _now()
    expired_rows = list(
        session.scalars(
            select(BillingCreditLedger).where(
                BillingCreditLedger.company_id == company_id,
                BillingCreditLedger.delta > 0,
                BillingCreditLedger.expires_at.is_not(None),
                BillingCreditLedger.expires_at <= now,
            )
        )
    )
    for grant in expired_rows:
        already_expired = session.scalar(
            select(BillingCreditLedger.id).where(
                BillingCreditLedger.company_id == company_id,
                BillingCreditLedger.event_type == BillingCreditLedgerEventType.EXPIRY,
                BillingCreditLedger.source_object_type == "billing_credit_ledger",
                BillingCreditLedger.source_object_id == grant.id,
            )
        )
        if already_expired:
            continue
        balance = _latest_credit_balance(session, company_id)
        if balance <= 0:
            continue
        _append_credit_ledger(
            session,
            company_id=company_id,
            subscription_id=grant.subscription_id,
            credit_bucket=grant.credit_bucket,
            event_type=BillingCreditLedgerEventType.EXPIRY,
            delta=-min(grant.delta, balance),
            reason="Credit grant expired.",
            source_object_type="billing_credit_ledger",
            source_object_id=grant.id,
        )


def grant_included_monthly_credits(
    session: Session,
    *,
    subscription: BillingSubscription,
    entitlements: dict[str, Any] | None = None,
) -> None:
    entitlements = entitlements or resolve_entitlements(session, subscription)
    included = int(entitlements.get("ai_credits_monthly") or 0)
    if included <= 0:
        return
    period_start = _to_aware(subscription.current_period_start) or _month_window()[0]
    period_end = _to_aware(subscription.current_period_end) or _period_end(
        period_start, subscription.billing_interval
    )
    source_id = f"{subscription.id}:{period_start.isoformat()}"
    existing = session.scalar(
        select(BillingCreditLedger.id).where(
            BillingCreditLedger.company_id == subscription.company_id,
            BillingCreditLedger.event_type
            == BillingCreditLedgerEventType.INCLUDED_MONTHLY_GRANT,
            BillingCreditLedger.source_object_type == "billing_subscription_period",
            BillingCreditLedger.source_object_id == source_id,
        )
    )
    if existing:
        return
    _append_credit_ledger(
        session,
        company_id=subscription.company_id,
        subscription_id=subscription.id,
        credit_bucket="included",
        event_type=BillingCreditLedgerEventType.INCLUDED_MONTHLY_GRANT,
        delta=included,
        reason="Monthly included AI credit grant.",
        source_object_type="billing_subscription_period",
        source_object_id=source_id,
        expires_at=period_end,
    )


def _usage_snapshot(
    session: Session,
    *,
    company: Company,
    subscription: BillingSubscription,
    entitlements: dict[str, Any],
) -> BillingUsageSnapshot:
    expire_due_ai_credits(session, company_id=company.id)
    grant_included_monthly_credits(session, subscription=subscription, entitlements=entitlements)
    balance = _latest_credit_balance(session, company.id)
    internal, viewers = _membership_counts(session, company.id)
    ai_included = _coerce_int(entitlements.get("ai_credits_monthly"))
    ai_used = int(
        session.scalar(
            select(func.coalesce(func.sum(BillingUsageAttribution.credits_debited), 0)).where(
                BillingUsageAttribution.company_id == company.id,
                BillingUsageAttribution.credits_debited > 0,
                BillingUsageAttribution.tenant_visible.is_(True),
            )
        )
        or 0
    )
    return BillingUsageSnapshot(
        ai_credits_included=ai_included,
        ai_credits_used=ai_used,
        ai_credits_remaining=balance,
        topup_credits_available=max(balance - (ai_included or 0), 0),
        tracked_cases_used=_tracked_case_count(session, company.id),
        tracked_cases_limit=_coerce_int(entitlements.get("tracked_cases_limit")),
        manual_refreshes_used_today=_manual_refreshes_today(session, company.id),
        manual_refreshes_limit_daily=_coerce_int(entitlements.get("manual_case_refreshes_daily")),
        storage_used_bytes=_storage_used_bytes(session, company.id),
        storage_limit_bytes=_coerce_int(entitlements.get("storage_bytes_limit")),
        users_internal_used=internal,
        users_internal_limit=_coerce_int(entitlements.get("users_internal_limit")),
        users_viewer_used=viewers,
        users_viewer_limit=_coerce_int(entitlements.get("users_viewer_limit")),
        matters_active_used=_active_matter_count(session, company.id),
        matters_active_limit=_coerce_int(entitlements.get("matters_active_limit")),
    )


def _account_record(account: BillingAccount | None) -> BillingAccountRecord | None:
    if account is None:
        return None
    return BillingAccountRecord(
        id=account.id,
        company_id=account.company_id,
        billing_email=account.billing_email,
        billing_name=account.billing_name,
        billing_phone=account.billing_phone,
        gstin=account.gstin,
        billing_address=account.billing_address_json,
        tax_treatment=account.tax_treatment,
    )


def _subscription_record(
    subscription: BillingSubscription | None,
) -> BillingSubscriptionRecord | None:
    if subscription is None:
        return None
    return BillingSubscriptionRecord(
        id=subscription.id,
        plan_code=subscription.plan_version.plan_code if subscription.plan_version else None,
        plan_name=subscription.plan_version.display_name if subscription.plan_version else None,
        status=subscription.status,
        segment=subscription.segment,
        billing_interval=subscription.billing_interval,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        trial_end=subscription.trial_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        externally_billable=subscription.externally_billable,
        source=subscription.source,
    )


def current_billing_state(session: Session, context: SessionContext) -> dict[str, Any]:
    subscription = ensure_grandfathered_subscription(session, context.company)
    account = ensure_billing_account(session, context.company)
    entitlements = resolve_entitlements(session, subscription)
    quota = _coerce_int(entitlements.get("storage_bytes_limit"))
    if context.company.storage_quota_bytes != quota:
        context.company.storage_quota_bytes = quota
        session.add(context.company)
    snapshot = _usage_snapshot(
        session,
        company=context.company,
        subscription=subscription,
        entitlements=entitlements,
    )
    session.flush()
    return {
        "billing_account": _account_record(account),
        "subscription": _subscription_record(subscription),
        "entitlements": entitlements,
        "usage": snapshot,
        "payment_provider": provider_readiness(),
    }


def provider_readiness() -> dict[str, Any]:
    settings = get_settings()
    env = settings.pine_labs_env.strip().lower()
    mock = env == "mock"
    configured = bool(
        settings.pine_labs_api_base_url
        and settings.pine_labs_payment_link_path
        and settings.pine_labs_merchant_id
        and (settings.pine_labs_client_id or settings.pine_labs_api_key)
        and (settings.pine_labs_client_secret or settings.pine_labs_api_secret)
    )
    disabled = not mock and (env in {"disabled", "off", "false"} or not configured)
    return {
        "provider": "pine_labs_plural",
        "mode": env,
        "configured": configured,
        "provider_disabled": disabled,
        "mock": mock,
        "subscriptions_enabled": settings.pine_labs_subscriptions_enabled,
    }


def _calculate_amounts(price: BillingPlanPrice, quantity: int) -> tuple[int, int, int]:
    amount = int(price.amount_minor or 0) * quantity
    if price.tax_behavior == "inclusive":
        tax = round(amount * price.tax_rate_bps / (10_000 + price.tax_rate_bps))
        return amount - tax, tax, amount
    tax = round(amount * price.tax_rate_bps / 10_000)
    return amount, tax, amount + tax


def _estimated_payment_gateway_cost_minor(session: Session, amount_minor: int) -> int:
    return estimate_payment_gateway_cost_minor(
        session,
        amount_minor=amount_minor,
        provider="pine_labs_plural",
    )


def _merchant_reference(company: Company, plan_code: str) -> str:
    stamp = _now().strftime("%Y%m%d%H%M%S")
    suffix = uuid4().hex[:8]
    safe_slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in company.slug)
    safe_plan = plan_code.replace("_", "-")
    return f"co-{safe_slug}-{safe_plan}-{stamp}-{suffix}"[:160]


def create_checkout(
    session: Session,
    *,
    context: SessionContext,
    payload: BillingCheckoutRequest | AddOnCheckoutRequest,
) -> BillingCheckoutResponse:
    subscription = ensure_grandfathered_subscription(session, context.company)
    account = ensure_billing_account(session, context.company)
    if isinstance(payload, AddOnCheckoutRequest):
        plan_code = payload.add_on_code
        checkout_type = "topup"
        interval = "one_time"
        quantity = payload.quantity
        metadata = {}
        success_url = payload.success_url
        cancel_url = payload.cancel_url
    else:
        if not payload.plan_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="plan_code is required for subscription checkout.",
            )
        plan_code = payload.plan_code
        checkout_type = payload.checkout_type
        interval = payload.interval
        quantity = payload.quantity
        metadata = dict(payload.metadata or {})
        success_url = payload.success_url
        cancel_url = payload.cancel_url
    plan = _get_plan(session, plan_code)
    if plan.segment == "add_on":
        add_on_interval = "one_time" if plan.prices[0].interval == "one_time" else "month"
        price = _select_price(plan, add_on_interval)
        checkout_type = "topup" if price.interval == "one_time" else "addon"
    else:
        if checkout_type not in PLAN_CHECKOUT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This plan requires a subscription checkout type.",
            )
        price = _select_price(plan, interval)
    amount, tax, total = _calculate_amounts(price, quantity)
    settings = get_settings()
    if total > settings.pine_labs_provider_limit_max_amount_minor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Checkout amount exceeds configured payment provider limit.",
        )
    metadata.update(
        {
            "plan_code": plan.plan_code,
            "price_id": price.id,
            "quantity": quantity,
            "interval": price.interval,
        }
    )
    checkout = BillingCheckoutSession(
        company_id=context.company.id,
        billing_account_id=account.id,
        subscription_id=subscription.id,
        plan_version_id=plan.id,
        checkout_type=checkout_type,
        status=BillingCheckoutStatus.CREATED,
        amount_minor=amount,
        tax_amount_minor=tax,
        total_amount_minor=total,
        currency=price.currency,
        success_url=success_url,
        cancel_url=cancel_url,
        provider="pine_labs_plural",
        expires_at=_now() + timedelta(hours=2),
        metadata_json=metadata,
        created_by_membership_id=context.membership.id,
    )
    session.add(checkout)
    session.flush()
    order = BillingPaymentOrder(
        company_id=context.company.id,
        checkout_session_id=checkout.id,
        subscription_id=subscription.id,
        provider="pine_labs_plural",
        merchant_reference=_merchant_reference(context.company, plan.plan_code),
        status=BillingPaymentOrderStatus.CREATED,
        amount_minor=amount,
        tax_amount_minor=tax,
        currency=price.currency,
    )
    session.add(order)
    session.flush()

    readiness = provider_readiness()
    if readiness["provider_disabled"]:
        checkout.status = BillingCheckoutStatus.PROVIDER_DISABLED
    elif readiness["mock"]:
        provider_order_id = f"mock-{order.id}"
        checkout.status = BillingCheckoutStatus.PAYMENT_PENDING
        checkout.provider_order_id = provider_order_id
        checkout.provider_checkout_url = (
            f"{settings.public_app_url}/billing/checkout/{checkout.id}?provider=mock"
        )
        order.status = BillingPaymentOrderStatus.PENDING
        order.provider_order_id = provider_order_id
        order.payment_url = checkout.provider_checkout_url
    else:
        result = PineLabsGatewayClient().create_payment_link(
            merchant_order_id=order.merchant_reference,
            amount_minor=checkout.total_amount_minor,
            currency=checkout.currency,
            customer_name=account.billing_name or context.company.name,
            customer_email=account.billing_email,
            customer_phone=account.billing_phone,
            description=f"CaseOps {plan.display_name}",
            return_url=success_url or f"{settings.public_app_url}/app/admin/billing",
            webhook_url=f"{settings.public_app_url}/api/payments/pine-labs/webhook",
        )
        checkout.status = BillingCheckoutStatus.PAYMENT_PENDING
        checkout.provider_order_id = result.provider_order_id
        checkout.provider_checkout_url = result.payment_url
        order.status = BillingPaymentOrderStatus.PENDING
        order.provider_order_id = result.provider_order_id
        order.payment_url = result.payment_url
        order.provider_payload_json = redact_provider_payload(result.raw_payload)
    record_from_context(
        session,
        context,
        action="billing.checkout.created",
        target_type="billing_checkout_session",
        target_id=checkout.id,
        metadata={"checkout_type": checkout.checkout_type, "plan_code": plan.plan_code},
    )
    session.commit()
    return checkout_response(checkout)


def checkout_response(checkout: BillingCheckoutSession) -> BillingCheckoutResponse:
    provider_disabled = checkout.status == BillingCheckoutStatus.PROVIDER_DISABLED
    next_action = "provider_disabled" if provider_disabled else "redirect"
    if checkout.status == BillingCheckoutStatus.PAID:
        next_action = "complete"
    elif checkout.status in {BillingCheckoutStatus.FAILED, BillingCheckoutStatus.CANCELLED}:
        next_action = "contact_support"
    return BillingCheckoutResponse(
        id=checkout.id,
        checkout_type=checkout.checkout_type,
        status=checkout.status,
        amount_minor=checkout.amount_minor,
        tax_amount_minor=checkout.tax_amount_minor,
        total_amount_minor=checkout.total_amount_minor,
        currency=checkout.currency,
        provider=checkout.provider,
        provider_checkout_url=checkout.provider_checkout_url,
        provider_order_id=checkout.provider_order_id,
        provider_disabled=provider_disabled,
        next_action=next_action,
        created_at=checkout.created_at,
        expires_at=checkout.expires_at,
    )


def get_checkout(
    session: Session,
    *,
    context: SessionContext,
    session_id: str,
) -> BillingCheckoutResponse:
    checkout = session.scalar(
        select(BillingCheckoutSession).where(
            BillingCheckoutSession.id == session_id,
            BillingCheckoutSession.company_id == context.company.id,
        )
    )
    if checkout is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkout not found.")
    return checkout_response(checkout)


def _order_for_checkout(session: Session, checkout: BillingCheckoutSession) -> BillingPaymentOrder:
    order = session.scalar(
        select(BillingPaymentOrder)
        .where(BillingPaymentOrder.checkout_session_id == checkout.id)
        .order_by(BillingPaymentOrder.created_at.desc())
        .limit(1)
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Checkout does not have a payment order.",
        )
    return order


def sync_checkout(
    session: Session,
    *,
    context: SessionContext,
    session_id: str,
) -> BillingCheckoutResponse:
    checkout = session.scalar(
        select(BillingCheckoutSession).where(
            BillingCheckoutSession.id == session_id,
            BillingCheckoutSession.company_id == context.company.id,
        )
    )
    if checkout is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkout not found.")
    if checkout.status == BillingCheckoutStatus.PROVIDER_DISABLED:
        record_from_context(
            session,
            context,
            action="billing.checkout.sync_provider_disabled",
            target_type="billing_checkout_session",
            target_id=checkout.id,
        )
        session.commit()
        return checkout_response(checkout)
    order = _order_for_checkout(session, checkout)
    readiness = provider_readiness()
    if readiness["mock"]:
        mock_status = str((checkout.metadata_json or {}).get("mock_status") or "paid")
        result = PineLabsPaymentStatusResult(
            provider_order_id=order.provider_order_id,
            provider_reference=order.merchant_reference,
            status=mock_status,
            amount_received_minor=checkout.total_amount_minor if mock_status == "paid" else 0,
            raw_payload={"mock": True, "status": mock_status},
        )
    elif order.provider_order_id:
        result = PineLabsGatewayClient().fetch_payment_status(
            provider_order_id=order.provider_order_id
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Checkout cannot be synced before provider order creation.",
        )
    apply_billing_payment_result(
        session,
        order=order,
        result=result,
        event_source="status_sync",
    )
    record_from_context(
        session,
        context,
        action="billing.checkout.synced",
        target_type="billing_checkout_session",
        target_id=checkout.id,
        metadata={"status": result.status},
    )
    session.commit()
    return checkout_response(checkout)


def _create_or_update_profit_rollup(
    session: Session,
    *,
    order: BillingPaymentOrder,
    checkout: BillingCheckoutSession,
) -> None:
    period_start, period_end = _month_window(order.paid_at or _now())
    row = session.scalar(
        select(BillingProfitRollup).where(
            BillingProfitRollup.company_id == order.company_id,
            BillingProfitRollup.period_start == period_start,
            BillingProfitRollup.period_end == period_end,
        )
    )
    gateway_cost = _estimated_payment_gateway_cost_minor(
        session,
        order.amount_paid_minor or checkout.total_amount_minor,
    )
    if row is None:
        row = BillingProfitRollup(
            company_id=order.company_id,
            subscription_id=order.subscription_id,
            period_start=period_start,
            period_end=period_end,
        )
        session.add(row)
    row.gross_revenue_minor = (row.gross_revenue_minor or 0) + checkout.amount_minor
    row.recognized_revenue_minor = (
        row.recognized_revenue_minor or 0
    ) + checkout.amount_minor
    row.tax_collected_minor = (row.tax_collected_minor or 0) + checkout.tax_amount_minor
    row.payment_gateway_cost_minor = (row.payment_gateway_cost_minor or 0) + gateway_cost
    row.total_variable_cost_minor = (
        (row.payment_gateway_cost_minor or 0)
        + (row.llm_cost_minor or 0)
        + (row.embedding_cost_minor or 0)
        + (row.case_refresh_cost_minor or 0)
        + (row.document_processing_cost_minor or 0)
        + (row.storage_cost_minor or 0)
        + (row.manual_support_cost_minor or 0)
        + (row.manual_research_cost_minor or 0)
    )
    row.gross_profit_minor = row.recognized_revenue_minor - row.total_variable_cost_minor
    if row.recognized_revenue_minor > 0:
        row.gross_margin_bps = round(row.gross_profit_minor * 10_000 / row.recognized_revenue_minor)


def _activate_subscription_from_checkout(
    session: Session,
    *,
    checkout: BillingCheckoutSession,
    order: BillingPaymentOrder,
) -> None:
    subscription = session.get(BillingSubscription, checkout.subscription_id)
    if subscription is None:
        return
    plan = session.get(BillingPlanVersion, checkout.plan_version_id)
    if plan is None:
        return
    now = _now()
    if checkout.checkout_type in PLAN_CHECKOUT_TYPES:
        interval = str((checkout.metadata_json or {}).get("interval") or "month")
        subscription.plan_version_id = plan.id
        subscription.plan_version = plan
        subscription.status = BillingSubscriptionStatus.ACTIVE
        subscription.segment = plan.segment
        subscription.billing_interval = interval
        subscription.current_period_start = now
        subscription.current_period_end = _period_end(now, interval)
        subscription.cancel_at_period_end = False
        subscription.provider = "pine_labs_plural"
        subscription.source = "self_service"
        subscription.externally_billable = True
        item = session.scalar(
            select(BillingSubscriptionItem).where(
                BillingSubscriptionItem.subscription_id == subscription.id,
                BillingSubscriptionItem.item_type == "base_plan",
                BillingSubscriptionItem.status == "active",
            )
        )
        if item is None:
            item = BillingSubscriptionItem(
                subscription_id=subscription.id,
                item_code=plan.plan_code,
                item_type="base_plan",
            )
            session.add(item)
        item.item_code = plan.plan_code
        item.amount_minor = checkout.amount_minor
        item.currency = checkout.currency
        item.interval = interval
        item.status = "active"
        entitlements = resolve_entitlements(session, subscription)
        grant_included_monthly_credits(
            session,
            subscription=subscription,
            entitlements=entitlements,
        )
    elif checkout.checkout_type in TOPUP_CHECKOUT_TYPES:
        entitlements = _plan_entitlements(plan)
        quantity = int((checkout.metadata_json or {}).get("quantity") or 1)
        credit_topup = int(entitlements.get("ai_credits_topup") or 0) * quantity
        if credit_topup > 0:
            expiry_months = int(entitlements.get("expires_after_months") or 12)
            _append_credit_ledger(
                session,
                company_id=checkout.company_id,
                subscription_id=subscription.id,
                credit_bucket="topup",
                event_type=BillingCreditLedgerEventType.TOPUP_PURCHASE,
                delta=credit_topup,
                reason=f"Purchased {plan.display_name}.",
                source_object_type="billing_payment_order",
                source_object_id=order.id,
                expires_at=now + timedelta(days=31 * expiry_months),
            )
        elif plan.prices and plan.prices[0].interval != "one_time":
            session.add(
                BillingSubscriptionItem(
                    subscription_id=subscription.id,
                    item_code=plan.plan_code,
                    item_type="add_on",
                    quantity=quantity,
                    amount_minor=checkout.amount_minor,
                    currency=checkout.currency,
                    interval=plan.prices[0].interval,
                    status="active",
                    provider_item_id=order.provider_order_id,
                )
            )


def apply_billing_payment_result(
    session: Session,
    *,
    order: BillingPaymentOrder,
    result: PineLabsPaymentStatusResult,
    event_source: str,
) -> None:
    checkout = order.checkout_session
    if checkout is None:
        return
    normalized = result.status
    if normalized == "paid":
        if order.status in {BillingPaymentOrderStatus.PAID, BillingPaymentOrderStatus.REFUNDED}:
            return
        order.status = BillingPaymentOrderStatus.PAID
        order.amount_paid_minor = result.amount_received_minor or checkout.total_amount_minor
        order.provider_order_id = result.provider_order_id or order.provider_order_id
        order.provider_payment_id = result.provider_reference or order.provider_payment_id
        order.provider_payload_json = redact_provider_payload(result.raw_payload)
        order.paid_at = _now()
        checkout.status = BillingCheckoutStatus.PAID
        checkout.provider_order_id = order.provider_order_id
        checkout.provider_payment_id = order.provider_payment_id
        _activate_subscription_from_checkout(session, checkout=checkout, order=order)
        _create_or_update_profit_rollup(session, order=order, checkout=checkout)
    elif normalized in {"failed", "cancelled", "expired"}:
        if order.status == BillingPaymentOrderStatus.PAID:
            return
        order.status = (
            BillingPaymentOrderStatus.CANCELLED
            if normalized in {"cancelled", "expired"}
            else BillingPaymentOrderStatus.FAILED
        )
        order.provider_payload_json = redact_provider_payload(result.raw_payload)
        order.failed_at = _now()
        checkout.status = (
            BillingCheckoutStatus.CANCELLED
            if normalized in {"cancelled", "expired"}
            else BillingCheckoutStatus.FAILED
        )
    elif normalized == "refunded":
        if order.status != BillingPaymentOrderStatus.PAID:
            return
        order.status = BillingPaymentOrderStatus.REFUNDED
        order.provider_payload_json = redact_provider_payload(result.raw_payload)
        # Refund and payment-adjustment events are operational records at launch.
        # They must not silently delete data or downgrade an already-activated
        # subscription; platform finance can reconcile or grant adjustments.
    else:
        if order.status not in TERMINAL_ORDER_STATUSES:
            order.status = BillingPaymentOrderStatus.PENDING
            checkout.status = BillingCheckoutStatus.PAYMENT_PENDING
    session.add_all([order, checkout])
    _record_usage_event_for_payment(session, order=order, source=event_source)


def _record_usage_event_for_payment(
    session: Session,
    *,
    order: BillingPaymentOrder,
    source: str,
) -> None:
    if order.status != BillingPaymentOrderStatus.PAID:
        return
    existing = session.scalar(
        select(BillingUsageEvent.id).where(
            BillingUsageEvent.company_id == order.company_id,
            BillingUsageEvent.source_type == "billing_payment_order",
            BillingUsageEvent.source_id == order.id,
        )
    )
    if existing:
        return
    session.add(
        BillingUsageEvent(
            company_id=order.company_id,
            subscription_id=order.subscription_id,
            usage_type="payment_gateway",
            quantity=1,
            unit="order",
            estimated_cost_minor=_estimated_payment_gateway_cost_minor(
                session,
                order.amount_paid_minor,
            ),
            source_type="billing_payment_order",
            source_id=order.id,
            metadata_json={"source": source},
        )
    )


def record_usage(
    session: Session,
    *,
    company_id: str,
    subscription_id: str | None,
    usage_type: str,
    feature_key: str,
    quantity: int,
    unit: str,
    actor_membership_id: str | None = None,
    matter_id: str | None = None,
    tracked_case_id: str | None = None,
    credits_debited: int = 0,
    estimated_cost_minor: int = 0,
    purpose: str | None = None,
    display_label: str | None = None,
    tenant_visible: bool = True,
    source_type: str | None = None,
    source_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BillingUsageAttribution:
    usage_event = BillingUsageEvent(
        company_id=company_id,
        subscription_id=subscription_id,
        usage_type=usage_type,
        quantity=quantity,
        unit=unit,
        estimated_cost_minor=estimated_cost_minor,
        source_type=source_type,
        source_id=source_id,
        metadata_json=metadata,
    )
    session.add(usage_event)
    session.flush()
    attribution = BillingUsageAttribution(
        company_id=company_id,
        subscription_id=subscription_id,
        billing_usage_event_id=usage_event.id,
        actor_membership_id=actor_membership_id,
        matter_id=matter_id,
        tracked_case_id=tracked_case_id,
        feature_key=feature_key,
        purpose=purpose,
        display_label=display_label,
        credits_debited=credits_debited,
        provider_units=quantity,
        estimated_internal_cost_minor=estimated_cost_minor,
        tenant_visible=tenant_visible,
    )
    session.add(attribution)
    session.flush()
    return attribution


def assert_ai_credits_available(
    session: Session,
    *,
    company_id: str | None,
    estimated_credits: int,
) -> None:
    if not company_id or estimated_credits <= 0:
        return
    company = session.get(Company, company_id)
    if company is None:
        return
    subscription = _subscription_for_gate(session, company)
    if subscription is None:
        return
    entitlements = resolve_entitlements(session, subscription)
    if entitlements.get("ai_credits_monthly") is None:
        return
    grant_included_monthly_credits(session, subscription=subscription, entitlements=entitlements)
    expire_due_ai_credits(session, company_id=company_id)
    if _latest_credit_balance(session, company_id) < estimated_credits:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="AI credit balance is insufficient for this action.",
        )


def debit_ai_credits(
    session: Session,
    *,
    company_id: str | None,
    actor_membership_id: str | None,
    matter_id: str | None,
    purpose: str,
    credits: int,
    source_object_type: str | None = None,
    source_object_id: str | None = None,
) -> None:
    if not company_id or credits <= 0:
        return
    company = session.get(Company, company_id)
    if company is None:
        return
    subscription = _subscription_for_gate(session, company)
    if subscription is None:
        return
    entitlements = resolve_entitlements(session, subscription)
    if entitlements.get("ai_credits_monthly") is None:
        llm_cost_minor, _ = effective_cost_minor(
            session,
            category="llm",
            provider=get_settings().llm_provider or "llm",
        )
        record_usage(
            session,
            company_id=company_id,
            subscription_id=subscription.id,
            usage_type="ai_credit",
            feature_key="ai_generation",
            quantity=credits,
            unit="credit",
            actor_membership_id=actor_membership_id,
            matter_id=matter_id,
            credits_debited=credits,
            estimated_cost_minor=credits * llm_cost_minor,
            purpose=purpose,
            display_label=purpose.replace("_", " ").title(),
            source_type=source_object_type,
            source_id=source_object_id,
        )
        return
    _append_credit_ledger(
        session,
        company_id=company_id,
        subscription_id=subscription.id,
        credit_bucket="pooled",
        event_type=BillingCreditLedgerEventType.USAGE_DEBIT,
        delta=-credits,
        reason=f"AI usage: {purpose}",
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        actor_membership_id=actor_membership_id,
    )
    llm_cost_minor, _ = effective_cost_minor(
        session,
        category="llm",
        provider=get_settings().llm_provider or "llm",
    )
    record_usage(
        session,
        company_id=company_id,
        subscription_id=subscription.id,
        usage_type="ai_credit",
        feature_key="ai_generation",
        quantity=credits,
        unit="credit",
        actor_membership_id=actor_membership_id,
        matter_id=matter_id,
        credits_debited=credits,
        estimated_cost_minor=credits * llm_cost_minor,
        purpose=purpose,
        display_label=purpose.replace("_", " ").title(),
        source_type=source_object_type,
        source_id=source_object_id,
    )


def estimate_ai_credits_for_call(
    *,
    purpose: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    token_total = max(prompt_tokens + completion_tokens, 1)
    base = max(1, round(token_total / 4_000))
    if purpose in {"matter_file_qa", "hearing_pack", "draft_generation"}:
        return max(base, 2)
    if purpose.startswith("legal_update"):
        return 0
    return base


def assert_user_limit(session: Session, *, context: SessionContext, role: MembershipRole) -> None:
    subscription = _subscription_for_gate(session, context.company)
    if subscription is None:
        return
    entitlements = resolve_entitlements(session, subscription)
    internal, viewers = _membership_counts(session, context.company.id)
    if role == MembershipRole.VIEWER:
        limit = _coerce_int(entitlements.get("users_viewer_limit"))
        used = viewers
        action = "billing_limit.viewer_user_blocked"
    else:
        limit = _coerce_int(entitlements.get("users_internal_limit"))
        used = internal
        action = "billing_limit.internal_user_blocked"
    if limit is not None and used + 1 > limit:
        record_from_context(
            session,
            context,
            action=action,
            target_type="company",
            target_id=context.company.id,
            result=AuditResult.DENIED,
            metadata={"used": used, "limit": limit, "requested_role": role},
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Billing plan user limit reached.",
        )


def assert_matter_limit(session: Session, *, context: SessionContext) -> None:
    subscription = _subscription_for_gate(session, context.company)
    if subscription is None:
        return
    entitlements = resolve_entitlements(session, subscription)
    limit = _coerce_int(entitlements.get("matters_active_limit"))
    used = _active_matter_count(session, context.company.id)
    if limit is not None and used + 1 > limit:
        record_from_context(
            session,
            context,
            action="billing_limit.active_matter_blocked",
            target_type="company",
            target_id=context.company.id,
            result=AuditResult.DENIED,
            metadata={"used": used, "limit": limit},
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Billing plan active matter limit reached.",
        )


def assert_tracked_case_limit(session: Session, *, context: SessionContext) -> None:
    subscription = _subscription_for_gate(session, context.company)
    if subscription is None:
        return
    entitlements = resolve_entitlements(session, subscription)
    limit = _coerce_int(entitlements.get("tracked_cases_limit"))
    used = _tracked_case_count(session, context.company.id)
    if limit is not None and used + 1 > limit:
        record_from_context(
            session,
            context,
            action="billing_limit.tracked_case_blocked",
            target_type="tracked_case",
            result=AuditResult.DENIED,
            metadata={"used": used, "limit": limit},
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Billing plan tracked case limit reached.",
        )


def assert_manual_refresh_limit(
    session: Session,
    *,
    context: SessionContext,
    tracked_case_id: str | None = None,
) -> None:
    subscription = _subscription_for_gate(session, context.company)
    if subscription is None:
        return
    entitlements = resolve_entitlements(session, subscription)
    limit = _coerce_int(entitlements.get("manual_case_refreshes_daily"))
    used = _manual_refreshes_today(session, context.company.id)
    if limit is not None and used + 1 > limit:
        record_from_context(
            session,
            context,
            action="billing_limit.manual_refresh_blocked",
            target_type="tracked_case",
            target_id=tracked_case_id,
            result=AuditResult.DENIED,
            metadata={"used_today": used, "limit": limit},
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Daily manual case refresh limit reached.",
        )


def record_manual_refresh_usage(
    session: Session,
    *,
    context: SessionContext,
    tracked_case_id: str | None,
) -> None:
    subscription = _subscription_for_gate(session, context.company)
    if subscription is None:
        return
    case_refresh_cost_minor, _ = effective_cost_minor(
        session,
        category="case_refresh",
        provider="case_tracking",
    )
    record_usage(
        session,
        company_id=context.company.id,
        subscription_id=subscription.id,
        usage_type="case_refresh",
        feature_key="case_tracking_manual_refresh",
        quantity=1,
        unit="refresh",
        actor_membership_id=context.membership.id,
        tracked_case_id=tracked_case_id,
        estimated_cost_minor=case_refresh_cost_minor,
        display_label="Manual case refresh",
        source_type="tracked_case",
        source_id=tracked_case_id,
    )


def effective_storage_quota(session: Session, *, company: Company) -> int | None:
    subscription = _subscription_for_gate(session, company)
    if subscription is None:
        return None
    entitlements = resolve_entitlements(session, subscription)
    return _coerce_int(entitlements.get("storage_bytes_limit"))


def _breakdown_rows(rows: Iterable[tuple[Any, Any, Any, Any]]) -> list[BillingUsageBreakdownRow]:
    result = []
    for key, label, quantity, credits in rows:
        result.append(
            BillingUsageBreakdownRow(
                key=str(key or "unknown"),
                label=str(label or key or "Unknown"),
                quantity=int(quantity or 0),
                credits=int(credits or 0),
            )
        )
    return result


def usage_report(
    session: Session,
    *,
    context: SessionContext,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> BillingUsageReportResponse:
    subscription = ensure_grandfathered_subscription(session, context.company)
    entitlements = resolve_entitlements(session, subscription)
    if period_start is None or period_end is None:
        period_start = _to_aware(subscription.current_period_start) or _month_window()[0]
        period_end = _to_aware(subscription.current_period_end) or _month_window()[1]
    base_filters = [
        BillingUsageAttribution.company_id == context.company.id,
        BillingUsageAttribution.tenant_visible.is_(True),
        BillingUsageAttribution.created_at >= period_start,
        BillingUsageAttribution.created_at < period_end,
    ]
    by_feature = session.execute(
        select(
            BillingUsageAttribution.feature_key,
            BillingUsageAttribution.display_label,
            func.coalesce(func.sum(BillingUsageAttribution.provider_units), 0),
            func.coalesce(func.sum(BillingUsageAttribution.credits_debited), 0),
        )
        .where(*base_filters)
        .group_by(BillingUsageAttribution.feature_key, BillingUsageAttribution.display_label)
        .order_by(func.sum(BillingUsageAttribution.provider_units).desc())
    )
    by_user = session.execute(
        select(
            BillingUsageAttribution.actor_membership_id,
            CompanyMembership.user_id,
            func.coalesce(func.sum(BillingUsageAttribution.provider_units), 0),
            func.coalesce(func.sum(BillingUsageAttribution.credits_debited), 0),
        )
        .join(
            CompanyMembership,
            CompanyMembership.id == BillingUsageAttribution.actor_membership_id,
            isouter=True,
        )
        .where(*base_filters)
        .group_by(BillingUsageAttribution.actor_membership_id, CompanyMembership.user_id)
    )
    by_matter = session.execute(
        select(
            BillingUsageAttribution.matter_id,
            Matter.title,
            func.coalesce(func.sum(BillingUsageAttribution.provider_units), 0),
            func.coalesce(func.sum(BillingUsageAttribution.credits_debited), 0),
        )
        .join(Matter, Matter.id == BillingUsageAttribution.matter_id, isouter=True)
        .where(*base_filters)
        .group_by(BillingUsageAttribution.matter_id, Matter.title)
    )
    by_case = session.execute(
        select(
            BillingUsageAttribution.tracked_case_id,
            TrackedCase.case_title,
            func.coalesce(func.sum(BillingUsageAttribution.provider_units), 0),
            func.coalesce(func.sum(BillingUsageAttribution.credits_debited), 0),
        )
        .join(TrackedCase, TrackedCase.id == BillingUsageAttribution.tracked_case_id, isouter=True)
        .where(*base_filters)
        .group_by(BillingUsageAttribution.tracked_case_id, TrackedCase.case_title)
    )
    daily = session.execute(
        select(
            func.date(BillingUsageAttribution.created_at),
            func.date(BillingUsageAttribution.created_at),
            func.coalesce(func.sum(BillingUsageAttribution.provider_units), 0),
            func.coalesce(func.sum(BillingUsageAttribution.credits_debited), 0),
        )
        .where(*base_filters)
        .group_by(func.date(BillingUsageAttribution.created_at))
        .order_by(func.date(BillingUsageAttribution.created_at).asc())
    )
    return BillingUsageReportResponse(
        period_start=period_start,
        period_end=period_end,
        snapshot=_usage_snapshot(
            session,
            company=context.company,
            subscription=subscription,
            entitlements=entitlements,
        ),
        by_feature=_breakdown_rows(by_feature),
        by_user=_breakdown_rows(by_user),
        by_matter=_breakdown_rows(by_matter),
        by_tracked_case=_breakdown_rows(by_case),
        daily=_breakdown_rows(daily),
    )


def credit_ledger(session: Session, *, context: SessionContext) -> BillingCreditLedgerResponse:
    ensure_grandfathered_subscription(session, context.company)
    expire_due_ai_credits(session, company_id=context.company.id)
    rows = list(
        session.scalars(
            select(BillingCreditLedger)
            .where(BillingCreditLedger.company_id == context.company.id)
            .order_by(BillingCreditLedger.created_at.desc())
            .limit(500)
        )
    )
    return BillingCreditLedgerResponse(
        rows=[
            BillingCreditLedgerRecord(
                id=row.id,
                credit_bucket=row.credit_bucket,
                event_type=row.event_type,
                delta=row.delta,
                balance_after=row.balance_after,
                reason=row.reason,
                source_object_type=row.source_object_type,
                source_object_id=row.source_object_id,
                expires_at=row.expires_at,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


def list_invoices(session: Session, *, context: SessionContext) -> BillingInvoiceListResponse:
    invoices = list(
        session.scalars(
            select(BillingManualInvoice)
            .where(BillingManualInvoice.company_id == context.company.id)
            .order_by(BillingManualInvoice.issued_on.desc(), BillingManualInvoice.created_at.desc())
        )
    )
    return BillingInvoiceListResponse(
        invoices=[
            BillingInvoiceRecord(
                id=invoice.id,
                invoice_number=invoice.invoice_number,
                invoice_type="manual",
                amount_minor=invoice.amount_minor,
                tax_amount_minor=invoice.tax_amount_minor,
                total_amount_minor=invoice.amount_minor + invoice.tax_amount_minor,
                amount_received_minor=invoice.amount_received_minor,
                currency=invoice.currency,
                status=invoice.status,
                issued_on=invoice.issued_on,
                due_on=invoice.due_on,
                paid_on=invoice.paid_on,
            )
            for invoice in invoices
        ]
    )


def _csv_bytes(headers: list[str], rows: Iterable[Iterable[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([str(value) if value is not None else "" for value in row])
    return buffer.getvalue().encode("utf-8")


def credit_ledger_csv(session: Session, *, context: SessionContext) -> bytes:
    rows = credit_ledger(session, context=context).rows
    return _csv_bytes(
        [
            "created_at",
            "bucket",
            "event_type",
            "delta",
            "balance_after",
            "reason",
            "source_type",
            "source_id",
            "expires_at",
        ],
        (
            (
                row.created_at,
                row.credit_bucket,
                row.event_type,
                row.delta,
                row.balance_after,
                row.reason,
                row.source_object_type,
                row.source_object_id,
                row.expires_at,
            )
            for row in rows
        ),
    )


def payments_csv(session: Session, *, context: SessionContext) -> bytes:
    rows = list(
        session.scalars(
            select(BillingPaymentOrder)
            .where(BillingPaymentOrder.company_id == context.company.id)
            .order_by(BillingPaymentOrder.created_at.desc())
        )
    )
    return _csv_bytes(
        [
            "created_at",
            "merchant_reference",
            "status",
            "amount_minor",
            "tax_amount_minor",
            "amount_paid_minor",
            "currency",
            "paid_at",
        ],
        (
            (
                row.created_at,
                row.merchant_reference,
                row.status,
                row.amount_minor,
                row.tax_amount_minor,
                row.amount_paid_minor,
                row.currency,
                row.paid_at,
            )
            for row in rows
        ),
    )


def spend_csv(session: Session, *, context: SessionContext) -> bytes:
    report = usage_report(session, context=context)
    return _csv_bytes(
        ["key", "label", "quantity", "credits"],
        ((row.key, row.label, row.quantity, row.credits) for row in report.by_feature),
    )


def statement_csv(session: Session, *, context: SessionContext) -> bytes:
    current = current_billing_state(session, context)
    invoices = list_invoices(session, context=context).invoices
    ledger = credit_ledger(session, context=context).rows
    rows = [
        ("subscription", current["subscription"].plan_code if current["subscription"] else "", ""),
        ("status", current["subscription"].status if current["subscription"] else "", ""),
        ("ai_credit_balance", current["usage"].ai_credits_remaining, ""),
    ]
    rows.extend(
        ("invoice", invoice.invoice_number, invoice.total_amount_minor)
        for invoice in invoices
    )
    rows.extend(("credit", row.event_type, row.delta) for row in ledger[:50])
    return _csv_bytes(["kind", "reference", "amount_or_delta"], rows)


def _ascii_pdf_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _pdf_bytes(title: str, rows: Iterable[tuple[str, object]]) -> bytes:
    from fpdf import FPDF  # type: ignore[import-not-found]

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(0, 10, _ascii_pdf_text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(
        0,
        7,
        _ascii_pdf_text(f"CaseOps GSTIN: {get_settings().billing_company_gstin}"),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)
    for label, value in rows:
        pdf.set_font("Helvetica", style="B", size=10)
        pdf.cell(48, 7, _ascii_pdf_text(label), border=0)
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 7, _ascii_pdf_text(value), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _invoice_for_tenant(
    session: Session,
    *,
    context: SessionContext,
    invoice_id: str,
) -> BillingManualInvoice:
    invoice = session.scalar(
        select(BillingManualInvoice).where(
            BillingManualInvoice.id == invoice_id,
            BillingManualInvoice.company_id == context.company.id,
        )
    )
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    return invoice


def invoice_download_json(
    session: Session,
    *,
    context: SessionContext,
    invoice_id: str,
) -> bytes:
    invoice = _invoice_for_tenant(session, context=context, invoice_id=invoice_id)
    payload = {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "invoice_type": "manual",
        "seller": {
            "name": "CaseOps",
            "gstin": get_settings().billing_company_gstin,
        },
        "company": {
            "id": context.company.id,
            "name": context.company.name,
            "slug": context.company.slug,
        },
        "amount_minor": invoice.amount_minor,
        "tax_amount_minor": invoice.tax_amount_minor,
        "total_amount_minor": invoice.amount_minor + invoice.tax_amount_minor,
        "amount_received_minor": invoice.amount_received_minor,
        "tds_deducted_minor": invoice.tds_deducted_minor,
        "currency": invoice.currency,
        "status": invoice.status,
        "issued_on": invoice.issued_on.isoformat() if invoice.issued_on else None,
        "due_on": invoice.due_on.isoformat() if invoice.due_on else None,
        "paid_on": invoice.paid_on.isoformat() if invoice.paid_on else None,
        "payment_reference": invoice.payment_reference,
        "po_number": invoice.po_number,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def invoice_download_pdf(
    session: Session,
    *,
    context: SessionContext,
    invoice_id: str,
) -> bytes:
    invoice = _invoice_for_tenant(session, context=context, invoice_id=invoice_id)
    return _pdf_bytes(
        "CaseOps Billing Invoice",
        [
            ("Invoice", invoice.invoice_number),
            ("Customer", context.company.name),
            ("Issued", invoice.issued_on.isoformat() if invoice.issued_on else ""),
            ("Due", invoice.due_on.isoformat() if invoice.due_on else ""),
            ("Status", invoice.status),
            ("Amount minor", f"{invoice.amount_minor} {invoice.currency}"),
            ("GST/tax minor", f"{invoice.tax_amount_minor} {invoice.currency}"),
            (
                "Total minor",
                f"{invoice.amount_minor + invoice.tax_amount_minor} {invoice.currency}",
            ),
            ("Received minor", f"{invoice.amount_received_minor} {invoice.currency}"),
            ("TDS deducted minor", f"{invoice.tds_deducted_minor} {invoice.currency}"),
            ("PO number", invoice.po_number or ""),
            ("Payment reference", invoice.payment_reference or ""),
        ],
    )


def statement_pdf(session: Session, *, context: SessionContext) -> bytes:
    current = current_billing_state(session, context)
    invoices = list_invoices(session, context=context).invoices
    ledger = credit_ledger(session, context=context).rows[:20]
    rows: list[tuple[str, object]] = [
        ("Workspace", context.company.name),
        ("Subscription", current["subscription"].plan_name if current["subscription"] else ""),
        ("Status", current["subscription"].status if current["subscription"] else ""),
        ("AI credit balance", current["usage"].ai_credits_remaining),
        ("Invoices", len(invoices)),
    ]
    for invoice in invoices[:20]:
        rows.append(
            (
                f"Invoice {invoice.invoice_number}",
                f"{invoice.status} | total minor {invoice.total_amount_minor} {invoice.currency}",
            )
        )
    for row in ledger:
        rows.append(
            (
                "Credit ledger",
                f"{row.event_type} | delta {row.delta} | balance {row.balance_after}",
            )
        )
    return _pdf_bytes("CaseOps Billing Statement", rows)


def cancel_subscription(session: Session, *, context: SessionContext) -> BillingSubscriptionRecord:
    subscription = ensure_grandfathered_subscription(session, context.company)
    subscription.cancel_at_period_end = True
    subscription.cancelled_at = _now()
    record_from_context(
        session,
        context,
        action="billing.subscription.cancel_requested",
        target_type="billing_subscription",
        target_id=subscription.id,
    )
    session.commit()
    return _subscription_record(subscription)


def reactivate_subscription(
    session: Session,
    *,
    context: SessionContext,
) -> BillingSubscriptionRecord:
    subscription = ensure_grandfathered_subscription(session, context.company)
    subscription.cancel_at_period_end = False
    if subscription.status == BillingSubscriptionStatus.CANCELLED:
        subscription.status = BillingSubscriptionStatus.ACTIVE
    record_from_context(
        session,
        context,
        action="billing.subscription.reactivated",
        target_type="billing_subscription",
        target_id=subscription.id,
    )
    session.commit()
    return _subscription_record(subscription)


def create_demo_request(session: Session, payload: DemoRequest) -> DemoRequestResponse:
    row = BillingEnrollment(
        contact_name=payload.contact_name,
        contact_email=str(payload.contact_email).lower(),
        contact_mobile=payload.contact_mobile,
        company_name=payload.company_name,
        segment=payload.segment,
        selected_plan=payload.selected_plan,
        source=payload.source,
        notes=payload.notes,
        status="demo_requested",
        status_timestamps_json={"demo_requested_at": _now().isoformat()},
    )
    session.add(row)
    session.commit()
    return DemoRequestResponse(id=row.id, status=row.status)


def assert_trial_start_allowed(session: Session, payload: TrialStartRequest) -> None:
    email = str(payload.owner_email).strip().lower()
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    mobile = (payload.mobile or "").strip() or None
    gstin = (payload.gstin or "").strip().upper() or None
    filters = [func.lower(BillingEnrollment.contact_email) == email]
    if domain and domain not in FREE_TRIAL_DOMAIN_EXEMPTIONS:
        filters.append(func.lower(BillingEnrollment.contact_email).like(f"%@{domain}"))
    if mobile:
        filters.append(BillingEnrollment.contact_mobile == mobile)
    if gstin:
        filters.append(func.upper(BillingEnrollment.gstin) == gstin)
    existing = session.scalar(
        select(BillingEnrollment.id)
        .where(
            BillingEnrollment.status == "trial_started",
            or_(*filters),
        )
        .limit(1)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A trial already exists for this email domain, mobile, or GSTIN.",
        )


def start_trial_for_company(
    session: Session,
    *,
    company: Company,
    selected_plan: str | None = None,
    coupon_code: str | None = None,
) -> BillingSubscription:
    account = ensure_billing_account(session, company)
    trial_plan = _get_plan(session, "trial")
    now = _now()
    existing = _latest_subscription(session, company.id)
    if existing is not None:
        subscription = existing
    else:
        subscription = BillingSubscription(company_id=company.id)
        session.add(subscription)
    subscription.billing_account_id = account.id
    subscription.plan_version_id = trial_plan.id
    subscription.status = BillingSubscriptionStatus.TRIALING
    subscription.segment = trial_plan.segment
    subscription.billing_interval = "one_time"
    subscription.trial_start = now
    subscription.trial_end = now + timedelta(days=14)
    subscription.current_period_start = now
    subscription.current_period_end = subscription.trial_end
    subscription.source = "trial_signup"
    subscription.externally_billable = False
    subscription.metadata_json = {
        "selected_plan": selected_plan,
        "coupon_code": coupon_code,
    }
    session.flush()
    session.add(
        BillingSubscriptionItem(
            subscription_id=subscription.id,
            item_code=trial_plan.plan_code,
            item_type="base_plan",
            quantity=1,
            amount_minor=0,
            interval="one_time",
            status="active",
        )
    )
    grant_included_monthly_credits(
        session,
        subscription=subscription,
        entitlements=_plan_entitlements(trial_plan),
    )
    return subscription


def handle_billing_provider_event(
    session: Session,
    *,
    payload: dict[str, object],
    raw_body: bytes,
    signature: str | None,
    webhook_id: str | None,
    webhook_timestamp: datetime | None,
) -> tuple[bool, str | None, bool]:
    result = PineLabsGatewayClient().parse_webhook_payload(payload)
    event_id = _extract_provider_event_id(payload)
    existing = None
    if webhook_id:
        existing = session.scalar(
            select(BillingProviderEvent).where(
                BillingProviderEvent.provider == "pine_labs_plural",
                BillingProviderEvent.webhook_id == webhook_id,
            )
        )
    if existing is None and event_id:
        existing = session.scalar(
            select(BillingProviderEvent).where(
                BillingProviderEvent.provider == "pine_labs_plural",
                BillingProviderEvent.provider_event_id == event_id,
            )
        )
    if existing is not None:
        existing.last_seen_at = _now()
        existing.retry_count += 1
        session.commit()
        return True, result.provider_order_id, True
    event = BillingProviderEvent(
        provider="pine_labs_plural",
        provider_event_id=event_id,
        webhook_id=webhook_id,
        webhook_timestamp=webhook_timestamp,
        signature_digest=_webhook_signature_digest(signature),
        event_type=str(payload.get("event_type") or payload.get("type") or "payment_status"),
        provider_order_id=result.provider_order_id,
        provider_payment_id=result.provider_reference,
        provider_subscription_id=_extract_first(payload, "subscription_id", "mandate_id"),
        resource_id=result.provider_order_id,
        payload_json=redact_provider_payload(payload),
        processing_status="received",
    )
    session.add(event)
    order = _load_billing_order(session, provider_order_id=result.provider_order_id)
    if order is None:
        event.processing_status = "ignored"
        session.commit()
        return False, result.provider_order_id, False
    previous_status = order.status
    apply_billing_payment_result(session, order=order, result=result, event_source="webhook")
    if (
        previous_status == BillingPaymentOrderStatus.PAID
        and result.status not in {"paid", "refunded"}
    ):
        event.processing_status = "ignored_out_of_order"
    else:
        event.processing_status = "processed"
    session.commit()
    return True, result.provider_order_id, False


def _load_billing_order(
    session: Session,
    *,
    provider_order_id: str | None,
) -> BillingPaymentOrder | None:
    if not provider_order_id:
        return None
    return session.scalar(
        select(BillingPaymentOrder)
        .options(selectinload(BillingPaymentOrder.checkout_session))
        .where(
            or_(
                BillingPaymentOrder.provider_order_id == provider_order_id,
                BillingPaymentOrder.provider_payment_id == provider_order_id,
                BillingPaymentOrder.merchant_reference == provider_order_id,
            )
        )
    )


def _extract_provider_event_id(payload: dict[str, object]) -> str | None:
    return _extract_first(payload, "event_id", "webhook_event_id", "id", "notification_id")


def _webhook_signature_digest(signature: str | None) -> str | None:
    if not signature:
        return None
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _extract_first(payload: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_first(data, *keys)
    return None


def platform_overview(session: Session) -> PlatformOverviewResponse:
    active_subscriptions = int(
        session.scalar(
            select(func.count(BillingSubscription.id)).where(
                BillingSubscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES)
            )
        )
        or 0
    )
    trial_count = int(
        session.scalar(
            select(func.count(BillingSubscription.id)).where(
                BillingSubscription.status == BillingSubscriptionStatus.TRIALING
            )
        )
        or 0
    )
    failed_payments = int(
        session.scalar(
            select(func.count(BillingPaymentOrder.id)).where(
                BillingPaymentOrder.status == BillingPaymentOrderStatus.FAILED
            )
        )
        or 0
    )
    monthly_rows = list(
        session.execute(
            select(BillingPlanPrice.interval, func.sum(BillingPlanPrice.amount_minor))
            .join(BillingPlanVersion, BillingPlanVersion.id == BillingPlanPrice.plan_version_id)
            .join(
                BillingSubscription,
                BillingSubscription.plan_version_id == BillingPlanVersion.id,
            )
            .where(BillingSubscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES))
            .group_by(BillingPlanPrice.interval)
        )
    )
    mrr = 0
    for interval, amount in monthly_rows:
        value = int(amount or 0)
        if interval == "month":
            mrr += value
        elif interval == "year":
            mrr += round(value / 12)
    profit_rows = list(session.scalars(select(BillingProfitRollup)))
    recognized = sum(row.recognized_revenue_minor for row in profit_rows)
    gross_revenue = sum(row.gross_revenue_minor for row in profit_rows)
    costs = sum(row.total_variable_cost_minor for row in profit_rows)
    gross_profit = sum(row.gross_profit_minor for row in profit_rows)
    margin = round(gross_profit * 10_000 / recognized) if recognized else None
    alerts = [
        {
            "company_id": row.company_id,
            "gross_margin_bps": row.gross_margin_bps,
            "gross_profit_minor": row.gross_profit_minor,
        }
        for row in profit_rows
        if row.gross_profit_minor < 0
        or (row.gross_margin_bps is not None and row.gross_margin_bps < 4000)
    ]
    alerts.extend(case_refresh_guardrail_warnings(session))
    return PlatformOverviewResponse(
        mrr_minor=mrr,
        arr_minor=mrr * 12,
        active_subscriptions=active_subscriptions,
        trial_count=trial_count,
        failed_payments=failed_payments,
        gross_revenue_minor=gross_revenue,
        recognized_revenue_minor=recognized,
        total_variable_cost_minor=costs,
        gross_profit_minor=gross_profit,
        gross_margin_bps=margin,
        margin_alerts=alerts,
    )


def platform_company_billing_detail(session: Session, company_id: str) -> dict[str, Any]:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found.")
    subscription = ensure_grandfathered_subscription(session, company)
    entitlements = resolve_entitlements(session, subscription)
    account = ensure_billing_account(session, company)
    return {
        "company": {"id": company.id, "name": company.name, "slug": company.slug},
        "billing_account": _account_record(account),
        "subscription": _subscription_record(subscription),
        "entitlements": entitlements,
        "usage": _usage_snapshot(
            session,
            company=company,
            subscription=subscription,
            entitlements=entitlements,
        ),
        "invoices": list_invoices_for_company(session, company_id=company_id),
    }


def list_invoices_for_company(session: Session, *, company_id: str) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(BillingManualInvoice)
            .where(BillingManualInvoice.company_id == company_id)
            .order_by(BillingManualInvoice.issued_on.desc())
        )
    )
    return [
        {
            "id": row.id,
            "invoice_number": row.invoice_number,
            "status": row.status,
            "amount_minor": row.amount_minor,
            "tax_amount_minor": row.tax_amount_minor,
            "amount_received_minor": row.amount_received_minor,
            "issued_on": row.issued_on.isoformat(),
            "due_on": row.due_on.isoformat() if row.due_on else None,
        }
        for row in rows
    ]


def platform_mutate_subscription(
    session: Session,
    *,
    company_id: str,
    payload: PlatformSubscriptionMutation,
    platform_admin: PlatformAdminMembership,
    context: SessionContext,
) -> dict[str, Any]:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found.")
    subscription = ensure_grandfathered_subscription(session, company)
    if payload.plan_code:
        plan = _get_plan(session, payload.plan_code)
        subscription.plan_version_id = plan.id
        subscription.segment = plan.segment
    subscription.billing_interval = payload.billing_interval
    subscription.status = payload.status
    subscription.source = "platform_admin"
    subscription.externally_billable = False if payload.status == "manual_active" else True
    subscription.current_period_start = subscription.current_period_start or _now()
    subscription.current_period_end = (
        None
        if subscription.billing_interval == "custom"
        else _period_end(subscription.current_period_start, subscription.billing_interval)
    )
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.subscription.updated",
        target_type="billing_subscription",
        target_id=subscription.id,
        company_id=company_id,
        metadata={"reason": payload.reason, "status": payload.status},
    )
    session.commit()
    return platform_company_billing_detail(session, company_id)


def platform_grant_credits(
    session: Session,
    *,
    company_id: str,
    payload: PlatformGrantCreditsRequest,
    platform_admin: PlatformAdminMembership,
    context: SessionContext,
) -> dict[str, Any]:
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found.")
    subscription = ensure_grandfathered_subscription(session, company)
    ledger = _append_credit_ledger(
        session,
        company_id=company_id,
        subscription_id=subscription.id,
        credit_bucket="manual",
        event_type=BillingCreditLedgerEventType.MANUAL_ADMIN_GRANT,
        delta=payload.credits,
        reason=payload.reason,
        platform_admin_id=platform_admin.id,
        expires_at=_now() + timedelta(days=365),
    )
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.credits.granted",
        target_type="billing_credit_ledger",
        target_id=ledger.id,
        company_id=company_id,
        metadata={"credits": payload.credits, "reason": payload.reason},
    )
    session.commit()
    return {"ledger_id": ledger.id, "balance_after": ledger.balance_after}


def platform_create_manual_invoice(
    session: Session,
    *,
    payload: PlatformManualInvoiceCreateRequest,
    platform_admin: PlatformAdminMembership,
    context: SessionContext,
) -> dict[str, Any]:
    row = BillingManualInvoice(
        company_id=payload.company_id,
        subscription_id=payload.subscription_id,
        invoice_number=payload.invoice_number,
        po_number=payload.po_number,
        amount_minor=payload.amount_minor,
        tax_amount_minor=payload.tax_amount_minor,
        issued_on=date.today(),
        due_on=payload.due_on,
        created_by_platform_admin_id=platform_admin.id,
        metadata_json={"reason": payload.reason},
    )
    session.add(row)
    session.flush()
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.manual_invoice.created",
        target_type="billing_manual_invoice",
        target_id=row.id,
        company_id=payload.company_id,
        metadata={"reason": payload.reason},
    )
    session.commit()
    return {"id": row.id, "invoice_number": row.invoice_number, "status": row.status}


def platform_mark_manual_invoice_paid(
    session: Session,
    *,
    invoice_id: str,
    payload: PlatformManualInvoicePaidRequest,
    platform_admin: PlatformAdminMembership,
    context: SessionContext,
) -> dict[str, Any]:
    row = session.get(BillingManualInvoice, invoice_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    row.amount_received_minor = payload.amount_received_minor
    row.tds_deducted_minor = payload.tds_deducted_minor
    row.payment_reference = payload.payment_reference
    row.paid_on = payload.paid_on or date.today()
    row.status = "paid" if row.amount_received_minor >= row.amount_minor else "partially_paid"
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.manual_invoice.marked_paid",
        target_type="billing_manual_invoice",
        target_id=row.id,
        company_id=row.company_id,
        metadata={"reason": payload.reason, "payment_reference": payload.payment_reference},
    )
    session.commit()
    return {"id": row.id, "status": row.status, "amount_received_minor": row.amount_received_minor}


def platform_provider_events(
    session: Session,
    *,
    q: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    filters = []
    if q:
        needle = f"%{q}%"
        filters.append(
            or_(
                BillingProviderEvent.provider_event_id.ilike(needle),
                BillingProviderEvent.provider_order_id.ilike(needle),
                BillingProviderEvent.webhook_id.ilike(needle),
            )
        )
    rows = list(
        session.scalars(
            select(BillingProviderEvent)
            .where(*filters)
            .order_by(BillingProviderEvent.first_seen_at.desc())
            .limit(limit)
        )
    )
    return [
        {
            "id": row.id,
            "provider": row.provider,
            "provider_event_id": row.provider_event_id,
            "webhook_id": row.webhook_id,
            "event_type": row.event_type,
            "provider_order_id": row.provider_order_id,
            "processing_status": row.processing_status,
            "first_seen_at": row.first_seen_at,
            "received_at": row.first_seen_at,
            "processed_at": row.last_seen_at,
            "error_message": row.error,
            "retry_count": row.retry_count,
        }
        for row in rows
    ]


def platform_usage_report(session: Session) -> list[dict[str, Any]]:
    rows = list(
        session.execute(
            select(
                BillingUsageAttribution.company_id,
                BillingUsageAttribution.feature_key,
                func.coalesce(func.sum(BillingUsageAttribution.provider_units), 0),
                func.coalesce(func.sum(BillingUsageAttribution.credits_debited), 0),
                func.coalesce(func.sum(BillingUsageAttribution.estimated_internal_cost_minor), 0),
            )
            .group_by(BillingUsageAttribution.company_id, BillingUsageAttribution.feature_key)
            .order_by(BillingUsageAttribution.company_id.asc())
        )
    )
    return [
        {
            "company_id": company_id,
            "feature_key": feature_key,
            "quantity": int(quantity or 0),
            "credits": int(credits or 0),
            "estimated_internal_cost_minor": int(cost or 0),
        }
        for company_id, feature_key, quantity, credits, cost in rows
    ]


def platform_profit_report(session: Session) -> list[dict[str, Any]]:
    rows = list(
        session.execute(
            select(BillingProfitRollup, Company.name)
            .join(Company, BillingProfitRollup.company_id == Company.id, isouter=True)
            .order_by(
                BillingProfitRollup.period_start.desc(), BillingProfitRollup.company_id.asc()
            )
        )
    )
    return [
        _profit_rollup_record(row, company_name=company_name)
        for row, company_name in rows
    ]


def platform_company_profitability(session: Session) -> list[dict[str, Any]]:
    rows = list(
        session.execute(
            select(
                Company.id,
                Company.name,
                func.coalesce(func.sum(BillingProfitRollup.gross_revenue_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.recognized_revenue_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.tax_collected_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.discount_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.payment_gateway_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.llm_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.embedding_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.case_refresh_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.document_processing_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.storage_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.manual_support_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.manual_research_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.total_variable_cost_minor), 0),
                func.coalesce(func.sum(BillingProfitRollup.gross_profit_minor), 0),
            )
            .join(BillingProfitRollup, BillingProfitRollup.company_id == Company.id, isouter=True)
            .group_by(Company.id, Company.name)
            .order_by(func.sum(BillingProfitRollup.gross_profit_minor).desc())
        )
    )
    result = []
    for (
        company_id,
        name,
        gross_revenue,
        revenue,
        tax,
        discount,
        gateway_cost,
        llm_cost,
        embedding_cost,
        case_refresh_cost,
        document_cost,
        storage_cost,
        support_cost,
        research_cost,
        cost,
        profit,
    ) in rows:
        margin = round(int(profit or 0) * 10_000 / int(revenue or 1)) if revenue else None
        result.append(
            {
                "company_id": company_id,
                "company_name": name,
                "gross_revenue_minor": int(gross_revenue or 0),
                "recognized_revenue_minor": int(revenue or 0),
                "tax_minor": int(tax or 0),
                "discounts_minor": int(discount or 0),
                "payment_provider_cost_minor": int(gateway_cost or 0),
                "payment_gateway_cost_minor": int(gateway_cost or 0),
                "llm_cost_minor": int(llm_cost or 0),
                "embedding_cost_minor": int(embedding_cost or 0),
                "case_refresh_cost_minor": int(case_refresh_cost or 0),
                "document_processing_cost_minor": int(document_cost or 0),
                "storage_cost_minor": int(storage_cost or 0),
                "manual_support_cost_minor": int(support_cost or 0),
                "manual_research_cost_minor": int(research_cost or 0),
                "total_variable_cost_minor": int(cost or 0),
                "gross_profit_minor": int(profit or 0),
                "gross_margin_bps": margin,
                "loss_risk": int(profit or 0) < 0 or (margin is not None and margin < 4000),
            }
        )
    return result


def _profit_rollup_record(
    row: BillingProfitRollup,
    *,
    company_name: str | None = None,
) -> dict[str, Any]:
    return {
        "company_id": row.company_id,
        "company_name": company_name,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "gross_revenue_minor": row.gross_revenue_minor,
        "recognized_revenue_minor": row.recognized_revenue_minor,
        "tax_minor": row.tax_collected_minor,
        "tax_collected_minor": row.tax_collected_minor,
        "discounts_minor": row.discount_minor,
        "discount_minor": row.discount_minor,
        "payment_provider_cost_minor": row.payment_gateway_cost_minor,
        "payment_gateway_cost_minor": row.payment_gateway_cost_minor,
        "llm_cost_minor": row.llm_cost_minor,
        "embedding_cost_minor": row.embedding_cost_minor,
        "case_refresh_cost_minor": row.case_refresh_cost_minor,
        "document_processing_cost_minor": row.document_processing_cost_minor,
        "storage_cost_minor": row.storage_cost_minor,
        "manual_support_cost_minor": row.manual_support_cost_minor,
        "manual_research_cost_minor": row.manual_research_cost_minor,
        "total_variable_cost_minor": row.total_variable_cost_minor,
        "gross_profit_minor": row.gross_profit_minor,
        "gross_margin_bps": row.gross_margin_bps,
        "status": row.status,
    }


def platform_profit_csv(session: Session) -> bytes:
    return _csv_bytes(
        [
            "company_id",
            "company_name",
            "period_start",
            "period_end",
            "gross_revenue_minor",
            "recognized_revenue_minor",
            "tax_minor",
            "discounts_minor",
            "payment_provider_cost_minor",
            "llm_cost_minor",
            "embedding_cost_minor",
            "case_refresh_cost_minor",
            "document_processing_cost_minor",
            "storage_cost_minor",
            "manual_support_cost_minor",
            "manual_research_cost_minor",
            "total_variable_cost_minor",
            "gross_profit_minor",
            "gross_margin_bps",
        ],
        (
            (
                row["company_id"],
                row.get("company_name"),
                row["period_start"],
                row["period_end"],
                row["gross_revenue_minor"],
                row["recognized_revenue_minor"],
                row["tax_minor"],
                row["discounts_minor"],
                row["payment_provider_cost_minor"],
                row["llm_cost_minor"],
                row["embedding_cost_minor"],
                row["case_refresh_cost_minor"],
                row["document_processing_cost_minor"],
                row["storage_cost_minor"],
                row["manual_support_cost_minor"],
                row["manual_research_cost_minor"],
                row["total_variable_cost_minor"],
                row["gross_profit_minor"],
                row["gross_margin_bps"],
            )
            for row in platform_profit_report(session)
        ),
    )


def platform_revenue_csv(session: Session) -> bytes:
    rows = list(
        session.scalars(
            select(BillingPaymentOrder)
            .where(BillingPaymentOrder.status == BillingPaymentOrderStatus.PAID)
            .order_by(BillingPaymentOrder.paid_at.desc())
        )
    )
    return _csv_bytes(
        ["paid_at", "company_id", "merchant_reference", "amount_paid_minor", "tax_amount_minor"],
        (
            (
                row.paid_at,
                row.company_id,
                row.merchant_reference,
                row.amount_paid_minor,
                row.tax_amount_minor,
            )
            for row in rows
        ),
    )


def platform_create_coupon(
    session: Session,
    *,
    payload: PlatformCouponCreateRequest,
    platform_admin: PlatformAdminMembership,
    context: SessionContext,
) -> dict[str, Any]:
    row = BillingCoupon(
        code=payload.code.strip().upper(),
        description=payload.description,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        currency=payload.currency,
        duration=payload.duration,
        duration_periods=payload.duration_periods,
        max_redemptions=payload.max_redemptions,
        valid_until=payload.valid_until,
        created_by_platform_admin_id=platform_admin.id,
    )
    session.add(row)
    session.flush()
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.coupon.created",
        target_type="billing_coupon",
        target_id=row.id,
        metadata={"code": row.code, "reason": payload.reason},
    )
    session.commit()
    return {"id": row.id, "code": row.code, "status": row.status}


def platform_list_coupons(session: Session) -> list[dict[str, Any]]:
    rows = list(session.scalars(select(BillingCoupon).order_by(BillingCoupon.created_at.desc())))
    return [
        {
            "id": row.id,
            "code": row.code,
            "discount_type": row.discount_type,
            "discount_value": row.discount_value,
            "status": row.status,
            "redeemed_count": row.redeemed_count,
        }
        for row in rows
    ]


def platform_set_overage_policy(
    session: Session,
    *,
    company_id: str,
    payload: PlatformOveragePolicyRequest,
    platform_admin: PlatformAdminMembership,
    context: SessionContext,
) -> dict[str, Any]:
    row = session.scalar(
        select(BillingOveragePolicy).where(BillingOveragePolicy.company_id == company_id)
    )
    if row is None:
        row = BillingOveragePolicy(company_id=company_id)
        session.add(row)
    session.flush()
    row.overage_allowed = payload.overage_allowed
    row.unit_prices_json = payload.unit_prices
    row.cap_amount_minor = payload.cap_amount_minor
    row.ends_at = payload.ends_at
    row.approved_by_platform_admin_id = platform_admin.id
    row.reason = payload.reason
    record_platform_audit(
        session,
        context=context,
        platform_admin=platform_admin,
        action="platform.overage_policy.updated",
        target_type="billing_overage_policy",
        target_id=row.id,
        company_id=company_id,
        metadata={"reason": payload.reason},
    )
    session.commit()
    return {
        "id": row.id,
        "company_id": row.company_id,
        "overage_allowed": row.overage_allowed,
        "cap_amount_minor": row.cap_amount_minor,
    }
