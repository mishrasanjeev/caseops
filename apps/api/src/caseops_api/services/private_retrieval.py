"""Fail-closed tenant-private search and saved-output access foundation.

The public authority corpus has a different owner and never enters these
tables.  Candidate IDs are tenant/ACL/generation filtered in SQL before any
lexical or vector ranking, then every returned row is authorized again during
hydration.  Cache entries contain IDs only and hydration is mandatory on hits.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, delete, exists, func, not_, or_, select, update
from sqlalchemy.orm import Session

from caseops_api.core.settings import Settings, get_settings
from caseops_api.db.models import (
    AssistantTurn,
    Client,
    Company,
    CompanyMembership,
    IpDocketRecord,
    IpDocument,
    Matter,
    MatterAttachment,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateIndexProjectionScope,
    PrivateProjectionEvent,
    PrivateSavedOutputAccess,
    User,
)
from caseops_api.services.capabilities import (
    membership_has_capability,
    resolve_membership_capabilities,
)
from caseops_api.services.ip_capability_catalog import (
    IPFeatureDecision,
    evaluate_ip_feature,
)
from caseops_api.services.ip_document_workflow import get_ip_document_policies
from caseops_api.services.matter_access import (
    visible_ip_dockets_filter,
    visible_matters_filter,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.tenant_ai_policy import resolve_tenant_policy

PrivateSourceType = Literal["client", "matter", "matter_document", "ip_docket", "ip_document"]
PrivateScopeType = Literal["client", "matter", "ip_docket"]
PrivateEventType = Literal["source_changed", "access_changed", "revoked", "tombstoned", "reindex"]

MAX_PREFILTER_CANDIDATES = 200
MAX_PRIVATE_RESULTS = 20
MAX_QUERY_TERMS = 8
PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH = 120
PRIVATE_SAVED_SOURCE_SCHEMA = "caseops.private-saved-output-source.v1"
STALE_PRIVATE_PROJECTION_WRITER_DETAIL = (
    "A stale private projection writer cannot cross an access or tombstone change."
)
_CACHE_TTL = timedelta(seconds=30)
_CACHE_MAX_ENTRIES = 256
_CACHE_LOCK = threading.Lock()
_CANDIDATE_CACHE: OrderedDict[str, tuple[datetime, tuple[str, ...]]] = OrderedDict()
_TERM_RE = re.compile(r"[\w-]+", re.UNICODE)


class PrivateRetrievalInvariantError(RuntimeError):
    """A private-index state transition would weaken a security invariant."""


class PrivateRetrievalConcurrencyError(PrivateRetrievalInvariantError):
    """A private-index operation lost a bounded race to another valid writer."""


def build_private_projection_event_key(raw_key: str) -> str:
    """Return the stable database key for one projection event operation.

    Existing keys that already fit remain byte-for-byte compatible. Oversized
    keys retain a readable prefix and the full SHA-256 digest of the unbounded
    operation identity, so every producer gets the same 120-character boundary
    without weakening retry semantics or truncating away collision resistance.
    """

    if not raw_key:
        raise PrivateRetrievalInvariantError(
            "A private projection event requires an idempotency key."
        )
    if len(raw_key) <= PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH:
        return raw_key
    marker = ":sha256:"
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    prefix_length = PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH - len(marker) - len(digest)
    return f"{raw_key[:prefix_length]}{marker}{digest}"


@dataclass(frozen=True, slots=True)
class ProjectionScopeInput:
    scope_type: PrivateScopeType
    scope_id: str
    access_policy_version: int


@dataclass(frozen=True, slots=True)
class PrivateProjectionInput:
    source_type: PrivateSourceType
    source_id: str
    source_version: str
    chunk_ordinal: int
    label: str
    content: str
    scopes: tuple[ProjectionScopeInput, ...]
    confidentiality: Literal["internal", "confidential", "restricted"] = "internal"
    is_privileged: bool = False
    source_state: Literal[
        "active", "approved", "filed", "indexed", "quarantined", "retired", "deleted"
    ] = "active"
    approval_state: Literal["not_required", "approved", "rejected", "withdrawn"] = "not_required"
    embedding_model: str | None = None
    embedding_version: str | None = None
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True, slots=True)
class HydratedPrivateResult:
    projection_id: str
    source_type: str
    source_id: str
    source_version: str
    label: str
    content: str
    score: float


@dataclass(frozen=True, slots=True)
class PrivateAutocompleteSuggestion:
    """Content-free private suggestion released only after final reauthorization."""

    projection_id: str
    source_type: str
    source_id: str
    source_version: str
    label: str


@dataclass(frozen=True, slots=True)
class PrivateRetrievalFence:
    """Exact identity and security epochs captured before asynchronous work."""

    company_id: str
    membership_id: str
    user_id: str
    generation_id: str
    access_policy_generation: int
    tombstone_generation: int
    required_capability: str
    activation_required: bool


@dataclass(frozen=True, slots=True)
class PrivateRetrievalActivation:
    """Current server-owned activation decision for a private consumer."""

    available: bool
    reason: str
    feature: IPFeatureDecision


def private_retrieval_activation(
    session: Session,
    *,
    context: SessionContext,
    settings: Settings | None = None,
) -> PrivateRetrievalActivation:
    """Re-evaluate auth, entitlement, rollout and tenant AI policy.

    A frontend flag or a context captured at login is never sufficient to
    activate private retrieval. ``workspace_core`` is the existing canonical
    IP entitlement/rollout owner; the tenant AI policy remains the independent
    consent boundary for sending workspace content to an assistant.
    """

    current = _refreshed_context(
        session,
        context=context,
        required_capability="ai:generate",
    )
    capabilities = (
        resolve_membership_capabilities(session, current.membership)
        if current is not None
        else set()
    )
    from caseops_api.services.saas_billing import current_entitlements_for_company

    feature = evaluate_ip_feature(
        "workspace_core",
        granted_capabilities=capabilities,
        entitlements=current_entitlements_for_company(session, context.company.id),
        settings=settings or get_settings(),
    )
    if current is None:
        return PrivateRetrievalActivation(
            available=False,
            reason="missing_capability",
            feature=feature,
        )
    policy = resolve_tenant_policy(session, company_id=context.company.id)
    if not policy.workspace_assistant_enabled:
        return PrivateRetrievalActivation(
            available=False,
            reason="tenant_ai_policy_disabled",
            feature=feature,
        )
    return PrivateRetrievalActivation(
        available=feature.available,
        reason=feature.reason,
        feature=feature,
    )


def private_source_version(row: Client | Matter | IpDocketRecord) -> str:
    """Return a version that changes for source edits and ACL changes."""

    updated_at = row.updated_at
    if updated_at is None:
        updated = "missing"
    else:
        # SQLite drops timezone metadata while PostgreSQL returns an aware UTC
        # value. Treat a naïve persisted timestamp as UTC so the same source
        # does not look stale merely because the ORM refreshed it.
        normalized = (
            updated_at.replace(tzinfo=UTC)
            if updated_at.tzinfo is None
            else updated_at.astimezone(UTC)
        )
        updated = normalized.isoformat()
    if isinstance(row, (Matter, IpDocketRecord)):
        return f"{row.access_policy_version}:{updated}"
    return updated


def _active_generation_statement(company_id: str):
    return select(PrivateIndexGeneration).where(
        PrivateIndexGeneration.company_id == company_id,
        PrivateIndexGeneration.state == "active",
    )


def _lock_private_company(session: Session, *, company_id: str) -> Company:
    """Serialize generation/event authority changes on one stable tenant row."""

    company = session.scalar(
        select(Company)
        .where(Company.id == company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if company is None:
        raise PrivateRetrievalInvariantError("Private index company does not exist.")
    return company


def ensure_active_private_generation(
    session: Session, *, company_id: str
) -> PrivateIndexGeneration:
    """Return the one active generation, creating an empty bootstrap safely."""

    rows = list(
        session.scalars(
            _active_generation_statement(company_id).execution_options(populate_existing=True)
        ).all()
    )
    if len(rows) > 1:
        raise PrivateRetrievalInvariantError("More than one private index generation is active.")
    if rows:
        return rows[0]
    company = session.scalar(
        select(Company)
        .where(Company.id == company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if company is None:
        raise PrivateRetrievalInvariantError("Private index company does not exist.")
    row = session.scalar(
        _active_generation_statement(company_id).execution_options(populate_existing=True)
    )
    if row is not None:
        return row
    now = datetime.now(UTC)
    row = PrivateIndexGeneration(
        company_id=company_id,
        generation_number=1,
        state="active",
        access_policy_generation=1,
        tombstone_generation=0,
        expected_projection_count=0,
        verified_projection_count=0,
        verification_sha256=hashlib.sha256(b"").hexdigest(),
        verified_at=now,
        activated_at=now,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return row


def create_shadow_private_generation(
    session: Session, *, company_id: str
) -> PrivateIndexGeneration:
    _lock_private_company(session, company_id=company_id)
    current = ensure_active_private_generation(session, company_id=company_id)
    generations = list(
        session.scalars(
            select(PrivateIndexGeneration)
            .where(PrivateIndexGeneration.company_id == company_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    if any(row.state in {"building", "ready"} for row in generations):
        raise PrivateRetrievalConcurrencyError("A private shadow generation is already open.")
    row = PrivateIndexGeneration(
        company_id=company_id,
        generation_number=max(row.generation_number for row in generations) + 1,
        state="building",
        access_policy_generation=current.access_policy_generation,
        tombstone_generation=current.tombstone_generation,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def mark_private_generation_ready(
    session: Session,
    *,
    company_id: str,
    generation_id: str,
    expected_projection_count: int,
    expected_access_policy_generation: int | None = None,
    expected_tombstone_generation: int | None = None,
) -> PrivateIndexGeneration:
    """Verify a shadow generation under the tenant's canonical lock order.

    Access/tombstone events (including Matter disposal) lock the Company row
    before any active or shadow generation.  Readiness followed by activation
    runs in one transaction, so taking a generation lock first here inverted
    that order and could deadlock a lifecycle write.  Serialize on Company
    first everywhere a generation can transition.
    """

    _lock_private_company(session, company_id=company_id)
    row = session.scalar(
        select(PrivateIndexGeneration)
        .where(
            PrivateIndexGeneration.id == generation_id,
            PrivateIndexGeneration.company_id == company_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.state != "building":
        raise PrivateRetrievalInvariantError("Only a building private generation can be verified.")
    if (
        expected_access_policy_generation is not None
        and row.access_policy_generation != expected_access_policy_generation
    ) or (
        expected_tombstone_generation is not None
        and row.tombstone_generation != expected_tombstone_generation
    ):
        raise PrivateRetrievalConcurrencyError(
            "A stale private rebuild cannot verify after an access or tombstone change."
        )
    count = int(
        session.scalar(
            select(func.count(PrivateIndexProjection.id)).where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.generation_id == generation_id,
                PrivateIndexProjection.is_tombstoned.is_(False),
            )
        )
        or 0
    )
    if count != expected_projection_count:
        raise PrivateRetrievalInvariantError(
            "Private generation projection count does not match its verification manifest."
        )
    projection_hashes = list(
        session.scalars(
            select(PrivateIndexProjection.content_sha256)
            .where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.generation_id == generation_id,
                PrivateIndexProjection.is_tombstoned.is_(False),
            )
            .order_by(PrivateIndexProjection.id)
        ).all()
    )
    row.expected_projection_count = expected_projection_count
    row.verified_projection_count = count
    row.verification_sha256 = hashlib.sha256(
        "\n".join(projection_hashes).encode("ascii")
    ).hexdigest()
    row.verified_at = datetime.now(UTC)
    row.state = "ready"
    session.flush()
    return row


def activate_private_generation(
    session: Session,
    *,
    company_id: str,
    generation_id: str,
    expected_active_generation_id: str,
) -> PrivateIndexGeneration:
    _lock_private_company(session, company_id=company_id)
    generations = list(
        session.scalars(
            select(PrivateIndexGeneration)
            .where(PrivateIndexGeneration.company_id == company_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    current = next((row for row in generations if row.state == "active"), None)
    target = next((row for row in generations if row.id == generation_id), None)
    if current is None or current.id != expected_active_generation_id:
        raise PrivateRetrievalConcurrencyError("The active private generation changed.")
    if target is None or target.state != "ready" or target.verified_at is None:
        raise PrivateRetrievalConcurrencyError("The shadow private generation is not verified.")
    if (
        target.access_policy_generation < current.access_policy_generation
        or target.tombstone_generation < current.tombstone_generation
    ):
        raise PrivateRetrievalConcurrencyError(
            "A stale private generation cannot bypass access or tombstone changes."
        )
    pending = session.scalar(
        select(PrivateProjectionEvent.id)
        .where(
            PrivateProjectionEvent.company_id == company_id,
            PrivateProjectionEvent.status != "applied",
        )
        .limit(1)
    )
    if pending is not None:
        raise PrivateRetrievalConcurrencyError(
            "A private generation cannot activate while projection events are unresolved."
        )
    now = datetime.now(UTC)
    current.state = "retired"
    current.retired_at = now
    session.flush()
    target.state = "active"
    target.activated_at = now
    session.flush()
    invalidate_private_retrieval_cache(company_id=company_id)
    return target


def _typed_scope_values(scope: ProjectionScopeInput) -> dict[str, str | None]:
    values = {"client_id": None, "matter_id": None, "ip_docket_id": None}
    values[f"{scope.scope_type}_id"] = scope.scope_id
    return values


def _assert_projection_input(payload: PrivateProjectionInput) -> None:
    if not payload.scopes:
        raise PrivateRetrievalInvariantError("A private projection needs an ACL scope.")
    if payload.chunk_ordinal < 0:
        raise PrivateRetrievalInvariantError(
            "A private projection chunk ordinal cannot be negative."
        )
    if not payload.content.strip():
        raise PrivateRetrievalInvariantError("A live private projection cannot have blank content.")
    if payload.is_privileged or payload.confidentiality != "internal":
        raise PrivateRetrievalInvariantError(
            "Privileged or non-internal content is not eligible for private AI retrieval."
        )
    if payload.source_state not in {"active", "approved", "filed", "indexed"}:
        raise PrivateRetrievalInvariantError("The private projection source is not active.")
    if payload.approval_state not in {"not_required", "approved"}:
        raise PrivateRetrievalInvariantError("The private projection source is not approved.")
    if len({(scope.scope_type, scope.scope_id) for scope in payload.scopes}) != len(payload.scopes):
        raise PrivateRetrievalInvariantError("Private projection scopes must be unique.")


def upsert_private_projection(
    session: Session,
    *,
    company_id: str,
    generation_id: str,
    payload: PrivateProjectionInput,
    expected_access_policy_generation: int,
    expected_tombstone_generation: int,
) -> PrivateIndexProjection:
    """Write one chunk only under the security epochs that produced its payload."""

    _assert_projection_input(payload)
    generation = session.scalar(
        select(PrivateIndexGeneration)
        .where(
            PrivateIndexGeneration.id == generation_id,
            PrivateIndexGeneration.company_id == company_id,
            PrivateIndexGeneration.state.in_(("building", "active")),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if generation is None:
        raise PrivateRetrievalInvariantError("Private generation is not writable.")
    if (
        generation.access_policy_generation != expected_access_policy_generation
        or generation.tombstone_generation != expected_tombstone_generation
    ):
        raise PrivateRetrievalConcurrencyError(STALE_PRIVATE_PROJECTION_WRITER_DETAIL)
    row = session.scalar(
        select(PrivateIndexProjection).where(
            PrivateIndexProjection.generation_id == generation_id,
            PrivateIndexProjection.source_type == payload.source_type,
            PrivateIndexProjection.source_id == payload.source_id,
            PrivateIndexProjection.source_version == payload.source_version,
            PrivateIndexProjection.chunk_ordinal == payload.chunk_ordinal,
        )
    )
    now = datetime.now(UTC)
    if row is None:
        row = PrivateIndexProjection(
            company_id=company_id,
            generation_id=generation_id,
            source_type=payload.source_type,
            source_id=payload.source_id,
            source_version=payload.source_version,
            chunk_ordinal=payload.chunk_ordinal,
            created_at=now,
        )
        session.add(row)
    _apply_private_projection_payload(
        row,
        payload=payload,
        generation=generation,
        now=now,
    )
    session.flush()
    session.execute(
        delete(PrivateIndexProjectionScope).where(
            PrivateIndexProjectionScope.company_id == company_id,
            PrivateIndexProjectionScope.projection_id == row.id,
        )
    )
    session.add_all(_projection_scope_rows(row=row, payload=payload, now=now))
    session.flush()
    invalidate_private_retrieval_cache(company_id=company_id)
    return row


def _apply_private_projection_payload(
    row: PrivateIndexProjection,
    *,
    payload: PrivateProjectionInput,
    generation: PrivateIndexGeneration,
    now: datetime,
) -> None:
    content = " ".join(payload.content.split())
    encoded_embedding = (
        json.dumps(list(payload.embedding), separators=(",", ":"))
        if payload.embedding is not None
        else None
    )
    row.label = payload.label.strip()[:255]
    row.content_text = content
    row.content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    row.confidentiality = payload.confidentiality
    row.is_privileged = payload.is_privileged
    row.source_state = payload.source_state
    row.approval_state = payload.approval_state
    row.access_policy_version = max(scope.access_policy_version for scope in payload.scopes)
    row.access_policy_generation = generation.access_policy_generation
    row.tombstone_generation = generation.tombstone_generation
    row.embedding_model = payload.embedding_model
    row.embedding_version = payload.embedding_version
    row.embedding_dimensions = len(payload.embedding) if payload.embedding is not None else None
    row.embedding_json = encoded_embedding
    row.is_tombstoned = False
    row.tombstoned_at = None
    row.tombstone_reason = None
    row.updated_at = now


def _projection_scope_rows(
    *,
    row: PrivateIndexProjection,
    payload: PrivateProjectionInput,
    now: datetime,
) -> list[PrivateIndexProjectionScope]:
    return [
        PrivateIndexProjectionScope(
            company_id=row.company_id,
            projection_id=row.id,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            access_policy_version=scope.access_policy_version,
            created_at=now,
            **_typed_scope_values(scope),
        )
        for scope in payload.scopes
    ]


def _lock_projection_scope_parents(
    session: Session,
    *,
    company_id: str,
    payloads: Sequence[PrivateProjectionInput],
) -> None:
    """Take bounded FK parent locks before the generation write fence.

    PostgreSQL validates each projection-scope foreign key with a ``KEY SHARE``
    lock.  If the generation is locked first, an interactive lifecycle writer
    that already owns the Matter/IP row can form a cycle while it advances the
    private generation epoch.  Acquire the exact, bounded scope parents in a
    stable order before touching the generation so the interactive writer can
    always finish and the later epoch check can reject this stale batch.
    """

    scope_models = {
        "client": Client,
        "matter": Matter,
        "ip_docket": IpDocketRecord,
    }
    for scope_type in ("client", "matter", "ip_docket"):
        scope_ids = sorted(
            {
                scope.scope_id
                for payload in payloads
                for scope in payload.scopes
                if scope.scope_type == scope_type
            }
        )
        if not scope_ids:
            continue
        model = scope_models[scope_type]
        locked_ids = tuple(
            session.scalars(
                select(model.id)
                .where(
                    model.company_id == company_id,
                    model.id.in_(scope_ids),
                )
                .order_by(model.id)
                .with_for_update(read=True, key_share=True)
            ).all()
        )
        if locked_ids != tuple(scope_ids):
            raise PrivateRetrievalConcurrencyError(STALE_PRIVATE_PROJECTION_WRITER_DETAIL)


def insert_private_projection_batch(
    session: Session,
    *,
    company_id: str,
    generation_id: str,
    payloads: Sequence[PrivateProjectionInput],
    expected_access_policy_generation: int,
    expected_tombstone_generation: int,
) -> tuple[PrivateIndexProjection, ...]:
    """Insert one fresh shadow batch under a single epoch fence.

    Rebuild shadows are write-once. Batching removes per-projection generation
    locks, existence reads, scope deletes, flushes and cache invalidations while
    preserving the same fail-closed epoch check at every commit boundary.
    """

    batch = tuple(payloads)
    if not batch:
        return ()
    for payload in batch:
        _assert_projection_input(payload)
    keys = {
        (
            payload.source_type,
            payload.source_id,
            payload.source_version,
            payload.chunk_ordinal,
        )
        for payload in batch
    }
    if len(keys) != len(batch):
        raise PrivateRetrievalInvariantError(
            "A private projection rebuild batch contains duplicate source chunks."
        )

    _lock_projection_scope_parents(
        session,
        company_id=company_id,
        payloads=batch,
    )
    generation = session.scalar(
        select(PrivateIndexGeneration)
        .where(
            PrivateIndexGeneration.id == generation_id,
            PrivateIndexGeneration.company_id == company_id,
            PrivateIndexGeneration.state == "building",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if generation is None:
        raise PrivateRetrievalInvariantError("Private generation is not writable.")
    if (
        generation.access_policy_generation != expected_access_policy_generation
        or generation.tombstone_generation != expected_tombstone_generation
    ):
        raise PrivateRetrievalConcurrencyError(STALE_PRIVATE_PROJECTION_WRITER_DETAIL)

    now = datetime.now(UTC)
    rows: list[PrivateIndexProjection] = []
    for payload in batch:
        row = PrivateIndexProjection(
            company_id=company_id,
            generation_id=generation_id,
            source_type=payload.source_type,
            source_id=payload.source_id,
            source_version=payload.source_version,
            chunk_ordinal=payload.chunk_ordinal,
            created_at=now,
        )
        _apply_private_projection_payload(
            row,
            payload=payload,
            generation=generation,
            now=now,
        )
        rows.append(row)
    session.add_all(rows)
    session.flush()
    session.add_all(
        [
            scope_row
            for row, payload in zip(rows, batch, strict=True)
            for scope_row in _projection_scope_rows(row=row, payload=payload, now=now)
        ]
    )
    session.flush()
    invalidate_private_retrieval_cache(company_id=company_id)
    return tuple(rows)


def _refreshed_context(
    session: Session,
    *,
    context: SessionContext,
    required_capability: str,
) -> SessionContext | None:
    membership = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == context.membership.id,
            CompanyMembership.company_id == context.company.id,
            CompanyMembership.is_active.is_(True),
        )
    )
    company = session.scalar(
        select(Company).where(Company.id == context.company.id, Company.is_active.is_(True))
    )
    user = session.scalar(select(User).where(User.id == context.user.id, User.is_active.is_(True)))
    if (
        membership is None
        or company is None
        or user is None
        or membership.user_id != user.id
        or not membership_has_capability(session, membership, required_capability)
    ):
        return None
    return SessionContext(
        company=company,
        membership=membership,
        user=user,
        token_issued_at=context.token_issued_at,
    )


def capture_private_retrieval_fence(
    session: Session,
    *,
    context: SessionContext,
    required_capability: str = "ai:generate",
    require_activation: bool = False,
) -> PrivateRetrievalFence | None:
    """Capture the exact active generation and actor boundary for later delivery."""

    current = _refreshed_context(
        session,
        context=context,
        required_capability=required_capability,
    )
    if current is None:
        return None
    generation = session.scalar(_active_generation_statement(current.company.id))
    if generation is None:
        return None
    return PrivateRetrievalFence(
        company_id=current.company.id,
        membership_id=current.membership.id,
        user_id=current.user.id,
        generation_id=generation.id,
        access_policy_generation=generation.access_policy_generation,
        tombstone_generation=generation.tombstone_generation,
        required_capability=required_capability,
        activation_required=require_activation,
    )


def _private_delivery_context(
    session: Session,
    *,
    fence: PrivateRetrievalFence,
) -> tuple[SessionContext, PrivateIndexGeneration] | None:
    """Reopen an asynchronous delivery only at its exact current security epochs."""

    actor = session.execute(
        select(Company, CompanyMembership, User)
        .join(
            CompanyMembership,
            and_(
                CompanyMembership.company_id == Company.id,
                CompanyMembership.id == fence.membership_id,
                CompanyMembership.user_id == fence.user_id,
                CompanyMembership.is_active.is_(True),
            ),
        )
        .join(
            User,
            and_(
                User.id == CompanyMembership.user_id,
                User.id == fence.user_id,
                User.is_active.is_(True),
            ),
        )
        .where(
            Company.id == fence.company_id,
            Company.is_active.is_(True),
        )
    ).one_or_none()
    if actor is None:
        return None
    company, membership, user = actor
    if not membership_has_capability(session, membership, fence.required_capability):
        return None
    generation = session.scalar(
        _active_generation_statement(fence.company_id).where(
            PrivateIndexGeneration.id == fence.generation_id,
            PrivateIndexGeneration.access_policy_generation == fence.access_policy_generation,
            PrivateIndexGeneration.tombstone_generation == fence.tombstone_generation,
        )
    )
    if generation is None:
        return None
    current = SessionContext(
        company=company,
        membership=membership,
        user=user,
    )
    if fence.activation_required:
        activation = private_retrieval_activation(session, context=current)
        if not activation.available:
            return None
    return current, generation


def _authorized_projection_ids_statement(
    session: Session,
    *,
    context: SessionContext,
    generation: PrivateIndexGeneration,
):
    visible_matter_ids = select(Matter.id).where(
        Matter.company_id == context.company.id,
        Matter.is_active.is_(True),
        visible_matters_filter(session, context=context),
    )
    visible_docket_ids = select(IpDocketRecord.id).where(
        IpDocketRecord.company_id == context.company.id,
        IpDocketRecord.is_active.is_(True),
        visible_ip_dockets_filter(session, context=context),
    )
    active_client_ids = select(Client.id).where(
        Client.company_id == context.company.id,
        Client.is_active.is_(True),
    )
    invalid_scope = exists(
        select(PrivateIndexProjectionScope.id).where(
            PrivateIndexProjectionScope.company_id == context.company.id,
            PrivateIndexProjectionScope.projection_id == PrivateIndexProjection.id,
            or_(
                and_(
                    PrivateIndexProjectionScope.scope_type == "client",
                    PrivateIndexProjectionScope.client_id.not_in(active_client_ids),
                ),
                and_(
                    PrivateIndexProjectionScope.scope_type == "matter",
                    or_(
                        PrivateIndexProjectionScope.matter_id.not_in(visible_matter_ids),
                        exists(
                            select(Matter.id).where(
                                Matter.id == PrivateIndexProjectionScope.matter_id,
                                Matter.company_id == context.company.id,
                                Matter.access_policy_version
                                != PrivateIndexProjectionScope.access_policy_version,
                            )
                        ),
                    ),
                ),
                and_(
                    PrivateIndexProjectionScope.scope_type == "ip_docket",
                    or_(
                        PrivateIndexProjectionScope.ip_docket_id.not_in(visible_docket_ids),
                        exists(
                            select(IpDocketRecord.id).where(
                                IpDocketRecord.id == PrivateIndexProjectionScope.ip_docket_id,
                                IpDocketRecord.company_id == context.company.id,
                                IpDocketRecord.access_policy_version
                                != PrivateIndexProjectionScope.access_policy_version,
                            )
                        ),
                    ),
                ),
            ),
        )
    )
    has_scope = exists(
        select(PrivateIndexProjectionScope.id).where(
            PrivateIndexProjectionScope.company_id == context.company.id,
            PrivateIndexProjectionScope.projection_id == PrivateIndexProjection.id,
        )
    )
    return select(PrivateIndexProjection.id).where(
        PrivateIndexProjection.company_id == context.company.id,
        PrivateIndexProjection.generation_id == generation.id,
        PrivateIndexProjection.is_tombstoned.is_(False),
        PrivateIndexProjection.is_privileged.is_(False),
        PrivateIndexProjection.confidentiality == "internal",
        PrivateIndexProjection.source_state.in_(("active", "approved", "filed", "indexed")),
        PrivateIndexProjection.approval_state.in_(("not_required", "approved")),
        has_scope,
        not_(invalid_scope),
    )


def _query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for term in _TERM_RE.findall(query.casefold()):
        if len(term) < 2 or term in terms:
            continue
        terms.append(term)
        if len(terms) == MAX_QUERY_TERMS:
            break
    return tuple(terms)


def prefilter_private_projection_ids(
    session: Session,
    *,
    context: SessionContext,
    query: str,
    source_types: set[PrivateSourceType] | None = None,
    filters: dict[str, object] | None = None,
    required_capability: str = "ai:generate",
    require_lexical_match: bool = True,
    limit: int = MAX_PREFILTER_CANDIDATES,
) -> tuple[str, ...]:
    """Return only SQL-prefiltered IDs; callers must still hydrate/reauthorize."""

    current_context = _refreshed_context(
        session,
        context=context,
        required_capability=required_capability,
    )
    if current_context is None:
        return ()
    generation = session.scalar(_active_generation_statement(context.company.id))
    if generation is None:
        return ()
    statement = _authorized_projection_ids_statement(
        session,
        context=current_context,
        generation=generation,
    )
    if source_types:
        statement = statement.where(PrivateIndexProjection.source_type.in_(source_types))
    normalized_filters = filters or {}
    supported_filters = {
        "client_id",
        "matter_id",
        "ip_docket_id",
        "document_id",
        "source_id",
        "source_version",
        "scope_ids",
        "source_refs",
    }
    unknown_filters = set(normalized_filters) - supported_filters
    if unknown_filters:
        raise PrivateRetrievalInvariantError(
            f"Unsupported private retrieval filters: {sorted(unknown_filters)}"
        )
    for key in ("client_id", "matter_id", "ip_docket_id"):
        value = normalized_filters.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise PrivateRetrievalInvariantError(
                f"Private retrieval filter {key!r} must be one non-empty identifier."
            )
        scope_type = key.removesuffix("_id")
        statement = statement.where(
            exists(
                select(PrivateIndexProjectionScope.id).where(
                    PrivateIndexProjectionScope.company_id == context.company.id,
                    PrivateIndexProjectionScope.projection_id == PrivateIndexProjection.id,
                    PrivateIndexProjectionScope.scope_type == scope_type,
                    PrivateIndexProjectionScope.scope_id == value,
                )
            )
        )
    selection_predicates = []
    requested_scopes = normalized_filters.get("scope_ids")
    if requested_scopes is not None:
        if not isinstance(requested_scopes, dict) or not requested_scopes:
            raise PrivateRetrievalInvariantError(
                "Private retrieval scope_ids must be a non-empty mapping."
            )
        scope_predicates = []
        for scope_type, raw_ids in sorted(requested_scopes.items()):
            if scope_type not in {"client", "matter", "ip_docket"}:
                raise PrivateRetrievalInvariantError(
                    f"Unsupported private retrieval scope type: {scope_type!r}"
                )
            if not isinstance(raw_ids, (list, tuple, set)):
                raise PrivateRetrievalInvariantError(
                    "Private retrieval scoped identifiers must be a bounded collection."
                )
            scope_ids = tuple(
                sorted(
                    {value.strip() for value in raw_ids if isinstance(value, str) and value.strip()}
                )
            )
            if not scope_ids or len(scope_ids) > 24 or len(scope_ids) != len(raw_ids):
                raise PrivateRetrievalInvariantError(
                    "Private retrieval accepts 1 to 24 unique non-empty scope identifiers."
                )
            scope_predicates.append(
                exists(
                    select(PrivateIndexProjectionScope.id).where(
                        PrivateIndexProjectionScope.company_id == context.company.id,
                        PrivateIndexProjectionScope.projection_id == PrivateIndexProjection.id,
                        PrivateIndexProjectionScope.scope_type == scope_type,
                        PrivateIndexProjectionScope.scope_id.in_(scope_ids),
                    )
                )
            )
        selection_predicates.extend(scope_predicates)
    requested_sources = normalized_filters.get("source_refs")
    if requested_sources is not None:
        if not isinstance(requested_sources, dict) or not requested_sources:
            raise PrivateRetrievalInvariantError(
                "Private retrieval source_refs must be a non-empty mapping."
            )
        source_predicates = []
        for source_type, raw_ids in sorted(requested_sources.items()):
            if source_type not in {
                "client",
                "matter",
                "matter_document",
                "ip_docket",
                "ip_document",
            }:
                raise PrivateRetrievalInvariantError(
                    f"Unsupported private retrieval source type: {source_type!r}"
                )
            if not isinstance(raw_ids, (list, tuple, set)):
                raise PrivateRetrievalInvariantError(
                    "Private retrieval source identifiers must be a bounded collection."
                )
            source_ids = tuple(
                sorted(
                    {value.strip() for value in raw_ids if isinstance(value, str) and value.strip()}
                )
            )
            if not source_ids or len(source_ids) > 24 or len(source_ids) != len(raw_ids):
                raise PrivateRetrievalInvariantError(
                    "Private retrieval accepts 1 to 24 unique non-empty source identifiers."
                )
            source_predicates.append(
                and_(
                    PrivateIndexProjection.source_type == source_type,
                    PrivateIndexProjection.source_id.in_(source_ids),
                )
            )
        selection_predicates.extend(source_predicates)
    if selection_predicates:
        statement = statement.where(or_(*selection_predicates))
    document_id = normalized_filters.get("document_id")
    if document_id is not None:
        if not isinstance(document_id, str) or not document_id.strip():
            raise PrivateRetrievalInvariantError(
                "Private retrieval document_id must be one non-empty identifier."
            )
        statement = statement.where(
            PrivateIndexProjection.source_type.in_(("matter_document", "ip_document")),
            PrivateIndexProjection.source_id == document_id,
        )
    for key, column in (
        ("source_id", PrivateIndexProjection.source_id),
        ("source_version", PrivateIndexProjection.source_version),
    ):
        value = normalized_filters.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise PrivateRetrievalInvariantError(
                f"Private retrieval filter {key!r} must be one non-empty value."
            )
        statement = statement.where(column == value)
    terms = _query_terms(query)
    if require_lexical_match and not terms:
        # A punctuation-only or one-character query must not degrade into a
        # newest-row listing of otherwise private content.
        return ()
    if terms and require_lexical_match:
        lowered = func.lower(PrivateIndexProjection.content_text)
        statement = statement.where(or_(*(lowered.contains(term) for term in terms)))
    bounded = max(1, min(limit, MAX_PREFILTER_CANDIDATES))
    return tuple(
        session.scalars(
            statement.order_by(
                PrivateIndexProjection.updated_at.desc(),
                PrivateIndexProjection.id,
            ).limit(bounded)
        ).all()
    )


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _source_versions_still_current(
    session: Session,
    *,
    context: SessionContext,
    projections: list[PrivateIndexProjection],
) -> set[str]:
    allowed: set[str] = set()
    grouped: dict[str, set[str]] = {}
    for row in projections:
        grouped.setdefault(row.source_type, set()).add(row.source_id)

    client_ids = grouped.get("client", set())
    if client_ids:
        for row in session.scalars(
            select(Client).where(
                Client.company_id == context.company.id,
                Client.id.in_(client_ids),
                Client.is_active.is_(True),
            )
        ).all():
            expected = private_source_version(row)
            allowed.update(
                item.id
                for item in projections
                if item.source_type == "client"
                and item.source_id == row.id
                and item.source_version == expected
            )

    matter_ids = grouped.get("matter", set())
    if matter_ids:
        for row in session.scalars(
            select(Matter).where(
                Matter.company_id == context.company.id,
                Matter.id.in_(matter_ids),
                Matter.is_active.is_(True),
                visible_matters_filter(session, context=context),
            )
        ).all():
            allowed.update(
                item.id
                for item in projections
                if item.source_type == "matter"
                and item.source_id == row.id
                and item.source_version == private_source_version(row)
            )

    attachment_ids = grouped.get("matter_document", set())
    if attachment_ids:
        for attachment, _matter in session.execute(
            select(MatterAttachment, Matter)
            .join(Matter, Matter.id == MatterAttachment.matter_id)
            .where(
                Matter.company_id == context.company.id,
                Matter.is_active.is_(True),
                MatterAttachment.processing_status == "indexed",
                MatterAttachment.id.in_(attachment_ids),
                visible_matters_filter(session, context=context),
            )
        ).all():
            allowed.update(
                item.id
                for item in projections
                if item.source_type == "matter_document"
                and item.source_id == attachment.id
                and item.source_version == attachment.sha256_hex
            )

    docket_ids = grouped.get("ip_docket", set())
    if docket_ids:
        for row in session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.company_id == context.company.id,
                IpDocketRecord.id.in_(docket_ids),
                IpDocketRecord.is_active.is_(True),
                visible_ip_dockets_filter(session, context=context),
            )
        ).all():
            allowed.update(
                item.id
                for item in projections
                if item.source_type == "ip_docket"
                and item.source_id == row.id
                and item.source_version == private_source_version(row)
            )

    document_ids = grouped.get("ip_document", set())
    if document_ids:
        policies = get_ip_document_policies(
            session,
            context=context,
            document_ids=document_ids,
        )
        current_versions = dict(
            session.execute(
                select(IpDocument.id, IpDocument.current_version).where(
                    IpDocument.company_id == context.company.id,
                    IpDocument.id.in_(set(policies)),
                )
            ).all()
        )
        allowed.update(
            item.id
            for item in projections
            if item.source_type == "ip_document"
            and item.source_id in policies
            and policies[item.source_id].ai_retrieval_allowed
            and item.source_version == str(current_versions[item.source_id])
        )
    return allowed


def _current_authorized_projection_rows(
    session: Session,
    *,
    context: SessionContext,
    generation: PrivateIndexGeneration,
    projection_ids: Iterable[str],
) -> tuple[PrivateIndexProjection, ...]:
    ids = tuple(dict.fromkeys(projection_ids))[:MAX_PREFILTER_CANDIDATES]
    if not ids:
        return ()
    authorized_ids = set(
        session.scalars(
            _authorized_projection_ids_statement(
                session,
                context=context,
                generation=generation,
            ).where(PrivateIndexProjection.id.in_(ids))
        ).all()
    )
    if not authorized_ids:
        return ()
    rows = list(
        session.scalars(
            select(PrivateIndexProjection).where(
                PrivateIndexProjection.company_id == context.company.id,
                PrivateIndexProjection.generation_id == generation.id,
                PrivateIndexProjection.id.in_(authorized_ids),
            )
        ).all()
    )
    current_source_ids = _source_versions_still_current(
        session,
        context=context,
        projections=rows,
    )
    by_id = {
        row.id: row for row in rows if row.id in authorized_ids and row.id in current_source_ids
    }
    return tuple(by_id[row_id] for row_id in ids if row_id in by_id)


def hydrate_private_projection_results(
    session: Session,
    *,
    context: SessionContext,
    projection_ids: Iterable[str],
    query: str,
    query_embedding: Sequence[float] | None = None,
    required_capability: str = "ai:generate",
    limit: int = MAX_PRIVATE_RESULTS,
) -> tuple[HydratedPrivateResult, ...]:
    """Reauthorize candidates and expose no metadata for stale/revoked rows."""

    ids = tuple(dict.fromkeys(projection_ids))[:MAX_PREFILTER_CANDIDATES]
    if not ids:
        return ()
    current_context = _refreshed_context(
        session,
        context=context,
        required_capability=required_capability,
    )
    if current_context is None:
        return ()
    generation = session.scalar(_active_generation_statement(context.company.id))
    if generation is None:
        return ()
    rows = _current_authorized_projection_rows(
        session,
        context=current_context,
        generation=generation,
        projection_ids=ids,
    )
    terms = _query_terms(query)
    ranked: list[tuple[float, PrivateIndexProjection]] = []
    for row in rows:
        lowered = row.content_text.casefold()
        lexical = sum(lowered.count(term) for term in terms) / max(1, len(terms))
        vector = 0.0
        if query_embedding is not None and row.embedding_json:
            try:
                embedding = tuple(float(value) for value in json.loads(row.embedding_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                embedding = ()
            vector = _cosine_similarity(tuple(query_embedding), embedding)
        ranked.append((lexical + vector, row))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    bounded = max(1, min(limit, MAX_PRIVATE_RESULTS))
    return tuple(
        HydratedPrivateResult(
            projection_id=row.id,
            source_type=row.source_type,
            source_id=row.source_id,
            source_version=row.source_version,
            label=row.label,
            content=row.content_text,
            score=score,
        )
        for score, row in ranked[:bounded]
    )


def private_retrieval_cache_key(
    *,
    company_id: str,
    membership_id: str,
    generation_id: str,
    access_policy_generation: int,
    tombstone_generation: int,
    query: str,
    source_types: set[str] | None,
    filters: dict[str, object] | None,
    locale: str,
    required_capability: str = "ai:generate",
) -> str:
    material = json.dumps(
        {
            "company_id": company_id,
            "membership_id": membership_id,
            "required_capability": required_capability,
            "generation_id": generation_id,
            "access_policy_generation": access_policy_generation,
            "tombstone_generation": tombstone_generation,
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "source_types": sorted(source_types or ()),
            "filters": filters or {},
            "locale": locale.casefold(),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"private:{company_id}:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def invalidate_private_retrieval_cache(*, company_id: str) -> None:
    prefix = f"private:{company_id}:"
    with _CACHE_LOCK:
        for key in tuple(_CANDIDATE_CACHE):
            if key.startswith(prefix):
                _CANDIDATE_CACHE.pop(key, None)


def retrieve_private_content(
    session: Session,
    *,
    context: SessionContext,
    query: str,
    source_types: set[PrivateSourceType] | None = None,
    filters: dict[str, object] | None = None,
    locale: str = "en-IN",
    query_embedding: Sequence[float] | None = None,
    required_capability: str = "ai:generate",
    require_activation: bool = False,
    limit: int = MAX_PRIVATE_RESULTS,
) -> tuple[HydratedPrivateResult, ...]:
    fence = capture_private_retrieval_fence(
        session,
        context=context,
        required_capability=required_capability,
        require_activation=require_activation,
    )
    if fence is None:
        return ()
    key = private_retrieval_cache_key(
        company_id=context.company.id,
        membership_id=context.membership.id,
        generation_id=fence.generation_id,
        access_policy_generation=fence.access_policy_generation,
        tombstone_generation=fence.tombstone_generation,
        query=query,
        source_types=set(source_types or ()),
        filters=filters,
        locale=locale,
        required_capability=required_capability,
    )
    now = datetime.now(UTC)
    with _CACHE_LOCK:
        cached = _CANDIDATE_CACHE.get(key)
        if cached is not None and now - cached[0] <= _CACHE_TTL:
            candidate_ids = cached[1]
            _CANDIDATE_CACHE.move_to_end(key)
        else:
            if cached is not None:
                _CANDIDATE_CACHE.pop(key, None)
            candidate_ids = ()
    if not candidate_ids:
        candidate_ids = prefilter_private_projection_ids(
            session,
            context=context,
            query=query,
            source_types=source_types,
            filters=filters,
            required_capability=required_capability,
            require_lexical_match=query_embedding is None,
        )
        with _CACHE_LOCK:
            _CANDIDATE_CACHE[key] = (now, candidate_ids)
            _CANDIDATE_CACHE.move_to_end(key)
            while len(_CANDIDATE_CACHE) > _CACHE_MAX_ENTRIES:
                _CANDIDATE_CACHE.popitem(last=False)
    # Cached IDs are never returned directly.  This reauthorization is the
    # security boundary that makes a stale cache harmless after revocation.
    return _private_results_for_delivery(
        session,
        fence=fence,
        projection_ids=candidate_ids,
        query=query,
        query_embedding=query_embedding,
        limit=limit,
    )


def _private_results_for_delivery(
    session: Session,
    *,
    fence: PrivateRetrievalFence,
    projection_ids: Iterable[str],
    query: str,
    query_embedding: Sequence[float] | None = None,
    limit: int = MAX_PRIVATE_RESULTS,
) -> tuple[HydratedPrivateResult, ...]:
    """Reauthorize exact epochs and sources immediately before serialization."""

    ids = tuple(dict.fromkeys(projection_ids))[:MAX_PREFILTER_CANDIDATES]
    delivery = _private_delivery_context(session, fence=fence)
    if delivery is None or not ids:
        return ()
    context, generation = delivery
    rows = _current_authorized_projection_rows(
        session,
        context=context,
        generation=generation,
        projection_ids=ids,
    )
    # This function is called only at the final serialization boundary. Stream
    # callers open a fresh session for each row, so this one bounded query set
    # is both the last authorization decision and resistant to N+1 work.
    terms = _query_terms(query)
    ranked: list[tuple[float, PrivateIndexProjection]] = []
    for row in rows:
        lowered = row.content_text.casefold()
        lexical = sum(lowered.count(term) for term in terms) / max(1, len(terms))
        vector = 0.0
        if query_embedding is not None and row.embedding_json:
            try:
                embedding = tuple(float(value) for value in json.loads(row.embedding_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                embedding = ()
            vector = _cosine_similarity(tuple(query_embedding), embedding)
        ranked.append((lexical + vector, row))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    bounded = max(1, min(limit, MAX_PRIVATE_RESULTS))
    return tuple(
        HydratedPrivateResult(
            projection_id=row.id,
            source_type=row.source_type,
            source_id=row.source_id,
            source_version=row.source_version,
            label=row.label,
            content=row.content_text,
            score=score,
        )
        for score, row in ranked[:bounded]
    )


def autocomplete_private_content(
    session: Session,
    *,
    context: SessionContext,
    query: str,
    source_types: set[PrivateSourceType] | None = None,
    filters: dict[str, object] | None = None,
    required_capability: str = "ai:generate",
    limit: int = 12,
) -> tuple[PrivateAutocompleteSuggestion, ...]:
    """Return authorized labels only; private content never enters the response."""

    fence = capture_private_retrieval_fence(
        session,
        context=context,
        required_capability=required_capability,
        require_activation=True,
    )
    if fence is None:
        return ()
    candidate_ids = prefilter_private_projection_ids(
        session,
        context=context,
        query=query,
        source_types=source_types,
        filters=filters,
        required_capability=required_capability,
        limit=min(limit, MAX_PRIVATE_RESULTS),
    )
    rows = _private_results_for_delivery(
        session,
        fence=fence,
        projection_ids=candidate_ids,
        query=query,
        limit=limit,
    )
    return tuple(
        PrivateAutocompleteSuggestion(
            projection_id=row.projection_id,
            source_type=row.source_type,
            source_id=row.source_id,
            source_version=row.source_version,
            label=row.label,
        )
        for row in rows
    )


def count_private_content(
    session: Session,
    *,
    context: SessionContext,
    query: str,
    source_types: set[PrivateSourceType] | None = None,
    filters: dict[str, object] | None = None,
    required_capability: str = "ai:generate",
) -> int:
    """Count only bounded, current rows reauthorized at count delivery time."""

    fence = capture_private_retrieval_fence(
        session,
        context=context,
        required_capability=required_capability,
        require_activation=True,
    )
    if fence is None:
        return 0
    candidate_ids = prefilter_private_projection_ids(
        session,
        context=context,
        query=query,
        source_types=source_types,
        filters=filters,
        required_capability=required_capability,
        limit=MAX_PREFILTER_CANDIDATES,
    )
    delivery = _private_delivery_context(session, fence=fence)
    if delivery is None:
        return 0
    current_context, generation = delivery
    rows = _current_authorized_projection_rows(
        session,
        context=current_context,
        generation=generation,
        projection_ids=candidate_ids,
    )
    return len(rows)


def stream_private_content(
    *,
    fence: PrivateRetrievalFence,
    projection_ids: Iterable[str],
    query: str,
    session_factory: Callable[[], Session],
    limit: int = MAX_PRIVATE_RESULTS,
) -> Iterator[HydratedPrivateResult]:
    """Stream rows with a fresh security/source check before every emission."""

    candidate_ids = tuple(dict.fromkeys(projection_ids))[:MAX_PREFILTER_CANDIDATES]
    if not candidate_ids:
        return
    with session_factory() as ordering_session:
        ordered = _private_results_for_delivery(
            ordering_session,
            fence=fence,
            projection_ids=candidate_ids,
            query=query,
            limit=limit,
        )
        ordered_ids = tuple(row.projection_id for row in ordered)
    for projection_id in ordered_ids:
        with session_factory() as delivery_session:
            delivered = _private_results_for_delivery(
                delivery_session,
                fence=fence,
                projection_ids=(projection_id,),
                query=query,
                limit=1,
            )
        if len(delivered) != 1:
            # Do not skip and continue: absence may mean a mid-stream revoke.
            # Termination exposes neither which row changed nor any later text.
            return
        yield delivered[0]


def capture_private_saved_source_manifest(
    session: Session,
    *,
    context: SessionContext,
    sources: Iterable[tuple[str, str]],
) -> tuple[dict[str, object], ...]:
    """Freeze exact private projection/ACL epochs for a saved output.

    Tenants without an active private generation remain on the existing
    default-off path. Once a generation exists, a saved output may not claim a
    private source unless every requested source has a current, authorized
    projection in that exact generation.
    """

    requested = tuple(dict.fromkeys(sources))
    if not requested:
        return ()
    if any(
        source_type not in {"client", "matter", "matter_document", "ip_docket", "ip_document"}
        or not source_id
        for source_type, source_id in requested
    ):
        raise PrivateRetrievalInvariantError("Saved-output private sources are invalid.")
    generation = session.scalar(_active_generation_statement(context.company.id))
    if generation is None:
        return ()
    requested_predicate = or_(
        *(
            and_(
                PrivateIndexProjection.source_type == source_type,
                PrivateIndexProjection.source_id == source_id,
            )
            for source_type, source_id in requested
        )
    )
    rows = list(
        session.scalars(
            select(PrivateIndexProjection).where(
                PrivateIndexProjection.company_id == context.company.id,
                PrivateIndexProjection.generation_id == generation.id,
                requested_predicate,
            )
        ).all()
    )
    authorized_ids = set(
        session.scalars(
            _authorized_projection_ids_statement(
                session,
                context=context,
                generation=generation,
            ).where(requested_predicate)
        ).all()
    )
    current_ids = _source_versions_still_current(
        session,
        context=context,
        projections=rows,
    )
    current_rows = [row for row in rows if row.id in authorized_ids and row.id in current_ids]
    available = {(row.source_type, row.source_id) for row in current_rows}
    if available != set(requested):
        raise PrivateRetrievalInvariantError(
            "A current authorized private projection is required before saving output."
        )
    return tuple(
        {
            "schema": PRIVATE_SAVED_SOURCE_SCHEMA,
            "generation_id": generation.id,
            "access_policy_generation": generation.access_policy_generation,
            "tombstone_generation": generation.tombstone_generation,
            "projection_id": row.id,
            "source_type": row.source_type,
            "source_id": row.source_id,
            "source_version": row.source_version,
            "source_sha256": row.content_sha256,
        }
        for row in sorted(current_rows, key=lambda item: item.id)
    )


def private_saved_source_manifest_is_current(
    session: Session,
    *,
    context: SessionContext,
    manifest: Iterable[object],
) -> bool:
    """Reauthorize a saved-output manifest without exposing failed entries.

    A shadow rebuild gives every equivalent projection a new generation and
    projection ID.  That generation change alone is not an access or source
    change: unrelated source creation must not make every previously saved
    draft unreadable.  When the saved generation has been retired, compare
    the complete source/version/hash multiset with the active generation and
    re-run current-source plus ACL authorization there.

    The retired projection is still part of the security proof.  Projection
    events tombstone affected rows across generations, so a source, parent
    scope, tenant access, or tombstone event keeps this path fail-closed even
    if a later rebuild happens to contain equivalent text.
    """

    entries = [
        item
        for item in manifest
        if isinstance(item, dict) and item.get("schema") == PRIVATE_SAVED_SOURCE_SCHEMA
    ]
    if not entries:
        return True
    generation = session.scalar(_active_generation_statement(context.company.id))
    if generation is None:
        return False
    projection_ids = {
        str(item.get("projection_id")) for item in entries if item.get("projection_id")
    }
    if len(projection_ids) != len(entries):
        return False
    saved_rows = list(
        session.scalars(
            select(PrivateIndexProjection).where(
                PrivateIndexProjection.company_id == context.company.id,
                PrivateIndexProjection.id.in_(projection_ids),
            )
        ).all()
    )
    if len(saved_rows) != len(entries):
        return False
    saved_by_id = {row.id: row for row in saved_rows}
    saved_generation_ids = {str(item.get("generation_id")) for item in entries}
    if len(saved_generation_ids) != 1 or "None" in saved_generation_ids:
        return False
    saved_generation_id = next(iter(saved_generation_ids))
    saved_generation = session.scalar(
        select(PrivateIndexGeneration).where(
            PrivateIndexGeneration.id == saved_generation_id,
            PrivateIndexGeneration.company_id == context.company.id,
        )
    )
    if saved_generation is None:
        return False
    for item in entries:
        row = saved_by_id.get(str(item["projection_id"]))
        if (
            row is None
            or row.generation_id != saved_generation_id
            or row.is_tombstoned
            or item.get("source_type") != row.source_type
            or item.get("source_id") != row.source_id
            or item.get("source_version") != row.source_version
            or item.get("source_sha256") != row.content_sha256
        ):
            return False

    if saved_generation_id == generation.id:
        if any(
            item.get("access_policy_generation") != generation.access_policy_generation
            or item.get("tombstone_generation") != generation.tombstone_generation
            for item in entries
        ):
            return False
        current_rows = saved_rows
    else:
        source_pairs = {
            (str(item.get("source_type")), str(item.get("source_id"))) for item in entries
        }
        current_rows = list(
            session.scalars(
                select(PrivateIndexProjection).where(
                    PrivateIndexProjection.company_id == context.company.id,
                    PrivateIndexProjection.generation_id == generation.id,
                    PrivateIndexProjection.is_tombstoned.is_(False),
                    or_(
                        *(
                            and_(
                                PrivateIndexProjection.source_type == source_type,
                                PrivateIndexProjection.source_id == source_id,
                            )
                            for source_type, source_id in sorted(source_pairs)
                        )
                    ),
                )
            ).all()
        )
        saved_keys = Counter(
            (
                str(item.get("source_type")),
                str(item.get("source_id")),
                str(item.get("source_version")),
                str(item.get("source_sha256")),
            )
            for item in entries
        )
        current_keys = Counter(
            (row.source_type, row.source_id, row.source_version, row.content_sha256)
            for row in current_rows
        )
        if saved_keys != current_keys:
            return False

    current_projection_ids = {row.id for row in current_rows}
    if len(current_projection_ids) != len(entries):
        return False
    authorized_ids = set(
        session.scalars(
            _authorized_projection_ids_statement(
                session,
                context=context,
                generation=generation,
            ).where(PrivateIndexProjection.id.in_(current_projection_ids))
        ).all()
    )
    current_ids = _source_versions_still_current(
        session,
        context=context,
        projections=current_rows,
    )
    return current_projection_ids <= authorized_ids and current_projection_ids <= current_ids


def enqueue_private_projection_event(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str,
    idempotency_key: str,
    event_type: PrivateEventType,
    target_type: str,
    target_id: str,
    target_version: str | None,
    reason_code: str,
) -> PrivateProjectionEvent:
    canonical_key = build_private_projection_event_key(idempotency_key)
    _lock_private_company(session, company_id=company_id)
    existing = session.scalar(
        select(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == company_id,
            PrivateProjectionEvent.idempotency_key == canonical_key,
        )
    )
    if existing is not None:
        if (
            existing.event_type != event_type
            or existing.target_type != target_type
            or existing.target_id != target_id
            or existing.target_version != target_version
            or existing.reason_code != reason_code[:120]
            or existing.actor_membership_id != actor_membership_id
        ):
            raise PrivateRetrievalInvariantError(
                "A private projection idempotency key cannot identify a different event."
            )
        return existing
    generation = session.scalar(
        _active_generation_statement(company_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if generation is None:
        generation = ensure_active_private_generation(session, company_id=company_id)
    if event_type == "access_changed":
        generation.access_policy_generation += 1
    else:
        generation.tombstone_generation += 1
    row = PrivateProjectionEvent(
        company_id=company_id,
        generation_id=generation.id,
        idempotency_key=canonical_key,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        target_version=target_version,
        access_policy_generation=generation.access_policy_generation,
        tombstone_generation=generation.tombstone_generation,
        status="pending",
        reason_code=reason_code[:120],
        actor_membership_id=actor_membership_id,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    invalidate_private_retrieval_cache(company_id=company_id)
    return row


def _affected_projection_statement(event: PrivateProjectionEvent):
    direct = and_(
        PrivateIndexProjection.source_type == event.target_type,
        PrivateIndexProjection.source_id == event.target_id,
    )
    if event.target_type in {"client", "matter", "ip_docket"}:
        scoped = exists(
            select(PrivateIndexProjectionScope.id).where(
                PrivateIndexProjectionScope.company_id == event.company_id,
                PrivateIndexProjectionScope.projection_id == PrivateIndexProjection.id,
                PrivateIndexProjectionScope.scope_type == event.target_type,
                PrivateIndexProjectionScope.scope_id == event.target_id,
            )
        )
    else:
        scoped = False
    target = True if event.target_type == "tenant" else or_(direct, scoped)
    return select(PrivateIndexProjection).where(
        PrivateIndexProjection.company_id == event.company_id,
        PrivateIndexProjection.generation_id == event.generation_id,
        PrivateIndexProjection.is_tombstoned.is_(False),
        target,
    )


def apply_private_projection_event(session: Session, *, event_id: str) -> PrivateProjectionEvent:
    event = session.scalar(
        select(PrivateProjectionEvent)
        .where(PrivateProjectionEvent.id == event_id)
        .with_for_update()
    )
    if event is None:
        raise PrivateRetrievalInvariantError("Private projection event does not exist.")
    if event.status == "applied":
        return event
    now = datetime.now(UTC)
    if event.target_type == "tenant":
        # Tenant disposition must neutralize active, retired, and unreadable
        # shadow generations. A set-based update tolerates a concurrent failed-
        # shadow delete without retaining ORM instances that later go stale.
        result = session.execute(
            update(PrivateIndexProjection)
            .where(
                PrivateIndexProjection.company_id == event.company_id,
                or_(
                    PrivateIndexProjection.is_tombstoned.is_(False),
                    PrivateIndexProjection.content_text != "",
                    PrivateIndexProjection.embedding_json.is_not(None),
                ),
            )
            .values(
                content_text="",
                embedding_json=None,
                embedding_dimensions=None,
                is_tombstoned=True,
                tombstoned_at=now,
                tombstone_reason=event.reason_code,
                tombstone_generation=event.tombstone_generation,
                updated_at=now,
            )
            .execution_options(synchronize_session="fetch")
        )
        affected: list[PrivateIndexProjection] = []
        affected_sources: set[tuple[str, str]] = set()
        affected_projection_count = max(int(result.rowcount or 0), 0)
    else:
        affected = list(session.scalars(_affected_projection_statement(event)).all())
        affected_sources = {(row.source_type, row.source_id) for row in affected}
        affected_projection_count = len(affected)
        for row in affected:
            row.content_text = ""
            row.embedding_json = None
            row.embedding_dimensions = None
            row.is_tombstoned = True
            row.tombstoned_at = now
            row.tombstone_reason = event.reason_code
            row.tombstone_generation = event.tombstone_generation
            row.updated_at = now

    if event.event_type in {"source_changed", "reindex"} and not affected:
        # A newly created source has no old projection to tombstone. Explicitly
        # invalidate the active manifest so bounded maintenance rebuilds the
        # tenant instead of treating the still internally consistent old
        # generation as complete forever.
        active_generation = session.scalar(
            select(PrivateIndexGeneration)
            .where(
                PrivateIndexGeneration.company_id == event.company_id,
                PrivateIndexGeneration.state == "active",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if active_generation is None:
            raise PrivateRetrievalInvariantError(
                "A source-creation event requires an active private generation."
            )
        active_generation.expected_projection_count = None
        active_generation.verified_projection_count = None
        active_generation.verification_sha256 = None
        active_generation.verified_at = None

    output_filter = (
        True
        if event.target_type == "tenant"
        else or_(
            and_(
                PrivateSavedOutputAccess.source_type == event.target_type,
                PrivateSavedOutputAccess.source_id == event.target_id,
            ),
            *(
                and_(
                    PrivateSavedOutputAccess.source_type == source_type,
                    PrivateSavedOutputAccess.source_id == source_id,
                )
                for source_type, source_id in sorted(affected_sources)
            ),
        )
    )
    outputs = list(
        session.scalars(
            select(PrivateSavedOutputAccess).where(
                PrivateSavedOutputAccess.company_id == event.company_id,
                output_filter,
                PrivateSavedOutputAccess.state.not_in(("locked", "redacted")),
            )
        ).all()
    )
    output_state = "reauthorization_required" if event.event_type == "access_changed" else "locked"
    for row in outputs:
        row.state = output_state
        row.locked_reason = event.reason_code
        row.locked_at = now
        row.access_policy_generation = event.access_policy_generation
        row.tombstone_generation = event.tombstone_generation
        row.updated_at = now
    shadow_generations = list(
        session.scalars(
            select(PrivateIndexGeneration)
            .where(
                PrivateIndexGeneration.company_id == event.company_id,
                PrivateIndexGeneration.state.in_(("building", "ready")),
            )
            .with_for_update()
        ).all()
    )
    for generation in shadow_generations:
        generation.access_policy_generation = max(
            generation.access_policy_generation,
            event.access_policy_generation,
        )
        generation.tombstone_generation = max(
            generation.tombstone_generation,
            event.tombstone_generation,
        )
        # An event after readiness invalidates the old verification manifest.
        if generation.state == "ready":
            generation.state = "building"
            generation.expected_projection_count = None
            generation.verified_projection_count = None
            generation.verification_sha256 = None
            generation.verified_at = None
    event.affected_projection_count = affected_projection_count
    event.affected_saved_output_count = len(outputs)
    event.status = "applied"
    event.applied_at = now
    event.error_code = None
    event.next_attempt_at = None
    session.flush()
    invalidate_private_retrieval_cache(company_id=event.company_id)
    return event


def propagate_private_projection_change(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str,
    idempotency_key: str,
    event_type: PrivateEventType,
    target_type: str,
    target_id: str,
    target_version: str | None,
    reason_code: str,
) -> PrivateProjectionEvent:
    event = enqueue_private_projection_event(
        session,
        company_id=company_id,
        actor_membership_id=actor_membership_id,
        idempotency_key=idempotency_key,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        target_version=target_version,
        reason_code=reason_code,
    )
    return apply_private_projection_event(session, event_id=event.id)


def propagate_private_source_creation(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str,
    idempotency_key: str,
    target_type: Literal["matter", "ip_docket"],
    target_id: str,
    target_version: str,
    reason_code: str,
) -> PrivateProjectionEvent | None:
    """Schedule a rebuild when a tenant already has a private index.

    A tenant that has never activated private retrieval retains the existing
    default-off path. Once an active generation exists, a newly created source
    must not remain invisible forever merely because there was no prior
    projection for the event consumer to tombstone.
    """

    generation_id = session.scalar(
        select(PrivateIndexGeneration.id).where(
            PrivateIndexGeneration.company_id == company_id,
            PrivateIndexGeneration.state == "active",
        )
    )
    if generation_id is None:
        return None
    return propagate_private_projection_change(
        session,
        company_id=company_id,
        actor_membership_id=actor_membership_id,
        idempotency_key=idempotency_key,
        event_type="source_changed",
        target_type=target_type,
        target_id=target_id,
        target_version=target_version,
        reason_code=reason_code,
    )


def register_private_saved_output(
    session: Session,
    *,
    company_id: str,
    assistant_turn_id: str,
    sources: Iterable[tuple[str, str, str, str | None]],
) -> tuple[PrivateSavedOutputAccess, ...]:
    turn = session.scalar(
        select(AssistantTurn).where(
            AssistantTurn.id == assistant_turn_id,
            AssistantTurn.company_id == company_id,
        )
    )
    if turn is None:
        raise PrivateRetrievalInvariantError("Saved assistant output does not exist.")
    generation = ensure_active_private_generation(session, company_id=company_id)
    now = datetime.now(UTC)
    source_rows = tuple(sources)
    existing_rows = list(
        session.scalars(
            select(PrivateSavedOutputAccess).where(
                PrivateSavedOutputAccess.company_id == company_id,
                PrivateSavedOutputAccess.assistant_turn_id == assistant_turn_id,
            )
        ).all()
    )
    existing_by_key = {
        (row.source_type, row.source_id, row.source_version): row for row in existing_rows
    }
    rows: list[PrivateSavedOutputAccess] = []
    for source_type, source_id, source_version, source_sha256 in source_rows:
        row = existing_by_key.get((source_type, source_id, source_version))
        if row is None:
            row = PrivateSavedOutputAccess(
                company_id=company_id,
                assistant_turn_id=assistant_turn_id,
                generation_id=generation.id,
                source_type=source_type,
                source_id=source_id,
                source_version=source_version,
                source_sha256=source_sha256,
                access_policy_generation=generation.access_policy_generation,
                tombstone_generation=generation.tombstone_generation,
                state="accessible",
                last_reauthorized_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        rows.append(row)
    session.flush()
    return tuple(rows)


def reauthorize_private_saved_outputs(
    session: Session,
    *,
    company_id: str,
    assistant_turn_ids: set[str],
    accessible_sources: set[tuple[str, str, str]],
) -> set[str]:
    """Refresh manifests and return turn IDs that must render locked/redacted."""

    if not assistant_turn_ids:
        return set()
    rows = list(
        session.scalars(
            select(PrivateSavedOutputAccess).where(
                PrivateSavedOutputAccess.company_id == company_id,
                PrivateSavedOutputAccess.assistant_turn_id.in_(assistant_turn_ids),
            )
        ).all()
    )
    now = datetime.now(UTC)
    blocked: set[str] = set()
    for row in rows:
        key = (row.source_type, row.source_id, row.source_version)
        if row.state in {"locked", "redacted"} or key not in accessible_sources:
            row.state = "locked"
            row.locked_reason = row.locked_reason or "source_access_or_version_changed"
            row.locked_at = row.locked_at or now
            blocked.add(row.assistant_turn_id)
        else:
            row.state = "accessible"
            row.locked_reason = None
            row.locked_at = None
            row.last_reauthorized_at = now
        row.updated_at = now
    session.flush()
    return blocked


__all__ = [
    "HydratedPrivateResult",
    "MAX_PREFILTER_CANDIDATES",
    "PRIVATE_PROJECTION_EVENT_KEY_MAX_LENGTH",
    "PRIVATE_SAVED_SOURCE_SCHEMA",
    "STALE_PRIVATE_PROJECTION_WRITER_DETAIL",
    "PrivateAutocompleteSuggestion",
    "PrivateProjectionInput",
    "PrivateRetrievalActivation",
    "PrivateRetrievalConcurrencyError",
    "PrivateRetrievalFence",
    "PrivateRetrievalInvariantError",
    "ProjectionScopeInput",
    "activate_private_generation",
    "apply_private_projection_event",
    "autocomplete_private_content",
    "build_private_projection_event_key",
    "capture_private_retrieval_fence",
    "capture_private_saved_source_manifest",
    "count_private_content",
    "create_shadow_private_generation",
    "ensure_active_private_generation",
    "hydrate_private_projection_results",
    "insert_private_projection_batch",
    "mark_private_generation_ready",
    "prefilter_private_projection_ids",
    "private_retrieval_activation",
    "private_retrieval_cache_key",
    "private_saved_source_manifest_is_current",
    "private_source_version",
    "propagate_private_source_creation",
    "propagate_private_projection_change",
    "reauthorize_private_saved_outputs",
    "register_private_saved_output",
    "retrieve_private_content",
    "stream_private_content",
    "upsert_private_projection",
]
