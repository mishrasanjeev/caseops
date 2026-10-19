"""Canonical IP team authority stays actor-scoped and fresh per statement."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event, literal, select, union_all
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    EthicalWall,
    IpDocketRecord,
    MatterAccessGrant,
    Team,
    TeamMembership,
)
from caseops_api.services.record_access_policy import visible_ip_dockets_filter
from tests.test_ip_active_team_candidates_postgres import _statement
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_membership,
)

pytestmark = pytest.mark.postgres


def _seed_team_grantee(session, *, company_id=None, direct=False, active=True):
    company_id = company_id or _seed_company(session)
    member_id = _seed_membership(session, company_id, role="owner")
    team = Team(
        company_id=company_id,
        name="Statement-scoped authority",
        slug=f"statement-authority-{uuid4().hex}",
        is_active=active,
    )
    docket = IpDocketRecord(
        company_id=company_id,
        title="Statement-scoped restricted fixture",
        record_type="design_intake",
        restricted=True,
        created_by_membership_id=member_id,
    )
    session.add_all([team, docket])
    session.flush()
    association = TeamMembership(team_id=team.id, membership_id=member_id)
    grant = MatterAccessGrant(
        company_id=company_id,
        ip_docket_id=docket.id,
        membership_id=member_id if direct else None,
        team_id=None if direct else team.id,
        granted_by_membership_id=member_id,
    )
    session.add_all([association, grant])
    session.flush()
    return {
        "company": company_id,
        "member": member_id,
        "team": team.id,
        "docket": docket.id,
        "association": association.id,
        "grant": grant.id,
    }


def _read_once(session, statement):
    sql = []
    connection = session.connection()

    def capture(_connection, _cursor, text, _params, _context, _many):
        sql.append(text)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        rows = session.execute(statement).all()
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert len(sql) == 1, sql
    return rows, sql[0]


@pytest.mark.parametrize("separate_tenants", [False, True], ids=["same-tenant", "two-tenants"])
def test_ip_team_predicates_compose_two_actors_without_borrowed_authority(
    pg_engine, separate_tenants
):
    with Session(pg_engine) as seed:
        first = _seed_team_grantee(seed)
        second = _seed_team_grantee(
            seed, company_id=None if separate_tenants else first["company"]
        )
        seed.commit()
    assert first["member"] != second["member"]
    assert first["team"] != second["team"]
    assert (first["company"] != second["company"]) is separate_tenants

    with Session(pg_engine) as reader:
        assert reader.get_bind().dialect.name == "postgresql"
        contexts = [
            _ip_race_context(
                reader, company_id=fixture["company"], membership_id=fixture["member"]
            )
            for fixture in (first, second)
        ]
        targets = [first["docket"], second["docket"]]

        def actor_scope(context):
            return select(
                literal(context.membership.id).label("actor_id"),
                IpDocketRecord.id.label("docket_id"),
            ).where(
                IpDocketRecord.id.in_(targets),
                IpDocketRecord.company_id == context.company.id,
                visible_ip_dockets_filter(reader, context=context),
            )

        # Distinct predicate invocations must keep distinct anonymous actor scopes.
        statement = union_all(*(actor_scope(context) for context in contexts))
        compiled = statement.compile(reader.get_bind())
        assert compiled.statement is statement
        rows, _sql = _read_once(reader, statement)
        assert len(rows) == 2
        assert {(row.actor_id, row.docket_id) for row in rows} == {
            (first["member"], first["docket"]),
            (second["member"], second["docket"]),
        }


@pytest.mark.parametrize(
    "change",
    ["team-deactivate", "membership-remove", "direct-revoke", "wall-activate", "wall-revoke"],
)
def test_same_precompiled_ip_statement_rechecks_second_transaction_changes(
    pg_engine, change
):
    direct = change in {"direct-revoke", "wall-activate", "wall-revoke"}
    has_wall = change in {"wall-activate", "wall-revoke"}
    initial_active = change != "wall-activate"
    with Session(pg_engine) as seed:
        fixture = _seed_team_grantee(seed, direct=direct, active=initial_active)
        wall_id = None
        if has_wall:
            wall = EthicalWall(
                company_id=fixture["company"],
                ip_docket_id=fixture["docket"],
                excluded_team_id=fixture["team"],
                created_by_membership_id=fixture["member"],
            )
            seed.add(wall)
            seed.flush()
            wall_id = wall.id
        seed.commit()

    with Session(pg_engine) as reader:
        assert reader.get_bind().dialect.name == "postgresql"
        assert reader.connection().get_isolation_level() == "READ COMMITTED"
        context = _ip_race_context(
            reader, company_id=fixture["company"], membership_id=fixture["member"]
        )
        warm_team = reader.get(Team, fixture["team"])
        warm_association = reader.get(TeamMembership, fixture["association"])
        warm_grant = reader.get(MatterAccessGrant, fixture["grant"])
        warm_wall = reader.get(EthicalWall, wall_id) if wall_id else None
        assert warm_team.is_active is initial_active
        assert warm_association is not None
        assert warm_grant.revoked_at is None
        assert warm_grant.membership_id == (fixture["member"] if direct else None)
        assert warm_grant.team_id == (None if direct else fixture["team"])

        # No predicate rebuild, reader commit or identity-map expiration below.
        statement = _statement(reader, context, fixture["docket"])
        compiled = statement.compile(reader.get_bind())
        assert compiled.statement is statement
        initial_allowed = change != "wall-revoke"
        expected = [(fixture["docket"],)] if initial_allowed else []
        before, before_sql = _read_once(reader, statement)
        assert before == expected
        reader_transaction = reader.get_transaction()
        assert reader_transaction is not None

        with Session(pg_engine) as writer:
            if change == "team-deactivate":
                writer.get(Team, fixture["team"]).is_active = False
            elif change == "membership-remove":
                writer.delete(writer.get(TeamMembership, fixture["association"]))
            elif change == "direct-revoke":
                writer.get(MatterAccessGrant, fixture["grant"]).revoked_at = datetime.now(UTC)
            elif change == "wall-activate":
                writer.get(Team, fixture["team"]).is_active = True
            else:
                writer.get(EthicalWall, wall_id).revoked_at = datetime.now(UTC)
            writer.commit()

        assert reader.get_transaction() is reader_transaction
        assert not reader.new and not reader.dirty and not reader.deleted
        assert reader.get(Team, fixture["team"]) is warm_team
        assert warm_team.is_active is initial_active
        assert reader.get(TeamMembership, fixture["association"]) is warm_association
        assert warm_grant.revoked_at is None
        if warm_wall is not None:
            assert warm_wall.revoked_at is None
        changed, changed_sql = _read_once(reader, statement)
        assert changed_sql == before_sql
        assert changed == ([] if initial_allowed else [(fixture["docket"],)])
        assert compiled.statement is statement

        with Session(pg_engine) as writer:
            if change in {"team-deactivate", "wall-activate"}:
                writer.get(Team, fixture["team"]).is_active = initial_active
            elif change == "membership-remove":
                writer.add(TeamMembership(
                    team_id=fixture["team"], membership_id=fixture["member"]
                ))
            elif change == "direct-revoke":
                writer.get(MatterAccessGrant, fixture["grant"]).revoked_at = None
            else:
                writer.get(EthicalWall, wall_id).revoked_at = None
            writer.commit()

        assert reader.get_transaction() is reader_transaction
        restored, restored_sql = _read_once(reader, statement)
        assert restored_sql == before_sql
        assert restored == expected
        assert compiled.statement is statement
        assert not reader.new and not reader.dirty and not reader.deleted
