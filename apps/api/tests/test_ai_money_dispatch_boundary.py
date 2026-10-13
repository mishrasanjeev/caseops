"""Offline dispatch, process-level SQLite admission and retained migration proof."""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import sessionmaker

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.ai_spend_models import AiProviderSpendAdmission, AiProviderSpendMonth
from caseops_api.db.base import Base
from caseops_api.db.session import CaseOpsSession
from caseops_api.services import ai_money_budget as budget

_NOVEMBER = "2026-11"
_MODEL = "offline-dispatch-model"
_TABLES = [AiProviderSpendMonth.__table__, AiProviderSpendAdmission.__table__]


def _month_values(month: str, *, limit: int = 30) -> dict:
    return {
        "month": month,
        "limit_minor": limit,
        "opening_spend_minor": 0,
        "admitted_minor": 0,
        "inr_per_usd_all_in": Decimal("100"),
        "pricing_json": {
            f"openai:{_MODEL}": {
                "input_usd_per_million": "1",
                "output_usd_per_million": "2",
                "source_url": "https://example.com/offline-dispatch-fixture",
                "source_sha256": "a" * 64,
            }
        },
        "opening_evidence_sha256": "b" * 64,
        "reconciled_at": datetime.now(UTC),
    }


def _reserve() -> str | None:
    return budget.reserve_paid_ai_call(
        provider="openai", model=_MODEL, input_bytes=1000, output_tokens=1000, retry_count=0
    )


@pytest.fixture
def dispatch_clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(month=_NOVEMBER, enabled=True)
    monkeypatch.setattr(budget, "current_budget_month", lambda: state.month)
    monkeypatch.setattr(
        budget,
        "get_settings",
        lambda: SimpleNamespace(
            effective_ai_money_budget_enabled=state.enabled,
            ai_money_budget_start_month=_NOVEMBER,
        ),
    )
    return state


