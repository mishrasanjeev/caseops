"""Canonical foreign-associate coordination over existing CaseOps owners."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Communication,
    CommunicationStatus,
    CompanyMembership,
    IpClientInstruction,
    IpCostItem,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpForeignAssociateInstruction,
    Matter,
    MatterOutsideCounselAssignment,
    OutsideCounsel,
    OutsideCounselAssignmentStatus,
    OutsideCounselPanelStatus,
    OutsideCounselSpendRecord,
    OutsideCounselSpendStatus,
)
from caseops_api.schemas.ip_foreign_associates import (
    IpForeignAssociateCreateRequest,
    IpForeignAssociatePageResponse,
    IpForeignAssociateResponse,
    IpForeignAssociateTransactionRequest,
    IpForeignAssociateTransactionResponse,
    IpForeignAssociateWorkspaceResponse,
)
from caseops_api.schemas.ip_lifecycle import IpDocketEventCreateRequest, IpDocketEventResponse
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_lifecycle import append_ip_docket_event
from caseops_api.services.ip_operations import (
    _lock_ip_dockets_in_stable_order,
    _lock_ip_writer_context,
)
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

_APPROVER_ACTIONS = {
    "approve",
    "approve_substantive_response",
    "approve_fee_change",
    "verify_filing_evidence",
    "complete",
    "reassign",
}
_TRANSITIONS: dict[str, dict[str, str]] = {
    "draft": {"approve": "approved", "cancel": "cancelled"},
    "approved": {
        "dispatch": "dispatched",
        "approve_fee_change": "approved",
        "cancel": "cancelled",
    },
    "dispatched": {
        "acknowledge": "acknowledged",
        "approve_fee_change": "dispatched",
        "refuse": "refused",
        "cancel": "cancelled",
    },
    "acknowledged": {
        "record_query": "in_progress",
        "approve_substantive_response": "in_progress",
        "approve_fee_change": "acknowledged",
        "report_filing": "filing_reported",
        "refuse": "refused",
        "cancel": "cancelled",
    },
    "in_progress": {
        "record_query": "in_progress",
        "approve_substantive_response": "in_progress",
        "approve_fee_change": "in_progress",
        "report_filing": "filing_reported",
        "refuse": "refused",
        "cancel": "cancelled",
    },
    "filing_reported": {
        "approve_fee_change": "filing_reported",
        "verify_filing_evidence": "evidence_verified",
    },
    "evidence_verified": {
        "approve_fee_change": "evidence_verified",
        "link_invoice": "invoiced",
    },
    "invoiced": {
        "approve_fee_change": "invoiced",
        "link_invoice": "invoiced",
        "complete": "completed",
    },
    "refused": {"reassign": "superseded", "cancel": "cancelled"},
}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _visible_statement(session: Session, *, context: SessionContext):
    return (
        select(IpForeignAssociateInstruction)
        .join(
            IpDocketRecord,
            (IpDocketRecord.id == IpForeignAssociateInstruction.docket_id)
            & (IpDocketRecord.company_id == IpForeignAssociateInstruction.company_id),
        )
        .outerjoin(
            Matter,
            (Matter.id == IpDocketRecord.matter_id)
            & (Matter.company_id == IpDocketRecord.company_id),
        )
        .where(
            IpForeignAssociateInstruction.company_id == context.company.id,
            IpForeignAssociateInstruction.neutralized_at.is_(None),
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            or_(IpDocketRecord.matter_id.is_(None), Matter.is_active.is_(True)),
            visible_ip_dockets_filter(session, context=context),
        )
    )


def list_ip_foreign_associate_instructions(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str | None,
    instruction_status: str | None,
    outstanding_response: bool | None,
    missing_filing_evidence: bool | None,
    limit: int,
    offset: int,
) -> IpForeignAssociatePageResponse:
    statement = _visible_statement(session, context=context)
    if docket_id:
        statement = statement.where(IpForeignAssociateInstruction.docket_id == docket_id)
    if instruction_status:
        statement = statement.where(IpForeignAssociateInstruction.status == instruction_status)
    if outstanding_response is True:
        statement = statement.where(
            IpForeignAssociateInstruction.status == "dispatched",
            IpForeignAssociateInstruction.acknowledged_at.is_(None),
        )
    elif outstanding_response is False:
        statement = statement.where(
            or_(
                IpForeignAssociateInstruction.status != "dispatched",
                IpForeignAssociateInstruction.acknowledged_at.is_not(None),
            )
        )
    if missing_filing_evidence is True:
        statement = statement.where(
            IpForeignAssociateInstruction.status == "filing_reported",
            IpForeignAssociateInstruction.filing_verified_at.is_(None),
        )
    elif missing_filing_evidence is False:
        statement = statement.where(
            or_(
                IpForeignAssociateInstruction.status != "filing_reported",
                IpForeignAssociateInstruction.filing_verified_at.is_not(None),
            )
        )
    total = (
        session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    rows = list(
        session.scalars(
            statement.order_by(
                IpForeignAssociateInstruction.updated_at.desc(),
                IpForeignAssociateInstruction.id,
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return IpForeignAssociatePageResponse(
        items=[IpForeignAssociateResponse.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_ip_foreign_associate_instruction(
    session: Session,
    *,
    context: SessionContext,
    instruction_id: str,
) -> IpForeignAssociateInstruction:
    row = session.scalar(
        _visible_statement(session, context=context).where(
            IpForeignAssociateInstruction.id == instruction_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Foreign-associate instruction not found.")
    return row


def _require_membership(
    session: Session, *, company_id: str, membership_id: str
) -> CompanyMembership:
    row = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=422, detail="Responsible lawyer is outside this company.")
    return row


def _decode_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _require_approved_associate(
    session: Session,
    *,
    company_id: str,
    counsel_id: str,
    jurisdiction: str,
) -> OutsideCounsel:
    row = session.scalar(
        select(OutsideCounsel).where(
            OutsideCounsel.id == counsel_id,
            OutsideCounsel.company_id == company_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=422, detail="Associate is outside this company.")
    if row.panel_status not in {
        OutsideCounselPanelStatus.ACTIVE,
        OutsideCounselPanelStatus.PREFERRED,
    }:
        raise HTTPException(status_code=422, detail="Associate is not on the active panel.")
    jurisdictions = {value.casefold() for value in _decode_list(row.jurisdictions_json)}
    if jurisdiction.casefold() not in jurisdictions:
        raise HTTPException(
            status_code=422,
            detail="Associate is not approved for the target jurisdiction.",
        )
    return row


def _require_assignment(
    session: Session,
    *,
    company_id: str,
    matter_id: str | None,
    counsel_id: str,
    assignment_id: str | None,
) -> MatterOutsideCounselAssignment | None:
    if matter_id is None:
        if assignment_id is not None:
            raise HTTPException(
                status_code=422,
                detail="A matter assignment cannot be linked to a matterless IP docket.",
            )
        return None
    if assignment_id is None:
        raise HTTPException(
            status_code=422,
            detail="Matter-linked IP work requires the approved outside-counsel assignment.",
        )
    row = session.scalar(
        select(MatterOutsideCounselAssignment).where(
            MatterOutsideCounselAssignment.id == assignment_id,
            MatterOutsideCounselAssignment.company_id == company_id,
            MatterOutsideCounselAssignment.matter_id == matter_id,
            MatterOutsideCounselAssignment.counsel_id == counsel_id,
        )
    )
    if row is None or row.status not in {
        OutsideCounselAssignmentStatus.APPROVED,
        OutsideCounselAssignmentStatus.ACTIVE,
    }:
        raise HTTPException(
            status_code=422,
            detail="Outside-counsel assignment is missing, mismatched, or inactive.",
        )
    return row


def _require_client_authority(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    instruction_id: str | None,
) -> IpClientInstruction | None:
    if instruction_id is None:
        return None
    row = session.scalar(
        select(IpClientInstruction).where(
            IpClientInstruction.id == instruction_id,
            IpClientInstruction.company_id == company_id,
            IpClientInstruction.docket_id == docket_id,
        )
    )
    if row is None or row.status != "accepted" or row.decision != "proceed":
        raise HTTPException(
            status_code=422,
            detail="Client authority must be an accepted proceed instruction for this docket.",
        )
    return row


def _require_cost_item(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    cost_item_id: str,
    nature: str,
) -> IpCostItem:
    row = session.scalar(
        select(IpCostItem).where(
            IpCostItem.id == cost_item_id,
            IpCostItem.company_id == company_id,
            IpCostItem.docket_id == docket_id,
            IpCostItem.cost_nature == nature,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=422,
            detail=f"Linked {nature} cost item is missing or belongs to another docket.",
        )
    return row


def _validate_initial_estimate_budget(
    *, estimate: IpCostItem, assignment: MatterOutsideCounselAssignment | None
) -> None:
    if assignment is None:
        return
    if estimate.currency.casefold() != assignment.currency.casefold():
        raise HTTPException(
            status_code=422,
            detail="Initial associate estimate currency does not match the approved assignment.",
        )
    if assignment.budget_amount_minor is None:
        raise HTTPException(
            status_code=422,
            detail="Approved outside-counsel assignment requires a budget ceiling.",
        )
    if estimate.amount_minor > assignment.budget_amount_minor:
        raise HTTPException(
            status_code=422,
            detail="Initial associate estimate exceeds the approved assignment budget.",
        )


def _document_refs(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    document_refs: list[str],
) -> list[IpDocument]:
    unique_refs = set(document_refs)
    if not unique_refs:
        return []
    rows = list(
        session.scalars(
            select(IpDocument)
            .join(
                IpDocumentLink,
                (IpDocumentLink.document_id == IpDocument.id)
                & (IpDocumentLink.company_id == IpDocument.company_id),
            )
            .where(
                IpDocument.company_id == company_id,
                IpDocument.id.in_(unique_refs),
                IpDocumentLink.docket_id == docket_id,
            )
            .distinct()
        ).all()
    )
    if {row.id for row in rows} != unique_refs:
        raise HTTPException(
            status_code=422,
            detail="Every selected document must be linked to this IP docket.",
        )
    return rows


def _validate_deadline_refs(
    session: Session, *, company_id: str, docket_id: str, deadline_refs: list[str]
) -> None:
    if not deadline_refs:
        return
    found = set(
        session.scalars(
            select(IpDeadline.id).where(
                IpDeadline.company_id == company_id,
                IpDeadline.docket_id == docket_id,
                IpDeadline.id.in_(set(deadline_refs)),
            )
        ).all()
    )
    if found != set(deadline_refs):
        raise HTTPException(status_code=422, detail="Deadline reference belongs elsewhere.")


def _append_transaction_event(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    instruction: IpForeignAssociateInstruction,
    expected_lifecycle_version: int,
    effective_at: datetime,
    responsible_membership_id: str,
    reason: str,
    evidence_refs: list[str],
    document_refs: list[str],
    deadline_refs: list[str],
    payload: dict[str, object],
) -> IpDocketEvent:
    event = append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=expected_lifecycle_version,
            event_kind="foreign_associate_instruction_transaction",
            source="manual",
            effective_at=effective_at,
            responsible_membership_id=responsible_membership_id,
            reason=reason,
            evidence_refs=evidence_refs,
            document_refs=document_refs,
            resulting_deadline_refs=deadline_refs,
            payload=payload,
        ),
        commit=False,
    )
    event.foreign_associate_instruction_id = instruction.id
    return event


def create_ip_foreign_associate_instruction(
    session: Session,
    *,
    context: SessionContext,
    payload: IpForeignAssociateCreateRequest,
) -> IpForeignAssociateInstruction:
    required_capability = "ip:approve" if payload.include_privileged_documents else "ip:write"
    context = _lock_ip_writer_context(
        session, context=context, required_capability=required_capability
    )
    docket = _lock_ip_dockets_in_stable_order(
        session,
        context=context,
        docket_ids={payload.docket_id},
        required_capability=required_capability,
    )[payload.docket_id]
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    _require_membership(
        session,
        company_id=context.company.id,
        membership_id=payload.responsible_membership_id,
    )
    _require_client_authority(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        instruction_id=payload.source_client_instruction_id,
    )
    _require_approved_associate(
        session,
        company_id=context.company.id,
        counsel_id=payload.outside_counsel_id,
        jurisdiction=payload.target_jurisdiction,
    )
    assignment = _require_assignment(
        session,
        company_id=context.company.id,
        matter_id=docket.matter_id,
        counsel_id=payload.outside_counsel_id,
        assignment_id=payload.assignment_id,
    )
    estimate = _require_cost_item(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        cost_item_id=payload.estimate_cost_item_id,
        nature="estimate",
    )
    _validate_initial_estimate_budget(estimate=estimate, assignment=assignment)
    documents = _document_refs(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        document_refs=payload.selected_document_refs,
    )
    privileged_refs = sorted(row.id for row in documents if row.is_privileged)
    if privileged_refs and not payload.include_privileged_documents:
        raise HTTPException(
            status_code=422,
            detail=(
                "Privileged documents are excluded unless explicitly selected "
                "by an IP approver."
            ),
        )
    existing = session.scalar(
        select(IpForeignAssociateInstruction.id).where(
            IpForeignAssociateInstruction.company_id == context.company.id,
            IpForeignAssociateInstruction.instruction_thread_key
            == payload.instruction_thread_key.strip(),
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Instruction thread already exists.")
    now = datetime.now(UTC)
    row = IpForeignAssociateInstruction(
        company_id=context.company.id,
        docket_id=docket.id,
        instruction_thread_key=payload.instruction_thread_key.strip(),
        instruction_version=1,
        row_version=1,
        source_client_instruction_id=payload.source_client_instruction_id,
        client_authority_reference=(
            payload.client_authority_reference.strip()
            if payload.client_authority_reference
            else None
        ),
        target_jurisdiction=payload.target_jurisdiction.strip(),
        outside_counsel_id=payload.outside_counsel_id,
        assignment_id=payload.assignment_id,
        responsible_membership_id=payload.responsible_membership_id,
        scope_json=payload.scope.model_dump(mode="json"),
        selected_document_refs_json=sorted(set(payload.selected_document_refs)),
        privileged_document_refs_json=privileged_refs,
        estimate_cost_item_id=payload.estimate_cost_item_id,
        estimate_terms_json=payload.estimate_terms.model_dump(mode="json"),
        budget_policy_reference=payload.budget_policy_reference.strip(),
        privileged_approved_by_membership_id=(
            context.membership.id if privileged_refs else None
        ),
        privileged_approved_at=now if privileged_refs else None,
        response_due_at=payload.response_due_at,
        created_by_membership_id=context.membership.id,
        updated_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    event = _append_transaction_event(
        session,
        context=context,
        docket=docket,
        instruction=row,
        expected_lifecycle_version=payload.expected_lifecycle_version,
        effective_at=now,
        responsible_membership_id=payload.responsible_membership_id,
        reason=payload.reason,
        evidence_refs=[
            value
            for value in [
                payload.client_authority_reference,
                payload.budget_policy_reference,
            ]
            if value
        ],
        document_refs=row.selected_document_refs_json,
        deadline_refs=[],
        payload={
            "foreign_associate_instruction_id": row.id,
            "transaction_kind": "created",
            "status_before": None,
            "status_after": "draft",
            "row_version_before": 0,
            "row_version_after": 1,
            "outside_counsel_id": row.outside_counsel_id,
            "assignment_id": row.assignment_id,
            "estimate_cost_item_id": row.estimate_cost_item_id,
            "privileged_document_refs": privileged_refs,
        },
    )
    record_from_context(
        session,
        context,
        action="ip_foreign_associate_instruction.created",
        target_type="ip_foreign_associate_instruction",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "event_id": event.id,
            "outside_counsel_id": row.outside_counsel_id,
            "target_jurisdiction": row.target_jurisdiction,
            "privileged_document_count": len(privileged_refs),
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Instruction identity changed; retry.") from exc
    session.refresh(row)
    return row


def _require_dispatch_communication(
    session: Session,
    *,
    company_id: str,
    matter_id: str | None,
    communication_id: str,
    expected_recipient_email: str | None,
) -> Communication:
    row = session.scalar(
        select(Communication).where(
            Communication.id == communication_id,
            Communication.company_id == company_id,
        )
    )
    if row is None or str(row.direction) != "outbound":
        raise HTTPException(
            status_code=422,
            detail="Dispatch Communication is missing, inbound, or belongs to another company.",
        )
    if row.status not in {
        CommunicationStatus.LOGGED,
        CommunicationStatus.SENT,
        CommunicationStatus.DELIVERED,
        CommunicationStatus.OPENED,
    }:
        raise HTTPException(
            status_code=422,
            detail="Dispatch Communication has not reached a sent or manual-dispatch state.",
        )
    if matter_id is not None and row.matter_id != matter_id:
        raise HTTPException(status_code=422, detail="Dispatch Communication belongs elsewhere.")
    if not expected_recipient_email or (
        (row.recipient_email or "").strip().casefold()
        != expected_recipient_email.strip().casefold()
    ):
        raise HTTPException(
            status_code=422,
            detail="Dispatch Communication recipient does not match the approved associate.",
        )
    return row


def _require_spend_record(
    session: Session,
    *,
    company_id: str,
    matter_id: str | None,
    counsel_id: str,
    assignment_id: str | None,
    spend_record_id: str,
) -> OutsideCounselSpendRecord:
    row = session.scalar(
        select(OutsideCounselSpendRecord).where(
            OutsideCounselSpendRecord.id == spend_record_id,
            OutsideCounselSpendRecord.company_id == company_id,
            OutsideCounselSpendRecord.counsel_id == counsel_id,
        )
    )
    if (
        row is None
        or matter_id is None
        or row.matter_id != matter_id
        or (assignment_id is not None and row.assignment_id != assignment_id)
    ):
        raise HTTPException(
            status_code=422,
            detail="Outside-counsel spend record is missing or belongs elsewhere.",
        )
    if not (row.invoice_reference or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Outside-counsel spend record requires its associate invoice reference.",
        )
    return row


def _require_invoice_reconciliation(
    *,
    actual: IpCostItem,
    spend: OutsideCounselSpendRecord,
    use_approved_amount: bool,
) -> None:
    spend_amount = (
        spend.approved_amount_minor
        if use_approved_amount and spend.approved_amount_minor is not None
        else spend.amount_minor
    )
    if (
        actual.currency.casefold() != spend.currency.casefold()
        or actual.amount_minor != spend_amount
    ):
        raise HTTPException(
            status_code=422,
            detail="Associate invoice and actual IP cost amount or currency do not reconcile.",
        )
    if actual.billing_link_type != "invoice" or not actual.billing_link_id:
        raise HTTPException(
            status_code=422,
            detail="Actual IP cost is not linked to canonical client billing.",
        )


def record_ip_foreign_associate_transaction(
    session: Session,
    *,
    context: SessionContext,
    instruction_id: str,
    payload: IpForeignAssociateTransactionRequest,
) -> IpForeignAssociateTransactionResponse:
    visible = get_ip_foreign_associate_instruction(
        session, context=context, instruction_id=instruction_id
    )
    required_capability = (
        "ip:approve" if payload.transaction_kind in _APPROVER_ACTIONS else "ip:write"
    )
    context = _lock_ip_writer_context(
        session, context=context, required_capability=required_capability
    )
    docket = _lock_ip_dockets_in_stable_order(
        session,
        context=context,
        docket_ids={visible.docket_id},
        required_capability=required_capability,
    )[visible.docket_id]
    row = session.scalar(
        select(IpForeignAssociateInstruction)
        .where(
            IpForeignAssociateInstruction.id == visible.id,
            IpForeignAssociateInstruction.company_id == context.company.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Foreign-associate instruction not found.")
    if row.row_version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Instruction version changed; reload.")
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    target_status = _TRANSITIONS.get(row.status, {}).get(payload.transaction_kind)
    if target_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Transaction {payload.transaction_kind} is not valid from {row.status}.",
        )
    _require_membership(
        session,
        company_id=context.company.id,
        membership_id=payload.responsible_membership_id,
    )
    _document_refs(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        document_refs=payload.document_refs,
    )
    _validate_deadline_refs(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        deadline_refs=payload.deadline_refs,
    )
    status_before = row.status
    version_before = row.row_version
    successor: IpForeignAssociateInstruction | None = None
    event_details: dict[str, object] = {}

    if payload.transaction_kind == "approve":
        _require_client_authority(
            session,
            company_id=context.company.id,
            docket_id=docket.id,
            instruction_id=row.source_client_instruction_id,
        )
        _require_approved_associate(
            session,
            company_id=context.company.id,
            counsel_id=row.outside_counsel_id,
            jurisdiction=row.target_jurisdiction,
        )
        _require_assignment(
            session,
            company_id=context.company.id,
            matter_id=docket.matter_id,
            counsel_id=row.outside_counsel_id,
            assignment_id=row.assignment_id,
        )
        _require_cost_item(
            session,
            company_id=context.company.id,
            docket_id=docket.id,
            cost_item_id=row.estimate_cost_item_id,
            nature="estimate",
        )
        documents = _document_refs(
            session,
            company_id=context.company.id,
            docket_id=docket.id,
            document_refs=row.selected_document_refs_json,
        )
        privileged_refs = sorted(
            document.id for document in documents if document.is_privileged
        )
        row.privileged_document_refs_json = privileged_refs
        if privileged_refs:
            row.privileged_approved_by_membership_id = context.membership.id
            row.privileged_approved_at = payload.effective_at
        row.approved_by_membership_id = context.membership.id
        row.approved_at = payload.effective_at
    elif payload.transaction_kind == "dispatch":
        associate = _require_approved_associate(
            session,
            company_id=context.company.id,
            counsel_id=row.outside_counsel_id,
            jurisdiction=row.target_jurisdiction,
        )
        if payload.dispatch_communication_id:
            _require_dispatch_communication(
                session,
                company_id=context.company.id,
                matter_id=docket.matter_id,
                communication_id=payload.dispatch_communication_id,
                expected_recipient_email=associate.primary_contact_email,
            )
        row.dispatch_communication_id = payload.dispatch_communication_id
        row.external_dispatch_reference = payload.external_dispatch_reference
        row.external_delivery_reference = payload.external_delivery_reference
        row.external_delivered_at = payload.external_delivered_at
        row.dispatched_at = payload.effective_at
    elif payload.transaction_kind == "acknowledge":
        row.acknowledged_at = payload.effective_at
        row.acknowledgement_reference = payload.acknowledgement_reference
    elif payload.transaction_kind == "approve_fee_change":
        replacement = _require_cost_item(
            session,
            company_id=context.company.id,
            docket_id=docket.id,
            cost_item_id=str(payload.replacement_estimate_cost_item_id),
            nature="estimate",
        )
        if replacement.id == row.estimate_cost_item_id:
            raise HTTPException(status_code=422, detail="Fee change requires a new estimate.")
        event_details["replaced_estimate_cost_item_id"] = row.estimate_cost_item_id
        event_details["replaced_estimate_terms"] = row.estimate_terms_json
        row.estimate_cost_item_id = replacement.id
        row.estimate_terms_json = payload.replacement_estimate_terms.model_dump(mode="json")
    elif payload.transaction_kind == "report_filing":
        row.filing_identifier = payload.filing_identifier
        row.filing_reported_at = payload.effective_at
        row.filing_evidence_refs_json = sorted(
            set(payload.evidence_refs) | set(payload.document_refs)
        )
    elif payload.transaction_kind == "verify_filing_evidence":
        if not (set(payload.evidence_refs) - set(row.filing_evidence_refs_json)):
            raise HTTPException(
                status_code=422,
                detail="Verification requires evidence independent of the associate filing report.",
            )
        row.filing_verified_at = payload.effective_at
    elif payload.transaction_kind == "link_invoice":
        actual = _require_cost_item(
            session,
            company_id=context.company.id,
            docket_id=docket.id,
            cost_item_id=str(payload.actual_cost_item_id),
            nature="actual",
        )
        spend = _require_spend_record(
            session,
            company_id=context.company.id,
            matter_id=docket.matter_id,
            counsel_id=row.outside_counsel_id,
            assignment_id=row.assignment_id,
            spend_record_id=str(payload.spend_record_id),
        )
        _require_invoice_reconciliation(actual=actual, spend=spend, use_approved_amount=False)
        row.actual_cost_item_id = actual.id
        row.spend_record_id = spend.id
    elif payload.transaction_kind == "complete":
        if row.spend_record_id is None or row.actual_cost_item_id is None:
            raise HTTPException(
                status_code=422,
                detail="Completion requires invoice and cost links.",
            )
        spend = _require_spend_record(
            session,
            company_id=context.company.id,
            matter_id=docket.matter_id,
            counsel_id=row.outside_counsel_id,
            assignment_id=row.assignment_id,
            spend_record_id=row.spend_record_id,
        )
        actual = _require_cost_item(
            session,
            company_id=context.company.id,
            docket_id=docket.id,
            cost_item_id=row.actual_cost_item_id,
            nature="actual",
        )
        if spend.status != OutsideCounselSpendStatus.PAID:
            raise HTTPException(status_code=422, detail="Associate invoice is not paid.")
        _require_invoice_reconciliation(actual=actual, spend=spend, use_approved_amount=True)
        if actual.reconciliation_status != "matched":
            raise HTTPException(
                status_code=422,
                detail="Filing cost is not reconciled to canonical client billing.",
            )
    elif payload.transaction_kind == "reassign":
        replacement_counsel = _require_approved_associate(
            session,
            company_id=context.company.id,
            counsel_id=str(payload.replacement_outside_counsel_id),
            jurisdiction=row.target_jurisdiction,
        )
        replacement_assignment = _require_assignment(
            session,
            company_id=context.company.id,
            matter_id=docket.matter_id,
            counsel_id=replacement_counsel.id,
            assignment_id=payload.replacement_assignment_id,
        )
        replacement_estimate = _require_cost_item(
            session,
            company_id=context.company.id,
            docket_id=docket.id,
            cost_item_id=str(payload.replacement_estimate_cost_item_id),
            nature="estimate",
        )
        successor = IpForeignAssociateInstruction(
            company_id=row.company_id,
            docket_id=row.docket_id,
            instruction_thread_key=row.instruction_thread_key,
            instruction_version=row.instruction_version + 1,
            row_version=1,
            supersedes_instruction_id=row.id,
            source_client_instruction_id=row.source_client_instruction_id,
            client_authority_reference=row.client_authority_reference,
            target_jurisdiction=row.target_jurisdiction,
            outside_counsel_id=replacement_counsel.id,
            assignment_id=replacement_assignment.id if replacement_assignment else None,
            responsible_membership_id=payload.responsible_membership_id,
            scope_json=row.scope_json,
            selected_document_refs_json=row.selected_document_refs_json,
            privileged_document_refs_json=row.privileged_document_refs_json,
            estimate_cost_item_id=replacement_estimate.id,
            estimate_terms_json=payload.replacement_estimate_terms.model_dump(mode="json"),
            budget_policy_reference=row.budget_policy_reference,
            approved_by_membership_id=context.membership.id,
            approved_at=payload.effective_at,
            privileged_approved_by_membership_id=row.privileged_approved_by_membership_id,
            privileged_approved_at=row.privileged_approved_at,
            response_due_at=payload.replacement_response_due_at,
            status="approved",
            created_by_membership_id=context.membership.id,
            updated_by_membership_id=context.membership.id,
        )
        session.add(successor)
        session.flush()
        event_details["successor_instruction_id"] = successor.id
        event_details["replacement_outside_counsel_id"] = successor.outside_counsel_id

    row.status = target_status
    row.row_version += 1
    row.updated_by_membership_id = context.membership.id
    row.updated_at = datetime.now(UTC)
    event = _append_transaction_event(
        session,
        context=context,
        docket=docket,
        instruction=row,
        expected_lifecycle_version=payload.expected_lifecycle_version,
        effective_at=payload.effective_at,
        responsible_membership_id=payload.responsible_membership_id,
        reason=payload.reason,
        evidence_refs=payload.evidence_refs,
        document_refs=payload.document_refs,
        deadline_refs=payload.deadline_refs,
        payload={
            **payload.details,
            **event_details,
            "foreign_associate_instruction_id": row.id,
            "transaction_kind": payload.transaction_kind,
            "status_before": status_before,
            "status_after": target_status,
            "row_version_before": version_before,
            "row_version_after": row.row_version,
            "delivery_is_acknowledgement": False,
            "dispatch_communication_id": row.dispatch_communication_id,
            "external_dispatch_reference": row.external_dispatch_reference,
            "estimate_cost_item_id": row.estimate_cost_item_id,
            "actual_cost_item_id": row.actual_cost_item_id,
            "spend_record_id": row.spend_record_id,
            "filing_identifier": row.filing_identifier,
        },
    )
    record_from_context(
        session,
        context,
        action="ip_foreign_associate_instruction.transaction_recorded",
        target_type="ip_foreign_associate_instruction",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "event_id": event.id,
            "transaction_kind": payload.transaction_kind,
            "status_before": status_before,
            "status_after": target_status,
            "successor_instruction_id": successor.id if successor else None,
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Instruction version changed; reload.") from exc
    session.refresh(row)
    session.refresh(event)
    if successor:
        session.refresh(successor)
    return IpForeignAssociateTransactionResponse(
        instruction=IpForeignAssociateResponse.model_validate(row),
        event=IpDocketEventResponse.model_validate(event),
        successor=(
            IpForeignAssociateResponse.model_validate(successor) if successor else None
        ),
    )


def ip_foreign_associate_workspace(
    session: Session,
    *,
    context: SessionContext,
    instruction_id: str,
) -> IpForeignAssociateWorkspaceResponse:
    row = get_ip_foreign_associate_instruction(
        session, context=context, instruction_id=instruction_id
    )
    counsel = session.scalar(
        select(OutsideCounsel).where(
            OutsideCounsel.id == row.outside_counsel_id,
            OutsideCounsel.company_id == context.company.id,
        )
    )
    if counsel is None:
        raise HTTPException(status_code=404, detail="Linked associate not found.")
    events = list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == context.company.id,
                IpDocketEvent.foreign_associate_instruction_id == row.id,
            )
            .order_by(IpDocketEvent.sequence, IpDocketEvent.id)
        ).all()
    )
    communication = (
        session.scalar(
            select(Communication).where(
                Communication.id == row.dispatch_communication_id,
                Communication.company_id == context.company.id,
            )
        )
        if row.dispatch_communication_id
        else None
    )
    spend = (
        session.scalar(
            select(OutsideCounselSpendRecord).where(
                OutsideCounselSpendRecord.id == row.spend_record_id,
                OutsideCounselSpendRecord.company_id == context.company.id,
            )
        )
        if row.spend_record_id
        else None
    )
    delivered_at = (
        communication.delivered_at if communication is not None else row.external_delivered_at
    )
    delivery_status = (
        str(communication.status)
        if communication is not None
        else ("delivered" if row.external_delivered_at else "externally_dispatched")
        if row.external_dispatch_reference
        else "not_dispatched"
    )
    filing_evidence_status = (
        "verified"
        if row.filing_verified_at
        else "reported_unverified"
        if row.filing_reported_at
        else "not_reported"
    )
    return IpForeignAssociateWorkspaceResponse(
        instruction=IpForeignAssociateResponse.model_validate(row),
        transactions=[IpDocketEventResponse.model_validate(event) for event in events],
        associate_name=counsel.name,
        delivery_status=delivery_status,
        delivered_at=delivered_at,
        acknowledgement_status="received" if row.acknowledged_at else "outstanding",
        filing_evidence_status=filing_evidence_status,
        invoice_status=str(spend.status) if spend else None,
        response_overdue=bool(
            row.response_due_at
            and _as_utc(row.response_due_at) < datetime.now(UTC)
            and row.acknowledged_at is None
        ),
    )
