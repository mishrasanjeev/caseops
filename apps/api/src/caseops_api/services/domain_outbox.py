from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    DomainConsumerEffect,
    DomainConsumerEffectState,
    DomainOutboxEvent,
    DomainOutboxState,
)
from caseops_api.db.session import serialize_sqlite_writer
from caseops_api.services.idempotency import canonical_json_sha256

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OutboxEventKeyReusedError(RuntimeError):
    """A stable event key was reused for different immutable event data."""


class StaleOutboxLeaseError(RuntimeError):
    """The caller's event lease/fence no longer owns the row."""


class NonterminalConsumerEffectError(RuntimeError):
    """An outbox event cannot succeed while one of its effects is in flight."""


class ConsumerEffectKeyReusedError(RuntimeError):
    """A consumer effect identity was reused for a different event."""


class StaleConsumerEffectLeaseError(RuntimeError):
    """The caller's consumer-effect lease/fence no longer owns the row."""


class ConsumerEffectClaimOutcome(StrEnum):
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class EnqueuedDomainEvent:
    event: DomainOutboxEvent
    created: bool


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    event_id: str
    company_id: str
    event_key: str
    lease_token: str
    fence_version: int
    attempts: int


@dataclass(frozen=True, slots=True)
class ConsumerEffectClaim:
    outcome: ConsumerEffectClaimOutcome
    effect: DomainConsumerEffect
    lease_token: str | None = None
    fence_version: int | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _event_lock_statement(
    session: Session,
    statement: Select[tuple[DomainOutboxEvent]],
    *,
    skip_locked: bool = False,
) -> Select[tuple[DomainOutboxEvent]]:
    if session.get_bind().dialect.name == "postgresql":
        return statement.with_for_update(
            of=DomainOutboxEvent,
            skip_locked=skip_locked,
        )
    return statement


def _effect_lock_statement(
    session: Session,
    statement: Select[tuple[DomainConsumerEffect]],
) -> Select[tuple[DomainConsumerEffect]]:
    if session.get_bind().dialect.name == "postgresql":
        return statement.with_for_update(of=DomainConsumerEffect)
    return statement


def _required(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required.")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters.")
    return normalized


