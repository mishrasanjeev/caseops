from __future__ import annotations

import inspect
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProvider,
    CalendarSyncSourceType,
    Company,
    CompanyMembership,
    EthicalWall,
    HearingReminder,
    HearingReminderDeliveryIntent,
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketRecord,
    IpResponsibilityAssignment,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterHearing,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    User,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
)
from caseops_api.services.calendar_projection_safety import (
    CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
)
from caseops_api.services.calendar_sync import (
    _encrypt_token_payload,
    _source_payload_for,
    process_calendar_deletion_tombstones,
    process_durable_google_calendar_sync,
    process_durable_outlook_sync,
    revoke_connection,
    set_google_calendar_provider_for_tests,
    set_outlook_provider_for_tests,
    sync_deadline_to_google_calendar,
    sync_deadline_to_outlook,
    sync_hearing_to_google_calendar,
    sync_hearing_to_outlook,
)
from caseops_api.services.hearing_reminders import run_reminder_worker
from caseops_api.services.ip_coverage_projection import (
    cutover_ip_coverage_projection,
    terminalize_coverage_only_deadline_projection,
    tombstone_matter_deadline_calendar_projections,
    tombstone_membership_calendar_projections,
)
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.notification_delivery import (
    _recipient_still_permitted,
    apply_notification_provider_event,
    drain_notification_delivery_intents,
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_google_calendar_sync import StubGoogleCalendarProvider
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _docket_for_matter,
    _member,
    _responsibilities,
    _rule_payload,
)
from tests.test_legalworkspace_calendar_sync import (
    StubOutlookProvider,
    _configure_ready_outlook,
)


