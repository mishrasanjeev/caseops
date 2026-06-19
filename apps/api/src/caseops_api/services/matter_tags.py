from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    Client,
    Matter,
    MatterTag,
    MatterTagAssignment,
    MembershipRole,
)
from caseops_api.schemas.matter_tags import (
    MatterBulkTagAssignRequest,
    MatterBulkTagAssignResponse,
    MatterTagAssignmentCreateRequest,
    MatterTagAssignmentRecord,
    MatterTagCreateRequest,
    MatterTagListResponse,
    MatterTagRecord,
    MatterTagSuggestionRecord,
    MatterTagSuggestionsResponse,
    MatterTagUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access, visible_matters_filter
from caseops_api.services.session_context import SessionContext


def slugify_tag(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "tag"


def _tag_record(tag: MatterTag) -> MatterTagRecord:
    return MatterTagRecord.model_validate(tag)


def _assignment_record(assignment: MatterTagAssignment) -> MatterTagAssignmentRecord:
    return MatterTagAssignmentRecord(
        id=assignment.id,
        matter_id=assignment.matter_id,
        tag=_tag_record(assignment.tag),
        source=assignment.source,  # type: ignore[arg-type]
        created_at=assignment.created_at,
    )


def _can_see_all_tags(context: SessionContext) -> bool:
    return context.membership.role in (MembershipRole.OWNER, MembershipRole.ADMIN)


def _visible_tags_query(session: Session, *, context: SessionContext):
    stmt = select(MatterTag).where(MatterTag.company_id == context.company.id)
    if _can_see_all_tags(context):
        return stmt.order_by(MatterTag.name.asc(), MatterTag.id.asc())
    return (
        stmt.join(MatterTagAssignment, MatterTagAssignment.tag_id == MatterTag.id)
        .join(Matter, Matter.id == MatterTagAssignment.matter_id)
        .where(MatterTagAssignment.company_id == context.company.id)
        .where(Matter.company_id == context.company.id)
        .where(visible_matters_filter(session, context=context))
        .order_by(MatterTag.name.asc(), MatterTag.id.asc())
    )


def _tag_visible_to_context(
    session: Session,
    *,
    context: SessionContext,
    tag_id: str,
) -> bool:
    if _can_see_all_tags(context):
        return True
    visible = session.scalar(
        _visible_tags_query(session, context=context)
        .where(MatterTag.id == tag_id)
        .limit(1)
    )
    return visible is not None


def _load_tag(
    session: Session,
    *,
    context: SessionContext,
    tag_id: str,
    require_visible: bool = False,
) -> MatterTag:
    tag = session.scalar(
        select(MatterTag)
        .where(MatterTag.id == tag_id)
        .where(MatterTag.company_id == context.company.id)
    )
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
    if require_visible and not _tag_visible_to_context(
        session,
        context=context,
        tag_id=tag.id,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
    return tag


def _load_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter)
        .options(selectinload(Matter.tag_assignments).joinedload(MatterTagAssignment.tag))
        .where(Matter.id == matter_id)
        .where(Matter.company_id == context.company.id)
    )
    if matter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return matter


def list_tags(session: Session, *, context: SessionContext) -> MatterTagListResponse:
    rows = list(
        session.scalars(_visible_tags_query(session, context=context)).unique()
    )
    return MatterTagListResponse(tags=[_tag_record(row) for row in rows])


def create_tag(
    session: Session,
    *,
    context: SessionContext,
    payload: MatterTagCreateRequest,
) -> MatterTagRecord:
    name = payload.name.strip()
    slug = payload.slug or slugify_tag(name)
    existing = session.scalar(
        select(MatterTag.id)
        .where(MatterTag.company_id == context.company.id)
        .where(MatterTag.slug == slug)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tag with this name already exists.",
        )
    tag = MatterTag(
        company_id=context.company.id,
        name=name,
        slug=slug,
        color_key=payload.color_key,
        created_by_membership_id=context.membership.id,
    )
    session.add(tag)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter_tag.created",
        target_type="matter_tag",
        target_id=tag.id,
        metadata={"name": tag.name, "slug": tag.slug, "color_key": tag.color_key},
    )
    return _tag_record(tag)


def update_tag(
    session: Session,
    *,
    context: SessionContext,
    tag_id: str,
    payload: MatterTagUpdateRequest,
) -> MatterTagRecord:
    tag = _load_tag(session, context=context, tag_id=tag_id)
    before = {"name": tag.name, "slug": tag.slug, "color_key": tag.color_key}
    if payload.name is not None:
        next_name = payload.name.strip()
        next_slug = slugify_tag(next_name)
        if next_slug != tag.slug:
            conflict = session.scalar(
                select(MatterTag.id)
                .where(MatterTag.company_id == context.company.id)
                .where(MatterTag.slug == next_slug)
                .where(MatterTag.id != tag.id)
            )
            if conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A tag with this name already exists.",
                )
        tag.name = next_name
        tag.slug = next_slug
    if payload.color_key is not None:
        tag.color_key = payload.color_key
    session.add(tag)
    session.flush()
    after = {"name": tag.name, "slug": tag.slug, "color_key": tag.color_key}
    if after != before:
        record_from_context(
            session,
            context,
            action="matter_tag.updated",
            target_type="matter_tag",
            target_id=tag.id,
            metadata={"before": before, "after": after},
        )
    return _tag_record(tag)


