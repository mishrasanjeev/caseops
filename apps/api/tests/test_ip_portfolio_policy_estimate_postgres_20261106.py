"""Portfolio reads stay linear once IP walls and grants exist.

2026-11-06: every test-legal ``GET /api/ip/portfolio`` and ``/families`` read
hit the 60 s statement timeout. The IP policy tested each per-docket wall and
grant seek as ``(scalar subquery) IS NULL``, which PostgreSQL estimates at
0.5%. Once the policy tables held rows (test-legal retains every run's revoked
walls and grants), the planner expected about one visible docket and joined
``trademark_applications`` and ``ip_assets`` by a sequential scan per docket.
That is quadratic in tenant width. The policy now uses ``[NOT] EXISTS`` with
the same seeks. This test reproduces the adverse statistics and rejects the
quadratic plan shape for every captured portfolio read.
"""

import json
from datetime import UTC, datetime
from time import perf_counter

import pytest
from sqlalchemy import event, text

from caseops_api.db.session import get_engine
from tests.sql_observation import is_read_only_select
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload
from tests.test_ip_renewal_tracker_20261015 import _clock

pytestmark = pytest.mark.postgres

WIDTH = 1000
REVOKED_POLICY_ROWS = 400
REPEATED_TABLES = {"ip_docket_records", "trademark_applications", "ip_assets"}


def _nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _nodes(child)


def _seed(client):
    actor = _actor(client)
    columns = ["Trademark", "Application Number", "Application Date", "Renewal Date"]
    for start in range(0, WIDTH, 500):
        rows = [
            [f"IP policy estimate {index:04d}", "", "2020-01-15", ""]
            for index in range(start, min(start + 500, WIDTH))
        ]
        job = _commit(
            client, actor, _upload(client, actor, columns, rows), key=f"policy-estimate-{start:04d}"
        )
        assert job["job"]["status"] == "committed"
        assert job["job"]["committed_rows"] == len(rows)
    return actor


def _retain_revoked_policy_rows(connection):
    # Revoked rows never match the policy, but they give the walls and grants
    # tables the statistics a long-lived tenant has.
    company_id, membership_id = connection.execute(
        text(
            "SELECT company_id, id FROM company_memberships "
            "WHERE company_id = (SELECT company_id FROM ip_docket_records LIMIT 1) LIMIT 1"
        )
    ).one()
    for table, subject, extra_column, extra_value in (
        ("ethical_walls", "excluded_membership_id", "", ""),
        ("matter_access_grants", "membership_id", ", access_level", ", 'member'"),
    ):
        connection.execute(
            text(
                f"INSERT INTO {table} (id, company_id, ip_docket_id, {subject}, revoked_at, "
                f"record_version, created_at{extra_column}) "
                f"SELECT gen_random_uuid()::text, CAST(:company AS VARCHAR), id, "
                f"CAST(:membership AS VARCHAR), now(), 1, now()"
                f"{extra_value} FROM ip_docket_records "
                "WHERE company_id = CAST(:company AS VARCHAR) "
                "ORDER BY id LIMIT :rows"
            ),
            {"company": company_id, "membership": membership_id, "rows": REVOKED_POLICY_ROWS},
        )


def _portfolio_rescans(client, monkeypatch, record_property, requests):
    _clock(monkeypatch, datetime(2026, 11, 6, 4, tzinfo=UTC))
    actor = _seed(client)
    engine = get_engine()
    with engine.begin() as connection:
        _retain_revoked_policy_rows(connection)
        connection.exec_driver_sql("ANALYZE")

    captured = []
    active = {"label": None}

    def before(connection, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        if active["label"] and is_read_only_select(getattr(compiled, "statement", None)):
            if "ip_docket_records" in statement and "trademark_applications" in statement:
                captured.append((active["label"], statement, parameters))

    timings = {}
    event.listen(engine, "before_cursor_execute", before)
    try:
        for label, (path, params) in requests.items():
            active["label"] = label
            started = perf_counter()
            response = client.get(path, headers=actor["headers"], params=params)
            timings[label] = round(perf_counter() - started, 3)
            active["label"] = None
            assert response.status_code == 200, response.text
    finally:
        event.remove(engine, "before_cursor_execute", before)
    record_property("portfolio_http_seconds", json.dumps(timings))
    assert {label for label, _, _ in captured} == set(requests)

    rescans, shapes = {}, {}
    with engine.connect() as connection:
        for index, (label, statement, parameters) in enumerate(captured):
            plan = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, FORMAT JSON) " + statement, parameters
            ).scalar_one()[0]["Plan"]
            offending = False
            for node in _nodes(plan):
                if (
                    node["Node Type"] == "Seq Scan"
                    and node.get("Relation Name") in REPEATED_TABLES
                    and node.get("Actual Loops", 1) > 1
                ):
                    rescans[f"{label}-{index}"] = (
                        node["Relation Name"],
                        node["Actual Loops"],
                        node.get("Actual Rows"),
                    )
                    offending = True
            if offending:
                shapes[f"{label}-{index}"] = [
                    (
                        node["Node Type"],
                        node.get("Join Type"),
                        node.get("Relation Name"),
                        node.get("Plan Rows"),
                        node.get("Actual Rows"),
                        node.get("Actual Loops"),
                        (node.get("Filter") or node.get("Join Filter") or "")[:160],
                    )
                    for node in _nodes(plan)
                    if node.get("Actual Loops", 0) <= 1 or node["Node Type"] == "Seq Scan"
                ][:40]
        connection.rollback()
    record_property("portfolio_rescans", json.dumps(rescans))
    record_property("portfolio_rescan_plans", json.dumps(shapes))
    return rescans


def test_portfolio_reads_never_rescan_the_portfolio_per_docket(
    isolated_postgres_client, monkeypatch, record_property
):
    requests = {
        "page": ("/api/ip/portfolio", {"limit": 50}),
        "query": ("/api/ip/portfolio", {"query": "IP policy estimate", "limit": 50}),
        "families": ("/api/ip/portfolio/families", {}),
    }
    rescans = _portfolio_rescans(isolated_postgres_client, monkeypatch, record_property, requests)
    assert rescans == {}
