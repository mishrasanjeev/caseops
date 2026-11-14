"""Real SQLite/TestClient regression for Teams sync-worker dispatch."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

from fastapi.testclient import TestClient

from caseops_api.api.routes import teams as team_routes
from tests.test_teams import _bootstrap, _headers, _invite_member


def test_blocked_team_removal_keeps_build_responsive_on_the_same_client_portal(
    client: TestClient, monkeypatch,
) -> None:
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    slug = "teams-http-responsiveness"
    boot = _bootstrap(client, slug)
    token = boot["access_token"]
    headers = {**_headers(token), "X-CaseOps-Automated-Test": "no-paid-providers"}
    member = _invite_member(client, token, slug, "teams-http-member@example.com")
    member_id = member["membership_id"]
    created = client.post(
        "/api/teams/", headers=headers,
        json={"name": "HTTP responsiveness", "slug": "http-responsiveness"},
    )
    assert created.status_code == 201, created.text
    team_id = created.json()["id"]
    added = client.post(
        f"/api/teams/{team_id}/members", headers=headers,
        json={"membership_id": member_id},
    )
    assert added.status_code == 200, added.text
    assert added.json()["member_count"] == 1
    row_id = added.json()["members"][0]["id"]
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["membership"]["id"] == boot["membership"]["id"]
    assert me.json()["company"]["id"] == boot["company"]["id"]

    # The existing fixture owns a single lifespan portal. Its bearer-cookie
    # wrapper only touches an empty jar here; neither concurrent route issues cookies.
    portal = client.portal
    assert portal is not None
    assert not client.app.dependency_overrides
    assert not list(client.cookies.jar)
    assert all("set-cookie" not in response.headers for response in [created, added, me])
    entered, release, delegated = Event(), Event(), Event()
    original_remove = team_routes.remove_team_member

    def blocked_remove(
        session, *, context, team_id, membership_id, expected_team_membership_id=None,
    ):
        assert client.portal is portal
        assert session.get_bind().dialect.name == "sqlite"
        assert context.company.id == boot["company"]["id"]
        assert context.membership.id == boot["membership"]["id"]
        assert team_id == created.json()["id"]
        assert membership_id == member_id
        assert expected_team_membership_id == row_id
        entered.set()
        assert release.wait(5), "The test did not release the bounded removal gate."
        delegated.set()
        return original_remove(
            session, context=context, team_id=team_id, membership_id=membership_id,
            expected_team_membership_id=expected_team_membership_id,
        )

    monkeypatch.setattr(team_routes, "remove_team_member", blocked_remove)

    def remove_member():
        assert client.portal is portal
        response = client.delete(
            f"/api/teams/{team_id}/members/{member_id}", headers=dict(headers),
            params={"expected_team_membership_id": row_id},
        )
        assert client.portal is portal
        return response

    def read_build():
        assert client.portal is portal
        response = client.get("/api/build", headers=dict(headers))
        completed_at = monotonic()
        completed_before_release = not release.is_set()
        assert client.portal is portal
        return response, completed_at, completed_before_release

    build_future = None
    delete_error = build_error = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        delete_future = pool.submit(remove_member)
        try:
            assert entered.wait(5), "The authenticated DELETE never entered its service."
            assert not delegated.is_set() and not delete_future.done()
            build_started_at = monotonic()
            build_future = pool.submit(read_build)
            build, completed_at, completed_before_release = build_future.result(timeout=1)
            assert completed_at - build_started_at < 1
            assert build.status_code == 200, build.text
            assert build.json()["service"] == "api"
            assert build.request.headers["authorization"] == headers["Authorization"]
            assert build.request.headers["x-caseops-automated-test"] == "no-paid-providers"
            assert completed_before_release and not release.is_set()
            assert not delegated.is_set() and not delete_future.done()
        finally:
            release.set()
            # exception() reaps without replacing an availability failure with
            # the worker's exception. Nested finally also reaps the other future.
            try:
                delete_error = delete_future.exception(timeout=6)
            finally:
                if build_future is not None:
                    build_error = build_future.exception(timeout=6)

    assert delete_future.done() and build_future is not None and build_future.done()
    assert delete_error is None, repr(delete_error)
    assert build_error is None, repr(build_error)
    assert delegated.is_set()
    removed = delete_future.result()
    assert removed.status_code == 200, removed.text
    assert removed.json()["id"] == team_id
    assert removed.json()["member_count"] == 0 and removed.json()["members"] == []
    assert removed.request.headers["authorization"] == headers["Authorization"]
    assert removed.request.headers["x-caseops-automated-test"] == "no-paid-providers"
    assert all("set-cookie" not in response.headers for response in [build, removed])
    assert client.portal is portal and not list(client.cookies.jar)
    persisted = client.get("/api/teams/", headers=headers)
    assert persisted.status_code == 200, persisted.text
    retained_team = next(team for team in persisted.json()["teams"] if team["id"] == team_id)
    assert retained_team["member_count"] == 0 and retained_team["members"] == []
