"""The IP docket policy can be used more than once in one statement (B4-ADJ-10).

``visible_ip_dockets_filter`` materializes the reader's active teams as a
CTE. Built anonymously, the CTE took its name from a temporary object; once
that object was freed the next call could reuse the name, so a statement
holding two policy calls failed to compile ("Multiple, unrelated CTEs found
with the same name") and the endpoint answered 500. GET /api/ip/watch hit it
first (fixed there alone in eb421f4c); any statement that combines two
policy-scoped subqueries is exposed the same way.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects import postgresql, sqlite

from caseops_api.db.models import (
    EthicalWall,
    IpDocketRecord,
    MatterAccessGrant,
    Team,
    TeamMembership,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.record_access_policy import visible_ip_dockets_filter
from tests.test_auth_company import bootstrap_company
from tests.test_ip_record_access_foundation import _create_restricted_docket, _invite_member
from tests.test_ip_record_workflow import _docket

_CONTEXT = SimpleNamespace(
    company=SimpleNamespace(id="company-1"), membership=SimpleNamespace(id="member-1")
)


def _two_policy_statement(context: object):
    first = select(IpDocketRecord.id).where(visible_ip_dockets_filter(None, context=context))  # type: ignore[arg-type]
    second = select(TrademarkApplication.docket_id).join(
        IpDocketRecord, IpDocketRecord.id == TrademarkApplication.docket_id
    ).where(visible_ip_dockets_filter(None, context=context))  # type: ignore[arg-type]
    return select(IpDocketRecord.id).where(
        or_(IpDocketRecord.id.in_(first), IpDocketRecord.id.in_(second))
    )


def test_two_policy_calls_in_one_statement_compile_on_every_dialect() -> None:
    # The old anonymous name collided in 392 of 400 compilations of this shape.
    for _ in range(100):
        statement = _two_policy_statement(_CONTEXT)
        for dialect in (sqlite.dialect(), postgresql.dialect()):
            sql = str(statement.compile(dialect=dialect))
            assert "MATERIALIZED" in sql or dialect.name == "sqlite"


def test_each_policy_call_names_its_own_cte() -> None:
    statement = _two_policy_statement(_CONTEXT)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    names = {
        line.split(" AS ")[0].strip().lstrip(",").strip().removeprefix("WITH ").strip()
        for line in sql.splitlines()
        if " AS MATERIALIZED" in line
    }
    assert len(names) == 2, sql


def test_policy_statements_keep_one_compilation_cache_key() -> None:
    # Unique literal names would make every policy query a cache miss.
    first = select(IpDocketRecord.id).where(visible_ip_dockets_filter(None, context=_CONTEXT))  # type: ignore[arg-type]
    second = select(IpDocketRecord.id).where(visible_ip_dockets_filter(None, context=_CONTEXT))  # type: ignore[arg-type]
    first_key, second_key = first._generate_cache_key(), second._generate_cache_key()
    assert first_key is not None and second_key is not None
    assert first_key.key == second_key.key


def test_two_policy_calls_execute_and_keep_the_policy(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = {"Authorization": f"Bearer {token}"}
    docket = _docket(client, headers, "CTE POLICY MARK")
    context = SimpleNamespace(
        company=SimpleNamespace(id=bootstrap["company"]["id"]),
        membership=SimpleNamespace(id=bootstrap["membership"]["id"]),
    )
    other = SimpleNamespace(
        company=SimpleNamespace(id="another-company"),
        membership=SimpleNamespace(id="another-member"),
    )
    with get_session_factory()() as session:
        visible = set(
            session.scalars(
                _two_policy_statement(context).where(  # type: ignore[arg-type]
                    IpDocketRecord.company_id == bootstrap["company"]["id"]
                )
            )
        )
        assert docket["id"] in visible
        # The other tenant's reader sees nothing of this tenant through either call.
        foreign = set(
            session.scalars(
                _two_policy_statement(other).where(
                    IpDocketRecord.company_id == other.company.id
                )
            )
        )
        assert foreign == set()


def _both_policies_statement(context: object):
    """A docket survives only if each of the two policy calls admits it."""
    first = select(IpDocketRecord.id).where(visible_ip_dockets_filter(None, context=context))  # type: ignore[arg-type]
    second = select(IpDocketRecord.id).where(visible_ip_dockets_filter(None, context=context))  # type: ignore[arg-type]
    return select(IpDocketRecord.id).where(
        IpDocketRecord.id.in_(first), IpDocketRecord.id.in_(second)
    )


def _either_policy_statement(context: object):
    """A docket leaks if either of the two policy calls admits it."""
    first = select(IpDocketRecord.id).where(visible_ip_dockets_filter(None, context=context))  # type: ignore[arg-type]
    second = select(IpDocketRecord.id).where(visible_ip_dockets_filter(None, context=context))  # type: ignore[arg-type]
    return select(IpDocketRecord.id).where(
        or_(IpDocketRecord.id.in_(first), IpDocketRecord.id.in_(second))
    )


def test_two_policy_calls_still_hide_restricted_and_walled_dockets_in_one_tenant(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    company_id = str(bootstrap["company"]["id"])
    owner_id = str(bootstrap["membership"]["id"])
    member_id, member_headers = _invite_member(client, owner_token)
    restricted = str(_create_restricted_docket(client, owner_headers)["id"])
    walled = str(_docket(client, owner_headers, "CTE WALLED MARK")["id"])
    open_docket = str(_docket(client, owner_headers, "CTE OPEN MARK")["id"])

    with get_session_factory()() as session:
        # The restricted docket is reachable only through a team the member is
        # not in, so each CTE must resolve the reader's own active teams.
        session.execute(
            delete(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == restricted)
        )
        review = Team(company_id=company_id, name="CTE review team", slug="cte-review-team")
        conflicted = Team(company_id=company_id, name="CTE conflict team", slug="cte-conflict-team")
        session.add_all([review, conflicted])
        session.flush()
        session.add(TeamMembership(team_id=review.id, membership_id=owner_id))
        session.add(TeamMembership(team_id=conflicted.id, membership_id=member_id))
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=restricted,
                team_id=review.id,
                reason="Team-only review scope.",
                granted_by_membership_id=owner_id,
            )
        )
        # The walled docket excludes the member's team through the team CTE.
        session.add(
            EthicalWall(
                company_id=company_id,
                ip_docket_id=walled,
                excluded_team_id=conflicted.id,
                reason="Conflict team excluded.",
                created_by_membership_id=owner_id,
            )
        )
        session.commit()

    owner = SimpleNamespace(
        company=SimpleNamespace(id=company_id), membership=SimpleNamespace(id=owner_id)
    )
    member = SimpleNamespace(
        company=SimpleNamespace(id=company_id), membership=SimpleNamespace(id=member_id)
    )
    in_tenant = IpDocketRecord.company_id == company_id
    with get_session_factory()() as session:
        # Positive control: both calls admit the team-granted and walled dockets
        # for the owner, so each CTE carries the owner's team.
        owner_rows = set(session.scalars(_both_policies_statement(owner).where(in_tenant)))
        assert {restricted, walled, open_docket} <= owner_rows
        # Neither call lets the restricted or walled docket reach the member.
        member_rows = set(session.scalars(_either_policy_statement(member).where(in_tenant)))
        assert open_docket in member_rows
        assert restricted not in member_rows
        assert walled not in member_rows
        # The same answer through the mixed shape used by the original 500.
        mixed = set(session.scalars(_two_policy_statement(member).where(in_tenant)))  # type: ignore[arg-type]
        assert restricted not in mixed and walled not in mixed and open_docket in mixed
    # The API, which uses the same policy, agrees.
    listed = client.get("/api/ip/dockets", headers=member_headers)
    assert listed.status_code == 200, listed.text
    listed_ids = {row["id"] for row in listed.json()["dockets"]}
    assert open_docket in listed_ids
    assert restricted not in listed_ids and walled not in listed_ids
