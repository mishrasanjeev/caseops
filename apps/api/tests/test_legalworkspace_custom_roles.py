from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, CompanyMembership, CustomRole
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers


def _bootstrap(
    client: TestClient,
    *,
    slug: str = "lw-s7-firm",
    email: str = "owner@lws7.example",
) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Owner S7",
            "owner_email": email,
            "owner_password": "OwnerPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_user(
    client: TestClient,
    token: str,
    *,
    email: str,
    role: str,
    full_name: str = "Role Target",
) -> dict[str, object]:
    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(token),
        json={
            "full_name": full_name,
            "email": email,
            "password": "MemberPass123!",
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login(client: TestClient, *, email: str, slug: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "MemberPass123!",
            "company_slug": slug,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _create_role(
    client: TestClient,
    token: str,
    *,
    name: str = "Matter creator",
    permissions: list[str] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/companies/current/roles",
        headers=auth_headers(token),
        json={
            "name": name,
            "description": "Created by LW-S7 tests",
            "base_role": "viewer",
            "permissions": permissions or ["matters:create"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_matter(client: TestClient, token: str, code: str) -> int:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Custom role matter {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    return response.status_code


def test_custom_role_assignment_changes_server_resolved_capabilities_and_route_guard(
    client: TestClient,
) -> None:
    boot = _bootstrap(client)
    owner_token = str(boot["access_token"])
    catalog = client.get(
        "/api/companies/current/capabilities",
        headers=auth_headers(owner_token),
    )
    assert catalog.status_code == 200, catalog.text
    assert any(
        row["capability"] == "matters:create"
        for row in catalog.json()["capabilities"]
    )
    viewer = _create_user(
        client,
        owner_token,
        email="viewer@lws7.example",
        role="viewer",
        full_name="Viewer S7",
    )
    viewer_token = _login(client, email="viewer@lws7.example", slug="lw-s7-firm")
    assert _create_matter(client, viewer_token, "S7-BEFORE") == 403

    role = _create_role(client, owner_token, permissions=["matters:create"])
    assign = client.post(
        f"/api/companies/current/employees/{viewer['membership_id']}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": role["id"]},
    )
    assert assign.status_code == 200, assign.text
    assert assign.json()["custom_role_id"] == role["id"]

    stale = client.get("/api/auth/me", headers=auth_headers(viewer_token))
    assert stale.status_code == 401
    fresh_token = _login(client, email="viewer@lws7.example", slug="lw-s7-firm")
    me = client.get("/api/auth/me", headers=auth_headers(fresh_token))
    assert me.status_code == 200, me.text
    assert me.json()["capabilities"] == ["matters:create"]
    assert _create_matter(client, fresh_token, "S7-AFTER") == 200


def test_same_second_custom_role_assignment_revokes_stale_token(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = _bootstrap(client, slug="lw-s7-same-second", email="owner@same-second.example")
    owner_token = str(boot["access_token"])
    viewer = _create_user(
        client,
        owner_token,
        email="viewer@same-second.example",
        role="viewer",
        full_name="Viewer Same Second",
    )

    frozen_issued_at = datetime(2026, 5, 6, 12, 0, 0, 100_000, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen_issued_at if tz is not None else frozen_issued_at.replace(tzinfo=None)

    monkeypatch.setattr("caseops_api.core.security.datetime", FrozenDateTime)
    stale_token = _login(
        client,
        email="viewer@same-second.example",
        slug="lw-s7-same-second",
    )
    monkeypatch.undo()

    factory = get_session_factory()
    with factory() as session:
        membership = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.id == viewer["membership_id"]
            )
        )
        assert membership is not None
        membership.sessions_valid_after = frozen_issued_at + timedelta(milliseconds=400)
        session.commit()

    stale = client.get("/api/auth/me", headers=auth_headers(stale_token))
    assert stale.status_code == 401


def test_fixed_role_behavior_and_owner_role_are_preserved_without_custom_role(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="lw-s7-fixed", email="owner@fixed.example")
    owner_token = str(boot["access_token"])
    owner_me = client.get("/api/auth/me", headers=auth_headers(owner_token))
    assert owner_me.status_code == 200
    assert "audit:export" in owner_me.json()["capabilities"]

    member = _create_user(
        client,
        owner_token,
        email="member@fixed.example",
        role="member",
    )
    member_token = _login(client, email="member@fixed.example", slug="lw-s7-fixed")
    member_me = client.get("/api/auth/me", headers=auth_headers(member_token))
    assert "matters:create" in member_me.json()["capabilities"]

    role = _create_role(client, owner_token, permissions=["clients:view"])
    factory = get_session_factory()
    with factory() as session:
        owner = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.id == boot["membership"]["id"]
            )
        )
        target = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.id == member["membership_id"]
            )
        )
        assert owner is not None and target is not None
        owner.custom_role_id = str(role["id"])
        session.commit()

    owner_after = client.get("/api/auth/me", headers=auth_headers(owner_token))
    assert owner_after.status_code == 200
    assert "audit:export" in owner_after.json()["capabilities"]


def test_custom_role_creation_rejects_owner_only_and_unknown_capabilities(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="lw-s7-deny", email="owner@deny.example")
    owner_token = str(boot["access_token"])
    admin = _create_user(
        client,
        owner_token,
        email="admin@deny.example",
        role="admin",
        full_name="Admin S7",
    )
    admin_token = _login(client, email="admin@deny.example", slug="lw-s7-deny")

    owner_only = client.post(
        "/api/companies/current/roles",
        headers=auth_headers(admin_token),
        json={"name": "Audit exporter", "permissions": ["audit:export"]},
    )
    assert owner_only.status_code == 403

    unknown = client.post(
        "/api/companies/current/roles",
        headers=auth_headers(owner_token),
        json={"name": "Unknown", "permissions": ["not:a-capability"]},
    )
    assert unknown.status_code == 400

    non_delegable_admin = client.post(
        "/api/companies/current/roles",
        headers=auth_headers(owner_token),
        json={"name": "Workspace admin", "permissions": ["workspace:admin"]},
    )
    assert non_delegable_admin.status_code == 403

    assign_owner = client.post(
        f"/api/companies/current/employees/{boot['membership']['id']}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": None},
    )
    assert assign_owner.status_code == 403
    assert admin["role"] == "admin"


