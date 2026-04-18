"""Teams + team-scoped visibility regression (Sprint 8c BG-026)."""
from __future__ import annotations

from fastapi.testclient import TestClient


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
    return resp.json()


def _login(client: TestClient, email: str, password: str, slug: str) -> str:
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "company_slug": slug},
    )
    assert resp.status_code == 200, resp.text
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
                "status": "active",
            },
        )
        assert resp.status_code == 200, resp.text
        matter = resp.json()
        if team_id is not None:
            patch = client.patch(
                f"/api/matters/{matter['id']}",
                headers=owner_headers,
                json={"team_id": team_id},
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
