from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    CalendarEventSync,
    CalendarEventSyncStatus,
    Company,
    CompanyMembership,
    InAppNotification,
    MatterCourtOrder,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    TenantOutlookConfiguration,
    User,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.calendar_sync import (
    process_durable_outlook_sync,
    set_outlook_provider_for_tests,
)
from caseops_api.services.identity import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company


class StubOutlookProvider:
    def __init__(self, *, fail: bool = False, fail_message: str = "provider unavailable") -> None:
        self.fail = fail
        self.fail_message = fail_message
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
                "access_token": "fixture-access-credential",
                "refresh_token": "fixture-refresh-credential",
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
            raise RuntimeError(self.fail_message)
        assert token_payload["access_token"] == "fixture-access-credential"
        self.calls.append(
            {
                "hearing_id": hearing.id,
                "matter_id": matter.id,
                "existing": existing_provider_event_id,
            }
        )
        return existing_provider_event_id or "remote-event-1"

    def validate_connection(self, *, token_payload: dict[str, object]) -> dict[str, object]:
        assert token_payload["access_token"] == "fixture-access-credential"
        return {
            "provider_account_id": "outlook-user-1",
            "display_email": "lawyer@example.test",
        }


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

    def validate_connection(self, **kwargs) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("unavailable provider should not validate")


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
    assert "fixture-access-credential" not in start.text
    state = parse_qs(urlparse(body["auth_url"]).query)["state"][0]
    callback = client.get(
        "/api/calendar/connections/outlook/callback",
        headers=_auth(token),
        params={"code": "oauth-code", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert "fixture-access-credential" not in callback.text
    return callback.json()["connection"]["id"]


def _configure_ready_outlook(
    client: TestClient,
    token: str,
    provider: StubOutlookProvider,
) -> str:
    set_outlook_provider_for_tests(provider)
    saved = client.patch(
        "/api/admin/outlook-configuration",
        headers=_auth(token),
        json={
            "client_id": "client-id-value",
            "client_secret": "fixture-credential-value",
            "tenant_id": "organizations",
            "redirect_uri": (
                "https://api.example.test/api/calendar/connections/outlook/callback"
            ),
            "scopes": ["offline_access", "User.Read", "Calendars.ReadWrite"],
            "oauth_consent_model_approved": True,
            "scopes_approved": True,
            "durable_runbook_approved": True,
            "rollback_approved": True,
            "redaction_rules_approved": True,
            "enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text
    connection_id = _connect_outlook(client, token, provider)
    tested = client.post(
        "/api/admin/outlook-configuration/test",
        headers=_auth(token),
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["adp20_readiness"] == "ready_for_adp20_implementation"
    return connection_id


def _session_context(session, company_id: str) -> SessionContext:
    company = session.get(Company, company_id)
    assert company is not None
    membership = session.scalar(
        select(CompanyMembership).where(CompanyMembership.company_id == company_id)
    )
    assert membership is not None
    user = session.get(User, membership.user_id)
    assert user is not None
    return SessionContext(company=company, user=user, membership=membership)


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
            assert "fixture-access-credential" not in connection.encrypted_token_ref
            assert "fixture-refresh-credential" not in connection.encrypted_token_ref

        listed = client.get("/api/calendar/connections", headers=_auth(token))
        assert listed.status_code == 200, listed.text
        assert listed.json()["connections"][0]["display_email"] == "lawyer@example.test"
        assert "fixture-access-credential" not in listed.text

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
        assert body["durable_automation"] == "blocked_pending_provider_approval"
        assert body["notification_delivery"] == "wtd_5_3_foundation_available"
        assert body["capabilities"] == {
            "sync_mode": "manual_bounded",
            "manual_sync_available": False,
            "durable_automation": "blocked_pending_provider_approval",
            "notification_delivery": "wtd_5_3_foundation_available",
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
        assert "fixture-access-credential" not in response.text
        assert "fixture-refresh-credential" not in response.text
    finally:
        set_outlook_provider_for_tests(None)


def test_admin_outlook_configuration_stores_secret_encrypted_and_names_only(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    response = client.patch(
        "/api/admin/outlook-configuration",
        headers=_auth(token),
        json={
            "client_id": "client-id-value",
            "client_secret": "fixture-credential-value",
            "tenant_id": "organizations",
            "redirect_uri": "https://api.example.test/api/calendar/connections/outlook/callback",
            "scopes": ["offline_access", "User.Read", "Calendars.ReadWrite"],
            "oauth_consent_model_approved": True,
            "scopes_approved": True,
            "durable_runbook_approved": True,
            "rollback_approved": True,
            "redaction_rules_approved": True,
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["config_source"] == "tenant_admin"
    assert body["missing_config_names"] == []
    assert body["missing_approval_keys"] == []
    assert "fixture-credential-value" not in response.text
    assert "client-id-value" not in response.text

    factory = get_session_factory()
    with factory() as session:
        row = session.scalar(select(TenantOutlookConfiguration))
        assert row is not None
        assert row.client_id == "client-id-value"
        assert row.encrypted_client_secret_ref is not None
        assert row.encrypted_client_secret_ref.startswith("fernet:")
        assert "fixture-credential-value" not in row.encrypted_client_secret_ref


def test_admin_outlook_readiness_test_requires_connection_then_unblocks(
    client: TestClient,
) -> None:
    provider = StubOutlookProvider()
    try:
        set_outlook_provider_for_tests(provider)
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        saved = client.patch(
            "/api/admin/outlook-configuration",
            headers=_auth(token),
            json={
                "client_id": "client-id-value",
                "client_secret": "fixture-credential-value",
                "tenant_id": "organizations",
                "redirect_uri": "https://api.example.test/api/calendar/connections/outlook/callback",
                "scopes": ["offline_access", "User.Read", "Calendars.ReadWrite"],
                "oauth_consent_model_approved": True,
                "scopes_approved": True,
                "durable_runbook_approved": True,
                "rollback_approved": True,
                "redaction_rules_approved": True,
                "enabled": True,
            },
        )
        assert saved.status_code == 200, saved.text

        blocked = client.post(
            "/api/admin/outlook-configuration/test",
            headers=_auth(token),
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["status"] == "blocked"
        assert blocked.json()["adp20_readiness"] == (
            "blocked_pending_admin_configuration"
        )
        assert "fixture-credential-value" not in blocked.text

        _connect_outlook(client, token, provider)
        passed = client.post(
            "/api/admin/outlook-configuration/test",
            headers=_auth(token),
        )
        assert passed.status_code == 200, passed.text
        body = passed.json()
        assert body["status"] == "passed"
        assert body["adp20_readiness"] == "ready_for_adp20_implementation"
        assert {check["key"] for check in body["checks"]} >= {
            "OUTLOOK_CLIENT_ID",
            "OUTLOOK_CLIENT_SECRET",
            "OUTLOOK_REDIRECT_URI",
            "OUTLOOK_TENANT_ID_OR_APPROVED_TENANT_MODE",
            "MICROSOFT_GRAPH_ME",
        }
        status = client.get("/api/admin/outlook-configuration", headers=_auth(token))
        assert status.status_code == 200, status.text
        assert status.json()["adp20_readiness"] == "ready_for_adp20_implementation"
        assert "fixture-access-credential" not in passed.text
        assert "fixture-credential-value" not in passed.text
    finally:
        set_outlook_provider_for_tests(None)


def test_durable_outlook_sync_skips_tenants_not_ready_names_only(
    client: TestClient,
) -> None:
    try:
        set_outlook_provider_for_tests(MissingOutlookProvider())
        bootstrap = bootstrap_company(client)
        company_id = str(bootstrap["company"]["id"])

        factory = get_session_factory()
        with factory() as session:
            context = _session_context(session, company_id)
            result = process_durable_outlook_sync(session, context=context)

        assert result.status == "blocked"
        assert result.adp20_readiness == "blocked_pending_admin_configuration"
        assert "OUTLOOK_CLIENT_ID" in result.missing_config_names
        assert result.provider_calls == 0
        assert result.examined == 0
        serialized = str(result)
        assert "fixture-access-credential" not in serialized
        assert "fixture-credential-value" not in serialized
    finally:
        set_outlook_provider_for_tests(None)


def test_durable_outlook_sync_is_idempotent_for_hearings(
    client: TestClient,
) -> None:
    provider = StubOutlookProvider()
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _configure_ready_outlook(client, token, provider)
        matter = _create_matter(client, token, "ADP20-IDEMP")
        hearing = _schedule_hearing(client, token, str(matter["id"]))
        company_id = str(bootstrap["company"]["id"])

        factory = get_session_factory()
        with factory() as session:
            context = _session_context(session, company_id)
            result = process_durable_outlook_sync(
                session,
                context=context,
                range_from=date.today(),
                range_to=date.today() + timedelta(days=14),
            )
            second = process_durable_outlook_sync(
                session,
                context=context,
                range_from=date.today(),
                range_to=date.today() + timedelta(days=14),
            )
            rows = list(session.scalars(select(CalendarEventSync)))

        assert result.status == "processed"
        assert result.synced == 1
        assert second.synced == 1
        assert len(rows) == 1
        assert rows[0].source_id == hearing["id"]
        assert rows[0].sync_status == CalendarEventSyncStatus.SYNCED
        assert provider.calls[1]["existing"] == "remote-event-1"
    finally:
        set_outlook_provider_for_tests(None)


def test_durable_outlook_sync_retry_and_dead_letter_are_redacted(
    client: TestClient,
) -> None:
    raw_error = (
        "authorization samplecredentialvalueforredaction for lawyer@example.test "
        "https://graph.example.test/events"
    )
    provider = StubOutlookProvider(fail=True, fail_message=raw_error)
    try:
        bootstrap = bootstrap_company(client)
        token = str(bootstrap["access_token"])
        _configure_ready_outlook(client, token, provider)
        matter = _create_matter(client, token, "ADP20-RETRY")
        _schedule_hearing(client, token, str(matter["id"]))
        company_id = str(bootstrap["company"]["id"])

        factory = get_session_factory()
        with factory() as session:
            context = _session_context(session, company_id)
            first = process_durable_outlook_sync(
                session,
                context=context,
                range_from=date.today(),
                range_to=date.today() + timedelta(days=14),
            )
            second = process_durable_outlook_sync(
                session,
                context=context,
                replay_failed_only=True,
            )
            third = process_durable_outlook_sync(
                session,
                context=context,
                replay_failed_only=True,
            )
            fourth = process_durable_outlook_sync(
                session,
                context=context,
                replay_failed_only=True,
            )
            sync = session.scalar(select(CalendarEventSync))
            assert sync is not None

        assert first.retry_scheduled == 1
        assert second.retry_scheduled == 1
        assert third.dead_lettered == 1
        assert fourth.dead_lettered == 1
        assert sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
        assert sync.attempts == sync.max_attempts == 3
        assert sync.dead_letter_reason == "retry_limit_exhausted"
        redacted = sync.last_error or ""
        assert "lawyer@example.test" not in redacted
        assert "samplecredentialvalueforredaction" not in redacted
        assert "graph.example.test" not in redacted
    finally:
        set_outlook_provider_for_tests(None)


def test_admin_outlook_replay_is_tenant_scoped(
    client: TestClient,
) -> None:
    provider = StubOutlookProvider(fail=True)
    try:
        first = bootstrap_company(client)
        first_token = str(first["access_token"])
        _configure_ready_outlook(client, first_token, provider)
        first_matter = _create_matter(client, first_token, "ADP20-REPLAY-A")
        _schedule_hearing(client, first_token, str(first_matter["id"]))

        second = _bootstrap_company(
            client,
            slug="adp20-replay-b",
            email="owner@adp20-replay-b.example",
        )
        second_token = str(second["access_token"])
        _configure_ready_outlook(client, second_token, provider)
        second_matter = _create_matter(client, second_token, "ADP20-REPLAY-B")
        _schedule_hearing(client, second_token, str(second_matter["id"]))

        factory = get_session_factory()
        with factory() as session:
            first_context = _session_context(session, str(first["company"]["id"]))
            second_context = _session_context(session, str(second["company"]["id"]))
            process_durable_outlook_sync(
                session,
                context=first_context,
                range_from=date.today(),
                range_to=date.today() + timedelta(days=14),
            )
            process_durable_outlook_sync(
                session,
                context=second_context,
                range_from=date.today(),
                range_to=date.today() + timedelta(days=14),
            )

        provider.fail = False
        replay = client.post(
            "/api/admin/outlook-sync/replay",
            headers=_auth(first_token),
            json={"limit": 10},
        )
        assert replay.status_code == 200, replay.text
        body = replay.json()
        assert body["status"] == "processed"
        assert body["replayed"] == 1
        assert body["synced"] == 1

        with factory() as session:
            first_rows = list(
                session.scalars(
                    select(CalendarEventSync).where(
                        CalendarEventSync.company_id == str(first["company"]["id"])
                    )
                )
            )
            second_rows = list(
                session.scalars(
                    select(CalendarEventSync).where(
                        CalendarEventSync.company_id == str(second["company"]["id"])
                    )
                )
            )
        assert [row.sync_status for row in first_rows] == [
            CalendarEventSyncStatus.SYNCED
        ]
        assert [row.sync_status for row in second_rows] == [
            CalendarEventSyncStatus.RETRY_SCHEDULED
        ]
        assert "fixture-access-credential" not in replay.text
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
        assert "fixture-access-credential" not in response.text
        assert "fixture-refresh-credential" not in response.text
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
        assert "fixture-access-credential" not in response.text
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
    assert listed.json()["durable_delivery"] == "wtd_5_3_foundation_available"
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
        intents = list(session.scalars(select(NotificationDeliveryIntent)))
        assert len(intents) == 1
        assert intents[0].status == NotificationDeliveryStatus.DELIVERED
        assert intents[0].in_app_notification_id == notification.id
        audits = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "notification.in_app.created")
            )
        )
        assert len(audits) == 1


def test_external_only_new_order_rule_creates_blocked_delivery_intent(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, "LW-S10-EXT-BLOCK")
    order_id = _seed_order(str(matter["id"]))
    rule = client.post(
        "/api/notification-rules",
        headers=_auth(token),
        json={
            "scope_type": "company",
            "event_type": "new_order_uploaded",
            "channels": ["email"],
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
        assert list(session.scalars(select(InAppNotification))) == []
        intents = list(session.scalars(select(NotificationDeliveryIntent)))
        assert len(intents) == 1
        intent = intents[0]
        assert intent.channel == "email"
        assert intent.status == NotificationDeliveryStatus.BLOCKED
        assert intent.attempts == 0
        assert intent.dead_letter_reason == "provider_disabled"
        assert intent.last_error_redacted == "external provider disabled"
        assert intent.title is None
        assert intent.body is None
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "notification_delivery.external.blocked"
                )
            )
        )
        assert len(audits) == 1
        assert upload.json()["id"] not in (audits[0].metadata_json or "")


def test_new_order_notifications_respect_ethically_walled_recipient(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    matter = _create_matter(client, token, "LW-S10-WALL-NOTIFY")
    order_id = _seed_order(str(matter["id"]))
    member = client.post(
        "/api/companies/current/users",
        headers=_auth(token),
        json={
            "full_name": "Walled Notifications",
            "email": "walled-notify@caseops-test.in",
            "role": "member",
            "password": "MemberPass123!",
        },
    )
    assert member.status_code == 200, member.text
    wall = client.post(
        f"/api/matters/{matter['id']}/access/walls",
        headers=_auth(token),
        json={
            "excluded_membership_id": member.json()["membership_id"],
            "reason": "Conflict",
        },
    )
    assert wall.status_code == 200, wall.text
    rule = client.post(
        "/api/notification-rules",
        headers=_auth(token),
        json={
            "scope_type": "company",
            "event_type": "new_order_uploaded",
            "channels": ["in_app", "email"],
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
        intents = list(session.scalars(select(NotificationDeliveryIntent)))
        notifications = list(session.scalars(select(InAppNotification)))
        blocked_membership_id = member.json()["membership_id"]
        assert intents
        assert notifications
        assert all(row.recipient_membership_id != blocked_membership_id for row in intents)
        assert all(
            row.recipient_membership_id != blocked_membership_id
            for row in notifications
        )


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
        assert list(session.scalars(select(NotificationDeliveryIntent))) == []
