from __future__ import annotations

import hmac
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError

from caseops_api.api.dependencies import DbSession
from caseops_api.core.machine_readiness_auth import machine_readiness_signature
from caseops_api.core.settings import get_settings
from caseops_api.schemas.production_safety import (
    MachineReadinessEvidenceWriteRequest,
    MachineReadinessEvidenceWriteResponse,
)
from caseops_api.services.production_safety import record_machine_readiness_evidence

router = APIRouter()

_MAX_BODY_BYTES = 64 * 1024
_MAX_CLOCK_SKEW_SECONDS = 300


async def require_machine_readiness_evidence_auth(
    request: Request,
    timestamp: Annotated[str | None, Header(alias="X-CaseOps-Machine-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-CaseOps-Machine-Signature")] = None,
) -> MachineReadinessEvidenceWriteRequest:
    """Authenticate and parse one exact-body machine evidence envelope."""

    secret = get_settings().machine_readiness_evidence_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Machine readiness evidence ingestion is not configured.",
        )
    if not timestamp or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid machine evidence authentication is required.",
        )
    try:
        signed_at = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid machine evidence authentication is required.",
        ) from exc
    if abs(int(time.time()) - signed_at) > _MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Machine evidence authentication timestamp is stale.",
        )
    chunks: list[bytes] = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > _MAX_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Machine evidence request body is empty or too large.",
            )
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Machine evidence request body is empty or too large.",
        )
    expected = machine_readiness_signature(
        secret=secret,
        timestamp=timestamp,
        body=body,
    )
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid machine evidence authentication is required.",
        )
    try:
        payload = MachineReadinessEvidenceWriteRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Machine evidence payload is malformed.",
        ) from exc
    return payload


@router.post(
    "/evidence",
    response_model=MachineReadinessEvidenceWriteResponse,
    include_in_schema=False,
)
def write_machine_readiness_evidence(
    payload: Annotated[
        MachineReadinessEvidenceWriteRequest,
        Depends(require_machine_readiness_evidence_auth),
    ],
    session: DbSession,
) -> MachineReadinessEvidenceWriteResponse:
    """Machine-only HMAC boundary; browser and platform-admin JWTs have no authority."""

    return record_machine_readiness_evidence(session, payload=payload)
