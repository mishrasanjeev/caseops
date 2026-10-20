from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

import httpx
import pytest
from email_validator import deliverability
from sqlalchemy import event

from caseops_api.core.settings import Settings
from caseops_api.db.models import (
    AuditActorType,
    AuditEvent,
    AuditResult,
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
from caseops_api.services import activity_reports
from caseops_api.services.activity_reports import (
    ACTIVITY_METRICS,
    SNAPSHOT_METRICS,
    build_activity_report,
    render_report,
)
from tests.sql_observation import is_read_only_select


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


def _report_account(session, index: int, company_type="solo", *, active=True):
    company = Company(
        name=f"Practice {index}", slug=f"practice-{index}", tenant_key=f"practice-{index}",
        company_type=company_type, is_active=active,
    )
    user = User(
        email=f"practice-{index}@example.com", full_name="Report Owner", password_hash="unused"
    )
    session.add_all([company, user])
    session.flush()
    membership = CompanyMembership(company_id=company.id, user_id=user.id, role="owner")
    session.add(membership)
    session.flush()
    return company, membership


def _activity(session, membership, at, *, action="employee.login", actor="human", result="success",
              company_id=None, matter_id=None):
    session.add(AuditEvent(
        company_id=company_id or membership.company_id, actor_membership_id=membership.id,
        actor_type=actor, action=action, target_type="employee", result=result,
        created_at=at.astimezone(UTC), matter_id=matter_id,
    ))


def test_internal_scope_bypasses_names_only_and_conserves_real_account_metrics(client) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    activity_at = now - timedelta(hours=1)
    types = [*CompanyType, "legacy-unclassified", ""]
    internal_names = [
        "Smoke Practice", "CSRF Practice", "test-legal", "Debug Practice", "E2E Practice",
    ]
    with get_session_factory()() as session:
        for index, kind in enumerate(types):
            for internal in (False, True):
                company, membership = _report_account(
                    session, index * 2 + int(internal), kind, active=not internal,
                )
                if internal:
                    company.name = internal_names[index]
                membership.created_at = activity_at
                session.add(Matter(
                    company_id=company.id, title="Scope report matter", matter_code="SCOPE-001",
                    practice_area="Litigation", forum_level="high_court", created_at=activity_at,
                ))
                _activity(session, membership, activity_at)
        session.commit()
        default = build_activity_report(session, now=now)
        email = build_activity_report(session, now=now, include_internal_accounts=False)
        all_accounts = build_activity_report(session, now=now, include_internal_accounts=True)

    assert default == email
    assert email["account_scope"] == "operational_email"
    assert email["excluded_account_count"] == 5
    assert all_accounts["account_scope"] == "all_registered_accounts"
    assert all_accounts["excluded_account_count"] == 0
    flattened = {
        account["company_id"]: account
        for segment in all_accounts["segments"].values() for account in segment["accounts"]
    }
    assert len(flattened) == 10
    assert {account["company_type"] for account in flattened.values()} == {str(t) for t in types}
    assert all(account["usage_status"] == "recent" for account in flattened.values())
    assert sum(not account["is_active"] for account in flattened.values()) == 5
    for key, complete in all_accounts["segments"].items():
        operational = email["segments"][key]
        assert complete["company_count"] == len(complete["accounts"])
        assert complete["company_count"] == operational["company_count"] * 2
        assert complete["company_names"] == [account["name"] for account in complete["accounts"]]
        for account in operational["accounts"]:
            assert account == flattened[account["company_id"]]
            assert account["current"]["active_matters"] == 1
            assert account["periods"]["till_date"]["matters_created"] == 1
            assert account["periods"]["till_date"]["users_added"] == 1
            assert account["periods"]["till_date"]["audit_events"] == 1
        for period in activity_reports.PERIODS:
            for metric, _label, _kind in ACTIVITY_METRICS:
                assert complete["periods"][period][metric] == sum(
                    account["periods"][period][metric] for account in complete["accounts"]
                )
                assert complete["periods"][period][metric] == (
                    operational["periods"][period][metric] * 2
                )
    for report in (email, all_accounts):
        text, html = render_report(report)
        expected_scope = (
            "All registered accounts (0 excluded)" if report is all_accounts
            else "Operational email; 5 accounts excluded"
        )
        assert expected_scope in text and expected_scope in html
        for name in internal_names:
            assert (name in text) == (report is all_accounts)
            assert (name in html) == (report is all_accounts)


def test_report_includes_every_enum_and_other_once_with_conserved_metrics(
    client, monkeypatch,
) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    types = [*CompanyType, "legacy-unclassified", ""]

    def periods(_session, accounts, *, period, start, end):
        assert start < end
        for index, account in enumerate(accounts.values(), 1):
            account["periods"][period] = {key: index for key, _label, _kind in ACTIVITY_METRICS}

    def snapshot(_session, accounts, *, today):
        assert today == now.astimezone(activity_reports.IST).date()
        for index, account in enumerate(accounts.values(), 1):
            account["current"] = {key: index for key, _label, _kind in SNAPSHOT_METRICS}

    monkeypatch.setattr(activity_reports, "_populate_period_activity", periods)
    monkeypatch.setattr(activity_reports, "_populate_current_snapshot", snapshot)
    with get_session_factory()() as session:
        companies = [_report_account(session, index, kind)[0] for index, kind in enumerate(types)]
        session.commit()
        report = build_activity_report(session, now=now)
        assert {company.company_type for company in companies} == {str(kind) for kind in types}
    assert list(report["segments"]) == ["law_firms", "general_counsels", "solo_lawyers", "other"]
    accounts = [a for segment in report["segments"].values() for a in segment["accounts"]]
    assert len(accounts) == len(types) == len({a["company_id"] for a in accounts})
    assert {a["company_type"] for a in accounts} == {str(kind) for kind in types}
    assert report["segments"]["solo_lawyers"]["company_count"] == 1
    assert report["segments"]["other"]["company_count"] == 2
    for segment in report["segments"].values():
        assert segment["company_count"] == len(segment["accounts"])
        for period in activity_reports.PERIODS:
            for key, _label, _kind in ACTIVITY_METRICS:
                assert segment["periods"][period][key] == sum(
                    a["periods"][period][key] for a in segment["accounts"]
                )
    text, html = render_report(report)
    assert "Solo Lawyers" in html and "Other / Unclassified" in html
    assert f">{len(types)}</strong><span>Total accounts" in html
    for account in accounts:
        assert account["name"] in html and account["name"] in text


@pytest.mark.parametrize("offset,status", [
    (timedelta(days=-30), "recent"),
    (timedelta(days=-30, microseconds=-1), "inactive"),
    (timedelta(hours=-1), "recent"),
    (timedelta(), "recent"),
    (timedelta(microseconds=1), "unknown"),
])
@pytest.mark.parametrize("now_zone", [UTC, activity_reports.IST])
def test_usage_is_rolling_thirty_elapsed_days_through_now(
    client, offset, status, now_zone,
) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC).astimezone(now_zone)
    with get_session_factory()() as session:
        _company, membership = _report_account(session, 1, active=False)
        _activity(session, membership, now + offset)
        session.commit()
        report = build_activity_report(session, now=now)
    account = report["segments"]["solo_lawyers"]["accounts"][0]
    assert account["is_active"] is False
    assert account["usage_status"] == status
    expected = (
        None if status == "unknown"
        else (now + offset).astimezone(activity_reports.IST).isoformat()
    )
    assert account["last_meaningful_activity_at"] == expected
    assert report["activity_window"]["cutoff"] == "2026-09-20T10:00:00+05:30"
    assert report["activity_window"]["as_of"] == report["generated_at"]
    assert report["generated_at"] == "2026-10-20T10:00:00+05:30"
    assert report["activity_window"]["days"] == 30
    assert report["activity_window"]["time_zone"] == "Asia/Kolkata"
    assert report["activity_window"]["basis"] == "successful_human_audit_events"


