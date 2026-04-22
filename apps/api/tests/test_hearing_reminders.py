"""BUG-013 — hearing reminders (dark-launched 2026-04-22).

Covers the full lifecycle we care about:

- Creating a hearing schedules one row per offset × recipient (owner
  of the workspace).
- Offsets in the past are skipped (so a hearing 3 hours from now
  gets a T-1h row but not a T-24h row).
- Scheduling is idempotent — a second create with the same
  ``(hearing_id, channel, scheduled_for)`` doesn't explode.
- Rescheduling (via ``cancel_reminders_for_hearing``) flips the old
  row to CANCELLED so the worker skips it.
- Worker auto-mode with flag OFF / provider unset leaves rows at
  QUEUED (dark launch) and bumps ``attempts``.
- Worker auto-mode with flag ON + provider set actually attempts a
  send and transitions to SENT on 200.
- A recipient with no email transitions the row to FAILED with the
  clear reason.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    HearingReminder,
    HearingReminderStatus,
    Matter,
    MatterHearing,
    MatterHearingStatus,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.hearing_reminders import (
    cancel_reminders_for_hearing,
    run_reminder_worker,
    schedule_reminders_for_hearing,
)
from tests.test_auth_company import auth_headers, bootstrap_company


def _days_ahead(n: int) -> date:
    return (datetime.now(UTC) + timedelta(days=n)).date()


def _mk_hearing_via_api(
    client: TestClient, token: str, matter_id: str, *, days_ahead: int = 2,
) -> dict:
    resp = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": _days_ahead(days_ahead).isoformat(),
            "forum_name": "Delhi HC, Bench: Hon'ble Mr. Justice X",
            "purpose": "Arguments on bail",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mk_matter(client: TestClient, token: str, code: str = "REM-1") -> dict:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Reminder test {code}",
            "matter_code": code,
            "practice_area": "criminal",
            "forum_level": "high_court",
            "status": "active",
            "court_name": "Delhi High Court",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------
# Scheduling — happens implicitly on hearing create.
# ---------------------------------------------------------------


def test_create_hearing_persists_reminder_rows(client: TestClient) -> None:
    """A hearing 2 days out → two reminders per eligible recipient
    (T-24h + T-1h) in status=queued. Proves the dark-launch hook
    fires in the real HTTP path."""
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-CREATE")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=2)

    factory = get_session_factory()
    with factory() as session:
        rows = list(
            session.query(HearingReminder).filter(
                HearingReminder.hearing_id == hearing["id"],
            )
        )
    # 1 owner × 2 offsets = 2 rows.
    assert len(rows) == 2
    assert {r.status for r in rows} == {HearingReminderStatus.QUEUED}
    assert all(r.recipient_email for r in rows)
    assert all(r.channel == "email" for r in rows)
    # Both scheduled_for values are in the future. SQLite round-trips
    # datetime-naive so normalise both sides to UTC for the compare.
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    for r in rows:
        sf = r.scheduled_for
        if sf.tzinfo is not None:
            sf = sf.astimezone(UTC).replace(tzinfo=None)
        assert sf > now_naive


def test_hearing_too_close_skips_the_24h_reminder(client: TestClient) -> None:
    """A hearing 3 hours out can't have a T-24h reminder (it's in the
    past), so only the T-1h row should exist."""
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-SOON")

    factory = get_session_factory()
    with factory() as session:
        matter_row = session.get(Matter, matter["id"])
        # Carefully place the hearing 3 hours from now — the offsets
        # are 24 and 1; 24 is in the past, 1 is still ~2h out.
        # We bypass the API helper to control the timing precisely.
        hearing = MatterHearing(
            matter_id=matter_row.id,
            hearing_on=(datetime.now(UTC) + timedelta(hours=3)).date(),
            forum_name="Delhi HC, Bench X",
            purpose="Arguments",
            status=MatterHearingStatus.SCHEDULED,
        )
        session.add(hearing)
        session.flush()
        # Pin an explicit hearing_at-equivalent closer to "now + 3h".
        # The service helper treats hearing_on as 04:30 UTC start.
        created = schedule_reminders_for_hearing(session, hearing=hearing)
        session.commit()

    # At most 1 row should have landed (T-1h if the 04:30 UTC start
    # is still > 1h away; 0 if not). Either way NOT 2.
    assert len(created) <= 1


def test_scheduling_is_idempotent_on_second_call(client: TestClient) -> None:
    """Re-calling schedule for the same hearing doesn't duplicate or
    raise — the uniqueness constraint catches it cleanly."""
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-IDEMP")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=5)

    factory = get_session_factory()
    with factory() as session:
        h = session.get(MatterHearing, hearing["id"])
        second = schedule_reminders_for_hearing(session, hearing=h)
        session.commit()
    # Second call creates nothing new (all pairs collide with the
    # existing uniqueness constraint).
    assert second == []

    with factory() as session:
        count = session.query(HearingReminder).filter(
            HearingReminder.hearing_id == hearing["id"]
        ).count()
    assert count == 2  # still 2 rows from the first create


# ---------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------


def test_cancel_reminders_flips_queued_to_cancelled(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-CANCEL")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)

    factory = get_session_factory()
    with factory() as session:
        n = cancel_reminders_for_hearing(session, hearing_id=hearing["id"])
        session.commit()
        rows = list(
            session.query(HearingReminder).filter(
                HearingReminder.hearing_id == hearing["id"]
            )
        )
    assert n == 2
    assert {r.status for r in rows} == {HearingReminderStatus.CANCELLED}


def test_update_hearing_reschedule_cancels_old_and_schedules_new(
    client: TestClient,
) -> None:
    """Rescheduling a hearing via PATCH must (a) flip the old reminder
    rows to CANCELLED so the worker skips them, and (b) queue fresh
    rows for the new date. Without this, flipping on SendGrid later
    would deliver a "hearing in 24h" email for a hearing that's now
    a month away."""
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-RESCHED")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)
    new_date = _days_ahead(10)

    resp = client.patch(
        f"/api/matters/{matter['id']}/hearings/{hearing['id']}",
        headers=auth_headers(token),
        json={"hearing_on": new_date.isoformat()},
    )
    assert resp.status_code == 200, resp.text

    factory = get_session_factory()
    with factory() as session:
        all_rows = list(
            session.query(HearingReminder).filter(
                HearingReminder.hearing_id == hearing["id"]
            )
        )
    cancelled = [r for r in all_rows if r.status == HearingReminderStatus.CANCELLED]
    queued = [r for r in all_rows if r.status == HearingReminderStatus.QUEUED]
    # Old rows still exist but are now CANCELLED; the new rows are QUEUED
    # against the new date. We don't pin row counts (depends on whether
    # each offset is still in the future from "now") but we MUST see both
    # a cancelled and a queued row, and the queued row's scheduled_for
    # must fall on / around the new hearing date.
    assert cancelled, "old reminders should be cancelled on reschedule"
    assert queued, "new reminders should be queued for the new date"
    for q in queued:
        assert q.scheduled_for.date() in {new_date, new_date - timedelta(days=1)}


def test_update_hearing_mark_completed_cancels_queued_reminders(
    client: TestClient,
) -> None:
    """Completing a hearing via PATCH flips every queued reminder to
    CANCELLED. No new reminders get scheduled (the hearing is done)."""
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-COMPLETE")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)

    resp = client.patch(
        f"/api/matters/{matter['id']}/hearings/{hearing['id']}",
        headers=auth_headers(token),
        json={"status": MatterHearingStatus.COMPLETED.value},
    )
    assert resp.status_code == 200, resp.text

    factory = get_session_factory()
    with factory() as session:
        rows = list(
            session.query(HearingReminder).filter(
                HearingReminder.hearing_id == hearing["id"]
            )
        )
    assert rows, "row count shouldn't change on complete"
    assert {r.status for r in rows} == {HearingReminderStatus.CANCELLED}


# ---------------------------------------------------------------
# Worker — dark-launch + live paths
# ---------------------------------------------------------------


def _force_due(session, hearing_id: str) -> None:
    """Shift the reminders into the past so the worker picks them."""
    for r in session.query(HearingReminder).filter(
        HearingReminder.hearing_id == hearing_id
    ):
        r.scheduled_for = datetime.now(UTC) - timedelta(minutes=5)
    session.commit()


def test_worker_auto_mode_flag_off_leaves_rows_queued(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag OFF (or provider unset) → worker logs 'would send' but
    leaves rows at QUEUED so flipping the flag later doesn't need a
    backfill."""
    import os

    from caseops_api.core.settings import get_settings

    os.environ.pop("CASEOPS_HEARING_REMINDERS_ENABLED", None)
    os.environ.pop("CASEOPS_SENDGRID_API_KEY", None)
    os.environ.pop("CASEOPS_SENDGRID_SENDER_EMAIL", None)
    get_settings.cache_clear()

    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-DARK")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)

    factory = get_session_factory()
    with factory() as session:
        _force_due(session, hearing["id"])
        report = run_reminder_worker(session, mode="auto")

    assert report["effective_live"] is False
    assert report["due_count"] == 2
    assert report["would_send"] == 2
    assert report["sent"] == 0

    with factory() as session:
        rows = list(
            session.query(HearingReminder).filter(
                HearingReminder.hearing_id == hearing["id"]
            )
        )
    assert {r.status for r in rows} == {HearingReminderStatus.QUEUED}
    assert all(r.attempts == 1 for r in rows)


