from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from caseops_api.api.dependencies import get_current_context, require_capability
from caseops_api.schemas.source_actions import (
    SourceActionInspectRequest,
    SourceActionRecord,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.source_actions import (
    assert_safe_source_redirect,
    inspect_source_action,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
SourceInspector = Annotated[
    SessionContext, Depends(require_capability("authorities:search"))
]


@router.post("/inspect", response_model=SourceActionRecord)
async def inspect_source(
    payload: SourceActionInspectRequest,
    context: SourceInspector,
) -> SourceActionRecord:
    del context
    return inspect_source_action(
        payload.source_reference,
        verified=payload.verified,
        quarantined=payload.quarantined,
    )


@router.get("/open", response_class=RedirectResponse)
async def open_source(
    context: CurrentContext,
    url: Annotated[str, Query(min_length=8, max_length=1000)],
) -> RedirectResponse:
    del context
    try:
        target = assert_safe_source_redirect(url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return RedirectResponse(
        target,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
