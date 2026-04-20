from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from caseops_api.core.settings import get_settings
from caseops_api.services import ocr as ocr_module
from caseops_api.services.ocr import (
    OcrPageResult,
    OcrResult,
    _apply_page_quality_gate,
    _detect_tesseract_lang,
    ocr_pdf,
    should_fallback_to_ocr,
)


def test_fallback_threshold_triggers_on_short_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_OCR_MIN_CHARS_BEFORE_FALLBACK", "600")
    get_settings.cache_clear()
    assert should_fallback_to_ocr("") is True
    assert should_fallback_to_ocr("   \n\t") is True
    assert should_fallback_to_ocr("short stub text") is True


def test_fallback_threshold_ignores_long_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_OCR_MIN_CHARS_BEFORE_FALLBACK", "600")
    get_settings.cache_clear()
    long_text = "Judgment body paragraph. " * 60  # ~1500 chars
    assert should_fallback_to_ocr(long_text) is False


def test_ocr_pdf_returns_none_when_provider_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CASEOPS_OCR_PROVIDER", "none")
    get_settings.cache_clear()
    dummy = tmp_path / "doc.pdf"
    dummy.write_bytes(b"%PDF-1.4\n%%EOF\n")
    assert ocr_pdf(dummy) is None


def test_ocr_pdf_returns_none_when_backend_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the rapidocr extras are not installed, the fallback returns None
    rather than raising — the ingester treats it as 'no OCR path available'."""
    monkeypatch.setenv("CASEOPS_OCR_PROVIDER", "rapidocr")
    get_settings.cache_clear()
    dummy = tmp_path / "doc.pdf"
    dummy.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with patch("caseops_api.services.ocr._build_backend", side_effect=RuntimeError("nope")):
        assert ocr_pdf(dummy) is None


def test_ocr_result_dataclass_roundtrip() -> None:
    result = OcrResult(
        text="abc",
        provider="rapidocr",
        pages_processed=1,
        pages_total=1,
        truncated=False,
    )
    assert result.text == "abc" and result.provider == "rapidocr"


# ---------------------------------------------------------------
# Sprint Q4 — per-page OCR quality gate.
# ---------------------------------------------------------------


def test_quality_gate_accepts_high_confidence_long_page() -> None:
    """A page at 0.9 conf with plenty of text must pass unchanged."""
    body = "Paragraph one of the judgment. " * 10  # ~300 chars
    gated = _apply_page_quality_gate(
        [OcrPageResult(text=body, confidence=0.9)],
        min_confidence=0.4,
        min_chars=50,
    )
    assert gated[0].accepted is True
    assert gated[0].reject_reason is None


def test_quality_gate_rejects_low_confidence_page() -> None:
    """Confidence below the floor -> rejected, even if long."""
    body = "Looks like real text but OCR was unsure about every token." * 5
    gated = _apply_page_quality_gate(
        [OcrPageResult(text=body, confidence=0.25)],
        min_confidence=0.4,
        min_chars=50,
    )
    assert gated[0].accepted is False
    assert "confidence 0.25" in (gated[0].reject_reason or "")


def test_quality_gate_rejects_too_short_page_even_at_high_confidence() -> None:
    """High conf but only two tokens -> very likely a stamp / seal."""
    gated = _apply_page_quality_gate(
        [OcrPageResult(text="TRUE COPY", confidence=0.95)],
        min_confidence=0.4,
        min_chars=50,
    )
    assert gated[0].accepted is False
    assert "length" in (gated[0].reject_reason or "")


def test_quality_gate_mixed_doc_keeps_only_clean_pages() -> None:
    """A representative real-world mix: 3 clean pages, 1 garbage, 1 short.

    Gate must keep exactly the 3 clean pages and mark the other two
    rejected with the specific reason so the ingester can log it.
    """
    pages = [
        OcrPageResult(text="Para one. " * 20, confidence=0.88),
        OcrPageResult(text="Para two. " * 20, confidence=0.91),
        OcrPageResult(
            text="v vv y a bb c k nmm /// x x", confidence=0.2
        ),  # OCR garbage
        OcrPageResult(text="STAMP", confidence=0.99),  # too short
        OcrPageResult(text="Para five. " * 20, confidence=0.85),
    ]
    gated = _apply_page_quality_gate(
        pages, min_confidence=0.4, min_chars=50,
    )
    accepted = [p for p in gated if p.accepted]
    rejected = [p for p in gated if not p.accepted]
    assert len(accepted) == 3
    assert len(rejected) == 2
    reasons = {p.reject_reason for p in rejected}
    assert any("confidence" in (r or "") for r in reasons)
    assert any("length" in (r or "") for r in reasons)


def test_quality_gate_zero_confidence_page_is_rejected() -> None:
    """Backend emits 0.0 when no words were detected — must be dropped."""
    gated = _apply_page_quality_gate(
        [OcrPageResult(text="", confidence=0.0)],
        min_confidence=0.4,
        min_chars=50,
    )
    assert gated[0].accepted is False


def test_quality_gate_threshold_is_configurable() -> None:
    """Lowering the floor accepts pages that the default would reject.

    Sanity-checks that the gate is actually driven by the passed-in
    thresholds and not hard-coded.
    """
    page = OcrPageResult(text="short blurb", confidence=0.3)
    strict = _apply_page_quality_gate(
        [page], min_confidence=0.4, min_chars=50,
    )
    relaxed = _apply_page_quality_gate(
        [page], min_confidence=0.1, min_chars=5,
    )
    assert strict[0].accepted is False
    assert relaxed[0].accepted is True


def test_ocr_result_surfaces_rejection_count() -> None:
    """The top-level OcrResult records pages_rejected so ingest telemetry
    can log garbage-ratio per document."""
    result = OcrResult(
        text="clean text",
        provider="rapidocr",
        pages_processed=3,
        pages_total=3,
        truncated=False,
        pages=[
            OcrPageResult(text="clean", confidence=0.9, accepted=True),
            OcrPageResult(
                text="junk",
                confidence=0.1,
                accepted=False,
                reject_reason="confidence 0.10 < 0.40",
            ),
            OcrPageResult(
                text="SEAL",
                confidence=0.98,
                accepted=False,
                reject_reason="length 4 < 50",
            ),
        ],
        pages_rejected=2,
    )
    assert result.pages_rejected == 2
    assert sum(1 for p in result.pages if not p.accepted) == 2


# ---------------------------------------------------------------
# Sprint Q2 — tesseract language auto-detect.
# ---------------------------------------------------------------


def test_detect_tesseract_lang_devanagari_sample_picks_hin() -> None:
    """A paragraph dominated by Devanagari code points (hindi / marathi)
    must resolve to the 'hin' tesseract pack."""
    # Sample: "appellant filed a petition" translated to Hindi, plus
    # a bit of Latin noise to prove the dominance threshold works.
    sample = "अपीलकर्ता ने याचिका दायर की। Case No. 123"
    assert _detect_tesseract_lang(sample, fallback="eng") == "hin"


def test_detect_tesseract_lang_tamil_sample_picks_tam() -> None:
    """Tamil-heavy sample -> 'tam'."""
    sample = "மேல்முறையீடு தாக்கல் செய்யப்பட்டது. Appeal 42"
    assert _detect_tesseract_lang(sample, fallback="eng") == "tam"


def test_detect_tesseract_lang_ascii_sample_picks_eng() -> None:
    """Latin-only text must stay on 'eng' rather than fall to fallback
    — fallback is only for the empty-input / unknown-script cases."""
    sample = "In the matter of the petition filed on 4 April 2026"
    assert _detect_tesseract_lang(sample, fallback="mar") == "eng"


def test_detect_tesseract_lang_empty_sample_returns_fallback() -> None:
    """No alphabetic characters -> hand back whatever the caller set as
    the fallback (production wires this to 'eng')."""
    assert _detect_tesseract_lang("", fallback="eng") == "eng"
    assert _detect_tesseract_lang("   \n\t 12345 ???", fallback="hin") == "hin"


def test_detect_tesseract_lang_bengali_falls_back_not_installed() -> None:
    """Bengali code points dominate but no 'ben' pack ships in the
    Docker image — helper must log + hand back the fallback so
    tesseract never gets a --lang it can't load."""
    sample = "আদালত রায় ঘোষণা করেছে"
    assert _detect_tesseract_lang(sample, fallback="eng") == "eng"