def _confirmed_deadline_environment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_id = str(bootstrap["membership"]["id"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client,
        owner_token,
        name="Projection Legal Approver",
        email="projection-legal@asterlegal.in",
    )
    reviewer_id, _ = _member(
        client,
        owner_token,
        name="Projection Backup Reviewer",
        email="projection-backup@asterlegal.in",
    )
    replacement_id, _ = _member(
        client,
        owner_token,
        name="Projection Emergency Cover",
        email="projection-cover@asterlegal.in",
    )
    unrelated_id, _ = _member(
        client,
        owner_token,
        name="Projection Unrelated User",
        email="projection-unrelated@asterlegal.in",
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-PROJECTION-CUTOVER")
    docket = _docket_for_matter(
        client,
        owner_headers,
        matter_id=str(matter["id"]),
    )

    calendar_response = client.post(
        "/api/ip/working-calendars",
        headers=owner_headers,
        json=_calendar_payload(),
    )
    assert calendar_response.status_code == 201, calendar_response.text
    calendar = calendar_response.json()
    activated_calendar = client.post(
        f"/api/ip/working-calendars/{calendar['id']}/activate",
        headers=legal_headers,
        json={"reason": "Independent source review for projection tests."},
    )
    assert activated_calendar.status_code == 200, activated_calendar.text

    rule_response = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=_rule_payload(),
    )
    assert rule_response.status_code == 201, rule_response.text
    rule = rule_response.json()
    activated_rule = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/activate",
        headers=legal_headers,
        json={"reviewer_membership_id": reviewer_id},
    )
    assert activated_rule.status_code == 200, activated_rule.text

    proposed = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Respond to examination report",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": True,
        },
    )
    assert proposed.status_code == 201, proposed.text
    proposed_deadline = proposed.json()
    confirmed = client.post(
        f"/api/ip/deadlines/{proposed_deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": proposed_deadline["version"],
            "responsibilities": _responsibilities(owner_id, reviewer_id),
            "reminder_offsets_days": [7, 1, 0],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_deadline = confirmed.json()
    return {
        "company_id": str(bootstrap["company"]["id"]),
        "owner_token": owner_token,
        "owner_id": owner_id,
        "legal_id": legal_id,
        "reviewer_id": reviewer_id,
        "replacement_id": replacement_id,
        "unrelated_id": unrelated_id,
        "matter_id": str(matter["id"]),
        "docket_id": str(docket["id"]),
        "ip_deadline_id": str(confirmed_deadline["id"]),
        "matter_deadline_id": str(confirmed_deadline["matter_deadline_id"]),
    }


def _context(session, *, company_id: str, membership_id: str) -> SessionContext:
    company = session.get(Company, company_id)
    membership = session.get(CompanyMembership, membership_id)
    assert company is not None and membership is not None
    return SessionContext(company=company, membership=membership, user=membership.user)


def _lock_single_projection_chain(
    session,
    *,
    env: dict[str, str],
) -> tuple[IpDocketRecord, IpDeadlineCoverage]:
    lock_company_memberships_for_assignment(
        session,
        company_id=env["company_id"],
        membership_ids=(
            env["legal_id"],
            env["owner_id"],
            env["reviewer_id"],
            env["replacement_id"],
        ),
    )
    session.scalar(
        select(Matter)
        .where(Matter.id == env["matter_id"])
        .with_for_update(of=Matter)
    )
    docket = session.scalar(
        select(IpDocketRecord)
        .where(IpDocketRecord.id == env["docket_id"])
        .with_for_update(of=IpDocketRecord)
    )
    session.scalar(
        select(IpDeadline)
        .where(IpDeadline.id == env["ip_deadline_id"])
        .with_for_update(of=IpDeadline)
    )
    session.scalar(
        select(MatterDeadline)
        .where(MatterDeadline.id == env["matter_deadline_id"])
        .with_for_update(of=MatterDeadline)
    )
    coverage = session.scalar(
        select(IpDeadlineCoverage)
        .where(
            IpDeadlineCoverage.docket_id == env["docket_id"],
            IpDeadlineCoverage.matter_deadline_id == env["matter_deadline_id"],
        )
        .with_for_update(of=IpDeadlineCoverage)
        .execution_options(populate_existing=True)
    )
    assert docket is not None and coverage is not None
    return docket, coverage


def test_atomic_primary_cutover_preserves_history_and_reconciles_every_projection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        connections: dict[str, UserCalendarConnection] = {}
        for key, membership_id, provider in (
            ("old_outlook", env["owner_id"], "outlook"),
            ("old_google", env["owner_id"], "google_calendar"),
            ("backup", env["reviewer_id"], "outlook"),
            ("replacement_outlook", env["replacement_id"], "outlook"),
            ("replacement_google", env["replacement_id"], "google_calendar"),
            ("unrelated", env["unrelated_id"], "outlook"),
        ):
            row = UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=membership_id,
                provider=provider,
                status="connected",
                encrypted_token_ref="not-used-by-cutover",
            )
            session.add(row)
            session.flush()
            connections[key] = row

        syncs = {
            "old_remote": CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connections["old_outlook"].id,
                source_type="matter_deadline",
                source_id=env["matter_deadline_id"],
                provider_event_id="old-owner-event",
                sync_status=CalendarEventSyncStatus.SYNCED,
            ),
            "old_local": CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connections["old_google"].id,
                source_type="matter_deadline",
                source_id=env["matter_deadline_id"],
                sync_status=CalendarEventSyncStatus.PENDING,
            ),
            "backup_deleted": CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connections["backup"].id,
                source_type="matter_deadline",
                source_id=env["matter_deadline_id"],
                provider_event_id="historical-deleted-event",
                sync_status=CalendarEventSyncStatus.DELETED,
            ),
            "replacement_dead": CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connections["replacement_outlook"].id,
                source_type="matter_deadline",
                source_id=env["matter_deadline_id"],
                sync_status=CalendarEventSyncStatus.DEAD_LETTER,
            ),
            "unrelated": CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connections["unrelated"].id,
                source_type="matter_deadline",
                source_id=env["matter_deadline_id"],
                sync_status=CalendarEventSyncStatus.PENDING,
            ),
        }
        session.add_all(syncs.values())
        old_primary_intents = list(
            session.scalars(
                select(NotificationDeliveryIntent)
                .where(
                    NotificationDeliveryIntent.schedule_source_type == "ip_deadline",
                    NotificationDeliveryIntent.schedule_source_id
                    == env["ip_deadline_id"],
                    NotificationDeliveryIntent.recipient_membership_id == env["owner_id"],
                )
                .order_by(NotificationDeliveryIntent.id)
            ).all()
        )
        backup_intent_ids = tuple(
            session.scalars(
                select(NotificationDeliveryIntent.id).where(
                    NotificationDeliveryIntent.schedule_source_type == "ip_deadline",
                    NotificationDeliveryIntent.schedule_source_id
                    == env["ip_deadline_id"],
                    NotificationDeliveryIntent.recipient_membership_id
                    == env["reviewer_id"],
                )
            ).all()
        )
        assert len(old_primary_intents) == 3 and backup_intent_ids
        old_primary_intents[0].status = NotificationDeliveryStatus.DELIVERED
        terminal_intent_id = old_primary_intents[0].id
        queued_old_primary_ids = {row.id for row in old_primary_intents[1:]}
        session.commit()
        connection_ids = {key: row.id for key, row in connections.items()}
        sync_ids = {key: row.id for key, row in syncs.items()}

    changed_at = datetime(2026, 8, 17, 12, tzinfo=UTC)
    with factory() as session:
        lock_company_memberships_for_assignment(
            session,
            company_id=env["company_id"],
            membership_ids=(
                env["legal_id"],
                env["owner_id"],
                env["reviewer_id"],
                env["replacement_id"],
                env["unrelated_id"],
            ),
        )
        matter = session.scalar(
            select(Matter)
            .where(Matter.id == env["matter_id"])
            .with_for_update(of=Matter)
        )
        docket = session.scalar(
            select(IpDocketRecord)
            .where(IpDocketRecord.id == env["docket_id"])
            .with_for_update(of=IpDocketRecord)
        )
        ip_deadline = session.scalar(
            select(IpDeadline)
            .where(IpDeadline.id == env["ip_deadline_id"])
            .with_for_update(of=IpDeadline)
        )
        operational = session.scalar(
            select(MatterDeadline)
            .where(MatterDeadline.id == env["matter_deadline_id"])
            .with_for_update(of=MatterDeadline)
        )
        coverage = session.scalar(
            select(IpDeadlineCoverage)
            .where(IpDeadlineCoverage.matter_deadline_id == env["matter_deadline_id"])
            .with_for_update(of=IpDeadlineCoverage)
        )
        assert all(row is not None for row in (matter, docket, ip_deadline, operational, coverage))
        assert docket is not None and coverage is not None
        context = _context(
            session,
            company_id=env["company_id"],
            membership_id=env["legal_id"],
        )
        coverage.responsible_membership_id = env["replacement_id"]
        coverage.coverage_status = "reassigned"
        coverage.accepted_at = None
        coverage.reassignment_version += 1
        result = cutover_ip_coverage_projection(
            session,
            context=context,
            docket=docket,
            coverage=coverage,
            previous_responsible_membership_id=env["owner_id"],
            previous_backup_membership_id=env["reviewer_id"],
            reason="Approved emergency primary cover.",
            replacement_source="emergency_coverage",
            responsible_accepted_at=None,
            notification_escalation_membership_id=env["unrelated_id"],
            reminder_generation="projection-test-v2",
            changed_at=changed_at,
        )
        session.commit()

        assert set(result.expired_assignment_ids)
        assert set(result.replacement_assignment_ids)
        assert set(result.notifications.cancelled_intent_ids) == queued_old_primary_ids
        assert result.notifications.replacement_intent_ids
        assert connection_ids["replacement_google"] in result.calendar.desired_connection_ids

    with factory() as session:
        operational = session.get(MatterDeadline, env["matter_deadline_id"])
        assert operational is not None
        assert operational.assignee_membership_id == env["replacement_id"]
        assignments = list(
            session.scalars(
                select(IpResponsibilityAssignment)
                .where(IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"])
                .order_by(IpResponsibilityAssignment.created_at, IpResponsibilityAssignment.id)
            ).all()
        )
        old_primary = [
            row
            for row in assignments
            if row.role == "primary" and row.membership_id == env["owner_id"]
        ]
        new_primary = [
            row
            for row in assignments
            if row.role == "primary" and row.membership_id == env["replacement_id"]
        ]
        assert len(old_primary) == len(new_primary) == 1
        assert old_primary[0].effective_until.replace(tzinfo=UTC) == changed_at
        assert new_primary[0].effective_until is None
        assert new_primary[0].accepted_at is None
        assert new_primary[0].replacement_source == "emergency_coverage"
        assert len([row for row in assignments if row.role != "primary"]) == 1

        assert session.get(CalendarEventSync, sync_ids["old_remote"]).sync_status == (
            CalendarEventSyncStatus.DELETE_PENDING
        )
        assert session.get(CalendarEventSync, sync_ids["old_local"]).sync_status == (
            CalendarEventSyncStatus.DELETED
        )
        assert session.get(CalendarEventSync, sync_ids["backup_deleted"]).sync_status == (
            CalendarEventSyncStatus.PENDING
        )
        assert session.get(CalendarEventSync, sync_ids["backup_deleted"]).provider_event_id is None
        assert session.get(CalendarEventSync, sync_ids["replacement_dead"]).sync_status == (
            CalendarEventSyncStatus.PENDING
        )
        assert session.get(CalendarEventSync, sync_ids["unrelated"]).sync_status == (
            CalendarEventSyncStatus.DELETED
        )
        created = session.scalar(
            select(CalendarEventSync).where(
                CalendarEventSync.calendar_connection_id
                == connection_ids["replacement_google"],
                CalendarEventSync.source_id == env["matter_deadline_id"],
            )
        )
        assert created is not None and created.sync_status == CalendarEventSyncStatus.PENDING

        assert session.get(NotificationDeliveryIntent, terminal_intent_id).status == (
            NotificationDeliveryStatus.DELIVERED
        )
        for intent_id in backup_intent_ids:
            assert session.get(NotificationDeliveryIntent, intent_id).status == (
                NotificationDeliveryStatus.QUEUED
            )
        replacements = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.id.in_(
                        result.notifications.replacement_intent_ids
                    )
                )
            ).all()
        )
        assert replacements
        assert {row.recipient_membership_id for row in replacements} == {
            env["replacement_id"]
        }
        assert all(row.ip_docket_id == env["docket_id"] for row in replacements)
        assert all(row.matter_id is None for row in replacements)
        assert {row.escalation_membership_id for row in replacements} == {
            env["unrelated_id"]
        }

        replacement_context = _context(
            session,
            company_id=env["company_id"],
            membership_id=env["replacement_id"],
        )
        payload = _source_payload_for(
            session,
            context=replacement_context,
            source_type="matter_deadline",
            source_id=env["matter_deadline_id"],
        )
        assert payload.ip_docket is not None and payload.matter is None
        assert payload.title == "CaseOps IP - Deadline"
        assert "IP-PROJECTION-CUTOVER" not in " ".join(payload.detail_lines)
        monkeypatch.setenv("CASEOPS_NOTIFICATION_EXTERNAL_DELIVERY_ENABLED", "true")
        monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "projection-dual-acl-key")
        monkeypatch.setenv(
            "CASEOPS_SENDGRID_SENDER_EMAIL",
            "projection-sender@example.test",
        )
        get_settings.cache_clear()
        dual_acl_intent = enqueue_notification_delivery_intent(
            session,
            context=replacement_context,
            recipient_membership=replacement_context.membership,
            channel="email",
            event_type="ip_deadline_reminder",
            source_type="ip_deadline",
            source_id=f"{env['ip_deadline_id']}:dual-acl",
            ip_docket=payload.ip_docket,
            schedule_source_type="ip_deadline",
            schedule_source_id=env["ip_deadline_id"],
            title="Dual ACL dispatch proof",
        )
        assert dual_acl_intent is not None
        wall = EthicalWall(
            company_id=env["company_id"],
            matter_id=env["matter_id"],
            excluded_membership_id=env["replacement_id"],
            reason="Independent Matter ACL blocks calendar disclosure.",
            created_by_membership_id=env["legal_id"],
        )
        session.add(wall)
        session.flush()
        with pytest.raises(HTTPException) as denied:
            _source_payload_for(
                session,
                context=replacement_context,
                source_type="matter_deadline",
                source_id=env["matter_deadline_id"],
            )
        assert denied.value.status_code == 404
        denied_enqueue = enqueue_notification_delivery_intent(
            session,
            context=replacement_context,
            recipient_membership=replacement_context.membership,
            channel="email",
            event_type="ip_deadline_reminder",
            source_type="ip_deadline",
            source_id=f"{env['ip_deadline_id']}:dual-acl-denied",
            ip_docket=payload.ip_docket,
            schedule_source_type="ip_deadline",
            schedule_source_id=env["ip_deadline_id"],
            title="Denied linked Matter enqueue",
        )
        assert denied_enqueue is None
        assert _recipient_still_permitted(session, dual_acl_intent) is False, (
            dual_acl_intent.ip_docket_id,
            dual_acl_intent.schedule_source_type,
            dual_acl_intent.schedule_source_id,
            dual_acl_intent.source_type,
            dual_acl_intent.source_id,
        )
        dispatch = process_notification_delivery_intent(
            session,
            intent_id=dual_acl_intent.id,
            context=replacement_context,
        )
        assert dispatch.blocked is True
        assert dual_acl_intent.dead_letter_reason == "recipient_permission_revoked"
        session.delete(wall)
        session.commit()

    class RevokingProvider(StubGoogleCalendarProvider):
        def upsert_calendar_item(self, **kwargs) -> str:
            provider_event_id = super().upsert_calendar_item(**kwargs)
            item = kwargs["item"]
            callback_session = object_session(item.ip_docket)
            assert callback_session is not None
            connection = callback_session.get(
                UserCalendarConnection,
                connection_ids["replacement_google"],
            )
            assert connection is not None
            connection.status = "revoked"
            connection.encrypted_token_ref = None
            callback_session.commit()
            return provider_event_id

    provider = RevokingProvider()
    set_google_calendar_provider_for_tests(provider)
    try:
        with factory() as session:
            connection = session.get(
                UserCalendarConnection,
                connection_ids["replacement_google"],
            )
            assert connection is not None
            connection.status = "connected"
            connection.encrypted_token_ref = _encrypt_token_payload(
                {"access_token": "google-access-credential"}
            )
            session.commit()
        with factory() as session:
            response = sync_deadline_to_google_calendar(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["replacement_id"],
                ),
                deadline_id=env["matter_deadline_id"],
            )
            assert response.sync.sync_status == CalendarEventSyncStatus.DELETED, (
                response.sync.last_error,
                response.sync.dead_letter_reason,
            )
        assert len(provider.calls) == 1
        assert provider.delete_calls == ["google-event-1"]

        with factory() as session:
            backup_connection = UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=env["reviewer_id"],
                provider=CalendarProvider.GOOGLE_CALENDAR,
                status="connected",
                encrypted_token_ref=_encrypt_token_payload(
                    {"access_token": "google-access-credential"}
                ),
            )
            session.add(backup_connection)
            backup = session.get(CompanyMembership, env["reviewer_id"])
            assert backup is not None
            backup.is_active = False
            session.commit()
        with factory() as session:
            zero_call = sync_deadline_to_google_calendar(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["reviewer_id"],
                ),
                deadline_id=env["matter_deadline_id"],
            )
            assert zero_call.sync.sync_status == CalendarEventSyncStatus.DELETED
        assert len(provider.calls) == 1
    finally:
        set_google_calendar_provider_for_tests(None)

    with factory() as session:
        context = _context(
            session,
            company_id=env["company_id"],
            membership_id=env["replacement_id"],
        )
        matter = session.get(Matter, env["matter_id"])
        docket = session.get(IpDocketRecord, env["docket_id"])
        assert matter is not None and docket is not None
        orphan = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="in_app",
            event_type="ip_deadline_reminder",
            source_type="ip_deadline",
            source_id=f"missing-{uuid4()}:0",
            matter=matter,
            schedule_source_type="ip_deadline",
            schedule_source_id=f"missing-{uuid4()}",
            title="Orphaned legal reminder",
        )
        assert orphan is not None
        orphan_result = process_notification_delivery_intent(
            session,
            intent_id=orphan.id,
            context=context,
        )
        assert orphan_result.blocked is True
        assert orphan.dead_letter_reason == "ip_deadline_target_inactive"

        terminal = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="in_app",
            event_type="ip_deadline_reminder",
            source_type="ip_deadline",
            source_id=f"{env['ip_deadline_id']}:terminal-check",
            ip_docket=docket,
            schedule_source_type="ip_deadline",
            schedule_source_id=env["ip_deadline_id"],
            title="Terminal legal reminder",
        )
        assert terminal is not None
        ip_deadline = session.get(IpDeadline, env["ip_deadline_id"])
        assert ip_deadline is not None
        ip_deadline.state = "completed"
        session.flush()
        terminal_result = process_notification_delivery_intent(
            session,
            intent_id=terminal.id,
            context=context,
        )
        assert terminal_result.blocked is True
        assert terminal.dead_letter_reason == "ip_deadline_target_inactive"

    with factory() as session:
        session.scalar(
            select(Matter)
            .where(Matter.id == env["matter_id"])
            .with_for_update(of=Matter)
        )
        session.scalar(
            select(IpDocketRecord)
            .where(IpDocketRecord.id == env["docket_id"])
            .with_for_update(of=IpDocketRecord)
        )
        legal_deadline = session.scalar(
            select(IpDeadline)
            .where(IpDeadline.id == env["ip_deadline_id"])
            .with_for_update(of=IpDeadline)
        )
        operational = session.scalar(
            select(MatterDeadline)
            .where(MatterDeadline.id == env["matter_deadline_id"])
            .with_for_update(of=MatterDeadline)
        )
        coverage = session.scalar(
            select(IpDeadlineCoverage)
            .where(IpDeadlineCoverage.matter_deadline_id == env["matter_deadline_id"])
            .with_for_update(of=IpDeadlineCoverage)
        )
        assert legal_deadline is not None and operational is not None and coverage is not None
        legal_deadline.state = "completed"
        operational.status = "completed"
        coverage.coverage_status = "completed"
        terminal_calendar = tombstone_matter_deadline_calendar_projections(
            session,
            company_id=env["company_id"],
            matter_deadline_id=env["matter_deadline_id"],
            reason="ip_deadline_completed",
        )
        assert sync_ids["old_remote"] in terminal_calendar.delete_pending_sync_ids
        source_rows = list(
            session.scalars(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_id == env["matter_deadline_id"]
                )
            ).all()
        )
        assert all(
            row.sync_status
            in {
                CalendarEventSyncStatus.DELETE_PENDING,
                CalendarEventSyncStatus.DELETED,
            }
            for row in source_rows
        )
        session.rollback()

    with factory() as session:
        lock_company_memberships_for_assignment(
            session,
            company_id=env["company_id"],
            membership_ids=(env["replacement_id"],),
        )
        stale = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connection_ids["replacement_outlook"],
            source_type="matter_task",
            source_id=str(uuid4()),
            provider_event_id="stale-member-event",
            sync_status=CalendarEventSyncStatus.SYNCED,
        )
        session.add(stale)
        session.flush()
        member_calendar = tombstone_membership_calendar_projections(
            session,
            company_id=env["company_id"],
            membership_id=env["replacement_id"],
            reason="membership_deactivated",
        )
        assert stale.id in member_calendar.delete_pending_sync_ids
        assert stale.sync_status == CalendarEventSyncStatus.DELETE_PENDING