@pytest.mark.parametrize("action,actor,result", [
    ("matter.created", AuditActorType.SYSTEM, AuditResult.SUCCESS),
    ("matter.created", AuditActorType.SERVICE, AuditResult.SUCCESS),
    ("matter.created", AuditActorType.AGENT, AuditResult.SUCCESS),
    ("matter.created", AuditActorType.HUMAN, AuditResult.DENIED),
    ("matter.created", AuditActorType.HUMAN, AuditResult.FAILED),
    *[(action, AuditActorType.HUMAN, AuditResult.SUCCESS) for action in (
        "case_tracking.poll_run", "case_tracking.update_detected",
        "case_tracking.identity_converged",
        "case_tracking.verification_fixture_refresh", "case_tracking.source_text_backfilled",
        "calendar.sync.succeeded", "calendar.connection.refreshed",
        "calendar.durable_google_calendar_sync.processed", "calendar_event_sync.drift_detected",
        "notification.in_app.created", "mailbox.gmail.webhook_processed",
    )],
])
def test_usage_ignores_background_and_unsuccessful_audits(client, action, actor, result) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    old = now - timedelta(days=31)
    with get_session_factory()() as session:
        _company, membership = _report_account(session, 1)
        _activity(session, membership, old, action="matter.created")
        _activity(session, membership, now, action=action, actor=actor, result=result)
        session.commit()
        account = build_activity_report(session, now=now)["segments"]["solo_lawyers"]["accounts"][0]
    assert account["usage_status"] == "inactive"
    assert account["last_meaningful_activity_at"] == (
        old.astimezone(activity_reports.IST).isoformat()
    )


