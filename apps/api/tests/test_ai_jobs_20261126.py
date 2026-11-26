"""BUG-003: research answers, intelligent reviews and audit exports run in an
independent Cloud Run job, not in API BackgroundTasks.

Production bills the API per request (``--cpu-throttling``), so work queued
after a 202 only got CPU while other requests reached the same instance:
answer efea077b ran for nine minutes and crashed. These tests pin the
replacement contract: dispatch on create with a durable queued fallback, an
atomic claim on every dialect, lease recovery, the requester's persisted
no-paid marker restored in the worker, and idempotent research submission.
"""

from __future__ import annotations

import ast
import datetime
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.db.models import AuditExportJob, Recommendation, ResearchAnswer
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import audit_exports, document_dispatch, intelligent_reviews
from caseops_api.services import research_answers as answers_service
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_research_answers_20261124 import QUERY

NO_PAID = {"X-CaseOps-Automated-Test": "no-paid-providers"}
ANSWER_ROUTE = "caseops_api.api.routes.research_answers.run_research_answer_job"
REVIEW_ROUTE = "caseops_api.api.routes.intelligent_reviews.run_intelligent_review_job"


def _queue_answer(client, token, *, query=QUERY, headers=None, **extra) -> dict:
    response = client.post(
        "/api/research/answers",
        headers={**auth_headers(token), **(headers or {})},
        json={"query": query, **extra},
    )
    assert response.status_code == 202, response.text
    return response.json()


def _review_body(matter_id: str, report_id: str, authority_ids: list[str]) -> dict:
    return {
        "matter_id": matter_id,
        "source_research_report_id": report_id,
        "issue": "Does prior use support the trademark opposition?",
        "facts": [{"label": "First use", "value": "2018", "source_ref": "client note"}],
        "document_refs": ["client-note-v1"],
        "included_authority_ids": authority_ids,
    }


def _age(model, row_id: str, *, minutes: int, column: str = "created_at") -> None:
    with get_session_factory()() as session:
        row = session.get(model, row_id)
        setattr(row, column, getattr(row, column) - datetime.timedelta(minutes=minutes))
        session.commit()


# --------------------------------------------------------------------------- #
# Dispatch on create
# --------------------------------------------------------------------------- #


def _cloud_dispatch(monkeypatch, *, accepted: bool) -> list[dict]:
    real = document_dispatch.get_settings()
    settings = SimpleNamespace(
        env=real.env,
        gcp_project_id="perfect-period-305406",
        ai_job_dispatch_mode="cloud_run_job",
        ai_job_run_region="asia-south1",
        ai_job_run_job="caseops-ai-jobs",
    )
    monkeypatch.setattr(document_dispatch, "get_settings", lambda: settings)
    wakes: list[dict] = []

    async def wake(**kwargs):
        wakes.append(kwargs)
        return accepted

    monkeypatch.setattr(document_dispatch, "_wake_cloud_run_queue", wake)
    return wakes


@pytest.mark.parametrize("accepted", [True, False])
def test_production_answer_wakes_the_ai_job_and_never_runs_after_the_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    wakes = _cloud_dispatch(monkeypatch, accepted=accepted)
    token = bootstrap_company(client)["access_token"]
    created = _queue_answer(client, token)
    assert wakes == [
        {"project": "perfect-period-305406", "region": "asia-south1", "job": "caseops-ai-jobs"}
    ]
    # TestClient runs BackgroundTasks before returning, so a queued row proves
    # nothing ran in the API process; a refused wake keeps it for the scheduler.
    read = client.get(f"/api/research/answers/{created['id']}", headers=auth_headers(token))
    assert read.json()["status"] == "queued"


