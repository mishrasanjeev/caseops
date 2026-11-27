"""OCR & Translate in further Indian languages (Ram BUG-005, 2026-11-26).

J04/J16, M03/M17, MOD-TS-002/003, US-066, FT-105/FT-107. Every provider call
goes to the in-process fakes of ``test_document_renditions_20261123``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from caseops_api.schemas.document_renditions import SUPPORTED_TRANSLATION_PAIRS
from caseops_api.services.document_rendition_pipeline import usable_native_text
from caseops_api.services.legal_translation_checks import normalise_digits
from tests.test_document_renditions_20261123 import (
    ENGLISH_PAGE,
    _detail,
    _latest,
    _pdf,
    _setup,
    _start,
    _upload,
    _verify_costs,
    _versions,
    providers,  # noqa: F401 - pytest fixture
)

# One short court-order sentence per language: an order date and Section 138,
# in the script's own digits where courts commonly use them.
SAMPLES = {
    "gu": "આદેશ તારીખ ૧૨.૦૩.૨૦૨૩ ના રોજ પસાર કરવામાં આવ્યો. કલમ ૧૩૮ હેઠળ કેસ.",
    "ta": "ஆணை 12.03.2023 அன்று பிறப்பிக்கப்பட்டது. பிரிவு 138 இன் கீழ் வழக்கு.",
    "te": "ఉత్తర్వు 12.03.2023 న జారీ చేయబడింది. సెక్షన్ 138 కింద కేసు.",
    "kn": "ಆದೇಶವನ್ನು 12.03.2023 ರಂದು ಹೊರಡಿಸಲಾಗಿದೆ. ಸೆಕ್ಷನ್ 138 ಅಡಿಯಲ್ಲಿ ಪ್ರಕರಣ.",
    "bn": "আদেশ ১২.০৩.২০২৩ তারিখে দেওয়া হয়েছে। ধারা ১৩৮ অনুযায়ী মামলা।",
    "ml": "ഉത്തരവ് 12.03.2023 ന് പുറപ്പെടുവിച്ചു. വകുപ്പ് 138 പ്രകാരം കേസ്.",
    "pa": "ਹੁਕਮ 12.03.2023 ਨੂੰ ਜਾਰੀ ਕੀਤਾ ਗਿਆ। ਧਾਰਾ 138 ਅਧੀਨ ਕੇਸ।",
}
# Read (OCR) only: Google lists Odia as experimental and Assamese as unsupported
# for the Translation LLM, and Urdu translation PDFs need a right-to-left font.
OCR_ONLY = {
    "od": "ଆଦେଶ ୧୨.୦୩.୨୦୨୩ ରେ ଜାରି କରାଯାଇଥିଲା। ଧାରା ୧୩୮ ଅଧୀନରେ ମାମଲା।",
    "ur": "حکم 12.03.2023 کو جاری کیا گیا۔ دفعہ 138 کے تحت مقدمہ۔",
    "as": "আদেশ ১২.০৩.২০২৩ তাৰিখে জাৰি কৰা হৈছিল। ধাৰা ১৩৮ অনুসৰি গোচৰ।",
}
ENGLISH_ORDER = "The order was passed on 12.03.2023. Case under Section 138."
NEW_LANGUAGES = (*SAMPLES, *OCR_ONLY)


@pytest.mark.parametrize("language", sorted(SAMPLES))
def test_scanned_order_is_read_in_its_language_and_translated_to_english(
    client: TestClient,
    providers,  # noqa: F811
    language: str,
) -> None:
    sarvam, google = providers
    sarvam.text_for = lambda _job, _page: SAMPLES[language]
    google.transform = lambda _text: ENGLISH_ORDER
    _verify_costs()
    _, token, matter_id = _setup(client)
    attachment_id = _upload(client, token, matter_id, f"order-{language}.pdf", _pdf([None]))

    started = _start(client, token, matter_id, attachment_id, language, "en")
    assert started.status_code == 202, started.text

    assert [item["language"] for item in sarvam.submissions] == [f"{language}-IN"]
    listing = _versions(client, token, matter_id, attachment_id)
    ocr = _latest(listing, "ocr")
    translation = _latest(listing, "translation")
    assert ocr["status"] == "ocr_completed", (ocr["error_code"], ocr["error_message"])
    assert translation["status"] == "translation_completed", (
        translation["error_code"],
        translation["error_message"],
    )
    sent = google.requests[0]
    assert (sent["sourceLanguageCode"], sent["targetLanguageCode"]) == (language, "en")
    detail = _detail(client, token, matter_id, attachment_id, translation["id"])
    paragraph = detail["pages"][0]["paragraphs"][0]
    assert paragraph["source"] == SAMPLES[language]
    # Native digits (Gujarati, Bengali) equal their ASCII translation: no flag.
    assert paragraph["flags"] == []


@pytest.mark.parametrize("language", sorted(SAMPLES))
def test_english_order_translates_into_each_language_with_a_readable_pdf(
    client: TestClient,
    providers,  # noqa: F811
    language: str,
) -> None:
    sarvam, google = providers
    sarvam.text_for = lambda _job, _page: ENGLISH_ORDER
    google.transform = lambda _text: SAMPLES[language]
    _verify_costs()
    _, token, matter_id = _setup(client)
    attachment_id = _upload(client, token, matter_id, "order-en.pdf", _pdf([None]))

    started = _start(client, token, matter_id, attachment_id, "en", language)
    assert started.status_code == 202, started.text

    translation = _latest(_versions(client, token, matter_id, attachment_id), "translation")
    assert translation["status"] == "translation_completed", (
        translation["error_code"],
        translation["error_message"],
    )
    assert translation["has_output_file"] is True
    pdf = client.get(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/renditions/"
        f"{translation['id']}/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pdf.status_code == 200, pdf.text
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf.content)
    text = "".join(page.get_textpage().get_text_range() for page in document)
    # PDFium drops the space at a line-wrap point, so compare without spacing:
    # every character must still render and extract, in order.
    assert "".join(SAMPLES[language].split()) in "".join(text.split()), text


@pytest.mark.parametrize("language", sorted(OCR_ONLY))
def test_ocr_only_language_is_read_but_never_sent_for_translation(
    client: TestClient,
    providers,  # noqa: F811
    language: str,
) -> None:
    sarvam, google = providers
    sarvam.text_for = lambda _job, _page: OCR_ONLY[language]
    _verify_costs()
    _, token, matter_id = _setup(client)
    attachment_id = _upload(client, token, matter_id, f"order-{language}.pdf", _pdf([None]))

    assert _start(client, token, matter_id, attachment_id, language, "en").status_code == 422
    assert _start(client, token, matter_id, attachment_id, "en", language).status_code == 422
    assert sarvam.submissions == [] and google.requests == []

    started = _start(client, token, matter_id, attachment_id, language)
    assert started.status_code == 202, started.text
    assert [item["language"] for item in sarvam.submissions] == [f"{language}-IN"]
    listing = _versions(client, token, matter_id, attachment_id)
    ocr = _latest(listing, "ocr")
    assert ocr["status"] == "ocr_completed", (ocr["error_code"], ocr["error_message"])
    detail = _detail(client, token, matter_id, attachment_id, ocr["id"])
    assert detail["pages"][0]["text"] == OCR_ONLY[language]
    assert google.requests == []


def test_readiness_offers_every_ocr_language_and_only_english_pairs(
    client: TestClient,
    providers,  # noqa: F811
) -> None:
    _verify_costs()
    _, token, matter_id = _setup(client)
    attachment_id = _upload(client, token, matter_id, "order.pdf", _pdf([ENGLISH_PAGE]))
    readiness = _versions(client, token, matter_id, attachment_id)["providers"]
    assert readiness["ocr_languages"] == [
        "en",
        "hi",
        "mr",
        "gu",
        "ta",
        "te",
        "kn",
        "bn",
        "ml",
        "pa",
        "od",
        "ur",
        "as",
    ]
    pairs = {(pair["source"], pair["target"]) for pair in readiness["translation_pairs"]}
    assert pairs == SUPPORTED_TRANSLATION_PAIRS
    assert len(pairs) == 18
    assert all("en" in pair for pair in pairs)
    assert not any(language in pair for pair in pairs for language in OCR_ONLY)


def test_a_non_english_pair_is_still_refused(client: TestClient, providers) -> None:  # noqa: F811
    _, token, matter_id = _setup(client)
    attachment_id = _upload(client, token, matter_id, "order.pdf", _pdf([ENGLISH_PAGE]))
    assert _start(client, token, matter_id, attachment_id, "ta", "hi").status_code == 422


@pytest.mark.parametrize("language", [*sorted(SAMPLES), *sorted(OCR_ONLY)])
def test_native_text_in_script_is_used_and_legacy_font_garble_is_sent_to_ocr(
    language: str,
) -> None:
    sample = SAMPLES.get(language) or OCR_ONLY[language]
    assert usable_native_text(sample * 3, language=language) == (True, "")
    # A legacy (non-Unicode) Indic font extracts as Latin letters.
    garble = "Aadesh tarikh 12.03.2023 na roj pasar karvama aavyo. Kalam 138 hethal kes. " * 2
    assert usable_native_text(garble, language=language) == (
        False,
        "legacy_font_encoding_suspected",
    )


@pytest.mark.parametrize(
    ("native", "ascii_digits"),
    [
        ("૧૨.૦૩.૨૦૨૩", "12.03.2023"),  # Gujarati
        ("১২.০৩.২০২৩", "12.03.2023"),  # Bengali
        ("੧੩੮", "138"),  # Gurmukhi
        ("୧୩୮", "138"),  # Oriya
        ("௧௩௮", "138"),  # Tamil
        ("౧౩౮", "138"),  # Telugu
        ("೧೩೮", "138"),  # Kannada
        ("൧൩൮", "138"),  # Malayalam
        ("१३८", "138"),  # Devanagari (unchanged)
    ],
)
def test_every_indic_digit_form_normalises_to_ascii(native: str, ascii_digits: str) -> None:
    assert normalise_digits(native) == ascii_digits


def test_new_languages_are_all_named(client: TestClient) -> None:
    from caseops_api.services.document_renditions import LANGUAGE_NAMES, OCR_LANGUAGES
    from caseops_api.services.sarvam_document_ai import LANGUAGE_CODES

    for language in NEW_LANGUAGES:
        assert language in OCR_LANGUAGES
        assert LANGUAGE_NAMES[language]
        assert LANGUAGE_CODES[language].endswith("-IN")
    assert (LANGUAGE_CODES["od"], LANGUAGE_CODES["ur"], LANGUAGE_CODES["as"]) == (
        "od-IN",
        "ur-IN",
        "as-IN",
    )
