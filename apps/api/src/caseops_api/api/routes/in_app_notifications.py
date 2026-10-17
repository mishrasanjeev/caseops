from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.in_app_notifications import (
    InAppNotificationUpdate,
    RecipientNotificationPage,
    RecipientNotificationRecord,
)
from caseops_api.services.in_app_notifications import (
    list_recipient_notifications,
    update_recipient_notification,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
Recipient = Annotated[SessionContext, Depends(require_capability("ip:read"))]


@router.get("", response_model=RecipientNotificationPage)
def list_current_receipts(
    session: DbSession,
    context: Recipient,
    docket_id: Annotated[str, Query(min_length=36, max_length=36)],
    dismissed: bool = False,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
):
    return list_recipient_notifications(
        session,
        context=context,
        docket_id=docket_id,
        dismissed=dismissed,
        cursor=cursor,
        limit=limit,
    )


@router.patch("/{notification_id}", response_model=RecipientNotificationRecord)
def change_receipt_status(
    notification_id: str,
    payload: InAppNotificationUpdate,
    session: DbSession,
    context: Recipient,
    docket_id: Annotated[str, Query(min_length=36, max_length=36)],
):
    return update_recipient_notification(
        session,
        context=context,
        docket_id=docket_id,
        notification_id=notification_id,
        payload=payload,
    )
