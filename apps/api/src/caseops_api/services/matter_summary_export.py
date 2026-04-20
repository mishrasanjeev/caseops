"""Sprint Q7 — export the matter executive summary as DOCX.

Takes an existing ``MatterExecutiveSummary`` (produced by
``services.matter_summary``) plus the matter's ``MatterTimeline``
(Sprint Q8) and renders both into a ready-to-download DOCX.

PDF export is a planned follow-up once we add ``fpdf2`` to the
dependency set — shipping DOCX now avoids a new native-dep ask and
covers ~80 % of the filing-ready use-case (lawyers routinely circulate
DOCX for markup).

The renderer is a pure function over the input dataclasses so it is
easy to unit-test without a live LLM call.
"""
from __future__ import annotations

import re
from io import BytesIO

from caseops_api.services.matter_summary import MatterExecutiveSummary
from caseops_api.services.matter_timeline import MatterTimeline


def render_summary_docx(
    *,
    matter_title: str,
    matter_code: str,
    summary: MatterExecutiveSummary,
    timeline: MatterTimeline,
) -> tuple[bytes, str]:
    """Return ``(bytes, filename)`` for the summary DOCX.

    Filename is derived from ``matter_code`` so it lands in the
    caller's downloads folder with an obvious association to the
    matter. Whitespace / slashes in the code are collapsed to hyphens.
    """
    from docx import Document  # type: ignore[import-not-found]
    from docx.shared import Pt

    doc = Document()

    title = doc.add_heading("Matter Executive Summary", level=1)
    for run in title.runs:
        run.font.size = Pt(20)

    meta = doc.add_paragraph()
    meta.add_run(f"{matter_title} ({matter_code})").bold = True
    meta.add_run("  ·  ")
    meta.add_run(
        f"Generated {summary.generated_at.strftime('%d %b %Y, %H:%M')}"
    ).italic = True

    doc.add_paragraph()  # spacer

    if summary.overview:
        doc.add_heading("Overview", level=2)
        doc.add_paragraph(summary.overview)

    if summary.key_facts:
        doc.add_heading("Key facts", level=2)
        for fact in summary.key_facts:
            doc.add_paragraph(fact, style="List Bullet")

    if summary.legal_issues:
        doc.add_heading("Legal issues", level=2)
        for issue in summary.legal_issues:
            doc.add_paragraph(issue, style="List Bullet")

    if summary.sections_cited:
        doc.add_heading("Statutes and sections cited", level=2)
        for sec in summary.sections_cited:
            doc.add_paragraph(sec, style="List Bullet")

    # Prefer the merged Q8 timeline over the summary's own guess —
    # Q8 is grounded in hearings / deadlines / court orders, not an
    # LLM hallucination.
    if timeline.events:
        doc.add_heading("Timeline", level=2)
        for event in timeline.events:
            p = doc.add_paragraph(style="List Number")
            p.add_run(f"{event.event_date.isoformat()} — ").bold = True
            p.add_run(f"{event.title}. ")
            p.add_run(event.summary)
    elif summary.timeline:
        # Fallback: LLM-generated timeline if there's nothing structured.
        doc.add_heading("Timeline (AI summary)", level=2)
        for event in summary.timeline:
            p = doc.add_paragraph(style="List Number")
            prefix = event.date or "—"
            p.add_run(f"{prefix} — ").bold = True
            p.add_run(event.label)

    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.add_run(
        "AI-assisted summary. Every cited statute traces to documents "
        "attached to this matter. Review before filing or circulating."
    ).italic = True

    buf = BytesIO()
    doc.save(buf)
    filename = _safe_filename(matter_code) + "-summary.docx"
    return buf.getvalue(), filename


def _safe_filename(matter_code: str) -> str:
    """Collapse whitespace / slashes to hyphens so the download is
    safe on every OS."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (matter_code or "matter").strip())
    return cleaned.strip("-") or "matter"


__all__ = ["render_summary_docx"]
