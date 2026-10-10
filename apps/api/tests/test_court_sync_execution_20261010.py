"""Court dispatch admission never releases caller-owned writes."""

from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import Integer, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from caseops_api.services import court_sync_jobs


class _Base(DeclarativeBase):
    pass


class _PendingWrite(_Base):
    __tablename__ = "court_dispatch_write"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


@pytest.mark.parametrize("env, tasks_count", [("local", 1), ("cloud", 0), ("unknown", 0)])
def test_court_dispatch_releases_read_only_admission_without_production_background_work(
    monkeypatch,
    env,
    tasks_count,
):
    monkeypatch.setattr(court_sync_jobs, "get_settings", lambda: SimpleNamespace(env=env))
    with Session(create_engine("sqlite://")) as session:
        session.execute(text("SELECT 1"))
        tasks = BackgroundTasks()
        court_sync_jobs.dispatch_matter_court_sync_job(
            session=session,
            background_tasks=tasks,
            job_id="already-durable",
        )
        assert not session.in_transaction()
        assert len(tasks.tasks) == tasks_count
        if tasks_count:
            assert tasks.tasks[0].func is court_sync_jobs.run_matter_court_sync_job
            assert tasks.tasks[0].args == ("already-durable",)


@pytest.mark.parametrize("writes", ["pending", "flushed", "savepoint", "external"])
def test_court_dispatch_preserves_uncommitted_caller_work_and_never_adds_task(writes):
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with engine.connect() as connection:
        external = connection.begin() if writes == "external" else None
        with Session(connection if external else engine) as session:
            session.add(_PendingWrite(id=1))
            if writes == "flushed":
                session.flush()
                assert not session.new and not session.dirty
            if writes == "savepoint":
                session.begin_nested()
            tasks = BackgroundTasks()
            with pytest.raises(HTTPException) as failure:
                court_sync_jobs.dispatch_matter_court_sync_job(
                    session=session,
                    background_tasks=tasks,
                    job_id="not-durable",
                )
            assert failure.value.status_code == 409
            assert not tasks.tasks
            assert session.in_transaction()
            if writes == "flushed":
                assert session.get(_PendingWrite, 1) is not None
            elif writes == "pending":
                assert session.new
        if external:
            assert connection.in_transaction()
            external.rollback()


@pytest.mark.parametrize("limit", [0, -1, 26, True])
def test_court_drain_and_recovery_reject_unbounded_selection_before_database(limit, monkeypatch):
    monkeypatch.setattr(
        court_sync_jobs,
        "get_session_factory",
        lambda: pytest.fail("database before bound"),
    )
    with pytest.raises(ValueError):
        court_sync_jobs.drain_matter_court_sync_jobs(limit=limit)
    with pytest.raises(ValueError):
        court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=15, limit=limit)


@pytest.mark.parametrize("age", [0, -1, 1441, True])
def test_court_recovery_rejects_invalid_age_before_database(age, monkeypatch):
    monkeypatch.setattr(
        court_sync_jobs,
        "get_session_factory",
        lambda: pytest.fail("database before age"),
    )
    with pytest.raises(ValueError):
        court_sync_jobs.recover_stale_matter_court_sync_jobs(stale_after_minutes=age)
