from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    Communication,
    EmailCalendarCandidate,
    InboundEmailEvent,
    Matter,
    MatterComplianceExtractionRun,
    MatterCourtOrder,
    MatterDeadline,
    MatterHearing,
    MatterProceedingSignal,
    MatterTask,
    ModelRun,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
)
from tests.test_legalworkspace_calendar_sync import (
    _auth,
    _bootstrap_company,
    _create_matter,
)


def _dispose_matter(matter_id: str) -> None:
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.status = "disposed"
        matter.is_active = False
        session.commit()


def _count_for_matter(session, model, matter_id: str) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(model).where(model.matter_id == matter_id)
        )
        or 0
    )


def test_disposed_matter_rejects_every_candidate_generated_work_path(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="disposed-candidates",
        email="owner@disposed-candidates.example",
    )
    token = str(bootstrap["access_token"])
    headers = _auth(token)
    matter = _create_matter(client, token, "DISPOSED-CANDIDATES")
    matter_id = str(matter["id"])

    starts_at = datetime.now(UTC) + timedelta(days=7)
    provider_candidate = client.post(
        "/api/calendar/provider-event-candidates",
        headers=headers,
        json={
            "provider": "google_calendar",
            "provider_event_id": "disposed-provider-event",
            "title": "Disposed hearing candidate",
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(hours=1)).isoformat(),
            "location": "Delhi High Court",
            "provider_status": "confirmed",
            "suggested_matter_id": matter_id,
        },
    )
    assert provider_candidate.status_code == 200, provider_candidate.text

    mailbox_candidate = client.post(
        "/api/mailbox/outlook/candidates",
        headers=headers,
        json={
            "provider_message_id": "disposed-mail-message",
            "provider_thread_id": "disposed-mail-thread",
            "subject": "Work must not be generated",
            "occurred_at": datetime.now(UTC).isoformat(),
            "snippet": "Create no task after disposal.",
            "labels": ["Inbox"],
            "attachment_count": 0,
            "suggested_matter_id": matter_id,
        },
    )
    assert mailbox_candidate.status_code == 200, mailbox_candidate.text

    imported_email = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json={
            "provider": "manual",
            "provider_message_id": "disposed-calendar-invite",
            "sender_email": "client@example.in",
            "sender_name": "Client",
            "to_recipients": ["lawyer@example.in"],
            "subject": "Invitation: Disposed strategy conference",
            "received_at": "2026-05-15T10:30:00Z",
            "body_preview": (
                "Calendar invitation for 2026-08-15 at 10:30 AM. "
                "Venue: Courtroom 4."
            ),
            "attachments": [],
        },
    )
    assert imported_email.status_code == 200, imported_email.text
    extracted = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=headers,
        json={"matter_id": matter_id},
    )
    assert extracted.status_code == 200, extracted.text
    email_candidate_id = extracted.json()["candidates"][0]["id"]

    with get_session_factory()() as session:
        inbound = InboundEmailEvent(
            company_id=str(bootstrap["company"]["id"]),
            matched_matter_id=matter_id,
            provider="local_safe",
            provider_message_id="disposed-inbound-message",
            from_address_hash="sha256:redacted",
            from_display="Client",
            to_addresses_json=["matter@example.test"],
            cc_addresses_json=[],
            subject="Disposed inbound work",
            received_at=datetime.now(UTC),
            snippet="Create no task after disposal.",
            attachment_metadata_json=[],
            status="new",
            provenance_json={"body_imported": False},
        )
        session.add(inbound)
        session.commit()
        inbound_id = inbound.id
        communication_count_before = _count_for_matter(
            session,
            Communication,
            matter_id,
        )

    _dispose_matter(matter_id)

    responses = [
        client.patch(
            "/api/calendar/provider-event-candidates/"
            f"{provider_candidate.json()['id']}",
            headers=headers,
            json={"action": "accept", "matter_id": matter_id},
        ),
        client.patch(
            f"/api/calendar/email-invitation-candidates/{email_candidate_id}",
            headers=headers,
            json={"action": "approve"},
        ),
        client.patch(
            f"/api/mailbox/imports/{mailbox_candidate.json()['id']}",
            headers=headers,
            json={
                "action": "create_task",
                "matter_id": matter_id,
                "task_title": "Must not exist",
            },
        ),
        client.patch(
            f"/api/mailbox/inbound-events/{inbound_id}",
            headers=headers,
            json={
                "action": "create_task",
                "matter_id": matter_id,
                "task_title": "Must not exist",
            },
        ),
    ]
    assert [response.status_code for response in responses] == [409, 409, 409, 409]
    assert all("disposed" in response.text.lower() for response in responses)

    with get_session_factory()() as session:
        assert _count_for_matter(session, MatterTask, matter_id) == 0
        assert _count_for_matter(session, MatterDeadline, matter_id) == 0
        assert _count_for_matter(session, MatterHearing, matter_id) == 0
        assert (
            _count_for_matter(session, Communication, matter_id)
            == communication_count_before
        )
        email_candidate = session.get(EmailCalendarCandidate, email_candidate_id)
        assert email_candidate is not None
        assert email_candidate.status == "needs_review"
        assert email_candidate.created_deadline_id is None
        inbound = session.get(InboundEmailEvent, inbound_id)
        assert inbound is not None
        assert inbound.status == "new"
        assert inbound.communication_id is None


