"""IPLF-030B/UJ-04: bounded export reads, not worker or source-snapshot proof."""

import hashlib
import json
import os
import re
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi import HTTPException
from psycopg import sql as pg_sql
from sqlalchemy import delete, event, func, insert, select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    IpDocketRecord,
    IpTrademarkParticularVersion,
    TrademarkApplication,
    TrademarkRepresentation,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.schemas.ip_portfolio import IpPortfolioFilters
from caseops_api.services import ip_portfolio as portfolio
from caseops_api.services.session_context import SessionContext
from tests.sql_observation import is_read_only_select
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload
from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture
from tests.test_ip_recipient_renewal_content_20261014 import _bootstrap_foreign
from tests.test_ip_renewal_tracker_20261015 import _clock
from tests.test_ip_tracker_retained_scale_postgres_20261017 import _fixture as _retained_fixture

pytestmark = pytest.mark.postgres
COLUMNS = ["mark", "application_date", "renewal_due_date"]


# Reuse the exact catalog projection previously executed by the owned PG17
# diagnostic, now on the same live case connection as the measured query.
_PROVENANCE_INDEX_CATALOG_SQL = (
    "\nSELECT json_build_object('database',current_database(),'user',current_user,'s"
    "chema',current_schema(),'transactionReadOnly',current_setting('transaction_rea"
    "d_only'),'defaultReadOnly',current_setting('default_transaction_read_only'),'v"
    "ersion',(SELECT version_num FROM alembic_version),'systemIdentifier',(SELECT s"
    "ystem_identifier::text FROM pg_control_system()),'indexState',(SELECT row_to_j"
    "son(q)FROM(\n    SELECT c.relkind, t.relname AS owner, tn.nspname AS owner_sche"
    "ma,\n           am.amname AS method, i.indisvalid, i.indisready, i.indisunique,"
    "\n           i.indexprs IS NULL AS expression_free,\n           pg_get_expr(i.in"
    "dpred, i.indrelid) AS predicate,\n           i.indnkeyatts = i.indnatts AS no_i"
    "ncludes,\n           ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALI"
    "TY k(attnum, pos)\n                 JOIN pg_attribute a ON a.attrelid = i.indre"
    "lid AND a.attnum = k.attnum\n                 ORDER BY k.pos) AS columns,\n     "
    "      (SELECT bool_and(opc.opcdefault AND i.indcollation[k] = a.attcollation\n "
    "                           AND i.indoption[k] = 0)\n            FROM generate_s"
    "eries(0, i.indnkeyatts - 1) k\n            JOIN pg_attribute a ON a.attrelid = "
    "i.indrelid AND a.attnum = i.indkey[k]\n            JOIN pg_opclass opc ON opc.o"
    "id = i.indclass[k]) AS standard_keys,\n           current_schema() AS schema\n  "
    "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace\n    LEFT JOIN "
    "pg_index i ON i.indexrelid = c.oid\n    LEFT JOIN pg_class t ON t.oid = i.indre"
    "lid\n    LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace\n    LEFT JOIN pg_"
    "am am ON am.oid = c.relam\n    WHERE n.nspname = current_schema() AND c.relname"
    " = 'ix_audit_events_source_proof_seek'\n)q),'typedIndexState',(SELECT row_to_js"
    "on(q)FROM(\n    SELECT c.relkind, t.relname AS owner, tn.nspname AS owner_schem"
    "a,\n           am.amname AS method, i.indisvalid, i.indisready, i.indisunique,\n"
    "           i.indexprs IS NULL AS expression_free,\n           pg_get_expr(i.ind"
    "pred, i.indrelid) AS predicate,\n           i.indnkeyatts = i.indnatts AS no_in"
    "cludes,\n           ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALIT"
    "Y k(attnum, pos)\n                 JOIN pg_attribute a ON a.attrelid = i.indrel"
    "id AND a.attnum = k.attnum\n                 ORDER BY k.pos) AS columns,\n      "
    "     (SELECT bool_and(opc.opcdefault AND i.indcollation[k] = a.attcollation\n  "
    "                          AND i.indoption[k] = 0)\n            FROM generate_se"
    "ries(0, i.indnkeyatts - 1) k\n            JOIN pg_attribute a ON a.attrelid = i"
    ".indrelid AND a.attnum = i.indkey[k]\n            JOIN pg_opclass opc ON opc.oi"
    "d = i.indclass[k]) AS standard_keys,\n           current_schema() AS schema\n   "
    " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace\n    LEFT JOIN p"
    "g_index i ON i.indexrelid = c.oid\n    LEFT JOIN pg_class t ON t.oid = i.indrel"
    "id\n    LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace\n    LEFT JOIN pg_a"
    "m am ON am.oid = c.relam\n    WHERE n.nspname = current_schema() AND c.relname "
    "= 'ix_audit_events_typed_source_proof_seek'\n)q),'indexDefinitions',(SELECT jso"
    "n_agg(json_build_object('name',c.relname,'valid',i.indisvalid,'ready',i.indisr"
    "eady,'definition',pg_get_indexdef(c.oid)))FROM pg_index i JOIN pg_class c ON c"
    ".oid=i.indexrelid WHERE i.indrelid='audit_events'::regclass),'keyDetails',(SEL"
    "ECT json_agg(json_build_object('position',k,'column',a.attname,'opclass',opc.o"
    "pcname,'defaultOpclass',opc.opcdefault,'collation',co.collname,'indoption',i.i"
    "ndoption[k]))FROM pg_class c JOIN pg_index i ON i.indexrelid=c.oid CROSS JOIN "
    "generate_series(0,i.indnkeyatts-1)k JOIN pg_attribute a ON a.attrelid=i.indrel"
    "id AND a.attnum=i.indkey[k] JOIN pg_opclass opc ON opc.oid=i.indclass[k] LEFT "
    "JOIN pg_collation co ON co.oid=i.indcollation[k] WHERE c.relname='ix_audit_eve"
    "nts_source_proof_seek'),'typedKeyDetails',(SELECT json_agg(json_build_object('"
    "position',k,'column',a.attname,'opclass',opc.opcname,'defaultOpclass',opc.opcd"
    "efault,'collation',co.collname,'indoption',i.indoption[k]))FROM pg_class c JOI"
    "N pg_index i ON i.indexrelid=c.oid CROSS JOIN generate_series(0,i.indnkeyatts-"
    "1)k JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=i.indkey[k] JOIN"
    " pg_opclass opc ON opc.oid=i.indclass[k] LEFT JOIN pg_collation co ON co.oid=i"
    ".indcollation[k] WHERE c.relname='ix_audit_events_typed_source_proof_seek'),'a"
    "uditStats',(SELECT json_build_object('estimatedRows',reltuples::bigint,'pages'"
    ",relpages)FROM pg_class WHERE oid='audit_events'::regclass))\n"
)


