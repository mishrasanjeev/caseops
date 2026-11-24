"""Readable PDF of a machine translation, keeping source page references.

Each source page becomes a "Source page N" section with its paragraphs in the
original order; headings stay headings and table text keeps its rows. The
document says plainly that it is an unreviewed machine translation until a
reviewer signs off; it is never labelled certified or verified.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from caseops_api.services.pdf_layout import safe_pdf_class

_FONT = "Helvetica"


def render_translation_pdf(
    *,
    title: str,
    source_language: str,
    target_language: str,
    model: str,
    version: int,
    generated_at: datetime,
    pages: list[dict[str, Any]],
) -> bytes:
    pdf_class = safe_pdf_class()

    class TranslationPDF(pdf_class):
        def footer(self) -> None:  # noqa: D401 - fpdf2 hook
            self.set_y(-12)
            self.set_font(_FONT, size=8)
            self.cell(
                0,
                5,
                f"Machine translation v{version} - not reviewed or certified - page "
                f"{self.page_no()}/{{nb}}",
                align="C",
            )

    pdf = TranslationPDF(format="A4")
    pdf.set_title(f"{title} ({target_language})")
    pdf.set_creation_date(
        generated_at if generated_at.tzinfo else generated_at.replace(tzinfo=UTC)
    )
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font(_FONT, size=13, style="B")
    pdf.multi_cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_FONT, size=8.5)
    pdf.multi_cell(
        0,
        4.5,
        (
            f"Translation {source_language} -> {target_language} by {model}. "
            "Unreviewed machine output: compare with the source before reliance. "
            "Page references point to the original document."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)
    for page in pages:
        pdf.set_font(_FONT, size=9, style="B")
        pdf.multi_cell(0, 5, f"Source page {page['page']}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        paragraphs = page.get("paragraphs") or []
        if not paragraphs:
            pdf.set_font(_FONT, size=9)
            pdf.multi_cell(
                0, 5, "[No readable text on this page.]", new_x="LMARGIN", new_y="NEXT",
            )
        for paragraph in paragraphs:
            text = paragraph.get("translated")
            if paragraph.get("source_unavailable") or text is None:
                pdf.set_font(_FONT, size=9)
                pdf.multi_cell(
                    0,
                    5,
                    "[Source text unclear or unreadable - see the original page.]",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
                pdf.ln(1.5)
                continue
            heading = paragraph.get("kind") in {"heading", "title", "section-header"}
            pdf.set_font(_FONT, size=10.5 if heading else 10, style="B" if heading else "")
            pdf.multi_cell(0, 5.2, text, new_x="LMARGIN", new_y="NEXT")
            if paragraph.get("flags"):
                pdf.set_font(_FONT, size=7.5)
                pdf.multi_cell(
                    0,
                    4,
                    "Review: " + ", ".join(str(flag) for flag in paragraph["flags"]),
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            pdf.ln(1.5)
        pdf.ln(2)
    return bytes(pdf.output())


__all__ = ["render_translation_pdf"]