def test_disposed_matter_blocks_proceeding_compliance_provider_and_notifications(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="disposed-intelligence",
        email="owner@disposed-intelligence.example",
    )
    token = str(bootstrap["access_token"])
    headers = _auth(token)
    matter = _create_matter(client, token, "DISPOSED-INTELLIGENCE")
    matter_id = str(matter["id"])

    with get_session_factory()() as session:
        order = MatterCourtOrder(
            matter_id=matter_id,
            order_date=date(2026, 7, 15),
            title="Disposed order",
            summary="No operational work may be generated.",
            order_text=(
                "The respondent shall file a reply affidavit within seven days "
                "from the date of this order."
            ),
            source="manual",
        )
        session.add(order)
        session.commit()
        order_id = order.id

    provider_calls = {"build": 0}

    def provider_must_not_be_built(*_args, **_kwargs):
        provider_calls["build"] += 1
        raise AssertionError("disposed compliance extraction called an LLM provider")

    monkeypatch.setattr(
        "caseops_api.services.compliance_extraction.build_provider",
        provider_must_not_be_built,
    )
    _dispose_matter(matter_id)

    proceeding = client.post(
        f"/api/matters/{matter_id}/court-orders/{order_id}/"
        "proceeding-intelligence/extract",
        headers=headers,
    )
    compliance = client.post(
        f"/api/matters/{matter_id}/court-orders/{order_id}/compliance/retry",
        headers=headers,
    )
    assert proceeding.status_code == 409, proceeding.text
    assert compliance.status_code == 409, compliance.text
    assert provider_calls == {"build": 0}

    with get_session_factory()() as session:
        assert _count_for_matter(session, MatterProceedingSignal, matter_id) == 0
        assert _count_for_matter(session, MatterComplianceExtractionRun, matter_id) == 0
        assert _count_for_matter(session, MatterTask, matter_id) == 0
        assert _count_for_matter(session, MatterDeadline, matter_id) == 0
        assert _count_for_matter(session, NotificationDeliveryIntent, matter_id) == 0
        assert _count_for_matter(session, ModelRun, matter_id) == 0


def test_operational_guard_refreshes_a_stale_identity_map_after_disposal(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="disposed-stale-identity",
        email="owner@disposed-stale-identity.example",
    )
    token = str(bootstrap["access_token"])
    matter_id = str(_create_matter(client, token, "DISPOSED-STALE")["id"])
    factory = get_session_factory()

    with factory() as stale_session:
        stale_matter = stale_session.get(Matter, matter_id)
        assert stale_matter is not None
        assert stale_matter.is_active is True

        _dispose_matter(matter_id)

        with pytest.raises(MatterNotOperationalError):
            assert_operational_matter(
                stale_session,
                matter=stale_matter,
                lock_for_write=False,
            )
        assert stale_matter.status == "disposed"
        assert stale_matter.is_active is False
