from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import false, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    Communication,
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeIpLink,
    CompanyNoticeMatterLink,
    DriveFileCandidate,
    IpCostItem,
    IpDeadline,
    IpDeadlineCoverage,
    IpDeadlineIncident,
    IpDocketControlReview,
    IpDocketQueue,
    IpDocketRecord,
    IpEvidenceCandidate,
    IpRelatedRightObligation,
    IpTitleInterest,
    IpTrademarkParticularVersion,
    Matter,
    MatterAttachment,
    MatterDeadline,
    MatterInvoice,
    MatterInvoiceLineItem,
    MatterTimeEntry,
    Team,
    TeamMembership,
    UserCalendarConnection,
)
from caseops_api.schemas.ip_operations import (
    IpAssignedCoverageListResponse,
    IpAssignedCoverageRecord,
    IpControlExceptionRecord,
    IpControlReviewCreateRequest,
    IpControlReviewExportRequest,
    IpControlReviewRecord,
    IpControlReviewSignOffRequest,
    IpCostItemCreateRequest,
    IpCostItemRecord,
    IpCostReconciliationReport,
    IpCostReconciliationRow,
    IpCoverageAcknowledgeOutcome,
    IpCoverageBulkAcknowledgeRequest,
    IpCoverageBulkAcknowledgeResponse,
    IpCoverageBulkReassignRequest,
    IpCoverageBulkReassignResponse,
    IpCoverageReassignPreviewRequest,
    IpCoverageReassignPreviewResponse,
    IpCoverageReassignProposeRequest,
    IpCoverageReplacementDecisionRequest,
    IpCoverageTransferAwaiting,
    IpCoverageTransfersAwaitingResponse,
    IpDailyDocketEscalation,
    IpDailyDocketQueue,
    IpDailyDocketResponse,
    IpDeadlineCoverageCreateRequest,
    IpDeadlineCoverageReassignRequest,
    IpDeadlineCoverageRecord,
    IpDeadlineIncidentCreateRequest,
    IpDeadlineIncidentRecord,
    IpDeadlineIncidentVerifyRequest,
    IpDocketControlReport,
    IpDocketCreateRequest,
    IpDocketListResponse,
    IpDocketQueueListResponse,
    IpDocketQueueRecord,
    IpDocketQueueSaveRequest,
    IpDocketRecordResponse,
    IpDocketVersionCreateRequest,
    IpEvidenceCandidateRecord,
    IpEvidenceCandidateReviewRequest,
    IpEvidenceDiscoveryResponse,
    IpNoticeLinkCreateRequest,
    IpNoticeLinkRecord,
    IpRelatedRightObligationCompleteRequest,
    IpRelatedRightObligationCreateRequest,
    IpRelatedRightObligationRecord,
    IpTitleInterestCreateRequest,
    IpTitleInterestRecord,
    TrademarkParticularPayload,
    TrademarkParticularVersionRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import (
    assert_access,
    assert_ip_docket_access,
    can_access_ip_docket,
    seed_restricted_ip_creator_access,
    visible_ip_dockets_filter,
)
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
    if docket.archived_by_matter_disposal or not docket.is_active:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    assert_ip_docket_access(session, context=context, docket=docket)
    if docket.matter_id:
        matter = session.get(Matter, docket.matter_id)
        if matter is None:
            raise HTTPException(status_code=404, detail="IP docket record not found.")
        try:
            assert_operational_matter(session, matter=matter)
        except MatterNotOperationalError as exc:
            raise HTTPException(status_code=404, detail="IP docket record not found.") from exc
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
    evidence_candidates = list(
        session.scalars(
            select(IpEvidenceCandidate)
            .where(IpEvidenceCandidate.docket_id == docket.id)
            .order_by(IpEvidenceCandidate.created_at.desc())
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
    obligations = list(
        session.scalars(
            select(IpRelatedRightObligation)
            .where(IpRelatedRightObligation.docket_id == docket.id)
            .order_by(
                IpRelatedRightObligation.due_on,
                IpRelatedRightObligation.created_at,
            )
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
        is_active=docket.is_active,
        lifecycle_version=docket.lifecycle_version,
        lifecycle_effective_at=docket.lifecycle_effective_at,
        lifecycle_reason=docket.lifecycle_reason,
        lifecycle_outcome=docket.lifecycle_outcome,
        lifecycle_source=docket.lifecycle_source,
        lifecycle_evidence_ref=docket.lifecycle_evidence_ref,
        successor_docket_id=docket.successor_docket_id,
        restricted=docket.restricted,
        access_policy_version=docket.access_policy_version,
        current_version=docket.current_version,
        current_particulars=TrademarkParticularVersionRecord.model_validate(particulars),
        notice_links=[IpNoticeLinkRecord.model_validate(row) for row in notice_links],
        evidence_candidates=[
            IpEvidenceCandidateRecord.model_validate(row) for row in evidence_candidates
        ],
        deadline_coverages=[IpDeadlineCoverageRecord.model_validate(row) for row in coverages],
        deadline_incidents=[IpDeadlineIncidentRecord.model_validate(row) for row in incidents],
        title_interests=[IpTitleInterestRecord.model_validate(row) for row in interests],
        related_right_obligations=[
            IpRelatedRightObligationRecord.model_validate(row) for row in obligations
        ],
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
    seed_restricted_ip_creator_access(
        session,
        context=context,
        docket=docket,
    )
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
        ip_docket_id=docket.id,
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
        ip_docket_id=docket.id,
        metadata={"version": next_version, "status": docket.status},
    )
    session.commit()
    session.refresh(docket)
    return _serialize_docket(session, docket)


def list_ip_dockets(session: Session, *, context: SessionContext) -> IpDocketListResponse:
    rows = list(
        session.scalars(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.company_id == context.company.id,
                visible_ip_dockets_filter(session, context=context),
            )
            .order_by(IpDocketRecord.updated_at.desc())
        ).all()
    )
    visible: list[IpDocketRecordResponse] = []
    for row in rows:
        if row.archived_by_matter_disposal or not row.is_active:
            continue
        if row.matter_id:
            matter = session.get(Matter, row.matter_id)
            if matter is None:
                continue
            try:
                assert_operational_matter(session, matter=matter)
            except MatterNotOperationalError:
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
        ip_docket_id=docket.id,
        metadata={"docket_id": docket.id, "link_kind": payload.link_kind},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Notice is already linked.") from exc
    return _serialize_docket(session, docket)


def _fingerprint(*parts: object) -> str:
    canonical = "|".join(str(part or "").strip().casefold() for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _evidence_source_specs(
    session: Session,
    *,
    docket: IpDocketRecord,
) -> list[dict[str, object]]:
    if not docket.matter_id:
        return []
    matter_id = docket.matter_id
    specs: list[dict[str, object]] = []

    notices = list(
        session.scalars(
            select(CompanyNotice)
            .join(
                CompanyNoticeMatterLink,
                CompanyNoticeMatterLink.notice_id == CompanyNotice.id,
            )
            .where(
                CompanyNotice.company_id == docket.company_id,
                CompanyNoticeMatterLink.company_id == docket.company_id,
                CompanyNoticeMatterLink.matter_id == matter_id,
            )
        ).all()
    )
    accepted_notice_ids = set(
        session.scalars(
            select(CompanyNoticeIpLink.notice_id).where(
                CompanyNoticeIpLink.company_id == docket.company_id,
                CompanyNoticeIpLink.docket_id == docket.id,
            )
        ).all()
    )
    for row in notices:
        if row.id in accepted_notice_ids:
            continue
        specs.append(
            {
                "source_type": "company_notice",
                "source_id": row.id,
                "fingerprint": row.sha256_hex or _fingerprint("notice", row.id),
                "evidence_kind": "official_notice" if row.authority else "correspondence",
                "link_kind": "official_notice" if row.authority else "correspondence",
                "metadata": {
                    "label": row.subject[:255],
                    "direction": row.direction,
                    "has_document": bool(row.storage_key),
                    "reply_required": row.reply_required,
                },
            }
        )

    communications = list(
        session.scalars(
            select(Communication).where(
                Communication.company_id == docket.company_id,
                Communication.matter_id == matter_id,
            )
        ).all()
    )
    for row in communications:
        specs.append(
            {
                "source_type": "communication",
                "source_id": row.id,
                "fingerprint": _fingerprint(
                    "communication",
                    row.external_message_id or row.id,
                    row.subject,
                    row.body,
                ),
                "evidence_kind": "correspondence",
                "link_kind": "instruction" if row.direction == "inbound" else "correspondence",
                "metadata": {
                    "label": (row.subject or f"{row.channel} communication")[:255],
                    "direction": row.direction,
                    "channel": row.channel,
                    "occurred_at": row.occurred_at.isoformat(),
                },
            }
        )

    attachments = list(
        session.scalars(
            select(MatterAttachment).where(MatterAttachment.matter_id == matter_id)
        ).all()
    )
    for row in attachments:
        specs.append(
            {
                "source_type": "matter_attachment",
                "source_id": row.id,
                "fingerprint": row.sha256_hex,
                "evidence_kind": "official_notice" if row.notice_type else "document",
                "link_kind": "official_notice" if row.notice_type else "correspondence",
                "metadata": {
                    "label": row.original_filename[:255],
                    "document_type": row.document_type,
                    "processing_status": row.processing_status,
                    "has_notice_metadata": bool(row.notice_type),
                },
            }
        )

    drive_rows = list(
        session.scalars(
            select(DriveFileCandidate).where(
                DriveFileCandidate.company_id == docket.company_id,
                DriveFileCandidate.linked_matter_id == matter_id,
            )
        ).all()
    )
    attachment_hashes = {row.id: row.sha256_hex for row in attachments}
    for row in drive_rows:
        specs.append(
            {
                "source_type": "drive_file_candidate",
                "source_id": row.id,
                "fingerprint": (
                    attachment_hashes.get(row.imported_attachment_id or "")
                    or _fingerprint(
                        "drive",
                        row.provider,
                        row.provider_file_id,
                        row.provider_version,
                    )
                ),
                "evidence_kind": "drive_document",
                "link_kind": "correspondence",
                "metadata": {
                    "label": row.name[:255],
                    "provider": row.provider,
                    "status": row.status,
                    "imported": bool(row.imported_attachment_id),
                },
            }
        )
    return specs


def discover_ip_evidence_candidates(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> IpEvidenceDiscoveryResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    discovered = 0
    duplicates = 0
    fingerprints: dict[str, IpEvidenceCandidate] = {}
    for candidate in session.scalars(
        select(IpEvidenceCandidate)
        .where(
            IpEvidenceCandidate.company_id == context.company.id,
            IpEvidenceCandidate.docket_id == docket.id,
        )
        .order_by(IpEvidenceCandidate.created_at)
    ):
        fingerprints.setdefault(candidate.source_fingerprint, candidate)
    for spec in _evidence_source_specs(session, docket=docket):
        existing = session.scalar(
            select(IpEvidenceCandidate).where(
                IpEvidenceCandidate.company_id == context.company.id,
                IpEvidenceCandidate.docket_id == docket.id,
                IpEvidenceCandidate.source_type == spec["source_type"],
                IpEvidenceCandidate.source_id == spec["source_id"],
            )
        )
        if existing is not None:
            continue
        fingerprint = str(spec["fingerprint"])
        duplicate = fingerprints.get(fingerprint)
        row = IpEvidenceCandidate(
            company_id=context.company.id,
            docket_id=docket.id,
            source_type=str(spec["source_type"]),
            source_id=str(spec["source_id"]),
            source_fingerprint=fingerprint,
            evidence_kind=str(spec["evidence_kind"]),
            suggested_link_kind=str(spec["link_kind"]),
            status="duplicate" if duplicate else "needs_review",
            duplicate_of_candidate_id=duplicate.id if duplicate else None,
            metadata_json=dict(spec["metadata"]),
        )
        session.add(row)
        session.flush()
        fingerprints.setdefault(fingerprint, row)
        discovered += 1
        duplicates += int(duplicate is not None)
    record_from_context(
        session,
        context,
        action="ip_evidence.discovery_completed",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"discovered_count": discovered, "duplicate_count": duplicates},
    )
    session.commit()
    rows = list(
        session.scalars(
            select(IpEvidenceCandidate)
            .where(IpEvidenceCandidate.docket_id == docket.id)
            .order_by(IpEvidenceCandidate.created_at.desc())
        ).all()
    )
    return IpEvidenceDiscoveryResponse(
        candidates=[IpEvidenceCandidateRecord.model_validate(row) for row in rows],
        discovered_count=discovered,
        duplicate_count=duplicates,
    )


def _candidate_source_still_linked(
    session: Session,
    *,
    docket: IpDocketRecord,
    candidate: IpEvidenceCandidate,
) -> bool:
    if not docket.matter_id:
        return False
    if candidate.source_type == "company_notice":
        return (
            session.scalar(
                select(CompanyNoticeMatterLink.id).where(
                    CompanyNoticeMatterLink.company_id == docket.company_id,
                    CompanyNoticeMatterLink.notice_id == candidate.source_id,
                    CompanyNoticeMatterLink.matter_id == docket.matter_id,
                )
            )
            is not None
        )
    if candidate.source_type == "communication":
        return (
            session.scalar(
                select(Communication.id).where(
                    Communication.company_id == docket.company_id,
                    Communication.id == candidate.source_id,
                    Communication.matter_id == docket.matter_id,
                )
            )
            is not None
        )
    if candidate.source_type == "matter_attachment":
        return (
            session.scalar(
                select(MatterAttachment.id).where(
                    MatterAttachment.id == candidate.source_id,
                    MatterAttachment.matter_id == docket.matter_id,
                )
            )
            is not None
        )
    if candidate.source_type == "drive_file_candidate":
        return (
            session.scalar(
                select(DriveFileCandidate.id).where(
                    DriveFileCandidate.company_id == docket.company_id,
                    DriveFileCandidate.id == candidate.source_id,
                    DriveFileCandidate.linked_matter_id == docket.matter_id,
                )
            )
            is not None
        )
    return False


def review_ip_evidence_candidate(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    candidate_id: str,
    payload: IpEvidenceCandidateReviewRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id, for_update=True)
    candidate = session.scalar(
        select(IpEvidenceCandidate)
        .where(
            IpEvidenceCandidate.id == candidate_id,
            IpEvidenceCandidate.docket_id == docket.id,
            IpEvidenceCandidate.company_id == context.company.id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="IP evidence candidate not found.")
    if candidate.status != payload.expected_status:
        raise HTTPException(status_code=409, detail="IP evidence candidate changed; reload.")
    if not _candidate_source_still_linked(session, docket=docket, candidate=candidate):
        raise HTTPException(
            status_code=409,
            detail="The source is no longer linked to this Matter.",
        )
    now = _now()
    if payload.action == "accept":
        candidate.status = "accepted"
        candidate.accepted_effect = payload.accepted_effect
        if candidate.source_type == "company_notice":
            existing_link = session.scalar(
                select(CompanyNoticeIpLink).where(
                    CompanyNoticeIpLink.notice_id == candidate.source_id,
                    CompanyNoticeIpLink.docket_id == docket.id,
                )
            )
            if existing_link is None:
                session.add(
                    CompanyNoticeIpLink(
                        company_id=context.company.id,
                        docket_id=docket.id,
                        notice_id=candidate.source_id,
                        link_kind=payload.link_kind or candidate.suggested_link_kind,
                        accepted_effect=payload.accepted_effect,
                        created_by_membership_id=context.membership.id,
                    )
                )
    else:
        candidate.status = "rejected"
    candidate.reviewed_by_membership_id = context.membership.id
    candidate.reviewed_at = now
    record_from_context(
        session,
        context,
        action=f"ip_evidence.{candidate.status}",
        target_type="ip_evidence_candidate",
        target_id=candidate.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "source_type": candidate.source_type,
            "source_ref": candidate.source_fingerprint[:16],
            "link_kind": payload.link_kind or candidate.suggested_link_kind,
        },
    )
    session.commit()
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
        ip_docket_id=docket.id,
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


def _resolve_escalation(
    session: Session,
    context: SessionContext,
    *,
    mode: str,
    escalation_membership_id: str | None,
) -> CompanyMembership | None:
    """An immediate transfer must name where a rejection goes.

    Immediate transfers exist because the outgoing person cannot be waited on.
    If the replacement then declines, the work has nowhere to fall back to, so
    the escalation owner is mandatory rather than optional.
    """

    if mode != "immediate":
        return None
    if escalation_membership_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_escalation_required",
                "message": (
                    "An immediate transfer must name an escalation owner, so declined "
                    "work cannot be left without a responsible person."
                ),
            },
        )
    return _membership_or_404(session, context, escalation_membership_id)


def _apply_coverage_transfer(
    coverage: IpDeadlineCoverage,
    *,
    replacement: CompanyMembership,
    mode: str,
    escalation: CompanyMembership | None,
    reason: str,
    now: datetime,
) -> bool:
    """Move or propose responsibility for one coverage row (CAL-OPS-08).

    Returns ``True`` when responsibility actually moved. This is the single
    place either transfer path may touch responsibility, and it deliberately
    never writes ``accepted_at``: an acceptance is a record that a named person
    took on a filing date, and only ``decide_ip_coverage_replacement`` — which
    runs on that person's own action — is entitled to write one.
    """

    coverage.pending_replacement_membership_id = replacement.id
    coverage.replacement_decision = "pending"
    coverage.replacement_decided_at = None
    coverage.replacement_decision_reason = reason
    coverage.reassignment_version += 1
    coverage.updated_at = now

    if mode == "immediate":
        coverage.responsible_membership_id = replacement.id
        if coverage.backup_membership_id == replacement.id:
            coverage.backup_membership_id = None
        coverage.emergency_escalation_membership_id = escalation.id if escalation else None
        coverage.coverage_status = "reassigned"
        # They hold the work now, so it belongs on their calendar now.
        coverage.calendar_projection_status = "pending"
        return True

    # Proposed: the current owner keeps the work until the replacement accepts.
    coverage.coverage_status = "transfer_pending"
    return False


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
    replacement = _membership_or_404(session, context, payload.responsible_membership_id)
    backup = (
        _membership_or_404(session, context, payload.backup_membership_id)
        if payload.backup_membership_id
        else None
    )
    # Guard before any mutation: an incoming owner or backup who cannot open
    # the record must not be given responsibility for its deadline.
    for incoming in (replacement, backup):
        if incoming is not None:
            _assert_replacement_can_cover(
                session, context=context, replacement=incoming, dockets=[docket]
            )
    escalation = _resolve_escalation(
        session,
        context,
        mode=payload.transfer_mode,
        escalation_membership_id=payload.escalation_membership_id,
    )
    old_responsible = coverage.responsible_membership_id
    # Naming a backup is an administrative assignment and applies at once; the
    # backup is not accountable for the date until responsibility moves.
    coverage.backup_membership_id = payload.backup_membership_id
    _apply_coverage_transfer(
        coverage,
        replacement=replacement,
        mode=payload.transfer_mode,
        escalation=escalation,
        reason=payload.reason,
        now=_now(),
    )
    record_from_context(
        session,
        context,
        action=f"ip_deadline_coverage.transfer_{payload.transfer_mode}",
        target_type="ip_deadline_coverage",
        target_id=coverage.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "old_responsible_membership_id": old_responsible,
            "new_responsible_membership_id": coverage.responsible_membership_id,
            "proposed_responsible_membership_id": payload.responsible_membership_id,
            "transfer_mode": payload.transfer_mode,
            "reason": payload.reason,
        },
    )
    session.commit()
    return _serialize_docket(session, docket)


def _assert_replacement_can_cover(
    session: Session,
    *,
    context: SessionContext,
    replacement: CompanyMembership,
    dockets: list[IpDocketRecord],
) -> None:
    """UJ-57-EXC-01/02: never hand work to someone who cannot open the record.

    Coverage reassignment previously checked only that the replacement existed,
    so a restricted docket or an ethical wall could be bypassed by making the
    walled-off member responsible for its deadline. The canonical
    ``can_access_ip_docket`` policy is evaluated as the *replacement*, and the
    transfer fails closed for the whole batch rather than partially applying.

    Blocked docket ids are returned so an operator can act, but no title or
    other record content is disclosed.
    """

    recipient = SessionContext(
        company=context.company,
        user=replacement.user,
        membership=replacement,
    )
    blocked = [
        docket.id
        for docket in dockets
        if not can_access_ip_docket(session, context=recipient, docket=docket)
    ]
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_replacement_lacks_access",
                "message": (
                    "The replacement cannot access every affected IP record, so the "
                    "transfer was refused in full."
                ),
                "blocked_docket_ids": sorted(blocked),
            },
        )


