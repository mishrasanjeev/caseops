"""Named 0007→0008 fencing of every paused reflected old-column writer.

Only after the exact migration→writer PostgreSQL edge is observed do we release
and join both Futures, then finish the captured current-head upgrade. No later
concurrent-index migration runs behind the intentionally retained old snapshot.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine

from alembic import command
from caseops_api.db.session import get_engine
from tests.test_counsel_page_migration_20261027 import _catalog, _rows
from tests.test_counsel_read_pages_20261027_postgres import entered_or_exception
from tests.test_deferred_native_projections_20261027_postgres import observed_edge
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as forbid_unadmitted_network,
)
from tests.test_matter_readthrough_page_migration_20261028 import (
    NEW_TABLES,
    OUTBOXES,
    identity,
    require_physical,
    require_reads,
    seed_old,
)
from tests.test_matter_task_queue_migration_20261028 import _artifact
from tests.test_platform_console_migration import fresh_engine, migration_config

pytestmark = pytest.mark.postgres
PREVIOUS = "20261027_0007"
NAMED_HEAD = "20261027_0008"
SOURCE_FAMILIES = (
    "recommendations",
    "recommendation_options",
    "recommendation_decisions",
    "hearing_packs",
    "hearing_pack_items",
)
FENCED_TABLES = (*SOURCE_FAMILIES, "matters", "matter_hearings")
FENCE_SQL = (
    "LOCK TABLE "
    + ",".join("public." + name for name in sorted(FENCED_TABLES))
    + " IN SHARE ROW EXCLUSIVE MODE"
)
FUNCTIONS = {
    "caseops_readthrough_rebuild_v1",
    "caseops_readthrough_mark_v1",
    "caseops_readthrough_finalize_v1",
    "caseops_readthrough_truncate_v1",
}
TRIGGERS = (
    {(name, "readthrough_source_v1") for name in FENCED_TABLES}
    | {(name, "readthrough_truncate_v1") for name in (*FENCED_TABLES, "companies")}
    | {("matter_readthrough_dirty", "readthrough_finalize_v1")}
)
INDEXES = {
    "pk_matter_recommendation_read_pages",
    "pk_matter_option_read_pages",
    "pk_matter_decision_read_pages",
    "pk_matter_hearing_pack_read_pages",
    "pk_matter_pack_item_read_pages",
    "matter_readthrough_dirty_pkey",
} | {
    "ix_matter_recommendation_read_pages_chron_seek",
    "ix_matter_recommendation_read_pages_id_seek",
    "ix_matter_option_read_pages_rank_seek",
    "ix_matter_decision_read_pages_chron_seek",
    "ix_matter_hearing_pack_read_pages_latest_seek",
    "ix_matter_hearing_pack_read_pages_id_seek",
    "ix_matter_pack_item_read_pages_rank_seek",
}


def preserved_catalog(before, after):
    """Every old catalog value survives; only literal 0008 objects are added."""
    assert set(after["tables"]) == set(before["tables"]) | NEW_TABLES
    for name, definition in before["tables"].items():
        assert after["tables"][name] == definition
    assert [row for row in after["indexes"] if row[0] not in NEW_TABLES] == before["indexes"]
    assert {row[1] for row in after["indexes"] if row[0] in NEW_TABLES} == INDEXES
    assert [row for row in after["triggers"] if (row[0], row[1]) not in TRIGGERS] == before[
        "triggers"
    ]
    assert {
        (row[0], row[1]) for row in after["triggers"] if (row[0], row[1]) in TRIGGERS
    } == TRIGGERS
    assert [row for row in after["functions"] if row[0] not in FUNCTIONS] == before["functions"]
    assert {row[0] for row in after["functions"] if row[0] in FUNCTIONS} == FUNCTIONS
    assert after["sequences"] == before["sequences"]


def retained_originals(before, after, source, new_id):
    """Retain raw JSON text and every old column; exclude only the new row."""
    retained = {
        name: [row for row in rows if name != source or row._mapping["id"] != new_id]
        for name, rows in after.items()
    }
    assert retained == before
    inserted = [row for row in after[source] if row._mapping["id"] == new_id]
    assert len(inserted) == 1 and len(after[source]) == len(before[source]) + 1


@pytest.mark.parametrize("source", SOURCE_FAMILIES)
def test_named_0008_waits_for_acknowledged_historical_source_writer_before_current_head(
    source, tmp_path, monkeypatch
):
    assert source in SOURCE_FAMILIES
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        captured_head = ScriptDirectory.from_config(config).get_current_head()
        assert captured_head is not None
        command.upgrade(config, PREVIOUS)
        scope, old_tables, rows, _ = seed_old(engine)
        original_names = sorted(set(inspect(engine).get_table_names()) - {"alembic_version"})
        before = _rows(engine, original_names)
        outboxes = _rows(engine, OUTBOXES)
        before_catalog = _catalog(engine)
        assert all(outboxes.values()) and NEW_TABLES.isdisjoint(before_catalog["tables"])
        assert before["predictive_outcome_classifications"]
        _artifact(tmp_path / "0007-retained-all-original-rows.json", before)
        _artifact(tmp_path / "0007-complete-catalog.json", before_catalog)
        table = old_tables[source]  # Reflected at 0007; no new ORM column writer.
        new_id = identity(70000 + SOURCE_FAMILIES.index(source))
        new = {**rows[source][min(rows[source])], "id": new_id}
        writer_entered, release_writer, fence_entered = Event(), Event(), Event()
        state = {"source": source, "newId": new_id, "fenceStatements": []}
        acknowledgement = {}
        joined, failures, lock_facts = {}, [], []
        serving_engine = get_engine()
        assert serving_engine.url == engine.url

        def old_writer():
            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL lock_timeout='5s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
                pid = connection.scalar(text("SELECT pg_backend_pid()"))
                statement = table.insert().values(**new).returning(table.c.id)
                acknowledged_id = connection.execute(statement).scalar_one()
                acknowledgement.update(pid=pid, source=source, id=acknowledged_id)
                assert acknowledged_id == new_id
                writer_entered.set()
                if not release_writer.wait(20):
                    raise AssertionError("Historical acknowledged source writer was not released")
            return {**acknowledgement, "committed": True}

        def before_sql(connection, cursor, sql, _params, _context, _many):
            if connection.engine.url.database != engine.url.database or sql != FENCE_SQL:
                return
            assert not fence_entered.is_set(), "Named migration attempted its source fence twice"
            state["migrationPid"] = cursor.connection.info.backend_pid
            state["fenceStatements"].append(sql)
            fence_entered.set()

        def after_sql(connection, _cursor, sql, _params, _context, _many):
            if connection.engine.url.database == engine.url.database and sql == FENCE_SQL:
                state["fenceAcquiredAfterWriterRelease"] = release_writer.is_set()

        event.listen(Engine, "before_cursor_execute", before_sql)
        event.listen(Engine, "after_cursor_execute", after_sql)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {"writer": pool.submit(old_writer)}
                try:
                    entered_or_exception(writer_entered, futures["writer"])
                    assert acknowledgement == {
                        "pid": acknowledgement["pid"],
                        "source": source,
                        "id": new_id,
                    }
                    assert type(acknowledgement["pid"]) is int and acknowledgement["pid"] > 0
                    _artifact(
                        tmp_path / "old-source-insert-ack-before-commit.json", acknowledgement
                    )
                    futures["migration"] = pool.submit(command.upgrade, config, NAMED_HEAD)
                    entered_or_exception(fence_entered, futures["migration"])
                    waiter, holder = state["migrationPid"], acknowledgement["pid"]
                    assert type(waiter) is int and waiter > 0 and waiter != holder
                    # Reviewed 3s/100-snapshot observer checks its final existing
                    # snapshot and surfaces a completed Future's exception.
                    observed_edge(
                        tmp_path, "named-0008-source", waiter, holder, futures["migration"]
                    )
                    with engine.connect() as observer:
                        locks = (
                            observer.execute(
                                text(
                                    "SELECT pid,relation::regclass::text AS relation,mode,granted,"
                                    "pg_blocking_pids(pid) AS blockers FROM pg_locks "
                                    "WHERE locktype='relation' AND pid IN (:waiter,:holder) "
                                    "AND relation=to_regclass(:relation) ORDER BY pid,mode,granted"
                                ),
                                {
                                    "waiter": waiter,
                                    "holder": holder,
                                    "relation": "public." + source,
                                },
                            )
                            .mappings()
                            .all()
                        )
                        lock_facts = [dict(row) for row in locks]
                        assert any(
                            row["pid"] == holder
                            and row["mode"] == "RowExclusiveLock"
                            and row["granted"]
                            for row in locks
                        )
                        assert any(
                            row["pid"] == waiter
                            and row["mode"] == "ShareRowExclusiveLock"
                            and not row["granted"]
                            and holder in row["blockers"]
                            for row in locks
                        )
                        version = observer.scalar(text("SELECT version_num FROM alembic_version"))
                        assert version == PREVIOUS
                        added = observer.scalars(
                            text(
                                "SELECT relname FROM pg_class "
                                "WHERE relnamespace='public'::regnamespace "
                                "AND relname IN (SELECT unnest(CAST(:names AS text[])))"
                            ),
                            {"names": sorted(NEW_TABLES)},
                        ).all()
                        assert added == []
                    assert not futures["migration"].done() and not futures["writer"].done()
                    assert not release_writer.is_set()
                except BaseException as error:
                    failures.append(error)
                finally:
                    # Release before serializing evidence or joining, including
                    # failures at the observer/worker/setup boundaries.
                    release_writer.set()
                    for role, pending in futures.items():
                        try:
                            joined[role] = {"completed": True, "result": pending.result(timeout=10)}
                        except BaseException as error:
                            joined[role] = {
                                "completed": pending.done(),
                                "failureClass": type(error).__name__,
                            }
                            if all(error is not previous for previous in failures):
                                failures.append(error)
                    _artifact(
                        tmp_path / "joined-historical-writer-and-named-migration.json", joined
                    )
        finally:
            release_writer.set()
            event.remove(Engine, "before_cursor_execute", before_sql)
            event.remove(Engine, "after_cursor_execute", after_sql)
        _artifact(tmp_path / "exact-historical-source-lock-modes.json", lock_facts)
        if failures:
            raise BaseExceptionGroup("Historical source fence or joined worker failed", failures)
        assert joined["writer"]["result"] == {**acknowledgement, "committed": True}
        assert state["fenceStatements"] == [FENCE_SQL]
        assert state["fenceAcquiredAfterWriterRelease"] is True
        with engine.connect() as connection:
            version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == NAMED_HEAD
        after = _rows(engine, original_names)
        retained_originals(before, after, source, new_id)
        actual_outboxes = _rows(engine, OUTBOXES)
        assert actual_outboxes == outboxes
        rows[source][new_id] = new
        require_physical(engine, scope, rows)
        read_observations = require_reads(engine, scope, rows)
        named_catalog = _catalog(engine)
        preserved_catalog(before_catalog, named_catalog)
        _artifact(tmp_path / "0008-all-original-columns-after-writer-and-backfill.json", after)
        _artifact(tmp_path / "0008-complete-catalog-after-joined-writer.json", named_catalog)
        # Current-head work starts only after both historical Futures returned.
        command.upgrade(config, captured_head)
        current_rows, current_catalog = _rows(engine, original_names), _catalog(engine)
        assert current_rows == after
        actual_outboxes = _rows(engine, OUTBOXES)
        assert actual_outboxes == outboxes
        require_physical(engine, scope, rows)
        require_reads(engine, scope, rows)
        command.upgrade(config, captured_head)
        repeat_rows, repeat_catalog = _rows(engine, original_names), _catalog(engine)
        assert repeat_rows == current_rows and repeat_catalog == current_catalog
        with engine.connect() as connection:
            version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == captured_head
        _artifact(tmp_path / "captured-current-head-complete-catalog.json", current_catalog)
        _artifact(tmp_path / "captured-current-head-retained-rows.json", current_rows)
        _artifact(
            tmp_path / "historical-source-fence-complete.json",
            {
                **state,
                "capturedHead": captured_head,
                "namedFence": NAMED_HEAD,
                "oldWriter": joined["writer"]["result"],
                "readObservations": read_observations,
                "originalRawRowsUnchanged": True,
                "outboxesUnchanged": True,
                "currentHeadUpgradeAfterBothFuturesJoined": True,
            },
        )
