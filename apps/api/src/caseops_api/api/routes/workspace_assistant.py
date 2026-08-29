from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.workspace_assistant import (
    AssistantActionConfirmRequest,
    AssistantActionPreviewRequest,
    AssistantActionPreviewResponse,
    AssistantAskRequest,
    AssistantAskResponse,
    AssistantScopeReplaceRequest,
    AssistantScopeSearchResponse,
    AssistantSessionArchiveRequest,
    AssistantSessionCreateRequest,
    AssistantSessionExportResponse,
    AssistantSessionListResponse,
    AssistantSessionRecord,
    AssistantTurnListResponse,
)
from caseops_api.services.assistant_actions import (
    confirm_assistant_action,
    preview_assistant_action,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.workspace_assistant import (
    archive_assistant_session,
    ask_workspace_assistant,
    create_assistant_session,
    export_assistant_session,
    get_assistant_session,
    list_assistant_sessions,
    list_assistant_turns,
    refuse_assistant_session_deletion,
    replace_assistant_scopes,
    search_assistant_scopes,
)

router = APIRouter()
AssistantUser = Annotated[SessionContext, Depends(require_capability("ai:generate"))]


@router.get(
    "/scope-options",
    response_model=AssistantScopeSearchResponse,
    summary="Find currently permitted records for an explicit assistant scope.",
)
def get_assistant_scope_options(
    context: AssistantUser,
    session: DbSession,
    query: Annotated[str, Query(alias="q", min_length=2, max_length=160)],
    limit: Annotated[int, Query(ge=1, le=20)] = 12,
) -> AssistantScopeSearchResponse:
    return search_assistant_scopes(
        session,
        context=context,
        query=query,
        limit=limit,
    )


@router.post(
    "/sessions",
    response_model=AssistantSessionRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a permission-scoped workspace assistant session.",
)
def post_assistant_session(
    payload: AssistantSessionCreateRequest,
    context: AssistantUser,
    session: DbSession,
) -> AssistantSessionRecord:
    return create_assistant_session(
        session,
        context=context,
        title=payload.title,
        scopes=payload.scopes,
    )


@router.get(
    "/sessions",
    response_model=AssistantSessionListResponse,
    summary="List the signed-in user's bounded assistant session history.",
)
def get_assistant_sessions(
    context: AssistantUser,
    session: DbSession,
    session_status: Annotated[Literal["active", "archived"] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> AssistantSessionListResponse:
    return list_assistant_sessions(
        session,
        context=context,
        session_status=session_status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=AssistantSessionRecord,
    summary="Read a session after reauthorizing every active scope.",
)
def get_assistant_session_route(
    session_id: str,
    context: AssistantUser,
    session: DbSession,
) -> AssistantSessionRecord:
    return get_assistant_session(
        session,
        context=context,
        session_id=session_id,
    )


@router.put(
    "/sessions/{session_id}/scopes",
    response_model=AssistantSessionRecord,
    summary="Atomically replace active scopes with optimistic concurrency.",
)
def put_assistant_session_scopes(
    session_id: str,
    payload: AssistantScopeReplaceRequest,
    context: AssistantUser,
    session: DbSession,
) -> AssistantSessionRecord:
    return replace_assistant_scopes(
        session,
        context=context,
        session_id=session_id,
        expected_version=payload.expected_version,
        scopes=payload.scopes,
    )


@router.post(
    "/sessions/{session_id}/archive",
    response_model=AssistantSessionRecord,
    summary="Archive a session without deleting retained legal work product.",
)
def post_assistant_session_archive(
    session_id: str,
    payload: AssistantSessionArchiveRequest,
    context: AssistantUser,
    session: DbSession,
) -> AssistantSessionRecord:
    return archive_assistant_session(
        session,
        context=context,
        session_id=session_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/sessions/{session_id}/ask",
    response_model=AssistantAskResponse,
    summary="Answer from explicit, currently permitted workspace scopes.",
)
def post_assistant_question(
    session_id: str,
    payload: AssistantAskRequest,
    context: AssistantUser,
    session: DbSession,
) -> AssistantAskResponse:
    return ask_workspace_assistant(
        session,
        context=context,
        session_id=session_id,
        expected_version=payload.expected_version,
        question=payload.question,
    )


@router.post(
    "/sessions/{session_id}/actions/preview",
    response_model=AssistantActionPreviewResponse,
    summary="Preview one proposed assistant write without changing its target.",
)
def post_assistant_action_preview(
    session_id: str,
    payload: AssistantActionPreviewRequest,
    context: AssistantUser,
    session: DbSession,
) -> AssistantActionPreviewResponse:
    return preview_assistant_action(
        session,
        context=context,
        session_id=session_id,
        payload=payload,
    )


@router.post(
    "/sessions/{session_id}/actions/{preview_id}/confirm",
    response_model=AssistantActionPreviewResponse,
    summary="Confirm an unchanged preview through the canonical domain writer.",
)
def post_assistant_action_confirmation(
    session_id: str,
    preview_id: str,
    payload: AssistantActionConfirmRequest,
    context: AssistantUser,
    session: DbSession,
) -> AssistantActionPreviewResponse:
    return confirm_assistant_action(
        session,
        context=context,
        session_id=session_id,
        preview_id=preview_id,
        payload=payload,
    )


@router.get(
    "/sessions/{session_id}/turns",
    response_model=AssistantTurnListResponse,
    summary="List retained turns after citation reauthorization.",
)
def get_assistant_turns(
    session_id: str,
    context: AssistantUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> AssistantTurnListResponse:
    return list_assistant_turns(
        session,
        context=context,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_id}/export",
    response_model=AssistantSessionExportResponse,
    summary="Export a retained session after current permission checks.",
)
def get_assistant_session_export(
    session_id: str,
    context: AssistantUser,
    session: DbSession,
) -> AssistantSessionExportResponse:
    return export_assistant_session(
        session,
        context=context,
        session_id=session_id,
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Apply the governed assistant-session deletion boundary.",
)
def delete_assistant_session(
    session_id: str,
    context: AssistantUser,
    session: DbSession,
) -> None:
    refuse_assistant_session_deletion(
        session,
        context=context,
        session_id=session_id,
    )
