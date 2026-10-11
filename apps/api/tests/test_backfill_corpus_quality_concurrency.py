"""Regression coverage for the --concurrency flag added to
backfill_corpus_quality.py.

Three invariants must hold across sequential and concurrent paths:

1. Same set of documents is processed when budget is ample.
2. Budget ceiling stops the run cleanly under concurrency overshoot.
3. Concurrency actually parallelizes slow LLM calls.

We stub ``extract_and_persist_structured`` with a fake that returns a
deterministic per-doc cost so we can assert the totals exactly.
"""
from __future__ import annotations

import threading
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import backfill_corpus_quality as mod
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.corpus_structured import StructuredExtractionSummary
from caseops_api.services.llm import (
    LLMDailyCapReachedError,
    LLMProviderError,
    LLMQuotaExhaustedError,
)


def _seed(n: int) -> list[str]:
    """Insert N pre-Layer-2 docs and return their ids."""
    factory = get_session_factory()
    ids: list[str] = []
    s = factory()
    try:
        for i in range(n):
            doc_id = f"test-doc-{i:02d}-{uuid.uuid4().hex[:6]}"
            doc = AuthorityDocument(
                id=doc_id,
                source="ecourts-sc",
                adapter_name="corpus-ingest",
                court_name="Supreme Court of India",
                forum_level="supreme_court",
                document_type="judgment",
                title=f"placeholder title {doc_id[:6]}",
                canonical_key=f"sc-{doc_id}",
                source_reference=f"sc/2024/{doc_id}",
                summary="",
                document_text="x" * 1000,
                extracted_char_count=1000,
                structured_version=None,
            )
            s.add(doc)
            ids.append(doc_id)
        s.commit()
    finally:
        s.close()
    return ids


def _fake_summary(session, *, document, tier: str) -> StructuredExtractionSummary:
    """Stand-in for extract_and_persist_structured. Returns deterministic
    $0.01/doc so a $0.05 budget caps at 5 docs."""
    _ = (session, tier)
    return StructuredExtractionSummary(
        document_id=document.id,
        chunks_annotated=0,
        provider="openai",
        model="gpt-5-mini",
        prompt_tokens=1607,
        completion_tokens=310,
        cost_usd=0.01,
        quality_score=0.9,
        quality_issues=(),
    )


def test_concurrent_run_processes_all_docs_under_budget(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ample budget, concurrent run completes every candidate."""
    _ = client
    _seed(20)
    seen: list[str] = []
    seen_lock = threading.Lock()

    def _capture(session, *, document, tier):
        with seen_lock:
            seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)

    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session,
            limit=None, dry_run=True, budget_usd=10.0,
            force_tier="standard", year_range=None,
            concurrency=4,
        )

    assert totals["standard"]["done"] == 20
    assert len(set(seen)) == 20
    # spent ~= 20 * 0.01 = $0.20
    assert 0.19 < totals["spent_usd"] < 0.22


def test_concurrent_budget_cap_stops_cleanly(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Budget=$0.05 with $0.01/doc must process at most ~5 docs even
    under 4-way concurrency. Allow concurrency-1 worker overshoot."""
    _ = client
    _seed(20)
    monkeypatch.setattr(mod, "extract_and_persist_structured", _fake_summary)

    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session,
            limit=None, dry_run=True, budget_usd=0.05,
            force_tier="standard", year_range=None,
            concurrency=4,
        )

    # Budget caps at 5 docs ($0.05 / $0.01) plus up to 3 in-flight workers.
    assert 5 <= totals["standard"]["done"] <= 5 + 4
    assert totals["spent_usd"] >= 0.05
    assert totals["spent_usd"] <= 0.05 + 4 * 0.01 + 1e-9


def test_sequential_mode_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """concurrency=1 takes the legacy code path; totals match the
    concurrent path on the same input."""
    _ = client
    _seed(20)
    monkeypatch.setattr(mod, "extract_and_persist_structured", _fake_summary)

    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session,
            limit=None, dry_run=True, budget_usd=10.0,
            force_tier="standard", year_range=None,
            concurrency=1,
        )

    assert totals["standard"]["done"] == 20
    assert 0.19 < totals["spent_usd"] < 0.22