def bulk_reassign_ip_deadline_coverages(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCoverageBulkReassignRequest,
    commit: bool = True,
) -> IpCoverageBulkReassignResponse:
    if payload.from_membership_id == payload.to_membership_id:
        raise HTTPException(status_code=422, detail="Coverage replacement must be different.")
    source = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == payload.from_membership_id,
            CompanyMembership.company_id == context.company.id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source membership not found.")
    replacement = _membership_or_404(session, context, payload.to_membership_id)
    rows = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                or_(
                    IpDeadlineCoverage.responsible_membership_id == source.id,
                    IpDeadlineCoverage.backup_membership_id == source.id,
                ),
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update()
        ).all()
    )
    affected_dockets = list(
        session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_({row.docket_id for row in rows} or {""}),
                IpDocketRecord.company_id == context.company.id,
            )
        ).all()
    )
    _assert_replacement_can_cover(
        session, context=context, replacement=replacement, dockets=affected_dockets
    )
    escalation = _resolve_escalation(
        session,
        context,
        mode=payload.transfer_mode,
        escalation_membership_id=payload.escalation_membership_id,
    )

    responsible_count = 0
    backup_count = 0
    pending_count = 0
    now = _now()
    for row in rows:
        expected_version = payload.expected_versions.get(row.id)
        if expected_version is not None and row.reassignment_version != expected_version:
            raise HTTPException(
                status_code=409,
                detail=f"Coverage {row.id} changed; reload before bulk reassignment.",
            )
        changed_roles: list[str] = []
        if row.backup_membership_id == source.id:
            # Backup naming is administrative and applies at once.
            row.backup_membership_id = replacement.id
            backup_count += 1
            changed_roles.append("backup")
        if row.responsible_membership_id == source.id:
            _apply_coverage_transfer(
                row,
                replacement=replacement,
                mode=payload.transfer_mode,
                escalation=escalation,
                reason=payload.reason,
                now=now,
            )
            responsible_count += 1
            pending_count += 1
            changed_roles.append("responsible")
        else:
            row.updated_at = now
            row.reassignment_version += 1
        if row.backup_membership_id == row.responsible_membership_id:
            row.backup_membership_id = None
        # Only project onto the replacement's calendar once the work is actually
        # theirs. A proposal they have not accepted must not appear as their
        # commitment.
        connection = (
            session.scalar(
                select(UserCalendarConnection).where(
                    UserCalendarConnection.company_id == context.company.id,
                    UserCalendarConnection.membership_id == replacement.id,
                    UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
                )
            )
            if row.responsible_membership_id == replacement.id
            else None
        )
        if connection is not None:
            existing_sync = session.scalar(
                select(CalendarEventSync).where(
                    CalendarEventSync.calendar_connection_id == connection.id,
                    CalendarEventSync.source_type == "matter_deadline",
                    CalendarEventSync.source_id == row.matter_deadline_id,
                )
            )
            if existing_sync is None:
                session.add(
                    CalendarEventSync(
                        company_id=context.company.id,
                        calendar_connection_id=connection.id,
                        source_type="matter_deadline",
                        source_id=row.matter_deadline_id,
                        sync_status=CalendarEventSyncStatus.PENDING,
                    )
                )
        docket = session.get(IpDocketRecord, row.docket_id)
        record_from_context(
            session,
            context,
            action=f"ip_deadline_coverage.bulk_transfer_{payload.transfer_mode}",
            target_type="ip_deadline_coverage",
            target_id=row.id,
            matter_id=docket.matter_id if docket else None,
            ip_docket_id=docket.id if docket else None,
            metadata={
                "from_membership_id": source.id,
                "to_membership_id": replacement.id,
                "roles": changed_roles,
                "reason": payload.reason,
                "reassignment_version": row.reassignment_version,
                "transfer_mode": payload.transfer_mode,
                "responsible_membership_id": row.responsible_membership_id,
            },
        )
    session.flush()
    if commit:
        session.commit()
    return IpCoverageBulkReassignResponse(
        reassigned_count=len(rows),
        responsible_count=responsible_count,
        backup_count=backup_count,
        coverage_ids=[row.id for row in rows],
        transfer_mode=payload.transfer_mode,
        pending_count=pending_count,
    )


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
        ip_docket_id=docket.id,
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
        ip_docket_id=docket.id,
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
        if payload.related_docket_id == docket.id:
            raise HTTPException(status_code=422, detail="A docket cannot be related to itself.")
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
            flags.append(f"party_overlap:{row.id}")
            if payload.interest_type in {"ownership", "assignment"} and row.interest_type in {
                "ownership",
                "assignment",
            }:
                flags.append(f"competing_title:{row.id}")
        if (
            overlaps
            and payload.interest_type == "licence"
            and row.interest_type
            in {
                "encumbrance",
                "security",
            }
        ):
            flags.append(f"licence_encumbrance_conflict:{row.id}")
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
        ip_docket_id=docket.id,
        metadata={
            "interest_type": payload.interest_type,
            "conflict_count": len(flags),
        },
    )
    session.commit()
    return _serialize_docket(session, docket)


