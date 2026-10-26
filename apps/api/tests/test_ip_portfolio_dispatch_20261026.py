from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from caseops_api.api.routes import portfolio_export_worker as route
from caseops_api.core.csrf import CSRFMiddleware
from caseops_api.core.settings import Settings, get_settings
from caseops_api.services import document_storage
from caseops_api.services import ip_portfolio_dispatch as dispatch

SECRET = "dedicated-export-worker-secret-20261026-not-jwt"
JOB = "53e2add5-a74c-45ac-a1a0-b59198cf877b"
PATH = "/api/internal/portfolio-exports/run"


@pytest.fixture
def worker_client(monkeypatch):
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_PORTFOLIO_EXPORT_WORKER_SECRET", SECRET)
    get_settings.cache_clear()
    application = FastAPI()
    application.add_middleware(CSRFMiddleware)
    application.include_router(route.router, prefix="/api/internal/portfolio-exports")

    @application.get("/probe")
    async def probe():
        return {"thread": threading.get_ident(), "ok": True}

    @application.post("/api/internal/portfolio-exports/other")
    async def sibling():
        raise AssertionError("Sibling CSRF boundary was bypassed")

    with TestClient(application) as client:
        yield client


def signed(body: bytes, *, timestamp: str | None = None, secret: str = SECRET):
    timestamp = timestamp or str(int(time.time()))
    return {
        **dispatch.NO_PAID_HEADERS,
        "Content-Type": "application/json",
        "X-CaseOps-Export-Timestamp": timestamp,
        "X-CaseOps-Export-Signature": dispatch.portfolio_export_signature(
            secret=secret, timestamp=timestamp, body=body
        ),
    }


def body(**extra):
    return json.dumps({"version": 1, "job_id": JOB, **extra}, separators=(",", ":")).encode()


def test_callback_awaits_durable_completion_off_loop_and_probe_remains_responsive(
    worker_client, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    threads = []

    def run(job):
        assert job == JOB
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(5), "Test did not release its bounded storage barrier"
        return "completed"

    monkeypatch.setattr(route, "run_portfolio_export_job", run)
    payload = body()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker_client.post, PATH, content=payload, headers=signed(payload))
        try:
            assert started.wait(5)
            assert not future.done(), "Task acknowledged before durable worker completion"
            before = time.monotonic()
            probe = worker_client.get("/probe")
            assert time.monotonic() - before < 1
            assert probe.status_code == 200 and probe.json()["ok"]
            assert threads[0] != probe.json()["thread"]
        finally:
            release.set()
        response = future.result(timeout=5)
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "status": "completed"}
    assert PATH not in worker_client.app.openapi()["paths"]


@pytest.mark.parametrize(
    "outcome,expected",
    [("busy", 409), ("terminal", 200), ("missing", 200), ("completed", 200), ("unknown", 503)],
)
def test_callback_returns_durable_outcome_without_inventing_completion(
    worker_client, monkeypatch, outcome, expected
):
    run = Mock(return_value=outcome)
    monkeypatch.setattr(route, "run_portfolio_export_job", run)
    payload = body()
    assert (
        worker_client.post(PATH, content=payload, headers=signed(payload)).status_code == expected
    )
    run.assert_called_once_with(JOB)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "stale", "future", "tampered-body", "wrong-key", "missing-marker", "bad-signature"],
)
def test_callback_authentication_fails_before_worker(worker_client, monkeypatch, mutation):
    run = Mock(side_effect=AssertionError("Unauthorized task reached worker"))
    monkeypatch.setattr(route, "run_portfolio_export_job", run)
    payload = body()
    headers = signed(payload)
    if mutation == "missing":
        headers = {**dispatch.NO_PAID_HEADERS, "Authorization": "Bearer browser-or-admin-jwt"}
    elif mutation in {"stale", "future"}:
        headers = signed(
            payload, timestamp=str(int(time.time()) + (301 if mutation == "future" else -301))
        )
    elif mutation == "tampered-body":
        payload += b" "
    elif mutation == "wrong-key":
        headers = signed(payload, secret="another-machine-readiness-or-jwt-key")
    elif mutation == "missing-marker":
        headers.pop("X-CaseOps-Automated-Test")
    else:
        headers["X-CaseOps-Export-Signature"] = "not-a-signature"
    headers["Cookie"] = "caseops_csrf=browser-cookie"
    assert worker_client.post(PATH, content=payload, headers=headers).status_code == 401
    run.assert_not_called()


