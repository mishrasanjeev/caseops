from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import MetaData, Table, and_, create_engine, inspect, select, text
from sqlalchemy.pool import NullPool

from alembic import command
from caseops_api.core.settings import get_settings


def migration_config(engine) -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    return config


@contextmanager
def historical_database(source_engine, revision: str):
    """Rehearse a named revision from template0, never an application clone."""
    assert revision != "head"
    assert source_engine.dialect.name == "postgresql"
    name = "caseops_historical_" + uuid4().hex
    admin = create_engine(source_engine.url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    quoted = admin.dialect.identifier_preparer.quote(name)
    created = False
    engine = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {quoted} TEMPLATE template0")
        created = True
        engine = create_engine(source_engine.url.set(database=name), poolclass=NullPool)
        config = migration_config(engine)
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("CASEOPS_DATABASE_URL", engine.url.render_as_string(hide_password=False))
            get_settings.cache_clear()
            try:
                command.upgrade(config, revision)
                with engine.connect() as connection:
                    assert (
                        connection.scalar(text("SELECT version_num FROM alembic_version"))
                        == revision
                    )
                yield engine, config
            finally:
                get_settings.cache_clear()
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            assert re.fullmatch(r"caseops_historical_[0-9a-f]{32}", name)
            assert name != source_engine.url.database
            with admin.connect() as connection:
                connection.exec_driver_sql(f"DROP DATABASE {quoted} WITH (FORCE)")
        admin.dispose()


def replay_fixture_rows(source_engine, destination_engine, roots):
    """Copy only explicit test rows and their dated FK parents, bounded to 64."""
    assert re.fullmatch(
        r"caseops_(?:http|migration)_[0-9a-f]{32}", source_engine.url.database or ""
    ), "Only independently isolated test fixtures may supply migration evidence"
    assert source_engine.url != destination_engine.url
    tables = {}
    inspector = inspect(destination_engine)
    copied = []
    visiting = set()
    seen = set()

    def table(engine, name):
        key = (engine, name)
        if key not in tables:
            tables[key] = Table(name, MetaData(), autoload_with=engine, resolve_fks=False)
        return tables[key]

    with source_engine.connect() as source, destination_engine.begin() as destination:

        def copy(name, identity, depth=0):
            assert depth < 16 and len(seen) + len(visiting) < 64, "Fixture lineage is unbounded"
            key = (name, tuple(sorted(identity.items())))
            if key in seen:
                return
            assert key not in visiting, "Cyclic fixture lineage requires an explicit fixture"
            target = table(destination_engine, name)
            predicate = and_(*(target.c[column] == value for column, value in identity.items()))
            existing = destination.execute(select(target).where(predicate)).mappings().one_or_none()
            if existing is not None:
                # Release-owned catalog parents are already seeded by the dated migration.
                seen.add(key)
                return
            original = table(source_engine, name)
            row = (
                source.execute(
                    select(original).where(
                        and_(*(original.c[column] == value for column, value in identity.items()))
                    )
                )
                .mappings()
                .one()
            )
            assert set(target.c.keys()) <= set(row), "Historical columns must exist in the fixture"
            values = {column.name: row[column.name] for column in target.c}
            visiting.add(key)
            for foreign_key in inspector.get_foreign_keys(name):
                assert foreign_key["referred_schema"] in (None, "public")
                parent = dict(
                    zip(
                        foreign_key["referred_columns"],
                        (values[column] for column in foreign_key["constrained_columns"]),
                        strict=True,
                    )
                )
                if all(value is not None for value in parent.values()):
                    copy(foreign_key["referred_table"], parent, depth + 1)
            destination.execute(target.insert().values(values))
            assert (
                dict(destination.execute(select(target).where(predicate)).mappings().one())
                == values
            )
            visiting.remove(key)
            seen.add(key)
            copied.append((name, identity))

        for name, identity in roots:
            copy(name, identity)
    return copied


def assert_fixture_downgrade_refused(source_engine, revision, predecessor, roots, message):
    with historical_database(source_engine, revision) as (engine, config):
        copied = replay_fixture_rows(source_engine, engine, roots)
        assert copied, "Retained evidence must exist before exercising its guard"
        snapshots = []
        with engine.connect() as connection:
            before = connection.execute(
                text(
                    "SELECT table_name, column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns WHERE table_schema='public' ORDER BY 1,2"
                )
            ).all()
            for name, identity in copied:
                table = Table(name, MetaData(), autoload_with=connection, resolve_fks=False)
                statement = select(table).where(
                    and_(*(table.c[column] == value for column, value in identity.items()))
                )
                snapshots.append((statement, dict(connection.execute(statement).mappings().one())))
        for _ in range(2):
            with pytest.raises(RuntimeError, match=message):
                command.downgrade(config, predecessor)
            with engine.connect() as connection:
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
                )
                assert (
                    connection.execute(
                        text(
                            "SELECT table_name, column_name, data_type, is_nullable, "
                            "column_default FROM information_schema.columns "
                            "WHERE table_schema='public' ORDER BY 1,2"
                        )
                    ).all()
                    == before
                )
                for statement, original in snapshots:
                    assert dict(connection.execute(statement).mappings().one()) == original


