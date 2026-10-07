"""Oct 8 BUG-003/004: real adapter contract and durable OAuth recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import sleep
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    ApiIdempotencyRecord,
    AuditEvent,
    CalendarConnectionStatus,
    Company,
    CompanyMembership,
    TenantGoogleWorkspaceConfiguration,
    TenantOutlookConfiguration,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import calendar_sync as calendar
from caseops_api.services.google_workspace import GOOGLE_WORKSPACE_CALENDAR_SCOPES
from tests.test_auth_company import bootstrap_company
from tests.test_legalworkspace_calendar_sync import _auth


@pytest.fixture
def google_provider():
    provider = calendar.GoogleCalendarProvider(
        calendar.GoogleCalendarRuntimeConfig(
            client_id="local-client",
            client_secret="local-secret",
            redirect_uri="http://testserver/api/calendar/connections/google-calendar/callback",
            source="environment",
        )
    )
    calendar.set_google_calendar_provider_for_tests(provider)
    try:
        yield provider
    finally:
        calendar.set_google_calendar_provider_for_tests(None)


def test_google_authorization_requests_minimum_identity_scopes(google_provider):
    assert calendar.GOOGLE_CALENDAR_SCOPES == GOOGLE_WORKSPACE_CALENDAR_SCOPES
    assert calendar.GOOGLE_CALENDAR_SCOPES is not GOOGLE_WORKSPACE_CALENDAR_SCOPES
    query = parse_qs(urlparse(google_provider.authorization_url(state="state")).query)
    assert set(query["scope"][0].split()) == {
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.events",
    }


@pytest.fixture
def outlook_provider():
    provider = calendar.MicrosoftGraphOutlookProvider(
        calendar.OutlookRuntimeConfig(
            client_id="outlook-client",
            client_secret="outlook-secret",
            tenant_id="tenant",
            redirect_uri="https://api.example.test/api/calendar/connections/outlook/callback",
            source="environment",
        )
    )
    calendar.set_outlook_provider_for_tests(provider)
    try:
        yield provider
    finally:
        calendar.set_outlook_provider_for_tests(None)


@pytest.mark.parametrize(
    "failure",
    [
        "token_json",
        "token_list",
        "empty_access",
        "numeric_access",
        "null_scope",
        "empty_scope",
        "scope_list",
        "missing_calendar_scope",
        "missing_identity_scope",
        "openid_only",
        "foreign_calendar_scope",
        "identity_json",
        "identity_list",
        "missing_subject",
        "numeric_subject",
        "oversized_subject",
        "numeric_email",
    ],
)
def test_outlook_native_adapter_rejects_malformed_provider_payload(
    client, outlook_provider, monkeypatch, failure,
):
    calls = []
    token = {"access_token": "outlook-access", "scope": "Calendars.ReadWrite User.Read"}
    identity = {"id": "outlook-subject", "mail": None, "userPrincipalName": "user@example.test"}
    if failure == "token_list":
        token = []
    elif failure == "empty_access":
        token["access_token"] = ""
    elif failure == "numeric_access":
        token["access_token"] = 42
    elif failure == "null_scope":
        token["scope"] = None
    elif failure == "empty_scope":
        token["scope"] = " "
    elif failure == "scope_list":
        token["scope"] = ["Calendars.ReadWrite", "User.Read"]
    elif failure == "missing_calendar_scope":
        token["scope"] = "User.Read"
    elif failure == "missing_identity_scope":
        token["scope"] = "Calendars.ReadWrite"
    elif failure == "openid_only":
        token["scope"] = "openid profile offline_access"
    elif failure == "foreign_calendar_scope":
        token["scope"] = "User.Read https://other.example/Calendars.ReadWrite"
    elif failure == "identity_list":
        identity = []
    elif failure == "missing_subject":
        identity.pop("id")
    elif failure == "numeric_subject":
        identity["id"] = 42
    elif failure == "oversized_subject":
        identity["id"] = "x" * 256
    elif failure == "numeric_email":
        identity["mail"] = 42

    def post(url, **kwargs):
        assert url == "https://login.microsoftonline.com/tenant/oauth2/v2.0/token"
        calls.append("token")
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            **({"content": b"not-json"} if failure == "token_json" else {"json": token}),
        )

    def get(method, url, **kwargs):
        assert method == "GET" and url == "https://graph.microsoft.com/v1.0/me"
        calls.append("identity")
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            **({"content": b"not-json"} if failure == "identity_json" else {"json": identity}),
        )

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "request", get)
    partial_grant = failure in {
        "missing_calendar_scope", "missing_identity_scope", "openid_only", "foreign_calendar_scope",
    }
    expected_code = (
        "calendar_oauth_reconnect_required" if partial_grant else "calendar_oauth_invalid_response"
    )
    expected_status = 409 if partial_grant else 502
    with pytest.raises(calendar.CalendarOAuthError) as invalid:
        outlook_provider.exchange_code(code="one-use-outlook-code")
    assert invalid.value.code == expected_code
    assert invalid.value.status_code == expected_status
    assert calls.count("token") == 1
    assert calls.count("identity") == (
        0
        if partial_grant or failure
        in {
            "token_json",
            "token_list",
            "empty_access",
            "numeric_access",
            "null_scope",
            "empty_scope",
            "scope_list",
        }
        else 1
    )
    direct_calls = list(calls)
    browser_token = bootstrap_company(client)["access_token"]
    start = client.post("/api/calendar/connections/outlook/start", headers=_auth(browser_token))
    assert start.status_code == 200, start.text
    state = parse_qs(urlparse(start.json()["auth_url"]).query)["state"][0]
    response = client.get(
        "/api/calendar/connections/outlook/callback",
        headers={**_auth(browser_token), "Accept": "application/json"},
        params={"state": state, "code": "one-use-outlook-code"},
    )
    assert response.status_code == expected_status, response.text
    assert response.json()["code"] == expected_code
    assert calls == direct_calls * 2
    with get_session_factory()() as session:
        row = session.scalar(select(UserCalendarConnection))
        assert row.status == CalendarConnectionStatus.ERROR
        assert row.provider_account_id is None
        assert calendar._oauth_claim_from_connection(row)[1] is None


@pytest.mark.parametrize(
    "scope_text",
    [None, "Calendars.ReadWrite User.Read",
     "https://graph.microsoft.com/Calendars.ReadWrite https://graph.microsoft.com/User.Read"],
)
def test_outlook_native_adapter_accepts_documented_scope_and_upn_contract(
    outlook_provider, monkeypatch, scope_text,
):
    token = {"access_token": "outlook-access"}
    if scope_text is not None:
        token["scope"] = scope_text

    def post(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json=token)

    def get(method, url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer outlook-access"
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            json={"id": "stable-outlook-id", "mail": None, "userPrincipalName": "a@example.test"},
        )

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "request", get)
    result = outlook_provider.exchange_code(code="valid-one-use-code")
    assert result["provider_account_id"] == "stable-outlook-id"
    assert result["display_email"] == "a@example.test"
    assert result["token_payload"] == token
    assert result["scopes"] == (
        scope_text.split() if scope_text is not None else calendar.OUTLOOK_SCOPES
    )


@pytest.mark.parametrize("provider_path", ["google-calendar", "outlook"])
@pytest.mark.parametrize(
    "failure",
    [
        "token_list", "empty_access", "numeric_access", "missing_subject",
        "numeric_subject", "invalid_email", "missing_scopes", "scope_string",
    ],
)
def test_shared_finalizer_rejects_incomplete_adapter_result_and_releases_claim(
    client, google_provider, outlook_provider, monkeypatch, provider_path, failure,
):
    provider = google_provider if provider_path == "google-calendar" else outlook_provider
    result = {
        "token_payload": {"access_token": "private-access"},
        "provider_account_id": "stable-subject",
        "display_email": "user@example.test",
        "scopes": list(calendar.GOOGLE_CALENDAR_SCOPES)
        if provider_path == "google-calendar" else list(calendar.OUTLOOK_SCOPES),
    }
    if failure == "token_list":
        result["token_payload"] = []
    elif failure == "empty_access":
        result["token_payload"]["access_token"] = " "
    elif failure == "numeric_access":
        result["token_payload"]["access_token"] = 42
    elif failure == "missing_subject":
        result.pop("provider_account_id")
    elif failure == "numeric_subject":
        result["provider_account_id"] = 42
    elif failure == "invalid_email":
        result["display_email"] = {"email": "not-a-string"}
    elif failure == "missing_scopes":
        result.pop("scopes")
    elif failure == "scope_string":
        result["scopes"] = "not-a-list"
    calls = []

    def exchange(*, code):
        calls.append(code)
        return result

    monkeypatch.setattr(provider, "exchange_code", exchange)
    token = bootstrap_company(client)["access_token"]
    base_path = f"/api/calendar/connections/{provider_path}"
    start = client.post(f"{base_path}/start", headers=_auth(token))
    assert start.status_code == 200, start.text
    state = parse_qs(urlparse(start.json()["auth_url"]).query)["state"][0]
    response = client.get(
        f"{base_path}/callback", headers={**_auth(token), "Accept": "application/json"},
        params={"state": state, "code": "one-use-code"},
    )
    assert response.status_code == 502, response.text
    assert response.json()["code"] == "calendar_oauth_invalid_response"
    with get_session_factory()() as session:
        row = session.scalar(select(UserCalendarConnection))
        assert row.status == CalendarConnectionStatus.ERROR
        assert row.provider_account_id is None
        assert row.encrypted_token_ref is None
        assert calendar._oauth_claim_from_connection(row)[1] is None
    replay = client.get(
        f"{base_path}/callback", headers={**_auth(token), "Accept": "application/json"},
        params={"state": state, "code": "one-use-code"},
    )
    assert replay.status_code == 409, replay.text
    assert replay.json()["code"] == "calendar_oauth_callback_consumed"
    assert calls == ["one-use-code"]


def _transport(monkeypatch, *, identity_status=200, identity=None):
    calls = []

    def token_post(url, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        calls.append(("token", kwargs["data"]["code"]))
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "access_token": "private-access",
                "refresh_token": "private-refresh",
                "scope": "openid https://www.googleapis.com/auth/userinfo.email "
                "https://www.googleapis.com/auth/calendar.events",
            },
        )

    def identity_get(method, url, **kwargs):
        assert method == "GET"
        assert url == "https://www.googleapis.com/oauth2/v3/userinfo"
        assert kwargs["headers"]["Authorization"] == "Bearer private-access"
        calls.append(("identity", identity_status))
        return httpx.Response(
            identity_status,
            request=httpx.Request(method, url),
            json=(
                identity
                if identity is not None
                else {"sub": "google-subject", "email": "calendar@example.test"}
            ),
        )

    monkeypatch.setattr(httpx, "post", token_post)
    monkeypatch.setattr(httpx, "request", identity_get)
    return calls


def _start(client, token):
    response = client.post("/api/calendar/connections/google-calendar/start", headers=_auth(token))
    assert response.status_code == 200, response.text
    return parse_qs(urlparse(response.json()["auth_url"]).query)["state"][0]


def _callback(client, token, state, code="one-use-code"):
    return client.get(
        "/api/calendar/connections/google-calendar/callback",
        headers={**_auth(token), "Accept": "application/json"},
        params={"state": state, "code": code},
    )


def test_token_success_userinfo_401_clears_claim_and_new_consent_recovers(
    client,
    google_provider,
    monkeypatch,
):
    bootstrap = bootstrap_company(client)
    token = bootstrap["access_token"]
    calls = _transport(monkeypatch, identity_status=401)
    state = _start(client, token)
    failed = _callback(client, token, state)
    assert failed.status_code == 409, failed.text
    assert failed.json()["code"] == "calendar_oauth_reconnect_required"
    assert "private-access" not in failed.text
    with get_session_factory()() as session:
        row = session.scalar(
            select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == bootstrap["company"]["id"],
            )
        )
        assert row.status == CalendarConnectionStatus.ERROR
        assert row.provider_account_id is None
        assert calendar._oauth_claim_from_connection(row)[1] is None
        failed_audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == row.id,
                AuditEvent.action == "calendar.connection.oauth_failed",
            )
        )
        assert failed_audit is not None
        assert failed_audit.result == "failed"
        assert "private-access" not in failed_audit.metadata_json
    repeated = _callback(client, token, state)
    assert repeated.status_code == 409, repeated.text
    assert repeated.json()["code"] == "calendar_oauth_callback_consumed"
    assert calls == [("token", "one-use-code"), ("identity", 401)]
    success_calls = _transport(monkeypatch)
    new_state = _start(client, token)
    assert new_state != state
    recovered = _callback(client, token, new_state, "fresh-code")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["connection"]["provider_account_id"] == "google-subject"
    assert recovered.json()["connection"]["display_email"] == "calendar@example.test"
    assert success_calls == [("token", "fresh-code"), ("identity", 200)]
    assert _callback(client, token, new_state, "fresh-code").status_code == 409
    assert len(success_calls) == 2
    with get_session_factory()() as session:
        row = session.scalar(
            select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == bootstrap["company"]["id"],
            )
        )
        assert row.status == CalendarConnectionStatus.CONNECTED
        assert row.provider_account_id == "google-subject"


@pytest.mark.parametrize(
    "identity",
    [
        [],
        {},
        {"sub": "subject"},
        {"sub": "", "email": "x@example.test"},
        {"sub": 42, "email": "x@example.test"},
    ],
)
def test_incomplete_google_identity_never_connects(google_provider, monkeypatch, identity):
    calls = _transport(monkeypatch, identity=identity)
    with pytest.raises(calendar.CalendarProviderError):
        google_provider.exchange_code(code="one-use-code")
    assert calls == [("token", "one-use-code"), ("identity", 200)]


@pytest.mark.parametrize(
    "body",
    [None, {}, {"access_token": ""}, {"access_token": 12}, {"access_token": "private-access"}],
)
def test_google_rejects_malformed_token_or_missing_explicit_grant(
    google_provider,
    monkeypatch,
    body,
):
    def post(url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            **({"content": b"not-json"} if body is None else {"json": body}),
        )

    def unexpected_read(*args, **kwargs):
        pytest.fail("Malformed credential/grant must not reach Google userinfo")

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "request", unexpected_read)
    with pytest.raises(calendar.CalendarOAuthError) as failure:
        google_provider.exchange_code(code="one-use-code")
    assert failure.value.code == "calendar_oauth_invalid_response"


@pytest.mark.parametrize(
    "failure", ["timeout", "invalid_grant", "malformed_token", "missing_scope"]
)
def test_exchange_failure_never_retries_token_or_strands_claim(
    client,
    google_provider,
    monkeypatch,
    failure,
):
    token = bootstrap_company(client)["access_token"]
    calls = []

    def token_post(url, **kwargs):
        calls.append(kwargs["data"]["code"])
        request = httpx.Request("POST", url)
        if failure == "timeout":
            raise httpx.ReadTimeout("may already have consumed code", request=request)
        if failure == "invalid_grant":
            return httpx.Response(400, request=request, json={"error": "invalid_grant"})
        if failure == "malformed_token":
            return httpx.Response(200, request=request, json=[])
        return httpx.Response(
            200,
            request=request,
            json={
                "access_token": "private-access",
                "scope": "openid email",
            },
        )

    def unexpected_get(*args, **kwargs):
        pytest.fail("Invalid token/grants must not reach userinfo")

    monkeypatch.setattr(httpx, "post", token_post)
    monkeypatch.setattr(httpx, "request", unexpected_get)
    state = _start(client, token)
    response = _callback(client, token, state)
    assert (
        response.status_code
        == {
            "timeout": 503,
            "invalid_grant": 409,
            "malformed_token": 502,
            "missing_scope": 409,
        }[failure]
    ), response.text
    with get_session_factory()() as session:
        row = session.scalar(select(UserCalendarConnection))
        assert calendar._oauth_claim_from_connection(row)[1] is None
        assert row.status == CalendarConnectionStatus.ERROR
    repeat = _callback(client, token, _start(client, token))
    assert repeat.status_code == 409, repeat.text
    assert repeat.json()["code"] == "calendar_oauth_callback_consumed"
    assert calls == ["one-use-code"]


@pytest.mark.parametrize("identity_status", [429, 503])
def test_userinfo_outage_is_bounded_and_releases_only_this_attempt(
    client,
    google_provider,
    monkeypatch,
    identity_status,
):
    token = bootstrap_company(client)["access_token"]
    calls = _transport(monkeypatch, identity_status=identity_status)
    response = _callback(client, token, _start(client, token))
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "calendar_oauth_provider_unavailable"
    assert calls == [("token", "one-use-code"), *[("identity", identity_status)] * 3]
    with get_session_factory()() as session:
        row = session.scalar(select(UserCalendarConnection))
        assert row.status == CalendarConnectionStatus.ERROR
        assert calendar._oauth_claim_from_connection(row)[1] is None


@pytest.mark.postgres
@pytest.mark.parametrize(
    "provider_kind", [calendar.CalendarProvider.GOOGLE_CALENDAR, calendar.CalendarProvider.OUTLOOK]
)
@pytest.mark.parametrize(
    "winner", ["new_consent", "new_claim", "revoke", "demote", "expired", "disable", "rotate",
               "session_cutoff", "company_disabled"]
)
@pytest.mark.parametrize("old_failure", [False, True])
def test_postgres_late_exchange_cannot_overwrite_or_clear_winner(
    pg_engine,
    monkeypatch,
    winner,
    old_failure,
    provider_kind,
):
    from tests.test_postgres_validation import (
        _ip_race_context,
        _seed_company,
        _seed_membership,
    )

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        membership_id = _seed_membership(seed, company_id, role="admin")
        if winner in {"disable", "rotate"}:
            if provider_kind == calendar.CalendarProvider.GOOGLE_CALENDAR:
                from caseops_api.services.google_workspace import _encrypt_secret

                config_row = TenantGoogleWorkspaceConfiguration(
                    company_id=company_id,
                    client_id="initial-client",
                    encrypted_client_secret_ref=_encrypt_secret("initial-secret"),
                    calendar_redirect_uri="https://api.example.test/api/calendar/connections/google-calendar/callback",
                    enabled=True,
                    calendar_enabled=True,
                )
            else:
                config_row = TenantOutlookConfiguration(
                    company_id=company_id,
                    client_id="initial-client",
                    encrypted_client_secret_ref=calendar._encrypt_secret("initial-secret"),
                    redirect_uri="https://api.example.test/api/calendar/connections/outlook/callback",
                    enabled=True,
                )
            seed.add(config_row)
            seed.flush()
            config_id = config_row.id
        seed.commit()
    entered, release = Event(), Event()
    worker_sessions, calls = [], []
    now = calendar._current_time()

    class Provider:
        configured = True
        unavailable_reason = None

        def exchange_code(self, *, code):
            calls.append(code)
            if code == "old-code":
                assert not worker_sessions[0].in_transaction()
                entered.set()
                assert release.wait(15), "coordinator did not release provider"
                if old_failure:
                    raise calendar.CalendarProviderError("private upstream failure")
            return {
                "token_payload": {"access_token": f"access-{code}"},
                "provider_account_id": f"subject-{code}",
                "display_email": "calendar@example.test",
                "scopes": list(calendar.GOOGLE_CALENDAR_SCOPES)
                if provider_kind == calendar.CalendarProvider.GOOGLE_CALENDAR
                else list(calendar.OUTLOOK_SCOPES),
            }

    set_provider = (
        calendar.set_google_calendar_provider_for_tests
        if provider_kind == calendar.CalendarProvider.GOOGLE_CALENDAR
        else calendar.set_outlook_provider_for_tests
    )
    set_provider(Provider())

    def complete(session, **kwargs):
        return calendar._complete_connection(session, calendar_provider=provider_kind, **kwargs)

    def context_for(session):
        context = _ip_race_context(session, company_id=company_id, membership_id=membership_id)
        context.token_issued_at = now.timestamp() - 1
        return context

    with Session(pg_engine) as session:
        original_state = calendar._sign_state(context_for(session), provider=provider_kind)

    def exchange_worker():
        with Session(pg_engine, expire_on_commit=False) as worker:
            worker_sessions.append(worker)
            return complete(
                worker,
                context=context_for(worker),
                code="old-code",
                state=original_state,
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(exchange_worker)
            try:
                assert entered.wait(15), "provider exchange never began"
                with Session(pg_engine) as duplicate:
                    with pytest.raises(HTTPException) as pending:
                        complete(
                            duplicate,
                            context=context_for(duplicate),
                            code="old-code",
                            state=original_state,
                        )
                    assert pending.value.detail["code"] == "calendar_oauth_exchange_in_flight"
                with Session(pg_engine, expire_on_commit=False) as writer:
                    writer.execute(text("SET LOCAL lock_timeout = '2s'"))
                    connection = writer.scalar(
                        select(UserCalendarConnection)
                        .where(
                            UserCalendarConnection.company_id == company_id,
                        )
                        .with_for_update(of=UserCalendarConnection)
                    )
                    connection_id = connection.id
                    assert calendar._oauth_claim_from_connection(connection)[1]
                    if winner == "revoke":
                        connection.status = CalendarConnectionStatus.REVOKED
                        connection.encrypted_token_ref = None
                    elif winner == "new_claim":
                        connection.encrypted_token_ref = calendar._encrypt_token_payload(
                            {
                                calendar._CALENDAR_OAUTH_CLAIM_KEY: "newer-committed-claim",
                                calendar._CALENDAR_OAUTH_CLAIM_EXPIRES_KEY: (
                                    now + timedelta(minutes=5)
                                ).isoformat(),
                            }
                        )
                    elif winner == "demote":
                        writer.get(CompanyMembership, membership_id).role = "viewer"
                    elif winner == "session_cutoff":
                        writer.get(CompanyMembership, membership_id).sessions_valid_after = now
                    elif winner == "company_disabled":
                        writer.get(Company, company_id).is_active = False
                    elif winner in {"disable", "rotate"}:
                        config_type = (
                            TenantGoogleWorkspaceConfiguration
                            if provider_kind == calendar.CalendarProvider.GOOGLE_CALENDAR
                            else TenantOutlookConfiguration
                        )
                        config = writer.get(config_type, config_id)
                        if winner == "disable":
                            config.enabled = False
                        else:
                            config.client_id = "replacement-client"
                    writer.commit()
                if winner in {"new_consent", "expired"}:
                    monkeypatch.setattr(
                        calendar, "_current_time", lambda: now + timedelta(minutes=6)
                    )
                if winner == "new_consent":
                    with Session(pg_engine, expire_on_commit=False) as second:
                        context = context_for(second)
                        with pytest.raises(HTTPException) as replay:
                            complete(
                                second,
                                context=context,
                                code="old-code",
                                state=original_state,
                            )
                        assert replay.value.detail["code"] == "calendar_oauth_callback_consumed"
                        second.rollback()
                        context = context_for(second)
                        fresh_state = calendar._sign_state(context, provider=provider_kind)
                        result = complete(
                            second,
                            context=context,
                            code="fresh-code",
                            state=fresh_state,
                        )
                        assert result.status == "connected"
            finally:
                release.set()
            with pytest.raises(HTTPException) as failure:
                future.result(timeout=15)
            assert failure.value.status_code == (
                502 if old_failure else 401 if winner == "session_cutoff"
                else 403 if winner in {"demote", "company_disabled"} else 409
            )
            if not old_failure and winner in {"disable", "rotate"}:
                assert failure.value.detail["code"] == "calendar_oauth_configuration_changed"
        with Session(pg_engine) as verify:
            row = verify.get(UserCalendarConnection, connection_id)
            assert calendar._oauth_claim_from_connection(row)[1] == (
                "newer-committed-claim" if winner == "new_claim" else None
            )
            if winner == "new_consent":
                assert row.status == CalendarConnectionStatus.CONNECTED
                assert row.provider_account_id == "subject-fresh-code"
                assert (
                    calendar._decrypt_token_payload(row.encrypted_token_ref)["access_token"]
                    == "access-fresh-code"
                )
            else:
                assert row.status == (
                    CalendarConnectionStatus.REVOKED
                    if winner == "revoke"
                    else CalendarConnectionStatus.ERROR
                )
                assert row.provider_account_id is None
            consumed = verify.scalars(
                select(ApiIdempotencyRecord).where(
                    ApiIdempotencyRecord.company_id == company_id,
                )
            ).all()
            assert len(consumed) == (4 if winner == "new_consent" else 2)
            assert all(record.state == "completed" for record in consumed)
        assert calls == (["old-code", "fresh-code"] if winner == "new_consent" else ["old-code"])
    finally:
        release.set()
        set_provider(None)


@pytest.mark.parametrize("provider_path", ["google-calendar", "outlook"])
@pytest.mark.parametrize("legacy_state", [False, True])
def test_unused_consent_before_disconnect_never_restores_a_revoked_connection(
    client, google_provider, outlook_provider, monkeypatch, provider_path, legacy_state,
):
    import jwt

    from caseops_api.core.settings import get_settings

    provider = google_provider if provider_path == "google-calendar" else outlook_provider
    calls = []

    def exchange(*, code):
        calls.append(code)
        if code == "failed-fresh-consent":
            raise calendar.CalendarProviderError("failed fresh consent")
        return {
            "token_payload": {"access_token": f"access-{code}"},
            "provider_account_id": f"subject-{code}",
            "display_email": "calendar@example.test",
            "scopes": list(calendar.GOOGLE_CALENDAR_SCOPES)
            if provider_path == "google-calendar" else list(calendar.OUTLOOK_SCOPES),
        }

    monkeypatch.setattr(provider, "exchange_code", exchange)
    token = bootstrap_company(client)["access_token"]
    base_path = f"/api/calendar/connections/{provider_path}"

    def start():
        response = client.post(f"{base_path}/start", headers=_auth(token))
        assert response.status_code == 200, response.text
        return parse_qs(urlparse(response.json()["auth_url"]).query)["state"][0]

    def complete(state, code):
        return client.get(
            f"{base_path}/callback", headers={**_auth(token), "Accept": "application/json"},
            params={"state": state, "code": code},
        )

    connected = complete(start(), "initial")
    assert connected.status_code == 200, connected.text
    connection_id = connected.json()["connection"]["id"]
    old_state = start()
    if legacy_state:
        payload = jwt.decode(old_state, get_settings().auth_secret, algorithms=["HS256"])
        payload.pop("started_at", None)
        old_state = jwt.encode(payload, get_settings().auth_secret, algorithm="HS256")
    revoked = client.delete(f"/api/calendar/connections/{connection_id}", headers=_auth(token))
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    def assert_old_rejected():
        stale = complete(old_state, "unused-old-code")
        assert stale.status_code == 409, stale.text
        assert stale.json()["code"] == "calendar_oauth_callback_consumed"
        assert "unused-old-code" not in calls

    assert_old_rejected()
    failed = complete(start(), "failed-fresh-consent")
    assert failed.status_code == 502, failed.text
    assert_old_rejected()
    recovered = complete(start(), "fresh-success")
    assert recovered.status_code == 200, recovered.text
    with get_session_factory()() as session:
        ciphertext = session.get(UserCalendarConnection, connection_id).encrypted_token_ref
    assert_old_rejected()
    with get_session_factory()() as session:
        row = session.get(UserCalendarConnection, connection_id)
        assert row.status == CalendarConnectionStatus.CONNECTED
        assert row.provider_account_id == "subject-fresh-success"
        assert row.encrypted_token_ref == ciphertext
    assert calls == ["initial", "failed-fresh-consent", "fresh-success"]


class OAuthBackoffGate:
    """Hold the post-rollback boundary until the coordinator finishes its writer."""

    def __init__(self, monkeypatch):
        from caseops_api.services import assignment_memberships

        self.entered = Event()
        self.resume = Event()
        self.entries = 0
        original_sleep = assignment_memberships.sleep

        def hold_backoff(seconds):
            self.entries += 1
            self.entered.set()
            assert self.resume.wait(15), "coordinator never released OAuth after rollback"
            original_sleep(seconds)

        monkeypatch.setattr(assignment_memberships, "sleep", hold_backoff)

    def wait(self, timeout):
        return self.entered.wait(timeout)

    def release(self):
        self.resume.set()


@pytest.fixture(params=[
    calendar.CalendarProvider.GOOGLE_CALENDAR, calendar.CalendarProvider.OUTLOOK,
])
def pg_calendar_authority(pg_engine, monkeypatch, request):
    from tests.test_postgres_validation import _ip_race_context, _seed_company, _seed_membership

    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        membership_id = _seed_membership(seed, company_id, role="admin")
        seed.commit()
    issued_at = calendar._current_time().timestamp()
    calls = []
    hook = [lambda code: None]
    retrying = OAuthBackoffGate(monkeypatch)

    def context(session):
        value = _ip_race_context(session, company_id=company_id, membership_id=membership_id)
        value.token_issued_at = issued_at
        return value

    def provider(_kind, session, **kwargs):
        def exchange_code(*, code):
            assert not session.in_transaction()
            calls.append(code)
            hook[0](code)
            return {
                "token_payload": {"access_token": f"access-{code}"},
                "provider_account_id": f"subject-{code}",
                "display_email": "calendar@example.test",
                "scopes": list(calendar.GOOGLE_CALENDAR_SCOPES)
                if request.param == calendar.CalendarProvider.GOOGLE_CALENDAR
                else list(calendar.OUTLOOK_SCOPES),
            }
        return SimpleNamespace(configured=True, exchange_code=exchange_code)

    monkeypatch.setattr(calendar, "_provider_for", provider)
    with Session(pg_engine) as seed:
        state = calendar._sign_state(context(seed), provider=request.param)

    def call(*, name, code="race"):
        with Session(pg_engine, expire_on_commit=False) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name},
            )
            session.commit()
            session.execute(text("SET LOCAL lock_timeout = '8s'"))
            return calendar._complete_connection(
                session, context=context(session), code=code, state=state,
                calendar_provider=request.param,
            )

    try:
        yield SimpleNamespace(
            engine=pg_engine, company_id=company_id, membership_id=membership_id,
            context=context, call=call, calls=calls, hook=hook, provider_kind=request.param,
            retrying=retrying,
        )
    finally:
        retrying.release()


@pytest.mark.postgres
def test_postgres_tenant_admin_audit_can_finish_while_oauth_waits(pg_calendar_authority):
    from caseops_api.services.audit import record_audit

    fixture = pg_calendar_authority
    name = f"oauth-tenant-admin-{uuid4().hex[:8]}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with Session(fixture.engine) as admin:
            admin.execute(text("SET LOCAL lock_timeout = '3s'"))
            company = admin.scalar(
                select(Company).where(Company.id == fixture.company_id).with_for_update(of=Company)
            )
            worker = executor.submit(fixture.call, name=name)
            try:
                assert fixture.retrying.wait(10), "OAuth did not encounter the held Company lock"
                record_audit(
                    admin, company_id=fixture.company_id,
                    actor_membership_id=fixture.membership_id,
                    action="company.test_disabled", target_type="company", target_id=company.id,
                )
                company.is_active = False
                admin.commit()
            except BaseException:
                admin.rollback()
                raise
            finally:
                fixture.retrying.release()
        with pytest.raises(HTTPException) as failure:
            worker.result(timeout=10)
    assert failure.value.status_code == 403
    assert fixture.calls == []
    with Session(fixture.engine) as verify:
        assert verify.scalar(select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == fixture.company_id,
        )) is None


@pytest.mark.postgres
def test_postgres_failure_cleanup_and_disconnect_share_authority_order(
    pg_calendar_authority, monkeypatch,
):
    fixture = pg_calendar_authority
    cleanup_locked, allow_audit = Event(), Event()
    original_audit = calendar.record_audit

    def fail_exchange(code):
        raise calendar.CalendarProviderError("expected failure")

    fixture.hook[0] = fail_exchange

    def paused_audit(*args, **kwargs):
        if kwargs.get("action") == "calendar.connection.oauth_failed":
            cleanup_locked.set()
            assert allow_audit.wait(15), "coordinator never released failure cleanup"
        return original_audit(*args, **kwargs)

    monkeypatch.setattr(calendar, "record_audit", paused_audit)
    name = f"oauth-disconnect-{uuid4().hex[:8]}"

    def disconnect():
        with Session(fixture.engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name},
            )
            session.commit()
            session.execute(text("SET LOCAL lock_timeout = '8s'"))
            row = session.scalar(select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == fixture.company_id,
            ))
            return calendar.revoke_connection(
                session, context=fixture.context(session), connection_id=row.id,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        failed_callback = executor.submit(fixture.call, name="oauth-failing-callback")
        revoked = None
        try:
            try:
                assert cleanup_locked.wait(10), "cleanup never reached its own claim"
                revoked = executor.submit(disconnect)
                assert fixture.retrying.wait(10), "disconnect did not encounter cleanup's lock"
            finally:
                allow_audit.set()
            with pytest.raises(HTTPException) as failure:
                failed_callback.result(timeout=15)
            assert failure.value.status_code == 502
        finally:
            fixture.retrying.release()
        assert revoked is not None and revoked.result(timeout=15).status == "revoked"
    assert fixture.calls == ["race"]
    with Session(fixture.engine) as verify:
        row = verify.scalar(select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == fixture.company_id,
        ))
        assert row.status == CalendarConnectionStatus.REVOKED
        assert row.encrypted_token_ref is None


@pytest.mark.postgres
def test_postgres_oauth_cannot_invert_real_matter_disposal_locks(
    pg_calendar_authority, monkeypatch,
):
    from caseops_api.db.models import Matter, PrivateProjectionEvent
    from caseops_api.schemas.matters import MatterLifecycleStatusRequest
    from caseops_api.services import matters, private_retrieval

    fixture = pg_calendar_authority
    with Session(fixture.engine) as seed:
        matter = Matter(
            company_id=fixture.company_id, title="OAuth lock-order regression",
            matter_code=f"OAUTH-{uuid4().hex[:8]}", status="active", practice_area="Civil",
            forum_level="high_court", is_active=True,
        )
        seed.add(matter)
        seed.flush()
        matter_id, updated_at = matter.id, matter.updated_at
        private_retrieval.ensure_active_private_generation(seed, company_id=fixture.company_id)
        seed.commit()
    actor_locked, continue_disposal = Event(), Event()
    private_company_locked = Event()
    original_actor = matters._lock_matter_mutation_actor
    original_private_company = private_retrieval._lock_private_company

    def observe_private_company(session, **kwargs):
        value = original_private_company(session, **kwargs)
        if kwargs["company_id"] == fixture.company_id:
            private_company_locked.set()
        return value

    monkeypatch.setattr(private_retrieval, "_lock_private_company", observe_private_company)

    def pause_actor(*args, **kwargs):
        value = original_actor(*args, **kwargs)
        actor_locked.set()
        assert continue_disposal.wait(15), "coordinator never released Matter disposal"
        return value

    monkeypatch.setattr(matters, "_lock_matter_mutation_actor", pause_actor)

    def dispose():
        with Session(fixture.engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '8s'"))
            return matters.transition_matter_lifecycle_status(
                session, context=fixture.context(session), matter_id=matter_id,
                payload=MatterLifecycleStatusRequest(
                    to_status="disposed", expected_from_status="active",
                    expected_updated_at=updated_at,
                    reason="Deterministic OAuth versus Matter disposal lock-order regression.",
                ),
            )

    name = f"oauth-matter-{uuid4().hex[:8]}"
    with ThreadPoolExecutor(max_workers=2) as executor:
        disposal = executor.submit(dispose)
        callback = None
        try:
            try:
                assert actor_locked.wait(10), "disposal never fenced the actor"
                callback = executor.submit(fixture.call, name=name)
                assert fixture.retrying.wait(10), "OAuth did not encounter disposal's actor lock"
                # Deliberately exceed the real 25ms backoff. The handshake, not
                # scheduler timing, must keep a second acquisition out of the probe.
                sleep(0.075)
                assert fixture.retrying.entries == 1
                with Session(fixture.engine) as probe:
                    assert probe.scalar(select(Company).where(
                        Company.id == fixture.company_id,
                    ).with_for_update(of=Company, nowait=True)) is not None
            finally:
                continue_disposal.set()
            assert disposal.result(timeout=15).status == "disposed"
            assert private_company_locked.is_set(), "disposal skipped private Company lock"
        finally:
            fixture.retrying.release()
        assert callback is not None and callback.result(timeout=15).status == "connected"
    assert fixture.calls == ["race"]
    with Session(fixture.engine) as verify:
        assert verify.get(Matter, matter_id).status == "disposed"
        assert verify.get(Matter, matter_id).is_active is False
        event = verify.scalar(select(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture.company_id,
            PrivateProjectionEvent.target_id == matter_id,
            PrivateProjectionEvent.event_type == "tombstoned",
        ))
        assert event is not None and event.status == "applied"


@pytest.mark.postgres
def test_postgres_oauth_and_real_team_scoping_both_finish(pg_calendar_authority, monkeypatch):
    from caseops_api.services import teams

    fixture = pg_calendar_authority
    company_locked, continue_scoping = Event(), Event()
    original_memberships = teams.lock_company_memberships_for_assignment

    def pause_before_memberships(*args, **kwargs):
        company_locked.set()
        assert continue_scoping.wait(15), "coordinator never released team scoping"
        return original_memberships(*args, **kwargs)

    monkeypatch.setattr(teams, "lock_company_memberships_for_assignment", pause_before_memberships)

    def toggle_scoping():
        with Session(fixture.engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '8s'"))
            value = teams.set_team_scoping(
                session, context=fixture.context(session), enabled=True,
            )
            session.commit()
            return value

    name = f"oauth-team-scoping-{uuid4().hex[:8]}"
    with ThreadPoolExecutor(max_workers=2) as executor:
        toggled = executor.submit(toggle_scoping)
        callback = None
        try:
            try:
                assert company_locked.wait(10), "team scoping never locked Company"
                callback = executor.submit(fixture.call, name=name)
                assert fixture.retrying.wait(10), "OAuth did not encounter team-scoping's lock"
                sleep(0.075)
                assert fixture.retrying.entries == 1
                # OAuth must release Membership before the Company writer continues.
                with Session(fixture.engine) as probe:
                    assert probe.scalar(select(CompanyMembership).where(
                        CompanyMembership.id == fixture.membership_id,
                    ).with_for_update(of=CompanyMembership, nowait=True)) is not None
            finally:
                continue_scoping.set()
            assert toggled.result(timeout=15) is True
        finally:
            fixture.retrying.release()
        assert callback is not None and callback.result(timeout=15).status == "connected"
    assert fixture.calls == ["race"]
    with Session(fixture.engine) as verify:
        assert verify.get(Company, fixture.company_id).team_scoping_enabled is True


@pytest.mark.postgres
def test_postgres_user_session_revocation_cannot_cycle_with_oauth(pg_calendar_authority):
    from caseops_api.db.models import User
    from caseops_api.services.identity import revoke_user_sessions

    fixture = pg_calendar_authority
    name = f"oauth-session-revoke-{uuid4().hex[:8]}"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with Session(fixture.engine) as writer:
            writer.execute(text("SET LOCAL lock_timeout = '3s'"))
            user_id = writer.get(CompanyMembership, fixture.membership_id).user_id
            writer.scalar(select(User).where(User.id == user_id).with_for_update(of=User))
            callback = executor.submit(fixture.call, name=name)
            try:
                assert fixture.retrying.wait(10), "OAuth did not encounter revocation's User lock"
                # The failed User NOWAIT must also release the earlier Membership lock.
                writer.scalar(select(CompanyMembership).where(
                    CompanyMembership.id == fixture.membership_id,
                ).with_for_update(of=CompanyMembership, nowait=True))
                revoke_user_sessions(writer, user_id=user_id)
                writer.commit()
            except BaseException:
                writer.rollback()
                raise
            finally:
                fixture.retrying.release()
        with pytest.raises(HTTPException) as failure:
            callback.result(timeout=10)
        assert failure.value.status_code == 401
    assert fixture.calls == []
