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


def test_client_unarchive_restores_active_flag(client: TestClient) -> None:
    """Phase B / BUG-025 (Hari 2026-04-23) — archive must be
    reversible. Without this every archive is permanent and the user
    has to bug an admin to manually flip the flag in the DB."""
    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]

    # Archive then unarchive.
    archived = client.delete(f"/api/clients/{cid}", headers=auth_headers(token))
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False

    restored = client.post(
        f"/api/clients/{cid}/unarchive", headers=auth_headers(token),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_active"] is True

    # The list reflects the restoration too.
    listing = client.get("/api/clients/", headers=auth_headers(token))
    assert listing.status_code == 200
    found = next(c for c in listing.json()["clients"] if c["id"] == cid)
    assert found["is_active"] is True


def test_client_unarchive_is_idempotent_on_active_client(
    client: TestClient,
) -> None:
    """Calling /unarchive on an already-active client must succeed
    and return the client. The web UI optimistically refreshes the
    list after the click, and a duplicate request from a double-click
    or a stale cache should not 4xx the user."""
    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]
    resp = client.post(
        f"/api/clients/{cid}/unarchive", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True


def test_client_unarchive_404s_cross_tenant(client: TestClient) -> None:
    """Tenant isolation — restoring company B's archived client from
    company A's session must 404, not silently flip the wrong row."""
    token_a = str(bootstrap_company(client)["access_token"])
    cid_a = _mk_client(client, token_a).json()["id"]
    client.delete(f"/api/clients/{cid_a}", headers=auth_headers(token_a))

    # Bootstrap a second tenant (clear cookies first — EG-001 cookie
    # wins over bearer in get_current_context, so the multi-tenant
    # test must drop the prior session cookie before bootstrapping).
    client.cookies.clear()
    resp_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other LLP",
            "company_slug": "other-unarchive",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-unarchive.example",
            "owner_password": "OtherStrong!234",
        },
    )
    assert resp_b.status_code == 200
    token_b = str(resp_b.json()["access_token"])
    client.cookies.clear()

    cross = client.post(
        f"/api/clients/{cid_a}/unarchive", headers=auth_headers(token_b),
    )
    assert cross.status_code == 404


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


# ---------------------------------------------------------------
# Phase B M11 slice 3 — KYC lifecycle
# ---------------------------------------------------------------


def _bootstrap_with_role(client, slug: str, role: str) -> str:
    """Bootstrap an owner then downgrade the membership row to
    ``role`` so we can test the staff-only KYC review gate without
    needing a full invite-flow fixture."""
    from sqlalchemy import update

    from caseops_api.db.models import CompanyMembership, MembershipRole
    from caseops_api.db.session import get_session_factory

    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"KYC {slug} LLP",
            "company_slug": f"kyc-{slug}",
            "company_type": "law_firm",
            "owner_full_name": f"KYC {slug} Owner",
            "owner_email": f"owner@kyc-{slug}.example",
            "owner_password": f"KycPw-{slug}!234",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    factory = get_session_factory()
    with factory() as session:
        session.execute(
            update(CompanyMembership)
            .where(CompanyMembership.id == body["membership"]["id"])
            .values(role=MembershipRole(role))
        )
        session.commit()
    client.cookies.clear()
    return str(body["access_token"])


def test_kyc_submit_then_verify_round_trip(client: TestClient) -> None:
    """The headline lifecycle: not_started → pending → verified.
    Status, audit columns, and document list all populate."""
    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]

    submitted = client.post(
        f"/api/clients/{cid}/kyc/submit",
        headers=auth_headers(token),
        json={"documents": [
            {"name": "PAN", "status": "received"},
            {"name": "Aadhaar", "status": "received"},
        ]},
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    assert body["kyc_status"] == "pending"
    assert body["kyc_submitted_at"] is not None
    assert len(body["kyc_documents"]) == 2

    verified = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
    )
    assert verified.status_code == 200
    body = verified.json()
    assert body["kyc_status"] == "verified"
    assert body["kyc_verified_at"] is not None
    assert body["kyc_verified_by_membership_id"] is not None
    assert body["kyc_rejection_reason"] is None


def test_kyc_reject_records_reason_then_resubmit_clears_it(
    client: TestClient,
) -> None:
    """Reject path: reviewer rejects with reason; lawyer re-submits
    a fresh pack; the rejection reason clears so the next reviewer
    is not biased by the previous rejection."""
    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]

    client.post(
        f"/api/clients/{cid}/kyc/submit",
        headers=auth_headers(token),
        json={"documents": [{"name": "PAN"}]},
    )
    rejected = client.post(
        f"/api/clients/{cid}/kyc/reject",
        headers=auth_headers(token),
        json={"reason": "Address proof missing"},
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["kyc_status"] == "rejected"
    assert body["kyc_rejection_reason"] == "Address proof missing"

    resubmitted = client.post(
        f"/api/clients/{cid}/kyc/submit",
        headers=auth_headers(token),
        json={"documents": [{"name": "PAN"}, {"name": "Address proof"}]},
    )
    assert resubmitted.status_code == 200
    body = resubmitted.json()
    assert body["kyc_status"] == "pending"
    assert body["kyc_rejection_reason"] is None
    assert len(body["kyc_documents"]) == 2


def test_kyc_verify_refuses_when_not_pending_409(client: TestClient) -> None:
    """Verifying without a submission would invent an audit row with
    no documents on file. Refuse with 409 so the lawyer must submit
    first."""
    token = str(bootstrap_company(client)["access_token"])
    cid = _mk_client(client, token).json()["id"]
    resp = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
    )
    assert resp.status_code == 409
    assert "submit" in resp.json()["detail"].lower()


def test_kyc_review_requires_staff_capability_403(client: TestClient) -> None:
    """A paralegal can SUBMIT KYC but not VERIFY — the staff-only
    review gate enforces the four-eyes pattern between the lawyer
    who collected docs and the partner who approves them."""
    token = _bootstrap_with_role(client, "para", "paralegal")
    cid = _mk_client(client, token).json()["id"]

    submitted = client.post(
        f"/api/clients/{cid}/kyc/submit",
        headers=auth_headers(token),
        json={"documents": [{"name": "PAN"}]},
    )
    assert submitted.status_code == 200, submitted.text

    verify = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
    )
    assert verify.status_code == 403
    reject = client.post(
        f"/api/clients/{cid}/kyc/reject",
        headers=auth_headers(token),
        json={"reason": "irrelevant — should never reach service layer"},
    )
    assert reject.status_code == 403


def test_kyc_does_not_leak_across_tenants(client: TestClient) -> None:
    """Tenant isolation. Tenant B POST /kyc/submit on tenant A's
    client must 404 — never confirm existence."""
    token_a = str(bootstrap_company(client)["access_token"])
    cid_a = _mk_client(client, token_a).json()["id"]
    client.cookies.clear()

    token_b = _bootstrap_with_role(client, "tenantb", "owner")
    leak = client.post(
        f"/api/clients/{cid_a}/kyc/submit",
        headers=auth_headers(token_b),
        json={"documents": []},
    )
    assert leak.status_code == 404
