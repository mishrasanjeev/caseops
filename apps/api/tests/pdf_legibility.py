"""Raster legibility checks for generated PDFs (BUG-016).

Text extraction cannot see colour: dark text on a dark fill still extracts and
still sits inside its column, which is how the invoice shipped unreadable line
items while glyph-position tests stayed green. These helpers render each page
to pixels and measure, for every text run, the WCAG contrast between the
run's glyph pixels and the immediate background around its physical object.

The physical object and its native fill colour identify the actual glyph ink.
The one-pixel surrounding ring identifies its local background without treating
a dense I/l stem as background. A neighbouring margin or border on one edge
cannot outvote the background around the other edges. Whole-fragment ActualText
can change text-page geometry, so it must never supply the measured ink box.
"""

from __future__ import annotations

import ctypes
from collections import Counter
from dataclasses import dataclass

import pypdfium2 as pdfium

DPI = 200
SCALE = DPI / 72
MIN_CONTRAST = 4.5


@dataclass(frozen=True)
class TextRun:
    # One physical text object; text is logical line context for diagnostics.
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


def run_contrast(
    image,
    box: tuple[int, int, int, int],
    ink_rgb: tuple[int, int, int],
) -> float:
    """Measure actual raster ink against the immediately surrounding colour.

    Use the physical text object's declared fill only to select its ink from
    the rendered pixels. Faint/transparent/occluded text therefore cannot pass
    using a theoretical foreground colour absent from the actual page.
    """

    left, top, right, bottom = box
    if right - left < 2 or bottom - top < 2:
        return 1.0
    ring: Counter = Counter()
    for strip in (
        (max(0, left - 1), max(0, top - 1), min(image.width, right + 1), top),
        (max(0, left - 1), bottom, min(image.width, right + 1), min(image.height, bottom + 1)),
        (max(0, left - 1), top, left, bottom),
        (right, top, min(image.width, right + 1), bottom),
    ):
        if strip[2] > strip[0] and strip[3] > strip[1]:
            with image.crop(strip) as pixels:
                ring.update(pixels.get_flattened_data())
    if not ring:
        return 1.0
    background = ring.most_common(1)[0][0]
    # A colon can place both dark cores at the physical top/bottom bounds.
    # An inset can retain only their antialiased fringe and misclassify it.
    with image.crop(box) as pixels:
        colours = set(pixels.get_flattened_data())
    if not colours:
        return 1.0
    ink = min(
        colours,
        key=lambda colour: (
            sum((a - b) ** 2 for a, b in zip(colour, ink_rgb, strict=True)),
            colour,
        ),
    )
    return contrast_ratio(luminance(ink), luminance(background))


def render(pdf_bytes: bytes) -> RenderedPdf:
    document = pdfium.PdfDocument(pdf_bytes)
    sizes: list[tuple[float, float]] = []
    texts: list[str] = []
    runs: list[TextRun] = []
    try:
        for index in range(len(document)):
            page = document[index]
            image = None
            textpage = None
            try:
                width, height = page.get_size()
                sizes.append((width, height))
                bitmap = page.render(scale=SCALE)
                try:
                    image = bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
                textpage = page.get_textpage()
                texts.append(textpage.get_text_range())
                for object_index, text_object in enumerate(
                    page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_TEXT])
                ):
                    left, bottom, right, top = text_object.get_bounds()
                    if right <= left or top <= bottom:  # Whitespace has no painted ink.
                        continue
                    # This label is context only. Semantic replacement text may
                    # not have a per-object decoder mapping; physical ink still
                    # needs measuring, including every continuation glyph.
                    text = textpage.get_text_bounded(0, bottom, width, top).strip()
                    if not text:
                        text = f"<text object {object_index}>"
                    rgba = [ctypes.c_uint() for _ in range(4)]
                    known = pdfium.raw.FPDFPageObj_GetFillColor(
                        text_object.raw, *(ctypes.byref(value) for value in rgba)
                    )
                    assert known, "The physical text object's fill colour is unavailable"
                    box = (
                        max(0, int(left * SCALE)),
                        max(0, int((height - top) * SCALE)),
                        min(image.width, int(right * SCALE) + 1),
                        min(image.height, int((height - bottom) * SCALE) + 1),
                    )
                    contrast = run_contrast(
                        image, box, tuple(value.value for value in rgba[:3])
                    )
                    runs.append(TextRun(index, text, (left, bottom, right, top), contrast))
            finally:
                if textpage is not None:
                    textpage.close()
                if image is not None:
                    image.close()
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
