"""Canonical append-only IP event and parent lifecycle command contract."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CalendarEventSync,
    CalendarEventSyncStatus,
    CompanyMembership,
    HearingReminder,
    HearingReminderDeliveryIntent,
    HearingReminderStatus,
    IpDeadline,
    IpDeadlineCoverage,
    IpDeadlineIncident,
    IpDocketEvent,
    IpDocketRecord,
    IpIdentifier,
    IpProceeding,
    IpRelatedRightObligation,
    IpResponsibilityAssignment,
    IpTitleInterest,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterHearing,
    MatterHearingStatus,
    MatterTask,
    MatterTaskStatus,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    TrademarkApplication,
    UserCalendarConnection,
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
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.calendar_projection_safety import (
    calendar_sync_upsert_claim_state,
    materialize_expired_calendar_sync_upsert_claim,
)
from caseops_api.services.ip_records import assert_application_can_enter_filed_phase
from caseops_api.services.matter_access import (
    assert_ip_docket_access,
    can_access,
    can_access_ip_docket,
)
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
    lock_matter_docket_family: bool = False,
) -> IpDocketRecord:
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
        # Matter is the access/lifecycle parent. Lock it before the IP child
        # so Matter disposal and direct IP transitions share one lock order.
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
        if lock_matter_docket_family and discovered_parent.matter_id:
            # A Matter deadline can serve more than one IP docket. Terminal
            # lifecycle must stabilize every sibling before it decides whether
            # that shared deadline is still operational elsewhere.
            locked_dockets = list(
                session.scalars(
                    select(IpDocketRecord)
                    .where(
                        IpDocketRecord.company_id == context.company.id,
                        IpDocketRecord.matter_id == discovered_parent.matter_id,
                    )
                    .order_by(IpDocketRecord.id)
                    .with_for_update(of=IpDocketRecord)
                    .execution_options(populate_existing=True)
                )
            )
            docket = next(
                (candidate for candidate in locked_dockets if candidate.id == docket_id),
                None,
            )
        else:
            docket = session.scalar(
                statement.with_for_update().execution_options(populate_existing=True)
            )
    if docket is None or docket.archived_by_matter_disposal:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    if for_update:
        assert discovered_parent is not None
        if docket.matter_id != discovered_parent.matter_id:
            raise HTTPException(
                status_code=409,
                detail="The IP docket parent changed; retry the operation.",
            )
    assert_ip_docket_access(session, context=context, docket=docket)
    if docket.matter_id:
        matter = locked_matter or session.scalar(
            select(Matter).where(
                Matter.id == docket.matter_id,
                Matter.company_id == context.company.id,
            )
        )
        if matter is None:
            raise HTTPException(status_code=404, detail="IP docket record not found.")
        if not matter.is_active:
            raise HTTPException(
                status_code=409,
                detail="The linked Matter is terminal; its dedicated lifecycle owns reopening.",
            )
    return docket


def _fence_reopen_linked_matter_roles(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> tuple[str | None, dict[str, str | None], dict[str, CompanyMembership]]:
    """Fence inherited Matter roles before the Matter/docket lock family.

    Terminal dockets are deliberately excluded from the normal live-IP
    deactivation guard.  A controlled reopen must therefore prove that every
    linked Matter role is still an active, authorized principal.  Discovering
    the IDs first and locking them in sorted order preserves the canonical
    Membership -> Matter -> docket lock order; the locked parent snapshot is
    revalidated before the transition is allowed to proceed.
    """

    matter_id = session.scalar(
        select(IpDocketRecord.matter_id).where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
    )
    roles: dict[str, str | None] = {
        "assignee": None,
        "responsible_lawyer": None,
    }
    if matter_id is not None:
        discovered = session.execute(
            select(
                Matter.assignee_membership_id,
                Matter.responsible_lawyer_membership_id,
            ).where(
                Matter.id == matter_id,
                Matter.company_id == context.company.id,
            )
        ).one_or_none()
        if discovered is not None:
            roles = {
                "assignee": discovered.assignee_membership_id,
                "responsible_lawyer": discovered.responsible_lawyer_membership_id,
            }
    locked_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=roles.values(),
    )
    return matter_id, roles, locked_memberships


def _assert_reopen_linked_matter_roles(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    discovered_matter_id: str | None,
    discovered_roles: dict[str, str | None],
    locked_memberships: dict[str, CompanyMembership],
) -> None:
    if docket.matter_id != discovered_matter_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_docket_reopen_matter_roles_changed",
                "message": "The linked Matter changed; reload before reopening.",
            },
        )
    if docket.matter_id is None:
        return

    matter = session.get(Matter, docket.matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    current_roles = {
        "assignee": matter.assignee_membership_id,
        "responsible_lawyer": matter.responsible_lawyer_membership_id,
    }
    if current_roles != discovered_roles:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_docket_reopen_matter_roles_changed",
                "message": "The linked Matter roles changed; reload before reopening.",
            },
        )

    for role, membership_id in current_roles.items():
        if membership_id is None:
            continue
        membership = locked_memberships.get(membership_id)
        if (
            membership is None
            or not membership.is_active
            or membership.user is None
            or not membership.user.is_active
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ip_docket_reopen_matter_role_unavailable",
                    "role": role,
                    "membership_id": membership_id,
                },
            )
        member_context = SessionContext(
            company=context.company,
            membership=membership,
            user=membership.user,
        )
        can_access_matter = can_access(session, context=member_context, matter=matter)
        can_access_docket = can_access_ip_docket(
            session, context=member_context, docket=docket
        )
        if not can_access_matter or not can_access_docket:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ip_docket_reopen_matter_role_inaccessible",
                    "role": role,
                    "membership_id": membership_id,
                },
            )


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
        ip_docket_id=docket.id,
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
            IpDeadlineIncident.status.notin_(("disproved", "verified")),
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


def _lock_live_legal_deadlines_for_lifecycle(
    session: Session,
    *,
    docket: IpDocketRecord,
) -> list[IpDeadline]:
    """Lock live legal-deadline parents before operational projections.

    Legal-deadline writers use Matter -> docket -> IpDeadline ->
    MatterDeadline.  The lifecycle command already owns Matter/docket, so this
    preserves that order and prevents a terminal transition from racing a
    confirm, override, or completion command.
    """

    return list(
        session.scalars(
            select(IpDeadline)
            .where(
                IpDeadline.company_id == docket.company_id,
                IpDeadline.docket_id == docket.id,
                IpDeadline.state.in_(("confirmed", "overdue")),
            )
            .order_by(IpDeadline.id)
            .with_for_update(of=IpDeadline)
            .execution_options(populate_existing=True)
        )
    )


def _neutralize_live_legal_deadlines(
    session: Session,
    *,
    legal_deadlines: list[IpDeadline],
    now: datetime,
) -> int:
    """Close live responsibility evidence after projections are locked.

    Reopening an IP docket must never reactivate a confirmed/overdue legal
    deadline or an open-ended responsibility assignment.  The immutable rows
    remain available as history; only their live interval is closed.
    """

    deadline_ids = {row.id for row in legal_deadlines}
    assignments = (
        list(
            session.scalars(
                select(IpResponsibilityAssignment)
                .where(
                    IpResponsibilityAssignment.deadline_id.in_(deadline_ids),
                    IpResponsibilityAssignment.effective_until.is_(None),
                )
                .order_by(IpResponsibilityAssignment.id)
                .with_for_update(of=IpResponsibilityAssignment)
                .execution_options(populate_existing=True)
            )
        )
        if deadline_ids
        else []
    )
    for assignment in assignments:
        assignment.effective_until = max(
            now,
            _as_utc(assignment.effective_from),
        )
        assignment.version += 1
    for row in legal_deadlines:
        row.state = "cancelled"
        row.version += 1
        row.updated_at = now
    return len(assignments)


def _remaining_operational_deadline_roles(
    session: Session,
    *,
    docket: IpDocketRecord,
    deadline_ids: set[str],
) -> tuple[dict[str, set[str]], set[str]]:
    """Return the stable sibling roles/references that survive this transition."""

    if not deadline_ids:
        return {}, set()
    coverages = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .join(IpDocketRecord, IpDocketRecord.id == IpDeadlineCoverage.docket_id)
            .where(
                IpDeadlineCoverage.company_id == docket.company_id,
                IpDeadlineCoverage.docket_id != docket.id,
                IpDeadlineCoverage.matter_deadline_id.in_(deadline_ids),
                IpDeadlineCoverage.coverage_status.notin_(
                    ("inactive_lifecycle", "completed")
                ),
                IpDocketRecord.company_id == docket.company_id,
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(TERMINAL_IP_DOCKET_STATUSES),
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update(of=IpDeadlineCoverage)
            .execution_options(populate_existing=True)
        )
    )
    roles: dict[str, set[str]] = {}
    for coverage in coverages:
        members = roles.setdefault(coverage.matter_deadline_id, set())
        members.add(coverage.responsible_membership_id)
        if coverage.backup_membership_id is not None:
            members.add(coverage.backup_membership_id)
        # Any create/delete/revival is asynchronous, so never certify a
        # sibling projection as current before the worker confirms it.
        coverage.calendar_projection_status = "pending"

    obligations = list(
        session.scalars(
            select(IpRelatedRightObligation)
            .join(IpDocketRecord, IpDocketRecord.id == IpRelatedRightObligation.docket_id)
            .where(
                IpRelatedRightObligation.company_id == docket.company_id,
                IpRelatedRightObligation.docket_id != docket.id,
                IpRelatedRightObligation.matter_deadline_id.in_(deadline_ids),
                IpRelatedRightObligation.status.notin_(
                    ("completed", "cancelled_lifecycle")
                ),
                IpDocketRecord.company_id == docket.company_id,
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(TERMINAL_IP_DOCKET_STATUSES),
            )
            .order_by(IpRelatedRightObligation.id)
            .with_for_update(of=IpRelatedRightObligation)
            .execution_options(populate_existing=True)
        )
    )
    remaining_reference_ids = set(roles)
    remaining_reference_ids.update(
        row.matter_deadline_id
        for row in obligations
        if row.matter_deadline_id is not None
    )
    return roles, remaining_reference_ids


def _neutralize_direct_docket_work_and_projections(
    session: Session,
    *,
    docket: IpDocketRecord,
    event: IpDocketEvent,
    lifecycle_version: int,
    legal_deadline_ids: set[str],
    calendar_deadline_ids: set[str],
    remaining_deadline_roles: dict[str, set[str]],
    surviving_deadline_ids: set[str],
    now: datetime,
) -> dict[str, int]:
    """Make every direct operational child durable-terminal under one lock.

    This helper runs for both a new terminal transition and the guarded reopen
    of a legacy terminal docket.  It deliberately preserves completed/sent
    history while neutralizing only work or outbound projections that could
    become actionable again when the parent is reopened.
    """

    tasks = list(
        session.scalars(
            select(MatterTask)
            .where(
                MatterTask.company_id == docket.company_id,
                MatterTask.ip_docket_id == docket.id,
                MatterTask.status.notin_(
                    (MatterTaskStatus.COMPLETED, MatterTaskStatus.CANCELLED)
                ),
            )
            .order_by(MatterTask.id)
            .with_for_update(of=MatterTask)
            .execution_options(populate_existing=True)
        )
    )
    task_ids: set[str] = set()
    for task in tasks:
        task_ids.add(task.id)
        task.status = MatterTaskStatus.CANCELLED
        task.completed_at = task.completed_at or now
        task.neutralized_by_ip_lifecycle_event_id = event.id
        task.neutralized_by_ip_lifecycle_version = lifecycle_version
        task.neutralized_at = now
        task.updated_at = now

    hearings = list(
        session.scalars(
            select(MatterHearing)
            .where(
                MatterHearing.company_id == docket.company_id,
                MatterHearing.ip_docket_id == docket.id,
                MatterHearing.status.in_(
                    (MatterHearingStatus.SCHEDULED, MatterHearingStatus.ADJOURNED)
                ),
            )
            .order_by(MatterHearing.id)
            .with_for_update(of=MatterHearing)
            .execution_options(populate_existing=True)
        )
    )
    hearing_ids: set[str] = set()
    for hearing in hearings:
        hearing_ids.add(hearing.id)
        hearing.status = MatterHearingStatus.CANCELLED
        hearing.neutralized_by_ip_lifecycle_event_id = event.id
        hearing.neutralized_by_ip_lifecycle_version = lifecycle_version
        hearing.neutralized_at = now
        hearing.updated_at = now

    reminders = list(
        session.scalars(
            select(HearingReminder)
            .where(
                HearingReminder.company_id == docket.company_id,
                HearingReminder.ip_docket_id == docket.id,
                HearingReminder.status == HearingReminderStatus.QUEUED,
            )
            .order_by(HearingReminder.id)
            .with_for_update(of=HearingReminder)
            .execution_options(populate_existing=True)
        )
    )
    reminder_ids = {row.id for row in reminders}
    for reminder in reminders:
        reminder.status = HearingReminderStatus.CANCELLED
        reminder.neutralized_by_ip_lifecycle_event_id = event.id
        reminder.neutralized_by_ip_lifecycle_version = lifecycle_version
        reminder.neutralized_at = now
        reminder.updated_at = now

    linked_intent_ids = (
        set(
            session.scalars(
                select(HearingReminderDeliveryIntent.intent_id).where(
                    HearingReminderDeliveryIntent.hearing_reminder_id.in_(reminder_ids)
                )
            )
        )
        if reminder_ids
        else set()
    )
    intent_targets = [NotificationDeliveryIntent.ip_docket_id == docket.id]
    if legal_deadline_ids:
        intent_targets.append(
            and_(
                NotificationDeliveryIntent.schedule_source_type == "ip_deadline",
                NotificationDeliveryIntent.schedule_source_id.in_(legal_deadline_ids),
            )
        )
    if linked_intent_ids:
        intent_targets.append(NotificationDeliveryIntent.id.in_(linked_intent_ids))
    intents = list(
        session.scalars(
            select(NotificationDeliveryIntent)
            .where(
                NotificationDeliveryIntent.company_id == docket.company_id,
                NotificationDeliveryIntent.status.in_(
                    (
                        NotificationDeliveryStatus.QUEUED,
                        NotificationDeliveryStatus.RETRY_SCHEDULED,
                    )
                ),
                or_(*intent_targets),
            )
            .order_by(NotificationDeliveryIntent.id)
            .with_for_update(of=NotificationDeliveryIntent)
            .execution_options(populate_existing=True)
        )
    )
    for intent in intents:
        intent.status = NotificationDeliveryStatus.CANCELLED
        intent.next_attempt_at = None
        intent.last_error_redacted = "IP docket lifecycle became terminal before delivery."
        intent.dead_letter_reason = "ip_docket_lifecycle_terminal"
        if intent.ip_docket_id == docket.id:
            intent.neutralized_by_ip_lifecycle_event_id = event.id
            intent.neutralized_by_ip_lifecycle_version = lifecycle_version
            intent.neutralized_at = now
        intent.updated_at = now

    source_pairs = {
        *(("matter_task", row_id) for row_id in task_ids),
        *(("matter_hearing", row_id) for row_id in hearing_ids),
        *(("matter_deadline", row_id) for row_id in calendar_deadline_ids),
    }
    sync_targets = [
        and_(
            CalendarEventSync.source_type == source_type,
            CalendarEventSync.source_id == source_id,
        )
        for source_type, source_id in sorted(source_pairs)
    ]
    syncs = (
        list(
            session.scalars(
                select(CalendarEventSync)
                .where(
                    CalendarEventSync.company_id == docket.company_id,
                    or_(*sync_targets),
                )
                .order_by(CalendarEventSync.id)
                .with_for_update(of=CalendarEventSync)
                .execution_options(populate_existing=True)
            )
        )
        if sync_targets
        else []
    )
    connection_ids = {row.calendar_connection_id for row in syncs}
    desired_membership_ids = {
        membership_id
        for membership_ids in remaining_deadline_roles.values()
        for membership_id in membership_ids
    }
    discovered_desired_connections = (
        list(
            session.scalars(
                select(UserCalendarConnection)
                .where(
                    UserCalendarConnection.company_id == docket.company_id,
                    UserCalendarConnection.membership_id.in_(desired_membership_ids),
                    UserCalendarConnection.status == "connected",
                )
                .order_by(UserCalendarConnection.id)
            )
        )
        if desired_membership_ids
        else []
    )
    connection_ids.update(row.id for row in discovered_desired_connections)
    connections = (
        list(
            session.scalars(
                select(UserCalendarConnection)
                .where(UserCalendarConnection.id.in_(connection_ids))
                .order_by(UserCalendarConnection.id)
                .with_for_update(of=UserCalendarConnection)
                .execution_options(populate_existing=True)
            )
        )
        if connection_ids
        else []
    )
    connections_by_id = {row.id: row for row in connections}
    desired_connections = [
        row
        for row in connections
        if row.status == "connected" and row.membership_id in desired_membership_ids
    ]
    existing_sync_keys = {
        (row.calendar_connection_id, row.source_type, row.source_id) for row in syncs
    }
    blocked_unknown_sync_ids: list[str] = []
    for sync in syncs:
        connection = connections_by_id.get(sync.calendar_connection_id)
        desired_for_source = remaining_deadline_roles.get(sync.source_id, set())
        upsert_claim_state = calendar_sync_upsert_claim_state(sync, now=now)
        if upsert_claim_state == "live":
            # Provider I/O is still in flight. Preserve the exact claim marker
            # and credential fence until its owner finalizes.
            blocked_unknown_sync_ids.append(sync.id)
            continue
        if upsert_claim_state == "expired":
            # Terminal cleanup cannot truthfully mark an unreceipted create as
            # absent. Persist the shared typed reconciliation state under the
            # existing parent -> Sync locks without contacting the provider.
            materialize_expired_calendar_sync_upsert_claim(sync, now=now)
            session.add(sync)
            blocked_unknown_sync_ids.append(sync.id)
            continue
        if upsert_claim_state == "manual_reconciliation":
            # Neither sibling preservation nor terminal withdrawal can claim
            # that an unreceipted remote create is absent. Keep the durable
            # reconciliation tombstone and its cleanup credential fence.
            blocked_unknown_sync_ids.append(sync.id)
            continue
        if (
            sync.source_type == "matter_deadline"
            and connection is not None
            and connection.status == "connected"
            and connection.membership_id in desired_for_source
        ):
            if sync.sync_status in (
                CalendarEventSyncStatus.DELETED,
                CalendarEventSyncStatus.DELETE_PENDING,
                CalendarEventSyncStatus.FAILED,
                CalendarEventSyncStatus.DEAD_LETTER,
            ):
                sync.sync_status = CalendarEventSyncStatus.PENDING
                sync.next_attempt_at = now
                sync.dead_letter_reason = None
                sync.last_error = None
            sync.neutralized_by_ip_lifecycle_event_id = None
            sync.neutralized_ip_docket_id = None
            sync.neutralized_by_ip_lifecycle_version = None
            sync.neutralized_at = None
            sync.updated_at = now
            continue
        if (
            sync.neutralized_by_ip_lifecycle_event_id is not None
            and sync.sync_status
            in (
                CalendarEventSyncStatus.DELETE_PENDING,
                CalendarEventSyncStatus.DELETED,
            )
        ):
            # The first lifecycle transition remains the immutable reason this
            # projection was withdrawn; a later controlled reopen must not
            # rewrite that provenance.
            continue
        source_survives = (
            sync.source_type == "matter_deadline"
            and sync.source_id in surviving_deadline_ids
        )
        if sync.provider_event_id:
            sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
            sync.next_attempt_at = now
        else:
            sync.sync_status = CalendarEventSyncStatus.DELETED
            sync.next_attempt_at = None
        sync.dead_letter_reason = "ip_docket_lifecycle_terminal"
        sync.last_error = None
        if not source_survives:
            sync.neutralized_by_ip_lifecycle_event_id = event.id
            sync.neutralized_ip_docket_id = docket.id
            sync.neutralized_by_ip_lifecycle_version = lifecycle_version
            sync.neutralized_at = now
        sync.updated_at = now

    created_syncs = 0
    for source_id, desired_members in sorted(remaining_deadline_roles.items()):
        for connection in desired_connections:
            key = (connection.id, "matter_deadline", source_id)
            if connection.membership_id not in desired_members or key in existing_sync_keys:
                continue
            session.add(
                CalendarEventSync(
                    company_id=docket.company_id,
                    calendar_connection_id=connection.id,
                    source_type="matter_deadline",
                    source_id=source_id,
                    sync_status=CalendarEventSyncStatus.PENDING,
                    next_attempt_at=now,
                    dead_letter_reason=None,
                )
            )
            existing_sync_keys.add(key)
            created_syncs += 1

    return {
        "cancelled_shared_tasks": len(tasks),
        "cancelled_shared_hearings": len(hearings),
        "cancelled_hearing_reminders": len(reminders),
        "cancelled_notification_intents": len(intents),
        "neutralized_calendar_syncs": sum(
            row.neutralized_by_ip_lifecycle_event_id == event.id for row in syncs
        ),
        "queued_sibling_calendar_syncs": created_syncs,
        "blocked_unknown_calendar_syncs": len(blocked_unknown_sync_ids),
    }


def transition_ip_docket_lifecycle(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpLifecycleTransitionRequest,
) -> tuple[IpDocketRecord, IpDocketEvent]:
    """Apply only the legal parent transition; IPLF-022B owns child-impact UI/routes."""

    requested_terminal = payload.to_status in TERMINAL_IP_DOCKET_STATUSES
    discovered_matter_id: str | None = None
    discovered_matter_roles: dict[str, str | None] = {}
    locked_matter_role_memberships: dict[str, CompanyMembership] = {}
    if not requested_terminal:
        (
            discovered_matter_id,
            discovered_matter_roles,
            locked_matter_role_memberships,
        ) = _fence_reopen_linked_matter_roles(
            session,
            context=context,
            docket_id=docket_id,
        )
    docket = _authorized_lifecycle_docket(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        # Reopen must make the same sibling-preservation decision as close;
        # otherwise a legacy terminal row can cancel a MatterDeadline that is
        # still operational for another docket on the linked Matter.
        lock_matter_docket_family=True,
    )
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    was_terminal = docket.status in TERMINAL_IP_DOCKET_STATUSES
    will_be_terminal = requested_terminal
    if was_terminal == will_be_terminal:
        raise HTTPException(
            status_code=409,
            detail="Lifecycle transitions must cross the active/terminal boundary.",
        )
    if not will_be_terminal:
        _assert_reopen_linked_matter_roles(
            session,
            context=context,
            docket=docket,
            discovered_matter_id=discovered_matter_id,
            discovered_roles=discovered_matter_roles,
            locked_memberships=locked_matter_role_memberships,
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

    # Every lifecycle event has a durable version identity. Docket-owned
    # operational children use this tuple as their neutralization provenance,
    # so persist it before acquiring or mutating any child row.
    event.resulting_lifecycle_version = next_version
    session.flush()

    neutralized_at = datetime.now(UTC)
    live_legal_deadlines = _lock_live_legal_deadlines_for_lifecycle(
        session,
        docket=docket,
    )
    legal_deadline_ids = {row.id for row in live_legal_deadlines}
    legal_projection_deadline_ids = {
        row.matter_deadline_id
        for row in live_legal_deadlines
        if row.matter_deadline_id is not None
    }
    neutralized_coverages = 0
    neutralized_obligations = 0
    cancelled_deadlines = 0
    lifecycle_deadline_ids: set[str] = set()
    calendar_deadline_ids = set(legal_projection_deadline_ids)
    remaining_deadline_roles: dict[str, set[str]] = {}
    remaining_deadline_reference_ids: set[str] = set()
    if will_be_terminal:
        coverage_refs = session.execute(
            select(IpDeadlineCoverage.id, IpDeadlineCoverage.matter_deadline_id).where(
                IpDeadlineCoverage.company_id == docket.company_id,
                IpDeadlineCoverage.docket_id == docket.id,
                IpDeadlineCoverage.coverage_status.notin_(
                    ("inactive_lifecycle", "completed")
                ),
            )
        ).all()
        obligation_refs = session.execute(
            select(
                IpRelatedRightObligation.id,
                IpRelatedRightObligation.matter_deadline_id,
            ).where(
                IpRelatedRightObligation.company_id == docket.company_id,
                IpRelatedRightObligation.docket_id == docket.id,
                IpRelatedRightObligation.status.notin_(
                    ("completed", "cancelled_lifecycle")
                ),
            )
        ).all()
        referenced_deadline_ids = {
            deadline_id
            for _row_id, deadline_id in [*coverage_refs, *obligation_refs]
            if deadline_id is not None
        }
        referenced_deadline_ids.update(legal_projection_deadline_ids)
        calendar_deadline_ids.update(referenced_deadline_ids)
        directly_owned_deadline = and_(
            MatterDeadline.ip_docket_id == docket.id,
            MatterDeadline.matter_id.is_(None),
            MatterDeadline.status.in_(
                (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
            ),
            MatterDeadline.neutralized_at.is_(None),
        )
        if docket.matter_id is not None:
            deadline_target = or_(
                directly_owned_deadline,
                and_(
                    MatterDeadline.id.in_(referenced_deadline_ids),
                    MatterDeadline.matter_id == docket.matter_id,
                    MatterDeadline.ip_docket_id.is_(None),
                ),
            )
        else:
            deadline_target = directly_owned_deadline
        deadlines = list(
            session.scalars(
                select(MatterDeadline)
                .where(
                    MatterDeadline.company_id == docket.company_id,
                    deadline_target,
                )
                .order_by(MatterDeadline.id)
                .with_for_update(of=MatterDeadline)
                .execution_options(populate_existing=True)
            )
        )
        locked_deadline_ids = {deadline.id for deadline in deadlines}
        operational_sibling_docket_ids = (
            set(
                session.scalars(
                    select(IpDocketRecord.id).where(
                        IpDocketRecord.company_id == docket.company_id,
                        IpDocketRecord.matter_id == docket.matter_id,
                        IpDocketRecord.id != docket.id,
                        IpDocketRecord.is_active.is_(True),
                        IpDocketRecord.archived_by_matter_disposal.is_(False),
                        IpDocketRecord.status.notin_(TERMINAL_IP_DOCKET_STATUSES),
                    )
                ).all()
            )
            if docket.matter_id is not None
            else set()
        )

        # Discover sibling child ids only after the whole Matter/docket family
        # and candidate deadlines are locked. Coverage writers and obligation
        # writers use the same parent-first order, so no operational sibling
        # reference can appear or disappear around this decision.
        sibling_coverage_refs = (
            session.execute(
                select(
                    IpDeadlineCoverage.id,
                    IpDeadlineCoverage.docket_id,
                    IpDeadlineCoverage.matter_deadline_id,
                ).where(
                    IpDeadlineCoverage.company_id == docket.company_id,
                    IpDeadlineCoverage.docket_id.in_(operational_sibling_docket_ids),
                    IpDeadlineCoverage.matter_deadline_id.in_(locked_deadline_ids),
                    IpDeadlineCoverage.coverage_status.notin_(
                        ("inactive_lifecycle", "completed")
                    ),
                )
            ).all()
            if operational_sibling_docket_ids and locked_deadline_ids
            else []
        )
        sibling_obligation_refs = (
            session.execute(
                select(
                    IpRelatedRightObligation.id,
                    IpRelatedRightObligation.docket_id,
                    IpRelatedRightObligation.matter_deadline_id,
                ).where(
                    IpRelatedRightObligation.company_id == docket.company_id,
                    IpRelatedRightObligation.docket_id.in_(
                        operational_sibling_docket_ids
                    ),
                    IpRelatedRightObligation.matter_deadline_id.in_(
                        locked_deadline_ids
                    ),
                    IpRelatedRightObligation.status.notin_(
                        ("completed", "cancelled_lifecycle")
                    ),
                )
            ).all()
            if operational_sibling_docket_ids and locked_deadline_ids
            else []
        )

        target_coverage_ids = {
            row_id for row_id, _deadline_id in coverage_refs
        }
        sibling_coverage_ids = {
            row_id for row_id, _docket_id, _deadline_id in sibling_coverage_refs
        }
        coverage_ids = target_coverage_ids | sibling_coverage_ids
        locked_coverages = (
            list(
                session.scalars(
                    select(IpDeadlineCoverage)
                    .where(
                        IpDeadlineCoverage.id.in_(coverage_ids),
                        IpDeadlineCoverage.company_id == docket.company_id,
                    )
                    .order_by(IpDeadlineCoverage.id)
                    .with_for_update(of=IpDeadlineCoverage)
                    .execution_options(populate_existing=True)
                )
            )
            if coverage_ids
            else []
        )
        coverages = [
            coverage
            for coverage in locked_coverages
            if coverage.id in target_coverage_ids
            and coverage.docket_id == docket.id
            and coverage.coverage_status not in ("inactive_lifecycle", "completed")
        ]
        sibling_coverage_deadline_ids = {
            coverage.matter_deadline_id
            for coverage in locked_coverages
            if coverage.id in sibling_coverage_ids
            and coverage.docket_id in operational_sibling_docket_ids
            and coverage.matter_deadline_id in locked_deadline_ids
            and coverage.coverage_status not in ("inactive_lifecycle", "completed")
        }
        for coverage in coverages:
            coverage.coverage_status = "inactive_lifecycle"
            coverage.calendar_projection_status = "inactive_lifecycle"
            coverage.updated_at = datetime.now(UTC)
        neutralized_coverages = len(coverages)

        target_obligation_ids = {
            row_id for row_id, _deadline_id in obligation_refs
        }
        sibling_obligation_ids = {
            row_id for row_id, _docket_id, _deadline_id in sibling_obligation_refs
        }
        obligation_ids = target_obligation_ids | sibling_obligation_ids
        locked_obligations = (
            list(
                session.scalars(
                    select(IpRelatedRightObligation)
                    .where(
                        IpRelatedRightObligation.id.in_(obligation_ids),
                        IpRelatedRightObligation.company_id == docket.company_id,
                    )
                    .order_by(IpRelatedRightObligation.id)
                    .with_for_update(of=IpRelatedRightObligation)
                    .execution_options(populate_existing=True)
                )
            )
            if obligation_ids
            else []
        )
        obligations = [
            obligation
            for obligation in locked_obligations
            if obligation.id in target_obligation_ids
            and obligation.docket_id == docket.id
            and obligation.status not in ("completed", "cancelled_lifecycle")
        ]
        sibling_obligation_deadline_ids = {
            obligation.matter_deadline_id
            for obligation in locked_obligations
            if obligation.id in sibling_obligation_ids
            and obligation.docket_id in operational_sibling_docket_ids
            and obligation.matter_deadline_id in locked_deadline_ids
            and obligation.status not in ("completed", "cancelled_lifecycle")
        }
        for obligation in obligations:
            obligation.status = "cancelled_lifecycle"
            obligation.updated_at = datetime.now(UTC)
        neutralized_obligations = len(obligations)

        sibling_deadline_ids = (
            sibling_coverage_deadline_ids | sibling_obligation_deadline_ids
        )
        for deadline in deadlines:
            is_directly_owned = deadline.ip_docket_id == docket.id and deadline.matter_id is None
            if (
                (is_directly_owned or deadline.id not in sibling_deadline_ids)
                and deadline.status in (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                and deadline.neutralized_at is None
                and (is_directly_owned or not deadline.cancelled_by_matter_disposal)
            ):
                deadline.status = MatterDeadlineStatus.CANCELLED
                deadline.completed_at = deadline.completed_at or neutralized_at
                deadline.updated_at = neutralized_at
                if is_directly_owned:
                    deadline.neutralized_by_ip_lifecycle_event_id = event.id
                    deadline.neutralized_by_ip_lifecycle_version = next_version
                    deadline.neutralized_at = neutralized_at
                cancelled_deadlines += 1
                lifecycle_deadline_ids.add(deadline.id)
    elif was_terminal and not will_be_terminal:
        # Upgrade-time repair may leave an old terminal docket with a direct
        # operational child. Reopening must neutralize that child under the
        # locked parent rather than make it visible again. Compliant shared-
        # work writers lock the docket first, so this refresh is authoritative.
        legacy_coverage_refs = session.execute(
            select(
                IpDeadlineCoverage.id,
                IpDeadlineCoverage.matter_deadline_id,
            ).where(
                IpDeadlineCoverage.company_id == docket.company_id,
                IpDeadlineCoverage.docket_id == docket.id,
                IpDeadlineCoverage.coverage_status.notin_(
                    ("inactive_lifecycle", "completed")
                ),
            )
        ).all()
        legacy_obligation_refs = session.execute(
            select(
                IpRelatedRightObligation.id,
                IpRelatedRightObligation.matter_deadline_id,
            ).where(
                IpRelatedRightObligation.company_id == docket.company_id,
                IpRelatedRightObligation.docket_id == docket.id,
                IpRelatedRightObligation.status.notin_(
                    ("completed", "cancelled_lifecycle")
                ),
            )
        ).all()
        calendar_deadline_ids.update(
            deadline_id
            for _row_id, deadline_id in [
                *legacy_coverage_refs,
                *legacy_obligation_refs,
            ]
            if deadline_id is not None
        )
        legacy_deadline_target = and_(
            MatterDeadline.ip_docket_id == docket.id,
            MatterDeadline.matter_id.is_(None),
        )
        if docket.matter_id is not None and calendar_deadline_ids:
            legacy_deadline_target = or_(
                legacy_deadline_target,
                and_(
                    MatterDeadline.id.in_(calendar_deadline_ids),
                    MatterDeadline.matter_id == docket.matter_id,
                    MatterDeadline.ip_docket_id.is_(None),
                ),
            )
        legacy_deadlines = list(
            session.scalars(
                select(MatterDeadline)
                .where(
                    MatterDeadline.company_id == docket.company_id,
                    legacy_deadline_target,
                    MatterDeadline.status.in_(
                        (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                    ),
                    MatterDeadline.neutralized_at.is_(None),
                )
                .order_by(MatterDeadline.id)
                .with_for_update(of=MatterDeadline)
                .execution_options(populate_existing=True)
            )
        )
        legacy_coverage_ids = {row_id for row_id, _deadline_id in legacy_coverage_refs}
        legacy_coverages = (
            list(
                session.scalars(
                    select(IpDeadlineCoverage)
                    .where(
                        IpDeadlineCoverage.id.in_(legacy_coverage_ids),
                        IpDeadlineCoverage.company_id == docket.company_id,
                    )
                    .order_by(IpDeadlineCoverage.id)
                    .with_for_update(of=IpDeadlineCoverage)
                    .execution_options(populate_existing=True)
                )
            )
            if legacy_coverage_ids
            else []
        )
        for coverage in legacy_coverages:
            if (
                coverage.docket_id == docket.id
                and coverage.coverage_status not in ("inactive_lifecycle", "completed")
            ):
                coverage.coverage_status = "inactive_lifecycle"
                coverage.calendar_projection_status = "inactive_lifecycle"
                coverage.updated_at = neutralized_at
        neutralized_coverages = len(legacy_coverages)

        legacy_obligation_ids = {
            row_id for row_id, _deadline_id in legacy_obligation_refs
        }
        legacy_obligations = (
            list(
                session.scalars(
                    select(IpRelatedRightObligation)
                    .where(
                        IpRelatedRightObligation.id.in_(legacy_obligation_ids),
                        IpRelatedRightObligation.company_id == docket.company_id,
                    )
                    .order_by(IpRelatedRightObligation.id)
                    .with_for_update(of=IpRelatedRightObligation)
                    .execution_options(populate_existing=True)
                )
            )
            if legacy_obligation_ids
            else []
        )
        for obligation in legacy_obligations:
            if (
                obligation.docket_id == docket.id
                and obligation.status not in ("completed", "cancelled_lifecycle")
            ):
                obligation.status = "cancelled_lifecycle"
                obligation.updated_at = neutralized_at
        neutralized_obligations = len(legacy_obligations)

        (
            remaining_deadline_roles,
            remaining_deadline_reference_ids,
        ) = _remaining_operational_deadline_roles(
            session,
            docket=docket,
            deadline_ids=calendar_deadline_ids,
        )
        for deadline in legacy_deadlines:
            is_directly_owned = (
                deadline.ip_docket_id == docket.id and deadline.matter_id is None
            )
            if (
                deadline.company_id == docket.company_id
                and (
                    is_directly_owned
                    or (
                        deadline.id in calendar_deadline_ids
                        and deadline.matter_id == docket.matter_id
                        and deadline.ip_docket_id is None
                    )
                )
                and deadline.status in (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                and deadline.neutralized_at is None
                and deadline.id not in remaining_deadline_reference_ids
            ):
                deadline.status = MatterDeadlineStatus.CANCELLED
                deadline.completed_at = deadline.completed_at or neutralized_at
                deadline.updated_at = neutralized_at
                if is_directly_owned:
                    deadline.neutralized_by_ip_lifecycle_event_id = event.id
                    deadline.neutralized_by_ip_lifecycle_version = next_version
                    deadline.neutralized_at = neutralized_at
                cancelled_deadlines += 1
                lifecycle_deadline_ids.add(deadline.id)

    if will_be_terminal:
        (
            remaining_deadline_roles,
            remaining_deadline_reference_ids,
        ) = _remaining_operational_deadline_roles(
            session,
            docket=docket,
            deadline_ids=calendar_deadline_ids,
        )

    neutralized_responsibility_assignments = _neutralize_live_legal_deadlines(
        session,
        legal_deadlines=live_legal_deadlines,
        now=neutralized_at,
    )
    direct_work_counts = _neutralize_direct_docket_work_and_projections(
        session,
        docket=docket,
        event=event,
        lifecycle_version=next_version,
        legal_deadline_ids=legal_deadline_ids,
        calendar_deadline_ids=calendar_deadline_ids | lifecycle_deadline_ids,
        remaining_deadline_roles=remaining_deadline_roles,
        surviving_deadline_ids=remaining_deadline_reference_ids,
        now=neutralized_at,
    )

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
        "neutralized_responsibility_assignments": (
            neutralized_responsibility_assignments
        ),
        **direct_work_counts,
        "final_legal_disposition": will_be_terminal,
    }
    record_from_context(
        session,
        context,
        action="ip_docket.lifecycle_transitioned",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
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
            "neutralized_responsibility_assignments": (
                neutralized_responsibility_assignments
            ),
            **direct_work_counts,
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
