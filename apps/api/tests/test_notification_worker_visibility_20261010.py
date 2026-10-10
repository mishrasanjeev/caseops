"""Worker delivery retains the final ACL fence without a browser actor."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import Company, InAppNotification, MatterAccessGrant
from caseops_api.services import notification_delivery as delivery
from tests.test_notification_visibility_queries_20261010 import _context, _enqueue
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_record_access_policy_batch_20261010 import _seed
from tests.test_record_access_policy_batch_20261010 import (
    visibility_session as _visibility_session,
)

visibility_session = _visibility_session


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("worker", [False, True])
@pytest.mark.parametrize("revocation", ["grant", "company"])
def test_final_lookup_rechecks_permission_with_or_without_actor_context(
    visibility_session, monkeypatch, existing, worker, revocation,
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
    retained = None
    if existing:
        retained = InAppNotification(
            company_id=company.id, matter_id=matter.id,
            recipient_membership_id=members["member"].id,
            event_type=intent.event_type, source_type=intent.source_type,
            source_id=source_id, title="Retained original title", body="Retained original body",
        )
        session.add(retained)
    session.commit()
    grant_id, company_id = grant.id, company.id
    original = delivery._recipient_still_permitted

    def revoke_after_early_check(current_session, current_intent):
        permitted = original(current_session, current_intent)
        assert permitted
        with Session(current_session.get_bind()) as writer:
            if revocation == "grant":
                writer.get(MatterAccessGrant, grant_id).revoked_at = datetime.now(UTC)
            else:
                writer.get(Company, company_id).is_active = False
            writer.commit()
        return permitted

    monkeypatch.setattr(delivery, "_recipient_still_permitted", revoke_after_early_check)
    result = delivery.process_notification_delivery_intent(
        session, intent_id=intent.id, company_id=company_id,
        context=None if worker else context,
    )
    session.commit()
    assert not result.delivered
    assert intent.in_app_notification_id is None
    assert intent.attempts == 1
    assert result.external_calls == 0
    assert session.scalar(select(func.count()).select_from(InAppNotification).where(
        InAppNotification.company_id == company_id,
    )) == int(existing)
    if retained is not None:
        session.refresh(retained)
        assert retained.title == "Retained original title"
        assert retained.body == "Retained original body"