def add_ip_related_right_obligation(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpRelatedRightObligationCreateRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id)
    _membership_or_404(session, context, payload.owner_membership_id)
    if payload.title_interest_id:
        interest = session.scalar(
            select(IpTitleInterest).where(
                IpTitleInterest.id == payload.title_interest_id,
                IpTitleInterest.docket_id == docket.id,
                IpTitleInterest.company_id == context.company.id,
            )
        )
        if interest is None:
            raise HTTPException(status_code=404, detail="Title interest not found.")
    if payload.matter_deadline_id:
        _deadline_for_docket(
            session,
            docket=docket,
            deadline_id=payload.matter_deadline_id,
        )
    row = IpRelatedRightObligation(
        company_id=context.company.id,
        docket_id=docket.id,
        title_interest_id=payload.title_interest_id,
        obligation_type=payload.obligation_type,
        title=payload.title.strip(),
        due_on=payload.due_on,
        owner_membership_id=payload.owner_membership_id,
        matter_deadline_id=payload.matter_deadline_id,
        status="open",
        evidence_reference=payload.evidence_reference.strip(),
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_related_right_obligation.created",
        target_type="ip_related_right_obligation",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "obligation_type": row.obligation_type,
            "due_on": row.due_on.isoformat() if row.due_on else None,
            "has_operational_deadline": bool(row.matter_deadline_id),
        },
    )
    session.commit()
    return _serialize_docket(session, docket)


