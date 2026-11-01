"""Audited retirement of an IP document (never a hard delete).

A retired document keeps its versions, links, bytes and audit trail and stays
readable in the history view, but it is withdrawn from every picker and write
validator that accepts an IP document as evidence.

The refusal rule comes from the validators that accept a document as evidence.
Retirement is refused while a record that cited the document still relies on
it:

* a recordal (instrument, party evidence, filing or acceptance evidence) that
  is not withdrawn or rejected;
* a foreign-associate instruction (selected, privileged or filing evidence)
  that is not cancelled or superseded;
* a docket event that cites it and is not a rejected registry candidate
  (recordal and instruction events follow their record's status);
* a title interest not tied to a recordal whose recordal status is not
  withdrawn or rejected;
* a renewal term certificate;
* a client portal publication of any version (no product path revokes a
  single publication, so a shared document stays that publication's record);
* an immutable source pin of a patent or specialist record.

Withdrawn, rejected, cancelled and superseded records allow it: they keep
reading the retired document from history.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import String, cast, inspect, null, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.ip_specialist_models import (
    IpSpecialistObligationEvent,
    IpSpecialistObligationLink,
    IpSpecialistObservation,
    IpSpecialistRecord,
    IpSpecialistWorkflowSource,
)
from caseops_api.db.models import (
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
    IpForeignAssociateInstruction,
    IpPatentApplicationIdentifier,
    IpPatentApplicationVersion,
    IpPatentFamilyVersion,
    IpPatentPartyDetail,
    IpPatentPriorityDetail,
    IpPostRegistrationRecordal,
    IpRenewalTerm,
    IpTitleInterest,
    PortalPublication,
    utcnow,
)
from caseops_api.db.patent_proceeding_models import IpPatentProceedingEvent
from caseops_api.db.patent_prosecution_models import (
    IpPatentEvidenceDocument,
    IpPatentEvidenceVersion,
    IpPatentProsecutionEvent,
)
from caseops_api.schemas.ip_documents import (
    IpDocumentLinkTarget,
    IpDocumentRecord,
    IpDocumentRetirementBlocker,
    IpDocumentRetirementPreview,
    IpDocumentRetireRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.ip_document_targets import _target_docket_id
from caseops_api.services.ip_document_workflow import (
    _assert_document_targets_accessible,
    _propagate_private_document_change,
    _serialize_document,
)
from caseops_api.services.record_access_policy import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

# Statuses in which the citing record no longer relies on its evidence.
RECORDAL_RELEASED_STATUSES = frozenset({"withdrawn", "rejected"})
INSTRUCTION_RELEASED_STATUSES = frozenset({"cancelled", "superseded"})
TITLE_INTEREST_RELEASED_STATUSES = frozenset({"withdrawn", "rejected"})
EVENT_RELEASED_CANDIDATE_STATUSES = frozenset({"rejected"})

# Immutable source pins: a saved patent or specialist record that names this
# document as its source evidence. These never release the document.
_SOURCE_PINS: tuple[tuple[type, str, str], ...] = (
    (IpPatentFamilyVersion, "source_document_id", "Patent family disclosure version"),
    (IpPatentApplicationVersion, "source_document_id", "Patent application version"),
    (IpPatentApplicationIdentifier, "source_document_id", "Patent application identifier"),
    (IpPatentPartyDetail, "source_document_id", "Patent party record"),
    (IpPatentPriorityDetail, "source_document_id", "Patent priority record"),
    (IpPatentProceedingEvent, "source_document_id", "Patent proceeding event"),
    (IpPatentEvidenceVersion, "source_document_id", "Patent prosecution evidence"),
    (IpPatentEvidenceDocument, "document_id", "Patent prosecution evidence"),
    (IpPatentProsecutionEvent, "source_document_id", "Patent prosecution event"),
    (IpSpecialistObservation, "source_document_id", "Specialist record observation"),
    (IpSpecialistWorkflowSource, "document_id", "Specialist workflow source"),
    (IpSpecialistObligationLink, "document_id", "Specialist obligation evidence"),
    (IpSpecialistObligationEvent, "document_id", "Specialist obligation evidence"),
)

_MAY_RETIRE_NOTE = (
    "Only a document manager (owner, admin or partner) or the member who uploaded "
    "this document can retire it."
)


@dataclass(frozen=True)
class _Citation:
    kind: str
    record_id: str
    label: str
    status: str | None
    docket_id: str | None
    resolution: str
    href: str | None


def _readable(value: str | None) -> str:
    return (value or "").replace("_", " ").strip()


def _mentions(column, document_id: str):
    """Cheap SQL prefilter; every candidate is re-checked exactly in Python."""

    return cast(column, String).like(f"%{document_id}%")


def _cites(values: object, document_id: str) -> bool:
    return isinstance(values, list) and document_id in {str(item) for item in values}


def _recordal_citations(session: Session, company_id: str, document_id: str) -> list[_Citation]:
    columns = (
        IpPostRegistrationRecordal.supporting_instrument_refs_json,
        IpPostRegistrationRecordal.filing_evidence_refs_json,
        IpPostRegistrationRecordal.acceptance_evidence_refs_json,
        IpPostRegistrationRecordal.parties_json,
    )
    rows = session.scalars(
        select(IpPostRegistrationRecordal)
        .where(
            IpPostRegistrationRecordal.company_id == company_id,
            or_(*(_mentions(column, document_id) for column in columns)),
        )
        .order_by(IpPostRegistrationRecordal.created_at, IpPostRegistrationRecordal.id)
    ).all()
    found: list[_Citation] = []
    for row in rows:
        party_refs = [
            str(party.get("evidence_reference"))
            for party in (row.parties_json or [])
            if isinstance(party, dict)
        ]
        cited = (
            _cites(row.supporting_instrument_refs_json, document_id)
            or _cites(row.filing_evidence_refs_json, document_id)
            or _cites(row.acceptance_evidence_refs_json, document_id)
            or document_id in party_refs
        )
        if not cited or row.status in RECORDAL_RELEASED_STATUSES:
            continue
        found.append(
            _Citation(
                kind="recordal",
                record_id=row.id,
                label=f"{_readable(row.recordal_type).capitalize()} recordal",
                status=row.status,
                docket_id=row.docket_id,
                resolution=(
                    "Withdraw this recordal on Post-registration first."
                    if row.status != "accepted"
                    else "This recorded recordal keeps the document as its evidence."
                ),
                href="/app/ip/recordals",
            )
        )
    return found


def _instruction_citations(
    session: Session, company_id: str, document_id: str
) -> list[_Citation]:
    columns = (
        IpForeignAssociateInstruction.selected_document_refs_json,
        IpForeignAssociateInstruction.privileged_document_refs_json,
        IpForeignAssociateInstruction.filing_evidence_refs_json,
    )
    rows = session.scalars(
        select(IpForeignAssociateInstruction)
        .where(
            IpForeignAssociateInstruction.company_id == company_id,
            or_(*(_mentions(column, document_id) for column in columns)),
        )
        .order_by(IpForeignAssociateInstruction.id)
    ).all()
    found: list[_Citation] = []
    for row in rows:
        cited = (
            _cites(row.selected_document_refs_json, document_id)
            or _cites(row.privileged_document_refs_json, document_id)
            or _cites(row.filing_evidence_refs_json, document_id)
        )
        if not cited or row.status in INSTRUCTION_RELEASED_STATUSES:
            continue
        found.append(
            _Citation(
                kind="foreign_associate_instruction",
                record_id=row.id,
                label=f"Foreign associate instruction for {row.target_jurisdiction}",
                status=row.status,
                docket_id=row.docket_id,
                resolution=(
                    "This completed instruction keeps the document as its evidence."
                    if row.status == "completed"
                    else "Cancel this instruction on Foreign associates first."
                ),
                href="/app/ip/foreign-associates",
            )
        )
    return found


def _event_citations(session: Session, company_id: str, document_id: str) -> list[_Citation]:
    rows = session.scalars(
        select(IpDocketEvent)
        .where(
            IpDocketEvent.company_id == company_id,
            # Recordal and instruction events follow their own record's status.
            IpDocketEvent.recordal_id.is_(None),
            IpDocketEvent.foreign_associate_instruction_id.is_(None),
            or_(
                _mentions(IpDocketEvent.document_refs_json, document_id),
                _mentions(IpDocketEvent.evidence_refs_json, document_id),
            ),
        )
        .order_by(IpDocketEvent.docket_id, IpDocketEvent.sequence)
    ).all()
    found: list[_Citation] = []
    for row in rows:
        cited = _cites(row.document_refs_json, document_id) or _cites(
            row.evidence_refs_json, document_id
        )
        if not cited or row.candidate_status in EVENT_RELEASED_CANDIDATE_STATUSES:
            continue
        found.append(
            _Citation(
                kind="docket_event",
                record_id=row.id,
                label=(
                    f"{_readable(row.event_kind).capitalize()} event of "
                    f"{row.effective_at.date().isoformat()}"
                ),
                status=row.candidate_status,
                docket_id=row.docket_id,
                resolution="Recorded docket history keeps the document as its evidence.",
                href=f"/app/ip?docket={row.docket_id}",
            )
        )
    return found


def _title_interest_citations(
    session: Session, company_id: str, document_id: str
) -> list[_Citation]:
    rows = session.scalars(
        select(IpTitleInterest)
        .where(
            IpTitleInterest.company_id == company_id,
            IpTitleInterest.source_recordal_id.is_(None),
            IpTitleInterest.evidence_reference == document_id,
        )
        .order_by(IpTitleInterest.id)
    ).all()
    return [
        _Citation(
            kind="title_interest",
            record_id=row.id,
            label=f"{_readable(row.interest_type).capitalize()} interest of {row.party_name}",
            status=row.recordal_status,
            docket_id=row.docket_id,
            resolution="This title interest keeps the document as its evidence.",
            href=f"/app/ip?docket={row.docket_id}",
        )
        for row in rows
        if row.recordal_status not in TITLE_INTEREST_RELEASED_STATUSES
    ]


def _renewal_citations(session: Session, company_id: str, document_id: str) -> list[_Citation]:
    rows = session.scalars(
        select(IpRenewalTerm)
        .where(
            IpRenewalTerm.company_id == company_id,
            IpRenewalTerm.certificate_document_id == document_id,
        )
        .order_by(IpRenewalTerm.id)
    ).all()
    return [
        _Citation(
            kind="renewal_certificate",
            record_id=row.id,
            label="Renewal term certificate",
            status=None,
            docket_id=row.docket_id,
            resolution="A recorded renewal certificate stays as the term's evidence.",
            href="/app/ip/renewals",
        )
        for row in rows
    ]


def _publication_citations(
    session: Session, company_id: str, document_id: str
) -> list[_Citation]:
    version_ids = select(IpDocumentVersion.id).where(
        IpDocumentVersion.company_id == company_id,
        IpDocumentVersion.document_id == document_id,
    )
    rows = session.scalars(
        select(PortalPublication)
        .where(
            PortalPublication.company_id == company_id,
            PortalPublication.document_version_id.in_(version_ids),
            PortalPublication.status != "revoked",
        )
        .order_by(PortalPublication.id)
    ).all()
    return [
        _Citation(
            kind="portal_publication",
            record_id=row.id,
            label=f"Client portal publication: {row.title}",
            status=row.status,
            docket_id=None,
            # No product path revokes a single publication; a document shared
            # with the client stays that publication's record.
            resolution=(
                "Shared with the client through the portal; it stays as that "
                "publication's record."
            ),
            href="/app/ip/client-portal",
        )
        for row in rows
    ]


def _source_pin_citations(
    session: Session, company_id: str, document_id: str
) -> list[_Citation]:
    found: list[_Citation] = []
    for model, column_name, label in _SOURCE_PINS:
        column = getattr(model, column_name)
        key = inspect(model).primary_key[0]
        docket_column = getattr(model, "docket_id", None)
        if docket_column is None and model is IpSpecialistObservation:
            statement = (
                select(key, IpSpecialistRecord.docket_id)
                .join(
                    IpSpecialistRecord,
                    (IpSpecialistRecord.id == IpSpecialistObservation.record_id)
                    & (IpSpecialistRecord.company_id == IpSpecialistObservation.company_id),
                )
            )
        elif docket_column is not None:
            statement = select(key, docket_column)
        else:
            statement = select(key, null())
        rows = session.execute(
            statement.where(model.company_id == company_id, column == document_id)
            .order_by(key)
            .limit(50)
        ).all()
        found.extend(
            _Citation(
                kind="source_evidence",
                record_id=str(record_id),
                label=label,
                status=None,
                docket_id=str(docket_id) if docket_id else None,
                resolution="Saved as source evidence of this record; it stays current.",
                href=f"/app/ip?docket={docket_id}" if docket_id else None,
            )
            for record_id, docket_id in rows
        )
    return found


def document_retirement_citations(
    session: Session, *, company_id: str, document_id: str
) -> list[_Citation]:
    """Every record that still relies on ``document_id`` as evidence."""

    return [
        *_recordal_citations(session, company_id, document_id),
        *_instruction_citations(session, company_id, document_id),
        *_event_citations(session, company_id, document_id),
        *_title_interest_citations(session, company_id, document_id),
        *_renewal_citations(session, company_id, document_id),
        *_publication_citations(session, company_id, document_id),
        *_source_pin_citations(session, company_id, document_id),
    ]


def _blockers(
    session: Session, *, context: SessionContext, citations: Iterable[_Citation]
) -> list[IpDocumentRetirementBlocker]:
    citations = list(citations)
    docket_ids = {row.docket_id for row in citations if row.docket_id}
    titles: dict[str, str] = (
        dict(
            session.execute(
                select(IpDocketRecord.id, IpDocketRecord.title).where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.id.in_(docket_ids),
                    visible_ip_dockets_filter(session, context=context),
                )
            ).all()
        )
        if docket_ids
        else {}
    )
    blockers: list[IpDocumentRetirementBlocker] = []
    for row in citations:
        if row.docket_id and row.docket_id not in titles:
            # A record on a docket this viewer cannot open is counted, not described.
            blockers.append(
                IpDocumentRetirementBlocker(
                    kind=row.kind,  # type: ignore[arg-type]
                    record_id="restricted",
                    label="A record you cannot open",
                    resolution=(
                        "Ask a colleague with access to that record to release the document."
                    ),
                )
            )
            continue
        blockers.append(
            IpDocumentRetirementBlocker(
                kind=row.kind,  # type: ignore[arg-type]
                record_id=row.record_id,
                label=row.label,
                status=row.status,
                docket_id=row.docket_id,
                docket_title=titles.get(row.docket_id) if row.docket_id else None,
                resolution=row.resolution,
                href=row.href,
            )
        )
    return blockers


def _may_retire(session: Session, *, context: SessionContext, document: IpDocument) -> bool:
    if not membership_has_capability(session, context.membership, "ip:write"):
        return False
    if membership_has_capability(session, context.membership, "documents:manage"):
        return True
    return document.created_by_membership_id == context.membership.id and (
        membership_has_capability(session, context.membership, "documents:upload")
    )


def _linked_docket_ids(
    session: Session, *, company_id: str, document: IpDocument
) -> list[str]:
    links = session.scalars(
        select(IpDocumentLink).where(
            IpDocumentLink.company_id == company_id,
            IpDocumentLink.document_id == document.id,
        )
    ).all()
    return sorted(
        {
            _target_docket_id(
                session,
                company_id=company_id,
                target=IpDocumentLinkTarget(target_type=row.target_type, target_id=row.target_id),
            )
            for row in links
        }
    )


def _readable_document(
    session: Session, *, context: SessionContext, document_id: str, for_update: bool
) -> IpDocument:
    if for_update:
        from caseops_api.services.private_retrieval import lock_private_authority_writer

        # Same tenant-before-source order as every other IP document writer.
        lock_private_authority_writer(session, company_id=context.company.id)
    statement = select(IpDocument).where(
        IpDocument.id == document_id, IpDocument.company_id == context.company.id
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    document = session.scalar(statement)
    if document is None:
        raise HTTPException(status_code=404, detail="IP document not found.")
    # Every linked docket must be one the viewer may open (closed dockets
    # included: retiring a closed docket's leftovers is the main cleanup path).
    _assert_document_targets_accessible(
        session, context=context, document_id=document.id, include_closed_dockets=True
    )
    return document


def preview_ip_document_retirement(
    session: Session, *, context: SessionContext, document_id: str
) -> IpDocumentRetirementPreview:
    document = _readable_document(
        session, context=context, document_id=document_id, for_update=False
    )
    may_retire = _may_retire(session, context=context, document=document)
    blockers = (
        []
        if document.retired_at is not None
        else _blockers(
            session,
            context=context,
            citations=document_retirement_citations(
                session, company_id=context.company.id, document_id=document.id
            ),
        )
    )
    return IpDocumentRetirementPreview(
        document_id=document.id,
        title=document.title,
        current_version=document.current_version,
        already_retired=document.retired_at is not None,
        may_retire=may_retire,
        permission_reason=None if may_retire else _MAY_RETIRE_NOTE,
        blockers=blockers,
        retirable=may_retire and document.retired_at is None and not blockers,
    )


def retire_ip_document(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    payload: IpDocumentRetireRequest,
) -> IpDocumentRecord:
    document = _readable_document(
        session, context=context, document_id=document_id, for_update=True
    )
    if not _may_retire(session, context=context, document=document):
        raise HTTPException(
            status_code=403,
            detail={"code": "ip_document_retire_forbidden", "message": _MAY_RETIRE_NOTE},
        )
    if document.retired_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_already_retired",
                "message": "This document is already retired.",
            },
        )
    if document.current_version != payload.expected_current_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_version_conflict",
                "message": "A new version was uploaded. Reload the document before retiring it.",
                "current_version": document.current_version,
            },
        )
    # Citations are read after the document row lock: a citing writer either
    # committed first (and is seen here) or waits on its shared lock and then
    # finds the document retired.
    citations = document_retirement_citations(
        session, company_id=context.company.id, document_id=document.id
    )
    if citations:
        blockers = _blockers(session, context=context, citations=citations)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_retirement_blocked",
                "message": (
                    "1 record still relies on this document as evidence. Release it "
                    "before retiring the document."
                    if len(blockers) == 1
                    else f"{len(blockers)} records still rely on this document as "
                    "evidence. Release them before retiring the document."
                ),
                "blockers": [row.model_dump(mode="json") for row in blockers],
            },
        )
    document.retired_at = utcnow()
    document.retired_by_membership_id = context.membership.id
    document.retirement_reason = payload.reason
    session.add(document)
    _propagate_private_document_change(
        session,
        context=context,
        document=document,
        event_type="access_changed",
        reason_code="ip_document_retired",
        idempotency_key=f"ip-document-retired:{document.id}",
    )
    docket_ids = _linked_docket_ids(session, company_id=context.company.id, document=document)
    record_from_context(
        session,
        context,
        action="ip_document.retired",
        target_type="ip_document",
        target_id=document.id,
        # A single-docket document also appears in that docket's audit trail.
        ip_docket_id=docket_ids[0] if len(docket_ids) == 1 else None,
        metadata={
            "title": document.title,
            "current_version": document.current_version,
            "reason": payload.reason,
            "docket_ids": docket_ids,
            "uploaded_by_actor": document.created_by_membership_id == context.membership.id,
        },
    )
    session.commit()
    return _serialize_document(session, context=context, document=document)


__all__ = [
    "document_retirement_citations",
    "preview_ip_document_retirement",
    "retire_ip_document",
]
