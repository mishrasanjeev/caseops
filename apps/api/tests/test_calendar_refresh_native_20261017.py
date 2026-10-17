"""The unchanged refresh HTTP race assertions must also hold on PostgreSQL."""

import pytest

from caseops_api.db.models import UserCalendarConnection
from tests import test_calendar_refresh_20261017 as refresh_assertions
from tests.test_legalworkspace_calendar_sync import _auth, _session_context

pytestmark = pytest.mark.postgres
expired_calendar = refresh_assertions.expired_calendar


@pytest.fixture
def client(isolated_postgres_client, http_pg_engine):
    assert http_pg_engine.dialect.name == "postgresql"
    return isolated_postgres_client


def test_native_encrypted_rotation(expired_calendar):
    refresh_assertions.test_expired_calendar_refreshes_once_and_persists_encrypted_rotation(
        expired_calendar
    )


def test_native_unknown_post_is_not_retried(expired_calendar):
    refresh_assertions.test_expired_calendar_unknown_event_post_is_not_retried(expired_calendar)


def test_native_capability_loss_wins(expired_calendar):
    refresh_assertions.test_lost_calendar_capability_during_refresh_prevents_event(expired_calendar)


def test_native_newer_credentials_win(expired_calendar):
    refresh_assertions.test_newer_credential_during_refresh_is_not_overwritten(expired_calendar)


def test_native_rejected_refresh_requires_reconnect(expired_calendar):
    refresh_assertions.test_rejected_refresh_has_zero_event_writes_and_requires_reconnect(
        expired_calendar
    )


def test_native_revocation_wins(expired_calendar):
    refresh_assertions.test_revocation_during_refresh_wins_without_event_or_rotation_publish(
        expired_calendar
    )


def test_pending_refresh_claim_prevents_a_second_token_post(expired_calendar):
    from caseops_api.services import calendar_sync as calendar

    fixture = expired_calendar
    observed = []

    def competing_refresh():
        with fixture["factory"]() as peer:
            assert peer.get_bind().dialect.name == "postgresql"
            connection = peer.get(UserCalendarConnection, fixture["connection_id"])
            context = _session_context(peer, connection.company_id)
            token = calendar._decrypt_token_payload(connection.encrypted_token_ref)
            peer.commit()
            with pytest.raises(calendar.CalendarRefreshError, match="pending or uncertain"):
                calendar._fresh_calendar_token(
                    peer, context=context, connection=connection, token_payload=token,
                )
            observed.append(True)

    fixture["grant_callback"][0] = competing_refresh
    response = fixture["client"].post(fixture["endpoint"], headers=_auth(fixture["token"]))
    assert response.status_code == 200, response.text
    assert response.json()["sync"]["sync_status"] == "synced"
    assert observed == [True]
    assert fixture["calls"] == ["refresh", "event"]
