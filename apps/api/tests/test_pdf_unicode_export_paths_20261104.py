"""Source-fidelity regressions at the five real PDF export entry points."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.pdf_legibility import assert_legible, compact
from tests.test_auth_company import auth_headers
from tests.test_bug016_invoice_pdf_legibility import _invoice_pdf, _profile
from tests.test_gba_law_office_prd import _bootstrap, _create_matter

SOURCE = "Counsel’s fees — “review”… ₹ 250.00; अधिवक्ता की फीस"


def test_actual_invoice_api_pdf_keeps_all_original_line_and_name_characters(client: TestClient):
    boot = _bootstrap(client, slug_seed="unicode-invoice")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "UNICODE-INV", title="Śrī Rāmesh — न्याय")
    _profile(client, token, firm_legal_name="Śrī “न्याय” Chambers")
    invoice, body = _invoice_pdf(
        client,
        token,
        str(matter["id"]),
        status="draft",
        client_name="Café — Rāmesh",
        manual_items=[{"description": SOURCE, "amount_minor": 25050}],
    )
    rendered = assert_legible(body)
    actual = compact(rendered.text)
    assert compact(SOURCE) in actual
    assert compact("Śrī “न्याय” Chambers") in actual
    assert compact("Café — Rāmesh") in actual
    assert compact("INR 250.50") in actual
    assert invoice["line_items"][0]["description"] == SOURCE
    assert len(rendered.page_sizes) == 1
    assert compact("Page 1 of 1") in actual


def test_uncovered_invoice_text_returns_actionable_api_error_without_partial_pdf_or_rewrite(
    client: TestClient,
):
    boot = _bootstrap(client, slug_seed="unicode-unsupported")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "UNICODE-UNSUPPORTED")
    _profile(client, token)
    headers = auth_headers(token)
    created = client.post(
        f"/api/matters/{matter['id']}/invoices",
        headers=headers,
        json={
            "issued_on": "2026-11-04",
            "client_name": "Synthetic Client",
            "status": "draft",
            "manual_items": [{"description": "Original source 漢", "amount_minor": 12345}],
        },
    )
    assert created.status_code == 200
    invoice = created.json()
    before_response = client.get(f"/api/matters/{matter['id']}/workspace", headers=headers)
    assert before_response.status_code == 200
    before = next(row for row in before_response.json()["invoices"] if row["id"] == invoice["id"])
    response = client.get(
        f"/api/matters/{matter['id']}/invoices/{invoice['id']}/download",
        headers=headers,
    )
    assert response.status_code == 422
    assert response.headers["content-type"].split(";", 1)[0] == "application/problem+json"
    assert not response.content.startswith(b"%PDF-")
    problem = response.json()
    assert problem["status"] == 422
    assert problem["type"] == "https://httpstatuses.com/422"
    error = json.dumps(problem, ensure_ascii=False)
    assert "Contact support" in error
    assert "漢" not in error
    after_response = client.get(f"/api/matters/{matter['id']}/workspace", headers=headers)
    assert after_response.status_code == 200
    after = next(row for row in after_response.json()["invoices"] if row["id"] == invoice["id"])
    assert after == before
    assert after["line_items"][0]["description"] == "Original source 漢"


def test_cause_list_pdf_preserves_actual_source_titles(client: TestClient):
    boot = _bootstrap(client, slug_seed="unicode-cause")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "UNICODE-CAUSE", title=SOURCE)
    response = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": "2026-11-04",
            "forum_name": "Delhi High Court",
            "purpose": "Arguments",
            "status": "scheduled",
        },
    )
    assert response.status_code == 200
    response = client.post(
        "/api/cause-lists/download",
        headers=auth_headers(token),
        json={"date_from": "2026-11-04", "date_to": "2026-11-04", "source": "hearings"},
    )
    assert response.status_code == 200
    rendered = assert_legible(response.content)
    assert compact(SOURCE) in compact(rendered.text)


def test_summary_export_preserves_source_sections_and_unicode():
    from caseops_api.services.matter_summary_export import render_summary_pdf
    from tests.test_matter_summary_export import _summary, _timeline

    body, _ = render_summary_pdf(
        matter_title=SOURCE,
        matter_code="UNICODE-SUMMARY",
        summary=_summary(),
        timeline=_timeline(),
    )
    rendered = assert_legible(body)
    assert compact(SOURCE) in compact(rendered.text)


def test_draft_export_preserves_original_body_and_court_profile():
    from caseops_api.services.court_format_profiles import resolve_profile
    from caseops_api.services.draft_pdf_export import render_pdf_bytes

    body = render_pdf_bytes(
        profile=resolve_profile(explicit_key="delhi_hc"),
        title="Application",
        matter_title="Matter",
        matter_code="UNICODE-DRAFT",
        draft_type="brief",
        revision=1,
        status_label="draft",
        body=SOURCE,
        citations=[],
        review_required=True,
    )
    rendered = assert_legible(body)
    assert compact(SOURCE) in compact(rendered.text)
    assert "REVIEW REQUIRED" in rendered.text


def test_saas_billing_pdf_preserves_original_row_text():
    from caseops_api.services.saas_billing import _pdf_bytes

    body = _pdf_bytes("CaseOps invoice", [("Description", SOURCE)])
    rendered = assert_legible(body)
    assert compact(SOURCE) in compact(rendered.text)
