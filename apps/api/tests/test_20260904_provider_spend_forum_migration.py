from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings

PREVIOUS_HEAD = "20260904_0001"
MIGRATION_HEAD = "20260904_0002"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def test_existing_billing_indexes_use_postgres_concurrent_builds() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260904_0002_provider_spend_and_forum_aliases.py"
    )
    migration_source = migration_path.read_text(encoding="utf-8")

    assert "existing_table_indexes = (" in migration_source
    assert 'if bind.dialect.name == "postgresql":' in migration_source
    assert "with op.get_context().autocommit_block():" in migration_source
    assert "postgresql_concurrently=True" in migration_source
    assert 'batch.create_index("ix_billing_usage_events_provider_key"' not in migration_source
    assert 'batch.create_index("ix_billing_usage_attribution_provider_key"' not in migration_source


def test_provider_spend_and_forum_alias_migration_round_trip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'sep04.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, PREVIOUS_HEAD)

    now = datetime.now(UTC).isoformat()
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO companies "
                    "(id, name, slug, company_type, tenant_key, timezone, is_active, "
                    "team_scoping_enabled, created_at) "
                    "VALUES ('company-gba', 'GBA Law Office', 'gba-law-office', "
                    "'law_firm', 'tenant-gba', 'Asia/Calcutta', 1, 0, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO companies "
                    "(id, name, slug, company_type, tenant_key, timezone, is_active, "
                    "team_scoping_enabled, created_at) "
                    "VALUES ('company-pinelabs', '  Pinelabs Pvt. Ltd.  ', "
                    "'pinelabs-pvt-ltd', 'corporate', 'tenant-pinelabs', "
                    "'Asia/Calcutta', 1, 0, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO billing_usage_events "
                    "(id, company_id, usage_type, quantity, unit, estimated_cost_minor, "
                    "currency, created_at) VALUES "
                    "('usage-ik', 'company-gba', 'indian_kanoon_search', 1, "
                    "'provider_call', 25, 'INR', :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO billing_usage_attribution "
                    "(id, company_id, billing_usage_event_id, feature_key, credits_debited, "
                    "provider_units, estimated_internal_cost_minor, tenant_visible, created_at) "
                    "VALUES ('attr-ik', 'company-gba', 'usage-ik', 'licensed_legal_research', "
                    "0, 1, 25, 1, :now)"
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert "provider_key" in {
            str(column["name"]) for column in inspector.get_columns("billing_usage_events")
        }
        assert inspector.has_table("company_provider_spend_policies")
        assert inspector.has_table("provider_spend_reservations")
        assert inspector.has_table("forum_catalog_aliases")
        alias_columns = {
            str(column["name"]) for column in inspector.get_columns("forum_catalog_aliases")
        }
        assert {
            "alias_type",
            "record_version",
            "created_by_platform_admin_id",
            "reviewed_by_platform_admin_id",
            "updated_by_platform_admin_id",
        }.issubset(alias_columns)
        alias_indexes = {
            str(index["name"]) for index in inspector.get_indexes("forum_catalog_aliases")
        }
        assert {
            "ix_forum_catalog_aliases_created_by_platform_admin_id",
            "ix_forum_catalog_aliases_reviewed_by_platform_admin_id",
            "ix_forum_catalog_aliases_updated_by_platform_admin_id",
        }.issubset(alias_indexes)
        assert "normalized_name" in {
            str(column["name"]) for column in inspector.get_columns("forum_catalog_entries")
        }
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT provider_key FROM billing_usage_events WHERE id = 'usage-ik'")
                )
                == "indian-kanoon"
            )
            assert (
                connection.scalar(
                    text("SELECT provider_key FROM billing_usage_attribution WHERE id = 'attr-ik'")
                )
                == "indian-kanoon"
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM company_provider_spend_policies "
                        "WHERE company_id = 'company-gba' AND monthly_limit_minor IS NULL"
                    )
                )
                == 2
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM company_provider_spend_policies "
                        "WHERE company_id = 'company-pinelabs' "
                        "AND monthly_limit_minor IS NULL"
                    )
                )
                == 2
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM company_provider_spend_policies "
                        "WHERE policy_source = "
                        "'user_authorized_named_exception_2026_09_04'"
                    )
                )
                == 4
            )
            assert set(
                connection.scalars(
                    text(
                        "SELECT forum_catalog_entry_id FROM forum_catalog_aliases "
                        "WHERE normalized_alias = 'tishazari'"
                    )
                )
            ) == {
                "district:india-gov:delhi:centraldelhi",
                "district:india-gov:delhi:westdelhi",
            }
            assert (
                connection.scalar(
                    text(
                        "SELECT alias_type FROM forum_catalog_aliases "
                        "WHERE normalized_alias = 'saket' LIMIT 1"
                    )
                )
                == "court_complex"
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT name FROM forum_catalog_entries "
                        "WHERE id = 'consumer:dcdrc:delhi:tis-hazari'"
                    )
                )
                == "District Consumer Commission, Tis Hazari"
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT normalized_name FROM forum_catalog_entries "
                        "WHERE id = 'district:india-gov:delhi:centraldelhi'"
                    )
                )
                == "centraldistrictcourtdelhi"
            )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert not inspector.has_table("forum_catalog_aliases")
        assert not inspector.has_table("provider_spend_reservations")
        assert "normalized_name" not in {
            str(column["name"]) for column in inspector.get_columns("forum_catalog_entries")
        }
        assert "provider_key" not in {
            str(column["name"]) for column in inspector.get_columns("billing_usage_events")
        }
    finally:
        engine.dispose()
