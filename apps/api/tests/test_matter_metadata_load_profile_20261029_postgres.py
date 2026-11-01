"""Bound metadata hydration in its first transaction, not just after commit."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import Table, event, inspect, select
from sqlalchemy.orm import RelationshipProperty, Session, selectinload
from sqlalchemy.sql import Select, visitors

from caseops_api.db.models import (
    Matter,
    MatterAttachment,
    MatterCourtOrder,
    MatterNote,
    MatterTag,
    MatterTagAssignment,
)
from caseops_api.schemas.matters import MatterUpdateRequest
from caseops_api.services import matters
from tests.test_matter_response_reload_20261029_postgres import (
    _assert_record,
    _stored_values,
)
from tests.test_matter_response_reload_20261029_postgres import (
    reload_seed as _canonical_reload_seed,  # noqa: F401
)
from tests.test_postgres_validation import (
    _ensure_migrations as _canonical_migrations,  # noqa: F401
)
from tests.test_postgres_validation import (
    _ip_race_context,
)

pytestmark = pytest.mark.postgres
_CAPACITY = 128
_SQL_BYTES = 64 * 1024
_UNRELATED = {
    "tasks",
    "notes",
    "hearings",
    "activity_events",
    "cause_list_entries",
    "court_sync_runs",
    "court_sync_jobs",
    "attachments",
    "time_entries",
    "invoices",
}
_WORKSPACE = _UNRELATED | {"tag_assignments", "court_orders"}
_UNRELATED_TABLES = {
    inspect(Matter).relationships[name].mapper.local_table.name for name in _UNRELATED
} | {
    inspect(Matter).relationships[parent].mapper.relationships[child].mapper.local_table.name
    for parent, child in (
        ("attachments", "chunks"),
        ("time_entries", "invoice_line_item"),
        ("invoices", "line_items"),
        ("invoices", "payment_attempts"),
    )
}
_RECORD_TABLES = Counter(
    {
        ("matters",): 1,
        ("matter_tag_assignments", "matter_tags"): 1,
        ("matter_court_orders",): 1,
    }
)


@pytest.fixture
def profile_seed(request, pg_engine):
    # Resolve the imported fixture alias without shadowing that import in an argument.
    seed = dict(request.getfixturevalue("_canonical_reload_seed"))
    content = b"Metadata profile fixture"
    with Session(pg_engine, expire_on_commit=False) as session:
        attachment = MatterAttachment(
            matter_id=seed["matter_id"],
            uploaded_by_membership_id=seed["actor_id"],
            original_filename="profile.txt",
            storage_key=f"profile/{uuid4()}",
            content_type="text/plain",
            size_bytes=len(content),
            sha256_hex=sha256(content).hexdigest(),
            document_type="other",
        )
        session.add(attachment)
        session.commit()
        seed["attachment_id"] = attachment.id
    return seed


def _fresh_separate_writer(engine, seed):
    with Session(engine, expire_on_commit=False) as writer:
        context = _ip_race_context(
            writer,
            company_id=seed["company_id"],
            membership_id=seed["actor_id"],
        )
        row = writer.get(Matter, seed["matter_id"])
        assert row is not None
        matters.update_matter(
            writer,
            context=context,
            matter_id=seed["matter_id"],
            commit=False,
            payload=MatterUpdateRequest(
                client_name=None,
                description="Fresh profile description",
                expected_updated_at=row.updated_at,
            ),
        )
        tag = writer.get(MatterTag, seed["tag_id"])
        order = writer.get(MatterCourtOrder, seed["order_id"])
        assert tag is not None and tag.company_id == seed["company_id"]
        assert order is not None and order.matter_id == seed["matter_id"]
        tag.name = "Beta profile"
        order.stay_status = "none"
        order.is_interim_order = False
        order.order_kind = "daily_order"
        added = MatterTag(
            company_id=seed["company_id"],
            name="Aaron profile",
            slug="profile-aaron",
            color_key="blue",
            created_by_membership_id=seed["actor_id"],
        )
        writer.add(added)
        writer.flush()
        writer.add(
            MatterTagAssignment(
                company_id=seed["company_id"],
                matter_id=seed["matter_id"],
                tag_id=added.id,
                created_by_membership_id=seed["actor_id"],
                source="manual",
            )
        )
        writer.commit()
    return _stored_values(engine, seed)


def _summary(receipt):
    events = receipt["events"]
    selects = [row for row in events if row["kind"] == "sql" and row["select"]]
    product = [row for row in selects if row["transaction"] == 1 and row["phase"] == "product"]
    graph, forbidden = [], []
    for row in product:
        index = row["orm_event"]
        if index is None:
            continue
        orm = events[index]
        path = orm["path"]
        if path and path[0] in _UNRELATED:
            forbidden.append(path)
        if (orm["matter_root"] and not row["locking"]) or (path and path[0] in _WORKSPACE):
            graph.append(row["index"])
    return {
        "first_transaction_product_selects": len(product),
        "first_transaction_graph_selects": len(graph),
        "graph_sql_events": graph,
        "unrelated_paths": forbidden,
        "unrelated_from_roots": [
            row["index"] for row in product if _UNRELATED_TABLES.intersection(row["tables"])
        ],
        "later_transaction_selects": sum(row["transaction"] > 1 for row in selects),
        "unpaired_orm_selects": sum(
            row["kind"] == "orm" and row["sql_event"] is None for row in events
        ),
        "unpaired_sql_selects": sum(row["orm_event"] is None for row in selects),
    }


@contextmanager
def _inventory(session, engine, seed, tmp_path, record_property):
    receipt = {
        "capacity": _CAPACITY,
        "seen": 0,
        "overflow": False,
        "capture_error": False,
        "phase": "prepare",
        "transactions": 0,
        "commits": 0,
        "rollbacks": 0,
        "events": [],
        "capture_finished": False,
    }
    owned, pending = [], []

    def record(kind, **values):
        receipt["seen"] += 1
        if len(receipt["events"]) == _CAPACITY:
            receipt["overflow"] = True
            return None
        row = {"index": len(receipt["events"]), "kind": kind, "phase": receipt["phase"], **values}
        receipt["events"].append(row)
        return row

    def began(_session, transaction, connection):
        if transaction.parent is not None:
            return
        receipt["transactions"] += 1
        if len(owned) < _CAPACITY:
            owned.append((connection, receipt["transactions"]))
        else:
            receipt["overflow"] = True
        record("begin", transaction=receipt["transactions"])

    def committed(_session):
        receipt["commits"] += 1
        record("commit", transaction=receipt["transactions"])

    def rolled_back(_session):
        receipt["rollbacks"] += 1
        record("rollback", transaction=receipt["transactions"])

    def orm_select(state):
        if not state.is_select:
            return
        try:
            path = (
                [
                    part.key
                    for part in state.loader_strategy_path.path
                    if isinstance(part, RelationshipProperty)
                ]
                if state.is_relationship_load
                else []
            )
            row = record(
                "orm",
                transaction=None,
                sql_event=None,
                path=path,
                matter_root=not state.is_relationship_load
                and any(item.get("expr") is Matter for item in state.statement.column_descriptions),
            )
            if row is not None:
                pending.append(row)
        except Exception as error:
            receipt["capture_error"] = True
            record("capture_error", callback="orm", error_type=type(error).__name__)

    def sql_before(connection, _cursor, statement, parameters, context, _many):
        transaction = next((number for item, number in reversed(owned) if item is connection), None)
        if transaction is None:
            return
        try:
            compiled = context.compiled
            expression = compiled.statement if compiled is not None else None
            is_select = statement.lstrip().upper().startswith(("SELECT", "WITH"))
            tables = (
                sorted(
                    {
                        node.name
                        for clause in expression.get_final_froms()
                        for node in visitors.iterate(clause)
                        if isinstance(node, Table)
                    }
                )
                if isinstance(expression, Select)
                else []
            )
            orm = next((row for row in reversed(pending) if row["sql_event"] is None), None)
            orm = orm if is_select else None
            encoded = statement.encode("utf-8")
            if len(encoded) > _SQL_BYTES:
                receipt["overflow"] = True
            row = record(
                "sql",
                transaction=transaction,
                select=is_select,
                tables=tables,
                locking=isinstance(expression, Select) and expression._for_update_arg is not None,
                sql=statement if len(encoded) <= _SQL_BYTES else None,
                sql_sha256=sha256(encoded).hexdigest(),
                sql_bytes=len(encoded),
                orm_event=orm["index"] if orm is not None else None,
                exact_scope=isinstance(parameters, Mapping)
                and parameters.get("id_1") == seed["matter_id"]
                and parameters.get("company_id_1") == seed["company_id"],
            )
            if orm is not None and row is not None:
                # Stamp from the real connection begin, including autobegin after commit.
                orm["transaction"] = transaction
                orm["sql_event"] = row["index"]
        except Exception as error:
            receipt["capture_error"] = True
            record("capture_error", callback="sql", error_type=type(error).__name__)

    hooks = [
        (session, "after_begin", began),
        (session, "after_commit", committed),
        (session, "after_rollback", rolled_back),
        (session, "do_orm_execute", orm_select),
        (engine, "before_cursor_execute", sql_before),
    ]
    for target, name, callback in hooks:
        event.listen(target, name, callback)
    try:
        yield receipt
    finally:
        for target, name, callback in reversed(hooks):
            event.remove(target, name, callback)
        receipt["capture_finished"] = True
        receipt["summary"] = _summary(receipt)
        path = tmp_path / "metadata-first-transaction-inventory.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
        record_property("matter_metadata_first_transaction_inventory", str(path))


def _assert_profile(receipt, mode):
    assert receipt["capture_finished"]
    assert not receipt["overflow"] and not receipt["capture_error"], receipt
    assert receipt["seen"] == len(receipt["events"]) <= _CAPACITY
    summary = receipt["summary"]
    assert summary["unpaired_orm_selects"] == summary["unpaired_sql_selects"] == 0, summary
    assert not summary["unrelated_paths"], (
        "Unused workspace relationships loaded before the first commit",
        summary,
    )
    assert not summary["unrelated_from_roots"], summary
    rows = [receipt["events"][index] for index in summary["graph_sql_events"]]
    assert len(rows) == 3, summary
    assert Counter(tuple(row["tables"]) for row in rows) == _RECORD_TABLES, rows
    paths = Counter(
        tuple(receipt["events"][row["orm_event"]]["path"])
        for row in rows
        if receipt["events"][row["orm_event"]]["path"]
    )
    assert paths == Counter({("tag_assignments",): 1, ("court_orders",): 1}), paths
    root = next(row for row in rows if row["tables"] == ["matters"])
    assert root["exact_scope"]
    assert "matters.id =" in root["sql"] and "matters.company_id =" in root["sql"]
    assert all(row["transaction"] == 1 and row["phase"] == "product" for row in rows)
    assert receipt["commits"] == (1 if mode == "commit" else 0)
    assert receipt["rollbacks"] == 0
    assert receipt["transactions"] == (2 if mode == "commit" else 1)
    if mode == "commit":
        assert summary["later_transaction_selects"] > 0
    else:
        assert summary["later_transaction_selects"] == 0


def _database_scalars(session, seed, fields):
    return dict(
        session.execute(
            select(*(getattr(Matter, name) for name in sorted(fields))).where(
                Matter.id == seed["matter_id"], Matter.company_id == seed["company_id"]
            )
        )
        .mappings()
        .one()
    )


def _workspace(session, seed):
    return matters.get_matter_workspace(
        session,
        context=_ip_race_context(
            session,
            company_id=seed["company_id"],
            membership_id=seed["actor_id"],
        ),
        matter_id=seed["matter_id"],
    )


@pytest.mark.parametrize(
    "mode,autoflush",
    [
        pytest.param("commit", False, id="commit-autoflush-off"),
        pytest.param("commit", True, id="commit-autoflush-on"),
        pytest.param("defer", False, id="defer-autoflush-off"),
        pytest.param("defer", True, id="defer-autoflush-on"),
        pytest.param("noop", False, id="noop-autoflush-off"),
        pytest.param("noop", True, id="noop-autoflush-on"),
    ],
)
def test_metadata_first_transaction_loads_only_record_graph(
    pg_engine,
    profile_seed,
    tmp_path,
    record_property,
    mode,
    autoflush,
):
    seed = profile_seed
    pending_note = None
    pending_note_id = None
    with Session(pg_engine, autoflush=autoflush, expire_on_commit=False) as session:
        with _inventory(session, pg_engine, seed, tmp_path, record_property) as receipt:
            context = _ip_race_context(
                session,
                company_id=seed["company_id"],
                membership_id=seed["actor_id"],
            )
            row = session.scalar(
                select(Matter)
                .options(
                    selectinload(Matter.tag_assignments).joinedload(MatterTagAssignment.tag),
                    selectinload(Matter.court_orders),
                )
                .where(Matter.id == seed["matter_id"], Matter.company_id == seed["company_id"])
            )
            assert row is not None
            old_tag = next(
                item.tag for item in row.tag_assignments if item.tag_id == seed["tag_id"]
            )
            old_order = row.court_orders[0]
            assert old_tag.name == "Zulu" and old_order.stay_status == "granted"
            first_transaction = session.get_transaction()
            assert first_transaction is not None
            fresh = _fresh_separate_writer(pg_engine, seed)
            if mode != "commit":
                pending_note_id = str(uuid4())
                pending_note = MatterNote(
                    id=pending_note_id,
                    matter_id=seed["matter_id"],
                    author_membership_id=seed["actor_id"],
                    body="Caller profile note",
                )
                session.add(pending_note)
            fields = {} if mode == "noop" else {"title": "Profile metadata result"}
            receipt["phase"] = "product"
            response = matters.update_matter(
                session,
                context=context,
                matter_id=seed["matter_id"],
                commit=mode != "defer",
                payload=MatterUpdateRequest(
                    expected_updated_at=fresh["scalars"]["updated_at"],
                    **fields,
                ),
            )
        # The complete bounded receipt is already on disk before any load-budget assertion.
        _assert_profile(receipt, mode)
        assert old_tag.name == "Beta profile" and old_order.stay_status == "none"
        scalars = _database_scalars(session, seed, fresh["scalars"])
        _assert_record(
            response, {"scalars": scalars, "tags": fresh["tags"]}, has_stay=False, has_interim=False
        )
        unchanged = set(scalars) - {"title", "updated_at"}
        assert {key: scalars[key] for key in unchanged} == {
            key: fresh["scalars"][key] for key in unchanged
        }
        assert scalars["title"] == (
            fresh["scalars"]["title"] if mode == "noop" else "Profile metadata result"
        )
        if mode == "noop":
            assert scalars == fresh["scalars"]
        if pending_note is not None:
            assert session.get_transaction() is first_transaction
            # Caller-owned flush follows capture; no-op is not required to flush pending work.
            session.flush()
        workspace = _workspace(session, seed)
        assert workspace.matter.model_dump() == response.model_dump()
        assert [item.id for item in workspace.attachments] == [seed["attachment_id"]]
        note_bodies = {note.body for note in workspace.notes}
        assert "Unrelated note must not be reloaded after commit." in note_bodies
        if pending_note is not None:
            assert "Caller profile note" in note_bodies
        with Session(pg_engine, expire_on_commit=False) as observer:
            observed = _workspace(observer, seed)
            if pending_note is None:
                assert workspace.model_dump() == observed.model_dump()
            else:
                _assert_record(observed.matter, fresh, has_stay=False, has_interim=False)
                assert observer.get(MatterNote, pending_note_id) is None
        if pending_note is not None:
            session.rollback()
            restored = _workspace(session, seed)
            _assert_record(restored.matter, fresh, has_stay=False, has_interim=False)
            with Session(pg_engine, expire_on_commit=False) as observer:
                assert observer.get(MatterNote, pending_note_id) is None
                assert restored.model_dump() == _workspace(observer, seed).model_dump()
