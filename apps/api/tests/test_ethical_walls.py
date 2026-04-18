from __future__ import annotations

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
            "status": "active",
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
