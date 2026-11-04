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
    # Ordinary Latin has a complete native ToUnicode map and keeps its physical
    # character geometry. ActualText is only the complex-cluster recovery path.
    # The independent full extracted-source assertion above covers both paths.
    assert logical_fragments
    assert all(fragment in source for fragment in logical_fragments)
    assert "अधिवक्ता" in "".join(logical_fragments)
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
    spans = re.findall(rb"/Span <</ActualText <([0-9A-F]+)>>> BDC", content)
    assert [bytes.fromhex(value.decode()).decode("utf-16") for value in spans] == ["अधिवक्ता"] * 6
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


@pytest.mark.parametrize(
    "family,style,size,source,minimum_width",
    (
        ("Times", "B", 14, "IN THE HIGH COURT OF DELHI AT NEW DELHI", 200),
        ("Helvetica", "", 9, "INR 1,23,45,678.00", 50),
    ),
)
def test_native_text_retains_independent_physical_character_geometry(
    family, style, size, source, minimum_width
):
    from tests.pdf_legibility import assert_legible

    pdf = document()
    pdf.set_font(family, style, size)
    pdf.cell(0, 8, source)
    body = bytes(pdf.output())
    rendered = assert_legible(body)
    assert source in rendered.text
    doc = pdfium.PdfDocument(body)
    page = doc[0]
    text = page.get_textpage()
    try:
        actual = text.get_text_range()
        start = actual.index(source)
        boxes = [text.get_charbox(start + index) for index in range(len(source))]
        assert max(box[2] for box in boxes) - min(box[0] for box in boxes) > minimum_width
        assert len({box for box in boxes}) == len(source)
        assert boxes[-1][0] > boxes[0][2] + minimum_width / 2
    finally:
        text.close()
        page.close()
        doc.close()


@pytest.mark.parametrize("family", ("Helvetica", "Times", "Courier"))
def test_native_gapped_cluster_mapping_keeps_literal_source_without_actualtext(family):
    pdf = document()
    pdf.set_font(family, "", 12)
    source = "office affine fi fl — Cafe\u0301 and nai\u0308ve ₹ 250.50"
    infos, _ = pdf.current_font.perform_harfbuzz_shaping(source, pdf.font_size_pt, pdf.text_shaping)
    clusters = [int(info.cluster) for info in infos]
    assert len(clusters) < len(source)  # Real ligature/combining cluster gap.
    pdf.multi_cell(0, 8, source, new_x="LMARGIN", new_y="NEXT")
    body = bytes(pdf.output())
    assert compact(source) in compact(extracted(body))
    assert "\x04" not in extracted(body)
    assert b"/ActualText" not in page_content(pdf.pages[1])


@pytest.mark.parametrize(
    "ink,background,legible",
    (
        ((0, 0, 0), (255, 255, 255), True),
        ((180, 180, 180), (255, 255, 255), False),
        ((17, 24, 39), (17, 24, 39), False),
        ((255, 255, 255), (17, 24, 39), True),
    ),
)
def test_physical_narrow_glyph_contrast_keeps_positive_and_negative_controls(
    ink, background, legible
):
    from tests.pdf_legibility import illegible_runs, render

    pdf = document()
    pdf.set_font("Helvetica", "", 14)
    pdf.set_fill_color(*background)
    pdf.rect(9, 9, 120, 18, style="F")
    pdf.set_text_color(*ink)
    source = "I lIl Sample — अधिवक्ता की फीस"
    pdf.set_xy(12, 16)
    pdf.multi_cell(0, 6, source, new_x="LMARGIN", new_y="NEXT")
    rendered = render(bytes(pdf.output()))
    assert source in rendered.text
    assert rendered.runs
    assert (illegible_runs(rendered) == []) is legible


@pytest.mark.parametrize("white_edge", ("top", "left"))
def test_touching_white_border_does_not_replace_dark_cell_background(white_edge):
    from PIL import Image, ImageDraw

    from tests.pdf_legibility import run_contrast

    ink = (17, 24, 39)
    with Image.new("RGB", (70, 50), ink) as image:
        draw = ImageDraw.Draw(image)
        if white_edge == "top":
            draw.line((9, 9, 40, 9), fill=(255, 255, 255))
        else:
            draw.line((9, 9, 9, 30), fill=(255, 255, 255))
        assert run_contrast(image, (10, 10, 40, 30), ink) == 1.0


@pytest.mark.parametrize(
    "clusters,complete",
    (
        ([], False),
        ([1], False),
        ([1, 2], False),
        ([0, 0], False),
        ([0, 2, 1], False),
        ([0], True),
        ([0, 2, 5], True),
    ),
)
def test_native_cluster_classification_requires_a_complete_known_prefix(clusters, complete):
    from caseops_api.services.pdf_fonts import _complete_native_cluster_map

    result = _complete_native_cluster_map(clusters)
    assert result is complete


def test_actual_leading_joiner_keeps_original_logical_source():
    source = "\u200dA"
    pdf = document()
    pdf.multi_cell(0, 8, source, new_x="LMARGIN", new_y="NEXT")
    body = bytes(pdf.output())
    actual = extracted(body)
    assert source in actual
