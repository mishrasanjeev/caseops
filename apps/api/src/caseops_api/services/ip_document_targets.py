"""Shared target discovery and lifecycle fences for IP uploads and indexing."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import IpDocketRecord, IpDocumentLink, Matter
from caseops_api.schemas.ip_documents import IpDocumentLinkTarget
from caseops_api.services.ip_domain_policy import IP_DOCUMENT_CHILD_TARGET_MODELS
from caseops_api.services.ip_operations import _lock_ip_dockets_in_stable_order
from caseops_api.services.session_context import SessionContext


def _target_docket_id(
    session: Session,
    *,
    company_id: str,
    target: IpDocumentLinkTarget,
) -> str:
    if target.target_type == "docket":
        return target.target_id
    model = IP_DOCUMENT_CHILD_TARGET_MODELS[target.target_type]
    row = session.scalar(
        select(model).where(model.id == target.target_id, model.company_id == company_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="IP document link target not found.")
    return str(row.docket_id)


def _upload_target_lifecycles(
    session: Session, *, company_id: str, targets: list[IpDocumentLinkTarget]
) -> dict[tuple[str, str], tuple[str, int, str | None, int | None]]:
    discovered = {
        (target.target_type, target.target_id): _target_docket_id(
            session, company_id=company_id, target=target
        )
        for target in targets
    }
    states = {
        row.id: (row.id, row.lifecycle_version, row.matter_id, row.matter_lifecycle_version)
        for row in session.execute(
            select(
                IpDocketRecord.id,
                IpDocketRecord.lifecycle_version,
                IpDocketRecord.matter_id,
                Matter.lifecycle_version.label("matter_lifecycle_version"),
            )
            .outerjoin(
                Matter, (Matter.id == IpDocketRecord.matter_id) & (Matter.company_id == company_id)
            )
            .where(
                IpDocketRecord.company_id == company_id,
                IpDocketRecord.id.in_(set(discovered.values())),
            )
        )
    }
    if set(states) != set(discovered.values()):
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    return {target: states[docket_id] for target, docket_id in discovered.items()}


def _upload_document_targets(
    session: Session, *, company_id: str, document_id: str
) -> list[IpDocumentLinkTarget]:
    return [
        IpDocumentLinkTarget(target_type=row.target_type, target_id=row.target_id)
        for row in session.scalars(
            select(IpDocumentLink).where(
                IpDocumentLink.company_id == company_id,
                IpDocumentLink.document_id == document_id,
            )
        )
    ]


def _lock_upload_targets(
    session: Session,
    *,
    context: SessionContext,
    targets: list[IpDocumentLinkTarget],
    expected_lifecycles: dict[tuple[str, str], tuple[str, int, str | None, int | None]],
) -> None:
    discovered = {
        (target.target_type, target.target_id): _target_docket_id(
            session, company_id=context.company.id, target=target
        )
        for target in targets
    }
    _lock_ip_dockets_in_stable_order(
        session,
        context=context,
        docket_ids=set(discovered.values()),
        required_capability="documents:upload",
    )
    for (target_type, target_id), docket_id in sorted(discovered.items()):
        if target_type == "docket":
            continue
        model = IP_DOCUMENT_CHILD_TARGET_MODELS[target_type]
        row = session.scalar(
            select(model)
            .where(model.id == target_id, model.company_id == context.company.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if row is None or row.docket_id != docket_id:
            raise HTTPException(status_code=409, detail="IP document link target changed.")
    if (
        _upload_target_lifecycles(session, company_id=context.company.id, targets=targets)
        != expected_lifecycles
    ):
        raise HTTPException(
            status_code=409, detail="IP document target lifecycle changed during upload."
        )
