from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

REVISION = "20260825_0001"
PREVIOUS_REVISION = "20260824_0003"
LINEAGE_TABLE = "authority_research_report_sources"
DOCUMENT_COLUMNS = {
    "provider_document_id",
    "canonical_url",
    "content_hash",
    "source_version",
    "legal_review_status",
}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _schema(database_url: str) -> tuple[set[str], set[str], str]:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        columns = (
            {str(column["name"]) for column in inspector.get_columns("authority_documents")}
            if "authority_documents" in tables
            else set()
        )
        with engine.connect() as connection:
            head = str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
        return tables, columns, head
    finally:
        engine.dispose()


def test_indian_kanoon_lineage_migration_and_fail_closed_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "indian-kanoon-lineage.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_REVISION)
    tables, columns, head = _schema(database_url)
    assert LINEAGE_TABLE not in tables
    assert not DOCUMENT_COLUMNS.intersection(columns)
    assert head == PREVIOUS_REVISION

    command.upgrade(config, REVISION)
    tables, columns, head = _schema(database_url)
    assert LINEAGE_TABLE in tables
    assert DOCUMENT_COLUMNS <= columns
    assert head == REVISION

    command.downgrade(config, PREVIOUS_REVISION)
    tables, columns, head = _schema(database_url)
    assert LINEAGE_TABLE not in tables
    assert not DOCUMENT_COLUMNS.intersection(columns)
    assert head == PREVIOUS_REVISION

    command.upgrade(config, REVISION)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO authority_documents "
                    "(id, source, adapter_name, court_name, forum_level, document_type, "
                    "title, canonical_key, summary, extracted_char_count, ingested_at, "
                    "created_at, updated_at) VALUES "
                    "('licensed-rollback-proof', 'indian_kanoon_licensed', 'test', "
                    "'Supreme Court of India', 'supreme', 'judgment', 'Rollback proof', "
                    "'licensed:rollback-proof', 'Proof', 0, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="Refusing IPLF-054 downgrade"):
        command.downgrade(config, PREVIOUS_REVISION)

    _, _, head = _schema(database_url)
    assert head == REVISION
    get_settings.cache_clear()
    clear_engine_cache()
