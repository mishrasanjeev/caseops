from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, Company, MatterAttachment
from caseops_api.db.session import get_session_factory


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, slug_prefix: str) -> dict[str, object]:
    slug = f"{slug_prefix}-{uuid4().hex[:8]}"
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug_prefix.title()} Firm",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug_prefix.title()} Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": "StrongPass123!",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    body["_company_slug"] = slug
    return body


def _invite_user(
    client: TestClient,
    owner_token: str,
    *,
    company_slug: str,
    email: str,
    role: str,
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": f"Storage {role.title()}",
            "email": email,
            "password": "MemberPass123!",
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": company_slug,
            "email": email,
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return str(response.json()["membership_id"]), str(login.json()["access_token"])


def _create_matter(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": f"Storage Governance {code}",
            "matter_code": code,
            "client_name": "Storage Client",
            "opposing_party": "Storage Counterparty",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _set_quota(company_id: str, quota_bytes: int | None) -> None:
    factory = get_session_factory()
    with factory() as session:
        company = session.get(Company, company_id)
        assert company is not None
        company.storage_quota_bytes = quota_bytes
        session.commit()


def _seed_attachment(matter_id: str, *, size_bytes: int, filename: str) -> str:
    attachment_id = str(uuid4())
    factory = get_session_factory()
    with factory() as session:
        session.add(
            MatterAttachment(
                id=attachment_id,
                matter_id=matter_id,
                original_filename=filename,
                storage_key=f"test/storage-governance/{attachment_id}-{filename}",
                content_type="text/plain",
                size_bytes=size_bytes,
                sha256_hex="a" * 64,
            )
        )
        session.commit()
    return attachment_id


def _upload_txt(client: TestClient, token: str, matter_id: str, body: bytes) -> object:
    return client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=_auth(token),
        files={"file": ("storage-note.txt", body, "text/plain")},
    )


def test_firm_storage_usage_rollup_and_tenant_isolation(client: TestClient) -> None:
    boot_a = _bootstrap(client, "adp01-usage-a")
    boot_b = _bootstrap(client, "adp01-usage-b")
    token_a = str(boot_a["access_token"])
    token_b = str(boot_b["access_token"])
    matter_a1 = _create_matter(client, token_a, f"ADP01-A1-{uuid4().hex[:4]}")
    matter_a2 = _create_matter(client, token_a, f"ADP01-A2-{uuid4().hex[:4]}")
    matter_b = _create_matter(client, token_b, f"ADP01-B1-{uuid4().hex[:4]}")
    _seed_attachment(matter_a1, size_bytes=120, filename="a-one.txt")
    _seed_attachment(matter_a2, size_bytes=80, filename="a-two.txt")
    _seed_attachment(matter_b, size_bytes=999, filename="b-one.txt")

    response_a = client.get(
        "/api/admin/storage-governance",
        headers=_auth(token_a),
    )
    assert response_a.status_code == 200, response_a.text
    payload_a = response_a.json()
    assert payload_a["used_bytes"] == 200
    assert payload_a["quota_bytes"] is None
    assert payload_a["state"] == "unlimited"
    assert {row["matter_id"] for row in payload_a["usage_by_matter"]} == {
        matter_a1,
        matter_a2,
    }
    assert {row["matter_id"] for row in payload_a["largest_files"]} == {
        matter_a1,
        matter_a2,
    }

    response_b = client.get(
        "/api/admin/storage-governance",
        headers=_auth(token_b),
    )
    assert response_b.status_code == 200, response_b.text
    payload_b = response_b.json()
    assert payload_b["used_bytes"] == 999
    assert [row["matter_id"] for row in payload_b["usage_by_matter"]] == [matter_b]


def test_admin_storage_breakdowns_respect_matter_visibility(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "adp01-visibility")
    owner_token = str(boot["access_token"])
    admin_membership_id, admin_token = _invite_user(
        client,
        owner_token,
        company_slug=str(boot["_company_slug"]),
        email=f"admin-{uuid4().hex[:8]}@adp01-visibility.example",
        role="admin",
    )
    visible_matter = _create_matter(client, owner_token, f"ADP01-VIS-{uuid4().hex[:4]}")
    restricted_matter = _create_matter(
        client,
        owner_token,
        f"ADP01-REST-{uuid4().hex[:4]}",
    )
    walled_matter = _create_matter(client, owner_token, f"ADP01-WALL-{uuid4().hex[:4]}")
    team_matter = _create_matter(client, owner_token, f"ADP01-TEAM-{uuid4().hex[:4]}")
    _seed_attachment(visible_matter, size_bytes=20, filename="visible-file.txt")
    _seed_attachment(restricted_matter, size_bytes=30, filename="restricted-file.txt")
    _seed_attachment(walled_matter, size_bytes=40, filename="walled-file.txt")
    _seed_attachment(team_matter, size_bytes=50, filename="team-file.txt")

    restricted = client.post(
        f"/api/matters/{restricted_matter}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    wall = client.post(
        f"/api/matters/{walled_matter}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": admin_membership_id},
    )
    assert wall.status_code == 200, wall.text
    team = client.post(
        "/api/teams/",
        headers=_auth(owner_token),
        json={"name": "Storage Governance", "slug": f"storage-{uuid4().hex[:8]}"},
    )
    assert team.status_code == 201, team.text
    assign = client.patch(
        f"/api/matters/{team_matter}",
        headers=_auth(owner_token),
        json={"team_id": team.json()["id"]},
    )
    assert assign.status_code == 200, assign.text
    scope = client.put(
        "/api/teams/scoping",
        headers=_auth(owner_token),
        json={"enabled": True},
    )
    assert scope.status_code == 200, scope.text

    response = client.get(
        "/api/admin/storage-governance",
        headers=_auth(admin_token),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["used_bytes"] == 140
    visible_ids = {row["matter_id"] for row in payload["usage_by_matter"]}
    largest_ids = {row["matter_id"] for row in payload["largest_files"]}
    archive_ids = {row["matter_id"] for row in payload["archive_candidates"]}
    assert visible_matter in visible_ids
    for hidden_id in {restricted_matter, walled_matter, team_matter}:
        assert hidden_id not in visible_ids
        assert hidden_id not in largest_ids
        assert hidden_id not in archive_ids
    details = json.dumps(
        {
            "usage_by_matter": payload["usage_by_matter"],
            "largest_files": payload["largest_files"],
            "archive_candidates": payload["archive_candidates"],
        }
    )
    assert "restricted-file.txt" not in details
    assert "walled-file.txt" not in details
    assert "team-file.txt" not in details


def test_upload_under_quota_succeeds(client: TestClient) -> None:
    boot = _bootstrap(client, "adp01-under")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, f"ADP01-UNDER-{uuid4().hex[:4]}")
    _set_quota(company_id, 1024)

    response = _upload_txt(client, token, matter_id, b"within quota")

    assert response.status_code == 200, response.text
    assert response.json()["size_bytes"] == len(b"within quota")


