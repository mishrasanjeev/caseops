from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    CompanyMembership,
    ContractActivity,
    ContractAttachment,
    DocumentProcessingAction,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingStatus,
    DocumentProcessingTargetType,
    MatterActivity,
    MatterAttachment,
    utcnow,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.document_processing import DocumentProcessingJobRecord
from caseops_api.services.document_processing import (
    index_contract_attachment,
    index_matter_attachment,
)


def _job_record(job: DocumentProcessingJob) -> DocumentProcessingJobRecord:
    return DocumentProcessingJobRecord(
        id=job.id,
        company_id=job.company_id,
        requested_by_membership_id=job.requested_by_membership_id,
        requested_by_name=(
            job.requested_by_membership.user.full_name
            if job.requested_by_membership and job.requested_by_membership.user
            else None
        ),
        target_type=job.target_type,
        attachment_id=job.attachment_id,
        action=job.action,
        status=job.status,
        attempt_count=job.attempt_count,
        processed_char_count=job.processed_char_count,
        error_message=job.error_message,
        queued_at=job.queued_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        updated_at=job.updated_at,
    )


def load_latest_processing_jobs(
    session: Session,
    *,
    target_type: str,
    attachment_ids: list[str],
) -> dict[str, DocumentProcessingJobRecord]:
    if not attachment_ids:
        return {}

    jobs = list(
        session.scalars(
            select(DocumentProcessingJob)
            .options(
                joinedload(DocumentProcessingJob.requested_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(
                DocumentProcessingJob.target_type == target_type,
                DocumentProcessingJob.attachment_id.in_(attachment_ids),
            )
            .order_by(
                DocumentProcessingJob.queued_at.desc(),
                DocumentProcessingJob.updated_at.desc(),
            )
        )
    )

    latest_by_attachment: dict[str, DocumentProcessingJobRecord] = {}
    for job in jobs:
        if job.attachment_id not in latest_by_attachment:
            latest_by_attachment[job.attachment_id] = _job_record(job)
    return latest_by_attachment


def enqueue_processing_job(
    session: Session,
    *,
    company_id: str,
    requested_by_membership_id: str | None,
    target_type: str,
    attachment_id: str,
    action: str,
) -> DocumentProcessingJob:
    job = DocumentProcessingJob(
        company_id=company_id,
        requested_by_membership_id=requested_by_membership_id,
        target_type=target_type,
        attachment_id=attachment_id,
        action=action,
        status=DocumentProcessingJobStatus.QUEUED,
    )
    session.add(job)
    session.flush()
    return job


def drain_document_processing_jobs(*, limit: int) -> int:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job_ids = list(
            session.scalars(
                select(DocumentProcessingJob.id)
                .where(DocumentProcessingJob.status == DocumentProcessingJobStatus.QUEUED)
                .order_by(
                    DocumentProcessingJob.queued_at.asc(),
                    DocumentProcessingJob.updated_at.asc(),
                )
                .limit(limit)
            )
        )
    finally:
        session.close()

    processed = 0
    for job_id in job_ids:
        before = load_processing_job(job_id)
        if before and before.status == DocumentProcessingJobStatus.QUEUED:
            run_document_processing_job(job_id)
            processed += 1
    return processed


def recover_stale_document_processing_jobs(*, stale_after_minutes: int) -> int:
    cutoff = utcnow() - timedelta(minutes=stale_after_minutes)
    session_factory = get_session_factory()
    session = session_factory()
    try:
        jobs = list(
            session.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.status == DocumentProcessingJobStatus.PROCESSING,
                    DocumentProcessingJob.started_at.is_not(None),
                    DocumentProcessingJob.started_at <= cutoff,
                )
            )
        )
        if not jobs:
            return 0

        for job in jobs:
            job.status = DocumentProcessingJobStatus.QUEUED
            job.error_message = "Recovered stale processing job for retry."
            job.started_at = None
            job.completed_at = None
            session.add(job)
        session.commit()
        return len(jobs)
    finally:
        session.close()


