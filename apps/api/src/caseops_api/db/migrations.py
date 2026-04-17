from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.base import Base
from caseops_api.db.session import get_engine


def get_alembic_config() -> Config:
    project_root = Path(__file__).resolve().parents[3]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def run_migrations() -> None:
    config = get_alembic_config()
    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    has_legacy_bootstrap = False

    if "alembic_version" in existing_tables:
        with engine.connect() as connection:
            version_rows = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchall()
        has_legacy_bootstrap = len(version_rows) == 0

    if existing_tables and ("alembic_version" not in existing_tables or has_legacy_bootstrap):
        Base.metadata.create_all(bind=engine)
        command.stamp(config, "head")
        return

    command.upgrade(config, "head")
