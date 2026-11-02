"""Join both actual historical heads without inventing already-applied DDL."""

from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import NativeDeviceSession, NativeRefreshToken
from tests.test_ip_portfolio_export_worker_migration_20261026 import (
    _assert_shape,
    _old_insert,
    _rows,
)
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company, _seed_membership

HEAD = "20261027_0001"
NATIVE = "20261024_0002"
WORKER = "20261026_0001"
TABLES = ("native_authorization_codes", "native_device_sessions", "native_refresh_tokens")
PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20261027_0001_native_export_merge.py"


def test_merge_revision_only_joins_the_two_existing_histories():
    spec = spec_from_file_location("native_export_merge", PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == HEAD
    assert module.down_revision == (NATIVE, WORKER)
    # Neither function imports an operation object or touches a database.
    module.upgrade()
    module.downgrade()


def native_rows(engine):
    with engine.connect() as connection:
        return {
            table: connection.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY id').all()
            for table in TABLES
        }


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("start", [NATIVE, WORKER])
def test_upgrade_from_each_retained_head_applies_the_missing_branch_once(
    kind, start, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, start)
        schema = inspect(engine)
        assert (set(TABLES) <= set(schema.get_table_names())) is (start == NATIVE)
        assert (
            "dispatch_protocol_version"
            in {column["name"] for column in schema.get_columns("ip_portfolio_export_jobs")}
        ) is (start == WORKER)
        now = datetime(2026, 10, 27, tzinfo=UTC)
        with Session(engine) as session:
            company = _seed_company(session)
            member = _seed_membership(session, company)
            user = session.scalar(
                text("SELECT user_id FROM company_memberships WHERE id=:member"), {"member": member}
            )
            session.execute(
                text(
                    "INSERT INTO user_mfa_step_ups "
                    "(id,user_id,membership_id,purpose,method,completed_at,expires_at,created_at) "
                    "VALUES ('merge-retained-mfa',:user,:member,'step_up','totp',:now,:expiry,:now)"
                ),
                {"user": user, "member": member, "now": now, "expiry": now + timedelta(minutes=5)},
            )
            if start == NATIVE:
                device = NativeDeviceSession(
                    membership_id=member,
                    platform="ios",
                    source_issued_at=now.timestamp(),
                    created_at=now,
                    last_used_at=now,
                    expires_at=now + timedelta(days=1),
                    revoked_at=now,
                    revocation_reason="refresh_replay",
                )
                session.add(device)
                session.flush()
                session.add(
                    NativeRefreshToken(
                        session_id=device.id,
                        token_hash="b" * 64,
                        created_at=now,
                        consumed_at=now,
                        expires_at=now + timedelta(days=1),
                    )
                )
            session.commit()
        legacy_ids = [
            _old_insert(engine, company, member, status=status)
            for status in ("pending", "running", "completed", "failed")
        ]
        original_exports = _rows(engine, old_only=True)
        original_native = native_rows(engine) if start == NATIVE else None
        with engine.connect() as connection:
            original_mfa = connection.execute(
                text(
                    "SELECT id,user_id,membership_id,purpose,method,"
                    "completed_at,expires_at,created_at "
                    "FROM user_mfa_step_ups ORDER BY id"
                )
            ).all()
        command.upgrade(config, HEAD)
        _assert_shape(engine)
        assert _rows(engine, old_only=True) == original_exports
        if original_native is not None:
            assert native_rows(engine) == original_native
        assert not database_foreign_key_gaps(inspect(engine), table_names=set(TABLES))
        for _ in range(2):
            command.upgrade(config, HEAD)
            with engine.connect() as connection:
                assert connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars().all() == [HEAD]
                retained = connection.execute(
                    text(
                        "SELECT id,dispatch_protocol_version,worker_claim_token,"
                        "worker_claim_expires_at "
                        "FROM ip_portfolio_export_jobs ORDER BY id"
                    )
                ).all()
                assert {row.id for row in retained} == set(legacy_ids)
                assert all(tuple(row)[1:] == (0, None, None) for row in retained)
                assert (
                    connection.execute(
                        text(
                            "SELECT id,user_id,membership_id,purpose,method,"
                            "completed_at,expires_at,created_at "
                            "FROM user_mfa_step_ups ORDER BY id"
                        )
                    ).all()
                    == original_mfa
                )
                assert (
                    connection.scalar(
                        text(
                            "SELECT source_token_issued_at FROM user_mfa_step_ups "
                            "WHERE id='merge-retained-mfa'"
                        )
                    )
                    is None
                )
            assert _rows(engine, old_only=True) == original_exports
            if original_native is not None:
                assert native_rows(engine) == original_native
