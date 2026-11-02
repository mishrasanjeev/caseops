"""Authenticated self-service intake only; no account-deletion executor."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response

from caseops_api.api.dependencies import DbSession, require_role
from caseops_api.db.models import MembershipRole
from caseops_api.schemas.account_privacy import (
    UUID_PATTERN,
    AccountDeletionRequestCreate,
    AccountDeletionRequestCurrent,
    AccountDeletionRequestReceipt,
)
from caseops_api.services import account_privacy
from caseops_api.services.session_context import SessionContext

router = APIRouter()
# Every supported tenant role can act only for its authenticated global User.
# require_role consumes the canonical CurrentContext, including native realm,
# cookie precedence, active membership and MFA. No admin capability is granted.
SelfRequester = Annotated[SessionContext, Depends(require_role(*MembershipRole))]


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("/deletion-requests", response_model=AccountDeletionRequestReceipt, status_code=202)
def submit(
    payload: AccountDeletionRequestCreate,
    context: SelfRequester,
    session: DbSession,
    response: Response,
) -> AccountDeletionRequestReceipt:
    _private(response)
    return account_privacy.submit_deletion_request(session, context=context, payload=payload)


@router.get("/deletion-requests", response_model=AccountDeletionRequestCurrent)
def current(
    context: SelfRequester, session: DbSession, response: Response
) -> AccountDeletionRequestCurrent:
    _private(response)
    return account_privacy.current_deletion_request(session, context=context)


@router.get("/deletion-requests/{request_id}", response_model=AccountDeletionRequestReceipt)
def read(
    request_id: Annotated[str, Path(min_length=36, max_length=36, pattern=UUID_PATTERN)],
    context: SelfRequester,
    session: DbSession,
    response: Response,
) -> AccountDeletionRequestReceipt:
    _private(response)
    return account_privacy.read_deletion_request(session, context=context, request_id=request_id)
