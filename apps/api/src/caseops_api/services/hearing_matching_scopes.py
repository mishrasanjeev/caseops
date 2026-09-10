"""Freeze current, authorized Matter identities across the existing provider lease."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Matter, TrackedCase, TrackedCaseBookmark
from caseops_api.services.hearing_matching import HearingIdentity
from caseops_api.services.matter_access import visible_matters_filter
from caseops_api.services.matter_operational_guard import matter_is_operational
from caseops_api.services.session_context import SessionContext

MAX_MATCH_SCOPES = 50
AUTOMATIC_LINK_SOURCES = {"matter_create_auto_link", "scheduled_existing_matter_backfill"}


def automatic_matter_link(tracked_case: TrackedCase) -> bool:
    return (tracked_case.metadata_json or {}).get("source") in AUTOMATIC_LINK_SOURCES


def matter_identity(matter: Matter) -> HearingIdentity:
    return HearingIdentity(
        cnr=matter.cnr_number,
        case_number=matter.case_number,
        filing_number=matter.filing_number,
        court_name=matter.court_name,
        state=matter.forum_state,
        district=matter.forum_district,
        city=matter.forum_city,
        parties=tuple(x for x in (matter.client_name, matter.opposing_party) if x),
        advocates=tuple(x for x in (matter.opposing_counsel,) if x),
    )


@dataclass(frozen=True)
class HearingScope:
    bookmark_id: str
    matter_id: str | None
    identity: HearingIdentity
    lifecycle_version: int | None
    access_policy_version: int | None


def capture_hearing_scopes(
    session: Session,
    *,
    context: SessionContext,
    tracked_case: TrackedCase,
    lock: bool = False,
) -> tuple[HearingScope, ...]:
    bookmarks = list(
        session.scalars(
            select(TrackedCaseBookmark)
            .where(
                TrackedCaseBookmark.company_id == context.company.id,
                TrackedCaseBookmark.tracked_case_id == tracked_case.id,
                TrackedCaseBookmark.is_archived.is_(False),
            )
            .order_by(TrackedCaseBookmark.id)
            .limit(MAX_MATCH_SCOPES + 1)
            .execution_options(populate_existing=True)
        )
    )
    if len(bookmarks) > MAX_MATCH_SCOPES:
        raise HTTPException(409, "Case matching scope exceeds the bounded refresh limit.")

    def signature(bookmark: TrackedCaseBookmark) -> tuple:
        return (
            bookmark.id,
            bookmark.matter_id,
            bookmark.created_by_membership_id,
            bookmark.scope_key,
            bookmark.active_scope_key,
        )

    initial = {bookmark.id: signature(bookmark) for bookmark in bookmarks}
    ids = sorted({row.matter_id for row in bookmarks if row.matter_id})
    authorized = (
        set(
            session.scalars(
                select(Matter.id).where(
                    Matter.company_id == context.company.id,
                    Matter.id.in_(ids),
                    visible_matters_filter(session, context=context),
                )
            )
        )
        if ids
        else set()
    )
    # Another actor's private source cannot become this actor's search input,
    # publication target or prerequisite for refreshing their own bookmark.
    bookmarks = [row for row in bookmarks if row.matter_id is None or row.matter_id in authorized]
    ids = sorted({row.matter_id for row in bookmarks if row.matter_id})
    statement = (
        select(Matter)
        .where(Matter.company_id == context.company.id, Matter.id.in_(ids))
        .order_by(Matter.id)
    )
    if lock:
        statement = statement.with_for_update(of=Matter)
    matters = (
        {
            row.id: row
            for row in session.scalars(statement.execution_options(populate_existing=True))
        }
        if ids
        else {}
    )
    if lock and bookmarks:
        expected = tuple(initial[row.id] for row in bookmarks)
        # Keep the lifecycle lock order: Matter first, then its bookmark rows.
        # Re-read after both locks so a completed archive/retarget cannot leave
        # stale ORM children eligible between scope discovery and publication.
        bookmarks = list(
            session.scalars(
                select(TrackedCaseBookmark)
                .where(
                    TrackedCaseBookmark.company_id == context.company.id,
                    TrackedCaseBookmark.tracked_case_id == tracked_case.id,
                    TrackedCaseBookmark.id.in_([row.id for row in bookmarks]),
                    TrackedCaseBookmark.is_archived.is_(False),
                )
                .order_by(TrackedCaseBookmark.id)
                .with_for_update(of=TrackedCaseBookmark)
                .execution_options(populate_existing=True)
            )
        )
        if tuple(signature(row) for row in bookmarks) != expected:
            raise HTTPException(409, "Bookmark scope changed during hearing publication.")
    scopes = []
    for bookmark in bookmarks:
        matter = matters.get(bookmark.matter_id)
        if bookmark.matter_id:
            if matter is None or not matter_is_operational(matter):
                raise HTTPException(409, "Case matching Matter is no longer operational.")
            scopes.append(
                HearingScope(
                    bookmark.id,
                    matter.id,
                    matter_identity(matter),
                    matter.lifecycle_version,
                    matter.access_policy_version,
                )
            )
        else:
            scopes.append(
                HearingScope(
                    bookmark.id,
                    None,
                    HearingIdentity(
                        cnr=tracked_case.cnr_number,
                        case_number=tracked_case.case_number,
                        court_code=tracked_case.court_code,
                        court_name=tracked_case.court_name,
                        parties=tuple(tracked_case.party_names_json or ()),
                    ),
                    None,
                    None,
                )
            )
    return tuple(scopes)
