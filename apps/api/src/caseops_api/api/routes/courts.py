"""Court / Bench / Judge read-only routes (§7.1).

v1 is read-only. Admin workflows for adding custom courts / benches /
judges per tenant come later — there's no product need until a firm
has a matter in a court we haven't catalogued, and when that happens
the `Matter.court_name` freeform column still works.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.db.models import AuthorityDocument, Court, Judge, Matter
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


# --- Sprint 9 BG-024: court profile ------------------------------------


class AuthorityStub(BaseModel):
    id: str
    title: str
    decision_date: str | None
    case_reference: str | None
    neutral_citation: str | None


class CourtProfileResponse(BaseModel):
    court: CourtRecord
    judges: list[JudgeRecord]
    portfolio_matter_count: int
    authority_document_count: int
    recent_authorities: list[AuthorityStub]


class JudgeProfileResponse(BaseModel):
    judge: JudgeRecord
    court: CourtRecord
    portfolio_matter_count: int
    authority_document_count: int
    recent_authorities: list[AuthorityStub]


# Declared BEFORE the catch-all /{court_id} route so FastAPI's
# in-order matching picks "judges" as a literal segment instead of
# treating it as a court id.
@router.get(
    "/judges/{judge_id}",
    response_model=JudgeProfileResponse,
    summary="Judge profile — court, your matters before this judge, recent authorities",
)
def get_judge_profile(
    judge_id: str,
    context: CurrentContext,
    session: DbSession,
) -> JudgeProfileResponse:
    judge = session.scalar(select(Judge).where(Judge.id == judge_id))
    if judge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Judge not found."
        )
    court = session.scalar(select(Court).where(Court.id == judge.court_id))
    if court is None:
        # Defensive — Judge.court_id is a FK with ON DELETE CASCADE,
        # so an orphan judge means a manual data drift, not a normal
        # state. Surface as 404 rather than 500.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Court for judge not found."
        )
    # Tenant matters where this judge appears in the freeform field. We
    # don't have a FK (the matter judge_name is human-typed) so this is
    # an exact-string match — close enough for the v1 profile.
    portfolio_count = (
        session.scalar(
            select(func.count())
            .select_from(Matter)
            .where(Matter.company_id == context.company.id)
            .where(Matter.judge_name == judge.full_name)
        )
        or 0
    )
    # Authorities where the judge sat on the bench. AuthorityDocument
    # carries a freeform bench_name like "S Abdul Nazeer, J., et al" —
    # an ILIKE on the surname is the v1 heuristic. Costs no schema
    # change; can swap for a structured judge-citation table later.
    authority_filter = AuthorityDocument.bench_name.ilike(f"%{judge.full_name}%")
    authority_count = (
        session.scalar(
            select(func.count())
            .select_from(AuthorityDocument)
            .where(authority_filter)
        )
        or 0
    )
    recent_authorities = list(
        session.execute(
            select(
                AuthorityDocument.id,
                AuthorityDocument.title,
                AuthorityDocument.decision_date,
                AuthorityDocument.case_reference,
                AuthorityDocument.neutral_citation,
            )
            .where(authority_filter)
            .order_by(AuthorityDocument.decision_date.desc().nulls_last())
            .limit(10)
        ).all()
    )
    return JudgeProfileResponse(
        judge=JudgeRecord.model_validate(judge),
        court=CourtRecord.model_validate(court),
        portfolio_matter_count=int(portfolio_count),
        authority_document_count=int(authority_count),
        recent_authorities=[
            AuthorityStub(
                id=row.id,
                title=row.title,
                decision_date=row.decision_date.isoformat() if row.decision_date else None,
                case_reference=row.case_reference,
                neutral_citation=row.neutral_citation,
            )
            for row in recent_authorities
        ],
    )


@router.get(
    "/{court_id}",
    response_model=CourtProfileResponse,
    summary="Court profile — judges + portfolio matters + recent authorities",
)
def get_court_profile(
    court_id: str,
    context: CurrentContext,
    session: DbSession,
) -> CourtProfileResponse:
    court = session.scalar(select(Court).where(Court.id == court_id))
    if court is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Court not found."
        )
    judges = list(
        session.scalars(
            select(Judge)
            .where(Judge.court_id == court_id, Judge.is_active.is_(True))
            .order_by(Judge.full_name)
        )
    )
    # Matters from this tenant's portfolio that reference the court —
    # either via the structured FK or the freeform court_name fallback.
    portfolio_count = (
        session.scalar(
            select(func.count())
            .select_from(Matter)
            .where(Matter.company_id == context.company.id)
            .where(
                (Matter.court_id == court.id)
                | (Matter.court_name == court.name)
            )
        )
        or 0
    )
    authority_count = (
        session.scalar(
            select(func.count())
            .select_from(AuthorityDocument)
            .where(AuthorityDocument.court_name == court.name)
        )
        or 0
    )
    recent_authorities = list(
        session.execute(
            select(
                AuthorityDocument.id,
                AuthorityDocument.title,
                AuthorityDocument.decision_date,
                AuthorityDocument.case_reference,
                AuthorityDocument.neutral_citation,
            )
            .where(AuthorityDocument.court_name == court.name)
            .order_by(AuthorityDocument.decision_date.desc().nulls_last())
            .limit(10)
        ).all()
    )
    return CourtProfileResponse(
        court=CourtRecord.model_validate(court),
        judges=[JudgeRecord.model_validate(j) for j in judges],
        portfolio_matter_count=int(portfolio_count),
        authority_document_count=int(authority_count),
        recent_authorities=[
            AuthorityStub(
                id=row.id,
                title=row.title,
                decision_date=row.decision_date.isoformat() if row.decision_date else None,
                case_reference=row.case_reference,
                neutral_citation=row.neutral_citation,
            )
            for row in recent_authorities
        ],
    )
