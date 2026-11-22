"""The additive journal-feed migration keeps tenant keys exact and refuses downgrade."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    IpJournalFeedSetting,
    IpJournalFeedTenantRun,
    IpPublicJournalDocument,
    User,
)
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config

PREVIOUS = "20261112_0001"
HEAD = "20261122_0001"
PUBLIC = {"ip_public_journal_checks", "ip_public_journal_documents", "ip_public_journal_entries"}
TENANT = {"ip_journal_feed_settings", "ip_journal_feed_tenant_runs"}


@pytest.mark.parametrize("kind", KINDS)
def test_journal_feed_migration_shape_tenant_keys_and_retained_downgrade(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        old_tables = set(inspect(engine).get_table_names())
        assert not (PUBLIC | TENANT) & old_tables
        command.upgrade(config, HEAD)
        schema = inspect(engine)
        assert set(schema.get_table_names()) == old_tables | PUBLIC | TENANT
        assert not database_foreign_key_gaps(schema, table_names=PUBLIC | TENANT)
        # The shared public store has no tenant column; the tenant tables do.
        for table in PUBLIC:
            assert "company_id" not in {column["name"] for column in schema.get_columns(table)}
        for table in TENANT:
            assert "company_id" in {column["name"] for column in schema.get_columns(table)}
        now = datetime(2026, 11, 22, tzinfo=UTC)
        with Session(engine) as session:
            if kind == "sqlite":
                session.execute(text("PRAGMA foreign_keys=ON"))
            members = []
            for name in ("one", "two"):
                company = Company(
                    name=f"Synthetic feed tenant {name}", slug=f"feed-migration-{name}",
                    tenant_key=f"feed-migration-{name}", company_type="law_firm",
                )
                user = User(
                    full_name="Synthetic feed actor", email=f"feed-{name}@example.com",
                    password_hash="test-fixture-unused",
                )
                members.append(CompanyMembership(company=company, user=user, role="owner"))
            session.add_all(members)
            session.flush()
            first, other = members
            document = IpPublicJournalDocument(
                source_key="ipindia-tm-journal", journal_number="2287",
                journal_date=date(2026, 11, 16), file_name="ipo-docs\\Class 1-9.pdf",
                source_url="https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal?FileName=x",
                status="parsed", attempts=1, entry_count=0, review_count=0,
                discovered_at=now, updated_at=now,
            )
            session.add(document)
            session.flush()
            session.add(IpJournalFeedSetting(
                company_id=first.company_id, enabled=True, run_as_membership_id=first.id,
                updated_by_membership_id=first.id, version=1, created_at=now, updated_at=now,
            ))
            session.flush()
            # Another tenant's member cannot be the run-as actor.
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(IpJournalFeedSetting(
                    company_id=other.company_id, enabled=True, run_as_membership_id=first.id,
                    updated_by_membership_id=other.id, version=1, created_at=now, updated_at=now,
                ))
                session.flush()
            run = dict(
                document_id=document.id, status="completed", attempts=1, entries_compared=0,
                matched_entries=0, publications_created=0, hits_created=0,
                ingestion_run_ids_json=[], started_at=now,
            )
            session.add(IpJournalFeedTenantRun(
                id=str(uuid4()), company_id=first.company_id, run_as_membership_id=first.id, **run
            ))
            session.flush()
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(IpJournalFeedTenantRun(
                    id=str(uuid4()), company_id=other.company_id,
                    run_as_membership_id=first.id, **run,
                ))
                session.flush()
            session.commit()
        with engine.connect() as connection:
            before = connection.execute(select(IpJournalFeedTenantRun.__table__)).all()
        with pytest.raises(RuntimeError, match="retained evidence; restore-forward only"):
            command.downgrade(config, PREVIOUS)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            assert connection.execute(select(IpJournalFeedTenantRun.__table__)).all() == before
