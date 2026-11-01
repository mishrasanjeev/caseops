"""Raster legibility checks for generated PDFs (BUG-016).

Text extraction cannot see colour: dark text on a dark fill still extracts and
still sits inside its column, which is how the invoice shipped unreadable line
items while glyph-position tests stayed green. These helpers render each page
to pixels and measure, for every text run, the WCAG contrast between the
run's glyph pixels and the dominant background colour inside the run's box.

Taking the darkest and lightest pixel of the whole box was too weak: a box
that touched a white margin or a border line passed even when its glyphs sat
on a fill of their own colour. The background is the most common colour in
the box, and glyph ink is only read from the box interior.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pypdfium2 as pdfium

DPI = 200
SCALE = DPI / 72
MIN_CONTRAST = 4.5


@dataclass(frozen=True)
class TextRun:
    page: int
    text: str
    box: tuple[float, float, float, float]  # left, bottom, right, top in points
    contrast: float


@dataclass(frozen=True)
class RenderedPdf:
    page_sizes: list[tuple[float, float]]
    page_texts: list[str]
    runs: list[TextRun]

    @property
    def text(self) -> str:
        return "\n".join(self.page_texts)


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: float, b: float) -> float:
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def run_contrast(image, box: tuple[int, int, int, int]) -> float:
    """Contrast of a run's glyph ink against the dominant colour of its box.

    The interior excludes the outer tenth of the width and fifth of the
    height, so a margin, rule or neighbouring cell that only touches the box
    edge cannot stand in for missing glyph ink.
    """

    left, top, right, bottom = box
    if right - left < 2 or bottom - top < 2:
        return 1.0
    background = Counter(image.crop(box).get_flattened_data()).most_common(1)[0][0]
    inset_x = (right - left) // 10
    inset_y = (bottom - top) // 5
    interior = (left + inset_x, top + inset_y, right - inset_x, bottom - inset_y)
    background_luminance = luminance(background)
    return max(
        contrast_ratio(luminance(colour), background_luminance)
        for colour in set(image.crop(interior).get_flattened_data())
    )


def render(pdf_bytes: bytes) -> RenderedPdf:
    document = pdfium.PdfDocument(pdf_bytes)
    sizes: list[tuple[float, float]] = []
    texts: list[str] = []
    runs: list[TextRun] = []
    try:
        for index in range(len(document)):
            page = document[index]
            width, height = page.get_size()
            sizes.append((width, height))
            image = page.render(scale=SCALE).to_pil().convert("RGB")
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            for rect_index in range(textpage.count_rects()):
                left, bottom, right, top = textpage.get_rect(rect_index)
                text = textpage.get_text_bounded(left, bottom, right, top).strip()
                if not text:
                    continue
                box = (
                    max(0, int(left * SCALE)),
                    max(0, int((height - top) * SCALE)),
                    min(image.width, int(right * SCALE) + 1),
                    min(image.height, int((height - bottom) * SCALE) + 1),
                )
                contrast = run_contrast(image, box)
                runs.append(TextRun(index, text, (left, bottom, right, top), contrast))
            textpage.close()
            page.close()
    finally:
        document.close()
    return RenderedPdf(sizes, texts, runs)


def illegible_runs(rendered: RenderedPdf) -> list[str]:
    """Text runs whose own pixels do not reach the WCAG AA contrast ratio."""

    return [
        f"page {run.page + 1}: {run.text!r} contrast {run.contrast:.2f}"
        for run in rendered.runs
        if run.contrast < MIN_CONTRAST
    ]


def runs_outside_page(rendered: RenderedPdf, *, tolerance: float = 0.5) -> list[str]:
    offenders = []
    for run in rendered.runs:
        width, height = rendered.page_sizes[run.page]
        left, bottom, right, top = run.box
        inside_x = -tolerance <= left and right <= width + tolerance
        inside_y = -tolerance <= bottom and top <= height + tolerance
        if not (inside_x and inside_y):
            offenders.append(f"page {run.page + 1}: {run.text!r} at {run.box}")
    return offenders


def compact(text: str) -> str:
    """Whitespace-free text, so wrapped lines compare equal to their source."""

    return "".join(text.split())


def assert_legible(pdf_bytes: bytes) -> RenderedPdf:
    rendered = render(pdf_bytes)
    assert rendered.runs, "the PDF drew no extractable text"
    illegible = illegible_runs(rendered)
    assert illegible == [], illegible
    outside = runs_outside_page(rendered)
    assert outside == [], outside
    return rendered