def test_concurrency_actually_parallelizes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """concurrency=4 must overlap fake LLM calls instead of running serially."""
    _ = client
    _seed(20)
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def _slow_summary(session, *, document, tier):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        try:
            return _fake_summary(session, document=document, tier=tier)
        finally:
            with active_lock:
                active -= 1

    monkeypatch.setattr(mod, "extract_and_persist_structured", _slow_summary)

    factory = get_session_factory()
    with factory() as session:
        mod._structured_pass(
            session,
            limit=None,
            dry_run=True,
            budget_usd=10.0,
            force_tier="standard",
            year_range=None,
            concurrency=1,
        )
        sequential_max_active = max_active

    active = 0
    max_active = 0

    with factory() as session:
        mod._structured_pass(
            session,
            limit=None,
            dry_run=True,
            budget_usd=10.0,
            force_tier="standard",
            year_range=None,
            concurrency=4,
        )
        parallel_max_active = max_active

    assert sequential_max_active == 1
    assert parallel_max_active > 1


def _memory_backfill(monkeypatch: pytest.MonkeyPatch, count: int = 20):
    docs = {
        f"money-doc-{index}": AuthorityDocument(
            id=f"money-doc-{index}",
            title="Retained judgment",
            source_reference=f"sc/2024_{index}_1_1_EN.pdf",
            forum_level="supreme_court",
            document_text="Judgment text " * 80,
            structured_version=None,
            decision_date=None,
        )
        for index in range(count)
    }
    sessions: list[object] = []
    snapshots: list[dict] = []

    class MemorySession:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0
            self.closed = False
            self.release_on_rollback = None
            sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: list(docs.values()))

        def get(self, model, doc_id):
            assert model is AuthorityDocument
            return docs.get(doc_id)

        def rollback(self):
            self.rollbacks += 1
            if self.release_on_rollback is not None:
                self.release_on_rollback.set()

        def commit(self):
            self.commits += 1

    monkeypatch.setattr(mod, "get_session_factory", lambda: MemorySession)
    monkeypatch.setattr(mod, "_emit_budget_snapshot", lambda totals: snapshots.append(dict(totals)))
    return docs, sessions, snapshots


@pytest.mark.parametrize("concurrency", [1, 4])
@pytest.mark.parametrize("entrypoint", ["pass", "cli"])
def test_money_stop_bounds_window_preserves_records_and_cli_outcome(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    concurrency: int,
    entrypoint: str,
) -> None:
    docs, sessions, snapshots = _memory_backfill(monkeypatch)
    started: list[str] = []
    lock = threading.Lock()
    initial_window = threading.Barrier(concurrency)

    def denied(_session, *, document, tier):
        with lock:
            started.append(document.id)
            ordinal = len(started)
        if ordinal <= concurrency:
            initial_window.wait(timeout=5)
        raise AiMoneyBudgetError("shared allowance unavailable")

    monkeypatch.setattr(mod, "extract_and_persist_structured", denied)
    if entrypoint == "cli":
        exit_code = mod.main(
            ["--stage", "structured", "--force-tier", "standard",
             "--concurrency", str(concurrency), "--budget-usd", "10"]
        )
        assert exit_code == 2
        assert "stop_reason=ai_money_denied" in capsys.readouterr().out
        totals = snapshots[-1]
    else:
        with mod.get_session_factory()() as session:
            totals = mod._structured_pass(
                session, limit=None, dry_run=False, budget_usd=10.0,
                force_tier="standard", year_range=None, concurrency=concurrency,
            )

    assert len(started) == concurrency
    assert started == list(docs)[:concurrency] or set(started) == set(list(docs)[:concurrency])
    assert len(docs) - len(started) == 20 - concurrency
    assert totals["stop_reason"] == "ai_money_denied"
    assert snapshots[-1]["stop_reason"] == "ai_money_denied"
    assert totals["failures"] == totals["quality_low"] == 0
    assert totals["standard"]["done"] == totals["premium"]["done"] == 0
    assert totals["spent_usd"] == 0
    assert all(session.commits == 0 and session.closed for session in sessions)
    assert all(doc.structured_version is None for doc in docs.values())
    assert all(doc.title == "Retained judgment" for doc in docs.values())