def complete_ip_related_right_obligation(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    obligation_id: str,
    payload: IpRelatedRightObligationCompleteRequest,
) -> IpDocketRecordResponse:
    docket = _docket_or_404(session, context=context, docket_id=docket_id, for_update=True)
    row = session.scalar(
        select(IpRelatedRightObligation)
        .where(
            IpRelatedRightObligation.id == obligation_id,
            IpRelatedRightObligation.docket_id == docket.id,
            IpRelatedRightObligation.company_id == context.company.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Related-right obligation not found.")
    if row.status != payload.expected_status:
        raise HTTPException(status_code=409, detail="Obligation changed; reload.")
    row.status = "completed"
    row.completion_evidence_reference = payload.completion_evidence_reference.strip()
    row.completed_at = _now()
    row.updated_at = row.completed_at
    record_from_context(
        session,
        context,
        action="ip_related_right_obligation.completed",
        target_type="ip_related_right_obligation",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"obligation_type": row.obligation_type},
    )
    session.commit()
    return _serialize_docket(session, docket)


def _canonical_billing_value(
    session: Session,
    *,
    cost: IpCostItem,
) -> tuple[int | None, str | None, str]:
    if not cost.billing_link_type or not cost.billing_link_id:
        return None, None, "unlinked"
    amount: int | None = None
    currency: str | None = None
    if cost.billing_link_type == "invoice":
        row = session.scalar(
            select(MatterInvoice).where(
                MatterInvoice.id == cost.billing_link_id,
                MatterInvoice.company_id == cost.company_id,
                MatterInvoice.matter_id == cost.matter_id,
            )
        )
        if row is not None:
            amount, currency = row.total_amount_minor, row.currency
    elif cost.billing_link_type == "invoice_line_item":
        result = session.execute(
            select(MatterInvoiceLineItem, MatterInvoice)
            .join(MatterInvoice, MatterInvoice.id == MatterInvoiceLineItem.invoice_id)
            .where(
                MatterInvoiceLineItem.id == cost.billing_link_id,
                MatterInvoice.company_id == cost.company_id,
                MatterInvoice.matter_id == cost.matter_id,
            )
        ).first()
        if result is not None:
            line, invoice = result
            amount, currency = line.line_total_amount_minor, invoice.currency
    elif cost.billing_link_type == "time_entry":
        row = session.scalar(
            select(MatterTimeEntry).where(
                MatterTimeEntry.id == cost.billing_link_id,
                MatterTimeEntry.matter_id == cost.matter_id,
            )
        )
        if row is not None:
            amount, currency = row.total_amount_minor, row.rate_currency
    if amount is None:
        return None, None, "missing"
    if currency != cost.currency or amount != cost.amount_minor:
        return amount, currency, "mismatch"
    return amount, currency, "matched"


def _apply_cost_reconciliation(
    session: Session,
    *,
    context: SessionContext,
    cost: IpCostItem,
) -> IpCostReconciliationRow:
    canonical_amount, _canonical_currency, status_value = _canonical_billing_value(
        session,
        cost=cost,
    )
    cost.reconciliation_status = status_value
    cost.canonical_amount_minor = canonical_amount
    cost.reconciliation_difference_minor = (
        canonical_amount - cost.amount_minor if canonical_amount is not None else None
    )
    cost.reconciled_at = _now()
    cost.reconciled_by_membership_id = context.membership.id
    return IpCostReconciliationRow(
        cost_item_id=cost.id,
        billing_link_type=cost.billing_link_type,
        billing_link_id=cost.billing_link_id,
        evidence_amount_minor=cost.amount_minor,
        canonical_amount_minor=canonical_amount,
        difference_minor=cost.reconciliation_difference_minor,
        currency=cost.currency,
        status=status_value,
    )


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
    _apply_cost_reconciliation(session, context=context, cost=cost)
    record_from_context(
        session,
        context,
        action="ip_cost_item.created",
        target_type="ip_cost_item",
        target_id=cost.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"category": payload.category, "currency": payload.currency.upper()},
    )
    session.commit()
    return _serialize_docket(session, docket)


