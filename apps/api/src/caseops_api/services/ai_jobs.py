"""Bounded drain of queued research answers, intelligent reviews and audit exports.

The API queues these rows and returns 202. Production bills the API per
request, so work left running after the response gets CPU only while other
requests land on the same instance. The independent ``caseops-ai-jobs`` Cloud
Run job runs them instead: woken on create, with a per-minute scheduler as
the backstop. Every runner claims its row with an atomic compare-and-set, so
concurrent executions never run the same row twice.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from caseops_api.db.models import (
    AuditExportJob,
    AuditExportJobStatus,
    Recommendation,
    ResearchAnswer,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import audit_exports, intelligent_reviews, research_answers

MAX_BATCH = 10
# The job's task timeout is 600 s. New work is claimed only in the first
# 240 s, so a typical 50-105 s answer always finishes inside the execution.
CLAIM_WINDOW_SECONDS = 240.0
# Longer than the task timeout: a running review or export older than this
# has no live executor.
RUNNING_LEASE = timedelta(minutes=15)

_SUCCESS = {
    "research_answer": {"answered", "abstained"},
    "intelligent_review": {"ready", "abstained"},
    "audit_export": {AuditExportJobStatus.COMPLETED},
}
_FAILED = {
    "research_answer": {"failed"},
    "intelligent_review": {"failed"},
    "audit_export": {AuditExportJobStatus.FAILED},
}


def _require_batch_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BATCH:
        raise ValueError(f"AI job batch size must be between 1 and {MAX_BATCH}.")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def recover_stale_ai_jobs(*, limit: int) -> int:
    """Settle rows whose executor is gone; each kind keeps its own semantics.

    Research answers use the same 10-minute rule as settle-on-read (failed,
    ``timed_out``). Reviews use the existing terminal-failure path. Exports
    become failed, which an explicit rerun may claim again.
    """
    _require_batch_limit(limit)
    now = datetime.now(UTC)
    recovered = 0
    stale_answer = (
        ResearchAnswer.status.in_(("queued", "running")),
        ResearchAnswer.created_at <= now - research_answers.STALE_AFTER,
    )
    with get_session_factory()() as session:
        answer_ids = list(
            session.scalars(
                select(ResearchAnswer.id)
                .where(*stale_answer)
                .order_by(ResearchAnswer.created_at.asc(), ResearchAnswer.id.asc())
                .limit(limit)
            )
        )
        session.rollback()
        for answer_id in answer_ids:
            answer = session.scalar(
                select(ResearchAnswer)
                .where(ResearchAnswer.id == answer_id, *stale_answer)
                .with_for_update(skip_locked=True)
            )
            if answer is None:
                session.rollback()
                continue
            # The same rule as settle-on-read: failed, timed_out.
            research_answers._settle_stale(session, answer)
            recovered += 1

        review_ids = list(
            session.scalars(
                select(Recommendation.id)
                .where(
                    Recommendation.type == "intelligent_review",
                    Recommendation.review_state == "running",
                    Recommendation.updated_at <= now - RUNNING_LEASE,
                )
                .order_by(Recommendation.updated_at.asc(), Recommendation.id.asc())
                .limit(limit)
            )
        )
        session.rollback()
        for review_id in review_ids:
            review = session.scalar(
                select(Recommendation)
                .where(
                    Recommendation.id == review_id,
                    Recommendation.review_state == "running",
                    Recommendation.updated_at <= now - RUNNING_LEASE,
                )
                .with_for_update(skip_locked=True)
            )
            if review is None:
                session.rollback()
                continue
            intelligent_reviews._mark_terminal_failure(
                session,
                review_id=review_id,
                state="failed",
                code="timed_out",
                detail="The review did not finish in time. No generated analysis was saved.",
            )
            recovered += 1

        exports = list(
            session.scalars(
                select(AuditExportJob)
                .where(
                    AuditExportJob.status == AuditExportJobStatus.RUNNING,
                    AuditExportJob.started_at.is_not(None),
                    AuditExportJob.started_at <= now - RUNNING_LEASE,
                )
                .order_by(AuditExportJob.started_at.asc(), AuditExportJob.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for job in exports:
            job.status = AuditExportJobStatus.FAILED
            job.error = "The export did not finish in time."
            job.completed_at = now
        session.commit()
        recovered += len(exports)
    return recovered


def _candidates(*, limit: int) -> list[tuple[datetime, str, str]]:
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        rows = [
            (_utc(created), "research_answer", row_id)
            for row_id, created in session.execute(
                select(ResearchAnswer.id, ResearchAnswer.created_at)
                .where(
                    ResearchAnswer.status == "queued",
                    ResearchAnswer.created_at > now - research_answers.STALE_AFTER,
                )
                .order_by(ResearchAnswer.created_at.asc(), ResearchAnswer.id.asc())
                .limit(limit)
            )
        ]
        rows += [
            (_utc(created), "intelligent_review", row_id)
            for row_id, created in session.execute(
                select(Recommendation.id, Recommendation.created_at)
                .where(
                    Recommendation.type == "intelligent_review",
                    Recommendation.review_state == "queued",
                )
                .order_by(Recommendation.created_at.asc(), Recommendation.id.asc())
                .limit(limit)
            )
        ]
        rows += [
            (_utc(created), "audit_export", row_id)
            for row_id, created in session.execute(
                select(AuditExportJob.id, AuditExportJob.created_at)
                .where(AuditExportJob.status == AuditExportJobStatus.PENDING)
                .order_by(AuditExportJob.created_at.asc(), AuditExportJob.id.asc())
                .limit(limit)
            )
        ]
    return sorted(rows)[:limit]


def _state(kind: str, row_id: str) -> str | None:
    with get_session_factory()() as session:
        if kind == "research_answer":
            return session.scalar(select(ResearchAnswer.status).where(ResearchAnswer.id == row_id))
        if kind == "intelligent_review":
            return session.scalar(
                select(Recommendation.review_state).where(Recommendation.id == row_id)
            )
        return session.scalar(select(AuditExportJob.status).where(AuditExportJob.id == row_id))


def _runners() -> dict[str, Callable[[str], bool]]:
    return {
        "research_answer": research_answers.run_research_answer_job,
        "intelligent_review": intelligent_reviews.run_intelligent_review_job,
        "audit_export": audit_exports.run_export_job,
    }


def drain_ai_jobs(
    *,
    limit: int,
    outcomes: dict[str, int] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Run up to ``limit`` queued rows, oldest first, claimed one at a time."""
    _require_batch_limit(limit)
    started = clock()
    runners = _runners()
    attempted = 0
    for _created, kind, row_id in _candidates(limit=limit):
        if clock() - started >= CLAIM_WINDOW_SECONDS:
            break
        if not runners[kind](row_id):
            continue
        attempted += 1
        if outcomes is not None:
            state = _state(kind, row_id)
            key = (
                "completed" if state in _SUCCESS[kind]
                else "failed" if state in _FAILED[kind]
                else "unfinalized"
            )
            outcomes[key] = outcomes.get(key, 0) + 1
    return attempted


__all__ = ["CLAIM_WINDOW_SECONDS", "RUNNING_LEASE", "drain_ai_jobs", "recover_stale_ai_jobs"]
