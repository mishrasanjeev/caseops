from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, false, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    Communication,
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeIpLink,
    CompanyNoticeMatterLink,
    DriveFileCandidate,
    IpControlReviewExceptionDecision,
    IpControlReviewSampleEvidence,
    IpControlReviewSignature,
    IpCostItem,
    IpDeadline,
    IpDeadlineCoverage,
    IpDeadlineIncident,
    IpDocketControlReview,
    IpDocketQueue,
    IpDocketRecord,
    IpEvidenceCandidate,
    IpRelatedRightObligation,
    IpTitleInterest,
    IpTrademarkParticularVersion,
    Matter,
    MatterAccessGrant,
    MatterAccessLevel,
    MatterAttachment,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterInvoice,
    MatterInvoiceLineItem,
    MatterTimeEntry,
    Team,
    TeamMembership,
)
from caseops_api.schemas.ip_operations import (
    IpAssignedCoverageListResponse,
    IpAssignedCoverageRecord,
    IpControlExceptionRecord,
    IpControlReviewCreateRequest,
    IpControlReviewDelta,
    IpControlReviewExceptionDecisionRecord,
    IpControlReviewExceptionDecisionRequest,
    IpControlReviewExportRequest,
    IpControlReviewListResponse,
    IpControlReviewPolicy,
    IpControlReviewRecord,
    IpControlReviewSampleRecord,
    IpControlReviewSampleRequest,
    IpControlReviewSignatureRecord,
    IpControlReviewSignOffRequest,
    IpControlReviewSnapshot,
    IpCostItemCreateRequest,
    IpCostItemRecord,
    IpCostReconciliationReport,
    IpCostReconciliationRow,
    IpCoverageAcknowledgeOutcome,
    IpCoverageBulkAcknowledgeRequest,
    IpCoverageBulkAcknowledgeResponse,
    IpCoverageBulkReassignRequest,
    IpCoverageBulkReassignResponse,
    IpCoverageReassignPreviewRequest,
    IpCoverageReassignPreviewResponse,
    IpCoverageReassignProposeRequest,
    IpCoverageReplacementDecisionRequest,
    IpCoverageTransferAwaiting,
    IpCoverageTransfersAwaitingResponse,
    IpDailyDocketEscalation,
    IpDailyDocketQueue,
    IpDailyDocketResponse,
    IpDeadlineCoverageCreateRequest,
    IpDeadlineCoverageReassignRequest,
    IpDeadlineCoverageRecord,
    IpDeadlineIncidentCreateRequest,
    IpDeadlineIncidentRecord,
    IpDeadlineIncidentVerifyRequest,
    IpDocketControlReport,
    IpDocketCreateRequest,
    IpDocketListResponse,
    IpDocketQueueListResponse,
    IpDocketQueueRecord,
    IpDocketQueueSaveRequest,
    IpDocketRecordResponse,
    IpDocketVersionCreateRequest,
    IpEvidenceCandidateRecord,
    IpEvidenceCandidateReviewRequest,
    IpEvidenceDiscoveryResponse,
    IpNoticeLinkCreateRequest,
    IpNoticeLinkRecord,
    IpRelatedRightObligationCompleteRequest,
    IpRelatedRightObligationCreateRequest,
    IpRelatedRightObligationRecord,
    IpTitleInterestCreateRequest,
    IpTitleInterestRecord,
    TrademarkParticularPayload,
    TrademarkParticularVersionRecord,
)
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.ip_coverage_projection import (
    cutover_ip_coverage_projection,
)
from caseops_api.services.ip_deadlines import (
    assert_distinct_deadline_coverage,
    assert_distinct_deadline_escalation,
)
from caseops_api.services.matter_access import (
    _operational_matter_role_snapshot,
    assert_access,
    assert_ip_docket_access,
    can_stably_access_ip_docket,
    can_stably_access_matter,
    seed_restricted_ip_creator_access,
    visible_ip_dockets_filter,
)
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
    matter_is_operational,
)
from caseops_api.services.session_context import SessionContext


def _now() -> datetime:
    return datetime.now(UTC)


CONTROL_REVIEW_QUERY_VERSION = "ip-docket-control-v1"
CONTROL_REVIEW_SNAPSHOT_SCHEMA_VERSION = 2
CONTROL_REVIEW_RESTRICTED_COUNT_POLICY = "omit_without_count"
CONTROL_REVIEW_POLICY_VERSION = "daily-docket-review-v1"

# Lifecycle-neutralized rows remain as immutable history after a controlled
# reopen. No operational read or write may treat them as live work again.
_TERMINAL_COVERAGE_STATUSES = ("inactive_lifecycle", "completed")
_TERMINAL_DOCKET_STATUSES = ("archived", "abandoned", "transferred", "retired", "closed")


def _deadline_is_operational(deadline: MatterDeadline | None) -> bool:
    return bool(
        deadline is not None
        and deadline.status in (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
        and deadline.neutralized_at is None
        and not deadline.cancelled_by_matter_disposal
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _readiness_errors(payload: TrademarkParticularPayload) -> list[str]:
    errors: list[str] = []
    if not (payload.representation.get("text") or payload.representation.get("evidence_reference")):
        errors.append("A word/device representation or immutable evidence reference is required.")
    if not any(party.role == "applicant" for party in payload.parties):
        errors.append("At least one applicant party is required.")
    for row in payload.filing_manifest:
        if row.required and not row.evidence_reference:
            errors.append(f"Required filing item {row.label!r} has no evidence reference.")
    if payload.use_priority and payload.use_priority.get("claim_priority"):
        if not payload.use_priority.get("priority_document_reference"):
            errors.append("A priority claim requires a priority-document reference.")
    return errors


def _matter_for_docket(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
) -> Matter | None:
    if matter_id is None:
        return None
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    # Docket creation must discover every inherited responsibility before it
    # acquires the participant fence.  Locking the Matter here would invert
    # Membership/User -> Matter and would also turn the later role snapshot
    # comparison into a same-snapshot no-op after a concurrent child writer.
    # The caller takes and revalidates the authoritative Matter lock after the
    # sorted participant fence.
    return assert_operational_matter(session, matter=matter, lock_for_write=False)


def _docket_or_404(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    for_update: bool = False,
    required_capability: str = "ip:write",
) -> IpDocketRecord:
    if for_update:
        # Every docket mutation eventually persists an actor-backed audit or
        # evidence row.  Fence that FK participant before Matter/docket locks;
        # otherwise offboarding can hold Membership while waiting on the
        # docket and this writer can hold the docket while PostgreSQL waits for
        # a Membership KEY SHARE lock during flush.
        context = _lock_ip_writer_context(
            session,
            context=context,
            required_capability=required_capability,
        )
    statement = select(IpDocketRecord).where(
        IpDocketRecord.id == docket_id,
        IpDocketRecord.company_id == context.company.id,
    )
    discovered_parent = (
        session.execute(
            select(IpDocketRecord.id, IpDocketRecord.matter_id).where(
                IpDocketRecord.id == docket_id,
                IpDocketRecord.company_id == context.company.id,
            )
        ).one_or_none()
        if for_update
        else None
    )
    docket = session.scalar(statement) if not for_update else None
    locked_matter: Matter | None = None
    if discovered_parent is not None and discovered_parent.matter_id:
        # Matter is the lifecycle parent. Match Matter disposal and the IP
        # lifecycle service's lock order before locking the docket child.
        locked_matter = session.scalar(
            select(Matter)
            .where(
                Matter.id == discovered_parent.matter_id,
                Matter.company_id == context.company.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_matter is None:
            raise HTTPException(status_code=404, detail="IP docket record not found.")
    if discovered_parent is not None:
        docket = session.scalar(
            statement.with_for_update().execution_options(populate_existing=True)
        )
    if docket is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    if for_update:
        assert discovered_parent is not None
        if docket.matter_id != discovered_parent.matter_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The IP docket parent changed; retry the operation.",
            )
    if docket.archived_by_matter_disposal or not docket.is_active:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    assert_ip_docket_access(session, context=context, docket=docket)
    if docket.matter_id:
        matter = locked_matter or session.get(Matter, docket.matter_id)
        if matter is None:
            raise HTTPException(status_code=404, detail="IP docket record not found.")
        try:
            assert_operational_matter(session, matter=matter)
        except MatterNotOperationalError as exc:
            raise HTTPException(status_code=404, detail="IP docket record not found.") from exc
    return docket


def _lock_ip_writer_context(
    session: Session,
    *,
    context: SessionContext,
    required_capability: str,
) -> SessionContext:
    """Fence an IP mutation actor and rebuild context from locked rows."""

    actor_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={context.membership.id},
    )
    locked_actor = actor_memberships.get(context.membership.id)
    if locked_actor is None or not locked_actor.is_active or not locked_actor.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active company membership is required for this IP mutation.",
        )
    require_locked_membership_capability(
        session,
        locked_actor,
        required_capability,
    )
    return SessionContext(
        company=context.company,
        user=locked_actor.user,
        membership=locked_actor,
    )


def _lock_ip_dockets_in_stable_order(
    session: Session,
    *,
    context: SessionContext,
    docket_ids: set[str],
    required_capability: str,
) -> dict[str, IpDocketRecord]:
    """Discover, lock, and exactly revalidate a related docket set.

    Cross-docket writers cannot call ``_docket_or_404`` once per record: two
    inverse relationships could otherwise acquire their Matter and docket
    locks in opposite orders. The actor must already be fenced; then every
    Matter parent is locked by id before every docket child is locked by id.
    """

    require_locked_membership_capability(
        session,
        context.membership,
        required_capability,
    )
    requested_ids = sorted(docket_ids)
    discovered_rows = list(
        session.execute(
            select(IpDocketRecord.id, IpDocketRecord.matter_id)
            .where(
                IpDocketRecord.company_id == context.company.id,
                IpDocketRecord.id.in_(requested_ids),
            )
            .order_by(IpDocketRecord.id)
        ).all()
    )
    discovered_parents = {row.id: row.matter_id for row in discovered_rows}
    if set(discovered_parents) != set(requested_ids):
        raise HTTPException(status_code=404, detail="IP docket record not found.")

    matter_ids = sorted({matter_id for matter_id in discovered_parents.values() if matter_id})
    locked_matters = (
        list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == context.company.id,
                    Matter.id.in_(matter_ids),
                )
                .order_by(Matter.id)
                .with_for_update(of=Matter)
                .execution_options(populate_existing=True)
            ).all()
        )
        if matter_ids
        else []
    )
    matters_by_id = {matter.id: matter for matter in locked_matters}
    if set(matters_by_id) != set(matter_ids):
        raise HTTPException(status_code=404, detail="IP docket record not found.")

    locked_dockets = list(
        session.scalars(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.company_id == context.company.id,
                IpDocketRecord.id.in_(requested_ids),
            )
            .order_by(IpDocketRecord.id)
            .with_for_update(of=IpDocketRecord)
            .execution_options(populate_existing=True)
        ).all()
    )
    dockets_by_id = {docket.id: docket for docket in locked_dockets}
    if set(dockets_by_id) != set(requested_ids):
        raise HTTPException(status_code=404, detail="IP docket record not found.")

    for docket_id in requested_ids:
        docket = dockets_by_id[docket_id]
        if docket.matter_id != discovered_parents[docket_id]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The IP docket parent changed; retry the operation.",
            )
        if docket.archived_by_matter_disposal or not docket.is_active:
            raise HTTPException(status_code=404, detail="IP docket record not found.")
        assert_ip_docket_access(session, context=context, docket=docket)
        if docket.matter_id:
            matter = matters_by_id[docket.matter_id]
            try:
                assert_operational_matter(session, matter=matter)
            except MatterNotOperationalError as exc:
                raise HTTPException(
                    status_code=404,
                    detail="IP docket record not found.",
                ) from exc
    return dockets_by_id


def _current_particulars(session: Session, docket: IpDocketRecord) -> IpTrademarkParticularVersion:
    row = session.scalar(
        select(IpTrademarkParticularVersion).where(
            IpTrademarkParticularVersion.docket_id == docket.id,
            IpTrademarkParticularVersion.company_id == docket.company_id,
            IpTrademarkParticularVersion.version == docket.current_version,
        )
    )
    if row is None:
        raise RuntimeError("IP docket current version is missing.")
    return row


def _serialize_docket(
    session: Session,
    docket: IpDocketRecord,
    *,
    context: SessionContext,
    may_read_rates: bool | None = None,
) -> IpDocketRecordResponse:
    """Serialize a docket for one specific reader.

    ``context`` is a required keyword rather than an optional one because the
    cost rows below are permissioned (UJ-52-EXC-05). An optional parameter
    would let a future call site omit it and silently pick whichever default
    was chosen here; a required one makes the omission a TypeError.

    ``may_read_rates`` is a cache, not a second source of truth: the capability
    depends only on the reader, so a caller serializing many dockets for one
    reader resolves it once instead of per docket. Leaving it ``None`` resolves
    it properly rather than assuming either answer.
    """

    particulars = _current_particulars(session, docket)
    notice_links = list(
        session.scalars(
            select(CompanyNoticeIpLink)
            .where(CompanyNoticeIpLink.docket_id == docket.id)
            .order_by(CompanyNoticeIpLink.created_at)
        ).all()
    )
    evidence_candidates = list(
        session.scalars(
            select(IpEvidenceCandidate)
            .where(IpEvidenceCandidate.docket_id == docket.id)
            .order_by(IpEvidenceCandidate.created_at.desc())
        ).all()
    )
    coverages = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(IpDeadlineCoverage.docket_id == docket.id)
            .order_by(IpDeadlineCoverage.created_at)
        ).all()
    )
    incidents = list(
        session.scalars(
            select(IpDeadlineIncident)
            .where(IpDeadlineIncident.docket_id == docket.id)
            .order_by(IpDeadlineIncident.created_at.desc())
        ).all()
    )
    interests = list(
        session.scalars(
            select(IpTitleInterest)
            .where(IpTitleInterest.docket_id == docket.id)
            .order_by(IpTitleInterest.effective_from, IpTitleInterest.created_at)
        ).all()
    )
    obligations = list(
        session.scalars(
            select(IpRelatedRightObligation)
            .where(IpRelatedRightObligation.docket_id == docket.id)
            .order_by(
                IpRelatedRightObligation.due_on,
                IpRelatedRightObligation.created_at,
            )
        ).all()
    )
    costs = list(
        session.scalars(
            select(IpCostItem)
            .where(IpCostItem.docket_id == docket.id)
            .order_by(IpCostItem.created_at)
        ).all()
    )
    if may_read_rates is None:
        may_read_rates = _may_read_confidential_rates(session, context=context)
    return IpDocketRecordResponse(
        id=docket.id,
        company_id=docket.company_id,
        matter_id=docket.matter_id,
        record_type=docket.record_type,
        title=docket.title,
        primary_identifier=docket.primary_identifier,
        status=docket.status,
        is_active=docket.is_active,
        lifecycle_version=docket.lifecycle_version,
        lifecycle_effective_at=docket.lifecycle_effective_at,
        lifecycle_reason=docket.lifecycle_reason,
        lifecycle_outcome=docket.lifecycle_outcome,
        lifecycle_source=docket.lifecycle_source,
        lifecycle_evidence_ref=docket.lifecycle_evidence_ref,
        successor_docket_id=docket.successor_docket_id,
        restricted=docket.restricted,
        access_policy_version=docket.access_policy_version,
        current_version=docket.current_version,
        current_particulars=TrademarkParticularVersionRecord.model_validate(particulars),
        notice_links=[IpNoticeLinkRecord.model_validate(row) for row in notice_links],
        evidence_candidates=[
            IpEvidenceCandidateRecord.model_validate(row) for row in evidence_candidates
        ],
        deadline_coverages=[IpDeadlineCoverageRecord.model_validate(row) for row in coverages],
        deadline_incidents=[IpDeadlineIncidentRecord.model_validate(row) for row in incidents],
        title_interests=[IpTitleInterestRecord.model_validate(row) for row in interests],
        related_right_obligations=[
            IpRelatedRightObligationRecord.model_validate(row) for row in obligations
        ],
        cost_items=[
            _serialize_cost_item(row, may_read_rates=may_read_rates) for row in costs
        ],
        created_at=docket.created_at,
        updated_at=docket.updated_at,
    )


def create_ip_docket(
    session: Session,
    *,
    context: SessionContext,
    payload: IpDocketCreateRequest,
    docket_id: str | None = None,
    source_provenance: tuple[str, str] | None = None,
) -> IpDocketRecordResponse:
    linked_matter = _matter_for_docket(
        session,
        context=context,
        matter_id=payload.matter_id,
    )
    candidate_role_snapshot = (
        _operational_matter_role_snapshot(session, matter=linked_matter)
        if linked_matter is not None
        else ()
    )
    candidate_role_ids = {
        membership_id
        for _object_type, _object_id, _relation, membership_id in candidate_role_snapshot
    }
    linked_role_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=candidate_role_ids | {context.membership.id},
    )
    locked_actor = linked_role_memberships.get(context.membership.id)
    if locked_actor is None or not locked_actor.is_active or not locked_actor.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active company membership is required to create an IP record.",
        )
    require_locked_membership_capability(session, locked_actor, "ip:write")
    if linked_matter is not None:
        locked_matter = session.scalar(
            select(Matter)
            .where(
                Matter.id == linked_matter.id,
                Matter.company_id == context.company.id,
            )
            .with_for_update(of=Matter)
            .execution_options(populate_existing=True)
        )
        if locked_matter is None:
            raise HTTPException(status_code=404, detail="Matter not found.")
        locked_role_snapshot = _operational_matter_role_snapshot(
            session,
            matter=locked_matter,
        )
        if locked_role_snapshot != candidate_role_snapshot:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_docket_linked_matter_roles_changed",
                    "message": (
                        "Linked-Matter responsibility changed; reload before creating "
                        "the IP record."
                    ),
                },
            )
        locked_context = SessionContext(
            company=context.company,
            user=locked_actor.user,
            membership=locked_actor,
        )
        _matter_for_docket(session, context=locked_context, matter_id=locked_matter.id)
        for membership_id in sorted(candidate_role_ids):
            member = linked_role_memberships.get(membership_id)
            if member is None or not member.is_active or not member.user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ip_docket_linked_matter_role_inactive",
                        "message": (
                            "Reassign inactive Matter responsibility before linking a "
                            "new operational IP record."
                        ),
                        "blocked_membership_ids": [membership_id],
                    },
                )
            if not can_stably_access_matter(
                session,
                context=SessionContext(
                    company=context.company,
                    user=member.user,
                    membership=member,
                ),
                matter=locked_matter,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ip_docket_linked_matter_role_lacks_stable_access",
                        "message": (
                            "Resolve durable linked-Matter access for every operational "
                            "role before creating the IP record."
                        ),
                        "blocked_membership_ids": [membership_id],
                    },
                )
    errors = _readiness_errors(payload.particulars)
    docket_values = {
        "company_id": context.company.id,
        "matter_id": payload.matter_id,
        "record_type": "trademark",
        "title": payload.title.strip(),
        "primary_identifier": (
            payload.primary_identifier.strip().upper() if payload.primary_identifier else None
        ),
        "status": "draft" if errors else "ready",
        "restricted": payload.restricted,
        "current_version": 1,
        "created_by_membership_id": context.membership.id,
    }
    if docket_id is not None:
        docket_values["id"] = docket_id
    docket = IpDocketRecord(**docket_values)
    session.add(docket)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That IP identifier already exists in this company.",
        ) from exc
    seed_restricted_ip_creator_access(
        session,
        context=context,
        docket=docket,
    )
    if docket.restricted:
        for membership_id in sorted(candidate_role_ids - {context.membership.id}):
            session.add(
                MatterAccessGrant(
                    company_id=context.company.id,
                    ip_docket_id=docket.id,
                    membership_id=membership_id,
                    access_level=MatterAccessLevel.MEMBER,
                    reason="Initial restricted-record Matter responsibility access.",
                    granted_by_membership_id=context.membership.id,
                )
            )
            docket.access_policy_version += 1
    version = _new_version(
        docket=docket,
        context=context,
        payload=payload.particulars,
        version=1,
        errors=errors,
        finalize=not errors,
    )
    session.add(version)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_docket.created",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"record_type": "trademark", "readiness_status": version.readiness_status},
    )
    if source_provenance is not None:
        source_type, source_id = source_provenance
        record_from_context(
            session,
            context,
            action="ip_docket.source_materialized",
            target_type=source_type,
            target_id=source_id,
            matter_id=docket.matter_id,
            ip_docket_id=docket.id,
            metadata={"docket_id": docket.id},
        )
    session.commit()
    session.refresh(docket)
    return _serialize_docket(session, docket, context=context)


