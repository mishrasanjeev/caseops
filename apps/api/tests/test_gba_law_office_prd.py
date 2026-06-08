from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    Matter,
    MatterComplianceItem,
    MatterInvoiceExport,
    MatterTask,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import poll_tracked_cases
from caseops_api.services.next_hearing import apply_next_hearing_update
from tests.test_auth_company import auth_headers
from tests.test_case_tracking import FakeCaseTrackingProvider


def _bootstrap(client: TestClient, *, slug_seed: str = "gba") -> dict[str, object]:
    suffix = uuid4().hex[:8]
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"GBA {suffix} Law Office",
            "company_slug": f"{slug_seed}-{suffix}",
            "company_type": "law_firm",
            "owner_full_name": "GBA Owner",
            "owner_email": f"owner-{suffix}@gba.example",
            "owner_password": "GbaOwnerPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_matter(
    client: TestClient,
    token: str,
    code: str,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": f"GBA PRD matter {code}",
        "matter_code": code,
        "client_name": "GBA Client Pvt Ltd",
        "opposing_party": "Respondent Ltd",
        "practice_area": "Commercial",
        "forum_level": "high_court",
        "court_name": "Delhi High Court",
        "status": "intake",
    }
    payload.update(overrides)
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_bookmark(client: TestClient, token: str, cnr: str) -> dict[str, object]:
    response = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(token),
        json={
            "provider": "ecourtsindia",
            "cnr_number": cnr,
            "case_number": f"WP(C) {cnr[-4:]}/2026",
            "court_code": "DLHC",
            "court_name": "Delhi High Court",
            "case_title": f"Petitioner {cnr[-4:]} v Respondent",
            "notification_enabled": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_matter_status_closed_input_normalizes_to_disposed(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="gba-status")
    token = str(boot["access_token"])

    matter = _create_matter(client, token, "GBA-STATUS", status="closed")

    assert matter["status"] == "disposed"
    listed = client.get(
        "/api/matters/?status=closed",
        headers=auth_headers(token),
    )
    assert listed.status_code == 200, listed.text
    assert [row["status"] for row in listed.json()["matters"]] == ["disposed"]


def test_case_tracking_window_disabled_and_backlog_paths(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = _bootstrap(client, slug_seed="gba-track")
    token = str(boot["access_token"])
    _create_bookmark(client, token, "DLHC010012342026")

    with get_session_factory()() as session:
        disabled_runs = poll_tracked_cases(session)
    assert disabled_runs[0].status == "skipped"
    assert disabled_runs[0].skipped_count == 1
    assert disabled_runs[0].provider_call_count == 0

    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    get_settings.cache_clear()
    provider = FakeCaseTrackingProvider()
    with get_session_factory()() as session:
        blocked_runs = poll_tracked_cases(
            session,
            provider=provider,
            enforce_window=True,
            now=datetime(2026, 6, 6, 9, 0, tzinfo=UTC),
        )
    assert blocked_runs[0].status == "blocked"
    assert blocked_runs[0].blocked_count == 1
    assert provider.bulk_refresh_calls == []

    _create_bookmark(client, token, "DLHC010099992026")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_POLL_LIMIT", "1")
    get_settings.cache_clear()
    provider = FakeCaseTrackingProvider()
    with get_session_factory()() as session:
        partial_runs = poll_tracked_cases(session, provider=provider, force=True)
    assert partial_runs[0].status == "partial"
    assert partial_runs[0].backlog_remaining_count == 1
    assert partial_runs[0].provider_call_count == 1
    assert len(provider.bulk_refresh_calls[0]) == 1


def test_compliance_extraction_defaults_to_review_and_confirm_creates_work(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="gba-comp")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "GBA-COMP")

    order = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json={
            "order_date": "2026-06-06",
            "title": "Daily order",
            "summary": "Compliance direction recorded.",
            "source": "manual_upload",
            "order_text": (
                "The parties shall comply within two weeks from today. "
                "The matter shall be listed on the next date after compliance."
            ),
            "order_kind": "daily_order",
        },
    )
    assert order.status_code == 200, order.text
    order_body = order.json()

    compliance = client.get(
        f"/api/matters/{matter['id']}/compliance",
        headers=auth_headers(token),
    )
    assert compliance.status_code == 200, compliance.text
    payload = compliance.json()
    assert payload["runs"][0]["status"] == "completed"
    assert payload["items"]
    item = payload["items"][0]
    assert item["review_status"] == "review_required"
    assert item["due_on"] is None
    assert item["generated_task_id"] is None
    assert item["generated_deadline_id"] is None
    assert "within two weeks" in item["source_snippet"].lower()

    confirmed = client.patch(
        f"/api/matters/{matter['id']}/compliance/{item['id']}",
        headers=auth_headers(token),
        json={"action": "confirm"},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_item = next(row for row in confirmed.json()["items"] if row["id"] == item["id"])
    assert confirmed_item["review_status"] == "confirmed"
    assert confirmed_item["generated_task_id"]
    assert confirmed_item["generated_deadline_id"] is None

    retry = client.post(
        f"/api/matters/{matter['id']}/court-orders/{order_body['id']}/compliance/retry",
        headers=auth_headers(token),
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["run"]["trigger"] == "manual_retry"

    with get_session_factory()() as session:
        db_item = session.get(MatterComplianceItem, item["id"])
        assert db_item is not None
        assert db_item.generated_task_id is not None
        assert session.get(MatterTask, db_item.generated_task_id) is not None
        assert db_item.generated_deadline_id is None


def test_order_upload_records_pending_extraction_state(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="gba-upload")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "GBA-UPLOAD")

    upload = client.post(
        f"/api/matters/{matter['id']}/attachments",
        headers=auth_headers(token),
        data={"document_type": "order_judgment"},
        files={"file": ("order.pdf", b"%PDF-1.4\nfake order bytes\n%%EOF", "application/pdf")},
    )
    assert upload.status_code == 200, upload.text

    compliance = client.get(
        f"/api/matters/{matter['id']}/compliance",
        headers=auth_headers(token),
    )
    assert compliance.status_code == 200, compliance.text
    run = compliance.json()["runs"][0]
    assert run["attachment_id"] == upload.json()["id"]
    assert run["status"] == "skipped"
    assert run["skip_reason"] == "text_extraction_pending"


def test_matter_billing_rate_tax_tds_pdf_and_audit(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="gba-bill")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "GBA-BILL")

    profile = client.post(
        "/api/admin/matter-billing",
        headers=auth_headers(token),
        json={
            "name": "GBA Default",
            "is_default": True,
            "currency": "INR",
            "firm_legal_name": "GBA Law Office",
            "firm_address": "Mumbai, Maharashtra",
            "firm_gstin": "27ABCDE1234F1Z5",
            "firm_pan": "ABCDE1234F",
            "default_place_of_supply": "Maharashtra",
            "default_sac_hsn": "998212",
            "gst_applicable": True,
            "gstin_state_code": "27",
            "cgst_rate_bps": 900,
            "sgst_rate_bps": 900,
            "igst_rate_bps": 1800,
            "tax_rate_bps": 1800,
            "invoice_prefix": "GBA",
            "next_invoice_sequence": 1,
            "payment_terms_days": 15,
            "billing_mode": "hourly",
            "default_rate_minor_per_hour": 100000,
            "expense_categories": ["court_fee", "reimbursement"],
            "retainer_adjustments_enabled": True,
        },
    )
    assert profile.status_code == 200, profile.text
    profile_body = profile.json()

    preview = client.get(
        "/api/admin/matter-billing/invoice-number-preview",
        headers=auth_headers(token),
        params={"profile_id": profile_body["id"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["invoice_number"] == "GBA-0001"

    patched = client.patch(
        f"/api/admin/matter-billing/{profile_body['id']}",
        headers=auth_headers(token),
        json={"footer_text": "Subject to engagement letter terms."},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["footer_text"] == "Subject to engagement letter terms."

    time_entry = client.post(
        f"/api/matters/{matter['id']}/time-entries",
        headers=auth_headers(token),
        json={
            "work_date": "2026-06-06",
            "description": "Draft rejoinder",
            "duration_minutes": 60,
            "billable": True,
            "rate_currency": "INR",
        },
    )
    assert time_entry.status_code == 200, time_entry.text
    assert time_entry.json()["rate_amount_minor"] == 100000
    assert time_entry.json()["rate_source"] == "profile_default"

    invoice = client.post(
        f"/api/matters/{matter['id']}/invoices",
        headers=auth_headers(token),
        json={
            "issued_on": "2026-06-06",
            "client_name": "GBA Client Pvt Ltd",
            "client_billing_name": "GBA Client Pvt Ltd",
            "client_billing_address": "Mumbai",
            "client_gstin": "27ZZZZZ9999Z1Z5",
            "place_of_supply": "Maharashtra",
            "sac_hsn": "998212",
            "status": "issued",
            "include_uninvoiced_time_entries": True,
            "tds_deducted_minor": 10000,
            "payment_adjustment_minor": 5000,
        },
    )
    assert invoice.status_code == 200, invoice.text
    body = invoice.json()
    assert body["invoice_number"] == "GBA-0001"
    assert body["due_on"] == "2026-06-21"
    assert body["taxable_value_minor"] == 100000
    assert body["cgst_amount_minor"] == 9000
    assert body["sgst_amount_minor"] == 9000
    assert body["igst_amount_minor"] == 0
    assert body["total_amount_minor"] == 118000
    assert body["balance_due_minor"] == 103000
    assert body["tds_deducted_minor"] == 10000

    rate = client.post(
        f"/api/admin/matter-billing/{profile_body['id']}/rates",
        headers=auth_headers(token),
        json={
            "rate_scope": "practice_area",
            "practice_area": "Arbitration",
            "currency": "INR",
            "amount_minor_per_hour": 125000,
        },
    )
    assert rate.status_code == 200, rate.text
    assert rate.json()["amount_minor_per_hour"] == 125000

    pdf = client.get(
        f"/api/matters/{matter['id']}/invoices/{body['id']}/download",
        headers={**auth_headers(token), "Origin": "http://localhost:3000"},
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert (
        'filename="caseops-matter-invoice-GBA-0001.pdf"'
        in pdf.headers["content-disposition"]
    )
    exposed_headers = pdf.headers["access-control-expose-headers"].lower()
    assert "content-disposition" in exposed_headers
    assert "x-caseops-checksum" in exposed_headers
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.headers["x-caseops-checksum"]) == 64

    with get_session_factory()() as session:
        assert session.scalar(select(MatterInvoiceExport)) is not None
        audit_actions = [
            row.action
            for row in session.scalars(
                select(AuditEvent).where(AuditEvent.company_id == boot["company"]["id"])
            )
        ]
        assert "matter_billing.profile.created" in audit_actions
        assert "matter_invoice.created" in audit_actions
        assert "matter_invoice.pdf.downloaded" in audit_actions


def test_next_hearing_manual_lock_creates_review_suggestion_and_accepts(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="gba-hearing")
    token = str(boot["access_token"])
    matter = _create_matter(
        client,
        token,
        "GBA-HEARING",
        next_hearing_on="2026-06-15",
        next_hearing_manual_lock=True,
    )

    with get_session_factory()() as session:
        db_matter = session.get(Matter, matter["id"])
        assert db_matter is not None
        result = apply_next_hearing_update(
            session,
            matter=db_matter,
            new_date=date(2026, 6, 20),
            source="case_tracking",
            actor_membership_id=str(boot["membership"]["id"]),
            source_ref_type="tracked_case",
            source_ref_id="fixture-tracked-case",
            confidence_label="high",
            reason="provider_future_date",
        )
        session.commit()
    assert result.applied is False
    assert result.suggestion_id is not None

    history = client.get(
        f"/api/matters/{matter['id']}/next-hearing/history",
        headers=auth_headers(token),
    )
    assert history.status_code == 200, history.text
    suggestion = history.json()["suggestions"][0]
    assert suggestion["status"] == "pending"
    assert suggestion["suggested_date"] == "2026-06-20"

    accepted = client.post(
        f"/api/matters/{matter['id']}/next-hearing/suggestions/{suggestion['id']}",
        headers=auth_headers(token),
        json={"action": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["suggestions"][0]["status"] == "accepted"

    refreshed = client.get(f"/api/matters/{matter['id']}", headers=auth_headers(token))
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["next_hearing_on"] == "2026-06-20"


def test_cause_list_preview_pdf_missing_fields_and_tenant_isolation(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, slug_seed="gba-cause-a")
    token_a = str(boot_a["access_token"])
    matter = _create_matter(
        client,
        token_a,
        "GBA-CAUSE",
        case_number=None,
        judge_name=None,
    )
    hearing = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token_a),
        json={
            "hearing_on": "2026-06-30",
            "forum_name": "Delhi High Court",
            "purpose": "Directions",
            "status": "scheduled",
        },
    )
    assert hearing.status_code == 200, hearing.text

    preview = client.post(
        "/api/cause-lists/preview",
        headers=auth_headers(token_a),
        json={
            "date": "2026-06-30",
            "source": "hearings",
            "include_disposed": False,
        },
    )
    assert preview.status_code == 200, preview.text
    rows = preview.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["case_number"] == "Not available"
    assert "case number" in " ".join(rows[0]["missing_field_warnings"]).lower()

    pdf = client.post(
        "/api/cause-lists/download",
        headers=auth_headers(token_a),
        json={
            "date": "2026-06-30",
            "source": "hearings",
            "include_disposed": False,
        },
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.headers["x-caseops-checksum"]) == 64

    boot_b = _bootstrap(client, slug_seed="gba-cause-b")
    token_b = str(boot_b["access_token"])
    isolated = client.post(
        "/api/cause-lists/preview",
        headers=auth_headers(token_b),
        json={"date": "2026-06-30", "source": "hearings"},
    )
    assert isolated.status_code == 200, isolated.text
    assert isolated.json()["rows"] == []

    with get_session_factory()() as session:
        audit_actions = [
            row.action
            for row in session.scalars(
                select(AuditEvent).where(AuditEvent.company_id == boot_a["company"]["id"])
            )
        ]
        assert "cause_list.pdf.downloaded" in audit_actions
