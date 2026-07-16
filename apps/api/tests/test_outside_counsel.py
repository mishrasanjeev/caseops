from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Matter, OutsideCounselSpendRecord
from caseops_api.db.session import get_session_factory
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
            "status": "intake",
            "practice_area": practice_area,
            "forum_level": forum_level,
            "court_name": court_name,
            "description": "Strategic litigation workflow.",
        },
    )
    assert response.status_code == 200
    return response.json()


def _invite_admin(client: TestClient, owner_token: str) -> tuple[str, str]:
    create_user = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Outside Counsel Admin",
            "email": "oc-admin@asterlegal.in",
            "password": "AdminPass123!",
            "role": "admin",
        },
    )
    assert create_user.status_code == 200, create_user.text
    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "oc-admin@asterlegal.in",
            "password": "AdminPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login_response.status_code == 200, login_response.text
    return str(create_user.json()["membership_id"]), str(
        login_response.json()["access_token"]
    )


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
    assert spend_record["payment_tracking_status"] == "unpaid"

    workspace_response = client.get(
        "/api/outside-counsel/workspace",
        headers=auth_headers(token),
    )
    assert workspace_response.status_code == 200
    payload = workspace_response.json()
    assert payload["summary"]["total_counsel_count"] == 1
    assert payload["summary"]["active_assignment_count"] == 1
    assert payload["summary"]["total_budget_minor"] == 500000
    assert payload["summary"]["total_agreed_minor"] == 500000
    assert payload["summary"]["total_spend_minor"] == 250000
    assert payload["summary"]["approved_spend_minor"] == 200000
    assert payload["summary"]["total_paid_minor"] == 0
    assert payload["summary"]["total_pending_minor"] == 250000
    assert payload["summary"]["multi_currency"] is False
    assert payload["summary"]["currency_codes"] == ["INR"]
    assert payload["summary"]["payment_status_counts"]["partially_approved"] == 1
    assert payload["profiles"][0]["name"] == "Khanna Advisory Chambers"
    assert payload["profiles"][0]["approved_spend_minor"] == 200000
    assert payload["assignments"][0]["matter_code"] == "COMM-2026-401"
    assert payload["assignments"][0]["fee_agreed_minor"] == 500000
    assert payload["spend_records"][0]["invoice_reference"] == "KAC/2026/044"
    assert payload["spend_records"][0]["pending_amount_minor"] == 250000
    assert payload["matter_summaries"][0]["matter_code"] == "COMM-2026-401"
    assert payload["matter_summaries"][0]["total_agreed_minor"] == 500000


def test_spend_record_update_tracks_paid_pending_and_redacts_audit(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    matter = _create_matter(
        client,
        token,
        title="Spend update matter",
        matter_code="OC-SPEND-2026-001",
    )
    counsel = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(token),
        json={"name": "Redacted Spend Chambers"},
    ).json()
    assignment = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "budget_amount_minor": 900000,
        },
    ).json()

    create_response = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "assignment_id": assignment["id"],
            "invoice_reference": "RSC-2026-009",
            "description": "Synthetic invoice narrative",
            "amount_minor": 300000,
            "notes": "Reviewer note example",
        },
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    assert created["paid_amount_minor"] == 0
    assert created["pending_amount_minor"] == 300000
    assert created["payment_tracking_status"] == "unpaid"

    update_response = client.patch(
        f"/api/outside-counsel/spend-records/{created['id']}",
        headers=auth_headers(token),
        json={
            "status": "paid",
            "paid_on": "2026-05-24",
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["payment_status"] == "paid"
    assert updated["payment_tracking_status"] == "paid"
    assert updated["paid_amount_minor"] == 300000
    assert updated["pending_amount_minor"] == 0

    workspace = client.get(
        "/api/outside-counsel/workspace",
        headers=auth_headers(token),
    ).json()
    assert workspace["summary"]["total_paid_minor"] == 300000
    assert workspace["summary"]["total_pending_minor"] == 0
    assert workspace["summary"]["payment_status_counts"]["paid"] == 1

    Session = get_session_factory()
    with Session() as session:
        rows = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.target_id == created["id"])
                .order_by(AuditEvent.created_at.asc())
            )
        )
    assert [row.action for row in rows] == [
        "outside_counsel.spend_recorded",
        "outside_counsel.spend_updated",
    ]
    for row in rows:
        metadata = json.loads(row.metadata_json or "{}")
        assert metadata["invoice_reference_present"] is True
        assert "description" not in metadata
        assert "notes" not in metadata
        assert "invoice_reference" not in metadata
        assert "Synthetic invoice narrative" not in row.metadata_json
        assert "RSC-2026-009" not in row.metadata_json
        assert "Reviewer note example" not in row.metadata_json