def _context(session, actor):
    return SessionContext(
        company=session.get(Company, actor["company"]["id"]),
        membership=session.get(CompanyMembership, actor["membership"]["id"]),
        user=session.get(User, actor["user"]["id"]),
    )


def _imported(client, monkeypatch, *, count=3):
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = _actor(client)
    prefix = f"Export projection {uuid4().hex}"
    committed = _commit(
        client,
        actor,
        _upload(
            client,
            actor,
            ["Trademark", "Application Date", "Renewal Date"],
            [[f"{prefix} {index:03d}", "2020-01-15", "2028-03-15"] for index in range(count)],
        ),
    )
    assert committed["job"]["committed_rows"] == count
    ids = [row["created_docket_id"] for row in committed["rows"]]
    assert len(set(ids)) == count and all(ids)
    return actor, IpPortfolioFilters(query=prefix), ids


@contextmanager
def _observe():
    records = []
    engine = get_engine()

    def before(connection, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        clause = getattr(compiled, "statement", None)
        limit_clause = getattr(clause, "_limit_clause", None)
        limit_name = getattr(compiled, "bind_names", {}).get(limit_clause)
        bound = getattr(context, "compiled_parameters", [])
        records.append({
            "statement": statement,
            "parameters": parameters,
            "read_only": is_read_only_select(clause),
            "limit": bound[0].get(limit_name) if bound and limit_name else None,
        })

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield records
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _nodes(child)


def _node_work(node):
    return (node.get("Actual Rows", 0) + sum(
        value for key, value in node.items() if key.startswith("Rows Removed ")
    )) * node.get("Actual Loops", 1)


def _provenance_work(node, *, owner=None):
    # Bitmap Index Scan children omit Relation Name; charge them to the actual
    # owning heap relation rather than silently dropping their index work.
    owner = node.get("Relation Name", owner)
    children = [
        (child, _provenance_work(
            child, owner=None if child.get("Parent Relationship") in {"SubPlan", "InitPlan"}
            else owner,
        )) for child in node.get("Plans", [])
    ]
    # A separate expression subplan does not make an unrelated outer join part
    # of the proof. Intermediate nodes *inside* a proof branch do count.
    attributable = owner in {"audit_events", "ip_import_rows"} or any(
        proof and child.get("Parent Relationship") not in {"SubPlan", "InitPlan"}
        for child, (_work, proof) in children
    )
    return (
        (_node_work(node) if attributable else 0)
        + sum(work for _child, (work, _proof) in children),
        attributable,
    )


def _audit_relation_buffers(node, *, covered=False):
    """Count each Audit relation's inclusive buffer totals once, never per loop."""
    audit = node.get("Relation Name") == "audit_events"
    nodes = []
    total = 0
    if audit and not covered:
        keys = ("Shared Hit Blocks", "Shared Read Blocks",
                "Local Hit Blocks", "Local Read Blocks")
        values = {key: node.get(key, 0) for key in keys}
        assert all(type(value) is int and value >= 0 for value in values.values())
        assert node.get("Actual Loops", 0) == 0 or any(key in node for key in keys)
        total = sum(values.values())
        nodes.append({"node_type": node["Node Type"], "accesses": total,
                      "actual_loops": node.get("Actual Loops", 0), **values})
    for child in node.get("Plans", []):
        observed = _audit_relation_buffers(child, covered=covered or audit)
        total += observed["accesses"]
        nodes.extend(observed["nodes"])
    return {
        "accesses": total,
        "nodes": nodes,
        "counter_scope": (
            "inclusive Audit relation buffers; no loop multiplication or child duplication"
        ),
    }


def _audit_buffer_budget_exceeded(observed, bound):
    assert type(bound) is int and bound > 0
    return observed["accesses"] > bound


def _assert_audit_buffer_counter_contract():
    leaf = {"Node Type": "Index Only Scan", "Relation Name": "audit_events",
            "Actual Loops": 999, "Shared Hit Blocks": 7, "Shared Read Blocks": 3}
    assert _audit_relation_buffers(leaf)["accesses"] == 10
    bitmap = {"Node Type": "Bitmap Heap Scan", "Relation Name": "audit_events",
              "Actual Loops": 2, "Shared Hit Blocks": 11, "Shared Read Blocks": 2,
              "Plans": [{"Node Type": "Bitmap Index Scan", "Shared Hit Blocks": 5,
                         "Shared Read Blocks": 1}]}
    assert _audit_relation_buffers(bitmap)["accesses"] == 13
    unrelated = {"Node Type": "Nested Loop", "Shared Hit Blocks": 50_000,
                 "Plans": [leaf, {"Node Type": "Index Scan",
                                   "Relation Name": "companies", "Shared Hit Blocks": 40_000}]}
    assert _audit_relation_buffers(unrelated)["accesses"] == 10
    separate = {"Node Type": "Result", "Plans": [leaf, {
        "Node Type": "Index Scan", "Relation Name": "audit_events",
        "Actual Loops": 1, "Shared Hit Blocks": 4, "Local Hit Blocks": 2}]}
    assert _audit_relation_buffers(separate)["accesses"] == 16


def _generic_plan(connection, record, entry, *, index):
    """Explain an actual server PREPARE under force_generic_plan, with safe literals."""
    parameters = record["parameters"]
    assert isinstance(parameters, dict)
    assert not re.search(r"%%\([A-Za-z0-9_]+\)s", record["statement"])
    order = []

    def positional(match):
        name = match.group(1)
        if name not in order:
            order.append(name)
        return f"${order.index(name) + 1}"

    statement = re.sub(r"%\(([A-Za-z0-9_]+)\)s", positional, record["statement"])
    statement = statement.replace("%%", "%")
    assert set(order) == set(parameters)
    name = f"caseops_export_generic_{index}"
    entry["prepared_sql"] = statement
    entry["prepared_parameter_order"] = order
    entry["prepared_name"] = name
    driver = connection.connection.driver_connection
    with driver.cursor() as cursor:
        cursor.execute("SELECT name FROM pg_prepared_statements", prepare=False)
        existing = {row[0] for row in cursor.fetchall()}
        assert name not in existing
        prepare = pg_sql.SQL("PREPARE {} AS ").format(pg_sql.Identifier(name)) + pg_sql.SQL(
            statement
        )
        cursor.execute(prepare, prepare=False)
        failure = None
        try:
            execute = pg_sql.SQL(
                "EXECUTE {}"
            ).format(pg_sql.Identifier(name))
            if order:
                execute += pg_sql.SQL(" ({})").format(
                    pg_sql.SQL(", ").join(pg_sql.Literal(parameters[key]) for key in order)
                )
            cursor.execute(execute, prepare=False)
            actual_rows = cursor.fetchall()
            expected_rows = [tuple(row) for row in connection.exec_driver_sql(
                record["statement"], parameters
            ).all()]
            entry["prepared_result_observation"] = {
                "observed_rows": len(actual_rows), "expected_rows": len(expected_rows),
                "observed_sha256": hashlib.sha256(json.dumps(
                    actual_rows, sort_keys=True, separators=(",", ":"), default=str,
                ).encode()).hexdigest(),
                "expected_sha256": hashlib.sha256(json.dumps(
                    expected_rows, sort_keys=True, separators=(",", ":"), default=str,
                ).encode()).hexdigest(),
                "complete_tuple_equality": actual_rows == expected_rows,
            }
            assert actual_rows == expected_rows
            cursor.execute(
                pg_sql.SQL("EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) ") + execute,
                prepare=False,
            )
            observed = cursor.fetchone()
            entry["plan"] = observed[0]
            entry["plan_state"] = "observed"
            cursor.execute(
                "SELECT statement, parameter_types::text[], generic_plans, custom_plans "
                "FROM pg_prepared_statements WHERE name = %s",
                (name,), prepare=False,
            )
            state = cursor.fetchone()
            entry["prepared_observation"] = {
                "statement": state[0], "parameter_types": state[1],
                "generic_plans": state[2], "custom_plans": state[3],
            }
            assert state[0].endswith(statement) and len(state[1]) == len(order)
            assert state[2] >= 2 and state[3] == 0
            return entry["plan"]
        except BaseException as error:
            failure = error
            entry["prepared_failure_class"] = type(error).__name__
            raise
        finally:
            try:
                cursor.execute(
                    pg_sql.SQL("DEALLOCATE {}").format(pg_sql.Identifier(name)), prepare=False
                )
            except BaseException as error:
                entry["prepared_cleanup_failure_class"] = type(error).__name__
                if failure is None:
                    raise


def _plans(records, *, directory, candidate_bound, audit_buffer_bound=None):
    problems = []
    profiles = {"default": [], "adverse": [], "generic": []}
    catalogs = {}
    sort_disabled_estimates = []
    differential_failure = None
    bound = 4 * candidate_bound + 16
    try:
        for profile, plans in profiles.items():
            with get_engine().begin() as connection:
                assert connection.dialect.name == "postgresql"
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                if profile == "adverse":
                    connection.exec_driver_sql("SET LOCAL enable_hashjoin = off")
                    connection.exec_driver_sql("SET LOCAL enable_mergejoin = off")
                if profile == "generic":
                    connection.exec_driver_sql("SET LOCAL plan_cache_mode = force_generic_plan")
                catalog = connection.exec_driver_sql(_PROVENANCE_INDEX_CATALOG_SQL).scalar_one()
                catalogs[profile] = catalog
                assert catalog["transactionReadOnly"] == "on"
                assert catalog["database"] == connection.engine.url.database
                for index, record in enumerate(records):
                    sql = record["statement"]
                    assert record["read_only"], record
                    entry = {**record, "profile": profile, "plan_state": "not_observed"}
                    plans.append(entry)
                    if profile == "generic":
                        plan = _generic_plan(connection, record, entry, index=index)
                    else:
                        plan = connection.exec_driver_sql(
                            "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + sql,
                            record["parameters"],
                        ).scalar_one()
                        entry.update(plan=plan, plan_state="observed")
                    nodes = list(_nodes(plan[0]["Plan"]))
                    # Preserve the original relation-only oracle separately.
                    relation_work = sum(
                        (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0)
                         + node.get("Rows Removed by Index Recheck", 0))
                        * node.get("Actual Loops", 1) for node in nodes
                        if node.get("Relation Name") in {"audit_events", "ip_import_rows"}
                    )
                    provenance_work, _proof = _provenance_work(plan[0]["Plan"])
                    audit_buffers = _audit_relation_buffers(plan[0]["Plan"])
                    intermediates = [
                        {"node_type": node["Node Type"], "cte": node.get("CTE Name"),
                         "subplan": node.get("Subplan Name"), "work": _node_work(node)}
                        for node in nodes if "Relation Name" not in node
                    ]
                    materialized_proof = [node for node in intermediates
                                          if node["cte"] == "ip_date_proof"
                                          or node["subplan"] == "CTE ip_date_proof"]
                    entry["work"] = {
                        "bound": bound, "relation": relation_work,
                        "audit_relation_buffers": audit_buffers,
                        "audit_buffer_bound": audit_buffer_bound,
                        "proof_subplans_and_owned_bitmap": provenance_work,
                        "materialized_proof_nodes": materialized_proof,
                        "whole_query_intermediate_nodes": intermediates,
                        "all_nodes_retained": len(nodes),
                        "bound_scope": "provenance; not a whole-query work guarantee",
                    }
                    if len(sql.encode()) > 65_536:
                        problems.append("SQL exceeds the existing 64KiB source-fact bound")
                    if any(sql.lower().count(f"from {table}") > 2
                           for table in ("audit_events", "ip_import_rows")):
                        problems.append("Source-proof bodies exceed the existing two-body bound")
                    if audit_buffer_bound is not None and _audit_buffer_budget_exceeded(
                        audit_buffers, audit_buffer_bound
                    ):
                        problems.append(
                            "Audit physical buffer accesses exceed the independent seek budget"
                        )
                    if relation_work > bound or provenance_work > bound:
                        problems.append("Provenance work exceeds the existing candidate bound")
                    if any(node["work"] > bound for node in materialized_proof):
                        problems.append("Materialized proof exceeds the existing candidate bound")
        # Diagnostic only: discourage sort to determine index eligibility. These
        # estimates do not execute the query or replace any actual-plan oracle.
        try:
            with get_engine().begin() as connection:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql("SET LOCAL enable_sort = off")
                catalogs["sort_disabled_estimate"] = connection.exec_driver_sql(
                    _PROVENANCE_INDEX_CATALOG_SQL
                ).scalar_one()
                for record in records:
                    assert record["read_only"], record
                    entry = {
                        **record, "profile": "sort_disabled_estimate",
                        "plan_state": "not_observed", "acceptance_evidence": False,
                        "analyze": False,
                    }
                    sort_disabled_estimates.append(entry)
                    plan = connection.exec_driver_sql(
                        "EXPLAIN (SETTINGS, FORMAT JSON) " + record["statement"],
                        record["parameters"],
                    ).scalar_one()
                    entry.update(plan=plan, plan_state="estimated_not_executed")
        except BaseException as error:
            differential_failure = {"class": type(error).__name__}
    finally:
        # Keep the original full default plans even on a bound failure, and
        # retain the separate adverse plans in the same per-shard CI artifact.
        destinations = [directory]
        if evidence := os.environ.get("CASEOPS_POSTGRES_QUERY_EVIDENCE_DIR"):
            target = Path(evidence) / directory.name
            target.mkdir(parents=True, exist_ok=True)
            destinations.append(target)
        for destination in destinations:
            for profile, plans in profiles.items():
                suffix = "" if profile == "default" else f"-{profile}"
                with (destination / f"export-projection{suffix}-plans.json").open(
                    "x", encoding="utf-8"
                ) as stream:
                    json.dump(plans, stream, indent=2, default=str)
            with (destination / "export-projection-same-case-index-catalog.json").open(
                "x", encoding="utf-8"
            ) as stream:
                json.dump(catalogs, stream, indent=2, default=str)
            with (destination / "export-projection-sort-disabled-estimates.json").open(
                "x", encoding="utf-8"
            ) as stream:
                json.dump({
                    "acceptance_evidence": False, "analyze": False,
                    "failure": differential_failure, "plans": sort_disabled_estimates,
                }, stream, indent=2, default=str)
    assert all(len(plans) == len(records) for plans in profiles.values())
    assert not problems, problems
    assert differential_failure is None, differential_failure


