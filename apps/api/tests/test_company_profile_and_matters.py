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


def test_matter_tasks_can_be_created_and_updated(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])

    user_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Aditi Senior Associate",
            "email": "aditi@asterlegal.in",
            "password": "AssociatePass123!",
            "role": "member",
        },
    )
    assignee_membership_id = user_response.json()["membership_id"]

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(owner_token),
        json={
            "title": "Interim injunction bundle",
            "matter_code": "COMM-2026-404",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    create_task_response = client.post(
        f"/api/matters/{matter_id}/tasks",
        headers=auth_headers(owner_token),
        json={
            "title": "Prepare injunction authorities",
            "description": "Pull Delhi and Supreme Court authorities on bank guarantee restraint.",
            "owner_membership_id": assignee_membership_id,
            "due_on": "2026-05-10",
            "priority": "urgent",
        },
    )

    assert create_task_response.status_code == 200
    task = create_task_response.json()
    assert task["title"] == "Prepare injunction authorities"
    assert task["owner_membership_id"] == assignee_membership_id
    assert task["status"] == "todo"

    update_task_response = client.patch(
        f"/api/matters/{matter_id}/tasks/{task['id']}",
        headers=auth_headers(owner_token),
        json={"status": "completed"},
    )

    assert update_task_response.status_code == 200
    updated_task = update_task_response.json()
    assert updated_task["status"] == "completed"
    assert updated_task["completed_at"] is not None

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(owner_token),
    )

    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    assert len(workspace["tasks"]) == 1
    assert workspace["tasks"][0]["title"] == "Prepare injunction authorities"
    assert workspace["tasks"][0]["status"] == "completed"
    assert any(event["event_type"] == "task_added" for event in workspace["activity"])
    assert any(event["event_type"] == "task_updated" for event in workspace["activity"])


def test_owner_can_import_court_sync_into_matter_workspace(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Commercial division appeal",
            "matter_code": "COMM-2026-220",
            "client_name": "North Arc Projects",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    sync_response = client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=auth_headers(token),
        json={
            "source": "eCourts",
            "summary": "Imported the latest listing and interim order from the court record.",
            "cause_list_entries": [
                {
                    "listing_date": "2026-05-09",
                    "forum_name": "Delhi High Court",
                    "bench_name": "Justice Mehta",
                    "courtroom": "Court 32",
                    "item_number": "18",
                    "stage": "Admission",
                    "notes": "Short pass-over likely after first call.",
                    "source_reference": "cause-list-2026-05-09.pdf",
                }
            ],
            "orders": [
                {
                    "order_date": "2026-04-16",
                    "title": "Interim protection order",
                    "summary": "Status quo to continue until the next date of hearing.",
                    "order_text": "Status quo will continue till the next date.",
                    "source_reference": "order-2026-04-16.pdf",
                }
            ],
        },
    )

    assert sync_response.status_code == 200
    sync_run = sync_response.json()
    assert sync_run["status"] == "completed"
    assert sync_run["source"] == "eCourts"
    assert sync_run["imported_cause_list_count"] == 1
    assert sync_run["imported_order_count"] == 1
    assert sync_run["triggered_by_name"] == "Sanjay Mishra"

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )

    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    assert workspace["matter"]["next_hearing_on"] == "2026-05-09"
    assert workspace["matter"]["court_name"] == "Delhi High Court"
    assert workspace["matter"]["judge_name"] == "Justice Mehta"
    assert len(workspace["court_sync_runs"]) == 1
    assert len(workspace["cause_list_entries"]) == 1
    assert len(workspace["court_orders"]) == 1
    assert workspace["cause_list_entries"][0]["item_number"] == "18"
    assert workspace["court_orders"][0]["title"] == "Interim protection order"
    assert any(event["event_type"] == "court_sync_imported" for event in workspace["activity"])


