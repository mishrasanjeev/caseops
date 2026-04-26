"""MOD-TS-007 (2026-04-26) — channel-breadth tests for the hearing
reminder worker.

Covers SMS via Twilio + WhatsApp routing:

- SMS row dispatches through the Twilio adapter when
  CASEOPS_TWILIO_ENABLED + creds are set.
- SMS row stays QUEUED with an actionable last_error when the gate
  is off (default deploy never burns money on a test SMS).
- WhatsApp row stays QUEUED pointing at Meta-template setup
  (default off; needs per-deployment template approval).
- SMS row with NULL recipient_phone fails fast with the
  skipped_missing_phone counter.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    HearingReminder,
    HearingReminderChannel,
    HearingReminderStatus,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.hearing_reminders import run_reminder_worker
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_hearing_reminders import (
    _force_due,
    _mk_hearing_via_api,
    _mk_matter,
)


def _mk_sms_reminder(
    session, *, hearing_id, matter_id, company_id,
    recipient_phone="+919999999999",
):
    """Insert one SMS-channel reminder row pre-due. The default
    schedule_reminders only emits EMAIL rows; we craft SMS rows
    directly so the dispatcher's channel routing is exercised."""
    r = HearingReminder(
        company_id=company_id,
        matter_id=matter_id,
        hearing_id=hearing_id,
        recipient_email=None,
        recipient_phone=recipient_phone,
        channel=HearingReminderChannel.SMS,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
        status=HearingReminderStatus.QUEUED,
    )
    session.add(r)
    session.commit()
    return r.id


def _mk_whatsapp_reminder(
    session, *, hearing_id, matter_id, company_id,
    recipient_phone="+919999999999",
):
    r = HearingReminder(
        company_id=company_id,
        matter_id=matter_id,
        hearing_id=hearing_id,
        recipient_email=None,
        recipient_phone=recipient_phone,
        channel=HearingReminderChannel.WHATSAPP,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
        status=HearingReminderStatus.QUEUED,
    )
    session.add(r)
    session.commit()
    return r.id


def test_sms_row_dispatches_through_twilio_when_enabled(
    client: TestClient,
) -> None:
    """CASEOPS_TWILIO_ENABLED + creds set → worker calls Twilio
    Messages API and marks the row SENT with provider='twilio'."""
    os.environ["CASEOPS_HEARING_REMINDERS_ENABLED"] = "true"
    os.environ["CASEOPS_SENDGRID_API_KEY"] = "SG.fake"
    os.environ["CASEOPS_SENDGRID_SENDER_EMAIL"] = "hearings@caseops.ai"
    os.environ["CASEOPS_TWILIO_ENABLED"] = "true"
    os.environ["CASEOPS_TWILIO_ACCOUNT_SID"] = "ACfaketestSid"
    os.environ["CASEOPS_TWILIO_AUTH_TOKEN"] = "fake-token"
    os.environ["CASEOPS_TWILIO_FROM_NUMBER"] = "+15555550000"
    get_settings.cache_clear()

    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter = _mk_matter(client, token, code="SMS-LIVE")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)

    class _FakeTwilioResponse:
        status_code = 201
        headers = {}
        text = ""

        def json(self):
            return {"sid": "SMtest123"}

    try:
        factory = get_session_factory()
        with factory() as session:
            sms_id = _mk_sms_reminder(
                session, hearing_id=hearing["id"],
                matter_id=matter["id"], company_id=company_id,
            )
            _force_due(session, hearing["id"])

            import httpx
            with patch.object(
                httpx, "post", return_value=_FakeTwilioResponse(),
            ):
                report = run_reminder_worker(session, mode="auto")

        assert report["sms_provider_configured"] is True
        with factory() as session:
            row = session.get(HearingReminder, sms_id)
        assert row.status == HearingReminderStatus.SENT
        assert row.provider == "twilio"
        assert row.provider_message_id == "SMtest123"
    finally:
        for key in (
            "CASEOPS_HEARING_REMINDERS_ENABLED",
            "CASEOPS_SENDGRID_API_KEY",
            "CASEOPS_SENDGRID_SENDER_EMAIL",
            "CASEOPS_TWILIO_ENABLED",
            "CASEOPS_TWILIO_ACCOUNT_SID",
            "CASEOPS_TWILIO_AUTH_TOKEN",
            "CASEOPS_TWILIO_FROM_NUMBER",
        ):
            os.environ.pop(key, None)
        get_settings.cache_clear()