def test_capability_catalog_exposes_non_delegable_flag_and_reason(
    client: TestClient,
) -> None:
    """BUG-034 (Hari 2026-05-09): the capability catalog must surface a
    machine-readable flag for capabilities that the backend will reject in
    `validate_custom_role_permissions`. Without it the admin/roles UI cannot
    pre-emptively disable selection and users hit a 403 after submit on
    capabilities like ``email_templates:manage`` / ``portal:invite`` /
    ``portal:manage_grants``.
    """

    boot = _bootstrap(
        client, slug="lw-s7-catalog", email="owner@catalog.example"
    )
    owner_token = str(boot["access_token"])

    response = client.get(
        "/api/companies/current/capabilities",
        headers=auth_headers(owner_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    capabilities = body["capabilities"]
    assert capabilities, "catalog must expose at least one capability"

    by_name = {row["capability"]: row for row in capabilities}
    for required in (
        "capability",
        "group",
        "label",
        "owner_only",
        "custom_role_delegable",
        "protected_reason",
    ):
        assert required in capabilities[0], required

    # Owner-only capabilities are not delegable; they carry a reason.
    audit_export = by_name["audit:export"]
    assert audit_export["owner_only"] is True
    assert audit_export["custom_role_delegable"] is False
    assert audit_export["protected_reason"]
    assert "owner" in audit_export["protected_reason"].lower()

    # The three exact non-delegable capabilities from Hari's report must be
    # surfaced as protected (not owner-only) and not delegable.
    for protected_capability in (
        "email_templates:manage",
        "portal:invite",
        "portal:manage_grants",
    ):
        row = by_name.get(protected_capability)
        assert row is not None, f"missing capability in catalog: {protected_capability}"
        assert row["owner_only"] is False, (
            f"{protected_capability} should be protected, not owner-only"
        )
        assert row["custom_role_delegable"] is False, (
            f"{protected_capability} must be flagged non-delegable"
        )
        assert row["protected_reason"], (
            f"{protected_capability} must explain why it is protected"
        )

    # A representative delegable capability stays delegable.
    matters_create = by_name["matters:create"]
    assert matters_create["custom_role_delegable"] is True
    assert matters_create["protected_reason"] is None


def test_capability_catalog_protected_capabilities_match_validation(
    client: TestClient,
) -> None:
    """BUG-034 round-trip: every capability flagged ``custom_role_delegable=False``
    in the catalog must in fact be rejected by ``POST /api/companies/current/roles``.
    Catalog drift between the flag and the validator is the failure mode this
    bug exposed; the test pins them together.
    """

    boot = _bootstrap(
        client, slug="lw-s7-roundtrip", email="owner@roundtrip.example"
    )
    owner_token = str(boot["access_token"])

    catalog = client.get(
        "/api/companies/current/capabilities",
        headers=auth_headers(owner_token),
    ).json()["capabilities"]

    protected = [
        row["capability"]
        for row in catalog
        if row["custom_role_delegable"] is False and row["owner_only"] is False
    ]
    assert protected, (
        "expected the catalog to flag at least one non-delegable, non-owner-only "
        "capability (e.g. email_templates:manage)"
    )

    for capability in protected:
        response = client.post(
            "/api/companies/current/roles",
            headers=auth_headers(owner_token),
            json={
                "name": f"Drift check {capability}",
                "permissions": [capability],
            },
        )
        assert response.status_code == 403, (
            f"catalog flagged {capability} non-delegable but validator did not "
            f"reject: status={response.status_code} body={response.text}"
        )


def test_malformed_inactive_or_revoked_custom_role_fails_closed(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="lw-s7-failclosed", email="owner@closed.example")
    owner_token = str(boot["access_token"])
    member = _create_user(
        client,
        owner_token,
        email="member@closed.example",
        role="member",
    )
    role = _create_role(client, owner_token, name="Broken role", permissions=["matters:create"])
    factory = get_session_factory()
    with factory() as session:
        custom_role = session.scalar(select(CustomRole).where(CustomRole.id == role["id"]))
        membership = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.id == member["membership_id"]
            )
        )
        assert custom_role is not None and membership is not None
        custom_role.permissions_json = ["matters:create", "unknown:capability"]
        membership.custom_role_id = custom_role.id
        session.commit()

    member_token = _login(client, email="member@closed.example", slug="lw-s7-failclosed")
    me = client.get("/api/auth/me", headers=auth_headers(member_token))
    assert me.status_code == 200
    assert me.json()["capabilities"] == []
    assert _create_matter(client, member_token, "S7-CLOSED") == 403

    with factory() as session:
        custom_role = session.scalar(select(CustomRole).where(CustomRole.id == role["id"]))
        assert custom_role is not None
        custom_role.permissions_json = ["matters:create"]
        custom_role.is_active = False
        session.commit()
    inactive_token = _login(client, email="member@closed.example", slug="lw-s7-failclosed")
    assert client.get("/api/auth/me", headers=auth_headers(inactive_token)).json()[
        "capabilities"
    ] == []