def _unexpected(*args, **kwargs):
    raise AssertionError("Export invoked unrelated full-row hydration or list statistics")


def test_manifest_matches_public_order_and_exact_truncation_without_hydration(
    isolated_postgres_client, monkeypatch,
):
    actor, filters, _ids = _imported(isolated_postgres_client, monkeypatch)
    with get_session_factory()() as session:
        context = _context(session, actor)
        applications = list(session.scalars(
            select(TrademarkApplication).where(
                TrademarkApplication.company_id == context.company.id
            ).order_by(TrademarkApplication.id)
        ))
        tied = datetime(2027, 1, 1, tzinfo=UTC)
        for application in applications:
            application.updated_at = tied
        applications[0].updated_at = tied + timedelta(days=1)
        session.commit()
        context = _context(session, actor)
        first = portfolio.list_ip_portfolio(session, context=context, filters=filters, limit=2)
        second = portfolio.list_ip_portfolio(
            session, context=context, filters=filters, limit=2, cursor=first.next_cursor
        )
        expected = [(row.application_id, row.updated_at) for row in first.rows + second.rows]
        assert [item[0] for item in expected] == [
            applications[0].id, applications[2].id, applications[1].id,
        ]
        monkeypatch.setattr(portfolio, "_portfolio_rows", _unexpected)
        monkeypatch.setattr(portfolio, "_portfolio_counts", _unexpected)
        for limit in (1, 2, 3, 4, 50_000):
            with _observe() as observed:
                manifest, truncated = portfolio.portfolio_export_manifest(
                    session, context=context, filters=filters, row_limit=limit
                )
            assert manifest == expected[:limit]
            assert truncated is (len(expected) > limit)
            assert len(observed) == 1 and observed[0]["read_only"]
            sql = observed[0]["statement"].lower()
            assert "count(" not in sql and "trademark_representations" not in sql
            assert observed[0]["limit"] == limit + 1


