from __future__ import annotations

import hashlib
import logging
from datetime import UTC, date, datetime, time
from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    AuditResult,
    CompanyMembership,
    Court,
    DocumentProcessingAction,
    DocumentProcessingTargetType,
    ForumCatalogEntry,
    Matter,
    MatterActivity,
    MatterAttachment,
    MatterBillingProfile,
    MatterCauseListEntry,
    MatterConflictCheckStatus,
    MatterCourtOrder,
    MatterCourtSyncJob,
    MatterCourtSyncRun,
    MatterHearing,
    MatterHearingStatus,
    MatterInvoice,
    MatterInvoiceLineItem,
    MatterInvoicePaymentAttempt,
    MatterNote,
    MatterProceedingSignal,
    MatterStatus,
    MatterStayStatus,
    MatterTag,
    MatterTagAssignment,
    MatterTask,
    MatterTaskStatus,
    MatterTimeEntry,
    MembershipRole,
    utcnow,
)
from caseops_api.schemas.billing import (
    InvoiceCreateRequest,
    InvoiceLineItemRecord,
    InvoicePaymentAttemptRecord,
    InvoiceRecord,
    TimeEntryCreateRequest,
    TimeEntryRecord,
)
from caseops_api.schemas.document_processing import DocumentProcessingJobRecord
from caseops_api.schemas.matter_tags import MatterTagRecord
from caseops_api.schemas.matters import (
    MATTER_CODE_ERROR,
    MatterActivityRecord,
    MatterAttachmentMetadataUpdateRequest,
    MatterAttachmentRecord,
    MatterCauseListEntryRecord,
    MatterCourtOrderCreateRequest,
    MatterCourtOrderRecord,
    MatterCourtOrderUpdateRequest,
    MatterCourtSyncImportRequest,
    MatterCourtSyncJobRecord,
    MatterCourtSyncRunRecord,
    MatterCreateRequest,
    MatterHearingCreateRequest,
    MatterHearingRecord,
    MatterListFilters,
    MatterListResponse,
    MatterNoteCreateRequest,
    MatterNoteRecord,
    MatterRecord,
    MatterTaskCreateRequest,
    MatterTaskRecord,
    MatterTaskUpdateRequest,
    MatterUpdateRequest,
    MatterWorkspaceMembership,
    MatterWorkspaceResponse,
    ResolvedBenchMember,
    normalize_matter_code,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.conflict_checks import (
    ConflictGateDecision,
    evaluate_matter_opening_gate,
)
from caseops_api.services.document_jobs import (
    enqueue_processing_job,
    load_latest_processing_jobs,
)
from caseops_api.services.document_storage import (
    persist_matter_attachment,
    resolve_storage_path,
    sanitize_filename,
)
from caseops_api.services.matter_access import (
    assert_access,
    can_access,
    visible_matters_filter,
)
from caseops_api.services.matter_billing import (
    calculate_invoice_tax,
    default_invoice_due_on,
    next_invoice_number,
    render_invoice_pdf,
    resolve_time_entry_rate,
)
from caseops_api.services.matter_tags import slugify_tag
from caseops_api.services.next_hearing import apply_next_hearing_update, clear_next_hearing
from caseops_api.services.session_context import SessionContext
from caseops_api.services.storage_governance import (
    StorageQuotaExceeded,
    assert_storage_quota_allows_upload,
    get_storage_upload_policy,
    record_storage_quota_blocked_upload,
)

logger = logging.getLogger(__name__)
ACTIVE_STAY_STATUSES = {"granted", "continued", "modified"}
FORUM_SELECTION_FIELDS = {
    "forum_level",
    "court_id",
    "court_name",
    "forum_catalog_entry_id",
    "forum_state",
    "forum_district",
    "forum_city",
    "forum_consumer_level",
}
DOCUMENT_TYPE_DEFAULT_LIFECYCLE: dict[str, str] = {
    "complaint_petition": "initiation",
    "notice": "initiation",
    "vakalatnama": "administrative",
    "pleading_reply": "pleadings",
    "affidavit": "pleadings",
    "chief_affidavit": "pleadings",
    "counter_affidavit": "pleadings",
    "evidence": "evidence",
    "written_submission": "arguments",
    "interim_application": "interim_applications",
    "order_judgment": "orders",
    "correspondence": "administrative",
    "research": "administrative",
    "billing": "administrative",
    "other": "other",
}


def _status_value(value: object) -> str | None:
    if value is None:
        return None
    status_value = str(value)
    return "disposed" if status_value == "closed" else status_value


def _conflict_gate_metadata(
    *,
    decision: ConflictGateDecision,
    from_status: str,
    to_status: str,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "from_status": from_status,
        "to_status": to_status,
        "conflict_gate": {
            "reason": decision.reason,
            "latest_check_id": decision.latest_check_id,
            "latest_status": decision.latest_status,
            "latest_ran_at": decision.latest_ran_at.isoformat()
            if decision.latest_ran_at
            else None,
        },
    }
    return metadata


def _conflict_gate_block_detail(decision: ConflictGateDecision) -> str:
    if decision.reason == "missing_check":
        return (
            "Matter cannot be activated until a conflict check is completed "
            "as clear or waived."
        )
    if decision.latest_status == MatterConflictCheckStatus.CONFLICTED.value:
        return (
            "Matter cannot be activated because the latest conflict check "
            "indicates a possible conflict requiring review."
        )
    return (
        "Matter cannot be activated because the latest conflict check "
        "requires review or waiver."
    )


def _order_has_active_stay(order: MatterCourtOrder) -> bool:
    return (order.stay_status or "none") in ACTIVE_STAY_STATUSES


def _normalize_order_identity_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).strip()
    return normalized or None


def _order_text_hash(value: str | None) -> str | None:
    normalized = _normalize_order_identity_text(value)
    if normalized is None:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _find_existing_imported_order(
    session: Session,
    *,
    matter_id: str,
    source: str,
    source_reference: str | None,
    order_date: date,
    title: str,
    order_text: str | None,
) -> MatterCourtOrder | None:
    """Find the same source order across court-sync reruns.

    The raw-text hash is mandatory so same-date daily orders do not collapse
    unless their source text is actually equivalent.
    """

    incoming_hash = _order_text_hash(order_text)
    if incoming_hash is None:
        return None
    incoming_title = (_normalize_order_identity_text(title) or "").casefold()
    stmt = select(MatterCourtOrder).where(
        MatterCourtOrder.matter_id == matter_id,
        MatterCourtOrder.source == source,
        MatterCourtOrder.order_date == order_date,
    )
    if source_reference:
        stmt = stmt.where(MatterCourtOrder.source_reference == source_reference)
    else:
        stmt = stmt.where(MatterCourtOrder.source_reference.is_(None))
    for candidate in session.scalars(stmt):
        candidate_title = (_normalize_order_identity_text(candidate.title) or "").casefold()
        if (
            candidate_title == incoming_title
            and _order_text_hash(candidate.order_text) == incoming_hash
        ):
            return candidate
    return None


def _order_is_interim(order: MatterCourtOrder) -> bool:
    return bool(order.is_interim_order) or order.order_kind == "interim_order"


def _matter_record(matter: Matter) -> MatterRecord:
    if matter.status == "closed":
        matter.status = MatterStatus.DISPOSED.value
    record = MatterRecord.model_validate(matter)
    assignments = list(getattr(matter, "tag_assignments", []) or [])
    record.tags = [
        MatterTagRecord.model_validate(assignment.tag)
        for assignment in sorted(
            assignments,
            key=lambda item: item.tag.name.lower() if item.tag else "",
        )
        if assignment.tag is not None
    ]
    orders = list(getattr(matter, "court_orders", []) or [])
    record.has_stay = any(_order_has_active_stay(order) for order in orders)
    record.has_interim_order = any(_order_is_interim(order) for order in orders)
    return record


def _clean_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _forum_snapshot(matter: Matter) -> dict[str, str | None]:
    return {
        "forum_level": matter.forum_level,
        "court_id": matter.court_id,
        "court_name": matter.court_name,
        "forum_catalog_entry_id": matter.forum_catalog_entry_id,
        "forum_state": matter.forum_state,
        "forum_district": matter.forum_district,
        "forum_city": matter.forum_city,
        "forum_consumer_level": matter.forum_consumer_level,
    }


def _load_active_court(session: Session, court_id: str | None) -> Court | None:
    if not court_id:
        return None
    court = session.scalar(
        select(Court).where(Court.id == court_id, Court.is_active.is_(True))
    )
    if court is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Court was not found in the public court catalog.",
        )
    return court


def _load_forum_catalog_entry(
    session: Session, entry_id: str | None
) -> ForumCatalogEntry | None:
    if not entry_id:
        return None
    entry = session.scalar(
        select(ForumCatalogEntry).where(
            ForumCatalogEntry.id == entry_id,
            ForumCatalogEntry.is_active.is_(True),
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forum selection was not found in the public catalog.",
        )
    return entry


def _validate_forum_metadata(entry: ForumCatalogEntry) -> None:
    if entry.forum_type == "supreme_court":
        return
    if entry.forum_type == "high_court" and not entry.state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="High Court selection requires a state.",
        )
    if entry.forum_type == "district_court" and (
        not entry.state or not (entry.district or entry.city)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="District Court selection requires state and district/city.",
        )
    if entry.forum_type == "consumer_forum":
        if entry.consumer_level in {"state", "district"} and not entry.state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="State consumer forum selection requires a state.",
            )
        if entry.consumer_level == "district" and not (entry.district or entry.city):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="District consumer forum selection requires district/city.",
            )


def _assert_matching_optional(
    *,
    provided: str | None,
    expected: str | None,
    field_name: str,
) -> None:
    if provided and expected and provided.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} does not match the selected forum catalog entry.",
        )


def _resolve_forum_selection(
    session: Session,
    *,
    forum_level: str | None,
    court_id: str | None,
    court_name: str | None,
    forum_catalog_entry_id: str | None,
    forum_state: str | None,
    forum_district: str | None,
    forum_city: str | None,
    forum_consumer_level: str | None,
) -> dict[str, str | None]:
    clean_forum_level = _clean_optional_str(forum_level)
    clean_court_id = _clean_optional_str(court_id)
    clean_court_name = _clean_optional_str(court_name)
    clean_catalog_entry_id = _clean_optional_str(forum_catalog_entry_id)
    clean_state = _clean_optional_str(forum_state)
    clean_district = _clean_optional_str(forum_district)
    clean_city = _clean_optional_str(forum_city)
    clean_consumer_level = _clean_optional_str(forum_consumer_level)

    entry = _load_forum_catalog_entry(session, clean_catalog_entry_id)
    if entry is not None:
        _validate_forum_metadata(entry)
        _assert_matching_optional(
            provided=clean_forum_level,
            expected=entry.forum_level,
            field_name="forum_level",
        )
        if clean_court_id:
            if entry.court_id is None or clean_court_id != entry.court_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="court_id does not match the selected forum catalog entry.",
                )
            provided_court = _load_active_court(session, clean_court_id)
            if provided_court is None or provided_court.forum_level != entry.forum_level:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="court_id does not match the selected forum level.",
                )
        _assert_matching_optional(
            provided=clean_state,
            expected=entry.state,
            field_name="forum_state",
        )
        _assert_matching_optional(
            provided=clean_district,
            expected=entry.district,
            field_name="forum_district",
        )
        _assert_matching_optional(
            provided=clean_city,
            expected=entry.city,
            field_name="forum_city",
        )
        _assert_matching_optional(
            provided=clean_consumer_level,
            expected=entry.consumer_level,
            field_name="forum_consumer_level",
        )
        return {
            "forum_level": entry.forum_level,
            "court_id": entry.court_id,
            "court_name": entry.name,
            "forum_catalog_entry_id": entry.id,
            "forum_state": entry.state,
            "forum_district": entry.district,
            "forum_city": entry.city,
            "forum_consumer_level": entry.consumer_level,
        }

    court = _load_active_court(session, clean_court_id)
    if court is not None:
        _assert_matching_optional(
            provided=clean_forum_level,
            expected=court.forum_level,
            field_name="forum_level",
        )
        return {
            "forum_level": court.forum_level,
            "court_id": court.id,
            "court_name": clean_court_name or court.name,
            "forum_catalog_entry_id": None,
            "forum_state": clean_state or court.jurisdiction,
            "forum_district": clean_district,
            "forum_city": clean_city or court.seat_city,
            "forum_consumer_level": clean_consumer_level,
        }

    if clean_forum_level is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="forum_level is required when no catalog forum is selected.",
        )
    if clean_forum_level == "tribunal" and clean_consumer_level:
        if clean_consumer_level in {"state", "district"} and not clean_state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Consumer forum fallback selection requires a state.",
            )
        if clean_consumer_level == "district" and not clean_district:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="District consumer forum fallback selection requires a district.",
            )
        if not clean_court_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Consumer forum fallback selection requires a forum name.",
            )
    return {
        "forum_level": clean_forum_level,
        "court_id": None,
        "court_name": clean_court_name,
        "forum_catalog_entry_id": None,
        "forum_state": clean_state,
        "forum_district": clean_district,
        "forum_city": clean_city,
        "forum_consumer_level": clean_consumer_level,
    }