def test_disposed_matter_rejects_outside_counsel_spend_create_and_update(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    matter = _create_matter(
        client,
        token,
        title="Disposed spend matter",
        matter_code="OC-DISPOSED-2026-001",
    )
    counsel = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(token),
        json={"name": "Terminal Boundary Chambers"},
    ).json()
    assignment = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "budget_amount_minor": 400000,
        },
    ).json()
    created_response = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "assignment_id": assignment["id"],
            "description": "Pre-disposal fee",
            "amount_minor": 100000,
        },
    )
    assert created_response.status_code == 200, created_response.text
    spend_record_id = created_response.json()["id"]

    Session = get_session_factory()
    with Session() as session:
        matter_row = session.get(Matter, matter["id"])
        assert matter_row is not None
        matter_row.status = "disposed"
        matter_row.is_active = False
        session.commit()

    update_response = client.patch(
        f"/api/outside-counsel/spend-records/{spend_record_id}",
        headers=auth_headers(token),
        json={"description": "Must not replace closed-file spend"},
    )
    create_response = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "assignment_id": assignment["id"],
            "description": "Must not enter a closed file",
            "amount_minor": 50000,
        },
    )
    assert update_response.status_code == 409, update_response.text
    assert create_response.status_code == 409, create_response.text
    assert "disposed" in update_response.text.lower()
    assert "disposed" in create_response.text.lower()

    with Session() as session:
        records = list(
            session.scalars(
                select(OutsideCounselSpendRecord).where(
                    OutsideCounselSpendRecord.matter_id == matter["id"]
                )
            )
        )
        assert len(records) == 1
        assert records[0].description == "Pre-disposal fee"


def test_spend_payment_tracking_and_currency_rollup_are_explicit(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    matter = _create_matter(
        client,
        token,
        title="Multi currency spend matter",
        matter_code="OC-MULTI-2026-001",
    )
    counsel_inr = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(token),
        json={"name": "INR Counsel"},
    ).json()
    counsel_usd = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(token),
        json={"name": "USD Counsel"},
    ).json()
    assignment_inr = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel_inr["id"],
            "budget_amount_minor": 0,
            "currency": "INR",
        },
    ).json()
    assignment_usd = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel_usd["id"],
            "budget_amount_minor": 50000,
            "currency": "USD",
        },
    ).json()

    zero_paid = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel_inr["id"],
            "assignment_id": assignment_inr["id"],
            "description": "Zero adjustment",
            "currency": "INR",
            "amount_minor": 0,
            "approved_amount_minor": 0,
            "status": "paid",
        },
    )
    assert zero_paid.status_code == 200, zero_paid.text
    assert zero_paid.json()["payment_tracking_status"] == "paid"
    assert zero_paid.json()["pending_amount_minor"] == 0

    partial_paid = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel_usd["id"],
            "assignment_id": assignment_usd["id"],
            "description": "Partially settled invoice",
            "currency": "USD",
            "amount_minor": 300000,
            "approved_amount_minor": 100000,
            "status": "paid",
        },
    )
    assert partial_paid.status_code == 200, partial_paid.text
    partial_body = partial_paid.json()
    assert partial_body["payment_tracking_status"] == "partially_paid"
    assert partial_body["paid_amount_minor"] == 100000
    assert partial_body["pending_amount_minor"] == 200000

    invalid_overpaid = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel_usd["id"],
            "description": "Invalid overpayment",
            "currency": "USD",
            "amount_minor": 1000,
            "approved_amount_minor": 1001,
            "status": "paid",
        },
    )
    assert invalid_overpaid.status_code == 400

    workspace = client.get(
        "/api/outside-counsel/workspace",
        headers=auth_headers(token),
    )
    assert workspace.status_code == 200, workspace.text
    payload = workspace.json()
    assert payload["summary"]["multi_currency"] is True
    assert payload["summary"]["currency_codes"] == ["INR", "USD"]
    assert payload["matter_summaries"][0]["multi_currency"] is True
    assert payload["matter_summaries"][0]["currency_codes"] == ["INR", "USD"]


