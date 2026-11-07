"""Deterministic Teams writer interleavings on migrated PostgreSQL."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from caseops_api.db.models import AuditEvent, Company, CompanyMembership, TeamMembership
from caseops_api.db.session import get_session_factory
from caseops_api.services import teams
from caseops_api.services.audit import record_from_context
from tests.test_postgres_validation import _ip_race_context
from tests.test_teams import _bootstrap, _headers, _invite_member, _membership_state

pytestmark = pytest.mark.postgres


@pytest.fixture
def team_fixture(isolated_postgres_client):
    client = isolated_postgres_client
    slug = "teams-writer-race"
    boot = _bootstrap(client, slug)
    token = boot["access_token"]
    headers = _headers(token)
    member = _invite_member(client, token, slug, "teams-race-member@example.com")
    created = client.post(
        "/api/teams/", headers=headers, json={"name": "Writer race", "slug": "writer-race"},
    )
    assert created.status_code == 201, created.text
    team_id = created.json()["id"]
    member_id = member["membership_id"]
    added = client.post(
        f"/api/teams/{team_id}/members", headers=headers, json={"membership_id": member_id},
    )
    assert added.status_code == 200, added.text
    return (
        boot["company"]["id"], boot["membership"]["id"], team_id,
        member_id, added.json()["members"][0]["id"],
    )


def _pid(session):
    return session.scalar(text("SELECT pg_backend_pid()"))


def _wait_on(engine, *, waiter, holder, sql_fragment):
    deadline = monotonic() + 5
    last = None
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
        while monotonic() < deadline:
            last = observer.execute(
                text("SELECT query, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": waiter},
            ).one_or_none()
            if last is not None and holder in last[1]:
                assert sql_fragment in last[0].lower(), last
                return
            sleep(0.01)
    pytest.fail(f"No PostgreSQL wait on {sql_fragment!r}; last observation: {last!r}")


def _run_writer(factory, identity, ready, writer):
    company_id, actor_id, team_id, member_id, row_id = identity
    with factory() as session:
        session.execute(text("SET LOCAL lock_timeout = '8s'"))
        session.execute(text("SET LOCAL statement_timeout = '10s'"))
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        ready.put(_pid(session))
        try:
            if writer == "patch":
                result = teams.update_team_member_lead(
                    session, context=context, team_id=team_id,
                    team_membership_id=row_id, is_lead=True,
                )
            elif writer == "fenced_remove":
                result = teams.remove_team_member(
                    session, context=context, team_id=team_id, membership_id=member_id,
                    expected_team_membership_id=row_id,
                )
            else:
                result = teams.add_team_member(
                    session, context=context, team_id=team_id,
                    membership_id=actor_id if writer == "legacy_add" else member_id,
                    is_lead=True,
                )
            session.commit()
        except HTTPException as exc:
            session.rollback()
            return exc.status_code, exc.detail
        return 200, result


@pytest.mark.parametrize("writer", ["patch", "legacy_upsert", "legacy_add"])
def test_scoping_and_team_writers_serialize_at_company(team_fixture, monkeypatch, writer):
    company_id, actor_id, team_id, member_id, row_id = team_fixture
    factory = get_session_factory()
    ready = Queue()
    lock_memberships = teams.lock_company_memberships_for_assignment
    with ThreadPoolExecutor(max_workers=1) as pool, factory() as holder:
        holder_pid = _pid(holder)
        future = None

        def overlap_after_scoping_company_lock(session, **kwargs):
            nonlocal future
            if session is holder:
                future = pool.submit(_run_writer, factory, team_fixture, ready, writer)
                _wait_on(
                    holder.get_bind(), waiter=ready.get(timeout=5), holder=holder_pid,
                    sql_fragment="for no key update of companies",
                )
            return lock_memberships(session, **kwargs)

        monkeypatch.setattr(
            teams, "lock_company_memberships_for_assignment",
            overlap_after_scoping_company_lock,
        )
        context = _ip_race_context(holder, company_id=company_id, membership_id=actor_id)
        try:
            enabled = teams.set_team_scoping(holder, context=context, enabled=True)
            assert enabled is True
            holder.commit()
        finally:
            holder.rollback()
            if future is not None:
                status, result = future.result(timeout=12)
        assert future is not None
        assert status == 200, result

    expected_member = actor_id if writer == "legacy_add" else member_id
    written = next(member for member in result.members if member.membership_id == expected_member)
    assert written.is_lead is True
    assert (written.id != row_id) is (writer == "legacy_add")
    persisted, events = _membership_state(written.id)
    assert persisted.is_lead is True
    assert [event.action for event in events] == (
        ["team_membership.added"] if writer == "legacy_add"
        else ["team_membership.added", "team_membership.updated"]
    )
    if writer != "legacy_add":
        assert json.loads(events[-1].metadata_json) == {
            "team_id": team_id, "membership_id": member_id,
            "before": {"is_lead": False}, "after": {"is_lead": True},
        }
    with factory() as read:
        assert read.get(Company, company_id).team_scoping_enabled is True


@pytest.mark.parametrize(
    ("writer", "replace"),
    [("patch", False), ("patch", True), ("fenced_remove", True)],
    ids=["removed-lead", "replaced-lead", "replaced-removal"],
)
def test_stale_team_writer_waits_for_removal_and_never_mutates_replacement(
    team_fixture, writer, replace,
):
    company_id, actor_id, team_id, member_id, row_id = team_fixture
    factory = get_session_factory()
    ready = Queue()
    replacement_id = None
    with ThreadPoolExecutor(max_workers=1) as pool, factory() as holder:
        context = _ip_race_context(holder, company_id=company_id, membership_id=actor_id)
        result = teams.remove_team_member(
            holder, context=context, team_id=team_id, membership_id=member_id,
        )
        assert not result.members
        if replace:
            result = teams.add_team_member(
                holder, context=context, team_id=team_id, membership_id=member_id,
            )
            replacement_id = result.members[0].id
            assert replacement_id != row_id
        future = pool.submit(_run_writer, factory, team_fixture, ready, writer)
        try:
            _wait_on(
                holder.get_bind(), waiter=ready.get(timeout=5), holder=_pid(holder),
                sql_fragment="for no key update of companies",
            )
            holder.commit()
        finally:
            holder.rollback()
            status, detail = future.result(timeout=12)
    assert status == 409
    assert detail["code"] == "team_membership_changed"
    with factory() as read:
        assert read.get(TeamMembership, row_id) is None
        rows = list(read.scalars(select(TeamMembership).where(TeamMembership.team_id == team_id)))
        assert [(row.id, row.is_lead) for row in rows] == (
            [(replacement_id, False)] if replace else []
        )
        actions = list(read.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.target_id.in_([row_id, replacement_id]))
            .order_by(AuditEvent.created_at, AuditEvent.id)
        ))
        assert actions == ["team_membership.added", "team_membership.removed"] + (
            ["team_membership.added"] if replace else []
        )


def test_membership_first_revocation_can_audit_while_lead_rechecks_fresh_acl(team_fixture):
    company_id, actor_id, _team_id, _member_id, row_id = team_fixture
    factory = get_session_factory()
    ready = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool, factory() as holder:
        context = _ip_race_context(holder, company_id=company_id, membership_id=actor_id)
        actor = holder.scalar(
            select(CompanyMembership).where(CompanyMembership.id == actor_id).with_for_update()
        )
        actor.role = "viewer"
        holder.flush()
        future = pool.submit(_run_writer, factory, team_fixture, ready, "patch")
        try:
            _wait_on(
                holder.get_bind(), waiter=ready.get(timeout=5), holder=_pid(holder),
                sql_fragment="for update of company_memberships",
            )
            # The waiter owns Company NO KEY UPDATE; this audit's Company FK
            # still needs KEY SHARE while revocation holds Membership.
            holder.execute(text("SET LOCAL lock_timeout = '1s'"))
            record_from_context(
                holder, context, action="test.team_authority_revoked",
                target_type="company_membership", target_id=actor_id,
            )
            holder.commit()
        finally:
            holder.rollback()
            status, detail = future.result(timeout=12)
    assert status == 403
    assert detail == "Capability 'teams:manage' is required."
    persisted, events = _membership_state(row_id)
    assert persisted.is_lead is False
    assert [event.action for event in events] == ["team_membership.added"]
