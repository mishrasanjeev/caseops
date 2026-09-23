# The template's exact user-facing error strings and field maps are intentionally
# kept readable; ruff's 100-column rule is not useful for those bounded literals.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import io
import csv
import json
import os
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, status
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import CompanyMembership, Matter, MatterBulkUpdateOperation, Team
from caseops_api.schemas.matter_bulk_updates import (
    MatterBulkUpdateApplyResponse,
    MatterBulkUpdateHistoryRecord,
    MatterBulkUpdateHistoryResponse,
    MatterBulkUpdatePreviewResponse,
    MatterBulkUpdateRow,
    MatterBulkUpdateSummary,
)
from caseops_api.schemas.matters import MatterUpdateRequest, normalize_matter_code
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matters import update_matter
from caseops_api.services.session_context import SessionContext

HEADERS = [
    "Matter Title",
    "Matter Code",
    "Matter Type",
    "Practice Area",
    "Matter Status",
    "Matter Description",
    "Client Name",
    "Client Code",
    "Client Contact Number",
    "Client Email",
    "Opposing Party Name",
    "Opposing Counsel",
    "Forum",
    "Court",
    "Court Forum Number",
    "Case Number",
    "Filing Number",
    "Filing Date",
    "Matter Owner",
    "Assigned Team",
    "Responsible Lawyer",
    "Temporary E-Case Number",
    "CNR Number",
]
MAX_ROWS = 500
MAX_FILE_BYTES = 5 * 1024 * 1024
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_TYPE = "text/csv; charset=utf-8"


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _json_value(value: Any) -> object:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Filing Date must be an ISO date such as 2026-09-21.") from exc


def _parse_rows(content: bytes, filename: str) -> tuple[str, list[tuple[int, dict[str, str]]], str]:
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Bulk update file must be {MAX_FILE_BYTES // (1024 * 1024)} MiB or smaller.",
        )
    extension = os.path.splitext(os.path.basename(filename))[1].casefold()
    if extension not in {".xlsx", ".csv"}:
        raise HTTPException(status_code=400, detail="Choose a .xlsx or .csv bulk-update file.")
    manifest_format = extension[1:]
    try:
        if manifest_format == "csv":
            text = content.decode("utf-8-sig", errors="strict")
            reader = csv.reader(io.StringIO(text, newline=""), strict=True)
            values = []
            for row in reader:
                values.append(row)
                if len(values) > MAX_ROWS + 1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Bulk update supports at most {MAX_ROWS} data rows.",
                    )
        else:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            try:
                sheet = workbook.active
                if sheet.max_row is not None and sheet.max_row > MAX_ROWS + 1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Bulk update supports at most {MAX_ROWS} data rows.",
                    )
                values = list(sheet.iter_rows(values_only=True))
            finally:
                workbook.close()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        label = "CSV file" if manifest_format == "csv" else "XLSX workbook"
        raise HTTPException(status_code=400, detail=f"Upload a valid UTF-8 {label}.") from exc
    if not values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The workbook is empty."
        )
    received_headers = [_cell(value) for value in values[0]]
    if received_headers != HEADERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "The bulk update template headers must match exactly.",
                "expected": HEADERS,
                "received": received_headers,
            },
        )
    rows: list[tuple[int, dict[str, str]]] = []
    for row_number, raw in enumerate(values[1:], start=2):
        cells = [_cell(value) for value in raw[: len(HEADERS)]]
        if not any(cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bulk update supports at most {MAX_ROWS} populated rows.",
            )
        rows.append((row_number, dict(zip(HEADERS, cells, strict=False))))
    return hashlib.sha256(content).hexdigest(), rows, manifest_format


def _forum_value(value: str) -> str:
    normalized = " ".join(value.lower().replace("-", " ").replace("_", " ").split())
    mapping = {
        "lower court": "lower_court",
        "district court": "lower_court",
        "high court": "high_court",
        "supreme court": "supreme_court",
        "tribunal": "tribunal",
        "arbitration": "arbitration",
        "advisory": "advisory",
    }
    return mapping.get(normalized, "")


