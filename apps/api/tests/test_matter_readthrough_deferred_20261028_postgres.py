"""Real mixed0005/0006/0008 commit races, prepared without a PG acceptance claim.

Canonical READ COMMITTED/default-deferred writers only. Distinct source rows
finish their ordinary writes and audit FK work while an independent DER1 gate
is held. No function replacement, constraint-mode change or manual refresh is
used. Existing3s/100-read directed-edge and5s join bounds remain unchanged.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import func, select, text, update

from caseops_api.db.models import (
    AuditEvent,
    CounselReadPageDirty,
    DomainOutboxEvent,
    InAppNotification,
    MatterReadthroughDirty,
    MatterTask,
    MatterTaskQueueDirty,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    OutsideCounselSpendRecord,
    Recommendation,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.audit import record_from_context
from tests.test_deferred_native_projections_20261027_postgres import (
    GATE,
    MARK,
    assert_whole_current_reads,
    begin,
    clean_and_retained,
    context,
    entered_or_exception,
    iso,
    observed_edge,
    seed,
    session_pid,
    snapshot,
    uid,
)
from tests.test_deferred_native_projections_20261027_postgres import (
    explicit_bearer_actor as explicit_bearer_actor,
)
from tests.test_deferred_native_projections_20261027_postgres import (
    forbid_unadmitted_network as forbid_unadmitted_network,
)

pytestmark = pytest.mark.postgres
STAMP = datetime(2026, 10, 28, 11, 12, 13, 123456, tzinfo=UTC)
DIRTY = (CounselReadPageDirty, MatterTaskQueueDirty, MatterReadthroughDirty)
OUTBOX = (
    DomainOutboxEvent,
    NotificationDeliveryIntent,
    NotificationDeliveryEvent,
    InAppNotification,
)


def rec_id(index):
    return uid(91001 + index)


def seed_recommendations(case):
    with get_session_factory()() as session:
        actor = context(session, case)
        name = actor.user.full_name
        assert isinstance(name, str) and name
        for index in (0, 1):
            session.add(
                Recommendation(
                    id=rec_id(index),
                    company_id=case["auth"]["company"]["id"],
                    matter_id=case["matter"]["id"],
                    type="authority",
                    title=f"Original recommendation {index}",
                    rationale=f"Original rationale {index}",
                    primary_option_index=0,
                    assumptions_json="[]",
                    missing_facts_json="[]",
                    retrieved_authorities_json="[]",
                    confidence="low",
                    review_required=True,
                    status="proposed",
                    created_at=STAMP + timedelta(microseconds=index),
                    updated_at=STAMP,
                )
            )
        session.commit()
    return name


def current_dirty(session):
    transaction = session.scalar(select(func.txid_current_if_assigned()))
    assert type(transaction) is int and transaction > 0
    counts = {}
    for model in DIRTY:
        count = session.scalar(
            select(func.count()).select_from(model).where(model.transaction_id == transaction)
        )
        assert type(count) is int and count > 0
        counts[model.__table__.name] = count
    return str(transaction), counts


def literal_recommendation_page(case):
    items = []
    for index in (1, 0):
        items.append(
            {
                "id": rec_id(index),
                "read_state": "available",
                "record": {
                    "type": "authority",
                    "title": f"Recommendation committed {index}",
                    "confidence": ("medium", "high")[index],
                    "review_required": bool(index),
                    "status": "proposed",
                },
                "created_at": iso(STAMP + timedelta(microseconds=index)),
                "updated_at": iso(STAMP + timedelta(seconds=index + 1)),
            }
        )
    return {
        "scope": {
            "company_id": case["auth"]["company"]["id"],
            "matter_id": case["matter"]["id"],
            "matter_status": "intake",
            "matter_is_active": True,
            "matter_lifecycle_version": case["matter"]["lifecycle_version"],
        },
        "parent_id": None,
        "limit": 25,
        "order": "created_at_desc_id_desc",
        "items": items,
        "next_cursor": None,
        "kind": "recommendations",
    }


def cold_recommendations(case, expected):
    url = f"/api/matter-readthrough/{case['matter']['id']}/recommendations"
    response = case["client"].get(url, headers=case["headers"])
    assert response.status_code == 200, response.text
    assert response.json() == expected
    reloaded = case["client"].get(url, headers=case["headers"])
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json() == expected
    with get_session_factory()() as session:
        source = list(
            session.scalars(
                select(Recommendation)
                .where(
                    Recommendation.company_id == case["auth"]["company"]["id"],
                    Recommendation.matter_id == case["matter"]["id"],
                )
                .order_by(Recommendation.id)
            )
        )
        assert [row.id for row in source] == [rec_id(0), rec_id(1)]
        for index, row in enumerate(source):
            assert row.title == f"Recommendation committed {index}"
            assert row.rationale == f"Original rationale {index}"
            assert row.assumptions_json == row.missing_facts_json == "[]"
            assert row.retrieved_authorities_json == "[]" and row.primary_option_index == 0


def save_attempt(tmp_path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    assert len(data) <= 65536
    with (tmp_path / "three-finalizers-attempt.json").open("xb") as stream:
        written = stream.write(data)
    assert written == len(data)


@pytest.mark.parametrize("first_waiter", [0, 1])
def test_three_finalizers_preserve_both_opposite_order_commits_after_real_der1_wait(
    isolated_postgres_client,
    first_waiter,
    tmp_path,
):
    case = seed(isolated_postgres_client)
    name = seed_recommendations(case)
    before_audit = snapshot((AuditEvent,))[0]
    before_outbox = snapshot(OUTBOX)
    ready, commit = [Event(), Event()], [Event(), Event()]
    identities, acknowledgements = {}, {}
    completed = []
    body_error = None
    join_errors = []

    def writer(index):
        with get_session_factory()() as session:
            pid = session_pid(session)
            identities[index] = pid
            isolation = session.scalar(text("SHOW transaction_isolation"))
            assert isolation == "read committed"
            work = [
                (
                    Recommendation,
                    rec_id(index),
                    {
                        "title": f"Recommendation committed {index}",
                        "confidence": ("medium", "high")[index],
                        "review_required": bool(index),
                        "updated_at": STAMP + timedelta(seconds=index + 1),
                    },
                ),
                (MatterTask, case["tasks"][index]["id"], {"title": f"Task committed {index}"}),
                (
                    OutsideCounselSpendRecord,
                    uid(20001 + index),
                    {"notes": f"Note committed {index}"},
                ),
            ]
            if index:
                work.reverse()
            writes = []
            for model, identity, values in work:
                result = session.execute(
                    update(model)
                    .where(
                        model.id == identity,
                        model.company_id == case["auth"]["company"]["id"],
                        model.matter_id == case["matter"]["id"],
                    )
                    .values(**values)
                )
                assert result.rowcount == 1
                writes.append(
                    {"table": model.__table__.name, "id": identity, "rowcount": result.rowcount}
                )
            audit = record_from_context(
                session,
                context(session, case),
                action=MARK,
                target_type="fixture",
                target_id=f"readthrough-three-finalizers-{index}",
                matter_id=case["matter"]["id"],
                metadata={"synthetic": True},
            )
            audit_id = session.scalar(select(AuditEvent.id).where(AuditEvent.id == audit.id))
            assert audit_id == audit.id and isinstance(audit_id, str)
            transaction, counts = current_dirty(session)
            acknowledgements[index] = {
                "backendPid": pid,
                "isolation": isolation,
                "transactionId": transaction,
                "sourceWrites": writes,
                "auditId": audit_id,
                "auditAcknowledged": True,
                "currentTransactionDirtyCounts": counts,
            }
            ready[index].set()
            released = commit[index].wait(3)
            assert released
            session.commit()
            return index

    with get_engine().connect() as gate, ThreadPoolExecutor(max_workers=2) as pool:
        holder = begin(gate)
        gate.execute(text(GATE))
        futures = [pool.submit(writer, index) for index in (0, 1)]
        try:
            for index in (0, 1):
                entered_or_exception(ready[index], futures[index])
            assert len({holder, identities[0], identities[1]}) == 3
            assert acknowledgements[0]["transactionId"] != acknowledgements[1]["transactionId"]
            commit[first_waiter].set()
            observed_edge(
                tmp_path, "first", identities[first_waiter], holder, futures[first_waiter]
            )
            second = 1 - first_waiter
            commit[second].set()
            observed_edge(tmp_path, "second", identities[second], holder, futures[second])
            gate.commit()
        except BaseException as error:
            body_error = error
        finally:
            for event in commit:
                event.set()
            gate.rollback()
            join_deadline = monotonic() + 5
            for index, future in enumerate(futures):
                try:
                    returned = future.result(timeout=max(0, join_deadline - monotonic()))
                    assert returned == index
                    completed.append(index)
                except BaseException as error:
                    join_errors.append(error)
            try:
                save_attempt(
                    tmp_path,
                    {
                        "firstWaiter": first_waiter,
                        "holderPid": holder,
                        "writerAcknowledgements": acknowledgements,
                        "completedWriters": completed,
                        "originalFailureClass": type(body_error).__name__ if body_error else None,
                        "joinFailureClasses": [type(error).__name__ for error in join_errors],
                        "gateObservationMaxReads": 100,
                        "gateObservationSeconds": 3,
                        "joinSeconds": 5,
                    },
                )
            except BaseException as error:
                join_errors.append(error)
        if body_error:
            raise body_error
        if join_errors:
            raise join_errors[0]

    expected = literal_recommendation_page(case)
    cold_recommendations(case, expected)
    assert_whole_current_reads(
        case,
        {row["id"]: f"Task committed {index}" for index, row in enumerate(case["tasks"])},
        {uid(20001 + index): f"Note committed {index}" for index in (0, 1)},
        name,
    )
    # The old helper's two-outbox assertion is retained, with the complete
    # four-model fixture snapshot checked separately here.
    clean_and_retained(case, before_audit, before_outbox[:2], 2)
    assert snapshot(OUTBOX) == before_outbox
    after_audit = snapshot((AuditEvent,))[0]
    previous_ids = {row["id"] for row in before_audit}
    new_audits = [row for row in after_audit if row["id"] not in previous_ids]
    assert {row["id"] for row in new_audits} == {
        acknowledgements[index]["auditId"] for index in (0, 1)
    }
    assert {row["target_id"] for row in new_audits} == {
        "readthrough-three-finalizers-0",
        "readthrough-three-finalizers-1",
    }
    with get_session_factory()() as session:
        counts = {
            model.__table__.name: session.scalar(select(func.count()).select_from(model))
            for model in DIRTY
        }
    assert counts == {model.__table__.name: 0 for model in DIRTY}
