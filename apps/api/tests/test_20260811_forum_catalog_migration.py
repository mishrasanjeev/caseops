from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache


def _alembic_config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _catalog_rows(database_url: str) -> dict[str, dict[str, object]]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return {
                str(row["id"]): dict(row)
                for row in connection.execute(
                    text(
                        "SELECT id, name, forum_type, forum_level, state, district, "
                        "consumer_level, lineage, source_url "
                        "FROM forum_catalog_entries"
                    )
                ).mappings()
            }
    finally:
        engine.dispose()


def test_manual_matter_forum_catalog_upgrades_downgrades_and_reupgrades(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "manual-matter-forum-catalog.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)

    command.upgrade(config, "20260811_0003")
    before = _catalog_rows(database_url)
    assert before["consumer:ncdrc"]["lineage"] == "Consumer Forum > NCDRC"
    assert "drt:delhi:drt-2" not in before

    command.upgrade(config, "head")
    upgraded = _catalog_rows(database_url)
    assert upgraded["consumer:ncdrc"]["lineage"] == (
        "NCDRC > National Consumer Disputes Redressal Commission"
    )
    assert upgraded["consumer:dcdrc:delhi:dwarka"]["lineage"] == (
        "District Commission > Delhi > Dwarka"
    )
    assert upgraded["drt:delhi:drt-2"]["name"] == "DRT-2"
    assert upgraded["recovery:delhi:po-court"]["name"] == "PO"
    assert upgraded["company-law:nclt"]["name"] == "NCLT"
    assert upgraded["tdsat:delhi"]["source_url"] == (
        "https://www.tdsat.gov.in/Delhi/Delhi.php"
    )

    command.downgrade(config, "20260811_0003")
    downgraded = _catalog_rows(database_url)
    assert "drt:delhi:drt-2" not in downgraded
    assert "consumer:dcdrc:delhi:dwarka" not in downgraded
    assert downgraded["consumer:ncdrc"]["lineage"] == "Consumer Forum > NCDRC"
    assert downgraded["consumer:scdrc:11070000"]["lineage"] == (
        "Consumer Forum > SCDRC > Delhi"
    )
    assert downgraded["consumer:dcdrc:11070077"]["lineage"] == (
        "Consumer Forum > DCDRC > Delhi > Central Delhi"
    )

    command.upgrade(config, "head")
    reupgraded = _catalog_rows(database_url)
    assert reupgraded["appellate-tribunal:fema"]["name"] == "FEMA"
    assert reupgraded["consumer:dcdrc:11070077"]["lineage"] == (
        "District Commission > Delhi > Central Delhi"
    )

    get_settings.cache_clear()
    clear_engine_cache()