def insert_historical_fixture(connection, model, **values):
    """Use actual dated columns with explicit facts and canonical Python defaults."""
    table = Table(model.__tablename__, MetaData(), autoload_with=connection, resolve_fks=False)
    assert set(values) <= set(table.c.keys()), "Do not seed future fields into a legacy fixture"
    for column in table.c:
        default = model.__table__.c[column.name].default
        if column.name not in values and default is not None:
            values[column.name] = default.arg(None) if default.is_callable else default.arg
    connection.execute(table.insert().values(values))
    return values["id"]


def seed_legacy_closed_matter(engine):
    from caseops_api.db.models import (
        CalendarEventSync,
        Company,
        CompanyMembership,
        Matter,
        MatterDeadline,
        MatterHearing,
        MatterTask,
        User,
        UserCalendarConnection,
    )

    ids = {
        name: str(uuid4())
        for name in (
            "company",
            "user",
            "membership",
            "matter",
            "task",
            "deadline",
            "hearing",
            "sync",
        )
    }
    with engine.begin() as connection:
        assert "lifecycle_version" not in {
            row["name"] for row in inspect(connection).get_columns("matters")
        }
        insert_historical_fixture(
            connection,
            Company,
            id=ids["company"],
            name="Legacy Lifecycle Firm",
            slug="legacy-" + ids["company"],
            company_type="law_firm",
            tenant_key=ids["company"],
        )
        insert_historical_fixture(
            connection,
            User,
            id=ids["user"],
            email=ids["user"] + "@example.com",
            full_name="Legacy Owner",
            password_hash="not-used",
        )
        insert_historical_fixture(
            connection,
            CompanyMembership,
            id=ids["membership"],
            company_id=ids["company"],
            user_id=ids["user"],
            role="owner",
        )
        insert_historical_fixture(
            connection,
            Matter,
            id=ids["matter"],
            company_id=ids["company"],
            title="Legacy closed matter",
            matter_code="LEGACY-1",
            client_name="Legacy Client",
            status="closed",
            practice_area="litigation",
            forum_level="high_court",
            is_active=True,
            next_hearing_on=date(2099, 4, 10),
            next_hearing_source="manual",
            next_hearing_source_ref_type="matter_hearing",
            next_hearing_source_ref_id=ids["hearing"],
            next_hearing_manual_lock=True,
        )
        insert_historical_fixture(
            connection,
            MatterTask,
            id=ids["task"],
            matter_id=ids["matter"],
            title="Legacy open task",
            status="todo",
        )
        insert_historical_fixture(
            connection,
            MatterDeadline,
            id=ids["deadline"],
            matter_id=ids["matter"],
            source="manual",
            kind="filing",
            title="Legacy deadline",
            due_on=date(2099, 4, 9),
            status="open",
        )
        insert_historical_fixture(
            connection,
            MatterHearing,
            id=ids["hearing"],
            matter_id=ids["matter"],
            hearing_on=date(2099, 4, 10),
            forum_name="Delhi High Court",
            purpose="Legacy open hearing",
            status="scheduled",
        )
        calendar_id = insert_historical_fixture(
            connection,
            UserCalendarConnection,
            company_id=ids["company"],
            membership_id=ids["membership"],
            provider="outlook",
            status="connected",
        )
        insert_historical_fixture(
            connection,
            CalendarEventSync,
            id=ids["sync"],
            company_id=ids["company"],
            calendar_connection_id=calendar_id,
            source_type="matter_hearing",
            source_id=ids["hearing"],
            provider_event_id="legacy-provider-event",
            sync_status="synced",
        )
        assert (
            connection.scalar(
                text("SELECT status FROM matters WHERE id=:id"), {"id": ids["matter"]}
            )
            == "closed"
        )
    return ids
