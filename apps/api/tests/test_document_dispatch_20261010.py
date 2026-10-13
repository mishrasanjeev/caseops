from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from caseops_api.core.settings import Settings
from caseops_api.services import document_dispatch as dispatch


class Base(DeclarativeBase):
    pass


class Admission(Base):
    __tablename__ = "admissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(default="initial")


@pytest.mark.parametrize("minutes", [0, 1, 14, 15, 16])
def test_claim_expiry_configuration_preserves_database_protocol_floor(minutes):
    if minutes < 15:
        with pytest.raises(ValidationError) as rejected:
            Settings(document_processing_stale_after_minutes=minutes)
        assert any(
            error["loc"] == ("document_processing_stale_after_minutes",)
            and error["type"] == "greater_than_equal"
            for error in rejected.value.errors()
        )
    else:
        settings = Settings(document_processing_stale_after_minutes=minutes)
        assert settings.document_processing_stale_after_minutes == minutes


def configure(monkeypatch, **overrides):
    values = dict(
        env="cloud",
        document_processing_dispatch_mode="cloud_run_job",
        gcp_project_id="perfect-period-305406",
        document_processing_run_region="asia-south1",
        document_processing_run_job="caseops-document-processing",
        court_sync_dispatch_mode="cloud_run_job",
        court_sync_run_region="asia-south1",
        court_sync_run_job="caseops-court-sync",
    )
    values.update(overrides)
    monkeypatch.setattr(dispatch, "get_settings", lambda: SimpleNamespace(**values))


@pytest.fixture(params=["document", "court"])
def dispatcher(request):
    return (
        dispatch.dispatch_document_processing_job if request.param == "document"
        else dispatch.dispatch_court_sync_processing_job
    )


@pytest.mark.parametrize("pending", ["new", "dirty", "deleted", "nested", "flushed", "external"])
def test_uncommitted_admission_fails_before_rollback_or_transport(monkeypatch, pending, dispatcher):
    configure(monkeypatch)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        if pending == "external":
            connection.begin()
        with Session(connection if pending == "external" else engine) as session:
            if pending == "flushed":
                session.add(Admission(id=1))
                session.flush()
                assert not session.new and not session.dirty and not session.deleted
            elif pending == "nested":
                session.begin_nested()
            elif pending != "external":
                admission = Admission(id=1)
                if pending == "new":
                    session.add(admission)
                else:
                    session.add(admission)
                    session.commit()
                    if pending == "dirty":
                        admission.label = "not committed"
                    else:
                        session.delete(admission)
            monkeypatch.setattr(dispatch, "_wake_cloud_run_queue",
                                lambda **_: pytest.fail("must not dispatch pending admission"))
            monkeypatch.setattr(session, "rollback", lambda: pytest.fail("discarded caller writes"))
            with pytest.raises(HTTPException, match="must be committed") as rejected:
                dispatcher(
                    session=session, background_tasks=BackgroundTasks(), job_id="pending",
                )
            assert rejected.value.status_code == 409
            if pending == "flushed":
                assert session.scalar(text("SELECT COUNT(*) FROM admissions")) == 1
            if pending == "external":
                assert isinstance(session.get_bind(), Connection) and connection.in_transaction()


@pytest.mark.parametrize("accepted", [True, False])
def test_production_wake_releases_transaction_and_never_runs_after_response(
    monkeypatch, accepted, dispatcher,
):
    configure(monkeypatch)
    tasks = BackgroundTasks()
    with Session(create_engine("sqlite://")) as session:
        session.execute(text("SELECT 1"))
        assert session.in_transaction()
        calls = []

        async def wake(**kwargs):
            assert not session.in_transaction()
            calls.append(kwargs)
            return accepted

        monkeypatch.setattr(dispatch, "_wake_cloud_run_queue", wake)
        dispatcher(
            session=session, background_tasks=tasks, job_id="durable-job"
        )
        assert calls == [
            dict(
                project="perfect-period-305406",
                region="asia-south1",
                job=("caseops-document-processing" if dispatcher.__name__
                     == "dispatch_document_processing_job" else "caseops-court-sync"),
            )
        ]
        assert not tasks.tasks
        assert not session.in_transaction()


@pytest.mark.parametrize("project", [None, "../../other", "https://attacker.invalid", "x"])
def test_invalid_target_cannot_start_an_execution(monkeypatch, project, dispatcher):
    configure(monkeypatch, gcp_project_id=project)
    monkeypatch.setattr(
        dispatch, "_wake_cloud_run_queue", lambda **_: pytest.fail("unexpected transport")
    )
    with Session(create_engine("sqlite://")) as session:
        tasks = BackgroundTasks()
        dispatcher(
            session=session, background_tasks=tasks, job_id="queued"
        )
        assert not tasks.tasks


@pytest.mark.parametrize("env, expected_tasks", [("local", 1), ("cloud", 0), ("unknown", 0)])
def test_only_local_runtime_can_keep_the_inline_background_path(
    monkeypatch, env, expected_tasks, dispatcher,
):
    configure(monkeypatch, env=env, document_processing_dispatch_mode="local_background",
              court_sync_dispatch_mode="local_background")
    monkeypatch.setattr(
        dispatch, "_wake_cloud_run_queue", lambda **_: pytest.fail("unexpected transport")
    )
    with Session(create_engine("sqlite://")) as session:
        tasks = BackgroundTasks()
        dispatcher(
            session=session, background_tasks=tasks, job_id="queued"
        )
        assert len(tasks.tasks) == expected_tasks
        if expected_tasks:
            assert tasks.tasks[0].func.__name__ == (
                "run_document_processing_job" if dispatcher.__name__
                == "dispatch_document_processing_job" else "run_matter_court_sync_job"
            )


