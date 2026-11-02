"""Exact-body machine authority, not a browser or reports-admin capability."""

from __future__ import annotations

import asyncio
import hmac
import re
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from caseops_api.core.settings import get_settings
from caseops_api.services.ip_portfolio_dispatch import portfolio_export_signature
from caseops_api.services.ip_portfolio_workflow import run_portfolio_export_job

router = APIRouter()
MAX_TASK_BODY_BYTES = 1024
TASK_BODY_SECONDS = 3.0


class PortfolioExportTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    job_id: UUID


async def require_export_task(
    request: Request,
    timestamp: Annotated[str | None, Header(alias="X-CaseOps-Export-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-CaseOps-Export-Signature")] = None,
) -> PortfolioExportTask:
    secret = get_settings().portfolio_export_worker_secret
    if not secret:
        raise HTTPException(status_code=503, detail="Portfolio export worker is not configured.")
    if (
        request.headers.get("X-CaseOps-Automated-Test") != "no-paid-providers"
        or not timestamp
        or not re.fullmatch(r"[0-9]{1,14}", timestamp)
        or str(int(timestamp)) != timestamp
        or abs(int(time.time()) - int(timestamp)) > 300
        or not signature
        or not re.fullmatch(r"[a-f0-9]{64}", signature)
    ):
        raise HTTPException(
            status_code=401, detail="Valid export worker authentication is required."
        )
    body = bytearray()
    try:
        async with asyncio.timeout(TASK_BODY_SECONDS):
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_TASK_BODY_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Export task body is empty or too large.",
                    )
                body.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=408, detail="Export task body did not arrive in time."
        ) from exc
    if not body:
        raise HTTPException(status_code=413, detail="Export task body is empty or too large.")
    expected = portfolio_export_signature(secret=secret, timestamp=timestamp, body=bytes(body))
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=401, detail="Valid export worker authentication is required."
        )
    try:
        return PortfolioExportTask.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Export task body is malformed.") from exc


@router.post("/run", include_in_schema=False)
def run_export_task(payload: Annotated[PortfolioExportTask, Depends(require_export_task)]) -> dict:
    # A synchronous route runs off the event loop. The request supplies CPU
    # until durable completion; status reads never trigger this work.
    outcome = run_portfolio_export_job(str(payload.job_id))
    if outcome == "busy":
        raise HTTPException(status_code=409, detail="Export already has an active worker.")
    if outcome not in {"completed", "terminal", "missing"}:
        raise HTTPException(
            status_code=503, detail="Export worker did not return a durable outcome."
        )
    return {"accepted": True, "status": outcome}
