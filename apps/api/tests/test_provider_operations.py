from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
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
    CaseTrackingSupportMatrix,
    Company,
    CompanyMembership,
    ConnectorHealthRecord,
    ConnectorHealthStatus,
    MailboxWebhookEvent,
    MailboxWebhookStatus,
    MatterHearing,
    MembershipRole,
    NotificationDeliveryChannel,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    UserCalendarConnection,
    UserMailboxConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.calendar_projection_safety import (
    CALENDAR_UPSERT_CLAIM_IN_FLIGHT_CODE,
    CALENDAR_UPSERT_CLAIM_PREFIX,
    CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE,
    CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
)
from caseops_api.services.calendar_sync import (
    materialize_expired_calendar_upsert_claims,
)
from caseops_api.services.provider_operations import update_provider_operation_state
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_legalworkspace_calendar_sync import _create_matter


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
        connection = session.scalar(
            select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == company_id,
                UserCalendarConnection.membership_id == membership_id,
                UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
            )
        )
        if connection is None:
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
                f"{uuid4()} webhook-signature: signed-secret phone +91 98765 43210"
            ),
            attempts=3,
            max_attempts=3,
            dead_letter_reason=(
                "retry_limit_exhausted signature=dead-letter-secret"
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


def _mailbox_webhook_fixture(
    *,
    company_id: str,
    membership_id: str,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        connection = session.scalar(
            select(UserMailboxConnection).where(
                UserMailboxConnection.company_id == company_id,
                UserMailboxConnection.membership_id == membership_id,
            )
        )
        if connection is None:
            connection = UserMailboxConnection(
                company_id=company_id,
                membership_id=membership_id,
                provider="gmail",
                status="connected",
            )
            session.add(connection)
            session.flush()
        event = MailboxWebhookEvent(
            company_id=company_id,
            mailbox_connection_id=connection.id,
            provider="gmail",
            history_id=f"history-{uuid4()}",
            email_address_hash=uuid4().hex,
            status=MailboxWebhookStatus.DEAD_LETTER,
            last_error_redacted="retry_limit_exhausted",
            attempts=3,
            max_attempts=3,
        )
        session.add(event)
        session.commit()
        return event.id


def _replay_preview(
    client: TestClient,
    *,
    token: str,
    operation_ids: list[str],
):
    return client.post(
        "/api/admin/provider-operations/jobs/replay-preview",
        headers=auth_headers(token),
        json={"operation_ids": operation_ids},
    )


def _unknown_calendar_create_fixture(
    *,
    company_id: str,
    membership_id: str,
    source_id: str,
    provider: str,
) -> tuple[str, str, datetime]:
    factory = get_session_factory()
    with factory() as session:
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=membership_id,
            provider=provider,
            status=CalendarConnectionStatus.REVOKED,
            encrypted_token_ref="retained-encrypted-reconciliation-credential",
        )
        session.add(connection)
        session.flush()
        sync = CalendarEventSync(
            company_id=company_id,
            calendar_connection_id=connection.id,
            source_type=CalendarSyncSourceType.MATTER_HEARING,
            source_id=source_id,
            provider_event_id=None,
            sync_status=CalendarEventSyncStatus.DEAD_LETTER,
            last_error="Calendar provider upsert outcome is unknown.",
            dead_letter_reason=CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
            attempts=1,
            max_attempts=3,
            next_attempt_at=None,
        )
        session.add(sync)
        session.commit()
        return sync.id, connection.id, sync.updated_at


def _raw_calendar_create_claim_fixture(
    *,
    company_id: str,
    membership_id: str,
    source_id: str,
    provider: str,
    live: bool,
) -> tuple[str, str, str]:
    factory = get_session_factory()
    with factory() as session:
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=membership_id,
            provider=provider,
            status=CalendarConnectionStatus.CONNECTED,
            encrypted_token_ref="retained-encrypted-raw-claim-credential",
        )
        session.add(connection)
        session.flush()
        marker = f"{CALENDAR_UPSERT_CLAIM_PREFIX}{uuid4().hex}"
        sync = CalendarEventSync(
            company_id=company_id,
            calendar_connection_id=connection.id,
            source_type=CalendarSyncSourceType.MATTER_HEARING,
            source_id=source_id,
            provider_event_id=None,
            sync_status=CalendarEventSyncStatus.PENDING,
            dead_letter_reason=marker,
            attempts=1,
            next_attempt_at=datetime.now(UTC)
            + (timedelta(minutes=5) if live else -timedelta(seconds=1)),
        )
        session.add(sync)
        session.commit()
        return sync.id, connection.id, marker


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
    assert "signed-secret" not in text
    assert "dead-letter-secret" not in text
    assert "98765" not in text

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

    preview = _replay_preview(client, token=token, operation_ids=[operation_id])
    assert preview.status_code == 200, preview.text
    assert preview.json()["operation_count"] == 1
    assert preview.json()["estimated_total_cost_minor"] == 0
    assert preview.json()["items"][0]["cost_basis"] == "internal_idempotent_delivery"
    preview_token = preview.json()["preview_token"]

    first = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/replay",
        headers=auth_headers(token),
        json={
            "reason": "Manual retry after provider review.",
            "preview_token": preview_token,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True
    assert first.json()["operation"]["status"] == "queued"

    second = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/replay",
        headers=auth_headers(token),
        json={"reason": "Duplicate click.", "preview_token": preview_token},
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


def test_provider_operation_mutation_requires_operator_reason(
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

    response = client.post(
        f"/api/admin/provider-operations/jobs/notification_delivery:{intent_id}/replay",
        headers=auth_headers(token),
        json={},
    )
    assert response.status_code == 422, response.text

    factory = get_session_factory()
    with factory() as session:
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert intent is not None
        assert intent.status == NotificationDeliveryStatus.DEAD_LETTER
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "provider_operation.replay",
                )
            )
            == 0
        )


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
        "/api/admin/provider-operations/jobs/replay-preview",
        headers=auth_headers(token),
        json={"operation_ids": [f"notification_delivery:{intent_id}"]},
    )
    assert response.status_code == 409, response.text

    factory = get_session_factory()
    with factory() as session:
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert intent is not None
        assert intent.status == NotificationDeliveryStatus.BLOCKED
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "provider_operation.replay_preview_denied",
                AuditEvent.result == "denied",
            )
        )
        assert audit is not None


