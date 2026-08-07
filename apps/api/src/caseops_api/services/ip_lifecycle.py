"""Canonical append-only IP event and parent lifecycle command contract."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    IpDeadlineCoverage,
    IpDeadlineIncident,
    IpDocketEvent,
    IpDocketRecord,
    IpIdentifier,
    IpProceeding,
    IpRelatedRightObligation,
    IpTitleInterest,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
    TrademarkApplication,
)
from caseops_api.schemas.ip_lifecycle import (
    IpChecklistItem,
    IpDocketEventCreateRequest,
    IpDocketEventPreviewResponse,
    IpLifecycleImpactRow,
    IpLifecyclePreviewResponse,
    IpLifecycleTransitionRequest,
    IpProsecutionWorkspaceResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_records import assert_application_can_enter_filed_phase
from caseops_api.services.matter_access import can_access
from caseops_api.services.session_context import SessionContext

TERMINAL_IP_DOCKET_STATUSES = frozenset(
    {"archived", "abandoned", "transferred", "retired", "closed"}
)
TERMINAL_APPLICATION_PHASES = frozenset(
    {"refused", "abandoned", "withdrawn", "closed", "transferred"}
)
EVENT_PHASES = {
    "filing": "filed",
    "formalities": "formalities",
    "examination_report": "examination",
    "response": "response_filed",
    "show_cause_hearing": "hearing",
    "acceptance": "accepted",
    "publication": "published",
    "registration": "registered",
    "renewal": "renewed",
    "refusal": "refused",
    "abandonment": "abandoned",
    "restoration": "restored",
}


def _as_utc(value: datetime) -> datetime:
    """Normalize database datetimes across PostgreSQL and SQLite test storage."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
    for_update: bool,
) -> tuple[TrademarkApplication | None, IpProceeding | None]:
    application: TrademarkApplication | None = None
    proceeding: IpProceeding | None = None
    if application_id is not None:
        statement = select(TrademarkApplication).where(
            TrademarkApplication.id == application_id,
            TrademarkApplication.company_id == company_id,
            TrademarkApplication.docket_id == docket_id,
        )
        if for_update:
            statement = statement.with_for_update()
        application = session.scalar(statement)
        if application is None:
            raise HTTPException(status_code=422, detail="Application is outside this docket.")
    if proceeding_id is not None:
        statement = select(IpProceeding).where(
            IpProceeding.id == proceeding_id,
            IpProceeding.company_id == company_id,
            IpProceeding.docket_id == docket_id,
        )
        if for_update:
            statement = statement.with_for_update()
        proceeding = session.scalar(statement)
        if proceeding is None:
            raise HTTPException(status_code=422, detail="Proceeding is outside this docket.")
    return application, proceeding


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


