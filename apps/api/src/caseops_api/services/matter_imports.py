from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal
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
    "name": "title",
    "client": "client_name",
    "clientname": "client_name",
    "clientreference": "client_name",
    "clientref": "client_name",
    "clientcode": "client_code",
    "clientcontactnumber": "client_contact_number",
    "clientphone": "client_contact_number",
    "clientemail": "client_email",
    "practicearea": "practice_area",
    "area": "practice_area",
    "mattertype": "matter_type",
    "type": "matter_type",
    "status": "status",
    "matterstatus": "status",
    "forum": "forum_level",
    "forumlevel": "forum_level",
    "court": "court_name",
    "courtname": "court_name",
    "forumname": "court_name",
    "matterdescription": "description",
    "description": "description",
    "opposingparty": "opposing_party",
    "opposingpartyname": "opposing_party",
    "opposingcounsel": "opposing_counsel",
    "casenumber": "case_number",
    "filingnumber": "filing_number",
    "filingdate": "filing_date",
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
    cleaned = re.sub(r"[\s_\-/.]+", "", value.strip().lower())
    return _FIELD_ALIASES.get(cleaned)


def _unsafe_formula_cell(value: str) -> bool:
    cleaned = value.lstrip()
    return bool(cleaned) and cleaned[0] in {"=", "+", "-", "@"}


def _unsafe_import_cell(header: str, value: str) -> bool:
    # A leading plus is a normal international-phone prefix. It is safe only
    # in the phone column and only when every remaining character is part of
    # a phone number. Actual XLSX formula nodes are still rejected separately.
    if (
        _canonical_header(header) == "client_contact_number"
        and value.strip().startswith("+")
        and re.fullmatch(r"\+[0-9 ()-]+", value.strip())
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
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV matter import must be UTF-8 encoded.",
        ) from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    rows: list[ParsedMatterImportRow] = []
    for row_index, row in enumerate(reader, start=2):
        raw = {
            str(key): _clean_cell(value)
            for key, value in row.items()
            if key is not None
        }
        if any(raw.values()):
            rows.append(ParsedMatterImportRow(row_number=row_index, raw=raw))
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
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return max(index - 1, 0)


