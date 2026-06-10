"""Connector automation readiness regression coverage.

These tests cover the safety edges added for the connector automation slice:
durable health without token leakage, review-first metadata queues, locked
calendar conflict handling, disabled inbound email, and external notification
delivery defaults.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from caseops_api.db.models import Matter
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
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert "client_secret" not in response.text

    checked = client.post("/api/admin/integrations/health/check", headers=_auth(token))
    assert checked.status_code == 200, checked.text
    assert len(checked.json()["health"]) == len(body["health"])
    assert "refresh_token" not in checked.text


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


def test_notification_preferences_keep_external_delivery_disabled(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="notification-prefs",
        email="owner@notification-prefs.example",
    )
    token = str(bootstrap["access_token"])

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