def _transport(monkeypatch, handler):
    real_client = httpx.AsyncClient
    clients = []

    def client(**kwargs):
        assert kwargs == dict(
            timeout=dispatch.DISPATCH_BUDGET_SECONDS, follow_redirects=False, trust_env=False,
        )
        instance = real_client(**kwargs, transport=httpx.MockTransport(handler))
        clients.append(instance)
        return instance

    monkeypatch.setattr(dispatch.httpx, "AsyncClient", client)
    return clients


def _wake(job="caseops-document-processing"):
    return asyncio.run(dispatch._wake_cloud_run_queue(
        project="perfect-period-305406", region="asia-south1", job=job,
    ))


@pytest.mark.parametrize("status", [200, 202, 302, 403, 429, 503])
@pytest.mark.parametrize("job", ["caseops-document-processing", "caseops-court-sync"])
def test_cloud_run_kick_is_one_bounded_no_override_post(monkeypatch, status, job):
    calls = []

    async def handler(request):
        calls.append(request)
        if request.method == "GET":
            assert str(request.url) == (
                "http://metadata.google.internal/computeMetadata/v1/"
                "instance/service-accounts/default/token"
            )
            assert request.headers["metadata-flavor"] == "Google"
            return httpx.Response(200, json={"access_token": "test-token"})
        assert request.method == "POST"
        assert str(request.url) == (
            "https://run.googleapis.com/v2/projects/perfect-period-305406/"
            f"locations/asia-south1/jobs/{job}:run"
        )
        assert request.content == b"{}"
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(status, headers={"location": "https://attacker.invalid"})

    clients = _transport(monkeypatch, handler)
    assert _wake(job) == (status in {200, 202})
    assert [request.method for request in calls] == ["GET", "POST"]
    assert len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize("payload", [{}, [], {"access_token": ""},
                                   {"access_token": "bad" + chr(10) + "header"},
                                   {"access_token": "x" * 4097}, {"access_token": None}])
def test_invalid_metadata_leaves_queued_work_without_post(monkeypatch, payload):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    clients = _transport(monkeypatch, handler)
    assert not _wake()
    assert len(calls) == 1 and clients[0].is_closed


@pytest.mark.parametrize("status", [302, 403, 429, 503])
def test_metadata_error_has_no_retry_redirect_or_post(monkeypatch, status):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://attacker.invalid"})

    clients = _transport(monkeypatch, handler)
    assert not _wake()
    assert len(calls) == 1 and clients[0].is_closed


@pytest.mark.parametrize("stage", ["metadata", "post"])
def test_total_deadline_cancels_slow_headers_and_closes_transport(monkeypatch, stage):
    monkeypatch.setattr(dispatch, "DISPATCH_BUDGET_SECONDS", 0.02)
    calls = []
    cancelled = []

    async def handler(request):
        calls.append(request.method)
        if stage == "metadata" or request.method == "POST":
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.append(request.method)
                raise
        return httpx.Response(200, json={"access_token": "test-token"})

    clients = _transport(monkeypatch, handler)
    assert not _wake()
    expected = ["GET"] if stage == "metadata" else ["GET", "POST"]
    assert calls == expected and cancelled == [expected[-1]]
    assert len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize("oversized", [False, True])
def test_metadata_stream_is_bounded_and_cancelled_before_post(monkeypatch, oversized):
    monkeypatch.setattr(dispatch, "DISPATCH_BUDGET_SECONDS", 0.02)
    closed = []
    calls = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b" " * (16_385 if oversized else 1)
            await asyncio.sleep(60)

        async def aclose(self):
            closed.append(True)

    async def handler(request):
        calls.append(request.method)
        return httpx.Response(200, stream=Body())

    clients = _transport(monkeypatch, handler)
    assert not _wake()
    assert calls == ["GET"] and closed == [True] and clients[0].is_closed


def test_all_eight_document_route_entry_points_share_the_dispatch_boundary():
    root = Path(__file__).resolve().parents[1] / "src/caseops_api/api/routes"
    calls = []
    for name in ("matters", "contracts", "ip_operations"):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            dispatches = [
                call
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and (
                    (
                        isinstance(call.func, ast.Name)
                        and call.func.id == "dispatch_document_processing_job"
                    )
                    or (
                        isinstance(call.func, ast.Name)
                        and call.func.id == "run_in_threadpool"
                        and call.args
                        and isinstance(call.args[0], ast.Name)
                        and call.args[0].id == "dispatch_document_processing_job"
                    )
                )
            ]
            for call in dispatches:
                assert {key.arg for key in call.keywords} == {
                    "session",
                    "background_tasks",
                    "job_id",
                }
                if isinstance(node, ast.AsyncFunctionDef):
                    assert isinstance(call.func, ast.Name) and call.func.id == "run_in_threadpool"
                calls.append((name, node.name))
    assert len(calls) == 8 and len(set(calls)) == 8


def test_court_pull_route_uses_the_committed_off_event_loop_dispatch_boundary():
    root = Path(__file__).resolve().parents[1] / "src/caseops_api/api/routes"
    tree = ast.parse((root / "matters.py").read_text(encoding="utf-8"))
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for call in ast.walk(node):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "run_in_threadpool" and call.args
                    and isinstance(call.args[0], ast.Name)
                    and call.args[0].id == "dispatch_court_sync_processing_job"):
                assert {keyword.arg for keyword in call.keywords} == {
                    "session", "background_tasks", "job_id",
                }
                assert any(isinstance(parent, ast.Await) and parent.value is call
                           for parent in ast.walk(node))
                matches.append(node.name)
    assert len(matches) == 1
    assert "background_tasks.add_task(run_matter_court_sync_job" not in ast.unparse(tree)
