from __future__ import annotations

import csv
import io
import json
import logging
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import PurePosixPath
from typing import BinaryIO, Literal
from xml.sax.saxutils import escape

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    DEFAULT_MATTER_STATUS,
    AuditResult,
    CompanyMembership,
    ForumCatalogEntry,
    Matter,
    MatterBulkImportJob,
    MatterBulkImportRow,
    MatterImportJobStatus,
    MatterImportRowStatus,
    NotificationDeliveryChannel,
    Team,
    TeamKind,
    TeamMembership,
    User,
)
from caseops_api.schemas.matter_imports import (
    BulkMatterImportDocumentReference,
    BulkMatterImportDryRunResponse,
    BulkMatterImportDryRunSummary,
    BulkMatterImportDuplicateCandidate,
    BulkMatterImportManifestFormat,
    BulkMatterImportRowPlan,
    MatterImportCommitResponse,
    MatterImportHistoryResponse,
    MatterImportJobResponse,
    MatterImportRowRecord,
)
from caseops_api.schemas.matters import MatterCreateRequest
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import visible_matters_filter
from caseops_api.services.matters import create_matter
from caseops_api.services.notification_delivery import enqueue_notification_delivery_intent
from caseops_api.services.session_context import SessionContext

MATTER_IMPORT_MAPPING_MAX_BYTES = 2 * 1024 * 1024
MATTER_IMPORT_DOCUMENT_MANIFEST_MAX_BYTES = 512 * 1024
MATTER_IMPORT_DOCUMENT_ARCHIVE_MAX_BYTES = 10 * 1024 * 1024
MATTER_IMPORT_MAX_ROWS = 500
MATTER_IMPORT_MAX_DOCUMENT_REFERENCES = 2000
MATTER_IMPORT_PREVIEW_TTL = timedelta(hours=24)
MATTER_IMPORT_STALE_AFTER = timedelta(minutes=10)
MATTER_IMPORT_XLSX_MAX_ENTRIES = 1000
MATTER_IMPORT_XLSX_MAX_ENTRY_BYTES = 16 * 1024 * 1024
MATTER_IMPORT_XLSX_MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MATTER_IMPORT_XLSX_MAX_COMPRESSION_RATIO = 250
MATTER_IMPORT_XLSX_MAX_COLUMNS = 16_384
MATTER_IMPORT_XLSX_MAX_ROWS = 1_048_576
MATTER_IMPORT_XLSX_MAX_METADATA_BYTES = 512 * 1024
MATTER_IMPORT_XLSX_MAX_SHARED_STRINGS = 100_000
MATTER_IMPORT_XLSX_MAX_SHARED_STRING_CHARS = 32_767
MATTER_IMPORT_XLSX_MAX_SHARED_TEXT_CHARS = 8 * 1024 * 1024
MATTER_IMPORT_PARSE_ROW_BUFFER = MATTER_IMPORT_MAX_ROWS + 26

logger = logging.getLogger(__name__)

MATTER_IMPORT_TEMPLATE_HEADERS = [
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
]

_DEFAULT_PRACTICE_AREAS = (
    "Arbitration",
    "Banking and Finance",
    "Civil",
    "Commercial",
    "Consumer",
    "Corporate",
    "Criminal",
    "Employment and Labour",
    "Family",
    "Insolvency",
    "Intellectual Property",
    "Real Estate",
    "Regulatory",
    "Tax",
    "Other",
)

_CSV_CONTENT_TYPES = {
    "",
    "application/csv",
    "application/octet-stream",
    "application/vnd.ms-excel",
    "text/csv",
}
_JSON_CONTENT_TYPES = {
    "",
    "application/json",
    "application/octet-stream",
    "text/json",
}
_XLSX_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_ZIP_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "application/zip",
    "application/x-zip-compressed",
}
_ALLOWED_DOCUMENT_CATEGORIES = {
    "pleadings",
    "orders",
    "evidence",
    "notices",
    "contracts",
    "correspondence",
    "other",
    "needs_review",
}
_FIELD_ALIASES = {
    "mattercode": "matter_code",
    "code": "matter_code",
    "matterid": "matter_code",
    "title": "title",
    "mattertitle": "title",
    "mattername": "title",
    "casetitle": "title",
    "name": "title",
    "client": "client_name",
    "clientname": "client_name",
    "existingclient": "client_name",
    "existingclientname": "client_name",
    "partyname": "client_name",
    "clientreference": "client_name",
    "clientref": "client_name",
    "clientcode": "client_code",
    "clientcontactnumber": "client_contact_number",
    "clientcontactno": "client_contact_number",
    "clientphone": "client_contact_number",
    "clientphoneno": "client_contact_number",
    "phone": "client_contact_number",
    "phoneno": "client_contact_number",
    "phonenumber": "client_contact_number",
    "clientemail": "client_email",
    "practicearea": "practice_area",
    "areaofpractice": "practice_area",
    "area": "practice_area",
    "mattertype": "matter_type",
    "type": "matter_type",
    "status": "status",
    "matterstatus": "status",
    "currentstatus": "status",
    "forum": "forum_level",
    "forumlevel": "forum_level",
    "courtforum": "forum_level",
    "forumcatalogentryid": "forum_catalog_entry_id",
    "forumstate": "forum_state",
    "forumdistrict": "forum_district",
    "forumcity": "forum_city",
    "forumconsumerlevel": "forum_consumer_level",
    "court": "court_name",
    "courtname": "court_name",
    "forumname": "court_name",
    "courtforumnumber": "court_forum_number",
    "courtforumno": "court_forum_number",
    "courtforumref": "court_forum_number",
    "courtforumreference": "court_forum_number",
    "courtnumber": "court_forum_number",
    "courtno": "court_forum_number",
    "forumnumber": "court_forum_number",
    "forumno": "court_forum_number",
    "matterdescription": "description",
    "description": "description",
    "opposingparty": "opposing_party",
    "opposingpartyname": "opposing_party",
    "opposingcounsel": "opposing_counsel",
    "casenumber": "case_number",
    "filingnumber": "filing_number",
    "filingdate": "filing_date",
    "dateoffiling": "filing_date",
    "owner": "owner_email",
    "owneremail": "owner_email",
    "assignee": "owner_email",
    "matterowner": "owner_email",
    "team": "team_slug",
    "teamslug": "team_slug",
    "assignedteam": "team_slug",
    "responsiblelawyer": "responsible_lawyer_email",
    "responsiblelawyeremail": "responsible_lawyer_email",
    "documents": "document_filenames",
    "documentfilenames": "document_filenames",
    "documentfilename": "document_filenames",
    "files": "document_filenames",
    "filenames": "document_filenames",
    "folderfiles": "document_filenames",
    "zipfiles": "document_filenames",
    "documentcategory": "document_category",
    "documentcategories": "document_category",
    "category": "document_category",
}


@dataclass(frozen=True)
class ParsedMatterImportRow:
    row_number: int
    raw: dict[str, str]
    unsafe_headers: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ParsedMatterImport:
    manifest_format: BulkMatterImportManifestFormat
    rows: list[ParsedMatterImportRow]


@dataclass(frozen=True)
class ExistingMatterCandidate:
    matter_id: str
    matter_code: str
    title: str
    client_name: str | None
    case_number: str | None


def _raise_bad_request(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _clean_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _canonical_header(value: str) -> str | None:
    # Client-maintained spreadsheets commonly decorate headings with periods,
    # slashes, ampersands, parentheses, or "#". Header punctuation is
    # presentation, not business data, so compare only case-folded letters
    # and digits.
    cleaned = re.sub(r"[^a-z0-9]+", "", value.strip().casefold())
    return _FIELD_ALIASES.get(cleaned)


def _unsafe_formula_cell(value: str) -> bool:
    cleaned = value.lstrip()
    return bool(cleaned) and cleaned[0] in {"=", "+", "-", "@"}


def _valid_leading_plus_phone(value: str) -> bool:
    cleaned = value.strip()
    match = re.fullmatch(
        r"(?P<number>\+[0-9()\s-]+)(?:(?:ext\.?|x)\s*\d{1,10})?",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match is None:
        return False
    main_number_digits = re.sub(r"\D", "", match.group("number"))
    return 7 <= len(main_number_digits) <= 20


def _unsafe_import_cell(header: str, value: str) -> bool:
    # A leading plus is a normal international-phone prefix. It is safe only
    # in the phone column and only when every remaining character is part of
    # a phone number. Actual XLSX formula nodes are still rejected separately.
    if (
        _canonical_header(header) == "client_contact_number"
        and value.strip().startswith("+")
        and _valid_leading_plus_phone(value)
    ):
        return False
    return _unsafe_formula_cell(value)


def _normalise_raw_row(raw: dict[str, str]) -> dict[str, str]:
    canonical: dict[str, str] = {}
    for header, value in raw.items():
        key = _canonical_header(header)
        if key is not None and key not in canonical:
            canonical[key] = _clean_cell(value)
    return canonical


def _canonical_header_set(values: list[str]) -> set[str]:
    return {
        key for value in values if value and (key := _canonical_header(value)) is not None
    }


def _header_score(values: list[str]) -> int:
    canonical = _canonical_header_set(values)
    # Required identity columns distinguish the real import sheet from
    # instruction/reference sheets that may also mention status/forum names.
    return len(canonical) + (10 if "title" in canonical else 0) + (
        10 if "matter_code" in canonical else 0
    )


def _header_has_required_identity(values: list[str]) -> bool:
    canonical = _canonical_header_set(values)
    return {"title", "matter_code"}.issubset(canonical)


def _header_row_index(rows: list[tuple[int, list[str], frozenset[int]]]) -> int:
    if not rows:
        return 0
    candidates = list(enumerate(rows[:25]))
    best_index, best_row = max(
        candidates,
        key=lambda item: (_header_score(item[1][1]), -item[0]),
    )
    return best_index if _header_score(best_row[1]) >= 2 else 0


def _decode_csv_text(content: bytes) -> str:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return content.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV matter import could not be decoded.",
            ) from exc
    try:
        decoded = content.decode("utf-8-sig")
        if "\x00" not in decoded:
            return decoded
    except UnicodeDecodeError:
        # A failed UTF-8 probe is expected for supported Windows-1252 exports.
        pass
    # Excel on Windows commonly exports CSV using the local ANSI code page.
    # cp1252 is deterministic and preserves the common legal/business
    # punctuation that prompted this compatibility change.
    try:
        return content.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV matter import must be UTF-8, UTF-16, or Windows-1252 encoded.",
        ) from exc


def _detect_mapping_kind(
    filename: str,
    content_type: str | None,
) -> BulkMatterImportManifestFormat:
    suffix = PurePosixPath(filename or "").suffix.lower()
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if suffix == ".csv":
        if normalized_content_type not in _CSV_CONTENT_TYPES:
            _raise_bad_request("Unsupported matter import CSV MIME type.")
        return "csv"
    if suffix == ".json":
        if normalized_content_type not in _JSON_CONTENT_TYPES:
            _raise_bad_request("Unsupported matter import JSON MIME type.")
        return "json"
    if suffix == ".xlsx":
        if normalized_content_type not in _XLSX_CONTENT_TYPES:
            _raise_bad_request("Unsupported matter import XLSX MIME type.")
        return "xlsx"
    _raise_bad_request("Unsupported matter import file type. Upload CSV, JSON, or XLSX.")


