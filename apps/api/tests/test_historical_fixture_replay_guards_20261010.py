"""Actual dated trigger contracts, semantic parents and bounded fixture lineage."""

import ast
import importlib.util
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError

from tests.fixtures_historical_migrations import (
    _initial_evidence_self_root,
    replay_finalized_access_review,
    replay_fixture_rows,
)

API = Path(__file__).resolve().parents[1]


def _migration(filename):
    spec = importlib.util.spec_from_file_location(filename, API / "alembic" / "versions" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = sa.create_engine("sqlite:///caseops_http_" + "d" * 32)
    destination = sa.create_engine("sqlite:///historical.db")
    for engine in (source, destination):

        @sa.event.listens_for(engine, "connect")
        def enforce_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

    try:
        yield source, destination
    finally:
        source.dispose()
        destination.dispose()


def _rows(engine, name):
    with engine.connect() as connection:
        table = sa.Table(name, sa.MetaData(), autoload_with=connection, resolve_fks=False)
        return [dict(row) for row in connection.execute(sa.select(table)).mappings()]


def _review_schema(engine, extra_parent_count=0):
    metadata = sa.MetaData()
    sa.Table("companies", metadata, sa.Column("id", sa.String, primary_key=True))
    sa.Table("users", metadata, sa.Column("id", sa.String, primary_key=True))
    for name in ("matters", "ip_docket_records"):
        extra_columns = (
            [
                sa.Column(f"parent_{index}", sa.String, sa.ForeignKey("users.id"))
                for index in range(extra_parent_count)
            ]
            if name == "matters"
            else []
        )
        sa.Table(
            name,
            metadata,
            sa.Column("id", sa.String, primary_key=True),
            sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
            sa.UniqueConstraint("id", "company_id"),
            *extra_columns,
        )
    sa.Table(
        "company_memberships",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("company_id", sa.String, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("id", "company_id"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            _migration("20260910_0001_access_review_campaigns.py").upgrade()


def _finalized_review(source, decision_count=1, extra_parent_count=0):
    metadata = sa.MetaData()
    metadata.reflect(source)
    with source.begin() as connection:
        connection.execute(metadata.tables["companies"].insert(), {"id": "company"})
        connection.execute(
            metadata.tables["users"].insert(),
            [{"id": "creator"}, {"id": "reviewer"}]
            + [{"id": f"parent-{index}"} for index in range(extra_parent_count)],
        )
        connection.execute(
            metadata.tables["matters"].insert(),
            {
                "id": "matter",
                "company_id": "company",
                **{f"parent_{index}": f"parent-{index}" for index in range(extra_parent_count)},
            },
        )
        connection.execute(
            metadata.tables["company_memberships"].insert(),
            {"id": "membership", "company_id": "company", "user_id": "reviewer"},
        )
        campaigns = metadata.tables["access_review_campaigns"]
        connection.execute(
            campaigns.insert(),
            {
                "id": "campaign",
                "company_id": "company",
                "matter_id": "matter",
                "ip_docket_id": None,
                "title": "Explicit retained review",
                "reason": "Current independent reviewer",
                "trigger": "periodic",
                "creator_user_id": "creator",
                "snapshot_json": {
                    "scope": {
                        "grants": [
                            {"id": "grant" if decision_count == 1 else f"grant-{index:02}"}
                            for index in range(decision_count)
                        ]
                    }
                },
                "snapshot_hash": "a" * 64,
                "status": "open",
                "version": decision_count + 1,
                "created_at": datetime(2026, 9, 10),
                "finalized_at": None,
            },
        )
        reviewed = dict(connection.execute(sa.select(campaigns)).mappings().one())
        connection.execute(
            metadata.tables["access_review_decisions"].insert(),
            [
                {
                    "id": "decision" if decision_count == 1 else f"decision-{index:02}",
                    "company_id": "company",
                    "campaign_id": "campaign",
                    "grant_id": "grant" if decision_count == 1 else f"grant-{index:02}",
                    "decision": "keep",
                    "reason": "Explicit reviewed scope",
                    "reviewer_user_id": "reviewer",
                    "reviewer_membership_id": "membership",
                    "created_at": datetime(2026, 9, 10, 1),
                }
                for index in range(decision_count)
            ],
        )
        connection.execute(
            campaigns.update().values(
                status="finalized",
                version=decision_count + 2,
                finalized_at=datetime(2026, 9, 10, 2),
            )
        )
    return reviewed


def test_finalized_review_requires_real_open_decision_finalization_order(engines):
    source, destination = engines
    for engine in engines:
        _review_schema(engine)
    reviewed = _finalized_review(source)
    originals = {
        name: _rows(source, name) for name in ("access_review_campaigns", "access_review_decisions")
    }
    with pytest.raises(IntegrityError, match="immutable or outside scope"):
        replay_fixture_rows(source, destination, [("access_review_decisions", {"id": "decision"})])
    assert _rows(destination, "access_review_campaigns") == []
    assert _rows(destination, "access_review_decisions") == []
    statements = []

    def capture(_connection, _cursor, sql, *_args):
        statements.append(sql)

    sa.event.listen(destination, "before_cursor_execute", capture)
    try:
        copied = replay_finalized_access_review(source, destination, reviewed)
    finally:
        sa.event.remove(destination, "before_cursor_execute", capture)
    assert ("access_review_decisions", {"id": "decision"}) in copied
    writes = [
        sql.split()[0:3]
        for sql in statements
        if sql.startswith(("INSERT INTO access_review_", "UPDATE access_review_"))
    ]
    assert writes[0][:3] == ["INSERT", "INTO", "access_review_campaigns"]
    assert writes[1][:3] == ["INSERT", "INTO", "access_review_decisions"]
    assert writes[2][:2] == ["UPDATE", "access_review_campaigns"]
    for name, original in originals.items():
        assert _rows(destination, name) == original
        assert _rows(source, name) == original
    for sql in (
        "UPDATE access_review_campaigns SET status='open', version=version+1, finalized_at=NULL",
        "DELETE FROM access_review_campaigns",
        "UPDATE access_review_decisions SET reason='forged'",
        "DELETE FROM access_review_decisions",
    ):
        with pytest.raises(IntegrityError, match="immutable"), destination.begin() as connection:
            connection.execute(sa.text(sql))
    for name, original in originals.items():
        assert _rows(destination, name) == original


@pytest.mark.parametrize("change", [{"version": 1}, {"snapshot_hash": "b" * 64}])
def test_review_reconstruction_rejects_invented_pre_finalization_snapshot(engines, change):
    source, destination = engines
    for engine in engines:
        _review_schema(engine)
    reviewed = _finalized_review(source)
    with pytest.raises(AssertionError):
        replay_finalized_access_review(source, destination, {**reviewed, **change})
    assert _rows(destination, "access_review_campaigns") == []
    assert _rows(destination, "access_review_decisions") == []


@pytest.mark.parametrize(
    "decision_count,extra_parent_count,blocked_stage",
    [(63, 0, "decision"), (1, 61, "campaign")],
)
def test_review_shared_row_budget_rejects_before_excess_insert_and_finalization(
    engines, decision_count, extra_parent_count, blocked_stage
):
    source, destination = engines
    for engine in engines:
        _review_schema(engine, extra_parent_count)
    reviewed = _finalized_review(source, decision_count, extra_parent_count)
    originals = {
        name: _rows(source, name) for name in ("access_review_campaigns", "access_review_decisions")
    }
    writes = []

    def capture(_connection, _cursor, sql, parameters, *_args):
        if sql.startswith(("INSERT", "UPDATE")):
            writes.append((sql, parameters))

    sa.event.listen(destination, "before_cursor_execute", capture)
    try:
        with pytest.raises(AssertionError, match="Fixture lineage is unbounded"):
            replay_finalized_access_review(source, destination, reviewed)
    finally:
        sa.event.remove(destination, "before_cursor_execute", capture)
    assert len(writes) == 64
    assert all(sql.startswith("INSERT") for sql, _parameters in writes)
    assert _rows(destination, "access_review_decisions") == []
    if blocked_stage == "campaign":
        assert not any(sql.startswith("INSERT INTO access_review_campaigns") for sql, _ in writes)
        assert _rows(destination, "access_review_campaigns") == []
    else:
        decisions = [
            parameters[0]
            for sql, parameters in writes
            if sql.startswith("INSERT INTO access_review_decisions")
        ]
        assert decisions == [f"decision-{index:02}" for index in range(58)]
        assert "decision-58" not in decisions
        assert _rows(destination, "access_review_campaigns") == [reviewed]
    for name, original in originals.items():
        assert _rows(source, name) == original


def test_review_shared_row_budget_allows_below_bound_real_guarded_finalization(engines):
    source, destination = engines
    for engine in engines:
        _review_schema(engine)
    reviewed = _finalized_review(source, decision_count=57)
    copied = replay_finalized_access_review(source, destination, reviewed)
    assert len(copied) == 63
    for name in ("access_review_campaigns", "access_review_decisions"):
        assert _rows(destination, name) == _rows(source, name)


def _priority_schema(engine):
    metadata = sa.MetaData()
    sa.Table("ip_docket_records", metadata, sa.Column("id", sa.String, primary_key=True))
    sa.Table(
        "ip_patent_applications",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("company_id", sa.String),
        sa.Column("docket_id", sa.String, sa.ForeignKey("ip_docket_records.id")),
    )
    sa.Table(
        "ip_relationships",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("source_docket_id", sa.String, sa.ForeignKey("ip_docket_records.id")),
        sa.Column("target_docket_id", sa.String, sa.ForeignKey("ip_docket_records.id")),
    )
    sa.Table(
        "ip_patent_priority_details",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("company_id", sa.String),
        sa.Column("relationship_id", sa.String, sa.ForeignKey("ip_relationships.id")),
        sa.Column("source_docket_id", sa.String, sa.ForeignKey("ip_docket_records.id")),
        sa.Column("target_docket_id", sa.String, sa.ForeignKey("ip_docket_records.id")),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        _migration("20260907_0002_patent_priority_evidence.py")._guards(connection)


def test_priority_copy_requires_both_semantic_application_parents_before_detail(engines):
    source, destination = engines
    for engine in engines:
        _priority_schema(engine)
    metadata = sa.MetaData()
    metadata.reflect(source)
    with source.begin() as connection:
        connection.execute(
            metadata.tables["ip_docket_records"].insert(), [{"id": "child"}, {"id": "parent"}]
        )
        connection.execute(
            metadata.tables["ip_patent_applications"].insert(),
            [
                {"id": "child-app", "company_id": "company", "docket_id": "child"},
                {"id": "parent-app", "company_id": "company", "docket_id": "parent"},
            ],
        )
        connection.execute(
            metadata.tables["ip_relationships"].insert(),
            {"id": "relation", "source_docket_id": "child", "target_docket_id": "parent"},
        )
        connection.execute(
            metadata.tables["ip_patent_priority_details"].insert(),
            {
                "id": "detail",
                "company_id": "company",
                "relationship_id": "relation",
                "source_docket_id": "child",
                "target_docket_id": "parent",
            },
        )
    with pytest.raises(IntegrityError, match="requires two patent applications"):
        replay_fixture_rows(source, destination, [("ip_patent_priority_details", {"id": "detail"})])
    assert _rows(destination, "ip_patent_priority_details") == []
    roots = [
        ("ip_patent_applications", {"id": "child-app"}),
        ("ip_patent_applications", {"id": "parent-app"}),
        ("ip_patent_priority_details", {"id": "detail"}),
    ]
    copied = replay_fixture_rows(source, destination, roots)
    assert copied[-1] == roots[-1]
    for name in metadata.tables:
        assert _rows(destination, name) == _rows(source, name)
    with pytest.raises(IntegrityError, match="append-only"), destination.begin() as connection:
        connection.execute(sa.text("UPDATE ip_patent_priority_details SET company_id='forged'"))
    tree = ast.parse(
        (Path(__file__).parent / "test_ip_patent_priority_postgres.py").read_text(
            encoding="utf-8-sig"
        )
    )
    refusal = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "assert_fixture_downgrade_refused"
    ]
    assert len(refusal) == 1
    assert ast.unparse(refusal[0].args[3]) == (
        "[('ip_patent_applications', {'id': child['id']}), "
        "('ip_patent_applications', {'id': parent['id']}), "
        "('ip_patent_priority_details', {'id': created.json()['id']})]"
    )


def _evidence_schema(engine):
    class Captured(Exception):
        pass

    definitions = []

    class Capture:
        def get_bind(self):
            return engine

        def add_column(self, *_args):
            pass

        def create_table(self, name, *columns):
            assert name == "ip_patent_evidence_versions"
            definitions.extend(columns)
            raise Captured

    migration = _migration("20260909_0004_patent_prosecution_evidence.py")
    migration.op = Capture()
    with pytest.raises(Captured):
        migration.upgrade()
    names = {"id", "company_id", "application_id", "root_id", "predecessor_id", "edition"}
    selected = [item for item in definitions if isinstance(item, sa.Column) and item.name in names]
    selected.extend(
        item
        for item in definitions
        if item.name
        in {
            "fk_patent_evidence_root",
            "fk_patent_evidence_predecessor",
            "uq_patent_evidence_owner",
            "ck_patent_evidence_lineage",
            "ck_patent_evidence_no_self",
        }
    )
    metadata = sa.MetaData()
    sa.Table("ip_patent_evidence_versions", metadata, *selected)
    metadata.create_all(engine)


def test_declared_initial_self_root_copies_without_waiving_its_real_fk_or_lineage(engines):
    source, destination = engines
    for engine in engines:
        _evidence_schema(engine)
    with source.begin() as connection:
        table = sa.Table("ip_patent_evidence_versions", sa.MetaData(), autoload_with=connection)
        connection.execute(
            table.insert(),
            {
                "id": "edition-1",
                "company_id": "company",
                "application_id": "application",
                "root_id": "edition-1",
                "predecessor_id": None,
                "edition": 1,
            },
        )
        connection.execute(
            table.insert(),
            {
                "id": "edition-2",
                "company_id": "company",
                "application_id": "application",
                "root_id": "edition-1",
                "predecessor_id": "edition-1",
                "edition": 2,
            },
        )
    assert replay_fixture_rows(
        source, destination, [("ip_patent_evidence_versions", {"id": "edition-2"})]
    ) == [
        (
            "ip_patent_evidence_versions",
            {"id": "edition-1", "company_id": "company", "application_id": "application"},
        ),
        ("ip_patent_evidence_versions", {"id": "edition-2"}),
    ]
    assert _rows(source, "ip_patent_evidence_versions") == _rows(
        destination, "ip_patent_evidence_versions"
    )
    with pytest.raises(IntegrityError), destination.begin() as connection:
        connection.execute(sa.text("UPDATE ip_patent_evidence_versions SET root_id='missing'"))
    with pytest.raises(IntegrityError, match="FOREIGN KEY"), destination.begin() as connection:
        connection.execute(
            table.insert(),
            {
                "id": "edition-3",
                "company_id": "company",
                "application_id": "application",
                "root_id": "missing",
                "predecessor_id": "edition-2",
                "edition": 3,
            },
        )


@pytest.mark.parametrize(
    "change",
    [
        {"name": "arbitrary_self_fk"},
        {"referred_table": "other"},
        {"referred_columns": ["root_id", "company_id", "application_id"]},
        {"constrained_columns": ["id", "company_id", "application_id"]},
    ],
)
def test_self_root_exception_rejects_other_fk_metadata(engines, change):
    _evidence_schema(engines[0])
    foreign_key = next(
        row
        for row in sa.inspect(engines[0]).get_foreign_keys("ip_patent_evidence_versions")
        if row["name"] == "fk_patent_evidence_root"
    )
    values = {"id": "root", "root_id": "root", "predecessor_id": None, "edition": 1}
    assert _initial_evidence_self_root("ip_patent_evidence_versions", foreign_key, values)
    assert not _initial_evidence_self_root(
        "ip_patent_evidence_versions", {**foreign_key, **change}, values
    )


@pytest.mark.parametrize(
    "change",
    [
        {"root_id": "other"},
        {"predecessor_id": "old"},
        {"edition": 2},
    ],
)
def test_self_root_exception_rejects_non_initial_identity(engines, change):
    _evidence_schema(engines[0])
    foreign_key = next(
        row
        for row in sa.inspect(engines[0]).get_foreign_keys("ip_patent_evidence_versions")
        if row["name"] == "fk_patent_evidence_root"
    )
    values = {"id": "root", "root_id": "root", "predecessor_id": None, "edition": 1}
    assert not _initial_evidence_self_root(
        "ip_patent_evidence_versions", foreign_key, {**values, **change}
    )


@pytest.mark.parametrize("parents", [{1: 1}, {1: 2, 2: 1}])
def test_arbitrary_row_local_or_multi_row_cycles_still_fail_closed(engines, parents):
    source, destination = engines
    for engine in engines:
        metadata = sa.MetaData()
        sa.Table(
            "fixture_nodes",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "parent_id",
                sa.Integer,
                sa.ForeignKey("fixture_nodes.id", deferrable=True, initially="DEFERRED"),
            ),
        )
        metadata.create_all(engine)
    table = sa.Table("fixture_nodes", sa.MetaData(), autoload_with=source)
    with source.begin() as connection:
        connection.execute(
            table.insert(),
            [{"id": identity, "parent_id": parent} for identity, parent in parents.items()],
        )
    with pytest.raises(AssertionError, match="Cyclic fixture lineage"):
        replay_fixture_rows(source, destination, [("fixture_nodes", {"id": 1})])
    assert _rows(destination, "fixture_nodes") == []


@pytest.mark.parametrize("count,accepted", [(16, True), (17, False)])
def test_fixture_depth_budget_is_unchanged(engines, count, accepted):
    source, destination = engines
    for engine in engines:
        metadata = sa.MetaData()
        sa.Table(
            "fixture_nodes",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("parent_id", sa.Integer, sa.ForeignKey("fixture_nodes.id")),
        )
        metadata.create_all(engine)
    table = sa.Table("fixture_nodes", sa.MetaData(), autoload_with=source)
    with source.begin() as connection:
        for identity in range(1, count + 1):
            connection.execute(table.insert(), {"id": identity, "parent_id": identity - 1 or None})
    if accepted:
        assert (
            len(replay_fixture_rows(source, destination, [("fixture_nodes", {"id": count})]))
            == count
        )
        assert _rows(destination, "fixture_nodes") == _rows(source, "fixture_nodes")
    else:
        with pytest.raises(AssertionError, match="Fixture lineage is unbounded"):
            replay_fixture_rows(source, destination, [("fixture_nodes", {"id": count})])
        assert _rows(destination, "fixture_nodes") == []


@pytest.mark.parametrize("count,accepted", [(64, True), (65, False)])
def test_fixture_row_budget_is_unchanged(engines, count, accepted):
    source, destination = engines
    for engine in engines:
        metadata = sa.MetaData()
        sa.Table("fixture_nodes", metadata, sa.Column("id", sa.Integer, primary_key=True))
        metadata.create_all(engine)
    table = sa.Table("fixture_nodes", sa.MetaData(), autoload_with=source)
    roots = [("fixture_nodes", {"id": identity}) for identity in range(count)]
    with source.begin() as connection:
        connection.execute(table.insert(), [{"id": identity} for identity in range(count)])
    original_roots = deepcopy(roots)
    if accepted:
        assert len(replay_fixture_rows(source, destination, roots)) == count
        assert _rows(destination, "fixture_nodes") == _rows(source, "fixture_nodes")
    else:
        with pytest.raises(AssertionError, match="Fixture lineage is unbounded"):
            replay_fixture_rows(source, destination, roots)
        assert _rows(destination, "fixture_nodes") == []
    assert roots == original_roots
