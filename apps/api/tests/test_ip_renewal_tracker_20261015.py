"""IP15-007..022: persisted source-date tracking without legal authority claims."""

from copy import deepcopy
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    InAppNotification,
    IpDocketRecord,
    IpImportRow,
    IpPortfolioRenewalOccurrence,
    IpPortfolioRenewalSeries,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewal_tracker, ip_renewals, notification_delivery
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload


def _imported(client, monkeypatch):
    monkeypatch.setattr(ip_renewals, "_now", lambda: datetime(2028, 1, 1, tzinfo=UTC))
    monkeypatch.setattr(ip_renewal_tracker, "_now", lambda: datetime(2028, 1, 1, tzinfo=UTC))
    actor = _actor(client)
    preview = _upload(
        client,
        actor,
        ["Trademark", "Application Date", "Renewal Date"],
        [["Recurring source mark", "2020-03-31", "2028-03-31"]],
    )
    committed = _commit(client, actor, preview)
    return actor, committed["rows"][0]["created_docket_id"]


def test_portfolio_has_independent_date_fields(client, monkeypatch):
    actor, docket_id = _imported(client, monkeypatch)
    response = client.get("/api/ip/portfolio", headers=actor["headers"])
    assert response.status_code == 200, response.text
    row = next(row for row in response.json()["rows"] if row["docket_id"] == docket_id)
    assert row["source_application_on"] == "2020-03-31"
    assert row["source_renewal_due_on"] == "2028-03-31"
    assert row["source_application_state"] == "imported_unverified"
    assert row["source_renewal_state"] == "imported_unverified"


def test_secure_date_edit_preserves_omitted_renewal(client, monkeypatch):
    actor, docket_id = _imported(client, monkeypatch)
    original = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"]).json()
    response = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": original["current_version"],
            "application_date": "2020-04-01",
            "reason": "Correct supplied application date",
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["source_application_on"] == "2020-04-01"
    assert saved["source_application_state"] == "manual"
    assert saved["source_renewal_due_on"] == "2028-03-31"
    assert saved["source_renewal_state"] == "imported_unverified"


def test_tracker_includes_missing_dates_and_authorized_counts(client, monkeypatch):
    actor, docket_id = _imported(client, monkeypatch)
    response = client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"])
    assert response.status_code == 200, response.text
    assert any(row["docket_id"] == docket_id for row in response.json()["rows"])
    assert set(response.json()["counts"]) == {
        "upcoming",
        "active",
        "due_today",
        "overdue",
        "missing",
        "failed",
    }


def test_tracker_query_matches_portfolio_targets_and_filters_counts(client):
    actor = _actor(client)
    preview = _upload(
        client,
        actor,
        ["Trademark", "Application Number", "Renewal Date"],
        [["Needle Target", "QA-12345", ""], ["Unrelated mark", "QA-67890", ""]],
    )
    committed = _commit(client, actor, preview)
    target_id = committed["rows"][0]["created_docket_id"]
    for query in ("needle target", "qa12345"):
        params = {"query": query, "limit": 1}
        portfolio = client.get("/api/ip/portfolio", headers=actor["headers"], params=params)
        assert portfolio.status_code == 200, portfolio.text
        assert [row["docket_id"] for row in portfolio.json()["rows"]] == [target_id]
        tracker = client.get(
            "/api/ip/portfolio/renewal-tracker", headers=actor["headers"], params=params
        )
        assert tracker.status_code == 200, tracker.text
        body = tracker.json()
        assert [row["docket_id"] for row in body["rows"]] == [target_id]
        assert body["counts"]["missing"] == 1
        assert body["next_cursor"] is None
    from tests.test_auth_company import auth_headers

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Tracker LLP",
            "company_slug": "other-tracker",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@othertracker.in",
            "owner_password": "OtherTrackerPass123!",
        },
    )
    assert other.status_code == 200, other.text
    response = client.get(
        "/api/ip/portfolio/renewal-tracker",
        headers=auth_headers(other.json()["access_token"]),
        params={"query": "needle target"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == []
    assert all(count == 0 for count in response.json()["counts"].values())
    response = client.get(
        "/api/ip/portfolio/renewal-tracker", headers=actor["headers"], params={"query": "x" * 201}
    )
    assert response.status_code == 422, response.text


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def tracker_client(request):
    return request.getfixturevalue(request.param)


def _clock(monkeypatch, stamp):
    for service in (ip_renewals, ip_renewal_tracker, notification_delivery):
        monkeypatch.setattr(service, "_now", lambda: stamp)


def _dispatch(actor):
    with get_session_factory()() as session:
        intents = session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.company_id == actor["company"]["id"],
                NotificationDeliveryIntent.status == "queued",
                NotificationDeliveryIntent.scheduled_for <= ip_renewal_tracker._now(),
            )
        ).all()
        results = [
            notification_delivery.process_notification_delivery_intent(
                session, intent_id=intent.id, company_id=actor["company"]["id"]
            )
            for intent in intents
        ]
        session.commit()
        return results


