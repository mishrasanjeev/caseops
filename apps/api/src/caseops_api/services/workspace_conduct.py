"""One acceptance receipt per tenant membership and approved rules version."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.db.models import CompanyMembership, NativeDeviceSession, WorkspaceConductAcceptance
from caseops_api.db.session import serialize_sqlite_writer
from caseops_api.schemas.workspace_conduct import WorkspaceConductStatus
from caseops_api.services import native_auth
from caseops_api.services.assignment_memberships import lock_company_memberships_for_oauth
from caseops_api.services.identity import _token_precedes_membership_cutoff
from caseops_api.services.session_context import SessionContext

RULES_VERSION = "2026-11-08"
POLICY_URL = "https://caseops.ai/workspace-use"


def _key(context: SessionContext) -> tuple[str, str, str]:
    return context.company.id, context.membership.id, RULES_VERSION


def _status(row: WorkspaceConductAcceptance | None) -> WorkspaceConductStatus:
    accepted_at = row.accepted_at if row is not None else None
    if accepted_at is not None and accepted_at.tzinfo is None:
        accepted_at = accepted_at.replace(tzinfo=UTC)
    return WorkspaceConductStatus(
        version=RULES_VERSION,
        policy_url=POLICY_URL,
        accepted_at=accepted_at,
    )


def _require_native(context: SessionContext) -> None:
    if context.native_session_id is None or context.token_issued_at is None:
        raise HTTPException(403, "An authenticated CaseOps app session is required.")


def current_status(session: Session, *, context: SessionContext) -> WorkspaceConductStatus:
    _require_native(context)
    return _status(session.get(WorkspaceConductAcceptance, _key(context)))


def lock_current_native_actor(
    session: Session, *, context: SessionContext, target_membership_id: str | None = None,
) -> tuple[SessionContext, CompanyMembership | None]:
    _require_native(context)
    serialize_sqlite_writer(session)
    # Native refresh uses this same Company -> Membership -> User -> Device
    # order. Include the reported membership before taking the Device lock.
    company, memberships = lock_company_memberships_for_oauth(
        session, company_id=context.company.id,
        membership_ids=(context.membership.id, target_membership_id),
    )
    fresh = memberships.get(context.membership.id)
    if company is None or fresh is None or fresh.user.id != context.user.id:
        raise HTTPException(401, "The current identity changed. Sign in again.")
    native_auth._validate_identity(SessionContext(
        company=company,
        membership=fresh,
        user=fresh.user,
        token_issued_at=context.token_issued_at,
    ))
    device = session.scalar(
        select(NativeDeviceSession)
        .where(
            NativeDeviceSession.id == context.native_session_id,
            NativeDeviceSession.membership_id == fresh.id,
        )
        .with_for_update(of=NativeDeviceSession)
        .execution_options(populate_existing=True)
    )
    if device is None:
        raise HTTPException(401, "The current native session is unavailable.")
    verified = native_auth.native_context(
        session,
        {
            "sid": device.id,
            "membership_id": fresh.id,
            "company_id": company.id,
            "sub": fresh.user.id,
        },
    )
    return verified, memberships.get(target_membership_id)


def accept_current(
    session: Session, *, context: SessionContext, version: str,
) -> WorkspaceConductStatus:
    _require_native(context)
    if version != RULES_VERSION:
        raise ProblemHTTPException(
            409,
            problem_type="workspace_conduct_version_changed",
            detail="The workspace use rules changed. Review the current version.",
        )
    verified, _target = lock_current_native_actor(session, context=context)
    row = session.get(WorkspaceConductAcceptance, _key(verified))
    if row is None:
        insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
        session.execute(
            insert(WorkspaceConductAcceptance)
            .values(
                company_id=verified.company.id,
                membership_id=verified.membership.id,
                version=RULES_VERSION,
                accepted_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["company_id", "membership_id", "version"])
        )
        row = session.get(WorkspaceConductAcceptance, _key(verified))
        if row is None:
            raise RuntimeError("Workspace conduct acceptance did not return a receipt.")
    receipt = _status(row)
    session.commit()
    return receipt


def require_for_locked_native_write(session: Session, *, context: SessionContext) -> None:
    """Use the actor already refreshed and locked by the canonical Matter writer."""
    _require_native(context)
    if _token_precedes_membership_cutoff(
        context.membership, token_issued_at=context.token_issued_at,
    ):
        raise HTTPException(401, "This session has been revoked. Please sign in again.")
    if session.get(WorkspaceConductAcceptance, _key(context)) is None:
        raise ProblemHTTPException(
            403,
            problem_type="workspace_conduct_acceptance_required",
            detail="Review and accept the current workspace use rules before adding content.",
        )