def _new_version(
    *,
    docket: IpDocketRecord,
    context: SessionContext,
    payload: TrademarkParticularPayload,
    version: int,
    errors: list[str],
    finalize: bool,
) -> IpTrademarkParticularVersion:
    return IpTrademarkParticularVersion(
        company_id=docket.company_id,
        docket_id=docket.id,
        version=version,
        form_key=payload.form_key,
        form_version=payload.form_version,
        mark_kind=payload.mark_kind,
        representation_json=payload.representation,
        classes_json=[row.model_dump() for row in payload.classes],
        use_priority_json=payload.use_priority,
        parties_json=[row.model_dump() for row in payload.parties],
        agent_json=payload.agent,
        filing_manifest_json=[row.model_dump() for row in payload.filing_manifest],
        readiness_status="ready" if not errors else "incomplete",
        readiness_errors_json=errors,
        created_by_membership_id=context.membership.id,
        finalized_at=_now() if finalize and not errors else None,
    )


def append_ip_docket_version(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDocketVersionCreateRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:write",
    )
    if docket.current_version != payload.expected_current_version:
        raise HTTPException(
            status_code=409,
            detail="IP docket version changed; reload before saving.",
        )
    errors = _readiness_errors(payload)
    if payload.finalize and errors:
        raise HTTPException(status_code=409, detail={"readiness_errors": errors})
    next_version = docket.current_version + 1
    session.add(
        _new_version(
            docket=docket,
            context=context,
            payload=payload,
            version=next_version,
            errors=errors,
            finalize=payload.finalize,
        )
    )
    docket.current_version = next_version
    docket.status = "ready" if payload.finalize and not errors else "draft"
    docket.updated_at = _now()
    record_from_context(
        session,
        context,
        action="ip_docket.version_created",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"version": next_version, "status": docket.status},
    )
    session.commit()
    session.refresh(docket)
    return _serialize_docket(session, docket, context=context)


def list_ip_dockets(session: Session, *, context: SessionContext) -> IpDocketListResponse:
    rows = list(
        session.scalars(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.company_id == context.company.id,
                visible_ip_dockets_filter(session, context=context),
            )
            .order_by(IpDocketRecord.updated_at.desc())
        ).all()
    )
    # One reader, one capability resolution - not one per docket in the list.
    may_read_rates = _may_read_confidential_rates(session, context=context)
    visible: list[IpDocketRecordResponse] = []
    for row in rows:
        if row.archived_by_matter_disposal or not row.is_active:
            continue
        if row.matter_id:
            matter = session.get(Matter, row.matter_id)
            if matter is None:
                continue
            try:
                assert_operational_matter(session, matter=matter)
            except MatterNotOperationalError:
                continue
        visible.append(
            _serialize_docket(
                session,
                row,
                context=context,
                may_read_rates=may_read_rates,
            )
        )
    return IpDocketListResponse(dockets=visible, count=len(visible))


def get_ip_docket(
    session: Session, *, context: SessionContext, docket_id: str
) -> IpDocketRecordResponse:
    return _serialize_docket(
        session,
        _docket_or_404(session, context=context, docket_id=docket_id),
        context=context,
    )


def _membership_or_404(
    session: Session, context: SessionContext, membership_id: str
) -> CompanyMembership:
    row = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == context.company.id,
        )
    )
    if row is None or not row.is_active or not row.user.is_active:
        raise HTTPException(status_code=404, detail="Company membership not found.")
    return row


def _lock_assignment_memberships_or_404(
    session: Session,
    context: SessionContext,
    *,
    membership_ids: set[str | None],
    active_membership_ids: set[str | None],
    required_capability: str,
) -> dict[str, CompanyMembership]:
    """Fence every assignment participant before locking lifecycle parents."""

    required_active_ids = {
        membership_id for membership_id in active_membership_ids if membership_id
    } | {context.membership.id}
    requested_ids = {
        membership_id for membership_id in membership_ids if membership_id
    } | required_active_ids
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=requested_ids,
    )
    if set(memberships) != requested_ids:
        raise HTTPException(status_code=404, detail="Company membership not found.")
    if any(
        not memberships[membership_id].is_active or not memberships[membership_id].user.is_active
        for membership_id in required_active_ids
    ):
        raise HTTPException(status_code=404, detail="Company membership not found.")
    require_locked_membership_capability(
        session,
        memberships[context.membership.id],
        required_capability,
    )
    return memberships


def add_ip_notice_link(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpNoticeLinkCreateRequest,
) -> IpDocketRecordResponse:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:write",
    )
    notice = session.scalar(
        select(CompanyNotice).where(
            CompanyNotice.id == payload.notice_id,
            CompanyNotice.company_id == context.company.id,
        )
    )
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    link = CompanyNoticeIpLink(
        company_id=context.company.id,
        docket_id=docket.id,
        notice_id=notice.id,
        link_kind=payload.link_kind,
        accepted_effect=payload.accepted_effect,
        created_by_membership_id=context.membership.id,
    )
    session.add(link)
    session.flush()
    record_from_context(
        session,
        context,
        action="company_notice.ip_linked",
        target_type="company_notice",
        target_id=notice.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"docket_id": docket.id, "link_kind": payload.link_kind},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Notice is already linked.") from exc
    return _serialize_docket(session, docket, context=context)


def _fingerprint(*parts: object) -> str:
    canonical = "|".join(str(part or "").strip().casefold() for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _evidence_source_specs(
    session: Session,
    *,
    docket: IpDocketRecord,
) -> list[dict[str, object]]:
    if not docket.matter_id:
        return []
    matter_id = docket.matter_id
    specs: list[dict[str, object]] = []

    notices = list(
        session.scalars(
            select(CompanyNotice)
            .join(
                CompanyNoticeMatterLink,
                CompanyNoticeMatterLink.notice_id == CompanyNotice.id,
            )
            .where(
                CompanyNotice.company_id == docket.company_id,
                CompanyNoticeMatterLink.company_id == docket.company_id,
                CompanyNoticeMatterLink.matter_id == matter_id,
            )
        ).all()
    )
    accepted_notice_ids = set(
        session.scalars(
            select(CompanyNoticeIpLink.notice_id).where(
                CompanyNoticeIpLink.company_id == docket.company_id,
                CompanyNoticeIpLink.docket_id == docket.id,
            )
        ).all()
    )
    for row in notices:
        if row.id in accepted_notice_ids:
            continue
        specs.append(
            {
                "source_type": "company_notice",
                "source_id": row.id,
                "fingerprint": row.sha256_hex or _fingerprint("notice", row.id),
                "evidence_kind": "official_notice" if row.authority else "correspondence",
                "link_kind": "official_notice" if row.authority else "correspondence",
                "metadata": {
                    "label": row.subject[:255],
                    "direction": row.direction,
                    "has_document": bool(row.storage_key),
                    "reply_required": row.reply_required,
                },
            }
        )

    communications = list(
        session.scalars(
            select(Communication).where(
                Communication.company_id == docket.company_id,
                Communication.matter_id == matter_id,
            )
        ).all()
    )
    for row in communications:
        specs.append(
            {
                "source_type": "communication",
                "source_id": row.id,
                "fingerprint": _fingerprint(
                    "communication",
                    row.external_message_id or row.id,
                    row.subject,
                    row.body,
                ),
                "evidence_kind": "correspondence",
                "link_kind": "instruction" if row.direction == "inbound" else "correspondence",
                "metadata": {
                    "label": (row.subject or f"{row.channel} communication")[:255],
                    "direction": row.direction,
                    "channel": row.channel,
                    "occurred_at": row.occurred_at.isoformat(),
                },
            }
        )

    attachments = list(
        session.scalars(
            select(MatterAttachment).where(MatterAttachment.matter_id == matter_id)
        ).all()
    )
    for row in attachments:
        specs.append(
            {
                "source_type": "matter_attachment",
                "source_id": row.id,
                "fingerprint": row.sha256_hex,
                "evidence_kind": "official_notice" if row.notice_type else "document",
                "link_kind": "official_notice" if row.notice_type else "correspondence",
                "metadata": {
                    "label": row.original_filename[:255],
                    "document_type": row.document_type,
                    "processing_status": row.processing_status,
                    "has_notice_metadata": bool(row.notice_type),
                },
            }
        )

    drive_rows = list(
        session.scalars(
            select(DriveFileCandidate).where(
                DriveFileCandidate.company_id == docket.company_id,
                DriveFileCandidate.linked_matter_id == matter_id,
            )
        ).all()
    )
    attachment_hashes = {row.id: row.sha256_hex for row in attachments}
    for row in drive_rows:
        specs.append(
            {
                "source_type": "drive_file_candidate",
                "source_id": row.id,
                "fingerprint": (
                    attachment_hashes.get(row.imported_attachment_id or "")
                    or _fingerprint(
                        "drive",
                        row.provider,
                        row.provider_file_id,
                        row.provider_version,
                    )
                ),
                "evidence_kind": "drive_document",
                "link_kind": "correspondence",
                "metadata": {
                    "label": row.name[:255],
                    "provider": row.provider,
                    "status": row.status,
                    "imported": bool(row.imported_attachment_id),
                },
            }
        )
    return specs


def discover_ip_evidence_candidates(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> IpEvidenceDiscoveryResponse:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:approve",
    )
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    discovered = 0
    duplicates = 0
    fingerprints: dict[str, IpEvidenceCandidate] = {}
    for candidate in session.scalars(
        select(IpEvidenceCandidate)
        .where(
            IpEvidenceCandidate.company_id == context.company.id,
            IpEvidenceCandidate.docket_id == docket.id,
        )
        .order_by(IpEvidenceCandidate.created_at)
    ):
        fingerprints.setdefault(candidate.source_fingerprint, candidate)
    for spec in _evidence_source_specs(session, docket=docket):
        existing = session.scalar(
            select(IpEvidenceCandidate).where(
                IpEvidenceCandidate.company_id == context.company.id,
                IpEvidenceCandidate.docket_id == docket.id,
                IpEvidenceCandidate.source_type == spec["source_type"],
                IpEvidenceCandidate.source_id == spec["source_id"],
            )
        )
        if existing is not None:
            continue
        fingerprint = str(spec["fingerprint"])
        duplicate = fingerprints.get(fingerprint)
        row = IpEvidenceCandidate(
            company_id=context.company.id,
            docket_id=docket.id,
            source_type=str(spec["source_type"]),
            source_id=str(spec["source_id"]),
            source_fingerprint=fingerprint,
            evidence_kind=str(spec["evidence_kind"]),
            suggested_link_kind=str(spec["link_kind"]),
            status="duplicate" if duplicate else "needs_review",
            duplicate_of_candidate_id=duplicate.id if duplicate else None,
            metadata_json=dict(spec["metadata"]),
        )
        session.add(row)
        session.flush()
        fingerprints.setdefault(fingerprint, row)
        discovered += 1
        duplicates += int(duplicate is not None)
    record_from_context(
        session,
        context,
        action="ip_evidence.discovery_completed",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"discovered_count": discovered, "duplicate_count": duplicates},
    )
    session.commit()
    rows = list(
        session.scalars(
            select(IpEvidenceCandidate)
            .where(IpEvidenceCandidate.docket_id == docket.id)
            .order_by(IpEvidenceCandidate.created_at.desc())
        ).all()
    )
    return IpEvidenceDiscoveryResponse(
        candidates=[IpEvidenceCandidateRecord.model_validate(row) for row in rows],
        discovered_count=discovered,
        duplicate_count=duplicates,
    )


def _candidate_source_still_linked(
    session: Session,
    *,
    docket: IpDocketRecord,
    candidate: IpEvidenceCandidate,
) -> bool:
    if not docket.matter_id:
        return False
    if candidate.source_type == "company_notice":
        return (
            session.scalar(
                select(CompanyNoticeMatterLink.id).where(
                    CompanyNoticeMatterLink.company_id == docket.company_id,
                    CompanyNoticeMatterLink.notice_id == candidate.source_id,
                    CompanyNoticeMatterLink.matter_id == docket.matter_id,
                )
            )
            is not None
        )
    if candidate.source_type == "communication":
        return (
            session.scalar(
                select(Communication.id).where(
                    Communication.company_id == docket.company_id,
                    Communication.id == candidate.source_id,
                    Communication.matter_id == docket.matter_id,
                )
            )
            is not None
        )
    if candidate.source_type == "matter_attachment":
        return (
            session.scalar(
                select(MatterAttachment.id).where(
                    MatterAttachment.id == candidate.source_id,
                    MatterAttachment.matter_id == docket.matter_id,
                )
            )
            is not None
        )
    if candidate.source_type == "drive_file_candidate":
        return (
            session.scalar(
                select(DriveFileCandidate.id).where(
                    DriveFileCandidate.company_id == docket.company_id,
                    DriveFileCandidate.id == candidate.source_id,
                    DriveFileCandidate.linked_matter_id == docket.matter_id,
                )
            )
            is not None
        )
    return False


def review_ip_evidence_candidate(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    candidate_id: str,
    payload: IpEvidenceCandidateReviewRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    candidate = session.scalar(
        select(IpEvidenceCandidate)
        .where(
            IpEvidenceCandidate.id == candidate_id,
            IpEvidenceCandidate.docket_id == docket.id,
            IpEvidenceCandidate.company_id == context.company.id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="IP evidence candidate not found.")
    if candidate.status != payload.expected_status:
        raise HTTPException(status_code=409, detail="IP evidence candidate changed; reload.")
    if not _candidate_source_still_linked(session, docket=docket, candidate=candidate):
        raise HTTPException(
            status_code=409,
            detail="The source is no longer linked to this Matter.",
        )
    now = _now()
    if payload.action == "accept":
        candidate.status = "accepted"
        candidate.accepted_effect = payload.accepted_effect
        if candidate.source_type == "company_notice":
            existing_link = session.scalar(
                select(CompanyNoticeIpLink).where(
                    CompanyNoticeIpLink.notice_id == candidate.source_id,
                    CompanyNoticeIpLink.docket_id == docket.id,
                )
            )
            if existing_link is None:
                session.add(
                    CompanyNoticeIpLink(
                        company_id=context.company.id,
                        docket_id=docket.id,
                        notice_id=candidate.source_id,
                        link_kind=payload.link_kind or candidate.suggested_link_kind,
                        accepted_effect=payload.accepted_effect,
                        created_by_membership_id=context.membership.id,
                    )
                )
    else:
        candidate.status = "rejected"
    candidate.reviewed_by_membership_id = context.membership.id
    candidate.reviewed_at = now
    record_from_context(
        session,
        context,
        action=f"ip_evidence.{candidate.status}",
        target_type="ip_evidence_candidate",
        target_id=candidate.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "source_type": candidate.source_type,
            "source_ref": candidate.source_fingerprint[:16],
            "link_kind": payload.link_kind or candidate.suggested_link_kind,
        },
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)


def _deadline_for_docket(
    session: Session,
    *,
    docket: IpDocketRecord,
    deadline_id: str,
) -> MatterDeadline:
    deadline = session.scalar(select(MatterDeadline).where(MatterDeadline.id == deadline_id))
    if deadline is None or not (
        (deadline.matter_id is None and deadline.ip_docket_id == docket.id)
        or (
            docket.matter_id is not None
            and deadline.matter_id == docket.matter_id
            and deadline.ip_docket_id is None
        )
    ):
        raise HTTPException(
            status_code=404,
            detail="Operational deadline is not part of this IP record.",
        )
    return deadline


def _lock_legal_deadlines_for_operational_deadlines(
    session: Session,
    *,
    company_id: str,
    matter_deadline_ids: set[str] | list[str],
) -> dict[str, IpDeadline]:
    """Lock legal parents before their operational deadline projections."""

    ids = sorted(set(matter_deadline_ids))
    if not ids:
        return {}
    candidates = list(
        session.execute(
            select(
                IpDeadline.id,
                IpDeadline.matter_deadline_id,
                IpDeadline.docket_id,
            ).where(
                IpDeadline.company_id == company_id,
                IpDeadline.matter_deadline_id.in_(ids),
            )
        ).all()
    )
    if not candidates:
        return {}
    rows = list(
        session.scalars(
            select(IpDeadline)
            .where(
                IpDeadline.company_id == company_id,
                IpDeadline.id.in_([candidate.id for candidate in candidates]),
            )
            .order_by(IpDeadline.id)
            .with_for_update(of=IpDeadline)
            .execution_options(populate_existing=True)
        ).all()
    )
    expected = {
        candidate.id: (candidate.matter_deadline_id, candidate.docket_id)
        for candidate in candidates
    }
    if len(rows) != len(expected) or any(
        (row.matter_deadline_id, row.docket_id) != expected.get(row.id) for row in rows
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IP legal-deadline projection changed; reload and retry.",
        )
    return {row.matter_deadline_id: row for row in rows if row.matter_deadline_id}


def _lock_docket_deadline(
    session: Session,
    *,
    docket: IpDocketRecord,
    deadline_id: str,
) -> MatterDeadline:
    """Lock and refresh the linked deadline before any coverage child.

    Operational validation happens after the coverage child is locked. That
    preserves the canonical lock order while letting callers retain the more
    specific inactive-child error when a terminal lifecycle has neutralized
    both rows.
    """

    legal_deadline = _lock_legal_deadlines_for_operational_deadlines(
        session,
        company_id=docket.company_id,
        matter_deadline_ids={deadline_id},
    ).get(deadline_id)
    if legal_deadline is not None and legal_deadline.docket_id != docket.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IP legal deadline belongs to a different docket.",
        )
    target_predicate = or_(
        and_(
            MatterDeadline.ip_docket_id == docket.id,
            MatterDeadline.matter_id.is_(None),
        ),
        and_(
            docket.matter_id is not None,
            MatterDeadline.matter_id == docket.matter_id,
            MatterDeadline.ip_docket_id.is_(None),
        ),
    )
    deadline = session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == deadline_id,
            MatterDeadline.company_id == docket.company_id,
            target_predicate,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    if deadline is None:
        raise HTTPException(
            status_code=404,
            detail="Operational deadline is not part of this IP record.",
        )
    return deadline


def _assert_operational_coverage_deadline(deadline: MatterDeadline) -> None:
    if _deadline_is_operational(deadline):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ip_coverage_deadline_inactive",
            "message": "Completed, cancelled, or neutralized deadlines cannot carry coverage.",
        },
    )


def _operational_coverage_ids_for_deadline(
    session: Session,
    *,
    company_id: str,
    deadline: MatterDeadline,
    lock: bool = False,
) -> list[str]:
    """Return live coverage projections sharing one identified deadline."""

    statement = (
        select(IpDeadlineCoverage, IpDocketRecord, Matter)
        .join(IpDocketRecord, IpDocketRecord.id == IpDeadlineCoverage.docket_id)
        .outerjoin(Matter, Matter.id == IpDocketRecord.matter_id)
        .where(
            IpDeadlineCoverage.company_id == company_id,
            IpDeadlineCoverage.matter_deadline_id == deadline.id,
        )
        .order_by(IpDeadlineCoverage.id)
    )
    if lock:
        statement = statement.with_for_update(of=IpDeadlineCoverage)
    return [
        coverage.id
        for coverage, docket, matter in session.execute(statement).all()
        if _coverage_child_is_operational(
            coverage,
            docket=docket,
            deadline=deadline,
            matter=matter,
        )
    ]


