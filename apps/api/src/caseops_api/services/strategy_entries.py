from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterStrategyEntry,
    Recommendation,
)
from caseops_api.schemas.recommendations import (
    MatterStrategyEntryCreateRequest,
    MatterStrategyEntryListResponse,
    MatterStrategyEntryRecord,
    MatterStrategyEntryUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access


def _member_name(membership: CompanyMembership | None) -> str | None:
    if membership is None or membership.user is None:
        return None
    return membership.user.full_name or membership.user.email


def _record(entry: MatterStrategyEntry) -> MatterStrategyEntryRecord:
    return MatterStrategyEntryRecord(
        id=entry.id,
        company_id=entry.company_id,
        matter_id=entry.matter_id,
        title=entry.title,
        body=entry.body,
        entry_type=entry.entry_type,
        status=entry.status,
        owner_membership_id=entry.owner_membership_id,
        owner_name=_member_name(entry.owner_membership),
        created_by_membership_id=entry.created_by_membership_id,
        created_by_name=_member_name(entry.created_by_membership),
        updated_by_membership_id=entry.updated_by_membership_id,
        updated_by_name=_member_name(entry.updated_by_membership),
        source_recommendation_id=entry.source_recommendation_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _load_visible_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _load_entry(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    entry_id: str,
) -> MatterStrategyEntry:
    _load_visible_matter(session, context=context, matter_id=matter_id)
    entry = session.scalar(
        select(MatterStrategyEntry)
        .options(
            selectinload(MatterStrategyEntry.owner_membership).selectinload(
                CompanyMembership.user
            ),
            selectinload(MatterStrategyEntry.created_by_membership).selectinload(
                CompanyMembership.user
            ),
            selectinload(MatterStrategyEntry.updated_by_membership).selectinload(
                CompanyMembership.user
            ),
        )
        .where(
            MatterStrategyEntry.id == entry_id,
            MatterStrategyEntry.company_id == context.company.id,
            MatterStrategyEntry.matter_id == matter_id,
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy entry not found.",
        )
    return entry


def _validate_owner(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str | None,
) -> str | None:
    if membership_id is None:
        return None
    membership = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == context.company.id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Strategy owner must be an active membership in this company.",
        )
    return membership.id


def _validate_source_recommendation(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    recommendation_id: str | None,
) -> str | None:
    if recommendation_id is None:
        return None
    recommendation = session.scalar(
        select(Recommendation.id).where(
            Recommendation.id == recommendation_id,
            Recommendation.company_id == context.company.id,
            Recommendation.matter_id == matter_id,
        )
    )
    if recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Source recommendation must belong to this matter.",
        )
    return recommendation


def _snapshot(entry: MatterStrategyEntry) -> dict[str, Any]:
    return {
        "title": entry.title,
        "body": entry.body,
        "entry_type": entry.entry_type,
        "status": entry.status,
        "owner_membership_id": entry.owner_membership_id,
        "source_recommendation_id": entry.source_recommendation_id,
    }


def list_strategy_entries(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> MatterStrategyEntryListResponse:
    matter = _load_visible_matter(session, context=context, matter_id=matter_id)
    entries = list(
        session.scalars(
            select(MatterStrategyEntry)
            .options(
                selectinload(MatterStrategyEntry.owner_membership).selectinload(
                    CompanyMembership.user
                ),
                selectinload(MatterStrategyEntry.created_by_membership).selectinload(
                    CompanyMembership.user
                ),
                selectinload(MatterStrategyEntry.updated_by_membership).selectinload(
                    CompanyMembership.user
                ),
            )
            .where(
                MatterStrategyEntry.company_id == context.company.id,
                MatterStrategyEntry.matter_id == matter.id,
            )
            .order_by(
                MatterStrategyEntry.updated_at.desc(),
                MatterStrategyEntry.created_at.desc(),
                MatterStrategyEntry.id.desc(),
            )
        )
    )
    return MatterStrategyEntryListResponse(
        matter_id=matter.id,
        entries=[_record(entry) for entry in entries],
    )


def create_strategy_entry(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterStrategyEntryCreateRequest,
) -> MatterStrategyEntryRecord:
    matter = _load_visible_matter(session, context=context, matter_id=matter_id)
    owner_id = _validate_owner(
        session,
        context=context,
        membership_id=payload.owner_membership_id or context.membership.id,
    )
    source_id = _validate_source_recommendation(
        session,
        context=context,
        matter_id=matter.id,
        recommendation_id=payload.source_recommendation_id,
    )
    entry = MatterStrategyEntry(
        company_id=context.company.id,
        matter_id=matter.id,
        title=payload.title.strip(),
        body=payload.body.strip(),
        entry_type=payload.entry_type,
        status=payload.status,
        owner_membership_id=owner_id,
        created_by_membership_id=context.membership.id,
        updated_by_membership_id=context.membership.id,
        source_recommendation_id=source_id,
    )
    session.add(entry)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter_strategy.created",
        target_type="matter_strategy_entry",
        target_id=entry.id,
        matter_id=matter.id,
        metadata={"after": _snapshot(entry)},
    )
    session.commit()
    return _record(_load_entry(session, context=context, matter_id=matter.id, entry_id=entry.id))


def update_strategy_entry(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    entry_id: str,
    payload: MatterStrategyEntryUpdateRequest,
) -> MatterStrategyEntryRecord:
    entry = _load_entry(session, context=context, matter_id=matter_id, entry_id=entry_id)
    before = _snapshot(entry)
    if "title" in payload.model_fields_set and payload.title is not None:
        entry.title = payload.title.strip()
    if "body" in payload.model_fields_set and payload.body is not None:
        entry.body = payload.body.strip()
    if "entry_type" in payload.model_fields_set and payload.entry_type is not None:
        entry.entry_type = payload.entry_type
    if "status" in payload.model_fields_set and payload.status is not None:
        entry.status = payload.status
    if "owner_membership_id" in payload.model_fields_set:
        entry.owner_membership_id = _validate_owner(
            session,
            context=context,
            membership_id=payload.owner_membership_id,
        )
    if "source_recommendation_id" in payload.model_fields_set:
        entry.source_recommendation_id = _validate_source_recommendation(
            session,
            context=context,
            matter_id=matter_id,
            recommendation_id=payload.source_recommendation_id,
        )
    entry.updated_by_membership_id = context.membership.id
    session.flush()
    after = _snapshot(entry)
    record_from_context(
        session,
        context,
        action="matter_strategy.updated",
        target_type="matter_strategy_entry",
        target_id=entry.id,
        matter_id=matter_id,
        metadata={"before": before, "after": after},
    )
    session.commit()
    return _record(_load_entry(session, context=context, matter_id=matter_id, entry_id=entry.id))


def delete_strategy_entry(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    entry_id: str,
) -> None:
    entry = _load_entry(session, context=context, matter_id=matter_id, entry_id=entry_id)
    before = _snapshot(entry)
    session.delete(entry)
    record_from_context(
        session,
        context,
        action="matter_strategy.deleted",
        target_type="matter_strategy_entry",
        target_id=entry.id,
        matter_id=matter_id,
        metadata={"before": before},
    )
    session.commit()
