"""Offline money-admission controls; no SDK or provider transport is constructed.

The PostgreSQL controls create only the two financial tables in an owned schema.
SQLite concurrency here is thread concurrency, not a cross-process guarantee.
Adapter token bounds, actual invoiced spend and migration rehearsal are separate.
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
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.ai_spend_models import AiProviderSpendAdmission, AiProviderSpendMonth
from caseops_api.db.base import Base
from caseops_api.db.session import CaseOpsSession
from caseops_api.scripts import reconcile_ai_money_budget as reconciliation
from caseops_api.services import ai_money_budget as budget

_MONTH = "2026-11"
_MODEL = "offline-test-model"
_TABLES = [AiProviderSpendMonth.__table__, AiProviderSpendAdmission.__table__]


def _pricing() -> dict:
    # These arithmetic-only rates are not an assertion of any provider's prices.
    return {
        f"openai:{_MODEL}": {
            "input_usd_per_million": "1",
            "output_usd_per_million": "2",
            "source_url": "https://example.com/offline-pricing-fixture",
            "source_sha256": "a" * 64,
        }
    }


def _policy(**overrides: object) -> reconciliation.ReconciledBudget:
    values = {
        "month": _MONTH,
        "limit_minor": 1_000_000,
        "opening_spend_minor": 0,
        "inr_per_usd_all_in": "100",
        "opening_evidence_sha256": "b" * 64,
        "pricing": _pricing(),
    }
    values.update(overrides)
    return reconciliation.ReconciledBudget.model_validate(values)


def _seed(
    factory: sessionmaker[CaseOpsSession],
    *,
    month: str = _MONTH,
    limit: int = 1_000_000,
    opening: int = 0,
    admitted: int | None = None,
    prices: dict | None = None,
) -> None:
    with factory() as session:
        session.add(
            AiProviderSpendMonth(
                month=month,
                limit_minor=limit,
                opening_spend_minor=opening,
                admitted_minor=opening if admitted is None else admitted,
                inr_per_usd_all_in=Decimal("100"),
                pricing_json=_pricing() if prices is None else prices,
                opening_evidence_sha256="b" * 64,
                reconciled_at=datetime.now(UTC),
            )
        )
        session.commit()


def _state(factory: sessionmaker[CaseOpsSession]) -> tuple[int, int, list[tuple[str, int]]]:
    with factory() as session:
        period = session.get(AiProviderSpendMonth, _MONTH)
        assert period is not None
        receipts = session.execute(
            select(AiProviderSpendAdmission.id, AiProviderSpendAdmission.upper_bound_minor)
            .where(AiProviderSpendAdmission.month == _MONTH)
            .order_by(AiProviderSpendAdmission.id)
        ).all()
        return period.opening_spend_minor, period.admitted_minor, list(receipts)


def _reserve(**overrides: object) -> str | None:
    values = {
        "provider": "openai",
        "model": _MODEL,
        "input_bytes": 1000,
        "output_tokens": 1000,
        "retry_count": 0,
    }
    values.update(overrides)
    return budget.reserve_paid_ai_call(**values)


@pytest.fixture(autouse=True)
def frozen_budget_period(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget, "current_budget_month", lambda: _MONTH)
    monkeypatch.setattr(
        budget,
        "get_settings",
        lambda: SimpleNamespace(
            effective_ai_money_budget_enabled=True,
            ai_money_budget_start_month=_MONTH,
        ),
    )


@pytest.fixture
def money_db(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[CaseOpsSession]]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'money.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 2},
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    Base.metadata.create_all(engine, tables=_TABLES)
    assert set(inspect(engine).get_table_names()) == {table.name for table in _TABLES}
    factory = sessionmaker(
        bind=engine, class_=CaseOpsSession, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(budget, "get_session_factory", lambda: factory)
    monkeypatch.setattr(reconciliation, "get_session_factory", lambda: factory)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.mark.parametrize("enabled,month", [(False, _MONTH), (True, "2026-10")])
def test_disabled_or_october_does_not_open_database(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, month: str
) -> None:
    monkeypatch.setattr(budget, "current_budget_month", lambda: month)
    monkeypatch.setattr(
        budget,
        "get_settings",
        lambda: SimpleNamespace(
            effective_ai_money_budget_enabled=enabled,
            ai_money_budget_start_month=_MONTH,
        ),
    )

    def forbidden_factory():
        pytest.fail("Bypassed money admission must not open a database session")

    monkeypatch.setattr(budget, "get_session_factory", forbidden_factory)
    assert _reserve() is None


@pytest.mark.parametrize("month", ["2026-10", _MONTH])
def test_no_paid_marker_denies_before_period_or_database(
    monkeypatch: pytest.MonkeyPatch, month: str
) -> None:
    monkeypatch.setattr(budget, "current_budget_month", lambda: month)

    def forbidden_factory():
        pytest.fail("An automated rejection must precede database access")

    monkeypatch.setattr(budget, "get_session_factory", forbidden_factory)
    token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
    try:
        with pytest.raises(budget.AiMoneyBudgetError, match="Automated verification"):
            _reserve()
    finally:
        reset_automated_test_request(token)


def test_november_requires_reconciled_month(money_db) -> None:
    with pytest.raises(budget.AiMoneyBudgetError, match="awaiting reconciliation"):
        _reserve()
    with money_db() as session:
        assert session.scalars(select(AiProviderSpendMonth)).all() == []
        assert session.scalars(select(AiProviderSpendAdmission)).all() == []


@pytest.mark.parametrize("retries", [0, 1, 2, 3, 4])
def test_exact_ceiling_charge_includes_all_declared_attempts(money_db, retries: int) -> None:
    _seed(money_db, opening=17)
    receipt = _reserve(retry_count=retries)
    assert receipt is not None and str(UUID(receipt)) == receipt
    amount = 30 * (retries + 1)
    assert _state(money_db) == (17, 17 + amount, [(receipt, amount)])


@pytest.mark.parametrize("input_bytes,output_tokens,amount", [(1, 0, 1), (0, 0, 1), (101, 0, 2)])
def test_rounds_up_and_never_records_zero_charge(
    money_db, input_bytes: int, output_tokens: int, amount: int
) -> None:
    _seed(money_db)
    receipt = _reserve(input_bytes=input_bytes, output_tokens=output_tokens)
    assert _state(money_db) == (0, amount, [(receipt, amount)])


@pytest.mark.parametrize(
    "overrides",
    [
        {"input_bytes": -1},
        {"input_bytes": True},
        {"input_bytes": 10_000_001},
        {"output_tokens": -1},
        {"output_tokens": True},
        {"output_tokens": 128_001},
        {"retry_count": -1},
        {"retry_count": True},
        {"retry_count": 5},
        {"provider": "unbounded provider name"},
        {"model": "x" * 121},
    ],
)
def test_unbounded_inputs_denied_before_database(monkeypatch, overrides: dict) -> None:
    def forbidden_factory():
        pytest.fail("Invalid request bounds must precede database access")

    monkeypatch.setattr(budget, "get_session_factory", forbidden_factory)
    with pytest.raises(budget.AiMoneyBudgetError, match="cannot be bounded"):
        _reserve(**overrides)


@pytest.mark.parametrize(
    "invalid",
    ["unknown-model", "http-evidence", "bad-hash", "extra-field", "zero-output", "oversized-map"],
)
def test_unknown_or_malformed_prices_do_not_change_liability(money_db, invalid: str) -> None:
    prices = _pricing()
    entry = prices[f"openai:{_MODEL}"]
    if invalid == "unknown-model":
        prices = {"openai:other-model": entry}
    elif invalid == "http-evidence":
        entry["source_url"] = "http://example.com/offline-pricing-fixture"
    elif invalid == "bad-hash":
        entry["source_sha256"] = "not-a-checksum"
    elif invalid == "extra-field":
        entry["unreviewed_discount"] = True
    elif invalid == "zero-output":
        entry["output_usd_per_million"] = "0"
    else:
        prices.update({f"openai:other-{index}": dict(entry) for index in range(32)})
    _seed(money_db, opening=19, prices=prices)
    with pytest.raises(budget.AiMoneyBudgetError):
        _reserve()
    assert _state(money_db) == (19, 19, [])


def test_exhaustion_preserves_opening_and_prior_receipt(money_db) -> None:
    _seed(money_db, limit=47, opening=17)
    receipt = _reserve()
    before = _state(money_db)
    assert before == (17, 47, [(receipt, 30)])
    with pytest.raises(budget.AiMoneyBudgetError, match="exhausted"):
        _reserve()
    assert _state(money_db) == before


def test_independent_commit_survives_caller_rollback_without_discarding_work(money_db) -> None:
    _seed(money_db)
    with money_db() as caller:
        assert caller.get(AiProviderSpendMonth, _MONTH) is not None
        sibling = AiProviderSpendMonth(
            month="2026-12",
            limit_minor=1_000_000,
            opening_spend_minor=0,
            admitted_minor=0,
            inr_per_usd_all_in=Decimal("100"),
            pricing_json=_pricing(),
            opening_evidence_sha256="c" * 64,
            reconciled_at=datetime.now(UTC),
        )
        caller.add(sibling)
        receipt = _reserve()
        assert caller.in_transaction()
        assert sibling in caller.new
        with money_db() as observer:
            assert observer.get(AiProviderSpendMonth, "2026-12") is None
        caller.rollback()
    assert _state(money_db) == (0, 30, [(receipt, 30)])


def test_owned_database_commit_failure_leaves_no_charge(money_db, monkeypatch) -> None:
    _seed(money_db)

    class CommitFailure(CaseOpsSession):
        def commit(self) -> None:
            self.flush()
            raise OperationalError(None, None, RuntimeError("offline commit fixture"))

    factory = sessionmaker(bind=money_db.kw["bind"], class_=CommitFailure, autoflush=False)
    monkeypatch.setattr(budget, "get_session_factory", lambda: factory)
    with pytest.raises(budget.AiMoneyBudgetError, match="temporarily unavailable"):
        _reserve()
    assert _state(money_db) == (0, 0, [])


def test_database_unavailable_is_not_an_unfunded_admission(monkeypatch) -> None:
    def unavailable_factory():
        raise OperationalError(None, None, RuntimeError("offline connection fixture"))

    monkeypatch.setattr(budget, "get_session_factory", unavailable_factory)
    with pytest.raises(budget.AiMoneyBudgetError, match="temporarily unavailable"):
        _reserve()


def test_independent_admission_does_not_borrow_callers_sqlite_writer_mutex(money_db) -> None:
    from caseops_api.db.session import serialize_sqlite_writer

    _seed(money_db)
    caller = money_db()
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        serialize_sqlite_writer(caller)
        future = pool.submit(_reserve)
        receipt = future.result(timeout=2)
        assert receipt is not None
        assert _state(money_db) == (0, 30, [(receipt, 30)])
    finally:
        caller.rollback()
        caller.close()
        pool.shutdown(wait=True, cancel_futures=True)


def test_sqlite_threads_have_one_finite_budget_winner(money_db) -> None:
    _seed(money_db, limit=30)
    ready = Barrier(2)

    def attempt() -> str | budget.AiMoneyBudgetError:
        ready.wait(timeout=2)
        try:
            result = _reserve()
            assert result is not None
            return result
        except budget.AiMoneyBudgetError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    winners = [result for result in results if isinstance(result, str)]
    denials = [result for result in results if isinstance(result, budget.AiMoneyBudgetError)]
    assert len(winners) == len(denials) == 1
    assert any(text in str(denials[0]) for text in ("exhausted", "changed concurrently"))
    assert _state(money_db) == (0, 30, [(winners[0], 30)])


def test_initialization_requires_explicit_opening_even_when_zero() -> None:
    values = _policy().model_dump(mode="json")
    del values["opening_spend_minor"]
    with pytest.raises(ValidationError, match="opening_spend_minor"):
        reconciliation.ReconciledBudget.model_validate(values)


def test_initialization_exact_replay_cannot_reset_admissions(money_db) -> None:
    policy = _policy(opening_spend_minor=17)
    assert reconciliation.initialize_budget(policy) is True
    receipt = _reserve()
    before = _state(money_db)
    assert before == (17, 47, [(receipt, 30)])
    assert reconciliation.initialize_budget(policy) is False
    assert _state(money_db) == before


@pytest.mark.parametrize("field", ["opening", "limit", "fx", "evidence", "pricing"])
def test_initialization_rejects_changed_snapshot_after_admission(money_db, field: str) -> None:
    policy = _policy(opening_spend_minor=17)
    assert reconciliation.initialize_budget(policy) is True
    _reserve()
    before = _state(money_db)
    changes: dict[str, object] = {}
    if field == "opening":
        changes["opening_spend_minor"] = 0
    elif field == "limit":
        changes["limit_minor"] = 999_999
    elif field == "fx":
        changes["inr_per_usd_all_in"] = "99"
    elif field == "evidence":
        changes["opening_evidence_sha256"] = "c" * 64
    else:
        prices = _pricing()
        prices[f"openai:{_MODEL}"]["output_usd_per_million"] = "1"
        changes["pricing"] = prices
    changed_policy = {"opening_spend_minor": 17, **changes}
    with pytest.raises(ValueError, match="refusing to reset"):
        reconciliation.initialize_budget(_policy(**changed_policy))
    assert _state(money_db) == before


@pytest.mark.parametrize("opening,admitted", [(-1, 0), (20, 19)])
def test_database_rejects_opening_lineage_violation(money_db, opening: int, admitted: int) -> None:
    with pytest.raises(IntegrityError):
        _seed(money_db, opening=opening, admitted=admitted)
    with money_db() as session:
        assert session.scalars(select(AiProviderSpendMonth)).all() == []


@pytest.fixture
def money_postgres_schema(request: pytest.FixtureRequest) -> Iterator[Engine]:
    url = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"}, (
        "Only isolated local PostgreSQL is allowed"
    )
    schema = f"ai_money_{uuid4().hex}"
    admin = create_engine(
        url,
        connect_args={
            "connect_timeout": 5,
            "options": "-c lock_timeout=2000 -c statement_timeout=10000",
        },
    )
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
                    "-c lock_timeout=2000 -c statement_timeout=10000"
                ),
            },
        )
        Base.metadata.create_all(engine, tables=_TABLES)
        assert set(inspect(engine).get_table_names(schema=schema)) == {
            table.name for table in _TABLES
        }
        request.node.user_properties.append(("ai_money_owned_schema", schema))
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            with admin.connect() as connection:
                assert (
                    connection.scalar(
                        text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
                        {"schema": schema},
                    )
                    is False
                )
            request.node.user_properties.append(("ai_money_owned_schema_dropped", "true"))
        admin.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("holder_spends", [False, True], ids=["waiter-wins", "holder-wins"])
def test_postgres_month_lock_has_one_directed_admission_winner(
    money_postgres_schema: Engine,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    holder_spends: bool,
) -> None:
    factory = sessionmaker(
        bind=money_postgres_schema, class_=CaseOpsSession, autoflush=False, expire_on_commit=False
    )
    _seed(factory, limit=30)
    holder = factory()
    worker = factory()
    # Connect all roles before the deliberate two-second lock interval.
    holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
    worker_pid = worker.scalar(text("SELECT pg_backend_pid()"))
    observer = money_postgres_schema.connect().execution_options(isolation_level="AUTOCOMMIT")
    assert observer.scalar(text("SELECT pg_backend_pid()")) not in {holder_pid, worker_pid}
    monkeypatch.setattr(budget, "get_session_factory", lambda: lambda: worker)
    entered = Event()
    timeline: dict[str, object] = {"holder_pid": holder_pid, "waiter_pid": worker_pid}
    pool = ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        period = holder.scalar(
            select(AiProviderSpendMonth)
            .where(AiProviderSpendMonth.month == _MONTH)
            .with_for_update()
        )
        assert period is not None
        if holder_spends:
            period.admitted_minor = 30
            holder.add(
                AiProviderSpendAdmission(
                    id=str(uuid4()),
                    month=_MONTH,
                    provider="openai",
                    model=_MODEL,
                    upper_bound_minor=30,
                )
            )
            holder.flush()
        timeline["held_monotonic"] = time.monotonic()

        def attempt() -> str | budget.AiMoneyBudgetError:
            entered.set()
            try:
                receipt = _reserve()
                assert receipt is not None
                return receipt
            except budget.AiMoneyBudgetError as exc:
                return exc

        future = pool.submit(attempt)
        assert entered.wait(timeout=1)
        deadline = time.monotonic() + 1
        blockers: list[int] = []
        while time.monotonic() < deadline:
            blockers = observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pid})
            if holder_pid in blockers:
                timeline["directed_wait_monotonic"] = time.monotonic()
                break
            time.sleep(0.005)
        assert holder_pid in blockers, "Native holder -> waiter direction was not observed"
        assert not future.done()
        timeline["blockers"] = blockers
        timeline["released_monotonic"] = time.monotonic()
        holder.commit()
        result = future.result(timeout=5)
        timeline["finished_monotonic"] = time.monotonic()
        opening, admitted, receipts = _state(factory)
        assert opening == 0 and admitted == 30
        assert len(receipts) == 1 and receipts[0][1] == 30
        if holder_spends:
            assert isinstance(result, budget.AiMoneyBudgetError)
            assert "exhausted" in str(result)
        else:
            assert isinstance(result, str)
            assert receipts == [(result, 30)]
    finally:
        holder.rollback()
        holder.close()
        pool.shutdown(wait=True, cancel_futures=True)
        worker.close()
        observer.close()
        request.node.user_properties.append(
            ("ai_money_native_wait", json.dumps(timeline, sort_keys=True))
        )
