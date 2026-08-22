from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import UniqueConstraint

from caseops_api.db.base import Base
from caseops_api.schemas.ip_deadlines import (
    IpDeadlineCalculationRequest,
    LegalCalendarSnapshot,
    ResponsibilityEvidence,
)
from caseops_api.services.ip_deadlines import (
    assert_critical_deadline_coverage,
    assert_rule_can_activate,
    calculate_ip_deadline,
    operational_projection_reference,
)

FOUNDATION_TABLES = {
    "legal_working_calendars",
    "legal_working_calendar_versions",
    "ip_rule_sets",
    "ip_rule_versions",
    "company_ip_rule_policies",
    "ip_deadlines",
    "ip_responsibility_assignments",
}


def _calendar(**overrides) -> LegalCalendarSnapshot:
    values = {
        "calendar_version_id": "calendar-version-1",
        "timezone": "Asia/Kolkata",
        "weekend_days": [5, 6],
        "holidays": [date(2026, 8, 17)],
        "exceptional_working_days": [],
        "source_reference": "https://official.example/calendar/2026",
        "source_hash": "a" * 64,
    }
    values.update(overrides)
    return LegalCalendarSnapshot(**values)


def _request(**overrides) -> IpDeadlineCalculationRequest:
    values = {
        "deadline_kind": "legal_deadline",
        "trigger_kind": "examination_report_received",
        "base_date": date(2026, 8, 14),
        "base_date_certainty": "certain",
        "duration_value": 1,
        "duration_unit": "days",
        "calendar_method": "business_days",
        "rule_version_id": "rule-version-1",
        "rule_citation": "Trade Marks Rules, verified fixture citation",
        "source_version": "source-2026-08-07",
        "engine_version": "caseops-ip-deadline-v1",
        "calendar": _calendar(),
    }
    values.update(overrides)
    return IpDeadlineCalculationRequest(**values)


def test_foundation_publishes_new_legal_evidence_without_duplicate_operational_owner() -> None:
    assert FOUNDATION_TABLES <= set(Base.metadata.tables)
    assert "matter_deadlines" in Base.metadata.tables
    deadline_table = Base.metadata.tables["ip_deadlines"]
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in deadline_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("matter_deadline_id",) in unique_columns


def test_business_day_calculation_skips_weekend_and_official_holiday() -> None:
    result = calculate_ip_deadline(_request())

    assert result.state == "candidate"
    assert result.result_on == date(2026, 8, 18)
    assert [row["reason"] for row in result.trace if "reason" in row] == [
        "weekend",
        "weekend",
        "holiday",
    ]
    assert "confirmation remains required" in result.explanation
    assert result.inputs["calendar"]["calendar_version_id"] == "calendar-version-1"


def test_uncertain_trigger_remains_visible_without_manufactured_precision() -> None:
    result = calculate_ip_deadline(
        _request(base_date=None, base_date_certainty="conflicting")
    )

    assert result.state == "provisional"
    assert result.result_on is None
    assert result.certainty == "conflicting"
    assert result.trace == [
        {"operation": "stop_for_uncertain_trigger", "certainty": "conflicting"}
    ]


def test_calculation_contract_accepts_the_canonical_renewal_grace_kind() -> None:
    request = _request(deadline_kind="renewal_grace")

    assert request.deadline_kind == "renewal_grace"
    assert calculate_ip_deadline(request).result_on == date(2026, 8, 18)


def test_calendar_rejects_conflicting_day_classification() -> None:
    with pytest.raises(ValueError, match="both a holiday and an exceptional working day"):
        _calendar(exceptional_working_days=[date(2026, 8, 17)])


def test_rule_activation_requires_two_independent_approvers_and_all_fixtures() -> None:
    assert_rule_can_activate(
        proposer_membership_id="proposer",
        reviewer_membership_id="reviewer",
        legal_approver_membership_id="lawyer",
        fixture_ids=["fixture-1", "fixture-2"],
        passed_fixture_ids=["fixture-2", "fixture-1"],
    )

    with pytest.raises(HTTPException, match="independent"):
        assert_rule_can_activate(
            proposer_membership_id="proposer",
            reviewer_membership_id="proposer",
            legal_approver_membership_id="lawyer",
            fixture_ids=["fixture-1"],
            passed_fixture_ids=["fixture-1"],
        )
    with pytest.raises(HTTPException, match="Every legal fixture"):
        assert_rule_can_activate(
            proposer_membership_id="proposer",
            reviewer_membership_id="reviewer",
            legal_approver_membership_id="lawyer",
            fixture_ids=["fixture-1", "fixture-2"],
            passed_fixture_ids=["fixture-1"],
        )


def test_critical_deadline_requires_acknowledged_primary_and_escalation_coverage() -> None:
    with pytest.raises(HTTPException, match="primary owner"):
        assert_critical_deadline_coverage([])
    with pytest.raises(HTTPException, match="backup or escalation"):
        assert_critical_deadline_coverage(
            [ResponsibilityEvidence(membership_id="primary", role="primary", accepted=True)]
        )
    with pytest.raises(HTTPException) as collapsed:
        assert_critical_deadline_coverage(
            [
                ResponsibilityEvidence(
                    membership_id="same-person", role="primary", accepted=True
                ),
                ResponsibilityEvidence(
                    membership_id="same-person", role="backup", accepted=True
                ),
            ]
        )
    assert collapsed.value.status_code == 409
    assert collapsed.value.detail["code"] == "ip_coverage_distinct_backup_required"

    assert_critical_deadline_coverage(
        [
            ResponsibilityEvidence(membership_id="primary", role="primary", accepted=True),
            ResponsibilityEvidence(membership_id="backup", role="backup", accepted=True),
        ]
    )


def test_operational_projection_uses_existing_deadline_source_contract() -> None:
    assert operational_projection_reference("ip-deadline-1") == (
        "ip_deadline",
        "ip-deadline-1",
    )

