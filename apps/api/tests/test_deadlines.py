"""matter_deadlines CRUD (BG-041, Sprint 13 partial)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    EthicalWall,
    IpDocketRecord,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterDeadlineStatus,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.matters import MatterDeadlineUpdateRequest
from caseops_api.services.deadlines import (
    create_deadline,
    list_deadlines,
    transition_deadline,
    update_deadline,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company


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
        assert "not found" in str(exc2.value).lower()


def test_linked_ip_generic_deadline_assignment_requires_durable_matter_access(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])

    candidate_ids: dict[str, str] = {}
    for access_case in ("future_wall", "expiring_grant"):
        created = client.post(
            "/api/companies/current/users",
            headers=headers,
            json={
                "full_name": f"Deadline {access_case}",
                "email": f"deadline-{access_case}@example.com",
                "password": "DeadlineFence123!",
                "role": "member",
            },
        )
        assert created.status_code == 200, created.text
        candidate_ids[access_case] = str(created.json()["membership_id"])

    factory = get_session_factory()
    with factory() as session:
        owner = session.get(CompanyMembership, owner_membership_id)
        assert owner is not None
        matter = Matter(
            company_id=company_id,
            assignee_membership_id=owner_membership_id,
            matter_code="DLN-IP-STABLE-ACCESS",
            title="Linked IP deadline stable access",
            practice_area="Intellectual Property",
            forum_level="high_court",
            status="active",
            restricted_access=True,
        )
        session.add(matter)
        session.flush()
        docket = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="Stable access deadline docket",
            primary_identifier="TM-DLN-STABLE-ACCESS",
            status="active",
            is_active=True,
            created_by_membership_id=owner_membership_id,
        )
        existing = MatterDeadline(
            company_id=company_id,
            matter_id=matter.id,
            source="custom",
            kind="response",
            title="Existing owner deadline",
            due_on=date(2026, 12, 1),
            status=MatterDeadlineStatus.OPEN,
            assignee_membership_id=owner_membership_id,
            created_by_membership_id=owner_membership_id,
        )
        session.add_all(
            [
                docket,
                existing,
                MatterAccessGrant(
                    company_id=company_id,
                    matter_id=matter.id,
                    membership_id=candidate_ids["future_wall"],
                    access_level="member",
                    reason="Unbounded access before the scheduled wall.",
                    granted_by_membership_id=owner_membership_id,
                ),
                MatterAccessGrant(
                    company_id=company_id,
                    matter_id=matter.id,
                    membership_id=candidate_ids["expiring_grant"],
                    access_level="member",
                    reason="Current access expires while responsibility remains live.",
                    granted_by_membership_id=owner_membership_id,
                    expires_at=datetime.now(UTC) + timedelta(days=2),
                ),
                EthicalWall(
                    company_id=company_id,
                    matter_id=matter.id,
                    excluded_membership_id=candidate_ids["future_wall"],
                    reason="Scheduled conflict activation.",
                    created_by_membership_id=owner_membership_id,
                    effective_from=datetime.now(UTC) + timedelta(days=1),
                ),
            ]
        )
        session.commit()
        matter_id = matter.id
        existing_id = existing.id

    with factory() as session:
        owner = session.get(CompanyMembership, owner_membership_id)
        assert owner is not None
        context = SessionContext(
            company=owner.company,
            user=owner.user,
            membership=owner,
        )
        with pytest.raises(HTTPException) as create_error:
            create_deadline(
                session,
                context=context,
                matter_id=matter_id,
                source="custom",
                kind="response",
                title="Future-wall assignment must not persist",
                due_on=date(2026, 12, 2),
                assignee_membership_id=candidate_ids["future_wall"],
            )
        assert create_error.value.status_code == 400
        assert "durable access" in str(create_error.value.detail)
        assert session.scalar(
            select(MatterDeadline.id).where(
                MatterDeadline.matter_id == matter_id,
                MatterDeadline.title == "Future-wall assignment must not persist",
            )
        ) is None

    with factory() as session:
        owner = session.get(CompanyMembership, owner_membership_id)
        assert owner is not None
        context = SessionContext(
            company=owner.company,
            user=owner.user,
            membership=owner,
        )
        with pytest.raises(HTTPException) as update_error:
            update_deadline(
                session,
                context=context,
                matter_id=matter_id,
                deadline_id=existing_id,
                payload=MatterDeadlineUpdateRequest(
                    assignee_membership_id=candidate_ids["expiring_grant"]
                ),
            )
        assert update_error.value.status_code == 400
        assert "durable access" in str(update_error.value.detail)
        session.rollback()
        persisted = session.get(MatterDeadline, existing_id)
        assert persisted is not None
        assert persisted.assignee_membership_id == owner_membership_id


@pytest.mark.parametrize("access_case", ["restricted_sibling", "future_ip_wall"])
def test_generic_deadline_assignment_requires_every_linked_ip_docket_access(
    client: TestClient,
    access_case: str,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    company_id = str(bootstrap["company"]["id"])
    owner_id = str(bootstrap["membership"]["id"])
    created_member = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": f"Every docket {access_case}",
            "email": f"every-docket-{access_case}@example.com",
            "password": "EveryDocketFence123!",
            "role": "member",
        },
    )
    assert created_member.status_code == 200, created_member.text
    candidate_id = str(created_member.json()["membership_id"])

    factory = get_session_factory()
    with factory() as session:
        matter = Matter(
            company_id=company_id,
            assignee_membership_id=owner_id,
            matter_code=f"DLN-EVERY-IP-{access_case}",
            title="Generic deadline across every linked IP docket",
            practice_area="Intellectual Property",
            forum_level="high_court",
            status="active",
        )
        session.add(matter)
        session.flush()
        first = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="First linked deadline docket",
            primary_identifier=f"DLN-EVERY-FIRST-{access_case}",
            status="active",
            is_active=True,
            restricted=False,
            created_by_membership_id=owner_id,
        )
        second = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="Second linked deadline docket",
            primary_identifier=f"DLN-EVERY-SECOND-{access_case}",
            status="active",
            is_active=True,
            restricted=access_case == "restricted_sibling",
            created_by_membership_id=owner_id,
        )
        existing = MatterDeadline(
            company_id=company_id,
            matter_id=matter.id,
            source="custom",
            kind="response",
            title="Existing sibling-bound deadline",
            due_on=date(2026, 12, 8),
            status=MatterDeadlineStatus.OPEN,
            assignee_membership_id=owner_id,
            created_by_membership_id=owner_id,
        )
        session.add_all([first, second, existing])
        session.flush()
        if access_case == "future_ip_wall":
            session.add(
                EthicalWall(
                    company_id=company_id,
                    ip_docket_id=second.id,
                    excluded_membership_id=candidate_id,
                    reason="Scheduled docket wall must block durable assignment.",
                    created_by_membership_id=owner_id,
                    effective_from=datetime.now(UTC) + timedelta(days=1),
                )
            )
        session.commit()
        matter_id = matter.id
        existing_id = existing.id

    with factory() as session:
        owner = session.get(CompanyMembership, owner_id)
        assert owner is not None
        context = SessionContext(
            company=owner.company,
            user=owner.user,
            membership=owner,
        )
        with pytest.raises(HTTPException) as create_error:
            create_deadline(
                session,
                context=context,
                matter_id=matter_id,
                source="custom",
                kind="response",
                title="Must not bypass one inaccessible sibling",
                due_on=date(2026, 12, 9),
                assignee_membership_id=candidate_id,
            )
        assert create_error.value.status_code == 400
        assert "durable access" in str(create_error.value.detail)
        session.rollback()

    with factory() as session:
        owner = session.get(CompanyMembership, owner_id)
        assert owner is not None
        context = SessionContext(
            company=owner.company,
            user=owner.user,
            membership=owner,
        )
        with pytest.raises(HTTPException) as update_error:
            update_deadline(
                session,
                context=context,
                matter_id=matter_id,
                deadline_id=existing_id,
                payload=MatterDeadlineUpdateRequest(
                    assignee_membership_id=candidate_id
                ),
            )
        assert update_error.value.status_code == 400
        session.rollback()
        persisted = session.get(MatterDeadline, existing_id)
        assert persisted is not None
        assert persisted.assignee_membership_id == owner_id
        assert session.scalar(
            select(MatterDeadline.id).where(
                MatterDeadline.matter_id == matter_id,
                MatterDeadline.title == "Must not bypass one inaccessible sibling",
            )
        ) is None
