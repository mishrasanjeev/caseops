"""IPLF-071 disposition checkpoints for private search and embedding state.

This module is a subsystem executor, not a tenant-deletion shortcut. It accepts
only an already approved ``TenantDataOperation`` execute row, revalidates the
reviewed dry-run target and hold state, then uses IPLF-066's canonical
tombstone event. Every local/provider outcome is a durable receipt or an
explicit deletion-delay exception; silence can never mean completion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditActorType,
    DataRetentionPolicyVersion,
    DataRetentionPolicyVersionStatus,
    PrivateIndexProjection,
    TenantDataDispositionCheckpoint,
    TenantDataOperation,
    TenantDataOperationItem,
)
from caseops_api.services.audit import record_audit
from caseops_api.services.data_governance import resolve_hold_for_target
from caseops_api.services.private_retrieval import propagate_private_projection_change

PRIVATE_INDEX_SUBSYSTEM = "private_index"
PROVIDER_SUBSYSTEM_PREFIX = "provider_embedding:"
_LOCAL_PROVIDERS = frozenset({"mock", "fastembed", "none"})


class DataDispositionInvariantError(RuntimeError):
    """An approved operation or its immutable evidence is inconsistent."""


def tenant_target_reference_hash(company_id: str) -> str:
    """Return the server-owned hash used by tenant-scoped dry-run items."""

    return hashlib.sha256(f"caseops:tenant:{company_id}".encode()).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _approved_private_operation(
    session: Session,
    *,
    operation_id: str,
) -> tuple[TenantDataOperation, TenantDataOperationItem]:
    operation = session.scalar(
        select(TenantDataOperation).where(TenantDataOperation.id == operation_id).with_for_update()
    )
    if operation is None:
        raise DataDispositionInvariantError("Approved data operation does not exist.")
    if (
        operation.execution_mode != "execute"
        or operation.approval_status != "approved"
        or operation.status != "planned"
        or operation.approves_operation_id is None
        or operation.approved_by_membership_id is None
    ):
        raise DataDispositionInvariantError(
            "Private disposition requires a separately approved execute operation."
        )
    if operation.operation_type not in {"retention_purge", "tenant_offboarding"}:
        raise DataDispositionInvariantError(
            "Private disposition is available only for purge or offboarding operations."
        )
    if operation.operation_type == "retention_purge":
        active_policy = None
        if operation.retention_policy_version_id is not None:
            active_policy = session.scalar(
                select(DataRetentionPolicyVersion).where(
                    DataRetentionPolicyVersion.id == operation.retention_policy_version_id,
                    DataRetentionPolicyVersion.company_id == operation.company_id,
                    DataRetentionPolicyVersion.status == DataRetentionPolicyVersionStatus.ACTIVE,
                )
            )
        if active_policy is None:
            raise DataDispositionInvariantError(
                "The approved retention policy version is no longer active."
            )
    dry_run = session.scalar(
        select(TenantDataOperation).where(
            TenantDataOperation.id == operation.approves_operation_id,
            TenantDataOperation.company_id == operation.company_id,
            TenantDataOperation.execution_mode == "dry_run",
            TenantDataOperation.status == "dry_run_complete",
        )
    )
    if (
        dry_run is None
        or dry_run.manifest_hash != operation.manifest_hash
        or dry_run.request_scope_hash != operation.request_scope_hash
        or dry_run.manifest_json != operation.manifest_json
    ):
        raise DataDispositionInvariantError(
            "The approved execution no longer matches its reviewed dry-run manifest."
        )

    expected_hash = tenant_target_reference_hash(operation.company_id)
    item = session.scalar(
        select(TenantDataOperationItem).where(
            TenantDataOperationItem.operation_id == operation.approves_operation_id,
            TenantDataOperationItem.company_id == operation.company_id,
            TenantDataOperationItem.data_class_id == "private_index_projections",
            TenantDataOperationItem.target_type == "tenant",
            TenantDataOperationItem.target_reference_hash == expected_hash,
        )
    )
    if item is None:
        raise DataDispositionInvariantError(
            "The reviewed manifest does not include the tenant-private index target."
        )
    if item.item_status != "eligible" or item.legal_hold_id is not None:
        raise DataDispositionInvariantError(
            "A held or blocked private-index target cannot be disposed."
        )
    current_hold_id = resolve_hold_for_target(
        session,
        company_id=operation.company_id,
        data_class_id=item.data_class_id,
        target_type=item.target_type,
        target_reference_hash=item.target_reference_hash,
    )
    if current_hold_id is not None:
        raise DataDispositionInvariantError(
            "A currently active legal hold blocks private-index disposition."
        )
    if operation.manifest_hash is None or operation.manifest_json is None:
        raise DataDispositionInvariantError(
            "The approved operation has no immutable dry-run manifest evidence."
        )
    return operation, item


def _provider_names(session: Session, *, company_id: str) -> tuple[str, ...]:
    versions = session.scalars(
        select(PrivateIndexProjection.embedding_version)
        .where(
            PrivateIndexProjection.company_id == company_id,
            PrivateIndexProjection.embedding_version.is_not(None),
        )
        .distinct()
        .limit(20)
    ).all()
    providers = {
        str(value).split(":", 1)[0].strip().casefold()
        for value in versions
        if value and str(value).strip()
    }
    return tuple(sorted(providers or {"none"}))


def _existing_checkpoint(
    session: Session,
    *,
    operation_id: str,
    subsystem: str,
    target_reference_hash: str,
) -> TenantDataDispositionCheckpoint | None:
    return session.scalar(
        select(TenantDataDispositionCheckpoint).where(
            TenantDataDispositionCheckpoint.operation_id == operation_id,
            TenantDataDispositionCheckpoint.subsystem == subsystem,
            TenantDataDispositionCheckpoint.target_type == "tenant",
            TenantDataDispositionCheckpoint.target_reference_hash == target_reference_hash,
        )
    )


def _terminal_checkpoint(
    session: Session,
    *,
    operation: TenantDataOperation,
    subsystem: str,
    provider_name: str | None,
    target_reference_hash: str,
    private_event_id: str,
    now: datetime,
    provider_retention_days: Mapping[str, int],
) -> TenantDataDispositionCheckpoint:
    existing = _existing_checkpoint(
        session,
        operation_id=operation.id,
        subsystem=subsystem,
        target_reference_hash=target_reference_hash,
    )
    if existing is not None:
        if existing.private_event_id != private_event_id:
            raise DataDispositionInvariantError(
                "A disposition checkpoint cannot be rebound to another private event."
            )
        return existing

    is_local = provider_name is None or provider_name in _LOCAL_PROVIDERS
    status = "completed" if is_local else "exception"
    outcome_type = "receipt" if is_local else "deletion_delay_exception"
    retention_days = provider_retention_days.get(provider_name or "", 0)
    expected_resolution_at = now + timedelta(days=retention_days) if retention_days > 0 else None
    receipt = f"caseops://data-disposition/{operation.id}/{subsystem}" if is_local else None
    exception_code = None if is_local else "provider_deletion_contract_delay"
    evidence = {
        "schema_version": 1,
        "operation_id": operation.id,
        "manifest_hash": operation.manifest_hash,
        "subsystem": subsystem,
        "target_type": "tenant",
        "target_reference_hash": target_reference_hash,
        "private_event_id": private_event_id,
        "provider_name": provider_name,
        "outcome_type": outcome_type,
        "provider_receipt_ref": receipt,
        "exception_code": exception_code,
        "expected_resolution_at": (
            expected_resolution_at.isoformat() if expected_resolution_at else None
        ),
        "completed_at": now.isoformat(),
    }
    row = TenantDataDispositionCheckpoint(
        company_id=operation.company_id,
        operation_id=operation.id,
        subsystem=subsystem,
        target_type="tenant",
        target_reference_hash=target_reference_hash,
        status=status,
        outcome_type=outcome_type,
        provider_name=provider_name,
        provider_receipt_ref=receipt,
        exception_code=exception_code,
        expected_resolution_at=expected_resolution_at,
        private_event_id=private_event_id,
        attempt_count=1,
        evidence_json=evidence,
        evidence_sha256=_canonical_digest(evidence),
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    session.add(row)
    session.flush()
    return row


def execute_private_retrieval_disposition(
    session: Session,
    *,
    operation_id: str,
    provider_retention_days: Mapping[str, int] | None = None,
    now: datetime | None = None,
) -> tuple[TenantDataDispositionCheckpoint, ...]:
    """Tombstone one approved tenant's private state and retain outcomes.

    External embedding APIs used by CaseOps do not expose a per-request delete
    endpoint. Such providers therefore produce an explicit contractual-delay
    exception, optionally with a configured resolution date, never a fabricated
    deletion receipt.
    """

    operation, item = _approved_private_operation(session, operation_id=operation_id)
    current = now or datetime.now(UTC)
    providers = _provider_names(session, company_id=operation.company_id)
    event = propagate_private_projection_change(
        session,
        company_id=operation.company_id,
        actor_membership_id=str(operation.approved_by_membership_id),
        idempotency_key=f"data-disposition:{operation.id}:private-index",
        event_type="tombstoned",
        target_type="tenant",
        target_id=operation.company_id,
        target_version=operation.manifest_hash,
        reason_code="approved_tenant_data_disposition",
    )
    unsafe_count = int(
        session.scalar(
            select(func.count(PrivateIndexProjection.id)).where(
                PrivateIndexProjection.company_id == operation.company_id,
                or_(
                    PrivateIndexProjection.is_tombstoned.is_(False),
                    PrivateIndexProjection.content_text != "",
                    PrivateIndexProjection.embedding_json.is_not(None),
                ),
            )
        )
        or 0
    )
    if unsafe_count:
        raise DataDispositionInvariantError(
            "Private disposition did not neutralize every tenant projection."
        )

    retention = dict(provider_retention_days or {})
    checkpoints = [
        _terminal_checkpoint(
            session,
            operation=operation,
            subsystem=PRIVATE_INDEX_SUBSYSTEM,
            provider_name=None,
            target_reference_hash=item.target_reference_hash,
            private_event_id=event.id,
            now=current,
            provider_retention_days=retention,
        )
    ]
    checkpoints.extend(
        _terminal_checkpoint(
            session,
            operation=operation,
            subsystem=f"{PROVIDER_SUBSYSTEM_PREFIX}{provider}",
            provider_name=provider,
            target_reference_hash=item.target_reference_hash,
            private_event_id=event.id,
            now=current,
            provider_retention_days=retention,
        )
        for provider in providers
    )
    record_audit(
        session,
        company_id=operation.company_id,
        actor_type=AuditActorType.HUMAN,
        actor_membership_id=operation.approved_by_membership_id,
        actor_label=operation.approver_label_snapshot,
        action="data_governance.private_disposition.checkpointed",
        target_type="tenant_data_operation",
        target_id=operation.id,
        metadata={
            "manifest_hash": operation.manifest_hash,
            "private_event_id": event.id,
            "checkpoint_count": len(checkpoints),
            "exception_count": sum(row.status == "exception" for row in checkpoints),
        },
    )
    return tuple(checkpoints)


__all__ = [
    "DataDispositionInvariantError",
    "execute_private_retrieval_disposition",
    "tenant_target_reference_hash",
]