def _parse_csv(content: bytes) -> list[ParsedMatterImportRow]:
    text = _decode_csv_text(content)
    delimiter_candidates: list[
        tuple[int, int, list[tuple[int, list[str], frozenset[int]]]]
    ] = []
    for delimiter_index, delimiter in enumerate((",", ";", "\t", "|")):
        try:
            candidate_rows: list[tuple[int, list[str], frozenset[int]]] = []
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            previous_line_number = 0
            for values in reader:
                row_number = previous_line_number + 1
                previous_line_number = reader.line_num
                cleaned_values = [_clean_cell(value) for value in values]
                if not any(cleaned_values):
                    continue
                candidate_rows.append((row_number, cleaned_values, frozenset()))
                if len(candidate_rows) >= MATTER_IMPORT_PARSE_ROW_BUFFER:
                    break
        except csv.Error as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV matter import file could not be parsed safely.",
            ) from exc
        if candidate_rows:
            header_index = _header_row_index(candidate_rows)
            delimiter_candidates.append(
                (
                    _header_score(candidate_rows[header_index][1]),
                    -delimiter_index,
                    candidate_rows,
                )
            )
    if not delimiter_candidates:
        return []
    parsed_rows = max(delimiter_candidates, key=lambda candidate: candidate[:2])[2]
    if not parsed_rows:
        return []
    header_index = _header_row_index(parsed_rows)
    headers = parsed_rows[header_index][1]
    header_unsafe_indices = {
        index for index, header in enumerate(headers) if _unsafe_formula_cell(header)
    }
    rows: list[ParsedMatterImportRow] = []
    for row_number, values, _unsafe_indices in parsed_rows[header_index + 1 :]:
        raw = {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
            if header
        }
        unsafe_headers = {
            headers[index]
            for index in header_unsafe_indices
            if index < len(headers) and headers[index]
        }
        if any(raw.values()) or unsafe_headers:
            rows.append(
                ParsedMatterImportRow(
                    row_number=row_number,
                    raw=raw,
                    unsafe_headers=frozenset(unsafe_headers),
                )
            )
    return rows


def _json_cell(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(_clean_cell(item) for item in value if _clean_cell(item))
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return _clean_cell(value)


def _parse_json(content: bytes) -> list[ParsedMatterImportRow]:
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="JSON matter import could not be parsed.",
        ) from exc
    if isinstance(data, dict):
        data = data.get("rows", [])
    if not isinstance(data, list):
        _raise_bad_request("JSON matter import must be a row array or object with rows.")
    rows: list[ParsedMatterImportRow] = []
    for row_index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            _raise_bad_request("JSON matter import rows must be objects.")
        raw = {str(key): _json_cell(value) for key, value in row.items()}
        if any(raw.values()):
            rows.append(ParsedMatterImportRow(row_number=row_index, raw=raw))
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
    match = re.fullmatch(r"([A-Za-z]+)([1-9][0-9]*)", ref)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="XLSX matter import contains an invalid cell reference.",
        )
    letters = match.group(1).upper()
    row_text = match.group(2)
    max_row_text = str(MATTER_IMPORT_XLSX_MAX_ROWS)
    if len(row_text) > len(max_row_text) or (
        len(row_text) == len(max_row_text) and row_text > max_row_text
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "XLSX matter import uses a row beyond the supported "
                f"{MATTER_IMPORT_XLSX_MAX_ROWS}-row safety limit."
            ),
        )
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
        if index > MATTER_IMPORT_XLSX_MAX_COLUMNS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "XLSX matter import uses a column beyond the supported "
                    f"{MATTER_IMPORT_XLSX_MAX_COLUMNS}-column safety limit."
                ),
            )
    return index - 1


def _xlsx_fallback_sheet_sort_key(path: str) -> tuple[int, str]:
    match = re.search(r"(\d+)\.xml$", path)
    if match is None:
        return (0, "")
    digits = match.group(1).lstrip("0") or "0"
    return (len(digits), digits)


def _validate_xlsx_archive(archive: zipfile.ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MATTER_IMPORT_XLSX_MAX_ENTRIES:
        _raise_bad_request("XLSX matter import contains too many archive entries.")
    total_uncompressed = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            _raise_bad_request("Encrypted XLSX matter import files are not supported.")
        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            _raise_bad_request(
                "XLSX matter import uses an unsupported ZIP compression method."
            )
        if entry.file_size > MATTER_IMPORT_XLSX_MAX_ENTRY_BYTES:
            _raise_bad_request("XLSX matter import contains an oversized archive entry.")
        total_uncompressed += entry.file_size
        if total_uncompressed > MATTER_IMPORT_XLSX_MAX_UNCOMPRESSED_BYTES:
            _raise_bad_request("XLSX matter import expands beyond the safe size limit.")
        if entry.file_size >= 1024 * 1024:
            compression_ratio = entry.file_size / max(entry.compress_size, 1)
            if compression_ratio > MATTER_IMPORT_XLSX_MAX_COMPRESSION_RATIO:
                _raise_bad_request(
                    "XLSX matter import contains a suspiciously compressed archive entry."
                )


def _read_bounded_xlsx_metadata(
    archive: zipfile.ZipFile,
    entry_name: str,
    *,
    description: str,
) -> bytes:
    entry = archive.getinfo(entry_name)
    if entry.file_size > MATTER_IMPORT_XLSX_MAX_METADATA_BYTES:
        _raise_bad_request(f"XLSX matter import {description} is too large.")
    with archive.open(entry) as source:
        content = source.read(MATTER_IMPORT_XLSX_MAX_METADATA_BYTES + 1)
    if len(content) > MATTER_IMPORT_XLSX_MAX_METADATA_BYTES:
        _raise_bad_request(f"XLSX matter import {description} is too large.")
    return content


def _xlsx_uses_1904_date_system(archive: zipfile.ZipFile) -> bool:
    try:
        workbook_root = ElementTree.fromstring(
            _read_bounded_xlsx_metadata(
                archive,
                "xl/workbook.xml",
                description="workbook metadata",
            )
        )
    except (KeyError, ElementTree.ParseError, DefusedXmlException):
        return False
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    workbook_properties = workbook_root.find("m:workbookPr", namespace)
    if workbook_properties is None:
        return False
    return workbook_properties.attrib.get("date1904", "").strip().casefold() in {
        "1",
        "true",
    }


def _normalise_1904_xlsx_date(value: str) -> str:
    cleaned = value.strip()
    if not re.fullmatch(r"[0-9]{1,7}(?:\.[0-9]+)?", cleaned):
        return value
    try:
        serial = int(cleaned.partition(".")[0])
        parsed = date(1904, 1, 1) + timedelta(days=serial)
    except (OverflowError, ValueError):
        return value
    return parsed.isoformat()


def _xlsx_worksheet_paths(archive: zipfile.ZipFile) -> list[str]:
    names = set(archive.namelist())
    fallback = sorted(
        (name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
        key=_xlsx_fallback_sheet_sort_key,
    )
    try:
        workbook_root = ElementTree.fromstring(
            _read_bounded_xlsx_metadata(
                archive,
                "xl/workbook.xml",
                description="workbook metadata",
            )
        )
        relationships_root = ElementTree.fromstring(
            _read_bounded_xlsx_metadata(
                archive,
                "xl/_rels/workbook.xml.rels",
                description="workbook relationship metadata",
            )
        )
    except (KeyError, ElementTree.ParseError, DefusedXmlException):
        return fallback

    relationship_namespace = {
        "r": "http://schemas.openxmlformats.org/package/2006/relationships"
    }
    workbook_namespace = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    }
    rels_by_id = {
        relation.attrib.get("Id", ""): relation.attrib.get("Target", "")
        for relation in relationships_root.findall(".//r:Relationship", relationship_namespace)
        if relation.attrib.get("Target")
    }
    ordered: list[str] = []
    relationship_id_attr = (
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    for sheet in workbook_root.findall(".//m:sheets/m:sheet", workbook_namespace):
        target = rels_by_id.get(sheet.attrib.get(relationship_id_attr, ""))
        if not target:
            continue
        normalized = target.replace("\\", "/").lstrip("/")
        if not normalized.startswith("xl/"):
            normalized = f"xl/{normalized}"
        if ".." in PurePosixPath(normalized).parts:
            continue
        if normalized in names and normalized not in ordered:
            ordered.append(normalized)
    ordered.extend(path for path in fallback if path not in ordered)
    return ordered


def _xlsx_shared_strings(
    shared_strings_stream: BinaryIO,
    *,
    namespace: dict[str, str],
) -> list[str]:
    shared_strings: list[str] = []
    total_text_chars = 0
    item_tag = f"{{{namespace['m']}}}si"
    text_tag = f"{{{namespace['m']}}}t"
    element_stack: list[ElementTree.Element] = []
    current_pieces: list[str] | None = None
    current_text_chars = 0
    for event, item in ElementTree.iterparse(
        shared_strings_stream,
        events=("start", "end"),
    ):
        if event == "start":
            element_stack.append(item)
            if item.tag == item_tag:
                if current_pieces is not None:
                    _raise_bad_request(
                        "XLSX matter import contains malformed nested shared strings."
                    )
                if len(shared_strings) >= MATTER_IMPORT_XLSX_MAX_SHARED_STRINGS:
                    _raise_bad_request(
                        "XLSX matter import contains too many shared strings."
                    )
                current_pieces = []
                current_text_chars = 0
            continue
        parent = element_stack[-2] if len(element_stack) >= 2 else None
        if item.tag == text_tag and current_pieces is not None:
            piece = item.text or ""
            current_text_chars += len(piece)
            if current_text_chars > MATTER_IMPORT_XLSX_MAX_SHARED_STRING_CHARS:
                _raise_bad_request(
                    "XLSX matter import contains an oversized shared string."
                )
            current_pieces.append(piece)
        elif item.tag == item_tag:
            if current_pieces is None:
                _raise_bad_request("XLSX matter import contains malformed shared strings.")
            total_text_chars += current_text_chars
            if total_text_chars > MATTER_IMPORT_XLSX_MAX_SHARED_TEXT_CHARS:
                _raise_bad_request(
                    "XLSX matter import shared-string text exceeds the safety limit."
                )
            shared_strings.append(_clean_cell("".join(current_pieces)))
            current_pieces = None
            current_text_chars = 0
        if parent is not None:
            parent.remove(item)
        item.clear()
        element_stack.pop()
    return shared_strings


def _xlsx_rows(
    worksheet_stream: BinaryIO,
    *,
    namespace: dict[str, str],
    shared_strings: list[str],
) -> list[tuple[int, list[str], frozenset[int]]]:
    rows: list[tuple[int, list[str], frozenset[int]]] = []
    previous_row_number: int | None = None
    row_tag = f"{{{namespace['m']}}}row"
    element_stack: list[ElementTree.Element] = []
    for event, row in ElementTree.iterparse(
        worksheet_stream,
        events=("start", "end"),
    ):
        if event == "start":
            element_stack.append(row)
            continue
        if row.tag != row_tag:
            element_stack.pop()
            continue
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
        raw_row_number = row.attrib.get("r")
        if raw_row_number is None:
            row_number = 1 if previous_row_number is None else previous_row_number + 1
        elif not re.fullmatch(r"[1-9][0-9]*", raw_row_number):
            _raise_bad_request("XLSX matter import contains an invalid row reference.")
        else:
            max_row_text = str(MATTER_IMPORT_XLSX_MAX_ROWS)
            if len(raw_row_number) > len(max_row_text) or (
                len(raw_row_number) == len(max_row_text)
                and raw_row_number > max_row_text
            ):
                _raise_bad_request(
                    "XLSX matter import contains a row beyond the Excel safety limit."
                )
            row_number = int(raw_row_number)
        if row_number == previous_row_number:
            _raise_bad_request("XLSX matter import contains duplicate row references.")
        if previous_row_number is not None and row_number < previous_row_number:
            _raise_bad_request("XLSX matter import contains out-of-order row references.")
        previous_row_number = row_number
        parent = element_stack[-2] if len(element_stack) >= 2 else None
        if parent is not None:
            # Detach completed rows from ``sheetData``; ``Element.clear`` alone
            # would leave one empty child object behind for every source row.
            parent.remove(row)
        row.clear()
        element_stack.pop()
        if any(values) or unsafe_indices:
            rows.append((row_number, values, frozenset(unsafe_indices)))
            if len(rows) >= MATTER_IMPORT_PARSE_ROW_BUFFER:
                return rows
    return rows


def _parse_xlsx(content: bytes) -> list[ParsedMatterImportRow]:
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            _validate_xlsx_archive(archive)
            uses_1904_date_system = _xlsx_uses_1904_date_system(archive)
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                with archive.open("xl/sharedStrings.xml") as shared_strings_stream:
                    shared_strings = _xlsx_shared_strings(
                        shared_strings_stream,
                        namespace=namespace,
                    )
            selected_worksheet: (
                tuple[
                    int,
                    int,
                    int,
                    int,
                    int,
                    list[tuple[int, list[str], frozenset[int]]],
                ]
                | None
            ) = None
            for sheet_index, worksheet_path in enumerate(_xlsx_worksheet_paths(archive)):
                with archive.open(worksheet_path) as worksheet_stream:
                    sheet_rows = _xlsx_rows(
                        worksheet_stream,
                        namespace=namespace,
                        shared_strings=shared_strings,
                    )
                if not sheet_rows:
                    continue
                header_index = _header_row_index(sheet_rows)
                header_values = sheet_rows[header_index][1]
                data_row_count = len(sheet_rows) - header_index - 1
                candidate = (
                    int(_header_has_required_identity(header_values)),
                    int(data_row_count > 0),
                    _header_score(header_values),
                    data_row_count,
                    -sheet_index,
                    sheet_rows,
                )
                if (
                    selected_worksheet is None
                    or candidate[:5] > selected_worksheet[:5]
                ):
                    selected_worksheet = candidate
    except (
        KeyError,
        NotImplementedError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        DefusedXmlException,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="XLSX matter import file could not be read.",
        ) from exc

    if selected_worksheet is None:
        return []
    selected_rows = selected_worksheet[5]
    header_index = _header_row_index(selected_rows)
    headers = selected_rows[header_index][1]
    header_unsafe_indices = set(selected_rows[header_index][2])
    header_unsafe_indices.update(
        index for index, header in enumerate(headers) if _unsafe_formula_cell(header)
    )
    parsed: list[ParsedMatterImportRow] = []
    for row_number, values, unsafe_indices in selected_rows[header_index + 1 :]:
        raw = {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
            if header
        }
        if uses_1904_date_system:
            for header in headers:
                if (
                    header
                    and _canonical_header(header) == "filing_date"
                    and header in raw
                ):
                    raw[header] = _normalise_1904_xlsx_date(raw[header])
        effective_unsafe_indices = set(header_unsafe_indices) | set(unsafe_indices)
        unsafe_headers: set[str] = set()
        for index in effective_unsafe_indices:
            if index < len(headers) and headers[index]:
                unsafe_headers.add(headers[index])
                continue
            synthetic_header = f"Unmapped Column {index + 1}"
            raw[synthetic_header] = values[index] if index < len(values) else ""
            unsafe_headers.add(synthetic_header)
        if any(raw.values()) or effective_unsafe_indices:
            parsed.append(
                ParsedMatterImportRow(
                    row_number=row_number,
                    raw=raw,
                    unsafe_headers=frozenset(unsafe_headers),
                )
            )
    return parsed


def parse_matter_import_mapping(
    *,
    filename: str,
    content_type: str | None,
    content: bytes,
) -> ParsedMatterImport:
    if len(content) > MATTER_IMPORT_MAPPING_MAX_BYTES:
        _raise_bad_request("Matter import mapping file exceeds the 2 MB limit.")
    kind = _detect_mapping_kind(filename, content_type)
    if kind == "csv":
        rows = _parse_csv(content)
    elif kind == "json":
        rows = _parse_json(content)
    else:
        rows = _parse_xlsx(content)
    if len(rows) > MATTER_IMPORT_MAX_ROWS:
        _raise_bad_request(f"Matter import supports at most {MATTER_IMPORT_MAX_ROWS} rows.")
    return ParsedMatterImport(manifest_format=kind, rows=rows)


def _safe_document_name(value: str) -> str | None:
    cleaned = value.strip().replace("\\", "/")
    if not cleaned or len(cleaned) > 500:
        return None
    if any(ord(char) < 32 for char in cleaned):
        return None
    path = PurePosixPath(cleaned)
    if path.is_absolute() or ".." in path.parts:
        return None
    if cleaned.endswith("/"):
        return None
    if cleaned.startswith("__MACOSX/"):
        return None
    return cleaned


def _document_key(value: str) -> str:
    return value.strip().replace("\\", "/").lower()


def _parse_document_manifest(filename: str, content: bytes) -> list[str]:
    if len(content) > MATTER_IMPORT_DOCUMENT_MANIFEST_MAX_BYTES:
        _raise_bad_request("Document manifest exceeds the 512 KB limit.")
    suffix = PurePosixPath(filename or "").suffix.lower()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document manifest must be UTF-8 encoded.",
        ) from exc
    names: list[str] = []
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document manifest JSON could not be parsed.",
            ) from exc
        if isinstance(data, dict):
            data = data.get("files", [])
        if not isinstance(data, list):
            _raise_bad_request("Document manifest JSON must be a list or object with files.")
        names = [_clean_cell(item) for item in data]
    elif suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return []
        for row in reader:
            filename_value = (
                row.get("filename")
                or row.get("path")
                or row.get("file")
                or next(iter(row.values()), "")
            )
            names.append(_clean_cell(filename_value))
    else:
        names = [_clean_cell(line) for line in text.splitlines()]
    return _bounded_document_names(names)


