from __future__ import annotations

from datetime import date, datetime
from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    CompanyMembership,
    DocumentProcessingAction,
    DocumentProcessingTargetType,
    Matter,
    MatterActivity,
    MatterAttachment,
    MatterCauseListEntry,
    MatterCourtOrder,
    MatterCourtSyncJob,
    MatterCourtSyncRun,
    MatterHearing,
    MatterInvoice,
    MatterInvoiceLineItem,
    MatterInvoicePaymentAttempt,
    MatterNote,
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
from caseops_api.schemas.matters import (
    MatterActivityRecord,
    MatterAttachmentRecord,
    MatterCauseListEntryRecord,
    MatterCourtOrderRecord,
    MatterCourtSyncImportRequest,
    MatterCourtSyncJobRecord,
    MatterCourtSyncRunRecord,
    MatterCreateRequest,
    MatterHearingCreateRequest,
    MatterHearingRecord,
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
from caseops_api.services.identity import SessionContext


def _matter_record(matter: Matter) -> MatterRecord:
    return MatterRecord.model_validate(matter)


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
    )


def _court_order_record(order: MatterCourtOrder) -> MatterCourtOrderRecord:
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
        status=invoice.status,
        currency=invoice.currency,
        subtotal_amount_minor=invoice.subtotal_amount_minor,
        tax_amount_minor=invoice.tax_amount_minor,
        total_amount_minor=invoice.total_amount_minor,
        amount_received_minor=invoice.amount_received_minor,
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
    return matter


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

    matter = Matter(
        company_id=context.company.id,
        title=payload.title.strip(),
        matter_code=payload.matter_code.strip(),
        client_name=payload.client_name.strip() if payload.client_name else None,
        opposing_party=payload.opposing_party.strip() if payload.opposing_party else None,
        status=payload.status,
        practice_area=payload.practice_area.strip(),
        forum_level=payload.forum_level,
        court_name=payload.court_name.strip() if payload.court_name else None,
        judge_name=payload.judge_name.strip() if payload.judge_name else None,
        description=payload.description.strip() if payload.description else None,
        next_hearing_on=payload.next_hearing_on,
    )
    session.add(matter)
    session.flush()
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="matter_created",
        title="Matter created",
        detail=f"{matter.matter_code} created as {matter.status}.",
    )
    session.commit()
    session.refresh(matter)
    return _matter_record(matter)


def list_matters(session: Session, *, context: SessionContext) -> MatterListResponse:
    matters = list(
        session.scalars(
            select(Matter)
            .where(Matter.company_id == context.company.id)
            .order_by(Matter.updated_at.desc())
        )
    )
    return MatterListResponse(
        company_id=context.company.id,
        matters=[_matter_record(matter) for matter in matters],
    )


def get_matter(session: Session, *, context: SessionContext, matter_id: str) -> MatterRecord:
    return _matter_record(_get_matter_model(session, context=context, matter_id=matter_id))


def update_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterUpdateRequest,
) -> MatterRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)

    updates = payload.model_dump(exclude_unset=True)
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
    for field_name, value in updates.items():
        setattr(matter, field_name, value)

    session.add(matter)
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="matter_updated",
        title="Matter updated",
        detail=f"Status is now {matter.status}.",
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
            task.owner_membership_id = owner.id

    previous_status = task.status
    for field_name, value in updates.items():
        setattr(task, field_name, value)
    if task.status == MatterTaskStatus.COMPLETED:
        task.completed_at = task.completed_at or utcnow()
    elif previous_status == MatterTaskStatus.COMPLETED:
        task.completed_at = None

    session.add(task)
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
    matter.next_hearing_on = payload.hearing_on
    session.add(hearing)
    session.add(matter)
    session.flush()
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="hearing_added",
        title="Hearing scheduled",
        detail=f"{payload.forum_name.strip()} on {payload.hearing_on.isoformat()}",
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

    for item in cause_list_entries:
        session.add(
            MatterCauseListEntry(
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
        )

    for item in orders:
        session.add(
            MatterCourtOrder(
                matter_id=matter.id,
                sync_run_id=sync_run.id,
                order_date=item.order_date,
                title=item.title.strip(),
                summary=item.summary.strip(),
                order_text=item.order_text.strip() if item.order_text else None,
                source=source,
                source_reference=item.source_reference.strip() if item.source_reference else None,
            )
        )

    if cause_list_entries:
        next_listing = min(cause_list_entries, key=lambda entry: entry.listing_date)
        matter.next_hearing_on = next_listing.listing_date
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
) -> tuple[MatterAttachmentRecord, str]:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    attachment = MatterAttachment(
        matter_id=matter.id,
        uploaded_by_membership_id=context.membership.id,
        original_filename=sanitize_filename(filename),
        storage_key="pending",
        content_type=content_type,
        size_bytes=0,
        sha256_hex="0" * 64,
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
        )
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
        session.commit()
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
    total_amount_minor = _calculate_time_entry_total(
        duration_minutes=payload.duration_minutes,
        rate_amount_minor=payload.rate_amount_minor,
        billable=payload.billable,
    )
    time_entry = MatterTimeEntry(
        matter_id=matter.id,
        author_membership_id=context.membership.id,
        work_date=payload.work_date,
        description=payload.description.strip(),
        duration_minutes=payload.duration_minutes,
        billable=payload.billable,
        rate_currency=payload.rate_currency.strip().upper(),
        rate_amount_minor=payload.rate_amount_minor,
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
    invoice_number = payload.invoice_number.strip()
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
        invoice_number=invoice_number,
        client_name=(payload.client_name.strip() if payload.client_name else matter.client_name),
        status=payload.status,
        currency="INR",
        issued_on=payload.issued_on,
        due_on=payload.due_on,
        notes=payload.notes.strip() if payload.notes else None,
    )
    session.add(invoice)
    session.flush()

    subtotal_amount_minor = 0
    for time_entry in selected_time_entries:
        line_item = MatterInvoiceLineItem(
            invoice_id=invoice.id,
            time_entry_id=time_entry.id,
            description=time_entry.description,
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
            duration_minutes=None,
            unit_rate_amount_minor=None,
            line_total_amount_minor=manual_item.amount_minor,
        )
        subtotal_amount_minor += manual_item.amount_minor
        session.add(line_item)

    total_amount_minor = subtotal_amount_minor + payload.tax_amount_minor
    invoice.subtotal_amount_minor = subtotal_amount_minor
    invoice.tax_amount_minor = payload.tax_amount_minor
    invoice.total_amount_minor = total_amount_minor
    invoice.amount_received_minor = 0
    invoice.balance_due_minor = total_amount_minor
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
