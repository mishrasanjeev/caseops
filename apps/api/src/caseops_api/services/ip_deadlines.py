"""Deterministic, side-effect-free IP deadline foundation.

This module calculates evidence only.  It does not create an operational
``MatterDeadline``, send a reminder, or auto-confirm a legal obligation.  The
completion slice owns those guarded commands and delegates its single
operational projection to the existing deadline service.
"""

from __future__ import annotations

import calendar as month_calendar
from datetime import date, timedelta

from fastapi import HTTPException, status

from caseops_api.schemas.ip_deadlines import (
    IpDeadlineCalculationRequest,
    IpDeadlineCalculationResult,
    LegalCalendarSnapshot,
    ResponsibilityEvidence,
)


def _is_working_day(value: date, calendar: LegalCalendarSnapshot) -> bool:
    if value in calendar.exceptional_working_days:
        return True
    return value.weekday() not in calendar.weekend_days and value not in calendar.holidays


def _roll_to_working_day(
    value: date,
    *,
    direction: int,
    calendar: LegalCalendarSnapshot,
    trace: list[dict],
) -> date:
    result = value
    while not _is_working_day(result, calendar):
        reason = "holiday" if result in calendar.holidays else "weekend"
        trace.append(
            {
                "operation": "skip_non_working_day",
                "date": result.isoformat(),
                "reason": reason,
            }
        )
        result += timedelta(days=direction)
    return result


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, month_calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, month=2, day=28)


def calculate_ip_deadline(
    payload: IpDeadlineCalculationRequest,
) -> IpDeadlineCalculationResult:
    """Return fully reproducible calculation evidence without legal side effects."""

    inputs = payload.model_dump(mode="json")
    if payload.base_date is None or payload.base_date_certainty != "certain":
        return IpDeadlineCalculationResult(
            state="provisional",
            result_on=None,
            certainty=payload.base_date_certainty,
            explanation=(
                f"{payload.deadline_kind.replace('_', ' ')} remains provisional because "
                f"the {payload.trigger_kind.replace('_', ' ')} date is "
                f"{payload.base_date_certainty}; no date was manufactured."
            ),
            inputs=inputs,
            trace=[
                {
                    "operation": "stop_for_uncertain_trigger",
                    "certainty": payload.base_date_certainty,
                }
            ],
        )

    direction = 1 if payload.direction == "after" else -1
    trace: list[dict] = [
        {
            "operation": "select_trigger",
            "trigger_kind": payload.trigger_kind,
            "base_date": payload.base_date.isoformat(),
        }
    ]
    result = payload.base_date

    if payload.calendar_method == "business_days":
        remaining = payload.duration_value
        if payload.include_base_date and _is_working_day(result, payload.calendar):
            remaining = max(0, remaining - 1)
            trace.append({"operation": "include_base_working_day", "date": result.isoformat()})
        while remaining:
            result += timedelta(days=direction)
            if _is_working_day(result, payload.calendar):
                remaining -= 1
            else:
                reason = "holiday" if result in payload.calendar.holidays else "weekend"
                trace.append(
                    {
                        "operation": "skip_non_working_day",
                        "date": result.isoformat(),
                        "reason": reason,
                    }
                )
    elif payload.calendar_method == "calendar_days":
        offset = payload.duration_value - (1 if payload.include_base_date else 0)
        result += timedelta(days=direction * max(0, offset))
        trace.append({"operation": "calendar_day_offset", "days": direction * max(0, offset)})
    elif payload.calendar_method == "month_anniversary":
        result = _add_months(result, direction * payload.duration_value)
        trace.append(
            {"operation": "month_anniversary", "months": direction * payload.duration_value}
        )
    else:
        result = _add_years(result, direction * payload.duration_value)
        trace.append({"operation": "year_anniversary", "years": direction * payload.duration_value})

    if payload.extension_days:
        result += timedelta(days=direction * payload.extension_days)
        trace.append({"operation": "extension", "days": direction * payload.extension_days})

    if payload.next_working_day and not _is_working_day(result, payload.calendar):
        result = _roll_to_working_day(
            result,
            direction=direction,
            calendar=payload.calendar,
            trace=trace,
        )

    trace.append({"operation": "result", "date": result.isoformat()})
    return IpDeadlineCalculationResult(
        state="candidate",
        result_on=result,
        certainty="certain",
        explanation=(
            f"Calculated {payload.deadline_kind.replace('_', ' ')} from "
            f"{payload.base_date.isoformat()} using {payload.duration_value} "
            f"{payload.duration_unit}, {payload.calendar_method.replace('_', ' ')}, "
            f"calendar version {payload.calendar.calendar_version_id}, and rule "
            f"version {payload.rule_version_id}; confirmation remains required."
        ),
        inputs=inputs,
        trace=trace,
    )


def assert_rule_can_activate(
    *,
    proposer_membership_id: str,
    reviewer_membership_id: str,
    legal_approver_membership_id: str,
    fixture_ids: list[str],
    passed_fixture_ids: list[str],
) -> None:
    """Enforce two-person legal approval and complete fixtures."""

    if proposer_membership_id in {reviewer_membership_id, legal_approver_membership_id}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rule activation requires reviewers independent of the proposer.",
        )
    if reviewer_membership_id == legal_approver_membership_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rule activation requires two distinct qualified approvers.",
        )
    if not fixture_ids or set(fixture_ids) != set(passed_fixture_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Every legal fixture must pass before rule activation.",
        )


def assert_critical_deadline_coverage(
    responsibilities: list[ResponsibilityEvidence],
) -> None:
    """Require acknowledged primary plus backup/escalation coverage."""

    accepted = [item for item in responsibilities if item.active and item.accepted]
    accepted_roles = {item.role for item in accepted}
    if "primary" not in accepted_roles:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Critical deadline confirmation requires an acknowledged primary owner.",
        )
    if not accepted_roles.intersection({"backup", "supervisor", "docketing"}):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Critical deadline confirmation requires backup or escalation coverage.",
        )
    primary_ids = {item.membership_id for item in accepted if item.role == "primary"}
    backup_ids = {
        item.membership_id
        for item in accepted
        if item.role in {"backup", "supervisor", "docketing"}
    }
    if primary_ids & backup_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_distinct_backup_required",
                "message": (
                    "Critical deadline responsibility and backup or escalation "
                    "coverage must be assigned to different people."
                ),
            },
        )


def assert_distinct_deadline_coverage(
    *,
    responsible_membership_id: str,
    backup_membership_id: str | None,
) -> None:
    """Refuse a coverage row whose primary and backup collapse to one person."""

    if (
        backup_membership_id is not None
        and responsible_membership_id == backup_membership_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_distinct_backup_required",
                "message": (
                    "Deadline responsibility and backup coverage must be assigned "
                    "to different people."
                ),
            },
        )


def assert_distinct_deadline_escalation(
    *,
    escalation_membership_id: str,
    backup_membership_id: str | None,
    responsible_membership_id: str | None = None,
) -> None:
    """Refuse a fallback that collapses onto primary or backup coverage."""

    if (
        escalation_membership_id == responsible_membership_id
        or (
            backup_membership_id is not None
            and escalation_membership_id == backup_membership_id
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_distinct_backup_required",
                "message": (
                    "The decline or expiry escalation owner must be different from "
                    "the resulting deadline responsible owner and backup."
                ),
            },
        )


def operational_projection_reference(deadline_id: str) -> tuple[str, str]:
    """Canonical source identity for the existing operational deadline owner."""

    return "ip_deadline", deadline_id
