"""Independent PostgreSQL upgrade preserves legacy MFA and replay evidence."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.base import Base
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import NativeDeviceSession, NativeRefreshToken, UserMFAStepUp
from tests.test_platform_console_migration import fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company, _seed_membership

pytestmark = pytest.mark.postgres
TABLES = {"native_authorization_codes", "native_device_sessions", "native_refresh_tokens"}


def test_native_upgrade_replay_and_refused_downgrade_retain_security_evidence(
    tmp_path, monkeypatch
):
    with fresh_engine("postgres", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, "20261022_0001")
        assert not TABLES.intersection(inspect(engine).get_table_names())
        now = datetime.now(UTC)
        with Session(engine) as session:
            company_id = _seed_company(session)
            membership_id = _seed_membership(session, company_id)
            user_id = session.scalar(
                text("SELECT user_id FROM company_memberships WHERE id = :id"),
                {"id": membership_id},
            )
            session.execute(
                text(
                    "INSERT INTO user_mfa_step_ups "
                    "(id, user_id, membership_id, purpose, method, "
                    "completed_at, expires_at, created_at) "
                    "VALUES ('legacy-native-proof', :user, :member, 'step_up', "
                    "'totp', :now, :expiry, :now)"
                ),
                {
                    "user": user_id,
                    "member": membership_id,
                    "now": now,
                    "expiry": now + timedelta(minutes=5),
                },
            )
            session.commit()
        command.upgrade(config, "20261024_0002")
        schema = inspect(engine)
        assert TABLES <= set(schema.get_table_names())
        assert not database_foreign_key_gaps(schema, table_names=TABLES)
        for name in TABLES:
            assert {column["name"] for column in schema.get_columns(name)} == set(
                Base.metadata.tables[name].columns.keys()
            )
            assert {index.name for index in Base.metadata.tables[name].indexes} <= {
                index["name"] for index in schema.get_indexes(name)
            }
        with Session(engine) as session:
            proof = session.get(UserMFAStepUp, "legacy-native-proof")
            assert proof.source_token_issued_at is None
            device = NativeDeviceSession(
                membership_id=membership_id,
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
                    token_hash="a" * 64,
                    created_at=now,
                    consumed_at=now,
                    expires_at=now + timedelta(days=1),
                )
            )
            session.commit()
            device_id = device.id
        with pytest.raises(RuntimeError, match="roll-forward or restore"):
            command.downgrade(config, "20261022_0001")
        command.upgrade(config, "20261024_0002")
        with Session(engine) as session:
            assert session.get(UserMFAStepUp, "legacy-native-proof").source_token_issued_at is None
            assert session.get(NativeDeviceSession, device_id).revocation_reason == "refresh_replay"
            assert (
                session.scalar(
                    select(NativeRefreshToken.token_hash).where(
                        NativeRefreshToken.session_id == device_id,
                    )
                )
                == "a" * 64
            )
            assert (
                session.scalar(text("SELECT version_num FROM alembic_version")) == "20261024_0002"
            )