def _optional(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters.")
    return normalized


def _safe_error(value: str | None) -> str | None:
    return _optional(value, field="last_error_redacted", maximum=500)


def _immutable_event_identity(event: DomainOutboxEvent) -> tuple[object, ...]:
    return (
        event.event_type,
        event.schema_version,
        event.aggregate_type,
        event.aggregate_id,
        event.aggregate_version,
        _aware(event.occurred_at),
        _aware(event.effective_at),
        event.source_command_id,
        event.source_event_id,
        event.producer,
        event.producer_revision,
        event.confidentiality,
        event.correlation_id,
        event.causation_id,
        event.payload_hash,
    )


def enqueue_domain_event(
    session: Session,
    *,
    company_id: str,
    event_key: str,
    event_type: str,
    schema_version: int,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
    occurred_at: datetime,
    effective_at: datetime,
    source_command_id: str | None,
    source_event_id: str | None,
    producer: str,
    confidentiality: str,
    correlation_id: str,
    payload: dict[str, object],
    producer_revision: str | None = None,
    causation_id: str | None = None,
    max_attempts: int = 5,
    now: datetime | None = None,
) -> EnqueuedDomainEvent:
    """Insert one immutable event in the caller's transaction.

    The function deliberately does not commit or invoke a consumer.
    """

    current_time = _aware(now or _now())
    company_id = _required(company_id, field="company_id", maximum=36)
    event_key = _required(event_key, field="event_key", maximum=200)
    event_type = _required(event_type, field="event_type", maximum=120)
    aggregate_type = _required(aggregate_type, field="aggregate_type", maximum=80)
    aggregate_id = _required(aggregate_id, field="aggregate_id", maximum=160)
    producer = _required(producer, field="producer", maximum=120)
    correlation_id = _required(correlation_id, field="correlation_id", maximum=160)
    source_command_id = _optional(
        source_command_id, field="source_command_id", maximum=160
    )
    source_event_id = _optional(source_event_id, field="source_event_id", maximum=160)
    producer_revision = _optional(
        producer_revision, field="producer_revision", maximum=64
    )
    causation_id = _optional(causation_id, field="causation_id", maximum=160)
    if source_command_id is None and source_event_id is None:
        raise ValueError("A source command or source event ID is required.")
    if schema_version <= 0:
        raise ValueError("schema_version must be positive.")
    if aggregate_version < 0:
        raise ValueError("aggregate_version cannot be negative.")
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive.")
    if confidentiality not in {"internal", "confidential", "privileged"}:
        raise ValueError("Unsupported event confidentiality.")
    if not isinstance(payload, dict):
        raise TypeError("Domain event payload must be a JSON object.")

    occurred_at = _aware(occurred_at)
    effective_at = _aware(effective_at)
    payload_hash = canonical_json_sha256(payload)
    candidate = DomainOutboxEvent(
        company_id=company_id,
        event_key=event_key,
        event_type=event_type,
        schema_version=schema_version,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        occurred_at=occurred_at,
        effective_at=effective_at,
        source_command_id=source_command_id,
        source_event_id=source_event_id,
        producer=producer,
        producer_revision=producer_revision,
        confidentiality=confidentiality,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload_hash=payload_hash,
        payload_json=payload,
        state=DomainOutboxState.QUEUED,
        attempts=0,
        max_attempts=max_attempts,
        fence_version=0,
        created_at=current_time,
        updated_at=current_time,
    )
    serialize_sqlite_writer(session)
    statement = select(DomainOutboxEvent).where(
        DomainOutboxEvent.company_id == company_id,
        DomainOutboxEvent.event_key == event_key,
    )
    existing = session.scalar(_event_lock_statement(session, statement))
    if existing is None:
        if session.get_bind().dialect.name == "sqlite":
            # Serialization was acquired before the absent-row lookup.  Avoid
            # a SAVEPOINT as the first SQLite write because a deferred driver
            # BEGIN can make RELEASE SAVEPOINT escape the caller's rollback.
            session.add(candidate)
            session.flush()
            return EnqueuedDomainEvent(event=candidate, created=True)
        try:
            with session.begin_nested():
                session.add(candidate)
                session.flush()
        except IntegrityError:
            existing = session.scalar(_event_lock_statement(session, statement))
            if existing is None:
                # A genuine event-key race leaves its winner visible.  Preserve
                # unrelated FK/check failures instead of disguising them.
                raise
        else:
            return EnqueuedDomainEvent(event=candidate, created=True)

    if _immutable_event_identity(existing) != _immutable_event_identity(candidate):
        raise OutboxEventKeyReusedError(
            "Domain event key is already bound to different immutable data."
        )
    return EnqueuedDomainEvent(event=existing, created=False)


def claim_outbox_events(
    session: Session,
    *,
    lease_owner: str,
    limit: int = 25,
    lease_for: timedelta = timedelta(minutes=5),
    company_id: str | None = None,
    now: datetime | None = None,
) -> list[OutboxClaim]:
    """Claim a disjoint due batch; PostgreSQL uses ``SKIP LOCKED``."""

    current_time = _aware(now or _now())
    lease_owner = _required(lease_owner, field="lease_owner", maximum=120)
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200.")
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive.")

    serialize_sqlite_writer(session)

    eligible = or_(
        and_(
            DomainOutboxEvent.state.in_(
                (DomainOutboxState.QUEUED, DomainOutboxState.RETRY_SCHEDULED)
            ),
            or_(
                DomainOutboxEvent.next_attempt_at.is_(None),
                DomainOutboxEvent.next_attempt_at <= current_time,
            ),
        ),
        and_(
            DomainOutboxEvent.state == DomainOutboxState.PROCESSING,
            DomainOutboxEvent.lease_expires_at <= current_time,
        ),
    )
    statement = (
        select(DomainOutboxEvent)
        .where(eligible)
        .order_by(
            func.coalesce(
                DomainOutboxEvent.next_attempt_at,
                DomainOutboxEvent.created_at,
            ),
            DomainOutboxEvent.created_at,
            DomainOutboxEvent.id,
        )
        .limit(limit)
    )
    if company_id is not None:
        statement = statement.where(DomainOutboxEvent.company_id == company_id)
    rows = list(
        session.scalars(
            _event_lock_statement(session, statement, skip_locked=True)
        ).all()
    )
    claims: list[OutboxClaim] = []
    for event in rows:
        if event.attempts >= event.max_attempts:
            # A worker may disappear after claiming the final permitted
            # attempt.  Once that lease expires, fence it and converge the row
            # to dead letter instead of leaving it stuck in ``processing``.
            event.state = DomainOutboxState.DEAD_LETTER
            event.lease_owner = None
            event.lease_token = None
            event.lease_expires_at = None
            event.next_attempt_at = None
            event.completed_at = None
            event.dead_lettered_at = current_time
            event.dead_letter_reason = "retry_limit_exhausted"
            if event.last_error_redacted is None:
                event.last_error_redacted = "Worker lease expired at retry limit."
            event.updated_at = current_time
            continue
        token = uuid4().hex
        event.state = DomainOutboxState.PROCESSING
        event.attempts += 1
        event.fence_version += 1
        event.lease_owner = lease_owner
        event.lease_token = token
        event.lease_expires_at = current_time + lease_for
        event.next_attempt_at = None
        event.dead_letter_reason = None
        event.updated_at = current_time
        claims.append(
            OutboxClaim(
                event_id=event.id,
                company_id=event.company_id,
                event_key=event.event_key,
                lease_token=token,
                fence_version=event.fence_version,
                attempts=event.attempts,
            )
        )
    session.flush()
    return claims


def _owned_outbox_event(
    session: Session,
    *,
    company_id: str,
    event_id: str,
    lease_token: str,
    fence_version: int,
    now: datetime,
) -> DomainOutboxEvent:
    serialize_sqlite_writer(session)
    statement = select(DomainOutboxEvent).where(
        DomainOutboxEvent.id == event_id,
        DomainOutboxEvent.company_id == company_id,
    )
    event = session.scalar(_event_lock_statement(session, statement))
    if (
        event is None
        or event.state != DomainOutboxState.PROCESSING
        or event.lease_token != lease_token
        or event.fence_version != fence_version
        or event.lease_expires_at is None
        or _aware(event.lease_expires_at) <= now
    ):
        raise StaleOutboxLeaseError("Outbox lease or fencing token is stale.")
    return event


def renew_outbox_lease(
    session: Session,
    *,
    claim: OutboxClaim,
    lease_for: timedelta,
    now: datetime | None = None,
) -> DomainOutboxEvent:
    current_time = _aware(now or _now())
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive.")
    event = _owned_outbox_event(
        session,
        company_id=claim.company_id,
        event_id=claim.event_id,
        lease_token=claim.lease_token,
        fence_version=claim.fence_version,
        now=current_time,
    )
    event.lease_expires_at = current_time + lease_for
    event.updated_at = current_time
    session.flush()
    return event


def complete_outbox_event(
    session: Session,
    *,
    claim: OutboxClaim,
    now: datetime | None = None,
) -> DomainOutboxEvent:
    current_time = _aware(now or _now())
    event = _owned_outbox_event(
        session,
        company_id=claim.company_id,
        event_id=claim.event_id,
        lease_token=claim.lease_token,
        fence_version=claim.fence_version,
        now=current_time,
    )
    processing_effect = session.scalar(
        _effect_lock_statement(
            session,
            select(DomainConsumerEffect)
            .where(
                DomainConsumerEffect.company_id == event.company_id,
                DomainConsumerEffect.outbox_event_id == event.id,
                DomainConsumerEffect.state == DomainConsumerEffectState.PROCESSING,
            )
            .limit(1),
        )
    )
    if processing_effect is not None:
        raise NonterminalConsumerEffectError(
            "Outbox event has a processing consumer effect."
        )
    event.state = DomainOutboxState.SUCCEEDED
    event.lease_owner = None
    event.lease_token = None
    event.lease_expires_at = None
    event.next_attempt_at = None
    event.completed_at = current_time
    event.dead_lettered_at = None
    event.dead_letter_reason = None
    event.last_error_redacted = None
    event.updated_at = current_time
    session.flush()
    return event


def record_outbox_failure(
    session: Session,
    *,
    claim: OutboxClaim,
    last_error_redacted: str,
    retry_at: datetime | None,
    dead_letter_reason: str = "retry_limit_exhausted",
    now: datetime | None = None,
) -> DomainOutboxEvent:
    current_time = _aware(now or _now())
    error = _safe_error(last_error_redacted)
    if error is None:
        raise ValueError("A redacted failure description is required.")
    reason = _required(
        dead_letter_reason, field="dead_letter_reason", maximum=160
    )
    event = _owned_outbox_event(
        session,
        company_id=claim.company_id,
        event_id=claim.event_id,
        lease_token=claim.lease_token,
        fence_version=claim.fence_version,
        now=current_time,
    )
    event.lease_owner = None
    event.lease_token = None
    event.lease_expires_at = None
    event.last_error_redacted = error
    event.completed_at = None
    if retry_at is not None and event.attempts < event.max_attempts:
        retry_at = _aware(retry_at)
        if retry_at <= current_time:
            raise ValueError("retry_at must be in the future.")
        event.state = DomainOutboxState.RETRY_SCHEDULED
        event.next_attempt_at = retry_at
        event.dead_lettered_at = None
        event.dead_letter_reason = None
    else:
        event.state = DomainOutboxState.DEAD_LETTER
        event.next_attempt_at = None
        event.dead_lettered_at = current_time
        event.dead_letter_reason = reason
    event.updated_at = current_time
    session.flush()
    return event


def _claim_effect_row(
    effect: DomainConsumerEffect,
    *,
    consumer_version: str,
    event: DomainOutboxEvent,
    lease_owner: str,
    lease_for: timedelta,
    now: datetime,
) -> ConsumerEffectClaim:
    token = uuid4().hex
    effect.consumer_version = consumer_version
    effect.state = DomainConsumerEffectState.PROCESSING
    effect.attempts += 1
    effect.outbox_fence_version = event.fence_version
    effect.lease_owner = lease_owner
    effect.lease_token = token
    effect.lease_expires_at = min(now + lease_for, _aware(event.lease_expires_at))
    effect.fence_version += 1
    effect.result_type = None
    effect.result_id = None
    effect.result_hash = None
    effect.last_error_redacted = None
    effect.completed_at = None
    effect.failed_at = None
    effect.updated_at = now
    return ConsumerEffectClaim(
        outcome=ConsumerEffectClaimOutcome.CLAIMED,
        effect=effect,
        lease_token=token,
        fence_version=effect.fence_version,
    )


def claim_consumer_effect(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    consumer_name: str,
    consumer_version: str,
    effect_key: str,
    lease_owner: str,
    lease_for: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
) -> ConsumerEffectClaim:
    """Claim a per-consumer effect while the caller owns its source event."""

    current_time = _aware(now or _now())
    consumer_name = _required(consumer_name, field="consumer_name", maximum=120)
    consumer_version = _required(
        consumer_version, field="consumer_version", maximum=64
    )
    effect_key = _required(effect_key, field="effect_key", maximum=200)
    lease_owner = _required(lease_owner, field="lease_owner", maximum=120)
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive.")
    event = _owned_outbox_event(
        session,
        company_id=outbox_claim.company_id,
        event_id=outbox_claim.event_id,
        lease_token=outbox_claim.lease_token,
        fence_version=outbox_claim.fence_version,
        now=current_time,
    )

    statement = select(DomainConsumerEffect).where(
        DomainConsumerEffect.company_id == event.company_id,
        DomainConsumerEffect.consumer_name == consumer_name,
        or_(
            DomainConsumerEffect.effect_key == effect_key,
            DomainConsumerEffect.outbox_event_id == event.id,
        ),
    )
    matches = list(session.scalars(_effect_lock_statement(session, statement)).all())
    if len(matches) > 1:
        raise ConsumerEffectKeyReusedError(
            "Consumer event and effect identities resolve to different rows."
        )
    effect = matches[0] if matches else None
    if effect is None:
        token = uuid4().hex
        effect = DomainConsumerEffect(
            company_id=event.company_id,
            outbox_event_id=event.id,
            consumer_name=consumer_name,
            consumer_version=consumer_version,
            effect_key=effect_key,
            state=DomainConsumerEffectState.PROCESSING,
            attempts=1,
            outbox_fence_version=event.fence_version,
            lease_owner=lease_owner,
            lease_token=token,
            lease_expires_at=min(
                current_time + lease_for,
                _aware(event.lease_expires_at),
            ),
            fence_version=1,
            created_at=current_time,
            updated_at=current_time,
        )
        if session.get_bind().dialect.name == "sqlite":
            session.add(effect)
            session.flush()
            return ConsumerEffectClaim(
                outcome=ConsumerEffectClaimOutcome.CLAIMED,
                effect=effect,
                lease_token=token,
                fence_version=1,
            )
        try:
            with session.begin_nested():
                session.add(effect)
                session.flush()
        except IntegrityError:
            matches = list(
                session.scalars(_effect_lock_statement(session, statement)).all()
            )
            if len(matches) != 1:
                # A genuine uniqueness race leaves exactly one matching effect.
                # Propagate tenant/FK/check violations unchanged.
                raise
            effect = matches[0]
        else:
            return ConsumerEffectClaim(
                outcome=ConsumerEffectClaimOutcome.CLAIMED,
                effect=effect,
                lease_token=token,
                fence_version=1,
            )

    if effect.outbox_event_id != event.id or effect.effect_key != effect_key:
        raise ConsumerEffectKeyReusedError(
            "Consumer effect key is already bound to a different event."
        )
    if effect.state == DomainConsumerEffectState.COMPLETED:
        return ConsumerEffectClaim(
            outcome=ConsumerEffectClaimOutcome.REPLAY,
            effect=effect,
        )
    if (
        effect.state == DomainConsumerEffectState.PROCESSING
        and effect.lease_expires_at is not None
        and _aware(effect.lease_expires_at) > current_time
    ):
        return ConsumerEffectClaim(
            outcome=ConsumerEffectClaimOutcome.IN_PROGRESS,
            effect=effect,
        )
    claimed = _claim_effect_row(
        effect,
        consumer_version=consumer_version,
        event=event,
        lease_owner=lease_owner,
        lease_for=lease_for,
        now=current_time,
    )
    session.flush()
    return claimed


def _owned_consumer_effect(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    effect_id: str,
    effect_lease_token: str,
    effect_fence_version: int,
    now: datetime,
) -> tuple[DomainOutboxEvent, DomainConsumerEffect]:
    event = _owned_outbox_event(
        session,
        company_id=outbox_claim.company_id,
        event_id=outbox_claim.event_id,
        lease_token=outbox_claim.lease_token,
        fence_version=outbox_claim.fence_version,
        now=now,
    )
    statement = select(DomainConsumerEffect).where(
        DomainConsumerEffect.id == effect_id,
        DomainConsumerEffect.company_id == event.company_id,
        DomainConsumerEffect.outbox_event_id == event.id,
    )
    effect = session.scalar(_effect_lock_statement(session, statement))
    if (
        effect is None
        or effect.state != DomainConsumerEffectState.PROCESSING
        or effect.lease_token != effect_lease_token
        or effect.fence_version != effect_fence_version
        or effect.outbox_fence_version != event.fence_version
        or effect.lease_expires_at is None
        or _aware(effect.lease_expires_at) <= now
    ):
        raise StaleConsumerEffectLeaseError(
            "Consumer effect lease or fencing token is stale."
        )
    return event, effect


def renew_consumer_effect_lease(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    effect_id: str,
    effect_lease_token: str,
    effect_fence_version: int,
    lease_for: timedelta,
    now: datetime | None = None,
) -> DomainConsumerEffect:
    """Renew one owned effect without outliving its source-event lease."""

    current_time = _aware(now or _now())
    if lease_for <= timedelta(0):
        raise ValueError("lease_for must be positive.")
    event, effect = _owned_consumer_effect(
        session,
        outbox_claim=outbox_claim,
        effect_id=effect_id,
        effect_lease_token=effect_lease_token,
        effect_fence_version=effect_fence_version,
        now=current_time,
    )
    event_lease_expires_at = event.lease_expires_at
    if event_lease_expires_at is None:
        raise StaleConsumerEffectLeaseError(
            "Source-event lease expired before consumer-effect renewal."
        )
    effect.lease_expires_at = min(
        current_time + lease_for,
        _aware(event_lease_expires_at),
    )
    effect.updated_at = current_time
    session.flush()
    return effect


def complete_consumer_effect(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    effect_id: str,
    effect_lease_token: str,
    effect_fence_version: int,
    result_type: str | None = None,
    result_id: str | None = None,
    result_hash: str | None = None,
    now: datetime | None = None,
) -> DomainConsumerEffect:
    current_time = _aware(now or _now())
    if (result_type is None) != (result_id is None):
        raise ValueError("result_type and result_id must be supplied together.")
    if result_hash is not None and not _SHA256.fullmatch(result_hash):
        raise ValueError("result_hash must be a lowercase SHA-256 digest.")
    _, effect = _owned_consumer_effect(
        session,
        outbox_claim=outbox_claim,
        effect_id=effect_id,
        effect_lease_token=effect_lease_token,
        effect_fence_version=effect_fence_version,
        now=current_time,
    )
    effect.state = DomainConsumerEffectState.COMPLETED
    effect.lease_owner = None
    effect.lease_token = None
    effect.lease_expires_at = None
    effect.result_type = result_type
    effect.result_id = result_id
    effect.result_hash = result_hash
    effect.last_error_redacted = None
    effect.completed_at = current_time
    effect.failed_at = None
    effect.updated_at = current_time
    session.flush()
    return effect


def fail_consumer_effect(
    session: Session,
    *,
    outbox_claim: OutboxClaim,
    effect_id: str,
    effect_lease_token: str,
    effect_fence_version: int,
    last_error_redacted: str,
    now: datetime | None = None,
) -> DomainConsumerEffect:
    current_time = _aware(now or _now())
    error = _safe_error(last_error_redacted)
    if error is None:
        raise ValueError("A redacted failure description is required.")
    _, effect = _owned_consumer_effect(
        session,
        outbox_claim=outbox_claim,
        effect_id=effect_id,
        effect_lease_token=effect_lease_token,
        effect_fence_version=effect_fence_version,
        now=current_time,
    )
    effect.state = DomainConsumerEffectState.FAILED
    effect.lease_owner = None
    effect.lease_token = None
    effect.lease_expires_at = None
    effect.result_type = None
    effect.result_id = None
    effect.result_hash = None
    effect.last_error_redacted = error
    effect.completed_at = None
    effect.failed_at = current_time
    effect.updated_at = current_time
    session.flush()
    return effect


__all__ = (
    "ConsumerEffectClaim",
    "ConsumerEffectClaimOutcome",
    "ConsumerEffectKeyReusedError",
    "EnqueuedDomainEvent",
    "NonterminalConsumerEffectError",
    "OutboxClaim",
    "OutboxEventKeyReusedError",
    "StaleConsumerEffectLeaseError",
    "StaleOutboxLeaseError",
    "claim_consumer_effect",
    "claim_outbox_events",
    "complete_consumer_effect",
    "complete_outbox_event",
    "enqueue_domain_event",
    "fail_consumer_effect",
    "record_outbox_failure",
    "renew_consumer_effect_lease",
    "renew_outbox_lease",
)
