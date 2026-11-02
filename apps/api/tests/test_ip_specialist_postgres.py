import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, literal, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import visitors

from caseops_api.db.models import (
    Client,
    Company,
    CompanyMembership,
    EthicalWall,
    IpAsset,
    IpDocketRecord,
    IpSpecialistRecord,
    IpSpecialistVersion,
    MatterAccessGrant,
    MembershipRole,
    Team,
    TeamMembership,
)
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_specialist import SpecialistCorrection, SpecialistFacts
from caseops_api.services.idempotency import canonical_json_sha256
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.ip_specialist import correct_record, create_record, list_records
from caseops_api.services.record_access_policy import visible_ip_dockets_filter
from tests import test_ip_specialist as journeys
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres
registered_intake = journeys.registered_intake


@pytest.mark.parametrize("domain", journeys.FACT_MODELS)
def test_specialist_http_domain_journey_postgres(
    isolated_postgres_client, registered_intake, domain
):
    journeys.test_domain_intake_and_source_journey(
        isolated_postgres_client, registered_intake, domain
    )


@pytest.mark.parametrize(
    "journey",
    [
        "test_source_failure_supersession_replay_and_domain_mismatch",
        "test_terminal_history_download_and_revoke",
        "test_cross_tenant_cannot_read_or_mutate",
        "test_specialist_access_cannot_be_published_through_generic_acl",
        "test_same_day_reopen_retires_creation_and_source_replays",
    ],
)
def test_specialist_http_exception_postgres(isolated_postgres_client, registered_intake, journey):
    getattr(journeys, journey)(isolated_postgres_client, registered_intake)


def _seed(engine):
    with Session(engine) as session:
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        client = Client(
            company_id=company_id, name="Specialist PostgreSQL client", client_type="corporate"
        )
        session.add(client)
        session.commit()
        record = create_record(
            session,
            context=_ip_race_context(session, company_id=company_id, membership_id=actor_id),
            payload=SpecialistFacts(
                title="Restricted design",
                client_id=client.id,
                jurisdiction_as_supplied="India",
                details={"domain": "design", **journeys.DETAILS["design"]},
            ),
            idempotency_key=str(uuid4()),
        )
        return company_id, actor_id, record