@pytest.fixture
def dispatch_db(tmp_path, monkeypatch) -> Iterator[sessionmaker[CaseOpsSession]]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'dispatch.db').as_posix()}")
    Base.metadata.create_all(engine, tables=_TABLES)
    factory = sessionmaker(
        bind=engine, class_=CaseOpsSession, autoflush=False, expire_on_commit=False
    )
    with factory() as session:
        session.add_all(
            [AiProviderSpendMonth(**_month_values(month)) for month in [_NOVEMBER, "2026-12"]]
        )
        session.commit()
    monkeypatch.setattr(budget, "get_session_factory", lambda: factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _retained(factory) -> tuple[list[tuple], list[tuple]]:
    with factory() as session:
        months = session.execute(
            select(AiProviderSpendMonth.month, AiProviderSpendMonth.admitted_minor).order_by(
                AiProviderSpendMonth.month
            )
        ).all()
        receipts = session.execute(
            select(
                AiProviderSpendAdmission.id,
                AiProviderSpendAdmission.month,
                AiProviderSpendAdmission.upper_bound_minor,
            ).order_by(AiProviderSpendAdmission.id)
        ).all()
        return list(months), list(receipts)


def test_october_bypass_cannot_dispatch_after_november_boundary(
    dispatch_clock, monkeypatch
) -> None:
    dispatch_clock.month = "2026-10"

    def forbidden_factory():
        pytest.fail("October bypass must not acquire an admission transaction")

    monkeypatch.setattr(budget, "get_session_factory", forbidden_factory)
    ticket = _reserve()
    assert ticket is None
    dispatch_clock.month = _NOVEMBER
    with pytest.raises(budget.AiMoneyBudgetError):
        budget.assert_paid_ai_dispatch(ticket)


def test_november_ticket_cannot_dispatch_in_december_or_refund_old_charge(
    dispatch_clock, dispatch_db
) -> None:
    ticket = _reserve()
    assert isinstance(ticket, budget.AiMoneyAdmission)
    assert ticket.month == _NOVEMBER
    before = _retained(dispatch_db)
    assert before == ([(_NOVEMBER, 30), ("2026-12", 0)], [(str(ticket), _NOVEMBER, 30)])
    dispatch_clock.month = "2026-12"
    with pytest.raises(budget.AiMoneyBudgetError):
        budget.assert_paid_ai_dispatch(ticket)
    assert _retained(dispatch_db) == before


def test_same_period_dispatch_uses_typed_committed_ticket(dispatch_clock, dispatch_db) -> None:
    ticket = _reserve()
    assert isinstance(ticket, budget.AiMoneyAdmission)
    assert ticket.month == dispatch_clock.month
    before = _retained(dispatch_db)
    budget.assert_paid_ai_dispatch(ticket)
    assert _retained(dispatch_db) == before


def test_reservation_captures_current_month_exactly_once(
    dispatch_clock, dispatch_db, monkeypatch
) -> None:
    calls: list[str] = []

    def counted_month() -> str:
        calls.append(dispatch_clock.month)
        return dispatch_clock.month

    monkeypatch.setattr(budget, "current_budget_month", counted_month)
    ticket = _reserve()
    assert isinstance(ticket, budget.AiMoneyAdmission)
    assert ticket.month == _NOVEMBER
    assert calls == [_NOVEMBER]


@pytest.mark.parametrize("ticket", [None, "untyped-admission"])
def test_active_period_rejects_missing_or_untyped_ticket(dispatch_clock, ticket) -> None:
    with pytest.raises(budget.AiMoneyBudgetError):
        budget.assert_paid_ai_dispatch(ticket)


@pytest.mark.parametrize("month,enabled", [("2026-10", True), (_NOVEMBER, False)])
def test_inactive_period_or_explicit_disable_preserves_dispatch_bypass(
    dispatch_clock, month: str, enabled: bool
) -> None:
    dispatch_clock.month = month
    dispatch_clock.enabled = enabled
    budget.assert_paid_ai_dispatch(None)


def test_dispatch_no_paid_marker_precedes_clock_and_ticket_validation(monkeypatch) -> None:
    def forbidden_read():
        pytest.fail("The authoritative no-paid marker must be checked first")

    monkeypatch.setattr(budget, "current_budget_month", forbidden_read)
    monkeypatch.setattr(budget, "get_settings", forbidden_read)
    token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
    try:
        with pytest.raises(budget.AiMoneyBudgetError, match="Automated"):
            budget.assert_paid_ai_dispatch("untyped-admission")
    finally:
        reset_automated_test_request(token)


def _sqlite_admission_process(database_path: str, update_barrier, result_pipe) -> None:
    """Spawn-safe worker: only an owned SQLite file, never SDK/provider transport."""
    engine = create_engine(
        f"sqlite:///{Path(database_path).as_posix()}", connect_args={"timeout": 2}
    )
    reached_update = False
    factory = sessionmaker(
        bind=engine, class_=CaseOpsSession, autoflush=False, expire_on_commit=False
    )
    budget.current_budget_month = lambda: _NOVEMBER
    budget.get_settings = lambda: SimpleNamespace(
        effective_ai_money_budget_enabled=True, ai_money_budget_start_month=_NOVEMBER
    )
    budget.get_session_factory = lambda: factory

    @event.listens_for(engine, "before_cursor_execute")
    def pause_update(_connection, _cursor, statement, _parameters, _context, _many) -> None:
        nonlocal reached_update
        normalized = statement.lstrip().replace('"', "").upper()
        if normalized.startswith("UPDATE AI_PROVIDER_SPEND_MONTHS") and not reached_update:
            reached_update = True
            update_barrier.wait(timeout=5)

    outcome: dict[str, object] = {"pid": os.getpid()}
    try:
        ticket = _reserve()
        assert isinstance(ticket, budget.AiMoneyAdmission)
        outcome.update(status="admitted", ticket=str(ticket), month=ticket.month)
    except budget.AiMoneyBudgetError as exc:
        outcome.update(
            status="denied",
            fenced=any(value in str(exc) for value in ("exhausted", "changed concurrently")),
        )
    except BaseException as exc:
        # Preserve failure identity without recording arbitrary exception payloads.
        outcome.update(status="worker-error", error_type=type(exc).__name__)
    finally:
        outcome["reached_update"] = reached_update
        engine.dispose()
        result_pipe.send(outcome)
        result_pipe.close()


def test_two_process_sqlite_conditional_update_has_one_budget_winner(tmp_path, request) -> None:
    database_path = tmp_path / "process-money.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine, tables=_TABLES)
    with engine.begin() as connection:
        connection.execute(AiProviderSpendMonth.__table__.insert(), _month_values(_NOVEMBER))
    engine.dispose()
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    processes = []
    pipes = []
    outcomes = []
    cleanup = []
    deadline = time.monotonic() + 20
    try:
        for _ in range(2):
            receive, send = context.Pipe(duplex=False)
            process = context.Process(
                target=_sqlite_admission_process,
                args=(str(database_path), barrier, send),
                name="caseops-owned-ai-money-race",
            )
            pipes.append(receive)
            processes.append(process)
            try:
                process.start()
            finally:
                send.close()
        for receive in pipes:
            assert receive.poll(max(0, deadline - time.monotonic())), "Owned worker receipt missing"
            outcomes.append(receive.recv())
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))
            assert not process.is_alive(), "Owned SQLite worker did not finish in its total budget"
            assert process.exitcode == 0
        assert len({outcome["pid"] for outcome in outcomes}) == 2
        assert all(outcome["pid"] != os.getpid() for outcome in outcomes)
        assert all(outcome["reached_update"] is True for outcome in outcomes)
        winners = [outcome for outcome in outcomes if outcome["status"] == "admitted"]
        denials = [outcome for outcome in outcomes if outcome["status"] == "denied"]
        assert len(winners) == len(denials) == 1, outcomes
        assert denials[0]["fenced"] is True
        assert winners[0]["month"] == _NOVEMBER
        readback = create_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            with readback.connect() as connection:
                assert connection.scalar(select(AiProviderSpendMonth.admitted_minor)) == 30
                receipts = connection.execute(
                    select(AiProviderSpendAdmission.id, AiProviderSpendAdmission.upper_bound_minor)
                ).all()
                assert receipts == [(winners[0]["ticket"], 30)]
        finally:
            readback.dispose()
    finally:
        for process in processes:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
                cleanup.append(
                    {"pid": process.pid, "exitcode": process.exitcode, "alive": process.is_alive()}
                )
                if not process.is_alive():
                    process.close()
        for receive in pipes:
            receive.close()
        request.node.user_properties.append(
            (
                "ai_money_process_race",
                json.dumps({"outcomes": outcomes, "cleanup": cleanup}, sort_keys=True),
            )
        )
        assert len(cleanup) == len(processes) and all(item["alive"] is False for item in cleanup)


