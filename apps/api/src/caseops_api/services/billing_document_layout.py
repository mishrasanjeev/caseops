"""One branded layout for every billing PDF (ENH-001).

Before ENH-001 each billing PDF drew its own page: the matter invoice and
receipt printed a plain title bar, the SaaS invoice and statement printed a
label/value list, and none carried a logo, watermark, signatory or any way to
check that a copy was genuine. ``render_billing_document`` is now the only way a
billing PDF is produced. It owns everything that makes a copy recognisably the
issuer's and verifiable:

* the letterhead (logo, issuer name, address, tax identifiers, contact),
* a light watermark behind every page (a status word such as DRAFT or PAID
  overrides the firm's own text, so an unissued copy can never look final),
* the title banner and footer (document marking, number, "Page n of N"),
* the closing block: the verification QR code with its printed link, and the
  authorised signatory with the signature image.

Callers supply only the document-specific body. The watermark and the QR code
are drawn as images, not text: a text watermark would be extracted into copied
text and would fail every legibility check that measures each text run against
its background.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
from typing import Any

from caseops_api.services.pdf_layout import TEXT_COLOR, safe_pdf_class

PAGE_MARGIN_MM = 12
LOGO_MAX_WIDTH_MM = 42
LOGO_MAX_HEIGHT_MM = 22
SIGNATURE_MAX_WIDTH_MM = 48
SIGNATURE_MAX_HEIGHT_MM = 16
QR_SIZE_MM = 28
# The closing block needs this much room; otherwise it moves to a new page
# whole, so the QR code is never split from its link or the signature from
# the signatory's name.
CLOSING_BLOCK_HEIGHT_MM = 46
ACCENT_RULE = (30, 41, 59)
MUTED_TEXT = (55, 65, 81)
WATERMARK_INK = (100, 116, 139)
WATERMARK_OPACITY = 0.09
QR_BOX_SIZE = 10
QR_BORDER_MODULES = 4


@dataclass(frozen=True, slots=True)
class DocumentIssuer:
    """Who issued the document: printed as the letterhead."""

    name: str
    detail_lines: tuple[str, ...] = ()
    logo_png: bytes | None = None


@dataclass(frozen=True, slots=True)
class DocumentSignatory:
    """The closing signature block.

    ``signature_png`` is applied only when the caller decided the document is
    final; ``note`` explains an unsigned block (for example a draft).
    """

    for_name: str
    name: str | None = None
    designation: str | None = None
    signature_png: bytes | None = None
    note: str | None = None
    label: str = "Authorised signatory"


@dataclass(frozen=True, slots=True)
class BillingDocument:
    title: str
    document_number: str
    issuer: DocumentIssuer
    author: str
    banner_fill: tuple[int, int, int] = (17, 24, 39)
    explanation: str | None = None
    footer_marking: str = ""
    watermark_text: str | None = None
    signatory: DocumentSignatory | None = None
    verification_url: str | None = None
    verification_note: str | None = None


@dataclass(frozen=True, slots=True)
class RenderedBillingDocument:
    """The PDF bytes plus a record of exactly which branding was drawn."""

    body: bytes
    sha256: str
    page_count: int
    watermark_text: str | None
    logo_drawn: bool
    signature_drawn: bool
    verification_url: str | None
    images: tuple[str, ...] = field(default_factory=tuple)


def _png_size(png: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(BytesIO(png)) as image:
        return image.size


def _fit(png: bytes, max_w: float, max_h: float) -> tuple[float, float]:
    width_px, height_px = _png_size(png)
    scale = min(max_w / width_px, max_h / height_px)
    return width_px * scale, height_px * scale


def qr_png(url: str) -> bytes:
    """Encode ``url`` as a QR code PNG (error correction M, 4-module quiet zone)."""

    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    code = qrcode.QRCode(
        error_correction=ERROR_CORRECT_M,
        box_size=QR_BOX_SIZE,
        border=QR_BORDER_MODULES,
    )
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white").get_image()
    buffer = BytesIO()
    image.convert("L").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def qr_modules(url: str) -> list[list[bool]]:
    """The module matrix ``qr_png`` draws for ``url``, without the quiet zone."""

    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=1, border=0)
    code.add_data(url)
    code.make(fit=True)
    return [[bool(cell) for cell in row] for row in code.get_matrix()]


@lru_cache(maxsize=64)
def watermark_png(text: str) -> bytes:
    """Rasterise ``text`` through the pinned, shaped PDF font pipeline.

    Indic firm names need HarfBuzz shaping; Pillow's own text layout depends on
    optional native libraries. The text is set by the same font policy as the
    rest of the PDF, rasterised with PDFium, and turned into a rotated,
    translucent PNG whose alpha is the glyph coverage.
    """

    import pypdfium2 as pdfium
    from PIL import Image

    font_size = 64 if len(text) <= 12 else 44 if len(text) <= 24 else 30
    probe = safe_pdf_class()(unit="pt", format=(10, 10))
    probe.set_font("Helvetica", "B", font_size)
    # Shaped clusters can be wider than the unshaped advance sum; pad generously.
    width_pt = probe.get_string_width(text) * 1.2 + font_size
    height_pt = font_size * 1.6
    sheet = safe_pdf_class()(unit="pt", format=(width_pt, height_pt))
    sheet.set_auto_page_break(auto=False)
    sheet.set_margins(0, 0, 0)
    sheet.add_page()
    sheet.set_font("Helvetica", "B", font_size)
    sheet.set_text_color(0, 0, 0)
    sheet.set_xy(0, 0)
    sheet.cell(width_pt, height_pt, text, align="C")
    document = pdfium.PdfDocument(bytes(sheet.output()))
    try:
        page = document[0]
        try:
            coverage = page.render(scale=150 / 72, grayscale=True).to_pil().convert("L")
        finally:
            page.close()
    finally:
        document.close()
    alpha = coverage.point(lambda value: round((255 - value) * WATERMARK_OPACITY))
    stamp = Image.new("RGBA", coverage.size, (*WATERMARK_INK, 0))
    stamp.putalpha(alpha)
    rotated = stamp.rotate(32, expand=True, resample=Image.Resampling.BICUBIC)
    buffer = BytesIO()
    rotated.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_billing_document(
    document: BillingDocument,
    draw_body: Callable[[Any], None],
) -> RenderedBillingDocument:
    """Draw ``document`` around ``draw_body`` and return the finished PDF."""

    pdf_class = safe_pdf_class()
    watermark = watermark_png(document.watermark_text) if document.watermark_text else None
    footer_prefix = f"{document.footer_marking}{document.document_number} | Page "
    continuation = f"{document.issuer.name} | {document.title} {document.document_number}"
    drawn: list[str] = []

    class _BrandedPdf(pdf_class):  # type: ignore[misc,valid-type]
        def header(self) -> None:
            if watermark is not None:
                width_mm = self.w * 0.78
                ratio = _png_size(watermark)
                height_mm = width_mm * ratio[1] / ratio[0]
                self.image(
                    BytesIO(watermark),
                    x=(self.w - width_mm) / 2,
                    y=(self.h - height_mm) / 2,
                    w=width_mm,
                    h=height_mm,
                )
                if self.page_no() == 1:
                    drawn.append("watermark")
            self.set_xy(self.l_margin, self.t_margin)
            if self.page_no() > 1:
                self.set_font("Helvetica", "", 8)
                self.set_text_color(*TEXT_COLOR)
                self.cell(0, 5, continuation, new_x="LMARGIN", new_y="NEXT")
                self.ln(2)

        # BUG-016: set_y(-14) inside the auto-break margin forced a blank second
        # page holding only "Page 1"; the footer stays above that margin.
        def footer(self) -> None:
            self.set_y(-12)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*TEXT_COLOR)
            self.cell(0, 5, f"{footer_prefix}{self.page_no()} of {{nb}}", align="C")

    pdf = _BrandedPdf(format="A4", unit="mm")
    pdf.set_margins(PAGE_MARGIN_MM, PAGE_MARGIN_MM, PAGE_MARGIN_MM)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.alias_nb_pages()
    pdf.set_title(f"{document.title} {document.document_number}")
    pdf.set_author(document.author)
    pdf.add_page()
    pdf.set_text_color(*TEXT_COLOR)
    logo_drawn = _draw_letterhead(pdf, document.issuer)
    if logo_drawn:
        drawn.append("logo")
    _draw_banner(pdf, document)
    draw_body(pdf)
    signature_drawn, qr_drawn = _draw_closing_block(pdf, document)
    if signature_drawn:
        drawn.append("signature")
    if qr_drawn:
        drawn.append("qr")
    body = bytes(pdf.output())
    return RenderedBillingDocument(
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        page_count=pdf.pages_count,
        watermark_text=document.watermark_text if watermark is not None else None,
        logo_drawn=logo_drawn,
        signature_drawn=signature_drawn,
        verification_url=document.verification_url if qr_drawn else None,
        images=tuple(drawn),
    )


_LINES = {"new_x": "LMARGIN", "new_y": "NEXT"}


def _draw_letterhead(pdf: Any, issuer: DocumentIssuer) -> bool:
    top = pdf.get_y()
    text_x = pdf.l_margin
    logo_bottom = top
    logo_drawn = False
    if issuer.logo_png:
        width, height = _fit(issuer.logo_png, LOGO_MAX_WIDTH_MM, LOGO_MAX_HEIGHT_MM)
        pdf.image(BytesIO(issuer.logo_png), x=pdf.l_margin, y=top, w=width, h=height)
        text_x = pdf.l_margin + width + 6
        logo_bottom = top + height
        logo_drawn = True
    width = pdf.w - pdf.r_margin - text_x
    pdf.set_xy(text_x, top)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*TEXT_COLOR)
    pdf.multi_cell(width, 7, issuer.name, new_x="LEFT", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*MUTED_TEXT)
    for line in issuer.detail_lines:
        if line:
            pdf.multi_cell(width, 4.4, line, new_x="LEFT", new_y="NEXT")
    pdf.set_text_color(*TEXT_COLOR)
    bottom = max(pdf.get_y(), logo_bottom) + 2.5
    pdf.set_draw_color(*ACCENT_RULE)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, bottom, pdf.w - pdf.r_margin, bottom)
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_xy(pdf.l_margin, bottom + 3)
    return logo_drawn


def _draw_banner(pdf: Any, document: BillingDocument) -> None:
    # BUG-016: the bar's fill must not leak into the tables drawn below it.
    with pdf.local_context(fill_color=document.banner_fill, text_color=(255, 255, 255)):
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8.5, f" {document.title}", fill=True, **_LINES)
    if document.explanation:
        pdf.set_font("Helvetica", "B", 9)
        pdf.multi_cell(0, 5, document.explanation, **_LINES)
    pdf.ln(3)


def _draw_closing_block(pdf: Any, document: BillingDocument) -> tuple[bool, bool]:
    if document.signatory is None and document.verification_url is None:
        return False, False
    if pdf.get_y() + CLOSING_BLOCK_HEIGHT_MM > pdf.h - pdf.b_margin:
        pdf.add_page()
    pdf.ln(4)
    top = pdf.get_y()
    half = pdf.epw / 2
    qr_drawn = False
    if document.verification_url:
        pdf.image(
            BytesIO(qr_png(document.verification_url)),
            x=pdf.l_margin,
            y=top,
            w=QR_SIZE_MM,
            h=QR_SIZE_MM,
        )
        qr_drawn = True
        text_x = pdf.l_margin + QR_SIZE_MM + 3
        text_w = half - QR_SIZE_MM - 3
        pdf.set_xy(text_x, top + 1)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.multi_cell(text_w, 4.4, "Verify this document", new_x="LEFT", new_y="NEXT")
        pdf.set_font("Helvetica", "", 7.5)
        pdf.multi_cell(
            text_w,
            3.8,
            document.verification_note
            or "Scan the code or open the link to confirm the issuer, status and "
            "fingerprint of this copy.",
            align="L",
            new_x="LEFT",
            new_y="NEXT",
        )
    signature_drawn = False
    if document.signatory is not None:
        signatory = document.signatory
        x = pdf.l_margin + half + 4
        width = half - 4
        pdf.set_xy(x, top)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.multi_cell(
            width, 4.4, f"For {signatory.for_name}", align="R", new_x="LEFT", new_y="NEXT"
        )
        image_top = pdf.get_y() + 1
        if signatory.signature_png:
            sig_w, sig_h = _fit(
                signatory.signature_png, SIGNATURE_MAX_WIDTH_MM, SIGNATURE_MAX_HEIGHT_MM
            )
            pdf.image(
                BytesIO(signatory.signature_png),
                x=pdf.w - pdf.r_margin - sig_w,
                y=image_top,
                w=sig_w,
                h=sig_h,
            )
            signature_drawn = True
            pdf.set_xy(x, image_top + SIGNATURE_MAX_HEIGHT_MM + 1)
        else:
            pdf.set_xy(x, image_top)
            pdf.set_font("Helvetica", "", 7.5)
            if signatory.note:
                pdf.multi_cell(
                    width, 3.8, signatory.note, align="R", new_x="LEFT", new_y="NEXT"
                )
            pdf.set_xy(x, image_top + SIGNATURE_MAX_HEIGHT_MM + 1)
        pdf.set_draw_color(*MUTED_TEXT)
        pdf.line(pdf.w - pdf.r_margin - 60, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.set_draw_color(0, 0, 0)
        pdf.ln(1)
        pdf.set_x(x)
        if signatory.name:
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.multi_cell(width, 4.4, signatory.name, align="R", new_x="LEFT", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        label = signatory.label
        if signatory.designation:
            label = f"{signatory.designation} | {label}"
        pdf.multi_cell(width, 4, label, align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_xy(pdf.l_margin, max(pdf.get_y(), top + QR_SIZE_MM) + 1.5)
    if qr_drawn:
        # The link is printed whole on one full-width line, so it can be typed
        # or copied when the code cannot be scanned. 8 pt keeps every glyph
        # above the contrast floor at print resolution.
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 4.2, f"Verification link: {document.verification_url}", **_LINES)
    pdf.ln(1)
    return signature_drawn, qr_drawn
