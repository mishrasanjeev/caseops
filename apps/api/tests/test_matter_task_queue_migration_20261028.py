"""Named 0005 -> 0006 retained-source journey on both supported dialects.

This is separate from the original 408-case projection inventory. It does not
claim production DB-role acceptance, a backup restoration, or a later head.
"""

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.models import Company, CompanyMembership, Matter, User
from caseops_api.services import matter_work_queue as queue
from caseops_api.services.session_context import SessionContext
from tests.test_counsel_page_migration_20261027 import _catalog, _rows, _seed
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as forbid_unadmitted_network,
)
from tests.test_platform_console_migration import fresh_engine, migration_config
from tests.test_postgres_validation import _seed_matter, _seed_membership

PREVIOUS = "20261027_0005"
NAMED_HEAD = "20261027_0006"
NEW_TABLES = {
    "matter_task_queue_groups",
    "matter_task_queue_pages",
    "matter_task_queue_dirty",
}
STAMP = datetime(2026, 10, 28, 3, 4, 5, 123456, tzinfo=UTC)
DIALECTS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
FIELDS = ("id", "title", "status", "priority", "due_on", "created_at", "updated_at")


def _json_value(value):
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (Row, list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, (bytes, memoryview)):
        return {"bytesHex": bytes(value).hex()}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError("Unexpected retained scalar type")


def _artifact(path, value):
    # Convert complete Rows, never their diagnostic repr (which can truncate a
    # wide value). Raw JSON storage text remains an exact string, not decoded.
    data = (json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True) + "\n").encode()
    assert len(data) <= 16 * 1024**2
    with path.open("xb") as output:
        written = output.write(data)
    assert written == len(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _reflected(engine, name):
    return Table(name, MetaData(), autoload_with=engine)


def _utc(value):
    # Only this fixture's known UTC persistence fields receive SQLite's offset.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _order(row):
    return (row["due_on"] is None, row["due_on"] or date.max, row["created_at"], row["id"])


def _seed_old_tasks(engine):
    scope, _ = _seed(engine, count=1)
    with Session(engine) as session:
        actor = session.get(CompanyMembership, scope["member"])
        actor.role = "owner"
        peer = _seed_membership(session, scope["company"])
        other_matter = _seed_matter(session, scope["company"])
        session.commit()
    team_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            _reflected(engine, "teams")
            .insert()
            .values(
                id=team_id,
                company_id=scope["company"],
                name="Migration team",
                slug="migration-team",
                kind="team",
                is_active=True,
                created_at=STAMP,
                updated_at=STAMP,
            )
        )
        for member in (scope["member"], peer):
            connection.execute(
                _reflected(engine, "team_memberships")
                .insert()
                .values(
                    id=str(uuid4()),
                    team_id=team_id,
                    membership_id=member,
                    is_lead=False,
                    created_at=STAMP,
                )
            )
    source = _reflected(engine, "matter_tasks")
    # Retain this actual historical Table for all post-upgrade compatibility
    # writes. No projection columns, defaults, or current ORM writer are used.
    rows = []
    for group, owner in enumerate((None, scope["member"], peer)):
        for number in reversed(range(27)):
            identity = str(UUID(int=0x600000 + group * 100 + number))
            rows.append(
                dict(
                    id=identity,
                    company_id=scope["company"],
                    matter_id=scope["matter"] if group < 2 else other_matter,
                    ip_docket_id=None,
                    created_by_membership_id=scope["member"],
                    owner_membership_id=owner,
                    title=f"Retained group {group} task {number}",
                    description=("Original wide source 🧾\n" * 70000)
                    if group == number == 0
                    else None,
                    due_on=None
                    if number % 4 == 0
                    else date(2027, 1, 1) + timedelta(days=number % 7),
                    status=("todo", "in_progress", "blocked")[number % 3],
                    priority=("low", "medium", "high", "urgent")[number % 4],
                    completed_at=None,
                    cancelled_by_matter_disposal=False,
                    neutralized_by_ip_lifecycle_event_id=None,
                    neutralized_by_ip_lifecycle_version=None,
                    neutralized_at=None,
                    created_at=STAMP + timedelta(microseconds=number % 3),
                    updated_at=STAMP,
                )
            )
    # A valid nullable legacy tenant scope remains stored, but never becomes a
    # tenant queue item. A terminal sibling remains stored and excluded too.
    for number, status in enumerate(("todo", "done")):
        row = dict(
            rows[0],
            id=str(UUID(int=0x610000 + number)),
            description=None,
            company_id=None if number == 0 else scope["company"],
            status=status,
        )
        rows.append(row)
    if engine.dialect.name == "sqlite":
        rows[0]["title"] = "Retained SQLite title 🧾" * 200
    with engine.begin() as connection:
        # Reverse/tied fixtures cannot derive the expected ordering from insert order.
        connection.execute(source.insert(), rows)
    assert set(rows[0]) == set(source.c.keys())
    assert len(rows[26]["description"].encode()) > 1024**2
    return scope, peer, source, {row["id"]: row for row in rows}


