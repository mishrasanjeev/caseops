from __future__ import annotations

from datetime import UTC, datetime

import pytest

from caseops_api.services.tenant_time import tenant_today


def test_tenant_today_uses_the_tenant_calendar_across_utc_midnight() -> None:
    instant = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)

    assert tenant_today("Asia/Calcutta", at=instant).isoformat() == "2026-08-28"
    assert tenant_today("UTC", at=instant).isoformat() == "2026-08-27"


def test_tenant_today_rejects_a_naive_instant() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        tenant_today("Asia/Calcutta", at=datetime(2026, 8, 28, 1, 0))
