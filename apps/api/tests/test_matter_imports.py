from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from xml.sax.saxutils import escape

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuditEvent,
    DocumentProcessingJob,
    Matter,
    MatterAttachment,
    MatterBulkImportJob,
    MatterBulkImportRow,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.matter_imports import (
    MATTER_IMPORT_TEMPLATE_HEADERS,
    MATTER_IMPORT_XLSX_MAX_METADATA_BYTES,
    MATTER_IMPORT_XLSX_MAX_SHARED_STRING_CHARS,
    MATTER_IMPORT_XLSX_MAX_SHARED_STRINGS,
    ElementTree,
    _business_match_key,
    _normalise_forum_level,
    _parse_import_date,
    _safe_csv_cell,
    _unsafe_import_cell,
    _valid_phone,
    parse_matter_import_mapping,
)
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str, title: str | None = None) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": title or f"Bulk import matter {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _invite_user(
    client: TestClient,
    owner_token: str,
    *,
    email: str,
    role: str,
) -> tuple[str, str]:
    create = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": f"Import {role}",
            "email": email,
            "role": role,
            "password": "ImportPass123!",
        },
    )
    assert create.status_code == 200, create.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": email,
            "password": "ImportPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return str(create.json()["membership_id"]), str(login.json()["access_token"])


def _bootstrap_company(client: TestClient, *, slug: str, email: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} Legal",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Import Owner",
            "owner_email": email,
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _counts() -> tuple[int, int, int]:
    factory = get_session_factory()
    with factory() as session:
        matters = session.scalar(select(func.count()).select_from(Matter)) or 0
        attachments = session.scalar(select(func.count()).select_from(MatterAttachment)) or 0
        jobs = session.scalar(select(func.count()).select_from(DocumentProcessingJob)) or 0
    return matters, attachments, jobs


def _audit_metadata(company_id: str) -> dict[str, object]:
    factory = get_session_factory()
    with factory() as session:
        event = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "matter.bulk_import.dry_run",
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        )
        assert event is not None
        return json.loads(event.metadata_json or "{}")


