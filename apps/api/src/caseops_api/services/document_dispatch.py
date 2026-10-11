"""Wake the durable document queue without doing production work after a response."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable

import httpx
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from caseops_api.core.settings import Settings, get_settings, is_non_local_env
from caseops_api.services.document_jobs import run_document_processing_job
from caseops_api.services.matter_write_fence import require_read_only_upload_session

logger = logging.getLogger(__name__)
DISPATCH_BUDGET_SECONDS = 3.0
PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,61}[a-z0-9]")


async def _wake_cloud_run_queue(*, project: str, region: str, job: str) -> bool:
    try:
        # The deadline covers metadata and headers without SDK backoff or
        # detached transport continuing after returning to the caller.
        async with asyncio.timeout(DISPATCH_BUDGET_SECONDS):
            async with httpx.AsyncClient(
                timeout=DISPATCH_BUDGET_SECONDS, follow_redirects=False, trust_env=False,
            ) as transport:
                async with transport.stream(
                    "GET",
                    "http://metadata.google.internal/computeMetadata/v1/"
                    "instance/service-accounts/default/token",
                    headers={"Metadata-Flavor": "Google"},
                ) as metadata:
                    if metadata.status_code != 200:
                        return False
                    token_bytes = bytearray()
                    async for chunk in metadata.aiter_bytes():
                        if len(token_bytes) + len(chunk) > 16_384:
                            return False
                        token_bytes.extend(chunk)
                    payload = json.loads(token_bytes)
                token = payload.get("access_token") if isinstance(payload, dict) else None
                if (not isinstance(token, str) or not 1 <= len(token) <= 4096
                        or any(ord(char) < 33 or ord(char) > 126 for char in token)):
                    return False
                async with transport.stream(
                    "POST",
                    f"https://run.googleapis.com/v2/projects/{project}/locations/{region}"
                    f"/jobs/{job}:run",
                    headers={"Authorization": f"Bearer {token}"}, json={},
                ) as response:
                    # No overrides, polling, response body or mutation retry.
                    return response.status_code in {200, 202}
    except Exception:
        # Admission is already durable. The bounded scheduled drain also wakes
        # this queue after a timeout, denied kick, or process crash.
        return False


def dispatch_document_processing_job(
    *,
    session: Session,
    background_tasks: BackgroundTasks,
    job_id: str,
) -> None:
    settings = get_settings()
    _dispatch_processing_job(
        session=session, background_tasks=background_tasks, job_id=job_id, settings=settings,
        mode=settings.document_processing_dispatch_mode,
        region=settings.document_processing_run_region, job=settings.document_processing_run_job,
        runner=run_document_processing_job,
    )


def dispatch_court_sync_processing_job(
    *, session: Session, background_tasks: BackgroundTasks, job_id: str,
) -> None:
    from caseops_api.services.court_sync_jobs import run_matter_court_sync_job

    settings = get_settings()
    _dispatch_processing_job(
        session=session, background_tasks=background_tasks, job_id=job_id, settings=settings,
        mode=settings.court_sync_dispatch_mode,
        region=settings.court_sync_run_region, job=settings.court_sync_run_job,
        runner=run_matter_court_sync_job,
    )


def _dispatch_processing_job(
    *, session: Session, background_tasks: BackgroundTasks, job_id: str,
    settings: Settings, mode: str, region: str, job: str, runner: Callable[[str], object],
) -> None:
    require_read_only_upload_session(
        session, detail="Processing admission must be committed before dispatch.",
    )
    session.rollback()
    if mode == "local_background":
        if is_non_local_env(settings.env):
            logger.error("CASEOPS_DOCUMENT_DISPATCH mode_unavailable; work remains queued")
            return
        background_tasks.add_task(runner, job_id)
        return
    project = settings.gcp_project_id or ""
    if not PROJECT_ID.fullmatch(project):
        logger.error("CASEOPS_DOCUMENT_DISPATCH invalid_project; work remains queued")
        return
    if not asyncio.run(_wake_cloud_run_queue(
        project=project,
        region=region,
        job=job,
    )):
        logger.warning("CASEOPS_DOCUMENT_DISPATCH wake_unavailable; work remains queued")
