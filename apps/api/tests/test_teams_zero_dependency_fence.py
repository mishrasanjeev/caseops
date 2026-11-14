"""Teams zero-dependency and synchronous-route contracts; no database required."""
from __future__ import annotations

import asyncio
import inspect
from threading import Event, get_ident
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.dialects import postgresql

from caseops_api.api.dependencies import get_current_context
from caseops_api.api.routes import teams as routes
from caseops_api.db.session import get_db_session
from caseops_api.schemas.teams import TeamListResponse
from caseops_api.services import teams


class _SnapshotSession:
    def __init__(self, answers=(), dockets=()):
        self.answers = iter(answers)
        self.dockets = list(dockets)
        self.probes = []
        self.docket_queries = []

    def scalar(self, statement):
        self.probes.append(statement)
        return next(self.answers)

    def scalars(self, statement):
        self.docket_queries.append(statement)
        return iter(self.dockets)


@pytest.mark.parametrize(
    "answers", [(False, False, False), (True, False, False),
                (False, True, False), (False, False, True)],
    ids=["none", "matter", "grant", "wall"],
)
def test_dependency_probes_compile_to_three_tenant_qualified_unfiltered_exists(answers):
    session = _SnapshotSession(answers)
    assert teams._team_has_access_dependencies(
        session, company_id="company", team_id="team",
    ) is any(answers)
    assert len(session.probes) == 3
    for statement, table, column in zip(
        session.probes,
        ["matters", "matter_access_grants", "ethical_walls"],
        ["team_id", "team_id", "excluded_team_id"], strict=True,
    ):
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = " ".join(str(compiled).split())
        assert "SELECT EXISTS (SELECT" in sql
        assert f"FROM {table} WHERE {table}.company_id = " in sql
        assert f"AND {table}.{column} = " in sql
        assert sorted(compiled.params.values()) == ["company", "team"]
        for excluded in (
            "revoked_at", "effective_from", "expires_at", "is_active", "status",
            "ip_docket_records", "LIMIT", "FOR UPDATE",
        ):
            assert excluded not in sql


def test_zero_dependency_snapshot_never_enumerates_dockets_or_roles(monkeypatch):
    session = _SnapshotSession([False, False, False])

    def unexpected_roles(*args, **kwargs):
        pytest.fail("A zero-dependency team must not load any IP responsibility.")

    monkeypatch.setattr(teams, "_operational_ip_docket_role_membership_ids", unexpected_roles)
    assert teams._operational_ip_role_fence_snapshot(
        session, company_id="company", membership_scope={"member"}, team_id="team",
    ) == {}
    assert len(session.probes) == 3
    assert session.docket_queries == []


@pytest.mark.parametrize("dependency", ["matter", "grant", "wall"])
def test_any_dependency_keeps_the_original_full_tenant_snapshot(monkeypatch, dependency):
    dockets = [SimpleNamespace(id="related", matter_id=None),
               SimpleNamespace(id="unrelated", matter_id="other-matter")]
    visited = []

    def roles(_session, *, docket):
        visited.append(docket.id)
        return {"member", "other-member"}

    monkeypatch.setattr(teams, "_operational_ip_docket_role_membership_ids", roles)
    original = _SnapshotSession(dockets=dockets)
    expected = teams._operational_ip_role_fence_snapshot(
        original, company_id="company", membership_scope={"member"},
    )
    answers = [name == dependency for name in ["matter", "grant", "wall"]]
    scoped = _SnapshotSession(answers, dockets)
    actual = teams._operational_ip_role_fence_snapshot(
        scoped, company_id="company", membership_scope={"member"}, team_id="team",
    )
    assert actual == expected
    assert set(actual) == {"related", "unrelated"}
    assert visited == ["related", "unrelated", "related", "unrelated"]
    assert str(scoped.docket_queries[0]) == str(original.docket_queries[0])
    assert scoped.docket_queries[0].compile().params == original.docket_queries[0].compile().params


