from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeIpLink,
    IpCostItem,
    IpDeadlineCoverage,
    IpDeadlineIncident,
    IpDocketRecord,
    IpTitleInterest,
    IpTrademarkParticularVersion,
    Matter,
    MatterDeadline,
    UserCalendarConnection,
)
from caseops_api.schemas.ip_operations import (
    IpCostItemCreateRequest,
    IpCostItemRecord,
    IpDeadlineCoverageCreateRequest,
    IpDeadlineCoverageReassignRequest,
    IpDeadlineCoverageRecord,
    IpDeadlineIncidentCreateRequest,
    IpDeadlineIncidentRecord,
    IpDeadlineIncidentVerifyRequest,
    IpDocketControlReport,
    IpDocketCreateRequest,
    IpDocketListResponse,
    IpDocketRecordResponse,
    IpDocketVersionCreateRequest,
    IpNoticeLinkCreateRequest,
    IpNoticeLinkRecord,
    IpTitleInterestCreateRequest,
    IpTitleInterestRecord,
    TrademarkParticularPayload,
    TrademarkParticularVersionRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access, can_access
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
)
from caseops_api.services.session_context import SessionContext


def _now() -> datetime:
    return datetime.now(UTC)


def _readiness_errors(payload: TrademarkParticularPayload) -> list[str]:
    errors: list[str] = []
    if not (payload.representation.get("text") or payload.representation.get("evidence_reference")):
        errors.append("A word/device representation or immutable evidence reference is required.")
    if not any(party.role == "applicant" for party in payload.parties):
        errors.append("At least one applicant party is required.")
    for row in payload.filing_manifest:
        if row.required and not row.evidence_reference:
            errors.append(f"Required filing item {row.label!r} has no evidence reference.")
    if payload.use_priority and payload.use_priority.get("claim_priority"):
        if not payload.use_priority.get("priority_document_reference"):
            errors.append("A priority claim requires a priority-document reference.")
    return errors


def _matter_for_docket(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
) -> Matter | None:
    if matter_id is None:
        return None
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return assert_operational_matter(session, matter=matter)


def _docket_or_404(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    for_update: bool = False,
) -> IpDocketRecord:
    stmt = select(IpDocketRecord).where(
        IpDocketRecord.id == docket_id,
        IpDocketRecord.company_id == context.company.id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    docket = session.scalar(stmt)
    if docket is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    if docket.archived_by_matter_disposal:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    if docket.matter_id:
        matter = session.get(Matter, docket.matter_id)
        if matter is None or not can_access(session, context=context, matter=matter):
            raise HTTPException(status_code=404, detail="IP docket record not found.")
        try:
            assert_operational_matter(session, matter=matter)
        except MatterNotOperationalError as exc:
            raise HTTPException(status_code=404, detail="IP docket record not found.") from exc
    elif docket.restricted:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    return docket


def _current_particulars(session: Session, docket: IpDocketRecord) -> IpTrademarkParticularVersion:
    row = session.scalar(
        select(IpTrademarkParticularVersion).where(
            IpTrademarkParticularVersion.docket_id == docket.id,
            IpTrademarkParticularVersion.company_id == docket.company_id,
            IpTrademarkParticularVersion.version == docket.current_version,
        )
    )
    if row is None:
        raise RuntimeError("IP docket current version is missing.")
    return row


def _serialize_docket(session: Session, docket: IpDocketRecord) -> IpDocketRecordResponse:
    particulars = _current_particulars(session, docket)
    notice_links = list(
        session.scalars(
            select(CompanyNoticeIpLink)
            .where(CompanyNoticeIpLink.docket_id == docket.id)
            .order_by(CompanyNoticeIpLink.created_at)
        ).all()
    )
    coverages = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(IpDeadlineCoverage.docket_id == docket.id)
            .order_by(IpDeadlineCoverage.created_at)
        ).all()
    )
    incidents = list(
        session.scalars(
            select(IpDeadlineIncident)
            .where(IpDeadlineIncident.docket_id == docket.id)
            .order_by(IpDeadlineIncident.created_at.desc())
        ).all()
    )
    interests = list(
        session.scalars(
            select(IpTitleInterest)
            .where(IpTitleInterest.docket_id == docket.id)
            .order_by(IpTitleInterest.effective_from, IpTitleInterest.created_at)
        ).all()
    )
    costs = list(
        session.scalars(
            select(IpCostItem)
            .where(IpCostItem.docket_id == docket.id)
            .order_by(IpCostItem.created_at)
        ).all()
    )
    return IpDocketRecordResponse(
        id=docket.id,
        company_id=docket.company_id,
        matter_id=docket.matter_id,
        record_type=docket.record_type,
        title=docket.title,
        primary_identifier=docket.primary_identifier,
        status=docket.status,
        restricted=docket.restricted,
        current_version=docket.current_version,
        current_particulars=TrademarkParticularVersionRecord.model_validate(particulars),
        notice_links=[IpNoticeLinkRecord.model_validate(row) for row in notice_links],
        deadline_coverages=[IpDeadlineCoverageRecord.model_validate(row) for row in coverages],
        deadline_incidents=[IpDeadlineIncidentRecord.model_validate(row) for row in incidents],
        title_interests=[IpTitleInterestRecord.model_validate(row) for row in interests],
        cost_items=[IpCostItemRecord.model_validate(row) for row in costs],
        created_at=docket.created_at,
        updated_at=docket.updated_at,
    )


