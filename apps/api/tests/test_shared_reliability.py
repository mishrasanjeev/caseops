from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    ApiIdempotencyRecord,
    DomainConsumerEffect,
    DomainConsumerEffectState,
    DomainOutboxEvent,
    DomainOutboxState,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.domain_outbox import (
    ConsumerEffectClaimOutcome,
    NonterminalConsumerEffectError,
    OutboxEventKeyReusedError,
    StaleConsumerEffectLeaseError,
    StaleOutboxLeaseError,
    claim_consumer_effect,
    claim_outbox_events,
    complete_consumer_effect,
    complete_outbox_event,
    enqueue_domain_event,
    record_outbox_failure,
    renew_consumer_effect_lease,
    renew_outbox_lease,
)
from caseops_api.services.idempotency import (
    CanonicalFilePart,
    IdempotencyClaimOutcome,
    StaleIdempotencyClaimError,
    canonical_json_bytes,
    canonical_json_sha256,
    canonical_request_hash,
    claim_idempotency,
    complete_idempotency,
)
from tests.test_auth_company import bootstrap_company

NOW = datetime(2026, 8, 12, 6, 30, tzinfo=UTC)


def test_canonical_json_golden_fixture_is_portable() -> None:
    payload = {
        "z": "π",
        "a": [True, None, 9_007_199_254_740_991],
        "nested": {"b": "line\nbreak", "a": -7},
    }
    encoded = (
        b'{"a":[true,null,9007199254740991],"nested":{"a":-7,'
        b'"b":"line\\nbreak"},"z":"\xcf\x80"}'
    )

    assert canonical_json_bytes(payload) == encoded
    assert canonical_json_sha256(payload) == (
        "d3ee29711006bc7cf74450a18051bf68ba50f25f023ff8d7d3667e312eff609d"
    )
    with pytest.raises(TypeError, match="not canonical"):
        canonical_json_bytes({"amount": 1.0})
    with pytest.raises(ValueError, match="safe range"):
        canonical_json_bytes({"counter": 9_007_199_254_740_992})


def _ids(client: TestClient) -> tuple[str, str]:
    bootstrap = bootstrap_company(client)
    return (
        str(bootstrap["company"]["id"]),
        str(bootstrap["membership"]["id"]),
    )


def _enqueue(
    session,
    *,
    company_id: str,
    event_key: str,
    payload: dict[str, object] | None = None,
    max_attempts: int = 3,
):
    return enqueue_domain_event(
        session,
        company_id=company_id,
        event_key=event_key,
        event_type="ip.legal_state.lifecycle_changed",
        schema_version=1,
        aggregate_type="ip_docket_record",
        aggregate_id="docket-fixture-1",
        aggregate_version=2,
        occurred_at=NOW,
        effective_at=NOW,
        source_command_id="command-fixture-1",
        source_event_id=None,
        producer="caseops-api",
        producer_revision="a" * 40,
        confidentiality="privileged",
        correlation_id="request-fixture-1",
        payload=payload or {"from_state": "draft", "to_state": "active"},
        max_attempts=max_attempts,
        now=NOW,
    )


def test_canonical_request_hash_is_stable_and_includes_ordered_file_evidence() -> None:
    first = CanonicalFilePart(
        field_name="evidence",
        file_name="tm-o.pdf",
        media_type="Application/PDF",
        size_bytes=42,
        content_sha256="a" * 64,
        representation_version="v1",
    )
    second = CanonicalFilePart(
        field_name="annexure",
        file_name="annexure.pdf",
        media_type="application/pdf",
        size_bytes=7,
        content_sha256="b" * 64,
    )
    left = canonical_request_hash(
        {"expected_version": 2, "transition": {"to": "active", "from": "draft"}},
        files=(first, second),
    )
    reordered_object = canonical_request_hash(
        {"transition": {"from": "draft", "to": "active"}, "expected_version": 2},
        files=(first, second),
    )

    assert left == reordered_object
    assert left != canonical_request_hash(
        {"expected_version": 2, "transition": {"to": "active", "from": "draft"}},
        files=(second, first),
    )
    assert left != canonical_request_hash(
        {"expected_version": 3, "transition": {"to": "active", "from": "draft"}},
        files=(first, second),
    )
    with pytest.raises(TypeError, match="Serialize dates"):
        canonical_request_hash({"occurred_at": NOW})


