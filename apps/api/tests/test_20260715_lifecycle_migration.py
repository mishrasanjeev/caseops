from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from tests.fixtures_historical_migrations import migration_config, seed_legacy_closed_matter


def test_lifecycle_migration_neutralizes_legacy_closed_children(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'legacy-lifecycle.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    engine = create_engine(database_url, future=True)
    config = migration_config(engine)
    command.upgrade(config, "20260708_0001")
    ids = seed_legacy_closed_matter(engine)
    matter_id, task_id, deadline_id, hearing_id, calendar_sync_id = (
        ids[name] for name in ("matter", "task", "deadline", "hearing", "sync")
    )
    command.upgrade(config, "20260715_0001")
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
            text("SELECT status, cancelled_by_matter_disposal FROM matter_hearings WHERE id = :id"),
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