def _parse_document_archive(filename: str, content_type: str | None, content: bytes) -> list[str]:
    if len(content) > MATTER_IMPORT_DOCUMENT_ARCHIVE_MAX_BYTES:
        _raise_bad_request("Document archive exceeds the 10 MB dry-run limit.")
    suffix = PurePosixPath(filename or "").suffix.lower()
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if suffix != ".zip" or normalized_content_type not in _ZIP_CONTENT_TYPES:
        _raise_bad_request("Document archive dry-run only supports ZIP files.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZIP document archive could not be read.",
        ) from exc
    return _bounded_document_names(names)


def _bounded_document_names(names: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for name in names:
        safe = _safe_document_name(name)
        if safe is None:
            continue
        key = _document_key(safe)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(safe)
        if len(cleaned) > MATTER_IMPORT_MAX_DOCUMENT_REFERENCES:
            _raise_bad_request(
                "Matter import supports at most "
                f"{MATTER_IMPORT_MAX_DOCUMENT_REFERENCES} document references."
            )
    return cleaned


def parse_matter_import_document_manifest(
    *,
    filename: str,
    content: bytes,
) -> list[str]:
    return _parse_document_manifest(filename, content)


def parse_matter_import_document_archive(
    *,
    filename: str,
    content_type: str | None,
    content: bytes,
) -> list[str]:
    return _parse_document_archive(filename, content_type, content)


def _split_document_references(value: str | None) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            names = [_clean_cell(item) for item in parsed if _clean_cell(item)]
            if len(names) > MATTER_IMPORT_MAX_DOCUMENT_REFERENCES:
                _raise_bad_request(
                    "Matter import supports at most "
                    f"{MATTER_IMPORT_MAX_DOCUMENT_REFERENCES} document references."
                )
            return names
    pieces = re.split(r"[\n;,]+", stripped)
    names = [_clean_cell(piece) for piece in pieces if piece.strip()]
    if len(names) > MATTER_IMPORT_MAX_DOCUMENT_REFERENCES:
        _raise_bad_request(
            "Matter import supports at most "
            f"{MATTER_IMPORT_MAX_DOCUMENT_REFERENCES} document references."
        )
    return names


def _normalised_key(*values: str | None) -> str:
    return "|".join(re.sub(r"\s+", " ", (value or "").strip()).lower() for value in values)


def _visible_existing_matter_candidates(
    session: Session,
    *,
    context: SessionContext,
) -> list[ExistingMatterCandidate]:
    rows = session.execute(
        select(
            Matter.id,
            Matter.matter_code,
            Matter.title,
            Matter.client_name,
            Matter.case_number,
        )
        .where(
            Matter.company_id == context.company.id,
            visible_matters_filter(session, context=context),
        )
        .order_by(Matter.matter_code.asc(), Matter.id.asc())
    )
    return [
        ExistingMatterCandidate(
            matter_id=str(matter_id),
            matter_code=str(matter_code),
            title=str(title),
            client_name=str(client_name) if client_name else None,
            case_number=str(case_number) if case_number else None,
        )
        for matter_id, matter_code, title, client_name, case_number in rows
    ]


def _duplicate_candidate_record(
    candidate: ExistingMatterCandidate,
) -> BulkMatterImportDuplicateCandidate:
    return BulkMatterImportDuplicateCandidate(
        matter_id=candidate.matter_id,
        matter_code=candidate.matter_code,
        title=candidate.title,
        client_name=candidate.client_name,
    )


def _business_match_key(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", (value or "").strip()).casefold()
    normalized = normalized.replace("&", " and ")
    # Preserve symbols that carry meaning in names such as C++ and C#
    # instead of collapsing distinct practice areas or teams to "c".
    normalized = normalized.replace("+", " plus ").replace("#", " sharp ")
    return " ".join(
        "".join(char if char.isalnum() else " " for char in normalized).split()
    )


def _exact_business_match_key(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", (value or "").strip()).casefold()
    return " ".join(normalized.split())


def _add_unique_team_lookup(
    lookup: dict[str, Team | None],
    key: str,
    team: Team,
) -> None:
    if not key:
        return
    if key not in lookup:
        lookup[key] = team
        return
    existing = lookup[key]
    if existing is not None and existing.id != team.id:
        lookup[key] = None


def _add_unique_label_lookup(
    lookup: dict[str, str | None],
    key: str,
    label: str,
) -> None:
    if not key:
        return
    if key not in lookup:
        lookup[key] = label
        return
    existing = lookup[key]
    if existing is not None and _exact_business_match_key(
        existing
    ) != _exact_business_match_key(label):
        lookup[key] = None


def _resolve_team(
    value: str,
    *,
    exact_lookup: dict[str, Team | None],
    normalized_lookup: dict[str, Team | None],
) -> tuple[Team | None, bool]:
    exact_key = _exact_business_match_key(value)
    if exact_key in exact_lookup:
        team = exact_lookup[exact_key]
        return team, team is None
    normalized_key = _business_match_key(value)
    if normalized_key in normalized_lookup:
        team = normalized_lookup[normalized_key]
        return team, team is None
    return None, False


def _resolve_business_label(
    value: str,
    *,
    exact_lookup: dict[str, str | None],
    normalized_lookup: dict[str, str | None],
) -> str:
    exact_key = _exact_business_match_key(value)
    if exact_key in exact_lookup and exact_lookup[exact_key] is not None:
        return exact_lookup[exact_key] or value
    normalized_key = _business_match_key(value)
    if (
        normalized_key in normalized_lookup
        and normalized_lookup[normalized_key] is not None
    ):
        return normalized_lookup[normalized_key] or value
    # A non-catalog or ambiguous presentation-equivalent label is valid
    # business data. Preserve it instead of silently choosing another label.
    return value


def _controlled_value_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().casefold())


_MATTER_STATUS_ALIASES = {
    "active": "active",
    "intake": "intake",
    "onhold": "on_hold",
    "hold": "on_hold",
    "disposed": "disposed",
    "closed": "disposed",
}

_FORUM_LEVEL_ALIASES = {
    "lowercourt": "lower_court",
    "districtcourt": "lower_court",
    "districtandsessionscourt": "lower_court",
    "districtsessionscourt": "lower_court",
    "sessionscourt": "lower_court",
    "highcourt": "high_court",
    "supremecourt": "supreme_court",
    "supremecourtofindia": "supreme_court",
    "tribunal": "tribunal",
    "consumerforum": "tribunal",
    "consumercommission": "tribunal",
    "arbitration": "arbitration",
    "arbitraltribunal": "arbitration",
    "advisory": "advisory",
}

_FORUM_CATEGORY_ALIASES = {
    "supremecourt": "supreme_court",
    "supremecourtofindia": "supreme_court",
    "highcourt": "high_court",
    "districtcourt": "district_court",
    "districtandsessionscourt": "district_court",
    "districtsessionscourt": "district_court",
    "sessionscourt": "district_court",
    "ncdrc": "ncdrc",
    "nationalcommission": "ncdrc",
    "statecommission": "state_commission",
    "scdrc": "state_commission",
    "districtcommission": "district_commission",
    "dcdrc": "district_commission",
    "dratdrt": "drt_drat",
    "drat": "drt_drat",
    "drt": "drt_drat",
    "recoveryforum": "recovery_forum",
    "recoveryforums": "recovery_forum",
    "nclatnclt": "company_law_tribunal",
    "nclat": "company_law_tribunal",
    "nclt": "company_law_tribunal",
    "tdsat": "tdsat",
    "appellatetribunal": "appellate_tribunal",
}

_FORUM_CATEGORY_LABELS = {
    "supreme_court": "Supreme Court",
    "high_court": "High Court",
    "district_court": "District Court",
    "ncdrc": "NCDRC",
    "state_commission": "State Commission",
    "district_commission": "District Commission",
    "drt_drat": "DRAT / DRT",
    "recovery_forum": "Recovery Forums",
    "company_law_tribunal": "NCLAT / NCLT",
    "tdsat": "TDSAT",
    "appellate_tribunal": "Appellate Tribunal",
}

# Client-maintained files predating the catalog used human common-court labels
# and sometimes a descriptive bench name. Rejecting those rows would break the
# established import contract. Exact values still resolve to catalog IDs, while
# only these three historical court families retain the old level/name fallback.
# Specialist and consumer categories introduced by the catalog are fail-closed.
_LEGACY_CATALOG_OPTIONAL_CATEGORIES = {
    "supreme_court",
    "high_court",
    "district_court",
}


@dataclass(frozen=True)
class _ResolvedImportForum:
    forum_level: str | None
    court_name: str | None
    forum_catalog_entry_id: str | None = None
    forum_state: str | None = None
    forum_district: str | None = None
    forum_city: str | None = None
    forum_consumer_level: str | None = None
    error: str | None = None


def _catalog_category(entry: ForumCatalogEntry) -> str:
    if entry.forum_type != "consumer_forum":
        return entry.forum_type
    return {
        "national": "ncdrc",
        "state": "state_commission",
        "district": "district_commission",
    }.get(entry.consumer_level or "", "consumer_forum")


def _forum_entry_match_keys(entry: ForumCatalogEntry) -> set[str]:
    values = {
        entry.id,
        entry.name,
        entry.lineage,
        entry.state,
        entry.district,
        entry.city,
    }
    return {_controlled_value_key(value) for value in values if value}


def _resolved_catalog_entry(entry: ForumCatalogEntry) -> _ResolvedImportForum:
    return _ResolvedImportForum(
        forum_level=entry.forum_level,
        court_name=entry.name,
        forum_catalog_entry_id=entry.id,
        forum_state=entry.state,
        forum_district=entry.district,
        forum_city=entry.city,
        forum_consumer_level=entry.consumer_level,
    )


def _resolve_import_forum(
    *,
    catalog_entries: list[ForumCatalogEntry],
    supplied_forum: str | None,
    supplied_court: str | None,
    supplied_catalog_entry_id: str | None,
) -> _ResolvedImportForum:
    """Resolve bulk input through the same active catalog as manual entry."""
    forum_text = (supplied_forum or "").strip()
    court_text = (supplied_court or "").strip()
    catalog_id = (supplied_catalog_entry_id or "").strip()
    entries_by_id = {entry.id: entry for entry in catalog_entries}

    if catalog_id:
        entry = entries_by_id.get(catalog_id)
        if entry is None:
            return _ResolvedImportForum(
                forum_level=None,
                court_name=court_text or None,
                error="Forum catalog selection is inactive or does not exist.",
            )
        category = _FORUM_CATEGORY_ALIASES.get(_controlled_value_key(forum_text))
        normalized_level = _normalise_forum_level(forum_text)
        if category and _catalog_category(entry) != category:
            return _ResolvedImportForum(
                forum_level=None,
                court_name=court_text or None,
                error="Forum category does not match the selected catalog entry.",
            )
        if not category and normalized_level and normalized_level != entry.forum_level:
            return _ResolvedImportForum(
                forum_level=None,
                court_name=court_text or None,
                error="Forum level does not match the selected catalog entry.",
            )
        if court_text and _controlled_value_key(court_text) not in _forum_entry_match_keys(entry):
            return _ResolvedImportForum(
                forum_level=None,
                court_name=court_text,
                error="Court does not match the selected forum catalog entry.",
            )
        return _resolved_catalog_entry(entry)

    # Preserve imports generated by earlier CaseOps templates, which used the
    # canonical enum tokens directly. New human-readable category labels use
    # the catalog resolver below and therefore require an exact selection.
    if forum_text.casefold() in {
        "lower_court",
        "high_court",
        "supreme_court",
        "tribunal",
        "arbitration",
        "advisory",
    }:
        return _ResolvedImportForum(
            forum_level=_normalise_forum_level(forum_text),
            court_name=court_text or None,
        )

    category = _FORUM_CATEGORY_ALIASES.get(_controlled_value_key(forum_text))
    if category is None:
        return _ResolvedImportForum(
            forum_level=_normalise_forum_level(forum_text),
            court_name=court_text or None,
        )

    candidates = [entry for entry in catalog_entries if _catalog_category(entry) == category]
    match_key = _controlled_value_key(court_text)
    if match_key:
        candidates = [
            entry for entry in candidates if match_key in _forum_entry_match_keys(entry)
        ]
    if len(candidates) == 1:
        return _resolved_catalog_entry(candidates[0])

    if category in _LEGACY_CATALOG_OPTIONAL_CATEGORIES:
        return _ResolvedImportForum(
            forum_level={
                "supreme_court": "supreme_court",
                "high_court": "high_court",
                "district_court": "lower_court",
            }[category],
            court_name=court_text or None,
        )

    label = _FORUM_CATEGORY_LABELS[category]
    if not match_key:
        reason = f"Court is required for {label} and must use the active forum catalog."
    elif not candidates:
        reason = f"Court is not an active {label} catalog selection."
    else:
        reason = f"Court matches multiple {label} catalog selections; use the exact name."
    return _ResolvedImportForum(
        forum_level=None,
        court_name=court_text or None,
        error=reason,
    )


def _normalise_matter_status(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    return _MATTER_STATUS_ALIASES.get(_controlled_value_key(cleaned), cleaned.casefold())


def _normalise_forum_level(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    return _FORUM_LEVEL_ALIASES.get(_controlled_value_key(cleaned), cleaned.casefold())


def _parse_import_date(value: str | None) -> tuple[date | None, str | None]:
    cleaned = (value or "").strip()
    if not cleaned:
        return None, None
    if re.fullmatch(r"\d{1,7}(?:\.\d+)?", cleaned):
        serial_text = cleaned.partition(".")[0]
        serial = int(serial_text)
        if 1 <= serial <= 2_958_465:
            return date(1899, 12, 30) + timedelta(days=serial), None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date(), None
    except ValueError:
        pass
    for date_format in (
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%d.%m.%y",
        "%d %b %Y",
        "%d-%b-%Y",
        "%d %B %Y",
        "%d-%B-%Y",
    ):
        try:
            return datetime.strptime(cleaned, date_format).date(), None
        except ValueError:
            continue
    return (
        None,
        "Filing date must be a common ISO/day-first date or a valid Excel date.",
    )


def _directory_lookups(
    session: Session,
    *,
    context: SessionContext,
) -> tuple[
    dict[str, CompanyMembership],
    dict[str, Team | None],
    dict[str, Team | None],
    set[tuple[str, str]],
    dict[str, str | None],
    dict[str, str | None],
]:
    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.is_active.is_(True),
            )
        ).unique()
    )
    members_by_email = {
        membership.user.email.strip().lower(): membership
        for membership in memberships
        if membership.user is not None and membership.user.is_active
    }
    teams = list(
        session.scalars(
            select(Team).where(
                Team.company_id == context.company.id,
                Team.is_active.is_(True),
            )
        )
    )
    teams_by_exact_key: dict[str, Team | None] = {}
    teams_by_normalized_key: dict[str, Team | None] = {}
    for team in teams:
        for value in (team.slug, team.name):
            _add_unique_team_lookup(
                teams_by_exact_key,
                _exact_business_match_key(value),
                team,
            )
            _add_unique_team_lookup(
                teams_by_normalized_key,
                _business_match_key(value),
                team,
            )
    team_ids = {team.id for team in teams}
    team_memberships = (
        {
            (team_id, membership_id)
            for team_id, membership_id in session.execute(
                select(TeamMembership.team_id, TeamMembership.membership_id).where(
                    TeamMembership.team_id.in_(team_ids)
                )
            )
        }
        if team_ids
        else set()
    )
    practice_areas_by_exact_key: dict[str, str | None] = {}
    practice_areas_by_normalized_key: dict[str, str | None] = {}

    def remember_practice_area(key_source: str, canonical_label: str) -> None:
        _add_unique_label_lookup(
            practice_areas_by_exact_key,
            _exact_business_match_key(key_source),
            canonical_label,
        )
        _add_unique_label_lookup(
            practice_areas_by_normalized_key,
            _business_match_key(key_source),
            canonical_label,
        )

    for value in _DEFAULT_PRACTICE_AREAS:
        remember_practice_area(value, value)
    for value in session.scalars(
        select(Matter.practice_area).where(Matter.company_id == context.company.id).distinct()
    ):
        if value:
            remember_practice_area(value, value)
    for team in teams:
        if team.kind != TeamKind.PRACTICE_AREA:
            continue
        remember_practice_area(team.name, team.name)
        remember_practice_area(team.slug, team.name)
    return (
        members_by_email,
        teams_by_exact_key,
        teams_by_normalized_key,
        team_memberships,
        practice_areas_by_exact_key,
        practice_areas_by_normalized_key,
    )


def _valid_phone(value: str | None) -> bool:
    if not value:
        return True
    cleaned = value.strip()
    phone_pattern = re.compile(
        r"(?P<number>\+?[0-9()\s.,#\-/&]+)(?:(?:ext\.?|x)\s*\d{1,10})?",
        flags=re.IGNORECASE,
    )
    match = phone_pattern.fullmatch(cleaned)
    if match is None:
        return False
    main_number_digits = re.sub(r"\D", "", match.group("number"))
    return 7 <= len(main_number_digits) <= 20


def dry_run_bulk_matter_import(
    session: Session,
    *,
    context: SessionContext,
    parsed_import: ParsedMatterImport,
    available_document_filenames: list[str] | None = None,
    strict_business_rules: bool = False,
    record_audit: bool = True,
) -> BulkMatterImportDryRunResponse:
    available_document_filenames = _bounded_document_names(available_document_filenames or [])
    available_document_keys = {_document_key(name) for name in available_document_filenames}
    (
        members_by_email,
        teams_by_exact_key,
        teams_by_normalized_key,
        team_memberships,
        practice_areas_by_exact_key,
        practice_areas_by_normalized_key,
    ) = _directory_lookups(session, context=context)
    forum_catalog_entries = list(
        session.scalars(
            select(ForumCatalogEntry)
            .where(ForumCatalogEntry.is_active.is_(True))
            .order_by(ForumCatalogEntry.display_order, ForumCatalogEntry.id)
        )
    )
    canonical_rows: list[tuple[ParsedMatterImportRow, dict[str, str], bool]] = []
    for row in parsed_import.rows:
        unsafe_headers = set(row.unsafe_headers)
        unsafe_by_header = {
            header: header in unsafe_headers or _unsafe_import_cell(header, value)
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
                ParsedMatterImportRow(row_number=row.row_number, raw=sanitized_raw),
                _normalise_raw_row(canonical_input),
                any(unsafe_by_header.values()),
            )
        )

    matter_codes = [
        row.get("matter_code", "").strip()
        for _parsed, row, _unsafe in canonical_rows
        if row.get("matter_code", "").strip()
    ]
    title_client_keys = [
        _normalised_key(row.get("title"), row.get("client_name"))
        for _parsed, row, _unsafe in canonical_rows
        if row.get("title", "").strip()
    ]
    duplicate_import_codes = {
        code.lower()
        for code in matter_codes
        if sum(1 for candidate in matter_codes if candidate.lower() == code.lower()) > 1
    }
    duplicate_import_title_clients = {
        key for key in title_client_keys if title_client_keys.count(key) > 1
    }
    case_numbers = [
        row.get("case_number", "").strip()
        for _parsed, row, _unsafe in canonical_rows
        if row.get("case_number", "").strip()
    ]
    duplicate_import_case_numbers = {
        number.lower()
        for number in case_numbers
        if sum(1 for candidate in case_numbers if candidate.lower() == number.lower()) > 1
    }

    existing_candidates = _visible_existing_matter_candidates(session, context=context)
    existing_by_code: dict[str, list[ExistingMatterCandidate]] = {}
    existing_by_title_client: dict[str, list[ExistingMatterCandidate]] = {}
    existing_by_case_number: dict[str, list[ExistingMatterCandidate]] = {}
    for candidate in existing_candidates:
        existing_by_code.setdefault(candidate.matter_code.lower(), []).append(candidate)
        existing_by_title_client.setdefault(
            _normalised_key(candidate.title, candidate.client_name),
            [],
        ).append(candidate)
        if candidate.case_number:
            existing_by_case_number.setdefault(candidate.case_number.lower(), []).append(candidate)

    row_plans: list[BulkMatterImportRowPlan] = []
    for parsed, row, unsafe_formula in canonical_rows:
        errors: list[str] = []
        if unsafe_formula:
            errors.append("Unsafe formula-like cell values are not allowed.")

        title = row.get("title", "").strip() or None
        matter_code = row.get("matter_code", "").strip() or None
        matter_type = row.get("matter_type", "").strip() or None
        client_name = row.get("client_name", "").strip() or None
        client_code = row.get("client_code", "").strip() or None
        client_contact_number = row.get("client_contact_number", "").strip() or None
        client_email = row.get("client_email", "").strip().lower() or None
        opposing_party = row.get("opposing_party", "").strip() or None
        opposing_counsel = row.get("opposing_counsel", "").strip() or None
        supplied_practice_area = row.get("practice_area", "").strip() or None
        practice_area = (
            _resolve_business_label(
                supplied_practice_area,
                exact_lookup=practice_areas_by_exact_key,
                normalized_lookup=practice_areas_by_normalized_key,
            )
            if supplied_practice_area
            else None
        )
        supplied_status = row.get("status", "").strip()
        matter_status = (
            _normalise_matter_status(supplied_status) or DEFAULT_MATTER_STATUS.value
        )
        description = row.get("description", "").strip() or None
        resolved_forum = _resolve_import_forum(
            catalog_entries=forum_catalog_entries,
            supplied_forum=row.get("forum_level"),
            supplied_court=row.get("court_name"),
            supplied_catalog_entry_id=row.get("forum_catalog_entry_id"),
        )
        forum_level = resolved_forum.forum_level
        court_name = resolved_forum.court_name
        forum_catalog_entry_id = resolved_forum.forum_catalog_entry_id
        forum_state = resolved_forum.forum_state
        forum_district = resolved_forum.forum_district
        forum_city = resolved_forum.forum_city
        forum_consumer_level = resolved_forum.forum_consumer_level
        court_forum_number = row.get("court_forum_number", "").strip() or None
        case_number = row.get("case_number", "").strip() or None
        filing_number = row.get("filing_number", "").strip() or None
        filing_date, filing_date_error = _parse_import_date(row.get("filing_date"))
        owner_email = row.get("owner_email", "").strip().lower() or None
        team_slug = row.get("team_slug", "").strip() or None
        responsible_lawyer_email = (
            row.get("responsible_lawyer_email", "").strip().lower() or None
        )
        owner_membership = members_by_email.get(owner_email or "")
        responsible_membership = members_by_email.get(responsible_lawyer_email or "")
        team, team_lookup_ambiguous = (
            _resolve_team(
                team_slug,
                exact_lookup=teams_by_exact_key,
                normalized_lookup=teams_by_normalized_key,
            )
            if team_slug
            else (None, False)
        )
        category = _normalise_document_category(row.get("document_category"))

        if title is None:
            errors.append("Matter title is required.")
        if matter_code is None:
            errors.append("Matter code is required.")
        if practice_area is None:
            errors.append("Practice area is required.")
        if forum_level is None and not resolved_forum.error:
            errors.append("Forum level is required.")
        if resolved_forum.error:
            errors.append(resolved_forum.error)
        if filing_date_error:
            errors.append(filing_date_error)
        if not _valid_phone(client_contact_number):
            errors.append("Client contact number must contain 7 to 20 digits.")
        if owner_email and owner_membership is None:
            errors.append("Matter owner must match an active user in this company.")
        if responsible_lawyer_email and responsible_membership is None:
            errors.append("Responsible lawyer must match an active user in this company.")
        if team_lookup_ambiguous:
            errors.append(
                "Assigned team matches more than one active team; use an exact team "
                "name or slug."
            )
        elif team_slug and team is None:
            errors.append("Assigned team must match an active team in this company.")
        if context.company.team_scoping_enabled and team is not None:
            for label, membership in (
                ("Matter owner", owner_membership),
                ("Responsible lawyer", responsible_membership),
            ):
                if membership and (team.id, membership.id) not in team_memberships:
                    errors.append(f"{label} must belong to the assigned team.")
        if category == "unsupported":
            errors.append("Document category is unsupported.")
            category = None
        document_references: list[BulkMatterImportDocumentReference] = []
        for document_name in _split_document_references(row.get("document_filenames")):
            safe_name = _safe_document_name(document_name)
            if safe_name is None:
                document_references.append(
                    BulkMatterImportDocumentReference(
                        filename=document_name[:120],
                        category=category,
                        status="invalid",
                    )
                )
                errors.append("Document filename reference is invalid.")
                continue
            if not available_document_keys:
                reference_status: Literal["unchecked", "available", "missing"] = "unchecked"
            elif _document_key(safe_name) in available_document_keys:
                reference_status = "available"
            else:
                reference_status = "missing"
                errors.append("Document filename reference is not present in the manifest.")
            document_references.append(
                BulkMatterImportDocumentReference(
                    filename=safe_name,
                    category=category,
                    status=reference_status,
                )
            )

        duplicate_candidates: list[BulkMatterImportDuplicateCandidate] = []
        if matter_code:
            if matter_code.lower() in duplicate_import_codes:
                errors.append("Duplicate matter code in this import file.")
            duplicate_candidates.extend(
                _duplicate_candidate_record(candidate)
                for candidate in existing_by_code.get(matter_code.lower(), [])
            )
        title_client_key = _normalised_key(title, client_name)
        if title and title_client_key in duplicate_import_title_clients:
            errors.append("Duplicate matter title/client in this import file.")
        duplicate_candidates.extend(
            _duplicate_candidate_record(candidate)
            for candidate in existing_by_title_client.get(title_client_key, [])
            if candidate.matter_id
        )
        if duplicate_candidates:
            errors.append("Duplicate matter candidate exists for this company.")
        if case_number:
            if case_number.lower() in duplicate_import_case_numbers:
                errors.append("Duplicate case number in this import file.")
            case_candidates = existing_by_case_number.get(case_number.lower(), [])
            duplicate_candidates.extend(
                _duplicate_candidate_record(candidate) for candidate in case_candidates
            )
            if case_candidates:
                errors.append("Duplicate case number exists for this company.")

        if matter_status == "disposed":
            errors.append(
                "A matter cannot be imported in a disposed state; use the "
                "audited lifecycle workflow after creation."
            )

        if title and matter_code and practice_area and forum_level:
            try:
                validated_payload = MatterCreateRequest.model_validate(
                    {
                        "title": title,
                        "matter_code": matter_code,
                        "matter_type": matter_type,
                        "client_name": client_name,
                        "client_code": client_code,
                        "client_contact_number": client_contact_number,
                        "client_email": client_email,
                        "opposing_party": opposing_party,
                        "opposing_counsel": opposing_counsel,
                        "case_number": case_number,
                        "filing_number": filing_number,
                        "filing_date": filing_date,
                        "status": matter_status,
                        "practice_area": practice_area,
                        "forum_level": forum_level,
                        "court_name": court_name,
                        "forum_catalog_entry_id": forum_catalog_entry_id,
                        "forum_state": forum_state,
                        "forum_district": forum_district,
                        "forum_city": forum_city,
                        "forum_consumer_level": forum_consumer_level,
                        "court_forum_number": court_forum_number,
                        "description": description,
                        "assignee_membership_id": (
                            owner_membership.id if owner_membership else None
                        ),
                        "responsible_lawyer_membership_id": (
                            responsible_membership.id if responsible_membership else None
                        ),
                        "team_id": team.id if team else None,
                    }
                )
                matter_code = validated_payload.matter_code
                matter_status = validated_payload.status
                practice_area = validated_payload.practice_area
                forum_level = validated_payload.forum_level
            except ValidationError as exc:
                for item in exc.errors():
                    loc = ".".join(str(part) for part in item.get("loc", ()))
                    message = str(item.get("msg", "Invalid value."))
                    errors.append(f"{loc}: {message}" if loc else message)

        row_plans.append(
            BulkMatterImportRowPlan(
                row_number=parsed.row_number,
                status="invalid" if errors else "valid",
                matter_code=matter_code,
                title=title,
                matter_type=matter_type,
                practice_area=practice_area,
                matter_status=matter_status,
                description=description,
                client_name=client_name,
                client_code=client_code,
                client_contact_number=client_contact_number,
                client_email=client_email,
                opposing_party_name=opposing_party,
                opposing_counsel=opposing_counsel,
                forum_level=forum_level,
                court_name=court_name,
                forum_catalog_entry_id=forum_catalog_entry_id,
                forum_state=forum_state,
                forum_district=forum_district,
                forum_city=forum_city,
                forum_consumer_level=forum_consumer_level,
                court_forum_number=court_forum_number,
                case_number=case_number,
                filing_number=filing_number,
                filing_date=filing_date,
                owner_email=owner_email,
                owner_membership_id=owner_membership.id if owner_membership else None,
                team_slug=team_slug,
                team_id=team.id if team else None,
                responsible_lawyer_email=responsible_lawyer_email,
                responsible_lawyer_membership_id=(
                    responsible_membership.id if responsible_membership else None
                ),
                document_references=document_references,
                duplicate_candidates=duplicate_candidates,
                errors=sorted(set(errors)),
            )
        )

    valid_count = sum(1 for row in row_plans if row.status == "valid")
    duplicate_rows = sum(1 for row in row_plans if row.duplicate_candidates)
    document_reference_count = sum(len(row.document_references) for row in row_plans)
    unsupported_document_reference_count = sum(
        1
        for row in row_plans
        for reference in row.document_references
        if reference.status in {"missing", "invalid"}
    )
    summary = BulkMatterImportDryRunSummary(
        manifest_format=parsed_import.manifest_format,
        total_rows=len(row_plans),
        valid_rows=valid_count,
        invalid_rows=len(row_plans) - valid_count,
        duplicate_candidate_rows=duplicate_rows,
        document_reference_count=document_reference_count,
        unsupported_document_reference_count=unsupported_document_reference_count,
        available_document_count=len(available_document_filenames),
    )
    if record_audit:
        record_from_context(
            session,
            context,
            action="matter.bulk_import.dry_run",
            target_type="matter_import",
            result=AuditResult.SUCCESS,
            metadata={
                "manifest_format": summary.manifest_format,
                "total_rows": summary.total_rows,
                "valid_rows": summary.valid_rows,
                "invalid_rows": summary.invalid_rows,
                "duplicate_candidate_rows": summary.duplicate_candidate_rows,
                "document_reference_count": summary.document_reference_count,
                "unsupported_document_reference_count": (
                    summary.unsupported_document_reference_count
                ),
                "available_document_count": summary.available_document_count,
                "dry_run": True,
                "will_create_matter_count": 0,
                "will_create_attachment_count": 0,
                "storage_writes": 0,
                "corpus_jobs_queued": 0,
            },
        )
        session.commit()
    return BulkMatterImportDryRunResponse(
        company_id=context.company.id,
        summary=summary,
        rows=row_plans,
        limitations=[
            "Dry-run only: no matters, attachments, storage objects, OCR, corpus jobs, " +
            "or embeddings are created.",
            "Commit execution, persistent import jobs, and Google Drive import are " +
            "separate follow-up milestones.",
        ],
    )


