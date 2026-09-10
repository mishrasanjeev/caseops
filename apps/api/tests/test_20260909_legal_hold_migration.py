"""Independently fresh upgrade, empty rollback, and populated rollback refusal."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import (
    Company,
    LegalHold,
    LegalHoldItem,
    LegalHoldReleaseRequest,
    TenantDataOperation,
)

HEAD = "20260909_0003"
PREDECESSOR = "20260909_0002"
TABLE = "legal_hold_release_requests"


def _seed_pre_feature_terminal_scope(engine):
    with Session(engine) as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == PREDECESSOR
        assert session.scalar(select(LegalHoldItem.id)) is None
        company = Company(
            name="Synthetic legacy scope",
            slug="legacy-scope",
            company_type="law_firm",
            tenant_key="legacy-scope",
        )
        session.add(company)
        session.flush()
        hold = LegalHold(
            company_id=company.id,
            key="legacy",
            title="Synthetic retained hold",
            authority_reference="fixture://legacy",
            creator_label_snapshot="Fixture",
            status="released",
            released_at=datetime.now(UTC),
        )
        session.add(hold)
        session.commit()
        assert session.get(LegalHold, hold.id).status == "released"
        # Deliberately demonstrate the pre-feature insertion hole, before upgrading.
        item = LegalHoldItem(
            company_id=company.id,
            legal_hold_id=hold.id,
            data_class_id="legal_holds",
            target_type="data_class",
            target_reference_hash="a" * 64,
        )
        session.add(item)
        session.commit()
        retained = dict(session.execute(select(LegalHoldItem.__table__)).mappings().one())
        return retained


def _assert_terminal_scope_retained_and_fenced(engine, retained):
    with Session(engine) as session:
        assert (
            dict(
                session.execute(
                    select(LegalHoldItem.__table__).where(LegalHoldItem.id == retained["id"])
                )
                .mappings()
                .one()
            )
            == retained
        )
        session.add(
            LegalHoldItem(
                company_id=retained["company_id"],
                legal_hold_id=retained["legal_hold_id"],
                data_class_id="legal_holds",
                target_type="data_class",
                target_reference_hash="b" * 64,
            )
        )
        with pytest.raises(DBAPIError, match="scope can only be added to a draft"):
            session.commit()
        session.rollback()
        assert session.get(LegalHold, retained["legal_hold_id"]).status == "released"
        assert (
            dict(
                session.execute(
                    select(LegalHoldItem.__table__).where(LegalHoldItem.id == retained["id"])
                )
                .mappings()
                .one()
            )
            == retained
        )


def _assert_draft_scope_changes_version(engine, company_id):
    with Session(engine) as session:
        hold = LegalHold(
            company_id=company_id,
            key="draft-scope",
            title="Synthetic draft hold",
            authority_reference="fixture://draft",
            creator_label_snapshot="Fixture",
        )
        session.add(hold)
        session.commit()
        before_scope = hold.updated_at
        session.add(
            LegalHoldItem(
                company_id=company_id,
                legal_hold_id=hold.id,
                data_class_id="legal_holds",
                target_type="data_class",
                target_reference_hash="c" * 64,
            )
        )
        session.commit()
        session.refresh(hold)
        assert hold.updated_at.replace(tzinfo=UTC) > before_scope.replace(tzinfo=UTC)
        hold.status = "cancelled"
        session.commit()
        session.add(
            LegalHoldItem(
                company_id=company_id,
                legal_hold_id=hold.id,
                data_class_id="legal_hold_items",
                target_type="data_class",
                target_reference_hash="d" * 64,
            )
        )
        with pytest.raises(DBAPIError, match="scope can only be added to a draft"):
            session.commit()
        session.rollback()
        assert session.get(LegalHold, hold.id).status == "cancelled"


def _rehearse(url, monkeypatch):
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    get_settings.cache_clear()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(config, PREDECESSOR)
    engine = create_engine(url)
    try:
        retained = _seed_pre_feature_terminal_scope(engine)
        command.upgrade(config, HEAD)
        _assert_terminal_scope_retained_and_fenced(engine, retained)
        _assert_draft_scope_changes_version(engine, retained["company_id"])
        inspector = inspect(engine)
        assert TABLE in inspector.get_table_names()
        assert {index["name"] for index in inspector.get_indexes("legal_holds")} >= {
            "ix_legal_holds_register_page"
        }
        assert {index["name"] for index in inspector.get_indexes(TABLE)} >= {
            "ix_hold_release_request_page"
        }
        assert database_foreign_key_gaps(inspector, table_names={TABLE}) == ()
        columns = {column["name"] for column in inspector.get_columns(TABLE)}
        assert {"request_hash", "request_json", "expires_at", "requester_user_id"} <= columns
        command.downgrade(config, PREDECESSOR)
        assert TABLE not in inspect(engine).get_table_names()
        assert "ix_legal_holds_register_page" not in {
            index["name"] for index in inspect(engine).get_indexes("legal_holds")
        }
        command.upgrade(config, HEAD)
        assert TABLE in inspect(engine).get_table_names()
        _assert_terminal_scope_retained_and_fenced(engine, retained)
        now = datetime.now(UTC)
        with Session(engine) as session:
            company = Company(
                name="Synthetic migration",
                slug="hold-migration",
                company_type="law_firm",
                tenant_key="hold-migration",
            )
            session.add(company)
            session.flush()
            hold = LegalHold(
                company_id=company.id,
                key="fixture",
                title="Synthetic hold",
                authority_reference="fixture://only",
                creator_label_snapshot="Fixture",
            )
            dry_run = TenantDataOperation(
                company_id=company.id,
                operation_type="tenant_offboarding",
                request_scope_json={},
                request_scope_hash="a" * 64,
                request_evidence_ref="fixture://only",
                requester_label_snapshot="Fixture",
            )
            session.add_all([hold, dry_run])
            session.flush()
            proposal = LegalHoldReleaseRequest(
                company_id=company.id,
                legal_hold_id=hold.id,
                dry_run_id=dry_run.id,
                idempotency_key="fixture",
                requester_user_id="retained-user",
                requester_membership_id="retained-member",
                requester_label_snapshot="Fixture",
                reason_reference="fixture://only",
                request_json={},
                request_hash="b" * 64,
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
            session.add(proposal)
            session.commit()
            proposal_id = proposal.id
        with pytest.raises(RuntimeError, match="roll forward"):
            command.downgrade(config, PREDECESSOR)
        with Session(engine) as session:
            assert session.get(LegalHoldReleaseRequest, proposal_id).request_hash == "b" * 64
            assert session.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            for verb in (
                "UPDATE legal_hold_release_requests SET reason_reference='changed'",
                "DELETE FROM legal_hold_release_requests",
            ):
                with pytest.raises(DBAPIError, match="immutable"):
                    session.execute(text(verb))
                session.rollback()
                assert session.scalar(select(LegalHoldReleaseRequest.id)) == proposal_id
    finally:
        engine.dispose()


def test_fresh_sqlite_upgrade_empty_rollback_reupgrade(tmp_path, monkeypatch):
    _rehearse(f"sqlite+pysqlite:///{tmp_path / 'fresh-hold-migration.db'}", monkeypatch)


@pytest.mark.postgres
def test_fresh_postgres_upgrade_empty_rollback_reupgrade(pg_engine, monkeypatch):
    from tests.fixtures_postgres_client import temporary_http_database

    with temporary_http_database(pg_engine.url) as fresh:
        _rehearse(fresh.url.render_as_string(hide_password=False), monkeypatch)
