"""IP18 retained-company width, source-fact SQL work and visible request budget."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from caseops_api.db.session import get_engine
from tests.sql_observation import is_read_only_select
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload
from tests.test_ip_renewal_tracker_20261015 import _clock

pytestmark = pytest.mark.postgres

# The retained readback exposed 1,345 portfolio records, not the private audit
# table's cardinality. Seed that observed width through real import provenance.
OBSERVED_PORTFOLIO_WIDTH = 1345
VISIBLE_BUDGET_SECONDS = 10
SQL_TEXT_BUDGET_BYTES = 65_536


def _save(directory, name, value):
    with (directory / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, default=str)


def _fixture(client, monkeypatch, *, target_last=False):
    now = datetime(2026, 10, 17, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    actor = _actor(client)
    run = uuid4().hex
    prefix = f"IP18 current source {run}"
    due = (now.date() + timedelta(days=60)).isoformat()
    target = [[f"{prefix} missing {index:02d}", "", "2020-01-15", ""] for index in range(51)]
    target += [
        [f"{prefix} outside", "", "2010-01-15", ""],
        [f"{prefix} due", "", "2020-01-15", due],
    ]
    columns = ["Trademark", "Application Number", "Application Date", "Renewal Date"]

    def commit_target():
        result = _commit(
            client, actor, _upload(client, actor, columns, target), key=f"target-{run}"
        )
        assert result["job"]["status"] == "committed"
        assert result["job"]["committed_rows"] == 53
        assert result["job"]["failed_rows"] == 0
        target_ids = [row["created_docket_id"] for row in result["rows"]]
        assert len(target_ids) == len(set(target_ids)) == 53 and all(target_ids)
        return target_ids

    target_ids = None if target_last else commit_target()

    background = []
    for index in range(OBSERVED_PORTFOLIO_WIDTH - 53):
        if index < 1156:
            renewal = ""
        elif index < 1159:
            renewal = (now.date() + timedelta(days=(7, 20, 80)[index - 1156])).isoformat()
        else:
            renewal = (now.date() + timedelta(days=3650)).isoformat()
        background.append(
            [
                f"IP18 retained source {run} {index:04d}",
                f"IP18-{run}-{index:04d}" if index < 1167 else "",
                "2020-01-15",
                renewal,
            ]
        )
    for start in range(0, len(background), 500):
        rows = background[start : start + 500]
        committed = _commit(
            client, actor, _upload(client, actor, columns, rows), key=f"retained-{run}-{start}"
        )
        assert committed["job"]["status"] == "committed"
        assert committed["job"]["committed_rows"] == len(rows)
        assert committed["job"]["failed_rows"] == 0
    if target_last:
        target_ids = commit_target()
    return actor, prefix, target_ids


def _shape(statement, *, read_only):
    if not read_only:
        return None
    lowered = statement.lower()
    if "sum(case" in lowered and "ip_docket_records" in lowered:
        return "counts"
    if (
        "select ip_docket_records.id" in lowered
        and "ip_trademark_particular_versions.id" in lowered
    ):
        return "page"
    if "from ip_import_rows" in lowered and "from audit_events" in lowered:
        return "portfolio_source"
    return None


def _plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


def test_retained_width_tracker_bounds_source_fact_work_and_visible_latency(
    isolated_postgres_client,
    monkeypatch,
    tmp_path,
):
    client = isolated_postgres_client
    actor, prefix, target_ids = _fixture(client, monkeypatch)
    missing_ids = target_ids[:51]
    journal = os.environ.get("CASEOPS_TEST_RESULT_JOURNAL")
    directory = (Path(journal).parent if journal else tmp_path) / "tracker-retained-scale"
    directory.mkdir(exist_ok=False)
    engine = get_engine()
    with engine.begin() as connection:
        assert connection.dialect.name == "postgresql"
        database = connection.scalar(text("select current_database()"))
        assert database.startswith("caseops_http_")
        assert not database.startswith("caseops_http_template_")
        for table in (
            "ip_docket_records",
            "ip_trademark_particular_versions",
            "audit_events",
            "ip_import_rows",
            "trademark_applications",
            "ip_identifiers",
            "ip_portfolio_renewal_series",
            "ip_portfolio_renewal_occurrences",
            "notification_delivery_intents",
            "ip_renewal_terms",
            "ip_deadlines",
        ):
            connection.exec_driver_sql(f"ANALYZE {table}")
        settings = {
            name: connection.exec_driver_sql(f"SHOW {name}").scalar_one()
            for name in (
                "server_version",
                "jit",
                "jit_above_cost",
                "jit_inline_above_cost",
                "jit_optimize_above_cost",
                "max_parallel_workers_per_gather",
            )
        }
    _save(
        directory,
        "fixture.json",
        {
            "portfolio_width": OBSERVED_PORTFOLIO_WIDTH,
            "target_rows": 53,
            "expected_missing_target": 51,
            "width_is_observed_portfolio_proxy_not_private_audit_count": True,
            "source": "Real upload/commit/resume; no forged source audit",
            "settings_unchanged": settings,
        },
    )
    active = {"label": None}
    observed = {}
    all_statements = {}
    statement_counts = {}
    select_counts = {}

    def before(connection, cursor, statement, parameters, context, executemany):
        label = active["label"]
        if label is None:
            return
        compiled = getattr(context, "compiled", None)
        read_only = is_read_only_select(getattr(compiled, "statement", None))
        all_statements.setdefault(label, []).append(
            {"statement": statement, "read_only_select": read_only}
        )
        statement_counts[label] = statement_counts.get(label, 0) + 1
        if read_only:
            select_counts[label] = select_counts.get(label, 0) + 1
        context.tracker_measure_kind = _shape(statement, read_only=read_only)
        if context.tracker_measure_kind:
            context.tracker_measure_started = perf_counter()

    def after(connection, cursor, statement, parameters, context, executemany):
        kind = getattr(context, "tracker_measure_kind", None)
        if active["label"] and kind:
            observed.setdefault(active["label"], []).append(
                {
                    "kind": kind,
                    "statement": statement,
                    "parameters": parameters,
                    "cursor_seconds": perf_counter() - context.tracker_measure_started,
                    "sql_bytes": len(statement.encode()),
                    "audit_proof_bodies": statement.lower().count("from audit_events"),
                    "import_proof_bodies": statement.lower().count("from ip_import_rows"),
                }
            )

    reports = []
    final = None
    filters = {
        "query": prefix,
        "application_date_from": "2020-01-01",
        "application_date_to": "2020-12-31",
        "category": "missing",
        "limit": 50,
    }
    profiles = [
        ("initial", {"limit": 50}),
        ("query", {"query": prefix, "limit": 50}),
        ("from", {"query": prefix, "application_date_from": "2020-01-01", "limit": 50}),
        ("to", {key: value for key, value in filters.items() if key != "category"}),
        ("missing", filters),
    ]
    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        for label, params in profiles:
            active["label"] = label
            started = perf_counter()
            response = client.get(
                "/api/ip/portfolio/renewal-tracker", headers=actor["headers"], params=params
            )
            elapsed = perf_counter() - started
            active["label"] = None
            assert response.status_code == 200, response.text
            body = response.json()
            reports.append(
                {
                    "profile": label,
                    "http_seconds": elapsed,
                    "status": response.status_code,
                    "rows": len(body["rows"]),
                    "counts": body["counts"],
                    "next_cursor_present": bool(body["next_cursor"]),
                }
            )
            _save(directory, f"{label}-request.json", reports[-1])
            if label == "missing":
                final = body
        assert final is not None
        active["label"] = "continuation"
        started = perf_counter()
        response = client.get(
            "/api/ip/portfolio/renewal-tracker",
            headers=actor["headers"],
            params={**filters, "cursor": final["next_cursor"]},
        )
        elapsed = perf_counter() - started
        active["label"] = None
        assert response.status_code == 200, response.text
        continuation = response.json()
        reports.append(
            {
                "profile": "continuation",
                "http_seconds": elapsed,
                "status": response.status_code,
                "rows": len(continuation["rows"]),
                "counts": continuation["counts"],
                "next_cursor_present": bool(continuation["next_cursor"]),
            }
        )

        portfolio_filters = {
            "query": prefix,
            "application_date_from": "2020-01-01",
            "application_date_to": "2020-12-31",
            "renewal_tracker_state": ["missing"],
        }
        columns = ["mark", "application_date", "renewal_due_date"]
        saved = client.post(
            "/api/ip/portfolio/views",
            headers=actor["headers"],
            json={
                "name": "IP18 retained scale dates",
                "filters": portfolio_filters,
                "columns": columns,
            },
        )
        assert saved.status_code == 201, saved.text
        retained = client.get("/api/ip/portfolio/views", headers=actor["headers"])
        assert retained.status_code == 200, retained.text
        view = next(row for row in retained.json()["views"] if row["id"] == saved.json()["id"])
        assert all(view["filters"][key] == value for key, value in portfolio_filters.items())
        assert view["columns"] == columns

        def adjacent_request(label, path, *, params=None, payload=None):
            active["label"] = label
            started = perf_counter()
            try:
                response = (
                    client.post(path, headers=actor["headers"], json=payload)
                    if payload is not None
                    else client.get(path, headers=actor["headers"], params=params)
                )
            finally:
                active["label"] = None
            elapsed = perf_counter() - started
            assert response.status_code == 200, response.text
            body = response.json()
            report = {
                "profile": label,
                "http_seconds": elapsed,
                "status": response.status_code,
                "rows": len(body.get("rows", body.get("families", []))),
                "counts": body.get("counts"),
                "row_count": body.get("row_count"),
                "truncated": body.get("truncated"),
            }
            reports.append(report)
            _save(directory, f"{label}-request.json", report)
            return body

        listed = adjacent_request(
            "portfolio", "/api/ip/portfolio", params={**portfolio_filters, "limit": 50}
        )
        assert len(listed["rows"]) == 50 and listed["next_cursor"]
        continued = adjacent_request(
            "portfolio-continuation",
            "/api/ip/portfolio",
            params={**portfolio_filters, "limit": 50, "cursor": listed["next_cursor"]},
        )
        assert len(continued["rows"]) == 1 and continued["next_cursor"] is None
        assert listed["counts"]["total"] == continued["counts"]["total"] == 51
        assert sorted(row["docket_id"] for row in listed["rows"] + continued["rows"]) == sorted(
            missing_ids
        )
        families = adjacent_request(
            "families",
            "/api/ip/portfolio/families",
            params={"query": prefix, "grouping": "mark", "limit": 100},
        )
        # The family HTTP route accepts the broad query, not dated filters.
        assert len(families["families"]) == 53 and families["next_cursor"] is None
        assert sorted(
            member["docket_id"] for family in families["families"] for member in family["members"]
        ) == sorted(target_ids)
        dated_families = adjacent_request(
            "dated-families",
            "/api/ip/portfolio/families",
            params={**portfolio_filters, "grouping": "mark", "limit": 100},
        )
        assert len(dated_families["families"]) == 51 and dated_families["next_cursor"] is None
        assert sorted(
            member["docket_id"]
            for family in dated_families["families"]
            for member in family["members"]
        ) == sorted(missing_ids)
        bounded_families = adjacent_request(
            "all-five-families",
            "/api/ip/portfolio/families",
            params={
                **portfolio_filters,
                "renewal_due_from": "2026-12-01",
                "renewal_due_to": "2026-12-31",
                "renewal_tracker_state": ["upcoming"],
                "grouping": "mark",
                "limit": 100,
            },
        )
        assert len(bounded_families["families"]) == 1
        assert bounded_families["next_cursor"] is None
        assert [
            member["docket_id"]
            for family in bounded_families["families"]
            for member in family["members"]
        ] == target_ids[-1:]
        preview = adjacent_request(
            "export-preview",
            "/api/ip/portfolio/exports/preview",
            payload={"filters": view["filters"], "columns": view["columns"], "row_limit": 50000},
        )
        assert preview["row_count"] == 51 and preview["truncated"] is False
    finally:
        active["label"] = None
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
        _save(directory, "all-observed-statements.json", observed)
        _save(directory, "all-request-timings.json", reports)
        _save(directory, "all-select-counts.json", select_counts)
        _save(directory, "all-statement-counts.json", statement_counts)
        _save(directory, "all-cursor-statements.json", all_statements)

    plans = {}
    with engine.begin() as connection:
        for label in (
            "initial",
            "missing",
            "continuation",
            "portfolio",
            "portfolio-continuation",
            "dated-families",
            "all-five-families",
            "export-preview",
        ):
            assert observed.get(label), f"No actual source SQL captured for {label}"
            if label in {"initial", "missing", "continuation"}:
                assert [row["kind"] for row in observed[label]] == ["counts", "page"]
            for index, measured in enumerate(observed[label]):
                key = f"{label}-{measured['kind']}-{index}"
                plan = connection.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + measured["statement"],
                    measured["parameters"],
                ).scalar_one()
                _save(directory, f"{key}-plan.json", plan)
                root = plan[0]
                nodes = list(_plan_nodes(root["Plan"]))
                plans[key] = {
                    "planning_ms": root.get("Planning Time"),
                    "execution_ms": root.get("Execution Time"),
                    "jit": root.get("JIT"),
                    "sql_bytes": measured["sql_bytes"],
                    "audit_proof_bodies": measured["audit_proof_bodies"],
                    "import_proof_bodies": measured["import_proof_bodies"],
                    "provenance_rows_examined": sum(
                        (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0))
                        * node.get("Actual Loops", 1)
                        for node in nodes
                        if node.get("Relation Name") in {"audit_events", "ip_import_rows"}
                    ),
                    "candidate_bound": OBSERVED_PORTFOLIO_WIDTH if label == "initial" else 53,
                }
    _save(directory, "measurement-summary.json", {"requests": reports, "plans": plans})

    assert len(final["rows"]) == 50 and final["next_cursor"]
    assert final["counts"] == {
        "upcoming": 1,
        "active": 0,
        "due_today": 0,
        "overdue": 0,
        "missing": 51,
        "failed": 0,
    }
    assert len(continuation["rows"]) == 1 and continuation["next_cursor"] is None
    assert continuation["counts"] == final["counts"]
    rows = final["rows"] + continuation["rows"]
    assert sorted(row["docket_id"] for row in rows) == sorted(missing_ids)
    assert all(
        row["source_application_state"] == "imported_unverified"
        and row["source_renewal_state"] == "missing"
        for row in rows
    )
    problems = []
    for report in reports:
        if report["http_seconds"] >= VISIBLE_BUDGET_SECONDS:
            problems.append(f"{report['profile']} exceeded existing visible10s budget")
        label = report["profile"]
        captured = all_statements.get(label, [])
        if not 0 < statement_counts.get(label, 0) <= 64:
            problems.append(f"{label} exceeded64 total cursor statements or captured no SQL")
        # Export preview deliberately persists an audit event; GET profiles do not.
        if label != "export-preview" and not all(row["read_only_select"] for row in captured):
            problems.append(f"{label} executed untyped or non-read-only SQL: {captured}")
    for key, plan in plans.items():
        if plan["sql_bytes"] > SQL_TEXT_BUDGET_BYTES:
            problems.append(f"{key} SQL text exceeds64KiB work-shape bound")
        if plan["audit_proof_bodies"] > 2 or plan["import_proof_bodies"] > 2:
            problems.append(f"{key} repeats provenance instead of staged source facts")
        if plan["provenance_rows_examined"] > 4 * plan["candidate_bound"] + 16:
            problems.append(f"{key} provenance work exceeds authorized candidate bound")
    assert not problems, "; ".join(problems)
