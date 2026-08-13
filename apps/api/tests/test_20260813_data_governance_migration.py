from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache, get_engine

PREVIOUS_HEAD = "20260812_0002"
MIGRATION_HEAD = "20260813_0001"
GOVERNANCE_TABLES = {
    "data_retention_policies",
    "data_retention_versions",
    "legal_holds",
    "legal_hold_items",
    "tenant_data_operations",
    "tenant_data_operation_items",
}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(
                connection.scalar(text("SELECT version_num FROM alembic_version"))
            )
    finally:
        engine.dispose()


def _seed_company(connection) -> str:
    company_id = str(uuid4())
    connection.execute(
        text(
            "INSERT INTO companies "
            "(id, name, slug, company_type, tenant_key, is_active, timezone, created_at) "
            "VALUES (:id, 'Data governance fixture', :slug, 'law_firm', "
            ":tenant_key, true, 'Asia/Kolkata', :created_at)"
        ),
        {
            "id": company_id,
            "slug": f"data-governance-{company_id[:8]}",
            "tenant_key": company_id,
            "created_at": datetime.now(UTC),
        },
    )
    return company_id


def _insert_governance_evidence(
    connection,
    company_id: str,
) -> tuple[str, str, str, str, str]:
    now = datetime.now(UTC)
    policy_id = str(uuid4())
    policy_version_id = str(uuid4())
    hold_id = str(uuid4())
    hold_item_id = str(uuid4())
    operation_id = str(uuid4())
    operation_item_id = str(uuid4())
    connection.execute(
        text(
            "INSERT INTO data_retention_policies "
            "(id, company_id, key, name, status, created_at, updated_at) VALUES "
            "(:id, :company_id, 'foundation-policy', 'Foundation policy', 'active', "
            ":now, :now)"
        ),
        {"id": policy_id, "company_id": company_id, "now": now},
    )
    connection.execute(
        text(
            "INSERT INTO data_retention_versions "
            "(id, company_id, policy_id, version, status, data_class_selector_json, "
            "purpose, legal_policy_basis, sensitivity, retention_days, disposition, "
            "hold_behavior, policy_hash, proposer_label_snapshot, created_at) VALUES "
            "(:id, :company_id, :policy_id, 1, 'candidate', '[\"legal_holds\"]', "
            "'Fixture purpose', 'fixture-basis', 'confidential', 365, 'retain', "
            "'preserve', :policy_hash, 'Fixture system', :now)"
        ),
        {
            "id": policy_version_id,
            "company_id": company_id,
            "policy_id": policy_id,
            "policy_hash": "a" * 64,
            "now": now,
        },
    )
    connection.execute(
        text(
            "INSERT INTO legal_holds "
            "(id, company_id, key, title, authority_reference, status, "
            "creator_label_snapshot, created_at, updated_at) VALUES "
            "(:id, :company_id, 'fixture-hold', 'Fixture hold', 'fixture://hold', "
            "'draft', 'Fixture system', :now, :now)"
        ),
        {"id": hold_id, "company_id": company_id, "now": now},
    )
    connection.execute(
        text(
            "INSERT INTO legal_hold_items "
            "(id, company_id, legal_hold_id, data_class_id, target_type, "
            "target_reference_hash, created_at) VALUES "
            "(:id, :company_id, :hold_id, 'legal_holds', 'tenant', "
            ":target_hash, :now)"
        ),
        {
            "id": hold_item_id,
            "company_id": company_id,
            "hold_id": hold_id,
            "target_hash": "e" * 64,
            "now": now,
        },
    )
    connection.execute(
        text(
            "INSERT INTO tenant_data_operations "
            "(id, company_id, operation_type, execution_mode, status, approval_status, "
            "request_scope_json, request_scope_hash, request_evidence_ref, manifest_json, "
            "manifest_hash, requester_label_snapshot, dry_run_completed_at, created_at, "
            "updated_at) VALUES "
            "(:id, :company_id, 'tenant_export', 'dry_run', 'dry_run_complete', "
            "'not_requested', '{}', :scope_hash, 'fixture://dry-run', '{}', "
            ":manifest_hash, 'Fixture system', :now, :now, :now)"
        ),
        {
            "id": operation_id,
            "company_id": company_id,
            "scope_hash": "b" * 64,
            "manifest_hash": "c" * 64,
            "now": now,
        },
    )
    connection.execute(
        text(
            "INSERT INTO tenant_data_operation_items "
            "(id, company_id, operation_id, data_class_id, target_type, "
            "target_reference_hash, item_status, candidate_record_count, estimated_bytes, "
            "safe_to_execute, created_at) VALUES "
            "(:id, :company_id, :operation_id, 'legal_holds', 'tenant', :target_hash, "
            "'eligible', 0, 0, false, :now)"
        ),
        {
            "id": operation_item_id,
            "company_id": company_id,
            "operation_id": operation_id,
            "target_hash": "d" * 64,
            "now": now,
        },
    )
    return policy_version_id, hold_id, hold_item_id, operation_id, operation_item_id


def test_data_governance_expand_is_empty_and_constraints_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'data-governance.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    engine = get_engine(database_url)
    with engine.begin() as connection:
        company_id = _seed_company(connection)
    engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    engine = get_engine(database_url)
    inspector = inspect(engine)
    assert GOVERNANCE_TABLES <= set(inspector.get_table_names())
    with engine.connect() as connection:
        assert all(
            connection.scalar(text(f"SELECT count(*) FROM {table_name}")) == 0
            for table_name in GOVERNANCE_TABLES
        )

    with engine.begin() as connection:
        (
            policy_version_id,
            hold_id,
            hold_item_id,
            operation_id,
            operation_item_id,
        ) = _insert_governance_evidence(connection, company_id)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE data_retention_versions SET policy_hash = 'short' "
                    "WHERE id = :policy_version_id"
                ),
                {"policy_version_id": policy_version_id},
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tenant_data_operations SET execution_mode = 'execute' "
                    "WHERE id = :operation_id"
                ),
                {"operation_id": operation_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tenant_data_operations SET manifest_hash = :manifest_hash "
                    "WHERE id = :operation_id"
                ),
                {"operation_id": operation_id, "manifest_hash": "e" * 64},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM legal_holds WHERE id = :hold_id"),
                {"hold_id": hold_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE legal_hold_items SET target_type = 'matter' "
                    "WHERE id = :hold_item_id"
                ),
                {"hold_item_id": hold_item_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM tenant_data_operation_items WHERE id = :operation_item_id"
                ),
                {"operation_item_id": operation_item_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE legal_holds SET status = 'released' "
                    "WHERE id = :hold_id"
                ),
                {"hold_id": hold_id},
            )

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE data_retention_versions SET status = 'approved' "
                "WHERE id = :policy_version_id"
            ),
            {"policy_version_id": policy_version_id},
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE data_retention_versions SET purpose = 'rewritten' "
                    "WHERE id = :policy_version_id"
                ),
                {"policy_version_id": policy_version_id},
            )

    engine.dispose()
    with pytest.raises(RuntimeError, match="Records-governance evidence exists"):
        command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == MIGRATION_HEAD

    get_settings.cache_clear()
    clear_engine_cache()


def test_empty_data_governance_schema_can_be_rehearsed_down_and_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'data-governance-empty.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == PREVIOUS_HEAD
    engine = create_engine(database_url, future=True)
    try:
        assert GOVERNANCE_TABLES.isdisjoint(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD

    get_settings.cache_clear()
    clear_engine_cache()