def test_usage_without_trusted_history_is_unknown_not_inferred_from_rows(client) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    with get_session_factory()() as session:
        company, _membership = _report_account(session, 1)
        _foreign, foreign_membership = _report_account(session, 2)
        session.add(Matter(
            company_id=company.id, title="Historic work", matter_code="OLD-1",
            practice_area="Litigation", forum_level="high_court",
            created_at=now-timedelta(days=90), updated_at=now,
        ))
        _activity(session, foreign_membership, now, company_id=company.id)
        session.add(AuditEvent(
            company_id=company.id, actor_type=AuditActorType.HUMAN,
            actor_membership_id=None, action="matter.created", target_type="matter",
            result=AuditResult.SUCCESS, created_at=now,
        ))
        session.commit()
        report = build_activity_report(session, now=now)
    account = next(
        a for a in report["segments"]["solo_lawyers"]["accounts"] if a["name"] == "Practice 1"
    )
    assert account["current"]["active_matters"] == 1
    assert account["periods"]["till_date"]["matters_created"] == 1
    assert account["usage_status"] == "unknown"
    assert account["last_meaningful_activity_at"] is None


@pytest.mark.parametrize("action", [
    "case_tracking.search", "ip_document.uploaded",
    "calendar.connection.connected", "notification_preferences.user_updated",
    "case_tracking.refresh", "case_tracking.bookmark_created", "mailbox.gmail.imported",
    "mailbox.gmail.watch_started", "mailbox.outlook_candidate.created",
    "domain_outbox.dead_letter.replayed", "calendar_event_sync.drift_reconciliation_decided",
])
def test_successful_human_business_actions_remain_meaningful(client, action) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    with get_session_factory()() as session:
        _company, membership = _report_account(session, 1)
        _activity(session, membership, now, action=action)
        session.commit()
        report = build_activity_report(session, now=now)
    assert report["segments"]["solo_lawyers"]["accounts"][0]["usage_status"] == "recent"


def test_automatic_bookmark_creation_does_not_impersonate_human_engagement(client) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    old = now - timedelta(days=31)
    with get_session_factory()() as session:
        company, membership = _report_account(session, 1)
        matter = Matter(
            company_id=company.id, title="Auto-link fixture", matter_code="AUTO-1",
            practice_area="Litigation", forum_level="high_court",
        )
        session.add(matter)
        session.flush()
        _activity(session, membership, old, action="matter.created")
        _activity(session, membership, now, action="case_tracking.bookmark_created",
                  matter_id=matter.id)
        session.commit()
        report = build_activity_report(session, now=now)
    account = report["segments"]["solo_lawyers"]["accounts"][0]
    assert account["usage_status"] == "inactive"
    assert account["last_meaningful_activity_at"] == (
        old.astimezone(activity_reports.IST).isoformat()
    )


