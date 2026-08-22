from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    CalendarEventSync,
    Company,
    CompanyMembership,
    HearingReminder,
    HearingReminderDeliveryIntent,
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketEvent,
    IpDocketRecord,
    IpRelatedRightObligation,
    IpResponsibilityAssignment,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    NotificationDeliveryIntent,
    User,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_lifecycle import (
    IpDocketEventCreateRequest,
    IpLifecycleTransitionRequest,
)
from caseops_api.services.calendar_projection_safety import (
    CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
)
from caseops_api.services.ip_lifecycle import (
    append_ip_docket_event,
    list_ip_docket_events,
    transition_ip_docket_lifecycle,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_coverage_projection_cutover import _confirmed_deadline_environment

EFFECTIVE_AT = datetime(2026, 8, 7, 4, 30, tzinfo=UTC)


def _particulars(mark: str) -> dict:
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {
            "text": mark,
            "evidence_reference": f"fixture:{mark.lower()}",
        },
        "classes": [{"class_number": 9, "specification": "Downloadable software"}],
        "use_priority": None,
        "parties": [{"role": "applicant", "name": "Fixture Applicant LLP"}],
        "agent": None,
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Mark representation",
                "required": True,
                "evidence_reference": f"fixture:{mark.lower()}",
            }
        ],
    }


def _docket(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    matter_id: str | None = None,
) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": matter_id is not None,
            "particulars": _particulars(title),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _context(session, bootstrap: dict) -> SessionContext:
    company = session.get(Company, str(bootstrap["company"]["id"]))
    membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
    assert company is not None and membership is not None
    user = session.get(User, membership.user_id)
    assert user is not None
    return SessionContext(company=company, membership=membership, user=user)


def _manual_event(*, membership_id: str, **overrides) -> IpDocketEventCreateRequest:
    payload = {
        "expected_lifecycle_version": 0,
        "event_kind": "examination_report",
        "source": "manual",
        "effective_at": EFFECTIVE_AT,
        "responsible_membership_id": membership_id,
        "reason": "Official examination report received and reviewed.",
        "evidence_refs": ["attachment:exam-report-1"],
        "resulting_stage": "examination",
    }
    payload.update(overrides)
    return IpDocketEventCreateRequest(**payload)


def test_append_only_events_preserve_sequence_corrections_and_registry_candidates(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    docket = _docket(client, headers, title="EVENT HISTORY MARK")
    membership_id = str(bootstrap["membership"]["id"])

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        original = append_ip_docket_event(
            session,
            context=context,
            docket_id=docket["id"],
            payload=_manual_event(membership_id=membership_id),
        )
        correction = append_ip_docket_event(
            session,
            context=context,
            docket_id=docket["id"],
            payload=_manual_event(
                membership_id=membership_id,
                event_kind="response",
                supersedes_event_id=original.id,
                correction_reason="The event type was entered incorrectly.",
                reason="Correct the event type without changing source history.",
            ),
        )
        candidate = append_ip_docket_event(
            session,
            context=context,
            docket_id=docket["id"],
            payload=_manual_event(
                membership_id=membership_id,
                event_kind="publication",
                source="registry",
                source_reference="ipindia:fixture-101",
                reason=None,
                candidate_status="candidate",
            ),
        )
        rows = list_ip_docket_events(
            session,
            context=context,
            docket_id=docket["id"],
        )

        assert [row.sequence for row in rows] == [1, 2, 3]
        assert rows[0].event_kind == "examination_report"
        assert rows[0].reason == "Official examination report received and reviewed."
        assert correction.supersedes_event_id == original.id
        assert candidate.candidate_status == "candidate"
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.company_id == context.company.id,
                    AuditEvent.target_type == "ip_docket_event",
                )
            )
        )
        assert actions == {"ip_docket.event_appended"}


def test_event_commands_reject_stale_registry_and_cross_tenant_targets(
    client: TestClient,
) -> None:
    first = bootstrap_company(client)
    first_headers = auth_headers(str(first["access_token"]))
    first_docket = _docket(client, first_headers, title="FIRST TENANT MARK")
    membership_id = str(first["membership"]["id"])

    second_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second IP Firm",
            "company_slug": "second-ip-firm",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "second-owner@example.com",
            "owner_password": "SecondOwnerPass123!",
        },
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    second_headers = auth_headers(str(second["access_token"]))
    second_docket = _docket(client, second_headers, title="SECOND TENANT MARK")
    asset = client.post(
        f"/api/ip/dockets/{second_docket['id']}/assets",
        headers=second_headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": "SECOND"},
    )
    assert asset.status_code == 201, asset.text
    application = client.post(
        f"/api/ip/dockets/{second_docket['id']}/applications",
        headers=second_headers,
        json={
            "asset_id": asset.json()["id"],
            "office": "IP India",
            "jurisdiction": "IN",
            "filing_phase": "draft",
            "source_pending_identifier_allocation": False,
        },
    )
    assert application.status_code == 201, application.text

    with get_session_factory()() as session:
        context = _context(session, first)
        with pytest.raises(HTTPException) as registry_error:
            append_ip_docket_event(
                session,
                context=context,
                docket_id=first_docket["id"],
                payload=_manual_event(
                    membership_id=membership_id,
                    source="registry",
                    source_reference="ipindia:test-registry-event",
                    reason=None,
                ),
            )
        assert registry_error.value.status_code == 422

        with pytest.raises(HTTPException) as tenant_error:
            append_ip_docket_event(
                session,
                context=context,
                docket_id=first_docket["id"],
                    payload=_manual_event(
                        membership_id=membership_id,
                        application_id=application.json()["application"]["id"],
                        expected_application_version=1,
                    ),
            )
        assert tenant_error.value.status_code == 422

        with pytest.raises(HTTPException) as stale_error:
            append_ip_docket_event(
                session,
                context=context,
                docket_id=first_docket["id"],
                payload=_manual_event(
                    membership_id=membership_id,
                    expected_lifecycle_version=9,
                ),
            )
        assert stale_error.value.status_code == 409
        assert session.scalar(select(IpDocketEvent)) is None


