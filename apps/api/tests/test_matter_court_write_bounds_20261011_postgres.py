"""Newly reconstructed court-write hydration regression, not recovered evidence.

This isolates getter SQL/materialization from complete real write-path SQL. It
does not attribute the earlier Docker manual-sync 55P03 to getter hydration.
Historical orders have different source/date/reference identities: this is not
a claim that an imported-order collision group has bounded work.
"""

from __future__ import annotations

import json
from collections import Counter
from contextlib import contextmanager
from datetime import date, timedelta
from functools import wraps
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    Company,
    InAppNotification,
    Matter,
    MatterActivity,
    MatterAttachment,
    MatterAttachmentChunk,
    MatterCauseListEntry,
    MatterComplianceExtractionRun,
    MatterComplianceItem,
    MatterCourtOrder,
    MatterCourtSyncJob,
    MatterCourtSyncRun,
    MatterDeadline,
    MatterHearing,
    MatterNote,
    MatterProceedingSignal,
    MatterTask,
    ModelRun,
    NotificationDeliveryIntent,
    NotificationRule,
)
from caseops_api.schemas.matters import (
    MatterCourtOrderCreateRequest,
    MatterCourtOrderSyncItem,
    MatterCourtOrderUpdateRequest,
    MatterCourtSyncImportRequest,
    MatterLifecycleStatusRequest,
)
from caseops_api.services import matters
from caseops_api.services.durable_workflows import redact_identifier
from caseops_api.services.matter_write_fence import lock_matter_private_authority
from tests.test_document_finalizer_overlap_20261009_postgres import (
    finalizer_audit as _finalizer_audit_fixture,
)
from tests.test_postgres_validation import (
    _ensure_migrations as _migrations_fixture,
)
from tests.test_postgres_validation import (
    _ip_race_context,
    _seed_company,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
finalizer_audit = _finalizer_audit_fixture
_ensure_migrations = _migrations_fixture
_TEXT = "The parties shall comply within two weeks from today."
_ORDER_DATE = date(2026, 10, 11)
_PATHS = (
    "create_matter_court_order",
    "update_matter_court_order",
    "create_matter_court_sync_import",
)
_HISTORY_MODELS = (
    MatterTask,
    MatterNote,
    MatterHearing,
    MatterActivity,
    MatterCauseListEntry,
    MatterCourtOrder,
    MatterCourtSyncRun,
    MatterCourtSyncJob,
    MatterAttachment,
    MatterAttachmentChunk,
)
_CHILD_RELATIONSHIPS = (
    "tasks",
    "notes",
    "hearings",
    "activity_events",
    "tag_assignments",
    "cause_list_entries",
    "court_orders",
    "court_sync_runs",
    "court_sync_jobs",
    "attachments",
    "time_entries",
    "invoices",
)
_OUTCOME_MODELS = (
    *_HISTORY_MODELS[:-1],
    MatterComplianceExtractionRun,
    MatterComplianceItem,
    MatterProceedingSignal,
    MatterDeadline,
    ModelRun,
    NotificationDeliveryIntent,
    InAppNotification,
    AuditEvent,
)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _row_hashes(session, model, ids):
    # Core columns avoid contaminating the ORM materialization measurement.
    rows = session.execute(
        select(model.__table__).where(model.id.in_(ids)).order_by(model.id)
    ).mappings()
    return {row["id"]: _digest(dict(row)) for row in rows}


def _history_snapshot(session, fixture):
    return {
        model.__tablename__: _row_hashes(session, model, fixture.history_ids[model])
        for model in _HISTORY_MODELS
    }


def _assert_history_retained(audit, fixture):
    with Session(audit.engine) as session:
        current = _history_snapshot(session, fixture)
    # Fail with only counts/hashes, never row contents or original identities.
    changed = [name for name, hashes in current.items() if hashes != fixture.history_hashes[name]]
    audit.record(
        "court_history_retention",
        history_size=fixture.history_size,
        hashes={name: _digest(hashes) for name, hashes in current.items()},
        counts={name: len(hashes) for name, hashes in current.items()},
        changed_tables=changed,
    )
    assert not changed, f"Retained historical rows changed in {changed}"


def _outcome_snapshot(session, fixture):
    result = {}
    for model in _OUTCOME_MODELS:
        rows = session.execute(
            select(model.__table__).where(model.matter_id == fixture.matter_id).order_by(model.id)
        ).mappings()
        result[model.__tablename__] = _digest([dict(row) for row in rows])
    return result


def _seed_history(audit, history_size):
    with Session(audit.engine, expire_on_commit=False) as session:
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        recipient_id = _seed_membership(session, company_id, role="member")
        matter_id = _seed_matter(session, company_id)
        parent = session.get(Matter, matter_id)
        parent.assignee_membership_id = recipient_id
        assert parent.lifecycle_version == 0 and parent.status == "active" and parent.is_active
        session.flush()
        history_ids = {model: [] for model in _HISTORY_MODELS}

        def retain(row):
            row.id = str(uuid4())
            history_ids[type(row)].append(row.id)
            session.add(row)
            return row

        for ordinal in range(history_size):
            historical_date = date(2020, 1, 1) + timedelta(days=ordinal)
            run = retain(
                MatterCourtSyncRun(
                    matter_id=matter_id,
                    triggered_by_membership_id=actor_id,
                    source=f"historical-{ordinal}",
                    status="completed",
                    imported_cause_list_count=1,
                    imported_order_count=1,
                )
            )
            attachment = retain(
                MatterAttachment(
                    matter_id=matter_id,
                    uploaded_by_membership_id=actor_id,
                    original_filename=f"history-{ordinal}.txt",
                    storage_key=f"court-history/{matter_id}/{ordinal}.txt",
                    content_type="text/plain",
                    size_bytes=len(_TEXT),
                    sha256_hex=sha256(_TEXT.encode()).hexdigest(),
                    processing_status="indexed",
                    extracted_text=_TEXT,
                    extracted_char_count=len(_TEXT),
                    document_type="order_judgment",
                )
            )
            # Persist actual FK parents before adding scalar-ID children.
            session.flush()
            retain(
                MatterCourtOrder(
                    matter_id=matter_id,
                    sync_run_id=run.id,
                    order_attachment_id=attachment.id,
                    order_date=historical_date,
                    title=f"Historical order {ordinal}",
                    summary="Retained historical record",
                    order_text=f"Historical text {ordinal}.",
                    source=f"historical-{ordinal}",
                    source_reference=f"historical-ref-{ordinal}",
                )
            )
            retain(
                MatterCauseListEntry(
                    matter_id=matter_id,
                    sync_run_id=run.id,
                    listing_date=historical_date,
                    forum_name="Historical court",
                    source=f"historical-{ordinal}",
                    source_reference=f"historical-listing-{ordinal}",
                )
            )
            retain(
                MatterCourtSyncJob(
                    company_id=company_id,
                    matter_id=matter_id,
                    requested_by_membership_id=actor_id,
                    sync_run_id=run.id,
                    source=f"historical-{ordinal}",
                    status="completed",
                )
            )
            retain(
                MatterAttachmentChunk(
                    attachment_id=attachment.id,
                    chunk_index=0,
                    content=f"Historical chunk {ordinal}.",
                    token_count=4,
                )
            )
            retain(
                MatterTask(
                    company_id=company_id,
                    matter_id=matter_id,
                    created_by_membership_id=actor_id,
                    owner_membership_id=recipient_id,
                    title=f"Historical task {ordinal}",
                    status="completed",
                )
            )
            retain(
                MatterNote(
                    matter_id=matter_id,
                    author_membership_id=actor_id,
                    body=f"Historical note {ordinal}.",
                )
            )
            retain(
                MatterHearing(
                    company_id=company_id,
                    matter_id=matter_id,
                    hearing_on=historical_date,
                    forum_name="Historical court",
                    purpose="Retained history",
                    status="completed",
                )
            )
            retain(
                MatterActivity(
                    matter_id=matter_id,
                    actor_membership_id=actor_id,
                    event_type="history_fixture",
                    title=f"Historical activity {ordinal}",
                    detail="Synthetic retained history",
                )
            )

        target_attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=actor_id,
            original_filename="current-order.txt",
            storage_key=f"court-target/{matter_id}.txt",
            content_type="text/plain",
            size_bytes=len(_TEXT),
            sha256_hex=sha256(_TEXT.encode()).hexdigest(),
            processing_status="indexed",
            extracted_text=_TEXT,
            extracted_char_count=len(_TEXT),
            document_type="order_judgment",
        )
        session.add(target_attachment)
        session.flush()
        target_order = MatterCourtOrder(
            matter_id=matter_id,
            order_date=_ORDER_DATE,
            title="Current order for metadata edit",
            summary="Current source-backed direction",
            source="manual",
            order_text=_TEXT,
        )
        rule = NotificationRule(
            company_id=company_id,
            scope_type="user",
            scope_id=recipient_id,
            event_type="new_order_uploaded",
            channels_json=["in_app"],
            enabled=True,
            created_by_membership_id=actor_id,
        )
        session.add_all([target_order, rule])
        session.commit()
        fixture = SimpleNamespace(
            company_id=company_id,
            actor_id=actor_id,
            recipient_id=recipient_id,
            matter_id=matter_id,
            attachment_id=target_attachment.id,
            order_id=target_order.id,
            rule_id=rule.id,
            history_size=history_size,
            history_ids=history_ids,
        )
        fixture.history_hashes = _history_snapshot(session, fixture)
        assert {len(rows) for rows in fixture.history_hashes.values()} == {history_size}, (
            "Fixture setup did not establish the complete intended history inventory"
        )
        identities = session.execute(
            select(
                MatterCourtOrder.source,
                MatterCourtOrder.order_date,
                MatterCourtOrder.source_reference,
            ).where(MatterCourtOrder.id.in_(history_ids[MatterCourtOrder]))
        ).all()
        assert len(set(identities)) == history_size, "Fixture identity collision is a setup defect"
        for model in (
            MatterComplianceExtractionRun,
            MatterComplianceItem,
            NotificationDeliveryIntent,
        ):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(
                        model.matter_id == matter_id,
                    )
                )
                == 0
            ), "Fixture unexpectedly ran a downstream service during setup"
    audit.record(
        "court_fixture_ready",
        history_size=history_size,
        counts={name: len(rows) for name, rows in fixture.history_hashes.items()},
        hashes={name: _digest(rows) for name, rows in fixture.history_hashes.items()},
        distinct_order_identities=len(set(identities)),
    )
    return fixture


