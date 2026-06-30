"""Connector automation readiness regression coverage.

These tests cover the safety edges added for the connector automation slice:
durable health without token leakage, review-first metadata queues, locked
calendar conflict handling, disabled inbound email, and external notification
delivery defaults.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    ConnectorHealthRecord,
    DriveFileCandidate,
    InboundEmailEvent,
    Matter,
)
from caseops_api.db.session import get_session_factory
from tests.test_legalworkspace_calendar_sync import (
    _auth,
    _bootstrap_company,
    _create_matter,
)


def test_connector_health_is_durable_and_token_safe(client: TestClient) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="connector-health",
        email="owner@connector-health.example",
    )
    token = str(bootstrap["access_token"])

    response = client.get("/api/admin/integrations/health", headers=_auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    providers = {row["provider"] for row in body["health"]}
    assert {"gmail", "google_drive", "google_calendar", "microsoft_365"} <= providers
    assert all(
        row["disabled_reason"] is None or len(row["disabled_reason"]) <= 160
        for row in body["health"]
    )
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert "client_secret" not in response.text

    checked = client.post("/api/admin/integrations/health/check", headers=_auth(token))
    assert checked.status_code == 200, checked.text
    assert len(checked.json()["health"]) == len(body["health"])
    assert "refresh_token" not in checked.text

    platform = client.get("/api/platform-admin/integrations/health", headers=_auth(token))
    assert platform.status_code == 403, platform.text


def test_admin_integrations_concurrent_reads_do_not_duplicate_health_records(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="connector-health-race",
        email="owner@connector-health-race.example",
    )
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    paths = [
        "/api/admin/integrations",
        "/api/admin/integrations/health",
        "/api/admin/integrations",
        "/api/admin/integrations/health",
        "/api/admin/integrations",
        "/api/admin/integrations/health",
    ]

    def request(path: str) -> tuple[int, str]:
        response = client.get(path, headers=_auth(token))
        return response.status_code, response.text

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(request, paths))

    assert all(status == 200 for status, _ in results), results

    factory = get_session_factory()
    with factory() as session:
        rows = list(
            session.scalars(
                select(ConnectorHealthRecord).where(
                    ConnectorHealthRecord.company_id == company_id
                )
            )
        )

    keys = [(row.provider, row.account_ref_hash) for row in rows]
    duplicates = {key: count for key, count in Counter(keys).items() if count > 1}
    assert duplicates == {}
    assert len(rows) >= 11


def test_microsoft365_configuration_masks_secret_and_reports_blocked_readiness(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="microsoft365-config",
        email="owner@microsoft365-config.example",
    )
    token = str(bootstrap["access_token"])

    updated = client.patch(
        "/api/admin/microsoft365-configuration",
        headers=_auth(token),
        json={
            "client_id": "graph-client-id",
            "client_secret": "graph-client-secret",
            "tenant_id": "graph-tenant-id",
            "redirect_uri": "https://api.caseops.test/auth/microsoft/callback",
            "scopes": ["User.Read", "Mail.Read", "Calendars.ReadWrite", "Files.Read.All"],
            "admin_consent_approved": False,
            "scopes_approved": True,
            "mail_enabled": True,
            "calendar_enabled": True,
            "drive_enabled": True,
            "enabled": True,
        },
    )

    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["provider"] == "microsoft_365"
    assert all(item["configured"] for item in body["required_config"])
    assert body["configured"] is False
    assert body["missing_approval_keys"] == ["admin_consent_approved"]
    assert body["readiness"] == "blocked_pending_admin_configuration"
    assert "graph-client-secret" not in updated.text
    assert "client_secret" not in updated.text

    tested = client.post(
        "/api/admin/microsoft365-configuration/test",
        headers=_auth(token),
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "blocked"
    assert "graph-client-secret" not in tested.text


def test_outlook_mail_candidate_is_review_first_without_body_import(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="outlook-review",
        email="owner@outlook-review.example",
    )
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, "OUTLOOK-1")

    created = client.post(
        "/api/mailbox/outlook/candidates",
        headers=_auth(token),
        json={
            "provider_message_id": "outlook-message-1",
            "provider_thread_id": "thread-1",
            "subject": "New demand notice",
            "sender_email": "client@example.com",
            "sender_name": "Client",
            "occurred_at": datetime.now(UTC).isoformat(),
            "snippet": "Please review the attached notice summary.",
            "labels": ["Inbox"],
            "attachment_count": 1,
            "suggested_matter_id": matter["id"],
        },
    )

    assert created.status_code == 200, created.text
    candidate = created.json()
    assert candidate["provider"] == "outlook_mail"
    assert candidate["status"] == "new"
    assert "Please review the attached notice summary." in created.text

    reviewed = client.patch(
        f"/api/mailbox/imports/{candidate['id']}",
        headers=_auth(token),
        json={"action": "request_content_import", "matter_id": matter["id"]},
    )

    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["content_import_queued"] is True
    assert reviewed.json()["import_record"]["status"] == "content_import_requested"
    assert "raw_body" not in reviewed.text


def test_drive_controls_never_enable_auto_import(client: TestClient) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="drive-controls",
        email="owner@drive-controls.example",
    )
    token = str(bootstrap["access_token"])

    response = client.patch(
        "/api/drive/google/controls",
        headers=_auth(token),
        json={
            "allowed_folders": ["Legal Intake"],
            "blocked_folders": ["Personal"],
            "max_file_size_bytes": 1048576,
            "allowed_mime_types": ["application/pdf"],
            "mode": "review_import",
            "auto_import_enabled": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_import_enabled"] is False
    assert body["allowed_folders"] == ["Legal Intake"]
    assert body["blocked_folders"] == ["Personal"]


def test_drive_candidate_queue_is_review_first_and_metadata_only(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="drive-candidates",
        email="owner@drive-candidates.example",
    )
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, "DRIVE-CAND-1")

    sync = client.post(
        "/api/drive/google/candidates/sync",
        headers=_auth(token),
        json={"limit": 10},
    )
    assert sync.status_code == 409, sync.text
    assert "not connected" in sync.text.lower()

    factory = get_session_factory()
    with factory() as session:
        candidate = DriveFileCandidate(
            company_id=str(bootstrap["company"]["id"]),
            provider="google_drive",
            provider_file_id="drive-candidate-1",
            provider_version="metadata-v1",
            name="Pleadings bundle.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
            owner_display="Client",
            modified_time=datetime.now(UTC),
            folder_path="Legal Intake",
            suggested_matter_id=str(matter["id"]),
            confidence=0.92,
            provenance_json={
                "provider": "google_drive",
                "provider_file_id": "drive-candidate-1",
                "content_imported": False,
            },
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    listed = client.get("/api/drive/candidates?status=new", headers=_auth(token))
    assert listed.status_code == 200, listed.text
    assert listed.json()["pending_count"] == 1
    assert listed.json()["candidates"][0]["name"] == "Pleadings bundle.pdf"
    assert "raw_body" not in listed.text

    reviewed = client.patch(
        f"/api/drive/candidates/{candidate_id}",
        headers=_auth(token),
        json={"action": "link_metadata", "matter_id": matter["id"]},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["candidate"]["status"] == "linked_metadata"
    assert reviewed.json()["candidate"]["imported_attachment_id"] is None


def test_calendar_candidate_respects_manual_locked_hearing(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="calendar-conflict",
        email="owner@calendar-conflict.example",
    )
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, "CAL-CONFLICT-1")

    factory = get_session_factory()
    with factory() as session:
        row = session.get(Matter, matter["id"])
        assert row is not None
        row.next_hearing_manual_lock = True
        session.commit()

    starts_at = datetime.now(UTC) + timedelta(days=7)
    created = client.post(
        "/api/calendar/provider-event-candidates",
        headers=_auth(token),
        json={
            "provider": "google_calendar",
            "provider_event_id": "event-lock-1",
            "title": "Arguments",
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(hours=1)).isoformat(),
            "location": "Delhi High Court",
            "organizer_display": "Court",
            "provider_status": "confirmed",
            "suggested_matter_id": matter["id"],
        },
    )
    assert created.status_code == 200, created.text

    reviewed = client.patch(
        f"/api/calendar/provider-event-candidates/{created.json()['id']}",
        headers=_auth(token),
        json={"action": "accept", "matter_id": matter["id"]},
    )

    assert reviewed.status_code == 409, reviewed.text
    assert "manually locked" in reviewed.text.lower()


def test_inbound_email_webhook_is_disabled_without_verified_provider(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/mailbox/inbound/webhook",
        json={
            "provider": "local_safe",
            "provider_message_id": "inbound-1",
            "from_email": "client@example.com",
            "to_addresses": ["matter@example.caseops.test"],
            "subject": "Matter email",
            "snippet": "Metadata only",
            "attachments": [
                {
                    "filename": "notice.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1234,
                    "scan_status": "pending_review",
                }
            ],
        },
    )

    assert response.status_code == 503, response.text
    assert "disabled" in response.text.lower()
    assert "Metadata only" not in response.text


def test_inbound_email_alias_and_event_review_stay_metadata_only(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="inbound-aliases",
        email="owner@inbound-aliases.example",
    )
    token = str(bootstrap["access_token"])

    created = client.post(
        "/api/mailbox/inbound-aliases",
        headers=_auth(token),
        json={
            "status": "disabled",
            "allowed_domains": ["client.example"],
            "retention_days": 90,
        },
    )
    assert created.status_code == 200, created.text
    alias = created.json()
    assert alias["status"] == "disabled"

    listed_aliases = client.get("/api/mailbox/inbound-aliases", headers=_auth(token))
    assert listed_aliases.status_code == 200, listed_aliases.text
    assert listed_aliases.json()["aliases"][0]["alias_address"] == alias["alias_address"]

    updated_alias = client.patch(
        f"/api/mailbox/inbound-aliases/{alias['id']}",
        headers=_auth(token),
        json={"status": "enabled", "allowed_senders": ["client@client.example"]},
    )
    assert updated_alias.status_code == 200, updated_alias.text
    assert updated_alias.json()["status"] == "enabled"

    factory = get_session_factory()
    with factory() as session:
        event = InboundEmailEvent(
            company_id=str(bootstrap["company"]["id"]),
            alias_id=alias["id"],
            provider="local_safe",
            provider_message_id="inbound-review-1",
            from_address_hash="sha256:redacted",
            from_display="Client",
            to_addresses_json=[alias["alias_address"]],
            cc_addresses_json=[],
            subject="Potential new matter",
            received_at=datetime.now(UTC),
            snippet="Metadata snippet only",
            attachment_metadata_json=[
                {
                    "filename": "notice.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1234,
                    "scan_status": "pending_review",
                }
            ],
            status="new",
            provenance_json={"provider": "local_safe", "body_imported": False},
        )
        session.add(event)
        session.commit()
        event_id = event.id

    listed_events = client.get("/api/mailbox/inbound-events", headers=_auth(token))
    assert listed_events.status_code == 200, listed_events.text
    assert listed_events.json()["pending_count"] == 1
    assert listed_events.json()["events"][0]["subject"] == "Potential new matter"
    assert "raw_body" not in listed_events.text

    reviewed_event = client.patch(
        f"/api/mailbox/inbound-events/{event_id}",
        headers=_auth(token),
        json={"action": "ignore"},
    )
    assert reviewed_event.status_code == 200, reviewed_event.text
    assert reviewed_event.json()["event"]["status"] == "ignored"
    assert "client@client.example" not in reviewed_event.text


def test_notification_preferences_keep_external_delivery_disabled(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="notification-prefs",
        email="owner@notification-prefs.example",
    )
    token = str(bootstrap["access_token"])

    admin_current = client.get("/api/admin/notification-preferences", headers=_auth(token))
    assert admin_current.status_code == 200, admin_current.text

    admin_updated = client.patch(
        "/api/admin/notification-preferences",
        headers=_auth(token),
        json={
            "channels": {"email": True, "sms": True, "whatsapp": True},
            "event_categories": {"connector_failures": True},
            "external_delivery_policy": "disabled_until_configured",
        },
    )
    assert admin_updated.status_code == 200, admin_updated.text
    assert admin_updated.json()["external_delivery_enabled"] is False

    updated = client.patch(
        "/api/notification-preferences",
        headers=_auth(token),
        json={
            "channels": {
                "in_app": True,
                "email": True,
                "sms": True,
                "whatsapp": True,
            },
            "digest_frequency": "daily",
            "event_categories": {"connector_failures": True},
        },
    )

    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["external_delivery_enabled"] is False
    assert body["user"]["channels"]["email"]["enabled"] is True
    assert body["user"]["channels"]["email"]["external_delivery_enabled"] is False
    assert body["user"]["channels"]["sms"]["external_delivery_enabled"] is False
    assert body["user"]["channels"]["whatsapp"]["external_delivery_enabled"] is False