def test_provider_operation_ignore_is_idempotent_and_audited(
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
        f"/api/admin/provider-operations/jobs/{operation_id}/ignore",
        headers=auth_headers(token),
        json={"reason": "Known duplicate provider event."},
    )
    assert first.status_code == 200, first.text
    assert first.json()["changed"] is True
    assert first.json()["operation"]["operator_state"] == "ignored"

    second = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/ignore",
        headers=auth_headers(token),
        json={"reason": "Repeat ignore after refresh."},
    )
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is False

    default_list = client.get(
        "/api/admin/provider-operations/jobs",
        headers=auth_headers(token),
    )
    assert default_list.status_code == 200, default_list.text
    assert default_list.json()["operations"] == []

    with_ignored = client.get(
        "/api/admin/provider-operations/jobs?include_resolved=true",
        headers=auth_headers(token),
    )
    assert with_ignored.status_code == 200, with_ignored.text
    assert with_ignored.json()["operations"][0]["operator_state"] == "ignored"

    factory = get_session_factory()
    with factory() as session:
        actions = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "provider_operation.ignore",
                )
                .order_by(AuditEvent.created_at.asc())
            )
        )
        assert len(actions) == 2
        metadata = json.dumps([json.loads(event.metadata_json or "{}") for event in actions])
        assert intent_id not in metadata
        assert "Known duplicate provider event." not in metadata
        assert "reason_present" in metadata


def test_provider_operation_actor_demotion_wins_before_operation_lock_and_audit(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    sync_id = _calendar_sync_fixture(
        company_id=company_id,
        membership_id=membership_id,
    )
    operation_id = f"calendar_sync:{sync_id}"
    factory = get_session_factory()
    with factory() as session:
        company = session.get(Company, company_id)
        membership = session.get(CompanyMembership, membership_id)
        assert company is not None and membership is not None
        stale_context = SessionContext(
            company=company,
            membership=membership,
            user=membership.user,
        )
        session.expunge_all()

    with factory() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = MembershipRole.MEMBER
        session.add(membership)
        session.commit()

    with factory() as session:
        with pytest.raises(HTTPException) as denied:
            update_provider_operation_state(
                session,
                context=stale_context,
                operation_id=operation_id,
                action="ignore",
                reason="A stale administrator context must not mutate provider work.",
            )
        assert denied.value.status_code == 403
        session.rollback()

    with factory() as session:
        sync = session.get(CalendarEventSync, sync_id)
        assert sync is not None
        assert sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
        assert sync.dead_letter_reason != "operator_ignored"
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "provider_operation.ignore",
            )
        ) == 0


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