def _payload_refs(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _event_checklist(payload: IpDocketEventCreateRequest) -> list[IpChecklistItem]:
    filing_like = payload.event_kind in {"filing", "response", "renewal"}
    form_refs = _payload_refs(payload.payload, "form_refs")
    fee_refs = _payload_refs(payload.payload, "fee_evidence_refs")
    approval_refs = _payload_refs(payload.payload, "approval_refs")
    exception_refs = _payload_refs(payload.payload, "unresolved_exceptions")
    return [
        IpChecklistItem(
            category="fact",
            key="event_contract",
            label="Typed event, source, date, and responsible user",
            required=True,
            satisfied=True,
        ),
        IpChecklistItem(
            category="document",
            key="document_evidence",
            label="Immutable document or evidence reference",
            required=filing_like,
            satisfied=bool(payload.document_refs or payload.evidence_refs),
            evidence_refs=[*payload.document_refs, *payload.evidence_refs],
        ),
        IpChecklistItem(
            category="form",
            key="form_evidence",
            label="Applicable form version/reference",
            required=filing_like,
            satisfied=bool(form_refs),
            evidence_refs=form_refs,
        ),
        IpChecklistItem(
            category="fee",
            key="fee_evidence",
            label="Official fee evidence or explicit no-fee basis",
            required=payload.event_kind in {"filing", "renewal"},
            satisfied=bool(fee_refs),
            evidence_refs=fee_refs,
        ),
        IpChecklistItem(
            category="approval",
            key="approval_evidence",
            label="Required legal approval reference",
            required=filing_like,
            satisfied=bool(approval_refs),
            evidence_refs=approval_refs,
        ),
        IpChecklistItem(
            category="exception",
            key="unresolved_exceptions",
            label="Unresolved exceptions remain explicit",
            required=False,
            satisfied=not exception_refs,
            evidence_refs=exception_refs,
        ),
    ]


def preview_ip_docket_event(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDocketEventCreateRequest,
) -> IpDocketEventPreviewResponse:
    docket = _authorized_lifecycle_docket(
        session,
        context=context,
        docket_id=docket_id,
        for_update=False,
    )
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    if not docket.is_active:
        raise HTTPException(status_code=409, detail="Terminal IP records cannot accept events.")
    application, proceeding = _owned_target(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
        for_update=False,
    )
    if application is not None and application.version != payload.expected_application_version:
        raise HTTPException(status_code=409, detail="Application version changed; reload.")
    if (
        application is not None
        and not application.is_active
        and payload.event_kind != "restoration"
    ):
        raise HTTPException(status_code=409, detail="Only restoration may reopen the application.")
    rows = list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == docket.company_id,
                IpDocketEvent.docket_id == docket.id,
            )
            .order_by(IpDocketEvent.sequence)
        )
    )
    current_phase = (
        application.filing_phase
        if application is not None
        else proceeding.stage
        if proceeding is not None
        else next((row.after_phase for row in reversed(rows) if row.after_phase), docket.status)
    )
    proposed_phase = payload.after_phase or EVENT_PHASES.get(payload.event_kind)
    duplicate_ids = [
        row.id
        for row in rows
        if row.event_kind == payload.event_kind
        and row.application_id == payload.application_id
        and row.proceeding_id == payload.proceeding_id
        and row.effective_at.date() == payload.effective_at.date()
        and row.candidate_status != "rejected"
    ]
    latest_effective = max((_as_utc(row.effective_at) for row in rows), default=None)
    backdated = (
        latest_effective is not None
        and _as_utc(payload.effective_at) < latest_effective
    )
    checklist = _event_checklist(payload)
    unresolved = [
        row.key for row in checklist if row.required and not row.satisfied
    ]
    if duplicate_ids and payload.reconciles_event_id is None:
        unresolved.append("duplicate_reconciliation_required")
    return IpDocketEventPreviewResponse(
        docket_id=docket.id,
        lifecycle_version=docket.lifecycle_version,
        current_phase=current_phase,
        proposed_phase=proposed_phase,
        backdated=backdated,
        recalculation_required=backdated or bool(payload.resulting_deadline_refs),
        duplicate_candidate_ids=duplicate_ids,
        checklist=checklist,
        unresolved_exception_codes=unresolved,
    )


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
    application, proceeding = _owned_target(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
        for_update=True,
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
    proposed_phase = payload.after_phase or EVENT_PHASES.get(payload.event_kind)
    before_phase = payload.before_phase
    apply_phase = not (
        payload.source == "registry"
        and payload.reconciles_event_id is None
        and payload.candidate_status == "candidate"
    )
    if application is not None:
        if application.version != payload.expected_application_version:
            raise HTTPException(status_code=409, detail="Application version changed; reload.")
        if not application.is_active and payload.event_kind != "restoration":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Terminal trademark applications are immutable; only a "
                    "dedicated restoration event may reopen them."
                ),
            )
        before_phase = application.filing_phase
        if proposed_phase is not None and apply_phase:
            if payload.event_kind == "filing":
                identifiers = list(
                    session.scalars(
                        select(IpIdentifier).where(
                            IpIdentifier.company_id == docket.company_id,
                            IpIdentifier.application_id == application.id,
                        )
                    )
                )
                assert_application_can_enter_filed_phase(application, identifiers)
            was_terminal = not application.is_active
            will_be_terminal = proposed_phase in TERMINAL_APPLICATION_PHASES
            application.filing_phase = proposed_phase
            application.is_active = not will_be_terminal
            if was_terminal != will_be_terminal:
                application.lifecycle_version += 1
            application.version += 1
            application.updated_at = datetime.now(UTC)
    elif proceeding is not None:
        before_phase = proceeding.stage
        if proposed_phase is not None and apply_phase:
            proceeding.stage = proposed_phase
            proceeding.version += 1
            proceeding.updated_at = datetime.now(UTC)
    next_sequence = (
        session.scalar(
            select(func.max(IpDocketEvent.sequence)).where(
                IpDocketEvent.company_id == docket.company_id,
                IpDocketEvent.docket_id == docket.id,
            )
        )
        or 0
    ) + 1
    checklist = _event_checklist(payload)
    event_payload = dict(payload.payload)
    event_payload["stage_checklist"] = [row.model_dump(mode="json") for row in checklist]
    event_payload["operational_completion"] = bool(
        _payload_refs(payload.payload, "task_refs")
    )
    event_payload["filing_evidence"] = bool(
        payload.event_kind in {"filing", "response"} and payload.document_refs
    )
    event_payload["registry_acceptance"] = bool(
        payload.source == "registry"
        and payload.event_kind in {"acceptance", "registration"}
        and payload.candidate_status in {"confirmed", "reconciled"}
    )
    event_payload["final_legal_disposition"] = bool(
        proposed_phase in TERMINAL_APPLICATION_PHASES
    )
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
        resulting_stage=payload.resulting_stage or proposed_phase,
        resulting_deadline_refs_json=payload.resulting_deadline_refs,
        before_phase=before_phase,
        after_phase=proposed_phase,
        candidate_status=payload.candidate_status,
        supersedes_event_id=payload.supersedes_event_id,
        correction_reason=payload.correction_reason,
        reconciles_event_id=payload.reconciles_event_id,
        reconciliation_decision=payload.reconciliation_decision,
        payload_json=event_payload,
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


