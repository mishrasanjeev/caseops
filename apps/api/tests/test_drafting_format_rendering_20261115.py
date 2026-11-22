"""Real output contracts; synthetic documents contain no customer content."""
from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pypdfium2 as pdfium
import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from caseops_api.services.court_format_profiles import resolve_profile
from caseops_api.services.draft_pdf_export import render_pdf_bytes
from caseops_api.services.drafting import _render_loaded_version_docx
from caseops_api.services.drafting_format_blocks import (
    ExecutionTable,
    FormatStructureError,
    document_blocks,
)
from caseops_api.services.drafting_formats import SOURCE_SHA256, format_manifest
from tests.test_pdf_unicode_fidelity_20261104 import compact, extracted


def _render(body, *, profile=None, reference=None, review_required=False):
    return render_pdf_bytes(
        profile=profile or resolve_profile(explicit_key="generic"),
        title="Internal ledger title", matter_title="Synthetic matter", matter_code="FORMAT-QA",
        draft_type="other", revision=7, status_label="approved", body=body,
        citations=[], review_required=review_required,
        created_at=datetime(2026, 11, 15, tzinfo=UTC),
        template_manifest={} if reference is None else {"presentation_reference": reference},
    )


def _word(body, *, reference=None, review_required=False):
    version = SimpleNamespace(
        id="synthetic-version", revision=7, body=body, verified_citation_count=1,
        citations_json="[]", source_manifest_json="[]",
        template_manifest_json=json.dumps(
            {} if reference is None else {"presentation_reference": reference},
        ),
    )
    draft = SimpleNamespace(
        title="Internal ledger title", draft_type="other",
        status="draft" if review_required else "approved",
        review_required=review_required, current_version_id=version.id, versions=[version],
    )
    data, name = _render_loaded_version_docx(
        draft=draft, target_label="Synthetic matter", version_id=version.id,
        court_name="Delhi High Court",
    )
    return data, name


def _execution_body():
    source = Path(__file__).parent / "fixtures" / "drafting" / "reference_formats.json"
    return json.loads(source.read_text(encoding="utf-8"))["render_samples"]["execution_application"]


def test_execution_table_parse_retains_source_labels_values_and_complete_original_lines():
    body = _execution_body()
    blocks = list(document_blocks(body, format_manifest("execution_application")))
    tables = [block for block in blocks if isinstance(block, ExecutionTable)]
    assert len(tables) == 1 and len(tables[0].rows) == 10
    table = tables[0]
    assert table.rows[0].label == "1. Suit number:"
    assert table.rows[0].ordinal == "1."
    assert table.rows[0].particular == " Suit number:"
    assert table.rows[0].value == " [actual number]"
    assert table.rows[9].label == "10. Court assistance requested:"
    rebuilt = "\n".join(
        "\n".join(block.source_lines) if isinstance(block, ExecutionTable) else block.text
        for block in blocks
    )
    assert rebuilt == body
    assert not any(isinstance(block, ExecutionTable) for block in document_blocks(body, None))


@pytest.mark.parametrize("numbering", ["period", "parenthesis", "wrapped"])
def test_execution_table_keeps_supported_row_numbers_and_multiline_values_verbatim(
    numbering, tmp_path,
):
    lines = _execution_body().split("\n")
    for index, line in enumerate(lines):
        if not line[:1].isdigit():
            continue
        number, rest = line.split(". ", 1)
        prefix = {"period": f"{number}.", "parenthesis": f"{number})", "wrapped": f"({number})"}
        lines[index] = prefix[numbering] + " " + rest
    body = "\n".join(lines).replace(
        "[dates and results]", "[First supplied application]\n  Further supplied result; ₹0.50.",
    )
    blocks = list(document_blocks(body, format_manifest("execution_application")))
    table = next(block for block in blocks if isinstance(block, ExecutionTable))
    assert table.rows[5].value == (
        " [First supplied application]\n  Further supplied result; ₹0.50."
    )
    rebuilt = "\n".join(
        "\n".join(block.source_lines) if isinstance(block, ExecutionTable) else block.text
        for block in blocks
    )
    assert rebuilt == body
    word_data, name = _word(body, reference=format_manifest("execution_application"))
    document = Document(io.BytesIO(word_data))
    table = document.tables[0]
    assert len(table.columns) == 3 and len(table.rows) == 10
    assert table.rows[-1].cells[0].text == {
        "period": "10.", "parenthesis": "10)", "wrapped": "(10)",
    }[numbering]
    assert table.rows[-1].cells[0].paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    word_text = "".join(node.text or "" for node in document.element.body.iter(qn("w:t")))
    assert compact(word_text) == compact(body)
    pdf_data = _render(body, reference=format_manifest("execution_application"))
    assert compact(body) in compact(extracted(pdf_data))
    (tmp_path / name).write_bytes(word_data)
    (tmp_path / (numbering + ".pdf")).write_bytes(pdf_data)


