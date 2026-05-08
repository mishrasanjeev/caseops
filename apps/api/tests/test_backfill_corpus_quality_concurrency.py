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

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import backfill_corpus_quality as mod
from caseops_api.services.corpus_structured import StructuredExtractionSummary


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
            force_tier="haiku", year_range=None,
            concurrency=4,
        )

    assert totals["haiku"]["done"] == 20
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
            force_tier="haiku", year_range=None,
            concurrency=4,
        )

    # Budget caps at 5 docs ($0.05 / $0.01) plus up to 3 in-flight workers.
    assert 5 <= totals["haiku"]["done"] <= 5 + 4
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
            force_tier="haiku", year_range=None,
            concurrency=1,
        )

    assert totals["haiku"]["done"] == 20
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
            force_tier="haiku",
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
            force_tier="haiku",
            year_range=None,
            concurrency=4,
        )
        parallel_max_active = max_active

    assert sequential_max_active == 1
    assert parallel_max_active > 1