def reconcile_ip_cost_items(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> IpCostReconciliationReport:
    docket = _docket_or_404(session, context=context, docket_id=docket_id, for_update=True)
    costs = list(
        session.scalars(
            select(IpCostItem)
            .where(
                IpCostItem.company_id == context.company.id,
                IpCostItem.docket_id == docket.id,
            )
            .order_by(IpCostItem.created_at, IpCostItem.id)
            .with_for_update()
        ).all()
    )
    rows = [_apply_cost_reconciliation(session, context=context, cost=cost) for cost in costs]
    checksum_payload = [row.model_dump(mode="json") for row in rows]
    checksum = hashlib.sha256(
        json.dumps(checksum_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    record_from_context(
        session,
        context,
        action="ip_cost.reconciled",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "accounting_owner": "matter_billing",
            "row_count": len(rows),
            "checksum_sha256": checksum,
            "status_counts": {
                status_value: sum(row.status == status_value for row in rows)
                for status_value in ("matched", "mismatch", "missing", "unlinked")
            },
        },
    )
    session.commit()
    return IpCostReconciliationReport(
        generated_at=_now(),
        docket_id=docket.id,
        rows=rows,
        matched_count=sum(row.status == "matched" for row in rows),
        mismatch_count=sum(row.status == "mismatch" for row in rows),
        missing_count=sum(row.status == "missing" for row in rows),
        unlinked_count=sum(row.status == "unlinked" for row in rows),
        checksum_sha256=checksum,
    )


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
    "list_ip_assigned_coverage",
    "bulk_acknowledge_ip_coverage",
    "save_ip_docket_queue",
    "list_ip_docket_queues",
    "delete_ip_docket_queue",
    "list_ip_coverage_transfers_awaiting",
    "add_ip_cost_item",
    "add_ip_deadline_coverage",
    "add_ip_deadline_incident",
    "add_ip_notice_link",
    "add_ip_related_right_obligation",
    "add_ip_title_interest",
    "append_ip_docket_version",
    "bulk_reassign_ip_deadline_coverages",
    "complete_ip_related_right_obligation",
    "create_ip_docket",
    "discover_ip_evidence_candidates",
    "get_ip_docket",
    "ip_docket_control_report",
    "list_ip_dockets",
    "reconcile_ip_cost_items",
    "reassign_ip_deadline_coverage",
    "review_ip_evidence_candidate",
    "verify_ip_deadline_incident",
]


def _control_exceptions(
    session: Session,
    *,
    context: SessionContext,
    listing: IpDocketListResponse,
) -> list[IpControlExceptionRecord]:
    """CAL-OPS-13 exception queue, derived from access-filtered records only.

    A restricted record the caller cannot open never reaches ``listing``, so it
    contributes neither an exception nor a count.
    """

    membership_active = {
        row.id: row.is_active
        for row in session.scalars(
            select(CompanyMembership).where(CompanyMembership.company_id == context.company.id)
        ).all()
    }
    found: list[IpControlExceptionRecord] = []
    for docket in listing.dockets:
        if docket.matter_id is not None and not docket.deadline_coverages:
            found.append(
                IpControlExceptionRecord(docket_id=docket.id, kind="uncovered")
            )
        for coverage in docket.deadline_coverages:
            if not membership_active.get(coverage.responsible_membership_id, False):
                found.append(
                    IpControlExceptionRecord(docket_id=docket.id, kind="inactive_owner")
                )
            if coverage.calendar_projection_status != "projected":
                found.append(
                    IpControlExceptionRecord(
                        docket_id=docket.id, kind="unprojected_calendar"
                    )
                )
        for incident in docket.deadline_incidents:
            if incident.status != "verified":
                found.append(
                    IpControlExceptionRecord(docket_id=docket.id, kind="open_incident")
                )
    return found


def _review_record(
    row: IpDocketControlReview,
    report: IpDocketControlReport,
) -> IpControlReviewRecord:
    return IpControlReviewRecord(
        id=row.id,
        generated_at=row.generated_at,
        filters=dict(row.filters_json or {}),
        freshness=dict(row.freshness_json or {}),
        completeness_status=row.completeness_status,
        incompleteness_reasons=list(row.incompleteness_reasons_json or []),
        mandatory_exceptions=[
            IpControlExceptionRecord(**item) for item in (row.mandatory_exception_ids_json or [])
        ],
        manifest_sha256=row.manifest_sha256,
        export_status=row.export_status,
        export_error_redacted=row.export_error_redacted,
        signer_label_snapshot=row.signer_label_snapshot,
        signed_off_at=row.signed_off_at,
        version=row.version,
        report=report,
    )


def create_ip_control_review(
    session: Session,
    *,
    context: SessionContext,
    payload: IpControlReviewCreateRequest,
) -> IpControlReviewRecord:
    """Produce a daily docket control review that can later be signed off.

    Freshness and completeness are recorded up front: a stale source or a failed
    query makes the review ``incomplete``, and an incomplete review can never be
    signed off (UJ-59-EXC-01). Mandatory exceptions are captured from the
    access-filtered listing and stored on the review, so no later filter or bulk
    dismissal can hide them (CAL-OPS-13).
    """

    report = ip_docket_control_report(session, context=context)
    listing = list_ip_dockets(session, context=context)
    exceptions = _control_exceptions(session, context=context, listing=listing)

    reasons: list[str] = []
    for source in sorted({s.strip() for s in payload.stale_sources if s.strip()}):
        reasons.append(f"stale_source:{source}")
    for query in sorted({q.strip() for q in payload.failed_queries if q.strip()}):
        reasons.append(f"failed_query:{query}")

    now = _now()
    manifest = hashlib.sha256(
        json.dumps(
            {
                "generated_at": now.isoformat(),
                "filters": payload.filters,
                "docket_count": report.docket_count,
                "exceptions": [item.model_dump(mode="json") for item in exceptions],
                "incompleteness": reasons,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    row = IpDocketControlReview(
        company_id=context.company.id,
        generated_at=now,
        filters_json=payload.filters,
        freshness_json={
            "stale_sources": sorted({s.strip() for s in payload.stale_sources if s.strip()}),
            "failed_queries": sorted({q.strip() for q in payload.failed_queries if q.strip()}),
            "observed_at": now.isoformat(),
        },
        completeness_status="incomplete" if reasons else "complete",
        incompleteness_reasons_json=reasons,
        mandatory_exception_ids_json=[item.model_dump(mode="json") for item in exceptions],
        manifest_sha256=manifest,
        export_status="not_requested",
        version=1,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip.control_review.generated",
        target_type="ip_docket_control_review",
        target_id=row.id,
        metadata={
            "completeness_status": row.completeness_status,
            "incompleteness_reasons": reasons,
            "mandatory_exception_count": len(exceptions),
            "manifest_sha256": manifest,
        },
    )
    session.commit()
    session.refresh(row)
    return _review_record(row, report)


def _review_or_404(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
    for_update: bool = False,
) -> IpDocketControlReview:
    statement = select(IpDocketControlReview).where(
        IpDocketControlReview.id == review_id,
        IpDocketControlReview.company_id == context.company.id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="Control review not found.")
    return row


def get_ip_control_review(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
) -> IpControlReviewRecord:
    row = _review_or_404(session, context=context, review_id=review_id)
    return _review_record(row, ip_docket_control_report(session, context=context))


def record_ip_control_review_export(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
    payload: IpControlReviewExportRequest,
) -> IpControlReviewRecord:
    """UJ-59-EXC-03 — a failed export must not leave the review signable."""

    row = _review_or_404(session, context=context, review_id=review_id, for_update=True)
    if row.signed_off_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A signed-off control review cannot be re-exported.",
        )
    row.export_status = payload.outcome
    row.export_error_redacted = (
        payload.error_redacted if payload.outcome == "failed" else None
    )
    row.version += 1
    record_from_context(
        session,
        context,
        action="ip.control_review.export_recorded",
        target_type="ip_docket_control_review",
        target_id=row.id,
        metadata={"outcome": payload.outcome},
    )
    session.commit()
    session.refresh(row)
    return _review_record(row, ip_docket_control_report(session, context=context))


def sign_off_ip_control_review(
    session: Session,
    *,
    context: SessionContext,
    review_id: str,
    payload: IpControlReviewSignOffRequest,
) -> IpControlReviewRecord:
    """CAL-OPS-09 sign-off, refused unless the review is genuinely clean."""

    row = _review_or_404(session, context=context, review_id=review_id, for_update=True)
    if row.version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Control review changed; reload before signing off.",
        )
    if row.signed_off_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Control review is already signed off.",
        )
    if row.completeness_status != "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_control_review_incomplete",
                "message": "An incomplete control review cannot be signed off.",
                "incompleteness_reasons": list(row.incompleteness_reasons_json or []),
            },
        )
    if row.export_status == "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_control_review_export_failed",
                "message": "Export generation failed; the review cannot be marked complete.",
            },
        )

    row.signed_off_by_membership_id = context.membership.id
    row.signer_label_snapshot = context.user.full_name or context.user.email
    row.signed_off_at = _now()
    row.version += 1
    record_from_context(
        session,
        context,
        action="ip.control_review.signed_off",
        target_type="ip_docket_control_review",
        target_id=row.id,
        metadata={
            "attestation": payload.attestation,
            "manifest_sha256": row.manifest_sha256,
            "mandatory_exception_count": len(row.mandatory_exception_ids_json or []),
        },
    )
    session.commit()
    session.refresh(row)
    return _review_record(row, ip_docket_control_report(session, context=context))