def _apply_forum_selection(matter: Matter, selection: dict[str, str | None]) -> None:
    matter.forum_level = selection["forum_level"] or matter.forum_level
    matter.court_id = selection["court_id"]
    matter.court_name = selection["court_name"]
    matter.forum_catalog_entry_id = selection["forum_catalog_entry_id"]
    matter.forum_state = selection["forum_state"]
    matter.forum_district = selection["forum_district"]
    matter.forum_city = selection["forum_city"]
    matter.forum_consumer_level = selection["forum_consumer_level"]


def _membership_summary(membership: CompanyMembership) -> MatterWorkspaceMembership:
    return MatterWorkspaceMembership(
        membership_id=membership.id,
        user_id=membership.user.id,
        full_name=membership.user.full_name,
        email=membership.user.email,
        role=membership.role,
        is_active=membership.is_active and membership.user.is_active,
    )


def _note_record(note: MatterNote) -> MatterNoteRecord:
    return MatterNoteRecord(
        id=note.id,
        matter_id=note.matter_id,
        author_membership_id=note.author_membership_id,
        author_name=note.author_membership.user.full_name,
        author_role=note.author_membership.role,
        body=note.body,
        created_at=note.created_at,
    )


def _task_record(task: MatterTask) -> MatterTaskRecord:
    return _task_record_with_source(task)


def _task_record_with_source(
    task: MatterTask,
    *,
    source_type: str = "user",
    source_ref_id: str | None = None,
    source_label: str | None = None,
) -> MatterTaskRecord:
    return MatterTaskRecord(
        id=task.id,
        matter_id=task.matter_id,
        created_by_membership_id=task.created_by_membership_id,
        created_by_name=(
            task.created_by_membership.user.full_name
            if task.created_by_membership and task.created_by_membership.user
            else None
        ),
        owner_membership_id=task.owner_membership_id,
        owner_name=(
            task.owner_membership.user.full_name
            if task.owner_membership and task.owner_membership.user
            else None
        ),
        title=task.title,
        description=task.description,
        due_on=task.due_on,
        status=task.status,
        priority=task.priority,
        source_type=source_type,
        source_ref_id=source_ref_id,
        source_label=source_label,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _hearing_record(hearing: MatterHearing) -> MatterHearingRecord:
    return MatterHearingRecord(
        id=hearing.id,
        matter_id=hearing.matter_id,
        hearing_on=hearing.hearing_on,
        forum_name=hearing.forum_name,
        judge_name=hearing.judge_name,
        purpose=hearing.purpose,
        status=hearing.status,
        outcome_note=hearing.outcome_note,
        created_at=hearing.created_at,
    )


def _activity_record(activity: MatterActivity) -> MatterActivityRecord:
    return MatterActivityRecord(
        id=activity.id,
        matter_id=activity.matter_id,
        actor_membership_id=activity.actor_membership_id,
        actor_name=activity.actor_membership.user.full_name if activity.actor_membership else None,
        event_type=activity.event_type,
        title=activity.title,
        detail=activity.detail,
        created_at=activity.created_at,
    )


def _parse_resolved_bench(judges_json: str | None):
    """Slice B (MOD-TS-001-C, 2026-04-25). Decode the resolver's JSON
    blob to a list of ResolvedBenchMember rows for the API response.
    Returns None when the resolver hasn't processed the row yet
    (judges_json IS NULL); empty list when it processed but no judge
    cleared the floor; populated list otherwise."""
    if judges_json is None:
        return None
    import json as _json

    try:
        parsed = _json.loads(judges_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    out = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        jid = item.get("judge_id")
        if not jid:
            continue
        out.append(
            ResolvedBenchMember(
                judge_id=str(jid),
                matched_alias=str(item.get("matched_alias") or ""),
                confidence=str(item.get("confidence") or "exact"),
            )
        )
    return out


def _cause_list_entry_record(entry: MatterCauseListEntry) -> MatterCauseListEntryRecord:
    return MatterCauseListEntryRecord(
        id=entry.id,
        matter_id=entry.matter_id,
        sync_run_id=entry.sync_run_id,
        listing_date=entry.listing_date,
        forum_name=entry.forum_name,
        bench_name=entry.bench_name,
        courtroom=entry.courtroom,
        item_number=entry.item_number,
        stage=entry.stage,
        notes=entry.notes,
        source=entry.source,
        source_reference=entry.source_reference,
        synced_at=entry.synced_at,
        created_at=entry.created_at,
        resolved_bench=_parse_resolved_bench(entry.judges_json),
    )


def _court_order_record(order: MatterCourtOrder) -> MatterCourtOrderRecord:
    judge_names = order.judge_names_json
    if not isinstance(judge_names, list):
        judge_names = None
    return MatterCourtOrderRecord(
        id=order.id,
        matter_id=order.matter_id,
        sync_run_id=order.sync_run_id,
        order_date=order.order_date,
        title=order.title,
        summary=order.summary,
        order_text=order.order_text,
        source=order.source,
        source_reference=order.source_reference,
        bench_name=order.bench_name,
        judge_names=judge_names,
        order_attachment_id=order.order_attachment_id,
        order_kind=order.order_kind,
        is_interim_order=bool(order.is_interim_order),
        stay_status=order.stay_status,
        stay_effective_until=order.stay_effective_until,
        synced_at=order.synced_at,
        created_at=order.created_at,
    )


def _court_sync_run_record(run: MatterCourtSyncRun) -> MatterCourtSyncRunRecord:
    return MatterCourtSyncRunRecord(
        id=run.id,
        matter_id=run.matter_id,
        triggered_by_membership_id=run.triggered_by_membership_id,
        triggered_by_name=(
            run.triggered_by_membership.user.full_name
            if run.triggered_by_membership and run.triggered_by_membership.user
            else None
        ),
        source=run.source,
        status=run.status,
        summary=run.summary,
        imported_cause_list_count=run.imported_cause_list_count,
        imported_order_count=run.imported_order_count,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _court_sync_job_record(job: MatterCourtSyncJob) -> MatterCourtSyncJobRecord:
    return MatterCourtSyncJobRecord(
        id=job.id,
        matter_id=job.matter_id,
        requested_by_membership_id=job.requested_by_membership_id,
        requested_by_name=(
            job.requested_by_membership.user.full_name
            if job.requested_by_membership and job.requested_by_membership.user
            else None
        ),
        sync_run_id=job.sync_run_id,
        source=job.source,
        source_reference=job.source_reference,
        adapter_name=job.adapter_name,
        status=job.status,
        imported_cause_list_count=job.imported_cause_list_count,
        imported_order_count=job.imported_order_count,
        error_message=job.error_message,
        queued_at=job.queued_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        updated_at=job.updated_at,
    )


def _attachment_record(
    attachment: MatterAttachment,
    *,
    latest_job: DocumentProcessingJobRecord | None = None,
) -> MatterAttachmentRecord:
    return MatterAttachmentRecord(
        id=attachment.id,
        matter_id=attachment.matter_id,
        uploaded_by_membership_id=attachment.uploaded_by_membership_id,
        uploaded_by_name=(
            attachment.uploaded_by_membership.user.full_name
            if attachment.uploaded_by_membership and attachment.uploaded_by_membership.user
            else None
        ),
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        sha256_hex=attachment.sha256_hex,
        processing_status=attachment.processing_status,
        extracted_char_count=attachment.extracted_char_count,
        extraction_error=attachment.extraction_error,
        processed_at=attachment.processed_at,
        latest_job=latest_job,
        document_type=attachment.document_type,
        lifecycle_stage=attachment.lifecycle_stage,
        document_date=attachment.document_date,
        sequence_index=attachment.sequence_index,
        linked_court_order_id=attachment.linked_court_order_id,
        hearing_id=attachment.hearing_id,
        created_at=attachment.created_at,
    )


def _time_entry_record(time_entry: MatterTimeEntry) -> TimeEntryRecord:
    return TimeEntryRecord(
        id=time_entry.id,
        matter_id=time_entry.matter_id,
        author_membership_id=time_entry.author_membership_id,
        author_name=(
            time_entry.author_membership.user.full_name
            if time_entry.author_membership and time_entry.author_membership.user
            else None
        ),
        work_date=time_entry.work_date,
        description=time_entry.description,
        duration_minutes=time_entry.duration_minutes,
        billable=time_entry.billable,
        rate_currency=time_entry.rate_currency,
        rate_amount_minor=time_entry.rate_amount_minor,
        billing_rate_id=time_entry.billing_rate_id,
        rate_source=time_entry.rate_source,
        total_amount_minor=time_entry.total_amount_minor,
        is_invoiced=time_entry.invoice_line_item is not None,
        created_at=time_entry.created_at,
    )


def _invoice_line_item_record(line_item: MatterInvoiceLineItem) -> InvoiceLineItemRecord:
    return InvoiceLineItemRecord(
        id=line_item.id,
        invoice_id=line_item.invoice_id,
        time_entry_id=line_item.time_entry_id,
        description=line_item.description,
        duration_minutes=line_item.duration_minutes,
        unit_rate_amount_minor=line_item.unit_rate_amount_minor,
        line_total_amount_minor=line_item.line_total_amount_minor,
        category=line_item.category,
        sac_hsn=line_item.sac_hsn,
        created_at=line_item.created_at,
    )


def _invoice_record(invoice: MatterInvoice) -> InvoiceRecord:
    return InvoiceRecord(
        id=invoice.id,
        company_id=invoice.company_id,
        matter_id=invoice.matter_id,
        issued_by_membership_id=invoice.issued_by_membership_id,
        issued_by_name=(
            invoice.issued_by_membership.user.full_name
            if invoice.issued_by_membership and invoice.issued_by_membership.user
            else None
        ),
        invoice_number=invoice.invoice_number,
        client_name=invoice.client_name,
        client_billing_name=invoice.client_billing_name,
        client_billing_address=invoice.client_billing_address,
        client_gstin=invoice.client_gstin,
        place_of_supply=invoice.place_of_supply,
        sac_hsn=invoice.sac_hsn,
        firm_legal_name=invoice.firm_legal_name,
        firm_address=invoice.firm_address,
        firm_gstin=invoice.firm_gstin,
        firm_pan=invoice.firm_pan,
        status=invoice.status,
        currency=invoice.currency,
        subtotal_amount_minor=invoice.subtotal_amount_minor,
        taxable_value_minor=invoice.taxable_value_minor,
        cgst_amount_minor=invoice.cgst_amount_minor,
        sgst_amount_minor=invoice.sgst_amount_minor,
        igst_amount_minor=invoice.igst_amount_minor,
        tax_amount_minor=invoice.tax_amount_minor,
        total_amount_minor=invoice.total_amount_minor,
        amount_received_minor=invoice.amount_received_minor,
        tds_deducted_minor=invoice.tds_deducted_minor,
        payment_adjustment_minor=invoice.payment_adjustment_minor,
        balance_due_minor=invoice.balance_due_minor,
        issued_on=invoice.issued_on,
        due_on=invoice.due_on,
        notes=invoice.notes,
        pine_labs_payment_url=invoice.pine_labs_payment_url,
        pine_labs_order_id=invoice.pine_labs_order_id,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
        line_items=[_invoice_line_item_record(line_item) for line_item in invoice.line_items],
        payment_attempts=[
            InvoicePaymentAttemptRecord(
                id=attempt.id,
                invoice_id=attempt.invoice_id,
                initiated_by_membership_id=attempt.initiated_by_membership_id,
                initiated_by_name=(
                    attempt.initiated_by_membership.user.full_name
                    if attempt.initiated_by_membership and attempt.initiated_by_membership.user
                    else None
                ),
                provider=attempt.provider,
                merchant_order_id=attempt.merchant_order_id,
                provider_order_id=attempt.provider_order_id,
                status=attempt.status,
                amount_minor=attempt.amount_minor,
                amount_received_minor=attempt.amount_received_minor,
                currency=attempt.currency,
                customer_name=attempt.customer_name,
                customer_email=attempt.customer_email,
                customer_phone=attempt.customer_phone,
                payment_url=attempt.payment_url,
                provider_reference=attempt.provider_reference,
                last_webhook_at=attempt.last_webhook_at,
                created_at=attempt.created_at,
                updated_at=attempt.updated_at,
            )
            for attempt in invoice.payment_attempts
        ],
    )


def _raise_billing_permission_error() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only owners and admins can create invoices.",
    )


def _raise_processing_permission_error() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only owners and admins can retry or reindex attachments.",
    )


def _calculate_time_entry_total(
    *,
    duration_minutes: int,
    rate_amount_minor: int | None,
    billable: bool,
) -> int:
    if not billable or rate_amount_minor is None:
        return 0
    return round((duration_minutes * rate_amount_minor) / 60)


def _append_activity(
    session: Session,
    *,
    matter_id: str,
    actor_membership_id: str | None,
    event_type: str,
    title: str,
    detail: str | None = None,
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


def _default_lifecycle_stage(document_type: str | None) -> str | None:
    if document_type is None:
        return None
    return DOCUMENT_TYPE_DEFAULT_LIFECYCLE.get(document_type)


def _validated_sequence_index(sequence_index: int | None) -> int | None:
    if sequence_index is not None and sequence_index < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="sequence_index must be greater than or equal to 0.",
        )
    return sequence_index


def _attachment_record_map(
    session: Session,
    attachments: list[MatterAttachment],
) -> list[MatterAttachmentRecord]:
    latest_jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
        attachment_ids=[attachment.id for attachment in attachments],
    )
    return [
        _attachment_record(attachment, latest_job=latest_jobs.get(attachment.id))
        for attachment in attachments
    ]


