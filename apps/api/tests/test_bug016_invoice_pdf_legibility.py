"""BUG-016 (Ram, 2026-10-30): invoice PDF line items and details unreadable.

The title bar's dark fill leaked into fpdf2's table helper, so every line item
and the invoice-details block were dark text on a dark fill, and a footer
placed inside the auto-break margin added a blank second page. These tests
render each PDF to pixels (pypdfium2) and measure the contrast of every text
run, so a colour defect fails even when text extraction still succeeds.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from fpdf import FPDF

from caseops_api.services.pdf_layout import write_wrapped_pairs, write_wrapped_table
from tests.pdf_legibility import assert_legible, compact, illegible_runs, render
from tests.test_auth_company import auth_headers
from tests.test_gba_law_office_prd import _bootstrap, _create_matter

LONG_DESCRIPTION = (
    "Drafting and settling the written statement with a detailed para-wise reply to "
    "the plaint, the list of documents, the affidavit of admission and denial, and "
    "the interlocutory application for condonation of delay before the Commercial "
    "Division of the High Court of Delhi at New Delhi"
)


def _profile(client: TestClient, token: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Default",
        "is_default": True,
        "currency": "INR",
        "firm_legal_name": "Mehta Legal Chambers LLP",
        "firm_address": "Chamber 12, Delhi High Court\nNew Delhi 110003",
        "firm_gstin": "07ABCDE1234F1Z5",
        "firm_pan": "ABCDE1234F",
        "default_place_of_supply": "Delhi",
        "default_sac_hsn": "998213",
        "gst_applicable": True,
        "gstin_state_code": "07",
        "cgst_rate_bps": 900,
        "sgst_rate_bps": 900,
        "igst_rate_bps": 1800,
        "tax_rate_bps": 1800,
        "invoice_prefix": "INV",
        "next_invoice_sequence": 1,
        "payment_terms_days": 30,
        "billing_mode": "hourly",
        "default_rate_minor_per_hour": 900000,
    }
    payload.update(overrides)
    response = client.post(
        "/api/admin/matter-billing", headers=auth_headers(token), json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


def _invoice_pdf(
    client: TestClient, token: str, matter_id: str, **payload: object
) -> tuple[dict[str, object], bytes]:
    body = {"issued_on": "2026-10-30", "client_name": "Punjab National Bank", **payload}
    created = client.post(
        f"/api/matters/{matter_id}/invoices", headers=auth_headers(token), json=body
    )
    assert created.status_code == 200, created.text
    invoice = created.json()
    pdf = client.get(
        f"/api/matters/{matter_id}/invoices/{invoice['id']}/download",
        headers=auth_headers(token),
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    return invoice, pdf.content


def test_bug016_issued_gst_invoice_is_legible_complete_and_one_page(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="bug016-issued")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "BUG016-ISSUED")
    _profile(client, token)
    for index, minutes in enumerate((660, 45)):
        entry = client.post(
            f"/api/matters/{matter['id']}/time-entries",
            headers=auth_headers(token),
            json={
                "work_date": "2026-10-29",
                "description": f"Conference with client {index} on the recovery suit",
                "duration_minutes": minutes,
                "billable": True,
                "rate_currency": "INR",
            },
        )
        assert entry.status_code == 200, entry.text
    manual = [
        {"description": LONG_DESCRIPTION, "amount_minor": 1234567800},
        {"description": "Court fee and filing charges", "amount_minor": 400000},
    ]
    invoice, body = _invoice_pdf(
        client,
        token,
        str(matter["id"]),
        status="issued",
        client_gstin="07AAACP0165G1ZR",
        client_billing_address="7 Bhikaiji Cama Place, New Delhi",
        include_uninvoiced_time_entries=True,
        manual_items=manual,
    )
    rendered = assert_legible(body)
    assert len(rendered.page_sizes) == 1, "no blank trailing page"
    text = compact(rendered.text)
    assert compact("Page 1 of 1") in text
    assert compact("Tax Invoice") in text
    assert "DRAFT" not in rendered.text
    assert compact("Mehta Legal Chambers LLP") in text
    for line in invoice["line_items"]:
        assert compact(line["description"]) in text, line["description"]
    assert compact("INR 1,23,45,678.00") in text  # Indian digit grouping
    assert compact("11.00 hrs") in text
    assert compact("INR 9,000.00/hr") in text
    assert compact("Status: Issued") in text


def test_bug016_draft_without_legal_name_is_marked_draft_and_names_the_firm(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="bug016-draft")
    token = str(boot["access_token"])
    company_name = str(boot["company"]["name"])
    matter = _create_matter(client, token, "BUG016-DRAFT")
    _profile(client, token, firm_legal_name=None, gst_applicable=False)
    invoice, body = _invoice_pdf(
        client,
        token,
        str(matter["id"]),
        status="draft",
        manual_items=[
            {"description": "Drafting charges for the reply", "amount_minor": 400000},
            {"description": LONG_DESCRIPTION, "amount_minor": 17500000},
        ],
    )
    assert invoice["status"] == "draft"
    rendered = assert_legible(body)
    assert len(rendered.page_sizes) == 1
    assert "DRAFT - NOT A TAX INVOICE" in rendered.text
    assert "Tax Invoice" not in rendered.text
    assert "DRAFT - not a tax invoice" in rendered.text  # footer marking
    assert compact(company_name) in compact(rendered.text)
    assert compact("Status: Draft") in compact(rendered.text)
    for line in invoice["line_items"]:
        assert compact(line["description"]) in compact(rendered.text)
    banner = [run for run in rendered.runs if "DRAFT - NOT A TAX INVOICE" in run.text]
    assert banner and banner[0].contrast >= 4.5


def test_bug016_multi_page_invoice_numbers_every_page_without_blank_page(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="bug016-pages")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "BUG016-PAGES")
    _profile(client, token)
    items = [
        {"description": f"{index:02d} {LONG_DESCRIPTION}", "amount_minor": 100000 + index}
        for index in range(40)
    ]
    invoice, body = _invoice_pdf(
        client, token, str(matter["id"]), status="issued", manual_items=items
    )
    rendered = assert_legible(body)
    pages = len(rendered.page_sizes)
    assert pages >= 2
    for number, page_text in enumerate(rendered.page_texts, start=1):
        assert compact(f"Page {number} of {pages}") in compact(page_text)
        content = [
            run for run in rendered.runs if run.page == number - 1 and "Page" not in run.text
        ]
        assert content, f"page {number} carries only the footer"
    for line in invoice["line_items"]:
        assert compact(line["description"]) in compact(rendered.text)
    assert "Outstanding" in rendered.page_texts[-1]


def test_bug016_outside_counsel_submission_reconciles_and_prints_review_copy(
    client: TestClient,
) -> None:
    from tests.test_portal_matters import (
        _bootstrap as _portal_bootstrap,
    )
    from tests.test_portal_matters import (
        _portal_csrf_headers,
        _seed_matter,
        _verify_and_session,
    )
    from tests.test_portal_outside_counsel import _invite_oc_portal_user

    boot = _portal_bootstrap(client, slug="bug016-oc", email="bug016-oc@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="BUG016-OC-1")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    submitted = client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json={
            "invoice_number": "OC-{BUG016}-1",
            "issued_on": "2026-10-23",
            "currency": "INR",
            "line_items": [{"description": "Appearance before the DRT", "amount_minor": 100000}],
        },
        headers=_portal_csrf_headers(client),
    )
    assert submitted.status_code in (200, 201), submitted.text
    client.cookies.clear()
    workspace = client.get(f"/api/matters/{matter_id}/workspace", headers=auth_headers(token))
    assert workspace.status_code == 200, workspace.text
    invoice = next(
        item for item in workspace.json()["invoices"] if item["invoice_number"] == "OC-{BUG016}-1"
    )
    assert invoice["status"] == "needs_review"
    assert invoice["taxable_value_minor"] == invoice["subtotal_amount_minor"] == 100000
    pdf = client.get(
        f"/api/matters/{matter_id}/invoices/{invoice['id']}/download",
        headers=auth_headers(token),
    )
    assert pdf.status_code == 200, pdf.text
    rendered = assert_legible(pdf.content)
    assert "OUTSIDE COUNSEL INVOICE - SUBMITTED FOR REVIEW" in rendered.text
    assert "Tax Invoice" not in rendered.text
    assert "OC Counsel (outside counsel)" in rendered.text
    assert compact("Taxable value INR 1,000.00") in compact(rendered.text)
    # A free-text portal invoice number must not break the page footer.
    assert compact("REVIEW COPY | OC-{BUG016}-1 | Page 1 of 1") in compact(rendered.text)


def test_bug016_table_helpers_ignore_and_restore_the_caller_graphics_state() -> None:
    pdf = FPDF(format="A4", unit="mm")
    pdf.add_page()
    pdf.set_fill_color(17, 24, 39)
    pdf.set_text_color(17, 24, 39)
    before = (pdf.fill_color, pdf.text_color)
    write_wrapped_pairs(pdf, [("Invoice No: INV-1", "Invoice Date: 2026-10-30")])
    write_wrapped_table(
        pdf,
        headings=("Description", "Amount"),
        weights=(3, 1),
        rows=[(LONG_DESCRIPTION, "INR 4,000.00"), ("Drafting Charges", "INR 1,000.00")],
    )
    assert (pdf.fill_color, pdf.text_color) == before
    rendered = render(bytes(pdf.output()))
    assert illegible_runs(rendered) == []
    assert compact("Drafting Charges") in compact(rendered.text)


# --- Sibling sweep: every PDF generator built on pdf_layout -----------------


def test_bug016_cause_list_pdf_is_legible(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="bug016-cause")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "BUG016-CAUSE", title=LONG_DESCRIPTION[:200])
    hearing = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": "2026-11-02",
            "forum_name": "High Court of Delhi",
            "purpose": "Arguments",
            "status": "scheduled",
        },
    )
    assert hearing.status_code == 200, hearing.text
    response = client.post(
        "/api/cause-lists/download",
        headers=auth_headers(token),
        json={"date_from": "2026-11-02", "date_to": "2026-11-02", "source": "hearings"},
    )
    assert response.status_code == 200, response.text
    rendered = assert_legible(response.content)
    assert compact(LONG_DESCRIPTION[:200]) in compact(rendered.text)


def test_bug016_matter_summary_pdf_is_legible() -> None:
    from caseops_api.services.matter_summary_export import render_summary_pdf
    from tests.test_matter_summary_export import _summary, _timeline

    body, _ = render_summary_pdf(
        matter_title="State v Accused",
        matter_code="CR-001/2026",
        summary=_summary(),
        timeline=_timeline(),
    )
    assert_legible(body)


def test_bug016_draft_export_pdf_is_legible() -> None:
    from caseops_api.services.court_format_profiles import resolve_profile
    from caseops_api.services.draft_pdf_export import render_pdf_bytes

    body = render_pdf_bytes(
        profile=resolve_profile(explicit_key="delhi_hc"),
        title="Bail Application",
        matter_title="State v. Sharma",
        matter_code="MTR-001",
        draft_type="brief",
        revision=1,
        status_label="draft",
        body="1. The applicant is in custody since 1 March 2026.\n\n2. " + LONG_DESCRIPTION,
        citations=["Sushila Aggarwal v. State (NCT of Delhi) (2020) 5 SCC 1"],
        review_required=True,
    )
    assert_legible(body)


def test_bug016_saas_billing_pdf_is_legible() -> None:
    from caseops_api.services.saas_billing import _pdf_bytes

    body = _pdf_bytes(
        "CaseOps Billing Invoice",
        [("Invoice", "BILL-001"), ("Amount", "INR 1,000.00"), ("Description", LONG_DESCRIPTION)],
    )
    assert_legible(body)


# --- Retiring a draft: POST /api/matters/{id}/invoices/{invoice_id}/void ----


def _member_token(client: TestClient, owner_token: str, slug: str, role: str) -> str:
    email = f"{role}-{slug}@bug016.example"
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={"full_name": "Billing Member", "email": email, "role": role,
              "password": "MemberPass123!"},
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={"company_slug": slug, "email": email, "password": "MemberPass123!"},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


def test_bug016_void_draft_releases_time_and_is_audited(client: TestClient) -> None:
    from sqlalchemy import select

    from caseops_api.db.models import AuditEvent
    from caseops_api.db.session import get_session_factory

    boot = _bootstrap(client, slug_seed="bug016-void")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "BUG016-VOID")
    entry = client.post(
        f"/api/matters/{matter['id']}/time-entries",
        headers=auth_headers(token),
        json={"work_date": "2026-10-29", "description": "Drafting the reply",
              "duration_minutes": 90, "billable": True, "rate_currency": "INR"},
    )
    assert entry.status_code == 200, entry.text
    draft, _ = _invoice_pdf(
        client, token, str(matter["id"]), status="draft", include_uninvoiced_time_entries=True,
        manual_items=[{"description": "Court fee", "amount_minor": 50000}],
    )
    voided = client.post(
        f"/api/matters/{matter['id']}/invoices/{draft['id']}/void", headers=auth_headers(token)
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "void"
    pdf = client.get(
        f"/api/matters/{matter['id']}/invoices/{draft['id']}/download", headers=auth_headers(token)
    )
    assert "VOID - CANCELLED INVOICE" in assert_legible(pdf.content).text
    # The released time entry can be billed again on a new invoice.
    again, _ = _invoice_pdf(
        client, token, str(matter["id"]), status="draft", include_uninvoiced_time_entries=True
    )
    assert [line["description"] for line in again["line_items"]] == ["Drafting the reply"]
    repeat = client.post(
        f"/api/matters/{matter['id']}/invoices/{draft['id']}/void", headers=auth_headers(token)
    )
    assert repeat.status_code == 409, repeat.text
    with get_session_factory()() as session:
        rows = list(session.scalars(select(AuditEvent).where(
            AuditEvent.action == "matter_invoice.voided", AuditEvent.target_id == draft["id"],
        )))
    assert len(rows) == 1
    assert rows[0].company_id == boot["company"]["id"]


def test_bug016_void_refuses_issued_other_tenant_and_member(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="bug016-void-neg")
    token = str(boot["access_token"])
    slug = str(boot["company"]["slug"])
    matter_code = "BUG016-VOID-NEG"
    matter = _create_matter(client, token, matter_code)
    manual = [{"description": "Court fee", "amount_minor": 50000}]
    issued, _ = _invoice_pdf(client, token, str(matter["id"]), status="issued", manual_items=manual)
    draft, _ = _invoice_pdf(client, token, str(matter["id"]), status="draft", manual_items=manual)
    url = f"/api/matters/{matter['id']}/invoices"

    refused = client.post(f"{url}/{issued['id']}/void", headers=auth_headers(token))
    assert refused.status_code == 409, refused.text
    assert "credit note" in refused.json()["detail"]

    member = _member_token(client, token, slug, "member")
    forbidden = client.post(f"{url}/{draft['id']}/void", headers=auth_headers(member))
    assert forbidden.status_code == 403, forbidden.text

    other = _bootstrap(client, slug_seed="bug016-void-other")
    leaked = client.post(
        f"{url}/{draft['id']}/void", headers=auth_headers(str(other["access_token"]))
    )
    assert leaked.status_code == 404, leaked.text
    other_matter = _create_matter(client, str(other["access_token"]), "BUG016-VOID-OTHER")
    crossed = client.post(
        f"/api/matters/{other_matter['id']}/invoices/{draft['id']}/void",
        headers=auth_headers(str(other["access_token"])),
    )
    assert crossed.status_code == 404, crossed.text

    still = client.get(f"/api/matters/{matter['id']}/workspace", headers=auth_headers(token))
    statuses = {item["id"]: item["status"] for item in still.json()["invoices"]}
    assert statuses[draft["id"]] == "draft"
    assert statuses[issued["id"]] == "issued"


# --- Review fixes: raster negative control, stored legacy state ------------


def test_bug016_raster_check_flags_dark_text_on_a_dark_fill() -> None:
    """Negative control: the metric must fail the reported defect itself."""

    pdf = FPDF(format="A4", unit="mm")
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 8, "Visible heading", new_x="LMARGIN", new_y="NEXT")
    pdf.set_fill_color(17, 24, 39)
    pdf.cell(80, 8, "Hidden cell text", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    # The pre-fix table: fpdf2 copies the caller's fill into every body cell.
    with pdf.table(col_widths=(3, 1)) as table:
        for values in (("Description", "Amount"), ("Drafting Charges", "INR 4,000.00")):
            row = table.row()
            for value in values:
                row.cell(value)
    rendered = render(bytes(pdf.output()))
    illegible = " ".join(illegible_runs(rendered))
    for hidden in ("Hidden cell text", "Drafting Charges", "INR 4,000.00"):
        assert hidden in illegible, (hidden, illegible)
    assert "Visible heading" not in illegible


def test_bug016_stored_outside_counsel_row_with_zero_taxable_value_prints_subtotal(
    client: TestClient,
) -> None:
    """INVR-2026-028's stored state: needs_review, taxable 0, no tax."""

    from caseops_api.db.models import MatterInvoice
    from caseops_api.db.session import get_session_factory
    from tests.test_portal_matters import (
        _bootstrap as _portal_bootstrap,
    )
    from tests.test_portal_matters import (
        _portal_csrf_headers,
        _seed_matter,
        _verify_and_session,
    )
    from tests.test_portal_outside_counsel import _invite_oc_portal_user

    boot = _portal_bootstrap(client, slug="bug016-oc-legacy", email="bug016-legacy@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="BUG016-OC-LEGACY")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    submitted = client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json={
            "invoice_number": "INVR-LEGACY-028",
            "issued_on": "2026-10-23",
            "currency": "INR",
            "line_items": [{"description": "Appearance before the DRT", "amount_minor": 100000}],
        },
        headers=_portal_csrf_headers(client),
    )
    assert submitted.status_code in (200, 201), submitted.text
    client.cookies.clear()
    workspace = client.get(f"/api/matters/{matter_id}/workspace", headers=auth_headers(token))
    invoice = next(
        item for item in workspace.json()["invoices"]
        if item["invoice_number"] == "INVR-LEGACY-028"
    )
    with get_session_factory()() as session:
        row = session.get(MatterInvoice, invoice["id"])
        assert row is not None
        row.taxable_value_minor = 0  # as stored in production before BUG-016
        session.commit()
    pdf = client.get(
        f"/api/matters/{matter_id}/invoices/{invoice['id']}/download",
        headers=auth_headers(token),
    )
    assert pdf.status_code == 200, pdf.text
    rendered = assert_legible(pdf.content)
    assert len(rendered.page_sizes) == 1
    text = compact(rendered.text)
    assert compact("Taxable value INR 1,000.00") in text
    assert compact("Grand total INR 1,000.00") in text
    assert "OUTSIDE COUNSEL INVOICE - SUBMITTED FOR REVIEW" in rendered.text
    assert "OC Counsel (outside counsel)" in rendered.text
    assert compact("Appearance before the DRT") in text


