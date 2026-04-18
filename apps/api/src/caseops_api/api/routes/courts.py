"""Court / Bench / Judge read-only routes (§7.1).

v1 is read-only. Admin workflows for adding custom courts / benches /
judges per tenant come later — there's no product need until a firm
has a matter in a court we haven't catalogued, and when that happens
the `Matter.court_name` freeform column still works.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.db.models import Court, Judge
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


class CourtRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    short_name: str
    forum_level: str
    jurisdiction: str | None
    seat_city: str | None
    hc_catalog_key: str | None
    is_active: bool
    created_at: datetime


class JudgeRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    court_id: str
    full_name: str
    honorific: str | None
    current_position: str | None
    is_active: bool


class CourtsListResponse(BaseModel):
    courts: list[CourtRecord]


class JudgesListResponse(BaseModel):
    court_id: str
    judges: list[JudgeRecord]


@router.get(
    "/",
    response_model=CourtsListResponse,
    summary="List every court the catalog knows about",
)
def list_courts(
    context: CurrentContext,
    session: DbSession,
    forum_level: str | None = None,
) -> CourtsListResponse:
    # The context is consumed only to enforce the auth check — every
    # authenticated user can browse the master catalog. Kept as an
    # explicit parameter so the role-guard sweep sees a SessionContext
    # dependency on the route.
    _ = context
    stmt = select(Court).where(Court.is_active.is_(True)).order_by(
        Court.forum_level, Court.name
    )
    if forum_level:
        stmt = stmt.where(Court.forum_level == forum_level)
    courts = list(session.scalars(stmt))
    return CourtsListResponse(
        courts=[CourtRecord.model_validate(court) for court in courts],
    )


@router.get(
    "/{court_id}/judges",
    response_model=JudgesListResponse,
    summary="List judges recorded against the given court",
)
def list_court_judges(
    court_id: str,
    context: CurrentContext,
    session: DbSession,
) -> JudgesListResponse:
    _ = context
    judges = list(
        session.scalars(
            select(Judge)
            .where(Judge.court_id == court_id, Judge.is_active.is_(True))
            .order_by(Judge.full_name)
        )
    )
    return JudgesListResponse(
        court_id=court_id,
        judges=[JudgeRecord.model_validate(judge) for judge in judges],
    )
