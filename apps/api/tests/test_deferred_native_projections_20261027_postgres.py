"""Real mixed 0005/0006 transaction contracts; source prepared, never auto-retried.

Canonical default-deferred READ COMMITTED writers only. Administrative TRUNCATE
and early SET CONSTRAINTS followed by more writes are outside this contract.
No production function is replaced. Worker finalizers take the gate only after
source/audit/FKs; an independent held fixture gate proves those writes finish.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update

from caseops_api.db.models import (
    AuditEvent,
    CounselReadPageDirty,
    DomainOutboxEvent,
    Matter,
    MatterOutsideCounselAssignment,
    MatterTask,
    MatterTaskQueueDirty,
    NotificationDeliveryIntent,
    OutsideCounselSpendRecord,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import matter_work_queue as queue
from caseops_api.services.audit import record_from_context
from caseops_api.services.counsel_read_pages import counsel_page_statement
from caseops_api.services.identity import get_session_context
from caseops_api.services.outside_counsel import (
    _matter_context_page_statement,
    _serialize_assignment_record,
    _serialize_spend_record,
)
from tests.test_counsel_read_pages_20261027 import case_for, snapshot
from tests.test_counsel_read_pages_20261027_postgres import (
    begin,
    copied_source,
    entered_or_exception,
)
from tests.test_matter_counsel_context_20261027 import get, uid
from tests.test_matter_work_queue_20261027 import task
from tests.test_matter_work_queue_20261027_postgres import (
    explicit_bearer_actor as explicit_bearer_actor,
)
from tests.test_matter_work_queue_20261027_postgres import (
    forbid_unadmitted_network as forbid_unadmitted_network,
)
from tests.test_outside_counsel import _create_matter

pytestmark = pytest.mark.postgres
GATE = "SELECT pg_advisory_xact_lock(1145393713,0)"
MARK = "fixture.mixed_projection_commit"


def session_pid(session):
    # Session.connection() has already autobegun its connection; do not call
    # Connection.begin() again. These are the existing five-second SQL budgets.
    session.execute(text("SET LOCAL statement_timeout='5s'"))
    session.execute(text("SET LOCAL lock_timeout='5s'"))
    return session.scalar(text("SELECT pg_backend_pid()"))


def observed_edge(tmp_path, label, waiter, holder, future):
    """Same reviewed3s/100read protocol, retaining each actual public snapshot."""
    deadline = monotonic() + 3
    snapshots = []
    try:
        with get_engine().connect() as observer:
            while len(snapshots) < 100:
                last = observer.scalar(text("SELECT pg_blocking_pids(:waiter)"), {"waiter": waiter})
                snapshots.append(last)
                # Check the existing final snapshot before testing the clock.
                if holder in last:
                    return
                if future.done():
                    future.result()
                    raise AssertionError("Writer completed before the required commit-gate edge")
                if monotonic() >= deadline:
                    break
                sleep(0.01)
        raise AssertionError("Required directed commit-gate edge was not observed")
    finally:
        data = (
            json.dumps(
                {
                    "waiterPid": waiter,
                    "holderPid": holder,
                    "snapshots": snapshots,
                    "maxSnapshots": 100,
                    "deadlineSeconds": 3,
                },
                indent=2,
            )
            + "\n"
        )
        assert len(data.encode()) <= 16384
        (tmp_path / (label + "-gate-edge.json")).write_text(data)


def seed(client):
    case = case_for(client, 2)
    owner = {**case["auth"], "headers": case["headers"]}
    case["tasks"] = [
        task(client, owner, case["matter"], owner["membership"]["id"], title=f"Original task {n}")
        for n in (1, 2)
    ]
    case["owner"] = owner
    return case


def iso(value):
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def context(session, case):
    result = get_session_context(session, case["auth"]["membership"]["id"])
    assert result.membership.role == "owner" and result.company.id == case["auth"]["company"]["id"]
    return result


def audit(session, case, token):
    record_from_context(
        session,
        context(session, case),
        action=MARK,
        target_type="fixture",
        target_id=token,
        matter_id=case["matter"]["id"],
        metadata={"synthetic": True},
    )


def dirty(session):
    # All source/audit writes must finish while the external DER1 gate is held.
    current = func.txid_current_if_assigned()
    assert (
        session.scalar(
            select(func.count())
            .select_from(MatterTaskQueueDirty)
            .where(MatterTaskQueueDirty.transaction_id == current)
        )
        > 0
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(CounselReadPageDirty)
            .where(CounselReadPageDirty.transaction_id == current)
        )
        > 0
    )


def clean_and_retained(case, before_audit, before_outbox, expected_new_audits):
    assert snapshot((DomainOutboxEvent, NotificationDeliveryIntent)) == before_outbox
    after = snapshot((AuditEvent,))[0]
    old = {row["id"]: row for row in before_audit}
    assert {row["id"]: row for row in after if row["id"] in old} == old
    new = [row for row in after if row["id"] not in old]
    assert len(new) == expected_new_audits and all(row["action"] == MARK for row in new)
    assert all(row["actor_membership_id"] == case["auth"]["membership"]["id"] for row in new)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(MatterTaskQueueDirty)) == 0
        assert session.scalar(select(func.count()).select_from(CounselReadPageDirty)) == 0


def assert_whole_current_reads(case, expected_titles, expected_notes, expected_name):
    """Cold canonical source serializers and literal queue response fields.

    Oracle reads are explicit fixture work, never hidden serving-plan work.
    No query-plan bound or native acceptance is claimed by this module.
    """
    company = case["auth"]["company"]["id"]
    member = case["auth"]["membership"]["id"]
    with get_session_factory()() as session:
        source_tasks = list(
            session.scalars(
                select(MatterTask)
                .where(
                    MatterTask.company_id == company,
                    MatterTask.owner_membership_id == member,
                )
                .order_by(MatterTask.due_on, MatterTask.created_at, MatterTask.id)
            )
        )
        assert {row.id: row.title for row in source_tasks} == expected_titles
        items = []
        for row in source_tasks:
            parent = session.get(Matter, row.matter_id)
            items.append(
                {
                    "id": row.id,
                    "title": row.title,
                    "status": row.status,
                    "priority": row.priority,
                    "due_on": row.due_on.isoformat() if row.due_on else None,
                    "owner_membership_id": row.owner_membership_id,
                    "created_at": iso(row.created_at),
                    "updated_at": iso(row.updated_at),
                    "matter": {
                        "id": parent.id,
                        "title": parent.title,
                        "matter_code": parent.matter_code,
                        "status": parent.status,
                        "is_active": parent.is_active,
                        "lifecycle_version": parent.lifecycle_version,
                    },
                }
            )
        expected_queue = {
            "scope": "matter_tasks",
            "ownership": "mine",
            "dates": "all",
            "due_from": None,
            "due_to": None,
            "sort": "due_on_created_at_id",
            "limit": 25,
            "items": items,
            "next_cursor": None,
        }
        parent = session.get(Matter, case["matter"]["id"])
        source_lists = []
        for model, serializer in (
            (MatterOutsideCounselAssignment, _serialize_assignment_record),
            (OutsideCounselSpendRecord, _serialize_spend_record),
        ):
            # This is the unchanged original source join, executed on PG; its
            # explicit selector flag chooses source shape, not a fake dialect.
            statement = _matter_context_page_statement(
                model,
                company_id=company,
                matter_id=parent.id,
                after=None,
                limit=25,
                dialect_name="sqlite",
            )
            result = []
            for row in session.scalars(statement):
                value = serializer(row).model_dump(mode="json")
                value.update(created_at=iso(row.created_at), updated_at=iso(row.updated_at))
                result.append(value)
            source_lists.append(result)
        assignments, spending = source_lists
        assert {row["id"]: row["notes"] for row in spending} == expected_notes
        assert all(row["assigned_by_name"] == expected_name for row in assignments)
        assert all(row["recorded_by_name"] == expected_name for row in spending)
        currencies = {}
        for row in assignments:
            value = currencies.setdefault(
                row["currency"],
                {
                    "currency": row["currency"],
                    "recorded_budget_minor": 0,
                    "unpriced_assignment_count": 0,
                    "amount_minor": 0,
                    "approved_amount_minor": 0,
                    "paid_amount_minor": 0,
                    "pending_amount_minor": 0,
                },
            )
            value["recorded_budget_minor"] += row["budget_amount_minor"] or 0
            value["unpriced_assignment_count"] += row["budget_amount_minor"] is None
        for row in spending:
            value = currencies.setdefault(
                row["currency"],
                {
                    "currency": row["currency"],
                    "recorded_budget_minor": 0,
                    "unpriced_assignment_count": 0,
                    "amount_minor": 0,
                    "approved_amount_minor": 0,
                    "paid_amount_minor": 0,
                    "pending_amount_minor": 0,
                },
            )
            for key in (
                "amount_minor",
                "approved_amount_minor",
                "paid_amount_minor",
                "pending_amount_minor",
            ):
                value[key] += row[key]
        expected_counsel = {
            "matter_id": parent.id,
            "matter_title": parent.title,
            "matter_code": parent.matter_code,
            "matter_status": parent.status,
            "matter_is_active": parent.is_active,
            "lifecycle_version": parent.lifecycle_version,
            "totals_scope": "page",
            "assignments": assignments,
            "spend_records": spending,
            "assignment_limit": 25,
            "spend_limit": 25,
            "assignment_next_after": None,
            "spend_next_after": None,
            "currencies": [currencies[key] for key in sorted(currencies)],
        }
    params = {"ownership": "mine", "dates": "all", "limit": 25}
    queue = case["client"].get("/api/matter-work-queue", headers=case["headers"], params=params)
    assert queue.status_code == 200, queue.text
    assert queue.json() == expected_queue
    assert (
        case["client"].get("/api/matter-work-queue", headers=case["headers"], params=params).json()
        == expected_queue
    )
    response = get(case, assignment_limit=25, spend_limit=25)
    assert response.status_code == 200, response.text
    assert response.json() == expected_counsel
    assert get(case, assignment_limit=25, spend_limit=25).json() == expected_counsel
    return expected_queue, expected_counsel


@pytest.mark.parametrize("first_waiter", [0, 1])
def test_opposite_projection_source_orders_finish_audit_before_shared_commit_gate(
    isolated_postgres_client,
    first_waiter,
    tmp_path,
):
    case = seed(isolated_postgres_client)
    before_audit = snapshot((AuditEvent,))[0]
    before_outbox = snapshot((DomainOutboxEvent, NotificationDeliveryIntent))
    ready, commit = [Event(), Event()], [Event(), Event()]
    identity = {}

    def writer(index):
        with get_session_factory()() as session:
            identity[index] = session_pid(session)
            work = [
                (MatterTask, case["tasks"][index]["id"], {"title": f"Task committed {index}"}),
                (
                    OutsideCounselSpendRecord,
                    uid(20001 + index),
                    {"notes": f"Note committed {index}"},
                ),
            ]
            if index:
                work.reverse()
            for model, record_id, values in work:
                session.execute(update(model).where(model.id == record_id).values(**values))
            if index:
                session.execute(
                    update(User)
                    .where(User.id == case["auth"]["user"]["id"])
                    .values(full_name="Current name after both projections")
                )
            audit(session, case, f"opposite-{index}")
            dirty(session)
            ready[index].set()
            commit_released = commit[index].wait(3)
            assert commit_released
            session.commit()

    with get_engine().connect() as gate, ThreadPoolExecutor(max_workers=2) as pool:
        holder = begin(gate)
        gate.execute(text(GATE))
        futures = [pool.submit(writer, index) for index in (0, 1)]
        try:
            for index in (0, 1):
                entered_or_exception(ready[index], futures[index])
            commit[first_waiter].set()
            observed_edge(tmp_path, "first", identity[first_waiter], holder, futures[first_waiter])
            second = 1 - first_waiter
            commit[second].set()
            observed_edge(tmp_path, "second", identity[second], holder, futures[second])
            gate.commit()
        finally:
            for event in commit:
                event.set()
            gate.rollback()
        for future in futures:
            future.result(timeout=5)
    assert_whole_current_reads(
        case,
        {row["id"]: f"Task committed {index}" for index, row in enumerate(case["tasks"])},
        {uid(20001 + n): f"Note committed {n}" for n in (0, 1)},
        "Current name after both projections",
    )
    clean_and_retained(case, before_audit, before_outbox, 2)


@pytest.mark.parametrize("first_commit", ["user", "new-parent-source"])
def test_mixed_user_and_new_parent_finalizers_observe_both_commit_orders_after_gate_wait(
    isolated_postgres_client,
    first_commit,
    tmp_path,
):
    case = seed(isolated_postgres_client)
    other = _create_matter(
        isolated_postgres_client,
        case["auth"]["access_token"],
        title="Mixed new parent",
        matter_code="MIXED-NEW-PARENT",
    )
    new_assignment_id = str(uuid4())
    new_task_id = str(uuid4())
    source_assignment = copied_source(
        MatterOutsideCounselAssignment, uid(1), id=new_assignment_id, matter_id=other["id"]
    )
    source_task = copied_source(
        MatterTask,
        case["tasks"][1]["id"],
        id=new_task_id,
        matter_id=other["id"],
        title="New parent task",
    )
    before_audit = snapshot((AuditEvent,))[0]
    before_outbox = snapshot((DomainOutboxEvent, NotificationDeliveryIntent))
    ready = Event()
    identity = {}

    def source_body(session):
        session.execute(MatterOutsideCounselAssignment.__table__.insert(), source_assignment)
        session.execute(MatterTask.__table__.insert(), source_task)
        audit(session, case, "new-parent-source")
        dirty(session)

    def user_body(session):
        session.execute(
            update(MatterTask)
            .where(MatterTask.id == case["tasks"][0]["id"])
            .values(title="Task alongside User rename")
        )
        session.execute(
            update(User)
            .where(User.id == case["auth"]["user"]["id"])
            .values(full_name="Mixed current User name")
        )
        audit(session, case, "user-rename")
        dirty(session)

    first, second = (user_body, source_body) if first_commit == "user" else (source_body, user_body)

    def peer():
        with get_session_factory()() as session:
            identity["peer"] = session_pid(session)
            second(session)
            ready.set()
            session.commit()

    with get_session_factory()() as main, ThreadPoolExecutor(max_workers=1) as pool:
        holder = session_pid(main)
        first(main)
        main.execute(text(GATE))  # Actual commit-stage gate AFTER all source/audit/FKs.
        future = pool.submit(peer)
        try:
            entered_or_exception(ready, future)
            observed_edge(tmp_path, "peer", identity["peer"], holder, future)
            main.commit()
        finally:
            main.rollback()
        future.result(timeout=5)
    expected_titles = {row["id"]: row["title"] for row in case["tasks"]}
    expected_titles[case["tasks"][0]["id"]] = "Task alongside User rename"
    expected_titles[new_task_id] = "New parent task"
    assert_whole_current_reads(
        case, expected_titles, {uid(20001): None, uid(20002): None}, "Mixed current User name"
    )
    new_case = {
        **case,
        "matter": other,
        "url": f"/api/outside-counsel/matters/{other['id']}/context",
    }
    assert_whole_current_reads(new_case, expected_titles, {}, "Mixed current User name")
    response = get(new_case, assignment_limit=25, spend_limit=25)
    assert response.status_code == 200, response.text
    assert [(r["id"], r["assigned_by_name"]) for r in response.json()["assignments"]] == [
        (new_assignment_id, "Mixed current User name")
    ]
    assert response.json()["spend_records"] == []
    assert get(new_case, assignment_limit=25, spend_limit=25).json() == response.json()
    clean_and_retained(case, before_audit, before_outbox, 2)


def test_mixed_source_user_audit_and_projection_rollback_keeps_whole_previous_reads(
    isolated_postgres_client,
):
    case = seed(isolated_postgres_client)
    before_audit = snapshot((AuditEvent,))[0]
    before_outbox = snapshot((DomainOutboxEvent, NotificationDeliveryIntent))
    titles = {row["id"]: row["title"] for row in case["tasks"]}
    with get_session_factory()() as session:
        name = session.get(User, case["auth"]["user"]["id"]).full_name
    before = assert_whole_current_reads(case, titles, {uid(20001): None, uid(20002): None}, name)
    with get_session_factory()() as session:
        session_pid(session)
        actor = context(session, case)
        retained_queue = queue.work_queue_statement(
            session, context=actor, ownership="mine", dates="all"
        )
        retained_counsel = counsel_page_statement(
            OutsideCounselSpendRecord,
            company_id=case["auth"]["company"]["id"],
            matter_id=case["matter"]["id"],
            after=None,
            limit=25,
        )
        original_queue = list(session.execute(retained_queue).mappings())
        original_counsel = list(session.execute(retained_counsel).mappings())
        session.execute(
            update(MatterTask)
            .where(MatterTask.id == case["tasks"][0]["id"])
            .values(title="Uncommitted mixed task")
        )
        session.execute(
            update(OutsideCounselSpendRecord)
            .where(OutsideCounselSpendRecord.id == uid(20001))
            .values(notes="Uncommitted mixed note")
        )
        session.execute(
            update(User)
            .where(User.id == case["auth"]["user"]["id"])
            .values(full_name="Uncommitted mixed User")
        )
        audit(session, case, "rolled-back")
        dirty(session)
        current_queue = list(session.execute(retained_queue).mappings())
        current_counsel = list(session.execute(retained_counsel).mappings())
        assert (
            next(row["title"] for row in current_queue if row["id"] == case["tasks"][0]["id"])
            == "Uncommitted mixed task"
        )
        pending = next(row for row in current_counsel if row["source_payload"]["id"] == uid(20001))
        assert pending["source_note"] == "Uncommitted mixed note"
        assert pending["actor_name"] == "Uncommitted mixed User"
        outside_during = assert_whole_current_reads(
            case, titles, {uid(20001): None, uid(20002): None}, name
        )
        assert outside_during == before
        session.rollback()
        restored_queue = list(session.execute(retained_queue).mappings())
        restored_counsel = list(session.execute(retained_counsel).mappings())
        assert restored_queue == original_queue
        assert restored_counsel == original_counsel
        session.rollback()
    after_rollback = assert_whole_current_reads(
        case, titles, {uid(20001): None, uid(20002): None}, name
    )
    assert after_rollback == before
    clean_and_retained(case, before_audit, before_outbox, 0)
