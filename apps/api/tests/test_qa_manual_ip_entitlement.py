"""One-shot operator admission, immutable receipts, and actual effective entitlements."""

from __future__ import annotations

import copy
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, Lock
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from caseops_api.db.models import (
    AuditEvent,
    BillingPlanEntitlement,
    BillingPlanVersion,
    BillingSubscription,
    Company,
)
from caseops_api.scripts import qa_manual_ip_entitlement as cli
from caseops_api.services import qa_manual_ip_entitlement as operator
from caseops_api.services.saas_billing import current_entitlements_for_company


@pytest.fixture
def operator_engine(_migrated_template_db, tmp_path):
    path = tmp_path / "operator.db"
    shutil.copyfile(_migrated_template_db, path)
    engine = create_engine(
        f"sqlite+pysqlite:///{path.as_posix()}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        yield engine
    finally:
        engine.dispose()


def _seed(engine, *, status="manual_active", billable=False, slug="test-legal"):
    company_id, subscription_id, plan_id = (str(uuid4()) for _ in range(3))
    with Session(engine) as session, session.begin():
        session.add(
            Company(
                id=company_id,
                name="Synthetic operator fixture",
                slug=slug,
                tenant_key=f"fixture-{company_id}",
                company_type="law_firm",
            )
        )
        session.add(
            BillingPlanVersion(
                id=plan_id,
                plan_code=f"fixture-{plan_id}",
                version="operator-test",
                segment="law_firm",
                display_name="Retained fixture plan",
            )
        )
        session.flush()
        session.add_all(
            [
                BillingPlanEntitlement(
                    plan_version_id=plan_id,
                    entitlement_key="ip_workspace",
                    value_type="boolean",
                    value_json=False,
                ),
                BillingPlanEntitlement(
                    plan_version_id=plan_id,
                    entitlement_key="gba_workspace",
                    value_type="boolean",
                    value_json=False,
                ),
                BillingSubscription(
                    id=subscription_id,
                    company_id=company_id,
                    plan_version_id=plan_id,
                    status=status,
                    segment="law_firm",
                    billing_interval="custom",
                    externally_billable=billable,
                    source="grandfathered_runtime",
                    provider="retained-offline",
                    provider_customer_id="retained-customer",
                    provider_subscription_id="retained-subscription",
                    entitlement_overrides_json={
                        "other_feature": {"limit": 7},
                        "paid_provider": False,
                    },
                    metadata_json={"retained": [1, "unchanged"]},
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            ]
        )
    return company_id, subscription_id, plan_id


def _request(engine, company_id, subscription_id):
    with Session(engine) as session:
        inspected = operator.inspect_qa_manual_ip_entitlement(
            session,
            company_id=company_id,
            subscription_id=subscription_id,
        )
        assert not session.in_transaction()
    return {
        "company_id": company_id,
        "subscription_id": subscription_id,
        "expected_before_sha256": inspected.before_sha256,
        "operation_id": str(uuid4()),
    }


def _state(engine, subscription_id):
    with Session(engine) as session:
        row = session.get(BillingSubscription, subscription_id)
        return copy.deepcopy(
            {
                column.key: getattr(row, column.key)
                for column in BillingSubscription.__table__.columns
            }
        )


def _grant(engine, request):
    with Session(engine) as session:
        receipt = operator.grant_qa_manual_ip_entitlement(session, **request)
        assert not session.in_transaction()
        return receipt


def _assert_preserved(engine, request, before):
    after = _state(engine, request["subscription_id"])
    assert after.pop("updated_at") > before["updated_at"]
    old = copy.deepcopy(before)
    old.pop("updated_at")
    overrides = old.pop("entitlement_overrides_json")
    assert after.pop("entitlement_overrides_json") == {**overrides, "ip_workspace": True}
    assert after == old
    with Session(engine) as session:
        assert current_entitlements_for_company(session, request["company_id"]) == {
            "ip_workspace": True,
            "gba_workspace": False,
            "other_feature": {"limit": 7},
            "paid_provider": False,
        }


@pytest.mark.parametrize("status", ["active", "trialing", "grace", "manual_active"])
def test_grant_preserves_plan_status_provider_other_keys_and_effective_gate(
    operator_engine, status
):
    company_id, subscription_id, _ = _seed(operator_engine, status=status)
    request = _request(operator_engine, company_id, subscription_id)
    before = _state(operator_engine, subscription_id)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement.lower())

    event.listen(operator_engine, "before_cursor_execute", capture)
    try:
        receipt = _grant(operator_engine, request)
        _assert_preserved(operator_engine, request, before)
    finally:
        event.remove(operator_engine, "before_cursor_execute", capture)
    assert not receipt.replayed
    assert len(statements) == 2
    assert statements[0].startswith("update ")
    assert "billing_subscriptions set entitlement_overrides_json=" in statements[0]
    assert "updated_at=" in statements[0]
    assert statements[1].startswith("insert into ") and "audit_events" in statements[1]
    assert (
        _request(operator_engine, company_id, subscription_id)["expected_before_sha256"]
        == receipt.after_sha256
    )


def test_identical_replay_is_noop_and_receipt_is_immutable(operator_engine):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    first = _grant(operator_engine, request)
    after = _state(operator_engine, subscription_id)
    with Session(operator_engine) as session:
        original_receipt = session.get(AuditEvent, first.audit_event_id).metadata_json
    replay = _grant(operator_engine, request)
    assert replay.replayed
    assert replay.audit_event_id == first.audit_event_id
    assert replay.after_sha256 == first.after_sha256
    assert _state(operator_engine, subscription_id) == after
    with Session(operator_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.company_id == company_id,
                )
            )
            == 1
        )
        assert session.get(AuditEvent, first.audit_event_id).metadata_json == original_receipt