class _CourtProbe:
    def __init__(self, audit, fixture, observer):
        self.audit, self.fixture, self.observer = audit, fixture, observer
        self.statements, self.getters = [], []
        self.materialized, self.historical_materialized = Counter(), Counter()
        self.held_locks = []
        self.current_getter = None
        self.history_keys = {
            (model.__tablename__, row_id)
            for model, ids in fixture.history_ids.items()
            for row_id in ids
        }

    def before(self, connection, _cursor, sql, _parameters, _context, _many):
        if connection.info.get("finalizer_role") != "mutation":
            return
        self.statements.append(sql)
        if self.current_getter is not None:
            self.current_getter["sql"].append(sql)
        # Every statement is counted and retained, not only lock/write templates.
        self.audit.record(
            "court_sql",
            ordinal=len(self.statements),
            getter=self.current_getter is not None,
            sql=sql,
            sql_sha256=sha256(sql.encode()).hexdigest(),
        )

    def loaded(self, _session, instance):
        table = inspect(instance).mapper.local_table.name
        self.materialized[table] += 1
        identity = inspect(instance).identity
        if identity and (table, identity[0]) in self.history_keys:
            self.historical_materialized[table] += 1
        if self.current_getter is not None:
            self.current_getter["orm_loads"][table] += 1

    def assert_locks_held(self):
        for model, identity in (
            (Company, self.fixture.company_id),
            (Matter, self.fixture.matter_id),
        ):
            with Session(self.observer) as session:
                session.execute(text("SET LOCAL lock_timeout = '2s'"))
                session.execute(text("SET LOCAL statement_timeout = '10s'"))
                statement = (
                    select(model.id)
                    .where(model.id == identity)
                    .with_for_update(
                        of=model,
                        nowait=True,
                        key_share=model is Company,
                    )
                )
                with pytest.raises(DBAPIError) as blocked:
                    session.scalar(statement)
                assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
                session.rollback()
            self.held_locks.append(model.__tablename__)
            self.audit.record("court_actual_lock_held", table=model.__tablename__, sqlstate="55P03")

    def assert_preparation_locks_released(self):
        for model, identity in (
            (Company, self.fixture.company_id),
            (Matter, self.fixture.matter_id),
        ):
            with Session(self.observer) as session:
                session.execute(text("SET LOCAL lock_timeout = '2s'"))
                session.execute(text("SET LOCAL statement_timeout = '10s'"))
                acquired = session.scalar(
                    select(model.id)
                    .where(model.id == identity)
                    .with_for_update(of=model, nowait=True)
                )
                assert acquired == identity
                session.rollback()
            self.audit.record("court_preparation_lock_released", table=model.__tablename__)

    @contextmanager
    def getter(self, kwargs):
        assert self.current_getter is None, "Unexpected nested getter invalidates the probe"
        row = {
            "sql": [],
            "statement_start": len(self.statements),
            "orm_loads": Counter(),
            "lock_for_update": kwargs.get("lock_for_update", False),
            "lock_for_share": kwargs.get("lock_for_share", False),
            "load_locked_children": kwargs.get("load_locked_children", True),
            "boundary": (
                "persistence"
                if kwargs.get("lock_for_update") or kwargs.get("lock_for_share")
                else "preparation"
            ),
        }
        self.current_getter = row
        try:
            yield
        finally:
            self.current_getter = None
            row["statement_end"] = len(self.statements)
            self.getters.append(row)
            self.audit.record(
                "court_getter_complete",
                history_size=self.fixture.history_size,
                statement_count=len(row["sql"]),
                orm_loads=dict(row["orm_loads"]),
                load_locked_children=row["load_locked_children"],
                lock_for_update=row["lock_for_update"],
                lock_for_share=row["lock_for_share"],
                boundary=row["boundary"],
                statement_start=row["statement_start"],
                statement_end=row["statement_end"],
            )

    @contextmanager
    def measure(self, session):
        session.info["court_bounds_probe"] = self
        event.listen(self.audit.engine, "before_cursor_execute", self.before)
        event.listen(session, "loaded_as_persistent", self.loaded)
        try:
            yield
        finally:
            event.remove(session, "loaded_as_persistent", self.loaded)
            event.remove(self.audit.engine, "before_cursor_execute", self.before)
            session.info.pop("court_bounds_probe", None)
            self.audit.record(
                "court_operation_complete",
                history_size=self.fixture.history_size,
                statement_count=len(self.statements),
                getter_count=len(self.getters),
                orm_loads=dict(self.materialized),
                historical_orm_loads=dict(self.historical_materialized),
            )