@pytest.mark.parametrize(
    "payload,expected",
    [
        (b"", 413),
        (b"x" * 1025, 413),
        (b"{", 422),
        (body(unexpected=True), 422),
        (body(job_id="invented"), 422),
    ],
)
def test_callback_body_is_bounded_strict_and_not_logged(
    worker_client, monkeypatch, caplog, payload, expected
):
    run = Mock()
    monkeypatch.setattr(route, "run_portfolio_export_job", run)
    assert (
        worker_client.post(PATH, content=payload, headers=signed(payload)).status_code == expected
    )
    run.assert_not_called()
    assert SECRET not in caplog.text
    if payload:
        assert payload.decode(errors="ignore") not in caplog.text


def test_worker_key_is_required_and_sibling_csrf_not_exempted(worker_client, monkeypatch):
    monkeypatch.delenv("CASEOPS_PORTFOLIO_EXPORT_WORKER_SECRET")
    get_settings.cache_clear()
    payload = body()
    assert worker_client.post(PATH, content=payload, headers=signed(payload)).status_code == 503
    assert worker_client.post("/api/internal/portfolio-exports/other", json={}).status_code == 403


def test_worker_key_cannot_reuse_browser_or_other_machine_authority():
    auth = "independent-test-auth-key-at-least-32-bytes"
    with pytest.raises(ValidationError, match="dedicated key"):
        Settings(env="local", auth_secret=auth, portfolio_export_worker_secret=auth)
    with pytest.raises(ValidationError, match="dedicated key"):
        Settings(
            env="local",
            auth_secret=auth,
            machine_readiness_evidence_secret=SECRET,
            portfolio_export_worker_secret=SECRET,
        )
    with pytest.raises(ValidationError, match="canonical HTTPS"):
        Settings(
            env="local",
            portfolio_export_task_url="https://example.com/api/internal/portfolio-exports/run",
        )


def test_machine_body_read_cannot_hold_request_cpu_without_a_finite_deadline(
    worker_client,
    monkeypatch,
):
    from starlette.requests import Request

    assert route.TASK_BODY_SECONDS == 3.0
    monkeypatch.setattr(route, "TASK_BODY_SECONDS", 0.01)
    payload = body()
    headers = signed(payload)

    async def slow_body():
        await asyncio.sleep(1)
        return {"type": "http.request", "body": payload, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": PATH,
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        },
        receive=slow_body,
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            route.require_export_task(
                request,
                timestamp=headers["X-CaseOps-Export-Timestamp"],
                signature=headers["X-CaseOps-Export-Signature"],
            )
        )
    assert error.value.status_code == 408


