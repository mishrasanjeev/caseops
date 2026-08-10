from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import Company, Matter
from caseops_api.db.session import clear_engine_cache

TARGET_TABLES = {
    "matter_tasks",
    "matter_hearings",
    "hearing_reminders",
    "matter_next_hearing_history",
    "matter_next_hearing_suggestions",
    "matter_deadlines",
}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
    finally:
        engine.dispose()


def test_shared_work_expand_backfill_switch_downgrade_reupgrade(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'shared-work.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, "20260809_0001")
    assert _head(database_url) == "20260809_0001"

    engine = create_engine(database_url, future=True)
    try:
        with Session(engine) as session:
            company = Company(
                name="Legacy Shared Work LLP",
                slug="legacy-shared-work",
                company_type="law_firm",
                tenant_key="legacy-shared-work",
                timezone="Asia/Kolkata",
                is_active=True,
            )
            session.add(company)
            session.flush()
            matter = Matter(
                company_id=company.id,
                title="Legacy Matter work",
                matter_code="LEGACY-SHARED-001",
                practice_area="Litigation",
                forum_level="district",
            )
            session.add(matter)
            session.flush()
            company_id = company.id
            matter_id = matter.id
            session.execute(
                text(
                    "INSERT INTO matter_tasks "
                    "(id, matter_id, title, status, priority, created_at, updated_at) "
                    "VALUES "
                    "('legacy-task-before-backfill', :matter_id, 'Legacy task', "
                    "'todo', 'medium', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"matter_id": matter_id},
            )
            session.commit()
    finally:
        engine.dispose()

    command.upgrade(config, "20260810_0001")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        for table_name in TARGET_TABLES:
            columns = {column["name"]: column for column in inspector.get_columns(table_name)}
            assert "ip_docket_id" in columns
            assert columns["matter_id"]["nullable"] is True
        assert "ip_docket_id" in {
            column["name"]
            for column in inspector.get_columns("notification_delivery_intents")
        }
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT company_id FROM matter_tasks "
                    "WHERE id = 'legacy-task-before-backfill'"
                )
            ).scalar_one() is None
    finally:
        engine.dispose()
    assert _head(database_url) == "20260810_0001"

    command.upgrade(config, "20260810_0002")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT company_id FROM matter_tasks "
                        "WHERE id = 'legacy-task-before-backfill'"
                    )
                ).scalar_one()
                == company_id
            )
            # Simulate the previous application writing after the one-time
            # backfill but before its revision is fully drained. The switch
            # must remain compatible and reconciliation must be able to see
            # this nullable tail.
            connection.execute(
                text(
                    "INSERT INTO matter_tasks "
                    "(id, matter_id, title, status, priority, created_at, updated_at) "
                    "VALUES "
                    "('legacy-task-after-backfill', :matter_id, 'Draining revision task', "
                    "'todo', 'medium', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"matter_id": matter_id},
            )
    finally:
        engine.dispose()
    assert _head(database_url) == "20260810_0002"

    command.upgrade(config, "20260810_0003")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        for table_name in TARGET_TABLES:
            checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table_name)
            }
            assert any(name and name.endswith("exactly_one_target") for name in checks)
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT company_id FROM matter_tasks "
                    "WHERE id = 'legacy-task-after-backfill'"
                )
            ).scalar_one() is None
    finally:
        engine.dispose()
    assert _head(database_url) == "20260810_0003"

    command.upgrade(config, "20260810_0004")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        hearing_columns = {
            column["name"]: column
            for column in inspector.get_columns("matter_hearings")
        }
        assert {
            "location_text",
            "meeting_url",
            "attendee_membership_ids_json",
        }.issubset(hearing_columns)
        reminder_columns = {
            column["name"]: column
            for column in inspector.get_columns("hearing_reminders")
        }
        assert reminder_columns["schedule_generation"]["nullable"] is False
        reminder_uniques = {
            constraint["name"]: set(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("hearing_reminders")
        }
        assert reminder_uniques[
            "uq_hearing_reminders_recipient_channel_time_generation"
        ] == {
            "hearing_id",
            "recipient_membership_id",
            "channel",
            "scheduled_for",
            "schedule_generation",
        }
    finally:
        engine.dispose()
    assert _head(database_url) == "20260810_0004"

    command.downgrade(config, "20260809_0001")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        for table_name in TARGET_TABLES:
            assert "ip_docket_id" not in {
                column["name"] for column in inspector.get_columns(table_name)
            }
    finally:
        engine.dispose()
    assert _head(database_url) == "20260809_0001"

    command.upgrade(config, "20260810_0004")
    assert _head(database_url) == "20260810_0004"
