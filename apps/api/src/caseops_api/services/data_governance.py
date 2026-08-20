"""Fail-closed records-governance foundations for IPLF-028A.

This module creates evidence-only dry-run manifests.  The bounded IPLF-028B
API may create and review those manifests, but it deliberately has no worker,
storage adapter, provider adapter, or execution path.  A future slice must add
explicit approval, step-up, rollout, and restore/export proof before any real
data action is even representable.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, NoReturn

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    DataRetentionPolicyVersion,
    DataRetentionPolicyVersionStatus,
    LegalHold,
    LegalHoldItem,
    LegalHoldStatus,
    TenantDataOperation,
    TenantDataOperationItem,
)
from caseops_api.governance.data_class_projection import (
    require_admissible_data_class,
    require_current_projection,
)
from caseops_api.schemas.data_governance import (
    TenantDataGovernanceIntegrityCheck,
    TenantDataGovernanceIntegrityReport,
    TenantDataOperationDependencyPlan,
    TenantDataOperationDryRunListResponse,
    TenantDataOperationDryRunRecord,
    TenantDataOperationDryRunRequest,
    TenantDataOperationDryRunSummary,
    TenantDataOperationExclusion,
    TenantDataOperationItemRecord,
    TenantDataOperationOffboardingCategory,
)
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.governance_integrity_scan import run_integrity_scan
from caseops_api.services.security import require_recent_step_up
from caseops_api.services.session_context import SessionContext
from caseops_api.services.tenant_offboarding import build_offboarding_plan


# This is only the IPLF-028A foundation inventory.  The later M2/M3 data-map
# work must expand it to every in-scope SQL/object/index/cache/queue/log/export
# class before an operation surface can be released.
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


def _lock_dry_run_actor(
    session: Session,
    *,
    context: SessionContext,
) -> SessionContext:
    """Refresh the writer before this audit-producing mutation.

    The route dependency prevents ordinary callers from entering.  This fence
    closes the role/custom-role revocation window before the manifest or its
    actor-backed audit row is persisted.
    """

    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(context.membership.id,),
    )
    actor: CompanyMembership | None = memberships.get(context.membership.id)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Data-governance administration is required.",
        )
    require_locked_membership_capability(session, actor, "audit:export")
    return SessionContext(company=context.company, membership=actor, user=actor.user)


def _registered_item_scope(payload: TenantDataOperationDryRunRequest) -> list[dict]:
    """Resolve every requested class through the reviewed runtime projection.

    Admission used to be a six-name frozenset declared here - a duplicate of the
    reviewed registry, free to drift from it, and unable to distinguish a real
    but unclassified table from a typo. It now comes from the compiled
    projection, which is regenerated from the reviewed artifacts and gated in CI.
    """

    seen: set[tuple[str, str, str]] = set()
    normalized: list[dict] = []
    for item in payload.items:
        data_class_id = item.data_class_id.strip()
        require_admissible_data_class(data_class_id)
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


# DATA-GOV-07 names five categories an export must exclude, and requires each
# exclusion to be DOCUMENTED rather than silently applied. A recipient who
# cannot see what was withheld cannot tell an export that omitted a category on
# purpose from one that missed it by accident - and for a tenant export leaving
# the platform, that difference is the whole assurance.
#
# `reference_metadata` is the second half of the requirement: it states what the
# recipient can still ask for, so an exclusion is a redirection rather than a
# dead end.
EXPORT_EXCLUSIONS: tuple[dict[str, str], ...] = (
    {
        "category": "platform_secrets",
        "reason": "Signing keys, provider credentials and webhook secrets are platform "
        "property and are never tenant data.",
        "reference_metadata": "Credential rotation dates are available through the "
        "security contact.",
    },
    {
        "category": "cross_tenant_and_global_data",
        "reason": "Records owned by other companies, and platform-global reference data, "
        "fall outside this tenant's scope.",
        "reference_metadata": "Global reference corpora are published separately under "
        "their own licence.",
    },
    {
        "category": "internal_provider_cost_and_profit",
        "reason": "Provider unit cost and margin are CaseOps commercial data, not a "
        "record of the tenant's matter.",
        "reference_metadata": "Amounts the tenant was billed remain in the billing "
        "records that ARE exported.",
    },
    {
        "category": "other_clients_restricted_records",
        "reason": "Matter-level restrictions and ethical walls survive an export; a "
        "tenant-wide request does not lift them.",
        "reference_metadata": "Counts of withheld records are reported without titles "
        "or party names.",
    },
    {
        "category": "non_redistributable_source_payloads",
        "reason": "Licensed judgment and statute payloads cannot be redistributed by "
        "CaseOps under their source terms.",
        "reference_metadata": "Citations, neutral identifiers and source URLs are "
        "exported so the recipient can retrieve the original.",
    },
)


def export_exclusions() -> list[dict[str, str]]:
    """The documented exclusion set for a tenant export manifest."""
    return [dict(entry) for entry in EXPORT_EXCLUSIONS]


def _as_utc(value: datetime | None) -> datetime | None:
    """Coerce a stored timestamp to UTC-aware.

    SQLite returns naive datetimes while the application writes aware ones, so
    comparing a stored value against a fresh one raises TypeError. Normalising
    at the comparison keeps the rule expressible on both backends.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _require_distinct_approver(
    *, requester_membership_id: str, approver_membership_id: str
) -> None:
    if requester_membership_id == approver_membership_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "legal_hold_approver_must_be_distinct",
                "detail": (
                    "The person requesting a legal hold change cannot approve it. "
                    "DATA-GOV-05 requires configured dual approval."
                ),
            },
        )


