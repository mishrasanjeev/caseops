"""Shared evidence, hearing, order, appeal, and extension opposition work."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpIdentifier,
    IpProceeding,
    Matter,
    MatterHearing,
)
from caseops_api.schemas.ip_deadlines import IpDeadlineOverrideRequest
from caseops_api.schemas.ip_lifecycle import IpDocketEventCreateRequest, IpDocketEventResponse
from caseops_api.schemas.ip_oppositions import (
    IpOppositionSharedActionRequest,
    IpOppositionSharedHearingRecord,
    IpOppositionSharedWorkflowResponse,
)
from caseops_api.services.ip_deadline_workflow import (
    _deadline_record,
    deadline_impact,
    override_deadline,
)
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.ip_opposition_workspace import _opposition_or_404
from caseops_api.services.matter_access import visible_matters_filter
from caseops_api.services.session_context import SessionContext

_ACTIVE_DEADLINE_STATES = frozenset({"confirmed", "overdue"})
_HEARING_STAGES = frozenset({"hearing_pending", "hearing_scheduled", "reserved_for_order"})
_FURTHER_EVIDENCE_STAGES = frozenset(
    {
        "opponent_evidence_filed",
        "applicant_evidence_due",
        "applicant_evidence_filed",
        "reply_evidence_due",
        "reply_evidence_filed",
        "hearing_pending",
        "hearing_scheduled",
    }
)


def _shared_opposition(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    for_update: bool,
    required_capability: str,
) -> tuple[IpDocketRecord, IpProceeding]:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=for_update,
        required_capability=required_capability,
    )
    proceeding = _opposition_or_404(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        proceeding_id=proceeding_id,
        for_update=for_update,
    )
    return docket, proceeding


def _proceeding_events(session: Session, proceeding: IpProceeding) -> list[IpDocketEvent]:
    return list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == proceeding.company_id,
                IpDocketEvent.docket_id == proceeding.docket_id,
                IpDocketEvent.proceeding_id == proceeding.id,
            )
            .order_by(IpDocketEvent.sequence)
        )
    )


def _shared_actions(events: list[IpDocketEvent]) -> list[IpDocketEvent]:
    return [row for row in events if row.event_kind == "opposition_shared_action"]


def _active_deadlines(session: Session, proceeding: IpProceeding) -> list[IpDeadline]:
    return list(
        session.scalars(
            select(IpDeadline)
            .join(IpDocketEvent, IpDocketEvent.id == IpDeadline.trigger_event_id)
            .where(
                IpDeadline.company_id == proceeding.company_id,
                IpDeadline.docket_id == proceeding.docket_id,
                IpDeadline.state.in_(_ACTIVE_DEADLINE_STATES),
                IpDocketEvent.proceeding_id == proceeding.id,
            )
            .order_by(IpDeadline.result_on, IpDeadline.created_at, IpDeadline.id)
        )
    )


def _shared_hearings(session: Session, proceeding: IpProceeding) -> list[MatterHearing]:
    return list(
        session.scalars(
            select(MatterHearing)
            .where(
                MatterHearing.company_id == proceeding.company_id,
                MatterHearing.ip_docket_id == proceeding.docket_id,
                MatterHearing.matter_id.is_(None),
            )
            .order_by(MatterHearing.hearing_on, MatterHearing.created_at, MatterHearing.id)
        )
    )


def _next_required_action(
    proceeding: IpProceeding,
    actions: list[IpDocketEvent],
    hearings: list[MatterHearing],
) -> str:
    if proceeding.stage == "closed":
        return "closed"
    if proceeding.stage in {
        "draft",
        "notice_filed",
        "service_pending",
        "counterstatement_due",
        "counterstatement_filed",
        "opponent_evidence_due",
        "applicant_evidence_due",
        "reply_evidence_due",
    }:
        return "complete_role_workflow"
    if proceeding.stage in {
        "opponent_evidence_filed",
        "applicant_evidence_filed",
        "reply_evidence_filed",
    }:
        return (
            "advance_to_hearing"
            if any(
                row.payload_json.get("action_kind") == "evidence_package_recorded"
                for row in actions
            )
            else "record_evidence_package"
        )
    if proceeding.stage == "hearing_pending":
        return "record_hearing_preparation" if hearings else "schedule_hearing"
    if proceeding.stage == "hearing_scheduled":
        prepared_hearing_ids = {
            row.payload_json.get("hearing_preparation", {}).get("shared_hearing_id")
            for row in actions
            if row.payload_json.get("action_kind") == "hearing_preparation_recorded"
        }
        if not prepared_hearing_ids:
            return "record_hearing_preparation"
        post_hearing_ids = {
            row.payload_json.get("hearing_preparation", {}).get("shared_hearing_id")
            for row in actions
            if row.payload_json.get("action_kind") == "post_hearing_note_recorded"
        }
        completed_hearing_ids = {row.id for row in hearings if row.status == "completed"}
        if prepared_hearing_ids & completed_hearing_ids:
            return (
                "advance_to_order"
                if post_hearing_ids & completed_hearing_ids
                else "record_post_hearing_note"
            )
        return "await_hearing"
    if proceeding.stage == "reserved_for_order":
        return "record_order"
    if proceeding.stage == "decided":
        return "review_appeal_or_close"
    if proceeding.stage == "appeal_pending":
        return "link_appeal"
    if proceeding.stage in {"appealed", "withdrawn"}:
        return "complete_appeal_or_close"
    return "complete_role_workflow"


def get_shared_workflow(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
) -> IpOppositionSharedWorkflowResponse:
    _, proceeding = _shared_opposition(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        for_update=False,
        required_capability="ip:read",
    )
    actions = _shared_actions(_proceeding_events(session, proceeding))
    deadlines = _active_deadlines(session, proceeding)
    hearings = _shared_hearings(session, proceeding)
    return IpOppositionSharedWorkflowResponse(
        proceeding_id=proceeding.id,
        represented_side=proceeding.side,
        current_stage=proceeding.stage,
        shared_actions=[IpDocketEventResponse.model_validate(row) for row in actions],
        active_deadlines=[_deadline_record(session, row) for row in deadlines],
        shared_hearings=[
            IpOppositionSharedHearingRecord(
                id=row.id,
                hearing_on=row.hearing_on,
                time_status=row.time_status,
                forum_name=row.forum_name,
                purpose=row.purpose,
                status=row.status,
            )
            for row in hearings
        ],
        next_required_action=_next_required_action(proceeding, actions, hearings),
    )


def _assert_supersession(
    session: Session,
    *,
    proceeding: IpProceeding,
    payload: IpOppositionSharedActionRequest,
) -> None:
    if payload.supersedes_action_event_id is None:
        return
    prior = session.scalar(
        select(IpDocketEvent).where(
            IpDocketEvent.id == payload.supersedes_action_event_id,
            IpDocketEvent.company_id == proceeding.company_id,
            IpDocketEvent.docket_id == proceeding.docket_id,
            IpDocketEvent.proceeding_id == proceeding.id,
            IpDocketEvent.event_kind == "opposition_shared_action",
        )
    )
    if prior is None:
        raise HTTPException(status_code=404, detail="Superseded opposition action not found.")
    if prior.payload_json.get("action_kind") != payload.action_kind:
        raise HTTPException(
            status_code=409,
            detail="A correction must supersede the same action kind.",
        )


def _assert_hearing(
    session: Session,
    *,
    proceeding: IpProceeding,
    hearing_id: str,
    require_completed: bool,
) -> MatterHearing:
    hearing = session.scalar(
        select(MatterHearing).where(
            MatterHearing.id == hearing_id,
            MatterHearing.company_id == proceeding.company_id,
            MatterHearing.ip_docket_id == proceeding.docket_id,
            MatterHearing.matter_id.is_(None),
        )
    )
    if hearing is None:
        raise HTTPException(status_code=404, detail="Shared opposition hearing not found.")
    if require_completed and hearing.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="Complete the shared hearing before adding notes.",
        )
    if not require_completed and hearing.status not in {"scheduled", "adjourned"}:
        raise HTTPException(
            status_code=409,
            detail="Hearing preparation requires an active hearing.",
        )
    return hearing


def _assert_evidence_package(
    actions: list[IpDocketEvent],
    *,
    proceeding: IpProceeding,
    payload: IpOppositionSharedActionRequest,
) -> None:
    package = payload.evidence_package
    assert package is not None
    expected_side_and_stages = {
        "rule_45": ("opponent", {"opponent_evidence_due", "opponent_evidence_filed"}),
        "rule_46": ("applicant", {"applicant_evidence_due", "applicant_evidence_filed"}),
        "rule_47": ("opponent", {"reply_evidence_due", "reply_evidence_filed"}),
        "further_evidence": (proceeding.side, _FURTHER_EVIDENCE_STAGES),
    }[package.package_kind]
    expected_side, allowed_stages = expected_side_and_stages
    if proceeding.side != expected_side or proceeding.stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail="This evidence package does not match the represented side and current stage.",
        )
    if package.package_kind == "further_evidence" and not any(
        row.payload_json.get("action_kind") == "further_evidence_leave_recorded"
        and row.payload_json.get("further_evidence_leave", {}).get("leave_or_order_reference")
        == package.leave_or_order_reference
        for row in actions
    ):
        raise HTTPException(
            status_code=409,
            detail="Record the matching leave or order before filing further evidence.",
        )
    duplicate = any(
        row.payload_json.get("action_kind") == "evidence_package_recorded"
        and row.payload_json.get("evidence_package", {}).get("package_kind")
        == package.package_kind
        and row.payload_json.get("evidence_package", {}).get("package_version")
        == package.package_version
        for row in actions
    )
    if duplicate and payload.supersedes_action_event_id is None:
        raise HTTPException(
            status_code=409,
            detail="This evidence package version is already recorded.",
        )


def _assert_order(
    session: Session,
    *,
    proceeding: IpProceeding,
    payload: IpOppositionSharedActionRequest,
    actions: list[IpDocketEvent],
) -> None:
    order = payload.order_details
    assert order is not None
    if proceeding.stage != "reserved_for_order":
        raise HTTPException(status_code=409, detail="Orders require the reserved-for-order stage.")
    if order.affected_application_id != proceeding.application_id or (
        order.affected_proceeding_id != proceeding.id
    ):
        raise HTTPException(
            status_code=409,
            detail="Order affected-record links do not match this opposition.",
        )
    if not any(
        row.payload_json.get("action_kind") == "hearing_preparation_recorded" for row in actions
    ):
        raise HTTPException(status_code=409, detail="Record hearing preparation before the order.")
    if any(row.payload_json.get("action_kind") == "order_recorded" for row in actions) and (
        payload.supersedes_action_event_id is None
    ):
        raise HTTPException(status_code=409, detail="An opposition order is already recorded.")


def _assert_appeal(
    session: Session,
    *,
    context: SessionContext,
    proceeding: IpProceeding,
    payload: IpOppositionSharedActionRequest,
    actions: list[IpDocketEvent],
) -> None:
    appeal = payload.appeal_link
    assert appeal is not None
    if proceeding.stage not in {"decided", "appeal_pending"}:
        raise HTTPException(
            status_code=409,
            detail="An appeal can only follow a decided opposition.",
        )
    order_event = next(
        (
            row
            for row in actions
            if row.id == appeal.order_event_id
            and row.payload_json.get("action_kind") == "order_recorded"
        ),
        None,
    )
    if order_event is None:
        raise HTTPException(
            status_code=409,
            detail="Appeal must link to this opposition's order event.",
        )
    if appeal.target_kind == "appeal_proceeding":
        target = session.scalar(
            select(IpProceeding).where(
                IpProceeding.id == appeal.target_id,
                IpProceeding.company_id == proceeding.company_id,
                IpProceeding.docket_id == proceeding.docket_id,
                IpProceeding.proceeding_kind == "appeal",
                IpProceeding.id != proceeding.id,
            )
        )
        identifier = session.scalar(
            select(IpIdentifier).where(
                IpIdentifier.company_id == proceeding.company_id,
                IpIdentifier.proceeding_id == appeal.target_id,
                IpIdentifier.identifier_kind == "appeal",
                IpIdentifier.raw_value == appeal.appeal_identifier,
                IpIdentifier.effective_until.is_(None),
            )
        )
        if target is None or identifier is None:
            raise HTTPException(
                status_code=409,
                detail="Appeal proceeding and identifier are required.",
            )
    else:
        target = session.scalar(
            select(Matter).where(
                Matter.id == appeal.target_id,
                Matter.company_id == context.company.id,
                visible_matters_filter(session, context=context),
            )
        )
        if target is None:
            raise HTTPException(status_code=404, detail="Appeal Matter not found.")
    if any(row.payload_json.get("action_kind") == "appeal_linked" for row in actions) and (
        payload.supersedes_action_event_id is None
    ):
        raise HTTPException(status_code=409, detail="An appeal is already linked.")


def _action_identity(payload: IpOppositionSharedActionRequest) -> str:
    if payload.deadline_extension:
        detail = (
            f"{payload.deadline_extension.deadline_id}:"
            f"{payload.deadline_extension.new_result_on.isoformat()}"
        )
    elif payload.further_evidence_leave:
        detail = payload.further_evidence_leave.leave_or_order_reference
    elif payload.evidence_package:
        detail = (
            f"{payload.evidence_package.package_kind}:"
            f"{payload.evidence_package.package_version}"
        )
    elif payload.hearing_preparation:
        detail = payload.hearing_preparation.shared_hearing_id
    elif payload.order_details:
        detail = payload.order_details.affected_proceeding_id
    else:
        assert payload.appeal_link is not None
        detail = f"{payload.appeal_link.target_kind}:{payload.appeal_link.target_id}"
    return f"{payload.action_kind}:{detail}"


def record_shared_action(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionSharedActionRequest,
) -> IpOppositionSharedWorkflowResponse:
    docket, proceeding = _shared_opposition(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        for_update=True,
        required_capability="ip:approve",
    )
    if proceeding.version != payload.expected_proceeding_version:
        raise HTTPException(status_code=409, detail="Proceeding version changed; reload.")
    if proceeding.stage == "closed":
        raise HTTPException(status_code=409, detail="Closed opposition proceedings are immutable.")
    _assert_supersession(session, proceeding=proceeding, payload=payload)
    events = _proceeding_events(session, proceeding)
    actions = _shared_actions(events)
    action_identity = _action_identity(payload)
    if payload.supersedes_action_event_id is None and any(
        row.payload_json.get("action_identity") == action_identity for row in actions
    ):
        raise HTTPException(
            status_code=409,
            detail="This opposition action is already recorded.",
        )

    resulting_deadline_refs: list[str] = []
    if payload.action_kind == "deadline_extended":
        extension = payload.deadline_extension
        assert extension is not None
        deadline = session.scalar(
            select(IpDeadline)
            .join(IpDocketEvent, IpDocketEvent.id == IpDeadline.trigger_event_id)
            .where(
                IpDeadline.id == extension.deadline_id,
                IpDeadline.company_id == proceeding.company_id,
                IpDeadline.docket_id == proceeding.docket_id,
                IpDeadline.state.in_(_ACTIVE_DEADLINE_STATES),
                IpDocketEvent.proceeding_id == proceeding.id,
            )
        )
        if deadline is None:
            raise HTTPException(status_code=404, detail="Active opposition deadline not found.")
        impact = deadline_impact(session, context=context, deadline_id=deadline.id)
        replacement = override_deadline(
            session,
            context=context,
            deadline_id=deadline.id,
            payload=IpDeadlineOverrideRequest(
                expected_version=extension.expected_deadline_version,
                new_result_on=extension.new_result_on,
                reason=payload.reason,
                evidence_reference=payload.source_reference,
                impact_token=impact.impact_token,
                responsibilities=extension.responsibilities,
                internal_target_on=extension.internal_target_on,
                reminder_offsets_days=extension.reminder_offsets_days,
            ),
            commit=False,
        )
        resulting_deadline_refs = [replacement.id]
    elif payload.action_kind == "further_evidence_leave_recorded":
        if proceeding.stage not in _FURTHER_EVIDENCE_STAGES:
            raise HTTPException(
                status_code=409,
                detail="Further-evidence leave is out of sequence.",
            )
    elif payload.action_kind == "evidence_package_recorded":
        _assert_evidence_package(actions, proceeding=proceeding, payload=payload)
    elif payload.action_kind in {
        "hearing_preparation_recorded",
        "post_hearing_note_recorded",
    }:
        preparation = payload.hearing_preparation
        assert preparation is not None
        if proceeding.stage not in _HEARING_STAGES:
            raise HTTPException(status_code=409, detail="Hearing work is out of sequence.")
        _assert_hearing(
            session,
            proceeding=proceeding,
            hearing_id=preparation.shared_hearing_id,
            require_completed=payload.action_kind == "post_hearing_note_recorded",
        )
    elif payload.action_kind == "order_recorded":
        _assert_order(session, proceeding=proceeding, payload=payload, actions=actions)
    elif payload.action_kind == "appeal_linked":
        _assert_appeal(
            session,
            context=context,
            proceeding=proceeding,
            payload=payload,
            actions=actions,
        )

    from caseops_api.services.ip_lifecycle import append_ip_docket_event

    append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            proceeding_id=proceeding.id,
            event_kind="opposition_shared_action",
            source=payload.source,
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            resulting_deadline_refs=resulting_deadline_refs,
            supersedes_event_id=payload.supersedes_action_event_id,
            correction_reason=(payload.reason if payload.supersedes_action_event_id else None),
            acknowledged_exception_codes=payload.acknowledged_exception_codes,
            payload={
                "opposition_shared_action": True,
                "action_kind": payload.action_kind,
                "action_identity": action_identity,
                "authorized_confirmation": payload.authorized_confirmation,
                "deadline_extension": (
                    payload.deadline_extension.model_dump(mode="json")
                    if payload.deadline_extension
                    else None
                ),
                "further_evidence_leave": (
                    payload.further_evidence_leave.model_dump(mode="json")
                    if payload.further_evidence_leave
                    else None
                ),
                "evidence_package": (
                    payload.evidence_package.model_dump(mode="json")
                    if payload.evidence_package
                    else None
                ),
                "hearing_preparation": (
                    payload.hearing_preparation.model_dump(mode="json")
                    if payload.hearing_preparation
                    else None
                ),
                "order_details": (
                    payload.order_details.model_dump(mode="json")
                    if payload.order_details
                    else None
                ),
                "appeal_link": (
                    payload.appeal_link.model_dump(mode="json") if payload.appeal_link else None
                ),
                "lawyer_confirmed_by_membership_id": context.membership.id,
            },
        ),
        commit=False,
    )
    workflow = get_shared_workflow(
        session,
        context=context,
        docket_id=docket.id,
        proceeding_id=proceeding.id,
    )
    session.commit()
    return workflow


def assert_shared_stage_prerequisites(
    session: Session,
    *,
    proceeding: IpProceeding,
    to_stage: str,
) -> None:
    required_action = {
        "reserved_for_order": "hearing_preparation_recorded",
        "decided": "order_recorded",
        "appealed": "appeal_linked",
    }.get(to_stage)
    if required_action is None:
        return
    actions = _shared_actions(_proceeding_events(session, proceeding))
    if not any(row.payload_json.get("action_kind") == required_action for row in actions):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_opposition_shared_action_required",
                "message": (
                    f"Record {required_action.replace('_', ' ')} before advancing the "
                    "canonical opposition stage."
                ),
            },
        )


__all__ = [
    "assert_shared_stage_prerequisites",
    "get_shared_workflow",
    "record_shared_action",
]
