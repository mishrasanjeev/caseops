"""Production-shaped preconditions for tests that exercise IP rule governance.

Rule and calendar governance writers enforce the company's ``ip_rule_governance``
entitlement on the server (IPLF-027B A1). A workspace is entitled in production
through a manual billing entitlement override, so tests that need an entitled
workspace use exactly that path; nothing here bypasses or monkeypatches the
server decision. Tests that prove the refusal simply do not call it.
"""

from __future__ import annotations

from sqlalchemy import select

from caseops_api.db.models import BillingSubscription
from caseops_api.db.session import get_session_factory

RULE_GOVERNANCE_ENTITLEMENT = "ip_rule_governance"
# The working calendar a rule fixture runs on in the precondition helpers.
PRECONDITION_CALENDAR = "ip-india-2026-precondition"


def grant_ip_rule_governance_entitlement(company_id: str) -> None:
    with get_session_factory()() as session:
        subscription = session.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.company_id == company_id)
            .order_by(BillingSubscription.created_at.desc())
        )
        if subscription is None:
            session.add(
                BillingSubscription(
                    company_id=company_id,
                    status="manual_active",
                    segment="law_firm",
                    source="ip-rule-governance-test",
                    externally_billable=False,
                    entitlement_overrides_json={RULE_GOVERNANCE_ENTITLEMENT: True},
                )
            )
        else:
            subscription.entitlement_overrides_json = {
                **(subscription.entitlement_overrides_json or {}),
                RULE_GOVERNANCE_ENTITLEMENT: True,
            }
        session.commit()


def rule_payload_on_calendar(payload: dict, calendar: dict) -> dict:
    """Bind every fixture of a deadline rule payload to a stored calendar version.

    ``calendar`` is a working calendar version record as the API returns it.
    The server accepts fixtures only on an active working calendar of the
    proposing workspace, exactly as stored (B4-ADJ-08), so tests embed the
    record they activated instead of a made-up snapshot.
    """

    snapshot = {
        "calendar_version_id": calendar["id"],
        "timezone": calendar["timezone"],
        "weekend_days": list(calendar["weekend_days"]),
        "holidays": list(calendar["holidays"]),
        "exceptional_working_days": list(calendar["exceptional_working_days"]),
        "source_reference": calendar["source_reference"],
        "source_hash": calendar["source_hash"],
    }
    bound = {**payload, "fixtures": []}
    for fixture in payload["fixtures"]:
        calculation = fixture.get("calculation")
        bound["fixtures"].append(
            {**fixture, "calculation": {**calculation, "calendar": dict(snapshot)}}
            if calculation
            else dict(fixture)
        )
    return bound


def activated_calendar(
    client,
    proposer_headers: dict[str, str],
    activator_headers: dict[str, str],
    payload: dict | None = None,
) -> dict:
    """Propose a working calendar and activate it as a second person."""

    body = payload or {
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
    proposed = client.post("/api/ip/working-calendars", headers=proposer_headers, json=body)
    assert proposed.status_code == 201, proposed.text
    activated = client.post(
        f"/api/ip/working-calendars/{proposed.json()['id']}/activate",
        headers=activator_headers,
        json={
            "reason": "Reviewed official calendar source and conflicts.",
            "conflict_reviewed": True,
        },
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


def _calendar_record(row) -> dict:
    return {
        "id": row.id,
        "timezone": row.timezone,
        "weekend_days": list(row.weekend_days_json),
        "holidays": list(row.holidays_json),
        "exceptional_working_days": list(row.exceptional_working_days_json),
        "source_reference": row.source_reference,
        "source_hash": row.source_hash,
    }


def company_active_calendar(company_id: str) -> dict:
    """The company's newest active working calendar version, seeding one if none exists.

    For tests whose subject is rule governance, not calendar governance: the
    calendar is a precondition, so it is stored as an already activated
    version (the calendar two-person path is proven by the calendar tests and
    ``activated_calendar``). Adding approver members here would change the
    approver counts those tests assert.
    """

    from datetime import UTC, date, datetime

    from caseops_api.db.models import LegalWorkingCalendar, LegalWorkingCalendarVersion

    with get_session_factory()() as session:
        row = session.scalar(
            select(LegalWorkingCalendarVersion)
            .where(
                LegalWorkingCalendarVersion.company_id == company_id,
                LegalWorkingCalendarVersion.status == "active",
            )
            .order_by(LegalWorkingCalendarVersion.created_at.desc())
        )
        if row is None:
            calendar = LegalWorkingCalendar(
                company_id=company_id,
                key=PRECONDITION_CALENDAR,
                name="IP India official working calendar 2026",
                jurisdiction="IN",
                office="IP India",
            )
            session.add(calendar)
            session.flush()
            row = LegalWorkingCalendarVersion(
                company_id=company_id,
                calendar_id=calendar.id,
                version=1,
                status="active",
                timezone="Asia/Kolkata",
                weekend_days_json=[5, 6],
                holidays_json=["2026-08-17"],
                exceptional_working_days_json=[],
                source_priority_json=["official_gazette", "official_office_notice"],
                source_reference="https://official.example/ip-india/calendar/2026",
                source_hash="a" * 64,
                effective_from=date(2026, 1, 1),
                effective_until=date(2026, 12, 31),
                proposer_label_snapshot="Calendar precondition",
                approver_label_snapshot="Calendar precondition approver",
                approved_at=datetime.now(UTC),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return _calendar_record(row)


def rule_payload_for_company(client, headers: dict[str, str], payload: dict) -> dict:
    """Bind a deadline rule payload to the caller's company's active calendar."""

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return rule_payload_on_calendar(
        payload, company_active_calendar(str(me.json()["company"]["id"]))
    )
