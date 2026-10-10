"""First-rollout counterproof: an old court executor ignores the new claim fence."""

import ast
import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import FunctionType, SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.orm import Session, joinedload, registry, relationship, sessionmaker

from alembic import command
from caseops_api.core.redaction import redact_provider_error
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterCourtSyncJob,
    MatterCourtSyncJobStatus,
    utcnow,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import court_sync_jobs
from caseops_api.services.court_sync_jobs import _matter_is_disposed
from caseops_api.services.court_sync_sources import get_court_sync_adapter
from caseops_api.services.matters import _persist_court_sync_import
from caseops_api.workers import court_sync
from tests.test_court_sync_execution_20261010_postgres import _result
from tests.test_document_finalizer_overlap_20261009_postgres import (
    finalizer_audit as _finalizer_audit_fixture,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_company,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
finalizer_audit = _finalizer_audit_fixture


# Exact body from 3dbf364d9834316d181d4a52b2e9b4c7bee431b4, rebound to its old mapper.
def _legacy_run(job_id: str) -> None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job = session.scalar(
            select(MatterCourtSyncJob)
            .options(
                joinedload(MatterCourtSyncJob.requested_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(MatterCourtSyncJob.id == job_id)
        )
        if not job or job.status not in {
            MatterCourtSyncJobStatus.QUEUED,
            MatterCourtSyncJobStatus.FAILED,
        }:
            return

        matter = session.scalar(select(Matter).where(Matter.id == job.matter_id))
        if matter is None:
            job.status = MatterCourtSyncJobStatus.FAILED
            job.error_message = "Matter not found for court sync job."
            job.completed_at = utcnow()
            session.add(job)
            session.commit()
            return
        if _matter_is_disposed(matter):
            job.status = MatterCourtSyncJobStatus.FAILED
            job.error_message = "Cancelled because the matter was disposed."
            job.completed_at = utcnow()
            session.add(job)
            session.commit()
            return

        job.status = MatterCourtSyncJobStatus.PROCESSING
        job.started_at = utcnow()
        job.completed_at = None
        job.error_message = None
        session.add(job)
        session.commit()

        try:
            adapter = get_court_sync_adapter(job.source)
            result = adapter.fetch(matter=matter, source_reference=job.source_reference)
            from caseops_api.services.compliance_participants import lock_compliance_participants

            lock_compliance_participants(
                session,
                company_id=matter.company_id,
                matter_id=job.matter_id,
                actor_membership_id=job.requested_by_membership_id,
                expected_lifecycle_version=matter.lifecycle_version,
            )
            matter = session.scalar(
                select(Matter)
                .where(Matter.id == job.matter_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if matter is None:
                raise ValueError("Matter not found for court sync job.")
            if _matter_is_disposed(matter):
                raise ValueError("Court sync cancelled because the matter was disposed.")
            sync_run = _persist_court_sync_import(
                session,
                matter=matter,
                actor_membership_id=job.requested_by_membership_id,
                source=job.source,
                summary=result.summary,
                cause_list_entries=result.cause_list_entries,
                orders=result.orders,
            )
            job.adapter_name = result.adapter_name
            job.sync_run_id = sync_run.id
            job.imported_cause_list_count = len(result.cause_list_entries)
            job.imported_order_count = len(result.orders)
            job.status = MatterCourtSyncJobStatus.COMPLETED
            job.completed_at = utcnow()
            session.add(job)
            session.commit()
        except Exception as exc:
            session.rollback()
            failed_job = session.scalar(
                select(MatterCourtSyncJob).where(MatterCourtSyncJob.id == job_id)
            )
            if failed_job is not None:
                failed_job.status = MatterCourtSyncJobStatus.FAILED
                failed_job.error_message = redact_provider_error(exc)
                failed_job.completed_at = utcnow()
                session.add(failed_job)
                session.commit()
    finally:
        session.close()


def _body_hash(function):
    node = ast.parse(inspect.getsource(function)).body[0]
    return hashlib.sha256(
        ast.dump(
            ast.Module(body=node.body, type_ignores=[]),
            include_attributes=False,
        ).encode()
    ).hexdigest()


@pytest.mark.parametrize("quiesce", [False, True])
def test_native_first_court_rollout_requires_legacy_executor_quiescence(
    finalizer_audit,
    monkeypatch,
    quiesce,
):
    audit = finalizer_audit
    assert _body_hash(_legacy_run) == (
        "952b61b6b5664f690431a81beb57b8c4c1ee873d90935979c6032684f698644e"
    )
    database = "court_rolling_" + uuid4().hex
    parent_engine, parent_factory = audit.engine, audit.factory
    with parent_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text(f'CREATE DATABASE "{database}"'))
    engine = create_engine(parent_engine.url.set(database=database))
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "alembic"))
    monkeypatch.setenv("CASEOPS_DATABASE_URL", engine.url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    legacy_registry = registry()
    entered, release = Event(), Event()
    try:
        command.upgrade(config, "20261010_0001")
        with Session(engine) as session:
            company = _seed_company(session)
            actor = _seed_membership(session, company, role="admin")
            matter = _seed_matter(session, company)
            job_id = str(uuid4())
            session.execute(
                text(
                    "INSERT INTO matter_court_sync_jobs "
                    "(id, company_id, matter_id, requested_by_membership_id, source, status, "
                    "imported_cause_list_count, imported_order_count, queued_at, updated_at) "
                    "VALUES (:id, :company, :matter, :actor, 'local-emulator', 'queued', "
                    "0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": job_id, "company": company, "matter": matter, "actor": actor},
            )
            session.commit()
        table = Table("matter_court_sync_jobs", MetaData(), autoload_with=engine)
        assert "no_paid_providers" not in table.c

        class LegacyJob:
            pass

        legacy_registry.map_imperatively(
            LegacyJob,
            table,
            properties={
                "requested_by_membership": relationship(
                    CompanyMembership,
                    primaryjoin=table.c.requested_by_membership_id == CompanyMembership.id,
                    foreign_keys=[table.c.requested_by_membership_id],
                ),
            },
        )
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        audit.engine, audit.factory = engine, factory
        for name, callback in audit.hooks:
            from sqlalchemy import event

            event.listen(engine, name, callback)

        def old_fetch(**_):
            entered.set()
            assert release.wait(15), "Old court executor not released"
            raise RuntimeError("Pinned legacy failure after replacement")

        old = FunctionType(
            _legacy_run.__code__,
            globals()
            | {
                "MatterCourtSyncJob": LegacyJob,
                "get_session_factory": lambda: lambda: audit.session("worker"),
                "get_court_sync_adapter": lambda _: SimpleNamespace(fetch=old_fetch),
            },
        )
        with audit.pool() as (pool, futures):
            future = pool.submit(old, job_id)
            futures.append(future)
            try:
                assert entered.wait(5)
                command.upgrade(config, "head")
                with Session(engine) as session:
                    job = session.get(MatterCourtSyncJob, job_id)
                    assert job.status == "processing" and job.no_paid_providers is True
                settings = SimpleNamespace(
                    court_sync_worker_admission_protocol_version=1,
                    court_sync_worker_admission_enabled=False,
                    court_sync_worker_batch_size=1,
                    court_sync_stale_after_minutes=15,
                )
                monkeypatch.setattr(court_sync, "get_settings", lambda: settings)
                monkeypatch.setattr(
                    court_sync_jobs,
                    "get_session_factory",
                    lambda: pytest.fail("disabled court SQL"),
                )
                assert court_sync.main(["--once", "--skip-migrations"]) == 0
                audit.record(
                    "court_rolling_disabled_new_executor",
                    old_still_running=True,
                    old_mapper_columns=list(table.c.keys()),
                    database=database,
                )
                if quiesce:
                    release.set()
                    future.result(timeout=5)
                clock = datetime.now(UTC) + timedelta(minutes=30)
                monkeypatch.setattr(court_sync_jobs, "utcnow", lambda: clock)
                monkeypatch.setattr(
                    court_sync_jobs,
                    "get_session_factory",
                    lambda: lambda: audit.session("mutation"),
                )
                monkeypatch.setattr(
                    court_sync_jobs,
                    "get_court_sync_adapter",
                    lambda _: SimpleNamespace(fetch=lambda **_: _result("New owner")),
                )
                recovered = court_sync_jobs.recover_stale_matter_court_sync_jobs(
                    stale_after_minutes=15,
                    limit=1,
                )
                assert recovered == (0 if quiesce else 1)
                assert court_sync_jobs.run_matter_court_sync_job(job_id) is True
                with Session(engine) as session:
                    job = session.get(MatterCourtSyncJob, job_id)
                    assert job.status == "completed" and job.sync_run_id is not None
                    retained_run = job.sync_run_id
                release.set()
                future.result(timeout=5)
                with Session(engine) as session:
                    job = session.get(MatterCourtSyncJob, job_id)
                    expected = "completed" if quiesce else "failed"
                    assert job.status == expected and job.sync_run_id == retained_run
                    assert job.requested_by_membership_id == actor
                    assert job.no_paid_providers is True
                    audit.record(
                        "court_rolling_winner",
                        quiesced=quiesce,
                        retained_run=retained_run,
                        status=job.status,
                        legacy_overwrite=not quiesce,
                        activity=audit.snapshot(),
                    )
            finally:
                release.set()
    finally:
        release.set()
        legacy_registry.dispose()
        audit.engine, audit.factory = parent_engine, parent_factory
        engine.dispose()
        with parent_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            assert not admin.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}
            )
        audit.record("court_rolling_database_dropped", database=database)
