"""IPLF-057B Madrid compatibility projection migration proof."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260825_0003"
MIGRATION_HEAD = "20260825_0004"


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def test_madrid_projection_backfills_and_survives_restore_forward_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'madrid-projection.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)
    command.upgrade(config, PREVIOUS_HEAD)

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO ip_docket_records (
                        id, company_id, record_type, title, status,
                        archived_by_matter_disposal, restricted, current_version,
                        created_by_membership_id, is_active, lifecycle_version
                    ) VALUES (
                        'docket-057b', 'company-057b', 'international_registration',
                        'ASTER international registration', 'ready', false, false, 1,
                        'member-057b', true, 0
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO trademark_international_registrations (
                        id, company_id, docket_id, record_kind, direction,
                        wipo_reference, holder_name, mark_name,
                        classes_json, goods_services_json, priority_claims_json,
                        source_url, source_reference, source_retrieved_at,
                        version,
                        created_by_membership_id, updated_by_membership_id,
                        created_at, updated_at
                    ) VALUES (
                        'madrid-057b', 'company-057b', 'docket-057b',
                        'international_registration', 'inbound', 'WIPO-057B',
                        'Aster Legal', 'ASTER',
                        '[9, 42]', '{"9":"Software","42":"Software services"}',
                        '[]', 'https://www.wipo.int/madrid/057b', 'WIPO-057B',
                        '2026-08-25 10:00:00', 1,
                        'member-057b', 'member-057b',
                        '2026-08-25 10:00:00', '2026-08-25 10:00:00'
                    )
                    """
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            projection = (
                connection.execute(
                    text(
                        """
                    SELECT * FROM ip_trademark_particular_versions
                    WHERE docket_id = 'docket-057b' AND version = 1
                    """
                    )
                )
                .mappings()
                .one()
            )
            assert projection["form_key"] == "MADRID_RECORD"
            assert json.loads(projection["representation_json"])["text"] == "ASTER"
            classes = json.loads(projection["classes_json"])
            assert classes == [
                {"class_number": 9, "specification": "Software"},
                {"class_number": 42, "specification": "Software services"},
            ]
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*) FROM ip_trademark_particular_versions
                    WHERE docket_id = 'docket-057b' AND version = 1
                    """
                    )
                )
                == 1
            )
    finally:
        engine.dispose()
    get_settings.cache_clear()
    clear_engine_cache()
