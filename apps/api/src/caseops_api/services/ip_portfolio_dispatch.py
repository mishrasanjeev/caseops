"""Durably admit export work before dispatch; production never works after a response."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time

import httpx
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.services.matter_write_fence import require_read_only_upload_session

logger = logging.getLogger(__name__)
DISPATCH_BUDGET_SECONDS = 3.0
PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,61}[a-z0-9]")
TASK_SIGNATURE_CONTEXT = b"caseops.portfolio-export-worker/v1"
NO_PAID_HEADERS = {"X-CaseOps-Automated-Test": "no-paid-providers"}


def portfolio_export_signature(*, secret: str, timestamp: str, body: bytes) -> str:
    value = b"\n".join((TASK_SIGNATURE_CONTEXT, timestamp.encode("ascii"), body))
    return hmac.new(secret.encode(), value, hashlib.sha256).hexdigest()


def require_portfolio_export_dispatch_ready() -> None:
    settings = get_settings()
    if settings.portfolio_export_dispatch_mode == "local_background":
        if not is_non_local_env(settings.env):
            return
    elif settings.portfolio_export_worker_secret and PROJECT_ID.fullmatch(
        settings.gcp_project_id or ""
    ):
        return
    raise HTTPException(status_code=503, detail="Portfolio export processing is not configured.")


async def dispatch_portfolio_export(
    *,
    session: Session,
    background_tasks: BackgroundTasks,
    job_id: str,
) -> bool:
    from caseops_api.services.ip_portfolio_workflow import run_portfolio_export_job

    require_portfolio_export_dispatch_ready()
    require_read_only_upload_session(
        session, detail="Export admission must be committed before dispatch."
    )
    session.rollback()
    settings = get_settings()
    if settings.portfolio_export_dispatch_mode == "local_background":
        background_tasks.add_task(run_portfolio_export_job, job_id)
        return True

    timestamp = str(int(time.time()))
    body = json.dumps({"version": 1, "job_id": job_id}, separators=(",", ":")).encode()
    signature = portfolio_export_signature(
        secret=settings.portfolio_export_worker_secret or "",
        timestamp=timestamp,
        body=body,
    )
    parent = (
        f"projects/{settings.gcp_project_id}/locations/{settings.portfolio_export_task_region}"
        f"/queues/{settings.portfolio_export_task_queue}"
    )
    task = {
        "task": {
            "httpRequest": {
                "httpMethod": "POST",
                "url": settings.portfolio_export_task_url,
                "headers": {
                    **NO_PAID_HEADERS,
                    "Content-Type": "application/json",
                    "X-CaseOps-Export-Timestamp": timestamp,
                    "X-CaseOps-Export-Signature": signature,
                },
                "body": base64.b64encode(body).decode("ascii"),
            },
            "dispatchDeadline": "120s",
        }
    }
    try:
        async with asyncio.timeout(DISPATCH_BUDGET_SECONDS):
            async with httpx.AsyncClient(
                timeout=DISPATCH_BUDGET_SECONDS,
                follow_redirects=False,
                trust_env=False,
            ) as transport:
                async with transport.stream(
                    "GET",
                    "http://metadata.google.internal/computeMetadata/v1/"
                    "instance/service-accounts/default/token",
                    headers={**NO_PAID_HEADERS, "Metadata-Flavor": "Google"},
                ) as metadata:
                    if metadata.status_code != 200:
                        return False
                    raw = bytearray()
                    async for chunk in metadata.aiter_bytes():
                        if len(raw) + len(chunk) > 16_384:
                            return False
                        raw.extend(chunk)
                    envelope = json.loads(raw)
                token = envelope.get("access_token") if isinstance(envelope, dict) else None
                if (
                    not isinstance(token, str)
                    or not 1 <= len(token) <= 4096
                    or any(ord(char) < 33 or ord(char) > 126 for char in token)
                ):
                    return False
                async with transport.stream(
                    "POST",
                    f"https://cloudtasks.googleapis.com/v2/{parent}/tasks",
                    headers={**NO_PAID_HEADERS, "Authorization": f"Bearer {token}"},
                    json=task,
                ) as response:
                    admitted = response.status_code in {200, 201}
                    if not admitted:
                        logger.warning(
                            "CASEOPS_PORTFOLIO_DISPATCH wake_unavailable; "
                            "durable work remains queued"
                        )
                    return admitted
    except Exception:
        logger.warning("CASEOPS_PORTFOLIO_DISPATCH wake_unavailable; durable work remains queued")
        return False
