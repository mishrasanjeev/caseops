"""Receive one authenticated global user's request, without performing deletion.

The workspace and membership are routing/audit provenance only. They confer no
authority to submit for another person, erase tenant records, send messages or
declare fulfillment. No provider, outbox or background task is involved.
"""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from caseops_api.db.models import AccountDeletionRequest, NativeDeviceSession
from caseops_api.schemas.account_privacy import (
    AccountDeletionRequestCreate,
    AccountDeletionRequestCurrent,
    AccountDeletionRequestReceipt,
)
from caseops_api.services import native_auth
from caseops_api.services.platform_audit import record_platform_audit
from caseops_api.services.security import enforce_login_mfa_if_required
from caseops_api.services.session_context import SessionContext

PATH = "/api/account/deletion-requests"


def _fresh_self(session: Session, context: SessionContext) -> SessionContext:
    if context.token_issued_at is None:
        raise HTTPException(401, "An authenticated tenant session is required.")
    # Same canonical Company -> Membership -> User fence as native exchange.
    # It refreshes active state/cutoffs, serializes this User across workspaces,
    # and drops all authority locks before its existing bounded lock retry.
    fresh = native_auth._identity_fence(
        session,
        membership_id=context.membership.id,
        source_issued_at=context.token_issued_at,
    )
    if fresh.user.id != context.user.id or fresh.company.id != context.company.id:
        raise HTTPException(401, "The current identity changed. Sign in again.")
    if context.native_session_id is not None:
        device = session.scalar(
            select(NativeDeviceSession)
            .where(NativeDeviceSession.id == context.native_session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if device is None:
            raise HTTPException(401, "The current native session is unavailable.")
        # Re-check the server-validated family, expiry and current MFA after
        # acquiring the same identity/device lock order as refresh/revocation.
        fresh = native_auth.native_context(
            session,
            {
                "sid": device.id,
                "membership_id": fresh.membership.id,
                "company_id": fresh.company.id,
                "sub": fresh.user.id,
            },
        )
    else:
        enforce_login_mfa_if_required(session, context=fresh, path=PATH)
    return fresh


def _receipt(row: AccountDeletionRequest) -> AccountDeletionRequestReceipt:
    stamp = row.requested_at
    return AccountDeletionRequestReceipt(
        id=row.id,
        operation_id=row.operation_id,
        status=row.status,
        requested_at=stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC),
    )


def _own(session: Session, user_id: str) -> AccountDeletionRequest | None:
    return session.scalar(
        select(AccountDeletionRequest).where(AccountDeletionRequest.subject_user_id == user_id)
    )


def submit_deletion_request(
    session: Session, *, context: SessionContext, payload: AccountDeletionRequestCreate
) -> AccountDeletionRequestReceipt:
    # Canonical SQLite absent-row writer fence, before checking the unique User.
    # The DB conflict barrier below also covers writers in other processes.
    serialize = getattr(session, "serialize_sqlite_writer", None)
    if session.get_bind().dialect.name == "sqlite":
        if serialize is None:
            raise RuntimeError("Account request requires the canonical SQLite session.")
        serialize()
    fresh = _fresh_self(session, context)
    row = _own(session, fresh.user.id)
    if row is None:
        insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
        statement = (
            insert(AccountDeletionRequest)
            .values(
                id=str(uuid4()),
                subject_user_id=fresh.user.id,
                submitted_from_company_id=fresh.company.id,
                submitted_by_membership_id=fresh.membership.id,
                operation_id=payload.operation_id,
                confirmation_version="account-deletion-v1",
                submitted_realm="native" if fresh.native_session_id else "tenant_web",
                status="received",
                requested_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=[AccountDeletionRequest.subject_user_id])
            .returning(AccountDeletionRequest.id)
        )
        inserted_id = session.scalar(statement)
        row = _own(session, fresh.user.id)
        if row is None:
            raise RuntimeError("Account request admission did not return a receipt.")
        if inserted_id is not None:
            # A global self request is private user/security provenance, not
            # the originating workspace's exportable tenant audit trail.
            # Flush it in the winning insert transaction; a replay writes none.
            record_platform_audit(
                session,
                context=fresh,
                platform_admin=None,
                company_id=None,
                action="account.deletion_request_received",
                target_type="account_deletion_request",
                target_id=row.id,
                metadata={
                    "request_type": "account_deletion",
                    "status": "received",
                    "deletion_completed": False,
                },
            )
    if row.operation_id != payload.operation_id:
        raise HTTPException(
            409,
            detail={
                "code": "account_deletion_request_pending",
                "message": "A request has already been received. Reload its receipt.",
            },
        )
    receipt = _receipt(row)
    session.commit()
    return receipt


def current_deletion_request(
    session: Session, *, context: SessionContext
) -> AccountDeletionRequestCurrent:
    fresh = _fresh_self(session, context)
    row = _own(session, fresh.user.id)
    return AccountDeletionRequestCurrent(request=_receipt(row) if row else None)


def read_deletion_request(
    session: Session, *, context: SessionContext, request_id: str
) -> AccountDeletionRequestReceipt:
    fresh = _fresh_self(session, context)
    row = session.scalar(
        select(AccountDeletionRequest).where(
            AccountDeletionRequest.id == request_id,
            AccountDeletionRequest.subject_user_id == fresh.user.id,
        )
    )
    if row is None:
        raise HTTPException(404, "Account request not found.")
    return _receipt(row)