@pytest.fixture
def court_audit(finalizer_audit, _ensure_migrations, monkeypatch):
    audit = finalizer_audit
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "")
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "")
    get_settings.cache_clear()
    original = matters._get_matter_model

    @wraps(original)
    def traced(session, **kwargs):
        probe = session.info.get("court_bounds_probe")
        if probe is None:
            return original(session, **kwargs)
        if not (kwargs.get("lock_for_update") or kwargs.get("lock_for_share")):
            # Match the locked probe's ready transaction/context. Retain every
            # setup statement in the operation, outside the parent-getter window.
            setup_start = len(probe.statements)
            session.connection()
            context = kwargs["context"]
            identities = (context.company.id, context.membership.id, context.user.id)
            assert identities[0] == probe.fixture.company_id
            assert identities[1] == probe.fixture.actor_id
            probe.audit.record(
                "court_getter_context_ready",
                statement_start=setup_start,
                statement_end=len(probe.statements),
                statement_count=len(probe.statements) - setup_start,
            )
            assert len(probe.statements) - setup_start <= 7
        with probe.getter(kwargs):
            result = original(session, **kwargs)
        if kwargs.get("lock_for_update") or kwargs.get("lock_for_share"):
            probe.assert_locks_held()
        else:
            probe.assert_preparation_locks_released()
        return result

    monkeypatch.setattr(matters, "_get_matter_model", traced)
    # A separate engine keeps expected NOWAIT rejections out of the write-error
    # inventory and cannot borrow the writer's labelled PostgreSQL backend.
    observer = create_engine(audit.engine.url, poolclass=NullPool)
    try:
        yield audit, observer
    finally:
        observer.dispose()