def test_active_coverage_only_deadline_is_ip_owned_for_google_and_outlook(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    google_connection_ref: dict[str, str] = {}

    class TransactionAwareGoogle(StubGoogleCalendarProvider):
        def upsert_calendar_item(self, **kwargs) -> str:
            callback_session = object_session(kwargs["item"].ip_docket)
            assert callback_session is not None
            assert callback_session.in_transaction() is False
            provider_event_id = super().upsert_calendar_item(**kwargs)
            revoke_connection(
                callback_session,
                context=_context(
                    callback_session,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
                connection_id=google_connection_ref["id"],
            )
            return provider_event_id

        def delete_event(self, **kwargs) -> None:
            self.delete_calls.append(str(kwargs["provider_event_id"]))
            raise RuntimeError("provider compensation unavailable")

    class TransactionAwareOutlook(StubOutlookProvider):
        def upsert_calendar_item(self, **kwargs) -> str:
            callback_session = object_session(kwargs["item"].ip_docket)
            assert callback_session is not None
            assert callback_session.in_transaction() is False
            return super().upsert_calendar_item(**kwargs)

    google = TransactionAwareGoogle()
    outlook = TransactionAwareOutlook()
    set_google_calendar_provider_for_tests(google)
    set_outlook_provider_for_tests(outlook)
    try:
        with factory() as session:
            deadline = MatterDeadline(
                company_id=env["company_id"],
                matter_id=env["matter_id"],
                source="ip_coverage",
                kind="filing",
                title="Privileged coverage-only filing detail",
                due_on=date(2026, 9, 18),
                status="open",
                assignee_membership_id=env["owner_id"],
                created_by_membership_id=env["legal_id"],
            )
            session.add(deadline)
            session.flush()
            coverage = IpDeadlineCoverage(
                company_id=env["company_id"],
                docket_id=env["docket_id"],
                matter_deadline_id=deadline.id,
                responsible_membership_id=env["owner_id"],
                backup_membership_id=env["reviewer_id"],
                coverage_status="accepted",
                calendar_projection_status="pending",
                accepted_at=datetime(2026, 8, 17, 16, tzinfo=UTC),
            )
            google_connection = UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=env["owner_id"],
                provider=CalendarProvider.GOOGLE_CALENDAR,
                status="connected",
                encrypted_token_ref=_encrypt_token_payload(
                    {"access_token": "google-access-credential"}
                ),
            )
            outlook_connection = UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=env["owner_id"],
                provider=CalendarProvider.OUTLOOK,
                status="connected",
                encrypted_token_ref=_encrypt_token_payload(
                    {"access_token": "fixture-access-credential"}
                ),
            )
            session.add_all([coverage, google_connection, outlook_connection])
            session.commit()
            deadline_id = deadline.id
            google_connection_ref["id"] = google_connection.id

        with factory() as session:
            owner_context = _context(
                session,
                company_id=env["company_id"],
                membership_id=env["owner_id"],
            )
            google_result = sync_deadline_to_google_calendar(
                session,
                context=owner_context,
                deadline_id=deadline_id,
            )
            outlook_result = sync_deadline_to_outlook(
                session,
                context=owner_context,
                deadline_id=deadline_id,
            )
            assert google_result.sync.sync_status == (
                CalendarEventSyncStatus.DELETE_PENDING
            )
            assert outlook_result.sync.sync_status == CalendarEventSyncStatus.SYNCED

        for call in (google.calls[0], outlook.calls[0]):
            assert call["matter_id"] is None
            assert call["ip_docket_id"] == env["docket_id"]
            assert call["title"] == "CaseOps IP - Deadline"
            assert "Privileged coverage-only filing detail" not in " ".join(
                call["detail_lines"]
            )

        with factory() as session:
            assert session.scalar(
                select(IpDeadline.id).where(
                    IpDeadline.matter_deadline_id == deadline_id
                )
            ) is None
            revoked_google = session.get(
                UserCalendarConnection,
                google_connection_ref["id"],
            )
            assert revoked_google is not None
            assert revoked_google.status == "revoked"
            assert revoked_google.encrypted_token_ref is not None
            google_sync = session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.calendar_connection_id
                    == google_connection_ref["id"],
                    CalendarEventSync.source_id == deadline_id,
                )
            )
            assert google_sync is not None
            assert google_sync.provider_event_id == "google-event-1"
            assert google_sync.sync_status == CalendarEventSyncStatus.DELETE_PENDING
            assert google.delete_calls == ["google-event-1"]
            with pytest.raises(HTTPException) as owner_denied:
                _source_payload_for(
                    session,
                    context=_context(
                        session,
                        company_id=env["company_id"],
                        membership_id=env["unrelated_id"],
                    ),
                    source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                    source_id=deadline_id,
                )
            assert owner_denied.value.status_code == 404

            session.add(
                EthicalWall(
                    company_id=env["company_id"],
                    matter_id=env["matter_id"],
                    excluded_membership_id=env["reviewer_id"],
                    reason="Independent Matter ACL blocks provider disclosure.",
                    created_by_membership_id=env["legal_id"],
                )
            )
            session.flush()
            with pytest.raises(HTTPException) as dual_acl_denied:
                _source_payload_for(
                    session,
                    context=_context(
                        session,
                        company_id=env["company_id"],
                        membership_id=env["reviewer_id"],
                    ),
                    source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                    source_id=deadline_id,
                )
            assert dual_acl_denied.value.status_code == 404
    finally:
        set_google_calendar_provider_for_tests(None)
        set_outlook_provider_for_tests(None)


@pytest.mark.parametrize(
    "provider_name",
    [CalendarProvider.GOOGLE_CALENDAR, CalendarProvider.OUTLOOK],
)
def test_ordinary_matter_access_revocation_after_claim_compensates_create(
    client: TestClient,
    provider_name: CalendarProvider,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_id = str(bootstrap["membership"]["id"])
    created_member = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": f"{provider_name} calendar grantee",
            "email": f"{provider_name.replace('_', '-')}@example.com",
            "password": "CalendarGrantee123!",
            "role": "member",
        },
    )
    assert created_member.status_code == 200, created_member.text
    member_id = str(created_member.json()["membership_id"])
    matter = _mk_matter(
        client,
        owner_token,
        f"ACL-{provider_name.replace('_', '-')}",
    )
    factory = get_session_factory()
    with factory() as session:
        matter_row = session.get(Matter, str(matter["id"]))
        assert matter_row is not None
        matter_row.restricted_access = True
        hearing = MatterHearing(
            company_id=company_id,
            matter_id=matter_row.id,
            hearing_on=date.today() + timedelta(days=12),
            forum_name="Delhi High Court",
            purpose="Restricted calendar hearing",
            responsible_membership_id=member_id,
        )
        grant = MatterAccessGrant(
            company_id=company_id,
            matter_id=matter_row.id,
            membership_id=member_id,
            granted_by_membership_id=owner_id,
            reason="Temporary calendar projection access.",
        )
        token = (
            "google-access-credential"
            if provider_name == CalendarProvider.GOOGLE_CALENDAR
            else "fixture-access-credential"
        )
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=member_id,
            provider=provider_name,
            status="connected",
            encrypted_token_ref=_encrypt_token_payload({"access_token": token}),
        )
        session.add_all([matter_row, hearing, grant, connection])
        session.commit()
        hearing_id = hearing.id
        grant_id = grant.id

    def revoke_grant() -> None:
        with factory() as revoker:
            lock_company_memberships_for_assignment(
                revoker,
                company_id=company_id,
                membership_ids=(owner_id, member_id),
            )
            revoker.scalar(
                select(Matter)
                .where(Matter.id == str(matter["id"]))
                .with_for_update(of=Matter)
            )
            locked_grant = revoker.scalar(
                select(MatterAccessGrant)
                .where(MatterAccessGrant.id == grant_id)
                .with_for_update(of=MatterAccessGrant)
            )
            assert locked_grant is not None
            locked_grant.revoked_at = datetime.now(UTC)
            locked_grant.revoked_by_membership_id = owner_id
            revoker.commit()

    if provider_name == CalendarProvider.GOOGLE_CALENDAR:
        class RevokingProvider(StubGoogleCalendarProvider):
            def upsert_hearing_event(self, **kwargs) -> str:
                callback_session = object_session(kwargs["matter"])
                assert callback_session is not None
                assert callback_session.in_transaction() is False
                result = super().upsert_hearing_event(**kwargs)
                revoke_grant()
                return result

        provider = RevokingProvider()
        set_google_calendar_provider_for_tests(provider)
        sync = sync_hearing_to_google_calendar
    else:
        class RevokingProvider(StubOutlookProvider):
            def __init__(self) -> None:
                super().__init__()
                self.delete_calls: list[str] = []

            def upsert_hearing_event(self, **kwargs) -> str:
                callback_session = object_session(kwargs["matter"])
                assert callback_session is not None
                assert callback_session.in_transaction() is False
                result = super().upsert_hearing_event(**kwargs)
                revoke_grant()
                return result

            def delete_event(self, **kwargs) -> None:
                self.delete_calls.append(str(kwargs["provider_event_id"]))

        provider = RevokingProvider()
        set_outlook_provider_for_tests(provider)
        sync = sync_hearing_to_outlook

    try:
        with factory() as session:
            response = sync(
                session,
                context=_context(
                    session,
                    company_id=company_id,
                    membership_id=member_id,
                ),
                hearing_id=hearing_id,
            )
            assert response.sync.sync_status == CalendarEventSyncStatus.DELETED
        assert len(provider.calls) == 1
        assert len(provider.delete_calls) == 1
    finally:
        if provider_name == CalendarProvider.GOOGLE_CALENDAR:
            set_google_calendar_provider_for_tests(None)
        else:
            set_outlook_provider_for_tests(None)


def test_coverage_only_terminal_projection_converges_every_sibling_and_exact_sync(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    changed_at = datetime(2026, 8, 17, 15, tzinfo=UTC)
    with factory() as session:
        sibling_docket = IpDocketRecord(
            company_id=env["company_id"],
            matter_id=env["matter_id"],
            record_type="trademark_application",
            title="Sibling coverage-only docket",
            primary_identifier=f"COVERAGE-ONLY-{uuid4()}",
            status="ready",
            is_active=True,
            restricted=False,
            created_by_membership_id=env["legal_id"],
        )
        deadline = MatterDeadline(
            company_id=env["company_id"],
            matter_id=env["matter_id"],
            source="custom",
            kind="renewal",
            title="Coverage-only terminal deadline",
            due_on=date(2026, 9, 15),
            status="open",
            assignee_membership_id=env["owner_id"],
            created_by_membership_id=env["legal_id"],
        )
        session.add_all([sibling_docket, deadline])
        session.flush()
        coverages = [
            IpDeadlineCoverage(
                company_id=env["company_id"],
                docket_id=env["docket_id"],
                matter_deadline_id=deadline.id,
                responsible_membership_id=env["owner_id"],
                backup_membership_id=env["reviewer_id"],
                coverage_status="accepted",
                calendar_projection_status="projected",
            ),
            IpDeadlineCoverage(
                company_id=env["company_id"],
                docket_id=sibling_docket.id,
                matter_deadline_id=deadline.id,
                responsible_membership_id=env["reviewer_id"],
                coverage_status="transfer_pending",
                calendar_projection_status="pending",
            ),
        ]
        connections = [
            UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=env["owner_id"],
                provider=CalendarProvider.OUTLOOK,
                status="connected",
                encrypted_token_ref="coverage-only-owner",
            ),
            UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=env["reviewer_id"],
                provider=CalendarProvider.GOOGLE_CALENDAR,
                status="connected",
                encrypted_token_ref="coverage-only-reviewer",
            ),
        ]
        session.add_all([*coverages, *connections])
        session.flush()
        exact_remote = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connections[0].id,
            source_type=CalendarSyncSourceType.MATTER_DEADLINE,
            source_id=deadline.id,
            provider_event_id="coverage-only-remote",
            sync_status=CalendarEventSyncStatus.SYNCED,
        )
        exact_local = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connections[1].id,
            source_type=CalendarSyncSourceType.MATTER_DEADLINE,
            source_id=deadline.id,
            sync_status=CalendarEventSyncStatus.PENDING,
        )
        unrelated = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connections[0].id,
            source_type=CalendarSyncSourceType.MATTER_DEADLINE,
            source_id=str(uuid4()),
            provider_event_id="unrelated-remote",
            sync_status=CalendarEventSyncStatus.SYNCED,
        )
        session.add_all([exact_remote, exact_local, unrelated])
        session.commit()
        deadline_id = deadline.id
        sibling_docket_id = sibling_docket.id
        coverage_ids = {row.id for row in coverages}
        exact_remote_id = exact_remote.id
        exact_local_id = exact_local.id
        unrelated_id = unrelated.id

    with factory() as session:
        lock_company_memberships_for_assignment(
            session,
            company_id=env["company_id"],
            membership_ids=(env["legal_id"], env["owner_id"], env["reviewer_id"]),
        )
        session.scalar(
            select(Matter)
            .where(Matter.id == env["matter_id"])
            .with_for_update(of=Matter)
        )
        list(
            session.scalars(
                select(IpDocketRecord)
                .where(IpDocketRecord.id.in_((env["docket_id"], sibling_docket_id)))
                .order_by(IpDocketRecord.id)
                .with_for_update(of=IpDocketRecord)
            ).all()
        )
        session.scalar(
            select(MatterDeadline)
            .where(MatterDeadline.id == deadline_id)
            .with_for_update(of=MatterDeadline)
        )
        list(
            session.scalars(
                select(IpDeadlineCoverage)
                .where(IpDeadlineCoverage.id.in_(sorted(coverage_ids)))
                .order_by(IpDeadlineCoverage.id)
                .with_for_update(of=IpDeadlineCoverage)
            ).all()
        )
        result = terminalize_coverage_only_deadline_projection(
            session,
            company_id=env["company_id"],
            matter_deadline_id=deadline_id,
            reason="coverage_only_deadline_completed",
            changed_at=changed_at,
        )
        session.commit()

        assert set(result.coverage_ids) == coverage_ids
        assert result.calendar.delete_pending_sync_ids == (exact_remote_id,)
        assert result.calendar.deleted_sync_ids == (exact_local_id,)
        completed_coverages = list(
            session.scalars(
                select(IpDeadlineCoverage).where(
                    IpDeadlineCoverage.id.in_(sorted(coverage_ids))
                )
            ).all()
        )
        assert all(row.coverage_status == "completed" for row in completed_coverages)
        assert all(
            row.calendar_projection_status == "completed"
            for row in completed_coverages
        )
        assert session.get(CalendarEventSync, exact_remote_id).sync_status == (
            CalendarEventSyncStatus.DELETE_PENDING
        )
        assert session.get(CalendarEventSync, exact_local_id).sync_status == (
            CalendarEventSyncStatus.DELETED
        )
        assert session.get(CalendarEventSync, unrelated_id).sync_status == (
            CalendarEventSyncStatus.SYNCED
        )


