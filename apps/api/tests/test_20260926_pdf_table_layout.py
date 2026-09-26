"""BUG-033 (Ram, 2026-09-26): cause list PDF text must stay inside its cells.

The old renderer drew fixed-width single-line cells whose widths exceeded the
printable page and cut every value at 32 characters, so text ran across column
borders. These tests read the generated PDF's glyph positions: no glyph may
cross a column border or leave the printable area, and long values must be
wrapped rather than truncated.
"""

from __future__ import annotations

import io
import re

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF
from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LTChar, LTTextContainer

from caseops_api.services.cause_lists import CAUSE_LIST_PDF_HEADINGS, CAUSE_LIST_PDF_WEIGHTS
from caseops_api.services.pdf_layout import pdf_text, write_wrapped_table
from tests.test_auth_company import auth_headers
from tests.test_gba_law_office_prd import _bootstrap, _create_matter

MM = 72 / 25.4
LONG_TITLE = (
    "Satish Kumar Mehani and Another versus Punjab National Bank and Others "
    "through its Chief Manager Recovery Department Connaught Place Branch"
)
LONG_JUDGE = "Hon'ble Mr. Justice Subramonium Prasad and Hon'ble Mr. Justice Harish Vaidyanathan"
LONG_LAWYERS = (
    "Ramesh Chandra Shrivastava, Senior Advocate with Anjali Venkataraman and Rohit Bhardwaj"
)


def _page_chars(page: object) -> list[LTChar]:
    found: list[LTChar] = []
    stack = [element for element in page if isinstance(element, LTTextContainer)]
    while stack:
        node = stack.pop()
        if isinstance(node, LTChar):
            found.append(node)
        elif hasattr(node, "__iter__"):
            stack.extend(node)
    return found


def _chars(pdf_bytes: bytes) -> list[LTChar]:
    return [char for page in extract_pages(io.BytesIO(pdf_bytes)) for char in _page_chars(page)]


def _column_borders(page_width_pt: float, weights: tuple[float, ...]) -> list[float]:
    left = 10 * MM
    usable = page_width_pt - 20 * MM
    total = sum(weights)
    borders = [left]
    for weight in weights:
        borders.append(borders[-1] + usable * weight / total)
    return borders


def _glyphs_crossing_borders(pdf_bytes: bytes, weights: tuple[float, ...]) -> list[str]:
    offenders = []
    for page in extract_pages(io.BytesIO(pdf_bytes)):
        borders = _column_borders(page.width, weights)
        chars = _page_chars(page)
        # Table glyphs are those at or below the first heading glyph "Sr".
        heading_top = max(
            (c.y1 for c in chars if c.get_text() == "S" and abs(c.x0 - borders[0]) < 3 * MM),
            default=None,
        )
        for char in chars:
            if char.get_text().isspace():
                continue
            if char.x0 < borders[0] - 0.5 or char.x1 > borders[-1] + 0.5:
                offenders.append(f"outside printable width: {char.get_text()!r} at {char.x0:.1f}")
            if heading_top is not None and char.y1 <= heading_top + 0.5:
                for border in borders[1:-1]:
                    if char.x0 < border - 0.3 and char.x1 > border + 0.3:
                        offenders.append(
                            f"crosses column border: {char.get_text()!r} at {char.x0:.1f}"
                        )
    return offenders


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _column_text(pdf_bytes: bytes, weights: tuple[float, ...], column: int) -> str:
    """Glyphs inside one column, read top-to-bottom then left-to-right."""

    text = []
    for page in extract_pages(io.BytesIO(pdf_bytes)):
        borders = _column_borders(page.width, weights)
        left, right = borders[column], borders[column + 1]
        chars = _page_chars(page)
        inside = [c for c in chars if c.x0 >= left - 0.3 and c.x1 <= right + 0.3]
        inside.sort(key=lambda c: (-round(c.y0, 0), c.x0))
        text.append("".join(c.get_text() for c in inside))
    return "".join(text)