def activate_legal_hold(
    session: Session,
    *,
    context: SessionContext,
    hold_id: str,
    approver_membership_id: str,
    approver_label: str,
) -> LegalHold:
    """Activate a drafted hold under step-up and dual approval (DATA-GOV-05).

    The database already refuses an active hold without a distinct
    company-scoped approver. That constraint is the guarantee; this function is
    where the SECOND control lives - step-up - which a CHECK constraint cannot
    express because it is a property of the session, not the row.
    """

    require_recent_step_up(session, context=context, purpose="legal_hold_change")
    hold = session.get(LegalHold, hold_id)
    if hold is None or hold.company_id != context.company.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal hold not found.")
    if hold.status != LegalHoldStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "legal_hold_not_draft",
                "detail": f"Only a draft hold can be activated; this one is {hold.status}.",
            },
        )
    _require_distinct_approver(
        requester_membership_id=context.membership.id,
        approver_membership_id=approver_membership_id,
    )

    # The creator columns are immutable by trigger: `created_by_membership_id`,
    # its company, and the creator label are fixed when the hold is DRAFTED.
    # That is the schema encoding dual approval end to end - the requester is
    # recorded before anyone can approve, so activation cannot retroactively
    # nominate one. An earlier version of this function set them here and the
    # trigger correctly rejected it.
    if hold.created_by_membership_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "legal_hold_has_no_recorded_requester",
                "detail": (
                    "A hold cannot be activated without the membership that drafted "
                    "it, because dual approval is meaningless without a first party."
                ),
            },
        )
    _require_distinct_approver(
        requester_membership_id=hold.created_by_membership_id,
        approver_membership_id=approver_membership_id,
    )

    hold.status = LegalHoldStatus.ACTIVE
    hold.activated_at = _now()
    hold.approved_by_membership_id = approver_membership_id
    hold.approved_by_membership_company_id = context.company.id
    hold.approver_label_snapshot = approver_label
    session.flush()
    return hold


def release_legal_hold(
    session: Session,
    *,
    context: SessionContext,
    hold_id: str,
    approver_membership_id: str,
    approver_label: str,
    release_dry_run_id: str,
) -> LegalHold:
    """Release a hold under step-up, dual approval, and a fresh dry run.

    DATA-GOV-05's last clause is the one with teeth: "release never deletes
    immediately without a new dry-run and waiting/approval policy". Releasing a
    hold does not itself delete anything, but it removes the thing that was
    blocking deletion - so the operator must have seen a CURRENT manifest of
    what becomes eligible the moment the hold lifts. A manifest produced before
    the hold, or for a different scope, does not answer that question.

    The dry run is required to be this company's, to be complete, and to
    postdate the hold's activation. Without the last condition an operator could
    satisfy the control with a manifest generated before the preserved data
    even existed.
    """

    require_recent_step_up(session, context=context, purpose="legal_hold_change")
    hold = session.get(LegalHold, hold_id)
    if hold is None or hold.company_id != context.company.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal hold not found.")
    if hold.status != LegalHoldStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "legal_hold_not_active",
                "detail": f"Only an active hold can be released; this one is {hold.status}.",
            },
        )
    _require_distinct_approver(
        requester_membership_id=context.membership.id,
        approver_membership_id=approver_membership_id,
    )

    dry_run = session.get(TenantDataOperation, release_dry_run_id)
    if (
        dry_run is None
        or dry_run.company_id != context.company.id
        or dry_run.status != "dry_run_complete"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "legal_hold_release_requires_dry_run",
                "detail": (
                    "Releasing a hold requires a completed dry run for this company "
                    "showing what becomes eligible once the hold lifts."
                ),
            },
        )
    activated_at = _as_utc(hold.activated_at)
    dry_run_completed_at = _as_utc(dry_run.dry_run_completed_at)
    if activated_at is not None and dry_run_completed_at is not None:
        if dry_run_completed_at < activated_at:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "legal_hold_release_dry_run_stale",
                    "detail": (
                        "The dry run predates the hold, so it cannot describe what "
                        "the hold is preserving. Run a new one."
                    ),
                },
            )

    hold.status = LegalHoldStatus.RELEASED
    hold.released_at = _now()
    hold.approved_by_membership_id = approver_membership_id
    hold.approved_by_membership_company_id = context.company.id
    hold.approver_label_snapshot = approver_label
    session.flush()
    return hold


