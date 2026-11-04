"""BUG-016: PDFs must preserve source text, not a transliterated test oracle.

These pure renderer tests need no database, browser, user record or provider.
The pre-repair native run is retained as the negative baseline.
"""

from __future__ import annotations

import pypdfium2 as pdfium
import pytest

from caseops_api.services.pdf_layout import (
    pdf_text,
    safe_pdf_class,
    write_wrapped_pairs,
    write_wrapped_table,
)

SAMPLES = (
    "Counsel’s professional fees — reviewing the “annexures”…",
    "En–dash; ‘single’ and “double”; middle·dot; bullet•; arrow→.",
    "Professional fee ₹ 1,250.50",
    "Café — Śrī Rāmesh and Łukasz",
    "Cafe\u0301 and nai\u0308ve",
    "अधिवक्ता की फीस और न्यायालय का आदेश",
    "Invoice शुल्क ₹ 250.00 — “सत्य”",
)


def compact(value: str) -> str:
    return "".join(value.split())


def extracted(body: bytes) -> str:
    document = pdfium.PdfDocument(body)
    pages = []
    try:
        for index in range(len(document)):
            page = document[index]
            text = page.get_textpage()
            try:
                pages.append(text.get_text_range())
            finally:
                text.close()
                page.close()
    finally:
        document.close()
    return "\n".join(pages)


@pytest.mark.parametrize("source", SAMPLES)
def test_pdf_text_preserves_independent_literal_unicode(source: str) -> None:
    assert pdf_text(source) == source


@pytest.mark.parametrize("source", SAMPLES)
def test_actual_wrapped_invoice_table_preserves_source_description(source: str) -> None:
    pdf = safe_pdf_class()(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    write_wrapped_table(
        pdf,
        headings=("Description", "Amount"),
        rows=((source, "INR 1,250.50"),),
        weights=(4, 1),
        font_size=10,
    )
    body = bytes(pdf.output())
    actual_text = extracted(body)
    assert compact(source) in compact(actual_text)


@pytest.mark.parametrize("family", ("Helvetica", "Times", "Courier"))
@pytest.mark.parametrize("style", ("", "B", "I", "BI"))
def test_actual_font_family_style_preserves_typography(family: str, style: str) -> None:
    source = "Counsel’s fees — “review”… ₹ 250.00"
    pdf = safe_pdf_class()(format="A4", unit="mm")
    pdf.add_page()
    pdf.set_font(family, style, 11)
    pdf.multi_cell(0, 6, source, new_x="LMARGIN", new_y="NEXT")
    actual_text = extracted(bytes(pdf.output()))
    assert compact(source) in compact(actual_text)


def test_actual_wrapped_invoice_pairs_preserve_client_and_firm() -> None:
    source = "Client: Śrī Rāmesh — “Legal”"
    pdf = safe_pdf_class()(format="A4", unit="mm")
    pdf.add_page()
    write_wrapped_pairs(pdf, ((source, "अधिवक्ता की फीस ₹ 250.00"),))
    text = compact(extracted(bytes(pdf.output())))
    assert compact(source) in text
    assert compact("अधिवक्ता की फीस ₹ 250.00") in text
