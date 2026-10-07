"""BUG-003/004 adjacent Gmail/Drive callback recovery, without provider traffic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    MembershipRole,
    TenantGoogleWorkspaceConfiguration,
    User,
    UserDriveConnection,
    UserMailboxConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import drive_sync, gmail_sync
from caseops_api.services.audit import record_audit
from caseops_api.services.calendar_sync import _decrypt_token_payload, _encrypt_secret
from caseops_api.services.identity import get_session_context
from tests.test_legalworkspace_calendar_sync import _bootstrap_company


class WorkerInterrupted(BaseException):
    """Simulate process death, which ordinary exception cleanup cannot catch."""


class OAuthHarness:
    def __init__(self, client, monkeypatch, kind):
        self.module = gmail_sync if kind == "gmail" else drive_sync
        self.model = UserMailboxConnection if kind == "gmail" else UserDriveConnection
        self.complete = (
            self.module.complete_gmail_connection
            if kind == "gmail"
            else self.module.complete_google_drive_connection
        )
        self.revoke = (
            self.module.revoke_gmail_connection
            if kind == "gmail"
            else self.module.revoke_google_drive_connection
        )
        self.kind = kind
        self.scopes = list(
            gmail_sync.GMAIL_SCOPES if kind == "gmail" else drive_sync.GOOGLE_DRIVE_SCOPES
        )
        self.calls = []
        self.hook = lambda code: None
        self.now = datetime.now(UTC)
        monkeypatch.setattr(self.module, "_oauth_now", lambda: self.now)
        monkeypatch.setattr(
            self.module,
            "_gmail_provider" if kind == "gmail" else "_drive_provider",
            self.provider,
        )
        prefix = "CASEOPS_GMAIL" if kind == "gmail" else "CASEOPS_GOOGLE_DRIVE"
        for suffix, value in (
            ("CLIENT_ID", "local-client"),
            ("CLIENT_SECRET", "local-client-secret"),
            ("REDIRECT_URI", "https://api.caseops.ai/api/drive/google/callback"),
        ):
            monkeypatch.setenv(prefix + "_" + suffix, value)
        get_settings.cache_clear()
        identity = uuid4().hex
        boot = _bootstrap_company(client, slug="oauth-" + identity, email=identity + "@example.com")
        self.membership_id = boot["membership"]["id"]
        self.company_id = boot["company"]["id"]
        self.user_id = boot["user"]["id"]
        self.issued_at = datetime.now(UTC).timestamp()
        self.factory = get_session_factory()
        with self.factory() as session:
            session.add(
                TenantGoogleWorkspaceConfiguration(
                    company_id=self.company_id,
                    client_id="local-client",
                    encrypted_client_secret_ref=_encrypt_secret("local-client-secret"),
                    gmail_redirect_uri="https://api.caseops.ai/api/mailbox/gmail/callback",
                    drive_redirect_uri="https://api.caseops.ai/api/drive/google/callback",
                    enabled=True,
                    gmail_enabled=True,
                    drive_enabled=True,
                )
            )
            session.commit()

    def provider(self, session, **kwargs):
        def exchange_code(*, code):
            assert not session.in_transaction(), "OAuth transport retained a DB transaction"
            self.calls.append(code)
            result = self.hook(code)
            if result is not None:
                return result
            return {
                "token_payload": {
                    "access_token": "access-" + code,
                    "refresh_token": "refresh-" + code,
                },
                "provider_account_id": "account-" + code,
                "display_email": "local@example.test",
                "scopes": self.scopes,
            }

        return SimpleNamespace(configured=True, exchange_code=exchange_code)

    def context(self, session):
        return get_session_context(session, self.membership_id, token_issued_at=self.issued_at)

    def state(self):
        with self.factory() as session:
            return self.module._sign_state(self.context(session))

    def call(self, state, code):
        with self.factory() as session:
            return self.complete(session, context=self.context(session), state=state, code=code)

    def named_call(self, state, code, name):
        with self.factory() as session:
            engine = session.get_bind()
        # Authority retries roll back, so retain observer identity on one physical connection.
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            connection.commit()
            try:
                with self.factory(bind=connection) as session:
                    return self.complete(
                        session, context=self.context(session), state=state, code=code
                    )
            finally:
                connection.rollback()
                connection.execute(text("RESET application_name"))
                connection.commit()

    def row(self):
        with self.factory() as session:
            row = session.scalar(select(self.model).where(self.model.company_id == self.company_id))
            assert row is not None
            token = (
                _decrypt_token_payload(row.encrypted_token_ref) if row.encrypted_token_ref else {}
            )
            return SimpleNamespace(
                id=row.id,
                status=row.status,
                token=token,
                ciphertext=row.encrypted_token_ref,
                connected_at=row.connected_at,
            )

    def disconnect(self):
        with self.factory() as session:
            return self.revoke(session, context=self.context(session), connection_id=self.row().id)

    def audit_count(self):
        with self.factory() as session:
            return len(
                list(
                    session.scalars(
                        select(AuditEvent).where(
                            AuditEvent.company_id == self.company_id,
                            AuditEvent.action
                            == (
                                "mailbox.gmail.connected"
                                if self.kind == "gmail"
                                else "drive.google.connected"
                            ),
                        )
                    )
                )
            )


@pytest.fixture(params=["gmail", "drive"])
def harness(client, monkeypatch, request):
    return OAuthHarness(client, monkeypatch, request.param)


@pytest.fixture(params=["gmail", "drive"])
def pg_harness(isolated_postgres_client, monkeypatch, request):
    return OAuthHarness(isolated_postgres_client, monkeypatch, request.param)


@pytest.fixture
def oauth_retrying(monkeypatch):
    from caseops_api.services import assignment_memberships

    retrying = Event()
    original_sleep = assignment_memberships.sleep

    def observe_backoff(seconds):
        retrying.set()
        original_sleep(seconds)

    monkeypatch.setattr(assignment_memberships, "sleep", observe_backoff)
    return retrying


def _assert_error(harness, state, code, suffix, status=409):
    with pytest.raises(HTTPException) as captured:
        harness.call(state, code)
    assert captured.value.status_code == status
    assert captured.value.detail["code"].endswith(suffix)
    assert "provider-secret" not in str(captured.value.detail)


@pytest.mark.parametrize("healthy", [False, True])
@pytest.mark.parametrize("failure", ["transport", "malformed", "missing_access", "invalid_scopes"])
def test_failed_exchange_releases_only_own_attempt_and_allows_fresh_start(
    harness, healthy, failure
):
    initial_state = harness.state()
    if healthy:
        harness.call(initial_state, "healthy")
        original = harness.row()
    failed_state = harness.state()

    def fail(code):
        if failure == "transport":
            raise RuntimeError("provider-secret in provider failure")
        if failure == "malformed":
            return ["not-an-object"]
        if failure == "missing_access":
            return {"token_payload": {"refresh_token": "provider-secret"}}
        return {"token_payload": {"access_token": "provider-secret"}, "scopes": "invalid"}

    harness.hook = fail
    _assert_error(harness, failed_state, "failed", "exchange_failed", 502)
    row = harness.row()
    assert row.token[harness.module._OAUTH_META_KEY]["marker"] is None
    assert row.status == ("connected" if healthy else "error")
    if healthy:
        assert row.token["access_token"] == original.token["access_token"]
        assert row.token["refresh_token"] == original.token["refresh_token"]
        assert row.connected_at == original.connected_at
        assert harness.call(initial_state, "healthy").connected
    before = len(harness.calls)
    _assert_error(harness, failed_state, "failed", "attempt_consumed")
    _assert_error(harness, failed_state, "different-code", "attempt_consumed")
    _assert_error(harness, harness.state(), "failed", "attempt_consumed")
    assert len(harness.calls) == before
    harness.hook = lambda code: None
    assert harness.call(harness.state(), "fresh").connected
    assert harness.row().token["access_token"] == "access-fresh"
    assert harness.audit_count() == (2 if healthy else 1)


def test_completed_replay_is_read_only_and_consumption_survives_disconnect(harness):
    state = harness.state()
    first = harness.call(state, "once")
    snapshot = harness.row()
    replay = harness.call(state, "once")
    assert replay.connected and replay.connection.id == first.connection.id
    assert harness.row().connected_at == snapshot.connected_at
    assert harness.row().ciphertext == snapshot.ciphertext
    assert harness.audit_count() == 1
    assert harness.calls == ["once"]
    _assert_error(harness, harness.state(), "once", "attempt_consumed")
    old_unused_state = harness.state()
    harness.disconnect()
    _assert_error(harness, state, "once", "attempt_consumed")
    _assert_error(harness, old_unused_state, "unused", "attempt_consumed")
    _assert_error(harness, harness.state(), "once", "attempt_consumed")
    assert harness.calls == ["once"]
    assert harness.row().status == "revoked"
    assert harness.row().ciphertext is None
    assert harness.call(harness.state(), "new-consent").connected


def test_interrupted_claim_expires_but_single_use_callback_never_retries(harness):
    state = harness.state()

    def die(code):
        raise WorkerInterrupted()

    harness.hook = die
    with pytest.raises(WorkerInterrupted):
        harness.call(state, "interrupted")
    meta = harness.row().token[harness.module._OAUTH_META_KEY]
    assert 0 < meta["expires_at"] - harness.now.timestamp() <= 300
    _assert_error(harness, state, "interrupted", "_in_flight")
    fresh = harness.state()
    _assert_error(harness, fresh, "fresh", "_in_flight")
    harness.now += timedelta(seconds=301)
    _assert_error(harness, state, "interrupted", "attempt_consumed")
    harness.hook = lambda code: None
    assert harness.call(fresh, "fresh").connected
    assert harness.calls == ["interrupted", "fresh"]


def test_success_returned_after_lease_expiry_cannot_publish(harness):
    def expire(code):
        harness.now += timedelta(seconds=301)

    harness.hook = expire
    state = harness.state()
    _assert_error(harness, state, "expired", "finalize_stale")
    row = harness.row()
    assert row.status == "error"
    assert "access_token" not in row.token
    assert row.token[harness.module._OAUTH_META_KEY]["marker"] is None
    assert harness.audit_count() == 0


@pytest.mark.parametrize(
    "failure",
    [
        "token_json",
        "token_shape",
        "profile_json",
        "profile_shape",
        "raw_exception",
        "token_empty",
        "access_numeric",
        "access_blank",
        "token_oversized",
        "refresh_numeric",
        "scope_empty",
        "scope_null",
        "scope_list",
        "scope_partial",
        "scope_broader",
        "profile_empty",
        "account_missing",
        "account_numeric",
        "account_oversized",
        "email_numeric",
        "email_blank",
        "email_invalid",
        "email_oversized",
    ],
)
def test_native_provider_malformed_response_and_raw_exception_release_claim(
    harness,
    monkeypatch,
    failure,
):
    harness.call(harness.state(), "healthy")
    original = harness.row()
    active_session = []
    posts = []
    mode = [failure]

    def native_provider(session, *, context):
        active_session[:] = [session]
        if harness.kind == "gmail":
            return gmail_sync.GoogleGmailProvider(
                gmail_sync._gmail_runtime_config(session, context=context),
            )
        return drive_sync.GoogleDriveProvider(
            drive_sync._google_drive_runtime_config(session, context=context),
        )

    def response(url, *, payload=None, malformed=False):
        request = httpx.Request("GET", url)
        if malformed:
            return httpx.Response(200, content=b"not-json-provider-secret", request=request)
        return httpx.Response(200, json=payload, request=request)

    def post(url, **kwargs):
        assert not active_session[0].in_transaction()
        posts.append(kwargs["data"]["code"])
        if mode[0] == "raw_exception":
            raise RuntimeError("provider-secret unexpected transport failure")
        payload = (
            ["provider-secret"]
            if mode[0] == "token_shape"
            else {
                "access_token": "native-access",
                "refresh_token": "native-refresh",
                "scope": " ".join(harness.scopes),
            }
        )
        if mode[0] == "token_empty":
            payload = {}
        elif mode[0] in {"access_numeric", "access_blank", "token_oversized"}:
            payload["access_token"] = {
                "access_numeric": 123,
                "access_blank": " ",
                "token_oversized": "x" * 65536,
            }[mode[0]]
        elif mode[0] == "refresh_numeric":
            payload["refresh_token"] = 123
        elif mode[0].startswith("scope_"):
            payload["scope"] = {
                "scope_empty": "",
                "scope_null": None,
                "scope_list": harness.scopes,
                "scope_partial": "openid",
                "scope_broader": "https://mail.google.com/"
                if harness.kind == "gmail"
                else "https://www.googleapis.com/auth/drive",
            }[mode[0]]
        return response(url, payload=payload, malformed=mode[0] == "token_json")

    def profile(method, url, **kwargs):
        assert method == "GET"
        assert not active_session[0].in_transaction()
        payload = (
            ["provider-secret"]
            if mode[0] == "profile_shape"
            else (
                {"emailAddress": "native@example.com", "historyId": "1"}
                if harness.kind == "gmail"
                else {
                    "user": {
                        "permissionId": "native-account",
                        "emailAddress": "native@example.com",
                    },
                }
            )
        )
        if mode[0] == "profile_empty":
            payload = {}
        elif mode[0].startswith(("account_", "email_")):
            account = payload if harness.kind == "gmail" else payload["user"]
            subject_key = "emailAddress" if harness.kind == "gmail" else "permissionId"
            if mode[0] == "account_missing":
                account.pop(subject_key)
            elif mode[0] == "account_numeric":
                account[subject_key] = 123
            elif mode[0] == "account_oversized":
                account[subject_key] = "x" * 244 + "@example.com"
            else:
                account["emailAddress"] = {
                    "email_numeric": 123,
                    "email_blank": " ",
                    "email_invalid": "invalid-address",
                    "email_oversized": "x" * 320 + "@a.com",
                }[mode[0]]
        return response(url, payload=payload, malformed=mode[0] == "profile_json")

    monkeypatch.setattr(
        harness.module,
        "_gmail_provider" if harness.kind == "gmail" else "_drive_provider",
        native_provider,
    )
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(harness.module, "request_with_retries", profile)
    state = harness.state()
    _assert_error(harness, state, "failed-native", "exchange_failed", 502)
    row = harness.row()
    assert row.status == "connected"
    assert row.token["access_token"] == original.token["access_token"]
    assert row.token["refresh_token"] == original.token["refresh_token"]
    assert not row.token[harness.module._OAUTH_META_KEY]["marker"]
    _assert_error(harness, state, "failed-native", "attempt_consumed")
    assert posts == ["failed-native"]
    mode[0] = "success"
    assert harness.call(harness.state(), "fresh-native").connected
    assert harness.row().token["access_token"] == "native-access"
    assert harness.audit_count() == 2
    assert posts == ["failed-native", "fresh-native"]


@pytest.mark.parametrize("scope_present", [False, True])
def test_native_provider_accepts_only_documented_omissions(harness, monkeypatch, scope_present):
    token = {"access_token": "access", "refresh_token": "refresh"}
    if scope_present:
        token["scope"] = " ".join(harness.scopes)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kwargs: httpx.Response(
            200,
            json=token,
            request=httpx.Request("POST", url),
        ),
    )
    profile = (
        {"emailAddress": "native@example.com"}
        if harness.kind == "gmail"
        else {"user": {"permissionId": "stable-account"}}
    )
    monkeypatch.setattr(
        harness.module,
        "request_with_retries",
        lambda method, url, **kwargs: httpx.Response(
            200, json=profile, request=httpx.Request(method, url)
        ),
    )
    with harness.factory() as session:
        context = harness.context(session)
        provider = (
            gmail_sync.GoogleGmailProvider(
                gmail_sync._gmail_runtime_config(session, context=context)
            )
            if harness.kind == "gmail"
            else drive_sync.GoogleDriveProvider(
                drive_sync._google_drive_runtime_config(session, context=context)
            )
        )
        session.rollback()
        result = provider.exchange_code(code="code")
    assert result["scopes"] == harness.scopes
    assert result["provider_account_id"] == (
        "native@example.com" if harness.kind == "gmail" else "stable-account"
    )
    assert result["display_email"] == ("native@example.com" if harness.kind == "gmail" else None)


def _change_authority(harness, change):
    if change == "disconnect":
        harness.disconnect()
        return
    with harness.factory() as session:
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        if change in {"membership", "cutoff", "capability"}:
            actor = session.get(CompanyMembership, harness.membership_id)
            if change == "membership":
                actor.is_active = False
            elif change == "cutoff":
                actor.sessions_valid_after = datetime.now(UTC) + timedelta(seconds=1)
            else:
                actor.role = MembershipRole.VIEWER
        elif change == "user":
            session.get(User, harness.user_id).is_active = False
        elif change == "company":
            session.get(Company, harness.company_id).is_active = False
        else:
            config = session.scalar(
                select(TenantGoogleWorkspaceConfiguration).where(
                    TenantGoogleWorkspaceConfiguration.company_id == harness.company_id,
                )
            )
            if change == "config_disabled":
                config.enabled = False
            else:
                config.client_id = "rotated-client"
        session.commit()


@pytest.mark.postgres
@pytest.mark.parametrize("writer", ["matter_disposal", "team_scoping"])
def test_postgres_actual_competing_authority_writers_complete(
    pg_harness, monkeypatch, writer, oauth_retrying
):
    from tests import test_calendar_oauth_recovery_20261008 as calendar_recovery

    harness = pg_harness
    state = harness.state()
    with harness.factory() as session:
        engine = session.get_bind()

    def call(*, name):
        return harness.named_call(state, "race", name).connection

    authority = SimpleNamespace(
        engine=engine,
        company_id=harness.company_id,
        membership_id=harness.membership_id,
        context=harness.context,
        call=call,
        calls=harness.calls,
        retrying=oauth_retrying,
    )
    # Reuse the real writer assertions shared with Calendar, not a simulated lock timeout.
    regression = (
        calendar_recovery.test_postgres_oauth_cannot_invert_real_matter_disposal_locks
        if writer == "matter_disposal"
        else calendar_recovery.test_postgres_oauth_and_real_team_scoping_both_finish
    )
    regression(authority, monkeypatch)
    assert harness.calls == ["race"]
    assert harness.row().status == "connected"
    assert harness.audit_count() == 1


@pytest.mark.postgres
def test_postgres_authority_lock_allows_membership_writer_audit(pg_harness, oauth_retrying):
    harness = pg_harness
    name = "oauth-membership-" + uuid4().hex[:8]
    state = harness.state()
    with ThreadPoolExecutor(max_workers=1) as pool, harness.factory() as writer:
        writer.execute(text("SET LOCAL lock_timeout = '750ms'"))
        writer.scalar(
            select(CompanyMembership)
            .where(CompanyMembership.id == harness.membership_id)
            .with_for_update(of=CompanyMembership)
        )
        callback = pool.submit(harness.named_call, state, "membership-audit-overlap", name)
        try:
            assert oauth_retrying.wait(10), "OAuth did not encounter the locked membership"
            # Matter disposal also explicitly locks Company after its membership fence.
            writer.scalar(
                select(Company).where(Company.id == harness.company_id).with_for_update(of=Company)
            )
            audit = record_audit(
                writer,
                company_id=harness.company_id,
                actor_membership_id=harness.membership_id,
                action="oauth.regression.membership_writer",
                target_type="membership",
                target_id=harness.membership_id,
            )
            audit_id = audit.id
            writer.commit()
        finally:
            writer.rollback()
        assert callback.result(timeout=10).connected
    with harness.factory() as session:
        assert session.get(AuditEvent, audit_id) is not None
    assert harness.calls == ["membership-audit-overlap"]
    assert harness.audit_count() == 1


@pytest.mark.postgres
def test_postgres_authority_lock_allows_company_writer_membership_audit(pg_harness, oauth_retrying):
    harness = pg_harness
    name = "oauth-company-" + uuid4().hex[:8]
    state = harness.state()
    with ThreadPoolExecutor(max_workers=1) as pool, harness.factory() as writer:
        writer.execute(text("SET LOCAL lock_timeout = '750ms'"))
        company = writer.scalar(
            select(Company).where(Company.id == harness.company_id).with_for_update(of=Company)
        )
        callback = pool.submit(harness.named_call, state, "company-audit-overlap", name)
        try:
            assert oauth_retrying.wait(10), "OAuth did not encounter the locked Company"
            audit = record_audit(
                writer,
                company_id=harness.company_id,
                actor_membership_id=harness.membership_id,
                action="oauth.regression.company_writer",
                target_type="company",
                target_id=harness.company_id,
            )
            audit_id = audit.id
            company.is_active = False
            writer.commit()
        finally:
            writer.rollback()
        with pytest.raises(HTTPException) as captured:
            callback.result(timeout=10)
        assert captured.value.status_code == 403
    with harness.factory() as session:
        assert session.get(AuditEvent, audit_id) is not None
        assert session.scalar(
            select(harness.model).where(harness.model.company_id == harness.company_id)
        ) is None
    assert harness.calls == []
    assert harness.audit_count() == 0


@pytest.mark.postgres
@pytest.mark.parametrize(
    "change",
    [
        "disconnect",
        "membership",
        "user",
        "company",
        "cutoff",
        "capability",
        "config_disabled",
        "config_rotated",
    ],
)
def test_postgres_duplicate_and_authority_winner_fence_callback(pg_harness, change):
    harness = pg_harness
    entered, release = Event(), Event()
    state = harness.state()

    def pause(code):
        entered.set()
        assert release.wait(10), "test did not release provider barrier"

    harness.hook = pause
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(harness.call, state, "racing")
        try:
            assert entered.wait(10), "provider was not reached"
            claim = harness.row().token[harness.module._OAUTH_META_KEY]
            assert claim["marker"] and claim["expires_at"] > harness.now.timestamp()
            _assert_error(harness, state, "racing", "_in_flight")
            _change_authority(harness, change)
        finally:
            release.set()
        with pytest.raises(HTTPException) as captured:
            worker.result(timeout=10)
    assert captured.value.status_code == (
        401
        if change == "cutoff"
        else (403 if change in {"company", "membership", "user", "capability"} else 409)
    )
    row = harness.row()
    assert row.status == ("revoked" if change == "disconnect" else "error")
    assert "access_token" not in row.token
    assert not row.token.get(harness.module._OAUTH_META_KEY, {}).get("marker")
    assert harness.calls == ["racing"]
    assert harness.audit_count() == 0


@pytest.mark.postgres
@pytest.mark.parametrize("stale_failure", [False, True])
def test_postgres_new_attempt_wins_over_old_success_or_failure(pg_harness, stale_failure):
    harness = pg_harness
    entered, release = Event(), Event()
    state = harness.state()
    fresh = harness.state()

    def pause(code):
        if code == "old":
            entered.set()
            assert release.wait(10)
            if stale_failure:
                raise RuntimeError("provider-secret")

    harness.hook = pause
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(harness.call, state, "old")
        try:
            assert entered.wait(10)
            harness.now += timedelta(seconds=301)
            assert harness.call(fresh, "replacement").connected
            snapshot = harness.row()
        finally:
            release.set()
        with pytest.raises(HTTPException) as captured:
            worker.result(timeout=10)
    assert captured.value.status_code == (502 if stale_failure else 409)
    assert harness.row().ciphertext == snapshot.ciphertext
    assert harness.row().status == "connected"
    assert harness.row().token["access_token"] == "access-replacement"
    assert harness.audit_count() == 1


@pytest.mark.postgres
@pytest.mark.parametrize("change", ["disconnect", "membership", "cutoff", "config_disabled"])
def test_postgres_failed_reconnect_after_revocation_never_restores_old_credentials(
    pg_harness, change
):
    harness = pg_harness
    harness.call(harness.state(), "healthy")
    entered, release = Event(), Event()

    def fail(code):
        entered.set()
        assert release.wait(10)
        raise RuntimeError("provider-secret")

    harness.hook = fail
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(harness.call, harness.state(), "bad-reconnect")
        try:
            assert entered.wait(10)
            _change_authority(harness, change)
        finally:
            release.set()
        with pytest.raises(HTTPException, match="502"):
            worker.result(timeout=10)
    row = harness.row()
    assert row.status == ("revoked" if change == "disconnect" else "error")
    if change == "disconnect":
        assert row.ciphertext is None
    else:
        assert row.token["access_token"] == "access-healthy"
        assert not row.token[harness.module._OAUTH_META_KEY]["marker"]
    assert harness.audit_count() == 1


def test_disconnect_still_works_with_unreadable_provider_configuration(harness):
    harness.call(harness.state(), "healthy")
    with harness.factory() as session:
        config = session.scalar(
            select(TenantGoogleWorkspaceConfiguration).where(
                TenantGoogleWorkspaceConfiguration.company_id == harness.company_id,
            )
        )
        config.encrypted_client_secret_ref = "invalid-encrypted-secret"
        session.commit()
    assert harness.disconnect().status == "revoked"
    assert harness.row().ciphertext is None
    assert harness.calls == ["healthy"]