def purge_dependency_plan(data_class_ids: Sequence[str]) -> dict[str, Any]:
    """Order a purge so a child is removed before the parent it references.

    DATA-GOV-08 requires a purge to carry a dependency plan. The order is
    DERIVED from the live foreign-key graph rather than maintained by hand,
    because a hand-written order is correct exactly until someone adds a
    relationship and does not remember this list. SQLAlchemy already sorts
    tables parents-first for creation; deletion is that order reversed.

    ``unsatisfied_dependencies`` is the half that matters more. If a request
    purges ``legal_holds`` but not ``legal_hold_items``, the delete either fails
    on the constraint or, worse, succeeds against a database configured to
    cascade and silently removes evidence the request never named. Reporting
    the referencing table by name lets an operator widen the scope
    deliberately instead of discovering it mid-execution.
    """

    from sqlalchemy.schema import sort_tables_and_constraints

    from caseops_api.db.models import Base

    requested = {str(item) for item in data_class_ids}
    tables = {table.name: table for table in Base.metadata.tables.values()}

    # `metadata.sorted_tables` warns about unresolvable foreign-key cycles and
    # then SILENTLY DROPS those edges from its ordering - "Foreign key
    # constraints involving these tables will not be considered". An order that
    # quietly ignores some foreign keys is exactly the failure this plan exists
    # to prevent, so the cycle is surfaced instead of swallowed.
    # `sort_tables_and_constraints` reports the broken edges: it yields a
    # (None, constraints) entry for the constraints it had to set aside.
    sorted_pairs = sort_tables_and_constraints(list(Base.metadata.tables.values()))
    ordered_tables = [table for table, _ in sorted_pairs if table is not None]
    cycle_broken: list[str] = []
    for table, constraints in sorted_pairs:
        if table is not None:
            continue
        for constraint in constraints:
            parent = getattr(constraint.table, "name", None)
            if parent and parent not in cycle_broken:
                cycle_broken.append(parent)

    # Creation order is parents-first, so deletion order is its reverse.
    deletion_order = [
        table.name for table in reversed(ordered_tables) if table.name in requested
    ]
    unresolved_cycles = sorted(name for name in cycle_broken if name in requested)

    # A requested class that is not a live table cannot be planned for, and
    # dropping it silently is the reassuring zero this plan exists to prevent:
    # the caller asked for it, no error was raised, and it simply is not in the
    # deletion order. Name them instead.
    unplanned_class_ids = sorted(name for name in requested if name not in tables)

    unsatisfied: list[dict[str, str]] = []
    for name in sorted(requested):
        table = tables.get(name)
        if table is None:
            continue
        for other in Base.metadata.tables.values():
            if other.name in requested:
                continue
            for foreign_key in other.foreign_keys:
                if foreign_key.column.table.name != name:
                    continue
                entry = {
                    "table": other.name,
                    "references": name,
                    "detail": (
                        f"{other.name} references {name} but is not in scope; purging "
                        f"{name} would orphan or block those rows."
                    ),
                }
                if entry not in unsatisfied:
                    unsatisfied.append(entry)

    return {
        "schema_version": 2,
        "deletion_order": deletion_order,
        "unsatisfied_dependencies": unsatisfied,
        # Empty is the normal case. A non-empty list means the ordering above
        # could not account for every foreign key touching the requested scope,
        # so it must not be executed as though it were complete.
        "unresolved_cycles": unresolved_cycles,
        # Requested classes with no live table. Reported rather than dropped,
        # because a plan that quietly covers less than it was asked to cover
        # still says order_is_complete.
        "unplanned_class_ids": unplanned_class_ids,
        "order_is_complete": not unresolved_cycles and not unplanned_class_ids,
    }


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

    context = _lock_dry_run_actor(session, context=context)
    # Before any per-item work: if the projection cannot be trusted, no answer
    # about any class is worth giving, and a partial manifest is worse than none.
    require_current_projection(session)

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
        # Existence was the whole check. A candidate is something one person
        # typed and nobody approved, and citing one recorded the manifest as
        # though a policy authorized it - a purge built from that manifest would
        # trace its authority to a draft. Only an ACTIVE version authorizes
        # anything; 'approved' is consent to activate, not activation.
        if policy.status != DataRetentionPolicyVersionStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "retention_policy_version_not_active",
                    "detail": (
                        "Only an active retention policy version authorizes a data "
                        f"operation; this one is {policy.status}."
                    ),
                    "status": policy.status,
                },
            )

    # DATA-GOV-06 requires point-in-time scope. Without it two dry runs of the
    # same request are not comparable, and an operator cannot say what the
    # manifest was true OF. It is part of the hashed scope so a re-run at a
    # different instant is a different manifest rather than a silent overwrite.
    as_of = payload.as_of or _now()
    request_scope = {
        "schema_version": 2,
        "operation_type": payload.operation_type,
        "execution_mode": "dry_run",
        "as_of": as_of.isoformat(),
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
        "schema_version": 2,
        "operation_type": payload.operation_type,
        "execution_mode": "dry_run",
        "execution_authorization": "absent",
        "as_of": as_of.isoformat(),
        "request_scope_hash": request_scope_hash,
        "active_hold_ids": active_hold_ids,
        # Only a tenant export leaves the platform, so only it carries the
        # exclusion record. Attaching the list to a purge or restore manifest
        # would imply a redistribution boundary that operation does not have.
        "exclusions": (
            export_exclusions() if payload.operation_type == "tenant_export" else []
        ),
        # Only an offboarding revokes a tenant's access surface.
        "offboarding_plan": (
            [
                {
                    "category": category.category,
                    "disposition": category.disposition,
                    "record_count": category.record_count,
                    "detail": category.detail,
                }
                for category in build_offboarding_plan(session, company_id=context.company.id)
            ]
            if payload.operation_type == "tenant_offboarding"
            else []
        ),
        # Only a purge removes rows, so only a purge carries a deletion order.
        "dependency_plan": (
            purge_dependency_plan([item["data_class_id"] for item in item_scope])
            if payload.operation_type == "retention_purge"
            else None
        ),
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
        rejection_reason=None,
        request_scope_hash=request_scope_hash,
        manifest_hash=manifest_hash,
        request_evidence_ref=payload.request_evidence_ref,
        completed_at=now,
        as_of=as_of,
        offboarding_plan=[
            TenantDataOperationOffboardingCategory.model_validate(entry)
            for entry in manifest["offboarding_plan"]
        ],
        dependency_plan=(
            TenantDataOperationDependencyPlan.model_validate(manifest["dependency_plan"])
            if manifest["dependency_plan"] is not None
            else None
        ),
        exclusions=[
            TenantDataOperationExclusion(**entry) for entry in manifest["exclusions"]
        ],
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


def get_dry_run_manifest(
    session: Session,
    *,
    context: SessionContext,
    operation_id: str,
) -> TenantDataOperationDryRunRecord:
    """Return one tenant-owned non-executable manifest for review."""

    operation = session.get(TenantDataOperation, operation_id)
    if (
        operation is None
        or operation.company_id != context.company.id
        or operation.execution_mode != "dry_run"
        or operation.status != "dry_run_complete"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dry run not found.")
    items = list(
        session.scalars(
            select(TenantDataOperationItem)
            .where(TenantDataOperationItem.operation_id == operation.id)
            .order_by(TenantDataOperationItem.id)
        ).all()
    )
    manifest = operation.manifest_json if isinstance(operation.manifest_json, dict) else {}
    completed_at = operation.dry_run_completed_at
    if completed_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dry-run evidence is incomplete.",
        )
    return TenantDataOperationDryRunRecord(
        id=operation.id,
        operation_type=operation.operation_type,
        execution_mode="dry_run",
        status="dry_run_complete",
        approval_status=operation.approval_status,
        rejection_reason=operation.rejection_reason,
        request_scope_hash=operation.request_scope_hash,
        manifest_hash=operation.manifest_hash,
        request_evidence_ref=operation.request_evidence_ref,
        completed_at=completed_at,
        as_of=datetime.fromisoformat(str(manifest["as_of"])),
        offboarding_plan=[
            TenantDataOperationOffboardingCategory.model_validate(entry)
            for entry in manifest.get("offboarding_plan", [])
        ],
        dependency_plan=(
            TenantDataOperationDependencyPlan.model_validate(manifest["dependency_plan"])
            if manifest.get("dependency_plan") is not None
            else None
        ),
        exclusions=[
            TenantDataOperationExclusion.model_validate(entry)
            for entry in manifest.get("exclusions", [])
        ],
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
            for row in items
        ],
    )


