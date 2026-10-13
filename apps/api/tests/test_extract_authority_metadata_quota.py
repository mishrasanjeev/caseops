from __future__ import annotations

import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuthorityDocument, ModelRun
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import extract_authority_metadata as mod
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import LLMProviderError, LLMQuotaExhaustedError


class _Provider:
    name = "openai"
    model = "gpt-5-mini"


def _run_with_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ids: list[str],
    concurrency: int,
    extract_one,
    provider_canary: bool = False,
) -> int:
    monkeypatch.setattr(mod, "_fetch_targets", lambda **_kwargs: ids)
    monkeypatch.setattr(mod, "_layer2_daily_cap_usd", lambda: 0.0)
    monkeypatch.setattr(mod, "build_provider", lambda **_kwargs: _Provider())
    monkeypatch.setattr(mod, "_extract_one", extract_one)
    return mod.run(
        limit=None,
        concurrency=concurrency,
        force=False,
        only_missing="any",
        provider_canary=provider_canary,
    )


def test_quota_stop_never_submits_beyond_the_bounded_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concurrency = 4
    ids = [f"doc-{index}" for index in range(20)]
    all_started = threading.Barrier(concurrency)
    release_drainers = threading.Event()
    started: list[str] = []
    started_lock = threading.Lock()

    def extract_one(doc_id: str, _provider: _Provider) -> dict[str, object]:
        with started_lock:
            started.append(doc_id)
        all_started.wait(timeout=5)
        if doc_id == ids[0]:
            # _extract_one sets this before returning its typed outcome. The
            # other workers wait so the driver cannot observe a success first.
            mod._QUOTA_EXHAUSTED_FLAG.set()
            release_drainers.set()
            return {"ok": False, "reason": "quota_exhausted"}
        assert release_drainers.wait(timeout=5)
        return {"ok": True, "updated": False}

    exit_code = _run_with_fakes(
        monkeypatch,
        ids=ids,
        concurrency=concurrency,
        extract_one=extract_one,
    )

    assert exit_code == mod.EXIT_QUOTA_EXHAUSTED
    assert len(started) == concurrency
    assert set(started) == set(ids[:concurrency])
    assert len(ids) - len(started) == 16


def test_transient_provider_error_keeps_the_rolling_window_moving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [f"doc-{index}" for index in range(9)]
    started: list[str] = []

    def extract_one(doc_id: str, _provider: _Provider) -> dict[str, object]:
        started.append(doc_id)
        if doc_id == ids[0]:
            return {"ok": False, "reason": "llm_error"}
        return {"ok": True, "updated": False}

    exit_code = _run_with_fakes(
        monkeypatch,
        ids=ids,
        concurrency=3,
        extract_one=extract_one,
    )

    assert exit_code == 0
    assert set(started) == set(ids)
    assert len(started) == len(ids)


def test_quota_error_is_audited_before_the_worker_stops(
    client: TestClient,
) -> None:
    _ = client
    token = uuid.uuid4().hex
    doc_id = f"quota-audit-{token}"
    factory = get_session_factory()
    with factory() as session:
        session.add(
            AuthorityDocument(
                id=doc_id,
                source="ecourts-sc",
                adapter_name="corpus-ingest",
                court_name="Supreme Court of India",
                forum_level="supreme_court",
                document_type="judgment",
                title="Quota Audit v. State",
                canonical_key=f"quota-audit-key-{token}",
                source_reference=f"quota/audit/{token}.pdf",
                summary="",
                document_text="Judgment text " * 30,
                extracted_char_count=420,
            )
        )
        session.commit()

    class _QuotaProvider(_Provider):
        def generate(self, *_args, **_kwargs):
            raise LLMQuotaExhaustedError(
                f"OpenAI quota exhausted: credit_balance_exhausted {token}"
            )

    mod._reset_run_state()
    outcome = mod._extract_one(doc_id, _QuotaProvider())

    assert outcome == {"ok": False, "reason": "quota_exhausted"}
    assert mod._QUOTA_EXHAUSTED_FLAG.is_set()
    with factory() as session:
        runs = list(session.scalars(select(ModelRun).where(ModelRun.error.contains(token))))
    assert len(runs) == 1
    assert runs[0].purpose == "metadata_extract"
    assert runs[0].provider == "openai"
    assert runs[0].model == "gpt-5-mini"
    assert runs[0].status == "error"


def test_cloud_run_job_timeout_is_capped_at_twelve_hours() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    job_script = repo_root / "scripts" / "extract-authority-metadata-job.sh"
    source = job_script.read_text(encoding="utf-8")

    assert "--task-timeout=43200s" in source
    assert "--task-timeout=86400s" not in source