def ip_daily_docket(
    session: Session,
    *,
    context: SessionContext,
    filters: dict | None = None,
    stale_sources: list[str] | None = None,
) -> IpDailyDocketResponse:
    """The daily docket a docketing manager triages (UJ-50).

    Read-derived from the access-filtered docket listing, so restricted work
    contributes neither a queue entry nor a count (UJ-50-EXC-01).

    Three rules carry the journey's acceptance — that a manager can identify
    every critical item without side spreadsheets or hidden logs:

    * an inactive owner escalates to the named backup, or is reported ``unowned``
      when there is none (UJ-50-EXC-02);
    * an unacknowledged critical item escalates rather than sitting quietly
      (UJ-50-EXC-04);
    * when a source is stale the affected counts are ``None``, never ``0``, so
      unknown work is never rendered as no work (UJ-50-EXC-03).
    """

    stale = sorted({s.strip() for s in (stale_sources or []) if s.strip()})
    counts_complete = not stale
    listing = list_ip_dockets(session, context=context)

    memberships = {
        row.id: row
        for row in session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(CompanyMembership.company_id == context.company.id)
        ).all()
    }

    # Criticality lives on the legal deadline, joined through the operational
    # deadline the coverage projects to.
    critical_matter_deadline_ids = {
        row
        for row in session.scalars(
            select(IpDeadline.matter_deadline_id).where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.is_critical.is_(True),
                IpDeadline.matter_deadline_id.is_not(None),
            )
        ).all()
        if row
    }

    assigned: dict[str, int] = {}
    critical: dict[str, int] = {}
    unacknowledged: dict[str, int] = {}
    escalations: list[IpDailyDocketEscalation] = []

    for docket in listing.dockets:
        for coverage in docket.deadline_coverages:
            owner_id = coverage.responsible_membership_id
            is_critical = coverage.matter_deadline_id in critical_matter_deadline_ids
            assigned[owner_id] = assigned.get(owner_id, 0) + 1
            if is_critical:
                critical[owner_id] = critical.get(owner_id, 0) + 1

            owner = memberships.get(owner_id)
            owner_active = bool(owner and owner.is_active and owner.user.is_active)
            acknowledged = coverage.coverage_status == "accepted" and coverage.accepted_at

            if not acknowledged:
                unacknowledged[owner_id] = unacknowledged.get(owner_id, 0) + 1

            if not owner_active:
                backup = memberships.get(coverage.backup_membership_id or "")
                backup_ok = bool(backup and backup.is_active and backup.user.is_active)
                escalations.append(
                    IpDailyDocketEscalation(
                        coverage_id=coverage.id,
                        docket_id=docket.id,
                        reason="owner_inactive" if backup_ok else "unowned",
                        critical=is_critical,
                        escalate_to_membership_id=backup.id if backup_ok else None,
                    )
                )
            elif is_critical and not acknowledged:
                backup = memberships.get(coverage.backup_membership_id or "")
                backup_ok = bool(backup and backup.is_active and backup.user.is_active)
                escalations.append(
                    IpDailyDocketEscalation(
                        coverage_id=coverage.id,
                        docket_id=docket.id,
                        reason="unacknowledged_critical",
                        critical=True,
                        escalate_to_membership_id=backup.id if backup_ok else None,
                    )
                )

    queues: list[IpDailyDocketQueue] = []
    for membership_id in sorted(assigned):
        member = memberships.get(membership_id)
        active = bool(member and member.is_active and member.user.is_active)
        queues.append(
            IpDailyDocketQueue(
                membership_id=membership_id,
                label=(
                    (member.user.full_name or member.user.email) if member else membership_id
                ),
                active=active,
                capacity_state="available" if active else "unavailable",
                # Unknown work must not render as no work.
                assigned_count=assigned[membership_id] if counts_complete else None,
                critical_count=critical.get(membership_id, 0) if counts_complete else None,
                unacknowledged_count=(
                    unacknowledged.get(membership_id, 0) if counts_complete else None
                ),
            )
        )

    escalations.sort(key=lambda item: (not item.critical, item.reason, item.coverage_id))
    return IpDailyDocketResponse(
        generated_at=_now(),
        filters=dict(filters or {}),
        stale_sources=stale,
        counts_are_complete=counts_complete,
        queues=queues,
        escalations=escalations,
    )