def test_sqlite_concurrent_replay_has_one_receipt(operator_engine):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    entered, attempting, release = Event(), Event(), Event()
    begins, mutex = [], Lock()

    def beginning(_connection, _cursor, statement, _parameters, _context, _many):
        if statement == "BEGIN IMMEDIATE":
            with mutex:
                begins.append(True)
                if len(begins) == 2:
                    attempting.set()

    def pause(_mapper, _connection, target):
        if target.request_id == request["operation_id"]:
            entered.set()
            assert release.wait(8), "SQLite receipt boundary was not released"

    event.listen(operator_engine, "before_cursor_execute", beginning)
    event.listen(AuditEvent, "before_insert", pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(_grant, operator_engine, request)
            try:
                assert entered.wait(5)
                second = workers.submit(_grant, operator_engine, request)
                assert attempting.wait(2)
                assert not second.done()
            finally:
                release.set()
            original, replay = first.result(timeout=10), second.result(timeout=10)
        assert original.replayed is False and replay.replayed is True
        assert original.audit_event_id == replay.audit_event_id
        assert original.after_sha256 == replay.after_sha256
        with Session(operator_engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.company_id == company_id,
                    )
                )
                == 1
            )
    finally:
        release.set()
        event.remove(operator_engine, "before_cursor_execute", beginning)
        event.remove(AuditEvent, "before_insert", pause)


@pytest.mark.parametrize("revoked", [False, None])
def test_consumed_operation_never_regrants_after_revocation(operator_engine, revoked):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    receipt = _grant(operator_engine, request)
    with Session(operator_engine) as session, session.begin():
        row = session.get(BillingSubscription, subscription_id)
        overrides = dict(row.entitlement_overrides_json)
        if revoked is None:
            overrides.pop("ip_workspace")
        else:
            overrides["ip_workspace"] = revoked
        row.entitlement_overrides_json = overrides
    revoked_state = _state(operator_engine, subscription_id)
    with pytest.raises(operator.QaManualIpGrantError, match="consumed_operation_state_changed"):
        _grant(operator_engine, request)
    assert _state(operator_engine, subscription_id) == revoked_state
    with Session(operator_engine) as session:
        assert session.get(AuditEvent, receipt.audit_event_id) is not None
        assert current_entitlements_for_company(session, company_id)["ip_workspace"] is False


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("slug", "not-test-legal", "tenant_identity_mismatch"),
        ("is_active", False, "tenant_identity_mismatch"),
        ("tenant_key", "changed-tenant-key", "before_fingerprint_mismatch"),
    ],
)
def test_identity_drift_refuses_before_write(operator_engine, field, value, code):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    with Session(operator_engine) as session, session.begin():
        setattr(session.get(Company, company_id), field, value)
    before = _state(operator_engine, subscription_id)
    with pytest.raises(operator.QaManualIpGrantError, match=code):
        _grant(operator_engine, request)
    assert _state(operator_engine, subscription_id) == before


