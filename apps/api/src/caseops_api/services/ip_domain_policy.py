"""Domain boundaries for existing trademark-only and disclosure surfaces."""

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from caseops_api.db.models import (
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpProceeding,
    TrademarkApplication,
)
from caseops_api.services.ip_specialist_contracts import RECORD_TYPES as SPECIALIST_RECORD_TYPES

# New domains opt in only after their disclosure journey is implemented.
GENERAL_DISCLOSURE_DOMAINS = ("trademark",)
RECORD_DOMAINS = {
    **SPECIALIST_RECORD_TYPES,
    "patent_family": "patent",
    "patent_application": "patent",
    "trademark": "trademark",
    "international_registration": "trademark",
    "international_designation": "trademark",
}
TRADEMARK_RECORD_TYPES = tuple(
    record_type for record_type, domain in RECORD_DOMAINS.items() if domain == "trademark"
)
IP_DOCUMENT_CHILD_TARGET_MODELS = {
    "application": TrademarkApplication,
    "proceeding": IpProceeding,
    "event": IpDocketEvent,
    "deadline": IpDeadline,
}


def general_ip_disclosure_allowed(docket: IpDocketRecord) -> bool:
    return RECORD_DOMAINS.get(docket.record_type) in GENERAL_DISCLOSURE_DOMAINS


def general_ip_disclosure_filter() -> ColumnElement[bool]:
    return IpDocketRecord.record_type.in_(tuple(
        record_type for record_type, domain in RECORD_DOMAINS.items()
        if domain in GENERAL_DISCLOSURE_DOMAINS
    ))


def general_ip_document_disclosure_filter() -> ColumnElement[bool]:
    """Every link must resolve to a disclosure-enabled domain, before LIMIT."""
    visible_dockets = select(IpDocketRecord.id).where(
        IpDocketRecord.company_id == IpDocumentLink.company_id,
        general_ip_disclosure_filter(),
    ).correlate(IpDocumentLink)
    allowed = [and_(
        IpDocumentLink.target_type == "docket",
        IpDocumentLink.target_id.in_(visible_dockets),
    )]
    for target_type, model in IP_DOCUMENT_CHILD_TARGET_MODELS.items():
        targets = select(model.id).join(
            IpDocketRecord,
            and_(IpDocketRecord.id == model.docket_id,
                 IpDocketRecord.company_id == model.company_id),
        ).where(
            model.company_id == IpDocumentLink.company_id,
            general_ip_disclosure_filter(),
        ).correlate(IpDocumentLink)
        allowed.append(and_(
            IpDocumentLink.target_type == target_type, IpDocumentLink.target_id.in_(targets)
        ))
    return ~exists(select(IpDocumentLink.id).where(
        IpDocumentLink.company_id == IpDocument.company_id,
        IpDocumentLink.document_id == IpDocument.id,
        ~or_(*allowed),
    ).correlate(IpDocument))


def disclosable_ip_document_ids(
    session: Session, *, company_id: str, document_ids: set[str]
) -> set[str]:
    if not document_ids:
        return set()
    return set(session.scalars(select(IpDocument.id).where(
        IpDocument.company_id == company_id,
        IpDocument.id.in_(document_ids),
        general_ip_document_disclosure_filter(),
    )))


def assert_trademark_docket(docket: IpDocketRecord) -> None:
    if docket.record_type not in TRADEMARK_RECORD_TYPES:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_domain_workflow_mismatch",
                "message": "Open this record in its own IP domain workspace.",
            },
        )
