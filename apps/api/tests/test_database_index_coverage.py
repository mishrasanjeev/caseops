from __future__ import annotations

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    Table,
    UniqueConstraint,
)

from caseops_api.db.base import Base
from caseops_api.db.index_coverage import (
    columns_cover,
    ensure_foreign_key_indexes,
    foreign_key_index_name,
)


def test_index_prefix_coverage_requires_every_foreign_key_column() -> None:
    assert columns_cover(("company_id", "matter_id", "created_at"), ("matter_id", "company_id"))
    assert not columns_cover(("company_id",), ("company_id", "matter_id"))
    assert not columns_cover(("created_at", "company_id", "matter_id"), ("company_id", "matter_id"))


def test_metadata_coverage_adds_only_missing_foreign_key_indexes() -> None:
    metadata = MetaData()
    Table(
        "parents",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("tenant_id", Integer),
        UniqueConstraint("id", "tenant_id"),
    )
    children = Table(
        "children",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("tenant_id", Integer, nullable=False),
        Column("parent_id", Integer, nullable=False),
        ForeignKeyConstraint(["parent_id", "tenant_id"], ["parents.id", "parents.tenant_id"]),
    )

    created = ensure_foreign_key_indexes(metadata)

    assert created == (foreign_key_index_name("children", ("parent_id", "tenant_id")),)
    assert {index.name for index in children.indexes} == set(created)
    assert ensure_foreign_key_indexes(metadata) == ()
    assert len(created[0]) <= 63


def test_caseops_metadata_has_complete_foreign_key_index_coverage() -> None:
    assert ensure_foreign_key_indexes(Base.metadata) == ()
    assert any(
        index.name.startswith("ix_fk_model_runs_")
        and {column.name for column in index.expressions[:2]} == {"ip_docket_id", "company_id"}
        for index in Base.metadata.tables["model_runs"].indexes
    )