@pytest.mark.parametrize("include_internal_accounts", [False, True])
def test_report_query_budget_does_not_grow_per_account(client, include_internal_accounts) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    with get_session_factory()() as session:
        _company, membership = _report_account(session, 0)
        _activity(session, membership, now)
        session.commit()
        engine = session.get_bind()

        def observed_report():
            statements = []
            clauses = []

            def observe(_connection, _cursor, statement, _parameters, _context, _many):
                statements.append(statement)

            def observe_clause(_connection, clause, _multiparams, _params, _options):
                clauses.append(clause)

            event.listen(engine, "before_cursor_execute", observe)
            event.listen(engine, "before_execute", observe_clause)
            try:
                result = build_activity_report(
                    session, now=now, include_internal_accounts=include_internal_accounts,
                )
            finally:
                event.remove(engine, "before_cursor_execute", observe)
                event.remove(engine, "before_execute", observe_clause)
            assert len(statements) == 58
            assert sum("max(audit_events.created_at)" in sql for sql in statements) == 1
            assert len(clauses) == len(statements)
            assert all(is_read_only_select(clause) for clause in clauses)
            return result

        first = observed_report()
        for index in range(1, 41):
            _company, membership = _report_account(session, index)
            _activity(session, membership, now)
        session.commit()
        second = observed_report()
    assert first["segments"]["solo_lawyers"]["company_count"] == 1
    assert second["segments"]["solo_lawyers"]["company_count"] == 41


def test_usage_aggregate_filters_selected_accounts_despite_heavy_excluded_history(client) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    with get_session_factory()() as session:
        selected, actor = _report_account(session, 1)
        internal, internal_actor = _report_account(session, 2)
        internal.name = "test-legal"
        _activity(session, actor, now - timedelta(days=31))
        for _index in range(512):
            _activity(session, internal_actor, now)
        session.commit()
        selected_id, internal_id = selected.id, internal.id
        statements = []

        def observe(_connection, clause, _multiparams, _params, _options):
            if "max(audit_events.created_at)" in str(clause):
                statements.append(clause)

        engine = session.get_bind()
        event.listen(engine, "before_execute", observe)
        try:
            report = build_activity_report(session, now=now)
        finally:
            event.remove(engine, "before_execute", observe)
    assert len(statements) == 1
    assert is_read_only_select(statements[0])
    compiled = statements[0].compile()
    assert "audit_events.company_id IN" in str(compiled)
    assert compiled.params["company_id_1"] == [selected_id]
    assert internal_id not in compiled.params["company_id_1"]
    account = report["segments"]["solo_lawyers"]["accounts"][0]
    assert account["company_id"] == selected_id and account["usage_status"] == "inactive"
    assert report["excluded_account_count"] == 1


def test_usage_empty_scope_performs_no_query(client, monkeypatch) -> None:
    assert client.app is not None
    with get_session_factory()() as session:
        def forbidden_query(*_args, **_kwargs):
            pytest.fail("Empty account scope must not execute an activity aggregate")

        monkeypatch.setattr(session, "execute", forbidden_query)
        activity_reports._populate_usage(session, {}, now=datetime(2026, 10, 20, tzinfo=UTC))


@pytest.mark.parametrize("action", [
    "new_worker.periodic_completed", "matter.future_automatic_maintenance",
    "calendar.connection.future_refresh",
])
def test_unknown_successful_human_action_does_not_invent_engagement(client, action) -> None:
    assert client.app is not None
    now = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
    with get_session_factory()() as session:
        _company, actor = _report_account(session, 1)
        _activity(session, actor, now, action=action)
        session.commit()
        report = build_activity_report(session, now=now)
    account = report["segments"]["solo_lawyers"]["accounts"][0]
    assert account["usage_status"] == "unknown"
    assert account["last_meaningful_activity_at"] is None


class _EmailText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.disclosures = []
        self.in_details = 0
        self.collapsed_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.disclosures.append(dict(attrs))
            self.in_details += 1

    def handle_endtag(self, tag):
        if tag == "details":
            self.in_details -= 1

    def handle_data(self, data):
        self.text.append(data)
        if self.in_details:
            self.collapsed_text.append(data)