def test_empty_court_sync_import_is_rejected(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Unlisted advisory matter",
            "matter_code": "ADV-2026-077",
            "practice_area": "Advisory",
            "forum_level": "advisory",
            "status": "intake",
        },
    )
    matter_id = matter_response.json()["id"]

    sync_response = client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=auth_headers(token),
        json={
            "source": "Manual update",
            "summary": "No court data attached yet.",
            "cause_list_entries": [],
            "orders": [],
        },
    )

    assert sync_response.status_code == 400
    assert (
        sync_response.json()["detail"]
        == "Provide at least one cause list entry or court order to import."
    )


def test_owner_can_queue_live_court_sync_pull(client: TestClient, monkeypatch) -> None:
    def fake_fetch_text(url: str) -> tuple[str, str]:
        if "cause-lists/cause-list" in url:
            return (
                """
                <html>
                  <body>
                    <div>1 ADVANCE CAUSE LIST 17-04-2026</div>
                    <a href="/files/2026-04/cause-list/advance.pdf">Download</a>
                  </body>
                </html>
                """,
                url,
            )
        return (
            """
            <html>
              <body>
                <a href="/judgments/latest-judgment.pdf">
                  North Arc Projects vs State Judgment date 16.04.2026
                </a>
              </body>
            </html>
            """,
            url,
        )

    monkeypatch.setattr("caseops_api.services.court_sync_sources._fetch_text", fake_fetch_text)
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_bytes",
        lambda url: (
            b"%PDF fake bytes",
            "https://delhihighcourt.nic.in/files/2026-04/cause-list/advance.pdf",
        ),
    )
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._extract_pdf_text_from_bytes",
        lambda data: (
            "North Arc Projects vs State before Justice Mehta in Court No. 32 "
            "Item 18 on 2026-04-17."
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "North Arc Projects vs State",
            "matter_code": "COMM-2026-221",
            "client_name": "North Arc Projects",
            "opposing_party": "State",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
            "court_name": "Delhi High Court",
            "judge_name": "Justice Mehta",
        },
    )
    matter_id = matter_response.json()["id"]

    pull_response = client.post(
        f"/api/matters/{matter_id}/court-sync/pull",
        headers=auth_headers(token),
        json={
            "source": "delhi_high_court_live",
            "source_reference": "North Arc Projects",
        },
    )

    assert pull_response.status_code == 200
    job = pull_response.json()
    assert job["source"] == "delhi_high_court_live"
    assert job["status"] in {"queued", "completed"}

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    workspace = workspace_response.json()
    assert workspace["court_sync_jobs"]
    latest_job = workspace["court_sync_jobs"][0]
    assert latest_job["source"] == "delhi_high_court_live"
    assert latest_job["status"] == "completed"
    assert latest_job["adapter_name"] == "caseops-delhi-high-court-live-v2"
    assert workspace["cause_list_entries"][0]["source"] == "delhi_high_court_live"
    assert workspace["cause_list_entries"][0]["bench_name"] == "Justice Mehta"
    assert workspace["cause_list_entries"][0]["courtroom"] == "Court 32"
    assert workspace["cause_list_entries"][0]["item_number"] == "18"
    assert any("North Arc Projects" in item["notes"] for item in workspace["cause_list_entries"])