def test_minimal_page_preserves_dates_manual_clear_and_missing_provenance(
    isolated_postgres_client, monkeypatch,
):
    client = isolated_postgres_client
    actor, filters, ids = _imported(client, monkeypatch)
    changed = client.patch(
        f"/api/ip/dockets/{ids[1]}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "application_date": "2028-02-29",
            "renewal_due_date": None,
            "reason": "Export current manual-date precedence control",
        },
    )
    assert changed.status_code == 200, changed.text
    with get_session_factory()() as session:
        version = session.scalar(select(IpTrademarkParticularVersion).where(
            IpTrademarkParticularVersion.docket_id == ids[2],
            IpTrademarkParticularVersion.company_id == actor["company"]["id"],
            IpTrademarkParticularVersion.version == 1,
        ))
        data = deepcopy(version.representation_json)
        data["portfolio_import"]["source_row_id"] = str(uuid4())
        version.representation_json = data
        session.commit()
        context = _context(session, actor)
        public = portfolio.list_ip_portfolio(session, context=context, filters=filters)
        expected = {row.docket_id: row for row in public.rows}
        assert expected[ids[0]].source_application_state == "imported_unverified"
        assert expected[ids[1]].source_application_state == "manual"
        assert expected[ids[1]].source_renewal_due_on is None
        assert expected[ids[2]].source_application_state == "missing"
        rows, cursor = portfolio.portfolio_export_page(
            session, context=context, filters=filters, columns=COLUMNS, limit=200
        )
        assert cursor is None and len(rows) == 3
        assert all(isinstance(row, portfolio.PortfolioExportDateRow) for row in rows)
        assert [(row.application_id, row.updated_at, row.asset_title, row.docket_title,
                 row.source_application_on, row.source_renewal_due_on) for row in rows] == [
            (row.application_id, row.updated_at, row.asset_title, row.docket_title,
             row.source_application_on, row.source_renewal_due_on) for row in public.rows
        ]
        assert expected[ids[0]].source_application_on == date(2020, 1, 15)
        assert expected[ids[1]].source_application_on == date(2028, 2, 29)
        assert expected[ids[2]].source_renewal_due_on is None


