"""Dated0006→0007 index-only compatibility; actual-current-head health is separate."""

import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.models import (
    AuditEvent,
    DomainOutboxEvent,
    HearingPack,
    HearingPackItem,
    InAppNotification,
    Recommendation,
    RecommendationDecision,
    RecommendationOption,
)
from tests.migration_index_catalog import (
    require_index_additions,
    require_revision,
    schema_catalog,
    write_catalog,
)
from tests.test_counsel_page_migration_20261027 import _rows
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company, _seed_matter, _seed_membership

PARENT = "20261027_0006"
HEAD = "20261027_0007"
PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20261027_0007_matter_readthrough_indexes.py"
)
STAMP = datetime(2026, 10, 28, 1, 2, 3, 123456, tzinfo=UTC)
EXPECTED = (
    (
        "recommendations",
        "ix_recommendation_read_company_matter_created_id",
        ["company_id", "matter_id", "created_at", "id"],
    ),
    (
        "recommendation_options",
        "ix_recommendation_option_parent_rank_id",
        ["recommendation_id", "rank", "id"],
    ),
    (
        "recommendation_decisions",
        "ix_recommendation_decision_parent_created_id",
        ["recommendation_id", "created_at", "id"],
    ),
    (
        "hearing_packs",
        "ix_hearing_pack_matter_hearing_generated_id",
        ["matter_id", "hearing_id", "generated_at", "id"],
    ),
    ("hearing_pack_items", "ix_hearing_pack_item_parent_rank_id", ["pack_id", "rank", "id"]),
)
PRESERVED = (
    "companies",
    "users",
    "company_memberships",
    "matters",
    "recommendations",
    "recommendation_options",
    "recommendation_decisions",
    "hearing_packs",
    "hearing_pack_items",
    "audit_events",
    "domain_outbox_events",
    "in_app_notifications",
)


def module():
    spec = importlib.util.spec_from_file_location("dated_readthrough_indexes", PATH)
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
        source = Recommendation(
            company_id=company,
            matter_id=matter,
            type="authority",
            title="Retained source",
            rationale="Retained original recommendation",
            assumptions_json='["literal source"]',
            missing_facts_json="[]",
            retrieved_authorities_json="[]",
            created_at=STAMP,
            updated_at=STAMP,
        )
        pack = HearingPack(
            matter_id=matter,
            hearing_id=None,
            summary="Retained original pack",
            generated_at=STAMP,
            reviewed_at=None,
            review_required=True,
            status="draft",
        )
        session.add_all([source, pack])
        session.flush()
        session.add_all(
            [
                RecommendationOption(
                    recommendation_id=source.id,
                    rank=0,
                    label="Stored option",
                    rationale="Original option body",
                    confidence="low",
                    supporting_citations_json='["opaque source"]',
                    risk_notes=None,
                ),
                RecommendationDecision(
                    recommendation_id=source.id,
                    actor_membership_id=None,
                    decision="deferred",
                    selected_option_index=None,
                    notes=None,
                    created_at=STAMP,
                ),
                HearingPackItem(
                    pack_id=pack.id,
                    item_type="chronology",
                    title="Stored item",
                    body="Original body",
                    source_ref=None,
                    rank=0,
                    created_at=STAMP,
                ),
                AuditEvent(
                    company_id=company,
                    actor_type="membership",
                    actor_membership_id=member,
                    matter_id=matter,
                    action="retained.fixture",
                    target_type="matter",
                    target_id=matter,
                    metadata_json='{"literal":"retained audit bytes"}',
                    created_at=STAMP,
                ),
                InAppNotification(
                    company_id=company,
                    recipient_membership_id=member,
                    event_type="retained.fixture",
                    source_type="matter",
                    source_id=matter,
                    matter_id=matter,
                    title="Retained receipt",
                    body="Exact stored source",
                    metadata_json={"literal": "no-paid-providers"},
                    created_at=STAMP,
                ),
            ]
        )
        payload = {"literal": "retained neutral event", "no_paid_providers": True}
        session.add(
            DomainOutboxEvent(
                company_id=company,
                event_key="readthrough-index-retained",
                event_type="fixture.retained",
                schema_version=1,
                aggregate_type="matter",
                aggregate_id=matter,
                aggregate_version=1,
                occurred_at=STAMP,
                effective_at=STAMP,
                source_command_id="offline-source-fixture",
                producer="offline-fixture",
                confidentiality="privileged",
                correlation_id="read-index-fixture",
                payload_hash=hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                payload_json=payload,
                expected_consumers_json=["offline-only"],
                state="queued",
                created_at=STAMP,
                updated_at=STAMP,
            )
        )
        session.commit()
        return source.id, pack.id


def shapes(engine):
    result = []
    with engine.connect() as connection:
        for table, name, columns in EXPECTED:
            found = next(
                row for row in inspect(connection).get_indexes(table) if row["name"] == name
            )
            assert found["column_names"] == columns and not found["unique"]
            if engine.dialect.name == "postgresql":
                row = connection.execute(
                    text(
                        "SELECT i.indisvalid,i.indisready,i.indisunique,"
                        "pg_get_expr(i.indpred,i.indrelid),i.indexprs IS NULL "
                        "FROM pg_index i WHERE i.indexrelid=to_regclass(:name)"
                    ),
                    {"name": name},
                ).one()
                assert tuple(row) == (
                    True,
                    True,
                    False,
                    "((type)::text <> 'intelligent_review'::text)"
                    if table == "recommendations"
                    else None,
                    True,
                )
                state = module()._postgres_state(connection, table, name, columns)
                assert state["indisvalid"] and state["indisready"]
                result.append(
                    (
                        name,
                        connection.scalar(text("SELECT to_regclass(:name)::oid"), {"name": name}),
                    )
                )
            else:
                assert module()._sqlite_exists(connection, table, name, columns)
                sql = connection.scalar(
                    text("SELECT sql FROM sqlite_master WHERE name=:name"), {"name": name}
                )
                assert (sql.rsplit(" WHERE ", 1)[-1] if " WHERE " in sql else None) == (
                    "type <> 'intelligent_review'" if table == "recommendations" else None
                )
                result.append((name, sql))
    return result