def test_owner_can_pull_bombay_high_court_live_orders(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_text",
        lambda url: (
            """
            <html>
              <body>
                <a href="generatenewauth.php?bhcpar=12345/2026">COMAPL/123/2026</a>
                BOMBAY Acme Industries Ltd Vs Beta Projects Pvt Ltd
                HON'BLE JUSTICE DESHMUKH 16/04/2026 [O]
              </body>
            </html>
            """,
            url,
        ),
    )
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_bytes",
        lambda url: (
            b"%PDF fake bytes",
            "https://www.bombayhighcourt.nic.in/generatenewauth.php?bhcpar=12345/2026",
        ),
    )
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._extract_pdf_text_from_bytes",
        lambda data: (
            "COMAPL/123/2026 Acme Industries Ltd vs Beta Projects Pvt Ltd "
            "before Justice Deshmukh. Interim protection continues till 30/04/2026."
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Acme Industries Ltd vs Beta Projects Pvt Ltd",
            "matter_code": "COMAPL/123/2026",
            "client_name": "Acme Industries Ltd",
            "opposing_party": "Beta Projects Pvt Ltd",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
            "court_name": "Bombay High Court",
            "judge_name": "Justice Deshmukh",
        },
    )
    matter_id = matter_response.json()["id"]

    pull_response = client.post(
        f"/api/matters/{matter_id}/court-sync/pull",
        headers=auth_headers(token),
        json={
            "source": "bombay_high_court_live",
            "source_reference": "COMAPL 123 OF 2026",
        },
    )

    assert pull_response.status_code == 200
    job = pull_response.json()
    assert job["source"] == "bombay_high_court_live"
    assert job["status"] in {"queued", "completed"}

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )

    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    assert workspace["court_sync_jobs"]
    latest_job = workspace["court_sync_jobs"][0]
    assert latest_job["source"] == "bombay_high_court_live"
    assert latest_job["status"] == "completed"
    assert latest_job["adapter_name"] == "caseops-bombay-high-court-live-v1"
    assert workspace["cause_list_entries"] == []
    assert workspace["court_orders"][0]["source"] == "bombay_high_court_live"
    assert workspace["court_orders"][0]["title"].startswith("Bombay High Court order")
    assert "Justice Deshmukh" in workspace["court_orders"][0]["summary"]
    assert workspace["court_orders"][0]["order_date"] == "2026-04-16"


def test_owner_can_pull_hyderabad_high_court_live_cause_list(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_text",
        lambda url: (
            """
            <html>
              <body>
                <h4>CAUSE LIST UPLOADING STATUS DATED: <span>17-04-2026</span></h4>
                <table>
                  <tbody>
                    <tr>
                      <td>1</td>
                      <td>11</td>
                      <td>DB-I</td>
                      <td>D</td>
                      <td>UPLOADED</td>
                      <td>16-04-2026 18:55</td>
                      <td><a target="_blank" href="https://tshc.gov.in/documents/NORMAL_COURT11.pdf">View</a></td>
                    </tr>
                  </tbody>
                </table>
              </body>
            </html>
            """,
            url,
        ),
    )
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_bytes",
        lambda url: (
            b"%PDF fake bytes",
            "https://tshc.gov.in/documents/NORMAL_COURT11.pdf",
        ),
    )
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._extract_pdf_text_from_bytes",
        lambda data: (
            "North Arc Projects versus State listed before Justice Rao in Court 11 "
            "Item 7 on 17-04-2026."
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "North Arc Projects versus State",
            "matter_code": "WRIT/220/2026",
            "client_name": "North Arc Projects",
            "opposing_party": "State",
            "practice_area": "Writ",
            "forum_level": "high_court",
            "status": "active",
            "court_name": "High Court for the State of Telangana",
            "judge_name": "Justice Rao",
        },
    )
    matter_id = matter_response.json()["id"]

    pull_response = client.post(
        f"/api/matters/{matter_id}/court-sync/pull",
        headers=auth_headers(token),
        json={
            "source": "hyderabad_high_court_live",
            "source_reference": "North Arc Projects",
        },
    )

    assert pull_response.status_code == 200

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    workspace = workspace_response.json()
    latest_job = workspace["court_sync_jobs"][0]
    assert latest_job["source"] == "hyderabad_high_court_live"
    assert latest_job["status"] == "completed"
    assert latest_job["adapter_name"] == "caseops-hyderabad-high-court-live-v1"
    assert workspace["cause_list_entries"][0]["source"] == "hyderabad_high_court_live"
    assert workspace["cause_list_entries"][0]["bench_name"] == "DB-I"
    assert workspace["cause_list_entries"][0]["courtroom"] == "Court 11"
    assert workspace["cause_list_entries"][0]["listing_date"] == "2026-04-17"