def test_minimal_page_query_count_is_page_bounded_and_ignores_retained_history(
    isolated_postgres_client, monkeypatch, tmp_path,
):
    # Literal counterexamples exercise the supplemental observer independently
    # of the real ordinary/adverse plans that follow.
    assert _provenance_work({
        "Node Type": "Bitmap Heap Scan", "Relation Name": "audit_events",
        "Actual Rows": 2, "Actual Loops": 3,
        "Plans": [{"Node Type": "Bitmap Index Scan", "Actual Rows": 5, "Actual Loops": 3}],
    })[0] == 21
    assert _provenance_work({
        "Node Type": "Nested Loop", "Actual Rows": 1, "Actual Loops": 2,
        "Rows Removed by Join Filter": 4,
        "Plans": [{"Node Type": "Index Scan", "Relation Name": "audit_events",
                   "Actual Rows": 1, "Actual Loops": 2}],
    })[0] == 12
    assert _provenance_work({
        "Node Type": "Nested Loop", "Actual Rows": 1, "Actual Loops": 2,
        "Rows Removed by Join Filter": 99,
        "Plans": [{"Node Type": "Index Scan", "Relation Name": "audit_events",
                   "Parent Relationship": "SubPlan", "Actual Rows": 2, "Actual Loops": 3}],
    })[0] == 6
    assert _provenance_work({
        "Node Type": "Result", "Actual Rows": 2, "Actual Loops": 3,
        "Plans": [{"Node Type": "Index Scan", "Relation Name": "ip_import_rows",
                   "Actual Rows": 2, "Actual Loops": 3}],
    })[0] == 12
    actor, filters, _ids = _imported(isolated_postgres_client, monkeypatch, count=201)
    with get_session_factory()() as session:
        context = _context(session, actor)
        application = session.scalar(select(TrademarkApplication).where(
            TrademarkApplication.company_id == context.company.id
        ))
        application_id = application.id
        company_id = context.company.id
        last_version = session.scalar(select(func.max(TrademarkRepresentation.version)).where(
            TrademarkRepresentation.company_id == company_id,
            TrademarkRepresentation.application_id == application_id,
        )) or 0
        session.add_all([
            TrademarkRepresentation(
                company_id=company_id, application_id=application_id,
                version=last_version + index + 1,
                representation_kind="word", content_sha256="a" * 64,
                metadata_json={"retained": "x" * 1024},
            )
            for index in range(501)
        ])
        session.commit()
        context = _context(session, actor)
        monkeypatch.setattr(portfolio, "_portfolio_rows", _unexpected)
        monkeypatch.setattr(portfolio, "_portfolio_counts", _unexpected)
        for limit in (1, 51, 200):
            with _observe() as observed:
                rows, cursor = portfolio.portfolio_export_page(
                    session, context=context, filters=filters, columns=COLUMNS, limit=limit
                )
            assert len(rows) == limit and cursor
            assert len(observed) == 2 and all(row["read_only"] for row in observed)
            assert all("trademark_representations" not in row["statement"] for row in observed)
        with _observe() as continuation:
            last, next_cursor = portfolio.portfolio_export_page(
                session, context=context, filters=filters, columns=COLUMNS, limit=200, cursor=cursor
            )
        assert len(last) == 1 and next_cursor is None
        assert len(continuation) == 2
        assert not {row.application_id for row in rows} & {row.application_id for row in last}
        with _observe() as mark_only:
            marked, _cursor = portfolio.portfolio_export_page(
                session, context=context, filters=filters, columns=["mark"], limit=51
            )
        assert len(marked) == 51 and len(mark_only) == 1
        _plans(observed + continuation + mark_only, directory=tmp_path, candidate_bound=201)


