"""Conflict-check routes (PG-001)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import (
    DbSession,
    require_capability,
)
from caseops_api.schemas.conflicts import (
    ConflictCheckListResponse,
    ConflictCheckRecord,
    ConflictCheckResolveRequest,
    ConflictCheckRunRequest,
)
from caseops_api.services.conflict_checks import (
    list_conflict_checks,
    resolve_conflict_check,
    run_conflict_check,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
ConflictRunner = Annotated[
    SessionContext, Depends(require_capability("conflicts:run"))
]
ConflictResolver = Annotated[
    SessionContext, Depends(require_capability("conflicts:resolve"))
]


@router.post(
    "/matters/{matter_id}/conflict-checks",
    response_model=ConflictCheckRecord,
    summary="Run a fresh conflict-of-interest scan on a matter",
)
async def post_matter_conflict_check(
    matter_id: str,
    payload: ConflictCheckRunRequest,
    context: ConflictRunner,
    session: DbSession,
) -> ConflictCheckRecord:
    return run_conflict_check(
        session, context=context, matter_id=matter_id, payload=payload,
    )


@router.get(
    "/matters/{matter_id}/conflict-checks",
    response_model=ConflictCheckListResponse,
    summary="List conflict checks recorded against a matter",
)
async def get_matter_conflict_checks(
    matter_id: str,
    context: ConflictRunner,
    session: DbSession,
) -> ConflictCheckListResponse:
    checks = list_conflict_checks(
        session, context=context, matter_id=matter_id,
    )
    return ConflictCheckListResponse(matter_id=matter_id, checks=checks)


@router.patch(
    "/conflict-checks/{check_id}",
    response_model=ConflictCheckRecord,
    summary="Resolve a pending conflict check (cleared / conflicted / waived)",
)
async def patch_conflict_check(
    check_id: str,
    payload: ConflictCheckResolveRequest,
    context: ConflictResolver,
    session: DbSession,
) -> ConflictCheckRecord:
    return resolve_conflict_check(
        session, context=context, check_id=check_id, payload=payload,
    )
