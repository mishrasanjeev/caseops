"""Complete cross-dialect HTTP contracts and all-relation work accounting."""

import json
import math
from datetime import date

import pytest
from sqlalchemy import func, literal, select, text, union_all
from sqlalchemy.dialects import postgresql

from caseops_api.db.models import MatterTask
from caseops_api.db.session import _proven_read_statement, get_session_factory
from caseops_api.db.statement_clock import StatementUtc
from caseops_api.services import matter_work_queue as queue
from tests.sql_observation import is_read_only_select
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)
from tests.test_matter_work_queue_20261027 import (
    STAMP,
    context_for,
    cursor_rules,
    date_views,
    eligibility,
    employee,
    excludes_ip,
    grant_change,
    lifecycle,
    ownership,
    pagination,
    policy_cursor,
    prebuilt_team,
    retained_role_downgrade,
    setup,
    team,
    temporal_boundary,
    uid,
    whole_response,
)

forbid_unadmitted_network = _forbid_unadmitted_network
pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def explicit_bearer_actor(isolated_postgres_client, monkeypatch):
    """Match the common fixture's CLI isolation; production cookie-first stays intact."""
    client = isolated_postgres_client
    original = client.request

    def request(method, url, **kwargs):
        request_headers = kwargs.get("headers") or {}
        token = request_headers.get("Authorization", "")
        if token.startswith("Bearer "):
            saved = list(client.cookies.jar)
            client.cookies.clear()
            try:
                return original(method, url, **kwargs)
            finally:
                for cookie in saved:
                    client.cookies.jar.set_cookie(cookie)
        return original(method, url, **kwargs)

    monkeypatch.setattr(client, "request", request)


@pytest.mark.parametrize("role", ["owner", "admin", "partner", "member", "paralegal", "viewer"])
def test_postgres_work_queue_whole_response(isolated_postgres_client, role):
    whole_response(isolated_postgres_client, role)


def test_postgres_work_queue_distinct_ownership(isolated_postgres_client):
    ownership(isolated_postgres_client)


@pytest.mark.parametrize(
    "change",
    [
        "actor_removed",
        "owner_removed",
        "team_inactive",
        "membership_inactive",
        "user_inactive",
        "foreign_owner",
    ],
)
def test_postgres_work_queue_current_team_eligibility(isolated_postgres_client, change):
    eligibility(isolated_postgres_client, change)


@pytest.mark.parametrize("reverse", [False, True])
def test_postgres_work_queue_complete_opposite_order_pages(isolated_postgres_client, reverse):
    pagination(isolated_postgres_client, reverse)


def test_postgres_work_queue_calendar_dates(isolated_postgres_client):
    date_views(isolated_postgres_client)


def test_postgres_work_queue_source_lifecycle(isolated_postgres_client):
    lifecycle(isolated_postgres_client)


@pytest.mark.parametrize(
    "boundary", ["wall", "restricted", "owner", "due", "completed", "lifecycle", "foreign_anchor"]
)
def test_postgres_work_queue_current_policy_continuation(isolated_postgres_client, boundary):
    policy_cursor(isolated_postgres_client, boundary)


def test_postgres_work_queue_prebuilt_team_and_wall(isolated_postgres_client):
    prebuilt_team(isolated_postgres_client)


def test_postgres_work_queue_prebuilt_grants(isolated_postgres_client):
    grant_change(isolated_postgres_client)


def test_postgres_work_queue_no_ip_relabel(isolated_postgres_client):
    excludes_ip(isolated_postgres_client)


def test_postgres_work_queue_cursor_contract(isolated_postgres_client):
    cursor_rules(isolated_postgres_client)


def _nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _nodes(child)


def _all_relation_work(plan):
    charges = []
    for node in _nodes(plan[0]["Plan"]):
        # ANALYZE must supply actual counts; an incomplete observer is never 0.
        loops = node["Actual Loops"]
        fields = [
            node["Actual Rows"],
            node.get("Rows Removed by Filter", 0),
            node.get("Rows Removed by Join Filter", 0),
            node.get("Rows Removed by Index Recheck", 0),
        ]
        assert all(
            type(value) in (int, float) and math.isfinite(value) and value >= 0
            for value in [loops, *fields]
        )
        charges.append(sum(fields) * loops)
    return sum(charges)