def test_rich_export_rows_and_cursor_equal_complete_public_rows_without_counts(
    isolated_postgres_client, monkeypatch,
):
    client = isolated_postgres_client
    headers, _docket, application = _rich_portfolio_fixture(client)
    identity = client.get("/api/auth/me", headers=headers)
    assert identity.status_code == 200, identity.text
    actor = identity.json()
    with get_session_factory()() as session:
        context = _context(session, actor)
        filters = IpPortfolioFilters()
        public = portfolio.list_ip_portfolio(session, context=context, filters=filters, limit=1)
        assert public.counts.total == 1 and public.rows[0].application_id == application["id"]
        monkeypatch.setattr(portfolio, "_portfolio_counts", _unexpected)
        for columns in (["representation", "provenance", "deadlines"], []):
            rows, cursor = portfolio.portfolio_export_page(
                session, context=context, filters=filters, columns=columns, limit=1
            )
            assert cursor == public.next_cursor
            assert [row.model_dump(mode="json") for row in rows] == [
                row.model_dump(mode="json") for row in public.rows
            ]


def test_manifest_and_page_reauthorize_restricted_rows_and_tenant_scope(
    isolated_postgres_client, monkeypatch,
):
    client = isolated_postgres_client
    actor, filters, ids = _imported(client, monkeypatch)
    foreign = _bootstrap_foreign(client)
    with get_session_factory()() as session:
        context = _context(session, actor)
        before, _truncated = portfolio.portfolio_export_manifest(
            session, context=context, filters=filters, row_limit=50_000
        )
        assert len(before) == 3
        with get_session_factory()() as writer:
            restricted = writer.get(IpDocketRecord, ids[0])
            assert restricted.company_id == context.company.id
            restricted.restricted = True
            writer.commit()
        manifest, truncated = portfolio.portfolio_export_manifest(
            session, context=context, filters=filters, row_limit=50_000
        )
        rows, cursor = portfolio.portfolio_export_page(
            session, context=context, filters=filters, columns=COLUMNS, limit=200
        )
        assert len(manifest) == len(rows) == 2 and not truncated and cursor is None
        assert [row.application_id for row in rows] == [item[0] for item in manifest]
        assert set(item[0] for item in manifest) < set(item[0] for item in before)
        other = _context(session, foreign)
        assert portfolio.portfolio_export_manifest(
            session, context=other, filters=filters, row_limit=1
        ) == ([], False)
        assert portfolio.portfolio_export_page(
            session, context=other, filters=filters, columns=COLUMNS, limit=1
        ) == ([], None)


