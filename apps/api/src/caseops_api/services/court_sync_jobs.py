from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    reset_provider_replay_request,
    set_automated_test_request,
    set_provider_replay_request,
)
from caseops_api.core.redaction import redact_provider_error
from caseops_api.core.settings import get_settings, is_non_local_env
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
from caseops_api.services.matter_write_fence import require_read_only_upload_session
from caseops_api.services.matters import (
    _get_matter_model,
    _persist_court_sync_import,
    _prepare_court_sync_import,
)
from caseops_api.services.session_context import SessionContext

_MAX_COURT_SYNC_BATCH = 25


@dataclass(frozen=True)
class _CourtSyncClaim:
    job_id: str
    company_id: str
    matter_id: str
    actor_membership_id: str | None
    source: str
    source_reference: str | None
    no_paid_providers: bool
    started_at: datetime
    expires_at: datetime
    lifecycle_version: int


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _require_batch_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= _MAX_COURT_SYNC_BATCH:
        raise ValueError("Court sync batch size must be between 1 and 25.")


def dispatch_matter_court_sync_job(
    *,
    session: Session,
    background_tasks: BackgroundTasks,
    job_id: str,
) -> None:
    """Release committed admission; production is drained by a separate court executor."""
    require_read_only_upload_session(
        session,
        detail="Court sync admission must be committed before dispatch.",
    )
    session.rollback()
    if not is_non_local_env(get_settings().env):
        background_tasks.add_task(run_matter_court_sync_job, job_id)


def _matter_is_disposed(matter: Matter) -> bool:
    return str(matter.status) in {"closed", "disposed"} or not matter.is_active


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
    if _matter_is_disposed(matter):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot queue court sync because this matter is disposed.",
        )

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
        no_paid_providers=paid_providers_blocked_for_request(),
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


def drain_matter_court_sync_jobs(*, limit: int, outcomes: dict[str, int] | None = None) -> int:
    _require_batch_limit(limit)
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job_ids = list(
            session.scalars(
                select(MatterCourtSyncJob.id)
                .where(MatterCourtSyncJob.status == MatterCourtSyncJobStatus.QUEUED)
                .order_by(
                    MatterCourtSyncJob.queued_at.asc(),
                    MatterCourtSyncJob.updated_at.asc(),
                    MatterCourtSyncJob.id.asc(),
                )
                .limit(limit)
            )
        )
    finally:
        session.close()

    attempted_ids = []
    for job_id in job_ids:
        if run_matter_court_sync_job(job_id):
            attempted_ids.append(job_id)
    if outcomes is not None and attempted_ids:
        with session_factory() as check:
            statuses = dict(
                check.execute(
                    select(MatterCourtSyncJob.id, MatterCourtSyncJob.status).where(
                        MatterCourtSyncJob.id.in_(attempted_ids)
                    ),
                ).all()
            )
        # These are current job outcomes, not a claim that this attempt finalized them.
        for job_id in attempted_ids:
            job_status = statuses.get(job_id)
            key = job_status if job_status in {"completed", "failed"} else "unfinalized"
            outcomes[key] = outcomes.get(key, 0) + 1
    return len(attempted_ids)


def recover_stale_matter_court_sync_jobs(
    *,
    stale_after_minutes: int,
    limit: int = _MAX_COURT_SYNC_BATCH,
) -> int:
    _require_batch_limit(limit)
    if isinstance(stale_after_minutes, bool) or not 1 <= stale_after_minutes <= 1440:
        raise ValueError("Court sync recovery age must be between 1 and 1440 minutes.")
    cutoff = utcnow() - timedelta(minutes=stale_after_minutes)
    session_factory = get_session_factory()
    session = session_factory()
    try:
        jobs = list(
            session.scalars(
                select(MatterCourtSyncJob)
                .where(
                    MatterCourtSyncJob.status == MatterCourtSyncJobStatus.PROCESSING,
                    MatterCourtSyncJob.started_at.is_not(None),
                    MatterCourtSyncJob.started_at <= cutoff,
                )
                .order_by(MatterCourtSyncJob.started_at.asc(), MatterCourtSyncJob.id.asc())
                .limit(limit)
                .with_for_update(of=MatterCourtSyncJob, skip_locked=True)
                .execution_options(populate_existing=True)
            )
        )
        if not jobs:
            return 0

        for job in jobs:
            job.updated_at = max(
                _utc(utcnow()),
                _utc(job.updated_at),
                _utc(job.started_at),
            ) + timedelta(microseconds=1)
            job.status = MatterCourtSyncJobStatus.QUEUED
            job.error_message = "Recovered stale court sync job for retry."
            job.started_at = None
            job.completed_at = None
            session.add(job)
        session.commit()
        return len(jobs)
    finally:
        session.close()


def _claim_is_current(job: MatterCourtSyncJob | None, claim: _CourtSyncClaim) -> bool:
    return bool(
        job is not None
        and job.status == MatterCourtSyncJobStatus.PROCESSING
        and job.started_at is not None
        and _utc(job.started_at) == claim.started_at
        and _utc(utcnow()) < claim.expires_at
        and job.company_id == claim.company_id
        and job.matter_id == claim.matter_id
        and job.requested_by_membership_id == claim.actor_membership_id
        and job.source == claim.source
        and job.source_reference == claim.source_reference
        and job.no_paid_providers is claim.no_paid_providers
    )


