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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from caseops_api.core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class OcrPageResult:
    """Per-page output from an OCR backend.

    ``confidence`` is the mean per-line / per-token recognition score in
    the range 0.0-1.0. Backends that don't expose confidence use 1.0 so
    pure-length filtering still works.
    """
    text: str
    confidence: float
    accepted: bool = True
    reject_reason: str | None = None


@dataclass
class OcrResult:
    text: str
    provider: str
    pages_processed: int
    pages_total: int
    truncated: bool
    # Sprint Q4 — per-page quality telemetry. Populated by every
    # backend so the ingester can log which pages were dropped and why.
    pages: list[OcrPageResult] = field(default_factory=list)
    pages_rejected: int = 0


class _OcrBackend(Protocol):
    name: str

    def ocr_pages(self, images: list[object], languages: str) -> list[OcrPageResult]: ...


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

    def ocr_pages(
        self, images: list[object], languages: str
    ) -> list[OcrPageResult]:
        import numpy as np  # type: ignore[import-not-found]

        pages: list[OcrPageResult] = []
        for image in images:
            arr = np.asarray(image)
            result = self._engine(arr)
            # rapidocr 3.x returns a Result-like object with `.txts`
            # (list[str]) + `.scores` (list[float]).
            txts = getattr(result, "txts", None)
            scores = getattr(result, "scores", None)
            if txts is None:
                # Older API: list of (box, text, score) tuples.
                triples = [item for item in (result or []) if isinstance(item, tuple)]
                txts = [t[1] for t in triples]
                scores = [float(t[2]) for t in triples]
            text = "\n".join(txts or [])
            if scores:
                # Mean of the per-line recognition scores. A page with
                # half the lines at 0.9 and half at 0.1 is genuinely a
                # mixed page and should be treated as ~0.5.
                confidence = float(sum(scores) / len(scores))
            else:
                # No lines were detected — confidence 0 so the page is
                # cleanly rejected by the gate.
                confidence = 0.0
            pages.append(OcrPageResult(text=text, confidence=confidence))
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

    def ocr_pages(
        self, images: list[object], languages: str
    ) -> list[OcrPageResult]:
        from pytesseract import Output  # type: ignore[import-not-found]

        pages: list[OcrPageResult] = []
        for image in images:
            # image_to_data returns per-token rows with a `conf` column
            # (0-100, or -1 for non-word rows). Filter -1, average the
            # rest, and join the tokens as the page text so we get both
            # the recognised string and its aggregate confidence in one
            # pass instead of two.
            data = self._pytesseract.image_to_data(
                image, lang=languages, output_type=Output.DICT
            )
            tokens = data.get("text", []) or []
            confs = data.get("conf", []) or []
            word_confs: list[float] = []
            words: list[str] = []
            for tok, conf in zip(tokens, confs, strict=False):
                try:
                    c = float(conf)
                except (TypeError, ValueError):
                    continue
                if c < 0:
                    continue
                if tok and tok.strip():
                    words.append(tok)
                    word_confs.append(c / 100.0)
            text = " ".join(words)
            confidence = (
                float(sum(word_confs) / len(word_confs)) if word_confs else 0.0
            )
            pages.append(OcrPageResult(text=text, confidence=confidence))
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
        pages_result = backend.ocr_pages(images, settings.ocr_languages)
    except Exception as exc:
        logger.warning(
            "%s OCR failed on %s: %s", backend.name, path.name, exc
        )
        return None

    # Q4 quality gate — drop pages below the per-page confidence or
    # char-count floor before joining. Pages remain in ``pages`` for
    # telemetry so downstream jobs can surface what was skipped, but
    # their text never reaches the embedding pipeline.
    gated = _apply_page_quality_gate(
        pages_result,
        min_confidence=settings.ocr_min_page_confidence,
        min_chars=settings.ocr_min_page_chars,
    )
    accepted_text = [p.text.strip() for p in gated if p.accepted and p.text.strip()]
    text = "\n\n".join(accepted_text)
    rejected = sum(1 for p in gated if not p.accepted)
    if rejected:
        logger.info(
            "%s OCR on %s: %d / %d pages dropped by quality gate.",
            backend.name,
            path.name,
            rejected,
            len(gated),
        )
    return OcrResult(
        text=text,
        provider=backend.name,
        pages_processed=len(gated),
        pages_total=total_pages,
        truncated=truncated,
        pages=gated,
        pages_rejected=rejected,
    )


def _apply_page_quality_gate(
    pages: list[OcrPageResult],
    *,
    min_confidence: float,
    min_chars: int,
) -> list[OcrPageResult]:
    """Mark pages as accepted / rejected using the Q4 thresholds.

    Returns a fresh list so ``pages_result`` from the backend stays
    untouched (easier to diff from the raw backend output when debugging).
    """
    out: list[OcrPageResult] = []
    for page in pages:
        stripped = page.text.strip()
        if page.confidence < min_confidence:
            reason = f"confidence {page.confidence:.2f} < {min_confidence:.2f}"
            out.append(OcrPageResult(
                text=page.text,
                confidence=page.confidence,
                accepted=False,
                reject_reason=reason,
            ))
            continue
        if len(stripped) < min_chars:
            reason = f"length {len(stripped)} < {min_chars}"
            out.append(OcrPageResult(
                text=page.text,
                confidence=page.confidence,
                accepted=False,
                reject_reason=reason,
            ))
            continue
        out.append(OcrPageResult(
            text=page.text,
            confidence=page.confidence,
            accepted=True,
        ))
    return out


def should_fallback_to_ocr(extracted_text: str) -> bool:
    """True when the pdfminer output is too sparse to trust for retrieval."""
    settings = get_settings()
    threshold = settings.ocr_min_chars_before_fallback
    stripped = (extracted_text or "").strip()
    return len(stripped) < threshold


__all__ = [
    "OcrPageResult",
    "OcrResult",
    "_apply_page_quality_gate",
    "ocr_pdf",
    "should_fallback_to_ocr",
]
