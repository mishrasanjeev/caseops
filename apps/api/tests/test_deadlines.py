"""matter_deadlines CRUD (BG-041, Sprint 13 partial)."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    Matter,
    MatterDeadlineStatus,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.deadlines import (
    create_deadline,
    list_deadlines,
    transition_deadline,
)
from caseops_api.services.identity import SessionContext
from tests.test_auth_company import bootstrap_company


def _context(session) -> tuple[SessionContext, Matter]:
    """Build a SessionContext for the first tenant + a fresh matter."""
    company = session.scalar(select(Company))
    membership = session.scalar(
        select(CompanyMembership).where(CompanyMembership.company_id == company.id)
    )
    user = session.get(User, membership.user_id)
    ctx = SessionContext(company=company, user=user, membership=membership)
    matter = Matter(
        company_id=company.id,
        matter_code="DLN-001",
        title="Deadline test matter",
        practice_area="civil",
        forum_level="high_court",
        status="intake",
    )
    session.add(matter)
    session.flush()
    return ctx, matter


@pytest.fixture
def seeded(client: TestClient):
    bootstrap_company(client)
    Session = get_session_factory()
    with Session() as session:
        ctx, matter = _context(session)
        session.commit()
        matter_id = matter.id
    return matter_id


def test_create_deadline_rejects_unknown_source(seeded) -> None:
    matter_id = seeded
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == company.id)
        )
        ctx = SessionContext(
            company=company,
            user=session.get(User, membership.user_id),
            membership=membership,
        )
        with pytest.raises(Exception) as exc:
            create_deadline(
                session,
                context=ctx,
                matter_id=matter_id,
                source="gibberish",
                kind="x",
                title="no source",
                due_on=date(2026, 5, 1),
            )
        assert "source" in str(exc.value).lower()


def test_create_deadline_happy_path_and_list(seeded) -> None:
    matter_id = seeded
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == company.id)
        )
        ctx = SessionContext(
            company=company,
            user=session.get(User, membership.user_id),
            membership=membership,
        )
        d = create_deadline(
            session,
            context=ctx,
            matter_id=matter_id,
            source="hearing",
            kind="reply_due",
            title="Reply to application",
            due_on=date(2026, 5, 12),
            notes="3 days after listing",
        )
        assert d.status == MatterDeadlineStatus.OPEN
        assert d.source == "hearing"
        assert d.kind == "reply_due"

        rows = list_deadlines(session, context=ctx, matter_id=matter_id)
        assert [r.id for r in rows] == [d.id]

        # Audit row landed.
        audits = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "deadline.created")
            )
        )
        assert any(a.target_id == d.id for a in audits)


def test_transition_deadline_to_done_and_reopen(seeded) -> None:
    matter_id = seeded
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == company.id)
        )
        ctx = SessionContext(
            company=company,
            user=session.get(User, membership.user_id),
            membership=membership,
        )
        d = create_deadline(
            session,
            context=ctx,
            matter_id=matter_id,
            source="draft",
            kind="reply_due",
            title="Draft reply",
            due_on=date(2026, 5, 15),
        )
        done = transition_deadline(
            session, context=ctx, deadline_id=d.id, action="complete"
        )
        assert done.status == MatterDeadlineStatus.DONE
        assert done.completed_at is not None

        # List excludes completed by default.
        open_only = list_deadlines(session, context=ctx, matter_id=matter_id)
        assert all(x.id != d.id for x in open_only)

        reopened = transition_deadline(
            session, context=ctx, deadline_id=d.id, action="reopen"
        )
        assert reopened.status == MatterDeadlineStatus.OPEN
        assert reopened.completed_at is None


def test_list_include_done_shows_everything(seeded) -> None:
    matter_id = seeded
    Session = get_session_factory()
    with Session() as session:
        company = session.scalar(select(Company))
        membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == company.id)
        )
        ctx = SessionContext(
            company=company,
            user=session.get(User, membership.user_id),
            membership=membership,
        )
        alive = create_deadline(
            session, context=ctx, matter_id=matter_id,
            source="custom", kind="x", title="Alive", due_on=date(2026, 6, 1),
        )
        dead = create_deadline(
            session, context=ctx, matter_id=matter_id,
            source="custom", kind="y", title="Dead", due_on=date(2026, 6, 2),
        )
        transition_deadline(session, context=ctx, deadline_id=dead.id, action="cancel")

        all_rows = list_deadlines(
            session, context=ctx, matter_id=matter_id, include_done=True
        )
        ids = {r.id for r in all_rows}
        assert alive.id in ids and dead.id in ids


def test_cross_tenant_deadline_is_invisible(client: TestClient) -> None:
    # Tenant A creates a matter + deadline; tenant B cannot load it.
    from tests.test_authority_annotations import _bootstrap

    _bootstrap(client, slug="dln-a", email="a-dln@example.com")
    _bootstrap(client, slug="dln-b", email="b-dln@example.com")

    Session = get_session_factory()
    with Session() as session:
        companies = list(
            session.scalars(select(Company).order_by(Company.created_at))
        )
        a, b = companies[-2], companies[-1]
        a_mem = session.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == a.id)
        )
        b_mem = session.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == b.id)
        )
        ctx_a = SessionContext(
            company=a, user=session.get(User, a_mem.user_id), membership=a_mem
        )
        ctx_b = SessionContext(
            company=b, user=session.get(User, b_mem.user_id), membership=b_mem
        )
        m_a = Matter(
            company_id=a.id,
            matter_code="CROSS-A",
            title="A's matter",
            practice_area="civil",
            forum_level="high_court",
            status="intake",
        )
        session.add(m_a)
        session.flush()
        d = create_deadline(
            session, context=ctx_a, matter_id=m_a.id,
            source="custom", kind="x", title="A's deadline", due_on=date(2026, 7, 1),
        )
        # B cannot list deadlines on A's matter — _load_matter raises 404.
        with pytest.raises(Exception) as exc:
            list_deadlines(session, context=ctx_b, matter_id=m_a.id)
        assert "matter not found" in str(exc.value).lower()
        # Nor can B transition A's deadline.
        with pytest.raises(Exception) as exc2:
            transition_deadline(session, context=ctx_b, deadline_id=d.id, action="complete")
        assert "matter not found" in str(exc2.value).lower()
