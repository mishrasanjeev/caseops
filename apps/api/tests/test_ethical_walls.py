from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str) -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"ACL test — {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _invite_member(
    client: TestClient, owner_token: str, email: str, role: str = "member"
) -> tuple[str, str]:
    """Create a second membership in the same tenant. Returns
    (membership_id, access_token)."""
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
    body = create.json()
    # CompanyUserRecord is flat: membership_id lives at top level.
    membership_id = body["membership_id"]
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


def _audit_rows(action: str, company_id: str) -> list[AuditEvent]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == action,
                )
                .order_by(AuditEvent.created_at.asc())
            )
        )


# ---------------------------------------------------------------------------
# Baseline: unrestricted matter stays visible to every company member.
# ---------------------------------------------------------------------------


def test_unrestricted_matter_is_visible_to_every_member(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    matter_id = _create_matter(client, owner_token, "ACL-OPEN")
    _, member_token = _invite_member(client, owner_token, "open@asterlegal.in")

    # Member sees the matter in the list and can open it.
    list_resp = client.get("/api/matters/", headers=auth_headers(member_token))
    assert list_resp.status_code == 200
    assert any(m["id"] == matter_id for m in list_resp.json()["matters"])

    get_resp = client.get(
        f"/api/matters/{matter_id}", headers=auth_headers(member_token)
    )
    assert get_resp.status_code == 200


# ---------------------------------------------------------------------------
# Restricted matter: non-granted member gets 404, granted member sees it.
# ---------------------------------------------------------------------------


def test_restricted_matter_hides_non_granted_members(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter_id = _create_matter(client, owner_token, "ACL-RESTRICT")
    member_mid, member_token = _invite_member(client, owner_token, "walled@asterlegal.in")

    toggle = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert toggle.status_code == 200
    assert toggle.json()["restricted_access"] is True

    # Member no longer sees the matter on the list or by id.
    list_resp = client.get("/api/matters/", headers=auth_headers(member_token))
    assert list_resp.status_code == 200
    assert all(m["id"] != matter_id for m in list_resp.json()["matters"])

    direct = client.get(
        f"/api/matters/{matter_id}", headers=auth_headers(member_token)
    )
    assert direct.status_code == 404
    # Denied access was audited.
    denied = _audit_rows("access_denied", company_id)
    assert any(e.target_id == matter_id for e in denied)

    # Grant the member and try again.
    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_mid, "reason": "Pulling onto the brief."},
    )
    assert grant.status_code == 200

    granted_list = client.get("/api/matters/", headers=auth_headers(member_token))
    assert any(m["id"] == matter_id for m in granted_list.json()["matters"])
    assert (
        client.get(
            f"/api/matters/{matter_id}", headers=auth_headers(member_token)
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# Ethical wall: blocks even a granted member, even on an unrestricted matter.
# ---------------------------------------------------------------------------


def test_ethical_wall_blocks_member_even_with_grant(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter_id = _create_matter(client, owner_token, "ACL-WALL")
    member_mid, member_token = _invite_member(client, owner_token, "conflict@asterlegal.in")

    # Make it restricted + grant, then add a wall. Wall > grant.
    client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_mid},
    )
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": member_mid, "reason": "Conflict."},
    )
    assert wall.status_code == 200

    blocked = client.get(
        f"/api/matters/{matter_id}", headers=auth_headers(member_token)
    )
    assert blocked.status_code == 404
    denied = _audit_rows("access_denied", company_id)
    assert any(e.target_id == matter_id for e in denied)

    # Removing the wall restores access (grant still present).
    wall_id = wall.json()["id"]
    rm = client.delete(
        f"/api/matters/{matter_id}/access/walls/{wall_id}",
        headers=auth_headers(owner_token),
    )
    assert rm.status_code == 204
    unblocked = client.get(
        f"/api/matters/{matter_id}", headers=auth_headers(member_token)
    )
    assert unblocked.status_code == 200


