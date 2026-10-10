from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.db.migrations import run_migrations
from caseops_api.services.case_tracking_summary import drain_update_summaries
from caseops_api.services.court_sync_jobs import (
    drain_matter_court_sync_jobs,
    recover_stale_matter_court_sync_jobs,
)
from caseops_api.services.document_jobs import (
    drain_document_processing_jobs,
    enqueue_scheduled_document_reprocessing,
    recover_stale_document_processing_jobs,
)

DOCUMENT_WORKER_ADMISSION_PROTOCOL_VERSION = 1


@dataclass(slots=True)
class WorkerRunSummary:
    recovered_stale_jobs: int
    queued_reprocessing_jobs: int
    processed_jobs: int
    recovered_stale_court_sync_jobs: int
    processed_court_sync_jobs: int
    processed_case_summaries: int = 0

    @property
    def touched_any_work(self) -> bool:
        return (
            self.recovered_stale_jobs > 0
            or self.queued_reprocessing_jobs > 0
            or self.processed_jobs > 0
            or self.recovered_stale_court_sync_jobs > 0
            or self.processed_court_sync_jobs > 0
            or self.processed_case_summaries > 0
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
    summary_batch_size: int = 5,
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
        processed_case_summaries=drain_update_summaries(limit=summary_batch_size),
    )


def _build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="caseops-document-worker",
        description="Drain CaseOps document processing jobs and schedule maintenance reprocessing.",
    )
    parser.add_argument("--once", action="store_true", help="Run one iteration and exit.")
    parser.add_argument(
        "--documents-only", action="store_true",
        help="Recover bounded expired document claims and drain documents only; requires --once.",
    )
    parser.add_argument(
        "--admission-disabled", action="store_true",
        help="Exit without database work; requires --documents-only.",
    )
    parser.add_argument("--summary-batch-size", type=int, choices=range(1, 26), default=5,
                        help="Maximum case update summaries per iteration.")
    parser.add_argument(
        "--batch-size",
        type=int,
        choices=range(1, 101),
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
    if args.documents_only and not args.once:
        parser.error("--documents-only requires --once")
    if args.admission_disabled and not args.documents_only:
        parser.error("--admission-disabled requires --documents-only")

    if args.documents_only:
        protocol = getattr(settings, "document_worker_admission_protocol_version", 0)
        admission = getattr(settings, "document_worker_admission_enabled", None)
        if protocol not in (0, DOCUMENT_WORKER_ADMISSION_PROTOCOL_VERSION):
            parser.error("unsupported document worker admission protocol")
        # Old binaries ignore the gate; deployment must retire them before enabling claims.
        if is_non_local_env(settings.env) and (
            protocol != DOCUMENT_WORKER_ADMISSION_PROTOCOL_VERSION or admission is None
        ):
            parser.error("non-local document worker requires explicit admission and protocol 1")
        if args.admission_disabled or admission is False:
            print(
                "CaseOps document worker: admission_protocol=1 admission=disabled "
                "recovered=0 queued=0 attempted=0 completed=0 failed=0 unfinalized=0 "
                "court_sync_recovered=0 court_sync_processed=0 case_summaries_processed=0",
                flush=True,
            )
            return 0

    if settings.auto_migrate and not args.skip_migrations and not args.documents_only:
        run_migrations()

    while True:
        document_outcomes: dict[str, int] = {}
        if args.documents_only:
            summary = WorkerRunSummary(
                recovered_stale_jobs=recover_stale_document_processing_jobs(
                    stale_after_minutes=15, limit=args.batch_size,
                ),
                queued_reprocessing_jobs=0,
                processed_jobs=drain_document_processing_jobs(
                    limit=args.batch_size, outcomes=document_outcomes,
                ),
                recovered_stale_court_sync_jobs=0, processed_court_sync_jobs=0,
            )
        elif args.skip_maintenance:
            summary = WorkerRunSummary(
                recovered_stale_jobs=0,
                queued_reprocessing_jobs=0,
                processed_jobs=drain_document_processing_jobs(limit=args.batch_size),
                recovered_stale_court_sync_jobs=0,
                processed_court_sync_jobs=drain_matter_court_sync_jobs(
                    limit=args.court_sync_batch_size
                ),
                processed_case_summaries=drain_update_summaries(limit=args.summary_batch_size),
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
                summary_batch_size=args.summary_batch_size,
            )

        document_counts = (
            f"attempted={summary.processed_jobs} "
            f"completed={document_outcomes.get('completed', 0)} "
            f"failed={document_outcomes.get('failed', 0)} "
            f"unfinalized={document_outcomes.get('unfinalized', 0)} "
            if args.documents_only else f"processed={summary.processed_jobs} "
        )
        admission_receipt = (
            "admission_protocol=1 admission=enabled " if args.documents_only else ""
        )
        print(
            "CaseOps document worker: "
            f"{admission_receipt}"
            f"recovered={summary.recovered_stale_jobs} "
            f"queued={summary.queued_reprocessing_jobs} "
            f"{document_counts}"
            f"court_sync_recovered={summary.recovered_stale_court_sync_jobs} "
            f"court_sync_processed={summary.processed_court_sync_jobs} "
            f"case_summaries_processed={summary.processed_case_summaries}",
            flush=True,
        )

        if args.once:
            return 0

        if not summary.touched_any_work:
            time.sleep(args.poll_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
