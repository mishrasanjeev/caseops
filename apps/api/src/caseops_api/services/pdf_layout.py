"""Shared fpdf2 helpers for tabular PDF exports.

2026-09-26 (BUG-033): the cause list drew each value with a single-line
``cell()`` of fixed width. fpdf2 neither clips nor wraps such cells, so long
values ran into the neighbouring columns, rows never grew, and the column
widths exceeded the printable page width. Tabular exports must use
``write_wrapped_table``: columns are sized from relative weights to the exact
printable width, every cell wraps inside its own column, each row grows to its
tallest cell, and the heading row repeats on every page.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import cache
from typing import Any

# The core Helvetica font is WinAnsi (Latin-1). Map common typography to
# readable equivalents first; anything still unencodable becomes "?" instead of
# failing the whole export. Non-Latin scripts remain lossless in DOCX exports.
_TYPOGRAPHY = {
    "–": "-",  # en dash
    "—": "--",  # em dash
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    " ": " ",  # non-breaking space
    "·": "-",  # middle dot
    "•": "*",  # bullet
    "→": "->",
    "₹": "INR ",
}
_TRANSLATION = {ord(key): value for key, value in _TYPOGRAPHY.items()}
_UNENCODABLE = re.compile(r"[^\x00-\xff]+")


def pdf_text(value: object) -> str:
    """Return text the core PDF font can encode, without raising."""

    if value is None:
        return ""
    text = str(value).translate(_TRANSLATION)
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        text = _UNENCODABLE.sub("?", text)
    return text


@cache
def safe_pdf_class() -> type:
    """FPDF subclass that cannot fail an export on text the core fonts lack.

    fpdf2 passes every string through ``normalize_text`` before drawing it and
    raises for characters outside the core-font encoding, so one non-Latin
    client, party or matter name turned a download into a server error. Every
    PDF generator builds its document from this class (enforced by a test).
    Imported lazily so PDF support stays off the application start-up path.
    """

    from fpdf import FPDF  # type: ignore[import-not-found]

    class SafeCoreFontPDF(FPDF):  # type: ignore[misc]
        def normalize_text(self, text: str) -> str:
            if not self.is_ttf_font:
                text = pdf_text(text)
            return super().normalize_text(text)

    return SafeCoreFontPDF


def write_wrapped_table(
    pdf: Any,
    *,
    headings: Sequence[str],
    rows: Sequence[Sequence[object]],
    weights: Sequence[float],
    font_size: float = 8,
) -> None:
    """Draw a table whose cells wrap inside their columns and rows grow.

    ``weights`` are relative column widths; fpdf2 scales them to the full
    effective page width, so the table can never overrun the margins.
    """

    if len(headings) != len(weights) or any(len(row) != len(weights) for row in rows):
        raise ValueError("Every table row must have one value per column.")
    from fpdf.fonts import FontFace  # type: ignore[import-not-found]

    pdf.set_font("Helvetica", "", font_size)
    with pdf.table(
        col_widths=tuple(weights),
        width=pdf.epw,
        line_height=font_size * 0.55,
        text_align="LEFT",
        headings_style=FontFace(emphasis="BOLD", fill_color=(236, 239, 244)),
        repeat_headings=1,
        padding=1,
    ) as table:
        heading = table.row()
        for label in headings:
            heading.cell(pdf_text(label))
        for values in rows:
            row = table.row()
            for value in values:
                row.cell(pdf_text(value))


def write_wrapped_pairs(
    pdf: Any,
    rows: Sequence[Sequence[object]],
    *,
    font_size: float = 9,
) -> None:
    """Draw borderless side-by-side label/value text that wraps in its half.

    Replaces ``cell(95, ...)`` followed by ``cell(0, ...)``: a long value in the
    left half could overwrite the right half, and nothing wrapped.
    """

    if not rows:
        return
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("Every pair row must have the same number of columns.")
    pdf.set_font("Helvetica", "", font_size)
    with pdf.table(
        col_widths=tuple(1 for _ in range(width)),
        width=pdf.epw,
        line_height=font_size * 0.5,
        text_align="LEFT",
        borders_layout="NONE",
        first_row_as_headings=False,
        padding=(0.5, 1),
    ) as table:
        for values in rows:
            row = table.row()
            for value in values:
                row.cell(pdf_text(value))