def test_acceptance_versions_live_primary_and_rejects_any_active_secondary_collision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    accepted_at = datetime(2026, 8, 17, 14, tzinfo=UTC)
    with factory() as session:
        primary = session.scalar(
            select(IpResponsibilityAssignment).where(
                IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"],
                IpResponsibilityAssignment.role == "primary",
                IpResponsibilityAssignment.effective_until.is_(None),
            )
        )
        assert primary is not None
        primary.accepted_at = None
        prior_version = primary.version
        session.commit()

    with factory() as session:
        docket, coverage = _lock_single_projection_chain(session, env=env)
        coverage.coverage_status = "accepted"
        coverage.accepted_at = accepted_at
        coverage.reassignment_version += 1
        result = cutover_ip_coverage_projection(
            session,
            context=_context(
                session,
                company_id=env["company_id"],
                membership_id=env["legal_id"],
            ),
            docket=docket,
            coverage=coverage,
            previous_responsible_membership_id=env["owner_id"],
            previous_backup_membership_id=env["reviewer_id"],
            reason="The immediate owner accepted responsibility.",
            replacement_source="immediate_acceptance",
            responsible_accepted_at=accepted_at,
        )
        assert result.expired_assignment_ids == ()
        assert result.replacement_assignment_ids == ()
        session.commit()

    with factory() as session:
        primary = session.scalar(
            select(IpResponsibilityAssignment).where(
                IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"],
                IpResponsibilityAssignment.role == "primary",
                IpResponsibilityAssignment.effective_until.is_(None),
            )
        )
        assert primary is not None
        assert primary.accepted_at is not None
        assert primary.accepted_at.replace(tzinfo=UTC) == accepted_at
        assert primary.version == prior_version + 1
        assert primary.delegation_reason == "The immediate owner accepted responsibility."
        assert primary.replacement_source == "immediate_acceptance"
        replacement = session.get(CompanyMembership, env["replacement_id"])
        actor = session.get(CompanyMembership, env["legal_id"])
        assert replacement is not None and actor is not None
        session.add(
            IpResponsibilityAssignment(
                company_id=env["company_id"],
                docket_id=env["docket_id"],
                deadline_id=env["ip_deadline_id"],
                membership_id=replacement.id,
                membership_label_snapshot=(
                    replacement.user.full_name or replacement.user.email
                ),
                role="supervisor",
                effective_from=accepted_at,
                accepted_at=None,
                delegation_reason="Pending supervisory review.",
                replacement_source="supervisor_assignment",
                escalation_policy_json={},
                version=1,
                created_by_membership_id=actor.id,
                creator_label_snapshot=actor.user.full_name or actor.user.email,
            )
        )
        session.commit()
    with factory() as session:
        before = _projection_snapshot(session, env=env)

    with factory() as session:
        docket, coverage = _lock_single_projection_chain(session, env=env)
        coverage.responsible_membership_id = env["replacement_id"]
        coverage.coverage_status = "reassigned"
        coverage.accepted_at = None
        coverage.reassignment_version += 1
        with pytest.raises(HTTPException) as blocked:
            cutover_ip_coverage_projection(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["legal_id"],
                ),
                docket=docket,
                coverage=coverage,
                previous_responsible_membership_id=env["owner_id"],
                previous_backup_membership_id=env["reviewer_id"],
                reason="Reject an A/A responsibility collision.",
                replacement_source="collision_guard_test",
                responsible_accepted_at=None,
            )
        assert isinstance(blocked.value.detail, dict)
        assert (
            blocked.value.detail["code"]
            == "ip_coverage_projection_primary_secondary_collision"
        )
        assert blocked.value.detail["conflicting_roles"] == ["supervisor"]
        session.rollback()

    with factory() as session:
        assert _projection_snapshot(session, env=env) == before


def _projection_snapshot(session, *, env: dict[str, str]) -> dict[str, object]:
    deadline = session.get(MatterDeadline, env["matter_deadline_id"])
    assert deadline is not None
    return {
        "assignee": deadline.assignee_membership_id,
        "coverages": tuple(
            (
                row.id,
                row.docket_id,
                row.responsible_membership_id,
                row.backup_membership_id,
                row.coverage_status,
                row.reassignment_version,
            )
            for row in session.scalars(
                select(IpDeadlineCoverage)
                .where(
                    IpDeadlineCoverage.matter_deadline_id
                    == env["matter_deadline_id"]
                )
                .order_by(IpDeadlineCoverage.id)
            ).all()
        ),
        "assignments": tuple(
            (
                row.id,
                row.membership_id,
                row.role,
                row.effective_until,
                row.replacement_source,
                row.version,
            )
            for row in session.scalars(
                select(IpResponsibilityAssignment)
                .where(
                    IpResponsibilityAssignment.deadline_id
                    == env["ip_deadline_id"]
                )
                .order_by(IpResponsibilityAssignment.id)
            ).all()
        ),
        "syncs": tuple(
            (row.id, row.calendar_connection_id, row.sync_status)
            for row in session.scalars(
                select(CalendarEventSync)
                .where(CalendarEventSync.source_id == env["matter_deadline_id"])
                .order_by(CalendarEventSync.id)
            ).all()
        ),
        "intents": tuple(
            (
                row.id,
                row.recipient_membership_id,
                row.status,
                row.superseded_by_intent_id,
            )
            for row in session.scalars(
                select(NotificationDeliveryIntent)
                .where(
                    NotificationDeliveryIntent.schedule_source_type
                    == "ip_deadline",
                    NotificationDeliveryIntent.schedule_source_id
                    == env["ip_deadline_id"],
                )
                .order_by(NotificationDeliveryIntent.id)
            ).all()
        ),
    }


def test_shared_operational_deadline_fails_closed_without_projection_mutation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    sibling = _docket_for_matter(
        client,
        auth_headers(env["owner_token"]),
        matter_id=env["matter_id"],
    )
    factory = get_session_factory()
    with factory() as session:
        session.add(
            IpDeadlineCoverage(
                company_id=env["company_id"],
                docket_id=str(sibling["id"]),
                matter_deadline_id=env["matter_deadline_id"],
                responsible_membership_id=env["unrelated_id"],
                backup_membership_id=env["reviewer_id"],
                coverage_status="accepted",
                calendar_projection_status="projected",
                accepted_at=datetime(2026, 8, 17, 10, tzinfo=UTC),
            )
        )
        session.commit()
    with factory() as session:
        before = _projection_snapshot(session, env=env)
        with pytest.raises(HTTPException) as calendar_blocked:
            _source_payload_for(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
                source_type="matter_deadline",
                source_id=env["matter_deadline_id"],
            )
        assert isinstance(calendar_blocked.value.detail, dict)
        assert (
            calendar_blocked.value.detail["code"]
            == "ip_coverage_projection_shared_deadline_unsupported"
        )

    with factory() as session:
        lock_company_memberships_for_assignment(
            session,
            company_id=env["company_id"],
            membership_ids=(
                env["legal_id"],
                env["owner_id"],
                env["reviewer_id"],
                env["replacement_id"],
            ),
        )
        session.scalar(
            select(Matter)
            .where(Matter.id == env["matter_id"])
            .with_for_update(of=Matter)
        )
        list(
            session.scalars(
                select(IpDocketRecord)
                .where(
                    IpDocketRecord.id.in_(
                        (env["docket_id"], str(sibling["id"]))
                    )
                )
                .order_by(IpDocketRecord.id)
                .with_for_update(of=IpDocketRecord)
            ).all()
        )
        session.scalar(
            select(IpDeadline)
            .where(IpDeadline.id == env["ip_deadline_id"])
            .with_for_update(of=IpDeadline)
        )
        session.scalar(
            select(MatterDeadline)
            .where(MatterDeadline.id == env["matter_deadline_id"])
            .with_for_update(of=MatterDeadline)
        )
        coverages = list(
            session.scalars(
                select(IpDeadlineCoverage)
                .where(
                    IpDeadlineCoverage.matter_deadline_id
                    == env["matter_deadline_id"]
                )
                .order_by(IpDeadlineCoverage.id)
                .with_for_update(of=IpDeadlineCoverage)
            ).all()
        )
        original = next(row for row in coverages if row.docket_id == env["docket_id"])
        docket = session.get(IpDocketRecord, env["docket_id"])
        assert docket is not None
        original.responsible_membership_id = env["replacement_id"]
        original.coverage_status = "reassigned"
        original.reassignment_version += 1
        with pytest.raises(HTTPException) as blocked:
            cutover_ip_coverage_projection(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["legal_id"],
                ),
                docket=docket,
                coverage=original,
                previous_responsible_membership_id=env["owner_id"],
                previous_backup_membership_id=env["reviewer_id"],
                reason="Refuse an ambiguous sibling projection.",
                replacement_source="shared_deadline_guard_test",
                responsible_accepted_at=None,
            )
        assert blocked.value.status_code == 409
        assert isinstance(blocked.value.detail, dict)
        assert (
            blocked.value.detail["code"]
            == "ip_coverage_projection_shared_deadline_unsupported"
        )
        session.rollback()

    with factory() as session:
        assert _projection_snapshot(session, env=env) == before