def cloud_mode(monkeypatch):
    monkeypatch.setenv("CASEOPS_ENV", "cloud")
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "independent-test-auth-key-at-least-32-bytes")
    monkeypatch.setenv("CASEOPS_GCP_PROJECT_ID", "perfect-period-305406")
    monkeypatch.setenv("CASEOPS_PORTFOLIO_EXPORT_DISPATCH_MODE", "cloud_tasks")
    monkeypatch.setenv("CASEOPS_PORTFOLIO_EXPORT_WORKER_SECRET", SECRET)
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "outcome", ["accepted", "denied", "lost-ack", "oversized-token", "invalid-token", "timeout"]
)
def test_actual_dispatch_constructors_are_marked_bounded_nonretrying_and_outside_transaction(
    monkeypatch, outcome, caplog
):
    cloud_mode(monkeypatch)
    calls = []
    real_client = httpx.AsyncClient
    engine = create_engine("sqlite+pysqlite://")
    with Session(engine) as session:
        session.execute(text("SELECT 1"))
        assert session.in_transaction()

        async def handler(request):
            assert not session.in_transaction()
            calls.append(request)
            assert request.headers["X-CaseOps-Automated-Test"] == "no-paid-providers"
            if len(calls) == 1:
                assert request.method == "GET" and request.url.host == "metadata.google.internal"
                assert request.headers["Metadata-Flavor"] == "Google"
                if outcome == "oversized-token":
                    return httpx.Response(200, content=b"x" * 16_385)
                return httpx.Response(
                    200,
                    json={
                        "access_token": "bad\nvalue"
                        if outcome == "invalid-token"
                        else "synthetic-token"
                    },
                )
            assert request.method == "POST" and request.url.host == "cloudtasks.googleapis.com"
            assert (
                request.url.path
                == "/v2/projects/perfect-period-305406/locations/asia-south1/queues/"
                "caseops-portfolio-exports/tasks"
            )
            task = json.loads(request.content)["task"]
            assert task["dispatchDeadline"] == "120s"
            callback = task["httpRequest"]
            assert callback["url"] == "https://api.caseops.ai" + PATH
            assert callback["httpMethod"] == "POST"
            assert callback["headers"]["X-CaseOps-Automated-Test"] == "no-paid-providers"
            raw = base64.b64decode(callback["body"], validate=True)
            assert raw == body()
            assert callback["headers"][
                "X-CaseOps-Export-Signature"
            ] == dispatch.portfolio_export_signature(
                secret=SECRET, timestamp=callback["headers"]["X-CaseOps-Export-Timestamp"], body=raw
            )
            assert set(task) == {"httpRequest", "dispatchDeadline"}
            if outcome == "lost-ack":
                raise httpx.ReadTimeout("acknowledgment unknown", request=request)
            if outcome == "timeout":
                await asyncio.sleep(1)
            return httpx.Response(
                403 if outcome == "denied" else 201, json={"name": "synthetic-task"}
            )

        def client_factory(**kwargs):
            assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(dispatch.httpx, "AsyncClient", client_factory)
        if outcome == "timeout":
            monkeypatch.setattr(dispatch, "DISPATCH_BUDGET_SECONDS", 0.05)
        background = BackgroundTasks()
        result = asyncio.run(
            dispatch.dispatch_portfolio_export(
                session=session, background_tasks=background, job_id=JOB
            )
        )
        assert result is (outcome == "accepted")
        assert not background.tasks and not session.in_transaction()
    engine.dispose()
    assert len(calls) == (1 if outcome in {"oversized-token", "invalid-token"} else 2)
    assert SECRET not in caplog.text and "synthetic-token" not in caplog.text


def test_only_local_background_is_allowed_and_dispatch_preserves_budget(monkeypatch):
    assert dispatch.DISPATCH_BUDGET_SECONDS == 3
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_PORTFOLIO_EXPORT_DISPATCH_MODE", "local_background")
    get_settings.cache_clear()
    background = BackgroundTasks()
    with Session(create_engine("sqlite+pysqlite://")) as session:
        assert asyncio.run(
            dispatch.dispatch_portfolio_export(
                session=session, background_tasks=background, job_id=JOB
            )
        )
    assert len(background.tasks) == 1 and background.tasks[0].args == (JOB,)
    cloud_mode(monkeypatch)
    monkeypatch.setenv("CASEOPS_PORTFOLIO_EXPORT_DISPATCH_MODE", "local_background")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as error:
        dispatch.require_portfolio_export_dispatch_ready()
    assert error.value.status_code == 503


def test_export_storage_timeout_is_opt_in_and_has_no_mutation_retry(monkeypatch):
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET", "synthetic-export-bucket")
    get_settings.cache_clear()
    blob = Mock()
    blob.upload_from_filename.side_effect = lambda filename, **kwargs: Path(filename).is_file() or (
        _ for _ in ()
    ).throw(AssertionError("Missing staged bytes"))
    cloud = Mock()
    cloud.bucket.return_value.blob.return_value = blob
    monkeypatch.setattr(document_storage, "_gcs_client", lambda: cloud)
    for deadline in (None, 10.0):
        document_storage.persist_workspace_attachment(
            company_id=str(uuid4()),
            workspace_id="ip-portfolio-exports",
            attachment_id=str(uuid4()),
            filename="export.csv",
            namespace="exports",
            stream=io.BytesIO(b"Mark\r\nExample\r\n"),
            storage_timeout_seconds=deadline,
        )
        assert blob.upload_from_filename.call_args.kwargs == (
            {} if deadline is None else {"timeout": 10.0, "retry": None}
        )