def test_lifecycle_transition_is_fail_closed_and_reopen_does_not_revive_children(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-LIFE-001")
    docket = _docket(
        client,
        headers,
        title="LIFECYCLE MARK",
        matter_id=matter["id"],
    )
    membership_id = str(bootstrap["membership"]["id"])
    deadline_response = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "trademark_response",
            "title": "Respond to examination report",
            "due_on": str(date.today() + timedelta(days=30)),
            "assignee_membership_id": membership_id,
        },
    )
    assert deadline_response.status_code == 200, deadline_response.text
    deadline_id = deadline_response.json()["id"]

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        coverage = IpDeadlineCoverage(
            company_id=context.company.id,
            docket_id=docket["id"],
            matter_deadline_id=deadline_id,
            responsible_membership_id=membership_id,
            coverage_status="accepted",
            calendar_projection_status="pending",
        )
        obligation = IpRelatedRightObligation(
            company_id=context.company.id,
            docket_id=docket["id"],
            obligation_type="response",
            title="Respond to examination report",
            due_on=date.today() + timedelta(days=30),
            owner_membership_id=membership_id,
            matter_deadline_id=deadline_id,
            status="open",
            evidence_reference="attachment:exam-report-1",
        )
        session.add_all([coverage, obligation])
        session.commit()

        terminal, terminal_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=docket["id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=EFFECTIVE_AT,
                reason="Registration is no longer maintained by this firm.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref="attachment:closure-instruction-1",
                linked_matter_handling="reviewed",
            ),
        )
        assert terminal.is_active is False
        assert terminal.lifecycle_version == 1
        assert terminal_event.before_phase == "ready"
        assert terminal_event.after_phase == "closed"

        session.refresh(coverage)
        session.refresh(obligation)
        deadline = session.get(MatterDeadline, deadline_id)
        assert coverage.coverage_status == "inactive_lifecycle"
        assert obligation.status == "cancelled_lifecycle"
        assert deadline is not None and deadline.status == "cancelled"

        with pytest.raises(HTTPException) as stale_transition:
            transition_ip_docket_lifecycle(
                session,
                context=context,
                docket_id=docket["id"],
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=0,
                    to_status="ready",
                    effective_at=EFFECTIVE_AT,
                    reason="Stale reopening request must be rejected.",
                    outcome="reopened",
                    source="lawyer_review",
                    evidence_ref="attachment:stale-reopen",
                    linked_matter_handling="reviewed",
                ),
            )
        assert stale_transition.value.status_code == 409
        session.rollback()

    assert client.get(f"/api/ip/dockets/{docket['id']}", headers=headers).status_code == 404
    blocked_version = client.post(
        f"/api/ip/dockets/{docket['id']}/versions",
        headers=headers,
        json=_particulars("BLOCKED") | {"expected_current_version": 1, "finalize": True},
    )
    assert blocked_version.status_code == 404

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        reopened, reopened_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=docket["id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=1,
                to_status="ready",
                effective_at=EFFECTIVE_AT + timedelta(days=1),
                reason="Named lawyer approved a controlled reopen.",
                outcome="reopened",
                source="lawyer_review",
                evidence_ref="attachment:reopen-approval-1",
                linked_matter_handling="reviewed",
            ),
        )
        assert reopened.is_active is True
        assert reopened.lifecycle_version == 2
        assert reopened_event.sequence == 2
        assert reopened_event.payload_json["reopen_without_child_resurrection"] is True

        coverage = session.scalar(
            select(IpDeadlineCoverage).where(IpDeadlineCoverage.docket_id == docket["id"])
        )
        obligation = session.scalar(
            select(IpRelatedRightObligation).where(
                IpRelatedRightObligation.docket_id == docket["id"]
            )
        )
        assert coverage is not None and coverage.coverage_status == "inactive_lifecycle"
        assert obligation is not None and obligation.status == "cancelled_lifecycle"
        persisted = session.get(IpDocketRecord, docket["id"])
        assert persisted is not None and persisted.status == "ready"

    reloaded = client.get(f"/api/ip/dockets/{docket['id']}", headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["lifecycle_version"] == 2
    assert reloaded.json()["deadline_coverages"][0]["coverage_status"] == ("inactive_lifecycle")
    assert reloaded.json()["related_right_obligations"][0]["status"] == ("cancelled_lifecycle")


@pytest.mark.parametrize("matter_linked", [False, True], ids=["standalone", "matter-linked"])
def test_lifecycle_neutralizes_every_uncovered_docket_deadline_before_reopen(
    client: TestClient,
    matter_linked: bool,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    suffix = "linked" if matter_linked else "standalone"
    assignee_response = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": f"Lifecycle Assignee {suffix}",
            "email": f"lifecycle-{suffix}@asterlegal.in",
            "password": "LifecycleMemberPass123!",
            "role": "member",
        },
    )
    assert assignee_response.status_code == 200, assignee_response.text
    assignee_id = str(assignee_response.json()["membership_id"])
    matter = _mk_matter(client, token, f"IP-LIFE-DIRECT-{suffix}") if matter_linked else None
    docket = _docket(
        client,
        headers,
        title=f"DIRECT DEADLINE {suffix.upper()}",
        matter_id=str(matter["id"]) if matter is not None else None,
    )
    if matter is not None:
        with get_session_factory()() as session:
            session.add_all(
                [
                    MatterAccessGrant(
                        company_id=str(bootstrap["company"]["id"]),
                        matter_id=str(matter["id"]),
                        membership_id=assignee_id,
                        reason="Exercise linked IP lifecycle assignment.",
                        granted_by_membership_id=str(bootstrap["membership"]["id"]),
                    ),
                    MatterAccessGrant(
                        company_id=str(bootstrap["company"]["id"]),
                        ip_docket_id=str(docket["id"]),
                        membership_id=assignee_id,
                        reason="Exercise linked IP lifecycle assignment.",
                        granted_by_membership_id=str(bootstrap["membership"]["id"]),
                    ),
                ]
            )
            session.commit()

    deadline_ids: list[str] = []
    for deadline_status in ("open", "missed"):
        created = client.post(
            "/api/ip/operational-deadlines",
            headers=headers,
            json={
                "docket_id": docket["id"],
                "source": "followup",
                "kind": "lifecycle_regression",
                "title": f"{deadline_status.title()} uncovered deadline",
                "due_on": str(date.today() + timedelta(days=14)),
                "assignee_membership_id": assignee_id,
            },
        )
        assert created.status_code == 201, created.text
        deadline_id = str(created.json()["id"])
        deadline_ids.append(deadline_id)
        if deadline_status == "missed":
            marked_missed = client.patch(
                f"/api/ip/operational-deadlines/{deadline_id}",
                headers=headers,
                json={"docket_id": docket["id"], "status": "missed"},
            )
            assert marked_missed.status_code == 200, marked_missed.text

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        with pytest.raises(HTTPException) as nonterminal_transition:
            transition_ip_docket_lifecycle(
                session,
                context=context,
                docket_id=docket["id"],
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=0,
                    to_status="ready",
                    effective_at=EFFECTIVE_AT,
                    reason="An active-to-active lifecycle write is not permitted.",
                    outcome="unchanged",
                    source="lawyer_review",
                    evidence_ref=f"attachment:{suffix}-invalid-active-transition",
                    linked_matter_handling="reviewed",
                ),
            )
        assert nonterminal_transition.value.status_code == 409
        session.rollback()

    with get_session_factory()() as session:
        unchanged_deadlines = list(
            session.scalars(
                select(MatterDeadline).where(MatterDeadline.id.in_(deadline_ids))
            )
        )
        assert {deadline.status for deadline in unchanged_deadlines} == {"open", "missed"}
        assert all(deadline.neutralized_at is None for deadline in unchanged_deadlines)

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        assert not list(
            session.scalars(
                select(IpDeadlineCoverage).where(
                    IpDeadlineCoverage.matter_deadline_id.in_(deadline_ids)
                )
            )
        )
        terminal, terminal_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=docket["id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=EFFECTIVE_AT,
                reason="All directly owned operational work must become terminal.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref=f"attachment:{suffix}-closure",
                linked_matter_handling="reviewed",
            ),
        )
        assert terminal.is_active is False
        assert terminal_event.resulting_lifecycle_version == 1
        assert terminal_event.payload_json["cancelled_shared_deadlines"] == 2
        terminal_event_id = terminal_event.id
        deadlines = list(
            session.scalars(
                select(MatterDeadline)
                .where(MatterDeadline.id.in_(deadline_ids))
                .order_by(MatterDeadline.id)
            )
        )
        assert len(deadlines) == 2
        for deadline in deadlines:
            assert deadline.matter_id is None
            assert deadline.ip_docket_id == docket["id"]
            assert deadline.status == "cancelled"
            assert deadline.completed_at is not None
            assert deadline.neutralized_by_ip_lifecycle_event_id == terminal_event_id
            assert deadline.neutralized_by_ip_lifecycle_version == 1
            assert deadline.neutralized_at is not None

    deactivated = client.patch(
        f"/api/companies/current/users/{assignee_id}",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["membership_active"] is False

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        reopened, reopened_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=docket["id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=1,
                to_status="ready",
                effective_at=EFFECTIVE_AT + timedelta(days=1),
                reason="Named lawyer approved a controlled reopen.",
                outcome="reopened",
                source="lawyer_review",
                evidence_ref=f"attachment:{suffix}-reopen",
                linked_matter_handling="reviewed",
            ),
        )
        assert reopened.is_active is True
        assert reopened.lifecycle_version == 2
        assert reopened_event.resulting_lifecycle_version == 2

    active_deadlines = client.get(
        "/api/ip/operational-deadlines",
        headers=headers,
        params={"docket_id": docket["id"]},
    )
    assert active_deadlines.status_code == 200, active_deadlines.text
    assert active_deadlines.json()["deadlines"] == []
    historical_deadlines = client.get(
        "/api/ip/operational-deadlines",
        headers=headers,
        params={"docket_id": docket["id"], "include_done": True},
    )
    assert historical_deadlines.status_code == 200, historical_deadlines.text
    assert {row["id"] for row in historical_deadlines.json()["deadlines"]} == set(deadline_ids)
    assert {row["status"] for row in historical_deadlines.json()["deadlines"]} == {"cancelled"}

    with get_session_factory()() as session:
        persisted_docket = session.get(IpDocketRecord, docket["id"])
        persisted_assignee = session.get(CompanyMembership, assignee_id)
        persisted_deadlines = list(
            session.scalars(select(MatterDeadline).where(MatterDeadline.id.in_(deadline_ids)))
        )
        assert persisted_docket is not None
        assert persisted_docket.status == "ready"
        assert persisted_docket.lifecycle_version == 2
        assert persisted_assignee is not None and persisted_assignee.is_active is False
        assert len(persisted_deadlines) == 2
        for deadline in persisted_deadlines:
            assert deadline.status == "cancelled"
            assert deadline.assignee_membership_id == assignee_id
            assert deadline.neutralized_by_ip_lifecycle_event_id == terminal_event_id
            assert deadline.neutralized_by_ip_lifecycle_version == 1


