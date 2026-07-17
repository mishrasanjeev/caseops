from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape

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
        assert b"Matter Title" in workbook.read("xl/worksheets/sheet1.xml")

    csv_body = (
        b"Matter Title,Matter Code,Matter Type,Practice Area,Matter Status,"
        b"Matter Description,Client Name,Client Code,Client Contact Number,"
        b"Client Email,Opposing Party Name,Opposing Counsel,Forum,Court,"
        b"Case Number,Filing Number,Filing Date,Matter Owner,Responsible Lawyer\n"
        b"Acme recovery proceedings,BULK-2026-001,Litigation,Commercial,active,"
        b"Recovery of unpaid invoices,Acme Industries,CLI-001,+919876543210,"
        b"legal@acme.com,Northstar Supplies,Rao Chambers,high_court,"
        b"Delhi High Court,CS-COMM-123-2026,FILING-123,2026-07-17,"
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
    assert record["case_number"] == "CS-COMM-123-2026"
    assert record["filing_number"] == "FILING-123"
    assert record["filing_date"] == "2026-07-17"
    assert record["assignee_membership_id"] == boot["membership"]["id"]
    assert record["responsible_lawyer_membership_id"] == boot["membership"]["id"]

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
    assert "Client name is required." in errors
    assert any("Practice area is invalid" in error for error in errors)
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
    assert "Client name is required." in report_text


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
        "Duplicate case number" in error
        for error in duplicate_preview.json()["rows"][0]["errors"]
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


def test_bulk_matter_creation_strict_xlsx_validation_and_formula_sanitization(
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
            ["Missing status", "XLSX-CREATE-2", "Civil", "", "Acme", "high_court", "9876543210"],
            ["Unsafe phone", "XLSX-CREATE-3", "Civil", "active", "Acme", "high_court", "=2+2"],
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
    assert (job["valid_rows"], job["invalid_rows"]) == (1, 2)
    assert "Matter status is required." in job["rows"][1]["errors"]
    assert "Unsafe formula-like cell values are not allowed." in job["rows"][2]["errors"]

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
        next(
            row["created_matter_id"]
            for row in result["job"]["rows"]
            if row["row_number"] == 3
        ),
    }
    with get_session_factory()() as session:
        recover_one_count = session.scalar(
            select(func.count()).select_from(Matter).where(Matter.matter_code == "RECOVER-1")
        )
        assert recover_one_count == 1