def create_ip_docket(
    session: Session,
    *,
    context: SessionContext,
    payload: IpDocketCreateRequest,
) -> IpDocketRecordResponse:
    if payload.restricted and not payload.matter_id:
        raise HTTPException(
            status_code=422,
            detail="Restricted IP records require a Matter policy anchor.",
        )
    _matter_for_docket(session, context=context, matter_id=payload.matter_id)
    errors = _readiness_errors(payload.particulars)
    docket = IpDocketRecord(
        company_id=context.company.id,
        matter_id=payload.matter_id,
        record_type="trademark",
        title=payload.title.strip(),
        primary_identifier=(
            payload.primary_identifier.strip().upper() if payload.primary_identifier else None
        ),
        status="draft" if errors else "ready",
        restricted=payload.restricted,
        current_version=1,
        created_by_membership_id=context.membership.id,
    )
    session.add(docket)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That IP identifier already exists in this company.",
        ) from exc
    version = _new_version(
        docket=docket,
        context=context,
        payload=payload.particulars,
        version=1,
        errors=errors,
        finalize=not errors,
    )
    session.add(version)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_docket.created",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        metadata={"record_type": "trademark", "readiness_status": version.readiness_status},
    )
    session.commit()
    session.refresh(docket)
    return _serialize_docket(session, docket)


def _new_version(
    *,
    docket: IpDocketRecord,
    context: SessionContext,
    payload: TrademarkParticularPayload,
    version: int,
    errors: list[str],
    finalize: bool,
) -> IpTrademarkParticularVersion:
    return IpTrademarkParticularVersion(
        company_id=docket.company_id,
        docket_id=docket.id,
        version=version,
        form_key=payload.form_key,
        form_version=payload.form_version,
        mark_kind=payload.mark_kind,
        representation_json=payload.representation,
        classes_json=[row.model_dump() for row in payload.classes],
        use_priority_json=payload.use_priority,
        parties_json=[row.model_dump() for row in payload.parties],
        agent_json=payload.agent,
        filing_manifest_json=[row.model_dump() for row in payload.filing_manifest],
        readiness_status="ready" if not errors else "incomplete",
        readiness_errors_json=errors,
        created_by_membership_id=context.membership.id,
        finalized_at=_now() if finalize and not errors else None,
    )


def append_ip_docket_version(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDocketVersionCreateRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id, for_update=True)
    if docket.current_version != payload.expected_current_version:
        raise HTTPException(
            status_code=409,
            detail="IP docket version changed; reload before saving.",
        )
    errors = _readiness_errors(payload)
    if payload.finalize and errors:
        raise HTTPException(status_code=409, detail={"readiness_errors": errors})
    next_version = docket.current_version + 1
    session.add(
        _new_version(
            docket=docket,
            context=context,
            payload=payload,
            version=next_version,
            errors=errors,
            finalize=payload.finalize,
        )
    )
    docket.current_version = next_version
    docket.status = "ready" if payload.finalize and not errors else "draft"
    docket.updated_at = _now()
    record_from_context(
        session,
        context,
        action="ip_docket.version_created",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        metadata={"version": next_version, "status": docket.status},
    )
    session.commit()
    session.refresh(docket)
    return _serialize_docket(session, docket)


