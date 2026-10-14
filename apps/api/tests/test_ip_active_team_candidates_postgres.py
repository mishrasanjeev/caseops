import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    EthicalWall,
    IpDocketRecord,
    MatterAccessGrant,
    Team,
    TeamMembership,
)
from caseops_api.services import ip_specialist as specialist_service
from caseops_api.services.record_access_policy import visible_ip_dockets_filter
from tests import test_ip_record_access_foundation as foundation
from tests import test_ip_specialist_postgres as specialist
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
registered_intake = specialist.registered_intake


def _use_bearer_identity_without_cookie_mixing(client, monkeypatch):
    original_request = client.request

    def request_with_auth_aware_cookies(method, url, **kwargs):
        headers = kwargs.get("headers") or {}
        auth = headers.get("Authorization") or headers.get("authorization") or ""
        if isinstance(auth, str) and auth.startswith("Bearer "):
            saved = list(client.cookies.jar)
            client.cookies.clear()
            try:
                return original_request(method, url, **kwargs)
            finally:
                for cookie in saved:
                    client.cookies.jar.set_cookie(cookie)
        return original_request(method, url, **kwargs)

    monkeypatch.setattr(client, "request", request_with_auth_aware_cookies)


def test_native_fixture_pins_cookie_bearer_actor_and_creator_grant(
    isolated_postgres_client, monkeypatch, request
):
    client = isolated_postgres_client
    bootstrap = foundation.bootstrap_company(client)
    owner = str(bootstrap["membership"]["id"])
    owner_headers = foundation.auth_headers(str(bootstrap["access_token"]))
    member, member_headers = foundation._invite_member(client, str(bootstrap["access_token"]))
    raw_me = client.get("/api/auth/me", headers=owner_headers)
    assert raw_me.status_code == 200, raw_me.text
    assert str(raw_me.json()["membership"]["id"]) == member
    raw_docket = foundation._create_restricted_docket(client, owner_headers)
    with foundation.get_session_factory()() as session:
        assert session.get_bind().dialect.name == "postgresql"
        row = session.get(IpDocketRecord, str(raw_docket["id"]))
        assert row.created_by_membership_id == member
        raw_grants = session.execute(
            select(
                MatterAccessGrant.membership_id, MatterAccessGrant.granted_by_membership_id,
                MatterAccessGrant.reason,
            ).where(
                MatterAccessGrant.ip_docket_id == row.id, MatterAccessGrant.revoked_at.is_(None)
            )
        ).all()
        assert raw_grants == [(member, member, "Initial restricted-record creator access.")]

    _use_bearer_identity_without_cookie_mixing(client, monkeypatch)
    owner_me = client.get("/api/auth/me", headers=owner_headers)
    member_me = client.get("/api/auth/me", headers=member_headers)
    assert owner_me.status_code == member_me.status_code == 200
    assert str(owner_me.json()["membership"]["id"]) == owner
    assert str(member_me.json()["membership"]["id"]) == member
    owned_docket = foundation._create_restricted_docket(client, owner_headers)
    with foundation.get_session_factory()() as session:
        row = session.get(IpDocketRecord, str(owned_docket["id"]))
        assert row.created_by_membership_id == owner
        owner_grants = session.execute(
            select(
                MatterAccessGrant.membership_id, MatterAccessGrant.granted_by_membership_id,
                MatterAccessGrant.reason,
            ).where(
                MatterAccessGrant.ip_docket_id == row.id, MatterAccessGrant.revoked_at.is_(None)
            )
        ).all()
        assert owner_grants == [(owner, owner, "Initial restricted-record creator access.")]
    hidden = client.get(f"/api/ip/dockets/{owned_docket['id']}", headers=member_headers)
    assert hidden.status_code == 404, hidden.text
    cookie_me = client.get("/api/auth/me")
    assert cookie_me.status_code == 200
    assert str(cookie_me.json()["membership"]["id"]) == member
    request.node.user_properties.append(
        (
            "native_http_actor_identity",
            json.dumps(
                {
                    "owner_membership_id": owner,
                    "member_membership_id": member,
                    "raw_owner_bearer_actual_membership": raw_me.json()["membership"]["id"],
                    "raw_docket_created_by": member,
                    "raw_creator_grants": [list(row) for row in raw_grants],
                    "bearer_owner_actual_membership": owner_me.json()["membership"]["id"],
                    "bearer_member_actual_membership": member_me.json()["membership"]["id"],
                    "bearer_docket_created_by": owner,
                    "bearer_creator_grants": [list(row) for row in owner_grants],
                    "member_cannot_read_owner_docket": hidden.status_code,
                    "cookie_only_actual_membership": cookie_me.json()["membership"]["id"],
                    "production_cookie_first_unchanged": True,
                }
            ),
        )
    )


