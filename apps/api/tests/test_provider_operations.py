from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProvider,
    CalendarSyncSourceType,
    NotificationDeliveryChannel,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _bootstrap_named_company(
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
            "owner_full_name": "Provider Ops Owner",
            "owner_email": email,
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _calendar_sync_fixture(
    *,
    company_id: str,
    membership_id: str,
    status: str = CalendarEventSyncStatus.DEAD_LETTER,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=membership_id,
            provider=CalendarProvider.OUTLOOK,
            status=CalendarConnectionStatus.CONNECTED,
            provider_account_id="outlook-account-sensitive",
        )
        session.add(connection)
        session.flush()
        sync = CalendarEventSync(
            company_id=company_id,
            calendar_connection_id=connection.id,
            source_type=CalendarSyncSourceType.MATTER_HEARING,
            source_id=str(uuid4()),
            provider_event_id="remote-event-secret-value",
            sync_status=status,
            last_error=(
                "authorization example-token-value-that-is-redacted for "
                "lawyer@example.test at https://provider.example.test/events/"
                f"{uuid4()}"
            ),
            attempts=3,
            max_attempts=3,
            dead_letter_reason=(
                "retry_limit_exhausted"
                if status == CalendarEventSyncStatus.DEAD_LETTER
                else None
            ),
        )
        session.add(sync)
        session.commit()
        return sync.id


def _notification_intent_fixture(
    *,
    company_id: str,
    membership_id: str,
    channel: str = NotificationDeliveryChannel.IN_APP,
    status: str = NotificationDeliveryStatus.DEAD_LETTER,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        intent = NotificationDeliveryIntent(
            company_id=company_id,
            recipient_membership_id=membership_id,
            channel=channel,
            event_type="legal_update_digest",
            source_type="legal_update_alert",
            source_id=f"alert-{uuid4()}",
            idempotency_key=uuid4().hex,
            status=status,
            attempts=3,
            max_attempts=3,
            last_error_redacted=(
                "bearer sensitive-provider-token for recipient@example.test "
                "at https://mail.example.test/send"
            ),
            dead_letter_reason=(
                "provider_disabled"
                if status == NotificationDeliveryStatus.BLOCKED
                else "retry_limit_exhausted"
            ),
        )
        session.add(intent)
        session.commit()
        return intent.id


def test_provider_operations_are_admin_only_redacted_and_tenant_scoped(
    client: TestClient,
) -> None:
    boot_a = bootstrap_company(client)
    owner_token = str(boot_a["access_token"])
    company_a = str(boot_a["company"]["id"])
    membership_a = str(boot_a["membership"]["id"])
    create_member = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Provider Ops Member",
            "email": "provider-member@asterlegal.in",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert create_member.status_code == 200, create_member.text
    login_member = client.post(
        "/api/auth/login",
        json={
            "email": "provider-member@asterlegal.in",
            "password": "MemberPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login_member.status_code == 200, login_member.text
    member_token = str(login_member.json()["access_token"])

    _calendar_sync_fixture(company_id=company_a, membership_id=membership_a)
    _notification_intent_fixture(
        company_id=company_a,
        membership_id=membership_a,
        channel=NotificationDeliveryChannel.EMAIL,
        status=NotificationDeliveryStatus.BLOCKED,
    )
    boot_b = _bootstrap_named_company(
        client,
        slug="provider-ops-other",
        email="owner@provider-ops-other.example",
    )
    _calendar_sync_fixture(
        company_id=str(boot_b["company"]["id"]),
        membership_id=str(boot_b["membership"]["id"]),
    )

    denied = client.get(
        "/api/admin/provider-operations/jobs",
        headers=auth_headers(member_token),
    )
    assert denied.status_code == 403, denied.text

    client.cookies.clear()
    response = client.get(
        "/api/admin/provider-operations/jobs",
        headers=auth_headers(owner_token),
    )
    assert response.status_code == 200, response.text
    text = response.text
    assert "lawyer@example.test" not in text
    assert "recipient@example.test" not in text
    assert "provider.example.test" not in text
    assert "mail.example.test" not in text
    assert "example-token-value" not in text
    assert "sensitive-provider-token" not in text
    assert "remote-event-secret-value" not in text

    body = response.json()
    assert len(body["operations"]) == 2
    assert body["open_count"] == 2
    assert {op["job_kind"] for op in body["operations"]} == {
        "calendar_sync",
        "notification_delivery",
    }
    assert all(op["company_id"] == company_a for op in body["operations"])
    assert all(op["source_ref"].startswith("id:") for op in body["operations"])


def test_provider_operation_replay_is_idempotent_and_audited(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    intent_id = _notification_intent_fixture(
        company_id=company_id,
        membership_id=membership_id,
        channel=NotificationDeliveryChannel.IN_APP,
        status=NotificationDeliveryStatus.DEAD_LETTER,
    )
    operation_id = f"notification_delivery:{intent_id}"

    first = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/replay",
        headers=auth_headers(token),
        json={"reason": "Manual retry after provider review."},
    )
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True
    assert first.json()["operation"]["status"] == "queued"

    second = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/replay",
        headers=auth_headers(token),
        json={"reason": "Duplicate click."},
    )
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is False

    factory = get_session_factory()
    with factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(NotificationDeliveryIntent))
            == 1
        )
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert intent is not None
        assert intent.status == NotificationDeliveryStatus.QUEUED
        assert intent.attempts == 0
        actions = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "provider_operation.replay",
                )
                .order_by(AuditEvent.created_at.asc())
            )
        )
        assert len(actions) == 2
        metadata = json.dumps([json.loads(event.metadata_json or "{}") for event in actions])
        assert intent.source_id not in metadata
        assert intent_id not in metadata
        assert "reason_present" in metadata


