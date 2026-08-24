"""IPLF-052 journal-watch API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.ip_watch import (
    IpJournalIngestionRunResponse,
    IpJournalIngestRequest,
    IpJournalIngestResponse,
    IpJournalPublicationResponse,
    IpWatchHandoffRequest,
    IpWatchHandoffResponse,
    IpWatchHitDispositionRequest,
    IpWatchHitResponse,
    IpWatchProfileCreateRequest,
    IpWatchProfileResponse,
    IpWatchProfileUpdateRequest,
    IpWatchWorkspaceResponse,
)
from caseops_api.services.ip_watch import (
    create_watch_handoff,
    create_watch_profile,
    decide_watch_hit,
    ingest_journal,
    list_watch_workspace,
    update_watch_profile_status,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()


@router.get("/watch", response_model=IpWatchWorkspaceResponse)
def watch_workspace(
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
    docket_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
) -> IpWatchWorkspaceResponse:
    return list_watch_workspace(
        session, context=context, docket_id=docket_id, limit=limit
    )


@router.post(
    "/watch/profiles",
    response_model=IpWatchProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def watch_profile_create(
    payload: IpWatchProfileCreateRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:watch_manage"))],
) -> IpWatchProfileResponse:
    return IpWatchProfileResponse.model_validate(
        create_watch_profile(session, context=context, payload=payload)
    )


@router.post("/watch/profiles/{profile_id}/status", response_model=IpWatchProfileResponse)
def watch_profile_status(
    profile_id: str,
    payload: IpWatchProfileUpdateRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:watch_manage"))],
) -> IpWatchProfileResponse:
    return IpWatchProfileResponse.model_validate(
        update_watch_profile_status(
            session,
            context=context,
            profile_id=profile_id,
            payload=payload,
        )
    )


@router.post(
    "/watch/journal-ingestions",
    response_model=IpJournalIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def journal_ingest(
    payload: IpJournalIngestRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:watch_manage"))],
) -> IpJournalIngestResponse:
    run, publications, hits, replay = ingest_journal(
        session, context=context, payload=payload
    )
    return IpJournalIngestResponse(
        run=IpJournalIngestionRunResponse.model_validate(run),
        publications=[
            IpJournalPublicationResponse.model_validate(item) for item in publications
        ],
        hits=[IpWatchHitResponse.model_validate(item) for item in hits],
        idempotent_replay=replay,
    )


@router.post("/watch/hits/{hit_id}/disposition", response_model=IpWatchHitResponse)
def watch_hit_disposition(
    hit_id: str,
    payload: IpWatchHitDispositionRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:watch_manage"))],
) -> IpWatchHitResponse:
    return IpWatchHitResponse.model_validate(
        decide_watch_hit(
            session,
            context=context,
            hit_id=hit_id,
            payload=payload,
        )
    )


@router.post(
    "/watch/hits/{hit_id}/handoffs",
    response_model=IpWatchHandoffResponse,
    status_code=status.HTTP_201_CREATED,
)
def watch_hit_handoff(
    hit_id: str,
    payload: IpWatchHandoffRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:watch_manage"))],
) -> IpWatchHandoffResponse:
    return IpWatchHandoffResponse.model_validate(
        create_watch_handoff(
            session,
            context=context,
            hit_id=hit_id,
            payload=payload,
        )
    )
