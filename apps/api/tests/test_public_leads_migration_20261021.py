"""Independent fresh upgrades and rollback refusal preserve release data."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.scripts.check_database_indexes import build_index_health_report
from caseops_api.services.platform_console_leads import leads_page
from tests.test_platform_console_migration import fresh_engine, migration_config

PREVIOUS = "20261020_0001"
REVISION = "20261021_0001"
INDEX = "ix_billing_enrollments_public_lead_created_id"
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
        else:
            triggers = connection.execute(
                sa.text("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")
            ).all()
    return aliases, triggers


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

        for _ in range(2):
            command.upgrade(config, "head")
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
            assert _records(engine) == before_records and _catalog(engine) == before_catalog
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
                if kind == "postgres":
                    health = build_index_health_report(connection)
                    assert health["status"] == "ok", health
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
        assert _records(engine) == before_records and _catalog(engine) == before_catalog
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION
        command.upgrade(config, "head")
        assert _records(engine) == before_records and _catalog(engine) == before_catalog
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
        assert not _records(engine)
        with pytest.raises(RuntimeError, match="downgrade requires roll-forward or restore"):
            command.downgrade(config, PREVIOUS)
        assert _columns(sa.inspect(engine)) == columns
        assert sa.inspect(engine).get_indexes("billing_enrollments") == indexes
        assert not _records(engine)
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION
        command.upgrade(config, "head")
        assert _columns(sa.inspect(engine)) == columns
        assert sa.inspect(engine).get_indexes("billing_enrollments") == indexes
        assert not _records(engine)
