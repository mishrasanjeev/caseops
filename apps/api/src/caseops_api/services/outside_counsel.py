from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterActivity,
    MatterInvoice,
    MatterOutsideCounselAssignment,
    MembershipRole,
    OutsideCounsel,
    OutsideCounselAssignmentStatus,
    OutsideCounselPanelStatus,
    OutsideCounselSpendRecord,
    OutsideCounselSpendStatus,
)
from caseops_api.schemas.outside_counsel import (
    OutsideCounselAssignmentCreateRequest,
    OutsideCounselAssignmentRecord,
    OutsideCounselCreateRequest,
    OutsideCounselPortfolioSummary,
    OutsideCounselRecommendationRecord,
    OutsideCounselRecommendationRequest,
    OutsideCounselRecommendationResponse,
    OutsideCounselRecord,
    OutsideCounselSpendRecordCreateRequest,
    OutsideCounselUpdateRequest,
    OutsideCounselWorkspaceResponse,
)
from caseops_api.schemas.outside_counsel import (
    OutsideCounselSpendRecord as OutsideCounselSpendRecordResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext


def _now() -> datetime:
    return datetime.now(UTC)


def _raise_forbidden(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def _raise_bad_request(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _raise_not_found(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def _raise_conflict(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def _normalize_string_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = value.strip()
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(candidate)
    return cleaned


def _encode_string_list(values: list[str]) -> str | None:
    cleaned = _normalize_string_list(values)
    if not cleaned:
        return None
    return json.dumps(cleaned)


def _decode_string_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return _normalize_string_list([str(item) for item in loaded])


def _require_management_role(context: SessionContext) -> None:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        _raise_forbidden("Only owners and admins can manage outside counsel profiles.")


def _get_company_matter(session: Session, *, context: SessionContext, matter_id: str) -> Matter:
    matter = session.scalar(
        select(Matter).where(Matter.id == matter_id, Matter.company_id == context.company.id)
    )
    if not matter:
        _raise_not_found("Matter was not found in the current company.")
    return matter


def _get_outside_counsel_model(
    session: Session,
    *,
    company_id: str,
    counsel_id: str,
) -> OutsideCounsel:
    counsel = session.scalar(
        select(OutsideCounsel)
        .options(
            selectinload(OutsideCounsel.assignments).joinedload(
                MatterOutsideCounselAssignment.matter
            ),
            selectinload(OutsideCounsel.spend_records),
        )
        .where(OutsideCounsel.id == counsel_id, OutsideCounsel.company_id == company_id)
    )
    if not counsel:
        _raise_not_found("Outside counsel profile was not found in the current company.")
    return counsel


def _get_assignment_model(
    session: Session,
    *,
    company_id: str,
    assignment_id: str,
) -> MatterOutsideCounselAssignment:
    assignment = session.scalar(
        select(MatterOutsideCounselAssignment).where(
            MatterOutsideCounselAssignment.id == assignment_id,
            MatterOutsideCounselAssignment.company_id == company_id,
        )
    )
    if not assignment:
        _raise_not_found("Outside counsel assignment was not found in the current company.")
    return assignment


def _append_matter_activity(
    session: Session,
    *,
    matter_id: str,
    actor_membership_id: str | None,
    event_type: str,
    title: str,
    detail: str | None,
) -> None:
    session.add(
        MatterActivity(
            matter_id=matter_id,
            actor_membership_id=actor_membership_id,
            event_type=event_type,
            title=title,
            detail=detail,
        )
    )


def _serialize_counsel_record(
    counsel: OutsideCounsel,
    *,
    assignments: list[MatterOutsideCounselAssignment],
    spend_records: list[OutsideCounselSpendRecord],
) -> OutsideCounselRecord:
    active_assignment_statuses = {
        OutsideCounselAssignmentStatus.APPROVED,
        OutsideCounselAssignmentStatus.ACTIVE,
    }
    approved_spend = sum(record.approved_amount_minor for record in spend_records)
    return OutsideCounselRecord(
        id=counsel.id,
        company_id=counsel.company_id,
        name=counsel.name,
        primary_contact_name=counsel.primary_contact_name,
        primary_contact_email=counsel.primary_contact_email,
        primary_contact_phone=counsel.primary_contact_phone,
        firm_city=counsel.firm_city,
        jurisdictions=_decode_string_list(counsel.jurisdictions_json),
        practice_areas=_decode_string_list(counsel.practice_areas_json),
        panel_status=counsel.panel_status,
        internal_notes=counsel.internal_notes,
        total_matters_count=len(assignments),
        active_matters_count=sum(
            1 for item in assignments if item.status in active_assignment_statuses
        ),
        total_spend_minor=sum(record.amount_minor for record in spend_records),
        approved_spend_minor=approved_spend,
        created_at=counsel.created_at,
        updated_at=counsel.updated_at,
    )


def _serialize_assignment_record(
    assignment: MatterOutsideCounselAssignment,
) -> OutsideCounselAssignmentRecord:
    return OutsideCounselAssignmentRecord(
        id=assignment.id,
        company_id=assignment.company_id,
        matter_id=assignment.matter_id,
        matter_title=assignment.matter.title,
        matter_code=assignment.matter.matter_code,
        counsel_id=assignment.counsel_id,
        counsel_name=assignment.counsel.name,
        assigned_by_membership_id=assignment.assigned_by_membership_id,
        assigned_by_name=(
            assignment.assigned_by_membership.user.full_name
            if assignment.assigned_by_membership and assignment.assigned_by_membership.user
            else None
        ),
        role_summary=assignment.role_summary,
        budget_amount_minor=assignment.budget_amount_minor,
        currency=assignment.currency,
        status=assignment.status,
        internal_notes=assignment.internal_notes,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _serialize_spend_record(
    record: OutsideCounselSpendRecord,
) -> OutsideCounselSpendRecordResponse:
    return OutsideCounselSpendRecordResponse(
        id=record.id,
        company_id=record.company_id,
        matter_id=record.matter_id,
        matter_title=record.matter.title,
        matter_code=record.matter.matter_code,
        counsel_id=record.counsel_id,
        counsel_name=record.counsel.name,
        assignment_id=record.assignment_id,
        recorded_by_membership_id=record.recorded_by_membership_id,
        recorded_by_name=(
            record.recorded_by_membership.user.full_name
            if record.recorded_by_membership and record.recorded_by_membership.user
            else None
        ),
        invoice_reference=record.invoice_reference,
        stage_label=record.stage_label,
        description=record.description,
        currency=record.currency,
        amount_minor=record.amount_minor,
        approved_amount_minor=record.approved_amount_minor,
        status=record.status,
        billed_on=record.billed_on,
        due_on=record.due_on,
        paid_on=record.paid_on,
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _build_summary(
    *,
    company_id: str,
    profiles: list[OutsideCounsel],
    assignments: list[MatterOutsideCounselAssignment],
    spend_records: list[OutsideCounselSpendRecord],
    invoices: list[MatterInvoice],
) -> OutsideCounselPortfolioSummary:
    preferred_panel_count = sum(
        1 for profile in profiles if profile.panel_status == OutsideCounselPanelStatus.PREFERRED
    )
    active_assignment_count = sum(
        1
        for assignment in assignments
        if assignment.status
        in {
            OutsideCounselAssignmentStatus.APPROVED,
            OutsideCounselAssignmentStatus.ACTIVE,
        }
    )
    total_budget_minor = sum(assignment.budget_amount_minor or 0 for assignment in assignments)
    total_spend_minor = sum(record.amount_minor for record in spend_records)
    approved_spend_minor = sum(record.approved_amount_minor for record in spend_records)
    disputed_spend_minor = sum(
        record.amount_minor
        for record in spend_records
        if record.status == OutsideCounselSpendStatus.DISPUTED
    )
    collected_invoice_minor = sum(invoice.amount_received_minor for invoice in invoices)
    outstanding_invoice_minor = sum(invoice.balance_due_minor for invoice in invoices)
    return OutsideCounselPortfolioSummary(
        company_id=company_id,
        total_counsel_count=len(profiles),
        preferred_panel_count=preferred_panel_count,
        active_assignment_count=active_assignment_count,
        total_budget_minor=total_budget_minor,
        total_spend_minor=total_spend_minor,
        approved_spend_minor=approved_spend_minor,
        disputed_spend_minor=disputed_spend_minor,
        collected_invoice_minor=collected_invoice_minor,
        outstanding_invoice_minor=outstanding_invoice_minor,
        profitability_signal_minor=collected_invoice_minor - approved_spend_minor,
    )


def get_outside_counsel_workspace(
    session: Session,
    *,
    context: SessionContext,
) -> OutsideCounselWorkspaceResponse:
    profiles = list(
        session.scalars(
            select(OutsideCounsel)
            .where(OutsideCounsel.company_id == context.company.id)
            .order_by(OutsideCounsel.updated_at.desc(), OutsideCounsel.created_at.desc())
        )
    )
    assignments = list(
        session.scalars(
            select(MatterOutsideCounselAssignment)
            .options(
                joinedload(MatterOutsideCounselAssignment.matter),
                joinedload(MatterOutsideCounselAssignment.counsel),
                joinedload(MatterOutsideCounselAssignment.assigned_by_membership).joinedload(
                    CompanyMembership.user
                ),
            )
            .where(MatterOutsideCounselAssignment.company_id == context.company.id)
            .order_by(
                MatterOutsideCounselAssignment.updated_at.desc(),
                MatterOutsideCounselAssignment.created_at.desc(),
            )
        )
    )
    spend_records = list(
        session.scalars(
            select(OutsideCounselSpendRecord)
            .options(
                joinedload(OutsideCounselSpendRecord.matter),
                joinedload(OutsideCounselSpendRecord.counsel),
                joinedload(OutsideCounselSpendRecord.recorded_by_membership).joinedload(
                    CompanyMembership.user
                ),
            )
            .where(OutsideCounselSpendRecord.company_id == context.company.id)
            .order_by(
                OutsideCounselSpendRecord.updated_at.desc(),
                OutsideCounselSpendRecord.created_at.desc(),
            )
        )
    )
    invoices = list(
        session.scalars(
            select(MatterInvoice)
            .where(MatterInvoice.company_id == context.company.id)
            .order_by(MatterInvoice.updated_at.desc())
        )
    )

    assignments_by_counsel: dict[str, list[MatterOutsideCounselAssignment]] = defaultdict(list)
    for assignment in assignments:
        assignments_by_counsel[assignment.counsel_id].append(assignment)

    spend_by_counsel: dict[str, list[OutsideCounselSpendRecord]] = defaultdict(list)
    for record in spend_records:
        spend_by_counsel[record.counsel_id].append(record)

    serialized_profiles = [
        _serialize_counsel_record(
            profile,
            assignments=assignments_by_counsel.get(profile.id, []),
            spend_records=spend_by_counsel.get(profile.id, []),
        )
        for profile in profiles
    ]

    return OutsideCounselWorkspaceResponse(
        summary=_build_summary(
            company_id=context.company.id,
            profiles=profiles,
            assignments=assignments,
            spend_records=spend_records,
            invoices=invoices,
        ),
        profiles=serialized_profiles,
        assignments=[_serialize_assignment_record(assignment) for assignment in assignments],
        spend_records=[_serialize_spend_record(record) for record in spend_records],
    )


def create_outside_counsel_profile(
    session: Session,
    *,
    context: SessionContext,
    payload: OutsideCounselCreateRequest,
) -> OutsideCounselRecord:
    _require_management_role(context)
    existing = session.scalar(
        select(OutsideCounsel).where(
            OutsideCounsel.company_id == context.company.id,
            OutsideCounsel.name == payload.name.strip(),
        )
    )
    if existing:
        _raise_conflict("An outside counsel profile with this name already exists.")

    counsel = OutsideCounsel(
        company_id=context.company.id,
        name=payload.name.strip(),
        primary_contact_name=payload.primary_contact_name.strip()
        if payload.primary_contact_name
        else None,
        primary_contact_email=payload.primary_contact_email.lower().strip()
        if payload.primary_contact_email
        else None,
        primary_contact_phone=payload.primary_contact_phone.strip()
        if payload.primary_contact_phone
        else None,
        firm_city=payload.firm_city.strip() if payload.firm_city else None,
        jurisdictions_json=_encode_string_list(payload.jurisdictions),
        practice_areas_json=_encode_string_list(payload.practice_areas),
        panel_status=payload.panel_status,
        internal_notes=payload.internal_notes.strip() if payload.internal_notes else None,
    )
    session.add(counsel)
    session.flush()
    record_from_context(
        session,
        context,
        action="outside_counsel.created",
        target_type="outside_counsel",
        target_id=counsel.id,
        metadata={"name": counsel.name, "panel_status": counsel.panel_status},
    )
    session.commit()
    session.refresh(counsel)
    return _serialize_counsel_record(counsel, assignments=[], spend_records=[])


def update_outside_counsel_profile(
    session: Session,
    *,
    context: SessionContext,
    counsel_id: str,
    payload: OutsideCounselUpdateRequest,
) -> OutsideCounselRecord:
    _require_management_role(context)
    counsel = _get_outside_counsel_model(
        session,
        company_id=context.company.id,
        counsel_id=counsel_id,
    )
    updates = payload.model_dump(exclude_unset=True)

    if "name" in updates and updates["name"] is not None:
        normalized_name = updates["name"].strip()
        existing = session.scalar(
            select(OutsideCounsel).where(
                OutsideCounsel.company_id == context.company.id,
                OutsideCounsel.name == normalized_name,
                OutsideCounsel.id != counsel.id,
            )
        )
        if existing:
            _raise_conflict("An outside counsel profile with this name already exists.")
        counsel.name = normalized_name

    if "primary_contact_name" in updates:
        counsel.primary_contact_name = (
            updates["primary_contact_name"].strip() if updates["primary_contact_name"] else None
        )
    if "primary_contact_email" in updates:
        counsel.primary_contact_email = (
            updates["primary_contact_email"].lower().strip()
            if updates["primary_contact_email"]
            else None
        )
    if "primary_contact_phone" in updates:
        counsel.primary_contact_phone = (
            updates["primary_contact_phone"].strip() if updates["primary_contact_phone"] else None
        )
    if "firm_city" in updates:
        counsel.firm_city = updates["firm_city"].strip() if updates["firm_city"] else None
    if "jurisdictions" in updates:
        counsel.jurisdictions_json = _encode_string_list(updates["jurisdictions"] or [])
    if "practice_areas" in updates:
        counsel.practice_areas_json = _encode_string_list(updates["practice_areas"] or [])
    if "panel_status" in updates and updates["panel_status"] is not None:
        counsel.panel_status = updates["panel_status"]
    if "internal_notes" in updates:
        counsel.internal_notes = (
            updates["internal_notes"].strip() if updates["internal_notes"] else None
        )

    session.add(counsel)
    session.commit()
    session.refresh(counsel)
    return _serialize_counsel_record(
        counsel,
        assignments=list(counsel.assignments),
        spend_records=list(counsel.spend_records),
    )


def create_outside_counsel_assignment(
    session: Session,
    *,
    context: SessionContext,
    payload: OutsideCounselAssignmentCreateRequest,
) -> OutsideCounselAssignmentRecord:
    matter = _get_company_matter(session, context=context, matter_id=payload.matter_id)
    counsel = _get_outside_counsel_model(
        session,
        company_id=context.company.id,
        counsel_id=payload.counsel_id,
    )
    existing = session.scalar(
        select(MatterOutsideCounselAssignment).where(
            MatterOutsideCounselAssignment.company_id == context.company.id,
            MatterOutsideCounselAssignment.matter_id == matter.id,
            MatterOutsideCounselAssignment.counsel_id == counsel.id,
        )
    )
    if existing:
        _raise_conflict("This outside counsel profile is already linked to the selected matter.")

    assignment = MatterOutsideCounselAssignment(
        company_id=context.company.id,
        matter_id=matter.id,
        counsel_id=counsel.id,
        assigned_by_membership_id=context.membership.id,
        role_summary=payload.role_summary.strip() if payload.role_summary else None,
        budget_amount_minor=payload.budget_amount_minor,
        currency=payload.currency.strip().upper(),
        status=payload.status,
        internal_notes=payload.internal_notes.strip() if payload.internal_notes else None,
    )
    session.add(assignment)
    session.flush()
    _append_matter_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="outside_counsel_linked",
        title="Outside counsel linked",
        detail=f"{counsel.name} linked with status {assignment.status}.",
    )
    session.commit()
    refreshed = session.scalar(
        select(MatterOutsideCounselAssignment)
        .options(
            joinedload(MatterOutsideCounselAssignment.matter),
            joinedload(MatterOutsideCounselAssignment.counsel),
            joinedload(MatterOutsideCounselAssignment.assigned_by_membership).joinedload(
                CompanyMembership.user
            ),
        )
        .where(MatterOutsideCounselAssignment.id == assignment.id)
    )
    assert refreshed is not None
    return _serialize_assignment_record(refreshed)


def create_outside_counsel_spend_record(
    session: Session,
    *,
    context: SessionContext,
    payload: OutsideCounselSpendRecordCreateRequest,
) -> OutsideCounselSpendRecordResponse:
    matter = _get_company_matter(session, context=context, matter_id=payload.matter_id)
    counsel = _get_outside_counsel_model(
        session,
        company_id=context.company.id,
        counsel_id=payload.counsel_id,
    )
    assignment: MatterOutsideCounselAssignment | None = None
    if payload.assignment_id:
        assignment = _get_assignment_model(
            session,
            company_id=context.company.id,
            assignment_id=payload.assignment_id,
        )
        if assignment.matter_id != matter.id or assignment.counsel_id != counsel.id:
            _raise_bad_request(
                "The selected assignment does not match the chosen matter and counsel."
            )
    else:
        assignment = session.scalar(
            select(MatterOutsideCounselAssignment).where(
                MatterOutsideCounselAssignment.company_id == context.company.id,
                MatterOutsideCounselAssignment.matter_id == matter.id,
                MatterOutsideCounselAssignment.counsel_id == counsel.id,
            )
        )

    if (
        payload.approved_amount_minor is not None
        and payload.approved_amount_minor > payload.amount_minor
    ):
        _raise_bad_request("Approved spend cannot exceed the submitted spend amount.")

    approved_amount_minor = payload.approved_amount_minor
    if payload.status in {OutsideCounselSpendStatus.APPROVED, OutsideCounselSpendStatus.PAID}:
        approved_amount_minor = (
            payload.amount_minor if approved_amount_minor is None else approved_amount_minor
        )
    elif payload.status == OutsideCounselSpendStatus.PARTIALLY_APPROVED:
        if approved_amount_minor is None:
            _raise_bad_request("Provide an approved amount for partially approved spend records.")
    else:
        approved_amount_minor = 0 if approved_amount_minor is None else approved_amount_minor

    spend_record = OutsideCounselSpendRecord(
        company_id=context.company.id,
        matter_id=matter.id,
        counsel_id=counsel.id,
        assignment_id=assignment.id if assignment else None,
        recorded_by_membership_id=context.membership.id,
        invoice_reference=payload.invoice_reference.strip() if payload.invoice_reference else None,
        stage_label=payload.stage_label.strip() if payload.stage_label else None,
        description=payload.description.strip(),
        currency=payload.currency.strip().upper(),
        amount_minor=payload.amount_minor,
        approved_amount_minor=approved_amount_minor,
        status=payload.status,
        billed_on=payload.billed_on,
        due_on=payload.due_on,
        paid_on=payload.paid_on,
        notes=payload.notes.strip() if payload.notes else None,
    )
    session.add(spend_record)
    session.flush()
    _append_matter_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="outside_counsel_spend_recorded",
        title="Outside counsel spend recorded",
        detail=(
            f"{counsel.name} spend recorded at {payload.amount_minor} "
            f"{spend_record.currency} minor units."
        ),
    )
    # Money event — goes into the unified audit trail alongside matter
    # activity so compliance can see spend without joining two tables.
    record_from_context(
        session,
        context,
        action="outside_counsel.spend_recorded",
        target_type="outside_counsel_spend",
        target_id=spend_record.id,
        matter_id=matter.id,
        metadata={
            "counsel_id": counsel.id,
            "amount_minor": payload.amount_minor,
            "currency": spend_record.currency,
            "description": spend_record.description,
        },
    )
    session.commit()
    refreshed = session.scalar(
        select(OutsideCounselSpendRecord)
        .options(
            joinedload(OutsideCounselSpendRecord.matter),
            joinedload(OutsideCounselSpendRecord.counsel),
            joinedload(OutsideCounselSpendRecord.recorded_by_membership).joinedload(
                CompanyMembership.user
            ),
        )
        .where(OutsideCounselSpendRecord.id == spend_record.id)
    )
    assert refreshed is not None
    return _serialize_spend_record(refreshed)


def get_outside_counsel_recommendations(
    session: Session,
    *,
    context: SessionContext,
    payload: OutsideCounselRecommendationRequest,
) -> OutsideCounselRecommendationResponse:
    matter = _get_company_matter(session, context=context, matter_id=payload.matter_id)
    profiles = list(
        session.scalars(
            select(OutsideCounsel)
            .options(
                selectinload(OutsideCounsel.assignments).joinedload(
                    MatterOutsideCounselAssignment.matter
                ),
                selectinload(OutsideCounsel.spend_records),
            )
            .where(OutsideCounsel.company_id == context.company.id)
            .order_by(OutsideCounsel.updated_at.desc())
        )
    )

    results: list[OutsideCounselRecommendationRecord] = []
    for counsel in profiles:
        score = 0.0
        evidence: list[str] = []
        jurisdictions = _decode_string_list(counsel.jurisdictions_json)
        practice_areas = _decode_string_list(counsel.practice_areas_json)
        assignments = list(counsel.assignments)
        spend_records = list(counsel.spend_records)

        if counsel.panel_status == OutsideCounselPanelStatus.PREFERRED:
            score += 3.0
            evidence.append("Preferred panel counsel.")
        elif counsel.panel_status == OutsideCounselPanelStatus.ACTIVE:
            score += 1.0
            evidence.append("Active panel counsel.")
        else:
            score -= 2.0
            evidence.append("Inactive panel status reduces ranking.")

        if matter.practice_area and any(
            item.lower() == matter.practice_area.lower() for item in practice_areas
        ):
            score += 5.0
            evidence.append(f"Practice area match for {matter.practice_area}.")

        if matter.forum_level and any(
            assignment.matter.forum_level == matter.forum_level for assignment in assignments
        ):
            score += 3.0
            evidence.append(f"Has prior work in {matter.forum_level.replace('_', ' ')} posture.")

        if matter.court_name and any(
            assignment.matter.court_name
            and assignment.matter.court_name.lower() == matter.court_name.lower()
            for assignment in assignments
        ):
            score += 4.0
            evidence.append(f"Has prior matters in {matter.court_name}.")

        if matter.court_name and any(
            item.lower() in matter.court_name.lower() for item in jurisdictions
        ):
            score += 2.0
            evidence.append("Declared jurisdiction overlaps with current court.")

        active_matter_count = sum(
            1
            for assignment in assignments
            if assignment.status
            in {
                OutsideCounselAssignmentStatus.APPROVED,
                OutsideCounselAssignmentStatus.ACTIVE,
            }
        )
        if active_matter_count:
            score += min(active_matter_count, 3)
            evidence.append(
                f"{active_matter_count} active or approved matter assignment(s) on record."
            )

        approved_spend_minor = sum(record.approved_amount_minor for record in spend_records)
        if approved_spend_minor:
            evidence.append(
                "Approved spend history totals "
                f"{approved_spend_minor} minor units across prior matters."
            )

        results.append(
            OutsideCounselRecommendationRecord(
                counsel_id=counsel.id,
                counsel_name=counsel.name,
                panel_status=counsel.panel_status,
                score=round(score, 2),
                total_matters_count=len(assignments),
                active_matters_count=active_matter_count,
                approved_spend_minor=approved_spend_minor,
                evidence=evidence or ["Panel profile available but no prior matter evidence yet."],
            )
        )

    results.sort(
        key=lambda item: (
            item.score,
            item.active_matters_count,
            item.total_matters_count,
            item.approved_spend_minor,
        ),
        reverse=True,
    )

    return OutsideCounselRecommendationResponse(
        matter_id=matter.id,
        matter_title=matter.title,
        matter_code=matter.matter_code,
        generated_at=_now(),
        results=results[: payload.limit],
    )
