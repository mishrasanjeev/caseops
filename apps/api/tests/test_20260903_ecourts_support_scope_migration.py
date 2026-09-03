from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from caseops_api.core.settings import get_settings

PREVIOUS_HEAD = "20260903_0001"
MIGRATION_HEAD = "20260903_0002"
SCOPE_ID = "6ed0fbb0-fd79-49e0-9a33-202609030002"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def test_ecourts_support_scope_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ecourts-scope.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, PREVIOUS_HEAD)

    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM case_tracking_support_matrix")) == 0
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT provider, court, lookup_method, refresh_cost_minor, "
                    "bulk_refresh_cost_minor, currency, legal_tos_status, enabled, "
                    "tenant_visible, evidence_ref FROM case_tracking_support_matrix "
                    "WHERE id = :scope_id"
                ),
                {"scope_id": SCOPE_ID},
            ).one()
            assert tuple(row[:9]) == (
                "ecourtsindia",
                "*",
                "cnr_or_case_number",
                15,
                15,
                "INR",
                "approved",
                1,
                1,
            )
            assert "ecourtsindia.com/api/docs" in row.evidence_ref
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM case_tracking_support_matrix WHERE id = :scope_id"),
                    {"scope_id": SCOPE_ID},
                )
                == 0
            )
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