def _task_sort_key(task: MatterTask) -> tuple[int, date, datetime]:
    status_rank = 1 if task.status == MatterTaskStatus.COMPLETED else 0
    due_on = task.due_on or date.max
    return (status_rank, due_on, task.created_at)


def _get_company_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> CompanyMembership:
    membership = session.scalar(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user))
        .where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if not membership or not membership.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignee membership was not found in the current company.",
        )
    return membership


def _get_matter_model(session: Session, *, context: SessionContext, matter_id: str) -> Matter:
    matter = session.scalar(
        select(Matter)
        .options(
            joinedload(Matter.assignee_membership).joinedload(CompanyMembership.user),
            selectinload(Matter.tasks)
            .joinedload(MatterTask.created_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.tasks)
            .joinedload(MatterTask.owner_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.notes)
            .joinedload(MatterNote.author_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.hearings),
            selectinload(Matter.activity_events)
            .joinedload(MatterActivity.actor_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.tag_assignments).joinedload(MatterTagAssignment.tag),
            selectinload(Matter.cause_list_entries),
            selectinload(Matter.court_orders),
            selectinload(Matter.court_sync_runs)
            .joinedload(MatterCourtSyncRun.triggered_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.court_sync_jobs)
            .joinedload(MatterCourtSyncJob.requested_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.attachments)
            .joinedload(MatterAttachment.uploaded_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.attachments).selectinload(MatterAttachment.chunks),
            selectinload(Matter.time_entries)
            .joinedload(MatterTimeEntry.author_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.time_entries).selectinload(MatterTimeEntry.invoice_line_item),
            selectinload(Matter.invoices)
            .joinedload(MatterInvoice.issued_by_membership)
            .joinedload(CompanyMembership.user),
            selectinload(Matter.invoices).selectinload(MatterInvoice.line_items),
            selectinload(Matter.invoices)
            .selectinload(MatterInvoice.payment_attempts)
            .joinedload(MatterInvoicePaymentAttempt.initiated_by_membership)
            .joinedload(CompanyMembership.user),
        )
        .where(Matter.id == matter_id, Matter.company_id == context.company.id)
    )
    if not matter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return matter


def _assert_membership_can_access_matter(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    membership: CompanyMembership,
) -> None:
    candidate_context = SessionContext(
        company=context.company,
        user=membership.user,
        membership=membership,
    )
    if can_access(session, context=candidate_context, matter=matter):
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Assignee cannot access this matter.",
    )


def _get_matter_attachment_model(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
) -> MatterAttachment:
    attachment = session.scalar(
        select(MatterAttachment)
        .options(
            joinedload(MatterAttachment.uploaded_by_membership).joinedload(CompanyMembership.user),
            selectinload(MatterAttachment.chunks),
        )
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(
            MatterAttachment.id == attachment_id,
            MatterAttachment.matter_id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    return attachment


def create_matter(
    session: Session,
    *,
    context: SessionContext,
    payload: MatterCreateRequest,
) -> MatterRecord:
    if payload.status == MatterStatus.ACTIVE.value:
        record_from_context(
            session,
            context,
            action="matter.status_transition.blocked",
            target_type="matter",
            result=AuditResult.DENIED,
            metadata={
                "from_status": None,
                "to_status": MatterStatus.ACTIVE.value,
                "conflict_gate": {
                    "reason": "direct_active_create_blocked",
                    "latest_check_id": None,
                    "latest_status": None,
                    "latest_ran_at": None,
                },
            },
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Matter cannot be created as active. Create it in intake and "
                "complete conflict clearance before activation."
            ),
        )
    from caseops_api.services.saas_billing import assert_matter_limit

    assert_matter_limit(session, context=context)
    existing_matter = session.scalar(
        select(Matter).where(
            Matter.company_id == context.company.id,
            Matter.matter_code == payload.matter_code.strip(),
        )
    )
    if existing_matter:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A matter with this code already exists for the current company.",
        )
    forum_selection = _resolve_forum_selection(
        session,
        forum_level=payload.forum_level,
        court_id=payload.court_id,
        court_name=payload.court_name,
        forum_catalog_entry_id=payload.forum_catalog_entry_id,
        forum_state=payload.forum_state,
        forum_district=payload.forum_district,
        forum_city=payload.forum_city,
        forum_consumer_level=payload.forum_consumer_level,
    )

    matter = Matter(
        company_id=context.company.id,
        title=payload.title.strip(),
        matter_code=payload.matter_code.strip(),
        client_name=payload.client_name.strip() if payload.client_name else None,
        opposing_party=payload.opposing_party.strip() if payload.opposing_party else None,
        case_number=payload.case_number.strip() if payload.case_number else None,
        cnr_number=payload.cnr_number.strip() if payload.cnr_number else None,
        status=payload.status,
        practice_area=payload.practice_area.strip(),
        forum_level=forum_selection["forum_level"] or payload.forum_level,
        court_id=forum_selection["court_id"],
        court_name=forum_selection["court_name"],
        forum_catalog_entry_id=forum_selection["forum_catalog_entry_id"],
        forum_state=forum_selection["forum_state"],
        forum_district=forum_selection["forum_district"],
        forum_city=forum_selection["forum_city"],
        forum_consumer_level=forum_selection["forum_consumer_level"],
        judge_name=payload.judge_name.strip() if payload.judge_name else None,
        description=payload.description.strip() if payload.description else None,
        claim_amount_minor=payload.claim_amount_minor,
        claim_currency=payload.claim_currency.strip().upper(),
        claim_amount_notes=payload.claim_amount_notes.strip()
        if payload.claim_amount_notes else None,
    )
    session.add(matter)
    session.flush()
    if payload.next_hearing_on is not None:
        apply_next_hearing_update(
            session,
            matter=matter,
            new_date=payload.next_hearing_on,
            source="manual",
            actor_membership_id=context.membership.id,
            context=context,
            reason="matter_created",
            manual_lock=payload.next_hearing_manual_lock,
        )
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="matter_created",
        title="Matter created",
        detail=f"{matter.matter_code} created as {matter.status}.",
    )
    record_from_context(
        session,
        context,
        action="matter.created",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={
            "matter_code": matter.matter_code,
            "status": matter.status,
            "forum_level": matter.forum_level,
            "court_id": matter.court_id,
            "court_name": matter.court_name,
            "forum_catalog_entry_id": matter.forum_catalog_entry_id,
            "forum_state": matter.forum_state,
            "forum_district": matter.forum_district,
            "forum_city": matter.forum_city,
            "forum_consumer_level": matter.forum_consumer_level,
            "claim_amount_minor": matter.claim_amount_minor,
            "claim_currency": matter.claim_currency,
        },
    )
    session.commit()
    session.refresh(matter)
    return _matter_record(matter)


def _created_boundary(value: date, *, end: bool = False) -> datetime:
    return datetime.combine(value, time.max if end else time.min, tzinfo=UTC)


def _apply_list_filters(stmt, filters: MatterListFilters):
    if (
        filters.min_claim_amount_minor is not None
        and filters.max_claim_amount_minor is not None
        and filters.min_claim_amount_minor > filters.max_claim_amount_minor
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_claim_amount_minor cannot exceed max_claim_amount_minor.",
        )

    if filters.q:
        needle = f"%{filters.q.strip()}%"
        stmt = stmt.where(
            or_(
                Matter.title.ilike(needle),
                Matter.matter_code.ilike(needle),
                Matter.client_name.ilike(needle),
                Matter.opposing_party.ilike(needle),
                Matter.court_name.ilike(needle),
                Matter.practice_area.ilike(needle),
            )
        )
    if filters.client_name:
        stmt = stmt.where(Matter.client_name.ilike(f"%{filters.client_name.strip()}%"))
    if filters.opposing_party:
        stmt = stmt.where(
            Matter.opposing_party.ilike(f"%{filters.opposing_party.strip()}%")
        )
    if filters.forum_level:
        stmt = stmt.where(Matter.forum_level == filters.forum_level)
    if filters.court_id:
        stmt = stmt.where(Matter.court_id == filters.court_id.strip())
    if filters.status:
        stmt = stmt.where(Matter.status == filters.status)
    if filters.created_from:
        stmt = stmt.where(Matter.created_at >= _created_boundary(filters.created_from))
    if filters.created_to:
        stmt = stmt.where(Matter.created_at <= _created_boundary(filters.created_to, end=True))
    if filters.next_hearing_from:
        stmt = stmt.where(Matter.next_hearing_on >= filters.next_hearing_from)
    if filters.next_hearing_to:
        stmt = stmt.where(Matter.next_hearing_on <= filters.next_hearing_to)
    if filters.tag:
        tag_value = filters.tag.strip()
        tag_slug = slugify_tag(tag_value)
        tag_exists = (
            select(MatterTagAssignment.id)
            .join(MatterTag, MatterTag.id == MatterTagAssignment.tag_id)
            .where(MatterTagAssignment.matter_id == Matter.id)
            .where(MatterTagAssignment.company_id == Matter.company_id)
            .where(MatterTag.company_id == Matter.company_id)
            .where(
                or_(
                    MatterTag.id == tag_value,
                    MatterTag.slug == tag_slug,
                    MatterTag.name.ilike(tag_value),
                )
            )
        )
        stmt = stmt.where(tag_exists.exists())
    if filters.has_stay is not None:
        stay_exists = (
            select(MatterCourtOrder.id)
            .where(MatterCourtOrder.matter_id == Matter.id)
            .where(MatterCourtOrder.stay_status.in_(ACTIVE_STAY_STATUSES))
        )
        stmt = stmt.where(stay_exists.exists() if filters.has_stay else ~stay_exists.exists())
    if filters.min_claim_amount_minor is not None:
        stmt = stmt.where(Matter.claim_amount_minor >= filters.min_claim_amount_minor)
    if filters.max_claim_amount_minor is not None:
        stmt = stmt.where(Matter.claim_amount_minor <= filters.max_claim_amount_minor)
    return stmt