@pytest.mark.parametrize(
    "status,billable,code",
    [
        ("manual_active", True, "subscription_is_billable"),
        ("cancelled", False, "active_subscription_not_unique"),
    ],
)
def test_billable_or_inactive_subscription_is_not_repaired(operator_engine, status, billable, code):
    company_id, subscription_id, _ = _seed(operator_engine, status=status, billable=billable)
    with (
        Session(operator_engine) as session,
        pytest.raises(operator.QaManualIpGrantError, match=code),
    ):
        operator.inspect_qa_manual_ip_entitlement(
            session, company_id=company_id, subscription_id=subscription_id
        )
    with (
        Session(operator_engine) as session,
        pytest.raises(operator.QaManualIpGrantError, match=code),
    ):
        operator.grant_qa_manual_ip_entitlement(
            session,
            company_id=company_id,
            subscription_id=subscription_id,
            expected_before_sha256="0" * 64,
            operation_id=str(uuid4()),
        )


def test_subscription_drift_and_other_tenant_never_granted(operator_engine):
    company_id, subscription_id, _ = _seed(operator_engine)
    foreign_id, foreign_subscription_id, _ = _seed(operator_engine, slug="foreign-fixture")
    request = _request(operator_engine, company_id, subscription_id)
    foreign_before = _state(operator_engine, foreign_subscription_id)
    for changed, code in [
        ({"subscription_id": foreign_subscription_id}, "subscription_identity_mismatch"),
        ({"company_id": foreign_id}, "tenant_identity_mismatch"),
        ({"expected_before_sha256": "0" * 64}, "before_fingerprint_mismatch"),
    ]:
        with pytest.raises(operator.QaManualIpGrantError, match=code):
            _grant(operator_engine, {**request, **changed})
    assert _state(operator_engine, foreign_subscription_id) == foreign_before
    assert (
        "ip_workspace" not in _state(operator_engine, subscription_id)["entitlement_overrides_json"]
    )


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
def test_deterministic_receipt_collision_is_rejected(operator_engine, field):
    company_id, subscription_id, _ = _seed(operator_engine)
    foreign_id, _, _ = _seed(operator_engine, slug="foreign-fixture")
    request = _request(operator_engine, company_id, subscription_id)
    audit_id = str(
        uuid5(NAMESPACE_URL, f"caseops:qa-manual-ip-entitlement:{request['operation_id']}")
    )
    values = dict(
        id=audit_id,
        company_id=company_id,
        action="qa.test_legal.manual_ip_granted",
        target_type="billing_subscription",
        target_id=subscription_id,
        actor_type="system",
        actor_label="qa_manual_ip_entitlement",
        result="success",
        request_id=request["operation_id"],
        metadata_json=json.dumps(
            {
                "schema_version": 1,
                "operation_id": request["operation_id"],
                "request_sha256": operator._digest({"schema_version": 1, **request}),
                "before_sha256": request["expected_before_sha256"],
                "after_sha256": request["expected_before_sha256"],
            }
        ),
    )
    values[field] = foreign_id if field == "company_id" else "wrong-receipt"
    with Session(operator_engine) as session, session.begin():
        session.add(AuditEvent(**values))
    before = _state(operator_engine, subscription_id)
    with pytest.raises(operator.QaManualIpGrantError, match="operation_receipt_mismatch"):
        _grant(operator_engine, request)
    assert _state(operator_engine, subscription_id) == before


def test_replay_input_or_after_fingerprint_drift_refuses(operator_engine):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    _grant(operator_engine, request)
    with pytest.raises(operator.QaManualIpGrantError, match="operation_receipt_mismatch"):
        _grant(operator_engine, {**request, "expected_before_sha256": "0" * 64})
    with Session(operator_engine) as session, session.begin():
        row = session.get(BillingSubscription, subscription_id)
        row.metadata_json = {"drift": True}
    drifted = _state(operator_engine, subscription_id)
    with pytest.raises(operator.QaManualIpGrantError, match="consumed_operation_state_changed"):
        _grant(operator_engine, request)
    assert _state(operator_engine, subscription_id) == drifted