@pytest.mark.parametrize("include_empty", [False, True])
@pytest.mark.parametrize("linked_only", [False, True])
def test_unscoped_snapshot_never_uses_the_team_dependency_shortcut(
    monkeypatch, include_empty, linked_only,
):
    session = _SnapshotSession(dockets=[SimpleNamespace(id="docket", matter_id="matter")])

    def unexpected_probe(*args, **kwargs):
        pytest.fail("Global scoping must keep its original all-linked fence.")

    monkeypatch.setattr(teams, "_team_has_access_dependencies", unexpected_probe)
    monkeypatch.setattr(teams, "_operational_ip_docket_role_membership_ids", lambda *a, **k: set())
    result = teams._operational_ip_role_fence_snapshot(
        session, company_id="company", membership_scope=None,
        include_empty=include_empty, linked_only=linked_only,
    )
    assert result == ({"docket": teams._IpRoleFenceEntry("matter", ())} if include_empty else {})
    assert len(session.docket_queries) == 1
    assert ("matter_id IS NOT NULL" in str(session.docket_queries[0])) is linked_only


def test_empty_membership_scope_with_a_dependency_still_uses_the_original_scan(monkeypatch):
    session = _SnapshotSession([False, True, False], [SimpleNamespace(id="docket", matter_id=None)])
    visited = []

    def roles(_session, *, docket):
        visited.append(docket.id)
        return {"member"}

    monkeypatch.setattr(teams, "_operational_ip_docket_role_membership_ids", roles)
    assert teams._operational_ip_role_fence_snapshot(
        session, company_id="company", membership_scope=set(), team_id="team",
    ) == {}
    assert visited == ["docket"]


@pytest.mark.parametrize("changed_checkpoint", [2, 3], ids=["before-parents", "after-parents"])
def test_each_snapshot_checkpoint_rechecks_dependencies_and_rejects_new_roles(
    monkeypatch, changed_checkpoint,
):
    answers = [False] * (3 * (changed_checkpoint - 1)) + [False, True, False]
    session = _SnapshotSession(answers, [SimpleNamespace(id="docket", matter_id=None)])
    monkeypatch.setattr(
        teams, "_operational_ip_docket_role_membership_ids", lambda *a, **k: {"member"},
    )
    kwargs = {"company_id": "company", "membership_scope": {"member"}, "team_id": "team"}
    expected = teams._operational_ip_role_fence_snapshot(session, **kwargs)
    assert expected == {}
    with pytest.raises(HTTPException) as rejected:
        teams._assert_fence_unchanged_before_parent_locks(session, expected=expected, **kwargs)
        assert changed_checkpoint == 3
        teams._lock_ip_role_fence_parents(session, expected=expected, **kwargs)
    assert rejected.value.status_code == 409
    assert rejected.value.detail["code"] == "ip_team_access_responsibility_changed"
    assert len(session.probes) == 3 * changed_checkpoint
    assert len(session.docket_queries) == 1


@pytest.mark.parametrize("endpoint", [
    "get_teams", "post_team", "patch_team", "delete_team_endpoint",
    "post_team_member", "delete_team_member", "patch_team_member_lead", "put_team_scoping",
])
def test_all_eight_teams_routes_are_registered_sync_db_endpoints(endpoint):
    function = getattr(routes, endpoint)
    assert not inspect.iscoroutinefunction(function)
    assert sum(route.endpoint is function for route in routes.router.routes) == 1


def test_blocked_team_db_work_does_not_monopolize_the_http_event_loop(monkeypatch):
    started, release, finished = Event(), Event(), Event()
    thread_ids = []

    def blocked_list(_session, *, context):
        thread_ids.append(get_ident())
        started.set()
        try:
            if not release.wait(3):
                raise AssertionError("The test must release its blocked synchronous service.")
            return TeamListResponse(teams=[], team_scoping_enabled=False)
        finally:
            finished.set()

    monkeypatch.setattr(routes, "list_teams", blocked_list)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/teams")
    app.dependency_overrides[get_current_context] = lambda: object()
    app.dependency_overrides[get_db_session] = lambda: object()

    @app.get("/unrelated")
    async def unrelated():
        return {"responsive": True}

    async def exercise():
        event_loop_thread = get_ident()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://caseops.test", trust_env=False,
            headers={"X-CaseOps-Automated-Test": "no-paid-providers"},
        ) as client:
            pending = asyncio.create_task(client.get("/api/teams/"))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                response = await asyncio.wait_for(client.get("/unrelated"), 1)
                assert response.status_code == 200
                assert response.json() == {"responsive": True}
                assert not release.is_set() and not finished.is_set()
                assert len(thread_ids) == 1
                assert thread_ids[0] != event_loop_thread
            finally:
                release.set()
                result = await asyncio.wait_for(pending, 4)
            assert result.status_code == 200
            assert result.json() == {"teams": [], "team_scoping_enabled": False}

    asyncio.run(exercise())
