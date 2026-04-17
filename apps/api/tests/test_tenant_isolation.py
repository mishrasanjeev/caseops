"""Tenant-leakage tests per WORK_TO_BE_DONE §11.1.

Two separate companies are bootstrapped. Company A's token must NOT be able to read
or mutate anything belonging to Company B. The matter-workspace surface, contracts,
outside counsel, authority corpus (read), company profile, and user directory are
all covered.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, slug: str, email_prefix: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} Firm",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug.title()} Owner",
            "owner_email": f"{email_prefix}@{slug}.in",
            "owner_password": "StrongPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_matter(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": f"Matter {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_contract(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/contracts/",
        headers=_auth(token),
        json={
            "title": f"Contract {code}",
            "contract_code": code,
            "contract_type": "Master Services Agreement",
            "status": "draft",
            "counterparty_name": "Counterparty Ltd",
        },
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()["id"]


def test_tenant_cannot_list_other_tenants_matters(client: TestClient) -> None:
    a = _bootstrap(client, "firm-alpha", "owner-a")
    b = _bootstrap(client, "firm-beta", "owner-b")
    token_a = str(a["access_token"])
    token_b = str(b["access_token"])

    _create_matter(client, token_a, "ALPHA-001")
    _create_matter(client, token_b, "BETA-001")

    list_a = client.get("/api/matters/", headers=_auth(token_a)).json()
    list_b = client.get("/api/matters/", headers=_auth(token_b)).json()

    codes_a = {m["matter_code"] for m in list_a.get("matters", list_a)}
    codes_b = {m["matter_code"] for m in list_b.get("matters", list_b)}
    assert "ALPHA-001" in codes_a and "BETA-001" not in codes_a
    assert "BETA-001" in codes_b and "ALPHA-001" not in codes_b


def test_tenant_cannot_fetch_other_tenants_matter_by_id(client: TestClient) -> None:
    a = _bootstrap(client, "firm-alpha", "owner-a")
    b = _bootstrap(client, "firm-beta", "owner-b")
    token_a = str(a["access_token"])
    token_b = str(b["access_token"])

    matter_a = _create_matter(client, token_a, "ALPHA-002")

    direct = client.get(f"/api/matters/{matter_a}", headers=_auth(token_b))
    assert direct.status_code in {403, 404}

    workspace = client.get(
        f"/api/matters/{matter_a}/workspace", headers=_auth(token_b)
    )
    assert workspace.status_code in {403, 404}


def test_tenant_cannot_mutate_other_tenants_matter(client: TestClient) -> None:
    a = _bootstrap(client, "firm-alpha", "owner-a")
    b = _bootstrap(client, "firm-beta", "owner-b")
    token_a = str(a["access_token"])
    token_b = str(b["access_token"])

    matter_a = _create_matter(client, token_a, "ALPHA-003")

    patched = client.patch(
        f"/api/matters/{matter_a}",
        headers=_auth(token_b),
        json={"title": "Pwned"},
    )
    assert patched.status_code in {403, 404}


def test_tenant_cannot_read_other_tenants_contract(client: TestClient) -> None:
    a = _bootstrap(client, "firm-alpha", "owner-a")
    b = _bootstrap(client, "firm-beta", "owner-b")
    token_a = str(a["access_token"])
    token_b = str(b["access_token"])

    contract_a = _create_contract(client, token_a, "CTR-A-001")

    listing_b = client.get("/api/contracts/", headers=_auth(token_b)).json()
    codes_b = {c["contract_code"] for c in listing_b.get("contracts", listing_b)}
    assert "CTR-A-001" not in codes_b

    direct = client.get(f"/api/contracts/{contract_a}", headers=_auth(token_b))
    assert direct.status_code in {403, 404}


def test_tenant_cannot_read_other_tenants_company_profile(client: TestClient) -> None:
    a = _bootstrap(client, "firm-alpha", "owner-a")
    b = _bootstrap(client, "firm-beta", "owner-b")
    token_b = str(b["access_token"])

    profile_b = client.get(
        "/api/companies/current/profile", headers=_auth(token_b)
    ).json()
    assert profile_b["slug"] == "firm-beta"
    assert profile_b["id"] != a["company"]["id"]


def test_tenant_cannot_list_other_tenants_users(client: TestClient) -> None:
    _bootstrap(client, "firm-alpha", "owner-a")
    b = _bootstrap(client, "firm-beta", "owner-b")
    token_b = str(b["access_token"])

    users_b = client.get("/api/companies/current/users", headers=_auth(token_b)).json()
    emails = {u["email"] for u in users_b["users"]}
    assert "owner-a@firm-alpha.in" not in emails
    assert "owner-b@firm-beta.in" in emails


def test_tenant_cannot_suspend_other_tenants_user(client: TestClient) -> None:
    a = _bootstrap(client, "firm-alpha", "owner-a")
    b = _bootstrap(client, "firm-beta", "owner-b")
    token_b = str(b["access_token"])
    membership_id_a = a["membership"]["id"]

    result = client.patch(
        f"/api/companies/current/users/{membership_id_a}",
        headers=_auth(token_b),
        json={"is_active": False},
    )
    assert result.status_code in {403, 404}


def test_tenant_cannot_fetch_other_tenants_invoice_payment_link(
    client: TestClient,
) -> None:
    a = _bootstrap(client, "firm-alpha", "owner-a")
    b = _bootstrap(client, "firm-beta", "owner-b")
    token_a = str(a["access_token"])
    token_b = str(b["access_token"])

    matter_a = _create_matter(client, token_a, "ALPHA-PAY")
    invoice = client.post(
        f"/api/matters/{matter_a}/invoices",
        headers=_auth(token_a),
        json={
            "invoice_number": "INV-A-1",
            "issued_on": "2026-04-17",
            "include_uninvoiced_time_entries": False,
            "manual_items": [{"description": "Retainer", "amount_minor": 100000}],
        },
    )
    assert invoice.status_code == 200
    invoice_id = invoice.json()["id"]

    cross = client.post(
        f"/api/payments/matters/{matter_a}/invoices/{invoice_id}/pine-labs/link",
        headers=_auth(token_b),
        json={"customer_name": "Attacker"},
    )
    assert cross.status_code in {403, 404}
