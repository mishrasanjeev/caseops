"""IPLF-052D migration: tenant keys are exact and retained lineage blocks downgrade."""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    IpOfficialSearchImport,
    User,
)
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company, _seed_membership

PREVIOUS = "20261122_0631"
HEAD = "20261123_0001"
TABLE = "ip_official_search_imports"
REFUSAL = f"{TABLE} holds retained official-page lineage; restore-forward only"


def _row(company_id: str, membership_id: str, digest: str) -> IpOfficialSearchImport:
    return IpOfficialSearchImport(
        company_id=company_id,
        source_kind="ipindia_estatus",
        official_url="https://tmrsearch.ipindia.gov.in/estatus",
        search_query_json={"application_number": "7012345"},
        original_filename="estatus.html",
        content_kind="html",
        byte_size=10,
        file_sha256=digest,
        parser_version="ipindia-official-page-v1",
        parse_status="parsed",
        fields_json={"application_number": "7012345"},
        published_values_json={},
        review_items_json=[],
        attribution="Office of the Controller General of Patents, Designs and Trade Marks",
        resolution_status="pending",
        uploaded_by_membership_id=membership_id,
        uploaded_at=datetime(2026, 11, 23, tzinfo=UTC),
        version=1,
    )


def seed_retained_import(engine) -> None:
    """One retained import, so a downgrade from this head refuses before any DDL."""
    with Session(engine) as session:
        company = _seed_company(session)
        member = _seed_membership(session, company)
        session.add(_row(company, member, "d" * 64))
        session.commit()


@pytest.mark.parametrize("kind", KINDS)
def test_official_search_migration_tenant_keys_and_retained_downgrade(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        old_tables = set(inspect(engine).get_table_names())
        assert TABLE not in old_tables
        command.upgrade(config, HEAD)
        schema = inspect(engine)
        assert set(schema.get_table_names()) == old_tables | {TABLE}
        assert not database_foreign_key_gaps(schema, table_names={TABLE})
        # An empty table can still be rolled back.
        command.downgrade(config, PREVIOUS)
        assert TABLE not in set(inspect(engine).get_table_names())
        command.upgrade(config, HEAD)
        with Session(engine) as session:
            if kind == "sqlite":
                session.execute(text("PRAGMA foreign_keys=ON"))
            members = []
            for name in ("one", "two"):
                company = Company(
                    name=f"Synthetic search tenant {name}",
                    slug=f"search-migration-{name}",
                    tenant_key=f"search-migration-{name}",
                    company_type="law_firm",
                )
                user = User(
                    full_name="Synthetic search actor",
                    email=f"search-{name}@example.com",
                    password_hash="test-fixture-unused",
                )
                members.append(CompanyMembership(company=company, user=user, role="owner"))
            session.add_all(members)
            session.flush()
            first, other = members
            session.add(_row(first.company_id, first.id, "a" * 64))
            session.flush()
            # Another tenant's member cannot be recorded as the uploader.
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(_row(other.company_id, first.id, "b" * 64))
                session.flush()
            # The same file is one import per tenant.
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(_row(first.company_id, first.id, "a" * 64))
                session.flush()
            # A linked row must name its application and registry snapshot.
            with pytest.raises(IntegrityError), session.begin_nested():
                linked = _row(first.company_id, first.id, "c" * 64)
                linked.resolution_status = "linked"
                session.add(linked)
                session.flush()
            session.add(_row(other.company_id, other.id, "a" * 64))
            session.commit()
        with engine.connect() as connection:
            before = connection.execute(select(IpOfficialSearchImport.__table__)).all()
        with pytest.raises(RuntimeError, match=REFUSAL):
            command.downgrade(config, PREVIOUS)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            assert connection.execute(select(IpOfficialSearchImport.__table__)).all() == before


@pytest.mark.postgres
def test_downgrade_waits_for_an_open_upload_and_keeps_its_committed_row(
    tmp_path, monkeypatch
):
    """An upload that commits while the downgrade waits is retained, not dropped."""

    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        with Session(engine) as seed:
            company = _seed_company(seed)
            member = _seed_membership(seed, company)
            seed.commit()
        writer = Session(engine)
        try:
            writer.add(_row(company, member, "e" * 64))
            writer.flush()  # holds the upload's row lock, uncommitted
            with ThreadPoolExecutor(max_workers=1) as executor:
                downgrade = executor.submit(command.downgrade, config, PREVIOUS)
                with pytest.raises(FutureTimeoutError):
                    downgrade.result(timeout=1)
                writer.commit()
                with pytest.raises(RuntimeError, match=REFUSAL):
                    downgrade.result(timeout=30)
        finally:
            writer.close()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            assert connection.scalar(text(f"SELECT count(*) FROM {TABLE}")) == 1