def _load_money_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261011_0001_shared_ai_money_budget.py"
    )
    spec = importlib.util.spec_from_file_location(f"owned_money_migration_{uuid4().hex}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("retained", ["month", "admission"])
def test_money_migration_downgrade_refuses_populated_financial_evidence(
    tmp_path, monkeypatch, retained: str
) -> None:
    migration = _load_money_migration()
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            month_values = _month_values(_NOVEMBER)
            if retained == "admission":
                month_values["admitted_minor"] = 30
            connection.execute(AiProviderSpendMonth.__table__.insert(), month_values)
            if retained == "admission":
                connection.execute(
                    AiProviderSpendAdmission.__table__.insert(),
                    {
                        "id": str(uuid4()),
                        "month": _NOVEMBER,
                        "provider": "openai",
                        "model": _MODEL,
                        "upper_bound_minor": 30,
                        "created_at": datetime.now(UTC),
                    },
                )
            before_months = connection.execute(select(AiProviderSpendMonth.__table__)).all()
            before_receipts = connection.execute(select(AiProviderSpendAdmission.__table__)).all()
            with pytest.raises((RuntimeError, ValueError)):
                migration.downgrade()
            assert set(inspect(connection).get_table_names()) == {table.name for table in _TABLES}
            assert connection.execute(select(AiProviderSpendMonth.__table__)).all() == before_months
            assert (
                connection.execute(select(AiProviderSpendAdmission.__table__)).all()
                == before_receipts
            )
    finally:
        engine.dispose()


def test_money_migration_empty_downgrade_remains_available(tmp_path, monkeypatch) -> None:
    migration = _load_money_migration()
    engine = create_engine(f"sqlite:///{(tmp_path / 'empty-migration.db').as_posix()}")
    try:
        with engine.begin() as connection:
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.downgrade()
            assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
