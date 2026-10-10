"""Recipient and nested-consumer correlation remain isolated on both databases."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeMatterLink,
    EthicalWall,
    Matter,
    MatterAccessGrant,
    TeamMembership,
    User,
)
from caseops_api.schemas.notices import NoticeListFilters
from caseops_api.services.matter_access import can_access
from caseops_api.services.notices import list_notices
from caseops_api.services.private_retrieval import (
    PrivateProjectionInput,
    ProjectionScopeInput,
    _authorized_projection_ids_statement,
    ensure_active_private_generation,
    private_source_version,
    upsert_private_projection,
)
from caseops_api.services.record_access_policy import visible_matter_membership_ids
from caseops_api.services.session_context import SessionContext
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_record_access_policy_batch_20261010 import _seed
from tests.test_record_access_policy_batch_20261010 import (
    visibility_session as _visibility_session,
)

visibility_session = _visibility_session


def _context(session, company, member):
    return SessionContext(company=company, membership=member,
                          user=session.get(User, member.user_id))


def _member(session, company_id):
    user = User(email=f"correlation-{uuid4()}@example.test", full_name="Ordinary peer",
                password_hash="not-used", is_active=True)
    session.add(user)
    session.flush()
    member = CompanyMembership(company_id=company_id, user_id=user.id, role="member")
    session.add(member)
    session.flush()
    return member


def _matter(session, company_id, *, restricted=False):
    row = Matter(company_id=company_id, title="Independent policy source",
                 matter_code=f"COR-{uuid4()}", status="intake", practice_area="commercial",
                 forum_level="high_court", restricted_access=restricted)
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("authority", ["member_grant", "team_grant", "matter_team"])
def test_batch_never_borrows_another_recipients_or_matters_authority(
    visibility_session, authority,
):
    session = visibility_session
    company, matter, members, outsider, team, second_team = _seed(
        session, scoped=True, restricted=authority != "matter_team",
    )
    matter.assignee_membership_id = None
    target = members["member"]
    peer = _member(session, company.id)
    unrelated = _matter(session, company.id, restricted=True)
    foreign = _matter(session, outsider.company_id, restricted=True)
    session.add_all([
        MatterAccessGrant(company_id=company.id, matter_id=unrelated.id, membership_id=peer.id),
        MatterAccessGrant(company_id=foreign.company_id, matter_id=foreign.id,
                          membership_id=outsider.id),
        TeamMembership(team_id=second_team.id, membership_id=peer.id),
    ])
    if authority == "member_grant":
        session.add(MatterAccessGrant(company_id=company.id, matter_id=matter.id,
                                      membership_id=target.id))
    elif authority == "team_grant":
        session.add(TeamMembership(team_id=team.id, membership_id=target.id))
        session.add(MatterAccessGrant(company_id=company.id, matter_id=matter.id,
                                      team_id=team.id))
    else:
        session.add(TeamMembership(team_id=team.id, membership_id=target.id))
    session.commit()
    assert visible_matter_membership_ids(
        session, company_id=company.id, matter_id=matter.id,
        membership_ids=[target.id, peer.id, outsider.id],
    ) == {target.id}
    assert can_access(session, context=_context(session, company, target), matter=matter)
    assert not can_access(session, context=_context(session, company, peer), matter=matter)


def test_batch_rechecks_role_team_removal_and_new_wall(visibility_session):
    session = visibility_session
    company, matter, members, _outsider, team, _second = _seed(session, scoped=True)
    owner, target = members["owner"], members["member"]
    session.add(TeamMembership(team_id=team.id, membership_id=target.id))
    session.commit()
    company_id, matter_id, owner_id, target_id = company.id, matter.id, owner.id, target.id

    def visible():
        return visible_matter_membership_ids(
            session, company_id=company_id, matter_id=matter_id,
            membership_ids=[owner_id, target_id],
        )

    assert visible() == {owner_id, target_id}
    with Session(session.get_bind()) as writer:
        writer.get(CompanyMembership, owner_id).role = "member"
        writer.execute(delete(TeamMembership).where(
            TeamMembership.team_id == team.id, TeamMembership.membership_id == target_id,
        ))
        writer.commit()
    assert visible() == set()
    session.add(MatterAccessGrant(company_id=company_id, matter_id=matter_id,
                                  membership_id=target_id))
    session.commit()
    assert visible() == {target_id}
    with Session(session.get_bind()) as writer:
        writer.add(EthicalWall(company_id=company_id, matter_id=matter_id,
                               excluded_membership_id=target_id,
                               effective_from=datetime.now(UTC)))
        writer.commit()
    assert visible() == set()


def test_batch_accepts_bound_duplicates_unknowns_and_rejects_mismatched_parent(
    visibility_session,
):
    session = visibility_session
    company, matter, members, outsider, _team, _second = _seed(session)
    owner_id = members["owner"].id
    assert visible_matter_membership_ids(
        session, company_id=company.id, matter_id=matter.id,
        membership_ids=[owner_id] * 498 + [str(uuid4()), outsider.id],
    ) == {owner_id}
    assert visible_matter_membership_ids(
        session, company_id=outsider.company_id, matter_id=matter.id,
        membership_ids=[outsider.id, owner_id],
    ) == set()
    assert visible_matter_membership_ids(
        session, company_id=company.id, matter_id=str(uuid4()), membership_ids=[owner_id],
    ) == set()


@pytest.mark.parametrize("scoped", [False, True])
def test_nested_notice_and_private_scope_queries_keep_hidden_nullable_parent_hidden(
    visibility_session, scoped,
):
    session = visibility_session
    company, hidden, members, _outsider, _team, _second = _seed(session, restricted=True)
    company.team_scoping_enabled = scoped
    hidden.assignee_membership_id = None
    hidden.team_id = None
    visible = _matter(session, company.id)
    unrelated = _matter(session, company.id, restricted=True)
    session.add(MatterAccessGrant(company_id=company.id, matter_id=unrelated.id,
                                  membership_id=members["member"].id))
    notices = [CompanyNotice(company_id=company.id, subject=label,
                             created_by_membership_id=members["owner"].id)
               for label in ("Standalone", "Visible only", "Mixed hidden")]
    session.add_all(notices)
    session.flush()
    session.add_all([
        CompanyNoticeMatterLink(company_id=company.id, notice_id=notices[1].id,
                               matter_id=visible.id),
        CompanyNoticeMatterLink(company_id=company.id, notice_id=notices[2].id,
                               matter_id=visible.id),
        CompanyNoticeMatterLink(company_id=company.id, notice_id=notices[2].id,
                               matter_id=hidden.id),
    ])
    session.commit()
    context = _context(session, company, members["member"])
    register = list_notices(session, context=context, filters=NoticeListFilters())
    assert register.total == 2
    assert {row.id for row in register.notices} == {notices[0].id, notices[1].id}
    assert not can_access(session, context=context, matter=hidden)

    generation = ensure_active_private_generation(session, company_id=company.id)
    projections = {}
    for source in (visible, hidden, unrelated):
        payload = PrivateProjectionInput(
            source_type="matter", source_id=source.id,
            source_version=private_source_version(source),
            chunk_ordinal=0, label="Policy source", content="Current bounded fixture source",
            scopes=(ProjectionScopeInput(scope_type="matter", scope_id=source.id,
                                         access_policy_version=source.access_policy_version),),
        )
        projection = upsert_private_projection(
            session, company_id=company.id, generation_id=generation.id, payload=payload,
            expected_access_policy_generation=generation.access_policy_generation,
            expected_tombstone_generation=generation.tombstone_generation,
        )
        projections[source.id] = projection.id
    session.commit()
    assert set(session.scalars(_authorized_projection_ids_statement(
        session, context=context, generation=generation,
    ))) == {projections[visible.id], projections[unrelated.id]}
