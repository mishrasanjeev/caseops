"""Calendar credential containment and current-authority fences on PostgreSQL."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarConnectionStatus,
    TenantOutlookConfiguration,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import calendar_sync
from tests import test_ip_calendar_drift as drift_assertions
from tests import test_legalworkspace_calendar_sync as readiness_assertions
from tests.test_auth_company import bootstrap_company

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _calendar_containment_runtime(monkeypatch):
    # Imported assertion functions do not carry their module's autouse fixtures.
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ROLLOUT_EXPIRES_AT", "2099-12-31T00:00:00Z")
    original_send = httpx.Client.send

    def local_only_send(self, request, **kwargs):
        assert request.url.host == "testserver", "Calendar fixtures cannot use external HTTP."
        return original_send(self, request, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", local_only_send)
    get_settings.cache_clear()
    try:
        yield
    finally:
        calendar_sync.set_google_calendar_provider_for_tests(None)
        calendar_sync.set_outlook_provider_for_tests(None)
        get_settings.cache_clear()


@pytest.fixture
def native_client(isolated_postgres_client, http_pg_engine):
    assert http_pg_engine.dialect.name == "postgresql"
    with get_session_factory()() as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert session.get_bind().url.database == http_pg_engine.url.database
    return isolated_postgres_client


@pytest.mark.parametrize(
    "damaged_token_kind",
    ["invalid_envelope", "malformed_json", "refresh_rejected", "errored_connection"],
)
def test_postgres_drift_contains_damaged_credential_and_continues_healthy_connection(
    native_client, damaged_token_kind,
):
    drift_assertions.test_uj62_exc03a_a_damaged_token_does_not_abort_other_connections(
        native_client, damaged_token_kind,
    )


@pytest.mark.parametrize(
    "damaged_token_kind", ["invalid_envelope", "malformed_json", "refresh_rejected"],
)
def test_postgres_failed_readiness_replaces_prior_pass_without_provider_probe(
    native_client, monkeypatch, damaged_token_kind,
):
    readiness_assertions.test_admin_outlook_readiness_corrupt_token_records_safe_failure(
        native_client, monkeypatch, damaged_token_kind,
    )


def test_postgres_new_consent_wins_during_rejected_readiness_refresh(
    native_client, monkeypatch,
):
    actor = bootstrap_company(native_client)
    token = str(actor["access_token"])
    provider = readiness_assertions.StubOutlookProvider()
    connection_id = readiness_assertions._configure_ready_outlook(native_client, token, provider)
    factory = get_session_factory()
    with factory() as seed:
        connection = seed.get(UserCalendarConnection, connection_id)
        assert connection is not None
        connection.encrypted_token_ref = calendar_sync._encrypt_token_payload({
            "access_token": "expired-native-access",
            "refresh_token": "rejected-native-refresh",
            calendar_sync._CALENDAR_TOKEN_EXPIRES_KEY:
                (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        })
        seed.commit()

    calls = []
    new_credentials = []
    consent_errors = []
    new_code = f"native-consent-{uuid4().hex}"

    def fresh_consent(*, code):
        assert code == new_code
        return {
            "token_payload": {
                "access_token": "newly-consented-native-access",
                "refresh_token": "newly-consented-native-refresh",
                "expires_in": 3600,
            },
            "provider_account_id": "newly-consented-native-account",
            "display_email": "native-owner@example.test",
            "scopes": ["offline_access", "User.Read", "Calendars.ReadWrite"],
        }

    def reject_after_new_consent(*, token_payload, scopes):
        calls.append("refresh")
        assert token_payload[calendar_sync._CALENDAR_REFRESH_CLAIM_KEY]["id"]
        # Run the canonical OAuth start/callback while the old provider POST
        # is outside its transaction. A new consent owns the entire credential.
        try:
            headers = readiness_assertions._auth(token)
            started = native_client.post(
                "/api/calendar/connections/outlook/start", headers=headers,
            )
            assert started.status_code == 200, started.text
            assert started.json()["provider_available"] is True
            state = parse_qs(urlparse(started.json()["auth_url"]).query)["state"][0]
            completed = native_client.get(
                "/api/calendar/connections/outlook/callback", headers=headers,
                params={"code": new_code, "state": state},
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["connection"]["id"] == connection_id
        except Exception as error:
            consent_errors.append(error)
            raise
        with factory() as observer:
            assert observer.get_bind().dialect.name == "postgresql"
            current = observer.get(UserCalendarConnection, connection_id)
            assert current is not None
            replacement = calendar_sync._decrypt_token_payload(current.encrypted_token_ref)
            assert replacement["access_token"] == "newly-consented-native-access"
            assert replacement["refresh_token"] == "newly-consented-native-refresh"
            assert calendar_sync._CALENDAR_REFRESH_CLAIM_KEY not in replacement
            new_credentials.append((current.encrypted_token_ref, replacement))
        raise calendar_sync.CalendarProviderError("unsafe-provider-credential")

    def forbidden_probe(**kwargs):
        calls.append("probe")
        raise AssertionError("Stale refresh must not probe the replacement credential.")

    monkeypatch.setattr(provider, "refresh_access_token", reject_after_new_consent, raising=False)
    monkeypatch.setattr(provider, "exchange_code", fresh_consent)
    monkeypatch.setattr(provider, "validate_connection", forbidden_probe)
    response = native_client.post(
        "/api/admin/outlook-configuration/test",
        headers=readiness_assertions._auth(token),
    )
    assert not consent_errors, str(consent_errors)
    assert len(new_credentials) == 1, "Fresh consent did not replace the credential."
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "outlook_readiness_probe_stale"
    assert calls == ["refresh"]
    with factory() as verify:
        current = verify.get(UserCalendarConnection, connection_id)
        assert current is not None
        assert current.status == CalendarConnectionStatus.CONNECTED
        assert current.encrypted_token_ref == new_credentials[0][0]
        assert calendar_sync._decrypt_token_payload(current.encrypted_token_ref) == (
            new_credentials[0][1]
        )
        assert calendar_sync._CALENDAR_REFRESH_CLAIM_KEY not in new_credentials[0][1]
        configuration = verify.scalar(select(TenantOutlookConfiguration))
        assert configuration is not None
        assert configuration.last_test_status != "passed"
    assert "unsafe-provider-credential" not in response.text
    assert "newly-consented-native" not in response.text