def _lifecycle_impacts(
    session: Session,
    *,
    docket: IpDocketRecord,
    payload: IpLifecycleTransitionRequest,
) -> list[IpLifecycleImpactRow]:
    impacts: list[IpLifecycleImpactRow] = []
    for row in session.scalars(
        select(IpDeadlineCoverage).where(
            IpDeadlineCoverage.company_id == docket.company_id,
            IpDeadlineCoverage.docket_id == docket.id,
            IpDeadlineCoverage.coverage_status.notin_(("inactive_lifecycle", "completed")),
        )
    ):
        impacts.append(
            IpLifecycleImpactRow(
                impact_kind="coverage",
                record_id=row.id,
                current_state=row.coverage_status,
                proposed_outcome="inactive_lifecycle",
            )
        )
    for row in session.scalars(
        select(IpRelatedRightObligation).where(
            IpRelatedRightObligation.company_id == docket.company_id,
            IpRelatedRightObligation.docket_id == docket.id,
            IpRelatedRightObligation.status.notin_(("completed", "cancelled_lifecycle")),
        )
    ):
        impacts.append(
            IpLifecycleImpactRow(
                impact_kind="obligation",
                record_id=row.id,
                current_state=row.status,
                proposed_outcome="cancelled_lifecycle",
            )
        )
    for row in session.scalars(
        select(IpDeadlineIncident).where(
            IpDeadlineIncident.company_id == docket.company_id,
            IpDeadlineIncident.docket_id == docket.id,
            IpDeadlineIncident.status == "open",
        )
    ):
        impacts.append(
            IpLifecycleImpactRow(
                impact_kind="incident",
                record_id=row.id,
                current_state=row.status,
                proposed_outcome="retain_restricted_history",
                blocking=True,
                blocker_code=f"open_deadline_incident:{row.id}",
            )
        )
    for row in session.scalars(
        select(IpProceeding).where(
            IpProceeding.company_id == docket.company_id,
            IpProceeding.docket_id == docket.id,
            IpProceeding.proceeding_kind.in_(("appeal", "recordal")),
            IpProceeding.stage.notin_(("closed", "withdrawn", "disposed")),
        )
    ):
        impacts.append(
            IpLifecycleImpactRow(
                impact_kind="proceeding",
                record_id=row.id,
                current_state=row.stage,
                proposed_outcome="retain_with_qualified_closure",
                blocking=True,
                blocker_code=f"pending_{row.proceeding_kind}:{row.id}",
            )
        )
    for row in session.scalars(
        select(IpTitleInterest).where(
            IpTitleInterest.company_id == docket.company_id,
            IpTitleInterest.docket_id == docket.id,
            IpTitleInterest.recordal_status.in_(("pending", "filed")),
        )
    ):
        impacts.append(
            IpLifecycleImpactRow(
                impact_kind="recordal",
                record_id=row.id,
                current_state=row.recordal_status,
                proposed_outcome="retain_with_qualified_closure",
                blocking=True,
                blocker_code=f"pending_recordal:{row.id}",
            )
        )
    if docket.matter_id:
        impacts.append(
            IpLifecycleImpactRow(
                impact_kind="matter",
                record_id=docket.matter_id,
                current_state="linked",
                proposed_outcome=payload.linked_matter_handling,
                blocking=payload.linked_matter_handling == "retain",
                blocker_code=(
                    "linked_matter_review_required"
                    if payload.linked_matter_handling == "retain"
                    else None
                ),
            )
        )
    if payload.successor_docket_id:
        impacts.append(
            IpLifecycleImpactRow(
                impact_kind="successor",
                record_id=payload.successor_docket_id,
                current_state="active",
                proposed_outcome="relationship_and_redirect_preserved",
            )
        )
    return impacts