def list_dry_run_manifests(
    session: Session,
    *,
    context: SessionContext,
    limit: int,
) -> TenantDataOperationDryRunListResponse:
    """Discover a bounded page of completed dry runs in the caller's tenant.

    This is review-only discovery.  It never exposes items or manifest
    contents, starts no work, and cannot make a dry run executable.  The
    exact-ID read endpoint remains the only detailed review surface.
    """

    operations = list(
        session.scalars(
            select(TenantDataOperation)
            .where(
                TenantDataOperation.company_id == context.company.id,
                TenantDataOperation.execution_mode == "dry_run",
                TenantDataOperation.status == "dry_run_complete",
            )
            .order_by(
                TenantDataOperation.dry_run_completed_at.desc(),
                TenantDataOperation.id.desc(),
            )
            .limit(limit)
        ).all()
    )
    summaries: list[TenantDataOperationDryRunSummary] = []
    for operation in operations:
        completed_at = operation.dry_run_completed_at
        manifest = operation.manifest_json if isinstance(operation.manifest_json, dict) else {}
        as_of = manifest.get("as_of")
        if completed_at is None or not isinstance(as_of, str):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dry-run evidence is incomplete.",
            )
        summaries.append(
            TenantDataOperationDryRunSummary(
                id=operation.id,
                operation_type=operation.operation_type,
                execution_mode="dry_run",
                status="dry_run_complete",
                approval_status=operation.approval_status,
                rejection_reason=operation.rejection_reason,
                request_scope_hash=operation.request_scope_hash,
                manifest_hash=operation.manifest_hash,
                request_evidence_ref=operation.request_evidence_ref,
                completed_at=completed_at,
                as_of=datetime.fromisoformat(as_of),
            )
        )
    return TenantDataOperationDryRunListResponse(operations=summaries)


