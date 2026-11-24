"""Pure checks behind OCR & Translate (FT-105, FT-107; SEC-025 support)."""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from caseops_api.services import google_translation, sarvam_document_ai
from caseops_api.services.document_rendition_pipeline import (
    usable_native_text,
    validate_ocr_page,
)
from caseops_api.services.legal_translation_checks import (
    batch_segments,
    check_translation,
    missing_details,
    number_tokens,
    segment_paragraphs,
    split_paragraphs,
)


def test_devanagari_digits_and_indian_grouping_compare_equal() -> None:
    assert number_tokens("₹५,००,००० दिनांक १२.०३.२०२३") == number_tokens(
        "Rs. 500000 dated 12.03.2023"
    )
    assert check_translation("धारा ३०२ और ४२०", "Sections 302 and 420") == []


def test_changed_case_number_amount_and_reporter_are_flagged() -> None:
    source = "In (2023) 4 SCC 123, CNR DLHC010012342023, costs of Rs. 5,00,000 were imposed."
    translated = "(2023) 4 एससीसी 123 में, लागत लगाई गई।"
    flags = check_translation(source, translated)
    assert {"number_missing", "identifier_changed", "citation_abbreviation_changed"} <= set(flags)
    details = missing_details(source, translated)
    assert details["missing_numbers"] == ["500000"]
    assert details["missing_identifiers"] == ["DLHC010012342023"]
    assert details["missing_abbreviations"] == ["CNR", "SCC"]


def test_added_number_and_omission_are_flagged() -> None:
    source = (
        "The respondent shall file a reply within the time granted by this Court today, "
        "with an advance copy to the petitioner."
    )
    assert "number_added" in check_translation(source, "Reply within 30 days.")
    assert "possible_omission" in check_translation(source, "Reply.")
    assert check_translation(source, "") == ["empty_translation"]
    assert "unclear_source" in check_translation("Order � dated", "Order dated")


def test_paragraph_segmentation_keeps_order_and_limits() -> None:
    long_paragraph = " ".join(f"Sentence {index} of the order." for index in range(400))
    paragraphs = ["First paragraph.", long_paragraph, "Last paragraph."]
    segments = segment_paragraphs(paragraphs, limit=500)
    assert all(len(segment.text) <= 500 for segment in segments)
    assert [segment.paragraph_index for segment in segments] == sorted(
        segment.paragraph_index for segment in segments
    )
    rejoined = " ".join(s.text for s in segments if s.paragraph_index == 1)
    assert rejoined.split() == long_paragraph.split()
    batches = batch_segments(segments, max_chars=1200, max_items=3)
    assert all(sum(len(s.text) for s in batch) <= 1200 or len(batch) == 1 for batch in batches)
    assert all(len(batch) <= 3 for batch in batches)
    assert [s for batch in batches for s in batch] == segments
    assert split_paragraphs("a\n\n  \n\nb\nc") == ["a", "b\nc"]


def test_native_text_layer_quality_gate() -> None:
    english = "The petition is allowed and the impugned order is set aside. " * 3
    assert usable_native_text(english, language="en") == (True, "")
    assert usable_native_text("Page 1", language="en") == (False, "no_text_layer")
    # Legacy Kruti Dev style text extracts as Latin garble for a Hindi document.
    garble = "vkns'k fnukad dks ikfjr fd;k x;kA ;kfpdkdrkZ dks Hkqxrku djus dk funsZ'k " * 2
    assert usable_native_text(garble, language="hi") == (
        False, "legacy_font_encoding_suspected",
    )
    assert usable_native_text("�" * 10 + english, language="en") == (
        False, "unreliable_text_layer",
    )


def test_ocr_page_validation_never_invents_text() -> None:
    empty = {"text": "", "reasons": []}
    validate_ocr_page(empty)
    assert (empty["status"], empty["reasons"]) == ("review", ["empty_page"])
    low = {"text": "आदेश " * 20, "reasons": [], "low_confidence_blocks": 2}
    validate_ocr_page(low)
    assert low["status"] == "review" and "low_confidence" in low["reasons"]
    assert low["text"] == "आदेश " * 20