@pytest.mark.parametrize("action", ["ignore", "mark-resolved"])
@pytest.mark.parametrize(
    ("kind", "fixture"),
    [
        ("notification_delivery", _notification_intent_fixture),
        ("mailbox_webhook", _mailbox_webhook_fixture),
    ],
)
def test_operator_closed_notification_and_webhook_cannot_replay(
    client: TestClient,
    action: str,
    kind: str,
    fixture,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    row_id = fixture(
        company_id=str(boot["company"]["id"]),
        membership_id=str(boot["membership"]["id"]),
    )
    operation_id = f"{kind}:{row_id}"

    closed = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/{action}",
        headers=auth_headers(token),
        json={"reason": "Operator verified this exact poison row is closed."},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["operation"]["operator_state"] in {"ignored", "resolved"}
    assert closed.json()["operation"]["replay_available"] is False

    exact = client.get(
        f"/api/admin/provider-operations/jobs/{operation_id}",
        headers=auth_headers(token),
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["replay_available"] is False
    preview = _replay_preview(client, token=token, operation_ids=[operation_id])
    assert preview.status_code == 409, preview.text


@pytest.mark.parametrize(
    ("kind", "fixture"),
    [
        ("calendar_sync", _calendar_sync_fixture),
        ("notification_delivery", _notification_intent_fixture),
        ("mailbox_webhook", _mailbox_webhook_fixture),
    ],
)
def test_operator_closed_row_is_filtered_before_same_source_limit(
    client: TestClient,
    kind: str,
    fixture,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    valid_id = fixture(company_id=company_id, membership_id=membership_id)
    closed_id = fixture(company_id=company_id, membership_id=membership_id)
    closed_operation_id = f"{kind}:{closed_id}"
    closed = client.post(
        f"/api/admin/provider-operations/jobs/{closed_operation_id}/ignore",
        headers=auth_headers(token),
        json={"reason": "Close the newest poison row before bounded selection."},
    )
    assert closed.status_code == 200, closed.text

    listing = client.get(
        "/api/admin/provider-operations/jobs?limit=1",
        headers=auth_headers(token),
    )
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert [row["id"] for row in payload["operations"]] == [f"{kind}:{valid_id}"]
    assert payload["returned_count"] == 1
    assert payload["page_limit"] == 1
    assert payload["counts_scope"] == "page"
    assert payload["open_count"] == 1


def test_exact_operation_lookup_discovers_old_reconciliation_row_beyond_200(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    matter = _create_matter(client, token, "PROVIDER-EXACT-LOOKUP")
    factory = get_session_factory()
    with factory() as session:
        hearing = MatterHearing(
            company_id=company_id,
            matter_id=str(matter["id"]),
            hearing_on=date.today() + timedelta(days=7),
            forum_name="Delhi High Court",
            purpose="Exact lookup reconciliation",
        )
        session.add(hearing)
        session.commit()
        hearing_id = hearing.id
    unknown_id, _connection_id, _updated_at = _unknown_calendar_create_fixture(
        company_id=company_id,
        membership_id=membership_id,
        source_id=hearing_id,
        provider=CalendarProvider.GOOGLE_CALENDAR,
    )
    operation_id = f"calendar_sync:{unknown_id}"
    with factory() as session:
        unknown = session.get(CalendarEventSync, unknown_id)
        assert unknown is not None
        unknown.updated_at = datetime.now(UTC) - timedelta(days=2)
        now = datetime.now(UTC)
        session.add_all(
            [
                NotificationDeliveryIntent(
                    company_id=company_id,
                    recipient_membership_id=membership_id,
                    channel=NotificationDeliveryChannel.IN_APP,
                    event_type="legal_update_digest",
                    source_type="legal_update_alert",
                    source_id=f"newer-{index}-{uuid4()}",
                    idempotency_key=uuid4().hex,
                    status=NotificationDeliveryStatus.DEAD_LETTER,
                    attempts=3,
                    max_attempts=3,
                    dead_letter_reason="retry_limit_exhausted",
                    updated_at=now + timedelta(seconds=index),
                )
                for index in range(201)
            ]
        )
        session.commit()

    listing = client.get(
        "/api/admin/provider-operations/jobs?limit=200",
        headers=auth_headers(token),
    )
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert payload["returned_count"] == 200
    assert payload["has_more"] is True
    assert operation_id not in {row["id"] for row in payload["operations"]}

    exact = client.get(
        f"/api/admin/provider-operations/jobs/{operation_id}",
        headers=auth_headers(token),
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["id"] == operation_id
    assert exact.json()["manual_reconciliation_required"] is True
    missing = client.get(
        f"/api/admin/provider-operations/jobs/calendar_sync:{uuid4()}",
        headers=auth_headers(token),
    )
    assert missing.status_code == 404, missing.text


@pytest.mark.parametrize(
    "provider",
    [CalendarProvider.GOOGLE_CALENDAR, CalendarProvider.OUTLOOK],
)
@pytest.mark.parametrize("live", [True, False], ids=["live", "expired"])
def test_raw_calendar_create_claim_is_never_replayed_or_operator_closed(
    client: TestClient,
    provider: CalendarProvider,
    live: bool,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    matter = _create_matter(
        client,
        token,
        f"RAW-{provider.value.replace('_', '-')}-{int(live)}",
    )
    factory = get_session_factory()
    with factory() as session:
        hearing = MatterHearing(
            company_id=company_id,
            matter_id=str(matter["id"]),
            hearing_on=date.today() + timedelta(days=7),
            forum_name="Delhi High Court",
            purpose="Raw provider claim",
        )
        session.add(hearing)
        session.commit()
        hearing_id = hearing.id
    sync_id, connection_id, marker = _raw_calendar_create_claim_fixture(
        company_id=company_id,
        membership_id=membership_id,
        source_id=hearing_id,
        provider=provider,
        live=live,
    )
    operation_id = f"calendar_sync:{sync_id}"
    expected_code = (
        CALENDAR_UPSERT_CLAIM_IN_FLIGHT_CODE
        if live
        else CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE
    )

    exact = client.get(
        f"/api/admin/provider-operations/jobs/{operation_id}",
        headers=auth_headers(token),
    )
    assert exact.status_code == 200, exact.text
    record = exact.json()
    assert record["replay_available"] is False
    assert record["ignore_available"] is False
    assert record["mark_resolved_available"] is False
    assert record["manual_reconciliation_required"] is (not live)
    assert record["automatic_replay_block_code"] == expected_code
    if not live:
        assert record["status"] == "dead_letter"
        assert record["dead_letter_reason"] == "[token-redacted]"
        assert marker not in exact.text

    preview = _replay_preview(client, token=token, operation_ids=[operation_id])
    assert preview.status_code == 409, preview.text
    assert preview.json()["code"] == expected_code
    for action in ("ignore", "mark-resolved"):
        denied = client.post(
            f"/api/admin/provider-operations/jobs/{operation_id}/{action}",
            headers=auth_headers(token),
            json={"reason": "Preserve the ambiguous provider-create receipt fence."},
        )
        assert denied.status_code == 409, denied.text
        assert denied.json()["code"] == expected_code

    with factory() as session:
        sync = session.get(CalendarEventSync, sync_id)
        connection = session.get(UserCalendarConnection, connection_id)
        assert sync is not None and connection is not None
        if live:
            assert sync.sync_status == CalendarEventSyncStatus.PENDING
            assert sync.dead_letter_reason == marker
        else:
            assert sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert sync.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            assert sync.next_attempt_at is None
        assert sync.provider_event_id is None
        assert connection.encrypted_token_ref is not None


def test_expired_calendar_claim_sweep_is_source_and_range_independent_for_both_providers(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    factory = get_session_factory()
    sync_ids: list[str] = []
    with factory() as session:
        company = session.get(Company, company_id)
        membership = session.get(CompanyMembership, membership_id)
        assert company is not None and membership is not None and membership.user is not None
        context = SessionContext(
            company=company,
            membership=membership,
            user=membership.user,
        )
        for provider in (
            CalendarProvider.GOOGLE_CALENDAR,
            CalendarProvider.OUTLOOK,
        ):
            connection = UserCalendarConnection(
                company_id=company_id,
                membership_id=membership_id,
                provider=provider,
                status=CalendarConnectionStatus.CONNECTED,
                encrypted_token_ref=f"retained-{provider.value}-credential",
            )
            session.add(connection)
            session.flush()
            for source_type in (
                CalendarSyncSourceType.MATTER_HEARING,
                CalendarSyncSourceType.MATTER_TASK,
                CalendarSyncSourceType.MATTER_DEADLINE,
            ):
                sync = CalendarEventSync(
                    company_id=company_id,
                    calendar_connection_id=connection.id,
                    source_type=source_type,
                    source_id=str(uuid4()),  # Deliberately missing and range-less.
                    sync_status=CalendarEventSyncStatus.PENDING,
                    dead_letter_reason=f"{CALENDAR_UPSERT_CLAIM_PREFIX}{uuid4().hex}",
                    next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
                )
                session.add(sync)
                session.flush()
                sync_ids.append(sync.id)
        session.commit()

        for provider in (
            CalendarProvider.GOOGLE_CALENDAR,
            CalendarProvider.OUTLOOK,
        ):
            assert materialize_expired_calendar_upsert_claims(
                session,
                context=context,
                calendar_provider=provider,
                limit=3,
            ) == 3
            # A second worker observes durable terminal UNKNOWN rows and does
            # no work; source lookup and provider I/O are never prerequisites.
            assert materialize_expired_calendar_upsert_claims(
                session,
                context=context,
                calendar_provider=provider,
                limit=3,
            ) == 0

        rows = list(
            session.scalars(
                select(CalendarEventSync).where(CalendarEventSync.id.in_(sync_ids))
            )
        )
        assert len(rows) == 6
        assert all(
            row.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            and row.provider_event_id is None
            and row.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            and row.next_attempt_at is None
            for row in rows
        )


def test_expired_raw_calendar_claim_can_be_reconciled_directly_from_exact_record(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    matter = _create_matter(client, token, "RAW-DIRECT-RECONCILE")
    factory = get_session_factory()
    with factory() as session:
        hearing = MatterHearing(
            company_id=company_id,
            matter_id=str(matter["id"]),
            hearing_on=date.today() + timedelta(days=8),
            forum_name="Delhi High Court",
            purpose="Direct raw-claim reconciliation",
        )
        session.add(hearing)
        session.commit()
        hearing_id = hearing.id
    sync_id, connection_id, _marker = _raw_calendar_create_claim_fixture(
        company_id=company_id,
        membership_id=membership_id,
        source_id=hearing_id,
        provider=CalendarProvider.OUTLOOK,
        live=False,
    )
    operation_id = f"calendar_sync:{sync_id}"
    exact = client.get(
        f"/api/admin/provider-operations/jobs/{operation_id}",
        headers=auth_headers(token),
    )
    assert exact.status_code == 200, exact.text
    record = exact.json()
    assert record["status"] == "dead_letter"
    assert record["manual_reconciliation_required"] is True

    reconciled = client.post(
        "/api/admin/provider-operations/jobs/"
        f"{operation_id}/reconcile-calendar-unknown-outcome",
        headers=auth_headers(token),
        json={
            "action": "attest_remote_absence",
            "expected_updated_at": record["updated_at"],
            "expected_status": "dead_letter",
            "expected_dead_letter_reason": CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
            "expected_provider": "outlook",
            "expected_connection_id": connection_id,
            "expected_source_type": "matter_hearing",
            "expected_source_id": hearing_id,
            "evidence_reference": "OUTLOOK-EXACT-SEARCH-RAW-ABSENT-001",
        },
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["operation"]["status"] == "deleted"
    with factory() as session:
        row = session.get(CalendarEventSync, sync_id)
        assert row is not None
        assert row.sync_status == CalendarEventSyncStatus.DELETED
        assert row.dead_letter_reason is None
        assert row.provider_event_id is None


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
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv(
        "CASEOPS_ECOURTSINDIA_API_BASE_URL",
        "https://ecourts-provider.example.test",
    )
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "ecourts-secret-token")
    get_settings.cache_clear()
    try:
        boot = bootstrap_company(client)
        token = str(boot["access_token"])
        blocked_response = client.get(
            "/api/admin/provider-operations/readiness",
            headers=auth_headers(token),
        )
        assert blocked_response.status_code == 200, blocked_response.text
        blocked_ecourts = next(
            row
            for row in blocked_response.json()["providers"]
            if row["provider"] == "ecourtsindia"
        )
        assert blocked_ecourts["state"] == "blocked_missing_config"
        assert blocked_ecourts["required_approval_keys"] == []
        assert blocked_ecourts["missing_approval_keys"] == []
        assert "CASE_TRACKING_SUPPORT_MATRIX_SCOPE" in blocked_ecourts[
            "missing_config_names"
        ]
        with get_session_factory()() as session:
            session.add(
                CaseTrackingSupportMatrix(
                    provider="ecourtsindia",
                    court="Delhi High Court",
                    lookup_method="cnr",
                    legal_tos_status="approved",
                    enabled=True,
                    tenant_visible=True,
                )
            )
            session.commit()

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
        "ecourts-provider.example.test",
        "ecourts-secret-token",
    ):
        assert secret_value not in text
    body = response.json()
    providers = {row["provider"]: row for row in body["providers"]}
    assert set(providers) == {
        "google_drive",
        "email_connector",
        "digest_delivery",
        "ecourtsindia",
        "ipindia-registry",
        "wipo-madrid",
        "indian-kanoon",
    }
    assert providers["google_drive"]["configured"] is True
    assert providers["google_drive"]["enabled"] is False
    assert providers["email_connector"]["external_calls_enabled"] is False
    assert providers["digest_delivery"]["external_calls_enabled"] is False
    assert providers["ecourtsindia"]["state"] == "ready"
    assert providers["ecourtsindia"]["external_calls_enabled"] is True
    assert providers["ecourtsindia"]["required_approval_keys"] == []
    assert providers["ecourtsindia"]["missing_approval_keys"] == []
    assert providers["ecourtsindia"]["adapter_contract"]["domain"] == "court_tracking"
    assert providers["ipindia-registry"]["configured"] is False
    assert providers["ipindia-registry"]["external_calls_enabled"] is False
    assert providers["wipo-madrid"]["configured"] is False
    assert providers["wipo-madrid"]["external_calls_enabled"] is False
    assert providers["wipo-madrid"]["adapter_contract"]["endpoint_paths"] == []
    assert "automated_sync_not_activated" in providers["wipo-madrid"][
        "missing_approval_keys"
    ]
    assert providers["indian-kanoon"]["state"] == "blocked_missing_config"
    assert providers["indian-kanoon"]["external_calls_enabled"] is False
    assert providers["indian-kanoon"]["required_approval_keys"] == []
    assert providers["indian-kanoon"]["missing_approval_keys"] == []
    assert "INDIAN_KANOON_API_TOKEN" in providers["indian-kanoon"][
        "missing_config_names"
    ]
    assert providers["indian-kanoon"]["adapter_contract"]["kill_switch_name"] == (
        "INDIAN_KANOON_ENABLED"
    )
    assert providers["ipindia-registry"]["adapter_contract"][
        "commercial_terms_status"
    ] == "not_approved"
    assert "GOOGLE_DRIVE_CLIENT_SECRET" in providers["google_drive"][
        "required_config_names"
    ]


def test_bounded_batch_replay_rejects_cross_tenant_and_stale_scope(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    operation_ids = [
        "notification_delivery:"
        + _notification_intent_fixture(
            company_id=company_id,
            membership_id=membership_id,
        )
        for _ in range(2)
    ]

    preview = _replay_preview(client, token=token, operation_ids=operation_ids)
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        "/api/admin/provider-operations/jobs/replay",
        headers=auth_headers(token),
        json={
            "reason": "Bounded retry after reviewing both poison rows.",
            "preview_token": preview.json()["preview_token"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["changed_count"] == 2
    assert len(confirmed.json()["operations"]) == 2

    other = _bootstrap_named_company(
        client,
        slug="provider-preview-other",
        email="owner@provider-preview-other.example",
    )
    client.cookies.clear()
    cross_tenant = client.post(
        "/api/admin/provider-operations/jobs/replay",
        headers=auth_headers(str(other["access_token"])),
        json={
            "reason": "Attempt to reuse another tenant preview.",
            "preview_token": preview.json()["preview_token"],
        },
    )
    assert cross_tenant.status_code == 422, cross_tenant.text

    third_id = _notification_intent_fixture(
        company_id=company_id,
        membership_id=membership_id,
    )
    third_operation_id = f"notification_delivery:{third_id}"
    stale_preview = _replay_preview(
        client,
        token=token,
        operation_ids=[third_operation_id],
    )
    assert stale_preview.status_code == 200, stale_preview.text
    factory = get_session_factory()
    with factory() as session:
        intent = session.get(NotificationDeliveryIntent, third_id)
        assert intent is not None
        intent.status = NotificationDeliveryStatus.DELIVERED
        intent.delivered_at = datetime.now(UTC)
        intent.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        session.commit()

    stale = client.post(
        f"/api/admin/provider-operations/jobs/{third_operation_id}/replay",
        headers=auth_headers(token),
        json={
            "reason": "This preview is now stale and must fail.",
            "preview_token": stale_preview.json()["preview_token"],
        },
    )
    assert stale.status_code == 409, stale.text


def test_replay_preview_is_bounded_unique_and_invokes_step_up(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    operation_id = (
        "notification_delivery:"
        + _notification_intent_fixture(
            company_id=company_id,
            membership_id=membership_id,
        )
    )
    duplicate = _replay_preview(
        client,
        token=token,
        operation_ids=[operation_id, operation_id],
    )
    assert duplicate.status_code == 422, duplicate.text
    over_limit = _replay_preview(
        client,
        token=token,
        operation_ids=[f"notification_delivery:{uuid4()}" for _ in range(26)],
    )
    assert over_limit.status_code == 422, over_limit.text

    preview = _replay_preview(client, token=token, operation_ids=[operation_id])
    assert preview.status_code == 200, preview.text
    purposes: list[str] = []

    def capture_step_up(*args, **kwargs) -> None:
        purposes.append(str(kwargs["purpose"]))

    monkeypatch.setattr(
        "caseops_api.services.provider_operations.require_recent_step_up",
        capture_step_up,
    )
    confirmed = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/replay",
        headers=auth_headers(token),
        json={
            "reason": "Replay after bounded preview and step-up check.",
            "preview_token": preview.json()["preview_token"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert purposes == ["provider_operation_replay"]


def test_replay_preview_rejects_tampered_and_expired_tokens(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    intent_id = _notification_intent_fixture(
        company_id=company_id,
        membership_id=membership_id,
    )
    operation_id = f"notification_delivery:{intent_id}"
    preview = _replay_preview(client, token=token, operation_ids=[operation_id])
    assert preview.status_code == 200, preview.text
    preview_token = str(preview.json()["preview_token"])

    tampered = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/replay",
        headers=auth_headers(token),
        json={
            "reason": "A changed signature must never authorize replay.",
            "preview_token": preview_token[:-1] + ("A" if preview_token[-1] != "A" else "B"),
        },
    )
    assert tampered.status_code == 422, tampered.text

    future = datetime.now(UTC) + timedelta(minutes=6)
    monkeypatch.setattr(
        "caseops_api.services.provider_operations._now",
        lambda: future,
    )
    expired = client.post(
        f"/api/admin/provider-operations/jobs/{operation_id}/replay",
        headers=auth_headers(token),
        json={
            "reason": "An expired preview must never authorize replay.",
            "preview_token": preview_token,
        },
    )
    assert expired.status_code == 409, expired.text
    factory = get_session_factory()
    with factory() as session:
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert intent is not None
        assert intent.status == NotificationDeliveryStatus.DEAD_LETTER


def test_unknown_calendar_create_requires_typed_audited_reconciliation(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    matter = _create_matter(client, owner_token, "PROVIDER-UNKNOWN-REC")
    factory = get_session_factory()
    with factory() as session:
        first_hearing = MatterHearing(
            company_id=company_id,
            matter_id=str(matter["id"]),
            hearing_on=date.today() + timedelta(days=7),
            forum_name="Delhi High Court",
            purpose="Arguments",
        )
        second_hearing = MatterHearing(
            company_id=company_id,
            matter_id=str(matter["id"]),
            hearing_on=date.today() + timedelta(days=7),
            forum_name="Delhi High Court",
            purpose="Verified absence",
        )
        session.add_all([first_hearing, second_hearing])
        session.commit()
        first_hearing_id = first_hearing.id
        second_hearing_id = second_hearing.id
    first_id, first_connection_id, first_updated_at = (
        _unknown_calendar_create_fixture(
            company_id=company_id,
            membership_id=membership_id,
            source_id=first_hearing_id,
            provider=CalendarProvider.OUTLOOK,
        )
    )
    second_id, second_connection_id, second_updated_at = (
        _unknown_calendar_create_fixture(
            company_id=company_id,
            membership_id=membership_id,
            source_id=second_hearing_id,
            provider=CalendarProvider.GOOGLE_CALENDAR,
        )
    )
    first_operation_id = f"calendar_sync:{first_id}"

    listing = client.get(
        "/api/admin/provider-operations/jobs",
        headers=auth_headers(owner_token),
    )
    assert listing.status_code == 200, listing.text
    first_record = next(
        row for row in listing.json()["operations"] if row["id"] == first_operation_id
    )
    assert first_record["replay_available"] is False
    assert first_record["manual_reconciliation_required"] is True
    assert (
        first_record["automatic_replay_block_code"]
        == CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE
    )

    preview = _replay_preview(
        client,
        token=owner_token,
        operation_ids=[first_operation_id],
    )
    assert preview.status_code == 409, preview.text
    assert preview.json()["code"] == CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE
    generic_resolution = client.post(
        f"/api/admin/provider-operations/jobs/{first_operation_id}/mark-resolved",
        headers=auth_headers(owner_token),
        json={"reason": "Provider search has not been performed yet."},
    )
    assert generic_resolution.status_code == 409, generic_resolution.text
    assert (
        generic_resolution.json()["code"]
        == CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE
    )

    create_member = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Reconciliation Member",
            "email": "reconciliation-member@asterlegal.in",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert create_member.status_code == 200, create_member.text
    member_login = client.post(
        "/api/auth/login",
        json={
            "email": "reconciliation-member@asterlegal.in",
            "password": "MemberPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert member_login.status_code == 200, member_login.text
    member_token = str(member_login.json()["access_token"])
    attach_payload = {
        "action": "attach_remote_event",
        "expected_updated_at": first_updated_at.isoformat(),
        "expected_status": "dead_letter",
        "expected_dead_letter_reason": CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
        "expected_provider": "outlook",
        "expected_connection_id": first_connection_id,
        "expected_source_type": "matter_hearing",
        "expected_source_id": first_hearing_id,
        "evidence_reference": "OUTLOOK-SEARCH-2026-08-17-001",
        "provider_event_id": "verified-outlook-event-id",
    }
    denied = client.post(
        f"/api/admin/provider-operations/jobs/{first_operation_id}/reconcile-calendar-unknown-outcome",
        headers=auth_headers(member_token),
        json=attach_payload,
    )
    assert denied.status_code == 403, denied.text

    client.cookies.clear()
    stale_payload = {
        **attach_payload,
        "expected_updated_at": (
            first_updated_at - timedelta(seconds=1)
        ).isoformat(),
    }
    stale = client.post(
        f"/api/admin/provider-operations/jobs/{first_operation_id}/reconcile-calendar-unknown-outcome",
        headers=auth_headers(owner_token),
        json=stale_payload,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "calendar_reconciliation_stale_state"

    attached = client.post(
        f"/api/admin/provider-operations/jobs/{first_operation_id}/reconcile-calendar-unknown-outcome",
        headers=auth_headers(owner_token),
        json=attach_payload,
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["operation"]["status"] == "delete_pending"
    assert attached.json()["operation"]["replay_available"] is False

    bad_state = client.post(
        f"/api/admin/provider-operations/jobs/{first_operation_id}/reconcile-calendar-unknown-outcome",
        headers=auth_headers(owner_token),
        json={
            **attach_payload,
            "expected_updated_at": attached.json()["operation"]["updated_at"],
            "expected_status": "delete_pending",
            "expected_dead_letter_reason": (
                "manual_reconciliation_remote_event_attached"
            ),
        },
    )
    assert bad_state.status_code == 409, bad_state.text
    assert bad_state.json()["code"] == "calendar_reconciliation_invalid_state"

    absence_operation_id = f"calendar_sync:{second_id}"
    absence = client.post(
        f"/api/admin/provider-operations/jobs/{absence_operation_id}/reconcile-calendar-unknown-outcome",
        headers=auth_headers(owner_token),
        json={
            "action": "attest_remote_absence",
            "expected_updated_at": second_updated_at.isoformat(),
            "expected_status": "dead_letter",
            "expected_dead_letter_reason": CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
            "expected_provider": "google_calendar",
            "expected_connection_id": second_connection_id,
            "expected_source_type": "matter_hearing",
            "expected_source_id": second_hearing_id,
            "evidence_reference": "GOOGLE-SEARCH-2026-08-17-ABSENT",
        },
    )
    assert absence.status_code == 200, absence.text
    assert absence.json()["operation"]["status"] == "deleted"

    factory = get_session_factory()
    with factory() as session:
        attached_row = session.get(CalendarEventSync, first_id)
        absence_row = session.get(CalendarEventSync, second_id)
        absence_connection = session.get(
            UserCalendarConnection, second_connection_id
        )
        assert attached_row is not None
        assert attached_row.provider_event_id == "verified-outlook-event-id"
        assert absence_row is not None
        assert absence_row.dead_letter_reason is None
        assert absence_connection is not None
        assert absence_connection.encrypted_token_ref is None
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action
                    == "calendar.sync.unknown_outcome_reconciled",
                )
            )
        )
        assert len(audits) == 2
        audit_metadata = [json.loads(row.metadata_json or "{}") for row in audits]
        assert {
            row["evidence_reference"] for row in audit_metadata
        } == {
            "OUTLOOK-SEARCH-2026-08-17-001",
            "GOOGLE-SEARCH-2026-08-17-ABSENT",
        }


def test_connector_health_fails_closed_without_recent_success_and_serializes_kind(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    now = datetime.now(UTC)
    factory = get_session_factory()
    with factory() as session:
        session.add_all(
            [
                ConnectorHealthRecord(
                    company_id=company_id,
                    provider="stale_provider",
                    account_ref_hash="stale",
                    configured_state=ConnectorHealthStatus.CONFIGURED,
                    connected_state=ConnectorHealthStatus.CONNECTED,
                    last_success_at=now - timedelta(days=2),
                    last_checked_at=now,
                ),
                ConnectorHealthRecord(
                    company_id=company_id,
                    provider="never_provider",
                    account_ref_hash="never",
                    configured_state=ConnectorHealthStatus.CONFIGURED,
                    connected_state=ConnectorHealthStatus.DEGRADED,
                    error_category="timeout with hidden@example.test",
                    last_failure_at=now,
                    last_checked_at=now,
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(
        "caseops_api.services.connector_health.refresh_connector_health_records",
        lambda session, context: [],
    )
    health = client.get(
        "/api/admin/integrations/health",
        headers=auth_headers(token),
    )
    assert health.status_code == 200, health.text
    rows = {row["provider"]: row for row in health.json()["health"]}
    assert rows["stale_provider"]["freshness_state"] == "stale"
    assert rows["stale_provider"]["operational_state"] == "unhealthy"
    assert rows["never_provider"]["freshness_state"] == "never_succeeded"
    assert rows["never_provider"]["response_class"] == "timeout"
    assert rows["never_provider"]["operator_attention_required"] is True
    assert "hidden@example.test" not in health.text

    operations = client.get(
        "/api/admin/provider-operations/jobs",
        headers=auth_headers(token),
    )
    assert operations.status_code == 200, operations.text
    connector = next(
        row for row in operations.json()["operations"] if row["job_kind"] == "connector_health"
    )
    assert connector["response_class"] == "timeout"
    assert connector["correlation_ref"].startswith("id:")
