"""GET-only retained recommendation/hearing-pack views; no action or generation endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.matter_readthrough import (
    HearingPackItemPage,
    HearingPackRead,
    RecommendationDecisionPage,
    RecommendationDetail,
    RecommendationOptionPage,
    RecommendationPage,
)
from caseops_api.services import matter_readthrough as reads
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
SourceID = Annotated[str, Path(min_length=1, max_length=36, pattern=r"^[^\x00-\x1f\x7f]+$")]
Limit = Annotated[int, Query(ge=1, le=25)]
Cursor = Annotated[str | None, Query(min_length=1, max_length=4000)]


@router.get("/{matter_id}/recommendations", response_model=RecommendationPage)
def recommendations(
    matter_id: SourceID,
    context: CurrentContext,
    session: DbSession,
    limit: Limit = 25,
    cursor: Cursor = None,
):
    return reads.list_recommendations(
        session, context=context, matter_id=matter_id, limit=limit, cursor=cursor
    )


@router.get("/{matter_id}/recommendations/{recommendation_id}", response_model=RecommendationDetail)
def recommendation(
    matter_id: SourceID, recommendation_id: SourceID, context: CurrentContext, session: DbSession
):
    return reads.get_recommendation(
        session, context=context, matter_id=matter_id, recommendation_id=recommendation_id
    )


@router.get(
    "/{matter_id}/recommendations/{recommendation_id}/options",
    response_model=RecommendationOptionPage,
)
def options(
    matter_id: SourceID,
    recommendation_id: SourceID,
    context: CurrentContext,
    session: DbSession,
    limit: Limit = 25,
    cursor: Cursor = None,
):
    return reads.list_options(
        session,
        context=context,
        matter_id=matter_id,
        recommendation_id=recommendation_id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{matter_id}/recommendations/{recommendation_id}/decisions",
    response_model=RecommendationDecisionPage,
)
def decisions(
    matter_id: SourceID,
    recommendation_id: SourceID,
    context: CurrentContext,
    session: DbSession,
    limit: Limit = 25,
    cursor: Cursor = None,
):
    return reads.list_decisions(
        session,
        context=context,
        matter_id=matter_id,
        recommendation_id=recommendation_id,
        limit=limit,
        cursor=cursor,
    )


@router.get("/{matter_id}/hearings/{hearing_id}/pack", response_model=HearingPackRead | None)
def latest_pack(
    matter_id: SourceID, hearing_id: SourceID, context: CurrentContext, session: DbSession
):
    return reads.get_latest_pack(
        session, context=context, matter_id=matter_id, hearing_id=hearing_id
    )


@router.get("/{matter_id}/hearing-packs/{pack_id}", response_model=HearingPackRead)
def pack(matter_id: SourceID, pack_id: SourceID, context: CurrentContext, session: DbSession):
    return reads.get_pack(session, context=context, matter_id=matter_id, pack_id=pack_id)


@router.get("/{matter_id}/hearing-packs/{pack_id}/items", response_model=HearingPackItemPage)
def pack_items(
    matter_id: SourceID,
    pack_id: SourceID,
    context: CurrentContext,
    session: DbSession,
    limit: Limit = 25,
    cursor: Cursor = None,
):
    return reads.list_pack_items(
        session, context=context, matter_id=matter_id, pack_id=pack_id, limit=limit, cursor=cursor
    )
