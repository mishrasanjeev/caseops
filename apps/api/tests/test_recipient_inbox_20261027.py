"""Populated recipient inbox contracts; delivery positives use normal APIs.

Raw rows below are corruption/history/scale controls after an actual delivered
receipt. They do not stand in for a positive delivery or a principal.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from caseops_api.core.automated_test_context import (
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    CustomRole,
    EthicalWall,
    HearingReminder,
    HearingReminderDeliveryIntent,
    InAppNotification,
    IpDocketRecord,
    Matter,
    NotificationDeliveryIntent,
    Team,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import notification_delivery
from caseops_api.services import recipient_inbox as inbox
from tests.sql_observation import is_read_only_select
from tests.test_hearing_explicit_channels_20261027 import context
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)
from tests.test_ip_notification_dismissal_20261017 import _delivered as _delivered_ip

forbid_unadmitted_network = _forbid_unadmitted_network
MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}
BASE = "/api/recipient-inbox"
PRIVATE = "SYNTHETIC_PRIVATE_STORED_BODY_MUST_NOT_APPEAR"
GENERATION_INDEX = "ix_hearing_reminder_company_hearing_generation"


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def boot(client):
    client.headers.update(MARKER)
    slug = "inbox-" + uuid4().hex[:12]
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Synthetic recipient firm",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Synthetic recipient",
            "owner_email": f"owner@{slug}.example.com",
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    actor = response.json()
    actor["headers"] = {**MARKER, "Authorization": "Bearer " + actor["access_token"]}
    return actor


def delivered_matter(client, monkeypatch, *, count=1):
    actor = boot(client)
    response = client.post(
        "/api/matters/",
        headers=actor["headers"],
        json={
            "title": "Current synthetic Matter",
            "matter_code": "INBOX-OWNED",
            "practice_area": "commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    matter = response.json()
    result = []
    for number in range(count):
        response = client.post(
            f"/api/matters/{matter['id']}/hearings",
            headers=actor["headers"],
            json={
                "hearing_on": (datetime.now(UTC) + timedelta(days=45 + number)).date().isoformat(),
                "forum_name": "Synthetic forum",
                "purpose": "Current hearing receipt",
                "timezone": "Asia/Kolkata",
                "time_status": "time_not_published",
                "expected_lifecycle_version": matter["lifecycle_version"],
                "reminder_channels": ["in_app"],
                "notification_critical": False,
                "reminder_offsets_hours": [24],
            },
        )
        assert response.status_code == 200, response.text
        hearing = response.json()
        with get_session_factory()() as session:
            intents = list(
                session.scalars(
                    select(NotificationDeliveryIntent).where(
                        NotificationDeliveryIntent.schedule_source_type == "matter_hearing",
                        NotificationDeliveryIntent.schedule_source_id == hearing["id"],
                    )
                )
            )
            assert len(intents) == 1 and intents[0].channel == "in_app"
            intent = intents[0]
            stamp = utc(intent.scheduled_for) + timedelta(seconds=1)
            monkeypatch.setattr(notification_delivery, "_now", lambda stamp=stamp: stamp)
            token = set_automated_test_request("no-paid-providers")
            try:
                assert paid_providers_blocked_for_request() is True
                delivered = notification_delivery.process_notification_delivery_intent(
                    session, intent_id=intent.id, company_id=actor["company"]["id"]
                )
                assert delivered.delivered is True and delivered.external_calls == 0
                notification_delivery.project_linked_hearing_reminder_intent(
                    session, intent_id=intent.id
                )
                session.commit()
            finally:
                reset_automated_test_request(token)
            session.refresh(intent)
            note = session.get(InAppNotification, intent.in_app_notification_id)
            assert note is not None and note.recipient_membership_id == actor["membership"]["id"]
            assert intent.delivered_at is not None
            result.append(
                {
                    "id": note.id,
                    "intent": intent.id,
                    "hearing": hearing,
                    "matter": matter,
                    "target": matter["id"],
                }
            )
    return actor, result


def delivered_source(client, monkeypatch, kind):
    if kind == "matter":
        actor, records = delivered_matter(client, monkeypatch)
        return actor, records[0]
    client.headers.update(MARKER)
    actor, docket, note_id = _delivered_ip(client, monkeypatch)
    actor["headers"] = {**actor["headers"], **MARKER}
    with get_session_factory()() as session:
        intent = session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.in_app_notification_id == note_id,
            )
        ).one()
        return actor, {"id": note_id, "intent": intent.id, "target": docket}


def raw_receipt(session, note_id):
    note = session.get(InAppNotification, note_id)
    intents = list(
        session.execute(
            select(*NotificationDeliveryIntent.__table__.c)
            .where(
                NotificationDeliveryIntent.in_app_notification_id == note_id,
            )
            .order_by(NotificationDeliveryIntent.id)
        ).mappings()
    )
    return deepcopy(
        {
            "note": {
                column.name: getattr(note, column.name) for column in InAppNotification.__table__.c
            },
            "intents": intents,
            "audit": list(
                session.scalars(
                    select(AuditEvent.id)
                    .where(
                        AuditEvent.target_type == "in_app_notification",
                        AuditEvent.target_id == note_id,
                        AuditEvent.action == "in_app_notification.status_changed",
                    )
                    .order_by(AuditEvent.id)
                )
            ),
        }
    )


def get_page(client, actor, **params):
    response = client.get(BASE, headers=actor["headers"], params=params)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    body = response.json()
    assert body["scope"] == "delivered_hearing_and_ip_renewal"
    return body


def roundtrip(client, monkeypatch, kind):
    actor, record = delivered_source(client, monkeypatch, kind)
    with get_session_factory()() as session:
        note = session.get(InAppNotification, record["id"])
        note.body = PRIVATE
        session.commit()
        before = raw_receipt(session, note.id)
    page = get_page(client, actor)
    assert len(page["items"]) == 1 and page["history_exhausted"] is True
    row = page["items"][0]
    assert row["id"] == record["id"] and row["status"] == "unread"
    assert row["target"] == {"kind": kind, "id": record["target"]}
    assert row["title"] == ("Hearing reminder" if kind == "matter" else "IP renewal alert")
    assert row["body"] == "Open the current record to review its details."
    assert PRIVATE not in json.dumps(page)
    assert datetime.fromisoformat(
        row["created_at"].replace("Z", "+00:00")
    ).utcoffset() == timedelta(0)
    for old, new in [("unread", "read"), ("read", "dismissed"), ("dismissed", "unread")]:
        payload = {"expected_status": old, "status": new}
        response = client.patch(
            "/api/recipient-inbox/{notification_id}".format(notification_id=record["id"]),
            headers=actor["headers"], json=payload,
        )
        assert response.status_code == 200 and response.json()["status"] == new, response.text
        replay = client.patch(f"{BASE}/{record['id']}", headers=actor["headers"], json=payload)
        assert replay.status_code == 200 and replay.json() == response.json()
        active, dismissed = get_page(client, actor), get_page(client, actor, view="dismissed")
        assert [x["id"] for x in active["items"]] == ([] if new == "dismissed" else [record["id"]])
        assert [x["id"] for x in dismissed["items"]] == (
            [record["id"]] if new == "dismissed" else []
        )
    with get_session_factory()() as session:
        after = raw_receipt(session, record["id"])
    assert after["intents"] == before["intents"]
    assert len(after["audit"]) == len(before["audit"]) + 3
    for key in before["note"].keys() - {"status", "read_at"}:
        assert after["note"][key] == before["note"][key]


@pytest.mark.parametrize("kind", ["matter", "ip_docket"])
def test_actual_delivered_receipt_active_dismissed_reload_and_owned_idempotent_mutation(
    client, monkeypatch, kind
):
    roundtrip(client, monkeypatch, kind)


def denied_changes(client, monkeypatch, kind, change):
    actor, record = delivered_source(client, monkeypatch, kind)
    with get_session_factory()() as session:
        before = raw_receipt(session, record["id"])
        member = session.get(CompanyMembership, actor["membership"]["id"])
        if change == "membership":
            member.is_active = False
        elif kind == "matter":
            member.role = "viewer"
            matter = session.get(Matter, record["target"])
            if change == "wall":
                session.add(
                    EthicalWall(
                        company_id=actor["company"]["id"],
                        matter_id=matter.id,
                        excluded_membership_id=member.id,
                        reason="Synthetic current wall",
                        created_by_membership_id=member.id,
                    )
                )
            elif change == "team":
                team = Team(company_id=actor["company"]["id"], name="Other team", slug="other-team")
                session.add(team)
                session.flush()
                matter.team_id = team.id
                session.get(Company, actor["company"]["id"]).team_scoping_enabled = True
            else:
                matter.status = "disposed"
                matter.is_active = False
        elif change == "capability":
            role = CustomRole(
                company_id=actor["company"]["id"],
                name="No IP",
                slug="no-ip",
                base_role="member",
                permissions_json=[],
                is_active=True,
                is_system=False,
            )
            session.add(role)
            session.flush()
            member.role, member.custom_role_id = "member", role.id
        else:
            session.get(IpDocketRecord, record["target"]).restricted = True
        session.commit()
    page = client.get(BASE, headers=actor["headers"])
    assert page.status_code in {200, 401, 403}
    if page.status_code == 200:
        assert page.json()["items"] == []
    changed = client.patch(
        f"{BASE}/{record['id']}",
        headers=actor["headers"],
        json={
            "expected_status": "unread",
            "status": "dismissed",
        },
    )
    assert changed.status_code in {401, 403, 404}, changed.text
    with get_session_factory()() as session:
        assert raw_receipt(session, record["id"]) == before
    source = (
        f"/api/matters/{record['target']}"
        if kind == "matter"
        else f"/api/ip/dockets/{record['target']}/summary"
    )
    denied = client.get(source, headers=actor["headers"])
    # Disposed Matters can have a retained read, but cannot remain inbox targets.
    if change != "disposed":
        assert denied.status_code in {401, 403, 404}, denied.text


@pytest.mark.parametrize(
    "kind,change",
    [
        ("matter", "wall"),
        ("matter", "team"),
        ("matter", "disposed"),
        ("matter", "membership"),
        ("ip_docket", "restricted"),
        ("ip_docket", "capability"),
        ("ip_docket", "membership"),
    ],
)
def test_fresh_actor_target_acl_team_wall_and_capability_revocation_are_not_mutations(
    client, monkeypatch, kind, change
):
    denied_changes(client, monkeypatch, kind, change)


def other_recipients(client, monkeypatch):
    actor, records = delivered_matter(client, monkeypatch)
    note_id = records[0]["id"]
    created = client.post(
        "/api/companies/current/users",
        headers=actor["headers"],
        json={
            "full_name": "Other recipient",
            "email": "other-inbox@example.com",
            "password": "OtherRecipient123!",
            "role": "viewer",
        },
    )
    assert created.status_code == 200, created.text
    for foreign in (False, True):
        with TestClient(client.app) as other:
            other.headers.update(MARKER)
            if foreign:
                outsider = boot(other)
            else:
                response = other.post(
                    "/api/auth/login",
                    json={
                        "company_slug": actor["company"]["slug"],
                        "email": "other-inbox@example.com",
                        "password": "OtherRecipient123!",
                    },
                )
                assert response.status_code == 200, response.text
                outsider = {
                    "headers": {
                        **MARKER,
                        "Authorization": "Bearer " + response.json()["access_token"],
                    }
                }
            assert get_page(other, outsider)["items"] == []
            changed = other.patch(
                f"{BASE}/{note_id}",
                headers=outsider["headers"],
                json={"expected_status": "unread", "status": "dismissed"},
            )
            assert changed.status_code == 404, changed.text
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).status == "unread"


def test_other_recipient_and_tenant_cannot_read_or_update_an_owned_receipt(client, monkeypatch):
    other_recipients(client, monkeypatch)


def chronology(client, monkeypatch):
    actor, records = delivered_matter(client, monkeypatch, count=4)
    ids = [row["id"] for row in records]
    stamp = datetime(2026, 1, 2, tzinfo=UTC)
    with get_session_factory()() as session:
        for note_id in ids:
            session.get(InAppNotification, note_id).created_at = stamp
        newest = min(ids)
        session.get(InAppNotification, newest).created_at = stamp + timedelta(seconds=1)
        session.commit()
    expected = [newest, *sorted(set(ids) - {newest}, reverse=True)]
    observed, cursor = [], None
    for _ in range(4):
        page = get_page(client, actor, limit=1, **({"cursor": cursor} if cursor else {}))
        observed.extend(row["id"] for row in page["items"])
        cursor = page["next_cursor"]
    assert observed == expected and cursor is None
    assert get_page(client, actor, limit=1)["items"][0]["id"] == newest


def test_timestamp_dominates_id_and_exact_ties_seek_before_limit_on_every_page(client, monkeypatch):
    chronology(client, monkeypatch)


def empty_page(client, monkeypatch):
    actor, records = delivered_matter(client, monkeypatch)
    with get_session_factory()() as session:
        valid = session.get(InAppNotification, records[0]["id"])
        session.add(
            InAppNotification(
                company_id=actor["company"]["id"],
                recipient_membership_id=actor["membership"]["id"],
                event_type="unsupported",
                source_type="unsupported",
                source_id=str(uuid4()),
                title=PRIVATE,
                created_at=utc(valid.created_at) + timedelta(seconds=1),
            )
        )
        session.commit()
    first = get_page(client, actor, limit=1)
    assert first["items"] == [] and first["history_exhausted"] is False and first["next_cursor"]
    second = get_page(client, actor, limit=1, cursor=first["next_cursor"])
    assert [row["id"] for row in second["items"]] == [records[0]["id"]]
    assert second["history_exhausted"] is True and second["next_cursor"] is None


def test_empty_bounded_candidate_page_retains_continuation_instead_of_claiming_empty_history(
    client, monkeypatch
):
    empty_page(client, monkeypatch)


def clone_invalid_link(session, actor, record):
    extra = NotificationDeliveryIntent(
        company_id=actor["company"]["id"],
        recipient_membership_id=actor["membership"]["id"],
        in_app_notification_id=record["id"],
        channel="in_app",
        event_type="unsupported",
        source_type="unsupported",
        source_id=str(uuid4()),
        idempotency_key="ambiguous-" + uuid4().hex,
        ip_docket_id=record["target"],
        status="blocked",
        metadata_json={"no_paid_providers": True},
    )
    session.add(extra)
    session.commit()


def ambiguous_fence(client, monkeypatch):
    actor, record = delivered_source(client, monkeypatch, "ip_docket")
    original = inbox._one_inbox_record
    reached = []

    def advisory_then_commit(session, current, notification_id):
        value = original(session, current, notification_id)
        if not reached:
            reached.append(True)
            with Session(session.get_bind()) as writer:
                clone_invalid_link(writer, actor, record)
        return value

    with get_session_factory()() as session:
        before = raw_receipt(session, record["id"])
    monkeypatch.setattr(inbox, "_one_inbox_record", advisory_then_commit)
    response = client.patch(
        f"{BASE}/{record['id']}",
        headers=actor["headers"],
        json={"expected_status": "unread", "status": "dismissed"},
    )
    assert response.status_code == 404 and reached == [True], response.text
    with get_session_factory()() as session:
        after = raw_receipt(session, record["id"])
    assert after["note"] == before["note"] and after["audit"] == before["audit"]
    assert len(after["intents"]) == 2  # The explicit corruption control is retained.


def test_ineligible_second_link_committed_after_advisory_read_is_refused_under_parent_fence(
    client, monkeypatch
):
    ambiguous_fence(client, monkeypatch)


def malformed_status(client, monkeypatch):
    actor, records = delivered_matter(client, monkeypatch)
    record = records[0]
    with get_session_factory()() as session:
        before = raw_receipt(session, record["id"])
    for payload, code in [
        ({"expected_status": "read", "status": "dismissed"}, 409),
        ({"expected_status": "unread", "status": "deleted"}, 422),
        ({"expected_status": "unread", "status": "read", "body": PRIVATE}, 422),
    ]:
        response = client.patch(f"{BASE}/{record['id']}", headers=actor["headers"], json=payload)
        assert response.status_code == code, response.text
        assert PRIVATE not in response.text
        assert response.headers["cache-control"] == "private, no-store"
    anonymous = TestClient(client.app)
    try:
        denied = anonymous.get(BASE)
        assert denied.status_code == 401
        assert denied.headers["cache-control"] == "private, no-store"
        assert denied.headers["referrer-policy"] == "no-referrer"
    finally:
        anonymous.close()
    with get_session_factory()() as session:
        assert raw_receipt(session, record["id"]) == before


def test_expected_state_invalid_extra_body_and_anonymous_errors_are_private_and_nonmutating(
    client, monkeypatch
):
    malformed_status(client, monkeypatch)


def cursor_contract(client):
    actor = boot(client)
    issued = datetime(2026, 10, 27, 0, tzinfo=UTC)
    created = issued - timedelta(days=1)
    row_id = str(uuid4())
    with get_session_factory()() as session:
        principal = context(session, actor)
        token = inbox.encode_inbox_cursor(principal, "active", 25, created, row_id, now=issued)
        assert actor["company"]["id"] not in token and row_id not in token
        for now in [issued, issued + timedelta(seconds=3599, microseconds=999999)]:
            assert inbox.decode_inbox_cursor(token, principal, "active", 25, now=now) == (
                created,
                row_id,
            )
        for now in [
            issued + timedelta(hours=1),
            issued + timedelta(hours=1, microseconds=1),
            issued - timedelta(seconds=1),
        ]:
            with pytest.raises(HTTPException) as expired:
                inbox.decode_inbox_cursor(token, principal, "active", 25, now=now)
            assert expired.value.status_code == 400
        payload = {
            **inbox._cursor_scope(principal, "active", 25),
            "created": created.isoformat(),
            "id": row_id,
            "iat": int(issued.timestamp()),
            "exp": int(issued.timestamp()) + 3600,
        }
        controls = [
            {key: value for key, value in payload.items() if key != missing} for missing in payload
        ]
        controls.extend(
            [
                {**payload, key: value}
                for key, value in [
                    ("company", str(uuid4())),
                    ("member", str(uuid4())),
                    ("user", str(uuid4())),
                    ("view", "dismissed"),
                    ("limit", 50),
                    ("v", True),
                    ("iat", True),
                    ("exp", payload["exp"] + 1),
                    ("created", "2026-10-27T00:00:00"),
                    ("id", "\n"),
                ]
            ]
        )
        controls.append({**payload, "unreviewed": PRIVATE})
        for invalid in controls:
            encrypted = (
                inbox._cursor_cipher()
                .encrypt_at_time(json.dumps(invalid).encode(), int(issued.timestamp()))
                .decode()
            )
            with pytest.raises(HTTPException) as refused:
                inbox.decode_inbox_cursor(encrypted, principal, "active", 25, now=issued)
            assert refused.value.status_code == 400 and PRIVATE not in str(refused.value.detail)
        # Change a complete interior base64 sextet, never unused padding bits.
        middle = len(token) // 2
        damaged = token[:middle] + ("A" if token[middle] != "A" else "B") + token[middle + 1 :]
        for invalid in [damaged, "", "é", "x" * 4001]:
            with pytest.raises(HTTPException):
                inbox.decode_inbox_cursor(invalid, principal, "active", 25, now=issued)
        for view, limit in [("dismissed", 25), ("active", 50)]:
            with pytest.raises(HTTPException):
                inbox.decode_inbox_cursor(token, principal, view, limit, now=issued)
    # Cursor test time is an explicit argument, never a process-wide JWT clock.
    response = client.get("/api/auth/me", headers=actor["headers"])
    assert response.status_code == 200, response.text


def test_encrypted_cursor_exact_scope_claims_signature_and_before_at_after_expiry_are_cursor_local(
    client,
):
    cursor_contract(client)


def generation_and_corruption(client, monkeypatch, change):
    actor, records = delivered_matter(client, monkeypatch)
    record = records[0]
    with get_session_factory()() as session:
        intent = session.get(NotificationDeliveryIntent, record["intent"])
        reminder = session.scalars(
            select(HearingReminder).where(
                HearingReminder.hearing_id == record["hearing"]["id"],
                HearingReminder.channel == "in_app",
            )
        ).one()
        if change == "new_generation":
            session.add(
                HearingReminder(
                    company_id=actor["company"]["id"],
                    matter_id=record["target"],
                    hearing_id=record["hearing"]["id"],
                    recipient_membership_id=actor["membership"]["id"],
                    channel="in_app",
                    scheduled_for=reminder.scheduled_for,
                    schedule_generation=reminder.schedule_generation + 1,
                    status="cancelled",
                )
            )
        elif change == "not_delivered":
            intent.status, intent.delivered_at = "queued", None
        elif change == "wrong_schedule":
            intent.scheduled_for = utc(intent.scheduled_for) + timedelta(seconds=1)
        else:
            note = session.get(InAppNotification, record["id"])
            note.source_id = PRIVATE + ":v1"
        session.commit()
    assert get_page(client, actor)["items"] == []
    denied = client.patch(
        f"{BASE}/{record['id']}",
        headers=actor["headers"],
        json={"expected_status": "unread", "status": "dismissed"},
    )
    assert denied.status_code == 404


@pytest.mark.parametrize(
    "change", ["new_generation", "not_delivered", "wrong_schedule", "malformed_source"]
)
def test_current_delivered_schedule_and_canonical_source_are_required(client, monkeypatch, change):
    generation_and_corruption(client, monkeypatch, change)


def read_only_recipient(client, monkeypatch):
    actor, records = delivered_matter(client, monkeypatch)
    record = records[0]
    with get_session_factory()() as session:
        session.get(CompanyMembership, actor["membership"]["id"]).role = "viewer"
        session.commit()
    response = client.patch(
        f"{BASE}/{record['id']}",
        headers=actor["headers"],
        json={"expected_status": "unread", "status": "read"},
    )
    assert response.status_code == 200, response.text
    forbidden = client.post(
        f"/api/matters/{record['target']}/tasks",
        headers=actor["headers"],
        json={
            "title": "Unpermitted task",
            "expected_lifecycle_version": record["matter"]["lifecycle_version"],
        },
    )
    assert forbidden.status_code == 403, forbidden.text


def test_receipt_management_does_not_grant_matter_write_authority(client, monkeypatch):
    read_only_recipient(client, monkeypatch)


def close_reopen(client, monkeypatch):
    actor, records = delivered_matter(client, monkeypatch)
    record = records[0]
    for target in ("disposed", "intake"):
        current = client.get(f"/api/matters/{record['target']}", headers=actor["headers"])
        assert current.status_code == 200, current.text
        matter = current.json()
        changed = client.patch(
            f"/api/matters/{record['target']}/lifecycle/status",
            headers=actor["headers"],
            json={
                "to_status": target,
                "expected_from_status": matter["status"],
                "expected_updated_at": matter["updated_at"],
                "reason": "Synthetic retained receipt lifecycle boundary",
            },
        )
        assert changed.status_code == 200, changed.text
        assert get_page(client, actor)["items"] == []
        with get_session_factory()() as session:
            before = raw_receipt(session, record["id"])
        refused = client.patch(
            f"{BASE}/{record['id']}",
            headers=actor["headers"],
            json={"expected_status": "unread", "status": "dismissed"},
        )
        assert refused.status_code == 404, refused.text
        with get_session_factory()() as session:
            assert raw_receipt(session, record["id"]) == before


def test_actual_parent_close_and_reopen_never_reactivate_retired_hearing_receipt(
    client, monkeypatch
):
    close_reopen(client, monkeypatch)


def postcommit_denial(client, monkeypatch):
    actor, records = delivered_matter(client, monkeypatch)
    record = records[0]
    original = inbox._one_inbox_record
    observed = []

    def current_before_but_denied_after_commit(session, principal, notification_id):
        observed.append(True)
        if len(observed) == 2:
            raise HTTPException(404, "Synthetic response read was denied after commit.")
        return original(session, principal, notification_id)

    monkeypatch.setattr(inbox, "_one_inbox_record", current_before_but_denied_after_commit)
    response = client.patch(
        f"{BASE}/{record['id']}",
        headers=actor["headers"],
        json={"expected_status": "unread", "status": "read"},
    )
    assert response.status_code == 404 and observed == [True, True], response.text
    with get_session_factory()() as session:
        persisted = raw_receipt(session, record["id"])
    assert persisted["note"]["status"] == "read" and len(persisted["audit"]) == 1
    assert len(persisted["intents"]) == 1 and persisted["intents"][0]["status"] == "delivered"


def test_postcommit_response_read_failure_does_not_assert_rollback_or_replay(client, monkeypatch):
    postcommit_denial(client, monkeypatch)


def source_bounds(client, monkeypatch, *, output=None):
    actor, records = delivered_matter(client, monkeypatch)
    measured = []
    with get_session_factory()() as session:
        engine = session.get_bind()

    def observe(_connection, _cursor, statement, parameters, execution_context, _many):
        measured.append(
            {
                "sql": statement,
                "parameters": parameters,
                "statement": getattr(execution_context.compiled, "statement", None),
                "typed_read": is_read_only_select(
                    getattr(execution_context.compiled, "statement", None)
                ),
            }
        )

    event.listen(engine, "before_cursor_execute", observe)
    try:
        page = get_page(client, actor, limit=25)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    if output is not None:
        (output / "actual-events.json").write_text(
            json.dumps(
                [{"sql": row["sql"], "typed_read": row["typed_read"]} for row in measured], indent=2
            )
        )
    assert [row["id"] for row in page["items"]] == [records[0]["id"]]
    assert 1 <= len(measured) <= 20
    assert all(row["typed_read"] for row in measured), (
        "every SQL event is charged and structurally classified"
    )
    from sqlalchemy.sql import visitors
    from sqlalchemy.sql.selectable import CTE, Join

    target_reads = [row["statement"] for row in measured if "inbox_exact_reminders" in row["sql"]]
    assert len(target_reads) == 1
    statement = target_reads[0]
    barriers = {
        id(node.element): node
        for node in visitors.iterate(statement)
        if isinstance(node, CTE) and node.name == "inbox_exact_reminders"
    }
    assert len(barriers) == 1
    assert next(iter(barriers.values())).element._limit_clause.value == 1

    def leaves(node):
        if isinstance(node, Join):
            yield from leaves(node.left)
            yield from leaves(node.right)
        else:
            yield node

    # An ORM alias must not accidentally leave the original broad history table
    # in the outer FROM. Its only base reads are inside the PK candidate and
    # bounded generation scalar, both independently measured below.
    assert all(
        node is not HearingReminder.__table__
        for root in statement.get_final_froms()
        for node in leaves(root)
    )
    return actor, records[0], measured


def test_populated_page_observes_every_actual_statement_under_a_fixed_read_budget(
    client, monkeypatch, tmp_path
):
    source_bounds(client, monkeypatch, output=tmp_path)


def plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from plan_nodes(child)


def plan_bound(client, monkeypatch, *, index_timing, adverse, output):
    """Owned PostgreSQL scale controls, with complete raw plans retained.

    The positive receipt is actually produced/delivered first. Extra cancelled
    generation-one history and unsupported old receipts are scale noise only.
    No statistics, planner deadlines or application budgets are increased.
    """
    actor, records = delivered_matter(client, monkeypatch)
    record = records[0]
    with get_session_factory()() as session:
        engine = session.get_bind()
    assert engine.dialect.name == "postgresql"
    index = next(
        index for index in HearingReminder.__table__.indexes if index.name == GENERATION_INDEX
    )
    if index_timing == "after_seed":
        index.drop(bind=engine)
    else:
        assert index_timing == "before_seed"
    with get_session_factory()() as session:
        reminder = session.scalars(
            select(HearingReminder).where(
                HearingReminder.hearing_id == record["hearing"]["id"],
                HearingReminder.channel == "in_app",
            )
        ).one()
        note = session.get(InAppNotification, record["id"])
        stamp = utc(note.created_at) - timedelta(days=365)
        for number in range(2000):
            session.add(
                HearingReminder(
                    company_id=actor["company"]["id"],
                    matter_id=record["target"],
                    hearing_id=record["hearing"]["id"],
                    recipient_membership_id=actor["membership"]["id"],
                    channel="in_app",
                    scheduled_for=utc(reminder.scheduled_for) - timedelta(minutes=number + 1),
                    schedule_generation=1,
                    status="cancelled",
                )
            )
            session.add(
                InAppNotification(
                    company_id=actor["company"]["id"],
                    recipient_membership_id=actor["membership"]["id"],
                    event_type="scale-noise",
                    source_type="scale-noise",
                    source_id=str(uuid4()),
                    title="Synthetic old noise",
                    created_at=stamp - timedelta(seconds=number),
                )
            )
        session.commit()
    if index_timing == "after_seed":
        index.create(bind=engine)

    measured = []

    def observe(_connection, _cursor, statement, parameters, execution_context, _many):
        measured.append(
            {
                "sql": statement,
                "parameters": parameters,
                "statement": getattr(execution_context.compiled, "statement", None),
                "typed_read": is_read_only_select(
                    getattr(execution_context.compiled, "statement", None)
                ),
            }
        )

    event.listen(engine, "before_cursor_execute", observe)
    try:
        page = get_page(client, actor, limit=25)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    (output / "actual-events.json").write_text(
        json.dumps(
            [{"sql": row["sql"], "typed_read": row["typed_read"]} for row in measured], indent=2
        )
    )
    assert [row["id"] for row in page["items"]] == [record["id"]]
    assert 1 <= len(measured) <= 20 and all(row["typed_read"] for row in measured)
    plans = []
    with engine.connect() as connection:
        if adverse:
            # Planner contrast only in this test connection; neither service
            # requests nor persistent settings change. Expose repeated inner
            # history work instead of amortizing it in a hash/merge join; retain
            # the ordered-index access needed by the candidate-page contract.
            connection.exec_driver_sql("SET LOCAL enable_hashjoin = off")
            connection.exec_driver_sql("SET LOCAL enable_mergejoin = off")
        for number, row in enumerate(measured):
            raw = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + row["sql"],
                row["parameters"],
            ).scalar_one()
            nodes = list(plan_nodes(raw[0]["Plan"]))
            # Include every node, including index-only/bitmap/CTE/intermediate
            # work without Relation Name, and weight every removed row by loops.
            work = sum(
                (
                    node.get("Actual Rows", 0)
                    + node.get("Rows Removed by Filter", 0)
                    + node.get("Rows Removed by Join Filter", 0)
                )
                * node.get("Actual Loops", 1)
                for node in nodes
            )
            plans.append({"sql": row["sql"], "raw": raw, "rowWorkAllNodes": work})
            (output / f"plan-{number:02d}.json").write_text(
                json.dumps(plans[-1], indent=2, default=str)
            )
    total = sum(row["rowWorkAllNodes"] for row in plans)
    (output / "plans-summary.json").write_text(
        json.dumps(
            {
                "indexTiming": index_timing,
                "adverse": adverse,
                "statementCount": len(plans),
                "allNodeRowWork": total,
            },
            indent=2,
        )
    )
    assert total <= 500, (
        "bounded candidate/PK/generation work must not scale with retained hearing history"
    )
    names = {
        node.get("Index Name") for plan in plans for node in plan_nodes(plan["raw"][0]["Plan"])
    }
    assert GENERATION_INDEX in names
    assert "ix_inapp_company_recipient_created_id" in names


def exact_source_candidate_refusal(client, monkeypatch, kind):
    actor, records = delivered_matter(client, monkeypatch, count=2 if kind == "owned" else 1)
    current = records[0]
    if kind == "owned":
        alternate = records[1]
        expected = []
        with get_session_factory()() as session:
            sibling = session.get(InAppNotification, alternate["id"])
            source = sibling.source_id
            # Keep the actual worker-produced reminder as the wrong owned PK
            # hint, but make its other receipt explicitly unsupported first.
            # This is a corruption fixture, not a second legitimate receipt;
            # it preserves the real recipient/event/source uniqueness rule.
            sibling.source_type = "synthetic-unsupported"
            session.commit()
    else:
        assert kind == "foreign"
        with TestClient(client.app) as other:
            _, foreign = delivered_matter(other, monkeypatch)
        with get_session_factory()() as session:
            source = session.get(InAppNotification, foreign[0]["id"]).source_id
        expected = []
    with get_session_factory()() as session:
        session.get(InAppNotification, current["id"]).source_id = source
        session.get(NotificationDeliveryIntent, current["intent"]).source_id = source
        session.commit()
        before = raw_receipt(session, current["id"])
        sibling_before = raw_receipt(session, records[1]["id"]) if kind == "owned" else None
    page = get_page(client, actor)
    assert [row["id"] for row in page["items"]] == expected
    denied = client.patch(
        f"{BASE}/{current['id']}",
        headers=actor["headers"],
        json={"expected_status": "unread", "status": "dismissed"},
    )
    assert denied.status_code == 404, denied.text
    with get_session_factory()() as session:
        assert raw_receipt(session, current["id"]) == before
        if sibling_before is not None:
            assert raw_receipt(session, records[1]["id"]) == sibling_before


@pytest.mark.parametrize("kind", ["owned", "foreign"])
def test_exact_pk_candidate_hint_never_grants_current_source_authority(client, monkeypatch, kind):
    exact_source_candidate_refusal(client, monkeypatch, kind)


def exact_primary_link_refusal(client, monkeypatch):
    actor, records = delivered_matter(client, monkeypatch, count=2)
    first, second = records
    with get_session_factory()() as session:
        links = list(
            session.scalars(
                select(HearingReminderDeliveryIntent).where(
                    HearingReminderDeliveryIntent.intent_id.in_(
                        (first["intent"], second["intent"])
                    ),
                    HearingReminderDeliveryIntent.is_primary.is_(True),
                )
            )
        )
        assert len(links) == 2
        by_intent = {link.intent_id: link for link in links}
        current, sibling = by_intent[first["intent"]], by_intent[second["intent"]]
        assert current.hearing_reminder_id != sibling.hearing_reminder_id
        # A corrupt bridge to another candidate must never establish authority
        # for this receipt, even when that sibling is independently legitimate.
        current.hearing_reminder_id = sibling.hearing_reminder_id
        session.commit()
        before = raw_receipt(session, first["id"])
        bridge = (current.id, current.hearing_reminder_id, current.intent_id, current.is_primary)
    page = get_page(client, actor)
    assert [row["id"] for row in page["items"]] == [second["id"]]
    denied = client.patch(
        f"{BASE}/{first['id']}",
        headers=actor["headers"],
        json={"expected_status": "unread", "status": "dismissed"},
    )
    assert denied.status_code == 404, denied.text
    with get_session_factory()() as session:
        assert raw_receipt(session, first["id"]) == before
        current = session.get(HearingReminderDeliveryIntent, bridge[0])
        assert (
            current.id,
            current.hearing_reminder_id,
            current.intent_id,
            current.is_primary,
        ) == bridge


def test_primary_bridge_belongs_to_exact_current_candidate_not_another_page_item(
    client, monkeypatch
):
    exact_primary_link_refusal(client, monkeypatch)
