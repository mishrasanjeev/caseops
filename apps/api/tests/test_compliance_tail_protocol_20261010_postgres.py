"""Frozen 3dbf tails across native DDL; current manual, worker and court controls."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import ColumnDefault, MetaData, Table, create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, registry, sessionmaker

from alembic import command
from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    DocumentProcessingJob,
    Matter,
    MatterAttachment,
    MatterComplianceExtractionRun,
    MatterComplianceItem,
    MatterCourtOrder,
    ModelRun,
    utcnow,
)
from caseops_api.schemas.matters import MatterCourtOrderSyncItem, MatterCourtSyncImportRequest
from caseops_api.services import (
    compliance_extraction,
    compliance_participants,
    court_sync_jobs,
    document_jobs,
    document_processing,
    matters,
)
from caseops_api.services.compliance_tail_protocol import (
    COMPLIANCE_TAIL_PROTOCOL,
    admit_compliance_run,
    bind_compliance_run_context,
)
from caseops_api.services.llm import LLMCompletion, LLMProviderError
from tests.test_compliance_participant_fence_20261010_postgres import _mutate, _seed, _UploadPhase
from tests.test_document_execution_protocol_20261010_postgres import (
    _historical_identity_columns,
    _wait_for_legacy_boundary,
)
from tests.test_document_worker_claims_20261010_postgres import _parsed, _worker
from tests.test_matter_writer_admission_postgres import _fixture
from tests.test_postgres_validation import _ip_race_context

pytestmark = pytest.mark.postgres
_TEXT = "The parties shall comply within two weeks from today."
_DATED_TEXT = "The parties shall comply by 24 October 2026."
_TAIL_REVISION = "20261010_0004"
_RETAINED_ANCESTRY = (
    ("20261011_0001", "20261010_0004"),
    ("20261010_0004", "20261010_0003"),
    ("20261010_0003", "20261010_0002"),
    ("20261010_0002", "20261010_0001"),
)
_TAIL_TABLES = (
    "matter_compliance_extraction_runs",
    "matter_compliance_items",
    "model_runs",
    "matter_tasks",
    "matter_deadlines",
    "audit_events",
    "notification_delivery_intents",
    "notification_delivery_events",
    "matter_proceeding_signals",
    "matter_hearings",
    "matter_next_hearing_history",
    "matter_next_hearing_suggestions",
    "matters",
    "companies",
    "matter_activity",
    "in_app_notifications",
    "private_projection_events",
    "private_index_generations",
    "private_index_projections",
    "private_index_projection_scopes",
)


def _capture_current_head(cfg):
    scripts = ScriptDirectory.from_config(cfg)
    current_head = scripts.get_current_head()
    assert current_head is not None, "A canonical migration head is required"
    for revision, expected_parent in _RETAINED_ANCESTRY:
        retained = scripts.get_revision(revision)
        assert retained is not None
        assert retained.down_revision == expected_parent, (
            f"{revision} must retain parent {expected_parent}"
        )
    ancestors = {revision.revision for revision in scripts.iterate_revisions(current_head, "base")}
    assert {revision for revision, _ in _RETAINED_ANCESTRY} <= ancestors
    return current_head


@pytest.mark.parametrize(
    "variant",
    ["future_descendant", "fork", "missing_worker_ancestor", "missing_worker_root", "empty"],
)
def test_captured_head_accepts_future_descendant_and_rejects_invalid_graph(tmp_path, variant):
    versions = tmp_path / "versions"
    versions.mkdir()
    revisions = [("20261010_0001", None)] + [
        (revision, parent) for revision, parent in reversed(_RETAINED_ANCESTRY)
    ]
    if variant == "future_descendant":
        revisions.append(("test_future_0001", "20261011_0001"))
    elif variant == "fork":
        revisions.extend([
            ("test_future_0001", "20261011_0001"),
            ("test_future_0002", "20261011_0001"),
        ])
    elif variant in {"missing_worker_ancestor", "missing_worker_root"}:
        missing_revision, bypass_revision, bypass_parent = (
            ("20261010_0003", "20261010_0004", "20261010_0002")
            if variant == "missing_worker_ancestor"
            else ("20261010_0001", "20261010_0002", None)
        )
        revisions = [
            (revision, bypass_parent if revision == bypass_revision else parent)
            for revision, parent in revisions if revision != missing_revision
        ]
    else:
        revisions = []
    for revision, parent in revisions:
        (versions / f"{revision}.py").write_text(
            f"revision = {revision!r}\ndown_revision = {parent!r}\n"
            "branch_labels = None\ndepends_on = None\n",
            encoding="utf-8",
        )
    cfg = Config()
    cfg.set_main_option("script_location", str(tmp_path))
    if variant == "future_descendant":
        assert _capture_current_head(cfg) == "test_future_0001"
    elif variant == "fork":
        with pytest.raises(CommandError, match="multiple heads"):
            _capture_current_head(cfg)
    elif variant in {"missing_worker_ancestor", "missing_worker_root"}:
        with pytest.raises(
            AssertionError, match=f"{bypass_revision} must retain parent {missing_revision}"
        ):
            _capture_current_head(cfg)
    else:
        with pytest.raises(AssertionError, match="canonical migration head is required"):
            _capture_current_head(cfg)


@pytest.fixture
def tail_database(pg_engine, monkeypatch):
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    current_head = _capture_current_head(cfg)
    name = "compliance_tail_" + uuid4().hex
    url = pg_engine.url.set(database=name)
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text(f'CREATE DATABASE "{name}"'))
    engine, mapper = create_engine(url), registry()
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "")
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    get_settings.cache_clear()
    database = None
    try:
        command.upgrade(cfg, "20261010_0002")
        table = Table("matter_compliance_extraction_runs", MetaData(), autoload_with=engine)
        assert "persistence_protocol" not in table.c
        table.c.id.default = ColumnDefault(lambda: str(uuid4()))
        table.c.created_at.default = ColumnDefault(utcnow)
        table.c.updated_at.default = ColumnDefault(utcnow)
        table.c.updated_at.onupdate = ColumnDefault(utcnow)

        class LegacyRun:
            pass

        mapper.map_imperatively(LegacyRun, table)
        fixture = _fixture(engine, active=False)
        with Session(engine) as session:
            attachment = session.get(MatterAttachment, fixture.attachment)
            attachment.document_type = "order_judgment"
            attachment.processing_status = "indexed"
            attachment.extracted_text = _TEXT
            attachment.extracted_char_count = len(_TEXT)
            order = MatterCourtOrder(
                matter_id=fixture.matter,
                order_date=date(2026, 10, 10),
                title="Frozen source",
                summary="Native tail proof",
                source="manual",
                order_text=_TEXT,
            )
            session.add(order)
            session.flush()
            fixture.order = order.id
            session.commit()
        database = SimpleNamespace(
            engine=engine, cfg=cfg, fixture=fixture, legacy_run=LegacyRun,
            current_head=current_head,
        )
        with _historical_identity_columns(engine):
            yield database
    finally:
        try:
            if database is not None:
                _snapshot(database)
        finally:
            mapper.dispose()
            engine.dispose()
            get_settings.cache_clear()
            with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
                admin.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
                assert not admin.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=:name)"),
                    {"name": name},
                )


def _load_frozen(name, digest):
    path = Path(__file__).parent / "fixtures" / name
    assert hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
    module_name = "frozen_tail_" + uuid4().hex
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name)
    return module


def _legacy(database):
    module = _load_frozen(
        "compliance_extraction_3dbf.py",
        "15b0353be9ea24f376aac63d6a1b6e71ba1eb0bd6b93201d5e29a43299971a87",
    )
    participants = _load_frozen(
        "compliance_participants_3dbf.py",
        "cebe9e90a70e7e09499c639f5c7ad526656c9d037c3a606e340d4082ca9dbf09",
    )
    for name in (
        "ComplianceParticipantFenceError",
        "lock_compliance_participants",
        "_notification_context",
        "_recipient_memberships",
    ):
        setattr(module, name, getattr(participants, name))
    module.MatterComplianceExtractionRun = database.legacy_run
    return module


def _install(database, *, frozen_in_flight=False):
    if os.getenv("CASEOPS_COMPLIANCE_TAIL_BASELINE") == "unguarded":
        target = "20261010_0003"
    else:
        # Install only the historical fence while the historical transaction is
        # paused. Later concurrent-index DDL must wait for that worker to end.
        target = "20261010_0004" if frozen_in_flight else database.current_head
    before = _snapshot(database)
    command.upgrade(database.cfg, target)
    if target != "20261010_0003":
        for row in before["matter_compliance_extraction_runs"]:
            row["persistence_protocol"] = None
    assert _snapshot(database) == before, "Installing a protocol must not rewrite historical rows"
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == target
    print(json.dumps({
        "event": "native_tail_schema_boundary",
        "target": target,
        "frozen_in_flight": frozen_in_flight,
        "captured_current_head": database.current_head,
    }))


def _snapshot(database, *, connection=None):
    # Full raw rows, not filtered ORM DTOs, expose earlier writes and changed history.
    with (database.engine.connect() if connection is None else nullcontext(connection)) as active:
        result = {
            table: [
                dict(row)
                for row in active.execute(
                    text(f'SELECT * FROM "{table}" ORDER BY id')
                ).mappings()
            ]
            for table in _TAIL_TABLES
        }
        result["index"] = [
            dict(row)
            for row in active.execute(
                text("SELECT * FROM matter_attachments ORDER BY id")
            ).mappings()
        ]
        result["chunks"] = [
            dict(row)
            for row in active.execute(
                text("SELECT * FROM matter_attachment_chunks ORDER BY id")
            ).mappings()
        ]
        result["jobs"] = [
            dict(row)
            for row in active.execute(
                text("SELECT * FROM document_processing_jobs ORDER BY id")
            ).mappings()
        ]
        print(json.dumps({"event": "raw_tail_snapshot", "tables": result}, default=str))
        return result


def _provider(module, monkeypatch, *, outcome="valid", callback=None):
    settings = get_settings().model_copy(
        update={
            "compliance_ai_extraction_enabled": True,
            "compliance_ai_extraction_auto_run_enabled": True,
            "compliance_auto_activate_generated_work_enabled": True,
        }
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    calls = []

    class NativeProvider:
        name, model = "mock", "local"

        def generate_structured(self, **_kwargs):
            calls.append("native-only")
            if callback:
                callback()
            if outcome == "failure":
                raise LLMProviderError("Deterministic native provider failure")
            return LLMCompletion(
                provider="mock",
                model="local",
                prompt_tokens=11,
                completion_tokens=13,
                latency_ms=1,
                text=json.dumps(
                    {
                        "items": [
                            {
                                "description": "File the source-backed reply",
                                "source_snippet": _TEXT,
                                "confidence_label": "low",
                            }
                        ],
                    }
                ),
            )

    monkeypatch.setattr(module, "build_provider", lambda **_: NativeProvider())
    return calls


def _invoke(module, database, source):
    fixture = database.fixture
    token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
    try:
        with Session(database.engine, expire_on_commit=False) as session:
            matter = session.get(Matter, fixture.matter)
            if source == "order":
                result = module.run_compliance_extraction_for_order(
                    session,
                    matter=matter,
                    order=session.get(MatterCourtOrder, fixture.order),
                    actor_membership_id=fixture.actor,
                )
            else:
                result = module.run_compliance_extraction_for_attachment(
                    session,
                    matter=matter,
                    attachment=session.get(MatterAttachment, fixture.attachment),
                    actor_membership_id=fixture.actor,
                )
            session.commit()
            return result
    finally:
        reset_automated_test_request(token)


def _historical_run(database, **overrides):
    with Session(database.engine) as session:
        run = database.legacy_run(
            **{
                "company_id": database.fixture.company,
                "matter_id": database.fixture.matter,
                "court_order_id": database.fixture.order,
                "source_type": "manual_order",
                "trigger": "manual_order_create",
                "status": "processing",
                "parser_version": "caseops-compliance-extraction-v1",
                "started_at": utcnow(),
                "source_hash": hashlib.sha256(_TEXT.encode()).hexdigest(),
                "created_by_membership_id": database.fixture.actor,
                "metadata_json": {},
                **overrides,
            }
        )
        session.add(run)
        session.commit()
        return run.id


def _new_run(database, session, **overrides):
    run = MatterComplianceExtractionRun(
        **{
            "company_id": database.fixture.company,
            "matter_id": database.fixture.matter,
            "court_order_id": database.fixture.order,
            "created_by_membership_id": database.fixture.actor,
            "source_type": "manual_order",
            "trigger": "manual_order_create",
            "status": "processing",
            "parser_version": "caseops-compliance-extraction-v1",
            "started_at": utcnow(),
            "metadata_json": {},
            **overrides,
        }
    )
    admit_compliance_run(session, run)
    session.add(run)
    session.flush()
    return run


@pytest.mark.parametrize("source", ["order", "attachment"])
@pytest.mark.parametrize("outcome", ["valid", "failure", "missing_source"])
def test_actual_full_3db_extraction_cannot_create_tail_outputs(
    tail_database, monkeypatch, source, outcome
):
    database, entered, release = tail_database, Event(), Event()
    legacy = _legacy(database)
    _provider(legacy, monkeypatch, outcome=outcome)
    original = legacy._create_run

    def before_run(*args, **kwargs):
        entered.set()
        assert release.wait(15), "Frozen pre-run boundary was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(legacy, "_create_run", before_run)
    if outcome == "missing_source":
        with Session(database.engine) as session:
            session.get(MatterCourtOrder, database.fixture.order).order_text = None
            session.get(MatterAttachment, database.fixture.attachment).extracted_text = None
            session.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_invoke, legacy, database, source)
        try:
            _wait_for_legacy_boundary(entered, future)
            _install(database, frozen_in_flight=True)
            # The new nullable column is the only allowed historical-row delta.
            before = _snapshot(database)
            release.set()
            with pytest.raises(DBAPIError) as rejected:
                future.result(10)
            assert rejected.value.orig.sqlstate == "55000"
            assert _snapshot(database) == before
        finally:
            release.set()
    _install(database)


@pytest.mark.parametrize("outcome", ["valid", "failure"])
def test_actual_full_3db_worker_post_index_tail_is_rejected(tail_database, monkeypatch, outcome):
    database, entered, release = tail_database, Event(), Event()
    legacy = _legacy(database)
    _provider(legacy, monkeypatch, outcome=outcome)
    worker = _load_frozen(
        "document_jobs_3dbf.py", "c4acf5992cf7e73c62702c2420a7468beb1358723dca4db4f674bc179cf0f78f"
    )
    worker.get_session_factory = lambda: sessionmaker(bind=database.engine, expire_on_commit=False)
    monkeypatch.setattr(document_processing, "parse_attachment", lambda *_: _parsed(_TEXT))
    worker.embed_matter_attachment_chunks = lambda *_a, **_kw: 0
    original = legacy.run_compliance_extraction_for_attachment

    def tail(*args, **kwargs):
        entered.set()
        assert release.wait(15), "Frozen post-index boundary was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(compliance_extraction, "run_compliance_extraction_for_attachment", tail)
    errors = []

    def error(context):
        errors.append((getattr(context.original_exception, "sqlstate", None), context.statement))

    def invoke():
        token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
        try:
            worker.run_document_processing_job(database.fixture.job)
        finally:
            reset_automated_test_request(token)

    event.listen(database.engine, "handle_error", error)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(invoke)
            try:
                _wait_for_legacy_boundary(entered, future)
                _install(database, frozen_in_flight=True)
                before = _snapshot(database)
                assert before["jobs"][0]["status"] == "completed"
                assert before["index"][0]["extracted_text"] == _TEXT
                release.set()
                with pytest.raises(DBAPIError):
                    future.result(10)
                assert any(
                    state == "55000" and "matter_compliance_extraction_runs" in sql
                    for state, sql in errors
                ), errors
                assert _snapshot(database) == before
            finally:
                release.set()
    finally:
        event.remove(database.engine, "handle_error", error)
    _install(database)


@pytest.mark.parametrize("status", ["completed", "failed", "skipped"])
def test_committed_legacy_run_cannot_finalize_or_autostamp(tail_database, status):
    database = tail_database
    with Session(database.engine) as session:
        legacy_run = database.legacy_run(
            company_id=database.fixture.company,
            matter_id=database.fixture.matter,
            court_order_id=database.fixture.order,
            source_type="manual_order",
            trigger="manual_order_create",
            status="processing",
            parser_version="caseops-compliance-extraction-v1",
            started_at=utcnow(),
            metadata_json={"historical": True},
        )
        session.add(legacy_run)
        session.commit()
        run_id = legacy_run.id
    _install(database)
    before = _snapshot(database)
    assert before["matter_compliance_extraction_runs"][0]["persistence_protocol"] is None
    for assignment in (
        "status=:status",
        "persistence_protocol='compliance-tail-v1'",
        "status=status",
    ):
        with pytest.raises(DBAPIError) as rejected, database.engine.begin() as connection:
            connection.execute(
                text(f"UPDATE matter_compliance_extraction_runs SET {assignment} WHERE id=:id"),
                {"id": run_id, "status": status},
            )
        assert rejected.value.orig.sqlstate == "55000"
        assert _snapshot(database) == before


@pytest.mark.parametrize("status", ["completed", "failed", "skipped"])
def test_full_frozen_existing_run_tail_rolls_back_already_created_items(
    tail_database, monkeypatch, status
):
    database = tail_database
    with Session(database.engine) as session:
        session.get(MatterCourtOrder, database.fixture.order).order_text = _DATED_TEXT
        session.commit()
    run_id = _historical_run(
        database, source_hash=hashlib.sha256(_DATED_TEXT.encode()).hexdigest(),
    )
    _install(database)

    def current_helper_was_used(*_args, **_kwargs):
        raise AssertionError("The frozen tail must use its historical participant helpers")

    for name in ("lock_compliance_participants", "_notification_context", "_recipient_memberships"):
        monkeypatch.setattr(compliance_participants, name, current_helper_was_used)
    legacy = _legacy(database)
    provider_calls = _provider(legacy, monkeypatch)
    before = _snapshot(database)
    with Session(database.engine) as session:
        # The actual 3dbf pipeline admits participants before parent/child persistence too.
        legacy.lock_compliance_participants(
            session,
            company_id=database.fixture.company,
            matter_id=database.fixture.matter,
            actor_membership_id=database.fixture.actor,
        )
        matter = session.get(Matter, database.fixture.matter)
        run = session.get(database.legacy_run, run_id)
        order = session.get(MatterCourtOrder, database.fixture.order)
        items = legacy._deterministic_items(
            session,
            run=run,
            matter=matter,
            court_order=order,
            attachment=None,
            source_text=order.order_text,
            order_date=order.order_date,
        )
        assert items, "The frozen pre-finalization path must really create child rows"
        assert order.order_text == _DATED_TEXT
        assert run.source_hash == hashlib.sha256(order.order_text.encode()).hexdigest()
        assert all(item.due_on == date(2026, 10, 24) for item in items)
        assert not provider_calls
        session.flush()
        assert list(session.scalars(select(MatterComplianceItem)))
        staged = _snapshot(database, connection=session.connection())
        assert staged["matter_compliance_items"] and staged["matter_tasks"]
        assert staged["matter_deadlines"] and staged["notification_delivery_intents"]
        tasks = {row["id"]: row for row in staged["matter_tasks"]}
        deadlines = {row["id"]: row for row in staged["matter_deadlines"]}
        for item in staged["matter_compliance_items"]:
            assert item["extraction_run_id"] == run.id and item["source_hash"] == run.source_hash
            assert tasks[item["generated_task_id"]]["due_on"] == date(2026, 10, 24)
            deadline = deadlines[item["generated_deadline_id"]]
            assert deadline["due_on"] == date(2026, 10, 24)
            assert deadline["source_ref_id"] == item["id"]
        assert (
            staged["matter_compliance_extraction_runs"]
            == before["matter_compliance_extraction_runs"]
        )
        with pytest.raises(DBAPIError) as rejected:
            legacy._finish_run(
                session,
                run=run,
                matter=matter,
                created_count=len(items),
                status_value=status,
                error="Native failure" if status == "failed" else None,
            )
            session.commit()
        assert rejected.value.orig.sqlstate == "55000"
        assert not provider_calls
        session.rollback()
    assert _snapshot(database) == before


def test_full_frozen_attachment_resuming_from_provider_cannot_persist(tail_database, monkeypatch):
    database, entered, release = tail_database, Event(), Event()
    legacy = _legacy(database)

    def provider_boundary():
        entered.set()
        assert release.wait(15), "Frozen provider callback was not released"

    calls = _provider(legacy, monkeypatch, callback=provider_boundary)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_invoke, legacy, database, "attachment")
        try:
            _wait_for_legacy_boundary(entered, future)
            _install(database, frozen_in_flight=True)
            before = _snapshot(database)
            release.set()
            with pytest.raises(DBAPIError) as rejected:
                future.result(10)
            assert rejected.value.orig.sqlstate == "55000"
            assert calls == ["native-only"]
            assert _snapshot(database) == before
        finally:
            release.set()
    _install(database)


def test_actual_3db_run_creation_prevents_retroactive_ddl_acceptance(tail_database, monkeypatch):
    database, entered, release = tail_database, Event(), Event()
    legacy = _legacy(database)
    _provider(legacy, monkeypatch)
    original = legacy._create_run

    def after_run(*args, **kwargs):
        run = original(*args, **kwargs)
        entered.set()
        assert release.wait(15), "Frozen run-creation boundary was not released"
        return run

    monkeypatch.setattr(legacy, "_create_run", after_run)
    monkeypatch.setenv("CASEOPS_MIGRATION_DB_LOCK_TIMEOUT_MS", "1000")
    get_settings.cache_clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_invoke, legacy, database, "attachment")
        try:
            _wait_for_legacy_boundary(entered, future)
            with pytest.raises(DBAPIError) as blocked:
                command.upgrade(database.cfg, "head")
            assert blocked.value.orig.sqlstate == "55P03"
            with database.engine.connect() as connection:
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == "20261010_0002"
                )
            release.set()
            future.result(10)
            _install(database)
            assert (
                _snapshot(database)["matter_compliance_extraction_runs"][0]["persistence_protocol"]
                is None
            )
        finally:
            release.set()


@pytest.mark.parametrize("source", ["order", "attachment"])
@pytest.mark.parametrize("outcome", ["valid", "failure", "missing_source", "persist_failure"])
def test_current_full_extraction_marker_success_failure_skip_and_replay(
    tail_database, monkeypatch, source, outcome
):
    database = tail_database
    command.upgrade(database.cfg, "head")
    calls = _provider(compliance_extraction, monkeypatch, outcome=outcome)
    if outcome == "persist_failure":

        def fail_persistence(*_args, **_kwargs):
            raise RuntimeError("Native persistence preparation failure")

        monkeypatch.setattr(compliance_extraction, "_deterministic_items", fail_persistence)
    if outcome == "missing_source":
        with Session(database.engine) as session:
            session.get(MatterCourtOrder, database.fixture.order).order_text = None
            session.get(MatterAttachment, database.fixture.attachment).extracted_text = None
            session.commit()
    first, items = _invoke(compliance_extraction, database, source)
    second, replay_items = _invoke(compliance_extraction, database, source)
    assert first.persistence_protocol == second.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL
    assert first.id != second.id and not replay_items
    expected = {"missing_source": "skipped", "persist_failure": "failed"}.get(outcome, "completed")
    assert first.status == second.status == expected
    assert bool(items) == (outcome not in {"missing_source", "persist_failure"})
    assert bool(calls) == (outcome != "missing_source")


def test_current_worker_retains_actual_attempt_and_persists_compliance(tail_database, monkeypatch):
    database = tail_database
    command.upgrade(database.cfg, "head")
    _provider(compliance_extraction, monkeypatch)
    _worker(monkeypatch, database.engine, lambda *_: _parsed(_TEXT))
    assert document_jobs.run_document_processing_job(database.fixture.job) is True
    with Session(database.engine) as session:
        job = session.get(DocumentProcessingJob, database.fixture.job)
        runs = list(session.scalars(select(MatterComplianceExtractionRun)))
        assert job.status == "completed" and job.error_message is None
        assert runs and all(run.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL for run in runs)
        assert list(session.scalars(select(MatterComplianceItem)))


@pytest.mark.parametrize(
    "path",
    ["create", "retry", "attachment_upload", "attachment_metadata", "manual_sync", "court_worker"],
)
def test_current_actual_manual_and_court_callers_keep_marker(tail_database, monkeypatch, path):
    database = tail_database
    command.upgrade(database.cfg, "head")

    def scoped_session(_role):
        return Session(database.engine)

    observations = []

    def record(event_name, **fields):
        assert paid_providers_blocked_for_request()
        observations.append({"event": event_name, **fields})

    audit = SimpleNamespace(
        engine=database.engine, session=scoped_session, record=record, pids={}
    )
    upload = _UploadPhase(audit) if path == "attachment_upload" else None
    fixture = _seed(audit)

    def marked_provider():
        assert paid_providers_blocked_for_request()

    calls = _provider(
        compliance_extraction, monkeypatch,
        callback=marked_provider if upload is not None else None,
    )
    with Session(audit.engine) as session:
        attachment = session.get(MatterAttachment, fixture["attachment_id"])
        attachment.processing_status, attachment.extracted_text = "indexed", _TEXT
        session.commit()
    token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
    try:
        _mutate(audit, fixture, path, monkeypatch, upload)
    finally:
        reset_automated_test_request(token)
    with Session(audit.engine) as session:
        runs = list(
            session.scalars(
                select(MatterComplianceExtractionRun).where(
                    MatterComplianceExtractionRun.matter_id == fixture["matter_id"],
                )
            )
        )
        assert runs and all(run.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL for run in runs)
        if upload is None:
            return
        assert upload.initial_ended and upload.storage_complete.is_set()
        assert {row["event"] for row in observations} >= {
            "upload_initial_transaction_ended", "upload_storage_entered", "upload_storage_complete"
        }
        uploaded = list(session.scalars(select(MatterAttachment).where(
            MatterAttachment.matter_id == fixture["matter_id"],
            MatterAttachment.id != fixture["attachment_id"],
        )))
        assert len(uploaded) == 1
        attachment = uploaded[0]
        uploaded_id = attachment.id
        assert attachment.linked_court_order_id == fixture["order_id"]
        assert attachment.document_type == "order_judgment"
        assert attachment.uploaded_by_membership_id == fixture["actor_id"]
        assert attachment.sha256_hex == hashlib.sha256(b"Local source order document").hexdigest()
        upload_runs = [run for run in runs if run.attachment_id == uploaded_id]
        assert len(upload_runs) == 1
        assert upload_runs[0].source_type == "manual_upload"
        assert upload_runs[0].trigger == "attachment_processed"
        assert upload_runs[0].status == "skipped"
        assert upload_runs[0].skip_reason == "text_extraction_pending"
        assert upload_runs[0].created_by_membership_id == fixture["actor_id"]
        jobs = list(session.scalars(select(DocumentProcessingJob).where(
            DocumentProcessingJob.attachment_id == uploaded_id,
        )))
        assert len(jobs) == 1 and jobs[0].no_paid_providers is True
        assert jobs[0].requested_by_membership_id == fixture["actor_id"]
        job_id = jobs[0].id
        assert calls == []
    _worker(monkeypatch, database.engine, lambda *_: _parsed(_TEXT))
    assert document_jobs.run_document_processing_job(job_id) is True
    assert calls == ["native-only"]
    with Session(database.engine) as session:
        job = session.get(DocumentProcessingJob, job_id)
        attachment = session.get(MatterAttachment, uploaded_id)
        assert job.status == "completed" and job.no_paid_providers is True
        assert job.requested_by_membership_id == fixture["actor_id"]
        assert attachment.uploaded_by_membership_id == fixture["actor_id"]
        assert attachment.extracted_text == _TEXT
        assert attachment.sha256_hex == hashlib.sha256(b"Local source order document").hexdigest()
        completed_runs = list(session.scalars(select(MatterComplianceExtractionRun).where(
            MatterComplianceExtractionRun.attachment_id == uploaded_id,
            MatterComplianceExtractionRun.status == "completed",
        )))
        assert len(completed_runs) == 1
        run = completed_runs[0]
        assert run.source_type == "manual_upload" and run.trigger == "attachment_processed"
        assert run.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL
        assert run.source_hash == hashlib.sha256(_TEXT.encode()).hexdigest()
        assert run.created_by_membership_id is None
        assert list(session.scalars(select(MatterComplianceItem).where(
            MatterComplianceItem.extraction_run_id == run.id,
        )))
        print(json.dumps({
            "event": "actual_upload_tail_proof", "attachment_id": uploaded_id,
            "job_id": job_id, "job_no_paid_providers": job.no_paid_providers,
            "uploaded_body_sha256": attachment.sha256_hex,
            "extracted_source_sha256": run.source_hash,
            "persistence_protocol": run.persistence_protocol,
            "provider": "deterministic-native-emulator",
        }))


def test_tail_context_does_not_leak_across_commit_or_rollback(tail_database, monkeypatch):
    database = tail_database
    command.upgrade(database.cfg, "head")
    _provider(compliance_extraction, monkeypatch)
    run, _ = _invoke(compliance_extraction, database, "attachment")
    for operation in ("commit", "rollback"):
        with database.engine.connect() as connection, Session(bind=connection) as session:
            retained = session.get(MatterComplianceExtractionRun, run.id)
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            bind_compliance_run_context(session, retained)
            assert session.scalar(text("SELECT current_setting('caseops.compliance_tail', true)"))
            getattr(session, operation)()
            assert session.scalar(text("SELECT pg_backend_pid()")) == pid
            assert not session.scalar(
                text("SELECT current_setting('caseops.compliance_tail', true)")
            )
            with pytest.raises(DBAPIError) as rejected:
                session.execute(
                    text("UPDATE matter_compliance_extraction_runs SET status=status WHERE id=:id"),
                    {"id": run.id},
                )
            assert rejected.value.orig.sqlstate == "55000"


def test_current_existing_run_finalize_review_and_legacy_retry_are_distinct(
    tail_database, monkeypatch
):
    database = tail_database
    with Session(database.engine) as session:
        old = database.legacy_run(
            company_id=database.fixture.company,
            matter_id=database.fixture.matter,
            court_order_id=database.fixture.order,
            source_type="manual_order",
            trigger="manual_retry",
            status="failed",
            parser_version="caseops-compliance-extraction-v1",
            metadata_json={"old": True},
        )
        session.add(old)
        session.commit()
        legacy_id = old.id
    command.upgrade(database.cfg, "head")
    original = _snapshot(database)["matter_compliance_extraction_runs"]
    _provider(compliance_extraction, monkeypatch)
    with Session(database.engine) as session:
        context = _ip_race_context(
            session, company_id=database.fixture.company, membership_id=database.fixture.actor
        )
        fresh, items = compliance_extraction.retry_order_compliance_extraction(
            session,
            context=context,
            matter_id=database.fixture.matter,
            order_id=database.fixture.order,
        )
        assert fresh.id != legacy_id and fresh.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL
        assert items
        compliance_extraction.update_compliance_item(
            session,
            context=context,
            matter_id=database.fixture.matter,
            item_id=items[0].id,
            action="confirm",
        )
        # Public retry/review commit; private finalization requires fresh admission.
        compliance_extraction.lock_compliance_participants(
            session,
            company_id=database.fixture.company,
            matter_id=database.fixture.matter,
            actor_membership_id=context.membership.id,
            context=context,
            required_capability="matters:write",
        )
        retained = session.get(MatterComplianceExtractionRun, fresh.id)
        compliance_extraction._finish_run(
            session,
            run=retained,
            matter=session.get(Matter, database.fixture.matter),
            created_count=len(items),
            status_value="completed",
        )
        session.commit()
        assert session.get(MatterComplianceExtractionRun, legacy_id).persistence_protocol is None
    assert [
        row
        for row in _snapshot(database)["matter_compliance_extraction_runs"]
        if row["id"] == legacy_id
    ] == original


@pytest.mark.parametrize(
    "variant",
    [
        "missing",
        "invalid_json",
        "array",
        "extra_key",
        "missing_key",
        "wrong_company",
        "wrong_run",
        "numeric_identity",
        "null_protocol",
        "oversized",
        "invalid_attempt",
    ],
)
def test_native_context_validation_is_fail_closed_and_bounded(tail_database, variant):
    database = tail_database
    command.upgrade(database.cfg, "head")
    with Session(database.engine) as session:
        run = _new_run(database, session)
        run_id = run.id
        session.commit()
        bind_compliance_run_context(session, run)
        payload = json.loads(
            session.scalar(text("SELECT current_setting('caseops.compliance_tail')"))
        )
        if variant == "extra_key":
            payload["extra"] = True
        elif variant == "missing_key":
            del payload["source_hash"]
        elif variant == "wrong_company":
            payload["company_id"] = str(uuid4())
        elif variant == "wrong_run":
            payload["run_id"] = str(uuid4())
        elif variant == "numeric_identity":
            payload["matter_id"] = 12
        elif variant == "null_protocol":
            payload["protocol"] = None
        elif variant == "invalid_attempt":
            payload["document_attempt"] = {
                "id": database.fixture.job,
                "attempt_count": 1,
                "started_at": "2026-10-10T00:00:00",
            }
        encoded = {"missing": "", "invalid_json": "{", "array": "[]", "oversized": " " * 4097}.get(
            variant, json.dumps(payload)
        )
        session.execute(
            text("SELECT set_config('caseops.compliance_tail', :payload, true)"),
            {"payload": encoded},
        )
        before = _snapshot(database)
        with pytest.raises(DBAPIError) as rejected:
            session.execute(
                text(
                    "UPDATE matter_compliance_extraction_runs SET status='completed' WHERE id=:id"
                ),
                {"id": run_id},
            )
        assert rejected.value.orig.sqlstate == "55000"
        session.rollback()
    assert _snapshot(database) == before


@pytest.mark.parametrize(
    "field",
    ["company_id", "matter_id", "court_order_id", "attachment_id", "created_by_membership_id"],
)
def test_native_cross_tenant_source_or_actor_cannot_use_matching_context(tail_database, field):
    database = tail_database
    other = _fixture(database.engine, active=False)
    with Session(database.engine) as session:
        order = MatterCourtOrder(
            matter_id=other.matter,
            order_date=date(2026, 10, 10),
            title="Other scope",
            summary="Other source",
            source="manual",
        )
        session.add(order)
        session.flush()
        other.order = order.id
        session.commit()
    command.upgrade(database.cfg, "head")
    identifiers = {
        "company_id": other.company,
        "matter_id": other.matter,
        "court_order_id": other.order,
        "attachment_id": other.attachment,
        "created_by_membership_id": other.actor,
    }
    before = _snapshot(database)
    with Session(database.engine) as session, pytest.raises(DBAPIError) as rejected:
        _new_run(database, session, **{field: identifiers[field]})
    assert rejected.value.orig.sqlstate == "55000"
    assert _snapshot(database) == before


@pytest.mark.parametrize("variant", ["valid", "replaced", "expired", "wrong_target", "wrong_job"])
def test_native_worker_attempt_uses_exact_current_row_not_adoption(tail_database, variant):
    database = tail_database
    captured_start = datetime.now(UTC) - timedelta(minutes=16 if variant == "expired" else 0)
    with Session(database.engine) as session:
        job = session.get(DocumentProcessingJob, database.fixture.job)
        job.status, job.started_at, job.completed_at = "completed", captured_start, utcnow()
        job.attempt_count = 2 if variant == "replaced" else 1
        if variant == "wrong_target":
            job.target_type = "ip_document_version"
        session.commit()
    command.upgrade(database.cfg, "head")
    before = _snapshot(database)
    with Session(database.engine) as session:
        session.info["document_job_attempt"] = SimpleNamespace(
            id=str(uuid4()) if variant == "wrong_job" else database.fixture.job,
            company_id=database.fixture.company,
            number=1,
            started_at=captured_start,
        )
        if variant == "valid":
            run = _new_run(database, session, attachment_id=database.fixture.attachment)
            session.commit()
            assert run.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL
        else:
            with pytest.raises(DBAPIError) as rejected:
                _new_run(database, session, attachment_id=database.fixture.attachment)
            assert rejected.value.orig.sqlstate == "55000"
            session.rollback()
            assert _snapshot(database) == before


@pytest.mark.parametrize("opted_in", [False, True])
def test_native_populated_downgrade_preserves_legacy_metadata_and_guard(tail_database, opted_in):
    database = tail_database
    _historical_run(database, metadata_json={"retained": "original"})
    command.upgrade(database.cfg, _TAIL_REVISION)
    database.cfg.cmd_opts = SimpleNamespace(
        x=["compliance_tail_fresh_downgrade=true"] if opted_in else []
    )
    before = _snapshot(database)
    with pytest.raises(RuntimeError, match="restore-forward"):
        command.downgrade(database.cfg, "20261010_0003")
    assert _snapshot(database) == before
    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == _TAIL_REVISION
        )


def test_native_empty_explicit_downgrade_then_upgrade_restores_fence(tail_database):
    database = tail_database
    command.upgrade(database.cfg, _TAIL_REVISION)
    database.cfg.cmd_opts = SimpleNamespace(x=["compliance_tail_fresh_downgrade=true"])
    command.downgrade(database.cfg, "20261010_0003")
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261010_0003"
        assert not connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
                "WHERE table_name='matter_compliance_extraction_runs' "
                "AND column_name='persistence_protocol')"
            )
        )
    command.upgrade(database.cfg, _TAIL_REVISION)
    with Session(database.engine) as session:
        run = _new_run(database, session)
        session.commit()
        assert run.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL


def test_native_downgrade_excludes_insert_between_empty_check_and_drop(tail_database):
    database = tail_database
    command.upgrade(database.cfg, _TAIL_REVISION)
    database.cfg.cmd_opts = SimpleNamespace(x=["compliance_tail_fresh_downgrade=true"])
    before = _snapshot(database)
    checked, release = Event(), Event()

    def pause_after_empty_check(_connection, _cursor, statement, *_args):
        if statement == "SELECT 1 FROM matter_compliance_extraction_runs LIMIT 1":
            checked.set()
            assert release.wait(timeout=10), "Native downgrade check was not released"

    event.listen(database.engine.__class__, "after_cursor_execute", pause_after_empty_check)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            downgrade = executor.submit(command.downgrade, database.cfg, "20261010_0003")
            try:
                assert checked.wait(timeout=10), "Actual downgrade never checked root emptiness"
                with Session(database.engine) as session:
                    session.execute(text("SET LOCAL lock_timeout = '250ms'"))
                    with pytest.raises(DBAPIError) as blocked:
                        _new_run(database, session)
                    assert blocked.value.orig.sqlstate == "55P03"
                    session.rollback()
            finally:
                release.set()
            downgrade.result(timeout=10)
    finally:
        release.set()
        event.remove(database.engine.__class__, "after_cursor_execute", pause_after_empty_check)
    command.upgrade(database.cfg, _TAIL_REVISION)
    assert _snapshot(database) == before


def test_native_downgrade_lock_timeout_retains_protocol_and_uncommitted_insert(
    tail_database, monkeypatch
):
    database = tail_database
    command.upgrade(database.cfg, _TAIL_REVISION)
    database.cfg.cmd_opts = SimpleNamespace(x=["compliance_tail_fresh_downgrade=true"])
    monkeypatch.setenv("CASEOPS_MIGRATION_DB_LOCK_TIMEOUT_MS", "1000")
    get_settings.cache_clear()
    before = _snapshot(database)
    with Session(database.engine) as session:
        run = _new_run(database, session)
        with pytest.raises(DBAPIError) as blocked:
            command.downgrade(database.cfg, "20261010_0003")
        assert blocked.value.orig.sqlstate == "55P03"
        session.commit()
        assert run.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL
    with database.engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == _TAIL_REVISION
        )
    after = _snapshot(database)
    assert len(after["matter_compliance_extraction_runs"]) == 1
    after["matter_compliance_extraction_runs"] = []
    assert after == before


@pytest.mark.parametrize("field", ["company_id", "matter_id", "purpose"])
@pytest.mark.parametrize("operation", ["insert", "update"])
def test_native_model_run_link_requires_exact_tenant_target_and_purpose(
    tail_database, field, operation
):
    database = tail_database
    other = _fixture(database.engine, active=False)
    command.upgrade(database.cfg, "head")
    with Session(database.engine) as session:
        model = ModelRun(
            **{
                "company_id": database.fixture.company,
                "matter_id": database.fixture.matter,
                "purpose": "compliance_extraction",
                "provider": "mock",
                "model": "local",
                field: {
                    "company_id": other.company,
                    "matter_id": other.matter,
                    "purpose": "metadata_extract",
                }[field],
            }
        )
        session.add(model)
        session.flush()
        model_id = model.id
        run_id = _new_run(database, session).id if operation == "update" else None
        session.commit()
    before = _snapshot(database)
    with Session(database.engine) as session, pytest.raises(DBAPIError) as rejected:
        if operation == "insert":
            _new_run(database, session, model_run_id=model_id)
        else:
            session.execute(
                text(
                    "UPDATE matter_compliance_extraction_runs SET model_run_id=:model WHERE id=:id"
                ),
                {"model": model_id, "id": run_id},
            )
    assert rejected.value.orig.sqlstate == "55000"
    assert _snapshot(database) == before


@pytest.mark.parametrize("parent", ["attachment", "model"])
def test_native_fk_detachment_retains_marker_and_source_history(tail_database, parent):
    database = tail_database
    command.upgrade(database.cfg, "head")
    with Session(database.engine) as session:
        model = ModelRun(
            company_id=database.fixture.company,
            matter_id=database.fixture.matter,
            purpose="compliance_extraction",
            provider="mock",
            model="local",
        )
        session.add(model)
        session.flush()
        run = _new_run(
            database,
            session,
            attachment_id=database.fixture.attachment,
            model_run_id=model.id,
            source_hash="b" * 64,
        )
        run_id, model_id = run.id, model.id
        session.commit()
        target = (
            session.get(MatterAttachment, database.fixture.attachment)
            if parent == "attachment"
            else session.get(ModelRun, model_id)
        )
        session.delete(target)
        session.commit()
        session.refresh(run)
        assert run.id == run_id and run.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL
        assert run.source_hash == "b" * 64
        assert (run.attachment_id if parent == "attachment" else run.model_run_id) is None


@pytest.mark.parametrize("caller", ["manual", "worker"])
def test_current_multi_order_import_rebinds_each_root_without_committing_partial_work(
    tail_database, monkeypatch, caller
):
    database = tail_database
    command.upgrade(database.cfg, "head")

    def scoped_session(_role):
        return Session(database.engine)

    audit = SimpleNamespace(engine=database.engine, session=scoped_session)
    fixture = _seed(audit)
    calls = _provider(compliance_extraction, monkeypatch)
    orders = [
        MatterCourtOrderSyncItem(
            order_date=date(2026, 10, day),
            title=f"Local order {day}",
            summary="Independent imported source",
            order_text=_TEXT,
        )
        for day in (14, 15)
    ]
    token = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
    try:
        if caller == "worker":
            adapter = SimpleNamespace(
                fetch=lambda **_: SimpleNamespace(
                    summary="Native local adapter",
                    orders=orders,
                    cause_list_entries=[],
                    adapter_name="local-emulator",
                )
            )
            monkeypatch.setattr(court_sync_jobs, "get_court_sync_adapter", lambda _: adapter)
            monkeypatch.setattr(
                court_sync_jobs, "get_session_factory", lambda: lambda: scoped_session("worker")
            )
            court_sync_jobs.run_matter_court_sync_job(fixture["court_job_id"])
        else:
            with scoped_session("manual") as session:
                context = _ip_race_context(
                    session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
                )
                matters.create_matter_court_sync_import(
                    session,
                    context=context,
                    matter_id=fixture["matter_id"],
                    payload=MatterCourtSyncImportRequest(source="local-emulator", orders=orders),
                )
    finally:
        reset_automated_test_request(token)
    with Session(database.engine) as session:
        runs = list(
            session.scalars(
                select(MatterComplianceExtractionRun).where(
                    MatterComplianceExtractionRun.matter_id == fixture["matter_id"]
                )
            )
        )
        assert len(runs) == 2 and len({run.id for run in runs}) == 2
        assert all(
            run.persistence_protocol == COMPLIANCE_TAIL_PROTOCOL and run.status == "completed"
            for run in runs
        )
        assert len({run.court_order_id for run in runs}) == 2
        assert calls == ["native-only", "native-only"]
