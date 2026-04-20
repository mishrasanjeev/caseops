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


# Sprint Q3 — handwriting retry band. First-pass rapidocr confidence
# inside this window AND with high per-line variance looks like a page
# the printed-text model half-recognised: a retry with the detection +
# recognition path explicitly on (wider beam / character set) sometimes
# recovers a cleaner read of a handwritten page. Outside this band
# we trust the first pass: above it is clean printed text, below it
# is unreadable and a second pass won't help.
_HANDWRITE_BAND_LOW = 0.25
_HANDWRITE_BAND_HIGH = 0.55
_HANDWRITE_VAR_THRESHOLD = 0.04  # ~ stddev 0.2 across per-line scores
_HANDWRITE_MIN_IMPROVEMENT = 0.05


def _score_variance(scores: list[float]) -> float:
    """Population variance of per-line scores. 0 for <2 scores."""
    if len(scores) < 2:
        return 0.0
    mean = sum(scores) / len(scores)
    return sum((s - mean) ** 2 for s in scores) / len(scores)


def _parse_rapidocr_result(result: object) -> tuple[list[str], list[float]]:
    """Normalise rapidocr's v2/v3 return shapes to (txts, scores)."""
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if txts is None:
        # Older API: list of (box, text, score) tuples.
        triples = [item for item in (result or []) if isinstance(item, tuple)]
        txts = [t[1] for t in triples]
        scores = [float(t[2]) for t in triples]
    return list(txts or []), [float(s) for s in (scores or [])]


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

    def _run_engine(self, arr: object, *, handwriting: bool) -> object:
        """Invoke rapidocr. ``handwriting=True`` asks for an explicit
        detect+recognise pass (wider beam / character set). Older
        rapidocr builds reject the kwargs — fall back to the plain call
        so a minor API drift never takes the whole ingest down."""
        if not handwriting:
            return self._engine(arr)
        try:
            return self._engine(arr, use_det=True, use_rec=True)
        except TypeError:
            # API drift: retry with the same default call the first
            # pass used. We still exercised a second decode round so
            # the caller gets a fresh result object to compare.
            return self._engine(arr)

    def ocr_pages(
        self, images: list[object], languages: str
    ) -> list[OcrPageResult]:
        import numpy as np  # type: ignore[import-not-found]

        pages: list[OcrPageResult] = []
        for image in images:
            arr = np.asarray(image)
            result = self._engine(arr)
            txts, scores = _parse_rapidocr_result(result)
            text = "\n".join(txts)
            if scores:
                # Mean of the per-line recognition scores. A page with
                # half the lines at 0.9 and half at 0.1 is genuinely a
                # mixed page and should be treated as ~0.5.
                confidence = float(sum(scores) / len(scores))
            else:
                # No lines were detected — confidence 0 so the page is
                # cleanly rejected by the gate.
                confidence = 0.0

            # Sprint Q3 — handwriting retry. The first pass looked
            # half-confident (printed-text model unsure) AND the per-
            # line scores disagree strongly (variance high): plausibly
            # a handwritten page. One retry, keep it only if it beats
            # the first pass by a meaningful margin.
            if (
                _HANDWRITE_BAND_LOW <= confidence < _HANDWRITE_BAND_HIGH
                and _score_variance(scores) >= _HANDWRITE_VAR_THRESHOLD
            ):
                try:
                    retry = self._run_engine(arr, handwriting=True)
                except Exception as exc:  # noqa: BLE001 — never fail a page
                    logger.warning("rapidocr handwriting retry errored: %s", exc)
                else:
                    r_txts, r_scores = _parse_rapidocr_result(retry)
                    r_conf = (
                        float(sum(r_scores) / len(r_scores)) if r_scores else 0.0
                    )
                    if r_conf - confidence >= _HANDWRITE_MIN_IMPROVEMENT:
                        text = "\n".join(r_txts)
                        confidence = r_conf
            pages.append(OcrPageResult(text=text, confidence=confidence))
        return pages


