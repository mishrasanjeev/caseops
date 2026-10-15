"""Independent fresh-database upgrade/downgrade, never a tenant DB clone."""

import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from tests.fixtures_postgres_client import temporary_http_database

TABLES = {"ip_portfolio_renewal_series", "ip_portfolio_renewal_occurrences"}
PREVIOUS = "20261011_0001"
HEAD = "20261015_0001"


@contextmanager
def _fresh_engine(kind, tmp_path):
    if kind == "postgres":
        source = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
        with temporary_http_database(source) as engine:
            yield engine
    else:
        engine = create_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'renewal-migration.db').as_posix()}"
        )
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.mark.parametrize("kind", ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def test_fresh_upgrade_preserves_catalog_and_empty_downgrade(kind, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    with _fresh_engine(kind, tmp_path) as engine:
        url = engine.url.render_as_string(hide_password=False)
        monkeypatch.setenv("CASEOPS_ENV", "local")
        monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
        get_settings.cache_clear()
        clear_engine_cache()
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, PREVIOUS)
        before_tables = set(inspect(engine).get_table_names())
        assert TABLES.isdisjoint(before_tables)
        with engine.connect() as connection:
            before_aliases = connection.execute(
                text("SELECT id, normalized_alias FROM forum_catalog_aliases ORDER BY id")
            ).all()
        assert before_aliases
        command.upgrade(config, HEAD)
        schema = inspect(engine)
        assert set(schema.get_table_names()) == before_tables | TABLES
        assert "renewal_reminder_policy_json" in {
            row["name"] for row in schema.get_columns("ip_workspace_configurations")
        }
        assert ("series_id", "generation", "local_on") in {
            tuple(row["column_names"])
            for row in schema.get_unique_constraints("ip_portfolio_renewal_occurrences")
        }
        assert {
            tuple(row["constrained_columns"])
            for row in schema.get_foreign_keys("ip_portfolio_renewal_occurrences")
        } >= {
            ("series_id", "company_id", "docket_id"),
            ("recipient_membership_id", "company_id"),
            ("docket_id", "source_version"),
            ("company_id", "delivery_key"),
        }
        assert ("next_reminder_at", "company_id", "id") in {
            tuple(row["column_names"]) for row in schema.get_indexes("ip_portfolio_renewal_series")
        }
        assert ("reconcile_after", "company_id", "id") in {
            tuple(row["column_names"]) for row in schema.get_indexes("ip_portfolio_renewal_series")
        }
        assert ("company_id", "last_delivery_key") in {
            tuple(row["constrained_columns"])
            for row in schema.get_foreign_keys("ip_portfolio_renewal_series")
        }
        assert (
            "company_id",
            "docket_id",
            "source_version",
            "generation",
            "local_on",
            "created_at",
            "id",
        ) in {
            tuple(row["column_names"])
            for row in schema.get_indexes("ip_portfolio_renewal_occurrences")
        }
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT id, normalized_alias FROM forum_catalog_aliases ORDER BY id")
                ).all()
                == before_aliases
            )
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        command.downgrade(config, PREVIOUS)
        assert set(inspect(engine).get_table_names()) == before_tables
        command.upgrade(config, HEAD)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD


@pytest.mark.parametrize("policy_only", [False, True])
def test_populated_evidence_or_policy_refuses_destructive_downgrade(
    client, monkeypatch, policy_only
):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import select

    from caseops_api.db.models import IpWorkspaceConfiguration
    from caseops_api.db.session import get_engine, get_session_factory
    from tests.test_ip_portfolio_spec_20261013 import _actor
    from tests.test_ip_renewal_tracker_20261015 import _imported

    actor = _actor(client) if policy_only else _imported(client, monkeypatch)[0]
    if policy_only:
        with get_session_factory()() as session:
            config = session.scalar(
                select(IpWorkspaceConfiguration).where(
                    IpWorkspaceConfiguration.company_id == actor["company"]["id"]
                )
            )
            config.renewal_reminder_policy_json = {"cadence_days": 2}
            session.commit()
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261015_0001_portfolio_renewal_occurrences.py"
    )
    spec = importlib.util.spec_from_file_location("renewal_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = get_engine()
    before = set(inspect(engine).get_table_names())
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        with pytest.raises(RuntimeError, match="Restore-forward required"):
            migration.downgrade()
    assert set(inspect(engine).get_table_names()) == before
