"""Fail-closed records-governance foundations for IPLF-028A.

This module creates evidence-only dry-run manifests.  It deliberately has no
worker, HTTP route, storage adapter, provider adapter, or execution path.  A
future slice must add explicit approval, step-up, rollout, and restore/export
proof before any real data action is even representable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    DataRetentionPolicyVersion,
    LegalHold,
    LegalHoldItem,
    LegalHoldStatus,
    TenantDataOperation,
    TenantDataOperationItem,
)
from caseops_api.schemas.data_governance import (
    TenantDataOperationDryRunRecord,
    TenantDataOperationDryRunRequest,
    TenantDataOperationItemRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext

# This is only the IPLF-028A foundation inventory.  The later M2/M3 data-map
# work must expand it to every in-scope SQL/object/index/cache/queue/log/export
# class before an operation surface can be released.
FOUNDATION_DATA_CLASS_IDS = frozenset(
    {
        "data_retention_policies",
        "data_retention_versions",
        "legal_holds",
        "legal_hold_items",
        "tenant_data_operations",
        "tenant_data_operation_items",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _actor_label(context: SessionContext) -> str:
    return context.user.full_name or context.user.email


def _registered_item_scope(payload: TenantDataOperationDryRunRequest) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    normalized: list[dict] = []
    for item in payload.items:
        data_class_id = item.data_class_id.strip()
        if data_class_id not in FOUNDATION_DATA_CLASS_IDS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "data_class_not_registered_for_dry_run",
                    "detail": (
                        "The IPLF-028A dry-run foundation accepts only its "
                        "registered governance data classes."
                    ),
                    "data_class_id": data_class_id,
                },
            )
        target_type = item.target_type.strip().lower()
        key = (data_class_id, target_type, item.target_reference_hash)
        if key in seen:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "duplicate_data_operation_target",
                    "detail": "Each data-operation target may appear only once.",
                },
            )
        seen.add(key)
        normalized.append(
            {
                "data_class_id": data_class_id,
                "target_type": target_type,
                "target_reference_hash": item.target_reference_hash,
                "candidate_record_count": item.candidate_record_count,
                "estimated_bytes": item.estimated_bytes,
                "detail_redacted": item.detail_redacted,
            }
        )
    return sorted(
        normalized,
        key=lambda row: (
            row["data_class_id"],
            row["target_type"],
            row["target_reference_hash"],
        ),
    )


def _active_hold_ids(session: Session, *, company_id: str) -> list[str]:
    """Return active hold IDs in deterministic order."""

    return list(
        session.scalars(
            select(LegalHold.id)
            .where(
                LegalHold.company_id == company_id,
                LegalHold.status == LegalHoldStatus.ACTIVE,
            )
            .order_by(LegalHold.id)
        ).all()
    )


# A hold item whose target_type is this covers an entire data class rather than
# one record, which is how "target ... data class" in DATA-GOV-04 is expressed.
HOLD_TARGET_TYPE_DATA_CLASS = "data_class"


def resolve_hold_for_target(
    session: Session,
    *,
    company_id: str,
    data_class_id: str,
    target_type: str | None = None,
    target_reference_hash: str | None = None,
) -> str | None:
    """Return the id of an active legal hold covering this target, or ``None``.

    DATA-GOV-04 requires a hold to target a company, client, record, custodian,
    data class or date range, and to preserve covered data. Until now the
    dry-run manifest treated ANY active hold as covering EVERY target: correct
    in direction, since it can only over-block, but it makes a scoped hold
    indistinguishable from a company-wide one and marks unrelated data as held.

    Coverage is decided in this order, and the order is the safety property:

    1. An active hold with NO items is company-wide. This preserves the previous
       behaviour exactly, and it is why an unscoped hold cannot silently narrow.
       Holds are itemless in practice today - nothing in the application writes
       ``LegalHoldItem`` yet - so this is the live path.
    2. An item naming the data class (``target_type='data_class'``) covers every
       record in that class.
    3. An item naming the exact record covers that record.

    Ties resolve to the lowest hold id so a manifest is reproducible.

    Fail-closed by construction: the function only ever narrows coverage when an
    item explicitly says so, and any hold it cannot interpret still matches at
    step 1. A caller must treat a non-None result as "blocked".
    """

    active_ids = _active_hold_ids(session, company_id=company_id)
    if not active_ids:
        return None

    items = list(
        session.scalars(
            select(LegalHoldItem)
            .where(
                LegalHoldItem.company_id == company_id,
                LegalHoldItem.legal_hold_id.in_(active_ids),
            )
            .order_by(LegalHoldItem.legal_hold_id, LegalHoldItem.id)
        ).all()
    )
    items_by_hold: dict[str, list[LegalHoldItem]] = {}
    for item in items:
        items_by_hold.setdefault(item.legal_hold_id, []).append(item)

    for hold_id in active_ids:
        hold_items = items_by_hold.get(hold_id)
        if not hold_items:
            return hold_id
        for item in hold_items:
            if item.data_class_id != data_class_id:
                continue
            if item.target_type == HOLD_TARGET_TYPE_DATA_CLASS:
                return hold_id
            if (
                target_type is not None
                and target_reference_hash is not None
                and item.target_type == target_type
                and item.target_reference_hash == target_reference_hash
            ):
                return hold_id
    return None


def create_dry_run_manifest(
    session: Session,
    *,
    context: SessionContext,
    payload: TenantDataOperationDryRunRequest,
) -> TenantDataOperationDryRunRecord:
    """Persist a synthetic, hold-aware dry-run manifest and nothing else.

    The function never reads production objects, downloads bytes, invokes a
    provider, queues work, or exposes an execute mode.  Its only side effects
    are the governance rows and a tenant audit event in the caller's company.
    """

    item_scope = _registered_item_scope(payload)
    policy_version_id = payload.retention_policy_version_id
    if policy_version_id is not None:
        policy = session.scalar(
            select(DataRetentionPolicyVersion).where(
                DataRetentionPolicyVersion.id == policy_version_id,
                DataRetentionPolicyVersion.company_id == context.company.id,
            )
        )
        if policy is None:
            raise HTTPException(status_code=404, detail="Retention policy version not found.")

    request_scope = {
        "schema_version": 1,
        "operation_type": payload.operation_type,
        "execution_mode": "dry_run",
        "items": item_scope,
    }
    request_scope_hash = _canonical_digest(request_scope)
    active_hold_ids = _active_hold_ids(session, company_id=context.company.id)
    now = _now()
    # Resolved per item, not once for the manifest. A hold scoped to one data
    # class previously marked every unrelated item "held", which reads to an
    # operator as far broader preservation than was actually ordered.
    item_records = []
    for item in item_scope:
        item_hold_id = resolve_hold_for_target(
            session,
            company_id=context.company.id,
            data_class_id=item["data_class_id"],
            target_type=item.get("target_type"),
            target_reference_hash=item.get("target_reference_hash"),
        )
        item_records.append(
            {
                **item,
                "item_status": "held" if item_hold_id else "eligible",
                "legal_hold_id": item_hold_id,
                "safe_to_execute": False,
            }
        )
    manifest = {
        "schema_version": 1,
        "operation_type": payload.operation_type,
        "execution_mode": "dry_run",
        "execution_authorization": "absent",
        "request_scope_hash": request_scope_hash,
        "active_hold_ids": active_hold_ids,
        "items": item_records,
    }
    manifest_hash = _canonical_digest(manifest)
    operation = TenantDataOperation(
        company_id=context.company.id,
        operation_type=payload.operation_type,
        execution_mode="dry_run",
        status="dry_run_complete",
        approval_status="not_requested",
        request_scope_json=request_scope,
        request_scope_hash=request_scope_hash,
        request_evidence_ref=payload.request_evidence_ref,
        retention_policy_version_id=policy_version_id,
        manifest_json=manifest,
        manifest_hash=manifest_hash,
        requested_by_membership_id=context.membership.id,
        requested_by_membership_company_id=context.company.id,
        requester_label_snapshot=_actor_label(context),
        dry_run_completed_at=now,
    )
    session.add(operation)
    session.flush()
    rows: list[TenantDataOperationItem] = []
    for item in item_records:
        row = TenantDataOperationItem(
            company_id=context.company.id,
            operation_id=operation.id,
            data_class_id=item["data_class_id"],
            target_type=item["target_type"],
            target_reference_hash=item["target_reference_hash"],
            item_status=item["item_status"],
            candidate_record_count=item["candidate_record_count"],
            estimated_bytes=item["estimated_bytes"],
            legal_hold_id=item["legal_hold_id"],
            safe_to_execute=False,
            detail_redacted=item["detail_redacted"],
        )
        session.add(row)
        rows.append(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="data_governance.operation.dry_run_completed",
        target_type="tenant_data_operation",
        target_id=operation.id,
        metadata={
            "operation_type": payload.operation_type,
            "execution_mode": "dry_run",
            "request_scope_hash": request_scope_hash,
            "manifest_hash": manifest_hash,
            "item_count": len(rows),
            "active_hold_count": len(active_hold_ids),
            "execute_authorized": False,
        },
    )
    session.commit()
    return TenantDataOperationDryRunRecord(
        id=operation.id,
        operation_type=payload.operation_type,
        execution_mode="dry_run",
        status="dry_run_complete",
        approval_status="not_requested",
        request_scope_hash=request_scope_hash,
        manifest_hash=manifest_hash,
        request_evidence_ref=payload.request_evidence_ref,
        completed_at=now,
        items=[
            TenantDataOperationItemRecord(
                id=row.id,
                data_class_id=row.data_class_id,
                target_type=row.target_type,
                target_reference_hash=row.target_reference_hash,
                item_status=row.item_status,
                candidate_record_count=row.candidate_record_count,
                estimated_bytes=row.estimated_bytes,
                legal_hold_id=row.legal_hold_id,
                safe_to_execute=False,
                detail_redacted=row.detail_redacted,
            )
            for row in rows
        ],
    )


def reject_data_operation_execution(*, operation_id: str) -> NoReturn:
    """Ensure future callers cannot mistake a dry-run record for authority."""

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "type": "data_operation_execution_unavailable",
            "detail": (
                "IPLF-028A stores dry-run evidence only; execute, purge, export, "
                "offboarding, restore, and provider actions are not implemented."
            ),
            "operation_id": operation_id,
        },
    )


__all__ = [
    "FOUNDATION_DATA_CLASS_IDS",
    "create_dry_run_manifest",
    "reject_data_operation_execution",
]