def test_email_collapses_only_known_inactive_and_preserves_complete_fallback() -> None:
    report = _report()
    report["activity_window"] = {
        "days": 30, "cutoff": "2026-06-10T08:00:00+05:30",
        "as_of": report["generated_at"], "time_zone": "Asia/Kolkata",
        "basis": "successful_human_audit_events",
    }
    base = report["segments"]["law_firms"]["accounts"][0]
    for key in ("law_firms", "general_counsels", "solo_lawyers", "other"):
        accounts = []
        for status in ("recent", "inactive", "unknown"):
            account = copy.deepcopy(base)
            account.update(
                name=f"{key} {status} <&>", usage_status=status,
                last_meaningful_activity_at=(
                    None if status == "unknown" else "2026-05-01T08:00:00+05:30"
                ),
            )
            accounts.append(account)
        report["segments"][key] = {
            "company_count": 3, "company_names": [a["name"] for a in accounts],
            "periods": copy.deepcopy(base["periods"]), "accounts": accounts,
        }
    before = copy.deepcopy(report)
    text, html = render_report(report)
    assert report == before
    parsed = _EmailText()
    parsed.feed(html)
    assert len(parsed.disclosures) == 4
    assert all("open" not in attrs for attrs in parsed.disclosures)
    assert html.count("<summary>") == 4
    assert "2026-06-10T08:00:00+05:30" in html and "2026-06-10T08:00:00+05:30" in text
    assert "Usage: Unknown" in text and "No recorded meaningful activity" in html
    assert "<script" not in html and "onclick=" not in html
    assert "display:none" not in html.replace(" ", "")
    fallback = " ".join(parsed.text)  # No disclosure/CSS semantics: all retained text is readable.
    for segment in report["segments"].values():
        for account in segment["accounts"]:
            assert account["name"] in text and account["name"] in fallback
            assert (account["name"] in " ".join(parsed.collapsed_text)) == (
                account["usage_status"] == "inactive"
            )
    assert ">12</strong><span>Total accounts" in html


@pytest.fixture
def report_sender(monkeypatch):
    settings = Settings(
        _env_file=None,
        env="local",
        activity_report_enabled=True,
        sendgrid_api_key="offline-report-key",
        sendgrid_sender_email="sender@example.com",
        sendgrid_sender_name="Offline CaseOps",
    )
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(202, request=httpx.Request("POST", url))

    monkeypatch.setattr(activity_reports, "get_settings", lambda: settings)
    monkeypatch.setattr(activity_reports.httpx, "post", post)
    return settings, calls


def test_sender_uses_one_post_with_four_private_personalizations(report_sender) -> None:
    settings, calls = report_sender
    recipients = [
        "mishra.sanjeev@gmail.com", "sanjeev@orchestrum.in",
        "ram.gupta@edumatica.io", "uday.chauhan@edumatica.io",
    ]
    settings.activity_report_recipient_email = ";".join(recipients)

    assert activity_reports.send_activity_report(_report()) == "sent"

    assert len(calls) == 1
    url, arguments = calls[0]
    assert url == "https://api.sendgrid.com/v3/mail/send"
    assert arguments["timeout"] == 30
    assert arguments["headers"] == {
        "Authorization": "Bearer offline-report-key", "Content-Type": "application/json",
    }
    payload = arguments["json"]
    assert payload["personalizations"] == [
        {"to": [{"email": recipient}]} for recipient in recipients
    ]
    assert "to" not in payload and "cc" not in payload and "bcc" not in payload
    assert payload["from"] == {"email": "sender@example.com", "name": "Offline CaseOps"}
    assert payload["subject"].startswith("CaseOps Account Activity Dashboard - ")
    text, html = render_report(_report())
    assert payload["content"] == [
        {"type": "text/plain", "value": text}, {"type": "text/html", "value": html},
    ]


def test_sender_preserves_legacy_default_recipient(report_sender) -> None:
    settings, calls = report_sender
    assert settings.activity_report_recipient_email == "mishra.sanjeev@gmail.com"
    assert activity_reports.send_activity_report(_report()) == "sent"
    assert calls[0][1]["json"]["personalizations"] == [
        {"to": [{"email": "mishra.sanjeev@gmail.com"}]},
    ]
    assert len(calls) == 1


