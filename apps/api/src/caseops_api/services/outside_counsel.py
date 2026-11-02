from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import (
    Session,
    joinedload,
    raiseload,
    selectinload,
    with_loader_criteria,
)

from caseops_api.db.models import (
    CompanyMembership,
    InvoiceStatus,
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
    MatterCounselContextResponse,
    MatterCounselPageCurrency,
    OutsideCounselAssignmentCreateRequest,
    OutsideCounselAssignmentRecord,
    OutsideCounselCreateRequest,
    OutsideCounselMatterSpendSummary,
    OutsideCounselPortfolioSummary,
    OutsideCounselRecommendationRecord,
    OutsideCounselRecommendationRequest,
    OutsideCounselRecommendationResponse,
    OutsideCounselRecord,
    OutsideCounselSpendRecordCreateRequest,
    OutsideCounselSpendRecordUpdateRequest,
    OutsideCounselUpdateRequest,
    OutsideCounselWorkspaceResponse,
)
from caseops_api.schemas.outside_counsel import (
    OutsideCounselSpendRecord as OutsideCounselSpendRecordResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.counsel_read_pages import counsel_page_statement, source_row_from_page
from caseops_api.services.matter_access import assert_access, visible_matters_filter
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext


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
    assert_access(session, context=context, matter=matter)
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


def _get_spend_record_model(
    session: Session,
    *,
    company_id: str,
    spend_record_id: str,
) -> OutsideCounselSpendRecord:
    spend_record = session.scalar(
        select(OutsideCounselSpendRecord)
        .options(
            joinedload(OutsideCounselSpendRecord.matter),
            joinedload(OutsideCounselSpendRecord.counsel),
            joinedload(OutsideCounselSpendRecord.recorded_by_membership).joinedload(
                CompanyMembership.user
            ),
        )
        .where(
            OutsideCounselSpendRecord.id == spend_record_id,
            OutsideCounselSpendRecord.company_id == company_id,
        )
    )
    if not spend_record:
        _raise_not_found("Outside counsel spend record was not found in the current company.")
    return spend_record


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


def _paid_amount_minor(record: OutsideCounselSpendRecord) -> int:
    return (
        record.approved_amount_minor
        if record.status == OutsideCounselSpendStatus.PAID
        else 0
    )


def _pending_amount_minor(record: OutsideCounselSpendRecord) -> int:
    return max(record.amount_minor - _paid_amount_minor(record), 0)


def _payment_tracking_status(record: OutsideCounselSpendRecord) -> str:
    paid_amount = _paid_amount_minor(record)
    if record.amount_minor == 0:
        return "paid" if record.status == OutsideCounselSpendStatus.PAID else "unpaid"
    if paid_amount <= 0:
        return "unpaid"
    if paid_amount >= record.amount_minor:
        return "paid"
    return "partially_paid"


def _spend_status_counts(records: list[OutsideCounselSpendRecord]) -> dict[str, int]:
    counts = {status.value: 0 for status in OutsideCounselSpendStatus}
    for record in records:
        counts[str(record.status)] = counts.get(str(record.status), 0) + 1
    return counts


def _currency_codes(
    *,
    assignments: list[MatterOutsideCounselAssignment],
    spend_records: list[OutsideCounselSpendRecord],
    invoices: list[MatterInvoice],
) -> list[str]:
    codes = {
        str(item.currency).upper()
        for item in [*assignments, *spend_records, *invoices]
        if getattr(item, "currency", None)
    }
    return sorted(codes) or ["INR"]


def _normalise_approved_amount(
    *,
    amount_minor: int,
    approved_amount_minor: int | None,
    status_value: str,
    status_changed: bool = False,
) -> int:
    if approved_amount_minor is not None and approved_amount_minor > amount_minor:
        _raise_bad_request("Approved spend cannot exceed the submitted spend amount.")

    if status_value in {OutsideCounselSpendStatus.APPROVED, OutsideCounselSpendStatus.PAID}:
        return amount_minor if approved_amount_minor is None else approved_amount_minor

    if status_value == OutsideCounselSpendStatus.PARTIALLY_APPROVED:
        if approved_amount_minor is None:
            _raise_bad_request("Provide an approved amount for partially approved spend records.")
        return approved_amount_minor

    if approved_amount_minor is None or status_changed:
        return 0
    return approved_amount_minor


def _spend_audit_metadata(record: OutsideCounselSpendRecord) -> dict[str, object]:
    return {
        "matter_id": record.matter_id,
        "counsel_id": record.counsel_id,
        "assignment_id": record.assignment_id,
        "invoice_reference_present": bool(record.invoice_reference),
        "stage_label_present": bool(record.stage_label),
        "amount_minor": record.amount_minor,
        "approved_amount_minor": record.approved_amount_minor,
        "paid_amount_minor": _paid_amount_minor(record),
        "pending_amount_minor": _pending_amount_minor(record),
        "currency": record.currency,
        "status": str(record.status),
        "billed_on_present": record.billed_on is not None,
        "due_on_present": record.due_on is not None,
        "paid_on_present": record.paid_on is not None,
        "notes_present": bool(record.notes),
    }


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
    *,
    labels: tuple[Matter, str | None] | None = None,
) -> OutsideCounselAssignmentRecord:
    return OutsideCounselAssignmentRecord(
        id=assignment.id,
        company_id=assignment.company_id,
        matter_id=assignment.matter_id,
        matter_title=(labels[0] if labels is not None else assignment.matter).title,
        matter_code=(labels[0] if labels is not None else assignment.matter).matter_code,
        counsel_id=assignment.counsel_id,
        counsel_name=assignment.counsel.name,
        assigned_by_membership_id=assignment.assigned_by_membership_id,
        assigned_by_name=(labels[1] if labels is not None else (
            assignment.assigned_by_membership.user.full_name
            if assignment.assigned_by_membership and assignment.assigned_by_membership.user
            else None
        )),
        role_summary=assignment.role_summary,
        budget_amount_minor=assignment.budget_amount_minor,
        fee_agreed_minor=assignment.budget_amount_minor,
        currency=assignment.currency,
        status=assignment.status,
        internal_notes=assignment.internal_notes,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _serialize_spend_record(
    record: OutsideCounselSpendRecord,
    *,
    labels: tuple[Matter, str | None] | None = None,
) -> OutsideCounselSpendRecordResponse:
    return OutsideCounselSpendRecordResponse(
        id=record.id,
        company_id=record.company_id,
        matter_id=record.matter_id,
        matter_title=(labels[0] if labels is not None else record.matter).title,
        matter_code=(labels[0] if labels is not None else record.matter).matter_code,
        counsel_id=record.counsel_id,
        counsel_name=record.counsel.name,
        assignment_id=record.assignment_id,
        recorded_by_membership_id=record.recorded_by_membership_id,
        recorded_by_name=(labels[1] if labels is not None else (
            record.recorded_by_membership.user.full_name
            if record.recorded_by_membership and record.recorded_by_membership.user
            else None
        )),
        invoice_reference=record.invoice_reference,
        stage_label=record.stage_label,
        description=record.description,
        currency=record.currency,
        amount_minor=record.amount_minor,
        approved_amount_minor=record.approved_amount_minor,
        paid_amount_minor=_paid_amount_minor(record),
        pending_amount_minor=_pending_amount_minor(record),
        status=record.status,
        payment_status=record.status,
        payment_tracking_status=_payment_tracking_status(record),
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
    total_paid_minor = sum(_paid_amount_minor(record) for record in spend_records)
    total_pending_minor = sum(_pending_amount_minor(record) for record in spend_records)
    disputed_spend_minor = sum(
        record.amount_minor
        for record in spend_records
        if record.status == OutsideCounselSpendStatus.DISPUTED
    )
    today = date.today()
    oc_invoices = [invoice for invoice in invoices if invoice.submitted_by_portal_user_id]
    collected_invoice_minor = sum(invoice.amount_received_minor for invoice in oc_invoices)
    outstanding_invoice_minor = sum(invoice.balance_due_minor for invoice in oc_invoices)
    pending_invoice_count = sum(
        1
        for invoice in oc_invoices
        if invoice.status
        in {InvoiceStatus.NEEDS_REVIEW, InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID}
    )
    overdue_invoice_count = sum(
        1
        for invoice in oc_invoices
        if invoice.due_on is not None
        and invoice.due_on < today
        and invoice.balance_due_minor > 0
        and invoice.status not in {InvoiceStatus.PAID, InvoiceStatus.VOID}
    )
    currency = assignments[0].currency if assignments else "INR"
    if not assignments and spend_records:
        currency = spend_records[0].currency
    currency_codes = _currency_codes(
        assignments=assignments,
        spend_records=spend_records,
        invoices=oc_invoices,
    )
    return OutsideCounselPortfolioSummary(
        company_id=company_id,
        currency=currency,
        currency_codes=currency_codes,
        currency_count=len(currency_codes),
        multi_currency=len(currency_codes) > 1,
        total_counsel_count=len(profiles),
        profile_count=len(profiles),
        preferred_panel_count=preferred_panel_count,
        active_assignment_count=active_assignment_count,
        total_agreed_minor=total_budget_minor,
        total_budget_minor=total_budget_minor,
        total_spend_minor=total_spend_minor,
        approved_spend_minor=approved_spend_minor,
        total_paid_minor=total_paid_minor,
        total_pending_minor=total_pending_minor,
        disputed_spend_minor=disputed_spend_minor,
        pending_invoice_count=pending_invoice_count,
        overdue_invoice_count=overdue_invoice_count,
        collected_invoice_minor=collected_invoice_minor,
        outstanding_invoice_minor=outstanding_invoice_minor,
        profitability_signal_minor=collected_invoice_minor - approved_spend_minor,
        payment_status_counts=_spend_status_counts(spend_records),
    )


def _build_matter_summaries(
    *,
    assignments: list[MatterOutsideCounselAssignment],
    spend_records: list[OutsideCounselSpendRecord],
    invoices: list[MatterInvoice],
) -> list[OutsideCounselMatterSpendSummary]:
    oc_invoices = [item for item in invoices if item.submitted_by_portal_user_id]
    matter_ids = {
        item.matter_id for item in assignments
    } | {item.matter_id for item in spend_records} | {item.matter_id for item in oc_invoices}
    summaries: list[OutsideCounselMatterSpendSummary] = []
    today = date.today()
    for matter_id in sorted(matter_ids):
        matter_assignments = [item for item in assignments if item.matter_id == matter_id]
        matter_spend = [item for item in spend_records if item.matter_id == matter_id]
        matter_invoices = [
            item
            for item in oc_invoices
            if item.matter_id == matter_id
        ]
        currency_codes = _currency_codes(
            assignments=matter_assignments,
            spend_records=matter_spend,
            invoices=matter_invoices,
        )
        matter = (
            matter_assignments[0].matter
            if matter_assignments
            else (matter_spend[0].matter if matter_spend else matter_invoices[0].matter)
        )
        summaries.append(
            OutsideCounselMatterSpendSummary(
                matter_id=matter_id,
                matter_title=matter.title,
                matter_code=matter.matter_code,
                currency=(
                    matter_assignments[0].currency
                    if matter_assignments
                    else (matter_spend[0].currency if matter_spend else "INR")
                ),
                currency_codes=currency_codes,
                currency_count=len(currency_codes),
                multi_currency=len(currency_codes) > 1,
                assigned_counsel_count=len({item.counsel_id for item in matter_assignments}),
                invoice_count=len(matter_invoices),
                pending_invoice_count=sum(
                    1
                    for invoice in matter_invoices
                    if invoice.status
                    in {
                        InvoiceStatus.NEEDS_REVIEW,
                        InvoiceStatus.ISSUED,
                        InvoiceStatus.PARTIALLY_PAID,
                    }
                ),
                overdue_invoice_count=sum(
                    1
                    for invoice in matter_invoices
                    if invoice.due_on is not None
                    and invoice.due_on < today
                    and invoice.balance_due_minor > 0
                    and invoice.status not in {InvoiceStatus.PAID, InvoiceStatus.VOID}
                ),
                total_agreed_minor=sum(
                    item.budget_amount_minor or 0 for item in matter_assignments
                ),
                total_spend_minor=sum(item.amount_minor for item in matter_spend),
                approved_spend_minor=sum(item.approved_amount_minor for item in matter_spend),
                total_paid_minor=sum(_paid_amount_minor(item) for item in matter_spend),
                total_pending_minor=sum(_pending_amount_minor(item) for item in matter_spend),
                payment_status_counts=_spend_status_counts(matter_spend),
            )
        )
    summaries.sort(key=lambda item: (item.matter_code, item.matter_title))
    return summaries


def _matter_context_page_statement(
    model, *, company_id, matter_id, after, limit, dialect_name="postgresql",
):
    """Tenant/Matter leading seek; no portfolio materialization or OFFSET."""
    if model is MatterOutsideCounselAssignment:
        actor = model.assigned_by_membership
    elif model is OutsideCounselSpendRecord:
        actor = model.recorded_by_membership
    else:
        raise ValueError("Unsupported Matter counsel page model.")
    if dialect_name == "postgresql":
        return counsel_page_statement(model, company_id=company_id, matter_id=matter_id,
                                      after=after, limit=limit)
    if dialect_name != "sqlite":
        raise ValueError("Unsupported Matter counsel read dialect.")
    statement = (
        select(model)
        .join(OutsideCounsel, OutsideCounsel.id == model.counsel_id)
        .where(model.company_id == company_id, model.matter_id == matter_id,
               OutsideCounsel.company_id == company_id)
        .options(
            joinedload(model.matter), joinedload(model.counsel),
            joinedload(actor).joinedload(CompanyMembership.user),
            with_loader_criteria(CompanyMembership, CompanyMembership.company_id == company_id),
            raiseload("*"),
        )
        .order_by(model.id)
        .limit(limit + 1)
        .execution_options(populate_existing=True)
    )
    return statement.where(model.id > after) if after is not None else statement


def _matter_context_after(session, model, *, context, matter_id, value):
    if value is None:
        return None
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, detail="A page continuation must be a record UUID.") from exc
    anchor = session.scalar(select(model.id).where(
        model.id == canonical, model.company_id == context.company.id, model.matter_id == matter_id,
    ).limit(1))
    if anchor is None:
        _raise_not_found("Page continuation was not found in this Matter.")
    return anchor


def get_matter_counsel_context(
    session: Session, *, context: SessionContext, matter_id: str,
    assignment_limit: int = 10, spend_limit: int = 10,
    assignment_after: str | None = None, spend_after: str | None = None,
) -> MatterCounselContextResponse:
    for limit in (assignment_limit, spend_limit):
        if type(limit) is not int or not 1 <= limit <= 25:
            raise HTTPException(422, detail="Matter counsel page limits must be between 1 and 25.")
    matter = session.scalar(select(Matter).where(
        Matter.id == matter_id, Matter.company_id == context.company.id,
    ).options(raiseload("*")).execution_options(populate_existing=True))
    if matter is None:
        _raise_not_found("Matter was not found in the current company.")
    # Same read authority as the existing workspace, with walls/teams/current
    # grants rechecked for every page. Closed Matter history remains readable.
    assert_access(session, context=context, matter=matter)
    assignment_after = _matter_context_after(
        session, MatterOutsideCounselAssignment, context=context,
        matter_id=matter.id, value=assignment_after,
    )
    spend_after = _matter_context_after(
        session, OutsideCounselSpendRecord, context=context,
        matter_id=matter.id, value=spend_after,
    )
    dialect = session.get_bind().dialect.name

    def page_rows(model, after, limit):
        statement = _matter_context_page_statement(
            model, company_id=context.company.id, matter_id=matter.id,
            after=after, limit=limit, dialect_name=dialect,
        )
        if dialect == "postgresql":
            return [source_row_from_page(model, item["source_payload"], item["source_note"],
                        item["actor_name"], company_id=context.company.id, matter_id=matter.id)
                    for item in session.execute(statement).mappings()]
        records = list(session.scalars(statement))
        def actor_name(record):
            member = (record.assigned_by_membership if model is MatterOutsideCounselAssignment
                      else record.recorded_by_membership)
            return member.user.full_name if member and member.user else None
        return [(record, actor_name(record)) for record in records]

    assignment_rows = page_rows(MatterOutsideCounselAssignment, assignment_after, assignment_limit)
    spend_rows = page_rows(OutsideCounselSpendRecord, spend_after, spend_limit)
    assignments = [row[0] for row in assignment_rows]
    spending = [row[0] for row in spend_rows]
    assignment_names = {row[0].id: row[1] for row in assignment_rows}
    spend_names = {row[0].id: row[1] for row in spend_rows}
    assignment_next = (
        assignments[assignment_limit - 1].id if len(assignments) > assignment_limit else None
    )
    spend_next = spending[spend_limit - 1].id if len(spending) > spend_limit else None
    assignments, spending = assignments[:assignment_limit], spending[:spend_limit]
    currencies = {}

    def currency(value):
        return currencies.setdefault(value, MatterCounselPageCurrency(
            currency=value, recorded_budget_minor=0, unpriced_assignment_count=0,
            amount_minor=0, approved_amount_minor=0, paid_amount_minor=0, pending_amount_minor=0,
        ))

    for assignment in assignments:
        item = currency(assignment.currency)
        if assignment.budget_amount_minor is None:
            item.unpriced_assignment_count += 1
        else:
            item.recorded_budget_minor += assignment.budget_amount_minor
    for record in spending:
        item = currency(record.currency)
        item.amount_minor += record.amount_minor
        item.approved_amount_minor += record.approved_amount_minor
        item.paid_amount_minor += _paid_amount_minor(record)
        item.pending_amount_minor += _pending_amount_minor(record)

    def dated(record):
        # These persisted columns are known UTC; SQLite drops their offset.
        return record.model_copy(update={
            key: (getattr(record, key).replace(tzinfo=UTC)
                  if getattr(record, key).tzinfo is None else getattr(record, key).astimezone(UTC))
            for key in ("created_at", "updated_at")
        })

    return MatterCounselContextResponse(
        matter_id=matter.id, matter_title=matter.title, matter_code=matter.matter_code,
        matter_status=matter.status, matter_is_active=matter.is_active,
        lifecycle_version=matter.lifecycle_version, totals_scope="page",
        assignments=[
            dated(_serialize_assignment_record(item, labels=(matter, assignment_names[item.id])))
            for item in assignments
        ],
        spend_records=[
            dated(_serialize_spend_record(item, labels=(matter, spend_names[item.id])))
            for item in spending
        ],
        assignment_limit=assignment_limit, spend_limit=spend_limit,
        assignment_next_after=assignment_next, spend_next_after=spend_next,
        currencies=[currencies[key] for key in sorted(currencies)],
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
            .join(Matter, Matter.id == MatterOutsideCounselAssignment.matter_id)
            .options(
                joinedload(MatterOutsideCounselAssignment.matter),
                joinedload(MatterOutsideCounselAssignment.counsel),
                joinedload(MatterOutsideCounselAssignment.assigned_by_membership).joinedload(
                    CompanyMembership.user
                ),
            )
            .where(
                MatterOutsideCounselAssignment.company_id == context.company.id,
                Matter.company_id == context.company.id,
                visible_matters_filter(session, context=context),
            )
            .order_by(
                MatterOutsideCounselAssignment.updated_at.desc(),
                MatterOutsideCounselAssignment.created_at.desc(),
            )
        )
    )
    spend_records = list(
        session.scalars(
            select(OutsideCounselSpendRecord)
            .join(Matter, Matter.id == OutsideCounselSpendRecord.matter_id)
            .options(
                joinedload(OutsideCounselSpendRecord.matter),
                joinedload(OutsideCounselSpendRecord.counsel),
                joinedload(OutsideCounselSpendRecord.recorded_by_membership).joinedload(
                    CompanyMembership.user
                ),
            )
            .where(
                OutsideCounselSpendRecord.company_id == context.company.id,
                Matter.company_id == context.company.id,
                visible_matters_filter(session, context=context),
            )
            .order_by(
                OutsideCounselSpendRecord.updated_at.desc(),
                OutsideCounselSpendRecord.created_at.desc(),
            )
        )
    )
    invoices = list(
        session.scalars(
            select(MatterInvoice)
            .join(Matter, Matter.id == MatterInvoice.matter_id)
            .options(joinedload(MatterInvoice.matter))
            .where(
                MatterInvoice.company_id == context.company.id,
                Matter.company_id == context.company.id,
                visible_matters_filter(session, context=context),
            )
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
        matter_summaries=_build_matter_summaries(
            assignments=assignments,
            spend_records=spend_records,
            invoices=invoices,
        ),
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
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="link outside counsel",
    )
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
    record_from_context(
        session,
        context,
        action="outside_counsel.assignment_created",
        target_type="outside_counsel_assignment",
        target_id=assignment.id,
        matter_id=matter.id,
        metadata={
            "matter_id": matter.id,
            "counsel_id": counsel.id,
            "budget_amount_minor": assignment.budget_amount_minor,
            "fee_agreed_minor": assignment.budget_amount_minor,
            "currency": assignment.currency,
            "status": str(assignment.status),
            "has_internal_notes": bool(assignment.internal_notes),
        },
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
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="record outside counsel spend",
    )
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

    approved_amount_minor = _normalise_approved_amount(
        amount_minor=payload.amount_minor,
        approved_amount_minor=payload.approved_amount_minor,
        status_value=payload.status,
    )

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
            **_spend_audit_metadata(spend_record),
            "change_type": "created",
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


def update_outside_counsel_spend_record(
    session: Session,
    *,
    context: SessionContext,
    spend_record_id: str,
    payload: OutsideCounselSpendRecordUpdateRequest,
) -> OutsideCounselSpendRecordResponse:
    spend_record = _get_spend_record_model(
        session,
        company_id=context.company.id,
        spend_record_id=spend_record_id,
    )
    assert_access(session, context=context, matter=spend_record.matter)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _serialize_spend_record(spend_record)
    require_operational_matter(
        session,
        matter=spend_record.matter,
        operation="update outside counsel spend",
    )

    old_status = str(spend_record.status)
    old_pending = _pending_amount_minor(spend_record)

    if "assignment_id" in updates:
        assignment_id = updates["assignment_id"]
        if assignment_id is None:
            spend_record.assignment_id = None
        else:
            assignment = _get_assignment_model(
                session,
                company_id=context.company.id,
                assignment_id=assignment_id,
            )
            if (
                assignment.matter_id != spend_record.matter_id
                or assignment.counsel_id != spend_record.counsel_id
            ):
                _raise_bad_request(
                    "The selected assignment does not match the spend record."
                )
            spend_record.assignment_id = assignment.id

    for attr in ("invoice_reference", "stage_label", "description", "notes"):
        if attr in updates:
            value = updates[attr]
            setattr(spend_record, attr, value.strip() if isinstance(value, str) else value)

    if "currency" in updates and updates["currency"] is not None:
        spend_record.currency = updates["currency"].strip().upper()
    if "amount_minor" in updates and updates["amount_minor"] is not None:
        spend_record.amount_minor = updates["amount_minor"]
    if "billed_on" in updates:
        spend_record.billed_on = updates["billed_on"]
    if "due_on" in updates:
        spend_record.due_on = updates["due_on"]
    if "paid_on" in updates:
        spend_record.paid_on = updates["paid_on"]
    if "status" in updates and updates["status"] is not None:
        spend_record.status = updates["status"]

    approved_supplied = "approved_amount_minor" in updates
    approved_value = (
        updates["approved_amount_minor"]
        if approved_supplied
        else spend_record.approved_amount_minor
    )
    if (
        not approved_supplied
        and str(spend_record.status)
        in {OutsideCounselSpendStatus.APPROVED, OutsideCounselSpendStatus.PAID}
        and str(spend_record.status) != old_status
    ):
        approved_value = None
    spend_record.approved_amount_minor = _normalise_approved_amount(
        amount_minor=spend_record.amount_minor,
        approved_amount_minor=approved_value,
        status_value=spend_record.status,
        status_changed=str(spend_record.status) != old_status,
    )

    session.add(spend_record)
    session.flush()
    record_from_context(
        session,
        context,
        action="outside_counsel.spend_updated",
        target_type="outside_counsel_spend",
        target_id=spend_record.id,
        matter_id=spend_record.matter_id,
        metadata={
            **_spend_audit_metadata(spend_record),
            "change_type": "updated",
            "previous_status": old_status,
            "status_changed": str(spend_record.status) != old_status,
            "previous_pending_amount_minor": old_pending,
        },
    )
    session.commit()
    refreshed = _get_spend_record_model(
        session,
        company_id=context.company.id,
        spend_record_id=spend_record.id,
    )
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
