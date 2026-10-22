"""Fresh cross-dialect upgrade and fail-closed retention of grant history."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause

from alembic import command
from caseops_api.db.models import PlatformAdminMembership, User
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config


def _indexes(schema):
    return [{**row, "dialect_options": {
        key: str(value) if isinstance(value, TextClause) else value
        for key, value in row["dialect_options"].items()
    }} for row in schema.get_indexes("platform_report_admins")]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("populated", [False, True])
def test_removed_column_preserves_identity_catalog_and_refuses_loss(
    kind, populated, tmp_path, monkeypatch, record_property
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, "20261021_0001")
        old_schema = inspect(engine)
        indexes = _indexes(old_schema)
        uniques = old_schema.get_unique_constraints("platform_report_admins")
        grants = Table("platform_report_admins", MetaData(), autoload_with=engine)
        audit = Table("platform_report_audit_events", MetaData(), autoload_with=engine)
        if populated:
            now = datetime.now(UTC)
            with Session(engine) as session:
                user = User(email="retained@migration.example", full_name="Retained Identity",
                            password_hash="synthetic-existing-password-hash")
                session.add(user)
                session.flush()
                root = PlatformAdminMembership(user_id=user.id)
                session.add(root)
                session.flush()
                grant_id, audit_id = str(uuid4()), str(uuid4())
                session.execute(grants.insert().values(
                    id=grant_id, user_id=user.id, root_platform_admin_id=root.id,
                    created_by_report_admin_id=None, role="manager", status="active", auth_epoch=7,
                    initializes_password=False, mfa_status="enrolled", recovery_code_hashes=[],
                    mfa_failures=0, login_failures=0, created_at=now, updated_at=now,
                ))
                session.execute(audit.insert().values(
                    id=audit_id, report_admin_id=grant_id, actor_user_id=user.id,
                    action="console.synthetic_retained", result="success", created_at=now,
                ))
                session.commit()
        with engine.connect() as connection:
            before = connection.execute(select(grants)).mappings().all()
            audit_before = connection.execute(select(audit)).mappings().all()
            users_before = connection.execute(
                text("SELECT id,email,password_hash FROM users")
            ).all()
        command.upgrade(config, "20261022_0001")
        schema = inspect(engine)
        column = next(c for c in schema.get_columns("platform_report_admins")
                      if c["name"] == "removed_at")
        assert column["nullable"] is True and column["default"] is None
        assert _indexes(schema) == indexes
        assert schema.get_unique_constraints("platform_report_admins") == uniques
        with engine.begin() as connection:
            assert connection.execute(select(grants)).mappings().all() == before
            assert connection.execute(select(audit)).mappings().all() == audit_before
            assert connection.execute(
                text("SELECT id,email,password_hash FROM users")
            ).all() == users_before
            assert connection.scalar(text(
                "SELECT count(*) FROM platform_report_admins WHERE removed_at IS NOT NULL"
            )) == 0
            if populated:
                connection.execute(text(
                    "UPDATE platform_report_admins SET removed_at=:now WHERE id=:id"
                ), {"now": datetime.now(UTC), "id": grant_id})
        with engine.connect() as connection:
            retained = connection.execute(text(
                "SELECT id,removed_at,auth_epoch FROM platform_report_admins ORDER BY id"
            )).all()
        with pytest.raises(RuntimeError, match="retained access history"):
            command.downgrade(config, "20261021_0001")
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == "20261022_0001"
            assert connection.execute(text(
                "SELECT id,removed_at,auth_epoch FROM platform_report_admins ORDER BY id"
            )).all() == retained
            assert connection.execute(select(audit)).mappings().all() == audit_before
            assert connection.execute(
                text("SELECT id,email,password_hash FROM users")
            ).all() == users_before
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT id,removed_at,auth_epoch FROM platform_report_admins ORDER BY id"
            )).all() == retained
        record_property("fresh_database_not_application_clone", True)
        record_property("unique_grant_and_retained_audit_preserved", True)
