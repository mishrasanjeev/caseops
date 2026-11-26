"""Three-part, source-verified research answers (J05 / M04)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.core.rate_limit import ai_route_rate_limit, limiter, tenant_aware_key
from caseops_api.schemas.research_answers import (
    ResearchAnswerCreateRequest,
    ResearchAnswerListResponse,
    ResearchAnswerRecord,
    ResearchAnswerSaveRequest,
)
from caseops_api.services.document_dispatch import dispatch_ai_job
from caseops_api.services.research_answers import (
    create_research_answer,
    get_research_answer,
    list_research_answers,
    run_research_answer_job,
    save_research_answer_to_matter,
    serialize_research_answer,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
# Generating an answer spends AI budget, so it follows the same capability as
# other AI analysis. Reading is limited to the author or, once saved, to
# people who can access the matter.
ResearchGenerator = Annotated[
    SessionContext, Depends(require_capability("recommendations:generate"))
]
ResearchReader = Annotated[SessionContext, Depends(require_capability("authorities:search"))]
ResearchSaver = Annotated[SessionContext, Depends(require_capability("matters:edit"))]


@router.post(
    "/answers",
    response_model=ResearchAnswerRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a source-verified three-part research answer",
)
@limiter.limit(ai_route_rate_limit, key_func=tenant_aware_key)
def create_answer(
    request: Request,
    payload: ResearchAnswerCreateRequest,
    background_tasks: BackgroundTasks,
    context: ResearchGenerator,
    session: DbSession,
) -> ResearchAnswerRecord:
    answer, created = create_research_answer(session, context=context, payload=payload)
    answer_id = answer.id
    record = serialize_research_answer(session, answer)
    if created:
        # Production wakes the independent AI job; a failed wake leaves the
        # committed row queued for its per-minute scheduler.
        dispatch_ai_job(
            session=session,
            background_tasks=background_tasks,
            job_id=answer_id,
            runner=run_research_answer_job,
        )
    return record


@router.get(
    "/answers",
    response_model=ResearchAnswerListResponse,
    summary="List my research answers, or those saved to a matter",
)
def list_answers(
    context: ResearchReader,
    session: DbSession,
    matter_id: Annotated[str | None, Query(max_length=36)] = None,
) -> ResearchAnswerListResponse:
    return list_research_answers(session, context=context, matter_id=matter_id)


@router.get(
    "/answers/{answer_id}",
    response_model=ResearchAnswerRecord,
    summary="Read one research answer",
)
def read_answer(
    answer_id: str, context: ResearchReader, session: DbSession
) -> ResearchAnswerRecord:
    return get_research_answer(session, context=context, answer_id=answer_id)


@router.post(
    "/answers/{answer_id}/save",
    response_model=ResearchAnswerRecord,
    summary="Save a completed research answer to a matter",
)
def save_answer(
    answer_id: str,
    payload: ResearchAnswerSaveRequest,
    context: ResearchSaver,
    session: DbSession,
) -> ResearchAnswerRecord:
    return save_research_answer_to_matter(
        session, context=context, answer_id=answer_id, matter_id=payload.matter_id
    )