def _zip(members: dict[str, object]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, json.dumps(payload, ensure_ascii=False))
    return buffer.getvalue()


def test_sarvam_output_maps_pages_and_reports_missing_ones() -> None:
    archive = _zip({
        "manifest.json": {"pages": 3},
        "x/metadata/page_001.json": {"blocks": [
            {"tag": "heading", "text": "ORDER", "confidence": 99},
            {"tag": "table", "text": "| Item | Amount |\n| Fee | 500 |", "confidence": 0.4},
        ]},
        "x/metadata/page_003.json": {"text": "third"},
        "x/metadata/page_009.json": {"text": "out of range"},
    })
    pages = sarvam_document_ai.parse_output_archive(archive, page_count=3)
    assert sorted(pages) == [1, 3]
    assert pages[1].blocks[0]["tag"] == "heading"
    assert pages[1].min_confidence == pytest.approx(0.4)
    assert pages[1].low_confidence_blocks == 1
    assert "| Fee | 500 |" in pages[1].text
    assert pages[3].text == "third"


def test_sarvam_output_falls_back_to_page_list_and_rejects_bad_archives() -> None:
    archive = _zip({"x/x.json": {"pages": [
        {"page_number": 2, "blocks": [{"text": "second"}]},
        {"page_number": 1, "blocks": [{"text": "first"}]},
    ]}})
    pages = sarvam_document_ai.parse_output_archive(archive, page_count=2)
    assert (pages[1].text, pages[2].text) == ("first", "second")
    with pytest.raises(sarvam_document_ai.SarvamError) as error:
        sarvam_document_ai.parse_output_archive(b"not a zip", page_count=1)
    assert error.value.code == "bad_output"


@pytest.mark.parametrize(
    ("status_code", "message", "code", "retryable"),
    [
        (429, "Rate limit", "rate_limited", True),
        (403, "User Rate Limit Exceeded", "rate_limited", True),
        (403, "Permission denied", "auth", False),
        (400, "Model not found in location", "model_unavailable", False),
        (400, "Unsupported language pair", "unsupported_language", False),
        (503, "Backend error", "unavailable", True),
    ],
)
def test_google_errors_are_classified(
    status_code: int, message: str, code: str, retryable: bool,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": message}})

    client = google_translation.GoogleTranslationClient(
        project_id="p", location="us-central1", base_url="https://translate.googleapis.com",
        timeout_seconds=5, http=httpx.Client(transport=httpx.MockTransport(handler)),
        token_provider=lambda: "t",
    )
    with pytest.raises(google_translation.GoogleTranslationError) as error:
        client.translate(["text"], source="en", target="hi")
    assert (error.value.code, error.value.retryable) == (code, retryable)


@pytest.mark.parametrize(
    ("status_code", "code", "charge_possible"),
    [(403, "auth", False), (413, "file_too_large", False), (422, "invalid_file", False),
     (429, "rate_limited", False), (500, "unavailable", True)],
)
def test_sarvam_submit_errors_are_classified(
    status_code: int, code: str, charge_possible: bool,
) -> None:
    client = sarvam_document_ai.SarvamDocumentClient(
        api_key="k", base_url="https://api.sarvam.ai", timeout_seconds=5,
        http=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json={"title": "x"}),
        )),
    )
    with pytest.raises(sarvam_document_ai.SarvamError) as error:
        client.submit_parse(
            filename="a.pdf", content=b"%PDF", content_type="application/pdf", language="hi",
        )
    assert (error.value.code, error.value.charge_possible) == (code, charge_possible)


def test_sarvam_rejects_unsupported_language_without_a_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    client = sarvam_document_ai.SarvamDocumentClient(
        api_key="k", base_url="https://api.sarvam.ai", timeout_seconds=5,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(sarvam_document_ai.SarvamError) as error:
        client.submit_parse(
            filename="a.pdf", content=b"%PDF", content_type="application/pdf", language="fr",
        )
    assert error.value.code == "unsupported_language"
