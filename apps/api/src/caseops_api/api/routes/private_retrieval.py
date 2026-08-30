from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.schemas.private_retrieval import (
    PrivateRetrievalIntegrityResponse,
    PrivateRetrievalResultRecord,
    PrivateRetrievalSearchRequest,
    PrivateRetrievalSearchResponse,
)
from caseops_api.services.private_retrieval import (
    private_retrieval_activation,
    retrieve_private_content,
)
from caseops_api.services.private_retrieval_jobs import inspect_private_index_integrity
from caseops_api.services.session_context import SessionContext

router = APIRouter()
PrivateSearchUser = Annotated[
    SessionContext,
    Depends(require_capability("ai:generate")),
]
PrivateIntegrityUser = Annotated[
    SessionContext,
    Depends(require_capability("matter_access:manage")),
]


@router.post(
    "/search",
    response_model=PrivateRetrievalSearchResponse,
    summary="Search current permitted tenant-private projections.",
)
def search_private_retrieval(
    payload: PrivateRetrievalSearchRequest,
    context: PrivateSearchUser,
    session: DbSession,
) -> PrivateRetrievalSearchResponse:
    activation = private_retrieval_activation(session, context=context)
    if not activation.available:
        raise ProblemHTTPException(
            status_code=403 if activation.reason == "missing_capability" else 503,
            problem_type="private_retrieval_unavailable",
            detail="Private workspace retrieval is not enabled for this tenant and release.",
            extras={"reason": activation.reason},
        )
    filters: dict[str, object] = {}
    if payload.scope_ids:
        filters["scope_ids"] = {
            scope_type: sorted(set(scope_ids))
            for scope_type, scope_ids in payload.scope_ids.items()
        }
    rows = retrieve_private_content(
        session,
        context=context,
        query=payload.query,
        source_types=set(payload.source_types) if payload.source_types else None,
        filters=filters,
        locale=payload.locale,
        limit=payload.limit,
    )
    return PrivateRetrievalSearchResponse(
        items=[
            PrivateRetrievalResultRecord(
                projection_id=row.projection_id,
                source_type=row.source_type,
                source_id=row.source_id,
                source_version=row.source_version,
                label=row.label,
                content=row.content,
                score=row.score,
            )
            for row in rows
        ],
    )


@router.get(
    "/integrity",
    response_model=PrivateRetrievalIntegrityResponse,
    summary="Read safe tenant-private projection release aggregates.",
)
def get_private_retrieval_integrity(
    context: PrivateIntegrityUser,
    session: DbSession,
) -> PrivateRetrievalIntegrityResponse:
    activation = private_retrieval_activation(session, context=context)
    report = inspect_private_index_integrity(
        session,
        company_id=context.company.id,
    )
    blockers = list(report.blockers)
    if not activation.available:
        blockers.insert(0, f"activation:{activation.reason}")
    return PrivateRetrievalIntegrityResponse(
        state=report.state if activation.available else "disabled",
        activation_reason=activation.reason,
        active_generation_id=report.active_generation_id,
        live_projection_count=report.live_projection_count,
        tombstoned_projection_count=report.tombstoned_projection_count,
        pending_event_count=report.pending_event_count,
        failed_event_count=report.failed_event_count,
        oldest_pending_lag_seconds=report.oldest_pending_lag_seconds,
        orphan_scope_count=report.orphan_scope_count,
        stale_source_count=report.stale_source_count,
        unsafe_tombstone_count=report.unsafe_tombstone_count,
        generation_manifest_matches=report.generation_manifest_matches,
        release_blocked=bool(blockers),
        blockers=blockers,
    )


__all__ = ["router"]
