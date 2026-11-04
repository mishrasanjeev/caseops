"""Real shaped-text semantics, keeping visual SDK operations and source values."""

from __future__ import annotations

import re
import zlib

import pypdfium2 as pdfium
import pytest

from caseops_api.services.pdf_layout import safe_pdf_class
from tests.test_pdf_unicode_fidelity_20261104 import compact, extracted


def document():
    pdf = safe_pdf_class()(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    return pdf


def page_content(page):
    """Inspect the pinned SDK's finalized stream without changing its bytes."""
    from fpdf.syntax import Name, PDFContentStream

    stream = page.contents
    if type(stream) in (bytes, bytearray):
        content = bytes(stream)
    else:
        assert type(stream) is PDFContentStream
        payload = stream.content_stream()
        assert type(payload) is bytes and len(payload) <= 1024 * 1024
        if stream.filter is None:
            content = payload
        else:
            expected_filter = Name("FlateDecode")
            assert stream.filter == expected_filter, "Unknown page content filter"
            decoder = zlib.decompressobj()
            try:
                content = decoder.decompress(payload, 1024 * 1024 + 1)
            except zlib.error as error:
                raise AssertionError("Corrupt declared FlateDecode page content") from error
            assert decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data
    assert len(content) <= 1024 * 1024
    return content


@pytest.mark.parametrize("fault", ("unknown-filter", "corrupt-flate", "oversized-flate"))
def test_content_inspection_refuses_unsupported_or_corrupt_actual_sdk_streams(fault):
    from types import SimpleNamespace

    from fpdf.syntax import Name, PDFContentStream

    if fault == "oversized-flate":
        stream = PDFContentStream(b"x" * (1024 * 1024 + 1), compress=True)
    else:
        stream = PDFContentStream(b"not a flate stream", compress=False)
        stream.filter = Name("LZWDecode" if fault == "unknown-filter" else "FlateDecode")
    with pytest.raises(AssertionError):
        page_content(SimpleNamespace(contents=stream))


def test_real_semantic_fragment_keeps_original_visual_operators_and_clone_state():
    from fpdf.line_break import Fragment

    pdf = document()
    # Select an actual fallback fragment whose shaping includes a continuation.
    fragments = list(pdf._parse_chars("अधिवक्ता की फीस", markdown=False))
    fragment = fragments[0]
    cloned = fragment.clone(characters=fragment.characters, link="https://example.invalid/")
    original = Fragment.render_with_text_shaping(cloned, 10, 20, pdf.h, 0)
    semantic = cloned.render_with_text_shaping(10, 20, pdf.h, 0)
    match = re.fullmatch(r"/Span <</ActualText <([0-9A-F]+)>>> BDC\n(.*)\nEMC", semantic, re.S)
    assert match is not None
    assert match[2] == original
    assert bytes.fromhex(match[1]).decode("utf-16") == cloned.string
    assert type(cloned) is type(fragment)
    assert cloned.graphics_state is fragment.graphics_state
    assert cloned.k == fragment.k
    assert cloned.link == "https://example.invalid/"
    assert fragment.link is None


@pytest.mark.parametrize(
    "source",
    (
        "Counsel’s fees — “review”… ₹ 250.00; अधिवक्ता की फीस",
        r"Literal (parentheses) \\ backslash <hex> /Span >> BDC EMC — अधिवक्ता की फीस",
        "Literal PDF syntax: ) Tj ET /ActualText <0004> BDC ( — अधिवक्ता की फीस",
    ),
)
def test_pdf_syntax_like_source_is_hex_encoded_and_extracted_as_original_text(source):
    pdf = document()
    pdf.multi_cell(0, 6, source, new_x="LMARGIN", new_y="NEXT")
    body = bytes(pdf.output())
    actual = extracted(body)
    assert compact(source) in compact(actual)
    assert "\x04" not in actual
    assert body.startswith(b"%PDF-1.5")
    content = page_content(pdf.pages[1])
    spans = re.findall(rb"/Span <</ActualText <([0-9A-F]+)>>> BDC", content)
    logical_fragments = [bytes.fromhex(value.decode()).decode("utf-16") for value in spans]
    assert "".join(logical_fragments) == source
    assert content.count(b" BDC") == content.count(b"EMC")


def test_narrow_wrapping_clones_preserve_all_logical_source_without_control_insertions():
    pdf = document()
    source = " ".join(
        f"Entry {index}: Counsel’s fees — अधिवक्ता की फीस ₹ {index}.50." for index in range(1, 7)
    )
    pdf.multi_cell(52, 6, source, new_x="LMARGIN", new_y="NEXT")
    body = bytes(pdf.output())
    actual = extracted(body)
    assert compact(source) in compact(actual)
    assert "\x04" not in actual
    assert len(pdf.pages) == 1
    content = page_content(pdf.pages[1])
    assert content.count(b"/ActualText") > 6
    assert content.count(b" BDC") == content.count(b"EMC")


def test_automatic_page_break_preserves_original_total_page_substitution_and_semantic_scopes():
    from fpdf.line_break import TotalPagesSubstitutionFragment

    Base = safe_pdf_class()

    class PagedPDF(Base):
        def footer(self):
            self.set_y(-12)
            self.set_font("Helvetica", "", 9)
            self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="C")

    pdf = PagedPDF(format="A4", unit="mm")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    before = "Before break — अधिवक्ता की फीस ₹ 250.00"
    after = "After break — अधिवक्ता की फीस ₹ 350.00"
    fragments = list(pdf._parse_chars("Page {nb}", markdown=False))
    substitutions = [f for f in fragments if isinstance(f, TotalPagesSubstitutionFragment)]
    assert len(substitutions) == 1
    assert type(substitutions[0]) is TotalPagesSubstitutionFragment
    pdf.multi_cell(0, 6, before, new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(pdf.h - pdf.b_margin - 1)
    pdf.multi_cell(0, 6, after, new_x="LMARGIN", new_y="NEXT")
    body = bytes(pdf.output())
    doc = pdfium.PdfDocument(body)
    text = []
    try:
        for index in range(len(doc)):
            page = doc[index]
            chars = page.get_textpage()
            try:
                text.append(chars.get_text_range())
            finally:
                chars.close()
                page.close()
    finally:
        doc.close()
    assert len(text) == 2
    assert compact(before) in compact(text[0])
    assert compact(after) in compact(text[1])
    assert compact("Page 1 of 2") in compact(text[0])
    assert compact("Page 2 of 2") in compact(text[1])
    assert "{nb}" not in "".join(text)
    assert "\x04" not in "".join(text)
    for page in pdf.pages.values():
        content = page_content(page)
        assert content.count(b" BDC") == content.count(b"EMC")
