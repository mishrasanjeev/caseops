from __future__ import annotations

import time

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import Company, DocumentProcessingJob, DocumentProcessingJobStatus
from caseops_api.db.session import get_session_factory

QA_SLUGS = frozenset({"caseops-qa", "caseops-ip-qa", "test-legal"})
QUIESCENCE_TIMEOUT_SECONDS = 300
POLL_SECONDS = 2


def pending_document_jobs(session: Session, company_ids: tuple[str, ...]) -> bool:
    if (
        not 1 <= len(company_ids) <= len(QA_SLUGS)
        or any(not isinstance(value, str) or not value for value in company_ids)
        or len(set(company_ids)) != len(company_ids)
    ):
        raise ValueError("invalid_document_queue_scope")
    return (
        session.scalar(
            select(DocumentProcessingJob.id)
            .where(
                DocumentProcessingJob.company_id.in_(company_ids),
                DocumentProcessingJob.status.in_(
                    (DocumentProcessingJobStatus.QUEUED, DocumentProcessingJobStatus.PROCESSING),
                ),
            )
            .limit(1),
        )
        is not None
    )


def _pending_snapshot() -> tuple[tuple[str, ...], bool]:
    with get_session_factory()() as session:
        try:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = '5000ms'"))
                session.execute(text("SET LOCAL lock_timeout = '2000ms'"))
            companies = list(
                session.execute(
                    select(Company.id, Company.slug)
                    .where(
                        Company.slug.in_(QA_SLUGS),
                        Company.is_active.is_(True),
                    )
                    .order_by(Company.id)
                    .limit(len(QA_SLUGS) + 1),
                )
            )
            if {row.slug for row in companies} != QA_SLUGS or len(companies) != len(QA_SLUGS):
                raise RuntimeError("qa_document_tenant_inventory_changed")
            ids = tuple(row.id for row in companies)
            pending = pending_document_jobs(session, ids)
            return ids, pending
        finally:
            session.rollback()


def wait_for_qa_document_quiescence() -> dict[str, int | str]:
    """Observe the fixed QA queues without claiming, retrying or modifying work."""
    started = time.monotonic()
    deadline = started + QUIESCENCE_TIMEOUT_SECONDS
    stable = 0
    polls = 0
    inventory: tuple[str, ...] | None = None
    while time.monotonic() < deadline:
        current, pending = _pending_snapshot()
        polls += 1
        if inventory is not None and current != inventory:
            raise RuntimeError("qa_document_tenant_inventory_changed")
        inventory = current
        stable = 0 if pending else stable + 1
        if stable == 2 and time.monotonic() < deadline:
            return {
                "schema_version": 1,
                "status": "ok",
                "company_count": len(QA_SLUGS),
                "stable_observations": stable,
                "polls": polls,
                "elapsed_seconds": int(time.monotonic() - started),
            }
        # The snapshot session is closed before waiting for the normal worker.
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(POLL_SECONDS, remaining))
    raise RuntimeError("qa_document_queue_not_quiescent")
