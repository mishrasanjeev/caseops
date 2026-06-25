from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from caseops_api.db.models import (
    AccountSetupToken,
    CompanyMembership,
    EmployeeBulkImportJob,
    EmployeeBulkImportRow,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import employee_imports as employee_import_service
from caseops_api.services.employee_imports import (
    EMPLOYEE_IMPORT_MAX_BYTES,
    EMPLOYEE_IMPORT_MAX_ROWS,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers
from tests.test_legalworkspace_employee_admin import (
    _audit_actions,
    _bootstrap,
    _create_employee,
)


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "Name",
            "Email",
            "Role",
            "Mobile",
            "Designation",
            "Department",
            "EmployeeCode",
            "ManagerEmail",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _xlsx_with_formula_cell() -> bytes:
    headers = [
        "Name",
        "Email",
        "Role",
        "Mobile",
        "Designation",
        "Department",
        "EmployeeCode",
        "ManagerEmail",
    ]

    def inline_cell(ref: str, value: str) -> str:
        escaped = (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        return f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>'

    header_cells = "".join(
        inline_cell(f"{chr(64 + index)}1", value)
        for index, value in enumerate(headers, start=1)
    )
    row_cells = "".join(
        [
            inline_cell("A2", "Formula XLSX"),
            inline_cell("B2", "xlsx-formula@bulk.example"),
            inline_cell("C2", "member"),
            '<c r="D2"><f>1+2</f><v>3</v></c>',
        ]
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{header_cells}</row><row r="2">{row_cells}</row></sheetData>'
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


def _preview(
    client: TestClient,
    token: str,
    *,
    filename: str,
    content: bytes,
    content_type: str = "text/csv",
):
    return client.post(
        "/api/companies/current/employees/imports/preview",
        headers=auth_headers(token),
        files={"file": (filename, content, content_type)},
    )


def test_employee_import_template_downloads_csv_and_xlsx(client: TestClient) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-template",
        email="owner@bulk-template.example",
    )
    token = str(boot["access_token"])

    csv_response = client.get(
        "/api/companies/current/employees/import-template?format=csv",
        headers=auth_headers(token),
    )
    assert csv_response.status_code == 200, csv_response.text
    assert "text/csv" in csv_response.headers["content-type"]
    assert "caseops-employee-import-template.csv" in csv_response.headers[
        "content-disposition"
    ]
    assert "Name,Email,Role" in csv_response.text

    xlsx_response = client.get(
        "/api/companies/current/employees/import-template?format=xlsx",
        headers=auth_headers(token),
    )
    assert xlsx_response.status_code == 200, xlsx_response.text
    assert xlsx_response.content.startswith(b"PK")
    assert "caseops-employee-import-template.xlsx" in xlsx_response.headers[
        "content-disposition"
    ]


def test_employee_import_preview_validates_rows_and_refuses_invalid_commit(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-validation",
        email="owner@bulk-validation.example",
    )
    token = str(boot["access_token"])
    manager = _create_employee(
        client,
        token,
        email="manager@bulk-validation.example",
        full_name="Import Manager",
        role="member",
    )
    content = _csv_bytes(
        [
            {
                "Name": "",
                "Email": "missing-name@bulk-validation.example",
                "Role": "member",
            },
            {
                "Name": "Formula User",
                "Email": "formula@bulk-validation.example",
                "Role": "member",
                "Mobile": "=HYPERLINK(\"https://evil.example\")",
            },
            {
                "Name": "Duplicate One",
                "Email": "dupe@bulk-validation.example",
                "Role": "viewer",
            },
            {
                "Name": "Duplicate Two",
                "Email": "dupe@bulk-validation.example",
                "Role": "member",
            },
            {
                "Name": "Bad Role",
                "Email": "bad-role@bulk-validation.example",
                "Role": "owner",
            },
            {
                "Name": "Existing Owner",
                "Email": "owner@bulk-validation.example",
                "Role": "member",
            },
            {
                "Name": "Bad Manager",
                "Email": "bad-manager@bulk-validation.example",
                "Role": "member",
                "ManagerEmail": "missing-manager@bulk-validation.example",
            },
            {
                "Name": "Valid Ref",
                "Email": "valid-ref@bulk-validation.example",
                "Role": "member",
                "ManagerEmail": str(manager["employee"]["email"]),
            },
        ]
    )

    preview = _preview(
        client,
        token,
        filename="employees.csv",
        content=content,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total_rows"] == 8
    assert body["valid_rows"] == 1
    assert body["invalid_rows"] == 7
    errors_by_email = {
        row["normalized"].get("email"): " ".join(row["errors"])
        for row in body["rows"]
    }
    assert "Name is required." in errors_by_email[
        "missing-name@bulk-validation.example"
    ]
    assert "Unsafe formula-like cell" in errors_by_email[
        "formula@bulk-validation.example"
    ]
    formula_row = next(
        row
        for row in body["rows"]
        if row["normalized"].get("email") == "formula@bulk-validation.example"
    )
    assert formula_row["raw"]["Mobile"] == "[unsafe formula removed]"
    assert formula_row["normalized"]["mobile"] is None
    assert "HYPERLINK" not in json.dumps(body)
    assert "Duplicate email in this import file." in errors_by_email[
        "dupe@bulk-validation.example"
    ]
    assert "Role must be one of" in errors_by_email[
        "bad-role@bulk-validation.example"
    ]
    assert "Email already belongs to this company." in errors_by_email[
        "owner@bulk-validation.example"
    ]
    assert "ManagerEmail must match" in errors_by_email[
        "bad-manager@bulk-validation.example"
    ]

    commit = client.post(
        f"/api/companies/current/employees/imports/{body['id']}/commit",
        headers=auth_headers(token),
    )
    assert commit.status_code == 400, commit.text

    factory = get_session_factory()
    with factory() as session:
        job = session.scalar(
            select(EmployeeBulkImportJob).where(EmployeeBulkImportJob.id == body["id"])
        )
        assert job is not None
        assert job.company_id == boot["company"]["id"]
        rows = list(
            session.scalars(
                select(EmployeeBulkImportRow).where(
                    EmployeeBulkImportRow.job_id == body["id"]
                )
            )
        )
        assert len(rows) == 8
        assert all(row.company_id == boot["company"]["id"] for row in rows)

    actions = [event.action for event in _audit_actions(str(boot["company"]["id"]))]
    assert "employee.import.previewed" in actions
    assert "employee.import.row_failed" in actions


def test_employee_import_rejects_all_formula_like_csv_prefixes(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-formula-prefixes",
        email="owner@bulk-formula-prefixes.example",
    )
    token = str(boot["access_token"])

    preview = _preview(
        client,
        token,
        filename="employees.csv",
        content=_csv_bytes(
            [
                {
                    "Name": "Plus Formula",
                    "Email": "plus@bulk-formula.example",
                    "Role": "member",
                    "Mobile": "+1+2",
                },
                {
                    "Name": "Minus Formula",
                    "Email": "minus@bulk-formula.example",
                    "Role": "member",
                    "Designation": "-1+2",
                },
                {
                    "Name": "Whitespace Formula",
                    "Email": "space@bulk-formula.example",
                    "Role": "member",
                    "Department": "   =HYPERLINK(\"https://evil.example\")",
                },
                {
                    "Name": "At Formula",
                    "Email": "at@bulk-formula.example",
                    "Role": "member",
                    "EmployeeCode": "@SUM(A1:A2)",
                },
            ]
        ),
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["valid_rows"] == 0
    assert body["invalid_rows"] == 4
    assert all(
        "Unsafe formula-like cell values are not allowed." in row["errors"]
        for row in body["rows"]
    )
    assert "+1+2" not in json.dumps(body)
    assert "-1+2" not in json.dumps(body)
    assert "HYPERLINK" not in json.dumps(body)
    assert "@SUM" not in json.dumps(body)


def test_employee_import_rejects_xlsx_formula_cells_with_cached_values(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-xlsx-formula",
        email="owner@bulk-xlsx-formula.example",
    )
    token = str(boot["access_token"])

    preview = _preview(
        client,
        token,
        filename="employees.xlsx",
        content=_xlsx_with_formula_cell(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["valid_rows"] == 0
    assert body["invalid_rows"] == 1
    row = body["rows"][0]
    assert "Unsafe formula-like cell values are not allowed." in row["errors"]
    assert row["raw"]["Mobile"] == "[unsafe formula removed]"
    assert row["normalized"]["mobile"] is None


def test_employee_import_rejects_xlsx_xml_entities(client: TestClient) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-xlsx-entity",
        email="owner@bulk-xlsx-entity.example",
    )
    token = str(boot["access_token"])

    preview = _preview(
        client,
        token,
        filename="employees.xlsx",
        content=_xlsx_with_external_entity(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert preview.status_code == 400, preview.text
    assert preview.json()["detail"] == "XLSX import file could not be read."


def test_employee_import_preview_does_not_leak_cross_tenant_email_existence(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(
        client,
        slug="bulk-email-a",
        email="owner@bulk-email-a.example",
    )
    token_a = str(boot_a["access_token"])
    _bootstrap(
        client,
        slug="bulk-email-b",
        email="owner@bulk-email-b.example",
    )

    preview = _preview(
        client,
        token_a,
        filename="employees.csv",
        content=_csv_bytes(
            [
                {
                    "Name": "Other Tenant Existing",
                    "Email": "owner@bulk-email-b.example",
                    "Role": "member",
                }
            ]
        ),
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["valid_rows"] == 1
    assert body["invalid_rows"] == 0
    assert "An account with this email already exists." not in json.dumps(body)


def test_employee_import_commit_does_not_oracle_cross_tenant_email_existence(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(
        client,
        slug="bulk-email-commit-a",
        email="owner@bulk-email-commit-a.example",
    )
    token_a = str(boot_a["access_token"])
    _bootstrap(
        client,
        slug="bulk-email-commit-b",
        email="owner@bulk-email-commit-b.example",
    )

    outcomes: list[dict[str, object]] = []
    for full_name, email in (
        ("Other Tenant Existing", "owner@bulk-email-commit-b.example"),
        ("Truly New Employee", "new@bulk-email-commit.example"),
    ):
        preview = _preview(
            client,
            token_a,
            filename="employees.csv",
            content=_csv_bytes(
                [
                    {
                        "Name": full_name,
                        "Email": email,
                        "Role": "member",
                    }
                ]
            ),
        )
        assert preview.status_code == 200, preview.text
        job = preview.json()
        assert job["valid_rows"] == 1
        assert job["invalid_rows"] == 0

        commit = client.post(
            f"/api/companies/current/employees/imports/{job['id']}/commit",
            headers=auth_headers(token_a),
        )
        assert commit.status_code == 200, commit.text
        body = commit.json()
        outcomes.append(body)
        assert body["job"]["status"] == "committed"
        assert body["job"]["created_count"] == 1
        assert body["created_employees"][0]["employee"]["email"] == email
        assert body["created_employees"][0]["setup"]["debug_token"]

    assert [outcome["job"]["created_count"] for outcome in outcomes] == [1, 1]


def test_employee_import_preview_still_rejects_current_tenant_duplicate_email(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-email-current-duplicate",
        email="owner@bulk-email-current-duplicate.example",
    )
    token = str(boot["access_token"])

    preview = _preview(
        client,
        token,
        filename="employees.csv",
        content=_csv_bytes(
            [
                {
                    "Name": "Existing Owner",
                    "Email": "owner@bulk-email-current-duplicate.example",
                    "Role": "member",
                }
            ]
        ),
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["valid_rows"] == 0
    assert body["invalid_rows"] == 1
    assert "Email already belongs to this company." in body["rows"][0]["errors"]

    commit = client.post(
        f"/api/companies/current/employees/imports/{body['id']}/commit",
        headers=auth_headers(token),
    )
    assert commit.status_code == 400, commit.text


def test_employee_import_commit_creates_employees_with_setup_tokens_and_audits(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-commit",
        email="owner@bulk-commit.example",
    )
    token = str(boot["access_token"])
    manager = _create_employee(
        client,
        token,
        email="manager@bulk-commit.example",
        full_name="Bulk Manager",
    )
    content = _csv_bytes(
        [
            {
                "Name": "Asha Bulk",
                "Email": "asha.bulk@example.com",
                "Role": "member",
                "Mobile": "919876543210",
                "Designation": "Associate",
                "Department": "Litigation",
                "EmployeeCode": "BULK-001",
                "ManagerEmail": str(manager["employee"]["email"]),
            },
            {
                "Name": "Dev Bulk",
                "Email": "dev.bulk@example.com",
                "Role": "viewer",
                "Department": "Finance",
                "EmployeeCode": "BULK-002",
            },
        ]
    )

    preview = _preview(
        client,
        token,
        filename="employees.csv",
        content=content,
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["valid_rows"] == 2
    assert job["invalid_rows"] == 0

    commit = client.post(
        f"/api/companies/current/employees/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert commit.status_code == 200, commit.text
    committed = commit.json()
    assert committed["job"]["status"] == "committed"
    assert committed["job"]["created_count"] == 2
    assert len(committed["created_employees"]) == 2
    assert all(row["setup"]["debug_token"] for row in committed["created_employees"])
    serialized = json.dumps(committed).lower()
    assert "password_hash" not in serialized
    assert "raw_password" not in serialized

    listing = client.get(
        "/api/companies/current/employees?q=bulk",
        headers=auth_headers(token),
    )
    assert listing.status_code == 200, listing.text
    emails = {row["email"] for row in listing.json()["employees"]}
    assert {"asha.bulk@example.com", "dev.bulk@example.com"} <= emails

    factory = get_session_factory()
    with factory() as session:
        token_hashes = list(session.scalars(select(AccountSetupToken.token_hash)))
        for created in committed["created_employees"]:
            assert created["setup"]["debug_token"] not in token_hashes
        created_rows = list(
            session.scalars(
                select(EmployeeBulkImportRow).where(
                    EmployeeBulkImportRow.job_id == job["id"],
                    EmployeeBulkImportRow.status == "created",
                )
            )
        )
        assert len(created_rows) == 2

    actions = [event.action for event in _audit_actions(str(boot["company"]["id"]))]
    assert "employee.import.previewed" in actions
    assert "employee.import.committed" in actions
    assert actions.count("employee.created") >= 2
    assert actions.count("employee.setup_token.created") >= 2


def test_employee_import_commit_claims_job_before_create_loop(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-double-commit",
        email="owner@bulk-double-commit.example",
    )
    token = str(boot["access_token"])
    preview = _preview(
        client,
        token,
        filename="employees.csv",
        content=_csv_bytes(
            [
                {
                    "Name": "Double Commit",
                    "Email": "double@bulk-double.example",
                    "Role": "member",
                }
            ]
        ),
    )
    assert preview.status_code == 200, preview.text
    job_id = preview.json()["id"]

    original_create = employee_import_service._create_employee_without_commit
    nested_statuses: list[int] = []

    def create_with_nested_commit(*args, **kwargs):
        if not nested_statuses:
            nested_statuses.append(-1)
            factory = get_session_factory()
            with factory() as nested_session:
                membership = nested_session.scalar(
                    select(CompanyMembership)
                    .options(
                        joinedload(CompanyMembership.company),
                        joinedload(CompanyMembership.user),
                    )
                    .where(CompanyMembership.id == boot["membership"]["id"])
                )
                assert membership is not None
                nested_context = SessionContext(
                    company=membership.company,
                    user=membership.user,
                    membership=membership,
                )
                try:
                    employee_import_service.commit_employee_import(
                        nested_session,
                        context=nested_context,
                        job_id=job_id,
                    )
                except HTTPException as exc:
                    nested_statuses[0] = exc.status_code
                else:
                    nested_statuses[0] = 200
        return original_create(*args, **kwargs)

    monkeypatch.setattr(
        employee_import_service,
        "_create_employee_without_commit",
        create_with_nested_commit,
    )

    commit = client.post(
        f"/api/companies/current/employees/imports/{job_id}/commit",
        headers=auth_headers(token),
    )
    assert commit.status_code == 200, commit.text
    assert nested_statuses == [400]

    factory = get_session_factory()
    with factory() as session:
        memberships = list(
            session.scalars(
                select(CompanyMembership)
                .join(User, User.id == CompanyMembership.user_id)
                .where(User.email == "double@bulk-double.example")
            )
        )
        assert len(memberships) == 1


def test_employee_import_commit_rejects_expired_preview_job(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-expired",
        email="owner@bulk-expired.example",
    )
    token = str(boot["access_token"])
    preview = _preview(
        client,
        token,
        filename="employees.csv",
        content=_csv_bytes(
            [
                {
                    "Name": "Expired Import",
                    "Email": "expired-import@bulk.example",
                    "Role": "member",
                }
            ]
        ),
    )
    assert preview.status_code == 200, preview.text
    job_id = preview.json()["id"]

    factory = get_session_factory()
    with factory() as session:
        job = session.scalar(
            select(EmployeeBulkImportJob).where(EmployeeBulkImportJob.id == job_id)
        )
        assert job is not None
        job.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()

    commit = client.post(
        f"/api/companies/current/employees/imports/{job_id}/commit",
        headers=auth_headers(token),
    )
    assert commit.status_code == 400, commit.text
    assert "expired" in commit.text.lower()

    listing = client.get(
        "/api/companies/current/employees?q=expired-import",
        headers=auth_headers(token),
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["employees"] == []


def test_employee_import_cancel_and_tenant_scope(client: TestClient) -> None:
    boot_a = _bootstrap(
        client,
        slug="bulk-cancel-a",
        email="owner@bulk-cancel-a.example",
    )
    token_a = str(boot_a["access_token"])
    boot_b = _bootstrap(
        client,
        slug="bulk-cancel-b",
        email="owner@bulk-cancel-b.example",
    )
    token_b = str(boot_b["access_token"])
    preview = _preview(
        client,
        token_a,
        filename="employees.csv",
        content=_csv_bytes(
            [
                {
                    "Name": "Cancel User",
                    "Email": "cancel@bulk.example",
                    "Role": "member",
                }
            ]
        ),
    )
    assert preview.status_code == 200, preview.text
    job_id = preview.json()["id"]

    cross_commit = client.post(
        f"/api/companies/current/employees/imports/{job_id}/commit",
        headers=auth_headers(token_b),
    )
    assert cross_commit.status_code == 404
    cross_cancel = client.post(
        f"/api/companies/current/employees/imports/{job_id}/cancel",
        headers=auth_headers(token_b),
    )
    assert cross_cancel.status_code == 404

    cancel = client.post(
        f"/api/companies/current/employees/imports/{job_id}/cancel",
        headers=auth_headers(token_a),
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    commit_cancelled = client.post(
        f"/api/companies/current/employees/imports/{job_id}/commit",
        headers=auth_headers(token_a),
    )
    assert commit_cancelled.status_code == 400

    actions = [event.action for event in _audit_actions(str(boot_a["company"]["id"]))]
    assert "employee.import.cancelled" in actions


def test_employee_import_rejects_unsupported_oversized_and_too_many_rows(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-limits",
        email="owner@bulk-limits.example",
    )
    token = str(boot["access_token"])

    unsupported = _preview(
        client,
        token,
        filename="employees.txt",
        content=b"Name,Email,Role\nText,text@example.com,member\n",
        content_type="text/plain",
    )
    assert unsupported.status_code == 400

    oversized = _preview(
        client,
        token,
        filename="employees.csv",
        content=b"x" * (EMPLOYEE_IMPORT_MAX_BYTES + 1),
        content_type="text/csv",
    )
    assert oversized.status_code == 400

    max_rows = _csv_bytes(
        [
            {
                "Name": f"Bulk Row {index}",
                "Email": f"bulk-row-{index}@limits.example",
                "Role": "member",
            }
            for index in range(EMPLOYEE_IMPORT_MAX_ROWS)
        ]
    )
    max_preview = _preview(
        client,
        token,
        filename="employees.csv",
        content=max_rows,
        content_type="text/csv",
    )
    assert max_preview.status_code == 200, max_preview.text
    assert max_preview.json()["total_rows"] == EMPLOYEE_IMPORT_MAX_ROWS

    too_many = _csv_bytes(
        [
            {
                "Name": f"Too Many {index}",
                "Email": f"too-many-{index}@limits.example",
                "Role": "member",
            }
            for index in range(EMPLOYEE_IMPORT_MAX_ROWS + 1)
        ]
    )
    too_many_response = _preview(
        client,
        token,
        filename="employees.csv",
        content=too_many,
        content_type="text/csv",
    )
    assert too_many_response.status_code == 400


def test_employee_import_mutations_require_company_user_management(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="bulk-role-guard",
        email="owner@bulk-role-guard.example",
    )
    owner_token = str(boot["access_token"])
    member = _create_employee(
        client,
        owner_token,
        email="member@bulk-role-guard.example",
        full_name="Guarded Member",
    )
    setup = client.post(
        "/api/auth/account-setup/complete",
        json={
            "token": member["setup"]["debug_token"],
            "password": "BulkMember123!",
        },
    )
    assert setup.status_code == 200, setup.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "member@bulk-role-guard.example",
            "password": "BulkMember123!",
            "company_slug": "bulk-role-guard",
        },
    )
    assert login.status_code == 200, login.text
    member_token = login.json()["access_token"]

    preview = _preview(
        client,
        member_token,
        filename="employees.csv",
        content=_csv_bytes(
            [
                {
                    "Name": "Blocked Import",
                    "Email": "blocked-import@example.com",
                    "Role": "member",
                }
            ]
        ),
    )
    assert preview.status_code == 403

    events = _audit_actions(str(boot["company"]["id"]))
    assert all(event.action != "employee.import.previewed" for event in events)