def list_ip_dockets(session: Session, *, context: SessionContext) -> IpDocketListResponse:
    rows = list(
        session.scalars(
            select(IpDocketRecord)
            .where(IpDocketRecord.company_id == context.company.id)
            .order_by(IpDocketRecord.updated_at.desc())
        ).all()
    )
    visible: list[IpDocketRecordResponse] = []
    for row in rows:
        if row.archived_by_matter_disposal:
            continue
        if row.matter_id:
            matter = session.get(Matter, row.matter_id)
            if matter is None or not can_access(session, context=context, matter=matter):
                continue
            try:
                assert_operational_matter(session, matter=matter)
            except MatterNotOperationalError:
                continue
        elif row.restricted:
            continue
        visible.append(_serialize_docket(session, row))
    return IpDocketListResponse(dockets=visible, count=len(visible))


def get_ip_docket(
    session: Session, *, context: SessionContext, docket_id: str
) -> IpDocketRecordResponse:
    return _serialize_docket(
        session,
        _docket_or_404(session, context=context, docket_id=docket_id),
    )


def _membership_or_404(
    session: Session, context: SessionContext, membership_id: str
) -> CompanyMembership:
    row = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == context.company.id,
        )
    )
    if row is None or not row.is_active:
        raise HTTPException(status_code=404, detail="Company membership not found.")
    return row


