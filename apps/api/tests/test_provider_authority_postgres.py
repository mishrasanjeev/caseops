"""Real PostgreSQL races for provider claim/I/O/finalize authority fences."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.api.routes import notifications as notification_routes
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProvider,
    CompanyMembership,
    IpDocketRecord,
    Matter,
    MatterDeadline,
    MatterHearing,
    MembershipRole,
    NotificationDeliveryIntent,
    TenantOutlookConfiguration,
    UserCalendarConnection,
)
from caseops_api.services import calendar_sync
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
)
from caseops_api.services.calendar_sync import (
    complete_google_calendar_connection,
    start_google_calendar_connection,
)
from caseops_api.services.calendar_sync import (
    test_outlook_tenant_configuration as run_outlook_readiness_test,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module", autouse=True)
def _ensure_provider_race_migrations():
    url = os.environ.get("CASEOPS_TEST_POSTGRES_URL", "").strip()
    if not url:
        yield
        return
    from alembic.config import Config

    from alembic import command

    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    yield


def test_postgres_drift_source_change_wins_after_committed_provider_read_claim(
    pg_engine,
) -> None:
    from tests.test_postgres_validation import (
        _ip_race_context,
        _seed_ip_coverage_lifecycle_fixture,
    )

    with Session(pg_engine, expire_on_commit=False) as seed:
        env = _seed_ip_coverage_lifecycle_fixture(seed)
        deadline = seed.get(MatterDeadline, env["deadline_id"])
        assert deadline is not None
        expected_date = deadline.due_on
        connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider=CalendarProvider.GOOGLE_CALENDAR,
            status=CalendarConnectionStatus.CONNECTED,
            encrypted_token_ref=calendar_sync._encrypt_token_payload(
                {"access_token": "pg-drift-token"}
            ),
        )
        seed.add(connection)
        seed.flush()
        sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connection.id,
            source_type="matter_deadline",
            source_id=deadline.id,
            provider_event_id="pg-drift-provider-event",
            sync_status=CalendarEventSyncStatus.SYNCED,
        )
        seed.add(sync)
        seed.commit()
        sync_id = sync.id

    provider_entered = Event()
    release_provider = Event()
    worker_sessions: list[Session] = []

    class BlockingDriftProvider:
        configured = True
        unavailable_reason = None

        def fetch_event(self, *, token_payload, provider_event_id):
            assert worker_sessions and worker_sessions[0].in_transaction() is False
            assert token_payload["access_token"] == "pg-drift-token"
            assert provider_event_id == "pg-drift-provider-event"
            provider_entered.set()
            assert release_provider.wait(10)
            return {
                "id": provider_event_id,
                "start_date": expected_date.isoformat(),
                "cancelled": False,
            }

    calendar_sync.set_google_calendar_provider_for_tests(BlockingDriftProvider())

    def run_worker():
        with Session(pg_engine, expire_on_commit=False) as worker:
            worker_sessions.append(worker)
            return calendar_sync.check_ip_calendar_projection_drift(
                worker,
                context=_ip_race_context(
                    worker,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_worker)
            assert provider_entered.wait(10), "drift provider read never began"
            with Session(pg_engine) as writer:
                deadline = writer.get(MatterDeadline, env["deadline_id"])
                assert deadline is not None
                deadline.due_on = deadline.due_on + timedelta(days=1)
                writer.commit()
            release_provider.set()
            assert future.result(timeout=15) == []
        with Session(pg_engine) as verify:
            sync = verify.get(CalendarEventSync, sync_id)
            assert sync is not None
            assert sync.drift_status == "unchecked"
            assert sync.drift_checked_at is None
            assert sync.dead_letter_reason is None
    finally:
        release_provider.set()
        calendar_sync.set_google_calendar_provider_for_tests(None)


def test_postgres_oauth_revoke_wins_during_external_exchange(pg_engine) -> None:
    from tests.test_postgres_validation import (
        _ip_race_context,
        _seed_ip_coverage_lifecycle_fixture,
    )

    with Session(pg_engine) as seed:
        env = _seed_ip_coverage_lifecycle_fixture(seed)

    provider_entered = Event()
    release_provider = Event()
    worker_sessions: list[Session] = []

    class BlockingOAuthProvider:
        configured = True
        unavailable_reason = None

        def authorization_url(self, *, state: str) -> str:
            return f"https://google.example.test/oauth?state={state}"

        def exchange_code(self, *, code: str):
            assert code == "pg-oauth-code"
            assert worker_sessions and worker_sessions[0].in_transaction() is False
            provider_entered.set()
            assert release_provider.wait(10)
            return {
                "token_payload": {
                    "access_token": "pg-google-access",
                    "refresh_token": "pg-google-refresh",
                },
                "provider_account_id": "pg-google-account",
                "display_email": "pg-google@example.test",
                "scopes": list(calendar_sync.GOOGLE_CALENDAR_SCOPES),
            }

    calendar_sync.set_google_calendar_provider_for_tests(BlockingOAuthProvider())

    def run_worker():
        with Session(pg_engine, expire_on_commit=False) as worker:
            worker_sessions.append(worker)
            context = _ip_race_context(
                worker,
                company_id=env["company_id"],
                membership_id=env["owner_id"],
            )
            start = start_google_calendar_connection(worker, context=context)
            assert start.auth_url is not None
            state = parse_qs(urlparse(start.auth_url).query)["state"][0]
            return complete_google_calendar_connection(
                worker,
                context=context,
                code="pg-oauth-code",
                state=state,
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_worker)
            assert provider_entered.wait(10), "OAuth exchange never began"
            with Session(pg_engine) as writer:
                connection = writer.scalar(
                    select(UserCalendarConnection).where(
                        UserCalendarConnection.company_id == env["company_id"],
                        UserCalendarConnection.membership_id == env["owner_id"],
                        UserCalendarConnection.provider
                        == CalendarProvider.GOOGLE_CALENDAR,
                    )
                )
                assert connection is not None
                connection.status = CalendarConnectionStatus.REVOKED
                connection.encrypted_token_ref = None
                writer.commit()
                connection_id = connection.id
            release_provider.set()
            with pytest.raises(HTTPException) as exc_info:
                future.result(timeout=15)
            assert exc_info.value.status_code == 409
        with Session(pg_engine) as verify:
            connection = verify.get(UserCalendarConnection, connection_id)
            assert connection is not None
            assert connection.status == CalendarConnectionStatus.REVOKED
            assert connection.provider_account_id is None
            assert connection.encrypted_token_ref is None
    finally:
        release_provider.set()
        calendar_sync.set_google_calendar_provider_for_tests(None)


def test_postgres_outlook_readiness_demotion_discards_provider_success(
    pg_engine,
) -> None:
    from tests.test_postgres_validation import (
        _ip_race_context,
        _seed_ip_coverage_lifecycle_fixture,
    )

    with Session(pg_engine, expire_on_commit=False) as seed:
        env = _seed_ip_coverage_lifecycle_fixture(seed)
        actor = seed.get(CompanyMembership, env["owner_id"])
        assert actor is not None
        actor.role = MembershipRole.OWNER
        configuration = TenantOutlookConfiguration(
            company_id=env["company_id"],
            provider=CalendarProvider.OUTLOOK,
            client_id="pg-outlook-client",
            encrypted_client_secret_ref=calendar_sync._encrypt_secret(
                "pg-outlook-secret"
            ),
            tenant_id="organizations",
            redirect_uri="https://api.example.test/outlook/callback",
            scopes_json=list(calendar_sync.OUTLOOK_SCOPES),
            oauth_consent_model_approved=True,
            scopes_approved=True,
            durable_runbook_approved=True,
            rollback_approved=True,
            redaction_rules_approved=True,
            enabled=True,
            created_by_membership_id=actor.id,
            updated_by_membership_id=actor.id,
        )
        connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=actor.id,
            provider=CalendarProvider.OUTLOOK,
            status=CalendarConnectionStatus.CONNECTED,
            encrypted_token_ref=calendar_sync._encrypt_token_payload(
                {"access_token": "pg-outlook-access"}
            ),
        )
        seed.add_all([configuration, connection])
        seed.commit()
        configuration_id = configuration.id

    provider_entered = Event()
    release_provider = Event()
    worker_sessions: list[Session] = []

    class BlockingReadinessProvider:
        configured = True
        unavailable_reason = None

        def validate_connection(self, *, token_payload):
            assert worker_sessions and worker_sessions[0].in_transaction() is False
            assert token_payload["access_token"] == "pg-outlook-access"
            provider_entered.set()
            assert release_provider.wait(10)
            return {"provider_account_id": "pg-outlook-account"}

    calendar_sync.set_outlook_provider_for_tests(BlockingReadinessProvider())

    def run_worker():
        with Session(pg_engine, expire_on_commit=False) as worker:
            worker_sessions.append(worker)
            return run_outlook_readiness_test(
                worker,
                context=_ip_race_context(
                    worker,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_worker)
            assert provider_entered.wait(10), "readiness provider probe never began"
            with Session(pg_engine) as writer:
                actor = writer.get(CompanyMembership, env["owner_id"])
                assert actor is not None
                actor.role = MembershipRole.VIEWER
                writer.commit()
            release_provider.set()
            with pytest.raises(HTTPException) as exc_info:
                future.result(timeout=15)
            assert exc_info.value.status_code == 403
        with Session(pg_engine) as verify:
            configuration = verify.get(TenantOutlookConfiguration, configuration_id)
            assert configuration is not None
            assert configuration.last_test_status != "passed"
    finally:
        release_provider.set()
        calendar_sync.set_outlook_provider_for_tests(None)


@pytest.mark.parametrize("ordering", ["parent_first", "recovery_first"])
def test_postgres_notification_recovery_uses_parent_before_intent_without_deadlock(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
    ordering: str,
) -> None:
    from tests.test_postgres_validation import (
        _ip_race_context,
        _seed_ip_coverage_lifecycle_fixture,
        _wait_for_postgres_lock_wait,
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", False)
    with Session(pg_engine, expire_on_commit=False) as seed:
        env = _seed_ip_coverage_lifecycle_fixture(seed)
        actor = seed.get(CompanyMembership, env["owner_id"])
        assert actor is not None
        actor.role = MembershipRole.OWNER
        hearing = MatterHearing(
            company_id=env["company_id"],
            matter_id=None,
            ip_docket_id=env["docket_id"],
            hearing_on=(calendar_sync._current_time() + timedelta(days=2)).date(),
            forum_name="PostgreSQL IP hearing",
            purpose="Notification recovery lock race",
            status="scheduled",
            responsible_membership_id=env["owner_id"],
        )
        seed.add(hearing)
        seed.flush()
        original = NotificationDeliveryIntent(
            company_id=env["company_id"],
            recipient_membership_id=env["owner_id"],
            destination_version=1,
            ip_docket_id=env["docket_id"],
            channel="email",
            event_type="pg_notification_recovery",
            source_type="provider_fixture",
            source_id=f"pg-recovery:{uuid4()}",
            idempotency_key=uuid4().hex,
            status="blocked",
            dead_letter_reason="provider_disabled",
            title="PostgreSQL notification recovery",
            body="Open CaseOps.",
            critical=True,
            schedule_source_type="matter_hearing",
            schedule_source_id=hearing.id,
            recipient_snapshot_json={
                "target_type": "membership",
                "target_ref": env["owner_id"],
                "destination": "pg-recovery@example.test",
                "channel": "email",
                "destination_version": 1,
            },
            dispatch_owner="durable_intent",
        )
        seed.add(original)
        seed.commit()
        original_id = original.id
        hearing_id = hearing.id

    writer_locked = Event()
    writer_attempted = Event()
    recovery_attempted = Event()
    recovery_locked = Event()
    release_writer = Event()
    release_recovery = Event()
    recovery_app = f"pg_notification_recovery_{ordering}"
    writer_app = f"pg_notification_parent_{ordering}"

    real_route_membership_fence = (
        notification_routes.lock_company_memberships_for_assignment
    )
    real_route_enqueue = notification_routes.enqueue_notification_delivery_intent

    if ordering == "parent_first":

        def observe_recovery_membership_fence(session, **kwargs):
            recovery_attempted.set()
            return real_route_membership_fence(session, **kwargs)

        monkeypatch.setattr(
            notification_routes,
            "lock_company_memberships_for_assignment",
            observe_recovery_membership_fence,
        )
    else:

        def hold_recovery_after_parent_and_intent_locks(session, **kwargs):
            recovery_locked.set()
            assert release_recovery.wait(10)
            return real_route_enqueue(session, **kwargs)

        monkeypatch.setattr(
            notification_routes,
            "enqueue_notification_delivery_intent",
            hold_recovery_after_parent_and_intent_locks,
        )

    def run_recovery():
        with Session(pg_engine, expire_on_commit=False) as worker:
            worker.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": recovery_app},
            )
            context = _ip_race_context(
                worker,
                company_id=env["company_id"],
                membership_id=env["owner_id"],
            )
            return asyncio.run(
                notification_routes.recover_notification_intent(
                    original_id,
                    notification_routes.NotificationRecoveryRequest(
                        replacement_membership_id=env["owner_id"],
                        recovery_action="PostgreSQL canonical lock-order recovery",
                    ),
                    context,
                    worker,
                )
            )

    def run_parent_writer() -> None:
        with Session(pg_engine) as writer:
            writer.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": writer_app},
            )
            if ordering == "recovery_first":
                writer_attempted.set()
            lock_company_memberships_for_assignment(
                writer,
                company_id=env["company_id"],
                membership_ids=(env["owner_id"],),
            )
            writer.scalar(
                select(Matter)
                .where(Matter.id == env["matter_id"])
                .with_for_update(of=Matter)
            )
            writer.scalar(
                select(IpDocketRecord)
                .where(IpDocketRecord.id == env["docket_id"])
                .with_for_update(of=IpDocketRecord)
            )
            writer.scalar(
                select(MatterHearing)
                .where(MatterHearing.id == hearing_id)
                .with_for_update(of=MatterHearing)
            )
            writer.scalar(
                select(NotificationDeliveryIntent)
                .where(NotificationDeliveryIntent.id == original_id)
                .with_for_update(of=NotificationDeliveryIntent)
            )
            if ordering == "parent_first":
                writer_locked.set()
                assert release_writer.wait(10)
            writer.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            if ordering == "parent_first":
                parent_future = executor.submit(run_parent_writer)
                if not writer_locked.wait(10):
                    parent_future.result(timeout=1)
                    pytest.fail("parent writer did not acquire the canonical graph")
                recovery_future = executor.submit(run_recovery)
                if not recovery_attempted.wait(10):
                    recovery_future.result(timeout=1)
                    pytest.fail("recovery did not attempt the Membership fence")
                _wait_for_postgres_lock_wait(
                    pg_engine,
                    application_name=recovery_app,
                )
                release_writer.set()
            else:
                recovery_future = executor.submit(run_recovery)
                if not recovery_locked.wait(10):
                    recovery_future.result(timeout=1)
                    pytest.fail("recovery did not acquire its parent and Intent graph")
                parent_future = executor.submit(run_parent_writer)
                if not writer_attempted.wait(10):
                    parent_future.result(timeout=1)
                    pytest.fail("parent writer did not attempt its Membership fence")
                _wait_for_postgres_lock_wait(
                    pg_engine,
                    application_name=writer_app,
                )
                release_recovery.set()
            parent_future.result(timeout=20)
            recovered = recovery_future.result(timeout=20)
            recovered_id = recovered.intent.id
    finally:
        release_writer.set()
        release_recovery.set()

    with Session(pg_engine) as verify:
        original = verify.get(NotificationDeliveryIntent, original_id)
        recovered = verify.get(NotificationDeliveryIntent, recovered_id)
        assert original is not None and recovered is not None
        assert original.superseded_by_intent_id == recovered.id
        assert recovered.ip_docket_id == env["docket_id"]
        assert recovered.matter_id is None
        assert recovered.schedule_source_type == "matter_hearing"
        assert recovered.schedule_source_id == hearing_id
