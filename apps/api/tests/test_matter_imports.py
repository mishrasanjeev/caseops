from __future__ import annotations

import io
import json
import zipfile
from xml.sax.saxutils import escape

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import AuditEvent, DocumentProcessingJob, Matter, MatterAttachment
from caseops_api.db.session import get_session_factory
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


def _xlsx_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    sheet_rows: list[str] = []
    for row_index, row in enumerate([headers, *rows], start=1):
        cells: list[str] = []
        for col_index, value in enumerate(row, start=1):
            col = ""
            index = col_index
            while index:
                index, rem = divmod(index - 1, 26)
                col = chr(65 + rem) + col
            cells.append(
                f'<c r="{col}{row_index}" t="inlineStr"><is><t>'
                f"{escape(value)}"
                "</t></is></c>"
            )
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
        '<sheets><sheet name="Matters" sheetId="1" r:id="rId1"/></sheets></workbook>'
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


def _zip_bytes(names: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, b"dry-run placeholder")
    return buffer.getvalue()


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
    assert "Matter import dry-run cannot plan direct active-status creation." in rows[0]["errors"]
    assert [ref["status"] for ref in rows[0]["document_references"]] == [
        "missing",
        "invalid",
    ]
    assert rows[1]["status"] == "invalid"
    assert "Duplicate matter code in this import file." in rows[1]["errors"]


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
