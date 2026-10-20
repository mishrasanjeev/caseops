from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from email_validator import deliverability

from caseops_api.core.settings import Settings
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
from caseops_api.services import activity_reports
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