@pytest.mark.parametrize("winner_action", ["correction", "closure"])
def test_concurrent_correction_reloads_the_locked_parent(
    pg_engine, registered_intake, winner_action
):
    company, actor, record = _seed(pg_engine)
    payload = SpecialistCorrection(
        expected_version=record.version,
        expected_lifecycle_version=record.lifecycle_version,
        reason="Concurrent source transcription correction",
        facts=record.facts,
    )
    name = f"other-ip-stale-{uuid4().hex[:12]}"

    def waiting_writer():
        with Session(pg_engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            context = _ip_race_context(session, company_id=company, membership_id=actor)
            try:
                correct_record(session, context=context, record_id=str(record.id), payload=payload)
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
            raise AssertionError("Stale writer was admitted")

    with Session(pg_engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        winner.scalar(select(Company).where(Company.id == company).with_for_update())
        future = pool.submit(waiting_writer)
        try:
            _wait_for_postgres_lock_wait(pg_engine, application_name=name)
            context = _ip_race_context(winner, company_id=company, membership_id=actor)
            if winner_action == "correction":
                correct_record(winner, context=context, record_id=str(record.id), payload=payload)
            else:
                transition_ip_docket_lifecycle(
                    winner,
                    context=context,
                    docket_id=str(record.docket_id),
                    payload=IpLifecycleTransitionRequest(
                        expected_lifecycle_version=0,
                        to_status="closed",
                        effective_at=datetime.now(UTC),
                        reason="Client closed during a stale correction request.",
                        outcome="closed",
                        source="lawyer_review",
                        evidence_ref="test:concurrent-closure",
                        linked_matter_handling="reviewed",
                    ),
                )
                winner.commit()
            assert future.result(timeout=8) == (409 if winner_action == "correction" else 404)
        finally:
            winner.rollback()
    with Session(pg_engine) as session:
        assert session.scalar(
            select(func.count())
            .select_from(IpSpecialistVersion)
            .where(IpSpecialistVersion.record_id == str(record.id))
        ) == (2 if winner_action == "correction" else 1)


def test_tenant_constraints_and_database_history_guard(pg_engine, registered_intake):
    company, _, record = _seed(pg_engine)
    other_company, _, _ = _seed(pg_engine)
    with Session(pg_engine) as session:
        header = session.get(IpSpecialistRecord, str(record.id))
        values = {column.name: getattr(header, column.name) for column in header.__table__.columns}
        with pytest.raises(IntegrityError):
            session.execute(
                insert(IpSpecialistRecord),
                {**values, "id": str(uuid4()), "company_id": other_company},
            )
        session.rollback()
        with pytest.raises(DBAPIError, match="Specialist evidence is immutable"):
            session.execute(
                text(
                    "UPDATE ip_specialist_versions SET reason = 'overwrite' "
                    "WHERE company_id = :company"
                ),
                {"company": company},
            )
        session.rollback()
        with pytest.raises(DBAPIError, match="Specialist evidence is immutable"):
            session.execute(
                text("DELETE FROM ip_specialist_versions WHERE company_id = :company"),
                {"company": company},
            )
        session.rollback()


def _seed_team_catalog_noise(session, company, actor, *, fresh_statistics=True, request=None):
    foreign_company = _seed_company(session)
    foreign_actor = _seed_membership(session, foreign_company, role="admin")
    stale_baseline = None
    if not fresh_statistics:
        assert session.scalar(text("SELECT current_database()")).startswith("caseops_migration_")
        assert session.scalar(select(func.count()).select_from(Team)) == 0
        assert session.scalar(select(func.count()).select_from(TeamMembership)) == 0
        # Match the existing stale-statistics fixtures, only in a fresh disposable database.
        for table in ("teams", "team_memberships"):
            session.execute(text(f"ALTER TABLE {table} SET (autovacuum_enabled = false)"))
        training = [
            Team(company_id=foreign_company, name=f"Training {index}", slug=f"training-{index}")
            for index in range(32)
        ]
        session.add_all(training)
        session.flush()
        session.add_all(
            TeamMembership(team_id=team.id, membership_id=foreign_actor) for team in training
        )
        session.flush()
        session.execute(text("ANALYZE teams"))
        session.execute(text("ANALYZE team_memberships"))
        stale_baseline = session.execute(
            text(
                "SELECT relname, reltuples::int, reloptions FROM pg_class "
                "WHERE oid IN ('teams'::regclass, 'team_memberships'::regclass) ORDER BY relname"
            )
        ).all()
        assert all(count == 32 for _table, count, _options in stale_baseline)
        assert all(
            "autovacuum_enabled=false" in options for _table, _count, options in stale_baseline
        )
        session.commit()
    teams = [
        Team(
            company_id=foreign_company,
            name=f"Foreign catalog noise {index}",
            slug=f"foreign-catalog-noise-{index}",
            is_active=index < 177,
        )
        for index in range(183)
    ]
    inactive = Team(
        company_id=company, name="Own inactive team", slug="own-inactive-team", is_active=False
    )
    session.add_all([*teams, inactive])
    session.flush()
    session.add_all(
        TeamMembership(team_id=team.id, membership_id=foreign_actor) for team in teams
    )
    session.commit()
    if fresh_statistics:
        session.execute(text("ANALYZE teams"))
        session.execute(text("ANALYZE team_memberships"))
    else:
        retained = session.execute(
            text(
                "SELECT relname, reltuples::int, reloptions FROM pg_class "
                "WHERE oid IN ('teams'::regclass, 'team_memberships'::regclass) ORDER BY relname"
            )
        ).all()
        assert retained == stale_baseline
        assert session.scalar(select(func.count()).select_from(Team)) == 216
        assert session.scalar(select(func.count()).select_from(TeamMembership)) == 215
        if request is not None:
            request.node.user_properties.append(
                (
                    "specialist_team_stale_fixture",
                    json.dumps(
                        {
                            "pre_import_rows": 32,
                            "stale_statistics_rows": [list(row) for row in retained],
                            "post_import_teams": 216,
                            "post_import_memberships": 215,
                            "automatic_analysis_disabled_in_disposable_fixture": True,
                            "no_analysis_after_catalog_growth": True,
                        }
                    ),
                )
            )
    assert session.scalar(
        select(func.count())
        .select_from(TeamMembership)
        .where(TeamMembership.membership_id == actor)
    ) == 0
    return inactive.id


def _retain_specialist_plan(request, plan, *, label):
    nodes, pending = [], [plan["Plan"]]
    while pending:
        node = pending.pop()
        nodes.append(node)
        pending.extend(node.get("Plans", []))
    # PostgreSQL rounds per-loop row averages; charge every active loop.
    row_work = sum(
        node.get("Actual Loops", 0)
        * (
            1
            + node.get("Actual Rows", 0)
            + node.get("Rows Removed by Filter", 0)
            + node.get("Rows Removed by Join Filter", 0)
        )
        for node in nodes
    )
    docket_nodes = [node for node in nodes if node.get("Relation Name") == "ip_docket_records"]
    retained = {
        "label": label,
        "row_work": row_work,
        "execution_ms": plan["Execution Time"],
        "docket_nodes": [
            {
                key: node.get(key)
                for key in ("Node Type", "Index Name", "Actual Loops", "Actual Rows", "Index Cond")
            }
            for node in docket_nodes
        ],
        "full_plan": plan,
    }
    encoded = json.dumps(retained, sort_keys=True)
    encoded = re.sub(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
        lambda match: "<fixture-uuid:" + sha256(match[0].encode()).hexdigest()[:12] + ">",
        encoded,
    )
    if len(encoded.encode()) > 131_072:
        request.node.user_properties.append(
            ("specialist_list_plan", json.dumps({"label": label, "full_plan_over_budget": True}))
        )
        pytest.fail("Complete specialist EXPLAIN exceeds the 128 KiB retention budget")
    request.node.user_properties.append(("specialist_list_plan", encoded))
    return row_work, docket_nodes, nodes


def _explain_specialist_clause(request, session, clauses, statements, *, label):
    specialist_clauses = [
        clause
        for clause in clauses
        if any(
            column.get("entity") is IpSpecialistRecord
            for column in getattr(clause, "column_descriptions", ())
        )
    ]
    if len(specialist_clauses) != 1:
        request.node.user_properties.append(
            (
                "specialist_list_plan",
                json.dumps(
                    {"label": label, "missing_select_clause": True, "statements": len(statements)}
                ),
            )
        )
        pytest.fail("No actual specialist SELECT clause retained for EXPLAIN")
    if len(clauses) != 1:
        request.node.user_properties.append(
            (
                "specialist_list_capture",
                json.dumps({"label": label, "select_clauses": len(clauses), "sql": statements}),
            )
        )
    sql = str(
        specialist_clauses[0].compile(session.get_bind(), compile_kwargs={"literal_binds": True})
    )
    plan = session.scalar(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql))[0]
    return _retain_specialist_plan(request, plan, label=label)


@pytest.mark.parametrize("visibility_order", ["balanced", "hidden_next_page"])
def test_ten_thousand_records_list_bounds_queries_and_omits_ungranted_rows(
    pg_engine, registered_intake, request, visibility_order
):
    company, actor, record = _seed(pg_engine)
    with Session(pg_engine) as session:
        inactive_team_id = _seed_team_catalog_noise(session, company, actor, request=request)
        docket = session.get(IpDocketRecord, str(record.docket_id))
        asset = session.get(IpAsset, str(record.asset_id))
        header = session.get(IpSpecialistRecord, str(record.id))
        grant = session.scalar(
            select(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == docket.id)
        )
        original_version = session.scalar(
            select(IpSpecialistVersion).where(IpSpecialistVersion.record_id == header.id)
        )
        record_rank, docket_rank = UUID(header.id).int, UUID(docket.id).int
        assert record_rank > 10_000 and docket_rank > 10_000

        def clone(row, **changes):
            return {
                **{column.name: getattr(row, column.name) for column in row.__table__.columns},
                **changes,
            }

        for batch in range(20):
            dockets, assets, records, versions, grants = [], [], [], [], []
            for offset in range(500):
                ordinal = batch * 500 + offset
                docket_id = str(UUID(int=docket_rank - 10_000 + ordinal))
                asset_id = str(uuid4())
                visible = (
                    ordinal % 2 == 0
                    if visibility_order == "balanced"
                    else ordinal < 26 or 79 <= ordinal < 5053
                )
                dockets.append(
                    clone(
                        docket,
                        id=docket_id,
                        title=f"{'Visible' if visible else 'Hidden'}-{batch}-{offset}",
                    )
                )
                assets.append(
                    clone(asset, id=asset_id, docket_id=docket_id, title=dockets[-1]["title"])
                )
                # Record and docket rank are independent of random UUID density.
                record_id = str(UUID(int=record_rank - 10_000 + ordinal))
                records.append(clone(header, id=record_id, docket_id=docket_id, asset_id=asset_id))
                facts = {**original_version.facts_json, "title": dockets[-1]["title"]}
                versions.append(
                    clone(
                        original_version,
                        id=str(uuid4()),
                        record_id=record_id,
                        facts_json=facts,
                        facts_sha256=canonical_json_sha256(facts),
                    )
                )
                if visible:
                    grants.append(clone(grant, id=str(uuid4()), ip_docket_id=docket_id))
            for model, rows in (
                (IpDocketRecord, dockets),
                (IpAsset, assets),
                (IpSpecialistRecord, records),
                (IpSpecialistVersion, versions),
                (MatterAccessGrant, grants),
            ):
                if rows:
                    session.execute(insert(model.__table__), rows)
            session.commit()
            # Bulk-loaded tables need fresh statistics before the plan is measured;
            # stale ones (autovacuum timing, rows left by earlier tests) make the bound flaky.
            for table in ("ip_docket_records", "ip_specialist_records", "matter_access_grants"):
                session.execute(text(f"ANALYZE {table}"))
        expected_ids = [str(UUID(int=record_rank - 10_000 + i)) for i in range(10_000)]
        assert list(session.scalars(
            select(IpSpecialistRecord.id).where(
                IpSpecialistRecord.company_id == company,
                IpSpecialistRecord.domain == "design",
            ).order_by(IpSpecialistRecord.id)
        )) == [*expected_ids, header.id]
        assert session.scalar(select(func.count(MatterAccessGrant.id)).where(
            MatterAccessGrant.company_id == company,
            MatterAccessGrant.membership_id == actor,
            MatterAccessGrant.ip_docket_id.is_not(None),
            MatterAccessGrant.revoked_at.is_(None),
        )) == 5001
        first_ordinals = (
            list(range(0, 50, 2)) if visibility_order == "balanced" else list(range(25))
        )
        next_ordinals = (
            list(range(50, 100, 2))
            if visibility_order == "balanced" else [25, *range(79, 103)]
        )
        first_expected = [expected_ids[i] for i in first_ordinals]
        next_expected = [expected_ids[i] for i in next_ordinals]
        request.node.user_properties.append(("specialist_fixture_order", json.dumps({
            "layout": visibility_order, "cloned_records": 10_000, "seed_records": 1,
            "cloned_grants": 5000, "seed_grants": 1,
            "first_ordinals": first_ordinals, "next_ordinals": next_ordinals,
            "first_cursor_ordinal": first_ordinals[-1], "next_cursor_ordinal": next_ordinals[-1],
        })))
        context = _ip_race_context(session, company_id=company, membership_id=actor)
        statements = []
        clauses = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        def capture_clause(_conn, clause, _multiparams, _params, _options):
            if getattr(clause, "is_select", False):
                clauses.append(clause)

        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        event.listen(pg_engine, "before_cursor_execute", capture)
        event.listen(pg_engine, "before_execute", capture_clause)
        try:
            page = list_records(session, context=context, domain="design", limit=25)
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)
            event.remove(pg_engine, "before_execute", capture_clause)
        row_work, docket_nodes, nodes = _explain_specialist_clause(
            request, session, clauses, statements, label="empty:first"
        )
        assert len(page.records) == 25 and page.next_cursor
        assert [str(row.id) for row in page.records] == first_expected
        assert str(page.next_cursor) == first_expected[-1]
        assert all(not row.title.startswith("Hidden") for row in page.records)
        assert len(statements) <= 12, statements
        assert not any("ip_specialist_versions" in statement for statement in statements)
        assert len(clauses) == 1 and "JOIN LATERAL" in statements[0]
        assert row_work <= 2048
        assert docket_nodes and all(node["Actual Loops"] <= 128 for node in docket_nodes)
        assert all("Index" in node["Node Type"] for node in docket_nodes)
        assert all(
            "id" in node.get("Index Cond", "") and ">=" in node.get("Index Cond", "")
            for node in docket_nodes
        ), docket_nodes
        assert all(node["Actual Rows"] <= 1 for node in docket_nodes)
        assert all(
            node["Actual Loops"] == 0 for node in nodes if node.get("Relation Name") == "teams"
        )

        first_ids = {row.id for row in page.records}
        for label, cursor in (
            ("empty:next", page.next_cursor),
            ("inactive:first", None),
            ("inactive:next", page.next_cursor),
        ):
            if label == "inactive:first":
                session.add(TeamMembership(team_id=inactive_team_id, membership_id=actor))
                session.commit()
                session.execute(text("SET LOCAL statement_timeout = '5s'"))
                cold_statements = []

                def capture_cold(
                    _conn, _cursor, statement, _params, _context, _many, captured=cold_statements
                ):
                    captured.append(statement)

                event.listen(pg_engine, "before_cursor_execute", capture_cold)
                try:
                    cold_page = list_records(session, context=context, domain="design", limit=25)
                finally:
                    event.remove(pg_engine, "before_cursor_execute", capture_cold)
                request.node.user_properties.append(
                    (
                        "fixture_context_refresh_control",
                        json.dumps(
                            {
                                "label": label,
                                "sql": cold_statements,
                                "expected_fixture_refresh_not_product_failure": True,
                            }
                        ),
                    )
                )
                assert len(cold_statements) == 3, cold_statements
                assert any("FROM companies" in sql for sql in cold_statements[:2])
                assert any("FROM company_memberships" in sql for sql in cold_statements[:2])
                assert "JOIN LATERAL" in cold_statements[2]
                assert first_ids == {row.id for row in cold_page.records}
                context = _ip_race_context(session, company_id=company, membership_id=actor)
                session.execute(text("SET LOCAL statement_timeout = '5s'"))
            statements.clear()
            clauses.clear()
            event.listen(pg_engine, "before_cursor_execute", capture)
            event.listen(pg_engine, "before_execute", capture_clause)
            try:
                following = list_records(
                    session,
                    context=context,
                    domain="design",
                    limit=25,
                    cursor=str(cursor) if cursor else None,
                )
            finally:
                event.remove(pg_engine, "before_cursor_execute", capture)
                event.remove(pg_engine, "before_execute", capture_clause)
            work, dockets, following_nodes = _explain_specialist_clause(
                request, session, clauses, statements, label=label
            )
            assert len(following.records) == 25 and following.next_cursor
            expected = next_expected if cursor else first_expected
            assert [str(row.id) for row in following.records] == expected
            assert str(following.next_cursor) == expected[-1]
            assert all(not row.title.startswith("Hidden") for row in following.records)
            assert len(statements) <= 12, statements
            assert not any("ip_specialist_versions" in statement for statement in statements)
            assert len(clauses) == 1 and "JOIN LATERAL" in statements[0]
            assert work <= 2048
            assert dockets and all(node["Actual Loops"] <= 128 for node in dockets)
            assert all("Index" in node["Node Type"] for node in dockets)
            assert all(
                "id" in node.get("Index Cond", "") and ">=" in node.get("Index Cond", "")
                for node in dockets
            ), dockets
            assert all(node["Actual Rows"] <= 1 for node in dockets)
            assert all(
                node["Actual Loops"] <= 1
                for node in following_nodes
                if node.get("Relation Name") in {"teams", "team_memberships"}
            )
            if label.startswith("empty"):
                assert all(
                    node["Actual Loops"] == 0
                    for node in following_nodes
                    if node.get("Relation Name") == "teams"
                )
            if cursor:
                assert first_ids.isdisjoint(row.id for row in following.records)
            else:
                assert first_ids == {row.id for row in following.records}


