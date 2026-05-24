from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    DocumentProcessingJob,
    MatterAttachment,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Drive import matter {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _bootstrap_company(
    client: TestClient,
    *,
    slug: str,
    email: str,
) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} Legal",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Drive Owner",
            "owner_email": email,
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


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
            "full_name": f"Drive {role}",
            "email": email,
            "role": role,
            "password": "DrivePass123!",
        },
    )
    assert create.status_code == 200, create.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": email,
            "password": "DrivePass123!",
        },
    )
    assert login.status_code == 200, login.text
    return str(create.json()["membership_id"]), str(login.json()["access_token"])


def _counts() -> tuple[int, int]:
    factory = get_session_factory()
    with factory() as session:
        attachments = session.scalar(select(func.count()).select_from(MatterAttachment)) or 0
        jobs = session.scalar(select(func.count()).select_from(DocumentProcessingJob)) or 0
    return attachments, jobs


def _latest_drive_audit_metadata(company_id: str) -> dict[str, object]:
    factory = get_session_factory()
    with factory() as session:
        event = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "matter.google_drive_import.dry_run",
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        )
        assert event is not None
        return json.loads(event.metadata_json or "{}")


@pytest.fixture
def drive_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_GOOGLE_DRIVE_CLIENT_ID", "drive-client-id")
    monkeypatch.setenv("CASEOPS_GOOGLE_DRIVE_CLIENT_SECRET", "drive-client-secret")
    monkeypatch.setenv(
        "CASEOPS_GOOGLE_DRIVE_REDIRECT_URI",
        "https://app.example/oauth/google-drive",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_provider_config_status_fails_closed_and_lists_names_only(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])

    response = client.get(
        "/api/matters/imports/drive/provider-config",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "google_drive"
    assert body["configured"] is False
    assert sorted(body["missing_config_names"]) == [
        "GOOGLE_DRIVE_CLIENT_ID",
        "GOOGLE_DRIVE_CLIENT_SECRET",
        "GOOGLE_DRIVE_REDIRECT_URI",
    ]
    # Names-only contract: the response carries env var NAMES, never values.
    # The literal name GOOGLE_DRIVE_CLIENT_SECRET is allowed; a value or any
    # OAuth bearer/refresh-token field name is not.
    for forbidden_key in ("access_token", "refresh_token", "bearer"):
        assert forbidden_key not in json.dumps(body).lower(), forbidden_key


def test_provider_config_status_reports_configured_when_all_set(
    client: TestClient,
    drive_configured: None,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])

    response = client.get(
        "/api/matters/imports/drive/provider-config",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["missing_config_names"] == []
    serialised = json.dumps(body)
    assert "drive-client-secret" not in serialised
    assert "drive-client-id" not in serialised


def test_drive_dry_run_happy_path_writes_no_attachments(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, "ADP12-HAPPY")
    before = _counts()

    payload = {
        "folder_id": "folder-123",
        "folder_name": "Matter ADP12 intake",
        "files": [
            {
                "provider_file_id": "drive-file-1",
                "name": "plaint.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 12_345,
                "modified_time": "2026-05-20T10:00:00Z",
                "parent_folder_id": "folder-123",
                "parent_folder_name": "Matter ADP12 intake",
            },
            {
                "provider_file_id": "drive-file-2",
                "name": "exhibit-a.png",
                "mime_type": "image/png",
                "size_bytes": 9_876,
            },
        ],
    }

    response = client.post(
        f"/api/matters/{matter_id}/imports/drive/dry-run",
        headers=auth_headers(token),
        json=payload,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["dry_run"] is True
    assert body["summary"]["commit_supported"] is False
    assert body["summary"]["total_files"] == 2
    assert body["summary"]["valid_files"] == 2
    assert body["summary"]["invalid_files"] == 0
    assert body["summary"]["duplicate_files"] == 0
    assert body["summary"]["unsupported_mime_files"] == 0
    assert body["summary"]["will_create_attachment_count"] == 0
    assert body["summary"]["storage_writes"] == 0
    assert body["summary"]["corpus_jobs_queued"] == 0

    categories = {file["name"]: file["category"] for file in body["files"]}
    assert categories["plaint.pdf"] == "pleadings"
    assert categories["exhibit-a.png"] == "evidence"
    statuses = {file["name"]: file["status"] for file in body["files"]}
    assert statuses == {"plaint.pdf": "valid", "exhibit-a.png": "valid"}

    assert _counts() == before
    metadata = _latest_drive_audit_metadata(company_id)
    assert metadata["provider"] == "google_drive"
    assert metadata["total_files"] == 2
    assert metadata["will_create_attachment_count"] == 0
    redacted = json.dumps(metadata)
    assert "plaint.pdf" not in redacted
    assert "drive-file-1" not in redacted
    assert "folder-123" not in redacted


def test_drive_dry_run_detects_duplicate_provider_file_ids(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "ADP12-DUP")

    payload = {
        "files": [
            {
                "provider_file_id": "drive-dup",
                "name": "order.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024,
            },
            {
                "provider_file_id": "drive-dup",
                "name": "order-copy.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 1024,
            },
        ],
    }

    response = client.post(
        f"/api/matters/{matter_id}/imports/drive/dry-run",
        headers=auth_headers(token),
        json=payload,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    statuses = [file["status"] for file in body["files"]]
    assert statuses == ["valid", "skipped_duplicate"]
    assert body["summary"]["duplicate_files"] == 1
    assert body["summary"]["valid_files"] == 1


def test_drive_dry_run_rejects_unsupported_mime_and_unsafe_filenames(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "ADP12-BAD")

    payload = {
        "files": [
            {
                "provider_file_id": "drive-bin",
                "name": "trojan.exe",
                "mime_type": "application/x-msdownload",
                "size_bytes": 256,
            },
            {
                "provider_file_id": "drive-traversal",
                "name": "../escape/leak.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 256,
            },
            {
                "provider_file_id": "drive-too-big",
                "name": "huge-pleadings.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 60 * 1024 * 1024,
            },
            {
                "provider_file_id": "drive-empty",
                "name": "empty.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 0,
            },
        ],
    }

    response = client.post(
        f"/api/matters/{matter_id}/imports/drive/dry-run",
        headers=auth_headers(token),
        json=payload,
    )

    assert response.status_code == 200, response.text
    files_by_id = {file["provider_file_id"]: file for file in response.json()["files"]}
    assert files_by_id["drive-bin"]["status"] == "unsupported_mime"
    assert files_by_id["drive-traversal"]["status"] == "invalid"
    assert any(
        "unsafe" in err.lower() or "traversal" in err.lower()
        for err in files_by_id["drive-traversal"]["errors"]
    )
    assert files_by_id["drive-too-big"]["status"] == "invalid"
    assert any(
        "limit" in err.lower() for err in files_by_id["drive-too-big"]["errors"]
    )
    assert files_by_id["drive-empty"]["status"] == "invalid"
    assert any("empty" in err.lower() for err in files_by_id["drive-empty"]["errors"])


def test_drive_dry_run_auto_categorization_is_deterministic(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "ADP12-CAT")

    payload = {
        "files": [
            {
                "provider_file_id": f"drive-{i}",
                "name": name,
                "mime_type": "application/pdf",
                "size_bytes": 1024,
            }
            for i, name in enumerate(
                [
                    "plaint draft.pdf",
                    "order_2024.pdf",
                    "exhibit-1.pdf",
                    "summons.pdf",
                    "lease agreement.pdf",
                    "letter to client.pdf",
                    "random-misc.pdf",
                ]
            )
        ],
    }

    first = client.post(
        f"/api/matters/{matter_id}/imports/drive/dry-run",
        headers=auth_headers(token),
        json=payload,
    )
    second = client.post(
        f"/api/matters/{matter_id}/imports/drive/dry-run",
        headers=auth_headers(token),
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    cats_first = {f["name"]: f["category"] for f in first.json()["files"]}
    cats_second = {f["name"]: f["category"] for f in second.json()["files"]}
    assert cats_first == cats_second
    assert cats_first == {
        "plaint draft.pdf": "pleadings",
        "order_2024.pdf": "orders",
        "exhibit-1.pdf": "evidence",
        "summons.pdf": "notices",
        "lease agreement.pdf": "contracts",
        "letter to client.pdf": "correspondence",
        "random-misc.pdf": "other",
    }


def test_drive_dry_run_enforces_tenant_isolation(client: TestClient) -> None:
    tenant_a = _bootstrap_company(
        client,
        slug="adp12-tenant-a",
        email="owner-a@adp12.example",
    )
    tenant_b = _bootstrap_company(
        client,
        slug="adp12-tenant-b",
        email="owner-b@adp12.example",
    )
    token_a = str(tenant_a["access_token"])
    token_b = str(tenant_b["access_token"])
    matter_a = _create_matter(client, token_a, "ADP12-ISO")

    response = client.post(
        f"/api/matters/{matter_a}/imports/drive/dry-run",
        headers=auth_headers(token_b),
        json={
            "files": [
                {
                    "provider_file_id": "drive-x",
                    "name": "plaint.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1024,
                }
            ],
        },
    )
    assert response.status_code == 404, response.text


def test_drive_dry_run_blocked_by_ethical_wall(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    matter_id = _create_matter(client, owner_token, "ADP12-WALL")
    admin_mid, admin_token = _invite_user(
        client,
        owner_token,
        email="drive-admin@asterlegal.in",
        role="admin",
    )
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": admin_mid, "reason": "Conflict."},
    )
    assert wall.status_code == 200, wall.text

    response = client.post(
        f"/api/matters/{matter_id}/imports/drive/dry-run",
        headers=auth_headers(admin_token),
        json={
            "files": [
                {
                    "provider_file_id": "drive-w",
                    "name": "order.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1024,
                }
            ],
        },
    )
    assert response.status_code == 404, response.text


def test_drive_dry_run_does_not_introduce_durable_sync_routes(
    client: TestClient,
) -> None:
    # Foundation must not introduce background sync, webhook, or polling
    # endpoints. Asserts the ADP-12 surface is dry-run + status only.
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    paths = set(response.json()["paths"].keys())
    drive_paths = {path for path in paths if "drive" in path.lower()}
    assert drive_paths == {
        "/api/matters/imports/drive/provider-config",
        "/api/matters/{matter_id}/imports/drive/dry-run",
    }, drive_paths
    for forbidden_substring in ("sync", "poll", "webhook", "commit", "oauth", "callback"):
        assert not any(
            forbidden_substring in path.lower() for path in drive_paths
        ), (forbidden_substring, drive_paths)


def test_drive_dry_run_payload_does_not_leak_oauth_tokens(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "ADP12-LEAK")

    response = client.post(
        f"/api/matters/{matter_id}/imports/drive/dry-run",
        headers=auth_headers(token),
        json={
            "files": [
                {
                    "provider_file_id": "drive-ok",
                    "name": "order.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1024,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    serialised = response.text.lower()
    for forbidden in (
        "access_token",
        "refresh_token",
        "client_secret",
        "authorization:",
        "bearer ",
    ):
        assert forbidden not in serialised
