"""BUG-001: manual trademark docketing depends on the ip:write capability only.

Ram's tenant (test-legal) lists every IP automation as missing_entitlement.
Creating a trademark application by hand must still work for a member whose
role grants ip:write, and be refused for one whose role does not, so the
"New trademark" control the page offers can never be one that only fails.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company

MANUAL_ROUTE = "/api/ip/trademark-applications/manual"
NOT_AUTOMATIONS = {"workspace_core", "manual_docketing", "taxonomy_admin"}


def _payload(title: str) -> dict:
    return {
        "title": title,
        "asset_title": "PLANLESS",
        "jurisdiction": "IN",
        "office": "IP India",
        "filing_phase": "draft",
        "source_pending_identifier_allocation": False,
        "application_number": None,
        "particulars": {
            "form_key": "TM-A",
            "form_version": "2026.1",
            "mark_kind": "word",
            "representation": {"text": "PLANLESS", "evidence_reference": "attachment:planless"},
            "classes": [{"class_number": 9, "specification": "Downloadable software"}],
            "use_priority": None,
            "parties": [{"role": "applicant", "name": "Planless Applicant LLP"}],
            "agent": None,
            "filing_manifest": [],
        },
    }


def _member(
    client: TestClient, owner: dict[str, str], *, name: str, email: str, permissions: list[str]
) -> dict[str, str]:
    role = client.post(
        "/api/companies/current/roles",
        headers=owner,
        json={"name": name, "base_role": "member", "permissions": permissions},
    )
    assert role.status_code == 200, role.text
    user = client.post(
        "/api/companies/current/users",
        headers=owner,
        json={"full_name": name, "email": email, "role": "member", "password": "PlanlessPass123!"},
    )
    assert user.status_code == 200, user.text
    assigned = client.post(
        f"/api/companies/current/employees/{user.json()['membership_id']}/role",
        headers=owner,
        json={"custom_role_id": role.json()["id"]},
    )
    assert assigned.status_code == 200, assigned.text
    login = client.post(
        "/api/auth/login",
        json={"company_slug": "aster-legal", "email": email, "password": "PlanlessPass123!"},
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return auth_headers(str(login.json()["access_token"]))


def test_manual_docketing_needs_ip_write_not_a_plan(client: TestClient) -> None:
    owner = auth_headers(str(bootstrap_company(client)["access_token"]))
    reader = _member(
        client, owner, name="IP Reader", email="reader@asterlegal.in", permissions=["ip:read"]
    )
    writer = _member(
        client,
        owner,
        name="IP Docketing Clerk",
        email="clerk@asterlegal.in",
        permissions=["ip:read", "ip:write"],
    )

    # The tenant is in Ram's state: no plan carries any IP automation.
    readiness = client.get("/api/ip/readiness", headers=writer)
    assert readiness.status_code == 200, readiness.text
    automations = [
        feature
        for feature in readiness.json()["features"]
        if feature["feature_id"] not in NOT_AUTOMATIONS
    ]
    assert len(automations) == 8
    for feature in automations:
        assert feature["available"] is False, feature
        assert "missing_entitlement" in feature["blocked_reasons"], feature

    refused = client.post(MANUAL_ROUTE, headers=reader, json=_payload("Reader filing attempt"))
    assert refused.status_code == 403, refused.text

    created = client.post(MANUAL_ROUTE, headers=writer, json=_payload("Clerk manual filing"))
    assert created.status_code == 201, created.text
    docket_id = created.json()["docket"]["id"]
    listed = client.get("/api/ip/dockets", headers=reader)
    assert listed.status_code == 200, listed.text
    assert [row["title"] for row in listed.json()["dockets"]] == ["Clerk manual filing"]

    # Another tenant neither sees nor reaches the record.
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Birch Legal LLP",
            "company_slug": "birch-legal",
            "company_type": "law_firm",
            "owner_full_name": "Birch Owner",
            "owner_email": "owner@birchlegal.in",
            "owner_password": "BirchPass123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))
    assert client.get(f"/api/ip/dockets/{docket_id}", headers=other_headers).status_code == 404
    assert client.get("/api/ip/dockets", headers=other_headers).json()["dockets"] == []