# --- Void keeps every money figure honest -------------------------------------


def _billing_figures(client: TestClient, token: str, matter_id: str) -> dict[str, object]:
    workspace = client.get(f"/api/matters/{matter_id}/workspace", headers=auth_headers(token))
    assert workspace.status_code == 200, workspace.text
    invoices = [item for item in workspace.json()["invoices"] if item["status"] != "void"]
    brief = client.post(
        f"/api/ai/matters/{matter_id}/briefs/generate",
        headers=auth_headers(token),
        json={"brief_type": "matter_summary"},
    )
    assert brief.status_code == 200, brief.text
    snapshot = str(brief.json()["billing_snapshot"])
    return {
        "total_billed": sum(item["total_amount_minor"] for item in invoices),
        # briefing.py sums balance_due_minor over every workspace invoice.
        "all_balances": sum(item["balance_due_minor"] for item in workspace.json()["invoices"]),
        "brief_open_balance": snapshot.split("total open balance", 1)[1],
    }


def test_bug016_void_zeroes_balance_and_restores_billing_and_brief_totals(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="bug016-void-totals")
    token = str(boot["access_token"])
    matter_code = "BUG016-VOID-TOTALS"
    matter = _create_matter(client, token, matter_code)
    matter_id = str(matter["id"])
    _invoice_pdf(
        client, token, matter_id, status="issued",
        manual_items=[{"description": "Earlier issued fee", "amount_minor": 50000}],
    )
    before = _billing_figures(client, token, matter_id)
    assert before["total_billed"] == before["all_balances"] == 50000
    draft, _ = _invoice_pdf(
        client, token, matter_id, status="draft", invoice_number="QA-B016-TOTALS-1",
        manual_items=[{"description": "Drafting charges", "amount_minor": 17900000}],
    )
    during = _billing_figures(client, token, matter_id)
    assert during["total_billed"] == 50000 + draft["total_amount_minor"]
    voided = client.post(
        f"/api/matters/{matter_id}/invoices/{draft['id']}/void", headers=auth_headers(token)
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "void"
    assert voided.json()["balance_due_minor"] == 0
    assert voided.json()["total_amount_minor"] == draft["total_amount_minor"]
    assert _billing_figures(client, token, matter_id) == before
    activity = client.get(f"/api/matters/{matter_id}/workspace", headers=auth_headers(token))
    events = [item["event_type"] for item in activity.json()["activity"]]
    assert "invoice_voided" in events


# --- Issue: the in-product path from draft to the firm's invoice -----------


def test_bug016_issue_draft_is_audited_final_and_prints_as_the_invoice(
    client: TestClient,
) -> None:
    from sqlalchemy import select

    from caseops_api.db.models import AuditEvent
    from caseops_api.db.session import get_session_factory

    boot = _bootstrap(client, slug_seed="bug016-issue")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "BUG016-ISSUE")
    matter_id = str(matter["id"])
    draft, draft_pdf = _invoice_pdf(
        client, token, matter_id, status="draft",
        manual_items=[{"description": "Settling the written statement", "amount_minor": 400000}],
    )
    assert "DRAFT - NOT A TAX INVOICE" in assert_legible(draft_pdf).text
    url = f"/api/matters/{matter_id}/invoices/{draft['id']}"
    issued = client.post(f"{url}/issue", headers=auth_headers(token))
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "issued"
    assert issued.json()["invoice_number"] == draft["invoice_number"]
    assert issued.json()["total_amount_minor"] == draft["total_amount_minor"]

    pdf = client.get(f"{url}/download", headers=auth_headers(token))
    rendered = assert_legible(pdf.content)
    assert "DRAFT" not in rendered.text
    assert compact("Status: Issued") in compact(rendered.text)
    assert compact("Settling the written statement") in compact(rendered.text)

    again = client.post(f"{url}/issue", headers=auth_headers(token))
    assert again.status_code == 409, again.text
    refused_void = client.post(f"{url}/void", headers=auth_headers(token))
    assert refused_void.status_code == 409, refused_void.text
    workspace = client.get(f"/api/matters/{matter_id}/workspace", headers=auth_headers(token))
    assert "invoice_issued" in [item["event_type"] for item in workspace.json()["activity"]]
    with get_session_factory()() as session:
        rows = list(session.scalars(select(AuditEvent).where(
            AuditEvent.action == "matter_invoice.issued", AuditEvent.target_id == draft["id"],
        )))
    assert len(rows) == 1
    assert rows[0].company_id == boot["company"]["id"]


