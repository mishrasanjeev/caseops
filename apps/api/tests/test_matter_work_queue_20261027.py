"""Normal synthetic HTTP queue contracts; no native or provider acceptance."""

import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import DateTime, event, func, literal, select, union_all
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import CompileError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.sql.util import ClauseAdapter

from caseops_api.db import statement_clock
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    EthicalWall,
    Matter,
    MatterAccessGrant,
    MatterTask,
    MembershipRole,
    User,
)
from caseops_api.db.session import _proven_read_statement, get_engine, get_session_factory
from caseops_api.db.statement_clock import StatementUtc
from caseops_api.services import matter_work_queue as queue
from caseops_api.services.record_access_policy import visible_matters_filter
from caseops_api.services.session_context import SessionContext
from tests.sql_observation import is_read_only_select
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)

forbid_unadmitted_network = _forbid_unadmitted_network
BASE = "/api/matter-work-queue"
MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}
PASSWORD = "SyntheticQueuePass123!"
STAMP = datetime(2026, 10, 27, 1, 2, 3, tzinfo=UTC)


def uid(n):
    return str(UUID(int=n))


def boot(client):
    slug = "work-" + uuid4().hex[:10]
    result = client.post(
        "/api/bootstrap/company",
        headers=MARKER,
        json={
            "company_name": "Synthetic queue firm",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Synthetic owner",
            "owner_email": f"owner@{slug}.example.com",
            "owner_password": PASSWORD,
        },
    )
    assert result.status_code == 200, result.text
    auth = result.json()
    auth["headers"] = {**MARKER, "Authorization": "Bearer " + auth["access_token"]}
    current = client.get("/api/auth/me", headers=auth["headers"])
    assert current.status_code == 200, current.text
    assert current.json()["membership"]["id"] == auth["membership"]["id"]
    assert current.json()["membership"]["role"] == "owner"
    return auth