def test_upload_over_quota_is_blocked_before_storage_write(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "adp01-over")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, f"ADP01-OVER-{uuid4().hex[:4]}")
    _set_quota(company_id, 10)

    response = _upload_txt(client, token, matter_id, b"this is too large")

    assert response.status_code == 413, response.text
    assert "Firm storage quota exceeded" in response.json()["detail"]
    storage_root = Path(get_settings().document_storage_path)
    if storage_root.exists():
        assert not any(path.is_file() for path in storage_root.rglob("*"))
    factory = get_session_factory()
    with factory() as session:
        attachment_count = session.scalar(
            select(func.count(MatterAttachment.id)).where(
                MatterAttachment.matter_id == matter_id
            )
        )
        assert attachment_count == 0
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "storage_quota.upload_blocked",
            )
        )
        assert audit is not None
        assert audit.result == "denied"
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["status"] == "blocked"
        assert metadata["incoming_size_bytes"] == len(b"this is too large")
        redacted = json.dumps(metadata)
        assert "storage-note.txt" not in redacted
        assert "filename" not in redacted


def test_zero_quota_is_a_hard_limit(client: TestClient) -> None:
    boot = _bootstrap(client, "adp01-zero")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, f"ADP01-ZERO-{uuid4().hex[:4]}")
    _set_quota(company_id, 0)

    response = _upload_txt(client, token, matter_id, b"x")

    assert response.status_code == 413, response.text
    workspace = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=_auth(token),
    )
    assert workspace.status_code == 200, workspace.text
    storage_policy = workspace.json()["storage_governance"]
    assert storage_policy["quota_bytes"] == 0
    assert storage_policy["remaining_bytes"] == 0
    assert storage_policy["state"] == "hard_limit"
    factory = get_session_factory()
    with factory() as session:
        attachment_count = session.scalar(
            select(func.count(MatterAttachment.id)).where(
                MatterAttachment.matter_id == matter_id
            )
        )
        assert attachment_count == 0


def test_upload_without_quota_preserves_existing_behavior(client: TestClient) -> None:
    boot = _bootstrap(client, "adp01-unset")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, f"ADP01-UNSET-{uuid4().hex[:4]}")

    response = _upload_txt(client, token, matter_id, b"legacy upload")

    assert response.status_code == 200, response.text
    workspace = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=_auth(token),
    )
    assert workspace.status_code == 200, workspace.text
    storage_policy = workspace.json()["storage_governance"]
    assert storage_policy["quota_bytes"] is None
    assert storage_policy["remaining_bytes"] is None
    assert storage_policy["state"] == "unlimited"


def test_admin_quota_update_is_audited_without_file_metadata(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "adp01-admin")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])

    response = client.patch(
        "/api/admin/storage-governance",
        headers=_auth(token),
        json={"quota_bytes": 4096},
    )

    assert response.status_code == 200, response.text
    assert response.json()["quota_bytes"] == 4096
    factory = get_session_factory()
    with factory() as session:
        company = session.get(Company, company_id)
        assert company is not None
        assert company.storage_quota_bytes == 4096
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "storage_quota.updated",
            )
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["before_quota_bytes"] is None
        assert metadata["after_quota_bytes"] == 4096
        redacted = json.dumps(metadata)
        assert "filename" not in redacted
        assert "document" not in redacted


def test_admin_negative_quota_is_rejected(client: TestClient) -> None:
    boot = _bootstrap(client, "adp01-negative")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])

    response = client.patch(
        "/api/admin/storage-governance",
        headers=_auth(token),
        json={"quota_bytes": -1},
    )

    assert response.status_code == 422, response.text
    factory = get_session_factory()
    with factory() as session:
        company = session.get(Company, company_id)
        assert company is not None
        assert company.storage_quota_bytes is None
