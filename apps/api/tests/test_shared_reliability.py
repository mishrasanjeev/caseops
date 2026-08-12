from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    ApiIdempotencyRecord,
    AuditEvent,
    Company,
    CompanyMembership,
    DomainConsumerEffect,
    DomainConsumerEffectState,
    DomainOutboxEvent,
    DomainOutboxState,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.domain_outbox import (
    ConsumerEffectClaimOutcome,
    NonterminalConsumerEffectError,
    OutboxEventKeyReusedError,
    StaleConsumerEffectLeaseError,
    StaleDeadLetterDispositionError,
    StaleOutboxLeaseError,
    claim_consumer_effect,
    claim_outbox_events,
    complete_consumer_effect,
    complete_outbox_event,
    domain_event_contract_snapshot,
    enqueue_domain_event,
    fail_consumer_effect,
    record_outbox_failure,
    renew_consumer_effect_lease,
    renew_outbox_lease,
    replay_dead_letter_event,
    resolve_dead_letter_event,
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
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company

NOW = datetime(2026, 8, 12, 6, 30, tzinfo=UTC)
LIFECYCLE_CONSUMERS = (
    "ip-portfolio-projection",
    "notification-intent-adapter",
    "operational-deadline-projection",
)


def test_canonical_json_golden_fixture_is_portable() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "idempotency_canonical_golden.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    for case in fixture["cases"]:
        assert canonical_json_bytes(case["value"]).decode("utf-8") == case["canonical"]
        assert canonical_json_sha256(case["value"]) == case["sha256"]
    with pytest.raises(TypeError, match="not canonical"):
        canonical_json_bytes({"amount": 1.0})
    with pytest.raises(ValueError, match="safe range"):
        canonical_json_bytes({"counter": 9_007_199_254_740_992})
    with pytest.raises(ValueError, match="unpaired surrogate"):
        canonical_json_bytes({"bad": "\ud800"})


def test_runtime_event_contracts_match_the_governance_catalog() -> None:
    catalog_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "ip-implementation"
        / "IP_EVENT_CATALOG.yaml"
    )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    admitted = {
        (contract["name"], contract["version"]): contract
        for contract in domain_event_contract_snapshot()
    }
    governed = {
        (contract["name"], contract["version"]): contract
        for contract in catalog["domain_events"]
    }

    assert set(admitted) == set(governed)
    for identity, runtime_contract in admitted.items():
        governance_contract = governed[identity]
        assert runtime_contract["confidentiality"] == governance_contract[
            "confidentiality"
        ]
        assert sorted(runtime_contract["consumers"]) == sorted(
            governance_contract["consumers"]
        )
        assert list(runtime_contract["required_payload_fields"]) == sorted(
            governance_contract["payload_schema"]["required"]
        )


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
    event_type: str = "ip.legal_state.lifecycle_changed",
    schema_version: int = 1,
    confidentiality: str = "privileged",
):
    event_payload: dict[str, object] = {
        "target_type": "ip_docket_record",
        "target_id": "docket-fixture-1",
        "from_state": "draft",
        "to_state": "active",
        "lifecycle_version": 2,
    }
    if payload is not None:
        event_payload.update(payload)
    return enqueue_domain_event(
        session,
        company_id=company_id,
        event_key=event_key,
        event_type=event_type,
        schema_version=schema_version,
        aggregate_type="ip_docket_record",
        aggregate_id="docket-fixture-1",
        aggregate_version=2,
        occurred_at=NOW,
        effective_at=NOW,
        source_command_id="command-fixture-1",
        source_event_id=None,
        producer="caseops-api",
        producer_revision="a" * 40,
        confidentiality=confidentiality,
        correlation_id="request-fixture-1",
        payload=event_payload,
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


def test_idempotency_claim_in_progress_replay_conflict_and_evidence_retention(
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
            operation="IP.DOCKET.TRANSITION",
            idempotency_key="fixture-key-1",
            request_hash=request_hash,
            claim_ttl=timedelta(minutes=1),
            now=NOW,
        )
        assert first.outcome == IdempotencyClaimOutcome.CLAIMED
        record_id = first.record.id
        original_created_at = first.record.created_at
        in_progress = claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="POST",
            operation="ip.docket.transition",
            idempotency_key="fixture-key-1",
            request_hash=request_hash,
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
            now=NOW + timedelta(days=31),
        )
        assert after_retention.outcome == IdempotencyClaimOutcome.KEY_REUSED
        assert after_retention.record.id == record_id
        assert after_retention.record.request_hash == request_hash
        persisted_created_at = after_retention.record.created_at
        if persisted_created_at.tzinfo is None:
            persisted_created_at = persisted_created_at.replace(tzinfo=UTC)
        assert persisted_created_at == original_created_at
        assert after_retention.record.claim_generation == 2


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
            now=NOW,
        )
        session.rollback()

    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(DomainOutboxEvent)) == 0
        assert (
            session.scalar(select(func.count()).select_from(ApiIdempotencyRecord))
            == 0
        )