def test_already_granted_new_operation_records_without_subscription_write(operator_engine):
    company_id, subscription_id, _ = _seed(operator_engine)
    with Session(operator_engine) as session, session.begin():
        row = session.get(BillingSubscription, subscription_id)
        row.entitlement_overrides_json = {**row.entitlement_overrides_json, "ip_workspace": True}
    before = _state(operator_engine, subscription_id)
    request = _request(operator_engine, company_id, subscription_id)
    receipt = _grant(operator_engine, request)
    assert receipt.before_sha256 == receipt.after_sha256
    assert _state(operator_engine, subscription_id) == before
    assert _grant(operator_engine, request).replayed


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("company_id", "invalid", "invalid_identifier"),
        ("operation_id", "invalid", "invalid_identifier"),
        ("expected_before_sha256", "invalid", "invalid_fingerprint"),
    ],
)
def test_invalid_request_never_queries_or_mutates(operator_engine, field, value, code):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    with Session(operator_engine) as session:
        with pytest.raises(operator.QaManualIpGrantError, match=code):
            operator.grant_qa_manual_ip_entitlement(session, **{**request, field: value})
        assert not session.in_transaction()


def test_audit_failure_rolls_back_grant(operator_engine):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    before = _state(operator_engine, subscription_id)

    def fail(_mapper, _connection, _target):
        raise RuntimeError("offline audit insertion failure")

    event.listen(AuditEvent, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="offline audit insertion failure"):
            _grant(operator_engine, request)
    finally:
        event.remove(AuditEvent, "before_insert", fail)
    assert _state(operator_engine, subscription_id) == before
    assert not _grant(operator_engine, request).replayed


def test_ambiguous_legacy_subscription_is_rejected(operator_engine):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    # This isolated SQLite database models a corrupt legacy schema, not valid admission.
    with operator_engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_billing_subscriptions_company_active"))
    with Session(operator_engine) as session, session.begin():
        session.add(
            BillingSubscription(
                company_id=company_id,
                status="active",
                segment="law_firm",
                externally_billable=False,
            )
        )
    with pytest.raises(operator.QaManualIpGrantError, match="active_subscription_not_unique"):
        _grant(operator_engine, request)


def test_caller_transaction_is_untouched(operator_engine):
    company_id, subscription_id, _ = _seed(operator_engine)
    request = _request(operator_engine, company_id, subscription_id)
    with Session(operator_engine) as session:
        row = session.get(BillingSubscription, subscription_id)
        row.metadata_json = {"caller": True}
        for function, arguments in [
            (operator.grant_qa_manual_ip_entitlement, request),
            (
                operator.inspect_qa_manual_ip_entitlement,
                {"company_id": company_id, "subscription_id": subscription_id},
            ),
        ]:
            with pytest.raises(operator.QaManualIpGrantError, match="caller_transaction_not_owned"):
                function(session, **arguments)
            assert session.in_transaction()
            assert row in session.dirty
        session.commit()
    assert _state(operator_engine, subscription_id)["metadata_json"] == {"caller": True}


@pytest.mark.parametrize("prior_query_only", [0, 1])
@pytest.mark.parametrize("identity_matches", [True, False])
def test_inspection_restores_exact_connection_before_pool_checkin(
    operator_engine,
    prior_query_only,
    identity_matches,
):
    company_id, subscription_id, _ = _seed(operator_engine)
    with operator_engine.connect() as connection:
        original_driver = connection.connection.driver_connection
        connection.exec_driver_sql(f"PRAGMA query_only = {prior_query_only}")
        connection.rollback()
    checked = []
    commits = []

    def on_checkin(dbapi_connection, _record):
        if dbapi_connection is not None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA query_only")
                checked.append((dbapi_connection is original_driver, cursor.fetchone()[0]))
            finally:
                cursor.close()

    def on_commit(_connection):
        commits.append(True)

    event.listen(operator_engine, "checkin", on_checkin)
    event.listen(operator_engine, "commit", on_commit)
    try:
        with Session(operator_engine) as session:
            if identity_matches:
                operator.inspect_qa_manual_ip_entitlement(
                    session,
                    company_id=company_id,
                    subscription_id=subscription_id,
                )
            else:
                with pytest.raises(
                    operator.QaManualIpGrantError, match="subscription_identity_mismatch"
                ):
                    operator.inspect_qa_manual_ip_entitlement(
                        session,
                        company_id=company_id,
                        subscription_id=str(uuid4()),
                    )
        assert checked == [(True, prior_query_only)]
        assert commits == []
    finally:
        event.remove(operator_engine, "checkin", on_checkin)
        event.remove(operator_engine, "commit", on_commit)


