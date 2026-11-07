"""Teams + team-scoped visibility regression (Sprint 8c BG-026)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, TeamMembership
from caseops_api.db.session import get_session_factory
from caseops_api.services import teams as team_service
from caseops_api.services.activity_reports import MEANINGFUL_ACTIVITY_ACTIONS


def _bootstrap(client: TestClient, slug: str) -> dict[str, str]:
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"Teams Test {slug}",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Teams Owner",
            "owner_email": f"owner-{slug}@example.com",
            "owner_password": "TeamsPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    # These journeys select explicit Bearer principals; a login cookie wins in production.
    client.cookies.clear()
    return resp.json()


def _login(client: TestClient, email: str, password: str, slug: str) -> str:
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "company_slug": slug},
    )
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return resp.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _invite_member(
    client: TestClient, owner_token: str, slug: str, email: str, role: str = "member"
) -> dict[str, str]:
    resp = client.post(
        "/api/companies/current/users",
        headers=_headers(owner_token),
        json={
            "full_name": "Member User",
            "email": email,
            "password": "MemberPass123!",
            "role": role,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _membership_state(
    team_membership_id: str,
) -> tuple[TeamMembership, list[AuditEvent]]:
    factory = get_session_factory()
    with factory() as session:
        membership = session.get(TeamMembership, team_membership_id)
        assert membership is not None
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.target_type == "team_membership",
                    AuditEvent.target_id == team_membership_id,
                )
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            )
        )
        return membership, events


@pytest.mark.parametrize("initial_is_lead", [False, True], ids=["promote", "demote"])
@pytest.mark.parametrize("writer", ["update_only", "legacy_upsert"])
def test_team_lead_change_persists_and_audits_once(
    client: TestClient, initial_is_lead: bool, writer: str,
) -> None:
    assert_team_lead_change_persists_and_audits_once(client, initial_is_lead, writer)


def assert_team_lead_change_persists_and_audits_once(
    client: TestClient, initial_is_lead: bool, writer: str,
) -> None:
    slug = "teams-lead-audit"
    boot = _bootstrap(client, slug)
    token = boot["access_token"]
    headers = _headers(token)
    member = _invite_member(client, token, slug, f"member-{slug}@example.com")
    membership_id = member["membership_id"]
    actor_id = boot["membership"]["id"]
    assert membership_id != actor_id
    create = client.post(
        "/api/teams/", headers=headers,
        json={"name": "Lead audit", "slug": "lead-audit"},
    )
    assert create.status_code == 201, create.text
    team_id = create.json()["id"]
    url = f"/api/teams/{team_id}/members"
    add = client.post(
        url, headers=headers,
        json={"membership_id": membership_id, "is_lead": initial_is_lead},
    )
    assert add.status_code == 200, add.text
    team_membership_id = add.json()["members"][0]["id"]
    persisted, events = _membership_state(team_membership_id)
    assert persisted.is_lead is initial_is_lead
    assert len(events) == 1
    added = events[0]
    assert added.action == "team_membership.added"
    assert added.company_id == boot["company"]["id"]
    assert added.actor_membership_id == actor_id
    assert added.actor_type == "human"
    assert added.result == "success"
    assert json.loads(added.metadata_json) == {
        "team_id": team_id, "membership_id": membership_id,
        "is_lead": initial_is_lead,
    }

    new_is_lead = not initial_is_lead
    if writer == "update_only":
        method = "PATCH"
        lead_url = f"{url}/{team_membership_id}/lead"
        payload = {"is_lead": new_is_lead}
    else:
        method = "POST"
        lead_url = url
        payload = {"membership_id": membership_id, "is_lead": new_is_lead}
    changed = client.request(method, lead_url, headers=headers, json=payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["member_count"] == 1
    assert changed.json()["members"][0]["id"] == team_membership_id
    assert changed.json()["members"][0]["is_lead"] is new_is_lead
    persisted, events = _membership_state(team_membership_id)
    assert persisted.team_id == team_id
    assert persisted.membership_id == membership_id
    assert persisted.is_lead is new_is_lead
    assert len(events) == 2
    assert events[0].id == added.id
    updated = events[1]
    assert updated.action == "team_membership.updated"
    assert updated.action in MEANINGFUL_ACTIVITY_ACTIONS
    assert updated.company_id == boot["company"]["id"]
    assert updated.actor_membership_id == actor_id
    assert updated.actor_type == "human"
    assert updated.result == "success"
    assert json.loads(updated.metadata_json) == {
        "team_id": team_id, "membership_id": membership_id,
        "before": {"is_lead": initial_is_lead},
        "after": {"is_lead": new_is_lead},
    }

    replay = client.request(method, lead_url, headers=headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["member_count"] == 1
    assert replay.json()["members"][0]["id"] == team_membership_id
    persisted, replay_events = _membership_state(team_membership_id)
    assert persisted.is_lead is new_is_lead
    assert [event.id for event in replay_events] == [event.id for event in events]


@pytest.mark.parametrize(
    ("attempt", "expected_status"),
    [
        ("non_manager", 403), ("foreign_team", 404), ("foreign_member", 400),
        ("patch_non_manager", 403), ("patch_foreign_team", 404),
        ("patch_foreign_row", 409), ("patch_company_membership_id", 409),
    ],
)
def test_team_lead_change_denials_preserve_membership_and_audit(
    client: TestClient, attempt: str, expected_status: int,
) -> None:
    assert_team_lead_change_denials_preserve_membership_and_audit(client, attempt, expected_status)


def assert_team_lead_change_denials_preserve_membership_and_audit(
    client: TestClient, attempt: str, expected_status: int,
) -> None:
    slug = "teams-lead-boundary"
    boot = _bootstrap(client, slug)
    token = boot["access_token"]
    headers = _headers(token)
    email = f"member-{slug}@example.com"
    member = _invite_member(client, token, slug, email)
    create = client.post(
        "/api/teams/", headers=headers,
        json={"name": "Lead boundary", "slug": "lead-boundary"},
    )
    assert create.status_code == 201, create.text
    team_id = create.json()["id"]
    membership_id = member["membership_id"]
    add = client.post(
        f"/api/teams/{team_id}/members", headers=headers,
        json={"membership_id": membership_id, "is_lead": False},
    )
    assert add.status_code == 200, add.text
    team_membership_id = add.json()["members"][0]["id"]
    _, before_events = _membership_state(team_membership_id)
    assert len(before_events) == 1

    attempt_headers = headers
    attempt_company = boot["company"]["id"]
    attempt_actor = boot["membership"]["id"]
    row_id = team_membership_id
    if attempt.endswith("non_manager"):
        member_token = _login(client, email, "MemberPass123!", slug)
        attempt_headers = _headers(member_token)
        attempt_actor = membership_id
    elif attempt == "patch_company_membership_id":
        row_id = membership_id
    else:
        other = _bootstrap(client, "teams-lead-other")
        membership_id = other["membership"]["id"]
        if attempt.endswith("foreign_team"):
            attempt_headers = _headers(other["access_token"])
            attempt_company = other["company"]["id"]
            attempt_actor = membership_id
        elif attempt == "patch_foreign_row":
            other_headers = _headers(other["access_token"])
            other_team = client.post(
                "/api/teams/", headers=other_headers,
                json={"name": "Other team", "slug": "other-team"},
            )
            assert other_team.status_code == 201, other_team.text
            other_add = client.post(
                f"/api/teams/{other_team.json()['id']}/members", headers=other_headers,
                json={"membership_id": membership_id},
            )
            assert other_add.status_code == 200, other_add.text
            row_id = other_add.json()["members"][0]["id"]

    principal = client.get("/api/auth/me", headers=attempt_headers)
    assert principal.status_code == 200, principal.text
    assert "cookie" not in principal.request.headers
    assert principal.json()["company"]["id"] == attempt_company
    assert principal.json()["membership"]["id"] == attempt_actor

    if attempt.startswith("patch_"):
        rejected = client.patch(
            f"/api/teams/{team_id}/members/{row_id}/lead", headers=attempt_headers,
            json={"is_lead": True},
        )
    else:
        rejected = client.post(
            f"/api/teams/{team_id}/members", headers=attempt_headers,
            json={"membership_id": membership_id, "is_lead": True},
        )
    assert "cookie" not in rejected.request.headers
    assert rejected.status_code == expected_status, rejected.text
    persisted, after_events = _membership_state(team_membership_id)
    assert persisted.is_lead is False
    assert persisted.team_id == team_id
    assert persisted.membership_id == member["membership_id"]
    assert [event.id for event in after_events] == [event.id for event in before_events]
    read_back = client.get("/api/teams/", headers=headers)
    assert read_back.status_code == 200, read_back.text
    assert "cookie" not in read_back.request.headers
    team = next(row for row in read_back.json()["teams"] if row["id"] == team_id)
    assert team["member_count"] == 1
    assert team["members"][0]["id"] == team_membership_id
    assert team["members"][0]["is_lead"] is False


def test_team_lead_and_audit_roll_back_together(client: TestClient, monkeypatch) -> None:
    boot = _bootstrap(client, "team-lead-rollback")
    headers = _headers(boot["access_token"])
    create = client.post(
        "/api/teams/", headers=headers, json={"name": "Rollback", "slug": "rollback"},
    )
    assert create.status_code == 201, create.text
    url = f"/api/teams/{create.json()['id']}/members"
    add = client.post(url, headers=headers, json={"membership_id": boot["membership"]["id"]})
    assert add.status_code == 200, add.text
    row_id = add.json()["members"][0]["id"]
    _, before_events = _membership_state(row_id)
    record = team_service.record_from_context

    def fail_after_flush(*args, **kwargs):
        record(*args, **kwargs)
        raise RuntimeError("abort before commit")

    monkeypatch.setattr(team_service, "record_from_context", fail_after_flush)
    with pytest.raises(RuntimeError, match="abort before commit"):
        client.patch(f"{url}/{row_id}/lead", headers=headers, json={"is_lead": True})

    persisted, after_events = _membership_state(row_id)
    assert persisted.is_lead is False
    assert [event.id for event in after_events] == [event.id for event in before_events]


def test_stale_team_membership_commands_preserve_replacement(client: TestClient) -> None:
    boot = _bootstrap(client, "team-stale-row")
    headers = _headers(boot["access_token"])
    member_id = boot["membership"]["id"]
    create = client.post(
        "/api/teams/", headers=headers, json={"name": "Stale row", "slug": "stale-row"},
    )
    assert create.status_code == 201, create.text
    team_id = create.json()["id"]
    members = f"/api/teams/{team_id}/members"
    removal = f"/api/teams/{team_id}/members/{member_id}"
    original = client.post(members, headers=headers, json={"membership_id": member_id})
    assert original.status_code == 200, original.text
    old_id = original.json()["members"][0]["id"]
    removed = client.delete(removal, headers=headers)
    assert removed.status_code == 200 and removed.json()["members"] == []
    stale_lead = f"/api/teams/{team_id}/members/{old_id}/lead"
    for replaced in (False, True):
        if replaced:
            added = client.post(members, headers=headers, json={"membership_id": member_id})
            assert added.status_code == 200, added.text
            new_id = added.json()["members"][0]["id"]
            assert new_id != old_id
        for rejected in (
            client.patch(stale_lead, headers=headers, json={"is_lead": True}),
            client.delete(removal, headers=headers, params={"expected_team_membership_id": old_id}),
        ):
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["code"] == "team_membership_changed"
        read_back = client.get("/api/teams/", headers=headers)
        assert read_back.status_code == 200, read_back.text
        rows = read_back.json()["teams"][0]["members"]
        if replaced:
            assert [(row["id"], row["is_lead"]) for row in rows] == [(new_id, False)]
        else:
            assert rows == []

    for payload in ({}, {"is_lead": "true"}, {"is_lead": True, "membership_id": member_id}):
        rejected = client.patch(
            f"/api/teams/{team_id}/members/{new_id}/lead", headers=headers, json=payload,
        )
        assert rejected.status_code == 422, rejected.text
    persisted, events = _membership_state(new_id)
    assert persisted.is_lead is False
    assert [event.action for event in events] == ["team_membership.added"]
    with get_session_factory()() as session:
        assert session.get(TeamMembership, old_id) is None
        assert list(session.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.target_type == "team_membership", AuditEvent.target_id == old_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )) == ["team_membership.added", "team_membership.removed"]


def test_team_crud_and_membership(client: TestClient) -> None:
    session = _bootstrap(client, "teams-crud")
    token = session["access_token"]
    headers = _headers(token)

    # Initially: no teams, scoping off.
    initial = client.get("/api/teams/", headers=headers).json()
    assert initial["teams"] == []
    assert initial["team_scoping_enabled"] is False

    # Create team.
    create = client.post(
        "/api/teams/",
        headers=headers,
        json={
            "name": "Litigation",
            "slug": "litigation",
            "kind": "practice_area",
            "description": "Bail, writs, commercial suits.",
        },
    )
    assert create.status_code == 201, create.text
    team = create.json()
    assert team["kind"] == "practice_area"
    assert team["member_count"] == 0

    # Duplicate slug → 409.
    dup = client.post(
        "/api/teams/",
        headers=headers,
        json={"name": "Litigation 2", "slug": "litigation"},
    )
    assert dup.status_code == 409

    # Add owner's own membership to the team.
    owner_membership_id = session["membership"]["id"]
    add = client.post(
        f"/api/teams/{team['id']}/members",
        headers=headers,
        json={"membership_id": owner_membership_id, "is_lead": True},
    )
    assert add.status_code == 200
    added = add.json()
    assert added["member_count"] == 1
    assert added["members"][0]["is_lead"] is True

    # Re-adding is idempotent — no duplicate row, and is_lead can flip.
    flip = client.post(
        f"/api/teams/{team['id']}/members",
        headers=headers,
        json={"membership_id": owner_membership_id, "is_lead": False},
    )
    assert flip.status_code == 200
    assert flip.json()["member_count"] == 1
    assert flip.json()["members"][0]["is_lead"] is False

    # Remove.
    rm = client.delete(
        f"/api/teams/{team['id']}/members/{owner_membership_id}",
        headers=headers,
    )
    assert rm.status_code == 200
    assert rm.json()["member_count"] == 0

    # Delete the team.
    delete = client.delete(f"/api/teams/{team['id']}", headers=headers)
    assert delete.status_code == 204


def test_team_scoping_gates_visibility_for_member(client: TestClient) -> None:
    """Core Sprint 8c invariant: when team scoping is on, a member sees
    only team-less matters + matters in teams they belong to."""
    slug = "teams-visibility"
    session = _bootstrap(client, slug)
    owner_token = session["access_token"]
    owner_headers = _headers(owner_token)

    # Create a member user to test scoping against.
    member_email = f"member-{slug}@example.com"
    _invite_member(client, owner_token, slug, member_email, role="member")
    member_token = _login(client, member_email, "MemberPass123!", slug)
    member_headers = _headers(member_token)

    # Owner creates two teams.
    lit_team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Litigation", "slug": "lit"},
    ).json()
    ip_team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "IP", "slug": "ip"},
    ).json()

    # Owner creates three matters — one on lit team, one on ip team,
    # one with no team (firm-wide).
    def make_matter(code: str, team_id: str | None) -> dict[str, str]:
        resp = client.post(
            "/api/matters/",
            headers=owner_headers,
            json={
                "title": f"Matter {code}",
                "matter_code": code,
                "practice_area": "criminal",
                "forum_level": "high_court",
                "status": "intake",
            },
        )
        assert resp.status_code == 200, resp.text
        matter = resp.json()
        if team_id is not None:
            patch = client.patch(
                f"/api/matters/{matter['id']}",
                headers=owner_headers,
                json={
                    "team_id": team_id,
                    "expected_updated_at": matter["updated_at"],
                },
            )
            assert patch.status_code == 200, patch.text
            matter = patch.json()
        return matter

    lit_matter = make_matter("LIT-001", lit_team["id"])
    ip_matter = make_matter("IP-001", ip_team["id"])
    firm_matter = make_matter("FIRM-001", None)

    # Before scoping is enabled, the member sees all three.
    before = client.get("/api/matters/", headers=member_headers).json()
    codes_before = {m["matter_code"] for m in before["matters"]}
    assert codes_before == {"LIT-001", "IP-001", "FIRM-001"}

    # Put member on the IP team.
    member_membership_id = None
    users = client.get(
        "/api/companies/current/users", headers=owner_headers
    ).json()
    for user in users.get("users", users):
        if user.get("email") == member_email:
            member_membership_id = user["membership_id"]
            break
    assert member_membership_id, "could not resolve member membership id"

    client.post(
        f"/api/teams/{ip_team['id']}/members",
        headers=owner_headers,
        json={"membership_id": member_membership_id},
    )

    # Enable scoping.
    scope = client.put(
        "/api/teams/scoping",
        headers=owner_headers,
        json={"enabled": True},
    )
    assert scope.status_code == 200
    assert scope.json()["enabled"] is True

    # Member now sees firm-wide + IP, NOT Litigation.
    after = client.get("/api/matters/", headers=member_headers).json()
    codes_after = {m["matter_code"] for m in after["matters"]}
    assert codes_after == {"IP-001", "FIRM-001"}
    assert "LIT-001" not in codes_after

    attachment = client.post(
        f"/api/matters/{lit_matter['id']}/attachments",
        headers=owner_headers,
        files={"file": ("team-secret.txt", b"team scoped", "text/plain")},
    )
    assert attachment.status_code == 200, attachment.text
    hidden_download = client.get(
        (
            f"/api/matters/{lit_matter['id']}/attachments/"
            f"{attachment.json()['id']}/download"
        ),
        headers=member_headers,
    )
    assert hidden_download.status_code == 404

    # Owner still sees everything regardless of scoping.
    owner_all = client.get("/api/matters/", headers=owner_headers).json()
    assert {m["matter_code"] for m in owner_all["matters"]} == {
        "LIT-001",
        "IP-001",
        "FIRM-001",
    }
    # Avoid unused-variable lint on the matter fixtures we created.
    _ = (lit_matter, ip_matter, firm_matter)


def test_team_endpoints_reject_non_admin(client: TestClient) -> None:
    slug = "teams-perms"
    session = _bootstrap(client, slug)
    owner_token = session["access_token"]

    member_email = f"mem-{slug}@example.com"
    _invite_member(client, owner_token, slug, member_email, role="member")
    member_token = _login(client, member_email, "MemberPass123!", slug)
    member_headers = _headers(member_token)

    # Member can read teams list (no gate) but cannot create / toggle scoping.
    list_resp = client.get("/api/teams/", headers=member_headers)
    assert list_resp.status_code == 200

    create_resp = client.post(
        "/api/teams/",
        headers=member_headers,
        json={"name": "Sneaky", "slug": "sneaky"},
    )
    assert create_resp.status_code == 403

    scope_resp = client.put(
        "/api/teams/scoping",
        headers=member_headers,
        json={"enabled": True},
    )
    assert scope_resp.status_code == 403
