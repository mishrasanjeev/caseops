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


def test_matter_code_available_endpoint(client: TestClient) -> None:
    """Strict Ledger #3 (BUG-021): the intake promote dialog must be
    able to check whether a matter_code is free BEFORE submit. This
    endpoint backs that pre-flight. Verify both branches:

    - A code that doesn't exist returns ``available=true`` and no
      suggestion.
    - A code that's taken returns ``available=false`` plus the next
      lexically-bumped suggestion (so the UI can offer one-click
      'Try this').
    Tenant-scoped — codes from other companies don't leak.
    """
    session = _bootstrap(client, "intake-codecheck")
    headers = _headers(session["access_token"])
    # Seed a matter so we have a known-taken code.
    create = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Seed matter for code check",
            "matter_code": "CR-2026-099",
            "practice_area": "criminal",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert create.status_code == 200, create.text

    # Free code → available, no suggestion.
    free = client.get(
        "/api/matters/code-available",
        headers=headers,
        params={"code": "WRIT-2026-1"},
    )
    assert free.status_code == 200, free.text
    body = free.json()
    assert body == {
        "available": True,
        "normalised": "WRIT-2026-1",
        "suggestion": None,
        "reason": None,
    }

    # Taken code → not available, suggestion bumps the trailing index.
    taken = client.get(
        "/api/matters/code-available",
        headers=headers,
        params={"code": "cr-2026-099"},  # lower-case to prove normalisation
    )
    assert taken.status_code == 200, taken.text
    body = taken.json()
    assert body["available"] is False
    assert body["normalised"] == "CR-2026-099"
    assert body["suggestion"] == "CR-2026-100"
    assert "already in use" in (body["reason"] or "").lower()

    # Tenant isolation — a fresh tenant sees the same code as available.
    other = _bootstrap(client, "intake-codecheck-other")
    other_headers = _headers(other["access_token"])
    isolated = client.get(
        "/api/matters/code-available",
        headers=other_headers,
        params={"code": "CR-2026-099"},
    )
    assert isolated.json()["available"] is True


def test_intake_promote_accepts_slash_matter_code(client: TestClient) -> None:
    """Ram-BUG-003 (2026-04-22): user reported "Could not promote
    request" when entering matter_code ``2065/2026``. Indian court
    filings often use slash-formatted codes (e.g. ``WRIT/220/2026``,
    ``COMAPL/123/2026``) so the schema explicitly allows ``/`` in the
    pattern. This regression pins that contract — if anyone tightens
    the regex, the canonical Indian filing format breaks. The test
    also verifies the promote returns 200 (not the generic 500 the
    bug report described), which would have surfaced as the toast
    Ram saw."""
    session = _bootstrap(client, "intake-slashcode")
    headers = _headers(session["access_token"])
    create = client.post(
        "/api/intake/requests",
        headers=headers,
        json={
            "title": "WRIT petition intake",
            "category": "litigation_support",
            "requester_name": "Solicitor",
            "description": "Quash impugned order, urgent.",
        },
    )
    assert create.status_code == 200, create.text
    request_id = create.json()["id"]

    promote = client.post(
        f"/api/intake/requests/{request_id}/promote",
        headers=headers,
        json={"matter_code": "2065/2026"},
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["linked_matter_code"] == "2065/2026"


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