def _resolve_membership(session: Session, *, company_id: str, label: str) -> str | None:
    needle = label.casefold()
    memberships = session.scalars(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user))
        .where(CompanyMembership.company_id == company_id, CompanyMembership.is_active.is_(True))
    )
    matches = [
        membership
        for membership in memberships
        if needle in {membership.user.email.casefold(), membership.user.full_name.casefold()}
    ]
    if len(matches) == 1:
        return matches[0].id
    if not matches:
        raise ValueError(f"No active company member matches '{label}'.")
    raise ValueError(f"'{label}' matches multiple active company members.")


def _resolve_team(session: Session, *, company_id: str, label: str) -> str:
    teams = session.scalars(
        select(Team).where(Team.company_id == company_id, Team.is_active.is_(True))
    )
    matches = [team for team in teams if team.name.casefold() == label.casefold()]
    if len(matches) != 1:
        raise ValueError(f"Assigned Team '{label}' must match one active team exactly.")
    return matches[0].id


def _updates_for_row(
    session: Session, *, context: SessionContext, matter: Matter, row: dict[str, str]
) -> tuple[dict[str, Any], list[str]]:
    updates: dict[str, Any] = {}
    errors: list[str] = []
    mapping = {
        "Matter Title": "title",
        "Matter Type": "matter_type",
        "Practice Area": "practice_area",
        "Matter Description": "description",
        "Client Name": "client_name",
        "Client Code": "client_code",
        "Client Contact Number": "client_contact_number",
        "Client Email": "client_email",
        "Opposing Party Name": "opposing_party",
        "Opposing Counsel": "opposing_counsel",
        "Court": "court_name",
        "Court Forum Number": "court_forum_number",
        "Case Number": "case_number",
        "Filing Number": "filing_number",
        "Temporary E-Case Number": "temporary_e_case_number",
        "CNR Number": "cnr_number",
    }
    for source, target in mapping.items():
        if row[source]:
            updates[target] = row[source]
    if row["Matter Status"]:
        errors.append("Bulk update cannot change Matter Status; use the dedicated matter workflow.")
    if row["Forum"]:
        forum_value = _forum_value(row["Forum"])
        if not forum_value:
            errors.append("Forum must match a supported forum level.")
        else:
            updates["forum_level"] = forum_value
    if row["Filing Date"]:
        try:
            updates["filing_date"] = _parse_date(row["Filing Date"])
        except ValueError as exc:
            errors.append(str(exc))
    for source, target in (
        ("Matter Owner", "assignee_membership_id"),
        ("Responsible Lawyer", "responsible_lawyer_membership_id"),
    ):
        if row[source]:
            try:
                updates[target] = _resolve_membership(
                    session, company_id=context.company.id, label=row[source]
                )
            except ValueError as exc:
                errors.append(str(exc))
    if row["Assigned Team"]:
        try:
            updates["team_id"] = _resolve_team(
                session, company_id=context.company.id, label=row["Assigned Team"]
            )
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        return {}, errors
    try:
        validated = MatterUpdateRequest(
            expected_updated_at=matter.updated_at,
            **updates,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc).split(" [type=")[0])
        return {}, errors
    validated_updates = validated.model_dump(exclude_unset=True)
    validated_updates.pop("expected_updated_at", None)
    return validated_updates, []


