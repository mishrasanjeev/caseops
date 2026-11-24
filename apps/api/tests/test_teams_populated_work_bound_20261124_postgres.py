"""Populated-team removal is bounded at production scale on PostgreSQL.

A team with any Matter, grant or wall keeps the tenant-wide IP role fence. That
fence used to run about a dozen queries per active IP docket, three times per
removal, two of those passes while the actor's and target's Membership/User
rows were locked. Run against the previous ``services/teams.py`` (609914f5a),
the unscoped removal case on this fixture issued the counts in
``_PER_DOCKET_FENCE_EVIDENCE``. The set-based fence must issue a constant
number of statements, hold identity locks for a constant number, load only the
affected dockets, and read rows linearly in the tenant's live role rows.
"""

from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    IpDocketRecord,
    Matter,
    MatterHearing,
    MatterTask,
    Team,
    TeamMembership,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.teams import TeamUpdateRequest
from caseops_api.services import teams
from tests import test_team_membership_safety_postgres as team_safety
from tests.test_postgres_validation import _ip_race_context, _seed_matter

pytestmark = pytest.mark.postgres
team_fixture = team_safety.team_fixture

_DOCKETS = 10_000
_MATTERS = 200
_HEARING_EVERY = 10
# Measured on the previous per-docket fence: unscoped removal, this fixture.
_PER_DOCKET_FENCE_EVIDENCE = {
    "statements": 269_983,
    "statements_while_identity_locked": 179_976,
    "rows_read": 92_983,
    "loaded": {"IpDocketRecord": 30_000, "Matter": 14_951},
}
_STATEMENT_BUDGET = 80
_LOCKED_STATEMENT_BUDGET = 60
_IDENTITY_LOCKS = ("of company_memberships", "of users")


def _seed_populated_tenant(identity) -> dict[str, object]:
    company_id, actor_id, team_id, member_id, _row_id = identity
    factory = get_session_factory()
    with factory() as seed:
        # The team's own dependency: a Matter on the team, linked to no docket.
        seed.get(Matter, _seed_matter(seed, company_id)).team_id = team_id
        matter_ids = [str(uuid4()) for _ in range(_MATTERS)]
        seed.execute(
            insert(Matter),
            [
                {
                    "id": matter_id,
                    "company_id": company_id,
                    "title": f"Firm-wide matter {index}",
                    "matter_code": f"POP-{index}",
                    "client_name": "Synthetic client",
                    "status": "active",
                    "practice_area": "ip",
                    "forum_level": "high_court",
                    "is_active": True,
                    "restricted_access": False,
                    "assignee_membership_id": actor_id,
                }
                for index, matter_id in enumerate(matter_ids)
            ],
        )
        docket_ids = [str(uuid4()) for _ in range(_DOCKETS)]
        seed.execute(
            insert(IpDocketRecord),
            [
                {
                    "id": docket_id,
                    "company_id": company_id,
                    "matter_id": matter_ids[index % _MATTERS] if index % 2 == 0 else None,
                    "record_type": "trademark",
                    "title": f"Populated docket {index}",
                    "primary_identifier": f"POP-{index}",
                    "status": "active",
                    "is_active": True,
                    "restricted": False,
                    "created_by_membership_id": actor_id,
                }
                for index, docket_id in enumerate(docket_ids)
            ],
        )
        task_rows = [
            {"company_id": company_id, "ip_docket_id": docket_id, "owner_membership_id": actor_id}
            for index, docket_id in enumerate(docket_ids)
            if index % 2 == 1
        ] + [
            {"company_id": company_id, "matter_id": matter_id, "owner_membership_id": actor_id}
            for matter_id in matter_ids
        ]
        # Target responsibilities: a task, a JSON attendee, a JSON reminder.
        task_rows.append(
            {"company_id": company_id, "ip_docket_id": docket_ids[1],
             "owner_membership_id": member_id}
        )
        seed.execute(
            insert(MatterTask),
            [
                {
                    "id": str(uuid4()),
                    "matter_id": None,
                    "ip_docket_id": None,
                    "title": "Live responsibility",
                    "status": "todo",
                    "priority": "medium",
                    "created_by_membership_id": actor_id,
                    **row,
                }
                for row in task_rows
            ],
        )
        hearing_rows = [
            {"ip_docket_id": docket_id, "attendee_membership_ids_json": [actor_id],
             "reminder_policy_json": {"recipient_membership_ids": [actor_id]}}
            for index, docket_id in enumerate(docket_ids)
            if index % _HEARING_EVERY == 0
        ] + [
            {"matter_id": matter_id, "attendee_membership_ids_json": [actor_id],
             "reminder_policy_json": {"escalation_membership_id": actor_id}}
            for matter_id in matter_ids
        ] + [
            {"ip_docket_id": docket_ids[2], "attendee_membership_ids_json": [member_id],
             "reminder_policy_json": None},
            {"ip_docket_id": docket_ids[3], "attendee_membership_ids_json": [],
             "reminder_policy_json": {"recipient_membership_ids": [member_id]}},
        ]
        seed.execute(
            insert(MatterHearing),
            [
                {
                    "id": str(uuid4()),
                    "company_id": company_id,
                    "matter_id": None,
                    "ip_docket_id": None,
                    "hearing_on": date(2027, 1, 15),
                    "forum_name": "Synthetic forum",
                    "purpose": "Synthetic hearing",
                    "status": "scheduled",
                    **row,
                }
                for row in hearing_rows
            ],
        )
        seed.commit()
    return {
        "affected": sorted(docket_ids[1:4]),
        "linked_dockets": _DOCKETS // 2,
        "role_rows": len(task_rows) + len(hearing_rows),
    }


