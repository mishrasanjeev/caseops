"""Canonical post-registration recordal aggregate over shared IP owners."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpCostItem,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocumentLink,
    IpPostRegistrationRecordal,
    IpRegistryLink,
    IpRegistrySnapshot,
    IpTitleInterest,
    Matter,
)
from caseops_api.schemas.ip_lifecycle import IpDocketEventCreateRequest, IpDocketEventResponse
from caseops_api.schemas.ip_operations import IpTitleInterestRecord
from caseops_api.schemas.ip_recordals import (
    IpRecordalCreateRequest,
    IpRecordalPageResponse,
    IpRecordalResponse,
    IpRecordalTransactionRequest,
    IpRecordalTransactionResponse,
    IpRecordalWorkspaceResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.ip_lifecycle import append_ip_docket_event
from caseops_api.services.ip_operations import (
    _lock_ip_dockets_in_stable_order,
    _lock_ip_writer_context,
    project_ip_recordal_title_interests,
)
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

_TRANSITIONS: dict[str, dict[str, str]] = {
    "draft": {"review_approved": "ready", "withdrawn": "withdrawn"},
    "ready": {"filed": "filed", "withdrawn": "withdrawn"},
    "filed": {
        "acknowledgement_received": "filed",
        "defect_noted": "defective",
        "accepted": "accepted",
        "rejected": "rejected",
        "withdrawn": "withdrawn",
    },
    "defective": {
        "corrected": "ready",
        "rejected": "rejected",
        "withdrawn": "withdrawn",
    },
}
_TITLE_STATUS = {
    "ready": "pending",
    "filed": "filed",
    "defective": "pending",
    "accepted": "recorded",
    "rejected": "rejected",
    "withdrawn": "withdrawn",
}


def _registry_party_conflict(
    recordal: IpPostRegistrationRecordal,
    snapshot: IpRegistrySnapshot,
) -> bool:
    """Compare the instrument's resulting parties with a normalized registry snapshot."""

    resulting_roles = {
        "assignment": {"assignee"},
        "transmission": {"transmittee"},
        "licence": {"licensee"},
        "registered_user": {"registered_user"},
    }.get(recordal.recordal_type)
    if not resulting_roles:
        return False
    instrument_names = {
        str(party.get("name", "")).strip().casefold()
        for party in recordal.parties_json
        if str(party.get("role", "")) in resulting_roles
        and str(party.get("name", "")).strip()
    }
    raw_registry_parties = snapshot.normalized_json.get("parties", [])
    if not isinstance(raw_registry_parties, list):
        return False
    registry_names = {
        str(party.get("name", "")).strip().casefold()
        for party in raw_registry_parties
        if isinstance(party, dict) and str(party.get("name", "")).strip()
    }
    return bool(instrument_names and registry_names and instrument_names != registry_names)


def _visible_recordals_statement(session: Session, *, context: SessionContext):
    return (
        select(IpPostRegistrationRecordal)
        .join(
            IpDocketRecord,
            (IpDocketRecord.id == IpPostRegistrationRecordal.docket_id)
            & (IpDocketRecord.company_id == IpPostRegistrationRecordal.company_id),
        )
        .outerjoin(
            Matter,
            (Matter.id == IpDocketRecord.matter_id)
            & (Matter.company_id == IpDocketRecord.company_id),
        )
        .where(
            IpPostRegistrationRecordal.company_id == context.company.id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            or_(IpDocketRecord.matter_id.is_(None), Matter.is_active.is_(True)),
            visible_ip_dockets_filter(session, context=context),
        )
    )