def test_money_stop_drains_admitted_successes_without_submitting_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs, sessions, _snapshots = _memory_backfill(monkeypatch)
    started: list[str] = []
    lock = threading.Lock()
    initial_window = threading.Barrier(4)
    denial_rolled_back = threading.Event()

    def mixed(session, *, document, tier):
        with lock:
            started.append(document.id)
        if document.id in list(docs)[:4]:
            initial_window.wait(timeout=5)
        if document.id == next(iter(docs)):
            session.release_on_rollback = denial_rolled_back
            raise AiMoneyBudgetError("shared allowance unavailable")
        assert denial_rolled_back.wait(timeout=5)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", mixed)
    with mod.get_session_factory()() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=None, concurrency=4,
        )

    assert len(started) == 4
    assert set(started) == set(list(docs)[:4])
    assert totals["stop_reason"] == "ai_money_denied"
    assert totals["failures"] == 0
    assert totals["standard"]["done"] == 3
    assert totals["spent_usd"] == pytest.approx(0.03)
    assert sum(session.commits for session in sessions) == 3
    assert all(session.closed for session in sessions)


@pytest.mark.parametrize("concurrency", [1, 4])
def test_money_stop_does_not_continue_into_the_next_tier(
    monkeypatch: pytest.MonkeyPatch, concurrency: int
) -> None:
    docs, _sessions, _snapshots = _memory_backfill(monkeypatch, 8)
    premium_ids = set(list(docs)[:4])
    monkeypatch.setattr(
        mod, "_tier_for_doc", lambda doc: "premium" if doc.id in premium_ids else "standard"
    )
    started: list[str] = []

    def denied(_session, *, document, tier):
        started.append(document.id)
        raise AiMoneyBudgetError("missing reviewed month")

    monkeypatch.setattr(mod, "extract_and_persist_structured", denied)
    with mod.get_session_factory()() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier=None, year_range=None, concurrency=concurrency,
        )

    assert set(started) <= premium_ids
    assert 1 <= len(started) <= concurrency
    assert totals["stop_reason"] == "ai_money_denied"
    assert totals["standard"]["done"] == totals["failures"] == 0


@pytest.mark.parametrize("concurrency", [1, 4])
def test_money_stop_preserves_transient_continuation(
    monkeypatch: pytest.MonkeyPatch, concurrency: int
) -> None:
    docs, _sessions, _snapshots = _memory_backfill(monkeypatch, 9)
    started: list[str] = []

    def transient_then_success(session, *, document, tier):
        started.append(document.id)
        if document.id == next(iter(docs)):
            raise LLMProviderError("deterministic temporary outage")
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", transient_then_success)
    with mod.get_session_factory()() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=None, concurrency=concurrency,
        )

    assert set(started) == set(docs)
    assert len(started) == 9
    assert totals.get("stop_reason") is None
    assert totals["failures"] == 1
    assert totals["standard"]["done"] == 8


@pytest.mark.parametrize("concurrency", [1, 4])
@pytest.mark.parametrize("error_type", [LLMDailyCapReachedError, LLMQuotaExhaustedError])
def test_money_stop_preserves_existing_daily_and_quota_stops(
    monkeypatch: pytest.MonkeyPatch, concurrency: int, error_type
) -> None:
    _docs, _sessions, _snapshots = _memory_backfill(monkeypatch)
    started: list[str] = []
    initial_window = threading.Barrier(concurrency)

    def stopped(_session, *, document, tier):
        started.append(document.id)
        initial_window.wait(timeout=5)
        raise error_type("deterministic existing operational stop")

    monkeypatch.setattr(mod, "extract_and_persist_structured", stopped)
    with mod.get_session_factory()() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=None, concurrency=concurrency,
        )

    assert len(started) == concurrency
    assert totals.get("stop_reason") is None
    assert totals["failures"] == totals["standard"]["done"] == 0