def test_persistent_daily_occurrences_replay_dismissal_and_due_inclusive(
    tracker_client, monkeypatch
):
    client = tracker_client
    actor, docket_id = _imported(client, monkeypatch)
    for index, day in enumerate(
        (date(2028, 2, 29), date(2028, 3, 1), date(2028, 3, 2), date(2028, 3, 31)), 1
    ):
        now = datetime.combine(day, datetime.min.time(), UTC).replace(hour=4)
        _clock(monkeypatch, now)
        with get_session_factory()() as session:
            result = ip_renewal_tracker.reconcile_renewal_series(session, now=now)
            assert result["advanced"] == 1
            assert not session.in_transaction()
        assert all(row.delivered for row in _dispatch(actor))
        with get_session_factory()() as session:
            occurrences = session.scalars(
                select(IpPortfolioRenewalOccurrence)
                .where(IpPortfolioRenewalOccurrence.docket_id == docket_id)
                .order_by(IpPortfolioRenewalOccurrence.local_on)
            ).all()
            notes = session.scalars(
                select(InAppNotification).where(
                    InAppNotification.company_id == actor["company"]["id"]
                )
            ).all()
            assert len(occurrences) == len(notes) == index
            assert occurrences[-1].local_on == day
            note = next(
                row
                for row in notes
                if row.metadata_json.get("source_due_on") == "2028-03-31" and row.status == "unread"
            )
            assert "not a verified legal deadline" in note.body
            if day == date(2028, 3, 31):
                assert "Renewal due today" in note.body
            note.status = "read"
            intent = session.scalar(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.in_app_notification_id == note.id
                )
            )
            attempts = intent.attempts
            replay = notification_delivery.process_notification_delivery_intent(
                session, intent_id=intent.id, company_id=actor["company"]["id"]
            )
            assert replay.delivered and intent.attempts == attempts
            session.commit()
        response = client.get(
            "/api/ip/portfolio/renewal-tracker",
            headers=actor["headers"],
            params={"query": "Recurring source mark"},
        )
        assert response.status_code == 200, response.text
        row = response.json()["rows"][0]
        assert row["status"] == "sent" and row["delivered_at"] and row["last_attempt_at"]
        assert row["reminder_start_on"] == "2028-02-29"
    _clock(monkeypatch, datetime(2028, 4, 1, 4, tzinfo=UTC))
    with get_session_factory()() as session:
        assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == 0
        assert session.scalar(select(func.count()).select_from(IpPortfolioRenewalOccurrence)) == 4
    assert _dispatch(actor) == []