def test_bug016_issue_refuses_member_and_other_tenant(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="bug016-issue-neg")
    token = str(boot["access_token"])
    slug = str(boot["company"]["slug"])
    matter = _create_matter(client, token, "BUG016-ISSUE-NEG")
    manual = [{"description": "Court fee", "amount_minor": 50000}]
    draft, _ = _invoice_pdf(client, token, str(matter["id"]), status="draft", manual_items=manual)
    url = f"/api/matters/{matter['id']}/invoices/{draft['id']}/issue"

    member = _member_token(client, token, slug, "member")
    assert client.post(url, headers=auth_headers(member)).status_code == 403

    other = _bootstrap(client, slug_seed="bug016-issue-other")
    other_token = str(other["access_token"])
    assert client.post(url, headers=auth_headers(other_token)).status_code == 404
    other_matter = _create_matter(client, other_token, "BUG016-ISSUE-OTHER")
    crossed = client.post(
        f"/api/matters/{other_matter['id']}/invoices/{draft['id']}/issue",
        headers=auth_headers(other_token),
    )
    assert crossed.status_code == 404, crossed.text
    still = client.get(f"/api/matters/{matter['id']}/workspace", headers=auth_headers(token))
    assert {item["id"]: item["status"] for item in still.json()["invoices"]}[draft["id"]] == "draft"


