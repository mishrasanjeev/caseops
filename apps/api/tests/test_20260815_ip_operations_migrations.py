"""SQLite round-trip proof for the IPLF-039C operations migration chain."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260814_0002"
MIGRATION_HEAD = "20260815_0004"
NEW_TABLES = {"ip_docket_control_reviews", "ip_docket_queues"}
ADDED_COLUMNS = {
    "ip_deadline_coverages": {
        "pending_replacement_membership_id",
        "replacement_decision",
        "replacement_decided_at",
        "replacement_decision_reason",
        "emergency_until",
        "emergency_escalation_membership_id",
    },
    "calendar_event_syncs": {"drift_status", "drift_checked_at", "drift_detail"},
}
EXPECTED_TENANT_FOREIGN_KEYS = {
    "ip_docket_control_reviews": {
        "fk_ip_control_review_signer_company": (
            ["signed_off_by_membership_id", "company_id"],
            "company_memberships",
            ["id", "company_id"],
            {"match": "SIMPLE", "deferrable": True, "initially": "DEFERRED"},
        ),
        "fk_ip_control_review_creator_company": (
            ["created_by_membership_id", "company_id"],
            "company_memberships",
            ["id", "company_id"],
            {"match": "SIMPLE", "deferrable": True, "initially": "DEFERRED"},
        ),
    },
    "ip_deadline_coverages": {
        "fk_ip_coverage_pending_replacement_company": (
            ["pending_replacement_membership_id", "company_id"],
            "company_memberships",
            ["id", "company_id"],
            {"match": "SIMPLE", "deferrable": True, "initially": "DEFERRED"},
        ),
        "fk_ip_coverage_emergency_escalation_company": (
            ["emergency_escalation_membership_id", "company_id"],
            "company_memberships",
            ["id", "company_id"],
            {"match": "SIMPLE", "deferrable": True, "initially": "DEFERRED"},
        ),
    },
    "ip_docket_queues": {
        "fk_ip_docket_queue_team_company": (
            ["team_id", "company_id"],
            "teams",
            ["id", "company_id"],
            {"ondelete": "CASCADE"},
        ),
        "fk_ip_docket_queue_owner_company": (
            ["owner_membership_id", "company_id"],
            "company_memberships",
            ["id", "company_id"],
            {"ondelete": "CASCADE"},
        ),
        "fk_ip_docket_queue_creator_company": (
            ["created_by_membership_id", "company_id"],
            "company_memberships",
            ["id", "company_id"],
            {"match": "SIMPLE", "deferrable": True, "initially": "DEFERRED"},
        ),
    },
}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def _column_names(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _sqlite_constraint_clause(connection, table: str, constraint_name: str) -> str:
    ddl = connection.scalar(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = :table"
        ),
        {"table": table},
    )
    assert ddl is not None
    normalized = " ".join(str(ddl).replace('"', "").upper().split())
    marker = f"CONSTRAINT {constraint_name.upper()} "
    start = normalized.index(marker)
    end = normalized.find(" CONSTRAINT ", start + len(marker))
    return normalized[start:] if end == -1 else normalized[start:end]


def test_ip_operations_migrations_upgrade_downgrade_and_reupgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-operations.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        before = inspect(engine)
        before_tables = set(before.get_table_names())
        before_columns = {
            table: _column_names(before, table) for table in ADDED_COLUMNS
        }
        assert NEW_TABLES.isdisjoint(before_tables)
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        upgraded = inspect(engine)
        assert NEW_TABLES <= set(upgraded.get_table_names())
        for table, names in ADDED_COLUMNS.items():
            assert names <= _column_names(upgraded, table)
        control_columns = _column_names(upgraded, "ip_docket_control_reviews")
        assert {"query_version", "snapshot_schema_version", "report_snapshot_json"} <= (
            control_columns
        )

        for table, expected_by_name in EXPECTED_TENANT_FOREIGN_KEYS.items():
            actual_by_name = {
                foreign_key["name"]: (
                    foreign_key["constrained_columns"],
                    foreign_key["referred_table"],
                    foreign_key["referred_columns"],
                )
                for foreign_key in upgraded.get_foreign_keys(table)
                if foreign_key.get("name")
            }
            for name, expected in expected_by_name.items():
                assert actual_by_name[name] == expected[:-1]

        with engine.connect() as connection:
            for table, expected_by_name in EXPECTED_TENANT_FOREIGN_KEYS.items():
                for name, expected in expected_by_name.items():
                    clause = _sqlite_constraint_clause(connection, table, name)
                    options = expected[-1]
                    if match := options.get("match"):
                        assert f"MATCH {match}" in clause
                    if ondelete := options.get("ondelete"):
                        assert f"ON DELETE {ondelete}" in clause
                    if options.get("deferrable"):
                        assert "DEFERRABLE" in clause
                    if initially := options.get("initially"):
                        assert f"INITIALLY {initially}" in clause
        assert _head(database_url) == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        downgraded = inspect(engine)
        assert NEW_TABLES.isdisjoint(set(downgraded.get_table_names()))
        for table, names in before_columns.items():
            assert _column_names(downgraded, table) == names
        assert _head(database_url) == PREVIOUS_HEAD
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD

    get_settings.cache_clear()
    clear_engine_cache()
