from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditResult,
    CompanyMembership,
    EmployeeBulkImportJob,
    EmployeeBulkImportRow,
    EmployeeImportJobStatus,
    EmployeeImportRowStatus,
    EmployeeProfile,
    MembershipRole,
    User,
)
from caseops_api.schemas.employees import (
    EmployeeCreateRequest,
    EmployeeCreateResponse,
    EmployeeImportCommitResponse,
    EmployeeImportJobResponse,
    EmployeeImportRowPreview,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.employees import (
    _create_employee_without_commit,
    _employee_record,
)
from caseops_api.services.identity import SessionContext

EMPLOYEE_IMPORT_MAX_BYTES = 2 * 1024 * 1024
EMPLOYEE_IMPORT_MAX_ROWS = 1000
EMPLOYEE_IMPORT_PREVIEW_TTL = timedelta(hours=24)

CSV_CONTENT_TYPES = {
    "",
    "application/csv",
    "application/octet-stream",
    "application/vnd.ms-excel",
    "text/csv",
}
XLSX_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
ROLE_VALUES = {"admin", "partner", "member", "paralegal", "viewer"}
TEMPLATE_HEADERS = [
    "Name",
    "Email",
    "Role",
    "Mobile",
    "Designation",
    "Department",
    "EmployeeCode",
    "ManagerEmail",
]


@dataclass(frozen=True)
class ParsedImportRow:
    row_number: int
    raw: dict[str, str]
    unsafe_headers: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ValidatedImportRow:
    row_number: int
    raw: dict[str, str]
    normalized: dict[str, object]
    errors: list[str]
    unsafe_formula: bool


def _utcnow() -> datetime:
    from caseops_api.db.models import utcnow

    return utcnow()


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _canonical_header(value: str) -> str | None:
    cleaned = re.sub(r"[\s_\-]+", "", value.strip().lower())
    aliases = {
        "name": "full_name",
        "fullname": "full_name",
        "email": "email",
        "role": "role",
        "mobile": "mobile",
        "phone": "mobile",
        "designation": "designation",
        "department": "department",
        "employeecode": "employee_code",
        "employeeid": "employee_code",
        "manageremail": "manager_email",
    }
    return aliases.get(cleaned)


def _unsafe_formula_cell(value: str) -> bool:
    cleaned = value.lstrip()
    if not cleaned:
        return False
    return cleaned[0] in {"=", "+", "-", "@"}


def _template_csv_bytes() -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerow(
        [
            "Asha Rao",
            "asha.rao@example.com",
            "member",
            "919876543210",
            "Associate",
            "Litigation",
            "EMP-001",
            "",
        ]
    )
    return buffer.getvalue().encode("utf-8")


def _xlsx_col(index: int) -> str:
    label = ""
    while index:
        index, rem = divmod(index - 1, 26)
        label = chr(65 + rem) + label
    return label


def _template_xlsx_bytes() -> bytes:
    rows = [
        TEMPLATE_HEADERS,
        [
            "Asha Rao",
            "asha.rao@example.com",
            "member",
            "919876543210",
            "Associate",
            "Litigation",
            "EMP-001",
            "",
        ],
    ]
    sheet_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{_xlsx_col(col_index)}{row_index}"
            escaped = (
                value.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Employees" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return buffer.getvalue()


def employee_import_template(format_value: Literal["csv", "xlsx"]) -> tuple[bytes, str, str]:
    if format_value == "xlsx":
        return (
            _template_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "caseops-employee-import-template.xlsx",
        )
    return _template_csv_bytes(), "text/csv; charset=utf-8", "caseops-employee-import-template.csv"


def _raise_bad_request(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _detect_upload_kind(filename: str, content_type: str | None) -> Literal["csv", "xlsx"]:
    suffix = Path(filename or "").suffix.lower()
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if suffix == ".csv":
        if normalized_content_type not in CSV_CONTENT_TYPES:
            _raise_bad_request("Unsupported employee import MIME type.")
        return "csv"
    if suffix == ".xlsx":
        if normalized_content_type not in XLSX_CONTENT_TYPES:
            _raise_bad_request("Unsupported employee import MIME type.")
        return "xlsx"
    _raise_bad_request("Unsupported employee import file type. Upload CSV or XLSX.")


def _normalise_raw_row(raw: dict[str, str]) -> dict[str, str]:
    canonical: dict[str, str] = {}
    for header, value in raw.items():
        key = _canonical_header(header)
        if key is not None and key not in canonical:
            canonical[key] = _clean_cell(value)
    return canonical


def _parse_csv(content: bytes) -> list[ParsedImportRow]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV import must be UTF-8 encoded.",
        ) from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    rows: list[ParsedImportRow] = []
    for row_index, row in enumerate(reader, start=2):
        raw = {
            str(key): _clean_cell(value)
            for key, value in row.items()
            if key is not None
        }
        if any(raw.values()):
            rows.append(ParsedImportRow(row_number=row_index, raw=raw))
    return rows


def _cell_text(
    cell: ElementTree.Element,
    *,
    namespace: dict[str, str],
    shared_strings: list[str],
) -> tuple[str, bool]:
    has_formula = cell.find("m:f", namespace) is not None
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text = "".join(node.text or "" for node in cell.findall(".//m:t", namespace))
        return _clean_cell(text), has_formula
    value = cell.find("m:v", namespace)
    if value is None or value.text is None:
        return "", has_formula
    if cell_type == "s":
        try:
            return _clean_cell(shared_strings[int(value.text)]), has_formula
        except (IndexError, ValueError):
            return "", has_formula
    return _clean_cell(value.text), has_formula


def _xlsx_cell_col(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return max(index - 1, 0)


def _parse_xlsx(content: bytes) -> list[ParsedImportRow]:
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in shared_root.findall(".//m:si", namespace):
                    shared_strings.append(
                        "".join(node.text or "" for node in item.findall(".//m:t", namespace))
                    )
            sheet_root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="XLSX import file could not be read.",
        ) from exc

    rows: list[tuple[list[str], frozenset[int]]] = []
    for row in sheet_root.findall(".//m:sheetData/m:row", namespace):
        values: list[str] = []
        unsafe_indices: set[int] = set()
        for cell in row.findall("m:c", namespace):
            ref = cell.attrib.get("r", "")
            index = _xlsx_cell_col(ref)
            while len(values) <= index:
                values.append("")
            value, unsafe = _cell_text(
                cell,
                namespace=namespace,
                shared_strings=shared_strings,
            )
            values[index] = value
            if unsafe:
                unsafe_indices.add(index)
        rows.append((values, frozenset(unsafe_indices)))
    if not rows:
        return []
    headers = rows[0][0]
    parsed: list[ParsedImportRow] = []
    for row_number, (values, unsafe_indices) in enumerate(rows[1:], start=2):
        raw = {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
            if header
        }
        if any(raw.values()):
            parsed.append(
                ParsedImportRow(
                    row_number=row_number,
                    raw=raw,
                    unsafe_headers=frozenset(
                        headers[index]
                        for index in unsafe_indices
                        if index < len(headers) and headers[index]
                    ),
                )
            )
    return parsed


def _parse_upload(
    *,
    filename: str,
    content_type: str | None,
    content: bytes,
) -> list[ParsedImportRow]:
    if len(content) > EMPLOYEE_IMPORT_MAX_BYTES:
        _raise_bad_request("Employee import file exceeds the 2 MB limit.")
    kind = _detect_upload_kind(filename, content_type)
    rows = _parse_csv(content) if kind == "csv" else _parse_xlsx(content)
    if len(rows) > EMPLOYEE_IMPORT_MAX_ROWS:
        _raise_bad_request(
            f"Employee import supports at most {EMPLOYEE_IMPORT_MAX_ROWS} rows."
        )
    return rows


def _value(raw: dict[str, str], key: str) -> str | None:
    value = raw.get(key, "").strip()
    return value or None


def _manager_lookup(
    session: Session,
    *,
    company_id: str,
    manager_emails: set[str],
) -> dict[str, str]:
    if not manager_emails:
        return {}
    rows = session.execute(
        select(func.lower(User.email), CompanyMembership.id)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
            User.is_active.is_(True),
            func.lower(User.email).in_(manager_emails),
        )
    )
    return {email: membership_id for email, membership_id in rows}


def _validate_rows(
    session: Session,
    *,
    context: SessionContext,
    parsed_rows: list[ParsedImportRow],
) -> list[ValidatedImportRow]:
    canonical_rows: list[tuple[ParsedImportRow, dict[str, str], bool]] = []
    for row in parsed_rows:
        unsafe_headers = set(row.unsafe_headers)
        unsafe_by_header = {
            header: header in unsafe_headers or _unsafe_formula_cell(value)
            for header, value in row.raw.items()
        }
        sanitized_raw = {
            header: ("[unsafe formula removed]" if unsafe_by_header[header] else value)
            for header, value in row.raw.items()
        }
        canonical_input = {
            header: ("" if unsafe_by_header[header] else value)
            for header, value in row.raw.items()
        }
        canonical_rows.append(
            (
                ParsedImportRow(row_number=row.row_number, raw=sanitized_raw),
                _normalise_raw_row(canonical_input),
                any(unsafe_by_header.values()),
            )
        )
    emails = [
        _value(raw, "email").lower()
        for _, raw, _ in canonical_rows
        if _value(raw, "email")
    ]
    employee_codes = [
        _value(raw, "employee_code")
        for _, raw, _ in canonical_rows
        if _value(raw, "employee_code")
    ]
    manager_emails = {
        _value(raw, "manager_email").lower()
        for _, raw, _ in canonical_rows
        if _value(raw, "manager_email")
    }
    duplicate_emails = {email for email in emails if emails.count(email) > 1}
    duplicate_codes = {
        code.lower()
        for code in employee_codes
        if sum(1 for candidate in employee_codes if candidate.lower() == code.lower()) > 1
    }

    existing_tenant_emails: set[str] = set()
    if emails:
        existing_tenant_emails = set(
            session.scalars(
                select(func.lower(User.email))
                .join(CompanyMembership, CompanyMembership.user_id == User.id)
                .where(
                    CompanyMembership.company_id == context.company.id,
                    func.lower(User.email).in_(set(emails)),
                )
            )
        )

    existing_codes: set[str] = set()
    if employee_codes:
        existing_codes = {
            code.lower()
            for code in session.scalars(
                select(EmployeeProfile.employee_code).where(
                    EmployeeProfile.company_id == context.company.id,
                    func.lower(EmployeeProfile.employee_code).in_(
                        {code.lower() for code in employee_codes}
                    ),
                )
            )
            if code
        }
    managers = _manager_lookup(
        session,
        company_id=context.company.id,
        manager_emails=manager_emails,
    )

    validated: list[ValidatedImportRow] = []
    for parsed, raw, unsafe_formula in canonical_rows:
        errors: list[str] = []
        if unsafe_formula:
            errors.append("Unsafe formula-like cell values are not allowed.")

        full_name = _value(raw, "full_name")
        email = (_value(raw, "email") or "").lower()
        role = (_value(raw, "role") or "").lower()
        mobile = _value(raw, "mobile")
        designation = _value(raw, "designation")
        department = _value(raw, "department")
        employee_code = _value(raw, "employee_code")
        manager_email = (_value(raw, "manager_email") or "").lower()

        if not full_name:
            errors.append("Name is required.")
        if not email:
            errors.append("Email is required.")
        elif email in duplicate_emails:
            errors.append("Duplicate email in this import file.")
        elif email in existing_tenant_emails:
            errors.append("Email already belongs to this company.")
        if not role:
            errors.append("Role is required.")
        elif role not in ROLE_VALUES:
            errors.append("Role must be one of admin, partner, member, paralegal, viewer.")
        elif context.membership.role == MembershipRole.ADMIN and role != MembershipRole.MEMBER:
            errors.append("Admins can only assign the member role.")
        if employee_code:
            code_key = employee_code.lower()
            if code_key in duplicate_codes:
                errors.append("Duplicate employee code in this import file.")
            elif code_key in existing_codes:
                errors.append("Employee code is already in use in this company.")
        manager_membership_id: str | None = None
        if manager_email:
            manager_membership_id = managers.get(manager_email)
            if manager_membership_id is None:
                errors.append("ManagerEmail must match an active employee in this company.")

        normalized: dict[str, object] = {
            "full_name": full_name,
            "email": email or None,
            "role": role or None,
            "mobile": mobile,
            "designation": designation,
            "department": department,
            "employee_code": employee_code,
            "manager_email": manager_email or None,
            "manager_membership_id": manager_membership_id,
        }
        try:
            EmployeeCreateRequest.model_validate(
                {
                    "full_name": full_name,
                    "email": email,
                    "role": role,
                    "mobile": mobile,
                    "designation": designation,
                    "department": department,
                    "employee_code": employee_code,
                    "manager_membership_id": manager_membership_id,
                    "joined_on": None,
                }
            )
        except ValidationError as exc:
            for item in exc.errors():
                loc = ".".join(str(part) for part in item.get("loc", ()))
                message = str(item.get("msg", "Invalid value."))
                errors.append(f"{loc}: {message}" if loc else message)
        validated.append(
            ValidatedImportRow(
                row_number=parsed.row_number,
                raw=parsed.raw,
                normalized=normalized,
                errors=sorted(set(errors)),
                unsafe_formula=unsafe_formula,
            )
        )
    return validated


def _job_response(session: Session, job: EmployeeBulkImportJob) -> EmployeeImportJobResponse:
    rows = list(
        session.scalars(
            select(EmployeeBulkImportRow)
            .where(EmployeeBulkImportRow.job_id == job.id)
            .order_by(EmployeeBulkImportRow.row_number.asc(), EmployeeBulkImportRow.id.asc())
        )
    )
    return EmployeeImportJobResponse(
        id=job.id,
        company_id=job.company_id,
        filename=job.filename,
        content_type=job.content_type,
        status=job.status,  # type: ignore[arg-type]
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        created_count=job.created_count,
        failed_count=job.failed_count,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        expires_at=job.expires_at,
        committed_at=job.committed_at,
        cancelled_at=job.cancelled_at,
        rows=[
            EmployeeImportRowPreview(
                id=row.id,
                row_number=row.row_number,
                raw=row.raw_json,
                normalized=row.normalized_json,
                errors=row.errors_json,
                status=row.status,  # type: ignore[arg-type]
                created_membership_id=row.created_membership_id,
            )
            for row in rows
        ],
    )


def preview_employee_import(
    session: Session,
    *,
    context: SessionContext,
    filename: str,
    content_type: str | None,
    content: bytes,
) -> EmployeeImportJobResponse:
    parsed_rows = _parse_upload(
        filename=filename,
        content_type=content_type,
        content=content,
    )
    validated = _validate_rows(session, context=context, parsed_rows=parsed_rows)
    now = _utcnow()
    valid_count = sum(1 for row in validated if not row.errors)
    invalid_count = len(validated) - valid_count
    job = EmployeeBulkImportJob(
        company_id=context.company.id,
        created_by_membership_id=context.membership.id,
        filename=(filename or "employees").strip()[:255],
        content_type=content_type,
        file_size_bytes=len(content),
        status=EmployeeImportJobStatus.PREVIEWED,
        total_rows=len(validated),
        valid_rows=valid_count,
        invalid_rows=invalid_count,
        created_count=0,
        failed_count=0,
        created_at=now,
        updated_at=now,
        expires_at=now + EMPLOYEE_IMPORT_PREVIEW_TTL,
    )
    session.add(job)
    session.flush()
    for validated_row in validated:
        row_status = (
            EmployeeImportRowStatus.VALID
            if not validated_row.errors
            else EmployeeImportRowStatus.INVALID
        )
        session.add(
            EmployeeBulkImportRow(
                company_id=context.company.id,
                job_id=job.id,
                row_number=validated_row.row_number,
                raw_json=validated_row.raw,
                normalized_json=validated_row.normalized,
                errors_json=validated_row.errors,
                status=row_status,
                created_at=now,
                updated_at=now,
            )
        )
    record_from_context(
        session,
        context,
        action="employee.import.previewed",
        target_type="employee_import",
        target_id=job.id,
        result=AuditResult.SUCCESS,
        metadata={
            "filename": job.filename,
            "content_type": content_type,
            "file_size_bytes": len(content),
            "total_rows": len(validated),
            "valid_rows": valid_count,
            "invalid_rows": invalid_count,
            "max_rows": EMPLOYEE_IMPORT_MAX_ROWS,
            "max_bytes": EMPLOYEE_IMPORT_MAX_BYTES,
        },
    )
    for invalid in (row for row in validated if row.errors):
        record_from_context(
            session,
            context,
            action="employee.import.row_failed",
            target_type="employee_import",
            target_id=job.id,
            result=AuditResult.FAILED,
            metadata={
                "row_number": invalid.row_number,
                "errors": invalid.errors,
            },
        )
    session.commit()
    session.refresh(job)
    return _job_response(session, job)


def _load_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> EmployeeBulkImportJob:
    job = session.scalar(
        select(EmployeeBulkImportJob).where(
            EmployeeBulkImportJob.id == job_id,
            EmployeeBulkImportJob.company_id == context.company.id,
        )
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee import job not found.",
        )
    return job


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_is_expired(job: EmployeeBulkImportJob, *, now: datetime) -> bool:
    return _aware_utc(job.expires_at) <= _aware_utc(now)


def _claim_job_for_commit(
    session: Session,
    *,
    context: SessionContext,
    job: EmployeeBulkImportJob,
) -> EmployeeBulkImportJob:
    now = _utcnow()
    result = session.execute(
        update(EmployeeBulkImportJob)
        .where(
            EmployeeBulkImportJob.id == job.id,
            EmployeeBulkImportJob.company_id == context.company.id,
            EmployeeBulkImportJob.status == EmployeeImportJobStatus.PREVIEWED,
        )
        .values(
            status=EmployeeImportJobStatus.COMMITTING,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        _raise_bad_request("Only previewed employee imports can be committed.")
    session.commit()
    return _load_job(session, context=context, job_id=job.id)


def _mark_commit_failed(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
    reason: str,
    message: str,
) -> None:
    job = _load_job(session, context=context, job_id=job_id)
    now = _utcnow()
    job.status = EmployeeImportJobStatus.FAILED
    job.failed_count = job.valid_rows
    job.error_message = message
    job.updated_at = now
    record_from_context(
        session,
        context,
        action="employee.import.commit_failed",
        target_type="employee_import",
        target_id=job.id,
        result=AuditResult.FAILED,
        metadata={
            "reason": reason,
            "total_rows": job.total_rows,
            "valid_rows": job.valid_rows,
            "invalid_rows": job.invalid_rows,
        },
    )
    session.commit()


def _parsed_rows_from_job(session: Session, job: EmployeeBulkImportJob) -> list[ParsedImportRow]:
    rows = list(
        session.scalars(
            select(EmployeeBulkImportRow)
            .where(EmployeeBulkImportRow.job_id == job.id)
            .order_by(EmployeeBulkImportRow.row_number.asc(), EmployeeBulkImportRow.id.asc())
        )
    )
    return [
        ParsedImportRow(
            row_number=row.row_number,
            raw={str(key): _clean_cell(value) for key, value in row.raw_json.items()},
        )
        for row in rows
    ]


def _persist_revalidation(
    session: Session,
    *,
    context: SessionContext,
    job: EmployeeBulkImportJob,
    validated: list[ValidatedImportRow],
) -> None:
    by_number = {row.row_number: row for row in validated}
    persisted = list(
        session.scalars(
            select(EmployeeBulkImportRow).where(EmployeeBulkImportRow.job_id == job.id)
        )
    )
    for row in persisted:
        validated_row = by_number[row.row_number]
        row.normalized_json = validated_row.normalized
        row.errors_json = validated_row.errors
        row.status = (
            EmployeeImportRowStatus.VALID
            if not validated_row.errors
            else EmployeeImportRowStatus.INVALID
        )
        row.updated_at = _utcnow()
    job.valid_rows = sum(1 for row in validated if not row.errors)
    job.invalid_rows = len(validated) - job.valid_rows
    job.updated_at = _utcnow()
    for invalid in (row for row in validated if row.errors):
        record_from_context(
            session,
            context,
            action="employee.import.row_failed",
            target_type="employee_import",
            target_id=job.id,
            result=AuditResult.FAILED,
            metadata={
                "row_number": invalid.row_number,
                "errors": invalid.errors,
                "phase": "commit_revalidation",
            },
        )


def commit_employee_import(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> EmployeeImportCommitResponse:
    job = _load_job(session, context=context, job_id=job_id)
    if job.status != EmployeeImportJobStatus.PREVIEWED:
        _raise_bad_request("Only previewed employee imports can be committed.")
    if _job_is_expired(job, now=_utcnow()):
        _raise_bad_request("Employee import preview has expired. Upload the file again.")
    if job.invalid_rows:
        _raise_bad_request("Cannot commit an employee import with validation errors.")

    parsed_rows = _parsed_rows_from_job(session, job)
    validated = _validate_rows(session, context=context, parsed_rows=parsed_rows)
    if any(row.errors for row in validated):
        _persist_revalidation(session, context=context, job=job, validated=validated)
        record_from_context(
            session,
            context,
            action="employee.import.commit_failed",
            target_type="employee_import",
            target_id=job.id,
            result=AuditResult.FAILED,
            metadata={
                "invalid_rows": job.invalid_rows,
                "reason": "commit_revalidation_failed",
            },
        )
        session.commit()
        _raise_bad_request("Cannot commit an employee import with validation errors.")

    job = _claim_job_for_commit(session, context=context, job=job)
    created: list[EmployeeCreateResponse] = []
    persisted_rows = list(
        session.scalars(
            select(EmployeeBulkImportRow)
            .where(EmployeeBulkImportRow.job_id == job.id)
            .order_by(EmployeeBulkImportRow.row_number.asc(), EmployeeBulkImportRow.id.asc())
        )
    )
    row_by_number = {row.row_number: row for row in persisted_rows}
    try:
        for validated_row in validated:
            payload = EmployeeCreateRequest.model_validate(
                {
                    "full_name": validated_row.normalized["full_name"],
                    "email": validated_row.normalized["email"],
                    "role": validated_row.normalized["role"],
                    "mobile": validated_row.normalized["mobile"],
                    "designation": validated_row.normalized["designation"],
                    "department": validated_row.normalized["department"],
                    "employee_code": validated_row.normalized["employee_code"],
                    "manager_membership_id": validated_row.normalized[
                        "manager_membership_id"
                    ],
                    "joined_on": None,
                }
            )
            pending = _create_employee_without_commit(
                session,
                context=context,
                payload=payload,
                reuse_existing_global_user=True,
            )
            row = row_by_number[validated_row.row_number]
            row.status = EmployeeImportRowStatus.CREATED
            row.created_membership_id = pending.membership.id
            row.updated_at = _utcnow()
            created.append(
                EmployeeCreateResponse(
                    employee=_employee_record(session, pending.membership),
                    setup=pending.setup.delivery_response(),
                )
            )
    except HTTPException as exc:
        session.rollback()
        _mark_commit_failed(
            session,
            context=context,
            job_id=job.id,
            reason="create_failed",
            message="Employee import could not be committed.",
        )
        if exc.status_code == status.HTTP_409_CONFLICT:
            _raise_bad_request(
                "Employee import could not be committed because one or more rows became invalid."
            )
        raise
    except Exception:
        session.rollback()
        _mark_commit_failed(
            session,
            context=context,
            job_id=job.id,
            reason="create_failed",
            message="Employee import could not be committed.",
        )
        raise

    now = _utcnow()
    job.status = EmployeeImportJobStatus.COMMITTED
    job.created_count = len(created)
    job.failed_count = 0
    job.committed_at = now
    job.updated_at = now
    record_from_context(
        session,
        context,
        action="employee.import.committed",
        target_type="employee_import",
        target_id=job.id,
        result=AuditResult.SUCCESS,
        metadata={
            "total_rows": job.total_rows,
            "created_count": len(created),
            "setup_delivered": sum(1 for row in created if row.setup.delivered),
            "setup_generated_not_delivered": sum(
                1 for row in created if not row.setup.delivered
            ),
        },
    )
    session.commit()
    session.refresh(job)
    return EmployeeImportCommitResponse(
        job=_job_response(session, job),
        created_employees=created,
    )


def cancel_employee_import(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> EmployeeImportJobResponse:
    job = _load_job(session, context=context, job_id=job_id)
    if job.status != EmployeeImportJobStatus.PREVIEWED:
        _raise_bad_request("Only previewed employee imports can be cancelled.")
    now = _utcnow()
    job.status = EmployeeImportJobStatus.CANCELLED
    job.cancelled_at = now
    job.updated_at = now
    record_from_context(
        session,
        context,
        action="employee.import.cancelled",
        target_type="employee_import",
        target_id=job.id,
        result=AuditResult.SUCCESS,
        metadata={
            "total_rows": job.total_rows,
            "valid_rows": job.valid_rows,
            "invalid_rows": job.invalid_rows,
        },
    )
    session.commit()
    session.refresh(job)
    return _job_response(session, job)


__all__ = [
    "EMPLOYEE_IMPORT_MAX_BYTES",
    "EMPLOYEE_IMPORT_MAX_ROWS",
    "cancel_employee_import",
    "commit_employee_import",
    "employee_import_template",
    "preview_employee_import",
]
