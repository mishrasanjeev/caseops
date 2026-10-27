"""Independent migration upgrade/restart/downgrade and complete index-shape proofs."""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.models import (
    HearingReminder,
    InAppNotification,
    MatterHearing,
    MatterOutsideCounselAssignment,
    NotificationDeliveryIntent,
    OutsideCounsel,
    OutsideCounselSpendRecord,
)
from tests.migration_index_catalog import (
    require_index_additions,
    require_revision,
    schema_catalog,
    write_catalog,
)
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company, _seed_matter, _seed_membership

HEAD = "20261027_0002"
PARENT = "20261027_0001"
PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20261027_0002_native_context_seek_indexes.py"
)
EXPECTED = (
    (
        "matter_outside_counsel_assignments",
        "ix_oc_assignments_company_matter_id",
        ["company_id", "matter_id", "id"],
    ),
    (
        "outside_counsel_spend_records",
        "ix_oc_spend_company_matter_id",
        ["company_id", "matter_id", "id"],
    ),
    (
        "in_app_notifications",
        "ix_inapp_company_recipient_created_id",
        ["company_id", "recipient_membership_id", "created_at", "id"],
    ),
    (
        "notification_delivery_intents",
        "ix_notification_intent_inapp_id",
        ["in_app_notification_id", "id"],
    ),
    (
        "hearing_reminders",
        "ix_hearing_reminder_company_hearing_generation",
        ["company_id", "hearing_id", "schedule_generation"],
    ),
)


def module():
    spec = importlib.util.spec_from_file_location("native_context_index_migration", PATH)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def apply(engine, operation="upgrade", destination=PARENT):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"destination_rev": destination})
        with context.begin_transaction(), Operations.context(context):
            getattr(module(), operation)()


def populate(engine):
    with Session(engine) as session:
        company = _seed_company(session)
        member = _seed_membership(session, company)
        matter = _seed_matter(session, company)
        counsel = OutsideCounsel(company_id=company, name="Retained index counsel")
        session.add(counsel)
        session.flush()
        assignment = MatterOutsideCounselAssignment(
            company_id=company, matter_id=matter, counsel_id=counsel.id, budget_amount_minor=1
        )
        session.add(assignment)
        session.flush()
        notification_id = str(uuid4())
        session.add_all(
            [
                OutsideCounselSpendRecord(
                    company_id=company,
                    matter_id=matter,
                    counsel_id=counsel.id,
                    assignment_id=assignment.id,
                    description="Retained one paise",
                    amount_minor=1,
                    approved_amount_minor=0,
                ),
                InAppNotification(
                    id=notification_id,
                    company_id=company,
                    recipient_membership_id=member,
                    event_type="synthetic",
                    source_type="synthetic",
                    source_id="owned",
                    matter_id=matter,
                    title="Retained receipt",
                    created_at=datetime(2026, 10, 27, tzinfo=UTC),
                ),
            ]
        )
        session.flush()
        session.add(
            NotificationDeliveryIntent(
                company_id=company,
                recipient_membership_id=member,
                in_app_notification_id=notification_id,
                channel="in_app",
                event_type="synthetic",
                source_type="synthetic",
                source_id="owned",
                idempotency_key="owned-index-receipt",
                metadata_json={"no_paid_providers": True},
            )
        )
        hearing = MatterHearing(
            company_id=company,
            matter_id=matter,
            hearing_on=date(2026, 10, 27),
            forum_name="Retained forum",
            purpose="Retained hearing",
            status="scheduled",
        )
        session.add(hearing)
        session.flush()
        session.add(
            HearingReminder(
                company_id=company,
                matter_id=matter,
                hearing_id=hearing.id,
                recipient_membership_id=member,
                channel="in_app",
                scheduled_for=datetime(2026, 10, 27, tzinfo=UTC),
                schedule_generation=7,
                status="cancelled",
            )
        )
        session.commit()


