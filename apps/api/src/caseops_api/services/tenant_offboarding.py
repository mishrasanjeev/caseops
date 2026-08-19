"""Tenant offboarding revocation plan (DATA-GOV-12).

The requirement: offboarding "revokes users/sessions/connectors/portal
links/provider callbacks, stops polling/reminders/reports, resolves ownership,
exports as approved, preserves holds and produces a signed completion/exception
manifest".

This builds the DRY-RUN half - what offboarding WOULD do - which is the part
that can exist before an execute path. ``tenant_offboarding`` is already a
registered data-operation type, so the plan travels in the same manifest as
export exclusions and the purge dependency plan.

Two properties matter more than the counts.

**Holds are preserved, never revoked.** Offboarding a tenant does not lift a
court's preservation order; if anything it makes preservation more important,
because nobody is left to notice. So legal holds appear in the plan as a
PRESERVED category, and a caller that treats every category as "to be removed"
would be visibly wrong rather than quietly destructive.

**A category that cannot be enumerated says so.** Several revocation targets
have no tenant-scoped store to count - sessions are stateless, some portal and
webhook tables are scoped through a parent rather than by ``company_id``. A
plan that silently omitted them would read as "nothing to revoke there", which
is the reassuring-zero this programme keeps having to design against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import Base, LegalHold, LegalHoldStatus

CategoryDisposition = Literal["revoke", "stop", "preserve", "unenumerable"]


@dataclass(frozen=True)
class OffboardingCategory:
    category: str
    disposition: CategoryDisposition
    record_count: int | None
    detail: str


# Tenant-scoped tables, verified to carry company_id. Anything without it is
# reported as unenumerable rather than counted through a guessed join, because
# a wrong count here understates what offboarding has to touch.
_REVOKE_TABLES: tuple[tuple[str, str, str], ...] = (
    ("users_and_memberships", "company_memberships", "firm logins and role assignments"),
    ("portal_users", "portal_users", "external client portal identities"),
    ("provider_callbacks", "mailbox_webhook_events", "inbound provider callback records"),
)
_STOP_TABLES: tuple[tuple[str, str, str], ...] = (
    ("polling", "tracked_case_bookmarks", "court-tracking poll subscriptions"),
    ("reminders", "hearing_reminders", "scheduled hearing reminders"),
    ("reports", "authority_research_reports", "saved research reports"),
)
# Named by the requirement but with no tenant-scoped store to count.
_UNENUMERABLE: tuple[tuple[str, str], ...] = (
    (
        "sessions",
        "sessions are stateless bearer tokens with no server-side store; "
        "revocation is by secret rotation, not by row",
    ),
    (
        "portal_links",
        "portal_magic_links and matter_portal_grants are scoped through their "
        "parent matter, not by company_id",
    ),
    (
        "connectors",
        "connector credentials live in the secret store, not in a tenant-scoped table",
    ),
)


def _count(session: Session, table_name: str, company_id: str) -> int | None:
    table = Base.metadata.tables.get(table_name)
    if table is None or "company_id" not in table.columns:
        return None
    statement = select(func.count()).select_from(table).where(
        table.c.company_id == company_id
    )
    return int(session.scalar(statement) or 0)


def build_offboarding_plan(
    session: Session, *, company_id: str
) -> tuple[OffboardingCategory, ...]:
    """Describe what offboarding this tenant would revoke, stop and preserve."""
    categories: list[OffboardingCategory] = []

    for category, table_name, detail in _REVOKE_TABLES:
        categories.append(
            OffboardingCategory(
                category=category,
                disposition="revoke",
                record_count=_count(session, table_name, company_id),
                detail=detail,
            )
        )
    for category, table_name, detail in _STOP_TABLES:
        categories.append(
            OffboardingCategory(
                category=category,
                disposition="stop",
                record_count=_count(session, table_name, company_id),
                detail=detail,
            )
        )

    # Holds are the exception that gives the plan its shape. An offboarded
    # tenant under a preservation order still has one.
    active_holds = int(
        session.scalar(
            select(func.count())
            .select_from(LegalHold)
            .where(
                LegalHold.company_id == company_id,
                LegalHold.status == LegalHoldStatus.ACTIVE,
            )
        )
        or 0
    )
    categories.append(
        OffboardingCategory(
            category="legal_holds",
            disposition="preserve",
            record_count=active_holds,
            detail=(
                "active legal holds survive offboarding; a departing tenant does "
                "not lift a preservation order"
            ),
        )
    )

    for category, detail in _UNENUMERABLE:
        categories.append(
            OffboardingCategory(
                category=category,
                disposition="unenumerable",
                record_count=None,
                detail=detail,
            )
        )
    return tuple(categories)


def offboarding_plan_is_blocked(categories: tuple[OffboardingCategory, ...]) -> bool:
    """Whether an active hold blocks completing this offboarding.

    Execution is not implemented, but the answer belongs in the dry run: an
    operator planning a tenant exit needs to know before scheduling it that a
    preservation order is outstanding.
    """
    return any(
        category.disposition == "preserve" and (category.record_count or 0) > 0
        for category in categories
    )
