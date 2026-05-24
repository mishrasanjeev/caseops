from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    CalendarEventSync,
    InAppNotification,
    MatterCourtOrder,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.calendar_sync import set_outlook_provider_for_tests
from tests.test_auth_company import auth_headers, bootstrap_company


class StubOutlookProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    @property
    def configured(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    def authorization_url(self, *, state: str) -> str:
        return f"https://login.example.test/outlook?state={state}"

    def exchange_code(self, *, code: str) -> dict[str, object]:
        assert code == "oauth-code"
        return {
            "token_payload": {
                "access_token": "raw-access-token",
                "refresh_token": "raw-refresh-token",
            },
            "provider_account_id": "outlook-user-1",
            "display_email": "lawyer@example.test",
            "scopes": ["offline_access", "User.Read", "Calendars.ReadWrite"],
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
            raise RuntimeError("provider unavailable")
        assert token_payload["access_token"] == "raw-access-token"
        self.calls.append(
            {
                "hearing_id": hearing.id,
                "matter_id": matter.id,
                "existing": existing_provider_event_id,
            }
        )
        return existing_provider_event_id or "remote-event-1"


class MissingOutlookProvider:
    @property
    def configured(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return "Microsoft Graph OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:  # pragma: no cover
        raise AssertionError("unavailable provider should not build auth URLs")

    def exchange_code(self, *, code: str) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("unavailable provider should not exchange codes")

    def upsert_hearing_event(self, **kwargs) -> str:  # pragma: no cover
        raise AssertionError("unavailable provider should not sync")


def _auth(token: str) -> dict[str, str]:
    return auth_headers(token)


def _bootstrap_company(
    client: TestClient,
    *,
    slug: str,
    email: str,
) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} Legal",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Calendar Owner",
            "owner_email": email,
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_matter(client: TestClient, token: str, code: str) -> dict[str, object]:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "matter_code": code,
            "title": f"Calendar sync matter {code}",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _schedule_hearing(
    client: TestClient,
    token: str,
    matter_id: str,
    *,
    purpose: str = "Arguments",
) -> dict[str, object]:
    response = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=_auth(token),
        json={
            "hearing_on": (date.today() + timedelta(days=7)).isoformat(),
            "forum_name": "Delhi High Court",
            "judge_name": "Justice Example",
            "purpose": purpose,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _connect_outlook(client: TestClient, token: str, provider: StubOutlookProvider) -> str:
    set_outlook_provider_for_tests(provider)
    start = client.post(
        "/api/calendar/connections/outlook/start",
        headers=_auth(token),
    )
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["provider_available"] is True
    assert "raw-access-token" not in start.text
    state = parse_qs(urlparse(body["auth_url"]).query)["state"][0]
    callback = client.get(
        "/api/calendar/connections/outlook/callback",
        headers=_auth(token),
        params={"code": "oauth-code", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert "raw-access-token" not in callback.text
    return callback.json()["connection"]["id"]


def _seed_order(matter_id: str) -> str:
    factory = get_session_factory()
    with factory() as session:
        order = MatterCourtOrder(
            matter_id=matter_id,
            order_date=date.today(),
            title="Order uploaded",
            summary="Order summary.",
            source="manual-test",
            synced_at=datetime.now(UTC),
        )
        session.add(order)
        session.commit()
        return order.id


def test_outlook_connection_start_callback_revoke_store_no_raw_tokens(
    client: TestClient,
) -> None:
    provider = StubOutlookProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        connection_id = _connect_outlook(client, token, provider)

        factory = get_session_factory()
        with factory() as session:
            connection = session.get(UserCalendarConnection, connection_id)
            assert connection is not None
            assert connection.status == "connected"
            assert connection.encrypted_token_ref is not None
            assert connection.encrypted_token_ref.startswith("fernet:")
            assert "raw-access-token" not in connection.encrypted_token_ref
            assert "raw-refresh-token" not in connection.encrypted_token_ref

        listed = client.get("/api/calendar/connections", headers=_auth(token))
        assert listed.status_code == 200, listed.text
        assert listed.json()["connections"][0]["display_email"] == "lawyer@example.test"
        assert "raw-access-token" not in listed.text

        revoked = client.delete(
            f"/api/calendar/connections/{connection_id}",
            headers=_auth(token),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"
    finally:
        set_outlook_provider_for_tests(None)


def test_outlook_start_reports_safe_unavailable_state(client: TestClient) -> None:
    try:
        set_outlook_provider_for_tests(MissingOutlookProvider())
        bootstrap = bootstrap_company(client)
        response = client.post(
            "/api/calendar/connections/outlook/start",
            headers=_auth(str(bootstrap["access_token"])),
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "provider": "outlook",
            "provider_available": False,
            "auth_url": None,
            "unavailable_reason": "Microsoft Graph OAuth is not configured.",
        }
    finally:
        set_outlook_provider_for_tests(None)


def test_sync_status_reports_bounded_manual_state_and_missing_config_names(
    client: TestClient,
) -> None:
    try:
        set_outlook_provider_for_tests(MissingOutlookProvider())
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        response = client.get("/api/calendar/sync-status", headers=_auth(token))
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["provider_available"] is False
        assert body["durable_automation"] == "blocked_pending_temporal"
        assert body["notification_delivery"] == "pending_wtd_5_3"
        assert body["capabilities"] == {
            "sync_mode": "manual_bounded",
            "manual_sync_available": False,
            "durable_automation": "blocked_pending_temporal",
            "notification_delivery": "pending_wtd_5_3",
            "email_invitation_candidates": "review_queue_available",
        }
        assert body["provider_config"] == [
            {
                "provider": "outlook",
                "configured": False,
                "missing_config_names": [
                    "OUTLOOK_CLIENT_ID",
                    "OUTLOOK_CLIENT_SECRET",
                    "OUTLOOK_REDIRECT_URI",
                ],
            }
        ]
        assert body["conflict_summary"] == {
            "has_conflicts": False,
            "candidate_count": 0,
            "duplicate_provider_event_count": 0,
            "changed_event_candidate_count": 0,
            "changed_event_detection": "unsupported_no_provider_snapshot",
        }
        assert body["conflict_candidates"] == []
        assert "raw-access-token" not in response.text
        assert "raw-refresh-token" not in response.text
    finally:
        set_outlook_provider_for_tests(None)


def test_manual_hearing_sync_is_idempotent_and_audited(client: TestClient) -> None:
    provider = StubOutlookProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_outlook(client, token, provider)
        matter = _create_matter(client, token, "LW-S10-SYNC")
        hearing = _schedule_hearing(client, token, str(matter["id"]))

        first = client.post(
            f"/api/calendar/sync/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert first.status_code == 200, first.text
        assert first.json()["sync"]["sync_status"] == "synced"
        second = client.post(
            f"/api/calendar/sync/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert second.status_code == 200, second.text
        assert second.json()["sync"]["provider_event_id"] == "remote-event-1"
        assert provider.calls[1]["existing"] == "remote-event-1"

        status = client.get("/api/calendar/sync-status", headers=_auth(token))
        assert status.status_code == 200, status.text
        assert status.json()["syncs"][0]["source_id"] == hearing["id"]
        assert status.json()["capabilities"]["sync_mode"] == "manual_bounded"

        factory = get_session_factory()
        with factory() as session:
            rows = list(session.scalars(select(CalendarEventSync)))
            assert len(rows) == 1
            audits = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "calendar.sync.succeeded"
                    )
                )
            )
            assert len(audits) == 2
    finally:
        set_outlook_provider_for_tests(None)


def test_sync_status_reports_duplicate_provider_event_conflict_candidate(
    client: TestClient,
) -> None:
    provider = StubOutlookProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        connection_id = _connect_outlook(client, token, provider)
        matter = _create_matter(client, token, "LW-S10-CONFLICT")
        first_hearing = _schedule_hearing(client, token, str(matter["id"]))
        second_hearing = _schedule_hearing(
            client,
            token,
            str(matter["id"]),
            purpose="Second listing",
        )

        first = client.post(
            f"/api/calendar/sync/hearings/{first_hearing['id']}",
            headers=_auth(token),
        )
        assert first.status_code == 200, first.text
        provider_event_id = first.json()["sync"]["provider_event_id"]

        factory = get_session_factory()
        with factory() as session:
            connection = session.get(UserCalendarConnection, connection_id)
            assert connection is not None
            duplicate = CalendarEventSync(
                company_id=connection.company_id,
                calendar_connection_id=connection.id,
                source_type="matter_hearing",
                source_id=str(second_hearing["id"]),
                provider_event_id=provider_event_id,
                sync_status="synced",
                last_synced_at=datetime.now(UTC),
            )
            session.add(duplicate)
            session.commit()

        response = client.get("/api/calendar/sync-status", headers=_auth(token))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["conflict_summary"]["has_conflicts"] is True
        assert body["conflict_summary"]["candidate_count"] == 1
        assert body["conflict_summary"]["duplicate_provider_event_count"] == 1
        assert body["conflict_summary"]["changed_event_detection"] == (
            "unsupported_no_provider_snapshot"
        )
        candidate = body["conflict_candidates"][0]
        assert candidate["conflict_type"] == "duplicate_provider_event_id"
        assert candidate["duplicate_count"] == 2
        assert candidate["provider_event_id"] == provider_event_id
        assert sorted(candidate["source_ids"]) == sorted(
            [first_hearing["id"], second_hearing["id"]]
        )
        assert "raw-access-token" not in response.text
        assert "raw-refresh-token" not in response.text
    finally:
        set_outlook_provider_for_tests(None)


def test_manual_hearing_sync_failure_persists_safe_status(
    client: TestClient,
) -> None:
    provider = StubOutlookProvider(fail=True)
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _connect_outlook(client, token, provider)
        matter = _create_matter(client, token, "LW-S10-FAIL")
        hearing = _schedule_hearing(client, token, str(matter["id"]))

        response = client.post(
            f"/api/calendar/sync/hearings/{hearing['id']}",
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        body = response.json()["sync"]
        assert body["sync_status"] == "failed"
        assert body["last_error"] == "provider unavailable"
        assert "raw-access-token" not in response.text
    finally:
        set_outlook_provider_for_tests(None)


def test_calendar_openapi_exposes_no_autonomous_sync_routes(
    client: TestClient,
) -> None:
    calendar_paths = {
        path
        for path in client.get("/openapi.json").json()["paths"]
        if path.startswith("/api/calendar")
    }
    joined = " ".join(sorted(calendar_paths)).lower()
    assert "webhook" not in joined
    assert "poll" not in joined
    assert "sweep" not in joined


def test_sync_denies_ethically_walled_matter_hearing(client: TestClient) -> None:
    provider = StubOutlookProvider()
    try:
        bootstrap = bootstrap_company(client)
        owner_token = str(bootstrap["access_token"])
        company_slug = str(bootstrap["company"]["slug"])
        member = client.post(
            "/api/companies/current/users",
            headers=_auth(owner_token),
            json={
                "full_name": "Walled Member",
                "email": "walled-sync@caseops-test.in",
                "role": "member",
                "password": "MemberPass123!",
            },
        )
        assert member.status_code == 200, member.text
        login = client.post(
            "/api/auth/login",
            json={
                "company_slug": company_slug,
                "email": "walled-sync@caseops-test.in",
                "password": "MemberPass123!",
            },
        )
        assert login.status_code == 200, login.text
        member_token = str(login.json()["access_token"])
        _connect_outlook(client, member_token, provider)
        matter = _create_matter(client, owner_token, "LW-S10-WALL")
        hearing = _schedule_hearing(client, owner_token, str(matter["id"]))

        wall = client.post(
            f"/api/matters/{matter['id']}/access/walls",
            headers=_auth(owner_token),
            json={"excluded_membership_id": member.json()["membership_id"], "reason": "Conflict"},
        )
        assert wall.status_code == 200, wall.text
        denied = client.post(
            f"/api/calendar/sync/hearings/{hearing['id']}",
            headers=_auth(member_token),
        )
        assert denied.status_code == 404, denied.text
        assert provider.calls == []
    finally:
        set_outlook_provider_for_tests(None)


def test_notification_rule_crud_is_permission_and_tenant_scoped(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    create = client.post(
        "/api/notification-rules",
        headers=_auth(owner_token),
        json={
            "scope_type": "company",
            "event_type": "new_order_uploaded",
            "channels": ["in_app"],
            "enabled": True,
        },
    )
    assert create.status_code == 200, create.text
    rule_id = create.json()["id"]

    listed = client.get("/api/notification-rules", headers=_auth(owner_token))
    assert listed.status_code == 200, listed.text
    assert listed.json()["durable_delivery"] == "blocked_pending_temporal"
    assert [row["id"] for row in listed.json()["rules"]] == [rule_id]

    member = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": "Member",
            "email": "member-notify@caseops-test.in",
            "role": "member",
            "password": "MemberPass123!",
        },
    )
    assert member.status_code == 200, member.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": str(bootstrap["company"]["slug"]),
            "email": "member-notify@caseops-test.in",
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    forbidden = client.get(
        "/api/notification-rules",
        headers=_auth(str(login.json()["access_token"])),
    )
    assert forbidden.status_code == 403

    other = _bootstrap_company(
        client,
        slug="lw-s10-other",
        email="owner@lw-s10-other.example",
    )
    cross = client.patch(
        f"/api/notification-rules/{rule_id}",
        headers=_auth(str(other["access_token"])),
        json={"enabled": False},
    )
    assert cross.status_code == 404

    patch = client.patch(
        f"/api/notification-rules/{rule_id}",
        headers=_auth(owner_token),
        json={"enabled": False},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["enabled"] is False
    delete = client.delete(
        f"/api/notification-rules/{rule_id}",
        headers=_auth(owner_token),
    )
    assert delete.status_code == 204, delete.text


def test_notification_rule_patch_distinguishes_null_scope_from_omitted(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, "LW-S10-RULE-SCOPE")
    create = client.post(
        "/api/notification-rules",
        headers=_auth(token),
        json={
            "scope_type": "matter",
            "scope_id": matter["id"],
            "event_type": "new_order_uploaded",
            "channels": ["in_app"],
            "enabled": True,
        },
    )
    assert create.status_code == 200, create.text
    rule_id = create.json()["id"]

    omitted = client.patch(
        f"/api/notification-rules/{rule_id}",
        headers=_auth(token),
        json={"enabled": False},
    )
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["scope_type"] == "matter"
    assert omitted.json()["scope_id"] == matter["id"]
    assert omitted.json()["enabled"] is False

    cleared = client.patch(
        f"/api/notification-rules/{rule_id}",
        headers=_auth(token),
        json={"scope_type": "company", "scope_id": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["scope_type"] == "company"
    assert cleared.json()["scope_id"] is None


def test_new_order_upload_creates_in_app_notification_when_rule_enabled(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, "notify-matter")
    order_id = _seed_order(str(matter["id"]))
    rule = client.post(
        "/api/notification-rules",
        headers=_auth(token),
        json={
            "scope_type": "company",
            "event_type": "new_order_uploaded",
            "channels": ["in_app"],
            "enabled": True,
        },
    )
    assert rule.status_code == 200, rule.text

    upload = client.post(
        f"/api/matters/{matter['id']}/attachments",
        headers=_auth(token),
        data={"document_type": "order_judgment", "linked_court_order_id": order_id},
        files={"file": ("order.pdf", b"%PDF-1.4\norder\n%%EOF", "application/pdf")},
    )
    assert upload.status_code == 200, upload.text

    factory = get_session_factory()
    with factory() as session:
        notifications = list(session.scalars(select(InAppNotification)))
        assert len(notifications) == 1
        notification = notifications[0]
        assert notification.company_id == str(bootstrap["company"]["id"])
        assert notification.matter_id == str(matter["id"])
        assert notification.source_id == upload.json()["id"]
        audits = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "notification.in_app.created")
            )
        )
        assert len(audits) == 1


def test_disabled_new_order_rule_does_not_notify(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, "LW-S10-DISABLED")
    order_id = _seed_order(str(matter["id"]))
    rule = client.post(
        "/api/notification-rules",
        headers=_auth(token),
        json={
            "scope_type": "company",
            "event_type": "new_order_uploaded",
            "channels": ["in_app"],
            "enabled": False,
        },
    )
    assert rule.status_code == 200, rule.text

    upload = client.post(
        f"/api/matters/{matter['id']}/attachments",
        headers=_auth(token),
        data={"document_type": "order_judgment", "linked_court_order_id": order_id},
        files={"file": ("order.pdf", b"%PDF-1.4\norder\n%%EOF", "application/pdf")},
    )
    assert upload.status_code == 200, upload.text

    factory = get_session_factory()
    with factory() as session:
        assert list(session.scalars(select(InAppNotification))) == []
