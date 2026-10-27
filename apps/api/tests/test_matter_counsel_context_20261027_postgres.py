"""Whole HTTP DTO/ACL parity and measured seek work on actual PostgreSQL."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from caseops_api.db.models import MatterOutsideCounselAssignment, OutsideCounselSpendRecord
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.outside_counsel import _matter_context_page_statement
from tests.sql_observation import is_read_only_select
from tests.test_matter_counsel_context_20261027 import (
    exercise_acl,
    exercise_exact_money,
    exercise_pages,
    seed_rows,
    setup_case,
    uid,
)
from tests.test_outside_counsel import _create_matter

pytestmark = pytest.mark.postgres


def test_postgres_matter_counsel_whole_money_dto(isolated_postgres_client):
    exercise_exact_money(isolated_postgres_client)


def test_postgres_matter_counsel_bounded_complete_pages(isolated_postgres_client):
    exercise_pages(isolated_postgres_client)


@pytest.mark.parametrize("boundary", ["restricted", "wall", "team", "foreign", "closed"])
def test_postgres_matter_counsel_current_acl(isolated_postgres_client, boundary):
    exercise_acl(isolated_postgres_client, boundary)


def _nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


@pytest.mark.parametrize("cohort_order", ["visible_first", "competing_first"])
@pytest.mark.parametrize("index_timing", ["before_seed", "after_seed"])
@pytest.mark.parametrize("cost", ["default", "adverse"])
def test_actual_postgres_counsel_plans_bound_candidate_and_join_work(
    isolated_postgres_client,
    index_timing,
    cohort_order,
    cost,
    tmp_path,
):
    # These real, complete plans are retained by the test, rather than inferred
    # from an index declaration. No index/scanner/work budget is waived.
    client = isolated_postgres_client
    case = setup_case(client, count=0)
    indexes = (
        ("matter_outside_counsel_assignments", "ix_oc_assignments_company_matter_id"),
        ("outside_counsel_spend_records", "ix_oc_spend_company_matter_id"),
    )
    physical_keys = (("counsel_read_pages", ("company_id", "matter_id", "record_kind", "max_id")),)
    physical_indexes = (("counsel_read_pages", "ix_counsel_read_pages_matter_id"),)
    engine = get_engine()
    if index_timing == "after_seed":
        with engine.begin() as connection:
            for _table, name in (*indexes, *physical_indexes):
                connection.exec_driver_sql(f'DROP INDEX "{name}"')
            for table, _columns in physical_keys:
                connection.exec_driver_sql(f'ALTER TABLE "{table}" DROP CONSTRAINT "{table}_pkey"')
    other = _create_matter(
        client, case["auth"]["access_token"], title="Other seek data", matter_code="OC-PLAN-OTHER"
    )
    cohorts = [(case["matter"], 160, 10, 10), (other, 640, 1, 2)]
    if cohort_order == "competing_first":
        cohorts.reverse()
    for matter, count, start, stride in cohorts:
        seed_rows(case["auth"], matter, count=count, start=start, stride=stride)
    if index_timing == "after_seed":
        with engine.begin() as connection:
            for table, name in indexes:
                connection.exec_driver_sql(
                    f'CREATE INDEX "{name}" ON "{table}" (company_id, matter_id, id)'
                )
            for table, name in physical_indexes:
                connection.exec_driver_sql(f'CREATE INDEX "{name}" ON "{table}" (matter_id)')
            for table, columns in physical_keys:
                names = ", ".join(f'"{column}"' for column in columns)
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table}" ADD CONSTRAINT "{table}_pkey" PRIMARY KEY ({names})'
                )
    plans = []
    violations = []
    with get_session_factory()() as session:
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        if cost == "adverse":
            session.execute(text("SET LOCAL random_page_cost = 100"))
        for model, after in (
            (MatterOutsideCounselAssignment, uid(800)),
            (OutsideCounselSpendRecord, uid(20800)),
        ):
            statement = _matter_context_page_statement(
                model,
                company_id=case["auth"]["company"]["id"],
                matter_id=case["matter"]["id"],
                after=after,
                limit=25,
            )
            assert is_read_only_select(statement)
            sql = str(
                statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
            payload = session.execute(
                text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
            ).scalar_one()
            nodes = list(_nodes(payload[0]["Plan"]))
            plans.append(payload)
            (
                tmp_path / f"{model.__tablename__}-{index_timing}-{cohort_order}-{cost}.json"
            ).write_text(json.dumps(payload, indent=2))
            assert payload[0]["Plan"]["Actual Rows"] == 26
            # Charge filter/join rejects, loop-weighted work and materialized rows.
            work = sum(
                (
                    node.get("Actual Rows", 0)
                    + node.get("Rows Removed by Filter", 0)
                    + node.get("Rows Removed by Join Filter", 0)
                    + node.get("Rows Removed by Index Recheck", 0)
                )
                * node.get("Actual Loops", 1)
                for node in nodes
            )
            if work > 400:
                violations.append((model.__tablename__, work, payload))
            # This changed serving query must not silently hydrate the800row
            # source/directory tables. Every introduced physical relation AND
            # CTE/Values/sort/join/loop remains in the SAME400work charge above.
            assert {node["Relation Name"] for node in nodes if "Relation Name" in node} <= {
                "counsel_read_pages",
                "counsel_read_page_dirty",
                model.__tablename__,
                "outside_counsel",
                "company_memberships",
                "users",
            }
            assert any(node.get("Relation Name") == "counsel_read_pages" for node in nodes)
            assert not any(
                node.get("Relation Name")
                in {
                    "matter_outside_counsel_assignments",
                    "outside_counsel_spend_records",
                    "outside_counsel",
                    "company_memberships",
                    "users",
                }
                and node.get("Actual Loops", 0) > 0
                for node in nodes
            )
            assert "OFFSET" not in sql
            rows = list(session.execute(statement).mappings())
            offset = 0 if model is MatterOutsideCounselAssignment else 20000
            assert [r["source_payload"]["id"] for r in rows] == [
                uid(offset + n) for n in range(810, 1070, 10)
            ]
        session.rollback()
    assert len(plans) == 2
    assert not violations, json.dumps(violations)