def _assert_single_operational_coverage_projection(
    session: Session,
    *,
    company_id: str,
    deadline: MatterDeadline,
    coverage_id: str | None,
) -> None:
    """Fail closed until a group handoff exists for shared live deadlines."""

    operational_ids = _operational_coverage_ids_for_deadline(
        session,
        company_id=company_id,
        deadline=deadline,
        lock=True,
    )
    expected_ids = [] if coverage_id is None else [coverage_id]
    if operational_ids == expected_ids:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ip_coverage_shared_deadline_handoff_required",
            "message": (
                "This operational deadline is shared by multiple IP docket coverages. "
                "Use a future group handoff workflow before changing responsibility."
            ),
            "matter_deadline_id": deadline.id,
            "coverage_ids": operational_ids,
        },
    )


def add_ip_deadline_coverage(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDeadlineCoverageCreateRequest,
) -> IpDocketRecordResponse:
    assert_distinct_deadline_coverage(
        responsible_membership_id=payload.responsible_membership_id,
        backup_membership_id=payload.backup_membership_id,
    )
    deadline_candidate = session.execute(
        select(
            MatterDeadline.assignee_membership_id,
            MatterDeadline.company_id,
        ).where(MatterDeadline.id == payload.matter_deadline_id)
    ).one_or_none()
    if deadline_candidate is None or deadline_candidate.company_id != context.company.id:
        raise HTTPException(
            status_code=404,
            detail="Operational deadline is not part of this IP record.",
        )
    assignment_ids = {
        deadline_candidate.assignee_membership_id,
        payload.responsible_membership_id,
        payload.backup_membership_id,
    }
    memberships = _lock_assignment_memberships_or_404(
        session,
        context,
        membership_ids=assignment_ids,
        active_membership_ids=assignment_ids,
        required_capability="ip:approve",
    )
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    deadline = _lock_docket_deadline(
        session,
        docket=docket,
        deadline_id=payload.matter_deadline_id,
    )
    _assert_operational_coverage_deadline(deadline)
    if deadline.assignee_membership_id != deadline_candidate.assignee_membership_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_deadline_assignment_changed",
                "message": "Deadline responsibility changed; reload before adding coverage.",
            },
        )
    _assert_single_operational_coverage_projection(
        session,
        company_id=context.company.id,
        deadline=deadline,
        coverage_id=None,
    )
    for incoming_id in assignment_ids:
        if incoming_id is not None:
            _assert_replacement_can_cover(
                session,
                context=context,
                replacement=memberships[incoming_id],
                dockets=[docket],
            )
    row = IpDeadlineCoverage(
        company_id=context.company.id,
        docket_id=docket.id,
        matter_deadline_id=payload.matter_deadline_id,
        responsible_membership_id=payload.responsible_membership_id,
        backup_membership_id=payload.backup_membership_id,
        coverage_status=payload.coverage_status,
        calendar_projection_status="pending",
        accepted_at=_now() if payload.coverage_status == "accepted" else None,
    )
    session.add(row)
    session.flush()
    projection = cutover_ip_coverage_projection(
        session,
        context=context,
        docket=docket,
        coverage=row,
        previous_responsible_membership_id=deadline_candidate.assignee_membership_id,
        previous_backup_membership_id=row.backup_membership_id,
        reason="Initial IP deadline coverage assignment",
        replacement_source="coverage_created",
        responsible_accepted_at=row.accepted_at,
    )
    record_from_context(
        session,
        context,
        action="ip_deadline_coverage.accepted",
        target_type="ip_deadline_coverage",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "matter_deadline_id": payload.matter_deadline_id,
            "calendar_projection_count": len(projection.calendar.desired_connection_ids),
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Deadline coverage already exists.") from exc
    return _serialize_docket(session, docket, context=context)


def _resolve_escalation(
    *,
    mode: str,
    escalation_membership_id: str | None,
    memberships: dict[str, CompanyMembership],
) -> CompanyMembership | None:
    """An immediate transfer must name where a rejection goes.

    Immediate transfers exist because the outgoing person cannot be waited on.
    If the replacement then declines, the work has nowhere to fall back to, so
    the escalation owner is mandatory rather than optional.
    """

    if mode != "immediate":
        return None
    if escalation_membership_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_escalation_required",
                "message": (
                    "An immediate transfer must name an escalation owner, so declined "
                    "work cannot be left without a responsible person."
                ),
            },
        )
    return memberships[escalation_membership_id]


def _assert_source_can_propose(
    source: CompanyMembership,
    *,
    transfer_mode: str,
) -> None:
    """Legacy-inactive ownership may be repaired, but cannot stay pending."""

    if transfer_mode != "proposed" or (source.is_active and source.user.is_active):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ip_coverage_immediate_repair_required",
            "message": (
                "An inactive current owner cannot retain responsibility during a "
                "proposal. Use the privileged immediate repair workflow."
            ),
        },
    )


def _assert_operational_coverage_participants(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    coverage_id: str,
    memberships: dict[str, CompanyMembership],
    responsible_membership_id: str,
    backup_membership_id: str | None,
) -> None:
    """Require every role that remains live to be active and dual-authorized."""

    for role, membership_id in (
        ("responsible", responsible_membership_id),
        ("backup", backup_membership_id),
    ):
        if membership_id is None:
            continue
        membership = memberships.get(membership_id)
        if membership is None or not membership.is_active or not membership.user.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_coverage_participant_repair_required",
                    "message": (
                        "A resulting operational coverage role belongs to an inactive "
                        "employee. Repair it with an immediate authorized handoff."
                    ),
                    "coverage_id": coverage_id,
                    "role": role,
                    "membership_id": membership_id,
                },
            )
        _assert_replacement_can_cover(
            session,
            context=context,
            replacement=membership,
            dockets=[docket],
        )


def _apply_coverage_transfer(
    coverage: IpDeadlineCoverage,
    *,
    replacement: CompanyMembership,
    mode: str,
    escalation: CompanyMembership | None,
    reason: str,
    now: datetime,
) -> bool:
    """Move or propose responsibility for one coverage row (CAL-OPS-08).

    Returns ``True`` when responsibility actually moved. This is the single
    place either transfer path may touch responsibility. It never creates an
    acceptance timestamp: an immediate handoff clears the prior owner's
    acceptance when responsibility changes, and only the named replacement's
    later decision may write a new ``accepted_at``.
    """

    coverage.pending_replacement_membership_id = replacement.id
    coverage.replacement_decision = "pending"
    coverage.replacement_decided_at = None
    coverage.replacement_decision_reason = reason
    coverage.reassignment_version += 1
    coverage.updated_at = now

    if mode == "immediate":
        if coverage.responsible_membership_id != replacement.id:
            coverage.accepted_at = None
        coverage.responsible_membership_id = replacement.id
        coverage.emergency_escalation_membership_id = escalation.id if escalation else None
        coverage.emergency_until = None
        coverage.coverage_status = "reassigned"
        # They hold the work now, so it belongs on their calendar now.
        coverage.calendar_projection_status = "pending"
        return True

    # Proposed: the current owner keeps the work until the replacement accepts.
    coverage.emergency_escalation_membership_id = None
    coverage.emergency_until = None
    coverage.coverage_status = "transfer_pending"
    return False


def reassign_ip_deadline_coverage(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    coverage_id: str,
    payload: IpDeadlineCoverageReassignRequest,
) -> IpDocketRecordResponse:
    assert_distinct_deadline_coverage(
        responsible_membership_id=payload.responsible_membership_id,
        backup_membership_id=payload.backup_membership_id,
    )
    candidate = session.execute(
        select(
            IpDeadlineCoverage.docket_id,
            IpDeadlineCoverage.matter_deadline_id,
            IpDeadlineCoverage.responsible_membership_id,
            IpDeadlineCoverage.backup_membership_id,
            IpDeadlineCoverage.pending_replacement_membership_id,
            IpDeadlineCoverage.emergency_escalation_membership_id,
            IpDeadlineCoverage.reassignment_version,
        ).where(
            IpDeadlineCoverage.id == coverage_id,
            IpDeadlineCoverage.docket_id == docket_id,
            IpDeadlineCoverage.company_id == context.company.id,
        )
    ).one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Deadline coverage not found.")
    assignment_ids = {
        candidate.responsible_membership_id,
        candidate.backup_membership_id,
        candidate.pending_replacement_membership_id,
        candidate.emergency_escalation_membership_id,
        payload.expected_responsible_membership_id,
        payload.responsible_membership_id,
        payload.backup_membership_id,
        (payload.escalation_membership_id if payload.transfer_mode == "immediate" else None),
    }
    active_assignment_ids = {
        payload.responsible_membership_id,
        (payload.escalation_membership_id if payload.transfer_mode == "immediate" else None),
    }
    memberships = _lock_assignment_memberships_or_404(
        session,
        context,
        membership_ids=assignment_ids,
        active_membership_ids=active_assignment_ids,
        required_capability="ip:approve",
    )
    source = memberships[candidate.responsible_membership_id]
    _assert_source_can_propose(source, transfer_mode=payload.transfer_mode)
    replacement = memberships[payload.responsible_membership_id]
    backup = memberships[payload.backup_membership_id] if payload.backup_membership_id else None
    escalation = _resolve_escalation(
        mode=payload.transfer_mode,
        escalation_membership_id=payload.escalation_membership_id,
        memberships=memberships,
    )
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    deadline = _lock_docket_deadline(
        session,
        docket=docket,
        deadline_id=candidate.matter_deadline_id,
    )
    coverage = session.scalar(
        select(IpDeadlineCoverage)
        .where(
            IpDeadlineCoverage.id == coverage_id,
            IpDeadlineCoverage.docket_id == docket.id,
            IpDeadlineCoverage.company_id == context.company.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if coverage is None:
        raise HTTPException(status_code=404, detail="Deadline coverage not found.")
    if (
        coverage.responsible_membership_id,
        coverage.backup_membership_id,
        coverage.pending_replacement_membership_id,
        coverage.emergency_escalation_membership_id,
        coverage.reassignment_version,
    ) != (
        candidate.responsible_membership_id,
        candidate.backup_membership_id,
        candidate.pending_replacement_membership_id,
        candidate.emergency_escalation_membership_id,
        candidate.reassignment_version,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_assignment_changed",
                "message": "Coverage assignments changed; reload before reassigning.",
            },
        )
    matter = session.get(Matter, docket.matter_id) if docket.matter_id else None
    if not _coverage_lifecycle_is_operational(
        coverage,
        docket=docket,
        matter=matter,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_inactive_lifecycle",
                "message": "Lifecycle-neutralized coverage cannot be reassigned.",
            },
        )
    _assert_operational_coverage_deadline(deadline)
    if not _coverage_child_is_operational(
        coverage,
        docket=docket,
        deadline=deadline,
        matter=matter,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_inactive_lifecycle",
                "message": "Lifecycle-neutralized coverage cannot be reassigned.",
            },
        )
    _assert_single_operational_coverage_projection(
        session,
        company_id=context.company.id,
        deadline=deadline,
        coverage_id=coverage.id,
    )
    assert_distinct_deadline_coverage(
        responsible_membership_id=coverage.responsible_membership_id,
        backup_membership_id=coverage.backup_membership_id,
    )
    if coverage.responsible_membership_id != payload.expected_responsible_membership_id:
        raise HTTPException(
            status_code=409,
            detail="Deadline responsibility changed; reload before reassigning.",
        )
    # Proposed mode changes backup cover immediately but leaves the current
    # owner responsible until acceptance. Validate that transient state as well
    # as the eventual replacement/backup pairing checked above; otherwise
    # ``backup=current owner`` reaches the database as an A/A row and leaks a
    # constraint failure instead of returning the typed domain conflict.
    effective_responsible_membership_id = (
        payload.responsible_membership_id
        if payload.transfer_mode == "immediate"
        else coverage.responsible_membership_id
    )
    assert_distinct_deadline_coverage(
        responsible_membership_id=effective_responsible_membership_id,
        backup_membership_id=payload.backup_membership_id,
    )
    if payload.backup_membership_id != coverage.backup_membership_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_backup_handoff_required",
                "message": (
                    "Existing backup responsibility cannot be replaced without an "
                    "accepted backup-handoff workflow."
                ),
            },
        )
    _assert_operational_coverage_participants(
        session,
        context=context,
        docket=docket,
        coverage_id=coverage.id,
        memberships=memberships,
        responsible_membership_id=effective_responsible_membership_id,
        backup_membership_id=payload.backup_membership_id,
    )
    # Guard before any mutation: an incoming owner or backup who cannot open
    # the record must not be given responsibility for its deadline.
    for incoming in (replacement, backup, escalation):
        if incoming is not None:
            _assert_replacement_can_cover(
                session, context=context, replacement=incoming, dockets=[docket]
            )
    if escalation is not None:
        assert_distinct_deadline_escalation(
            escalation_membership_id=escalation.id,
            backup_membership_id=payload.backup_membership_id,
            responsible_membership_id=replacement.id,
        )
    old_responsible = coverage.responsible_membership_id
    old_backup = coverage.backup_membership_id
    # Naming a backup is an administrative assignment and applies at once; the
    # backup is not accountable for the date until responsibility moves.
    coverage.backup_membership_id = payload.backup_membership_id
    now = _now()
    moved = _apply_coverage_transfer(
        coverage,
        replacement=replacement,
        mode=payload.transfer_mode,
        escalation=escalation,
        reason=payload.reason,
        now=now,
    )
    if moved:
        session.flush()
        cutover_ip_coverage_projection(
            session,
            context=context,
            docket=docket,
            coverage=coverage,
            previous_responsible_membership_id=old_responsible,
            previous_backup_membership_id=old_backup,
            reason=payload.reason,
            replacement_source="direct_immediate",
            responsible_accepted_at=None,
            notification_escalation_membership_id=(
                escalation.id if escalation is not None else None
            ),
            changed_at=now,
        )
    record_from_context(
        session,
        context,
        action=f"ip_deadline_coverage.transfer_{payload.transfer_mode}",
        target_type="ip_deadline_coverage",
        target_id=coverage.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "old_responsible_membership_id": old_responsible,
            "new_responsible_membership_id": coverage.responsible_membership_id,
            "proposed_responsible_membership_id": payload.responsible_membership_id,
            "transfer_mode": payload.transfer_mode,
            "reason": payload.reason,
        },
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)


def _membership_can_cover_docket(
    session: Session,
    *,
    context: SessionContext,
    membership: CompanyMembership,
    docket: IpDocketRecord,
) -> bool:
    recipient = SessionContext(
        company=context.company,
        user=membership.user,
        membership=membership,
    )
    return can_stably_access_ip_docket(
        session,
        context=recipient,
        docket=docket,
    )


def _assert_replacement_can_cover(
    session: Session,
    *,
    context: SessionContext,
    replacement: CompanyMembership,
    dockets: list[IpDocketRecord],
) -> None:
    """UJ-57-EXC-01/02: never hand work to someone who cannot open the record.

    Coverage reassignment previously checked only that the replacement existed,
    so a restricted docket or an ethical wall could be bypassed by making the
    walled-off member responsible for its deadline. The canonical
    ``can_access_ip_docket`` policy is evaluated as the *replacement*, and the
    transfer fails closed for the whole batch rather than partially applying.

    Blocked docket ids are returned so an operator can act, but no title or
    other record content is disclosed.
    """

    blocked = [
        docket.id
        for docket in dockets
        if not _membership_can_cover_docket(
            session,
            context=context,
            membership=replacement,
            docket=docket,
        )
    ]
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_replacement_lacks_access",
                "message": (
                    "The replacement cannot access every affected IP record, so the "
                    "transfer was refused in full."
                ),
                "blocked_docket_ids": sorted(blocked),
            },
        )


def bulk_reassign_ip_deadline_coverages(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCoverageBulkReassignRequest,
    commit: bool = True,
    replacement_source: str = "bulk_reassignment",
) -> IpCoverageBulkReassignResponse:
    if payload.from_membership_id == payload.to_membership_id:
        raise HTTPException(status_code=422, detail="Coverage replacement must be different.")
    candidate_rows = _coverages_for_member(
        session,
        context=context,
        membership_id=payload.from_membership_id,
    )
    assignment_ids = {
        payload.from_membership_id,
        payload.to_membership_id,
        (payload.escalation_membership_id if payload.transfer_mode == "immediate" else None),
    }
    assignment_ids.update(
        membership_id
        for row in candidate_rows
        for membership_id in (
            row.responsible_membership_id,
            row.backup_membership_id,
            row.pending_replacement_membership_id,
            row.emergency_escalation_membership_id,
        )
        if membership_id is not None
    )
    memberships = _lock_assignment_memberships_or_404(
        session,
        context,
        membership_ids=assignment_ids,
        active_membership_ids={
            payload.to_membership_id,
            (payload.escalation_membership_id if payload.transfer_mode == "immediate" else None),
        },
        required_capability="ip:approve",
    )
    source = memberships[payload.from_membership_id]
    _assert_source_can_propose(source, transfer_mode=payload.transfer_mode)
    replacement = memberships[payload.to_membership_id]
    escalation = _resolve_escalation(
        mode=payload.transfer_mode,
        escalation_membership_id=payload.escalation_membership_id,
        memberships=memberships,
    )
    # Matter lifecycle is authoritative. Lock every affected parent before its
    # docket and coverage children, then re-read all three levels from the
    # database. This matches disposal's lock order and prevents a stale ORM row
    # from being reassigned after disposal has neutralized it.
    rows, affected_dockets = _lock_operational_coverages_for_member(
        session,
        context=context,
        membership_id=source.id,
    )
    _assert_distinct_backup_replacement(
        rows,
        source_membership_id=source.id,
        replacement_membership_id=replacement.id,
    )
    if any(row.backup_membership_id == source.id for row in rows):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_backup_handoff_required",
                "message": (
                    "Existing backup responsibility cannot be bulk-reassigned without "
                    "an accepted backup-handoff workflow."
                ),
            },
        )
    _assert_replacement_can_cover(
        session, context=context, replacement=replacement, dockets=affected_dockets
    )
    affected_dockets_by_id = {docket.id: docket for docket in affected_dockets}
    deadlines_by_id = {
        deadline.id: deadline
        for deadline in session.scalars(
            select(MatterDeadline).where(
                MatterDeadline.company_id == context.company.id,
                MatterDeadline.id.in_({row.matter_deadline_id for row in rows}),
            )
        ).all()
    }
    for row in rows:
        docket = affected_dockets_by_id.get(row.docket_id)
        if docket is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Coverage participants changed; reload before reassignment.",
            )
        resulting_responsible_id = (
            replacement.id
            if row.responsible_membership_id == source.id and payload.transfer_mode == "immediate"
            else row.responsible_membership_id
        )
        _assert_operational_coverage_participants(
            session,
            context=context,
            docket=docket,
            coverage_id=row.id,
            memberships=memberships,
            responsible_membership_id=resulting_responsible_id,
            backup_membership_id=row.backup_membership_id,
        )
    if escalation is not None:
        responsible_docket_ids = {
            row.docket_id for row in rows if row.responsible_membership_id == source.id
        }
        _assert_replacement_can_cover(
            session,
            context=context,
            replacement=escalation,
            dockets=[docket for docket in affected_dockets if docket.id in responsible_docket_ids],
        )
        _assert_distinct_escalation_backups(
            rows,
            source_membership_id=source.id,
            escalation_membership_id=escalation.id,
            replacement_membership_id=replacement.id,
        )

    responsible_count = 0
    backup_count = 0
    pending_count = 0
    now = _now()
    for row in rows:
        expected_version = payload.expected_versions.get(row.id)
        if expected_version is not None and row.reassignment_version != expected_version:
            raise HTTPException(
                status_code=409,
                detail=f"Coverage {row.id} changed; reload before bulk reassignment.",
            )
        changed_roles: list[str] = []
        previous_responsible = row.responsible_membership_id
        previous_backup = row.backup_membership_id
        if row.backup_membership_id == source.id:
            # Backup naming is administrative and applies at once.
            row.backup_membership_id = replacement.id
            backup_count += 1
            changed_roles.append("backup")
        if row.responsible_membership_id == source.id:
            moved = _apply_coverage_transfer(
                row,
                replacement=replacement,
                mode=payload.transfer_mode,
                escalation=escalation,
                reason=payload.reason,
                now=now,
            )
            responsible_count += 1
            pending_count += 1
            changed_roles.append("responsible")
        else:
            moved = False
            row.updated_at = now
            row.reassignment_version += 1
        docket = affected_dockets_by_id.get(row.docket_id)
        deadline = deadlines_by_id.get(row.matter_deadline_id)
        if docket is None or deadline is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Coverage projection changed; reload before reassignment.",
            )
        _assert_single_operational_coverage_projection(
            session,
            company_id=context.company.id,
            deadline=deadline,
            coverage_id=row.id,
        )
        if moved:
            session.flush()
            cutover_ip_coverage_projection(
                session,
                context=context,
                docket=docket,
                coverage=row,
                previous_responsible_membership_id=previous_responsible,
                previous_backup_membership_id=previous_backup,
                reason=payload.reason,
                replacement_source=replacement_source,
                responsible_accepted_at=None,
                notification_escalation_membership_id=(
                    escalation.id if escalation is not None else None
                ),
                changed_at=now,
            )
        record_from_context(
            session,
            context,
            action=f"ip_deadline_coverage.bulk_transfer_{payload.transfer_mode}",
            target_type="ip_deadline_coverage",
            target_id=row.id,
            matter_id=docket.matter_id if docket else None,
            ip_docket_id=docket.id if docket else None,
            metadata={
                "from_membership_id": source.id,
                "to_membership_id": replacement.id,
                "roles": changed_roles,
                "reason": payload.reason,
                "reassignment_version": row.reassignment_version,
                "transfer_mode": payload.transfer_mode,
                "responsible_membership_id": row.responsible_membership_id,
            },
        )
    session.flush()
    if commit:
        session.commit()
    return IpCoverageBulkReassignResponse(
        reassigned_count=len(rows),
        responsible_count=responsible_count,
        backup_count=backup_count,
        coverage_ids=[row.id for row in rows],
        transfer_mode=payload.transfer_mode,
        pending_count=pending_count,
    )


