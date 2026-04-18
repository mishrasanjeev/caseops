"""Team CRUD + membership + team-scoping toggle (Sprint 8c BG-026)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.teams import (
    TeamCreateRequest,
    TeamListResponse,
    TeamMembershipCreateRequest,
    TeamRecord,
    TeamScopingResponse,
    TeamScopingUpdateRequest,
    TeamUpdateRequest,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.teams import (
    add_team_member,
    create_team,
    delete_team,
    list_teams,
    remove_team_member,
    set_team_scoping,
    update_team,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
TeamManager = Annotated[
    SessionContext, Depends(require_capability("teams:manage"))
]


@router.get(
    "/",
    response_model=TeamListResponse,
    summary="List teams for the current company",
)
async def get_teams(
    context: CurrentContext, session: DbSession
) -> TeamListResponse:
    return list_teams(session, context=context)


@router.post(
    "/",
    response_model=TeamRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team",
)
async def post_team(
    payload: TeamCreateRequest,
    context: TeamManager,
    session: DbSession,
) -> TeamRecord:
    result = create_team(session, context=context, payload=payload)
    session.commit()
    return result


@router.patch(
    "/{team_id}",
    response_model=TeamRecord,
    summary="Update a team",
)
async def patch_team(
    team_id: str,
    payload: TeamUpdateRequest,
    context: TeamManager,
    session: DbSession,
) -> TeamRecord:
    result = update_team(
        session, context=context, team_id=team_id, payload=payload
    )
    session.commit()
    return result


@router.delete(
    "/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a team",
)
async def delete_team_endpoint(
    team_id: str,
    context: TeamManager,
    session: DbSession,
) -> None:
    delete_team(session, context=context, team_id=team_id)
    session.commit()


@router.post(
    "/{team_id}/members",
    response_model=TeamRecord,
    summary="Add a member to a team",
)
async def post_team_member(
    team_id: str,
    payload: TeamMembershipCreateRequest,
    context: TeamManager,
    session: DbSession,
) -> TeamRecord:
    result = add_team_member(
        session,
        context=context,
        team_id=team_id,
        membership_id=payload.membership_id,
        is_lead=payload.is_lead,
    )
    session.commit()
    return result


@router.delete(
    "/{team_id}/members/{membership_id}",
    response_model=TeamRecord,
    summary="Remove a member from a team",
)
async def delete_team_member(
    team_id: str,
    membership_id: str,
    context: TeamManager,
    session: DbSession,
) -> TeamRecord:
    result = remove_team_member(
        session,
        context=context,
        team_id=team_id,
        membership_id=membership_id,
    )
    session.commit()
    return result


@router.put(
    "/scoping",
    response_model=TeamScopingResponse,
    summary="Turn team-scoped matter visibility on or off",
)
async def put_team_scoping(
    payload: TeamScopingUpdateRequest,
    context: TeamManager,
    session: DbSession,
) -> TeamScopingResponse:
    enabled = set_team_scoping(session, context=context, enabled=payload.enabled)
    session.commit()
    return TeamScopingResponse(enabled=enabled)