# Sprint Q2 — tesseract language auto-detect. Each tuple is
# (unicode_block_start, unicode_block_end_exclusive, tesseract_lang).
# Ordered so the first match wins; ranges are disjoint so ordering only
# matters for the dominance tie-breaker.
_SCRIPT_BLOCKS: tuple[tuple[int, int, str], ...] = (
    (0x0900, 0x0980, "hin"),  # Devanagari (Hindi / Marathi / Sanskrit)
    (0x0980, 0x0A00, "ben"),  # Bengali (not currently installed)
    (0x0B80, 0x0C00, "tam"),  # Tamil
    (0x0C00, 0x0C80, "tel"),  # Telugu
    (0x0C80, 0x0D00, "kan"),  # Kannada
)
_AUTO_DETECT_SENTINEL = "auto"
_SCRIPT_DOMINANCE_THRESHOLD = 0.20  # >= 20% of alphabetic code points
# Languages whose tesseract data files we actually ship in the Docker
# image. Detected scripts outside this set warn + fall back to the
# caller-supplied fallback (usually 'eng') so we never hand tesseract a
# --lang pack that the binary will reject with a TessdataManager error.
_INSTALLED_TESSERACT_LANGS: frozenset[str] = frozenset(
    {"eng", "hin", "mar", "tam", "tel", "kan"}
)


def _detect_tesseract_lang(sample_text: str, fallback: str) -> str:
    """Pick a tesseract ``--lang`` code from a sample of recognised text.

    Counts alphabetic-ish code points (letters only; digits, whitespace,
    and punctuation are ignored so a page header like "2024 SCC 123" does
    not drown out a paragraph of Devanagari). A script wins if it
    accounts for ``_SCRIPT_DOMINANCE_THRESHOLD`` or more of the alpha
    pool. When no script dominates — or the winning script is not
    installed — we return ``fallback``.
    """
    if not sample_text:
        return fallback
    alpha_total = 0
    block_counts: dict[str, int] = {}
    for ch in sample_text:
        if not ch.isalpha():
            continue
        alpha_total += 1
        cp = ord(ch)
        matched = False
        for start, end, lang in _SCRIPT_BLOCKS:
            if start <= cp < end:
                block_counts[lang] = block_counts.get(lang, 0) + 1
                matched = True
                break
        if not matched:
            # Latin / ASCII / other → treated as English for the pool.
            block_counts["eng"] = block_counts.get("eng", 0) + 1
    if alpha_total == 0:
        return fallback
    # Consider non-English scripts first: they're the point of auto
    # detect. If none dominates, default to English.
    for _, _, lang in _SCRIPT_BLOCKS:
        count = block_counts.get(lang, 0)
        if count / alpha_total >= _SCRIPT_DOMINANCE_THRESHOLD:
            if lang not in _INSTALLED_TESSERACT_LANGS:
                logger.warning(
                    "OCR auto-detect chose %r but that tesseract language "
                    "pack is not installed; falling back to %r.",
                    lang,
                    fallback,
                )
                return fallback
            return lang
    return "eng"


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

    def _ocr_one(self, image: object, lang: str) -> OcrPageResult:
        from pytesseract import Output  # type: ignore[import-not-found]

        data = self._pytesseract.image_to_data(
            image, lang=lang, output_type=Output.DICT
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
        return OcrPageResult(text=text, confidence=confidence)

    def ocr_pages(
        self, images: list[object], languages: str
    ) -> list[OcrPageResult]:
        # Sprint Q2 — when the operator opted in with
        # CASEOPS_OCR_LANGUAGES=auto, probe the first page with a cheap
        # eng pass, detect the dominant script, then use that lang for
        # every page. Mixed-script judgments stay single-lang per
        # document — tesseract's multi-lang mode ("eng+hin") is slower
        # and routinely misclassifies Latin tokens as Devanagari, so
        # one lang per doc is the pragmatic win.
        effective_lang = languages
        if languages.strip().lower() == _AUTO_DETECT_SENTINEL:
            if images:
                probe = self._ocr_one(images[0], "eng")
                effective_lang = _detect_tesseract_lang(
                    probe.text, fallback="eng"
                )
                logger.info(
                    "OCR auto-detect selected lang=%r from page 1 sample.",
                    effective_lang,
                )
            else:
                effective_lang = "eng"

        pages: list[OcrPageResult] = []
        for image in images:
            pages.append(self._ocr_one(image, effective_lang))
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
    "_detect_tesseract_lang",
    "ocr_pdf",
    "should_fallback_to_ocr",
]