def add_ip_deadline_incident(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDeadlineIncidentCreateRequest,
) -> IpDocketRecordResponse:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:approve",
    )
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    for deadline_id in (payload.matter_deadline_id, payload.correction_deadline_id):
        if deadline_id:
            _deadline_for_docket(session, docket=docket, deadline_id=deadline_id)
    incident = IpDeadlineIncident(
        company_id=context.company.id,
        docket_id=docket.id,
        matter_deadline_id=payload.matter_deadline_id,
        severity=payload.severity,
        summary=payload.summary.strip(),
        impact_json=payload.impact,
        containment=payload.containment,
        correction_deadline_id=payload.correction_deadline_id,
        status="contained" if payload.containment else "open",
    )
    session.add(incident)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_deadline_incident.created",
        target_type="ip_deadline_incident",
        target_id=incident.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"severity": payload.severity, "status": incident.status},
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)


def verify_ip_deadline_incident(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    incident_id: str,
    payload: IpDeadlineIncidentVerifyRequest,
) -> IpDocketRecordResponse:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:approve",
    )
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    incident = session.scalar(
        select(IpDeadlineIncident)
        .where(
            IpDeadlineIncident.id == incident_id,
            IpDeadlineIncident.docket_id == docket.id,
            IpDeadlineIncident.company_id == context.company.id,
        )
        .with_for_update()
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Deadline incident not found.")
    if not incident.containment:
        raise HTTPException(status_code=409, detail="Containment is required before verification.")
    incident.status = "verified"
    incident.corrective_action = payload.corrective_action.strip()
    incident.verified_at = _now()
    incident.verified_by_membership_id = context.membership.id
    record_from_context(
        session,
        context,
        action="ip_deadline_incident.verified",
        target_type="ip_deadline_incident",
        target_id=incident.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"severity": incident.severity},
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)


def add_ip_title_interest(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpTitleInterestCreateRequest,
) -> IpDocketRecordResponse:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:approve",
    )
    if payload.related_docket_id:
        if payload.related_docket_id == docket_id:
            raise HTTPException(status_code=422, detail="A docket cannot be related to itself.")
    requested_docket_ids = {docket_id}
    if payload.related_docket_id:
        requested_docket_ids.add(payload.related_docket_id)
    locked_dockets = _lock_ip_dockets_in_stable_order(
        session,
        context=context,
        docket_ids=requested_docket_ids,
        required_capability="ip:approve",
    )
    docket = locked_dockets[docket_id]
    existing = list(
        session.scalars(
            select(IpTitleInterest)
            .where(
                IpTitleInterest.company_id == context.company.id,
                IpTitleInterest.docket_id == docket.id,
            )
            .order_by(IpTitleInterest.id)
            .with_for_update()
        ).all()
    )
    flags: list[str] = []
    new_until = payload.effective_until or date.max
    for row in existing:
        row_until = row.effective_until or date.max
        overlaps = payload.effective_from <= row_until and row.effective_from <= new_until
        if overlaps and row.party_name.casefold() != payload.party_name.casefold():
            flags.append(f"party_overlap:{row.id}")
            if payload.interest_type in {"ownership", "assignment"} and row.interest_type in {
                "ownership",
                "assignment",
            }:
                flags.append(f"competing_title:{row.id}")
        if (
            overlaps
            and payload.interest_type == "licence"
            and row.interest_type
            in {
                "encumbrance",
                "security",
            }
        ):
            flags.append(f"licence_encumbrance_conflict:{row.id}")
    interest = IpTitleInterest(
        company_id=context.company.id,
        docket_id=docket.id,
        interest_type=payload.interest_type,
        party_name=payload.party_name.strip(),
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        related_docket_id=payload.related_docket_id,
        evidence_reference=payload.evidence_reference.strip(),
        recordal_status=payload.recordal_status,
        conflict_flags_json=flags,
    )
    session.add(interest)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_title_interest.created",
        target_type="ip_title_interest",
        target_id=interest.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "interest_type": payload.interest_type,
            "conflict_count": len(flags),
        },
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)


def add_ip_related_right_obligation(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpRelatedRightObligationCreateRequest,
) -> IpDocketRecordResponse:
    memberships = _lock_assignment_memberships_or_404(
        session,
        context,
        membership_ids={payload.owner_membership_id},
        active_membership_ids={payload.owner_membership_id},
        required_capability="ip:approve",
    )
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    _assert_replacement_can_cover(
        session,
        context=context,
        replacement=memberships[payload.owner_membership_id],
        dockets=[docket],
    )
    if payload.title_interest_id:
        interest = session.scalar(
            select(IpTitleInterest).where(
                IpTitleInterest.id == payload.title_interest_id,
                IpTitleInterest.docket_id == docket.id,
                IpTitleInterest.company_id == context.company.id,
            )
        )
        if interest is None:
            raise HTTPException(status_code=404, detail="Title interest not found.")
    if payload.matter_deadline_id:
        deadline = _lock_docket_deadline(
            session,
            docket=docket,
            deadline_id=payload.matter_deadline_id,
        )
        if not _deadline_is_operational(deadline):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_obligation_deadline_inactive",
                    "message": (
                        "Completed, cancelled, or neutralized deadlines cannot carry "
                        "an operational obligation."
                    ),
                },
            )
    row = IpRelatedRightObligation(
        company_id=context.company.id,
        docket_id=docket.id,
        title_interest_id=payload.title_interest_id,
        obligation_type=payload.obligation_type,
        title=payload.title.strip(),
        due_on=payload.due_on,
        owner_membership_id=payload.owner_membership_id,
        matter_deadline_id=payload.matter_deadline_id,
        status="open",
        evidence_reference=payload.evidence_reference.strip(),
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_related_right_obligation.created",
        target_type="ip_related_right_obligation",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "obligation_type": row.obligation_type,
            "due_on": row.due_on.isoformat() if row.due_on else None,
            "has_operational_deadline": bool(row.matter_deadline_id),
        },
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)


def complete_ip_related_right_obligation(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    obligation_id: str,
    payload: IpRelatedRightObligationCompleteRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    row = session.scalar(
        select(IpRelatedRightObligation)
        .where(
            IpRelatedRightObligation.id == obligation_id,
            IpRelatedRightObligation.docket_id == docket.id,
            IpRelatedRightObligation.company_id == context.company.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Related-right obligation not found.")
    if row.status != payload.expected_status:
        raise HTTPException(status_code=409, detail="Obligation changed; reload.")
    row.status = "completed"
    row.completion_evidence_reference = payload.completion_evidence_reference.strip()
    row.completed_at = _now()
    row.updated_at = row.completed_at
    record_from_context(
        session,
        context,
        action="ip_related_right_obligation.completed",
        target_type="ip_related_right_obligation",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"obligation_type": row.obligation_type},
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)


#: Every terminal answer reconciliation can give a cost. ``estimate`` and
#: ``nonbillable`` are outcomes, not stages: neither can become ``matched``.
_COST_RECONCILIATION_STATUSES = (
    "matched",
    "mismatch",
    "missing",
    "unlinked",
    "estimate",
    "nonbillable",
)

#: UJ-52-EXC-05. Confidential rates are readable only by the capability that
#: manages fees, not by every reader of the docket. ``ip:fees_view`` is
#: deliberately not enough: it is held by all staff.
_CONFIDENTIAL_RATE_CAPABILITY = "ip:fees_manage"


def _may_read_confidential_rates(session: Session, *, context: SessionContext) -> bool:
    return membership_has_capability(
        session,
        context.membership,
        _CONFIDENTIAL_RATE_CAPABILITY,
    )


def _serialize_cost_item(cost: IpCostItem, *, may_read_rates: bool) -> IpCostItemRecord:
    """Serialize one cost, withholding a confidential rate where required.

    Withholding replaces the monetary fields with ``None`` and sets
    ``amount_withheld``. It never substitutes a zero: a reader who cannot see
    the rate must be able to tell that a cost exists and that its amount was
    withheld, which is a different fact from a cost of nothing.
    """

    record = IpCostItemRecord.model_validate(cost)
    if not cost.rate_confidential or may_read_rates:
        return record
    return record.model_copy(
        update={
            "amount_minor": None,
            "fx_rate": None,
            "base_amount_minor": None,
            "canonical_amount_minor": None,
            "reconciliation_difference_minor": None,
            "amount_withheld": True,
        }
    )


def _cost_comparison_value(cost: IpCostItem) -> tuple[int, str]:
    """The amount the Matter ledger could actually match.

    ``amount_minor``/``currency`` always hold the cost as originally incurred
    (UJ-52-EXC-02). When a conversion was preserved, the ledger was billed in
    the converted currency, so that is the figure reconciliation must compare -
    comparing the original would report every converted cost as a mismatch.
    """

    if cost.base_amount_minor is not None and cost.base_currency is not None:
        return cost.base_amount_minor, cost.base_currency
    return cost.amount_minor, cost.currency


def _canonical_billing_value(
    session: Session,
    *,
    cost: IpCostItem,
) -> tuple[int | None, str | None, str]:
    # UJ-52-EXC-04: a provider's estimate is not an expense, so it has no
    # counterpart in the ledger and must never be reported as reconciled.
    if cost.cost_nature == "estimate":
        return None, None, "estimate"
    # UJ-52-EXC-01: a nonbillable cost is deliberately outside client billing.
    # It is a distinct answer from "not linked yet", which still expects a link.
    if not cost.billable:
        return None, None, "nonbillable"
    if not cost.billing_link_type or not cost.billing_link_id:
        return None, None, "unlinked"
    amount: int | None = None
    currency: str | None = None
    if cost.billing_link_type == "invoice":
        row = session.scalar(
            select(MatterInvoice).where(
                MatterInvoice.id == cost.billing_link_id,
                MatterInvoice.company_id == cost.company_id,
                MatterInvoice.matter_id == cost.matter_id,
            )
        )
        if row is not None:
            amount, currency = row.total_amount_minor, row.currency
    elif cost.billing_link_type == "invoice_line_item":
        result = session.execute(
            select(MatterInvoiceLineItem, MatterInvoice)
            .join(MatterInvoice, MatterInvoice.id == MatterInvoiceLineItem.invoice_id)
            .where(
                MatterInvoiceLineItem.id == cost.billing_link_id,
                MatterInvoice.company_id == cost.company_id,
                MatterInvoice.matter_id == cost.matter_id,
            )
        ).first()
        if result is not None:
            line, invoice = result
            amount, currency = line.line_total_amount_minor, invoice.currency
    elif cost.billing_link_type == "time_entry":
        row = session.scalar(
            select(MatterTimeEntry).where(
                MatterTimeEntry.id == cost.billing_link_id,
                MatterTimeEntry.matter_id == cost.matter_id,
            )
        )
        if row is not None:
            amount, currency = row.total_amount_minor, row.rate_currency
    if amount is None:
        return None, None, "missing"
    comparison_amount, comparison_currency = _cost_comparison_value(cost)
    if currency != comparison_currency or amount != comparison_amount:
        return amount, currency, "mismatch"
    return amount, currency, "matched"


def _apply_cost_reconciliation(
    session: Session,
    *,
    context: SessionContext,
    cost: IpCostItem,
) -> IpCostReconciliationRow:
    canonical_amount, _canonical_currency, status_value = _canonical_billing_value(
        session,
        cost=cost,
    )
    comparison_amount, comparison_currency = _cost_comparison_value(cost)
    cost.reconciliation_status = status_value
    cost.canonical_amount_minor = canonical_amount
    # The difference is against the figure that was compared, not against the
    # original amount: for a converted cost those are different numbers and
    # only the former describes the ledger gap.
    cost.reconciliation_difference_minor = (
        canonical_amount - comparison_amount if canonical_amount is not None else None
    )
    cost.reconciled_at = _now()
    cost.reconciled_by_membership_id = context.membership.id
    return IpCostReconciliationRow(
        cost_item_id=cost.id,
        billing_link_type=cost.billing_link_type,
        billing_link_id=cost.billing_link_id,
        evidence_amount_minor=cost.amount_minor,
        canonical_amount_minor=canonical_amount,
        difference_minor=cost.reconciliation_difference_minor,
        currency=cost.currency,
        comparison_amount_minor=comparison_amount,
        comparison_currency=comparison_currency,
        status=status_value,
    )


def add_ip_cost_item(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpCostItemCreateRequest,
) -> IpDocketRecordResponse:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:fees_manage",
    )
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:fees_manage",
    )
    # UJ-52-EXC-01. The absence of a billing Matter blocks billable capture,
    # never the capture of the cost itself: an official fee paid to the
    # registry is incurred whether or not a billing profile exists, and
    # refusing it here loses the evidence instead of deferring the billing
    # decision. The caller must state the decision; it is never inferred.
    if not docket.matter_id:
        if payload.billable:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This IP docket has no Matter billing owner, so a billable cost "
                    "cannot be recorded against it. Record the cost as nonbillable "
                    "to preserve the evidence, or link the docket to a Matter first."
                ),
            )
        if payload.billing_link_type is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This IP docket has no Matter billing owner, so there is no "
                    "billing record to link the cost to."
                ),
            )
    cost = IpCostItem(
        company_id=context.company.id,
        docket_id=docket.id,
        matter_id=docket.matter_id,
        category=payload.category,
        description=payload.description.strip(),
        amount_minor=payload.amount_minor,
        currency=payload.currency.upper(),
        billable=payload.billable,
        cost_nature=payload.cost_nature,
        rate_confidential=payload.rate_confidential,
        fx_rate=payload.fx_rate,
        fx_rate_source=(
            payload.fx_rate_source.strip() if payload.fx_rate_source is not None else None
        ),
        fx_converted_at=payload.fx_converted_at,
        base_amount_minor=payload.base_amount_minor,
        base_currency=(
            payload.base_currency.upper() if payload.base_currency is not None else None
        ),
        evidence_reference=payload.evidence_reference.strip(),
        billing_link_type=payload.billing_link_type,
        billing_link_id=payload.billing_link_id,
        created_by_membership_id=context.membership.id,
    )
    session.add(cost)
    session.flush()
    _apply_cost_reconciliation(session, context=context, cost=cost)
    record_from_context(
        session,
        context,
        action="ip_cost_item.created",
        target_type="ip_cost_item",
        target_id=cost.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        # The audit records the classification but never the amount: a
        # confidential rate withheld from the docket read path must not be
        # recoverable from the audit trail that every reviewer can read.
        metadata={
            "category": payload.category,
            "currency": payload.currency.upper(),
            "billable": payload.billable,
            "cost_nature": payload.cost_nature,
            "rate_confidential": payload.rate_confidential,
            "converted": payload.fx_rate is not None,
        },
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)


