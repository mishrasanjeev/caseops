"""One fresh participant selection owns each compliance notification decision."""

from types import SimpleNamespace

import pytest

from caseops_api.db.models import NotificationDeliveryChannel
from caseops_api.services import compliance_extraction, compliance_participants


@pytest.mark.parametrize("kind", ["review", "failure"])
@pytest.mark.parametrize("scenario", ["eligible", "no-context", "fence-changed"])
def test_notification_uses_one_current_fence_without_changing_delivery(kind, scenario, monkeypatch):
    session = object()
    matter = SimpleNamespace(id="matter", company_id="company")
    context = SimpleNamespace(membership=SimpleNamespace(id="actor"))
    members = {key: SimpleNamespace(id=key) for key in ("reviewer", "admin")}
    fence = SimpleNamespace(
        context=None if scenario == "no-context" else context,
        memberships=members,
        selection=SimpleNamespace(review_ids=("reviewer",), failure_ids=("reviewer", "admin")),
    )
    reads, deliveries, parent_checks = [], [], []

    def checked_parent(actual_session, *, matter):
        assert actual_session is session
        parent_checks.append(matter)
        return matter

    def checked_fence(actual_session, *, matter, actor_membership_id):
        assert actual_session is session and matter.id == "matter"
        assert actor_membership_id == "actor"
        reads.append("fresh-fence")
        if scenario == "fence-changed":
            raise compliance_participants.ComplianceParticipantFenceError(
                409, detail={"code": "compliance_participants_changed"}
            )
        return fence

    def enqueue(actual_session, **kwargs):
        assert actual_session is session
        deliveries.append(kwargs)

    monkeypatch.setattr(compliance_extraction, "assert_operational_matter", checked_parent)
    monkeypatch.setattr(compliance_participants, "_participant_fence", checked_fence)
    monkeypatch.setattr(compliance_extraction, "enqueue_notification_delivery_intent", enqueue)

    def notify():
        if kind == "review":
            compliance_extraction._notify_review_required(
                session,
                matter=matter,
                actor_membership_id="actor",
                item=SimpleNamespace(
                    id="item", court_order_id="order", description="Review source"
                ),
            )
        else:
            compliance_extraction._notify_extraction_failure(
                session,
                matter=matter,
                actor_membership_id="actor",
                run=SimpleNamespace(
                    id="run",
                    court_order_id="order",
                    error_message_redacted=None,
                    skip_reason="missing source",
                ),
            )

    if scenario == "fence-changed":
        with pytest.raises(compliance_participants.ComplianceParticipantFenceError) as raised:
            notify()
        assert raised.value.detail == {"code": "compliance_participants_changed"}
    else:
        notify()
    assert parent_checks == [matter]
    expected_recipients = (
        []
        if scenario != "eligible"
        else (["reviewer"] if kind == "review" else ["reviewer", "admin"])
    )
    assert [row["recipient_membership"].id for row in deliveries] == expected_recipients
    for row in deliveries:
        assert row["context"] is context and row["matter"] is matter
        assert row["channel"] == NotificationDeliveryChannel.IN_APP
        assert row["linked_court_order_id"] == "order"
        assert (row["event_type"], row["source_type"], row["source_id"]) == (
            ("compliance_review_required", "matter_compliance_item", "item")
            if kind == "review"
            else ("compliance_extraction_failed", "matter_compliance_extraction_run", "run")
        )
        assert row["body"] == ("Review source" if kind == "review" else "missing source")
    assert reads == ["fresh-fence"], "One participant fence must own context and recipients."
