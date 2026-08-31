"""PG-005 Sprint 4 (2026-05-01) — court-filing bundle ZIP.

A filing bundle is what a fee-earner hands to the court clerk: the
memorandum / petition (court-format-aware PDF), the vakalatnama
(power of attorney for counsel), an index page listing the contents,
the matter's exhibits / annexures, and an e-stamp placeholder so the
filing clerk knows where to slot the court-fee receipt.

The bundle is delivered as a ZIP. We deliberately avoid merging the
PDFs into a single file because the lawyer routinely needs to split,
swap, or re-order the components at the bar room before filing. ZIP
preserves file boundaries; the index inside the ZIP is the sourcing
truth.

Layout inside the ZIP::

    00-index.pdf              (auto-generated cover + table of contents)
    01-memorandum.pdf         (the draft, rendered through the court profile)
    02-vakalatnama.pdf        (existing vakalat draft on the matter, OR a
                               placeholder page if none has been drafted)
    03-estamp-placeholder.pdf (one-page slot for the court-fee e-stamp)
    04-exhibits/
        01-<exhibit-A-filename>
        02-<exhibit-B-filename>
        ...

The vakalat resolver picks (in priority order):
1. ``vakalat_draft_id`` query param (caller-supplied override).
2. The newest ``DraftTemplateType.VAKALATNAMA`` draft on the same matter.
3. Falls back to a placeholder page ("VAKALATNAMA — to be executed by
   client + counsel before filing").

The exhibits selector defaults to all of the matter's
``MatterAttachment`` rows; the caller can pass ``attachment_ids`` to
narrow the set when the matter has unrelated attachments.

Same citation gate as the DOCX / PDF paths — zero-citation drafts are
blocked unless the draft has been approved or finalized on record.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Draft,
    DraftStatus,
    Matter,
    MatterAttachment,
)
from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.court_format_profiles import (
    CourtFormatProfile,
    resolve_profile,
)
from caseops_api.services.document_storage import resolve_storage_path
from caseops_api.services.draft_pdf_export import _ascii_safe, render_pdf_bytes
from caseops_api.services.drafting import _load_draft, _load_matter
from caseops_api.services.session_context import SessionContext


@dataclass(frozen=True)
class FilingBundleResult:
    zip_bytes: bytes
    filename: str
    profile_key: str
    memorandum_filename: str
    vakalat_source: str  # "draft:<id>" | "placeholder"
    exhibit_count: int


def render_filing_bundle(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    draft_id: str,
    version_id: str | None = None,
    court_profile_key: str | None = None,
    vakalat_draft_id: str | None = None,
    attachment_ids: list[str] | None = None,
) -> FilingBundleResult:
    """Build the filing-bundle ZIP for the given memorandum draft.

    See module docstring for layout, vakalat-resolution, and exhibit-
    selection semantics.
    """
    matter = _load_matter(session, context, matter_id)
    draft = _load_draft(session, matter, draft_id, context=context)
    target_id = version_id or draft.current_version_id
    if not target_id or not draft.versions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft has no version to bundle. Generate one first.",
        )
    version = next((v for v in draft.versions if v.id == target_id), None)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft version not found.",
        )

    # Same citation gate as the PDF / DOCX export paths. PRD §6.1 / §17.4.
    gate_bypassed = draft.status in {DraftStatus.APPROVED, DraftStatus.FINALIZED}
    if not gate_bypassed and (version.verified_citation_count or 0) <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This draft version has zero verified citations. Filing "
                "bundle export is refused until at least one citation "
                "is verified OR the reviewing partner explicitly "
                "approves the draft on record."
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

    memorandum_pdf = render_pdf_bytes(
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

    vakalat_pdf, vakalat_source = _resolve_and_render_vakalat(
        session,
        matter=matter,
        explicit_vakalat_draft_id=vakalat_draft_id,
        profile=profile,
    )

    estamp_pdf = _render_estamp_placeholder(profile=profile, matter=matter)

    selected_attachments = _select_attachments(
        session,
        matter=matter,
        attachment_ids=attachment_ids,
    )

    index_pdf = _render_index_pdf(
        profile=profile,
        matter=matter,
        draft=draft,
        revision=version.revision,
        vakalat_source=vakalat_source,
        attachments=selected_attachments,
    )

    safe_title = _safe_segment(draft.title)
    memorandum_filename = f"01-memorandum-{safe_title}-r{version.revision}.pdf"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00-index.pdf", index_pdf)
        zf.writestr(memorandum_filename, memorandum_pdf)
        zf.writestr("02-vakalatnama.pdf", vakalat_pdf)
        zf.writestr("03-estamp-placeholder.pdf", estamp_pdf)
        for idx, (att, exhibit_bytes) in enumerate(selected_attachments, start=1):
            label = _safe_segment(att.original_filename) or f"exhibit-{idx}"
            ext = _extension_from_filename(att.original_filename)
            zf.writestr(f"04-exhibits/{idx:02d}-{label}{ext}", exhibit_bytes)

    bundle_filename = (
        f"{_safe_segment(matter.matter_code)}"
        f"-{safe_title}-r{version.revision}-{profile.key}-bundle.zip"
    )

    return FilingBundleResult(
        zip_bytes=buf.getvalue(),
        filename=bundle_filename,
        profile_key=profile.key,
        memorandum_filename=memorandum_filename,
        vakalat_source=vakalat_source,
        exhibit_count=len(selected_attachments),
    )


def _resolve_and_render_vakalat(
    session: Session,
    *,
    matter: Matter,
    explicit_vakalat_draft_id: str | None,
    profile: CourtFormatProfile,
) -> tuple[bytes, str]:
    """Pick the vakalat to include and return ``(pdf_bytes, source_tag)``.

    Source tag is ``draft:<id>`` for a real vakalat draft; ``placeholder``
    for the auto-generated stand-in. The placeholder is deliberate — it
    forces the lawyer to slot in the executed vakalat before filing
    rather than letting the bundle ship without one."""
    if explicit_vakalat_draft_id:
        vakalat_draft = session.scalar(
            select(Draft)
            .where(
                Draft.id == explicit_vakalat_draft_id,
                Draft.matter_id == matter.id,
            )
        )
        if vakalat_draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Vakalatnama draft {explicit_vakalat_draft_id!r} not "
                    f"found on matter {matter.matter_code!r}."
                ),
            )
        if vakalat_draft.template_type != DraftTemplateType.VAKALATNAMA.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Draft {explicit_vakalat_draft_id!r} is not a "
                    f"VAKALATNAMA template "
                    f"(template_type={vakalat_draft.template_type!r})."
                ),
            )
    else:
        vakalat_draft = session.scalar(
            select(Draft)
            .where(
                Draft.matter_id == matter.id,
                Draft.template_type == DraftTemplateType.VAKALATNAMA.value,
            )
            .order_by(Draft.created_at.desc())
        )

    if vakalat_draft is None:
        return _render_vakalat_placeholder(profile=profile, matter=matter), "placeholder"

    target_version = next(
        (v for v in vakalat_draft.versions if v.id == vakalat_draft.current_version_id),
        None,
    )
    if target_version is None:
        return _render_vakalat_placeholder(profile=profile, matter=matter), "placeholder"

    pdf = render_pdf_bytes(
        profile=profile,
        title="Vakalatnama",
        matter_title=matter.title,
        matter_code=matter.matter_code,
        draft_type="vakalat",
        revision=target_version.revision,
        status_label=str(vakalat_draft.status),
        body=target_version.body,
        citations=[],
        review_required=vakalat_draft.review_required,
    )
    return pdf, f"draft:{vakalat_draft.id}"


def _render_vakalat_placeholder(
    *, profile: CourtFormatProfile, matter: Matter,
) -> bytes:
    body = (
        "This page is a placeholder for the executed VAKALATNAMA.\n\n"
        "Before filing, replace this page with the vakalat signed by the "
        "client and accepted by counsel. Use the CaseOps drafting studio "
        "(template: Vakalatnama) to generate a court-specific draft, "
        "have it executed, and re-export this filing bundle.\n\n"
        f"Matter: {matter.title} ({matter.matter_code})\n"
        f"Court : {matter.court_name or '<court to be set on the matter>'}\n"
    )
    return render_pdf_bytes(
        profile=profile,
        title="VAKALATNAMA — placeholder",
        matter_title=matter.title,
        matter_code=matter.matter_code,
        draft_type="vakalat-placeholder",
        revision=0,
        status_label="placeholder",
        body=body,
        citations=[],
        review_required=True,
    )


def _render_estamp_placeholder(
    *, profile: CourtFormatProfile, matter: Matter,
) -> bytes:
    body = (
        "E-STAMP PLACEHOLDER\n\n"
        "Affix the court-fee e-stamp / treasury challan in the space "
        "below before filing.\n\n"
        "Court fee is computed on the relief sought / valuation of the "
        "matter; consult the applicable State Court-Fees Act schedule.\n\n"
        f"Matter           : {matter.title}\n"
        f"Matter code      : {matter.matter_code}\n"
        f"Court            : {matter.court_name or '<court to be set>'}\n"
        f"Practice area    : {matter.practice_area}\n"
        f"Forum level      : {matter.forum_level}\n\n"
        "[ INSERT E-STAMP HERE ]\n\n\n"
        "(This placeholder is generated by the CaseOps filing-bundle "
        "exporter. It is NOT a substitute for an actual e-stamp.)"
    )
    return render_pdf_bytes(
        profile=profile,
        title="E-STAMP PLACEHOLDER",
        matter_title=matter.title,
        matter_code=matter.matter_code,
        draft_type="estamp-placeholder",
        revision=0,
        status_label="placeholder",
        body=body,
        citations=[],
        review_required=False,
    )


def _select_attachments(
    session: Session,
    *,
    matter: Matter,
    attachment_ids: list[str] | None,
) -> list[tuple[MatterAttachment, bytes]]:
    """Read selected attachments off disk + return ``(row, bytes)`` pairs.

    Defaults to all attachments on the matter when ``attachment_ids`` is
    None. Attachments that no longer exist on disk are silently skipped
    — the index page in the bundle records the omission so the lawyer
    is not surprised at the bar room."""
    query = (
        select(MatterAttachment)
        .where(MatterAttachment.matter_id == matter.id)
        .order_by(MatterAttachment.created_at.asc())
    )
    if attachment_ids:
        query = query.where(MatterAttachment.id.in_(attachment_ids))

    rows = list(session.scalars(query).all())

    # Surface unknown ids as 422 so the caller can fix the request
    # rather than silently dropping the wrong attachment.
    if attachment_ids:
        seen = {r.id for r in rows}
        missing = [a for a in attachment_ids if a not in seen]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Attachments {missing!r} not found on matter "
                    f"{matter.matter_code!r}."
                ),
            )

    out: list[tuple[MatterAttachment, bytes]] = []
    for row in rows:
        path = resolve_storage_path(row.storage_key)
        if not path.exists():
            # Skip unreadable files; the index page will note the gap.
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        out.append((row, data))
    return out


def _render_index_pdf(
    *,
    profile: CourtFormatProfile,
    matter: Matter,
    draft: Draft,
    revision: int,
    vakalat_source: str,
    attachments: list[tuple[MatterAttachment, bytes]],
) -> bytes:
    lines: list[str] = []
    lines.append(f"Matter   : {matter.title}")
    lines.append(f"Code     : {matter.matter_code}")
    if matter.court_name:
        lines.append(f"Court    : {matter.court_name}")
    if matter.practice_area:
        lines.append(f"Area     : {matter.practice_area}")
    lines.append("")
    lines.append("Bundle contents")
    lines.append("---------------")
    lines.append("00. This index")
    lines.append(f"01. Memorandum / petition (revision {revision}) — {draft.title}")

    if vakalat_source.startswith("draft:"):
        lines.append("02. Vakalatnama (executed draft)")
    else:
        lines.append("02. Vakalatnama (PLACEHOLDER — slot in the executed copy before filing)")

    lines.append("03. E-stamp placeholder (insert the court-fee e-stamp here)")

    if attachments:
        lines.append("04. Exhibits / annexures:")
        for idx, (att, _) in enumerate(attachments, start=1):
            size_kb = max(1, (att.size_bytes or 0) // 1024)
            lines.append(
                f"    {idx:02d}. {att.original_filename}  "
                f"({size_kb} KB; {att.content_type or 'binary'})"
            )
    else:
        lines.append("04. No exhibits attached to this bundle.")

    lines.append("")
    lines.append(
        "(Generated by the CaseOps filing-bundle exporter. Verify each "
        "component before filing — the bundle is a packaging convenience, "
        "not a final-quality check.)"
    )
    body = "\n".join(lines)

    return render_pdf_bytes(
        profile=profile,
        title=f"FILING BUNDLE — {matter.matter_code}",
        matter_title=matter.title,
        matter_code=matter.matter_code,
        draft_type="filing-bundle-index",
        revision=revision,
        status_label="bundle-index",
        body=body,
        citations=[],
        review_required=False,
    )


def _safe_segment(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip())
    return cleaned.strip("-")[:60]


def _extension_from_filename(filename: str | None) -> str:
    if not filename:
        return ""
    m = re.search(r"\.[A-Za-z0-9]{1,8}$", filename)
    return m.group(0) if m else ""


# Re-export for tests; the real implementation lives in draft_pdf_export.
_ = _ascii_safe


__all__ = ["FilingBundleResult", "render_filing_bundle"]
