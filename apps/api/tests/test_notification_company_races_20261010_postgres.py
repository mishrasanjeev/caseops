"""Native tenant-disable/dispatch winners, with deterministic local transport."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    InAppNotification,
    Matter,
    MatterPortalGrant,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
)
from caseops_api.services import communications
from caseops_api.services import notification_delivery as delivery
from tests.test_document_finalizer_overlap_20261009_postgres import (
    finalizer_audit as _finalizer_audit,
)
from tests.test_notification_company_activity_20261010 import _enqueue, _fixture
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres
finalizer_audit = _finalizer_audit


def _seed_intent(audit, target):
    with audit.session("mutation") as session:
        company, context, kwargs = _fixture(
            session, "email_member" if target == "employee" else target,
        )
        matter = session.scalars(select(Matter).where(Matter.company_id == company.id)).one()
        kwargs["matter"] = matter
        if target == "portal":
            session.add(MatterPortalGrant(
                company_id=company.id, portal_user_id=kwargs["recipient_portal_user"].id,
                matter_id=matter.id, role="viewer",
                granted_by_membership_id=context.membership.id,
                granted_by_label_snapshot="Local race fixture owner",
            ))
            session.flush()
        intent = _enqueue(session, context, kwargs)
        assert intent is not None and company.is_active
        assert intent.status == "queued" and intent.attempts == 0
        assert intent.dead_letter_reason is None and intent.provider_event_id is None
        assert intent.scheduled_for is None
        session.commit()
        fixture = {
            "company_id": company.id, "matter_id": matter.id, "intent_id": intent.id,
            "parent_state": (matter.status, matter.is_active, matter.lifecycle_version,
                             matter.updated_at),
        }
    audit.record(
        "notification_race_source", target=target, fixture=fixture,
        admitted_status="queued", initial_attempts=0,
        delivery_origin=str(Path(delivery.__file__).resolve()),
        delivery_sha256=sha256(Path(delivery.__file__).read_bytes()).hexdigest(),
        test_origin=str(Path(__file__).resolve()),
        test_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    return fixture


def _lock_order(audit, target, *, internal=False):
    statements = audit.statements["worker"]

    def positions(clause):
        return [index for index, sql in enumerate(statements) if clause in sql]

    company = positions("FOR NO KEY UPDATE OF companies")
    member = positions("FOR UPDATE OF company_memberships")
    user = positions("FOR UPDATE OF users")
    parent = positions("FOR UPDATE OF matters")
    intent = positions("FOR UPDATE OF notification_delivery_intents")
    assert parent and intent and parent[0] < intent[0]
    if internal:
        assert not company and not member and not user
    else:
        assert len(company) == 1 and company[0] < parent[0]
        if target == "employee":
            assert member and user
            assert company[0] < member[0] < user[0] < parent[0] < intent[0]
        else:
            assert not member and not user, "Do not invent an employee actor for delivery"
    audit.record("notification_lock_order", target=target, internal=internal,
                 company=company, membership=member, user=user, parent=parent, intent=intent)


def _read_back(audit, fixture, winner, calls):
    with Session(audit.engine) as session:
        company = session.get(Company, fixture["company_id"])
        matter = session.get(Matter, fixture["matter_id"])
        intent = session.get(NotificationDeliveryIntent, fixture["intent_id"])
        assert not company.is_active
        assert (matter.status, matter.is_active, matter.lifecycle_version,
                matter.updated_at) == fixture["parent_state"]
        assert intent.fallback_intent_id is None and intent.in_app_notification_id is None
        assert session.scalar(select(func.count()).select_from(InAppNotification).where(
            InAppNotification.company_id == company.id,
        )) == 0
        assert session.scalar(select(func.count()).select_from(NotificationDeliveryIntent).where(
            NotificationDeliveryIntent.company_id == company.id,
        )) == 1
        events = list(session.scalars(select(NotificationDeliveryEvent.event_type).where(
            NotificationDeliveryEvent.intent_id == intent.id,
        )))
        if winner == "disable":
            assert intent.status == "blocked" and intent.attempts == 0
            assert intent.dead_letter_reason == "recipient_permission_revoked"
            assert intent.provider_event_id is None and not calls
            assert events.count("delivery_permission_blocked") == 1
            assert "delivery_claimed" not in events and "provider_accepted" not in events
        else:
            assert intent.status == "sent" and intent.attempts == 1
            assert intent.provider_event_id == calls[0] and len(calls) == 1
            assert events.count("delivery_claimed") == events.count("provider_accepted") == 1
            assert "delivery_permission_blocked" not in events
        # A replay after disablement must not issue another disclosure or rewrite provenance.
        snapshot = (intent.status, intent.attempts, intent.provider_event_id)
        delivery.process_notification_delivery_intent(
            session, intent_id=intent.id, company_id=company.id, context=None,
        )
        session.commit()
        assert (intent.status, intent.attempts, intent.provider_event_id) == snapshot
    audit.record("notification_winner_verified", winner=winner, calls=len(calls),
                 company_active=False, parent_unchanged=True, intent=snapshot, events=events)


@pytest.mark.parametrize("target", ["employee", "portal", "external"])
@pytest.mark.parametrize("winner", ["disable", "claim"])
def test_company_disable_and_external_claim_have_native_winner_order(
    finalizer_audit, monkeypatch, target, winner,
):
    audit = finalizer_audit
    company_locked, provider_entered, provider_release, disabled = (Event() for _ in range(4))
    calls, worker_session = [], {}
    monkeypatch.setattr(delivery, "get_settings", lambda: SimpleNamespace(
        notification_external_delivery_enabled=True,
        notification_external_delivery_provider="sendgrid",
        sendgrid_api_key="deterministic-local-provider",
        sendgrid_sender_email="local@example.test",
    ))
    fixture = _seed_intent(audit, target)

    def send(**_kwargs):
        session = worker_session["session"]
        assert not session.in_transaction(), "Provider transport retained a SQL transaction"
        activity = audit.snapshot()
        assert not any(row["application_name"] == audit.names["worker"] and row["xact_start"]
                       for row in activity)
        provider_id = "local-race-" + uuid4().hex
        calls.append(provider_id)
        audit.record("transaction_free_provider", calls=len(calls), activity=activity,
                     in_transaction=session.in_transaction())
        provider_entered.set()
        assert provider_release.wait(8), "Deterministic provider boundary was not released"
        assert disabled.is_set(), "Late disablement did not commit before provider completion"
        return True, provider_id, None

    monkeypatch.setattr(communications, "_send_via_sendgrid", send)

    def pause_company(connection, _cursor, sql, _parameters, _context, _many):
        if (winner == "claim" and connection.info.get("finalizer_role") == "worker"
                and "FOR NO KEY UPDATE OF companies" in sql and not company_locked.is_set()):
            audit.record("external_company_fenced", pid=audit.pids["worker"], sql=sql)
            company_locked.set()
            assert audit.release.wait(8), "Claim admission boundary was not released"

    def deliver():
        with audit.session("worker") as session:
            warmed = session.get(Company, fixture["company_id"])
            assert warmed.is_active, "Establish the advisory identity before disable commits"
            worker_session["session"] = session
            result = delivery.process_notification_delivery_intent(
                session, intent_id=fixture["intent_id"], company_id=fixture["company_id"],
                context=None,
            )
            session.commit()
            audit.record("worker_returned", delivered=result.delivered)
            return result

    def disable():
        with audit.session("revocation") as session:
            company = session.scalar(select(Company).where(
                Company.id == fixture["company_id"],
            ).with_for_update(of=Company, key_share=True).execution_options(populate_existing=True))
            assert company.is_active
            company.is_active = False
            session.flush()
            if winner == "disable":
                company_locked.set()
                assert audit.release.wait(8), "Disable admission boundary was not released"
            session.commit()
            disabled.set()
            audit.record("company_disable_committed", pid=audit.pids["revocation"])

    event.listen(audit.engine, "after_cursor_execute", pause_company)
    try:
        with audit.pool() as (pool, futures):
            try:
                first = pool.submit(disable if winner == "disable" else deliver)
                futures.append(first)
                assert company_locked.wait(4), "First contender did not own Company admission"
                second = pool.submit(deliver if winner == "disable" else disable)
                futures.append(second)
                waiter, holder = ("worker", "revocation") if winner == "disable" else (
                    "revocation", "worker",
                )
                audit.await_blocker(waiter, holder)
                if winner == "disable":
                    assert not provider_entered.is_set() and not calls
                    pending_locks = audit.statements["worker"]
                    assert sum("FOR " in sql for sql in pending_locks) == 1
                    assert "FOR NO KEY UPDATE OF companies" in pending_locks[-1]
                    audit.release.set()
                    first.result(timeout=4)
                    result = second.result(timeout=4)
                    assert not result.delivered
                else:
                    audit.release.set()
                    assert provider_entered.wait(4), "External dispatch did not reach transport"
                    second.result(timeout=4)
                    assert disabled.is_set()
                    with Session(audit.engine) as observer:
                        claimed = observer.get(NotificationDeliveryIntent, fixture["intent_id"])
                        assert claimed.status == "sent" and claimed.attempts == 1
                        assert claimed.provider_event_id.startswith(
                            delivery.NOTIFICATION_DISPATCH_CLAIM_PREFIX,
                        )
                        assert not observer.get(Company, fixture["company_id"]).is_active
                        audit.record("authorized_claim_retained_after_disable",
                                     attempts=claimed.attempts, status=claimed.status,
                                     company_active=False)
                    provider_release.set()
                    assert first.result(timeout=4).delivered
            finally:
                audit.release.set()
                provider_release.set()
    finally:
        event.remove(audit.engine, "after_cursor_execute", pause_company)
    _lock_order(audit, target)
    _read_back(audit, fixture, winner, calls)
    assert not audit.errors


def test_in_app_delivery_does_not_add_a_company_or_employee_lock(finalizer_audit, monkeypatch):
    audit = finalizer_audit
    fixture = _seed_intent(audit, "matter")
    company_locked = Event()

    def forbidden_transport(**_kwargs):
        raise AssertionError("In-app delivery attempted external transport")

    monkeypatch.setattr(communications, "_send_via_sendgrid", forbidden_transport)

    def hold_company():
        with audit.session("revocation") as session:
            assert session.scalar(select(Company).where(
                Company.id == fixture["company_id"],
            ).with_for_update(of=Company, key_share=True)) is not None
            company_locked.set()
            assert audit.release.wait(8), "In-app lock counterproof was not released"
            session.commit()

    def deliver():
        with audit.session("worker") as session:
            result = delivery.process_notification_delivery_intent(
                session, intent_id=fixture["intent_id"], company_id=fixture["company_id"],
                context=None,
            )
            session.commit()
            return result

    with audit.pool() as (pool, futures):
        try:
            holder = pool.submit(hold_company)
            futures.append(holder)
            assert company_locked.wait(4)
            worker = pool.submit(deliver)
            futures.append(worker)
            assert worker.result(timeout=4).delivered
            assert not holder.done(), "Company holder must still own the counterproof lock"
            audit.record("in_app_completed_while_company_locked", activity=audit.snapshot())
            _lock_order(audit, "employee", internal=True)
        finally:
            audit.release.set()
        holder.result(timeout=4)
    with Session(audit.engine) as session:
        assert session.get(Company, fixture["company_id"]).is_active
        assert session.scalar(select(func.count()).select_from(InAppNotification).where(
            InAppNotification.company_id == fixture["company_id"],
        )) == 1
    assert not audit.errors
