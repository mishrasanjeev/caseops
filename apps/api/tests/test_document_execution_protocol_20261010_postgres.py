"""Native arbitration, including unchanged pre-feature workers across DDL."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, event, inspect, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError, ProgrammingError
from sqlalchemy.orm import Load, Session, joinedload, registry, relationship, sessionmaker
from sqlalchemy.sql.selectable import CompoundSelect, Select, SelectStatementGrouping

from alembic import command
from caseops_api.core.security import hash_password
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    ContractActivity,
    DocumentProcessingJob,
    IpDocument,
    MatterActivity,
    PrivateProjectionEvent,
    User,
)
from caseops_api.services import document_jobs, document_processing, embeddings
from tests.fixtures_historical_migrations import historical_database
from tests.fixtures_postgres_client import temporary_http_database
from tests.test_document_worker_claims_20261010_postgres import _activity_source, _parsed
from tests.test_matter_writer_admission_postgres import _fixture
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres

LEGACY_SHA256 = "c4acf5992cf7e73c62702c2420a7468beb1358723dca4db4f674bc179cf0f78f"


def _wait_for_legacy_boundary(entered, future, *, timeout=10):
    if entered.wait(timeout):
        return
    if future.done():
        result = future.result()
        pytest.fail(f"Frozen worker returned before its required boundary: {result!r}")
    pytest.fail("Frozen worker did not reach its required boundary; Future remains pending.")


@pytest.mark.parametrize("outcome", ["error", "returned", "pending", "entered"])
def test_legacy_boundary_reports_early_future_outcome(outcome):
    entered, future = Event(), Future()
    if outcome == "error":
        future.set_exception(RuntimeError("actual frozen worker failure"))
        with pytest.raises(RuntimeError, match="actual frozen worker failure"):
            _wait_for_legacy_boundary(entered, future, timeout=0)
    elif outcome == "returned":
        future.set_result(None)
        with pytest.raises(pytest.fail.Exception, match="returned before.*None"):
            _wait_for_legacy_boundary(entered, future, timeout=0)
    elif outcome == "pending":
        with pytest.raises(pytest.fail.Exception, match="Future remains pending"):
            _wait_for_legacy_boundary(entered, future, timeout=0)
    else:
        entered.set()
        _wait_for_legacy_boundary(entered, future, timeout=0)


def _historical_select_descriptions(statement):
    if isinstance(statement, Select):
        return tuple(statement.column_descriptions)
    if isinstance(statement, SelectStatementGrouping):
        return _historical_select_descriptions(statement.element)
    if isinstance(statement, CompoundSelect):
        assert statement.selects, "Empty historical identity compound SELECT"
        return tuple(
            description
            for branch in statement.selects
            for description in _historical_select_descriptions(branch)
        )
    raise AssertionError(f"Unsupported historical identity SELECT: {type(statement).__name__}")


@contextmanager
def _historical_identity_columns(engine):
    columns = frozenset(column["name"] for column in inspect(engine).get_columns("users"))
    absent = tuple(
        prop.key for prop in inspect(User).column_attrs if prop.columns[0].name not in columns
    )
    assert "sessions_valid_after" not in columns
    # IP document retirement (20261101_0001) postdates this database too.
    document_columns = frozenset(
        column["name"] for column in inspect(engine).get_columns("ip_documents")
    )
    document_absent = tuple(
        prop.key
        for prop in inspect(IpDocument).column_attrs
        if prop.columns[0].name not in document_columns
    )
    assert "retired_at" in document_absent

    def historical_reads(state):
        if not state.is_select or state.session.get_bind() is not engine:
            return
        options = []
        for description in _historical_select_descriptions(state.statement):
            entity = description.get("entity")
            if entity is None or description.get("expr") is not entity:
                continue
            mapper = inspect(entity).mapper
            if mapper.class_ is IpDocument:
                loader = Load(entity)
                for key in document_absent:
                    loader = loader.defer(getattr(IpDocument, key), raiseload=True)
                options.append(loader)
                continue
            if mapper.class_ is User:
                loader, target = Load(entity), entity
            elif mapper.class_ is CompanyMembership:
                loader, target = Load(entity).defaultload(entity.user), User
            elif (
                "requested_by_membership" in mapper.relationships
                and mapper.relationships["requested_by_membership"].mapper.class_
                is CompanyMembership
            ):
                loader, target = (
                    Load(entity).defaultload(entity.requested_by_membership)
                    .defaultload(CompanyMembership.user), User,
                )
            else:
                continue
            for key in absent:
                loader = loader.defer(getattr(target, key), raiseload=True)
            options.append(loader)
        if options:
            # Entity deferral cannot be assumed to propagate across compound arms.
            assert isinstance(state.statement, Select), (
                "Historical identity entity loading requires a plain Select"
            )
            state.statement = state.statement.options(*options)

    # Freeze only this historical database's read dependency column set. An
    # unexpected new-field read raises; it must never fabricate a null cutoff.
    event.listen(Session, "do_orm_execute", historical_reads)
    try:
        yield columns
    finally:
        event.remove(Session, "do_orm_execute", historical_reads)


@pytest.fixture
def protocol_database(pg_engine, monkeypatch):
    name = "document_protocol_" + uuid4().hex
    url = pg_engine.url.set(database=name)
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    mapper = registry()
    try:
        command.upgrade(cfg, "20260928_0001")
        table = Table("document_processing_jobs", MetaData(), autoload_with=engine)
        assert "no_paid_providers" not in table.c

        class LegacyJob:
            pass

        mapper.map_imperatively(LegacyJob, table, properties={
            "requested_by_membership": relationship(CompanyMembership,
                primaryjoin=table.c.requested_by_membership_id == CompanyMembership.id,
                foreign_keys=[table.c.requested_by_membership_id]),
        })
        command.upgrade(cfg, "20261010_0002")
        with _historical_identity_columns(engine):
            yield SimpleNamespace(engine=engine, cfg=cfg, legacy_job=LegacyJob)
    finally:
        mapper.dispose()
        engine.dispose()
        get_settings.cache_clear()
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


def _legacy_module(database, clock):
    source = Path(__file__).parent / "fixtures" / "document_jobs_3dbf.py"
    git_bytes = source.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(git_bytes).hexdigest() == LEGACY_SHA256
    spec = importlib.util.spec_from_file_location("frozen_document_jobs_3dbf", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DocumentProcessingJob = database.legacy_job
    module.get_session_factory = lambda: sessionmaker(
        bind=database.engine, expire_on_commit=False, autoflush=False,
    )
    module.utcnow = lambda: clock[0]
    return module


def test_historical_identity_has_real_columns_and_rejects_new_cutoff_access(protocol_database):
    engine = protocol_database.engine
    fixture = _fixture(engine, active=False)
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "sessions_valid_after" not in columns
    statements = []

    def observed(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observed)
    try:
        with Session(engine) as session:
            member = session.scalar(select(CompanyMembership).where(
                CompanyMembership.id == fixture.actor,
            ).options(joinedload(CompanyMembership.user)))
            assert member is not None and member.is_active and member.user.is_active
            assert member.user.full_name
            assert columns <= set(inspect(member.user).dict)
            assert "sessions_valid_after" in inspect(member.user).unloaded
            assert "sessions_valid_after" not in inspect(member.user).dict
            with pytest.raises(InvalidRequestError, match="sessions_valid_after.*raiseload"):
                _ = member.user.sessions_valid_after
            assert not any("users_1.sessions_valid_after" in sql for sql in statements)
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert "sessions_valid_after" not in {
        column["name"] for column in inspect(engine).get_columns("users")
    }


def test_historical_identity_scope_leaves_other_engine_and_post_context_cutoff_real(pg_engine):
    with historical_database(pg_engine, "20261010_0002") as (engine, cfg):
        users = Table("users", MetaData(), autoload_with=engine, resolve_fks=False)
        assert "sessions_valid_after" not in users.c
        user_id, cutoff = str(uuid4()), datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(users.insert().values(
                id=user_id, email=f"{user_id}@historical.example", full_name="Historical User",
                password_hash=hash_password("HistoricalContractPass123!"),
                is_active=True, created_at=cutoff,
            ))
        unrelated = create_engine(engine.url)
        try:
            assert not inspect(User).attrs.sessions_valid_after.deferred
            with _historical_identity_columns(engine):
                with Session(engine) as session:
                    user = session.get(User, user_id)
                    assert user is not None and user.is_active
                    with pytest.raises(
                        InvalidRequestError, match="sessions_valid_after.*raiseload",
                    ):
                        _ = user.sessions_valid_after
                # A different Engine must still issue its normal modern query,
                # not inherit the historical loader or a fabricated null cutoff.
                with Session(unrelated) as session:
                    with pytest.raises(ProgrammingError) as missing:
                        session.get(User, user_id)
                    assert missing.value.orig.sqlstate == "42703"
                    assert "sessions_valid_after" in str(missing.value.orig)
                command.upgrade(cfg, "head")
                assert "sessions_valid_after" in {
                    column["name"] for column in inspect(engine).get_columns("users")
                }
                with unrelated.begin() as connection:
                    connection.execute(User.__table__.update().where(User.id == user_id).values(
                        sessions_valid_after=cutoff,
                    ))
                with Session(unrelated) as session:
                    user = session.get(User, user_id)
                    assert user.sessions_valid_after == cutoff
                    assert "sessions_valid_after" not in inspect(user).unloaded
            # Listener removal restores normal loads on the original Engine too.
            with Session(engine) as session:
                user = session.get(User, user_id)
                assert user.sessions_valid_after == cutoff
                assert "sessions_valid_after" not in inspect(user).unloaded
            assert not inspect(User).attrs.sessions_valid_after.deferred
        finally:
            unrelated.dispose()


def _snapshot(engine, fixture):
    with Session(engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        source = check.get(fixture.model, fixture.source)
        result = {
            "job": tuple(getattr(job, key) for key in (
                "status", "attempt_count", "started_at", "completed_at", "error_message",
                "processed_char_count", "no_paid_providers", "requested_by_membership_id",
            )),
            "source": tuple(getattr(source, key) for key in (
                "extracted_text", "extracted_char_count", "processed_at", "processing_status",
            )),
            "private": check.execute(select(PrivateProjectionEvent.id,
                PrivateProjectionEvent.event_type, PrivateProjectionEvent.target_id).where(
                    PrivateProjectionEvent.company_id == fixture.company,
                ).order_by(PrivateProjectionEvent.id)).all(),
        }
        if hasattr(source, "chunks"):
            result["chunks"] = [(chunk.id, chunk.content) for chunk in source.chunks]
        if fixture.model.__name__ == "MatterAttachment":
            result["vectors"] = check.execute(text(
                "SELECT id, embedding_vector::text FROM matter_attachment_chunks "
                "WHERE attachment_id=:id ORDER BY id"
            ), {"id": fixture.source}).all()
        activity = (
            ContractActivity if fixture.model.__name__ == "ContractAttachment" else MatterActivity
        )
        result["activities"] = check.execute(select(activity.id, activity.event_type,
            activity.detail).order_by(activity.id)).all()
        return result


def _assert_legacy_overlap(
    protocol_database, monkeypatch, target, old_fails, *, legacy_embedding_success=False,
):
    database = protocol_database
    fixture = _activity_source(database.engine, target)
    entered, release = Event(), Event()
    clock = [datetime.now(UTC) - timedelta(minutes=16)]
    legacy = _legacy_module(database, clock)
    current_factory = sessionmaker(bind=database.engine, expire_on_commit=False)
    monkeypatch.setattr(document_jobs, "get_session_factory", lambda: current_factory)
    monkeypatch.setattr(document_jobs, "utcnow", lambda: clock[0])
    monkeypatch.setattr(document_jobs, "embed_matter_attachment_chunks",
                        document_processing.embed_matter_attachment_chunks)
    def embed(chunks):
        if chunks == ["Rejected legacy output!!"] and not legacy_embedding_success:
            raise embeddings.EmbeddingProviderError("Local legacy lexical fallback")
        return SimpleNamespace(vectors=[[0.01] * 1024 for _ in chunks],
                               model="local-proof", dimensions=1024)

    monkeypatch.setattr(embeddings, "build_provider", lambda: SimpleNamespace(embed=embed))
    calls = []

    def parse(*_):
        calls.append("old" if not entered.is_set() else "new")
        if len(calls) == 1:
            entered.set()
            assert release.wait(30)
            if old_fails:
                raise RuntimeError("Rejected legacy parser failure")
            # Same count and shared deterministic final timestamp intentionally
            # challenge a value-only trigger's identical receipt UPDATE bypass.
            return _parsed("Rejected legacy output!!")
        return _parsed("Current protected output")

    monkeypatch.setattr(document_processing, "parse_attachment", parse)
    errors = []

    def failed(context):
        errors.append((getattr(context.original_exception, "sqlstate", None),
                       context.statement, str(context.original_exception)))

    event.listen(database.engine, "handle_error", failed)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(legacy.run_document_processing_job, fixture.job)
            try:
                _wait_for_legacy_boundary(entered, old)
                start = monotonic()
                command.upgrade(database.cfg, "20261010_0003")
                assert monotonic() - start < 10
                clock[0] = datetime.now(UTC)
                assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 1
                assert document_jobs.run_document_processing_job(fixture.job) is True
                before = _snapshot(database.engine, fixture)
                assert before["job"][0:2] == ("completed", 2), before
                assert before["job"][6] is True
                assert before["source"][0] == "Current protected output"
                if target == "matter":
                    assert before["chunks"] and before["vectors"][0][1] is not None
                release.set()
                with pytest.raises(DBAPIError) as rejected:
                    old.result(10)
                assert rejected.value.orig.sqlstate == "55000"
                assert _snapshot(database.engine, fixture) == before
                assert calls == ["old", "new"]
                assert any(state == "55000" and "document_processing_jobs" in sql
                           for state, sql, _ in errors), errors
                if target == "matter" and not old_fails and legacy_embedding_success:
                    # The actual helper flushes vectors/chunks before changing the
                    # receipt. Its stale chunk index collides first; the protocol
                    # must independently reject the fallback receipt overwrite.
                    assert any(state == "23505" and "uq_matter_attachment_chunk_index" in detail
                               for state, _, detail in errors), errors
                    assert sum(state == "55000" for state, _, _ in errors) == 1, errors
                else:
                    assert sum(state == "55000" for state, _, _ in errors) >= (
                        1 if old_fails else 2
                    ), errors
            finally:
                release.set()
    finally:
        event.remove(database.engine, "handle_error", failed)


@pytest.mark.parametrize("target", ["matter", "contract", "ip-targetless"])
@pytest.mark.parametrize("old_fails", [False, True])
def test_actual_3db_worker_cannot_clobber_reclaimed_result_after_trigger_install(
    protocol_database, monkeypatch, target, old_fails,
):
    _assert_legacy_overlap(protocol_database, monkeypatch, target, old_fails)


def test_actual_3db_vector_flush_collision_cannot_clobber_fallback_receipt(
    protocol_database, monkeypatch,
):
    _assert_legacy_overlap(protocol_database, monkeypatch, "matter", False,
                           legacy_embedding_success=True)


@pytest.mark.parametrize("target", ["matter", "contract", "ip-targetless"])
@pytest.mark.parametrize("status", ["queued", "failed"])
def test_actual_legacy_claim_is_rejected_before_parser_or_provider(
    protocol_database, monkeypatch, target, status,
):
    database = protocol_database
    fixture = _activity_source(database.engine, target)
    # Establish the pre-trigger legacy FAILED fixture, not a bypass at head.
    with database.engine.begin() as seed:
        seed.execute(text("UPDATE document_processing_jobs SET status=:status WHERE id=:id"),
                     {"status": status, "id": fixture.job})
    command.upgrade(database.cfg, "20261010_0003")
    legacy = _legacy_module(database, [datetime.now(UTC)])

    def forbidden(*_a, **_kw):
        pytest.fail("A rejected legacy claim must not admit parser/provider I/O")

    monkeypatch.setattr(document_processing, "parse_attachment", forbidden)
    legacy.embed_matter_attachment_chunks = forbidden
    before = _snapshot(database.engine, fixture)
    with pytest.raises(DBAPIError) as rejected:
        legacy.run_document_processing_job(fixture.job)
    assert rejected.value.orig.sqlstate == "55000"
    assert _snapshot(database.engine, fixture) == before


@pytest.mark.parametrize("payload", [
    None, "", "null", "[]", "{}", "not json", '{"id":null}',
    '{"id":"wrong","attempt_count":1,"started_at":null}',
    '{"id":"JOB","attempt_count":null,"started_at":null}',
    '{"id":"JOB","attempt_count":1}',
    '{"id":"JOB","attempt_count":1,"started_at":false}',
    '{"id":"JOB","attempt_count":1,"started_at":"invalid"}',
])
def test_malformed_or_missing_context_rejects_claim_without_null_bypass(pg_engine, payload):
    fixture = _fixture(pg_engine, active=False)
    with pg_engine.connect() as connection:
        if payload is not None:
            connection.execute(text(
                "SELECT set_config('caseops.document_job_attempt', :value, true)"
            ), {"value": payload.replace("JOB", fixture.job)})
        with pytest.raises(DBAPIError) as rejected:
            connection.execute(text("UPDATE document_processing_jobs SET status='processing', "
                "attempt_count=1, started_at=clock_timestamp() WHERE id=:id"), {"id": fixture.job})
        assert rejected.value.orig.sqlstate == "55000"
        connection.rollback()
    with Session(pg_engine) as check:
        assert check.get(DocumentProcessingJob, fixture.job).status == "queued"
        check.delete(check.get(DocumentProcessingJob, fixture.job))
        check.commit()


@pytest.mark.parametrize("finish", ["commit", "rollback", "savepoint"])
def test_transaction_local_identity_resets_on_native_pooled_connection(pg_engine, finish):
    pooled = create_engine(pg_engine.url, pool_size=1, max_overflow=0)
    try:
        with pooled.connect() as connection:
            pid = connection.scalar(text("SELECT pg_backend_pid()"))
            nested = connection.begin_nested() if finish == "savepoint" else None
            connection.execute(text(
                "SELECT set_config('caseops.document_job_attempt', :value, true)"
            ), {"value": '{"id":"owned-attempt"}'})
            if nested is not None:
                nested.rollback()
                assert not connection.scalar(text(
                    "SELECT current_setting('caseops.document_job_attempt', true)"))
                connection.commit()
            else:
                getattr(connection, finish)()
        with pooled.connect() as connection:
            assert connection.scalar(text("SELECT pg_backend_pid()")) == pid
            assert not connection.scalar(text(
                "SELECT current_setting('caseops.document_job_attempt', true)"))
    finally:
        pooled.dispose()


@pytest.mark.parametrize("field,value", [
    ("id", "other"), ("queued_at", datetime(2026, 1, 1, tzinfo=UTC)),
    ("company_id", "other"), ("attachment_id", "other"), ("target_type", "contract_attachment"),
    ("action", "reindex"), ("no_paid_providers", False), ("requested_by_membership_id", "other"),
])
def test_execution_provenance_cannot_change_even_without_status_change(pg_engine, field, value):
    fixture = _fixture(pg_engine, active=False)
    with pg_engine.connect() as connection:
        with pytest.raises(DBAPIError) as rejected:
            connection.execute(text(f"UPDATE document_processing_jobs SET {field}=:value "
                                    "WHERE id=:id"), {"id": fixture.job, "value": value})
        assert rejected.value.orig.sqlstate == "55000"
        connection.rollback()
    with Session(pg_engine) as check:
        check.delete(check.get(DocumentProcessingJob, fixture.job))
        check.commit()


def test_requester_fk_set_null_retains_legacy_receipt_and_marker(pg_engine):
    fixture = _fixture(pg_engine, active=False)
    # Uploader is retained independently, so remove only the historical job actor.
    with Session(pg_engine) as seed:
        from tests.test_postgres_validation import _seed_membership

        actor = _seed_membership(seed, fixture.company, role="admin")
        source = seed.get(DocumentProcessingJob, fixture.job)
        seed.delete(source)
        seed.flush()
        job = DocumentProcessingJob(company_id=fixture.company,
            requested_by_membership_id=actor, target_type="matter_attachment",
            attachment_id=fixture.attachment, action="initial_index")
        seed.add(job)
        seed.commit()
        job_id = job.id
        # Execute native DELETE so the database's FK SET NULL, rather than an
        # ORM relationship cascade, exercises the provenance trigger.
        seed.execute(text("DELETE FROM company_memberships WHERE id=:id"), {"id": actor})
        seed.commit()
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, job_id)
        assert job.requested_by_membership_id is None
        assert (job.status, job.attempt_count, job.no_paid_providers) == ("queued", 0, True)
        check.delete(job)
        check.commit()


def test_independent_trigger_upgrade_retained_downgrade_preserves_catalog_and_receipts(
    protocol_database,
):
    database = protocol_database
    fixtures = []
    for status in ("queued", "processing", "completed", "failed"):
        for no_paid in (False, True):
            fixture = _activity_source(database.engine, "matter")
            with Session(database.engine) as seed:
                receipt = seed.get(DocumentProcessingJob, fixture.job)
                receipt.status, receipt.no_paid_providers = status, no_paid
                receipt.attempt_count = 0 if status == "queued" else 1
                receipt.started_at = None if status == "queued" else datetime.now(UTC)
                receipt.completed_at = (
                    datetime.now(UTC) if status in ("completed", "failed") else None
                )
                seed.commit()
            fixtures.append(fixture)
    before = [_snapshot(database.engine, fixture) for fixture in fixtures]
    with database.engine.connect() as check:
        indexes = check.execute(text("SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename='document_processing_jobs' ORDER BY indexname")).all()
    command.upgrade(database.cfg, "20261010_0003")
    command.upgrade(database.cfg, "20261010_0003")
    with database.engine.connect() as check:
        assert check.scalar(text("SELECT count(*) FROM pg_trigger WHERE "
            "tgrelid='document_processing_jobs'::regclass AND NOT tgisinternal "
            "AND tgname='document_execution_protocol'")) == 1
        assert check.scalar(text("SELECT count(*) FROM pg_trigger WHERE "
            "tgrelid='document_processing_jobs'::regclass AND NOT tgisinternal "
            "AND tgname='document_execution_provenance'")) == 1
        assert check.scalar(text("SELECT count(*) FROM pg_proc WHERE "
                                 "proname='caseops_document_execution_protocol'")) == 1
        assert check.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE "
            "tablename='document_processing_jobs' ORDER BY indexname")).all() == indexes
    assert [_snapshot(database.engine, fixture) for fixture in fixtures] == before
    for opt_in in (None, "document_execution_fresh_downgrade=false",
                   "document_execution_fresh_downgrade=true"):
        database.cfg.cmd_opts = SimpleNamespace(x=[] if opt_in is None else [opt_in])
        with pytest.raises(RuntimeError, match="Document execution protocol.*restore-forward"):
            command.downgrade(database.cfg, "20261010_0002")
        assert [_snapshot(database.engine, fixture) for fixture in fixtures] == before
        with database.engine.connect() as check:
            assert check.scalar(text("SELECT version_num FROM alembic_version")) == "20261010_0003"
            assert check.scalar(text("SELECT count(*) FROM pg_trigger WHERE "
                "tgrelid='document_processing_jobs'::regclass AND NOT tgisinternal "
                "AND tgname IN ('document_execution_protocol', 'document_execution_provenance')"
            )) == 2
            assert check.scalar(text(
                "SELECT to_regprocedure('caseops_document_execution_protocol()')"
            )) is not None
            assert check.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE "
                "tablename='document_processing_jobs' ORDER BY indexname")).all() == indexes
        with database.engine.connect() as old:
            with pytest.raises(DBAPIError) as rejected:
                old.execute(text("UPDATE document_processing_jobs SET status='processing', "
                    "attempt_count=1,started_at=clock_timestamp() WHERE id=:id"
                ), {"id": fixtures[0].job})
            assert rejected.value.orig.sqlstate == "55000"
            old.rollback()
    database.cfg.cmd_opts = SimpleNamespace(x=[])
    command.upgrade(database.cfg, "head")
    assert [_snapshot(database.engine, fixture) for fixture in fixtures] == before


def test_document_protocol_rehearsal_refuses_a_retained_legacy_compliance_root(protocol_database):
    database = protocol_database
    fixture = _activity_source(database.engine, "matter")
    root = Table("matter_compliance_extraction_runs", MetaData(), autoload_with=database.engine)
    assert "persistence_protocol" not in root.c
    with database.engine.begin() as seed:
        matter_id = seed.scalar(select(fixture.model.matter_id).where(
            fixture.model.id == fixture.source,
        ))
        assert matter_id is not None
        seed.execute(root.insert().values(id=str(uuid4()), company_id=fixture.company,
            matter_id=matter_id, attachment_id=fixture.source, source_type="attachment",
            trigger="manual", parser_version="legacy-fixture", status="failed",
            created_by_membership_id=fixture.actor, created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC)))
        seed.execute(text("DELETE FROM document_processing_jobs WHERE id=:id"), {"id": fixture.job})
        assert seed.scalar(text("SELECT count(*) FROM document_processing_jobs")) == 0
        before = [dict(row) for row in seed.execute(select(root)).mappings()]
        assert len(before) == 1
    command.upgrade(database.cfg, "20261010_0003")
    database.cfg.cmd_opts = SimpleNamespace(x=["document_execution_fresh_downgrade=true"])
    with pytest.raises(RuntimeError, match="Document execution protocol.*restore-forward"):
        command.downgrade(database.cfg, "20261010_0002")
    with database.engine.connect() as check:
        assert [dict(row) for row in check.execute(select(root)).mappings()] == before
        assert check.scalar(text("SELECT version_num FROM alembic_version")) == "20261010_0003"
        assert check.scalar(text("SELECT count(*) FROM pg_trigger WHERE "
            "tgrelid='document_processing_jobs'::regclass AND NOT tgisinternal "
            "AND tgname IN ('document_execution_protocol', 'document_execution_provenance')")) == 2


def test_independent_empty_document_protocol_rehearsal_requires_explicit_opt_in(protocol_database):
    database = protocol_database
    with database.engine.connect() as check:
        assert check.scalar(text("SELECT count(*) FROM document_processing_jobs")) == 0
        assert check.scalar(text("SELECT count(*) FROM matter_compliance_extraction_runs")) == 0
        indexes = check.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE "
            "tablename='document_processing_jobs' ORDER BY indexname")).all()
        columns = check.execute(text("SELECT column_name,data_type,is_nullable,column_default "
            "FROM information_schema.columns WHERE table_name='document_processing_jobs' "
            "ORDER BY ordinal_position")).all()
    command.upgrade(database.cfg, "20261010_0003")
    with pytest.raises(RuntimeError, match="Document execution protocol.*restore-forward"):
        command.downgrade(database.cfg, "20261010_0002")
    database.cfg.cmd_opts = SimpleNamespace(x=["document_execution_fresh_downgrade=true"])
    command.downgrade(database.cfg, "20261010_0002")
    with database.engine.connect() as check:
        assert check.scalar(text(
            "SELECT to_regprocedure('caseops_document_execution_protocol()')"
        )) is None
        assert check.scalar(text("SELECT count(*) FROM pg_trigger WHERE "
            "tgrelid='document_processing_jobs'::regclass AND NOT tgisinternal "
            "AND tgname IN ('document_execution_protocol', 'document_execution_provenance')")) == 0
        assert check.scalar(text("SELECT version_num FROM alembic_version")) == "20261010_0002"
        assert check.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE "
            "tablename='document_processing_jobs' ORDER BY indexname")).all() == indexes
        assert check.execute(text("SELECT column_name,data_type,is_nullable,column_default "
            "FROM information_schema.columns WHERE table_name='document_processing_jobs' "
            "ORDER BY ordinal_position")).all() == columns
        assert check.scalar(text("SELECT count(*) FROM document_processing_jobs")) == 0
        assert check.scalar(text("SELECT count(*) FROM matter_compliance_extraction_runs")) == 0
    command.upgrade(database.cfg, "20261010_0003")
    command.upgrade(database.cfg, "20261010_0003")
    with database.engine.connect() as check:
        assert check.scalar(text("SELECT count(*) FROM pg_trigger WHERE "
            "tgrelid='document_processing_jobs'::regclass AND NOT tgisinternal "
            "AND tgname IN ('document_execution_protocol', 'document_execution_provenance')")) == 2


@pytest.mark.parametrize("age,limit", [(1, 5), (14, 5), (15, 6), (15, 0)])
def test_invalid_recovery_contract_rejects_before_session_creation(monkeypatch, age, limit):
    def forbidden():
        pytest.fail("Invalid recovery policy must fail before creating a SQL session")

    monkeypatch.setattr(document_jobs, "get_session_factory", forbidden)
    with pytest.raises(ValueError):
        document_jobs.recover_stale_document_processing_jobs(stale_after_minutes=age, limit=limit)


@pytest.mark.parametrize("status", ["queued", "processing"])
def test_attempt_bound_disposal_cancellation_has_no_message_only_exemption(pg_engine, status):
    fixture = _fixture(pg_engine, active=False)
    with Session(pg_engine) as seed:
        from tests.fixtures_document_jobs import (
            legacy_document_processing_receipt as _legacy_receipt_fixture,
        )

        _legacy_receipt_fixture(seed, fixture.job, status=status, attempt_count=1,
                                started_at=datetime.now(UTC) - timedelta(days=154)
                                if status == "processing" else None)
        seed.commit()
    with pg_engine.connect() as old:
        with pytest.raises(DBAPIError) as rejected:
            old.execute(text("UPDATE document_processing_jobs SET status='failed', "
                "error_message='Cancelled because the matter was disposed.', "
                "completed_at=clock_timestamp() WHERE id=:id"), {"id": fixture.job})
        assert rejected.value.orig.sqlstate == "55000"
        old.rollback()
    with Session(pg_engine) as disposer:
        job = disposer.get(DocumentProcessingJob, fixture.job)
        assert document_jobs.cancel_document_processing_job_for_disposal(
            disposer, job, completed_at=datetime.now(UTC),
        ) is True
        disposer.commit()
        assert document_jobs.cancel_document_processing_job_for_disposal(
            disposer, job, completed_at=datetime.now(UTC),
        ) is False
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        assert (job.status, job.attempt_count, job.processed_char_count, job.no_paid_providers) == (
            "failed", 1, 0, True,
        )
        check.delete(job)
        check.commit()


def test_http_template_clones_preserve_execution_trigger_function_and_rejection(
    pg_engine, migrated_http_template,
):
    signatures = []
    for _ in range(2):
        with temporary_http_database(pg_engine.url, template=migrated_http_template) as clone:
            with clone.connect() as check:
                signatures.append((
                    check.scalar(text("SELECT version_num FROM alembic_version")),
                    check.execute(text("SELECT tgname,pg_get_triggerdef(oid) FROM pg_trigger "
                        "WHERE tgrelid='document_processing_jobs'::regclass AND NOT tgisinternal "
                        "ORDER BY tgname")).all(),
                    check.scalar(text("SELECT pg_get_functiondef("
                        "'caseops_document_execution_protocol()'::regprocedure)")),
                ))
            assert len(signatures[-1][1]) == 2
            fixture = _fixture(clone, active=False)
            with clone.connect() as old:
                with pytest.raises(DBAPIError) as rejected:
                    old.execute(text("UPDATE document_processing_jobs SET status='processing' "
                                     "WHERE id=:id"), {"id": fixture.job})
                assert rejected.value.orig.sqlstate == "55000"
                old.rollback()
    assert signatures[0] == signatures[1]


@pytest.mark.parametrize("mismatch", ["id", "attempt_count", "started_at", "null_start"])
def test_same_status_progress_cannot_adopt_other_attempt_tuple(pg_engine, mismatch):
    fixture = _fixture(pg_engine, active=False)
    with Session(pg_engine) as claimant:
        assert document_jobs._claim_job(claimant, fixture.job) is not None
        attempt = claimant.info["document_job_attempt"]
    payload = {"id": attempt.id, "attempt_count": attempt.number,
               "started_at": attempt.started_at.isoformat()}
    payload[mismatch if mismatch != "null_start" else "started_at"] = {
        "id": str(uuid4()), "attempt_count": attempt.number - 1,
        "started_at": (attempt.started_at - timedelta(seconds=1)).isoformat(),
        "null_start": None,
    }[mismatch]
    with pg_engine.connect() as old:
        old.execute(text("SELECT set_config('caseops.document_job_attempt', :value, true)"),
                    {"value": json.dumps(payload)})
        with pytest.raises(DBAPIError) as rejected:
            old.execute(text("UPDATE document_processing_jobs SET error_message='stale progress' "
                             "WHERE id=:id"), {"id": fixture.job})
        assert rejected.value.orig.sqlstate == "55000"
        old.rollback()
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        assert job.status == "processing" and job.error_message is None
        check.delete(job)
        check.commit()


def test_row_local_claim_trigger_does_not_query_or_lock_company(pg_engine):
    fixture = _fixture(pg_engine, active=False)
    with Session(pg_engine) as holder:
        holder.scalar(select(Company).where(Company.id == fixture.company).with_for_update())
        with Session(pg_engine) as claimant:
            claimant.execute(text("SET LOCAL lock_timeout='1s'"))
            assert document_jobs._claim_job(claimant, fixture.job) is not None
        holder.rollback()
    with Session(pg_engine) as cleanup:
        cleanup.delete(cleanup.get(DocumentProcessingJob, fixture.job))
        cleanup.commit()


def test_identical_terminal_execution_update_still_requires_attempt_context(pg_engine):
    fixture = _fixture(pg_engine, active=False)
    with Session(pg_engine) as worker:
        job = document_jobs._claim_job(worker, fixture.job)
        document_jobs._mark_job_failed(worker, job, error_message="Deterministic terminal refusal")
    with pg_engine.connect() as old:
        with pytest.raises(DBAPIError) as rejected:
            old.execute(text("UPDATE document_processing_jobs SET status=status, "
                "attempt_count=attempt_count, started_at=started_at, completed_at=completed_at, "
                "processed_char_count=processed_char_count, error_message=error_message "
                "WHERE id=:id"), {"id": fixture.job})
        assert rejected.value.orig.sqlstate == "55000"
        old.rollback()
    with Session(pg_engine) as cleanup:
        job = cleanup.get(DocumentProcessingJob, fixture.job)
        assert (job.status, job.attempt_count, job.error_message) == (
            "failed", 1, "Deterministic terminal refusal",
        )
        cleanup.delete(job)
        cleanup.commit()


def test_stale_recovery_installs_identity_per_individual_flush_at_most_five(pg_engine, monkeypatch):
    fixtures = [_fixture(pg_engine, active=False) for _ in range(6)]
    with Session(pg_engine) as seed:
        from tests.fixtures_document_jobs import (
            legacy_document_processing_receipt as _legacy_receipt_fixture,
        )

        for fixture in fixtures:
            _legacy_receipt_fixture(seed, fixture.job, status="processing", attempt_count=1,
                                    started_at=datetime.now(UTC) - timedelta(minutes=16))
        seed.commit()
    monkeypatch.setattr(document_jobs, "get_session_factory",
                        lambda: sessionmaker(bind=pg_engine, expire_on_commit=False))
    operations = []

    def record(_conn, _cursor, sql, parameters, _context, many):
        if "set_config('caseops.document_job_attempt'" in sql or sql.startswith(
            "UPDATE document_processing_jobs "
        ):
            operations.append((sql, parameters, many))

    event.listen(pg_engine, "before_cursor_execute", record)
    try:
        assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 5
    finally:
        event.remove(pg_engine, "before_cursor_execute", record)
    assert len(operations) == 10
    for context, update in zip(operations[::2], operations[1::2], strict=True):
        assert "set_config" in context[0]
        assert update[0].startswith("UPDATE document_processing_jobs ")
        assert update[2] is False
        identity = json.loads(context[1]["identity"])
        assert identity["id"] in {fixture.job for fixture in fixtures}
        assert identity["attempt_count"] == 1
        assert identity["started_at"] is not None
    with Session(pg_engine) as cleanup:
        statuses = [cleanup.get(DocumentProcessingJob, fixture.job).status for fixture in fixtures]
        assert statuses.count("queued") == 5 and statuses.count("processing") == 1
        for fixture in fixtures:
            cleanup.delete(cleanup.get(DocumentProcessingJob, fixture.job))
        cleanup.commit()


def test_completed_compliance_error_annotation_reinstalls_attempt_after_rollback(
    pg_engine, monkeypatch,
):
    fixture = _fixture(pg_engine, active=False)
    from caseops_api.db.models import MatterAttachment
    from caseops_api.services import compliance_extraction

    with Session(pg_engine) as seed:
        seed.get(MatterAttachment, fixture.attachment).document_type = "order_judgment"
        seed.commit()
    monkeypatch.setattr(document_jobs, "get_session_factory",
                        lambda: sessionmaker(bind=pg_engine, expire_on_commit=False))
    monkeypatch.setattr(document_processing, "parse_attachment", lambda *_: _parsed())
    monkeypatch.setattr(document_jobs, "embed_matter_attachment_chunks", lambda *_a, **_kw: 0)

    def failed(session, **_):
        assert not session.in_transaction()
        session.execute(text("SELECT 1"))
        raise RuntimeError("Local deterministic compliance failure")

    monkeypatch.setattr(compliance_extraction, "run_compliance_extraction_for_attachment", failed)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    with Session(pg_engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        assert (job.status, job.attempt_count) == ("completed", 1)
        assert job.error_message == (
            "Compliance extraction failed: Local deterministic compliance failure"
        )
        assert check.get(MatterAttachment, fixture.attachment).extracted_text == "Prepared content"
