"""Native transaction/tenant fences for IP15-013 and IP15-015."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, Lock, current_thread

import pytest
from sqlalchemy import func, select

from caseops_api.db.models import (
    IpPortfolioRenewalOccurrence,
    IpPortfolioRenewalSeries,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewal_tracker, private_retrieval
from tests.sql_observation import is_read_only_select
from tests.test_ip_renewal_tracker_20261015 import _clock, _dispatch, _imported

pytestmark = pytest.mark.postgres


def test_two_actual_workers_serialize_one_persisted_occurrence(
    isolated_postgres_client, monkeypatch
):
    actor, docket_id = _imported(isolated_postgres_client, monkeypatch)
    now = datetime(2028, 3, 1, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    first_holding, second_entered, release = Event(), Event(), Event()
    counter_lock = Lock()
    calls = 0
    original = private_retrieval.lock_private_authority_writer

    def bounded_overlap(session, *, company_id):
        nonlocal calls
        assert not session.in_transaction(), (
            "Candidate observation must close before authority locks."
        )
        with counter_lock:
            calls += 1
            position = calls
        if position == 2:
            second_entered.set()
        original(session, company_id=company_id)
        if position == 1:
            first_holding.set()
            assert release.wait(10), "Overlap coordinator did not release the first worker."

    monkeypatch.setattr(private_retrieval, "lock_private_authority_writer", bounded_overlap)

    def run():
        with get_session_factory()() as session:
            result = ip_renewal_tracker.reconcile_renewal_series(session, now=now)
            assert not session.in_transaction()
            return result

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="renewal-worker") as pool:
        first = pool.submit(run)
        try:
            assert first_holding.wait(10)
            second = pool.submit(run)
            assert second_entered.wait(10)
            assert not second.done()
        finally:
            release.set()
        results = [first.result(timeout=15), second.result(timeout=15)]
    assert sum(row["advanced"] for row in results) == 1
    assert len(_dispatch(actor)) == 1
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpPortfolioRenewalOccurrence)
                .where(
                    IpPortfolioRenewalOccurrence.docket_id == docket_id,
                    IpPortfolioRenewalOccurrence.local_on == now.date(),
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(NotificationDeliveryIntent)
                .where(NotificationDeliveryIntent.source_type == ip_renewal_tracker.SOURCE)
            )
            == 1
        )


def test_actual_source_edit_wins_after_discovery_before_worker_lock(
    isolated_postgres_client, monkeypatch
):
    client = isolated_postgres_client
    actor, docket_id = _imported(client, monkeypatch)
    now = datetime(2028, 3, 1, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    discovered, release = Event(), Event()
    original = private_retrieval.lock_private_authority_writer

    def pause_worker(session, *, company_id):
        if current_thread().name.startswith("renewal-worker"):
            assert not session.in_transaction()
            discovered.set()
            assert release.wait(10)
        original(session, company_id=company_id)

    monkeypatch.setattr(private_retrieval, "lock_private_authority_writer", pause_worker)

    def run():
        with get_session_factory()() as session:
            return ip_renewal_tracker.reconcile_renewal_series(session, now=now)

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="renewal-worker") as pool:
        result = pool.submit(run)
        try:
            assert discovered.wait(10)
            removed = client.patch(
                f"/api/ip/dockets/{docket_id}/portfolio-dates",
                headers=actor["headers"],
                json={
                    "expected_current_version": 1,
                    "renewal_due_date": None,
                    "reason": "Source withdrawn before worker authority acquisition",
                },
            )
            assert removed.status_code == 200, removed.text
        finally:
            release.set()
        assert result.result(timeout=15)["advanced"] == 0
    assert _dispatch(actor) == []
    with get_session_factory()() as session:
        series = session.scalar(
            select(IpPortfolioRenewalSeries).where(IpPortfolioRenewalSeries.docket_id == docket_id)
        )
        assert series.source_version == 2 and series.next_reminder_at is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpPortfolioRenewalOccurrence)
                .where(IpPortfolioRenewalOccurrence.local_on == now.date())
            )
            == 0
        )


def test_dense_retained_history_bounds_actual_current_reads_and_catchup(
    isolated_postgres_client, monkeypatch, request
):
    import json
    import os
    from datetime import date, timedelta
    from pathlib import Path
    from uuid import uuid4

    from sqlalchemy import event, insert, text

    from caseops_api.db.models import Company, CompanyMembership
    from caseops_api.db.session import get_engine
    from caseops_api.services.ip_renewal_tracker_read import list_tracker
    from caseops_api.services.notification_delivery import (
        cancel_pending_notification_intents,
        notification_delivery_idempotency_key,
    )
    from caseops_api.services.session_context import SessionContext

    client = isolated_postgres_client
    actor, docket_id = _imported(client, monkeypatch)
    _clock(monkeypatch, datetime(2028, 2, 29, 4, tzinfo=UTC))
    receipt = _dispatch(actor)
    assert len(receipt) == 1 and receipt[0].delivered
    now = datetime(2028, 3, 20, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    edited = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "application_date": "2020-04-01",
            "reason": "Current source version for dense retention proof",
        },
    )
    assert edited.status_code == 200, edited.text
    with get_session_factory()() as session:
        series = session.scalar(
            select(IpPortfolioRenewalSeries).where(IpPortfolioRenewalSeries.docket_id == docket_id)
        )
        for schedule_type, schedule_id in (
            (ip_renewal_tracker.SCHEDULE, series.id),
            ("ip_portfolio_renewal", docket_id),
        ):
            cancel_pending_notification_intents(
                session,
                company_id=series.company_id,
                schedule_source_type=schedule_type,
                schedule_source_id=schedule_id,
                cancellation_reason="synthetic_retained_generation_fixture",
            )
        series.generation = 1002
        series.next_reminder_at = now
        session.flush()
        existing_pairs = set(
            session.execute(
                select(
                    IpPortfolioRenewalOccurrence.generation, IpPortfolioRenewalOccurrence.local_on
                ).where(IpPortfolioRenewalOccurrence.series_id == series.id)
            ).all()
        )
        intents, occurrences = [], []
        for generation in range(1, 1003):
            if generation == 1001:
                continue
            for day in range(20 if generation == 1002 else 32):
                occurrence_id = str(uuid4())
                source_version = 1 if generation <= 500 else 2
                local_on = date(2028, 2, 29) + timedelta(days=day)
                if (generation, local_on) in existing_pairs:
                    continue
                key = notification_delivery_idempotency_key(
                    company_id=series.company_id,
                    recipient_membership_id=series.recipient_membership_id,
                    channel="in_app",
                    event_type=ip_renewal_tracker.EVENT,
                    source_type=ip_renewal_tracker.SOURCE,
                    source_id=occurrence_id,
                )
                intents.append(
                    {
                        "company_id": series.company_id,
                        "recipient_membership_id": series.recipient_membership_id,
                        "channel": "in_app",
                        "event_type": ip_renewal_tracker.EVENT,
                        "source_type": ip_renewal_tracker.SOURCE,
                        "source_id": occurrence_id,
                        "idempotency_key": key,
                        "ip_docket_id": docket_id,
                        "schedule_source_type": ip_renewal_tracker.SCHEDULE,
                        "schedule_source_id": series.id,
                        "scheduled_for": now,
                        "status": "failed",
                        "title": "Retained fixture",
                        "body": "Retained source date, not a verified legal deadline.",
                    }
                )
                occurrences.append(
                    {
                        "id": occurrence_id,
                        "company_id": series.company_id,
                        "docket_id": docket_id,
                        "series_id": series.id,
                        "generation": generation,
                        "source_version": source_version,
                        "recipient_membership_id": series.recipient_membership_id,
                        "due_on": series.due_on,
                        "local_on": local_on,
                        "scheduled_for": now,
                        "delivery_key": key,
                    }
                )
                if len(intents) == 250:
                    session.execute(insert(NotificationDeliveryIntent), intents)
                    session.execute(insert(IpPortfolioRenewalOccurrence), occurrences)
                    intents, occurrences = [], []
        if intents:
            session.execute(insert(NotificationDeliveryIntent), intents)
            session.execute(insert(IpPortfolioRenewalOccurrence), occurrences)
        session.commit()
        session.execute(text("ANALYZE ip_portfolio_renewal_occurrences"))
        session.execute(text("ANALYZE notification_delivery_intents"))
        session.commit()
    statements = {}
    all_statements = []
    engine = get_engine()

    def capture(connection, cursor, statement, parameters, context, executemany):
        sql = statement.lower()
        compiled = getattr(context, "compiled", None)
        read_only = is_read_only_select(getattr(compiled, "statement", None))
        all_statements.append({"statement": statement, "read_only_select": read_only})
        label = None
        if (
            sql.startswith("update notification_delivery_intents")
            and "ip_portfolio_renewal_occurrences" in sql
        ):
            label = "catchup_cleanup"
        elif (
            read_only and "sum(" in sql and "ip_portfolio_renewal_occurrences" in sql
        ):
            label = "category_counts"
        elif (
            read_only
            and "select ip_docket_records.id, (select notification_delivery_intents.id" in sql
        ):
            label = "current_hydration"
        elif (
            read_only
            and "select ip_portfolio_renewal_series.docket_id, "
            "notification_delivery_intents.delivered_at" in sql
        ):
            label = "confirmed_history"
        elif (
            read_only
            and "select notification_delivery_intents.id " in sql
            and "join in_app_notifications" in sql
        ):
            label = "same_day_dedupe"
        elif (
            read_only
            and "select notification_delivery_intents.id " in sql
            and "join ip_portfolio_renewal_occurrences" in sql
        ):
            label = "current_pending_keys"
        if label:
            statements[label] = (
                statement,
                parameters.copy() if isinstance(parameters, dict) else parameters,
            )

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with get_session_factory()() as session:
            assert ip_renewal_tracker.reconcile_renewal_series(session, now=now)["advanced"] == 1
        with get_session_factory()() as session:
            membership = session.get(CompanyMembership, actor["membership"]["id"])
            context = SessionContext(
                company=session.get(Company, actor["company"]["id"]),
                membership=membership,
                user=membership.user,
            )
            result = list_tracker(session, context=context, query="Recurring source mark")
            assert len(result.rows) == 1 and result.rows[0].current_version == 2
            assert result.counts["active"] == 1 and result.rows[0].delivered_at is not None
            series = session.scalar(
                select(IpPortfolioRenewalSeries).where(
                    IpPortfolioRenewalSeries.docket_id == docket_id
                )
            )
            with session.begin_nested() as boundary:
                ip_renewal_tracker._cancel(
                    session, series=series, reason="retained_work_proof", now=now
                )
                boundary.rollback()
            session.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        request.node.user_properties.append((
            "dense_history_statements", json.dumps(all_statements, sort_keys=True),
        ))
    assert set(statements) == {
        "catchup_cleanup",
        "category_counts",
        "current_hydration",
        "confirmed_history",
        "same_day_dedupe",
        "current_pending_keys",
    }, all_statements
    plans = {}
    with engine.begin() as connection:
        for label, (statement, parameters) in statements.items():
            plans[label] = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters
            ).scalar_one()
    output = Path(os.environ["CASEOPS_TEST_RESULT_JOURNAL"]).parent / "dense-history-plans.json"
    output.write_text(
        json.dumps(
            {
                "retained_old_occurrences": 32000,
                "current_old_occurrences": 20,
                "current_version": 2,
                "current_generation": 1002,
                "plans": plans,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    def nodes(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from nodes(child)

    for label, plan in plans.items():
        occurrence_nodes = [
            node
            for node in nodes(plan)
            if node.get("Relation Name") == "ip_portfolio_renewal_occurrences"
        ]
        assert (
            sum(
                (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0))
                * node.get("Actual Loops", 1)
                for node in occurrence_nodes
            )
            <= 256
        ), label
        history_nodes = [
            node
            for node in nodes(plan)
            if node.get("Relation Name")
            in {
                "notification_delivery_intents",
                "in_app_notifications",
                "ip_portfolio_renewal_occurrences",
            }
        ]
        assert (
            sum(
                (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0))
                * node.get("Actual Loops", 1)
                for node in history_nodes
            )
            <= 512
        ), label
    for label in ("category_counts", "current_hydration"):
        assert any(
            node.get("Index Name") == "ix_ip_renewal_occurrence_current"
            and node.get("Actual Loops", 0) > 0
            for node in nodes(plans[label])
        ), label