def snapshot(engine):
    with engine.connect() as connection:
        return {
            table: connection.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY id').all()
            for table in (
                "outside_counsel",
                "matter_outside_counsel_assignments",
                "outside_counsel_spend_records",
                "in_app_notifications",
                "notification_delivery_intents",
                "matter_hearings",
                "hearing_reminders",
            )
        }


def shapes(engine):
    rows = []
    with engine.connect() as connection:
        for table, name, columns in EXPECTED:
            observed = next(
                row for row in inspect(connection).get_indexes(table) if row["name"] == name
            )
            assert observed["column_names"] == columns and not observed["unique"]
            if engine.dialect.name == "postgresql":
                state = module()._postgres_state(connection, table, name, columns)
                assert state["indisvalid"] and state["indisready"]
                oid = connection.scalar(text("SELECT to_regclass(:name)::oid"), {"name": name})
                rows.append((name, oid))
            else:
                assert module()._sqlite_exists(connection, table, name, columns)
                rows.append(
                    (
                        name,
                        connection.scalar(
                            text("SELECT sql FROM sqlite_master WHERE name=:name"), {"name": name}
                        ),
                    )
                )
    return rows


@pytest.mark.parametrize("kind", KINDS)
def test_seek_indexes_preserve_populated_rows_restart_and_parent_roundtrip(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        populate(engine)
        before = snapshot(engine)
        parent_catalog = schema_catalog(engine)
        require_revision(engine, PARENT)
        write_catalog(tmp_path / "parent-catalog.json", parent_catalog, PARENT)
        command.upgrade(config, HEAD)
        original = shapes(engine)
        head_catalog = schema_catalog(engine)
        require_index_additions(parent_catalog, head_catalog, EXPECTED)
        require_revision(engine, HEAD)
        write_catalog(tmp_path / "dated-head-catalog.json", head_catalog, HEAD)
        apply(engine)
        assert shapes(engine) == original and snapshot(engine) == before
        assert schema_catalog(engine) == head_catalog
        require_revision(engine, HEAD)
        command.downgrade(config, PARENT)
        for table, name, _ in EXPECTED:
            assert name not in {row["name"] for row in inspect(engine).get_indexes(table)}
        assert snapshot(engine) == before
        assert schema_catalog(engine) == parent_catalog
        require_revision(engine, PARENT)
        command.upgrade(config, HEAD)
        shapes(engine)
        assert snapshot(engine) == before
        assert schema_catalog(engine) == head_catalog
        require_revision(engine, HEAD)


@pytest.mark.parametrize("kind", KINDS)
def test_wide_historical_downgrade_refuses_and_retains_rows_shapes_and_revision(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        populate(engine)
        before, indexes = snapshot(engine), shapes(engine)
        full_catalog = schema_catalog(engine)
        require_revision(engine, HEAD)
        with pytest.raises(RuntimeError, match="exact immediate parent|roll-forward or restore"):
            command.downgrade(config, "20261024_0001")
        assert snapshot(engine) == before and shapes(engine) == indexes
        assert schema_catalog(engine) == full_catalog
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == HEAD


@pytest.mark.parametrize("kind", KINDS)
def test_conflicting_same_name_index_refuses_before_any_sibling_change(kind, tmp_path, monkeypatch):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        populate(engine)
        table, name, _ = EXPECTED[-1]
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE INDEX "{name}" ON "{table}" (id)')
        before = snapshot(engine)
        original = {table: inspect(engine).get_indexes(table) for table, _, _ in EXPECTED}
        full_catalog = schema_catalog(engine)
        with pytest.raises(RuntimeError, match="conflicting shape"):
            apply(engine)
        assert {table: inspect(engine).get_indexes(table) for table, _, _ in EXPECTED} == original
        assert schema_catalog(engine) == full_catalog
        require_revision(engine, PARENT)
        assert snapshot(engine) == before