@pytest.mark.parametrize("deadline", [0, -1, 60.01])
def test_invalid_storage_timeout_fails_before_staging(monkeypatch, deadline):
    stage = Mock(side_effect=AssertionError("Invalid deadline staged bytes"))
    monkeypatch.setattr(document_storage, "_write_stream_to_temp_file", stage)
    with pytest.raises(ValueError, match="timeout"):
        document_storage.persist_workspace_attachment(
            company_id="tenant",
            workspace_id="exports",
            attachment_id="job",
            filename="export.csv",
            stream=io.BytesIO(b"data"),
            storage_timeout_seconds=deadline,
        )
    stage.assert_not_called()


@pytest.mark.postgres
def test_real_http_admission_task_callback_and_exact_export_on_postgres(client, monkeypatch):
    from sqlalchemy import func, select

    from caseops_api.db.models import AuditEvent, IpPortfolioExportJob
    from caseops_api.db.session import get_session_factory
    from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture

    headers, _docket, _application = _rich_portfolio_fixture(client)
    headers = {**headers, **dispatch.NO_PAID_HEADERS}
    original_auth_secret = get_settings().auth_secret
    cloud_mode(monkeypatch)
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", original_auth_secret)
    get_settings.cache_clear()
    captured = []
    real_client = httpx.AsyncClient

    async def receive(request):
        assert request.headers["X-CaseOps-Automated-Test"] == "no-paid-providers"
        if request.url.host == "metadata.google.internal":
            return httpx.Response(200, json={"access_token": "synthetic-metadata-token"})
        assert request.url.host == "cloudtasks.googleapis.com" and request.method == "POST"
        captured.append(json.loads(request.content)["task"]["httpRequest"])
        return httpx.Response(200, json={"name": "synthetic-durable-task"})

    monkeypatch.setattr(
        dispatch.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(receive), **kwargs),
    )
    payload = {
        "format": "csv",
        "filters": {"jurisdiction": ["IN"]},
        "columns": ["mark", "application_numbers", "opposition_numbers", "provenance"],
        "row_limit": 50000,
    }
    preview = client.post("/api/ip/portfolio/exports/preview", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    admitted = client.post(
        "/api/ip/portfolio/exports",
        headers=headers,
        json={**payload, "preview_token": preview.json()["preview_token"]},
    )
    assert admitted.status_code == 202, admitted.text
    job_id = admitted.json()["id"]
    assert len(captured) == 1
    assert (
        client.get(f"/api/ip/portfolio/exports/{job_id}", headers=headers).json()["status"]
        == "pending"
    )
    callback = captured[0]
    raw = base64.b64decode(callback["body"], validate=True)
    assert json.loads(raw) == {"version": 1, "job_id": job_id}
    completed = client.post(PATH, headers=callback["headers"], content=raw)
    assert completed.status_code == 200, completed.text
    assert completed.json() == {"accepted": True, "status": "completed"}
    replayed = client.post(PATH, headers=callback["headers"], content=raw)
    assert replayed.status_code == 200 and replayed.json()["status"] == "completed"
    record = client.get(f"/api/ip/portfolio/exports/{job_id}", headers=headers).json()
    assert record["status"] == "completed" and record["row_count"] == 1 and record["download_ready"]
    downloaded = client.get(f"/api/ip/portfolio/exports/{job_id}/download", headers=headers)
    assert (
        downloaded.status_code == 200 and downloaded.headers["cache-control"] == "private, no-store"
    )
    csv = downloaded.content.decode("utf-8-sig")
    assert "Application numbers" in csv and "TM / 2026 / 00421" in csv
    assert "OPP / 88 / 2026" in csv and "CaseOps legal record" in csv
    with get_session_factory()() as session:
        job = session.get(IpPortfolioExportJob, job_id)
        assert job.dispatch_protocol_version == 1 and job.status == "completed"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.target_id == job_id,
                    AuditEvent.action == "ip_portfolio.export.completed",
                )
            )
            == 1
        )
    assert len(captured) == 1, "Callback replay must not enqueue another task"
