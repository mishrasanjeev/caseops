from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarEventSync,
    Company,
    CompanyMembership,
    Matter,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    User,
    UserCalendarConnection,
)
from caseops_api.db.session import clear_engine_cache


def _alembic_config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def test_lifecycle_migration_neutralizes_legacy_closed_children(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "legacy-lifecycle.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)
    command.upgrade(config, "head")

    company_id = str(uuid4())
    user_id = str(uuid4())
    membership_id = str(uuid4())
    matter_id = str(uuid4())
    task_id = str(uuid4())
    deadline_id = str(uuid4())
    hearing_id = str(uuid4())
    calendar_sync_id = str(uuid4())
    engine = create_engine(database_url, future=True)
    with Session(engine) as session:
        company = Company(
            id=company_id,
            name="Legacy Lifecycle Firm",
            slug=f"legacy-lifecycle-{company_id[:8]}",
            company_type="law_firm",
            tenant_key=company_id,
        )
        user = User(
            id=user_id,
            email=f"legacy-lifecycle-{user_id[:8]}@example.com",
            full_name="Legacy Lifecycle Owner",
            password_hash="not-used",
        )
        matter = Matter(
            id=matter_id,
            company_id=company_id,
            title="Legacy closed matter",
            matter_code="LEGACY-CLOSED-1",
            client_name="Legacy Client",
            status="disposed",
            practice_area="litigation",
            forum_level="high_court",
            is_active=False,
            next_hearing_on=date(2099, 4, 10),
            next_hearing_source="manual",
            next_hearing_source_ref_type="matter_hearing",
            next_hearing_source_ref_id=hearing_id,
            next_hearing_manual_lock=True,
        )
        session.add_all([company, user])
        session.commit()
        membership = CompanyMembership(
            id=membership_id,
            company_id=company_id,
            user_id=user_id,
            role="owner",
        )
        session.add_all([membership, matter])
        session.commit()
        # Child rows use scalar matter_id values rather than in-memory ORM
        # relationships. Persist the valid FK parents explicitly before the
        # children so a permissive SQLite insert order cannot mask a fixture
        # that PostgreSQL would reject.
        session.add_all(
            [
                MatterTask(
                    id=task_id,
                    matter_id=matter_id,
                    title="Legacy open task",
                    status="todo",
                ),
                MatterDeadline(
                    id=deadline_id,
                    matter_id=matter_id,
                    source="manual",
                    kind="filing",
                    title="Legacy open deadline",
                    due_on=date(2099, 4, 9),
                    status="open",
                ),
                MatterHearing(
                    id=hearing_id,
                    matter_id=matter_id,
                    hearing_on=date(2099, 4, 10),
                    forum_name="Delhi High Court",
                    purpose="Legacy open hearing",
                    status="scheduled",
                ),
            ]
        )
        session.commit()
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=membership_id,
            provider="outlook",
            status="connected",
        )
        session.add(connection)
        session.commit()
        session.add(
            CalendarEventSync(
                id=calendar_sync_id,
                company_id=company_id,
                calendar_connection_id=connection.id,
                source_type="matter_hearing",
                source_id=hearing_id,
                provider_event_id="legacy-provider-event",
                sync_status="synced",
            )
        )
        session.commit()
    engine.dispose()

    get_settings.cache_clear()
    command.downgrade(config, "20260708_0001")
    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE matters SET status = 'closed', is_active = 1, "
                "next_hearing_on = '2099-04-10', next_hearing_source = 'manual', "
                "next_hearing_source_ref_type = 'matter_hearing', "
                "next_hearing_source_ref_id = :hearing_id, "
                "next_hearing_manual_lock = 1 WHERE id = :matter_id"
            ),
            {"hearing_id": hearing_id, "matter_id": matter_id},
        )
    engine.dispose()

    get_settings.cache_clear()
    command.upgrade(config, "head")
    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        matter_row = connection.execute(
            text(
                "SELECT status, is_active, next_hearing_on, next_hearing_source, "
                "next_hearing_source_ref_type, next_hearing_source_ref_id, "
                "next_hearing_manual_lock FROM matters WHERE id = :id"
            ),
            {"id": matter_id},
        ).one()
        task_row = connection.execute(
            text(
                "SELECT status, completed_at, cancelled_by_matter_disposal "
                "FROM matter_tasks WHERE id = :id"
            ),
            {"id": task_id},
        ).one()
        deadline_row = connection.execute(
            text(
                "SELECT status, completed_at, cancelled_by_matter_disposal "
                "FROM matter_deadlines WHERE id = :id"
            ),
            {"id": deadline_id},
        ).one()
        hearing_row = connection.execute(
            text(
                "SELECT status, cancelled_by_matter_disposal "
                "FROM matter_hearings WHERE id = :id"
            ),
            {"id": hearing_id},
        ).one()
        calendar_sync_row = connection.execute(
            text(
                "SELECT sync_status, next_attempt_at, dead_letter_reason "
                "FROM calendar_event_syncs WHERE id = :id"
            ),
            {"id": calendar_sync_id},
        ).one()
    engine.dispose()

    assert tuple(matter_row) == ("disposed", 0, None, "unknown", None, None, 0)
    assert task_row.status == "cancelled"
    assert task_row.completed_at is not None
    assert task_row.cancelled_by_matter_disposal == 1
    assert deadline_row.status == "cancelled"
    assert deadline_row.completed_at is not None
    assert deadline_row.cancelled_by_matter_disposal == 1
    assert tuple(hearing_row) == ("cancelled", 1)
    assert calendar_sync_row.sync_status == "delete_pending"
    assert calendar_sync_row.next_attempt_at is not None
    assert calendar_sync_row.dead_letter_reason == "matter_disposed_delete"
    get_settings.cache_clear()
    clear_engine_cache()