def _mutate(session, context, identity, mutation):
    _company_id, _actor_id, team_id, member_id, row_id = identity
    if mutation == "remove":
        teams.remove_team_member(
            session,
            context=context,
            team_id=team_id,
            membership_id=member_id,
            expected_team_membership_id=row_id,
        )
        return "team_membership.removed", row_id
    if mutation == "deactivate":
        teams.update_team(
            session, context=context, team_id=team_id, payload=TeamUpdateRequest(is_active=False)
        )
        return "team.updated", team_id
    teams.delete_team(session, context=context, team_id=team_id)
    return "team.deleted", team_id


@pytest.mark.parametrize("mutation", ["remove", "deactivate", "delete"])
@pytest.mark.parametrize("scoping_enabled", [False, True], ids=["unscoped", "scoped"])
def test_populated_team_change_is_bounded_at_production_scale(
    team_fixture, request, mutation, scoping_enabled
):
    company_id, actor_id, team_id, member_id, row_id = team_fixture
    seeded = _seed_populated_tenant(team_fixture)
    factory = get_session_factory()
    with factory() as precondition:
        precondition.get(Company, company_id).team_scoping_enabled = scoping_enabled
        precondition.commit()
        assert teams._team_has_access_dependencies(
            precondition, company_id=company_id, team_id=team_id
        )
        # The fence must find exactly the target's three live responsibilities.
        snapshot = teams._operational_ip_role_fence_snapshot(
            precondition,
            company_id=company_id,
            membership_scope={member_id},
            team_id=team_id,
        )
        assert sorted(snapshot) == seeded["affected"]
        assert {entry.role_membership_ids for entry in snapshot.values()} == {(member_id,)}

    statements: list[str] = []
    rows_read = [0]
    loaded: dict[str, int] = {"IpDocketRecord": 0, "Matter": 0}
    with factory() as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        connection = session.connection()

        def record(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(" ".join(statement.lower().split()))

        def count_rows(_connection, cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select") and cursor.rowcount > 0:
                rows_read[0] += cursor.rowcount

        def count_loads(_session, instance):
            name = type(instance).__name__
            if name in loaded:
                loaded[name] += 1

        event.listen(connection, "before_cursor_execute", record)
        event.listen(connection, "after_cursor_execute", count_rows)
        event.listen(session, "loaded_as_persistent", count_loads)
        try:
            action, target_id = _mutate(session, context, team_fixture, mutation)
            session.flush()
        finally:
            event.remove(connection, "before_cursor_execute", record)
            event.remove(connection, "after_cursor_execute", count_rows)
            event.remove(session, "loaded_as_persistent", count_loads)
        session.commit()

    first_lock = next(
        index
        for index, sql in enumerate(statements)
        if "for update" in sql and any(lock in sql for lock in _IDENTITY_LOCKS)
    )
    locked = len(statements) - first_lock
    evidence = {
        "statements": len(statements),
        "statements_while_identity_locked": locked,
        "per_docket_fence_unscoped_removal": _PER_DOCKET_FENCE_EVIDENCE,
        "rows_read": rows_read[0],
        "loaded": loaded,
    }
    request.node.user_properties.append(("populated_team_work", json.dumps(evidence)))
    assert len(statements) <= _STATEMENT_BUDGET, evidence
    assert locked <= _LOCKED_STATEMENT_BUDGET, evidence
    # Only the affected dockets and their Matters are loaded as entities.
    assert loaded["IpDocketRecord"] <= len(seeded["affected"]), evidence
    assert loaded["Matter"] <= len(seeded["affected"]) + 1, evidence
    # Three fence passes, each reading every docket, linked docket and live
    # role row at most once, plus a small constant for the rest of the request.
    assert rows_read[0] <= 3 * (_DOCKETS + seeded["linked_dockets"] + seeded["role_rows"]) + 200, (
        evidence
    )

    with factory() as read:
        assert read.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == action,
                AuditEvent.target_id == target_id,
            )
        ) == 1
        if mutation == "remove":
            assert read.get(TeamMembership, row_id) is None
            assert read.get(Team, team_id).is_active is True
        elif mutation == "deactivate":
            assert read.get(Team, team_id).is_active is False
        else:
            assert read.get(Team, team_id) is None
        assert read.scalar(
            select(func.count())
            .select_from(MatterTask)
            .where(MatterTask.company_id == company_id, MatterTask.status == "todo")
        ) == _DOCKETS // 2 + _MATTERS + 1
