from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml
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
        updates_response = client.get(
            f"/api/case-tracking/bookmarks/{seeded['bookmark_id']}/updates",
            headers=headers,
        )
        assert updates_response.status_code == 200, updates_response.text
        assert updates_response.json()["updates"][0]["id"] == seeded["update_id"]
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


def _batch_identities(*, seeded=False):
    items = []
    for index, scenario in enumerate(("positive", "marked", "persistent_qa")):
        item = {"company_id": f"company-{index}", "actor_id": f"actor-{index}",
                "matter_id": f"matter-{index}", "scenario": scenario}
        if seeded:
            item.update(bookmark_id=f"bookmark-{index}", update_id=f"update-{index}")
        items.append(item)
    return items


def test_cleanup_regression_is_required_by_standard_ci():
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["web"]
    selected = [step for step in job["steps"]
                if step.get("name") == "Docker summary fixture and cleanup unit regressions"]
    assert len(selected) == 1
    assert selected[0]["run"] == (
        "node --experimental-strip-types --test scripts/summary-fixture-support.test.mjs"
    )
    assert "if" not in selected[0] and not selected[0].get("continue-on-error", False)
    assert "if" not in job and not job.get("continue-on-error", False)
    assert (root / "scripts/summary-fixture-support.test.mjs").is_file()


def _read_batch(items, command="seed-inspect-many"):
    return fixture.read_batch(io.BytesIO(json.dumps({"items": items}).encode()), command=command)


@pytest.mark.parametrize("command", ["seed-inspect-many", "inspect-many"])
def test_batch_input_accepts_exact_bounded_identities(command):
    identities = _batch_identities(seeded=command == "inspect-many")
    assert _read_batch(identities, command) == identities


@pytest.mark.parametrize("field", sorted(fixture.INSPECT_FIELDS))
def test_batch_input_rejects_duplicate_identities(field):
    identities = _batch_identities(seeded=True)
    identities[1][field] = identities[0][field]
    with pytest.raises(ValueError, match="Duplicate summary batch"):
        _read_batch(identities, "inspect-many")


@pytest.mark.parametrize("field", sorted(fixture.INSPECT_FIELDS))
def test_batch_input_rejects_missing_fields(field):
    identities = _batch_identities(seeded=True)
    del identities[1][field]
    with pytest.raises(ValueError, match="missing or unexpected"):
        _read_batch(identities, "inspect-many")


@pytest.mark.parametrize("items", [[], [None], "not-a-list", _batch_identities() + [{}]])
def test_batch_input_rejects_invalid_or_oversize_inventory(items):
    with pytest.raises(ValueError):
        _read_batch(items)


@pytest.mark.parametrize("value", [None, True, 1, "", "x" * 37, ["actor"]])
def test_batch_input_rejects_unbounded_or_nonstring_values(value):
    identities = _batch_identities()
    identities[0]["actor_id"] = value
    with pytest.raises(ValueError, match="bounded strings"):
        _read_batch(identities)


@pytest.mark.parametrize("payload", [
    b" " * (fixture.BATCH_MAX_BYTES + 1),
    b'{"items": [], "items": []}', b'{"items": [], "secret": "forbidden"}',
    b"[]", b'{"items": [',
], ids=["oversize", "duplicate-field", "extra-field", "not-object", "invalid-json"])
def test_batch_input_rejects_oversize_duplicate_or_invalid_json(payload):
    with pytest.raises(ValueError):
        fixture.read_batch(io.BytesIO(payload), command="seed-inspect-many")


def _fake_batch_sessions(monkeypatch):
    identities = _batch_identities(seeded=True)
    contexts = {item["actor_id"]: SimpleNamespace(company=SimpleNamespace(
        id=item["company_id"], slug=("summarypersistent-" if item["scenario"] == "persistent_qa"
                                   else "summaryacceptance-") + "fixture",
    )) for item in identities}
    updates = {item["update_id"]: SimpleNamespace(
        id=item["update_id"], company_id=item["company_id"], tracked_case_id=f"tracked-{index}",
        summary=fixture.FALLBACK, ai_summary_json={"summary_source": "provider"},
        model_run_id=None, source_text_sha256="original-source-hash",
    ) for index, item in enumerate(identities)}
    bookmarks = {item["bookmark_id"]: SimpleNamespace(
        company_id=item["company_id"], created_by_membership_id=item["actor_id"],
        matter_id=item["matter_id"], tracked_case_id=f"tracked-{index}",
    ) for index, item in enumerate(identities)}
    matters = {item["matter_id"]: SimpleNamespace(company_id=item["company_id"])
               for item in identities}
    sessions, resolutions = [], []
    active = set()

    class Rows(list):
        def one(self):
            assert len(self) == 1
            return self[0]

    class Session:
        def __init__(self):
            self.actor = None
            sessions.append(self)

        def __enter__(self):
            assert not active, "A previous actor's session is still open."
            active.add(self)
            return self

        def __exit__(self, *args):
            active.remove(self)

        def get(self, model, identity):
            return (bookmarks if model is fixture.TrackedCaseBookmark else matters).get(identity)

        def scalar(self, statement):
            if statement.column_descriptions[0].get("entity") is fixture.TrackedCaseUpdate:
                parameters = statement.compile().params
                update = updates.get(parameters["id_1"])
                return (
                    update if update and update.company_id == parameters["company_id_1"] else None
                )
            return 0

        def scalars(self, statement):
            if statement.column_descriptions[0].get("entity") is fixture.DomainOutboxEvent:
                item = next(item for item in identities if item["actor_id"] == self.actor)
                return Rows([SimpleNamespace(
                    id="event-" + self.actor, state="queued", attempts=0,
                    payload_json={"no_paid_providers": item["scenario"] == "marked"},
                )])
            return Rows()

    def context(session, actor):
        assert session in active
        assert session.actor in (None, actor), "An actor context was reused across identities."
        session.actor = actor
        resolutions.append((session, actor))
        return contexts[actor]

    def seed(session, **kwargs):
        assert session.actor == kwargs["actor_id"]
        return next(item.copy() for item in identities if item["actor_id"] == session.actor)

    monkeypatch.setattr(fixture, "get_session_factory", lambda: Session)
    monkeypatch.setattr(fixture, "get_session_context", context)
    monkeypatch.setattr(fixture, "seed", seed)
    return identities, Session, sessions, resolutions, contexts, updates, bookmarks, matters