def test_external_delivery_uses_fresh_locked_user_destination(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_NOTIFICATION_EXTERNAL_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "test-sendgrid-key")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "sender@example.test")
    get_settings.cache_clear()
    bootstrap = bootstrap_company(client)
    matter_payload = _mk_matter(client, str(bootstrap["access_token"]), "FRESH-DEST")
    factory = get_session_factory()
    old_email = str(bootstrap["user"]["email"])
    new_email = f"fresh-{uuid4()}@example.test"
    with factory() as session:
        context = _context(
            session,
            company_id=str(bootstrap["company"]["id"]),
            membership_id=str(bootstrap["membership"]["id"]),
        )
        matter = session.get(Matter, matter_payload["id"])
        assert matter is not None
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="email",
            event_type="fresh_destination",
            source_type="matter",
            source_id=str(matter.id),
            matter=matter,
            title="Fresh destination proof",
        )
        assert intent is not None
        intent_id = intent.id
        session.commit()
    with factory() as session:
        user = session.get(User, str(bootstrap["user"]["id"]))
        assert user is not None
        user.email = new_email
        session.commit()

    sent_to: list[str] = []
    worker_session_ref: list[Session] = []

    def fake_sendgrid(**kwargs):
        assert worker_session_ref
        worker_session = worker_session_ref[0]
        assert worker_session.in_transaction() is False
        sent_to.append(str(kwargs["to_email"]))
        # The committed claim wins before deactivation. The irreversible send
        # is allowed and finalized, while a deactivation that committed first
        # would have blocked the claim's locked authorization check.
        with factory() as deactivation_session:
            user = deactivation_session.get(User, str(bootstrap["user"]["id"]))
            assert user is not None
            user.is_active = False
            deactivation_session.commit()
        return True, "fresh-provider-event", None

    from caseops_api.services import communications

    monkeypatch.setattr(communications, "_send_via_sendgrid", fake_sendgrid)
    with factory() as session:
        worker_session_ref.append(session)
        result = process_notification_delivery_intent(
            session,
            intent_id=intent_id,
            company_id=str(bootstrap["company"]["id"]),
        )
        session.commit()
        assert result.status == NotificationDeliveryStatus.SENT
    assert sent_to == [new_email]
    assert old_email not in sent_to

    with factory() as session:
        user = session.get(User, str(bootstrap["user"]["id"]))
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert user is not None and user.is_active is False
        assert intent is not None
        intent.status = NotificationDeliveryStatus.BLOCKED
        intent.dead_letter_reason = "recipient_permission_revoked"
        session.commit()

    with factory() as session:
        assert apply_notification_provider_event(
            session,
            event={
                "notification_intent_id": intent_id,
                "sg_message_id": "fresh-provider-event",
                "sg_event_id": f"stale-delivered-{uuid4()}",
                "event": "delivered",
                "timestamp": int(datetime.now(UTC).timestamp()),
                "email": new_email,
            },
        )
        session.commit()
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert intent is not None
        assert intent.status == NotificationDeliveryStatus.BLOCKED
        assert intent.dead_letter_reason == "recipient_permission_revoked"


def test_expired_notification_claim_is_dead_lettered_without_duplicate_send(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_NOTIFICATION_EXTERNAL_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "test-sendgrid-key")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "sender@example.test")
    get_settings.cache_clear()
    bootstrap = bootstrap_company(client)
    matter_payload = _mk_matter(
        client,
        str(bootstrap["access_token"]),
        "EXPIRED-NOTIFICATION-CLAIM",
    )
    factory = get_session_factory()
    with factory() as session:
        context = _context(
            session,
            company_id=str(bootstrap["company"]["id"]),
            membership_id=str(bootstrap["membership"]["id"]),
        )
        matter = session.get(Matter, str(matter_payload["id"]))
        assert matter is not None
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="email",
            event_type="expired_claim",
            source_type="matter",
            source_id=matter.id,
            matter=matter,
            title="Expired dispatch claim",
        )
        assert intent is not None
        intent.status = NotificationDeliveryStatus.SENT
        intent.provider_event_id = "dispatch_claim:crashed-worker"
        intent.dispatch_owner = "provider_claim"
        intent.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()
        intent_id = intent.id

    def fail_if_sent(**_kwargs):  # pragma: no cover - assertion boundary
        raise AssertionError("an unknown SendGrid outcome must not be retried")

    from caseops_api.services import communications

    monkeypatch.setattr(communications, "_send_via_sendgrid", fail_if_sent)
    with factory() as session:
        result = process_notification_delivery_intent(
            session,
            intent_id=intent_id,
            context=_context(
                session,
                company_id=str(bootstrap["company"]["id"]),
                membership_id=str(bootstrap["membership"]["id"]),
            ),
        )
        assert result.status == NotificationDeliveryStatus.DEAD_LETTER
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert intent is not None
        assert (
            intent.dead_letter_reason
            == "dispatch_claim_expired_provider_outcome_unknown"
        )
        assert intent.dispatch_owner == "durable_intent"
        assert intent.next_attempt_at is None


def test_revoked_expired_upsert_claim_retains_credential_for_manual_cleanup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider=CalendarProvider.GOOGLE_CALENDAR,
            status="connected",
            encrypted_token_ref=_encrypt_token_payload(
                {"access_token": "revocation-repair-credential"}
            ),
        )
        session.add(connection)
        session.flush()
        sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connection.id,
            source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
            source_id=env["matter_deadline_id"],
            sync_status=CalendarEventSyncStatus.PENDING,
            dead_letter_reason="provider_upsert_claim:crashed-worker",
            next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(sync)
        session.commit()
        connection_id = connection.id
        sync_id = sync.id

    provider = StubGoogleCalendarProvider()
    set_google_calendar_provider_for_tests(provider)
    try:
        with factory() as session:
            context = _context(
                session,
                company_id=env["company_id"],
                membership_id=env["owner_id"],
            )
            revoked = revoke_connection(
                session,
                context=context,
                connection_id=connection_id,
            )
            assert revoked.status == "revoked"
            classified = session.get(CalendarEventSync, sync_id)
            assert classified is not None
            assert classified.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert classified.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            assert classified.next_attempt_at is None
            result = process_calendar_deletion_tombstones(
                session,
                context=context,
                calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
                limit=1,
            )
            assert result.examined == 0
            assert result.dead_lettered == 0
            assert result.provider_calls == 0
        assert provider.calls == []
        assert getattr(provider, "delete_calls", []) == []

        with factory() as session:
            connection = session.get(UserCalendarConnection, connection_id)
            sync = session.get(CalendarEventSync, sync_id)
            assert connection is not None and sync is not None
            assert sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert sync.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            assert connection.encrypted_token_ref is not None
    finally:
        set_google_calendar_provider_for_tests(None)


def test_projection_tombstone_preserves_live_create_claim_until_expiry_classifies_unknown(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider=CalendarProvider.GOOGLE_CALENDAR,
            status="connected",
            encrypted_token_ref=_encrypt_token_payload(
                {"access_token": "google-access-credential"}
            ),
        )
        session.add(connection)
        session.flush()
        sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connection.id,
            source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
            source_id=env["matter_deadline_id"],
            sync_status=CalendarEventSyncStatus.PENDING,
            dead_letter_reason="provider_upsert_claim:in-flight-cutover-create",
            next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        session.add(sync)
        session.commit()
        sync_id = sync.id

    with factory() as session:
        _lock_single_projection_chain(session, env=env)
        result = tombstone_matter_deadline_calendar_projections(
            session,
            company_id=env["company_id"],
            matter_deadline_id=env["matter_deadline_id"],
            reason="concurrent_assignment_terminalized",
        )
        assert result.tombstoned_sync_ids == ()
        preserved = session.get(CalendarEventSync, sync_id)
        assert preserved is not None
        assert preserved.sync_status == CalendarEventSyncStatus.PENDING
        assert (
            preserved.dead_letter_reason
            == "provider_upsert_claim:in-flight-cutover-create"
        )
        session.commit()

    provider = StubGoogleCalendarProvider()
    set_google_calendar_provider_for_tests(provider)
    try:
        with factory() as session:
            preserved = session.get(CalendarEventSync, sync_id)
            assert preserved is not None
            preserved.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        with factory() as session:
            response = sync_deadline_to_google_calendar(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
                deadline_id=env["matter_deadline_id"],
            )
            assert response.sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert (
                response.sync.dead_letter_reason
                == "provider_upsert_claim_expired_remote_unknown"
            )
        assert provider.calls == []
    finally:
        set_google_calendar_provider_for_tests(None)


@pytest.mark.parametrize(
    "provider_name",
    [CalendarProvider.GOOGLE_CALENDAR, CalendarProvider.OUTLOOK],
)
def test_projection_tombstone_materializes_expired_claim_and_preserves_typed_unknown(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider_name: CalendarProvider,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    provider = (
        StubGoogleCalendarProvider()
        if provider_name == CalendarProvider.GOOGLE_CALENDAR
        else StubOutlookProvider()
    )
    if provider_name == CalendarProvider.GOOGLE_CALENDAR:
        set_google_calendar_provider_for_tests(provider)
    else:
        set_outlook_provider_for_tests(provider)
    factory = get_session_factory()
    try:
        with factory() as session:
            connections = [
                UserCalendarConnection(
                    company_id=env["company_id"],
                    membership_id=membership_id,
                    provider=provider_name,
                    provider_account_id=f"projection-{provider_name}-{index}",
                    status="connected",
                    encrypted_token_ref=f"projection-{provider_name}-credential-{index}",
                )
                for index, membership_id in enumerate(
                    (env["owner_id"], env["reviewer_id"], env["unrelated_id"])
                )
            ]
            session.add_all(connections)
            session.flush()
            expired = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connections[0].id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=env["matter_deadline_id"],
                sync_status=CalendarEventSyncStatus.PENDING,
                dead_letter_reason=f"provider_upsert_claim:{provider_name}-expired",
                next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            typed = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connections[1].id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=env["matter_deadline_id"],
                sync_status=CalendarEventSyncStatus.DEAD_LETTER,
                dead_letter_reason=CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
                last_error="Calendar provider upsert outcome is unknown.",
                attempts=6,
            )
            known = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connections[2].id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=env["matter_deadline_id"],
                provider_event_id=f"{provider_name}-known-remote-event",
                sync_status=CalendarEventSyncStatus.SYNCED,
            )
            session.add_all([expired, typed, known])
            session.commit()
            expired_id = expired.id
            typed_id = typed.id
            known_id = known.id
            connection_ids = tuple(row.id for row in connections)

        with factory() as session:
            result = tombstone_matter_deadline_calendar_projections(
                session,
                company_id=env["company_id"],
                matter_deadline_id=env["matter_deadline_id"],
                reason="projection_secondary_writer_terminal",
            )
            session.commit()
            assert set(result.tombstoned_sync_ids) == {expired_id, known_id}
            assert result.delete_pending_sync_ids == (known_id,)
            assert result.deleted_sync_ids == ()

        assert provider.calls == []
        assert getattr(provider, "delete_calls", []) == []
        with factory() as session:
            expired = session.get(CalendarEventSync, expired_id)
            typed = session.get(CalendarEventSync, typed_id)
            known = session.get(CalendarEventSync, known_id)
            assert expired is not None and typed is not None and known is not None
            assert expired.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert expired.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            assert expired.next_attempt_at is None
            assert expired.durable_last_attempt_at is not None
            assert typed.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert typed.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            assert typed.last_error == "Calendar provider upsert outcome is unknown."
            assert typed.attempts == 6
            assert known.sync_status == CalendarEventSyncStatus.DELETE_PENDING
            assert known.provider_event_id == f"{provider_name}-known-remote-event"
            for connection_id in connection_ids:
                connection = session.get(UserCalendarConnection, connection_id)
                assert connection is not None and connection.encrypted_token_ref is not None

        operation = client.get(
            f"/api/admin/provider-operations/jobs/calendar_sync:{expired_id}",
            headers=auth_headers(env["owner_token"]),
        )
        assert operation.status_code == 200, operation.text
        assert operation.json()["manual_reconciliation_required"] is True
        assert operation.json()["replay_available"] is False
    finally:
        if provider_name == CalendarProvider.GOOGLE_CALENDAR:
            set_google_calendar_provider_for_tests(None)
        else:
            set_outlook_provider_for_tests(None)


