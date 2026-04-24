from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.authorities import (
    AuthorityAnnotationCreateRequest,
    AuthorityAnnotationListResponse,
    AuthorityAnnotationRecord,
    AuthorityAnnotationUpdateRequest,
    AuthorityCorpusStats,
    AuthorityDocumentListResponse,
    AuthorityIngestionRequest,
    AuthorityIngestionRunRecord,
    AuthoritySearchRequest,
    AuthoritySearchResponse,
    AuthoritySourceListResponse,
    SavedAnnotationListResponse,
    SavedAuthorityAnnotationRecord,
)
from caseops_api.services.authorities import (
    get_authority_corpus_stats,
    ingest_authority_source,
    list_authority_sources,
    list_recent_authority_documents,
    search_authorities,
)
from caseops_api.services.authority_annotations import (
    create_annotation,
    delete_annotation,
    list_annotations,
    list_tenant_annotations,
    update_annotation,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
AuthorityIngester = Annotated[SessionContext, Depends(require_capability('authorities:ingest'))]
AuthoritySearcher = Annotated[SessionContext, Depends(require_capability('authorities:search'))]
AuthorityAnnotator = Annotated[SessionContext, Depends(require_capability('authorities:annotate'))]


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
    context: AuthorityIngester,
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


@router.get(
    "/stats",
    response_model=AuthorityCorpusStats,
    summary="Aggregate counters for the authority corpus",
)
async def get_authority_stats(
    context: CurrentContext,
    session: DbSession,
) -> AuthorityCorpusStats:
    return get_authority_corpus_stats(session, context=context)


@router.post(
    "/search",
    response_model=AuthoritySearchResponse,
    summary="Search the authority corpus",
)
async def post_authority_search(
    payload: AuthoritySearchRequest,
    context: AuthoritySearcher,
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
    description=(
        "Attach a note, flag, or tag to a shared authority document. "
        "The authority corpus stays global; the annotation is visible "
        "only to the calling tenant. `(kind, title)` must be unique "
        "per (tenant, authority) — re-posting the same pair returns "
        "409. Each mutation is audited as `authority_annotation.created`."
    ),
    status_code=status.HTTP_201_CREATED,
    tags=["authorities"],
)
async def post_authority_annotation(
    authority_id: str,
    payload: AuthorityAnnotationCreateRequest,
    context: AuthorityAnnotator,
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
    context: AuthorityAnnotator,
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
    context: AuthorityAnnotator,
    session: DbSession,
) -> None:
    delete_annotation(session, context=context, annotation_id=annotation_id)


@router.get(
    "/annotations",
    response_model=SavedAnnotationListResponse,
    summary="List every annotation this tenant has saved across the corpus",
    description=(
        "Saved-research history (BUG-030). Returns the calling tenant's "
        "annotations joined with authority preview fields so the UI can "
        "render the history page in one round trip. Newest first, capped "
        "server-side at 500 rows."
    ),
    tags=["authorities"],
)
async def get_saved_annotations(
    context: CurrentContext,
    session: DbSession,
    include_archived: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> SavedAnnotationListResponse:
    pairs = list_tenant_annotations(
        session,
        context=context,
        include_archived=include_archived,
        limit=limit,
    )
    return SavedAnnotationListResponse(
        annotations=[
            SavedAuthorityAnnotationRecord(
                id=ann.id,
                authority_document_id=ann.authority_document_id,
                created_by_membership_id=ann.created_by_membership_id,
                kind=ann.kind,
                title=ann.title,
                body=ann.body,
                is_archived=ann.is_archived,
                created_at=ann.created_at,
                updated_at=ann.updated_at,
                authority_court_name=auth.court_name,
                authority_forum_level=auth.forum_level,
                authority_document_type=auth.document_type,
                authority_title=auth.title,
                authority_neutral_citation=auth.neutral_citation,
                authority_case_reference=auth.case_reference,
                authority_decision_date=auth.decision_date,
                authority_summary=auth.summary,
            )
            for ann, auth in pairs
        ]
    )