# ---------------------------------------------------------------
# Sprint Q3 — rapidocr handwriting retry.
# ---------------------------------------------------------------


class _StubRapidOcrBackend(ocr_module._RapidOcrBackend):
    """Bypass the real rapidocr import; drive the retry branch with a
    scripted engine so the test covers the control flow, not the ONNX
    runtime."""

    def __init__(self, scripts: list[object]) -> None:  # noqa: D401
        self._scripts = list(scripts)
        self._calls: list[str] = []

        def engine(arr: object, **kwargs: object) -> object:
            self._calls.append("retry" if kwargs else "first")
            return self._scripts.pop(0)

        self._engine = engine  # type: ignore[assignment]


def _make_rapidocr_result(txts: list[str], scores: list[float]) -> object:
    return SimpleNamespace(txts=txts, scores=scores)


def test_rapidocr_handwriting_retry_triggers_in_band_with_high_variance() -> None:
    """First pass in the 0.25-0.55 band + noisy per-line scores -> the
    backend retries once, and keeps the retry when it beats the first
    pass by >= 0.05."""
    first = _make_rapidocr_result(
        txts=["murky line a", "clear line b", "barely a word"],
        # mean 0.40, variance ~0.10 (well above threshold)
        scores=[0.10, 0.90, 0.20],
    )
    retry = _make_rapidocr_result(
        txts=["handwritten line a", "handwritten line b"],
        scores=[0.80, 0.85],  # mean 0.825 — clear improvement
    )
    backend = _StubRapidOcrBackend(scripts=[first, retry])
    pages = backend.ocr_pages([object()], languages="eng")
    assert backend._calls == ["first", "retry"]
    assert pages[0].text.startswith("handwritten line a")
    assert pages[0].confidence == pytest.approx(0.825)


