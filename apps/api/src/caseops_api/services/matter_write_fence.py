"""Explicit tenant admission for Matter writes that emit private events."""

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from caseops_api.db.models import CompanyMembership, PrivateIndexGeneration


def require_read_only_upload_session(session: Session, *, detail: str) -> None:
    """Reject caller-owned writes before an upload can release a transaction."""
    bind = session.get_bind()
    # A fresh Session can join a transaction it does not own on its first query.
    if isinstance(bind, Connection) and bind.in_transaction():
        raise HTTPException(status_code=409, detail=detail)
    caller_owns_writes = bool(
        session.new or session.dirty or session.deleted or session.in_nested_transaction()
    )
    if not caller_owns_writes:
        if not session.in_transaction():
            return
        connection = session.connection()
        if connection.dialect.name == "postgresql":
            if connection.scalar(text("SELECT pg_current_xact_id_if_assigned() IS NULL")) is True:
                return
        elif connection.dialect.name == "sqlite":
            if not connection.connection.driver_connection.in_transaction:
                return
    raise HTTPException(status_code=409, detail=detail)


def lock_matter_private_authority(session: Session, *, company_id: str) -> None:
    """Enter before actor/source locks and flushes, after external provider I/O.

    Outer callers must enter before their own locks/savepoints and reenter after
    every commit. This deliberately does not change assignment-helper defaults
    or cache admission across transactions. Actor authorization remains separate.
    """
    from caseops_api.services.private_retrieval import lock_private_authority_writer

    with session.no_autoflush:
        lock_private_authority_writer(session, company_id=company_id)


def lock_document_private_provenance(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str | None,
    requested_by_membership_id: str | None,
    uploaded_by_membership_id: str | None,
    locked_by_membership_id: str | None,
) -> None:
    """After Company, lock retained worker FKs before source/parent locks.

    This is historical provenance, not live actor authorization. Keep inactive
    memberships valid and use exactly the FK's KEY SHARE strength. Company
    admission makes the default-off generation check stable until commit. The
    bounded source/job references matter even without a private event: later
    dirty flushes can recheck unchanged FKs within the same transaction.
    """
    with session.no_autoflush:
        generation = session.scalar(
            select(PrivateIndexGeneration.id).where(
                PrivateIndexGeneration.company_id == company_id,
                PrivateIndexGeneration.state == "active",
            )
        )
        if generation is not None and actor_membership_id is None:
            raise ValueError("Document private event requires retained actor provenance.")
        membership_ids = sorted(
            {
                value
                for value in (
                    requested_by_membership_id,
                    uploaded_by_membership_id,
                    locked_by_membership_id,
                )
                if value is not None
            }
        )
        if actor_membership_id is not None and actor_membership_id not in membership_ids:
            raise ValueError("Document event actor must be retained source provenance.")
        if not membership_ids:
            return
        retained = list(
            session.scalars(
                select(CompanyMembership.id)
                .where(
                    CompanyMembership.company_id == company_id,
                    CompanyMembership.id.in_(membership_ids),
                )
                .order_by(CompanyMembership.id)
                .with_for_update(of=CompanyMembership, read=True, key_share=True)
            )
        )
        if retained != membership_ids:
            raise ValueError("Document retained actor does not belong to the company.")
