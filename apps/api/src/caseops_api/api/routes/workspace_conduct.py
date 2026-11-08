"""The authenticated native actor's own workspace conduct receipt."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from caseops_api.api.dependencies import DbSession, require_role
from caseops_api.db.models import MembershipRole
from caseops_api.schemas.workspace_conduct import WorkspaceConductAccept, WorkspaceConductStatus
from caseops_api.services import workspace_conduct
from caseops_api.services.session_context import SessionContext

router = APIRouter()
NativeActor = Annotated[SessionContext, Depends(require_role(*MembershipRole))]


@router.get("", response_model=WorkspaceConductStatus)
def current(
    context: NativeActor, session: DbSession, response: Response,
) -> WorkspaceConductStatus:
    response.headers["Cache-Control"] = "no-store"
    return workspace_conduct.current_status(session, context=context)


@router.post("/accept", response_model=WorkspaceConductStatus)
def accept(
    payload: WorkspaceConductAccept,
    context: NativeActor,
    session: DbSession,
    response: Response,
) -> WorkspaceConductStatus:
    response.headers["Cache-Control"] = "no-store"
    return workspace_conduct.accept_current(session, context=context, version=payload.version)