@pytest.mark.parametrize("damage", [
    "missing_heading", "duplicate_heading", "missing_prayer", "missing_row", "duplicate_row",
    "wrong_order", "empty_label", "extra_row", "oversized_label", "unclosed_parenthesis",
    "malformed_continuation", "large_row_number",
])
def test_execution_table_rejects_ambiguous_structure_without_reflecting_private_values(damage):
    body = _execution_body().replace("[actual number]", "PRIVATE-EXECUTION-VALUE")
    if damage == "missing_heading":
        body = body.replace("PARTICULARS OF EXECUTION\n", "")
    elif damage == "duplicate_heading":
        body += "\nPARTICULARS OF EXECUTION"
    elif damage == "missing_prayer":
        body = body.replace("\nPRAYER\n", "\n[Missing prayer heading]\n")
    elif damage == "missing_row":
        body = "\n".join(line for line in body.split("\n") if not line.startswith("5. "))
    elif damage == "duplicate_row":
        body = body.replace("5. Payment or satisfaction:", "4. Payment or satisfaction:")
    elif damage == "wrong_order":
        body = body.replace("1. Suit number:", "2. Suit number:")
    elif damage == "empty_label":
        body = body.replace("1. Suit number:", "1. :")
    elif damage == "extra_row":
        body = body.replace("\nPRAYER\n", "\n11. Unknown extra row: [value]\nPRAYER\n")
    elif damage == "oversized_label":
        body = body.replace("1. Suit number:", "1. " + "X" * 241 + ":")
    elif damage == "unclosed_parenthesis":
        body = body.replace("1. Suit number:", "(1. Suit number:")
    elif damage == "malformed_continuation":
        body = body.replace("2. Parties:", "2. : [ambiguous label]\n2. Parties:")
    else:
        body = body.replace("\nPRAYER\n", "\n100. Unknown extra row: [value]\nPRAYER\n")
    with pytest.raises(FormatStructureError) as error:
        list(document_blocks(body, format_manifest("execution_application")))
    assert "PRIVATE-EXECUTION-VALUE" not in str(error.value)


def test_invalid_execution_table_never_starts_either_document_renderer(monkeypatch):
    from fastapi import HTTPException

    calls = []
    monkeypatch.setattr("docx.Document", lambda: calls.append("word"))
    monkeypatch.setattr(
        "caseops_api.services.pdf_layout.safe_pdf_class", lambda: calls.append("pdf"),
    )
    reference = format_manifest("execution_application")
    with pytest.raises(HTTPException) as word_error:
        _word("PRIVATE-MISSING-TABLE", reference=reference)
    assert word_error.value.status_code == 422
    with pytest.raises(FormatStructureError):
        _render("PRIVATE-MISSING-TABLE", reference=reference)
    assert calls == []


def test_execution_value_spans_pages_without_lost_reordered_or_clipped_text(tmp_path):
    source = _execution_body()
    continuation = "\n".join(
        f"Entry {index}: supplied history; जमा ₹0.50. No legal proposition."
        for index in range(120)
    )
    body = source.replace("[dates and results]", continuation)
    reference = format_manifest("execution_application")
    word_data, name = _word(body, reference=reference)
    document = Document(io.BytesIO(word_data))
    word_text = "".join(node.text or "" for node in document.element.body.iter(qn("w:t")))
    assert compact(word_text) == compact(body)
    profile = resolve_profile(explicit_key="delhi_hc")
    pdf_data = _render(body, profile=profile, reference=reference)
    (tmp_path / name).write_bytes(word_data)
    (tmp_path / "execution-multipage.pdf").write_bytes(pdf_data)
    content = []
    with pdfium.PdfDocument(pdf_data) as pdf:
        assert len(pdf) >= 3
        for index in range(len(pdf)):
            page = pdf[index]
            text = page.get_textpage()
            try:
                actual = compact(text.get_text_range())
                footer = f"Page{index + 1}of{len(pdf)}"
                assert footer in actual
                content.append(actual.replace(footer, ""))
                boxes = [text.get_charbox(i) for i in range(text.count_chars())
                         if text.get_text_range(i, 1).strip()]
                assert min(box[0] for box in boxes) >= profile.margin_left_mm * 72 / 25.4 - 1
                assert max(box[2] for box in boxes) <= (
                    210 - profile.margin_right_mm
                ) * 72 / 25.4 + 1
            finally:
                text.close()
                page.close()
    assert compact(body) in "".join(content)


