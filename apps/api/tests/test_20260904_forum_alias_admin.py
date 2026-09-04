from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    ForumCatalogAlias,
    ForumCatalogEntry,
    PlatformAdminAuditEvent,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _founder_token(client: TestClient, monkeypatch) -> str:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    return str(bootstrap_company(client)["access_token"])


def test_tenant_owner_cannot_manage_global_forum_aliases(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])

    response = client.get(
        "/api/platform-admin/forum-aliases",
        headers=auth_headers(token),
    )

    assert response.status_code == 403, response.text


def test_forum_alias_admin_rejects_source_url_longer_than_storage_contract(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        target_id = session.scalar(
            select(ForumCatalogEntry.id)
            .where(ForumCatalogEntry.is_active.is_(True))
            .order_by(ForumCatalogEntry.id)
            .limit(1)
        )
        assert target_id is not None

    response = client.post(
        "/api/platform-admin/forum-aliases",
        headers=auth_headers(token),
        json={
            "forum_catalog_entry_id": target_id,
            "alias": "A bounded source URL alias",
            "alias_type": "other",
            "source_name": "Official source",
            "source_url": f"https://example.test/{'a' * 500}",
            "verification_status": "pending",
            "is_active": True,
            "reason": "Prove request validation matches the database contract.",
        },
    )

    assert response.status_code == 422, response.text


def test_forum_alias_admin_rejects_null_and_empty_updates(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)

    for payload in (
        {
            "alias": None,
            "expected_record_version": 0,
            "reason": "Reject an explicit null alias before persistence.",
        },
        {
            "expected_record_version": 0,
            "reason": "Reject a no-op update before persistence.",
        },
        {
            "is_active": False,
            "expected_record_version": 0,
            "reason": "     ",
        },
    ):
        response = client.patch(
            "/api/platform-admin/forum-aliases/not-used",
            headers=auth_headers(token),
            json=payload,
        )
        assert response.status_code == 422, response.text


def test_forum_alias_admin_rejects_whitespace_only_required_text(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        target_id = session.scalar(
            select(ForumCatalogEntry.id)
            .where(ForumCatalogEntry.is_active.is_(True))
            .order_by(ForumCatalogEntry.id)
            .limit(1)
        )
        assert target_id is not None

    valid_payload = {
        "forum_catalog_entry_id": target_id,
        "alias": "Whitespace boundary alias",
        "alias_type": "other",
        "source_name": "Official source",
        "source_url": None,
        "verification_status": "pending",
        "is_active": True,
        "reason": "Add a request-boundary validation regression.",
    }
    for field_name in ("forum_catalog_entry_id", "alias", "source_name", "reason"):
        response = client.post(
            "/api/platform-admin/forum-aliases",
            headers=auth_headers(token),
            json={**valid_payload, field_name: "     "},
        )
        assert response.status_code == 422, (field_name, response.text)


def test_platform_admin_alias_lifecycle_is_source_backed_audited_and_generic(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        target = session.scalar(
            select(ForumCatalogEntry)
            .where(
                ForumCatalogEntry.is_active.is_(True),
                ForumCatalogEntry.state.is_not(None),
                ForumCatalogEntry.state != "Delhi",
            )
            .order_by(ForumCatalogEntry.state, ForumCatalogEntry.name)
            .limit(1)
        )
        assert target is not None
        target_id = target.id
        target_state = target.state

    alias_label = f"September registry label {target_state}"
    created = client.post(
        "/api/platform-admin/forum-aliases",
        headers=auth_headers(token),
        json={
            "forum_catalog_entry_id": target_id,
            "alias": alias_label,
            "alias_type": "provider_label",
            "source_name": "Official eCourts services directory",
            "source_url": "https://services.ecourts.gov.in/",
            "verification_status": "verified",
            "is_active": True,
            "reason": "Add a reviewed non-Delhi provider label for regression coverage.",
        },
    )
    assert created.status_code == 200, created.text
    record = created.json()
    assert record["forum_catalog_entry_id"] == target_id
    assert record["alias_type"] == "provider_label"
    assert record["verification_status"] == "verified"
    assert record["record_version"] == 0
    assert record["created_by_platform_admin_id"]
    assert record["reviewed_by_platform_admin_id"] == record["created_by_platform_admin_id"]
    assert record["updated_by_platform_admin_id"] == record["created_by_platform_admin_id"]

    listing = client.get(
        "/api/platform-admin/forum-aliases",
        headers=auth_headers(token),
        params={"q": alias_label, "verification_status": "verified", "is_active": True},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["returned_count"] == 1
    assert listing.json()["aliases"][0]["id"] == record["id"]

    resolved = client.get(
        "/api/courts/forum-catalog/resolve",
        headers=auth_headers(token),
        params={"query": alias_label, "state": target_state},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_entry"]["id"] == target_id

    deactivated = client.patch(
        f"/api/platform-admin/forum-aliases/{record['id']}",
        headers=auth_headers(token),
        json={
            "is_active": False,
            "expected_record_version": 0,
            "reason": "Retire the regression alias after proving the live resolver path.",
        },
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False
    assert deactivated.json()["record_version"] == 1

    no_longer_resolved = client.get(
        "/api/courts/forum-catalog/resolve",
        headers=auth_headers(token),
        params={"query": alias_label, "state": target_state},
    )
    assert no_longer_resolved.status_code == 200, no_longer_resolved.text
    assert no_longer_resolved.json()["status"] == "not_found"

    stale = client.patch(
        f"/api/platform-admin/forum-aliases/{record['id']}",
        headers=auth_headers(token),
        json={
            "is_active": True,
            "expected_record_version": 0,
            "reason": "Attempt a deliberately stale alias update for regression coverage.",
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["type"] == "forum_alias_stale_write"
    assert stale.json()["code"] == "forum_alias_stale_write"

    with factory() as session:
        stored = session.get(ForumCatalogAlias, record["id"])
        assert stored is not None
        assert stored.is_active is False
        assert stored.record_version == 1
        audit_actions = {row.action for row in session.scalars(select(PlatformAdminAuditEvent))}
        assert {
            "platform.forum_alias.created",
            "platform.forum_alias.updated",
            "platform.forum_aliases.viewed",
        }.issubset(audit_actions)


def test_pending_alias_is_not_resolvable_and_verification_requires_https_source(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        target_id = session.scalar(
            select(ForumCatalogEntry.id)
            .where(ForumCatalogEntry.is_active.is_(True))
            .order_by(ForumCatalogEntry.id)
            .limit(1)
        )
        assert target_id is not None

    missing_source = client.post(
        "/api/platform-admin/forum-aliases",
        headers=auth_headers(token),
        json={
            "forum_catalog_entry_id": target_id,
            "alias": "Verified without source",
            "alias_type": "other",
            "source_name": "Reviewed registry",
            "source_url": None,
            "verification_status": "verified",
            "is_active": True,
            "reason": "Prove verified identities cannot be admitted without source evidence.",
        },
    )
    assert missing_source.status_code == 422, missing_source.text
    assert missing_source.json()["type"] == "forum_alias_verified_source_required"
    assert missing_source.json()["code"] == "forum_alias_verified_source_required"

    pending = client.post(
        "/api/platform-admin/forum-aliases",
        headers=auth_headers(token),
        json={
            "forum_catalog_entry_id": target_id,
            "alias": "Pending September alias",
            "alias_type": "spelling_variant",
            "source_name": "Unconfirmed registry report",
            "source_url": None,
            "verification_status": "pending",
            "is_active": True,
            "reason": "Record a candidate without admitting it into legal identity resolution.",
        },
    )
    assert pending.status_code == 200, pending.text

    unresolved = client.get(
        "/api/courts/forum-catalog/resolve",
        headers=auth_headers(token),
        params={"query": "Pending September alias"},
    )
    assert unresolved.status_code == 200, unresolved.text
    assert unresolved.json()["status"] == "not_found"

    duplicate = client.post(
        "/api/platform-admin/forum-aliases",
        headers=auth_headers(token),
        json={
            "forum_catalog_entry_id": target_id,
            "alias": "Pending-September Alias",
            "alias_type": "local_name",
            "source_name": "Second report",
            "source_url": None,
            "verification_status": "pending",
            "is_active": True,
            "reason": "Prove normalized duplicates update the existing row instead.",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["type"] == "forum_alias_duplicate"
    assert duplicate.json()["code"] == "forum_alias_duplicate"