def test_idempotency_claim_in_progress_replay_hash_conflict_and_expiry(
    client: TestClient,
) -> None:
    company_id, membership_id = _ids(client)
    request_hash = canonical_request_hash({"to_state": "active", "expected": 1})
    changed_hash = canonical_request_hash({"to_state": "closed", "expected": 1})

    with get_session_factory()() as session:
        first = claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="post",
            operation="ip.docket.transition",
            idempotency_key="fixture-key-1",
            request_hash=request_hash,
            expires_at=NOW + timedelta(days=30),
            claim_ttl=timedelta(minutes=1),
            now=NOW,
        )
        assert first.outcome == IdempotencyClaimOutcome.CLAIMED
        in_progress = claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="POST",
            operation="ip.docket.transition",
            idempotency_key="fixture-key-1",
            request_hash=request_hash,
            expires_at=NOW + timedelta(days=30),
            now=NOW + timedelta(seconds=10),
        )
        assert in_progress.outcome == IdempotencyClaimOutcome.IN_PROGRESS
        conflict = claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="POST",
            operation="ip.docket.transition",
            idempotency_key="fixture-key-1",
            request_hash=changed_hash,
            expires_at=NOW + timedelta(days=30),
            now=NOW + timedelta(seconds=10),
        )
        assert conflict.outcome == IdempotencyClaimOutcome.KEY_REUSED
        session.commit()

    with get_session_factory()() as session:
        reclaimed = claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="POST",
            operation="ip.docket.transition",
            idempotency_key="fixture-key-1",
            request_hash=request_hash,
            expires_at=NOW + timedelta(days=30),
            claim_ttl=timedelta(minutes=5),
            now=NOW + timedelta(minutes=2),
        )
        assert reclaimed.outcome == IdempotencyClaimOutcome.CLAIMED
        assert reclaimed.claim_generation == 2
        with pytest.raises(StaleIdempotencyClaimError):
            complete_idempotency(
                session,
                company_id=company_id,
                record_id=first.record.id,
                claim_token=str(first.claim_token),
                claim_generation=int(first.claim_generation or 0),
                response_status=200,
                now=NOW + timedelta(minutes=2, seconds=1),
            )
        completed = complete_idempotency(
            session,
            company_id=company_id,
            record_id=reclaimed.record.id,
            claim_token=str(reclaimed.claim_token),
            claim_generation=int(reclaimed.claim_generation or 0),
            response_status=201,
            result_type="ip_docket_record",
            result_id="docket-fixture-1",
            now=NOW + timedelta(minutes=2, seconds=2),
        )
        assert completed.result_id == "docket-fixture-1"
        session.commit()

    with get_session_factory()() as session:
        replay = claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="POST",
            operation="ip.docket.transition",
            idempotency_key="fixture-key-1",
            request_hash=request_hash,
            expires_at=NOW + timedelta(days=30),
            now=NOW + timedelta(minutes=3),
        )
        assert replay.outcome == IdempotencyClaimOutcome.REPLAY
        assert replay.record.response_status == 201
        assert replay.record.result_type == "ip_docket_record"

        after_retention = claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="POST",
            operation="ip.docket.transition",
            idempotency_key="fixture-key-1",
            request_hash=changed_hash,
            expires_at=NOW + timedelta(days=61),
            now=NOW + timedelta(days=31),
        )
        assert after_retention.outcome == IdempotencyClaimOutcome.CLAIMED
        assert after_retention.record.request_hash == changed_hash
        assert after_retention.claim_generation == 3


def test_outbox_enqueue_is_idempotent_and_rolls_back_with_domain_transaction(
    client: TestClient,
) -> None:
    company_id, membership_id = _ids(client)
    with get_session_factory()() as session:
        created = _enqueue(session, company_id=company_id, event_key="event-rollback")
        duplicate = _enqueue(session, company_id=company_id, event_key="event-rollback")
        assert created.created is True
        assert duplicate.created is False
        with pytest.raises(OutboxEventKeyReusedError):
            _enqueue(
                session,
                company_id=company_id,
                event_key="event-rollback",
                payload={"from_state": "draft", "to_state": "closed"},
            )
        claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="POST",
            operation="ip.docket.transition",
            idempotency_key="rollback-key",
            request_hash=canonical_request_hash({"expected": 1}),
            expires_at=NOW + timedelta(days=30),
            now=NOW,
        )
        session.rollback()

    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(DomainOutboxEvent)) == 0
        assert (
            session.scalar(select(func.count()).select_from(ApiIdempotencyRecord))
            == 0
        )


