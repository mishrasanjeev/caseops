"""Anonymous stage-seed reuse must not capture a different current-source CTE."""

import re
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import selectable, visitors
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import CTE

from caseops_api.db.models import Company, CompanyMembership, IpDocketRecord, User
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.ip_renewal_tracker_read import scoped_tracker_query, tracker_row
from caseops_api.services.session_context import SessionContext
from tests.test_ip_tracker_filters_20261017 import _records

_STAGES = {
    "ip_date_scoped",
    "ip_date_proof",
    "ip_date_raw",
    "ip_date_validated",
    "ip_tracker_stopped",
}
_COUNTS = {"upcoming": 2, "active": 0, "due_today": 0, "overdue": 0, "missing": 0, "failed": 0}


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def source_client(request):
    return request.getfixturevalue(request.param)


def _reuse_anonymous_seed(monkeypatch):
    # prefix_with() copies a CTE after its anonymous seed was allocated. Force
    # legal reuse of that discarded seed, without rewriting SQL or compiler code.
    real_id = id
    monkeypatch.setattr(
        selectable,
        "id",
        lambda node: 1729 if isinstance(node, CTE) else real_id(node),
        raising=False,
    )


def test_five_stage_names_preserve_pg_materialization_acl_and_current_source(monkeypatch):
    _reuse_anonymous_seed(monkeypatch)
    context = SimpleNamespace(
        company=SimpleNamespace(id="00000000-0000-4000-8000-000000000001"),
        membership=SimpleNamespace(id="00000000-0000-4000-8000-000000000002", role="owner"),
    )
    statement, _ = scoped_tracker_query(None, context=context)
    ctes = {id(node): node for node in visitors.iterate(statement) if isinstance(node, CTE)}
    names = [str(node.name) for node in ctes.values()]
    assert _STAGES <= set(names)
    assert len(names) == len(set(names)) == 6
    assert all(node.nesting for node in ctes.values() if str(node.name) in _STAGES)
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = compiled.string.lower()
    materialized_ctes = [
        node
        for node in ctes.values()
        if any(
            isinstance(prefix, TextClause)
            and prefix.text == "MATERIALIZED"
            and dialect == "postgresql"
            for prefix, dialect in node._prefixes
        )
    ]
    assert len(materialized_ctes) == len(ctes) == 6
    declaration = r"\bas\s+materialized\s*\("
    assert len(re.findall(declaration, sql)) == 6
    decoy = (
        "with ip_materialized_proof_seek as (select 1) "
        "select ip_materialized_proof_seek.value from ip_materialized_proof_seek"
    )
    assert decoy.count("materialized") == 3
    assert re.findall(declaration, decoy) == []
    for fence in (
        "team_memberships",
        "ethical_walls",
        "matter_access_grants",
        "restricted",
        "ip_import_rows",
        "audit_events",
        "current_version",
        "company_id",
    ):
        assert fence in sql
    assert context.company.id in compiled.params.values()
    assert context.membership.id in compiled.params.values()


@pytest.mark.parametrize("surface", ["tracker", "portfolio"])
def test_warm_shared_reads_keep_all_counts_categories_dates_and_tenant_scope(
    source_client, monkeypatch, surface, record_property
):
    client = source_client
    actor, ids = _records(client, monkeypatch)
    foreign = SimpleNamespace(
        company=SimpleNamespace(id="00000000-0000-4000-8000-000000000009"),
        membership=SimpleNamespace(id=actor["membership"]["id"]),
    )
    assert foreign.company.id != actor["company"]["id"]
    engine = get_engine()
    hits = []

    def capture(_connection, _cursor, statement, _parameters, context, _many):
        if "ip_import_rows" in statement and "audit_events" in statement:
            hits.append(context.cache_hit.name)

    event.listen(engine, "before_cursor_execute", capture)
    _reuse_anonymous_seed(monkeypatch)
    path = "/api/ip/portfolio" + ("/renewal-tracker" if surface == "tracker" else "")
    try:
        for _ in range(2):
            for category in (None, *_COUNTS):
                params = {"query": "IP18 source", "limit": 100}
                if category:
                    params["category" if surface == "tracker" else "renewal_tracker_state"] = (
                        category
                    )
                response = client.get(path, headers=actor["headers"], params=params)
                assert response.status_code == 200, response.text
                body = response.json()
                expected = (
                    set(ids)
                    if category is None
                    else set(ids[:2])
                    if category == "upcoming"
                    else set()
                )
                assert {row["docket_id"] for row in body["rows"]} == expected
                if surface == "tracker":
                    assert body["counts"] == _COUNTS
                    assert all(
                        row["source_renewal_state"] == "imported_unverified" for row in body["rows"]
                    )
                else:
                    assert body["counts"]["total"] == len(expected)
            filtered = client.get(
                path,
                headers=actor["headers"],
                params={
                    "query": "IP18 source",
                    "application_date_from": "2015-01-01",
                    "renewal_due_to": "2028-03-31",
                },
            )
            assert filtered.status_code == 200, filtered.text
            assert [row["docket_id"] for row in filtered.json()["rows"]] == [ids[1]]
            with get_session_factory()() as session:
                statement, _facts = scoped_tracker_query(session, context=foreign, docket_id=ids[0])
                assert session.execute(statement).all() == []
        assert "CACHE_HIT" in hits, "Repeated reads must exercise the real compiled cache."
        record_property("source_query_compile_cache_hits", hits.count("CACHE_HIT"))
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_postcommit_corrections_return_the_exact_current_version_under_seed_reuse(
    source_client, monkeypatch
):
    client = source_client
    actor, ids = _records(client, monkeypatch)
    _reuse_anonymous_seed(monkeypatch)
    for version, due in enumerate(("2028-04-01", None, "2028-01-02"), 2):
        response = client.patch(
            f"/api/ip/dockets/{ids[0]}/portfolio-renewal-date",
            headers=actor["headers"],
            json={
                "expected_current_version": version - 1,
                "renewal_due_date": due,
                "reason": "Deterministic CTE identity regression",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["current_version"] == version
        with get_session_factory()() as session:
            context = SessionContext(
                company=session.get(Company, actor["company"]["id"]),
                membership=session.get(CompanyMembership, actor["membership"]["id"]),
                user=session.get(User, actor["user"]["id"]),
            )
            row = tracker_row(session, context=context, docket_id=ids[0])
            assert (
                row.source_renewal_due_on.isoformat() if row.source_renewal_due_on else None
            ) == due
            assert row.source_renewal_state == ("manual" if due else "missing")
            assert session.get(IpDocketRecord, ids[0]).current_version == version
