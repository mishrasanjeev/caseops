from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.db.models import AuthorityDocument, Court, Judge, JudgeMappingReview
from caseops_api.schemas.judge_mapping import (
    AuthorityRemapResponse,
    BenchAliasCreateRequest,
    CatalogAliasRecord,
    JudgeAliasCreateRequest,
    JudgeIdentityRecord,
    JudgeMappingCandidateRecord,
    JudgeMappingReviewListResponse,
    JudgeMappingReviewRecord,
    JudgeMappingReviewResolveRequest,
    JudgeMergeRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.judge_mapping import (
    JudgeMappingConflict,
    JudgeMappingError,
    add_bench_alias,
    add_judge_alias,
    merge_duplicate_judges,
    rebuild_authority_mapping,
    resolve_mapping_review,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CourtCurator = Annotated[
    SessionContext, Depends(require_capability("court_sync:run"))
]


def _raise_mapping_error(exc: JudgeMappingError) -> None:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, JudgeMappingConflict)
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get(
    "/reviews",
    response_model=JudgeMappingReviewListResponse,
    summary="List bounded unresolved or historical judge-mapping reviews.",
)
def list_mapping_reviews(
    context: CourtCurator,
    session: DbSession,
    review_status: Annotated[str, Query(alias="status", max_length=24)] = "open",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> JudgeMappingReviewListResponse:
    del context
    rows = list(
        session.scalars(
            select(JudgeMappingReview)
            .where(JudgeMappingReview.status == review_status)
            .order_by(JudgeMappingReview.updated_at.desc(), JudgeMappingReview.id.desc())
            .limit(limit + 1)
        )
    )
    page = rows[:limit]
    authority_ids = {row.authority_document_id for row in page}
    court_ids = {row.court_id for row in page if row.court_id}
    candidate_ids = {
        candidate_id
        for row in page
        for candidate_id in (row.candidate_judge_ids_json or [])
    }
    authorities = {
        item.id: item
        for item in session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.id.in_(authority_ids))
        )
    }
    courts = {
        item.id: item
        for item in session.scalars(select(Court).where(Court.id.in_(court_ids)))
    }
    judges = {
        item.id: item
        for item in session.scalars(select(Judge).where(Judge.id.in_(candidate_ids)))
    }
    records: list[JudgeMappingReviewRecord] = []
    for row in page:
        document = authorities[row.authority_document_id]
        records.append(
            JudgeMappingReviewRecord(
                id=row.id,
                authority_document_id=row.authority_document_id,
                authority_title=document.title,
                court_id=row.court_id,
                court_name=courts[row.court_id].name if row.court_id else None,
                raw_judge_name=row.raw_judge_name,
                source_ordinal=row.source_ordinal,
                reason=row.reason,
                status=row.status,
                resolver_version=row.resolver_version,
                candidates=[
                    JudgeMappingCandidateRecord(
                        id=judge.id,
                        full_name=judge.full_name,
                        court_id=judge.court_id,
                    )
                    for candidate_id in (row.candidate_judge_ids_json or [])
                    if (judge := judges.get(candidate_id)) is not None
                ],
                resolved_judge_id=row.resolved_judge_id,
                resolution_note=row.resolution_note,
                record_version=row.record_version,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return JudgeMappingReviewListResponse(
        reviews=records,
        returned_count=len(records),
        limit=limit,
        has_more=len(rows) > limit,
    )


@router.post(
    "/reviews/{review_id}/resolve",
    response_model=JudgeMappingReviewRecord,
    summary="Resolve one judge-mapping review with optimistic concurrency.",
)
def post_mapping_review_resolution(
    review_id: str,
    payload: JudgeMappingReviewResolveRequest,
    context: CourtCurator,
    session: DbSession,
) -> JudgeMappingReviewRecord:
    try:
        review = resolve_mapping_review(
            session,
            review_id=review_id,
            judge_id=payload.judge_id,
            expected_record_version=payload.expected_record_version,
            membership_id=context.membership.id,
            note=payload.note,
            commit=False,
        )
    except JudgeMappingError as exc:
        _raise_mapping_error(exc)
    record_from_context(
        session,
        context,
        action="judge_mapping.review.resolve",
        target_type="judge_mapping_review",
        target_id=review.id,
        metadata={"judge_id": payload.judge_id, "record_version": review.record_version},
        commit=True,
    )
    return list_mapping_reviews_by_id(session, review)


def list_mapping_reviews_by_id(
    session: DbSession, review: JudgeMappingReview
) -> JudgeMappingReviewRecord:
    document = session.get(AuthorityDocument, review.authority_document_id)
    court = session.get(Court, review.court_id) if review.court_id else None
    candidate_ids = review.candidate_judge_ids_json or []
    candidates = {
        row.id: row
        for row in session.scalars(select(Judge).where(Judge.id.in_(candidate_ids)))
    }
    return JudgeMappingReviewRecord(
        id=review.id,
        authority_document_id=review.authority_document_id,
        authority_title=document.title if document else "Unavailable authority",
        court_id=review.court_id,
        court_name=court.name if court else None,
        raw_judge_name=review.raw_judge_name,
        source_ordinal=review.source_ordinal,
        reason=review.reason,
        status=review.status,
        resolver_version=review.resolver_version,
        candidates=[
            JudgeMappingCandidateRecord(
                id=judge.id, full_name=judge.full_name, court_id=judge.court_id
            )
            for candidate_id in candidate_ids
            if (judge := candidates.get(candidate_id)) is not None
        ],
        resolved_judge_id=review.resolved_judge_id,
        resolution_note=review.resolution_note,
        record_version=review.record_version,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@router.post("/judges/{judge_id}/aliases", response_model=CatalogAliasRecord)
def post_judge_alias(
    judge_id: str,
    payload: JudgeAliasCreateRequest,
    context: CourtCurator,
    session: DbSession,
) -> CatalogAliasRecord:
    try:
        alias = add_judge_alias(
            session,
            judge_id=judge_id,
            **payload.model_dump(),
            commit=False,
        )
    except JudgeMappingError as exc:
        _raise_mapping_error(exc)
    record_from_context(
        session,
        context,
        action="judge_catalog.alias.upsert",
        target_type="judge_alias",
        target_id=alias.id,
        metadata={"judge_id": judge_id, "source": payload.source},
        commit=True,
    )
    return CatalogAliasRecord.model_validate(alias)


@router.post("/benches/{bench_id}/aliases", response_model=CatalogAliasRecord)
def post_bench_alias(
    bench_id: str,
    payload: BenchAliasCreateRequest,
    context: CourtCurator,
    session: DbSession,
) -> CatalogAliasRecord:
    try:
        alias = add_bench_alias(
            session, bench_id=bench_id, **payload.model_dump(), commit=False
        )
    except JudgeMappingError as exc:
        _raise_mapping_error(exc)
    record_from_context(
        session,
        context,
        action="bench_catalog.alias.upsert",
        target_type="bench_alias",
        target_id=alias.id,
        metadata={"bench_id": bench_id, "source": payload.source},
        commit=True,
    )
    return CatalogAliasRecord.model_validate(alias)


@router.post("/judges/{source_judge_id}/merge", response_model=JudgeIdentityRecord)
def post_judge_merge(
    source_judge_id: str,
    payload: JudgeMergeRequest,
    context: CourtCurator,
    session: DbSession,
) -> JudgeIdentityRecord:
    try:
        destination = merge_duplicate_judges(
            session,
            source_judge_id=source_judge_id,
            destination_judge_id=payload.destination_judge_id,
            expected_source_version=payload.expected_source_version,
            expected_destination_version=payload.expected_destination_version,
            commit=False,
        )
    except JudgeMappingError as exc:
        _raise_mapping_error(exc)
    record_from_context(
        session,
        context,
        action="judge_catalog.identity.merge",
        target_type="judge",
        target_id=source_judge_id,
        metadata={
            "destination_judge_id": destination.id,
            "reason": payload.reason,
        },
        commit=True,
    )
    return JudgeIdentityRecord.model_validate(destination)


@router.post(
    "/authorities/{authority_document_id}/reprocess",
    response_model=AuthorityRemapResponse,
)
def post_authority_reprocess(
    authority_document_id: str,
    context: CourtCurator,
    session: DbSession,
) -> AuthorityRemapResponse:
    try:
        summary = rebuild_authority_mapping(
            session, authority_document_id=authority_document_id, commit=False
        )
    except JudgeMappingError as exc:
        _raise_mapping_error(exc)
    record_from_context(
        session,
        context,
        action="judge_mapping.authority.reprocess",
        target_type="authority_document",
        target_id=authority_document_id,
        metadata={
            "mapped": summary.mapped,
            "collisions": summary.collisions,
            "unresolved": summary.unresolved,
        },
        commit=True,
    )
    return AuthorityRemapResponse(**summary.__dict__)
