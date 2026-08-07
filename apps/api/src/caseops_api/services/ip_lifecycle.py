"""Canonical append-only IP event and parent lifecycle command contract."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    IpDeadlineCoverage,
    IpDocketEvent,
    IpDocketRecord,
    IpProceeding,
    IpRelatedRightObligation,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
    TrademarkApplication,
)
from caseops_api.schemas.ip_lifecycle import (
    IpDocketEventCreateRequest,
    IpLifecycleTransitionRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import can_access
from caseops_api.services.session_context import SessionContext

TERMINAL_IP_DOCKET_STATUSES = frozenset(
    {"archived", "abandoned", "transferred", "retired", "closed"}
)


def _authorized_lifecycle_docket(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    for_update: bool,
) -> IpDocketRecord:
    statement = select(IpDocketRecord).where(
        IpDocketRecord.id == docket_id,
        IpDocketRecord.company_id == context.company.id,
    )
    docket = session.scalar(statement)
    if docket is not None and for_update and docket.matter_id:
        # Matter is the access/lifecycle parent. Lock it before the IP child
        # so Matter disposal and direct IP transitions share one lock order.
        session.scalar(
            select(Matter)
            .where(
                Matter.id == docket.matter_id,
                Matter.company_id == context.company.id,
            )
            .with_for_update()
        )
    if docket is not None and for_update:
        docket = session.scalar(statement.with_for_update())
    if docket is None or docket.archived_by_matter_disposal:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    if docket.matter_id:
        matter = session.scalar(
            select(Matter).where(
                Matter.id == docket.matter_id,
                Matter.company_id == context.company.id,
            )
        )
        if matter is None or not can_access(session, context=context, matter=matter):
            raise HTTPException(status_code=404, detail="IP docket record not found.")
        if not matter.is_active:
            raise HTTPException(
                status_code=409,
                detail="The linked Matter is terminal; its dedicated lifecycle owns reopening.",
            )
    elif docket.restricted:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    return docket


def _active_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> CompanyMembership:
    row = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if row is None:
        raise HTTPException(
            status_code=422,
            detail="Responsible user is not an active tenant member.",
        )
    return row


def _owned_target(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    application_id: str | None,
    proceeding_id: str | None,
) -> None:
    if application_id is not None:
        application = session.scalar(
            select(TrademarkApplication).where(
                TrademarkApplication.id == application_id,
                TrademarkApplication.company_id == company_id,
                TrademarkApplication.docket_id == docket_id,
            )
        )
        if application is None:
            raise HTTPException(status_code=422, detail="Application is outside this docket.")
    if proceeding_id is not None:
        proceeding = session.scalar(
            select(IpProceeding).where(
                IpProceeding.id == proceeding_id,
                IpProceeding.company_id == company_id,
                IpProceeding.docket_id == docket_id,
            )
        )
        if proceeding is None:
            raise HTTPException(status_code=422, detail="Proceeding is outside this docket.")


def _prior_event(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    event_id: str | None,
    label: str,
) -> IpDocketEvent | None:
    if event_id is None:
        return None
    row = session.scalar(
        select(IpDocketEvent).where(
            IpDocketEvent.id == event_id,
            IpDocketEvent.company_id == company_id,
            IpDocketEvent.docket_id == docket_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=422, detail=f"{label} event is outside this docket.")
    return row


def _append_locked_event(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    payload: IpDocketEventCreateRequest,
) -> IpDocketEvent:
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    if not docket.is_active:
        raise HTTPException(
            status_code=409,
            detail="Terminal IP records are immutable; use the dedicated reopen transition.",
        )
    _active_membership(
        session,
        company_id=docket.company_id,
        membership_id=payload.responsible_membership_id,
    )
    _owned_target(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
    )
    _prior_event(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        event_id=payload.supersedes_event_id,
        label="Superseded",
    )
    _prior_event(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        event_id=payload.reconciles_event_id,
        label="Reconciled",
    )
    if payload.source == "registry" and payload.reconciles_event_id is None:
        if payload.candidate_status != "candidate":
            raise HTTPException(
                status_code=422,
                detail="New registry events must remain candidates until reconciled.",
            )
    next_sequence = (
        session.scalar(
            select(func.max(IpDocketEvent.sequence)).where(
                IpDocketEvent.company_id == docket.company_id,
                IpDocketEvent.docket_id == docket.id,
            )
        )
        or 0
    ) + 1
    row = IpDocketEvent(
        company_id=docket.company_id,
        docket_id=docket.id,
        sequence=next_sequence,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
        event_kind=payload.event_kind,
        source=payload.source,
        source_reference=payload.source_reference,
        effective_at=payload.effective_at,
        entered_at=datetime.now(UTC),
        responsible_membership_id=payload.responsible_membership_id,
        entered_by_membership_id=context.membership.id,
        reason=payload.reason,
        evidence_refs_json=payload.evidence_refs,
        document_refs_json=payload.document_refs,
        resulting_stage=payload.resulting_stage,
        resulting_deadline_refs_json=payload.resulting_deadline_refs,
        before_phase=payload.before_phase,
        after_phase=payload.after_phase,
        candidate_status=payload.candidate_status,
        supersedes_event_id=payload.supersedes_event_id,
        correction_reason=payload.correction_reason,
        reconciles_event_id=payload.reconciles_event_id,
        reconciliation_decision=payload.reconciliation_decision,
        payload_json=payload.payload,
    )
    session.add(row)
    session.flush()
    return row


def append_ip_docket_event(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDocketEventCreateRequest,
) -> IpDocketEvent:
    docket = _authorized_lifecycle_docket(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
    )
    row = _append_locked_event(session, context=context, docket=docket, payload=payload)
    record_from_context(
        session,
        context,
        action="ip_docket.event_appended",
        target_type="ip_docket_event",
        target_id=row.id,
        matter_id=docket.matter_id,
        metadata={
            "docket_id": docket.id,
            "sequence": row.sequence,
            "event_kind": row.event_kind,
            "source": row.source,
            "candidate_status": row.candidate_status,
            "supersedes_event_id": row.supersedes_event_id,
            "reconciles_event_id": row.reconciles_event_id,
        },
    )
    session.commit()
    session.refresh(row)
    return row


def transition_ip_docket_lifecycle(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpLifecycleTransitionRequest,
) -> tuple[IpDocketRecord, IpDocketEvent]:
    """Apply only the legal parent transition; IPLF-022B owns child-impact UI/routes."""

    docket = _authorized_lifecycle_docket(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
    )
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    was_terminal = docket.status in TERMINAL_IP_DOCKET_STATUSES
    will_be_terminal = payload.to_status in TERMINAL_IP_DOCKET_STATUSES
    if was_terminal == will_be_terminal:
        raise HTTPException(
            status_code=409,
            detail="Lifecycle transitions must cross the active/terminal boundary.",
        )
    if payload.successor_docket_id:
        successor = session.scalar(
            select(IpDocketRecord).where(
                IpDocketRecord.id == payload.successor_docket_id,
                IpDocketRecord.company_id == docket.company_id,
                IpDocketRecord.is_active.is_(True),
            )
        )
        if successor is None or successor.id == docket.id:
            raise HTTPException(status_code=422, detail="Successor must be another active docket.")

    before_status = docket.status
    next_version = docket.lifecycle_version + 1
    # Create the immutable transition fact while the parent is still active;
    # reopening creates the row directly because terminal ordinary appends are
    # deliberately forbidden.
    event_payload = IpDocketEventCreateRequest(
        expected_lifecycle_version=docket.lifecycle_version,
        event_kind="lifecycle_transition",
        source="manual",
        effective_at=payload.effective_at,
        responsible_membership_id=context.membership.id,
        reason=payload.reason,
        evidence_refs=[payload.evidence_ref],
        before_phase=before_status,
        after_phase=payload.to_status,
        payload={
            "outcome": payload.outcome,
            "successor_docket_id": payload.successor_docket_id,
            "reopen_without_child_resurrection": not will_be_terminal,
        },
    )
    if docket.is_active:
        event = _append_locked_event(
            session,
            context=context,
            docket=docket,
            payload=event_payload,
        )
    else:
        next_sequence = (
            session.scalar(
                select(func.max(IpDocketEvent.sequence)).where(
                    IpDocketEvent.company_id == docket.company_id,
                    IpDocketEvent.docket_id == docket.id,
                )
            )
            or 0
        ) + 1
        event = IpDocketEvent(
            company_id=docket.company_id,
            docket_id=docket.id,
            sequence=next_sequence,
            event_kind="lifecycle_transition",
            source="manual",
            effective_at=payload.effective_at,
            entered_at=datetime.now(UTC),
            responsible_membership_id=context.membership.id,
            entered_by_membership_id=context.membership.id,
            reason=payload.reason,
            evidence_refs_json=[payload.evidence_ref],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            before_phase=before_status,
            after_phase=payload.to_status,
            candidate_status="confirmed",
            payload_json=event_payload.payload,
        )
        session.add(event)
        session.flush()

    neutralized_coverages = 0
    neutralized_obligations = 0
    cancelled_deadlines = 0
    if will_be_terminal:
        coverages = list(
            session.scalars(
                select(IpDeadlineCoverage).where(
                    IpDeadlineCoverage.company_id == docket.company_id,
                    IpDeadlineCoverage.docket_id == docket.id,
                    IpDeadlineCoverage.coverage_status.notin_(("inactive_lifecycle", "completed")),
                )
            )
        )
        for coverage in coverages:
            coverage.coverage_status = "inactive_lifecycle"
            coverage.calendar_projection_status = "inactive_lifecycle"
            coverage.updated_at = datetime.now(UTC)
        neutralized_coverages = len(coverages)

        obligations = list(
            session.scalars(
                select(IpRelatedRightObligation).where(
                    IpRelatedRightObligation.company_id == docket.company_id,
                    IpRelatedRightObligation.docket_id == docket.id,
                    IpRelatedRightObligation.status.notin_(("completed", "cancelled_lifecycle")),
                )
            )
        )
        for obligation in obligations:
            obligation.status = "cancelled_lifecycle"
            obligation.updated_at = datetime.now(UTC)
        neutralized_obligations = len(obligations)

        deadline_ids = {
            row.matter_deadline_id
            for row in [*coverages, *obligations]
            if row.matter_deadline_id is not None
        }
        deadlines = (
            list(
                session.scalars(
                    select(MatterDeadline).where(
                        MatterDeadline.id.in_(deadline_ids),
                        MatterDeadline.status == MatterDeadlineStatus.OPEN,
                    )
                )
            )
            if deadline_ids
            else []
        )
        for deadline in deadlines:
            deadline.status = MatterDeadlineStatus.CANCELLED
            deadline.updated_at = datetime.now(UTC)
        cancelled_deadlines = len(deadlines)

    docket.status = payload.to_status
    docket.is_active = not will_be_terminal
    docket.lifecycle_version = next_version
    docket.lifecycle_effective_at = payload.effective_at
    docket.lifecycle_reason = payload.reason
    docket.lifecycle_outcome = payload.outcome
    docket.lifecycle_source = payload.source
    docket.lifecycle_evidence_ref = payload.evidence_ref
    docket.successor_docket_id = payload.successor_docket_id
    docket.updated_at = datetime.now(UTC)
    record_from_context(
        session,
        context,
        action="ip_docket.lifecycle_transitioned",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        metadata={
            "before_status": before_status,
            "after_status": docket.status,
            "lifecycle_version": docket.lifecycle_version,
            "event_id": event.id,
            "successor_docket_id": docket.successor_docket_id,
            "reopen_without_child_resurrection": not will_be_terminal,
            "neutralized_coverages": neutralized_coverages,
            "neutralized_obligations": neutralized_obligations,
            "cancelled_shared_deadlines": cancelled_deadlines,
        },
    )
    session.commit()
    session.refresh(docket)
    session.refresh(event)
    return docket, event


def list_ip_docket_events(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> list[IpDocketEvent]:
    _authorized_lifecycle_docket(
        session,
        context=context,
        docket_id=docket_id,
        for_update=False,
    )
    return list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == context.company.id,
                IpDocketEvent.docket_id == docket_id,
            )
            .order_by(IpDocketEvent.sequence)
        ).all()
    )