def _csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _xlsx_worksheet_xml(rows: list[list[str]]) -> str:
    sheet_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for col_index, value in enumerate(row, start=1):
            col = ""
            index = col_index
            while index:
                index, rem = divmod(index - 1, 26)
                col = chr(65 + rem) + col
            cells.append(
                f'<c r="{col}{row_index}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )


def _xlsx_workbook_bytes(
    sheets: list[tuple[str, list[list[str]]]],
    *,
    date_1904: bool = False,
) -> bytes:
    worksheets = [_xlsx_worksheet_xml(rows) for _name, rows in sheets]
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        + ('<workbookPr date1904="1"/>' if date_1904 else "")
        + "<sheets>"
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, (name, _rows) in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        + "</Relationships>"
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
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        + "</Types>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for index, worksheet in enumerate(worksheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet)
    return buffer.getvalue()


def _xlsx_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    return _xlsx_workbook_bytes([("Matters", [headers, *rows])])


def _replace_xlsx_xml(content: bytes, entry_name: str, old: str, new: str) -> bytes:
    source = io.BytesIO(content)
    output = io.BytesIO()
    with (
        zipfile.ZipFile(source) as source_archive,
        zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as output_archive,
    ):
        for entry in source_archive.infolist():
            payload = source_archive.read(entry.filename)
            if entry.filename == entry_name:
                text = payload.decode("utf-8")
                assert old in text
                payload = text.replace(old, new, 1).encode("utf-8")
            output_archive.writestr(entry, payload)
    return output.getvalue()


def _with_xlsx_entry(content: bytes, entry_name: str, payload: str) -> bytes:
    source = io.BytesIO(content)
    output = io.BytesIO()
    found = False
    with (
        zipfile.ZipFile(source) as source_archive,
        zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as output_archive,
    ):
        for entry in source_archive.infolist():
            if entry.filename == entry_name:
                output_archive.writestr(entry, payload.encode("utf-8"))
                found = True
            else:
                output_archive.writestr(entry, source_archive.read(entry.filename))
        if not found:
            output_archive.writestr(entry_name, payload.encode("utf-8"))
    return output.getvalue()


def _xlsx_with_external_entity() -> bytes:
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE worksheet [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1">'
        '<c r="A1" t="inlineStr"><is><t>&xxe;</t></is></c>'
        "</row></sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return buffer.getvalue()


def _zip_bytes(names: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, b"dry-run placeholder")
    return buffer.getvalue()


def test_import_date_rejects_out_of_range_excel_serial_without_overflow() -> None:
    value, error = _parse_import_date("9" * 10_000)

    assert value is None
    assert error is not None


def test_import_date_accepts_common_unambiguous_business_formats() -> None:
    for value in (
        "2026-07-17",
        "2026/07/17",
        "2026.07.17",
        "2026-07-17T10:30:00+05:30",
        "17/07/2026",
        "17-07-2026",
        "17.07.2026",
        "17/07/26",
        "17-07-26",
        "17.07.26",
        "17 Jul 2026",
        "17-Jul-2026",
        "17 July 2026",
        "17-July-2026",
        "46220",
        "46220.5",
    ):
        parsed, error = _parse_import_date(value)

        assert parsed == date(2026, 7, 17)
        assert error is None


@pytest.mark.parametrize(
    "value",
    ("HIGH COURT", "High Court", "high court", "High court"),
)
def test_forum_normalization_accepts_every_source_report_case_variant(
    value: str,
) -> None:
    assert _normalise_forum_level(value) == "high_court"


def test_csv_parser_accepts_excel_encodings_delimiters_and_title_rows() -> None:
    headers = ["Matter Title", "Matter Code", "Practice Area", "Forum"]
    values = ["M/s. Café & Co. (Claim #7)", "CSV-COMPAT-7", "Civil & Commercial", "High Court"]
    cases = (
        (",", "utf-8-sig"),
        (";", "utf-16"),
        ("\t", "cp1252"),
        ("|", "utf-8"),
    )

    for delimiter, encoding in cases:
        text = "\n".join(
            (
                "Client matter register export",
                delimiter.join(headers),
                delimiter.join(values),
            )
        )
        parsed = parse_matter_import_mapping(
            filename="client-register.csv",
            content_type="text/csv",
            content=text.encode(encoding),
        )

        assert len(parsed.rows) == 1
        assert parsed.rows[0].row_number == 3
        assert parsed.rows[0].raw["Matter Title"] == values[0]
        assert parsed.rows[0].raw["Matter Code"] == "CSV-COMPAT-7"


def test_csv_parser_preserves_physical_start_lines_for_multiline_records() -> None:
    content = _csv_bytes(
        ["Matter Title", "Matter Code", "Practice Area", "Forum"],
        [
            ["First line\ncontinued title", "CSV-MULTILINE-1", "Civil", "High Court"],
            ["Second record", "CSV-MULTILINE-2", "Civil", "High Court"],
        ],
    )

    parsed = parse_matter_import_mapping(
        filename="multiline.csv",
        content_type="text/csv",
        content=content,
    )

    assert [row.row_number for row in parsed.rows] == [2, 4]


def test_csv_parser_marks_formula_like_selected_headers_unsafe() -> None:
    content = (
        b"=Matter Title,Matter Code,Practice Area,Forum\n"
        b"Header formula,CSV-HEADER-FORMULA,Civil,High Court\n"
    )

    parsed = parse_matter_import_mapping(
        filename="formula-header.csv",
        content_type="text/csv",
        content=content,
    )

    assert parsed.rows[0].unsafe_headers == frozenset({"=Matter Title"})


def test_csv_parser_returns_400_for_oversized_fields_instead_of_server_error() -> None:
    oversized_title = "A" * 140_000
    content = (
        "Matter Title,Matter Code,Practice Area,Forum\n"
        f"{oversized_title},CSV-LARGE-1,Civil,High Court\n"
    ).encode()

    with pytest.raises(HTTPException) as exc_info:
        parse_matter_import_mapping(
            filename="oversized-field.csv",
            content_type="text/csv",
            content=content,
        )

    assert exc_info.value.status_code == 400
    assert "parsed safely" in str(exc_info.value.detail)


def test_xlsx_parser_propagates_formula_flags_from_headers_and_unmapped_cells() -> None:
    headers = ["Matter Title", "Matter Code", "Practice Area", "Forum"]
    values = ["Formula header row", "XLSX-FORMULA-HEADER", "Civil", "High Court"]
    base = _xlsx_bytes(headers, [values])
    formula_like_header = _replace_xlsx_xml(
        base,
        "xl/worksheets/sheet1.xml",
        '<c r="A1" t="inlineStr"><is><t>Matter Title</t></is></c>',
        '<c r="A1" t="inlineStr"><is><t>=Matter Title</t></is></c>',
    )
    parsed_formula_like_header = parse_matter_import_mapping(
        filename="formula-like-header.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=formula_like_header,
    )
    assert parsed_formula_like_header.rows[0].unsafe_headers == frozenset(
        {"=Matter Title"}
    )

    formula_header = _replace_xlsx_xml(
        base,
        "xl/worksheets/sheet1.xml",
        '<c r="A1" t="inlineStr"><is><t>Matter Title</t></is></c>',
        '<c r="A1" t="str"><f>&quot;Matter Title&quot;</f><v>Matter Title</v></c>',
    )
    parsed_header = parse_matter_import_mapping(
        filename="formula-header.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=formula_header,
    )
    assert parsed_header.rows[0].unsafe_headers == frozenset({"Matter Title"})

    orphan_base = _xlsx_bytes(
        [*headers, ""],
        [["Orphan formula row", "XLSX-FORMULA-ORPHAN", "Civil", "High Court", "2"]],
    )
    orphan_formula = _replace_xlsx_xml(
        orphan_base,
        "xl/worksheets/sheet1.xml",
        '<c r="E2" t="inlineStr"><is><t>2</t></is></c>',
        '<c r="E2"><f>1+1</f><v>2</v></c>',
    )
    parsed_orphan = parse_matter_import_mapping(
        filename="formula-orphan.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=orphan_formula,
    )
    assert parsed_orphan.rows[0].unsafe_headers == frozenset({"Unmapped Column 5"})


def test_xlsx_parser_rejects_extreme_cell_references_and_zip_expansion() -> None:
    base = _xlsx_bytes(
        ["Matter Title", "Matter Code", "Practice Area", "Forum"],
        [["Bounded workbook", "XLSX-BOUNDED-1", "Civil", "High Court"]],
    )
    boundary_reference = _replace_xlsx_xml(
        base,
        "xl/worksheets/sheet1.xml",
        "</row></sheetData>",
        '<c r="XFD2" t="inlineStr"><is><t>boundary</t></is></c></row></sheetData>',
    )
    parsed_boundary = parse_matter_import_mapping(
        filename="boundary-reference.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=boundary_reference,
    )
    assert parsed_boundary.rows[0].raw["Matter Code"] == "XLSX-BOUNDED-1"

    extreme_reference = _replace_xlsx_xml(
        base,
        "xl/worksheets/sheet1.xml",
        'r="A2"',
        'r="XFE2"',
    )
    with pytest.raises(HTTPException) as ref_error:
        parse_matter_import_mapping(
            filename="extreme-reference.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=extreme_reference,
        )
    assert ref_error.value.status_code == 400
    assert "column beyond" in str(ref_error.value.detail)

    duplicate_row = _replace_xlsx_xml(
        base,
        "xl/worksheets/sheet1.xml",
        '<row r="2">',
        '<row r="2"></row><row r="2">',
    )
    with pytest.raises(HTTPException) as duplicate_error:
        parse_matter_import_mapping(
            filename="duplicate-row.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=duplicate_row,
        )
    assert duplicate_error.value.status_code == 400
    assert "duplicate row" in str(duplicate_error.value.detail).lower()

    excessive_row = _replace_xlsx_xml(
        base,
        "xl/worksheets/sheet1.xml",
        '<row r="2">',
        '<row r="1048577">',
    )
    with pytest.raises(HTTPException) as row_error:
        parse_matter_import_mapping(
            filename="excessive-row.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=excessive_row,
        )
    assert row_error.value.status_code == 400
    assert "Excel safety limit" in str(row_error.value.detail)

    huge_cell_row = _replace_xlsx_xml(
        base,
        "xl/worksheets/sheet1.xml",
        'r="A2"',
        f'r="A{"9" * 5000}"',
    )
    with pytest.raises(HTTPException) as huge_cell_error:
        parse_matter_import_mapping(
            filename="huge-cell-row-reference.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=huge_cell_row,
        )
    assert huge_cell_error.value.status_code == 400
    assert "row beyond" in str(huge_cell_error.value.detail)

    huge_row = _replace_xlsx_xml(
        base,
        "xl/worksheets/sheet1.xml",
        '<row r="2">',
        f'<row r="{"9" * 5000}">',
    )
    with pytest.raises(HTTPException) as huge_row_error:
        parse_matter_import_mapping(
            filename="huge-row-reference.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=huge_row,
        )
    assert huge_row_error.value.status_code == 400
    assert "Excel safety limit" in str(huge_row_error.value.detail)

    huge_sheet_number = _with_xlsx_entry(
        base,
        f"xl/worksheets/sheet{'9' * 5000}.xml",
        (
            '<worksheet xmlns="'
            'http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData/></worksheet>"
        ),
    )
    parsed_huge_sheet_number = parse_matter_import_mapping(
        filename="huge-sheet-number.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=huge_sheet_number,
    )
    assert parsed_huge_sheet_number.rows[0].raw["Matter Code"] == "XLSX-BOUNDED-1"

    expanded = io.BytesIO()
    with zipfile.ZipFile(expanded, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        with zipfile.ZipFile(io.BytesIO(base)) as source:
            for entry in source.infolist():
                archive.writestr(entry, source.read(entry.filename))
        archive.writestr("xl/sharedStrings.xml", b"0" * (17 * 1024 * 1024))
    expanded_content = expanded.getvalue()
    assert len(expanded_content) < 2 * 1024 * 1024
    with pytest.raises(HTTPException) as archive_error:
        parse_matter_import_mapping(
            filename="expanded.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=expanded_content,
        )
    assert archive_error.value.status_code == 400
    assert "oversized archive entry" in str(archive_error.value.detail)

    unsupported_compression = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(base)) as source,
        zipfile.ZipFile(unsupported_compression, "w") as target,
    ):
        for entry in source.infolist():
            target.writestr(
                entry.filename,
                source.read(entry.filename),
                compress_type=zipfile.ZIP_BZIP2,
            )
    with pytest.raises(HTTPException) as compression_error:
        parse_matter_import_mapping(
            filename="unsupported-compression.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=unsupported_compression.getvalue(),
        )
    assert compression_error.value.status_code == 400
    assert "unsupported ZIP compression" in str(compression_error.value.detail)


def test_xlsx_parser_stops_streaming_after_the_bounded_row_buffer() -> None:
    headers = ["Matter Title", "Matter Code", "Practice Area", "Forum"]
    rows = [
        [f"Bounded row {index}", f"XLSX-STREAM-{index}", "Civil", "High Court"]
        for index in range(1, 1001)
    ]
    malformed_after_limit = _replace_xlsx_xml(
        _xlsx_bytes(headers, rows),
        "xl/worksheets/sheet1.xml",
        "</sheetData></worksheet>",
        "<malformed-tail",
    )

    with pytest.raises(HTTPException) as exc_info:
        parse_matter_import_mapping(
            filename="bounded-stream.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=malformed_after_limit,
        )

    assert exc_info.value.status_code == 400
    assert "at most 500 rows" in str(exc_info.value.detail)


def test_xlsx_parser_streams_shared_strings_without_materializing_the_xml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = ["Matter Title", "Matter Code", "Practice Area", "Forum"]
    workbook = _replace_xlsx_xml(
        _xlsx_bytes(
            headers,
            [["Shared title", "XLSX-SHARED-1", "Civil", "High Court"]],
        ),
        "xl/worksheets/sheet1.xml",
        '<c r="A1" t="inlineStr"><is><t>Matter Title</t></is></c>',
        '<c r="A1" t="s"><v>0</v></c>',
    )
    workbook = _with_xlsx_entry(
        workbook,
        "xl/sharedStrings.xml",
        (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><r><t>Matter </t></r><r><t>Title</t></r></si>"
            "</sst>"
        ),
    )
    original_fromstring = ElementTree.fromstring

    def reject_shared_string_dom(content: bytes) -> ElementTree.Element:
        assert b"<sst " not in content
        return original_fromstring(content)

    monkeypatch.setattr(
        ElementTree,
        "fromstring",
        reject_shared_string_dom,
    )

    parsed = parse_matter_import_mapping(
        filename="shared-strings.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=workbook,
    )

    assert parsed.rows[0].raw["Matter Title"] == "Shared title"


@pytest.mark.parametrize(
    ("entry_name", "closing_tag", "expected_detail"),
    (
        ("xl/workbook.xml", "</workbook>", "workbook metadata"),
        (
            "xl/_rels/workbook.xml.rels",
            "</Relationships>",
            "workbook relationship metadata",
        ),
    ),
)
def test_xlsx_parser_caps_workbook_metadata_entries(
    entry_name: str,
    closing_tag: str,
    expected_detail: str,
) -> None:
    base = _xlsx_bytes(
        ["Matter Title", "Matter Code", "Practice Area", "Forum"],
        [["Metadata bounds", "XLSX-METADATA-1", "Civil", "High Court"]],
    )
    oversized = _replace_xlsx_xml(
        base,
        entry_name,
        closing_tag,
        f"<!--{'x' * (MATTER_IMPORT_XLSX_MAX_METADATA_BYTES + 1)}-->{closing_tag}",
    )

    with pytest.raises(HTTPException) as exc_info:
        parse_matter_import_mapping(
            filename="oversized-metadata.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=oversized,
        )

    assert exc_info.value.status_code == 400
    assert expected_detail in str(exc_info.value.detail)


def test_xlsx_parser_caps_shared_string_count_and_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _xlsx_bytes(
        ["Matter Title", "Matter Code", "Practice Area", "Forum"],
        [["Shared bounds", "XLSX-SHARED-BOUNDS", "Civil", "High Court"]],
    )
    oversized_text = _with_xlsx_entry(
        base,
        "xl/sharedStrings.xml",
        (
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<si><t>{'x' * (MATTER_IMPORT_XLSX_MAX_SHARED_STRING_CHARS + 1)}</t></si>"
            "</sst>"
        ),
    )
    with pytest.raises(HTTPException) as text_error:
        parse_matter_import_mapping(
            filename="oversized-shared-string.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=oversized_text,
        )
    assert "oversized shared string" in str(text_error.value.detail)

    excessive_count = _with_xlsx_entry(
        base,
        "xl/sharedStrings.xml",
        (
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(
                f"<si><t>{index}</t></si>"
                for index in range(MATTER_IMPORT_XLSX_MAX_SHARED_STRINGS + 1)
            )
            + "</sst>"
        ),
    )
    with pytest.raises(HTTPException) as count_error:
        parse_matter_import_mapping(
            filename="too-many-shared-strings.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=excessive_count,
        )
    assert "too many shared strings" in str(count_error.value.detail)

    monkeypatch.setattr(
        "caseops_api.services.matter_imports.MATTER_IMPORT_XLSX_MAX_SHARED_TEXT_CHARS",
        5,
    )
    excessive_total_text = _with_xlsx_entry(
        base,
        "xl/sharedStrings.xml",
        (
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<si><t>one</t></si><si><t>two</t></si>"
            "</sst>"
        ),
    )
    with pytest.raises(HTTPException) as total_text_error:
        parse_matter_import_mapping(
            filename="too-much-shared-string-text.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=excessive_total_text,
        )
    assert "shared-string text exceeds" in str(total_text_error.value.detail)


def test_xlsx_parser_respects_the_workbook_1904_date_system() -> None:
    workbook = _xlsx_workbook_bytes(
        [
            (
                "Matters",
                [
                    ["Matter Title", "Matter Code", "Practice Area", "Forum", "Filing Date"],
                    [
                        "1904 workbook date",
                        "XLSX-DATE-1904",
                        "Civil",
                        "High Court",
                        "44758.75",
                    ],
                ],
            )
        ],
        date_1904=True,
    )

    parsed = parse_matter_import_mapping(
        filename="date-1904.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=workbook,
    )

    assert parsed.rows[0].raw["Filing Date"] == "2026-07-17"


def test_client_phone_formula_exception_requires_one_leading_plus() -> None:
    assert _valid_phone("+91 (98765) 432-10")
    assert _valid_phone("+91 98765 43210 ext. 42")
    assert not _valid_phone("91+98765+43210")
    assert not _valid_phone("+91+98765+43210")
    assert not _valid_phone("+x1234567")
    assert not _valid_phone("+ext1234567")
    assert not _valid_phone("+1 ext. 234567")
    assert _valid_phone("+1234567&1")
    assert _valid_phone("+1234567/1")
    assert not _unsafe_import_cell("Client Contact Number", "+91 (98765) 432-10")
    assert _unsafe_import_cell("Client Contact Number", "+91+98765+43210")
    assert _unsafe_import_cell("Client Contact Number", "+x1234567")
    assert _unsafe_import_cell("Client Contact Number", "+1234567&1")
    assert _unsafe_import_cell("Client Contact Number", "+1234567/1")


def test_business_match_keys_preserve_meaningful_plus_and_hash_symbols() -> None:
    assert _business_match_key("Banking & Finance") == _business_match_key(
        "Banking and Finance"
    )
    assert len(
        {
            _business_match_key("C++"),
            _business_match_key("C#"),
            _business_match_key("C / + #"),
        }
    ) == 3
    assert _business_match_key("R\u00e9f\u00e9r\u00e9") != _business_match_key("Refere")
    assert _business_match_key(
        "\u0935\u093e\u0923\u093f\u091c\u094d\u092f"
    ) != _business_match_key("\u5546\u696d")


def test_error_report_cells_neutralize_spreadsheet_formula_prefixes() -> None:
    for value in ("=1+1", "+cmd", "-2+3", "@SUM(A1:A2)", "  =HYPERLINK(\"x\")"):
        assert _safe_csv_cell(value).lstrip().startswith("'")
    assert _safe_csv_cell("Safe matter title") == "Safe matter title"


def test_bulk_matter_import_csv_dry_run_returns_plan_without_writes(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    before = _counts()
    csv_body = (
        b"MatterCode,Title,ClientName,PracticeArea,ForumLevel,Status,"
        b"DocumentFilenames,DocumentCategory\n"
        b"ADP11-001,Cheque recovery import,Asha Traders,Commercial,"
        b"high_court,intake,notice.pdf; pleadings/plaint.pdf,pleadings\n"
    )

    response = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token),
        files={
            "mapping_file": ("matters.csv", csv_body, "text/csv"),
            "document_manifest": (
                "documents.txt",
                b"notice.pdf\npleadings/plaint.pdf\n",
                "text/plain",
            ),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["dry_run"] is True
    assert body["summary"]["commit_supported"] is False
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["will_create_matter_count"] == 0
    assert body["summary"]["will_create_attachment_count"] == 0
    assert body["summary"]["storage_writes"] == 0
    assert body["summary"]["corpus_jobs_queued"] == 0
    row = body["rows"][0]
    assert row["status"] == "valid"
    assert [ref["status"] for ref in row["document_references"]] == [
        "available",
        "available",
    ]
    assert _counts() == before
    metadata = _audit_metadata(company_id)
    assert metadata["total_rows"] == 1
    assert metadata["document_reference_count"] == 2
    redacted = json.dumps(metadata)
    assert "notice.pdf" not in redacted
    assert "Cheque recovery import" not in redacted


def test_bulk_matter_import_reports_invalid_rows_and_unsupported_documents(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    csv_body = (
        b"MatterCode,Title,PracticeArea,ForumLevel,Status,DocumentFilenames,"
        b"DocumentCategory\n"
        b"ADP11-BAD,,Civil,high_court,active,missing.pdf; ../outside.pdf,unknown\n"
        b"ADP11-BAD,Second Row,Civil,high_court,intake,available.pdf,orders\n"
    )

    response = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token),
        files={
            "mapping_file": ("matters.csv", csv_body, "text/csv"),
            "document_manifest": ("docs.txt", b"available.pdf\n", "text/plain"),
        },
    )

    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert rows[0]["status"] == "invalid"
    assert "Matter title is required." in rows[0]["errors"]
    assert "Document category is unsupported." in rows[0]["errors"]
    assert "Document filename reference is not present in the manifest." in rows[0]["errors"]
    assert "Document filename reference is invalid." in rows[0]["errors"]
    assert [ref["status"] for ref in rows[0]["document_references"]] == [
        "missing",
        "invalid",
    ]
    assert rows[1]["status"] == "invalid"
    assert "Duplicate matter code in this import file." in rows[1]["errors"]


def test_bulk_matter_import_omitted_or_explicit_active_status_is_valid(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    csv_body = (
        b"MatterCode,Title,PracticeArea,ForumLevel,Status\n"
        b"ADP11-DEFAULT,Default active,Civil,high_court,\n"
        b"ADP11-ACTIVE,Explicit active,Civil,high_court,active\n"
    )
    response = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token),
        files={"mapping_file": ("matters.csv", csv_body, "text/csv")},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert [(row["status"], row["matter_status"]) for row in rows] == [
        ("valid", "active"),
        ("valid", "active"),
    ]


def test_bulk_matter_import_rejects_terminal_status_bypass(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    csv_body = (
        b"MatterCode,Title,PracticeArea,ForumLevel,Status\n"
        b"ADP11-DISPOSED,Disposed bypass,Civil,high_court,disposed\n"
        b"ADP11-CLOSED,Legacy closed bypass,Civil,high_court,closed\n"
    )
    response = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token),
        files={"mapping_file": ("matters.csv", csv_body, "text/csv")},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    assert [row["status"] for row in rows] == ["invalid", "invalid"]
    assert all(
        any("cannot be imported in a disposed state" in error for error in row["errors"])
        for row in rows
    )


def test_bulk_matter_import_duplicate_detection_is_tenant_scoped(
    client: TestClient,
) -> None:
    tenant_a = _bootstrap_company(
        client,
        slug="adp11-tenant-a",
        email="owner-a@adp11.example",
    )
    token_a = str(tenant_a["access_token"])
    _create_matter(client, token_a, "ADP11-DUP", "Tenant A duplicate")
    tenant_b = _bootstrap_company(
        client,
        slug="adp11-tenant-b",
        email="owner-b@adp11.example",
    )
    token_b = str(tenant_b["access_token"])

    response_a = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token_a),
        files={
            "mapping_file": (
                "matters.json",
                json.dumps(
                    [
                        {
                            "matter_code": "ADP11-DUP",
                            "title": "Tenant A duplicate",
                            "practice_area": "Civil",
                            "forum_level": "high_court",
                        }
                    ]
                ).encode("utf-8"),
                "application/json",
            )
        },
    )
    response_b = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token_b),
        files={
            "mapping_file": (
                "matters.json",
                json.dumps(
                    [
                        {
                            "matter_code": "ADP11-DUP",
                            "title": "Tenant A duplicate",
                            "practice_area": "Civil",
                            "forum_level": "high_court",
                        }
                    ]
                ).encode("utf-8"),
                "application/json",
            )
        },
    )

    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text
    row_a = response_a.json()["rows"][0]
    row_b = response_b.json()["rows"][0]
    assert row_a["status"] == "invalid"
    assert row_a["duplicate_candidates"][0]["matter_code"] == "ADP11-DUP"
    assert row_b["status"] == "valid"
    assert row_b["duplicate_candidates"] == []