def test_production_review_and_export_wake_the_ai_job_and_stay_queued(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_intelligent_reviews import _setup

    wakes = _cloud_dispatch(monkeypatch, accepted=False)
    bootstrap, matter_id, report_id, authority_ids, _ = _setup(client)
    token = str(bootstrap["access_token"])
    review = client.post(
        "/api/research/reviews",
        headers=auth_headers(token),
        json=_review_body(matter_id, report_id, authority_ids),
    )
    assert review.status_code == 202, review.text
    export = client.post(
        "/api/admin/audit/export/async", headers=auth_headers(token), json={"format": "jsonl"}
    )
    assert export.status_code == 202, export.text
    assert [wake["job"] for wake in wakes] == ["caseops-ai-jobs", "caseops-ai-jobs"]
    with get_session_factory()() as session:
        assert session.get(Recommendation, review.json()["id"]).review_state == "queued"
        assert session.get(AuditExportJob, export.json()["id"]).status == "pending"


# --------------------------------------------------------------------------- #
# Idempotent research submission
# --------------------------------------------------------------------------- #


def test_duplicate_in_flight_research_submission_returns_the_same_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[str] = []
    monkeypatch.setattr(ANSWER_ROUTE, runs.append)
    token = bootstrap_company(client)["access_token"]
    first = _queue_answer(client, token)
    respelled = "  " + QUERY.upper().replace(" ", "   \n ") + "  "
    second = _queue_answer(client, token, query=respelled)
    assert second["id"] == first["id"]
    assert runs == [first["id"]]

    # A different matter context is a different question.
    from tests.test_intelligent_reviews import _create_matter

    matter_id = _create_matter(client, token, code="AIJOB-IDEM-1")
    scoped = _queue_answer(client, token, context_matter_id=matter_id)
    assert scoped["id"] != first["id"]

    # Once the first answer is no longer in flight, the same question is new.
    _age(ResearchAnswer, first["id"], minutes=11)
    fresh = _queue_answer(client, token)
    assert fresh["id"] not in {first["id"], scoped["id"]}
    with get_session_factory()() as session:
        company_id = session.get(ResearchAnswer, first["id"]).company_id
        count = session.scalar(
            select(func.count()).select_from(ResearchAnswer).where(
                ResearchAnswer.company_id == company_id
            )
        )
    assert count == 3
    assert runs == [first["id"], scoped["id"], fresh["id"]]


# --------------------------------------------------------------------------- #
# Worker-side no-paid restore
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("marked", [True, False])
def test_the_worker_restores_the_persisted_no_paid_marker_for_answers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, marked: bool
) -> None:
    monkeypatch.setattr(ANSWER_ROUTE, lambda _id: None)
    token = bootstrap_company(client)["access_token"]
    marker = NO_PAID if marked else None
    created = _queue_answer(client, token, headers=marker)
    observed: list[bool] = []

    def record(session, answer):
        observed.append(paid_providers_blocked_for_request())
        answers_service._finish(session, answer, state="failed", error_code="internal_error")

    monkeypatch.setattr(answers_service, "_run", record)
    # The worker has no request: only the queued row can carry the marker.
    assert paid_providers_blocked_for_request() is False
    assert answers_service.run_research_answer_job(created["id"]) is True
    assert observed == [marked]
    assert paid_providers_blocked_for_request() is False


@pytest.mark.parametrize("marked", [True, False])
def test_the_worker_restores_the_persisted_no_paid_marker_for_reviews(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, marked: bool
) -> None:
    from tests.test_intelligent_reviews import _setup

    monkeypatch.setattr(REVIEW_ROUTE, lambda _id: None)
    bootstrap, matter_id, report_id, authority_ids, _ = _setup(client)
    token = str(bootstrap["access_token"])
    response = client.post(
        "/api/research/reviews",
        headers={**auth_headers(token), **(NO_PAID if marked else {})},
        json=_review_body(matter_id, report_id, authority_ids),
    )
    assert response.status_code == 202, response.text
    observed: list[bool] = []
    original = intelligent_reviews._load_report

    def record(*args, **kwargs):
        observed.append(paid_providers_blocked_for_request())
        return original(*args, **kwargs)

    monkeypatch.setattr(intelligent_reviews, "_load_report", record)
    monkeypatch.setattr(
        intelligent_reviews, "build_provider",
        lambda *a, **k: pytest.fail("the marker test must stop before generation"),
    )
    monkeypatch.setattr(intelligent_reviews, "_source_documents", lambda *a, **k: [])
    assert paid_providers_blocked_for_request() is False
    intelligent_reviews.run_intelligent_review_job(response.json()["id"])
    assert observed and set(observed) == {marked}
    assert paid_providers_blocked_for_request() is False


# --------------------------------------------------------------------------- #
# Atomic claim
# --------------------------------------------------------------------------- #


