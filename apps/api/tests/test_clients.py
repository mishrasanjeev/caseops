"""MOD-TS-009 — Clients CRUD + per-matter assignment.

Covers:

- create / list / get / update / archive lifecycle
- tenant isolation (Tenant B cannot see / edit / archive Tenant A's client)
- `(company_id, name, client_type)` uniqueness constraint
- per-matter assign + unassign
- capability guard — viewer role cannot create/edit/archive
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def _mk_matter(client: TestClient, token: str, code: str = "CL-001") -> dict:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Clients regression — {code}",
            "matter_code": code,
            "practice_area": "civil",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mk_client(client: TestClient, token: str, **overrides) -> dict:
    body = {
        "name": "Acme Industries Pvt Ltd",
        "client_type": "corporate",
        "primary_contact_name": "Hari",
        "primary_contact_email": "hari@acme.example",
        "primary_contact_phone": "+91 98765 43210",
        "city": "Bengaluru",
    } | overrides
    resp = client.post(
        "/api/clients/", headers=auth_headers(token), json=body,
    )
    return resp


# ---------------------------------------------------------------
# Happy-path CRUD
# ---------------------------------------------------------------


def test_client_create_then_list_contains_it(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    create = _mk_client(client, token)
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["name"] == "Acme Industries Pvt Ltd"
    assert created["client_type"] == "corporate"
    assert created["is_active"] is True
    assert created["kyc_status"] == "not_started"

    lst = client.get("/api/clients/", headers=auth_headers(token))
    assert lst.status_code == 200
    ids = {c["id"] for c in lst.json()["clients"]}
    assert created["id"] in ids


def test_client_get_returns_profile(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]
    resp = client.get(f"/api/clients/{cid}", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == cid
    assert resp.json()["matters"] == []
    assert resp.json()["total_matters_count"] == 0


def test_client_full_address_round_trips(client: TestClient) -> None:
    """Strict Ledger #4 (BUG-022, 2026-04-22): the prior schema only
    persisted city/state/country, so a typed door-no + street was
    silently discarded. Migration 20260422_0002 added
    address_line_1, address_line_2, postal_code; this regression
    proves all three fields round-trip cleanly through create →
    fetch → update → re-fetch.
    """
    token = str(bootstrap_company(client)["access_token"])
    create = _mk_client(
        client,
        token,
        address_line_1="Door no. 12, MG Road",
        address_line_2="Brigade Towers, 4th floor",
        city="Bengaluru",
        state="Karnataka",
        postal_code="560001",
        country="India",
    )
    assert create.status_code == 200, create.text
    created = create.json()
    assert created["address_line_1"] == "Door no. 12, MG Road"
    assert created["address_line_2"] == "Brigade Towers, 4th floor"
    assert created["postal_code"] == "560001"
    assert created["city"] == "Bengaluru"
    assert created["state"] == "Karnataka"
    assert created["country"] == "India"

    # Fetch — same shape comes back.
    fetched = client.get(
        f"/api/clients/{created['id']}", headers=auth_headers(token),
    )
    assert fetched.status_code == 200
    body = fetched.json()
    for field in (
        "address_line_1", "address_line_2", "postal_code",
        "city", "state", "country",
    ):
        assert body[field] == created[field], (field, body[field])

    # Update — patch all four address-tier fields and re-read.
    patch = client.patch(
        f"/api/clients/{created['id']}",
        headers=auth_headers(token),
        json={
            "address_line_1": "1 Embassy Park Drive",
            "address_line_2": None,  # explicit clear
            "postal_code": "560034",
        },
    )
    assert patch.status_code == 200, patch.text
    updated = patch.json()
    assert updated["address_line_1"] == "1 Embassy Park Drive"
    assert updated["address_line_2"] is None
    assert updated["postal_code"] == "560034"


def test_client_update_changes_fields(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]
    resp = client.patch(
        f"/api/clients/{cid}",
        headers=auth_headers(token),
        json={"primary_contact_name": "Hari Gupta", "kyc_status": "verified"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["primary_contact_name"] == "Hari Gupta"
    assert resp.json()["kyc_status"] == "verified"


def test_client_archive_flips_is_active(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]
    resp = client.delete(f"/api/clients/{cid}", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    # Get still works — archive is a soft-delete.
    check = client.get(f"/api/clients/{cid}", headers=auth_headers(token))
    assert check.status_code == 200
    assert check.json()["is_active"] is False


# ---------------------------------------------------------------
# Validation + uniqueness
# ---------------------------------------------------------------


def test_client_create_rejects_unknown_type(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = _mk_client(client, token, client_type="alien")
    assert resp.status_code == 422  # Pydantic literal rejects at schema layer


def test_client_create_dedup_conflicts_on_same_name_and_type(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    a = _mk_client(client, token, name="Acme Corp", client_type="corporate")
    assert a.status_code == 200
    b = _mk_client(client, token, name="Acme Corp", client_type="corporate")
    assert b.status_code == 409
    assert "already exists" in b.json()["detail"].lower()


def test_client_same_name_different_type_is_allowed(client: TestClient) -> None:
    """Uniqueness is on ``(company_id, name, client_type)`` — so the
    same name CAN be used across two types (e.g., an individual and
    their corporation can share a surname)."""
    token = str(bootstrap_company(client)["access_token"])
    a = _mk_client(client, token, name="Sharma", client_type="individual")
    assert a.status_code == 200
    b = _mk_client(client, token, name="Sharma", client_type="corporate")
    assert b.status_code == 200


# ---------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------


def test_client_cross_tenant_404s(client: TestClient) -> None:
    token_a = str(bootstrap_company(client)["access_token"])
    a_id = _mk_client(client, token_a).json()["id"]

    token_b_resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B LLP",
            "company_slug": "tenant-b-clients",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "b@tenant-b.example",
            "owner_password": "TenantB-Strong!234",
        },
    )
    token_b = str(token_b_resp.json()["access_token"])

    # Tenant B tries to GET / PATCH / DELETE Tenant A's client.
    assert client.get(f"/api/clients/{a_id}", headers=auth_headers(token_b)).status_code == 404
    assert client.patch(
        f"/api/clients/{a_id}", headers=auth_headers(token_b), json={"name": "hacked"},
    ).status_code == 404
    assert client.delete(
        f"/api/clients/{a_id}", headers=auth_headers(token_b),
    ).status_code == 404


# ---------------------------------------------------------------
# Per-matter assignment
# ---------------------------------------------------------------


def test_assign_client_to_matter_then_see_on_client_profile(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="CL-ASSIGN-1")
    client_profile = _mk_client(client, token).json()

    assign = client.post(
        f"/api/matters/{matter['id']}/clients",
        headers=auth_headers(token),
        json={"client_id": client_profile["id"], "role": "petitioner"},
    )
    assert assign.status_code == 200, assign.text
    assert assign.json()["role"] == "petitioner"
    assert assign.json()["is_primary"] is True

    # Client profile now shows the matter link.
    profile = client.get(
        f"/api/clients/{client_profile['id']}", headers=auth_headers(token),
    ).json()
    assert profile["total_matters_count"] == 1
    assert profile["active_matters_count"] == 1
    assert profile["matters"][0]["matter_id"] == matter["id"]
    assert profile["matters"][0]["role"] == "petitioner"


def test_assign_client_is_idempotent_on_repost(client: TestClient) -> None:
    """A second POST with the same (matter, client) pair updates role/
    is_primary rather than erroring. Keeps the UX simple (one button)."""
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="CL-ASSIGN-2")
    cid = _mk_client(client, token).json()["id"]

    one = client.post(
        f"/api/matters/{matter['id']}/clients",
        headers=auth_headers(token),
        json={"client_id": cid, "role": "petitioner"},
    )
    two = client.post(
        f"/api/matters/{matter['id']}/clients",
        headers=auth_headers(token),
        json={"client_id": cid, "role": "respondent", "is_primary": False},
    )
    assert one.status_code == 200
    assert two.status_code == 200
    assert two.json()["id"] == one.json()["id"]
    assert two.json()["role"] == "respondent"
    assert two.json()["is_primary"] is False


def test_unassign_client_from_matter(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="CL-ASSIGN-3")
    cid = _mk_client(client, token).json()["id"]

    client.post(
        f"/api/matters/{matter['id']}/clients",
        headers=auth_headers(token),
        json={"client_id": cid},
    )
    rm = client.delete(
        f"/api/matters/{matter['id']}/clients/{cid}",
        headers=auth_headers(token),
    )
    assert rm.status_code == 204

    # Client profile matters list goes back to empty.
    profile = client.get(
        f"/api/clients/{cid}", headers=auth_headers(token),
    ).json()
    assert profile["total_matters_count"] == 0


def test_assign_nonexistent_client_404s(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="CL-ASSIGN-4")
    resp = client.post(
        f"/api/matters/{matter['id']}/clients",
        headers=auth_headers(token),
        json={"client_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404


def test_unassign_unknown_pair_404s(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="CL-ASSIGN-5")
    cid = _mk_client(client, token).json()["id"]
    resp = client.delete(
        f"/api/matters/{matter['id']}/clients/{cid}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------


def test_client_crud_emits_audit_events(client: TestClient) -> None:
    """Create / update / archive must each emit an audit_events row so
    governance can trace who touched a client record."""
    from caseops_api.db.models import AuditEvent
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]
    client.patch(
        f"/api/clients/{cid}",
        headers=auth_headers(token),
        json={"kyc_status": "verified"},
    )
    client.delete(f"/api/clients/{cid}", headers=auth_headers(token))

    factory = get_session_factory()
    with factory() as session:
        from sqlalchemy import select
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.target_id == cid)
                .order_by(AuditEvent.created_at)
            )
        )
    actions = [e.action for e in events]
    assert "client.created" in actions
    assert "client.updated" in actions
    assert "client.archived" in actions