def employee(client, owner, role="member"):
    response = client.post(
        "/api/companies/current/users",
        headers=owner["headers"],
        json={
            "full_name": "Synthetic queue member",
            "email": f"member-{uuid4().hex}@queue.example.com",
            "password": PASSWORD,
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    member = response.json()
    login = client.post(
        "/api/auth/login",
        headers=MARKER,
        json={
            "company_slug": owner["company"]["slug"],
            "email": member["email"],
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200, login.text
    auth = login.json()
    auth["headers"] = {**MARKER, "Authorization": "Bearer " + auth["access_token"]}
    assert auth["membership"]["id"] == member["membership_id"]
    current = client.get("/api/auth/me", headers=auth["headers"])
    assert current.status_code == 200, current.text
    assert current.json()["membership"]["id"] == member["membership_id"]
    assert current.json()["membership"]["role"] == role
    return auth


def matter(client, owner):
    response = client.post(
        "/api/matters/",
        headers=owner["headers"],
        json={
            "title": "Queued Matter",
            "matter_code": "QUEUE-" + uuid4().hex[:10],
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Synthetic queue client",
            "opposing_party": "Synthetic respondent",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def task(
    client, owner, parent, assigned, *, due="2028-02-29", title="Recorded queue task", status="todo"
):
    response = client.post(
        f"/api/matters/{parent['id']}/tasks",
        headers=owner["headers"],
        json={
            "title": title,
            "description": "Not copied into the queue.",
            "owner_membership_id": assigned,
            "due_on": due,
            "status": status,
            "priority": "high",
            "expected_lifecycle_version": parent["lifecycle_version"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["id"] and body["matter_id"] == parent["id"] and body["owner_membership_id"] == assigned
    )
    return body


def team(client, owner, *members):
    response = client.post(
        "/api/teams/",
        headers=owner["headers"],
        json={
            "name": "Queue team",
            "slug": "queue-" + uuid4().hex[:8],
        },
    )
    assert response.status_code == 201, response.text
    value = response.json()
    for member in members:
        added = client.post(
            f"/api/teams/{value['id']}/members",
            headers=owner["headers"],
            json={"membership_id": member["membership"]["id"]},
        )
        assert added.status_code == 200, added.text
    return value


def setup(client, role="member"):
    owner = boot(client)
    actor = owner if role == "owner" else employee(client, owner, role)
    parent = matter(client, owner)
    return {"client": client, "owner": owner, "actor": actor, "matter": parent}


def get(case, **params):
    return case["client"].get(BASE, headers=case["actor"]["headers"], params=params)


def snapshot():
    with get_session_factory()() as session:
        return [
            dict(row)
            for row in session.execute(
                select(MatterTask.__table__).order_by(MatterTask.id)
            ).mappings()
        ]


def headers(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


def whole_response(client, role):
    case = setup(client, role)
    record = task(client, case["owner"], case["matter"], case["actor"]["membership"]["id"])
    before = snapshot()
    expected = {
        "scope": "matter_tasks",
        "ownership": "mine",
        "dates": "all",
        "due_from": None,
        "due_to": None,
        "sort": "due_on_created_at_id",
        "limit": 25,
        "next_cursor": None,
        "items": [
            {
                "id": record["id"],
                "title": "Recorded queue task",
                "status": "todo",
                "priority": "high",
                "due_on": "2028-02-29",
                "owner_membership_id": case["actor"]["membership"]["id"],
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
                "matter": {
                    k: case["matter"][k]
                    for k in (
                        "id",
                        "title",
                        "matter_code",
                        "status",
                        "is_active",
                        "lifecycle_version",
                    )
                },
            }
        ],
    }
    # Queue exposes known UTC instants explicitly, including SQLite persistence.
    for k in ("created_at", "updated_at"):
        value = datetime.fromisoformat(record[k].replace("Z", "+00:00"))
        expected["items"][0][k] = value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    statements = []

    def observe(_c, _u, sql, _p, context, _m):
        statements.append(
            (
                sql,
                is_read_only_select(getattr(getattr(context, "compiled", None), "statement", None)),
            )
        )

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        response = get(case)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert response.status_code == 200, response.text
    headers(response)
    assert response.json() == expected
    assert statements and len(statements) <= 16 and all(readonly for _, readonly in statements)
    assert get(case).json() == expected
    assert snapshot() == before


@pytest.mark.parametrize("role", [r.value for r in MembershipRole])
def test_complete_readonly_response_and_reload_for_every_current_tenant_role(client, role):
    whole_response(client, role)


def ownership(client):
    case = setup(client)
    peer, outsider = employee(client, case["owner"]), employee(client, case["owner"])
    team(client, case["owner"], case["actor"], peer)
    mine = task(client, case["owner"], case["matter"], case["actor"]["membership"]["id"])
    theirs = task(client, case["owner"], case["matter"], peer["membership"]["id"])
    task(client, case["owner"], case["matter"], outsider["membership"]["id"])
    free = task(client, case["owner"], case["matter"], None)
    before = snapshot()
    for mode, expected in (("mine", mine), ("team", theirs), ("unassigned", free)):
        response = get(case, ownership=mode)
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["items"]] == [expected["id"]]
    assert snapshot() == before


def test_mine_other_shared_active_team_and_unassigned_are_distinct_ownership_views(client):
    ownership(client)


def eligibility(client, change):
    assert change in {
        "actor_removed",
        "owner_removed",
        "team_inactive",
        "membership_inactive",
        "user_inactive",
        "foreign_owner",
    }
    case = setup(client)
    peer = employee(client, case["owner"])
    group = team(client, case["owner"], case["actor"], peer)
    record = task(client, case["owner"], case["matter"], peer["membership"]["id"])
    assert [r["id"] for r in get(case, ownership="team").json()["items"]] == [record["id"]]
    if change in {"actor_removed", "owner_removed"}:
        target = case["actor"] if change == "actor_removed" else peer
        response = client.delete(
            f"/api/teams/{group['id']}/members/{target['membership']['id']}",
            headers=case["owner"]["headers"],
        )
        assert response.status_code == 200, response.text
    elif change == "team_inactive":
        response = client.patch(
            f"/api/teams/{group['id']}", headers=case["owner"]["headers"], json={"is_active": False}
        )
        assert response.status_code == 200, response.text
    else:
        with get_session_factory()() as session:
            if change == "membership_inactive":
                session.get(CompanyMembership, peer["membership"]["id"]).is_active = False
            elif change == "user_inactive":
                session.get(User, peer["user"]["id"]).is_active = False
            else:
                foreign = boot(client)
                session.get(MatterTask, record["id"]).owner_membership_id = foreign["membership"][
                    "id"
                ]
            session.commit()
    before = snapshot()
    assert get(case, ownership="team").json()["items"] == []
    assert get(case, ownership="unassigned").json()["items"] == []
    assert snapshot() == before


@pytest.mark.parametrize(
    "change",
    [
        "actor_removed",
        "owner_removed",
        "team_inactive",
        "membership_inactive",
        "user_inactive",
        "foreign_owner",
    ],
)
def test_team_is_current_active_tenant_ownership_not_all_visible_work(client, change):
    eligibility(client, change)


def pagination(client, reverse):
    case = setup(client)
    ids = list(range(1, 34))
    if reverse:
        ids.reverse()
    with get_session_factory()() as session:
        for n in ids:
            session.add(
                MatterTask(
                    id="legacy-task-boundary" if n == 30 else uid(n),
                    company_id=case["owner"]["company"]["id"],
                    matter_id=case["matter"]["id"],
                    owner_membership_id=case["actor"]["membership"]["id"],
                    title=f"Retained task {n}",
                    due_on=None if n > 30 else date(2028, 2, 29),
                    status="todo",
                    priority="medium",
                    created_at=STAMP + timedelta(seconds=1 if n <= 5 else 0),
                    updated_at=STAMP,
                )
            )
        session.commit()
    before = snapshot()
    expected = [
        *[uid(n) for n in range(6, 30)],
        "legacy-task-boundary",
        *[uid(n) for n in [*range(1, 6), 31, 32, 33]],
    ]
    first = get(case, limit=25)
    assert first.status_code == 200, first.text
    one = first.json()
    assert [r["id"] for r in one["items"]] == expected[:25]
    assert isinstance(one["next_cursor"], str) and one["next_cursor"]
    assert case["matter"]["title"] not in one["next_cursor"]
    second = get(case, limit=25, cursor=one["next_cursor"])
    assert second.status_code == 200, second.text
    two = second.json()
    assert [r["id"] for r in two["items"]] == expected[25:]
    assert two["next_cursor"] is None
    assert len(set(r["id"] for r in one["items"] + two["items"])) == 33
    assert second.json() == get(case, limit=25, cursor=one["next_cursor"]).json()
    assert snapshot() == before


@pytest.mark.parametrize("reverse", [False, True])
def test_more_than25_due_created_id_membership_is_independent_of_physical_and_uuid_order(
    client, reverse
):
    pagination(client, reverse)


def date_views(client):
    case = setup(client)
    values = ["0001-01-01", "2028-02-29", "9999-12-31", None]
    records = [
        task(client, case["owner"], case["matter"], case["actor"]["membership"]["id"], due=d)
        for d in values
    ]
    for params, indexes in (
        ({}, [0, 1, 2, 3]),
        ({"dates": "dated"}, [0, 1, 2]),
        ({"dates": "undated"}, [3]),
        ({"dates": "dated", "due_from": "2028-02-29", "due_to": "2028-02-29"}, [1]),
    ):
        response = get(case, **params)
        assert response.status_code == 200, response.text
        assert [r["id"] for r in response.json()["items"]] == [records[n]["id"] for n in indexes]
        assert [r["due_on"] for r in response.json()["items"]] == [values[n] for n in indexes]
    for params in (
        {"dates": "all", "due_from": "2028-01-01"},
        {"dates": "undated", "due_to": "2028-01-01"},
        {"dates": "dated", "due_from": "2028-03-01", "due_to": "2028-02-29"},
        {"dates": "dated", "due_from": "2026-02-29"},
        {"dates": "dated", "due_from": "0"},
        {"limit": 26},
        {"ownership": "all"},
    ):
        response = get(case, **params)
        assert response.status_code == 422, response.text
        headers(response)


def test_calendar_date_only_past_future_and_undated_views_have_no_today_horizon(client):
    date_views(client)


def lifecycle(client):
    case = setup(client)
    row = task(client, case["owner"], case["matter"], case["actor"]["membership"]["id"])
    done = task(
        client, case["owner"], case["matter"], case["actor"]["membership"]["id"], status="completed"
    )
    assert [r["id"] for r in get(case).json()["items"]] == [row["id"]]
    for target in ("disposed", "intake"):
        current = client.get(
            f"/api/matters/{case['matter']['id']}/workspace", headers=case["owner"]["headers"]
        ).json()["matter"]
        changed = client.patch(
            f"/api/matters/{current['id']}/lifecycle/status",
            headers=case["owner"]["headers"],
            json={
                "to_status": target,
                "expected_from_status": current["status"],
                "expected_updated_at": current["updated_at"],
                "reason": "Owned queue lifecycle proof",
            },
        )
        assert changed.status_code == 200, changed.text
        assert get(case).json()["items"] == []
    with get_session_factory()() as session:
        assert session.get(MatterTask, row["id"]).cancelled_by_matter_disposal is True
        assert session.get(MatterTask, done["id"]).status == "completed"


def test_operational_sources_only_and_close_reopen_does_not_resurrect_retained_history(client):
    lifecycle(client)


def policy_cursor(client, boundary):
    assert boundary in {
        "wall",
        "restricted",
        "owner",
        "due",
        "completed",
        "lifecycle",
        "foreign_anchor",
    }
    case = setup(client)
    mode = "unassigned" if boundary in {"wall", "restricted"} else "mine"
    assigned = None if mode == "unassigned" else case["actor"]["membership"]["id"]
    for _ in range(3):
        task(client, case["owner"], case["matter"], assigned)
    page = get(case, limit=1, ownership=mode).json()
    first = page["items"][0]
    cursor = page["next_cursor"]
    assert cursor
    if boundary in {"wall", "restricted"}:
        path = "walls" if boundary == "wall" else "restricted"
        body = (
            {
                "excluded_membership_id": case["actor"]["membership"]["id"],
                "reason": "Queue policy proof",
            }
            if boundary == "wall"
            else {"restricted": True}
        )
        response = client.post(
            f"/api/matters/{case['matter']['id']}/access/{path}",
            headers=case["owner"]["headers"],
            json=body,
        )
        assert response.status_code == 200, response.text
    elif boundary == "lifecycle":
        current = client.get(
            f"/api/matters/{case['matter']['id']}/workspace", headers=case["owner"]["headers"]
        ).json()["matter"]
        response = client.patch(
            f"/api/matters/{current['id']}/lifecycle/status",
            headers=case["owner"]["headers"],
            json={
                "to_status": "disposed",
                "expected_from_status": current["status"],
                "expected_updated_at": current["updated_at"],
                "reason": "Queue cursor proof",
            },
        )
        assert response.status_code == 200, response.text
    else:
        foreign_record = None
        if boundary == "foreign_anchor":
            foreign = boot(client)
            foreign_parent = matter(client, foreign)
            foreign_record = task(client, foreign, foreign_parent, foreign["membership"]["id"])
        with get_session_factory()() as session:
            if boundary == "foreign_anchor":
                context = context_for(session, case["actor"])
                cursor = queue.encode_work_cursor(
                    context,
                    "mine",
                    "all",
                    1,
                    None,
                    None,
                    {
                        "id": foreign_record["id"],
                        "due_on": date(2028, 2, 29),
                        "created_at": datetime.fromisoformat(
                            foreign_record["created_at"].replace("Z", "+00:00")
                        ),
                    },
                )
            else:
                row = session.get(MatterTask, first["id"])
                if boundary == "owner":
                    row.owner_membership_id = None
                elif boundary == "due":
                    row.due_on = date(2029, 1, 1)
                else:
                    row.status = "completed"
                session.commit()
    before = snapshot()
    response = get(case, limit=1, ownership=mode, cursor=cursor)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "work_queue_cursor_stale"
    assert response.json()["detail"] == "Work or access changed. Reload the work queue."
    assert response.json()["title"] == "Conflict" and response.json()["status"] == 409
    if boundary == "foreign_anchor":
        assert foreign_record["id"] not in response.text
    headers(response)
    assert snapshot() == before


@pytest.mark.parametrize(
    "boundary", ["wall", "restricted", "owner", "due", "completed", "lifecycle", "foreign_anchor"]
)
def test_continuation_requires_current_policy_membership_lifecycle_and_exact_sort_anchor(
    client, boundary
):
    policy_cursor(client, boundary)


def context_for(session, auth):
    return SessionContext(
        company=session.get(Company, auth["company"]["id"]),
        membership=session.get(CompanyMembership, auth["membership"]["id"]),
        user=session.get(User, auth["user"]["id"]),
    )


def prebuilt_team(client):
    case = setup(client)
    peer = employee(client, case["owner"])
    group = team(client, case["owner"], case["actor"], peer)
    row = task(client, case["owner"], case["matter"], peer["membership"]["id"])
    with get_session_factory()() as session:
        statement = queue.work_queue_statement(
            session, context=context_for(session, case["actor"]), ownership="team", dates="all"
        )
        assert is_read_only_select(statement)
        started = queue._utc(session.scalar(select(StatementUtc())))
        assert [r["id"] for r in session.execute(statement).mappings()] == [row["id"]]
        transaction = session.get_transaction()
        assert transaction is not None
        if session.get_bind().dialect.name == "postgresql":
            assert session.connection().get_isolation_level() == "READ COMMITTED"
        else:
            # The canonical SQLite driver does not BEGIN a snapshot for SELECT.
            # Its SQLAlchemy Session transaction remains open and unchanged.
            assert session.connection().connection.driver_connection.in_transaction is False
        removed = client.delete(
            f"/api/teams/{group['id']}/members/{case['actor']['membership']['id']}",
            headers=case["owner"]["headers"],
        )
        assert removed.status_code == 200, removed.text
        assert list(session.execute(statement).mappings()) == []
        assert session.get_transaction() is transaction
        added = client.post(
            f"/api/teams/{group['id']}/members",
            headers=case["owner"]["headers"],
            json={"membership_id": case["actor"]["membership"]["id"]},
        )
        assert added.status_code == 200, added.text
        assert [r["id"] for r in session.execute(statement).mappings()] == [row["id"]]
        assert session.get_transaction() is transaction
        wall = client.post(
            f"/api/matters/{case['matter']['id']}/access/walls",
            headers=case["owner"]["headers"],
            json={
                "excluded_membership_id": case["actor"]["membership"]["id"],
                "reason": "Current queue wall",
            },
        )
        assert wall.status_code == 200, wall.text
        with get_session_factory()() as verify:
            stored_wall = verify.get(EthicalWall, wall.json()["id"])
            assert queue._utc(stored_wall.effective_from) > started
        assert session.get_transaction() is transaction
        assert list(session.execute(statement).mappings()) == []


def test_same_prebuilt_team_statement_reauthorizes_committed_team_and_wall_changes(client):
    prebuilt_team(client)


def grant_change(client):
    case = setup(client)
    record = task(client, case["owner"], case["matter"], None)
    restricted = client.post(
        f"/api/matters/{case['matter']['id']}/access/restricted",
        headers=case["owner"]["headers"],
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    with get_session_factory()() as session:
        statement = queue.work_queue_statement(
            session,
            context=context_for(session, case["actor"]),
            ownership="unassigned",
            dates="all",
        )
        started = queue._utc(session.scalar(select(StatementUtc())))
        assert list(session.execute(statement).mappings()) == []
        transaction = session.get_transaction()
        assert transaction is not None
        if session.get_bind().dialect.name == "postgresql":
            assert session.connection().get_isolation_level() == "READ COMMITTED"
        else:
            # The canonical SQLite driver does not BEGIN a snapshot for SELECT.
            # Its SQLAlchemy Session transaction remains open and unchanged.
            assert session.connection().connection.driver_connection.in_transaction is False
        grant = client.post(
            f"/api/matters/{case['matter']['id']}/access/grants",
            headers=case["owner"]["headers"],
            json={
                "membership_id": case["actor"]["membership"]["id"],
                "reason": "Queue current grant",
            },
        )
        assert grant.status_code == 200, grant.text
        with get_session_factory()() as verify:
            stored_grant = verify.get(MatterAccessGrant, grant.json()["id"])
            assert queue._utc(stored_grant.effective_from) > started
        assert session.get_transaction() is transaction
        assert [r["id"] for r in session.execute(statement).mappings()] == [record["id"]]
        assert session.get_transaction() is transaction
        revoke = client.delete(
            f"/api/matters/{case['matter']['id']}/access/grants/{grant.json()['id']}",
            headers=case["owner"]["headers"],
        )
        assert revoke.status_code == 204, revoke.text
        assert list(session.execute(statement).mappings()) == []


def test_same_prebuilt_statement_observes_grant_add_and_revocation(client):
    grant_change(client)


def excludes_ip(client):
    from tests.test_mobile_source_reads_20261027 import _docket

    case = setup(client)
    record = task(client, case["owner"], case["matter"], case["actor"]["membership"]["id"])
    with get_session_factory()() as session:
        docket_id = _docket(session, case["owner"])
        session.add(
            MatterTask(
                company_id=case["owner"]["company"]["id"],
                ip_docket_id=docket_id,
                owner_membership_id=case["actor"]["membership"]["id"],
                title="Separate IP work",
                status="todo",
                priority="medium",
                created_at=STAMP,
                updated_at=STAMP,
            )
        )
        session.commit()
    before = snapshot()
    assert len(before) == 2
    assert [r["id"] for r in get(case).json()["items"]] == [record["id"]]
    assert snapshot() == before


def test_ip_tasks_are_retained_but_not_presented_as_matter_work(client):
    excludes_ip(client)


def cursor_rules(client):
    case = setup(client)
    with get_session_factory()() as session:
        context = context_for(session, case["actor"])
        token = queue.encode_work_cursor(
            context,
            "mine",
            "all",
            1,
            None,
            None,
            {
                "id": uid(1),
                "due_on": None,
                "created_at": STAMP,
            },
            now=STAMP,
        )
        end = STAMP + timedelta(seconds=queue.CURSOR_TTL_SECONDS)
        assert queue.decode_work_cursor(
            token, context, "mine", "all", 1, None, None, now=end - timedelta(microseconds=1)
        )["id"] == uid(1)
        for moment in (end, end + timedelta(seconds=1), STAMP - timedelta(seconds=1)):
            with pytest.raises(HTTPException) as error:
                queue.decode_work_cursor(token, context, "mine", "all", 1, None, None, now=moment)
            assert error.value.status_code == 400
        for changes in ({"ownership": "team"}, {"dates": "dated"}, {"limit": 2}):
            args = {"ownership": "mine", "dates": "all", "limit": 1, **changes}
            with pytest.raises(HTTPException):
                queue.decode_work_cursor(token, context, **args, lower=None, upper=None, now=STAMP)
        body = json.loads(queue._cipher().decrypt(token.encode()))
        for key in ("company", "member", "user"):
            foreign = {**body, key: uid(999999)}
            altered = (
                queue._cipher()
                .encrypt_at_time(json.dumps(foreign).encode(), int(STAMP.timestamp()))
                .decode()
            )
            with pytest.raises(HTTPException):
                queue.decode_work_cursor(altered, context, "mine", "all", 1, None, None, now=STAMP)
        for change in (
            {"v": True},
            {"iat": True},
            {"id": ""},
            {"id": "x" * 37},
            {"id": "control\nidentity"},
            {"created": "2026-10-27"},
            {"extra": "PRIVATE_CURSOR_CONTENT"},
        ):
            altered = (
                queue._cipher()
                .encrypt_at_time(json.dumps({**body, **change}).encode(), int(STAMP.timestamp()))
                .decode()
            )
            with pytest.raises(HTTPException) as failure:
                queue.decode_work_cursor(altered, context, "mine", "all", 1, None, None, now=STAMP)
            assert "PRIVATE_CURSOR_CONTENT" not in str(failure.value.detail)
        for key in sorted(queue._FIELDS):
            incomplete = {k: v for k, v in body.items() if k != key}
            altered = (
                queue._cipher()
                .encrypt_at_time(json.dumps(incomplete).encode(), int(STAMP.timestamp()))
                .decode()
            )
            with pytest.raises(HTTPException):
                queue.decode_work_cursor(altered, context, "mine", "all", 1, None, None, now=STAMP)
        with pytest.raises(HTTPException):
            queue.decode_work_cursor(
                token[:-2] + "zz", context, "mine", "all", 1, None, None, now=STAMP
            )
    client.cookies.clear()
    unauthorized = client.get(BASE, headers=MARKER)
    assert unauthorized.status_code == 401
    headers(unauthorized)
    bad_cursor = get(case, cursor="PRIVATE_CURSOR_CONTENT")
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()["code"] == "work_queue_cursor_invalid"
    assert bad_cursor.json()["detail"] == "The work queue continuation is invalid or expired."
    assert "PRIVATE_CURSOR_CONTENT" not in bad_cursor.text
    headers(bad_cursor)
    missing = client.get(BASE + "/not-a-route", headers=case["actor"]["headers"])
    assert missing.status_code == 404
    headers(missing)


def test_cursor_local_clock_scope_signature_and_required_claims_without_auth_clock_patch(client):
    cursor_rules(client)


def retained_role_downgrade(client):
    owner = boot(client)
    parent = matter(client, owner)
    record = task(client, owner, parent, None)
    restricted = client.post(
        f"/api/matters/{parent['id']}/access/restricted",
        headers=owner["headers"],
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    with get_session_factory()() as reader:
        stale = context_for(reader, owner)
        statement = queue.work_queue_statement(
            reader, context=stale, ownership="unassigned", dates="all"
        )
        assert is_read_only_select(statement)
        assert [row["id"] for row in reader.execute(statement).mappings()] == [record["id"]]
        # Retain the request's observed role; no ORM refresh may mask the race.
        reader.expunge_all()
        reader.rollback()
        with Session(reader.get_bind()) as writer:
            actor = writer.get(CompanyMembership, owner["membership"]["id"])
            actor.role = MembershipRole.MEMBER
            writer.commit()
        assert list(reader.execute(statement).mappings()) == []
        reader.rollback()
        with pytest.raises(HTTPException) as rejected:
            queue.list_matter_work_queue(reader, context=stale, ownership="unassigned")
        assert rejected.value.status_code == 403
        assert rejected.value.detail == {
            "code": "work_queue_authority_changed",
            "message": "Workspace access changed. Reload your account.",
        }
        reader.rollback()
        fresh = context_for(reader, owner)
        assert fresh.membership.role == MembershipRole.MEMBER
        assert (
            queue.list_matter_work_queue(reader, context=fresh, ownership="unassigned").items == []
        )
    assert snapshot()[0]["id"] == record["id"]


def test_retained_owner_statement_and_endpoint_refuse_committed_role_downgrade(client):
    retained_role_downgrade(client)


def test_typed_statement_clock_compilers_and_read_guard_are_closed():
    statement = select(StatementUtc(), StatementUtc()._annotate({"clock": "reviewed"}))
    assert is_read_only_select(statement)
    assert _proven_read_statement(statement)
    postgres_sql = str(statement.compile(dialect=postgresql.dialect()))
    assert postgres_sql.count("statement_timestamp()") == 2
    assert "now()" not in postgres_sql
    sqlite_compiled = statement.compile(dialect=sqlite.dialect())
    assert len([x for x in sqlite_compiled.bind_names if x.key == "_caseops_statement_utc"]) == 1
    assert "CURRENT_TIMESTAMP" not in str(sqlite_compiled)
    assert "strftime" not in str(sqlite_compiled)
    assert not _proven_read_statement(select(func.caseops_statement_utc("unreviewed")))
    assert not _proven_read_statement(select(func.caseops_statement_utc()))
    with pytest.raises(CompileError, match="only PostgreSQL and SQLite"):
        str(statement)


def test_canonical_sqlite_clock_is_one_execution_bind_across_cache_adapters_and_interleaved_cursors(
    tmp_path, monkeypatch
):
    engine = get_engine(f"sqlite+pysqlite:///{(tmp_path / 'statement-clock.sqlite').as_posix()}")
    assert engine.dialect.name == "sqlite"
    edge = datetime(2028, 2, 29, 1, 2, 3, 123456, tzinfo=UTC)
    calls = []

    def clock():
        value = edge + timedelta(microseconds=len(calls))
        calls.append(value)
        return value

    monkeypatch.setattr(statement_clock, "_utc_now", clock)
    adapted = ClauseAdapter(Matter.__table__.alias()).traverse(StatementUtc())
    statement = union_all(
        select(StatementUtc().label("clock"), literal(1).label("row")),
        select(adapted, literal(2)),
        select(StatementUtc(), literal(3)),
    )
    assert is_read_only_select(statement) and _proven_read_statement(statement)
    observed = []

    def capture(_connection, _cursor, sql, _params, _context, _many):
        observed.append(sql)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with engine.connect() as first, engine.connect() as second:
            assert first.connection.driver_connection is not second.connection.driver_connection
            cursor = first.execute(statement)
            first_row = cursor.fetchone()
            assert len(calls) == 1
            assert queue._utc(first_row.clock) == edge
            # A second cursor on the SAME connection cannot change bound values
            # in the first cursor, unlike a mutable per-connection UDF clock.
            same_connection = first.execute(statement).all()
            other_connection = second.execute(statement).all()
            assert len(calls) == 3
            assert {queue._utc(row.clock) for row in same_connection} == {
                edge + timedelta(microseconds=1)
            }
            assert {queue._utc(row.clock) for row in other_connection} == {
                edge + timedelta(microseconds=2)
            }
            assert {queue._utc(row.clock) for row in cursor.fetchall()} == {edge}
            assert len(observed) == 3
            monkeypatch.setattr(statement_clock, "_utc_now", lambda: edge.replace(tzinfo=None))
            with pytest.raises(StatementError) as refused:
                first.execute(statement)
            assert isinstance(refused.value.orig, ValueError)
            assert len(observed) == 3  # No fallback timestamp or SQL dispatch.
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def temporal_boundary(client, kind, edge_kind, delta):
    case = setup(client)
    row = task(client, case["owner"], case["matter"], case["actor"]["membership"]["id"])
    if kind == "grant":
        response = client.post(
            f"/api/matters/{case['matter']['id']}/access/restricted",
            headers=case["owner"]["headers"],
            json={"restricted": True},
        )
        assert response.status_code == 200, response.text
    response = client.post(
        f"/api/matters/{case['matter']['id']}/access/{'grants' if kind == 'grant' else 'walls'}",
        headers=case["owner"]["headers"],
        json={
            "membership_id" if kind == "grant" else "excluded_membership_id": case["actor"][
                "membership"
            ]["id"],
            "reason": "Synthetic exact temporal window",
        },
    )
    assert response.status_code == 200, response.text
    edge = datetime(2028, 2, 29, 1, 2, 3, 123456, tzinfo=UTC)
    lower = edge if edge_kind == "effective" else edge - timedelta(days=1)
    upper = edge if edge_kind == "expiry" else edge + timedelta(days=1)
    model = MatterAccessGrant if kind == "grant" else EthicalWall
    # These window columns are retained storage, absent from the simple Matter
    # grant/wall DTO. Change only this normal-API-created owned fixture row.
    with get_session_factory()() as writer:
        retained = writer.get(model, response.json()["id"])
        retained.effective_from, retained.expires_at = lower, upper
        writer.commit()
    moment = edge + timedelta(microseconds=delta)
    with get_session_factory()() as reader:
        current = context_for(reader, case["actor"])
        predicate = visible_matters_filter(
            reader,
            context=current,
            statement_time=literal(moment, type_=DateTime(timezone=True)),
        )
        statement = (
            select(MatterTask.id)
            .join(Matter, Matter.id == MatterTask.matter_id)
            .where(
                MatterTask.id == row["id"],
                MatterTask.company_id == current.company.id,
                Matter.company_id == current.company.id,
                predicate,
            )
        )
        assert is_read_only_select(statement) and _proven_read_statement(statement)
        active = lower <= moment < upper
        allowed = active if kind == "grant" else not active
        assert list(reader.scalars(statement)) == ([row["id"]] if allowed else [])
        persisted = reader.get(model, response.json()["id"])
        assert queue._utc(persisted.effective_from) == lower
        assert queue._utc(persisted.expires_at) == upper
        with pytest.raises(TypeError, match="typed DateTime"):
            visible_matters_filter(reader, context=current, statement_time=moment)


@pytest.mark.parametrize("kind", ["grant", "wall"])
@pytest.mark.parametrize("edge_kind", ["effective", "expiry"])
@pytest.mark.parametrize(
    "delta", [-1, 0, 1], ids=["one-microsecond-before", "exact", "one-microsecond-after"]
)
def test_policy_typed_temporal_boundaries_preserve_exact_microseconds(
    client, kind, edge_kind, delta
):
    temporal_boundary(client, kind, edge_kind, delta)