def reconcile_ip_cost_items(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> IpCostReconciliationReport:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:fees_manage",
    )
    costs = list(
        session.scalars(
            select(IpCostItem)
            .where(
                IpCostItem.company_id == context.company.id,
                IpCostItem.docket_id == docket.id,
            )
            .order_by(IpCostItem.created_at, IpCostItem.id)
            .with_for_update()
        ).all()
    )
    rows = [_apply_cost_reconciliation(session, context=context, cost=cost) for cost in costs]
    checksum_payload = [row.model_dump(mode="json") for row in rows]
    checksum = hashlib.sha256(
        json.dumps(checksum_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    record_from_context(
        session,
        context,
        action="ip_cost.reconciled",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "accounting_owner": "matter_billing",
            "row_count": len(rows),
            "checksum_sha256": checksum,
            "status_counts": {
                status_value: sum(row.status == status_value for row in rows)
                for status_value in _COST_RECONCILIATION_STATUSES
            },
        },
    )
    session.commit()
    return IpCostReconciliationReport(
        generated_at=_now(),
        docket_id=docket.id,
        rows=rows,
        matched_count=sum(row.status == "matched" for row in rows),
        mismatch_count=sum(row.status == "mismatch" for row in rows),
        missing_count=sum(row.status == "missing" for row in rows),
        unlinked_count=sum(row.status == "unlinked" for row in rows),
        estimate_count=sum(row.status == "estimate" for row in rows),
        nonbillable_count=sum(row.status == "nonbillable" for row in rows),
        checksum_sha256=checksum,
    )


def _ip_docket_control_report_from_listing(
    session: Session,
    *,
    context: SessionContext,
    listing: IpDocketListResponse,
    generated_at: datetime,
) -> IpDocketControlReport:
    totals: dict[str, int] = {}
    for docket in listing.dockets:
        for item in docket.cost_items:
            totals[item.currency] = totals.get(item.currency, 0) + item.amount_minor
    membership_active = {
        row.id: row.is_active
        for row in session.scalars(
            select(CompanyMembership).where(CompanyMembership.company_id == context.company.id)
        ).all()
    }
    return IpDocketControlReport(
        generated_at=generated_at,
        docket_count=listing.count,
        ready_count=sum(row.status == "ready" for row in listing.dockets),
        uncovered_deadline_count=sum(
            row.matter_id is not None and not row.deadline_coverages for row in listing.dockets
        ),
        open_incident_count=sum(
            incident.status != "verified"
            for row in listing.dockets
            for incident in row.deadline_incidents
        ),
        unprojected_calendar_count=sum(
            coverage.calendar_projection_status != "projected"
            for row in listing.dockets
            for coverage in row.deadline_coverages
        ),
        inactive_coverage_count=sum(
            not membership_active.get(coverage.responsible_membership_id, False)
            for row in listing.dockets
            for coverage in row.deadline_coverages
        ),
        total_cost_minor_by_currency=totals,
    )


def ip_docket_control_report(session: Session, *, context: SessionContext) -> IpDocketControlReport:
    listing = list_ip_dockets(session, context=context)
    return _ip_docket_control_report_from_listing(
        session,
        context=context,
        listing=listing,
        generated_at=_now(),
    )


__all__ = [
    "list_ip_assigned_coverage",
    "bulk_acknowledge_ip_coverage",
    "save_ip_docket_queue",
    "list_ip_docket_queues",
    "delete_ip_docket_queue",
    "list_ip_coverage_transfers_awaiting",
    "add_ip_cost_item",
    "add_ip_deadline_coverage",
    "add_ip_deadline_incident",
    "add_ip_notice_link",
    "add_ip_related_right_obligation",
    "add_ip_title_interest",
    "append_ip_docket_version",
    "bulk_reassign_ip_deadline_coverages",
    "complete_ip_related_right_obligation",
    "create_ip_docket",
    "discover_ip_evidence_candidates",
    "get_ip_docket",
    "ip_docket_control_report",
    "list_ip_dockets",
    "reconcile_ip_cost_items",
    "reassign_ip_deadline_coverage",
    "review_ip_evidence_candidate",
    "verify_ip_deadline_incident",
]


def _control_exceptions(
    session: Session,
    *,
    context: SessionContext,
    listing: IpDocketListResponse,
) -> list[IpControlExceptionRecord]:
    """CAL-OPS-13 exception queue, derived from access-filtered records only.

    A restricted record the caller cannot open never reaches ``listing``, so it
    contributes neither an exception nor a count.
    """

    membership_active = {
        row.id: row.is_active
        for row in session.scalars(
            select(CompanyMembership).where(CompanyMembership.company_id == context.company.id)
        ).all()
    }
    found: list[IpControlExceptionRecord] = []
    for docket in listing.dockets:
        if docket.matter_id is not None and not docket.deadline_coverages:
            found.append(IpControlExceptionRecord(docket_id=docket.id, kind="uncovered"))
        for coverage in docket.deadline_coverages:
            if not membership_active.get(coverage.responsible_membership_id, False):
                found.append(IpControlExceptionRecord(docket_id=docket.id, kind="inactive_owner"))
            if coverage.calendar_projection_status != "projected":
                found.append(
                    IpControlExceptionRecord(docket_id=docket.id, kind="unprojected_calendar")
                )
        for incident in docket.deadline_incidents:
            if incident.status != "verified":
                found.append(IpControlExceptionRecord(docket_id=docket.id, kind="open_incident"))
    return found


def _apply_control_review_filters(
    session: Session,
    *,
    context: SessionContext,
    listing: IpDocketListResponse,
    filters: dict[str, object],
) -> IpDocketListResponse:
    """Apply the complete v1 filter contract to an access-scoped population."""

    included_ids = {row.id for row in listing.dockets}
    excluded_ids = set(filters.get("exclude_docket_ids", []))
    if unknown_ids := sorted(excluded_ids - included_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "ip_control_review_filter_invalid",
                "message": (
                    "exclude_docket_ids must reference records in the caller's "
                    "full access-scoped docket population."
                ),
                "invalid_count": len(unknown_ids),
            },
        )

    team_value = filters.get("team")
    team_matter_ids: set[str] | None = None
    if team_value is not None:
        team = session.scalar(
            select(Team).where(
                Team.company_id == context.company.id,
                Team.is_active.is_(True),
                or_(Team.id == team_value, Team.slug == team_value),
            )
        )
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "ip_control_review_filter_invalid",
                    "message": "team must identify an active team in this workspace.",
                },
            )
        team_matter_ids = set(
            session.scalars(
                select(Matter.id).where(
                    Matter.company_id == context.company.id,
                    Matter.team_id == team.id,
                )
            ).all()
        )

    filtered = [
        row
        for row in listing.dockets
        if row.id not in excluded_ids
        and (team_matter_ids is None or row.matter_id in team_matter_ids)
    ]
    return IpDocketListResponse(dockets=filtered, count=len(filtered))


def _stored_control_review_snapshot(row: IpDocketControlReview) -> IpControlReviewSnapshot:
    payload = dict(row.report_snapshot_json or {})
    if (
        not payload
        or row.snapshot_schema_version not in {1, CONTROL_REVIEW_SNAPSHOT_SCHEMA_VERSION}
        or payload.get("schema_version") != row.snapshot_schema_version
        or payload.get("query_version") != row.query_version
        or _sha256_json(payload) != row.manifest_sha256
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "ip_control_review_snapshot_integrity_failed",
                "message": "Stored control-review evidence failed its integrity check.",
            },
        )
    return IpControlReviewSnapshot.model_validate(payload)


def _exception_key(docket_id: str, kind: str) -> str:
    return f"{docket_id}:{kind}"


def _control_review_policy(row: IpDocketControlReview) -> IpControlReviewPolicy:
    payload = dict(row.review_policy_json or {})
    if payload:
        return IpControlReviewPolicy.model_validate(payload)
    return IpControlReviewPolicy(
        policy_version="legacy-single-signature-v1",
        required_signature_count=row.required_signature_count,
        required_sample_size=row.required_sample_size,
        distinct_preparer_and_reviewer=row.required_signature_count > 1,
    )


def _control_review_children(
    session: Session,
    *,
    row: IpDocketControlReview,
) -> tuple[
    list[IpControlReviewExceptionDecision],
    list[IpControlReviewSampleEvidence],
    list[IpControlReviewSignature],
]:
    decisions = list(
        session.scalars(
            select(IpControlReviewExceptionDecision)
            .where(
                IpControlReviewExceptionDecision.company_id == row.company_id,
                IpControlReviewExceptionDecision.review_id == row.id,
            )
            .order_by(
                IpControlReviewExceptionDecision.docket_id,
                IpControlReviewExceptionDecision.exception_kind,
            )
        ).all()
    )
    samples = list(
        session.scalars(
            select(IpControlReviewSampleEvidence)
            .where(
                IpControlReviewSampleEvidence.company_id == row.company_id,
                IpControlReviewSampleEvidence.review_id == row.id,
            )
            .order_by(
                IpControlReviewSampleEvidence.sampled_at,
                IpControlReviewSampleEvidence.id,
            )
        ).all()
    )
    signatures = list(
        session.scalars(
            select(IpControlReviewSignature)
            .where(
                IpControlReviewSignature.company_id == row.company_id,
                IpControlReviewSignature.review_id == row.id,
            )
            .order_by(IpControlReviewSignature.sequence)
        ).all()
    )
    return decisions, samples, signatures


def _review_record(session: Session, row: IpDocketControlReview) -> IpControlReviewRecord:
    snapshot = _stored_control_review_snapshot(row)
    decisions, samples, signatures = _control_review_children(session, row=row)
    decision_keys = {_exception_key(item.docket_id, item.exception_kind) for item in decisions}
    exception_keys = {
        _exception_key(item.docket_id, item.kind) for item in snapshot.mandatory_exceptions
    }
    pending_exception_count = len(exception_keys - decision_keys)
    policy = _control_review_policy(row)
    if row.signed_off_at is not None:
        signoff_status = "signed"
    elif signatures:
        signoff_status = "awaiting_second_signature"
    else:
        signoff_status = "draft"
    return IpControlReviewRecord(
        id=row.id,
        generated_at=snapshot.generated_at,
        filters=snapshot.filters,
        freshness=snapshot.freshness,
        completeness_status=row.completeness_status,
        incompleteness_reasons=snapshot.incompleteness_reasons,
        mandatory_exceptions=snapshot.mandatory_exceptions,
        query_version=row.query_version,
        manifest_sha256=row.manifest_sha256,
        export_status=row.export_status,
        export_error_redacted=row.export_error_redacted,
        signer_label_snapshot=row.signer_label_snapshot,
        signed_off_at=row.signed_off_at,
        review_policy=policy,
        predecessor_review_id=row.predecessor_review_id,
        delta=IpControlReviewDelta.model_validate(row.delta_json or {}),
        exception_decisions=[
            IpControlReviewExceptionDecisionRecord(
                docket_id=item.docket_id,
                exception_kind=item.exception_kind,
                disposition=item.disposition,
                annotation=item.annotation,
                evidence_reference=item.evidence_reference,
                decided_by_membership_id=item.decided_by_membership_id,
                decided_at=item.decided_at,
            )
            for item in decisions
        ],
        reviewer_samples=[
            IpControlReviewSampleRecord(
                docket_id=item.docket_id,
                reviewer_membership_id=item.reviewer_membership_id,
                source_evidence_reference=item.source_evidence_reference,
                calculation_evidence_reference=item.calculation_evidence_reference,
                coverage_evidence_reference=item.coverage_evidence_reference,
                notes=item.notes,
                sampled_at=item.sampled_at,
            )
            for item in samples
        ],
        signatures=[
            IpControlReviewSignatureRecord(
                signer_membership_id=item.signer_membership_id,
                signer_role=item.signer_role,
                signer_label_snapshot=item.signer_label_snapshot,
                attestation=item.attestation,
                manifest_sha256=item.manifest_sha256,
                sequence=item.sequence,
                signed_at=item.signed_at,
            )
            for item in signatures
        ],
        pending_exception_count=pending_exception_count,
        annotated_exception_count=sum(item.disposition == "annotated" for item in decisions),
        signoff_status=signoff_status,
        version=row.version,
        report=snapshot.report,
        snapshot=snapshot,
    )


def _control_review_delta(
    session: Session,
    *,
    context: SessionContext,
    filters: dict[str, object],
    included_records: list[dict[str, object]],
    exceptions: list[IpControlExceptionRecord],
    accessible_docket_ids: set[str],
) -> IpControlReviewDelta:
    """Link to the latest comparable signed report without crossing access scope."""

    candidates = list(
        session.scalars(
            select(IpDocketControlReview)
            .where(
                IpDocketControlReview.company_id == context.company.id,
                IpDocketControlReview.signed_off_at.is_not(None),
            )
            .order_by(IpDocketControlReview.generated_at.desc())
        ).all()
    )
    predecessor: IpDocketControlReview | None = None
    predecessor_snapshot: IpControlReviewSnapshot | None = None
    for candidate in candidates:
        if dict(candidate.filters_json or {}) != filters:
            continue
        candidate_snapshot = _stored_control_review_snapshot(candidate)
        candidate_ids = {item.docket_id for item in candidate_snapshot.included_records} | {
            item.docket_id for item in candidate_snapshot.mandatory_exceptions
        }
        if candidate_ids.issubset(accessible_docket_ids):
            predecessor = candidate
            predecessor_snapshot = candidate_snapshot
            break

    if predecessor is None or predecessor_snapshot is None:
        return IpControlReviewDelta()

    previous = {item.docket_id: item.sha256 for item in predecessor_snapshot.included_records}
    current = {str(item["docket_id"]): str(item["sha256"]) for item in included_records}
    previous_exceptions = {
        _exception_key(item.docket_id, item.kind)
        for item in predecessor_snapshot.mandatory_exceptions
    }
    current_exceptions = {_exception_key(item.docket_id, item.kind) for item in exceptions}
    return IpControlReviewDelta(
        predecessor_review_id=predecessor.id,
        predecessor_manifest_sha256=predecessor.manifest_sha256,
        added_docket_ids=sorted(current.keys() - previous.keys()),
        removed_docket_ids=sorted(previous.keys() - current.keys()),
        changed_docket_ids=sorted(
            docket_id
            for docket_id in current.keys() & previous.keys()
            if current[docket_id] != previous[docket_id]
        ),
        added_exception_keys=sorted(current_exceptions - previous_exceptions),
        removed_exception_keys=sorted(previous_exceptions - current_exceptions),
    )


def create_ip_control_review(
    session: Session,
    *,
    context: SessionContext,
    payload: IpControlReviewCreateRequest,
) -> IpControlReviewRecord:
    """Produce a daily docket control review that can later be signed off.

    Freshness and completeness are recorded up front: a stale source or a failed
    query makes the review ``incomplete``, and an incomplete review can never be
    signed off (UJ-59-EXC-01). Mandatory exceptions are captured from the
    access-filtered listing and stored on the review, so no later filter or bulk
    dismissal can hide them (CAL-OPS-13).
    """

    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )

    reasons: list[str] = []
    for source in sorted({s.strip() for s in payload.stale_sources if s.strip()}):
        reasons.append(f"stale_source:{source}")
    for query in sorted({q.strip() for q in payload.failed_queries if q.strip()}):
        reasons.append(f"failed_query:{query}")

    filters = payload.filters.model_dump(
        mode="json",
        exclude_none=True,
        exclude_defaults=True,
    )
    now = _now()
    freshness = {
        "stale_sources": sorted({s.strip() for s in payload.stale_sources if s.strip()}),
        "failed_queries": sorted({q.strip() for q in payload.failed_queries if q.strip()}),
        "observed_at": now.isoformat(),
    }
    full_listing = list_ip_dockets(session, context=context)
    exceptions = _control_exceptions(
        session,
        context=context,
        listing=full_listing,
    )
    listing = _apply_control_review_filters(
        session,
        context=context,
        listing=full_listing,
        filters=filters,
    )
    report = _ip_docket_control_report_from_listing(
        session,
        context=context,
        listing=listing,
        generated_at=now,
    )
    included_records = sorted(
        (
            {
                "docket_id": docket.id,
                "current_version": docket.current_version,
                "sha256": _sha256_json(docket.model_dump(mode="json")),
            }
            for docket in listing.dockets
        ),
        key=lambda item: item["docket_id"],
    )
    policy = IpControlReviewPolicy(
        policy_version=CONTROL_REVIEW_POLICY_VERSION,
        required_signature_count=2,
        required_sample_size=1 if included_records else 0,
        distinct_preparer_and_reviewer=True,
    )
    delta = _control_review_delta(
        session,
        context=context,
        filters=filters,
        included_records=included_records,
        exceptions=exceptions,
        accessible_docket_ids={row.id for row in full_listing.dockets},
    )
    snapshot = IpControlReviewSnapshot(
        schema_version=CONTROL_REVIEW_SNAPSHOT_SCHEMA_VERSION,
        query_version=CONTROL_REVIEW_QUERY_VERSION,
        generated_at=now,
        timezone=context.company.timezone,
        filters=filters,
        freshness=freshness,
        hidden_restricted_count_policy=CONTROL_REVIEW_RESTRICTED_COUNT_POLICY,
        included_records=included_records,
        report=report,
        mandatory_exceptions=exceptions,
        incompleteness_reasons=reasons,
        review_policy=policy,
        delta=delta,
    )
    snapshot_json = snapshot.model_dump(mode="json")
    manifest = _sha256_json(snapshot_json)

    row = IpDocketControlReview(
        company_id=context.company.id,
        generated_at=now,
        filters_json=filters,
        freshness_json=freshness,
        completeness_status="incomplete" if reasons else "complete",
        incompleteness_reasons_json=reasons,
        mandatory_exception_ids_json=[item.model_dump(mode="json") for item in exceptions],
        query_version=CONTROL_REVIEW_QUERY_VERSION,
        snapshot_schema_version=CONTROL_REVIEW_SNAPSHOT_SCHEMA_VERSION,
        report_snapshot_json=snapshot_json,
        manifest_sha256=manifest,
        review_policy_json=policy.model_dump(mode="json"),
        required_signature_count=policy.required_signature_count,
        required_sample_size=policy.required_sample_size,
        predecessor_review_id=delta.predecessor_review_id,
        delta_json=delta.model_dump(mode="json"),
        export_status="not_requested",
        version=1,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip.control_review.generated",
        target_type="ip_docket_control_review",
        target_id=row.id,
        metadata={
            "completeness_status": row.completeness_status,
            "incompleteness_reasons": reasons,
            "mandatory_exception_count": len(exceptions),
            "manifest_sha256": manifest,
        },
    )
    session.commit()
    session.refresh(row)
    return _review_record(session, row)


def _review_or_404(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
    for_update: bool = False,
) -> IpDocketControlReview:
    statement = select(IpDocketControlReview).where(
        IpDocketControlReview.id == review_id,
        IpDocketControlReview.company_id == context.company.id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="Control review not found.")
    snapshot = _stored_control_review_snapshot(row)
    visible_ids = {docket.id for docket in list_ip_dockets(session, context=context).dockets}
    protected_ids = _control_review_protected_ids(snapshot)
    if not protected_ids.issubset(visible_ids):
        # A stored report can reveal identifiers and workload facts. Losing
        # access to any included record therefore hides the whole artifact.
        raise HTTPException(status_code=404, detail="Control review not found.")
    return row


def _control_review_protected_ids(snapshot: IpControlReviewSnapshot) -> set[str]:
    return {item.docket_id for item in snapshot.included_records} | {
        item.docket_id for item in snapshot.mandatory_exceptions
    }


def list_ip_control_reviews(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 20,
) -> IpControlReviewListResponse:
    """Return recent reviews only when every frozen record remains visible."""

    visible_ids = {docket.id for docket in list_ip_dockets(session, context=context).dockets}
    rows = session.scalars(
        select(IpDocketControlReview)
        .where(IpDocketControlReview.company_id == context.company.id)
        .order_by(IpDocketControlReview.generated_at.desc(), IpDocketControlReview.id.desc())
    )
    reviews: list[IpControlReviewRecord] = []
    for row in rows:
        snapshot = _stored_control_review_snapshot(row)
        if not _control_review_protected_ids(snapshot).issubset(visible_ids):
            continue
        reviews.append(_review_record(session, row))
        if len(reviews) >= limit:
            break
    return IpControlReviewListResponse(reviews=reviews)


def get_ip_control_review(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
) -> IpControlReviewRecord:
    row = _review_or_404(session, context=context, review_id=review_id)
    return _review_record(session, row)


def record_ip_control_review_export(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
    payload: IpControlReviewExportRequest,
) -> IpControlReviewRecord:
    """UJ-59-EXC-03 — a failed export must not leave the review signable."""

    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )
    row = _review_or_404(session, context=context, review_id=review_id, for_update=True)
    _stored_control_review_snapshot(row)
    _decisions, _samples, signatures = _control_review_children(session, row=row)
    if row.signed_off_at is not None or signatures:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A control review with a signature cannot be re-exported.",
        )
    row.export_status = payload.outcome
    row.export_error_redacted = payload.error_redacted if payload.outcome == "failed" else None
    row.version += 1
    record_from_context(
        session,
        context,
        action="ip.control_review.export_recorded",
        target_type="ip_docket_control_review",
        target_id=row.id,
        metadata={"outcome": payload.outcome},
    )
    session.commit()
    session.refresh(row)
    return _review_record(session, row)


