"""BUG-053 (Hari 2026-06-08) - Google Calendar V1.

Regression coverage for the production-safe Google Calendar slice. The tests
use a local provider double only; they never call Google APIs.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import object_session

from caseops_api.db.models import (
    AuditEvent,
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProvider,
    Company,
    CompanyMembership,
    IpDocketRecord,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    MembershipRole,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.calendar_projection_safety import (
    CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE,
    CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
)
from caseops_api.services.calendar_sync import (
    GOOGLE_CALENDAR_SCOPES,
    process_calendar_deletion_tombstones,
    process_durable_google_calendar_sync,
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
        call = {
            "source_type": item.source_type,
            "source_id": item.source_id,
            "matter_id": item.matter.id if item.matter is not None else None,
            "existing": existing_provider_event_id,
        }
        if item.ip_docket is not None:
            call.update(
                {
                    "ip_docket_id": item.ip_docket.id,
                    "title": item.title,
                    "detail_lines": item.detail_lines,
                    "occurs_on": item.occurs_on,
                    "category": item.category,
                    "private_properties": item.private_properties,
                }
            )
        self.calls.append(call)
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


def test_ip_calendar_projection_is_minimal_stable_and_idempotent(
    client: TestClient,
) -> None:
    provider = StubGoogleCalendarProvider()
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    connection_id = _connect_google(client, token, provider)
    try:
        with get_session_factory()() as session:
            docket = IpDocketRecord(
                company_id=company_id,
                record_type="trademark",
                title="Highly confidential acquisition mark",
                status="draft",
                restricted=False,
                created_by_membership_id=membership_id,
            )
            session.add(docket)
            session.commit()
            docket_id = docket.id

        task = client.post(
            "/api/ip/tasks",
            headers=_auth(token),
            json={
                "docket_id": docket_id,
                "title": "Prepare privileged acquisition analysis",
                "due_on": (date.today() + timedelta(days=10)).isoformat(),
                "owner_membership_id": membership_id,
            },
        )
        assert task.status_code == 201, task.text
        task_id = str(task.json()["id"])

        first = client.post(
            f"/api/calendar/sync/google-calendar/tasks/{task_id}",
            headers=_auth(token),
        )
        second = client.post(
            f"/api/calendar/sync/google-calendar/tasks/{task_id}",
            headers=_auth(token),
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["sync"]["provider_event_id"] == second.json()["sync"][
            "provider_event_id"
        ]
        assert len(provider.calls) == 2
        assert provider.calls[0]["existing"] is None
        assert provider.calls[1]["existing"] == first.json()["sync"]["provider_event_id"]
        projection = provider.calls[0]
        assert projection["matter_id"] is None
        assert projection["ip_docket_id"] == docket_id
        assert projection["title"] == "CaseOps IP - Task"
        assert projection["occurs_on"] == date.today() + timedelta(days=10)
        rendered = " ".join(projection["detail_lines"])
        assert "Highly confidential" not in rendered
        assert "privileged acquisition" not in rendered
        assert projection["private_properties"]["caseops_ip_docket_id"] == docket_id

        provider.fail = True
        failed = client.post(
            f"/api/calendar/sync/google-calendar/tasks/{task_id}",
            headers=_auth(token),
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["sync"]["sync_status"] == "failed"
        provider.fail = False
        retried = client.post(
            f"/api/calendar/sync/google-calendar/tasks/{task_id}",
            headers=_auth(token),
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["sync"]["sync_status"] == "synced"
        assert retried.json()["sync"]["provider_event_id"] == first.json()["sync"][
            "provider_event_id"
        ]
        canonical_task = client.get(
            f"/api/ip/tasks?docket_id={docket_id}",
            headers=_auth(token),
        )
        assert canonical_task.status_code == 200, canonical_task.text
        assert canonical_task.json()["tasks"][0]["due_on"] == (
            date.today() + timedelta(days=10)
        ).isoformat()

        with get_session_factory()() as session:
            rows = list(
                session.scalars(
                    select(CalendarEventSync).where(
                        CalendarEventSync.source_type == "matter_task",
                        CalendarEventSync.source_id == task_id,
                    )
                )
            )
            assert len(rows) == 1

        hearing_date = date.today() + timedelta(days=15)
        hearing = client.post(
            "/api/ip/hearings",
            headers=_auth(token),
            json={
                "docket_id": docket_id,
                "hearing_on": hearing_date.isoformat(),
                "forum_name": "Trade Marks Registry",
                "purpose": "Confidential hearing purpose",
                "time_status": "time_not_published",
                "responsible_membership_id": membership_id,
            },
        )
        assert hearing.status_code == 201, hearing.text
        hearing_id = str(hearing.json()["id"])
        projected = client.post(
            f"/api/calendar/sync/google-calendar/hearings/{hearing_id}",
            headers=_auth(token),
        )
        assert projected.status_code == 200, projected.text
        hearing_event_id = projected.json()["sync"]["provider_event_id"]
        hearing_projection = provider.calls[-1]
        assert hearing_projection["title"] == "CaseOps IP - Hearing"
        assert hearing_projection["occurs_on"] == hearing_date
        assert "Confidential hearing purpose" not in " ".join(
            hearing_projection["detail_lines"]
        )

        moved = client.patch(
            f"/api/ip/hearings/{hearing_id}",
            headers=_auth(token),
            json={
                "docket_id": docket_id,
                "hearing_on": (hearing_date + timedelta(days=1)).isoformat(),
            },
        )
        assert moved.status_code == 200, moved.text
        assert provider.calls[-1]["existing"] == hearing_event_id
        assert provider.calls[-1]["source_id"] == hearing_id

        cancelled = client.patch(
            f"/api/ip/hearings/{hearing_id}",
            headers=_auth(token),
            json={"docket_id": docket_id, "status": "cancelled"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert provider.delete_calls == [hearing_event_id]
        with get_session_factory()() as session:
            hearing_sync = session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_type == "matter_hearing",
                    CalendarEventSync.source_id == hearing_id,
                )
            )
            assert hearing_sync is not None
            assert hearing_sync.sync_status == CalendarEventSyncStatus.DELETED

        revoked = client.delete(
            f"/api/calendar/connections/{connection_id}",
            headers=_auth(token),
        )
        assert revoked.status_code == 200, revoked.text
        blocked = client.post(
            f"/api/calendar/sync/google-calendar/tasks/{task_id}",
            headers=_auth(token),
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"] == "Google Calendar is not connected."
        with get_session_factory()() as session:
            task_sync = session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_type == "matter_task",
                    CalendarEventSync.source_id == task_id,
                )
            )
            assert task_sync is not None
            assert task_sync.provider_event_id == first.json()["sync"][
                "provider_event_id"
            ]
    finally:
        set_google_calendar_provider_for_tests(None)


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
        # Cancellation commits an exact tombstone; provider I/O is drained
        # only after the lifecycle transaction releases its locks.
        assert provider.delete_calls == []

        factory = get_session_factory()
        with factory() as session:
            sync_row = session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_id == hearing["id"],
                    CalendarEventSync.provider_event_id == "google-event-1",
                )
            )
            assert sync_row is not None
            assert sync_row.sync_status == CalendarEventSyncStatus.DELETE_PENDING
            audit = session.scalar(
                select(AuditEvent)
                .where(AuditEvent.action == "calendar.sync.auto_delete_queued")
                .order_by(AuditEvent.created_at.desc())
            )
            assert audit is not None
            metadata = json.loads(audit.metadata_json or "{}")
            assert metadata["provider"] == "google_calendar"
            assert "google-access-credential" not in audit.metadata_json
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
            sync_row = session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_id == hearing["id"],
                    CalendarEventSync.provider_event_id == "google-event-1",
                )
            )
            assert sync_row is not None
            assert sync_row.sync_status == CalendarEventSyncStatus.DELETED
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
        assert failed.json()["sync"]["sync_status"] == "dead_letter"
        assert (
            failed.json()["sync"]["dead_letter_reason"]
            == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        )

        ops = client.get(
            "/api/admin/provider-operations/jobs",
            headers=_auth(token),
        )
        assert ops.status_code == 200, ops.text
        body = ops.json()
        assert body["operations"][0]["provider"] == "google_calendar"
        assert body["operations"][0]["job_kind"] == "calendar_sync"
        assert body["operations"][0]["replay_available"] is False
        assert body["operations"][0]["manual_reconciliation_required"] is True
        assert "google-access-credential" not in ops.text
        assert "googleapis.com" not in ops.text

        operation_id = body["operations"][0]["id"]
        resolved = client.post(
            f"/api/admin/provider-operations/jobs/{operation_id}/mark-resolved",
            headers=_auth(token),
            json={"reason": "Handled in Google console."},
        )
        assert resolved.status_code == 409, resolved.text
        assert resolved.json()["code"] == CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE

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


@pytest.mark.parametrize("winner", ["revoke", "deactivate", "demote"])
def test_google_oauth_exchange_discards_result_when_authority_changes(
    client: TestClient,
    winner: str,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])

    class AuthorityChangingProvider(StubGoogleCalendarProvider):
        def exchange_code(self, *, code: str) -> dict[str, object]:
            exchanged = super().exchange_code(code=code)
            # The OAuth claim was committed before this callback. A second DB
            # session can therefore win revocation/deactivation/demotion while
            # the external exchange is in flight.
            with get_session_factory()() as concurrent:
                membership = concurrent.get(CompanyMembership, membership_id)
                assert membership is not None
                if winner == "revoke":
                    connection = concurrent.scalar(
                        select(UserCalendarConnection).where(
                            UserCalendarConnection.company_id == company_id,
                            UserCalendarConnection.membership_id == membership_id,
                            UserCalendarConnection.provider
                            == CalendarProvider.GOOGLE_CALENDAR,
                        )
                    )
                    assert connection is not None
                    connection.status = CalendarConnectionStatus.REVOKED
                    connection.encrypted_token_ref = None
                elif winner == "deactivate":
                    membership.is_active = False
                else:
                    membership.role = MembershipRole.VIEWER
                concurrent.commit()
            return exchanged

    provider = AuthorityChangingProvider()
    set_google_calendar_provider_for_tests(provider)
    try:
        start = client.post(
            "/api/calendar/connections/google-calendar/start",
            headers=_auth(token),
        )
        assert start.status_code == 200, start.text
        state = parse_qs(urlparse(start.json()["auth_url"]).query)["state"][0]
        callback = client.get(
            "/api/calendar/connections/google-calendar/callback",
            headers=_auth(token),
            params={"code": "google-oauth-code", "state": state},
        )
        assert callback.status_code in {403, 409}, callback.text
        with get_session_factory()() as session:
            connection = session.scalar(
                select(UserCalendarConnection).where(
                    UserCalendarConnection.company_id == company_id,
                    UserCalendarConnection.membership_id == membership_id,
                    UserCalendarConnection.provider
                    == CalendarProvider.GOOGLE_CALENDAR,
                )
            )
            assert connection is not None
            assert connection.status != CalendarConnectionStatus.CONNECTED
            assert connection.provider_account_id is None
            assert "google-access-credential" not in str(
                connection.encrypted_token_ref or ""
            )
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_reconnect_blocks_different_account_until_exact_delete_drains(
    client: TestClient,
) -> None:
    class AccountProvider(StubGoogleCalendarProvider):
        def __init__(self) -> None:
            super().__init__()
            self.account_id = "google-user-1"
            self.exchange_calls = 0

        def exchange_code(self, *, code: str) -> dict[str, object]:
            self.exchange_calls += 1
            result = super().exchange_code(code=code)
            result["provider_account_id"] = self.account_id
            result["display_email"] = f"{self.account_id}@example.test"
            return result

    provider = AccountProvider()
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    set_google_calendar_provider_for_tests(provider)
    try:
        connection_id = _connect_google(client, token, provider)
        with get_session_factory()() as session:
            session.add(
                CalendarEventSync(
                    company_id=company_id,
                    calendar_connection_id=connection_id,
                    source_type="matter_hearing",
                    source_id=str(uuid4()),
                    provider_event_id="prior-account-event",
                    sync_status=CalendarEventSyncStatus.DELETE_PENDING,
                    dead_letter_reason="connection_revoked_delete",
                )
            )
            session.commit()
        provider.account_id = "google-user-2"
        start = client.post(
            "/api/calendar/connections/google-calendar/start",
            headers=_auth(token),
        )
        state = parse_qs(urlparse(start.json()["auth_url"]).query)["state"][0]
        blocked = client.get(
            "/api/calendar/connections/google-calendar/callback",
            headers=_auth(token),
            params={"code": "google-oauth-code", "state": state},
        )
        assert blocked.status_code == 409, blocked.text
        assert provider.exchange_calls == 1
        with get_session_factory()() as session:
            connection = session.get(UserCalendarConnection, connection_id)
            assert connection is not None
            assert connection.provider_account_id == "google-user-1"
            assert connection.status == CalendarConnectionStatus.CONNECTED
    finally:
        set_google_calendar_provider_for_tests(None)


def test_durable_google_create_timeout_is_unknown_and_never_replayed(
    client: TestClient,
) -> None:
    class AcceptedThenTimeoutProvider(StubGoogleCalendarProvider):
        def upsert_hearing_event(self, **kwargs) -> str:
            self.calls.append(
                {
                    "hearing_id": kwargs["hearing"].id,
                    "matter_id": kwargs["matter"].id,
                    "existing": kwargs["existing_provider_event_id"],
                }
            )
            raise TimeoutError("Google accepted create before response timeout")

    provider = AcceptedThenTimeoutProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        company_id = str(bootstrap["company"]["id"])
        membership_id = str(bootstrap["membership"]["id"])
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "GOOGLE-UNKNOWN-TRANSPORT")
        hearing = _schedule_hearing(client, token, str(matter["id"]))
        factory = get_session_factory()
        with factory() as session:
            company = session.get(Company, company_id)
            membership = session.get(CompanyMembership, membership_id)
            assert company is not None and membership is not None
            context = SessionContext(
                company=company,
                membership=membership,
                user=membership.user,
            )
            first = process_durable_google_calendar_sync(
                session,
                context=context,
                range_from=date.today(),
                range_to=date.today() + timedelta(days=14),
                limit=1,
            )
            second = process_durable_google_calendar_sync(
                session,
                context=context,
                replay_failed_only=True,
                limit=1,
            )
            sync = session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_id == str(hearing["id"])
                )
            )
            assert sync is not None
            assert sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert sync.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        assert first.dead_lettered == 1
        assert second.examined == 0
        assert second.provider_calls == 0
        assert len(provider.calls) == 1
    finally:
        set_google_calendar_provider_for_tests(None)


def test_ordinary_child_terminal_winner_compensates_every_google_create(
    client: TestClient,
) -> None:
    factory = get_session_factory()

    class TerminalizingProvider(StubGoogleCalendarProvider):
        def _terminalize(self, model, source_id: str, terminal_status: str) -> None:
            with factory() as callback_session:
                row = callback_session.get(model, source_id)
                assert row is not None
                row.status = terminal_status
                callback_session.commit()

        def upsert_hearing_event(self, **kwargs) -> str:
            assert object_session(kwargs["hearing"]).in_transaction() is False
            source_id = str(kwargs["hearing"].id)
            self.calls.append({"source_type": "matter_hearing", "source_id": source_id})
            self._terminalize(MatterHearing, source_id, "cancelled")
            return f"stale-hearing-{source_id}"

        def upsert_calendar_item(self, **kwargs) -> str:
            assert object_session(kwargs["item"].matter).in_transaction() is False
            item = kwargs["item"]
            self.calls.append({"source_type": item.source_type, "source_id": item.source_id})
            if item.source_type == "matter_task":
                self._terminalize(MatterTask, item.source_id, "cancelled")
            else:
                self._terminalize(MatterDeadline, item.source_id, "cancelled")
            return f"stale-{item.source_type}-{item.source_id}"

    provider = TerminalizingProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "GOOGLE-CHILD-FENCE")
        hearing = _schedule_hearing(client, token, str(matter["id"]))
        task_response = client.post(
            f"/api/matters/{matter['id']}/tasks",
            headers=_auth(token),
            json={
                "title": "Terminal-race task",
                "due_on": (date.today() + timedelta(days=5)).isoformat(),
                "priority": "high",
            },
        )
        deadline_response = client.post(
            f"/api/matters/{matter['id']}/deadlines",
            headers=_auth(token),
            json={
                "title": "Terminal-race deadline",
                "due_on": (date.today() + timedelta(days=7)).isoformat(),
                "kind": "filing",
            },
        )
        assert task_response.status_code == 200, task_response.text
        assert deadline_response.status_code == 200, deadline_response.text
        sources = (
            ("hearings", str(hearing["id"])),
            ("tasks", str(task_response.json()["id"])),
            ("deadlines", str(deadline_response.json()["id"])),
        )
        for route_part, source_id in sources:
            response = client.post(
                f"/api/calendar/sync/google-calendar/{route_part}/{source_id}",
                headers=_auth(token),
            )
            assert response.status_code == 200, response.text
            assert response.json()["sync"]["sync_status"] == "deleted"
            assert response.json()["sync"]["provider_event_id"] is not None
        assert len(provider.calls) == 3
        assert provider.delete_calls == [
            f"stale-hearing-{sources[0][1]}",
            f"stale-matter_task-{sources[1][1]}",
            f"stale-matter_deadline-{sources[2][1]}",
        ]
    finally:
        set_google_calendar_provider_for_tests(None)


def test_google_upsert_finalize_rechecks_calendar_capability_and_compensates(
    client: TestClient,
) -> None:
    factory = get_session_factory()

    class DemotingProvider(StubGoogleCalendarProvider):
        def __init__(self, *, membership_id: str) -> None:
            super().__init__()
            self.membership_id = membership_id

        def upsert_hearing_event(self, **kwargs) -> str:
            # The claim is durable and the provider call is outside the
            # transaction that locked the actor/source/sync/connection graph.
            assert object_session(kwargs["hearing"]).in_transaction() is False
            source_id = str(kwargs["hearing"].id)
            returned_id = f"demoted-google-{source_id}"
            self.calls.append({"source_type": "matter_hearing", "source_id": source_id})
            with factory() as callback_session:
                membership = callback_session.get(
                    CompanyMembership,
                    self.membership_id,
                )
                assert membership is not None
                membership.role = MembershipRole.VIEWER
                callback_session.commit()
            return returned_id

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    membership_id = str(bootstrap["membership"]["id"])
    provider = DemotingProvider(membership_id=membership_id)
    try:
        _connect_google(client, token, provider)
        matter = _create_matter(client, token, "GOOGLE-CAPABILITY-FINALIZE")
        hearing = _schedule_hearing(client, token, str(matter["id"]))

        response = client.post(
            f"/api/calendar/sync/google-calendar/hearings/{hearing['id']}",
            headers=_auth(token),
        )

        assert response.status_code == 200, response.text
        sync = response.json()["sync"]
        assert sync["sync_status"] == "deleted"
        assert sync["provider_event_id"] == f"demoted-google-{hearing['id']}"
        assert provider.delete_calls == [f"demoted-google-{hearing['id']}"]
        assert len(provider.calls) == 1
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