def _write(session, context, fixture, path):
    args = {"context": context, "matter_id": fixture.matter_id}
    if path == "create_matter_court_order":
        return matters.create_matter_court_order(
            session,
            **args,
            payload=MatterCourtOrderCreateRequest(
                order_date=_ORDER_DATE,
                title="New source-backed manual order",
                summary="Local deterministic compliance direction",
                source="manual",
                source_reference="current-manual-reference",
                order_text=_TEXT,
                order_attachment_id=fixture.attachment_id,
                order_kind="interim_order",
                is_interim_order=True,
                stay_status="granted",
            ),
        )
    if path == "update_matter_court_order":
        return matters.update_matter_court_order(
            session,
            **args,
            order_id=fixture.order_id,
            payload=MatterCourtOrderUpdateRequest(
                bench_name="Current bench",
                judge_names=["Current judge"],
                order_kind="interim_order",
                is_interim_order=True,
                stay_status="granted",
            ),
        )
    assert path == "create_matter_court_sync_import"
    return matters.create_matter_court_sync_import(
        session,
        **args,
        payload=MatterCourtSyncImportRequest(
            source="local-emulator-current",
            summary="Native local court import",
            orders=[
                MatterCourtOrderSyncItem(
                    order_date=_ORDER_DATE,
                    title="New source-backed imported order",
                    summary="Local deterministic compliance direction",
                    order_text=_TEXT,
                    source_reference="current-import-reference",
                    order_kind="interim_order",
                    is_interim_order=True,
                    stay_status="granted",
                )
            ],
        ),
    )


def _assert_company_first(probe, *, membership_fence=True):
    locks = [sql for sql in probe.statements if " FOR " in sql.upper()]
    assert locks and "FOR NO KEY UPDATE OF companies" in locks[0]
    parent_index = next(
        index
        for index, sql in enumerate(locks)
        if ("FOR UPDATE OF matters" in sql or "FOR SHARE OF matters" in sql)
    )
    assert parent_index > 0
    if membership_fence:
        assert any("FOR UPDATE OF company_memberships" in sql for sql in locks[:parent_index])
        assert any("FOR UPDATE OF users" in sql for sql in locks[:parent_index])
    locked_getters = [
        row for row in probe.getters if row["lock_for_update"] or row["lock_for_share"]
    ]
    assert locked_getters, "No final parent authority fence was observed"
    for row in locked_getters:
        parent_locks = [
            sql
            for sql in row["sql"]
            if ("FOR UPDATE OF matters" in sql or "FOR SHARE OF matters" in sql)
        ]
        assert len(parent_locks) == 1 and " JOIN " not in parent_locks[0].upper()
    for row in probe.getters:
        if row["boundary"] == "preparation":
            assert not any(" FOR " in sql.upper() for sql in row["sql"])
            reacquired = [
                sql for sql in probe.statements[row["statement_end"]:] if " FOR " in sql.upper()
            ]
            assert reacquired and "FOR NO KEY UPDATE OF companies" in reacquired[0]
            final_parent_index = next(
                index for index, sql in enumerate(reacquired) if "FOR UPDATE OF matters" in sql
            )
            assert final_parent_index > 0
            assert any(
                "FOR UPDATE OF company_memberships" in sql
                for sql in reacquired[:final_parent_index]
            )
            assert any("FOR UPDATE OF users" in sql for sql in reacquired[:final_parent_index])


