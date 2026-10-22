"""Independent fresh upgrades and rollback refusal preserve release data."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.scripts.check_database_indexes import build_index_health_report
from caseops_api.services.billing_demo import NOTIFICATION_POLICY, NOTIFICATION_PURPOSE
from caseops_api.services.platform_console_leads import leads_page
from tests.test_platform_console_migration import fresh_engine, migration_config

PREVIOUS = "20261020_0001"
REVISION = "20261021_0001"
INDEX = "ix_billing_enrollments_public_lead_created_id"
BRIDGE_TRIGGER = "trg_billing_enrollments_legacy_public_lead_insert"
BRIDGE_FUNCTION = "caseops_classify_legacy_public_lead_insert"
KINDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]


def _table(engine):
    return sa.Table("billing_enrollments", sa.MetaData(), autoload_with=engine)


def _records(engine):
    table = _table(engine)
    with engine.connect() as connection:
        return {
            row["id"]: {key: value for key, value in row.items() if key != "is_public_lead"}
            for row in connection.execute(sa.select(table)).mappings()
        }


def _columns(schema):
    return [{**row, "type": str(row["type"])} for row in schema.get_columns("billing_enrollments")]


def _raw_records(engine):
    table = _table(engine)
    columns = [
        sa.cast(column, sa.Text).label(column.name)
        if column.name == "status_timestamps_json"
        else column
        for column in table.c
        if column.name != "is_public_lead"
    ]
    with engine.connect() as connection:
        return {row["id"]: dict(row) for row in connection.execute(sa.select(*columns)).mappings()}


def _catalog(engine):
    with engine.connect() as connection:
        aliases = connection.execute(
            sa.text("SELECT id, normalized_alias FROM forum_catalog_aliases ORDER BY id")
        ).all()
        if engine.dialect.name == "postgresql":
            triggers = connection.execute(
                sa.text(
                    "SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid) "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE NOT t.tgisinternal AND n.nspname='public' "
                    "ORDER BY c.relname,t.tgname"
                )
            ).all()
            functions = connection.execute(
                sa.text(
                    "SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.proname=:name ORDER BY p.oid"
                ),
                {"name": BRIDGE_FUNCTION},
            ).all()
        else:
            triggers = connection.execute(
                sa.text("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")
            ).all()
            functions = []
    return aliases, triggers, functions


def _assert_insert_bridge(engine, before_catalog):
    aliases, triggers, functions = _catalog(engine)
    name_index = 1 if engine.dialect.name == "postgresql" else 0
    bridge = [row for row in triggers if row[name_index] == BRIDGE_TRIGGER]
    assert len(bridge) == 1
    assert aliases == before_catalog[0]
    assert [row for row in triggers if row[name_index] != BRIDGE_TRIGGER] == before_catalog[1]
    definition = bridge[0][-1]
    header = definition.upper().split(" ON ", 1)[0]
    assert "INSERT" in header and "UPDATE" not in header
    if engine.dialect.name == "postgresql":
        assert bridge[0][0] == "billing_enrollments"
        assert len(functions) == 1 and functions[0][0] == BRIDGE_FUNCTION
        assert "NEW.is_public_lead := true" in functions[0][1]
        assert "notification_purpose" in functions[0][1]
    else:
        assert not functions
        assert "WHERE id = NEW.id" in definition
        assert "notification_purpose" in definition
    assert not before_catalog[2]


@pytest.mark.parametrize("kind", KINDS)
def test_historical_visibility_upgrade_replay_and_rollback_refusal_preserve_all_records(
    kind,
    tmp_path,
    monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        before_schema = sa.inspect(engine)
        before_columns = _columns(before_schema)
        before_indexes = before_schema.get_indexes("billing_enrollments")
        before_foreign_keys = before_schema.get_foreign_keys("billing_enrollments")
        assert "is_public_lead" not in {row["name"] for row in before_columns}
        now = datetime(2026, 10, 21, 12, tzinfo=UTC)
        definitions = [
            (True, "demo_requested", {}),
            (True, "converted", {"demo_requested_at": now.isoformat()}),
            (
                True,
                "converted",
                {
                    "demo_admission": {
                        "contract_version": "seo_demo_20261009",
                        "notification_status": "outcome_unknown",
                        "attempts": 3,
                        "last_error_code": "timeout",
                    }
                },
            ),
            (
                True,
                "converted",
                {
                    "demo_admission": {
                        "contract_version": "legacy_public_demo_v1",
                        "notification_status": "pending",
                    }
                },
            ),
            (False, "trial_started", {}),
            (False, "converted", {"demo_requested_at": ""}),
            (False, "converted", {"created_at": now.isoformat()}),
            (False, "converted", {"demo_requested_at": "2026-10-21"}),
        ]
        records, expected = [], {}
        for index, (public, status, state) in enumerate(definitions):
            identity = str(uuid4())
            expected[identity] = public
            records.append(
                {
                    "id": identity,
                    "contact_name": f"Retained {index}",
                    "contact_email": f"retained-{index}@example.com",
                    "segment": "solo",
                    "source": "demo",
                    "status": status,
                    "notes": f"Retained note {index}",
                    "created_at": now,
                    "updated_at": now,
                    "status_timestamps_json": state,
                }
            )
        with engine.begin() as connection:
            connection.execute(_table(engine).insert(), records)
        before_records, before_catalog = _records(engine), _catalog(engine)
        assert before_catalog[0]

        after_catalog = None
        for _ in range(2):
            command.upgrade(config, REVISION)
            schema = sa.inspect(engine)
            columns = _columns(schema)
            added = next(row for row in columns if row["name"] == "is_public_lead")
            assert added["nullable"] is False and added["default"] is not None
            assert [row for row in columns if row["name"] != "is_public_lead"] == before_columns
            indexes = schema.get_indexes("billing_enrollments")
            assert [row for row in indexes if row["name"] != INDEX] == before_indexes
            assert next(row for row in indexes if row["name"] == INDEX)["column_names"] == [
                "is_public_lead",
                "created_at",
                "id",
            ]
            assert schema.get_foreign_keys("billing_enrollments") == before_foreign_keys
            assert _records(engine) == before_records
            _assert_insert_bridge(engine, before_catalog)
            if after_catalog is None:
                after_catalog = _catalog(engine)
            else:
                assert _catalog(engine) == after_catalog
            table = _table(engine)
            with engine.connect() as connection:
                assert (
                    connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                    == REVISION
                )
                actual = dict(
                    connection.execute(
                        sa.select(
                            table.c.id,
                            table.c.is_public_lead,
                        )
                    ).all()
                )
                assert actual == expected
            with Session(engine) as session:
                page = leads_page(session, cursor=None, limit=100)
                assert {row.id for row in page.items} == {
                    identity for identity, public in expected.items() if public
                }
                assert all(not row.notification.eligible for row in page.items)
                assert not page.has_more

        with pytest.raises(RuntimeError, match="downgrade requires roll-forward or restore"):
            command.downgrade(config, PREVIOUS)
        schema = sa.inspect(engine)
        assert _columns(schema) == columns
        assert schema.get_indexes("billing_enrollments") == indexes
        assert schema.get_foreign_keys("billing_enrollments") == before_foreign_keys
        assert _records(engine) == before_records and _catalog(engine) == after_catalog
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION
        command.upgrade(config, REVISION)
        assert _records(engine) == before_records and _catalog(engine) == after_catalog
        table = _table(engine)
        with engine.connect() as connection:
            assert (
                dict(
                    connection.execute(
                        sa.select(
                            table.c.id,
                            table.c.is_public_lead,
                        )
                    ).all()
                )
                == expected
            )


@pytest.mark.parametrize("kind", KINDS)
def test_empty_enrollment_database_keeps_roll_forward_only_policy(kind, tmp_path, monkeypatch):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, REVISION)
        columns = _columns(sa.inspect(engine))
        indexes = sa.inspect(engine).get_indexes("billing_enrollments")
        catalog = _catalog(engine)
        assert not _records(engine)
        with pytest.raises(RuntimeError, match="downgrade requires roll-forward or restore"):
            command.downgrade(config, PREVIOUS)
        assert _columns(sa.inspect(engine)) == columns
        assert sa.inspect(engine).get_indexes("billing_enrollments") == indexes
        assert not _records(engine)
        assert _catalog(engine) == catalog
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION
        command.upgrade(config, REVISION)
        assert _columns(sa.inspect(engine)) == columns
        assert sa.inspect(engine).get_indexes("billing_enrollments") == indexes
        assert not _records(engine)
        assert _catalog(engine) == catalog


@pytest.mark.parametrize("kind", KINDS)
def test_rolling_legacy_inserts_are_classified_without_reviving_excluded_records(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        old_table = _table(engine)
        assert "is_public_lead" not in old_table.c
        before_catalog = _catalog(engine)
        now = datetime(2026, 10, 22, 0, tzinfo=UTC)
        outbox = {
            "contract_version": "seo_demo_20261009",
            "notification_status": "outcome_unknown",
            "attempts": 3,
            "claim": "retained-legacy-claim",
            "lease_until": now.isoformat(),
            "last_error_code": "timeout",
        }

        def record(status, state):
            identity = str(uuid4())
            return {
                "id": identity,
                "contact_name": "Rolling admission",
                "contact_email": f"{identity}@example.com",
                "segment": "solo",
                "source": "demo",
                "status": status,
                "notes": "Retained rolling fixture",
                "created_at": now,
                "updated_at": now,
                "status_timestamps_json": state,
            }

        pre_excluded = record(
            "demo_requested",
            {
                "demo_admission": {
                    **outbox,
                    "notification_purpose": NOTIFICATION_PURPOSE,
                    "notification_policy": NOTIFICATION_POLICY,
                    "notification_eligible": True,
                }
            },
        )
        pre_malformed = record("converted", ["not", "an", "object"])
        with engine.begin() as connection:
            connection.execute(old_table.insert(), pre_excluded)
            if kind == "sqlite":
                connection.execute(
                    old_table.insert().values(
                        **{
                            **pre_malformed,
                            "status_timestamps_json": sa.literal_column("'not-json'"),
                        }
                    )
                )
            else:
                connection.execute(old_table.insert(), pre_malformed)
        pre_records = _raw_records(engine)
        command.upgrade(config, REVISION)
        command.upgrade(config, REVISION)
        _assert_insert_bridge(engine, before_catalog)
        assert _raw_records(engine) == pre_records
        table = _table(engine)

        definitions = [
            (True, "demo_requested", {"demo_admission": outbox}),
            (True, "converted", {"demo_requested_at": now.isoformat()}),
            (True, "converted", {"demo_admission": outbox}),
            (True, "converted", {"demo_admission": {"contract_version": "legacy_public_demo_v1"}}),
            (False, "converted", {}),
            (False, "converted", {"demo_requested_at": "2026-10-22"}),
            (False, "converted", {"demo_admission": {"contract_version": "other"}}),
            (False, "converted", {"demo_admission": {"contract_version": ["seo_demo_20261009"]}}),
            (False, "converted", {"demo_admission": "not-an-object"}),
            (False, "converted", ["not", "an", "object"]),
            (False, "converted", "not-json-object"),
            (False, "converted", None),
        ]
        records = []
        expected = {pre_excluded["id"]: False, pre_malformed["id"]: False}
        for public, status, state in definitions:
            item = record(status, state)
            records.append(item)
            expected[item["id"]] = public
        excluded = [
            {
                **record(
                    "demo_requested",
                    {
                        "demo_admission": {
                            **outbox,
                            "notification_purpose": purpose,
                            "notification_policy": NOTIFICATION_POLICY,
                            "notification_eligible": True,
                        }
                    },
                ),
                "is_public_lead": False,
            }
            for purpose in (NOTIFICATION_PURPOSE, "future-purpose", None, False, "")
        ]
        expected.update({item["id"]: False for item in excluded})
        null_metadata = record("demo_requested", None)
        expected[null_metadata["id"]] = True
        with engine.begin() as connection:
            # This reflected pre-upgrade shape cannot send the new column.
            connection.execute(old_table.insert(), records)
            connection.execute(table.insert(), excluded)
            connection.execute(
                old_table.insert().values(**{**null_metadata, "status_timestamps_json": sa.null()})
            )
            assert (
                dict(connection.execute(sa.select(table.c.id, table.c.is_public_lead)).all())
                == expected
            )

        raw = _raw_records(engine)
        for item in records + excluded:
            assert raw[item["id"]]["status_timestamps_json"] == json.dumps(
                item["status_timestamps_json"]
            )
            assert raw[item["id"]]["updated_at"].replace(tzinfo=UTC) == now
        assert raw[null_metadata["id"]]["status_timestamps_json"] is None

        malformed = record("converted", {})
        statement = old_table.insert().values(
            **{**malformed, "status_timestamps_json": sa.literal_column("'not-json'")}
        )
        with engine.begin() as connection:
            if kind == "sqlite":
                connection.execute(statement)
                expected[malformed["id"]] = False
            else:
                # PostgreSQL's JSON type rejects invalid text before the trigger.
                with pytest.raises(sa.exc.DataError), connection.begin_nested():
                    connection.execute(statement)
        after_malformed = _raw_records(engine)
        assert all(after_malformed[identity] == value for identity, value in raw.items())

        rolled_back = record("demo_requested", {})
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(old_table.insert(), rolled_back)
            assert (
                connection.scalar(
                    sa.select(table.c.is_public_lead).where(table.c.id == rolled_back["id"])
                )
                is True
            )
            transaction.rollback()
        assert rolled_back["id"] not in _raw_records(engine)

        revoked = records[0]["id"]
        with engine.begin() as connection:
            connection.execute(
                old_table.update()
                .where(old_table.c.id == revoked)
                .values(status="converted", updated_at=now + timedelta(minutes=1))
            )
            assert (
                connection.scalar(sa.select(table.c.is_public_lead).where(table.c.id == revoked))
                is True
            )
            connection.execute(
                table.update().where(table.c.id == revoked).values(is_public_lead=False)
            )
            # Neither an old-protocol update nor removal of the new marker revives false.
            for identity in (revoked, excluded[0]["id"]):
                connection.execute(
                    old_table.update()
                    .where(old_table.c.id == identity)
                    .values(
                        status="demo_requested", status_timestamps_json={"demo_admission": outbox}
                    )
                )
                assert (
                    connection.scalar(
                        sa.select(table.c.is_public_lead).where(table.c.id == identity)
                    )
                    is False
                )
        expected[revoked] = False
        before_records, catalog = _raw_records(engine), _catalog(engine)
        for _ in range(2):
            command.upgrade(config, REVISION)
            with Session(engine) as session:
                page = leads_page(session, cursor=None, limit=100)
                assert {row.id for row in page.items} == {
                    identity for identity, public in expected.items() if public
                }
                assert all(not row.notification.eligible for row in page.items)
                assert not page.has_more
            assert _raw_records(engine) == before_records and _catalog(engine) == catalog
        with pytest.raises(RuntimeError, match="downgrade requires roll-forward or restore"):
            command.downgrade(config, PREVIOUS)
        assert _raw_records(engine) == before_records and _catalog(engine) == catalog
        with engine.connect() as connection:
            assert (
                dict(connection.execute(sa.select(table.c.id, table.c.is_public_lead)).all())
                == expected
            )
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION


@pytest.mark.parametrize("kind", KINDS)
def test_actual_current_head_has_complete_public_lead_index_health(kind, tmp_path, monkeypatch):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        heads = ScriptDirectory.from_config(config).get_heads()
        assert len(heads) == 1
        command.upgrade(config, "head")
        schema = sa.inspect(engine)
        assert (
            next(row for row in _columns(schema) if row["name"] == "is_public_lead")["nullable"]
            is False
        )
        index = next(
            row for row in schema.get_indexes("billing_enrollments") if row["name"] == INDEX
        )
        assert index["column_names"] == ["is_public_lead", "created_at", "id"]
        with engine.connect() as connection:
            health = build_index_health_report(connection)
        assert health["status"] == "ok", health
        assert health["schema_revisions"] == heads == [health["required_schema_revision"]]