def _expected_rows(rows):
    return [
        row
        for row in rows.values()
        if row["company_id"] is not None and row["status"] in ("todo", "in_progress", "blocked")
    ]


def _assert_source_rows(engine, rows):
    with engine.connect() as connection:
        actual = connection.execute(select(_reflected(engine, "matter_tasks"))).mappings().all()
    normalized = {
        row["id"]: {
            key: _utc(value) if isinstance(value, datetime) else value for key, value in row.items()
        }
        for row in actual
    }
    # Covers every historical source column, including the wide private field
    # deliberately absent from both the packed read schema and the response.
    assert normalized == rows


def _assert_physical(engine, rows):
    _assert_source_rows(engine, rows)
    expected = defaultdict(list)
    for row in _expected_rows(rows):
        expected[(row["company_id"], row["matter_id"], row["owner_membership_id"])].append(row)
    with engine.connect() as connection:
        groups = (
            connection.execute(select(_reflected(engine, "matter_task_queue_groups")))
            .mappings()
            .all()
        )
        pages = (
            connection.execute(select(_reflected(engine, "matter_task_queue_pages")))
            .mappings()
            .all()
        )
        dirty = connection.scalar(text("SELECT count(*) FROM matter_task_queue_dirty"))
    assert dirty == 0
    actual_scopes = {
        (g["company_id"], g["matter_id"], None if g["owner_is_null"] else g["owner_key"]): g["id"]
        for g in groups
    }
    # Every fixture scope retains records throughout this journey.
    assert len(actual_scopes) == len(groups) and set(expected) == set(actual_scopes)
    assert all(p["group_id"] in set(actual_scopes.values()) for p in pages)
    for scope, group_id in actual_scopes.items():
        ordered = sorted(expected.get(scope, []), key=_order)
        packed = sorted((p for p in pages if p["group_id"] == group_id), key=lambda p: p["page_no"])
        chunks = [ordered[n : n + 25] for n in range(0, len(ordered), 25)]
        assert [(p["page_no"], p["entry_count"]) for p in packed] == [
            (n, len(c)) for n, c in enumerate(chunks)
        ]
        for page, chunk in zip(packed, chunks, strict=True):
            for slot in range(25):
                for field in FIELDS:
                    actual = page[f"s{slot}_{field}"]
                    if actual is not None and field in ("created_at", "updated_at"):
                        actual = _utc(actual)
                    assert actual == (chunk[slot][field] if slot < len(chunk) else None)
            dated = [row["due_on"] for row in chunk if row["due_on"] is not None]
            assert (page["has_dated"], page["has_undated"]) == (
                bool(dated),
                len(dated) < len(chunk),
            )
            expected_dates = (min(dated), max(dated)) if dated else (None, None)
            assert (page["min_dated"], page["max_dated"]) == expected_dates
            last = chunk[-1]
            assert (
                page["last_null"],
                page["last_date"],
                _utc(page["last_created"]),
                page["last_id"],
            ) == (
                last["due_on"] is None,
                last["due_on"] or date.min,
                last["created_at"],
                last["id"],
            )


