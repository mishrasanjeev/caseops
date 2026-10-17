"""IP15-017: retained recipient actions never cancel renewal recurrence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, date, datetime
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    CustomRole,
    InAppNotification,
    IpDocketRecord,
    IpPortfolioRenewalSeries,
    MatterAccessGrant,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewal_tracker
from caseops_api.services.notification_delivery import (
    process_notification_delivery_intent,
    project_linked_hearing_reminder_intent,
)
from tests.test_ip_current_source_reminders_20261013 import _import_source
from tests.test_ip_recipient_renewal_content_20261014 import _deliver
from tests.test_ip_renewal_tracker_20261015 import _clock, _dispatch, _imported


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def notification_client(request):
    return request.getfixturevalue(request.param)


def _delivered(client, monkeypatch):
    actor, docket_id = _imported(client, monkeypatch)
    _clock(monkeypatch, datetime(2028, 2, 29, 4, tzinfo=UTC))
    with get_session_factory()() as session:
        assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == 1
    assert all(result.delivered for result in _dispatch(actor))
    with get_session_factory()() as session:
        note = session.scalars(select(InAppNotification)).one()
        return actor, docket_id, note.id


def _url(docket_id, note_id=None):
    base = f"/api/in-app-notifications?docket_id={docket_id}"
    return base if note_id is None else f"/api/in-app-notifications/{note_id}?docket_id={docket_id}"


def _snapshot(session, note_id):
    note = session.get(InAppNotification, note_id)
    intent = session.scalars(
        select(NotificationDeliveryIntent).where(
            NotificationDeliveryIntent.in_app_notification_id == note.id,
        )
    ).one()
    series = session.scalars(select(IpPortfolioRenewalSeries)).one()
    return deepcopy(
        {
            "note": (note.title, note.body, note.source_type, note.source_id, note.metadata_json),
            "intent": (
                intent.status,
                intent.body,
                intent.attempts,
                intent.delivered_at,
                intent.neutralized_at,
                intent.in_app_notification_id,
            ),
            "series": (
                series.generation,
                series.due_on,
                series.cancelled_at,
                series.next_reminder_at,
            ),
        }
    )


def test_actual_recipient_dismiss_restore_retains_receipt_and_audit(
    notification_client, monkeypatch
):
    client = notification_client
    actor, docket_id, note_id = _delivered(client, monkeypatch)
    with get_session_factory()() as session:
        original = _snapshot(session, note_id)
    page = client.get(_url(docket_id), headers=actor["headers"])
    assert page.status_code == 200, page.text
    note = page.json()["items"][0]
    assert note["id"] == note_id and note["status"] == "unread"
    assert note["body"] == original["note"][1]
    for before, after in (("unread", "dismissed"), ("dismissed", "unread"), ("unread", "read")):
        response = client.patch(
            _url(docket_id, note_id),
            headers=actor["headers"],
            json={
                "expected_status": before,
                "status": after,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == after
        replay = client.patch(
            _url(docket_id, note_id),
            headers=actor["headers"],
            json={
                "expected_status": before,
                "status": after,
            },
        )
        assert replay.status_code == 200, replay.text
        with get_session_factory()() as session:
            assert _snapshot(session, note_id) == original
    with get_session_factory()() as session:
        actions = session.scalars(
            select(AuditEvent).where(
                AuditEvent.target_type == "in_app_notification",
                AuditEvent.target_id == note_id,
            )
        ).all()
        assert len(actions) == 3
        assert {row.actor_membership_id for row in actions} == {actor["membership"]["id"]}


def test_dismissal_does_not_suppress_genuine_next_day_receipts(notification_client, monkeypatch):
    client = notification_client
    actor, docket_id, first_id = _delivered(client, monkeypatch)
    dismissed = client.patch(
        _url(docket_id, first_id),
        headers=actor["headers"],
        json={
            "expected_status": "unread",
            "status": "dismissed",
        },
    )
    assert dismissed.status_code == 200, dismissed.text
    for day in (date(2028, 3, 1), date(2028, 3, 2)):
        _clock(monkeypatch, datetime.combine(day, datetime.min.time(), UTC).replace(hour=4))
        with get_session_factory()() as session:
            assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == 1
        assert all(result.delivered for result in _dispatch(actor))
        assert _dispatch(actor) == []
    with get_session_factory()() as session:
        notes = session.scalars(select(InAppNotification)).all()
        assert len(notes) == 3
        assert session.get(InAppNotification, first_id).status == "dismissed"
        assert sum(note.status == "unread" for note in notes) == 2
        assert len({note.source_id for note in notes}) == 3
        assert session.scalars(select(IpPortfolioRenewalSeries)).one().cancelled_at is None


def test_legacy_portfolio_delivery_summary_survives_dismiss_restore(
    notification_client, monkeypatch
):
    client = notification_client
    _clock(monkeypatch, datetime(2028, 3, 20, tzinfo=UTC))
    actor, imported = _import_source(client)
    docket_id = imported["created_docket_id"]
    _, note_id, body = _deliver(actor, docket_id)
    for expected, target in (("unread", "dismissed"), ("dismissed", "unread")):
        changed = client.patch(
            _url(docket_id, note_id),
            headers=actor["headers"],
            json={
                "expected_status": expected,
                "status": target,
            },
        )
        assert changed.status_code == 200, changed.text
        portfolio = client.get("/api/ip/portfolio", headers=actor["headers"]).json()["rows"][0]
        assert portfolio["source_renewal_alert_status"] == "delivered"
        assert portfolio["source_renewal_alert_body"] == (None if target == "dismissed" else body)
        with get_session_factory()() as session:
            assert session.get(InAppNotification, note_id).body == body


def test_full_hearing_policy_and_current_receipt_survive_time_confirmation(
    notification_client, monkeypatch
):
    client = notification_client
    actor, docket_id = _imported(client, monkeypatch)
    member_id = actor["membership"]["id"]
    policy = {
        "offsets_hours": [48, 24],
        "channels": ["in_app"],
        "recipient_membership_ids": [member_id],
        "date_reminder_local_time": "17:45:00",
        "critical": True,
    }
    source = {
        "source": "manual",
        "source_ref_type": "manual_note",
        "source_ref_id": "fixture:hearing-source",
    }
    created = client.post(
        "/api/ip/hearings",
        headers=actor["headers"],
        json={
            "docket_id": docket_id,
            "hearing_on": "2028-03-20",
            "time_status": "time_not_published",
            "timezone": "Asia/Kolkata",
            "forum_name": "Trade Marks Registry",
            "purpose": "Policy readback",
            "hearing_mode": "virtual",
            "meeting_url": "https://example.com/hearing",
            "location_text": "Registry room",
            "attendee_membership_ids": [member_id],
            "responsible_membership_id": member_id,
            "reminder_policy": policy,
            **source,
        },
    )
    assert created.status_code == 201, created.text
    hearing = created.json()
    assert hearing["reminder_policy"] == {**policy, "escalation_membership_id": None}
    assert len(hearing["reminders"]) == 2 and hearing["hearing_time"] is None
    confirmed = client.patch(
        f"/api/ip/hearings/{hearing['id']}",
        headers=actor["headers"],
        json={
            "docket_id": docket_id,
            "time_status": "exact",
            "hearing_time": "14:30:00",
            "session_label": None,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    current = confirmed.json()
    assert current["current_schedule_generation"] == 2 and len(current["reminders"]) == 4
    current_rows = [row for row in current["reminders"] if row["schedule_generation"] == 2]
    assert len(current_rows) == 2
    _clock(monkeypatch, datetime(2028, 3, 18, 10, tzinfo=UTC))
    first = min(current_rows, key=lambda row: row["scheduled_for"])
    with get_session_factory()() as session:
        intent = session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.source_type == "hearing_reminder",
                NotificationDeliveryIntent.source_id == f"{first['id']}:v1",
            )
        ).one()
        delivered = process_notification_delivery_intent(
            session, intent_id=intent.id, company_id=actor["company"]["id"]
        )
        assert delivered.delivered and delivered.external_calls == 0
        project_linked_hearing_reminder_intent(session, intent_id=intent.id)
        note_id = intent.in_app_notification_id
        session.commit()
    page = client.get(_url(docket_id), headers=actor["headers"])
    assert page.status_code == 200, page.text
    assert [row["id"] for row in page.json()["items"]] == [note_id]
    dismissed = client.patch(
        _url(docket_id, note_id),
        headers=actor["headers"],
        json={
            "expected_status": "unread",
            "status": "dismissed",
        },
    )
    assert dismissed.status_code == 200, dismissed.text
    moved = client.patch(
        f"/api/ip/hearings/{hearing['id']}",
        headers=actor["headers"],
        json={
            "docket_id": docket_id,
            "hearing_on": "2028-03-22",
        },
    )
    assert moved.status_code == 200, moved.text
    listed = client.get(
        "/api/ip/hearings", headers=actor["headers"], params={"docket_id": docket_id}
    ).json()["hearings"][0]
    assert listed["reminder_policy"] == current["reminder_policy"]
    assert listed["hearing_time"] == "14:30:00" and listed["hearing_on"] == "2028-03-22"
    for key, value in source.items():
        assert listed[key] == value
    assert listed["current_schedule_generation"] == 3
    assert (
        client.get(_url(docket_id) + "&dismissed=true", headers=actor["headers"]).json()["items"]
        == []
    )
    rejected = client.patch(
        _url(docket_id, note_id),
        headers=actor["headers"],
        json={
            "expected_status": "dismissed",
            "status": "unread",
        },
    )
    assert rejected.status_code == 404, rejected.text
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).status == "dismissed"


@pytest.mark.parametrize("change", ["source", "terminal", "receipt_link", "recipient"])
def test_current_recipient_source_and_lifecycle_deny_body_and_mutation(
    notification_client, monkeypatch, change
):
    client = notification_client
    actor, docket_id, note_id = _delivered(client, monkeypatch)
    if change == "recipient":
        created = client.post(
            "/api/companies/current/users",
            headers=actor["headers"],
            json={
                "full_name": "Other recipient",
                "email": "other-recipient@example.com",
                "password": "OtherRecipient123!",
                "role": "member",
            },
        )
        assert created.status_code == 200, created.text
        other_id = created.json()["membership_id"]
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, docket_id)
        note = session.get(InAppNotification, note_id)
        if change == "source":
            docket.current_version += 1
        elif change == "terminal":
            docket.status = "closed"
            docket.is_active = False
        elif change == "receipt_link":
            session.scalars(select(NotificationDeliveryIntent)).one().in_app_notification_id = None
        else:
            # A current viewer is not authorized to operate another recipient's receipt.
            note.recipient_membership_id = other_id
        session.commit()
    response = client.get(_url(docket_id), headers=actor["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    response = client.patch(
        _url(docket_id, note_id),
        headers=actor["headers"],
        json={
            "expected_status": "unread",
            "status": "dismissed",
        },
    )
    assert response.status_code == 404, response.text
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).status == "unread"


def test_stale_status_conflict_and_invalid_body_are_not_mutations(notification_client, monkeypatch):
    client = notification_client
    actor, docket_id, note_id = _delivered(client, monkeypatch)
    for payload, expected in (
        ({"expected_status": "read", "status": "dismissed"}, 409),
        ({"expected_status": "unread", "status": "deleted"}, 422),
        ({"expected_status": "unread", "status": "dismissed", "body": "rewrite"}, 422),
    ):
        response = client.patch(_url(docket_id, note_id), headers=actor["headers"], json=payload)
        assert response.status_code == expected, response.text
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).status == "unread"


@pytest.mark.parametrize("boundary", ["access_wall", "capability", "membership"])
def test_current_access_revocation_never_mutates_retained_notification(
    notification_client, monkeypatch, boundary
):
    client = notification_client
    actor, docket_id, note_id = _delivered(client, monkeypatch)
    with get_session_factory()() as session:
        before = _snapshot(session, note_id)
        membership = session.get(CompanyMembership, actor["membership"]["id"])
        if boundary == "access_wall":
            session.get(IpDocketRecord, docket_id).restricted = True
        elif boundary == "membership":
            membership.is_active = False
        else:
            role = CustomRole(
                company_id=actor["company"]["id"],
                name="No IP access",
                slug="no-ip-access",
                base_role="member",
                permissions_json=[],
                is_active=True,
                is_system=False,
            )
            session.add(role)
            session.flush()
            membership.role, membership.custom_role_id = "member", role.id
        session.commit()
    response = client.get(_url(docket_id), headers=actor["headers"])
    if boundary == "access_wall":
        assert response.status_code == 200 and response.json()["items"] == []
    else:
        assert response.status_code in (401, 403), response.text
    response = client.patch(
        _url(docket_id, note_id),
        headers=actor["headers"],
        json={
            "expected_status": "unread",
            "status": "dismissed",
        },
    )
    assert response.status_code in (401, 403, 404), response.text
    with get_session_factory()() as session:
        assert _snapshot(session, note_id) == before
        assert session.get(InAppNotification, note_id).status == "unread"


@pytest.mark.parametrize("limit", [0, 51])
def test_recipient_page_bounds_are_enforced(notification_client, monkeypatch, limit):
    client = notification_client
    actor, docket_id, _ = _delivered(client, monkeypatch)
    response = client.get(_url(docket_id), headers=actor["headers"], params={"limit": limit})
    assert response.status_code == 422, response.text


def test_other_current_viewer_and_foreign_tenant_cannot_operate_receipt(
    notification_client, monkeypatch
):
    client = notification_client
    actor, docket_id, note_id = _delivered(client, monkeypatch)
    created = client.post(
        "/api/companies/current/users",
        headers=actor["headers"],
        json={
            "full_name": "Other viewer",
            "email": "other-viewer@example.com",
            "password": "OtherViewer123!",
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    for foreign in (False, True):
        other = TestClient(client.app)
        try:
            if foreign:
                response = other.post(
                    "/api/bootstrap/company",
                    json={
                        "company_name": "Foreign notification tenant",
                        "company_slug": "foreign-notifications",
                        "company_type": "law_firm",
                        "owner_full_name": "Foreign owner",
                        "owner_email": "foreign-owner@example.com",
                        "owner_password": "ForeignOwner123!",
                    },
                )
            else:
                response = other.post(
                    "/api/auth/login",
                    json={
                        "company_slug": actor["company"]["slug"],
                        "email": "other-viewer@example.com",
                        "password": "OtherViewer123!",
                    },
                )
            assert response.status_code == 200, response.text
            identity = other.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {response.json()['access_token']}"},
            )
            assert identity.status_code == 200, identity.text
            assert identity.json()["membership"]["id"] != actor["membership"]["id"]
            headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
            other.cookies.clear()
            assert other.get(_url(docket_id), headers=headers).json()["items"] == []
            rejected = other.patch(
                _url(docket_id, note_id),
                headers=headers,
                json={
                    "expected_status": "unread",
                    "status": "dismissed",
                },
            )
            assert rejected.status_code == 404, rejected.text
        finally:
            other.close()


@pytest.mark.postgres
@pytest.mark.parametrize("boundary", ["lifecycle", "grant"])
@pytest.mark.parametrize("restore", [False, True])
def test_native_locked_revocation_wins_dismiss_or_restore(
    isolated_postgres_client, monkeypatch, boundary, restore
):
    client = isolated_postgres_client
    actor, docket_id, note_id = _delivered(client, monkeypatch)
    if restore:
        response = client.patch(
            _url(docket_id, note_id),
            headers=actor["headers"],
            json={
                "expected_status": "unread",
                "status": "dismissed",
            },
        )
        assert response.status_code == 200, response.text
    with get_session_factory()() as session:
        if boundary == "grant":
            session.get(IpDocketRecord, docket_id).restricted = True
            session.add(
                MatterAccessGrant(
                    company_id=actor["company"]["id"],
                    ip_docket_id=docket_id,
                    membership_id=actor["membership"]["id"],
                    reason="Current recipient grant",
                    granted_by_membership_id=actor["membership"]["id"],
                )
            )
            session.commit()
        before = _snapshot(session, note_id)
    with get_session_factory()() as authority:
        docket = authority.scalar(
            select(IpDocketRecord).where(IpDocketRecord.id == docket_id).with_for_update()
        )
        holder_pid = authority.scalar(text("SELECT pg_backend_pid()"))
        if boundary == "lifecycle":
            docket.status, docket.is_active = "closed", False
        else:
            grant = authority.scalars(
                select(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == docket_id)
            ).one()
            grant.revoked_at = datetime.now(UTC)
        authority.flush()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                client.patch,
                _url(docket_id, note_id),
                headers=actor["headers"],
                json={
                    "expected_status": "dismissed" if restore else "unread",
                    "status": "unread" if restore else "dismissed",
                },
            )
            try:
                deadline = monotonic() + 5
                blocked = False
                while monotonic() < deadline:
                    with get_session_factory()() as observer:
                        blocked = bool(
                            observer.scalar(
                                text(
                                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                                    "WHERE :holder = ANY(pg_blocking_pids(pid)))"
                                ),
                                {"holder": holder_pid},
                            )
                        )
                    if blocked:
                        break
                    sleep(0.01)
                assert blocked and not pending.done(), (
                    "The real PostgreSQL row-lock overlap was not established."
                )
            finally:
                authority.commit()
            response = pending.result(timeout=10)
            assert response.status_code in (403, 404), response.text
    with get_session_factory()() as session:
        assert _snapshot(session, note_id) == before
        assert session.get(InAppNotification, note_id).status == (
            "dismissed" if restore else "unread"
        )