def test_revoked_custom_role_keeps_assigned_member_fail_closed(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="lw-s7-revoke", email="owner@revoke.example")
    owner_token = str(boot["access_token"])
    member = _create_user(
        client,
        owner_token,
        email="member@revoke.example",
        role="member",
        full_name="Member Revoked",
    )
    role = _create_role(
        client,
        owner_token,
        name="Read-only client catalog",
        permissions=["clients:view"],
    )
    assign = client.post(
        f"/api/companies/current/employees/{member['membership_id']}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": role["id"]},
    )
    assert assign.status_code == 200, assign.text

    revoke = client.delete(
        f"/api/companies/current/roles/{role['id']}",
        headers=auth_headers(owner_token),
    )
    assert revoke.status_code == 200, revoke.text

    member_token = _login(client, email="member@revoke.example", slug="lw-s7-revoke")
    me = client.get("/api/auth/me", headers=auth_headers(member_token))
    assert me.status_code == 200, me.text
    assert me.json()["capabilities"] == []
    assert _create_matter(client, member_token, "S7-REVOKED") == 403


def test_missing_custom_role_reference_keeps_member_fail_closed(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="lw-s7-missing", email="owner@missing.example")
    owner_token = str(boot["access_token"])
    member = _create_user(
        client,
        owner_token,
        email="member@missing.example",
        role="member",
        full_name="Member Missing",
    )
    factory = get_session_factory()
    with factory() as session:
        membership = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.id == member["membership_id"]
            )
        )
        assert membership is not None
        membership.custom_role_id = "missing-custom-role"
        session.commit()

    member_token = _login(client, email="member@missing.example", slug="lw-s7-missing")
    assert client.get("/api/auth/me", headers=auth_headers(member_token)).json()[
        "capabilities"
    ] == []
    assert _create_matter(client, member_token, "S7-MISSING") == 403