def list_matters(
    session: Session,
    *,
    context: SessionContext,
    limit: int | None = None,
    cursor: str | None = None,
    filters: MatterListFilters | None = None,
) -> MatterListResponse:
    from caseops_api.services.pagination import (
        clamp_limit,
        decode_cursor,
        encode_cursor,
    )

    page_size = clamp_limit(limit)
    decoded = decode_cursor(cursor)

    stmt = (
        select(Matter)
        .options(
            selectinload(Matter.tag_assignments).joinedload(MatterTagAssignment.tag),
            selectinload(Matter.court_orders),
        )
        .where(
            Matter.company_id == context.company.id,
            visible_matters_filter(session, context=context),
        )
        .order_by(Matter.updated_at.desc(), Matter.id.desc())
    )
    stmt = _apply_list_filters(stmt, filters or MatterListFilters())
    if decoded is not None:
        stmt = stmt.where(
            or_(
                Matter.updated_at < decoded.updated_at,
                and_(
                    Matter.updated_at == decoded.updated_at,
                    Matter.id < decoded.id,
                ),
            )
        )

    rows = list(session.scalars(stmt.limit(page_size + 1)))
    has_more = len(rows) > page_size
    if has_more:
        rows = rows[:page_size]
    next_cursor = (
        encode_cursor(rows[-1].updated_at, rows[-1].id) if has_more and rows else None
    )
    return MatterListResponse(
        company_id=context.company.id,
        matters=[_matter_record(matter) for matter in rows],
        next_cursor=next_cursor,
    )


def get_matter(session: Session, *, context: SessionContext, matter_id: str) -> MatterRecord:
    return _matter_record(_get_matter_model(session, context=context, matter_id=matter_id))


def matter_code_available(
    session: Session, *, context: SessionContext, code: str,
) -> dict:
    """Pre-submit guard for the intake → matter promotion dialog
    (BUG-021 / Strict Ledger #3). Returns
    ``{available: bool, normalised: str, suggestion: str | None}``.

    - ``normalised`` is the upper-cased + stripped form the backend
      will actually persist; the UI should reflect this so the user
      knows what they're submitting.
    - ``suggestion`` is the next lexically-bumped variant when the
      code is taken (e.g. ``CR-2026-099 → CR-2026-100``); the dialog
      uses it as a one-click 'Try this' affordance, mirroring the
      post-failure auto-suggest the BUG-017 fix shipped — but now the
      user gets it BEFORE the failed submit.
    Tenant-scoped: codes from other companies cannot leak in either
    the availability check or the suggestion.
    """
    try:
        normalised = normalize_matter_code(code)
    except ValueError:
        return {
            "available": False,
            "normalised": (code or "").strip().upper(),
            "suggestion": None,
            "reason": MATTER_CODE_ERROR,
        }
    existing = session.scalar(
        select(Matter.id).where(
            Matter.company_id == context.company.id,
            Matter.matter_code == normalised,
        )
    )
    if existing is None:
        return {
            "available": True,
            "normalised": normalised,
            "suggestion": None,
            "reason": None,
        }
    suggestion = _next_available_code(
        session, company_id=context.company.id, code=normalised,
    )
    return {
        "available": False,
        "normalised": normalised,
        "suggestion": suggestion,
        "reason": "Matter code is already in use in this workspace.",
    }


def _next_available_code(
    session: Session, *, company_id: str, code: str, max_iters: int = 100,
) -> str | None:
    """Bump the trailing numeric segment until we find a free code.
    Mirrors the frontend ``suggestNextMatterCode`` so server + client
    suggest the same value on a duplicate. Returns None when no
    trailing number is found OR the bump search is exhausted (very
    unlikely — the cap is just a hard safety stop)."""
    trailing_digits = len(code) - len(code.rstrip("0123456789"))
    if trailing_digits == 0:
        return None

    prefix = code[:-trailing_digits]
    digits = code[-trailing_digits:]
    width = len(digits)
    n = int(digits)
    for _ in range(max_iters):
        n += 1
        candidate = f"{prefix}{str(n).zfill(width)}"
        taken = session.scalar(
            select(Matter.id).where(
                Matter.company_id == company_id,
                Matter.matter_code == candidate,
            )
        )
        if taken is None:
            return candidate
    return None


def update_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterUpdateRequest,
) -> MatterRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)

    updates = payload.model_dump(exclude_unset=True)
    status_before = _status_value(matter.status)
    requested_status = _status_value(updates.get("status"))
    opening_gate_decision: ConflictGateDecision | None = None
    if requested_status == MatterStatus.ACTIVE.value and (
        status_before != MatterStatus.ACTIVE.value
    ):
        opening_gate_decision = evaluate_matter_opening_gate(
            session,
            company_id=context.company.id,
            matter_id=matter.id,
            expected_opposing_party_name=updates.get("opposing_party")
            if "opposing_party" in updates
            else matter.opposing_party,
        )
        if not opening_gate_decision.allowed:
            record_from_context(
                session,
                context,
                action="matter.status_transition.blocked",
                target_type="matter",
                target_id=matter.id,
                matter_id=matter.id,
                result=AuditResult.DENIED,
                metadata=_conflict_gate_metadata(
                    decision=opening_gate_decision,
                    from_status=status_before,
                    to_status=MatterStatus.ACTIVE.value,
                ),
                commit=True,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_conflict_gate_block_detail(opening_gate_decision),
            )
    claim_before = {
        "claim_amount_minor": matter.claim_amount_minor,
        "claim_currency": matter.claim_currency,
        "claim_amount_notes": matter.claim_amount_notes,
    }
    forum_before = _forum_snapshot(matter)
    assignee_membership_id = updates.pop("assignee_membership_id", None)
    assignee_changed = "assignee_membership_id" in payload.model_dump(exclude_unset=True)
    if assignee_changed:
        if assignee_membership_id is None:
            matter.assignee_membership_id = None
        else:
            assignee = _get_company_membership(
                session,
                company_id=context.company.id,
                membership_id=assignee_membership_id,
            )
            matter.assignee_membership_id = assignee.id

    # Sprint 8c: validate team membership lives in this company before
    # letting the setattr loop below accept it (otherwise a rogue
    # `team_id` from tenant A could land on tenant B's matter via a
    # raw foreign-key write).
    if "team_id" in updates:
        team_id = updates.pop("team_id")
        if team_id is None:
            matter.team_id = None
        else:
            from caseops_api.db.models import Team

            belongs = session.scalar(
                select(Team.id)
                .where(Team.id == team_id)
                .where(Team.company_id == context.company.id)
            )
            if belongs is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Team does not belong to this company.",
                )
            matter.team_id = team_id

    if FORUM_SELECTION_FIELDS & updates.keys():
        forum_selection = _resolve_forum_selection(
            session,
            forum_level=updates.pop("forum_level", matter.forum_level),
            court_id=updates.pop("court_id", matter.court_id),
            court_name=updates.pop("court_name", matter.court_name),
            forum_catalog_entry_id=updates.pop(
                "forum_catalog_entry_id", matter.forum_catalog_entry_id
            ),
            forum_state=updates.pop("forum_state", matter.forum_state),
            forum_district=updates.pop("forum_district", matter.forum_district),
            forum_city=updates.pop("forum_city", matter.forum_city),
            forum_consumer_level=updates.pop(
                "forum_consumer_level", matter.forum_consumer_level
            ),
        )
        _apply_forum_selection(matter, forum_selection)

    next_hearing_changed = "next_hearing_on" in updates
    next_hearing_on = updates.pop("next_hearing_on", None)
    next_hearing_manual_lock = updates.pop("next_hearing_manual_lock", None)

    for field_name, value in updates.items():
        if field_name == "claim_currency" and isinstance(value, str):
            value = value.strip().upper()
        if field_name == "claim_amount_notes" and isinstance(value, str):
            value = value.strip() or None
        if field_name in {"case_number", "cnr_number"} and isinstance(value, str):
            value = value.strip() or None
        setattr(matter, field_name, value)
    if next_hearing_changed and next_hearing_on is not None:
        apply_next_hearing_update(
            session,
            matter=matter,
            new_date=next_hearing_on,
            source="manual",
            actor_membership_id=context.membership.id,
            context=context,
            reason="matter_updated",
            manual_lock=bool(next_hearing_manual_lock),
            force=True,
        )
    elif next_hearing_changed and next_hearing_on is None:
        old_hearing = matter.next_hearing_on
        matter.next_hearing_on = None
        matter.next_hearing_source = "manual"
        matter.next_hearing_updated_by_membership_id = context.membership.id
        matter.next_hearing_updated_at = utcnow()
        matter.next_hearing_manual_lock = bool(next_hearing_manual_lock)
        from caseops_api.db.models import MatterNextHearingHistory

        session.add(
            MatterNextHearingHistory(
                company_id=matter.company_id,
                matter_id=matter.id,
                old_date=old_hearing,
                new_date=None,
                source="manual",
                changed_by_membership_id=context.membership.id,
                change_reason="matter_updated",
                manual_lock=matter.next_hearing_manual_lock,
            )
        )
        record_from_context(
            session,
            context,
            action="matter.next_hearing.updated",
            target_type="matter",
            target_id=matter.id,
            matter_id=matter.id,
            metadata={
                "before": old_hearing.isoformat() if old_hearing else None,
                "after": None,
                "source": "manual",
                "manual_lock": matter.next_hearing_manual_lock,
            },
        )
    elif next_hearing_manual_lock is not None:
        matter.next_hearing_manual_lock = bool(next_hearing_manual_lock)

    session.add(matter)
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="matter_updated",
        title="Matter updated",
        detail=f"Status is now {matter.status}.",
    )
    claim_after = {
        "claim_amount_minor": matter.claim_amount_minor,
        "claim_currency": matter.claim_currency,
        "claim_amount_notes": matter.claim_amount_notes,
    }
    status_after = _status_value(matter.status)
    if status_before != status_after:
        status_metadata: dict[str, object] = {
            "from_status": status_before,
            "to_status": status_after,
        }
        if opening_gate_decision is not None:
            status_metadata = _conflict_gate_metadata(
                decision=opening_gate_decision,
                from_status=status_before or "",
                to_status=status_after or "",
            )
        record_from_context(
            session,
            context,
            action="matter.status_transition.completed",
            target_type="matter",
            target_id=matter.id,
            matter_id=matter.id,
            metadata=status_metadata,
        )
    if claim_after != claim_before:
        record_from_context(
            session,
            context,
            action="matter.claim_amount.updated",
            target_type="matter",
            target_id=matter.id,
            matter_id=matter.id,
            metadata={"before": claim_before, "after": claim_after},
        )
    forum_after = _forum_snapshot(matter)
    if forum_after != forum_before:
        record_from_context(
            session,
            context,
            action="matter.forum.updated",
            target_type="matter",
            target_id=matter.id,
            matter_id=matter.id,
            metadata={"before": forum_before, "after": forum_after},
        )
    session.commit()
    session.refresh(matter)
    return _matter_record(matter)


def get_matter_workspace(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> MatterWorkspaceResponse:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(CompanyMembership.company_id == context.company.id)
            .order_by(CompanyMembership.created_at.asc())
        )
    )
    available_assignees = [
        _membership_summary(membership)
        for membership in memberships
        if membership.is_active and membership.user.is_active
    ]
    return MatterWorkspaceResponse(
        matter=_matter_record(matter),
        assignee=(
            _membership_summary(matter.assignee_membership)
            if matter.assignee_membership
            else None
        ),
        available_assignees=available_assignees,
        storage_governance=get_storage_upload_policy(
            session,
            company_id=context.company.id,
        ),
        tasks=[_task_record(task) for task in sorted(matter.tasks, key=_task_sort_key)],
        cause_list_entries=[
            _cause_list_entry_record(entry) for entry in matter.cause_list_entries
        ],
        court_orders=[_court_order_record(order) for order in matter.court_orders],
        court_sync_runs=[_court_sync_run_record(run) for run in matter.court_sync_runs],
        court_sync_jobs=[_court_sync_job_record(job) for job in matter.court_sync_jobs],
        attachments=_attachment_record_map(session, matter.attachments),
        time_entries=[_time_entry_record(time_entry) for time_entry in matter.time_entries],
        invoices=[_invoice_record(invoice) for invoice in matter.invoices],
        notes=[_note_record(note) for note in matter.notes],
        hearings=[_hearing_record(hearing) for hearing in matter.hearings],
        activity=[_activity_record(activity) for activity in matter.activity_events],
    )


