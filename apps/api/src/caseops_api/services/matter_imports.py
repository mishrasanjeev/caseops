from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal
from xml.etree import ElementTree

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuditResult, Matter, MatterStatus
from caseops_api.schemas.matter_imports import (
    BulkMatterImportDocumentReference,
    BulkMatterImportDryRunResponse,
    BulkMatterImportDryRunSummary,
    BulkMatterImportDuplicateCandidate,
    BulkMatterImportManifestFormat,
    BulkMatterImportRowPlan,
)
from caseops_api.schemas.matters import MatterCreateRequest
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import visible_matters_filter
from caseops_api.services.session_context import SessionContext

MATTER_IMPORT_MAPPING_MAX_BYTES = 2 * 1024 * 1024
MATTER_IMPORT_DOCUMENT_MANIFEST_MAX_BYTES = 512 * 1024
MATTER_IMPORT_DOCUMENT_ARCHIVE_MAX_BYTES = 10 * 1024 * 1024
MATTER_IMPORT_MAX_ROWS = 500
MATTER_IMPORT_MAX_DOCUMENT_REFERENCES = 2000

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
    "owner": "owner_email",
    "owneremail": "owner_email",
    "assignee": "owner_email",
    "team": "team_slug",
    "teamslug": "team_slug",
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
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
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
        select(Matter.id, Matter.matter_code, Matter.title, Matter.client_name)
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
        )
        for matter_id, matter_code, title, client_name in rows
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


def dry_run_bulk_matter_import(
    session: Session,
    *,
    context: SessionContext,
    parsed_import: ParsedMatterImport,
    available_document_filenames: list[str] | None = None,
) -> BulkMatterImportDryRunResponse:
    available_document_filenames = _bounded_document_names(available_document_filenames or [])
    available_document_keys = {_document_key(name) for name in available_document_filenames}
    canonical_rows: list[tuple[ParsedMatterImportRow, dict[str, str], bool]] = []
    for row in parsed_import.rows:
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

    existing_candidates = _visible_existing_matter_candidates(session, context=context)
    existing_by_code: dict[str, list[ExistingMatterCandidate]] = {}
    existing_by_title_client: dict[str, list[ExistingMatterCandidate]] = {}
    for candidate in existing_candidates:
        existing_by_code.setdefault(candidate.matter_code.lower(), []).append(candidate)
        existing_by_title_client.setdefault(
            _normalised_key(candidate.title, candidate.client_name),
            [],
        ).append(candidate)

    row_plans: list[BulkMatterImportRowPlan] = []
    for parsed, row, unsafe_formula in canonical_rows:
        errors: list[str] = []
        if unsafe_formula:
            errors.append("Unsafe formula-like cell values are not allowed.")

        title = row.get("title", "").strip() or None
        matter_code = row.get("matter_code", "").strip() or None
        client_name = row.get("client_name", "").strip() or None
        practice_area = row.get("practice_area", "").strip() or None
        matter_type = row.get("matter_type", "").strip() or None
        matter_status = row.get("status", "").strip() or MatterStatus.INTAKE.value
        forum_level = row.get("forum_level", "").strip() or None
        court_name = row.get("court_name", "").strip() or None
        owner_email = row.get("owner_email", "").strip() or None
        team_slug = row.get("team_slug", "").strip() or None
        category = _normalise_document_category(row.get("document_category"))

        if title is None:
            errors.append("Matter title is required.")
        if matter_code is None:
            errors.append("Matter code is required.")
        if practice_area is None:
            errors.append("Practice area is required.")
        if forum_level is None:
            errors.append("Forum level is required.")
        if category == "unsupported":
            errors.append("Document category is unsupported.")
            category = None
        if matter_status == MatterStatus.ACTIVE.value:
            errors.append(
                "Matter import dry-run cannot plan direct active-status creation."
            )

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

        if title and matter_code and practice_area and forum_level:
            try:
                MatterCreateRequest.model_validate(
                    {
                        "title": title,
                        "matter_code": matter_code,
                        "client_name": client_name,
                        "status": matter_status,
                        "practice_area": practice_area,
                        "forum_level": forum_level,
                        "court_name": court_name,
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
                client_name=client_name,
                practice_area=practice_area,
                matter_type=matter_type,
                matter_status=matter_status,
                forum_level=forum_level,
                court_name=court_name,
                owner_email=owner_email,
                team_slug=team_slug,
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


__all__ = [
    "MATTER_IMPORT_DOCUMENT_ARCHIVE_MAX_BYTES",
    "MATTER_IMPORT_DOCUMENT_MANIFEST_MAX_BYTES",
    "MATTER_IMPORT_MAPPING_MAX_BYTES",
    "dry_run_bulk_matter_import",
    "parse_matter_import_document_archive",
    "parse_matter_import_document_manifest",
    "parse_matter_import_mapping",
]
