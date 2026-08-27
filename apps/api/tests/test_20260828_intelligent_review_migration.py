from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.session import clear_engine_cache
from caseops_api.scripts.check_database_indexes import build_index_health_report

PREVIOUS_HEAD = "20260827_0002"
MIGRATION_HEAD = "20260828_0001"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260828_0001_intelligent_review_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("intelligent_review_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraint_names(rows: list[dict[str, object]]) -> set[str]:
    return {str(row["name"]) for row in rows if row.get("name")}


def _health_failures(health: dict[str, object]) -> dict[str, object]:
    failures: dict[str, object] = {}
    for key, value in health.items():
        if (
            key in {"status", "schema_revisions", "sequential_scan_warnings"}
            or not isinstance(value, list)
            or not value
        ):
            continue
        if key == "missing_declared_indexes":
            failures[key] = [
                f"{item['table_name']}.{item['index_name']}" for item in value
            ]
        else:
            failures[key] = {"count": len(value), "sample": value[:10]}
    return failures


def test_intelligent_review_migration_round_trip_and_index_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'intelligent-review.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config()

    command.upgrade(config, PREVIOUS_HEAD)
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        recommendation_columns = {
            str(column["name"]) for column in inspector.get_columns("recommendations")
        }
        assert {
            "ip_docket_id",
            "ip_proceeding_id",
            "source_research_report_id",
            "review_state",
            "review_progress",
            "review_payload_json",
            "source_manifest_json",
            "review_selection_json",
            "finalized_by_membership_id",
            "finalized_at",
            "updated_at",
        } <= recommendation_columns
        assert "source_recommendation_id" in {
            str(column["name"]) for column in inspector.get_columns("drafts")
        }
        assert {
            "fk_recommendation_matter_company",
            "fk_recommendation_ip_docket_company",
            "fk_recommendation_ip_proceeding_target",
            "fk_recommendation_research_report_company",
            "fk_recommendation_finalizer_company",
        } <= _constraint_names(inspector.get_foreign_keys("recommendations"))
        assert {
            "ck_recommendation_exactly_one_target",
            "ck_recommendation_review_source",
            "ck_recommendation_review_state",
            "ck_recommendation_review_progress",
        } <= _constraint_names(inspector.get_check_constraints("recommendations"))
        assert "uq_draft_source_recommendation" in _constraint_names(
            inspector.get_unique_constraints("drafts")
        )
        recommendation_indexes = _constraint_names(
            inspector.get_indexes("recommendations")
        )
        assert {
            "ix_recommendations_company_review_state_created",
            "ix_recommendations_company_ip_docket_created",
            "ix_fk_recommendations_finalized_by_me_a0403a0f",
            "ix_fk_recommendations_ip_docket_id_company",
            "ix_fk_recommendations_ip_proceeding_i_0c288976",
            "ix_fk_recommendations_source_research_ae8b70ed",
            "ix_fk_recommendations_matter_id_compa_edcf1c7f",
        } <= recommendation_indexes
        assert database_foreign_key_gaps(
            inspector,
            table_names={"recommendations", "drafts"},
        ) == ()
        with engine.connect() as connection:
            health = build_index_health_report(connection)
        assert health["status"] == "ok", _health_failures(health)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                MIGRATION_HEAD
            )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert "ip_docket_id" not in {
            str(column["name"])
            for column in inspector.get_columns("recommendations")
        }
        assert "source_recommendation_id" not in {
            str(column["name"]) for column in inspector.get_columns("drafts")
        }
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)


def test_intelligent_review_downgrade_refuses_retained_work_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _module()

    class ScalarResult:
        @staticmethod
        def scalar_one() -> int:
            return 1

    class FakeConnection:
        dialect = type("Dialect", (), {"name": "sqlite"})()

        @staticmethod
        def execute(_statement: object) -> ScalarResult:
            return ScalarResult()

    class FakeOperations:
        @staticmethod
        def get_bind() -> FakeConnection:
            return FakeConnection()

    monkeypatch.setattr(migration, "op", FakeOperations())
    with pytest.raises(RuntimeError, match="intelligent-review work product exists"):
        migration.downgrade()
