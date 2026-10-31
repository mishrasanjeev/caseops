"""Exact provenance parity and bounded seeks with the tenant-only index retained."""

from copy import deepcopy
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from caseops_api.db.models import AuditEvent, IpImportRow
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import ip_portfolio as portfolio
from caseops_api.services.ip_portfolio_dates import current_date_facts
from tests.test_auth_company import auth_headers
from tests.test_ip_portfolio_export_projection_20261026 import (
    COLUMNS,
    _context,
    _imported,
    _observe,
    _plans,
)
from tests.test_ip_provenance_proof_20261028 import (
    _IMPORTED,
    _assert_readers,
    _case,
    _committed,
    _preview,
    _versions,
    real_actor,
)
from tests.test_ip_recipient_renewal_content_20261014 import _bootstrap_foreign
from tests.test_ip_renewal_tracker_20261015 import _clock

_KEY = ["company_id", "action", "target_type", "target_id", "ip_docket_id"]
_FULL = "ix_audit_events_source_provenance"
_SINGLE = "ix_audit_events_company_id"


@pytest.fixture(params=[
    pytest.param("client", id="sqlite"),
    pytest.param("isolated_postgres_client", id="postgres", marks=pytest.mark.postgres),
])
def proof_client(request):
    return request.getfixturevalue(request.param)


def test_full_key_seek_preserves_each_predicate_duplicates_and_missing(proof_client, monkeypatch):
    client = proof_client
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = real_actor(client)
    company_id = actor["company"]["id"]
    labels = (
        "positive", "source-company", "audit-company", "audit-action", "audit-target-type",
        "audit-target-id", "audit-docket", "missing-row", "missing-audit", "duplicates",
        "mixed", "null-target", "null-docket",
    )
    ids = _committed(client, actor, len(labels))
    preview = _preview(client, actor, len(labels))
    staged_ids = [row["id"] for row in preview["rows"]]
    with TestClient(client.app, headers={
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }) as foreign_client:
        foreign = _bootstrap_foreign(foreign_client)
        foreign["headers"] = {
            **auth_headers(str(foreign["access_token"])),
            "X-CaseOps-Automated-Test": "no-paid-providers",
        }
        foreign_row = _preview(foreign_client, foreign, 1)["rows"][0]["id"]
    foreign_company = foreign["company"]["id"]
    with get_session_factory()() as session:
        versions = _versions(session, company_id, ids)
        assert session.get(IpImportRow, foreign_row).company_id == foreign_company
        assert session.scalar(select(AuditEvent.id).where(
            AuditEvent.action == "ip_docket.source_materialized",
            AuditEvent.target_id.in_([*staged_ids, foreign_row]),
        )) is None
        previous = {row.id: tuple(row) for row in session.execute(
            select(AuditEvent.__table__).where(AuditEvent.company_id == company_id)
        )}
        cases = {}
        for label, docket_id, staged_id in zip(labels, ids, staged_ids, strict=True):
            version = versions[docket_id]
            if label == "positive":
                cases[label] = _case(version, True, _IMPORTED)
                continue
            source_id = foreign_row if label == "source-company" else staged_id
            if label == "missing-row":
                source_id = str(uuid4())
                assert session.get(IpImportRow, source_id) is None
            data = deepcopy(version.representation_json)
            data["portfolio_import"]["source_row_id"] = source_id
            version.representation_json = data
            good = {
                "company_id": company_id, "actor_type": "system",
                "actor_membership_id": None, "action": "ip_docket.source_materialized",
                "target_type": "ip_import_row", "target_id": source_id,
                "ip_docket_id": docket_id,
            }
            changed = {
                "audit-company": {"company_id": foreign_company},
                "audit-action": {"action": "ip_docket.source_materialized~"},
                "audit-target-type": {"target_type": "ip_import_row~"},
                "audit-target-id": {"target_id": source_id + "~"},
                "audit-docket": {"ip_docket_id": ids[0]},
                "null-target": {"target_id": None},
                "null-docket": {"ip_docket_id": None},
            }
            if label != "missing-audit":
                session.add(AuditEvent(**{**good, **changed.get(label, {})}))
            if label in {"duplicates", "mixed"}:
                session.add(AuditEvent(**good))
            if label == "mixed":
                for mismatch in changed.values():
                    session.add(AuditEvent(**{**good, **mismatch}))
            proven = label in {"duplicates", "mixed"}
            cases[label] = _case(version, proven, _IMPORTED if proven else (None, None))
        session.commit()
        candidates = _assert_readers(session, company_id=company_id, cases=cases)
        foreign = current_date_facts(candidates, company_id=foreign_company)
        assert session.execute(select(foreign)).all() == []
        after = {row.id: tuple(row) for row in session.execute(
            select(AuditEvent.__table__).where(AuditEvent.id.in_(list(previous)))
        )}
        assert after == previous, "The seek must not rewrite retained audit evidence."


