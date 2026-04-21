from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterCourtSyncJob,
    MatterCourtSyncJobStatus,
    utcnow,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.matters import MatterCourtSyncJobRecord
from caseops_api.services.court_sync_sources import (
    get_court_sync_adapter,
    list_supported_court_sync_sources,
    resolve_source_for_court,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.matters import _get_matter_model, _persist_court_sync_import


def _job_record(job: MatterCourtSyncJob) -> MatterCourtSyncJobRecord:
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


def create_matter_court_sync_job(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    source: str | None,
    source_reference: str | None,
) -> MatterCourtSyncJobRecord:
    matter = _get_matter_model(session, context=context, matter_id=matter_id)

    # When the client omits `source`, derive it from the matter's court.
    # Most matters only ever want one live adapter — forcing the lawyer
    # to pick one from a dropdown is bad UX.
    if not source or not source.strip():
        resolved = resolve_source_for_court(matter.court_name)
        if resolved is None:
            # Distinguish "no court set on matter" from "court set but
            # no adapter" — the first is a data-completion action for
            # the user; the second is a product-coverage gap.
            supported = ", ".join(list_supported_court_sync_sources())
            if not matter.court_name:
                detail = (
                    "This matter doesn't have a court set. Edit the matter "
                    "to choose a court before running sync — supported: "
                    f"{supported}."
                )
            else:
                detail = (
                    f"Live sync isn't wired for {matter.court_name!r} yet. "
                    "Pass an explicit `source` from the supported list "
                    "or edit the matter to use a supported court — "
                    f"supported: {supported}."
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
            )
        source = resolved

    try:
        get_court_sync_adapter(source)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    job = MatterCourtSyncJob(
        company_id=context.company.id,
        matter_id=matter.id,
        requested_by_membership_id=context.membership.id,
        source=source.strip(),
        source_reference=source_reference.strip() if source_reference else None,
        status=MatterCourtSyncJobStatus.QUEUED,
    )
    session.add(job)
    session.commit()

    refreshed = session.scalar(
        select(MatterCourtSyncJob)
        .options(
            joinedload(MatterCourtSyncJob.requested_by_membership).joinedload(
                CompanyMembership.user
            )
        )
        .where(MatterCourtSyncJob.id == job.id)
    )
    assert refreshed is not None
    return _job_record(refreshed)


def load_court_sync_job(job_id: str) -> MatterCourtSyncJobRecord | None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job = session.scalar(
            select(MatterCourtSyncJob)
            .options(
                joinedload(MatterCourtSyncJob.requested_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(MatterCourtSyncJob.id == job_id)
        )
        return _job_record(job) if job else None
    finally:
        session.close()


def drain_matter_court_sync_jobs(*, limit: int) -> int:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job_ids = list(
            session.scalars(
                select(MatterCourtSyncJob.id)
                .where(MatterCourtSyncJob.status == MatterCourtSyncJobStatus.QUEUED)
                .order_by(MatterCourtSyncJob.queued_at.asc(), MatterCourtSyncJob.updated_at.asc())
                .limit(limit)
            )
        )
    finally:
        session.close()

    processed = 0
    for job_id in job_ids:
        before = load_court_sync_job(job_id)
        if before and before.status == MatterCourtSyncJobStatus.QUEUED:
            run_matter_court_sync_job(job_id)
            processed += 1
    return processed


def recover_stale_matter_court_sync_jobs(*, stale_after_minutes: int) -> int:
    cutoff = utcnow() - timedelta(minutes=stale_after_minutes)
    session_factory = get_session_factory()
    session = session_factory()
    try:
        jobs = list(
            session.scalars(
                select(MatterCourtSyncJob).where(
                    MatterCourtSyncJob.status == MatterCourtSyncJobStatus.PROCESSING,
                    MatterCourtSyncJob.started_at.is_not(None),
                    MatterCourtSyncJob.started_at <= cutoff,
                )
            )
        )
        if not jobs:
            return 0

        for job in jobs:
            job.status = MatterCourtSyncJobStatus.QUEUED
            job.error_message = "Recovered stale court sync job for retry."
            job.started_at = None
            job.completed_at = None
            session.add(job)
        session.commit()
        return len(jobs)
    finally:
        session.close()


def run_matter_court_sync_job(job_id: str) -> None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job = session.scalar(
            select(MatterCourtSyncJob)
            .options(
                joinedload(MatterCourtSyncJob.requested_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(MatterCourtSyncJob.id == job_id)
        )
        if not job or job.status not in {
            MatterCourtSyncJobStatus.QUEUED,
            MatterCourtSyncJobStatus.FAILED,
        }:
            return

        job.status = MatterCourtSyncJobStatus.PROCESSING
        job.started_at = utcnow()
        job.completed_at = None
        job.error_message = None
        session.add(job)
        session.commit()

        try:
            matter = session.scalar(select(Matter).where(Matter.id == job.matter_id))
            if matter is None:
                raise ValueError("Matter not found for court sync job.")

            adapter = get_court_sync_adapter(job.source)
            result = adapter.fetch(matter=matter, source_reference=job.source_reference)
            sync_run = _persist_court_sync_import(
                session,
                matter=matter,
                actor_membership_id=job.requested_by_membership_id,
                source=job.source,
                summary=result.summary,
                cause_list_entries=result.cause_list_entries,
                orders=result.orders,
            )
            job.adapter_name = result.adapter_name
            job.sync_run_id = sync_run.id
            job.imported_cause_list_count = len(result.cause_list_entries)
            job.imported_order_count = len(result.orders)
            job.status = MatterCourtSyncJobStatus.COMPLETED
            job.completed_at = utcnow()
            session.add(job)
            session.commit()
        except Exception as exc:
            session.rollback()
            failed_job = session.scalar(
                select(MatterCourtSyncJob).where(MatterCourtSyncJob.id == job_id)
            )
            if failed_job is not None:
                failed_job.status = MatterCourtSyncJobStatus.FAILED
                failed_job.error_message = str(exc)
                failed_job.completed_at = utcnow()
                session.add(failed_job)
                session.commit()
    finally:
        session.close()