@pytest.mark.parametrize("matter_linked", [False, True], ids=["standalone", "matter-linked"])
def test_reopen_repairs_legacy_terminal_docket_with_uncovered_deadlines(
    client: TestClient,
    matter_linked: bool,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    suffix = "linked" if matter_linked else "standalone"
    assignee_response = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": f"Legacy Lifecycle Assignee {suffix}",
            "email": f"legacy-lifecycle-{suffix}@asterlegal.in",
            "password": "LegacyLifecycleMemberPass123!",
            "role": "member",
        },
    )
    assert assignee_response.status_code == 200, assignee_response.text
    assignee_id = str(assignee_response.json()["membership_id"])
    matter = _mk_matter(client, token, f"IP-LIFE-LEGACY-{suffix}") if matter_linked else None
    docket = _docket(
        client,
        headers,
        title=f"LEGACY DEADLINE {suffix.upper()}",
        matter_id=str(matter["id"]) if matter is not None else None,
    )

    with get_session_factory()() as session:
        docket_row = session.get(IpDocketRecord, docket["id"])
        assignee = session.get(CompanyMembership, assignee_id)
        assert docket_row is not None and assignee is not None
        assignee_user = session.get(User, assignee.user_id)
        assert assignee_user is not None
        docket_row.status = "closed"
        docket_row.is_active = False
        docket_row.lifecycle_version = 1
        docket_row.lifecycle_effective_at = EFFECTIVE_AT
        docket_row.lifecycle_reason = "Legacy terminal row imported before child repair."
        docket_row.lifecycle_outcome = "closed"
        docket_row.lifecycle_source = "migration"
        docket_row.lifecycle_evidence_ref = f"migration:{suffix}-legacy-terminal"
        assignee.is_active = False
        assignee_user.is_active = False
        legacy_deadlines = [
            MatterDeadline(
                company_id=docket_row.company_id,
                ip_docket_id=docket_row.id,
                source="followup",
                kind="lifecycle_regression",
                title=f"Legacy {deadline_status} uncovered deadline",
                due_on=date.today() + timedelta(days=7),
                status=deadline_status,
                assignee_membership_id=assignee_id,
                created_by_membership_id=str(bootstrap["membership"]["id"]),
            )
            for deadline_status in ("open", "missed")
        ]
        legacy_task = MatterTask(
            company_id=docket_row.company_id,
            ip_docket_id=docket_row.id,
            created_by_membership_id=str(bootstrap["membership"]["id"]),
            owner_membership_id=assignee_id,
            title="Legacy open IP task",
            status="todo",
        )
        legacy_hearing = MatterHearing(
            company_id=docket_row.company_id,
            ip_docket_id=docket_row.id,
            hearing_on=date.today() + timedelta(days=12),
            forum_name="IP India",
            purpose="Legacy show-cause hearing",
            responsible_membership_id=assignee_id,
            attendee_membership_ids_json=[assignee_id],
            reminder_policy_json={"recipient_membership_ids": [assignee_id]},
            status="scheduled",
        )
        session.add_all([*legacy_deadlines, legacy_task, legacy_hearing])
        session.flush()
        legacy_obligation = IpRelatedRightObligation(
            company_id=docket_row.company_id,
            docket_id=docket_row.id,
            obligation_type="response",
            title="Legacy open related-right obligation",
            due_on=date.today() + timedelta(days=8),
            owner_membership_id=assignee_id,
            matter_deadline_id=legacy_deadlines[0].id,
            status="open",
            evidence_reference=f"fixture:{suffix}-legacy-obligation",
        )
        legacy_reminder = HearingReminder(
            company_id=docket_row.company_id,
            ip_docket_id=docket_row.id,
            hearing_id=legacy_hearing.id,
            recipient_membership_id=assignee_id,
            recipient_email=f"legacy-lifecycle-{suffix}@asterlegal.in",
            channel="email",
            scheduled_for=datetime.now(UTC) + timedelta(days=11),
            status="queued",
        )
        legacy_intent = NotificationDeliveryIntent(
            company_id=docket_row.company_id,
            recipient_membership_id=assignee_id,
            ip_docket_id=docket_row.id,
            channel="email",
            event_type="hearing_reminder",
            source_type="matter_hearing",
            source_id=legacy_hearing.id,
            idempotency_key=f"legacy-lifecycle-{suffix}-hearing",
            status="queued",
        )
        connection = UserCalendarConnection(
            company_id=docket_row.company_id,
            membership_id=assignee_id,
            provider="outlook",
            provider_account_id=f"legacy-lifecycle-{suffix}-calendar",
            status="connected",
        )
        session.add_all(
            [legacy_obligation, legacy_reminder, legacy_intent, connection]
        )
        session.flush()
        session.add_all(
            [
                HearingReminderDeliveryIntent(
                    hearing_reminder_id=legacy_reminder.id,
                    intent_id=legacy_intent.id,
                    is_primary=True,
                ),
                CalendarEventSync(
                    company_id=docket_row.company_id,
                    calendar_connection_id=connection.id,
                    source_type="matter_hearing",
                    source_id=legacy_hearing.id,
                    provider_event_id=f"legacy-{suffix}-hearing-event",
                    sync_status="synced",
                ),
            ]
        )
        session.commit()
        deadline_ids = [deadline.id for deadline in legacy_deadlines]
        task_id = legacy_task.id
        hearing_id = legacy_hearing.id
        reminder_id = legacy_reminder.id
        intent_id = legacy_intent.id
        obligation_id = legacy_obligation.id

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        reopened, reopened_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=docket["id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=1,
                to_status="ready",
                effective_at=EFFECTIVE_AT + timedelta(days=1),
                reason="Repair legacy children before the controlled reopen.",
                outcome="reopened",
                source="lawyer_review",
                evidence_ref=f"attachment:{suffix}-legacy-reopen",
                linked_matter_handling="reviewed",
            ),
        )
        assert reopened.is_active is True
        assert reopened.lifecycle_version == 2
        assert reopened_event.resulting_lifecycle_version == 2
        assert reopened_event.payload_json["cancelled_shared_deadlines"] == 2
        assert reopened_event.payload_json["cancelled_shared_tasks"] == 1
        assert reopened_event.payload_json["cancelled_shared_hearings"] == 1
        assert reopened_event.payload_json["cancelled_hearing_reminders"] == 1
        assert reopened_event.payload_json["neutralized_obligations"] == 1
        reopened_event_id = reopened_event.id

    active_deadlines = client.get(
        "/api/ip/operational-deadlines",
        headers=headers,
        params={"docket_id": docket["id"]},
    )
    assert active_deadlines.status_code == 200, active_deadlines.text
    assert active_deadlines.json()["deadlines"] == []

    with get_session_factory()() as session:
        persisted_docket = session.get(IpDocketRecord, docket["id"])
        persisted_assignee = session.get(CompanyMembership, assignee_id)
        persisted_deadlines = list(
            session.scalars(select(MatterDeadline).where(MatterDeadline.id.in_(deadline_ids)))
        )
        persisted_task = session.get(MatterTask, task_id)
        persisted_hearing = session.get(MatterHearing, hearing_id)
        persisted_reminder = session.get(HearingReminder, reminder_id)
        persisted_intent = session.get(NotificationDeliveryIntent, intent_id)
        persisted_obligation = session.get(IpRelatedRightObligation, obligation_id)
        assert persisted_docket is not None
        assert persisted_docket.status == "ready"
        assert persisted_docket.lifecycle_version == 2
        assert persisted_assignee is not None and persisted_assignee.is_active is False
        assert len(persisted_deadlines) == 2
        for deadline in persisted_deadlines:
            assert deadline.status == "cancelled"
            assert deadline.assignee_membership_id == assignee_id
            assert deadline.completed_at is not None
            assert deadline.neutralized_by_ip_lifecycle_event_id == reopened_event_id
            assert deadline.neutralized_by_ip_lifecycle_version == 2
            assert deadline.neutralized_at is not None
        assert persisted_task is not None and persisted_task.status == "cancelled"
        assert persisted_task.neutralized_by_ip_lifecycle_event_id == reopened_event_id
        assert persisted_hearing is not None and persisted_hearing.status == "cancelled"
        assert persisted_hearing.neutralized_by_ip_lifecycle_event_id == reopened_event_id
        assert persisted_reminder is not None and persisted_reminder.status == "cancelled"
        assert persisted_intent is not None and persisted_intent.status == "cancelled"
        assert persisted_obligation is not None
        assert persisted_obligation.status == "cancelled_lifecycle"


