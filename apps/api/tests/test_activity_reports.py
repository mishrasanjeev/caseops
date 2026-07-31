from __future__ import annotations

from datetime import UTC, datetime

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    CompanyNotice,
    CompanyType,
    Matter,
    MatterTask,
    MatterTaskStatus,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.activity_reports import (
    ACTIVITY_METRICS,
    SNAPSHOT_METRICS,
    build_activity_report,
    render_report,
)


def _period(**overrides: int | float) -> dict[str, int | float]:
    values = {key: 0.0 if kind == "hours" else 0 for key, _label, kind in ACTIVITY_METRICS}
    values.update(overrides)
    return values


def _snapshot(**overrides: int) -> dict[str, int]:
    values = {key: 0 for key, _label, _kind in SNAPSHOT_METRICS}
    values.update(overrides)
    return values


def _report() -> dict:
    law_periods = {
        "day": _period(matters_created=12, notices_sent=3, billable_hours=4.5),
        "week": _period(matters_created=45, notices_sent=9, billable_hours=22.0),
        "month": _period(
            matters_created=1234,
            notices_sent=27,
            invoiced_amount_minor=250_000,
        ),
        "till_date": _period(
            matters_created=4321,
            notices_sent=99,
            invoiced_amount_minor=1_500_000,
        ),
    }
    account = {
        "company_id": "law-1",
        "name": "Alpha Legal",
        "company_type": CompanyType.LAW_FIRM.value,
        "is_active": True,
        "current": _snapshot(
            active_users=8,
            active_matters=21,
            overdue_tasks=2,
            storage_bytes=10 * 1024 * 1024,
            outstanding_amount_minor=75_000,
        ),
        "periods": law_periods,
    }
    return {
        "generated_at": "2026-07-10T08:00:00+05:30",
        "reporting_periods": {
            "day": {"start_date": "2026-07-09", "end_date": "2026-07-09"},
            "week": {"start_date": "2026-06-29", "end_date": "2026-07-05"},
            "month": {"start_date": "2026-06-01", "end_date": "2026-06-30"},
            "till_date": {"start_date": None, "end_date": "2026-07-10"},
        },
        "segments": {
            "law_firms": {
                "company_count": 1,
                "company_names": ["Alpha Legal"],
                "periods": law_periods,
                "accounts": [account],
            },
            "general_counsels": {
                "company_count": 0,
                "company_names": [],
                "periods": {period: _period() for period in law_periods},
                "accounts": [],
            },
        },
    }


def test_render_report_builds_account_wise_html_and_plaintext_dashboard() -> None:
    text, html = render_report(_report())

    assert "<!doctype html>" in html
    assert '<table role="presentation"' in html
    assert '<th scope="col">Daily' in html
    assert '<th scope="col">Till date' in html
    assert '<th scope="row">Matters created</th>' in html
    assert '<th scope="row">Invoiced value (INR)</th>' in html
    assert "09 Jul 2026" in html
    assert "29 Jun 2026 - 05 Jul 2026" in html
    assert "Through 10 Jul 2026" in html
    assert ">1,234</td>" in html
    assert "₹2,500.00" in html
    assert "Law Firms" in html
    assert "General Counsels" in html
    assert "Alpha Legal" in html
    assert "Active users" in html
    assert "Document storage" in html
    assert "10.00 MB" in html
    assert "border-collapse" in html
    assert "@media(max-width:680px)" in html

    assert "Metric | Daily | Weekly | Monthly | Till date" in text
    assert "Matters created | 12 | 45 | 1,234 | 4,321" in text
    assert "Daily: 09 Jul 2026" in text
    assert "ACCOUNT: Alpha Legal (Active)" in text
    assert "- Active users: 8" in text


def test_render_report_escapes_account_names_and_handles_empty_segment() -> None:
    report = _report()
    report["segments"]["law_firms"]["accounts"][0]["name"] = "A&B <Legal>"

    text, html = render_report(report)

    assert "A&amp;B &lt;Legal&gt;" in html
    assert "A&B <Legal>" not in html
    assert "A&B <Legal>" in text
    assert "No accounts recorded" in html
    assert "No accounts recorded" in text


