from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.authorities import (
    AuthorityDocumentListResponse,
    AuthorityIngestionRequest,
    AuthorityIngestionRunRecord,
    AuthoritySearchRequest,
    AuthoritySearchResponse,
    AuthoritySourceListResponse,
)
from caseops_api.services.authorities import (
    ingest_authority_source,
    list_authority_sources,
    list_recent_authority_documents,
    search_authorities,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get(
    "/sources",
    response_model=AuthoritySourceListResponse,
    summary="List authority sources",
)
async def get_authority_sources(
    context: CurrentContext,
) -> AuthoritySourceListResponse:
    return list_authority_sources(context=context)


@router.post(
    "/ingestions/pull",
    response_model=AuthorityIngestionRunRecord,
    summary="Pull authority documents from an official live source",
)
async def pull_authority_source(
    payload: AuthorityIngestionRequest,
    context: CurrentContext,
    session: DbSession,
) -> AuthorityIngestionRunRecord:
    return ingest_authority_source(session, context=context, payload=payload)


@router.get(
    "/documents/recent",
    response_model=AuthorityDocumentListResponse,
    summary="List recently ingested authority documents",
)
async def get_recent_authority_documents(
    context: CurrentContext,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=20)] = 12,
) -> AuthorityDocumentListResponse:
    return list_recent_authority_documents(session, context=context, limit=limit)


@router.post(
    "/search",
    response_model=AuthoritySearchResponse,
    summary="Search the authority corpus",
)
async def post_authority_search(
    payload: AuthoritySearchRequest,
    context: CurrentContext,
    session: DbSession,
) -> AuthoritySearchResponse:
    return search_authorities(session, context=context, payload=payload)
