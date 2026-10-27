"""IPLF-030B/UJ-04: second concurrent-DROP wait recovery on fresh PostgreSQL.

Keep this one PG case separate from the unchanged62-case retirement module.
Its independent database fixture and existing retirement helpers are reused.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from alembic import command
from tests import test_audit_prefix_retirement_20261028 as retirement
from tests.test_audit_prefix_retirement_20261028 import (
    FULL,
    LEGACY,
    PARENT,
    PREFIX,
    REVISION,
    TABLE,
    _append,
    _apply,
    _config,
    _healthy,
    _index_state,
    _insert,
    _module,
    _object,
    _others,
    _owners,
    _snapshot,
    _state,
    _version,
)

database = retirement.database


@pytest.mark.postgres
def test_second_drop_wait_cancel_retains_dead_prefix_and_replays(database, record_property):
    engine, config, module = database, _config(), _module()
    command.upgrade(config, PARENT)
    company = _owners(engine)[0]
    original_ids = {_append(engine, company) for _ in range(2)}
    original = {row.id: tuple(row) for row in _snapshot(engine)}
    assert set(original) == original_ids
    full, others = _object(engine, FULL), _others(engine)
    legacy_oid = _index_state(engine, LEGACY).oid
    held, observed = {}, {"second_wait_proven": False}

    def capture_drop(connection, cursor, statement, parameters, context, executemany):
        if (connection.engine.url.database != engine.url.database
                or not statement.startswith("DROP INDEX CONCURRENTLY")
                or not re.search(rf"\b{re.escape(LEGACY)}\b", statement)
                or "worker_pid" in observed):
            return
        assert connection.connection.driver_connection.autocommit is True
        observed["worker_pid"] = connection.exec_driver_sql(
            "SELECT pg_backend_pid()"
        ).scalar_one()
        for setting in ("lock_timeout", "statement_timeout"):
            observed[setting] = connection.exec_driver_sql("SHOW " + setting).scalar_one()
        r1 = engine.connect().execution_options(isolation_level="REPEATABLE READ")
        held["r1"] = r1
        observed["r1_pid"] = r1.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
        r1.execute(sa.text(f"SELECT id FROM {TABLE}")).all()

    def wait_stage(monitor, dead, blocker_key, label):
        while time.monotonic() < observe_end and not future.done():
            worker, blocker = observed.get("worker_pid"), observed.get(blocker_key)
            if worker is not None and blocker is not None:
                state = module._postgres_state(monitor, LEGACY, PREFIX)
                native = monitor.execute(sa.text(
                    "SELECT state, wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers "
                    "FROM pg_stat_activity WHERE pid = :pid AND datname = :database "
                    "AND query LIKE :query"
                ), {"pid": worker, "database": engine.url.database,
                    "query": f"DROP INDEX CONCURRENTLY%{LEGACY}%"}).mappings().one_or_none()
                flags = None if state is None else (
                    state["indisvalid"], state["indisready"], state["indislive"]
                )
                if (flags == (False, not dead, not dead) and native is not None
                        and native["state"] == "active"
                        and native["wait_event_type"] == "Lock"
                        and native["wait_event"] == "virtualxid"
                        and blocker in native["blockers"]):
                    proof = {"flags": flags, "worker_pid": worker, "blocker_pid": blocker,
                             "blocking_pids": list(native["blockers"]),
                             "wait_event": native["wait_event"], "observed_at": time.monotonic()}
                    observed[label] = proof
                    return proof
            time.sleep(0.02)
        if future.done():
            # Preserve a real DDL failure instead of disguising it as an observed phase.
            future.result()
        pytest.fail(f"Native {label} state/wait was not proved; second-wait coverage UNVERIFIED")

    event.listen(Engine, "before_cursor_execute", capture_drop)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            observe_end = time.monotonic() + 30
            future = pool.submit(command.upgrade, config, REVISION)
            try:
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as monitor:
                    first = wait_stage(monitor, False, "r1_pid", "first_wait")
                    r2 = engine.connect().execution_options(isolation_level="REPEATABLE READ")
                    held["r2"] = r2
                    assert not r2.in_transaction()
                    observed["r2_opened_at"] = time.monotonic()
                    assert observed["r2_opened_at"] > first["observed_at"]
                    observed["r2_pid"] = r2.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                    assert observed["r2_pid"] not in {observed["r1_pid"], observed["worker_pid"]}
                    r2.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
                    observed["rolled_back_late_audit"] = _insert(r2, company)
                    late = wait_stage(monitor, False, "r1_pid", "first_wait_with_late_writer")
                    assert observed["r2_pid"] not in late["blocking_pids"]
                    r1 = held.pop("r1")
                    r1.rollback()
                    r1.close()
                    observed["r1_released"] = True
                    second = wait_stage(monitor, True, "r2_pid", "second_wait")
                    assert observed["r1_pid"] not in second["blocking_pids"]
                    observed["second_wait_proven"] = True
                    _healthy(engine, FULL)
                    assert _object(engine, FULL) == full
                    started = time.monotonic()
                    observed["concurrent_audit"] = _append(engine, company)
                    observed["append_seconds"] = time.monotonic() - started
                    assert observed["append_seconds"] < 2
                    wait_stage(monitor, True, "r2_pid", "second_wait_after_append")
                    assert monitor.scalar(sa.text("SELECT pg_cancel_backend(:pid)"),
                                          {"pid": observed["worker_pid"]})
                    with pytest.raises(DBAPIError) as error:
                        future.result(timeout=10)
                    observed["cancel_sqlstate"] = error.value.orig.sqlstate
                    assert observed["cancel_sqlstate"] == "57014"
            finally:
                for name, blocker in list(held.items()):
                    blocker.rollback()
                    blocker.close()
                    observed[name + "_released"] = True
                held.clear()
    finally:
        event.remove(Engine, "before_cursor_execute", capture_drop)
        record_property("second_wait_protocol", dict(observed))

    assert observed["second_wait_proven"] and observed["r2_released"]
    assert observed["lock_timeout"] == "5s" and observed["statement_timeout"] == "15min"
    dead = _state(engine, LEGACY)
    assert dead is not None
    assert (dead["indisvalid"], dead["indisready"], dead["indislive"]) == (False, False, False)
    assert _index_state(engine, LEGACY).oid == legacy_oid
    _healthy(engine, FULL)
    assert _object(engine, FULL) == full and _others(engine) == others
    assert _version(engine) == PARENT
    before_replay = _snapshot(engine)
    assert {row.id for row in before_replay} == original_ids | {observed["concurrent_audit"]}
    assert observed["rolled_back_late_audit"] not in {row.id for row in before_replay}
    assert {row.id: tuple(row) for row in before_replay if row.id in original} == original
    command.upgrade(config, REVISION)
    _apply(engine)
    assert not _state(engine, LEGACY) and _version(engine) == REVISION
    _healthy(engine, FULL)
    assert _object(engine, FULL) == full and _others(engine) == others
    assert _snapshot(engine) == before_replay
    record_property("second_wait_recovery", {
        "legacy_oid": legacy_oid, "cancel_sqlstate": observed["cancel_sqlstate"],
        "retained_audit_ids": sorted(row.id for row in before_replay),
        "parent_version_after_cancel": PARENT, "replayed_version": REVISION,
    })
