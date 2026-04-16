from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command
from caseops_api.core.settings import get_settings


def get_alembic_config() -> Config:
    project_root = Path(__file__).resolve().parents[3]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def run_migrations() -> None:
    command.upgrade(get_alembic_config(), "head")