def test_retained_width_date_category_projection_keeps_existing_work_bounds(
    isolated_postgres_client, monkeypatch, tmp_path,
):
    actor, prefix, target_ids = _retained_fixture(isolated_postgres_client, monkeypatch)
    filters = IpPortfolioFilters(
        query=prefix, application_date_from=date(2020, 1, 1),
        application_date_to=date(2020, 12, 31), renewal_tracker_state=["missing"],
    )
    with get_session_factory()() as session:
        context = _context(session, actor)
        started = perf_counter()
        with _observe() as observed:
            manifest, truncated = portfolio.portfolio_export_manifest(
                session, context=context, filters=filters, row_limit=50_000
            )
            rows, cursor = portfolio.portfolio_export_page(
                session, context=context, filters=filters, columns=COLUMNS, limit=200
            )
        elapsed = perf_counter() - started
        assert len(manifest) == len(rows) == 51 and not truncated and cursor is None
        assert [row.application_id for row in rows] == [item[0] for item in manifest]
        expected_ids = set(session.scalars(select(TrademarkApplication.id).where(
            TrademarkApplication.company_id == context.company.id,
            TrademarkApplication.docket_id.in_(target_ids[:51]),
        )))
        assert set(item[0] for item in manifest) == expected_ids
        assert all(row.source_application_on == date(2020, 1, 15)
                   and row.source_renewal_due_on is None for row in rows)
    # Each scoped selector reads policy once; only the page also hydrates dates.
    assert len(observed) == 5 and all(row["read_only"] for row in observed)
    _plans(observed, directory=tmp_path, candidate_bound=53)
    assert elapsed < 10, f"Projection exceeded the existing visible 10s work budget: {elapsed}"


def test_export_projection_rejects_invalid_bounds_and_cursor(isolated_postgres_client, monkeypatch):
    actor, filters, _ids = _imported(isolated_postgres_client, monkeypatch, count=1)
    with get_session_factory()() as session:
        context = _context(session, actor)
        for limit in (0, 50_001):
            with pytest.raises(HTTPException) as rejected:
                portfolio.portfolio_export_manifest(
                    session, context=context, filters=filters, row_limit=limit
                )
            assert rejected.value.status_code == 400
        for limit in (0, 201):
            with pytest.raises(HTTPException) as rejected:
                portfolio.portfolio_export_page(
                    session, context=context, filters=filters, columns=COLUMNS, limit=limit
                )
            assert rejected.value.status_code == 400
        with pytest.raises(HTTPException) as rejected:
            portfolio.portfolio_export_page(
                session, context=context, filters=filters, columns=COLUMNS,
                limit=1, cursor="not-a-portfolio-cursor",
            )
        assert rejected.value.status_code == 400


