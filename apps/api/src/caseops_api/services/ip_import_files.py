"""Bounded, source-preserving CSV/XLSX parsing for the neutral IP import owner."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook

from caseops_api.schemas.ip_imports import (
    IpImportJobCreateRequest,
    IpImportRowInput,
    IpParsedImportJobCreateRequest,
)

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 1000
MAX_IMPORT_COLUMNS = 100
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_SOURCE_TEXT_BYTES = 10 * 1024 * 1024
HEADER_ALIASES = {
    "title": "title",
    "trademark": "mark_text",
    "mark": "mark_text",
    "mark text": "mark_text",
    "class": "class_number",
    "classes": "class_number",
    "nice class": "class_number",
    "nice classes": "class_number",
    "class number": "class_number",
    "applicant": "applicant_name",
    "applicant name": "applicant_name",
    "applicant names": "applicant_name",
    "applicant name s": "applicant_name",
    "owner": "applicant_name",
    "proprietor": "applicant_name",
    "goods services": "specification",
    "goods and services": "specification",
    "specification": "specification",
    "application number": "application_number",
    "application no": "application_number",
    "app no": "application_number",
    "representation": "representation_kind",
    "representation type": "representation_kind",
    "representation kind": "representation_kind",
    "agent": "agent_name",
    "agent name": "agent_name",
    "jurisdiction": "jurisdiction",
    "country": "jurisdiction",
    "office": "office",
    "matter id": "matter_id",
    "s no": "source_reference",
    "sno": "source_reference",
    "serial number": "source_reference",
    "trademark image": "image_reference",
    "application date": "application_date",
    "filing date": "application_date",
    "renewal due date": "renewal_due_date",
    "renewal date": "renewal_due_date",
    "status": "source_status",
    "comment": "comment",
    "takeover request": "takeover_request",
    "name change request": "name_change_request",
    "address change request": "address_change_request",
    "internal remarks": "internal_remarks",
    "registration number": "registration_number",
    "registration no": "registration_number",
    "filing number": "filing_number",
    "priority date": "priority_date",
    "notes": "notes",
}
METADATA_FIELDS = {
    "source_reference",
    "image_reference",
    "source_status",
    "comment",
    "takeover_request",
    "name_change_request",
    "address_change_request",
    "internal_remarks",
    "registration_number",
    "filing_number",
    "priority_date",
    "notes",
}


def normalize_header(value: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", value.casefold()).split())


def source_value(value: object) -> object:
    # Native Excel dates are source evidence too, and must be JSON serializable.
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    return value


def _headers(values: list[object]) -> list[str]:
    if len(values) > MAX_IMPORT_COLUMNS:
        raise HTTPException(422, "Import files are limited to 100 columns.")
    headers = [
        str(value or "").strip() or f"Unnamed column {i}" for i, value in enumerate(values, 1)
    ]
    if any(len(header) > 255 for header in headers):
        raise HTTPException(422, "Import headers are limited to 255 characters.")
    if len(set(headers)) != len(headers):
        raise HTTPException(
            422,
            "Repeated identical headers are ambiguous; give them unique names.",
        )
    return headers


def _materialize(headers: list[str], iterator) -> list[dict[str, object]]:
    rows = []
    text_bytes = 0
    for values in iterator:
        if len(rows) >= MAX_IMPORT_ROWS:
            raise HTTPException(422, "Import files are limited to 1,000 rows.")
        if len(values) > len(headers) and any(
            value not in (None, "") for value in values[len(headers) :]
        ):
            raise HTTPException(422, "A data row contains cells without a source header.")
        if any(isinstance(value, str) and len(value) > 10000 for value in values):
            raise HTTPException(422, "Import cells are limited to 10,000 characters.")
        text_bytes += sum(len(value.encode("utf-8")) for value in values if isinstance(value, str))
        if text_bytes > MAX_SOURCE_TEXT_BYTES:
            raise HTTPException(422, "Decoded source text exceeds 10 MB; split the import file.")
        rows.append({key: source_value(value) for key, value in zip(headers, values, strict=False)})
    return rows


def _rows_from_csv(content: bytes) -> list[dict[str, object]]:
    try:
        reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        headers = _headers(list(next(reader)))
        return _materialize(headers, reader)
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV files must use UTF-8 encoding.") from exc
    except StopIteration as exc:
        raise HTTPException(422, "The import file is empty.") from exc
    except csv.Error as exc:
        raise HTTPException(422, "The CSV file could not be read.") from exc


def _rows_from_xlsx(content: bytes) -> list[dict[str, object]]:
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if (
                len(members) > 1000
                or sum(member.file_size for member in members) > MAX_EXPANDED_BYTES
            ):
                raise HTTPException(422, "The expanded XLSX file exceeds the safe import limit.")
        workbook = load_workbook(
            io.BytesIO(content), read_only=True, data_only=False, keep_links=False
        )
        try:
            sheet = workbook.active
            if sheet is None:
                raise HTTPException(422, "The XLSX file has no active worksheet.")
            if sheet.max_column is not None and sheet.max_column > MAX_IMPORT_COLUMNS:
                raise HTTPException(422, "Import files are limited to 100 columns.")
            if sheet.max_row is not None and sheet.max_row > MAX_IMPORT_ROWS + 1:
                raise HTTPException(422, "Import files are limited to 1,000 rows.")
            iterator = sheet.iter_rows(values_only=True)
            return _materialize(_headers(list(next(iterator))), iterator)
        finally:
            workbook.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "The XLSX file could not be read.") from exc


def parse_ip_import_file(*, filename: str, content: bytes) -> IpImportJobCreateRequest:
    if not content:
        raise HTTPException(422, "The import file is empty.")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "Import files are limited to 10 MB.")
    suffix = Path(filename).suffix.casefold()
    if suffix == ".csv":
        rows = _rows_from_csv(content)
    elif suffix == ".xlsx":
        rows = _rows_from_xlsx(content)
    else:
        raise HTTPException(415, "Use a CSV or XLSX import file.")
    if not rows:
        raise HTTPException(422, "The import file has no data rows.")
    return IpParsedImportJobCreateRequest(
        filename=Path(filename).name,
        source_sha256=sha256(content).hexdigest(),
        rows=[IpImportRowInput(row_number=index, values=row) for index, row in enumerate(rows, 1)],
    )


__all__ = [
    "MAX_IMPORT_BYTES",
    "MAX_IMPORT_ROWS",
    "MAX_IMPORT_COLUMNS",
    "MAX_EXPANDED_BYTES",
    "MAX_SOURCE_TEXT_BYTES",
    "HEADER_ALIASES",
    "METADATA_FIELDS",
    "normalize_header",
    "source_value",
    "parse_ip_import_file",
]
