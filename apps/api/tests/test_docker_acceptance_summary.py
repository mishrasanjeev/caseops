from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from sqlalchemy import select

from caseops_api.db.models import Company, Matter, ModelRun
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import docker_acceptance_summary as fixture
from caseops_api.scripts.docker_acceptance_case_provider import AcceptanceProviderHandler
from caseops_api.services import case_tracking_summary as summaries
from caseops_api.services.llm import MockProvider
from caseops_api.services.llm_cassette import CassetteMissError, CassetteProvider, cassette_key
from caseops_api.services.llm_types import LLMMessage
from caseops_api.workers import document_processor
from tests.test_auth_company import auth_headers, bootstrap_company


def _local_settings(**overrides):
    return SimpleNamespace(
        **{
            "database_url": "postgresql+psycopg://caseops:caseops@postgres:5432/caseops",
            "env": "e2e",
            "case_tracking_enabled": True,
            "case_tracking_provider": "ecourtsindia",
            "ecourtsindia_api_base_url": "http://acceptance-case-provider:8080",
            "ecourtsindia_api_token": "docker-acceptance-provider-token",
            "llm_provider": "mock",
            "llm_model": fixture.MODEL,
            "llm_api_key": None,
            **overrides,
        }
    )


@pytest.mark.parametrize(
    "override",
    [
        {"env": "production"},
        {"env": "local"},
        {"database_url": "postgresql://caseops:caseops@shared-db/caseops"},
        {"database_url": "postgresql://caseops:caseops@postgres/shared"},
        {"case_tracking_enabled": False},
        {"case_tracking_provider": "disabled"},
        {"ecourtsindia_api_base_url": "https://webapi.ecourtsindia.com"},
        {"ecourtsindia_api_token": "not-the-dummy-token"},
        {"llm_provider": "openai"},
        {"llm_model": "different-model"},
        {"llm_api_key": "must-never-be-present"},
    ],
)
def test_fixture_guard_rejects_nonisolated_runtime(monkeypatch, override):
    monkeypatch.setenv("CASEOPS_SUMMARY_ACCEPTANCE", "1")
    monkeypatch.setattr(fixture, "get_settings", lambda: _local_settings(**override))
    with pytest.raises(RuntimeError, match="isolated"):
        fixture.guard_local_runtime()


def test_fixture_guard_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("CASEOPS_SUMMARY_ACCEPTANCE", raising=False)
    monkeypatch.setattr(fixture, "get_settings", _local_settings)
    with pytest.raises(RuntimeError, match="isolated"):
        fixture.guard_local_runtime()
    monkeypatch.setenv("CASEOPS_SUMMARY_ACCEPTANCE", "1")
    fixture.guard_local_runtime()


def test_frozen_cassette_is_strict_and_cannot_fall_through(tmp_path):
    row = fixture.cassette_row()
    payload = summaries.SummaryPayload.model_validate_json(row["completion"]["text"])
    assert payload.concise_summary == fixture.GENERATED
    path = tmp_path / "summary.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    class Tripwire(MockProvider):
        def generate(self, *args, **kwargs):
            pytest.fail("Replay must never reach even the mock inner adapter.")

    provider = CassetteProvider(Tripwire(fixture.MODEL), path=path, mode="replay")
    update = summaries.TrackedCaseUpdate(
        update_type="new_order",
        title=fixture.SOURCE_TITLE,
        source_text=fixture.SOURCE_TEXT,
        source_text_truncated=False,
    )
    response = provider.generate(
        summaries._messages(summaries.TrackedCase(), update),
        temperature=0.1,
        max_tokens=1200,
    )
    assert response.text == row["completion"]["text"]
    with pytest.raises(CassetteMissError):
        provider.generate([LLMMessage(role="user", content="drift")])


def test_frozen_prompt_drift_is_not_silently_rerecorded(monkeypatch):
    monkeypatch.setattr(fixture, "SOURCE_TEXT", "Changed source")
    with pytest.raises(RuntimeError, match="prompt changed"):
        fixture.cassette_row()