def _normalise_document_category(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[\s\-/]+", "_", value.strip().lower())
    if cleaned in {"other_needs_review", "needs_review"}:
        return "needs_review"
    if cleaned in _ALLOWED_DOCUMENT_CATEGORIES:
        return cleaned
    return "unsupported"


def _xlsx_col(index: int) -> str:
    label = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _worksheet_xml(
    rows: list[list[str]],
    *,
    freeze_header: bool = False,
    data_validations: str = "",
) -> str:
    sheet_rows: list[str] = []
    max_columns = max((len(row) for row in rows), default=1)
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            reference = f"{_xlsx_col(column_index)}{row_index}"
            cells.append(
                f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
                f"{escape(str(value))}</t></is></c>"
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    views = (
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        if freeze_header
        else ""
    )
    columns = "".join(
        f'<col min="{index}" max="{index}" width="22" customWidth="1"/>'
        for index in range(1, max_columns + 1)
    )
    auto_filter = f'<autoFilter ref="A1:{_xlsx_col(max_columns)}{max(len(rows), 1)}"/>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"{views}<cols>{columns}</cols><sheetData>{''.join(sheet_rows)}</sheetData>"
        f"{auto_filter}{data_validations}</worksheet>"
    )


def _matter_template_csv_bytes() -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(MATTER_IMPORT_TEMPLATE_HEADERS)
    writer.writerow(
        [
            "Acme recovery proceedings",
            "COM-2026-001",
            "Litigation",
            "Commercial",
            "active",
            "Recovery of unpaid invoices under the supply agreement.",
            "Acme Industries",
            "CLI-001",
            "+91 98765 43210",
            "legal@acme.example",
            "Northstar Supplies",
            "Rao Chambers",
            "High Court",
            "Delhi High Court",
            "COURT-FORUM-123/2026",
            "CS(COMM) 123/2026",
            "FILING-123/2026",
            "2026-07-17",
            "owner@example.com",
            "commercial-litigation",
            "lawyer@example.com",
        ]
    )
    return buffer.getvalue().encode("utf-8")


def _matter_template_xlsx_bytes(
    forum_catalog_entries: list[ForumCatalogEntry],
) -> bytes:
    import_rows = [
        MATTER_IMPORT_TEMPLATE_HEADERS,
        [
            "Acme recovery proceedings",
            "COM-2026-001",
            "Litigation",
            "Commercial",
            "active",
            "Recovery of unpaid invoices under the supply agreement.",
            "Acme Industries",
            "CLI-001",
            "+91 98765 43210",
            "legal@acme.example",
            "Northstar Supplies",
            "Rao Chambers",
            "High Court",
            "Delhi High Court",
            "COURT-FORUM-123/2026",
            "CS(COMM) 123/2026",
            "FILING-123/2026",
            "2026-07-17",
            "owner@example.com",
            "commercial-litigation",
            "lawyer@example.com",
        ],
    ]
    reference_rows = [["Matter Status", "Forum", "Practice Area"]]
    statuses = ["active", "intake", "on_hold"]
    forums = [
        *_FORUM_CATEGORY_LABELS.values(),
        "Tribunal",
        "Arbitration",
        "Advisory",
    ]
    max_reference_rows = max(len(statuses), len(forums), len(_DEFAULT_PRACTICE_AREAS))
    for index in range(max_reference_rows):
        reference_rows.append(
            [
                statuses[index] if index < len(statuses) else "",
                forums[index] if index < len(forums) else "",
                _DEFAULT_PRACTICE_AREAS[index]
                if index < len(_DEFAULT_PRACTICE_AREAS)
                else "",
            ]
        )
    instruction_rows = [
        ["Bulk Matter Import Instructions", "Details"],
        [
            "Required fields",
            "Matter Title, Matter Code, Practice Area, Forum",
        ],
        [
            "Optional defaults",
            "Matter Status defaults to active; Client Name is optional.",
        ],
        [
            "Flexible values",
            (
                "Status and Forum ignore case, spaces, hyphens, and underscores. "
                + "Business punctuation is accepted in descriptive fields."
            ),
        ],
        [
            "Court Forum Number",
            (
                "Optional court/forum reference number, stored separately from Case Number "
                + "and Filing Number."
            ),
        ],
        [
            "Dates",
            "ISO, common day-first formats, and native Excel dates are accepted.",
        ],
        [
            "People",
            "Matter Owner and Responsible Lawyer must be active work-email " +
            "addresses in this company.",
        ],
        ["Teams", "Assigned Team must be an active team name or slug in this company."],
        [
            "Duplicates",
            "Matter Code, Case Number, and matching Matter Title + Client Name are checked.",
        ],
        ["Import", "Upload this file, review every validation error, then confirm import."],
        [
            "Forum catalog",
            (
                "Use Forum Catalog for the exact Court value. Manual creation, editing, "
                + "CSV, and XLSX uploads are validated against this same active master."
            ),
        ],
        [
            "Security",
            (
                "Formula cells and values beginning with =, +, -, or @ are rejected. "
                + "A syntactically valid international phone may begin with + only in "
                + "Client Contact Number."
            ),
        ],
        [
            "Limits",
            f"Maximum {MATTER_IMPORT_MAX_ROWS} data rows and "
            f"{MATTER_IMPORT_MAPPING_MAX_BYTES // (1024 * 1024)} MB.",
        ],
    ]
    validations = (
        '<dataValidations count="3">'
        '<dataValidation type="list" allowBlank="1" sqref="E2:E501">'
        "<formula1>'Reference Values'!$A$2:$A$4</formula1></dataValidation>"
        '<dataValidation type="list" allowBlank="0" sqref="M2:M501">'
        f"<formula1>'Reference Values'!$B$2:$B${len(forums) + 1}</formula1></dataValidation>"
        '<dataValidation type="list" allowBlank="0" sqref="D2:D501">'
        "<formula1>'Reference Values'!$C$2:$C$16</formula1></dataValidation>"
        "</dataValidations>"
    )
    forum_catalog_rows = [
        [
            "Forum",
            "Exact Court / Tribunal",
            "Forum Level",
            "State",
            "District",
            "City",
            "Catalog ID",
            "Source",
        ],
        *[
            [
                _FORUM_CATEGORY_LABELS.get(_catalog_category(entry), entry.forum_type),
                entry.name,
                entry.forum_level,
                entry.state or "",
                entry.district or "",
                entry.city or "",
                entry.id,
                entry.source_url or "",
            ]
            for entry in forum_catalog_entries
        ],
    ]
    worksheets = [
        _worksheet_xml(import_rows, freeze_header=True, data_validations=validations),
        _worksheet_xml(reference_rows, freeze_header=True),
        _worksheet_xml(forum_catalog_rows, freeze_header=True),
        _worksheet_xml(instruction_rows, freeze_header=True),
    ]
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Matter Import" sheetId="1" r:id="rId1"/>'
        '<sheet name="Reference Values" sheetId="2" r:id="rId2"/>'
        '<sheet name="Forum Catalog" sheetId="3" r:id="rId3"/>'
        '<sheet name="Instructions" sheetId="4" r:id="rId4"/></sheets></workbook>'
    )
    workbook_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            '<Relationship '
            f'Id="rId{index}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, 5)
        )
        + "</Relationships>"
    )
    root_relationships = (
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
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, 5)
        )
        + "</Types>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        for index, worksheet in enumerate(worksheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet)
    return buffer.getvalue()


