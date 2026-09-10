"""Authenticated commands over the existing LegalHold preservation owner.

Release proposals are immutable evidence, never a second preservation state.
No command invokes a data executor or grants deletion authority.
"""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import NoReturn

from fastapi import HTTPException
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    LegalHold,
    LegalHoldItem,
    LegalHoldReleaseRequest,
    TenantDataOperation,
    TenantDataOperationItem,
)
from caseops_api.governance.data_class_projection import (
    require_admissible_data_class,
    require_current_projection,
)
from caseops_api.schemas.legal_holds import (
    HoldDraftRequest,
    HoldListResponse,
    HoldRecord,
    HoldReleaseListResponse,
    HoldReleaseProposal,
    HoldReleaseRequest,
)
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.security import require_step_up_always
from caseops_api.services.session_context import SessionContext


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _reject(code: str, detail: str, status: int = 409) -> NoReturn:
    raise HTTPException(status_code=status, detail={"type": code, "detail": detail})


def _actor(
    session: Session,
    context: SessionContext,
    *,
    mutate: bool,
    participants: tuple[str, ...] = (),
    capability: str = "legal_holds:manage",
) -> tuple[SessionContext, dict[str, CompanyMembership]]:
    # This tenant fence is also required by the disposition adapter before it
    # reads holds. Membership/User then hold locks cannot invert that order.
    company = session.scalar(
        select(Company)
        .where(Company.id == context.company.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if company is None or not company.is_active:
        _reject("legal_hold_access_required", "An active workspace is required.", 403)
    members = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=[context.membership.id, *participants],
    )
    member = members.get(context.membership.id)
    if member is None or member.user_id != context.user.id:
        _reject("legal_hold_access_required", "Preservation administration is required.", 403)
    require_locked_membership_capability(session, member, capability)
    fresh = SessionContext(company=company, membership=member, user=member.user)
    if mutate:
        require_step_up_always(session, context=fresh, purpose="legal_hold_change")
    # Retain every fenced participant: SQLAlchemy's identity map uses weak
    # references, so reloading a discarded participant loses its fence marker.
    return fresh, members


def _load(session: Session, context: SessionContext, hold_id: str) -> LegalHold:
    hold = session.scalar(
        select(LegalHold)
        .where(
            LegalHold.company_id == context.company.id,
            LegalHold.id == hold_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if hold is None:
        _reject("legal_hold_not_found", "Legal hold not found.", 404)
    return hold


def _version(hold: LegalHold, expected: datetime) -> None:
    if _utc(hold.updated_at) != _utc(expected):
        _reject("legal_hold_stale", "The hold changed. Reload before issuing a new command.")


def _items(session: Session, hold: LegalHold) -> list[LegalHoldItem]:
    rows = list(
        session.scalars(
            select(LegalHoldItem)
            .where(
                LegalHoldItem.company_id == hold.company_id,
                LegalHoldItem.legal_hold_id == hold.id,
            )
            .order_by(LegalHoldItem.data_class_id, LegalHoldItem.id)
            .limit(101)
        )
    )
    if len(rows) > 100:
        _reject("legal_hold_scope_limit", "This preservation scope exceeds the command limit.")
    if any(row.target_type != "data_class" for row in rows):
        _reject(
            "legal_hold_scope_unsupported",
            "This retained hold requires its original scoped workflow.",
        )
    return rows


def _record(hold: LegalHold, items: list[LegalHoldItem]) -> HoldRecord:
    return HoldRecord(
        id=hold.id,
        title=hold.title,
        authority_reference=hold.authority_reference,
        status=hold.status,
        scope="data_classes" if items else "company",
        data_class_ids=[row.data_class_id for row in items],
        created_by_membership_id=hold.created_by_membership_id,
        approved_by_membership_id=hold.approved_by_membership_id,
        updated_at=hold.updated_at,
        activated_at=hold.activated_at,
        released_at=hold.released_at,
    )


def list_holds(
    session: Session, *, context: SessionContext, limit: int = 25, before_id: str | None = None
) -> HoldListResponse:
    context, _members = _actor(session, context, mutate=False)
    if not 1 <= limit <= 100:
        _reject("legal_hold_page_invalid", "Choose a page size from 1 to 100.", 422)
    query = select(LegalHold).where(LegalHold.company_id == context.company.id)
    if before_id is not None:
        anchor = _load(session, context, before_id)
        query = query.where(
            tuple_(LegalHold.created_at, LegalHold.id) < (anchor.created_at, anchor.id)
        )
    holds = list(
        session.scalars(
            query.order_by(LegalHold.created_at.desc(), LegalHold.id.desc()).limit(limit + 1)
        )
    )
    # One bounded item read, not one query per hold.
    items = list(
        session.scalars(
            select(LegalHoldItem)
            .where(
                LegalHoldItem.company_id == context.company.id,
                LegalHoldItem.legal_hold_id.in_([hold.id for hold in holds[:limit]]),
            )
            .order_by(LegalHoldItem.legal_hold_id, LegalHoldItem.data_class_id)
            .limit(limit * 100 + 1)
        )
    )
    if len(items) > limit * 100 or any(row.target_type != "data_class" for row in items):
        _reject("legal_hold_scope_unsupported", "Retained scopes require their original workflow.")
    grouped: dict[str, list[LegalHoldItem]] = {}
    for item in items:
        grouped.setdefault(item.legal_hold_id, []).append(item)
    if any(len(rows) > 100 for rows in grouped.values()):
        _reject("legal_hold_scope_limit", "This preservation scope exceeds the command limit.")
    return HoldListResponse(
        holds=[_record(hold, grouped.get(hold.id, [])) for hold in holds[:limit]],
        has_more=len(holds) > limit,
        next_before_id=holds[limit - 1].id if len(holds) > limit else None,
    )


def create_hold(
    session: Session, *, context: SessionContext, payload: HoldDraftRequest
) -> HoldRecord:
    context, _members = _actor(session, context, mutate=True, capability="audit:export")
    require_current_projection(session)
    classes = sorted(set(payload.data_class_ids))
    if (payload.scope == "company" and classes) or (
        payload.scope == "data_classes" and not classes
    ):
        _reject(
            "legal_hold_scope_invalid",
            "Choose whole-workspace preservation or registered data classes.",
            422,
        )
    for class_id in classes:
        require_admissible_data_class(class_id)
    existing = session.scalar(
        select(LegalHold).where(
            LegalHold.company_id == context.company.id,
            LegalHold.key == payload.idempotency_key,
        )
    )
    if existing:
        items = _items(session, existing)
        if (
            existing.status != "draft"
            or existing.created_by_membership_id != context.membership.id
            or existing.title != payload.title
            or existing.authority_reference != payload.authority_reference
            or sorted(row.data_class_id for row in items) != classes
        ):
            _reject(
                "legal_hold_replay_conflict",
                "The creation key belongs to another command or a non-draft hold.",
            )
        return _record(existing, items)
    hold = LegalHold(
        company_id=context.company.id,
        key=payload.idempotency_key,
        title=payload.title,
        authority_reference=payload.authority_reference,
        status="draft",
        created_by_membership_id=context.membership.id,
        created_by_membership_company_id=context.company.id,
        creator_label_snapshot=context.user.full_name or context.user.email,
    )
    session.add(hold)
    session.flush()
    items = [
        LegalHoldItem(
            company_id=context.company.id,
            legal_hold_id=hold.id,
            data_class_id=class_id,
            target_type="data_class",
            target_reference_hash=_digest([context.company.id, class_id]),
        )
        for class_id in classes
    ]
    session.add_all(items)
    record_from_context(
        session,
        context,
        action="legal_hold.created",
        target_type="legal_hold",
        target_id=hold.id,
        metadata={"scope": payload.scope, "class_count": len(classes)},
    )
    session.commit()
    session.refresh(hold)
    return _record(hold, items)


def activate_hold(
    session: Session, *, context: SessionContext, hold_id: str, expected_updated_at: datetime
) -> HoldRecord:
    context, _members = _actor(session, context, mutate=True)
    hold = _load(session, context, hold_id)
    _version(hold, expected_updated_at)
    if hold.status != "draft":
        _reject("legal_hold_not_draft", "Only a draft hold can be activated.")
    creator_user_id = session.scalar(
        select(CompanyMembership.user_id).where(
            CompanyMembership.id == hold.created_by_membership_id,
            CompanyMembership.company_id == context.company.id,
        )
    )
    if creator_user_id is None or creator_user_id == context.user.id:
        _reject(
            "legal_hold_approver_must_be_distinct", "A different person must approve preservation."
        )
    items = _items(session, hold)
    require_current_projection(session)
    for item in items:
        require_admissible_data_class(item.data_class_id)
    hold.status = "active"
    hold.activated_at = datetime.now(UTC)
    hold.updated_at = hold.activated_at
    hold.approved_by_membership_id = context.membership.id
    hold.approved_by_membership_company_id = context.company.id
    hold.approver_label_snapshot = context.user.full_name or context.user.email
    record_from_context(
        session, context, action="legal_hold.activated", target_type="legal_hold", target_id=hold.id
    )
    session.commit()
    session.refresh(hold)
    return _record(hold, items)


def _release_snapshot(session: Session, hold: LegalHold, dry_run_id: str) -> dict:
    require_current_projection(session)
    operation = session.scalar(
        select(TenantDataOperation).where(
            TenantDataOperation.company_id == hold.company_id,
            TenantDataOperation.id == dry_run_id,
        )
    )
    now = datetime.now(UTC)
    if (
        operation is None
        or operation.execution_mode != "dry_run"
        or operation.operation_type not in {"retention_purge", "tenant_offboarding"}
        or operation.status != "dry_run_complete"
        or operation.dry_run_completed_at is None
        or hold.activated_at is None
        or _utc(operation.dry_run_completed_at) < _utc(hold.activated_at)
        or not timedelta(0) <= now - _utc(operation.dry_run_completed_at) <= timedelta(minutes=30)
    ):
        _reject(
            "legal_hold_release_requires_dry_run",
            "Create a current preservation dry run after activation.",
        )
    scope = _items(session, hold)
    for item in scope:
        require_admissible_data_class(item.data_class_id)
    if not scope:
        # Six reviewed metadata classes cannot certify a whole-tenant release.
        _reject(
            "legal_hold_full_inventory_required",
            "Whole-workspace release requires a complete registered inventory.",
            503,
        )
    manifest_items = list(
        session.scalars(
            select(TenantDataOperationItem)
            .where(
                TenantDataOperationItem.company_id == hold.company_id,
                TenantDataOperationItem.operation_id == operation.id,
            )
            .limit(501)
        )
    )
    tenant_hash = sha256(f"caseops:tenant:{hold.company_id}".encode()).hexdigest()
    covered = {
        item.data_class_id
        for item in manifest_items
        if item.target_type == "tenant" and item.target_reference_hash == tenant_hash
    }
    if len(manifest_items) > 500 or not {item.data_class_id for item in scope}.issubset(covered):
        _reject(
            "legal_hold_release_scope_mismatch",
            "The dry run does not cover this hold's complete scope.",
        )
    active = list(
        session.execute(
            select(LegalHold.id, LegalHold.updated_at)
            .where(
                LegalHold.company_id == hold.company_id,
                LegalHold.status == "active",
            )
            .order_by(LegalHold.id)
            .limit(501)
        )
    )
    if len(active) > 500:
        _reject(
            "legal_hold_inventory_limit",
            "The active preservation inventory exceeds the command limit.",
        )
    return {
        "hold_updated_at": _utc(hold.updated_at).isoformat(),
        "manifest_hash": operation.manifest_hash,
        "scope_hash": operation.request_scope_hash,
        "data_classes": sorted(item.data_class_id for item in scope),
        "active_holds": [[row.id, _utc(row.updated_at).isoformat()] for row in active],
    }


def propose_release(
    session: Session, *, context: SessionContext, hold_id: str, payload: HoldReleaseRequest
) -> HoldReleaseProposal:
    context, _members = _actor(session, context, mutate=True, capability="audit:export")
    hold = _load(session, context, hold_id)
    _version(hold, payload.expected_updated_at)
    if hold.status != "active":
        _reject("legal_hold_not_active", "Only an active hold can receive a release request.")
    snapshot = _release_snapshot(session, hold, payload.dry_run_id)
    snapshot.update(
        {
            "hold_id": hold.id,
            "dry_run_id": payload.dry_run_id,
            "reason_reference": payload.reason_reference,
            "requester_user_id": context.user.id,
        }
    )
    request_hash = _digest(snapshot)
    existing = session.scalar(
        select(LegalHoldReleaseRequest).where(
            LegalHoldReleaseRequest.company_id == context.company.id,
            LegalHoldReleaseRequest.idempotency_key == payload.idempotency_key,
        )
    )
    now = datetime.now(UTC)
    if existing:
        if existing.request_hash != request_hash or _utc(existing.expires_at) <= now:
            _reject(
                "legal_hold_release_replay_conflict",
                "The request key belongs to a changed or expired release proposal.",
            )
        proposal = existing
    else:
        proposal = LegalHoldReleaseRequest(
            company_id=context.company.id,
            legal_hold_id=hold.id,
            dry_run_id=payload.dry_run_id,
            idempotency_key=payload.idempotency_key,
            requester_user_id=context.user.id,
            requester_membership_id=context.membership.id,
            requester_label_snapshot=context.user.full_name or context.user.email,
            reason_reference=payload.reason_reference,
            request_json=snapshot,
            request_hash=request_hash,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        session.add(proposal)
        session.flush()
        record_from_context(
            session,
            context,
            action="legal_hold.release_requested",
            target_type="legal_hold",
            target_id=hold.id,
            metadata={"proposal_id": proposal.id, "request_hash": proposal.request_hash},
        )
        session.commit()
    return HoldReleaseProposal(
        id=proposal.id,
        hold_id=hold.id,
        request_hash=proposal.request_hash,
        expires_at=proposal.expires_at,
        requester_membership_id=proposal.requester_membership_id,
        reason_reference=proposal.reason_reference,
        dry_run_id=proposal.dry_run_id,
    )


def approve_release(
    session: Session,
    *,
    context: SessionContext,
    hold_id: str,
    proposal_id: str,
    expected_updated_at: datetime,
) -> HoldRecord:
    requester_id = session.scalar(
        select(LegalHoldReleaseRequest.requester_membership_id).where(
            LegalHoldReleaseRequest.company_id == context.company.id,
            LegalHoldReleaseRequest.legal_hold_id == hold_id,
            LegalHoldReleaseRequest.id == proposal_id,
        )
    )
    context, members = _actor(
        session, context, mutate=True, participants=(requester_id,) if requester_id else ()
    )
    hold = _load(session, context, hold_id)
    _version(hold, expected_updated_at)
    if hold.status != "active":
        _reject("legal_hold_not_active", "Only an active hold can be released.")
    proposal = session.scalar(
        select(LegalHoldReleaseRequest).where(
            LegalHoldReleaseRequest.company_id == context.company.id,
            LegalHoldReleaseRequest.legal_hold_id == hold.id,
            LegalHoldReleaseRequest.id == proposal_id,
        )
    )
    if proposal is None:
        _reject("legal_hold_release_not_found", "Release proposal not found.", 404)
    requester = members.get(proposal.requester_membership_id)
    if (
        requester is None
        or requester.company_id != context.company.id
        or requester.user_id != proposal.requester_user_id
    ):
        _reject(
            "legal_hold_release_requester_changed", "The requesting identity is no longer valid."
        )
    require_locked_membership_capability(session, requester, "audit:export")
    if proposal.requester_user_id == context.user.id:
        _reject("legal_hold_approver_must_be_distinct", "A different person must approve release.")
    if (
        _utc(proposal.expires_at) <= datetime.now(UTC)
        or _digest(proposal.request_json) != proposal.request_hash
    ):
        _reject(
            "legal_hold_release_expired",
            "The proposal expired or its retained evidence is inconsistent.",
        )
    current = _release_snapshot(session, hold, proposal.dry_run_id)
    if any(proposal.request_json.get(key) != value for key, value in current.items()):
        _reject(
            "legal_hold_release_changed",
            "Preservation or dry-run evidence changed. Create a new release request.",
        )
    # Keep the original activation approver unchanged. Release identity is in
    # the immutable request and the canonical audit, not retroactively replaced.
    hold.status = "released"
    hold.released_at = datetime.now(UTC)
    hold.updated_at = hold.released_at
    hold.release_reason_redacted = proposal.reason_reference
    record_from_context(
        session,
        context,
        action="legal_hold.released",
        target_type="legal_hold",
        target_id=hold.id,
        metadata={
            "proposal_id": proposal.id,
            "request_hash": proposal.request_hash,
            "fresh_purge_dry_run_required": True,
        },
    )
    items = _items(session, hold)
    session.commit()
    session.refresh(hold)
    return _record(hold, items)


def list_release_proposals(
    session: Session,
    *,
    context: SessionContext,
    hold_id: str,
    limit: int = 25,
    before_id: str | None = None,
) -> HoldReleaseListResponse:
    context, _members = _actor(session, context, mutate=False)
    hold = _load(session, context, hold_id)
    if not 1 <= limit <= 100:
        _reject("legal_hold_page_invalid", "Choose a page size from 1 to 100.", 422)
    query = select(LegalHoldReleaseRequest).where(
        LegalHoldReleaseRequest.company_id == context.company.id,
        LegalHoldReleaseRequest.legal_hold_id == hold.id,
    )
    if before_id is not None:
        anchor = session.scalar(query.where(LegalHoldReleaseRequest.id == before_id))
        if anchor is None:
            _reject("legal_hold_not_found", "Legal hold release request not found.", 404)
        query = query.where(
            tuple_(LegalHoldReleaseRequest.created_at, LegalHoldReleaseRequest.id)
            < (anchor.created_at, anchor.id)
        )
    if hold.status != "active":
        return HoldReleaseListResponse(proposals=[], has_more=False)
    proposals = list(
        session.scalars(
            query.where(LegalHoldReleaseRequest.expires_at > datetime.now(UTC))
            .order_by(LegalHoldReleaseRequest.created_at.desc(), LegalHoldReleaseRequest.id.desc())
            .limit(limit + 1)
        )
    )
    return HoldReleaseListResponse(
        proposals=[
            HoldReleaseProposal(
                id=row.id,
                hold_id=hold.id,
                request_hash=row.request_hash,
                expires_at=row.expires_at,
                requester_membership_id=row.requester_membership_id,
                reason_reference=row.reason_reference,
                dry_run_id=row.dry_run_id,
            )
            for row in proposals[:limit]
        ],
        has_more=len(proposals) > limit,
        next_before_id=proposals[limit - 1].id if len(proposals) > limit else None,
    )
