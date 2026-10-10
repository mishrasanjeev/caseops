"""Fresh ACL and idempotency reads remain distinct from a missing queue row."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    EthicalWall,
    InAppNotification,
    MatterAccessGrant,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.services import notification_delivery as delivery
from caseops_api.services.matter_access import can_access
from caseops_api.services.matter_operational_guard import matter_is_operational
from caseops_api.services.session_context import SessionContext
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_record_access_policy_batch_20261010 import (
    _seed,
)
from tests.test_record_access_policy_batch_20261010 import (
    visibility_session as _visibility_session,
)

visibility_session = _visibility_session


def _context(session, company, membership):
    return SessionContext(company=company, membership=membership,
                          user=session.get(User, membership.user_id))


def _enqueue(session, context, recipient, matter, source_id):
    return delivery.enqueue_notification_delivery_intent(
        session, context=context, recipient_membership=recipient, matter=matter,
        channel="in_app", event_type="fresh_visibility", source_type="court_order",
        source_id=source_id, title="Retained notification", body="Open CaseOps.",
    )


def _count(session, model, company_id):
    return session.scalar(select(func.count()).select_from(model).where(
        model.company_id == company_id,
    ))


@pytest.mark.parametrize("policy", [
    "visible", "restricted", "scoped", "wall", "grant", "revoked_grant", "expired_grant",
])
def test_enqueue_current_visibility_and_exact_idempotency(visibility_session, policy):
    session = visibility_session
    company, matter, members, _outsider, _team, _other = _seed(
        session, scoped=policy == "scoped",
        restricted=policy in {"restricted", "grant", "revoked_grant", "expired_grant"},
    )
    if policy == "wall":
        session.add(EthicalWall(company_id=company.id, matter_id=matter.id,
                                excluded_membership_id=members["member"].id))
    if policy in {"grant", "revoked_grant", "expired_grant"}:
        session.add(MatterAccessGrant(
            company_id=company.id, matter_id=matter.id, membership_id=members["member"].id,
            effective_from=datetime.now(UTC) - timedelta(days=2),
            revoked_at=datetime.now(UTC) if policy == "revoked_grant" else None,
            expires_at=datetime.now(UTC) - timedelta(days=1)
            if policy == "expired_grant" else None,
        ))
    session.commit()
    context = _context(session, company, members["owner"])
    source_id = str(uuid4())
    permitted = policy in {"visible", "grant"}
    assert matter_is_operational(matter)
    assert can_access(session, context=_context(session, company, members["member"]),
                      matter=matter) == permitted
    intent = _enqueue(session, context, members["member"], matter, source_id)
    if not permitted:
        assert intent is None
        assert _count(session, NotificationDeliveryIntent, company.id) == 0
        assert _count(session, InAppNotification, company.id) == 0
        return
    assert intent is not None
    original_id = intent.id
    assert _enqueue(session, context, members["member"], matter, source_id).id == original_id
    result = delivery.process_notification_delivery_intent(
        session, intent_id=original_id, context=context,
    )
    assert result.delivered
    session.commit()
    assert _count(session, NotificationDeliveryIntent, company.id) == 1
    assert _count(session, InAppNotification, company.id) == 1
    replay = delivery.process_notification_delivery_intent(
        session, intent_id=original_id, context=context,
    )
    assert replay.delivered and replay.intent_id == original_id
    assert _count(session, InAppNotification, company.id) == 1


@pytest.mark.parametrize("existing", [False, True])
def test_enqueue_rechecks_revocation_after_parent_lock(
    visibility_session, monkeypatch, existing,
):
    session = visibility_session
    company, matter, members, _outsider, _team, _other = _seed(session, restricted=True)
    grant = MatterAccessGrant(company_id=company.id, matter_id=matter.id,
                              membership_id=members["member"].id)
    session.add(grant)
    session.commit()
    context = _context(session, company, members["owner"])
    source_id = str(uuid4())
    retained = (
        _enqueue(session, context, members["member"], matter, source_id) if existing else None
    )
    session.commit()
    grant_id = grant.id
    original_guard = delivery.assert_operational_matter

    def revoke_after_parent_lock(*args, **kwargs):
        current = original_guard(*args, **kwargs)
        with Session(session.get_bind()) as writer:
            writer.get(MatterAccessGrant, grant_id).revoked_at = datetime.now(UTC)
            writer.commit()
        return current

    monkeypatch.setattr(delivery, "assert_operational_matter", revoke_after_parent_lock)
    assert _enqueue(session, context, members["member"], matter, source_id) is None
    assert _count(session, NotificationDeliveryIntent, company.id) == int(existing)
    if retained is not None:
        assert session.get(NotificationDeliveryIntent, retained.id).status == "queued"
    assert _count(session, InAppNotification, company.id) == 0


@pytest.mark.parametrize("existing", [False, True])
def test_delivery_rechecks_revocation_at_final_lookup(
    visibility_session, monkeypatch, existing,
):
    session = visibility_session
    company, matter, members, _outsider, _team, _other = _seed(session, restricted=True)
    grant = MatterAccessGrant(company_id=company.id, matter_id=matter.id,
                              membership_id=members["member"].id)
    session.add(grant)
    session.commit()
    context = _context(session, company, members["owner"])
    source_id = str(uuid4())
    intent = _enqueue(session, context, members["member"], matter, source_id)
    assert intent is not None
    if existing:
        session.add(InAppNotification(
            company_id=company.id, matter_id=matter.id,
            recipient_membership_id=members["member"].id,
            event_type=intent.event_type, source_type=intent.source_type, source_id=source_id,
            title="Legacy retained notification", body="Original body",
        ))
    session.commit()
    grant_id = grant.id
    original_permission = delivery._recipient_still_permitted

    def revoke_after_permission_gate(current_session, current_intent):
        permitted = original_permission(current_session, current_intent)
        assert permitted
        with Session(session.get_bind()) as writer:
            writer.get(MatterAccessGrant, grant_id).revoked_at = datetime.now(UTC)
            writer.commit()
        return permitted

    monkeypatch.setattr(delivery, "_recipient_still_permitted", revoke_after_permission_gate)
    result = delivery.process_notification_delivery_intent(
        session, intent_id=intent.id, context=context,
    )
    assert not result.delivered
    assert intent.in_app_notification_id is None
    assert _count(session, InAppNotification, company.id) == int(existing)
    assert _count(session, NotificationDeliveryIntent, company.id) == 1


def test_visible_legacy_notification_is_reused_without_rewrite(visibility_session):
    session = visibility_session
    company, matter, members, _outsider, _team, _other = _seed(session)
    context = _context(session, company, members["owner"])
    source_id = str(uuid4())
    legacy = InAppNotification(
        company_id=company.id, matter_id=matter.id,
        recipient_membership_id=members["member"].id,
        event_type="fresh_visibility", source_type="court_order", source_id=source_id,
        title="Legacy retained notification", body="Original body",
    )
    session.add(legacy)
    session.commit()
    intent = _enqueue(session, context, members["member"], matter, source_id)
    assert intent is not None
    result = delivery.process_notification_delivery_intent(
        session, intent_id=intent.id, context=context,
    )
    assert result.delivered and intent.in_app_notification_id == legacy.id
    assert legacy.title == "Legacy retained notification" and legacy.body == "Original body"
    assert _count(session, InAppNotification, company.id) == 1


def test_enqueue_rejects_cross_tenant_recipient(visibility_session):
    session = visibility_session
    company, matter, members, outsider, _team, _other = _seed(session)
    context = _context(session, company, members["owner"])
    assert _enqueue(session, context, outsider, matter, str(uuid4())) is None
    assert _count(session, NotificationDeliveryIntent, company.id) == 0
    assert session.get(CompanyMembership, outsider.id).company_id != company.id


def test_exact_lookup_does_not_reuse_or_rewrite_sibling_identities(visibility_session):
    session = visibility_session
    company, matter, members, outsider, _team, _other = _seed(session)
    context = _context(session, company, members["owner"])
    source_id = str(uuid4())
    earlier = _enqueue(session, context, members["member"], matter, str(uuid4()))
    assert earlier is not None
    siblings = []
    for changed in ("recipient", "event", "source_type", "source_id", "company"):
        row = InAppNotification(
            company_id=outsider.company_id if changed == "company" else company.id,
            recipient_membership_id=outsider.id if changed == "company"
            else members["assignee"].id if changed == "recipient" else members["member"].id,
            event_type="other_event" if changed == "event" else "fresh_visibility",
            source_type="other_source" if changed == "source_type" else "court_order",
            source_id=str(uuid4()) if changed == "source_id" else source_id,
            title="Sibling retained title", body="Sibling retained body",
        )
        session.add(row)
        siblings.append(row)
    session.commit()
    sibling_ids = {row.id for row in siblings}
    intent = _enqueue(session, context, members["member"], matter, source_id)
    assert intent is not None and intent.id != earlier.id
    result = delivery.process_notification_delivery_intent(
        session, intent_id=intent.id, context=context,
    )
    assert result.delivered and intent.in_app_notification_id not in sibling_ids
    session.commit()
    assert _count(session, InAppNotification, company.id) == 5
    assert all(row.title == "Sibling retained title" and row.body == "Sibling retained body"
               for row in siblings)
    assert _enqueue(session, context, members["member"], matter, source_id).id == intent.id