def decide_ip_control_review_exception(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
    docket_id: str,
    exception_kind: str,
    payload: IpControlReviewExceptionDecisionRequest,
) -> IpControlReviewRecord:
    """Record one immutable manager decision against a frozen exception."""

    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )
    row = _review_or_404(session, context=context, review_id=review_id, for_update=True)
    snapshot = _stored_control_review_snapshot(row)
    if row.version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Control review changed; reload before recording the decision.",
        )
    decisions, _samples, signatures = _control_review_children(session, row=row)
    if row.signed_off_at is not None or signatures:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Exception evidence cannot change after signing begins.",
        )
    key = _exception_key(docket_id, exception_kind)
    allowed = {_exception_key(item.docket_id, item.kind) for item in snapshot.mandatory_exceptions}
    if key not in allowed:
        raise HTTPException(status_code=404, detail="Control-review exception not found.")
    if any(
        item.docket_id == docket_id and item.exception_kind == exception_kind for item in decisions
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This control-review exception already has immutable evidence.",
        )

    decision = IpControlReviewExceptionDecision(
        company_id=context.company.id,
        review_id=row.id,
        docket_id=docket_id,
        exception_kind=exception_kind,
        disposition=payload.disposition,
        annotation=payload.annotation.strip(),
        evidence_reference=payload.evidence_reference.strip(),
        decided_by_membership_id=context.membership.id,
        decided_at=_now(),
    )
    session.add(decision)
    row.version += 1
    record_from_context(
        session,
        context,
        action="ip.control_review.exception_decided",
        target_type="ip_docket_control_review",
        target_id=row.id,
        metadata={
            "exception_key": key,
            "disposition": decision.disposition,
            "manifest_sha256": row.manifest_sha256,
        },
    )
    session.commit()
    session.refresh(row)
    return _review_record(session, row)


def record_ip_control_review_sample(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
    payload: IpControlReviewSampleRequest,
) -> IpControlReviewRecord:
    """Persist one second-reviewer source/calculation/coverage sample."""

    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:approve",
    )
    row = _review_or_404(session, context=context, review_id=review_id, for_update=True)
    snapshot = _stored_control_review_snapshot(row)
    if row.version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Control review changed; reload before recording the sample.",
        )
    _decisions, samples, signatures = _control_review_children(session, row=row)
    if row.signed_off_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A signed-off control review cannot receive reviewer samples.",
        )
    if context.membership.id == row.created_by_membership_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The preparer cannot supply the independent reviewer sample.",
        )
    if any(item.signer_role == "reviewer" for item in signatures):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reviewer evidence cannot change after the reviewer signs.",
        )
    if payload.docket_id not in {item.docket_id for item in snapshot.included_records}:
        raise HTTPException(status_code=404, detail="Sampled docket not found in this review.")
    if any(
        item.docket_id == payload.docket_id and item.reviewer_membership_id == context.membership.id
        for item in samples
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This reviewer already sampled that docket.",
        )

    sample = IpControlReviewSampleEvidence(
        company_id=context.company.id,
        review_id=row.id,
        docket_id=payload.docket_id,
        reviewer_membership_id=context.membership.id,
        source_evidence_reference=payload.source_evidence_reference.strip(),
        calculation_evidence_reference=payload.calculation_evidence_reference.strip(),
        coverage_evidence_reference=payload.coverage_evidence_reference.strip(),
        notes=payload.notes.strip() if payload.notes else None,
        sampled_at=_now(),
    )
    session.add(sample)
    row.version += 1
    record_from_context(
        session,
        context,
        action="ip.control_review.sample_recorded",
        target_type="ip_docket_control_review",
        target_id=row.id,
        metadata={
            "docket_id": payload.docket_id,
            "manifest_sha256": row.manifest_sha256,
        },
    )
    session.commit()
    session.refresh(row)
    return _review_record(session, row)


def sign_off_ip_control_review(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
    payload: IpControlReviewSignOffRequest,
) -> IpControlReviewRecord:
    """CAL-OPS-09 sign-off, refused unless the review is genuinely clean."""

    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:approve",
    )
    row = _review_or_404(session, context=context, review_id=review_id, for_update=True)
    snapshot = _stored_control_review_snapshot(row)
    if row.version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Control review changed; reload before signing off.",
        )
    decisions, samples, signatures = _control_review_children(session, row=row)
    if row.signed_off_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Control review is already signed off.",
        )
    if row.completeness_status != "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_control_review_incomplete",
                "message": "An incomplete control review cannot be signed off.",
                "incompleteness_reasons": list(row.incompleteness_reasons_json or []),
            },
        )
    if row.export_status == "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_control_review_export_failed",
                "message": "Export generation failed; the review cannot be marked complete.",
            },
        )
    decision_keys = {_exception_key(item.docket_id, item.exception_kind) for item in decisions}
    exception_keys = {
        _exception_key(item.docket_id, item.kind) for item in snapshot.mandatory_exceptions
    }
    pending_exception_keys = sorted(exception_keys - decision_keys)
    if pending_exception_keys:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_control_review_exceptions_unresolved",
                "message": (
                    "Mandatory exceptions require explicit resolution evidence before sign-off."
                ),
                "mandatory_exception_count": len(pending_exception_keys),
            },
        )

    policy = _control_review_policy(row)
    if len(signatures) >= policy.required_signature_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Control review already has every required signature.",
        )
    if any(item.signer_membership_id == context.membership.id for item in signatures):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The same reviewer cannot sign a control review twice.",
        )

    sequence = len(signatures) + 1
    signer_role = "preparer" if sequence == 1 else "reviewer"
    if signer_role == "preparer" and (
        row.created_by_membership_id is not None
        and context.membership.id != row.created_by_membership_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The control-review preparer must provide the first signature.",
        )
    if signer_role == "reviewer":
        if context.membership.id == row.created_by_membership_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The second signature must come from an independent reviewer.",
            )
        sample_count = len(
            {
                item.docket_id
                for item in samples
                if item.reviewer_membership_id == context.membership.id
            }
        )
        if sample_count < policy.required_sample_size:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_control_review_sample_required",
                    "message": (
                        "The second reviewer must record the required sample before signing."
                    ),
                    "required_sample_size": policy.required_sample_size,
                    "recorded_sample_size": sample_count,
                },
            )

    signed_at = _now()
    signature = IpControlReviewSignature(
        company_id=context.company.id,
        review_id=row.id,
        signer_membership_id=context.membership.id,
        signer_role=signer_role,
        signer_label_snapshot=context.user.full_name or context.user.email,
        attestation=payload.attestation.strip(),
        manifest_sha256=row.manifest_sha256,
        sequence=sequence,
        signed_at=signed_at,
    )
    session.add(signature)
    if sequence == policy.required_signature_count:
        row.signed_off_by_membership_id = context.membership.id
        row.signer_label_snapshot = signature.signer_label_snapshot
        row.signed_off_at = signed_at
    row.version += 1
    record_from_context(
        session,
        context,
        action=(
            "ip.control_review.signed_off"
            if row.signed_off_at is not None
            else "ip.control_review.signature_recorded"
        ),
        target_type="ip_docket_control_review",
        target_id=row.id,
        metadata={
            "signer_role": signer_role,
            "signature_sequence": sequence,
            "manifest_sha256": row.manifest_sha256,
            "mandatory_exception_count": len(row.mandatory_exception_ids_json or []),
        },
    )
    session.commit()
    session.refresh(row)
    return _review_record(session, row)


def ip_daily_docket(
    session: Session,
    *,
    context: SessionContext,
    filters: dict | None = None,
    stale_sources: list[str] | None = None,
) -> IpDailyDocketResponse:
    """The daily docket a docketing manager triages (UJ-50).

    Read-derived from the access-filtered docket listing, so restricted work
    contributes neither a queue entry nor a count (UJ-50-EXC-01).

    Three rules carry the journey's acceptance — that a manager can identify
    every critical item without side spreadsheets or hidden logs:

    * an inactive owner escalates to the named backup, or is reported ``unowned``
      when there is none (UJ-50-EXC-02);
    * an unacknowledged critical item escalates rather than sitting quietly
      (UJ-50-EXC-04);
    * when a source is stale the affected counts are ``None``, never ``0``, so
      unknown work is never rendered as no work (UJ-50-EXC-03).
    """

    stale = sorted({s.strip() for s in (stale_sources or []) if s.strip()})
    counts_complete = not stale
    applied_filters = dict(filters or {})
    listing = _apply_control_review_filters(
        session,
        context=context,
        listing=list_ip_dockets(session, context=context),
        filters=applied_filters,
    )
    listed_docket_ids = {docket.id for docket in listing.dockets}
    operational_coverage_ids = set(
        session.scalars(
            select(IpDeadlineCoverage.id)
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.id == IpDeadlineCoverage.docket_id,
                    IpDocketRecord.company_id == IpDeadlineCoverage.company_id,
                ),
            )
            .join(
                MatterDeadline,
                and_(
                    MatterDeadline.id == IpDeadlineCoverage.matter_deadline_id,
                    MatterDeadline.company_id == IpDeadlineCoverage.company_id,
                ),
            )
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                IpDeadlineCoverage.docket_id.in_(listed_docket_ids or {""}),
                IpDeadlineCoverage.coverage_status.notin_(_TERMINAL_COVERAGE_STATUSES),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(_TERMINAL_DOCKET_STATUSES),
                MatterDeadline.status.in_((MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
                or_(
                    and_(
                        MatterDeadline.ip_docket_id == IpDocketRecord.id,
                        MatterDeadline.matter_id.is_(None),
                    ),
                    and_(
                        IpDocketRecord.matter_id.is_not(None),
                        MatterDeadline.matter_id == IpDocketRecord.matter_id,
                        MatterDeadline.ip_docket_id.is_(None),
                    ),
                ),
            )
        ).all()
    )

    memberships = {
        row.id: row
        for row in session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(CompanyMembership.company_id == context.company.id)
        ).all()
    }

    # Criticality lives on the legal deadline, joined through the operational
    # deadline the coverage projects to.
    critical_matter_deadline_ids = {
        row
        for row in session.scalars(
            select(IpDeadline.matter_deadline_id).where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.is_critical.is_(True),
                IpDeadline.matter_deadline_id.is_not(None),
            )
        ).all()
        if row
    }

    assigned: dict[str, int] = {}
    critical: dict[str, int] = {}
    unacknowledged: dict[str, int] = {}
    escalations: list[IpDailyDocketEscalation] = []

    for docket in listing.dockets:
        for coverage in docket.deadline_coverages:
            # SQL already verifies the exact linked deadline and its
            # operational state. Completed/cancelled/neutralized children stay
            # historical even if their coverage row itself remains nonterminal.
            if coverage.id not in operational_coverage_ids:
                continue
            owner_id = coverage.responsible_membership_id
            is_critical = coverage.matter_deadline_id in critical_matter_deadline_ids
            assigned[owner_id] = assigned.get(owner_id, 0) + 1
            if is_critical:
                critical[owner_id] = critical.get(owner_id, 0) + 1

            owner = memberships.get(owner_id)
            owner_active = bool(owner and owner.is_active and owner.user.is_active)
            acknowledged = coverage.coverage_status == "accepted" and coverage.accepted_at

            if not acknowledged:
                unacknowledged[owner_id] = unacknowledged.get(owner_id, 0) + 1

            if not owner_active:
                backup = memberships.get(coverage.backup_membership_id or "")
                backup_ok = bool(backup and backup.is_active and backup.user.is_active)
                escalations.append(
                    IpDailyDocketEscalation(
                        coverage_id=coverage.id,
                        docket_id=docket.id,
                        reason="owner_inactive" if backup_ok else "unowned",
                        critical=is_critical,
                        escalate_to_membership_id=backup.id if backup_ok else None,
                    )
                )
            elif is_critical and not acknowledged:
                backup = memberships.get(coverage.backup_membership_id or "")
                backup_ok = bool(backup and backup.is_active and backup.user.is_active)
                escalations.append(
                    IpDailyDocketEscalation(
                        coverage_id=coverage.id,
                        docket_id=docket.id,
                        reason="unacknowledged_critical",
                        critical=True,
                        escalate_to_membership_id=backup.id if backup_ok else None,
                    )
                )

    queues: list[IpDailyDocketQueue] = []
    for membership_id in sorted(assigned):
        member = memberships.get(membership_id)
        active = bool(member and member.is_active and member.user.is_active)
        queues.append(
            IpDailyDocketQueue(
                membership_id=membership_id,
                label=((member.user.full_name or member.user.email) if member else membership_id),
                active=active,
                capacity_state="available" if active else "unavailable",
                # Unknown work must not render as no work.
                assigned_count=assigned[membership_id] if counts_complete else None,
                critical_count=critical.get(membership_id, 0) if counts_complete else None,
                unacknowledged_count=(
                    unacknowledged.get(membership_id, 0) if counts_complete else None
                ),
            )
        )

    escalations.sort(key=lambda item: (not item.critical, item.reason, item.coverage_id))
    return IpDailyDocketResponse(
        generated_at=_now(),
        filters=applied_filters,
        stale_sources=stale,
        counts_are_complete=counts_complete,
        queues=queues,
        escalations=escalations,
    )


def _aware_utc(value):
    """Normalize a possibly-naive timestamp for comparison."""

    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _coverage_roles(
    row: IpDeadlineCoverage,
    *,
    membership_id: str,
) -> list[str]:
    """Return the exact roles ``membership_id`` holds on one coverage row."""

    roles: list[str] = []
    if row.responsible_membership_id == membership_id:
        roles.append("responsible")
    if row.backup_membership_id == membership_id:
        roles.append("backup")
    return roles


def _backup_replacement_conflicts(
    rows: list[IpDeadlineCoverage],
    *,
    source_membership_id: str,
    replacement_membership_id: str,
) -> list[IpDeadlineCoverage]:
    """Rows where a replacement would occupy both coverage roles.

    The collision can happen in either direction: replacing a backup with the
    current primary, or replacing the primary with the current backup. Both
    must be refused before a proposal or immediate transfer mutates any row.
    """

    return [
        row
        for row in rows
        if (
            row.responsible_membership_id == source_membership_id
            and row.backup_membership_id == source_membership_id
        )
        or (
            row.backup_membership_id == source_membership_id
            and row.responsible_membership_id == replacement_membership_id
        )
        or (
            row.responsible_membership_id == source_membership_id
            and row.backup_membership_id == replacement_membership_id
        )
    ]


def _assert_distinct_backup_replacement(
    rows: list[IpDeadlineCoverage],
    *,
    source_membership_id: str,
    replacement_membership_id: str,
) -> None:
    conflicts = _backup_replacement_conflicts(
        rows,
        source_membership_id=source_membership_id,
        replacement_membership_id=replacement_membership_id,
    )
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_distinct_backup_required",
                "message": (
                    "The proposed replacement already holds the other coverage role "
                    "on affected deadlines; choose a distinct backup."
                ),
                "blocked_coverage_ids": [row.id for row in conflicts],
                "blocked_docket_ids": sorted({row.docket_id for row in conflicts}),
            },
        )


def _assert_distinct_escalation_backups(
    rows: list[IpDeadlineCoverage],
    *,
    source_membership_id: str,
    escalation_membership_id: str,
    replacement_membership_id: str,
) -> None:
    """Refuse a fallback that cannot take responsibility after a decline."""

    for row in rows:
        if row.responsible_membership_id == source_membership_id:
            assert_distinct_deadline_escalation(
                escalation_membership_id=escalation_membership_id,
                backup_membership_id=row.backup_membership_id,
                responsible_membership_id=replacement_membership_id,
            )


def _coverage_preview_roles(
    rows: list[IpDeadlineCoverage],
    *,
    membership_id: str,
) -> dict[str, list[str]]:
    return {row.id: _coverage_roles(row, membership_id=membership_id) for row in rows}


def _coverage_preview_token(
    rows: list[IpDeadlineCoverage],
    *,
    membership_id: str,
) -> str:
    """An atomic snapshot of the coverage set being transferred (CAL-OPS-08).

    Any concurrent change to any affected row alters the token, so a transfer
    built on a stale preview is refused rather than partially applied.
    """

    parts = sorted(
        f"{row.id}:{row.reassignment_version}:{row.responsible_membership_id}"
        f":{row.backup_membership_id or ''}:{row.replacement_decision}:"
        f"{','.join(_coverage_roles(row, membership_id=membership_id))}"
        for row in rows
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _coverages_for_member(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    for_update: bool = False,
    include_auxiliary_roles: bool = False,
) -> list[IpDeadlineCoverage]:
    if for_update:
        rows, _dockets = _lock_operational_coverages_for_member(
            session,
            context=context,
            membership_id=membership_id,
        )
        return rows

    # A preview is an actionable surface too. Filter the parent and deadline
    # lifecycle in SQL so a legacy non-terminal coverage row under a disposed
    # parent cannot appear transferable.
    membership_predicate = or_(
        IpDeadlineCoverage.responsible_membership_id == membership_id,
        IpDeadlineCoverage.backup_membership_id == membership_id,
    )
    if include_auxiliary_roles:
        membership_predicate = or_(
            membership_predicate,
            and_(
                IpDeadlineCoverage.pending_replacement_membership_id == membership_id,
                IpDeadlineCoverage.replacement_decision == "pending",
            ),
            and_(
                IpDeadlineCoverage.emergency_escalation_membership_id == membership_id,
                or_(
                    and_(
                        IpDeadlineCoverage.pending_replacement_membership_id.is_not(None),
                        IpDeadlineCoverage.replacement_decision == "pending",
                        IpDeadlineCoverage.pending_replacement_membership_id
                        == IpDeadlineCoverage.responsible_membership_id,
                    ),
                    and_(
                        IpDeadlineCoverage.coverage_status == "emergency",
                        IpDeadlineCoverage.emergency_until.is_not(None),
                        IpDeadlineCoverage.emergency_until > _now(),
                    ),
                ),
            ),
        )
    return list(
        session.scalars(
            select(IpDeadlineCoverage)
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.id == IpDeadlineCoverage.docket_id,
                    IpDocketRecord.company_id == IpDeadlineCoverage.company_id,
                ),
            )
            .join(
                MatterDeadline,
                and_(
                    MatterDeadline.id == IpDeadlineCoverage.matter_deadline_id,
                    MatterDeadline.company_id == IpDeadlineCoverage.company_id,
                ),
            )
            .outerjoin(
                Matter,
                and_(
                    Matter.id == IpDocketRecord.matter_id,
                    Matter.company_id == IpDocketRecord.company_id,
                ),
            )
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                membership_predicate,
                IpDeadlineCoverage.coverage_status.notin_(_TERMINAL_COVERAGE_STATUSES),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(_TERMINAL_DOCKET_STATUSES),
                MatterDeadline.status.in_((MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.id.is_not(None),
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
                or_(
                    and_(
                        MatterDeadline.ip_docket_id == IpDocketRecord.id,
                        MatterDeadline.matter_id.is_(None),
                    ),
                    and_(
                        IpDocketRecord.matter_id.is_not(None),
                        MatterDeadline.matter_id == IpDocketRecord.matter_id,
                        MatterDeadline.ip_docket_id.is_(None),
                    ),
                ),
            )
            .order_by(IpDeadlineCoverage.id)
        ).all()
    )


