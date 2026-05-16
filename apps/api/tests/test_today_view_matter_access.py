"""P1-4 (matter-access scoping) — the Today cockpit and per-matter
next-action must never surface a matter the caller could not also see
in the matters list.

Before this fix the five today_view aggregators filtered on
``Matter.company_id`` only, so a member could see hearings / tasks /
drafts-in-review / overdue invoices / deadlines (and the next-action
card) for matters hidden from them by ``restricted_access`` without a
grant, an ethical wall, or team scoping. These tests assert the leak
is closed across all three access mechanisms, for every stream and for
next-action, while leaving an accessible control matter visible.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_today_view import (
    _create_matter,
    _seed_deadline,
    _seed_draft_in_review,
    _seed_hearing,
    _seed_invoice,
    _seed_task,
)

_TODAY = date.today()


def _invite_member(
    client: TestClient, owner_token: str, email: str, role: str = "member"
) -> tuple[str, str]:
    """Second membership in the bootstrap tenant (slug aster-legal).
    Returns (membership_id, member_access_token)."""
    create = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": f"Member {email.split('@')[0]}",
            "email": email,
            "role": role,
            "password": "MemberPass123!",
        },
    )
    assert create.status_code == 200, create.text
    membership_id = create.json()["membership_id"]
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": email,
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return membership_id, str(login.json()["access_token"])


def _seed_all_streams(client: TestClient, owner_token: str, matter_id: str) -> None:
    """Seed one row in every Today stream for a matter, as the owner
    (owners bypass all ACLs, so this works before we restrict it)."""
    _seed_hearing(matter_id, _TODAY + timedelta(days=3))
    # Unassigned task: would show for ANY tenant member if the matter
    # were visible — so it's the sharpest leak probe.
    _seed_task(matter_id, due_on=_TODAY + timedelta(days=2), owner=None)
    _seed_draft_in_review(client, owner_token, matter_id)
    _seed_invoice(matter_id, due_on=_TODAY - timedelta(days=5))
    _seed_deadline(matter_id, due_on=_TODAY + timedelta(days=2))


def _today(client: TestClient, token: str) -> dict:
    resp = client.get("/api/me/today", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _matter_ids_in_today(body: dict) -> set[str]:
    ids: set[str] = set()
    for stream in (
        "hearings_next_7d",
        "tasks_due_or_overdue",
        "drafts_in_review",
        "overdue_invoices",
        "deadlines_next_7d",
    ):
        for row in body[stream]:
            ids.add(row["matter"]["id"])
    return ids


def _next_action(client: TestClient, token: str, matter_id: str):
    resp = client.get(
        f"/api/matters/{matter_id}/next-action", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _assert_member_blocked(
    client: TestClient,
    *,
    member_token: str,
    hidden_matter: str,
    control_matter: str,
) -> None:
    """The shared invariant: member sees the control matter across all
    five streams + a next-action, and NONE of the hidden matter."""
    body = _today(client, member_token)
    ids = _matter_ids_in_today(body)
    assert hidden_matter not in ids, (
        f"hidden matter {hidden_matter} leaked into Today streams: {ids}"
    )
    assert control_matter in ids, (
        "control matter should still be visible across the streams"
    )
    # Every individual stream must exclude the hidden matter.
    for stream in (
        "hearings_next_7d",
        "tasks_due_or_overdue",
        "drafts_in_review",
        "overdue_invoices",
        "deadlines_next_7d",
    ):
        assert all(
            r["matter"]["id"] != hidden_matter for r in body[stream]
        ), f"{stream} leaked the hidden matter"

    # next-action: hidden → null; control → a real action.
    assert _next_action(client, member_token, hidden_matter) is None
    assert _next_action(client, member_token, control_matter) is not None


def test_restricted_matter_without_grant_is_hidden_from_today_and_next_action(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    control = _create_matter(client, owner_token, "ACC-OPEN")
    hidden = _create_matter(client, owner_token, "ACC-RESTRICT")
    _seed_all_streams(client, owner_token, control)
    _seed_all_streams(client, owner_token, hidden)

    member_mid, member_token = _invite_member(
        client, owner_token, "restrict@asterlegal.in"
    )

    toggle = client.post(
        f"/api/matters/{hidden}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert toggle.status_code == 200, toggle.text

    _assert_member_blocked(
        client,
        member_token=member_token,
        hidden_matter=hidden,
        control_matter=control,
    )

    # Owner bypasses the ACL — proves the predicate is the matter-access
    # gate, not a blanket filter that would also blind the owner.
    owner_ids = _matter_ids_in_today(_today(client, owner_token))
    assert hidden in owner_ids and control in owner_ids

    # Granting the member restores visibility everywhere.
    grant = client.post(
        f"/api/matters/{hidden}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_mid, "reason": "Pulled onto the brief."},
    )
    assert grant.status_code == 200, grant.text
    granted_ids = _matter_ids_in_today(_today(client, member_token))
    assert hidden in granted_ids
    assert _next_action(client, member_token, hidden) is not None


def test_ethical_walled_matter_is_hidden_even_with_grant(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    control = _create_matter(client, owner_token, "WALL-OPEN")
    hidden = _create_matter(client, owner_token, "WALL-CONFLICT")
    _seed_all_streams(client, owner_token, control)
    _seed_all_streams(client, owner_token, hidden)

    member_mid, member_token = _invite_member(
        client, owner_token, "wall@asterlegal.in"
    )

    # Restrict + grant, then wall. Wall must override the grant in the
    # Today feed exactly as it does in the matters list.
    client.post(
        f"/api/matters/{hidden}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    client.post(
        f"/api/matters/{hidden}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_mid},
    )
    wall = client.post(
        f"/api/matters/{hidden}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": member_mid, "reason": "Conflict."},
    )
    assert wall.status_code == 200, wall.text

    _assert_member_blocked(
        client,
        member_token=member_token,
        hidden_matter=hidden,
        control_matter=control,
    )


def test_team_scoped_matter_is_hidden_from_non_team_member(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])

    # Control matter has no team (firm-wide → stays visible under
    # scoping); hidden matter is on a team the member is not in.
    control = _create_matter(client, owner_token, "TEAM-FIRMWIDE")
    hidden = _create_matter(client, owner_token, "TEAM-LIT")
    _seed_all_streams(client, owner_token, control)
    _seed_all_streams(client, owner_token, hidden)

    _, member_token = _invite_member(client, owner_token, "team@asterlegal.in")

    lit_team = client.post(
        "/api/teams/",
        headers=auth_headers(owner_token),
        json={"name": "Litigation", "slug": "lit"},
    )
    assert lit_team.status_code in (200, 201), lit_team.text
    team_id = lit_team.json()["id"]

    assign = client.patch(
        f"/api/matters/{hidden}",
        headers=auth_headers(owner_token),
        json={"team_id": team_id},
    )
    assert assign.status_code == 200, assign.text

    scope = client.put(
        "/api/teams/scoping",
        headers=auth_headers(owner_token),
        json={"enabled": True},
    )
    assert scope.status_code == 200, scope.text

    _assert_member_blocked(
        client,
        member_token=member_token,
        hidden_matter=hidden,
        control_matter=control,
    )