@pytest.mark.parametrize("index_timing", ["before", "after"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("cost", ["default", "adverse"])
@pytest.mark.parametrize("ownership", ["mine", "team", "unassigned"])
def test_postgres_work_queue_actual_plans_charge_every_relation_and_loop(
    isolated_postgres_client,
    reverse,
    cost,
    ownership,
    index_timing,
    tmp_path,
):
    assert index_timing in {"before", "after"}
    assert cost in {"default", "adverse"}
    case = setup(isolated_postgres_client)
    other = employee(isolated_postgres_client, case["owner"])
    team(isolated_postgres_client, case["owner"], case["actor"], other)
    target = {
        "mine": case["actor"]["membership"]["id"],
        "team": other["membership"]["id"],
        "unassigned": None,
    }[ownership]
    ids = list(range(1, 801))
    if reverse:
        ids.reverse()
    with get_session_factory()() as session:
        if index_timing == "after":
            session.execute(
                text(
                    "ALTER TABLE matter_task_queue_pages DROP CONSTRAINT pk_matter_task_queue_pages"
                )
            )
            session.commit()
        for n in ids:
            session.add(
                MatterTask(
                    id=uid(n),
                    company_id=case["owner"]["company"]["id"],
                    matter_id=case["matter"]["id"],
                    owner_membership_id=target if n <= 160 else case["owner"]["membership"]["id"],
                    title="Retained bounded-plan task",
                    status="todo",
                    priority="medium",
                    due_on=date(2028, 2, 29),
                    created_at=STAMP,
                    updated_at=STAMP,
                )
            )
        session.commit()
        if index_timing == "after":
            session.execute(
                text(
                    "ALTER TABLE matter_task_queue_pages ADD CONSTRAINT pk_matter_task_queue_pages "
                    "PRIMARY KEY (group_id,page_no)"
                )
            )
            session.commit()
    with get_session_factory()() as session:
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        if cost == "adverse":
            session.execute(text("SET LOCAL random_page_cost = 100"))
        statement = queue.work_queue_statement(
            session,
            context=context_for(session, case["actor"]),
            ownership=ownership,
            dates="all",
        ).limit(26)
        assert is_read_only_select(statement)
        sql = str(
            statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        plan = session.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)).scalar_one()
        (
            tmp_path / f"queue-{ownership}-{cost}-reverse-{reverse}-index-{index_timing}.json"
        ).write_text(json.dumps(plan, indent=2))
        assert plan[0]["Plan"]["Actual Rows"] == 26
        work = _all_relation_work(plan)
        assert work <= 400, json.dumps(plan)
        assert "OFFSET" not in sql


def test_postgres_retained_owner_statement_refuses_committed_role_downgrade(
    isolated_postgres_client,
):
    retained_role_downgrade(isolated_postgres_client)


@pytest.mark.parametrize("kind", ["grant", "wall"])
@pytest.mark.parametrize("edge_kind", ["effective", "expiry"])
@pytest.mark.parametrize(
    "delta", [-1, 0, 1], ids=["one-microsecond-before", "exact", "one-microsecond-after"]
)
def test_postgres_policy_typed_temporal_boundaries(
    isolated_postgres_client,
    kind,
    edge_kind,
    delta,
):
    temporal_boundary(isolated_postgres_client, kind, edge_kind, delta)


def test_postgres_statement_clock_is_not_transaction_time(isolated_postgres_client):
    with get_session_factory()() as reader:
        assert reader.get_bind().dialect.name == "postgresql"
        started = reader.scalar(select(func.now()))
        transaction = reader.get_transaction()
        statement = union_all(
            select(StatementUtc().label("clock"), func.now().label("transaction"), literal(1)),
            select(StatementUtc(), func.now(), literal(2)),
            select(StatementUtc(), func.now(), literal(3)),
        )
        assert is_read_only_select(statement) and _proven_read_statement(statement)
        first = reader.execute(statement).all()
        second = reader.execute(statement).all()
        assert reader.get_transaction() is transaction
        assert len(first) == len(second) == 3
        assert {row.clock for row in first} == {first[0].clock}
        assert {row.clock for row in second} == {second[0].clock}
        assert {row.transaction for row in first + second} == {started}
        assert started < first[0].clock < second[0].clock