@pytest.mark.parametrize("command", ["seed-inspect-many", "inspect-many"])
def test_batch_matches_scalar_raw_snapshots_with_fresh_actor_sessions(monkeypatch, command):
    identities, factory, sessions, resolutions, *_ = _fake_batch_sessions(monkeypatch)
    scalar = []
    for identity in identities:
        with factory() as session:
            scalar.append(fixture.inspect_fixture(session, actor_id=identity["actor_id"],
                                                   update_id=identity["update_id"]))
    sessions.clear()
    resolutions.clear()
    inputs = identities if command == "inspect-many" else _batch_identities()
    result = fixture.run_batch(_read_batch(inputs, command), command=command)
    assert result["ok"] is True
    assert result["failure"] is None
    assert [row["identity"] for row in result["items"]] == inputs
    assert [row["inspection"] for row in result["items"]] == scalar
    assert len(sessions) == (6 if command == "seed-inspect-many" else 3)
    assert len(set(sessions)) == len(sessions)
    assert [actor for _, actor in resolutions] == [
        item["actor_id"] for item in identities
        for _ in range(2 if command == "seed-inspect-many" else 1)
    ]
    if command == "seed-inspect-many":
        assert [row["seed"] for row in result["items"]] == identities


@pytest.mark.parametrize("boundary", [
    "company", "update", "bookmark", "creator", "matter", "tracked", "scenario",
])
def test_batch_rejects_cross_tenant_and_actor_child_scope(monkeypatch, boundary):
    identities, _, _, _, _, updates, bookmarks, matters = _fake_batch_sessions(monkeypatch)
    if boundary == "company":
        identities[0]["company_id"] = "different-company"
    elif boundary == "update":
        updates["update-0"].company_id = "company-1"
    elif boundary == "bookmark":
        bookmarks["bookmark-0"].company_id = "company-1"
    elif boundary == "creator":
        bookmarks["bookmark-0"].created_by_membership_id = "actor-1"
    elif boundary == "matter":
        matters["matter-0"].company_id = "company-1"
    elif boundary == "tracked":
        bookmarks["bookmark-0"].tracked_case_id = "tracked-1"
    else:
        identities[0]["scenario"] = "persistent_qa"
    result = fixture.run_batch(identities, command="inspect-many")
    assert result["ok"] is False
    assert result["failure"]["identity"] == identities[0]
    assert result["failure"]["error_type"] == "ValueError"
    assert "inspection" not in result["items"][0]


def test_batch_seed_rejects_cross_tenant_before_mutation(monkeypatch):
    identities, *_ = _fake_batch_sessions(monkeypatch)
    identities[0]["company_id"] = "different-company"
    monkeypatch.setattr(fixture, "seed", lambda *args, **kwargs: pytest.fail("cross-tenant seed"))
    result = fixture.run_batch(identities, command="seed-inspect-many")
    assert not result["ok"]
    assert result["failure"]["error_type"] == "ValueError"


def test_batch_rechecks_actor_scope_after_the_previous_inspection(monkeypatch):
    identities, _, sessions, _, contexts, *_ = _fake_batch_sessions(monkeypatch)
    original = fixture.inspect_fixture

    def inspect(session, **kwargs):
        snapshot = original(session, **kwargs)
        if kwargs["actor_id"] == "actor-0":
            contexts["actor-1"].company.id = "changed-company"
        return snapshot

    monkeypatch.setattr(fixture, "inspect_fixture", inspect)
    result = fixture.run_batch(identities, command="inspect-many")
    assert not result["ok"]
    assert result["items"][0]["inspection"]["summary"] == fixture.FALLBACK
    assert result["failure"]["identity"] == identities[1]
    assert len(sessions) == 2