def test_outbox_retry_dead_letter_effect_replay_and_fencing(
    client: TestClient,
) -> None:
    company_id, _ = _ids(client)
    with get_session_factory()() as session:
        event = _enqueue(
            session,
            company_id=company_id,
            event_key="event-effect-once",
            max_attempts=2,
        ).event
        session.commit()
        event_id = event.id

    with get_session_factory()() as session:
        first_claim = claim_outbox_events(
            session,
            lease_owner="worker-a",
            company_id=company_id,
            limit=1,
            lease_for=timedelta(minutes=1),
            now=NOW,
        )[0]
        effect = claim_consumer_effect(
            session,
            outbox_claim=first_claim,
            consumer_name="fixture-projection",
            consumer_version="v1",
            effect_key="projection:docket-fixture-1:v2",
            lease_owner="worker-a",
            lease_for=timedelta(minutes=1),
            now=NOW,
        )
        assert effect.outcome == ConsumerEffectClaimOutcome.CLAIMED
        completed_effect = complete_consumer_effect(
            session,
            outbox_claim=first_claim,
            effect_id=effect.effect.id,
            effect_lease_token=str(effect.lease_token),
            effect_fence_version=int(effect.fence_version or 0),
            result_type="projection",
            result_id="docket-fixture-1:v2",
            result_hash="c" * 64,
            now=NOW + timedelta(seconds=1),
        )
        assert completed_effect.state == DomainConsumerEffectState.COMPLETED
        replay = claim_consumer_effect(
            session,
            outbox_claim=first_claim,
            consumer_name="fixture-projection",
            consumer_version="v1",
            effect_key="projection:docket-fixture-1:v2",
            lease_owner="worker-a",
            now=NOW + timedelta(seconds=2),
        )
        assert replay.outcome == ConsumerEffectClaimOutcome.REPLAY
        record_outbox_failure(
            session,
            claim=first_claim,
            last_error_redacted="fixture provider unavailable",
            retry_at=NOW + timedelta(minutes=2),
            now=NOW + timedelta(seconds=3),
        )
        session.commit()

    with get_session_factory()() as session:
        second_claim = claim_outbox_events(
            session,
            lease_owner="worker-b",
            company_id=company_id,
            limit=1,
            lease_for=timedelta(minutes=1),
            now=NOW + timedelta(minutes=2),
        )[0]
        assert second_claim.event_id == event_id
        assert second_claim.fence_version == 2
        replay = claim_consumer_effect(
            session,
            outbox_claim=second_claim,
            consumer_name="fixture-projection",
            consumer_version="v1",
            effect_key="projection:docket-fixture-1:v2",
            lease_owner="worker-b",
            now=NOW + timedelta(minutes=2, seconds=1),
        )
        assert replay.outcome == ConsumerEffectClaimOutcome.REPLAY
        with pytest.raises(StaleOutboxLeaseError):
            complete_outbox_event(
                session,
                claim=first_claim,
                now=NOW + timedelta(minutes=2, seconds=2),
            )
        dead = record_outbox_failure(
            session,
            claim=second_claim,
            last_error_redacted="fixture poison event",
            retry_at=NOW + timedelta(minutes=3),
            now=NOW + timedelta(minutes=2, seconds=3),
        )
        assert dead.state == DomainOutboxState.DEAD_LETTER
        assert dead.attempts == dead.max_attempts == 2
        assert dead.next_attempt_at is None
        assert dead.dead_lettered_at is not None
        session.commit()

    with get_session_factory()() as session:
        stored = session.get(DomainOutboxEvent, event_id)
        assert stored is not None
        assert stored.state == DomainOutboxState.DEAD_LETTER
        assert session.scalar(select(func.count()).select_from(DomainConsumerEffect)) == 1


def test_outbox_final_attempt_expired_lease_converges_to_dead_letter(
    client: TestClient,
) -> None:
    company_id, _ = _ids(client)
    with get_session_factory()() as session:
        event = _enqueue(
            session,
            company_id=company_id,
            event_key="event-final-lease-expired",
            max_attempts=1,
        ).event
        session.commit()
        event_id = event.id

    with get_session_factory()() as session:
        claim = claim_outbox_events(
            session,
            lease_owner="worker-that-disappears",
            company_id=company_id,
            limit=1,
            lease_for=timedelta(seconds=1),
            now=NOW,
        )[0]
        session.commit()

    with get_session_factory()() as session:
        assert claim_outbox_events(
            session,
            lease_owner="recovery-worker",
            company_id=company_id,
            limit=1,
            now=NOW + timedelta(seconds=2),
        ) == []
        stored = session.get(DomainOutboxEvent, event_id)
        assert stored is not None
        assert stored.state == DomainOutboxState.DEAD_LETTER
        assert stored.dead_letter_reason == "retry_limit_exhausted"
        assert stored.lease_token is None
        with pytest.raises(StaleOutboxLeaseError):
            complete_outbox_event(
                session,
                claim=claim,
                now=NOW + timedelta(seconds=3),
            )


