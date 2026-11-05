"""Read-only billing entitlement resolution.

Side-effect free helpers shared by ``saas_billing`` and ``provider_spend``.
They live here so neither service imports the other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    BillingPlanVersion,
    BillingSubscription,
    BillingSubscriptionStatus,
)

ACTIVE_SUBSCRIPTION_STATUSES = {
    BillingSubscriptionStatus.ACTIVE,
    BillingSubscriptionStatus.TRIALING,
    BillingSubscriptionStatus.GRACE,
    BillingSubscriptionStatus.MANUAL_ACTIVE,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _to_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


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
                    BillingPlanVersion.version == subscription.plan_version.version,
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


def current_entitlements_for_company(session: Session, company_id: str) -> dict[str, Any]:
    """Resolve existing effective entitlements without creating billing state.

    Authorization/readiness checks must be side-effect free. A company without
    an existing subscription therefore has no entitlements and fails closed;
    the explicit billing bootstrap/current-state workflow remains the owner of
    grandfathered subscription creation.
    """

    subscription = _latest_subscription(session, company_id)
    if subscription is None or subscription.status not in ACTIVE_SUBSCRIPTION_STATUSES:
        return {}
    return resolve_entitlements(session, subscription)


def trial_has_ended(subscription: BillingSubscription, *, now: datetime | None = None) -> bool:
    """A trial ends at ``trial_end``; afterwards the workspace is read-only."""

    if subscription.status != BillingSubscriptionStatus.TRIALING:
        return False
    trial_end = _to_aware(subscription.trial_end)
    return trial_end is not None and trial_end <= (now or _now())
