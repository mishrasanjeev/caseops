import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import IpSpecialistObservation, IpSpecialistRecord, IpSpecialistVersion
from tests import test_ip_specialist as journeys
from tests.fixtures_postgres_client import temporary_http_database
from tests.test_ip_specialist_postgres import _seed
from tests.test_ip_specialist_schema import MODELS, assert_schema

pytestmark = pytest.mark.postgres
registered_intake = journeys.registered_intake


def test_specialist_migration_fresh_upgrade_empty_downgrade_and_restore(
    monkeypatch, registered_intake
):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    predecessor = ScriptDirectory.from_config(config).get_revision("20260909_0005").down_revision
    source_url = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    # No application database or migrated test template is cloned by this rehearsal.
    with temporary_http_database(source_url) as engine:
        monkeypatch.setenv("CASEOPS_DATABASE_URL", engine.url.render_as_string(hide_password=False))
        monkeypatch.setenv("CASEOPS_ENV", "local")
        get_settings.cache_clear()
        command.upgrade(config, predecessor)
        before = set(inspect(engine).get_table_names())
        command.upgrade(config, "20260909_0005")
        tables = {model.__tablename__ for model in MODELS}
        inspector = inspect(engine)
        assert_schema(inspector)
        assert set(inspector.get_table_names()) == before | tables
        assert database_foreign_key_gaps(inspector, table_names=tables) == ()
        for model in (IpSpecialistRecord, IpSpecialistVersion, IpSpecialistObservation):
            assert {column.name for column in model.__table__.columns} == {
                column["name"] for column in inspector.get_columns(model.__tablename__)
            }
            assert {index.name for index in model.__table__.indexes} <= {
                index["name"] for index in inspector.get_indexes(model.__tablename__)
            }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM companies")) == 0
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                        "('ip_specialist_versions_immutable', "
                        "'ip_specialist_observations_immutable', "
                        "'ip_specialist_workflow_versions_immutable', "
                        "'ip_specialist_workflow_sources_immutable', "
                        "'ip_specialist_obligation_links_immutable', "
                        "'ip_specialist_obligation_events_immutable')"
                    )
                )
                == 6
            )
        command.downgrade(config, predecessor)
        assert set(inspect(engine).get_table_names()) == before
        command.upgrade(config, "20260909_0005")
        assert set(inspect(engine).get_table_names()) == before | tables
        _, _, record = _seed(engine)
        with pytest.raises(
            RuntimeError, match="Retained specialist evidence prevents destructive downgrade"
        ):
            command.downgrade(config, predecessor)
        assert set(inspect(engine).get_table_names()) == before | tables
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM ip_specialist_versions WHERE record_id = :record"),
                    {"record": str(record.id)},
                )
                == 1
            )