def enqueue_scheduled_document_reprocessing(
    *,
    limit: int,
    retry_after_hours: int,
    reindex_after_hours: int,
) -> int:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        queued = 0
        retry_cutoff = utcnow() - timedelta(hours=retry_after_hours)
        reindex_cutoff = utcnow() - timedelta(hours=reindex_after_hours)

        if retry_after_hours >= 0 and queued < limit:
            queued += _enqueue_attachment_reprocessing_candidates(
                session,
                target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
                attachment_model=MatterAttachment,
                candidate_statuses=[
                    DocumentProcessingStatus.NEEDS_OCR,
                    DocumentProcessingStatus.FAILED,
                ],
                action=DocumentProcessingAction.RETRY,
                processed_before=retry_cutoff,
                limit=limit - queued,
            )
        if retry_after_hours >= 0 and queued < limit:
            queued += _enqueue_attachment_reprocessing_candidates(
                session,
                target_type=DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
                attachment_model=ContractAttachment,
                candidate_statuses=[
                    DocumentProcessingStatus.NEEDS_OCR,
                    DocumentProcessingStatus.FAILED,
                ],
                action=DocumentProcessingAction.RETRY,
                processed_before=retry_cutoff,
                limit=limit - queued,
            )
        if reindex_after_hours >= 0 and queued < limit:
            queued += _enqueue_attachment_reprocessing_candidates(
                session,
                target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
                attachment_model=MatterAttachment,
                candidate_statuses=[DocumentProcessingStatus.INDEXED],
                action=DocumentProcessingAction.REINDEX,
                processed_before=reindex_cutoff,
                limit=limit - queued,
            )
        if reindex_after_hours >= 0 and queued < limit:
            queued += _enqueue_attachment_reprocessing_candidates(
                session,
                target_type=DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
                attachment_model=ContractAttachment,
                candidate_statuses=[DocumentProcessingStatus.INDEXED],
                action=DocumentProcessingAction.REINDEX,
                processed_before=reindex_cutoff,
                limit=limit - queued,
            )

        session.commit()
        return queued
    finally:
        session.close()


def load_processing_job(job_id: str) -> DocumentProcessingJobRecord | None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job = session.scalar(
            select(DocumentProcessingJob)
            .options(
                joinedload(DocumentProcessingJob.requested_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(DocumentProcessingJob.id == job_id)
        )
        return _job_record(job) if job else None
    finally:
        session.close()


def run_document_processing_job(job_id: str) -> None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job = session.scalar(
            select(DocumentProcessingJob)
            .options(
                joinedload(DocumentProcessingJob.requested_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(DocumentProcessingJob.id == job_id)
        )
        if not job or job.status not in {
            DocumentProcessingJobStatus.QUEUED,
            DocumentProcessingJobStatus.FAILED,
        }:
            return

        job.status = DocumentProcessingJobStatus.PROCESSING
        job.attempt_count += 1
        job.started_at = utcnow()
        job.completed_at = None
        job.error_message = None
        job.processed_char_count = 0
        session.add(job)
        session.commit()

        try:
            if job.target_type == DocumentProcessingTargetType.MATTER_ATTACHMENT:
                _process_matter_attachment_job(session, job)
            elif job.target_type == DocumentProcessingTargetType.CONTRACT_ATTACHMENT:
                _process_contract_attachment_job(session, job)
            else:
                _mark_job_failed(
                    session,
                    job,
                    error_message=f"Unsupported document processing target: {job.target_type}.",
                )
        except Exception as exc:
            session.rollback()
            failed_job = session.scalar(
                select(DocumentProcessingJob).where(DocumentProcessingJob.id == job.id)
            )
            if failed_job is not None:
                _mark_job_failed(session, failed_job, error_message=str(exc))
    finally:
        session.close()


def _success_title(action: str) -> str:
    if action == DocumentProcessingAction.RETRY:
        return "Attachment retry completed"
    if action == DocumentProcessingAction.REINDEX:
        return "Attachment reindex completed"
    return "Attachment indexed"


def _failure_title(action: str) -> str:
    if action == DocumentProcessingAction.RETRY:
        return "Attachment retry failed"
    if action == DocumentProcessingAction.REINDEX:
        return "Attachment reindex failed"
    return "Attachment processing failed"


def _mark_job_failed(
    session: Session,
    job: DocumentProcessingJob,
    *,
    error_message: str,
) -> None:
    job.status = DocumentProcessingJobStatus.FAILED
    job.error_message = error_message
    job.completed_at = utcnow()
    session.add(job)
    session.commit()


def _attachment_has_open_job(
    session: Session,
    *,
    target_type: str,
    attachment_id: str,
) -> bool:
    existing_job = session.scalar(
        select(DocumentProcessingJob.id).where(
            DocumentProcessingJob.target_type == target_type,
            DocumentProcessingJob.attachment_id == attachment_id,
            DocumentProcessingJob.status.in_(
                [DocumentProcessingJobStatus.QUEUED, DocumentProcessingJobStatus.PROCESSING]
            ),
        )
    )
    return existing_job is not None


def _enqueue_attachment_reprocessing_candidates(
    session: Session,
    *,
    target_type: str,
    attachment_model: type[MatterAttachment] | type[ContractAttachment],
    candidate_statuses: list[str],
    action: str,
    processed_before,
    limit: int,
) -> int:
    if limit <= 0:
        return 0

    attachments = list(
        session.scalars(
            select(attachment_model)
            .options(
                joinedload(MatterAttachment.matter)
                if attachment_model is MatterAttachment
                else joinedload(ContractAttachment.contract)
            )
            .where(
                attachment_model.processing_status.in_(candidate_statuses),
                attachment_model.processed_at.is_not(None),
                attachment_model.processed_at <= processed_before,
            )
            .order_by(attachment_model.processed_at.asc())
            .limit(limit * 3)
        )
    )

    queued = 0
    for attachment in attachments:
        if queued >= limit:
            break
        if _attachment_has_open_job(
            session,
            target_type=target_type,
            attachment_id=attachment.id,
        ):
            continue
        if isinstance(attachment, MatterAttachment):
            company_id = attachment.matter.company_id
        else:
            company_id = attachment.contract.company_id
        enqueue_processing_job(
            session,
            company_id=company_id,
            requested_by_membership_id=None,
            target_type=target_type,
            attachment_id=attachment.id,
            action=action,
        )
        queued += 1
    return queued


def _process_matter_attachment_job(session: Session, job: DocumentProcessingJob) -> None:
    attachment = session.scalar(
        select(MatterAttachment)
        .options(
            selectinload(MatterAttachment.chunks),
            joinedload(MatterAttachment.matter),
        )
        .where(MatterAttachment.id == job.attachment_id)
    )
    if not attachment or not attachment.matter or attachment.matter.company_id != job.company_id:
        _mark_job_failed(session, job, error_message="Matter attachment could not be found.")
        return

    attachment.chunks.clear()
    session.flush()
    index_matter_attachment(attachment)
    job.processed_char_count = attachment.extracted_char_count
    job.error_message = attachment.extraction_error
    job.completed_at = utcnow()
    job.status = (
        DocumentProcessingJobStatus.COMPLETED
        if attachment.processing_status == DocumentProcessingStatus.INDEXED
        else DocumentProcessingJobStatus.FAILED
    )
    session.add(attachment)
    session.add(job)
    session.add(
        MatterActivity(
            matter_id=attachment.matter_id,
            actor_membership_id=job.requested_by_membership_id,
            event_type=(
                "attachment_processed"
                if job.status == DocumentProcessingJobStatus.COMPLETED
                else "attachment_processing_failed"
            ),
            title=(
                _success_title(job.action)
                if job.status == DocumentProcessingJobStatus.COMPLETED
                else _failure_title(job.action)
            ),
            detail=(
                f"{attachment.original_filename} processed with status "
                f"{attachment.processing_status}."
                if not attachment.extraction_error
                else f"{attachment.original_filename}: {attachment.extraction_error}"
            ),
        )
    )
    session.commit()


def _process_contract_attachment_job(session: Session, job: DocumentProcessingJob) -> None:
    attachment = session.scalar(
        select(ContractAttachment)
        .options(
            selectinload(ContractAttachment.chunks),
            joinedload(ContractAttachment.contract),
        )
        .where(ContractAttachment.id == job.attachment_id)
    )
    if (
        not attachment
        or not attachment.contract
        or attachment.contract.company_id != job.company_id
    ):
        _mark_job_failed(session, job, error_message="Contract attachment could not be found.")
        return

    attachment.chunks.clear()
    session.flush()
    index_contract_attachment(attachment)
    job.processed_char_count = attachment.extracted_char_count
    job.error_message = attachment.extraction_error
    job.completed_at = utcnow()
    job.status = (
        DocumentProcessingJobStatus.COMPLETED
        if attachment.processing_status == DocumentProcessingStatus.INDEXED
        else DocumentProcessingJobStatus.FAILED
    )
    session.add(attachment)
    session.add(job)
    session.add(
        ContractActivity(
            contract_id=attachment.contract_id,
            actor_membership_id=job.requested_by_membership_id,
            event_type=(
                "contract_attachment_processed"
                if job.status == DocumentProcessingJobStatus.COMPLETED
                else "contract_attachment_processing_failed"
            ),
            title=(
                _success_title(job.action)
                if job.status == DocumentProcessingJobStatus.COMPLETED
                else _failure_title(job.action)
            ),
            detail=(
                f"{attachment.original_filename} processed with status "
                f"{attachment.processing_status}."
                if not attachment.extraction_error
                else f"{attachment.original_filename}: {attachment.extraction_error}"
            ),
        )
    )
    session.commit()