def test_bug016_partner_downloads_and_issues_but_only_the_owner_voids(
    client: TestClient,
) -> None:
    """The billing page gates PDF/Issue on invoices:issue and Void on invoices:void."""

    boot = _bootstrap(client, slug_seed="bug016-partner")
    token = str(boot["access_token"])
    slug = str(boot["company"]["slug"])
    matter_code = "BUG016-PARTNER"
    matter = _create_matter(client, token, matter_code)
    url = f"/api/matters/{matter['id']}/invoices"
    partner = _member_token(client, token, slug, "partner")
    admin = _member_token(client, token, slug, "admin")
    created = client.post(
        url,
        headers=auth_headers(partner),
        json={
            "issued_on": "2026-10-30",
            "status": "draft",
            "include_uninvoiced_time_entries": False,
            "manual_items": [{"description": "Partner drafted fee", "amount_minor": 120000}],
        },
    )
    assert created.status_code == 200, created.text
    draft = created.json()

    pdf = client.get(f"{url}/{draft['id']}/download", headers=auth_headers(partner))
    assert pdf.status_code == 200, pdf.text
    assert compact("Partner drafted fee") in compact(assert_legible(pdf.content).text)

    for role_token in (partner, admin):
        refused = client.post(f"{url}/{draft['id']}/void", headers=auth_headers(role_token))
        assert refused.status_code == 403, refused.text
        assert "invoices:void" in refused.json()["detail"]

    issued = client.post(f"{url}/{draft['id']}/issue", headers=auth_headers(partner))
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "issued"


def test_bug016_ip_cost_linked_to_a_voided_draft_surfaces_as_missing(
    client: TestClient,
) -> None:
    """IPLF-UJ-52-EXC-06 applied to the new void path."""

    from tests.test_ip_039f_cost_linkage import _cost, _reconcile, _setup

    headers, docket, matter = _setup(client)
    created = client.post(
        f"/api/matters/{matter['id']}/invoices",
        headers=headers,
        json={
            "issued_on": "2026-10-30",
            "status": "draft",
            "include_uninvoiced_time_entries": False,
            "manual_items": [{"description": "Official filing fee", "amount_minor": 900000}],
        },
    )
    assert created.status_code == 200, created.text
    draft = created.json()
    linked = _cost(
        client, headers, docket["id"], billing_link_type="invoice", billing_link_id=draft["id"]
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["cost_items"][0]["reconciliation_status"] == "matched"

    voided = client.post(
        f"/api/matters/{matter['id']}/invoices/{draft['id']}/void", headers=headers
    )
    assert voided.status_code == 200, voided.text
    report = _reconcile(client, headers, docket["id"]).json()
    assert report["missing_count"] == 1
    assert report["matched_count"] == 0