def test_real_word_document_uses_a4_body_caption_headings_and_signature_alignment(tmp_path):
    body = (
        "IN THE COURT OF [confirmed court]\nBETWEEN\n[Supplied parties]\nFACTS\n"
        "1. Amount ₹0.50; आशा.\nPRAYER\n(a) Supplied relief.\nVERIFICATION\n"
        "[Actual ranges]\nDeponent"
    )
    reference = format_manifest("bail")
    data, name = _word(body, reference=reference)
    document = Document(io.BytesIO(data))
    assert "\n".join(paragraph.text for paragraph in document.paragraphs) == body
    assert document.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    prayer = next(paragraph for paragraph in document.paragraphs if paragraph.text == "PRAYER")
    assert prayer.paragraph_format.keep_with_next is True
    assert prayer.runs[0].bold is True
    assert document.paragraphs[-1].alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert round(document.sections[0].page_width.mm, 1) == 210
    assert round(document.sections[0].page_height.mm, 1) == 297
    assert document.core_properties.identifier == SOURCE_SHA256
    footer_xml = document.sections[0].footer.paragraphs[0]._p.xml
    assert 'w:instr="PAGE"' in footer_xml and 'w:instr="NUMPAGES"' in footer_xml
    (tmp_path / name).write_bytes(data)
    pdf_data = _render(
        body, profile=resolve_profile(explicit_key="delhi_hc"), reference=reference,
    )
    assert compact(body) in compact(extracted(pdf_data))
    with pdfium.PdfDocument(pdf_data) as pdf:
        assert pdf.get_metadata_dict()["Title"] == "Internal ledger title"
    (tmp_path / "unicode-court.pdf").write_bytes(pdf_data)


@pytest.mark.parametrize("instrument,first_heading,second_heading,roles", [
    ("Sale deed", "BETWEEN", "AND", "Vendor\nVendee"),
    ("Mortgage deed", "BY", "IN FAVOUR OF", "Mortgagor\nMortgagee"),
    ("Partnership deed", "BETWEEN", "AND", "Partner\nPartner"),
    ("Dissolution of partnership", "BETWEEN", "AND", "Partner\nPartner"),
    ("Relinquishment deed", "BY", "IN FAVOUR OF", "Releasor\nReleasee"),
    ("Gift deed", "BETWEEN", "AND", "Donor\nDonee"),
])
def test_each_deed_word_and_pdf_keeps_its_own_text_and_has_no_automatic_court_caption(
    instrument, first_heading, second_heading, roles, tmp_path,
):
    body = (
        f"{instrument}\n{first_heading}\n[Supplied first party]\n{second_heading}\n"
        "[Supplied second party]\nRECITALS\n1. Supplied facts; ₹0.50.\n"
        f"OPERATIVE TERMS\n[Agreed terms]\nSCHEDULE\n[Supplied schedule]\nEXECUTION\n{roles}"
    )
    reference = format_manifest("conveyancing_deed", facts={"instrument_type": instrument})
    word_data, name = _word(body, reference=reference)
    document = Document(io.BytesIO(word_data))
    assert "\n".join(paragraph.text for paragraph in document.paragraphs) == body
    assert document.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    for heading in (first_heading, second_heading):
        paragraph = next(item for item in document.paragraphs if item.text == heading)
        assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert "Internal ledger title" not in "\n".join(
        paragraph.text for paragraph in document.paragraphs
    )
    pdf_data = _render(body, profile=resolve_profile(explicit_key="delhi_hc"), reference=reference)
    text = extracted(pdf_data)
    assert compact(body) in compact(text)
    assert "IN THE HIGH COURT OF DELHI" not in text
    assert "PRAYER" not in text and "VERIFICATION" not in text
    assert "Lawyer review required before signing, registration or service." in text
    assert b"/FontFile2" in pdf_data
    (tmp_path / name).write_bytes(word_data)
    (tmp_path / (name + ".pdf")).write_bytes(pdf_data)