@pytest.mark.parametrize("subject", ["membership", "team"])
def test_canonical_ip_subject_windows_and_team_eligibility_postgres(
    isolated_postgres_client, subject, monkeypatch
):
    _use_bearer_identity_without_cookie_mixing(isolated_postgres_client, monkeypatch)
    foundation.test_ip_unique_subject_seek_preserves_windows_and_team_eligibility(
        isolated_postgres_client, subject
    )


def test_public_specialist_cursor_roundtrips_and_stays_tenant_scoped(
    isolated_postgres_client, registered_intake, monkeypatch, request
):
    client = isolated_postgres_client
    _use_bearer_identity_without_cookie_mixing(client, monkeypatch)
    headers, facts = specialist.journeys.setup(client)
    owner_me = client.get("/api/auth/me", headers=headers)
    assert owner_me.status_code == 200, owner_me.text
    records = []
    for index in range(2):
        created = specialist.journeys.create(
            client, headers, {**facts, "title": f"Public cursor record {index}"}
        )
        assert created.status_code == 201, created.text
        records.append(created.json()["id"])
    expected = sorted(records)
    with foundation.get_session_factory()() as session:
        assert session.get_bind().dialect.name == "postgresql"

    original = specialist_service.list_records
    received_cursors = []

    def capture_cursor(session, **kwargs):
        cursor = kwargs.get("cursor")
        assert cursor is None or isinstance(cursor, str)
        received_cursors.append(cursor)
        return original(session, **kwargs)

    monkeypatch.setattr(specialist_service, "list_records", capture_cursor)
    url = specialist.journeys.BASE + "/records"
    first = client.get(url, headers=headers, params={"domain": "design", "limit": 1})
    assert first.status_code == 200, first.text
    assert [row["id"] for row in first.json()["records"]] == expected[:1]
    cursor = first.json()["next_cursor"]
    assert isinstance(cursor, str) and cursor == expected[0]
    second = client.get(
        url, headers=headers, params={"domain": "design", "limit": 1, "cursor": cursor}
    )
    assert second.status_code == 200, second.text
    assert [row["id"] for row in second.json()["records"]] == expected[1:]
    assert second.json()["next_cursor"] is None
    assert received_cursors == [None, cursor]
    invalid = client.get(
        url, headers=headers, params={"domain": "design", "limit": 1, "cursor": "invalid-cursor"}
    )
    assert invalid.status_code == 422, invalid.text
    assert received_cursors == [None, cursor]

    foreign_key = str(uuid4())
    foreign_bootstrap = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Foreign cursor fixture",
            "company_slug": f"cursor-foreign-{foreign_key}",
            "company_type": "law_firm",
            "owner_full_name": "Foreign cursor fixture owner",
            "owner_email": f"cursor-{foreign_key}@example.com",
            "owner_password": "OnlyLocalCursor2026!",
        },
    )
    assert foreign_bootstrap.status_code == 200, foreign_bootstrap.text
    foreign_headers = {
        **foundation.auth_headers(str(foreign_bootstrap.json()["access_token"])),
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    foreign_client = client.post(
        "/api/clients",
        headers=foreign_headers,
        json={"name": "Foreign cursor fixture client", "client_type": "corporate"},
    )
    assert foreign_client.status_code == 200, foreign_client.text
    foreign_facts = {
        **facts, "title": "Foreign cursor fixture record", "client_id": foreign_client.json()["id"]
    }
    foreign_me = client.get("/api/auth/me", headers=foreign_headers)
    assert foreign_me.status_code == 200, foreign_me.text
    assert foreign_me.json()["company"]["id"] != owner_me.json()["company"]["id"]
    created = specialist.journeys.create(client, foreign_headers, foreign_facts)
    assert created.status_code == 201, created.text
    foreign_id = created.json()["id"]
    own = client.get(url, headers=foreign_headers, params={"domain": "design", "limit": 1})
    assert own.status_code == 200, own.text
    assert [row["id"] for row in own.json()["records"]] == [foreign_id]
    cross_scope = client.get(
        url, headers=foreign_headers, params={"domain": "design", "limit": 1, "cursor": cursor}
    )
    assert cross_scope.status_code == 200, cross_scope.text
    assert [row["id"] for row in cross_scope.json()["records"]] == (
        [foreign_id] if foreign_id > cursor else []
    )
    assert cross_scope.json()["next_cursor"] is None
    assert received_cursors == [None, cursor, None, cursor]
    request.node.user_properties.append(
        (
            "native_http_cursor_roundtrip",
            json.dumps(
                {
                    "exact_owner_record_ids": expected,
                    "serialized_cursor": cursor,
                    "page2_exact_ids": [row["id"] for row in second.json()["records"]],
                    "invalid_cursor_status": invalid.status_code,
                    "invalid_cursor_rejected_before_service": True,
                    "foreign_company_distinct": True,
                    "foreign_record_id": foreign_id,
                    "cross_scope_exact_ids": [row["id"] for row in cross_scope.json()["records"]],
                    "real_service_received_cursors": received_cursors,
                    "production_pagination_unchanged": True,
                }
            ),
        )
    )


def test_missing_captured_clause_has_a_bounded_diagnostic():
    request = SimpleNamespace(node=SimpleNamespace(user_properties=[]))
    with pytest.raises(pytest.fail.Exception, match="No actual specialist SELECT clause"):
        specialist._explain_specialist_clause(request, None, [], [], label="missing-clause")
    assert len(request.node.user_properties) == 1
    name, value = request.node.user_properties[0]
    assert name == "specialist_list_plan"
    assert json.loads(value) == {
        "label": "missing-clause", "missing_select_clause": True, "statements": 0
    }


def _statement(session, context, docket_id):
    return (
        select(IpDocketRecord.id)
        .where(
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.id == docket_id,
            visible_ip_dockets_filter(session, context=context),
        )
        .limit(1)
    )


def _assert_visibility(session, context, docket_id, expected, request, label):
    session.execute(text("SET LOCAL statement_timeout = '5s'"))
    statement = _statement(session, context, docket_id)
    actual = session.scalar(statement)
    sql = str(statement.compile(session.get_bind(), compile_kwargs={"literal_binds": True}))
    plan = session.scalar(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql))[0]
    work, _dockets, nodes = specialist._retain_specialist_plan(request, plan, label=label)
    assert actual == (docket_id if expected else None)
    assert work <= 2048
    memberships = session.scalar(
        select(func.count())
        .select_from(TeamMembership)
        .where(TeamMembership.membership_id == context.membership.id)
    )
    teams = [node for node in nodes if node.get("Relation Name") == "teams"]
    request.node.user_properties.append(
        (
            "active_team_workload",
            json.dumps(
                {
                    "label": label,
                    "actor_memberships": memberships,
                    "team_probes": sum(node["Actual Loops"] for node in teams),
                    "row_work": work,
                }
            ),
        )
    )
    assert sum(node["Actual Loops"] for node in teams) <= 2 * memberships
    assert all("Index" in node["Node Type"] for node in teams if node["Actual Loops"])


