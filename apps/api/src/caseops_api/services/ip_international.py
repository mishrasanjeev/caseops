"""Canonical Madrid aggregate service over existing IP lifecycle owners."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDocketRecord,
    IpRelationship,
    Matter,
    TrademarkApplication,
    TrademarkInternationalRegistration,
)
from caseops_api.schemas.ip_international import (
    TrademarkInternationalRecordCreateRequest,
    TrademarkInternationalRecordPageResponse,
    TrademarkInternationalRecordResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_operations import (
    _lock_ip_dockets_in_stable_order,
    _lock_ip_writer_context,
)
from caseops_api.services.matter_access import (
    seed_restricted_ip_creator_access,
    visible_ip_dockets_filter,
)
from caseops_api.services.session_context import SessionContext


def _visible_records_statement(session: Session, *, context: SessionContext):
    return (
        select(TrademarkInternationalRegistration)
        .join(
            IpDocketRecord,
            (IpDocketRecord.id == TrademarkInternationalRegistration.docket_id)
            & (IpDocketRecord.company_id == TrademarkInternationalRegistration.company_id),
        )
        .outerjoin(
            Matter,
            (Matter.id == IpDocketRecord.matter_id)
            & (Matter.company_id == IpDocketRecord.company_id),
        )
        .where(
            TrademarkInternationalRegistration.company_id == context.company.id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            or_(IpDocketRecord.matter_id.is_(None), Matter.is_active.is_(True)),
            visible_ip_dockets_filter(session, context=context),
        )
    )


def list_international_records(
    session: Session,
    *,
    context: SessionContext,
    record_kind: str | None,
    parent_registration_id: str | None,
    limit: int,
    offset: int,
) -> TrademarkInternationalRecordPageResponse:
    statement = _visible_records_statement(session, context=context)
    if record_kind:
        statement = statement.where(
            TrademarkInternationalRegistration.record_kind == record_kind
        )
    if parent_registration_id:
        statement = statement.where(
            TrademarkInternationalRegistration.parent_registration_id
            == parent_registration_id
        )
    total = session.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0
    rows = list(
        session.scalars(
            statement.order_by(
                TrademarkInternationalRegistration.updated_at.desc(),
                TrademarkInternationalRegistration.id,
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return TrademarkInternationalRecordPageResponse(
        items=[TrademarkInternationalRecordResponse.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_international_record(
    session: Session,
    *,
    context: SessionContext,
    record_id: str,
) -> TrademarkInternationalRegistration:
    row = session.scalar(
        _visible_records_statement(session, context=context).where(
            TrademarkInternationalRegistration.id == record_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Madrid record not found.")
    return row


def create_international_record(
    session: Session,
    *,
    context: SessionContext,
    payload: TrademarkInternationalRecordCreateRequest,
) -> TrademarkInternationalRegistration:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )
    related_ids = {payload.docket_id} if payload.docket_id else set()
    parent: TrademarkInternationalRegistration | None = None
    basic_application: TrademarkApplication | None = None

    if payload.parent_registration_id:
        parent = session.scalar(
            select(TrademarkInternationalRegistration).where(
                TrademarkInternationalRegistration.id == payload.parent_registration_id,
                TrademarkInternationalRegistration.company_id == context.company.id,
                TrademarkInternationalRegistration.record_kind == "international_registration",
            )
        )
        if parent is None:
            raise HTTPException(status_code=404, detail="Parent Madrid registration not found.")
        related_ids.add(parent.docket_id)

    if payload.basic_application_id:
        basic_application = session.scalar(
            select(TrademarkApplication).where(
                TrademarkApplication.id == payload.basic_application_id,
                TrademarkApplication.company_id == context.company.id,
                TrademarkApplication.is_active.is_(True),
            )
        )
        if basic_application is None:
            raise HTTPException(status_code=404, detail="Basic trademark application not found.")
        related_ids.add(basic_application.docket_id)

    dockets = (
        _lock_ip_dockets_in_stable_order(
            session,
            context=context,
            docket_ids=related_ids,
            required_capability="ip:write",
        )
        if related_ids
        else {}
    )
    if payload.docket_id:
        docket = dockets[payload.docket_id]
    else:
        docket = IpDocketRecord(
            company_id=context.company.id,
            record_type=payload.record_kind,
            title=(payload.docket_title or payload.mark_name).strip(),
            primary_identifier=None,
            status="ready",
            restricted=payload.restricted,
            current_version=1,
            created_by_membership_id=context.membership.id,
        )
        session.add(docket)
        session.flush()
        seed_restricted_ip_creator_access(
            session,
            context=context,
            docket=docket,
        )
        record_from_context(
            session,
            context,
            action="ip_docket.created",
            target_type="ip_docket_record",
            target_id=docket.id,
            ip_docket_id=docket.id,
            metadata={"record_type": docket.record_type, "source": "madrid_record"},
        )
    expected_docket_type = payload.record_kind
    if docket.record_type != expected_docket_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Madrid {payload.record_kind} requires a {expected_docket_type} docket.",
        )
    if parent is not None and payload.direction != parent.direction:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A designation direction must match its parent registration.",
        )
    if basic_application is not None:
        basic_docket = dockets[basic_application.docket_id]
        if basic_docket.record_type != "trademark":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The Madrid basic mark must use a trademark application docket.",
            )
        if basic_application.jurisdiction.upper() != "IN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An outbound Madrid registration requires a basic Indian application.",
            )

    row = TrademarkInternationalRegistration(
        company_id=context.company.id,
        docket_id=docket.id,
        record_kind=payload.record_kind,
        direction=payload.direction,
        parent_registration_id=payload.parent_registration_id,
        basic_application_id=payload.basic_application_id,
        international_application_number=payload.international_application_number,
        ir_number=payload.ir_number,
        wipo_reference=payload.wipo_reference.strip(),
        holder_name=payload.holder_name.strip(),
        mark_name=payload.mark_name.strip(),
        office_of_origin=(payload.office_of_origin or None),
        designated_member_code=(payload.designated_member_code or None),
        designated_office=(payload.designated_office or None),
        jurisdiction=(payload.jurisdiction or None),
        designation_kind=payload.designation_kind,
        classes_json=payload.classes,
        goods_services_json=payload.goods_services,
        priority_claims_json=payload.priority_claims,
        form_kind=payload.form_kind,
        wipo_status=payload.wipo_status,
        national_status=payload.national_status,
        local_agent_name=payload.local_agent_name,
        source_url=payload.source_url,
        source_reference=payload.source_reference.strip(),
        source_retrieved_at=payload.source_retrieved_at,
        application_date=payload.application_date,
        international_registration_date=payload.international_registration_date,
        designation_effective_date=payload.designation_effective_date,
        notification_date=payload.notification_date,
        publication_date=payload.publication_date,
        statement_date=payload.statement_date,
        dependency_end_date=payload.dependency_end_date,
        renewal_due_date=payload.renewal_due_date,
        created_by_membership_id=context.membership.id,
        updated_by_membership_id=context.membership.id,
    )
    session.add(row)

    if basic_application is not None:
        session.add(
            IpRelationship(
                company_id=context.company.id,
                source_docket_id=row.docket_id,
                target_docket_id=basic_application.docket_id,
                relationship_kind="basic_mark",
                effective_from=payload.application_date
                or payload.international_registration_date
                or payload.source_retrieved_at.date(),
                source=payload.source_reference[:120],
            )
        )
    if parent is not None:
        assert payload.designation_effective_date is not None
        session.add(
            IpRelationship(
                company_id=context.company.id,
                source_docket_id=parent.docket_id,
                target_docket_id=row.docket_id,
                relationship_kind="madrid_designation",
                effective_from=payload.designation_effective_date,
                source=payload.source_reference[:120],
            )
        )
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A Madrid record with this docket, IR number, or designation identity "
                "already exists."
            ),
        ) from exc

    record_from_context(
        session,
        context,
        action="ip_madrid.record_created",
        target_type="trademark_international_registration",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "record_kind": row.record_kind,
            "direction": row.direction,
            "parent_registration_id": row.parent_registration_id,
            "basic_application_id": row.basic_application_id,
            "source_reference": row.source_reference,
        },
    )
    session.commit()
    session.refresh(row)
    return row