def test_owner_can_pull_karnataka_high_court_live_cause_list(
    client: TestClient,
    monkeypatch,
) -> None:
    def fake_fetch_text(url: str) -> tuple[str, str]:
        if url.endswith("causelistSearch.php"):
            return (
                """
                <html>
                  <body>
                    <input type="text" id="afromDt" value="17/04/2026" />
                  </body>
                </html>
                """,
                url,
            )
        if url.endswith("entire_causelist.php"):
            return (
                """
                <html>
                  <body>
                    <iframe src="pdfs/consolidatedCauselist/blrconsolidation.pdf"></iframe>
                    <iframe src="pdfs/consolidatedCauselist/dwdconsolidation.pdf"></iframe>
                    <iframe src="pdfs/consolidatedCauselist/klbconsolidation.pdf"></iframe>
                  </body>
                </html>
                """,
                url,
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_text",
        fake_fetch_text,
    )
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_bytes",
        lambda url: (b"%PDF fake bytes", url),
    )
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._extract_pdf_text_from_bytes",
        lambda data: (
            "WRIT/220/2026 North Arc Projects versus State listed in Bengaluru Bench "
            "Court No. 12 Item 5 on 17/04/2026."
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "North Arc Projects versus State",
            "matter_code": "WRIT/220/2026",
            "client_name": "North Arc Projects",
            "opposing_party": "State",
            "practice_area": "Writ",
            "forum_level": "high_court",
            "status": "active",
            "court_name": "Karnataka High Court",
        },
    )
    matter_id = matter_response.json()["id"]

    pull_response = client.post(
        f"/api/matters/{matter_id}/court-sync/pull",
        headers=auth_headers(token),
        json={
            "source": "karnataka_high_court_live",
            "source_reference": "WRIT 220 OF 2026",
        },
    )

    assert pull_response.status_code == 200

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    workspace = workspace_response.json()
    latest_job = workspace["court_sync_jobs"][0]
    assert latest_job["source"] == "karnataka_high_court_live"
    assert latest_job["status"] == "completed"
    assert latest_job["adapter_name"] == "caseops-karnataka-high-court-live-v1"
    assert workspace["cause_list_entries"][0]["source"] == "karnataka_high_court_live"
    assert workspace["cause_list_entries"][0]["bench_name"] == "Bengaluru Bench"
    assert workspace["cause_list_entries"][0]["courtroom"] == "Court 12"
    assert workspace["cause_list_entries"][0]["item_number"] == "5"
    assert workspace["cause_list_entries"][0]["listing_date"] == "2026-04-17"
    assert "captcha-gated" in workspace["cause_list_entries"][0]["notes"]


