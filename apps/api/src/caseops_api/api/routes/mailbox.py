"""Mailbox connector routes.

All authenticated routes are tenant-scoped and review-first. The Gmail webhook
route is token-verified and stores only hashed provider references.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.mailbox import (
    MailboxAttachmentCandidateListResponse,
    MailboxAttachmentCandidateReviewRequest,
    MailboxAttachmentCandidateReviewResponse,
    MailboxConnectionCallbackResponse,
    MailboxConnectionRecord,
    MailboxConnectionStartResponse,
    MailboxImportRequest,
    MailboxImportResponse,
    MailboxStatusResponse,
    MailboxWatchResponse,
    MailboxWebhookIngestResponse,
)
from caseops_api.services.gmail_sync import (
    complete_gmail_connection,
    import_recent_gmail_messages,
    ingest_gmail_webhook,
    list_attachment_candidates,
    list_gmail_status,
    list_message_imports,
    review_attachment_candidate,
    revoke_gmail_connection,
    start_gmail_connection,
    start_gmail_watch,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
MailboxViewer = Annotated[SessionContext, Depends(require_capability("calendar:view"))]
MailboxOperator = Annotated[SessionContext, Depends(require_capability("calendar:sync"))]


@router.get(
    "/gmail/status",
    response_model=MailboxStatusResponse,
    summary="List the caller's Gmail mailbox connector status.",
)
async def get_gmail_status(
    context: MailboxViewer,
    session: DbSession,
) -> MailboxStatusResponse:
    return list_gmail_status(session, context=context)


@router.post(
    "/gmail/start",
    response_model=MailboxConnectionStartResponse,
    summary="Start Gmail OAuth without exposing tokens.",
)
async def start_gmail(
    context: MailboxOperator,
    session: DbSession,
) -> MailboxConnectionStartResponse:
    return start_gmail_connection(session, context=context)


@router.get(
    "/gmail/callback",
    response_model=MailboxConnectionCallbackResponse,
    summary="Complete Gmail OAuth callback.",
)
async def complete_gmail(
    context: MailboxOperator,
    session: DbSession,
    code: Annotated[str, Query(min_length=1)],
    state: Annotated[str, Query(min_length=1)],
) -> MailboxConnectionCallbackResponse:
    return complete_gmail_connection(
        session,
        context=context,
        code=code,
        state=state,
    )


@router.delete(
    "/connections/{connection_id}",
    response_model=MailboxConnectionRecord,
    summary="Revoke a Gmail mailbox connection for the caller.",
)
async def revoke_gmail(
    context: MailboxOperator,
    session: DbSession,
    connection_id: str,
) -> MailboxConnectionRecord:
    return revoke_gmail_connection(
        session,
        context=context,
        connection_id=connection_id,
    )


@router.post(
    "/gmail/import",
    response_model=MailboxImportResponse,
    summary="Import recent Gmail metadata into review-first CaseOps records.",
)
async def import_gmail(
    payload: MailboxImportRequest,
    context: MailboxOperator,
    session: DbSession,
) -> MailboxImportResponse:
    return import_recent_gmail_messages(session, context=context, payload=payload)


@router.post(
    "/gmail/watch",
    response_model=MailboxWatchResponse,
    summary="Start Gmail Pub/Sub watch for the caller's connected mailbox.",
)
async def watch_gmail(
    context: MailboxOperator,
    session: DbSession,
) -> MailboxWatchResponse:
    return start_gmail_watch(session, context=context)


@router.post(
    "/gmail/webhook",
    response_model=MailboxWebhookIngestResponse,
    summary="Ingest a token-verified Gmail Pub/Sub webhook.",
)
async def gmail_webhook(
    session: DbSession,
    payload: dict[str, Any],
    token: str | None = Query(default=None),
) -> MailboxWebhookIngestResponse:
    return ingest_gmail_webhook(
        session,
        verification_token=token,
        payload=payload,
    )


@router.get(
    "/imports",
    response_model=MailboxImportResponse,
    summary="List tenant-safe Gmail message import records.",
)
async def get_imports(
    context: MailboxViewer,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> MailboxImportResponse:
    return list_message_imports(session, context=context, limit=limit)


@router.get(
    "/attachment-candidates",
    response_model=MailboxAttachmentCandidateListResponse,
    summary="List Gmail attachment candidates awaiting review.",
)
async def get_attachment_candidates(
    context: MailboxViewer,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> MailboxAttachmentCandidateListResponse:
    return list_attachment_candidates(session, context=context, limit=limit)


@router.patch(
    "/attachment-candidates/{candidate_id}",
    response_model=MailboxAttachmentCandidateReviewResponse,
    summary="Approve/import or reject one Gmail attachment candidate.",
)
async def patch_attachment_candidate(
    candidate_id: str,
    payload: MailboxAttachmentCandidateReviewRequest,
    context: MailboxOperator,
    session: DbSession,
) -> MailboxAttachmentCandidateReviewResponse:
    return review_attachment_candidate(
        session,
        context=context,
        candidate_id=candidate_id,
        payload=payload,
    )

