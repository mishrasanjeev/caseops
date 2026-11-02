"""PostgreSQL typed scalar pages; complete current policy precedes group bounds.

Each current company/Matter/owner group contributes at most its next 26 rows.
The globally first 26 must occur in that union. No owner/team prelimit is used.
Dense ordered 25-slot pages mean two leaves suffice after the exact continuation
and date bounds. Current Matter facts are joined, never copied into storage.
"""

from datetime import date

from sqlalchemy import Date, and_, case, column, exists, literal, select, true, tuple_, values
from sqlalchemy.orm import aliased

from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterTaskQueueGroup,
    MatterTaskQueuePage,
    TeamMembership,
    User,
)
from caseops_api.db.statement_clock import StatementUtc
from caseops_api.db.task_queue_page_models import SLOTS, TASK_FIELDS
from caseops_api.services.matter_work_queue_policy import _current_actor, _utc
from caseops_api.services.record_access_policy import active_actor_team_ids, visible_matters_filter


def sort_key(columns):
    return (
        columns.due_on.is_(None),
        case((columns.due_on.is_(None), literal(date.min, type_=Date)), else_=columns.due_on),
        columns.created_at,
        columns.id,
    )


def statement(
    session,
    *,
    context,
    ownership,
    dates,
    lower=None,
    upper=None,
    anchor=None,
    outer_bound=True,
    _actor_fence=None,
    _owner_teams=None,
):
    groups = MatterTaskQueueGroup.__table__
    pages = MatterTaskQueuePage.__table__
    if type(outer_bound) is not bool:
        raise ValueError("The global page bound must be explicit.")
    if dates not in {"all", "dated", "undated"}:
        raise ValueError("Unsupported work date view.")
    if ownership == "mine":
        owner = and_(groups.c.owner_is_null.is_(False), groups.c.owner_key == context.membership.id)
    elif ownership == "unassigned":
        owner = groups.c.owner_is_null.is_(True)
    elif ownership == "team":
        teams = (
            active_actor_team_ids(
                company_id=context.company.id, membership_id=context.membership.id
            )
            if _owner_teams is None
            else _owner_teams
        )
        peer = aliased(CompanyMembership, name="page_queue_owner")
        user = aliased(User, name="page_queue_owner_user")
        shared = aliased(TeamMembership, name="page_queue_owner_team")
        owner = and_(
            groups.c.owner_is_null.is_(False),
            groups.c.owner_key != context.membership.id,
            exists(
                select(peer.id)
                .join(user, user.id == peer.user_id)
                .join(shared, shared.membership_id == peer.id)
                .where(
                    peer.id == groups.c.owner_key,
                    peer.company_id == context.company.id,
                    peer.is_active.is_(True),
                    user.is_active.is_(True),
                    shared.team_id.in_(select(teams.c.team_id)),
                )
            ),
        )
    else:
        raise ValueError("Unsupported work ownership.")
    eligible = (
        select(
            groups.c.id.label("group_id"),
            case((groups.c.owner_is_null.is_(True), None), else_=groups.c.owner_key).label(
                "owner_membership_id"
            ),
            Matter.id.label("matter_id"),
            Matter.title.label("matter_title"),
            Matter.matter_code,
            Matter.status.label("matter_status"),
            Matter.is_active,
            Matter.lifecycle_version,
        )
        .select_from(
            groups.join(
                Matter,
                and_(Matter.id == groups.c.matter_id, Matter.company_id == groups.c.company_id),
            )
        )
        .where(
            _current_actor(context) if _actor_fence is None else _actor_fence,
            groups.c.company_id == context.company.id,
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.in_(("intake", "active", "on_hold")),
            owner,
            visible_matters_filter(session, context=context, statement_time=StatementUtc()),
        )
        .cte("queue_current_eligible_groups")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    page_filters = [pages.c.group_id == eligible.c.group_id]
    if dates == "dated":
        page_filters.append(pages.c.has_dated.is_(True))
    elif dates == "undated":
        page_filters.append(pages.c.has_undated.is_(True))
    if lower is not None:
        page_filters.append(pages.c.max_dated >= lower)
    if upper is not None:
        page_filters.append(pages.c.min_dated <= upper)
    if anchor is not None:
        anchor_key = (
            anchor["due_on"] is None,
            anchor["due_on"] or date.min,
            _utc(anchor["created_at"]),
            anchor["id"],
        )
        page_filters.append(
            tuple_(pages.c.last_null, pages.c.last_date, pages.c.last_created, pages.c.last_id)
            > tuple_(*anchor_key)
        )
    page = (
        select(*pages.c)
        .where(*page_filters)
        .order_by(pages.c.page_no)
        .limit(2)
        .correlate(eligible)
        .lateral("queue_two_dense_pages")
    )
    typed = [column(name, pages.c[f"s0_{name}"].type) for name in TASK_FIELDS]
    slots = (
        values(*typed)
        .data([tuple(page.c[f"s{i}_{name}"] for name in TASK_FIELDS) for i in range(SLOTS)])
        .lateral("queue_fixed_slots")
    )
    predicates = [slots.c.id.is_not(None)]
    if dates == "dated":
        predicates.append(slots.c.due_on.is_not(None))
    elif dates == "undated":
        predicates.append(slots.c.due_on.is_(None))
    if lower is not None:
        predicates.append(slots.c.due_on >= lower)
    if upper is not None:
        predicates.append(slots.c.due_on <= upper)
    if anchor is not None:
        predicates.append(tuple_(*sort_key(slots.c)) > tuple_(*anchor_key))
    group_page = (
        select(
            *[slots.c[name] for name in TASK_FIELDS],
            eligible.c.owner_membership_id,
            eligible.c.matter_id,
            eligible.c.matter_title,
            eligible.c.matter_code,
            eligible.c.matter_status,
            eligible.c.is_active,
            eligible.c.lifecycle_version,
        )
        .select_from(page.join(slots, true()))
        .where(*predicates)
        .order_by(*sort_key(slots.c))
        .limit(26)
        .correlate(eligible)
        .lateral("queue_group_first26")
    )
    result = select(*group_page.c).select_from(eligible.join(group_page, true()))
    # The standalone contract remains globally ordered and capped. The wrapper
    # supplies its ONE global order/cap over mutually exclusive transaction
    # branches; each complete eligible group still contributes its first26.
    if outer_bound:
        return result.order_by(*sort_key(group_page.c)).limit(26)
    return result
