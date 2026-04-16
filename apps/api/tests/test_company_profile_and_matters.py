from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def test_owner_can_update_company_profile(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    response = client.patch(
        "/api/companies/current/profile",
        headers=auth_headers(token),
        json={
            "name": "Aster Legal India LLP",
            "primary_contact_email": "ops@asterlegal.in",
            "billing_contact_name": "Finance Desk",
            "billing_contact_email": "billing@asterlegal.in",
            "headquarters": "New Delhi",
            "timezone": "Asia/Calcutta",
            "website_url": "https://caseops.ai",
            "practice_summary": "Commercial disputes, appellate work, and high-stakes hearings.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Aster Legal India LLP"
    assert payload["billing_contact_email"] == "billing@asterlegal.in"
    assert payload["practice_summary"].startswith("Commercial disputes")


def test_authenticated_user_can_create_and_list_matters(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    create_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "State v. Rao - Bail Appeal",
            "matter_code": "BLR-2026-001",
            "client_name": "Rao Family Office",
            "opposing_party": "State of Karnataka",
            "status": "active",
            "practice_area": "Criminal",
            "forum_level": "high_court",
            "court_name": "Karnataka High Court",
            "judge_name": "Justice Sharma",
            "description": "Urgent appellate bail strategy and hearing prep.",
            "next_hearing_on": "2026-05-02",
        },
    )

    assert create_response.status_code == 200
    matter = create_response.json()
    assert matter["matter_code"] == "BLR-2026-001"
    assert matter["forum_level"] == "high_court"

    list_response = client.get("/api/matters/", headers=auth_headers(token))
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload["matters"]) == 1
    assert payload["matters"][0]["title"] == "State v. Rao - Bail Appeal"


def test_authenticated_user_can_update_a_matter(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    create_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Acme Contracts Arbitration",
            "matter_code": "ARB-2026-003",
            "client_name": "Acme Industries",
            "opposing_party": "Beta Projects",
            "status": "intake",
            "practice_area": "Arbitration",
            "forum_level": "arbitration",
            "description": "Initial claim drafting and hearing strategy.",
        },
    )
    matter_id = create_response.json()["id"]

    update_response = client.patch(
        f"/api/matters/{matter_id}",
        headers=auth_headers(token),
        json={
            "status": "active",
            "court_name": "SIAC",
            "judge_name": "Arbitral Tribunal",
        },
    )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["status"] == "active"
    assert payload["court_name"] == "SIAC"
    assert payload["judge_name"] == "Arbitral Tribunal"


def test_matter_workspace_includes_notes_hearings_activity_and_assignment(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])

    user_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Priya Associate",
            "email": "priya@asterlegal.in",
            "password": "AssociatePass123!",
            "role": "member",
        },
    )
    assignee_membership_id = user_response.json()["membership_id"]

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(owner_token),
        json={
            "title": "Regulatory writ petition",
            "matter_code": "WRIT-2026-010",
            "practice_area": "Regulatory",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    assign_response = client.patch(
        f"/api/matters/{matter_id}",
        headers=auth_headers(owner_token),
        json={"assignee_membership_id": assignee_membership_id},
    )
    assert assign_response.status_code == 200
    assert assign_response.json()["assignee_membership_id"] == assignee_membership_id

    note_response = client.post(
        f"/api/matters/{matter_id}/notes",
        headers=auth_headers(owner_token),
        json={"body": "Prepare chronology and bench brief before Friday."},
    )
    assert note_response.status_code == 200

    hearing_response = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=auth_headers(owner_token),
        json={
            "hearing_on": "2026-05-15",
            "forum_name": "Delhi High Court",
            "judge_name": "Justice Mehta",
            "purpose": "Admission and interim relief",
            "status": "scheduled",
        },
    )
    assert hearing_response.status_code == 200

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(owner_token),
    )

    assert workspace_response.status_code == 200
    payload = workspace_response.json()
    assert payload["matter"]["id"] == matter_id
    assert payload["assignee"]["membership_id"] == assignee_membership_id
    assert len(payload["notes"]) == 1
    assert payload["notes"][0]["author_name"] == "Sanjay Mishra"
    assert len(payload["hearings"]) == 1
    assert payload["hearings"][0]["forum_name"] == "Delhi High Court"
    assert len(payload["activity"]) >= 4


