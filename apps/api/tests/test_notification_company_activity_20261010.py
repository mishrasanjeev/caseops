"""A retained delivery intent cannot outlive current tenant admission."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    InAppNotification,
    IpDocketRecord,
    NotificationDeliveryIntent,
    PortalUser,
)
from caseops_api.services import communications
from caseops_api.services import notification_delivery as delivery
from tests.test_notification_visibility_queries_20261010 import _context
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_record_access_policy_batch_20261010 import _seed
from tests.test_record_access_policy_batch_20261010 import (
    visibility_session as _visibility_session,
)

visibility_session = _visibility_session
TARGETS = ("matter", "standalone", "ip", "email_member", "portal", "external")


@pytest.fixture
def local_sender(monkeypatch):
    calls = []
    monkeypatch.setattr(delivery, "get_settings", lambda: SimpleNamespace(
        notification_external_delivery_enabled=True,
        notification_external_delivery_provider="sendgrid",
        sendgrid_api_key="local",
        sendgrid_sender_email="local@example.test",
    ))

    def send(**kwargs):
        calls.append(kwargs)
        return True, "local-provider-event", None

    monkeypatch.setattr(communications, "_send_via_sendgrid", send)
    return calls


def _fixture(session, target):
    company, matter, members, _outsider, _team, _other = _seed(session)
    context = _context(session, company, members["owner"])
    kwargs = {"recipient_membership": members["owner"], "channel": "in_app"}
    if target in {"matter", "email_member"}:
        kwargs["matter"] = matter
    if target == "ip":
        docket = IpDocketRecord(company_id=company.id, record_type="trademark",
                                title="Tenant activity notification", status="draft")
        session.add(docket)
        session.flush()
        kwargs["ip_docket"] = docket
    if target in {"email_member", "portal", "external"}:
        kwargs["channel"] = "email"
    if target == "portal":
        portal = PortalUser(company_id=company.id, email=f"portal-{uuid4()}@example.test",
                            full_name="Portal recipient", role="client")
        session.add(portal)
        session.flush()
        kwargs.pop("recipient_membership")
        kwargs["recipient_portal_user"] = portal
    if target == "external":
        kwargs.pop("recipient_membership")
        kwargs.update(recipient_external_ref="reviewed-local-destination", destination_snapshot={
            "approved": True, "approval_ref": "local-reviewed-destination",
            "destination": "external@example.test",
        })
    session.commit()
    return company, context, kwargs


def _enqueue(session, context, kwargs):
    return delivery.enqueue_notification_delivery_intent(
        session, context=context, event_type="tenant_activity",
        source_type="local_fixture", source_id=str(uuid4()),
        title="Tenant notification", body="Open CaseOps.", **kwargs,
    )


def _disable(session, company):
    assert company.is_active
    with Session(session.get_bind()) as writer:
        writer.get(Company, company.id).is_active = False
        writer.commit()
    # The authority read must not trust this warmed ORM identity.
    assert company.is_active


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("disabled", [False, True])
def test_retained_intent_rechecks_current_company_before_delivery(
    visibility_session, local_sender, target, disabled,
):
    session = visibility_session
    company, context, kwargs = _fixture(session, target)
    intent = _enqueue(session, context, kwargs)
    assert intent is not None
    session.commit()
    if disabled:
        _disable(session, company)
    result = delivery.process_notification_delivery_intent(
        session, intent_id=intent.id, context=context,
    )
    session.commit()
    if disabled:
        assert not result.delivered
        assert intent.status == "blocked"
        assert intent.dead_letter_reason == "recipient_permission_revoked"
        assert intent.attempts == 0
        assert intent.provider_event_id is None
        assert intent.fallback_intent_id is None
        assert local_sender == []
        assert session.scalar(select(func.count()).select_from(InAppNotification).where(
            InAppNotification.company_id == company.id,
        )) == 0
    elif kwargs["channel"] == "in_app":
        assert result.delivered and intent.in_app_notification_id is not None
        assert local_sender == []
    else:
        assert intent.status == "sent" and intent.provider_event_id == "local-provider-event"
        assert len(local_sender) == 1


@pytest.mark.parametrize("target", TARGETS)
def test_disabled_company_does_not_admit_a_new_or_fallback_intent(
    visibility_session, local_sender, target,
):
    session = visibility_session
    company, context, kwargs = _fixture(session, target)
    _disable(session, company)
    assert _enqueue(session, context, kwargs) is None
    assert session.scalar(select(func.count()).select_from(NotificationDeliveryIntent).where(
        NotificationDeliveryIntent.company_id == company.id,
    )) == 0
    assert local_sender == []


@pytest.mark.parametrize("target", ["matter", "standalone", "ip"])
def test_in_app_final_lookup_rechecks_company_disablement(
    visibility_session, local_sender, monkeypatch, target,
):
    session = visibility_session
    company, context, kwargs = _fixture(session, target)
    intent = _enqueue(session, context, kwargs)
    assert intent is not None
    session.commit()
    permitted = delivery._recipient_still_permitted

    def disable_after_permission_gate(current_session, current_intent):
        result = permitted(current_session, current_intent)
        assert result
        _disable(current_session, company)
        return result

    monkeypatch.setattr(delivery, "_recipient_still_permitted", disable_after_permission_gate)
    result = delivery.process_notification_delivery_intent(
        session, intent_id=intent.id, context=context,
    )
    assert not result.delivered
    assert intent.in_app_notification_id is None
    assert session.scalar(select(func.count()).select_from(InAppNotification).where(
        InAppNotification.company_id == company.id,
    )) == 0
    assert local_sender == []
