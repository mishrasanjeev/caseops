from types import SimpleNamespace

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    select,
)
from sqlalchemy.engine import make_url

from tests.fixtures_historical_migrations import historical_database, replay_fixture_rows


def test_historical_rehearsal_rejects_moving_head_before_database_work():
    with pytest.raises(AssertionError):
        with historical_database(None, "head"):
            pytest.fail("Moving head must not enter a historical rehearsal")


def test_historical_postgres_rehearsal_rejects_sqlite():
    engine = create_engine("sqlite://")
    try:
        with pytest.raises(AssertionError):
            with historical_database(engine, "20260715_0001"):
                pytest.fail("The native rehearsal must not substitute SQLite")
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "database",
    ["postgres", "caseops", "caseops_http_template_" + "a" * 32],
    ids=["shared-admin", "shared-application", "immutable-template"],
)
def test_fixture_replay_rejects_shared_or_template_database_before_any_read(database):
    source = SimpleNamespace(url=make_url("postgresql+psycopg://localhost/" + database))
    with pytest.raises(AssertionError, match="independently isolated"):
        replay_fixture_rows(source, None, [("companies", {"id": "not-a-fixture"})])


def test_fixture_replay_rejects_same_database_before_any_read():
    source = SimpleNamespace(
        url=make_url("postgresql+psycopg://localhost/caseops_http_" + "a" * 32)
    )
    with pytest.raises(AssertionError):
        replay_fixture_rows(source, source, [("companies", {"id": "not-a-fixture"})])


@pytest.mark.parametrize("marker", [True, False], ids=["legacy-no-paid", "explicit-human"])
def test_fixture_replay_copies_only_explicit_lineage_and_preserves_boolean(
    tmp_path, monkeypatch, marker
):
    monkeypatch.chdir(tmp_path)
    source = create_engine("sqlite:///caseops_http_" + "b" * 32)
    destination = create_engine("sqlite:///dated.db")

    @event.listens_for(destination, "connect")
    def require_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    def schema(engine, modern):
        metadata = MetaData()
        parents = Table("fixture_parents", metadata, Column("id", Integer, primary_key=True))
        columns = [
            Column("id", Integer, primary_key=True),
            Column("parent_id", Integer, ForeignKey("fixture_parents.id"), nullable=False),
            Column("no_paid_providers", Boolean, nullable=False),
        ]
        if modern:
            columns.append(Column("future_fact", String))
        children = Table("fixture_children", metadata, *columns)
        metadata.create_all(engine)
        return parents, children

    parents, children = schema(source, True)
    dated_parents, dated_children = schema(destination, False)
    try:
        with source.begin() as connection:
            connection.execute(parents.insert(), [{"id": 1}, {"id": 2}])
            connection.execute(
                children.insert(),
                [
                    {"id": 1, "parent_id": 1, "no_paid_providers": marker, "future_fact": "modern"},
                    {
                        "id": 2,
                        "parent_id": 2,
                        "no_paid_providers": not marker,
                        "future_fact": "unrelated",
                    },
                ],
            )
        copied = replay_fixture_rows(source, destination, [("fixture_children", {"id": 1})])
        assert copied == [("fixture_parents", {"id": 1}), ("fixture_children", {"id": 1})]
        with destination.connect() as connection:
            assert connection.execute(select(dated_parents)).all() == [(1,)]
            assert connection.execute(select(dated_children)).all() == [(1, 1, marker)]
        with source.connect() as connection:
            assert connection.execute(select(children)).all() == [
                (1, 1, marker, "modern"),
                (2, 2, not marker, "unrelated"),
            ]
    finally:
        source.dispose()
        destination.dispose()
