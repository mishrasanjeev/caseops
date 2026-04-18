from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.authorities import (
    AuthorityAnnotationCreateRequest,
    AuthorityAnnotationListResponse,
    AuthorityAnnotationRecord,
    AuthorityAnnotationUpdateRequest,
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
from caseops_api.services.authority_annotations import (
    create_annotation,
    delete_annotation,
    list_annotations,
    update_annotation,
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


def _annotation_record(annotation) -> AuthorityAnnotationRecord:
    return AuthorityAnnotationRecord(
        id=annotation.id,
        company_id=annotation.company_id,
        authority_document_id=annotation.authority_document_id,
        created_by_membership_id=annotation.created_by_membership_id,
        kind=annotation.kind,
        title=annotation.title,
        body=annotation.body,
        is_archived=annotation.is_archived,
        created_at=annotation.created_at,
        updated_at=annotation.updated_at,
    )


@router.get(
    "/documents/{authority_id}/annotations",
    response_model=AuthorityAnnotationListResponse,
    summary="List this tenant's annotations on an authority document",
    tags=["authorities"],
)
async def get_authority_annotations(
    authority_id: str,
    context: CurrentContext,
    session: DbSession,
    include_archived: Annotated[bool, Query()] = False,
) -> AuthorityAnnotationListResponse:
    items = list_annotations(
        session,
        context=context,
        authority_id=authority_id,
        include_archived=include_archived,
    )
    return AuthorityAnnotationListResponse(
        annotations=[_annotation_record(a) for a in items]
    )


@router.post(
    "/documents/{authority_id}/annotations",
    response_model=AuthorityAnnotationRecord,
    summary="Create a tenant-private annotation on an authority document",
    status_code=status.HTTP_201_CREATED,
    tags=["authorities"],
)
async def post_authority_annotation(
    authority_id: str,
    payload: AuthorityAnnotationCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> AuthorityAnnotationRecord:
    annotation = create_annotation(
        session,
        context=context,
        authority_id=authority_id,
        kind=payload.kind,
        title=payload.title,
        body=payload.body,
    )
    return _annotation_record(annotation)


@router.patch(
    "/annotations/{annotation_id}",
    response_model=AuthorityAnnotationRecord,
    summary="Update a tenant-private authority annotation",
    tags=["authorities"],
)
async def patch_authority_annotation(
    annotation_id: str,
    payload: AuthorityAnnotationUpdateRequest,
    context: CurrentContext,
    session: DbSession,
) -> AuthorityAnnotationRecord:
    annotation = update_annotation(
        session,
        context=context,
        annotation_id=annotation_id,
        title=payload.title,
        body=payload.body,
        is_archived=payload.is_archived,
    )
    return _annotation_record(annotation)


@router.delete(
    "/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a tenant-private authority annotation",
    tags=["authorities"],
    responses={204: {"description": "Annotation deleted"}},
)
async def delete_authority_annotation(
    annotation_id: str,
    context: CurrentContext,
    session: DbSession,
) -> None:
    delete_annotation(session, context=context, annotation_id=annotation_id)
