"""Bounded workers and release checks for the tenant-private index.

Every invocation owns exactly one tenant.  Source enumeration, provider
batches, projection writes, verification and activation never combine tenant
payloads.  Public authorities are intentionally absent from this module.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
    IpProceeding,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateIndexProjectionScope,
    PrivateProjectionEvent,
    TrademarkApplication,
)
from caseops_api.services.embeddings import EmbeddingProvider
from caseops_api.services.private_retrieval import (
    PrivateProjectionInput,
    PrivateRetrievalInvariantError,
    ProjectionScopeInput,
    activate_private_generation,
    apply_private_projection_event,
    create_shadow_private_generation,
    ensure_active_private_generation,
    mark_private_generation_ready,
    private_source_version,
    upsert_private_projection,
)

MAX_PRIVATE_REBUILD_PROJECTIONS = 2_000
MAX_PRIVATE_PROVIDER_BATCH = 32
MAX_PRIVATE_EMBED_TEXT_CHARS = 4_000
MAX_PENDING_EVENTS_PER_RUN = 100
MAX_PRIVATE_MAINTENANCE_COMPANIES = 50
MAX_PRIVATE_EVENT_ATTEMPTS = 3
DEFAULT_PRIVATE_EVENT_RETRY_BACKOFF_SECONDS = 30
DEFAULT_PRIVATE_EVENT_LAG_SLO_SECONDS = 300
DEFAULT_PRIVATE_PROVIDER_DEADLINE_SECONDS = 30.0
LOW_OCR_QUALITY_THRESHOLD = 0.65


@dataclass(frozen=True, slots=True)
class PrivateRebuildSummary:
    company_id: str
    previous_generation_id: str
    generation_id: str
    projection_count: int
    provider_batch_count: int
    provider_text_count: int
    activated: bool


@dataclass(frozen=True, slots=True)
class PrivateIntegrityReport:
    company_id: str
    state: str
    active_generation_id: str | None
    live_projection_count: int
    tombstoned_projection_count: int
    pending_event_count: int
    failed_event_count: int
    oldest_pending_lag_seconds: int | None
    orphan_scope_count: int
    stale_source_count: int
    unsafe_tombstone_count: int
    generation_manifest_matches: bool
    blockers: tuple[str, ...]

    @property
    def release_blocked(self) -> bool:
        return bool(self.blockers)


@dataclass(frozen=True, slots=True)
class PrivateMaintenanceCandidates:
    company_ids: tuple[str, ...]
    truncated: bool


def list_private_maintenance_companies(
    session: Session,
    *,
    limit: int = MAX_PRIVATE_MAINTENANCE_COMPANIES,
) -> PrivateMaintenanceCandidates:
    """Select a bounded tenant set from indexed private operational state."""

    bounded = max(1, min(limit, MAX_PRIVATE_MAINTENANCE_COMPANIES))
    event_companies = select(PrivateProjectionEvent.company_id.label("company_id")).where(
        PrivateProjectionEvent.status.in_(("pending", "failed"))
    )
    generation_companies = select(PrivateIndexGeneration.company_id.label("company_id")).where(
        PrivateIndexGeneration.state.in_(("building", "ready", "active", "failed"))
    )
    candidates = event_companies.union(generation_companies).subquery()
    rows = tuple(
        str(value)
        for value in session.scalars(
            select(candidates.c.company_id).order_by(candidates.c.company_id).limit(bounded + 1)
        ).all()
    )
    return PrivateMaintenanceCandidates(
        company_ids=rows[:bounded],
        truncated=len(rows) > bounded,
    )


def _bounded_append(
    payloads: list[PrivateProjectionInput],
    payload: PrivateProjectionInput,
    *,
    limit: int,
) -> None:
    if len(payloads) >= limit:
        raise PrivateRetrievalInvariantError(
            "Private rebuild exceeded its bounded projection limit; leave the "
            "last verified generation active and resume through a larger offline plan."
        )
    payloads.append(payload)


def _private_projection_inputs(
    session: Session,
    *,
    company_id: str,
    limit: int,
) -> list[PrivateProjectionInput]:
    """Read only canonical, currently active, tenant-owned source rows."""

    bounded = max(1, min(limit, MAX_PRIVATE_REBUILD_PROJECTIONS))
    payloads: list[PrivateProjectionInput] = []

    clients = session.scalars(
        select(Client)
        .where(Client.company_id == company_id, Client.is_active.is_(True))
        .order_by(Client.id)
        .limit(bounded + 1)
    ).all()
    for row in clients:
        _bounded_append(
            payloads,
            PrivateProjectionInput(
                source_type="client",
                source_id=row.id,
                source_version=private_source_version(row),
                chunk_ordinal=0,
                label=row.name,
                content=f"Client {row.name}. Type {row.client_type}. KYC {row.kyc_status}.",
                scopes=(
                    ProjectionScopeInput(
                        scope_type="client",
                        scope_id=row.id,
                        access_policy_version=1,
                    ),
                ),
            ),
            limit=bounded,
        )

    remaining = bounded - len(payloads)
    matters = session.scalars(
        select(Matter)
        .where(Matter.company_id == company_id, Matter.is_active.is_(True))
        .order_by(Matter.id)
        .limit(remaining + 1)
    ).all()
    for row in matters:
        text = " ".join(
            value
            for value in (
                f"Matter {row.matter_code}: {row.title}.",
                f"Status {row.status}.",
                f"Practice area {row.practice_area}.",
                f"Forum {row.court_name or row.forum_level}.",
                f"Client {row.client_name}." if row.client_name else "",
                row.description or "",
            )
            if value
        )
        _bounded_append(
            payloads,
            PrivateProjectionInput(
                source_type="matter",
                source_id=row.id,
                source_version=private_source_version(row),
                chunk_ordinal=0,
                label=f"{row.matter_code} · {row.title}",
                content=text,
                scopes=(
                    ProjectionScopeInput(
                        scope_type="matter",
                        scope_id=row.id,
                        access_policy_version=row.access_policy_version,
                    ),
                ),
            ),
            limit=bounded,
        )

    remaining = bounded - len(payloads)
    attachment_rows = session.execute(
        select(MatterAttachmentChunk, MatterAttachment, Matter)
        .join(MatterAttachment, MatterAttachment.id == MatterAttachmentChunk.attachment_id)
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(
            Matter.company_id == company_id,
            Matter.is_active.is_(True),
            MatterAttachment.processing_status == "indexed",
            MatterAttachmentChunk.content != "",
        )
        .order_by(MatterAttachment.id, MatterAttachmentChunk.chunk_index)
        .limit(remaining + 1)
    ).all()
    for chunk, attachment, matter in attachment_rows:
        _bounded_append(
            payloads,
            PrivateProjectionInput(
                source_type="matter_document",
                source_id=attachment.id,
                source_version=attachment.sha256_hex,
                chunk_ordinal=chunk.chunk_index,
                label=attachment.original_filename,
                content=chunk.content[:MAX_PRIVATE_EMBED_TEXT_CHARS],
                scopes=(
                    ProjectionScopeInput(
                        scope_type="matter",
                        scope_id=matter.id,
                        access_policy_version=matter.access_policy_version,
                    ),
                ),
            ),
            limit=bounded,
        )

    remaining = bounded - len(payloads)
    dockets = session.scalars(
        select(IpDocketRecord)
        .where(
            IpDocketRecord.company_id == company_id,
            IpDocketRecord.is_active.is_(True),
        )
        .order_by(IpDocketRecord.id)
        .limit(remaining + 1)
    ).all()
    for row in dockets:
        _bounded_append(
            payloads,
            PrivateProjectionInput(
                source_type="ip_docket",
                source_id=row.id,
                source_version=private_source_version(row),
                chunk_ordinal=0,
                label=row.title,
                content=(
                    f"IP docket {row.title}. Type {row.record_type}. Status {row.status}. "
                    f"Primary identifier {row.primary_identifier or 'not allocated'}."
                ),
                scopes=(
                    ProjectionScopeInput(
                        scope_type="ip_docket",
                        scope_id=row.id,
                        access_policy_version=row.access_policy_version,
                    ),
                ),
            ),
            limit=bounded,
        )

    remaining = bounded - len(payloads)
    document_rows = session.execute(
        select(IpDocument, IpDocumentVersion)
        .join(
            IpDocumentVersion,
            and_(
                IpDocumentVersion.document_id == IpDocument.id,
                IpDocumentVersion.version == IpDocument.current_version,
            ),
        )
        .where(
            IpDocument.company_id == company_id,
            IpDocument.confidentiality == "internal",
            IpDocument.is_privileged.is_(False),
            IpDocumentVersion.processing_status == "indexed",
            IpDocumentVersion.extracted_text.is_not(None),
            or_(
                IpDocumentVersion.ocr_quality_score.is_(None),
                IpDocumentVersion.ocr_quality_score >= LOW_OCR_QUALITY_THRESHOLD,
            ),
        )
        .order_by(IpDocument.id)
        .limit(remaining + 1)
    ).all()
    document_ids = {document.id for document, _version in document_rows}
    links = session.scalars(
        select(IpDocumentLink).where(
            IpDocumentLink.company_id == company_id,
            IpDocumentLink.document_id.in_(document_ids),
        )
    ).all()
    target_models = {
        "application": TrademarkApplication,
        "proceeding": IpProceeding,
        "event": IpDocketEvent,
        "deadline": IpDeadline,
    }
    targets: dict[tuple[str, str], str] = {}
    grouped_targets: dict[str, set[str]] = defaultdict(set)
    links_by_document: dict[str, list[IpDocumentLink]] = defaultdict(list)
    for link in links:
        links_by_document[link.document_id].append(link)
        if link.target_type == "docket":
            targets[(link.target_type, link.target_id)] = link.target_id
        elif link.target_type in target_models:
            grouped_targets[link.target_type].add(link.target_id)
    for target_type, target_ids in grouped_targets.items():
        model = target_models[target_type]
        rows = session.execute(
            select(model.id, model.docket_id).where(
                model.company_id == company_id,
                model.id.in_(target_ids),
            )
        ).all()
        targets.update(
            {(target_type, str(target_id)): str(docket_id) for target_id, docket_id in rows}
        )
    docket_ids = set(targets.values())
    docket_versions = {
        str(row.id): int(row.access_policy_version)
        for row in session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.company_id == company_id,
                IpDocketRecord.id.in_(docket_ids),
                IpDocketRecord.is_active.is_(True),
            )
        ).all()
    }
    for document, version in document_rows:
        linked = links_by_document.get(document.id, [])
        linked_dockets = {targets.get((link.target_type, link.target_id)) for link in linked}
        if not linked or None in linked_dockets or not linked_dockets:
            continue
        if not set(linked_dockets).issubset(docket_versions):
            continue
        scopes = tuple(
            ProjectionScopeInput(
                scope_type="ip_docket",
                scope_id=docket_id,
                access_policy_version=docket_versions[docket_id],
            )
            for docket_id in sorted(linked_dockets)
            if docket_id is not None
        )
        extracted = " ".join((version.extracted_text or "").split())
        for ordinal, offset in enumerate(range(0, len(extracted), MAX_PRIVATE_EMBED_TEXT_CHARS)):
            text = extracted[offset : offset + MAX_PRIVATE_EMBED_TEXT_CHARS]
            if not text:
                continue
            _bounded_append(
                payloads,
                PrivateProjectionInput(
                    source_type="ip_document",
                    source_id=document.id,
                    source_version=str(document.current_version),
                    chunk_ordinal=ordinal,
                    label=document.title,
                    content=text,
                    scopes=scopes,
                    source_state="indexed",
                ),
                limit=bounded,
            )
    latest_events = (
        select(
            PrivateProjectionEvent.target_type.label("target_type"),
            PrivateProjectionEvent.target_id.label("target_id"),
            PrivateProjectionEvent.event_type.label("event_type"),
            func.row_number()
            .over(
                partition_by=(
                    PrivateProjectionEvent.target_type,
                    PrivateProjectionEvent.target_id,
                ),
                order_by=(
                    PrivateProjectionEvent.created_at.desc(),
                    PrivateProjectionEvent.id.desc(),
                ),
            )
            .label("event_rank"),
        )
        .where(
            PrivateProjectionEvent.company_id == company_id,
            PrivateProjectionEvent.status == "applied",
        )
        .subquery()
    )
    tombstone_rows = session.execute(
        select(latest_events.c.target_type, latest_events.c.target_id)
        .where(
            latest_events.c.event_rank == 1,
            latest_events.c.event_type.in_(("revoked", "tombstoned")),
        )
        .order_by(latest_events.c.target_type, latest_events.c.target_id)
        .limit(bounded + 1)
    ).all()
    if len(tombstone_rows) > bounded:
        raise PrivateRetrievalInvariantError(
            "Private tombstone ledger exceeds the bounded rebuild limit."
        )
    tombstones = {(str(kind), str(target_id)) for kind, target_id in tombstone_rows}
    if ("tenant", company_id) in tombstones:
        return []
    return [
        payload
        for payload in payloads
        if (payload.source_type, payload.source_id) not in tombstones
        and not any((scope.scope_type, scope.scope_id) in tombstones for scope in payload.scopes)
    ]


def _reuse_current_embeddings(
    session: Session,
    *,
    company_id: str,
    generation_id: str,
    payloads: Sequence[PrivateProjectionInput],
    limit: int,
) -> list[PrivateProjectionInput]:
    rows = session.scalars(
        select(PrivateIndexProjection)
        .where(
            PrivateIndexProjection.company_id == company_id,
            PrivateIndexProjection.generation_id == generation_id,
            PrivateIndexProjection.is_tombstoned.is_(False),
            PrivateIndexProjection.embedding_json.is_not(None),
        )
        .order_by(PrivateIndexProjection.id)
        .limit(limit + 1)
    ).all()
    if len(rows) > limit:
        raise PrivateRetrievalInvariantError(
            "Private embedding reuse exceeds the bounded rebuild limit."
        )
    reusable = {
        (
            row.source_type,
            row.source_id,
            row.source_version,
            row.chunk_ordinal,
            row.content_sha256,
        ): row
        for row in rows
    }
    reused: list[PrivateProjectionInput] = []
    for payload in payloads:
        content_hash = hashlib.sha256(payload.content.encode()).hexdigest()
        row = reusable.get(
            (
                payload.source_type,
                payload.source_id,
                payload.source_version,
                payload.chunk_ordinal,
                content_hash,
            )
        )
        if row is None or row.embedding_json is None:
            reused.append(payload)
            continue
        try:
            vector = tuple(float(value) for value in json.loads(row.embedding_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            reused.append(payload)
            continue
        if not vector or row.embedding_dimensions != len(vector):
            reused.append(payload)
            continue
        reused.append(
            replace(
                payload,
                embedding=vector,
                embedding_model=row.embedding_model,
                embedding_version=row.embedding_version,
            )
        )
    return reused


def _embed_private_payloads(
    payloads: Sequence[PrivateProjectionInput],
    *,
    provider: EmbeddingProvider,
    allow_external_provider: bool,
    provider_deadline_seconds: float,
) -> tuple[list[PrivateProjectionInput], int]:
    provider_name = str(provider.name).casefold()
    if provider_name not in {"mock", "fastembed"} and not allow_external_provider:
        raise PrivateRetrievalInvariantError(
            "External private embedding is disabled until tenant/provider policy permits it."
        )
    embedded: list[PrivateProjectionInput] = []
    batch_count = 0
    deadline = max(0.01, min(float(provider_deadline_seconds), 120.0))
    for offset in range(0, len(payloads), MAX_PRIVATE_PROVIDER_BATCH):
        batch = list(payloads[offset : offset + MAX_PRIVATE_PROVIDER_BATCH])
        # The provider receives only the already-approved, bounded source text.
        # Labels, tenant IDs, record IDs, ACLs and projection metadata stay local.
        texts = [payload.content[:MAX_PRIVATE_EMBED_TEXT_CHARS] for payload in batch]
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="private-embed")
        future = executor.submit(provider.embed, texts, input_type="document")
        try:
            result = future.result(timeout=deadline)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise PrivateRetrievalInvariantError(
                "The private embedding provider exceeded its bounded deadline."
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if len(result.vectors) != len(batch):
            raise PrivateRetrievalInvariantError(
                "The embedding provider returned an incomplete private batch."
            )
        batch_count += 1
        embedded.extend(
            replace(
                payload,
                embedding=tuple(float(value) for value in vector),
                embedding_model=result.model,
                embedding_version=f"{result.provider}:{result.dimensions}",
            )
            for payload, vector in zip(batch, result.vectors, strict=True)
        )
    return embedded, batch_count


def rebuild_private_index(
    session: Session,
    *,
    company_id: str,
    provider: EmbeddingProvider | None = None,
    allow_external_provider: bool = False,
    provider_deadline_seconds: float = DEFAULT_PRIVATE_PROVIDER_DEADLINE_SECONDS,
    projection_limit: int = MAX_PRIVATE_REBUILD_PROJECTIONS,
    activate: bool = False,
) -> PrivateRebuildSummary:
    """Build and verify one tenant shadow without stale-worker resurrection.

    Source enumeration and shadow creation are committed before any provider
    call.  The provider therefore runs without tenant/generation row locks.
    Every later write presents the exact access/tombstone epochs captured with
    that source snapshot; an event landing during provider I/O makes the job
    stale and the shadow is failed rather than populated or activated.
    """

    if session.new or session.dirty or session.deleted:
        raise PrivateRetrievalInvariantError(
            "Private rebuild requires a clean worker session before its provider boundary."
        )
    unresolved_event_count = int(
        session.scalar(
            select(func.count(PrivateProjectionEvent.id)).where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.status.in_(("pending", "failed")),
            )
        )
        or 0
    )
    if unresolved_event_count:
        raise PrivateRetrievalInvariantError(
            "Private rebuild requires every projection event to reach a terminal applied state."
        )
    active = ensure_active_private_generation(session, company_id=company_id)
    shadow = create_shadow_private_generation(session, company_id=company_id)
    payloads = _private_projection_inputs(
        session,
        company_id=company_id,
        limit=projection_limit,
    )
    payloads = _reuse_current_embeddings(
        session,
        company_id=company_id,
        generation_id=active.id,
        payloads=payloads,
        limit=max(1, min(projection_limit, MAX_PRIVATE_REBUILD_PROJECTIONS)),
    )
    previous_generation_id = str(active.id)
    shadow_generation_id = str(shadow.id)
    expected_access_policy_generation = int(shadow.access_policy_generation)
    expected_tombstone_generation = int(shadow.tombstone_generation)
    # A provider callback must be able to commit a revocation while this job is
    # waiting. The job owns this transaction boundary and publishes only an
    # empty, non-readable building generation before releasing its locks.
    session.commit()
    provider_batches = 0
    try:
        if provider is not None and payloads:
            payloads, provider_batches = _embed_private_payloads(
                payloads,
                provider=provider,
                allow_external_provider=allow_external_provider,
                provider_deadline_seconds=provider_deadline_seconds,
            )
        for payload in payloads:
            upsert_private_projection(
                session,
                company_id=company_id,
                generation_id=shadow_generation_id,
                payload=payload,
                expected_access_policy_generation=expected_access_policy_generation,
                expected_tombstone_generation=expected_tombstone_generation,
            )
        mark_private_generation_ready(
            session,
            company_id=company_id,
            generation_id=shadow_generation_id,
            expected_projection_count=len(payloads),
            expected_access_policy_generation=expected_access_policy_generation,
            expected_tombstone_generation=expected_tombstone_generation,
        )
        if activate:
            activate_private_generation(
                session,
                company_id=company_id,
                generation_id=shadow_generation_id,
                expected_active_generation_id=previous_generation_id,
            )
        session.flush()
    except Exception as exc:
        session.rollback()
        failed_shadow = session.scalar(
            select(PrivateIndexGeneration)
            .where(
                PrivateIndexGeneration.id == shadow_generation_id,
                PrivateIndexGeneration.company_id == company_id,
                PrivateIndexGeneration.state.in_(("building", "ready")),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if failed_shadow is not None:
            failed_shadow.state = "failed"
            failed_shadow.failure_code = type(exc).__name__[:80]
            session.commit()
        raise
    return PrivateRebuildSummary(
        company_id=company_id,
        previous_generation_id=previous_generation_id,
        generation_id=shadow_generation_id,
        projection_count=len(payloads),
        provider_batch_count=provider_batches,
        provider_text_count=len(payloads) if provider is not None else 0,
        activated=activate,
    )


def process_pending_private_projection_events(
    session: Session,
    *,
    company_id: str,
    limit: int = MAX_PENDING_EVENTS_PER_RUN,
    max_attempts: int = MAX_PRIVATE_EVENT_ATTEMPTS,
    retry_backoff_seconds: int = DEFAULT_PRIVATE_EVENT_RETRY_BACKOFF_SECONDS,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Claim and apply a bounded tenant event batch with durable retry state."""

    bounded = max(1, min(limit, MAX_PENDING_EVENTS_PER_RUN))
    bounded_attempts = max(1, min(max_attempts, 10))
    bounded_backoff = max(1, min(retry_backoff_seconds, 3_600))
    current = now or datetime.now(UTC)
    event_ids = tuple(
        session.scalars(
            select(PrivateProjectionEvent.id)
            .where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.status == "pending",
                or_(
                    PrivateProjectionEvent.next_attempt_at.is_(None),
                    PrivateProjectionEvent.next_attempt_at <= current,
                ),
            )
            .order_by(PrivateProjectionEvent.created_at, PrivateProjectionEvent.id)
            .limit(bounded)
            .with_for_update(skip_locked=True)
        ).all()
    )
    applied: list[str] = []
    for event_id in event_ids:
        try:
            with session.begin_nested():
                apply_private_projection_event(session, event_id=event_id)
        except Exception as exc:
            event = session.get(PrivateProjectionEvent, event_id)
            if event is not None:
                with session.begin_nested():
                    event.attempt_count = int(event.attempt_count or 0) + 1
                    event.last_attempt_at = current
                    event.error_code = type(exc).__name__[:80]
                    if event.attempt_count >= bounded_attempts:
                        event.status = "failed"
                        event.next_attempt_at = None
                    else:
                        event.status = "pending"
                        event.next_attempt_at = current + timedelta(
                            seconds=bounded_backoff * (2 ** (event.attempt_count - 1))
                        )
                    session.flush()
            continue
        event = session.get(PrivateProjectionEvent, event_id)
        if event is not None:
            event.attempt_count = int(event.attempt_count or 0) + 1
            event.last_attempt_at = current
            event.next_attempt_at = None
            event.error_code = None
            session.flush()
        applied.append(event_id)
    return tuple(applied)