def _interleave(table: str, second_executor):
    """Run ``second_executor`` just before the first executor's claim write.

    Both executors have then read the row as runnable. SQLite ignores
    ``FOR UPDATE``, so only a compare-and-set write keeps one winner.
    """
    engine = get_engine()
    state = {"fired": False}

    def before(_conn, _cursor, statement, *_args):
        if not state["fired"] and statement.lstrip().upper().startswith(f"UPDATE {table}"):
            state["fired"] = True
            second_executor()

    def remove() -> None:
        event.remove(engine, "before_cursor_execute", before)
        assert state["fired"], "the interleaving never reached a claim write"

    event.listen(engine, "before_cursor_execute", before)
    return remove


def test_concurrent_executors_run_a_research_answer_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ANSWER_ROUTE, lambda _id: None)
    token = bootstrap_company(client)["access_token"]
    answer_id = _queue_answer(client, token)["id"]
    runs: list[str] = []

    def run(session, answer):
        runs.append(answer.id)
        answers_service._finish(session, answer, state="failed", error_code="internal_error")

    monkeypatch.setattr(answers_service, "_run", run)
    remove = _interleave("RESEARCH_ANSWERS",
                         lambda: answers_service.run_research_answer_job(answer_id))
    try:
        answers_service.run_research_answer_job(answer_id)
    finally:
        remove()
    assert runs == [answer_id]


def test_concurrent_executors_generate_an_intelligent_review_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_intelligent_reviews import StaticReviewProvider, _review_payload, _setup

    monkeypatch.setattr(REVIEW_ROUTE, lambda _id: None)
    bootstrap, matter_id, report_id, authority_ids, passages = _setup(client)
    token = str(bootstrap["access_token"])
    review_id = client.post(
        "/api/research/reviews",
        headers=auth_headers(token),
        json=_review_body(matter_id, report_id, authority_ids),
    ).json()["id"]
    provider = StaticReviewProvider(_review_payload(authority_ids, passages))
    remove = _interleave(
        "RECOMMENDATIONS",
        lambda: intelligent_reviews.run_intelligent_review_job(review_id, provider=provider),
    )
    try:
        intelligent_reviews.run_intelligent_review_job(review_id, provider=provider)
    finally:
        remove()
    assert provider.called == 1


def test_concurrent_executors_write_an_audit_export_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("caseops_api.api.routes.admin.run_export_job", lambda _id: None)
    token = bootstrap_company(client)["access_token"]
    job_id = client.post(
        "/api/admin/audit/export/async", headers=auth_headers(token), json={"format": "jsonl"}
    ).json()["id"]
    writes: list[str] = []

    def persist(**kwargs):
        writes.append(kwargs["attachment_id"])
        return SimpleNamespace(storage_key=f"exports/{kwargs['attachment_id']}", size_bytes=1)

    monkeypatch.setattr(audit_exports, "persist_workspace_attachment", persist)
    remove = _interleave("AUDIT_EXPORT_JOBS", lambda: audit_exports.run_export_job(job_id))
    try:
        audit_exports.run_export_job(job_id)
    finally:
        remove()
    assert writes == [job_id]
    with get_session_factory()() as session:
        assert session.get(AuditExportJob, job_id).status == "completed"


def test_a_stale_queued_answer_is_never_claimed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ANSWER_ROUTE, lambda _id: None)
    token = bootstrap_company(client)["access_token"]
    answer_id = _queue_answer(client, token)["id"]
    _age(ResearchAnswer, answer_id, minutes=11)
    monkeypatch.setattr(answers_service, "_run", lambda *_: pytest.fail("stale answer ran"))
    assert answers_service.run_research_answer_job(answer_id) is False
    with get_session_factory()() as session:
        assert session.get(ResearchAnswer, answer_id).status == "queued"


# --------------------------------------------------------------------------- #
# Drain and lease recovery
# --------------------------------------------------------------------------- #