def test_coverage_cutover_never_revives_claim_or_typed_unknown_rows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    google = StubGoogleCalendarProvider()
    outlook = StubOutlookProvider()
    set_google_calendar_provider_for_tests(google)
    set_outlook_provider_for_tests(outlook)
    factory = get_session_factory()
    try:
        with factory() as session:
            connections: dict[str, UserCalendarConnection] = {}
            for name, membership_id, provider_name in (
                ("expired_old", env["owner_id"], CalendarProvider.GOOGLE_CALENDAR),
                ("live_backup", env["reviewer_id"], CalendarProvider.OUTLOOK),
                ("typed_new", env["replacement_id"], CalendarProvider.GOOGLE_CALENDAR),
                ("known_unrelated", env["unrelated_id"], CalendarProvider.OUTLOOK),
            ):
                connection = UserCalendarConnection(
                    company_id=env["company_id"],
                    membership_id=membership_id,
                    provider=provider_name,
                    provider_account_id=f"cutover-{name}",
                    status="connected",
                    encrypted_token_ref=f"cutover-{name}-credential",
                )
                session.add(connection)
                session.flush()
                connections[name] = connection
            rows = {
                "expired_old": CalendarEventSync(
                    company_id=env["company_id"],
                    calendar_connection_id=connections["expired_old"].id,
                    source_type="matter_deadline",
                    source_id=env["matter_deadline_id"],
                    sync_status=CalendarEventSyncStatus.PENDING,
                    dead_letter_reason="provider_upsert_claim:cutover-expired-old",
                    next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
                ),
                "live_backup": CalendarEventSync(
                    company_id=env["company_id"],
                    calendar_connection_id=connections["live_backup"].id,
                    source_type="matter_deadline",
                    source_id=env["matter_deadline_id"],
                    sync_status=CalendarEventSyncStatus.PENDING,
                    dead_letter_reason="provider_upsert_claim:cutover-live-backup",
                    next_attempt_at=datetime.now(UTC) + timedelta(minutes=30),
                    attempts=3,
                    last_error="outlook-create-in-flight",
                ),
                "typed_new": CalendarEventSync(
                    company_id=env["company_id"],
                    calendar_connection_id=connections["typed_new"].id,
                    source_type="matter_deadline",
                    source_id=env["matter_deadline_id"],
                    sync_status=CalendarEventSyncStatus.DEAD_LETTER,
                    dead_letter_reason=CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
                    last_error="Calendar provider upsert outcome is unknown.",
                    attempts=8,
                ),
                "known_unrelated": CalendarEventSync(
                    company_id=env["company_id"],
                    calendar_connection_id=connections["known_unrelated"].id,
                    source_type="matter_deadline",
                    source_id=env["matter_deadline_id"],
                    provider_event_id="cutover-known-unrelated-event",
                    sync_status=CalendarEventSyncStatus.SYNCED,
                ),
            }
            session.add_all(rows.values())
            session.commit()
            row_ids = {name: row.id for name, row in rows.items()}
            connection_ids = {name: row.id for name, row in connections.items()}

        with factory() as session:
            docket, coverage = _lock_single_projection_chain(session, env=env)
            coverage.responsible_membership_id = env["replacement_id"]
            coverage.coverage_status = "reassigned"
            coverage.accepted_at = None
            coverage.reassignment_version += 1
            result = cutover_ip_coverage_projection(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["legal_id"],
                ),
                docket=docket,
                coverage=coverage,
                previous_responsible_membership_id=env["owner_id"],
                previous_backup_membership_id=env["reviewer_id"],
                reason="Cut over while calendar provider receipt state is fenced.",
                replacement_source="calendar_claim_cutover_regression",
                responsible_accepted_at=None,
                notification_escalation_membership_id=env["unrelated_id"],
                reminder_generation="calendar-claim-cutover-v1",
            )
            session.commit()
            assert set(result.calendar.desired_connection_ids) == {
                connection_ids["live_backup"],
                connection_ids["typed_new"],
            }

        assert google.calls == [] and google.delete_calls == []
        assert outlook.calls == []
        with factory() as session:
            expired = session.get(CalendarEventSync, row_ids["expired_old"])
            live = session.get(CalendarEventSync, row_ids["live_backup"])
            typed = session.get(CalendarEventSync, row_ids["typed_new"])
            known = session.get(CalendarEventSync, row_ids["known_unrelated"])
            assert all(row is not None for row in (expired, live, typed, known))
            assert expired is not None
            assert expired.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert expired.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            assert expired.next_attempt_at is None
            assert live is not None
            assert live.sync_status == CalendarEventSyncStatus.PENDING
            assert live.dead_letter_reason == "provider_upsert_claim:cutover-live-backup"
            assert live.attempts == 3 and live.last_error == "outlook-create-in-flight"
            assert typed is not None
            assert typed.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert typed.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            assert typed.attempts == 8
            assert known is not None
            assert known.sync_status == CalendarEventSyncStatus.DELETE_PENDING
            assert known.provider_event_id == "cutover-known-unrelated-event"
            coverage = session.scalar(
                select(IpDeadlineCoverage).where(
                    IpDeadlineCoverage.docket_id == env["docket_id"],
                    IpDeadlineCoverage.matter_deadline_id
                    == env["matter_deadline_id"],
                )
            )
            assert coverage is not None and coverage.calendar_projection_status == "pending"

        operation = client.get(
            f"/api/admin/provider-operations/jobs/calendar_sync:{row_ids['expired_old']}",
            headers=auth_headers(env["owner_token"]),
        )
        assert operation.status_code == 200, operation.text
        assert operation.json()["manual_reconciliation_required"] is True
    finally:
        set_google_calendar_provider_for_tests(None)
        set_outlook_provider_for_tests(None)


@pytest.mark.parametrize(
    "provider_name",
    [CalendarProvider.GOOGLE_CALENDAR, CalendarProvider.OUTLOOK],
)
@pytest.mark.parametrize(
    "authority_change",
    ["coverage_reassigned", "docket_terminal", "membership_inactive", "access_walled"],
)
def test_expired_create_claim_is_classified_before_changed_authority_can_erase_it(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider_name: CalendarProvider,
    authority_change: str,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    owner_membership_id = (
        env["reviewer_id"] if authority_change == "access_walled" else env["owner_id"]
    )
    provider = (
        StubGoogleCalendarProvider()
        if provider_name == CalendarProvider.GOOGLE_CALENDAR
        else StubOutlookProvider()
    )
    if provider_name == CalendarProvider.GOOGLE_CALENDAR:
        set_google_calendar_provider_for_tests(provider)
    else:
        set_outlook_provider_for_tests(provider)

    factory = get_session_factory()
    try:
        with factory() as session:
            connection = UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=owner_membership_id,
                provider=provider_name,
                status="connected",
                encrypted_token_ref=_encrypt_token_payload(
                    {"access_token": f"{provider_name}-unknown-repair-credential"}
                ),
            )
            session.add(connection)
            session.flush()
            sync = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connection.id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=env["matter_deadline_id"],
                sync_status=CalendarEventSyncStatus.PENDING,
                dead_letter_reason=f"provider_upsert_claim:{authority_change}",
                next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            session.add(sync)
            session.commit()
            sync_id = sync.id
            connection_id = connection.id

        if authority_change == "coverage_reassigned":
            with factory() as session:
                docket, coverage = _lock_single_projection_chain(session, env=env)
                coverage.responsible_membership_id = env["replacement_id"]
                coverage.coverage_status = "reassigned"
                coverage.accepted_at = None
                coverage.reassignment_version += 1
                cutover_ip_coverage_projection(
                    session,
                    context=_context(
                        session,
                        company_id=env["company_id"],
                        membership_id=env["legal_id"],
                    ),
                    docket=docket,
                    coverage=coverage,
                    previous_responsible_membership_id=env["owner_id"],
                    previous_backup_membership_id=env["reviewer_id"],
                    reason="Approved reassignment while provider receipt is pending.",
                    replacement_source="expired_claim_reassignment_test",
                    responsible_accepted_at=None,
                    notification_escalation_membership_id=env["unrelated_id"],
                    reminder_generation="expired-claim-reassignment-v2",
                )
                session.commit()
        elif authority_change == "docket_terminal":
            with factory() as session:
                docket = session.get(IpDocketRecord, env["docket_id"])
                assert docket is not None
                transition_ip_docket_lifecycle(
                    session,
                    context=_context(
                        session,
                        company_id=env["company_id"],
                        membership_id=env["legal_id"],
                    ),
                    docket_id=docket.id,
                    payload=IpLifecycleTransitionRequest(
                        expected_lifecycle_version=docket.lifecycle_version,
                        to_status="closed",
                        effective_at=datetime.now(UTC),
                        reason="Close docket while a provider receipt is pending.",
                        outcome="closed",
                        source="lawyer_review",
                        evidence_ref="audit:expired-calendar-claim-terminal",
                        linked_matter_handling="reviewed",
                    ),
                )
                session.commit()
        elif authority_change == "membership_inactive":
            with factory() as session:
                memberships = lock_company_memberships_for_assignment(
                    session,
                    company_id=env["company_id"],
                    membership_ids=(owner_membership_id,),
                )
                actor = memberships[owner_membership_id]
                tombstone_membership_calendar_projections(
                    session,
                    company_id=env["company_id"],
                    membership_id=owner_membership_id,
                    reason="membership_deactivated",
                )
                actor.is_active = False
                session.add(actor)
                session.commit()
        else:
            with factory() as session:
                session.add(
                    EthicalWall(
                        company_id=env["company_id"],
                        matter_id=env["matter_id"],
                        excluded_membership_id=owner_membership_id,
                        reason="Matter access removed while provider receipt is pending.",
                        created_by_membership_id=env["legal_id"],
                    )
                )
                session.commit()

        with factory() as session:
            preserved = session.get(CalendarEventSync, sync_id)
            assert preserved is not None
            assert preserved.dead_letter_reason == (
                f"provider_upsert_claim:{authority_change}"
            )
            preserved.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(preserved)
            session.commit()

        with factory() as session:
            context = _context(
                session,
                company_id=env["company_id"],
                membership_id=owner_membership_id,
            )
            response = (
                sync_deadline_to_google_calendar(
                    session,
                    context=context,
                    deadline_id=env["matter_deadline_id"],
                )
                if provider_name == CalendarProvider.GOOGLE_CALENDAR
                else sync_deadline_to_outlook(
                    session,
                    context=context,
                    deadline_id=env["matter_deadline_id"],
                )
            )
            assert response.sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert response.sync.dead_letter_reason == (
                "provider_upsert_claim_expired_remote_unknown"
            )

        assert provider.calls == []
        with factory() as session:
            connection = session.get(UserCalendarConnection, connection_id)
            sync = session.get(CalendarEventSync, sync_id)
            assert connection is not None and sync is not None
            assert sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert sync.dead_letter_reason == (
                "provider_upsert_claim_expired_remote_unknown"
            )
            assert connection.encrypted_token_ref is not None
    finally:
        if provider_name == CalendarProvider.GOOGLE_CALENDAR:
            set_google_calendar_provider_for_tests(None)
        else:
            set_outlook_provider_for_tests(None)


@pytest.mark.parametrize(
    "provider_name",
    [CalendarProvider.GOOGLE_CALENDAR, CalendarProvider.OUTLOOK],
)
def test_durable_provider_entrypoint_classifies_expired_claim_before_access_poison(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider_name: CalendarProvider,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    provider = (
        StubGoogleCalendarProvider()
        if provider_name == CalendarProvider.GOOGLE_CALENDAR
        else StubOutlookProvider()
    )
    if provider_name == CalendarProvider.GOOGLE_CALENDAR:
        set_google_calendar_provider_for_tests(provider)
    else:
        _configure_ready_outlook(client, env["owner_token"], provider)

    factory = get_session_factory()
    try:
        with factory() as session:
            connection = UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=env["reviewer_id"],
                provider=provider_name,
                status="connected",
                encrypted_token_ref=_encrypt_token_payload(
                    {"access_token": "fixture-access-credential"}
                ),
            )
            session.add(connection)
            session.flush()
            sync = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connection.id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=env["matter_deadline_id"],
                sync_status=CalendarEventSyncStatus.PENDING,
                dead_letter_reason="provider_upsert_claim:durable-access-poison",
                next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            session.add(sync)
            session.commit()
            sync_id = sync.id

        with factory() as session:
            session.add(
                EthicalWall(
                    company_id=env["company_id"],
                    matter_id=env["matter_id"],
                    excluded_membership_id=env["reviewer_id"],
                    reason="Access revoked before durable claim recovery.",
                    created_by_membership_id=env["legal_id"],
                )
            )
            session.commit()
        with factory() as session:
            sync = session.get(CalendarEventSync, sync_id)
            deadline = session.get(MatterDeadline, env["matter_deadline_id"])
            assert sync is not None and deadline is not None
            assert sync.dead_letter_reason == (
                "provider_upsert_claim:durable-access-poison"
            )
            sync.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(sync)
            session.commit()
            due_on = deadline.due_on

        with factory() as session:
            context = _context(
                session,
                company_id=env["company_id"],
                membership_id=env["legal_id"],
            )
            result = (
                process_durable_google_calendar_sync(
                    session,
                    context=context,
                    range_from=due_on - timedelta(days=1),
                    range_to=due_on + timedelta(days=1),
                    limit=1,
                )
                if provider_name == CalendarProvider.GOOGLE_CALENDAR
                else process_durable_outlook_sync(
                    session,
                    context=context,
                    range_from=due_on - timedelta(days=1),
                    range_to=due_on + timedelta(days=1),
                    limit=1,
                )
            )
            assert result.dead_lettered == 1
            assert result.provider_calls == 0

        assert provider.calls == []
        with factory() as session:
            sync = session.get(CalendarEventSync, sync_id)
            assert sync is not None
            assert sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            assert sync.dead_letter_reason == (
                "provider_upsert_claim_expired_remote_unknown"
            )
    finally:
        if provider_name == CalendarProvider.GOOGLE_CALENDAR:
            set_google_calendar_provider_for_tests(None)
        else:
            set_outlook_provider_for_tests(None)


