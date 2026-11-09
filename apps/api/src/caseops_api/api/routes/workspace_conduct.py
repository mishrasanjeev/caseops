"""The authenticated native actor's own workspace conduct receipt."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from caseops_api.api.dependencies import DbSession, get_current_context, require_role
from caseops_api.db.models import MembershipRole
from caseops_api.schemas.workspace_conduct import (
    WorkspaceConductAccept,
    WorkspaceConductReportCreate,
    WorkspaceConductReportPage,
    WorkspaceConductReportReceipt,
    WorkspaceConductStatus,
)
from caseops_api.services import workspace_conduct, workspace_conduct_reports
from caseops_api.services.platform_admin import require_platform_admin
from caseops_api.services.session_context import SessionContext

router = APIRouter()
workspace_operator_router = APIRouter()
publisher_operator_router = APIRouter()
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



@router.post("/reports", response_model=WorkspaceConductReportReceipt, status_code=202)
def report(
    payload: WorkspaceConductReportCreate,
    context: NativeActor,
    session: DbSession,
    response: Response,
) -> WorkspaceConductReportReceipt:
    response.headers["Cache-Control"] = "no-store"
    return workspace_conduct_reports.receive(session, context=context, payload=payload)


@workspace_operator_router.get("/reports", response_model=WorkspaceConductReportPage)
def workspace_intake(
    context: Annotated[SessionContext, Depends(require_role(MembershipRole.OWNER))],
    session: DbSession,
    response: Response,
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> WorkspaceConductReportPage:
    response.headers["Cache-Control"] = "no-store"
    return workspace_conduct_reports.workspace_intake(
        session, context=context, after=str(after) if after is not None else None, limit=limit,
    )


@publisher_operator_router.get(
    "/workspace-conduct-reports", response_model=WorkspaceConductReportPage,
)
def publisher_intake(
    context: Annotated[SessionContext, Depends(get_current_context)],
    session: DbSession,
    response: Response,
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> WorkspaceConductReportPage:
    response.headers["Cache-Control"] = "no-store"
    platform_admin = require_platform_admin(session, context)
    return workspace_conduct_reports.publisher_intake(
        session, context=context, platform_admin=platform_admin,
        after=str(after) if after is not None else None, limit=limit,
    )