def test_custom_manage_users_holder_cannot_assign_elevated_employee_roles(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="lw-s7-manage-users", email="owner@manage-users.example")
    owner_token = str(boot["access_token"])
    member = _create_user(
        client,
        owner_token,
        email="member@manage-users.example",
        role="member",
        full_name="Member User Manager",
    )
    target = _create_user(
        client,
        owner_token,
        email="target@manage-users.example",
        role="member",
        full_name="Role Target",
    )
    role = _create_role(
        client,
        owner_token,
        name="Employee directory manager",
        permissions=["company:manage_users"],
    )
    assign = client.post(
        f"/api/companies/current/employees/{member['membership_id']}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": role["id"]},
    )
    assert assign.status_code == 200, assign.text

    manager_token = _login(
        client,
        email="member@manage-users.example",
        slug="lw-s7-manage-users",
    )
    create_admin = client.post(
        "/api/companies/current/employees",
        headers=auth_headers(manager_token),
        json={
            "full_name": "Escalated Admin",
            "email": "escalated@manage-users.example",
            "role": "admin",
        },
    )
    assert create_admin.status_code == 403

    update_partner = client.patch(
        f"/api/companies/current/employees/{target['membership_id']}",
        headers=auth_headers(manager_token),
        json={"role": "partner"},
    )
    assert update_partner.status_code == 403

    create_member = client.post(
        "/api/companies/current/employees",
        headers=auth_headers(manager_token),
        json={
            "full_name": "Allowed Member",
            "email": "allowed-member@manage-users.example",
            "role": "member",
        },
    )
    assert create_member.status_code == 200, create_member.text


def test_custom_manage_users_holder_cannot_mint_or_assign_stronger_custom_roles(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s7-role-escalation",
        email="owner@role-escalation.example",
    )
    owner_token = str(boot["access_token"])
    manager = _create_user(
        client,
        owner_token,
        email="manager@role-escalation.example",
        role="member",
        full_name="Custom Role Manager",
    )
    peer = _create_user(
        client,
        owner_token,
        email="peer@role-escalation.example",
        role="member",
        full_name="Peer Target",
    )
    manager_role = _create_role(
        client,
        owner_token,
        name="Custom employee manager",
        permissions=["company:manage_users"],
    )
    assign_manager = client.post(
        f"/api/companies/current/employees/{manager['membership_id']}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": manager_role["id"]},
    )
    assert assign_manager.status_code == 200, assign_manager.text

    manager_token = _login(
        client,
        email="manager@role-escalation.example",
        slug="lw-s7-role-escalation",
    )

    create_workspace_admin = client.post(
        "/api/companies/current/roles",
        headers=auth_headers(manager_token),
        json={
            "name": "Workspace admin by custom manager",
            "permissions": ["workspace:admin"],
        },
    )
    assert create_workspace_admin.status_code == 403

    create_unowned_matter_creator = client.post(
        "/api/companies/current/roles",
        headers=auth_headers(manager_token),
        json={
            "name": "Matter creator by custom manager",
            "permissions": ["matters:create"],
        },
    )
    assert create_unowned_matter_creator.status_code == 403

    owner_created_stronger_role = _create_role(
        client,
        owner_token,
        name="Owner-created matter creator",
        permissions=["matters:create"],
    )
    self_assign = client.post(
        f"/api/companies/current/employees/{manager['membership_id']}/role",
        headers=auth_headers(manager_token),
        json={"custom_role_id": owner_created_stronger_role["id"]},
    )
    assert self_assign.status_code == 403

    peer_assign = client.post(
        f"/api/companies/current/employees/{peer['membership_id']}/role",
        headers=auth_headers(manager_token),
        json={"custom_role_id": owner_created_stronger_role["id"]},
    )
    assert peer_assign.status_code == 403

    manager_me = client.get("/api/auth/me", headers=auth_headers(manager_token))
    assert manager_me.status_code == 200, manager_me.text
    assert manager_me.json()["capabilities"] == ["company:manage_users"]


