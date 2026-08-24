from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import CompanyMembership, IpDocketRecord, IpMatterLink, Matter
from caseops_api.schemas.ip_matter_links import (
    IpDocketMatterLinkListResponse,
    IpMatterLifecycleRecord,
    IpMatterLinkCreateRequest,
    IpMatterLinkRecord,
    IpMatterLinkRetireRequest,
    IpMatterLinkRetireResponse,
    MatterIpLinkListResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.matter_access import (
    assert_access,
    assert_ip_docket_access,
    can_access,
    can_access_ip_docket,
)
from caseops_api.services.matter_operational_guard import assert_operational_matter
from caseops_api.services.session_context import SessionContext


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


def _access_mismatch(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    matter: Matter,
) -> bool:
    if docket.restricted != matter.restricted_access:
        return True
    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.is_active.is_(True),
            )
            .order_by(CompanyMembership.id)
        )
    )
    for membership in memberships:
        if membership.user is None or not membership.user.is_active:
            continue
        member_context = SessionContext(
            company=context.company,
            membership=membership,
            user=membership.user,
        )
        if can_access_ip_docket(
            session, context=member_context, docket=docket
        ) != can_access(session, context=member_context, matter=matter):
            return True
    return False


def _record(
    session: Session,
    *,
    context: SessionContext,
    link: IpMatterLink,
    docket: IpDocketRecord,
    matter: Matter,
) -> IpMatterLinkRecord:
    return IpMatterLinkRecord(
        id=link.id,
        company_id=link.company_id,
        docket_id=link.docket_id,
        matter_id=link.matter_id,
        relation_role=link.relation_role,
        effective_from=link.effective_from,
        retired_at=link.retired_at,
        source=link.source,
        source_reference=link.source_reference,
        reason=link.reason,
        retirement_reason=link.retirement_reason,
        created_by_membership_id=link.created_by_membership_id,
        retired_by_membership_id=link.retired_by_membership_id,
        access_mismatch_warning=_access_mismatch(
            session, context=context, docket=docket, matter=matter
        ),
        lifecycle=IpMatterLifecycleRecord(
            matter_id=matter.id,
            matter_code=matter.matter_code,
            matter_title=matter.title,
            matter_status=str(getattr(matter.status, "value", matter.status)),
            matter_is_active=matter.is_active,
            docket_id=docket.id,
            docket_title=docket.title,
            docket_status=docket.status,
            docket_is_active=docket.is_active,
        ),
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


def _visible_records(
    session: Session,
    *,
    context: SessionContext,
    rows: list[IpMatterLink],
) -> list[IpMatterLinkRecord]:
    records: list[IpMatterLinkRecord] = []
    for link in rows:
        docket = session.scalar(
            select(IpDocketRecord).where(
                IpDocketRecord.id == link.docket_id,
                IpDocketRecord.company_id == context.company.id,
            )
        )
        matter = session.scalar(
            select(Matter).where(
                Matter.id == link.matter_id,
                Matter.company_id == context.company.id,
            )
        )
        if (
            docket is None
            or matter is None
            or not can_access_ip_docket(session, context=context, docket=docket)
            or not can_access(session, context=context, matter=matter)
        ):
            continue
        records.append(
            _record(session, context=context, link=link, docket=docket, matter=matter)
        )
    return records


def list_docket_matter_links(
    session: Session, *, context: SessionContext, docket_id: str
) -> IpDocketMatterLinkListResponse:
    docket = session.scalar(
        select(IpDocketRecord).where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
    )
    if docket is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    assert_ip_docket_access(session, context=context, docket=docket)
    rows = list(
        session.scalars(
            select(IpMatterLink)
            .where(
                IpMatterLink.company_id == context.company.id,
                IpMatterLink.docket_id == docket.id,
            )
            .order_by(
                IpMatterLink.retired_at.is_not(None),
                IpMatterLink.effective_from.desc(),
                IpMatterLink.id,
            )
        )
    )
    records = _visible_records(session, context=context, rows=rows)
    return IpDocketMatterLinkListResponse(
        docket_id=docket.id,
        links=records,
        count=len(records),
        active_count=sum(row.retired_at is None for row in records),
    )


def list_matter_ip_links(
    session: Session, *, context: SessionContext, matter_id: str
) -> MatterIpLinkListResponse:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    rows = list(
        session.scalars(
            select(IpMatterLink)
            .where(
                IpMatterLink.company_id == context.company.id,
                IpMatterLink.matter_id == matter.id,
            )
            .order_by(
                IpMatterLink.retired_at.is_not(None),
                IpMatterLink.effective_from.desc(),
                IpMatterLink.id,
            )
        )
    )
    records = _visible_records(session, context=context, rows=rows)
    return MatterIpLinkListResponse(
        matter_id=matter.id,
        links=records,
        count=len(records),
        active_count=sum(row.retired_at is None for row in records),
    )


def create_matter_link(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpMatterLinkCreateRequest,
    commit: bool = True,
) -> IpMatterLinkRecord:
    context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:write"
    )
    matter = session.scalar(
        select(Matter)
        .where(
            Matter.id == payload.matter_id,
            Matter.company_id == context.company.id,
        )
        .with_for_update(of=Matter)
        .execution_options(populate_existing=True)
    )
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    docket = session.scalar(
        select(IpDocketRecord)
        .where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
        .with_for_update(of=IpDocketRecord)
        .execution_options(populate_existing=True)
    )
    if docket is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    assert_ip_docket_access(session, context=context, docket=docket)
    if _aware(docket.updated_at) != _aware(payload.expected_docket_updated_at):
        raise _conflict("ip_docket_version_conflict", "The IP record changed; reload and retry.")
    if payload.relation_role == "operational":
        assert_operational_matter(session, matter=matter, lock_for_write=False)
        active_operational = session.scalar(
            select(IpMatterLink)
            .where(
                IpMatterLink.company_id == context.company.id,
                IpMatterLink.docket_id == docket.id,
                IpMatterLink.relation_role == "operational",
                IpMatterLink.retired_at.is_(None),
            )
            .limit(1)
        )
        if active_operational is not None or docket.matter_id not in (None, matter.id):
            raise _conflict(
                "ip_operational_matter_exists",
                "Retire the current operational Matter link before assigning another.",
            )
    now = datetime.now(UTC)
    effective_from = payload.effective_from or now
    if _aware(effective_from) > now:
        raise HTTPException(status_code=422, detail="effective_from cannot be in the future.")
    link = IpMatterLink(
        company_id=context.company.id,
        docket_id=docket.id,
        matter_id=matter.id,
        relation_role=payload.relation_role,
        effective_from=effective_from,
        source="manual",
        source_reference=payload.source_reference,
        reason=payload.reason.strip(),
        created_by_membership_id=context.membership.id,
    )
    session.add(link)
    if payload.relation_role == "operational":
        docket.matter_id = matter.id
    docket.updated_at = now
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise _conflict(
            "ip_matter_link_duplicate",
            "That active Matter link already exists.",
        ) from exc
    record_from_context(
        session,
        context,
        action="ip_matter_link.created",
        target_type="ip_matter_link",
        target_id=link.id,
        matter_id=matter.id,
        ip_docket_id=docket.id,
        metadata={"relation_role": link.relation_role, "effective_from": link.effective_from},
    )
    if commit:
        session.commit()
        session.refresh(link)
    return _record(session, context=context, link=link, docket=docket, matter=matter)


