"""Issue #513 / J19/M21/US-063, J14/M14/US-040/042: one durable public lead,
worker-owned notification, observable failure and manager readback on SQLite
and PostgreSQL.

Human (unmarked) admissions use the real SendGrid adapter with ``httpx.post``
replaced and every other HTTP transport denied, so no socket is opened.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingEnrollment
from caseops_api.db.session import get_session_factory
from caseops_api.services import billing_demo as demo
from tests import test_platform_console as console_cases
from tests.test_auth_company import auth_headers

URL = "/api/billing/enrollments/demo-request"
LEADS = "/api/platform-console/leads"
SENDGRID = "https://api.sendgrid.com/v3/mail/send"
NOW = datetime(2030, 3, 4, 9, tzinfo=UTC)
PII = (
    "Issue Contact Sentinel",
    "issue513-contact@example.com",
    "Issue Organisation Sentinel",
    "Issue notes sentinel",
    "private-provider-response-sentinel",
)
BACKENDS = ["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]


def _payload(source, intent, *, segment="solo", role="solo_advocate", plan=None, **changes):
    return {
        "idempotency_key": str(uuid4()),
        "contact_name": PII[0],
        "contact_email": PII[1],
        "company_name": PII[2],
        "segment": segment,
        "role": role,
        "intent": intent,
        "source": source,
        "selected_plan": plan,
        "notes": PII[3],
        "privacy_notice_version": "2026-10-21",
        **changes,
    }


def _human(client):
    # The PostgreSQL client marks every request as automated. A real visitor
    # sends no marker, so drop it; the fake transport below still owns all HTTP.
    client.headers.pop("X-CaseOps-Automated-Test", None)
    return client


def _install_mail(monkeypatch):
    mail = SimpleNamespace(calls=[], outcomes=[])
    monkeypatch.delenv("CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL", raising=False)
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "offline-issue513-key")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "sender@example.com")
    monkeypatch.setenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_DEMO_RETENTION_ENABLED", "false")
    get_settings.cache_clear()
    previous = httpx.post

    def post(url, **kwargs):
        if url != SENDGRID:
            return previous(url, **kwargs)
        mail.calls.append(kwargs["json"])
        outcome = mail.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, text="private-provider-response-sentinel")

    def deny(*_args, **_kwargs):
        raise AssertionError("Unmocked HTTP transport in the issue 513 fixture")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(httpx, "post", post)
    return mail


@pytest.fixture
def demo_log(caplog):
    # Alembic's fileConfig in the session migration fixtures disables loggers
    # that already exist, which would make every log assertion vacuous. Enable
    # the service logger and attach caplog directly for this test only.
    was_disabled = demo.logger.disabled
    demo.logger.disabled = False
    demo.logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=demo.logger.name):
            yield caplog
    finally:
        demo.logger.removeHandler(caplog.handler)
        demo.logger.disabled = was_disabled


@pytest.fixture
def clock(monkeypatch):
    value = [NOW]
    monkeypatch.setattr(demo, "_now", lambda: value[0])
    return value


@pytest.fixture(params=BACKENDS)
def lead_client(request, monkeypatch, clock):
    client = _human(request.getfixturevalue(request.param))
    yield client, _install_mail(monkeypatch)
    get_settings.cache_clear()


@pytest.fixture(params=BACKENDS)
def lead_console(request, monkeypatch, clock):
    client = request.getfixturevalue(request.param)
    data = console_cases.provision_report_console(client, monkeypatch)
    _human(client)
    data["mail"] = _install_mail(monkeypatch)
    yield data
    get_settings.cache_clear()


def _state(identity):
    with get_session_factory()() as session:
        return demo._state(session.get(BillingEnrollment, identity))


def _change(identity, **changes):
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        state = demo._state(row)
        state.update(changes)
        demo._save(row, state)
        session.commit()


def _public_lead_count():
    with get_session_factory()() as session:
        return session.scalar(
            select(func.count())
            .select_from(BillingEnrollment)
            .where(BillingEnrollment.is_public_lead.is_(True))
        )


def _undelivered(caplog):
    # Propagation may also deliver a record to caplog; count each record once.
    return list(
        {
            id(record): record
            for record in caplog.records
            if record.name == demo.logger.name
            and record.getMessage().startswith("Public lead alert not delivered:")
        }.values()
    )


def test_issue513_landing_and_pricing_leads_survive_smtp_timeout_into_manager_readback(
    lead_console, clock, demo_log
):
    caplog = demo_log
    client, mail = lead_console["client"], lead_console["mail"]
    landing = _payload("homepage", "demo")
    pricing = _payload(
        "pricing_page", "pricing", segment="firm", role="partner", plan="firm-annual"
    )

    first = client.post(URL, json=landing)
    clock[0] = NOW + timedelta(seconds=1)
    second = client.post(URL, json=pricing)
    assert first.status_code == second.status_code == 200
    assert first.json() == {"id": landing["idempotency_key"], "status": "demo_requested"}
    assert second.json() == {"id": pricing["idempotency_key"], "status": "demo_requested"}
    # Acknowledgement follows the durable commit; HTTP never performs transport.
    assert mail.calls == []
    for identity in (landing["idempotency_key"], pricing["idempotency_key"]):
        state = _state(identity)
        assert state["notification_status"] == "pending" and state["attempts"] == 0
        assert state["notification_eligible"] is True and state["automated_request"] is False

    # A double submit of the same key returns the original lead; changed
    # details under that key and invalid input never create another record.
    assert client.post(URL, json=landing).json() == first.json()
    assert client.post(URL, json=pricing).json() == second.json()
    assert client.post(URL, json={**pricing, "role": "associate"}).status_code == 409
    invalid = client.post(URL, json=_payload("homepage", "demo", contact_email="bad"))
    assert invalid.status_code == 422
    assert _public_lead_count() == 2
    assert mail.calls == []

    # The scheduled worker owns delivery: the landing alert is accepted and the
    # pricing alert times out at the provider boundary.
    clock[0] = NOW + timedelta(seconds=2)
    mail.outcomes = [202, httpx.ReadTimeout(PII[4])]
    assert demo.drain_demo_notifications() == {"selected": 2}
    assert len(mail.calls) == 2
    for call in mail.calls:
        assert call["personalizations"][0]["to"] == [{"email": demo.NOTIFICATION_RECIPIENT}]
        assert not any(value in json.dumps(call) for value in PII)
    landed, timed_out = _state(landing["idempotency_key"]), _state(pricing["idempotency_key"])
    assert (landed["notification_status"], landed.get("last_error_code")) == ("sent", None)
    assert timed_out["notification_status"] == "outcome_unknown"
    assert timed_out["last_error_code"] == "transport_outcome_unknown"
    assert timed_out["attempts"] == 1

    failures = _undelivered(caplog)
    assert [record.getMessage() for record in failures] == [
        f"Public lead alert not delivered: lead={pricing['idempotency_key']} "
        "status=outcome_unknown error=transport_outcome_unknown"
    ]
    assert failures[0].enrollment_id == pricing["idempotency_key"]
    assert not any(value in caplog.text for value in PII)

    # An uncertain send is never blindly repeated by later worker runs.
    clock[0] = NOW + timedelta(hours=3)
    assert demo.drain_demo_notifications() == {"selected": 0}
    assert len(mail.calls) == 2

    # Lead PII stays behind the MFA-complete manager session.
    tenant = client.get(LEADS, headers=auth_headers(lead_console["tenant"]["access_token"]))
    assert tenant.status_code in {401, 403}
    assert PII[1] not in tenant.text
    console_cases._manager(lead_console)
    newest = client.get(LEADS, params={"limit": 1})
    assert newest.status_code == 200, newest.text
    assert newest.json()["has_more"] is True
    oldest = client.get(LEADS, params={"limit": 1, "cursor": newest.json()["next_cursor"]})
    assert oldest.status_code == 200, oldest.text
    assert oldest.json()["has_more"] is False and oldest.json()["next_cursor"] is None
    (pricing_row,), (landing_row,) = newest.json()["items"], oldest.json()["items"]
    for row, sent in ((pricing_row, pricing), (landing_row, landing)):
        assert row["id"] == sent["idempotency_key"]
        assert {
            key: row[key]
            for key in (
                "contact_name",
                "contact_email",
                "company_name",
                "segment",
                "selected_plan",
                "source",
                "role",
                "intent",
                "notes",
                "privacy_notice_version",
            )
        } == {
            key: sent[key]
            for key in (
                "contact_name",
                "contact_email",
                "company_name",
                "segment",
                "selected_plan",
                "source",
                "role",
                "intent",
                "notes",
                "privacy_notice_version",
            )
        }
    assert datetime.fromisoformat(pricing_row["submitted_at"]) == NOW + timedelta(seconds=1)
    assert datetime.fromisoformat(landing_row["submitted_at"]) == NOW
    assert pricing_row["notification"] == {
        "status": "outcome_unknown",
        "attempts": 1,
        "last_error_code": "transport_outcome_unknown",
        "eligible": True,
    }
    assert landing_row["notification"] == {
        "status": "accepted",
        "attempts": 1,
        "last_error_code": None,
        "eligible": True,
    }


@pytest.mark.parametrize(
    ("case", "status", "error"),
    [
        ("rejected", "exhausted", "provider_rejected"),
        ("unavailable", "outcome_unknown", "transport_outcome_unknown"),
        ("timeout", "outcome_unknown", "transport_outcome_unknown"),
        ("rate_limited", "retry_pending", "provider_rate_limited"),
        ("rate_limited_last_attempt", "exhausted", "provider_rate_limited"),
        ("claim_expired", "outcome_unknown", "claim_expired"),
        ("attempt_limit", "exhausted", "attempt_limit"),
        ("accepted", "sent", None),
    ],
)
def test_issue513_every_undelivered_outcome_is_logged_by_reference_only(
    lead_client, clock, demo_log, case, status, error
):
    caplog = demo_log
    client, mail = lead_client
    response = client.post(URL, json=_payload("homepage", "demo"))
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    outcome = {
        "rejected": 400,
        "unavailable": 503,
        "timeout": httpx.ConnectTimeout(PII[4]),
        "rate_limited": 429,
        "rate_limited_last_attempt": 429,
        "accepted": 202,
    }.get(case)
    mail.outcomes = [] if outcome is None else [outcome]
    if case == "rate_limited_last_attempt":
        _change(identity, attempts=demo.MAX_ATTEMPTS - 1)
    elif case == "attempt_limit":
        _change(identity, attempts=demo.MAX_ATTEMPTS)
    elif case == "claim_expired":
        _change(
            identity,
            notification_status="sending",
            claim="interrupted-issue513-claim",
            lease_until=(NOW - timedelta(seconds=1)).isoformat(),
            attempts=1,
        )

    demo.deliver_demo_notification(identity)

    state = _state(identity)
    assert state["notification_status"] == status
    assert state.get("last_error_code") == error
    assert len(mail.calls) == (0 if outcome is None else 1)
    failures = _undelivered(caplog)
    if error is None:
        assert failures == []
    else:
        assert [record.getMessage() for record in failures] == [
            f"Public lead alert not delivered: lead={identity} status={status} error={error}"
        ]
        assert (
            failures[0].enrollment_id,
            failures[0].notification_status,
            failures[0].error_code,
        ) == (identity, status, error)
    assert not any(value in caplog.text for value in PII)
    # The lead itself is retained whatever happened to its alert.
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        assert row.is_public_lead is True and row.contact_email == PII[1]
