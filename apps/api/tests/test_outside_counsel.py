from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(
    client: TestClient,
    token: str,
    *,
    title: str,
    matter_code: str,
    practice_area: str = "Commercial Litigation",
    forum_level: str = "high_court",
    court_name: str | None = "Delhi High Court",
) -> dict[str, object]:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": title,
            "matter_code": matter_code,
            "client_name": "Aster Group",
            "opposing_party": "Contoso Infra",
            "status": "active",
            "practice_area": practice_area,
            "forum_level": forum_level,
            "court_name": court_name,
            "description": "Strategic litigation workflow.",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_owner_can_manage_outside_counsel_and_spend_workspace(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter = _create_matter(
        client,
        token,
        title="North Arc Projects v. State",
        matter_code="COMM-2026-401",
    )

    profile_response = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(token),
        json={
            "name": "Khanna Advisory Chambers",
            "primary_contact_name": "Anika Khanna",
            "primary_contact_email": "anika@khannaadvisory.in",
            "primary_contact_phone": "+91-9876543210",
            "firm_city": "New Delhi",
            "jurisdictions": ["Delhi High Court", "Supreme Court of India"],
            "practice_areas": ["Commercial Litigation", "Arbitration"],
            "panel_status": "preferred",
            "internal_notes": "Strong on urgent injunction and admission work.",
        },
    )
    assert profile_response.status_code == 200
    counsel = profile_response.json()

    assignment_response = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "role_summary": "High Court strategy and final argument support",
            "budget_amount_minor": 500000,
            "currency": "INR",
            "status": "approved",
            "internal_notes": "Approval from litigation head recorded.",
        },
    )
    assert assignment_response.status_code == 200
    assignment = assignment_response.json()
    assert assignment["budget_amount_minor"] == 500000

    spend_response = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "assignment_id": assignment["id"],
            "invoice_reference": "KAC/2026/044",
            "stage_label": "Interim relief hearing",
            "description": "Interim hearing fee and preparation conferences",
            "currency": "INR",
            "amount_minor": 250000,
            "approved_amount_minor": 200000,
            "status": "partially_approved",
            "notes": "Capped after budget review.",
        },
    )
    assert spend_response.status_code == 200
    spend_record = spend_response.json()
    assert spend_record["approved_amount_minor"] == 200000
    assert spend_record["status"] == "partially_approved"

    workspace_response = client.get(
        "/api/outside-counsel/workspace",
        headers=auth_headers(token),
    )
    assert workspace_response.status_code == 200
    payload = workspace_response.json()
    assert payload["summary"]["total_counsel_count"] == 1
    assert payload["summary"]["active_assignment_count"] == 1
    assert payload["summary"]["total_budget_minor"] == 500000
    assert payload["summary"]["total_spend_minor"] == 250000
    assert payload["summary"]["approved_spend_minor"] == 200000
    assert payload["profiles"][0]["name"] == "Khanna Advisory Chambers"
    assert payload["profiles"][0]["approved_spend_minor"] == 200000
    assert payload["assignments"][0]["matter_code"] == "COMM-2026-401"
    assert payload["spend_records"][0]["invoice_reference"] == "KAC/2026/044"


def test_recommendations_prefer_matching_counsel_history(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    prior_matter = _create_matter(
        client,
        token,
        title="Alpha Holdings commercial appeal",
        matter_code="COMM-2026-210",
        practice_area="Commercial Litigation",
        forum_level="high_court",
        court_name="Delhi High Court",
    )
    unrelated_matter = _create_matter(
        client,
        token,
        title="Beta Energy arbitration",
        matter_code="ARB-2026-310",
        practice_area="Arbitration",
        forum_level="arbitration",
        court_name="SIAC",
    )
    target_matter = _create_matter(
        client,
        token,
        title="Gamma Projects special appeal",
        matter_code="COMM-2026-999",
        practice_area="Commercial Litigation",
        forum_level="high_court",
        court_name="Delhi High Court",
    )

    strong_counsel = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(token),
        json={
            "name": "Dua Litigation Office",
            "jurisdictions": ["Delhi High Court"],
            "practice_areas": ["Commercial Litigation"],
            "panel_status": "preferred",
        },
    ).json()
    weak_counsel = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(token),
        json={
            "name": "Sierra Arbitration Co.",
            "jurisdictions": ["SIAC"],
            "practice_areas": ["Arbitration"],
            "panel_status": "inactive",
        },
    ).json()

    strong_assignment_response = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(token),
        json={
            "matter_id": prior_matter["id"],
            "counsel_id": strong_counsel["id"],
            "role_summary": "Lead arguing counsel",
            "status": "active",
        },
    )
    assert strong_assignment_response.status_code == 200

    weak_assignment_response = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(token),
        json={
            "matter_id": unrelated_matter["id"],
            "counsel_id": weak_counsel["id"],
            "role_summary": "Arbitration-only counsel",
            "status": "active",
        },
    )
    assert weak_assignment_response.status_code == 200

    recommendation_response = client.post(
        "/api/outside-counsel/recommendations",
        headers=auth_headers(token),
        json={"matter_id": target_matter["id"], "limit": 5},
    )
    assert recommendation_response.status_code == 200
    payload = recommendation_response.json()

    assert payload["results"][0]["counsel_name"] == "Dua Litigation Office"
    assert any("Practice area match" in item for item in payload["results"][0]["evidence"])
    assert any(
        "prior matters in Delhi High Court" in item
        for item in payload["results"][0]["evidence"]
    )


def test_member_cannot_create_outside_counsel_profile(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])

    create_user = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Meera Member",
            "email": "meera@asterlegal.in",
            "password": "MeeraPass123!",
            "role": "member",
        },
    )
    assert create_user.status_code == 200

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "meera@asterlegal.in",
            "password": "MeeraPass123!",
            "company_slug": "aster-legal",
        },
    )
    member_token = str(login_response.json()["access_token"])

    response = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(member_token),
        json={"name": "Blocked Counsel"},
    )
    assert response.status_code == 403


def test_cross_tenant_counsel_profile_cannot_be_used(client: TestClient) -> None:
    first_company = bootstrap_company(client)
    first_token = str(first_company["access_token"])
    first_matter = _create_matter(
        client,
        first_token,
        title="First company matter",
        matter_code="DEL-2026-111",
    )

    second_company_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Beacon GC",
            "company_slug": "beacon-gc",
            "company_type": "corporate_legal",
            "owner_full_name": "Asha Rao",
            "owner_email": "asha@beacongc.in",
            "owner_password": "BeaconPass123!",
        },
    )
    assert second_company_response.status_code == 200
    second_token = str(second_company_response.json()["access_token"])

    second_counsel_response = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(second_token),
        json={"name": "Other Tenant Counsel"},
    )
    assert second_counsel_response.status_code == 200
    second_counsel_id = second_counsel_response.json()["id"]

    assignment_response = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(first_token),
        json={
            "matter_id": first_matter["id"],
            "counsel_id": second_counsel_id,
            "status": "approved",
        },
    )
    assert assignment_response.status_code == 404