def create_matter_note(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterNoteCreateRequest,
) -> MatterNoteRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    note = MatterNote(
        matter_id=matter.id,
        author_membership_id=context.membership.id,
        body=payload.body.strip(),
    )
    session.add(note)
    session.flush()
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="note_added",
        title="Internal note added",
        detail=payload.body.strip()[:140],
    )
    session.commit()
    refreshed_note = session.scalar(
        select(MatterNote)
        .options(joinedload(MatterNote.author_membership).joinedload(CompanyMembership.user))
        .where(MatterNote.id == note.id)
    )
    assert refreshed_note is not None
    return _note_record(refreshed_note)


def create_matter_task(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterTaskCreateRequest,
) -> MatterTaskRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    owner_membership_id: str | None = None
    owner_name: str | None = None
    if payload.owner_membership_id:
        owner = _get_company_membership(
            session,
            company_id=context.company.id,
            membership_id=payload.owner_membership_id,
        )
        _assert_membership_can_access_matter(
            session,
            context=context,
            matter=matter,
            membership=owner,
        )
        owner_membership_id = owner.id
        owner_name = owner.user.full_name

    task = MatterTask(
        matter_id=matter.id,
        created_by_membership_id=context.membership.id,
        owner_membership_id=owner_membership_id,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        due_on=payload.due_on,
        status=payload.status,
        priority=payload.priority,
        completed_at=utcnow() if payload.status == MatterTaskStatus.COMPLETED else None,
    )
    session.add(task)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter_task.created",
        target_type="matter_task",
        target_id=task.id,
        matter_id=matter.id,
        metadata={
            "status": task.status,
            "priority": task.priority,
            "due_on": task.due_on.isoformat() if task.due_on else None,
            "has_description": bool(task.description),
            "has_owner": bool(task.owner_membership_id),
            "source_type": "user",
        },
    )
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="task_added",
        title="Matter task created",
        detail=(
            f"{task.title} assigned to {owner_name}."
            if owner_name
            else f"{task.title} added to the workspace."
        ),
    )
    session.commit()
    refreshed_task = session.scalar(
        select(MatterTask)
        .options(
            joinedload(MatterTask.created_by_membership).joinedload(CompanyMembership.user),
            joinedload(MatterTask.owner_membership).joinedload(CompanyMembership.user),
        )
        .where(MatterTask.id == task.id)
    )
    assert refreshed_task is not None
    return _task_record(refreshed_task)


def list_matter_tasks(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    include_completed: bool = True,
) -> list[MatterTaskRecord]:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    stmt = (
        select(MatterTask)
        .options(
            joinedload(MatterTask.created_by_membership).joinedload(CompanyMembership.user),
            joinedload(MatterTask.owner_membership).joinedload(CompanyMembership.user),
        )
        .where(MatterTask.matter_id == matter.id)
        .order_by(
            MatterTask.due_on.is_(None),
            MatterTask.due_on.asc(),
            MatterTask.created_at.asc(),
            MatterTask.id.asc(),
        )
    )
    if not include_completed:
        stmt = stmt.where(MatterTask.status != MatterTaskStatus.COMPLETED)
    tasks = list(session.scalars(stmt))
    if not tasks:
        return []

    signals_by_task = {
        signal.generated_task_id: signal
        for signal in session.scalars(
            select(MatterProceedingSignal).where(
                MatterProceedingSignal.matter_id == matter.id,
                MatterProceedingSignal.generated_task_id.in_([task.id for task in tasks]),
            )
        )
        if signal.generated_task_id
    }
    rows: list[MatterTaskRecord] = []
    for task in tasks:
        signal = signals_by_task.get(task.id)
        if signal is None:
            rows.append(_task_record(task))
            continue
        rows.append(
            _task_record_with_source(
                task,
                source_type="proceeding_intelligence",
                source_ref_id=signal.id,
                source_label=signal.signal_type,
            )
        )
    return rows


def update_matter_task(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    task_id: str,
    payload: MatterTaskUpdateRequest,
) -> MatterTaskRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    task = session.scalar(
        select(MatterTask)
        .options(
            joinedload(MatterTask.created_by_membership).joinedload(CompanyMembership.user),
            joinedload(MatterTask.owner_membership).joinedload(CompanyMembership.user),
        )
        .where(MatterTask.id == task_id, MatterTask.matter_id == matter.id)
    )
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter task not found.")

    updates = payload.model_dump(exclude_unset=True)
    owner_membership_id = updates.pop("owner_membership_id", None)
    owner_changed = "owner_membership_id" in payload.model_dump(exclude_unset=True)
    if owner_changed:
        if owner_membership_id is None:
            task.owner_membership_id = None
        else:
            owner = _get_company_membership(
                session,
                company_id=context.company.id,
                membership_id=owner_membership_id,
            )
            _assert_membership_can_access_matter(
                session,
                context=context,
                matter=matter,
                membership=owner,
            )
            task.owner_membership_id = owner.id

    previous_status = task.status
    previous_due_on = task.due_on
    previous_priority = task.priority
    previous_owner = task.owner_membership_id
    for field_name, value in updates.items():
        setattr(task, field_name, value)
    if task.status == MatterTaskStatus.COMPLETED:
        task.completed_at = task.completed_at or utcnow()
    elif previous_status == MatterTaskStatus.COMPLETED:
        task.completed_at = None

    session.add(task)
    action = "matter_task.updated"
    if previous_status != task.status:
        if task.status == MatterTaskStatus.COMPLETED:
            action = "matter_task.completed"
        elif previous_status == MatterTaskStatus.COMPLETED:
            action = "matter_task.reopened"
    changed_fields = sorted(
        field
        for field, changed in {
            "status": previous_status != task.status,
            "due_on": previous_due_on != task.due_on,
            "priority": previous_priority != task.priority,
            "owner_membership_id": previous_owner != task.owner_membership_id,
            "title": "title" in updates,
            "description": "description" in updates,
        }.items()
        if changed
    )
    record_from_context(
        session,
        context,
        action=action,
        target_type="matter_task",
        target_id=task.id,
        matter_id=matter.id,
        metadata={
            "status": task.status,
            "changed_fields": changed_fields,
            "has_description": bool(task.description),
            "has_owner": bool(task.owner_membership_id),
        },
    )
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="task_updated",
        title="Matter task updated",
        detail=f"{task.title} is now {task.status}.",
    )
    session.commit()
    refreshed_task = session.scalar(
        select(MatterTask)
        .options(
            joinedload(MatterTask.created_by_membership).joinedload(CompanyMembership.user),
            joinedload(MatterTask.owner_membership).joinedload(CompanyMembership.user),
        )
        .where(MatterTask.id == task.id)
    )
    assert refreshed_task is not None
    return _task_record(refreshed_task)


def update_matter_hearing(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    hearing_id: str,
    payload,  # schemas.matters.MatterHearingUpdateRequest — quoted to avoid a circular import
) -> MatterHearingRecord:
    """Update a hearing entry. Transition to status='completed' with an
    outcome_note auto-creates a follow-up task so the PRD §9.6
    post-hearing loop survives a distracted user. Other status changes
    are recorded as activity but do not create tasks."""
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    hearing = session.scalar(
        select(MatterHearing).where(
            MatterHearing.id == hearing_id, MatterHearing.matter_id == matter.id
        )
    )
    if hearing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hearing not found."
        )

    prior_status = hearing.status
    prior_hearing_on = hearing.hearing_on
    if payload.status is not None:
        hearing.status = payload.status
    if payload.outcome_note is not None:
        hearing.outcome_note = payload.outcome_note.strip() or None
    if payload.hearing_on is not None:
        hearing.hearing_on = payload.hearing_on
        if hearing.status not in _CLOSED_HEARING_STATUSES:
            apply_next_hearing_update(
                session,
                matter=matter,
                new_date=payload.hearing_on,
                source="manual",
                actor_membership_id=context.membership.id,
                context=context,
                source_ref_type="matter_hearing",
                source_ref_id=hearing.id,
                reason="hearing_updated",
                manual_lock=True,
                force=True,
            )
    session.add(hearing)
    session.flush()

    # BUG-013 follow-up: reminders stay in sync with the hearing's real
    # state. A reschedule queues new rows for the new time AND cancels
    # the stale old ones; a completed transition just cancels queued
    # rows so the worker doesnt fire a "you have a hearing in 24h"
    # email against a hearing that already happened.
    rescheduled = (
        payload.hearing_on is not None and payload.hearing_on != prior_hearing_on
    )
    completed_transition = hearing.status == "completed" and prior_status != "completed"
    cancelled_transition = hearing.status == "cancelled" and prior_status != "cancelled"
    closed_hearing_changed = hearing.status in _CLOSED_HEARING_STATUSES and (
        completed_transition
        or cancelled_transition
        or payload.hearing_on is not None
    )
    if closed_hearing_changed:
        _reconcile_next_hearing_after_closed_hearing(
            session,
            context=context,
            matter=matter,
            hearing=hearing,
            prior_hearing_on=prior_hearing_on,
        )
    if rescheduled or completed_transition or cancelled_transition:
        try:
            from caseops_api.services.hearing_reminders import (
                cancel_reminders_for_hearing,
                schedule_reminders_for_hearing,
            )
            cancel_reminders_for_hearing(session, hearing_id=hearing.id)
            if rescheduled and hearing.status not in {"completed", "cancelled"}:
                schedule_reminders_for_hearing(session, hearing=hearing)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hearing_reminders sync on update failed: %s", exc,
            )

    if cancelled_transition:
        try:
            from caseops_api.services.calendar_sync import (
                delete_synced_hearing_events_for_context,
            )

            delete_synced_hearing_events_for_context(
                session,
                context=context,
                hearing_id=hearing.id,
                commit=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("calendar sync auto-delete on cancellation failed: %s", exc)

    completed = (
        payload.status == "completed"
        and prior_status != "completed"
    )
    if completed and (payload.create_follow_up is None or payload.create_follow_up):
        from datetime import timedelta

        due = hearing.hearing_on + timedelta(days=3)
        outcome_detail = hearing.outcome_note or "Post-hearing follow-up"
        follow_up = MatterTask(
            matter_id=matter.id,
            created_by_membership_id=context.membership.id,
            owner_membership_id=matter.assignee_membership_id,
            title=f"Post-hearing follow-up — {hearing.purpose}",
            description=outcome_detail,
            due_on=due,
            status="todo",
            priority="high",
        )
        session.add(follow_up)
        session.flush()

    if completed:
        activity_event_type = "hearing_completed"
        activity_title = f"Hearing marked completed - {hearing.purpose}"
        audit_action = "hearing.completed"
    elif cancelled_transition:
        activity_event_type = "hearing_cancelled"
        activity_title = f"Hearing cancelled - {hearing.purpose}"
        audit_action = "hearing.cancelled"
    else:
        activity_event_type = "hearing_updated"
        activity_title = f"Hearing updated - {hearing.purpose}"
        audit_action = "hearing.updated"

    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type=activity_event_type,
        title=activity_title,
        detail=hearing.outcome_note or activity_title,
    )
    record_from_context(
        session,
        context,
        action=audit_action,
        target_type="hearing",
        target_id=hearing.id,
        matter_id=matter.id,
        metadata={
            "prior_status": prior_status,
            "status": hearing.status,
            "has_outcome_note": bool(hearing.outcome_note),
        },
    )
    session.commit()
    session.refresh(hearing)
    return _hearing_record(hearing)


_OPEN_HEARING_STATUSES = {
    MatterHearingStatus.SCHEDULED.value,
    MatterHearingStatus.ADJOURNED.value,
}
_CLOSED_HEARING_STATUSES = {
    MatterHearingStatus.COMPLETED.value,
    MatterHearingStatus.CANCELLED.value,
}