def _load_claim(session: Session, claim: _CourtSyncClaim, *, lock: bool):
    statement = select(MatterCourtSyncJob).where(MatterCourtSyncJob.id == claim.job_id)
    if lock:
        statement = statement.with_for_update(of=MatterCourtSyncJob)
    job = session.scalar(statement.execution_options(populate_existing=True))
    return job if _claim_is_current(job, claim) else None


def run_matter_court_sync_job(job_id: str) -> bool:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job = session.scalar(
            select(MatterCourtSyncJob)
            .where(MatterCourtSyncJob.id == job_id)
            .with_for_update(of=MatterCourtSyncJob, skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if not job or job.status not in {
            MatterCourtSyncJobStatus.QUEUED,
            MatterCourtSyncJobStatus.FAILED,
        }:
            return False

        matter = session.scalar(select(Matter).where(Matter.id == job.matter_id))
        if matter is None or matter.company_id != job.company_id:
            job.status = MatterCourtSyncJobStatus.FAILED
            job.error_message = "Matter not found for court sync job."
            job.completed_at = utcnow()
            session.add(job)
            session.commit()
            return True
        if _matter_is_disposed(matter):
            job.status = MatterCourtSyncJobStatus.FAILED
            job.error_message = "Cancelled because the matter was disposed."
            job.completed_at = utcnow()
            session.add(job)
            session.commit()
            return True

        job.status = MatterCourtSyncJobStatus.PROCESSING
        # The existing timestamp is the claim identity. Recovery advances updated_at,
        # so even a fixed/backward clock cannot reuse an earlier claim timestamp.
        job.started_at = max(_utc(utcnow()), _utc(job.updated_at) + timedelta(microseconds=1))
        job.completed_at = None
        job.error_message = None
        session.add(job)
        claim = _CourtSyncClaim(
            job_id=job.id,
            company_id=job.company_id,
            matter_id=job.matter_id,
            actor_membership_id=job.requested_by_membership_id,
            source=job.source,
            source_reference=job.source_reference,
            no_paid_providers=job.no_paid_providers is not False,
            started_at=_utc(job.started_at),
            expires_at=_utc(job.started_at)
            + timedelta(
                minutes=get_settings().court_sync_stale_after_minutes,
            ),
            lifecycle_version=matter.lifecycle_version,
        )
        session.commit()
        # Adapters consume only loaded scalar Matter fields, never this session.
        session.expunge_all()

        marker = set_automated_test_request(
            NO_PAID_PROVIDERS_VALUE
            if claim.no_paid_providers or paid_providers_blocked_for_request()
            else None,
        )
        # Replay permission was request-local and is not recorded by this queue.
        replay_marker = set_provider_replay_request(None)
        try:
            adapter = get_court_sync_adapter(claim.source)
            result = adapter.fetch(matter=matter, source_reference=claim.source_reference)
            if _load_claim(session, claim, lock=False) is None:
                return True
            matter = session.get(Matter, claim.matter_id, populate_existing=True)
            if matter is None or matter.company_id != claim.company_id:
                raise ValueError("Matter not found for court sync job.")
            if matter.lifecycle_version != claim.lifecycle_version:
                raise ValueError("Court sync cancelled because the matter lifecycle changed.")
            prepared_compliance = _prepare_court_sync_import(
                session, matter=matter, source=claim.source,
                cause_list_entries=result.cause_list_entries,
                orders=result.orders,
            )
            if _load_claim(session, claim, lock=False) is None:
                return True
            from caseops_api.services.compliance_participants import lock_compliance_participants

            lock_compliance_participants(
                session,
                company_id=claim.company_id,
                matter_id=claim.matter_id,
                actor_membership_id=claim.actor_membership_id,
                expected_lifecycle_version=claim.lifecycle_version,
            )
            # Re-read and lock after the external call. Disposal may have won
            # while the adapter was fetching; populate_existing prevents the
            # session identity map from handing us the stale pre-fetch row.
            matter = session.scalar(
                select(Matter)
                .where(Matter.id == claim.matter_id, Matter.company_id == claim.company_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if matter is None:
                raise ValueError("Matter not found for court sync job.")
            if _matter_is_disposed(matter):
                raise ValueError("Court sync cancelled because the matter was disposed.")
            job = _load_claim(session, claim, lock=True)
            if job is None:
                return True
            sync_run = _persist_court_sync_import(
                session,
                matter=matter,
                actor_membership_id=claim.actor_membership_id,
                source=claim.source,
                summary=result.summary,
                cause_list_entries=result.cause_list_entries,
                orders=result.orders,
                prepared_compliance=prepared_compliance,
            )
            if not _claim_is_current(job, claim):
                session.rollback()
                return True
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
            failed_job = _load_claim(session, claim, lock=True)
            if failed_job is not None:
                failed_job.status = MatterCourtSyncJobStatus.FAILED
                failed_job.error_message = redact_provider_error(exc)
                failed_job.completed_at = utcnow()
                session.add(failed_job)
                session.commit()
        finally:
            reset_provider_replay_request(replay_marker)
            reset_automated_test_request(marker)
        return True
    finally:
        session.close()