def test_attachment_download_honours_restriction_grant_and_ethical_wall(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    matter_id = _create_matter(client, owner_token, "ACL-DOWNLOAD")
    member_mid, member_token = _invite_member(
        client, owner_token, "download-wall@asterlegal.in"
    )
    upload = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(owner_token),
        files={"file": ("privileged.txt", b"privileged material", "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    download_url = (
        f"/api/matters/{matter_id}/attachments/{upload.json()['id']}/download"
    )

    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    assert client.get(download_url, headers=auth_headers(member_token)).status_code == 404

    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_mid, "reason": "Document review assignment"},
    )
    assert grant.status_code == 200, grant.text
    allowed = client.get(download_url, headers=auth_headers(member_token))
    assert allowed.status_code == 200
    assert allowed.content == b"privileged material"

    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": member_mid, "reason": "Conflict discovered"},
    )
    assert wall.status_code == 200, wall.text
    assert client.get(download_url, headers=auth_headers(member_token)).status_code == 404


# ---------------------------------------------------------------------------
# Owners bypass walls so they can't be locked out of their own firm.
# ---------------------------------------------------------------------------


def test_owner_bypasses_ethical_wall_on_own_matter(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    owner_mid = boot["membership"]["id"]
    matter_id = _create_matter(client, owner_token, "ACL-OWNER-BYPASS")

    # Someone maliciously walls the owner off. The wall row lands in the
    # DB (we don't validate actor vs wall target) but enforcement must
    # ignore it for owners.
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": owner_mid, "reason": "Self-wall test."},
    )
    assert wall.status_code == 200

    still_sees = client.get(
        f"/api/matters/{matter_id}", headers=auth_headers(owner_token)
    )
    assert still_sees.status_code == 200


# ---------------------------------------------------------------------------
# Authorisation: plain members cannot manage walls/grants.
# ---------------------------------------------------------------------------


def test_member_cannot_manage_grants_or_walls(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    matter_id = _create_matter(client, owner_token, "ACL-MEMBER-DENY")
    member_mid, member_token = _invite_member(client, owner_token, "junior@asterlegal.in")

    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=auth_headers(member_token),
        json={"membership_id": member_mid},
    )
    assert grant.status_code == 403

    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(member_token),
        json={"excluded_membership_id": member_mid},
    )
    assert wall.status_code == 403


# ---------------------------------------------------------------------------
# Cross-tenant: tenant B cannot manage tenant A's matter.
# ---------------------------------------------------------------------------


def test_cross_tenant_access_management_returns_404(client: TestClient) -> None:
    boot_a = bootstrap_company(client)
    token_a = str(boot_a["access_token"])
    matter_a = _create_matter(client, token_a, "ACL-X-A")

    boot_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B",
            "company_slug": "acl-tenant-b",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "owner@aclb.in",
            "owner_password": "TenantBPass123!",
        },
    )
    assert boot_b.status_code == 200
    token_b = str(boot_b.json()["access_token"])
    member_b = boot_b.json()["membership"]["id"]

    # Tenant B cannot toggle restricted_access on tenant A's matter.
    toggle = client.post(
        f"/api/matters/{matter_a}/access/restricted",
        headers=auth_headers(token_b),
        json={"restricted": True},
    )
    assert toggle.status_code == 404

    # Tenant B cannot add a grant referencing tenant A's matter even
    # with a membership id from their own tenant.
    grant = client.post(
        f"/api/matters/{matter_a}/access/grants",
        headers=auth_headers(token_b),
        json={"membership_id": member_b},
    )
    assert grant.status_code == 404


# ---------------------------------------------------------------------------
# Admin wall directory: GET /api/matters/ethical-walls (US-040, FT-008, SEC-004).
# ---------------------------------------------------------------------------