def test_cause_list_pdf_wraps_long_values_inside_their_columns(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="bug033")
    token = str(boot["access_token"])
    for index in range(3):
        matter = _create_matter(
            client,
            token,
            f"BUG033-{index}-MATTER-FILE-REFERENCE-2026",
            title=f"{LONG_TITLE} {index}",
            case_number=f"W.P.(C) 62{index}9/2019 with CM APPL. 1234{index}/2019",
            judge_name=LONG_JUDGE,
            court_name="High Court of Delhi at New Delhi, Principal Bench",
        )
        hearing = client.post(
            f"/api/matters/{matter['id']}/hearings",
            headers=auth_headers(token),
            json={
                "hearing_on": "2026-09-25",
                "forum_name": "High Court of Delhi at New Delhi, Principal Bench",
                "purpose": "Arguments",
                "status": "scheduled",
            },
        )
        assert hearing.status_code == 200, hearing.text
    response = client.post(
        "/api/cause-lists/download",
        headers=auth_headers(token),
        json={"date_from": "2026-09-25", "date_to": "2026-09-25", "source": "hearings"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["x-caseops-row-count"] == "3"
    body = response.content

    assert _glyphs_crossing_borders(body, CAUSE_LIST_PDF_WEIGHTS) == []
    title_column = CAUSE_LIST_PDF_HEADINGS.index("Title")
    court_column = CAUSE_LIST_PDF_HEADINGS.index("Court")
    titles = _compact(_column_text(body, CAUSE_LIST_PDF_WEIGHTS, title_column))
    courts = _compact(_column_text(body, CAUSE_LIST_PDF_WEIGHTS, court_column))
    # Wrapped, never truncated: every long value survives in full in its column.
    for index in range(3):
        assert _compact(f"{LONG_TITLE} {index}") in titles
    assert courts.count(_compact("High Court of Delhi at New Delhi, Principal Bench")) == 3
    text = _compact(extract_text(io.BytesIO(body)))
    for heading in CAUSE_LIST_PDF_HEADINGS:
        assert _compact(heading) in text
    assert "2026-09-25" in extract_text(io.BytesIO(body))


def test_cause_list_pdf_with_non_latin_text_downloads(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="bug033-unicode")
    token = str(boot["access_token"])
    matter = _create_matter(
        client,
        token,
        "BUG033-UNICODE",
        title="Rāmesh — “Quoted” v State ‘Ltd’ … ₹ 5,00,000 राम",
    )
    hearing = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": "2026-09-25",
            "forum_name": "Delhi High Court",
            "purpose": "Arguments",
            "status": "scheduled",
        },
    )
    assert hearing.status_code == 200, hearing.text
    response = client.post(
        "/api/cause-lists/download",
        headers=auth_headers(token),
        json={"date_from": "2026-09-25", "date_to": "2026-09-25", "source": "hearings"},
    )
    assert response.status_code == 200, response.text
    text = extract_text(io.BytesIO(response.content))
    assert '"Quoted"' in text
    assert "INR" in text


def test_pdf_text_keeps_latin1_and_replaces_only_unencodable_text() -> None:
    assert pdf_text(None) == ""
    assert pdf_text("Café — “A” ‘B’ …") == 'Café -- "A" \'B\' ...'
    assert pdf_text("₹ 10") == "INR  10"
    assert pdf_text("राम") == "?"


def test_wrapped_table_rejects_rows_with_the_wrong_column_count() -> None:
    pdf = FPDF(orientation="L", format="A4", unit="mm")
    pdf.add_page()
    with pytest.raises(ValueError, match="one value per column"):
        write_wrapped_table(pdf, headings=("A", "B"), rows=[("1",)], weights=(1, 1))