def test_terminal_docket_neutralizes_live_work_and_outbound_state_before_reopen(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.services import calendar_sync
    from tests.test_google_calendar_sync import StubGoogleCalendarProvider
    from tests.test_legalworkspace_calendar_sync import StubOutlookProvider

    google_provider = StubGoogleCalendarProvider()
    outlook_provider = StubOutlookProvider()
    monkeypatch.setattr(
        calendar_sync,
        "_google_calendar_provider_override",
        google_provider,
    )
    monkeypatch.setattr(
        calendar_sync,
        "_outlook_provider_override",
        outlook_provider,
    )
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()

    with factory() as session:
        task = MatterTask(
            company_id=env["company_id"],
            ip_docket_id=env["docket_id"],
            created_by_membership_id=env["owner_id"],
            owner_membership_id=env["unrelated_id"],
            title="Prepare direct IP filing packet",
            status="in_progress",
        )
        hearing = MatterHearing(
            company_id=env["company_id"],
            ip_docket_id=env["docket_id"],
            hearing_on=date.today() + timedelta(days=21),
            forum_name="IP India",
            purpose="Show-cause hearing",
            responsible_membership_id=env["unrelated_id"],
            attendee_membership_ids_json=[env["unrelated_id"]],
            reminder_policy_json={
                "recipient_membership_ids": [env["unrelated_id"]],
                "escalation_membership_id": env["unrelated_id"],
            },
            status="scheduled",
        )
        session.add_all([task, hearing])
        session.flush()
        reminder = HearingReminder(
            company_id=env["company_id"],
            ip_docket_id=env["docket_id"],
            hearing_id=hearing.id,
            recipient_membership_id=env["unrelated_id"],
            recipient_email="projection-unrelated@asterlegal.in",
            channel="email",
            scheduled_for=datetime.now(UTC) + timedelta(days=20),
            status="queued",
        )
        hearing_intent = NotificationDeliveryIntent(
            company_id=env["company_id"],
            recipient_membership_id=env["unrelated_id"],
            ip_docket_id=env["docket_id"],
            channel="email",
            event_type="hearing_reminder",
            source_type="matter_hearing",
            source_id=hearing.id,
            idempotency_key="ip-lifecycle-hearing-reminder",
            status="queued",
        )
        connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["unrelated_id"],
            provider="outlook",
            provider_account_id="ip-lifecycle-member-calendar",
            status="connected",
        )
        expired_connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider="google_calendar",
            provider_account_id="ip-lifecycle-expired-calendar",
            status="connected",
            encrypted_token_ref="ip-lifecycle-google-reconciliation-credential",
        )
        typed_connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider="outlook",
            provider_account_id="ip-lifecycle-typed-calendar",
            status="connected",
            encrypted_token_ref="ip-lifecycle-outlook-reconciliation-credential",
        )
        session.add_all(
            [
                reminder,
                hearing_intent,
                connection,
                expired_connection,
                typed_connection,
            ]
        )
        session.flush()
        session.add(
            HearingReminderDeliveryIntent(
                hearing_reminder_id=reminder.id,
                intent_id=hearing_intent.id,
                is_primary=True,
            )
        )
        syncs = [
            CalendarEventSync(
                company_id=env["company_id"],
                calendar_connection_id=connection.id,
                source_type=source_type,
                source_id=source_id,
                provider_event_id=f"provider-{source_type}",
                sync_status="synced",
            )
            for source_type, source_id in (
                ("matter_task", task.id),
                ("matter_hearing", hearing.id),
            )
        ]
        in_flight_deadline_sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=connection.id,
            source_type="matter_deadline",
            source_id=env["matter_deadline_id"],
            provider_event_id=None,
            sync_status="pending",
            dead_letter_reason="provider_upsert_claim:in-flight-lifecycle-create",
            next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        expired_deadline_sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=expired_connection.id,
            source_type="matter_deadline",
            source_id=env["matter_deadline_id"],
            provider_event_id=None,
            sync_status="pending",
            dead_letter_reason="provider_upsert_claim:expired-lifecycle-create",
            next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        typed_deadline_sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=typed_connection.id,
            source_type="matter_deadline",
            source_id=env["matter_deadline_id"],
            provider_event_id=None,
            sync_status="dead_letter",
            dead_letter_reason=CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
            last_error="Calendar provider upsert outcome is unknown.",
            attempts=7,
        )
        syncs.extend(
            [
                in_flight_deadline_sync,
                expired_deadline_sync,
                typed_deadline_sync,
            ]
        )
        session.add_all(syncs)
        session.commit()
        task_id = task.id
        hearing_id = hearing.id
        reminder_id = reminder.id
        hearing_intent_id = hearing_intent.id
        sync_ids = {row.id for row in syncs}
        in_flight_sync_id = in_flight_deadline_sync.id
        expired_sync_id = expired_deadline_sync.id
        typed_sync_id = typed_deadline_sync.id
        reconciliation_connection_ids = {
            expired_connection.id,
            typed_connection.id,
        }

    with factory() as session:
        company = session.get(Company, env["company_id"])
        owner = session.get(CompanyMembership, env["owner_id"])
        assert company is not None and owner is not None and owner.user is not None
        context = SessionContext(company=company, membership=owner, user=owner.user)
        terminal, terminal_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=env["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=EFFECTIVE_AT,
                reason="Close every live IP child and outbound projection.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref="attachment:complete-ip-closure",
                linked_matter_handling="reviewed",
            ),
        )
        assert terminal.is_active is False
        assert terminal_event.payload_json["cancelled_shared_tasks"] == 1
        assert terminal_event.payload_json["cancelled_shared_hearings"] == 1
        assert terminal_event.payload_json["cancelled_hearing_reminders"] == 1
        assert terminal_event.payload_json["neutralized_responsibility_assignments"] == 2
        assert terminal_event.payload_json["blocked_unknown_calendar_syncs"] == 3
        terminal_event_id = terminal_event.id

    for sync_id in (expired_sync_id, typed_sync_id):
        operation = client.get(
            f"/api/admin/provider-operations/jobs/calendar_sync:{sync_id}",
            headers=auth_headers(env["owner_token"]),
        )
        assert operation.status_code == 200, operation.text
        assert operation.json()["manual_reconciliation_required"] is True
        assert operation.json()["replay_available"] is False

    owner_login = client.post(
        "/api/auth/login",
        json={
            "email": "owner@asterlegal.in",
            "password": "FoundersPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert owner_login.status_code == 200, owner_login.text
    client.cookies.clear()
    deactivated = client.patch(
        f"/api/companies/current/users/{env['unrelated_id']}",
        headers=auth_headers(str(owner_login.json()["access_token"])),
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["membership_active"] is False

    with factory() as session:
        company = session.get(Company, env["company_id"])
        owner = session.get(CompanyMembership, env["owner_id"])
        assert company is not None and owner is not None and owner.user is not None
        context = SessionContext(company=company, membership=owner, user=owner.user)
        reopened, reopened_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=env["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=1,
                to_status="ready",
                effective_at=EFFECTIVE_AT + timedelta(days=1),
                reason="Reopen without reviving terminal children.",
                outcome="reopened",
                source="lawyer_review",
                evidence_ref="attachment:controlled-ip-reopen",
                linked_matter_handling="reviewed",
            ),
        )
        assert reopened.is_active is True
        assert reopened_event.payload_json["cancelled_shared_tasks"] == 0
        assert reopened_event.payload_json["cancelled_shared_hearings"] == 0

    with factory() as session:
        task = session.get(MatterTask, task_id)
        hearing = session.get(MatterHearing, hearing_id)
        reminder = session.get(HearingReminder, reminder_id)
        hearing_intent = session.get(NotificationDeliveryIntent, hearing_intent_id)
        deadline = session.get(IpDeadline, env["ip_deadline_id"])
        projection = session.get(MatterDeadline, env["matter_deadline_id"])
        assignments = list(
            session.scalars(
                select(IpResponsibilityAssignment).where(
                    IpResponsibilityAssignment.deadline_id == env["ip_deadline_id"]
                )
            )
        )
        syncs = list(
            session.scalars(select(CalendarEventSync).where(CalendarEventSync.id.in_(sync_ids)))
        )
        assert task is not None and task.status == "cancelled"
        assert task.neutralized_by_ip_lifecycle_event_id == terminal_event_id
        assert hearing is not None and hearing.status == "cancelled"
        assert hearing.neutralized_by_ip_lifecycle_event_id == terminal_event_id
        assert reminder is not None and reminder.status == "cancelled"
        assert reminder.neutralized_by_ip_lifecycle_event_id == terminal_event_id
        assert hearing_intent is not None and hearing_intent.status == "cancelled"
        assert deadline is not None and deadline.state == "cancelled"
        assert projection is not None and projection.status == "cancelled"
        assert assignments and all(row.effective_until is not None for row in assignments)
        assert len(syncs) == 5
        assert {row.sync_status for row in syncs} == {
            "delete_pending",
            "pending",
            "dead_letter",
        }
        preserved_claim = session.get(CalendarEventSync, in_flight_sync_id)
        assert preserved_claim is not None
        assert preserved_claim.provider_event_id is None
        assert (
            preserved_claim.dead_letter_reason
            == "provider_upsert_claim:in-flight-lifecycle-create"
        )
        assert preserved_claim.neutralized_ip_docket_id is None
        expired_claim = session.get(CalendarEventSync, expired_sync_id)
        typed_unknown = session.get(CalendarEventSync, typed_sync_id)
        assert expired_claim is not None and typed_unknown is not None
        assert expired_claim.sync_status == "dead_letter"
        assert expired_claim.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        assert expired_claim.next_attempt_at is None
        assert expired_claim.durable_last_attempt_at is not None
        assert typed_unknown.sync_status == "dead_letter"
        assert typed_unknown.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        assert typed_unknown.last_error == "Calendar provider upsert outcome is unknown."
        assert typed_unknown.attempts == 7
        assert all(
            row.neutralized_ip_docket_id is None
            for row in (expired_claim, typed_unknown)
        )
        for connection_id in reconciliation_connection_ids:
            connection = session.get(UserCalendarConnection, connection_id)
            assert connection is not None and connection.encrypted_token_ref is not None
        assert all(
            row.neutralized_ip_docket_id == env["docket_id"]
            for row in syncs
            if row.id not in {in_flight_sync_id, expired_sync_id, typed_sync_id}
        )
    assert google_provider.calls == [] and google_provider.delete_calls == []
    assert outlook_provider.calls == []


def test_lifecycle_preserves_shared_deadline_and_reconciles_sibling_calendar_roles(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.services import calendar_sync
    from tests.test_google_calendar_sync import StubGoogleCalendarProvider
    from tests.test_legalworkspace_calendar_sync import StubOutlookProvider

    google_provider = StubGoogleCalendarProvider()
    outlook_provider = StubOutlookProvider()
    monkeypatch.setattr(
        calendar_sync,
        "_google_calendar_provider_override",
        google_provider,
    )
    monkeypatch.setattr(
        calendar_sync,
        "_outlook_provider_override",
        outlook_provider,
    )
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    with factory() as session:
        sibling = IpDocketRecord(
            company_id=env["company_id"],
            matter_id=env["matter_id"],
            record_type="trademark",
            title="Sibling live IP docket",
            status="ready",
            is_active=True,
            created_by_membership_id=env["owner_id"],
        )
        session.add(sibling)
        session.flush()
        sibling_coverage = IpDeadlineCoverage(
            company_id=env["company_id"],
            docket_id=sibling.id,
            matter_deadline_id=env["matter_deadline_id"],
            responsible_membership_id=env["replacement_id"],
            backup_membership_id=env["unrelated_id"],
            coverage_status="accepted",
            calendar_projection_status="projected",
        )
        old_connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["owner_id"],
            provider="outlook",
            provider_account_id="closing-docket-calendar",
            status="connected",
        )
        sibling_connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["replacement_id"],
            provider="outlook",
            provider_account_id="sibling-docket-calendar",
            status="connected",
            encrypted_token_ref="sibling-outlook-reconciliation-credential",
        )
        revivable_connection = UserCalendarConnection(
            company_id=env["company_id"],
            membership_id=env["unrelated_id"],
            provider="google_calendar",
            provider_account_id="sibling-docket-revivable-calendar",
            status="connected",
        )
        session.add_all(
            [
                sibling_coverage,
                old_connection,
                sibling_connection,
                revivable_connection,
            ]
        )
        session.flush()
        old_sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=old_connection.id,
            source_type="matter_deadline",
            source_id=env["matter_deadline_id"],
            provider_event_id="closing-docket-provider-event",
            sync_status="synced",
        )
        sibling_sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=sibling_connection.id,
            source_type="matter_deadline",
            source_id=env["matter_deadline_id"],
            sync_status="pending",
            dead_letter_reason="provider_upsert_claim:expired-sibling-create",
            next_attempt_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        revivable_sync = CalendarEventSync(
            company_id=env["company_id"],
            calendar_connection_id=revivable_connection.id,
            source_type="matter_deadline",
            source_id=env["matter_deadline_id"],
            sync_status="deleted",
        )
        session.add_all([old_sync, sibling_sync, revivable_sync])
        session.commit()
        sibling_coverage_id = sibling_coverage.id
        old_sync_id = old_sync.id
        sibling_sync_id = sibling_sync.id
        revivable_sync_id = revivable_sync.id
        sibling_connection_id = sibling_connection.id

    with factory() as session:
        company = session.get(Company, env["company_id"])
        owner = session.get(CompanyMembership, env["owner_id"])
        assert company is not None and owner is not None and owner.user is not None
        context = SessionContext(company=company, membership=owner, user=owner.user)
        _, terminal_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=env["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=EFFECTIVE_AT,
                reason="Close one docket without damaging a live sibling.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref="attachment:sibling-safe-close",
                linked_matter_handling="reviewed",
            ),
        )
        assert terminal_event.payload_json["blocked_unknown_calendar_syncs"] == 1

    operation = client.get(
        f"/api/admin/provider-operations/jobs/calendar_sync:{sibling_sync_id}",
        headers=auth_headers(env["owner_token"]),
    )
    assert operation.status_code == 200, operation.text
    assert operation.json()["manual_reconciliation_required"] is True

    with factory() as session:
        projection = session.get(MatterDeadline, env["matter_deadline_id"])
        sibling_coverage = session.get(IpDeadlineCoverage, sibling_coverage_id)
        old_sync = session.get(CalendarEventSync, old_sync_id)
        sibling_sync = session.get(CalendarEventSync, sibling_sync_id)
        revivable_sync = session.get(CalendarEventSync, revivable_sync_id)
        assert projection is not None and projection.status == "open"
        assert sibling_coverage is not None
        assert sibling_coverage.coverage_status == "accepted"
        assert sibling_coverage.calendar_projection_status == "pending"
        assert old_sync is not None and old_sync.sync_status == "delete_pending"
        assert old_sync.neutralized_by_ip_lifecycle_event_id is None
        assert sibling_sync is not None and sibling_sync.sync_status == "dead_letter"
        assert sibling_sync.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        assert sibling_sync.next_attempt_at is None
        assert sibling_sync.neutralized_by_ip_lifecycle_event_id is None
        assert revivable_sync is not None and revivable_sync.sync_status == "pending"
        sibling_connection = session.get(UserCalendarConnection, sibling_connection_id)
        assert sibling_connection is not None
        assert sibling_connection.encrypted_token_ref is not None

    with factory() as session:
        company = session.get(Company, env["company_id"])
        owner = session.get(CompanyMembership, env["owner_id"])
        assert company is not None and owner is not None and owner.user is not None
        context = SessionContext(company=company, membership=owner, user=owner.user)
        transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=env["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=1,
                to_status="ready",
                effective_at=EFFECTIVE_AT + timedelta(days=1),
                reason="Reopen while preserving the sibling-owned deadline.",
                outcome="reopened",
                source="lawyer_review",
                evidence_ref="attachment:sibling-safe-reopen",
                linked_matter_handling="reviewed",
            ),
        )

    with factory() as session:
        projection = session.get(MatterDeadline, env["matter_deadline_id"])
        old_sync = session.get(CalendarEventSync, old_sync_id)
        sibling_sync = session.get(CalendarEventSync, sibling_sync_id)
        revivable_sync = session.get(CalendarEventSync, revivable_sync_id)
        assert projection is not None and projection.status == "open"
        assert old_sync is not None and old_sync.sync_status == "delete_pending"
        assert old_sync.neutralized_by_ip_lifecycle_event_id is None
        assert sibling_sync is not None and sibling_sync.sync_status == "dead_letter"
        assert sibling_sync.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        assert sibling_sync.neutralized_by_ip_lifecycle_event_id is None
        assert revivable_sync is not None and revivable_sync.sync_status == "pending"
    assert google_provider.calls == [] and google_provider.delete_calls == []
    assert outlook_provider.calls == []


