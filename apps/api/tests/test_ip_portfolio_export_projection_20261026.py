"""IPLF-030B/UJ-04: bounded export reads, not worker or source-snapshot proof."""

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select

from caseops_api.db.models import (
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


def _plans(records, *, directory, candidate_bound):
    problems = []
    plans = []
    with get_engine().begin() as connection:
        assert connection.dialect.name == "postgresql"
        for record in records:
            sql = record["statement"]
            assert record["read_only"], record
            plan = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + sql,
                record["parameters"],
            ).scalar_one()
            plans.append({**record, "plan": plan})
            if len(sql.encode()) > 65_536:
                problems.append("SQL exceeds the existing 64KiB source-fact bound")
            if any(sql.lower().count(f"from {table}") > 2
                   for table in ("audit_events", "ip_import_rows")):
                problems.append("Source-proof bodies exceed the existing two-body bound")
            work = sum(
                (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0)
                 + node.get("Rows Removed by Index Recheck", 0)) * node.get("Actual Loops", 1)
                for node in _nodes(plan[0]["Plan"])
                if node.get("Relation Name") in {"audit_events", "ip_import_rows"}
            )
            if work > 4 * candidate_bound + 16:
                problems.append("Provenance work exceeds the existing candidate bound")
    with (directory / "export-projection-plans.json").open("x", encoding="utf-8") as stream:
        json.dump(plans, stream, indent=2, default=str)
    assert not problems, problems


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