def test_owner_can_pull_chennai_high_court_public_orders(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_text",
        lambda url: (
            """
            <html>
              <body>
                <p class="post-item-title">
                  <a href="javascript:getpdf1(945);" rel="bookmark">
                    <img src="admin/images/pdf.png" />
                    Sitting Arrangements - Principal Seat at Madras - wef 02.03.2026 -
                    (405.68 KB) English
                  </a>
                </p>
                <p class="post-item-date">February 26, 2026</p>
              </body>
            </html>
            """,
            url,
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Principal Seat operational update",
            "matter_code": "OPS/55/2026",
            "client_name": "General Counsel Office",
            "practice_area": "General Litigation",
            "forum_level": "high_court",
            "status": "active",
            "court_name": "Madras High Court",
        },
    )
    matter_id = matter_response.json()["id"]

    pull_response = client.post(
        f"/api/matters/{matter_id}/court-sync/pull",
        headers=auth_headers(token),
        json={
            "source": "chennai_high_court_live",
            "source_reference": "Principal Seat",
        },
    )

    assert pull_response.status_code == 200

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    workspace = workspace_response.json()
    latest_job = workspace["court_sync_jobs"][0]
    assert latest_job["source"] == "chennai_high_court_live"
    assert latest_job["status"] == "completed"
    assert latest_job["adapter_name"] == "caseops-chennai-high-court-public-v1"
    assert workspace["court_orders"][0]["source"] == "chennai_high_court_live"
    assert workspace["court_orders"][0]["title"].startswith("Madras High Court public order")
    assert workspace["court_orders"][0]["order_date"] == "2026-02-26"
    assert "captcha-gated" in workspace["court_orders"][0]["summary"]


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
    assert attachment["processing_status"] == "pending"
    assert attachment["extracted_char_count"] == 0
    assert attachment["processed_at"] is None
    assert attachment["latest_job"]["action"] == "initial_index"
    assert attachment["latest_job"]["status"] == "queued"

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )

    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    assert len(workspace["attachments"]) == 1
    assert workspace["attachments"][0]["id"] == attachment["id"]
    assert workspace["attachments"][0]["processing_status"] == "indexed"
    assert workspace["attachments"][0]["latest_job"]["status"] == "completed"
    assert any(event["event_type"] == "attachment_added" for event in workspace["activity"])
    assert any(event["event_type"] == "attachment_processed" for event in workspace["activity"])

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


def test_pdf_attachment_is_marked_as_needing_ocr(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Scanned trial record",
            "matter_code": "SCAN-2026-019",
            "practice_area": "Litigation",
            "forum_level": "lower_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("scan.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
    )

    assert upload_response.status_code == 200
    attachment = upload_response.json()
    assert attachment["processing_status"] == "pending"
    assert attachment["extracted_char_count"] == 0
    assert attachment["latest_job"]["status"] == "queued"

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )

    assert workspace_response.status_code == 200
    workspace_attachment = workspace_response.json()["attachments"][0]
    assert workspace_attachment["processing_status"] == "needs_ocr"
    assert "OCR" in workspace_attachment["extraction_error"]
    assert workspace_attachment["latest_job"]["status"] == "failed"


def test_pdf_attachment_can_be_indexed_when_pdf_extractor_returns_text(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_pdf_text",
        lambda path: "Filed appeal on 2026-04-12 with listed hearing on 2026-05-03.",
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "PDF appeal bundle",
            "matter_code": "PDF-2026-021",
            "practice_area": "Appellate",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("appeal.pdf", b"%PDF fake bytes", "application/pdf")},
    )

    assert upload_response.status_code == 200
    attachment = upload_response.json()
    assert attachment["processing_status"] == "pending"
    assert attachment["latest_job"]["status"] == "queued"

    search_response = client.post(
        f"/api/ai/matters/{matter_id}/search",
        headers=auth_headers(token),
        json={"query": "appeal hearing", "limit": 3},
    )

    assert search_response.status_code == 200
    assert search_response.json()["results"]


def test_scanned_pdf_attachment_can_be_indexed_when_ocr_returns_text(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_pdf_text",
        lambda path: "",
    )
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_scanned_pdf_text",
        lambda path: (
            "Scanned hearing bundle includes witness statement and next hearing "
            "on 2026-05-18."
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Scanned hearing bundle",
            "matter_code": "SCAN-2026-022",
            "practice_area": "Litigation",
            "forum_level": "lower_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("scanned-bundle.pdf", b"%PDF scanned bytes", "application/pdf")},
    )

    assert upload_response.status_code == 200
    attachment = upload_response.json()
    assert attachment["processing_status"] == "pending"
    assert attachment["latest_job"]["status"] == "queued"

    search_response = client.post(
        f"/api/ai/matters/{matter_id}/search",
        headers=auth_headers(token),
        json={"query": "witness hearing", "limit": 3},
    )

    assert search_response.status_code == 200
    assert search_response.json()["results"]


