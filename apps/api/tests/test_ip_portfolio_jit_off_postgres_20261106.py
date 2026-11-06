"""Portfolio reads never JIT-compile, even when the server default forces JIT.

2026-11-06: after an autoanalyze, every test-legal ``GET /api/ip/portfolio``
and ``/portfolio/families`` read went from ~1 s to the 60 s statement timeout.
The policy-scoped statements are tens of KB of SQL, and JIT is chosen per
statement from the planner's cost estimate, so crossing ``jit_*_above_cost``
adds compile time to every read. The request engine now disables JIT on its
connections. This test sets the adverse server default (JIT forced for every
statement), replays the exact captured portfolio SQL, and requires a positive
control: the same SQL on a JIT-enabled connection must still compile.
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

FORCED_JIT = {
    "jit": "on",
    "jit_above_cost": "0",
    "jit_inline_above_cost": "0",
    "jit_optimize_above_cost": "0",
}


def _seed(client, monkeypatch):
    _clock(monkeypatch, datetime(2026, 11, 6, 4, tzinfo=UTC))
    actor = _actor(client)
    prefix = "IP JIT portfolio"
    columns = ["Trademark", "Application Number", "Application Date", "Renewal Date"]
    rows = [[f"{prefix} {index:02d}", "", "2020-01-15", ""] for index in range(12)]
    committed = _commit(client, actor, _upload(client, actor, columns, rows), key="jit-off-seed")
    assert committed["job"]["status"] == "committed"
    assert committed["job"]["committed_rows"] == 12
    return actor, prefix


def test_portfolio_reads_do_not_jit_compile_under_forced_server_jit(
    isolated_postgres_client, monkeypatch, record_property
):
    client = isolated_postgres_client
    actor, prefix = _seed(client, monkeypatch)
    engine = get_engine()
    with engine.begin() as connection:
        database = connection.scalar(text("select current_database()"))
        assert database.startswith("caseops_http_")
        for name, value in FORCED_JIT.items():
            connection.exec_driver_sql(f'ALTER DATABASE "{database}" SET {name} = {value}')
        connection.exec_driver_sql("ANALYZE")
    engine.dispose()

    captured = []
    active = {"label": None}

    def before(connection, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        if active["label"] and is_read_only_select(getattr(compiled, "statement", None)):
            if "ip_docket_records" in statement:
                captured.append((active["label"], statement, parameters))

    requests = {
        "portfolio": ("/api/ip/portfolio", {"limit": 50}),
        "query": ("/api/ip/portfolio", {"query": prefix, "limit": 50}),
        "tracker": (
            "/api/ip/portfolio",
            {
                "query": prefix,
                "renewal_tracker_state": "missing",
                "application_date_from": "2020-01-01",
                "application_date_to": "2020-12-31",
                "limit": 50,
            },
        ),
        "families": ("/api/ip/portfolio/families", {}),
    }
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

    jit_free, controls = {}, {}
    with engine.connect() as connection:
        # The adverse database default reaches the session; only the
        # connection option (applied after it) turns JIT off.
        assert connection.exec_driver_sql("SHOW jit_above_cost").scalar_one() == "0"
        assert connection.exec_driver_sql("SHOW jit").scalar_one() == "off"
        for index, (label, statement, parameters) in enumerate(captured):
            plan = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, FORMAT JSON) " + statement, parameters
            ).scalar_one()[0]
            jit_free[f"{label}-{index}"] = plan.get("JIT")
        connection.rollback()
        connection.exec_driver_sql("SET LOCAL jit = on")
        for index, (label, statement, parameters) in enumerate(captured):
            plan = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, FORMAT JSON) " + statement, parameters
            ).scalar_one()[0]
            controls[f"{label}-{index}"] = (plan.get("JIT") or {}).get("Functions", 0)
        connection.rollback()
    record_property("jit_control_functions", json.dumps(controls))
    assert all(value is None for value in jit_free.values()), jit_free
    assert all(functions > 0 for functions in controls.values()), controls


def test_portfolio_export_session_disables_jit_under_forced_server_jit(isolated_postgres_client):
    from time import monotonic

    from caseops_api.services.ip_portfolio_workflow import _export_session

    engine = get_engine()
    with engine.begin() as connection:
        database = connection.scalar(text("select current_database()"))
        assert database.startswith("caseops_http_")
        for name, value in FORCED_JIT.items():
            connection.exec_driver_sql(f'ALTER DATABASE "{database}" SET {name} = {value}')
    engine.dispose()
    with _export_session(monotonic() + 30) as session:
        assert session.execute(text("SHOW jit_above_cost")).scalar_one() == "0"
        assert session.execute(text("SHOW jit")).scalar_one() == "off"