def test_stale_team_catalog_cannot_expand_specialist_page_work(
    migration_pg_engine, registered_intake, monkeypatch, request
):
    original_seed = specialist._seed_team_catalog_noise

    def stale_seed(session, company, actor, **kwargs):
        return original_seed(session, company, actor, **{**kwargs, "fresh_statistics": False})

    monkeypatch.setattr(specialist, "_seed_team_catalog_noise", stale_seed)
    try:
        specialist.test_ten_thousand_records_list_bounds_queries_and_omits_ungranted_rows(
            migration_pg_engine, registered_intake, request
        )
    finally:
        with migration_pg_engine.begin() as connection:
            for table in ("teams", "team_memberships"):
                connection.execute(text(f"ALTER TABLE {table} RESET (autovacuum_enabled)"))
            assert all(
                not options
                for options in connection.scalars(
                    text(
                        "SELECT reloptions FROM pg_class "
                        "WHERE oid IN ('teams'::regclass, 'team_memberships'::regclass)"
                    )
                )
            )


def test_later_team_grant_wall_and_live_membership_changes_keep_the_same_policy(
    migration_pg_engine, request
):
    now = datetime.now(UTC)
    with Session(migration_pg_engine) as session:
        company = _seed_company(session)
        actor = _seed_membership(session, company, role="owner")
        specialist._seed_team_catalog_noise(session, company, actor)
        docket = IpDocketRecord(
            company_id=company, title="Later team authority", record_type="design_intake",
            restricted=True,
        )
        teams = [
            Team(company_id=company, name=f"Actor team {index}", slug=f"actor-team-{index}")
            for index in range(3)
        ]
        session.add_all([docket, *teams])
        session.flush()
        associations = [TeamMembership(team_id=team.id, membership_id=actor) for team in teams]
        session.add_all(associations)
        grant = MatterAccessGrant(
            company_id=company, ip_docket_id=docket.id, team_id=teams[-1].id,
            granted_by_membership_id=actor,
        )
        session.add(grant)
        session.commit()
        context = _ip_race_context(session, company_id=company, membership_id=actor)
        target = docket.id

        def check(expected, label):
            _assert_visibility(session, context, target, expected, request, label)

        check(True, "later-team:grant")
        direct = MatterAccessGrant(
            company_id=company, ip_docket_id=target, membership_id=actor,
            granted_by_membership_id=actor,
        )
        wall = EthicalWall(
            company_id=company, ip_docket_id=target, excluded_team_id=teams[-1].id,
            created_by_membership_id=actor,
        )
        session.add_all([direct, wall])
        session.commit()
        check(False, "later-team:wall-over-owner-and-direct-grant")
        teams[-1].is_active = False
        session.commit()
        check(True, "later-team:inactive-wall-does-not-veto-direct-grant")
        teams[-1].is_active = True
        session.delete(associations[-1])
        session.commit()
        check(True, "later-team:warm-membership-removal")
        direct.revoked_at = now
        session.commit()
        check(False, "later-team:removed-membership-no-team-grant")
        session.add(TeamMembership(team_id=teams[-1].id, membership_id=actor))
        session.commit()
        check(False, "later-team:restored-membership-wall-still-wins")
        wall.revoked_at = now
        session.commit()
        check(True, "later-team:current-wall-revocation")
        for effective, expiry, revoked, expected in (
            (now + timedelta(days=1), None, None, False),
            (now - timedelta(days=2), now - timedelta(days=1), None, False),
            (now - timedelta(days=2), now + timedelta(days=1), now, False),
            (now - timedelta(days=2), now + timedelta(days=1), None, True),
        ):
            grant.effective_from, grant.expires_at, grant.revoked_at = effective, expiry, revoked
            session.commit()
            check(expected, "later-team:grant-window")
        for effective, expiry, revoked, expected in (
            (now + timedelta(days=1), None, None, True),
            (now - timedelta(days=2), now - timedelta(days=1), None, True),
            (now - timedelta(days=2), None, now, True),
            (now - timedelta(days=2), now + timedelta(days=1), None, False),
        ):
            wall.effective_from, wall.expires_at, wall.revoked_at = effective, expiry, revoked
            session.commit()
            check(expected, "later-team:wall-window")
        wall.revoked_at = now
        grant.revoked_at = now
        unused = Team(company_id=company, name="Unjoined successor", slug="unjoined-successor")
        session.add(unused)
        session.flush()
        session.add(
            MatterAccessGrant(
                company_id=company, ip_docket_id=target, team_id=unused.id,
                granted_by_membership_id=actor,
            )
        )
        session.commit()
        check(False, "later-team:wrong-subject-successor-is-not-authority")