def _assert_specialist_base_acl_parity(session, context, record_id, *, allowed, closed=False):
    header = session.get(IpSpecialistRecord, record_id)
    docket = session.get(IpDocketRecord, header.docket_id)
    canonical = session.scalar(
        select(IpDocketRecord.id).where(
            IpDocketRecord.id == header.docket_id,
            IpDocketRecord.company_id == context.company.id,
            visible_ip_dockets_filter(session, context=context),
        )
    )
    assert (canonical is not None) is allowed
    assert docket.is_active is (not closed)
    if closed:
        assert docket.status == "closed"
    for include_closed in (False, True):
        page = list_records(
            session, context=context, domain="design", limit=25,
            include_closed=include_closed,
        )
        expected = [UUID(record_id)] if allowed and (not closed or include_closed) else []
        assert [row.id for row in page.records] == expected
        assert page.next_cursor is None
        if expected:
            summary = page.records[0]
            assert (summary.title, summary.lifecycle_status, summary.version) == (
                docket.title, docket.status, docket.current_version,
            )


@pytest.mark.parametrize(
    "scenario", ["owner_ungranted", "member_wall", "team_wall", "sole_team_grant", "include_closed"]
)
def test_specialist_list_matches_base_acl_after_docket_adaptation(
    pg_engine, registered_intake, scenario
):
    company, actor, record = _seed(pg_engine)
    with Session(pg_engine) as session:
        session.get(CompanyMembership, actor).role = MembershipRole.OWNER
        grant = session.scalars(
            select(MatterAccessGrant).where(
                MatterAccessGrant.company_id == company,
                MatterAccessGrant.ip_docket_id == str(record.docket_id),
                MatterAccessGrant.membership_id == actor,
                MatterAccessGrant.revoked_at.is_(None),
            )
        ).one()
        session.commit()
        context = _ip_race_context(session, company_id=company, membership_id=actor)
        record_id = str(record.id)
        _assert_specialist_base_acl_parity(session, context, record_id, allowed=True)
        if scenario == "owner_ungranted":
            grant.revoked_at = datetime.now(UTC)
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=False)
        elif scenario == "sole_team_grant":
            grant.revoked_at = datetime.now(UTC)
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=False)
            team = Team(company_id=company, name="Sole alias grant team",
                        slug=f"sole-alias-grant-{uuid4().hex}", is_active=True)
            session.add(team)
            session.flush()
            association = TeamMembership(team_id=team.id, membership_id=actor)
            team_grant = MatterAccessGrant(
                company_id=company, ip_docket_id=str(record.docket_id),
                team_id=team.id, granted_by_membership_id=actor,
            )
            session.add_all([association, team_grant])
            session.commit()
            assert session.scalar(select(func.count()).select_from(MatterAccessGrant).where(
                MatterAccessGrant.company_id == company,
                MatterAccessGrant.ip_docket_id == str(record.docket_id),
                MatterAccessGrant.membership_id == actor,
                MatterAccessGrant.revoked_at.is_(None),
            )) == 0
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=True)
            team.is_active = False
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=False)
            team.is_active = True
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=True)
            session.delete(association)
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=False)
            session.add(TeamMembership(team_id=team.id, membership_id=actor))
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=True)
            team_grant.revoked_at = datetime.now(UTC)
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=False)
            team_grant.revoked_at = None
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=True)
            transition_ip_docket_lifecycle(
                session, context=context, docket_id=str(record.docket_id),
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=record.lifecycle_version,
                    to_status="closed", effective_at=datetime.now(UTC),
                    reason="Local sole-team grant closed-read fixture.",
                    outcome="closed", source="local_fixture",
                    evidence_ref="fixture:specialist-sole-team-alias",
                    linked_matter_handling="reviewed",
                ),
            )
            session.commit()
            _assert_specialist_base_acl_parity(
                session, context, record_id, allowed=True, closed=True
            )
            team_grant.revoked_at = datetime.now(UTC)
            session.commit()
            _assert_specialist_base_acl_parity(
                session, context, record_id, allowed=False, closed=True
            )
        elif scenario in {"member_wall", "team_wall"}:
            wall_subject = {"excluded_membership_id": actor}
            team = None
            if scenario == "team_wall":
                team = Team(company_id=company, name="Alias wall team",
                            slug=f"alias-wall-{uuid4().hex}", is_active=True)
                session.add(team)
                session.flush()
                session.add(TeamMembership(team_id=team.id, membership_id=actor))
                wall_subject = {"excluded_team_id": team.id}
            wall = EthicalWall(
                company_id=company, ip_docket_id=str(record.docket_id),
                created_by_membership_id=actor, **wall_subject,
            )
            session.add(wall)
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=False)
            if team is not None:
                team.is_active = False
            else:
                wall.revoked_at = datetime.now(UTC)
            session.commit()
            _assert_specialist_base_acl_parity(session, context, record_id, allowed=True)
        else:
            transition_ip_docket_lifecycle(
                session,
                context=context,
                docket_id=str(record.docket_id),
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=record.lifecycle_version,
                    to_status="closed", effective_at=datetime.now(UTC),
                    reason="Local fixture closure for list and retained ACL parity.",
                    outcome="closed", source="local_fixture",
                    evidence_ref="fixture:specialist-list-alias",
                    linked_matter_handling="reviewed",
                ),
            )
            session.commit()
            _assert_specialist_base_acl_parity(
                session, context, record_id, allowed=True, closed=True
            )
            grant.revoked_at = datetime.now(UTC)
            session.commit()
            _assert_specialist_base_acl_parity(
                session, context, record_id, allowed=False, closed=True
            )
        versions = session.scalar(
            select(func.count()).select_from(IpSpecialistVersion).where(
                IpSpecialistVersion.record_id == record_id,
                IpSpecialistVersion.company_id == company,
            )
        )
        assert versions == 1