def _reconcile_next_hearing_after_closed_hearing(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    hearing: MatterHearing,
    prior_hearing_on: date | None,
) -> None:
    tracked_by_source = (
        matter.next_hearing_source_ref_type == "matter_hearing"
        and matter.next_hearing_source_ref_id == hearing.id
    )
    tracked_by_date = matter.next_hearing_on in {prior_hearing_on, hearing.hearing_on}
    if not tracked_by_source and not tracked_by_date:
        return

    replacement = session.scalar(
        select(MatterHearing)
        .where(
            MatterHearing.matter_id == matter.id,
            MatterHearing.id != hearing.id,
            MatterHearing.status.in_(tuple(_OPEN_HEARING_STATUSES)),
        )
        .order_by(MatterHearing.hearing_on.asc(), MatterHearing.created_at.asc())
        .limit(1)
    )
    if replacement is not None:
        apply_next_hearing_update(
            session,
            matter=matter,
            new_date=replacement.hearing_on,
            source="manual",
            actor_membership_id=context.membership.id,
            context=context,
            source_ref_type="matter_hearing",
            source_ref_id=replacement.id,
            reason="hearing_closed_recomputed",
            manual_lock=True,
            force=True,
        )
        return

    clear_next_hearing(
        session,
        matter=matter,
        source="manual",
        actor_membership_id=context.membership.id,
        context=context,
        source_ref_type="matter_hearing",
        source_ref_id=hearing.id,
        reason="hearing_closed_cleared",
        manual_lock=True,
    )


def _validated_order_attachment_id(
    session: Session,
    *,
    matter_id: str,
    attachment_id: str | None,
) -> str | None:
    if attachment_id is None:
        return None
    found = session.scalar(
        select(MatterAttachment.id).where(
            MatterAttachment.id == attachment_id,
            MatterAttachment.matter_id == matter_id,
        )
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Linked order attachment was not found on this matter.",
        )
    return found


def _validated_attachment_court_order_id(
    session: Session,
    *,
    matter_id: str,
    court_order_id: str | None,
) -> str | None:
    if court_order_id is None:
        return None
    found = session.scalar(
        select(MatterCourtOrder.id).where(
            MatterCourtOrder.id == court_order_id,
            MatterCourtOrder.matter_id == matter_id,
        )
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Linked court order was not found on this matter.",
        )
    return found


def _validated_attachment_hearing_id(
    session: Session,
    *,
    matter_id: str,
    hearing_id: str | None,
) -> str | None:
    """BUG-045: validate the chosen hearing belongs to this matter.

    Mirrors ``_validated_attachment_court_order_id`` so an out-of-tenant
    hearing id can't be smuggled into the FK and quietly persisted.
    """
    if hearing_id is None:
        return None
    found = session.scalar(
        select(MatterHearing.id).where(
            MatterHearing.id == hearing_id,
            MatterHearing.matter_id == matter_id,
        )
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Linked hearing was not found on this matter.",
        )
    return found


def _attachment_metadata_snapshot(attachment: MatterAttachment) -> dict[str, object]:
    return {
        "document_type": attachment.document_type,
        "lifecycle_stage": attachment.lifecycle_stage,
        "document_date": attachment.document_date,
        "sequence_index": attachment.sequence_index,
        "linked_court_order_id": attachment.linked_court_order_id,
        "hearing_id": attachment.hearing_id,
    }


def _order_metadata_snapshot(order: MatterCourtOrder) -> dict[str, object]:
    judge_names = order.judge_names_json
    return {
        "bench_name": order.bench_name,
        "judge_names": judge_names if isinstance(judge_names, list) else None,
        "order_attachment_id": order.order_attachment_id,
        "order_kind": order.order_kind,
        "is_interim_order": bool(order.is_interim_order),
        "stay_status": order.stay_status,
        "stay_effective_until": order.stay_effective_until,
    }


def create_matter_court_order(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterCourtOrderCreateRequest,
) -> MatterCourtOrderRecord:
    """BUG-032 (Hari 2026-05-09) — manual court-order create.

    The hearings page Orders-on-file card needs an explicit
    Add-order affordance. Court-sync was the only path that produced
    ``MatterCourtOrder`` rows before this; an order from a
    hand-uploaded PDF or scanned remarks summary could not exist
    without first running a sync (and a corresponding sync hit).

    Reuses the same access + audit + activity primitives as the
    PATCH path (`update_matter_court_order`). The optional file
    attachment is uploaded by the caller via the existing
    ``POST /api/matters/{id}/attachments`` route first; the resulting
    `attachment_id` is passed in here as `order_attachment_id` and
    is validated against the same matter (no cross-tenant linking).

    Notification side-effect: when an attachment is linked, this
    fires ``create_new_order_uploaded_notifications`` to keep parity
    with the upload-with-linked-court-order path. Without that call,
    a manually-created order with an attachment would silently skip
    the in-app notification rules other workspace members rely on.
    """

    matter = _get_matter_model(session, context=context, matter_id=matter_id)

    attachment_id = _validated_order_attachment_id(
        session,
        matter_id=matter.id,
        attachment_id=payload.order_attachment_id,
    )

    is_interim = bool(payload.is_interim_order)
    stay_status = payload.stay_status or MatterStayStatus.NONE

    order = MatterCourtOrder(
        matter_id=matter.id,
        sync_run_id=None,
        order_date=payload.order_date,
        title=payload.title.strip(),
        summary=payload.summary.strip(),
        order_text=payload.order_text,
        source=payload.source.strip() or "manual_upload",
        source_reference=payload.source_reference,
        bench_name=(
            payload.bench_name.strip() if payload.bench_name else None
        ),
        judge_names_json=payload.judge_names,
        order_attachment_id=attachment_id,
        order_kind=payload.order_kind,
        is_interim_order=is_interim,
        stay_status=stay_status,
        stay_effective_until=payload.stay_effective_until,
    )
    session.add(order)
    session.flush()

    # Mirror the matter-rollup updates that update_matter_court_order
    # applies on PATCH so the matter-summary badges show immediately.
    if is_interim:
        matter.has_interim_order = True
    if stay_status and stay_status != MatterStayStatus.NONE:
        matter.has_stay = True

    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="court_order_added",
        title="Court order added",
        detail=order.title,
    )
    record_from_context(
        session,
        context,
        action="matter_court_order.created",
        target_type="matter_court_order",
        target_id=order.id,
        matter_id=matter.id,
        metadata={
            "source": order.source,
            "order_kind": order.order_kind,
            "is_interim_order": order.is_interim_order,
            "stay_status": order.stay_status,
            "has_attachment": order.order_attachment_id is not None,
        },
    )

    if attachment_id is not None:
        # Reuse the existing notification helper so manual-create
        # parity matches the attachment-upload-with-linked-order
        # path. Without this call, downstream NotificationRule rows
        # would not fire on the new order. Imported lazily — same
        # pattern as `create_matter_attachment` uses.
        from caseops_api.services.notification_rules import (
            create_new_order_uploaded_notifications,
        )

        create_new_order_uploaded_notifications(
            session,
            context=context,
            matter=matter,
            attachment_id=attachment_id,
            linked_court_order_id=order.id,
        )

    try:
        from caseops_api.services.compliance_extraction import (
            run_compliance_extraction_for_order,
        )

        run_compliance_extraction_for_order(
            session,
            matter=matter,
            order=order,
            trigger="manual_order_create",
            actor_membership_id=context.membership.id,
            context=context,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("compliance extraction failed for court_order_id=%s: %s", order.id, exc)

    session.commit()
    session.refresh(order)
    return _court_order_record(order)


def update_matter_court_order(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    order_id: str,
    payload: MatterCourtOrderUpdateRequest,
) -> MatterCourtOrderRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    order = session.scalar(
        select(MatterCourtOrder).where(
            MatterCourtOrder.id == order_id,
            MatterCourtOrder.matter_id == matter.id,
        )
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Court order not found.",
        )

    before = _order_metadata_snapshot(order)
    updates = payload.model_dump(exclude_unset=True)
    if "bench_name" in updates:
        value = updates["bench_name"]
        order.bench_name = value.strip() if isinstance(value, str) else None
    if "judge_names" in updates:
        order.judge_names_json = updates["judge_names"]
    if "order_attachment_id" in updates:
        order.order_attachment_id = _validated_order_attachment_id(
            session,
            matter_id=matter.id,
            attachment_id=updates["order_attachment_id"],
        )
    if updates.get("order_kind") is not None:
        order.order_kind = updates["order_kind"]
    if updates.get("is_interim_order") is not None:
        order.is_interim_order = bool(updates["is_interim_order"])
    if updates.get("stay_status") is not None:
        order.stay_status = updates["stay_status"]
    if "stay_effective_until" in updates:
        order.stay_effective_until = updates["stay_effective_until"]

    after = _order_metadata_snapshot(order)
    if after != before:
        session.add(order)
        _append_activity(
            session,
            matter_id=matter.id,
            actor_membership_id=context.membership.id,
            event_type="court_order_updated",
            title="Court order metadata updated",
            detail=order.title,
        )
        record_from_context(
            session,
            context,
            action="matter_court_order.metadata.updated",
            target_type="matter_court_order",
            target_id=order.id,
            matter_id=matter.id,
            metadata={"before": before, "after": after},
        )
        stay_before = {
            "order_kind": before["order_kind"],
            "is_interim_order": before["is_interim_order"],
            "stay_status": before["stay_status"],
            "stay_effective_until": before["stay_effective_until"],
        }
        stay_after = {
            "order_kind": after["order_kind"],
            "is_interim_order": after["is_interim_order"],
            "stay_status": after["stay_status"],
            "stay_effective_until": after["stay_effective_until"],
        }
        if stay_after != stay_before:
            record_from_context(
                session,
                context,
                action="matter_court_order.stay.updated",
                target_type="matter_court_order",
                target_id=order.id,
                matter_id=matter.id,
                metadata={"before": stay_before, "after": stay_after},
            )
    session.commit()
    session.refresh(order)
    return _court_order_record(order)


def create_matter_hearing(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterHearingCreateRequest,
) -> MatterHearingRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    hearing = MatterHearing(
        matter_id=matter.id,
        hearing_on=payload.hearing_on,
        forum_name=payload.forum_name.strip(),
        judge_name=payload.judge_name.strip() if payload.judge_name else None,
        purpose=payload.purpose.strip(),
        status=payload.status,
        outcome_note=payload.outcome_note.strip() if payload.outcome_note else None,
    )
    session.add(hearing)
    session.add(matter)
    session.flush()
    if hearing.status not in _CLOSED_HEARING_STATUSES:
        apply_next_hearing_update(
            session,
            matter=matter,
            new_date=payload.hearing_on,
            source="manual",
            actor_membership_id=context.membership.id,
            context=context,
            source_ref_type="matter_hearing",
            source_ref_id=hearing.id,
            reason="hearing_created",
            manual_lock=True,
            force=True,
        )
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="hearing_added",
        title="Hearing scheduled",
        detail=f"{payload.forum_name.strip()} on {payload.hearing_on.isoformat()}",
    )
    # BUG-013 dark-launched reminders (2026-04-22) — persist the
    # reminder intent now so the worker can pick up the rows the
    # moment SendGrid credentials land. See
    # ``services/hearing_reminders.py`` and
    # ``memory/feedback_fix_vs_mitigation.md``. Scheduling failure
    # must not block the hearing create — the transaction proceeds
    # even if reminder persistence raises.
    if hearing.status not in _CLOSED_HEARING_STATUSES:
        try:
            from caseops_api.services.hearing_reminders import (
                schedule_reminders_for_hearing,
            )
            schedule_reminders_for_hearing(session, hearing=hearing)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hearing_reminders.schedule_reminders_for_hearing failed: %s",
                exc,
            )
    session.commit()
    session.refresh(hearing)
    return _hearing_record(hearing)


