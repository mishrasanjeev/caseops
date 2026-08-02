"""Mailbox connector routes.

All authenticated routes are tenant-scoped and review-first. The Gmail webhook
route is token-verified and stores only hashed provider references.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.inbound_email import (
    InboundEmailAliasCreateRequest,
    InboundEmailAliasListResponse,
    InboundEmailAliasRecord,
    InboundEmailAliasUpdateRequest,
    InboundEmailEventListResponse,
    InboundEmailEventReviewRequest,
    InboundEmailEventReviewResponse,
    InboundEmailWebhookRequest,
    InboundEmailWebhookResponse,
)
from caseops_api.schemas.mailbox import (
    MailboxAttachmentCandidateListResponse,
    MailboxAttachmentCandidateReviewRequest,
    MailboxAttachmentCandidateReviewResponse,
    MailboxConnectionCallbackResponse,
    MailboxConnectionRecord,
    MailboxConnectionStartResponse,
    MailboxImportRequest,
    MailboxImportResponse,
    MailboxMessageImportRecord,
    MailboxMessageReviewRequest,
    MailboxMessageReviewResponse,
    MailboxStatusResponse,
    MailboxWatchResponse,
    MailboxWebhookIngestResponse,
    OutlookMailCandidateCreateRequest,
)
from caseops_api.services.connector_health import refresh_connector_health_records
from caseops_api.services.gmail_sync import (
    complete_gmail_connection,
    create_outlook_mail_candidate,
    import_recent_gmail_messages,
    ingest_gmail_webhook,
    list_attachment_candidates,
    list_gmail_status,
    list_message_imports,
    review_attachment_candidate,
    review_message_import,
    revoke_gmail_connection,
    start_gmail_connection,
    start_gmail_watch,
)
from caseops_api.services.inbound_email import (
    create_inbound_email_alias,
    ingest_inbound_email_webhook,
    list_inbound_email_aliases,
    list_inbound_email_events,
    review_inbound_email_event,
    update_inbound_email_alias,
)
from caseops_api.services.security import require_recent_step_up
from caseops_api.services.session_context import SessionContext

router = APIRouter()
MailboxViewer = Annotated[SessionContext, Depends(require_capability("calendar:view"))]
MailboxOperator = Annotated[SessionContext, Depends(require_capability("calendar:sync"))]
WorkspaceAdmin = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]


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
    require_recent_step_up(session, context=context, purpose="connector_disconnect")
    response = revoke_gmail_connection(
        session,
        context=context,
        connection_id=connection_id,
    )
    refresh_connector_health_records(session, context=context)
    session.commit()
    return response


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
    provider: str | None = Query(default=None),
    matter_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=120),
) -> MailboxImportResponse:
    return list_message_imports(
        session,
        context=context,
        limit=limit,
        provider=provider,
        matter_id=matter_id,
        status_filter=status_filter,
        q=q,
    )


@router.patch(
    "/imports/{import_id}",
    response_model=MailboxMessageReviewResponse,
    summary="Review one mailbox metadata candidate without importing raw bodies.",
)
async def patch_message_import(
    import_id: str,
    payload: MailboxMessageReviewRequest,
    context: MailboxOperator,
    session: DbSession,
) -> MailboxMessageReviewResponse:
    return review_message_import(
        session,
        context=context,
        import_id=import_id,
        payload=payload,
    )


@router.post(
    "/outlook/candidates",
    response_model=MailboxMessageImportRecord,
    summary="Create a local-safe Outlook Mail metadata review candidate.",
)
async def post_outlook_mail_candidate(
    payload: OutlookMailCandidateCreateRequest,
    context: MailboxOperator,
    session: DbSession,
) -> MailboxMessageImportRecord:
    return create_outlook_mail_candidate(session, context=context, payload=payload)


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


@router.get(
    "/inbound-aliases",
    response_model=InboundEmailAliasListResponse,
    summary="List tenant/matter inbound email aliases.",
)
async def get_inbound_email_aliases(
    context: WorkspaceAdmin,
    session: DbSession,
) -> InboundEmailAliasListResponse:
    return list_inbound_email_aliases(session, context=context)


@router.post(
    "/inbound-aliases",
    response_model=InboundEmailAliasRecord,
    summary="Create a disabled-by-default inbound email alias.",
)
async def post_inbound_email_alias(
    payload: InboundEmailAliasCreateRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> InboundEmailAliasRecord:
    return create_inbound_email_alias(session, context=context, payload=payload)


@router.patch(
    "/inbound-aliases/{alias_id}",
    response_model=InboundEmailAliasRecord,
    summary="Update inbound email alias controls.",
)
async def patch_inbound_email_alias(
    alias_id: str,
    payload: InboundEmailAliasUpdateRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> InboundEmailAliasRecord:
    return update_inbound_email_alias(
        session,
        context=context,
        alias_id=alias_id,
        payload=payload,
    )


@router.post(
    "/inbound/webhook",
    response_model=InboundEmailWebhookResponse,
    summary="Ingest a provider-verified inbound email metadata event.",
)
async def post_inbound_email_webhook(
    request: Request,
    payload: InboundEmailWebhookRequest,
    session: DbSession,
    signature: str | None = Header(default=None, alias="X-CaseOps-Inbound-Signature"),
) -> InboundEmailWebhookResponse:
    raw_body = await request.body()
    return ingest_inbound_email_webhook(
        session,
        payload=payload,
        raw_body=raw_body,
        signature=signature,
    )


@router.get(
    "/inbound-events",
    response_model=InboundEmailEventListResponse,
    summary="List inbound email alias review events.",
)
async def get_inbound_email_events(
    context: MailboxViewer,
    session: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    matter_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> InboundEmailEventListResponse:
    return list_inbound_email_events(
        session,
        context=context,
        status_filter=status_filter,
        matter_id=matter_id,
        limit=limit,
    )


@router.patch(
    "/inbound-events/{event_id}",
    response_model=InboundEmailEventReviewResponse,
    summary="Review one inbound email event without importing raw bodies.",
)
async def patch_inbound_email_event(
    event_id: str,
    payload: InboundEmailEventReviewRequest,
    context: MailboxOperator,
    session: DbSession,
) -> InboundEmailEventReviewResponse:
    return review_inbound_email_event(
        session,
        context=context,
        event_id=event_id,
        payload=payload,
    )