def test_build_activity_report_groups_activity_by_account_and_period(client) -> None:
    assert client.app is not None
    activity_at = datetime(2026, 7, 9, 4, 30, tzinfo=UTC)
    now = datetime(2026, 7, 10, 2, 30, tzinfo=UTC)

    with get_session_factory()() as session:
        company = Company(
            name="Account One",
            slug="account-one",
            company_type=CompanyType.LAW_FIRM.value,
            tenant_key="account-one",
            created_at=activity_at,
        )
        user = User(
            email="account-one@example.com",
            full_name="Account User",
            password_hash="not-used-in-this-test",
            created_at=activity_at,
        )
        session.add_all([company, user])
        session.flush()
        membership = CompanyMembership(
            company_id=company.id,
            user_id=user.id,
            role="admin",
            created_at=activity_at,
        )
        matter = Matter(
            company_id=company.id,
            title="Report matter",
            matter_code="REPORT-001",
            practice_area="Litigation",
            forum_level="high_court",
            created_at=activity_at,
        )
        session.add_all([membership, matter])
        session.flush()
        session.add_all(
            [
                MatterTask(
                    matter_id=matter.id,
                    title="Completed report task",
                    status=MatterTaskStatus.COMPLETED,
                    completed_at=activity_at,
                    created_at=activity_at,
                ),
                CompanyNotice(
                    company_id=company.id,
                    created_by_membership_id=membership.id,
                    direction="sent",
                    subject="Sent report notice",
                    status="Open",
                    sent_on=activity_at.date(),
                    created_at=activity_at,
                ),
            ]
        )
        session.commit()

        report = build_activity_report(session, now=now)

    segment = report["segments"]["law_firms"]
    assert segment["company_count"] == 1
    account = segment["accounts"][0]
    assert account["name"] == "Account One"
    assert account["periods"]["day"]["users_added"] == 1
    assert account["periods"]["day"]["matters_created"] == 1
    assert account["periods"]["day"]["tasks_created"] == 1
    assert account["periods"]["day"]["tasks_completed"] == 1
    assert account["periods"]["day"]["notices_sent"] == 1
    assert account["periods"]["till_date"]["matters_created"] == 1
    assert account["current"]["active_users"] == 1
    assert account["current"]["active_matters"] == 1
    assert account["current"]["open_notices"] == 1
    assert report["reporting_periods"]["till_date"]["end_date"] == "2026-07-10"


def test_build_activity_report_excludes_non_production_account_names(client) -> None:
    assert client.app is not None
    created_at = datetime(2026, 7, 10, 2, 30, tzinfo=UTC)

    with get_session_factory()() as session:
        session.add_all(
            [
                Company(
                    name="Production Legal",
                    slug="production-legal",
                    company_type=CompanyType.LAW_FIRM.value,
                    tenant_key="production-legal",
                    created_at=created_at,
                ),
                Company(
                    name="Smoke Account",
                    slug="smoke-account",
                    company_type=CompanyType.LAW_FIRM.value,
                    tenant_key="smoke-account",
                    created_at=created_at,
                ),
                Company(
                    name="CSRF Probe",
                    slug="csrf-probe",
                    company_type=CompanyType.LAW_FIRM.value,
                    tenant_key="csrf-probe",
                    created_at=created_at,
                ),
                Company(
                    name="Debug E2E TEST tenant",
                    slug="debug-e2e-test-tenant",
                    company_type=CompanyType.CORPORATE_LEGAL.value,
                    tenant_key="debug-e2e-test-tenant",
                    created_at=created_at,
                ),
            ]
        )
        session.commit()

        report = build_activity_report(
            session,
            now=datetime(2026, 7, 10, 2, 30, tzinfo=UTC),
        )

    accounts = [
        account
        for segment in report["segments"].values()
        for account in segment["accounts"]
    ]
    assert [account["name"] for account in accounts] == ["Production Legal"]
    assert report["segments"]["law_firms"]["company_count"] == 1
    assert report["segments"]["general_counsels"]["company_count"] == 0
