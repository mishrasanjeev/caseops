from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from tests.test_postgres_validation import _seed_company

pytestmark = pytest.mark.postgres


def test_fresh_upgrade_downgrade_legacy_receipts_default_no_paid(pg_engine, monkeypatch):
    name = "document_claim_migration_" + uuid4().hex
    url = pg_engine.url.set(database=name)
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    legacy_ids = [str(uuid4()), str(uuid4())]
    try:
        command.upgrade(cfg, "20260928_0001")
        with Session(engine) as seed:
            company = _seed_company(seed)
            for job_id, status in zip(legacy_ids, ["queued", "processing"], strict=True):
                seed.execute(text(
                    "INSERT INTO document_processing_jobs "
                    "(id, company_id, target_type, attachment_id, action, status, attempt_count, "
                    "processed_char_count, queued_at, updated_at) "
                    "VALUES (:id, :company, 'matter_attachment', :attachment, 'initial_index', "
                    ":status, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"id": job_id, "company": company, "attachment": str(uuid4()), "status": status})
            seed.commit()
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        with engine.connect() as check:
            assert check.execute(text(
                "SELECT id, no_paid_providers FROM document_processing_jobs ORDER BY id"
            )).all() == [(job_id, True) for job_id in sorted(legacy_ids)]
            column = next(row for row in inspect(check).get_columns("document_processing_jobs")
                          if row["name"] == "no_paid_providers")
            assert column["nullable"] is False and "true" in column["default"]
            indexes = {row["name"]: row["column_names"]
                       for row in inspect(check).get_indexes("document_processing_jobs")}
            assert indexes["ix_document_processing_jobs_queue"] == ["status", "queued_at", "id"]
            assert indexes["ix_document_processing_jobs_recovery"] == [
                "status", "started_at", "id",
            ]
        command.downgrade(cfg, "20260928_0001")
        with engine.connect() as check:
            assert "no_paid_providers" not in {
                row["name"] for row in inspect(check).get_columns("document_processing_jobs")
            }
            assert check.execute(text(
                "SELECT id FROM document_processing_jobs ORDER BY id"
            )).scalars().all() == sorted(legacy_ids)
        command.upgrade(cfg, "head")
        with engine.connect() as check:
            assert check.execute(text(
                "SELECT no_paid_providers FROM document_processing_jobs"
            )).scalars().all() == [True, True]
    finally:
        engine.dispose()
        get_settings.cache_clear()
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
