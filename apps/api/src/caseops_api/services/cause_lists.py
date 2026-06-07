from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    CauseListExport,
    CompanyMembership,
    Matter,
    MatterCauseListEntry,
    MatterHearing,
    MatterStatus,
)
from caseops_api.schemas.cause_lists import (
    CauseListPreviewRequest,
    CauseListPreviewResponse,
    CauseListRow,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import visible_matters_filter

PDF_TEMPLATE_VERSION = "caseops-cause-list-v1"
_MISSING = "Not available"


def _now() -> datetime:
    return datetime.now(UTC)


def _filters(payload: CauseListPreviewRequest) -> dict[str, object]:
    return payload.model_dump(mode="json")


def _value_or_missing(value: str | None, warnings: list[str], label: str) -> str:
    cleaned = (value or "").strip()
    if cleaned:
        return cleaned
    warnings.append(f"{label} not available")
    return _MISSING


def _lawyers(matter: Matter, warnings: list[str]) -> str:
    assignee = matter.assignee_membership
    if assignee and assignee.user:
        return assignee.user.full_name or assignee.user.email or _MISSING
    warnings.append("lawyers appearing not available")
    return _MISSING


def _case_number(matter: Matter, source_ref: str | None, warnings: list[str]) -> str:
    value = matter.case_number or matter.cnr_number or source_ref
    return _value_or_missing(value, warnings, "case number")


def _case_title(matter: Matter, warnings: list[str]) -> str:
    return _value_or_missing(matter.title, warnings, "case title")


def _file_number(matter: Matter, warnings: list[str]) -> str:
    return _value_or_missing(matter.matter_code, warnings, "file number")


def _apply_matter_filters(
    session: Session,
    stmt,
    *,
    context: SessionContext,
    payload: CauseListPreviewRequest,
):
    stmt = stmt.where(Matter.company_id == context.company.id)
    stmt = stmt.where(visible_matters_filter(session, context=context))
    if not payload.include_disposed:
        stmt = stmt.where(Matter.status != MatterStatus.DISPOSED)
    if payload.practice_area:
        stmt = stmt.where(Matter.practice_area == payload.practice_area)
    if payload.matter_status:
        stmt = stmt.where(Matter.status == payload.matter_status)
    if payload.lawyer_membership_id:
        stmt = stmt.where(Matter.assignee_membership_id == payload.lawyer_membership_id)
    return stmt


def _rows_from_hearings(
    session: Session,
    *,
    context: SessionContext,
    payload: CauseListPreviewRequest,
) -> list[CauseListRow]:
    stmt = (
        select(MatterHearing, Matter)
        .join(Matter, Matter.id == MatterHearing.matter_id)
        .options(
            joinedload(MatterHearing.matter)
            .joinedload(Matter.assignee_membership)
            .joinedload(CompanyMembership.user)
        )
        .where(
            MatterHearing.hearing_on >= payload.date_from,
            MatterHearing.hearing_on <= payload.date_to,
        )
    )
    stmt = _apply_matter_filters(session, stmt, context=context, payload=payload)
    if payload.court:
        stmt = stmt.where(MatterHearing.forum_name.ilike(f"%{payload.court.strip()}%"))
    rows: list[CauseListRow] = []
    for hearing, matter in session.execute(stmt).all():
        warnings: list[str] = []
        rows.append(
            CauseListRow(
                serial_number=0,
                file_number=_file_number(matter, warnings),
                court_name=_value_or_missing(hearing.forum_name, warnings, "court name"),
                case_number=_case_number(matter, None, warnings),
                case_title=_case_title(matter, warnings),
                judge_name=_value_or_missing(
                    hearing.judge_name or matter.judge_name,
                    warnings,
                    "judge name",
                ),
                court_number=_MISSING,
                item_number=_MISSING,
                lawyers_appearing=_lawyers(matter, warnings),
                hearing_date=hearing.hearing_on,
                source="hearings",
                source_ref=hearing.id,
                missing_field_warnings=[
                    *warnings,
                    "court number not available",
                    "item number not available",
                ],
            )
        )
    return rows


def _rows_from_cause_entries(
    session: Session,
    *,
    context: SessionContext,
    payload: CauseListPreviewRequest,
) -> list[CauseListRow]:
    stmt = (
        select(MatterCauseListEntry, Matter)
        .join(Matter, Matter.id == MatterCauseListEntry.matter_id)
        .options(
            joinedload(MatterCauseListEntry.matter)
            .joinedload(Matter.assignee_membership)
            .joinedload(CompanyMembership.user)
        )
        .where(
            MatterCauseListEntry.listing_date >= payload.date_from,
            MatterCauseListEntry.listing_date <= payload.date_to,
        )
    )
    stmt = _apply_matter_filters(session, stmt, context=context, payload=payload)
    if payload.court:
        stmt = stmt.where(MatterCauseListEntry.forum_name.ilike(f"%{payload.court.strip()}%"))
    rows: list[CauseListRow] = []
    for entry, matter in session.execute(stmt).all():
        warnings: list[str] = []
        rows.append(
            CauseListRow(
                serial_number=0,
                file_number=_file_number(matter, warnings),
                court_name=_value_or_missing(entry.forum_name, warnings, "court name"),
                case_number=_case_number(matter, entry.source_reference, warnings),
                case_title=_case_title(matter, warnings),
                judge_name=_value_or_missing(
                    entry.bench_name or matter.judge_name,
                    warnings,
                    "judge name",
                ),
                court_number=_value_or_missing(entry.courtroom, warnings, "court number"),
                item_number=_value_or_missing(entry.item_number, warnings, "item number"),
                lawyers_appearing=_lawyers(matter, warnings),
                hearing_date=entry.listing_date,
                source="cause_list_entries",
                source_ref=entry.id,
                missing_field_warnings=warnings,
            )
        )
    return rows


def preview_cause_list(
    session: Session,
    *,
    context: SessionContext,
    payload: CauseListPreviewRequest,
) -> CauseListPreviewResponse:
    rows: list[CauseListRow] = []
    if payload.source in {"hearings", "both"}:
        rows.extend(_rows_from_hearings(session, context=context, payload=payload))
    if payload.source in {"cause_list_entries", "both"}:
        rows.extend(_rows_from_cause_entries(session, context=context, payload=payload))
    if payload.sort == "court":
        rows.sort(key=lambda row: (row.court_name, row.hearing_date, row.file_number))
    elif payload.sort == "lawyer":
        rows.sort(key=lambda row: (row.lawyers_appearing, row.hearing_date, row.file_number))
    else:
        rows.sort(key=lambda row: (row.hearing_date, row.court_name, row.file_number))
    for index, row in enumerate(rows, start=1):
        row.serial_number = index
    return CauseListPreviewResponse(
        generated_at=_now(),
        filters=_filters(payload),
        rows=rows,
    )


def render_cause_list_pdf(
    session: Session,
    *,
    context: SessionContext,
    payload: CauseListPreviewRequest,
) -> tuple[bytes, str, str, int]:
    from fpdf import FPDF  # type: ignore[import-not-found]

    preview = preview_cause_list(session, context=context, payload=payload)
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=14)

    def header() -> None:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Cause List", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(
            0,
            5,
            f"Dates: {payload.date_from.isoformat()} to {payload.date_to.isoformat()} | "
            f"Generated: {preview.generated_at.isoformat()}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        filter_bits = [
            f"source={payload.source}",
            f"court={payload.court or 'all'}",
            f"practice={payload.practice_area or 'all'}",
            f"status={payload.matter_status or 'all'}",
            f"include_disposed={payload.include_disposed}",
        ]
        pdf.cell(0, 5, "Filters: " + ", ".join(filter_bits), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 6)
        for label, width in [
            ("Sr", 8),
            ("File", 22),
            ("Court", 31),
            ("Case No", 28),
            ("Title", 39),
            ("Judge", 25),
            ("Court/Item", 18),
            ("Lawyer", 28),
        ]:
            pdf.cell(width, 6, label, border=1)
        pdf.ln()

    pdf.add_page()
    header()
    pdf.set_font("Helvetica", "", 6)
    for row in preview.rows:
        if pdf.get_y() > 270:
            pdf.cell(0, 4, f"Page {pdf.page_no()}", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.add_page()
            header()
            pdf.set_font("Helvetica", "", 6)
        values = [
            str(row.serial_number),
            row.file_number,
            row.court_name,
            row.case_number,
            row.case_title,
            row.judge_name,
            f"{row.court_number}/{row.item_number}",
            row.lawyers_appearing,
        ]
        widths = [8, 22, 31, 28, 39, 25, 18, 28]
        for value, width in zip(values, widths, strict=True):
            pdf.cell(width, 6, str(value)[:32], border=1)
        pdf.ln()
    if not preview.rows:
        pdf.cell(0, 8, "No matters found for the selected filters.", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(-12)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, f"Page {pdf.page_no()}", align="C")
    body = bytes(pdf.output())
    checksum = hashlib.sha256(body).hexdigest()
    filename = (
        f"cause-list-{payload.date_from.isoformat()}-to-{payload.date_to.isoformat()}.pdf"
    )
    export = CauseListExport(
        company_id=context.company.id,
        generated_by_membership_id=context.membership.id,
        date_from=payload.date_from,
        date_to=payload.date_to,
        filters_json=_filters(payload),
        row_count=len(preview.rows),
        format="pdf",
        file_name=filename,
        checksum=checksum,
    )
    session.add(export)
    record_from_context(
        session,
        context,
        action="cause_list.pdf.downloaded",
        target_type="cause_list_export",
        target_id=export.id,
        metadata={
            "filters": _filters(payload),
            "row_count": len(preview.rows),
            "file_name": filename,
            "checksum": checksum,
            "template_version": PDF_TEMPLATE_VERSION,
        },
    )
    session.commit()
    return body, filename, checksum, len(preview.rows)
