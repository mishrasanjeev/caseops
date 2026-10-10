import ast
from pathlib import Path
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


@pytest.mark.parametrize(
    "filename,function,previous,revision",
    [
        (
            "test_20260715_lifecycle_migration.py",
            "test_lifecycle_migration_neutralizes_legacy_closed_children",
            "20260708_0001",
            "20260715_0001",
        ),
        (
            "test_20260717_matter_default_migration.py",
            "test_matter_status_database_default_upgrades_and_downgrades_cleanly",
            "20260715_0001",
            "20260717_0001",
        ),
        (
            "test_20260723_court_forum_number_migration.py",
            "test_court_forum_number_migration_upgrades_downgrades_and_reupgrades",
            "20260717_0002",
            "20260723_0001",
        ),
        (
            "test_20260811_forum_catalog_migration.py",
            "test_manual_matter_forum_catalog_upgrades_downgrades_and_reupgrades",
            "20260811_0003",
            "20260811_0004",
        ),
        (
            "test_20260828_intelligent_review_migration.py",
            "test_intelligent_review_migration_round_trip_and_index_coverage",
            "20260827_0002",
            "20260828_0001",
        ),
        (
            "test_20260828_case_tracking_source_text_migration.py",
            "test_case_tracking_source_text_migration_round_trip_and_index_health",
            "20260828_0001",
            "20260828_0002",
        ),
    ],
    ids=["lifecycle", "matter-default", "court-forum", "forum-catalog", "review", "source-text"],
)
def test_reported_dated_roundtrips_cannot_upgrade_a_computed_moving_head(
    filename, function, previous, revision
):
    tree = ast.parse((Path(__file__).parent / filename).read_text(encoding="utf-8-sig"))
    constants = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    journey = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function
    )
    targets = []
    for node in ast.walk(journey):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "command"
            and node.func.attr in {"upgrade", "downgrade"}
        ):
            assert len(node.args) == 2
            argument = node.args[1]
            target = (
                argument.value
                if isinstance(argument, ast.Constant)
                else constants.get(argument.id) if isinstance(argument, ast.Name) else None
            )
            assert target in {previous, revision}, (
                filename,
                node.lineno,
                "A dated roundtrip cannot descend from moving head; keep head health separate",
                ast.unparse(node),
            )
            targets.append(target)
    assert set(targets) == {previous, revision}


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