def inspect_private_index_integrity(
    session: Session,
    *,
    company_id: str,
    now: datetime | None = None,
    event_lag_slo_seconds: int = DEFAULT_PRIVATE_EVENT_LAG_SLO_SECONDS,
) -> PrivateIntegrityReport:
    """Return safe aggregate integrity state; never return source identifiers."""

    current = now or datetime.now(UTC)
    generation = session.scalar(
        select(PrivateIndexGeneration).where(
            PrivateIndexGeneration.company_id == company_id,
            PrivateIndexGeneration.state == "active",
        )
    )
    active_generation_id = generation.id if generation is not None else ""
    live_count = 0
    tombstoned_count = 0
    manifest_matches = False
    if generation is not None:
        live_count = int(
            session.scalar(
                select(func.count(PrivateIndexProjection.id)).where(
                    PrivateIndexProjection.company_id == company_id,
                    PrivateIndexProjection.generation_id == generation.id,
                    PrivateIndexProjection.is_tombstoned.is_(False),
                )
            )
            or 0
        )
        tombstoned_count = int(
            session.scalar(
                select(func.count(PrivateIndexProjection.id)).where(
                    PrivateIndexProjection.company_id == company_id,
                    PrivateIndexProjection.generation_id == generation.id,
                    PrivateIndexProjection.is_tombstoned.is_(True),
                )
            )
            or 0
        )
        hashes = tuple(
            session.scalars(
                select(PrivateIndexProjection.content_sha256)
                .where(
                    PrivateIndexProjection.company_id == company_id,
                    PrivateIndexProjection.generation_id == generation.id,
                    PrivateIndexProjection.is_tombstoned.is_(False),
                )
                .order_by(PrivateIndexProjection.id)
            ).all()
        )
        import hashlib

        digest = hashlib.sha256("\n".join(hashes).encode("ascii")).hexdigest()
        manifest_matches = (
            generation.expected_projection_count == live_count
            and generation.verified_projection_count == live_count
            and generation.verification_sha256 == digest
        )

    pending_count = int(
        session.scalar(
            select(func.count(PrivateProjectionEvent.id)).where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.status == "pending",
            )
        )
        or 0
    )
    failed_count = int(
        session.scalar(
            select(func.count(PrivateProjectionEvent.id)).where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.status == "failed",
            )
        )
        or 0
    )
    oldest = session.scalar(
        select(func.min(PrivateProjectionEvent.created_at)).where(
            PrivateProjectionEvent.company_id == company_id,
            PrivateProjectionEvent.status == "pending",
        )
    )
    oldest_lag = None
    if oldest is not None:
        normalized_oldest = oldest.replace(tzinfo=UTC) if oldest.tzinfo is None else oldest
        oldest_lag = max(0, int((current - normalized_oldest).total_seconds()))

    orphan_scope_count = int(
        session.scalar(
            select(func.count(PrivateIndexProjectionScope.id))
            .join(
                PrivateIndexProjection,
                and_(
                    PrivateIndexProjection.id == PrivateIndexProjectionScope.projection_id,
                    PrivateIndexProjection.company_id == PrivateIndexProjectionScope.company_id,
                ),
            )
            .where(
                PrivateIndexProjectionScope.company_id == company_id,
                PrivateIndexProjection.generation_id == active_generation_id,
                PrivateIndexProjection.is_tombstoned.is_(False),
                or_(
                    and_(
                        PrivateIndexProjectionScope.scope_type == "client",
                        ~exists(
                            select(Client.id).where(
                                Client.company_id == company_id,
                                Client.id == PrivateIndexProjectionScope.client_id,
                                Client.is_active.is_(True),
                            )
                        ),
                    ),
                    and_(
                        PrivateIndexProjectionScope.scope_type == "matter",
                        ~exists(
                            select(Matter.id).where(
                                Matter.company_id == company_id,
                                Matter.id == PrivateIndexProjectionScope.matter_id,
                                Matter.is_active.is_(True),
                                Matter.access_policy_version
                                == PrivateIndexProjectionScope.access_policy_version,
                            )
                        ),
                    ),
                    and_(
                        PrivateIndexProjectionScope.scope_type == "ip_docket",
                        ~exists(
                            select(IpDocketRecord.id).where(
                                IpDocketRecord.company_id == company_id,
                                IpDocketRecord.id == PrivateIndexProjectionScope.ip_docket_id,
                                IpDocketRecord.is_active.is_(True),
                                IpDocketRecord.access_policy_version
                                == PrivateIndexProjectionScope.access_policy_version,
                            )
                        ),
                    ),
                ),
            )
        )
        or 0
    )
    unscoped = int(
        session.scalar(
            select(func.count(PrivateIndexProjection.id)).where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.generation_id == active_generation_id,
                PrivateIndexProjection.is_tombstoned.is_(False),
                ~exists(
                    select(PrivateIndexProjectionScope.id).where(
                        PrivateIndexProjectionScope.company_id == company_id,
                        PrivateIndexProjectionScope.projection_id == PrivateIndexProjection.id,
                    )
                ),
            )
        )
        or 0
    )
    orphan_scope_count += unscoped
    live_sources = list(
        session.scalars(
            select(PrivateIndexProjection)
            .where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.generation_id == active_generation_id,
                PrivateIndexProjection.is_tombstoned.is_(False),
            )
            .order_by(PrivateIndexProjection.id)
            .limit(MAX_PRIVATE_REBUILD_PROJECTIONS + 1)
        ).all()
    )
    source_scan_truncated = len(live_sources) > MAX_PRIVATE_REBUILD_PROJECTIONS
    live_sources = live_sources[:MAX_PRIVATE_REBUILD_PROJECTIONS]
    current_versions: dict[tuple[str, str], str] = {}
    grouped_sources: dict[str, set[str]] = defaultdict(set)
    for row in live_sources:
        grouped_sources[row.source_type].add(row.source_id)
    for row in session.scalars(
        select(Client).where(
            Client.company_id == company_id,
            Client.id.in_(grouped_sources.get("client", set())),
            Client.is_active.is_(True),
        )
    ).all():
        current_versions[("client", row.id)] = private_source_version(row)
    for row in session.scalars(
        select(Matter).where(
            Matter.company_id == company_id,
            Matter.id.in_(grouped_sources.get("matter", set())),
            Matter.is_active.is_(True),
        )
    ).all():
        current_versions[("matter", row.id)] = private_source_version(row)
    for row in session.scalars(
        select(MatterAttachment)
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(
            Matter.company_id == company_id,
            MatterAttachment.id.in_(grouped_sources.get("matter_document", set())),
            MatterAttachment.processing_status == "indexed",
        )
    ).all():
        current_versions[("matter_document", row.id)] = row.sha256_hex
    for row in session.scalars(
        select(IpDocketRecord).where(
            IpDocketRecord.company_id == company_id,
            IpDocketRecord.id.in_(grouped_sources.get("ip_docket", set())),
            IpDocketRecord.is_active.is_(True),
        )
    ).all():
        current_versions[("ip_docket", row.id)] = private_source_version(row)
    for document, _version in session.execute(
        select(IpDocument, IpDocumentVersion)
        .join(
            IpDocumentVersion,
            and_(
                IpDocumentVersion.document_id == IpDocument.id,
                IpDocumentVersion.version == IpDocument.current_version,
            ),
        )
        .where(
            IpDocument.company_id == company_id,
            IpDocument.id.in_(grouped_sources.get("ip_document", set())),
            IpDocument.confidentiality == "internal",
            IpDocument.is_privileged.is_(False),
            IpDocumentVersion.processing_status == "indexed",
            or_(
                IpDocumentVersion.ocr_quality_score.is_(None),
                IpDocumentVersion.ocr_quality_score >= LOW_OCR_QUALITY_THRESHOLD,
            ),
        )
    ).all():
        current_versions[("ip_document", document.id)] = str(document.current_version)
    stale_source_count = sum(
        current_versions.get((row.source_type, row.source_id)) != row.source_version
        for row in live_sources
    )
    unsafe_tombstones = int(
        session.scalar(
            select(func.count(PrivateIndexProjection.id)).where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.is_tombstoned.is_(True),
                or_(
                    PrivateIndexProjection.content_text != "",
                    PrivateIndexProjection.embedding_json.is_not(None),
                ),
            )
        )
        or 0
    )
    blockers: list[str] = []
    if generation is None:
        blockers.append("missing_active_generation")
    elif not manifest_matches:
        blockers.append("active_generation_manifest_mismatch")
    if pending_count:
        blockers.append("pending_projection_events")
    if oldest_lag is not None and oldest_lag > max(1, event_lag_slo_seconds):
        blockers.append("projection_event_lag_slo_exceeded")
    if failed_count:
        blockers.append("failed_projection_events")
    if orphan_scope_count:
        blockers.append("orphan_or_stale_scopes")
    if source_scan_truncated:
        blockers.append("integrity_scan_limit_exceeded")
    if stale_source_count:
        blockers.append("stale_or_ineligible_sources")
    if unsafe_tombstones:
        blockers.append("unsafe_tombstone_payload")
    state = "blocked" if blockers else "ready"
    return PrivateIntegrityReport(
        company_id=company_id,
        state=state,
        active_generation_id=generation.id if generation is not None else None,
        live_projection_count=live_count,
        tombstoned_projection_count=tombstoned_count,
        pending_event_count=pending_count,
        failed_event_count=failed_count,
        oldest_pending_lag_seconds=oldest_lag,
        orphan_scope_count=orphan_scope_count,
        stale_source_count=stale_source_count,
        unsafe_tombstone_count=unsafe_tombstones,
        generation_manifest_matches=manifest_matches,
        blockers=tuple(blockers),
    )


__all__ = [
    "DEFAULT_PRIVATE_EVENT_LAG_SLO_SECONDS",
    "DEFAULT_PRIVATE_EVENT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_PRIVATE_PROVIDER_DEADLINE_SECONDS",
    "MAX_PRIVATE_EVENT_ATTEMPTS",
    "MAX_PENDING_EVENTS_PER_RUN",
    "MAX_PRIVATE_PROVIDER_BATCH",
    "MAX_PRIVATE_MAINTENANCE_COMPANIES",
    "MAX_PRIVATE_REBUILD_PROJECTIONS",
    "PrivateIntegrityReport",
    "PrivateRebuildSummary",
    "inspect_private_index_integrity",
    "list_private_maintenance_companies",
    "process_pending_private_projection_events",
    "rebuild_private_index",
]
