"""Canonical Madrid aggregate service over existing IP lifecycle owners."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpCostItem,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocumentLink,
    IpRelationship,
    IpTrademarkParticularVersion,
    Matter,
    TrademarkApplication,
    TrademarkInternationalRegistration,
)
from caseops_api.schemas.ip_international import (
    TrademarkInternationalActionRequest,
    TrademarkInternationalActionResponse,
    TrademarkInternationalRecordCreateRequest,
    TrademarkInternationalRecordPageResponse,
    TrademarkInternationalRecordResponse,
    TrademarkInternationalWorkspaceResponse,
)
from caseops_api.schemas.ip_lifecycle import (
    IpDocketEventCreateRequest,
    IpDocketEventResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_cost_lineage import active_ip_cost_predicate
from caseops_api.services.ip_deadline_workflow import deadline_workspace
from caseops_api.services.ip_document_workflow import list_linked_ip_documents
from caseops_api.services.ip_lifecycle import append_ip_docket_event, list_ip_docket_events
from caseops_api.services.ip_operations import (
    _lock_ip_dockets_in_stable_order,
    _lock_ip_writer_context,
    get_ip_docket,
)
from caseops_api.services.matter_access import (
    seed_restricted_ip_creator_access,
    visible_ip_dockets_filter,
)
from caseops_api.services.provider_adapter_catalog import provider_adapter_definition
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
        statement = statement.where(TrademarkInternationalRegistration.record_kind == record_kind)
    if parent_registration_id:
        statement = statement.where(
            TrademarkInternationalRegistration.parent_registration_id == parent_registration_id
        )
    total = (
        session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    )
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
        session.add(
            IpTrademarkParticularVersion(
                company_id=context.company.id,
                docket_id=docket.id,
                version=1,
                form_key=payload.form_kind or "MADRID_RECORD",
                form_version="source-recorded-v1",
                mark_kind="word",
                representation_json={
                    "text": payload.mark_name.strip(),
                    "evidence_reference": payload.source_reference.strip(),
                },
                classes_json=[
                    {
                        "class_number": class_number,
                        "specification": payload.goods_services[str(class_number)],
                    }
                    for class_number in payload.classes
                ],
                use_priority_json={"claims": payload.priority_claims}
                if payload.priority_claims
                else None,
                parties_json=[{"role": "holder", "name": payload.holder_name.strip()}],
                agent_json=(
                    {"name": payload.local_agent_name.strip()} if payload.local_agent_name else None
                ),
                filing_manifest_json=[
                    {
                        "key": "madrid_source",
                        "label": "Madrid source record",
                        "required": True,
                        "evidence_reference": payload.source_reference.strip(),
                    }
                ],
                readiness_status="ready",
                readiness_errors_json=[],
                created_by_membership_id=context.membership.id,
                finalized_at=datetime.now(UTC),
            )
        )
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


_NATIONAL_ACTIONS = {
    "national_examination_recorded",
    "provisional_refusal_recorded",
    "response_filed",
    "publication_recorded",
    "opposition_recorded",
    "grant_statement_recorded",
    "refusal_statement_recorded",
}
_OUTBOUND_REGISTRATION_ACTIONS = {
    "form_prepared",
    "office_of_origin_certified",
    "wipo_irregularity",
    "international_registration_recorded",
    "dependency_impact_review",
    "central_attack_impact_review",
    "subsequent_designation_recorded",
}
_IMPACT_REVIEW_ACTIONS = {
    "dependency_impact_review",
    "central_attack_impact_review",
}


def _validate_owned_refs(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    payload: TrademarkInternationalActionRequest,
) -> None:
    def missing_ids(model, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        rows = set(
            session.scalars(
                select(model.id).where(
                    model.company_id == company_id,
                    model.docket_id == docket_id,
                    model.id.in_(set(ids)),
                )
            )
        )
        return set(ids) - rows

    missing_deadlines = missing_ids(IpDeadline, payload.deadline_refs)
    if missing_deadlines:
        raise HTTPException(
            status_code=422,
            detail="Madrid deadline references must belong to this designation docket.",
        )
    active_costs = set(
        session.scalars(
            select(IpCostItem.id).where(
                IpCostItem.company_id == company_id,
                IpCostItem.docket_id == docket_id,
                IpCostItem.id.in_(set(payload.cost_item_refs)),
                active_ip_cost_predicate(),
            )
        )
    )
    missing_costs = set(payload.cost_item_refs) - active_costs
    if missing_costs:
        raise HTTPException(
            status_code=422,
            detail="Madrid cost references must be active and belong to this designation docket.",
        )
    if payload.document_refs:
        event_ids = select(IpDocketEvent.id).where(
            IpDocketEvent.company_id == company_id,
            IpDocketEvent.docket_id == docket_id,
        )
        deadline_ids = select(IpDeadline.id).where(
            IpDeadline.company_id == company_id,
            IpDeadline.docket_id == docket_id,
        )
        linked_ids = set(
            session.scalars(
                select(IpDocumentLink.document_id).where(
                    IpDocumentLink.company_id == company_id,
                    or_(
                        (IpDocumentLink.target_type == "docket")
                        & (IpDocumentLink.target_id == docket_id),
                        (IpDocumentLink.target_type == "event")
                        & (IpDocumentLink.target_id.in_(event_ids)),
                        (IpDocumentLink.target_type == "deadline")
                        & (IpDocumentLink.target_id.in_(deadline_ids)),
                    ),
                )
            )
        )
        if set(payload.document_refs) - linked_ids:
            raise HTTPException(
                status_code=422,
                detail="Madrid document references must be linked to this designation docket.",
            )


def _assert_action_scope(
    row: TrademarkInternationalRegistration,
    payload: TrademarkInternationalActionRequest,
) -> None:
    if payload.action_kind in _NATIONAL_ACTIONS and row.record_kind != "international_designation":
        raise HTTPException(
            status_code=422,
            detail="National-office workflow actions belong to one designation, not the IR.",
        )
    if payload.action_kind in _OUTBOUND_REGISTRATION_ACTIONS and (
        row.record_kind != "international_registration" or row.direction != "outbound"
    ):
        raise HTTPException(
            status_code=422,
            detail="This action belongs to an outbound international registration.",
        )
    if (
        payload.action_kind == "wipo_notification_recorded"
        and row.record_kind != "international_designation"
    ):
        raise HTTPException(
            status_code=422,
            detail="WIPO designation notification belongs to one designation docket.",
        )
    if (
        payload.action_kind == "local_agent_instruction"
        and row.record_kind != "international_designation"
    ):
        raise HTTPException(
            status_code=422,
            detail="Local-agent instruction belongs to one designation docket.",
        )
    if payload.national_status is not None and row.record_kind != "international_designation":
        raise HTTPException(
            status_code=422,
            detail="The international registration cannot own a national-office status.",
        )


def _source_candidate(
    session: Session,
    *,
    row: TrademarkInternationalRegistration,
    payload: TrademarkInternationalActionRequest,
) -> IpDocketEvent | None:
    if payload.action_kind != "source_reconciliation":
        return None
    candidate = session.scalar(
        select(IpDocketEvent)
        .where(
            IpDocketEvent.id == payload.reconciles_event_id,
            IpDocketEvent.company_id == row.company_id,
            IpDocketEvent.docket_id == row.docket_id,
            IpDocketEvent.event_kind == "madrid_action",
            IpDocketEvent.candidate_status == "candidate",
        )
        .with_for_update()
    )
    if candidate is None or candidate.payload_json.get("action_kind") != "source_snapshot":
        raise HTTPException(status_code=404, detail="Madrid source candidate not found.")
    already_reconciled = session.scalar(
        select(IpDocketEvent.id).where(
            IpDocketEvent.company_id == row.company_id,
            IpDocketEvent.docket_id == row.docket_id,
            IpDocketEvent.reconciles_event_id == candidate.id,
        )
    )
    if already_reconciled is not None:
        raise HTTPException(
            status_code=409, detail="Madrid source candidate is already reconciled."
        )
    return candidate


def record_international_action(
    session: Session,
    *,
    context: SessionContext,
    record_id: str,
    payload: TrademarkInternationalActionRequest,
) -> TrademarkInternationalActionResponse:
    visible = get_international_record(
        session,
        context=context,
        record_id=record_id,
    )
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )
    _lock_ip_dockets_in_stable_order(
        session,
        context=context,
        docket_ids={visible.docket_id},
        required_capability="ip:write",
    )
    row = session.scalar(
        select(TrademarkInternationalRegistration)
        .where(
            TrademarkInternationalRegistration.id == visible.id,
            TrademarkInternationalRegistration.company_id == context.company.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Madrid record not found.")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Madrid record version changed; reload.")
    _assert_action_scope(row, payload)
    _validate_owned_refs(
        session,
        company_id=row.company_id,
        docket_id=row.docket_id,
        payload=payload,
    )
    candidate = _source_candidate(session, row=row, payload=payload)

    event_details = dict(payload.details)
    event_details.update(
        {
            "action_kind": payload.action_kind,
            "authority": payload.authority,
            "source_url": payload.source_url,
            "source_reference": payload.source_reference,
            "source_retrieved_at": payload.source_retrieved_at.isoformat(),
            "wipo_status": payload.wipo_status,
            "national_status": payload.national_status,
            "local_agent_name": payload.local_agent_name,
            "ir_number": payload.ir_number,
            "international_registration_date": (
                payload.international_registration_date.isoformat()
                if payload.international_registration_date
                else None
            ),
            "notification_date": (
                payload.notification_date.isoformat() if payload.notification_date else None
            ),
            "publication_date": (
                payload.publication_date.isoformat() if payload.publication_date else None
            ),
            "statement_date": (
                payload.statement_date.isoformat() if payload.statement_date else None
            ),
            "renewal_due_date": (
                payload.renewal_due_date.isoformat() if payload.renewal_due_date else None
            ),
            "cost_item_refs": payload.cost_item_refs,
            "record_version_before": row.version,
        }
    )
    if candidate is not None:
        event_details["candidate_authority"] = candidate.payload_json.get("authority")
        event_details["candidate_source_url"] = candidate.payload_json.get("source_url")

    event = append_ip_docket_event(
        session,
        context=context,
        docket_id=row.docket_id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            event_kind="madrid_action",
            source="registry" if payload.action_kind == "source_snapshot" else "manual",
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            resulting_deadline_refs=payload.deadline_refs,
            candidate_status=(
                "candidate"
                if payload.action_kind == "source_snapshot"
                else "reconciled"
                if payload.action_kind == "source_reconciliation"
                else "confirmed"
            ),
            reconciles_event_id=payload.reconciles_event_id,
            reconciliation_decision=payload.reconciliation_decision,
            acknowledged_exception_codes=payload.acknowledged_exception_codes,
            payload=event_details,
        ),
        commit=False,
    )

    status_applied = False
    if candidate is not None and payload.reconciliation_decision != "reject_candidate":
        authority = candidate.payload_json.get("authority")
        if authority == "wipo" and candidate.payload_json.get("wipo_status"):
            row.wipo_status = str(candidate.payload_json["wipo_status"])
            status_applied = True
        elif authority == "national_office" and candidate.payload_json.get("national_status"):
            if row.record_kind != "international_designation":
                raise HTTPException(
                    status_code=422,
                    detail="National-office source candidate cannot update an IR status.",
                )
            row.national_status = str(candidate.payload_json["national_status"])
            status_applied = True

    if payload.action_kind == "local_agent_instruction":
        row.local_agent_name = (payload.local_agent_name or "").strip() or None
    if payload.action_kind == "international_registration_recorded":
        if not payload.ir_number or not payload.international_registration_date:
            raise HTTPException(
                status_code=422,
                detail="International registration requires IR number and registration date.",
            )
        row.ir_number = payload.ir_number.strip()
        row.international_registration_date = payload.international_registration_date
    if payload.action_kind == "wipo_notification_recorded":
        if not payload.notification_date:
            raise HTTPException(status_code=422, detail="WIPO notification date is required.")
        row.notification_date = payload.notification_date
    if payload.action_kind == "publication_recorded":
        if not payload.publication_date:
            raise HTTPException(status_code=422, detail="Publication date is required.")
        row.publication_date = payload.publication_date
    if payload.action_kind in {"grant_statement_recorded", "refusal_statement_recorded"}:
        if not payload.statement_date:
            raise HTTPException(status_code=422, detail="Statement date is required.")
        row.statement_date = payload.statement_date
    if payload.action_kind == "renewal_transaction":
        if not payload.renewal_due_date:
            raise HTTPException(status_code=422, detail="Next renewal due date is required.")
        row.renewal_due_date = payload.renewal_due_date

    row.version += 1
    row.updated_by_membership_id = context.membership.id
    row.updated_at = datetime.now(UTC)
    event.payload_json = {**event.payload_json, "record_version_after": row.version}
    record_from_context(
        session,
        context,
        action="ip_madrid.action_recorded",
        target_type="trademark_international_registration",
        target_id=row.id,
        ip_docket_id=row.docket_id,
        metadata={
            "action_kind": payload.action_kind,
            "authority": payload.authority,
            "event_id": event.id,
            "status_applied": status_applied,
            "impact_review_only": payload.action_kind in _IMPACT_REVIEW_ACTIONS,
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Madrid identity or version changed while recording the action.",
        ) from exc
    session.refresh(row)
    session.refresh(event)
    return TrademarkInternationalActionResponse(
        record=TrademarkInternationalRecordResponse.model_validate(row),
        event=IpDocketEventResponse.model_validate(event),
        status_applied=status_applied,
        impact_review_only=payload.action_kind in _IMPACT_REVIEW_ACTIONS,
    )


def international_workspace(
    session: Session,
    *,
    context: SessionContext,
    record_id: str,
) -> TrademarkInternationalWorkspaceResponse:
    row = get_international_record(session, context=context, record_id=record_id)
    docket = get_ip_docket(session, context=context, docket_id=row.docket_id)
    events = list_ip_docket_events(
        session,
        context=context,
        docket_id=row.docket_id,
    )
    deadline_data = deadline_workspace(
        session,
        context=context,
        docket_id=row.docket_id,
    )
    event_ids = {event.id for event in events}
    deadline_ids = {deadline.id for deadline in deadline_data.deadlines}
    linked_documents = list_linked_ip_documents(
        session,
        context=context,
        docket_id=row.docket_id,
        event_ids=event_ids,
        deadline_ids=deadline_ids,
        limit=100,
    )

    parent = None
    if row.parent_registration_id:
        parent_row = get_international_record(
            session,
            context=context,
            record_id=row.parent_registration_id,
        )
        parent = TrademarkInternationalRecordResponse.model_validate(parent_row)
    designations = []
    if row.record_kind == "international_registration":
        designation_page = list_international_records(
            session,
            context=context,
            record_kind="international_designation",
            parent_registration_id=row.id,
            limit=100,
            offset=0,
        )
        designations = designation_page.items

    reconciled_ids = {
        event.reconciles_event_id for event in events if event.reconciles_event_id is not None
    }
    unresolved = [
        event
        for event in events
        if event.event_kind == "madrid_action"
        and event.candidate_status == "candidate"
        and event.id not in reconciled_ids
    ]
    gaps: list[str] = []
    if row.record_kind == "international_registration" and row.direction == "outbound":
        if row.basic_application_id is None:
            gaps.append("basic_indian_mark_missing")
        if not row.form_kind:
            gaps.append("madrid_form_missing")
        if not row.office_of_origin:
            gaps.append("office_of_origin_missing")
        if not designations:
            gaps.append("designation_missing")
    if not row.ir_number:
        gaps.append("ir_number_missing")
    if row.record_kind == "international_designation" and not row.national_status:
        gaps.append("national_status_unconfirmed")
    if not deadline_data.deadlines:
        gaps.append("deadline_missing")
    if not linked_documents:
        gaps.append("document_missing")
    if not any(cost.lineage_status == "active" for cost in docket.cost_items):
        gaps.append("fee_or_cost_missing")
    if unresolved:
        gaps.append("source_reconciliation_pending")

    actions: list[str] = []
    if "basic_indian_mark_missing" in gaps:
        actions.append("link_eligible_basic_indian_mark")
    if "madrid_form_missing" in gaps:
        actions.append("record_mm2_or_applicable_form")
    if "designation_missing" in gaps:
        actions.append("add_designated_member")
    if "ir_number_missing" in gaps:
        actions.append("record_international_registration")
    if "source_reconciliation_pending" in gaps:
        actions.append("reconcile_wipo_or_national_snapshot")
    if "deadline_missing" in gaps:
        actions.append("propose_and_confirm_madrid_deadline")
    if "document_missing" in gaps:
        actions.append("link_madrid_document")
    if "fee_or_cost_missing" in gaps:
        actions.append("record_madrid_fee_or_cost")

    provider = provider_adapter_definition("wipo-madrid")
    if provider is None:
        raise RuntimeError("WIPO Madrid provider contract is missing from the catalog.")

    return TrademarkInternationalWorkspaceResponse(
        record=TrademarkInternationalRecordResponse.model_validate(row),
        docket=docket,
        parent=parent,
        designations=designations,
        events=[IpDocketEventResponse.model_validate(event) for event in events],
        deadlines=deadline_data.deadlines,
        documents=linked_documents,
        costs=docket.cost_items,
        unresolved_source_candidates=[
            IpDocketEventResponse.model_validate(event) for event in unresolved
        ],
        data_quality_gaps=gaps,
        next_required_actions=actions,
        provider_mode="manual_sourced_only",
        provider_activation_blockers=list(provider.activation_blockers),
    )