def test_matter_attachment_upload_and_download_are_available_in_workspace(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Commercial appeal bundle",
            "matter_code": "COMM-2026-101",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={
            "file": (
                "appeal-brief.txt",
                b"Detailed chronology and grounds for appeal.",
                "text/plain",
            )
        },
    )

    assert upload_response.status_code == 200
    attachment = upload_response.json()
    assert attachment["original_filename"] == "appeal-brief.txt"
    assert attachment["content_type"] == "text/plain"
    assert attachment["size_bytes"] > 0

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )

    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    assert len(workspace["attachments"]) == 1
    assert workspace["attachments"][0]["id"] == attachment["id"]
    assert any(event["event_type"] == "attachment_added" for event in workspace["activity"])

    download_response = client.get(
        f"/api/matters/{matter_id}/attachments/{attachment['id']}/download",
        headers=auth_headers(token),
    )

    assert download_response.status_code == 200
    assert download_response.content == b"Detailed chronology and grounds for appeal."


def test_cross_tenant_user_cannot_download_another_company_attachment(
    client: TestClient,
) -> None:
    first_company = bootstrap_company(client)
    first_token = str(first_company["access_token"])

    first_matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(first_token),
        json={
            "title": "Restricted evidence bundle",
            "matter_code": "SEC-2026-404",
            "practice_area": "Investigations",
            "forum_level": "lower_court",
            "status": "active",
        },
    )
    first_matter_id = first_matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{first_matter_id}/attachments",
        headers=auth_headers(first_token),
        files={"file": ("sealed-note.txt", b"Confidential exhibit", "text/plain")},
    )
    attachment_id = upload_response.json()["id"]

    second_company_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Tenant Legal",
            "company_slug": "second-tenant-legal",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondtenant.in",
            "owner_password": "SecondOwner123!",
        },
    )
    second_token = str(second_company_response.json()["access_token"])

    forbidden_download = client.get(
        f"/api/matters/{first_matter_id}/attachments/{attachment_id}/download",
        headers=auth_headers(second_token),
    )

    assert forbidden_download.status_code == 404