def test_revoked_expired_known_id_update_claim_drains_exact_remote_copy(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider=CalendarProvider.GOOGLE_CALENDAR,
            status="connected",
            encrypted_token_ref=_encrypt_token_payload(
                {"access_token": "google-access-credential"}
            ),
        )
        session.add(connection)
        session.flush()
        sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connection.id,
            source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
            source_id=env["matter_deadline_id"],
            provider_event_id="known-remote-event-before-update",
            sync_status=CalendarEventSyncStatus.PENDING,
            dead_letter_reason="provider_upsert_claim:crashed-update-worker",
            next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(sync)
        session.commit()
        connection_id = connection.id
        sync_id = sync.id

    provider = StubGoogleCalendarProvider()
    set_google_calendar_provider_for_tests(provider)
    try:
        with factory() as session:
            context = _context(
                session,
                company_id=env["company_id"],
                membership_id=env["owner_id"],
            )
            revoke_connection(
                session,
                context=context,
                connection_id=connection_id,
            )
            result = process_calendar_deletion_tombstones(
                session,
                context=context,
                calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
                limit=1,
            )
            assert result.deleted == 1
            assert result.provider_calls == 1
        assert provider.delete_calls == ["known-remote-event-before-update"]
        with factory() as session:
            connection = session.get(UserCalendarConnection, connection_id)
            sync = session.get(CalendarEventSync, sync_id)
            assert connection is not None and sync is not None
            assert sync.sync_status == CalendarEventSyncStatus.DELETED
            assert sync.dead_letter_reason is None
            assert connection.encrypted_token_ref is None
    finally:
        set_google_calendar_provider_for_tests(None)


@pytest.mark.parametrize(
    "provider_name",
    [CalendarProvider.GOOGLE_CALENDAR, CalendarProvider.OUTLOOK],
)
def test_bounded_calendar_worker_filters_out_of_range_pending_before_limit(
    client: TestClient,
    provider_name: CalendarProvider,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter = _mk_matter(client, token, f"RANGE-{provider_name.replace('_', '-')}")
    if provider_name == CalendarProvider.OUTLOOK:
        provider = StubOutlookProvider()
        connection_id = _configure_ready_outlook(client, token, provider)
    else:
        provider = StubGoogleCalendarProvider()
        set_google_calendar_provider_for_tests(provider)
        with get_session_factory()() as session:
            connection = UserCalendarConnection(
                company_id=company_id,
                membership_id=membership_id,
                provider=CalendarProvider.GOOGLE_CALENDAR,
                status="connected",
                encrypted_token_ref=_encrypt_token_payload(
                    {"access_token": "google-access-credential"}
                ),
            )
            session.add(connection)
            session.commit()
            connection_id = connection.id

    range_from = date.today()
    eligible_due_on = range_from + timedelta(days=2)
    factory = get_session_factory()
    with factory() as session:
        poison = MatterDeadline(
            company_id=company_id,
            matter_id=str(matter["id"]),
            source="manual",
            kind="filing",
            title="Old out-of-range pending row",
            due_on=range_from - timedelta(days=90),
            status="open",
            assignee_membership_id=membership_id,
            created_by_membership_id=membership_id,
        )
        eligible = MatterDeadline(
            company_id=company_id,
            matter_id=str(matter["id"]),
            source="manual",
            kind="filing",
            title="Eligible pending row",
            due_on=eligible_due_on,
            status="open",
            assignee_membership_id=membership_id,
            created_by_membership_id=membership_id,
        )
        session.add_all([poison, eligible])
        session.flush()
        poison_sync = CalendarEventSync(
            company_id=company_id,
            calendar_connection_id=connection_id,
            source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
            source_id=poison.id,
            sync_status=CalendarEventSyncStatus.PENDING,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        eligible_sync = CalendarEventSync(
            company_id=company_id,
            calendar_connection_id=connection_id,
            source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
            source_id=eligible.id,
            sync_status=CalendarEventSyncStatus.PENDING,
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        session.add_all([poison_sync, eligible_sync])
        session.commit()
        poison_sync_id = poison_sync.id
        eligible_sync_id = eligible_sync.id
        eligible_id = eligible.id

    try:
        with factory() as session:
            context = _context(
                session,
                company_id=company_id,
                membership_id=membership_id,
            )
            if provider_name == CalendarProvider.OUTLOOK:
                result = process_durable_outlook_sync(
                    session,
                    context=context,
                    range_from=range_from,
                    range_to=range_from + timedelta(days=10),
                    limit=1,
                )
            else:
                result = process_durable_google_calendar_sync(
                    session,
                    context=context,
                    range_from=range_from,
                    range_to=range_from + timedelta(days=10),
                    limit=1,
                )
        assert result.examined == 1
        assert result.synced == 1
        assert [call["source_id"] for call in provider.calls] == [eligible_id]
        with factory() as session:
            assert session.get(CalendarEventSync, poison_sync_id).sync_status == (
                CalendarEventSyncStatus.PENDING
            )
            assert session.get(CalendarEventSync, eligible_sync_id).sync_status == (
                CalendarEventSyncStatus.SYNCED
            )
    finally:
        if provider_name == CalendarProvider.GOOGLE_CALENDAR:
            set_google_calendar_provider_for_tests(None)
        else:
            set_outlook_provider_for_tests(None)


def test_durable_outlook_drains_exact_pending_ip_deadline_and_recomputes_projection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProjectionOutlookProvider(StubOutlookProvider):
        def __init__(self) -> None:
            super().__init__()
            self.delete_calls: list[str] = []

        def delete_event(
            self,
            *,
            token_payload: dict[str, object],
            provider_event_id: str,
        ) -> None:
            assert token_payload["access_token"] == "fixture-access-credential"
            self.delete_calls.append(provider_event_id)

    env = _confirmed_deadline_environment(client, monkeypatch)
    provider = ProjectionOutlookProvider()
    try:
        owner_connection_id = _configure_ready_outlook(
            client,
            env["owner_token"],
            provider,
        )
        factory = get_session_factory()
        with factory() as session:
            deadline = session.get(MatterDeadline, env["matter_deadline_id"])
            coverage = session.scalar(
                select(IpDeadlineCoverage).where(
                    IpDeadlineCoverage.matter_deadline_id
                    == env["matter_deadline_id"]
                )
            )
            assert deadline is not None and coverage is not None
            unrelated_connection = UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=env["unrelated_id"],
                provider=CalendarProvider.OUTLOOK,
                status="connected",
                encrypted_token_ref=_encrypt_token_payload(
                    {"access_token": "fixture-access-credential"}
                ),
            )
            session.add(unrelated_connection)
            session.flush()
            desired = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=owner_connection_id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=deadline.id,
                sync_status=CalendarEventSyncStatus.PENDING,
            )
            stale = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=unrelated_connection.id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=deadline.id,
                provider_event_id="stale-outlook-ip-copy",
                sync_status=CalendarEventSyncStatus.DELETE_PENDING,
            )
            coverage.calendar_projection_status = "pending"
            session.add_all([desired, stale, coverage])
            session.commit()
            due_on = deadline.due_on
            desired_id = desired.id
            stale_id = stale.id

        with factory() as session:
            result = process_durable_outlook_sync(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
                range_from=due_on,
                range_to=due_on,
            )

        assert result.examined == 1
        assert result.synced == 1
        assert provider.delete_calls == ["stale-outlook-ip-copy"]
        assert [call["source_id"] for call in provider.calls] == [
            env["matter_deadline_id"]
        ]
        with factory() as session:
            assert session.get(CalendarEventSync, desired_id).sync_status == (
                CalendarEventSyncStatus.SYNCED
            )
            assert session.get(CalendarEventSync, stale_id).sync_status == (
                CalendarEventSyncStatus.DELETED
            )
            coverage = session.scalar(
                select(IpDeadlineCoverage).where(
                    IpDeadlineCoverage.matter_deadline_id
                    == env["matter_deadline_id"]
                )
            )
            assert coverage is not None
            assert coverage.calendar_projection_status == "projected"
    finally:
        set_outlook_provider_for_tests(None)


