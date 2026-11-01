"""B4-ADJ-01: portal invitations and grant management obey Matter visibility.

A walled or unauthorised colleague with ``portal:invite`` must not be able to
grant a client or outside counsel portal access to a Matter or IP docket they
cannot see themselves. The invitation answers exactly like a missing record
(404, no existence leak), writes nothing and audits the denial. The IP grant
list and revoke apply the same visibility predicate.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import AuditEvent, MatterPortalGrant, PortalUser
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ethical_walls import _create_matter, _invite_member
from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture


def _invite(
    client: TestClient,
    token_headers: dict[str, str],
    *,
    email: str,
    matter_ids: list[str] | None = None,
    ip_docket_ids: list[str] | None = None,
    role: str = "client",
):
    body: dict = {"email": email, "full_name": "Portal Person", "role": role}
    if matter_ids is not None:
        body["matter_ids"] = matter_ids
    if ip_docket_ids is not None:
        body.update(
            {
                "ip_docket_ids": ip_docket_ids,
                "event_kinds": ["registry_snapshot_accepted"],
                "deadline_kinds": ["opposition_evidence"],
                "document_categories": ["evidence"],
                "can_submit_instructions": True,
            }
        )
    return client.post("/api/admin/portal/invitations", headers=token_headers, json=body)


def _portal_rows(company_id: str) -> tuple[int, int]:
    with get_session_factory()() as session:
        users = session.scalar(
            select(func.count()).select_from(PortalUser).where(PortalUser.company_id == company_id)
        )
        grants = session.scalar(
            select(func.count())
            .select_from(MatterPortalGrant)
            .where(MatterPortalGrant.company_id == company_id)
        )
    return int(users or 0), int(grants or 0)


def _denials(company_id: str, target_id: str) -> list[AuditEvent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "access_denied",
                    AuditEvent.target_id == target_id,
                )
            )
        )


def _wall(client: TestClient, owner_headers: dict[str, str], matter_id: str, membership_id: str):
    response = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=owner_headers,
        json={"excluded_membership_id": membership_id, "reason": "Conflict with the client."},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_walled_admin_cannot_invite_a_portal_user_to_a_walled_matter(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_headers = auth_headers(str(boot["access_token"]))
    company_id = str(boot["company"]["id"])
    walled_matter = _create_matter(client, str(boot["access_token"]), "PORTAL-WALL-1")
    open_matter = _create_matter(client, str(boot["access_token"]), "PORTAL-OPEN-1")
    admin_id, admin_token = _invite_member(
        client, str(boot["access_token"]), "walled-admin@asterlegal.in", role="admin"
    )
    admin_headers = auth_headers(admin_token)
    _wall(client, owner_headers, walled_matter, admin_id)

    for matter_ids in ([walled_matter], [open_matter, walled_matter]):
        refused = _invite(
            client, admin_headers, email="walled-client@example.com", matter_ids=matter_ids
        )
        assert refused.status_code == 404, refused.text
        # Same answer as a Matter that does not exist: no existence leak.
        assert refused.json()["detail"] == "Matter not found."
    assert _portal_rows(company_id) == (0, 0)
    denials = _denials(company_id, walled_matter)
    assert denials and all(row.result == "denied" for row in denials)
    assert all(row.actor_membership_id == admin_id for row in denials)

    # Positive control: the same admin can invite to a Matter they can see,
    # and the owner (never walled) can invite to the walled Matter.
    allowed = _invite(
        client, admin_headers, email="open-client@example.com", matter_ids=[open_matter]
    )
    assert allowed.status_code == 201, allowed.text
    owner_invite = _invite(
        client, owner_headers, email="walled-client@example.com", matter_ids=[walled_matter]
    )
    assert owner_invite.status_code == 201, owner_invite.text
    assert _portal_rows(company_id) == (2, 2)


def test_walled_admin_reinvite_cannot_rescope_an_existing_walled_grant(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_headers = auth_headers(str(boot["access_token"]))
    company_id = str(boot["company"]["id"])
    matter = _create_matter(client, str(boot["access_token"]), "PORTAL-WALL-2")
    owner_invite = _invite(
        client,
        owner_headers,
        email="existing@example.com",
        matter_ids=[matter],
        role="outside_counsel",
    )
    assert owner_invite.status_code == 201, owner_invite.text
    grant_id = owner_invite.json()["grants"][0]["id"]
    admin_id, admin_token = _invite_member(
        client, str(boot["access_token"]), "walled-admin2@asterlegal.in", role="admin"
    )
    _wall(client, owner_headers, matter, admin_id)

    with get_session_factory()() as session:
        before = session.get(MatterPortalGrant, grant_id)
        assert before is not None
        before_state = (before.scope_json, before.row_version, before.granted_by_membership_id)

    refused = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(admin_token),
        json={
            "email": "existing@example.com",
            "full_name": "Existing Counsel",
            "role": "outside_counsel",
            "matter_ids": [matter],
            "can_upload": True,
            "can_invoice": True,
        },
    )
    assert refused.status_code == 404, refused.text
    with get_session_factory()() as session:
        after = session.get(MatterPortalGrant, grant_id)
        assert after is not None
        assert (after.scope_json, after.row_version, after.granted_by_membership_id) == before_state
    assert _portal_rows(company_id) == (1, 1)


def test_restricted_matter_without_a_grant_is_not_invitable_by_an_admin(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_headers = auth_headers(str(boot["access_token"]))
    company_id = str(boot["company"]["id"])
    matter = _create_matter(client, str(boot["access_token"]), "PORTAL-RESTRICTED")
    admin_id, admin_token = _invite_member(
        client, str(boot["access_token"]), "plain-admin@asterlegal.in", role="admin"
    )
    restricted = client.post(
        f"/api/matters/{matter}/access/restricted",
        headers=owner_headers,
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text

    refused = _invite(client, auth_headers(admin_token), email="r@example.com", matter_ids=[matter])
    assert refused.status_code == 404, refused.text
    assert _portal_rows(company_id) == (0, 0)

    granted = client.post(
        f"/api/matters/{matter}/access/grants",
        headers=owner_headers,
        json={"membership_id": admin_id},
    )
    assert granted.status_code == 200, granted.text
    allowed = _invite(client, auth_headers(admin_token), email="r@example.com", matter_ids=[matter])
    assert allowed.status_code == 201, allowed.text


def test_member_role_and_other_tenant_cannot_invite(client: TestClient) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    matter = _create_matter(client, str(boot["access_token"]), "PORTAL-ROLE")
    _member_id, member_token = _invite_member(
        client, str(boot["access_token"]), "member@asterlegal.in", role="member"
    )
    forbidden = _invite(
        client, auth_headers(member_token), email="m@example.com", matter_ids=[matter]
    )
    assert forbidden.status_code == 403, forbidden.text

    client.cookies.clear()
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Firm LLP",
            "company_slug": "other-firm-portal",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@otherfirm.in",
            "owner_password": "FoundersPass123!",
        },
    )
    assert other.status_code == 200, other.text
    client.cookies.clear()
    foreign = _invite(
        client,
        auth_headers(str(other.json()["access_token"])),
        email="m@example.com",
        matter_ids=[matter],
    )
    assert foreign.status_code == 404, foreign.text
    assert foreign.json()["detail"] == "Matter not found."
    assert _portal_rows(company_id) == (0, 0)
    assert _portal_rows(str(other.json()["company"]["id"])) == (0, 0)


def test_walled_admin_cannot_grant_list_or_revoke_a_walled_ip_docket(
    client: TestClient,
) -> None:
    owner_headers, docket, _application = _rich_portfolio_fixture(client)
    me = client.get("/api/auth/me", headers=owner_headers)
    assert me.status_code == 200, me.text
    company_id = str(me.json()["company"]["id"])
    owner_token = owner_headers["Authorization"].split(" ", 1)[1]
    admin_id, admin_token = _invite_member(
        client, owner_token, "ip-walled-admin@asterlegal.in", role="admin"
    )
    admin_headers = auth_headers(admin_token)
    # IP records carry their own walls (linked Matter access is not inherited).
    panel = client.get(f"/api/ip/dockets/{docket['id']}/access", headers=owner_headers)
    assert panel.status_code == 200, panel.text
    wall_payload = {
        "action": "add_wall",
        "expected_access_policy_version": panel.json()["access_policy_version"],
        "reason": "Conflict check requires immediate exclusion.",
        "subject_type": "membership",
        "subject_id": admin_id,
    }
    preview = client.post(
        f"/api/ip/dockets/{docket['id']}/access/preview", headers=owner_headers, json=wall_payload
    )
    assert preview.status_code == 200, preview.text
    applied = client.post(
        f"/api/ip/dockets/{docket['id']}/access/apply",
        headers=owner_headers,
        json={**wall_payload, "preview_token": preview.json()["preview_token"]},
    )
    assert applied.status_code == 200, applied.text
    assert client.get(f"/api/ip/dockets/{docket['id']}", headers=admin_headers).status_code == 404

    refused = _invite(
        client, admin_headers, email="ip-client@example.com", ip_docket_ids=[docket["id"]]
    )
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"] == "IP record not found."
    assert _portal_rows(company_id) == (0, 0)
    assert _denials(company_id, docket["id"])

    owner_invite = _invite(
        client, owner_headers, email="ip-client@example.com", ip_docket_ids=[docket["id"]]
    )
    assert owner_invite.status_code == 201, owner_invite.text
    grant = owner_invite.json()["grants"][0]

    owner_list = client.get("/api/admin/portal/ip-grants", headers=owner_headers)
    assert owner_list.status_code == 200, owner_list.text
    assert [row["id"] for row in owner_list.json()["grants"]] == [grant["id"]]

    # The walled admin sees neither the grant nor the docket title.
    admin_list = client.get("/api/admin/portal/ip-grants", headers=admin_headers)
    assert admin_list.status_code == 200, admin_list.text
    assert admin_list.json()["grants"] == []
    assert docket["title"] not in admin_list.text

    revoke = client.post(
        f"/api/admin/portal/ip-grants/{grant['id']}/revoke",
        headers=admin_headers,
        json={"expected_row_version": 1, "reason": "Walled admin should not reach this."},
    )
    assert revoke.status_code == 404, revoke.text
    assert revoke.json()["detail"] == "Portal grant not found."
    with get_session_factory()() as session:
        stored = session.get(MatterPortalGrant, grant["id"])
        assert stored is not None and stored.revoked_at is None

    # The owner can still revoke it.
    owner_revoke = client.post(
        f"/api/admin/portal/ip-grants/{grant['id']}/revoke",
        headers=owner_headers,
        json={"expected_row_version": 1, "reason": "Client access removed by the firm."},
    )
    assert owner_revoke.status_code == 200, owner_revoke.text