def get_tenant_integrity_report(
    session: Session,
    *,
    context: SessionContext,
) -> TenantDataGovernanceIntegrityReport:
    """Return content-minimized DATA-GOV-17 visibility for one tenant.

    The scanner is intentionally candid when a control cannot be evaluated:
    ``unavailable`` stays distinct from ``ok``. This reads current metadata
    only; it does not schedule a scan, alter any hold, or authorize a data
    operation.
    """

    report = run_integrity_scan(session, company_id=context.company.id)
    return TenantDataGovernanceIntegrityReport(
        checks=[
            TenantDataGovernanceIntegrityCheck(
                check_id=check.check_id,
                status=check.status,
                summary=check.summary,
                findings=list(check.findings),
                blocked_by=check.blocked_by,
            )
            for check in report.checks
        ],
        ok_count=report.ok_count,
        finding_count=report.finding_count,
        unavailable_count=report.unavailable_count,
        is_complete=report.is_complete,
    )


def reject_data_operation_execution(*, operation_id: str) -> NoReturn:
    """Ensure future callers cannot mistake a dry-run record for authority."""

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            # ``type`` is reserved by the RFC 7807 envelope. Keep the
            # operation discriminator as an extension member so API clients
            # receive it instead of losing it during error normalization.
            "code": "data_operation_execution_unavailable",
            "detail": (
                "IPLF-028A stores dry-run evidence only; execute, purge, export, "
                "offboarding, restore, and provider actions are not implemented."
            ),
            "operation_id": operation_id,
        },
    )


__all__ = [
    "create_dry_run_manifest",
    "get_dry_run_manifest",
    "get_tenant_integrity_report",
    "list_dry_run_manifests",
    "reject_data_operation_execution",
]