def test_rapidocr_handwriting_retry_does_not_run_outside_band() -> None:
    """A high-confidence first pass must not trigger the retry — we
    don't waste a second decode on pages that already look clean."""
    first = _make_rapidocr_result(
        txts=["clean line one", "clean line two", "clean line three"],
        scores=[0.88, 0.90, 0.92],  # mean 0.90, way above the band
    )
    backend = _StubRapidOcrBackend(scripts=[first])  # no retry scripted
    pages = backend.ocr_pages([object()], languages="eng")
    assert backend._calls == ["first"]
    assert pages[0].confidence == pytest.approx(0.90)


def test_rapidocr_handwriting_retry_keeps_first_pass_when_improvement_too_small() -> None:
    """Retry ran but only nudged confidence by < 0.05 -> keep the first
    pass so we don't swap in a marginally-better but differently-wrong
    recognition."""
    first = _make_rapidocr_result(
        txts=["first pass line"],
        scores=[0.10, 0.70],  # mean 0.40, variance 0.09 (high)
    )
    retry = _make_rapidocr_result(
        txts=["retry pass line"],
        scores=[0.40, 0.43],  # mean 0.415 — only +0.015 over first
    )
    backend = _StubRapidOcrBackend(scripts=[first, retry])
    pages = backend.ocr_pages([object()], languages="eng")
    assert backend._calls == ["first", "retry"]
    assert pages[0].text == "first pass line"
    assert pages[0].confidence == pytest.approx(0.40)