def _preview_rows(
    session: Session, *, context: SessionContext, rows: list[tuple[int, dict[str, str]]]
) -> list[MatterBulkUpdateRow]:
    codes = [
        normalize_matter_code(row.get("Matter Code", ""))
        for _, row in rows
        if row.get("Matter Code", "")
    ]
    matters = session.scalars(
        select(Matter).where(Matter.company_id == context.company.id, Matter.matter_code.in_(codes))
    )
    by_code = {matter.matter_code: matter for matter in matters}
    code_counts: dict[str, int] = {}
    for _, row in rows:
        raw_code = row.get("Matter Code", "")
        try:
            code = normalize_matter_code(raw_code)
        except Exception:
            continue
        code_counts[code] = code_counts.get(code, 0) + 1
    result: list[MatterBulkUpdateRow] = []
    for row_number, row in rows:
        raw_code = row.get("Matter Code", "")
        try:
            code = normalize_matter_code(raw_code)
        except Exception:
            code = ""
        matter = by_code.get(code)
        if code and code_counts.get(code, 0) > 1:
            result.append(
                MatterBulkUpdateRow(
                    row_number=row_number,
                    matter_code=code,
                    status="invalid",
                    errors=["Matter Code appears more than once in this file; remove duplicate rows."],
                )
            )
            continue
        if not raw_code or matter is None:
            result.append(
                MatterBulkUpdateRow(
                    row_number=row_number,
                    matter_code=code or raw_code,
                    status="invalid",
                    errors=[
                        "Matter Code must match one existing matter; this workflow never creates matters."
                    ],
                )
            )
            continue
        try:
            assert_access(session, context=context, matter=matter)
            updates, errors = _updates_for_row(session, context=context, matter=matter, row=row)
        except Exception as exc:  # noqa: BLE001
            updates, errors = {}, [str(exc)]
        changes: dict[str, dict[str, object]] = {}
        for field_name, new_value in updates.items():
            old_value = getattr(matter, field_name, None)
            if _json_value(old_value) != _json_value(new_value):
                changes[field_name] = {"old": _json_value(old_value), "new": _json_value(new_value)}
        result.append(
            MatterBulkUpdateRow(
                row_number=row_number,
                matter_id=matter.id,
                matter_code=matter.matter_code,
                status="invalid" if errors else ("changed" if changes else "unchanged"),
                errors=errors,
                changes=changes,
                expected_updated_at=matter.updated_at,
            )
        )
    return result


def preview_matter_bulk_update(
    session: Session, *, context: SessionContext, content: bytes, filename: str
) -> MatterBulkUpdatePreviewResponse:
    file_hash, rows, _ = _parse_rows(content, filename)
    plans = _preview_rows(session, context=context, rows=rows)
    token = _preview_token(file_hash, plans)
    changed = sum(plan.status == "changed" for plan in plans)
    unchanged = sum(plan.status == "unchanged" for plan in plans)
    invalid = sum(plan.status == "invalid" for plan in plans)
    return MatterBulkUpdatePreviewResponse(
        preview_token=token,
        headers=HEADERS,
        summary=MatterBulkUpdateSummary(
            total_rows=len(plans),
            matched_rows=len(plans) - invalid,
            changed_rows=changed,
            unchanged_rows=unchanged,
            invalid_rows=invalid,
        ),
        rows=plans,
    )


