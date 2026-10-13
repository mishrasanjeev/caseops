from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import IpDocketRecord, Matter
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.matter_access import assert_ip_docket_access
from caseops_api.services.session_context import SessionContext


def _docket_or_404(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    for_update: bool = False,
    required_capability: str = "ip:write",
) -> IpDocketRecord:
    if for_update:
        # Every docket mutation eventually persists an actor-backed audit or
        # evidence row.  Fence that FK participant before Matter/docket locks;
        # otherwise offboarding can hold Membership while waiting on the
        # docket and this writer can hold the docket while PostgreSQL waits for
        # a Membership KEY SHARE lock during flush.
        context = _lock_ip_writer_context(
            session,
            context=context,
            required_capability=required_capability,
        )
    statement = select(IpDocketRecord).where(
        IpDocketRecord.id == docket_id,
        IpDocketRecord.company_id == context.company.id,
    )
    discovered_parent = (
        session.execute(
            select(IpDocketRecord.id, IpDocketRecord.matter_id).where(
                IpDocketRecord.id == docket_id,
                IpDocketRecord.company_id == context.company.id,
            )
        ).one_or_none()
        if for_update
        else None
    )
    docket = session.scalar(statement) if not for_update else None
    locked_matter: Matter | None = None
    if discovered_parent is not None and discovered_parent.matter_id:
        # Stabilize the compatibility pointer before the docket lock. The
        # Matter is not the IP lifecycle parent; this lock only prevents a
        # concurrent operational relink from changing the target mid-write.
        locked_matter = session.scalar(
            select(Matter)
            .where(
                Matter.id == discovered_parent.matter_id,
                Matter.company_id == context.company.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_matter is None:
            raise HTTPException(status_code=404, detail="IP docket record not found.")
    if discovered_parent is not None:
        docket = session.scalar(
            statement.with_for_update().execution_options(populate_existing=True)
        )
    if docket is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    if for_update:
        assert discovered_parent is not None
        if docket.matter_id != discovered_parent.matter_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The IP docket parent changed; retry the operation.",
            )
    if docket.archived_by_matter_disposal or not docket.is_active:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    assert_ip_docket_access(session, context=context, docket=docket)
    return docket


def _lock_ip_writer_context(
    session: Session,
    *,
    context: SessionContext,
    required_capability: str,
) -> SessionContext:
    """Fence an IP mutation actor and rebuild context from locked rows."""

    actor_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={context.membership.id},
    )
    locked_actor = actor_memberships.get(context.membership.id)
    if locked_actor is None or not locked_actor.is_active or not locked_actor.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active company membership is required for this IP mutation.",
        )
    require_locked_membership_capability(
        session,
        locked_actor,
        required_capability,
    )
    return SessionContext(
        company=context.company,
        user=locked_actor.user,
        membership=locked_actor,
    )