def test_bulk_matter_import_respects_ethical_wall_visibility(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    matter_id = _create_matter(client, owner_token, "ADP11-WALLED", "Walled duplicate")
    admin_mid, admin_token = _invite_user(
        client,
        owner_token,
        email="import-admin@asterlegal.in",
        role="admin",
    )
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": admin_mid, "reason": "Conflict."},
    )
    assert wall.status_code == 200, wall.text

    response = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(admin_token),
        files={
            "mapping_file": (
                "matters.json",
                json.dumps(
                    [
                        {
                            "matter_code": "ADP11-WALLED",
                            "title": "Walled duplicate",
                            "practice_area": "Civil",
                            "forum_level": "high_court",
                        }
                    ]
                ).encode("utf-8"),
                "application/json",
            )
        },
    )

    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["status"] == "valid"
    assert row["duplicate_candidates"] == []


def test_bulk_matter_import_accepts_xlsx_and_zip_filename_dry_run(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    xlsx = _xlsx_bytes(
        [
            "MatterCode",
            "Title",
            "PracticeArea",
            "ForumLevel",
            "DocumentFilenames",
            "DocumentCategory",
        ],
        [
            [
                "ADP11-XLSX",
                "XLSX dry run",
                "Civil",
                "tribunal",
                "bundle/order.pdf",
                "orders",
            ]
        ],
    )

    response = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token),
        files={
            "mapping_file": (
                "matters.xlsx",
                xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "document_archive": (
                "bundle.zip",
                _zip_bytes(["bundle/order.pdf"]),
                "application/zip",
            ),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["manifest_format"] == "xlsx"
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["available_document_count"] == 1
    assert body["rows"][0]["document_references"][0]["status"] == "available"


def test_bulk_matter_import_rejects_xlsx_xml_entities(client: TestClient) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])

    response = client.post(
        "/api/matters/imports/dry-run",
        headers=auth_headers(token),
        files={
            "mapping_file": (
                "matters.xlsx",
                _xlsx_with_external_entity(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "XLSX matter import file could not be read."


def test_bulk_matter_creation_template_preview_commit_history_and_notifications(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])

    xlsx_template = client.get(
        "/api/matters/imports/template?format=xlsx",
        headers=auth_headers(token),
    )
    assert xlsx_template.status_code == 200, xlsx_template.text
    assert xlsx_template.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    with zipfile.ZipFile(io.BytesIO(xlsx_template.content)) as workbook:
        assert {f"xl/worksheets/sheet{index}.xml" for index in range(1, 4)}.issubset(
            workbook.namelist()
        )
        import_sheet = workbook.read("xl/worksheets/sheet1.xml")
        assert b"Matter Title" in import_sheet
        assert b"Court Forum Number" in import_sheet

    csv_template = client.get(
        "/api/matters/imports/template?format=csv",
        headers=auth_headers(token),
    )
    assert csv_template.status_code == 200, csv_template.text
    template_headers = next(csv.reader(io.StringIO(csv_template.content.decode("utf-8-sig"))))
    assert "Court Forum Number" in template_headers
    assert template_headers.index("Court Forum Number") == template_headers.index("Court") + 1

    csv_body = (
        b"Matter Title,Matter Code,Matter Type,Practice Area,Matter Status,"
        b"Matter Description,Client Name,Client Code,Client Contact Number,"
        b"Client Email,Opposing Party Name,Opposing Counsel,Forum,Court,"
        b"Court Forum Number,Case Number,Filing Number,Filing Date,Matter Owner,"
        b"Responsible Lawyer\n"
        b"Acme recovery proceedings,BULK-2026-001,Litigation,Commercial,intake,"
        b"Recovery of unpaid invoices,Acme Industries,CLI-001,+919876543210,"
        b"legal@acme.com,Northstar Supplies,Rao Chambers,high_court,"
        b"Delhi High Court,Court / Forum #12-A,CS-COMM-123-2026,FILING-123,2026-07-17,"
        b"owner@asterlegal.in,owner@asterlegal.in\n"
    )
    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={"file": ("matters.csv", csv_body, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["status"] == "validated"
    assert job["valid_rows"] == 1
    assert job["invalid_rows"] == 0
    assert job["source_sha256"]
    normalized = job["rows"][0]["normalized"]
    assert normalized["client_code"] == "CLI-001"
    assert normalized["filing_date"] == "2026-07-17"
    assert normalized["court_forum_number"] == "Court / Forum #12-A"
    assert normalized["owner_membership_id"] == boot["membership"]["id"]

    committed = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert committed.status_code == 200, committed.text
    result = committed.json()
    assert result["job"]["status"] == "completed"
    assert result["job"]["created_count"] == 1
    assert result["job"]["failed_count"] == 0
    assert len(result["created_matter_ids"]) == 1

    matter = client.get(
        f"/api/matters/{result['created_matter_ids'][0]}",
        headers=auth_headers(token),
    )
    assert matter.status_code == 200, matter.text
    record = matter.json()
    assert record["matter_type"] == "Litigation"
    assert record["client_code"] == "CLI-001"
    assert record["client_contact_number"] == "+919876543210"
    assert record["client_email"] == "legal@acme.com"
    assert record["opposing_counsel"] == "Rao Chambers"
    assert record["court_forum_number"] == "Court / Forum #12-A"
    assert record["case_number"] == "CS-COMM-123-2026"
    assert record["filing_number"] == "FILING-123"
    assert record["filing_date"] == "2026-07-17"
    assert record["assignee_membership_id"] == boot["membership"]["id"]
    assert record["responsible_lawyer_membership_id"] == boot["membership"]["id"]
    assert record["status"] == "intake"

    activated = client.patch(
        f"/api/matters/{record['id']}",
        headers=auth_headers(token),
        json={
            "status": "active",
            "expected_updated_at": record["updated_at"],
        },
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"

    repeated = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["created_matter_ids"] == result["created_matter_ids"]

    history = client.get(
        "/api/matters/imports/history?q=matters.csv",
        headers=auth_headers(token),
    )
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    assert history.json()["imports"][0]["uploaded_by_email"] == "owner@asterlegal.in"
    assert history.json()["imports"][0]["rows"] == []

    factory = get_session_factory()
    with factory() as session:
        events = set(
            session.scalars(
                select(NotificationDeliveryIntent.event_type).where(
                    NotificationDeliveryIntent.source_id == job["id"]
                )
            )
        )
    assert "matter_import.upload_succeeded" in events
    assert "matter_import.completed" in events


def test_bulk_matter_creation_normalizes_business_values_and_preserves_punctuation(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    headers = [
        "Matter Title",
        "Matter Code",
        "Practice Area",
        "Matter Status",
        "Client Name",
        "Matter Description",
        "Opposing Party Name",
        "Opposing Counsel",
        "Forum",
        "Court",
        "Court Forum Number",
        "Case Number",
        "Filing Number",
    ]
    rows = [
        [
            "M/s. Rao & Co. v. A.B.C. Ltd. (Claim #42/2026)",
            "RELAXED-CASE-1",
            "Technology, Media & Telecommunications (TMT) / Data-Privacy",
            "  ACTIVE  ",
            "",
            "Invoices #42, #43 / FY 2025-26; terms (A) & (B).",
            "A.B.C. Industries Pvt. Ltd. / North Division",
            "D'Souza, Rao & Co. (Counsel)",
            "  HIGH COURT  ",
            "High Court of Delhi, Bench #3 (Commercial)",
            "Forum #12/A-3",
            "CS (COMM) 42/2026",
            "Filing #ABC/2026",
        ],
        [
            "Mixed-case status and forum",
            "RELAXED-CASE-2",
            "Banking & Finance",
            "On Hold",
            "Existing Client, Inc.",
            "",
            "",
            "",
            "Supreme Court",
            "",
            "",
            "",
            "",
        ],
        [
            "Default optional status and client",
            "RELAXED-CASE-3",
            "Emerging-Tech & AI",
            "",
            "",
            "",
            "",
            "",
            "District & Sessions Court",
            "",
            "",
            "",
            "",
        ],
        [
            "Mixed-case intake tribunal",
            "RELAXED-CASE-4",
            "Tax / Customs",
            "InTaKe",
            "",
            "",
            "",
            "",
            "TrIbUnAl",
            "",
            "",
            "",
            "",
        ],
    ]
    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={"file": ("relaxed-business-values.csv", _csv_bytes(headers, rows), "text/csv")},
    )

    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert (job["valid_rows"], job["invalid_rows"]) == (4, 0)
    normalized = [row["normalized"] for row in job["rows"]]
    assert [(row["matter_status"], row["forum_level"]) for row in normalized] == [
        ("active", "high_court"),
        ("on_hold", "supreme_court"),
        ("active", "lower_court"),
        ("intake", "tribunal"),
    ]
    assert normalized[0].get("client_name") is None
    assert (
        normalized[0]["practice_area"]
        == "Technology, Media & Telecommunications (TMT) / Data-Privacy"
    )
    assert normalized[0]["description"] == "Invoices #42, #43 / FY 2025-26; terms (A) & (B)."
    assert normalized[0]["court_forum_number"] == "Forum #12/A-3"

    committed = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert committed.status_code == 200, committed.text
    committed_job = committed.json()["job"]
    assert committed_job["status"] == "completed"
    assert committed_job["created_count"] == 4
    first_row = next(
        row for row in committed_job["rows"] if row["normalized"]["matter_code"] == "RELAXED-CASE-1"
    )
    matter = client.get(
        f"/api/matters/{first_row['created_matter_id']}",
        headers=auth_headers(token),
    )
    assert matter.status_code == 200, matter.text
    record = matter.json()
    assert record["title"] == "M/s. Rao & Co. v. A.B.C. Ltd. (Claim #42/2026)"
    assert record["client_name"] is None
    assert record["opposing_party"] == "A.B.C. Industries Pvt. Ltd. / North Division"
    assert record["opposing_counsel"] == "D'Souza, Rao & Co. (Counsel)"
    assert record["court_name"] == "High Court of Delhi, Bench #3 (Commercial)"
    assert record["court_forum_number"] == "Forum #12/A-3"
    assert record["case_number"] == "CS (COMM) 42/2026"
    assert record["filing_number"] == "Filing #ABC/2026"


def test_bulk_matter_creation_resolves_exact_team_names_and_rejects_ambiguous_aliases(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    request_headers = auth_headers(token)
    symbol_team = client.post(
        "/api/teams/",
        headers=request_headers,
        json={"name": "A&B", "slug": "a-symbol-b", "kind": "practice_area"},
    )
    word_team = client.post(
        "/api/teams/",
        headers=request_headers,
        json={"name": "A and B", "slug": "a-and-b", "kind": "practice_area"},
    )
    assert symbol_team.status_code in (200, 201), symbol_team.text
    assert word_team.status_code in (200, 201), word_team.text

    preview = client.post(
        "/api/matters/imports/preview",
        headers=request_headers,
        files={
            "file": (
                "team-name-collisions.csv",
                _csv_bytes(
                    [
                        "Matter Title",
                        "Matter Code",
                        "Practice Area",
                        "Forum",
                        "Assigned Team",
                    ],
                    [
                        ["Exact symbol team", "TEAM-EXACT-1", "Civil", "High Court", "A&B"],
                        [
                            "Exact word team",
                            "TEAM-EXACT-2",
                            "Civil",
                            "High Court",
                            "A and B",
                        ],
                        [
                            "Ambiguous equivalent team",
                            "TEAM-AMBIGUOUS-3",
                            "Civil",
                            "High Court",
                            "A & B",
                        ],
                    ],
                ),
                "text/csv",
            )
        },
    )

    assert preview.status_code == 200, preview.text
    rows = preview.json()["rows"]
    assert [
        (row["status"], row["normalized"].get("team_id")) for row in rows
    ] == [
        ("valid", symbol_team.json()["id"]),
        ("valid", word_team.json()["id"]),
        ("invalid", None),
    ]
    assert rows[2]["errors"] == [
        "Assigned team matches more than one active team; use an exact team name or slug."
    ]


def test_bulk_matter_creation_accepts_existing_client_xlsx_layout_and_aliases(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    xlsx = _xlsx_workbook_bytes(
        [
            ("Blank canonical template", [MATTER_IMPORT_TEMPLATE_HEADERS]),
            (
                "Instructions",
                [
                    ["Client matter register instructions"],
                    ["Upload the Matter Register worksheet without deleting title rows."],
                    ["Matter Status", "Forum"],
                ],
            ),
            (
                "Matter Register",
                [
                    ["Legacy Legal Matter Register"],
                    ["Generated by Client ERP v4.2 on 23/07/2026"],
                    [],
                    [
                        "Matter Name",
                        "Matter ID",
                        "Area of Practice",
                        "Current Status",
                        "Existing Client Name",
                        "Court / Forum",
                        "Client Phone No.",
                        "Date of Filing",
                        "Court / Forum No.",
                    ],
                    [
                        "M/s. Legacy & Co. / A.B.C. (Case #7)",
                        "LEGACY-CLIENT-7",
                        "Banking & Finance / FinTech",
                        "Active",
                        "M/s. Acme & Sons (India) Pvt. Ltd.",
                        "High Court",
                        "+91 (98765) 432-10",
                        "17.07.2026",
                        "Court #4 / Bench-A",
                    ],
                ],
            ),
        ]
    )
    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={
            "file": (
                "existing-client-register.xlsx",
                xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert (job["valid_rows"], job["invalid_rows"]) == (1, 0), job["rows"]
    row = job["rows"][0]
    assert row["row_number"] == 5
    assert row["normalized"]["matter_code"] == "LEGACY-CLIENT-7"
    assert row["normalized"]["practice_area"] == "Banking & Finance / FinTech"
    assert row["normalized"]["matter_status"] == "active"
    assert row["normalized"]["client_name"] == "M/s. Acme & Sons (India) Pvt. Ltd."
    assert row["normalized"]["forum_level"] == "high_court"
    assert row["normalized"]["client_contact_number"] == "+91 (98765) 432-10"
    assert row["normalized"]["filing_date"] == "2026-07-17"
    assert row["normalized"]["court_forum_number"] == "Court #4 / Bench-A"

    committed = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert committed.status_code == 200, committed.text
    matter_id = committed.json()["created_matter_ids"][0]
    matter = client.get(
        f"/api/matters/{matter_id}",
        headers=auth_headers(token),
    )
    assert matter.status_code == 200, matter.text
    record = matter.json()
    assert record["client_name"] == "M/s. Acme & Sons (India) Pvt. Ltd."
    assert record["client_contact_number"] == "+91 (98765) 432-10"
    assert record["filing_date"] == "2026-07-17"
    assert record["court_forum_number"] == "Court #4 / Bench-A"


def test_bulk_matter_creation_accepts_excel_semicolon_windows_1252_csv(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Client export generated on 23/07/2026"])
    writer.writerow(
        [
            "Matter Name",
            "Matter ID",
            "Area of Practice",
            "Current Status",
            "Existing Client Name",
            "Court / Forum",
            "Matter Description",
        ]
    )
    writer.writerow(
        [
            "M/s. Müller & Söhne – Claim #9/2026",
            "CP1252-CLIENT-9",
            "Commercial / Distribution",
            "ACTIVE",
            "",
            "High Court",
            "“Supply, services & support” – Schedule (A), clause #9.",
        ]
    )
    csv_body = buffer.getvalue().encode("cp1252")

    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={
            "file": (
                "client-export.csv",
                csv_body,
                "application/vnd.ms-excel",
            )
        },
    )

    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert (job["valid_rows"], job["invalid_rows"]) == (1, 0), job["rows"]
    row = job["rows"][0]
    assert row["row_number"] == 3
    assert row["normalized"]["title"] == "M/s. Müller & Söhne – Claim #9/2026"
    assert row["normalized"]["matter_status"] == "active"
    assert row["normalized"]["forum_level"] == "high_court"
    assert (
        row["normalized"]["description"]
        == "“Supply, services & support” – Schedule (A), clause #9."
    )


def test_bulk_matter_creation_partial_success_and_error_report(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    csv_body = (
        b"Matter Title,Matter Code,Practice Area,Matter Status,Client Name,Forum,Client Email\n"
        b"Valid bulk row,BULK-PARTIAL-1,Civil,active,Asha Rao,high_court,asha@example.com\n"
        b"Invalid bulk row,BULK-PARTIAL-2,Unknown Specialty,closed,,high_court,not-an-email\n"
    )
    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={"file": ("partial.csv", csv_body, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert (job["valid_rows"], job["invalid_rows"]) == (1, 1)
    errors = job["rows"][1]["errors"]
    assert "Client name is required." not in errors
    assert not any("Practice area is invalid" in error for error in errors)
    assert any("disposed state" in error for error in errors)
    assert any("email" in error.lower() for error in errors)

    committed = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert committed.status_code == 200, committed.text
    result = committed.json()["job"]
    assert result["status"] == "completed_with_errors"
    assert (result["created_count"], result["failed_count"]) == (1, 1)

    report = client.get(
        f"/api/matters/imports/{job['id']}/errors",
        headers=auth_headers(token),
    )
    assert report.status_code == 200, report.text
    report_text = report.content.decode("utf-8-sig")
    assert "Row Number,Matter Code,Matter Title,Status,Errors" in report_text
    assert "BULK-PARTIAL-2" in report_text
    assert "disposed state" in report_text


def test_bulk_matter_creation_detects_case_duplicates_and_commit_time_staleness(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    existing = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Existing case",
            "matter_code": "EXISTING-CASE",
            "client_name": "Existing Client",
            "practice_area": "Civil",
            "forum_level": "high_court",
            "status": "active",
            "case_number": "CASE-777",
        },
    )
    assert existing.status_code == 200, existing.text

    duplicate_create = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Duplicate direct create",
            "matter_code": "DIRECT-DUPLICATE-CASE",
            "client_name": "Other Client",
            "practice_area": "Civil",
            "forum_level": "high_court",
            "status": "active",
            "case_number": "case-777",
        },
    )
    assert duplicate_create.status_code == 409, duplicate_create.text

    update_target = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Duplicate update target",
            "matter_code": "UPDATE-DUPLICATE-CASE",
            "client_name": "Other Client",
            "practice_area": "Civil",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert update_target.status_code == 200, update_target.text
    update_duplicate = client.patch(
        f"/api/matters/{update_target.json()['id']}",
        headers=auth_headers(token),
        json={
            "case_number": "CASE-777",
            "expected_updated_at": update_target.json()["updated_at"],
        },
    )
    assert update_duplicate.status_code == 409, update_duplicate.text

    duplicate_preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={
            "file": (
                "duplicate.csv",
                b"Matter Title,Matter Code,Practice Area,Matter Status,Client Name,"
                b"Forum,Case Number\n"
                b"Different title,NEW-CODE,Civil,active,Another Client,high_court,case-777\n",
                "text/csv",
            )
        },
    )
    assert duplicate_preview.status_code == 200, duplicate_preview.text
    assert any(
        "Duplicate case number" in error for error in duplicate_preview.json()["rows"][0]["errors"]
    )

    fresh_preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={
            "file": (
                "stale.csv",
                b"Matter Title,Matter Code,Practice Area,Matter Status,Client Name,Forum\n"
                b"Stale preview,STALE-CODE,Civil,active,Stale Client,high_court\n",
                "text/csv",
            )
        },
    )
    assert fresh_preview.status_code == 200, fresh_preview.text
    stale_job = fresh_preview.json()
    _create_matter(client, token, "STALE-CODE", "Created after preview")
    stale_commit = client.post(
        f"/api/matters/imports/{stale_job['id']}/commit",
        headers=auth_headers(token),
    )
    assert stale_commit.status_code == 400, stale_commit.text
    with get_session_factory()() as session:
        persisted = session.get(MatterBulkImportJob, stale_job["id"])
        assert persisted is not None
        assert persisted.status == "completed_with_errors"


def test_bulk_matter_creation_permissions_custom_matter_manager_and_tenant_isolation(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    viewer_mid, viewer_token = _invite_user(
        client,
        owner_token,
        email="matter-manager@asterlegal.in",
        role="viewer",
    )
    denied = client.get(
        "/api/matters/imports/template?format=csv",
        headers=auth_headers(viewer_token),
    )
    assert denied.status_code == 403

    role = client.post(
        "/api/companies/current/roles",
        headers=auth_headers(owner_token),
        json={
            "name": "Matter Manager",
            "description": "May validate and commit matter imports only.",
            "base_role": "viewer",
            "permissions": ["matters:bulk_import"],
        },
    )
    assert role.status_code == 200, role.text
    assigned = client.post(
        f"/api/companies/current/employees/{viewer_mid}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": role.json()["id"]},
    )
    assert assigned.status_code == 200, assigned.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "matter-manager@asterlegal.in",
            "password": "ImportPass123!",
        },
    )
    assert login.status_code == 200, login.text
    manager_token = str(login.json()["access_token"])
    allowed = client.get(
        "/api/matters/imports/template?format=csv",
        headers=auth_headers(manager_token),
    )
    assert allowed.status_code == 200, allowed.text

    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(manager_token),
        files={
            "file": (
                "manager.csv",
                b"Matter Title,Matter Code,Practice Area,Matter Status,Client Name,Forum\n"
                b"Managed import,MANAGER-1,Civil,active,Manager Client,high_court\n",
                "text/csv",
            )
        },
    )
    assert preview.status_code == 200, preview.text

    tenant_b = _bootstrap_company(
        client,
        slug="bulk-import-tenant-b",
        email="owner@bulk-b.example",
    )
    tenant_b_token = str(tenant_b["access_token"])
    cross_tenant = client.get(
        f"/api/matters/imports/{preview.json()['id']}",
        headers=auth_headers(tenant_b_token),
    )
    assert cross_tenant.status_code == 404


def test_bulk_matter_creation_optional_status_keeps_security_and_code_rules_strict(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    xlsx = _xlsx_bytes(
        [
            "Matter Title",
            "Matter Code",
            "Practice Area",
            "Matter Status",
            "Client Name",
            "Forum",
            "Client Contact Number",
        ],
        [
            [
                "Valid workbook row",
                "XLSX-CREATE-1",
                "Civil",
                "active",
                "Acme",
                "high_court",
                "+919876543210",
            ],
            [
                "Optional status",
                "XLSX-CREATE-2",
                "Emerging-Tech & AI",
                "",
                "",
                "High Court",
                "9876543210",
            ],
            ["Unsafe phone", "XLSX-CREATE-3", "Civil", "active", "Acme", "high_court", "=2+2"],
            [
                "Unsafe matter code",
                "XLSX/CREATE#4",
                "Civil",
                "active",
                "Acme",
                "high_court",
                "9876543210",
            ],
        ],
    )
    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={
            "file": (
                "strict.xlsx",
                xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert (job["valid_rows"], job["invalid_rows"]) == (2, 2)
    assert job["rows"][1]["status"] == "valid"
    assert job["rows"][1]["normalized"]["matter_status"] == "active"
    assert job["rows"][1]["normalized"].get("client_name") is None
    assert "Unsafe formula-like cell values are not allowed." in job["rows"][2]["errors"]
    assert any("letters, numbers, and hyphens" in error for error in job["rows"][3]["errors"])

    with get_session_factory()() as session:
        unsafe_row = session.scalar(
            select(MatterBulkImportRow).where(
                MatterBulkImportRow.job_id == job["id"],
                MatterBulkImportRow.row_number == 4,
            )
        )
        assert unsafe_row is not None
        assert unsafe_row.raw_json["Client Contact Number"] == "[unsafe formula removed]"


def test_bulk_matter_creation_expiry_and_cancel_are_terminal(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])

    def preview(code: str) -> dict[str, object]:
        response = client.post(
            "/api/matters/imports/preview",
            headers=auth_headers(token),
            files={
                "file": (
                    f"{code}.csv",
                    (
                        "Matter Title,Matter Code,Practice Area,Matter Status,Client Name,Forum\n"
                        f"Terminal test,{code},Civil,active,Terminal Client,high_court\n"
                    ).encode(),
                    "text/csv",
                )
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    expired = preview("EXPIRED-IMPORT-1")
    with get_session_factory()() as session:
        job = session.get(MatterBulkImportJob, str(expired["id"]))
        assert job is not None
        job.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    expired_commit = client.post(
        f"/api/matters/imports/{expired['id']}/commit",
        headers=auth_headers(token),
    )
    assert expired_commit.status_code == 400
    expired_detail = client.get(
        f"/api/matters/imports/{expired['id']}",
        headers=auth_headers(token),
    ).json()
    assert expired_detail["status"] == "expired"

    cancelled = preview("CANCELLED-IMPORT-1")
    cancel = client.post(
        f"/api/matters/imports/{cancelled['id']}/cancel",
        headers=auth_headers(token),
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"
    cancelled_commit = client.post(
        f"/api/matters/imports/{cancelled['id']}/commit",
        headers=auth_headers(token),
    )
    assert cancelled_commit.status_code == 400


def test_bulk_matter_creation_recovers_stale_import_without_recreating_completed_rows(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    preview = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={
            "file": (
                "recover.csv",
                b"Matter Title,Matter Code,Practice Area,Matter Status,Client Name,Forum\n"
                b"Already committed,RECOVER-1,Civil,active,Recovery Client,high_court\n"
                b"Resume this row,RECOVER-2,Civil,active,Recovery Client,high_court\n",
                "text/csv",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    job_id = preview.json()["id"]
    existing_id = _create_matter(client, token, "RECOVER-1", "Already committed")

    with get_session_factory()() as session:
        job = session.get(MatterBulkImportJob, job_id)
        first_row = session.scalar(
            select(MatterBulkImportRow).where(
                MatterBulkImportRow.job_id == job_id,
                MatterBulkImportRow.row_number == 2,
            )
        )
        assert job is not None and first_row is not None
        job.status = "importing"
        job.updated_at = datetime.now(UTC) - timedelta(minutes=11)
        first_row.status = "created"
        first_row.created_matter_id = existing_id
        session.commit()

    resumed = client.post(
        f"/api/matters/imports/{job_id}/commit",
        headers=auth_headers(token),
    )
    assert resumed.status_code == 200, resumed.text
    result = resumed.json()
    assert result["job"]["status"] == "completed"
    assert result["job"]["created_count"] == 2
    assert set(result["created_matter_ids"]) == {
        existing_id,
        next(row["created_matter_id"] for row in result["job"]["rows"] if row["row_number"] == 3),
    }
    with get_session_factory()() as session:
        recover_one_count = session.scalar(
            select(func.count()).select_from(Matter).where(Matter.matter_code == "RECOVER-1")
        )
        assert recover_one_count == 1
