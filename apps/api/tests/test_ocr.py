from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from caseops_api.core.settings import get_settings
from caseops_api.services.ocr import (
    OcrPageResult,
    OcrResult,
    _apply_page_quality_gate,
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