def _directory(client: TestClient, token: str) -> dict:
    resp = client.get("/api/matters/ethical-walls", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_wall_directory_names_walled_member_creator_and_is_audited(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    owner_mid = boot["membership"]["id"]
    company_id = boot["company"]["id"]
    matter_id = _create_matter(client, owner_token, "ACL-DIR")
    member_mid, _ = _invite_member(client, owner_token, "dir-walled@asterlegal.in")

    assert _directory(client, owner_token) == {"walls": [], "truncated": False}

    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": member_mid, "reason": "Acted for the counterparty."},
    )
    assert wall.status_code == 200, wall.text
    wall_id = wall.json()["id"]

    body = _directory(client, owner_token)
    assert body["truncated"] is False
    assert len(body["walls"]) == 1
    row = body["walls"][0]
    assert row["id"] == wall_id
    assert row["matter_id"] == matter_id
    assert row["matter_code"] == "ACL-DIR"
    assert row["matter_title"] == "ACL test — ACL-DIR"
    assert row["excluded_membership_id"] == member_mid
    assert row["excluded_full_name"] == "Member dir-walled"
    assert row["excluded_email"] == "dir-walled@asterlegal.in"
    assert row["excluded_role"] == "member"
    assert row["excluded_membership_active"] is True
    assert row["enforced"] is True
    assert row["reason"] == "Acted for the counterparty."
    assert row["created_by_membership_id"] == owner_mid
    assert row["created_by_full_name"] == "Sanjay Mishra"

    viewed = _audit_rows("matter.ethical_walls_viewed", company_id)
    assert [e.actor_membership_id for e in viewed] == [owner_mid, owner_mid]
    assert json.loads(viewed[-1].metadata_json or "{}") == {
        "wall_count": 1,
        "truncated": False,
    }
    assert any(
        e.target_id == wall_id
        for e in _audit_rows("matter.ethical_wall_added", company_id)
    )

    rm = client.delete(
        f"/api/matters/{matter_id}/access/walls/{wall_id}",
        headers=auth_headers(owner_token),
    )
    assert rm.status_code == 204
    assert _directory(client, owner_token)["walls"] == []
    assert any(
        e.target_id == wall_id
        for e in _audit_rows("matter.ethical_wall_removed", company_id)
    )


def test_wall_directory_marks_owner_walls_as_not_enforced(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    owner_mid = boot["membership"]["id"]
    matter_id = _create_matter(client, owner_token, "ACL-DIR-OWNER")
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": owner_mid},
    )
    assert wall.status_code == 200, wall.text

    [row] = _directory(client, owner_token)["walls"]
    assert row["excluded_role"] == "owner"
    assert row["enforced"] is False
    # Enforcement agrees: the owner still opens the Matter.
    opened = client.get(f"/api/matters/{matter_id}", headers=auth_headers(owner_token))
    assert opened.status_code == 200


def test_wall_directory_requires_session_and_access_manager_role(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    _, member_token = _invite_member(client, owner_token, "dir-member@asterlegal.in")
    _, partner_token = _invite_member(
        client, owner_token, "dir-partner@asterlegal.in", role="partner"
    )

    # Login set a session cookie; drop it so the request is truly anonymous.
    client.cookies.clear()
    anonymous = client.get("/api/matters/ethical-walls")
    assert anonymous.status_code == 401
    for token in (member_token, partner_token):
        denied = client.get("/api/matters/ethical-walls", headers=auth_headers(token))
        assert denied.status_code == 403
    assert _audit_rows("matter.ethical_walls_viewed", company_id) == []


def test_wall_directory_never_lists_another_tenants_walls(client: TestClient) -> None:
    boot_a = bootstrap_company(client)
    token_a = str(boot_a["access_token"])
    matter_a = _create_matter(client, token_a, "ACL-DIR-XA")
    member_a, _ = _invite_member(client, token_a, "dir-xa@asterlegal.in")
    wall = client.post(
        f"/api/matters/{matter_a}/access/walls",
        headers=auth_headers(token_a),
        json={"excluded_membership_id": member_a, "reason": "Tenant A conflict."},
    )
    assert wall.status_code == 200, wall.text

    boot_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B",
            "company_slug": "acl-dir-tenant-b",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "owner@acldirb.in",
            "owner_password": "TenantBPass123!",
        },
    )
    assert boot_b.status_code == 200, boot_b.text
    token_b = str(boot_b.json()["access_token"])

    assert _directory(client, token_b) == {"walls": [], "truncated": False}
    # Tenant B cannot lift tenant A's wall by id either.
    wall_id = wall.json()["id"]
    rm = client.delete(
        f"/api/matters/{matter_a}/access/walls/{wall_id}",
        headers=auth_headers(token_b),
    )
    assert rm.status_code == 404
    # Nor add one, nor read tenant A's access panel.
    member_b = boot_b.json()["membership"]["id"]
    add = client.post(
        f"/api/matters/{matter_a}/access/walls",
        headers=auth_headers(token_b),
        json={"excluded_membership_id": member_b},
    )
    assert add.status_code == 404
    panel = client.get(f"/api/matters/{matter_a}/access", headers=auth_headers(token_b))
    assert panel.status_code == 404
    assert len(_directory(client, token_a)["walls"]) == 1


