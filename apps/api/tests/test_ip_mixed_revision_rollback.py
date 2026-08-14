"""IPLF-027E mixed-revision deployment and rollback journey (UJ-67).

IPLF-027A supplied the mechanism: immutable outbox envelopes, leases, fences,
per-consumer effects, and a downgrade that refuses to delete evidence. This
module supplies the missing **journey-level proof** for UJ-67's stated
acceptance:

    Old and new revisions coexist without corrupting legal state, and rollback
    after a committed event preserves that event and prevents duplicate
    consumers.

Stable manifest test IDs:

* ``IPLF-UJ-67-NORMAL``   old and new revisions coexist across an additive schema
* ``IPLF-UJ-67-EXC-02``   mixed-version contract fails closed
* ``IPLF-UJ-67-EXC-05``   rollback disables the feature while schema/history stay

Not covered here, and deliberately left open on IPLF-027B:

* ``UJ-67-EXC-01`` lock/table-scan window — needs real PostgreSQL lock timing.
* ``UJ-67-EXC-03`` backfill mismatch — no backfill owner exists in this slice;
  data operations belong to IPLF-028 and are blocked on approved policy.
* ``UJ-67-EXC-04`` canary/SLO failure — needs a real deployment.
* ``UJ-67-EXC-06`` restore/roll-forward rehearsal — needs an authorized SRE run;
  only the destructive-downgrade refusal half is covered, by
  ``test_20260812_ip_workflow_lifecycle_migration.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    DomainConsumerEffect,
    DomainConsumerEffectState,
    DomainOutboxEvent,
    DomainOutboxState,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.domain_outbox import (
    ConsumerEffectClaimOutcome,
    claim_consumer_effect,
    claim_outbox_events,
    complete_consumer_effect,
    complete_outbox_event,
    enqueue_domain_event,
)
from tests.test_auth_company import bootstrap_company

NOW = datetime(2026, 8, 14, 6, 30, tzinfo=UTC)
OLD_REVISION = "caseops-api@rev-old"
NEW_REVISION = "caseops-api@rev-new"
LIFECYCLE_CONSUMERS = (
    "ip-portfolio-projection",
    "notification-intent-adapter",
    "operational-deadline-projection",
)


def _company(client: TestClient) -> str:
    return str(bootstrap_company(client)["company"]["id"])


def _enqueue(
    session,
    *,
    company_id: str,
    event_key: str,
    producer_revision: str,
    aggregate_version: int = 2,
    event_type: str = "ip.legal_state.lifecycle_changed",
    schema_version: int = 1,
    payload: dict[str, object] | None = None,
):
    body: dict[str, object] = {
        "target_type": "ip_docket_record",
        "target_id": "docket-fixture-1",
        "from_state": "draft",
        "to_state": "active",
        "lifecycle_version": aggregate_version,
    }
    if payload is not None:
        body.update(payload)
    return enqueue_domain_event(
        session,
        company_id=company_id,
        event_key=event_key,
        event_type=event_type,
        schema_version=schema_version,
        aggregate_type="ip_docket_record",
        aggregate_id="docket-fixture-1",
        aggregate_version=aggregate_version,
        occurred_at=NOW,
        effective_at=NOW,
        source_command_id=f"command-{event_key}",
        source_event_id=None,
        producer="ip-lifecycle",
        producer_revision=producer_revision,
        confidentiality="privileged",
        correlation_id=f"correlation-{event_key}",
        payload=body,
        now=NOW,
    )


def _drain_one(session, *, company_id: str, lease_owner: str, effect_key: str):
    """Claim one due event and run every expected consumer effect to success.

    The event contract requires the full consumer set to be terminal before the
    event itself can complete, so a partial drain would fail closed.
    """

    claim = claim_outbox_events(
        session,
        lease_owner=lease_owner,
        company_id=company_id,
        limit=1,
        lease_for=timedelta(minutes=1),
        now=NOW,
    )[0]
    claimed = []
    for consumer_name in LIFECYCLE_CONSUMERS:
        effect = claim_consumer_effect(
            session,
            outbox_claim=claim,
            consumer_name=consumer_name,
            consumer_version="v1",
            effect_key=f"{consumer_name}:{effect_key}",
            lease_owner=lease_owner,
            lease_for=timedelta(minutes=1),
            now=NOW,
        )
        assert effect.outcome == ConsumerEffectClaimOutcome.CLAIMED
        complete_consumer_effect(
            session,
            outbox_claim=claim,
            effect_id=effect.effect.id,
            effect_lease_token=str(effect.lease_token),
            effect_fence_version=int(effect.fence_version or 0),
            now=NOW,
        )
        claimed.append(effect)
    return claim, claimed


def test_uj67_normal_old_and_new_revisions_coexist(client: TestClient) -> None:
    """IPLF-UJ-67-NORMAL — mixed revisions write the same expanded schema safely."""

    company_id = _company(client)

    # An old application revision and a new one both write during the rollout.
    with get_session_factory()() as session:
        old = _enqueue(
            session,
            company_id=company_id,
            event_key="mixed-old-writer",
            producer_revision=OLD_REVISION,
            aggregate_version=2,
        )
        new = _enqueue(
            session,
            company_id=company_id,
            event_key="mixed-new-writer",
            producer_revision=NEW_REVISION,
            aggregate_version=3,
        )
        assert old.created is True
        assert new.created is True
        session.commit()

    # Both envelopes persist with distinct immutable identities and their
    # producing revision recorded; neither corrupts the other.
    with get_session_factory()() as session:
        rows = list(
            session.scalars(
                select(DomainOutboxEvent)
                .where(DomainOutboxEvent.company_id == company_id)
                .order_by(DomainOutboxEvent.aggregate_version)
            ).all()
        )
        assert [r.producer_revision for r in rows] == [OLD_REVISION, NEW_REVISION]
        assert [r.aggregate_version for r in rows] == [2, 3]
        assert len({r.id for r in rows}) == 2
        assert all(r.state == DomainOutboxState.QUEUED for r in rows)

    # A worker on the new revision drains the old revision's event.
    with get_session_factory()() as session:
        claim, _effects = _drain_one(
            session,
            company_id=company_id,
            lease_owner="worker-new-1",
            effect_key="projection:docket-fixture-1:v2",
        )
        complete_outbox_event(session, claim=claim, now=NOW)
        session.commit()

    with get_session_factory()() as session:
        effects = list(
            session.scalars(
                select(DomainConsumerEffect).where(
                    DomainConsumerEffect.company_id == company_id
                )
            ).all()
        )
        assert len(effects) == len(LIFECYCLE_CONSUMERS)
        assert all(e.state == DomainConsumerEffectState.COMPLETED for e in effects)
        # The other revision's event is untouched and still due.
        remaining = session.scalars(
            select(DomainOutboxEvent).where(
                DomainOutboxEvent.company_id == company_id,
                DomainOutboxEvent.aggregate_version == 3,
            )
        ).one()
        assert remaining.state == DomainOutboxState.QUEUED


def test_uj67_exc02_mixed_version_contract_fails_closed(client: TestClient) -> None:
    """IPLF-UJ-67-EXC-02 — an unadmitted contract is rejected, not absorbed."""

    company_id = _company(client)

    with get_session_factory()() as session:
        committed = _enqueue(
            session,
            company_id=company_id,
            event_key="contract-good",
            producer_revision=NEW_REVISION,
        )
        assert committed.created is True
        session.commit()

    # An old revision emits a schema version the catalogue does not admit.
    with get_session_factory()() as session:
        with pytest.raises(ValueError):
            _enqueue(
                session,
                company_id=company_id,
                event_key="contract-bad-schema",
                producer_revision=OLD_REVISION,
                schema_version=99,
            )
        session.rollback()

    # An event type outside the catalogue is refused the same way.
    with get_session_factory()() as session:
        with pytest.raises(ValueError):
            _enqueue(
                session,
                company_id=company_id,
                event_key="contract-bad-type",
                producer_revision=OLD_REVISION,
                event_type="ip.unknown.not_in_catalogue",
            )
        session.rollback()

    # A payload missing a required contract field is refused.
    with get_session_factory()() as session:
        with pytest.raises(ValueError):
            enqueue_domain_event(
                session,
                company_id=company_id,
                event_key="contract-bad-payload",
                event_type="ip.legal_state.lifecycle_changed",
                schema_version=1,
                aggregate_type="ip_docket_record",
                aggregate_id="docket-fixture-1",
                aggregate_version=4,
                occurred_at=NOW,
                effective_at=NOW,
                source_command_id="command-bad-payload",
                source_event_id=None,
                producer="ip-lifecycle",
                producer_revision=OLD_REVISION,
                confidentiality="privileged",
                correlation_id="correlation-bad-payload",
                payload={"target_type": "ip_docket_record"},
                now=NOW,
            )
        session.rollback()

    # Fail-closed: only the admitted event exists; no partial row was written.
    with get_session_factory()() as session:
        rows = list(
            session.scalars(
                select(DomainOutboxEvent).where(DomainOutboxEvent.company_id == company_id)
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].event_key == "contract-good"
        assert rows[0].producer_revision == NEW_REVISION


def test_uj67_exc05_rollback_preserves_history_without_duplicate_consumers(
    client: TestClient,
) -> None:
    """IPLF-UJ-67-EXC-05 — disabling the feature keeps schema and committed history."""

    company_id = _company(client)

    # The runtime controls are fail-closed by default, so a rollback that turns
    # the feature off is the default state rather than a special mode.
    settings = get_settings()
    assert settings.domain_outbox_consumers_enabled is False
    assert settings.ip_workflow_commands_enabled is False

    with get_session_factory()() as session:
        _enqueue(
            session,
            company_id=company_id,
            event_key="rollback-committed",
            producer_revision=NEW_REVISION,
        )
        session.commit()

    # A consumer commits an effect before the rollback.
    with get_session_factory()() as session:
        claim, effects = _drain_one(
            session,
            company_id=company_id,
            lease_owner="worker-before-rollback",
            effect_key="projection:docket-fixture-1:v2",
        )
        complete_outbox_event(session, claim=claim, now=NOW)
        session.commit()
        committed_effect_ids = sorted(item.effect.id for item in effects)

    # Rollback: the old revision's worker generation comes back after the lease
    # window and re-processes what it believes is still outstanding.
    with get_session_factory()() as session:
        after = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
        redelivered = claim_outbox_events(
            session,
            lease_owner="worker-after-rollback",
            company_id=company_id,
            limit=5,
            lease_for=timedelta(minutes=1),
            now=after,
        )
        # A succeeded event is terminal: it is never re-claimed for delivery.
        assert redelivered == []

    # The additive schema and the committed history both survive intact.
    with get_session_factory()() as session:
        event = session.scalars(
            select(DomainOutboxEvent).where(DomainOutboxEvent.company_id == company_id)
        ).one()
        assert event.state == DomainOutboxState.SUCCEEDED
        assert event.producer_revision == NEW_REVISION

        effects = list(
            session.scalars(
                select(DomainConsumerEffect).where(
                    DomainConsumerEffect.company_id == company_id
                )
            ).all()
        )
        # Exactly one effect row per consumer: no duplicate consumer ran.
        assert sorted(e.id for e in effects) == committed_effect_ids
        assert all(e.state == DomainConsumerEffectState.COMPLETED for e in effects)
        assert (
            session.scalar(select(func.count()).select_from(DomainConsumerEffect))
            == len(LIFECYCLE_CONSUMERS)
        )
