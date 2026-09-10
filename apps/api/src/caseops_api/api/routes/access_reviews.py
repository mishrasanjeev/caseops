from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.access_reviews import (
    CampaignCreate,
    CampaignPage,
    CampaignRecord,
    ReviewDecision,
    ScopeSnapshot,
    TargetPage,
    TargetType,
    VersionCommand,
)
from caseops_api.services import access_reviews as service
from caseops_api.services.session_context import SessionContext

router = APIRouter()
AccessManager = Annotated[SessionContext, Depends(require_capability("matter_access:manage"))]


@router.get("/targets", response_model=TargetPage)
def targets(
    context: AccessManager,
    session: DbSession,
    kind: TargetType,
    q: str = Query(default="", max_length=100),
    after_id: str | None = Query(default=None, max_length=36),
):
    return service.list_targets(session, context=context, kind=kind, query=q, after_id=after_id)


@router.get("/scope", response_model=ScopeSnapshot)
def scope(
    context: AccessManager,
    session: DbSession,
    kind: TargetType,
    target_id: str = Query(min_length=1, max_length=36),
):
    return service.scope_snapshot(session, context=context, kind=kind, target_id=target_id)


@router.get("", response_model=CampaignPage)
def campaigns(
    context: AccessManager,
    session: DbSession,
    before_id: str | None = Query(default=None, max_length=36),
):
    return service.list_campaigns(session, context=context, before_id=before_id)


@router.post("", response_model=CampaignRecord, status_code=201)
def create(payload: CampaignCreate, context: AccessManager, session: DbSession):
    return service.create_campaign(session, context=context, payload=payload)


@router.get("/{campaign_id}", response_model=CampaignRecord)
def get(campaign_id: str, context: AccessManager, session: DbSession):
    return service.get_campaign(session, context=context, campaign_id=campaign_id)


@router.post("/{campaign_id}/decisions", response_model=CampaignRecord)
def decide(campaign_id: str, payload: ReviewDecision, context: AccessManager, session: DbSession):
    return service.decide(session, context=context, campaign_id=campaign_id, payload=payload)


@router.post("/{campaign_id}/finalize", response_model=CampaignRecord)
def finalize(campaign_id: str, payload: VersionCommand, context: AccessManager, session: DbSession):
    return service.finalize(
        session, context=context, campaign_id=campaign_id, expected_version=payload.expected_version
    )
