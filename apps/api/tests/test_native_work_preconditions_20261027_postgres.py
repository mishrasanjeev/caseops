"""Real PostgreSQL HTTP readers and writes; no device or provider acceptance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from caseops_api.api.routes import matters as routes
from caseops_api.db.models import Matter
from caseops_api.db.session import get_engine
from tests.test_native_work_preconditions_20261027 import (
    KINDS,
    assert_work_problem,
    create_payload,
    create_record,
    endpoint,
    exercise_close_reopen,
    exercise_required_and_current,
    exercise_stale_child,
    patch_payload,
    persistence,
    transition,
    work_case,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("kind", KINDS)
def test_postgres_native_observed_current_work(isolated_postgres_client, http_pg_engine, kind):
    assert http_pg_engine.dialect.name == "postgresql"
    exercise_required_and_current(isolated_postgres_client, kind)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("operation", ["create", "update"])
def test_postgres_native_closed_reopened_parent(isolated_postgres_client, kind, operation):
    exercise_close_reopen(isolated_postgres_client, kind, operation)


@pytest.mark.parametrize("kind", KINDS)
def test_postgres_native_stale_child(isolated_postgres_client, kind):
    exercise_stale_child(isolated_postgres_client, kind)


def _entered_or_propagate(future, entered, seconds=3):
    if entered.wait(seconds):
        return
    if future.done():
        future.result()  # Expose an actual HTTP/setup exception before a barrier diagnosis.
    raise AssertionError("Native HTTP request did not reach the admitted service barrier")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("operation", ["create", "update"])
def test_http_inflight_parent_close_reopen_rejects_old_observation(
    isolated_postgres_client,
    monkeypatch,
    kind,
    operation,
):
    client = isolated_postgres_client
    case = work_case(client)
    record = create_record(case, kind)
    payload = create_payload(kind) if operation == "create" else patch_payload(case, kind, record)
    payload["expected_lifecycle_version"] = case["matter"]["lifecycle_version"]
    name = f"{operation}_matter_{kind}"
    original = getattr(routes, name)
    entered, release = Event(), Event()

    def paused(session, **kwargs):
        if kwargs["context"].native_session_id is not None:
            entered.set()
            assert release.wait(5), "Native HTTP request was not released"
        return original(session, **kwargs)

    monkeypatch.setattr(routes, name, paused)
    # A separate TestClient portal permits the browser requests to run while the
    # native synchronous service is deliberately paused on its own event loop.
    native_client = TestClient(
        client.app, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            invoke = native_client.post if operation == "create" else native_client.patch
            future = pool.submit(
                invoke,
                endpoint(case, kind, None if operation == "create" else record),
                headers=case["native"],
                json=payload,
            )
            try:
                _entered_or_propagate(future, entered)
                closed = transition(case, "disposed")
                reopened = transition(case, "intake")
                assert reopened["lifecycle_version"] == closed["lifecycle_version"] + 1
                before = persistence(case)
            finally:
                release.set()
            result = future.result(timeout=5)
    finally:
        release.set()
        native_client.close()
    assert result.status_code == 409, result.text
    assert_work_problem(result, "matter_lifecycle_changed")
    assert persistence(case) == before


@pytest.mark.parametrize("kind", KINDS)
def test_http_inflight_child_update_rejects_old_client_record(
    isolated_postgres_client,
    monkeypatch,
    kind,
):
    client = isolated_postgres_client
    case = work_case(client)
    record = create_record(case, kind)
    original = getattr(routes, f"update_matter_{kind}")
    entered, release = Event(), Event()

    def paused(session, **kwargs):
        if kwargs["context"].native_session_id is not None:
            entered.set()
            assert release.wait(5), "Native child request was not released"
        return original(session, **kwargs)

    monkeypatch.setattr(routes, f"update_matter_{kind}", paused)
    native_client = TestClient(
        client.app, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                native_client.patch,
                endpoint(case, kind, record),
                headers=case["native"],
                json=patch_payload(case, kind, record),
            )
            try:
                _entered_or_propagate(future, entered)
                dirty = (
                    {"title": "Committed concurrent task"}
                    if kind == "task"
                    else {"outcome_note": "Committed concurrent hearing"}
                )
                winner = client.patch(
                    endpoint(case, kind, record), headers=case["browser"], json=dirty
                )
                assert winner.status_code == 200, winner.text
                before = persistence(case)
            finally:
                release.set()
            result = future.result(timeout=5)
    finally:
        release.set()
        native_client.close()
    assert result.status_code == 409, result.text
    assert_work_problem(
        result, "matter_task_changed" if kind == "task" else "matter_hearing_changed"
    )
    assert persistence(case) == before


@pytest.mark.parametrize("kind", KINDS)
def test_native_http_write_waits_for_the_same_parent_row_lock(
    isolated_postgres_client,
    http_pg_engine,
    kind,
):
    client = isolated_postgres_client
    case = work_case(client)
    payload = {
        **create_payload(kind),
        "expected_lifecycle_version": case["matter"]["lifecycle_version"],
    }
    waiter = {"pid": None}
    reached = Event()

    def capture(connection, _cursor, statement, _parameters, _context, _many):
        if "FOR UPDATE OF matters" in statement:
            waiter["pid"] = connection.connection.driver_connection.info.backend_pid
            reached.set()

    native_client = TestClient(
        client.app, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}
    )
    serving_engine = get_engine()
    assert serving_engine.url.database == http_pg_engine.url.database
    event.listen(serving_engine, "before_cursor_execute", capture)
    try:
        with Session(http_pg_engine) as holder, ThreadPoolExecutor(max_workers=1) as pool:
            holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
            locked = holder.scalar(
                select(Matter).where(Matter.id == case["matter"]["id"]).with_for_update(of=Matter)
            )
            assert locked is not None
            future = pool.submit(
                native_client.post, endpoint(case, kind), headers=case["native"], json=payload
            )
            try:
                _entered_or_propagate(future, reached)
                snapshots = []
                deadline = monotonic() + 3
                with http_pg_engine.connect() as observer:
                    for _ in range(150):
                        blockers = observer.scalar(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter["pid"]}
                        )
                        snapshots.append(blockers)
                        if holder_pid in blockers or monotonic() >= deadline:
                            break
                        if future.done():
                            future.result()
                            raise AssertionError(
                                "Native request completed without the parent barrier"
                            )
                        sleep(0.02)
                # Evaluate the final existing snapshot, including a deadline-edge positive.
                assert snapshots and holder_pid in snapshots[-1], snapshots
                assert not future.done()
            finally:
                holder.rollback()
            result = future.result(timeout=5)
    finally:
        event.remove(serving_engine, "before_cursor_execute", capture)
        native_client.close()
    assert result.status_code == 200, result.text