def test_the_drain_runs_queued_answers_oldest_first_within_its_bound(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caseops_api.services import ai_jobs

    monkeypatch.setattr(ANSWER_ROUTE, lambda _id: None)
    token = bootstrap_company(client)["access_token"]
    ids = [_queue_answer(client, token, query=f"{QUERY} Variant {n}.")["id"] for n in range(3)]
    ran: list[str] = []

    def run(session, answer):
        ran.append(answer.id)
        answers_service._finish(session, answer, state="abstained", error_code="no_sources")

    monkeypatch.setattr(answers_service, "_run", run)
    outcomes: dict[str, int] = {}
    assert ai_jobs.drain_ai_jobs(limit=2, outcomes=outcomes) == 2
    assert ran == ids[:2] and outcomes == {"completed": 2}
    # Claims stop once the claim window has elapsed.
    ticks = iter([0.0, ai_jobs.CLAIM_WINDOW_SECONDS])
    assert ai_jobs.drain_ai_jobs(limit=2, clock=lambda: next(ticks)) == 0
    assert ran == ids[:2]
    assert ai_jobs.drain_ai_jobs(limit=2) == 1 and ran == ids
    with pytest.raises(ValueError):
        ai_jobs.drain_ai_jobs(limit=11)


def test_recovery_settles_work_whose_executor_is_gone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caseops_api.services import ai_jobs
    from tests.test_intelligent_reviews import _setup

    monkeypatch.setattr(ANSWER_ROUTE, lambda _id: None)
    monkeypatch.setattr(REVIEW_ROUTE, lambda _id: None)
    monkeypatch.setattr("caseops_api.api.routes.admin.run_export_job", lambda _id: None)
    bootstrap, matter_id, report_id, authority_ids, _ = _setup(client)
    token = str(bootstrap["access_token"])
    stale_answer = _queue_answer(client, token)["id"]
    live_answer = _queue_answer(client, token, query=f"{QUERY} Second.")["id"]
    review_id = client.post(
        "/api/research/reviews", headers=auth_headers(token),
        json=_review_body(matter_id, report_id, authority_ids),
    ).json()["id"]
    export_id = client.post(
        "/api/admin/audit/export/async", headers=auth_headers(token), json={"format": "csv"}
    ).json()["id"]
    with get_session_factory()() as session:
        session.get(Recommendation, review_id).review_state = "running"
        job = session.get(AuditExportJob, export_id)
        job.status = "running"
        job.started_at = datetime.datetime.now(datetime.UTC)
        session.commit()
    _age(ResearchAnswer, stale_answer, minutes=11)

    # Inside the lease nothing but the stale answer is touched.
    assert ai_jobs.recover_stale_ai_jobs(limit=3) == 1
    with get_session_factory()() as session:
        assert session.get(Recommendation, review_id).review_state == "running"
        assert session.get(AuditExportJob, export_id).status == "running"

    _age(Recommendation, review_id, minutes=16, column="updated_at")
    _age(AuditExportJob, export_id, minutes=16, column="started_at")
    assert ai_jobs.recover_stale_ai_jobs(limit=3) == 2
    with get_session_factory()() as session:
        answer = session.get(ResearchAnswer, stale_answer)
        assert (answer.status, answer.error_code) == ("failed", "timed_out")
        assert session.get(ResearchAnswer, live_answer).status == "queued"
        review = session.get(Recommendation, review_id)
        assert (review.review_state, review.review_error_code) == ("failed", "timed_out")
        export = session.get(AuditExportJob, export_id)
        assert export.status == "failed" and export.error
    assert ai_jobs.recover_stale_ai_jobs(limit=3) == 0


# --------------------------------------------------------------------------- #
# Worker CLI admission
# --------------------------------------------------------------------------- #


def _settings(**overrides):
    return SimpleNamespace(**({
        "ai_job_worker_admission_protocol_version": 1,
        "ai_job_worker_admission_enabled": True,
        "ai_job_worker_batch_size": 3,
    } | overrides))


@pytest.fixture
def worker(monkeypatch):
    from caseops_api.db import migrations
    from caseops_api.workers import ai_jobs as module

    monkeypatch.setattr(
        migrations, "run_migrations", lambda: pytest.fail("AI executor must never migrate")
    )
    return module


@pytest.mark.parametrize("protocol, admission", [
    (0, True), (None, True), (2, True), (True, True), ("1", True),
    (1, None), (1, "true"), (1, 1), (1, 0),
])
def test_invalid_admission_configuration_fails_before_sql(worker, monkeypatch, protocol,
                                                          admission):
    monkeypatch.setattr(worker, "get_settings", lambda: _settings(
        ai_job_worker_admission_protocol_version=protocol,
        ai_job_worker_admission_enabled=admission,
    ))
    monkeypatch.setattr(answers_service, "get_session_factory",
                        lambda: pytest.fail("SQL before admission"))
    with pytest.raises(SystemExit) as error:
        worker.main(["--once", "--skip-migrations"])
    assert error.value.code == 2


@pytest.mark.parametrize("args", [[], ["--batch-size=3"], ["--once", "--batch-size=0"],
                                  ["--once", "--batch-size=11"], ["--once", "--batch-size=x"]])
def test_cli_rejects_continuous_or_unbounded_work(worker, monkeypatch, args):
    monkeypatch.setattr(worker, "get_settings", _settings)
    with pytest.raises(SystemExit) as error:
        worker.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize("args, enabled", [
    (["--once"], False), (["--once", "--skip-migrations"], False),
    (["--once", "--admission-disabled"], True),
])
def test_disabled_admission_does_no_work_and_prints_a_zero_receipt(
    worker, monkeypatch, capsys, args, enabled,
):
    from caseops_api.services import ai_jobs

    monkeypatch.setattr(worker, "get_settings",
                        lambda: _settings(ai_job_worker_admission_enabled=enabled))
    monkeypatch.setattr(ai_jobs, "recover_stale_ai_jobs", lambda **_: pytest.fail("worked"))
    monkeypatch.setattr(ai_jobs, "drain_ai_jobs", lambda **_: pytest.fail("worked"))
    assert worker.main(args) == 0
    assert capsys.readouterr().out == (
        "CaseOps AI job worker: admission_protocol=1 admission=disabled "
        "recovered=0 attempted=0 completed=0 failed=0 unfinalized=0\n"
    )


def test_enabled_worker_recovers_then_drains_one_bounded_batch(worker, monkeypatch, capsys):
    from caseops_api.services import ai_jobs

    monkeypatch.setattr(worker, "get_settings", _settings)
    calls = []
    monkeypatch.setattr(ai_jobs, "recover_stale_ai_jobs",
                        lambda **kw: calls.append(("recover", kw)) or 1)

    def drain(*, limit, outcomes):
        calls.append(("drain", {"limit": limit}))
        outcomes.update(completed=1, failed=1)
        return 2

    monkeypatch.setattr(ai_jobs, "drain_ai_jobs", drain)
    assert worker.main(["--once", "--batch-size=2", "--skip-migrations"]) == 0
    assert calls == [("recover", {"limit": 2}), ("drain", {"limit": 2})]
    assert capsys.readouterr().out == (
        "CaseOps AI job worker: admission_protocol=1 admission=enabled "
        "recovered=1 attempted=2 completed=1 failed=1 unfinalized=0\n"
    )


def test_worker_console_entry_and_import_boundary():
    from caseops_api.workers import ai_jobs as module

    api = Path(__file__).resolve().parents[1]
    config = tomllib.loads((api / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["scripts"]["caseops-ai-job-worker"] == (
        "caseops_api.workers.ai_jobs:main"
    )
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imports == {"__future__", "caseops_api.core.settings", "caseops_api.services.ai_jobs"}


def test_the_cloud_job_environment_strings_start_the_worker(monkeypatch, capsys):
    """Cloud Run passes CASEOPS_AI_JOB_WORKER_ADMISSION_PROTOCOL_VERSION as "1".

    The Docker offline-startup gate caught the AI job worker crashing at
    Settings() on that string while the document and court sync workers
    accepted it; every unit test above passed integers.
    """
    from caseops_api.core.settings import get_settings
    from caseops_api.workers import ai_jobs as module

    monkeypatch.setenv("CASEOPS_AI_JOB_WORKER_ADMISSION_PROTOCOL_VERSION", "1")
    monkeypatch.setenv("CASEOPS_AI_JOB_WORKER_ADMISSION_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert module.main(["--once", "--skip-migrations"]) == 0
    finally:
        get_settings.cache_clear()
    assert "admission_protocol=1 admission=disabled" in capsys.readouterr().out
