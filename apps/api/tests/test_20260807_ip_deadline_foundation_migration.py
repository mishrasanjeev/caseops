from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

EXPECTED_TABLES = {
    "legal_working_calendars",
    "legal_working_calendar_versions",
    "ip_rule_sets",
    "ip_rule_versions",
    "company_ip_rule_policies",
    "ip_deadlines",
    "ip_responsibility_assignments",
}

EXPECTED_INDEXES = {
    ("legal_working_calendars", "ix_legal_working_calendars_created_by_membership_id"),
    (
        "legal_working_calendar_versions",
        "ix_legal_working_calendar_versions_proposed_by_membership_id",
    ),
    (
        "legal_working_calendar_versions",
        "ix_legal_working_calendar_versions_approved_by_membership_id",
    ),
    ("ip_rule_versions", "ix_ip_rule_versions_proposed_by_membership_id"),
    ("ip_rule_versions", "ix_ip_rule_versions_reviewed_by_membership_id"),
    ("ip_rule_versions", "ix_ip_rule_versions_legal_approved_by_membership_id"),
    ("company_ip_rule_policies", "ix_company_ip_rule_policies_rule_set_id"),
    (
        "company_ip_rule_policies",
        "ix_company_ip_rule_policies_active_rule_version_id",
    ),
    (
        "company_ip_rule_policies",
        "ix_company_ip_rule_policies_updated_by_membership_id",
    ),
    ("ip_deadlines", "ix_ip_deadlines_confirmed_by_membership_id"),
    ("ip_deadlines", "ix_ip_deadlines_created_by_membership_id"),
    (
        "ip_responsibility_assignments",
        "ix_ip_responsibility_assignments_company_id",
    ),
    (
        "ip_responsibility_assignments",
        "ix_ip_responsibility_assignments_created_by_membership_id",
    ),
    ("ip_deadlines", "ix_ip_deadlines_company_state_result"),
}


def _alembic_config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _schema(database_url: str) -> tuple[set[str], set[tuple[str, str]], str]:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        indexes = {
            (table, str(index["name"]))
            for table in EXPECTED_TABLES.intersection(tables)
            for index in inspector.get_indexes(table)
            if index.get("name")
        }
        with engine.connect() as connection:
            head = str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
        return tables, indexes, head
    finally:
        engine.dispose()


def test_ip_deadline_foundation_migration_upgrades_downgrades_and_reupgrades(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "ip-deadline-foundation.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)

    command.upgrade(config, "20260807_0004")
    tables, _, head = _schema(database_url)
    assert not EXPECTED_TABLES.intersection(tables)
    assert head == "20260807_0004"

    command.upgrade(config, "20260807_0005")
    tables, indexes, head = _schema(database_url)
    assert EXPECTED_TABLES <= tables
    assert EXPECTED_INDEXES <= indexes
    assert head == "20260807_0005"

    command.downgrade(config, "20260807_0004")
    tables, _, head = _schema(database_url)
    assert not EXPECTED_TABLES.intersection(tables)
    assert head == "20260807_0004"

    command.upgrade(config, "20260807_0005")
    tables, indexes, head = _schema(database_url)
    assert EXPECTED_TABLES <= tables
    assert EXPECTED_INDEXES <= indexes
    assert head == "20260807_0005"

    get_settings.cache_clear()
    clear_engine_cache()
