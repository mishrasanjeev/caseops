from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260826_0001"
MIGRATION_HEAD = "20260826_0002"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _database_url(tmp_path: Path, name: str) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"


def _configure(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def _seed_legacy_mappings(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    stamp = "2026-08-26 00:00:00"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO courts (
                        id, name, short_name, forum_level, jurisdiction,
                        is_active, created_at, updated_at
                    ) VALUES (
                        'court-060a', 'IPLF 060A Court', 'I60A', 'high_court',
                        'india', true, :stamp, :stamp
                    )
                    """
                ),
                {"stamp": stamp},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO judges (
                        id, court_id, full_name, is_active, created_at, updated_at
                    ) VALUES
                        ('judge-exact', 'court-060a', 'Exact Judge', true, :stamp, :stamp),
                        ('judge-low', 'court-060a', 'Low Judge', true, :stamp, :stamp)
                    """
                ),
                {"stamp": stamp},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO authority_documents (
                        id, source, adapter_name, court_name, forum_level,
                        document_type, title, decision_date, canonical_key,
                        summary, document_text, extracted_char_count,
                        ingested_at, created_at, updated_at
                    ) VALUES
                        (
                            'authority-exact', 'official_test', 'test',
                            'IPLF 060A Court', 'high_court', 'judgment',
                            'Exact authority', '2026-08-20', 'iplf-060a:exact',
                            'Exact legacy mapping.', 'Text', 4, :stamp, :stamp, :stamp
                        ),
                        (
                            'authority-low', 'official_test', 'test',
                            'IPLF 060A Court', 'high_court', 'judgment',
                            'Low authority', '2026-08-20', 'iplf-060a:low',
                            'Low legacy mapping.', 'Text', 4, :stamp, :stamp, :stamp
                        )
                    """
                ),
                {"stamp": stamp},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO judge_decision_index (
                        id, judge_id, authority_document_id, role,
                        match_confidence, created_at
                    ) VALUES
                        (
                            'mapping-exact', 'judge-exact', 'authority-exact',
                            'sat_on', 'exact', :stamp
                        ),
                        (
                            'mapping-low', 'judge-low', 'authority-low',
                            'sat_on', 'low', :stamp
                        )
                    """
                ),
                {"stamp": stamp},
            )
    finally:
        engine.dispose()


def test_judge_mapping_migration_empty_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path, "judge-mapping-empty.db")
    _configure(database_url, monkeypatch)
    config = _config()
    command.upgrade(config, PREVIOUS_HEAD)

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert {"bench_aliases", "judge_mapping_reviews"} <= set(
            schema.get_table_names()
        )
        assert {
            "raw_judge_name",
            "source_ordinal",
            "mapping_status",
            "resolver_version",
            "evidence_json",
            "is_analytics_eligible",
        } <= {
            column["name"]
            for column in schema.get_columns("judge_decision_index")
        }
        assert _head(database_url) == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert "bench_aliases" not in schema.get_table_names()
        assert "judge_mapping_reviews" not in schema.get_table_names()
        assert "mapping_status" not in {
            column["name"]
            for column in schema.get_columns("judge_decision_index")
        }
        assert _head(database_url) == PREVIOUS_HEAD
    finally:
        engine.dispose()


def test_legacy_eligibility_backfill_and_populated_downgrade_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url(tmp_path, "judge-mapping-populated.db")
    _configure(database_url, monkeypatch)
    config = _config()
    command.upgrade(config, PREVIOUS_HEAD)
    _seed_legacy_mappings(database_url)

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO authority_documents (
                        id, source, adapter_name, court_name, forum_level,
                        document_type, title, decision_date, canonical_key,
                        summary, document_text, extracted_char_count,
                        ingested_at, created_at, updated_at
                    ) VALUES (
                        'authority-unreviewed', 'official_test', 'test',
                        'IPLF 060A Court', 'high_court', 'judgment',
                        'Unreviewed authority', '2026-08-20',
                        'iplf-060a:unreviewed', 'Unreviewed mapping.', 'Text', 4,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO judge_decision_index (
                        id, judge_id, authority_document_id, role,
                        match_confidence, created_at, updated_at
                    ) VALUES (
                        'mapping-unreviewed', 'judge-exact',
                        'authority-unreviewed', 'sat_on', NULL,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            eligibility = dict(
                connection.execute(
                    text(
                        """
                        SELECT id, is_analytics_eligible
                        FROM judge_decision_index
                        ORDER BY id
                        """
                    )
                ).all()
            )
            assert bool(eligibility["mapping-exact"]) is True
            assert bool(eligibility["mapping-low"]) is False
            assert bool(eligibility["mapping-unreviewed"]) is False
            connection.execute(
                text(
                    """
                    UPDATE judges
                    SET source_name = 'Official roster'
                    WHERE id = 'judge-exact'
                    """
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="Restore-forward required"):
        command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