def _persist_court_sync_import(
    session: Session,
    *,
    matter: Matter,
    actor_membership_id: str | None,
    source: str,
    summary: str | None,
    cause_list_entries,
    orders,
) -> MatterCourtSyncRun:
    if not cause_list_entries and not orders:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one cause list entry or court order to import.",
        )

    sync_run = MatterCourtSyncRun(
        matter_id=matter.id,
        triggered_by_membership_id=actor_membership_id,
        source=source,
        summary=summary,
        imported_cause_list_count=len(cause_list_entries),
        imported_order_count=len(orders),
    )
    session.add(sync_run)
    session.flush()

    new_listing_ids: list[str] = []
    for item in cause_list_entries:
        new_entry = MatterCauseListEntry(
            matter_id=matter.id,
            sync_run_id=sync_run.id,
            listing_date=item.listing_date,
            forum_name=item.forum_name.strip(),
            bench_name=item.bench_name.strip() if item.bench_name else None,
            courtroom=item.courtroom.strip() if item.courtroom else None,
            item_number=item.item_number.strip() if item.item_number else None,
            stage=item.stage.strip() if item.stage else None,
            notes=item.notes.strip() if item.notes else None,
            source=source,
            source_reference=item.source_reference.strip() if item.source_reference else None,
        )
        session.add(new_entry)
        session.flush()
        new_listing_ids.append(new_entry.id)

    new_orders: list[MatterCourtOrder] = []
    for item in orders:
        order_attachment_id = _validated_order_attachment_id(
            session,
            matter_id=matter.id,
            attachment_id=item.order_attachment_id,
        )
        title = item.title.strip()
        source_reference = item.source_reference.strip() if item.source_reference else None
        order_text = item.order_text.strip() if item.order_text else None
        order = _find_existing_imported_order(
            session,
            matter_id=matter.id,
            source=source,
            source_reference=source_reference,
            order_date=item.order_date,
            title=title,
            order_text=order_text,
        )
        if order is None:
            order = MatterCourtOrder(
                matter_id=matter.id,
                sync_run_id=sync_run.id,
                order_date=item.order_date,
                title=title,
                summary=item.summary.strip(),
                order_text=order_text,
                source=source,
                source_reference=source_reference,
                bench_name=item.bench_name.strip() if item.bench_name else None,
                judge_names_json=item.judge_names,
                order_attachment_id=order_attachment_id,
                order_kind=item.order_kind,
                is_interim_order=item.is_interim_order,
                stay_status=item.stay_status,
                stay_effective_until=item.stay_effective_until,
            )
        else:
            order.sync_run_id = sync_run.id
            order.summary = item.summary.strip()
            order.order_text = order_text
            order.bench_name = item.bench_name.strip() if item.bench_name else None
            order.judge_names_json = item.judge_names
            order.order_attachment_id = order_attachment_id
            order.order_kind = item.order_kind
            order.is_interim_order = item.is_interim_order
            order.stay_status = item.stay_status
            order.stay_effective_until = item.stay_effective_until
            order.synced_at = utcnow()
        session.add(order)
        session.flush()
        new_orders.append(order)

    if cause_list_entries:
        next_listing = min(cause_list_entries, key=lambda entry: entry.listing_date)
        apply_next_hearing_update(
            session,
            matter=matter,
            new_date=next_listing.listing_date,
            source="cause_list",
            actor_membership_id=actor_membership_id,
            source_ref_type="matter_court_sync_run",
            source_ref_id=sync_run.id,
            reason="court_sync_import",
            confidence_label="high",
        )
        matter.court_name = next_listing.forum_name.strip()
        if next_listing.bench_name:
            matter.judge_name = next_listing.bench_name.strip()

    session.add(matter)
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=actor_membership_id,
        event_type="court_sync_imported",
        title="Court sync imported",
        detail=(
            f"{source} imported {len(cause_list_entries)} cause list item(s) and "
            f"{len(orders)} order(s)."
        ),
    )
    session.add(sync_run)

    # MOD-TS-018 (2026-04-26 PM): resolve the bench inline for each
    # newly-imported listing so /matters/{id}/bench-strategy can
    # surface L-B aggregates immediately. Without this, judges_json
    # stays NULL until the periodic resolve_cause_list_benches.py
    # job runs (next scheduled wake) and the bench-strategy panel
    # shows "insufficient" even though the data is in L-B.
    # Failures are logged + tolerated — the periodic job will retry.
    if new_listing_ids:
        from caseops_api.services.bench_resolver import resolve_listing_bench

        for listing_id in new_listing_ids:
            try:
                resolve_listing_bench(session, listing_id=listing_id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "bench_resolver: failed for listing_id=%s; "
                    "leaving judges_json NULL for periodic retry",
                    listing_id,
                )

    if new_orders:
        from caseops_api.services.compliance_extraction import (
            run_compliance_extraction_for_order,
        )
        from caseops_api.services.proceeding_intelligence import (
            extract_imported_order_proceeding_intelligence,
        )

        for order in new_orders:
            try:
                extract_imported_order_proceeding_intelligence(
                    session,
                    matter=matter,
                    order=order,
                    actor_membership_id=actor_membership_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "proceeding_intelligence: failed for court_order_id=%s: %s",
                    order.id,
                    exc,
                )
            try:
                run_compliance_extraction_for_order(
                    session,
                    matter=matter,
                    order=order,
                    trigger="court_sync",
                    actor_membership_id=actor_membership_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "compliance_extraction: failed for court_order_id=%s: %s",
                    order.id,
                    exc,
                )

    return sync_run


def create_matter_court_sync_import(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterCourtSyncImportRequest,
) -> MatterCourtSyncRunRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    sync_run = _persist_court_sync_import(
        session,
        matter=matter,
        actor_membership_id=context.membership.id,
        source=payload.source.strip(),
        summary=payload.summary.strip() if payload.summary else None,
        cause_list_entries=payload.cause_list_entries,
        orders=payload.orders,
    )
    session.commit()

    refreshed_run = session.scalar(
        select(MatterCourtSyncRun)
        .options(
            joinedload(MatterCourtSyncRun.triggered_by_membership).joinedload(
                CompanyMembership.user
            )
        )
        .where(MatterCourtSyncRun.id == sync_run.id)
    )
    assert refreshed_run is not None
    return _court_sync_run_record(refreshed_run)


def create_matter_attachment(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
    document_type: str | None = None,
    lifecycle_stage: str | None = None,
    document_date: date | None = None,
    sequence_index: int | None = None,
    linked_court_order_id: str | None = None,
    hearing_id: str | None = None,
) -> tuple[MatterAttachmentRecord, str]:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    audit_matter_id = matter.id
    linked_court_order_id = _validated_attachment_court_order_id(
        session,
        matter_id=matter.id,
        court_order_id=linked_court_order_id,
    )
    hearing_id = _validated_attachment_hearing_id(
        session,
        matter_id=matter.id,
        hearing_id=hearing_id,
    )
    sequence_index = _validated_sequence_index(sequence_index)
    lifecycle_stage = lifecycle_stage or _default_lifecycle_stage(document_type)
    # §6.3: refuse obviously-wrong uploads before they touch disk.
    # Checks extension whitelist, content-type coherence, and magic
    # bytes; leaves the stream cursor at 0 on success.
    from caseops_api.services.file_security import verify_upload

    verify_upload(filename=filename, content_type=content_type, stream=stream)
    attachment = MatterAttachment(
        matter_id=matter.id,
        uploaded_by_membership_id=context.membership.id,
        original_filename=sanitize_filename(filename),
        storage_key="pending",
        content_type=content_type,
        size_bytes=0,
        sha256_hex="0" * 64,
        document_type=document_type,
        lifecycle_stage=lifecycle_stage,
        document_date=document_date,
        sequence_index=sequence_index,
        linked_court_order_id=linked_court_order_id,
        hearing_id=hearing_id,
    )
    session.add(attachment)
    session.flush()

    try:
        stored = persist_matter_attachment(
            company_id=context.company.id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            filename=filename,
            stream=stream,
            before_store=lambda size_bytes: assert_storage_quota_allows_upload(
                session,
                company_id=context.company.id,
                matter_id=matter.id,
                incoming_size_bytes=size_bytes,
            ),
        )
        # §9.3: ClamAV scan on the persisted bytes. Skipped when
        # CASEOPS_CLAMAV_HOST is unset; raises 400 on infection.
        from caseops_api.services.document_storage import (
            delete_stored_document,
            resolve_storage_path,
        )
        from caseops_api.services.virus_scan import reject_if_infected

        try:
            reject_if_infected(
                resolve_storage_path(stored.storage_key),
                filename=filename,
            )
        except Exception:
            try:
                delete_stored_document(stored.storage_key)
            except Exception:
                # Best-effort cleanup; preserve the original scan failure.
                pass
            raise
        attachment.storage_key = stored.storage_key
        attachment.size_bytes = stored.size_bytes
        attachment.sha256_hex = stored.sha256_hex
        job = enqueue_processing_job(
            session,
            company_id=context.company.id,
            requested_by_membership_id=context.membership.id,
            target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
            attachment_id=attachment.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        session.add(attachment)
        _append_activity(
            session,
            matter_id=matter.id,
            actor_membership_id=context.membership.id,
            event_type="attachment_added",
            title="Document uploaded",
            detail=(
                f"{attachment.original_filename} uploaded to the matter workspace "
                "and queued for processing."
            ),
        )
        if linked_court_order_id:
            from caseops_api.services.notification_rules import (
                create_new_order_uploaded_notifications,
            )

            create_new_order_uploaded_notifications(
                session,
                context=context,
                matter=matter,
                attachment_id=attachment.id,
                linked_court_order_id=linked_court_order_id,
            )
        if linked_court_order_id or document_type == "order_judgment":
            try:
                from caseops_api.services.compliance_extraction import (
                    run_compliance_extraction_for_attachment,
                )

                run_compliance_extraction_for_attachment(
                    session,
                    matter=matter,
                    attachment=attachment,
                    trigger="attachment_processed",
                    actor_membership_id=context.membership.id,
                    context=context,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "compliance extraction pending run failed for attachment_id=%s: %s",
                    attachment.id,
                    exc,
                )
        session.commit()
    except StorageQuotaExceeded as exc:
        session.rollback()
        record_storage_quota_blocked_upload(
            session,
            context=context,
            matter_id=audit_matter_id,
            error=exc,
        )
        raise exc.to_http_exception() from exc
    except Exception:
        session.rollback()
        raise

    refreshed_attachment = session.scalar(
        select(MatterAttachment)
        .options(
            joinedload(MatterAttachment.uploaded_by_membership).joinedload(CompanyMembership.user)
        )
        .where(MatterAttachment.id == attachment.id)
    )
    assert refreshed_attachment is not None
    latest_jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
        attachment_ids=[refreshed_attachment.id],
    )
    return (
        _attachment_record(
            refreshed_attachment,
            latest_job=latest_jobs.get(refreshed_attachment.id),
        ),
        job.id,
    )


def update_matter_attachment_metadata(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    payload: MatterAttachmentMetadataUpdateRequest,
) -> MatterAttachmentRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    attachment = session.scalar(
        select(MatterAttachment)
        .options(
            joinedload(MatterAttachment.uploaded_by_membership).joinedload(
                CompanyMembership.user
            ),
            joinedload(MatterAttachment.linked_court_order),
        )
        .where(
            MatterAttachment.id == attachment_id,
            MatterAttachment.matter_id == matter.id,
        )
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")

    before = _attachment_metadata_snapshot(attachment)
    updates = payload.model_dump(exclude_unset=True)
    if "document_type" in updates:
        attachment.document_type = updates["document_type"]
        if "lifecycle_stage" not in updates:
            attachment.lifecycle_stage = _default_lifecycle_stage(attachment.document_type)
    if "lifecycle_stage" in updates:
        attachment.lifecycle_stage = updates["lifecycle_stage"]
    if "document_date" in updates:
        attachment.document_date = updates["document_date"]
    if "sequence_index" in updates:
        attachment.sequence_index = _validated_sequence_index(updates["sequence_index"])
    if "linked_court_order_id" in updates:
        attachment.linked_court_order_id = _validated_attachment_court_order_id(
            session,
            matter_id=matter.id,
            court_order_id=updates["linked_court_order_id"],
        )
    if "hearing_id" in updates:
        attachment.hearing_id = _validated_attachment_hearing_id(
            session,
            matter_id=matter.id,
            hearing_id=updates["hearing_id"],
        )

    after = _attachment_metadata_snapshot(attachment)
    if before != after:
        session.add(attachment)
        _append_activity(
            session,
            matter_id=matter.id,
            actor_membership_id=context.membership.id,
            event_type="attachment_metadata_updated",
            title="Document metadata updated",
            detail=attachment.original_filename,
        )
        record_from_context(
            session,
            context,
            action="matter_attachment.metadata.updated",
            target_type="matter_attachment",
            target_id=attachment.id,
            matter_id=matter.id,
            metadata={
                "before": before,
                "after": after,
                "matter_code": matter.matter_code,
                "filename": attachment.original_filename,
            },
        )
        if attachment.linked_court_order_id or attachment.document_type == "order_judgment":
            try:
                from caseops_api.services.compliance_extraction import (
                    run_compliance_extraction_for_attachment,
                )

                run_compliance_extraction_for_attachment(
                    session,
                    matter=matter,
                    attachment=attachment,
                    trigger="manual_retry",
                    actor_membership_id=context.membership.id,
                    context=context,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "compliance extraction failed for attachment_id=%s: %s",
                    attachment.id,
                    exc,
                )
    session.commit()
    session.refresh(attachment)
    latest_jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
        attachment_ids=[attachment.id],
    )
    return _attachment_record(attachment, latest_job=latest_jobs.get(attachment.id))