def _catalog(connection):
    return [dict(row) for row in connection.execute(text("""
        SELECT c.relname AS name, i.indisvalid, i.indisready, i.indislive,
               pg_get_indexdef(c.oid) AS definition,
               ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum, pos)
                     JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                     ORDER BY k.pos) AS columns
        FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = current_schema() AND t.relname = 'audit_events'
        ORDER BY c.relname
    """)).mappings()]


def _statistics(connection):
    return {
        "relations": [dict(row) for row in connection.execute(text("""
            SELECT relname, reltuples, relpages FROM pg_class
            WHERE relnamespace = current_schema()::regnamespace
              AND relname IN ('audit_events', 'ip_import_rows') ORDER BY relname
        """)).mappings()],
        "attributes": [dict(row) for row in connection.execute(text("""
            SELECT tablename, attname, n_distinct FROM pg_stats
            WHERE schemaname = current_schema()
              AND tablename IN ('audit_events', 'ip_import_rows')
            ORDER BY tablename, attname
        """)).mappings()],
    }


@pytest.mark.postgres
@pytest.mark.parametrize("statistics", ["fresh", "stale-empty", "analyzed"])
def test_export_provenance_keeps_820_work_bound_with_single_prefix_present(
    isolated_postgres_client, monkeypatch, tmp_path, request, statistics,
):
    engine = get_engine()
    with engine.begin() as connection:
        database = connection.exec_driver_sql("SELECT current_database()").scalar_one()
        assert database.startswith("caseops_http_")
        assert not database.startswith("caseops_http_template_")
        # Control statistics only inside this test-owned migrated database.
        for table in ("audit_events", "ip_import_rows"):
            connection.exec_driver_sql(f"ALTER TABLE {table} SET (autovacuum_enabled = false)")
        before_catalog = _catalog(connection)
        by_name = {row["name"]: row for row in before_catalog}
        assert by_name[_FULL]["columns"] == _KEY
        assert by_name[_SINGLE]["columns"] == ["company_id"]
        assert "ix_audit_events_company_action" not in by_name
        assert all(by_name[name][state] for name in (_FULL, _SINGLE)
                   for state in ("indisvalid", "indisready", "indislive"))
        assert not _statistics(connection)["attributes"]
        if statistics == "stale-empty":
            for table in ("audit_events", "ip_import_rows"):
                connection.exec_driver_sql(f"ANALYZE {table}")
        before_statistics = _statistics(connection)
    actor, filters, _ids = _imported(isolated_postgres_client, monkeypatch, count=201)
    with engine.begin() as connection:
        if statistics == "analyzed":
            for table in ("audit_events", "ip_import_rows"):
                connection.exec_driver_sql(f"ANALYZE {table}")
        after_statistics = _statistics(connection)
        actual_counts = {
            table: connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
            for table in ("audit_events", "ip_import_rows")
        }
        assert all(count >= 201 for count in actual_counts.values())
        assert _catalog(connection) == before_catalog
        if statistics == "fresh":
            assert not after_statistics["attributes"]
        elif statistics == "stale-empty":
            assert after_statistics == before_statistics
            assert all(row["reltuples"] < actual_counts[row["relname"]]
                       for row in after_statistics["relations"])
        else:
            assert after_statistics["attributes"]
    with get_session_factory()() as session:
        context = _context(session, actor)
        with _observe() as observed:
            rows, cursor = portfolio.portfolio_export_page(
                session, context=context, filters=filters, columns=COLUMNS, limit=200,
            )
        assert len(rows) == 200 and cursor
        assert all(row.source_application_on == date(2020, 1, 15)
                   and row.source_renewal_due_on == date(2028, 3, 15) for row in rows)
        assert len(observed) == 2 and all(row["read_only"] for row in observed)
    _plans(
        observed, directory=tmp_path, candidate_bound=201, nodeid=request.node.nodeid,
        measurement={"statistics": statistics, "catalog": before_catalog,
                     "before_statistics": before_statistics, "after_statistics": after_statistics,
                     "actual_counts": actual_counts, "tenant_only_index_retained": True},
    )