def test_wrapped_table_never_overruns_the_printable_width() -> None:
    for orientation in ("P", "L"):
        pdf = FPDF(orientation=orientation, format="A4", unit="mm")
        pdf.add_page()
        write_wrapped_table(
            pdf,
            headings=CAUSE_LIST_PDF_HEADINGS,
            weights=CAUSE_LIST_PDF_WEIGHTS,
            rows=[tuple(f"{label} {LONG_LAWYERS}" for label in CAUSE_LIST_PDF_HEADINGS)] * 25,
        )
        body = bytes(pdf.output())
        assert _glyphs_crossing_borders(body, CAUSE_LIST_PDF_WEIGHTS) == [], orientation
        assert _chars(body)


INVOICE_WEIGHTS = (82, 25, 25, 25, 28)


def test_invoice_pdf_wraps_line_items_and_accepts_non_latin_names(client: TestClient) -> None:
    """The invoice drew four single-line columns and crashed on non-Latin text."""

    boot = _bootstrap(client, slug_seed="bug033-invoice")
    token = str(boot["access_token"])
    matter = _create_matter(
        client, token, "BUG033-INV", title="Rāmesh — “Quoted” v State राम"
    )
    profile = client.post(
        "/api/admin/matter-billing",
        headers=auth_headers(token),
        json={
            "name": "Default",
            "is_default": True,
            "currency": "INR",
            "firm_legal_name": "Śrī Legal — Chambers",
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
            "invoice_prefix": "INV",
            "next_invoice_sequence": 1,
            "payment_terms_days": 15,
            "billing_mode": "hourly",
            "default_rate_minor_per_hour": 100000,
        },
    )
    assert profile.status_code == 200, profile.text
    for index in range(12):
        entry = client.post(
            f"/api/matters/{matter['id']}/time-entries",
            headers=auth_headers(token),
            json={
                "work_date": "2026-06-06",
                "description": f"{index} " + LONG_TITLE + " — reviewed “annexures” … राम",
                "duration_minutes": 60 + index,
                "billable": True,
                "rate_currency": "INR",
            },
        )
        assert entry.status_code == 200, entry.text
    invoice = client.post(
        f"/api/matters/{matter['id']}/invoices",
        headers=auth_headers(token),
        json={
            "issued_on": "2026-06-06",
            "client_name": "Ānanda Traders",
            "client_billing_name": "Ānanda Traders",
            "client_billing_address": "Mumbai",
            "place_of_supply": "Maharashtra",
            "sac_hsn": "998212",
            "status": "issued",
            "include_uninvoiced_time_entries": True,
        },
    )
    assert invoice.status_code == 200, invoice.text
    pdf = client.get(
        f"/api/matters/{matter['id']}/invoices/{invoice.json()['id']}/download",
        headers=auth_headers(token),
    )
    assert pdf.status_code == 200, pdf.text
    body = pdf.content
    # Glyphs stay inside the portrait printable width and the line-item columns.
    assert [
        offender
        for offender in _glyphs_crossing_borders(body, INVOICE_WEIGHTS)
        if offender.startswith("outside printable width")
    ] == []
    descriptions = _compact(_column_text(body, INVOICE_WEIGHTS, 0))
    for index in range(12):
        assert _compact(f"{index} {LONG_TITLE}") in descriptions


def test_every_pdf_generator_builds_documents_through_the_safe_font_class() -> None:
    """A bare FPDF lets one non-Latin value fail the whole download."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "caseops_api"
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if path.name != "pdf_layout.py"
        and re.search(r"from fpdf import[^\n]*\bFPDF\b|\bfpdf\.FPDF\b", path.read_text("utf-8"))
    ]
    assert offenders == []


def test_every_multi_cell_returns_the_cursor_explicitly() -> None:
    """multi_cell() defaults to leaving the cursor at the right margin, which drew
    the invoice's Matter line off the page; every call must say where to go next."""

    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "caseops_api"
    offenders = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "multi_cell":
                keywords = {keyword.arg for keyword in node.keywords}
                if "new_x" not in keywords and None not in keywords:
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == []
