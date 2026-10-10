from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.redaction import redact_provider_error
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Contract,
    ContractActivity,
    ContractAttachment,
    DocumentProcessingAction,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingStatus,
    DocumentProcessingTargetType,
    IpDocument,
    IpDocumentVersion,
    Matter,
    MatterActivity,
    MatterAttachment,
    utcnow,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.document_processing import DocumentProcessingJobRecord
from caseops_api.services.document_processing import (
    embed_matter_attachment_chunks,
    index_contract_attachment,
    index_ip_document_version,
    index_matter_attachment,
)
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
    matter_is_operational,
)
from caseops_api.services.matter_write_fence import (
    lock_document_private_provenance,
    lock_matter_private_authority,
)

DOCUMENT_JOB_CLAIM_MINUTES = 15
MAX_DOCUMENT_JOB_BATCH = 100
MAX_DOCUMENT_JOB_RECOVERY_BATCH = 5


@dataclass(frozen=True, slots=True)
class _Attempt:
    id: str
    company_id: str
    number: int
    started_at: datetime | None


class _ClaimLost(RuntimeError):
    pass


def _bounded_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_DOCUMENT_JOB_BATCH:
        raise ValueError(f"Document job limit must be between 1 and {MAX_DOCUMENT_JOB_BATCH}.")
    return limit


def _set_attempt_context(
    session: Session, attempt: _Attempt, *, operation: str = "execute",
) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    payload = json.dumps({
        "id": attempt.id,
        "attempt_count": attempt.number,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "operation": operation,
    })
    with session.no_autoflush:
        session.execute(text(
            "SELECT set_config('caseops.document_job_attempt', :identity, true)"
        ), {"identity": payload})


def _claim_job(session: Session, job_id: str) -> DocumentProcessingJob | None:
    # Bare-row locking avoids nullable joined actors; CAS also protects SQLite.
    if session.get_bind().dialect.name == "sqlite" and hasattr(session, "serialize_sqlite_writer"):
        session.serialize_sqlite_writer()
    available = session.execute(
        select(DocumentProcessingJob.id, DocumentProcessingJob.company_id,
               DocumentProcessingJob.attempt_count).where(
            DocumentProcessingJob.id == job_id,
            DocumentProcessingJob.status == DocumentProcessingJobStatus.QUEUED,
        ).with_for_update(of=DocumentProcessingJob, skip_locked=True)
    ).one_or_none()
    if available is None:
        session.rollback()
        return None
    started_at = utcnow()
    _set_attempt_context(session, _Attempt(
        id=available.id, company_id=available.company_id,
        number=available.attempt_count + 1, started_at=started_at,
    ))
    claimed = session.execute(
        update(DocumentProcessingJob).where(
            DocumentProcessingJob.id == job_id,
            DocumentProcessingJob.status == DocumentProcessingJobStatus.QUEUED,
        ).values(
            status=DocumentProcessingJobStatus.PROCESSING,
            attempt_count=DocumentProcessingJob.attempt_count + 1,
            started_at=started_at, completed_at=None, error_message=None,
            processed_char_count=0,
        ).returning(
            DocumentProcessingJob.id, DocumentProcessingJob.company_id,
            DocumentProcessingJob.attempt_count, DocumentProcessingJob.started_at,
        )
    ).one_or_none()
    session.commit()
    if claimed is None:
        return None
    session.info["document_job_attempt"] = _Attempt(
        id=claimed.id, company_id=claimed.company_id, number=claimed.attempt_count,
        started_at=claimed.started_at,
    )
    # A process may pause after commit; never adopt a reclaimed attempt's token.
    job = session.get(DocumentProcessingJob, job_id)
    if job is None or (
        job.company_id, job.status, job.attempt_count, job.started_at
    ) != (
        claimed.company_id, DocumentProcessingJobStatus.PROCESSING,
        claimed.attempt_count, claimed.started_at,
    ):
        session.rollback()
        return None
    return job


def _fence_attempt(session: Session) -> None:
    attempt = session.info["document_job_attempt"]
    with session.no_autoflush:
        job = session.scalar(
            select(DocumentProcessingJob.id).where(
                DocumentProcessingJob.id == attempt.id,
                DocumentProcessingJob.company_id == attempt.company_id,
                DocumentProcessingJob.status == DocumentProcessingJobStatus.PROCESSING,
                DocumentProcessingJob.attempt_count == attempt.number,
                DocumentProcessingJob.started_at == attempt.started_at,
                DocumentProcessingJob.started_at > utcnow() - timedelta(
                    minutes=DOCUMENT_JOB_CLAIM_MINUTES
                ),
            ).with_for_update(of=DocumentProcessingJob)
        )
    if job is None:
        raise _ClaimLost("Document processing claim expired or was replaced.")
    _set_attempt_context(session, attempt)


def _release_preparation_transaction(session: Session, source) -> None:
    # Detach loaded immutable inputs before rollback so parser/provider work
    # cannot lazy-load, autoflush or retain a database transaction.
    if hasattr(source, "chunks"):
        session.info["document_source_chunks"] = sorted(chunk.id for chunk in source.chunks)
    session.expunge_all()
    session.rollback()


def _assert_company_active(session: Session, *, company_id: str) -> None:
    with session.no_autoflush:
        active = session.scalar(select(Company.is_active).where(Company.id == company_id))
    if active is not True:
        raise ValueError("Company inactive; document processing skipped.")


def _lock_active_company_authority(session: Session, *, company_id: str) -> None:
    lock_matter_private_authority(session, company_id=company_id)
    # Scalar read cannot reuse an activity value captured before external I/O.
    _assert_company_active(session, company_id=company_id)


def _assert_same_source(session: Session, source) -> None:
    model = type(source)
    names = ["sha256_hex", "storage_key", "uploaded_by_membership_id"]
    if isinstance(source, IpDocumentVersion):
        names.extend(["document_id", "version", "state", "locked_by_membership_id"])
    elif isinstance(source, MatterAttachment):
        names.extend(["matter_id", "linked_court_order_id", "document_type"])
    elif isinstance(source, ContractAttachment):
        names.append("contract_id")
    row = session.execute(
        select(*(getattr(model, name) for name in names)).where(model.id == source.id)
        .with_for_update(of=model)
    ).one_or_none()
    if row is None or tuple(row) != tuple(getattr(source, name) for name in names):
        raise ValueError("Document source changed during processing.")
    if hasattr(source, "chunks"):
        chunk_model = model.chunks.property.mapper.class_
        ids = sorted(session.scalars(
            select(chunk_model.id).where(chunk_model.attachment_id == source.id)
        ))
        if ids != session.info["document_source_chunks"]:
            raise ValueError("Document chunks changed during processing.")


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
    no_paid_providers: bool = False,
) -> DocumentProcessingJob:
    job = DocumentProcessingJob(
        company_id=company_id,
        requested_by_membership_id=requested_by_membership_id,
        target_type=target_type,
        attachment_id=attachment_id,
        action=action,
        status=DocumentProcessingJobStatus.QUEUED,
        no_paid_providers=no_paid_providers or paid_providers_blocked_for_request(),
    )
    session.add(job)
    session.flush()
    return job


def drain_document_processing_jobs(*, limit: int, outcomes: dict[str, int] | None = None) -> int:
    _bounded_limit(limit)
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job_ids = list(
            session.scalars(
                select(DocumentProcessingJob.id)
                .where(DocumentProcessingJob.status == DocumentProcessingJobStatus.QUEUED)
                .order_by(
                    DocumentProcessingJob.queued_at.asc(),
                    DocumentProcessingJob.id.asc(),
                )
                .limit(limit)
            )
        )
    finally:
        session.close()

    processed = 0
    for job_id in job_ids:
        if run_document_processing_job(job_id):
            processed += 1
            if outcomes is not None:
                with session_factory() as check:
                    status = check.scalar(select(DocumentProcessingJob.status).where(
                        DocumentProcessingJob.id == job_id,
                    ))
                # Claimed is not indexed: terminal refusals remain FAILED, and
                # a recovered/lost attempt may still be QUEUED or PROCESSING.
                key = status if status in {"completed", "failed"} else "unfinalized"
                outcomes[key] = outcomes.get(key, 0) + 1
    return processed


def recover_stale_document_processing_jobs(
    *, stale_after_minutes: int = DOCUMENT_JOB_CLAIM_MINUTES, limit: int = 5,
) -> int:
    _bounded_limit(limit)
    if limit > MAX_DOCUMENT_JOB_RECOVERY_BATCH:
        raise ValueError("Document recovery batch size must not exceed 5.")
    if stale_after_minutes < DOCUMENT_JOB_CLAIM_MINUTES:
        raise ValueError("Document recovery age must be at least the 15-minute claim lease.")
    cutoff = utcnow() - timedelta(minutes=stale_after_minutes)
    session_factory = get_session_factory()
    session = session_factory()
    try:
        jobs = list(
            session.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.status == DocumentProcessingJobStatus.PROCESSING,
                    or_(
                        DocumentProcessingJob.started_at <= cutoff,
                        and_(DocumentProcessingJob.started_at.is_(None),
                             DocumentProcessingJob.updated_at <= cutoff),
                    ),
                ).order_by(DocumentProcessingJob.started_at.nulls_first(), DocumentProcessingJob.id)
                .limit(limit).with_for_update(of=DocumentProcessingJob, skip_locked=True)
            )
        )
        if not jobs:
            return 0

        for job in jobs:
            _set_attempt_context(session, _Attempt(
                id=job.id, company_id=job.company_id,
                number=job.attempt_count, started_at=job.started_at,
            ))
            job.status = DocumentProcessingJobStatus.QUEUED
            job.error_message = "Recovered stale processing job for retry."
            job.started_at = None
            job.completed_at = None
            session.add(job)
            session.flush([job])
        session.commit()
        return len(jobs)
    finally:
        session.close()


def cancel_document_processing_job_for_disposal(
    session: Session, job: DocumentProcessingJob, *, completed_at: datetime,
) -> bool:
    # The lifecycle caller already holds Company and the authoritative Matter.
    # Lock/reload this receipt and flush it before another identity is installed.
    with session.no_autoflush:
        current = session.scalar(select(DocumentProcessingJob).where(
            DocumentProcessingJob.id == job.id,
            DocumentProcessingJob.company_id == job.company_id,
            DocumentProcessingJob.target_type == DocumentProcessingTargetType.MATTER_ATTACHMENT,
        ).with_for_update(of=DocumentProcessingJob).execution_options(populate_existing=True))
        if current is None or current.status not in {
            DocumentProcessingJobStatus.QUEUED, DocumentProcessingJobStatus.PROCESSING,
        }:
            return False
        _set_attempt_context(session, _Attempt(
            id=current.id, company_id=current.company_id,
            number=current.attempt_count, started_at=current.started_at,
        ), operation="cancel")
        current.status = DocumentProcessingJobStatus.FAILED
        current.error_message = "Cancelled because the matter was disposed."
        current.completed_at = completed_at
        session.flush([current])
    return True


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
                target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
                attachment_model=IpDocumentVersion,
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
                target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
                attachment_model=IpDocumentVersion,
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


def run_document_processing_job(job_id: str) -> bool:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job = _claim_job(session, job_id)
        if job is None:
            return False
        marker = set_automated_test_request(
            NO_PAID_PROVIDERS_VALUE
            if job.no_paid_providers or paid_providers_blocked_for_request() else None
        )
        try:
            _assert_company_active(session, company_id=job.company_id)
            if job.target_type == DocumentProcessingTargetType.MATTER_ATTACHMENT:
                _process_matter_attachment_job(session, job)
            elif job.target_type == DocumentProcessingTargetType.CONTRACT_ATTACHMENT:
                _process_contract_attachment_job(session, job)
            elif job.target_type == DocumentProcessingTargetType.IP_DOCUMENT_VERSION:
                _process_ip_document_version_job(session, job)
            else:
                _mark_job_failed(
                    session,
                    job,
                    error_message=f"Unsupported document processing target: {job.target_type}.",
                )
        except _ClaimLost:
            session.rollback()
        except Exception as exc:
            session.rollback()
            _mark_job_failed(session, job, error_message=redact_provider_error(exc))
        finally:
            reset_automated_test_request(marker)
        return True
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
    session.rollback()
    attempt = session.info["document_job_attempt"]
    lock_matter_private_authority(session, company_id=attempt.company_id)
    try:
        _fence_attempt(session)
    except _ClaimLost:
        session.rollback()
        return
    current = session.get(DocumentProcessingJob, attempt.id)
    current.status = DocumentProcessingJobStatus.FAILED
    current.error_message = error_message
    current.completed_at = utcnow()
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
    attachment_model: type[MatterAttachment] | type[ContractAttachment] | type[IpDocumentVersion],
    candidate_statuses: list[str],
    action: str,
    processed_before,
    limit: int,
) -> int:
    if limit <= 0:
        return 0

    stmt = select(attachment_model)
    if attachment_model is MatterAttachment:
        stmt = stmt.options(joinedload(MatterAttachment.matter))
    elif attachment_model is ContractAttachment:
        stmt = stmt.options(joinedload(ContractAttachment.contract))
    attachments = list(
        session.scalars(
            stmt.where(
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
            if not matter_is_operational(attachment.matter):
                continue
            company_id = attachment.matter.company_id
        elif isinstance(attachment, ContractAttachment):
            company_id = attachment.contract.company_id
        else:
            company_id = attachment.company_id
        enqueue_processing_job(
            session,
            company_id=company_id,
            requested_by_membership_id=None,
            target_type=target_type,
            attachment_id=attachment.id,
            action=action,
            no_paid_providers=True,
        )
        queued += 1
    return queued


def _process_matter_attachment_job(session: Session, job: DocumentProcessingJob) -> None:
    attachment = session.scalar(
        select(MatterAttachment)
        .options(
            selectinload(MatterAttachment.chunks),
            joinedload(MatterAttachment.matter),
            joinedload(MatterAttachment.linked_court_order),
        )
        .where(MatterAttachment.id == job.attachment_id)
    )
    if not attachment or not attachment.matter or attachment.matter.company_id != job.company_id:
        _mark_job_failed(session, job, error_message="Matter attachment could not be found.")
        return

    try:
        assert_operational_matter(
            session,
            matter=attachment.matter,
            lock_for_write=False,
        )
    except MatterNotOperationalError:
        _mark_job_failed(
            session,
            job,
            error_message="Matter disposed; document processing skipped.",
        )
        return

    lifecycle_version = attachment.matter.lifecycle_version
    _release_preparation_transaction(session, attachment)
    # Replacing the relationship also deletes prior chunks for retry/reindex,
    # but deliberately leave that mutation unflushed until the external
    # parse/embed work has finished and the parent lifecycle row is locked.
    index_matter_attachment(attachment)

    event_actor_membership_id = (
        job.requested_by_membership_id or attachment.uploaded_by_membership_id
    )
    parent_locked_for_persist = False

    def lock_operational_parent_for_persist() -> None:
        nonlocal parent_locked_for_persist
        if parent_locked_for_persist:
            return
        # The attachment and replacement chunks are dirty at this point.
        # Private events retain the historical human actor FK even though the
        # processing activity is a system event. Enter tenant authority before
        # the retained job/source FKs and parent locks, with chunks unflushed.
        # The shared parent fence still excludes disposal and reopening.
        with session.no_autoflush:
            _lock_active_company_authority(session, company_id=job.company_id)
            _fence_attempt(session)
            lock_document_private_provenance(
                session,
                company_id=job.company_id,
                actor_membership_id=event_actor_membership_id,
                requested_by_membership_id=job.requested_by_membership_id,
                uploaded_by_membership_id=attachment.uploaded_by_membership_id,
                locked_by_membership_id=None,
            )
            fresh_matter = session.scalar(select(Matter).where(
                Matter.id == attachment.matter_id, Matter.company_id == job.company_id,
            ))
            if fresh_matter is None:
                raise ValueError("Matter attachment could not be found.")
            assert_operational_matter(
                session,
                matter=fresh_matter,
                shared_lifecycle_fence=True,
            )
            if fresh_matter.lifecycle_version != lifecycle_version:
                raise ValueError("Matter lifecycle changed during document processing.")
            _assert_same_source(session, attachment)
            set_committed_value(attachment, "matter", fresh_matter)
            session.add(attachment)
        parent_locked_for_persist = True

    # Keep the attachment, chunks, and Matter row unlocked throughout the
    # external embedding call. PostgreSQL embedding writes require a flush,
    # so the hook acquires/rechecks the lifecycle lock immediately beforehand.
    # Best-effort provider failure still leaves lexical chunks, protected by
    # the explicit lock immediately below.
    _assert_company_active(session, company_id=job.company_id)
    session.rollback()
    embed_matter_attachment_chunks(
        session,
        attachment,
        before_flush=lock_operational_parent_for_persist,
    )
    lock_operational_parent_for_persist()
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
    should_extract_compliance = job.status == DocumentProcessingJobStatus.COMPLETED and (
        attachment.linked_court_order_id or attachment.document_type == "order_judgment"
    )
    processing_job_id = job.id
    session.add(
        MatterActivity(
            matter_id=attachment.matter_id,
            actor_membership_id=None,
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
    if event_actor_membership_id is not None:
        from caseops_api.services.private_retrieval import (
            propagate_private_source_change_if_indexed,
        )

        session.flush()
        propagate_private_source_change_if_indexed(
            session,
            company_id=job.company_id,
            actor_membership_id=event_actor_membership_id,
            idempotency_key=f"matter-document-indexed:{job.id}",
            event_type="source_changed",
            target_type="matter_document",
            target_id=attachment.id,
            target_version=attachment.sha256_hex,
            reason_code="matter_attachment_processing_completed",
        )

    # Persist indexing atomically under the parent lifecycle lock, then release
    # that lock before downstream compliance work. Compliance may involve many
    # queries or a provider deadline; it must not block the next interactive
    # order, hearing, or notice mutation on the same matter.
    session.commit()

    if should_extract_compliance:
        try:
            from caseops_api.services.compliance_extraction import (
                run_compliance_extraction_for_attachment,
            )

            run_compliance_extraction_for_attachment(
                session,
                matter=attachment.matter,
                attachment=attachment,
                trigger="attachment_processed",
                actor_membership_id=None,
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            from caseops_api.core.redaction import redact_provider_error

            persisted_job = session.get(DocumentProcessingJob, processing_job_id)
            if persisted_job is not None:
                _set_attempt_context(session, session.info["document_job_attempt"])
                persisted_job.error_message = (
                    f"Compliance extraction failed: {redact_provider_error(exc)}"
                )
                session.add(persisted_job)
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

    linked_matter_id = attachment.contract.linked_matter_id
    linked_lifecycle = (
        session.scalar(select(Matter.lifecycle_version).where(Matter.id == linked_matter_id))
        if linked_matter_id else None
    )
    _release_preparation_transaction(session, attachment)
    index_contract_attachment(attachment)
    with session.no_autoflush:
        _lock_active_company_authority(session, company_id=job.company_id)
        _fence_attempt(session)
        lock_document_private_provenance(
            session, company_id=job.company_id,
            actor_membership_id=(
                job.requested_by_membership_id or attachment.uploaded_by_membership_id
            ),
            requested_by_membership_id=job.requested_by_membership_id,
            uploaded_by_membership_id=attachment.uploaded_by_membership_id,
            locked_by_membership_id=None,
        )
        if linked_matter_id is not None:
            matter = session.scalar(select(Matter).where(
                Matter.id == linked_matter_id, Matter.company_id == job.company_id,
            ))
            if matter is None:
                raise ValueError("Linked Matter could not be found.")
            assert_operational_matter(session, matter=matter, shared_lifecycle_fence=True)
            if matter.lifecycle_version != linked_lifecycle:
                raise ValueError("Linked Matter lifecycle changed during document processing.")
        contract = session.scalar(select(Contract).where(
            Contract.id == attachment.contract_id, Contract.company_id == job.company_id,
        ).with_for_update(of=Contract))
        if contract is None or contract.linked_matter_id != linked_matter_id:
            raise ValueError("Contract parent changed during processing.")
        _assert_same_source(session, attachment)
        set_committed_value(attachment, "contract", contract)
        session.add(attachment)
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


def _process_ip_document_version_job(session: Session, job: DocumentProcessingJob) -> None:
    version = session.scalar(
        select(IpDocumentVersion).where(
            IpDocumentVersion.id == job.attachment_id,
            IpDocumentVersion.company_id == job.company_id,
        )
    )
    if version is None:
        _mark_job_failed(session, job, error_message="IP document version could not be found.")
        return
    from caseops_api.services.ip_document_targets import (
        _lock_upload_targets,
        _upload_document_targets,
        _upload_target_lifecycles,
    )

    document = session.scalar(select(IpDocument).where(
        IpDocument.id == version.document_id, IpDocument.company_id == job.company_id,
    ))
    if document is None:
        _mark_job_failed(session, job, error_message="IP document could not be found.")
        return
    current_version = document.current_version
    targets = _upload_document_targets(
        session, company_id=job.company_id, document_id=document.id,
    )
    expected_lifecycles = _upload_target_lifecycles(
        session, company_id=job.company_id, targets=targets,
    )
    _release_preparation_transaction(session, version)
    index_ip_document_version(version)
    # Extraction dirties the version. Fence authority before even a SELECT can
    # autoflush it; patent source writers already lock Company before versions.
    # Keep extraction outside the tenant lock.
    with session.no_autoflush:
        _lock_active_company_authority(session, company_id=job.company_id)
        _fence_attempt(session)
        lock_document_private_provenance(
            session,
            company_id=job.company_id,
            actor_membership_id=version.uploaded_by_membership_id,
            requested_by_membership_id=job.requested_by_membership_id,
            uploaded_by_membership_id=version.uploaded_by_membership_id,
            locked_by_membership_id=version.locked_by_membership_id,
        )
        if targets:
            from caseops_api.services.identity import get_session_context
            from caseops_api.services.ip_operations import _lock_ip_writer_context

            context = get_session_context(session, version.uploaded_by_membership_id)
            if context.company.id != job.company_id:
                raise ValueError("Document actor does not belong to the company.")
            context = _lock_ip_writer_context(
                session, context=context, required_capability="documents:upload",
            )
            fresh_targets = _upload_document_targets(
                session, company_id=job.company_id, document_id=version.document_id,
            )
            if set((row.target_type, row.target_id) for row in fresh_targets) != set(
                (row.target_type, row.target_id) for row in targets
            ):
                raise ValueError("IP document targets changed during processing.")
            _lock_upload_targets(
                session, context=context, targets=fresh_targets,
                expected_lifecycles=expected_lifecycles,
            )
        document = session.scalar(select(IpDocument).where(
            IpDocument.id == version.document_id, IpDocument.company_id == job.company_id,
        ).with_for_update(of=IpDocument))
        if document is None or document.current_version != current_version:
            raise ValueError("IP document version changed during processing.")
        _assert_same_source(session, version)
    job.processed_char_count = version.extracted_char_count
    job.error_message = version.extraction_error
    job.completed_at = utcnow()
    job.status = (
        DocumentProcessingJobStatus.COMPLETED
        if version.processing_status == DocumentProcessingStatus.INDEXED
        else DocumentProcessingJobStatus.FAILED
    )
    session.add(version)
    session.add(job)
    if document is not None and document.current_version == version.version:
        from caseops_api.services.private_retrieval import (
            propagate_private_source_change_if_indexed,
        )

        session.flush()
        propagate_private_source_change_if_indexed(
            session,
            company_id=job.company_id,
            actor_membership_id=version.uploaded_by_membership_id,
            idempotency_key=f"ip-document-indexed:{job.id}",
            event_type="source_changed",
            target_type="ip_document",
            target_id=document.id,
            target_version=str(document.current_version),
            reason_code="ip_document_processing_completed",
        )
    session.commit()