def test_wall_overrides_admin_and_partner_roles_and_hides_directory_rows(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    walled_matter = _create_matter(client, owner_token, "ACL-DIR-ADMIN")
    open_matter = _create_matter(client, owner_token, "ACL-DIR-OPEN")
    admin_mid, admin_token = _invite_member(
        client, owner_token, "dir-admin@asterlegal.in", role="admin"
    )
    partner_mid, partner_token = _invite_member(
        client, owner_token, "dir-partner2@asterlegal.in", role="partner"
    )
    member_mid, _ = _invite_member(client, owner_token, "dir-other@asterlegal.in")

    def visible_ids(token: str) -> set[str]:
        resp = client.get("/api/matters/", headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        return {m["id"] for m in resp.json()["matters"]}

    # The partner is also the walled matter's assignee: a wall beats that too.
    current = client.get(f"/api/matters/{walled_matter}", headers=auth_headers(owner_token))
    assigned = client.patch(
        f"/api/matters/{walled_matter}",
        headers=auth_headers(owner_token),
        json={
            "assignee_membership_id": partner_mid,
            "expected_updated_at": current.json()["updated_at"],
        },
    )
    assert assigned.status_code == 200, assigned.text

    # Before any wall the admin and partner see both matters.
    for token in (admin_token, partner_token):
        assert {walled_matter, open_matter} <= visible_ids(token)

    for excluded in (admin_mid, partner_mid, member_mid):
        resp = client.post(
            f"/api/matters/{walled_matter}/access/walls",
            headers=auth_headers(owner_token),
            json={"excluded_membership_id": excluded, "reason": "Screened."},
        )
        assert resp.status_code == 200, resp.text
    other = client.post(
        f"/api/matters/{open_matter}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": member_mid},
    )
    assert other.status_code == 200, other.text

    # Broad roles do not get through the wall: list and detail both hide it.
    for token in (admin_token, partner_token):
        ids = visible_ids(token)
        assert walled_matter not in ids
        assert open_matter in ids
        detail = client.get(f"/api/matters/{walled_matter}", headers=auth_headers(token))
        assert detail.status_code == 404

    # The walled admin's directory omits every wall on the walled matter,
    # including walls naming other people, and never shows its code.
    admin_view = _directory(client, admin_token)
    assert [row["matter_id"] for row in admin_view["walls"]] == [open_matter]
    assert "ACL-DIR-ADMIN" not in str(admin_view)

    # The owner bypasses walls and sees all four.
    owner_view = _directory(client, owner_token)
    assert len(owner_view["walls"]) == 4
    assert {row["excluded_membership_id"] for row in owner_view["walls"]} == {
        admin_mid,
        partner_mid,
        member_mid,
    }


# ---------------------------------------------------------------------------
# A wall also overrides the admin role on the access-management API (SEC-004).
# ---------------------------------------------------------------------------


def _panel(client: TestClient, token: str, matter_id: str) -> dict:
    resp = client.get(f"/api/matters/{matter_id}/access", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_walled_admin_cannot_read_or_change_that_matters_walls_or_grants(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter_id = _create_matter(client, owner_token, "ACL-WALLED-ADMIN")
    admin_mid, admin_token = _invite_member(
        client, owner_token, "walled-admin@asterlegal.in", role="admin"
    )
    member_mid, _ = _invite_member(client, owner_token, "acl-colleague@asterlegal.in")

    own_wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": admin_mid, "reason": "Conflict."},
    )
    assert own_wall.status_code == 200, own_wall.text
    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_mid},
    )
    assert grant.status_code == 200, grant.text
    before = _panel(client, owner_token, matter_id)
    denied_before = len(_audit_rows("access_denied", company_id))

    admin = auth_headers(admin_token)
    attempts = [
        client.delete(
            f"/api/matters/{matter_id}/access/walls/{own_wall.json()['id']}", headers=admin
        ),
        client.post(
            f"/api/matters/{matter_id}/access/walls",
            headers=admin,
            json={"excluded_membership_id": member_mid},
        ),
        client.post(
            f"/api/matters/{matter_id}/access/grants",
            headers=admin,
            json={"membership_id": admin_mid, "reason": "Let me back in."},
        ),
        client.post(
            f"/api/matters/{matter_id}/access/grants",
            headers=admin,
            json={"membership_id": member_mid},
        ),
        client.delete(
            f"/api/matters/{matter_id}/access/grants/{grant.json()['id']}", headers=admin
        ),
        client.post(
            f"/api/matters/{matter_id}/access/restricted",
            headers=admin,
            json={"restricted": True},
        ),
        client.get(f"/api/matters/{matter_id}/access", headers=admin),
    ]
    # Same answer as any read of a walled Matter: not found, no existence leak.
    assert [r.status_code for r in attempts] == [404] * len(attempts)
    assert all(r.json()["detail"] == "Matter not found." for r in attempts)

    # Every refusal is audited against the Matter, and nothing changed.
    denied = _audit_rows("access_denied", company_id)[denied_before:]
    assert len(denied) == len(attempts)
    assert {(e.target_id, e.actor_membership_id) for e in denied} == {(matter_id, admin_mid)}
    assert _panel(client, owner_token, matter_id) == before
    still_walled = client.get(f"/api/matters/{matter_id}", headers=admin)
    assert still_walled.status_code == 404