def _assert_whole_queue(engine, scope, peer, rows, output):
    output.mkdir()
    calls = 0
    with Session(engine) as session:
        member = session.get(CompanyMembership, scope["member"])
        context = SessionContext(
            company=session.get(Company, scope["company"]),
            membership=member,
            user=session.get(User, member.user_id),
        )
        matters = {row["matter_id"]: session.get(Matter, row["matter_id"]) for row in rows.values()}
        assert all(matter.lifecycle_version == 0 for matter in matters.values())
        for ownership, owner in (("mine", scope["member"]), ("team", peer), ("unassigned", None)):
            for dates in ("all", "dated", "undated"):
                expected = sorted(
                    (
                        row
                        for row in _expected_rows(rows)
                        if row["owner_membership_id"] == owner
                        and (dates == "all" or (row["due_on"] is not None) == (dates == "dated"))
                    ),
                    key=_order,
                )
                actual = []
                cursor = None
                seen = set()
                for _ in range(4):
                    calls += 1
                    page = queue.list_matter_work_queue(
                        session,
                        context=context,
                        ownership=ownership,
                        dates=dates,
                        limit=10,
                        cursor=cursor,
                    )
                    value = page.model_dump()
                    assert {
                        k: v for k, v in value.items() if k not in ("items", "next_cursor")
                    } == dict(
                        scope="matter_tasks",
                        ownership=ownership,
                        dates=dates,
                        due_from=None,
                        due_to=None,
                        sort="due_on_created_at_id",
                        limit=10,
                    )
                    actual.extend(value["items"])
                    cursor = value["next_cursor"]
                    if cursor is None:
                        break
                    assert (
                        isinstance(cursor, str) and 0 < len(cursor) <= 4000 and cursor not in seen
                    )
                    seen.add(cursor)
                else:
                    raise AssertionError("Finite fixture queue did not finish in four pages")
                oracle = []
                for row in expected:
                    matter = matters[row["matter_id"]]
                    oracle.append(
                        {
                            **{field: row[field] for field in FIELDS},
                            "owner_membership_id": row["owner_membership_id"],
                            "matter": dict(
                                id=matter.id,
                                title=matter.title,
                                matter_code=matter.matter_code,
                                status="active",
                                is_active=True,
                                lifecycle_version=0,
                            ),
                        }
                    )
                _artifact(
                    output / f"{ownership}-{dates}.json", {"actual": actual, "oracle": oracle}
                )
                assert actual == oracle
        session.rollback()
    assert calls <= 36
    return {"views": 9, "serviceCalls": calls, "maximumServiceCalls": 36}