def test_fixture_executes_installed_worker_not_consumer(monkeypatch, tmp_path):
    class Launched(Exception):
        pass

    captured = {}
    monkeypatch.setattr(sys, "argv", ["summary-fixture", "worker"])
    monkeypatch.setattr(fixture, "guard_local_runtime", lambda: None)
    monkeypatch.setattr(fixture.shutil, "which", lambda name: f"/installed/bin/{name}")
    monkeypatch.setattr(fixture.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(
        summaries, "drain_update_summaries", lambda **kw: pytest.fail("direct drain")
    )

    def execve(executable, argv, env):
        captured.update(executable=executable, argv=argv, env=env)
        raise Launched

    monkeypatch.setattr(fixture.os, "execve", execve)
    with pytest.raises(Launched):
        fixture.main()
    assert captured["executable"] == "/installed/bin/caseops-document-worker"
    assert captured["argv"] == [
        captured["executable"],
        "--once",
        "--skip-migrations",
        "--skip-maintenance",
        "--summary-batch-size",
        "25",
    ]
    assert captured["env"]["CASEOPS_LLM_CASSETTE_MODE"] == "replay"
    assert (
        json.loads(Path(captured["env"]["CASEOPS_LLM_CASSETTE_PATH"]).read_text())
        == fixture.cassette_row()
    )


@pytest.mark.parametrize("scenario", ["positive", "marked", "persistent_qa"])
def test_fixture_enqueues_canonical_source_and_retains_marker(
    client, monkeypatch, tmp_path, scenario
):
    boot = bootstrap_company(client)
    headers = auth_headers(boot["access_token"])
    assert client.get("/api/billing/current", headers=headers).status_code == 200
    created = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Summary acceptance",
            "matter_code": "SUM-001",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert created.status_code == 200, created.text
    matter_id = created.json()["id"]
    with get_session_factory()() as session:
        session.get(Company, boot["company"]["id"]).slug = (
            "summarypersistent-fixture"
            if scenario == "persistent_qa"
            else "summaryacceptance-fixture"
        )
        session.commit()
        original = session.get(Matter, matter_id)
        lifecycle = (original.status, original.is_active, original.lifecycle_version)
        seeded = fixture.seed(
            session, actor_id=boot["membership"]["id"], matter_id=matter_id, scenario=scenario
        )
        before = fixture.inspect_fixture(
            session, actor_id=seeded["actor_id"], update_id=seeded["update_id"]
        )
        assert before["summary"] == fixture.FALLBACK
        assert before["model_run_id"] is None
        assert before["event"]["no_paid_providers"] is (scenario == "marked")
        assert before["event"]["attempts"] == 0
        assert before["effects"] == before["runs"] == []
        assert before["provider_operations"] == before["spend_reservations"] == 0
        update = session.get(summaries.TrackedCaseUpdate, seeded["update_id"])
        assert fixture.FROZEN_CASSETTE_KEY == cassette_key(
            model=fixture.MODEL,
            temperature=0.1,
            max_tokens=1200,
            messages=summaries._messages(summaries.TrackedCase(), update),
        )
        session.rollback()
    if scenario != "positive":
        monkeypatch.setattr(
            summaries, "build_provider", lambda **kw: pytest.fail("blocked adapter build")
        )
    path = tmp_path / "summary.jsonl"
    path.write_text(json.dumps(fixture.cassette_row()) + "\n", encoding="utf-8")
    for name, value in {
        "CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS": "summarypersistent-fixture",
        "CASEOPS_LLM_PROVIDER": "mock",
        "CASEOPS_LLM_MODEL": fixture.MODEL,
        "CASEOPS_LLM_TEMPERATURE": "0.1",
        "CASEOPS_LLM_CASSETTE_MODE": "replay",
        "CASEOPS_LLM_CASSETTE_PATH": str(path),
    }.items():
        monkeypatch.setenv(name, value)
    # Match a separately launched worker; the persisted request marker and
    # configured tenant exclusion remain, and only offline replay is available.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    summaries.get_settings.cache_clear()
    try:
        assert document_processor.main(["--once", "--skip-migrations", "--skip-maintenance"]) == 0
        with get_session_factory()() as session:
            after = fixture.inspect_fixture(
                session, actor_id=seeded["actor_id"], update_id=seeded["update_id"]
            )
            if scenario == "positive":
                assert after["summary"] == fixture.GENERATED
                assert after["model_run_id"]
                assert after["runs"] == [
                    {
                        "id": after["model_run_id"],
                        "status": "ok",
                        "provider": "mock",
                        "model": fixture.MODEL,
                        "prompt_tokens": 80,
                        "completion_tokens": 40,
                    }
                ]
                assert after["effects"] == [
                    {
                        "state": "completed",
                        "result_type": "tracked_case_update",
                        "result_id": seeded["update_id"],
                    }
                ]
            else:
                assert after["effects"] == [
                    {
                        "state": "completed",
                        "result_type": "case_summary_suppressed",
                        "result_id": "automated_request"
                        if scenario == "marked"
                        else "automated_worker_or_tenant",
                    }
                ]
                assert after["model_run_id"] is None
                assert after["runs"] == []
            assert after["provider_operations"] == after["spend_reservations"] == 0
        assert document_processor.main(["--once", "--skip-migrations", "--skip-maintenance"]) == 0
        with get_session_factory()() as session:
            assert (
                fixture.inspect_fixture(
                    session,
                    actor_id=seeded["actor_id"],
                    update_id=seeded["update_id"],
                )
                == after
            )
    finally:
        summaries.get_settings.cache_clear()
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        assert (matter.status, matter.is_active, matter.lifecycle_version) == lifecycle
        assert len(list(session.scalars(select(ModelRun)))) == (1 if scenario == "positive" else 0)


def test_offline_emulator_serves_exact_authorized_source(monkeypatch):
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "docker-acceptance-provider-token")
    server = ThreadingHTTPServer(("127.0.0.1", 0), AcceptanceProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}{fixture.SOURCE_PATH}"
        with pytest.raises(HTTPError) as denied:
            urlopen(url, timeout=3)
        assert denied.value.code == 401
        request = Request(url, headers={"Authorization": "Bearer docker-acceptance-provider-token"})
        with urlopen(request, timeout=3) as response:
            assert response.status == 200
            assert response.read() == fixture.SOURCE_TEXT.encode()
            assert response.headers["Content-Type"] == "text/markdown; charset=utf-8"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
