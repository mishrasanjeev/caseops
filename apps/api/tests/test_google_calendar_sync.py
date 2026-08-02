"""BUG-053 (Hari 2026-06-08) - Google Calendar V1.

Regression coverage for the production-safe Google Calendar slice. The tests
use a local provider double only; they never call Google APIs.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import object_session

from caseops_api.db.models import (
    AuditEvent,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProvider,
    Company,
    CompanyMembership,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.calendar_sync import (
    GOOGLE_CALENDAR_SCOPES,
    process_calendar_deletion_tombstones,
    set_google_calendar_provider_for_tests,
    sync_hearing_to_google_calendar,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company
from tests.test_legalworkspace_calendar_sync import (
    _auth,
    _bootstrap_company,
    _create_matter,
    _schedule_hearing,
)


class StubGoogleCalendarProvider:
    def __init__(
        self,
        *,
        fail: bool = False,
        fail_message: str = "google provider unavailable",
    ) -> None:
        self.fail = fail
        self.fail_message = fail_message
        self.calls: list[dict[str, object]] = []
        self.delete_calls: list[str] = []

    @property
    def configured(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    def authorization_url(self, *, state: str) -> str:
        return f"https://accounts.google.example.test/oauth?state={state}"

    def exchange_code(self, *, code: str) -> dict[str, object]:
        assert code == "google-oauth-code"
        return {
            "token_payload": {
                "access_token": "google-access-credential",
                "refresh_token": "google-refresh-credential",
            },
            "provider_account_id": "google-user-1",
            "display_email": "lawyer@gmail.example",
            "scopes": list(GOOGLE_CALENDAR_SCOPES),
        }

    def upsert_hearing_event(
        self,
        *,
        token_payload: dict[str, object],
        hearing,
        matter,
        existing_provider_event_id: str | None,
    ) -> str:
        if self.fail:
            raise RuntimeError(self.fail_message)
        assert token_payload["access_token"] == "google-access-credential"
        self.calls.append(
            {
                "hearing_id": hearing.id,
                "matter_id": matter.id,
                "existing": existing_provider_event_id,
            }
        )
        return existing_provider_event_id or f"google-event-{len(self.calls)}"

    def upsert_calendar_item(
        self,
        *,
        token_payload: dict[str, object],
        item,
        existing_provider_event_id: str | None,
    ) -> str:
        if self.fail:
            raise RuntimeError(self.fail_message)
        assert token_payload["access_token"] == "google-access-credential"
        self.calls.append(
            {
                "source_type": item.source_type,
                "source_id": item.source_id,
                "matter_id": item.matter.id,
                "existing": existing_provider_event_id,
            }
        )
        return existing_provider_event_id or f"google-event-{len(self.calls)}"

    def validate_connection(self, *, token_payload: dict[str, object]) -> dict[str, object]:
        assert token_payload["access_token"] == "google-access-credential"
        return {
            "provider_account_id": "google-user-1",
            "display_email": "lawyer@gmail.example",
        }

    def delete_event(
        self,
        *,
        token_payload: dict[str, object],
        provider_event_id: str,
    ) -> None:
        if self.fail:
            raise RuntimeError(self.fail_message)
        assert token_payload["access_token"] == "google-access-credential"
        self.delete_calls.append(provider_event_id)


class MissingGoogleCalendarProvider:
    @property
    def configured(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return "Google Calendar OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:  # pragma: no cover
        raise AssertionError("unavailable provider should not build auth URLs")

    def exchange_code(self, *, code: str) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("unavailable provider should not exchange codes")

    def upsert_hearing_event(self, **kwargs) -> str:  # pragma: no cover
        raise AssertionError("unavailable provider should not sync")

    def validate_connection(self, **kwargs) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("unavailable provider should not validate")

    def delete_event(self, **kwargs) -> None:  # pragma: no cover
        raise AssertionError("unavailable provider should not delete")


def _bounded_range() -> dict[str, str]:
    today = date.today()
    return {
        "from": (today - timedelta(days=1)).isoformat(),
        "to": (today + timedelta(days=30)).isoformat(),
    }


def _connect_google(
    client: TestClient,
    token: str,
    provider: StubGoogleCalendarProvider,
) -> str:
    set_google_calendar_provider_for_tests(provider)
    start = client.post(
        "/api/calendar/connections/google-calendar/start",
        headers=_auth(token),
    )
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["provider"] == "google_calendar"
    assert body["provider_available"] is True
    assert "google-access-credential" not in start.text
    state = parse_qs(urlparse(body["auth_url"]).query)["state"][0]

    callback = client.get(
        "/api/calendar/connections/google-calendar/callback",
        headers=_auth(token),
        params={"code": "google-oauth-code", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["provider"] == "google_calendar"
    assert callback.json()["connection"]["provider"] == "google_calendar"
    assert "google-access-credential" not in callback.text
    assert "google-refresh-credential" not in callback.text
    return callback.json()["connection"]["id"]


def test_google_calendar_connection_start_callback_revoke_store_no_raw_tokens(
    client: TestClient,
    monkeypatch,
) -> None:
    provider = StubGoogleCalendarProvider()
    purposes: list[str] = []
    monkeypatch.setattr(
        "caseops_api.api.routes.calendar.require_recent_step_up",
        lambda *args, **kwargs: purposes.append(kwargs["purpose"]),
    )
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        connection_id = _connect_google(client, token, provider)

        factory = get_session_factory()
        with factory() as session:
            connection = session.get(UserCalendarConnection, connection_id)
            assert connection is not None
            assert connection.provider == CalendarProvider.GOOGLE_CALENDAR
            assert connection.status == "connected"
            assert connection.encrypted_token_ref is not None
            assert connection.encrypted_token_ref.startswith("fernet:")
            assert "google-access-credential" not in connection.encrypted_token_ref
            assert "google-refresh-credential" not in connection.encrypted_token_ref

        listed = client.get("/api/calendar/connections", headers=_auth(token))
        assert listed.status_code == 200, listed.text
        assert listed.json()["connections"][0]["provider"] == "google_calendar"
        assert listed.json()["connections"][0]["display_email"] == ("lawyer@gmail.example")
        assert "google-access-credential" not in listed.text

        revoked = client.delete(
            f"/api/calendar/connections/{connection_id}",
            headers=_auth(token),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["provider"] == "google_calendar"
        assert revoked.json()["status"] == "revoked"
        assert "google-access-credential" not in revoked.text
        assert purposes == ["connector_disconnect"]
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_calendar_start_reports_safe_unavailable_state(
    client: TestClient,
) -> None:
    try:
        set_google_calendar_provider_for_tests(MissingGoogleCalendarProvider())
        bootstrap = bootstrap_company(client)
        response = client.post(
            "/api/calendar/connections/google-calendar/start",
            headers=_auth(str(bootstrap["access_token"])),
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "provider": "google_calendar",
            "provider_available": False,
            "auth_url": None,
            "unavailable_reason": "Google Calendar OAuth is not configured.",
        }
    finally:
        set_google_calendar_provider_for_tests(None)


def test_sync_status_reports_google_config_names_without_tokens(
    client: TestClient,
) -> None:
    try:
        set_google_calendar_provider_for_tests(MissingGoogleCalendarProvider())
        bootstrap = bootstrap_company(client)
        response = client.get(
            "/api/calendar/sync-status",
            headers=_auth(str(bootstrap["access_token"])),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        provider_config = {item["provider"]: item for item in body["provider_config"]}
        assert provider_config["google_calendar"]["configured"] is False
        assert provider_config["google_calendar"]["missing_config_names"] == [
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REDIRECT_URI",
        ]
        assert "google-access-credential" not in response.text
        assert "google-refresh-credential" not in response.text
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_calendar_manual_hearing_sync_is_idempotent_and_audited(
    client: TestClient,
) -> None:
    provider = StubGoogleCalendarProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "BUG-053-GSYNC")
        hearing = _schedule_hearing(client, token, str(matter["id"]))

        first = client.post(
            f"/api/calendar/sync/google-calendar/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert first.status_code == 200, first.text
        assert first.json()["sync"]["sync_status"] == "synced"
        assert first.json()["sync"]["provider_event_id"] == "google-event-1"

        second = client.post(
            f"/api/calendar/sync/google-calendar/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert second.status_code == 200, second.text
        assert second.json()["sync"]["provider_event_id"] == "google-event-1"
        assert provider.calls[1]["existing"] == "google-event-1"

        deleted = client.delete(
            f"/api/calendar/sync/google-calendar/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["sync"]["sync_status"] == "deleted"
        assert deleted.json()["sync"]["provider_event_id"] == "google-event-1"
        assert provider.delete_calls == ["google-event-1"]

        second_delete = client.delete(
            f"/api/calendar/sync/google-calendar/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert second_delete.status_code == 200, second_delete.text
        assert second_delete.json()["sync"]["sync_status"] == "deleted"
        assert provider.delete_calls == ["google-event-1"]

        factory = get_session_factory()
        with factory() as session:
            rows = list(session.scalars(select(CalendarEventSync)))
            assert len(rows) == 1
            assert rows[0].connection.provider == CalendarProvider.GOOGLE_CALENDAR
            assert rows[0].sync_status == CalendarEventSyncStatus.DELETED
            audits = list(
                session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.action.in_(("calendar.sync.succeeded", "calendar.sync.deleted"))
                    )
                    .order_by(AuditEvent.created_at.asc())
                )
            )
            assert len(audits) == 3
            metadata = json.dumps([json.loads(event.metadata_json or "{}") for event in audits])
            assert "google_calendar" in metadata
            assert "google-access-credential" not in metadata

        status = client.get("/api/calendar/sync-status", headers=_auth(token))
        assert status.status_code == 200, status.text
        assert status.json()["connections"][0]["provider"] == "google_calendar"
        assert status.json()["syncs"][0]["source_id"] == hearing["id"]
        assert "google-access-credential" not in status.text
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_calendar_synced_hearing_is_deleted_when_hearing_is_cancelled(
    client: TestClient,
) -> None:
    provider = StubGoogleCalendarProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "BUG-053-CANCEL")
        hearing = _schedule_hearing(client, token, str(matter["id"]))

        synced = client.post(
            f"/api/calendar/sync/google-calendar/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert synced.status_code == 200, synced.text
        assert synced.json()["sync"]["provider_event_id"] == "google-event-1"

        cancelled = client.patch(
            f"/api/matters/{matter['id']}/hearings/{hearing['id']}",
            headers=_auth(token),
            json={"status": "cancelled"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert provider.delete_calls == ["google-event-1"]

        factory = get_session_factory()
        with factory() as session:
            sync_row = session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_id == hearing["id"],
                    CalendarEventSync.provider_event_id == "google-event-1",
                )
            )
            assert sync_row is not None
            assert sync_row.sync_status == CalendarEventSyncStatus.DELETED
            audit = session.scalar(
                select(AuditEvent)
                .where(AuditEvent.action == "calendar.sync.auto_deleted")
                .order_by(AuditEvent.created_at.desc())
            )
            assert audit is not None
            metadata = json.loads(audit.metadata_json or "{}")
            assert metadata["provider"] == "google_calendar"
            assert "google-access-credential" not in audit.metadata_json
    finally:
        set_google_calendar_provider_for_tests(None)


def test_disposal_enqueues_and_drains_provider_deletion_tombstone(
    client: TestClient,
) -> None:
    provider = StubGoogleCalendarProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "BUG-053-DISPOSAL-TOMBSTONE")
        hearing = _schedule_hearing(client, token, str(matter["id"]))
        synced = client.post(
            f"/api/calendar/sync/google-calendar/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert synced.status_code == 200, synced.text

        current = client.get(
            f"/api/matters/{matter['id']}",
            headers=_auth(token),
        ).json()
        disposed = client.patch(
            f"/api/matters/{matter['id']}/lifecycle/status",
            headers=_auth(token),
            json={
                "to_status": "disposed",
                "expected_from_status": current["status"],
                "expected_updated_at": current["updated_at"],
                "reason": "Final order entered and matter file formally closed",
            },
        )
        assert disposed.status_code == 200, disposed.text
        assert provider.delete_calls == []

        factory = get_session_factory()
        with factory() as session:
            sync = session.scalar(
                select(CalendarEventSync).where(CalendarEventSync.source_id == hearing["id"])
            )
            assert sync is not None
            assert sync.sync_status == CalendarEventSyncStatus.DELETE_PENDING
            company = session.get(Company, bootstrap["company"]["id"])
            membership = session.get(
                CompanyMembership,
                bootstrap["membership"]["id"],
            )
            assert company is not None and membership is not None
            result = process_calendar_deletion_tombstones(
                session,
                context=SessionContext(
                    company=company,
                    membership=membership,
                    user=membership.user,
                ),
                calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
            )
            assert result.deleted == 1

        assert provider.delete_calls == ["google-event-1"]
        with factory() as session:
            sync = session.scalar(
                select(CalendarEventSync).where(CalendarEventSync.source_id == hearing["id"])
            )
            assert sync is not None
            assert sync.sync_status == CalendarEventSyncStatus.DELETED
    finally:
        set_google_calendar_provider_for_tests(None)


def test_provider_upsert_cannot_overwrite_lifecycle_change_with_synced(
    client: TestClient,
) -> None:
    class LifecycleChangingProvider(StubGoogleCalendarProvider):
        def upsert_hearing_event(self, **kwargs) -> str:
            provider_event_id = super().upsert_hearing_event(**kwargs)
            matter = kwargs["matter"]
            matter.status = "disposed"
            matter.is_active = False
            matter.lifecycle_version += 1
            lifecycle_session = object_session(matter)
            assert lifecycle_session is not None
            lifecycle_session.commit()
            return provider_event_id

    provider = LifecycleChangingProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "BUG-053-INFLIGHT-DISPOSAL")
        hearing = _schedule_hearing(client, token, str(matter["id"]))

        factory = get_session_factory()
        with factory() as session:
            company = session.get(Company, bootstrap["company"]["id"])
            membership = session.get(
                CompanyMembership,
                bootstrap["membership"]["id"],
            )
            assert company is not None and membership is not None
            response = sync_hearing_to_google_calendar(
                session,
                context=SessionContext(
                    company=company,
                    membership=membership,
                    user=membership.user,
                ),
                hearing_id=str(hearing["id"]),
            )
            assert response.sync.sync_status == CalendarEventSyncStatus.DELETED

        assert provider.delete_calls == ["google-event-1"]
        with factory() as session:
            sync = session.scalar(
                select(CalendarEventSync).where(CalendarEventSync.source_id == hearing["id"])
            )
            assert sync is not None
            assert sync.sync_status == CalendarEventSyncStatus.DELETED
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_calendar_syncs_tasks_and_deadlines_without_exposing_tokens(
    client: TestClient,
) -> None:
    provider = StubGoogleCalendarProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "BUG-053-SOURCES")

        task = client.post(
            f"/api/matters/{matter['id']}/tasks",
            headers=_auth(token),
            json={
                "title": "File rejoinder",
                "due_on": (date.today() + timedelta(days=5)).isoformat(),
                "priority": "high",
            },
        )
        assert task.status_code == 200, task.text
        deadline = client.post(
            f"/api/matters/{matter['id']}/deadlines",
            headers=_auth(token),
            json={
                "title": "Reply deadline",
                "due_on": (date.today() + timedelta(days=7)).isoformat(),
                "kind": "reply_affidavit_deadline",
            },
        )
        assert deadline.status_code == 200, deadline.text

        task_sync = client.post(
            f"/api/calendar/sync/google-calendar/tasks/{task.json()['id']}",
            headers=_auth(token),
        )
        assert task_sync.status_code == 200, task_sync.text
        assert task_sync.json()["sync"]["source_type"] == "matter_task"
        assert task_sync.json()["sync"]["sync_status"] == "synced", task_sync.text

        deadline_sync = client.post(
            f"/api/calendar/sync/google-calendar/deadlines/{deadline.json()['id']}",
            headers=_auth(token),
        )
        assert deadline_sync.status_code == 200, deadline_sync.text
        assert deadline_sync.json()["sync"]["source_type"] == "matter_deadline"
        assert deadline_sync.json()["sync"]["sync_status"] == "synced", deadline_sync.text

        assert provider.calls == [
            {
                "source_type": "matter_task",
                "source_id": task.json()["id"],
                "matter_id": matter["id"],
                "existing": None,
            },
            {
                "source_type": "matter_deadline",
                "source_id": deadline.json()["id"],
                "matter_id": matter["id"],
                "existing": None,
            },
        ]
        combined = task_sync.text + deadline_sync.text
        assert "google-access-credential" not in combined
        assert "google-refresh-credential" not in combined
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_calendar_bulk_sync_respects_matter_filter_and_tenant_scope(
    client: TestClient,
) -> None:
    provider = StubGoogleCalendarProvider()
    try:
        boot_a = _bootstrap_company(
            client,
            slug="bug-053-a",
            email="owner-a@bug-053.example",
        )
        token_a = str(boot_a["access_token"])
        _connect_google(client, token_a, provider)
        matter_a1 = _create_matter(client, token_a, "BUG-053-A1")
        matter_a2 = _create_matter(client, token_a, "BUG-053-A2")
        hearing_a1 = _schedule_hearing(client, token_a, str(matter_a1["id"]))
        _schedule_hearing(client, token_a, str(matter_a2["id"]))

        boot_b = _bootstrap_company(
            client,
            slug="bug-053-b",
            email="owner-b@bug-053.example",
        )
        token_b = str(boot_b["access_token"])
        _connect_google(client, token_b, provider)
        matter_b1 = _create_matter(client, token_b, "BUG-053-B1")
        _schedule_hearing(client, token_b, str(matter_b1["id"]))

        response = client.post(
            "/api/calendar/sync/google-calendar",
            headers=_auth(token_a),
            json={**_bounded_range(), "matter_id": str(matter_a1["id"])},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["examined"] == 1
        assert body["created"] == 1
        assert body["updated"] == 0
        assert body["failed"] == 0
        assert body["skipped"] == 0
        assert body["items"][0]["source_id"] == hearing_a1["id"]
        assert body["items"][0]["matter_id"] == matter_a1["id"]
        assert provider.calls == [
            {
                "hearing_id": hearing_a1["id"],
                "matter_id": matter_a1["id"],
                "existing": None,
            }
        ]
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_calendar_bulk_sync_guards_range_and_missing_connection(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    missing = client.post(
        "/api/calendar/sync/google-calendar",
        headers=_auth(token),
        json={**_bounded_range()},
    )
    assert missing.status_code == 409, missing.text
    assert missing.json()["detail"] == "Google Calendar is not connected."

    provider = StubGoogleCalendarProvider()
    try:
        _connect_google(client, token, provider)
        overlong = client.post(
            "/api/calendar/sync/google-calendar",
            headers=_auth(token),
            json={"from": "2020-01-01", "to": "2025-01-01"},
        )
        assert overlong.status_code == 400, overlong.text
        assert "92 days" in overlong.json()["detail"]
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_calendar_failures_show_in_provider_operations_as_google(
    client: TestClient,
) -> None:
    raw_error = (
        "bearer google-access-credential for lawyer@gmail.example "
        "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    )
    provider = StubGoogleCalendarProvider(fail=True, fail_message=raw_error)
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "BUG-053-OPS")
        hearing = _schedule_hearing(client, token, str(matter["id"]))

        failed = client.post(
            f"/api/calendar/sync/google-calendar/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["sync"]["sync_status"] == "failed"

        ops = client.get(
            "/api/admin/provider-operations/jobs",
            headers=_auth(token),
        )
        assert ops.status_code == 200, ops.text
        body = ops.json()
        assert body["operations"][0]["provider"] == "google_calendar"
        assert body["operations"][0]["job_kind"] == "calendar_sync"
        assert "google-access-credential" not in ops.text
        assert "googleapis.com" not in ops.text

        operation_id = body["operations"][0]["id"]
        resolved = client.post(
            f"/api/admin/provider-operations/jobs/{operation_id}/mark-resolved",
            headers=_auth(token),
            json={"reason": "Handled in Google console."},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["operation"]["provider"] == "google_calendar"

        factory = get_session_factory()
        with factory() as session:
            audit = session.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.action == "provider_operation.mark_resolved",
                    AuditEvent.company_id == str(bootstrap["company"]["id"]),
                )
                .order_by(AuditEvent.created_at.desc())
            )
            assert audit is not None
            metadata = json.loads(audit.metadata_json or "{}")
            assert metadata["provider"] == "google_calendar"
            assert "Handled in Google console." not in audit.metadata_json
    finally:
        set_google_calendar_provider_for_tests(None)


def test_admin_google_calendar_replay_is_local_safe_and_token_safe(
    client: TestClient,
) -> None:
    provider = StubGoogleCalendarProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_google(client, token, provider)

        replay = client.post(
            "/api/admin/google-calendar-sync/replay",
            headers=_auth(token),
            json={"limit": 10},
        )
        assert replay.status_code == 200, replay.text
        body = replay.json()
        assert body["provider"] == "google_calendar"
        assert body["status"] == "processed"
        assert body["examined"] == 0
        assert body["replayed"] == 0
        assert provider.calls == []
        assert "google-access-credential" not in replay.text
        assert "google-refresh-credential" not in replay.text

        factory = get_session_factory()
        with factory() as session:
            audit = session.scalar(
                select(AuditEvent)
                .where(AuditEvent.action == "calendar.durable_google_calendar_sync.replayed")
                .order_by(AuditEvent.created_at.desc())
            )
            assert audit is not None
            metadata = json.loads(audit.metadata_json or "{}")
            assert metadata["provider"] == "google_calendar"
            assert "google-access-credential" not in audit.metadata_json
    finally:
        set_google_calendar_provider_for_tests(None)