def matter_import_template(
    session: Session,
    format_value: Literal["csv", "xlsx"],
) -> tuple[bytes, str, str]:
    if format_value == "xlsx":
        entries = list(
            session.scalars(
                select(ForumCatalogEntry)
                .where(ForumCatalogEntry.is_active.is_(True))
                .order_by(ForumCatalogEntry.display_order, ForumCatalogEntry.id)
            )
        )
        return (
            _matter_template_xlsx_bytes(entries),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "caseops-matter-import-template.xlsx",
        )
    return (
        _matter_template_csv_bytes(),
        "text/csv; charset=utf-8",
        "caseops-matter-import-template.csv",
    )


def _now() -> datetime:
    from caseops_api.db.models import utcnow

    return utcnow()


def _sanitized_raw(row: ParsedMatterImportRow) -> dict[str, str]:
    return {
        header: (
            "[unsafe formula removed]"
            if header in row.unsafe_headers or _unsafe_import_cell(header, value)
            else value
        )
        for header, value in row.raw.items()
    }


def _normalized_plan(plan: BulkMatterImportRowPlan) -> dict[str, object]:
    return plan.model_dump(
        mode="json",
        exclude={
            "row_number",
            "status",
            "errors",
            "document_references",
            "duplicate_candidates",
        },
        exclude_none=True,
    )