def _assert_outcomes(audit, fixture, path, result, *, replay=False):
    with Session(audit.engine) as session:
        parent = session.get(Matter, fixture.matter_id)
        assert parent.status == "active" and parent.is_active and parent.lifecycle_version == 0
        if path == "create_matter_court_sync_import":
            run = session.get(MatterCourtSyncRun, result.id)
            assert run.status == "completed" and run.triggered_by_membership_id == fixture.actor_id
            assert run.imported_order_count == 1 and run.imported_cause_list_count == 0
            orders = list(
                session.scalars(
                    select(MatterCourtOrder).where(
                        MatterCourtOrder.matter_id == fixture.matter_id,
                        MatterCourtOrder.source == "local-emulator-current",
                    )
                )
            )
            assert len(orders) == 1
            order = orders[0]
            assert (
                order.sync_run_id == result.id
                and order.source_reference == "current-import-reference"
            )
            assert session.scalar(
                select(func.count())
                .select_from(MatterActivity)
                .where(
                    MatterActivity.matter_id == fixture.matter_id,
                    MatterActivity.event_type == "court_sync_imported",
                )
            ) == (2 if replay else 1)
        else:
            order = session.get(MatterCourtOrder, result.id)
            assert order.id == (
                fixture.order_id if path == "update_matter_court_order" else result.id
            )
            assert order.sync_run_id is None
            assert order.order_attachment_id == (
                fixture.attachment_id if path == "create_matter_court_order" else None
            )
            action = (
                "matter_court_order.created"
                if path == "create_matter_court_order"
                else "matter_court_order.metadata.updated"
            )
            audits = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.matter_id == fixture.matter_id,
                        AuditEvent.action == action,
                        AuditEvent.target_id == order.id,
                    )
                )
            )
            assert len(audits) == 1 and audits[0].actor_membership_id == fixture.actor_id
            activity = (
                "court_order_added"
                if path == "create_matter_court_order"
                else "court_order_updated"
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(MatterActivity)
                    .where(
                        MatterActivity.matter_id == fixture.matter_id,
                        MatterActivity.event_type == activity,
                    )
                )
                == 1
            )
        assert order.matter_id == fixture.matter_id and order.order_date == _ORDER_DATE
        assert order.order_text == _TEXT and order.order_kind == "interim_order"
        assert order.is_interim_order and order.stay_status == "granted"
        if path == "create_matter_court_order":
            context = _ip_race_context(
                session, company_id=fixture.company_id, membership_id=fixture.actor_id
            )
            record = matters.get_matter(session, context=context, matter_id=fixture.matter_id)
            assert record.has_interim_order and record.has_stay
            intents = list(
                session.scalars(
                    select(NotificationDeliveryIntent).where(
                        NotificationDeliveryIntent.matter_id == fixture.matter_id,
                        NotificationDeliveryIntent.event_type == "new_order_uploaded",
                    )
                )
            )
            assert len(intents) == 1
            intent = intents[0]
            assert (
                intent.status == "delivered" and intent.channel == "in_app" and intent.attempts == 1
            )
            assert intent.recipient_membership_id == fixture.recipient_id
            assert (
                intent.source_id == fixture.attachment_id
                and intent.metadata_json["linked_court_order_ref"] == redact_identifier(order.id)
                and intent.metadata_json["has_linked_court_order"] is True
            )
            assert intent.notification_rule_id == fixture.rule_id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(InAppNotification)
                    .where(
                        InAppNotification.matter_id == fixture.matter_id,
                        InAppNotification.event_type == "new_order_uploaded",
                        InAppNotification.recipient_membership_id == fixture.recipient_id,
                        InAppNotification.source_id == fixture.attachment_id,
                    )
                )
                == 1
            )
        if path == "update_matter_court_order":
            assert order.bench_name == "Current bench" and order.judge_names_json == [
                "Current judge"
            ]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.matter_id == fixture.matter_id,
                        AuditEvent.target_id == order.id,
                        AuditEvent.action == "matter_court_order.stay.updated",
                    )
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(MatterComplianceExtractionRun)
                    .where(
                        MatterComplianceExtractionRun.matter_id == fixture.matter_id,
                    )
                )
                == 0
            )
        else:
            runs = list(
                session.scalars(
                    select(MatterComplianceExtractionRun).where(
                        MatterComplianceExtractionRun.matter_id == fixture.matter_id,
                        MatterComplianceExtractionRun.court_order_id == order.id,
                    )
                )
            )
            assert len(runs) == (2 if replay else 1)
            assert all(run.status == "completed" and run.skip_reason is None for run in runs)
            assert all(run.created_by_membership_id == fixture.actor_id for run in runs)
            trigger = "manual_order_create" if path == "create_matter_court_order" else "court_sync"
            assert {run.trigger for run in runs} == {trigger}
            items = list(
                session.scalars(
                    select(MatterComplianceItem).where(
                        MatterComplianceItem.matter_id == fixture.matter_id,
                        MatterComplianceItem.court_order_id == order.id,
                    )
                )
            )
            assert items and all(
                item.generated_task_id is None and item.generated_deadline_id is None
                for item in items
            )
            assert all(
                item.source_snippet and item.review_status == "review_required" for item in items
            )
            assert sum(run.metadata_json["created_item_count"] for run in runs) == len(items)
            if replay:
                assert any(run.metadata_json["created_item_count"] == 0 for run in runs)
            audits = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "matter_compliance.extraction.completed",
                        AuditEvent.target_id.in_([run.id for run in runs]),
                    )
                )
            )
            assert len(audits) == len(runs)
            assert all(row.actor_membership_id == fixture.actor_id for row in audits)
            intents = list(
                session.scalars(
                    select(NotificationDeliveryIntent).where(
                        NotificationDeliveryIntent.matter_id == fixture.matter_id,
                        NotificationDeliveryIntent.event_type == "compliance_review_required",
                    )
                )
            )
            assert {intent.source_id for intent in intents} == {item.id for item in items}
            assert len(intents) == len(items)
            assert all(
                intent.recipient_membership_id == fixture.recipient_id
                and intent.channel == "in_app"
                and intent.metadata_json["linked_court_order_ref"] == redact_identifier(order.id)
                and intent.metadata_json["has_linked_court_order"] is True
                for intent in intents
            )
        expected_orders = fixture.history_size + (1 if path == "update_matter_court_order" else 2)
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterCourtOrder)
                .where(
                    MatterCourtOrder.matter_id == fixture.matter_id,
                )
            )
            == expected_orders
        )
        return order.id