def test_manual_independent_dates_no_import_forgery_stale_and_atomic_rollback(
    tracker_client, monkeypatch
):
    from caseops_api.services import ip_portfolio_dates_writer
    from tests.test_ip_039a_filing_particulars import _particulars

    client = tracker_client
    actor = _actor(client)
    created = client.post(
        "/api/ip/dockets",
        headers=actor["headers"],
        json={
            "title": "Manual source dates",
            "restricted": False,
            "particulars": _particulars("Manual source dates"),
        },
    )
    assert created.status_code == 201, created.text
    original = created.json()
    docket_id = original["id"]
    original_particulars = deepcopy(original["current_particulars"])
    url = f"/api/ip/dockets/{docket_id}/portfolio-dates"
    saved = client.patch(
        url,
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "application_date": "2020-02-29",
            "renewal_due_date": "2028-03-31",
            "reason": "Dates supplied by client source",
        },
    )
    assert saved.status_code == 200, saved.text
    assert (
        saved.json()["source_application_state"] == saved.json()["source_renewal_state"] == "manual"
    )
    current = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"]).json()
    assert current["status"] == original["status"]
    for field in (
        "mark_kind",
        "classes_json",
        "parties_json",
        "use_priority_json",
        "agent_json",
        "filing_manifest_json",
    ):
        assert current["current_particulars"][field] == original_particulars[field]
    assert (
        client.patch(
            url,
            headers=actor["headers"],
            json={
                "expected_current_version": 1,
                "application_date": None,
                "reason": "Attempt a stale write",
            },
        ).status_code
        == 409
    )

    def fail_audit(*args, **kwargs):
        raise RuntimeError("deterministic audit failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(ip_portfolio_dates_writer, "record_from_context", fail_audit)
        with pytest.raises(RuntimeError, match="deterministic audit failure"):
            client.patch(
                url,
                headers=actor["headers"],
                json={
                    "expected_current_version": 2,
                    "renewal_due_date": None,
                    "reason": "Failed date removal is atomic",
                },
            )
    with get_session_factory()() as session:
        assert session.get(IpDocketRecord, docket_id).current_version == 2
        assert session.scalar(select(func.count()).select_from(IpImportRow)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "ip_docket.source_materialized")
            )
            == 0
        )
        assert (
            session.scalar(
                select(IpPortfolioRenewalSeries).where(
                    IpPortfolioRenewalSeries.docket_id == docket_id
                )
            ).cancelled_at
            is None
        )
    cleared = client.patch(
        url,
        headers=actor["headers"],
        json={
            "expected_current_version": 2,
            "application_date": None,
            "reason": "Application date explicitly withdrawn",
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["source_application_state"] == "missing"
    assert cleared.json()["source_renewal_due_on"] == "2028-03-31"


@pytest.mark.parametrize(
    "value", [True, 1770000000, "03/04/2028", "20280304", "2028-03-04T00:00:00Z"]
)
def test_date_edit_rejects_guessing_and_timestamp_inputs(value):
    from pydantic import ValidationError

    from caseops_api.schemas.ip_renewal_tracker import IpPortfolioDatesUpdate

    with pytest.raises(ValidationError):
        IpPortfolioDatesUpdate(
            expected_current_version=1, reason="Explicit source date", application_date=value
        )


@pytest.mark.parametrize(
    ("due", "start"),
    [
        ("2028-03-31", "2028-02-29"),
        ("2027-03-31", "2027-02-28"),
        ("2029-01-31", "2028-12-31"),
        ("2028-05-31", "2028-04-30"),
    ],
)
def test_calendar_month_not_fixed_days(due, start):
    assert ip_renewal_tracker.month_start(date.fromisoformat(due)) == date.fromisoformat(start)


def test_backfill_one_current_occurrence_no_historical_burst(tracker_client, monkeypatch):
    client = tracker_client
    with monkeypatch.context() as old_policy:
        old_policy.setattr(ip_renewal_tracker, "synchronize_series", lambda *args, **kwargs: None)
        actor, docket_id = _imported(client, monkeypatch)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpPortfolioRenewalSeries)) == 0
        assert session.scalar(select(func.count()).select_from(IpPortfolioRenewalOccurrence)) == 0
    _clock(monkeypatch, datetime(2028, 3, 20, 4, tzinfo=UTC))
    for expected in (1, 0):
        with get_session_factory()() as session:
            assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == expected
    results = _dispatch(actor)
    assert len(results) == 1 and results[0].delivered
    with get_session_factory()() as session:
        occurrences = session.scalars(
            select(IpPortfolioRenewalOccurrence).order_by(IpPortfolioRenewalOccurrence.local_on)
        ).all()
        assert [row.local_on for row in occurrences] == [date(2028, 2, 29), date(2028, 3, 20)]
        old = session.scalar(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.source_type == "ip_trademark_particular_version"
            )
        )
        assert old.status == "cancelled"
        assert session.scalar(select(func.count()).select_from(InAppNotification)) == 1


