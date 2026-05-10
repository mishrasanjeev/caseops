"""BUG-038 (Hari 2026-05-09) — tenant-scoped email suppression.

Covers:
- apply_sendgrid_event (HearingReminder) writes a suppression row on
  bounce/dropped/spamreport AND on unsubscribe/group_unsubscribe.
- apply_sendgrid_communication_event (Communication) writes the same.
- is_suppressed is tenant-isolated: a suppression in tenant A does
  not block sends in tenant B.
- record_suppression is idempotent — re-applying the same event for
  the same (company_id, recipient_email) refreshes last_event_at /
  reason / source_message_id without creating a duplicate row.
- run_reminder_worker cancels QUEUED rows whose recipient address is
  suppressed, instead of paying SendGrid for a known-failed send.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    EmailSuppression,
    EmailSuppressionReason,
    HearingReminder,
    HearingReminderChannel,
    HearingReminderStatus,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.communications import (
    apply_sendgrid_communication_event,
)
from caseops_api.services.email_suppression import (
    is_suppressed,
    reason_for_event,
    record_suppression,
)
from caseops_api.services.hearing_reminders import (
    apply_sendgrid_event,
    run_reminder_worker,
)


def _bootstrap(client: TestClient, *, slug: str) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Suppression Owner",
            "owner_email": f"owner-{slug}@example.com",
            "owner_password": "OwnerPass1234!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _insert_reminder(
    session, *, company_id: str, matter_id: str, hearing_id: str,
    recipient_email: str = "h@example.com",
    provider_message_id: str | None = "MSG-suppression-1",
    status: str = HearingReminderStatus.SENT,
) -> str:
    r = HearingReminder(
        company_id=company_id,
        matter_id=matter_id,
        hearing_id=hearing_id,
        recipient_email=recipient_email,
        channel=HearingReminderChannel.EMAIL,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
        status=status,
        provider="sendgrid",
        provider_message_id=provider_message_id,
        sent_at=datetime.now(UTC) - timedelta(minutes=4),
    )
    session.add(r)
    session.commit()
    return r.id


def _make_matter_with_hearing(
    client: TestClient, owner_token: str
) -> tuple[str, str, str]:
    """Bootstrap helper: returns (company_id, matter_id, hearing_id)."""
    from tests.test_hearing_reminders import (
        _mk_hearing_via_api,
        _mk_matter,
    )

    matter = _mk_matter(client, owner_token, "Sup-1")
    matter_id = matter["id"]
    hearing = _mk_hearing_via_api(
        client, owner_token, matter_id, days_ahead=7
    )
    hearing_id = hearing["id"]
    factory = get_session_factory()
    with factory() as session:
        from caseops_api.db.models import MatterHearing

        h = session.scalar(select(MatterHearing).where(MatterHearing.id == hearing_id))
        assert h is not None
        return h.matter.company_id, matter_id, hearing_id


def test_apply_sendgrid_event_writes_suppression_on_bounce(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="sup-bounce")
    owner_token = str(boot["access_token"])
    company_id, matter_id, hearing_id = _make_matter_with_hearing(
        client, owner_token
    )

    factory = get_session_factory()
    with factory() as session:
        _insert_reminder(
            session,
            company_id=company_id,
            matter_id=matter_id,
            hearing_id=hearing_id,
            recipient_email="bouncer@example.com",
            provider_message_id="MSG-BOUNCE-001",
        )

    bounce_event = {
        "sg_message_id": "MSG-BOUNCE-001.filterdrecvN",
        "event": "bounce",
        "email": "bouncer@example.com",
        "reason": "550 mailbox does not exist",
        "timestamp": int(datetime.now(UTC).timestamp()),
    }
    with factory() as session:
        result = apply_sendgrid_event(session, event=bounce_event)
        session.commit()
        assert result is True

        row = session.scalar(
            select(EmailSuppression).where(
                EmailSuppression.company_id == company_id,
                EmailSuppression.recipient_email == "bouncer@example.com",
            )
        )
        assert row is not None
        assert row.reason == EmailSuppressionReason.BOUNCE.value
        assert row.detail and "mailbox does not exist" in row.detail
        assert row.source_message_id == "MSG-BOUNCE-001.filterdrecvN"


@pytest.mark.parametrize(
    "event_name,expected_reason",
    [
        ("dropped", EmailSuppressionReason.DROPPED),
        ("spamreport", EmailSuppressionReason.SPAM_REPORT),
        ("unsubscribe", EmailSuppressionReason.UNSUBSCRIBE),
        ("group_unsubscribe", EmailSuppressionReason.GROUP_UNSUBSCRIBE),
    ],
)
def test_apply_sendgrid_event_writes_suppression_for_each_reason(
    client: TestClient,
    event_name: str,
    expected_reason: EmailSuppressionReason,
) -> None:
    """BUG-038: explicit handling for every event type the user listed
    (dropped / spam_report / unsubscribe / group_unsubscribe).
    `bounce` is covered by the dedicated test above."""
    slug = f"sup-{event_name.replace('_', '')}"
    boot = _bootstrap(client, slug=slug)
    owner_token = str(boot["access_token"])
    company_id, matter_id, hearing_id = _make_matter_with_hearing(
        client, owner_token
    )

    factory = get_session_factory()
    msg_id = f"MSG-{event_name.upper()}-001"
    address = f"{event_name}@example.com"
    with factory() as session:
        _insert_reminder(
            session,
            company_id=company_id,
            matter_id=matter_id,
            hearing_id=hearing_id,
            recipient_email=address,
            provider_message_id=msg_id,
        )

    event = {
        "sg_message_id": f"{msg_id}.fdN",
        "event": event_name,
        "email": address,
        "timestamp": int(datetime.now(UTC).timestamp()),
    }
    with factory() as session:
        apply_sendgrid_event(session, event=event)
        session.commit()
        row = session.scalar(
            select(EmailSuppression).where(
                EmailSuppression.company_id == company_id,
                EmailSuppression.recipient_email == address,
            )
        )
        assert row is not None
        assert row.reason == expected_reason.value


def test_apply_sendgrid_communication_event_writes_suppression_on_bounce(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="sup-comm")
    owner_token = str(boot["access_token"])
    company_id, _, _ = _make_matter_with_hearing(client, owner_token)

    factory = get_session_factory()
    with factory() as session:
        from caseops_api.db.models import (
            Communication,
            CommunicationChannel,
            CommunicationDirection,
            CommunicationStatus,
        )

        comm = Communication(
            company_id=company_id,
            matter_id=None,
            client_id=None,
            direction=CommunicationDirection.OUTBOUND,
            channel=CommunicationChannel.EMAIL,
            subject="Test",
            body="Test body",
            recipient_name=None,
            recipient_email="comm@example.com",
            status=CommunicationStatus.SENT,
            occurred_at=datetime.now(UTC),
            external_message_id="COMM-MSG-001",
        )
        session.add(comm)
        session.commit()

    event = {
        "sg_message_id": "COMM-MSG-001.fdN",
        "event": "bounce",
        "email": "comm@example.com",
        "reason": "550 user unknown",
        "timestamp": int(datetime.now(UTC).timestamp()),
    }
    with factory() as session:
        apply_sendgrid_communication_event(session, event=event)
        session.commit()
        row = session.scalar(
            select(EmailSuppression).where(
                EmailSuppression.company_id == company_id,
                EmailSuppression.recipient_email == "comm@example.com",
            )
        )
        assert row is not None
        assert row.reason == EmailSuppressionReason.BOUNCE.value


def test_record_suppression_is_idempotent_and_refreshes_last_event_at(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="sup-idem")
    company_id = boot["company"]["id"]
    factory = get_session_factory()
    with factory() as session:
        first = record_suppression(
            session,
            company_id=company_id,
            recipient_email="repeat@example.com",
            reason=EmailSuppressionReason.BOUNCE,
            detail="initial",
            source_message_id="MSG-FIRST",
        )
        session.commit()
        first_at = first.last_event_at
        original_id = first.id

    with factory() as session:
        second = record_suppression(
            session,
            company_id=company_id,
            recipient_email="repeat@example.com",
            reason=EmailSuppressionReason.UNSUBSCRIBE,
            detail="now they unsubscribed too",
            source_message_id="MSG-SECOND",
        )
        session.commit()
        # Same row, fresh fields.
        assert second.id == original_id
        assert second.reason == EmailSuppressionReason.UNSUBSCRIBE.value
        assert second.detail == "now they unsubscribed too"
        assert second.source_message_id == "MSG-SECOND"
        assert second.last_event_at >= first_at

    # No duplicate rows.
    with factory() as session:
        rows = list(
            session.scalars(
                select(EmailSuppression).where(
                    EmailSuppression.company_id == company_id,
                    EmailSuppression.recipient_email == "repeat@example.com",
                )
            )
        )
        assert len(rows) == 1


def test_is_suppressed_is_tenant_isolated(client: TestClient) -> None:
    """A bounce in tenant A must not block sends in tenant B."""
    boot_a = _bootstrap(client, slug="sup-ten-a")
    boot_b = _bootstrap(client, slug="sup-ten-b")
    factory = get_session_factory()
    with factory() as session:
        record_suppression(
            session,
            company_id=boot_a["company"]["id"],
            recipient_email="shared@example.com",
            reason=EmailSuppressionReason.BOUNCE,
        )
        session.commit()

    with factory() as session:
        # Tenant A sees the suppression.
        sup_a = is_suppressed(
            session,
            company_id=boot_a["company"]["id"],
            recipient_email="shared@example.com",
        )
        assert sup_a is not None
        # Tenant B does NOT — same address, different tenant.
        sup_b = is_suppressed(
            session,
            company_id=boot_b["company"]["id"],
            recipient_email="shared@example.com",
        )
        assert sup_b is None


def test_reason_for_event_handles_known_and_ignores_unknown() -> None:
    assert reason_for_event("bounce") == EmailSuppressionReason.BOUNCE
    assert reason_for_event("DROPPED") == EmailSuppressionReason.DROPPED
    assert reason_for_event("spamreport") == EmailSuppressionReason.SPAM_REPORT
    assert reason_for_event("spam_report") == EmailSuppressionReason.SPAM_REPORT
    assert reason_for_event("unsubscribe") == EmailSuppressionReason.UNSUBSCRIBE
    assert (
        reason_for_event("group_unsubscribe")
        == EmailSuppressionReason.GROUP_UNSUBSCRIBE
    )
    # Anything else (delivered, open, click, processed, deferred) is None
    # — not a suppression-producing event.
    assert reason_for_event("delivered") is None
    assert reason_for_event("open") is None
    assert reason_for_event("click") is None
    assert reason_for_event("") is None


def test_auth_flow_mailers_bypass_suppression(client: TestClient) -> None:
    """BUG-038 regression guard: account-setup, password-reset, and
    portal-access mail must NOT consult ``is_suppressed``. A user who
    unsubscribed from matter mail in this tenant must still be able
    to complete password reset, set up their account, and authenticate
    into the portal.

    This test pre-populates an ``email_suppressions`` row for an
    address, then exercises the two endpoints that fan out into
    ``employee_mailer.send_employee_account_link``:

    1. ``POST /api/companies/current/employees`` — creates an
       employee at the suppressed address; the request must succeed
       (200) and a setup token must be issued. If a future change
       wires ``is_suppressed`` into ``employee_mailer``, the create
       call would 4xx (or 200 with a suppression-laced error in the
       audit) and this test breaks.
    2. ``POST /api/auth/password-reset/start`` — anti-enumeration
       returns ``delivered=true`` regardless of account existence;
       the test asserts that contract holds AND that the underlying
       token is issued (debug_token populated in test env) for the
       previously-created employee at the suppressed address.

    The point isn't to prove the mail was sent — in a test env
    ``send_employee_account_link`` returns False with ``"non-prod"``
    by design. The point is to prove that the suppression check is
    NOT silently locking auth-flow mail.
    """
    boot = _bootstrap(client, slug="sup-authbypass")
    owner_token = str(boot["access_token"])
    suppressed_address = "pre-suppressed@example.com"

    # Pre-populate the suppression row for this tenant before any
    # auth-flow mail is attempted.
    factory = get_session_factory()
    with factory() as session:
        record_suppression(
            session,
            company_id=boot["company"]["id"],
            recipient_email=suppressed_address,
            reason=EmailSuppressionReason.UNSUBSCRIBE,
            detail="user opted out of matter mail",
        )
        session.commit()

    # 1. Employee create at the suppressed address. Must succeed.
    from tests.test_auth_company import auth_headers

    create_resp = client.post(
        "/api/companies/current/employees",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Pre Suppressed Employee",
            "email": suppressed_address,
            "role": "member",
            "mobile": "+91-9000000001",
            "designation": "Associate",
            "department": "Litigation",
            "employee_code": "PRE-SUP-1",
            "joined_on": "2026-05-09",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    body = create_resp.json()
    # Token MUST have been issued — proves the auth-flow code did
    # not short-circuit on suppression.
    assert body.get("setup", {}).get("debug_token"), (
        "account_setup token was not issued; auth-flow mailer may have "
        "been blocked by suppression"
    )

    # 2. Password-reset-start at the same suppressed address. Must
    # also succeed and issue a token.
    reset_resp = client.post(
        "/api/auth/password-reset/start",
        json={
            "company_slug": "sup-authbypass",
            "email": suppressed_address,
        },
    )
    assert reset_resp.status_code == 200, reset_resp.text
    reset_body = reset_resp.json()
    assert reset_body["delivered"] is True
    assert reset_body.get("debug_token"), (
        "password_reset token was not issued for a pre-suppressed "
        "address; auth-flow mailer may have been blocked by suppression"
    )


def test_run_reminder_worker_cancels_suppressed_rows(
    client: TestClient,
) -> None:
    """BUG-038: the worker must skip rows whose recipient is suppressed
    in the same tenant. Marks them CANCELLED with an actionable
    last_error and counts them in `report["suppressed"]` so the
    operator dashboard surfaces the skip rather than silently failing."""
    os.environ["CASEOPS_HEARING_REMINDERS_ENABLED"] = "true"
    os.environ["CASEOPS_SENDGRID_API_KEY"] = "SG.fake"
    os.environ["CASEOPS_SENDGRID_SENDER_EMAIL"] = "hearings@caseops.ai"
    try:
        boot = _bootstrap(client, slug="sup-worker")
        owner_token = str(boot["access_token"])
        company_id, matter_id, hearing_id = _make_matter_with_hearing(
            client, owner_token
        )

        factory = get_session_factory()
        with factory() as session:
            record_suppression(
                session,
                company_id=company_id,
                recipient_email="known-bounce@example.com",
                reason=EmailSuppressionReason.BOUNCE,
                detail="prior bounce",
            )
            session.commit()

        with factory() as session:
            row_id = _insert_reminder(
                session,
                company_id=company_id,
                matter_id=matter_id,
                hearing_id=hearing_id,
                recipient_email="known-bounce@example.com",
                provider_message_id=None,
                status=HearingReminderStatus.QUEUED,
            )

        with factory() as session:
            from caseops_api.core.settings import get_settings

            get_settings.cache_clear()  # type: ignore[attr-defined]
            report = run_reminder_worker(session)
            session.commit()

        assert report["suppressed"] == 1
        assert report["sent"] == 0

        with factory() as session:
            r = session.get(HearingReminder, row_id)
            assert r is not None
            assert r.status == HearingReminderStatus.CANCELLED
            assert r.last_error and "suppressed" in r.last_error
    finally:
        for k in (
            "CASEOPS_HEARING_REMINDERS_ENABLED",
            "CASEOPS_SENDGRID_API_KEY",
            "CASEOPS_SENDGRID_SENDER_EMAIL",
        ):
            os.environ.pop(k, None)