def test_sqlite_idempotency_absent_row_claims_are_serialized(
    client: TestClient,
) -> None:
    company_id, membership_id = _ids(client)
    first_claimed = Event()
    release_first = Event()
    request_hash = canonical_request_hash({"transition": "active"})

    def claim_first() -> IdempotencyClaimOutcome:
        with get_session_factory()() as session:
            claim = claim_idempotency(
                session,
                company_id=company_id,
                actor_scope=f"membership:{membership_id}",
                actor_membership_id=membership_id,
                http_method="POST",
                operation="fixture.concurrent-idempotency",
                idempotency_key="sqlite-concurrent-key",
                request_hash=request_hash,
                expires_at=NOW + timedelta(days=30),
                now=NOW,
            )
            first_claimed.set()
            assert release_first.wait(timeout=5)
            session.commit()
            return claim.outcome

    def claim_second() -> IdempotencyClaimOutcome:
        with get_session_factory()() as session:
            claim = claim_idempotency(
                session,
                company_id=company_id,
                actor_scope=f"membership:{membership_id}",
                actor_membership_id=membership_id,
                http_method="POST",
                operation="fixture.concurrent-idempotency",
                idempotency_key="sqlite-concurrent-key",
                request_hash=request_hash,
                expires_at=NOW + timedelta(days=30),
                now=NOW + timedelta(seconds=1),
            )
            session.commit()
            return claim.outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim_first)
        assert first_claimed.wait(timeout=5)
        second = executor.submit(claim_second)
        assert not second.done()
        release_first.set()
        assert first.result(timeout=5) == IdempotencyClaimOutcome.CLAIMED
        assert second.result(timeout=5) == IdempotencyClaimOutcome.IN_PROGRESS


def test_sqlite_outbox_enqueue_absent_row_claims_are_serialized(
    client: TestClient,
) -> None:
    company_id, _ = _ids(client)
    first_enqueued = Event()
    release_first = Event()

    def enqueue_first() -> bool:
        with get_session_factory()() as session:
            result = _enqueue(
                session,
                company_id=company_id,
                event_key="sqlite-concurrent-enqueue",
            )
            first_enqueued.set()
            assert release_first.wait(timeout=5)
            session.commit()
            return result.created

    def enqueue_second() -> bool:
        with get_session_factory()() as session:
            result = _enqueue(
                session,
                company_id=company_id,
                event_key="sqlite-concurrent-enqueue",
            )
            session.commit()
            return result.created

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(enqueue_first)
        assert first_enqueued.wait(timeout=5)
        second = executor.submit(enqueue_second)
        assert not second.done()
        release_first.set()
        assert first.result(timeout=5) is True
        assert second.result(timeout=5) is False


def test_sqlite_outbox_and_effect_claims_are_serialized(
    client: TestClient,
) -> None:
    company_id, _ = _ids(client)
    with get_session_factory()() as session:
        event = _enqueue(
            session,
            company_id=company_id,
            event_key="sqlite-concurrent-outbox",
        ).event
        session.commit()
        event_id = event.id

    event_claimed = Event()
    release_event_claim = Event()

    def claim_event_first():
        with get_session_factory()() as session:
            claim = claim_outbox_events(
                session,
                company_id=company_id,
                lease_owner="sqlite-worker-a",
                limit=1,
                now=NOW,
            )[0]
            event_claimed.set()
            assert release_event_claim.wait(timeout=5)
            session.commit()
            return claim

    def claim_event_second():
        with get_session_factory()() as session:
            claims = claim_outbox_events(
                session,
                company_id=company_id,
                lease_owner="sqlite-worker-b",
                limit=1,
                now=NOW + timedelta(seconds=1),
            )
            session.commit()
            return claims

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim_event_first)
        assert event_claimed.wait(timeout=5)
        second = executor.submit(claim_event_second)
        assert not second.done()
        release_event_claim.set()
        outbox_claim = first.result(timeout=5)
        assert outbox_claim.event_id == event_id
        assert second.result(timeout=5) == []

    effect_claimed = Event()
    release_effect_claim = Event()

    def claim_effect_first() -> ConsumerEffectClaimOutcome:
        with get_session_factory()() as session:
            claim = claim_consumer_effect(
                session,
                outbox_claim=outbox_claim,
                consumer_name="sqlite-consumer",
                consumer_version="v1",
                effect_key="sqlite-effect-key",
                lease_owner="sqlite-worker-a",
                now=NOW + timedelta(seconds=2),
            )
            effect_claimed.set()
            assert release_effect_claim.wait(timeout=5)
            session.commit()
            return claim.outcome

    def claim_effect_second() -> ConsumerEffectClaimOutcome:
        with get_session_factory()() as session:
            claim = claim_consumer_effect(
                session,
                outbox_claim=outbox_claim,
                consumer_name="sqlite-consumer",
                consumer_version="v1",
                effect_key="sqlite-effect-key",
                lease_owner="sqlite-worker-b",
                now=NOW + timedelta(seconds=3),
            )
            session.commit()
            return claim.outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim_effect_first)
        assert effect_claimed.wait(timeout=5)
        second = executor.submit(claim_effect_second)
        assert not second.done()
        release_effect_claim.set()
        assert first.result(timeout=5) == ConsumerEffectClaimOutcome.CLAIMED
        assert second.result(timeout=5) == ConsumerEffectClaimOutcome.IN_PROGRESS


