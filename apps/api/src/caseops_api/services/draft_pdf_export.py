"""PG-005 Sprint 3 (2026-05-01) — court-format-aware PDF export for
drafts.

Mirrors the ``render_version_docx`` shape so the route layer can swap
between the two without changing the lookup / authorization /
citation-gate logic. The PDF path is preferred for filing-grade
output (margins + page numbering + court header are court-rule
sensitive); the DOCX path remains for circulating drafts for markup.

Same citation gate as DOCX: a non-approved draft with zero verified
citations cannot be exported. PRD §6.1 / §17.4.

Court rules sources are pinned in
``services.court_format_profiles``; this module is a thin renderer
over those profiles.
"""

from __future__ import annotations

import io
import json
import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from caseops_api.db.models import DraftStatus
from caseops_api.services.court_format_profiles import (
    CourtFormatProfile,
    resolve_profile,
    validate_required_fields,
)
from caseops_api.services.drafting import _load_draft, _load_matter
from caseops_api.services.session_context import SessionContext


def render_version_pdf(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    draft_id: str,
    version_id: str | None = None,
    court_profile_key: str | None = None,
) -> tuple[bytes, str, str, str, int]:
    """Return ``(pdf_bytes, suggested_filename, profile_key, category, missing_count)``.

    ``court_profile_key`` overrides the auto-resolution from the
    matter's court name. Falls back to the draft's current version
    when ``version_id`` is not supplied.
    """
    matter = _load_matter(session, context, matter_id)
    draft = _load_draft(session, matter, draft_id, context=context)
    target_id = version_id or draft.current_version_id
    if not target_id or not draft.versions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft has no version to export. Generate one first.",
        )
    version = next((v for v in draft.versions if v.id == target_id), None)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft version not found.",
        )

    # Same citation gate as the DOCX path. PRD §6.1 / §17.4 — zero-
    # citation drafts cannot leave the system without explicit partner
    # approval.
    gate_bypassed = draft.status in {DraftStatus.APPROVED, DraftStatus.FINALIZED}
    if not gate_bypassed and (version.verified_citation_count or 0) <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This draft version has zero verified citations. PDF "
                "export is refused until at least one citation is "
                "verified OR the reviewing partner explicitly approves "
                "the draft on record."
            ),
        )

    try:
        profile = resolve_profile(
            explicit_key=court_profile_key,
            court_name=getattr(matter, "court_name", None),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    try:
        citations = json.loads(version.citations_json) if version.citations_json else []
    except json.JSONDecodeError:
        citations = []
    required_field_findings = validate_required_fields(
        profile,
        template_type=draft.template_type or "",
        facts=_draft_facts(draft),
        matter_court_name=getattr(matter, "court_name", None),
    )
    missing_required_field_count = sum(
        1 for finding in required_field_findings if not finding.satisfied
    )

    pdf_bytes = render_pdf_bytes(
        profile=profile,
        title=draft.title,
        matter_title=matter.title,
        matter_code=matter.matter_code,
        draft_type=str(draft.draft_type),
        revision=version.revision,
        status_label=str(draft.status),
        body=version.body,
        citations=citations,
        review_required=draft.review_required,
    )

    safe_title = (
        "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in draft.title).strip("-")[
            :60
        ]
        or "draft"
    )
    filename = f"{safe_title}-r{version.revision}-{profile.key}.pdf"
    return (
        pdf_bytes,
        filename,
        profile.key,
        profile.category,
        missing_required_field_count,
    )


