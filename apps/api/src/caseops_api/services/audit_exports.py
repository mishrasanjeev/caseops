"""Async audit export jobs (§10.4).

Pipeline:

1. ``enqueue_export`` creates an ``AuditExportJob`` row in the caller's
   tenant (status=pending) and returns it.
2. ``run_export_job`` is the worker body. It is callable from a
   FastAPI ``BackgroundTask`` (today), a separate ``caseops-audit-
   exporter`` CLI (for Cloud Run Jobs), or a Temporal activity
   (future §5.1). Each call looks up the job, runs the export in the
   caller-supplied format, writes the artifact via the document
   storage backend, and stamps ``completed_at`` / ``size_bytes`` /
   ``row_count`` on the row. Errors land in the ``error`` column and
   flip status to ``failed``.
3. ``read_export_bytes`` streams the artifact for the download route;
   it reuses the same storage resolution as matter attachments.

The point of holding the state in Postgres is that the worker choice
is a runtime decision — swapping BackgroundTasks for Cloud Tasks or
Temporal is not a schema migration.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Iterator, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    AuditExportJob,
    AuditExportJobStatus,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.audit import record_from_context
from caseops_api.services.document_storage import (
    persist_workspace_attachment,
    resolve_storage_path,
)
from caseops_api.services.identity import SessionContext


logger = logging.getLogger(__name__)


FormatLiteral = Literal["jsonl", "csv"]


_CSV_COLUMNS = [
    "id",
    "created_at",
    "company_id",
    "actor_type",
    "actor_membership_id",
    "actor_label",
    "matter_id",
    "action",
    "target_type",
    "target_id",
    "result",
    "metadata",
    "request_id",
]


def _event_dict(event: AuditEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "created_at": event.created_at.isoformat(),
        "company_id": event.company_id,
        "actor_type": event.actor_type,
        "actor_membership_id": event.actor_membership_id,
        "actor_label": event.actor_label,
        "matter_id": event.matter_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "result": event.result,
        "metadata": (
            json.loads(event.metadata_json) if event.metadata_json else None
        ),
        "request_id": event.request_id,
    }


def enqueue_export(
    session: Session,
    *,
    context: SessionContext,
    fmt: FormatLiteral = "jsonl",
    since: datetime | None = None,
    until: datetime | None = None,
    action_filter: str | None = None,
    row_limit: int | None = None,
) -> AuditExportJob:
    job = AuditExportJob(
        company_id=context.company.id,
        requested_by_membership_id=context.membership.id,
        status=AuditExportJobStatus.PENDING,
        format=fmt,
        since=since,
        until=until,
        action_filter=action_filter,
        row_limit=row_limit,
    )
    session.add(job)
    session.flush()
    record_from_context(
        session,
        context,
        action="audit.export.enqueued",
        target_type="audit_export_job",
        target_id=job.id,
        metadata={
            "format": fmt,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "action_filter": action_filter,
            "row_limit": row_limit,
        },
        commit=True,
    )
    return job


def get_export_job(
    session: Session, *, context: SessionContext, job_id: str
) -> AuditExportJob:
    job = session.get(AuditExportJob, job_id)
    if job is None or job.company_id != context.company.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audit export job not found.",
        )
    return job


def list_export_jobs(
    session: Session, *, context: SessionContext, limit: int = 25
) -> list[AuditExportJob]:
    return list(
        session.scalars(
            select(AuditExportJob)
            .where(AuditExportJob.company_id == context.company.id)
            .order_by(AuditExportJob.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    )


def read_export_bytes(job: AuditExportJob) -> Iterator[bytes]:
    """Stream the completed artifact from storage. Caller verifies the
    job belongs to the tenant *before* calling this."""
    if job.status != AuditExportJobStatus.COMPLETED or not job.storage_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Audit export job is in status {job.status!r}; "
                "download is only available once status is 'completed'."
            ),
        )
    path = resolve_storage_path(job.storage_key)
    if not Path(path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export artifact is missing on storage.",
        )
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(64 * 1024)
            if not chunk:
                return
            yield chunk


# ---------------------------------------------------------------------------
# Worker body
# ---------------------------------------------------------------------------


def _iter_events_jsonl(events: list[AuditEvent]) -> Iterator[bytes]:
    for event in events:
        yield (json.dumps(_event_dict(event), separators=(",", ":")) + "\n").encode(
            "utf-8"
        )


def _iter_events_csv(events: list[AuditEvent]) -> Iterator[bytes]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    yield buffer.getvalue().encode("utf-8")
    for event in events:
        buffer.seek(0)
        buffer.truncate()
        row = _event_dict(event)
        row["metadata"] = (
            json.dumps(row["metadata"], separators=(",", ":"))
            if row["metadata"] is not None
            else ""
        )
        writer.writerow(row)
        yield buffer.getvalue().encode("utf-8")


class _BytesIterStream(io.RawIOBase):
    """Adapter: let ``persist_workspace_attachment`` consume a byte
    generator as if it were a stream. Writes all bytes into a
    ``BytesIO`` and exposes its interface — fine for exports up to
    tenant-reasonable sizes (MBs, not GBs) on Cloud Run. For GB-scale
    the worker CLI variant uploads a temp file directly.
    """

    def __init__(self, gen: Iterator[bytes]) -> None:
        super().__init__()
        self._buffer = io.BytesIO()
        self._bytes_written = 0
        for chunk in gen:
            self._buffer.write(chunk)
            self._bytes_written += len(chunk)
        self._buffer.seek(0)

    def read(self, size: int = -1) -> bytes:  # type: ignore[override]
        return self._buffer.read(size)

    def readable(self) -> bool:  # type: ignore[override]
        return True

    def seek(self, offset: int, whence: int = 0) -> int:  # type: ignore[override]
        return self._buffer.seek(offset, whence)

    def tell(self) -> int:  # type: ignore[override]
        return self._buffer.tell()

    @property
    def size_bytes(self) -> int:
        return self._bytes_written


def run_export_job(job_id: str) -> None:
    """Worker body. Opens its own session so the caller can schedule
    this as a FastAPI BackgroundTask, from a worker CLI, or from a
    Temporal activity.
    """
    Session = get_session_factory()
    with Session() as session:
        job = session.get(AuditExportJob, job_id)
        if job is None:
            logger.warning("audit export job %s vanished before run", job_id)
            return
        if job.status not in {
            AuditExportJobStatus.PENDING,
            AuditExportJobStatus.FAILED,
        }:
            logger.info(
                "audit export job %s is in status %s; skipping run",
                job.id,
                job.status,
            )
            return
        job.status = AuditExportJobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.error = None
        session.commit()

        try:
            stmt = (
                select(AuditEvent)
                .where(AuditEvent.company_id == job.company_id)
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            )
            if job.since is not None:
                stmt = stmt.where(AuditEvent.created_at >= job.since)
            if job.until is not None:
                stmt = stmt.where(AuditEvent.created_at <= job.until)
            if job.action_filter:
                stmt = stmt.where(AuditEvent.action == job.action_filter)
            if job.row_limit:
                stmt = stmt.limit(min(job.row_limit, 500_000))

            events = list(session.scalars(stmt))
            fmt = (job.format or "jsonl").lower()
            if fmt == "csv":
                gen = _iter_events_csv(events)
                ext = "csv"
            else:
                gen = _iter_events_jsonl(events)
                ext = "jsonl"

            stream = _BytesIterStream(gen)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            filename = f"audit-{stamp}.{ext}"
            stored = persist_workspace_attachment(
                company_id=job.company_id,
                workspace_id="audit-exports",
                attachment_id=job.id,
                filename=filename,
                stream=stream,
                namespace="exports",
            )

            job.storage_key = stored.storage_key
            job.size_bytes = stored.size_bytes
            job.row_count = len(events)
            job.status = AuditExportJobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("audit export job %s failed", job.id)
            job.status = AuditExportJobStatus.FAILED
            job.error = str(exc)[:1800]
            job.completed_at = datetime.now(UTC)
            session.commit()


__all__ = [
    "FormatLiteral",
    "enqueue_export",
    "get_export_job",
    "list_export_jobs",
    "read_export_bytes",
    "run_export_job",
]