def test_external_delivery_replay_stays_blocked_fail_closed(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    intent_id = _notification_intent_fixture(
        company_id=company_id,
        membership_id=membership_id,
        channel=NotificationDeliveryChannel.EMAIL,
        status=NotificationDeliveryStatus.BLOCKED,
    )

    response = client.post(
        f"/api/admin/provider-operations/jobs/notification_delivery:{intent_id}/replay",
        headers=auth_headers(token),
        json={"reason": "Try email replay."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is False
    assert body["operation"]["status"] == "blocked"
    assert "blocked" in body["message"].lower()

    factory = get_session_factory()
    with factory() as session:
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert intent is not None
        assert intent.status == NotificationDeliveryStatus.BLOCKED
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "provider_operation.replay",
                AuditEvent.result == "denied",
            )
        )
        assert audit is not None


def test_provider_operation_resolve_moves_item_out_of_default_open_list(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    sync_id = _calendar_sync_fixture(
        company_id=company_id,
        membership_id=membership_id,
        status=CalendarEventSyncStatus.FAILED,
    )
    operation_id = f"calendar_sync:{sync_id}"

    resolved = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/mark-resolved",
        headers=auth_headers(token),
        json={"reason": "Handled in provider console."},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["operation"]["operator_state"] == "resolved"

    default_list = client.get(
        "/api/admin/provider-operations/jobs",
        headers=auth_headers(token),
    )
    assert default_list.status_code == 200, default_list.text
    assert default_list.json()["operations"] == []

    with_resolved = client.get(
        "/api/admin/provider-operations/jobs?include_resolved=true",
        headers=auth_headers(token),
    )
    assert with_resolved.status_code == 200, with_resolved.text
    assert with_resolved.json()["operations"][0]["operator_state"] == "resolved"


def test_provider_readiness_is_names_only_and_fail_closed(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_GOOGLE_DRIVE_CLIENT_ID", "drive-client-id-secret")
    monkeypatch.setenv("CASEOPS_GOOGLE_DRIVE_CLIENT_SECRET", "drive-client-secret")
    monkeypatch.setenv(
        "CASEOPS_GOOGLE_DRIVE_REDIRECT_URI",
        "https://app.example.test/oauth/google-drive",
    )
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "sendgrid-secret-token")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "billing@example.test")
    monkeypatch.setenv("CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY", "public-key-secret")
    get_settings.cache_clear()
    try:
        boot = bootstrap_company(client)
        token = str(boot["access_token"])

        response = client.get(
            "/api/admin/provider-operations/readiness",
            headers=auth_headers(token),
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200, response.text
    text = response.text
    for secret_value in (
        "drive-client-id-secret",
        "drive-client-secret",
        "app.example.test",
        "sendgrid-secret-token",
        "billing@example.test",
        "public-key-secret",
    ):
        assert secret_value not in text
    body = response.json()
    providers = {row["provider"]: row for row in body["providers"]}
    assert set(providers) == {
        "google_drive",
        "email_connector",
        "digest_delivery",
    }
    assert providers["google_drive"]["configured"] is True
    assert providers["google_drive"]["enabled"] is False
    assert providers["email_connector"]["external_calls_enabled"] is False
    assert providers["digest_delivery"]["external_calls_enabled"] is False
    assert "GOOGLE_DRIVE_CLIENT_SECRET" in providers["google_drive"][
        "required_config_names"
    ]