def test_provider_canary_forces_one_eligible_target_and_succeeds_only_on_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [f"canary-{index}" for index in range(6)]
    selected: list[str] = []
    fetch_arguments: list[dict[str, object]] = []

    def fetch_targets(**kwargs) -> list[str]:
        fetch_arguments.append(kwargs)
        return ids[: kwargs["limit"]]

    def extract_one(doc_id: str, _provider: _Provider) -> dict[str, object]:
        selected.append(doc_id)
        return {"ok": True, "updated": False, "provider_completed": True}

    monkeypatch.setattr(mod, "_fetch_targets", fetch_targets)
    monkeypatch.setattr(mod, "_layer2_daily_cap_usd", lambda: 0.0)
    monkeypatch.setattr(mod, "build_provider", lambda **_kwargs: _Provider())
    monkeypatch.setattr(mod, "_extract_one", extract_one)

    exit_code = mod.run(
        limit=99,
        concurrency=12,
        force=True,
        only_missing="citation",
        provider_canary=True,
    )

    assert exit_code == 0
    assert fetch_arguments == [
        {
            "limit": 1,
            "force": False,
            "only_missing": "any",
            "provider_canary": True,
        }
    ]
    assert selected == [ids[0]]


def test_provider_canary_fails_closed_when_no_eligible_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mod, "_fetch_targets", lambda **_kwargs: [])

    exit_code = mod.run(
        limit=None,
        concurrency=8,
        force=False,
        only_missing="any",
        provider_canary=True,
    )

    assert exit_code == mod.EXIT_PROVIDER_CANARY_FAILED


@pytest.mark.parametrize(
    "outcome",
    [
        {"ok": False, "reason": "no_text"},
        {"ok": False, "reason": "parse_error"},
        {"ok": True, "updated": False},
    ],
)
def test_provider_canary_fails_without_an_actual_successful_completion(
    monkeypatch: pytest.MonkeyPatch,
    outcome: dict[str, object],
) -> None:
    calls: list[str] = []

    def extract_one(doc_id: str, _provider: _Provider) -> dict[str, object]:
        calls.append(doc_id)
        return outcome

    exit_code = _run_with_fakes(
        monkeypatch,
        ids=["eligible-canary"],
        concurrency=8,
        extract_one=extract_one,
        provider_canary=True,
    )

    assert exit_code == mod.EXIT_PROVIDER_CANARY_FAILED
    assert calls == ["eligible-canary"]


def test_provider_canary_query_requires_missing_metadata_and_eligible_text(
    client: TestClient,
) -> None:
    _ = client
    token = uuid.uuid4().hex
    factory = get_session_factory()
    short_id = f"canary-short-{token}"
    eligible_id = f"canary-eligible-{token}"
    complete_id = f"canary-complete-{token}"
    with factory() as session:
        for doc_id, text_value, citation, case_reference in (
            (short_id, "short", None, None),
            (eligible_id, "Eligible judgment text " * 20, None, None),
            (
                complete_id,
                "Already complete judgment text " * 20,
                "2026 INSC 1",
                "C.A. 1/2026",
            ),
        ):
            session.add(
                AuthorityDocument(
                    id=doc_id,
                    source="ecourts-sc",
                    adapter_name="corpus-ingest",
                    court_name="Supreme Court of India",
                    forum_level="supreme_court",
                    document_type="judgment",
                    title="Provider Canary v. State",
                    canonical_key=f"canary-key-{doc_id}",
                    source_reference=f"canary/{doc_id}.pdf",
                    summary="",
                    document_text=text_value,
                    extracted_char_count=len(text_value),
                    neutral_citation=citation,
                    case_reference=case_reference,
                )
            )
        session.commit()

    targets = mod._fetch_targets(
        limit=1,
        force=False,
        only_missing="any",
        provider_canary=True,
    )

    assert targets == [eligible_id]


def test_provider_canary_cli_flag_reaches_fail_closed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments: list[dict[str, object]] = []

    def fake_run(**kwargs) -> int:
        arguments.append(kwargs)
        return mod.EXIT_PROVIDER_CANARY_FAILED

    monkeypatch.setattr(mod, "run", fake_run)

    exit_code = mod.main(
        ["--provider-canary", "--limit", "99", "--concurrency", "12", "--force"]
    )

    assert exit_code == mod.EXIT_PROVIDER_CANARY_FAILED
    assert arguments[0]["provider_canary"] is True


