"""Expired Calendar credentials must renew before event transport, never replay it."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from weakref import WeakSet

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from caseops_api.db.models import CalendarEventSync, CompanyMembership, UserCalendarConnection
from caseops_api.db.session import get_session_factory
from caseops_api.services import calendar_sync as calendar
from tests.test_auth_company import bootstrap_company
from tests.test_google_calendar_sync import StubGoogleCalendarProvider, _connect_google
from tests.test_legalworkspace_calendar_sync import (
    StubOutlookProvider,
    _auth,
    _connect_outlook,
    _create_matter,
    _schedule_hearing,
    _session_context,
)


@pytest.fixture(params=["google", "outlook"])
def expired_calendar(client, request, monkeypatch):
    kind = request.param
    actor = bootstrap_company(client)
    token = str(actor["access_token"])
    if kind == "google":
        connection_id = _connect_google(client, token, StubGoogleCalendarProvider())
        provider = calendar.GoogleCalendarProvider(calendar.GoogleCalendarRuntimeConfig(
            client_id="offline-client", client_secret="offline-secret",
            redirect_uri="http://testserver/callback", source="environment"))
        setter = calendar.set_google_calendar_provider_for_tests
        endpoint = "/api/calendar/sync/google-calendar/hearings/"
    else:
        connection_id = _connect_outlook(client, token, StubOutlookProvider())
        provider = calendar.MicrosoftGraphOutlookProvider(calendar.OutlookRuntimeConfig(
            client_id="offline-client", client_secret="offline-secret", tenant_id="organizations",
            redirect_uri="http://testserver/callback", source="environment"))
        setter = calendar.set_outlook_provider_for_tests
        endpoint = "/api/calendar/sync/hearings/"
    factory = get_session_factory()
    with factory() as session:
        row = session.get(UserCalendarConnection, connection_id)
        payload = calendar._decrypt_token_payload(row.encrypted_token_ref)
        payload.update(access_token="expired-access", refresh_token="old-refresh", expires_in=1)
        row.encrypted_token_ref = calendar._encrypt_token_payload(payload)
        row.connected_at = datetime.now(UTC) - timedelta(hours=2)
        session.commit()
    setter(provider)
    matter = _create_matter(client, token, "CAL17-" + kind)
    hearing = _schedule_hearing(client, token, str(matter["id"]))
    calls = []
    grant_callback = [None]
    grant_response = [None]
    event_timeout = [False]
    refresh_timeout = [False]
    expected_refresh = ["old-refresh"]
    original_send = httpx.Client.send
    active_sessions = WeakSet()

    def began(session, transaction, connection):
        active_sessions.add(session)

    def ended(session, transaction):
        if transaction.parent is None:
            active_sessions.discard(session)

    event.listen(Session, "after_begin", began)
    event.listen(Session, "after_transaction_end", ended)

    def offline_send(self, req, **kwargs):
        if req.url.host == "testserver":
            return original_send(self, req, **kwargs)
        if req.url.host not in {
            "oauth2.googleapis.com", "www.googleapis.com", "login.microsoftonline.com",
            "graph.microsoft.com",
        }:
            raise AssertionError("Unexpected external transport in Calendar fixture")
        if req.url.path.endswith("/token"):
            assert not active_sessions, "Token transport retained an application transaction"
            data = parse_qs(req.content.decode())
            assert data["grant_type"] == ["refresh_token"]
            assert data["refresh_token"] == expected_refresh
            calls.append("refresh")
            if grant_callback[0]:
                grant_callback[0]()
            if refresh_timeout[0]:
                raise httpx.ReadTimeout("offline uncertain token rotation", request=req)
            if grant_response[0]:
                code, body = grant_response[0]
                return httpx.Response(code, json=body, request=req)
            scopes = ("openid email https://www.googleapis.com/auth/calendar.events"
                      if kind == "google" else "User.Read Calendars.ReadWrite")
            return httpx.Response(200, request=req, json={
                "access_token": "fresh-access", "refresh_token": "new-refresh",
                "expires_in": 3600, "scope": scopes, "token_type": "Bearer"})
        calls.append("event")
        assert not active_sessions, "Event transport retained an application transaction"
        if req.headers.get("Authorization") != "Bearer fresh-access":
            return httpx.Response(401, request=req, json={"error": "invalid_token"})
        if event_timeout[0]:
            raise httpx.ReadTimeout("offline unknown create", request=req)
        return httpx.Response(200, request=req, json={"id": "offline-event"})

    monkeypatch.setattr(httpx.Client, "send", offline_send)
    try:
        yield dict(client=client, kind=kind, token=token, connection_id=connection_id,
                   endpoint=endpoint + hearing["id"], calls=calls, factory=factory,
                   grant_callback=grant_callback, grant_response=grant_response,
                   event_timeout=event_timeout, refresh_timeout=refresh_timeout,
                   expected_refresh=expected_refresh, matter=matter)
    finally:
        setter(None)
        event.remove(Session, "after_begin", began)
        event.remove(Session, "after_transaction_end", ended)


def test_expired_calendar_refreshes_once_and_persists_encrypted_rotation(expired_calendar):
    fixture = expired_calendar
    response = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert response.status_code == 200, response.text
    assert response.json()["sync"]["sync_status"] == "synced"
    assert fixture["calls"] == ["refresh", "event"]
    with fixture["factory"]() as session:
        row = session.get(UserCalendarConnection, fixture["connection_id"])
        assert row.status == "connected"
        assert row.encrypted_token_ref.startswith("fernet:")
        assert "fresh-access" not in row.encrypted_token_ref
        assert "new-refresh" not in row.encrypted_token_ref
        payload = calendar._decrypt_token_payload(row.encrypted_token_ref)
        assert payload["access_token"] == "fresh-access"
        assert payload["refresh_token"] == "new-refresh"
    assert "fresh-access" not in response.text and "new-refresh" not in response.text
    again = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert again.status_code == 200
    assert fixture["calls"] == ["refresh", "event", "event"]


def test_expired_calendar_unknown_event_post_is_not_retried(expired_calendar):
    fixture = expired_calendar
    fixture["event_timeout"][0] = True
    response = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert response.status_code == 200, response.text
    assert response.json()["sync"]["sync_status"] != "synced"
    assert fixture["calls"] == ["refresh", "event"]
    fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert fixture["calls"] == ["refresh", "event"]


def test_revocation_during_refresh_wins_without_event_or_rotation_publish(expired_calendar):
    fixture = expired_calendar
    observed = []

    def revoke():
        # A separate ASGI portal models the concurrent request; recursively
        # calling the original portal from its event-loop thread is invalid.
        other = TestClient(fixture["client"].app)
        try:
            result = other.delete("/api/calendar/connections/" + fixture["connection_id"],
                                  headers=_auth(fixture["token"]))
            observed.append((result.status_code, result.text))
        finally:
            other.close()

    fixture["grant_callback"][0] = revoke
    result = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert result.status_code == 200, result.text
    assert observed and observed[0][0] == 200, observed
    assert result.json()["sync"]["sync_status"] != "synced"
    assert fixture["calls"] == ["refresh"]
    with fixture["factory"]() as session:
        row = session.get(UserCalendarConnection, fixture["connection_id"])
        assert row.status == "revoked"
        if row.encrypted_token_ref:
            payload = calendar._decrypt_token_payload(row.encrypted_token_ref)
            assert payload["access_token"] != "fresh-access"


def test_lost_calendar_capability_during_refresh_prevents_event(expired_calendar):
    fixture = expired_calendar

    def deactivate():
        with fixture["factory"]() as session:
            row = session.get(UserCalendarConnection, fixture["connection_id"])
            session.get(CompanyMembership, row.membership_id).is_active = False
            session.commit()

    fixture["grant_callback"][0] = deactivate
    result = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert result.status_code in {200, 403}, result.text
    assert fixture["calls"] == ["refresh"]
    with fixture["factory"]() as session:
        row = session.get(UserCalendarConnection, fixture["connection_id"])
        payload = calendar._decrypt_token_payload(row.encrypted_token_ref)
        assert payload["access_token"] != "fresh-access"


def test_newer_credential_during_refresh_is_not_overwritten(expired_calendar):
    fixture = expired_calendar

    def replace():
        with fixture["factory"]() as session:
            row = session.get(UserCalendarConnection, fixture["connection_id"])
            row.encrypted_token_ref = calendar._encrypt_token_payload(
                {"access_token": "newer-consent"}
            )
            session.commit()

    fixture["grant_callback"][0] = replace
    result = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert result.status_code == 200, result.text
    assert fixture["calls"] == ["refresh"]
    with fixture["factory"]() as session:
        row = session.get(UserCalendarConnection, fixture["connection_id"])
        assert row.status == "connected"
        assert calendar._decrypt_token_payload(row.encrypted_token_ref) == {
            "access_token": "newer-consent"
        }


def test_rejected_refresh_has_zero_event_writes_and_requires_reconnect(expired_calendar):
    fixture = expired_calendar
    fixture["grant_response"][0] = (400, {"error": "invalid_grant"})
    result = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert result.status_code == 200, result.text
    assert fixture["calls"] == ["refresh"]
    with fixture["factory"]() as session:
        row = session.get(UserCalendarConnection, fixture["connection_id"])
        assert row.status == "error"
    again = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert again.status_code == 409
    assert fixture["calls"] == ["refresh"]


def _revoked_expired_cleanup(fixture):
    initial = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert initial.status_code == 200, initial.text
    assert initial.json()["sync"]["sync_status"] == "synced"
    sync_id = initial.json()["sync"]["id"]
    assert fixture["calls"] == ["refresh", "event"]
    revoked = fixture["client"].delete(
        "/api/calendar/connections/" + fixture["connection_id"],
        headers=_auth(fixture["token"]),
    )
    assert revoked.status_code == 200, revoked.text
    with fixture["factory"]() as session:
        row = session.get(UserCalendarConnection, fixture["connection_id"])
        assert row.status == "revoked"
        payload = calendar._decrypt_token_payload(row.encrypted_token_ref)
        assert payload["refresh_token"] == "new-refresh"
        payload[calendar._CALENDAR_TOKEN_EXPIRES_KEY] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        row.encrypted_token_ref = calendar._encrypt_token_payload(payload)
        sync = session.get(CalendarEventSync, sync_id)
        assert sync.sync_status == "delete_pending"
        assert sync.provider_event_id == "offline-event"
        session.commit()
    fixture["calls"].clear()
    fixture["expected_refresh"][0] = "new-refresh"
    return sync_id


@pytest.mark.parametrize("failure", ["timeout", "invalid_grant"])
def test_revoked_cleanup_token_post_is_never_replayed(expired_calendar, monkeypatch, failure):
    fixture = expired_calendar
    sync_id = _revoked_expired_cleanup(fixture)
    if failure == "timeout":
        fixture["refresh_timeout"][0] = True
    else:
        fixture["grant_response"][0] = (400, {"error": "invalid_grant"})
    clock = [datetime.now(UTC)]
    monkeypatch.setattr(calendar, "_current_time", lambda: clock[0])
    for attempt in range(3):
        with fixture["factory"]() as session:
            connection = session.get(UserCalendarConnection, fixture["connection_id"])
            context = _session_context(session, connection.company_id)
            outcome, _ = calendar._process_calendar_deletion_tombstone_by_id(
                session, context=context, sync_id=sync_id,
                expected_connection_id=fixture["connection_id"],
            )
            assert outcome in {"retry_scheduled", "dead_lettered"}, (attempt, outcome)
        # Crossing the durable refresh lease must not permit a second token POST.
        clock[0] += timedelta(minutes=6)
    assert fixture["calls"] == ["refresh"]
    with fixture["factory"]() as session:
        connection = session.get(UserCalendarConnection, fixture["connection_id"])
        assert connection.status == "revoked"
        assert connection.encrypted_token_ref.startswith("fernet:")
        payload = calendar._decrypt_token_payload(connection.encrypted_token_ref)
        assert payload[calendar._CALENDAR_REFRESH_CLAIM_KEY]
        assert payload["refresh_token"] == "new-refresh"
        assert session.get(CalendarEventSync, sync_id).sync_status != "deleted"


def test_revoked_cleanup_successful_rotation_deletes_only_known_event(expired_calendar):
    fixture = expired_calendar
    sync_id = _revoked_expired_cleanup(fixture)
    with fixture["factory"]() as session:
        connection = session.get(UserCalendarConnection, fixture["connection_id"])
        context = _session_context(session, connection.company_id)
        outcome, _ = calendar._process_calendar_deletion_tombstone_by_id(
            session, context=context, sync_id=sync_id,
            expected_connection_id=fixture["connection_id"],
        )
        assert outcome == "deleted"
    assert fixture["calls"] == ["refresh", "event"]
    with fixture["factory"]() as session:
        connection = session.get(UserCalendarConnection, fixture["connection_id"])
        assert connection.status == "revoked"
        assert connection.encrypted_token_ref is None
        sync = session.get(CalendarEventSync, sync_id)
        assert sync.sync_status == "deleted"
        assert sync.provider_event_id == "offline-event"


@pytest.fixture(params=["google", "outlook"])
def native_refresh(request):
    if request.param == "google":
        return calendar.GoogleCalendarProvider(calendar.GoogleCalendarRuntimeConfig(
            client_id="offline-client", client_secret="offline-secret",
            redirect_uri="http://testserver/callback", source="environment")), list(
                calendar.GOOGLE_CALENDAR_SCOPES
            )
    return calendar.MicrosoftGraphOutlookProvider(calendar.OutlookRuntimeConfig(
        client_id="offline-client", client_secret="offline-secret", tenant_id="organizations",
        redirect_uri="http://testserver/callback", source="environment")), list(
            calendar.OUTLOOK_SCOPES
        )


@pytest.mark.parametrize("omitted", ["scope", "refresh_token"])
def test_refresh_preserves_exact_grant_when_optional_fields_are_omitted(
    native_refresh, monkeypatch, omitted,
):
    provider, scopes = native_refresh
    payload = {"access_token": "fresh-access", "refresh_token": "rotated-refresh",
               "expires_in": 3600, "scope": " ".join(scopes), "token_type": "Bearer"}
    payload.pop(omitted)
    calls = []

    def response(url, *, data, timeout):
        calls.append(data)
        assert "scope" not in data
        assert timeout == 15
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", response)
    result = provider.refresh_access_token(
        token_payload={"refresh_token": "prior-refresh"}, scopes=scopes,
    )
    assert len(calls) == 1
    assert result["refresh_token"] == (
        "prior-refresh" if omitted == "refresh_token" else "rotated-refresh"
    )
    assert result[calendar._CALENDAR_TOKEN_EXPIRES_KEY]


@pytest.mark.parametrize("field,value", [
    ("expires_in", None), ("expires_in", True), ("expires_in", "3600"),
    ("expires_in", 0), ("expires_in", 30), ("expires_in", 31_536_001),
    ("access_token", 7), ("refresh_token", ""), ("scope", ""),
    ("scope", "User.Read"), ("token_type", "MAC"),
])
def test_malformed_refresh_contract_fails_closed_without_retry(
    native_refresh, monkeypatch, field, value,
):
    provider, scopes = native_refresh
    payload = {"access_token": "fresh-access", "refresh_token": "rotated-refresh",
               "expires_in": 3600, "scope": " ".join(scopes), "token_type": "Bearer"}
    payload[field] = value
    calls = []

    def response(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", response)
    with pytest.raises(calendar.CalendarRefreshError):
        provider.refresh_access_token(token_payload={"refresh_token": "prior"}, scopes=scopes)
    assert len(calls) == 1


def test_google_equivalent_identity_scope_is_not_a_new_permission(monkeypatch):
    provider = calendar.GoogleCalendarProvider(calendar.GoogleCalendarRuntimeConfig(
        client_id="offline-client", client_secret="offline-secret",
        redirect_uri="http://testserver/callback", source="environment"))

    def response(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "access_token": "fresh", "expires_in": 3600,
            "scope": "openid https://www.googleapis.com/auth/userinfo.email "
                     "https://www.googleapis.com/auth/calendar.events",
        })

    monkeypatch.setattr(httpx, "post", response)
    result = provider.refresh_access_token(
        token_payload={"refresh_token": "prior"}, scopes=calendar.GOOGLE_CALENDAR_SCOPES,
    )
    assert result["access_token"] == "fresh"