def test_configured_cadence_time_filters_counts_and_date_clear(tracker_client, monkeypatch):
    from tests.test_ip_workspace_configuration import _configuration

    client = tracker_client
    actor, docket_id = _imported(client, monkeypatch)
    now = datetime(2028, 3, 20, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    config = _configuration(actor["membership"]["id"])
    config.update(
        expected_version=1, renewal_reminder_cadence_days=2, renewal_reminder_delivery_time="10:15"
    )
    saved = client.put("/api/ip/workspace/configuration", headers=actor["headers"], json=config)
    assert saved.status_code == 200, saved.text
    assert saved.json()["configuration"]["renewal_reminder_cadence_days"] == 2
    with get_session_factory()() as session:
        assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == 0
        series = session.scalar(
            select(IpPortfolioRenewalSeries).where(IpPortfolioRenewalSeries.docket_id == docket_id)
        )
        assert series.next_reminder_at.replace(tzinfo=UTC) == datetime(
            2028, 3, 20, 4, 45, tzinfo=UTC
        )
    _clock(monkeypatch, datetime(2028, 3, 20, 5, tzinfo=UTC))
    with get_session_factory()() as session:
        assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == 1
    assert len(_dispatch(actor)) == 1
    for params, expected in (
        ({"application_date_from": "2020-03-31", "application_date_to": "2020-03-31"}, 1),
        ({"renewal_due_from": "2028-04-01"}, 0),
        ({"renewal_tracker_state": "active"}, 1),
    ):
        result = client.get("/api/ip/portfolio", headers=actor["headers"], params=params)
        assert result.status_code == 200, result.text
        assert len(result.json()["rows"]) == expected
    result = client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"])
    assert result.status_code == 200, result.text
    assert result.json()["counts"]["due_today"] == 1
    assert result.json()["rows"][0]["next_reminder_at"].startswith("2028-03-22T04:45")
    changed = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "renewal_due_date": None,
            "reason": "Source renewal date withdrawn",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["source_renewal_state"] == "missing"
    assert changed.json()["tracker"]["delivered_at"] is not None
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(IpPortfolioRenewalSeries).where(
                    IpPortfolioRenewalSeries.docket_id == docket_id
                )
            ).next_reminder_at
            is None
        )


def test_quiet_hours_defer_current_occurrence_without_losing_it(client, monkeypatch):
    actor, docket_id = _imported(client, monkeypatch)
    _clock(monkeypatch, datetime(2028, 2, 29, 4, tzinfo=UTC))
    preferences = client.patch(
        "/api/notification-preferences",
        headers=actor["headers"],
        json={
            "quiet_hours": {
                "enabled": True,
                "start": "08:00",
                "end": "10:00",
                "timezone": "Asia/Kolkata",
            }
        },
    )
    assert preferences.status_code == 200, preferences.text
    with get_session_factory()() as session:
        ip_renewal_tracker.reconcile_renewal_series(session)
    result = _dispatch(actor)
    assert len(result) == 1 and str(result[0].status) == "retry_scheduled"
    with get_session_factory()() as session:
        intent = session.scalar(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.ip_docket_id == docket_id
            )
        )
        assert intent.attempts == 0 and intent.in_app_notification_id is None
        assert intent.next_attempt_at.replace(tzinfo=UTC) == datetime(
            2028, 2, 29, 4, 30, tzinfo=UTC
        )
    _clock(monkeypatch, datetime(2028, 2, 29, 4, 31, tzinfo=UTC))
    with get_session_factory()() as session:
        result = notification_delivery.process_notification_delivery_intent(
            session, intent_id=intent.id, company_id=actor["company"]["id"]
        )
        assert result.delivered
        session.commit()


