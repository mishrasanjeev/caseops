"""Structural controls only; these do not execute a native or PG observer."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Integer, column, delete, literal, select, table, text, update
from sqlalchemy.sql.selectable import TextualSelect

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "mobile_v1_readonly_ast", ROOT / "scripts/mobile/local-v1-controls.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_typed_select_and_materialized_with_are_allowed():
    source = table("synthetic_source", column("id"))
    current = (
        select(source.c.id)
        .where(source.c.id == "synthetic-id")
        .limit(1)
        .cte("current")
        .prefix_with("MATERIALIZED")
    )
    statement = select(current.c.id)
    MODULE.require_readonly_statement(statement)


def test_nested_dml_cte_is_refused_before_any_execution():
    source = table("synthetic_source", column("id"))
    removed = (
        delete(source).where(source.c.id == "synthetic-id").returning(source.c.id).cte("removed")
    )
    statement = select(literal(1)).add_cte(removed)
    with pytest.raises(AssertionError, match="V1_TYPED_READONLY_SELECT_REQUIRED"):
        MODULE.require_readonly_statement(statement)


def test_opaque_textual_select_is_refused():
    statement = text("SELECT 1").columns(id=Integer)
    assert isinstance(statement, TextualSelect)
    with pytest.raises(AssertionError, match="V1_TYPED_READONLY_SELECT_REQUIRED"):
        MODULE.require_readonly_statement(statement)


def test_nested_opaque_text_and_top_level_update_are_refused():
    source = table("synthetic_source", column("id"))
    statements = (
        select(source.c.id).where(text("1 = 1")),
        update(source).values(id="synthetic-only"),
    )
    for statement in statements:
        with pytest.raises(AssertionError, match="V1_TYPED_READONLY_SELECT_REQUIRED"):
            MODULE.require_readonly_statement(statement)
