"""Readiness may adopt peer rotation, never a replacement OAuth consent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from caseops_api.db.models import (
    AuditEvent,
    CalendarConnectionStatus,
    TenantOutlookConfiguration,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import calendar_sync as calendar
from tests.test_auth_company import bootstrap_company
from tests.test_legalworkspace_calendar_sync import (
    StubOutlookProvider,
    _auth,
    _configure_ready_outlook,
    _session_context,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def client(isolated_postgres_client, http_pg_engine):
    assert http_pg_engine.dialect.name == "postgresql"
    return isolated_postgres_client


@pytest.fixture
def peer_readiness(client):
    actor = bootstrap_company(client)
    token = str(actor["access_token"])
    company_id = str(actor["company"]["id"])
    workers = []
    graph_transactions = []
    graph_tokens = []
    refresh_transactions = []
    replacement_code = "replacement-" + uuid4().hex
    replacement_account = ["outlook-user-1"]

    class Provider(StubOutlookProvider):
        def exchange_code(self, *, code):
            if code == "oauth-code":
                return super().exchange_code(code=code)
            assert code == replacement_code
            return {
                "token_payload": {
                    "access_token": "replacement-fixture-access",
                    "refresh_token": "replacement-fixture-refresh",
                    "expires_in": 3600,
                },
                "provider_account_id": replacement_account[0],
                "display_email": "replacement@example.test",
                "scopes": ["offline_access", "User.Read", "Calendars.ReadWrite"],
            }

        def refresh_access_token(self, *, token_payload, scopes):
            refresh_transactions.append([worker.in_transaction() for worker in workers])
            assert refresh_transactions[-1] == [False, False]
            assert token_payload["refresh_token"] == "prior-fixture-refresh"
            assert scopes == ["offline_access", "User.Read", "Calendars.ReadWrite"]
            return calendar._stamp_calendar_token_expiry({
                **token_payload,
                "access_token": "peer-fixture-access",
                "refresh_token": "peer-fixture-refresh",
                "expires_in": 3600,
            })

        def validate_connection(self, *, token_payload):
            if not workers:
                return super().validate_connection(token_payload=token_payload)
            graph_transactions.append([worker.in_transaction() for worker in workers])
            graph_tokens.append(token_payload["access_token"])
            return {
                "provider_account_id": replacement_account[0],
                "display_email": "replacement@example.test",
            }

    provider = Provider()
    try:
        connection_id = _configure_ready_outlook(client, token, provider)
        factory = get_session_factory()
        consent_time = datetime.now(UTC)
        with factory() as setup:
            connection = setup.get(UserCalendarConnection, connection_id)
            assert connection is not None
            payload = calendar._decrypt_token_payload(connection.encrypted_token_ref)
            payload.update({
                "access_token": "expired-fixture-access",
                "refresh_token": "prior-fixture-refresh",
                "expires_in": 3600,
                calendar._CALENDAR_TOKEN_EXPIRES_KEY:
                    (consent_time - timedelta(hours=2)).isoformat(),
            })
            connection.encrypted_token_ref = calendar._encrypt_token_payload(payload)
            connection.connected_at = consent_time
            setup.commit()
            original_account = connection.provider_account_id
            original_encrypted = connection.encrypted_token_ref
        yield {
            "client": client, "token": token, "company_id": company_id,
            "connection_id": connection_id, "factory": factory, "workers": workers,
            "graph_transactions": graph_transactions, "graph_tokens": graph_tokens,
            "refresh_transactions": refresh_transactions,
            "replacement_code": replacement_code,
            "replacement_account": replacement_account,
            "consent_time": consent_time, "original_account": original_account,
            "original_encrypted": original_encrypted,
        }
    finally:
        calendar.set_outlook_provider_for_tests(None)


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _interleave_before_authority(monkeypatch, fixture, worker, operation):
    original = calendar._calendar_refresh_authority
    entered = []

    def fenced(session, **kwargs):
        assert session.get_bind().dialect.name == "postgresql"
        if session is worker and not entered:
            entered.append(True)
            assert session.in_transaction() is False
            operation()
        # The real Company/Membership/configuration/connection fences still run.
        return original(session, **kwargs)

    monkeypatch.setattr(calendar, "_calendar_refresh_authority", fenced)
    return entered


def test_peer_same_consent_rotation_validates_without_transaction(peer_readiness, monkeypatch):
    fixture = peer_readiness
    factory = fixture["factory"]
    peer_receipt = []
    with factory() as worker:
        context = _session_context(worker, fixture["company_id"])
        worker_pid = worker.scalar(text("SELECT pg_backend_pid()"))
        worker.commit()
        fixture["workers"].append(worker)

        def rotate():
            peer_engine = create_engine(worker.get_bind().url, poolclass=NullPool)
            try:
                with factory(bind=peer_engine) as peer:
                    fixture["workers"].append(peer)
                    peer_pid = peer.scalar(text("SELECT pg_backend_pid()"))
                    assert peer_pid != worker_pid
                    connection = peer.get(UserCalendarConnection, fixture["connection_id"])
                    assert connection is not None
                    peer_context = _session_context(peer, fixture["company_id"])
                    payload = calendar._decrypt_token_payload(connection.encrypted_token_ref)
                    peer.commit()
                    result = calendar._fresh_calendar_token(
                        peer, context=peer_context, connection=connection, token_payload=payload,
                    )
                    assert result[0]["access_token"] == "peer-fixture-access"
                    assert result[1] is True
                    assert peer.in_transaction() is False
                    peer_receipt.append(True)
            finally:
                if len(fixture["workers"]) > 1:
                    fixture["workers"].remove(peer)
                peer_engine.dispose()

        entered = _interleave_before_authority(monkeypatch, fixture, worker, rotate)
        result = calendar.test_outlook_tenant_configuration(worker, context=context)
        assert entered == [True] and peer_receipt == [True]
        assert result.status == "passed"
        assert fixture["refresh_transactions"] == [[False, False]]
        assert fixture["graph_tokens"] == ["peer-fixture-access"]
        assert fixture["graph_transactions"] == [[False]], (
            "Readiness retained a database transaction during Graph validation",
            fixture["graph_transactions"],
        )
        assert worker.in_transaction() is False
    with factory() as verify:
        connection = verify.get(UserCalendarConnection, fixture["connection_id"])
        assert connection is not None
        assert connection.provider_account_id == fixture["original_account"]
        assert _aware(connection.connected_at) == fixture["consent_time"]
        assert connection.status == CalendarConnectionStatus.CONNECTED
        configuration = verify.scalar(select(TenantOutlookConfiguration).where(
            TenantOutlookConfiguration.company_id == fixture["company_id"],
        ))
        assert configuration is not None and configuration.last_test_status == "passed"


@pytest.mark.parametrize("replacement", ["different_account", "same_account_same_connected_at"])
def test_new_consent_before_authority_is_stale_without_graph(
    peer_readiness, monkeypatch, replacement,
):
    fixture = peer_readiness
    factory = fixture["factory"]
    replacement_receipt = []
    if replacement == "different_account":
        fixture["replacement_account"][0] = "replacement-account-" + uuid4().hex

    class SameConsentTime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = fixture["consent_time"]
            return fixed.replace(tzinfo=None) if tz is None else fixed.astimezone(tz)

    with factory() as worker:
        context = _session_context(worker, fixture["company_id"])
        worker.commit()
        fixture["workers"].append(worker)

        def replace():
            with monkeypatch.context() as clock:
                if replacement == "same_account_same_connected_at":
                    clock.setattr(calendar, "datetime", SameConsentTime)
                other = TestClient(fixture["client"].app, headers={
                    "X-CaseOps-Automated-Test": "no-paid-providers",
                })
                try:
                    start = other.post(
                        "/api/calendar/connections/outlook/start", headers=_auth(fixture["token"]),
                    )
                    assert start.status_code == 200, start.text
                    state = parse_qs(urlparse(start.json()["auth_url"]).query)["state"][0]
                    callback = other.get(
                        "/api/calendar/connections/outlook/callback",
                        headers=_auth(fixture["token"]),
                        params={"state": state, "code": fixture["replacement_code"]},
                    )
                    assert callback.status_code == 200, callback.text
                    assert callback.json()["connection"]["id"] == fixture["connection_id"]
                    replacement_receipt.append(callback.json()["connection"]["id"])
                finally:
                    other.close()
            with factory() as verify:
                current = verify.get(UserCalendarConnection, fixture["connection_id"])
                assert current is not None
                assert current.status == CalendarConnectionStatus.CONNECTED
                assert current.provider_account_id == fixture["replacement_account"][0]
                assert current.encrypted_token_ref != fixture["original_encrypted"]
                if replacement == "same_account_same_connected_at":
                    assert _aware(current.connected_at) == fixture["consent_time"]

        entered = _interleave_before_authority(monkeypatch, fixture, worker, replace)
        rejected = None
        try:
            calendar.test_outlook_tenant_configuration(worker, context=context)
        except HTTPException as exc:
            rejected = exc
        finally:
            worker.rollback()
        assert entered == [True] and replacement_receipt == [fixture["connection_id"]]
        assert fixture["refresh_transactions"] == []
        assert rejected is not None, "A replaced OAuth consent must make the readiness claim stale"
        assert rejected.status_code == 409
        assert isinstance(rejected.detail, dict)
        assert rejected.detail["code"] == "outlook_readiness_probe_stale"
        assert fixture["graph_tokens"] == [], "A stale consent must produce zero Graph validations"
    with factory() as verify:
        current = verify.get(UserCalendarConnection, fixture["connection_id"])
        assert current is not None
        assert current.status == CalendarConnectionStatus.CONNECTED
        assert current.provider_account_id == fixture["replacement_account"][0]
        payload = calendar._decrypt_token_payload(current.encrypted_token_ref)
        assert payload["access_token"] == "replacement-fixture-access"
        configuration = verify.scalar(select(TenantOutlookConfiguration).where(
            TenantOutlookConfiguration.company_id == fixture["company_id"],
        ))
        assert configuration is not None and configuration.last_test_status != "passed"
        passed = list(verify.scalars(select(AuditEvent).where(
            AuditEvent.company_id == fixture["company_id"],
            AuditEvent.action == "outlook.configuration.test_passed",
        )))
        assert len(passed) == 1, "Only the setup probe may retain a successful readiness audit"