def test_outbox_catalog_payload_and_database_envelope_guards(
    client: TestClient,
) -> None:
    company_id, _ = _ids(client)
    with get_session_factory()() as session:
        with pytest.raises(ValueError, match="not admitted"):
            _enqueue(
                session,
                company_id=company_id,
                event_key="unknown-event",
                event_type="fixture.event",
                confidentiality="internal",
            )
        with pytest.raises(ValueError, match="not allowlisted"):
            _enqueue(
                session,
                company_id=company_id,
                event_key="sensitive-payload",
                payload={"access_token": "must-not-land"},
            )
        enqueued = _enqueue(
            session,
            company_id=company_id,
            event_key="immutable-envelope",
        )
        assert enqueued.event.expected_consumers == LIFECYCLE_CONSUMERS
        event_id = enqueued.event.id
        session.commit()

    with get_session_factory()() as session:
        stored = session.get(DomainOutboxEvent, event_id)
        assert stored is not None
        assert tuple(stored.expected_consumers_json) == LIFECYCLE_CONSUMERS
        with pytest.raises(IntegrityError, match="envelope is immutable"):
            session.execute(
                update(DomainOutboxEvent)
                .where(DomainOutboxEvent.id == event_id)
                .values(aggregate_version=stored.aggregate_version + 1)
            )
            session.commit()
        session.rollback()


def test_idempotency_retention_and_actor_identity_are_server_owned(
    client: TestClient,
) -> None:
    company_id, membership_id = _ids(client)
    with get_session_factory()() as session:
        with pytest.raises(ValueError, match="identify the supplied membership"):
            claim_idempotency(
                session,
                company_id=company_id,
                actor_scope="system:not-the-member",
                actor_membership_id=membership_id,
                http_method="POST",
                operation="ip.legal_state.lifecycle_change",
                idempotency_key="actor-mismatch",
                request_hash=canonical_request_hash({"expected": 1}),
                now=NOW,
            )
        claimed = claim_idempotency(
            session,
            company_id=company_id,
            actor_scope=f"membership:{membership_id}",
            actor_membership_id=membership_id,
            http_method="POST",
            operation="ip.legal_state.lifecycle_change",
            idempotency_key="server-retention",
            request_hash=canonical_request_hash({"expected": 1}),
            now=NOW,
        )
        assert claimed.record.expires_at >= NOW + timedelta(days=365)
        record_id = claimed.record.id
        session.commit()

    with get_session_factory()() as session:
        with pytest.raises(IntegrityError, match="identity is immutable"):
            session.execute(
                update(ApiIdempotencyRecord)
                .where(ApiIdempotencyRecord.id == record_id)
                .values(request_hash="f" * 64)
            )
            session.commit()
        session.rollback()


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
            consumer_name="ip-portfolio-projection",
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
            consumer_name="ip-portfolio-projection",
            consumer_version="v1",
            effect_key="projection:docket-fixture-1:v2",
            lease_owner="worker-a",
            now=NOW + timedelta(seconds=2),
        )
        assert replay.outcome == ConsumerEffectClaimOutcome.REPLAY
        retry = record_outbox_failure(
            session,
            claim=first_claim,
            last_error_redacted=(
                "Authorization: Bearer top-secret; password=hunter2 provider unavailable"
            ),
            retry_at=NOW + timedelta(minutes=2),
            now=NOW + timedelta(seconds=3),
        )
        assert retry.last_error_redacted is not None
        assert "top-secret" not in retry.last_error_redacted
        assert "hunter2" not in retry.last_error_redacted
        assert "[REDACTED]" in retry.last_error_redacted
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
            consumer_name="ip-portfolio-projection",
            consumer_version="v1",
            effect_key="projection:docket-fixture-1:v2",
            lease_owner="worker-b",
            now=NOW + timedelta(minutes=2, seconds=1),
        )
        assert replay.outcome == ConsumerEffectClaimOutcome.REPLAY
        poison_effect = claim_consumer_effect(
            session,
            outbox_claim=second_claim,
            consumer_name="notification-intent-adapter",
            consumer_version="v1",
            effect_key="notification:docket-fixture-1:v2",
            lease_owner="worker-b",
            now=NOW + timedelta(minutes=2, seconds=1),
        )
        fail_consumer_effect(
            session,
            outbox_claim=second_claim,
            effect_id=poison_effect.effect.id,
            effect_lease_token=str(poison_effect.lease_token),
            effect_fence_version=int(poison_effect.fence_version or 0),
            last_error_redacted="schema-rejected notification intent",
            now=NOW + timedelta(minutes=2, seconds=2),
        )
        with pytest.raises(
            NonterminalConsumerEffectError,
            match="missing=1, nonterminal=1",
        ):
            complete_outbox_event(
                session,
                claim=second_claim,
                now=NOW + timedelta(minutes=2, seconds=2),
            )
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
        assert session.scalar(select(func.count()).select_from(DomainConsumerEffect)) == 2


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
        effect = claim_consumer_effect(
            session,
            outbox_claim=claim,
            consumer_name="ip-portfolio-projection",
            consumer_version="v1",
            effect_key="expired-parent-effect",
            lease_owner="worker-that-disappears",
            lease_for=timedelta(seconds=1),
            now=NOW,
        )
        effect_id = effect.effect.id
        effect_fence = int(effect.fence_version or 0)
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
        stored_effect = session.get(DomainConsumerEffect, effect_id)
        assert stored_effect is not None
        assert stored_effect.state == DomainConsumerEffectState.FAILED
        assert stored_effect.fence_version == effect_fence + 1
        assert stored_effect.lease_token is None
        with pytest.raises(StaleOutboxLeaseError):
            complete_outbox_event(
                session,
                claim=claim,
                now=NOW + timedelta(seconds=3),
            )


