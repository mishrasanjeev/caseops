"""GC intake queue regression (Sprint 8b BG-025)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _bootstrap(client: TestClient, slug: str) -> dict[str, str]:
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"Intake Test {slug}",
            "company_slug": slug,
            "company_type": "corporate_legal",
            "owner_full_name": "Intake Owner",
            "owner_email": f"owner-{slug}@example.com",
            "owner_password": "IntakePass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_intake_create_list_update_promote(client: TestClient) -> None:
    session = _bootstrap(client, "intake-happy")
    token = session["access_token"]
    headers = _headers(token)

    # Create.
    resp = client.post(
        "/api/intake/requests",
        headers=headers,
        json={
            "title": "Review SaaS MSA with Stripe",
            "category": "contract_review",
            "priority": "high",
            "requester_name": "Anita Business",
            "requester_email": "anita@acme.in",
            "business_unit": "Product",
            "description": "Vendor sent a standard MSA. Need legal review before signature.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "new"
    assert body["priority"] == "high"
    assert body["submitted_by_name"] == "Intake Owner"
    request_id = body["id"]

    # List.
    list_resp = client.get("/api/intake/requests", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()["requests"]) == 1

    # Update: triage + assign to self.
    membership_id = session["membership"]["id"]
    patch = client.patch(
        f"/api/intake/requests/{request_id}",
        headers=headers,
        json={
            "status": "triaging",
            "assigned_to_membership_id": membership_id,
            "triage_notes": "Standard commercial MSA, low risk.",
        },
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["status"] == "triaging"
    assert patch.json()["assigned_to_membership_id"] == membership_id

    # Promote: becomes a real matter, status flips to in_progress.
    promote = client.post(
        f"/api/intake/requests/{request_id}/promote",
        headers=headers,
        json={
            "matter_code": "INT-STRIPE-001",
            "practice_area": "commercial",
            "forum_level": "high_court",
        },
    )
    assert promote.status_code == 200, promote.text
    promoted = promote.json()
    assert promoted["status"] == "in_progress"
    assert promoted["linked_matter_id"] is not None
    assert promoted["linked_matter_code"] == "INT-STRIPE-001"


def test_intake_rejects_cross_tenant_access(client: TestClient) -> None:
    # Tenant A creates an intake request.
    session_a = _bootstrap(client, "intake-tenant-a")
    create = client.post(
        "/api/intake/requests",
        headers=_headers(session_a["access_token"]),
        json={
            "title": "Private to tenant A",
            "category": "other",
            "priority": "low",
            "requester_name": "Tenant A Requester",
            "description": "This must not be visible to tenant B.",
        },
    )
    assert create.status_code == 200
    request_id = create.json()["id"]

    # Tenant B tries to fetch/patch/promote it — all 404 because the
    # service filters by company_id before the row check.
    session_b = _bootstrap(client, "intake-tenant-b")
    headers_b = _headers(session_b["access_token"])
    list_b = client.get("/api/intake/requests", headers=headers_b).json()
    assert list_b["requests"] == []

    patch_b = client.patch(
        f"/api/intake/requests/{request_id}",
        headers=headers_b,
        json={"status": "rejected"},
    )
    assert patch_b.status_code == 404

    promote_b = client.post(
        f"/api/intake/requests/{request_id}/promote",
        headers=headers_b,
        json={"matter_code": "HIJACK-001"},
    )
    assert promote_b.status_code == 404


def test_intake_promote_blocked_when_terminal(client: TestClient) -> None:
    session = _bootstrap(client, "intake-terminal")
    headers = _headers(session["access_token"])
    create = client.post(
        "/api/intake/requests",
        headers=headers,
        json={
            "title": "Already rejected",
            "category": "other",
            "priority": "low",
            "requester_name": "Someone",
            "description": "Reject this one.",
        },
    )
    request_id = create.json()["id"]

    # Mark as rejected.
    client.patch(
        f"/api/intake/requests/{request_id}",
        headers=headers,
        json={"status": "rejected"},
    )

    # Now promotion should 409 — terminal state.
    promote = client.post(
        f"/api/intake/requests/{request_id}/promote",
        headers=headers,
        json={"matter_code": "NO-GOOD-001"},
    )
    assert promote.status_code == 409
    assert "rejected" in promote.json()["detail"].lower()


def test_intake_status_filter(client: TestClient) -> None:
    session = _bootstrap(client, "intake-filter")
    headers = _headers(session["access_token"])

    # Two requests, one triaged.
    r1 = client.post(
        "/api/intake/requests",
        headers=headers,
        json={
            "title": "New one",
            "category": "other",
            "priority": "low",
            "requester_name": "Alex Requester",
            "description": "Still new — please leave this as new status.",
        },
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        "/api/intake/requests",
        headers=headers,
        json={
            "title": "Triage me",
            "category": "other",
            "priority": "high",
            "requester_name": "Bella Counsel",
            "description": "Please triage this promptly.",
        },
    )
    assert r2.status_code == 200, r2.text
    client.patch(
        f"/api/intake/requests/{r2.json()['id']}",
        headers=headers,
        json={"status": "triaging"},
    )

    new_only = client.get(
        "/api/intake/requests?status=new", headers=headers
    ).json()["requests"]
    assert len(new_only) == 1
    assert new_only[0]["id"] == r1.json()["id"]

    triaging = client.get(
        "/api/intake/requests?status=triaging", headers=headers
    ).json()["requests"]
    assert len(triaging) == 1
    assert triaging[0]["id"] == r2.json()["id"]