def test_sender_trims_and_deduplicates_in_first_seen_order_without_dns(
    report_sender, monkeypatch,
) -> None:
    settings, calls = report_sender

    def forbidden_dns(*_args, **_kwargs):
        pytest.fail("Recipient syntax validation must not perform DNS checks")

    monkeypatch.setattr(deliverability, "validate_email_deliverability", forbidden_dns)
    settings.activity_report_recipient_email = (
        " First@EXAMPLE.COM ; second@example.com ;first@example.com;"
        "third@example.com;fourth@example.com;SECOND@example.com "
    )
    normalized = Settings(
        _env_file=None, env="local",
        activity_report_recipient_email=settings.activity_report_recipient_email,
    )
    assert normalized.activity_report_recipient_email == (
        "First@example.com;second@example.com;third@example.com;fourth@example.com"
    )
    assert activity_reports.send_activity_report(_report()) == "sent"
    assert calls[0][1]["json"]["personalizations"] == [
        {"to": [{"email": recipient}]} for recipient in (
            "First@example.com", "second@example.com", "third@example.com", "fourth@example.com",
        )
    ]
    assert len(calls) == 1


@pytest.mark.parametrize("recipients", [
    pytest.param("", id="empty"),
    pytest.param("   ", id="spaces-only"),
    pytest.param(";one@example.com", id="leading-empty"),
    pytest.param("one@example.com;", id="trailing-empty"),
    pytest.param("one@example.com;;two@example.com", id="middle-empty"),
    pytest.param("one@example.com,two@example.com", id="comma-list"),
    pytest.param("Operator <one@example.com>", id="display-name"),
    pytest.param("<one@example.com>", id="angle-address"),
    pytest.param("one@example.com\r\nBcc: other@example.com", id="header-injection"),
    pytest.param("\tone@example.com", id="control-tab"),
    pytest.param("one@example.com\x00", id="control-nul"),
    pytest.param("one@example.com\u0085", id="control-c1"),
    pytest.param("one@example.com\u200b", id="control-format"),
    pytest.param("one@example.com\u2028", id="line-separator"),
    pytest.param("one@example.com\u2029", id="paragraph-separator"),
    pytest.param("not-an-email", id="invalid-address"),
    pytest.param("one@localhost", id="invalid-domain"),
    pytest.param(";".join(f"user{i}@example.com" for i in range(5)), id="five-unique"),
    pytest.param("x" * 1025, id="raw-input-bound"),
])
def test_sender_rejects_invalid_settings_before_transport(report_sender, recipients) -> None:
    settings, calls = report_sender
    with pytest.raises(ValueError):
        Settings(_env_file=None, env="local", activity_report_recipient_email=recipients)
    # Defend the transport boundary even when a test/operator mutates cached settings.
    settings.activity_report_recipient_email = recipients
    with pytest.raises(ValueError, match="^Invalid activity report recipients\\.$"):
        activity_reports.send_activity_report(_report())
    assert calls == []


def test_disabled_report_never_sends(report_sender) -> None:
    settings, calls = report_sender
    settings.activity_report_enabled = False
    settings.activity_report_recipient_email = "invalid"
    assert activity_reports.send_activity_report(_report()) == "disabled"
    assert calls == []


@pytest.mark.parametrize("missing", ["sendgrid_api_key", "sendgrid_sender_email"])
def test_sender_rejects_missing_configuration_without_transport(report_sender, missing) -> None:
    settings, calls = report_sender
    setattr(settings, missing, None)
    with pytest.raises(RuntimeError, match="SendGrid is not configured"):
        activity_reports.send_activity_report(_report())
    assert calls == []


@pytest.mark.parametrize("status", [400, 429, 500])
def test_sender_preserves_provider_rejection_without_retry(
    report_sender, monkeypatch, status,
) -> None:
    _settings, calls = report_sender

    def rejected(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(activity_reports.httpx, "post", rejected)
    with pytest.raises(httpx.HTTPStatusError):
        activity_reports.send_activity_report(_report())
    assert len(calls) == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_sender_preserves_uncertain_transport_failure_without_retry(
    report_sender, monkeypatch, error,
) -> None:
    _settings, calls = report_sender

    def failed(url, **kwargs):
        calls.append((url, kwargs))
        raise error("offline transport failure", request=httpx.Request("POST", url))

    monkeypatch.setattr(activity_reports.httpx, "post", failed)
    with pytest.raises(error):
        activity_reports.send_activity_report(_report())
    assert len(calls) == 1
