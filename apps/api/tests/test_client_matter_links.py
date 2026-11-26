"""Client <-> Matter links (MOD-TS-009, J12 step 2, US-034, FT-045).

nova-legal 2026-11-25: "No option available to link a client with a
specific matter." These tests pin the server contract the link UI relies
on:

- a client profile and the client list only show (and count) Matters the
  reader can open; ethical walls and restricted Matters stay hidden;
- link and unlink are tenant scoped for both the Matter and the client;
- archived clients cannot be linked, by the link route or by Matter create;
- every link, role/primary change, primary demotion and unlink is audited;
- a Matter has at most one primary client, and the primary client's name
  is copied into ``Matter.client_name`` (unlinking keeps the last name);
- Matter create with ``client_id`` accepts and rejects exactly what the
  link route accepts and rejects.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    Client,
    Matter,
    MatterClientAssignment,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _matter_body(code: str, **extra: object) -> dict:
    return {
        "title": f"Client link regression {code}",
        "matter_code": code,
        "practice_area": "civil",
        "forum_level": "high_court",
        "status": "active",
    } | extra


def _mk_matter(client: TestClient, token: str, code: str, **extra: object) -> dict:
    resp = client.post(
        "/api/matters/", headers=auth_headers(token), json=_matter_body(code, **extra),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mk_client(client: TestClient, token: str, name: str, **extra: object) -> dict:
    resp = client.post(
        "/api/clients/",
        headers=auth_headers(token),
        json={"name": name, "client_type": "corporate"} | extra,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _link(client: TestClient, token: str, matter_id: str, client_id: str, **extra: object):
    return client.post(
        f"/api/matters/{matter_id}/clients",
        headers=auth_headers(token),
        json={"client_id": client_id} | extra,
    )


def _unlink(client: TestClient, token: str, matter_id: str, client_id: str):
    return client.delete(
        f"/api/matters/{matter_id}/clients/{client_id}", headers=auth_headers(token),
    )


def _member(client: TestClient, owner_token: str, role: str = "member") -> tuple[str, str]:
    email = f"{role}-links@asterlegal.in"
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": f"Links {role.title()}",
            "email": email,
            "password": "LinksMember123!",
            "role": role,
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "LinksMember123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return str(created.json()["membership_id"]), str(login.json()["access_token"])


def _other_tenant(client: TestClient) -> str:
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Birch Advocates LLP",
            "company_slug": "birch-advocates",
            "company_type": "law_firm",
            "owner_full_name": "Birch Owner",
            "owner_email": "owner@birch.example",
            "owner_password": "BirchOwner123!",
        },
    )
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return str(resp.json()["access_token"])


def _audit(matter_id: str) -> list[tuple[str, dict]]:
    with get_session_factory()() as session:
        rows = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.matter_id == matter_id,
                AuditEvent.action.like("matter.client%"),
            )
            .order_by(AuditEvent.created_at, AuditEvent.id)
        ).all()
        return [(row.action, json.loads(row.metadata_json or "{}")) for row in rows]


def _assignments(matter_id: str) -> dict[str, MatterClientAssignment]:
    with get_session_factory()() as session:
        rows = session.scalars(
            select(MatterClientAssignment).where(
                MatterClientAssignment.matter_id == matter_id
            )
        ).all()
        session.expunge_all()
        return {row.client_id: row for row in rows}


def _matter_client_name(matter_id: str) -> str | None:
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        return matter.client_name


# ---------------------------------------------------------------
# Visibility: the client profile must not leak walled Matters
# ---------------------------------------------------------------


def test_client_profile_and_list_hide_walled_and_restricted_matters(
    client: TestClient,
) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    member_id, member = _member(client, owner)
    open_matter = _mk_matter(client, owner, "LNK-OPEN")
    walled = _mk_matter(client, owner, "LNK-WALLED", title="Walled acquisition")
    restricted = _mk_matter(client, owner, "LNK-RESTRICTED", title="Restricted dispute")
    shared = _mk_client(client, owner, "Shared Holdings Ltd")
    for matter in (open_matter, walled, restricted):
        assert _link(client, owner, matter["id"], shared["id"]).status_code == 200

    wall = client.post(
        f"/api/matters/{walled['id']}/access/walls",
        headers=auth_headers(owner),
        json={"excluded_membership_id": member_id, "reason": "Acts for the other side"},
    )
    assert wall.status_code == 200, wall.text
    restrict = client.post(
        f"/api/matters/{restricted['id']}/access/restricted",
        headers=auth_headers(owner),
        json={"restricted": True},
    )
    assert restrict.status_code == 200, restrict.text

    profile = client.get(f"/api/clients/{shared['id']}", headers=auth_headers(member))
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert [m["matter_id"] for m in body["matters"]] == [open_matter["id"]]
    assert body["total_matters_count"] == 1
    assert body["active_matters_count"] == 1
    assert "LNK-WALLED" not in profile.text
    assert "Walled acquisition" not in profile.text
    assert "LNK-RESTRICTED" not in profile.text

    listing = client.get("/api/clients/", headers=auth_headers(member))
    assert listing.status_code == 200, listing.text
    row = next(c for c in listing.json()["clients"] if c["id"] == shared["id"])
    assert [m["matter_id"] for m in row["matters"]] == [open_matter["id"]]
    assert row["total_matters_count"] == 1
    assert "LNK-WALLED" not in listing.text
    assert "LNK-RESTRICTED" not in listing.text

    # The owner bypasses walls and restrictions by design and sees all three.
    owner_profile = client.get(
        f"/api/clients/{shared['id']}", headers=auth_headers(owner),
    ).json()
    assert owner_profile["total_matters_count"] == 3


def test_walled_member_cannot_link_or_unlink_on_walled_matter(client: TestClient) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    member_id, member = _member(client, owner)
    walled = _mk_matter(client, owner, "LNK-WALL-WRITE")
    linked = _mk_client(client, owner, "Already Linked Pvt Ltd")
    other = _mk_client(client, owner, "Would Be Linked Pvt Ltd")
    assert _link(client, owner, walled["id"], linked["id"]).status_code == 200
    wall = client.post(
        f"/api/matters/{walled['id']}/access/walls",
        headers=auth_headers(owner),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text

    assert _link(client, member, walled["id"], other["id"]).status_code == 404
    assert _unlink(client, member, walled["id"], linked["id"]).status_code == 404
    assert set(_assignments(walled["id"])) == {linked["id"]}


# ---------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------


def test_link_and_unlink_reject_foreign_matter_and_foreign_client(
    client: TestClient,
) -> None:
    owner_a = str(bootstrap_company(client)["access_token"])
    matter_a = _mk_matter(client, owner_a, "LNK-TENANT-A")
    client_a = _mk_client(client, owner_a, "Tenant A Client")
    assert _link(client, owner_a, matter_a["id"], client_a["id"]).status_code == 200

    owner_b = _other_tenant(client)
    matter_b = _mk_matter(client, owner_b, "LNK-TENANT-B")
    client_b = _mk_client(client, owner_b, "Tenant B Client")

    # Tenant B acting on Tenant A's Matter, with its own client or A's.
    assert _link(client, owner_b, matter_a["id"], client_b["id"]).status_code == 404
    assert _link(client, owner_b, matter_a["id"], client_a["id"]).status_code == 404
    assert _unlink(client, owner_b, matter_a["id"], client_a["id"]).status_code == 404
    # Tenant B linking Tenant A's client to its own Matter.
    foreign_client = _link(client, owner_b, matter_b["id"], client_a["id"])
    assert foreign_client.status_code == 404
    assert "client not found" in foreign_client.text.lower()
    # Tenant A unlinking a client id that belongs to Tenant B resolves the
    # client in A's tenant first.
    foreign_unlink = _unlink(client, owner_a, matter_a["id"], client_b["id"])
    assert foreign_unlink.status_code == 404
    assert "client not found" in foreign_unlink.text.lower()

    assert set(_assignments(matter_a["id"])) == {client_a["id"]}
    assert _assignments(matter_b["id"]) == {}


# ---------------------------------------------------------------
# Validation: archived clients, viewer role, disposed matters
# ---------------------------------------------------------------


def test_archived_client_cannot_be_linked(client: TestClient) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, owner, "LNK-ARCHIVED")
    archived = _mk_client(client, owner, "Archived Client Ltd")
    assert client.delete(
        f"/api/clients/{archived['id']}", headers=auth_headers(owner),
    ).status_code == 200

    resp = _link(client, owner, matter["id"], archived["id"])
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "matter_client_inactive"
    assert "archived" in resp.json()["detail"].lower()
    assert _assignments(matter["id"]) == {}


def test_viewer_cannot_link_or_unlink(client: TestClient) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    _, viewer = _member(client, owner, role="viewer")
    matter = _mk_matter(client, owner, "LNK-VIEWER")
    linked = _mk_client(client, owner, "Viewer Linked Ltd")
    other = _mk_client(client, owner, "Viewer Other Ltd")
    assert _link(client, owner, matter["id"], linked["id"]).status_code == 200

    assert _link(client, viewer, matter["id"], other["id"]).status_code == 403
    assert _unlink(client, viewer, matter["id"], linked["id"]).status_code == 403
    # Viewers can still read the linked clients.
    listing = client.get(
        f"/api/matters/{matter['id']}/client-verification", headers=auth_headers(viewer),
    )
    assert listing.status_code == 200, listing.text
    assert [c["client_id"] for c in listing.json()["clients"]] == [linked["id"]]
    assert set(_assignments(matter["id"])) == {linked["id"]}


def test_disposed_matter_rejects_link_and_unlink(client: TestClient) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, owner, "LNK-DISPOSED")
    linked = _mk_client(client, owner, "Disposed Linked Ltd")
    other = _mk_client(client, owner, "Disposed Other Ltd")
    assert _link(client, owner, matter["id"], linked["id"]).status_code == 200
    with get_session_factory()() as session:
        row = session.get(Matter, matter["id"])
        assert row is not None
        row.status = "disposed"
        row.is_active = False
        session.commit()

    assert _link(client, owner, matter["id"], other["id"]).status_code == 409
    assert _unlink(client, owner, matter["id"], linked["id"]).status_code == 409
    assert set(_assignments(matter["id"])) == {linked["id"]}


# ---------------------------------------------------------------
# Primary client, audit trail, client_name sync
# ---------------------------------------------------------------


def test_primary_is_unique_and_every_change_is_audited(client: TestClient) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, owner, "LNK-PRIMARY")
    first = _mk_client(client, owner, "First Primary Ltd")
    second = _mk_client(client, owner, "Second Party Ltd")
    third = _mk_client(client, owner, "Third Party Ltd")

    # The first link becomes primary; a later link without is_primary does not
    # take the primary role away from it.
    one = _link(client, owner, matter["id"], first["id"], role="petitioner")
    assert one.status_code == 200, one.text
    assert one.json()["is_primary"] is True
    two = _link(client, owner, matter["id"], second["id"], role="co-petitioner")
    assert two.status_code == 200, two.text
    assert two.json()["is_primary"] is False

    # Promoting the third client demotes the first in the same transaction.
    three = _link(client, owner, matter["id"], third["id"], is_primary=True)
    assert three.status_code == 200, three.text
    assert three.json()["is_primary"] is True
    rows = _assignments(matter["id"])
    assert {cid for cid, row in rows.items() if row.is_primary} == {third["id"]}
    assert rows[first["id"]].role == "petitioner"

    # Re-posting an existing pair changes the role and is audited; an omitted
    # is_primary keeps the current primary flag.
    repost = _link(client, owner, matter["id"], second["id"], role="respondent")
    assert repost.status_code == 200, repost.text
    assert repost.json()["id"] == two.json()["id"]
    assert repost.json()["role"] == "respondent"
    assert repost.json()["is_primary"] is False
    # An identical re-post changes nothing and writes no audit row.
    same = _link(client, owner, matter["id"], second["id"], role="respondent")
    assert same.status_code == 200, same.text

    assert _unlink(client, owner, matter["id"], second["id"]).status_code == 204

    events = _audit(matter["id"])
    actions = [action for action, _ in events]
    assert actions == [
        "matter.client_assigned",
        "matter.client_assigned",
        "matter.client_assignment_updated",
        "matter.client_assigned",
        "matter.client_assignment_updated",
        "matter.client_unassigned",
    ]
    demotion = events[2][1]
    assert demotion["client_id"] == first["id"]
    assert demotion["reason"] == "primary_reassigned"
    assert demotion["changes"] == {"is_primary": {"before": True, "after": False}}
    promoted = events[3][1]
    assert promoted["client_id"] == third["id"]
    assert promoted["is_primary"] is True
    assert promoted["demoted_client_ids"] == [first["id"]]
    role_change = events[4][1]
    assert role_change["client_id"] == second["id"]
    assert role_change["changes"] == {
        "role": {"before": "co-petitioner", "after": "respondent"},
    }
    assert events[5][1]["client_id"] == second["id"]
    assert events[5][1]["was_primary"] is False


def test_primary_link_syncs_client_name_and_unlink_keeps_it(client: TestClient) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, owner, "LNK-NAME", client_name="Typed Free Text Name")
    secondary = _mk_client(client, owner, "Secondary Only Ltd")
    primary = _mk_client(client, owner, "Registered Client Pvt Ltd")

    # A secondary link does not touch the Matter's client name.
    resp = _link(client, owner, matter["id"], secondary["id"], is_primary=False)
    assert resp.status_code == 200, resp.text
    assert resp.json()["matter_client_name"] == "Typed Free Text Name"
    assert _matter_client_name(matter["id"]) == "Typed Free Text Name"

    resp = _link(client, owner, matter["id"], primary["id"], is_primary=True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["matter_client_name"] == "Registered Client Pvt Ltd"
    assert _matter_client_name(matter["id"]) == "Registered Client Pvt Ltd"
    workspace = client.get(
        f"/api/matters/{matter['id']}/workspace", headers=auth_headers(owner),
    )
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["matter"]["client_name"] == "Registered Client Pvt Ltd"
    # Matter search reads client_name, so the linked client finds the Matter.
    search = client.get(
        "/api/matters/", params={"q": "Registered Client"}, headers=auth_headers(owner),
    )
    assert search.status_code == 200, search.text
    assert [m["id"] for m in search.json()["matters"]] == [matter["id"]]

    assert _unlink(client, owner, matter["id"], primary["id"]).status_code == 204
    assert _matter_client_name(matter["id"]) == "Registered Client Pvt Ltd"

    events = _audit(matter["id"])
    assert [action for action, _ in events] == [
        "matter.client_assigned",
        "matter.client_assigned",
        "matter.client_unassigned",
    ]
    assert events[0][1]["primary_name_synced"] is False
    assert events[1][1]["primary_name_synced"] is True
    assert events[2][1]["was_primary"] is True
    assert events[2][1]["primary_name_retained"] is True
    # Audit rows record that the name changed, never the name (DATA-GOV-11).
    assert all(
        "Registered Client" not in json.dumps(meta) and "Typed Free" not in json.dumps(meta)
        for _, meta in events
    )


def test_client_verification_listing_reports_archived_link(client: TestClient) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, owner, "LNK-LIST")
    linked = _mk_client(client, owner, "Listed Then Archived Ltd")
    assert _link(client, owner, matter["id"], linked["id"]).status_code == 200
    assert client.delete(
        f"/api/clients/{linked['id']}", headers=auth_headers(owner),
    ).status_code == 200

    listing = client.get(
        f"/api/matters/{matter['id']}/client-verification", headers=auth_headers(owner),
    )
    assert listing.status_code == 200, listing.text
    record = listing.json()["clients"][0]
    assert record["client_id"] == linked["id"]
    assert record["client_is_active"] is False
    # An archived client can still be unlinked; it just cannot be linked again.
    assert _unlink(client, owner, matter["id"], linked["id"]).status_code == 204
    assert _link(client, owner, matter["id"], linked["id"]).status_code == 409


def test_client_verification_listing_carries_contact_details_inside_access_scope(
    client: TestClient,
) -> None:
    """The Matter's Clients card shows the linked client's contact details.

    They come from the same tenant- and wall-scoped read as the KYC status, so a
    walled member and another tenant see nothing.
    """
    owner = str(bootstrap_company(client)["access_token"])
    member_id, member = _member(client, owner)
    matter = _mk_matter(client, owner, "LNK-CONTACT")
    detailed = _mk_client(
        client,
        owner,
        "Contactable Holdings Ltd",
        primary_contact_name="Meera Shah",
        primary_contact_email="meera@contactable.example",
        primary_contact_phone="+91 98200 00001",
        city="Pune",
    )
    bare = _mk_client(client, owner, "Bare Record LLP")
    assert _link(client, owner, matter["id"], detailed["id"], is_primary=True).status_code == 200
    assert _link(client, owner, matter["id"], bare["id"], is_primary=False).status_code == 200

    listing = client.get(
        f"/api/matters/{matter['id']}/client-verification", headers=auth_headers(owner),
    )
    assert listing.status_code == 200, listing.text
    records = {row["client_id"]: row for row in listing.json()["clients"]}
    contact_keys = (
        "primary_contact_name", "primary_contact_email", "primary_contact_phone", "city",
    )
    assert {key: records[detailed["id"]][key] for key in contact_keys} == {
        "primary_contact_name": "Meera Shah",
        "primary_contact_email": "meera@contactable.example",
        "primary_contact_phone": "+91 98200 00001",
        "city": "Pune",
    }
    assert {key: records[bare["id"]][key] for key in contact_keys} == dict.fromkeys(contact_keys)

    wall = client.post(
        f"/api/matters/{matter['id']}/access/walls",
        headers=auth_headers(owner),
        json={"excluded_membership_id": member_id, "reason": "Acts for the other side"},
    )
    assert wall.status_code == 200, wall.text
    walled = client.get(
        f"/api/matters/{matter['id']}/client-verification", headers=auth_headers(member),
    )
    assert walled.status_code == 404
    assert "meera@contactable.example" not in walled.text
    foreign = client.get(
        f"/api/matters/{matter['id']}/client-verification",
        headers=auth_headers(_other_tenant(client)),
    )
    assert foreign.status_code == 404
    assert "meera@contactable.example" not in foreign.text


# ---------------------------------------------------------------
# Two-path parity: Matter create with client_id vs the link route
# ---------------------------------------------------------------


def test_create_matter_with_client_links_primary_and_syncs_name(client: TestClient) -> None:
    owner = str(bootstrap_company(client)["access_token"])
    registered = _mk_client(client, owner, "Created With Matter Ltd")

    created = client.post(
        "/api/matters/",
        headers=auth_headers(owner),
        json=_matter_body(
            "LNK-CREATE", client_id=registered["id"], client_name="Ignored Typed Name",
        ),
    )
    assert created.status_code == 200, created.text
    matter = created.json()
    assert matter["client_name"] == "Created With Matter Ltd"
    rows = _assignments(matter["id"])
    assert set(rows) == {registered["id"]}
    assert rows[registered["id"]].is_primary is True
    assert [action for action, _ in _audit(matter["id"])] == ["matter.client_assigned"]
    profile = client.get(
        f"/api/clients/{registered['id']}", headers=auth_headers(owner),
    ).json()
    assert [m["matter_id"] for m in profile["matters"]] == [matter["id"]]


def test_create_matter_and_link_route_reject_the_same_clients(client: TestClient) -> None:
    owner_a = str(bootstrap_company(client)["access_token"])
    target = _mk_matter(client, owner_a, "LNK-PARITY-TARGET")
    archived = _mk_client(client, owner_a, "Parity Archived Ltd")
    assert client.delete(
        f"/api/clients/{archived['id']}", headers=auth_headers(owner_a),
    ).status_code == 200
    owner_b = _other_tenant(client)
    foreign = _mk_client(client, owner_b, "Parity Foreign Ltd")

    cases = [
        (archived["id"], 409),
        (foreign["id"], 404),
        ("00000000-0000-0000-0000-000000000000", 404),
    ]
    for index, (client_id, expected) in enumerate(cases):
        via_link = _link(client, owner_a, target["id"], client_id)
        via_create = client.post(
            "/api/matters/",
            headers=auth_headers(owner_a),
            json=_matter_body(f"LNK-PARITY-{index}", client_id=client_id),
        )
        assert (via_link.status_code, via_create.status_code) == (expected, expected), (
            client_id, via_link.text, via_create.text,
        )
        assert via_link.json().get("code") == via_create.json().get("code")

    with get_session_factory()() as session:
        codes = set(
            session.scalars(
                select(Matter.matter_code).where(Matter.matter_code.like("LNK-PARITY-%"))
            )
        )
        assert codes == {"LNK-PARITY-TARGET"}
        assert session.scalars(select(MatterClientAssignment)).all() == []
        # The archived client row is untouched by either refusal.
        assert session.get(Client, archived["id"]).is_active is False


def test_create_with_client_id_gives_case_tracking_the_same_party_names(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matter create with ``client_id`` names the client before auto-linking.

    The case-tracking auto-link runs inside create and reads
    ``Matter.client_name`` for its party names; a linked client must reach it
    exactly as the same typed name does.
    """
    from caseops_api.services import case_tracking

    owner = str(bootstrap_company(client)["access_token"])
    registered = _mk_client(client, owner, "Party Parity Holdings Ltd")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", "https://provider.example")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "server-side-token")
    get_settings.cache_clear()
    seen: dict[str, list[str]] = {}
    original = case_tracking._create_or_get_bookmark

    def recording(session, *, context, payload, matter):
        seen[matter.matter_code] = list(payload.party_names)
        return original(session, context=context, payload=payload, matter=matter)

    monkeypatch.setattr(case_tracking, "_create_or_get_bookmark", recording)
    identity = {
        "court_name": "Delhi High Court",
        "opposing_party": "Example Respondent",
    }
    try:
        typed = _mk_matter(
            client, owner, "LNK-PARTY-TYPED",
            client_name="Party Parity Holdings Ltd",
            case_number="WP(C) 11/2026",
            cnr_number="DLHC010011112026",
            **identity,
        )
        linked = _mk_matter(
            client, owner, "LNK-PARTY-LINKED",
            client_id=registered["id"],
            case_number="WP(C) 12/2026",
            cnr_number="DLHC010012122026",
            **identity,
        )
    finally:
        get_settings.cache_clear()

    assert seen["LNK-PARTY-TYPED"] == ["Party Parity Holdings Ltd", "Example Respondent"]
    assert seen["LNK-PARTY-LINKED"] == seen["LNK-PARTY-TYPED"]
    assert typed["client_name"] == linked["client_name"] == "Party Parity Holdings Ltd"
    assert _assignments(linked["id"])[registered["id"]].is_primary is True