def _load_job(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> MatterBulkImportJob:
    job = session.scalar(
        select(MatterBulkImportJob)
        .options(
            joinedload(MatterBulkImportJob.created_by_membership).joinedload(
                CompanyMembership.user
            )
        )
        .where(
            MatterBulkImportJob.id == job_id,
            MatterBulkImportJob.company_id == context.company.id,
        )
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter import not found.",
        )
    return job


def _job_response(
    session: Session,
    job: MatterBulkImportJob,
    *,
    include_rows: bool = True,
) -> MatterImportJobResponse:
    rows = (
        list(
            session.scalars(
                select(MatterBulkImportRow)
                .where(MatterBulkImportRow.job_id == job.id)
                .order_by(MatterBulkImportRow.row_number, MatterBulkImportRow.id)
            )
        )
        if include_rows
        else []
    )
    uploader = job.created_by_membership
    user = uploader.user if uploader is not None else None
    return MatterImportJobResponse(
        id=job.id,
        company_id=job.company_id,
        filename=job.filename,
        content_type=job.content_type,
        manifest_format=job.manifest_format,  # type: ignore[arg-type]
        file_size_bytes=job.file_size_bytes,
        source_sha256=job.source_sha256,
        status=job.status,  # type: ignore[arg-type]
        total_rows=job.total_rows,
        valid_rows=job.valid_rows,
        invalid_rows=job.invalid_rows,
        created_count=job.created_count,
        failed_count=job.failed_count,
        validation_error_count=job.validation_error_count,
        error_message=job.error_message,
        uploaded_by_membership_id=job.created_by_membership_id,
        uploaded_by_name=user.full_name if user else None,
        uploaded_by_email=user.email if user else None,
        created_at=job.created_at,
        updated_at=job.updated_at,
        expires_at=job.expires_at,
        imported_at=job.imported_at,
        cancelled_at=job.cancelled_at,
        rows=[
            MatterImportRowRecord(
                id=row.id,
                row_number=row.row_number,
                status=row.status,  # type: ignore[arg-type]
                normalized=row.normalized_json,
                errors=list(row.errors_json or []),
                created_matter_id=row.created_matter_id,
            )
            for row in rows
        ],
    )


def _notify_import_actor(
    session: Session,
    *,
    context: SessionContext,
    job: MatterBulkImportJob,
    event_type: str,
    title: str,
    body: str,
) -> None:
    enqueue_notification_delivery_intent(
        session,
        context=context,
        recipient_membership=context.membership,
        channel=NotificationDeliveryChannel.IN_APP,
        event_type=event_type,
        source_type="matter_import",
        source_id=job.id,
        title=title,
        body=body,
    )


def preview_matter_import(
    session: Session,
    *,
    context: SessionContext,
    filename: str,
    content_type: str | None,
    content: bytes,
) -> MatterImportJobResponse:
    parsed = parse_matter_import_mapping(
        filename=filename,
        content_type=content_type,
        content=content,
    )
    if parsed.manifest_format not in {"csv", "xlsx"}:
        _raise_bad_request("Bulk matter creation supports CSV or XLSX files.")
    if not parsed.rows:
        _raise_bad_request("Matter import file contains no data rows.")
    plan = dry_run_bulk_matter_import(
        session,
        context=context,
        parsed_import=parsed,
        strict_business_rules=True,
        record_audit=False,
    )
    now = _now()
    job = MatterBulkImportJob(
        company_id=context.company.id,
        created_by_membership_id=context.membership.id,
        filename=(filename or "matters").strip()[:255],
        content_type=content_type,
        manifest_format=parsed.manifest_format,
        file_size_bytes=len(content),
        source_sha256=sha256(content).hexdigest(),
        status=MatterImportJobStatus.VALIDATED,
        total_rows=plan.summary.total_rows,
        valid_rows=plan.summary.valid_rows,
        invalid_rows=plan.summary.invalid_rows,
        created_count=0,
        failed_count=0,
        validation_error_count=sum(len(row.errors) for row in plan.rows),
        created_at=now,
        updated_at=now,
        expires_at=now + MATTER_IMPORT_PREVIEW_TTL,
    )
    session.add(job)
    session.flush()
    parsed_by_number = {row.row_number: row for row in parsed.rows}
    for row_plan in plan.rows:
        source_row = parsed_by_number[row_plan.row_number]
        session.add(
            MatterBulkImportRow(
                company_id=context.company.id,
                job_id=job.id,
                row_number=row_plan.row_number,
                raw_json=_sanitized_raw(source_row),
                normalized_json=_normalized_plan(row_plan),
                errors_json=row_plan.errors,
                status=(
                    MatterImportRowStatus.VALID
                    if row_plan.status == "valid"
                    else MatterImportRowStatus.INVALID
                ),
                created_at=now,
                updated_at=now,
            )
        )
    record_from_context(
        session,
        context,
        action="matter.import.validated",
        target_type="matter_import",
        target_id=job.id,
        result=AuditResult.SUCCESS,
        metadata={
            "manifest_format": job.manifest_format,
            "file_size_bytes": job.file_size_bytes,
            "source_sha256": job.source_sha256,
            "total_rows": job.total_rows,
            "valid_rows": job.valid_rows,
            "invalid_rows": job.invalid_rows,
            "validation_error_count": job.validation_error_count,
        },
    )
    _notify_import_actor(
        session,
        context=context,
        job=job,
        event_type="matter_import.upload_succeeded",
        title="Matter import uploaded",
        body=f"{job.filename} was uploaded and {job.total_rows} rows were checked.",
    )
    if job.invalid_rows:
        _notify_import_actor(
            session,
            context=context,
            job=job,
            event_type="matter_import.validation_failed",
            title="Matter import has validation errors",
            body=f"{job.invalid_rows} of {job.total_rows} rows need correction.",
        )
    session.commit()
    job = _load_job(session, context=context, job_id=job.id)
    return _job_response(session, job)


def get_matter_import(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> MatterImportJobResponse:
    return _job_response(session, _load_job(session, context=context, job_id=job_id))


def list_matter_imports(
    session: Session,
    *,
    context: SessionContext,
    query: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
) -> MatterImportHistoryResponse:
    filters = [MatterBulkImportJob.company_id == context.company.id]
    if status_filter:
        filters.append(MatterBulkImportJob.status == status_filter)
    normalized_query = (query or "").strip().lower()
    statement = (
        select(MatterBulkImportJob)
        .options(
            joinedload(MatterBulkImportJob.created_by_membership).joinedload(
                CompanyMembership.user
            )
        )
        .outerjoin(
            CompanyMembership,
            CompanyMembership.id == MatterBulkImportJob.created_by_membership_id,
        )
        .outerjoin(User, User.id == CompanyMembership.user_id)
        .where(*filters)
    )
    count_statement = (
        select(func.count(MatterBulkImportJob.id))
        .outerjoin(
            CompanyMembership,
            CompanyMembership.id == MatterBulkImportJob.created_by_membership_id,
        )
        .outerjoin(User, User.id == CompanyMembership.user_id)
        .where(*filters)
    )
    if normalized_query:
        search_filter = (
            func.lower(MatterBulkImportJob.filename).contains(normalized_query)
            | func.lower(User.full_name).contains(normalized_query)
            | func.lower(User.email).contains(normalized_query)
        )
        statement = statement.where(search_filter)
        count_statement = count_statement.where(search_filter)
    jobs = list(
        session.scalars(
            statement.order_by(
                MatterBulkImportJob.created_at.desc(),
                MatterBulkImportJob.id.desc(),
            ).limit(max(1, min(limit, 100)))
        ).unique()
    )
    total = int(session.scalar(count_statement) or 0)
    return MatterImportHistoryResponse(
        imports=[_job_response(session, job, include_rows=False) for job in jobs],
        total=total,
    )


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _job_is_expired(job: MatterBulkImportJob) -> bool:
    return _aware_utc(job.expires_at) <= _aware_utc(_now())


def _parsed_rows_for_revalidation(rows: list[MatterBulkImportRow]) -> ParsedMatterImport:
    parsed_rows = [
        ParsedMatterImportRow(
            row_number=row.row_number,
            raw={key: _clean_cell(value) for key, value in row.normalized_json.items()},
        )
        for row in rows
        if row.status == MatterImportRowStatus.VALID
    ]
    return ParsedMatterImport(manifest_format="json", rows=parsed_rows)


def _payload_from_normalized(normalized: dict[str, object]) -> MatterCreateRequest:
    return MatterCreateRequest.model_validate(
        {
            "title": normalized.get("title"),
            "matter_code": normalized.get("matter_code"),
            "matter_type": normalized.get("matter_type"),
            "practice_area": normalized.get("practice_area"),
            "status": normalized.get("matter_status"),
            "description": normalized.get("description"),
            "client_name": normalized.get("client_name"),
            "client_code": normalized.get("client_code"),
            "client_contact_number": normalized.get("client_contact_number"),
            "client_email": normalized.get("client_email"),
            "opposing_party": normalized.get("opposing_party_name"),
            "opposing_counsel": normalized.get("opposing_counsel"),
            "forum_level": normalized.get("forum_level"),
            "court_name": normalized.get("court_name"),
            "forum_catalog_entry_id": normalized.get("forum_catalog_entry_id"),
            "forum_state": normalized.get("forum_state"),
            "forum_district": normalized.get("forum_district"),
            "forum_city": normalized.get("forum_city"),
            "forum_consumer_level": normalized.get("forum_consumer_level"),
            "court_forum_number": normalized.get("court_forum_number"),
            "case_number": normalized.get("case_number"),
            "filing_number": normalized.get("filing_number"),
            "filing_date": normalized.get("filing_date"),
            "assignee_membership_id": normalized.get("owner_membership_id"),
            "team_id": normalized.get("team_id"),
            "responsible_lawyer_membership_id": normalized.get(
                "responsible_lawyer_membership_id"
            ),
        }
    )


def commit_matter_import(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> MatterImportCommitResponse:
    job = _load_job(session, context=context, job_id=job_id)
    terminal = {
        MatterImportJobStatus.COMPLETED,
        MatterImportJobStatus.COMPLETED_WITH_ERRORS,
    }
    if job.status in terminal:
        response = _job_response(session, job)
        return MatterImportCommitResponse(
            job=response,
            created_matter_ids=[
                row.created_matter_id for row in response.rows if row.created_matter_id
            ],
        )
    is_recovery = job.status == MatterImportJobStatus.IMPORTING
    if job.status not in {
        MatterImportJobStatus.VALIDATED,
        MatterImportJobStatus.IMPORTING,
    }:
        _raise_bad_request("Only a validated matter import can be confirmed.")
    if job.status == MatterImportJobStatus.VALIDATED and _job_is_expired(job):
        job.status = MatterImportJobStatus.EXPIRED
        job.updated_at = _now()
        session.commit()
        _raise_bad_request("Matter import validation has expired. Upload the file again.")

    persisted_rows = list(
        session.scalars(
            select(MatterBulkImportRow)
            .where(MatterBulkImportRow.job_id == job.id)
            .order_by(MatterBulkImportRow.row_number, MatterBulkImportRow.id)
        )
    )
    if not is_recovery:
        revalidation = dry_run_bulk_matter_import(
            session,
            context=context,
            parsed_import=_parsed_rows_for_revalidation(persisted_rows),
            strict_business_rules=True,
            record_audit=False,
        )
        plans_by_number = {plan.row_number: plan for plan in revalidation.rows}
        for row in persisted_rows:
            if row.status != MatterImportRowStatus.VALID:
                continue
            plan = plans_by_number[row.row_number]
            row.normalized_json = _normalized_plan(plan)
            row.errors_json = plan.errors
            row.status = (
                MatterImportRowStatus.VALID
                if plan.status == "valid"
                else MatterImportRowStatus.INVALID
            )
            row.updated_at = _now()
        job.valid_rows = sum(
            1 for row in persisted_rows if row.status == MatterImportRowStatus.VALID
        )
        job.invalid_rows = sum(
            1 for row in persisted_rows if row.status == MatterImportRowStatus.INVALID
        )
        job.validation_error_count = sum(len(row.errors_json or []) for row in persisted_rows)
        if not job.valid_rows:
            job.status = MatterImportJobStatus.COMPLETED_WITH_ERRORS
            job.failed_count = job.total_rows
            job.imported_at = _now()
            job.updated_at = job.imported_at
            session.commit()
            _raise_bad_request("No valid matter rows remain after commit-time revalidation.")

    claim_conditions = [
        MatterBulkImportJob.id == job.id,
        MatterBulkImportJob.company_id == context.company.id,
    ]
    if is_recovery:
        claim_conditions.extend(
            [
                MatterBulkImportJob.status == MatterImportJobStatus.IMPORTING,
                MatterBulkImportJob.updated_at <= _now() - MATTER_IMPORT_STALE_AFTER,
            ]
        )
    else:
        claim_conditions.append(MatterBulkImportJob.status == MatterImportJobStatus.VALIDATED)
    claim = session.execute(
        update(MatterBulkImportJob)
        .where(*claim_conditions)
        .values(status=MatterImportJobStatus.IMPORTING, updated_at=_now())
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        session.rollback()
        _raise_bad_request(
            "Matter import is already being processed. Retry after ten minutes "
            "only if processing stopped."
        )
    session.commit()

    valid_row_ids = [row.id for row in persisted_rows if row.status == MatterImportRowStatus.VALID]
    for row_id in valid_row_ids:
        row = session.get(MatterBulkImportRow, row_id)
        if row is None:
            continue
        row_number = row.row_number
        try:
            created = create_matter(
                session,
                context=context,
                payload=_payload_from_normalized(row.normalized_json),
                commit=False,
            )
            row.status = MatterImportRowStatus.CREATED
            row.created_matter_id = created.id
            row.updated_at = _now()
            heartbeat = session.get(MatterBulkImportJob, job_id)
            if heartbeat is not None:
                heartbeat.updated_at = row.updated_at
            record_from_context(
                session,
                context,
                action="matter.import.row_created",
                target_type="matter_import",
                target_id=job_id,
                matter_id=created.id,
                result=AuditResult.SUCCESS,
                metadata={"row_number": row.row_number},
            )
            # Matter creation, its audit/activity records, the row outcome, and
            # the heartbeat are committed as one transaction.
            session.commit()
        except HTTPException as exc:
            session.rollback()
            row = session.get(MatterBulkImportRow, row_id)
            if row is not None:
                row.status = MatterImportRowStatus.FAILED
                row.errors_json = [
                    str(exc.detail)
                    if exc.status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT}
                    else "Matter could not be created after validation."
                ]
                row.updated_at = _now()
                heartbeat = session.get(MatterBulkImportJob, job_id)
                if heartbeat is not None:
                    heartbeat.updated_at = row.updated_at
                session.commit()
        except Exception:
            safe_job_id = job_id.replace("\r", r"\r").replace("\n", r"\n")
            logger.exception(
                "Unexpected matter import row failure (job_id=%s, row_number=%s)",
                safe_job_id,
                row_number,
            )
            session.rollback()
            row = session.get(MatterBulkImportRow, row_id)
            if row is not None:
                row.status = MatterImportRowStatus.FAILED
                row.errors_json = ["Matter could not be created after validation."]
                row.updated_at = _now()
                heartbeat = session.get(MatterBulkImportJob, job_id)
                if heartbeat is not None:
                    heartbeat.updated_at = row.updated_at
                session.commit()

    job = _load_job(session, context=context, job_id=job_id)
    final_rows = list(
        session.scalars(select(MatterBulkImportRow).where(MatterBulkImportRow.job_id == job.id))
    )
    job.created_count = sum(1 for row in final_rows if row.status == MatterImportRowStatus.CREATED)
    job.failed_count = job.total_rows - job.created_count
    job.status = (
        MatterImportJobStatus.COMPLETED
        if job.failed_count == 0
        else MatterImportJobStatus.COMPLETED_WITH_ERRORS
    )
    job.imported_at = _now()
    job.updated_at = job.imported_at
    record_from_context(
        session,
        context,
        action="matter.import.completed",
        target_type="matter_import",
        target_id=job.id,
        result=(AuditResult.SUCCESS if job.created_count else AuditResult.FAILED),
        metadata={
            "total_rows": job.total_rows,
            "created_count": job.created_count,
            "failed_count": job.failed_count,
            "validation_error_count": job.validation_error_count,
            "status": job.status,
        },
    )
    _notify_import_actor(
        session,
        context=context,
        job=job,
        event_type="matter_import.completed",
        title="Matter import completed",
        body=f"{job.created_count} matters were created; {job.failed_count} rows failed.",
    )
    session.commit()
    job = _load_job(session, context=context, job_id=job.id)
    return MatterImportCommitResponse(
        job=_job_response(session, job),
        created_matter_ids=[
            row.created_matter_id
            for row in final_rows
            if row.status == MatterImportRowStatus.CREATED and row.created_matter_id
        ],
    )


def cancel_matter_import(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> MatterImportJobResponse:
    job = _load_job(session, context=context, job_id=job_id)
    if job.status != MatterImportJobStatus.VALIDATED:
        _raise_bad_request("Only a validated matter import can be cancelled.")
    job.status = MatterImportJobStatus.CANCELLED
    job.cancelled_at = _now()
    job.updated_at = job.cancelled_at
    record_from_context(
        session,
        context,
        action="matter.import.cancelled",
        target_type="matter_import",
        target_id=job.id,
        result=AuditResult.SUCCESS,
        metadata={"total_rows": job.total_rows},
    )
    session.commit()
    return _job_response(session, _load_job(session, context=context, job_id=job.id))


def _safe_csv_cell(value: object) -> str:
    text = str(value or "")
    return f"'{text}" if text.lstrip().startswith(("=", "+", "-", "@")) else text


def matter_import_error_report(
    session: Session,
    *,
    context: SessionContext,
    job_id: str,
) -> tuple[bytes, str]:
    job = _load_job(session, context=context, job_id=job_id)
    rows = list(
        session.scalars(
            select(MatterBulkImportRow)
            .where(
                MatterBulkImportRow.job_id == job.id,
                MatterBulkImportRow.status.in_(
                    [MatterImportRowStatus.INVALID, MatterImportRowStatus.FAILED]
                ),
            )
            .order_by(MatterBulkImportRow.row_number, MatterBulkImportRow.id)
        )
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Row Number", "Matter Code", "Matter Title", "Status", "Errors"])
    for row in rows:
        writer.writerow(
            [
                row.row_number,
                _safe_csv_cell(row.normalized_json.get("matter_code")),
                _safe_csv_cell(row.normalized_json.get("title")),
                row.status,
                _safe_csv_cell("; ".join(row.errors_json or [])),
            ]
        )
    record_from_context(
        session,
        context,
        action="matter.import.error_report_downloaded",
        target_type="matter_import",
        target_id=job.id,
        result=AuditResult.SUCCESS,
        metadata={"error_rows": len(rows)},
    )
    session.commit()
    return buffer.getvalue().encode("utf-8-sig"), f"matter-import-errors-{job.id}.csv"


__all__ = [
    "MATTER_IMPORT_DOCUMENT_ARCHIVE_MAX_BYTES",
    "MATTER_IMPORT_DOCUMENT_MANIFEST_MAX_BYTES",
    "MATTER_IMPORT_MAPPING_MAX_BYTES",
    "MATTER_IMPORT_MAX_ROWS",
    "cancel_matter_import",
    "commit_matter_import",
    "dry_run_bulk_matter_import",
    "get_matter_import",
    "list_matter_imports",
    "matter_import_error_report",
    "matter_import_template",
    "parse_matter_import_document_archive",
    "parse_matter_import_document_manifest",
    "parse_matter_import_mapping",
    "preview_matter_import",
]