def _aware_utc(value):
    """Normalize a possibly-naive timestamp for comparison."""

    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _coverage_preview_token(rows: list[IpDeadlineCoverage]) -> str:
    """An atomic snapshot of the coverage set being transferred (CAL-OPS-08).

    Any concurrent change to any affected row alters the token, so a transfer
    built on a stale preview is refused rather than partially applied.
    """

    parts = sorted(
        f"{row.id}:{row.reassignment_version}:{row.responsible_membership_id}"
        f":{row.backup_membership_id or ''}:{row.replacement_decision}"
        for row in rows
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _coverages_for_member(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    for_update: bool = False,
) -> list[IpDeadlineCoverage]:
    statement = (
        select(IpDeadlineCoverage)
        .where(
            IpDeadlineCoverage.company_id == context.company.id,
            or_(
                IpDeadlineCoverage.responsible_membership_id == membership_id,
                IpDeadlineCoverage.backup_membership_id == membership_id,
            ),
        )
        .order_by(IpDeadlineCoverage.id)
    )
    if for_update:
        statement = statement.with_for_update()
    return list(session.scalars(statement).all())


def _queue_scope(row: IpDocketQueue) -> str:
    return "team" if row.team_id else "personal"


def _serialize_queue(row: IpDocketQueue) -> IpDocketQueueRecord:
    return IpDocketQueueRecord(
        id=row.id,
        name=row.name,
        description=row.description,
        filters=dict(row.filters_json or {}),
        team_id=row.team_id,
        owner_membership_id=row.owner_membership_id,
        scope=_queue_scope(row),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _caller_team_ids(session: Session, *, context: SessionContext) -> set[str]:
    return {
        team_id
        for team_id in session.scalars(
            select(TeamMembership.team_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(
                Team.company_id == context.company.id,
                TeamMembership.membership_id == context.membership.id,
            )
        ).all()
    }


def save_ip_docket_queue(
    session: Session,
    *,
    context: SessionContext,
    payload: IpDocketQueueSaveRequest,
) -> IpDocketQueueRecord:
    """Save a named daily-docket queue (CAL-OPS-09).

    A team queue may only be saved by a member of that team: sharing a view
    into a team's workload is a disclosure, not a preference.
    """

    if payload.team_id is not None:
        team = session.scalar(
            select(Team).where(
                Team.id == payload.team_id,
                Team.company_id == context.company.id,
            )
        )
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found.")
        if payload.team_id not in _caller_team_ids(session, context=context):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a member of the team can save a queue for it.",
            )

    existing = session.scalar(
        select(IpDocketQueue).where(
            IpDocketQueue.company_id == context.company.id,
            IpDocketQueue.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_docket_queue_name_taken",
                "message": "A queue with this name already exists in this workspace.",
            },
        )

    row = IpDocketQueue(
        company_id=context.company.id,
        name=payload.name,
        description=payload.description,
        filters_json=dict(payload.filters),
        team_id=payload.team_id,
        # A team queue is still attributed, so it can be governed and cleaned up.
        owner_membership_id=None if payload.team_id else context.membership.id,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    record_from_context(
        session,
        context,
        action="ip_docket_queue.saved",
        target_type="ip_docket_queue",
        target_id=row.id,
        metadata={"name": row.name, "scope": _queue_scope(row), "team_id": row.team_id},
    )
    session.commit()
    session.refresh(row)
    return _serialize_queue(row)


def list_ip_docket_queues(
    session: Session,
    *,
    context: SessionContext,
) -> IpDocketQueueListResponse:
    """Queues the caller may use: their own, plus their teams'."""

    team_ids = _caller_team_ids(session, context=context)
    rows = list(
        session.scalars(
            select(IpDocketQueue)
            .where(
                IpDocketQueue.company_id == context.company.id,
                or_(
                    IpDocketQueue.owner_membership_id == context.membership.id,
                    IpDocketQueue.team_id.in_(team_ids) if team_ids else false(),
                ),
            )
            .order_by(IpDocketQueue.name)
        ).all()
    )
    return IpDocketQueueListResponse(queues=[_serialize_queue(row) for row in rows])


def delete_ip_docket_queue(
    session: Session,
    *,
    context: SessionContext,
    queue_id: str,
) -> None:
    row = session.scalar(
        select(IpDocketQueue).where(
            IpDocketQueue.id == queue_id,
            IpDocketQueue.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Queue not found.")
    if row.team_id:
        if row.team_id not in _caller_team_ids(session, context=context):
            raise HTTPException(status_code=404, detail="Queue not found.")
    elif row.owner_membership_id != context.membership.id:
        # Someone else's personal queue is not theirs to know about either.
        raise HTTPException(status_code=404, detail="Queue not found.")

    record_from_context(
        session,
        context,
        action="ip_docket_queue.deleted",
        target_type="ip_docket_queue",
        target_id=row.id,
        metadata={"name": row.name, "scope": _queue_scope(row)},
    )
    session.delete(row)
    session.commit()


def bulk_acknowledge_ip_coverage(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCoverageBulkAcknowledgeRequest,
) -> IpCoverageBulkAcknowledgeResponse:
    """Acknowledge many assigned deadlines at once (CAL-OPS-09).

    Acknowledgement is what stops a critical item escalating, so it must be a
    real act by the person who holds the work: this only ever acknowledges rows
    where the caller is the responsible member, which is why it is entitled to
    write ``accepted_at``.

    Validation is **per record and partial by design**. Acknowledging is not a
    security boundary — a caller can only acknowledge their own work — so
    failing all fifty because one row moved would be worse than reporting that
    one. Every requested id is reported back, so a dropped row can never be
    mistaken for an acknowledged one. This is the opposite of the transfer
    path, where handing a restricted record to the wrong person *is* a boundary
    and the whole batch fails closed.
    """

    requested = list(dict.fromkeys(payload.coverage_ids))
    rows = {
        row.id: row
        for row in session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.id.in_(requested),
                IpDeadlineCoverage.company_id == context.company.id,
            )
            .with_for_update()
        ).all()
    }
    dockets = {
        docket.id: docket
        for docket in session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_({row.docket_id for row in rows.values()} or {""}),
                IpDocketRecord.company_id == context.company.id,
            )
        ).all()
    }

    now = _now()
    outcomes: list[IpCoverageAcknowledgeOutcome] = []
    acknowledged_ids: list[str] = []

    for coverage_id in requested:
        row = rows.get(coverage_id)
        docket = dockets.get(row.docket_id) if row else None
        if (
            row is None
            or docket is None
            or not can_access_ip_docket(session, context=context, docket=docket)
        ):
            # A record the caller cannot open is reported as absent, never as a
            # record they may not touch — that would confirm it exists.
            outcomes.append(
                IpCoverageAcknowledgeOutcome(coverage_id=coverage_id, acknowledged=False,
                                             reason="not_found")
            )
            continue
        if row.responsible_membership_id != context.membership.id:
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="not_responsible",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue
        expected = payload.expected_versions.get(coverage_id)
        if expected is not None and row.reassignment_version != expected:
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="version_conflict",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue
        if row.replacement_decision == "pending":
            # An outstanding transfer is a decision, not an acknowledgement;
            # acknowledging around it would bury the choice.
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="transfer_pending",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue
        if row.coverage_status == "accepted" and row.accepted_at is not None:
            outcomes.append(
                IpCoverageAcknowledgeOutcome(
                    coverage_id=coverage_id,
                    acknowledged=False,
                    reason="already_acknowledged",
                    reassignment_version=row.reassignment_version,
                )
            )
            continue

        row.coverage_status = "accepted"
        row.accepted_at = now
        row.updated_at = now
        acknowledged_ids.append(coverage_id)
        outcomes.append(
            IpCoverageAcknowledgeOutcome(
                coverage_id=coverage_id,
                acknowledged=True,
                reason="acknowledged",
                reassignment_version=row.reassignment_version,
            )
        )

    if acknowledged_ids:
        record_from_context(
            session,
            context,
            action="ip_deadline_coverage.bulk_acknowledged",
            target_type="company_membership",
            target_id=context.membership.id,
            metadata={
                "coverage_ids": acknowledged_ids,
                "requested_count": len(requested),
                "rejected_count": len(requested) - len(acknowledged_ids),
            },
        )
    session.commit()
    return IpCoverageBulkAcknowledgeResponse(
        acknowledged_count=len(acknowledged_ids),
        rejected_count=len(requested) - len(acknowledged_ids),
        outcomes=outcomes,
    )


def list_ip_assigned_coverage(
    session: Session,
    *,
    context: SessionContext,
    unacknowledged_only: bool = False,
) -> IpAssignedCoverageListResponse:
    """The caller's own deadlines (CAL-OPS-09).

    The daily docket counts each member's workload; this returns the work
    itself, so the count can be acted on rather than only read. Restricted
    records the caller cannot open are excluded, exactly as the counts are.
    """

    rows = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                IpDeadlineCoverage.responsible_membership_id == context.membership.id,
            )
            .order_by(IpDeadlineCoverage.id)
        ).all()
    )
    if not rows:
        return IpAssignedCoverageListResponse()

    dockets = {
        docket.id: docket
        for docket in session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_({row.docket_id for row in rows}),
                IpDocketRecord.company_id == context.company.id,
            )
        ).all()
    }
    deadlines = {
        deadline.id: deadline
        for deadline in session.scalars(
            select(MatterDeadline).where(
                MatterDeadline.id.in_({row.matter_deadline_id for row in rows} or {""})
            )
        ).all()
    }
    critical_ids = {
        value
        for value in session.scalars(
            select(IpDeadline.matter_deadline_id).where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.is_critical.is_(True),
                IpDeadline.matter_deadline_id.is_not(None),
            )
        ).all()
        if value
    }

    today = _now().date()
    records: list[IpAssignedCoverageRecord] = []
    for row in rows:
        docket = dockets.get(row.docket_id)
        if docket is None or not can_access_ip_docket(session, context=context, docket=docket):
            continue
        acknowledged = row.coverage_status == "accepted" and row.accepted_at is not None
        if unacknowledged_only and acknowledged:
            continue
        deadline = deadlines.get(row.matter_deadline_id)
        due_on = getattr(deadline, "due_on", None)
        records.append(
            IpAssignedCoverageRecord(
                coverage_id=row.id,
                docket_id=docket.id,
                docket_title=docket.title,
                docket_identifier=docket.primary_identifier,
                deadline_title=getattr(deadline, "title", None),
                due_on=due_on,
                days_until_due=(due_on - today).days if due_on else None,
                critical=row.matter_deadline_id in critical_ids,
                acknowledged=acknowledged,
                coverage_status=row.coverage_status,
                transfer_pending=row.replacement_decision == "pending",
                reassignment_version=row.reassignment_version,
            )
        )
    return IpAssignedCoverageListResponse(coverages=records)


def list_ip_coverage_transfers_awaiting(
    session: Session,
    *,
    context: SessionContext,
) -> IpCoverageTransfersAwaitingResponse:
    """Coverage transfers waiting on the calling member (CAL-OPS-08).

    A proposal is addressed to one person, so it is listed for that person
    rather than found by opening each docket. Access is re-checked at read
    time: a grant can be withdrawn after a transfer is proposed, and a record
    the reader may no longer open must not surface here.
    """

    rows = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                IpDeadlineCoverage.pending_replacement_membership_id == context.membership.id,
                IpDeadlineCoverage.replacement_decision == "pending",
            )
            .order_by(IpDeadlineCoverage.id)
        ).all()
    )
    if not rows:
        return IpCoverageTransfersAwaitingResponse()

    dockets = {
        docket.id: docket
        for docket in session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_({row.docket_id for row in rows}),
                IpDocketRecord.company_id == context.company.id,
            )
        ).all()
    }
    deadlines = {
        deadline.id: deadline
        for deadline in session.scalars(
            select(MatterDeadline).where(
                MatterDeadline.id.in_({row.matter_deadline_id for row in rows} or {""})
            )
        ).all()
    }
    critical_ids = {
        value
        for value in session.scalars(
            select(IpDeadline.matter_deadline_id).where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.is_critical.is_(True),
                IpDeadline.matter_deadline_id.is_not(None),
            )
        ).all()
        if value
    }

    members = {
        member.id: member
        for member in session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(CompanyMembership.company_id == context.company.id)
        ).all()
    }

    def _label(membership_id: str | None) -> str | None:
        if membership_id is None:
            return None
        member = members.get(membership_id)
        if member is None:
            return membership_id
        return member.user.full_name or member.user.email

    today = _now().date()
    transfers: list[IpCoverageTransferAwaiting] = []
    for row in rows:
        docket = dockets.get(row.docket_id)
        if docket is None or not can_access_ip_docket(session, context=context, docket=docket):
            continue
        deadline = deadlines.get(row.matter_deadline_id)
        due_on = getattr(deadline, "due_on", None)
        transfers.append(
            IpCoverageTransferAwaiting(
                coverage_id=row.id,
                docket_id=docket.id,
                docket_title=docket.title,
                docket_identifier=docket.primary_identifier,
                deadline_title=getattr(deadline, "title", None),
                due_on=due_on,
                days_until_due=(due_on - today).days if due_on else None,
                critical=row.matter_deadline_id in critical_ids,
                # The work has already moved when the responsible member is the
                # reader; that only happens on an immediate transfer.
                transfer_kind=(
                    "immediate"
                    if row.responsible_membership_id == context.membership.id
                    else "proposed"
                ),
                responsible_membership_id=row.responsible_membership_id,
                responsible_label=_label(row.responsible_membership_id)
                or row.responsible_membership_id,
                escalation_membership_id=row.emergency_escalation_membership_id,
                escalation_label=_label(row.emergency_escalation_membership_id),
                reason=row.replacement_decision_reason,
                reassignment_version=row.reassignment_version,
            )
        )
    return IpCoverageTransfersAwaitingResponse(transfers=transfers)


