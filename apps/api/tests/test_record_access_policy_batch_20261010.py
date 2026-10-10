"""Live bounded recipient visibility uses the scalar Matter policy on both DBs."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    EthicalWall,
    Matter,
    MatterAccessGrant,
    Team,
    TeamMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.matter_access import can_access
from caseops_api.services.record_access_policy import visible_matter_membership_ids
from caseops_api.services.session_context import SessionContext
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def visibility_session(request):
    if request.param == "sqlite":
        request.getfixturevalue("client")
        factory = get_session_factory()
    else:
        engine = request.getfixturevalue("pg_engine")

        def factory():
            return Session(engine)
    with factory() as session:
        yield session


def _seed(session, *, scoped=False, restricted=False):
    company = Company(
        name="Visibility batch", slug=f"visibility-{uuid4()}", company_type="law_firm",
        tenant_key=str(uuid4()), team_scoping_enabled=scoped,
    )
    other = Company(
        name="Other visibility tenant", slug=f"visibility-other-{uuid4()}",
        company_type="law_firm", tenant_key=str(uuid4()),
    )
    session.add_all([company, other])
    session.flush()
    members = {}
    for name, role in (("owner", "owner"), ("member", "member"), ("assignee", "admin")):
        user = User(email=f"visibility-{uuid4()}@example.com", full_name=name,
                    password_hash="not-used", is_active=True)
        session.add(user)
        session.flush()
        member = CompanyMembership(company_id=company.id, user_id=user.id, role=role)
        session.add(member)
        session.flush()
        members[name] = member
    outsider_user = User(email=f"visibility-{uuid4()}@example.com", full_name="Other owner",
                         password_hash="not-used", is_active=True)
    session.add(outsider_user)
    session.flush()
    outsider = CompanyMembership(company_id=other.id, user_id=outsider_user.id, role="owner")
    session.add(outsider)
    team = Team(company_id=company.id, name="Matter team", slug=f"matter-{uuid4()}")
    second_team = Team(company_id=company.id, name="Recipient team", slug=f"recipient-{uuid4()}")
    session.add_all([team, second_team])
    session.flush()
    matter = Matter(
        company_id=company.id, title="Visibility source", matter_code=f"VIS-{uuid4()}",
        status="intake", practice_area="commercial", forum_level="high_court",
        restricted_access=restricted, team_id=team.id,
        assignee_membership_id=members["assignee"].id,
    )
    session.add(matter)
    session.commit()
    return company, matter, members, outsider, team, second_team


def _read_batch(session, company, matter, members, outsider):
    return visible_matter_membership_ids(
        session, company_id=company.id, matter_id=matter.id,
        membership_ids=[*(row.id for row in members.values()), outsider.id],
    )


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("restricted", [False, True])
@pytest.mark.parametrize("scenario", [
    "none", "matter_team", "grant", "revoked_grant", "expired_grant", "future_grant",
    "team_grant", "inactive_team_grant", "wall_over_grant", "team_wall", "expired_wall",
    "owner_wall", "assignee_wall",
])
def test_batch_matches_exact_policy_and_one_statement(
    visibility_session, scoped, restricted, scenario,
):
    session = visibility_session
    company, matter, members, outsider, team, recipient_team = _seed(
        session, scoped=scoped, restricted=restricted,
    )
    now = datetime.now(UTC)
    target = members["member"]
    ordinary = not scoped and not restricted
    permitted = ordinary
    if scenario == "matter_team":
        session.add(TeamMembership(team_id=team.id, membership_id=target.id))
        permitted = not restricted
    if scenario in {"grant", "revoked_grant", "expired_grant", "future_grant",
                    "wall_over_grant"}:
        session.add(MatterAccessGrant(
            company_id=company.id, matter_id=matter.id, membership_id=target.id,
            granted_by_membership_id=members["owner"].id,
            effective_from=now + timedelta(days=1) if scenario == "future_grant"
            else now - timedelta(days=2),
            expires_at=now - timedelta(days=1) if scenario == "expired_grant" else None,
            revoked_at=now if scenario == "revoked_grant" else None,
        ))
        permitted = scenario in {"grant", "wall_over_grant"} or ordinary
    if scenario in {"team_grant", "inactive_team_grant", "team_wall"}:
        session.add(TeamMembership(team_id=recipient_team.id, membership_id=target.id))
        if scenario == "team_wall":
            session.add(EthicalWall(company_id=company.id, matter_id=matter.id,
                                    excluded_team_id=recipient_team.id))
        else:
            recipient_team.is_active = scenario != "inactive_team_grant"
            session.add(MatterAccessGrant(
                company_id=company.id, matter_id=matter.id, team_id=recipient_team.id,
                granted_by_membership_id=members["owner"].id,
            ))
        permitted = scenario == "team_grant" or (
            scenario == "inactive_team_grant" and ordinary
        )
    if scenario in {"wall_over_grant", "expired_wall", "owner_wall", "assignee_wall"}:
        subject = members[scenario.removesuffix("_wall")] if scenario in {
            "owner_wall", "assignee_wall",
        } else target
        session.add(EthicalWall(
            company_id=company.id, matter_id=matter.id, excluded_membership_id=subject.id,
            effective_from=now - timedelta(days=2),
            expires_at=now - timedelta(days=1) if scenario == "expired_wall" else None,
        ))
        if scenario == "wall_over_grant":
            permitted = False
    session.commit()
    ids = {members["owner"].id}
    if scenario != "assignee_wall":
        ids.add(members["assignee"].id)
    if permitted:
        ids.add(target.id)
    scalar = {
        row.id for row in members.values()
        if can_access(session, context=SessionContext(
            company=company, membership=row, user=session.get(User, row.user_id),
        ), matter=matter)
    }
    assert scalar == ids
    session.flush()
    company_id, matter_id = company.id, matter.id
    membership_ids = [*(row.id for row in members.values()), outsider.id]
    statements = []
    engine = session.get_bind()

    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        statements.append(sql)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert visible_matter_membership_ids(
            session, company_id=company_id, matter_id=matter_id,
            membership_ids=membership_ids,
        ) == ids
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert statements[0].count("FROM company_memberships") == 1


def test_batch_rechecks_warmed_team_policy_and_revoked_grant(visibility_session):
    session = visibility_session
    company, matter, members, outsider, _team, _other = _seed(session)
    target = members["member"]
    assert target.id in _read_batch(session, company, matter, members, outsider)
    with Session(session.get_bind()) as writer:
        writer.get(Company, company.id).team_scoping_enabled = True
        writer.commit()
    assert company.team_scoping_enabled is False
    assert target.id not in _read_batch(session, company, matter, members, outsider)
    grant = MatterAccessGrant(company_id=company.id, matter_id=matter.id,
                              membership_id=target.id)
    session.add(grant)
    session.commit()
    assert target.id in _read_batch(session, company, matter, members, outsider)
    with Session(session.get_bind()) as writer:
        writer.get(MatterAccessGrant, grant.id).revoked_at = datetime.now(UTC)
        writer.commit()
    assert target.id not in _read_batch(session, company, matter, members, outsider)


def test_batch_bounds_raw_input_without_query_or_unbounded_consumption():
    consumed = []

    def ids():
        for number in range(100_000):
            consumed.append(number)
            yield "same"

    with pytest.raises(ValueError, match="500 participants"):
        visible_matter_membership_ids(None, company_id="tenant", matter_id="matter",
                                      membership_ids=ids())
    assert len(consumed) == 501
    assert visible_matter_membership_ids(
        None, company_id="tenant", matter_id="matter", membership_ids=[],
    ) == set()