def preview_ip_docket_lifecycle(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpLifecycleTransitionRequest,
) -> IpLifecyclePreviewResponse:
    docket = _authorized_lifecycle_docket(
        session,
        context=context,
        docket_id=docket_id,
        for_update=False,
    )
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    impacts = _lifecycle_impacts(session, docket=docket, payload=payload)
    blocker_codes = [row.blocker_code for row in impacts if row.blocker_code]
    return IpLifecyclePreviewResponse(
        docket_id=docket.id,
        from_status=docket.status,
        to_status=payload.to_status,
        expected_lifecycle_version=docket.lifecycle_version,
        impacts=impacts,
        blocker_codes=blocker_codes,
        requires_exception_acknowledgement=bool(blocker_codes),
        reopen_without_child_resurrection=not docket.is_active,
    )


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
    impacts = _lifecycle_impacts(session, docket=docket, payload=payload)
    blocker_codes = {row.blocker_code for row in impacts if row.blocker_code}
    missing_acknowledgements = sorted(
        blocker_codes - set(payload.acknowledged_exception_codes)
    )
    if missing_acknowledgements:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_lifecycle_exceptions_unresolved",
                "blocker_codes": missing_acknowledgements,
            },
        )
    if payload.second_approver_membership_id:
        if payload.second_approver_membership_id == context.membership.id:
            raise HTTPException(
                status_code=422,
                detail="The second approver must be a different active tenant member.",
            )
        _active_membership(
            session,
            company_id=docket.company_id,
            membership_id=payload.second_approver_membership_id,
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
            "acknowledged_exception_codes": payload.acknowledged_exception_codes,
            "second_approver_membership_id": payload.second_approver_membership_id,
            "client_report_handling": payload.client_report_handling,
            "linked_matter_handling": payload.linked_matter_handling,
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
    event.payload_json = {
        **event.payload_json,
        "impact_preview": [row.model_dump(mode="json") for row in impacts],
        "neutralized_coverages": neutralized_coverages,
        "neutralized_obligations": neutralized_obligations,
        "cancelled_shared_deadlines": cancelled_deadlines,
        "final_legal_disposition": will_be_terminal,
    }
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


def get_ip_prosecution_workspace(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> IpProsecutionWorkspaceResponse:
    docket = _authorized_lifecycle_docket(
        session,
        context=context,
        docket_id=docket_id,
        for_update=False,
    )
    events = list_ip_docket_events(
        session,
        context=context,
        docket_id=docket.id,
    )
    applications = list(
        session.scalars(
            select(TrademarkApplication)
            .where(
                TrademarkApplication.company_id == docket.company_id,
                TrademarkApplication.docket_id == docket.id,
            )
            .order_by(TrademarkApplication.created_at)
        )
    )
    current_phase = (
        applications[0].filing_phase
        if applications
        else next((row.after_phase for row in reversed(events) if row.after_phase), docket.status)
    )
    reconciled_ids = {row.reconciles_event_id for row in events if row.reconciles_event_id}
    pending_candidates = [
        row
        for row in events
        if row.candidate_status == "candidate" and row.id not in reconciled_ids
    ]
    registry_events = [row for row in events if row.source == "registry"]
    freshness = (
        "candidate_pending"
        if pending_candidates
        else "current"
        if registry_events
        else "not_configured"
    )
    gaps: list[str] = []
    if not applications:
        gaps.append("application_missing")
    if any(not row.source_reference and row.source != "manual" for row in events):
        gaps.append("source_reference_missing")
    if pending_candidates:
        gaps.append("registry_candidate_unreconciled")
    unconfirmed_deadlines = sorted(
        {
            reference
            for row in events
            if row.payload_json.get("deadlines_confirmed") is not True
            for reference in row.resulting_deadline_refs_json
        }
    )
    conflicting_ids: set[str] = set()
    for index, row in enumerate(events):
        for candidate in events[index + 1 :]:
            if (
                row.event_kind == candidate.event_kind
                and row.application_id == candidate.application_id
                and row.proceeding_id == candidate.proceeding_id
                and row.effective_at.date() == candidate.effective_at.date()
                and row.id not in reconciled_ids
                and candidate.id not in reconciled_ids
            ):
                conflicting_ids.update((row.id, candidate.id))
    return IpProsecutionWorkspaceResponse(
        docket_id=docket.id,
        lifecycle_status=docket.status,
        lifecycle_version=docket.lifecycle_version,
        current_phase=current_phase,
        registry_freshness=freshness,
        data_quality_gaps=sorted(set(gaps)),
        unconfirmed_deadline_refs=unconfirmed_deadlines,
        conflicting_event_ids=sorted(conflicting_ids),
        events=events,
        operational_completion_count=sum(
            row.payload_json.get("operational_completion") is True for row in events
        ),
        filing_evidence_count=sum(
            row.payload_json.get("filing_evidence") is True for row in events
        ),
        registry_acceptance_count=sum(
            row.payload_json.get("registry_acceptance") is True for row in events
        ),
        final_disposition_count=sum(
            row.payload_json.get("final_legal_disposition") is True for row in events
        ),
    )
