"""Source-prepared PG invariants. No migration/DB acceptance until separately run.

Canonical writers use READ COMMITTED and do not force deferred constraints early.
Arbitrary SET CONSTRAINTS IMMEDIATE administration followed by more source writes
is not claimed supported. Isolation-level regressions retain standard 40001.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from caseops_api.db.models import MatterTask, MatterTaskQueueDirty
from caseops_api.db.session import get_session_factory
from caseops_api.services import matter_work_queue as queue
from tests.test_matter_work_queue_20261027 import context_for, setup, task
from tests.test_matter_work_queue_20261027_postgres import (
    explicit_bearer_actor as explicit_bearer_actor,
)
from tests.test_matter_work_queue_20261027_postgres import (
    forbid_unadmitted_network as forbid_unadmitted_network,
)

pytestmark = pytest.mark.postgres


def ids(session, statement):
    return [row["id"] for row in session.execute(statement).mappings()]


@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_same_prebuilt_select_reads_own_changes_rollback_and_committed_state(
    isolated_postgres_client,
    operation,
):
    case = setup(isolated_postgres_client)
    first = task(isolated_postgres_client, case["owner"], case["matter"], None)
    with get_session_factory()() as session:
        retained = queue.work_queue_statement(
            session,
            context=context_for(session, case["actor"]),
            ownership="unassigned",
            dates="all",
        )
        before = list(session.execute(retained).mappings())
        assert [row["id"] for row in before] == [first["id"]]
        if operation == "insert":
            row = session.get(MatterTask, first["id"])
            created = MatterTask(
                id=str(uuid4()),
                company_id=row.company_id,
                matter_id=row.matter_id,
                owner_membership_id=None,
                title="Own pending creation",
                status="todo",
                priority="medium",
                due_on=date(2027, 1, 1),
            )
            session.add(created)
        elif operation == "update":
            session.get(MatterTask, first["id"]).title = "Own pending update"
        else:
            session.delete(session.get(MatterTask, first["id"]))
        session.flush()
        assert session.scalar(select(MatterTaskQueueDirty.transaction_id).limit(1)) is not None
        during = list(session.execute(retained).mappings())
        if operation == "insert":
            assert set(row["id"] for row in during) == {first["id"], created.id}
        elif operation == "update":
            assert during[0]["title"] == "Own pending update"
        else:
            assert during == []
        session.rollback()
        assert list(session.execute(retained).mappings()) == before
        session.rollback()
        row = session.get(MatterTask, first["id"])
        row.title = "Committed exact title"
        session.commit()
        assert session.scalar(select(MatterTaskQueueDirty.transaction_id).limit(1)) is None
        assert list(session.execute(retained).mappings())[0]["title"] == "Committed exact title"


def wait_event(event, peer=None, seconds=5):
    """Surface a completed failed peer before diagnosing a missing barrier."""
    deadline = monotonic() + seconds
    while not event.wait(min(0.02, max(0, deadline - monotonic()))):
        if peer is not None and peer.done():
            peer.result()
            raise AssertionError("Peer completed before the required barrier")
        if monotonic() >= deadline:
            raise AssertionError("Required source-write barrier was not reached")


def source_lock_cycle(client, *, force_immediate):
    case = setup(client)
    one = task(client, case["owner"], case["matter"], None)
    two = task(client, case["owner"], case["matter"], None)
    a_flushed, b_flushed = threading.Event(), threading.Event()

    def a():
        with get_session_factory()() as session:
            session.execute(text("SET LOCAL statement_timeout='5s'"))
            session.execute(text("SET LOCAL lock_timeout='5s'"))
            session.get(MatterTask, one["id"]).title = "A first source write"
            session.flush()
            if force_immediate:
                session.execute(text("SET CONSTRAINTS trg_task_queue_finalize IMMEDIATE"))
            a_flushed.set()
            wait_event(b_flushed)
            # Default deferral must not hold a group lock while this waits for
            # B's source row. B can commit without reading/locking A's source row.
            session.get(MatterTask, two["id"]).title = "A second source write"
            session.flush()
            session.commit()
            return True

    def b():
        wait_event(a_flushed)
        with get_session_factory()() as session:
            session.execute(text("SET LOCAL statement_timeout='5s'"))
            session.execute(text("SET LOCAL lock_timeout='5s'"))
            session.get(MatterTask, two["id"]).title = "B independent source write"
            session.flush()
            b_flushed.set()
            session.commit()
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa, fb = pool.submit(a), pool.submit(b)
        try:
            wait_event(a_flushed, peer=fa)
            wait_event(b_flushed, peer=fb)
            assert fa.result(timeout=7) is True
            assert fb.result(timeout=7) is True
        finally:
            a_flushed.set()
            b_flushed.set()
    with get_session_factory()() as session:
        assert session.get(MatterTask, one["id"]).title == "A first source write"
        assert session.get(MatterTask, two["id"]).title == "A second source write"
        current = queue.list_matter_work_queue(
            session, context=context_for(session, case["actor"]), ownership="unassigned"
        )
        assert {row.id: row.title for row in current.items} == {
            one["id"]: "A first source write",
            two["id"]: "A second source write",
        }


def assert_queue_function_owner_catalog(tmp_path):
    from caseops_api.db.session import get_engine

    engine = get_engine()
    assert_queue_ddl_transport(engine, tmp_path)
    signatures = {
        "caseops_refresh_task_queue_group": "text, text, text",
        "caseops_finalize_task_queue": "",
        "caseops_task_queue_insert": "",
        "caseops_task_queue_update": "",
        "caseops_task_queue_delete": "",
        "caseops_task_queue_truncate": "",
    }
    with engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT current_user,session_user,r.oid,current_setting('role') "
                "FROM pg_roles r WHERE r.rolname=current_user"
            )
        ).one()
        functions = connection.execute(
            text(
                "SELECT p.proname,p.oid,p.proowner,r.rolname,p.prosecdef,p.proconfig,"
                "oidvectortypes(p.proargtypes),p.proacl IS NOT NULL,p.provolatile,"
                "EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) "
                "a WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),"
                "has_function_privilege(current_user,p.oid,'EXECUTE') "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='public' AND p.proname IN "
                "('caseops_refresh_task_queue_group','caseops_finalize_task_queue',"
                "'caseops_task_queue_insert','caseops_task_queue_update','caseops_task_queue_delete',"
                "'caseops_task_queue_truncate') ORDER BY p.proname LIMIT 7"
            )
        ).all()
    # The isolated canonical migrator/runtime connection is the same owner.
    # No arbitrary differently granted DB role is claimed supported.
    assert role[0] == role[1] == engine.url.username and role[3] == "none"
    assert len(functions) == 6 and {row[0]: row[6] for row in functions} == signatures
    for row in functions:
        assert (row[2], row[3]) == (role[2], role[0])
        assert row[4] is False and row[7] is True and row[8] == "v"
        assert row[9] is False and row[10] is True
        assert len(row[5]) == 1
        key, value = row[5][0].split("=", 1)
        assert key == "search_path"
        assert [part.strip() for part in value.split(",")] == ["pg_catalog", "public"]
    evidence = {
        "scope": "actual isolated canonical migrator/runtime role only",
        "currentUser": role[0],
        "sessionUser": role[1],
        "roleOid": role[2],
        "functions": [
            dict(
                name=row[0],
                oid=row[1],
                ownerOid=row[2],
                owner=row[3],
                securityDefiner=row[4],
                searchPath=row[5],
                signature=row[6],
                explicitAcl=row[7],
                volatility=row[8],
                publicExecute=row[9],
                ownerExecute=row[10],
            )
            for row in functions
        ],
    }
    (tmp_path / "queue-function-owner-catalog.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )


def assert_queue_ddl_transport(engine, tmp_path):
    """The actual psycopg cursor must receive raw parameter-free modulo DDL."""
    from sqlalchemy.exc import ProgrammingError

    from caseops_api.db.task_queue_page_schema_v1 import install

    baseline = None
    with engine.connect() as connection:
        identity = id(connection.connection.dbapi_connection)
        try:
            connection.exec_driver_sql("SELECT 27 % 25")
        except ProgrammingError as error:
            baseline = type(error.orig).__name__
        finally:
            connection.rollback()
        assert baseline == "ProgrammingError"
        assert id(connection.connection.dbapi_connection) == identity
        result = connection.exec_driver_sql(
            "SELECT 27 % 25", execution_options={"no_parameters": True}
        ).scalar_one()
        assert result == 2
        assert connection.get_execution_options().get("no_parameters") is not True
        # The reviewed functions explicitly target public. Reinstall only these
        # six functions and their dependent triggers inside one transaction in
        # this fixture-owned database, then prove rollback restores their exact
        # original catalog rows before this case starts its source writers.
        signatures = (
            "caseops_refresh_task_queue_group(text,text,text)",
            "caseops_finalize_task_queue()",
            "caseops_task_queue_insert()",
            "caseops_task_queue_update()",
            "caseops_task_queue_delete()",
            "caseops_task_queue_truncate()",
        )
        catalog = text(
            "SELECT p.oid,p.proname,pg_get_functiondef(p.oid),p.proacl::text "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname LIKE 'caseops%task_queue%' "
            "ORDER BY p.oid"
        )
        before = connection.execute(catalog).all()
        assert len(before) == 6
        trigger_catalog = text(
            "SELECT t.oid,t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t "
            "JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND t.tgname LIKE 'trg_task_queue_%' ORDER BY t.oid"
        )
        before_triggers = connection.execute(trigger_catalog).all()
        assert len(before_triggers) == 5
        try:
            for signature in signatures:
                connection.exec_driver_sql(f"DROP FUNCTION public.{signature} CASCADE")
            install(connection)
            installed = connection.execute(catalog).all()
            assert len(installed) == 6
            assert id(connection.connection.dbapi_connection) == identity
        finally:
            connection.rollback()
        after = connection.execute(catalog).all()
        assert after == before
        after_triggers = connection.execute(trigger_catalog).all()
        assert after_triggers == before_triggers
    (tmp_path / "queue-ddl-same-connection-transport.json").write_text(
        json.dumps(
            {
                "originalDefaultDispatch": baseline,
                "sameDbapiConnectionAfterRollbackAndInstall": True,
                "literalModuloResult": result,
                "installedFunctions": len(installed),
                "originalFunctionCatalogRestoredAfterRollback": after == before,
                "originalTriggerCatalogRestoredAfterRollback": after_triggers == before_triggers,
            },
            indent=2,
        )
        + "\n"
    )


def test_deferred_finalizer_does_not_lock_group_before_last_source_write(
    isolated_postgres_client,
    tmp_path,
):
    assert_queue_function_owner_catalog(tmp_path)
    source_lock_cycle(isolated_postgres_client, force_immediate=False)


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"])
def test_commit_gate_wait_refreshes_current_snapshot_or_keeps_standard_serialization_failure(
    isolated_postgres_client,
    isolation,
):
    from time import sleep

    from sqlalchemy.orm import Session

    from caseops_api.db.models import HearingReminder, NotificationDeliveryIntent
    from caseops_api.db.session import get_engine

    case = setup(isolated_postgres_client)
    one = task(isolated_postgres_client, case["owner"], case["matter"], None)
    two = task(isolated_postgres_client, case["owner"], case["matter"], None)
    base = get_engine()
    ready = threading.Event()
    worker_pid = {}

    def outbox(connection):
        return [
            connection.execute(select(model.__table__).order_by(model.id)).all()
            for model in (HearingReminder, NotificationDeliveryIntent)
        ]

    with base.connect() as connection:
        before_outbox = outbox(connection)

    def second_writer():
        with Session(base.execution_options(isolation_level=isolation)) as session:
            try:
                session.execute(text("SET LOCAL statement_timeout='5s'"))
                session.execute(text("SET LOCAL lock_timeout='5s'"))
                worker_pid["pid"] = session.scalar(text("SELECT pg_backend_pid()"))
                session.get(MatterTask, two["id"]).title = "B source snapshot"
                session.flush()
                ready.set()
                session.commit()
                return {"committed": True, "sqlstate": None}
            except Exception as error:
                session.rollback()
                state = getattr(getattr(error, "orig", None), "sqlstate", None)
                if state != "40001":
                    raise
                return {"committed": False, "sqlstate": state}

    with Session(base.execution_options(isolation_level=isolation)) as first:
        first.execute(text("SET LOCAL statement_timeout='5s'"))
        first.execute(text("SET LOCAL lock_timeout='5s'"))
        holder_pid = first.scalar(text("SELECT pg_backend_pid()"))
        first.get(MatterTask, one["id"]).title = "A source snapshot"
        first.flush()
        # All source/FK/audit writes in this transaction are finished. Holding
        # the exact real finalizer gate here creates a directed native wait.
        first.execute(text("SELECT pg_advisory_xact_lock(1145393713,0)"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(second_writer)
            try:
                wait_event(ready, peer=future)
                snapshots, deadline = [], monotonic() + 3
                with base.connect() as observer:
                    for _ in range(150):
                        blockers = observer.scalar(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pid["pid"]}
                        )
                        snapshots.append(blockers)
                        if holder_pid in blockers or monotonic() >= deadline:
                            break
                        if future.done():
                            future.result()
                            raise AssertionError("Writer returned before the directed gate wait")
                        sleep(0.02)
                assert snapshots and holder_pid in snapshots[-1]
                assert not future.done()
                first.commit()
            finally:
                first.rollback()
            second = future.result(timeout=7)
    if isolation == "READ COMMITTED":
        assert second == {"committed": True, "sqlstate": None}
    else:
        assert second in (
            {"committed": True, "sqlstate": None},
            {"committed": False, "sqlstate": "40001"},
        )
    with get_session_factory()() as session:
        actual = {
            row.id: row.title
            for row in session.scalars(
                select(MatterTask).where(MatterTask.id.in_([one["id"], two["id"]]))
            )
        }
        assert actual[one["id"]] == "A source snapshot"
        assert actual[two["id"]] == ("B source snapshot" if second["committed"] else two["title"])
        page = queue.list_matter_work_queue(
            session, context=context_for(session, case["actor"]), ownership="unassigned"
        )
        assert {row.id: row.title for row in page.items} == actual
        assert session.scalar(select(MatterTaskQueueDirty.transaction_id).limit(1)) is None
        assert outbox(session) == before_outbox