def render_pdf_bytes(
    *,
    profile: CourtFormatProfile,
    title: str,
    matter_title: str,
    matter_code: str,
    draft_type: str,
    revision: int,
    status_label: str,
    body: str,
    citations: list[str],
    review_required: bool,
) -> bytes:
    """Pure-function PDF renderer. Separated from ``render_version_pdf``
    so unit tests can exercise the layout without an authorisation or
    DB session."""
    from fpdf import FPDF  # type: ignore[import-not-found]

    # Subclass so we can inject the running page header + footer (page
    # numbers go through fpdf2's footer hook to ensure consistent
    # placement on every page).
    class CourtFormattedPDF(FPDF):
        def header(self) -> None:  # noqa: D401 — fpdf2 hook
            on_first_page = self.page_no() == 1
            has_header_text = bool(profile.court_header_text)
            if on_first_page and profile.show_court_header_first_page and has_header_text:
                self.set_font(
                    profile.body_font,
                    size=profile.heading_font_size_pt,
                    style="B",
                )
                self.cell(
                    0,
                    8,
                    _ascii_safe(profile.court_header_text),
                    new_x="LMARGIN",
                    new_y="NEXT",
                    align="C",
                )
                self.ln(2)
            elif (
                not on_first_page and profile.show_court_header_subsequent_pages and has_header_text
            ):
                self.set_font(
                    profile.body_font,
                    size=profile.body_font_size_pt - 2,
                    style="I",
                )
                self.cell(
                    0,
                    5,
                    _ascii_safe(profile.court_header_text),
                    new_x="LMARGIN",
                    new_y="NEXT",
                    align="C",
                )
                self.ln(1)

        def footer(self) -> None:
            self.set_y(-15)
            self.set_font(profile.body_font, size=profile.body_font_size_pt - 2, style="I")
            text = _ascii_safe(
                profile.page_number_format.format(
                    n=self.page_no(),
                    total="{nb}",
                )
            )
            align = {"left": "L", "center": "C", "right": "R"}.get(
                profile.page_number_position,
                "R",
            )
            self.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT", align=align)

    pdf = CourtFormattedPDF(format=profile.page_format, unit="mm")
    pdf.set_margins(
        profile.margin_left_mm,
        profile.margin_top_mm,
        profile.margin_right_mm,
    )
    pdf.set_auto_page_break(auto=True, margin=profile.margin_bottom_mm)
    pdf.alias_nb_pages()  # populates {nb} in the footer page-number string
    pdf.add_page()

    # Title block
    pdf.set_font(profile.body_font, size=profile.title_font_size_pt, style="B")
    pdf.multi_cell(
        0,
        8,
        _ascii_safe(title),
        new_x="LMARGIN",
        new_y="NEXT",
        align="C",
    )
    pdf.ln(1)

    # Matter meta — small italic, single line
    pdf.set_font(profile.body_font, size=profile.body_font_size_pt - 2, style="I")
    meta_line = (
        f"Matter: {matter_title} ({matter_code})  ·  "
        f"Type: {draft_type}  ·  Revision {revision}  ·  Status: {status_label}"
    )
    pdf.multi_cell(
        0,
        5,
        _ascii_safe(meta_line),
        new_x="LMARGIN",
        new_y="NEXT",
        align="C",
    )
    pdf.ln(3)

    if review_required:
        pdf.set_font(profile.body_font, size=profile.body_font_size_pt - 1, style="I")
        pdf.multi_cell(
            0,
            5,
            _ascii_safe("REVIEW REQUIRED — this draft has not been approved by a partner."),
            new_x="LMARGIN",
            new_y="NEXT",
            align="C",
        )
        pdf.ln(2)

    # Body — split on blank lines into paragraphs; respect single \n
    # as soft line breaks within a paragraph.
    pdf.set_font(profile.body_font, size=profile.body_font_size_pt)
    for block in (body or "").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        # Soft line breaks become real newlines inside a multi_cell
        # call. fpdf2 handles wrapping at margin width.
        pdf.multi_cell(
            0,
            profile.body_line_height_mm,
            _ascii_safe(block),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(2)

    if citations:
        pdf.ln(2)
        pdf.set_font(profile.body_font, size=profile.heading_font_size_pt, style="B")
        pdf.cell(0, 8, "Authorities cited", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(profile.body_font, size=profile.body_font_size_pt)
        for c in citations:
            pdf.multi_cell(
                0,
                profile.body_line_height_mm,
                _ascii_safe(f"- {c}"),
                new_x="LMARGIN",
                new_y="NEXT",
            )

    out = io.BytesIO()
    out.write(bytes(pdf.output()))
    return out.getvalue()


def _ascii_safe(text: str) -> str:
    """fpdf2's bundled Helvetica is WinAnsi (Latin-1). Drop or remap
    any non-Latin-1 characters so the PDF writer doesn't blow up.

    Same approach as ``services.matter_summary_export``. A future pass
    can subset a TrueType font (Noto Sans Devanagari etc.) to support
    Hindi / Tamil / Bengali bodies natively in the PDF; today those
    bodies should be exported as DOCX.
    """
    if not text:
        return ""
    table = {
        "–": "-",  # en dash
        "—": "--",  # em dash
        "‘": "'",  # left single quote
        "’": "'",  # right single quote
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "…": "...",  # ellipsis
        " ": " ",  # non-breaking space
        "·": "-",  # middle dot — ASCII fallback
        "•": "*",  # bullet
        "→": "->",  # right arrow
        "₹": "INR ",  # rupee sign
    }
    out = text.translate({ord(k): v for k, v in table.items()})
    try:
        out.encode("latin-1")
    except UnicodeEncodeError:
        # Drop anything Helvetica-1252 can't encode. The DOCX path
        # remains lossless for non-Latin scripts.
        out = re.sub(
            r"[^\x00-\xff]+",
            "?",
            out,
        )
    return out


def _draft_facts(draft: object) -> dict[str, object]:
    facts_json = getattr(draft, "facts_json", None)
    if not facts_json:
        return {}
    try:
        parsed = json.loads(facts_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = ["render_pdf_bytes", "render_version_pdf"]