def preview_ip_coverage_reassignment(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCoverageReassignPreviewRequest,
) -> IpCoverageReassignPreviewResponse:
    """UJ-57-NORMAL — the atomic preview CAL-OPS-08 requires before a transfer."""

    if payload.from_membership_id == payload.to_membership_id:
        raise HTTPException(status_code=422, detail="Coverage replacement must be different.")
    _membership_or_404(session, context, payload.from_membership_id)
    replacement = _membership_or_404(session, context, payload.to_membership_id)

    rows = _coverages_for_member(
        session, context=context, membership_id=payload.from_membership_id
    )
    dockets = list(
        session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_({row.docket_id for row in rows} or {""}),
                IpDocketRecord.company_id == context.company.id,
            )
        ).all()
    )
    # The access decision is part of the preview, not a surprise at commit.
    blocked = [
        docket.id
        for docket in dockets
        if not can_access_ip_docket(
            session,
            context=SessionContext(
                company=context.company, user=replacement.user, membership=replacement
            ),
            docket=docket,
        )
    ]
    return IpCoverageReassignPreviewResponse(
        from_membership_id=payload.from_membership_id,
        to_membership_id=payload.to_membership_id,
        preview_token=_coverage_preview_token(rows),
        affected_coverage_ids=[row.id for row in rows],
        affected_docket_ids=sorted({row.docket_id for row in rows}),
        blocked_docket_ids=sorted(blocked),
        transfer_allowed=not blocked,
    )


def propose_ip_coverage_reassignment(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCoverageReassignProposeRequest,
) -> IpCoverageReassignPreviewResponse:
    """Propose a transfer; ownership does not move until it is accepted.

    CAL-OPS-08 requires an accepted replacement or approved emergency coverage,
    so a proposal marks each row ``pending`` and leaves the current owner in
    place. Emergency cover transfers immediately but is time-boxed and must name
    an escalation owner.
    """

    if payload.from_membership_id == payload.to_membership_id:
        raise HTTPException(status_code=422, detail="Coverage replacement must be different.")
    _membership_or_404(session, context, payload.from_membership_id)
    replacement = _membership_or_404(session, context, payload.to_membership_id)

    rows = _coverages_for_member(
        session, context=context, membership_id=payload.from_membership_id, for_update=True
    )
    # UJ-57-EXC-04: the preview must still describe reality.
    if _coverage_preview_token(rows) != payload.preview_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_preview_stale",
                "message": "Affected work changed after the preview; preview again.",
            },
        )

    dockets = list(
        session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_({row.docket_id for row in rows} or {""}),
                IpDocketRecord.company_id == context.company.id,
            )
        ).all()
    )
    _assert_replacement_can_cover(
        session, context=context, replacement=replacement, dockets=dockets
    )

    emergency_until = payload.emergency_until
    if emergency_until is not None:
        if payload.emergency_escalation_membership_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Emergency coverage requires an escalation owner.",
            )
        escalation = _membership_or_404(
            session, context, payload.emergency_escalation_membership_id
        )
        if _aware_utc(emergency_until) <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Emergency coverage must expire in the future.",
            )
    else:
        escalation = None

    now = _now()
    for row in rows:
        row.pending_replacement_membership_id = replacement.id
        row.replacement_decision_reason = payload.reason
        if emergency_until is not None:
            # UJ-57-EXC-05: emergency cover moves ownership now, but only until
            # it expires, and it always names who it escalates to.
            row.responsible_membership_id = replacement.id
            row.replacement_decision = "accepted"
            row.replacement_decided_at = now
            row.emergency_until = emergency_until
            row.emergency_escalation_membership_id = escalation.id if escalation else None
            row.coverage_status = "emergency"
        else:
            row.replacement_decision = "pending"
            row.replacement_decided_at = None
            row.coverage_status = "transfer_pending"
        row.reassignment_version += 1
        row.updated_at = now

    record_from_context(
        session,
        context,
        action="ip_deadline_coverage.transfer_proposed",
        target_type="company_membership",
        target_id=payload.from_membership_id,
        metadata={
            "to_membership_id": replacement.id,
            "coverage_ids": [row.id for row in rows],
            "emergency": emergency_until is not None,
            "reason": payload.reason,
        },
    )
    session.commit()
    refreshed = _coverages_for_member(
        session, context=context, membership_id=payload.from_membership_id
    )
    return IpCoverageReassignPreviewResponse(
        from_membership_id=payload.from_membership_id,
        to_membership_id=replacement.id,
        preview_token=_coverage_preview_token(refreshed),
        affected_coverage_ids=[row.id for row in rows],
        affected_docket_ids=sorted({row.docket_id for row in rows}),
        blocked_docket_ids=[],
        transfer_allowed=True,
    )


def decide_ip_coverage_replacement(
    session: Session,
    *,
    context: SessionContext,
    coverage_id: str,
    payload: IpCoverageReplacementDecisionRequest,
) -> IpDocketRecordResponse:
    """UJ-57-NORMAL / UJ-57-EXC-03 — the named replacement accepts or rejects."""

    row = session.scalar(
        select(IpDeadlineCoverage)
        .where(
            IpDeadlineCoverage.id == coverage_id,
            IpDeadlineCoverage.company_id == context.company.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Deadline coverage not found.")
    docket = _docket_or_404(session, context=context, docket_id=row.docket_id, for_update=True)
    if row.replacement_decision != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No replacement decision is pending for this coverage.",
        )
    if row.pending_replacement_membership_id != context.membership.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the named replacement may decide this transfer.",
        )

    now = _now()
    previous_owner = row.responsible_membership_id
    if payload.decision == "accepted":
        row.responsible_membership_id = context.membership.id
        if row.backup_membership_id == context.membership.id:
            row.backup_membership_id = None
        row.coverage_status = "accepted"
        row.accepted_at = now
    elif row.responsible_membership_id == context.membership.id:
        # UJ-57-EXC-03, immediate transfer: the work is already theirs, so a
        # rejection cannot simply be declined in place, and it must not go back
        # to a person who has left. It escalates to the named owner.
        escalation_id = row.emergency_escalation_membership_id
        if escalation_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_coverage_no_escalation_owner",
                    "message": (
                        "This transfer has no escalation owner, so declining it would "
                        "leave the deadline unowned. Reassign it explicitly instead."
                    ),
                },
            )
        _membership_or_404(session, context, escalation_id)
        row.responsible_membership_id = escalation_id
        if row.backup_membership_id == escalation_id:
            row.backup_membership_id = None
        row.coverage_status = "escalated"
        row.accepted_at = None
        row.calendar_projection_status = "pending"
    else:
        # UJ-57-EXC-03: a rejection returns the work, it never leaves it unowned.
        # In proposed mode the original owner never stopped holding it.
        row.coverage_status = "accepted" if row.accepted_at else "pending"
    row.replacement_decision = payload.decision
    row.replacement_decided_at = now
    if payload.reason is not None:
        # The field also carries the proposer's reason; an acceptance given
        # without a note must not erase why the transfer was asked for.
        row.replacement_decision_reason = payload.reason
    row.pending_replacement_membership_id = None
    row.reassignment_version += 1
    row.updated_at = now

    record_from_context(
        session,
        context,
        action=f"ip_deadline_coverage.transfer_{payload.decision}",
        target_type="ip_deadline_coverage",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "previous_responsible_membership_id": previous_owner,
            "responsible_membership_id": row.responsible_membership_id,
            "reason": payload.reason,
        },
    )
    session.commit()
    return _serialize_docket(session, docket)
