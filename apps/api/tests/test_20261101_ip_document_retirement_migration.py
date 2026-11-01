"""20261101_8146 adds audited retirement columns to ip_documents, nothing else."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.index_coverage import database_foreign_key_gaps, foreign_key_index_name
from caseops_api.db.session import clear_engine_cache
from tests.fixtures_postgres_client import temporary_http_database
from tests.test_ip_document_taxonomy_defaults_migration_20261031 import (
    _alembic_config,
    _company,
    _membership,
)

PARENT = "20261031_0002"
REVISION = "20261101_8146"


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def fresh_engine(request, tmp_path):
    if request.param == "postgres":
        source = request.getfixturevalue("pg_engine")
        with temporary_http_database(source.url) as engine:
            yield engine
    else:
        engine = create_engine(
            "sqlite+pysqlite:///" + (tmp_path / "document-retirement.db").as_posix()
        )
        try:
            yield engine
        finally:
            engine.dispose()


def test_retirement_columns_are_additive_complete_and_indexed(fresh_engine, monkeypatch) -> None:
    config = _alembic_config(fresh_engine, monkeypatch)
    try:
        command.upgrade(config, PARENT)
        before = {column["name"] for column in inspect(fresh_engine).get_columns("ip_documents")}
        assert not before & {"retired_at", "retired_by_membership_id", "retirement_reason"}
        command.upgrade(config, REVISION)
    finally:
        clear_engine_cache()

    inspector = inspect(fresh_engine)
    columns = {column["name"]: column for column in inspector.get_columns("ip_documents")}
    for name in ("retired_at", "retired_by_membership_id", "retirement_reason"):
        assert columns[name]["nullable"] is True
    index = foreign_key_index_name("ip_documents", ("retired_by_membership_id", "company_id"))
    assert index in {row["name"] for row in inspector.get_indexes("ip_documents")}
    assert database_foreign_key_gaps(inspector, table_names=["ip_documents"]) == ()

    with Session(fresh_engine) as session:
        company_id = _company(session, "retirement-migration")
        member = _membership(session, company_id, role="owner", created_at=datetime.now(UTC))
        session.commit()
        if fresh_engine.dialect.name == "sqlite":
            session.execute(text("PRAGMA foreign_keys=OFF"))
        # A partial retirement record is refused by the completeness check.
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO ip_documents (id, company_id, taxonomy_entry_id, title, "
                    "confidentiality, is_privileged, current_version, created_by_membership_id, "
                    "created_at, updated_at, retired_at) VALUES ('doc-partial', :company, "
                    "'tax', 'Partial', 'internal', false, 1, :member, :now, :now, :now)"
                ),
                {"company": company_id, "member": member, "now": datetime.now(UTC)},
            )
            session.flush()
        session.rollback()
