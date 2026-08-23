"""Applicant-side opposition work product over canonical events and deadlines."""

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
    IpOppositionApplicantActionRequest,
    IpOppositionApplicantDeadlineProposalRequest,
    IpOppositionApplicantDeadlineRecord,
    IpOppositionApplicantWorkflowResponse,
)
from caseops_api.services.ip_deadline_workflow import _deadline_record, propose_deadline
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.ip_opposition_workspace import (
    _opposition_or_404,
    assert_opposition_workspace_ready,
)
from caseops_api.services.session_context import SessionContext

_WORKFLOW_STAGES = frozenset({"counterstatement_due", "applicant_evidence_due"})
_DEADLINE_OPEN_STATES = frozenset({"provisional", "candidate", "confirmed", "overdue"})


def _applicant_opposition(
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
    if proceeding.side != "applicant":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Applicant workflow is only available when the firm represents the applicant.",
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


def _applicant_actions(events: list[IpDocketEvent]) -> list[IpDocketEvent]:
    return [
        row
        for row in events
        if row.event_kind == "opposition_applicant_action"
        and row.payload_json.get("opposition_applicant_action") is True
        and row.candidate_status in {"confirmed", "reconciled"}
    ]


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
        if rule_set is not None and rule_set.stage in _WORKFLOW_STAGES:
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


def _next_required_action(
    *,
    number_confirmed: bool,
    proceeding: IpProceeding,
    actions: list[IpDocketEvent],
    deadlines: list[tuple[str, IpDeadline]],
) -> str:
    if not number_confirmed:
        return "record_opposition_number"
    actions_by_kind = {str(row.payload_json.get("action_kind")): row for row in actions}
    deadline_by_stage = {
        stage: row for stage, row in deadlines if row.state in _DEADLINE_OPEN_STATES
    }
    counterstatement = deadline_by_stage.get("counterstatement_due")
    if proceeding.stage in {"draft", "notice_filed", "service_pending", "counterstatement_due"}:
        if counterstatement is None:
            return "propose_counterstatement_deadline"
        if counterstatement.state not in {"confirmed", "overdue"}:
            return "confirm_counterstatement_deadline"
    if proceeding.stage in {"draft", "notice_filed", "service_pending"}:
        return "advance_to_counterstatement_due"
    if proceeding.stage == "counterstatement_due":
        if "counterstatement_filed" not in actions_by_kind:
            return "file_counterstatement"
    if proceeding.stage == "counterstatement_filed":
        if "counterstatement_served" not in actions_by_kind:
            return "record_counterstatement_service"
    if proceeding.stage == "applicant_evidence_due":
        evidence = deadline_by_stage.get("applicant_evidence_due")
        if evidence is None:
            return "propose_applicant_evidence_deadline"
        if evidence.state not in {"confirmed", "overdue"}:
            return "confirm_applicant_evidence_deadline"
        if "applicant_evidence_decision" not in actions_by_kind:
            return "record_applicant_evidence_decision"
    return "await_opponent_or_later_stage"


def get_applicant_workflow(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
) -> IpOppositionApplicantWorkflowResponse:
    _, proceeding = _applicant_opposition(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        for_update=False,
        required_capability="ip:read",
    )
    events = _proceeding_events(session, proceeding)
    actions = _applicant_actions(events)
    deadlines = _deadline_rows(
        session,
        proceeding=proceeding,
        events=events,
    )
    number_confirmed = _number_is_confirmed(session, proceeding)
    return IpOppositionApplicantWorkflowResponse(
        proceeding_id=proceeding.id,
        represented_side="applicant",
        opposition_number_status=("confirmed" if number_confirmed else "pending_allocation"),
        applicant_actions=[IpDocketEventResponse.model_validate(row) for row in actions],
        deadlines=[
            IpOppositionApplicantDeadlineRecord(
                workflow_stage=stage,
                deadline=_deadline_record(session, row),
            )
            for stage, row in deadlines
        ],
        next_required_action=_next_required_action(
            number_confirmed=number_confirmed,
            proceeding=proceeding,
            actions=actions,
            deadlines=deadlines,
        ),
    )


def record_applicant_action(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionApplicantActionRequest,
) -> IpOppositionApplicantWorkflowResponse:
    docket, proceeding = _applicant_opposition(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        for_update=True,
        required_capability="ip:approve",
    )
    if proceeding.version != payload.expected_proceeding_version:
        raise HTTPException(status_code=409, detail="Proceeding version changed; reload.")
    assert_opposition_workspace_ready(session, proceeding=proceeding)
    expected_stage = {
        "counterstatement_filed": "counterstatement_due",
        "counterstatement_served": "counterstatement_filed",
        "applicant_evidence_decision": "applicant_evidence_due",
    }[payload.action_kind]
    if proceeding.stage != expected_stage:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{payload.action_kind.replace('_', ' ')} requires opposition stage "
                f"{expected_stage!r}; current stage is {proceeding.stage!r}."
            ),
        )
    actions = _applicant_actions(_proceeding_events(session, proceeding))
    if any(row.payload_json.get("action_kind") == payload.action_kind for row in actions):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This applicant action is already recorded; correct it through supersession.",
        )

    from caseops_api.services.ip_lifecycle import append_ip_docket_event

    append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            proceeding_id=proceeding.id,
            event_kind="opposition_applicant_action",
            source=payload.source,
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            payload={
                "opposition_applicant_action": True,
                "action_kind": payload.action_kind,
                "document_classification": {
                    "counterstatement_filed": "tm_o_counterstatement",
                    "counterstatement_served": "tm_o_counterstatement_service",
                    "applicant_evidence_decision": "rule_46_applicant_evidence",
                }[payload.action_kind],
                "filing_reference": payload.filing_reference,
                "filed_on": payload.filed_on.isoformat() if payload.filed_on else None,
                "evidence_election": payload.evidence_election,
                "verification": (
                    payload.verification.model_dump(mode="json") if payload.verification else None
                ),
                "service": (payload.service.model_dump(mode="json") if payload.service else None),
                "lawyer_confirmed_by_membership_id": context.membership.id,
                "approval_refs": [f"membership:{context.membership.id}"],
            },
        ),
        commit=False,
    )
    workflow = get_applicant_workflow(
        session,
        context=context,
        docket_id=docket.id,
        proceeding_id=proceeding.id,
    )
    session.commit()
    return workflow


