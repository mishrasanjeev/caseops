"""Explicit tenant admission for Matter writes that emit private events."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import CompanyMembership, PrivateIndexGeneration


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