def test_spend_update_respects_restricted_wall_and_team_visibility(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])
    admin_membership_id, admin_token = _invite_admin(client, owner_token)
    matter = _create_matter(
        client,
        owner_token,
        title="Spend update access matter",
        matter_code="OC-ACCESS-2026-001",
    )
    counsel = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(owner_token),
        json={"name": "Access Counsel"},
    ).json()
    spend = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(owner_token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "description": "Restricted spend update",
            "amount_minor": 100000,
        },
    )
    assert spend.status_code == 200, spend.text
    restricted = client.post(
        f"/api/matters/{matter['id']}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    denied_restricted = client.patch(
        f"/api/outside-counsel/spend-records/{spend.json()['id']}",
        headers=auth_headers(admin_token),
        json={"status": "paid"},
    )
    assert denied_restricted.status_code == 404, denied_restricted.text

    grant = client.post(
        f"/api/matters/{matter['id']}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": admin_membership_id, "reason": "Review spend"},
    )
    assert grant.status_code == 200, grant.text
    wall = client.post(
        f"/api/matters/{matter['id']}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": admin_membership_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text
    denied_wall = client.patch(
        f"/api/outside-counsel/spend-records/{spend.json()['id']}",
        headers=auth_headers(admin_token),
        json={"status": "paid"},
    )
    assert denied_wall.status_code == 404, denied_wall.text

    team_matter = _create_matter(
        client,
        owner_token,
        title="Team scoped spend matter",
        matter_code="OC-TEAM-2026-001",
    )
    team_spend = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(owner_token),
        json={
            "matter_id": team_matter["id"],
            "counsel_id": counsel["id"],
            "description": "Team scoped spend update",
            "amount_minor": 100000,
        },
    )
    assert team_spend.status_code == 200, team_spend.text
    team = client.post(
        "/api/teams/",
        headers=auth_headers(owner_token),
        json={"name": "Outside Counsel Team", "slug": "oc-spend-team"},
    )
    assert team.status_code == 201, team.text
    assign_team = client.patch(
        f"/api/matters/{team_matter['id']}",
        headers=auth_headers(owner_token),
        json={
            "team_id": team.json()["id"],
            "expected_updated_at": team_matter["updated_at"],
        },
    )
    assert assign_team.status_code == 200, assign_team.text
    scope = client.put(
        "/api/teams/scoping",
        headers=auth_headers(owner_token),
        json={"enabled": True},
    )
    assert scope.status_code == 200, scope.text
    denied_team = client.patch(
        f"/api/outside-counsel/spend-records/{team_spend.json()['id']}",
        headers=auth_headers(admin_token),
        json={"status": "paid"},
    )
    assert denied_team.status_code == 404, denied_team.text


def test_workspace_hides_restricted_matter_spend_from_ungranted_member(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])
    matter = _create_matter(
        client,
        owner_token,
        title="Restricted spend matter",
        matter_code="OC-REST-2026-001",
    )
    restricted = client.post(
        f"/api/matters/{matter['id']}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    counsel = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(owner_token),
        json={"name": "Restricted Spend Counsel"},
    ).json()
    assignment = client.post(
        "/api/outside-counsel/assignments",
        headers=auth_headers(owner_token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "budget_amount_minor": 700000,
        },
    )
    assert assignment.status_code == 200, assignment.text
    spend = client.post(
        "/api/outside-counsel/spend-records",
        headers=auth_headers(owner_token),
        json={
            "matter_id": matter["id"],
            "counsel_id": counsel["id"],
            "description": "Restricted matter spend",
            "amount_minor": 150000,
        },
    )
    assert spend.status_code == 200, spend.text

    create_user = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Ungrant Member",
            "email": "ungrant@asterlegal.in",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert create_user.status_code == 200, create_user.text
    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "ungrant@asterlegal.in",
            "password": "MemberPass123!",
            "company_slug": "aster-legal",
        },
    )
    member_token = str(login_response.json()["access_token"])

    member_workspace = client.get(
        "/api/outside-counsel/workspace",
        headers=auth_headers(member_token),
    )
    assert member_workspace.status_code == 200, member_workspace.text
    body = member_workspace.json()
    assert body["assignments"] == []
    assert body["spend_records"] == []
    assert body["matter_summaries"] == []


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
