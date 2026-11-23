"""PG-005 Sprint 3 (2026-05-01) — court-format-aware PDF export for
drafts.

Mirrors the ``render_version_docx`` shape so the route layer can swap
between the two without changing the lookup / authorization /
citation-gate logic. This is a review PDF using legacy layout presets;
content approval does not verify the preset against current filing rules.

Same citation gate as DOCX: a non-approved draft with zero verified
citations cannot be exported. PRD §6.1 / §17.4.

The presets lack reviewed legal-source provenance. This renderer does not
invent missing pleading structure or repair the approved source content.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from caseops_api.db.models import DraftStatus
from caseops_api.services.court_format_profiles import (
    CourtFormatProfile,
    resolve_profile,
    validate_required_fields,
)
from caseops_api.services.drafting import _load_draft, _load_manifest, _load_matter
from caseops_api.services.drafting_format_blocks import (
    EXECUTION_COLUMN_SHARES,
    EXECUTION_PADDING_MM,
    ExecutionTable,
    FormatStructureError,
    document_blocks,
)
from caseops_api.services.session_context import SessionContext

ExecutionRowLayout = tuple[list[str], list[str], list[str]]


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
        from caseops_api.services.drafting_formats import read_format_reference

        template_manifest = _load_manifest(version.template_manifest_json, {})
        presentation = read_format_reference(template_manifest)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The saved document format reference is unavailable. "
                "Regenerate or review this version before export."
            ),
        ) from None
    try:
        noncourt = presentation and presentation["family"] in {
            "notice", "correspondence_reply", "deed",
        }
        profile = resolve_profile(
            explicit_key=court_profile_key or ("generic" if noncourt else None),
            court_name=None if noncourt else getattr(matter, "court_name", None),
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
    if presentation and presentation["family"] in {"notice", "correspondence_reply", "deed"}:
        required_field_findings = []
    missing_required_field_count = sum(
        1 for finding in required_field_findings if not finding.satisfied
    )

    try:
        pdf_bytes = render_pdf_bytes(
            profile=profile, title=draft.title, matter_title=matter.title,
            matter_code=matter.matter_code, draft_type=str(draft.draft_type),
            revision=version.revision, status_label=str(draft.status), body=version.body,
            citations=citations, review_required=draft.review_required,
            created_at=version.created_at, template_manifest=template_manifest,
        )
    except FormatStructureError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc),
        ) from None

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
    created_at: datetime | None = None,
    template_manifest: object = None,
) -> bytes:
    """Pure-function PDF renderer. Separated from ``render_version_pdf``
    so unit tests can exercise the layout without an authorisation or
    DB session."""
    from caseops_api.services.drafting_formats import read_format_reference
    from caseops_api.services.pdf_layout import safe_pdf_class

    presentation = read_format_reference(template_manifest)
    body_blocks = list(document_blocks(body or "", presentation)) if presentation else []
    if presentation and presentation["family"] != "registry":
        from dataclasses import replace

        profile = replace(
            profile, show_court_header_first_page=False,
            show_court_header_subsequent_pages=False,
        )

    pdf_class = safe_pdf_class()

    # Subclass so we can inject the running page header + footer (page
    # numbers go through fpdf2's footer hook to ensure consistent
    # placement on every page).
    class CourtFormattedPDF(pdf_class):
        def header(self) -> None:  # noqa: D401 — fpdf2 hook
            on_first_page = self.page_no() == 1
            has_header_text = bool(profile.court_header_text)
            if on_first_page and profile.show_court_header_first_page and has_header_text:
                self.set_font(
                    profile.body_font,
                    size=profile.heading_font_size_pt,
                    style="B",
                )
                self.multi_cell(
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
                self.multi_cell(
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
    if created_at is not None:
        # Stable snapshot bytes allow download-time reauthorization to reject a
        # changed profile/content/review state without substituting unseen output.
        pdf.set_creation_date(
            created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
        )
    pdf.set_subject(
        f"court-profile={profile.key}; layout-sha256={profile.layout_digest}; rules=unverified"
    )
    pdf.set_margins(
        profile.margin_left_mm,
        profile.margin_top_mm,
        profile.margin_right_mm,
    )
    pdf.set_auto_page_break(auto=True, margin=profile.margin_bottom_mm)
    pdf.alias_nb_pages()  # populates {nb} in the footer page-number string
    pdf.add_page()

    # New reference versions carry their caption/title in the approved body.
    # Legacy versions retain the existing title and metadata presentation.
    if not presentation:
        pdf.set_font(profile.body_font, size=profile.title_font_size_pt, style="B")
        pdf.multi_cell(
            0, 8, _ascii_safe(title), new_x="LMARGIN", new_y="NEXT", align="C",
        )
        pdf.ln(1)

    # Matter meta — small italic, single line
    pdf.set_font(profile.body_font, size=profile.body_font_size_pt - 2, style="I")
    meta_line = (
        f"Matter: {matter_title} ({matter_code})  ·  "
        f"Type: {draft_type}  ·  Revision {revision}  ·  Status: {status_label}"
    )
    if not presentation:
        pdf.multi_cell(
            0, 5, _ascii_safe(meta_line), new_x="LMARGIN", new_y="NEXT", align="C",
        )
        pdf.ln(3)
    else:
        pdf.set_title(title)
        pdf.set_keywords(
            f"format={presentation['version']}; source={presentation['source_sha256']}; "
            f"profile={presentation['profile']}; revision={revision}; status={status_label}"
        )

    pdf.set_font(profile.body_font, size=profile.body_font_size_pt - 2, style="I")
    pdf.multi_cell(
        0,
        5,
        _ascii_safe(
            "Lawyer review required before signing, registration or service."
            if presentation and presentation["family"] in {"notice", "correspondence_reply", "deed"}
            else f"Layout preset: {profile.key}. Court rules unverified; lawyer review required."
        ),
        new_x="LMARGIN",
        new_y="NEXT",
        align="C",
    )
    pdf.ln(2)

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
    for block in (() if presentation else (body or "").split("\n\n")):
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

    if presentation:
        previous_blank = False
        signature_end = 0
        table_layouts: dict[int, list[ExecutionRowLayout]] = {}
        for block_index, block in enumerate(body_blocks):
            if isinstance(block, ExecutionTable):
                layout = table_layouts.get(block_index)
                if layout is None:
                    layout = _execution_table_layout(pdf, block, profile)
                _draw_execution_table(pdf, layout, profile)
                previous_blank = False
                continue
            line = block
            blank = not line.text.strip()
            if blank:
                if not previous_blank:
                    pdf.ln(2)
                previous_blank = True
                continue
            previous_blank = False
            height = profile.body_line_height_mm
            pdf.set_font(
                profile.body_font,
                size=profile.body_font_size_pt,
                style="B" if line.bold else "",
            )
            if line.alignment == "R":
                if line.keep_with_next and block_index >= signature_end:
                    # Recognized signature labels are short, single-line paragraphs.
                    # Reserve the whole contiguous block once, including its last line.
                    signature_end = block_index + 1
                    while signature_end < len(body_blocks):
                        following = body_blocks[signature_end]
                        if isinstance(following, ExecutionTable) or following.alignment != "R":
                            break
                        signature_end += 1
                    signature_height = (signature_end - block_index) * height
                    if signature_height <= pdf.eph and pdf.will_page_break(signature_height):
                        pdf.add_page()
            elif line.keep_with_next:
                # Measure the actual wrapped heading; two assumed physical
                # lines cannot keep a long caption with the next body line.
                heading_height = pdf.multi_cell(
                    0, height, _ascii_safe(line.text),
                    new_x="LMARGIN", new_y="NEXT", align=line.alignment,
                    dry_run=True, output="HEIGHT",
                )
                next_index = None
                for index in range(block_index + 1, len(body_blocks)):
                    following = body_blocks[index]
                    if isinstance(following, ExecutionTable) or following.text.strip():
                        next_index = index
                        break
                next_height = height
                if next_index is not None:
                    next_table = body_blocks[next_index]
                    if isinstance(next_table, ExecutionTable):
                        layout = _execution_table_layout(pdf, next_table, profile)
                        table_layouts[next_index] = layout
                        next_height = (
                            max(len(layout[0][0]), len(layout[0][1])) * height
                            + 2 * EXECUTION_PADDING_MM
                        )
                if pdf.will_page_break(float(heading_height) + next_height + 2):
                    pdf.add_page()
            pdf.multi_cell(
                0, height, _ascii_safe(line.text),
                new_x="LMARGIN", new_y="NEXT", align=line.alignment,
            )

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


def _execution_table_layout(
    pdf: Any, table: ExecutionTable, profile: CourtFormatProfile,
) -> list[ExecutionRowLayout]:
    """Measure the same fonts/widths used for drawing, with no emitted bytes."""
    widths = tuple(pdf.epw * share for share in EXECUTION_COLUMN_SHARES)
    layout = []
    with pdf.local_context():
        for row in table.rows:
            cells = []
            for index, text in enumerate((row.ordinal, row.particular, row.value)):
                pdf.set_font(
                    profile.body_font, size=profile.body_font_size_pt,
                    style="B" if index < 2 else "",
                )
                lines = pdf.multi_cell(
                    widths[index] - 2 * EXECUTION_PADDING_MM,
                    profile.body_line_height_mm, _ascii_safe(text),
                    dry_run=True, output="LINES", new_x="LMARGIN", new_y="NEXT",
                )
                cells.append(lines or [""])
            layout.append((cells[0], cells[1], cells[2]))
    return layout


def _draw_execution_table(
    pdf: Any, layout: list[ExecutionRowLayout], profile: CourtFormatProfile,
) -> None:
    """Split tall values across pages without clipping or repeating source text."""
    widths = tuple(pdf.epw * share for share in EXECUTION_COLUMN_SHARES)
    padding = EXECUTION_PADDING_MM
    height = profile.body_line_height_mm
    for number_lines, label_lines, value_lines in layout:
        offset = 0
        first = True
        total = max(len(number_lines), len(label_lines), len(value_lines))
        while offset < total:
            available = int((pdf.h - pdf.b_margin - pdf.get_y() - 2 * padding) // height)
            minimum = max(len(number_lines), len(label_lines)) if first else 1
            if available < minimum:
                pdf.add_page()
                available = int(
                    (pdf.h - pdf.b_margin - pdf.get_y() - 2 * padding) // height
                )
                if available < minimum:
                    raise FormatStructureError(
                        "The execution table label cannot fit this layout.",
                    )
            count = min(available, total - offset)
            row_height = count * height + 2 * padding
            left, top = pdf.l_margin, pdf.get_y()
            cell_lines = (
                number_lines if first else [], label_lines if first else [],
                value_lines[offset:offset + count],
            )
            # Each graphics context belongs to one physical page. Restoring a
            # pre-table font state after several pages can leave its cached
            # "font already emitted" flag attached to the wrong page.
            with pdf.local_context(draw_color=(0, 0, 0), line_width=0.15):
                for index, lines in enumerate(cell_lines):
                    x = left + sum(widths[:index])
                    pdf.rect(x, top, widths[index], row_height)
                    if lines:
                        pdf.set_xy(x + padding, top + padding)
                        pdf.set_font(
                            profile.body_font, size=profile.body_font_size_pt,
                            style="B" if index < 2 else "",
                        )
                        pdf.multi_cell(
                            widths[index] - 2 * padding, height, "\n".join(lines),
                            align="C" if index == 0 else "L",
                            new_x="LMARGIN", new_y="NEXT",
                        )
            pdf.set_xy(left, top + row_height)
            first = False
            offset += count


def _ascii_safe(text: str) -> str:
    """Compatibility name; preserve the original text with pinned PDF fonts."""
    from caseops_api.services.pdf_layout import pdf_text

    return pdf_text(text)


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
