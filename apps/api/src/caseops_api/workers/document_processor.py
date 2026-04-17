from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from caseops_api.core.settings import get_settings
from caseops_api.db.migrations import run_migrations
from caseops_api.services.court_sync_jobs import (
    drain_matter_court_sync_jobs,
    recover_stale_matter_court_sync_jobs,
)
from caseops_api.services.document_jobs import (
    drain_document_processing_jobs,
    enqueue_scheduled_document_reprocessing,
    recover_stale_document_processing_jobs,
)


@dataclass(slots=True)
class WorkerRunSummary:
    recovered_stale_jobs: int
    queued_reprocessing_jobs: int
    processed_jobs: int
    recovered_stale_court_sync_jobs: int
    processed_court_sync_jobs: int

    @property
    def touched_any_work(self) -> bool:
        return (
            self.recovered_stale_jobs > 0
            or self.queued_reprocessing_jobs > 0
            or self.processed_jobs > 0
            or self.recovered_stale_court_sync_jobs > 0
            or self.processed_court_sync_jobs > 0
        )


def run_worker_iteration(
    *,
    batch_size: int,
    stale_after_minutes: int,
    retry_after_hours: int,
    reindex_after_hours: int,
    reprocessing_batch_size: int,
    court_sync_batch_size: int,
    court_sync_stale_after_minutes: int,
) -> WorkerRunSummary:
    recovered_stale_jobs = recover_stale_document_processing_jobs(
        stale_after_minutes=stale_after_minutes
    )
    recovered_stale_court_sync_jobs = recover_stale_matter_court_sync_jobs(
        stale_after_minutes=court_sync_stale_after_minutes
    )
    queued_reprocessing_jobs = enqueue_scheduled_document_reprocessing(
        limit=reprocessing_batch_size,
        retry_after_hours=retry_after_hours,
        reindex_after_hours=reindex_after_hours,
    )
    processed_jobs = drain_document_processing_jobs(limit=batch_size)
    processed_court_sync_jobs = drain_matter_court_sync_jobs(limit=court_sync_batch_size)
    return WorkerRunSummary(
        recovered_stale_jobs=recovered_stale_jobs,
        queued_reprocessing_jobs=queued_reprocessing_jobs,
        processed_jobs=processed_jobs,
        recovered_stale_court_sync_jobs=recovered_stale_court_sync_jobs,
        processed_court_sync_jobs=processed_court_sync_jobs,
    )


def _build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="caseops-document-worker",
        description="Drain CaseOps document processing jobs and schedule maintenance reprocessing.",
    )
    parser.add_argument("--once", action="store_true", help="Run one iteration and exit.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.document_worker_batch_size,
        help="Maximum queued jobs to process per iteration.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=settings.document_worker_poll_interval_seconds,
        help="Sleep interval between iterations when running continuously.",
    )
    parser.add_argument(
        "--stale-after-minutes",
        type=int,
        default=settings.document_processing_stale_after_minutes,
        help="Requeue jobs stuck in processing longer than this threshold.",
    )
    parser.add_argument(
        "--retry-after-hours",
        type=int,
        default=settings.document_retry_after_hours,
        help="Auto-queue retry jobs for failed or OCR-needed attachments older than this.",
    )
    parser.add_argument(
        "--reindex-after-hours",
        type=int,
        default=settings.document_reindex_after_hours,
        help="Auto-queue reindex jobs for indexed attachments older than this.",
    )
    parser.add_argument(
        "--reprocessing-batch-size",
        type=int,
        default=settings.document_reprocessing_batch_size,
        help="Maximum scheduled retry or reindex jobs to enqueue per iteration.",
    )
    parser.add_argument(
        "--skip-maintenance",
        action="store_true",
        help="Only drain queued jobs; skip stale recovery and scheduled reprocessing.",
    )
    parser.add_argument(
        "--court-sync-batch-size",
        type=int,
        default=settings.court_sync_worker_batch_size,
        help="Maximum queued court sync jobs to process per iteration.",
    )
    parser.add_argument(
        "--court-sync-stale-after-minutes",
        type=int,
        default=settings.court_sync_stale_after_minutes,
        help="Requeue court sync jobs stuck in processing beyond this threshold.",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Do not auto-run database migrations before starting the worker.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()

    if settings.auto_migrate and not args.skip_migrations:
        run_migrations()

    while True:
        if args.skip_maintenance:
            summary = WorkerRunSummary(
                recovered_stale_jobs=0,
                queued_reprocessing_jobs=0,
                processed_jobs=drain_document_processing_jobs(limit=args.batch_size),
                recovered_stale_court_sync_jobs=0,
                processed_court_sync_jobs=drain_matter_court_sync_jobs(
                    limit=args.court_sync_batch_size
                ),
            )
        else:
            summary = run_worker_iteration(
                batch_size=args.batch_size,
                stale_after_minutes=args.stale_after_minutes,
                retry_after_hours=args.retry_after_hours,
                reindex_after_hours=args.reindex_after_hours,
                reprocessing_batch_size=args.reprocessing_batch_size,
                court_sync_batch_size=args.court_sync_batch_size,
                court_sync_stale_after_minutes=args.court_sync_stale_after_minutes,
            )

        print(
            "CaseOps document worker: "
            f"recovered={summary.recovered_stale_jobs} "
            f"queued={summary.queued_reprocessing_jobs} "
            f"processed={summary.processed_jobs} "
            f"court_sync_recovered={summary.recovered_stale_court_sync_jobs} "
            f"court_sync_processed={summary.processed_court_sync_jobs}",
            flush=True,
        )

        if args.once:
            return 0

        if not summary.touched_any_work:
            time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