def _assert_denied_writes(audit, fixture, path):
    with Session(audit.engine) as session:
        baseline = _outcome_snapshot(session, fixture)
    # A warmed context must not bypass current ACL changes committed elsewhere.
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session, company_id=fixture.company_id, membership_id=fixture.actor_id
        )
        cached_parent = session.get(Matter, fixture.matter_id)
        assert not cached_parent.restricted_access
        with Session(audit.engine) as other:
            other.get(Matter, fixture.matter_id).restricted_access = True
            other.commit()
        with pytest.raises(HTTPException) as denied:
            _write(session, context, fixture, path)
        assert denied.value.status_code == 404 and denied.value.detail == "Matter not found."
        session.rollback()
    with Session(audit.engine) as session:
        assert _outcome_snapshot(session, fixture) == baseline
        session.get(Matter, fixture.matter_id).restricted_access = False
        other_company = _seed_company(session)
        other_actor = _seed_membership(session, other_company, role="admin")
        session.commit()
    with audit.session("mutation") as session:
        context = _ip_race_context(session, company_id=other_company, membership_id=other_actor)
        with pytest.raises(HTTPException) as denied:
            _write(session, context, fixture, path)
        assert denied.value.status_code == 404 and denied.value.detail == "Matter not found."
        session.rollback()
    with Session(audit.engine) as session:
        assert _outcome_snapshot(session, fixture) == baseline
    # Keep the actual cached active parent alive while the lifecycle command wins.
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session, company_id=fixture.company_id, membership_id=fixture.actor_id
        )
        cached_parent = session.get(Matter, fixture.matter_id)
        assert cached_parent.status == "active" and cached_parent.lifecycle_version == 0
        with audit.session("revocation") as other:
            other_context = _ip_race_context(
                other, company_id=fixture.company_id, membership_id=fixture.actor_id
            )
            parent = other.get(Matter, fixture.matter_id)
            matters.transition_matter_lifecycle_status(
                other,
                context=other_context,
                matter_id=fixture.matter_id,
                payload=MatterLifecycleStatusRequest(
                    to_status="disposed",
                    expected_from_status="active",
                    expected_updated_at=parent.updated_at,
                    reason="Local court getter lifecycle fence regression.",
                ),
            )
        with Session(audit.engine) as check:
            disposed = _outcome_snapshot(check, fixture)
            parent = check.get(Matter, fixture.matter_id)
            assert (
                parent.status == "disposed"
                and not parent.is_active
                and parent.lifecycle_version == 1
            )
        with pytest.raises(HTTPException) as denied:
            _write(session, context, fixture, path)
        operation = {
            "create_matter_court_order": "add a court order",
            "update_matter_court_order": "update a court order",
            "create_matter_court_sync_import": "import court-sync data",
        }[path]
        assert denied.value.status_code == 409
        assert (
            denied.value.detail
            == f"Cannot {operation} because this matter is disposed or inactive."
        )
        session.rollback()
    with Session(audit.engine) as check:
        assert _outcome_snapshot(check, fixture) == disposed
        parent = check.get(Matter, fixture.matter_id)
        assert (
            parent.status == "disposed" and not parent.is_active and parent.lifecycle_version == 1
        )
    audit.record(
        "court_denial_fences_complete",
        path=path,
        history_size=fixture.history_size,
        restricted_acl=404,
        foreign_tenant=404,
        stale_active_parent=409,
    )