@pytest.mark.parametrize("boundary", ["preference", "membership", "date_change", "date_clear"])
def test_current_occurrence_rechecks_source_and_recipient(tracker_client, monkeypatch, boundary):
    client = tracker_client
    actor, docket_id = _imported(client, monkeypatch)
    _clock(monkeypatch, datetime(2028, 3, 1, 4, tzinfo=UTC))
    with get_session_factory()() as session:
        ip_renewal_tracker.reconcile_renewal_series(session)
        intent = session.scalar(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.company_id == actor["company"]["id"],
                NotificationDeliveryIntent.source_type == ip_renewal_tracker.SOURCE,
            )
        )
        intent_id = intent.id
    if boundary == "preference":
        response = client.patch(
            "/api/notification-preferences",
            headers=actor["headers"],
            json={"channels": {"in_app": False}},
        )
        assert response.status_code == 200, response.text
    elif boundary == "membership":
        with get_session_factory()() as session:
            session.get(CompanyMembership, actor["membership"]["id"]).is_active = False
            session.commit()
    else:
        response = client.patch(
            f"/api/ip/dockets/{docket_id}/portfolio-dates",
            headers=actor["headers"],
            json={
                "expected_current_version": 1,
                "renewal_due_date": "2028-04-30" if boundary == "date_change" else None,
                "reason": "Correct current source before dispatch",
            },
        )
        assert response.status_code == 200, response.text
    with get_session_factory()() as session:
        retained = session.get(NotificationDeliveryIntent, intent_id)
        if boundary.startswith("date_"):
            assert retained.status == "cancelled"
            retained.status = "queued"  # Retained repair state must still pass the source fence.
            session.commit()
        result = notification_delivery.process_notification_delivery_intent(
            session, intent_id=intent_id, company_id=actor["company"]["id"]
        )
        assert result.blocked and not result.delivered
        assert retained.in_app_notification_id is None and retained.attempts == 0
        session.commit()
        assert session.scalar(select(func.count()).select_from(InAppNotification)) == 0


def test_retry_uses_same_occurrence_and_confirms_real_delivery(tracker_client, monkeypatch):
    client = tracker_client
    actor, docket_id = _imported(client, monkeypatch)
    now = datetime(2028, 3, 1, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    with get_session_factory()() as session:
        ip_renewal_tracker.reconcile_renewal_series(session)
        intent = session.scalar(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.ip_docket_id == docket_id,
                NotificationDeliveryIntent.source_type == ip_renewal_tracker.SOURCE,
            )
        )
        intent_id, source_id = intent.id, intent.source_id
        result = notification_delivery.record_notification_delivery_failure(
            session, intent=intent, raw_error="deterministic local in-app failure", retryable=True
        )
        assert result.retry_scheduled
        retry_at = intent.next_attempt_at.replace(tzinfo=UTC)
        session.commit()
    tracker = client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"]).json()
    assert tracker["counts"]["failed"] == 1
    assert tracker["rows"][0]["status"] == "failed" and tracker["rows"][0]["delivered_at"] is None
    _clock(monkeypatch, retry_at)
    with get_session_factory()() as session:
        result = notification_delivery.process_notification_delivery_intent(
            session, intent_id=intent_id, company_id=actor["company"]["id"]
        )
        assert result.delivered
        session.commit()
        assert session.get(NotificationDeliveryIntent, intent_id).source_id == source_id
        assert session.scalar(select(func.count()).select_from(InAppNotification)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpPortfolioRenewalOccurrence)
                .where(IpPortfolioRenewalOccurrence.local_on == now.date())
            )
            == 1
        )


@pytest.mark.parametrize(
    ("day", "clock", "expected"),
    [
        (date(2028, 3, 11), "09:00", datetime(2028, 3, 11, 14, tzinfo=UTC)),
        (date(2028, 3, 12), "09:00", datetime(2028, 3, 12, 13, tzinfo=UTC)),
        (date(2028, 3, 12), "02:30", datetime(2028, 3, 12, 7, 30, tzinfo=UTC)),
        (date(2028, 11, 5), "01:30", datetime(2028, 11, 5, 5, 30, tzinfo=UTC)),
    ],
)
def test_timezone_dst_delivery_instants(day, clock, expected):
    assert (
        ip_renewal_tracker.local_stamp(day, timezone="America/New_York", delivery_time=clock)
        == expected
    )
