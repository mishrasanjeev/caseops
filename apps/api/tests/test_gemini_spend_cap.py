"""Gemini-only INR 10,000 monthly cap (owner decision 2026-11-01); offline.

SQLite controls use owned files; the PostgreSQL controls create only the two
Gemini cap tables in an owned schema of an isolated local server. SQLite
thread concurrency is not a cross-process guarantee; the PostgreSQL row lock is.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from caseops_api.db.ai_spend_models import AiGeminiSpendAdmission, AiGeminiSpendMonth
from caseops_api.db.base import Base
from caseops_api.db.session import CaseOpsSession
from caseops_api.services import gemini_spend_cap as cap
from caseops_api.services.ai_money_budget import AiMoneyBudgetError

_MODEL = "gemini-3.8-flash"
_TABLES = [AiGeminiSpendMonth.__table__, AiGeminiSpendAdmission.__table__]
_NOV = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


def _sqlite_factory(path) -> tuple[Engine, sessionmaker[CaseOpsSession]]:
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    Base.metadata.create_all(engine, tables=_TABLES)
    return engine, sessionmaker(
        bind=engine, class_=CaseOpsSession, autoflush=False, expire_on_commit=False
    )


@pytest.fixture
def ledger(tmp_path, monkeypatch) -> Iterator[sessionmaker[CaseOpsSession]]:
    engine, factory = _sqlite_factory(tmp_path / "gemini-cap.db")
    monkeypatch.setattr(cap, "get_session_factory", lambda: factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _state(factory, month: str = "2026-11") -> tuple[int | None, int | None, list[tuple]]:
    with factory() as session:
        period = session.get(AiGeminiSpendMonth, month)
        receipts = session.execute(
            select(
                AiGeminiSpendAdmission.id,
                AiGeminiSpendAdmission.model,
                AiGeminiSpendAdmission.upper_bound_minor,
            )
            .where(AiGeminiSpendAdmission.month == month)
            .order_by(AiGeminiSpendAdmission.id)
        ).all()
        return (
            None if period is None else period.limit_minor,
            None if period is None else period.admitted_minor,
            [tuple(row) for row in receipts],
        )


def _reserve(*, now=_NOV, input_bytes=10_000, output_tokens=8192) -> str:
    return cap.reserve_gemini_spend(
        model=_MODEL, input_bytes=input_bytes, output_tokens=output_tokens, now=now
    )


def test_pinned_constants_are_the_reviewed_owner_decision():
    assert cap.GEMINI_FALLBACK_MODEL == _MODEL
    assert cap.MONTHLY_CAP_MINOR == 1_000_000  # INR 10,000 in paise
    assert cap._USD_PER_MILLION == {_MODEL: (Decimal("1.50"), Decimal("7.50"))}
    assert cap.INR_PER_USD_ALL_IN == Decimal("95.0")
    assert cap.PRICING_SOURCE_URL == (
        "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
    )
    assert cap.PRICING_CHECKED_ON == "2026-11-01"
    assert cap.CAP_REFUSAL == (
        "The monthly Gemini fallback allowance is used up. No external request was sent."
    )


@pytest.mark.parametrize(
    ("input_bytes", "output_tokens", "expected"),
    [
        # (10,000 x 1.50 + 8,192 x 7.50) / 1e6 USD x 95 x 100 = 726.18 -> 727 paise
        (10_000, 8192, 727),
        (1_000_000, 0, 14_250),  # $1.50 -> INR 142.50
        (0, 100_000, 7_125),  # $0.75 -> INR 71.25
        (1, 0, 1),  # never a zero charge
        (0, 0, 1),
        (10_000_000, 128_000, 151_620),  # largest admissible request: $15.96
    ],
)
def test_reservation_math_rounds_up_from_conservative_prices(input_bytes, output_tokens, expected):
    assert (
        cap.worst_case_minor(model=_MODEL, input_bytes=input_bytes, output_tokens=output_tokens)
        == expected
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "gemini-3.5-flash-lite"},
        {"model": "bad model"},
        {"input_bytes": -1},
        {"input_bytes": 10_000_001},
        {"input_bytes": True},
        {"output_tokens": 128_001},
        {"output_tokens": 1.5},
    ],
)
def test_unpriced_or_unbounded_requests_refused_before_the_database(monkeypatch, overrides):
    monkeypatch.setattr(cap, "get_session_factory", lambda: pytest.fail("no database access"))
    values = {"model": _MODEL, "input_bytes": 10, "output_tokens": 10, **overrides}
    with pytest.raises(AiMoneyBudgetError, match="No external request was sent") as caught:
        cap.reserve_gemini_spend(**values)
    assert not isinstance(caught.value, cap.GeminiAllowanceError)


def test_month_row_is_created_automatically_at_zero_with_content_free_admission(ledger):
    assert _state(ledger) == (None, None, [])
    receipt = _reserve()
    assert _state(ledger) == (1_000_000, 727, [(receipt, _MODEL, 727)])
    columns = {column["name"] for column in inspect(ledger.kw["bind"]).get_columns(
        "ai_gemini_spend_admissions"
    )}
    assert columns == {"id", "month", "model", "upper_bound_minor", "created_at"}
    second = _reserve()
    limit, admitted, receipts = _state(ledger)
    assert (limit, admitted) == (1_000_000, 1454)
    assert sorted(row[0] for row in receipts) == sorted([receipt, second])


def test_refusal_at_the_cap_keeps_prior_liability(ledger):
    with ledger() as session:
        session.add(
            AiGeminiSpendMonth(
                month="2026-11", limit_minor=1_000_000, admitted_minor=1_000_000 - 727,
                created_at=_NOV,
            )
        )
        session.commit()
    receipt = _reserve()  # exactly fits
    assert _state(ledger) == (1_000_000, 1_000_000, [(receipt, _MODEL, 727)])
    with pytest.raises(cap.GeminiAllowanceError) as caught:
        _reserve(input_bytes=0, output_tokens=0)  # even one paise is refused
    assert str(caught.value) == cap.CAP_REFUSAL
    assert _state(ledger) == (1_000_000, 1_000_000, [(receipt, _MODEL, 727)])


def test_lowered_limit_row_is_honoured_and_corrupt_rows_fail_closed(ledger):
    with ledger() as session:
        session.add(
            AiGeminiSpendMonth(month="2026-11", limit_minor=500, admitted_minor=0, created_at=_NOV)
        )
        session.commit()
    with pytest.raises(cap.GeminiAllowanceError):
        _reserve()
    with ledger() as session, pytest.raises(IntegrityError):
        session.add(
            AiGeminiSpendMonth(
                month="2026-12", limit_minor=1_000_001, admitted_minor=0, created_at=_NOV
            )
        )
        session.commit()


@pytest.mark.parametrize(
    ("moment", "month"),
    [
        (datetime(2026, 10, 31, 18, 29, 59, 999999, tzinfo=UTC), "2026-10"),
        (datetime(2026, 10, 31, 18, 30, tzinfo=UTC), "2026-11"),
        (datetime(2026, 12, 31, 18, 29, 59, tzinfo=UTC), "2026-12"),
        (datetime(2026, 12, 31, 18, 30, tzinfo=UTC), "2027-01"),
    ],
)
def test_ist_month_boundaries(moment, month):
    assert cap.ist_month(moment) == month


def test_new_ist_month_rolls_over_automatically_after_exhaustion(ledger):
    with ledger() as session:
        session.add(
            AiGeminiSpendMonth(
                month="2026-10", limit_minor=1_000_000, admitted_minor=1_000_000,
                created_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
        )
        session.commit()
    before = datetime(2026, 10, 31, 18, 29, 59, tzinfo=UTC)
    after = datetime(2026, 10, 31, 18, 30, tzinfo=UTC)
    with pytest.raises(cap.GeminiAllowanceError):
        _reserve(now=before)
    receipt = _reserve(now=after)
    assert _state(ledger, "2026-10") == (1_000_000, 1_000_000, [])
    assert _state(ledger) == (1_000_000, 727, [(receipt, _MODEL, 727)])


def test_independent_commit_survives_caller_rollback(ledger):
    caller = ledger()
    try:
        caller.execute(text("SELECT 1"))
        receipt = _reserve()
        caller.rollback()
    finally:
        caller.close()
    assert _state(ledger) == (1_000_000, 727, [(receipt, _MODEL, 727)])


def test_ledger_unavailable_is_not_a_funded_admission(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    factory = sessionmaker(bind=engine, class_=CaseOpsSession)
    monkeypatch.setattr(cap, "get_session_factory", lambda: factory)
    try:
        with pytest.raises(AiMoneyBudgetError, match="temporarily unavailable") as caught:
            _reserve()
        assert not isinstance(caught.value, cap.GeminiAllowanceError)
    finally:
        engine.dispose()


def test_sqlite_two_writer_race_has_one_winner(ledger):
    with ledger() as session:
        session.add(
            AiGeminiSpendMonth(
                month="2026-11", limit_minor=1_000_000, admitted_minor=1_000_000 - 727,
                created_at=_NOV,
            )
        )
        session.commit()
    ready = Barrier(2)

    def attempt() -> str | AiMoneyBudgetError:
        ready.wait(timeout=5)
        try:
            return _reserve()
        except AiMoneyBudgetError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in [pool.submit(attempt) for _ in "ab"]]
    winners = [result for result in results if isinstance(result, str)]
    losers = [result for result in results if isinstance(result, cap.GeminiAllowanceError)]
    assert len(winners) == len(losers) == 1
    assert _state(ledger) == (1_000_000, 1_000_000, [(winners[0], _MODEL, 727)])


def test_sqlite_first_writers_of_a_new_month_both_fit(ledger):
    ready = Barrier(2)

    def attempt() -> str:
        ready.wait(timeout=5)
        return _reserve()

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = [future.result(timeout=10) for future in [pool.submit(attempt) for _ in "ab"]]
    limit, admitted, rows = _state(ledger)
    assert (limit, admitted) == (1_000_000, 1454)
    assert sorted(row[0] for row in rows) == sorted(receipts)


@pytest.mark.parametrize(
    "client_fixture",
    ["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)],
)
def test_migrated_schema_matches_the_ledger(request, client_fixture):
    # Both fixtures build their database with the Alembic chain (20261101_0002).
    request.getfixturevalue(client_fixture)
    receipt = _reserve()
    from caseops_api.db.session import get_session_factory

    limit, admitted, rows = _state(get_session_factory())
    assert (limit, admitted, rows) == (1_000_000, 727, [(receipt, _MODEL, 727)])


# --- PostgreSQL ---------------------------------------------------------------------


@pytest.fixture
def cap_postgres(request: pytest.FixtureRequest, monkeypatch) -> Iterator[Engine]:
    url = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"}, "Only isolated local PostgreSQL"
    schema = f"gemini_cap_{uuid4().hex}"
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    engine: Engine | None = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        engine = create_engine(
            url,
            connect_args={
                "connect_timeout": 5,
                "options": (
                    f"-c search_path={schema},pg_catalog "
                    "-c lock_timeout=5000 -c statement_timeout=10000"
                ),
            },
        )
        Base.metadata.create_all(engine, tables=_TABLES)
        assert set(inspect(engine).get_table_names(schema=schema)) == {t.name for t in _TABLES}
        request.node.user_properties.append(("gemini_cap_owned_schema", schema))
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _pg_factory(engine: Engine) -> sessionmaker[CaseOpsSession]:
    return sessionmaker(bind=engine, class_=CaseOpsSession, autoflush=False, expire_on_commit=False)


@pytest.mark.postgres
@pytest.mark.parametrize("holder_spends", [False, True], ids=["waiter-wins", "holder-wins"])
def test_postgres_month_lock_has_one_directed_winner(
    cap_postgres: Engine, monkeypatch, request, holder_spends: bool
) -> None:
    factory = _pg_factory(cap_postgres)
    with factory() as session:
        session.add(
            AiGeminiSpendMonth(
                month="2026-11", limit_minor=1_000_000, admitted_minor=1_000_000 - 727,
                created_at=_NOV,
            )
        )
        session.commit()
    holder, worker = factory(), factory()
    holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
    # Keep the worker's connection checked out so its pid stays the observed one.
    worker_pid = worker.scalar(text("SELECT pg_backend_pid()"))
    observer = cap_postgres.connect().execution_options(isolation_level="AUTOCOMMIT")
    monkeypatch.setattr(cap, "get_session_factory", lambda: lambda: worker)
    entered = Event()
    timeline: dict[str, object] = {"holder_pid": holder_pid, "waiter_pid": worker_pid}
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        period = holder.scalar(
            select(AiGeminiSpendMonth)
            .where(AiGeminiSpendMonth.month == "2026-11")
            .with_for_update()
        )
        assert period is not None
        if holder_spends:
            period.admitted_minor = 1_000_000
            holder.add(
                AiGeminiSpendAdmission(
                    id=str(uuid4()), month="2026-11", model=_MODEL, upper_bound_minor=727,
                    created_at=_NOV,
                )
            )
            holder.flush()

        def attempt() -> str | AiMoneyBudgetError:
            entered.set()
            try:
                return _reserve()
            except AiMoneyBudgetError as exc:
                return exc

        future = pool.submit(attempt)
        assert entered.wait(timeout=2)
        deadline = time.monotonic() + 3
        blockers: list[int] = []
        while time.monotonic() < deadline:
            blockers = observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pid})
            if holder_pid in blockers:
                break
            time.sleep(0.005)
        assert holder_pid in blockers, "native holder -> waiter wait was not observed"
        assert not future.done()
        timeline["blockers"] = blockers
        holder.commit()
        result = future.result(timeout=10)
        limit, admitted, rows = _state(factory)
        assert (limit, admitted, len(rows)) == (1_000_000, 1_000_000, 1)
        if holder_spends:
            assert isinstance(result, cap.GeminiAllowanceError)
            assert str(result) == cap.CAP_REFUSAL
        else:
            assert isinstance(result, str) and rows[0][0] == result
    finally:
        holder.rollback()
        holder.close()
        pool.shutdown(wait=True, cancel_futures=True)
        worker.close()
        observer.close()
        request.node.user_properties.append(("gemini_cap_native_wait", json.dumps(timeline)))


@pytest.mark.postgres
def test_postgres_concurrent_month_creation_and_race(cap_postgres: Engine, monkeypatch) -> None:
    factory = _pg_factory(cap_postgres)
    monkeypatch.setattr(cap, "get_session_factory", lambda: factory)
    ready = Barrier(4)

    def attempt() -> str | AiMoneyBudgetError:
        ready.wait(timeout=5)
        try:
            return _reserve()
        except AiMoneyBudgetError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [future.result(timeout=20) for future in [pool.submit(attempt) for _ in "abcd"]]
    # Concurrent first writers of a new month all fit; none sees a duplicate key.
    assert all(isinstance(result, str) for result in results), results
    limit, admitted, rows = _state(factory)
    assert (limit, admitted) == (1_000_000, 4 * 727)
    assert sorted(row[0] for row in rows) == sorted(results)
    # Only one of two racing writers fits the last allowance.
    with factory() as session:
        session.execute(
            AiGeminiSpendMonth.__table__.update()
            .where(AiGeminiSpendMonth.month == "2026-11")
            .values(admitted_minor=1_000_000 - 727)
        )
        session.commit()
    race = Barrier(2)

    def last() -> str | AiMoneyBudgetError:
        race.wait(timeout=5)
        try:
            return _reserve()
        except AiMoneyBudgetError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        final = [future.result(timeout=20) for future in [pool.submit(last) for _ in "ab"]]
    assert sum(isinstance(result, str) for result in final) == 1
    assert sum(isinstance(result, cap.GeminiAllowanceError) for result in final) == 1
    assert _state(factory)[1] == 1_000_000