def _lock_operational_coverages_for_member(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
) -> tuple[list[IpDeadlineCoverage], list[IpDocketRecord]]:
    """Lock transferable coverage in parent-to-child order and revalidate it.

    Candidate discovery is deliberately lock-free: it finds lifecycle parents
    without first owning a child lock. The authoritative pass then locks sorted
    Matter rows, sorted docket rows, sorted operational-deadline rows, and
    finally sorted coverage rows.
    ``populate_existing`` discards identity-map snapshots taken by previews or
    earlier reads. Only refreshed, operational children are returned.
    """

    candidate_rows = session.execute(
        select(
            IpDeadlineCoverage.id,
            IpDeadlineCoverage.docket_id,
            IpDeadlineCoverage.matter_deadline_id,
        )
        .where(
            IpDeadlineCoverage.company_id == context.company.id,
            or_(
                IpDeadlineCoverage.responsible_membership_id == membership_id,
                IpDeadlineCoverage.backup_membership_id == membership_id,
            ),
            IpDeadlineCoverage.coverage_status.notin_(_TERMINAL_COVERAGE_STATUSES),
        )
        .order_by(IpDeadlineCoverage.id)
    ).all()
    if not candidate_rows:
        return [], []

    target_candidate_ids = sorted(
        {coverage_id for coverage_id, _docket_id, _deadline_id in candidate_rows}
    )
    deadline_ids = sorted({deadline_id for _coverage_id, _docket_id, deadline_id in candidate_rows})
    # A schema-valid deadline can be shared by multiple docket coverages. Lock
    # every sibling parent and coverage in the same global order before any
    # cutover so opposite-owner bulk requests cannot take sibling child locks
    # in reverse order. The release remains fail-closed for this ambiguous
    # projection shape.
    all_candidate_rows = session.execute(
        select(
            IpDeadlineCoverage.id,
            IpDeadlineCoverage.docket_id,
            IpDeadlineCoverage.matter_deadline_id,
        )
        .where(
            IpDeadlineCoverage.company_id == context.company.id,
            IpDeadlineCoverage.matter_deadline_id.in_(deadline_ids),
            IpDeadlineCoverage.coverage_status.notin_(_TERMINAL_COVERAGE_STATUSES),
        )
        .order_by(IpDeadlineCoverage.id)
    ).all()
    candidate_ids = sorted(
        {coverage_id for coverage_id, _docket_id, _deadline_id in all_candidate_rows}
    )
    docket_ids = sorted({docket_id for _coverage_id, docket_id, _deadline_id in all_candidate_rows})
    docket_parent_rows = session.execute(
        select(IpDocketRecord.id, IpDocketRecord.matter_id).where(
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.id.in_(docket_ids),
        )
    ).all()
    matter_ids = sorted(
        {matter_id for _docket_id, matter_id in docket_parent_rows if matter_id is not None}
    )

    locked_matters = (
        list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == context.company.id,
                    Matter.id.in_(matter_ids),
                )
                .order_by(Matter.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        if matter_ids
        else []
    )
    locked_dockets = list(
        session.scalars(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.company_id == context.company.id,
                IpDocketRecord.id.in_(docket_ids),
            )
            .order_by(IpDocketRecord.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    legal_deadlines = _lock_legal_deadlines_for_operational_deadlines(
        session,
        company_id=context.company.id,
        matter_deadline_ids=deadline_ids,
    )
    if any(
        legal_deadline.docket_id not in docket_ids for legal_deadline in legal_deadlines.values()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IP legal-deadline projection changed; reload and retry.",
        )
    locked_deadlines = list(
        session.scalars(
            select(MatterDeadline)
            .where(
                MatterDeadline.company_id == context.company.id,
                MatterDeadline.id.in_(deadline_ids),
            )
            .order_by(MatterDeadline.id)
            .with_for_update(of=MatterDeadline)
            .execution_options(populate_existing=True)
        ).all()
    )
    locked_coverages = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                IpDeadlineCoverage.id.in_(candidate_ids),
                IpDeadlineCoverage.coverage_status.notin_(_TERMINAL_COVERAGE_STATUSES),
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    matters_by_id = {matter.id: matter for matter in locked_matters}
    dockets_by_id = {docket.id: docket for docket in locked_dockets}
    deadlines_by_id = {deadline.id: deadline for deadline in locked_deadlines}

    operational_coverages = [
        row
        for row in locked_coverages
        if (docket := dockets_by_id.get(row.docket_id)) is not None
        and _coverage_child_is_operational(
            row,
            docket=docket,
            deadline=deadlines_by_id.get(row.matter_deadline_id),
            matter=matters_by_id.get(docket.matter_id) if docket.matter_id else None,
        )
    ]
    operational_by_deadline: dict[str, list[str]] = {}
    for row in operational_coverages:
        operational_by_deadline.setdefault(row.matter_deadline_id, []).append(row.id)
    shared = {
        deadline_id: coverage_ids
        for deadline_id, coverage_ids in operational_by_deadline.items()
        if len(coverage_ids) > 1
    }
    if shared:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_shared_deadline_handoff_required",
                "message": (
                    "A shared operational deadline needs a group handoff workflow "
                    "before responsibility can change."
                ),
                "shared_deadlines": shared,
            },
        )
    operational_rows = [
        row
        for row in operational_coverages
        if row.id in target_candidate_ids
        and (
            row.responsible_membership_id == membership_id
            or row.backup_membership_id == membership_id
        )
    ]
    operational_docket_ids = {row.docket_id for row in operational_rows}
    return operational_rows, [
        docket for docket in locked_dockets if docket.id in operational_docket_ids
    ]


def _queue_scope(row: IpDocketQueue) -> str:
    return "team" if row.team_id else "personal"


def _serialize_queue(row: IpDocketQueue) -> IpDocketQueueRecord:
    return IpDocketQueueRecord(
        id=row.id,
        name=row.name,
        description=row.description,
        filters=dict(row.filters_json or {}),
        team_id=row.team_id,
        owner_membership_id=row.owner_membership_id,
        scope=_queue_scope(row),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _caller_team_ids(session: Session, *, context: SessionContext) -> set[str]:
    return {
        team_id
        for team_id in session.scalars(
            select(TeamMembership.team_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(
                Team.company_id == context.company.id,
                TeamMembership.membership_id == context.membership.id,
            )
        ).all()
    }


def save_ip_docket_queue(
    session: Session,
    *,
    context: SessionContext,
    payload: IpDocketQueueSaveRequest,
) -> IpDocketQueueRecord:
    """Save a named daily-docket queue (CAL-OPS-09).

    A team queue may only be saved by a member of that team: sharing a view
    into a team's workload is a disclosure, not a preference.
    """

    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )

    if payload.team_id is not None:
        team = session.scalar(
            select(Team).where(
                Team.id == payload.team_id,
                Team.company_id == context.company.id,
            )
        )
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found.")
        if payload.team_id not in _caller_team_ids(session, context=context):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a member of the team can save a queue for it.",
            )

    existing = session.scalar(
        select(IpDocketQueue).where(
            IpDocketQueue.company_id == context.company.id,
            IpDocketQueue.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_docket_queue_name_taken",
                "message": "A queue with this name already exists in this workspace.",
            },
        )

    row = IpDocketQueue(
        company_id=context.company.id,
        name=payload.name,
        description=payload.description,
        filters_json=dict(payload.filters),
        team_id=payload.team_id,
        # A team queue is still attributed, so it can be governed and cleaned up.
        owner_membership_id=None if payload.team_id else context.membership.id,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    record_from_context(
        session,
        context,
        action="ip_docket_queue.saved",
        target_type="ip_docket_queue",
        target_id=row.id,
        metadata={"name": row.name, "scope": _queue_scope(row), "team_id": row.team_id},
    )
    session.commit()
    session.refresh(row)
    return _serialize_queue(row)


def list_ip_docket_queues(
    session: Session,
    *,
    context: SessionContext,
) -> IpDocketQueueListResponse:
    """Queues the caller may use: their own, plus their teams'."""

    team_ids = _caller_team_ids(session, context=context)
    rows = list(
        session.scalars(
            select(IpDocketQueue)
            .where(
                IpDocketQueue.company_id == context.company.id,
                or_(
                    IpDocketQueue.owner_membership_id == context.membership.id,
                    IpDocketQueue.team_id.in_(team_ids) if team_ids else false(),
                ),
            )
            .order_by(IpDocketQueue.name)
        ).all()
    )
    return IpDocketQueueListResponse(queues=[_serialize_queue(row) for row in rows])


def delete_ip_docket_queue(
    session: Session,
    *,
    context: SessionContext,
    queue_id: str,
) -> None:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )
    row = session.scalar(
        select(IpDocketQueue)
        .where(
            IpDocketQueue.id == queue_id,
            IpDocketQueue.company_id == context.company.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Queue not found.")
    if row.team_id:
        if row.team_id not in _caller_team_ids(session, context=context):
            raise HTTPException(status_code=404, detail="Queue not found.")
    elif row.owner_membership_id != context.membership.id:
        # Someone else's personal queue is not theirs to know about either.
        raise HTTPException(status_code=404, detail="Queue not found.")

    record_from_context(
        session,
        context,
        action="ip_docket_queue.deleted",
        target_type="ip_docket_queue",
        target_id=row.id,
        metadata={"name": row.name, "scope": _queue_scope(row)},
    )
    session.delete(row)
    session.commit()


def _coverage_lifecycle_is_operational(
    coverage: IpDeadlineCoverage,
    *,
    docket: IpDocketRecord,
    matter: Matter | None,
) -> bool:
    """Check the durable coverage and parent lifecycle state.

    Lifecycle transitions intentionally retain coverage as historical evidence.
    Reopening a parent only makes the parent available for new work; it must not
    revive a child neutralized by an earlier terminal transition.
    """

    if coverage.coverage_status in _TERMINAL_COVERAGE_STATUSES:
        return False
    if (
        not docket.is_active
        or docket.archived_by_matter_disposal
        or docket.status in _TERMINAL_DOCKET_STATUSES
    ):
        return False
    if docket.matter_id is not None and (matter is None or not matter_is_operational(matter)):
        return False
    return True


def _coverage_child_is_operational(
    coverage: IpDeadlineCoverage,
    *,
    docket: IpDocketRecord,
    deadline: MatterDeadline | None,
    matter: Matter | None,
) -> bool:
    """Fail closed for every read/write that presents coverage as actionable."""

    if not _coverage_lifecycle_is_operational(
        coverage,
        docket=docket,
        matter=matter,
    ):
        return False
    if deadline is None or deadline.id != coverage.matter_deadline_id:
        return False
    docket_owned = deadline.matter_id is None and deadline.ip_docket_id == docket.id
    matter_owned = (
        docket.matter_id is not None
        and deadline.matter_id == docket.matter_id
        and deadline.ip_docket_id is None
    )
    if not docket_owned and not matter_owned:
        return False
    return _deadline_is_operational(deadline)


def _coverage_action_statement(session: Session, *, context: SessionContext):
    """Base query for bounded, access-scoped personal coverage queues.

    Visibility and lifecycle predicates live in SQL so a caller with years of
    history cannot make Today load every coverage row and issue one access query
    per docket before the response cap is applied.
    """

    return (
        select(
            IpDeadlineCoverage,
            IpDocketRecord,
            MatterDeadline,
            IpDeadline.is_critical.label("is_critical"),
        )
        .select_from(IpDeadlineCoverage)
        .join(
            IpDocketRecord,
            and_(
                IpDocketRecord.id == IpDeadlineCoverage.docket_id,
                IpDocketRecord.company_id == IpDeadlineCoverage.company_id,
            ),
        )
        .join(
            MatterDeadline,
            and_(
                MatterDeadline.id == IpDeadlineCoverage.matter_deadline_id,
                MatterDeadline.company_id == IpDeadlineCoverage.company_id,
            ),
        )
        .outerjoin(
            Matter,
            and_(
                Matter.id == IpDocketRecord.matter_id,
                Matter.company_id == IpDocketRecord.company_id,
            ),
        )
        .outerjoin(
            IpDeadline,
            and_(
                IpDeadline.matter_deadline_id == MatterDeadline.id,
                IpDeadline.company_id == IpDeadlineCoverage.company_id,
            ),
        )
        .where(
            IpDeadlineCoverage.company_id == context.company.id,
            IpDeadlineCoverage.coverage_status.notin_(_TERMINAL_COVERAGE_STATUSES),
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            IpDocketRecord.status.notin_(_TERMINAL_DOCKET_STATUSES),
            MatterDeadline.status.in_((MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)),
            MatterDeadline.neutralized_at.is_(None),
            MatterDeadline.cancelled_by_matter_disposal.is_(False),
            or_(
                IpDocketRecord.matter_id.is_(None),
                and_(
                    Matter.id.is_not(None),
                    Matter.is_active.is_(True),
                    Matter.status.notin_(("disposed", "closed")),
                ),
            ),
            or_(
                and_(
                    MatterDeadline.ip_docket_id == IpDocketRecord.id,
                    MatterDeadline.matter_id.is_(None),
                ),
                and_(
                    IpDocketRecord.matter_id.is_not(None),
                    MatterDeadline.matter_id == IpDocketRecord.matter_id,
                    MatterDeadline.ip_docket_id.is_(None),
                ),
            ),
            visible_ip_dockets_filter(session, context=context),
        )
    )


def bulk_acknowledge_ip_coverage(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCoverageBulkAcknowledgeRequest,
) -> IpCoverageBulkAcknowledgeResponse:
    """Acknowledge many assigned deadlines at once (CAL-OPS-09).

    Acknowledgement is what stops a critical item escalating, so it must be a
    real act by the person who holds the work: this only ever acknowledges rows
    where the caller is the responsible member, which is why it is entitled to
    write ``accepted_at``.

    Validation is **per record and partial by design**. Acknowledging is not a
    security boundary — a caller can only acknowledge their own work — so
    failing all fifty because one row moved would be worse than reporting that
    one. Every requested id is reported back, so a dropped row can never be
    mistaken for an acknowledged one. This is the opposite of the transfer
    path, where handing a restricted record to the wrong person *is* a boundary
    and the whole batch fails closed.
    """

    requested = list(dict.fromkeys(payload.coverage_ids))
    actor_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={context.membership.id},
    )
    locked_actor = actor_memberships.get(context.membership.id)
    if locked_actor is None or not locked_actor.is_active or not locked_actor.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active company membership is required to acknowledge coverage.",
        )
    require_locked_membership_capability(session, locked_actor, "ip:write")
    context = SessionContext(
        company=context.company,
        membership=locked_actor,
        user=locked_actor.user,
    )

    # Discover ids only, then acquire the shared lifecycle lock order:
    # Matter -> docket -> MatterDeadline -> coverage. A parent disposal or a
    # deadline completion therefore either wins and is observed on the refreshed
    # pass, or waits until this acknowledgement commits.
    candidate_refs = session.execute(
        select(
            IpDeadlineCoverage.id,
            IpDeadlineCoverage.docket_id,
            IpDeadlineCoverage.matter_deadline_id,
        ).where(
            IpDeadlineCoverage.id.in_(requested),
            IpDeadlineCoverage.company_id == context.company.id,
        )
    ).all()
    candidate_docket_ids = {row.docket_id for row in candidate_refs}
    candidate_deadline_ids = {row.matter_deadline_id for row in candidate_refs}
    discovered_dockets = session.execute(
        select(IpDocketRecord.id, IpDocketRecord.matter_id).where(
            IpDocketRecord.id.in_(candidate_docket_ids or {""}),
            IpDocketRecord.company_id == context.company.id,
        )
    ).all()
    matter_ids = {matter_id for _docket_id, matter_id in discovered_dockets if matter_id}
    matters = {
        matter.id: matter
        for matter in session.scalars(
            select(Matter)
            .where(
                Matter.id.in_(matter_ids or {""}),
                Matter.company_id == context.company.id,
            )
            .order_by(Matter.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    }
    dockets = {
        docket.id: docket
        for docket in session.scalars(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.id.in_(candidate_docket_ids or {""}),
                IpDocketRecord.company_id == context.company.id,
            )
            .order_by(IpDocketRecord.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    }
    deadlines = {
        deadline.id: deadline
        for deadline in session.scalars(
            select(MatterDeadline)
            .where(
                MatterDeadline.id.in_(candidate_deadline_ids or {""}),
                MatterDeadline.company_id == context.company.id,
            )
            .order_by(MatterDeadline.id)
            .with_for_update(of=MatterDeadline)
            .execution_options(populate_existing=True)
        ).all()
    }
    rows = {
        row.id: row
        for row in session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.id.in_(requested),
                IpDeadlineCoverage.company_id == context.company.id,
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    }
    visible_docket_ids = set(
        session.scalars(
            select(IpDocketRecord.id).where(
                IpDocketRecord.id.in_(candidate_docket_ids or {""}),
                IpDocketRecord.company_id == context.company.id,
                visible_ip_dockets_filter(session, context=context),
            )
        ).all()
    )

    now = _now()
    outcomes: list[IpCoverageAcknowledgeOutcome] = []
    acknowledged_ids: list[str] = []

    for coverage_id in requested:
        row = rows.get(coverage_id)
        docket = dockets.get(row.docket_id) if row else None
        if row is None or docket is None or docket.id not in visible_docket_ids:
            # A record the caller cannot open is reported as absent, never as a
            # record they may not touch — that would confirm it exists.
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id, acknowledged=False, reason="not_found"
                )
            )
            continue
        if not _coverage_child_is_operational(
            row,
            docket=docket,
            deadline=deadlines.get(row.matter_deadline_id),
            matter=matters.get(docket.matter_id) if docket.matter_id else None,
        ):
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="inactive_lifecycle",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue
        if row.responsible_membership_id != context.membership.id:
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="not_responsible",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue
        expected = payload.expected_versions.get(coverage_id)
        if expected is not None and row.reassignment_version != expected:
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="version_conflict",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue
        if row.replacement_decision == "pending":
            # An outstanding transfer is a decision, not an acknowledgement;
            # acknowledging around it would bury the choice.
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="transfer_pending",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue
        if row.coverage_status == "accepted" and row.accepted_at is not None:
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="already_acknowledged",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue

        row.coverage_status = "accepted"
        row.accepted_at = now
        row.updated_at = now
        acknowledged_ids.append(coverage_id)
        outcomes.append(
            IpCoverageAcknowledgeOutcome(
                coverage_id=coverage_id,
                acknowledged=True,
                reason="acknowledged",
                reassignment_version=row.reassignment_version,
            )
        )

    if acknowledged_ids:
        record_from_context(
            session,
            context,
            action="ip_deadline_coverage.bulk_acknowledged",
            target_type="company_membership",
            target_id=context.membership.id,
            metadata={
                "coverage_ids": acknowledged_ids,
                "requested_count": len(requested),
                "rejected_count": len(requested) - len(acknowledged_ids),
            },
        )
    session.commit()
    return IpCoverageBulkAcknowledgeResponse(
        acknowledged_count=len(acknowledged_ids),
        rejected_count=len(requested) - len(acknowledged_ids),
        outcomes=outcomes,
    )


def list_ip_assigned_coverage(
    session: Session,
    *,
    context: SessionContext,
    unacknowledged_only: bool = False,
    actionable_only: bool = False,
    limit: int | None = None,
) -> IpAssignedCoverageListResponse:
    """The caller's own deadlines (CAL-OPS-09).

    The daily docket counts each member's workload; this returns the work
    itself, so the count can be acted on rather than only read. Restricted
    records the caller cannot open are excluded, exactly as the counts are.
    """

    statement = _coverage_action_statement(session, context=context).where(
        IpDeadlineCoverage.responsible_membership_id == context.membership.id,
    )
    if unacknowledged_only:
        statement = statement.where(
            or_(
                IpDeadlineCoverage.coverage_status != "accepted",
                IpDeadlineCoverage.accepted_at.is_(None),
            )
        )
    if actionable_only:
        statement = statement.where(IpDeadlineCoverage.replacement_decision != "pending")
    statement = statement.order_by(
        MatterDeadline.due_on,
        IpDocketRecord.title,
        IpDeadlineCoverage.id,
    )
    if limit is not None:
        statement = statement.limit(max(0, limit))

    today = _now().date()
    records: list[IpAssignedCoverageRecord] = []
    for row, docket, deadline, is_critical in session.execute(statement).all():
        acknowledged = row.coverage_status == "accepted" and row.accepted_at is not None
        due_on = deadline.due_on
        records.append(
            IpAssignedCoverageRecord(
                coverage_id=row.id,
                docket_id=docket.id,
                docket_title=docket.title,
                docket_identifier=docket.primary_identifier,
                deadline_title=getattr(deadline, "title", None),
                due_on=due_on,
                days_until_due=(due_on - today).days if due_on else None,
                critical=bool(is_critical),
                acknowledged=acknowledged,
                coverage_status=row.coverage_status,
                transfer_pending=row.replacement_decision == "pending",
                reassignment_version=row.reassignment_version,
            )
        )
    return IpAssignedCoverageListResponse(coverages=records)


def list_ip_coverage_transfers_awaiting(
    session: Session,
    *,
    context: SessionContext,
    limit: int | None = None,
) -> IpCoverageTransfersAwaitingResponse:
    """Coverage transfers waiting on the calling member (CAL-OPS-08).

    A proposal is addressed to one person, so it is listed for that person
    rather than found by opening each docket. Access is re-checked at read
    time: a grant can be withdrawn after a transfer is proposed, and a record
    the reader may no longer open must not surface here.
    """

    statement = (
        _coverage_action_statement(session, context=context)
        .where(
            IpDeadlineCoverage.pending_replacement_membership_id == context.membership.id,
            IpDeadlineCoverage.replacement_decision == "pending",
        )
        .order_by(
            MatterDeadline.due_on,
            IpDocketRecord.title,
            IpDeadlineCoverage.id,
        )
    )
    if limit is not None:
        statement = statement.limit(max(0, limit))
    rows = list(session.execute(statement).all())
    if not rows:
        return IpCoverageTransfersAwaitingResponse()

    member_ids = {
        membership_id
        for row, _docket, _deadline, _critical in rows
        for membership_id in (
            row.responsible_membership_id,
            row.emergency_escalation_membership_id,
        )
        if membership_id
    }
    members = {
        member.id: member
        for member in session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.id.in_(member_ids or {""}),
            )
        ).all()
    }

    def _label(membership_id: str | None) -> str | None:
        if membership_id is None:
            return None
        member = members.get(membership_id)
        if member is None:
            return membership_id
        return member.user.full_name or member.user.email

    today = _now().date()
    transfers: list[IpCoverageTransferAwaiting] = []
    for row, docket, deadline, is_critical in rows:
        due_on = deadline.due_on
        transfers.append(
            IpCoverageTransferAwaiting(
                coverage_id=row.id,
                docket_id=docket.id,
                docket_title=docket.title,
                docket_identifier=docket.primary_identifier,
                deadline_title=getattr(deadline, "title", None),
                due_on=due_on,
                days_until_due=(due_on - today).days if due_on else None,
                critical=bool(is_critical),
                # The work has already moved when the responsible member is the
                # reader; that only happens on an immediate transfer.
                transfer_kind=(
                    "immediate"
                    if row.responsible_membership_id == context.membership.id
                    else "proposed"
                ),
                responsible_membership_id=row.responsible_membership_id,
                responsible_label=_label(row.responsible_membership_id)
                or row.responsible_membership_id,
                escalation_membership_id=row.emergency_escalation_membership_id,
                escalation_label=_label(row.emergency_escalation_membership_id),
                reason=row.replacement_decision_reason,
                reassignment_version=row.reassignment_version,
            )
        )
    return IpCoverageTransfersAwaitingResponse(transfers=transfers)