@pytest.mark.parametrize("neighbor_scope", ["own", "foreign"])
def test_specialist_list_rejects_a_present_nonmatching_docket_successor(
    pg_engine, registered_intake, neighbor_scope
):
    company, actor, record = _seed(pg_engine)
    with Session(pg_engine) as session:
        neighbor_company, neighbor_actor = company, actor
        if neighbor_scope == "foreign":
            neighbor_company = _seed_company(session)
            neighbor_actor = _seed_membership(session, neighbor_company, role="admin")
        base = uuid4().int & ~((1 << 32) - 1)
        absent_id, neighbor_id = [str(UUID(int=base + offset)) for offset in (2, 3)]
        absent = session.get(IpDocketRecord, absent_id)
        assert absent is None
        session.add(
            IpDocketRecord(
                id=neighbor_id, company_id=neighbor_company,
                title="Present successor must not supply specialist facts",
                record_type="design_intake", restricted=True,
            )
        )
        session.flush()
        session.add(
            MatterAccessGrant(
                company_id=neighbor_company, ip_docket_id=neighbor_id,
                membership_id=neighbor_actor, granted_by_membership_id=neighbor_actor,
            )
        )
        session.commit()
        successor = session.scalar(
            select(IpDocketRecord.id).where(IpDocketRecord.id >= absent_id)
            .order_by(IpDocketRecord.id).limit(1)
        )
        assert successor == neighbor_id
        context = _ip_race_context(session, company_id=company, membership_id=actor)
        clauses = []

        def capture(_connection, clause, _multiparams, _params, _options):
            if any(
                column.get("entity") is IpSpecialistRecord
                for column in getattr(clause, "column_descriptions", ())
            ):
                clauses.append(clause)

        bind = session.get_bind()
        event.listen(bind, "before_execute", capture)
        try:
            admitted = list_records(session, context=context, domain="design", limit=25)
        finally:
            event.remove(bind, "before_execute", capture)
        assert [row.id for row in admitted.records] == [record.id]
        assert len(clauses) == 1
        # Probe the actual captured query without corrupting FK-backed fixture rows.
        replacement = literal(absent_id, type_=IpSpecialistRecord.__table__.c.docket_id.type)
        replaced = 0

        def replace(node):
            nonlocal replaced
            if (
                getattr(node, "table", None) is IpSpecialistRecord.__table__
                and getattr(node, "key", None) == "docket_id"
            ):
                replaced += 1
                return replacement
            return None

        missing_target_clause = visitors.replacement_traverse(clauses[0], {}, replace)
        assert replaced > 0
        rejected = session.execute(missing_target_clause).all()
        assert rejected == []