def list_ip_recordals(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str | None,
    recordal_type: str | None,
    recordal_status: str | None,
    limit: int,
    offset: int,
) -> IpRecordalPageResponse:
    statement = _visible_recordals_statement(session, context=context)
    if docket_id:
        statement = statement.where(IpPostRegistrationRecordal.docket_id == docket_id)
    if recordal_type:
        statement = statement.where(IpPostRegistrationRecordal.recordal_type == recordal_type)
    if recordal_status:
        statement = statement.where(IpPostRegistrationRecordal.status == recordal_status)
    total = (
        session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    )
    rows = list(
        session.scalars(
            statement.order_by(
                IpPostRegistrationRecordal.updated_at.desc(),
                IpPostRegistrationRecordal.id,
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return IpRecordalPageResponse(
        items=[IpRecordalResponse.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_ip_recordal(
    session: Session,
    *,
    context: SessionContext,
    recordal_id: str,
) -> IpPostRegistrationRecordal:
    row = session.scalar(
        _visible_recordals_statement(session, context=context).where(
            IpPostRegistrationRecordal.id == recordal_id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Post-registration recordal not found.")
    return row


def _linked_document_ids(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
) -> set[str]:
    event_ids = select(IpDocketEvent.id).where(
        IpDocketEvent.company_id == company_id,
        IpDocketEvent.docket_id == docket_id,
    )
    deadline_ids = select(IpDeadline.id).where(
        IpDeadline.company_id == company_id,
        IpDeadline.docket_id == docket_id,
    )
    return set(
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


def _validate_owned_refs(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    document_refs: list[str],
    cost_item_refs: list[str],
    deadline_refs: list[str],
) -> None:
    if document_refs and set(document_refs) - _linked_document_ids(
        session, company_id=company_id, docket_id=docket_id
    ):
        raise HTTPException(
            status_code=422,
            detail="Recordal documents must be linked to the selected docket.",
        )

    def missing_ids(model, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        found = set(
            session.scalars(
                select(model.id).where(
                    model.company_id == company_id,
                    model.docket_id == docket_id,
                    model.id.in_(set(ids)),
                )
            )
        )
        return set(ids) - found

    if missing_ids(IpCostItem, cost_item_refs):
        raise HTTPException(
            status_code=422,
            detail="Recordal cost references must belong to the selected docket.",
        )
    if missing_ids(IpDeadline, deadline_refs):
        raise HTTPException(
            status_code=422,
            detail="Recordal deadline references must belong to the selected docket.",
        )


def _registry_snapshot_for_docket(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    snapshot_id: str,
    affected_registration_refs: list[str],
) -> IpRegistrySnapshot:
    normalized_refs = {
        normalize_ip_identifier(reference) for reference in affected_registration_refs
    }
    snapshot = session.scalar(
        select(IpRegistrySnapshot)
        .join(
            IpRegistryLink,
            (IpRegistryLink.id == IpRegistrySnapshot.link_id)
            & (IpRegistryLink.company_id == IpRegistrySnapshot.company_id),
        )
        .where(
            IpRegistrySnapshot.id == snapshot_id,
            IpRegistrySnapshot.company_id == company_id,
            IpRegistryLink.docket_id == docket_id,
            IpRegistryLink.match_status == "confirmed",
            IpRegistryLink.identifier_kind.in_({"application", "registration"}),
            IpRegistryLink.normalized_identifier.in_(normalized_refs),
        )
    )
    if snapshot is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Registry snapshot must belong to a confirmed application or registration "
                "link explicitly affected by this recordal."
            ),
        )
    return snapshot


def create_ip_recordal(
    session: Session,
    *,
    context: SessionContext,
    payload: IpRecordalCreateRequest,
) -> IpPostRegistrationRecordal:
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:write",
    )
    docket = _lock_ip_dockets_in_stable_order(
        session,
        context=context,
        docket_ids={payload.docket_id},
        required_capability="ip:write",
    )[payload.docket_id]
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    _validate_owned_refs(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        document_refs=payload.supporting_instrument_refs,
        cost_item_refs=payload.fee_cost_item_refs,
        deadline_refs=[],
    )
    row = IpPostRegistrationRecordal(
        company_id=context.company.id,
        docket_id=docket.id,
        recordal_type=payload.recordal_type,
        legal_basis=payload.legal_basis.strip(),
        form_code=payload.form_code.strip(),
        parties_json=[party.model_dump(mode="json") for party in payload.parties],
        executed_on=payload.executed_on,
        effective_on=payload.effective_on,
        affected_registration_refs_json=payload.affected_registration_refs,
        affected_classes_json=payload.affected_classes,
        scope_json={"scope_kind": payload.scope_kind, **payload.scope_details},
        supporting_instrument_refs_json=payload.supporting_instrument_refs,
        fee_cost_item_refs_json=payload.fee_cost_item_refs,
        deadline_rule_key=payload.deadline_rule_key,
        status="draft",
        created_by_membership_id=context.membership.id,
        updated_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    event = append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            event_kind="post_registration_recordal_transaction",
            source="manual",
            effective_at=datetime.now(UTC),
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.supporting_instrument_refs,
            document_refs=payload.supporting_instrument_refs,
            payload={
                "recordal_id": row.id,
                "transaction_kind": "created",
                "status_before": None,
                "status_after": "draft",
                "recordal_version_before": 0,
                "recordal_version_after": 1,
            },
        ),
        commit=False,
    )
    event.recordal_id = row.id
    record_from_context(
        session,
        context,
        action="ip_recordal.created",
        target_type="ip_post_registration_recordal",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"recordal_type": row.recordal_type, "event_id": event.id},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Recordal identity changed; retry.") from exc
    session.refresh(row)
    return row


def record_ip_recordal_transaction(
    session: Session,
    *,
    context: SessionContext,
    recordal_id: str,
    payload: IpRecordalTransactionRequest,
) -> IpRecordalTransactionResponse:
    visible = get_ip_recordal(session, context=context, recordal_id=recordal_id)
    required_capability = (
        "ip:approve"
        if payload.transaction_kind in {"review_approved", "accepted", "rejected"}
        else "ip:write"
    )
    context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability=required_capability,
    )
    docket = _lock_ip_dockets_in_stable_order(
        session,
        context=context,
        docket_ids={visible.docket_id},
        required_capability=required_capability,
    )[visible.docket_id]
    row = session.scalar(
        select(IpPostRegistrationRecordal)
        .where(
            IpPostRegistrationRecordal.id == visible.id,
            IpPostRegistrationRecordal.company_id == context.company.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Post-registration recordal not found.")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Recordal version changed; reload.")
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    target_status = _TRANSITIONS.get(row.status, {}).get(payload.transaction_kind)
    if target_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"Transaction {payload.transaction_kind} is not valid from {row.status}.",
        )
    _validate_owned_refs(
        session,
        company_id=context.company.id,
        docket_id=docket.id,
        document_refs=payload.document_refs,
        cost_item_refs=payload.cost_item_refs,
        deadline_refs=payload.deadline_refs,
    )
    registry_snapshot: IpRegistrySnapshot | None = None
    registry_party_conflict = False
    if payload.registry_snapshot_id:
        registry_snapshot = _registry_snapshot_for_docket(
            session,
            company_id=context.company.id,
            docket_id=docket.id,
            snapshot_id=payload.registry_snapshot_id,
            affected_registration_refs=row.affected_registration_refs_json,
        )
        if (
            payload.source_url
            and str(payload.source_url).rstrip("/")
            != registry_snapshot.source_url.rstrip("/")
        ):
            raise HTTPException(
                status_code=422,
                detail="Registry source URL must match the selected immutable snapshot.",
            )
        registry_party_conflict = _registry_party_conflict(row, registry_snapshot)
        if (
            registry_party_conflict
            and payload.details.get("client_registry_conflict_reviewed") is not True
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Client and Registry party evidence conflict; an IP approver must "
                    "record the conflict review before acceptance."
                ),
            )

    status_before = row.status
    version_before = row.version
    row.status = target_status
    row.version += 1
    row.updated_by_membership_id = context.membership.id
    row.updated_at = datetime.now(UTC)
    if payload.transaction_kind == "filed":
        row.filing_evidence_refs_json = sorted(
            set(row.filing_evidence_refs_json) | set(payload.evidence_refs)
        )
    if payload.transaction_kind == "accepted":
        row.acceptance_evidence_refs_json = sorted(
            set(row.acceptance_evidence_refs_json) | set(payload.evidence_refs)
        )
        row.registry_snapshot_id = payload.registry_snapshot_id

    projected: list[IpTitleInterest] = []
    title_status = _TITLE_STATUS.get(target_status)
    if title_status:
        projected = project_ip_recordal_title_interests(
            session,
            context=context,
            docket=docket,
            recordal=row,
            recordal_status=title_status,
            registry_recorded_on=payload.registry_recorded_on,
        )

    event = append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            event_kind="post_registration_recordal_transaction",
            source="manual",
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            resulting_deadline_refs=payload.deadline_refs,
            payload={
                **payload.details,
                "client_registry_conflict_detected": registry_party_conflict,
                "recordal_id": row.id,
                "transaction_kind": payload.transaction_kind,
                "status_before": status_before,
                "status_after": target_status,
                "recordal_version_before": version_before,
                "recordal_version_after": row.version,
                "source_url": str(payload.source_url) if payload.source_url else None,
                "registry_evidence_source": (
                    "immutable_snapshot" if registry_snapshot is not None else None
                ),
                "registry_snapshot_id": payload.registry_snapshot_id,
                "registry_recorded_on": (
                    payload.registry_recorded_on.isoformat()
                    if payload.registry_recorded_on
                    else None
                ),
                "cost_item_refs": payload.cost_item_refs,
                "projected_title_interest_ids": [interest.id for interest in projected],
            },
        ),
        commit=False,
    )
    event.recordal_id = row.id
    record_from_context(
        session,
        context,
        action="ip_recordal.transaction_recorded",
        target_type="ip_post_registration_recordal",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "transaction_kind": payload.transaction_kind,
            "status_before": status_before,
            "status_after": target_status,
            "event_id": event.id,
            "registry_projection_applied": target_status == "accepted" and bool(projected),
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Recordal version changed; reload.") from exc
    session.refresh(row)
    session.refresh(event)
    for interest in projected:
        session.refresh(interest)
    return IpRecordalTransactionResponse(
        recordal=IpRecordalResponse.model_validate(row),
        event=IpDocketEventResponse.model_validate(event),
        projected_title_interests=[
            IpTitleInterestRecord.model_validate(interest) for interest in projected
        ],
        registry_projection_applied=target_status == "accepted" and bool(projected),
    )


def ip_recordal_workspace(
    session: Session,
    *,
    context: SessionContext,
    recordal_id: str,
) -> IpRecordalWorkspaceResponse:
    row = get_ip_recordal(session, context=context, recordal_id=recordal_id)
    events = list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == context.company.id,
                IpDocketEvent.recordal_id == row.id,
            )
            .order_by(IpDocketEvent.sequence, IpDocketEvent.id)
        ).all()
    )
    interests = list(
        session.scalars(
            select(IpTitleInterest)
            .where(
                IpTitleInterest.company_id == context.company.id,
                IpTitleInterest.docket_id == row.docket_id,
                IpTitleInterest.source_recordal_id == row.id,
            )
            .order_by(IpTitleInterest.effective_from, IpTitleInterest.id)
        ).all()
    )
    today = date.today()
    registered = [
        interest
        for interest in interests
        if interest.recordal_status == "recorded"
        and interest.effective_from <= today
        and (interest.effective_until is None or interest.effective_until >= today)
    ]
    pending = [
        interest for interest in interests if interest.recordal_status in {"pending", "filed"}
    ]
    return IpRecordalWorkspaceResponse(
        recordal=IpRecordalResponse.model_validate(row),
        transactions=[IpDocketEventResponse.model_validate(event) for event in events],
        title_interests=[IpTitleInterestRecord.model_validate(interest) for interest in interests],
        current_registered_interests=[
            IpTitleInterestRecord.model_validate(interest) for interest in registered
        ],
        pending_interests=[IpTitleInterestRecord.model_validate(interest) for interest in pending],
    )