@pytest.mark.parametrize(
    ("role_attribute", "member_key"),
    (
        ("assignee_membership_id", "unrelated_id"),
        ("responsible_lawyer_membership_id", "replacement_id"),
    ),
)
def test_reopen_rejects_inactive_linked_matter_roles(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    role_attribute: str,
    member_key: str,
) -> None:
    env = _confirmed_deadline_environment(client, monkeypatch)
    factory = get_session_factory()
    target_id = env[member_key]

    with factory() as session:
        matter = session.get(Matter, env["matter_id"])
        assert matter is not None
        setattr(matter, role_attribute, target_id)
        session.commit()

    with factory() as session:
        company = session.get(Company, env["company_id"])
        owner = session.get(CompanyMembership, env["owner_id"])
        assert company is not None and owner is not None and owner.user is not None
        context = SessionContext(company=company, membership=owner, user=owner.user)
        terminal, _event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=env["docket_id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=EFFECTIVE_AT,
                reason="Close the docket before deactivating an inherited Matter role.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref=f"attachment:close-before-{role_attribute}-deactivation",
                linked_matter_handling="reviewed",
            ),
        )
        assert terminal.is_active is False

    client.cookies.clear()
    deactivated = client.patch(
        f"/api/companies/current/users/{target_id}",
        headers=auth_headers(env["owner_token"]),
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["membership_active"] is False

    with factory() as session:
        company = session.get(Company, env["company_id"])
        owner = session.get(CompanyMembership, env["owner_id"])
        assert company is not None and owner is not None and owner.user is not None
        context = SessionContext(company=company, membership=owner, user=owner.user)
        with pytest.raises(HTTPException) as exc_info:
            transition_ip_docket_lifecycle(
                session,
                context=context,
                docket_id=env["docket_id"],
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=1,
                    to_status="ready",
                    effective_at=EFFECTIVE_AT + timedelta(days=1),
                    reason="Reopen must not revive an inactive linked Matter role.",
                    outcome="reopened",
                    source="lawyer_review",
                    evidence_ref=f"attachment:blocked-{role_attribute}-reopen",
                    linked_matter_handling="reviewed",
                ),
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == {
            "code": "ip_docket_reopen_matter_role_unavailable",
            "role": (
                "assignee"
                if role_attribute == "assignee_membership_id"
                else "responsible_lawyer"
            ),
            "membership_id": target_id,
        }

    with factory() as session:
        persisted = session.get(IpDocketRecord, env["docket_id"])
        assert persisted is not None
        assert persisted.status == "closed"
        assert persisted.is_active is False
        assert persisted.lifecycle_version == 1
