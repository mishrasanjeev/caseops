"""Read-only actor and UTC facts shared by logical and packed Matter queues."""

from datetime import UTC

from sqlalchemy import exists, select
from sqlalchemy.orm import aliased

from caseops_api.db.models import Company, CompanyMembership, User

__all__ = ["_current_actor", "_utc"]


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