@pytest.mark.parametrize("kind", KINDS)
def test_dated_readthrough_upgrade_restart_parent_roundtrip_preserves_all_columns(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        populate(engine)
        before = _rows(engine, PRESERVED)
        parent = schema_catalog(engine)
        require_revision(engine, PARENT)
        assert all(before[name] for name in PRESERVED)
        write_catalog(tmp_path / "parent-catalog.json", parent, PARENT)
        command.upgrade(config, HEAD)
        identity = shapes(engine)
        head = schema_catalog(engine)
        require_index_additions(parent, head, EXPECTED)
        require_revision(engine, HEAD)
        write_catalog(tmp_path / "dated-head-catalog.json", head, HEAD)
        apply(engine)
        assert (
            shapes(engine) == identity
            and _rows(engine, PRESERVED) == before
            and schema_catalog(engine) == head
        )
        command.downgrade(config, PARENT)
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == parent
        require_revision(engine, PARENT)
        command.upgrade(config, HEAD)
        shapes(engine)
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == head
        require_revision(engine, HEAD)


@pytest.mark.parametrize("kind", KINDS)
def test_old_column_insert_update_delete_and_wide_text_remain_valid_after_indexes(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        recommendation_id, pack_id = populate(engine)
        original = _rows(engine, PRESERVED)
        catalog = schema_catalog(engine)
        wide = "ह" * 1000000
        with Session(engine) as session:
            recommendation = session.get(Recommendation, recommendation_id)
            recommendation.rationale = wide
            option = RecommendationOption(
                recommendation_id=recommendation_id,
                rank=0,
                label="Rolling old-column writer",
                rationale=wide,
                confidence="low",
                supporting_citations_json="[]",
            )
            item = HearingPackItem(
                pack_id=pack_id,
                item_type="chronology",
                title="Rolling retained item",
                body=wide,
                rank=0,
                source_ref="opaque:literal-source",
            )
            session.add_all([option, item])
            session.commit()
            option_id = option.id
            item_id = item.id
        before = _rows(engine, PRESERVED)
        apply(engine)
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == catalog
        with Session(engine) as session:
            retained = session.get(Recommendation, recommendation_id).rationale
            body = session.get(HearingPackItem, item_id).body
            session.delete(session.get(RecommendationOption, option_id))
            session.delete(session.get(HearingPackItem, item_id))
            session.commit()
        assert retained == body == wide
        after = _rows(engine, PRESERVED)
        assert (
            after["audit_events"] == original["audit_events"]
            and after["domain_outbox_events"] == original["domain_outbox_events"]
            and after["in_app_notifications"] == original["in_app_notifications"]
        )
        shapes(engine)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("conflict", ["wrong_columns", "wrong_partial_predicate"])
def test_conflicting_shape_refuses_before_any_new_sibling_ddl(
    kind, conflict, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        populate(engine)
        table, name, columns = EXPECTED[0]
        wrong = (
            f'CREATE INDEX "{name}" ON "{table}" (id)'
            if conflict == "wrong_columns"
            else (
                f'CREATE INDEX "{name}" ON "{table}" ({",".join(columns)}) '
                "WHERE type = 'intelligent_review'"
            )
        )
        with engine.begin() as connection:
            connection.exec_driver_sql(wrong)
        before = _rows(engine, PRESERVED)
        catalog = schema_catalog(engine)
        with pytest.raises(RuntimeError, match="conflicting shape"):
            apply(engine)
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == catalog
        require_revision(engine, PARENT)


@pytest.mark.parametrize("kind", KINDS)
def test_cross_historical_downgrade_refuses_at_exact_guard_and_preserves_complete_head(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        populate(engine)
        before = _rows(engine, PRESERVED)
        catalog = schema_catalog(engine)
        identity = shapes(engine)
        message = (
            r"^SQLite seek index downgrade requires exact immediate parent\.$"
            if kind == "sqlite"
            else r"^Matter-task queue storage requires reviewed roll-forward or restore\.$"
        )
        with pytest.raises(RuntimeError, match=message):
            command.downgrade(config, "20261027_0005")
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == catalog
        assert shapes(engine) == identity
        require_revision(engine, HEAD)


@pytest.mark.parametrize("kind", KINDS)
def test_actual_current_head_has_five_read_indexes_and_complete_global_index_health(
    kind, tmp_path, monkeypatch
):
    from caseops_api.db.index_coverage import database_foreign_key_gaps

    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, "head")
        shapes(engine)
        assert not database_foreign_key_gaps(inspect(engine))
        # Full actual-current catalog also validates every PG index ready/valid;
        # this is deliberately separate from the frozen0006→0007 catalog test.
        current = schema_catalog(engine)
        assert current