def delete_tag(session: Session, *, context: SessionContext, tag_id: str) -> None:
    tag = _load_tag(session, context=context, tag_id=tag_id)
    metadata = {"name": tag.name, "slug": tag.slug, "color_key": tag.color_key}
    record_from_context(
        session,
        context,
        action="matter_tag.deleted",
        target_type="matter_tag",
        target_id=tag.id,
        metadata=metadata,
    )
    session.delete(tag)


def assign_tag_to_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterTagAssignmentCreateRequest,
) -> MatterTagAssignmentRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    tag = _load_tag(
        session,
        context=context,
        tag_id=payload.tag_id,
        require_visible=True,
    )
    existing = session.scalar(
        select(MatterTagAssignment)
        .options(joinedload(MatterTagAssignment.tag))
        .where(MatterTagAssignment.company_id == context.company.id)
        .where(MatterTagAssignment.matter_id == matter.id)
        .where(MatterTagAssignment.tag_id == tag.id)
    )
    if existing:
        return _assignment_record(existing)
    assignment = MatterTagAssignment(
        company_id=context.company.id,
        matter_id=matter.id,
        tag_id=tag.id,
        source=payload.source,
        created_by_membership_id=context.membership.id,
    )
    assignment.tag = tag
    session.add(assignment)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter_tag.assigned",
        target_type="matter_tag_assignment",
        target_id=assignment.id,
        matter_id=matter.id,
        metadata={
            "matter_id": matter.id,
            "tag_id": tag.id,
            "tag_slug": tag.slug,
            "source": assignment.source,
        },
    )
    return _assignment_record(assignment)


def remove_tag_from_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    tag_id: str,
) -> None:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    tag = _load_tag(session, context=context, tag_id=tag_id, require_visible=True)
    assignment = session.scalar(
        select(MatterTagAssignment)
        .where(MatterTagAssignment.company_id == context.company.id)
        .where(MatterTagAssignment.matter_id == matter.id)
        .where(MatterTagAssignment.tag_id == tag.id)
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag assignment not found.",
        )
    record_from_context(
        session,
        context,
        action="matter_tag.unassigned",
        target_type="matter_tag_assignment",
        target_id=assignment.id,
        matter_id=matter.id,
        metadata={"matter_id": matter.id, "tag_id": tag.id, "tag_slug": tag.slug},
    )
    session.delete(assignment)


def bulk_assign_tag(
    session: Session,
    *,
    context: SessionContext,
    payload: MatterBulkTagAssignRequest,
) -> MatterBulkTagAssignResponse:
    tag = _load_tag(
        session,
        context=context,
        tag_id=payload.tag_id,
        require_visible=True,
    )
    matter_ids = list(dict.fromkeys(payload.matter_ids))
    matters = [
        _load_matter(session, context=context, matter_id=matter_id)
        for matter_id in matter_ids
    ]
    created: list[MatterTagAssignment] = []
    skipped = 0
    for matter in matters:
        existing = session.scalar(
            select(MatterTagAssignment.id)
            .where(MatterTagAssignment.company_id == context.company.id)
            .where(MatterTagAssignment.matter_id == matter.id)
            .where(MatterTagAssignment.tag_id == tag.id)
        )
        if existing:
            skipped += 1
            continue
        assignment = MatterTagAssignment(
            company_id=context.company.id,
            matter_id=matter.id,
            tag_id=tag.id,
            source=payload.source,
            created_by_membership_id=context.membership.id,
        )
        assignment.tag = tag
        session.add(assignment)
        created.append(assignment)
    session.flush()
    if created:
        record_from_context(
            session,
            context,
            action="matter_tag.bulk_assigned",
            target_type="matter_tag",
            target_id=tag.id,
            metadata={
                "tag_id": tag.id,
                "tag_slug": tag.slug,
                "matter_ids": [assignment.matter_id for assignment in created],
                "assigned_count": len(created),
                "skipped_count": skipped,
            },
        )
    return MatterBulkTagAssignResponse(
        assigned_count=len(created),
        skipped_count=skipped,
        assignments=[_assignment_record(assignment) for assignment in created],
    )


def suggest_tags_for_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> MatterTagSuggestionsResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    existing_tags = {
        tag.slug: tag.id
        for tag in session.scalars(_visible_tags_query(session, context=context)).unique()
    }
    suggestions: dict[str, MatterTagSuggestionRecord] = {}

    def add(name: str | None, source: str) -> None:
        if not name:
            return
        clean = " ".join(name.strip().split())
        if len(clean) < 2:
            return
        slug = slugify_tag(clean)
        suggestions.setdefault(
            slug,
            MatterTagSuggestionRecord(
                name=clean,
                slug=slug,
                source=source,  # type: ignore[arg-type]
                existing_tag_id=existing_tags.get(slug),
            ),
        )

    add(matter.client_name, "client_name")
    add(matter.opposing_party, "opposing_party")

    for client in session.scalars(
        select(Client)
        .where(Client.company_id == context.company.id)
        .order_by(Client.name.asc())
        .limit(20)
    ):
        add(client.name, "known_client")

    return MatterTagSuggestionsResponse(
        matter_id=matter.id,
        suggestions=sorted(suggestions.values(), key=lambda item: item.name.lower()),
    )
