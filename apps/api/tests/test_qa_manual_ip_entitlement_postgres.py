"""Real PostgreSQL operator guards and tenant-first concurrent receipt/revocation fences."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, object_session

from caseops_api.db.models import (
    AuditEvent,
    BillingSubscription,
    Company,
)
from caseops_api.services import qa_manual_ip_entitlement as operator
from tests import test_qa_manual_ip_entitlement as cases

pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("_ensure_migrations")]


@pytest.fixture
def owned_engine(http_pg_engine):
    """Canonical isolated database from a separately migrated, connection-disabled template."""
    return http_pg_engine


def test_native_canonical_audit_exact_receipt_and_replay(owned_engine, monkeypatch):
    assert owned_engine.dialect.name == "postgresql"
    cases.test_grant_uses_canonical_audit_with_exact_receipt_metadata(owned_engine, monkeypatch)


def test_native_canonical_audit_failure_after_flush_rolls_back(owned_engine, monkeypatch):
    assert owned_engine.dialect.name == "postgresql"
    cases.test_canonical_audit_failure_after_flush_rolls_back_grant(owned_engine, monkeypatch)


def test_native_canonical_audit_default_explicit_identity_and_rollback(owned_engine):
    assert owned_engine.dialect.name == "postgresql"
    cases.test_canonical_audit_identity_preserves_default_and_caller_rollback(owned_engine)


def test_native_canonical_audit_identity_collision(owned_engine):
    assert owned_engine.dialect.name == "postgresql"
    cases.test_canonical_audit_identity_collision_never_overwrites(owned_engine)


@pytest.mark.parametrize("status", ["active", "trialing", "grace", "manual_active"])
def test_native_grant_preserves_actual_plan_status_and_effective_gate(owned_engine, status):
    cases.test_grant_preserves_plan_status_provider_other_keys_and_effective_gate(
        owned_engine, status
    )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("slug", "foreign", "tenant_identity_mismatch"),
        ("is_active", False, "tenant_identity_mismatch"),
        ("tenant_key", "drifted", "before_fingerprint_mismatch"),
    ],
)
def test_native_identity_drift(owned_engine, field, value, code):
    cases.test_identity_drift_refuses_before_write(owned_engine, field, value, code)


@pytest.mark.parametrize(
    "status,billable,code",
    [
        ("manual_active", True, "subscription_is_billable"),
        ("cancelled", False, "active_subscription_not_unique"),
    ],
)
def test_native_billable_and_inactive_refused(owned_engine, status, billable, code):
    cases.test_billable_or_inactive_subscription_is_not_repaired(
        owned_engine, status, billable, code
    )


def test_native_subscription_and_other_tenant_scope(owned_engine):
    cases.test_subscription_drift_and_other_tenant_never_granted(owned_engine)


@pytest.mark.parametrize(
    "field",
    [
        "company_id",
        "action",
        "target_type",
        "target_id",
        "result",
        "actor_type",
        "actor_label",
        "request_id",
        "metadata_json",
    ],
)
def test_native_receipt_collision(owned_engine, field):
    cases.test_deterministic_receipt_collision_is_rejected(owned_engine, field)


def test_native_atomic_audit_rollback(owned_engine):
    cases.test_audit_failure_rolls_back_grant(owned_engine)


def test_native_autocommit_binding_is_rejected_before_locks_or_writes(owned_engine):
    company_id, subscription_id, _ = cases._seed(owned_engine)
    request = cases._request(owned_engine, company_id, subscription_id)
    before = cases._state(owned_engine, subscription_id)
    with pytest.raises(operator.QaManualIpGrantError, match="autocommit_connection_not_allowed"):
        cases._grant(owned_engine.execution_options(isolation_level="AUTOCOMMIT"), request)
    assert cases._state(owned_engine, subscription_id) == before
    with Session(owned_engine) as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_native_external_caller_transaction_remains_committable(owned_engine):
    company_id, subscription_id, _ = cases._seed(owned_engine)
    request = cases._request(owned_engine, company_id, subscription_id)
    with owned_engine.begin() as connection:
        connection.execute(
            BillingSubscription.__table__.update()
            .where(
                BillingSubscription.id == subscription_id,
            )
            .values(metadata_json={"caller": True})
        )
        with Session(bind=connection) as session:
            with pytest.raises(operator.QaManualIpGrantError, match="caller_transaction_not_owned"):
                operator.grant_qa_manual_ip_entitlement(session, **request)
            assert connection.in_transaction()
    after = cases._state(owned_engine, subscription_id)
    assert after["metadata_json"] == {"caller": True}
    assert "ip_workspace" not in after["entitlement_overrides_json"]


def test_native_grant_budgets_precede_tenant_lock_and_do_not_change_defaults(owned_engine):
    company_id, subscription_id, _ = cases._seed(owned_engine)
    request = cases._request(owned_engine, company_id, subscription_id)
    commands = [
        "SHOW lock_timeout",
        "SHOW statement_timeout",
        "SHOW idle_in_transaction_session_timeout",
    ]
    with owned_engine.connect() as connection:
        before = [connection.scalar(text(command)) for command in commands]
    observed = []

    def capture(connection, _cursor, statement, _parameters, _context, _many):
        if "companies" in statement.lower() and "for update" in statement.lower():
            observed.append([connection.scalar(text(command)) for command in commands])

    event.listen(owned_engine, "before_cursor_execute", capture)
    try:
        cases._grant(owned_engine, request)
    finally:
        event.remove(owned_engine, "before_cursor_execute", capture)
    assert observed == [["3s", "10s", "15s"]]
    with owned_engine.connect() as connection:
        assert [connection.scalar(text(command)) for command in commands] == before


@pytest.mark.parametrize("revoked", [False, None])
def test_native_consumed_operation_cannot_regrant(owned_engine, revoked):
    cases.test_consumed_operation_never_regrants_after_revocation(owned_engine, revoked)


def test_native_ambiguous_legacy_active_rows_refused(owned_engine):
    company_id, subscription_id, _ = cases._seed(owned_engine)
    request = cases._request(owned_engine, company_id, subscription_id)
    import re

    assert re.fullmatch(r"caseops_http_[0-9a-f]{32}", owned_engine.url.database)
    # Remove only this isolated test database's partial index to model corrupt legacy state.
    with owned_engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_billing_subscriptions_company_active"))
    with Session(owned_engine) as session, session.begin():
        session.add(
            BillingSubscription(
                company_id=company_id,
                status="active",
                segment="law_firm",
                externally_billable=False,
            )
        )
    with pytest.raises(operator.QaManualIpGrantError, match="active_subscription_not_unique"):
        cases._grant(owned_engine, request)


def test_native_inspection_is_repeatable_read_read_only_and_rolls_back(owned_engine, monkeypatch):
    company_id, subscription_id, _ = cases._seed(owned_engine)
    original = operator._fingerprint
    observed = []
    commits = []

    def inspect_transaction(company, subscription):
        session = object_session(company)
        observed.append(
            (
                session.scalar(text("SHOW transaction_read_only")),
                session.scalar(text("SHOW transaction_isolation")),
                session.scalar(text("SHOW statement_timeout")),
            )
        )
        return original(company, subscription)

    def committed(_connection):
        commits.append(True)

    event.listen(owned_engine, "commit", committed)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(operator, "_fingerprint", inspect_transaction)
            request = cases._request(owned_engine, company_id, subscription_id)
        assert observed == [("on", "repeatable read", "10s")]
        assert commits == []
    finally:
        event.remove(owned_engine, "commit", committed)

    def forbidden_write(company, _subscription):
        object_session(company).execute(Company.__table__.update().values(is_active=False))

    with monkeypatch.context() as patch:
        patch.setattr(operator, "_fingerprint", forbidden_write)
        with Session(owned_engine) as session, pytest.raises(DBAPIError) as caught:
            operator.inspect_qa_manual_ip_entitlement(
                session, company_id=company_id, subscription_id=subscription_id
            )
        assert caught.value.orig.sqlstate == "25006"
    assert not cases._grant(owned_engine, request).replayed


def _wait_for_edge(engine, blocked_pid, blocker_pid):
    deadline = time.monotonic() + 2
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            if (
                blocker_pid
                in observer.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": blocked_pid}
                ).scalar_one()
            ):
                return
            time.sleep(0.01)
    raise AssertionError("Expected directed PostgreSQL Company-lock edge was not observed")


def _pid_recorder(engine):
    pids, mutex = [], Lock()
    ready = Event()

    def capture(connection, _cursor, statement, _parameters, _context, _many):
        if "companies" in statement.lower() and "for update" in statement.lower():
            pid = connection.scalar(text("SELECT pg_backend_pid()"))
            with mutex:
                pids.append(pid)
                ready.set()

    event.listen(engine, "before_cursor_execute", capture)
    return pids, ready, capture


def test_native_concurrent_replay_has_one_atomic_receipt(owned_engine, record_property):
    company_id, subscription_id, _ = cases._seed(owned_engine)
    request = cases._request(owned_engine, company_id, subscription_id)
    entered, release = Event(), Event()
    pids, ready, capture = _pid_recorder(owned_engine)

    def pause(_mapper, _connection, target):
        if target.request_id == request["operation_id"]:
            entered.set()
            assert release.wait(8), "Native receipt boundary was not released"

    event.listen(AuditEvent, "before_insert", pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(cases._grant, owned_engine, request)
            try:
                assert entered.wait(5)
                assert len(pids) == 1
                ready.clear()
                second = workers.submit(cases._grant, owned_engine, request)
                assert ready.wait(2)
                assert len(pids) == 2 and pids[0] != pids[1]
                _wait_for_edge(owned_engine, pids[1], pids[0])
                record_property("writer_pid", pids[0])
                record_property("replay_pid", pids[1])
            finally:
                release.set()
            original, replay = first.result(timeout=10), second.result(timeout=10)
        assert original.replayed is False and replay.replayed is True
        assert original.audit_event_id == replay.audit_event_id
        assert original.after_sha256 == replay.after_sha256
        with Session(owned_engine) as session:
            assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
    finally:
        release.set()
        event.remove(AuditEvent, "before_insert", pause)
        event.remove(owned_engine, "before_cursor_execute", capture)


def test_native_concurrent_revocation_wins_over_consumed_replay(owned_engine, record_property):
    company_id, subscription_id, _ = cases._seed(owned_engine)
    request = cases._request(owned_engine, company_id, subscription_id)
    receipt = cases._grant(owned_engine, request)
    with Session(owned_engine) as revoker:
        revoker.scalar(select(Company).where(Company.id == company_id).with_for_update())
        revoker_pid = revoker.scalar(text("SELECT pg_backend_pid()"))
        pids, ready, capture = _pid_recorder(owned_engine)
        try:
            with ThreadPoolExecutor(max_workers=1) as workers:
                replay = workers.submit(cases._grant, owned_engine, request)
                try:
                    assert ready.wait(2) and len(pids) == 1
                    _wait_for_edge(owned_engine, pids[0], revoker_pid)
                    row = revoker.get(BillingSubscription, subscription_id)
                    overrides = dict(row.entitlement_overrides_json)
                    overrides["ip_workspace"] = False
                    row.entitlement_overrides_json = overrides
                    record_property("revoker_pid", revoker_pid)
                    record_property("replay_pid", pids[0])
                    revoker.commit()
                finally:
                    revoker.rollback()
                with pytest.raises(
                    operator.QaManualIpGrantError, match="consumed_operation_state_changed"
                ):
                    replay.result(timeout=10)
        finally:
            event.remove(owned_engine, "before_cursor_execute", capture)
    with Session(owned_engine) as session:
        assert (
            session.get(BillingSubscription, subscription_id).entitlement_overrides_json[
                "ip_workspace"
            ]
            is False
        )
        assert session.get(AuditEvent, receipt.audit_event_id) is not None
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_native_full_ip_grant_entitles_every_ip_feature(owned_engine):
    from tests import test_qa_full_ip_entitlement as full_cases

    assert owned_engine.dialect.name == "postgresql"
    full_cases.test_full_ip_grant_entitles_every_ip_feature_and_preserves_everything_else(
        owned_engine
    )


def test_native_full_ip_replay_is_idempotent_and_never_regrants(owned_engine):
    from tests import test_qa_full_ip_entitlement as full_cases

    full_cases.test_full_ip_replay_is_idempotent_and_never_regrants_after_revocation(owned_engine)


def test_native_full_ip_grant_targets_test_legal_only(owned_engine):
    from tests import test_qa_full_ip_entitlement as full_cases

    full_cases.test_full_ip_grant_targets_test_legal_only(owned_engine)


def test_native_operation_id_is_consumed_by_one_entitlement_set(owned_engine):
    from tests import test_qa_full_ip_entitlement as full_cases

    full_cases.test_an_operation_id_is_consumed_by_exactly_one_entitlement_set(owned_engine)
