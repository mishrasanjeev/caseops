"""Opponent-side opposition work product over canonical events and deadlines."""

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
    IpRuleSet,
    IpRuleVersion,
)
from caseops_api.schemas.ip_deadlines import IpDeadlineProposalRequest
from caseops_api.schemas.ip_lifecycle import IpDocketEventCreateRequest, IpDocketEventResponse
from caseops_api.schemas.ip_oppositions import (
    IpOppositionOpponentActionRequest,
    IpOppositionOpponentDeadlineProposalRequest,
    IpOppositionOpponentDeadlineRecord,
    IpOppositionOpponentWorkflowResponse,
    IpOppositionProfile,
)
from caseops_api.schemas.shared_work import IpSharedTaskCreateRequest
from caseops_api.services.ip_deadline_workflow import _deadline_record, propose_deadline
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.ip_opposition_workspace import (
    _opposition_or_404,
    get_opposition_workspace,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.shared_work import create_ip_shared_task

_WORKFLOW_STAGES = frozenset({"notice_filing_due", "opponent_evidence_due", "reply_evidence_due"})
_DEADLINE_OPEN_STATES = frozenset({"provisional", "candidate", "confirmed", "overdue"})
_FILING_ACTIONS = frozenset({"notice_filed", "notice_refiled"})


def _opponent_opposition(
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
    if proceeding.side != "opponent":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Opponent workflow is only available when the firm represents the opponent.",
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


def _opponent_actions(events: list[IpDocketEvent]) -> list[IpDocketEvent]:
    return [
        row
        for row in events
        if row.event_kind == "opposition_opponent_action"
        and row.payload_json.get("opposition_opponent_action") is True
        and row.candidate_status in {"confirmed", "reconciled"}
    ]


def _profile(events: list[IpDocketEvent]) -> IpOppositionProfile | None:
    for event in reversed(events):
        if event.event_kind != "opposition_profile":
            continue
        value = event.payload_json.get("opposition_profile")
        if isinstance(value, dict):
            return IpOppositionProfile.model_validate(value)
    return None


def _deadline_rows(
    session: Session,
    *,
    proceeding: IpProceeding,
    events: list[IpDocketEvent],
) -> list[tuple[str, IpDeadline]]:
    event_ids = [row.id for row in events]
    if not event_ids:
        return []
    rows = list(
        session.scalars(
            select(IpDeadline)
            .where(
                IpDeadline.company_id == proceeding.company_id,
                IpDeadline.docket_id == proceeding.docket_id,
                IpDeadline.trigger_event_id.in_(event_ids),
            )
            .order_by(IpDeadline.created_at, IpDeadline.id)
        )
    )
    result: list[tuple[str, IpDeadline]] = []
    for row in rows:
        rule = session.get(IpRuleVersion, row.rule_version_id)
        rule_set = session.get(IpRuleSet, rule.rule_set_id) if rule is not None else None
        if (
            rule_set is not None
            and rule_set.role == "opponent"
            and rule_set.stage in _WORKFLOW_STAGES
        ):
            result.append((rule_set.stage, row))
    return result


def _number_is_confirmed(session: Session, proceeding: IpProceeding) -> bool:
    return (
        session.scalar(
            select(IpIdentifier.id).where(
                IpIdentifier.company_id == proceeding.company_id,
                IpIdentifier.proceeding_id == proceeding.id,
                IpIdentifier.identifier_kind == "opposition",
                IpIdentifier.effective_until.is_(None),
                IpIdentifier.reconciliation_status == "confirmed",
            )
        )
        is not None
    )


def _latest_action(
    actions: list[IpDocketEvent], kinds: set[str] | frozenset[str]
) -> IpDocketEvent | None:
    return next(
        (row for row in reversed(actions) if row.payload_json.get("action_kind") in kinds),
        None,
    )


def _accepted_filing(actions: list[IpDocketEvent]) -> IpDocketEvent | None:
    filing = _latest_action(actions, _FILING_ACTIONS)
    rejection = _latest_action(actions, {"notice_filing_rejected"})
    if filing is None or (rejection is not None and rejection.sequence > filing.sequence):
        return None
    return filing


def _active_deadline(
    deadlines: list[tuple[str, IpDeadline]], workflow_stage: str
) -> IpDeadline | None:
    return next(
        (
            row
            for stage, row in reversed(deadlines)
            if stage == workflow_stage and row.state in _DEADLINE_OPEN_STATES
        ),
        None,
    )


def _next_required_action(
    *,
    number_confirmed: bool,
    proceeding: IpProceeding,
    profile: IpOppositionProfile,
    actions: list[IpDocketEvent],
    deadlines: list[tuple[str, IpDeadline]],
) -> str:
    action_kinds = {str(row.payload_json.get("action_kind")) for row in actions}
    if "watch_hit_closed" in action_kinds:
        return "watch_hit_closed_no_proceeding"
    if proceeding.stage == "draft":
        notice_deadline = _active_deadline(deadlines, "notice_filing_due")
        if notice_deadline is None:
            return "propose_notice_filing_deadline"
        if notice_deadline.state not in {"confirmed", "overdue"}:
            return "confirm_notice_filing_deadline"
        if profile.client_instruction_state != "confirmed":
            if "client_instruction_escalated" not in action_kinds:
                return "record_client_instruction_escalation"
            return "await_client_instruction"
        if _accepted_filing(actions) is None:
            if "notice_filing_rejected" in action_kinds:
                return "correct_rejected_notice"
            return "file_notice"
        if not number_confirmed:
            return "record_opposition_number"
        return "advance_to_notice_filed"
    if proceeding.stage == "notice_filed":
        if not number_confirmed:
            return "record_opposition_number"
        return "advance_to_service_pending"
    if proceeding.stage == "service_pending":
        if "notice_served" not in action_kinds:
            return "record_notice_service"
        return "await_counterstatement"
    if proceeding.stage in {"counterstatement_due", "counterstatement_filed"}:
        return "await_counterstatement"
    if proceeding.stage == "opponent_evidence_due":
        evidence_deadline = _active_deadline(deadlines, "opponent_evidence_due")
        if evidence_deadline is None:
            return "propose_opponent_evidence_deadline"
        if evidence_deadline.state not in {"confirmed", "overdue"}:
            return "confirm_opponent_evidence_deadline"
        if "opponent_evidence_decision" not in action_kinds:
            return "record_opponent_evidence_decision"
    if proceeding.stage in {"opponent_evidence_filed", "applicant_evidence_due"}:
        return "await_applicant_evidence"
    if proceeding.stage == "applicant_evidence_filed":
        return "await_applicant_evidence"
    if proceeding.stage == "reply_evidence_due":
        reply_deadline = _active_deadline(deadlines, "reply_evidence_due")
        if reply_deadline is None:
            return "propose_reply_evidence_deadline"
        if reply_deadline.state not in {"confirmed", "overdue"}:
            return "confirm_reply_evidence_deadline"
        if "reply_evidence_decision" not in action_kinds:
            return "record_reply_evidence_decision"
    return "await_hearing_or_later_stage"


def get_opponent_workflow(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
) -> IpOppositionOpponentWorkflowResponse:
    _, proceeding = _opponent_opposition(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        for_update=False,
        required_capability="ip:read",
    )
    events = _proceeding_events(session, proceeding)
    actions = _opponent_actions(events)
    profile = _profile(events)
    if profile is None:
        raise HTTPException(status_code=409, detail="Confirm the opposition profile first.")
    deadlines = _deadline_rows(session, proceeding=proceeding, events=events)
    number_confirmed = _number_is_confirmed(session, proceeding)
    rejection = _latest_action(actions, {"notice_filing_rejected"})
    corrective_task_id = (
        str(rejection.payload_json.get("corrective_task_id"))
        if rejection is not None and rejection.payload_json.get("corrective_task_id")
        else None
    )
    return IpOppositionOpponentWorkflowResponse(
        proceeding_id=proceeding.id,
        represented_side="opponent",
        opposition_number_status=("confirmed" if number_confirmed else "pending_allocation"),
        client_instruction_status=profile.client_instruction_state,
        opponent_actions=[IpDocketEventResponse.model_validate(row) for row in actions],
        deadlines=[
            IpOppositionOpponentDeadlineRecord(
                workflow_stage=stage,
                deadline=_deadline_record(session, row),
            )
            for stage, row in deadlines
        ],
        corrective_task_id=corrective_task_id,
        next_required_action=_next_required_action(
            number_confirmed=number_confirmed,
            proceeding=proceeding,
            profile=profile,
            actions=actions,
            deadlines=deadlines,
        ),
    )


def _assert_action_readiness(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    proceeding: IpProceeding,
    action_kind: str,
) -> None:
    workspace = get_opposition_workspace(
        session,
        context=context,
        docket_id=docket.id,
        proceeding_id=proceeding.id,
    )
    allowed = {"confirmed_opposition_identifier_required"}
    if action_kind in {"client_instruction_escalated", "watch_hit_closed"}:
        allowed.add("confirmed_client_instruction_required")
    gaps = [row for row in workspace.readiness_gaps if row not in allowed]
    if gaps:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ip_opposition_opponent_not_ready", "gaps": gaps},
        )


def record_opponent_action(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionOpponentActionRequest,
) -> IpOppositionOpponentWorkflowResponse:
    docket, proceeding = _opponent_opposition(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        for_update=True,
        required_capability="ip:approve",
    )
    if proceeding.version != payload.expected_proceeding_version:
        raise HTTPException(status_code=409, detail="Proceeding version changed; reload.")
    _assert_action_readiness(
        session,
        context=context,
        docket=docket,
        proceeding=proceeding,
        action_kind=payload.action_kind,
    )
    events = _proceeding_events(session, proceeding)
    profile = _profile(events)
    assert profile is not None  # readiness requires the profile
    expected_stage = {
        "watch_hit_closed": "draft",
        "client_instruction_escalated": "draft",
        "notice_filed": "draft",
        "notice_filing_rejected": "draft",
        "notice_refiled": "draft",
        "notice_served": "service_pending",
        "opponent_evidence_decision": "opponent_evidence_due",
        "reply_evidence_decision": "reply_evidence_due",
    }[payload.action_kind]
    if proceeding.stage != expected_stage:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{payload.action_kind.replace('_', ' ')} requires opposition stage "
                f"{expected_stage!r}; current stage is {proceeding.stage!r}."
            ),
        )
    actions = _opponent_actions(events)
    deadlines = _deadline_rows(session, proceeding=proceeding, events=events)
    required_deadline_stage = {
        "client_instruction_escalated": "notice_filing_due",
        "notice_filed": "notice_filing_due",
        "notice_filing_rejected": "notice_filing_due",
        "notice_refiled": "notice_filing_due",
        "opponent_evidence_decision": "opponent_evidence_due",
        "reply_evidence_decision": "reply_evidence_due",
    }.get(payload.action_kind)
    if required_deadline_stage:
        deadline = _active_deadline(deadlines, required_deadline_stage)
        if deadline is None or deadline.state not in {"confirmed", "overdue"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Confirm the governed {required_deadline_stage.replace('_', ' ')} "
                    "before recording this opponent action."
                ),
            )
    if any(row.payload_json.get("action_kind") == payload.action_kind for row in actions):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This opponent action is already recorded; correct it through supersession.",
        )
    if payload.action_kind == "watch_hit_closed":
        if proceeding.origin_kind != "watch_hit" or _latest_action(actions, _FILING_ACTIONS):
            raise HTTPException(
                status_code=409,
                detail="Only an unfiled watch-hit intake may close without a proceeding.",
            )
    if payload.action_kind == "client_instruction_escalated" and (
        profile.client_instruction_state != "pending"
    ):
        raise HTTPException(status_code=409, detail="Client instruction is not pending.")
    if payload.action_kind in _FILING_ACTIONS and profile.client_instruction_state != "confirmed":
        raise HTTPException(status_code=409, detail="Confirmed client instruction is required.")
    if payload.action_kind == "notice_refiled" and not _latest_action(
        actions, {"notice_filing_rejected"}
    ):
        raise HTTPException(status_code=409, detail="No rejected TM-O filing requires correction.")

    workflow_task_id: str | None = None
    if payload.action_kind in {
        "notice_filing_rejected",
        "client_instruction_escalated",
    }:
        is_rejection = payload.action_kind == "notice_filing_rejected"
        task = create_ip_shared_task(
            session,
            context=context,
            payload=IpSharedTaskCreateRequest(
                docket_id=docket.id,
                title=(
                    "Correct rejected TM-O opposition filing"
                    if is_rejection
                    else "Obtain opponent client instruction before limitation"
                ),
                description=(
                    (
                        f"Correct and resubmit rejected filing {payload.rejection_reference}. "
                        if is_rejection
                        else f"Escalated instruction request {payload.escalation_reference}. "
                    )
                    + f"Source: {payload.source_reference}."
                ),
                owner_membership_id=payload.responsible_membership_id,
                due_on=(payload.corrective_due_on if is_rejection else payload.escalation_due_on),
                status="todo",
                priority="urgent",
            ),
            commit=False,
        )
        workflow_task_id = task.id

    from caseops_api.services.ip_lifecycle import append_ip_docket_event

    append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            proceeding_id=proceeding.id,
            event_kind="opposition_opponent_action",
            source=payload.source,
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            payload={
                "opposition_opponent_action": True,
                "action_kind": payload.action_kind,
                "document_classification": {
                    "watch_hit_closed": "watch_hit_disposition",
                    "client_instruction_escalated": "client_instruction_escalation",
                    "notice_filed": "tm_o_notice",
                    "notice_filing_rejected": "tm_o_rejection",
                    "notice_refiled": "tm_o_notice",
                    "notice_served": "tm_o_notice_service",
                    "opponent_evidence_decision": "rule_45_opponent_evidence",
                    "reply_evidence_decision": "rule_47_reply_evidence",
                }[payload.action_kind],
                "filing_reference": payload.filing_reference,
                "filed_on": payload.filed_on.isoformat() if payload.filed_on else None,
                "evidence_election": payload.evidence_election,
                "verification": (
                    payload.verification.model_dump(mode="json") if payload.verification else None
                ),
                "service": payload.service.model_dump(mode="json") if payload.service else None,
                "rejection_reference": payload.rejection_reference,
                "corrective_due_on": (
                    payload.corrective_due_on.isoformat() if payload.corrective_due_on else None
                ),
                "corrective_task_id": (
                    workflow_task_id if payload.action_kind == "notice_filing_rejected" else None
                ),
                "escalation_reference": payload.escalation_reference,
                "escalation_due_on": (
                    payload.escalation_due_on.isoformat() if payload.escalation_due_on else None
                ),
                "escalation_task_id": (
                    workflow_task_id
                    if payload.action_kind == "client_instruction_escalated"
                    else None
                ),
                "lawyer_confirmed_by_membership_id": context.membership.id,
                "approval_refs": [f"membership:{context.membership.id}"],
            },
        ),
        commit=False,
    )
    workflow = get_opponent_workflow(
        session,
        context=context,
        docket_id=docket.id,
        proceeding_id=proceeding.id,
    )
    session.commit()
    return workflow