def _memory_metadata(monkeypatch: pytest.MonkeyPatch, count: int = 20):
    docs = {
        f"money-doc-{index}": AuthorityDocument(
            id=f"money-doc-{index}",
            title="Retained judgment",
            document_text="Judgment text " * 30,
            neutral_citation=None,
            case_reference=None,
            structured_version=None,
        )
        for index in range(count)
    }
    audit_rows: list[ModelRun] = []
    commits: list[bool] = []

    class MemorySession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, model, doc_id):
            assert model is AuthorityDocument
            return docs.get(doc_id)

        def add(self, row):
            audit_rows.append(row)

        def flush(self):
            return None

        def commit(self):
            commits.append(True)

    monkeypatch.setattr(mod, "get_session_factory", lambda: MemorySession)
    monkeypatch.setattr(mod, "_fetch_targets", lambda **_kwargs: list(docs))
    monkeypatch.setattr(mod, "_layer2_daily_cap_usd", lambda: 0.0)
    return docs, audit_rows, commits


@pytest.mark.parametrize("concurrency", [1, 4])
@pytest.mark.parametrize("entrypoint", ["run", "cli"])
def test_money_stop_bounds_admission_and_leaves_unsubmitted_remainder(
    monkeypatch: pytest.MonkeyPatch, concurrency: int, entrypoint: str
) -> None:
    docs, audit_rows, commits = _memory_metadata(monkeypatch)
    started: list[str] = []
    lock = threading.Lock()
    initial_window = threading.Barrier(concurrency)

    class DeniedProvider(_Provider):
        def generate(self, *_args, **_kwargs):
            with lock:
                started.append(threading.current_thread().name)
                ordinal = len(started)
            if ordinal <= concurrency:
                initial_window.wait(timeout=5)
            raise AiMoneyBudgetError("shared allowance unavailable")

    monkeypatch.setattr(mod, "build_provider", lambda **_kwargs: DeniedProvider())
    if entrypoint == "cli":
        exit_code = mod.main(["--concurrency", str(concurrency)])
    else:
        exit_code = mod.run(
            limit=None, concurrency=concurrency, force=False, only_missing="any"
        )

    assert exit_code == 5  # Distinct from daily cap, upstream quota and canary.
    assert len(started) == concurrency
    assert len(docs) - len(started) == 20 - concurrency
    assert audit_rows == []
    assert commits == []
    assert mod._stats["llm_error"] == 0
    assert mod._stats["ai_money_denied"] == concurrency
    assert all(doc.neutral_citation is None for doc in docs.values())
    assert all(doc.structured_version is None for doc in docs.values())


def test_money_stop_worker_short_circuits_without_a_document_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs, audit_rows, commits = _memory_metadata(monkeypatch, 2)
    calls: list[bool] = []

    class DeniedProvider(_Provider):
        def generate(self, *_args, **_kwargs):
            calls.append(True)
            raise AiMoneyBudgetError("missing reviewed month")

    mod._reset_run_state()
    first, second = docs
    provider = DeniedProvider()
    outcome = mod._extract_one(first, provider)
    pending = mod._extract_one(second, provider)

    assert outcome == {"ok": False, "reason": "ai_money_denied"}
    assert pending == {"ok": False, "reason": "ai_money_halt"}
    assert calls == [True]
    assert audit_rows == []
    assert commits == []
    assert mod._stats["llm_error"] == 0
    assert docs[first].title == docs[second].title == "Retained judgment"


def test_money_stop_escaped_worker_is_nonzero_and_next_run_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []

    def denied(doc_id, _provider):
        started.append(doc_id)
        raise AiMoneyBudgetError("unknown exact model price")

    exit_code = _run_with_fakes(
        monkeypatch, ids=["first", "unsubmitted"], concurrency=1, extract_one=denied
    )
    assert exit_code == 5
    assert started == ["first"]

    def admitted(doc_id, _provider):
        started.append(doc_id)
        return {"ok": True, "updated": False}

    next_exit = _run_with_fakes(
        monkeypatch, ids=["next-run"], concurrency=1, extract_one=admitted
    )
    assert next_exit == 0
    assert started == ["first", "next-run"]


@pytest.mark.parametrize("concurrency", [1, 4])
def test_money_stop_does_not_change_transient_provider_continuation(
    monkeypatch: pytest.MonkeyPatch, concurrency: int
) -> None:
    docs, audit_rows, commits = _memory_metadata(monkeypatch, 9)
    calls: list[bool] = []

    class TransientProvider(_Provider):
        def generate(self, *_args, **_kwargs):
            calls.append(True)
            raise LLMProviderError("deterministic temporary outage")

    monkeypatch.setattr(mod, "build_provider", lambda **_kwargs: TransientProvider())
    exit_code = mod.run(
        limit=None, concurrency=concurrency, force=False, only_missing="any"
    )

    assert exit_code == 0
    assert len(calls) == len(docs) == len(audit_rows) == len(commits) == 9
    assert mod._stats["llm_error"] == 9
