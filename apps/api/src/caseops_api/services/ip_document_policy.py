"""Read-only IP document disclosure policy without workflow dependencies."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
)
from caseops_api.schemas.ip_documents import IpDocumentPolicyResponse
from caseops_api.services.ip_domain_policy import (
    IP_DOCUMENT_CHILD_TARGET_MODELS,
    disclosable_ip_document_ids,
)
from caseops_api.services.record_access_policy import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

LOW_OCR_QUALITY_THRESHOLD = 0.65
_TARGET_MODELS = IP_DOCUMENT_CHILD_TARGET_MODELS


def get_accessible_ip_document_ids(
    session: Session,
    *,
    context: SessionContext,
    document_ids: set[str],
) -> set[str]:
    """Batch the canonical all-linked-targets access decision."""

    existing_ids = set(
        session.scalars(
            select(IpDocument.id).where(
                IpDocument.company_id == context.company.id,
                IpDocument.id.in_(document_ids),
            )
        )
    )
    if not existing_ids:
        return set()
    links = session.scalars(
        select(IpDocumentLink).where(
            IpDocumentLink.company_id == context.company.id,
            IpDocumentLink.document_id.in_(existing_ids),
        )
    ).all()
    links_by_document: dict[str, list[IpDocumentLink]] = defaultdict(list)
    targets_by_type: dict[str, set[str]] = defaultdict(set)
    for link in links:
        links_by_document[link.document_id].append(link)
        if link.target_type != "docket":
            targets_by_type[link.target_type].add(link.target_id)

    target_dockets: dict[tuple[str, str], str] = {}
    for target_type, target_ids in targets_by_type.items():
        model = _TARGET_MODELS.get(target_type)
        if model is None:
            continue
        target_rows = session.execute(
            select(model.id, model.docket_id).where(
                model.company_id == context.company.id,
                model.id.in_(target_ids),
            )
        ).all()
        target_dockets.update(
            {(target_type, str(target_id)): str(docket_id) for target_id, docket_id in target_rows}
        )

    docket_ids: set[str] = set()
    document_dockets: dict[str, set[str]] = defaultdict(set)
    invalid_documents: set[str] = set()
    for document_id, document_links in links_by_document.items():
        for link in document_links:
            docket_id = (
                link.target_id
                if link.target_type == "docket"
                else target_dockets.get((link.target_type, link.target_id))
            )
            if docket_id is None:
                invalid_documents.add(document_id)
                continue
            docket_ids.add(docket_id)
            document_dockets[document_id].add(docket_id)
    visible_docket_ids = set(
        session.scalars(
            select(IpDocketRecord.id).where(
                IpDocketRecord.company_id == context.company.id,
                IpDocketRecord.id.in_(docket_ids),
                visible_ip_dockets_filter(session, context=context),
            )
        ).all()
    )
    return {
        document_id
        for document_id in existing_ids
        if document_id not in invalid_documents
        and document_dockets.get(document_id, set()).issubset(visible_docket_ids)
    }



def get_ip_document_policies(
    session: Session,
    *,
    context: SessionContext,
    document_ids: set[str],
) -> dict[str, IpDocumentPolicyResponse]:
    """Batch current document policy and linked-target authorization.

    The single-document owner remains authoritative. This adapter applies the
    same all-links-must-be-visible rule without issuing one target query per
    document, which keeps scoped retrieval query work constant as its bounded
    candidate count grows.
    """

    accessible_ids = get_accessible_ip_document_ids(
        session,
        context=context,
        document_ids=document_ids,
    )
    if not accessible_ids:
        return {}
    rows = session.execute(
        select(IpDocument, IpDocumentVersion)
        .join(
            IpDocumentVersion,
            (IpDocumentVersion.document_id == IpDocument.id)
            & (IpDocumentVersion.version == IpDocument.current_version),
        )
        .where(
            IpDocument.company_id == context.company.id,
            IpDocument.id.in_(accessible_ids),
        )
    ).all()
    disclosable_ids = disclosable_ip_document_ids(
        session, company_id=context.company.id, document_ids=accessible_ids
    )
    return {
        document.id: _policy(
            document, version, domain_disclosure_allowed=document.id in disclosable_ids
        )
        for document, version in rows
    }



def _policy(
    document: IpDocument,
    version: IpDocumentVersion,
    *,
    domain_disclosure_allowed: bool,
) -> IpDocumentPolicyResponse:
    reasons: list[str] = []
    if not domain_disclosure_allowed:
        reasons.append("This IP domain has no enabled general disclosure workflow.")
    if document.is_privileged:
        reasons.append(
            "Attorney-client privileged documents are restricted from AI, portal, "
            "export, and notification content."
        )
    if document.confidentiality != "internal":
        reasons.append(
            f"Confidentiality label {document.confidentiality!r} restricts downstream disclosure."
        )
    low_quality = (
        version.ocr_quality_score is not None
        and version.ocr_quality_score < LOW_OCR_QUALITY_THRESHOLD
    )
    if low_quality:
        reasons.append("OCR/extraction quality is below the legal-use threshold.")
    if version.processing_status != "indexed":
        reasons.append("Document processing is not complete and indexed.")
    disclosure_allowed = (
        domain_disclosure_allowed
        and not document.is_privileged
        and document.confidentiality == "internal"
    )
    return IpDocumentPolicyResponse(
        ai_retrieval_allowed=(
            disclosure_allowed and version.processing_status == "indexed" and not low_quality
        ),
        portal_share_allowed=disclosure_allowed,
        export_allowed=disclosure_allowed,
        notification_content_allowed=disclosure_allowed,
        reasons=reasons,
    )
