"""Single-writer renewal and client-instruction commands for IPLF-037A."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Communication,
    IpClientInstruction,
    IpCostItem,
    IpDeadline,
    IpDocketEvent,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
    IpRenewalTerm,
)
from caseops_api.schemas.ip_renewals import (
    IpClientInstructionAcknowledgeRequest,
    IpClientInstructionCreateRequest,
    IpClientInstructionRecord,
    IpRenewalFoundationContract,
    IpRenewalTermCreateRequest,
    IpRenewalTermListResponse,
    IpRenewalTermRecord,
    IpRenewalTermTransitionRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext

_CONFIRMED_DEADLINE_STATES = {"confirmed", "overdue"}
_FILING_EVENT_KINDS = {"filing", "renewal_filing"}
_ACCEPTANCE_EVENT_KINDS = {"acceptance", "renewal_acceptance"}
_TRANSITIONS: dict[str, set[str]] = {
    "due": {"instructed", "filing_in_progress", "filed", "grace", "overdue", "cancelled"},
    "instructed": {"filing_in_progress", "filed", "grace", "overdue", "cancelled"},
    "filing_in_progress": {"filed", "grace", "overdue", "cancelled"},
    "filed": {"accepted", "grace", "overdue", "cancelled"},
    "accepted": {"completed", "cancelled"},
    "grace": {"filing_in_progress", "filed", "overdue", "cancelled"},
    "overdue": {"filing_in_progress", "filed", "grace", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


def _assert_reference_unchanged(
    *, current: str | None, proposed: str | None, label: str
) -> None:
    if current is not None and proposed is not None and current != proposed:
        raise _conflict(
            "ip_renewal_evidence_immutable",
            f"Recorded {label} evidence cannot be replaced; use the legal-event correction flow.",
        )


def _docket(session: Session, context: SessionContext, docket_id: str, *, write: bool):
    from caseops_api.services.ip_operations import _docket_or_404

    return _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=write,
        required_capability="ip:write",
    )


def _term(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    write: bool,
) -> tuple[object, IpRenewalTerm]:
    docket = _docket(session, context, docket_id, write=write)
    statement = select(IpRenewalTerm).where(
        IpRenewalTerm.id == term_id,
        IpRenewalTerm.company_id == context.company.id,
        IpRenewalTerm.docket_id == docket.id,
    )
    if write:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="IP renewal term not found.")
    return docket, row


def _event(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    event_id: str,
    kinds: set[str],
    label: str,
) -> IpDocketEvent:
    row = session.scalar(
        select(IpDocketEvent).where(
            IpDocketEvent.id == event_id,
            IpDocketEvent.company_id == context.company.id,
            IpDocketEvent.docket_id == docket_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} event not found.")
    if row.candidate_status != "confirmed" or row.event_kind not in kinds:
        raise _conflict(
            "ip_renewal_event_not_verified",
            f"{label} must be a confirmed {', '.join(sorted(kinds))} event.",
        )
    return row


def _deadline(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    deadline_id: str,
    kind: str,
    label: str,
) -> IpDeadline:
    row = session.scalar(
        select(IpDeadline).where(
            IpDeadline.id == deadline_id,
            IpDeadline.company_id == context.company.id,
            IpDeadline.docket_id == docket_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} deadline not found.")
    if row.state not in _CONFIRMED_DEADLINE_STATES or row.deadline_kind != kind:
        raise _conflict(
            "ip_renewal_deadline_not_confirmed",
            f"{label} must be a confirmed {kind} legal deadline.",
        )
    return row


def _cost_item(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    cost_item_id: str,
) -> IpCostItem:
    row = session.scalar(
        select(IpCostItem).where(
            IpCostItem.id == cost_item_id,
            IpCostItem.company_id == context.company.id,
            IpCostItem.docket_id == docket_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="IP renewal fee cost item not found.")
    return row


def _document(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    document_id: str,
) -> IpDocument:
    row = session.scalar(
        select(IpDocument).where(
            IpDocument.id == document_id,
            IpDocument.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="IP renewal certificate not found.")
    current_version = session.scalar(
        select(IpDocumentVersion).where(
            IpDocumentVersion.company_id == context.company.id,
            IpDocumentVersion.document_id == row.id,
            IpDocumentVersion.version == row.current_version,
        )
    )
    linked = session.scalar(
        select(IpDocumentLink.id).where(
            IpDocumentLink.company_id == context.company.id,
            IpDocumentLink.document_id == row.id,
            IpDocumentLink.docket_id == docket_id,
        )
    )
    if current_version is None or current_version.state != "accepted" or linked is None:
        raise _conflict(
            "ip_renewal_certificate_not_accepted",
            "The certificate must be an accepted current IP document linked to this docket.",
        )
    return row


def _instructions(
    session: Session, *, company_id: str, term_id: str
) -> list[IpClientInstruction]:
    return list(
        session.scalars(
            select(IpClientInstruction)
            .where(
                IpClientInstruction.company_id == company_id,
                IpClientInstruction.renewal_term_id == term_id,
            )
            .order_by(IpClientInstruction.instruction_version)
        ).all()
    )


def _record(session: Session, row: IpRenewalTerm) -> IpRenewalTermRecord:
    return IpRenewalTermRecord.model_validate(row).model_copy(
        update={
            "instructions": [
                IpClientInstructionRecord.model_validate(instruction)
                for instruction in _instructions(
                    session, company_id=row.company_id, term_id=row.id
                )
            ]
        }
    )


def renewal_foundation_contract() -> IpRenewalFoundationContract:
    return IpRenewalFoundationContract()


def list_renewal_terms(
    session: Session, *, context: SessionContext, docket_id: str
) -> IpRenewalTermListResponse:
    docket = _docket(session, context, docket_id, write=False)
    rows = list(
        session.scalars(
            select(IpRenewalTerm)
            .where(
                IpRenewalTerm.company_id == context.company.id,
                IpRenewalTerm.docket_id == docket.id,
            )
            .order_by(IpRenewalTerm.term_sequence, IpRenewalTerm.id)
        ).all()
    )
    return IpRenewalTermListResponse(
        items=[_record(session, row) for row in rows], total=len(rows)
    )


def create_renewal_term(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpRenewalTermCreateRequest,
) -> IpRenewalTermRecord:
    docket = _docket(session, context, docket_id, write=True)
    _event(
        session,
        context=context,
        docket_id=docket.id,
        event_id=payload.registration_event_id,
        kinds={"registration"},
        label="Registration",
    )
    _deadline(
        session,
        context=context,
        docket_id=docket.id,
        deadline_id=payload.renewal_deadline_id,
        kind="renewal",
        label="Renewal",
    )
    if payload.grace_deadline_id:
        _deadline(
            session,
            context=context,
            docket_id=docket.id,
            deadline_id=payload.grace_deadline_id,
            kind="renewal_grace",
            label="Grace-period",
        )
    if payload.fee_cost_item_id:
        _cost_item(
            session,
            context=context,
            docket_id=docket.id,
            cost_item_id=payload.fee_cost_item_id,
        )
    duplicate = session.scalar(
        select(IpRenewalTerm.id).where(
            IpRenewalTerm.company_id == context.company.id,
            IpRenewalTerm.docket_id == docket.id,
            IpRenewalTerm.registration_event_id == payload.registration_event_id,
            IpRenewalTerm.renewal_deadline_id == payload.renewal_deadline_id,
        )
    )
    if duplicate is not None:
        raise _conflict(
            "ip_renewal_term_exists",
            "A renewal term already exists for this registration event and deadline.",
        )
    next_sequence = int(
        session.scalar(
            select(func.coalesce(func.max(IpRenewalTerm.term_sequence), 0)).where(
                IpRenewalTerm.company_id == context.company.id,
                IpRenewalTerm.docket_id == docket.id,
            )
        )
        or 0
    ) + 1
    row = IpRenewalTerm(
        company_id=context.company.id,
        docket_id=docket.id,
        term_sequence=next_sequence,
        registration_event_id=payload.registration_event_id,
        renewal_deadline_id=payload.renewal_deadline_id,
        grace_deadline_id=payload.grace_deadline_id,
        fee_cost_item_id=payload.fee_cost_item_id,
        state="due",
        version=1,
        created_by_membership_id=context.membership.id,
        updated_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_renewal_term.created",
        target_type="ip_renewal_term",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "registration_event_id": row.registration_event_id,
            "renewal_deadline_id": row.renewal_deadline_id,
            "grace_deadline_id": row.grace_deadline_id,
        },
    )
    session.commit()
    session.refresh(row)
    return _record(session, row)


def create_client_instruction(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    payload: IpClientInstructionCreateRequest,
) -> IpRenewalTermRecord:
    docket, term = _term(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        write=True,
    )
    if term.state in {"completed", "cancelled"}:
        raise _conflict(
            "ip_renewal_term_terminal",
            "A terminal renewal term cannot receive a new client instruction.",
        )
    current = session.scalar(
        select(IpClientInstruction)
        .where(
            IpClientInstruction.company_id == context.company.id,
            IpClientInstruction.renewal_term_id == term.id,
            IpClientInstruction.status != "superseded",
        )
        .order_by(IpClientInstruction.instruction_version.desc())
        .with_for_update()
    )
    if current is None:
        if payload.expected_current_instruction_id is not None:
            raise _conflict(
                "ip_client_instruction_stale",
                "No current client instruction exists; refresh and retry.",
            )
        instruction_version = 1
    else:
        if (
            payload.expected_current_instruction_id != current.id
            or payload.expected_current_row_version != current.row_version
        ):
            raise _conflict(
                "ip_client_instruction_stale",
                "The current client instruction changed; refresh before creating a revision.",
            )
        current.status = "superseded"
        current.row_version += 1
        current.updated_at = _now()
        instruction_version = current.instruction_version + 1
    if payload.source_communication_id:
        communication = session.scalar(
            select(Communication).where(
                Communication.id == payload.source_communication_id,
                Communication.company_id == context.company.id,
            )
        )
        if communication is None:
            raise HTTPException(status_code=404, detail="Source communication not found.")
    row = IpClientInstruction(
        company_id=context.company.id,
        docket_id=term.docket_id,
        renewal_term_id=term.id,
        instruction_version=instruction_version,
        row_version=1,
        decision=payload.decision,
        status="pending",
        scope_json=payload.scope,
        options_json=payload.options,
        instruction_deadline_at=payload.instruction_deadline_at,
        source_channel=payload.source_channel.strip(),
        source_communication_id=payload.source_communication_id,
        authority_name=payload.authority_name.strip(),
        authority_reference=(
            payload.authority_reference.strip() if payload.authority_reference else None
        ),
        evidence_refs_json=[reference.strip() for reference in payload.evidence_refs],
        received_at=payload.received_at,
        supersedes_instruction_id=current.id if current is not None else None,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_client_instruction.created",
        target_type="ip_client_instruction",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "renewal_term_id": term.id,
            "instruction_version": row.instruction_version,
            "decision": row.decision,
            "supersedes_instruction_id": row.supersedes_instruction_id,
        },
    )
    session.commit()
    session.refresh(term)
    return _record(session, term)


def acknowledge_client_instruction(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    instruction_id: str,
    payload: IpClientInstructionAcknowledgeRequest,
) -> IpRenewalTermRecord:
    docket, term = _term(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        write=True,
    )
    instruction = session.scalar(
        select(IpClientInstruction)
        .where(
            IpClientInstruction.id == instruction_id,
            IpClientInstruction.company_id == context.company.id,
            IpClientInstruction.docket_id == docket.id,
            IpClientInstruction.renewal_term_id == term.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if instruction is None:
        raise HTTPException(status_code=404, detail="Client instruction not found.")
    if (
        instruction.status != payload.expected_status
        or instruction.row_version != payload.expected_row_version
        or _aware(instruction.updated_at) != _aware(payload.expected_updated_at)
    ):
        raise _conflict(
            "ip_client_instruction_stale",
            "The client instruction changed; refresh before acknowledging it.",
        )
    if payload.resulting_event_id:
        _event(
            session,
            context=context,
            docket_id=docket.id,
            event_id=payload.resulting_event_id,
            kinds={"client_instruction"},
            label="Resulting instruction",
        )
    now = _now()
    instruction.status = payload.status
    instruction.row_version += 1
    instruction.acknowledged_at = now
    instruction.acknowledged_by_membership_id = context.membership.id
    instruction.acknowledgement_reason = payload.reason.strip()
    instruction.resulting_event_id = payload.resulting_event_id
    instruction.updated_at = now
    if payload.status == "accepted" and instruction.decision == "renew":
        term.state = "instructed"
        term.version += 1
        term.updated_by_membership_id = context.membership.id
        term.updated_at = now
    record_from_context(
        session,
        context,
        action=f"ip_client_instruction.{payload.status}",
        target_type="ip_client_instruction",
        target_id=instruction.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "renewal_term_id": term.id,
            "instruction_version": instruction.instruction_version,
            "decision": instruction.decision,
            "resulting_event_id": instruction.resulting_event_id,
        },
    )
    session.commit()
    session.refresh(term)
    return _record(session, term)


def transition_renewal_term(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    payload: IpRenewalTermTransitionRequest,
) -> IpRenewalTermRecord:
    docket, term = _term(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        write=True,
    )
    if (
        term.state != payload.expected_state
        or term.version != payload.expected_version
        or _aware(term.updated_at) != _aware(payload.expected_updated_at)
    ):
        raise _conflict(
            "ip_renewal_term_stale",
            "The renewal term changed; refresh before transitioning it.",
        )
    if payload.target_state not in _TRANSITIONS[term.state]:
        raise _conflict(
            "ip_renewal_transition_invalid",
            f"A renewal cannot transition from {term.state} to {payload.target_state}.",
        )
    if payload.target_state == "instructed":
        accepted_renewal_instruction = session.scalar(
            select(IpClientInstruction.id).where(
                IpClientInstruction.company_id == context.company.id,
                IpClientInstruction.renewal_term_id == term.id,
                IpClientInstruction.status == "accepted",
                IpClientInstruction.decision == "renew",
            )
        )
        if accepted_renewal_instruction is None:
            raise _conflict(
                "ip_renewal_instruction_required",
                "An accepted renew instruction is required before marking the term instructed.",
            )
    _assert_reference_unchanged(
        current=term.fee_cost_item_id,
        proposed=payload.fee_cost_item_id,
        label="fee",
    )
    _assert_reference_unchanged(
        current=term.filing_event_id,
        proposed=payload.filing_event_id,
        label="filing",
    )
    _assert_reference_unchanged(
        current=term.acceptance_event_id,
        proposed=payload.acceptance_event_id,
        label="acceptance",
    )
    _assert_reference_unchanged(
        current=term.certificate_document_id,
        proposed=payload.certificate_document_id,
        label="certificate",
    )
    _assert_reference_unchanged(
        current=term.next_term_deadline_id,
        proposed=payload.next_term_deadline_id,
        label="next-term deadline",
    )
    if payload.fee_cost_item_id:
        _cost_item(
            session,
            context=context,
            docket_id=docket.id,
            cost_item_id=payload.fee_cost_item_id,
        )
    if payload.filing_event_id:
        _event(
            session,
            context=context,
            docket_id=docket.id,
            event_id=payload.filing_event_id,
            kinds=_FILING_EVENT_KINDS,
            label="Renewal filing",
        )
    if payload.acceptance_event_id:
        _event(
            session,
            context=context,
            docket_id=docket.id,
            event_id=payload.acceptance_event_id,
            kinds=_ACCEPTANCE_EVENT_KINDS,
            label="Registry acceptance",
        )
    if payload.certificate_document_id:
        _document(
            session,
            context=context,
            docket_id=docket.id,
            document_id=payload.certificate_document_id,
        )
    if payload.next_term_deadline_id:
        next_deadline = _deadline(
            session,
            context=context,
            docket_id=docket.id,
            deadline_id=payload.next_term_deadline_id,
            kind="renewal",
            label="Next-term renewal",
        )
        acceptance_event_id = payload.acceptance_event_id or term.acceptance_event_id
        if next_deadline.trigger_event_id != acceptance_event_id:
            raise _conflict(
                "ip_renewal_next_term_trigger_mismatch",
                "The next-term deadline must be calculated from this term's acceptance event.",
            )
    now = _now()
    term.state = payload.target_state
    term.version += 1
    term.updated_by_membership_id = context.membership.id
    term.updated_at = now
    if payload.fee_cost_item_id is not None:
        term.fee_cost_item_id = payload.fee_cost_item_id
    if payload.filing_initiated_reference is not None:
        term.filing_initiated_reference = payload.filing_initiated_reference.strip()
    if payload.filing_event_id is not None:
        term.filing_event_id = payload.filing_event_id
    if payload.acceptance_event_id is not None:
        term.acceptance_event_id = payload.acceptance_event_id
    if payload.certificate_document_id is not None:
        term.certificate_document_id = payload.certificate_document_id
    if payload.next_term_deadline_id is not None:
        term.next_term_deadline_id = payload.next_term_deadline_id
    if payload.target_state == "completed":
        term.completed_at = now
    record_from_context(
        session,
        context,
        action=f"ip_renewal_term.{payload.target_state}",
        target_type="ip_renewal_term",
        target_id=term.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "from_state": payload.expected_state,
            "to_state": payload.target_state,
            "reason": payload.reason.strip(),
            "filing_event_id": term.filing_event_id,
            "acceptance_event_id": term.acceptance_event_id,
            "certificate_document_id": term.certificate_document_id,
            "next_term_deadline_id": term.next_term_deadline_id,
        },
    )
    session.commit()
    session.refresh(term)
    return _record(session, term)
