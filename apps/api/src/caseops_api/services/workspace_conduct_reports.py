"""Private conduct intake with exact target visibility and metadata-only queues."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.orm import Session, aliased

from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterAttachment,
    MatterNote,
    MembershipRole,
    PlatformAdminMembership,
    WorkspaceConductReport,
)
from caseops_api.schemas.workspace_conduct import (
    ConductReportSource,
    ConductUserReportTarget,
    WorkspaceConductReportCreate,
    WorkspaceConductReportMetadata,
    WorkspaceConductReportPage,
    WorkspaceConductReportReceipt,
)
from caseops_api.services import workspace_conduct
from caseops_api.services.assignment_memberships import lock_company_memberships_for_oauth
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import _token_precedes_membership_cutoff
from caseops_api.services.matters import _get_matter_model
from caseops_api.services.platform_audit import record_platform_audit
from caseops_api.services.session_context import SessionContext

_ADMINISTRATOR_ROLES = (MembershipRole.OWNER, MembershipRole.ADMIN)


def _not_found() -> HTTPException:
    return HTTPException(404, "Reported item not found.")


def _source_query(target: ConductReportSource, source_kind: str, company_id: str):
    model, author = (
        (MatterNote, MatterNote.author_membership_id)
        if source_kind == "note"
        else (MatterAttachment, MatterAttachment.uploaded_by_membership_id)
    )
    return (
        select(author)
        .join(Matter, Matter.id == model.matter_id)
        .where(
            model.id == str(target.item_id),
            model.matter_id == str(target.matter_id),
            Matter.company_id == company_id,
        ),
        model,
    )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def receive(
    session: Session, *, context: SessionContext, payload: WorkspaceConductReportCreate,
) -> WorkspaceConductReportReceipt:
    target = payload.target
    user_target = isinstance(target, ConductUserReportTarget)
    source_kind = target.source_kind if user_target else target.kind
    statement, model = _source_query(target, source_kind, context.company.id)
    # This scalar hint establishes lock order only. Recheck source identity
    # and exact Matter visibility under the actor and source locks below.
    hinted_member_id = session.scalar(statement)
    fresh, target_member = workspace_conduct.lock_current_native_actor(
        session, context=context, target_membership_id=hinted_member_id,
    )
    try:
        _get_matter_model(
            session, context=fresh, matter_id=str(target.matter_id),
            lock_for_share=True, load_locked_children=False,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise _not_found() from None
    source = session.execute(statement.with_for_update(read=True, of=model)).one_or_none()
    if source is None or source[0] != hinted_member_id:
        raise _not_found()
    if hinted_member_id is not None and target_member is None:
        raise _not_found()
    if user_target and (
        target_member is None
        or target_member.id != str(target.membership_id)
        or target_member.user_id == fresh.user.id
    ):
        raise _not_found()

    key = {
        "company_id": fresh.company.id,
        "reporter_membership_id": fresh.membership.id,
        "operation_id": str(payload.operation_id),
    }
    fields = {
        "target_kind": target.kind,
        "target_membership_id": hinted_member_id,
        "source_kind": source_kind,
        "source_matter_id": str(target.matter_id),
        "source_item_id": str(target.item_id),
        "reason": payload.reason,
    }
    # The reporter membership lock serializes duplicate admissions. The unique
    # database key also prevents more than one receipt for this operation.
    row = session.scalar(select(WorkspaceConductReport).filter_by(**key))
    if row is None:
        row = WorkspaceConductReport(
            **key, **fields, id=str(uuid4()), received_at=datetime.now(UTC),
            routing=(
                "publisher"
                if target_member is None or target_member.role in _ADMINISTRATOR_ROLES
                else "workspace"
            ),
        )
        session.add(row)
    elif any(getattr(row, name) != value for name, value in fields.items()):
        raise ProblemHTTPException(
            409,
            problem_type="workspace_conduct_report_operation_conflict",
            detail="This operation was already used to report a different target or reason.",
        )
    receipt = WorkspaceConductReportReceipt(
        id=row.id, operation_id=row.operation_id, received_at=_utc(row.received_at),
    )
    session.commit()
    return receipt


def _metadata_page(
    session: Session, *, context: SessionContext, publisher: bool, after: str | None, limit: int,
) -> WorkspaceConductReportPage:
    report = WorkspaceConductReport
    subject = aliased(CompanyMembership)
    base = (
        select(
            report.id, report.company_id, report.target_membership_id,
            report.target_kind, report.reason, report.received_at,
        )
        .outerjoin(subject, and_(
            subject.company_id == report.company_id,
            subject.id == report.target_membership_id,
        ))
        .where(or_(subject.user_id.is_(None), subject.user_id != context.user.id))
    )
    # A later promotion must immediately hide earlier reports from workspace
    # intake and make them available to the publisher. A previously escalated
    # report stays there even after a demotion.
    if publisher:
        base = base.where(or_(
            report.routing == "publisher", subject.role.in_(_ADMINISTRATOR_ROLES),
        ))
    else:
        base = base.where(
            report.company_id == context.company.id,
            report.routing == "workspace",
            subject.role.not_in(_ADMINISTRATOR_ROLES),
        )
    if after is not None:
        anchor = session.execute(base.where(report.id == after)).one_or_none()
        if anchor is None:
            raise HTTPException(404, "Report continuation not found.")
        base = base.where(tuple_(report.received_at, report.id) < (
            anchor.received_at, anchor.id,
        ))
    rows = session.execute(base.order_by(report.received_at.desc(), report.id.desc()).limit(
        limit + 1,
    )).all()
    return WorkspaceConductReportPage(
        reports=[
            WorkspaceConductReportMetadata(
                id=row.id,
                company_id=row.company_id,
                target_membership_id=row.target_membership_id,
                target_kind=row.target_kind,
                reason=row.reason,
                received_at=_utc(row.received_at),
            )
            for row in rows[:limit]
        ],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


def workspace_intake(
    session: Session, *, context: SessionContext, after: str | None, limit: int,
) -> WorkspaceConductReportPage:
    if context.native_session_id is not None:
        raise HTTPException(403, "Workspace report intake requires a browser session.")
    company, memberships = lock_company_memberships_for_oauth(
        session, company_id=context.company.id, membership_ids=(context.membership.id,),
    )
    actor = memberships.get(context.membership.id)
    if (
        company is None or not company.is_active or actor is None or not actor.is_active
        or not actor.user.is_active or actor.role != MembershipRole.OWNER
        or actor.user_id != context.user.id
        or _token_precedes_membership_cutoff(actor, token_issued_at=context.token_issued_at)
    ):
        raise HTTPException(403, "Workspace owner access is required.")
    page = _metadata_page(session, context=context, publisher=False, after=after, limit=limit)
    record_from_context(
        session, context, action="workspace_conduct.intake_read",
        target_type="workspace_conduct_report", actor_label="Workspace owner",
        metadata={"returned_count": len(page.reports)}, commit=True,
    )
    return page


def publisher_intake(
    session: Session,
    *,
    context: SessionContext,
    platform_admin: PlatformAdminMembership,
    after: str | None,
    limit: int,
) -> WorkspaceConductReportPage:
    page = _metadata_page(session, context=context, publisher=True, after=after, limit=limit)
    record_platform_audit(
        session, context=context, platform_admin=platform_admin,
        action="workspace_conduct.publisher_intake_read",
        target_type="workspace_conduct_report",
        metadata={"returned_count": len(page.reports)},
    )
    session.commit()
    return page