@pytest.mark.parametrize("prior_query_only", [0, 1])
def test_inspection_cleanup_failure_invalidates_connection(operator_engine, prior_query_only):
    company_id, subscription_id, _ = _seed(operator_engine)
    with operator_engine.connect() as connection:
        original_driver = connection.connection.driver_connection
        connection.exec_driver_sql(f"PRAGMA query_only = {prior_query_only}")
        connection.rollback()
    setters, invalidated = [], []

    def fail_cleanup(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("PRAGMA query_only = "):
            setters.append(statement)
            if len(setters) == 2:
                raise RuntimeError("offline SQLite cleanup failure")

    def invalidated_connection(dbapi_connection, _record, _error):
        invalidated.append(dbapi_connection)

    event.listen(operator_engine, "before_cursor_execute", fail_cleanup)
    event.listen(operator_engine, "invalidate", invalidated_connection)
    try:
        with (
            Session(operator_engine) as session,
            pytest.raises(
                RuntimeError,
                match="offline SQLite cleanup failure",
            ),
        ):
            operator.inspect_qa_manual_ip_entitlement(
                session,
                company_id=company_id,
                subscription_id=subscription_id,
            )
        assert invalidated == [original_driver]
        with operator_engine.connect() as connection:
            assert connection.connection.driver_connection is not original_driver
            assert connection.scalar(text("PRAGMA query_only")) == 0
    finally:
        event.remove(operator_engine, "before_cursor_execute", fail_cleanup)
        event.remove(operator_engine, "invalidate", invalidated_connection)


def test_inspection_sqlite_rejects_writes_and_recovers_pool(operator_engine, monkeypatch):
    company_id, subscription_id, _ = _seed(operator_engine)
    original = operator._fingerprint

    def attempt_write(company, subscription):
        from sqlalchemy.orm import object_session

        object_session(company).execute(text("UPDATE companies SET is_active = 0"))
        return original(company, subscription)

    with monkeypatch.context() as patch:
        patch.setattr(operator, "_fingerprint", attempt_write)
        with Session(operator_engine) as session, pytest.raises(DBAPIError):
            operator.inspect_qa_manual_ip_entitlement(
                session, company_id=company_id, subscription_id=subscription_id
            )
    assert not _grant(
        operator_engine, _request(operator_engine, company_id, subscription_id)
    ).replayed


def test_cli_envelopes_exact_and_failures_sanitized(operator_engine, monkeypatch, capsys):
    company_id, subscription_id, _ = _seed(operator_engine)
    monkeypatch.setattr(cli, "get_session_factory", lambda: sessionmaker(operator_engine))
    identifiers = ["--company-id", company_id, "--subscription-id", subscription_id]
    assert cli.main(["inspect", *identifiers]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert set(inspected) == {
        "schema_version",
        "mode",
        "company_id",
        "subscription_id",
        "before_sha256",
    }
    operation_id = str(uuid4())
    args = [
        "grant",
        *identifiers,
        "--expected-before-sha256",
        inspected["before_sha256"],
        "--operation-id",
        operation_id,
    ]
    assert cli.main(args) == 0
    granted = json.loads(capsys.readouterr().out)
    assert set(granted) == {
        "schema_version",
        "mode",
        "company_id",
        "subscription_id",
        "operation_id",
        "request_sha256",
        "before_sha256",
        "after_sha256",
        "audit_event_id",
        "replayed",
    }
    assert granted["replayed"] is False
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["replayed"] is True
    assert cli.main(["inspect", "--private-argument", "private@example.com"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"
    assert capsys.readouterr().err == ""
    monkeypatch.setattr(
        cli,
        "get_session_factory",
        lambda: (_ for _ in ()).throw(RuntimeError("private database URL")),
    )
    assert cli.main(["inspect", *identifiers]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["error"]["code"] == "operator_failed"
    assert "private" not in output.out + output.err