def test_unwalled_admin_and_walled_owner_still_manage_walls_and_grants(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    owner_mid = boot["membership"]["id"]
    matter_id = _create_matter(client, owner_token, "ACL-MANAGERS")
    _, admin_token = _invite_member(
        client, owner_token, "free-admin@asterlegal.in", role="admin"
    )
    member_mid, _ = _invite_member(client, owner_token, "managed@asterlegal.in")

    def manage(token: str) -> None:
        headers = auth_headers(token)
        assert _panel(client, token, matter_id)["matter_id"] == matter_id
        wall = client.post(
            f"/api/matters/{matter_id}/access/walls",
            headers=headers,
            json={"excluded_membership_id": member_mid},
        )
        assert wall.status_code == 200, wall.text
        lifted = client.delete(
            f"/api/matters/{matter_id}/access/walls/{wall.json()['id']}", headers=headers
        )
        assert lifted.status_code == 204, lifted.text
        grant = client.post(
            f"/api/matters/{matter_id}/access/grants",
            headers=headers,
            json={"membership_id": member_mid},
        )
        assert grant.status_code == 200, grant.text
        revoked = client.delete(
            f"/api/matters/{matter_id}/access/grants/{grant.json()['id']}", headers=headers
        )
        assert revoked.status_code == 204, revoked.text

    manage(admin_token)

    # Owners bypass walls, including a wall naming themselves.
    self_wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": owner_mid},
    )
    assert self_wall.status_code == 200, self_wall.text
    manage(owner_token)
    lifted = client.delete(
        f"/api/matters/{matter_id}/access/walls/{self_wall.json()['id']}",
        headers=auth_headers(owner_token),
    )
    assert lifted.status_code == 204, lifted.text
