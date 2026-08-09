from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    IpDeadline,
    IpDeadlineCoverage,
    MatterDeadline,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars


def _member(
    client: TestClient,
    owner_token: str,
    *,
    name: str,
    email: str,
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
            "company_slug": "aster-legal",
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


def test_rule_calendar_deadline_end_to_end_and_immutable_legal_completion(
    client: TestClient,
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

    incomplete_coverage = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(owner_id, reviewer_id)[:1],
        },
    )
    assert incomplete_coverage.status_code == 409
    stale = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": 99,
            "responsibilities": _responsibilities(owner_id, reviewer_id),
        },
    )
    assert stale.status_code == 409

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

    generic_done = client.patch(
        f"/api/matters/{matter['id']}/deadlines/{confirmed['matter_deadline_id']}",
        headers=owner_headers,
        json={"status": "done"},
    )
    assert generic_done.status_code == 200, generic_done.text
    still_legal = client.get(
        f"/api/ip/dockets/{docket['id']}/deadline-workspace",
        headers=owner_headers,
    )
    assert still_legal.status_code == 200, still_legal.text
    stored = next(item for item in still_legal.json()["deadlines"] if item["id"] == confirmed["id"])
    assert stored["state"] == "confirmed"
    assert still_legal.json()["automation_state"] == "explicit_confirmation_only"

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
        legal_projection = session.get(MatterDeadline, replacement["matter_deadline_id"])
        assert legal_projection is not None
        assert legal_projection.status == "done"
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