def retire_matter_link(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    link_id: str,
    payload: IpMatterLinkRetireRequest,
) -> IpMatterLinkRetireResponse:
    context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:write"
    )
    discovered = session.scalar(
        select(IpMatterLink).where(
            IpMatterLink.id == link_id,
            IpMatterLink.docket_id == docket_id,
            IpMatterLink.company_id == context.company.id,
        )
    )
    if discovered is None:
        raise HTTPException(status_code=404, detail="IP Matter link not found.")
    matter = session.scalar(
        select(Matter)
        .where(
            Matter.id == discovered.matter_id,
            Matter.company_id == context.company.id,
        )
        .with_for_update(of=Matter)
    )
    docket = session.scalar(
        select(IpDocketRecord)
        .where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
        .with_for_update(of=IpDocketRecord)
        .execution_options(populate_existing=True)
    )
    link = session.scalar(
        select(IpMatterLink)
        .where(
            IpMatterLink.id == link_id,
            IpMatterLink.company_id == context.company.id,
        )
        .with_for_update(of=IpMatterLink)
        .execution_options(populate_existing=True)
    )
    if matter is None or docket is None or link is None:
        raise HTTPException(status_code=404, detail="IP Matter link not found.")
    assert_access(session, context=context, matter=matter)
    assert_ip_docket_access(session, context=context, docket=docket)
    if link.retired_at is not None:
        raise _conflict("ip_matter_link_retired", "That Matter link is already retired.")
    if _aware(link.updated_at) != _aware(payload.expected_link_updated_at):
        raise _conflict(
            "ip_matter_link_version_conflict",
            "The Matter link changed; reload and retry.",
        )
    if _aware(docket.updated_at) != _aware(payload.expected_docket_updated_at):
        raise _conflict("ip_docket_version_conflict", "The IP record changed; reload and retry.")
    now = datetime.now(UTC)
    retired_at = payload.retired_at or now
    if _aware(retired_at) < _aware(link.effective_from) or _aware(retired_at) > now:
        raise HTTPException(
            status_code=422,
            detail="retired_at must be between effective_from and the current time.",
        )
    link.retired_at = retired_at
    link.retired_by_membership_id = context.membership.id
    link.retirement_reason = payload.reason.strip()
    link.updated_at = now
    pointer_cleared = link.relation_role == "operational" and docket.matter_id == matter.id
    if pointer_cleared:
        docket.matter_id = None
    docket.updated_at = now
    record_from_context(
        session,
        context,
        action="ip_matter_link.retired",
        target_type="ip_matter_link",
        target_id=link.id,
        matter_id=matter.id,
        ip_docket_id=docket.id,
        metadata={"relation_role": link.relation_role, "retired_at": retired_at},
    )
    session.commit()
    session.refresh(link)
    return IpMatterLinkRetireResponse(
        link=_record(session, context=context, link=link, docket=docket, matter=matter),
        operational_pointer_cleared=pointer_cleared,
    )
