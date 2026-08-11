from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            )
    finally:
        engine.dispose()


def test_record_access_expand_backfill_switch_downgrade_reupgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'record-access.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)
    command.upgrade(config, "20260810_0004")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO companies (
                        id, name, slug, company_type, tenant_key, timezone,
                        is_active, team_scoping_enabled, created_at
                    ) VALUES (
                        'access-company', 'Access LLP', 'access-llp', 'law_firm',
                        'access-llp', 'Asia/Kolkata', true, false, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            for user_id, email in (
                ("access-owner-user", "owner@access.test"),
                ("access-member-user", "member@access.test"),
                ("access-tail-user", "tail@access.test"),
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO users (
                            id, email, full_name, password_hash, is_active, created_at
                        ) VALUES (
                            :id, :email, :email, 'fixture', true, CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {"id": user_id, "email": email},
                )
            for membership_id, user_id, role in (
                ("access-owner", "access-owner-user", "owner"),
                ("access-member", "access-member-user", "member"),
                ("access-tail", "access-tail-user", "member"),
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO company_memberships (
                            id, company_id, user_id, role, is_active, created_at
                        ) VALUES (
                            :id, 'access-company', :user_id, :role, true,
                            CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {"id": membership_id, "user_id": user_id, "role": role},
                )
            connection.execute(
                text(
                    """
                    INSERT INTO matters (
                        id, company_id, assignee_membership_id, title, matter_code,
                        status, practice_area, forum_level, is_active,
                        lifecycle_version, restricted_access, created_at, updated_at
                    ) VALUES (
                        'access-matter', 'access-company', 'access-member',
                        'Restricted legacy Matter', 'ACCESS-1', 'intake',
                        'IP', 'high_court', true, 0, true,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO ip_docket_records (
                        id, company_id, matter_id, record_type, title, status,
                        is_active, lifecycle_version, archived_by_matter_disposal,
                        restricted, current_version, created_by_membership_id,
                        created_at, updated_at
                    ) VALUES (
                        'access-docket', 'access-company', 'access-matter',
                        'trademark', 'Restricted legacy docket', 'draft',
                        true, 0, false, false, 1, 'access-owner',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO matter_access_grants (
                        id, matter_id, membership_id, access_level, reason,
                        granted_by_membership_id, created_at
                    ) VALUES (
                        'legacy-grant', 'access-matter', 'access-member', 'member',
                        'legacy grant', 'access-owner', CURRENT_TIMESTAMP
                    )
                    """
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "20260811_0001")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        grant_columns = {
            column["name"] for column in inspector.get_columns("matter_access_grants")
        }
        wall_columns = {
            column["name"] for column in inspector.get_columns("ethical_walls")
        }
        assert {
            "company_id",
            "ip_docket_id",
            "team_id",
            "effective_from",
            "expires_at",
            "revoked_at",
            "record_version",
        }.issubset(grant_columns)
        assert {
            "company_id",
            "ip_docket_id",
            "excluded_team_id",
            "effective_from",
            "expires_at",
            "revoked_at",
            "record_version",
        }.issubset(wall_columns)
        assert "ip_docket_id" in {
            column["name"] for column in inspector.get_columns("audit_events")
        }
    finally:
        engine.dispose()
    assert _head(database_url) == "20260811_0001"

    command.upgrade(config, "20260811_0002")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            assert connection.execute(
                text(
                    "SELECT company_id FROM matter_access_grants "
                    "WHERE id = 'legacy-grant'"
                )
            ).scalar_one() == "access-company"
            assert connection.execute(
                text(
                    "SELECT restricted FROM ip_docket_records "
                    "WHERE id = 'access-docket'"
                )
            ).scalar_one()
            ip_grantees = set(
                connection.execute(
                    text(
                        "SELECT membership_id FROM matter_access_grants "
                        "WHERE ip_docket_id = 'access-docket'"
                    )
                ).scalars()
            )
            assert {"access-owner", "access-member"}.issubset(ip_grantees)
            connection.execute(
                text(
                    """
                    INSERT INTO matter_access_grants (
                        id, matter_id, membership_id, access_level, reason,
                        granted_by_membership_id, created_at
                    ) VALUES (
                        'legacy-tail-grant', 'access-matter', 'access-tail',
                        'member', 'draining writer', 'access-owner',
                        CURRENT_TIMESTAMP
                    )
                    """
                )
            )
    finally:
        engine.dispose()
    assert _head(database_url) == "20260811_0002"

    command.upgrade(config, "20260811_0003")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT company_id FROM matter_access_grants "
                    "WHERE id = 'legacy-tail-grant'"
                )
            ).scalar_one() == "access-company"
        for table_name in ("matter_access_grants", "ethical_walls"):
            checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table_name)
            }
            assert any(name and name.endswith("exactly_one_target") for name in checks)
            assert any(name and name.endswith("exactly_one_subject") for name in checks)
        team_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("teams")
        }
        assert "uq_teams_id_company_id" in team_uniques
    finally:
        engine.dispose()
    assert _head(database_url) == "20260811_0003"

    command.downgrade(config, "20260810_0004")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert "ip_docket_id" not in {
            column["name"] for column in inspector.get_columns("matter_access_grants")
        }
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM matter_access_grants "
                    "WHERE id = 'legacy-grant'"
                )
            ).scalar_one() == 1
    finally:
        engine.dispose()
    assert _head(database_url) == "20260810_0004"

    command.upgrade(config, "20260811_0003")
    assert _head(database_url) == "20260811_0003"