def _parse_xlsx(content: bytes) -> list[ParsedMatterImportRow]:
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
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError, DefusedXmlException) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="XLSX matter import file could not be read.",
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
    parsed: list[ParsedMatterImportRow] = []
    for row_number, (values, unsafe_indices) in enumerate(rows[1:], start=2):
        raw = {
            header: values[index] if index < len(values) else ""
            for index, header in enumerate(headers)
            if header
        }
        if any(raw.values()):
            parsed.append(
                ParsedMatterImportRow(
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


def _catalog_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _parse_import_date(value: str | None) -> tuple[date | None, str | None]:
    cleaned = (value or "").strip()
    if not cleaned:
        return None, None
    if re.fullmatch(r"\d+(?:\.0+)?", cleaned):
        try:
            serial = int(float(cleaned))
            if 1 <= serial <= 2_958_465:
                return date(1899, 12, 30) + timedelta(days=serial), None
        except (OverflowError, ValueError):
            pass
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(cleaned, date_format).date(), None
        except ValueError:
            continue
    return None, "Filing date must be YYYY-MM-DD, DD/MM/YYYY, or a valid Excel date."


def _directory_lookups(
    session: Session,
    *,
    context: SessionContext,
) -> tuple[
    dict[str, CompanyMembership],
    dict[str, Team],
    set[tuple[str, str]],
    set[str],
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
    teams_by_key: dict[str, Team] = {}
    for team in teams:
        teams_by_key.setdefault(_catalog_key(team.slug), team)
        teams_by_key.setdefault(_catalog_key(team.name), team)
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
    allowed_practice_areas = {_catalog_key(value) for value in _DEFAULT_PRACTICE_AREAS}
    allowed_practice_areas.update(
        _catalog_key(value)
        for value in session.scalars(
            select(Matter.practice_area).where(Matter.company_id == context.company.id).distinct()
        )
        if value
    )
    allowed_practice_areas.update(
        _catalog_key(team.name)
        for team in teams
        if team.kind == TeamKind.PRACTICE_AREA
    )
    allowed_practice_areas.update(
        _catalog_key(team.slug)
        for team in teams
        if team.kind == TeamKind.PRACTICE_AREA
    )
    return members_by_email, teams_by_key, team_memberships, allowed_practice_areas


def _valid_phone(value: str | None) -> bool:
    if not value:
        return True
    cleaned = value.strip()
    digits = re.sub(r"\D", "", cleaned)
    return bool(re.fullmatch(r"\+?[0-9 ()-]+", cleaned)) and 7 <= len(digits) <= 20


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
        teams_by_key,
        team_memberships,
        allowed_practice_areas,
    ) = _directory_lookups(session, context=context)
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
        practice_area = row.get("practice_area", "").strip() or None
        supplied_status = row.get("status", "").strip()
        matter_status = supplied_status or DEFAULT_MATTER_STATUS.value
        description = row.get("description", "").strip() or None
        forum_level = row.get("forum_level", "").strip() or None
        court_name = row.get("court_name", "").strip() or None
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
        team = teams_by_key.get(_catalog_key(team_slug)) if team_slug else None
        category = _normalise_document_category(row.get("document_category"))

        if title is None:
            errors.append("Matter title is required.")
        if matter_code is None:
            errors.append("Matter code is required.")
        if strict_business_rules and client_name is None:
            errors.append("Client name is required.")
        if strict_business_rules and not supplied_status:
            errors.append("Matter status is required.")
        if practice_area is None:
            errors.append("Practice area is required.")
        elif strict_business_rules and _catalog_key(practice_area) not in allowed_practice_areas:
            errors.append(
                "Practice area is invalid. Use a template reference value or an active "
                "workspace practice-area team."
            )
        if forum_level is None:
            errors.append("Forum level is required.")
        if filing_date_error:
            errors.append(filing_date_error)
        if not _valid_phone(client_contact_number):
            errors.append("Client contact number must contain 7 to 20 digits.")
        if owner_email and owner_membership is None:
            errors.append("Matter owner must match an active user in this company.")
        if responsible_lawyer_email and responsible_membership is None:
            errors.append("Responsible lawyer must match an active user in this company.")
        if team_slug and team is None:
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

        if matter_status in {"disposed", "closed"}:
            errors.append(
                "A matter cannot be imported in a disposed state; use the "
                "audited lifecycle workflow after creation."
            )

        if title and matter_code and practice_area and forum_level:
            try:
                MatterCreateRequest.model_validate(
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
            "high_court",
            "Delhi High Court",
            "CS(COMM) 123/2026",
            "FILING-123/2026",
            "2026-07-17",
            "owner@example.com",
            "commercial-litigation",
            "lawyer@example.com",
        ]
    )
    return buffer.getvalue().encode("utf-8")


def _matter_template_xlsx_bytes() -> bytes:
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
            "high_court",
            "Delhi High Court",
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
    forums = ["lower_court", "high_court", "supreme_court", "tribunal", "arbitration", "advisory"]
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
            "Matter Title, Matter Code, Client Name, Matter Status, Practice Area, Forum",
        ],
        ["Dates", "Use YYYY-MM-DD. DD/MM/YYYY and native Excel dates are also accepted."],
        [
            "People",
            "Matter Owner and Responsible Lawyer must be active work-email "
            "addresses in this company.",
        ],
        ["Teams", "Assigned Team must be an active team name or slug in this company."],
        [
            "Duplicates",
            "Matter Code, Case Number, and matching Matter Title + Client Name are checked.",
        ],
        ["Import", "Upload this file, review every validation error, then confirm import."],
        ["Security", "Formula cells and values beginning with =, +, -, or @ are rejected."],
        [
            "Limits",
            f"Maximum {MATTER_IMPORT_MAX_ROWS} data rows and "
            f"{MATTER_IMPORT_MAPPING_MAX_BYTES // (1024 * 1024)} MB.",
        ],
    ]
    validations = (
        '<dataValidations count="3">'
        '<dataValidation type="list" allowBlank="0" sqref="E2:E501">'
        "<formula1>'Reference Values'!$A$2:$A$4</formula1></dataValidation>"
        '<dataValidation type="list" allowBlank="0" sqref="M2:M501">'
        "<formula1>'Reference Values'!$B$2:$B$7</formula1></dataValidation>"
        '<dataValidation type="list" allowBlank="0" sqref="D2:D501">'
        "<formula1>'Reference Values'!$C$2:$C$16</formula1></dataValidation>"
        "</dataValidations>"
    )
    worksheets = [
        _worksheet_xml(import_rows, freeze_header=True, data_validations=validations),
        _worksheet_xml(reference_rows, freeze_header=True),
        _worksheet_xml(instruction_rows, freeze_header=True),
    ]
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Matter Import" sheetId="1" r:id="rId1"/>'
        '<sheet name="Reference Values" sheetId="2" r:id="rId2"/>'
        '<sheet name="Instructions" sheetId="3" r:id="rId3"/></sheets></workbook>'
    )
    workbook_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            '<Relationship '
            f'Id="rId{index}" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, 4)
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
            for index in range(1, 4)
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


def matter_import_template(format_value: Literal["csv", "xlsx"]) -> tuple[bytes, str, str]:
    if format_value == "xlsx":
        return (
            _matter_template_xlsx_bytes(),
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
            logger.exception(
                "Unexpected matter import row failure (job_id=%s, row_number=%s)",
                job_id,
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
