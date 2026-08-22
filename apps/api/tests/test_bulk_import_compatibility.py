"""IPLF-032B neutral read adapters over canonical import owners."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    BulkImportJob,
    EmployeeBulkImportJob,
    EmployeeBulkImportRow,
    MatterBulkImportJob,
    MatterBulkImportRow,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company

PASSWORD = "FoundersPass123!"


def _bootstrap(client: TestClient, *, slug: str, email: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} Legal LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug} Owner",
            "owner_email": email,
            "owner_password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_jobs(company_id: str, membership_id: str) -> dict[str, str]:
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        ip_job = BulkImportJob(
            company_id=company_id,
            domain="ip_trademark",
            filename="portfolio.csv",
            source_sha256="a" * 64,
            status="committed_with_errors",
            total_rows=3,
            valid_rows=2,
            invalid_rows=1,
            committed_rows=1,
            failed_rows=1,
            created_by_membership_id=membership_id,
            creator_label_snapshot="Import Owner",
            committed_at=now,
        )
        matter_job = MatterBulkImportJob(
            company_id=company_id,
            created_by_membership_id=membership_id,
            filename="matters.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            manifest_format="xlsx",
            file_size_bytes=2048,
            source_sha256="b" * 64,
            status="completed_with_errors",
            total_rows=4,
            valid_rows=3,
            invalid_rows=1,
            duplicate_rows=1,
            created_count=2,
            failed_count=1,
            validation_error_count=1,
            imported_at=now,
            expires_at=now + timedelta(hours=24),
        )
        employee_job = EmployeeBulkImportJob(
            company_id=company_id,
            created_by_membership_id=membership_id,
            filename="employees.csv",
            content_type="text/csv",
            file_size_bytes=512,
            status="committed",
            total_rows=2,
            valid_rows=1,
            invalid_rows=1,
            created_count=1,
            failed_count=1,
            committed_at=now,
            expires_at=now + timedelta(hours=24),
        )
        session.add_all([ip_job, matter_job, employee_job])
        session.flush()
        session.add(
            MatterBulkImportRow(
                company_id=company_id,
                job_id=matter_job.id,
                row_number=2,
                raw_json={},
                normalized_json={},
                errors_json=["Missing court"],
                status="invalid",
            )
        )
        session.add(
            EmployeeBulkImportRow(
                company_id=company_id,
                job_id=employee_job.id,
                row_number=2,
                raw_json={},
                normalized_json={},
                errors_json=["Invalid email"],
                status="invalid",
            )
        )
        session.commit()
        return {"ip": ip_job.id, "matter": matter_job.id, "employee": employee_job.id}


def test_iplf032b_surfaces_all_import_owners_without_rewriting_history(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    ids = _seed_jobs(company_id, membership_id)

    response = client.get("/api/imports/history", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accessible_domains"] == ["ip_trademark", "matter", "employee"]
    jobs = {job["domain"]: job for job in body["jobs"]}
    assert set(jobs) == {"ip_trademark", "matter", "employee"}
    assert jobs["ip_trademark"]["source_owner"] == "bulk_import_jobs"
    assert jobs["ip_trademark"]["read_only_adapter"] is False
    assert jobs["matter"]["source_owner"] == "matter_bulk_import_jobs"
    assert jobs["matter"]["source_status"] == "completed_with_errors"
    assert jobs["matter"]["status"] == "committed_with_errors"
    assert jobs["employee"]["source_owner"] == "employee_bulk_import_jobs"
    assert jobs["employee"]["source_status"] == "committed"
    assert jobs["employee"]["status"] == "committed_with_errors"

    employee_manifest = client.get(
        f"/api/imports/employee/{ids['employee']}/manifest",
        headers=auth_headers(token),
    )
    assert employee_manifest.status_code == 200, employee_manifest.text
    manifest = employee_manifest.json()
    assert manifest["schema_version"] == "bulk-import-manifest-v1"
    assert manifest["compatibility_mode"] == "read_only_adapter"
    assert manifest["job"]["id"] == ids["employee"]
    assert manifest["job"]["source_sha256"] is None
    assert manifest["limitations"] == [
        "Legacy employee jobs did not persist an input checksum."
    ]

    errors = client.get(
        f"/api/imports/matter/{ids['matter']}/errors",
        headers=auth_headers(token),
    )
    assert errors.status_code == 200, errors.text
    assert errors.headers["cache-control"] == "private, no-store"
    rows = list(csv.DictReader(io.StringIO(errors.content.decode("utf-8-sig"))))
    assert rows == [
        {
            "row_number": "2",
            "status": "invalid",
            "errors": '["Missing court"]',
            "created_record_id": "",
        }
    ]

    with get_session_factory()() as session:
        assert session.get(MatterBulkImportJob, ids["matter"]).status == "completed_with_errors"
        assert session.get(EmployeeBulkImportJob, ids["employee"]).status == "committed"


def test_iplf032b_filters_domains_by_capability_and_fails_closed(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    create = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Portfolio Reader",
            "email": "reader@asterlegal.in",
            "password": "ReaderPass123!",
            "role": "member",
        },
    )
    assert create.status_code == 200, create.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "reader@asterlegal.in",
            "password": "ReaderPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    headers = auth_headers(str(login.json()["access_token"]))

    history = client.get("/api/imports/history", headers=headers)
    assert history.status_code == 200, history.text
    assert "employee" not in history.json()["accessible_domains"]
    forbidden = client.get("/api/imports/history?domain=employee", headers=headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Missing capability: company:manage_users"


def test_iplf032b_legacy_adapters_are_tenant_isolated(client: TestClient) -> None:
    first = _bootstrap(client, slug="adapter-a", email="owner@adapter-a.example")
    second = _bootstrap(client, slug="adapter-b", email="owner@adapter-b.example")
    ids = _seed_jobs(
        str(first["company"]["id"]),
        str(first["membership"]["id"]),
    )
    second_headers = auth_headers(str(second["access_token"]))

    for suffix in ("", "/manifest", "/errors"):
        response = client.get(
            f"/api/imports/matter/{ids['matter']}{suffix}",
            headers=second_headers,
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Import job not found."