def test_owner_can_retry_matter_attachment_processing_when_ocr_becomes_available(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_pdf_text",
        lambda path: "",
    )
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_scanned_pdf_text",
        lambda path: "",
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Retry OCR hearing record",
            "matter_code": "SCAN-2026-023",
            "practice_area": "Litigation",
            "forum_level": "lower_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("retry-scan.pdf", b"%PDF scanned bytes", "application/pdf")},
    )
    attachment_id = upload_response.json()["id"]

    first_workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    first_attachment = first_workspace_response.json()["attachments"][0]
    assert first_attachment["processing_status"] == "needs_ocr"
    assert first_attachment["latest_job"]["status"] == "failed"

    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_scanned_pdf_text",
        lambda path: "OCR recovery produced a witness note and hearing listed for 2026-05-21.",
    )

    retry_response = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/retry",
        headers=auth_headers(token),
    )

    assert retry_response.status_code == 200
    retry_attachment = retry_response.json()
    assert retry_attachment["latest_job"]["action"] == "retry"
    assert retry_attachment["latest_job"]["status"] == "queued"

    final_workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    final_attachment = final_workspace_response.json()["attachments"][0]
    assert final_attachment["processing_status"] == "indexed"
    assert final_attachment["latest_job"]["status"] == "completed"


def test_member_cannot_reindex_matter_attachment(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])

    create_user_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Case Member",
            "email": "member@asterlegal.in",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert create_user_response.status_code == 200

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "member@asterlegal.in",
            "password": "MemberPass123!",
            "company_slug": "aster-legal",
        },
    )
    member_token = str(login_response.json()["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(owner_token),
        json={
            "title": "Protected reindex matter",
            "matter_code": "SCAN-2026-024",
            "practice_area": "Advisory",
            "forum_level": "advisory",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(owner_token),
        files={"file": ("memo.txt", b"Initial indexing text", "text/plain")},
    )
    attachment_id = upload_response.json()["id"]

    response = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/reindex",
        headers=auth_headers(member_token),
    )

    assert response.status_code == 403


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
    client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=auth_headers(token),
        json={
            "source": "eCourts",
            "cause_list_entries": [
                {
                    "listing_date": "2026-05-03",
                    "forum_name": "Delhi High Court",
                    "bench_name": "Justice Rao",
                    "stage": "Interim relief",
                }
            ],
            "orders": [
                {
                    "order_date": "2026-04-16",
                    "title": "Interim protection order",
                    "summary": "No coercive steps until the next hearing date.",
                }
            ],
        },
    )

    brief_response = client.post(
        f"/api/ai/matters/{matter_id}/briefs/generate",
        headers=auth_headers(token),
        json={"brief_type": "matter_summary", "focus": "Board update and litigation posture"},
    )

    assert brief_response.status_code == 200
    payload = brief_response.json()
    assert payload["brief_type"] == "matter_summary"
    assert payload["provider"] == "caseops-briefing-court-sync-v4"
    assert payload["headline"].startswith("Matter summary")
    assert any("Interim protection order" in item for item in payload["authority_highlights"])
    assert any("BluePeak Energy" in item for item in payload["key_points"])
    assert any("Interim protection order" in item for item in payload["upcoming_items"])
    assert any("Delhi High Court" in item for item in payload["court_posture"])
    assert any("Cause list source" in item for item in payload["source_provenance"])
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
    assert any("No synced court order" in risk for risk in payload["risks"])
    assert any("No synced cause list" in risk for risk in payload["risks"])
    assert any("No authority-grade" in risk for risk in payload["risks"])