def test_typed_proof_prefix_bounds_foreign_same_target_histories(
    isolated_postgres_client, monkeypatch, tmp_path,
):
    client = isolated_postgres_client
    _assert_audit_buffer_counter_contract()
    # Fixed contract for 201 seeks in this <=53k-row, six-text-key fixture:
    # 16 pages/seek permits a conservative six-level descent, metadata/VM,
    # leaf/heap boundary visits and slack; 64 extra pages cover fixed overhead.
    # This is independent of measured work, not a general index-height claim.
    audit_buffer_bound = 16 * 201 + 64
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actors = []
    for _ in range(3):
        client.cookies.clear()
        actors.append(_actor(client, bootstrapper=_bootstrap_foreign))
    by_company = {actor["company"]["id"]: actor for actor in actors}
    assert len(by_company) == 3
    with get_session_factory()() as session:
        ordered_companies = list(session.scalars(
            select(Company.id).where(Company.id.in_(by_company)).order_by(Company.id)
        ))
    assert len(ordered_companies) == 3 and set(ordered_companies) == set(by_company)
    lower, owner, upper = [by_company[key] for key in ordered_companies]
    company_id = owner["company"]["id"]
    assert ordered_companies.index(company_id) == 1
    client.cookies.clear()
    prefix = f"Typed history bound {uuid4().hex}"
    committed = _commit(client, owner, _upload(
        client, owner, ["Trademark", "Application Date", "Renewal Date"],
        [[f"{prefix} {n:03d}", "2020-01-15", "2028-03-15"] for n in range(201)],
    ))
    assert committed["job"]["committed_rows"] == 201
    docket_ids = [row["created_docket_id"] for row in committed["rows"]]
    assert len(docket_ids) == len(set(docket_ids)) == 201 and all(docket_ids)
    filters = IpPortfolioFilters(query=prefix)
    with get_session_factory()() as session:
        versions = list(session.scalars(
            select(IpTrademarkParticularVersion).where(
                IpTrademarkParticularVersion.company_id == company_id,
                IpTrademarkParticularVersion.docket_id.in_(docket_ids),
                IpTrademarkParticularVersion.version == 1,
            )
        ))
        assert len(versions) == 201
        source_pairs = [(version.docket_id, version.representation_json[
            "portfolio_import"]["source_row_id"]) for version in versions]
        source_ids = [source for _docket, source in source_pairs]
        assert len(set(source_ids)) == 201 and all(len(value) == 36 for value in source_ids)
        original_versions = {version.id: deepcopy(version.representation_json)
                             for version in versions}
        application_ids = set(session.scalars(
            select(TrademarkApplication.id).where(TrademarkApplication.company_id == company_id)
        ))
        assert len(application_ids) == 201
        histories = []
        for docket_id, source in source_pairs:
            exact = dict(actor_type="system", ip_docket_id=docket_id,
                         action="ip_docket.source_materialized",
                         target_type="ip_import_row", target_id=source)
            for foreign in (lower, upper):
                histories.extend(dict(exact, company_id=foreign["company"]["id"])
                                 for _ in range(64))
            histories.extend(dict(exact, company_id=company_id, ip_docket_id=None)
                             for _ in range(64))
            histories.extend(dict(exact, company_id=company_id, target_id=None)
                             for _ in range(64))
            for wrong_type in ("a_import_row", "z_import_row"):
                histories.append(dict(exact, company_id=company_id, target_type=wrong_type))
            for wrong_source in (source[:-1], source + "~"):
                histories.append(dict(exact, company_id=company_id, target_id=wrong_source))
        assert len(histories) == 52_260
        history_insert = insert(AuditEvent)
        session.execute(history_insert, histories)
        session.commit()
        monkeypatch.setattr(portfolio, "_portfolio_rows", _unexpected)
        monkeypatch.setattr(portfolio, "_portfolio_counts", _unexpected)
        for phase, present in (("positive", True), ("missing-owned-proof", False)):
            if not present:
                removal = delete(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "ip_docket.source_materialized",
                    AuditEvent.target_type == "ip_import_row",
                    AuditEvent.target_id.in_(source_ids),
                    AuditEvent.ip_docket_id.in_(docket_ids),
                )
                session.execute(removal)
                session.commit()
                session.expire_all()
            current_versions = {version.id: deepcopy(version.representation_json)
                                for version in session.scalars(
                                    select(IpTrademarkParticularVersion).where(
                                        IpTrademarkParticularVersion.company_id == company_id,
                                        IpTrademarkParticularVersion.docket_id.in_(docket_ids),
                                        IpTrademarkParticularVersion.version == 1,
                                    )
                                )}
            assert current_versions == original_versions
            context = _context(session, owner)
            for limit in (1, 51, 200):
                with _observe() as observed:
                    rows, cursor = portfolio.portfolio_export_page(
                        session, context=context, filters=filters, columns=COLUMNS, limit=limit
                    )
                assert len(rows) == limit and cursor
                assert len(observed) == 2 and all(row["read_only"] for row in observed)
                assert all("trademark_representations" not in row["statement"]
                           for row in observed)
            with _observe() as continuation:
                last, next_cursor = portfolio.portfolio_export_page(
                    session, context=context, filters=filters, columns=COLUMNS,
                    limit=200, cursor=cursor,
                )
            assert len(last) == 1 and next_cursor is None and len(continuation) == 2
            assert not {row.application_id for row in rows} & {row.application_id for row in last}
            assert {row.application_id for row in [*rows, *last]} == application_ids
            for row in [*rows, *last]:
                assert row.source_application_on == (date(2020, 1, 15) if present else None)
                assert row.source_renewal_due_on == (date(2028, 3, 15) if present else None)
            with _observe() as mark_only:
                marked, _cursor = portfolio.portfolio_export_page(
                    session, context=context, filters=filters, columns=["mark"], limit=51
                )
            assert len(marked) == 51 and len(mark_only) == 1
            destination = tmp_path / (tmp_path.name + "-" + phase)
            destination.mkdir()
            _plans(observed + continuation + mark_only,
                   directory=destination, candidate_bound=201,
                   audit_buffer_bound=audit_buffer_bound)