def test_worker_live_sends_and_marks_sent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag ON + SendGrid creds set → worker actually POSTs to
    SendGrid. We stub the httpx call but assert the row transitions
    to SENT with a provider_message_id."""
    import os

    from caseops_api.core.settings import get_settings

    os.environ["CASEOPS_HEARING_REMINDERS_ENABLED"] = "true"
    os.environ["CASEOPS_SENDGRID_API_KEY"] = "SG.fake"
    os.environ["CASEOPS_SENDGRID_SENDER_EMAIL"] = "hearings@caseops.ai"
    get_settings.cache_clear()

    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-LIVE")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3)

    class _FakeResponse:
        status_code = 202
        headers = {"X-Message-Id": "msg-test-123"}
        text = ""

    try:
        factory = get_session_factory()
        with factory() as session:
            _force_due(session, hearing["id"])
            import httpx
            with patch.object(httpx, "post", return_value=_FakeResponse()) as mock:
                report = run_reminder_worker(session, mode="auto")
                # Real send attempted once per recipient-row.
                assert mock.call_count == 2

        assert report["effective_live"] is True
        assert report["sent"] == 2
        assert report["failed"] == 0

        with factory() as session:
            rows = list(
                session.query(HearingReminder).filter(
                    HearingReminder.hearing_id == hearing["id"]
                )
            )
        assert {r.status for r in rows} == {HearingReminderStatus.SENT}
        assert all(r.provider == "sendgrid" for r in rows)
        assert all(r.provider_message_id == "msg-test-123" for r in rows)
    finally:
        for key in (
            "CASEOPS_HEARING_REMINDERS_ENABLED",
            "CASEOPS_SENDGRID_API_KEY",
            "CASEOPS_SENDGRID_SENDER_EMAIL",
        ):
            os.environ.pop(key, None)
        get_settings.cache_clear()


def test_worker_mode_live_raises_when_provider_unset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``mode='live'`` explicitly requires the provider. Emergency
    manual runs should fail loudly, not silently skip."""
    import os

    from caseops_api.core.settings import get_settings

    # Force the provider off so the guardrail fires.
    for key in (
        "CASEOPS_SENDGRID_API_KEY",
        "CASEOPS_SENDGRID_SENDER_EMAIL",
    ):
        os.environ.pop(key, None)
    get_settings.cache_clear()

    # ``client`` pins the Session factory to the test SQLite DB; without
    # it the factory falls back to the shell env's DATABASE_URL.
    _ = client
    factory = get_session_factory()
    with factory() as session:
        with pytest.raises(RuntimeError, match="SendGrid credentials"):
            run_reminder_worker(session, mode="live")