def propose_applicant_deadline(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionApplicantDeadlineProposalRequest,
) -> IpOppositionApplicantDeadlineRecord:
    _, proceeding = _applicant_opposition(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        for_update=False,
        required_capability="ip:approve",
    )
    assert_opposition_workspace_ready(session, proceeding=proceeding)
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
            rule_set.role == "applicant",
            rule_set.stage == payload.workflow_stage,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Applicant opposition deadlines require an exact opposition/applicant/"
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
            detail="An active applicant deadline already exists for this workflow stage.",
        )
    deadline = propose_deadline(
        session,
        context=context,
        docket_id=docket_id,
        payload=IpDeadlineProposalRequest(
            title={
                "counterstatement_due": "Applicant counterstatement deadline",
                "applicant_evidence_due": "Applicant evidence deadline",
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
    return IpOppositionApplicantDeadlineRecord(
        workflow_stage=payload.workflow_stage,
        deadline=deadline,
    )


def assert_applicant_stage_prerequisites(
    session: Session,
    *,
    proceeding: IpProceeding,
    to_stage: str,
) -> None:
    if proceeding.side != "applicant":
        return
    required_action = {
        "counterstatement_filed": "counterstatement_filed",
        "applicant_evidence_filed": "applicant_evidence_decision",
    }.get(to_stage)
    if required_action is None:
        return
    actions = _applicant_actions(_proceeding_events(session, proceeding))
    if not any(row.payload_json.get("action_kind") == required_action for row in actions):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_opposition_applicant_action_required",
                "message": (
                    f"Record the applicant {required_action.replace('_', ' ')} work product "
                    "before advancing the canonical stage."
                ),
            },
        )


__all__ = [
    "assert_applicant_stage_prerequisites",
    "get_applicant_workflow",
    "propose_applicant_deadline",
    "record_applicant_action",
]