def preview_ip_coverage_reassignment(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCoverageReassignPreviewRequest,
) -> IpCoverageReassignPreviewResponse:
    """UJ-57-NORMAL — the atomic preview CAL-OPS-08 requires before a transfer."""

    if payload.from_membership_id == payload.to_membership_id:
        raise HTTPException(status_code=422, detail="Coverage replacement must be different.")
    source = session.scalar(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user))
        .where(
            CompanyMembership.id == payload.from_membership_id,
            CompanyMembership.company_id == context.company.id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Company membership not found.")
    replacement = _membership_or_404(session, context, payload.to_membership_id)

    rows = _coverages_for_member(session, context=context, membership_id=payload.from_membership_id)
    dockets = list(
        session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_({row.docket_id for row in rows} or {""}),
                IpDocketRecord.company_id == context.company.id,
            )
        ).all()
    )
    # The access decision is part of the preview, not a surprise at commit.
    blocked = [
        docket.id
        for docket in dockets
        if not _membership_can_cover_docket(
            session,
            context=context,
            membership=replacement,
            docket=docket,
        )
    ]
    dockets_by_id = {docket.id: docket for docket in dockets}
    participant_ids = {
        membership_id
        for row in rows
        for membership_id in (
            row.responsible_membership_id,
            row.backup_membership_id,
        )
        if membership_id is not None
    }
    participants = {
        membership.id: membership
        for membership in session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.id.in_(participant_ids or {""}),
            )
        ).all()
    }
    for row in rows:
        docket = dockets_by_id.get(row.docket_id)
        if docket is None:
            blocked.append(row.docket_id)
            continue
        for membership_id in (
            row.responsible_membership_id,
            row.backup_membership_id,
        ):
            if membership_id is None:
                continue
            membership = participants.get(membership_id)
            if (
                membership is None
                or not membership.is_active
                or not membership.user.is_active
                or not _membership_can_cover_docket(
                    session,
                    context=context,
                    membership=membership,
                    docket=docket,
                )
            ):
                blocked.append(row.docket_id)
        deadline = session.get(MatterDeadline, row.matter_deadline_id)
        if (
            deadline is None
            or len(
                _operational_coverage_ids_for_deadline(
                    session,
                    company_id=context.company.id,
                    deadline=deadline,
                )
            )
            != 1
        ):
            blocked.append(row.docket_id)
    backup_conflicts = _backup_replacement_conflicts(
        rows,
        source_membership_id=payload.from_membership_id,
        replacement_membership_id=replacement.id,
    )
    blocked.extend(row.docket_id for row in backup_conflicts)
    blocked.extend(
        row.docket_id for row in rows if row.backup_membership_id == payload.from_membership_id
    )
    return IpCoverageReassignPreviewResponse(
        from_membership_id=payload.from_membership_id,
        to_membership_id=payload.to_membership_id,
        preview_token=_coverage_preview_token(rows, membership_id=payload.from_membership_id),
        affected_coverage_ids=[row.id for row in rows],
        affected_roles=_coverage_preview_roles(rows, membership_id=payload.from_membership_id),
        affected_docket_ids=sorted({row.docket_id for row in rows}),
        blocked_docket_ids=sorted(set(blocked)),
        transfer_allowed=not blocked,
    )


def propose_ip_coverage_reassignment(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCoverageReassignProposeRequest,
) -> IpCoverageReassignPreviewResponse:
    """Propose a transfer; ownership does not move until it is accepted.

    CAL-OPS-08 requires an accepted replacement or approved emergency coverage,
    so a proposal marks each row ``pending`` and leaves the current owner in
    place. Emergency cover transfers immediately but is time-boxed and must name
    an escalation owner.
    """

    if payload.from_membership_id == payload.to_membership_id:
        raise HTTPException(status_code=422, detail="Coverage replacement must be different.")
    emergency_until = payload.emergency_until
    if emergency_until is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_emergency_expiry_unavailable",
                "message": (
                    "Time-boxed emergency coverage is unavailable until an idempotent "
                    "expiry transition is enabled. Use a proposed or immediate transfer."
                ),
            },
        )
    if emergency_until is not None and payload.emergency_escalation_membership_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Emergency coverage requires an escalation owner.",
        )
    candidate_rows = _coverages_for_member(
        session,
        context=context,
        membership_id=payload.from_membership_id,
    )
    assignment_ids = {
        payload.from_membership_id,
        payload.to_membership_id,
        payload.emergency_escalation_membership_id if emergency_until is not None else None,
    }
    assignment_ids.update(
        membership_id
        for row in candidate_rows
        for membership_id in (
            row.responsible_membership_id,
            row.backup_membership_id,
            row.pending_replacement_membership_id,
            row.emergency_escalation_membership_id,
        )
        if membership_id is not None
    )
    memberships = _lock_assignment_memberships_or_404(
        session,
        context,
        membership_ids=assignment_ids,
        active_membership_ids={
            payload.to_membership_id,
            payload.emergency_escalation_membership_id,
        },
        required_capability="ip:write",
    )
    source = memberships[payload.from_membership_id]
    _assert_source_can_propose(source, transfer_mode="proposed")
    replacement = memberships[payload.to_membership_id]
    escalation = (
        memberships[payload.emergency_escalation_membership_id]
        if emergency_until is not None and payload.emergency_escalation_membership_id is not None
        else None
    )

    rows, dockets = _lock_operational_coverages_for_member(
        session,
        context=context,
        membership_id=payload.from_membership_id,
    )
    _assert_distinct_backup_replacement(
        rows,
        source_membership_id=payload.from_membership_id,
        replacement_membership_id=replacement.id,
    )
    backup_rows = [row for row in rows if row.backup_membership_id == payload.from_membership_id]
    if backup_rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_backup_handoff_required",
                "message": (
                    "Existing backup responsibility cannot be proposed for reassignment "
                    "without an accepted backup-handoff workflow."
                ),
                "blocked_coverage_ids": [row.id for row in backup_rows],
            },
        )
    # UJ-57-EXC-04: the preview must still describe reality.
    if (
        _coverage_preview_token(rows, membership_id=payload.from_membership_id)
        != payload.preview_token
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_preview_stale",
                "message": "Affected work changed after the preview; preview again.",
            },
        )

    _assert_replacement_can_cover(
        session, context=context, replacement=replacement, dockets=dockets
    )
    dockets_by_id = {docket.id: docket for docket in dockets}
    for row in rows:
        docket = dockets_by_id.get(row.docket_id)
        if docket is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Coverage participants changed; reload before reassignment.",
            )
        _assert_operational_coverage_participants(
            session,
            context=context,
            docket=docket,
            coverage_id=row.id,
            memberships=memberships,
            responsible_membership_id=row.responsible_membership_id,
            backup_membership_id=row.backup_membership_id,
        )
    if emergency_until is not None:
        if _aware_utc(emergency_until) <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Emergency coverage must expire in the future.",
            )
    if escalation is not None:
        responsible_docket_ids = {
            row.docket_id
            for row in rows
            if row.responsible_membership_id == payload.from_membership_id
        }
        _assert_replacement_can_cover(
            session,
            context=context,
            replacement=escalation,
            dockets=[docket for docket in dockets if docket.id in responsible_docket_ids],
        )
        _assert_distinct_escalation_backups(
            rows,
            source_membership_id=payload.from_membership_id,
            escalation_membership_id=escalation.id,
            replacement_membership_id=replacement.id,
        )

    affected_roles = _coverage_preview_roles(rows, membership_id=payload.from_membership_id)
    now = _now()
    for row in rows:
        roles = affected_roles[row.id]

        # Backup naming is an administrative assignment, not a transfer of
        # primary accountability. A backup-only row must retain its existing
        # responsible owner and must never create a responsibility decision.
        if "backup" in roles:
            row.backup_membership_id = replacement.id

        if "responsible" in roles:
            row.pending_replacement_membership_id = replacement.id
            row.replacement_decision_reason = payload.reason
            if emergency_until is not None:
                # UJ-57-EXC-05: emergency cover moves ownership now, but only until
                # it expires, and it always names who it escalates to.
                row.responsible_membership_id = replacement.id
                row.replacement_decision = "accepted"
                row.replacement_decided_at = now
                row.emergency_until = emergency_until
                row.emergency_escalation_membership_id = escalation.id if escalation else None
                row.coverage_status = "emergency"
            else:
                row.replacement_decision = "pending"
                row.replacement_decided_at = None
                row.emergency_until = None
                row.emergency_escalation_membership_id = None
                row.coverage_status = "transfer_pending"

        row.reassignment_version += 1
        row.updated_at = now

    record_from_context(
        session,
        context,
        action="ip_deadline_coverage.transfer_proposed",
        target_type="company_membership",
        target_id=payload.from_membership_id,
        metadata={
            "to_membership_id": replacement.id,
            "coverage_ids": [row.id for row in rows],
            "coverage_roles": affected_roles,
            "emergency": emergency_until is not None,
            "reason": payload.reason,
        },
    )
    session.commit()
    refreshed = _coverages_for_member(
        session, context=context, membership_id=payload.from_membership_id
    )
    return IpCoverageReassignPreviewResponse(
        from_membership_id=payload.from_membership_id,
        to_membership_id=replacement.id,
        preview_token=_coverage_preview_token(refreshed, membership_id=payload.from_membership_id),
        affected_coverage_ids=[row.id for row in rows],
        affected_roles=affected_roles,
        affected_docket_ids=sorted({row.docket_id for row in rows}),
        blocked_docket_ids=[],
        transfer_allowed=True,
    )


def decide_ip_coverage_replacement(
    session: Session,
    *,
    context: SessionContext,
    coverage_id: str,
    payload: IpCoverageReplacementDecisionRequest,
) -> IpDocketRecordResponse:
    """UJ-57-NORMAL / UJ-57-EXC-03 — the named replacement accepts or rejects."""

    candidate = session.execute(
        select(
            IpDeadlineCoverage.docket_id,
            IpDeadlineCoverage.matter_deadline_id,
            IpDeadlineCoverage.responsible_membership_id,
            IpDeadlineCoverage.backup_membership_id,
            IpDeadlineCoverage.pending_replacement_membership_id,
            IpDeadlineCoverage.emergency_escalation_membership_id,
            IpDeadlineCoverage.reassignment_version,
        ).where(
            IpDeadlineCoverage.id == coverage_id,
            IpDeadlineCoverage.company_id == context.company.id,
        )
    ).one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Deadline coverage not found.")
    assignment_ids = {
        context.membership.id,
        candidate.responsible_membership_id,
        candidate.backup_membership_id,
        candidate.pending_replacement_membership_id,
        candidate.emergency_escalation_membership_id,
    }
    required_active_ids = {context.membership.id}
    if (
        payload.decision == "rejected"
        and candidate.responsible_membership_id == context.membership.id
        and candidate.emergency_escalation_membership_id is not None
    ):
        required_active_ids.add(candidate.emergency_escalation_membership_id)
    memberships = _lock_assignment_memberships_or_404(
        session,
        context,
        membership_ids=assignment_ids,
        active_membership_ids=required_active_ids,
        required_capability="ip:write",
    )
    # Match lifecycle's lock order: the parent is authoritative and must win
    # before a child decision can mutate responsibility or status.
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=candidate.docket_id,
        for_update=True,
        required_capability="ip:write",
    )
    deadline = _lock_docket_deadline(
        session,
        docket=docket,
        deadline_id=candidate.matter_deadline_id,
    )
    row = session.scalar(
        select(IpDeadlineCoverage)
        .where(
            IpDeadlineCoverage.id == coverage_id,
            IpDeadlineCoverage.docket_id == docket.id,
            IpDeadlineCoverage.company_id == context.company.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Deadline coverage not found.")
    if (
        row.responsible_membership_id,
        row.backup_membership_id,
        row.pending_replacement_membership_id,
        row.emergency_escalation_membership_id,
        row.reassignment_version,
    ) != (
        candidate.responsible_membership_id,
        candidate.backup_membership_id,
        candidate.pending_replacement_membership_id,
        candidate.emergency_escalation_membership_id,
        candidate.reassignment_version,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_assignment_changed",
                "message": "Coverage assignments changed; reload before deciding.",
            },
        )
    matter = session.get(Matter, docket.matter_id) if docket.matter_id else None
    if not _coverage_lifecycle_is_operational(
        row,
        docket=docket,
        matter=matter,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_inactive_lifecycle",
                "message": "Lifecycle-neutralized coverage cannot accept a decision.",
            },
        )
    _assert_operational_coverage_deadline(deadline)
    if not _coverage_child_is_operational(
        row,
        docket=docket,
        deadline=deadline,
        matter=matter,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_inactive_lifecycle",
                "message": "Lifecycle-neutralized coverage cannot accept a decision.",
            },
        )
    _assert_single_operational_coverage_projection(
        session,
        company_id=context.company.id,
        deadline=deadline,
        coverage_id=row.id,
    )
    if row.replacement_decision != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No replacement decision is pending for this coverage.",
        )
    if row.pending_replacement_membership_id != context.membership.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the named replacement may decide this transfer.",
        )

    now = _now()
    previous_owner = row.responsible_membership_id
    previous_backup = row.backup_membership_id
    if payload.decision == "accepted":
        _assert_operational_coverage_participants(
            session,
            context=context,
            docket=docket,
            coverage_id=row.id,
            memberships=memberships,
            responsible_membership_id=context.membership.id,
            backup_membership_id=row.backup_membership_id,
        )
        # A legacy pending transfer may already name the current backup as its
        # replacement. Refuse that acceptance before changing responsibility;
        # silently deleting backup coverage is not a safe reconciliation.
        assert_distinct_deadline_coverage(
            responsible_membership_id=context.membership.id,
            backup_membership_id=row.backup_membership_id,
        )
        row.responsible_membership_id = context.membership.id
        row.coverage_status = "accepted"
        row.accepted_at = now
    elif row.responsible_membership_id == context.membership.id:
        # UJ-57-EXC-03, immediate transfer: the work is already theirs, so a
        # rejection cannot simply be declined in place, and it must not go back
        # to a person who has left. It escalates to the named owner.
        escalation_id = row.emergency_escalation_membership_id
        if escalation_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_coverage_no_escalation_owner",
                    "message": (
                        "This transfer has no escalation owner, so declining it would "
                        "leave the deadline unowned. Reassign it explicitly instead."
                    ),
                },
            )
        escalation = memberships[escalation_id]
        _assert_operational_coverage_participants(
            session,
            context=context,
            docket=docket,
            coverage_id=row.id,
            memberships=memberships,
            responsible_membership_id=escalation.id,
            backup_membership_id=row.backup_membership_id,
        )
        assert_distinct_deadline_escalation(
            escalation_membership_id=escalation.id,
            responsible_membership_id=context.membership.id,
            backup_membership_id=row.backup_membership_id,
        )
        assert_distinct_deadline_coverage(
            responsible_membership_id=escalation.id,
            backup_membership_id=row.backup_membership_id,
        )
        row.responsible_membership_id = escalation.id
        row.coverage_status = "escalated"
        row.accepted_at = None
        row.calendar_projection_status = "pending"
    else:
        # UJ-57-EXC-03: a rejection returns the work, it never leaves it unowned.
        # In proposed mode the original owner never stopped holding it.
        _assert_operational_coverage_participants(
            session,
            context=context,
            docket=docket,
            coverage_id=row.id,
            memberships=memberships,
            responsible_membership_id=row.responsible_membership_id,
            backup_membership_id=row.backup_membership_id,
        )
        row.coverage_status = "accepted" if row.accepted_at else "pending"
    row.replacement_decision = payload.decision
    row.replacement_decided_at = now
    if payload.reason is not None:
        # The field also carries the proposer's reason; an acceptance given
        # without a note must not erase why the transfer was asked for.
        row.replacement_decision_reason = payload.reason
    row.pending_replacement_membership_id = None
    row.emergency_until = None
    row.emergency_escalation_membership_id = None
    row.reassignment_version += 1
    row.updated_at = now
    should_reconcile_projection = (
        row.responsible_membership_id != previous_owner or payload.decision == "accepted"
    )
    if should_reconcile_projection:
        session.flush()
        cutover_ip_coverage_projection(
            session,
            context=context,
            docket=docket,
            coverage=row,
            previous_responsible_membership_id=previous_owner,
            previous_backup_membership_id=previous_backup,
            reason=payload.reason or row.replacement_decision_reason or "Coverage decision",
            replacement_source=(
                "replacement_accepted" if payload.decision == "accepted" else "decline_escalation"
            ),
            responsible_accepted_at=row.accepted_at,
            changed_at=now,
        )

    record_from_context(
        session,
        context,
        action=f"ip_deadline_coverage.transfer_{payload.decision}",
        target_type="ip_deadline_coverage",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "previous_responsible_membership_id": previous_owner,
            "responsible_membership_id": row.responsible_membership_id,
            "reason": payload.reason,
        },
    )
    session.commit()
    return _serialize_docket(session, docket, context=context)