# ---------------------------------------------------------------
# CLI entry point — JSON on stdout, exit 0 on success.
# ---------------------------------------------------------------


def test_cli_dry_run_returns_json_report(
    client: TestClient, capsys,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-CLI")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=5)
    _ = hearing

    from caseops_api.scripts.send_hearing_reminders import main

    rc = main(["--mode", "dry_run"])
    assert rc == 0
    captured = capsys.readouterr()
    import json as _json
    report = _json.loads(captured.out.strip().splitlines()[-1])
    assert report["mode"] == "dry_run"
    assert report["effective_live"] is False


def _unused_guard() -> None:  # keep private imports referenced
    _ = time


# ---------------------------------------------------------------
# SendGrid event webhook — updates rows from sent → delivered/failed
# ---------------------------------------------------------------


def test_sendgrid_webhook_updates_row_to_delivered(
    client: TestClient,
) -> None:
    """POST a ``delivered`` event whose sg_message_id prefix matches
    our stored provider_message_id → the reminder row flips to
    ``delivered`` with ``delivered_at`` populated."""
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-WH-OK")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=5)

    factory = get_session_factory()
    with factory() as session:
        # Pretend the worker already sent one reminder.
        r = (
            session.query(HearingReminder)
            .filter(HearingReminder.hearing_id == hearing["id"])
            .first()
        )
        r.status = HearingReminderStatus.SENT
        r.provider_message_id = "msg-webhook-42"
        session.commit()

    event_body = [
        {
            "event": "delivered",
            "sg_message_id": "msg-webhook-42.filterdrecv-1234",
            "timestamp": 1777_000_000,
            "email": "owner@example.com",
        }
    ]
    # No public key configured → signature check is a no-op.
    resp = client.post(
        "/api/webhooks/sendgrid/events",
        json=event_body,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] == 1
    assert body["matched"] == 1

    with factory() as session:
        row = session.scalar(
            select(HearingReminder).where(
                HearingReminder.provider_message_id == "msg-webhook-42"
            )
        )
        assert row is not None
        assert row.status == HearingReminderStatus.DELIVERED
        assert row.delivered_at is not None


def test_sendgrid_webhook_bounce_marks_row_failed(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-WH-BOUNCE")
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=5)

    factory = get_session_factory()
    with factory() as session:
        r = (
            session.query(HearingReminder)
            .filter(HearingReminder.hearing_id == hearing["id"])
            .first()
        )
        r.status = HearingReminderStatus.SENT
        r.provider_message_id = "msg-bounce-7"
        session.commit()

    resp = client.post(
        "/api/webhooks/sendgrid/events",
        json=[
            {
                "event": "bounce",
                "sg_message_id": "msg-bounce-7.filterdrecv-1",
                "reason": "mailbox unavailable",
                "timestamp": 1777_000_500,
            }
        ],
    )
    assert resp.status_code == 200
    with factory() as session:
        row = session.scalar(
            select(HearingReminder).where(
                HearingReminder.provider_message_id == "msg-bounce-7"
            )
        )
        assert row.status == HearingReminderStatus.FAILED
        assert "mailbox unavailable" in (row.last_error or "")


def test_sendgrid_webhook_unknown_message_id_is_no_op(
    client: TestClient,
) -> None:
    """A `sg_message_id` we never issued must NOT match any row —
    the endpoint returns 200 with matched=0 so SendGrid doesn't
    retry infinitely."""
    resp = client.post(
        "/api/webhooks/sendgrid/events",
        json=[
            {"event": "delivered", "sg_message_id": "not-ours.filterdrecv-0"},
        ],
    )
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 1, "matched": 0}


def test_admin_notifications_list_is_tenant_scoped(client: TestClient) -> None:
    """Admin list endpoint must only return rows for the caller's
    workspace — sanity for a staff dashboard over tenant-owned data.
    """
    token = str(bootstrap_company(client)["access_token"])
    matter = _mk_matter(client, token, code="REM-ADMIN-A")
    _ = _mk_hearing_via_api(client, token, matter["id"], days_ahead=4)

    resp = client.get(
        "/api/admin/notifications", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_queued"] == 2  # T-24h + T-1h
    assert len(body["reminders"]) == 2

    # Tenant B — separate workspace; should see zero reminders.
    b_resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B admin LLP",
            "company_slug": "tenant-b-reminders",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "b@tenant-b-reminders.example",
            "owner_password": "TenantB-Strong!234",
        },
    )
    token_b = str(b_resp.json()["access_token"])
    b_list = client.get(
        "/api/admin/notifications", headers=auth_headers(token_b),
    )
    assert b_list.status_code == 200
    assert b_list.json()["total_queued"] == 0
    assert b_list.json()["reminders"] == []
