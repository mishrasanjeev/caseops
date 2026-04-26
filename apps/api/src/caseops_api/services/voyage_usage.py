"""Voyage spend ledger + daily cap.

Mirror of the Anthropic ``ModelRun`` audit, applied to Voyage embed
calls. Both helpers fail SOFT on DB issues so an audit-side outage
never breaks an ingest, but the cap check still raises so a
configuration mistake cannot bleed past the daily ceiling.

Per the Apr 18-26 incident: $343 of Voyage spend on a 26K-doc SC
ingest with zero on-DB visibility — by the time the operator checked
the Voyage console, the bill was already booked.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import VoyageUsage
from caseops_api.db.session import get_session_factory

logger = logging.getLogger(__name__)


class VoyageDailyCapExceeded(RuntimeError):
    """Raised before a new embed call when today's cumulative Voyage
    spend exceeds ``voyage_daily_cap_usd``. The caller should treat
    this as a stop-the-line signal — the cap is intentionally low so
    a runaway sweep cannot bleed for hours unnoticed."""


def _start_of_today_utc() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def estimate_cost_usd(*, tokens: int, price_per_million_usd: float | None = None) -> float:
    if price_per_million_usd is None:
        price_per_million_usd = float(get_settings().voyage_price_per_million_tokens_usd)
    return (max(int(tokens), 0) / 1_000_000.0) * float(price_per_million_usd)


def assert_under_daily_cap() -> None:
    """Raise ``VoyageDailyCapExceeded`` if today's spend already
    exceeds the configured daily cap. Cap=0 disables the check."""
    settings = get_settings()
    cap = float(settings.voyage_daily_cap_usd)
    if cap <= 0:
        return
    cutoff = _start_of_today_utc()
    try:
        with get_session_factory()() as session:
            spent = session.scalar(
                select(func.coalesce(func.sum(VoyageUsage.cost_usd), 0))
                .where(VoyageUsage.created_at >= cutoff)
                .where(VoyageUsage.status == "ok")
            )
    except Exception as exc:  # DB unreachable — fail SOFT, log loudly.
        logger.warning(
            "voyage_usage.assert_under_daily_cap: DB read failed (%s); "
            "skipping cap check this call.", exc,
        )
        return
    spent_f = float(spent or 0)
    if spent_f >= cap:
        raise VoyageDailyCapExceeded(
            f"Voyage daily-cap exceeded: spent=${spent_f:.4f} >= "
            f"cap=${cap:.4f} (UTC day starting {cutoff.isoformat()}). "
            "Raise CASEOPS_VOYAGE_DAILY_CAP_USD or wait until tomorrow."
        )


def record_call(
    *,
    purpose: str,
    model: str,
    input_type: str,
    texts_count: int,
    tokens: int,
    dimensions: int,
    latency_ms: int,
    status: str = "ok",
    error: str | None = None,
    company_id: str | None = None,
) -> None:
    """Persist one Voyage embed call as a ``VoyageUsage`` row.

    Fail-soft: a DB write failure logs and returns instead of raising,
    so audit problems never break ingest. The cap check is the gate
    that protects spend; this row is the receipt."""
    settings = get_settings()
    if not settings.voyage_usage_audit_enabled:
        return
    cost = estimate_cost_usd(
        tokens=tokens,
        price_per_million_usd=float(settings.voyage_price_per_million_tokens_usd),
    )
    try:
        with get_session_factory()() as session:
            row = VoyageUsage(
                company_id=company_id,
                purpose=purpose or "unspecified",
                model=model,
                input_type=input_type,
                texts_count=int(texts_count),
                tokens=int(tokens),
                dimensions=int(dimensions),
                cost_usd=cost,
                latency_ms=int(latency_ms),
                status=status,
                error=error,
            )
            session.add(row)
            session.commit()
    except Exception as exc:
        logger.warning(
            "voyage_usage.record_call: DB write failed (%s); "
            "metric lost but ingest continues.", exc,
        )


def daily_spend_usd() -> float:
    """Helper for scripts/dashboards. Returns 0.0 on read failure."""
    cutoff = _start_of_today_utc()
    try:
        with get_session_factory()() as session:
            spent = session.scalar(
                select(func.coalesce(func.sum(VoyageUsage.cost_usd), 0))
                .where(VoyageUsage.created_at >= cutoff)
                .where(VoyageUsage.status == "ok")
            )
    except Exception:
        return 0.0
    return float(spent or 0.0)


def spend_over_window(hours: int) -> float:
    """Cumulative Voyage spend over the last ``hours`` hours."""
    cutoff = datetime.now(UTC) - timedelta(hours=max(int(hours), 1))
    try:
        with get_session_factory()() as session:
            spent = session.scalar(
                select(func.coalesce(func.sum(VoyageUsage.cost_usd), 0))
                .where(VoyageUsage.created_at >= cutoff)
                .where(VoyageUsage.status == "ok")
            )
    except Exception:
        return 0.0
    return float(spent or 0.0)
