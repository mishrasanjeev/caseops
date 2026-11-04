"""Keep ordinary pdfminer output; recover failed Unicode mapping per PDF.

The fallback reads the same opened source and extracts every page with PDFium,
which understands inline ActualText. No output-string CID matching or rewriting
is used: literal business text such as ``(cid:4)`` stays literal.
"""

from __future__ import annotations

import math
import os
import stat
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from pathlib import Path
from threading import RLock
from typing import BinaryIO

from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfdocument import PDFEncryptionError
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage


class PDFTextExtractionError(ValueError):
    """The PDF needs another extraction/OCR path; no degraded text is returned."""


_PDFIUM_LOCK = RLock()


@contextmanager
def pdfium_operation():
    """Serialize complete native lifetimes across extraction and OCR threads."""
    with _PDFIUM_LOCK:
        yield


def copy_pdfium_image(bitmap):
    """Detach Pillow pixels before releasing a native bitmap inside its lock."""
    try:
        view = bitmap.to_pil()
        try:
            return view.copy()
        finally:
            view.close()
    finally:
        bitmap.close()


@dataclass(frozen=True)
class _MinerText:
    text: str
    undefined_characters: int
    mapped_counts: Counter[str] = field(default_factory=Counter)
    error: Exception | None = None


class _ObservedTextConverter(TextConverter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.undefined_characters = 0
        self.mapped_counts: Counter[str] = Counter()

    def handle_undefined_char(self, font, cid):
        self.undefined_characters += 1
        return super().handle_undefined_char(font, cid)

    def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate):
        before = self.undefined_characters
        advance = super().render_char(
            matrix,
            font,
            fontsize,
            scaling,
            rise,
            cid,
            ncs,
            graphicstate,
        )
        if self.undefined_characters == before:
            self.mapped_counts.update(char for char in font.to_unichr(cid) if not char.isspace())
        return advance


def _version(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_size,
        row.st_mtime_ns,
        row.st_ctime_ns,
        row.st_nlink,
        getattr(row, "st_birthtime_ns", 0),
        getattr(row, "st_file_attributes", 0),
    )


def _same_object(path: os.stat_result, descriptor: os.stat_result) -> bool:
    # Windows pathname and descriptor APIs expose different mode/ctime fields.
    # Bind their shared identity while retaining exact versions within each API.
    return (
        path.st_dev,
        path.st_ino,
        stat.S_IFMT(path.st_mode),
        path.st_size,
        path.st_mtime_ns,
    ) == (
        descriptor.st_dev,
        descriptor.st_ino,
        stat.S_IFMT(descriptor.st_mode),
        descriptor.st_size,
        descriptor.st_mtime_ns,
    )


@contextmanager
def _source(source: str | Path | bytes) -> Iterator[BinaryIO]:
    if isinstance(source, bytes):
        with BytesIO(source) as stream:
            yield stream
        return
    path = Path(source)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        before_path = path.stat()
        if not _same_object(before_path, before):
            raise PDFTextExtractionError("PDF source changed during extraction.")
        try:
            yield stream
        finally:
            after = os.fstat(stream.fileno())
            if _version(before) != _version(after) or _version(before_path) != _version(
                path.stat()
            ):
                raise PDFTextExtractionError("PDF source changed during extraction.")


def _pdfminer_text(stream: BinaryIO) -> _MinerText:
    """The pinned extract_text defaults, with one per-call observation hook."""
    with StringIO() as output:
        resource_manager = PDFResourceManager(caching=True)
        device = _ObservedTextConverter(
            resource_manager, output, codec="utf-8", laparams=LAParams()
        )
        interpreter = PDFPageInterpreter(resource_manager, device)
        error: Exception | None = None
        try:
            # Match pdfminer.high_level.extract_text: no page subset, maxpages=0,
            # password="", caching=True, default check_extractable behavior.
            for page in PDFPage.get_pages(stream, None, maxpages=0, password="", caching=True):
                interpreter.process_page(page)
        except Exception as caught:
            error = caught
        finally:
            device.close()
        return _MinerText(
            output.getvalue(),
            device.undefined_characters,
            device.mapped_counts.copy(),
            error,
        )


@pdfium_operation()
def _pdfium_text(source: bytes | BinaryIO) -> str:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    document = pdfium.PdfDocument(source, autoclose=False)
    pages: list[str] = []
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    bounds = list(page.get_bbox())
                    for char_index in range(text_page.count_chars()):
                        if raw.FPDFText_HasUnicodeMapError(text_page, char_index) != 0:
                            raise PDFTextExtractionError(
                                "PDF fallback has an unresolved Unicode mapping."
                            )
                        box = text_page.get_charbox(char_index)
                        if not all(math.isfinite(value) for value in box):
                            raise PDFTextExtractionError("PDF fallback has invalid text geometry.")
                        bounds = [
                            min(bounds[0], box[0]),
                            min(bounds[1], box[1]),
                            max(bounds[2], box[2]),
                            max(bounds[3], box[3]),
                        ]
                    # Bounded text supports full Unicode rather than the SDK's
                    # UCS-2 range convenience method. Include every text box,
                    # also outside the crop box; no page prefix/text is omitted.
                    text = text_page.get_text_bounded(*bounds, errors="strict")
                    if any(
                        (ord(char) < 32 and char not in "\t\n\r\f") or 127 <= ord(char) <= 159
                        for char in text
                    ):
                        raise PDFTextExtractionError("PDF fallback contains invalid text controls.")
                    pages.append(text)
                finally:
                    text_page.close()
            finally:
                page.close()
    finally:
        document.close()
    return "\f".join(pages)


def extract_pdf_text(source: str | Path | bytes) -> str:
    """Extract one complete PDF, preserving callers' existing OCR decisions.

    Healthy pdfminer output is returned exactly. A real undefined-glyph event,
    empty result or parser error selects PDFium for the whole same-source PDF.
    A failed/empty recovery never returns the original unresolved-CID text.
    Password/extraction-policy errors do not authorize a different reader.
    """
    with _source(source) as stream:
        first_error: Exception | None = None
        original: _MinerText | None = None
        try:
            original = _pdfminer_text(stream)
        except (PDFEncryptionError, MemoryError):
            raise
        except Exception as error:
            first_error = error
        else:
            if isinstance(original.error, (PDFEncryptionError, MemoryError)):
                raise original.error
            if original.error is not None:
                first_error = original.error
            elif not original.undefined_characters and original.text.strip():
                return original.text
            elif original.undefined_characters:
                first_error = PDFTextExtractionError(
                    "PDF text has unresolved Unicode mappings and needs OCR."
                )
        try:
            stream.seek(0)
            recovered = _pdfium_text(stream)
            if not recovered.strip() and first_error is not None:
                raise PDFTextExtractionError("PDF fallback returned no readable text.")
            if original is not None and (original.undefined_characters or original.error):
                # Compare independently decoded glyph values, not marker-like
                # substrings. A recovery cannot silently lose already-mapped
                # characters. Layout whitespace/order may differ by engine.
                actual = Counter(char for char in recovered if not char.isspace())
                if original.mapped_counts - actual:
                    raise PDFTextExtractionError("PDF fallback lost already-readable characters.")
        except Exception as fallback_error:
            if first_error is not None:
                raise first_error from fallback_error
            raise PDFTextExtractionError("PDF text extraction still needs OCR.") from fallback_error
        return recovered
