"""Tenant provider-spend policy, atomic reservations, and report projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    BillingUsageEvent,
    Company,
    CompanyProviderSpendPolicy,
    ProviderSpendReservation,
)
from caseops_api.db.session import get_session_factory, serialize_sqlite_writer
from caseops_api.schemas.saas_billing import BillingProviderSpendRow

DEFAULT_MONTHLY_LIMIT_MINOR = 100_000
PROVIDER_KEYS = ("indian-kanoon", "ecourtsindia")
PROVIDER_LABELS = {
    "indian-kanoon": "Indian Kanoon",
    "ecourtsindia": "eCourtsIndia",
}
RESERVATION_TTL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class ResolvedProviderSpendPolicy:
    monthly_limit_minor: int | None
    currency: str
    source: str

    @property
    def unlimited(self) -> bool:
        return self.monthly_limit_minor is None


def _now() -> datetime:
    return datetime.now(UTC)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def resolve_provider_spend_policy(
    session: Session,
    *,
    company: Company,
    provider_key: str,
) -> ResolvedProviderSpendPolicy:
    row = session.scalar(
        select(CompanyProviderSpendPolicy).where(
            CompanyProviderSpendPolicy.company_id == company.id,
            CompanyProviderSpendPolicy.provider_key == provider_key,
            CompanyProviderSpendPolicy.is_active.is_(True),
        )
    )
    if row is not None:
        return ResolvedProviderSpendPolicy(
            monthly_limit_minor=row.monthly_limit_minor,
            currency=row.currency,
            source=row.policy_source,
        )
    return ResolvedProviderSpendPolicy(
        monthly_limit_minor=DEFAULT_MONTHLY_LIMIT_MINOR,
        currency="INR",
        source="caseops_default_provider_budget_2026_09_04",
    )


def provider_spend_minor(
    session: Session,
    *,
    company_id: str,
    provider_key: str,
    period_start: datetime,
) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(BillingUsageEvent.estimated_cost_minor), 0)).where(
                BillingUsageEvent.company_id == company_id,
                BillingUsageEvent.provider_key == provider_key,
                BillingUsageEvent.created_at >= period_start,
            )
        )
        or 0
    )


def provider_spend_rows(
    session: Session,
    *,
    company: Company,
    period_start: datetime | None = None,
) -> list[BillingProviderSpendRow]:
    period_start = period_start or _month_start(_now())
    rows: list[BillingProviderSpendRow] = []
    for provider_key in PROVIDER_KEYS:
        policy = resolve_provider_spend_policy(
            session,
            company=company,
            provider_key=provider_key,
        )
        spent = provider_spend_minor(
            session,
            company_id=company.id,
            provider_key=provider_key,
            period_start=period_start,
        )
        remaining = (
            None if policy.unlimited else max(int(policy.monthly_limit_minor or 0) - spent, 0)
        )
        rows.append(
            BillingProviderSpendRow(
                provider_key=provider_key,
                label=PROVIDER_LABELS[provider_key],
                spent_minor=spent,
                monthly_limit_minor=policy.monthly_limit_minor,
                remaining_minor=remaining,
                unlimited=policy.unlimited,
                currency=policy.currency,
                policy_source=policy.source,
            )
        )
    return rows


def _reserve_provider_spend(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str | None,
    provider_key: str,
    operation_key: str,
    amount_minor: int,
) -> str | None:
    if amount_minor <= 0:
        return None
    if provider_key not in PROVIDER_KEYS:
        raise ValueError(f"Unsupported paid provider: {provider_key}")
    now = _now()
    company = session.scalar(select(Company).where(Company.id == company_id).with_for_update())
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found.")
    policy = resolve_provider_spend_policy(
        session,
        company=company,
        provider_key=provider_key,
    )
    spent = provider_spend_minor(
        session,
        company_id=company.id,
        provider_key=provider_key,
        period_start=_month_start(now),
    )
    reserved = int(
        session.scalar(
            select(func.coalesce(func.sum(ProviderSpendReservation.amount_minor), 0)).where(
                ProviderSpendReservation.company_id == company.id,
                ProviderSpendReservation.provider_key == provider_key,
                ProviderSpendReservation.status == "reserved",
                ProviderSpendReservation.expires_at > now,
            )
        )
        or 0
    )
    if (
        policy.monthly_limit_minor is not None
        and spent + reserved + amount_minor > policy.monthly_limit_minor
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "provider_budget_exhausted",
                "message": (
                    f"The workspace {PROVIDER_LABELS[provider_key]} monthly budget "
                    "is exhausted; no external request was made."
                ),
                "provider": provider_key,
                "spent_minor": spent,
                "reserved_minor": reserved,
                "monthly_limit_minor": policy.monthly_limit_minor,
                "currency": policy.currency,
            },
        )
    reservation = ProviderSpendReservation(
        company_id=company.id,
        provider_key=provider_key,
        actor_membership_id=actor_membership_id,
        operation_key=operation_key[:120],
        amount_minor=amount_minor,
        currency=policy.currency,
        status="reserved",
        expires_at=now + RESERVATION_TTL,
    )
    session.add(reservation)
    session.flush()
    return reservation.id


def reserve_provider_spend_in_session(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str | None,
    provider_key: str,
    operation_key: str,
    amount_minor: int,
) -> str | None:
    """Reserve within an existing writer transaction; the caller owns commit."""

    return _reserve_provider_spend(
        session,
        company_id=company_id,
        actor_membership_id=actor_membership_id,
        provider_key=provider_key,
        operation_key=operation_key,
        amount_minor=amount_minor,
    )


def reserve_provider_spend(
    *,
    company_id: str,
    actor_membership_id: str | None,
    provider_key: str,
    operation_key: str,
    amount_minor: int,
) -> str | None:
    """Atomically reserve budget without holding a lock across the provider call."""

    with get_session_factory()() as budget_session:
        serialize_sqlite_writer(budget_session)
        reservation_id = _reserve_provider_spend(
            budget_session,
            company_id=company_id,
            actor_membership_id=actor_membership_id,
            provider_key=provider_key,
            operation_key=operation_key,
            amount_minor=amount_minor,
        )
        budget_session.commit()
        return reservation_id


def settle_provider_spend(
    session: Session,
    *,
    reservation_id: str | None,
    amount_minor: int | None = None,
) -> None:
    if reservation_id is None:
        return
    row = session.scalar(
        select(ProviderSpendReservation)
        .where(ProviderSpendReservation.id == reservation_id)
        .with_for_update()
    )
    if row is None or row.status != "reserved":
        return
    if amount_minor is not None:
        if amount_minor < 0 or amount_minor > row.amount_minor:
            raise ValueError("Settled provider spend must fit inside the reservation.")
        row.amount_minor = amount_minor
    row.status = "settled"
    row.settled_at = _now()
    session.add(row)


def release_provider_spend_in_session(
    session: Session,
    *,
    reservation_id: str | None,
) -> None:
    if reservation_id is None:
        return
    row = session.scalar(
        select(ProviderSpendReservation)
        .where(ProviderSpendReservation.id == reservation_id)
        .with_for_update()
    )
    if row is None or row.status != "reserved":
        return
    row.status = "released"
    row.released_at = _now()
    session.add(row)


def release_provider_spend(*, reservation_id: str | None) -> None:
    if reservation_id is None:
        return
    with get_session_factory()() as budget_session:
        serialize_sqlite_writer(budget_session)
        row = budget_session.scalar(
            select(ProviderSpendReservation)
            .where(ProviderSpendReservation.id == reservation_id)
            .with_for_update()
        )
        if row is None or row.status != "reserved":
            return
        row.status = "released"
        row.released_at = _now()
        budget_session.add(row)
        budget_session.commit()


__all__ = [
    "DEFAULT_MONTHLY_LIMIT_MINOR",
    "PROVIDER_KEYS",
    "provider_spend_minor",
    "provider_spend_rows",
    "release_provider_spend",
    "release_provider_spend_in_session",
    "reserve_provider_spend",
    "reserve_provider_spend_in_session",
    "resolve_provider_spend_policy",
    "settle_provider_spend",
]