@pytest.mark.parametrize("path", _PATHS)
def test_court_write_getter_does_not_hydrate_unrelated_history(court_audit, path):
    audit, observer = court_audit
    measured = []
    for history_size in (1, 501):
        fixture = _seed_history(audit, history_size)
        with audit.session("mutation") as session:
            context = _ip_race_context(
                session, company_id=fixture.company_id, membership_id=fixture.actor_id
            )
            probe = _CourtProbe(audit, fixture, observer)
            with probe.measure(session):
                result = _write(session, context, fixture, path)
        _assert_company_first(probe)
        order_id = _assert_outcomes(audit, fixture, path, result)
        _assert_history_retained(audit, fixture)
        measured.append(probe)
        # Manual create has no idempotency contract. Metadata no-op and imported
        # order identity replay are real, separate cold-session guarantees.
        if path != "create_matter_court_order":
            with Session(audit.engine) as check:
                before_replay = _outcome_snapshot(check, fixture)
                item_ids = set(
                    check.scalars(
                        select(MatterComplianceItem.id).where(
                            MatterComplianceItem.matter_id == fixture.matter_id,
                        )
                    )
                )
                intent_hashes = _row_hashes(
                    check,
                    NotificationDeliveryIntent,
                    list(
                        check.scalars(
                            select(NotificationDeliveryIntent.id).where(
                                NotificationDeliveryIntent.matter_id == fixture.matter_id,
                            )
                        )
                    ),
                )
            with audit.session("mutation") as session:
                context = _ip_race_context(
                    session, company_id=fixture.company_id, membership_id=fixture.actor_id
                )
                replay_probe = _CourtProbe(audit, fixture, observer)
                with replay_probe.measure(session):
                    replay_result = _write(session, context, fixture, path)
            _assert_company_first(replay_probe)
            assert _assert_outcomes(audit, fixture, path, replay_result, replay=True) == order_id
            assert (
                replay_result.id == result.id
                if path == "update_matter_court_order"
                else (replay_result.id != result.id)
            )
            with Session(audit.engine) as check:
                if path == "update_matter_court_order":
                    assert _outcome_snapshot(check, fixture) == before_replay
                assert (
                    set(
                        check.scalars(
                            select(MatterComplianceItem.id).where(
                                MatterComplianceItem.matter_id == fixture.matter_id,
                            )
                        )
                    )
                    == item_ids
                )
                assert (
                    _row_hashes(check, NotificationDeliveryIntent, list(intent_hashes))
                    == intent_hashes
                )
            _assert_history_retained(audit, fixture)
            measured.append(replay_probe)
        _assert_denied_writes(audit, fixture, path)
    assert audit.errors == [], "Unexpected database errors are not hydration regression proof"
    # Defer the RED assertion until both inventories and real write/fence outcomes
    # are retained. Setup/side-effect failures must not masquerade as a useful RED.
    receipts = [
        {
            "history_size": probe.fixture.history_size,
            "total_sql": len(probe.statements),
            "getter_sql": [len(row["sql"]) for row in probe.getters],
            "getter_orm_loads": [dict(row["orm_loads"]) for row in probe.getters],
            "getter_boundaries": [row["boundary"] for row in probe.getters],
            "historical_orm_loads": dict(probe.historical_materialized),
        }
        for probe in measured
    ]
    audit.record("court_bound_comparison", path=path, measurements=receipts)
    boundaries = (
        ["preparation", "persistence"]
        if path == "create_matter_court_sync_import"
        else ["persistence"]
    )
    assert all(
        [row["boundary"] for row in probe.getters] == boundaries for probe in measured
    ), receipts
    assert all(
        len(row["sql"]) == 2
        for probe in measured
        for row in probe.getters
    ), {"court_getter_sql_budget": receipts}
    assert all(
        not row["load_locked_children"]
        for probe in measured
        for row in probe.getters
        if row["boundary"] == "persistence"
    ), receipts
    assert all(not probe.historical_materialized for probe in measured), receipts
    assert all(
        not (
            set(row["orm_loads"])
            - {
                "matters",
                "company_memberships",
                "users",
            }
        )
        for probe in measured
        for row in probe.getters
    ), receipts
    for attempt in range(1 if path == "create_matter_court_order" else 2):
        assert len(measured[attempt].statements) == len(
            measured[attempt + (1 if path == "create_matter_court_order" else 2)].statements
        ), receipts


def test_default_locked_getter_retains_child_hydration(court_audit):
    audit, observer = court_audit
    for history_size in (1, 501):
        fixture = _seed_history(audit, history_size)
        for shared in (False, True):
            with audit.session("mutation") as session:
                context = _ip_race_context(
                    session, company_id=fixture.company_id, membership_id=fixture.actor_id
                )
                probe = _CourtProbe(audit, fixture, observer)
                with probe.measure(session):
                    lock_matter_private_authority(session, company_id=fixture.company_id)
                    parent = matters._get_matter_model(
                        session,
                        context=context,
                        matter_id=fixture.matter_id,
                        lock_for_update=not shared,
                        lock_for_share=shared,
                    )
                    state = inspect(parent)
                    assert not (set(_CHILD_RELATIONSHIPS) & state.unloaded)
                    for model, ids in fixture.history_ids.items():
                        loaded_ids = {key[1][0] for key in session.identity_map if key[0] is model}
                        assert set(ids) <= loaded_ids, (
                            f"Default getter dropped {model.__tablename__}"
                        )
                    assert all("chunks" not in inspect(row).unloaded for row in parent.attachments)
                    assert parent.status == "active" and parent.lifecycle_version == 0
                _assert_company_first(probe, membership_fence=False)
                assert len(probe.getters) == 1 and probe.getters[0]["load_locked_children"]
                assert len(probe.getters[0]["sql"]) >= 16
                assert dict(probe.historical_materialized) == {
                    model.__tablename__: history_size for model in _HISTORY_MODELS
                }
                session.rollback()
            _assert_history_retained(audit, fixture)
    assert audit.errors == []


