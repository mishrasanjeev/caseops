from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.matter_tags import (
    MatterTagCreateRequest,
    MatterTagListResponse,
    MatterTagRecord,
    MatterTagUpdateRequest,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_tags import (
    create_tag,
    delete_tag,
    list_tags,
    update_tag,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
TagManager = Annotated[SessionContext, Depends(require_capability("matter_access:manage"))]


@router.get("/", response_model=MatterTagListResponse, summary="List matter tags")
async def get_current_company_matter_tags(
    context: CurrentContext,
    session: DbSession,
) -> MatterTagListResponse:
    return list_tags(session, context=context)


@router.post(
    "/",
    response_model=MatterTagRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a matter tag",
)
async def post_current_company_matter_tag(
    payload: MatterTagCreateRequest,
    context: TagManager,
    session: DbSession,
) -> MatterTagRecord:
    result = create_tag(session, context=context, payload=payload)
    session.commit()
    return result


@router.patch(
    "/{tag_id}",
    response_model=MatterTagRecord,
    summary="Update a matter tag",
)
async def patch_current_company_matter_tag(
    tag_id: str,
    payload: MatterTagUpdateRequest,
    context: TagManager,
    session: DbSession,
) -> MatterTagRecord:
    result = update_tag(session, context=context, tag_id=tag_id, payload=payload)
    session.commit()
    return result


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a matter tag",
)
async def delete_current_company_matter_tag(
    tag_id: str,
    context: TagManager,
    session: DbSession,
) -> Response:
    delete_tag(session, context=context, tag_id=tag_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