def test_batch_retains_mismatched_committed_seed_and_refuses_inspection(monkeypatch):
    identities, *_ = _fake_batch_sessions(monkeypatch)
    changed = {**identities[0], "matter_id": "different-matter"}
    monkeypatch.setattr(fixture, "seed", lambda *args, **kwargs: changed)
    monkeypatch.setattr(fixture, "inspect_fixture", lambda *args, **kwargs: pytest.fail("inspect"))
    result = fixture.run_batch(_batch_identities(), command="seed-inspect-many")
    assert not result["ok"]
    assert result["items"][0]["seed"] == changed
    assert result["failure"]["message"] == "Seed returned a different fixture identity."


@pytest.mark.parametrize("command", ["seed-inspect-many", "inspect-many"])
def test_batch_partial_failure_retains_raw_prefix_and_failing_identity(monkeypatch, command):
    identities, _, sessions, *_ = _fake_batch_sessions(monkeypatch)
    original = fixture.inspect_fixture

    def inspect(session, **kwargs):
        if kwargs["actor_id"] == "actor-1":
            raise RuntimeError("injected inspection failure")
        return original(session, **kwargs)

    monkeypatch.setattr(fixture, "inspect_fixture", inspect)
    inputs = identities if command == "inspect-many" else _batch_identities()
    result = fixture.run_batch(inputs, command=command)
    assert not result["ok"]
    assert len(result["items"]) == 2
    assert result["items"][0]["inspection"]["summary"] == fixture.FALLBACK
    assert result["failure"] == {"identity": inputs[1], "error_type": "RuntimeError",
                                  "message": "injected inspection failure"}
    assert all(session.actor != "actor-2" for session in sessions)
    if command == "seed-inspect-many":
        assert result["items"][1]["seed"] == identities[1]


def test_batch_cli_retains_failure_json_and_nonzero_exit(monkeypatch, capsys):
    _fake_batch_sessions(monkeypatch)
    monkeypatch.setenv("CASEOPS_SUMMARY_ACCEPTANCE", "1")
    monkeypatch.setattr(fixture, "get_settings", _local_settings)
    monkeypatch.setattr(sys, "argv", ["fixture", "inspect-many"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(
        json.dumps({"items": _batch_identities(seeded=True)}).encode(),
    )))
    monkeypatch.setattr(fixture, "inspect_fixture", lambda *args, **kwargs: (_ for _ in ()).throw(
        ValueError("injected"),
    ))
    with pytest.raises(SystemExit) as failed:
        fixture.main()
    assert failed.value.code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["failure"]["identity"] == _batch_identities(seeded=True)[0]
    assert output["ok"] is False


def test_batch_cli_rejects_identity_argv_before_reading_or_mutating(monkeypatch):
    monkeypatch.setattr(fixture, "guard_local_runtime", lambda: None)
    monkeypatch.setattr(sys, "argv", ["fixture", "inspect-many", "--actor-id", "actor-0"])
    monkeypatch.setattr(fixture, "read_batch", lambda *args, **kwargs: pytest.fail("read stdin"))
    with pytest.raises(SystemExit) as rejected:
        fixture.main()
    assert rejected.value.code == 2


def test_worker_launcher_defers_seed_imports_but_checks_actual_frozen_prompt(tmp_path):
    code = '''
import importlib.abc, sys
from pathlib import Path
class NoSeedImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            "caseops_api.services.case_tracking", "caseops_api.services.case_tracking_providers",
        }:
            raise AssertionError("seed-only dependency imported before execve: " + fullname)
sys.meta_path.insert(0, NoSeedImports())
from caseops_api.scripts import docker_acceptance_summary as fixture
assert Path(fixture.__file__).resolve() == Path(sys.argv[1]).resolve()
assert fixture.frozen_call_key() == fixture.FROZEN_CASSETTE_KEY
fixture.guard_local_runtime = lambda: None
fixture.shutil.which = lambda name: "/installed/bin/" + name
fixture.tempfile.tempdir = sys.argv[2]
class Launched(Exception): pass
def launch(executable, argv, environment):
    assert executable == "/installed/bin/caseops-document-worker"
    assert argv == [executable, "--once", "--skip-migrations", "--skip-maintenance",
                    "--summary-batch-size", "25"]
    assert environment["CASEOPS_LLM_CASSETTE_MODE"] == "replay"
    raise Launched()
fixture.os.execve = launch
sys.argv = ["fixture", "worker"]
try: fixture.main()
except Launched: pass
else: raise AssertionError("real execve contract not reached")
fixture.SOURCE_TEXT = "drift"
try: fixture.main()
except RuntimeError as error: assert "prompt changed" in str(error)
else: raise AssertionError("prompt drift reached execve")
print("seed import tripwire and actual frozen prompt passed")
'''
    environment = {**os.environ, "PYTHONPATH": str(Path(fixture.__file__).parents[2]),
                   "CASEOPS_LLM_PROVIDER": "mock", "CASEOPS_LLM_API_KEY": "",
                   "CASEOPS_EMBEDDING_PROVIDER": "mock", "CASEOPS_EMBEDDING_API_KEY": ""}
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, fixture.__file__, str(tmp_path)],
        env=environment, capture_output=True, text=True, timeout=45, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "actual frozen prompt passed" in result.stdout
