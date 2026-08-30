from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.private_retrieval import (
    PrivateRetrievalAutocompleteRecord,
    PrivateRetrievalAutocompleteResponse,
    PrivateRetrievalCountResponse,
    PrivateRetrievalIntegrityResponse,
    PrivateRetrievalResultRecord,
    PrivateRetrievalSearchRequest,
    PrivateRetrievalSearchResponse,
)
from caseops_api.services.private_retrieval import (
    MAX_PREFILTER_CANDIDATES,
    autocomplete_private_content,
    capture_private_retrieval_fence,
    count_private_content,
    prefilter_private_projection_ids,
    private_retrieval_activation,
    retrieve_private_content,
    stream_private_content,
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


def _require_private_retrieval(session: DbSession, context: SessionContext) -> None:
    activation = private_retrieval_activation(session, context=context)
    if activation.available:
        return
    raise ProblemHTTPException(
        status_code=403 if activation.reason == "missing_capability" else 503,
        problem_type="private_retrieval_unavailable",
        detail="Private workspace retrieval is not enabled for this tenant and release.",
        extras={"reason": activation.reason},
    )


def _request_filters(payload: PrivateRetrievalSearchRequest) -> dict[str, object]:
    if not payload.scope_ids:
        return {}
    return {
        "scope_ids": {
            scope_type: sorted(set(scope_ids))
            for scope_type, scope_ids in payload.scope_ids.items()
        }
    }


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
    _require_private_retrieval(session, context)
    rows = retrieve_private_content(
        session,
        context=context,
        query=payload.query,
        source_types=set(payload.source_types) if payload.source_types else None,
        filters=_request_filters(payload),
        locale=payload.locale,
        require_activation=True,
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


@router.post(
    "/autocomplete",
    response_model=PrivateRetrievalAutocompleteResponse,
    summary="Autocomplete from current permitted private labels without snippets.",
)
def autocomplete_private_retrieval(
    payload: PrivateRetrievalSearchRequest,
    context: PrivateSearchUser,
    session: DbSession,
) -> PrivateRetrievalAutocompleteResponse:
    _require_private_retrieval(session, context)
    rows = autocomplete_private_content(
        session,
        context=context,
        query=payload.query,
        source_types=set(payload.source_types) if payload.source_types else None,
        filters=_request_filters(payload),
        limit=payload.limit,
    )
    return PrivateRetrievalAutocompleteResponse(
        items=[
            PrivateRetrievalAutocompleteRecord(
                projection_id=row.projection_id,
                source_type=row.source_type,
                source_id=row.source_id,
                source_version=row.source_version,
                label=row.label,
            )
            for row in rows
        ]
    )


@router.post(
    "/count",
    response_model=PrivateRetrievalCountResponse,
    summary="Count a bounded set of current permitted private matches.",
)
def count_private_retrieval(
    payload: PrivateRetrievalSearchRequest,
    context: PrivateSearchUser,
    session: DbSession,
) -> PrivateRetrievalCountResponse:
    _require_private_retrieval(session, context)
    count = count_private_content(
        session,
        context=context,
        query=payload.query,
        source_types=set(payload.source_types) if payload.source_types else None,
        filters=_request_filters(payload),
    )
    return PrivateRetrievalCountResponse(
        visible_match_count=count,
        count_limit=MAX_PREFILTER_CANDIDATES,
        count_is_capped=count >= MAX_PREFILTER_CANDIDATES,
    )


@router.post(
    "/search/stream",
    response_class=StreamingResponse,
    summary="Stream private results with a fresh authorization check per row.",
    responses={
        200: {
            "description": (
                "Authorized NDJSON records; delivery stops on any security or source change."
            ),
            "content": {
                "application/x-ndjson": {
                    "schema": {"type": "string"},
                }
            },
        }
    },
)
def stream_private_retrieval(
    payload: PrivateRetrievalSearchRequest,
    context: PrivateSearchUser,
    session: DbSession,
) -> StreamingResponse:
    _require_private_retrieval(session, context)
    fence = capture_private_retrieval_fence(
        session,
        context=context,
        require_activation=True,
    )
    candidate_ids = (
        prefilter_private_projection_ids(
            session,
            context=context,
            query=payload.query,
            source_types=set(payload.source_types) if payload.source_types else None,
            filters=_request_filters(payload),
            limit=payload.limit,
        )
        if fence is not None
        else ()
    )

    def body() -> Iterator[str]:
        if fence is None:
            return
        for row in stream_private_content(
            fence=fence,
            projection_ids=candidate_ids,
            query=payload.query,
            session_factory=get_session_factory(),
            limit=payload.limit,
        ):
            record = PrivateRetrievalResultRecord(
                projection_id=row.projection_id,
                source_type=row.source_type,
                source_id=row.source_id,
                source_version=row.source_version,
                label=row.label,
                content=row.content,
                score=row.score,
            )
            yield json.dumps(record.model_dump(), separators=(",", ":")) + "\n"

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
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
