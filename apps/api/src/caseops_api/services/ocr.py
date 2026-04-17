"""OCR fallback for scanned judgment PDFs.

Two provider paths:

- ``rapidocr``: pure-Python ONNX backend. No native binary, no admin rights.
  Apache-2.0. First use downloads ~100 MB of models. Slower than Tesseract
  on Latin-only text but handles mixed layouts and stamps well.
- ``tesseract``: calls out to the locally-installed Tesseract binary via
  ``pytesseract``. Fastest and most accurate for legal body text — *if*
  the user has Tesseract installed. We never try to install it from here.

The module is import-light: heavy dependencies (onnxruntime, rapidocr,
pytesseract, PIL) are imported only when the corresponding provider is
actually used. If a provider is missing we gracefully return no text and
let the ingester skip / flag the document.

Rendering uses ``pypdfium2`` (already a core dep) so we do not require
poppler on Windows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from caseops_api.core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class OcrResult:
    text: str
    provider: str
    pages_processed: int
    pages_total: int
    truncated: bool


class _OcrBackend(Protocol):
    name: str

    def ocr_pages(self, images: list[object], languages: str) -> list[str]: ...


def _render_pdf_pages(
    path: Path, *, dpi: int, max_pages: int
) -> tuple[list[object], int, bool]:
    """Render each page of ``path`` to a PIL image. Returns (images, total_pages, truncated)."""
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - core dep in pyproject
        raise RuntimeError("pypdfium2 is required for OCR rendering.") from exc

    scale = dpi / 72
    pdf = pdfium.PdfDocument(str(path))
    total = len(pdf)
    images: list[object] = []
    page_count = min(total, max_pages)
    for idx in range(page_count):
        page = pdf[idx]
        bitmap = page.render(scale=scale)
        images.append(bitmap.to_pil())
    pdf.close()
    return images, total, page_count < total


class _RapidOcrBackend:
    name = "rapidocr"

    def __init__(self) -> None:
        try:
            from rapidocr import RapidOCR  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "The 'rapidocr' package is not installed. Run "
                "`uv sync --extra ocr` or set CASEOPS_OCR_PROVIDER=none.",
            ) from exc
        self._engine = RapidOCR()

    def ocr_pages(self, images: list[object], languages: str) -> list[str]:
        import numpy as np  # type: ignore[import-not-found]

        pages: list[str] = []
        for image in images:
            arr = np.asarray(image)
            result = self._engine(arr)
            # rapidocr 3.x returns a Result-like object with `.txts` (list[str]).
            txts = getattr(result, "txts", None)
            if txts is None:
                # Older API: list of (box, text, score) tuples.
                txts = [item[1] for item in (result or []) if isinstance(item, tuple)]
            pages.append("\n".join(txts or []))
        return pages


class _TesseractBackend:
    name = "tesseract"

    def __init__(self) -> None:
        try:
            import pytesseract  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "pytesseract is not installed. Run `uv sync --extra ocr` "
                "and install the Tesseract binary, or set "
                "CASEOPS_OCR_PROVIDER=none.",
            ) from exc
        settings = get_settings()
        if settings.tesseract_command:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_command
        self._pytesseract = pytesseract

    def ocr_pages(self, images: list[object], languages: str) -> list[str]:
        pages: list[str] = []
        for image in images:
            pages.append(self._pytesseract.image_to_string(image, lang=languages))
        return pages


def _build_backend(provider: str) -> _OcrBackend | None:
    provider = provider.lower().strip()
    if provider in {"none", "off", ""}:
        return None
    if provider == "rapidocr":
        return _RapidOcrBackend()
    if provider == "tesseract":
        return _TesseractBackend()
    raise ValueError(
        f"Unknown CASEOPS_OCR_PROVIDER={provider!r}. "
        "Use 'rapidocr', 'tesseract', or 'none'."
    )


def ocr_pdf(path: Path) -> OcrResult | None:
    """Run OCR over ``path`` using the configured provider.

    Returns ``None`` when OCR is disabled or the backend cannot load (e.g.,
    the user has not installed the ocr extras). A best-effort partial
    result is returned when only some pages succeed — we never let a
    single bad page abort a whole document.
    """
    settings = get_settings()
    try:
        backend = _build_backend(settings.ocr_provider)
    except RuntimeError as exc:
        logger.warning("OCR unavailable (%s); skipping %s.", exc, path.name)
        return None
    if backend is None:
        return None

    try:
        images, total_pages, truncated = _render_pdf_pages(
            path,
            dpi=settings.ocr_render_dpi,
            max_pages=settings.ocr_max_pages,
        )
    except Exception as exc:
        logger.warning("Could not render %s for OCR: %s", path.name, exc)
        return None

    try:
        pages_text = backend.ocr_pages(images, settings.ocr_languages)
    except Exception as exc:
        logger.warning(
            "%s OCR failed on %s: %s", backend.name, path.name, exc
        )
        return None

    text = "\n\n".join(t.strip() for t in pages_text if t and t.strip())
    return OcrResult(
        text=text,
        provider=backend.name,
        pages_processed=len(pages_text),
        pages_total=total_pages,
        truncated=truncated,
    )


def should_fallback_to_ocr(extracted_text: str) -> bool:
    """True when the pdfminer output is too sparse to trust for retrieval."""
    settings = get_settings()
    threshold = settings.ocr_min_chars_before_fallback
    stripped = (extracted_text or "").strip()
    return len(stripped) < threshold


__all__ = [
    "OcrResult",
    "ocr_pdf",
    "should_fallback_to_ocr",
]
