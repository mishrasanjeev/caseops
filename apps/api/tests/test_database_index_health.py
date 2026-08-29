from __future__ import annotations

import pytest
import sqlalchemy as sa

from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.scripts import check_database_indexes


def test_required_schema_revision_is_derived_from_the_alembic_graph() -> None:
    assert check_database_indexes._required_schema_revision() == "20260829_0001"


def test_health_report_rejects_a_database_behind_the_source_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES ('20260827_0001')")
        )
        monkeypatch.setattr(
            check_database_indexes,
            "_required_schema_revision",
            lambda: "20260827_0002",
        )
        monkeypatch.setattr(check_database_indexes, "_declared_indexes", dict)

        report = check_database_indexes.build_index_health_report(connection)

    assert report["status"] == "failed"
    assert report["required_schema_revision"] == "20260827_0002"
    assert report["schema_revision_mismatch"] == ["20260827_0001"]


def test_live_inspection_finds_and_then_clears_composite_fk_gap() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        connection.execute(
            sa.text(
                "CREATE TABLE parents (id INTEGER NOT NULL, tenant_id INTEGER NOT NULL, "
                "PRIMARY KEY (id, tenant_id))"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE children (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL, "
                "tenant_id INTEGER NOT NULL, FOREIGN KEY(parent_id, tenant_id) "
                "REFERENCES parents(id, tenant_id))"
            )
        )

        gaps = database_foreign_key_gaps(sa.inspect(connection))
        assert [(gap.table_name, gap.columns) for gap in gaps] == [
            ("children", ("parent_id", "tenant_id"))
        ]

        connection.execute(
            sa.text("CREATE INDEX ix_children_fk ON children (tenant_id, parent_id)")
        )
        assert database_foreign_key_gaps(sa.inspect(connection)) == ()


def test_health_report_rejects_an_index_name_with_wrong_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE children (id INTEGER PRIMARY KEY, parent_id INTEGER, "
                "tenant_id INTEGER)"
            )
        )
        connection.execute(
            sa.text("CREATE INDEX ix_children_expected ON children (tenant_id, parent_id)")
        )
        monkeypatch.setattr(
            check_database_indexes,
            "_declared_indexes",
            lambda: {
                "children": {
                    "ix_children_expected": check_database_indexes.DeclaredIndex(
                        columns=("parent_id", "tenant_id"),
                        requires_exact_name=True,
                    )
                }
            },
        )

        report = check_database_indexes.build_index_health_report(connection)

    assert report["status"] == "failed"
    assert report["mismatched_declared_indexes"] == [
        {
            "table_name": "children",
            "index_name": "ix_children_expected",
            "expected_columns": ["parent_id", "tenant_id"],
            "actual_columns": ["tenant_id", "parent_id"],
        }
    ]


def test_health_report_accepts_equivalent_implicit_column_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE children (id INTEGER PRIMARY KEY, parent_id INTEGER, "
                "tenant_id INTEGER)"
            )
        )
        connection.execute(
            sa.text("CREATE INDEX ix_children_covering ON children (parent_id, tenant_id)")
        )
        monkeypatch.setattr(
            check_database_indexes,
            "_declared_indexes",
            lambda: {
                "children": {
                    "ix_children_parent_id": check_database_indexes.DeclaredIndex(
                        columns=("parent_id",),
                        requires_exact_name=False,
                    )
                }
            },
        )

        report = check_database_indexes.build_index_health_report(connection)

    assert report["missing_declared_indexes"] == []
