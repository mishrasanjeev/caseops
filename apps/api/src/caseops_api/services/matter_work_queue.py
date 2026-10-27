"""Current open Matter tasks with complete, actor-scoped keyset pages.

Team means OTHER active people sharing an active company team. Team ownership
never confers Matter access. Policy is applied before ordering/LIMIT; no owner
directory, lazy per-row query, portfolio hydration or cross-request team cache.
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, date, datetime

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import Date, and_, column, exists, func, or_, select, tuple_, union_all
from sqlalchemy.orm import aliased

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    MatterTask,
    MatterTaskQueueDirty,
    TeamMembership,
    User,
)
from caseops_api.db.statement_clock import StatementUtc
from caseops_api.schemas.matter_work_queue import (
    MatterWorkQueuePage,
    WorkQueueMatter,
    WorkQueueTask,
)
from caseops_api.services.record_access_policy import active_actor_team_ids, visible_matters_filter

CURSOR_TTL_SECONDS = 3600
_FIELDS = {
    "v",
    "company",
    "member",
    "user",
    "ownership",
    "dates",
    "from",
    "to",
    "limit",
    "id",
    "due",
    "created",
    "iat",
    "exp",
}


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _problem(status, code, message):
    raise HTTPException(status, detail={"code": code, "message": message})


def _day(value):
    if value is None:
        return None
    if type(value) is date:
        return value
    try:
        parsed = date.fromisoformat(value)
        if not isinstance(value, str) or parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        _problem(422, "work_queue_date_invalid", "Use a calendar date in YYYY-MM-DD format.")


def _filters(ownership, dates, limit, due_from, due_to):
    if ownership not in {"mine", "team", "unassigned"} or dates not in {"all", "dated", "undated"}:
        _problem(422, "work_queue_filter_invalid", "Choose a supported ownership and date view.")
    if type(limit) is not int or not 1 <= limit <= 25:
        _problem(422, "work_queue_limit_invalid", "Work queue limits are between 1 and 25.")
    lower, upper = _day(due_from), _day(due_to)
    if ((lower is not None or upper is not None) and dates != "dated") or (
        lower is not None and upper is not None and lower > upper
    ):
        _problem(
            422, "work_queue_date_range_invalid", "Use an ordered date range in the dated view."
        )
    return lower, upper


def _cipher():
    key = hmac.new(
        get_settings().auth_secret.encode(), b"caseops-matter-work-queue-cursor-v1", hashlib.sha256
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _scope(context, ownership, dates, limit, lower, upper):
    return {
        "v": 1,
        "company": context.company.id,
        "member": context.membership.id,
        "user": context.user.id,
        "ownership": ownership,
        "dates": dates,
        "limit": limit,
        "from": lower.isoformat() if lower else None,
        "to": upper.isoformat() if upper else None,
    }


def _record_id(value):
    # The canonical storage/API key is String(36), not a UUID-only contract.
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 36
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise ValueError("Invalid bounded work record identity.")
    return value


def encode_work_cursor(context, ownership, dates, limit, lower, upper, row, *, now=None):
    issued = int(_utc(now or datetime.now(UTC)).timestamp())
    body = {
        **_scope(context, ownership, dates, limit, lower, upper),
        "id": _record_id(row["id"]),
        "due": row["due_on"].isoformat() if row["due_on"] else None,
        "created": _utc(row["created_at"]).isoformat(),
        "iat": issued,
        "exp": issued + CURSOR_TTL_SECONDS,
    }
    return (
        _cipher()
        .encrypt_at_time(json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), issued)
        .decode("ascii")
    )


def decode_work_cursor(value, context, ownership, dates, limit, lower, upper, *, now=None):
    """This clock is cursor-local; authentication time is never patched."""
    stamp = _utc(now or datetime.now(UTC)).timestamp()
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 4000:
            raise ValueError
        body = json.loads(
            _cipher().decrypt_at_time(value.encode("ascii"), CURSOR_TTL_SECONDS, int(stamp))
        )
        if not isinstance(body, dict) or set(body) != _FIELDS:
            raise ValueError
        if any(
            body[k] != v for k, v in _scope(context, ownership, dates, limit, lower, upper).items()
        ):
            raise ValueError
        if any(type(body[k]) is not int for k in ("v", "limit", "iat", "exp")):
            raise ValueError
        if (
            body["exp"] - body["iat"] != CURSOR_TTL_SECONDS
            or not body["iat"] <= stamp < body["exp"]
        ):
            raise ValueError
        _record_id(body["id"])
        due = None if body["due"] is None else date.fromisoformat(body["due"])
        if due is not None and due.isoformat() != body["due"]:
            raise ValueError
        created = datetime.fromisoformat(body["created"])
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError
        return {"id": body["id"], "due_on": due, "created_at": _utc(created)}
    except (InvalidToken, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        _problem(
            400, "work_queue_cursor_invalid", "The work queue continuation is invalid or expired."
        )


def _current_actor(context):
    """Fresh SQL facts must agree with the role used to compose the ACL."""
    actor = aliased(CompanyMembership, name="queue_actor")
    actor_user = aliased(User, name="queue_actor_user")
    return exists(
        select(actor.id)
        .join(actor_user, actor_user.id == actor.user_id)
        .join(Company, Company.id == actor.company_id)
        .where(
            actor.id == context.membership.id,
            actor.company_id == context.company.id,
            actor.user_id == context.user.id,
            actor.role == context.membership.role,
            actor.is_active.is_(True),
            actor_user.is_active.is_(True),
            Company.is_active.is_(True),
        )
    )


def _require_current_actor(session, context):
    if not session.scalar(select(_current_actor(context))):
        _problem(
            403, "work_queue_authority_changed", "Workspace access changed. Reload your account."
        )


def logical_work_queue_statement(
    session,
    *,
    context,
    ownership,
    dates,
    lower=None,
    upper=None,
    _actor_fence=None,
    _owner_teams=None,
):
    """Typed scalar query: all tenant, owner, lifecycle and ACL filters precede LIMIT."""
    if ownership == "mine":
        owner = MatterTask.owner_membership_id == context.membership.id
    elif ownership == "unassigned":
        owner = MatterTask.owner_membership_id.is_(None)
    elif ownership == "team":
        teams = (
            active_actor_team_ids(
                company_id=context.company.id, membership_id=context.membership.id
            )
            if _owner_teams is None
            else _owner_teams
        )
        peer = aliased(CompanyMembership, name="queue_owner")
        peer_user = aliased(User, name="queue_owner_user")
        shared = aliased(TeamMembership, name="queue_owner_team")
        owner = and_(
            MatterTask.owner_membership_id != context.membership.id,
            exists(
                select(peer.id)
                .join(peer_user, peer_user.id == peer.user_id)
                .join(shared, shared.membership_id == peer.id)
                .where(
                    peer.id == MatterTask.owner_membership_id,
                    peer.company_id == context.company.id,
                    peer.is_active.is_(True),
                    peer_user.is_active.is_(True),
                    shared.team_id.in_(select(teams.c.team_id)),
                )
            ),
        )
    else:
        raise ValueError("Unsupported work ownership.")
    statement = (
        select(
            MatterTask.id,
            MatterTask.title,
            MatterTask.status,
            MatterTask.priority,
            MatterTask.due_on,
            MatterTask.owner_membership_id,
            MatterTask.created_at,
            MatterTask.updated_at,
            Matter.id.label("matter_id"),
            Matter.title.label("matter_title"),
            Matter.matter_code,
            Matter.status.label("matter_status"),
            Matter.is_active,
            Matter.lifecycle_version,
        )
        .join(
            Matter,
            and_(Matter.id == MatterTask.matter_id, Matter.company_id == MatterTask.company_id),
        )
        .where(
            _current_actor(context) if _actor_fence is None else _actor_fence,
            MatterTask.company_id == context.company.id,
            MatterTask.ip_docket_id.is_(None),
            Matter.company_id == context.company.id,
            Matter.is_active.is_(True),
            Matter.status.in_(("intake", "active", "on_hold")),
            MatterTask.status.in_(("todo", "in_progress", "blocked")),
            MatterTask.cancelled_by_matter_disposal.is_(False),
            MatterTask.neutralized_at.is_(None),
            MatterTask.neutralized_by_ip_lifecycle_event_id.is_(None),
            MatterTask.neutralized_by_ip_lifecycle_version.is_(None),
            visible_matters_filter(session, context=context, statement_time=StatementUtc()),
            owner,
        )
    )
    if dates == "dated":
        statement = statement.where(MatterTask.due_on.is_not(None))
    elif dates == "undated":
        statement = statement.where(MatterTask.due_on.is_(None))
    elif dates != "all":
        raise ValueError("Unsupported work date view.")
    if lower is not None:
        statement = statement.where(MatterTask.due_on >= lower)
    if upper is not None:
        statement = statement.where(MatterTask.due_on <= upper)
    return statement


def work_queue_statement(
    session, *, context, ownership, dates, lower=None, upper=None, anchor=None
):
    """Complete ordered page. Callers must not append MatterTask expressions.

    Cursor predicates enter each group before its bound. The authoritative
    anchor recheck deliberately uses logical_work_queue_statement instead.
    SQLite keeps the original scalar source query and the same response order.
    """
    postgres = session.get_bind().dialect.name == "postgresql"
    actor_fence = owner_teams = None
    if postgres:
        # These are typed SQL facts shared only inside THIS statement. Retained
        # Selects still re-evaluate current actor/team rows on every execution.
        actor = (
            select(_current_actor(context).label("allowed"))
            .cte("queue_authorized_actor")
            .prefix_with("MATERIALIZED", dialect="postgresql")
        )
        actor_fence = select(actor.c.allowed).scalar_subquery().is_(True)
        if ownership == "team":
            owner_teams = active_actor_team_ids(
                company_id=context.company.id, membership_id=context.membership.id
            )
    logical = logical_work_queue_statement(
        session,
        context=context,
        ownership=ownership,
        dates=dates,
        lower=lower,
        upper=upper,
        _actor_fence=actor_fence,
        _owner_teams=owner_teams,
    )
    if anchor is not None:
        logical = _after(logical, anchor)
    logical = logical.order_by(
        MatterTask.due_on.is_(None), MatterTask.due_on, MatterTask.created_at, MatterTask.id
    ).limit(26)
    if not postgres:
        return logical
    from caseops_api.services.task_queue_pages import statement

    # The predicate is SQL, not a construction-time Python check: the SAME
    # retained Select must observe later own writes/flushes before commit.
    dirty = exists(
        select(MatterTaskQueueDirty.transaction_id).where(
            MatterTaskQueueDirty.transaction_id == func.txid_current_if_assigned()
        )
    )
    committed = statement(
        session,
        context=context,
        ownership=ownership,
        dates=dates,
        lower=lower,
        upper=upper,
        anchor=anchor,
        outer_bound=False,
        _actor_fence=actor_fence,
        _owner_teams=owner_teams,
    )
    source = logical.where(dirty).subquery("queue_own_write_page")
    combined = union_all(
        committed.where(~dirty),
        select(*[source.c[item.name] for item in committed.selected_columns]),
    )
    # Compound ORDER BY uses its reviewed RESULT columns, not an expression
    # over another subquery. DateASCNULLSLAST is the same dated/undated order;
    # created_at/id remain the exact unique tie-breaker before the global bound.
    return combined.order_by(
        column("due_on", Date).asc().nulls_last(),
        column("created_at").asc(),
        column("id").asc(),
    ).limit(26)


def _after(statement, anchor):
    tie = tuple_(MatterTask.created_at, MatterTask.id) > (anchor["created_at"], anchor["id"])
    if anchor["due_on"] is None:
        return statement.where(MatterTask.due_on.is_(None), tie)
    return statement.where(
        or_(
            MatterTask.due_on.is_(None),
            MatterTask.due_on > anchor["due_on"],
            and_(MatterTask.due_on == anchor["due_on"], tie),
        )
    )


def list_matter_work_queue(
    session,
    *,
    context,
    ownership="mine",
    dates="all",
    limit=25,
    cursor=None,
    due_from=None,
    due_to=None,
):
    lower, upper = _filters(ownership, dates, limit, due_from, due_to)
    _require_current_actor(session, context)
    anchor = None
    if cursor is not None:
        anchor = decode_work_cursor(cursor, context, ownership, dates, limit, lower, upper)
        current = (
            session.execute(
                logical_work_queue_statement(
                    session,
                    context=context,
                    ownership=ownership,
                    dates=dates,
                    lower=lower,
                    upper=upper,
                )
                .where(MatterTask.id == anchor["id"])
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if (
            current is None
            or current["due_on"] != anchor["due_on"]
            or _utc(current["created_at"]) != anchor["created_at"]
        ):
            _require_current_actor(session, context)
            _problem(
                409, "work_queue_cursor_stale", "Work or access changed. Reload the work queue."
            )
    statement = work_queue_statement(
        session,
        context=context,
        ownership=ownership,
        dates=dates,
        lower=lower,
        upper=upper,
        anchor=anchor,
    )
    rows = list(session.execute(statement.limit(limit + 1)).mappings())
    # Do not serialize a role-filtered empty page as lack of work after a race.
    _require_current_actor(session, context)
    kept = rows[:limit]
    return MatterWorkQueuePage(
        ownership=ownership,
        dates=dates,
        due_from=lower,
        due_to=upper,
        limit=limit,
        items=[
            WorkQueueTask(
                id=row["id"],
                title=row["title"],
                status=row["status"],
                priority=row["priority"],
                due_on=row["due_on"],
                owner_membership_id=row["owner_membership_id"],
                created_at=_utc(row["created_at"]),
                updated_at=_utc(row["updated_at"]),
                matter=WorkQueueMatter(
                    id=row["matter_id"],
                    title=row["matter_title"],
                    matter_code=row["matter_code"],
                    status=row["matter_status"],
                    is_active=row["is_active"],
                    lifecycle_version=row["lifecycle_version"],
                ),
            )
            for row in kept
        ],
        next_cursor=encode_work_cursor(context, ownership, dates, limit, lower, upper, kept[-1])
        if len(rows) > limit
        else None,
    )
