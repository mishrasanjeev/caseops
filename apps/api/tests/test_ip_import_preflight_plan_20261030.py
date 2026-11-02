"""IPLF-032/UJ-02/NFT-005: actual default-plan work, not result cardinality.

The fixture owns a template0 database and never clones application tenant data.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BulkImportJob,
    Company,
    CompanyMembership,
    IpDocketRecord,
    User,
)
from caseops_api.db.session import clear_engine_cache, get_session_factory
from caseops_api.services import ip_imports
from caseops_api.services.session_context import SessionContext
from tests.fixtures_postgres_client import temporary_http_database
from tests.sql_observation import is_read_only_select
from tests.test_ip_portfolio_spec_20261013 import _actor, _upload
from tests.test_ip_recipient_renewal_content_20261014 import _bootstrap_foreign

pytestmark = pytest.mark.postgres
N = 1000
BATCH = 500
NOISE_DOCKETS_PER_TENANT = 6000
EXACT_RECEIPTS = 64
NOISE_RECEIPTS = 32
NEAR_MISSES = 16
PROVENANCE_INDEX = "ix_audit_events_source_provenance"
TABLES = ("audit_events", "ip_docket_records")
PROVENANCE_COLUMNS = ("company_id", "action", "target_type", "target_id", "ip_docket_id")
RAW_BOUND = 4 * N + 16
LOOP_BOUND = N + 8
TOTAL_WORK_BOUND = 24 * N + 128
BUFFER_BOUND = 32 * N + 256


class Evidence:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.emit("started", expected_candidates=N)

    def emit(self, kind, **fields):
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": kind, **fields}, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def retain(self, name, value):
        with (self.directory / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        self.emit("artifact", name=name)


@pytest.fixture
def preflight_evidence(request, tmp_path, record_property):
    journal = os.environ.get("CASEOPS_TEST_RESULT_JOURNAL")
    configured = os.environ.get("CASEOPS_FINALIZER_EVIDENCE_DIR")
    root = Path(configured) if configured else Path(journal).parent if journal else tmp_path
    digest = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    evidence = Evidence(root / "ip-preflight-plans" / f"{digest}-{uuid4().hex}")
    record_property("ip_preflight_plan_evidence", str(evidence.directory))
    evidence.emit("identity", nodeid=request.node.nodeid)
    yield evidence
    # This is not a pytest completion verdict; retained_results owns phase results.
    evidence.emit("evidence_fixture_teardown")


@pytest.fixture
def http_pg_engine(monkeypatch, preflight_evidence):
    """Override only storage for the existing isolated_postgres_client fixture."""
    source = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    assert source.get_backend_name() == "postgresql"
    with temporary_http_database(source) as engine:
        assert engine.url.database != source.database
        url = engine.url.render_as_string(hide_password=False)
        monkeypatch.setenv("CASEOPS_ENV", "local")
        monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
        monkeypatch.setenv("CASEOPS_TEST_POSTGRES_URL", url)
        get_settings.cache_clear()
        clear_engine_cache()
        root = Path(__file__).resolve().parents[1]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        try:
            preflight_evidence.emit("migration_started", database=engine.url.database,
                                    origin="template0; no application database clone")
            command.upgrade(config, "head")
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT count(*) FROM companies")) == 0
                revisions = list(connection.scalars(
                    text("SELECT version_num FROM alembic_version"),
                ))
            preflight_evidence.emit("migration_complete", revisions=revisions)
            yield engine
        finally:
            clear_engine_cache()
            get_settings.cache_clear()
    preflight_evidence.emit("database_dropped", database=engine.url.database)


def _context(session, actor):
    context = SessionContext(
        company=session.get(Company, actor["company"]["id"]),
        membership=session.get(CompanyMembership, actor["membership"]["id"]),
        user=session.get(User, actor["user"]["id"]),
    )
    assert context.company and context.membership and context.user
    return context


def _insert(session, table, rows):
    batch = []
    count = 0
    for row in rows:
        batch.append(row)
        if len(batch) == BATCH:
            session.execute(table.insert(), batch)
            count += len(batch)
            batch.clear()
    if batch:
        session.execute(table.insert(), batch)
        count += len(batch)
    return count


def _docket(actor, docket_id, number):
    return {
        "id": docket_id, "company_id": actor["company"]["id"],
        "created_by_membership_id": actor["membership"]["id"],
        "record_type": "trademark", "title": f"Physical plan fixture {number}",
        "status": "draft", "is_active": True,
    }


def _receipt(actor, row_id, docket_id, ordinal, *, action=None, target_type="ip_import_row"):
    return {
        "id": str(uuid4()), "company_id": actor["company"]["id"],
        "actor_type": "membership", "actor_membership_id": actor["membership"]["id"],
        "action": action or ip_imports.IMPORT_MATERIALIZATION_ACTION,
        "target_type": target_type, "target_id": row_id, "ip_docket_id": docket_id,
        "result": "success",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=ordinal),
    }


def _snapshot(session):
    relations = list(session.execute(text("""
        SELECT c.relname, c.reltuples, c.relpages,
               (SELECT count(*) FROM pg_statistic s WHERE s.starelid=c.oid) AS statistic_rows
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=current_schema() AND c.relname IN ('audit_events','ip_docket_records')
        ORDER BY c.relname
    """)).mappings())
    indexes = list(session.execute(text("""
        SELECT t.relname AS table_name, i.relname AS index_name,
               x.indisvalid, x.indisready, x.indisprimary, pg_get_indexdef(i.oid) AS definition,
               ARRAY(SELECT a.attname FROM unnest(x.indkey) WITH ORDINALITY AS k(attnum,ord)
                     JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.attnum
                     WHERE k.ord <= x.indnkeyatts ORDER BY k.ord) AS key_columns
        FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid
        JOIN pg_class t ON t.oid=x.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname=current_schema() AND t.relname IN ('audit_events','ip_docket_records')
        ORDER BY t.relname,i.relname
    """)).mappings())
    settings = list(session.execute(text("""
        SELECT name, setting, reset_val, boot_val, source, pending_restart
        FROM pg_settings
        WHERE name LIKE 'enable_%' OR name IN (
            'plan_cache_mode','work_mem','random_page_cost','seq_page_cost',
            'effective_cache_size','default_statistics_target','jit',
            'max_parallel_workers_per_gather','statement_timeout','lock_timeout',
            'idle_in_transaction_session_timeout','autovacuum','track_counts')
        ORDER BY name
    """)).mappings())
    counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
              for model in (AuditEvent, IpDocketRecord)}
    return {"relations": [dict(row) for row in relations],
            "indexes": [dict(row) for row in indexes],
            "settings": [dict(row) for row in settings], "counts": counts,
            "server_version": session.scalar(text("SHOW server_version"))}


@contextmanager
def _capture(session):
    statements, loaded = [], []
    connection = session.connection()

    def before(conn, cursor, sql, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        clause = getattr(compiled, "statement", None)
        statements.append({
            "sql": sql, "parameters": parameters, "executemany": executemany,
            "read_only": is_read_only_select(clause), "complete": False,
            "selected_columns": len(list(getattr(clause, "selected_columns", ()))),
        })
        context.ip_preflight_plan_record = statements[-1]

    def after(conn, cursor, sql, parameters, context, executemany):
        context.ip_preflight_plan_record["complete"] = True

    def hydrated(observed, instance):
        loaded.append(type(instance).__name__)

    event.listen(connection, "before_cursor_execute", before)
    event.listen(connection, "after_cursor_execute", after)
    event.listen(session, "loaded_as_persistent", hydrated)
    try:
        yield statements, loaded
    finally:
        event.remove(session, "loaded_as_persistent", hydrated)
        event.remove(connection, "after_cursor_execute", after)
        event.remove(connection, "before_cursor_execute", before)


def _nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _nodes(child)


def _work(node):
    loops = node.get("Actual Loops", 0)
    fields = ("Actual Rows", "Rows Removed by Filter", "Rows Removed by Join Filter",
              "Rows Removed by Index Recheck")
    # EXPLAIN rounds per-loop averages. +1 per reported field is conservative,
    # including a rounded zero; a missing counter is not a reported zero.
    upper = loops * sum(math.ceil(node[field] + 1) for field in fields if field in node)
    return {"tuple_upper": upper, "loops": loops,
            "work_upper": upper + loops, "heap_fetches": node.get("Heap Fetches", 0)}


def _has_column(name, source):
    return bool(re.search(rf"(?<![a-z_]){re.escape(name)}(?![a-z_])", source))


def _assess(document, catalog):
    nodes = list(_nodes(document[0]["Plan"]))
    active = [node for node in nodes if node.get("Actual Loops", 0) > 0]
    problems = []
    measurements = {}
    indexes = {row["index_name"]: row for row in catalog["indexes"]}
    provenance = indexes.get(PROVENANCE_INDEX)
    if not provenance or not provenance["indisvalid"] or not provenance["indisready"]:
        problems.append("Migrated provenance index is absent, invalid or not ready")
    elif tuple(provenance["key_columns"]) != PROVENANCE_COLUMNS:
        problems.append("Provenance index does not retain the exact five-key order")
    for table in TABLES:
        leaves = [node for node in active if node.get("Relation Name") == table]
        index_nodes = [node for node in active
                       if indexes.get(node.get("Index Name"), {}).get("table_name") == table]
        # Bitmap Index Scan has no Relation Name. Charge it in addition to its heap.
        charged = leaves + [node for node in index_nodes if node not in leaves]
        raw = sum(_work(node)["tuple_upper"] for node in charged)
        loops = sum(_work(node)["loops"] for node in charged)
        measurements[table] = {"tuple_upper": raw, "loops": loops,
                               "heap_fetches": sum(_work(n)["heap_fetches"] for n in charged)}
        if measurements[table]["heap_fetches"] > 2 * N + 16:
            problems.append(f"{table}: index-only heap-fetch bound exceeded")
        if not leaves or not index_nodes:
            problems.append(f"{table}: missing executed indexed access")
        if raw > RAW_BOUND or loops > LOOP_BOUND:
            problems.append(f"{table}: raw/loop bound exceeded: {measurements[table]}")
        if any(node["Node Type"] not in {"Index Scan", "Index Only Scan", "Bitmap Heap Scan"}
               for node in leaves):
            problems.append(f"{table}: executed broad or unaccounted relation scan")
        for node in index_nodes:
            index = indexes[node["Index Name"]]
            if not index["indisvalid"] or not index["indisready"]:
                problems.append(f"{table}: executed an unhealthy index")
            condition = node.get("Index Cond", "")
            if table == "audit_events":
                if node["Index Name"] != PROVENANCE_INDEX or any(
                    not _has_column(column, condition) for column in PROVENANCE_COLUMNS
                ):
                    problems.append("Audit lookup lacks the complete five-key Index Cond")
            elif not _has_column("id", condition) or not _has_column(
                "company_id", condition + " " + node.get("Filter", ""),
            ):
                problems.append("Docket lookup lost its identity or tenant condition")
    total = sum(_work(node)["work_upper"] for node in active)
    root = document[0]["Plan"]
    shared = root.get("Shared Hit Blocks", 0) + root.get("Shared Read Blocks", 0)
    if "Shared Hit Blocks" not in root or "Shared Read Blocks" not in root:
        problems.append("Missing BUFFERS evidence")
    if total > TOTAL_WORK_BOUND:
        problems.append(f"Total executor tuple/startup work {total} exceeds {TOTAL_WORK_BOUND}")
    if shared > BUFFER_BOUND:
        problems.append(f"Inclusive shared buffer work {shared} exceeds {BUFFER_BOUND}")
    if root.get("Temp Read Blocks", 0) or root.get("Temp Written Blocks", 0):
        problems.append("Scalar candidate query spilled to temporary storage")
    return {"relations": measurements, "total_work_upper": total,
            "shared_blocks": shared, "execution_ms": document[0].get("Execution Time"),
            "bounds": {"raw_per_relation": RAW_BOUND, "loops_per_relation": LOOP_BOUND,
                       "heap_fetches_per_relation": 2 * N + 16,
                       "all_node_work": TOTAL_WORK_BOUND, "shared_blocks": BUFFER_BOUND},
            "problems": problems}


def _history(session, actor, foreign, rows, noise_rows):
    candidates = [ip_imports._import_docket_id(row.id) for row in rows]
    own = [ip_imports._import_docket_id(row["id"]) for row in noise_rows[0]]
    other = [ip_imports._import_docket_id(row["id"]) for row in noise_rows[1]]
    own += [str(uuid4()) for _ in range(NOISE_DOCKETS_PER_TENANT - N)]
    other += [str(uuid4()) for _ in range(NOISE_DOCKETS_PER_TENANT - N)]
    for owner, ids in ((actor, candidates), (actor, own), (foreign, other)):
        _insert(session, IpDocketRecord.__table__,
                (_docket(owner, docket_id, i) for i, docket_id in enumerate(ids)))

    def receipts():
        for owner, ids, sources in ((actor, own, noise_rows[0]), (foreign, other, noise_rows[1])):
            for i, source in enumerate(sources):
                for version in range(NOISE_RECEIPTS):
                    yield _receipt(owner, source["id"], ids[i], i * NOISE_RECEIPTS + version)
            for i, docket_id in enumerate(ids):
                yield _receipt(owner, docket_id, docket_id, i, action="ip_docket.updated",
                               target_type="ip_docket_record")
        for i, row in enumerate(rows):
            # Real FK parents, same-tenant memberships and retained source rows.
            # These are synthetic receipts/reservations, not proof of materialization.
            for version in range(NEAR_MISSES):
                yield _receipt(actor, row.id, own[i], version)
                yield _receipt(actor, row.id, candidates[i], version,
                               action="ip_import.row_reviewed")
            if i % 4 != 0:
                for version in range(EXACT_RECEIPTS):
                    yield _receipt(actor, row.id, candidates[i], version)

    audit_count = _insert(session, AuditEvent.__table__, receipts())
    assert audit_count == 156000
    return {row.id: i % 4 != 0 for i, row in enumerate(rows)}


@pytest.mark.parametrize("statistics", ["fresh", "stale", "analyzed"],
                         ids=["fresh-no-stats", "stale-64-row-stats", "after-analyze"])
def test_thousand_candidate_preflight_has_bounded_default_physical_plan(
    isolated_postgres_client, statistics, preflight_evidence,
):
    """IP-PFP-01..03: entire admitted inventory, deep duplicates and exact SQL."""
    client = isolated_postgres_client
    actor = _actor(client)
    with TestClient(client.app, headers={
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }) as foreign_client:
        foreign = _bootstrap_foreign(foreign_client)
        foreign["headers"] = {
            "Authorization": f"Bearer {foreign['access_token']}",
            "X-CaseOps-Automated-Test": "no-paid-providers",
        }
        foreign_preview = _upload(
            foreign_client, foreign, ["Trademark", "Jurisdiction", "Office"],
            [[f"Foreign history {i}", "IN", "IP India"] for i in range(N)],
        )
    preview = _upload(client, actor, ["Trademark", "Applicant", "Class"],
                      [["Shared bounded plan mark", f"Distinct plan owner {i}", "9,36"]
                       for i in range(N)])
    noise = _upload(client, actor, ["Trademark"], [[f"Own history {i}"] for i in range(N)])
    for admitted in (preview, noise, foreign_preview):
        assert admitted["job"]["valid_rows"] == N and len(admitted["rows"]) == N
    evidence = preflight_evidence
    evidence.retain("source-identity.json", {
        "ip_imports_sha256": hashlib.sha256(Path(ip_imports.__file__).read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "statistics": statistics, "job_id": preview["job"]["id"],
        "company_id": actor["company"]["id"], "foreign_company_id": foreign["company"]["id"],
    })
    with get_session_factory()() as session:
        assert session.get_bind().dialect.name == "postgresql"
        # Exclude automatic ANALYZE races without changing a setting. Only these
        # two disposable tables are locked; this is not a latency benchmark.
        session.execute(text(
            "LOCK TABLE audit_events, ip_docket_records IN SHARE UPDATE EXCLUSIVE MODE"
        ))
        context = _context(session, actor)
        job = session.get(BulkImportJob, preview["job"]["id"])
        rows = ip_imports._rows(session, job)
        assert len(rows) == N
        assert [row.id for row in rows] == [row["id"] for row in preview["rows"]]
        assert all(row.commit_status == "pending" and row.validation_status == "valid"
                   and row.company_id == actor["company"]["id"] for row in rows)
        initial = _snapshot(session)
        evidence.retain("initial-catalog.json", initial)
        overridden = [row for row in initial["settings"]
                      if (row["name"].startswith("enable_") and row["setting"] != row["boot_val"])
                      or (row["name"] == "plan_cache_mode" and row["setting"] != "auto")
                      or (row["source"] in {"session", "client"} and
                          (row["name"].startswith("enable_") or row["name"] in {
                              "plan_cache_mode", "random_page_cost", "seq_page_cost",
                              "default_statistics_target", "work_mem", "effective_cache_size",
                          }))]
        assert not overridden, (
            "Default-plan acceptance cannot inherit planner overrides", overridden,
        )
        assert all(row["statistic_rows"] == 0 for row in initial["relations"]), (
            "Fresh fixture already has column statistics; do not relabel it fresh", initial
        )
        for owner in (actor, foreign):
            for i in range(32):
                docket_id = str(uuid4())
                session.execute(IpDocketRecord.__table__.insert(), [_docket(owner, docket_id, i)])
                session.execute(AuditEvent.__table__.insert(), [_receipt(
                    owner, docket_id, docket_id, i, action="ip_docket.updated",
                    target_type="ip_docket_record",
                )])
        if statistics == "stale":
            session.execute(text("ANALYZE audit_events"))
            session.execute(text("ANALYZE ip_docket_records"))
        baseline = _snapshot(session)
        evidence.retain("baseline-catalog.json", baseline)
        expected = _history(session, actor, foreign, rows,
                            (noise["rows"], foreign_preview["rows"]))
        if statistics == "analyzed":
            session.execute(text("ANALYZE audit_events"))
            session.execute(text("ANALYZE ip_docket_records"))
        measured = _snapshot(session)
        evidence.retain("measured-catalog.json", measured)
        assert measured["settings"] == baseline["settings"] == initial["settings"]
        assert measured["indexes"] == initial["indexes"]
        for table, delta in (("ip_docket_records", 13000), ("audit_events", 156000)):
            assert measured["counts"][table] - baseline["counts"][table] == delta
        if statistics == "fresh":
            assert all(row["statistic_rows"] == 0 for row in measured["relations"])
        elif statistics == "stale":
            assert measured["relations"] == baseline["relations"]
            assert all(0 < row["reltuples"] < measured["counts"][row["relname"]] / 10
                       for row in measured["relations"])
        else:
            assert all(row["statistic_rows"] > 0 and
                       abs(row["reltuples"] - measured["counts"][row["relname"]]) <=
                       measured["counts"][row["relname"]] / 10
                       for row in measured["relations"])

        with _capture(session) as (statements, loaded):
            facts = ip_imports._preflight_materialized_dockets(session, context=context, rows=rows)
        evidence.retain("captured-sql.json", {"statements": statements, "orm_loads": loaded})
        assert len(statements) == 1 and statements[0]["complete"]
        statement = statements[0]
        assert statement["read_only"] and not statement["executemany"]
        assert statement["selected_columns"] == 2 and not loaded
        # Explain precisely the driver SQL/binds, not a hand-written or recompiled query.
        evidence.emit("explain_started", candidates=N, statistics=statistics)
        document = session.connection().exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + statement["sql"],
            statement["parameters"],
        ).scalar_one()
        evidence.retain("explain-analyze-buffers.json", document)
        assessment = _assess(document, measured)
        evidence.retain("physical-work.json", assessment)
        evidence.emit("explain_retained", candidates=N, **assessment)
        assert facts == expected and len(facts) == N
        assert sum(facts.values()) == 750
        assert document[0]["Plan"]["Actual Rows"] == N
        assert not assessment["problems"], assessment
        evidence.emit("acceptance_assertions_completed", statistics=statistics)
        # Dispose all synthetic history with the private database; no source writes,
        # materialization claim/outcome changes, or cross-commit facts are exercised.