def test_sms_row_stays_queued_with_actionable_error_when_twilio_disabled(
    client: TestClient,
) -> None:
    """Default deployment: CASEOPS_TWILIO_ENABLED=false → SMS rows
    NEVER fail and NEVER send. They stay QUEUED with last_error
    pointing the operator at the env vars to set."""
    os.environ["CASEOPS_HEARING_REMINDERS_ENABLED"] = "true"
    os.environ["CASEOPS_SENDGRID_API_KEY"] = "SG.fake"
    os.environ["CASEOPS_SENDGRID_SENDER_EMAIL"] = "hearings@caseops.ai"
    os.environ.pop("CASEOPS_TWILIO_ENABLED", None)
    get_settings.cache_clear()

    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter = _mk_matter(client, token, code="SMS-OFF")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)

    try:
        factory = get_session_factory()
        with factory() as session:
            sms_id = _mk_sms_reminder(
                session, hearing_id=hearing["id"],
                matter_id=matter["id"], company_id=company_id,
            )
            report = run_reminder_worker(session, mode="auto")

        assert report["sms_provider_configured"] is False
        assert report["skipped_provider_disabled"] >= 1

        with factory() as session:
            row = session.get(HearingReminder, sms_id)
        assert row.status == HearingReminderStatus.QUEUED
        assert "CASEOPS_TWILIO_ENABLED" in (row.last_error or "")
    finally:
        for key in (
            "CASEOPS_HEARING_REMINDERS_ENABLED",
            "CASEOPS_SENDGRID_API_KEY",
            "CASEOPS_SENDGRID_SENDER_EMAIL",
        ):
            os.environ.pop(key, None)
        get_settings.cache_clear()


def test_whatsapp_row_stays_queued_pointing_at_meta_template_setup(
    client: TestClient,
) -> None:
    """WhatsApp default = disabled. Row stays QUEUED with last_error
    naming the env vars + Meta template-approval requirement."""
    os.environ["CASEOPS_HEARING_REMINDERS_ENABLED"] = "true"
    os.environ["CASEOPS_SENDGRID_API_KEY"] = "SG.fake"
    os.environ["CASEOPS_SENDGRID_SENDER_EMAIL"] = "hearings@caseops.ai"
    get_settings.cache_clear()

    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter = _mk_matter(client, token, code="WA-OFF")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)

    try:
        factory = get_session_factory()
        with factory() as session:
            wa_id = _mk_whatsapp_reminder(
                session, hearing_id=hearing["id"],
                matter_id=matter["id"], company_id=company_id,
            )
            report = run_reminder_worker(session, mode="auto")

        assert report["whatsapp_provider_configured"] is False
        with factory() as session:
            row = session.get(HearingReminder, wa_id)
        assert row.status == HearingReminderStatus.QUEUED
        assert "CASEOPS_WHATSAPP_ENABLED" in (row.last_error or "")
        assert "Meta template" in (row.last_error or "")
    finally:
        for key in (
            "CASEOPS_HEARING_REMINDERS_ENABLED",
            "CASEOPS_SENDGRID_API_KEY",
            "CASEOPS_SENDGRID_SENDER_EMAIL",
        ):
            os.environ.pop(key, None)
        get_settings.cache_clear()


def test_sms_row_with_no_recipient_phone_fails_fast(
    client: TestClient,
) -> None:
    """SMS row with NULL recipient_phone is FAILED and counted in
    skipped_missing_phone — mirror of the email no-recipient case."""
    os.environ["CASEOPS_HEARING_REMINDERS_ENABLED"] = "true"
    os.environ["CASEOPS_SENDGRID_API_KEY"] = "SG.fake"
    os.environ["CASEOPS_SENDGRID_SENDER_EMAIL"] = "hearings@caseops.ai"
    os.environ["CASEOPS_TWILIO_ENABLED"] = "true"
    os.environ["CASEOPS_TWILIO_ACCOUNT_SID"] = "ACfake"
    os.environ["CASEOPS_TWILIO_AUTH_TOKEN"] = "tok"
    os.environ["CASEOPS_TWILIO_FROM_NUMBER"] = "+15555550000"
    get_settings.cache_clear()

    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter = _mk_matter(client, token, code="SMS-NOPH")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)

    try:
        factory = get_session_factory()
        with factory() as session:
            sms_id = _mk_sms_reminder(
                session, hearing_id=hearing["id"],
                matter_id=matter["id"], company_id=company_id,
                recipient_phone=None,
            )
            report = run_reminder_worker(session, mode="auto")

        assert report["skipped_missing_phone"] >= 1
        with factory() as session:
            row = session.get(HearingReminder, sms_id)
        assert row.status == HearingReminderStatus.FAILED
        assert "no recipient phone" in (row.last_error or "")
    finally:
        for key in (
            "CASEOPS_HEARING_REMINDERS_ENABLED",
            "CASEOPS_SENDGRID_API_KEY",
            "CASEOPS_SENDGRID_SENDER_EMAIL",
            "CASEOPS_TWILIO_ENABLED",
            "CASEOPS_TWILIO_ACCOUNT_SID",
            "CASEOPS_TWILIO_AUTH_TOKEN",
            "CASEOPS_TWILIO_FROM_NUMBER",
        ):
            os.environ.pop(key, None)
        get_settings.cache_clear()


# Acknowledge auth_headers usage for ruff (helper imports it but
# doesn't reference it directly — keeping the import keeps the
# surface available for future channel-routing tests).
_ = auth_headers
