from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.matter_work_queue import MatterWorkQueuePage
from caseops_api.services.matter_work_queue import list_matter_work_queue
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
Day = Annotated[str | None, Query(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]


@router.get("", response_model=MatterWorkQueuePage)
def queue(
    session: DbSession,
    context: CurrentContext,
    ownership: Literal["mine", "team", "unassigned"] = "mine",
    dates: Literal["all", "dated", "undated"] = "all",
    limit: Annotated[int, Query(ge=1, le=25)] = 25,
    cursor: Annotated[str | None, Query(max_length=4000)] = None,
    due_from: Day = None,
    due_to: Day = None,
):
    return list_matter_work_queue(
        session,
        context=context,
        ownership=ownership,
        dates=dates,
        limit=limit,
        cursor=cursor,
        due_from=due_from,
        due_to=due_to,
    )