def test_former_eager_preparation_is_rejected_by_court_bounds(court_audit, monkeypatch):
    audit, _observer = court_audit
    original = matters._get_matter_model
    record = audit.record
    comparisons = []

    def formerly_eager(session, **kwargs):
        if not (kwargs.get("lock_for_update") or kwargs.get("lock_for_share")):
            kwargs["load_locked_children"] = True
        return original(session, **kwargs)

    def retain(event_name, **values):
        if event_name == "court_bound_comparison":
            comparisons.append(values)
        return record(event_name, **values)

    monkeypatch.setattr(matters, "_get_matter_model", formerly_eager)
    monkeypatch.setattr(audit, "record", retain)
    with pytest.raises(AssertionError, match="court_getter_sql_budget"):
        test_court_write_getter_does_not_hydrate_unrelated_history(
            court_audit, "create_matter_court_sync_import",
        )
    assert len(comparisons) == 1
    rows = comparisons[0]["measurements"]
    assert [row["history_size"] for row in rows] == [1, 1, 501, 501]
    for row in rows:
        assert row["getter_sql"][0] > 2 and row["getter_sql"][1] == 2
        assert row["historical_orm_loads"] == {
            model.__tablename__: row["history_size"] for model in _HISTORY_MODELS
        }
    audit.record("court_former_eager_negative_complete", measurements=rows)


def test_missing_final_parent_lock_is_rejected_by_native_probe(court_audit, monkeypatch):
    audit, observer = court_audit
    fixture = _seed_history(audit, 1)
    with Session(audit.engine) as check:
        baseline = _outcome_snapshot(check, fixture)
        parent_before = _row_hashes(check, Matter, [fixture.matter_id])

    def missing_lock(*, company_id, matter_id, shared):
        assert shared is False
        return select(Matter).where(Matter.id == matter_id, Matter.company_id == company_id)

    monkeypatch.setattr(matters, "_matter_lock_statement", missing_lock)
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session, company_id=fixture.company_id, membership_id=fixture.actor_id,
        )
        probe = _CourtProbe(audit, fixture, observer)
        with probe.measure(session):
            lock_matter_private_authority(session, company_id=fixture.company_id)
            with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE") as rejected:
                matters._get_matter_model(
                    session, context=context, matter_id=fixture.matter_id,
                    lock_for_update=True, load_locked_children=False,
                )
            assert type(rejected.value) is pytest.fail.Exception
            assert str(rejected.value) == f"DID NOT RAISE {DBAPIError!r}"
        session.rollback()
    assert len(probe.getters) == 1 and probe.getters[0]["boundary"] == "persistence"
    assert probe.held_locks == ["companies"]
    assert not any("FOR UPDATE OF matters" in sql for sql in probe.statements)
    assert not probe.historical_materialized and audit.errors == []
    _assert_history_retained(audit, fixture)
    with Session(audit.engine) as check:
        assert _outcome_snapshot(check, fixture) == baseline
        assert _row_hashes(check, Matter, [fixture.matter_id]) == parent_before
    audit.record(
        "court_missing_final_lock_negative_complete", missing_lock="matters",
        no_durable_writes=True, observed_held_locks=probe.held_locks,
        failure_type=type(rejected.value).__name__, failure_message=str(rejected.value),
    )


def test_default_readers_keep_rich_workspace_dto(court_audit, monkeypatch):
    audit, observer = court_audit
    fields = {
        MatterTask: "tasks", MatterNote: "notes", MatterHearing: "hearings",
        MatterActivity: "activity", MatterCauseListEntry: "cause_list_entries",
        MatterCourtOrder: "court_orders", MatterCourtSyncRun: "court_sync_runs",
        MatterCourtSyncJob: "court_sync_jobs", MatterAttachment: "attachments",
    }
    original = matters._get_matter_model

    def explicit_full(session, **kwargs):
        kwargs["load_locked_children"] = True
        return original(session, **kwargs)

    for history_size in (1, 501):
        fixture = _seed_history(audit, history_size)
        for reader in (matters.get_matter, matters.get_matter_workspace):
            outputs = []
            for explicit in (False, True):
                with monkeypatch.context() as patch:
                    if explicit:
                        patch.setattr(matters, "_get_matter_model", explicit_full)
                    with audit.session("mutation") as session:
                        context = _ip_race_context(
                            session, company_id=fixture.company_id, membership_id=fixture.actor_id,
                        )
                        probe = _CourtProbe(audit, fixture, observer)
                        with probe.measure(session):
                            result = reader(session, context=context, matter_id=fixture.matter_id)
                        assert len(probe.getters) == 1
                        assert probe.getters[0]["load_locked_children"] is True
                        assert dict(probe.historical_materialized) == {
                            model.__tablename__: history_size for model in _HISTORY_MODELS
                        }
                        payload = result.model_dump(mode="json")
                        if reader is matters.get_matter_workspace:
                            for model, field in fields.items():
                                assert set(fixture.history_ids[model]) <= {
                                    row["id"] for row in payload[field]
                                }
                        outputs.append(payload)
            assert outputs[0] == outputs[1]
            audit.record(
                "court_default_reader_dto_complete", reader=reader.__name__,
                history_size=history_size, dto_sha256=_digest(outputs[0]),
                default_equals_explicit_full=True,
            )
        _assert_history_retained(audit, fixture)
    assert audit.errors == []
