from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarEventSync,
    CalendarEventSyncStatus,
    EthicalWall,
    IpDeadline,
    IpDeadlineCoverage,
    IpResponsibilityAssignment,
    MatterDeadline,
    NotificationDeliveryIntent,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_deadlines import (
    IpDeadlineCalculationRequest,
    IpDeadlineConfirmRequest,
    IpDeadlineRuleDefinition,
    IpRuleVersionProposalRequest,
    LegalCalendarSnapshot,
    LegalCalendarVersionProposalRequest,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars


@pytest.fixture(autouse=True)
def _enable_rule_governance_for_existing_workflow_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the pre-A0 behavior only through an explicit enabled state."""

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _member(
    client: TestClient,
    owner_token: str,
    *,
    name: str,
    email: str,
    company_slug: str = "aster-legal",
) -> tuple[str, str]:
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": name,
            "email": email,
            "password": "DeadlineAdmin123!",
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "DeadlineAdmin123!",
            "company_slug": company_slug,
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return str(created.json()["membership_id"]), str(login.json()["access_token"])


def _docket_for_matter(
    client: TestClient,
    headers: dict[str, str],
    *,
    matter_id: str,
) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Deadline Workflow Mark",
            "matter_id": matter_id,
            "restricted": False,
            "particulars": _particulars("DEADLINE WORKFLOW MARK"),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _calendar_payload() -> dict:
    return {
        "key": "ip-india-2026",
        "name": "IP India official working calendar 2026",
        "jurisdiction": "IN",
        "office": "IP India",
        "timezone": "Asia/Kolkata",
        "weekend_days": [5, 6],
        "holidays": ["2026-08-17"],
        "exceptional_working_days": [],
        "source_priority": ["official_gazette", "official_office_notice"],
        "source_reference": "https://official.example/ip-india/calendar/2026",
        "source_hash": "a" * 64,
        "effective_from": "2026-01-01",
        "effective_until": "2026-12-31",
    }


def _rule_payload() -> dict:
    calculation = {
        "deadline_kind": "legal_deadline",
        "trigger_kind": "examination_report_received",
        "base_date": "2026-08-14",
        "base_date_certainty": "certain",
        "duration_value": 1,
        "duration_unit": "days",
        "calendar_method": "business_days",
        "direction": "after",
        "include_base_date": False,
        "next_working_day": True,
        "extension_days": 0,
        "rule_version_id": "fixture-rule-version",
        "rule_citation": "Trade Marks Rules, verified fixture citation",
        "source_version": "fixture-source-2026-08-09",
        "engine_version": "caseops-ip-deadline-v1",
        "calendar": {
            "calendar_version_id": "fixture-calendar-version",
            "timezone": "Asia/Kolkata",
            "weekend_days": [5, 6],
            "holidays": ["2026-08-17"],
            "exceptional_working_days": [],
            "source_reference": "https://official.example/ip-india/calendar/2026",
            "source_hash": "a" * 64,
        },
    }
    return {
        "key": "in-tm-examination-response-v1",
        "rule_kind": "deadline",
        "jurisdiction": "IN",
        "office": "IP India",
        "right_kind": "trademark",
        "proceeding_kind": "application",
        "role": "applicant",
        "stage": "examination",
        "source_record_id": "tm-rules-2017-amended-2026-08-09",
        "source_hash": "b" * 64,
        "source_reference": "https://official.example/ip-india/tm-rules",
        "effective_from": "2026-01-01",
        "effective_until": None,
        "engine_compatibility": "caseops-ip-deadline-v1",
        "definition": {
            "deadline_kind": "legal_deadline",
            "trigger_kind": "examination_report_received",
            "duration_value": 1,
            "duration_unit": "days",
            "calendar_method": "business_days",
            "direction": "after",
            "include_base_date": False,
            "next_working_day": True,
            "extension_days": 0,
            "rule_citation": "Trade Marks Rules, verified fixture citation",
        },
        "fixtures": [
            {
                "id": "weekend-and-holiday-boundary",
                "fixture_kind": "boundary",
                "calculation": calculation,
                "expected_state": "candidate",
                "expected_result_on": "2026-08-18",
                "evidence_reference": "fixture:official-calendar-2026",
            }
        ],
    }


def _responsibilities(primary_id: str, backup_id: str) -> list[dict]:
    return [
        {
            "membership_id": primary_id,
            "role": "primary",
            "accepted": True,
            "escalation_policy": {"after_hours": 24},
        },
        {
            "membership_id": backup_id,
            "role": "backup",
            "accepted": True,
            "escalation_policy": {"after_hours": 24},
        },
    ]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"weekend_days": [-1, 6]}, "weekend days must be integers"),
        ({"weekend_days": [5, 5]}, "weekend days cannot contain duplicates"),
        ({"timezone": "Invalid/Deadline-Timezone"}, "valid IANA timezone"),
    ],
)
def test_legal_calendar_snapshot_rejects_unsafe_calendar_inputs(
    overrides: dict,
    message: str,
) -> None:
    payload = _rule_payload()["fixtures"][0]["calculation"]["calendar"]
    payload.update(overrides)

    with pytest.raises(ValidationError, match=message):
        LegalCalendarSnapshot.model_validate(payload)


def test_deadline_schema_validators_reject_inconsistent_legal_inputs() -> None:
    calculation = _rule_payload()["fixtures"][0]["calculation"]
    calculation["duration_unit"] = "months"
    with pytest.raises(ValidationError, match="business_days calculations require days"):
        IpDeadlineCalculationRequest.model_validate(calculation)

    definition = _rule_payload()["definition"]
    definition["duration_unit"] = "years"
    with pytest.raises(ValidationError, match="business_days rules require days"):
        IpDeadlineRuleDefinition.model_validate(definition)

    invalid_dates = _rule_payload()
    invalid_dates["effective_from"] = "2026-08-02"
    invalid_dates["effective_until"] = "2026-08-01"
    with pytest.raises(ValidationError, match="effective_until cannot precede"):
        IpRuleVersionProposalRequest.model_validate(invalid_dates)

    missing_calculation = _rule_payload()
    missing_calculation["fixtures"][0]["calculation"] = None
    with pytest.raises(ValidationError, match="deterministic calculations"):
        IpRuleVersionProposalRequest.model_validate(missing_calculation)

    invalid_calendar_dates = _calendar_payload()
    invalid_calendar_dates["effective_from"] = "2026-08-02"
    invalid_calendar_dates["effective_until"] = "2026-08-01"
    with pytest.raises(ValidationError, match="effective_until cannot precede"):
        LegalCalendarVersionProposalRequest.model_validate(invalid_calendar_dates)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"corrected_result_on": "2026-08-18"},
            "corrected confirmation requires reason and evidence",
        ),
        ({"reminder_offsets_days": [7, 7]}, "reminder offsets cannot contain duplicates"),
        ({"reminder_offsets_days": [3651]}, "reminder offsets must be between"),
    ],
)
def test_deadline_confirmation_rejects_unsafe_correction_and_reminders(
    overrides: dict,
    message: str,
) -> None:
    payload = {
        "expected_version": 1,
        "responsibilities": [
            {"membership_id": "fixture-primary", "role": "primary", "accepted": True}
        ],
        **overrides,
    }

    with pytest.raises(ValidationError, match=message):
        IpDeadlineConfirmRequest.model_validate(payload)


def test_all_five_deadline_writers_remain_operable_with_governance_flag_off(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_id = str(bootstrap["membership"]["id"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client,
        owner_token,
        name="Deadline Legal Approver",
        email="deadline-legal@asterlegal.in",
    )
    reviewer_id, _reviewer_token = _member(
        client,
        owner_token,
        name="Deadline Fixture Reviewer",
        email="deadline-reviewer@asterlegal.in",
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-DL-023B")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])

    calendar_proposal = client.post(
        "/api/ip/working-calendars",
        headers=owner_headers,
        json=_calendar_payload(),
    )
    assert calendar_proposal.status_code == 201, calendar_proposal.text
    calendar = calendar_proposal.json()
    self_approval = client.post(
        f"/api/ip/working-calendars/{calendar['id']}/activate",
        headers=owner_headers,
        json={"reason": "Reviewed official calendar source and conflicts."},
    )
    assert self_approval.status_code == 409
    activated_calendar = client.post(
        f"/api/ip/working-calendars/{calendar['id']}/activate",
        headers=legal_headers,
        json={"reason": "Reviewed official calendar source and conflicts."},
    )
    assert activated_calendar.status_code == 200, activated_calendar.text
    assert activated_calendar.json()["status"] == "active"

    rule_proposal = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=_rule_payload(),
    )
    assert rule_proposal.status_code == 201, rule_proposal.text
    rule = rule_proposal.json()
    self_review = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/activate",
        headers=legal_headers,
        json={"reviewer_membership_id": legal_id},
    )
    assert self_review.status_code == 409
    activated_rule = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/activate",
        headers=legal_headers,
        json={
            "reviewer_membership_id": reviewer_id,
            "select_for_company": True,
            "auto_confirm_eligible": False,
        },
    )
    assert activated_rule.status_code == 200, activated_rule.text
    assert activated_rule.json()["status"] == "active"
    assert activated_rule.json()["fixtures_passed_at"] is not None

    # A0 drains only governance ownership. Already selected immutable rules
    # must continue to support proposal, confirmation, recalculation,
    # override, and completion while the governance flag is false.
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()
    assert get_settings().ip_rule_governance_enabled is False

    proposal = client.post(
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
    assert proposal.status_code == 201, proposal.text
    deadline = proposal.json()
    assert deadline["state"] == "candidate"
    assert deadline["result_on"] == "2026-08-18"
    assert [step["reason"] for step in deadline["calculation_trace"] if "reason" in step] == [
        "weekend",
        "weekend",
        "holiday",
    ]

    noncritical_proposal = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Noncritical deadline still needs an accepted primary",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": False,
        },
    )
    assert noncritical_proposal.status_code == 201, noncritical_proposal.text
    noncritical = noncritical_proposal.json()
    unaccepted_primary = client.post(
        f"/api/ip/deadlines/{noncritical['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": noncritical["version"],
            "responsibilities": [
                {
                    "membership_id": owner_id,
                    "role": "primary",
                    "accepted": False,
                }
            ],
        },
    )
    assert unaccepted_primary.status_code == 409, unaccepted_primary.text
    assert (
        unaccepted_primary.json()["code"]
        == "ip_deadline_primary_acceptance_required"
    )
    with get_session_factory()() as session:
        rejected_deadline = session.get(IpDeadline, noncritical["id"])
        assignments = list(
            session.scalars(
                select(IpResponsibilityAssignment).where(
                    IpResponsibilityAssignment.deadline_id == noncritical["id"]
                )
            ).all()
        )
        assert rejected_deadline is not None
        assert rejected_deadline.state == "candidate"
        assert rejected_deadline.matter_deadline_id is None
        assert assignments == []

    incomplete_coverage = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(owner_id, reviewer_id)[:1],
        },
    )
    assert incomplete_coverage.status_code == 409
    collapsed_coverage = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(owner_id, owner_id),
        },
    )
    assert collapsed_coverage.status_code == 409, collapsed_coverage.text
    assert (
        collapsed_coverage.json()["code"]
        == "ip_coverage_distinct_backup_required"
    )
    stale = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": 99,
            "responsibilities": _responsibilities(owner_id, reviewer_id),
        },
    )
    assert stale.status_code == 409

    with get_session_factory()() as session:
        wall = EthicalWall(
            company_id=matter["company_id"],
            ip_docket_id=docket["id"],
            excluded_membership_id=reviewer_id,
            reason="Responsibility assignee cannot access the IP record.",
            created_by_membership_id=owner_id,
        )
        session.add(wall)
        session.commit()
        wall_id = wall.id
    blocked_by_ip_wall = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(owner_id, reviewer_id),
        },
    )
    assert blocked_by_ip_wall.status_code == 409, blocked_by_ip_wall.text
    assert "stable Matter and IP-record access" in blocked_by_ip_wall.text
    with get_session_factory()() as session:
        wall = session.get(EthicalWall, wall_id)
        assert wall is not None
        session.delete(wall)
        session.add_all(
            [
                UserCalendarConnection(
                    company_id=matter["company_id"],
                    membership_id=owner_id,
                    provider="outlook",
                    status="connected",
                    encrypted_token_ref="workflow-owner-calendar",
                ),
                UserCalendarConnection(
                    company_id=matter["company_id"],
                    membership_id=reviewer_id,
                    provider="google_calendar",
                    status="connected",
                    encrypted_token_ref="workflow-reviewer-calendar",
                ),
            ]
        )
        session.commit()

    confirmed_response = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(owner_id, reviewer_id),
            "internal_target_on": "2026-08-16",
            "reminder_offsets_days": [7, 1, 0],
        },
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    confirmed = confirmed_response.json()
    assert confirmed["state"] == "confirmed"
    assert confirmed["matter_deadline_id"] is not None
    assert len(confirmed["responsibilities"]) == 2
    calendar_view = client.get(
        "/api/calendar/events",
        headers=owner_headers,
        params={"from": "2026-08-16", "to": "2026-08-18"},
    )
    assert calendar_view.status_code == 200, calendar_view.text
    calendar_rows = calendar_view.json()["events"]
    legal_date = next(row for row in calendar_rows if row["title"] == deadline["title"])
    internal_target = next(
        row for row in calendar_rows if row["title"] == f"Internal target: {deadline['title']}"
    )
    assert legal_date["display_type"] == "filing_deadline"
    assert internal_target["display_type"] == "internal_target"
    assert legal_date["ip_docket_id"] == docket["id"]
    assert internal_target["ip_docket_id"] == docket["id"]
    with get_session_factory()() as session:
        initial_syncs = list(
            session.scalars(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_type == "matter_deadline",
                    CalendarEventSync.source_id == confirmed["matter_deadline_id"],
                )
            ).all()
        )
        assert len(initial_syncs) == 2
        assert {row.sync_status for row in initial_syncs} == {
            CalendarEventSyncStatus.PENDING
        }
        initial_sync_ids = {row.id for row in initial_syncs}
        for index, row in enumerate(initial_syncs):
            row.sync_status = CalendarEventSyncStatus.SYNCED
            row.provider_event_id = f"confirmed-provider-{index}"
        coverage = session.scalar(
            select(IpDeadlineCoverage).where(
                IpDeadlineCoverage.matter_deadline_id == confirmed["matter_deadline_id"]
            )
        )
        assert coverage is not None
        assert coverage.calendar_projection_status == "pending"
        session.commit()

    generic_done = client.patch(
        f"/api/matters/{matter['id']}/deadlines/{confirmed['matter_deadline_id']}",
        headers=owner_headers,
        json={"status": "done", "assignee_membership_id": reviewer_id},
    )
    assert generic_done.status_code == 409, generic_done.text
    assert generic_done.json()["code"] == "ip_deadline_workflow_required"
    still_legal = client.get(
        f"/api/ip/dockets/{docket['id']}/deadline-workspace",
        headers=owner_headers,
    )
    assert still_legal.status_code == 200, still_legal.text
    stored = next(item for item in still_legal.json()["deadlines"] if item["id"] == confirmed["id"])
    assert stored["state"] == "confirmed"
    assert still_legal.json()["automation_state"] == "explicit_confirmation_only"
    with get_session_factory()() as session:
        operational = session.get(MatterDeadline, confirmed["matter_deadline_id"])
        coverage = session.scalar(
            select(IpDeadlineCoverage).where(
                IpDeadlineCoverage.matter_deadline_id == confirmed["matter_deadline_id"]
            )
        )
        assert operational is not None and coverage is not None
        assert operational.status == "open"
        assert operational.assignee_membership_id == coverage.responsible_membership_id

    recalculation = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/recalculate",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"],
            "base_date": "2026-08-15",
            "base_date_certainty": "certain",
            "reason": "A later official receipt date was verified.",
            "evidence_reference": "attachment:official-receipt-later-date",
        },
    )
    assert recalculation.status_code == 200, recalculation.text
    candidate = recalculation.json()
    assert candidate["state"] == "candidate"
    assert candidate["supersedes_deadline_id"] == confirmed["id"]

    with get_session_factory()() as session:
        original = session.get(IpDeadline, confirmed["id"])
        assert original is not None
        assert original.state == "confirmed"

    impact = client.get(
        f"/api/ip/deadlines/{confirmed['id']}/impact",
        headers=legal_headers,
    )
    assert impact.status_code == 200, impact.text
    impact_body = impact.json()
    with get_session_factory()() as session:
        wall = EthicalWall(
            company_id=matter["company_id"],
            ip_docket_id=docket["id"],
            excluded_membership_id=reviewer_id,
            reason="Override responsibility cannot access the IP record.",
            created_by_membership_id=owner_id,
        )
        session.add(wall)
        session.commit()
        override_wall_id = wall.id
    blocked_override = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/override",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"],
            "new_result_on": "2026-08-20",
            "reason": "Official extension order changes the legal date.",
            "evidence_reference": "attachment:official-extension-order",
            "impact_token": impact_body["impact_token"],
            "responsibilities": _responsibilities(owner_id, reviewer_id),
        },
    )
    assert blocked_override.status_code == 409, blocked_override.text
    assert "stable Matter and IP-record access" in blocked_override.text
    with get_session_factory()() as session:
        wall = session.get(EthicalWall, override_wall_id)
        assert wall is not None
        session.delete(wall)
        session.commit()
    bad_override = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/override",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"],
            "new_result_on": "2026-08-20",
            "reason": "Official extension order changes the legal date.",
            "evidence_reference": "attachment:official-extension-order",
            "impact_token": "stale-token",
            "responsibilities": _responsibilities(owner_id, reviewer_id),
        },
    )
    assert bad_override.status_code == 409
    override = client.post(
        f"/api/ip/deadlines/{confirmed['id']}/override",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"],
            "new_result_on": "2026-08-20",
            "reason": "Official extension order changes the legal date.",
            "evidence_reference": "attachment:official-extension-order",
            "impact_token": impact_body["impact_token"],
            "responsibilities": _responsibilities(owner_id, reviewer_id),
            "reminder_offsets_days": [1, 0],
        },
    )
    assert override.status_code == 200, override.text
    replacement = override.json()
    assert replacement["state"] == "confirmed"
    assert replacement["result_on"] == "2026-08-20"
    assert replacement["supersedes_deadline_id"] == confirmed["id"]
    with get_session_factory()() as session:
        from caseops_api.services.calendar_sync import (
            _recompute_ip_calendar_projection_status,
        )

        retired_syncs = list(
            session.scalars(
                select(CalendarEventSync).where(CalendarEventSync.id.in_(initial_sync_ids))
            ).all()
        )
        assert {row.sync_status for row in retired_syncs} == {
            CalendarEventSyncStatus.DELETE_PENDING
        }
        retired_coverage = session.scalar(
            select(IpDeadlineCoverage).where(
                IpDeadlineCoverage.matter_deadline_id
                == confirmed["matter_deadline_id"]
            )
        )
        assert retired_coverage is not None
        assert retired_coverage.coverage_status == "completed"
        assert retired_coverage.calendar_projection_status == "completed"
        for row in retired_syncs:
            row.sync_status = CalendarEventSyncStatus.DELETED
        session.flush()
        assert (
            _recompute_ip_calendar_projection_status(
                session,
                company_id=matter["company_id"],
                matter_deadline_id=confirmed["matter_deadline_id"],
            )
            is None
        )
        session.refresh(retired_coverage)
        assert retired_coverage.coverage_status == "completed"
        assert retired_coverage.calendar_projection_status == "completed"
        replacement_syncs = list(
            session.scalars(
                select(CalendarEventSync).where(
                    CalendarEventSync.source_type == "matter_deadline",
                    CalendarEventSync.source_id == replacement["matter_deadline_id"],
                )
            ).all()
        )
        assert len(replacement_syncs) == 2
        assert {row.sync_status for row in replacement_syncs} == {
            CalendarEventSyncStatus.PENDING
        }
        replacement_sync_ids = {row.id for row in replacement_syncs}
        for index, row in enumerate(replacement_syncs):
            row.sync_status = CalendarEventSyncStatus.SYNCED
            row.provider_event_id = f"replacement-provider-{index}"
        session.commit()

    completed = client.post(
        f"/api/ip/deadlines/{replacement['id']}/complete",
        headers=legal_headers,
        json={
            "expected_version": replacement["version"],
            "evidence_reference": "receipt:official-response-filing",
            "attestation": "Verified filing evidence against the official receipt.",
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "completed"
    assert completed.json()["completed_evidence_ref"] == "receipt:official-response-filing"

    with get_session_factory()() as session:
        legal_rows = list(
            session.scalars(select(IpDeadline).where(IpDeadline.docket_id == docket["id"])).all()
        )
        assert {row.state for row in legal_rows} >= {"completed", "superseded", "candidate"}
        coverages = list(
            session.scalars(
                select(IpDeadlineCoverage).where(IpDeadlineCoverage.docket_id == docket["id"])
            ).all()
        )
        assert len(coverages) == 2
        assert {row.coverage_status for row in coverages} == {"completed"}
        assert {row.calendar_projection_status for row in coverages} == {
            "completed"
        }
        legal_projection = session.get(MatterDeadline, replacement["matter_deadline_id"])
        assert legal_projection is not None
        assert legal_projection.status == "done"
        completed_syncs = list(
            session.scalars(
                select(CalendarEventSync).where(
                    CalendarEventSync.id.in_(replacement_sync_ids)
                )
            ).all()
        )
        assert {row.sync_status for row in completed_syncs} == {
            CalendarEventSyncStatus.DELETE_PENDING
        }
        reminder_intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.schedule_source_type == "ip_deadline"
                )
            ).all()
        )
        assert reminder_intents
        assert {intent.channel for intent in reminder_intents} == {"in_app"}
        assert all(intent.status != "queued" for intent in reminder_intents)


def test_provisional_exception_disabled_rule_and_cross_tenant_governance_fail_closed(
    client: TestClient,
) -> None:
    first = bootstrap_company(client)
    owner_token = str(first["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client,
        owner_token,
        name="Exception Legal Approver",
        email="deadline-exception-legal@asterlegal.in",
    )
    reviewer_id, _ = _member(
        client,
        owner_token,
        name="Exception Fixture Reviewer",
        email="deadline-exception-reviewer@asterlegal.in",
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-DL-EXCEPTION")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])

    calendar = client.post(
        "/api/ip/working-calendars", headers=owner_headers, json=_calendar_payload()
    ).json()
    activated_calendar = client.post(
        f"/api/ip/working-calendars/{calendar['id']}/activate",
        headers=legal_headers,
        json={"reason": "Independent calendar review is complete."},
    )
    assert activated_calendar.status_code == 200, activated_calendar.text
    rule = client.post("/api/ip/deadline-rules", headers=owner_headers, json=_rule_payload()).json()
    activated_rule = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/activate",
        headers=legal_headers,
        json={"reviewer_membership_id": reviewer_id},
    )
    assert activated_rule.status_code == 200, activated_rule.text

    provisional_response = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Resolve conflicting official receipt date",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": None,
            "base_date_certainty": "conflicting",
            "is_critical": True,
        },
    )
    assert provisional_response.status_code == 201, provisional_response.text
    provisional = provisional_response.json()
    assert provisional["state"] == "provisional"
    assert provisional["result_on"] is None
    blocked_confirmation = client.post(
        f"/api/ip/deadlines/{provisional['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": provisional["version"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert blocked_confirmation.status_code == 409

    workspace = client.get(
        f"/api/ip/dockets/{docket['id']}/deadline-workspace",
        headers=owner_headers,
    )
    assert workspace.status_code == 200, workspace.text
    exception = next(
        item for item in workspace.json()["exceptions"] if item["deadline_id"] == provisional["id"]
    )
    assert set(exception["exception_kinds"]) >= {"conflicting", "unowned"}

    resolved_confirmation = client.post(
        f"/api/ip/deadlines/{provisional['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": provisional["version"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
            "corrected_result_on": "2026-08-18",
            "correction_reason": "Independent review resolved the competing official sources.",
            "correction_evidence_reference": "attachment:source-conflict-resolution",
        },
    )
    assert resolved_confirmation.status_code == 200, resolved_confirmation.text
    assert resolved_confirmation.json()["state"] == "confirmed"
    assert resolved_confirmation.json()["certainty"] == "certain"
    assert resolved_confirmation.json()["id"] == provisional["id"]
    assert resolved_confirmation.json()["override_evidence_ref"] == (
        "attachment:source-conflict-resolution"
    )
    assert resolved_confirmation.json()["calculation_trace"][-1]["operation"] == (
        "sourced_confirmation_correction"
    )

    impact = client.get(
        f"/api/ip/deadline-rules/{rule['id']}/impact",
        headers=legal_headers,
    ).json()
    disabled = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/transition",
        headers=legal_headers,
        json={
            "impact_token": impact["impact_token"],
            "reason": "Emergency source conflict requires fail-closed disablement.",
            "emergency_disable": True,
        },
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    blocked_proposal = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Must not calculate from disabled rule",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
        },
    )
    assert blocked_proposal.status_code == 409

    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Deadline Firm",
            "company_slug": "other-deadline-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-deadline.example",
            "owner_password": "OtherDeadline123!",
        },
    )
    assert second.status_code == 200, second.text
    second_headers = auth_headers(str(second.json()["access_token"]))
    leaked_impact = client.get(
        f"/api/ip/deadline-rules/{rule['id']}/impact",
        headers=second_headers,
    )
    assert leaked_impact.status_code == 404
    leaked_workspace = client.get(
        f"/api/ip/dockets/{docket['id']}/deadline-workspace",
        headers=second_headers,
    )
    assert leaked_workspace.status_code == 404