def request_matter_attachment_processing(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    action: str,
) -> tuple[MatterAttachmentRecord, str]:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        _raise_processing_permission_error()

    attachment = _get_matter_attachment_model(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
    )
    job = enqueue_processing_job(
        session,
        company_id=context.company.id,
        requested_by_membership_id=context.membership.id,
        target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
        attachment_id=attachment.id,
        action=action,
    )
    session.add(attachment)
    _append_activity(
        session,
        matter_id=attachment.matter_id,
        actor_membership_id=context.membership.id,
        event_type=(
            "attachment_retry_requested"
            if action == DocumentProcessingAction.RETRY
            else "attachment_reindex_requested"
        ),
        title=(
            "Attachment retry requested"
            if action == DocumentProcessingAction.RETRY
            else "Attachment reindex requested"
        ),
        detail=f"{attachment.original_filename} queued for {action.replace('_', ' ')}.",
    )
    session.commit()
    refreshed_attachment = _get_matter_attachment_model(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment.id,
    )
    latest_jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
        attachment_ids=[refreshed_attachment.id],
    )
    return (
        _attachment_record(
            refreshed_attachment,
            latest_job=latest_jobs.get(refreshed_attachment.id),
        ),
        job.id,
    )


def get_matter_attachment_download(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
) -> tuple[MatterAttachment, str]:
    attachment = session.scalar(
        select(MatterAttachment)
        .options(
            joinedload(MatterAttachment.uploaded_by_membership).joinedload(CompanyMembership.user)
        )
        .join(Matter, Matter.id == MatterAttachment.matter_id)
        .where(
            MatterAttachment.id == attachment_id,
            MatterAttachment.matter_id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")

    storage_path = resolve_storage_path(attachment.storage_key)
    if not storage_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment file is no longer available.",
        )
    return attachment, str(storage_path)


def create_time_entry(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: TimeEntryCreateRequest,
) -> TimeEntryRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    rate_currency = payload.rate_currency.strip().upper()
    rate_amount_minor = payload.rate_amount_minor
    billing_rate_id: str | None = None
    rate_source: str | None = "manual" if rate_amount_minor is not None else None
    if rate_amount_minor is None and payload.billable:
        resolved_rate = resolve_time_entry_rate(
            session,
            matter=matter,
            membership_id=context.membership.id,
            role=str(context.membership.role),
            work_date=payload.work_date,
            requested_currency=rate_currency,
        )
        rate_amount_minor = resolved_rate.rate_amount_minor
        rate_currency = resolved_rate.currency
        billing_rate_id = resolved_rate.rate_id
        rate_source = resolved_rate.source
    total_amount_minor = _calculate_time_entry_total(
        duration_minutes=payload.duration_minutes,
        rate_amount_minor=rate_amount_minor,
        billable=payload.billable,
    )
    time_entry = MatterTimeEntry(
        matter_id=matter.id,
        author_membership_id=context.membership.id,
        work_date=payload.work_date,
        description=payload.description.strip(),
        duration_minutes=payload.duration_minutes,
        billable=payload.billable,
        rate_currency=rate_currency,
        rate_amount_minor=rate_amount_minor,
        billing_rate_id=billing_rate_id,
        rate_source=rate_source,
        total_amount_minor=total_amount_minor,
    )
    session.add(time_entry)
    session.flush()
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="time_entry_added",
        title="Time entry logged",
        detail=f"{payload.duration_minutes} minutes recorded for billing.",
    )
    session.commit()
    refreshed_time_entry = session.scalar(
        select(MatterTimeEntry)
        .options(
            joinedload(MatterTimeEntry.author_membership).joinedload(CompanyMembership.user),
            selectinload(MatterTimeEntry.invoice_line_item),
        )
        .where(MatterTimeEntry.id == time_entry.id)
    )
    assert refreshed_time_entry is not None
    return _time_entry_record(refreshed_time_entry)


def create_matter_invoice(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: InvoiceCreateRequest,
) -> InvoiceRecord:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        _raise_billing_permission_error()

    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    billing_profile = None
    if matter.billing_profile_id:
        billing_profile = session.scalar(
            select(MatterBillingProfile).where(
                MatterBillingProfile.id == matter.billing_profile_id,
                MatterBillingProfile.company_id == context.company.id,
            )
        )
    if billing_profile is None:
        billing_profile = session.scalar(
            select(MatterBillingProfile)
            .where(
                MatterBillingProfile.company_id == context.company.id,
                MatterBillingProfile.is_default.is_(True),
            )
            .order_by(MatterBillingProfile.updated_at.desc())
            .limit(1)
        )
    invoice_number = (
        payload.invoice_number.strip()
        if payload.invoice_number
        else next_invoice_number(billing_profile)
    )
    existing_invoice = session.scalar(
        select(MatterInvoice).where(
            MatterInvoice.company_id == context.company.id,
            MatterInvoice.invoice_number == invoice_number,
        )
    )
    if existing_invoice:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An invoice with this number already exists for the current company.",
        )

    selected_time_entries: list[MatterTimeEntry] = []
    if payload.include_uninvoiced_time_entries:
        selected_time_entries = list(
            session.scalars(
                select(MatterTimeEntry)
                .options(selectinload(MatterTimeEntry.invoice_line_item))
                .where(MatterTimeEntry.matter_id == matter.id)
                .order_by(MatterTimeEntry.work_date.asc(), MatterTimeEntry.created_at.asc())
            )
        )
        selected_time_entries = [
            time_entry
            for time_entry in selected_time_entries
            if time_entry.billable and time_entry.invoice_line_item is None
        ]

    if not selected_time_entries and not payload.manual_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Add billable uninvoiced time entries or manual items before creating "
                "an invoice."
            ),
        )

    invoice = MatterInvoice(
        company_id=context.company.id,
        matter_id=matter.id,
        issued_by_membership_id=context.membership.id,
        billing_profile_id=billing_profile.id if billing_profile else None,
        invoice_number=invoice_number,
        client_name=(payload.client_name.strip() if payload.client_name else matter.client_name),
        client_billing_name=(
            payload.client_billing_name.strip()
            if payload.client_billing_name
            else (payload.client_name.strip() if payload.client_name else matter.client_name)
        ),
        client_billing_address=payload.client_billing_address,
        client_gstin=payload.client_gstin,
        place_of_supply=(
            payload.place_of_supply
            or (billing_profile.default_place_of_supply if billing_profile else None)
        ),
        sac_hsn=payload.sac_hsn or (billing_profile.default_sac_hsn if billing_profile else None),
        firm_legal_name=billing_profile.firm_legal_name if billing_profile else None,
        firm_address=billing_profile.firm_address if billing_profile else None,
        firm_gstin=billing_profile.firm_gstin if billing_profile else None,
        firm_pan=billing_profile.firm_pan if billing_profile else None,
        status=payload.status,
        currency=billing_profile.currency if billing_profile else "INR",
        issued_on=payload.issued_on,
        due_on=payload.due_on or default_invoice_due_on(billing_profile, payload.issued_on),
        notes=(
            payload.notes.strip()
            if payload.notes
            else (billing_profile.notes_template if billing_profile else None)
        ),
        tds_deducted_minor=payload.tds_deducted_minor,
        payment_adjustment_minor=payload.payment_adjustment_minor,
    )
    session.add(invoice)
    session.flush()

    subtotal_amount_minor = 0
    for time_entry in selected_time_entries:
        line_item = MatterInvoiceLineItem(
            invoice_id=invoice.id,
            time_entry_id=time_entry.id,
            description=time_entry.description,
            category="time",
            sac_hsn=invoice.sac_hsn,
            duration_minutes=time_entry.duration_minutes,
            unit_rate_amount_minor=time_entry.rate_amount_minor,
            line_total_amount_minor=time_entry.total_amount_minor,
        )
        subtotal_amount_minor += time_entry.total_amount_minor
        session.add(line_item)

    for manual_item in payload.manual_items:
        line_item = MatterInvoiceLineItem(
            invoice_id=invoice.id,
            description=manual_item.description.strip(),
            category=manual_item.category,
            sac_hsn=manual_item.sac_hsn or invoice.sac_hsn,
            duration_minutes=None,
            unit_rate_amount_minor=None,
            line_total_amount_minor=manual_item.amount_minor,
        )
        subtotal_amount_minor += manual_item.amount_minor
        session.add(line_item)

    if billing_profile is None and payload.tax_amount_minor:
        taxable_value_minor = subtotal_amount_minor
        tax_amount_minor = payload.tax_amount_minor
        total_amount_minor = subtotal_amount_minor + tax_amount_minor
        balance_due_minor = (
            total_amount_minor - payload.tds_deducted_minor - payload.payment_adjustment_minor
        )
        cgst_amount_minor = 0
        sgst_amount_minor = 0
        igst_amount_minor = tax_amount_minor
    else:
        tax = calculate_invoice_tax(
            profile=billing_profile,
            taxable_value_minor=subtotal_amount_minor,
            client_gstin=invoice.client_gstin,
            amount_received_minor=0,
            tds_deducted_minor=payload.tds_deducted_minor,
            payment_adjustment_minor=payload.payment_adjustment_minor,
        )
        taxable_value_minor = tax.taxable_value_minor
        tax_amount_minor = tax.tax_amount_minor
        total_amount_minor = tax.total_amount_minor
        balance_due_minor = tax.balance_due_minor
        cgst_amount_minor = tax.cgst_amount_minor
        sgst_amount_minor = tax.sgst_amount_minor
        igst_amount_minor = tax.igst_amount_minor
    invoice.subtotal_amount_minor = subtotal_amount_minor
    invoice.taxable_value_minor = taxable_value_minor
    invoice.cgst_amount_minor = cgst_amount_minor
    invoice.sgst_amount_minor = sgst_amount_minor
    invoice.igst_amount_minor = igst_amount_minor
    invoice.tax_amount_minor = tax_amount_minor
    invoice.total_amount_minor = total_amount_minor
    invoice.amount_received_minor = 0
    invoice.balance_due_minor = balance_due_minor
    session.add(invoice)
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="invoice_created",
        title="Invoice created",
        detail=(
            f"{invoice.invoice_number} created with total "
            f"{invoice.total_amount_minor} minor units."
        ),
    )
    record_from_context(
        session,
        context,
        action="matter_invoice.created",
        target_type="matter_invoice",
        target_id=invoice.id,
        matter_id=matter.id,
        metadata={
            "invoice_number": invoice.invoice_number,
            "billing_profile_id": invoice.billing_profile_id,
            "taxable_value_minor": invoice.taxable_value_minor,
            "cgst_amount_minor": invoice.cgst_amount_minor,
            "sgst_amount_minor": invoice.sgst_amount_minor,
            "igst_amount_minor": invoice.igst_amount_minor,
            "tds_deducted_minor": invoice.tds_deducted_minor,
            "payment_adjustment_minor": invoice.payment_adjustment_minor,
            "line_count": len(selected_time_entries) + len(payload.manual_items),
        },
    )
    session.commit()
    refreshed_invoice = session.scalar(
        select(MatterInvoice)
        .options(
            joinedload(MatterInvoice.issued_by_membership).joinedload(CompanyMembership.user),
            selectinload(MatterInvoice.line_items),
        )
        .where(MatterInvoice.id == invoice.id)
    )
    assert refreshed_invoice is not None
    return _invoice_record(refreshed_invoice)


def get_matter_invoice_pdf(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    invoice_id: str,
) -> tuple[bytes, str, str]:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        _raise_billing_permission_error()
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    invoice = session.scalar(
        select(MatterInvoice)
        .options(
            joinedload(MatterInvoice.matter),
            selectinload(MatterInvoice.line_items),
        )
        .where(
            MatterInvoice.id == invoice_id,
            MatterInvoice.matter_id == matter.id,
            MatterInvoice.company_id == context.company.id,
        )
    )
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    return render_invoice_pdf(session, context=context, invoice=invoice)
