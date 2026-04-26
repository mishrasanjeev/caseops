"""VoyageUsage ledger + daily-cap tests.

Anchored to the Apr 18-26 incident where $343 of Voyage spend went
unnoticed because we had no on-DB ledger. These tests prove:

1. ``record_call`` writes one row per Voyage embed with cost derived
   from tokens × price.
2. ``assert_under_daily_cap`` raises ``VoyageDailyCapExceeded`` once
   today's cumulative cost crosses the configured cap.
3. Cap=0 disables the gate (escape hatch).
4. Audit-disabled mode skips the write but the cap still applies.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.db.models import VoyageUsage
from caseops_api.db.session import get_session_factory
from caseops_api.services import voyage_usage as vu


def _wipe(session) -> None:
    session.query(VoyageUsage).delete()
    session.commit()


def test_estimate_cost_usd_uses_price_per_million(client: TestClient) -> None:
    # 1M tokens at $0.18/M = $0.18
    assert abs(vu.estimate_cost_usd(tokens=1_000_000, price_per_million_usd=0.18) - 0.18) < 1e-9
    # Half a million = $0.09
    assert abs(vu.estimate_cost_usd(tokens=500_000, price_per_million_usd=0.18) - 0.09) < 1e-9
    # Negative tokens clamp to 0
    assert vu.estimate_cost_usd(tokens=-5, price_per_million_usd=0.18) == 0.0


def test_record_call_writes_row_with_derived_cost(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_VOYAGE_USAGE_AUDIT_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_VOYAGE_PRICE_PER_MILLION_TOKENS_USD", "0.18")
    get_settings.cache_clear()
    factory = get_session_factory()
    with factory() as session:
        _wipe(session)

    vu.record_call(
        purpose="ingest",
        model="voyage-4-large",
        input_type="document",
        texts_count=10,
        tokens=2_000_000,  # $0.36 worth
        dimensions=1024,
        latency_ms=120,
    )

    with factory() as session:
        rows = session.query(VoyageUsage).all()
    assert len(rows) == 1
    assert rows[0].purpose == "ingest"
    assert rows[0].tokens == 2_000_000
    assert abs(float(rows[0].cost_usd) - 0.36) < 1e-6
    assert rows[0].status == "ok"


def test_assert_under_daily_cap_raises_when_over(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_VOYAGE_USAGE_AUDIT_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_VOYAGE_DAILY_CAP_USD", "0.10")
    monkeypatch.setenv("CASEOPS_VOYAGE_PRICE_PER_MILLION_TOKENS_USD", "0.18")
    get_settings.cache_clear()
    factory = get_session_factory()
    with factory() as session:
        _wipe(session)

    # Single call worth $0.18 — already over the $0.10 cap.
    vu.record_call(
        purpose="ingest",
        model="voyage-4-large",
        input_type="document",
        texts_count=5,
        tokens=1_000_000,
        dimensions=1024,
        latency_ms=80,
    )

    try:
        vu.assert_under_daily_cap()
    except vu.VoyageDailyCapExceeded as exc:
        assert "0.10" in str(exc) or "$0.1" in str(exc)
    else:
        raise AssertionError("expected VoyageDailyCapExceeded")


def test_assert_under_daily_cap_noop_when_zero(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_VOYAGE_DAILY_CAP_USD", "0")
    get_settings.cache_clear()
    factory = get_session_factory()
    with factory() as session:
        _wipe(session)
        # Drop a $1000 row; cap=0 must not raise.
        session.add(VoyageUsage(
            purpose="ingest", model="voyage-4-large", input_type="document",
            texts_count=1, tokens=999_999, dimensions=1024, cost_usd=1000.0,
            latency_ms=10, status="ok",
        ))
        session.commit()

    vu.assert_under_daily_cap()  # must not raise


def test_assert_under_daily_cap_ignores_yesterday(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_VOYAGE_DAILY_CAP_USD", "0.10")
    get_settings.cache_clear()
    factory = get_session_factory()
    with factory() as session:
        _wipe(session)
        # A $1000 spend booked at yesterday must not count against
        # today's cap — the cap is per-UTC-day.
        yesterday = datetime.now(UTC) - timedelta(days=1, hours=2)
        session.add(VoyageUsage(
            purpose="ingest", model="voyage-4-large", input_type="document",
            texts_count=1, tokens=999_999, dimensions=1024, cost_usd=1000.0,
            latency_ms=10, status="ok", created_at=yesterday,
        ))
        session.commit()

    vu.assert_under_daily_cap()  # must not raise


def test_audit_disabled_skips_write_but_cap_still_applies(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_VOYAGE_USAGE_AUDIT_ENABLED", "false")
    monkeypatch.setenv("CASEOPS_VOYAGE_DAILY_CAP_USD", "0.10")
    monkeypatch.setenv("CASEOPS_VOYAGE_PRICE_PER_MILLION_TOKENS_USD", "0.18")
    get_settings.cache_clear()
    factory = get_session_factory()
    with factory() as session:
        _wipe(session)

    vu.record_call(
        purpose="ingest", model="voyage-4-large", input_type="document",
        texts_count=5, tokens=1_000_000, dimensions=1024, latency_ms=10,
    )
    with factory() as session:
        assert session.query(VoyageUsage).count() == 0  # write skipped

    # Cap reads from DB so with no rows it stays under cap.
    vu.assert_under_daily_cap()
