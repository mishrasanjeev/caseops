from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from caseops_api.core.settings import get_settings
from caseops_api.services.ocr import (
    OcrResult,
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
