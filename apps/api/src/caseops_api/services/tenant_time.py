from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def tenant_today(
    timezone_name: str,
    *,
    at: datetime | None = None,
) -> date:
    """Return the calendar date that governs the tenant's legal work."""

    instant = at or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("tenant_today requires a timezone-aware instant")
    return instant.astimezone(ZoneInfo(timezone_name)).date()