def apply_matter_bulk_update(
    session: Session,
    *,
    context: SessionContext,
    content: bytes,
    filename: str,
    preview_token: str,
) -> MatterBulkUpdateApplyResponse:
    file_hash, rows, manifest_format = _parse_rows(content, filename)
    plans = _preview_rows(session, context=context, rows=rows)
    current_token = _preview_token(file_hash, plans)
    safe_filename = os.path.basename(filename).replace("\\", "_").replace("/", "_")[:255] or "upload"
    if current_token != preview_token:
        changed = sum(plan.status == "changed" for plan in plans)
        invalid = sum(plan.status == "invalid" for plan in plans)
        session.add(
            MatterBulkUpdateOperation(
                company_id=context.company.id,
                uploader_membership_id=context.membership.id,
                filename=safe_filename,
                format=manifest_format,
                status="stale",
                total_rows=len(plans),
                changed_rows=changed,
                invalid_rows=invalid,
                applied_rows=0,
                failed_rows=changed,
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A Matter changed after preview or the upload differs; review a fresh preview before applying.",
        )
    applied = 0
    failed = 0
    for plan, (_, raw_row) in zip(plans, rows, strict=True):
        if plan.status != "changed":
            continue
        matter = session.get(Matter, plan.matter_id)
        if matter is None:
            plan.status = "failed"
            plan.errors.append("Matter no longer exists.")
            failed += 1
            continue
        try:
            updates, errors = _updates_for_row(session, context=context, matter=matter, row=raw_row)
            if errors:
                raise ValueError("; ".join(errors))
            updates["expected_updated_at"] = plan.expected_updated_at
            with session.begin_nested():
                update_matter(
                    session,
                    context=context,
                    matter_id=matter.id,
                    payload=MatterUpdateRequest(**updates),
                    commit=False,
                )
            plan.status = "applied"
            applied += 1
        except Exception as exc:  # noqa: BLE001
            plan.status = "failed"
            plan.errors.append(str(exc))
            failed += 1
    failed += sum(plan.status == "invalid" for plan in plans)
    status_value = "completed_with_errors" if failed else "completed"
    operation = MatterBulkUpdateOperation(
        company_id=context.company.id,
        uploader_membership_id=context.membership.id,
        filename=safe_filename,
        format=manifest_format,
        status=status_value,
        total_rows=len(plans),
        changed_rows=sum(bool(plan.changes) for plan in plans),
        invalid_rows=sum(plan.status == "invalid" for plan in plans),
        applied_rows=applied,
        failed_rows=failed,
    )
    session.add(operation)
    session.commit()
    return MatterBulkUpdateApplyResponse(
        preview_token=preview_token,
        applied_rows=applied,
        failed_rows=failed,
        rows=plans,
        operation_id=operation.id,
    )


def _preview_token(file_hash: str, plans: list[MatterBulkUpdateRow]) -> str:
    state = [
        {
            "row": plan.row_number,
            "matter_id": plan.matter_id,
            "status": plan.status,
            "expected_updated_at": plan.expected_updated_at.isoformat()
            if plan.expected_updated_at
            else None,
            "changes": plan.changes,
            "errors": plan.errors,
        }
        for plan in plans
    ]
    payload = json.dumps([file_hash, state], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def matter_bulk_update_template(manifest_format: str) -> tuple[bytes, str, str]:
    if manifest_format == "csv":
        output = io.StringIO(newline="")
        csv.writer(output, lineterminator="\r\n").writerow(HEADERS)
        return output.getvalue().encode("utf-8"), CSV_TYPE, "matter-bulk-update-template.csv"
    if manifest_format != "xlsx":
        raise HTTPException(status_code=400, detail="Format must be csv or xlsx.")
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Matter Updates"
    sheet.append(HEADERS)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue(), XLSX_TYPE, "matter-bulk-update-template.xlsx"


def list_matter_bulk_update_history(
    session: Session, *, context: SessionContext, limit: int = 50
) -> MatterBulkUpdateHistoryResponse:
    query = select(MatterBulkUpdateOperation).where(
        MatterBulkUpdateOperation.company_id == context.company.id
    )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    operations = session.scalars(
        query.options(
            joinedload(MatterBulkUpdateOperation.uploader_membership).joinedload(
                CompanyMembership.user
            )
        )
        .order_by(MatterBulkUpdateOperation.created_at.desc())
        .limit(limit)
    )
    records = []
    for item in operations:
        membership = item.uploader_membership
        records.append(
            MatterBulkUpdateHistoryRecord(
                id=item.id,
                filename=item.filename,
                format=item.format,
                status=item.status,
                total_rows=item.total_rows,
                changed_rows=item.changed_rows,
                invalid_rows=item.invalid_rows,
                applied_rows=item.applied_rows,
                failed_rows=item.failed_rows,
                uploader_membership_id=item.uploader_membership_id,
                uploader_name=membership.user.full_name if membership else None,
                uploader_email=membership.user.email if membership else None,
                created_at=item.created_at,
            )
        )
    return MatterBulkUpdateHistoryResponse(operations=records, total=total)