def test_wrapped_caption_is_not_orphaned_above_its_first_body_line(tmp_path):
    heading = "APPLICATION FOR " + "SYNTHETIC SUBSTANTIVE RELIEF " * 7 + "CAPTION-END"
    assert len(heading) <= 240
    body = "\n".join([
        *(f"{i}. Synthetic short paragraph." for i in range(40)), heading, "BODY-ANCHOR",
    ])
    data = _render(body, reference=format_manifest("bail"))
    (tmp_path / "wrapped-caption.pdf").write_bytes(data)
    with pdfium.PdfDocument(data) as document:
        assert len(document) >= 2
        pages = []
        for index in range(len(document)):
            page = document[index]
            text = page.get_textpage()
            try:
                pages.append(text.get_text_range())
            finally:
                text.close()
                page.close()
    heading_page = next(index for index, text in enumerate(pages) if "APPLICATION FOR" in text)
    assert "CAPTION-END" in pages[heading_page]
    assert "BODY-ANCHOR" in pages[heading_page]
    without_footers = "".join(pages).replace("Page 1 of 2", "").replace("Page 2 of 2", "")
    assert compact(body) in compact(without_footers)


def test_new_and_legacy_review_warnings_are_retained_once_in_each_word_document(tmp_path):
    body = "GIFT DEED\nRECITALS\n[Supplied facts]\nEXECUTION\n[Signature]"
    reference = format_manifest("conveyancing_deed", facts={"instrument_type": "Gift deed"})
    for value in (None, reference):
        data, _ = _word(body, reference=value, review_required=True)
        (tmp_path / ("review-reference.docx" if value else "review-legacy.docx")).write_bytes(data)
        paragraphs = [paragraph.text for paragraph in Document(io.BytesIO(data)).paragraphs]
        assert sum("review required" in text.lower() for text in paragraphs) == 1
        assert body in "\n".join(paragraphs)
    legacy, _ = _word(body)
    assert Document(io.BytesIO(legacy)).paragraphs[0].text == "Internal ledger title"
    legacy_pdf = extracted(_render(body))
    assert "Internal ledger title" in legacy_pdf
    assert "Revision 7" in legacy_pdf


@pytest.mark.parametrize("template_type", [
    "execution_application", "succession_certificate", "legal_notice_reply",
])
def test_specific_manual_form_particulars_survive_real_word_and_pdf_output(template_type, tmp_path):
    source = Path(__file__).parent / "fixtures" / "drafting" / "reference_formats.json"
    body = json.loads(source.read_text(encoding="utf-8"))["render_samples"][template_type]
    reference = format_manifest(template_type)
    word_data, name = _word(body, reference=reference)
    document = Document(io.BytesIO(word_data))
    if template_type == "execution_application":
        word_text = "".join(node.text or "" for node in document.element.body.iter(qn("w:t")))
        assert compact(word_text) == compact(body)
        assert len(document.tables) == 1 and len(document.tables[0].rows) == 10
        assert len(document.tables[0].columns) == 3
        assert document.tables[0].rows[0].cells[0].text == "1."
        assert document.tables[0].rows[0].cells[1].text == " Suit number:"
        assert document.tables[0].rows[0].cells[2].text == " [actual number]"
    else:
        assert "\n".join(paragraph.text for paragraph in document.paragraphs) == body
    profile = resolve_profile(
        explicit_key="generic" if template_type == "legal_notice_reply" else "delhi_hc",
    )
    pdf_data = _render(body, profile=profile, reference=reference)
    pages = []
    with pdfium.PdfDocument(pdf_data) as pdf:
        for index in range(len(pdf)):
            page = pdf[index]
            text = page.get_textpage()
            try:
                footer = profile.page_number_format.format(n=index + 1, total=len(pdf))
                main_text, separator, page_footer = text.get_text_range().rstrip().rpartition("\n")
                assert separator and page_footer == footer
                pages.append(main_text)
            finally:
                text.close()
                page.close()
    assert compact(body) in compact("".join(pages))
    if template_type == "execution_application":
        assert len(pages) >= 2
        assert sum("DecreeHolderAdvocate" in compact(page) for page in pages) == 1
        signature = {
            p.text: p for p in document.paragraphs if p.text in {"Decree Holder", "Advocate"}
        }
        assert signature["Decree Holder"].paragraph_format.keep_with_next is True
        assert signature["Advocate"].paragraph_format.keep_with_next is False
    (tmp_path / name).write_bytes(word_data)
    (tmp_path / (template_type + ".pdf")).write_bytes(pdf_data)


@pytest.mark.parametrize("kind", ["word", "pdf"])
def test_corrupted_saved_format_reference_refuses_output_instead_of_relabelling(kind):
    reference = format_manifest("bail")
    reference["source_sha256"] = "unknown"
    if kind == "word":
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as error:
            _word("Synthetic body", reference=reference)
        assert error.value.status_code == 422
    else:
        with pytest.raises(ValueError):
            _render("Synthetic body", reference=reference)