def propose_opponent_deadline(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionOpponentDeadlineProposalRequest,
) -> IpOppositionOpponentDeadlineRecord:
    docket, proceeding = _opponent_opposition(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        for_update=True,
        required_capability="ip:approve",
    )
    _assert_action_readiness(
        session,
        context=context,
        docket=docket,
        proceeding=proceeding,
        action_kind="client_instruction_escalated",
    )
    expected_stage = {
        "notice_filing_due": "draft",
        "opponent_evidence_due": "opponent_evidence_due",
        "reply_evidence_due": "reply_evidence_due",
    }[payload.workflow_stage]
    if proceeding.stage != expected_stage:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The {payload.workflow_stage.replace('_', ' ')} rule requires opposition "
                f"stage {expected_stage!r}; current stage is {proceeding.stage!r}."
            ),
        )
    trigger = session.scalar(
        select(IpDocketEvent).where(
            IpDocketEvent.id == payload.trigger_event_id,
            IpDocketEvent.company_id == proceeding.company_id,
            IpDocketEvent.docket_id == proceeding.docket_id,
            IpDocketEvent.proceeding_id == proceeding.id,
            IpDocketEvent.candidate_status.in_(("confirmed", "reconciled")),
        )
    )
    if trigger is None:
        raise HTTPException(status_code=404, detail="Confirmed opposition trigger event not found.")
    rule = session.get(IpRuleVersion, payload.rule_version_id)
    rule_set = session.get(IpRuleSet, rule.rule_set_id) if rule is not None else None
    if rule_set is None or not all(
        (
            rule_set.proceeding_kind == "opposition",
            rule_set.role == "opponent",
            rule_set.stage == payload.workflow_stage,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Opponent opposition deadlines require an exact opposition/opponent/"
                f"{payload.workflow_stage} governed rule."
            ),
        )
    existing = _deadline_rows(
        session,
        proceeding=proceeding,
        events=_proceeding_events(session, proceeding),
    )
    if any(
        stage == payload.workflow_stage and row.state in _DEADLINE_OPEN_STATES
        for stage, row in existing
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active opponent deadline already exists for this workflow stage.",
        )
    deadline = propose_deadline(
        session,
        context=context,
        docket_id=docket_id,
        payload=IpDeadlineProposalRequest(
            title={
                "notice_filing_due": "Opponent TM-O notice filing deadline",
                "opponent_evidence_due": "Opponent Rule 45 evidence deadline",
                "reply_evidence_due": "Opponent Rule 47 reply evidence deadline",
            }[payload.workflow_stage],
            trigger_event_id=payload.trigger_event_id,
            rule_version_id=payload.rule_version_id,
            calendar_version_id=payload.calendar_version_id,
            base_date=payload.base_date,
            base_date_certainty=payload.base_date_certainty,
            date_precision=payload.date_precision,
            is_critical=payload.is_critical,
        ),
    )
    return IpOppositionOpponentDeadlineRecord(
        workflow_stage=payload.workflow_stage,
        deadline=deadline,
    )


def assert_opponent_stage_prerequisites(
    session: Session,
    *,
    proceeding: IpProceeding,
    to_stage: str,
) -> None:
    if proceeding.side != "opponent":
        return
    required_action = {
        "notice_filed": "accepted_notice_filing",
        "counterstatement_due": "notice_served",
        "opponent_evidence_filed": "opponent_evidence_decision",
        "reply_evidence_filed": "reply_evidence_decision",
    }.get(to_stage)
    if required_action is None:
        return
    actions = _opponent_actions(_proceeding_events(session, proceeding))
    satisfied = (
        _accepted_filing(actions) is not None
        if required_action == "accepted_notice_filing"
        else any(row.payload_json.get("action_kind") == required_action for row in actions)
    )
    if not satisfied:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_opposition_opponent_action_required",
                "message": (
                    f"Record the opponent {required_action.replace('_', ' ')} work product "
                    "before advancing the canonical stage."
                ),
            },
        )


__all__ = [
    "assert_opponent_stage_prerequisites",
    "get_opponent_workflow",
    "propose_opponent_deadline",
    "record_opponent_action",
]