@pytest.mark.parametrize("kind", DIALECTS)
def test_seeded_0005_to_named_0006_old_writes_and_retained_downgrade_refusal(
    kind, tmp_path, monkeypatch
):
    assert kind in ("sqlite", "postgres")  # Refuse unsupported targets before DB admission.
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        scripts = ScriptDirectory.from_config(config)
        assert scripts.get_revision(NAMED_HEAD).down_revision == PREVIOUS
        command.upgrade(config, PREVIOUS)
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == PREVIOUS and NEW_TABLES.isdisjoint(inspect(engine).get_table_names())
        scope, peer, old_writer, rows = _seed_old_tasks(engine)
        old_tables = sorted(set(inspect(engine).get_table_names()) - {"alembic_version"})
        before_rows = _rows(engine, old_tables)
        before_catalog = _catalog(engine)
        before_ref = _artifact(tmp_path / "0005-source-audit-outbox-receipts.json", before_rows)
        assert before_ref["bytes"] > 1024**2
        _artifact(tmp_path / "0005-catalog.json", before_catalog)
        assert all(
            before_rows[name]
            for name in (
                "matter_tasks",
                "audit_events",
                "domain_outbox_events",
                "in_app_notifications",
                "notification_delivery_intents",
                "notification_delivery_events",
            )
        )
        command.upgrade(config, NAMED_HEAD)
        after_rows = _rows(engine, old_tables)
        after_ref = _artifact(tmp_path / "0006-preserved-old-rows.json", after_rows)
        after_catalog = _catalog(engine)
        _artifact(tmp_path / "0006-catalog.json", after_catalog)
        assert after_rows == before_rows and after_ref["sha256"] == before_ref["sha256"]
        assert set(after_catalog["tables"]) == set(before_catalog["tables"]) | NEW_TABLES
        assert {
            name: after_catalog["tables"][name] for name in before_catalog["tables"]
        } == before_catalog["tables"]
        for category in ("indexes", "triggers", "functions", "sequences"):
            assert all(value in after_catalog[category] for value in before_catalog[category])
        assert "description" not in {
            column["name"] for column in inspect(engine).get_columns("matter_task_queue_pages")
        }
        _assert_physical(engine, rows)
        observations = [
            _assert_whole_queue(engine, scope, peer, rows, tmp_path / "queue-after-upgrade")
        ]

        created = dict(
            rows[str(UUID(int=0x600001))],
            id=str(UUID(int=0x620000)),
            owner_membership_id=None,
            title="Old writer after upgrade",
            description=None,
            due_on=date(2026, 12, 1),
            created_at=STAMP + timedelta(seconds=1),
            updated_at=STAMP + timedelta(seconds=1),
        )
        with engine.begin() as connection:
            connection.execute(old_writer.insert().values(**created))
        rows[created["id"]] = created
        _assert_physical(engine, rows)
        observations.append(
            _assert_whole_queue(engine, scope, peer, rows, tmp_path / "queue-after-insert")
        )
        changed_id = str(UUID(int=0x600002))
        changed = dict(
            owner_membership_id=peer,
            due_on=None,
            status="blocked",
            title="Old writer moved scope",
            updated_at=STAMP + timedelta(seconds=2),
        )
        with engine.begin() as connection:
            connection.execute(
                old_writer.update().where(old_writer.c.id == changed_id).values(**changed)
            )
        rows[changed_id].update(changed)
        _assert_physical(engine, rows)
        observations.append(
            _assert_whole_queue(engine, scope, peer, rows, tmp_path / "queue-after-update")
        )
        with engine.begin() as connection:
            connection.execute(old_writer.delete().where(old_writer.c.id == created["id"]))
        del rows[created["id"]]
        _assert_physical(engine, rows)
        observations.append(
            _assert_whole_queue(engine, scope, peer, rows, tmp_path / "queue-after-delete")
        )
        retained = _rows(engine, [name for name in old_tables if name != "matter_tasks"])
        assert retained == {
            name: value for name, value in before_rows.items() if name != "matter_tasks"
        }
        all_tables = sorted(inspect(engine).get_table_names())
        refusal_rows, refusal_catalog = _rows(engine, all_tables), _catalog(engine)
        before_refusal = _artifact(tmp_path / "0006-before-refusal-all-rows.json", refusal_rows)
        _artifact(tmp_path / "0006-before-refusal-catalog.json", refusal_catalog)
        failure = None
        try:
            command.downgrade(config, PREVIOUS)
        except RuntimeError as error:
            failure = str(error)
        assert failure == "Matter-task queue storage requires reviewed roll-forward or restore."
        current_rows, current_catalog = _rows(engine, all_tables), _catalog(engine)
        after_refusal = _artifact(tmp_path / "0006-after-refusal-all-rows.json", current_rows)
        _artifact(tmp_path / "0006-after-refusal-catalog.json", current_catalog)
        assert current_rows == refusal_rows and current_catalog == refusal_catalog
        assert before_refusal["sha256"] == after_refusal["sha256"]
        with engine.connect() as connection:
            actual_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert actual_revision == NAMED_HEAD
        _assert_physical(engine, rows)
        observations.append(
            _assert_whole_queue(engine, scope, peer, rows, tmp_path / "queue-after-refusal")
        )
        _artifact(
            tmp_path / "named-boundary-journey.json",
            dict(
                previous=PREVIOUS,
                namedHead=NAMED_HEAD,
                dialect=kind,
                historicalOldColumnTasks=83,
                compatibilityWrites={"insert": 1, "update": 1, "delete": 1},
                originalWideTextUnchanged=True,
                sourceAuditOutboxReceiptBytesPreserved=True,
                wholeQueueReloads=len(observations),
                observations=observations,
                maximumServiceCalls=180,
                physicalSlotsCompared=True,
                actualRetainedRefusal=True,
                productionRoleAcceptance=False,
                backupRestorationClaimed=False,
            ),
        )