def test_durable_google_deadline_drain_is_row_driven_and_isolates_shared_authority(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    sibling = _docket_for_matter(
        client,
        auth_headers(env["owner_token"]),
        matter_id=env["matter_id"],
    )
    provider = StubGoogleCalendarProvider()
    set_google_calendar_provider_for_tests(provider)
    try:
        factory = get_session_factory()
        with factory() as session:
            connection = UserCalendarConnection(
                company_id=env["company_id"],
                membership_id=env["owner_id"],
                provider=CalendarProvider.GOOGLE_CALENDAR,
                status="connected",
                encrypted_token_ref=_encrypt_token_payload(
                    {"access_token": "google-access-credential"}
                ),
            )
            session.add(connection)
            session.flush()
            session.add(
                IpDeadlineCoverage(
                    company_id=env["company_id"],
                    docket_id=str(sibling["id"]),
                    matter_deadline_id=env["matter_deadline_id"],
                    responsible_membership_id=env["unrelated_id"],
                    backup_membership_id=env["reviewer_id"],
                    coverage_status="accepted",
                    calendar_projection_status="pending",
                    accepted_at=datetime(2026, 8, 17, 10, tzinfo=UTC),
                )
            )
            shared = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connection.id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=env["matter_deadline_id"],
                sync_status=CalendarEventSyncStatus.PENDING,
            )
            safe_deadline = MatterDeadline(
                company_id=env["company_id"],
                matter_id=env["matter_id"],
                source="manual",
                kind="filing",
                title="Independent non-IP calendar deadline",
                due_on=date(2026, 9, 30),
                status="open",
                assignee_membership_id=env["owner_id"],
                created_by_membership_id=env["owner_id"],
            )
            session.add_all([shared, safe_deadline])
            session.flush()
            safe = CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connection.id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=safe_deadline.id,
                sync_status=CalendarEventSyncStatus.PENDING,
            )
            session.add(safe)
            session.commit()
            shared_id = shared.id
            safe_sync_id = safe.id
            safe_deadline_id = safe_deadline.id

        with factory() as session:
            first = process_durable_google_calendar_sync(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
                range_from=date(2026, 8, 1),
                range_to=date(2026, 10, 31),
                limit=1,
            )
        assert first.examined == 1
        assert first.skipped == 1
        assert first.dead_lettered == 1
        assert first.synced == 0
        assert provider.calls == []

        with factory() as session:
            second = process_durable_google_calendar_sync(
                session,
                context=_context(
                    session,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
                range_from=date(2026, 8, 1),
                range_to=date(2026, 10, 31),
                limit=1,
            )
        assert second.examined == 1
        assert second.skipped == 0
        assert second.synced == 1
        assert [call["source_id"] for call in provider.calls] == [safe_deadline_id]
        with factory() as session:
            assert session.get(CalendarEventSync, shared_id).sync_status == (
                CalendarEventSyncStatus.DEAD_LETTER
            )
            assert str(
                session.get(CalendarEventSync, shared_id).dead_letter_reason
            ).startswith("projection_authority_invalid:")
            assert session.get(CalendarEventSync, safe_sync_id).sync_status == (
                CalendarEventSyncStatus.SYNCED
            )
    finally:
        set_google_calendar_provider_for_tests(None)


@pytest.mark.postgres
def test_postgres_revoke_serializes_between_provider_claim_and_finalize(
    pg_engine,
) -> None:
    """A committed claim releases every PG lock before revoke/provider I/O."""

    # This module can sort before test_postgres_validation.py under `-m
    # postgres`, so independently make the shared sidecar schema current.
    from alembic.config import Config

    from alembic import command

    postgres_url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    project_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(project_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_root / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(alembic_config, "head")

    from tests.test_postgres_validation import (
        _ip_race_context,
        _seed_ip_coverage_lifecycle_fixture,
    )

    with Session(pg_engine, expire_on_commit=False) as seed_session:
        env = _seed_ip_coverage_lifecycle_fixture(seed_session)
        connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider=CalendarProvider.GOOGLE_CALENDAR,
            status="connected",
            encrypted_token_ref=_encrypt_token_payload(
                {"access_token": "google-access-credential"}
            ),
        )
        seed_session.add(connection)
        seed_session.commit()
        connection_id = connection.id

    provider_entered = Event()
    allow_provider_return = Event()
    provider_session_ids: list[int] = []

    class BlockingGoogleProvider(StubGoogleCalendarProvider):
        def upsert_calendar_item(self, **kwargs) -> str:
            callback_session = object_session(kwargs["item"].ip_docket)
            assert callback_session is not None
            assert callback_session.in_transaction() is False
            provider_session_ids.append(id(callback_session))
            provider_entered.set()
            assert allow_provider_return.wait(10), "revoke never released provider callback"
            return super().upsert_calendar_item(**kwargs)

        def delete_event(self, **kwargs) -> None:
            assert provider_session_ids
            # The exact deletion was claimed and committed before cleanup I/O.
            assert worker_session_ref[0].in_transaction() is False
            return super().delete_event(**kwargs)

    provider = BlockingGoogleProvider()
    worker_session_ref: list[Session] = []
    set_google_calendar_provider_for_tests(provider)

    def _worker():
        with Session(pg_engine, expire_on_commit=False) as worker_session:
            worker_session_ref.append(worker_session)
            return sync_deadline_to_google_calendar(
                worker_session,
                context=_ip_race_context(
                    worker_session,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
                deadline_id=env["deadline_id"],
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_worker)
            try:
                assert provider_entered.wait(10), "provider claim never committed"
                with Session(pg_engine, expire_on_commit=False) as revoker_session:
                    assert id(revoker_session) != provider_session_ids[0]
                    revoked = revoke_connection(
                        revoker_session,
                        context=_ip_race_context(
                            revoker_session,
                            company_id=env["company_id"],
                            membership_id=env["owner_id"],
                        ),
                        connection_id=connection_id,
                    )
                    assert revoked.status == "revoked"
            finally:
                allow_provider_return.set()
            result = future.result(timeout=15)

        assert result.sync.sync_status == CalendarEventSyncStatus.DELETED
        assert len(provider.calls) == 1
        assert provider.delete_calls == ["google-event-1"]
        with Session(pg_engine, expire_on_commit=False) as verify_session:
            connection = verify_session.get(UserCalendarConnection, connection_id)
            sync = verify_session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.calendar_connection_id == connection_id,
                    CalendarEventSync.source_id == env["deadline_id"],
                )
            )
            coverage = verify_session.get(
                IpDeadlineCoverage,
                env["coverage_id"],
            )
            assert connection is not None and sync is not None and coverage is not None
            assert connection.status == "revoked"
            assert connection.encrypted_token_ref is None
            assert sync.sync_status == CalendarEventSyncStatus.DELETED
            assert coverage.calendar_projection_status == "projected"
    finally:
        allow_provider_return.set()
        set_google_calendar_provider_for_tests(None)


@pytest.mark.postgres
def test_postgres_matter_grant_revocation_wins_before_calendar_claim(
    pg_engine,
) -> None:
    """A canonical access writer that wins first prevents provider I/O."""

    from alembic.config import Config

    from alembic import command
    from tests.test_postgres_validation import (
        _ip_race_context,
        _seed_ip_coverage_lifecycle_fixture,
    )

    postgres_url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    project_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(project_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_root / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(alembic_config, "head")

    with Session(pg_engine, expire_on_commit=False) as seed:
        env = _seed_ip_coverage_lifecycle_fixture(seed)
        matter = seed.get(Matter, env["matter_id"])
        assert matter is not None
        matter.restricted_access = True
        hearing = MatterHearing(
            company_id=env["company_id"],
            matter_id=matter.id,
            hearing_on=date.today() + timedelta(days=8),
            forum_name="Delhi High Court",
            purpose="PostgreSQL access fence",
            responsible_membership_id=env["owner_id"],
        )
        grant = MatterAccessGrant(
            company_id=env["company_id"],
            matter_id=matter.id,
            membership_id=env["owner_id"],
            granted_by_membership_id=env["replacement_id"],
            reason="Temporary provider access.",
        )
        connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider=CalendarProvider.GOOGLE_CALENDAR,
            status="connected",
            encrypted_token_ref=_encrypt_token_payload(
                {"access_token": "google-access-credential"}
            ),
        )
        seed.add_all([matter, hearing, grant, connection])
        seed.commit()
        hearing_id = hearing.id
        grant_id = grant.id

    class NoCallGoogleProvider(StubGoogleCalendarProvider):
        def upsert_calendar_item(self, **kwargs) -> str:  # pragma: no cover
            raise AssertionError("revoked Matter access must block provider I/O")

    provider = NoCallGoogleProvider()
    set_google_calendar_provider_for_tests(provider)
    writer_has_locks = Event()
    release_writer = Event()

    def revoke_access() -> None:
        with Session(pg_engine, expire_on_commit=False) as writer:
            lock_company_memberships_for_assignment(
                writer,
                company_id=env["company_id"],
                membership_ids=(env["owner_id"], env["replacement_id"]),
            )
            writer.scalar(
                select(Matter)
                .where(Matter.id == env["matter_id"])
                .with_for_update(of=Matter)
            )
            locked_grant = writer.scalar(
                select(MatterAccessGrant)
                .where(MatterAccessGrant.id == grant_id)
                .with_for_update(of=MatterAccessGrant)
            )
            assert locked_grant is not None
            locked_grant.revoked_at = datetime.now(UTC)
            locked_grant.revoked_by_membership_id = env["replacement_id"]
            writer_has_locks.set()
            assert release_writer.wait(10)
            writer.commit()

    def sync_calendar():
        with Session(pg_engine, expire_on_commit=False) as worker:
            return sync_hearing_to_google_calendar(
                worker,
                context=_ip_race_context(
                    worker,
                    company_id=env["company_id"],
                    membership_id=env["owner_id"],
                ),
                hearing_id=hearing_id,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            revoke_future = executor.submit(revoke_access)
            assert writer_has_locks.wait(10)
            sync_future = executor.submit(sync_calendar)
            try:
                with pytest.raises(TimeoutError):
                    sync_future.result(timeout=0.05)
            finally:
                release_writer.set()
            revoke_future.result(timeout=10)
            response = sync_future.result(timeout=10)
        assert response.sync.sync_status == CalendarEventSyncStatus.DELETED
        assert provider.calls == []
    finally:
        release_writer.set()
        set_google_calendar_provider_for_tests(None)


@pytest.mark.postgres
def test_postgres_legacy_and_intent_workers_emit_one_hearing_email(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent compatibility projection cannot race a second provider send."""

    from alembic.config import Config

    from alembic import command
    from tests.test_postgres_validation import _seed_ip_coverage_lifecycle_fixture

    postgres_url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    project_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(project_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(project_root / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(alembic_config, "head")

    settings = get_settings()
    monkeypatch.setattr(settings, "hearing_reminders_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_provider", "sendgrid")
    monkeypatch.setattr(settings, "sendgrid_api_key", "test-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")

    with Session(pg_engine, expire_on_commit=False) as seed:
        env = _seed_ip_coverage_lifecycle_fixture(seed)
        hearing = MatterHearing(
            company_id=env["company_id"],
            matter_id=env["matter_id"],
            hearing_on=date.today() + timedelta(days=1),
            forum_name="Delhi High Court",
            purpose="Concurrent canonical reminder",
            responsible_membership_id=env["owner_id"],
        )
        seed.add(hearing)
        seed.flush()
        due_at = datetime.now(UTC) - timedelta(minutes=1)
        reminder = HearingReminder(
            company_id=env["company_id"],
            matter_id=env["matter_id"],
            hearing_id=hearing.id,
            recipient_membership_id=env["owner_id"],
            recipient_email="notice-pg@example.test",
            channel="email",
            scheduled_for=due_at,
            status="queued",
        )
        intent = NotificationDeliveryIntent(
            company_id=env["company_id"],
            recipient_membership_id=env["owner_id"],
            matter_id=env["matter_id"],
            channel="email",
            event_type="hearing_upcoming",
            source_type="hearing_reminder",
            source_id=f"pg:{hearing.id}:v1",
            idempotency_key=uuid4().hex,
            status="queued",
            scheduled_for=due_at,
            title="CaseOps notification",
            body="Open CaseOps to review this notification securely.",
            schedule_source_type="matter_hearing",
            schedule_source_id=hearing.id,
            dispatch_owner="durable_intent",
            comparison_status="dual_read_matched",
        )
        seed.add_all([reminder, intent])
        seed.flush()
        seed.add(
            HearingReminderDeliveryIntent(
                hearing_reminder_id=reminder.id,
                intent_id=intent.id,
                is_primary=True,
            )
        )
        seed.commit()
        reminder_id = reminder.id
        intent_id = intent.id

    external_calls: list[str] = []
    drain_sessions: list[Session] = []

    def canonical_send(**kwargs):
        assert drain_sessions
        assert drain_sessions[0].in_transaction() is False
        external_calls.append(str(kwargs["custom_args"]["notification_intent_id"]))
        return True, "pg-canonical-reminder-message", None

    def legacy_send_forbidden(**_kwargs):  # pragma: no cover - assertion boundary
        raise AssertionError("legacy worker attempted provider I/O")

    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        canonical_send,
    )
    monkeypatch.setattr(
        "caseops_api.services.hearing_reminders._send_via_sendgrid",
        legacy_send_forbidden,
    )
    monkeypatch.setattr(
        "caseops_api.services.hearing_reminders._send_via_twilio_sms",
        legacy_send_forbidden,
    )
    start = Event()

    def project_legacy():
        with Session(pg_engine, expire_on_commit=False) as session:
            assert start.wait(10)
            return run_reminder_worker(session, mode="live", limit=10)

    def drain_intent():
        with Session(pg_engine, expire_on_commit=False) as session:
            drain_sessions.append(session)
            assert start.wait(10)
            return drain_notification_delivery_intents(session, limit=10)

    with ThreadPoolExecutor(max_workers=2) as executor:
        legacy_future = executor.submit(project_legacy)
        drain_future = executor.submit(drain_intent)
        start.set()
        legacy_future.result(timeout=15)
        drained = drain_future.result(timeout=15)

    assert drained["external_calls"] == 1
    assert external_calls == [intent_id]
    with Session(pg_engine) as verify:
        reminder = verify.get(HearingReminder, reminder_id)
        intent = verify.get(NotificationDeliveryIntent, intent_id)
        assert reminder is not None and reminder.status == "sent"
        assert intent is not None and intent.status == "sent"
        assert intent.provider_event_id == "pg-canonical-reminder-message"


def test_calendar_lock_inventory_is_sync_before_connection() -> None:
    from caseops_api.services import calendar_sync, ip_coverage_projection

    for function in (
            ip_coverage_projection.reconcile_ip_coverage_calendar_projections,
            calendar_sync._recompute_ip_calendar_projection_status,
            calendar_sync._process_calendar_deletion_tombstone_by_id,
            calendar_sync._post_provider_deletion_winner,
    ):
        source = inspect.getsource(function)
        assert source.index("with_for_update(of=CalendarEventSync)") < source.index(
            "with_for_update(of=UserCalendarConnection)"
        ), function.__name__