def test_dead_letter_ignore_and_replay_are_tenant_scoped_audited_transitions(
    client: TestClient,
) -> None:
    company_id, membership_id = _ids(client)
    with get_session_factory()() as session:
        event_id = _enqueue(
            session,
            company_id=company_id,
            event_key="dead-letter-operator-transition",
            max_attempts=1,
        ).event.id
        session.commit()

    with get_session_factory()() as session:
        claim = claim_outbox_events(
            session,
            company_id=company_id,
            lease_owner="poison-worker",
            limit=1,
            now=NOW,
        )[0]
        dead_letter = record_outbox_failure(
            session,
            claim=claim,
            last_error_redacted="poison input",
            retry_at=NOW + timedelta(minutes=1),
            now=NOW + timedelta(seconds=1),
        )
        terminal_fence = dead_letter.fence_version
        company = session.get(Company, company_id)
        membership = session.get(CompanyMembership, membership_id)
        assert company is not None and membership is not None
        user = session.get(User, membership.user_id)
        assert user is not None
        context = SessionContext(company=company, membership=membership, user=user)

        ignored = resolve_dead_letter_event(
            session,
            context=context,
            event_id=event_id,
            expected_fence_version=terminal_fence,
            resolution="ignored",
            reason="Authorization=Bearer operator-secret duplicate source evidence",
            now=NOW + timedelta(seconds=2),
        )
        assert ignored.dead_letter_resolution == "ignored"
        assert ignored.dead_letter_resolved_at is not None
        with pytest.raises(StaleDeadLetterDispositionError):
            replay_dead_letter_event(
                session,
                context=context,
                event_id=event_id,
                expected_fence_version=terminal_fence,
                reason="stale replay",
                now=NOW + timedelta(seconds=3),
            )
        replayed = replay_dead_letter_event(
            session,
            context=context,
            event_id=event_id,
            expected_fence_version=ignored.fence_version,
            reason="corrected source evidence is now available",
            now=NOW + timedelta(seconds=4),
        )
        assert replayed.state == DomainOutboxState.QUEUED
        assert replayed.attempts == 0
        assert replayed.dead_letter_resolution is None
        session.commit()

    with get_session_factory()() as session:
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.target_id == event_id,
                )
            ).all()
        )
        assert {audit.action for audit in audits} == {
            "domain_outbox.dead_letter.ignored",
            "domain_outbox.dead_letter.replayed",
        }
        assert all("operator-secret" not in (audit.metadata_json or "") for audit in audits)


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
                consumer_name="ip-portfolio-projection",
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
                consumer_name="ip-portfolio-projection",
                consumer_version="v1",
                effect_key="sqlite-effect-key",
                lease_owner="sqlite-worker-b",
                now=NOW + timedelta(seconds=3),
            )
            session.commit()
            return claim.outcome

    def claim_unregistered_effect() -> None:
        with get_session_factory()() as session:
            with pytest.raises(ValueError, match="not admitted"):
                claim_consumer_effect(
                    session,
                    outbox_claim=outbox_claim,
                    consumer_name="unregistered-consumer",
                    consumer_version="v1",
                    effect_key="unregistered-effect-key",
                    lease_owner="sqlite-worker-c",
                    now=NOW + timedelta(seconds=3),
                )

    claim_unregistered_effect()

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
        with pytest.raises(NonterminalConsumerEffectError, match="missing=3"):
            complete_outbox_event(
                session,
                claim=outbox_claim,
                now=NOW + timedelta(seconds=1),
            )
        effect_claim = claim_consumer_effect(
            session,
            outbox_claim=outbox_claim,
            consumer_name="ip-portfolio-projection",
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
        for consumer_name in LIFECYCLE_CONSUMERS[1:]:
            additional_claim = claim_consumer_effect(
                session,
                outbox_claim=outbox_claim,
                consumer_name=consumer_name,
                consumer_version="v1",
                effect_key=f"renewal-effect-key:{consumer_name}",
                lease_owner="renewal-worker",
                now=NOW + timedelta(minutes=2),
            )
            complete_consumer_effect(
                session,
                outbox_claim=outbox_claim,
                effect_id=additional_claim.effect.id,
                effect_lease_token=str(additional_claim.lease_token),
                effect_fence_version=int(additional_claim.fence_version or 0),
                now=NOW + timedelta(minutes=2),
            )
        completed = complete_outbox_event(
            session,
            claim=outbox_claim,
            now=NOW + timedelta(minutes=2, seconds=1),
        )
        assert completed.state == DomainOutboxState.SUCCEEDED
        session.commit()