def add_ip_notice_link(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpNoticeLinkCreateRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    notice = session.scalar(
        select(CompanyNotice).where(
            CompanyNotice.id == payload.notice_id,
            CompanyNotice.company_id == context.company.id,
        )
    )
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    link = CompanyNoticeIpLink(
        company_id=context.company.id,
        docket_id=docket.id,
        notice_id=notice.id,
        link_kind=payload.link_kind,
        accepted_effect=payload.accepted_effect,
        created_by_membership_id=context.membership.id,
    )
    session.add(link)
    session.flush()
    record_from_context(
        session,
        context,
        action="company_notice.ip_linked",
        target_type="company_notice",
        target_id=notice.id,
        matter_id=docket.matter_id,
        metadata={"docket_id": docket.id, "link_kind": payload.link_kind},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Notice is already linked.") from exc
    return _serialize_docket(session, docket)


def _deadline_for_docket(
    session: Session,
    *,
    docket: IpDocketRecord,
    deadline_id: str,
) -> MatterDeadline:
    deadline = session.scalar(select(MatterDeadline).where(MatterDeadline.id == deadline_id))
    if deadline is None or not docket.matter_id or deadline.matter_id != docket.matter_id:
        raise HTTPException(
            status_code=404,
            detail="Operational deadline is not part of this IP record's Matter.",
        )
    return deadline


def add_ip_deadline_coverage(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDeadlineCoverageCreateRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    _deadline_for_docket(session, docket=docket, deadline_id=payload.matter_deadline_id)
    _membership_or_404(session, context, payload.responsible_membership_id)
    if payload.backup_membership_id:
        _membership_or_404(session, context, payload.backup_membership_id)
    membership_ids = tuple(
        value
        for value in (
            payload.responsible_membership_id,
            payload.backup_membership_id,
        )
        if value
    )
    connections = list(
        session.scalars(
            select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.membership_id.in_(membership_ids),
                UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
            )
        ).all()
    )
    row = IpDeadlineCoverage(
        company_id=context.company.id,
        docket_id=docket.id,
        matter_deadline_id=payload.matter_deadline_id,
        responsible_membership_id=payload.responsible_membership_id,
        backup_membership_id=payload.backup_membership_id,
        coverage_status=payload.coverage_status,
        calendar_projection_status="pending",
        accepted_at=_now() if payload.coverage_status == "accepted" else None,
    )
    session.add(row)
    for connection in connections:
        existing_sync = session.scalar(
            select(CalendarEventSync).where(
                CalendarEventSync.calendar_connection_id == connection.id,
                CalendarEventSync.source_type == "matter_deadline",
                CalendarEventSync.source_id == payload.matter_deadline_id,
            )
        )
        if existing_sync is None:
            session.add(
                CalendarEventSync(
                    company_id=context.company.id,
                    calendar_connection_id=connection.id,
                    source_type="matter_deadline",
                    source_id=payload.matter_deadline_id,
                    sync_status=CalendarEventSyncStatus.PENDING,
                )
            )
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_deadline_coverage.accepted",
        target_type="ip_deadline_coverage",
        target_id=row.id,
        matter_id=docket.matter_id,
        metadata={
            "matter_deadline_id": payload.matter_deadline_id,
            "calendar_projection_count": len(connections),
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Deadline coverage already exists.") from exc
    return _serialize_docket(session, docket)


def reassign_ip_deadline_coverage(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    coverage_id: str,
    payload: IpDeadlineCoverageReassignRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    coverage = session.scalar(
        select(IpDeadlineCoverage)
        .where(
            IpDeadlineCoverage.id == coverage_id,
            IpDeadlineCoverage.docket_id == docket.id,
            IpDeadlineCoverage.company_id == context.company.id,
        )
        .with_for_update()
    )
    if coverage is None:
        raise HTTPException(status_code=404, detail="Deadline coverage not found.")
    if coverage.responsible_membership_id != payload.expected_responsible_membership_id:
        raise HTTPException(
            status_code=409,
            detail="Deadline responsibility changed; reload before reassigning.",
        )
    _membership_or_404(session, context, payload.responsible_membership_id)
    if payload.backup_membership_id:
        _membership_or_404(session, context, payload.backup_membership_id)
    old_responsible = coverage.responsible_membership_id
    coverage.responsible_membership_id = payload.responsible_membership_id
    coverage.backup_membership_id = payload.backup_membership_id
    coverage.coverage_status = "reassigned"
    coverage.calendar_projection_status = "pending"
    coverage.accepted_at = _now()
    record_from_context(
        session,
        context,
        action="ip_deadline_coverage.reassigned",
        target_type="ip_deadline_coverage",
        target_id=coverage.id,
        matter_id=docket.matter_id,
        metadata={
            "old_responsible_membership_id": old_responsible,
            "new_responsible_membership_id": payload.responsible_membership_id,
            "reason": payload.reason,
        },
    )
    session.commit()
    return _serialize_docket(session, docket)


def add_ip_deadline_incident(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDeadlineIncidentCreateRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    for deadline_id in (payload.matter_deadline_id, payload.correction_deadline_id):
        if deadline_id:
            _deadline_for_docket(session, docket=docket, deadline_id=deadline_id)
    incident = IpDeadlineIncident(
        company_id=context.company.id,
        docket_id=docket.id,
        matter_deadline_id=payload.matter_deadline_id,
        severity=payload.severity,
        summary=payload.summary.strip(),
        impact_json=payload.impact,
        containment=payload.containment,
        correction_deadline_id=payload.correction_deadline_id,
        status="contained" if payload.containment else "open",
    )
    session.add(incident)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_deadline_incident.created",
        target_type="ip_deadline_incident",
        target_id=incident.id,
        matter_id=docket.matter_id,
        metadata={"severity": payload.severity, "status": incident.status},
    )
    session.commit()
    return _serialize_docket(session, docket)


def verify_ip_deadline_incident(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    incident_id: str,
    payload: IpDeadlineIncidentVerifyRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    incident = session.scalar(
        select(IpDeadlineIncident)
        .where(
            IpDeadlineIncident.id == incident_id,
            IpDeadlineIncident.docket_id == docket.id,
            IpDeadlineIncident.company_id == context.company.id,
        )
        .with_for_update()
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Deadline incident not found.")
    if not incident.containment:
        raise HTTPException(status_code=409, detail="Containment is required before verification.")
    incident.status = "verified"
    incident.corrective_action = payload.corrective_action.strip()
    incident.verified_at = _now()
    incident.verified_by_membership_id = context.membership.id
    record_from_context(
        session,
        context,
        action="ip_deadline_incident.verified",
        target_type="ip_deadline_incident",
        target_id=incident.id,
        matter_id=docket.matter_id,
        metadata={"severity": incident.severity},
    )
    session.commit()
    return _serialize_docket(session, docket)


def add_ip_title_interest(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpTitleInterestCreateRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    if payload.related_docket_id:
        _docket_or_404(session, context=context, docket_id=payload.related_docket_id)
    existing = list(
        session.scalars(
            select(IpTitleInterest).where(
                IpTitleInterest.company_id == context.company.id,
                IpTitleInterest.docket_id == docket.id,
            )
        ).all()
    )
    flags: list[str] = []
    new_until = payload.effective_until or date.max
    for row in existing:
        row_until = row.effective_until or date.max
        overlaps = payload.effective_from <= row_until and row.effective_from <= new_until
        if overlaps and row.party_name.casefold() != payload.party_name.casefold():
            flags.append(f"overlap:{row.id}")
    interest = IpTitleInterest(
        company_id=context.company.id,
        docket_id=docket.id,
        interest_type=payload.interest_type,
        party_name=payload.party_name.strip(),
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        related_docket_id=payload.related_docket_id,
        evidence_reference=payload.evidence_reference.strip(),
        recordal_status=payload.recordal_status,
        conflict_flags_json=flags,
    )
    session.add(interest)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_title_interest.created",
        target_type="ip_title_interest",
        target_id=interest.id,
        matter_id=docket.matter_id,
        metadata={
            "interest_type": payload.interest_type,
            "conflict_count": len(flags),
        },
    )
    session.commit()
    return _serialize_docket(session, docket)


def add_ip_cost_item(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpCostItemCreateRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    if not docket.matter_id:
        raise HTTPException(status_code=409, detail="IP costs require a Matter billing owner.")
    cost = IpCostItem(
        company_id=context.company.id,
        docket_id=docket.id,
        matter_id=docket.matter_id,
        category=payload.category,
        description=payload.description.strip(),
        amount_minor=payload.amount_minor,
        currency=payload.currency.upper(),
        evidence_reference=payload.evidence_reference.strip(),
        billing_link_type=payload.billing_link_type,
        billing_link_id=payload.billing_link_id,
        created_by_membership_id=context.membership.id,
    )
    session.add(cost)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_cost_item.created",
        target_type="ip_cost_item",
        target_id=cost.id,
        matter_id=docket.matter_id,
        metadata={"category": payload.category, "currency": payload.currency.upper()},
    )
    session.commit()
    return _serialize_docket(session, docket)


def ip_docket_control_report(session: Session, *, context: SessionContext) -> IpDocketControlReport:
    listing = list_ip_dockets(session, context=context)
    totals: dict[str, int] = {}
    for docket in listing.dockets:
        for item in docket.cost_items:
            totals[item.currency] = totals.get(item.currency, 0) + item.amount_minor
    membership_active = {
        row.id: row.is_active
        for row in session.scalars(
            select(CompanyMembership).where(CompanyMembership.company_id == context.company.id)
        ).all()
    }
    return IpDocketControlReport(
        generated_at=_now(),
        docket_count=listing.count,
        ready_count=sum(row.status == "ready" for row in listing.dockets),
        uncovered_deadline_count=sum(
            row.matter_id is not None and not row.deadline_coverages for row in listing.dockets
        ),
        open_incident_count=sum(
            incident.status != "verified"
            for row in listing.dockets
            for incident in row.deadline_incidents
        ),
        unprojected_calendar_count=sum(
            coverage.calendar_projection_status != "projected"
            for row in listing.dockets
            for coverage in row.deadline_coverages
        ),
        inactive_coverage_count=sum(
            not membership_active.get(coverage.responsible_membership_id, False)
            for row in listing.dockets
            for coverage in row.deadline_coverages
        ),
        total_cost_minor_by_currency=totals,
    )


__all__ = [
    "add_ip_cost_item",
    "add_ip_deadline_coverage",
    "add_ip_deadline_incident",
    "add_ip_notice_link",
    "add_ip_title_interest",
    "append_ip_docket_version",
    "create_ip_docket",
    "get_ip_docket",
    "ip_docket_control_report",
    "list_ip_dockets",
    "reassign_ip_deadline_coverage",
    "verify_ip_deadline_incident",
]