def test_effect_must_finish_before_event_and_lease_can_be_renewed(
    client: TestClient,
) -> None:
    company_id, _ = _ids(client)
    with get_session_factory()() as session:
        _enqueue(
            session,
            company_id=company_id,
            event_key="event-effect-renewal",
        )
        session.commit()

    with get_session_factory()() as session:
        outbox_claim = claim_outbox_events(
            session,
            company_id=company_id,
            lease_owner="renewal-worker",
            limit=1,
            lease_for=timedelta(minutes=1),
            now=NOW,
        )[0]
        effect_claim = claim_consumer_effect(
            session,
            outbox_claim=outbox_claim,
            consumer_name="renewal-consumer",
            consumer_version="v1",
            effect_key="renewal-effect-key",
            lease_owner="renewal-worker",
            lease_for=timedelta(minutes=1),
            now=NOW,
        )

        with pytest.raises(NonterminalConsumerEffectError):
            complete_outbox_event(
                session,
                claim=outbox_claim,
                now=NOW + timedelta(seconds=10),
            )

        renew_outbox_lease(
            session,
            claim=outbox_claim,
            lease_for=timedelta(minutes=5),
            now=NOW + timedelta(seconds=30),
        )
        renewed = renew_consumer_effect_lease(
            session,
            outbox_claim=outbox_claim,
            effect_id=effect_claim.effect.id,
            effect_lease_token=str(effect_claim.lease_token),
            effect_fence_version=int(effect_claim.fence_version or 0),
            lease_for=timedelta(minutes=4),
            now=NOW + timedelta(seconds=30),
        )
        assert renewed.lease_expires_at is not None
        assert renewed.lease_expires_at == NOW + timedelta(minutes=4, seconds=30)

        with pytest.raises(StaleConsumerEffectLeaseError):
            renew_consumer_effect_lease(
                session,
                outbox_claim=outbox_claim,
                effect_id=effect_claim.effect.id,
                effect_lease_token="stale-token",
                effect_fence_version=int(effect_claim.fence_version or 0),
                lease_for=timedelta(minutes=1),
                now=NOW + timedelta(minutes=2),
            )

        with pytest.raises(StaleConsumerEffectLeaseError):
            renew_consumer_effect_lease(
                session,
                outbox_claim=outbox_claim,
                effect_id=effect_claim.effect.id,
                effect_lease_token=str(effect_claim.lease_token),
                effect_fence_version=int(effect_claim.fence_version or 0) + 1,
                lease_for=timedelta(minutes=1),
                now=NOW + timedelta(minutes=2),
            )

        capped = renew_consumer_effect_lease(
            session,
            outbox_claim=outbox_claim,
            effect_id=effect_claim.effect.id,
            effect_lease_token=str(effect_claim.lease_token),
            effect_fence_version=int(effect_claim.fence_version or 0),
            lease_for=timedelta(minutes=10),
            now=NOW + timedelta(seconds=40),
        )
        assert capped.lease_expires_at == NOW + timedelta(minutes=5, seconds=30)

        complete_consumer_effect(
            session,
            outbox_claim=outbox_claim,
            effect_id=effect_claim.effect.id,
            effect_lease_token=str(effect_claim.lease_token),
            effect_fence_version=int(effect_claim.fence_version or 0),
            now=NOW + timedelta(minutes=2),
        )
        completed = complete_outbox_event(
            session,
            claim=outbox_claim,
            now=NOW + timedelta(minutes=2, seconds=1),
        )
        assert completed.state == DomainOutboxState.SUCCEEDED
        session.commit()