def test_custom_manage_users_holder_cannot_clear_custom_roles_to_restore_fixed_access(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s7-clear-escalation",
        email="owner@clear-escalation.example",
    )
    owner_token = str(boot["access_token"])
    manager = _create_user(
        client,
        owner_token,
        email="manager@clear-escalation.example",
        role="member",
        full_name="Custom Role Manager",
    )
    peer = _create_user(
        client,
        owner_token,
        email="peer@clear-escalation.example",
        role="member",
        full_name="Restricted Peer",
    )
    manager_role = _create_role(
        client,
        owner_token,
        name="Custom manager clear guard",
        permissions=["company:manage_users"],
    )
    peer_role = _create_role(
        client,
        owner_token,
        name="Peer client reader",
        permissions=["clients:view"],
    )
    for target, role in ((manager, manager_role), (peer, peer_role)):
        assign = client.post(
            f"/api/companies/current/employees/{target['membership_id']}/role",
            headers=auth_headers(owner_token),
            json={"custom_role_id": role["id"]},
        )
        assert assign.status_code == 200, assign.text

    manager_token = _login(
        client,
        email="manager@clear-escalation.example",
        slug="lw-s7-clear-escalation",
    )

    peer_clear = client.post(
        f"/api/companies/current/employees/{peer['membership_id']}/role",
        headers=auth_headers(manager_token),
        json={"custom_role_id": None},
    )
    assert peer_clear.status_code == 403

    self_clear = client.post(
        f"/api/companies/current/employees/{manager['membership_id']}/role",
        headers=auth_headers(manager_token),
        json={"custom_role_id": None},
    )
    assert self_clear.status_code == 403

    manager_me = client.get("/api/auth/me", headers=auth_headers(manager_token))
    assert manager_me.status_code == 200, manager_me.text
    assert manager_me.json()["capabilities"] == ["company:manage_users"]

    peer_token = _login(
        client,
        email="peer@clear-escalation.example",
        slug="lw-s7-clear-escalation",
    )
    peer_me = client.get("/api/auth/me", headers=auth_headers(peer_token))
    assert peer_me.status_code == 200, peer_me.text
    assert peer_me.json()["capabilities"] == ["clients:view"]


def test_owner_can_clear_custom_role_and_revokes_stale_session(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s7-owner-clear",
        email="owner@owner-clear.example",
    )
    owner_token = str(boot["access_token"])
    member = _create_user(
        client,
        owner_token,
        email="member@owner-clear.example",
        role="member",
        full_name="Clearable Member",
    )
    role = _create_role(
        client,
        owner_token,
        name="Client reader before clear",
        permissions=["clients:view"],
    )
    assign = client.post(
        f"/api/companies/current/employees/{member['membership_id']}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": role["id"]},
    )
    assert assign.status_code == 200, assign.text

    member_token = _login(client, email="member@owner-clear.example", slug="lw-s7-owner-clear")
    before = client.get("/api/auth/me", headers=auth_headers(member_token))
    assert before.status_code == 200, before.text
    assert before.json()["capabilities"] == ["clients:view"]

    clear = client.post(
        f"/api/companies/current/employees/{member['membership_id']}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": None},
    )
    assert clear.status_code == 200, clear.text
    assert clear.json()["custom_role_id"] is None

    stale = client.get("/api/auth/me", headers=auth_headers(member_token))
    assert stale.status_code == 401

    fresh_token = _login(client, email="member@owner-clear.example", slug="lw-s7-owner-clear")
    after = client.get("/api/auth/me", headers=auth_headers(fresh_token))
    assert after.status_code == 200, after.text
    assert "matters:create" in after.json()["capabilities"]


def test_custom_roles_are_tenant_scoped_and_audited(client: TestClient) -> None:
    boot_a = _bootstrap(client, slug="lw-s7-a", email="owner@s7-a.example")
    token_a = str(boot_a["access_token"])
    member_a = _create_user(
        client,
        token_a,
        email="member@s7-a.example",
        role="member",
    )
    role_a = _create_role(client, token_a, name="Tenant A creator")

    boot_b = _bootstrap(client, slug="lw-s7-b", email="owner@s7-b.example")
    token_b = str(boot_b["access_token"])
    list_b = client.get("/api/companies/current/roles", headers=auth_headers(token_b))
    assert list_b.status_code == 200
    assert list_b.json()["roles"] == []

    cross_assign = client.post(
        f"/api/companies/current/employees/{member_a['membership_id']}/role",
        headers=auth_headers(token_b),
        json={"custom_role_id": role_a["id"]},
    )
    assert cross_assign.status_code == 404

    update = client.patch(
        f"/api/companies/current/roles/{role_a['id']}",
        headers=auth_headers(token_a),
        json={"description": "Updated safely", "permissions": ["matters:create", "clients:view"]},
    )
    assert update.status_code == 200, update.text
    assign = client.post(
        f"/api/companies/current/employees/{member_a['membership_id']}/role",
        headers=auth_headers(token_a),
        json={"custom_role_id": role_a["id"]},
    )
    assert assign.status_code == 200, assign.text

    factory = get_session_factory()
    with factory() as session:
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == boot_a["company"]["id"])
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            )
        )
    actions = [event.action for event in events]
    assert "custom_role.created" in actions
    assert "custom_role.updated" in actions
    assert "employee.custom_role.assigned" in actions
    updated = next(event for event in events if event.action == "custom_role.updated")
    metadata = json.loads(updated.metadata_json or "{}")
    assert metadata["before"]["permissions"] == ["matters:create"]
    assert metadata["after"]["permissions"] == ["clients:view", "matters:create"]
