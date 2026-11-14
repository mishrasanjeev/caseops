"""PostgreSQL regression candidates for the narrow zero-dependency repair."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from queue import Queue
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text

from caseops_api.db.models import (
    AuditEvent,
    Company,
    EthicalWall,
    IpDocketRecord,
    Matter,
    MatterAccessGrant,
    MatterTask,
    Team,
    TeamMembership,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.teams import TeamUpdateRequest
from caseops_api.services import teams
from caseops_api.services.matter_access import can_stably_access_ip_docket
from tests.test_postgres_validation import _ip_race_context, _seed_company, _seed_matter
from tests.test_team_membership_safety_postgres import (
    _pid,
    _run_writer,
    _wait_on,
    team_fixture,  # noqa: F401
)

pytestmark = pytest.mark.postgres

_UNRELATED_DOCKET_COUNT = 10_000
_UNUSED_TEAM_QUERY_BUDGET = 40
_ROLE_TABLES = (
    "ip_deadline_coverages",
    "matter_deadlines",
    "ip_deadlines",
    "ip_responsibility_assignments",
    "matter_tasks",
    "matter_hearings",
    "ip_related_right_obligations",
)


def _mutate(session, context, identity, mutation):
    _company_id, _actor_id, team_id, member_id, row_id = identity
    if mutation == "remove":
        return teams.remove_team_member(
            session, context=context, team_id=team_id,
            membership_id=member_id, expected_team_membership_id=row_id,
        )
    if mutation == "deactivate":
        return teams.update_team(
            session, context=context, team_id=team_id,
            payload=TeamUpdateRequest(is_active=False),
        )
    assert mutation == "delete"
    return teams.delete_team(session, context=context, team_id=team_id)


@pytest.mark.parametrize("mutation", ["remove", "deactivate", "delete"])
@pytest.mark.parametrize("scoping_enabled", [False, True], ids=["unscoped", "scoped"])
def test_unused_team_does_not_load_tenant_ip_roles_at_production_scale(
    team_fixture, mutation, scoping_enabled,
):
    company_id, actor_id, team_id, member_id, row_id = team_fixture
    factory = get_session_factory()
    with factory() as seed:
        company = seed.get(Company, company_id)
        assert company is not None
        company.team_scoping_enabled = scoping_enabled
        seed.execute(insert(IpDocketRecord), [
            {
                "id": str(uuid4()), "company_id": company_id,
                "record_type": "trademark", "title": f"Unrelated docket {index}",
                "primary_identifier": f"UNRELATED-{index}", "status": "active",
                "is_active": True, "restricted": False,
                "created_by_membership_id": actor_id,
            }
            for index in range(_UNRELATED_DOCKET_COUNT)
        ])
        seed.commit()

    with factory() as precondition:
        assert precondition.scalar(select(func.count()).select_from(IpDocketRecord).where(
            IpDocketRecord.company_id == company_id,
            IpDocketRecord.matter_id.is_(None),
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.status == "active",
        )) == _UNRELATED_DOCKET_COUNT
        assert precondition.scalar(select(func.count()).select_from(Matter).where(
            Matter.company_id == company_id, Matter.team_id == team_id,
        )) == 0
        assert precondition.scalar(select(func.count()).select_from(MatterAccessGrant).where(
            MatterAccessGrant.company_id == company_id, MatterAccessGrant.team_id == team_id,
        )) == 0
        assert precondition.scalar(select(func.count()).select_from(EthicalWall).where(
            EthicalWall.company_id == company_id, EthicalWall.excluded_team_id == team_id,
        )) == 0
        assert precondition.get(TeamMembership, row_id).membership_id == member_id

    statements: list[str] = []
    with factory() as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        connection = session.connection()

        def reject_unrelated_docket(_session, instance):
            assert not isinstance(instance, IpDocketRecord), (
                "An unused team must have zero affected IP targets; the mutation "
                "loaded a tenant docket before establishing any team dependency."
            )

        def bound_queries(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())
            assert len(statements) <= _UNUSED_TEAM_QUERY_BUDGET, (
                "Unused-team work grew with unrelated tenant data."
            )
            compact = " ".join(statement.lower().split())
            assert not any(f"from {table}" in compact for table in _ROLE_TABLES), (
                "An unused team queried operational role tables despite zero targets."
            )

        event.listen(session, "loaded_as_persistent", reject_unrelated_docket)
        event.listen(connection, "before_cursor_execute", bound_queries)
        try:
            result = _mutate(session, context, team_fixture, mutation)
            session.flush()
        finally:
            event.remove(connection, "before_cursor_execute", bound_queries)
            event.remove(session, "loaded_as_persistent", reject_unrelated_docket)
        session.commit()
        if mutation == "remove":
            assert result.members == []
        elif mutation == "deactivate":
            assert result.is_active is False
        else:
            assert result is None

    assert 0 < len(statements) <= _UNUSED_TEAM_QUERY_BUDGET
    with factory() as read:
        team = read.get(Team, team_id)
        membership = read.get(TeamMembership, row_id)
        if mutation == "delete":
            assert team is None and membership is None
        elif mutation == "remove":
            assert team is not None and team.is_active is True
            assert membership is None
        else:
            assert team is not None and team.is_active is False
            assert membership is not None
        assert read.get(Company, company_id).team_scoping_enabled is scoping_enabled
        assert read.scalar(select(func.count()).select_from(IpDocketRecord).where(
            IpDocketRecord.company_id == company_id, IpDocketRecord.status == "active",
        )) == _UNRELATED_DOCKET_COUNT
        action = {
            "remove": "team_membership.removed",
            "deactivate": "team.updated", "delete": "team.deleted",
        }[mutation]
        assert read.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.company_id == company_id, AuditEvent.action == action,
            AuditEvent.target_id == (row_id if mutation == "remove" else team_id),
        )) == 1


@pytest.mark.parametrize("mutation", ["remove", "deactivate", "delete"])
@pytest.mark.parametrize("access_path", ["matter_team", "matter_team_grant", "ip_team_grant"])
def test_team_work_scope_preserves_linked_and_unlinked_responsibilities(
    team_fixture, mutation, access_path,
):
    company_id, actor_id, team_id, member_id, row_id = team_fixture
    factory = get_session_factory()
    grant_id = None
    with factory() as seed:
        seed.get(Company, company_id).team_scoping_enabled = True
        matter_id = None
        if access_path != "ip_team_grant":
            matter_id = _seed_matter(seed, company_id)
            matter = seed.get(Matter, matter_id)
            assert matter is not None
            matter.team_id = team_id if access_path == "matter_team" else None
            matter.restricted_access = access_path == "matter_team_grant"
            seed.flush()
        docket = IpDocketRecord(
            company_id=company_id, matter_id=matter_id, record_type="trademark",
            title="Affected role docket", status="active", is_active=True,
            restricted=access_path == "ip_team_grant",
            created_by_membership_id=actor_id,
        )
        seed.add(docket)
        seed.flush()
        docket_id = docket.id
        task = MatterTask(
            company_id=company_id, ip_docket_id=docket_id,
            title="Retained operational responsibility", status="todo", priority="high",
            owner_membership_id=member_id, created_by_membership_id=actor_id,
        )
        seed.add(task)
        if access_path != "matter_team":
            grant = MatterAccessGrant(
                company_id=company_id, team_id=team_id,
                matter_id=matter_id if access_path == "matter_team_grant" else None,
                ip_docket_id=docket_id if access_path == "ip_team_grant" else None,
                access_level="member", reason="Team-only durable access fixture.",
                granted_by_membership_id=actor_id, effective_from=None, expires_at=None,
            )
            seed.add(grant)
            seed.flush()
            grant_id = grant.id
        seed.flush()
        task_id = task.id
        seed.commit()

    with factory() as precondition:
        context = _ip_race_context(precondition, company_id=company_id, membership_id=member_id)
        docket = precondition.get(IpDocketRecord, docket_id)
        assert docket is not None
        assert (docket.matter_id is None) is (access_path == "ip_team_grant")
        assert can_stably_access_ip_docket(precondition, context=context, docket=docket)
        task_before = precondition.get(MatterTask, task_id)
        assert task_before is not None and task_before.status == "todo"
        retained_task = (
            task_before.owner_membership_id, task_before.status, task_before.updated_at,
        )

    deletion_makes_matter_firmwide = mutation == "delete" and access_path == "matter_team"
    with factory() as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        if deletion_makes_matter_firmwide:
            assert _mutate(session, context, team_fixture, mutation) is None
            session.commit()
        else:
            with pytest.raises(HTTPException) as rejected:
                _mutate(session, context, team_fixture, mutation)
            session.rollback()
            assert rejected.value.status_code == 409
            assert rejected.value.detail["code"] == "ip_team_access_responsibility_handoff_required"
            assert rejected.value.detail["blocked_membership_ids"] == [member_id]
            assert rejected.value.detail["blocked_ip_docket_ids"] == [docket_id]

    with factory() as read:
        if deletion_makes_matter_firmwide:
            assert read.get(Team, team_id) is None
            assert read.get(TeamMembership, row_id) is None
            assert read.get(Matter, matter_id).team_id is None
            context = _ip_race_context(read, company_id=company_id, membership_id=member_id)
            assert can_stably_access_ip_docket(
                read, context=context, docket=read.get(IpDocketRecord, docket_id),
            )
        else:
            assert read.get(Team, team_id).is_active is True
            assert read.get(TeamMembership, row_id).membership_id == member_id
        task = read.get(MatterTask, task_id)
        assert (task.owner_membership_id, task.status, task.updated_at) == retained_task
        docket = read.get(IpDocketRecord, docket_id)
        assert docket.is_active is True and docket.status == "active"
        if grant_id is not None:
            assert read.get(MatterAccessGrant, grant_id).revoked_at is None
        assert read.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.company_id == company_id,
            AuditEvent.action.in_(["team_membership.removed", "team.updated", "team.deleted"]),
            AuditEvent.target_id.in_([row_id, team_id]),
        )) == int(deletion_makes_matter_firmwide)


def _seed_unlinked_role_dockets(session, identity, *, count):
    company_id, actor_id, _team_id, member_id, _row_id = identity
    dockets = [IpDocketRecord(
        company_id=company_id, record_type="trademark", title=f"Role docket {index}",
        status="active", is_active=True, restricted=False,
        created_by_membership_id=actor_id,
    ) for index in range(count)]
    session.add_all(dockets)
    session.flush()
    for docket in dockets:
        session.add(MatterTask(
            company_id=company_id, ip_docket_id=docket.id, title="Live role",
            status="todo", owner_membership_id=member_id, created_by_membership_id=actor_id,
        ))
    session.flush()
    return [docket.id for docket in dockets]


def _team_acl_dependency(kind, *, company_id, team_id, docket_id, state):
    now = datetime.now(UTC)
    fields = {
        "company_id": company_id, "ip_docket_id": docket_id,
        "effective_from": now - timedelta(days=2),
        "expires_at": now - timedelta(days=1) if state == "expired" else None,
        "revoked_at": now - timedelta(days=1) if state == "revoked" else None,
        "reason": "Retained team dependency fixture.",
    }
    if state == "future":
        fields["effective_from"] = now + timedelta(days=1)
    if kind == "grant":
        return MatterAccessGrant(team_id=team_id, access_level="member", **fields)
    assert kind == "wall"
    return EthicalWall(excluded_team_id=team_id, **fields)


@pytest.mark.parametrize("mutation", ["remove", "deactivate", "delete"])
@pytest.mark.parametrize("state", ["revoked", "expired", "future"])
@pytest.mark.parametrize("kind", ["grant", "wall"])
def test_historical_and_future_unlinked_acl_dependencies_keep_the_full_fence(
    team_fixture, monkeypatch, mutation, state, kind,
):
    company_id, actor_id, team_id, _member_id, _row_id = team_fixture
    factory = get_session_factory()
    with factory() as seed:
        docket_ids = _seed_unlinked_role_dockets(seed, team_fixture, count=2)
        seed.add(_team_acl_dependency(
            kind, company_id=company_id, team_id=team_id, docket_id=docket_ids[0], state=state,
        ))
        seed.commit()

    visited = []
    original_roles = teams._operational_ip_docket_role_membership_ids

    def record_roles(session, *, docket):
        visited.append(docket.id)
        assert docket.matter_id is None
        return original_roles(session, docket=docket)

    monkeypatch.setattr(teams, "_operational_ip_docket_role_membership_ids", record_roles)
    with factory() as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        assert teams._team_has_access_dependencies(session, company_id=company_id, team_id=team_id)
        _mutate(session, context, team_fixture, mutation)
        session.commit()
    # Any dependency preserves the original tenant-wide pipeline, including
    # the second docket with no dependency on this team, at all three stages.
    assert visited == sorted(docket_ids) * 3
    with factory() as read:
        assert read.scalar(select(func.count()).select_from(MatterTask).where(
            MatterTask.ip_docket_id.in_(docket_ids), MatterTask.status == "todo",
        )) == 2


@pytest.mark.parametrize("mutation", ["remove", "deactivate", "delete"])
def test_zero_dependency_is_rechecked_at_all_three_locked_checkpoints(
    team_fixture, monkeypatch, mutation,
):
    company_id, actor_id, team_id, _member_id, _row_id = team_fixture
    factory = get_session_factory()
    with factory() as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        connection = session.connection()
        acquired = set()
        observations = []
        original_probe = teams._team_has_access_dependencies
        transaction = session.get_transaction()

        def observe_sql(_connection, _cursor, statement, _parameters, _context, _many):
            sql = " ".join(statement.lower().split())
            for table in ["companies", "company_memberships", "users", "teams"]:
                if f"for update of {table}" in sql or f"for no key update of {table}" in sql:
                    acquired.add(table)

        def observe_probe(probe_session, **kwargs):
            assert probe_session is session
            assert kwargs == {"company_id": company_id, "team_id": team_id}
            assert session.get_transaction() is transaction
            observations.append(set(acquired))
            return original_probe(probe_session, **kwargs)

        monkeypatch.setattr(teams, "_team_has_access_dependencies", observe_probe)
        event.listen(connection, "before_cursor_execute", observe_sql)
        try:
            _mutate(session, context, team_fixture, mutation)
        finally:
            event.remove(connection, "before_cursor_execute", observe_sql)
        session.commit()
    assert observations == [set(), {"companies", "company_memberships", "users", "teams"},
                            {"companies", "company_memberships", "users", "teams"}]


@pytest.mark.parametrize("kind", ["matter", "grant", "wall"])
def test_dependency_existence_is_tenant_qualified_on_postgres(team_fixture, kind):
    company_id, _actor_id, team_id, _member_id, _row_id = team_fixture
    factory = get_session_factory()
    with factory() as seed:
        other_company = _seed_company(seed)
        other_team = Team(company_id=other_company, name="Other tenant", slug="other-tenant")
        seed.add(other_team)
        seed.flush()
        other_team_id = other_team.id
        if kind == "matter":
            matter_id = _seed_matter(seed, other_company)
            seed.get(Matter, matter_id).team_id = other_team_id
        else:
            docket = IpDocketRecord(
                company_id=other_company, record_type="trademark", title="Other tenant target",
                status="active", is_active=True, restricted=False,
            )
            seed.add(docket)
            seed.flush()
            seed.add(_team_acl_dependency(
                kind, company_id=other_company, team_id=other_team_id,
                docket_id=docket.id, state="revoked",
            ))
        seed.commit()
    with factory() as read:
        assert teams._team_has_access_dependencies(
            read, company_id=other_company, team_id=other_team_id,
        )
        assert not teams._team_has_access_dependencies(read, company_id=company_id, team_id=team_id)
        assert not teams._team_has_access_dependencies(read, company_id=company_id, team_id=other_team_id)
        assert not teams._team_has_access_dependencies(read, company_id=other_company, team_id=team_id)


@pytest.mark.parametrize("kind", ["matter", "grant", "wall"])
def test_new_dependency_committed_before_team_lock_cannot_escape_recheck(team_fixture, kind):
    company_id, _actor_id, team_id, _member_id, row_id = team_fixture
    factory = get_session_factory()
    with factory() as seed:
        docket_id = _seed_unlinked_role_dockets(seed, team_fixture, count=1)[0]
        matter_id = _seed_matter(seed, company_id) if kind == "matter" else None
        seed.commit()

    ready = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool, factory() as holder:
        if kind == "matter":
            holder.get(Matter, matter_id).team_id = team_id
        else:
            # A valid raw fixture writer tests the Team FK boundary without an
            # actor Membership FK obscuring it. Production ACL writers also
            # serialize at Company. Revoked rows still count as dependencies.
            holder.add(_team_acl_dependency(
                kind, company_id=company_id, team_id=team_id,
                docket_id=docket_id, state="revoked",
            ))
        holder.flush()
        holder_pid = _pid(holder)
        future = pool.submit(_run_writer, factory, team_fixture, ready, "fenced_remove")
        try:
            _wait_on(
                holder.get_bind(), waiter=ready.get(timeout=5), holder=holder_pid,
                sql_fragment="for update of teams",
            )
            holder.commit()
        finally:
            holder.rollback()
            status, detail = future.result(timeout=12)
    assert status == 409
    assert detail["code"] == "ip_team_access_responsibility_changed"
    with factory() as read:
        assert read.get(TeamMembership, row_id) is not None
        assert teams._team_has_access_dependencies(read, company_id=company_id, team_id=team_id)
        assert read.scalar(select(func.count()).select_from(MatterTask).where(
            MatterTask.ip_docket_id == docket_id, MatterTask.status == "todo",
        )) == 1


def test_negative_dependency_exists_uses_real_indexes_amid_other_team_history(team_fixture, request):
    company_id, actor_id, team_id, _member_id, _row_id = team_fixture
    factory = get_session_factory()
    with factory() as seed:
        other_team = Team(company_id=company_id, name="History owner", slug="history-owner")
        seed.add(other_team)
        seed.flush()
        other_team_id = other_team.id
        docket = IpDocketRecord(
            company_id=company_id, record_type="trademark", title="History target",
            status="active", is_active=True, restricted=False, created_by_membership_id=actor_id,
        )
        seed.add(docket)
        seed.flush()
        now = datetime.now(UTC)
        seed.execute(insert(Matter), [
            {"id": str(uuid4()), "company_id": company_id, "team_id": other_team_id,
             "title": f"Other-team matter {index}", "matter_code": f"OTHER-{index}",
             "client_name": "Synthetic history", "status": "active", "practice_area": "commercial",
             "forum_level": "high_court", "is_active": True, "restricted_access": False}
            for index in range(_UNRELATED_DOCKET_COUNT)
        ])
        for model, subject in [(MatterAccessGrant, "team_id"), (EthicalWall, "excluded_team_id")]:
            seed.execute(insert(model), [
                {"id": str(uuid4()), "company_id": company_id, subject: other_team_id,
                 "ip_docket_id": docket.id, "effective_from": now - timedelta(days=2),
                 "revoked_at": now - timedelta(days=1), "reason": f"Retained history {index}"}
                for index in range(_UNRELATED_DOCKET_COUNT)
            ])
        seed.commit()

    plans = []
    with factory() as session:
        for model, subject in [(Matter, Matter.team_id), (MatterAccessGrant, MatterAccessGrant.team_id),
                               (EthicalWall, EthicalWall.excluded_team_id)]:
            assert session.scalar(select(func.count()).select_from(model).where(
                model.company_id == company_id, subject == other_team_id,
            )) == _UNRELATED_DOCKET_COUNT
        for table in ["matters", "matter_access_grants", "ethical_walls"]:
            session.execute(text(f"ANALYZE {table}"))

        statements = []

        def retain_statement(execute_state):
            if execute_state.is_select:
                statements.append(execute_state.statement)

        event.listen(session, "do_orm_execute", retain_statement)
        try:
            assert not teams._team_has_access_dependencies(session, company_id=company_id, team_id=team_id)
        finally:
            event.remove(session, "do_orm_execute", retain_statement)
        assert len(statements) == 3
        for statement, table, index in zip(
            statements, ["matters", "matter_access_grants", "ethical_walls"],
            ["ix_matters_team_id", "ix_matter_access_grants_team_id", "ix_ethical_walls_excluded_team_id"],
            strict=True,
        ):
            sql = str(statement.compile(
                dialect=session.get_bind().dialect, compile_kwargs={"literal_binds": True},
            ))
            plan = session.scalar(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"))
            plans.append(plan)
            nodes = []
            pending = [plan[0]["Plan"]]
            while pending:
                node = pending.pop()
                nodes.append(node)
                pending.extend(node.get("Plans", []))
            assert any(node.get("Index Name") == index for node in nodes), plan
            scans = [node for node in nodes if node.get("Relation Name") == table]
            assert scans, plan
            for scan in scans:
                assert scan["Node Type"] != "Seq Scan", plan
                assert scan["Actual Rows"] == 0, plan
                assert scan.get("Rows Removed by Filter", 0) == 0, plan
                assert scan.get("Rows Removed by Index Recheck", 0) == 0, plan
    # Retain real plan/buffer counters, including nonzero index-page reads.
    # Zero returned scan rows is not a claim of zero physical I/O.
    request.node.user_properties.append(("team_dependency_explain_plans", json.dumps(plans)))


def test_global_scoping_keeps_the_unfiltered_roleless_linked_parent_fence(team_fixture, monkeypatch):
    company_id, actor_id, _team_id, _member_id, _row_id = team_fixture
    factory = get_session_factory()
    with factory() as seed:
        matter_id = _seed_matter(seed, company_id)
        docket = IpDocketRecord(
            company_id=company_id, matter_id=matter_id, record_type="trademark",
            title="Roleless global fence", status="active", is_active=True, restricted=False,
            created_by_membership_id=actor_id,
        )
        seed.add(docket)
        seed.flush()
        docket_id = docket.id
        seed.commit()

    original_parents = teams._lock_ip_role_fence_parents
    locked = []

    def unexpected_probe(*args, **kwargs):
        pytest.fail("Global scoping enablement must not use a team-local shortcut.")

    def record_parents(session, **kwargs):
        assert kwargs.get("team_id") is None
        assert kwargs["include_empty"] is True and kwargs["linked_only"] is True
        assert kwargs["expected"] == {docket_id: teams._IpRoleFenceEntry(matter_id, ())}
        matters, dockets = original_parents(session, **kwargs)
        locked.append(([matter.id for matter in matters], [docket.id for docket in dockets]))
        return matters, dockets

    monkeypatch.setattr(teams, "_team_has_access_dependencies", unexpected_probe)
    monkeypatch.setattr(teams, "_lock_ip_role_fence_parents", record_parents)
    with factory() as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        assert teams.set_team_scoping(session, context=context, enabled=True) is True
        session.commit()
    assert locked == [([matter_id], [docket_id])]
    with factory() as read:
        assert read.get(Company, company_id).team_scoping_enabled is True
