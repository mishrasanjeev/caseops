"""Which IP documents a writer may still cite as evidence.

A retired document is kept for history only. Every citing writer, including
the IP operations and lifecycle writers, reads this leaf instead of the
document workflow, so citation checks add no edge back into that workflow.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import IpDocument


def citable_ip_document_ids(
    session: Session,
    *,
    company_id: str,
    document_ids: set[str],
    lock: bool = False,
) -> set[str]:
    """The subset of ``document_ids`` that is not retired.

    Every picker and write validator that accepts an IP document as evidence
    intersects its own candidates with this set. Write validators pass
    ``lock=True``: the shared row lock serializes the citation with a
    concurrent retirement, which takes the document row FOR UPDATE and then
    re-reads every citation.
    """

    if not document_ids:
        return set()
    statement = select(IpDocument.id).where(
        IpDocument.company_id == company_id,
        IpDocument.id.in_(document_ids),
        IpDocument.retired_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update(read=True)
    return set(session.scalars(statement).all())


def reject_retired_document_refs(
    session: Session,
    *,
    company_id: str,
    refs: Iterable[object],
) -> None:
    """Refuse a free-text evidence reference that names a retired IP document.

    Docket events and title interests store evidence references as free text.
    When a value is the id of one of the tenant's IP documents, retirement
    counts that row as a citation, so the writer refuses a retired document and
    takes the same shared row lock as every other citing writer. Text that
    names no IP document is left alone.
    """

    named = {ref for ref in refs if isinstance(ref, str) and ref}
    if not named:
        return
    documents = set(
        session.scalars(
            select(IpDocument.id).where(
                IpDocument.company_id == company_id,
                IpDocument.id.in_(named),
            )
        ).all()
    )
    if not documents:
        return
    current = citable_ip_document_ids(
        session, company_id=company_id, document_ids=documents, lock=True
    )
    if documents - current:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_retired",
                "message": (
                    "A cited evidence document was retired and is kept for history only. "
                    "Cite a current document."
                ),
            },
        )
