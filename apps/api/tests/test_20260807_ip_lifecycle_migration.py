from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache


def _alembic_config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _schema(database_url: str) -> tuple[set[str], set[str], set[str], str]:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        docket_columns = {row["name"] for row in inspector.get_columns("ip_docket_records")}
        event_indexes = (
            {
                str(index["name"])
                for index in inspector.get_indexes("ip_docket_events")
                if index.get("name")
            }
            if "ip_docket_events" in tables
            else set()
        )
        with engine.connect() as connection:
            head = str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
        return tables, docket_columns, event_indexes, head
    finally:
        engine.dispose()


def test_ip_lifecycle_migration_upgrades_downgrades_and_reupgrades(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "ip-lifecycle.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)

    command.upgrade(config, "20260807_0002")
    tables, columns, _, head = _schema(database_url)
    assert "ip_docket_events" not in tables
    assert "lifecycle_version" not in columns
    assert head == "20260807_0002"

    command.upgrade(config, "20260807_0003")
    tables, columns, indexes, head = _schema(database_url)
    assert "ip_docket_events" in tables
    assert {
        "is_active",
        "lifecycle_version",
        "lifecycle_effective_at",
        "lifecycle_reason",
        "lifecycle_outcome",
        "lifecycle_source",
        "lifecycle_evidence_ref",
        "successor_docket_id",
    }.issubset(columns)
    assert {
        "ix_ip_docket_events_company_effective",
        "ix_ip_docket_events_company_candidate",
    }.issubset(indexes)
    assert head == "20260807_0003"

    command.downgrade(config, "20260807_0002")
    tables, columns, _, head = _schema(database_url)
    assert "ip_docket_events" not in tables
    assert "lifecycle_version" not in columns
    assert head == "20260807_0002"

    command.upgrade(config, "20260807_0003")
    tables, columns, indexes, head = _schema(database_url)
    assert "ip_docket_events" in tables
    assert "lifecycle_version" in columns
    assert "ix_ip_docket_events_company_effective" in indexes
    assert head == "20260807_0003"

    get_settings.cache_clear()
    clear_engine_cache()