def test_empty_attachment_upload_is_rejected(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Drafting workspace",
            "matter_code": "DRFT-2026-018",
            "practice_area": "Advisory",
            "forum_level": "advisory",
            "status": "intake",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert upload_response.status_code == 400
    assert upload_response.json()["detail"] == "Attachment upload cannot be empty."


def test_time_entry_and_invoice_show_up_in_matter_workspace(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "High-value arbitration",
            "matter_code": "ARB-2026-120",
            "client_name": "Acme Holdings",
            "practice_area": "Arbitration",
            "forum_level": "arbitration",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    time_entry_response = client.post(
        f"/api/matters/{matter_id}/time-entries",
        headers=auth_headers(token),
        json={
            "work_date": "2026-04-16",
            "description": "Prepared claim strategy and first hearing brief.",
            "duration_minutes": 90,
            "billable": True,
            "rate_currency": "INR",
            "rate_amount_minor": 120000,
        },
    )

    assert time_entry_response.status_code == 200
    time_entry = time_entry_response.json()
    assert time_entry["total_amount_minor"] == 180000
    assert time_entry["is_invoiced"] is False

    invoice_response = client.post(
        f"/api/matters/{matter_id}/invoices",
        headers=auth_headers(token),
        json={
            "invoice_number": "INV-2026-001",
            "issued_on": "2026-04-16",
            "due_on": "2026-04-30",
            "tax_amount_minor": 18000,
            "notes": "Initial strategy and hearing preparation.",
            "include_uninvoiced_time_entries": True,
            "manual_items": [
                {
                    "description": "Court clerk filing coordination",
                    "amount_minor": 15000,
                }
            ],
        },
    )

    assert invoice_response.status_code == 200
    invoice = invoice_response.json()
    assert invoice["invoice_number"] == "INV-2026-001"
    assert invoice["subtotal_amount_minor"] == 195000
    assert invoice["total_amount_minor"] == 213000
    assert len(invoice["line_items"]) == 2

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )

    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    assert len(workspace["time_entries"]) == 1
    assert workspace["time_entries"][0]["is_invoiced"] is True
    assert len(workspace["invoices"]) == 1
    assert workspace["invoices"][0]["invoice_number"] == "INV-2026-001"
    assert any(event["event_type"] == "time_entry_added" for event in workspace["activity"])
    assert any(event["event_type"] == "invoice_created" for event in workspace["activity"])


def test_member_cannot_create_invoice(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])

    create_user_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Riya Member",
            "email": "riya@asterlegal.in",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert create_user_response.status_code == 200

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "riya@asterlegal.in",
            "password": "MemberPass123!",
            "company_slug": "aster-legal",
        },
    )
    member_token = str(login_response.json()["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(owner_token),
        json={
            "title": "Compliance advice",
            "matter_code": "ADV-2026-020",
            "practice_area": "Compliance",
            "forum_level": "advisory",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    response = client.post(
        f"/api/matters/{matter_id}/invoices",
        headers=auth_headers(member_token),
        json={
            "invoice_number": "INV-2026-002",
            "issued_on": "2026-04-16",
            "include_uninvoiced_time_entries": False,
            "manual_items": [{"description": "Advice note", "amount_minor": 50000}],
        },
    )

    assert response.status_code == 403


def test_owner_can_create_and_sync_pine_labs_payment_link(
    client: TestClient,
    monkeypatch,
) -> None:
    from caseops_api.services.pine_labs import (
        PineLabsCreatePaymentLinkResult,
        PineLabsPaymentStatusResult,
    )

    class FakeGateway:
        def create_payment_link(self, **kwargs):
            return PineLabsCreatePaymentLinkResult(
                provider_order_id="pl-order-001",
                payment_url="https://pay.pinelabs.test/pl-order-001",
                provider_reference="plink-ref-001",
                status="created",
                raw_payload={
                    "order_id": "pl-order-001",
                    "payment_url": "https://pay.pinelabs.test/pl-order-001",
                    "status": "created",
                },
            )

        def fetch_payment_status(self, **kwargs):
            return PineLabsPaymentStatusResult(
                provider_order_id="pl-order-001",
                provider_reference="plink-ref-001",
                status="paid",
                amount_received_minor=236000,
                raw_payload={
                    "order_id": "pl-order-001",
                    "status": "paid",
                    "amount_received_minor": 236000,
                },
            )

    monkeypatch.setattr("caseops_api.services.payments._get_gateway_client", lambda: FakeGateway())

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Appellate commercial dispute",
            "matter_code": "COMM-2026-210",
            "client_name": "Northstar Industries",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    client.post(
        f"/api/matters/{matter_id}/time-entries",
        headers=auth_headers(token),
        json={
            "work_date": "2026-04-16",
            "description": "Prepared appeal draft and interim relief note.",
            "duration_minutes": 120,
            "billable": True,
            "rate_currency": "INR",
            "rate_amount_minor": 100000,
        },
    )

    invoice_response = client.post(
        f"/api/matters/{matter_id}/invoices",
        headers=auth_headers(token),
        json={
            "invoice_number": "INV-2026-PL-001",
            "issued_on": "2026-04-16",
            "tax_amount_minor": 36000,
            "include_uninvoiced_time_entries": True,
        },
    )
    invoice_id = invoice_response.json()["id"]

    payment_link_response = client.post(
        f"/api/payments/matters/{matter_id}/invoices/{invoice_id}/pine-labs/link",
        headers=auth_headers(token),
        json={
            "customer_name": "Northstar Industries",
            "customer_email": "finance@northstar.in",
            "customer_phone": "9876543210",
        },
    )

    assert payment_link_response.status_code == 200
    payment_attempt = payment_link_response.json()
    assert payment_attempt["provider_order_id"] == "pl-order-001"
    assert payment_attempt["payment_url"] == "https://pay.pinelabs.test/pl-order-001"

    sync_response = client.post(
        f"/api/payments/matters/{matter_id}/invoices/{invoice_id}/pine-labs/sync",
        headers=auth_headers(token),
    )

    assert sync_response.status_code == 200
    assert sync_response.json()["status"] == "paid"

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    invoice = workspace_response.json()["invoices"][0]
    assert invoice["status"] == "paid"
    assert invoice["balance_due_minor"] == 0
    assert len(invoice["payment_attempts"]) == 1


def test_pine_labs_webhook_updates_invoice_status(
    client: TestClient,
    monkeypatch,
) -> None:
    from caseops_api.services.pine_labs import PineLabsCreatePaymentLinkResult

    class FakeGateway:
        def create_payment_link(self, **kwargs):
            return PineLabsCreatePaymentLinkResult(
                provider_order_id="pl-order-webhook",
                payment_url="https://pay.pinelabs.test/pl-order-webhook",
                provider_reference="plink-ref-webhook",
                status="created",
                raw_payload={
                    "order_id": "pl-order-webhook",
                    "payment_url": "https://pay.pinelabs.test/pl-order-webhook",
                    "status": "created",
                },
            )

        def parse_webhook_payload(self, payload):
            from caseops_api.services.pine_labs import PineLabsPaymentStatusResult

            return PineLabsPaymentStatusResult(
                provider_order_id=str(payload["order_id"]),
                provider_reference="plink-ref-webhook",
                status=str(payload["status"]),
                amount_received_minor=int(payload["amount_received_minor"]),
                raw_payload=dict(payload),
            )

    monkeypatch.setattr("caseops_api.services.payments._get_gateway_client", lambda: FakeGateway())

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Consumer dispute settlement",
            "matter_code": "CONS-2026-030",
            "practice_area": "Consumer",
            "forum_level": "tribunal",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    invoice_response = client.post(
        f"/api/matters/{matter_id}/invoices",
        headers=auth_headers(token),
        json={
            "invoice_number": "INV-2026-PL-002",
            "issued_on": "2026-04-16",
            "include_uninvoiced_time_entries": False,
            "manual_items": [{"description": "Settlement memo", "amount_minor": 75000}],
        },
    )
    invoice_id = invoice_response.json()["id"]

    client.post(
        f"/api/payments/matters/{matter_id}/invoices/{invoice_id}/pine-labs/link",
        headers=auth_headers(token),
        json={"customer_name": "Consumer team"},
    )

    webhook_payload = {
        "order_id": "pl-order-webhook",
        "status": "paid",
        "amount_received_minor": 75000,
        "event_type": "payment_success",
    }
    webhook_body = json.dumps(webhook_payload).encode("utf-8")
    signature = hmac.new(
        b"pine-webhook-secret",
        webhook_body,
        hashlib.sha256,
    ).hexdigest()

    webhook_response = client.post(
        "/api/payments/pine-labs/webhook",
        content=webhook_body,
        headers={
            "Content-Type": "application/json",
            "X-PineLabs-Signature": signature,
        },
    )

    assert webhook_response.status_code == 200
    assert webhook_response.json()["accepted"] is True

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    invoice = workspace_response.json()["invoices"][0]
    assert invoice["status"] == "paid"
    assert invoice["amount_received_minor"] == 75000


def test_ai_matter_summary_brief_uses_workspace_data(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Regulatory enforcement response",
            "matter_code": "REG-2026-042",
            "client_name": "BluePeak Energy",
            "practice_area": "Regulatory",
            "forum_level": "high_court",
            "status": "active",
            "court_name": "Delhi High Court",
            "next_hearing_on": "2026-05-03",
        },
    )
    matter_id = matter_response.json()["id"]

    client.post(
        f"/api/matters/{matter_id}/notes",
        headers=auth_headers(token),
        json={
            "body": (
                "Need final chronology, regulator correspondence, and interim relief "
                "position."
            )
        },
    )
    client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("notice.txt", b"Regulatory notice and annexures", "text/plain")},
    )

    brief_response = client.post(
        f"/api/ai/matters/{matter_id}/briefs/generate",
        headers=auth_headers(token),
        json={"brief_type": "matter_summary", "focus": "Board update and litigation posture"},
    )

    assert brief_response.status_code == 200
    payload = brief_response.json()
    assert payload["brief_type"] == "matter_summary"
    assert payload["provider"] == "caseops-heuristic-v1"
    assert payload["headline"].startswith("Matter summary")
    assert any("BluePeak Energy" in item for item in payload["key_points"])
    assert any(
        "Board update and litigation posture" in item
        for item in payload["recommended_actions"]
    )


def test_ai_hearing_prep_brief_flags_missing_workspace_data(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Urgent bail appeal",
            "matter_code": "BAIL-2026-011",
            "practice_area": "Criminal",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    brief_response = client.post(
        f"/api/ai/matters/{matter_id}/briefs/generate",
        headers=auth_headers(token),
        json={"brief_type": "hearing_prep"},
    )

    assert brief_response.status_code == 200
    payload = brief_response.json()
    assert payload["brief_type"] == "hearing_prep"
    assert any("No assignee" in risk for risk in payload["risks"])
    assert any("No source documents" in risk for risk in payload["risks"])
