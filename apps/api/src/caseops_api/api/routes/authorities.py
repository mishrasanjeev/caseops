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
    AuthorityTreatmentBucketRecord,
    AuthorityTreatmentSampleRecord,
    AuthorityTreatmentSummaryResponse,
    JudgmentAlertDigestPreviewResponse,
    JudgmentAlertListResponse,
    JudgmentAlertRecord,
    JudgmentAlertRuleCreateRequest,
    JudgmentAlertRuleListResponse,
    JudgmentAlertRuleRecord,
    JudgmentAlertRuleUpdateRequest,
    JudgmentAlertRunRequest,
    JudgmentAlertRunResponse,
    JudgmentAlertUpdateRequest,
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
from caseops_api.services.authority_treatments import (
    summarize_treatments,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.judgment_alerts import (
    create_judgment_alert_rule,
    list_judgment_alert_rules,
    list_judgment_alerts,
    preview_judgment_alert_digest,
    run_judgment_alert_rule,
    update_judgment_alert,
    update_judgment_alert_rule,
)

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


@router.get(
    "/alerts/rules",
    response_model=JudgmentAlertRuleListResponse,
    summary="List saved judgment alert rules",
)
async def get_judgment_alert_rules(
    context: AuthoritySearcher,
    session: DbSession,
) -> JudgmentAlertRuleListResponse:
    return list_judgment_alert_rules(session, context=context)


@router.post(
    "/alerts/rules",
    response_model=JudgmentAlertRuleRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a saved judgment alert rule",
)
async def post_judgment_alert_rule(
    payload: JudgmentAlertRuleCreateRequest,
    context: AuthoritySearcher,
    session: DbSession,
) -> JudgmentAlertRuleRecord:
    return create_judgment_alert_rule(session, context=context, payload=payload)


@router.patch(
    "/alerts/rules/{rule_id}",
    response_model=JudgmentAlertRuleRecord,
    summary="Update or archive a saved judgment alert rule",
)
async def patch_judgment_alert_rule(
    rule_id: str,
    payload: JudgmentAlertRuleUpdateRequest,
    context: AuthoritySearcher,
    session: DbSession,
) -> JudgmentAlertRuleRecord:
    return update_judgment_alert_rule(
        session,
        context=context,
        rule_id=rule_id,
        payload=payload,
    )


@router.post(
    "/alerts/rules/{rule_id}/run",
    response_model=JudgmentAlertRunResponse,
    summary="Preview or generate in-app judgment alerts from existing authorities",
)
async def post_judgment_alert_rule_run(
    rule_id: str,
    payload: JudgmentAlertRunRequest,
    context: AuthoritySearcher,
    session: DbSession,
) -> JudgmentAlertRunResponse:
    return run_judgment_alert_rule(
        session,
        context=context,
        rule_id=rule_id,
        payload=payload,
    )


@router.get(
    "/alerts",
    response_model=JudgmentAlertListResponse,
    summary="List in-app judgment alerts",
)
async def get_judgment_alerts(
    context: AuthoritySearcher,
    session: DbSession,
    include_dismissed: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> JudgmentAlertListResponse:
    return list_judgment_alerts(
        session,
        context=context,
        include_dismissed=include_dismissed,
        limit=limit,
    )


@router.get(
    "/alerts/digest-preview",
    response_model=JudgmentAlertDigestPreviewResponse,
    summary="Preview an in-app-only judgment alert digest",
)
async def get_judgment_alert_digest_preview(
    context: AuthoritySearcher,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> JudgmentAlertDigestPreviewResponse:
    return preview_judgment_alert_digest(
        session,
        context=context,
        limit=limit,
    )


@router.patch(
    "/alerts/{alert_id}",
    response_model=JudgmentAlertRecord,
    summary="Mark an in-app judgment alert read or dismissed",
)
async def patch_judgment_alert(
    alert_id: str,
    payload: JudgmentAlertUpdateRequest,
    context: AuthoritySearcher,
    session: DbSession,
) -> JudgmentAlertRecord:
    return update_judgment_alert(
        session,
        context=context,
        alert_id=alert_id,
        payload=payload,
    )


@router.get(
    "/{authority_document_id}/treatments",
    response_model=AuthorityTreatmentSummaryResponse,
    summary="Good-law treatment summary for one authority (PG-006)",
)
async def get_authority_treatment_summary(
    authority_document_id: str,
    context: AuthoritySearcher,
    session: DbSession,
) -> AuthorityTreatmentSummaryResponse:
    """Return the treatment counts + sample evidence for one authority.

    PG-006 Phase 1B — reads from ``authority_citations.treatment``
    (populated by Phase 1A's heuristic classifier). The response
    powers the research-result badge and the per-authority "good
    law?" panel. Permission gate is the same as authority search.
    """
    _ = context  # suppress unused; capability check happens via the dep
    summary = summarize_treatments(session, authority_document_id)
    return AuthorityTreatmentSummaryResponse(
        authority_document_id=summary.authority_document_id,
        total_incoming=summary.total_incoming,
        adverse_count=summary.adverse_count,
        has_adverse_treatment=summary.has_adverse_treatment,
        worst_treatment=summary.worst_treatment,  # type: ignore[arg-type]
        buckets=[
            AuthorityTreatmentBucketRecord(
                treatment=b.treatment,  # type: ignore[arg-type]
                count=b.count,
                samples=[
                    AuthorityTreatmentSampleRecord(
                        citing_authority_document_id=s.citing_authority_document_id,
                        citing_title=s.citing_title,
                        citing_neutral_citation=s.citing_neutral_citation,
                        citation_text=s.citation_text,
                        treatment=s.treatment,  # type: ignore[arg-type]
                        confidence=s.confidence,
                        evidence_text=s.evidence_text,
                    )
                    for s in b.samples
                ],
            )
            for b in summary.buckets
        ],
    )


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