def test_owner_can_pull_central_delhi_district_court_public_service_status(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_text",
        lambda url: (
            """
            <html>
              <head>
                <title>Cause List / Daily Board | Central District Court, Delhi | India</title>
              </head>
              <body>
                <input value="2" type="radio" class="causeType" id="chkCauseTypeCivil" />
                <input value="3" type="radio" class="causeType" id="chkCauseTypeCriminal" />
                <script src="https://centraldelhi.dcourts.gov.in/wp-content/plugins/ecourt/services/cause-list/api.js"></script>
                <div id="siwp_captcha_container_0"></div>
                <input type="hidden" name="es_ajax_request" value="1" />
                <p>Last Updated: <strong>Apr 16, 2026</strong></p>
              </body>
            </html>
            """,
            url,
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "District-court operational monitoring",
            "matter_code": "DIST-OPS-001",
            "client_name": "BluePeak Energy",
            "practice_area": "Litigation Operations",
            "forum_level": "lower_court",
            "status": "active",
            "court_name": "Central District Court, Delhi",
        },
    )
    matter_id = matter_response.json()["id"]

    pull_response = client.post(
        f"/api/matters/{matter_id}/court-sync/pull",
        headers=auth_headers(token),
        json={
            "source": "central_delhi_district_court_public",
            "source_reference": "cause list daily board",
        },
    )

    assert pull_response.status_code == 200

    workspace_response = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=auth_headers(token),
    )
    workspace = workspace_response.json()
    latest_job = workspace["court_sync_jobs"][0]
    assert latest_job["source"] == "central_delhi_district_court_public"
    assert latest_job["status"] == "completed"
    assert latest_job["adapter_name"] == "caseops-central-delhi-district-court-public-v1"
    assert workspace["court_orders"][0]["source"] == "central_delhi_district_court_public"
    assert workspace["court_orders"][0]["order_date"] == "2026-04-16"
    assert "captcha-gated" in workspace["court_orders"][0]["summary"]


def test_ai_matter_document_review_uses_uploaded_attachment_text(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Commercial recovery appeal",
            "matter_code": "REC-2026-052",
            "client_name": "Northwind Capital",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={
            "file": (
                "recovery-appeal.txt",
                (
                    b"Appeal petition filed on 2026-04-10. Demand notice dated 2026-03-21 "
                    b"was served before filing. Interim hearing listed for 2026-05-04."
                ),
                "text/plain",
            )
        },
    )

    review_response = client.post(
        f"/api/ai/matters/{matter_id}/documents/review",
        headers=auth_headers(token),
        json={"review_type": "workspace_review", "focus": "Chronology and filing posture"},
    )

    assert review_response.status_code == 200
    payload = review_response.json()
    assert payload["provider"] == "caseops-matter-review-retrieval-v1"
    assert payload["headline"].startswith("Document review")
    assert "recovery-appeal.txt" in payload["source_attachments"]
    assert any("2026-04-10" in item for item in payload["chronology"])
    assert any("Chronology and filing posture" in item for item in payload["recommended_actions"])


def test_ai_matter_search_returns_ranked_snippets_from_uploaded_documents(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Writ challenge on regulatory inspection",
            "matter_code": "WRIT-2026-061",
            "practice_area": "Regulatory",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={
            "file": (
                "inspection-note.txt",
                (
                    b"Petition challenges the inspection notice issued by the regulator. "
                    b"The inspection team recorded a hearing note about sealing risks and "
                    b"compliance follow-up."
                ),
                "text/plain",
            )
        },
    )
    client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={
            "file": (
                "board-update.txt",
                b"Board update focused on finance exposure only.",
                "text/plain",
            )
        },
    )

    search_response = client.post(
        f"/api/ai/matters/{matter_id}/search",
        headers=auth_headers(token),
        json={"query": "appeal hearing", "limit": 3},
    )

    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["provider"] == "caseops-matter-search-retrieval-v1"
    assert payload["query"] == "appeal hearing"
    assert payload["results"]
    top_result = payload["results"][0]
    assert top_result["attachment_name"] == "inspection-note.txt"
    assert any(term in top_result["snippet"].lower() for term in ["hearing", "petition"])
    assert any(term in top_result["matched_terms"] for term in ["petition", "challenge"])
