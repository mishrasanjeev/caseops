"""Actual FK/statement-snapshot/name races; no mocked locking or provider calls."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects import postgresql

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    CounselReadPageDirty,
    Matter,
    MatterOutsideCounselAssignment,
    OutsideCounsel,
    OutsideCounselSpendRecord,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.counsel_read_pages import counsel_page_statement
from tests.sql_observation import is_read_only_select
from tests.test_counsel_read_pages_20261027 import (
    case_for,
    exercise_current_names_and_foreign_actor,
    exercise_move_parent_and_cursor,
    exercise_old_source_crud,
    exercise_rollback,
    exercise_wide_old_note,
    immutable_side_effects,
    require_dense,
)
from tests.test_counsel_read_pages_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)
from tests.test_matter_counsel_context_20261027 import get, uid
from tests.test_matter_counsel_context_20261027_postgres import _nodes
from tests.test_outside_counsel import _create_matter

forbid_unadmitted_network = _forbid_unadmitted_network

pytestmark = pytest.mark.postgres


def test_postgres_old_column_dense_crud(isolated_postgres_client):
    exercise_old_source_crud(isolated_postgres_client)


def test_postgres_wide_note_remains_native_text(isolated_postgres_client):
    exercise_wide_old_note(isolated_postgres_client)


def test_postgres_current_names_foreign_owner_null(isolated_postgres_client):
    exercise_current_names_and_foreign_actor(isolated_postgres_client)


def test_postgres_rollback_preserves_source_projection_audit_outbox(isolated_postgres_client):
    exercise_rollback(isolated_postgres_client)


def test_postgres_parent_move_and_stale_source_anchor(isolated_postgres_client):
    exercise_move_parent_and_cursor(isolated_postgres_client)


def copied_source(model, source_id, **changes):
    with get_engine().connect() as connection:
        row = dict(
            connection.execute(select(model.__table__).where(model.id == source_id))
            .mappings()
            .one()
        )
    return {**row, **changes}


def begin(connection):
    connection.begin()
    connection.execute(text("SET LOCAL lock_timeout='5s'"))
    connection.execute(text("SET LOCAL statement_timeout='5s'"))
    return connection.scalar(text("SELECT pg_backend_pid()"))


def worker_insert(model, row, identity, entered):
    with get_engine().connect() as connection:
        identity["pid"] = begin(connection)
        entered.set()
        connection.execute(insert(model.__table__), row)
        connection.commit()


def entered_or_exception(entered, future):
    if entered.wait(3):
        return
    if future.done():
        future.result()
    raise AssertionError("Old-column writer did not reach the bounded admitted connection")


def require_blocker(waiter, holder, future):
    # The final EXISTING snapshot is checked before the deadline test. A pending
    # future's exception is not hidden behind a barrier timeout/executor exit.
    deadline = monotonic() + 3
    observations = 0
    last = []
    with get_engine().connect() as observer:
        while observations < 100:
            last = observer.scalar(text("SELECT pg_blocking_pids(:waiter)"), {"waiter": waiter})
            observations += 1
            if holder in last:
                return
            if future.done():
                future.result()
                raise AssertionError("Writer completed without the required directed lock edge")
            if monotonic() >= deadline:
                break
            sleep(0.01)
    raise AssertionError(
        f"Required waiter/holder edge absent after{observations} bounded snapshots; last={last}"
    )


@pytest.mark.parametrize("change", ("name", "company"))
def test_existing_counsel_key_fence_admits_new_parent_after_current_profile(
    isolated_postgres_client,
    change,
):
    client = isolated_postgres_client
    case = case_for(client, 1)
    other = _create_matter(
        client,
        case["auth"]["access_token"],
        title="New profile race Matter",
        matter_code="OC-NEW-PROFILE",
    )
    row = copied_source(MatterOutsideCounselAssignment, uid(1), id=uid(7001), matter_id=other["id"])
    replacement = {"name": "Current committed counsel"}
    if change == "company":
        with get_session_factory()() as session:
            foreign = Company(
                name="Foreign profile",
                slug="foreign-profile-race",
                tenant_key="foreign-profile-race",
                company_type="law_firm",
            )
            session.add(foreign)
            session.flush()
            foreign_id = foreign.id
            session.commit()
        replacement = {"company_id": foreign_id}
    before = immutable_side_effects()
    entered = Event()
    identity = {}
    with get_engine().connect() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        holder = begin(writer)
        writer.execute(
            update(OutsideCounsel).where(OutsideCounsel.id == uid(10001)).values(**replacement)
        )
        future = pool.submit(worker_insert, MatterOutsideCounselAssignment, row, identity, entered)
        try:
            entered_or_exception(entered, future)
            require_blocker(identity["pid"], holder, future)
        finally:
            writer.commit()
        future.result(timeout=5)
    current = {
        **case,
        "matter": other,
        "url": f"/api/outside-counsel/matters/{other['id']}/context",
    }
    response = get(current)
    assert response.status_code == 200, response.text
    if change == "name":
        assert [(r["id"], r["counsel_name"]) for r in response.json()["assignments"]] == [
            (uid(7001), "Current committed counsel")
        ]
        require_dense(current, [uid(7001)], "assignment")
    else:
        assert response.json()["assignments"] == []
        require_dense(current, [], "assignment")
        with get_engine().connect() as connection:
            assert connection.scalar(
                select(MatterOutsideCounselAssignment.id).where(
                    MatterOutsideCounselAssignment.id == uid(7001)
                )
            ) == uid(7001)
    assert immutable_side_effects() == before


@pytest.mark.parametrize("change", ("user", "company"))
def test_existing_membership_key_fence_and_foreign_null_in_new_parent(
    isolated_postgres_client,
    change,
):
    client = isolated_postgres_client
    case = case_for(client, 1)
    other = _create_matter(
        client,
        case["auth"]["access_token"],
        title="New membership race Matter",
        matter_code="OC-NEW-ACTOR",
    )
    with get_session_factory()() as session:
        one = User(
            email="actor-one@example.com",
            full_name="Original actor",
            password_hash="synthetic-unusable",
        )
        two = User(
            email="actor-two@example.com",
            full_name="Current replacement actor",
            password_hash="synthetic-unusable",
        )
        foreign = Company(
            name="Foreign actor",
            slug="foreign-actor-race",
            tenant_key="foreign-actor-race",
            company_type="law_firm",
        )
        session.add_all([one, two, foreign])
        session.flush()
        actor = CompanyMembership(
            company_id=case["auth"]["company"]["id"], user_id=one.id, role="viewer", is_active=True
        )
        session.add(actor)
        session.flush()
        actor_id = actor.id
        two_id = two.id
        foreign_id = foreign.id
        session.commit()
    row = copied_source(
        MatterOutsideCounselAssignment,
        uid(1),
        id=uid(7002),
        matter_id=other["id"],
        assigned_by_membership_id=actor_id,
    )
    replacement = {"user_id": two_id} if change == "user" else {"company_id": foreign_id}
    entered = Event()
    identity = {}
    before = immutable_side_effects()
    with get_engine().connect() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        holder = begin(writer)
        writer.execute(
            update(CompanyMembership).where(CompanyMembership.id == actor_id).values(**replacement)
        )
        future = pool.submit(worker_insert, MatterOutsideCounselAssignment, row, identity, entered)
        try:
            entered_or_exception(entered, future)
            require_blocker(identity["pid"], holder, future)
        finally:
            writer.commit()
        future.result(timeout=5)
    current = {
        **case,
        "matter": other,
        "url": f"/api/outside-counsel/matters/{other['id']}/context",
    }
    response = get(current)
    assert response.status_code == 200, response.text
    assert response.json()["assignments"][0]["assigned_by_name"] == (
        "Current replacement actor" if change == "user" else None
    )
    assert immutable_side_effects() == before


def test_user_name_commit_cannot_miss_concurrent_new_parent(isolated_postgres_client):
    client = isolated_postgres_client
    case = case_for(client, 1)
    other = _create_matter(
        client,
        case["auth"]["access_token"],
        title="New User-name Matter",
        matter_code="OC-NEW-USER-NAME",
    )
    with get_engine().connect() as connection:
        user_id = connection.scalar(
            select(CompanyMembership.user_id).where(
                CompanyMembership.id == case["auth"]["membership"]["id"]
            )
        )
    row = copied_source(MatterOutsideCounselAssignment, uid(1), id=uid(7003), matter_id=other["id"])
    entered = Event()
    identity = {}
    before = immutable_side_effects()
    current = {
        **case,
        "matter": other,
        "url": f"/api/outside-counsel/matters/{other['id']}/context",
    }
    with get_engine().connect() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        begin(writer)
        writer.execute(
            update(User)
            .where(User.id == user_id)
            .values(full_name="Current independently served User name")
        )
        future = pool.submit(worker_insert, MatterOutsideCounselAssignment, row, identity, entered)
        try:
            entered_or_exception(entered, future)
            # Admission intentionally completes BEFORE the unrelated User name
            # commit. No synthetic User SHARE or forced profile→Matter lock.
            future.result(timeout=3)
            response = get(current)
            assert response.status_code == 200, response.text
            assert response.json()["assignments"][0]["assigned_by_name"] == "Sanjay Mishra"
        finally:
            writer.commit()
    response = get(current)
    assert response.status_code == 200, response.text
    assert (
        response.json()["assignments"][0]["assigned_by_name"]
        == "Current independently served User name"
    )
    assert (
        get(case).json()["assignments"][0]["assigned_by_name"]
        == "Current independently served User name"
    )
    assert immutable_side_effects() == before


def test_waited_same_parent_finalizer_includes_committed_peer(isolated_postgres_client):
    case = case_for(isolated_postgres_client, 1)
    first = copied_source(OutsideCounselSpendRecord, uid(20001), id=uid(70001), amount_minor=7)
    second = copied_source(OutsideCounselSpendRecord, uid(20001), id=uid(70002), amount_minor=11)
    entered = Event()
    identity = {}
    before = immutable_side_effects()
    with get_engine().connect() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        holder = begin(writer)
        writer.execute(insert(OutsideCounselSpendRecord.__table__), first)
        # Represent the commit-stage gate only AFTER this writer's source/FKs.
        # The second commit must wait, then rebuild from a fresh statement
        # snapshot that includes the first committed source row.
        writer.execute(text("SELECT pg_advisory_xact_lock(1145393713,0)"))
        future = pool.submit(worker_insert, OutsideCounselSpendRecord, second, identity, entered)
        try:
            entered_or_exception(entered, future)
            require_blocker(identity["pid"], holder, future)
        finally:
            writer.commit()
        future.result(timeout=5)
    response = get(case)
    assert response.status_code == 200, response.text
    assert [
        (r["id"], r["amount_minor"], r["pending_amount_minor"])
        for r in response.json()["spend_records"]
    ] == [(uid(20001), 3, 2), (uid(70001), 7, 6), (uid(70002), 11, 10)]
    require_dense(case, [uid(20001), uid(70001), uid(70002)], "spend")
    assert immutable_side_effects() == before


def test_profile_rebuild_does_not_request_preheld_matter_lock(isolated_postgres_client):
    case = case_for(isolated_postgres_client, 1)
    # The actual Matter lock exists before a profile update rebuilds that same
    # parent. The old parent-FK/FOR UPDATE design would block here, not pass.
    with get_engine().connect() as parent, ThreadPoolExecutor(max_workers=1) as pool:
        holder = begin(parent)
        parent.execute(
            select(Matter.id).where(Matter.id == case["matter"]["id"]).with_for_update()
        ).scalar_one()

        def rename():
            with get_engine().connect() as connection:
                begin(connection)
                connection.execute(
                    update(OutsideCounsel)
                    .where(OutsideCounsel.id == uid(10001))
                    .values(name="No Matter lock inversion")
                )
                connection.commit()

        future = pool.submit(rename)
        try:
            future.result(timeout=3)
        finally:
            parent.rollback()
    assert holder > 0
    assert get(case).json()["assignments"][0]["counsel_name"] == "No Matter lock inversion"


@pytest.mark.parametrize("cost", ("default", "adverse"))
@pytest.mark.parametrize("insertion_order", ("forward", "reverse"))
def test_unassociated_users_do_not_expand_serving_work(
    isolated_postgres_client,
    cost,
    insertion_order,
    tmp_path,
):
    case = case_for(isolated_postgres_client, 28)
    order = list(range(800))
    if insertion_order == "reverse":
        order.reverse()
    with get_session_factory()() as session:
        before = session.scalar(select(func.count()).select_from(User))
        session.add_all(
            [
                User(
                    id=uid(100000 + n),
                    email=f"directory-{n}@example.com",
                    full_name=f"Unassociated synthetic name {n}",
                    password_hash="synthetic-unusable",
                )
                for n in order
            ]
        )
        session.commit()
        user_count = session.scalar(select(func.count()).select_from(User))
        assert user_count == before + 800
        assert session.scalar(select(func.count()).select_from(CounselReadPageDirty)) == 0
    plans = []
    violations = []
    with get_session_factory()() as session:
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        if cost == "adverse":
            session.execute(text("SET LOCAL random_page_cost=100"))
        for model, offset in (
            (MatterOutsideCounselAssignment, 0),
            (OutsideCounselSpendRecord, 20000),
        ):
            statement = counsel_page_statement(
                model,
                company_id=case["auth"]["company"]["id"],
                matter_id=case["matter"]["id"],
                after=uid(offset + 1),
                limit=25,
            )
            assert is_read_only_select(statement)
            sql = str(
                statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
            payload = session.execute(
                text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
            ).scalar_one()
            plans.append(payload)
            (
                tmp_path / f"{model.__tablename__}-directory-{insertion_order}-{cost}.json"
            ).write_text(json.dumps(payload, indent=2))
            nodes = list(_nodes(payload[0]["Plan"]))
            charge = sum(
                (
                    n.get("Actual Rows", 0)
                    + n.get("Rows Removed by Filter", 0)
                    + n.get("Rows Removed by Join Filter", 0)
                    + n.get("Rows Removed by Index Recheck", 0)
                )
                * n.get("Actual Loops", 1)
                for n in nodes
            )
            if charge > 400:
                violations.append((model.__tablename__, charge, payload))
            assert {n["Relation Name"] for n in nodes if "Relation Name" in n} <= {
                "counsel_read_pages",
                "counsel_read_page_dirty",
                model.__tablename__,
                "outside_counsel",
                "company_memberships",
                "users",
            }
            assert not any(
                n.get("Actual Loops", 0) > 0
                and n.get("Relation Name")
                in {
                    model.__tablename__,
                    "outside_counsel",
                    "company_memberships",
                    "users",
                }
                for n in nodes
            )
            actual = list(session.execute(statement).mappings())
            assert [r["source_payload"]["id"] for r in actual] == [
                uid(offset + n) for n in range(2, 28)
            ]
            assert all(r["actor_name"] == "Sanjay Mishra" for r in actual)
        session.rollback()
    assert len(plans) == 2
    assert not violations, json.dumps(violations)


@pytest.mark.parametrize("change", ("source", "profile", "user"))
def test_retained_select_observes_own_later_write_before_commit_and_rollback(
    isolated_postgres_client,
    change,
):
    case = case_for(isolated_postgres_client, 1)
    statement = counsel_page_statement(
        MatterOutsideCounselAssignment,
        company_id=case["auth"]["company"]["id"],
        matter_id=case["matter"]["id"],
        after=None,
        limit=25,
    )
    before = immutable_side_effects()
    with get_engine().connect() as connection:
        begin(connection)
        initial = list(connection.execute(statement).mappings())
        assert initial[0]["source_payload"]["counsel_name"] == "Scoped counsel 1"
        if change == "source":
            connection.execute(
                update(MatterOutsideCounselAssignment)
                .where(MatterOutsideCounselAssignment.id == uid(1))
                .values(internal_notes="Current uncommitted own note")
            )
        elif change == "profile":
            connection.execute(
                update(OutsideCounsel)
                .where(OutsideCounsel.id == uid(10001))
                .values(name="Current uncommitted own profile")
            )
        else:
            user_id = connection.scalar(
                select(CompanyMembership.user_id).where(
                    CompanyMembership.id == case["auth"]["membership"]["id"]
                )
            )
            connection.execute(
                update(User)
                .where(User.id == user_id)
                .values(full_name="Current uncommitted own User name")
            )
        assert connection.scalar(select(func.count()).select_from(CounselReadPageDirty)) > 0
        current = list(connection.execute(statement).mappings())
        if change == "source":
            assert current[0]["source_note"] == "Current uncommitted own note"
        elif change == "profile":
            assert current[0]["source_payload"]["counsel_name"] == "Current uncommitted own profile"
        else:
            assert current[0]["actor_name"] == "Current uncommitted own User name"
        outside = get(case)
        assert outside.status_code == 200
        assert outside.json()["assignments"][0]["counsel_name"] == "Scoped counsel 1"
        assert outside.json()["assignments"][0]["internal_notes"] is None
        connection.rollback()
        assert list(connection.execute(statement).mappings()) == initial
        connection.rollback()
    assert immutable_side_effects() == before


def test_canonical_membership_update_finishes_before_spend_audit_fk_tail(
    isolated_postgres_client,
    tmp_path,
):
    from asyncio import get_running_loop
    from contextlib import closing
    from threading import get_ident

    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from tests.test_outside_counsel import _invite_admin

    client = isolated_postgres_client
    case = case_for(client, 2)
    admin_id, admin_token = _invite_admin(client, case["auth"]["access_token"])
    client.cookies.clear()  # Each supplied normal Bearer principal is isolated.
    with get_engine().begin() as connection:
        connection.execute(
            update(MatterOutsideCounselAssignment)
            .where(MatterOutsideCounselAssignment.id == uid(2))
            .values(assigned_by_membership_id=admin_id)
        )
    source_flushed, release = Event(), Event()
    engine = get_engine()
    entries = {"spend": [], "membership": []}

    def entry(connection):
        return {
            "thread": get_ident(),
            "eventLoop": id(get_running_loop()),
            "backendPid": connection.connection.driver_connection.info.backend_pid,
        }

    def pause_source_tail(_conn, _cursor, sql, _params, context, _many):
        statement = getattr(getattr(context, "compiled", None), "statement", None)
        table = getattr(getattr(statement, "table", None), "name", None)
        if getattr(statement, "is_update", False) and table == "company_memberships":
            entries["membership"].append(entry(_conn))
        if getattr(statement, "is_update", False) and table == "outside_counsel_spend_records":
            entries["spend"].append(entry(_conn))
            source_flushed.set()
            assert release.wait(3), "canonical source/audit tail was not released"

    event.listen(engine, "after_cursor_execute", pause_source_tail)
    try:
        # The primary fixture owns the one application lifespan. Reusing its
        # context-managed TestClient would block both async handlers on the
        # SAME portal while this synchronous SQL callback waits for release.
        # An unentered peer creates its own per-request portal, without a second
        # lifespan. Its credentials, cookies and no-paid admission stay explicit.
        with (
            closing(
                TestClient(
                    client.app,
                    headers={"X-CaseOps-Automated-Test": "no-paid-providers"},
                )
            ) as worker,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            assert worker.portal is None and not worker.cookies
            future = pool.submit(
                worker.patch,
                f"/api/outside-counsel/spend-records/{uid(20001)}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"notes": "Canonical audit tail candidate"},
            )
            try:
                entered_or_exception(source_flushed, future)
                response = client.patch(
                    f"/api/companies/current/users/{admin_id}",
                    headers=case["headers"],
                    json={"role": "member"},
                )
                assert response.status_code == 200, response.text
            finally:
                release.set()
            result = future.result(timeout=5)
            assert result.status_code == 200, result.text
            assert worker.portal is None
    finally:
        event.remove(engine, "after_cursor_execute", pause_source_tail)
        release.set()
    assert len(entries["spend"]) == len(entries["membership"]) == 1
    for key in ("thread", "eventLoop", "backendPid"):
        assert entries["spend"][0][key] != entries["membership"][0][key]
    (tmp_path / "canonical-independent-worker-entries.json").write_text(
        json.dumps(entries, indent=2) + "\n"
    )
    with get_engine().connect() as connection:
        assert (
            connection.scalar(
                select(CompanyMembership.role).where(CompanyMembership.id == admin_id)
            )
            == "member"
        )
        assert (
            connection.scalar(
                select(OutsideCounselSpendRecord.notes).where(
                    OutsideCounselSpendRecord.id == uid(20001)
                )
            )
            == "Canonical audit tail candidate"
        )
        assert connection.scalar(select(func.count()).select_from(CounselReadPageDirty)) == 0


def test_old_multistatement_source_writer_finishes_before_waiting_profile_finalizer(
    isolated_postgres_client,
):
    case = case_for(isolated_postgres_client, 2)
    second = copied_source(OutsideCounselSpendRecord, uid(20002), id=uid(79002))
    entered, release = Event(), Event()
    with get_engine().connect() as source, ThreadPoolExecutor(max_workers=1) as pool:
        source_pid = begin(source)
        source.execute(
            update(OutsideCounselSpendRecord)
            .where(OutsideCounselSpendRecord.id == uid(20001))
            .values(notes="First old-column statement")
        )

        def rename_then_commit(identity):
            with get_engine().connect() as profile:
                identity["pid"] = begin(profile)
                profile.execute(
                    update(OutsideCounsel)
                    .where(OutsideCounsel.id == uid(10002))
                    .values(name="After multi-statement writer")
                )
                entered.set()
                assert release.wait(3)
                profile.commit()

        identity = {}
        future = pool.submit(rename_then_commit, identity)
        try:
            entered_or_exception(entered, future)
            # Profile has its existing unique-key UPDATE lock, but NO CPG lock.
            # Release its commit; our next source statement waits on its FK,
            # not while holding a projection lock that the profile needs.
            release.set()
            source.execute(insert(OutsideCounselSpendRecord.__table__), second)
            source.commit()
            future.result(timeout=5)
        finally:
            release.set()
            source.rollback()
    assert source_pid > 0
    response = get(case)
    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["spend_records"] if r["id"] == uid(79002))
    assert row["counsel_name"] == "After multi-statement writer"
    assert row["notes"] is None
    require_dense(case, [uid(20001), uid(20002), uid(79002)], "spend")


def test_user_commit_before_uncommitted_new_parent_source_is_seen_by_later_finalizer(
    isolated_postgres_client,
):
    case = case_for(isolated_postgres_client, 1)
    other = _create_matter(
        isolated_postgres_client,
        case["auth"]["access_token"],
        title="User commits first",
        matter_code="OC-USER-FIRST",
    )
    row = copied_source(
        MatterOutsideCounselAssignment, uid(1), id=uid(79003), matter_id=other["id"]
    )
    inserted, release = Event(), Event()

    def staged_source():
        with get_engine().connect() as connection:
            begin(connection)
            connection.execute(insert(MatterOutsideCounselAssignment.__table__), row)
            inserted.set()
            assert release.wait(3)
            connection.commit()

    with get_engine().connect() as profile, ThreadPoolExecutor(max_workers=1) as pool:
        begin(profile)
        user_id = profile.scalar(
            select(CompanyMembership.user_id).where(
                CompanyMembership.id == case["auth"]["membership"]["id"]
            )
        )
        profile.execute(
            update(User)
            .where(User.id == user_id)
            .values(full_name="User committed before source finalization")
        )
        future = pool.submit(staged_source)
        try:
            entered_or_exception(inserted, future)
            # The new source is not visible to profile scope expansion yet.
            profile.commit()
        finally:
            release.set()
        future.result(timeout=5)
    current = {
        **case,
        "matter": other,
        "url": f"/api/outside-counsel/matters/{other['id']}/context",
    }
    response = get(current)
    assert response.status_code == 200, response.text
    assert [(r["id"], r["assigned_by_name"]) for r in response.json()["assignments"]] == [
        (uid(79003), "User committed before source finalization")
    ]
    assert get(case).json()["assignments"][0]["assigned_by_name"] == (
        "User committed before source finalization"
    )
    require_dense(current, [uid(79003)], "assignment")


def test_waited_user_finalizer_expands_new_parent_after_source_commits(
    isolated_postgres_client,
):
    case = case_for(isolated_postgres_client, 1)
    other = _create_matter(
        isolated_postgres_client,
        case["auth"]["access_token"],
        title="Source commits before waited User",
        matter_code="OC-WAITED-USER",
    )
    row = copied_source(
        MatterOutsideCounselAssignment, uid(1), id=uid(79004), matter_id=other["id"]
    )
    source_ready, user_ready, release = Event(), Event(), Event()
    identities = {}
    with get_engine().connect() as observer:
        user_id = observer.scalar(
            select(CompanyMembership.user_id).where(
                CompanyMembership.id == case["auth"]["membership"]["id"]
            )
        )

    def source_commit_gate():
        with get_engine().connect() as connection:
            identities["source"] = begin(connection)
            connection.execute(insert(MatterOutsideCounselAssignment.__table__), row)
            # Fixture owns only the actual commit-stage gate AFTER source/FKs.
            connection.execute(text("SELECT pg_advisory_xact_lock(1145393713,0)"))
            source_ready.set()
            assert release.wait(3)
            connection.commit()

    def user_commit():
        with get_engine().connect() as connection:
            identities["user"] = begin(connection)
            connection.execute(
                update(User)
                .where(User.id == user_id)
                .values(full_name="Name after actual waited finalizer")
            )
            user_ready.set()
            connection.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        source = pool.submit(source_commit_gate)
        entered_or_exception(source_ready, source)
        user = pool.submit(user_commit)
        try:
            entered_or_exception(user_ready, user)
            require_blocker(identities["user"], identities["source"], user)
        finally:
            release.set()
        source.result(timeout=5)
        user.result(timeout=5)
    current = {
        **case,
        "matter": other,
        "url": f"/api/outside-counsel/matters/{other['id']}/context",
    }
    response = get(current)
    assert response.status_code == 200, response.text
    assert response.json()["assignments"][0]["assigned_by_name"] == (
        "Name after actual waited finalizer"
    )
    assert get(case).json()["assignments"][0]["assigned_by_name"] == (
        "Name after actual waited finalizer"
    )
    require_dense(current, [uid(79004)], "assignment")
