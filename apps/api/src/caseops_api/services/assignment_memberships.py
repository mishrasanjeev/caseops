from __future__ import annotations

from collections.abc import Iterable
from time import monotonic, sleep

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.attributes import set_committed_value

from caseops_api.db.models import Company, CompanyMembership, CustomRole, User
from caseops_api.services.capabilities import membership_has_capability

_ASSIGNMENT_FENCE_TRANSACTION_ATTR = "_caseops_assignment_fence_transaction"


def lock_company_memberships_for_assignment(
    session: Session,
    *,
    company_id: str,
    membership_ids: Iterable[str | None],
    no_key_update: bool = False,
    nowait: bool = False,
) -> dict[str, CompanyMembership]:
    """Lock assignment participants in one stable, tenant-scoped order.

    Assignment writers must acquire this fence before any Matter, docket,
    deadline, or coverage lock.  The separate user refresh deliberately avoids
    a joined eager-load in PostgreSQL's ``FOR UPDATE`` statement.
    OAuth opts into NO KEY UPDATE so a tenant writer can finish audit FK
    checks while holding Company. Existing mutation lock strength is unchanged.
    """

    requested_ids = sorted({membership_id for membership_id in membership_ids if membership_id})
    if not requested_ids:
        return {}

    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.id.in_(requested_ids),
            )
            .order_by(CompanyMembership.id)
            .with_for_update(of=CompanyMembership, key_share=no_key_update, nowait=nowait)
            .execution_options(populate_existing=True)
        ).all()
    )
    user_ids = sorted({membership.user_id for membership in memberships})
    users = (
        list(
            session.scalars(
                select(User)
                .where(User.id.in_(user_ids))
                .order_by(User.id)
                .with_for_update(of=User, key_share=no_key_update, nowait=nowait)
                .execution_options(populate_existing=True)
            ).all()
        )
        if user_ids
        else []
    )
    users_by_id = {user.id: user for user in users}
    if set(users_by_id) != set(user_ids):
        raise RuntimeError("Company membership user is missing.")
    transaction = session.get_transaction()
    if transaction is None:
        raise RuntimeError("Membership assignment fence requires an active transaction.")
    for membership in memberships:
        # The relationship may have been loaded before this transaction won
        # the User lock. Pin it to the authoritative refreshed instance so
        # every caller's active check reads the fenced row.
        set_committed_value(membership, "user", users_by_id[membership.user_id])
        setattr(membership, _ASSIGNMENT_FENCE_TRANSACTION_ATTR, transaction)
    return {membership.id: membership for membership in memberships}


def lock_company_memberships_for_oauth(
    session: Session, *, company_id: str, membership_ids: Iterable[str | None],
) -> tuple[Company | None, dict[str, CompanyMembership]]:
    """Acquire only OAuth authority locks, without cycling against either writer order.

    Team changes take Company first; Matter mutations take Membership first.
    Password changes may take User first. Every authority row is NOWAIT:
    drop ALL locks before bounded backoff, then reacquire fresh authority.
    No provider I/O or staged write belongs inside this retry boundary.
    """
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("OAuth authority acquisition cannot retry staged writes.")
    ids = tuple(membership_ids)
    postgres = session.get_bind().dialect.name == "postgresql"
    deadline = monotonic() + 5
    previous_timeout = session.scalar(text("SHOW lock_timeout")) if postgres else None

    def set_timeout() -> None:
        if postgres:
            session.execute(
                text("SELECT set_config('lock_timeout', :timeout, true)"),
                {"timeout": f"{max(1, int((deadline - monotonic()) * 1000))}ms"},
            )

    while True:
        try:
            set_timeout()
            company = session.scalar(
                select(Company).where(Company.id == company_id)
                .with_for_update(of=Company, key_share=True, nowait=postgres)
                .execution_options(populate_existing=True)
            )
            actors = lock_company_memberships_for_assignment(
                session, company_id=company_id, membership_ids=ids,
                no_key_update=True, nowait=postgres,
            )
            if postgres:
                session.execute(
                    text("SELECT set_config('lock_timeout', :timeout, true)"),
                    {"timeout": previous_timeout},
                )
            return company, actors
        except DBAPIError as exc:
            if not postgres or getattr(exc.orig, "sqlstate", None) != "55P03":
                raise
            session.rollback()
            if monotonic() >= deadline:
                break
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(0.025, remaining))
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "oauth_authority_busy",
            "message": (
                "Workspace access is changing. Check the connection and start Connect again."
            ),
        },
    )


def require_locked_membership_capability(
    session: Session,
    membership: CompanyMembership,
    capability: str,
) -> CompanyMembership:
    """Require one capability on a Membership/User fenced in this transaction.

    Custom-role mutation deliberately keeps its existing CustomRole -> assigned
    Membership update order.  The assigned Membership update is atomic with the
    role change, so this helper needs no CustomRole lock: a writer holding the
    Membership fence serializes before an uncommitted role change, while a role
    change that committed first is visible after ``populate_existing`` above.
    """

    transaction = session.get_transaction()
    user = membership.__dict__.get("user")
    if (
        transaction is None
        or object_session(membership) is not session
        or getattr(membership, _ASSIGNMENT_FENCE_TRANSACTION_ATTR, None)
        is not transaction
        or not isinstance(user, User)
        or user.id != membership.user_id
        or object_session(user) is not session
    ):
        raise RuntimeError(
            "Capability checks for mutations require a Membership/User fence."
        )

    # A Session may have resolved this relationship before the Membership fence,
    # or the fenced row may now reference another role. Refresh the exact current
    # target with a plain MVCC read so neither case can be hidden by the identity
    # map. Never acquire a CustomRole row lock here: assigned Membership
    # invalidation is the serialization point shared with update/revoke.
    with session.no_autoflush:
        custom_role = (
            session.scalar(
                select(CustomRole)
                .where(
                    CustomRole.id == membership.custom_role_id,
                    CustomRole.company_id == membership.company_id,
                )
                .execution_options(populate_existing=True)
            )
            if membership.custom_role_id
            else None
        )
        set_committed_value(membership, "custom_role", custom_role)
        allowed = (
            membership.is_active
            and user.is_active
            and membership_has_capability(session, membership, capability)
        )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Capability {capability!r} is required.",
        )
    return membership


def lock_user_for_membership_deactivation(
    session: Session,
    *,
    membership: CompanyMembership,
) -> User:
    """Return the User already fenced by the membership-first helper.

    Every production caller first invokes
    :func:`lock_company_memberships_for_assignment`, which now locks and pins
    the corresponding User rows in stable order. Avoid a duplicate lock query
    here so the global protocol has one auditable acquisition point.
    """

    del session  # retained for the existing caller contract
    user = membership.__dict__.get("user")
    if not isinstance(user, User) or user.id != membership.user_id:
        raise RuntimeError("Company membership user was not fenced.")
    return user


def has_other_active_company_memberships(
    session: Session,
    *,
    membership: CompanyMembership,
) -> bool:
    """Return whether the shared User retains another live tenant login."""

    return (
        session.scalar(
            select(CompanyMembership.id)
            .join(Company, Company.id == CompanyMembership.company_id)
            .where(
                CompanyMembership.user_id == membership.user_id,
                CompanyMembership.id != membership.id,
                CompanyMembership.is_active.is_(True),
                Company.is_active.is_(True),
            )
            .limit(1)
        )
        is not None
    )