def test_foreign_association_and_own_inactive_team_do_not_expand_access(
    migration_pg_engine, request
):
    with Session(migration_pg_engine) as session:
        company = _seed_company(session)
        actor = _seed_membership(session, company, role="owner")
        inactive = specialist._seed_team_catalog_noise(session, company, actor)
        foreign = session.scalar(select(Team).where(Team.company_id != company, Team.is_active))
        docket = IpDocketRecord(
            company_id=company, title="Own restricted record", restricted=True,
            record_type="design_intake",
        )
        foreign_docket = IpDocketRecord(
            company_id=foreign.company_id, title="Foreign restricted record", restricted=True,
            record_type="design_intake",
        )
        session.add_all([docket, foreign_docket])
        session.flush()
        session.add_all(
            [
                TeamMembership(team_id=foreign.id, membership_id=actor),
                TeamMembership(team_id=inactive, membership_id=actor),
                MatterAccessGrant(
                    company_id=foreign.company_id, ip_docket_id=foreign_docket.id,
                    team_id=foreign.id,
                ),
                MatterAccessGrant(company_id=company, ip_docket_id=docket.id, team_id=inactive),
            ]
        )
        session.commit()
        context = _ip_race_context(session, company_id=company, membership_id=actor)
        _assert_visibility(session, context, docket.id, False, request, "foreign:own-record-hidden")
        _assert_visibility(
            session, context, foreign_docket.id, False, request, "foreign:tenant-filter-denies"
        )
        direct = MatterAccessGrant(
            company_id=company, ip_docket_id=docket.id, membership_id=actor,
            granted_by_membership_id=actor,
        )
        wall = EthicalWall(
            company_id=company, ip_docket_id=docket.id, excluded_team_id=inactive,
            created_by_membership_id=actor,
        )
        session.add_all([direct, wall])
        session.commit()
        _assert_visibility(session, context, docket.id, True, request, "inactive:direct-grant")
        session.get(Team, inactive).is_active = True
        session.commit()
        _assert_visibility(session, context, docket.id, False, request, "active:wall-wins")
        wall.revoked_at = datetime.now(UTC)
        session.commit()
        _assert_visibility(session, context, docket.id, True, request, "active:wall-revoked")
