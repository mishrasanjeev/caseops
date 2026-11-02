from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, get_current_context, require_role
from caseops_api.db.models import MembershipRole
from caseops_api.schemas.in_app_notifications import InAppNotificationUpdate
from caseops_api.schemas.recipient_inbox import InboxPage, InboxRecord
from caseops_api.services.recipient_inbox import list_recipient_inbox, update_inbox_record
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
# All supported tenant roles may manage their own receipt. The service still
# checks the recipient, current source and parent authority under its lock.
RecipientContext = Annotated[SessionContext, Depends(require_role(*tuple(MembershipRole)))]


@router.get("", response_model=InboxPage)
def inbox(
    session: DbSession,
    context: CurrentContext,
    view: Literal["active", "dismissed"] = "active",
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: Annotated[str | None, Query(max_length=4000)] = None,
):
    return list_recipient_inbox(session, context=context, view=view, limit=limit, cursor=cursor)


@router.patch("/{notification_id}", response_model=InboxRecord)
def change_inbox_status(
    notification_id: str,
    payload: InAppNotificationUpdate,
    session: DbSession,
    context: RecipientContext,
):
    return update_inbox_record(
        session, context=context, notification_id=notification_id, payload=payload
    )
