"""Regression coverage for the concurrent-mode triage-session
release in ``_structured_pass``.

Anchor: 2026-05-04 c=16 run on the ingest VM held the triage SELECT
session ``idle in transaction`` for 30+ minutes
(``wait_event=Client/ClientRead``). With Cloud SQL
``max_connections=100`` and several other VM jobs alive, every
held connection matters. PR #14 issues ``session.rollback()``
right after the in-memory buckets are sorted, so the long-running
worker run starts with the triage connection back in the pool.

These tests pin:

- concurrent mode (``concurrency > 1``) calls ``rollback()`` on the
  triage session BEFORE the first worker is invoked
- sequential mode (``concurrency == 1``) does NOT touch the triage
  session — it reuses the same session for ``commit()`` after
  every doc, and a premature rollback would corrupt that flow
- ``rollback()`` not ``close()`` is used (caller's
  ``with SessionFactory() as session:`` context manager stays
  valid)
"""
from __future__ import annotations

import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import backfill_corpus_quality as mod
from caseops_api.services.corpus_structured import StructuredExtractionSummary


def _seed(n: int) -> list[str]:
    factory = get_session_factory()
    s = factory()
    ids: list[str] = []
    try:
        for i in range(n):
            doc_id = f"trg-{i:02d}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts-sc", adapter_name="corpus-ingest",
                court_name="Supreme Court of India", forum_level="supreme_court",
                document_type="judgment", title="English Title v. State",
                canonical_key=f"k-{doc_id}",
                source_reference=f"sc/2024/2024_1_{i}_5_EN.pdf",
                summary="", document_text="The petitioner appeals.",
                extracted_char_count=20, structured_version=None,
            ))
            ids.append(doc_id)
        s.commit()
    finally:
        s.close()
    return ids


def _fake_summary(session, *, document, tier: str) -> StructuredExtractionSummary:
    _ = (session, tier)
    return StructuredExtractionSummary(
        document_id=document.id,
        chunks_annotated=0,
        provider="openai", model="gpt-5-mini",
        prompt_tokens=100, completion_tokens=20,
        cost_usd=0.01, quality_score=0.9, quality_issues=(),
    )


class _Tracking:
    """Counts ``rollback()`` / ``close()`` calls on a session,
    delegating every other attribute to the wrapped instance."""

    def __init__(self, real_session):
        self._real = real_session
        self.rollback_calls: list[float] = []
        self.close_calls = 0
        # Captured by extract_and_persist_structured stub when it is
        # invoked — lets us assert ordering of rollback vs first
        # worker call.
        self.rollback_count_at_first_worker_call: int | None = None

    def __getattr__(self, name):
        return getattr(self._real, name)

    def rollback(self):
        import time
        self.rollback_calls.append(time.time())
        return self._real.rollback()

    def close(self):
        self.close_calls += 1
        return self._real.close()


def test_concurrent_mode_rolls_back_triage_session_before_workers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anchor test: at concurrency > 1, the first worker call must
    see ``rollback()`` already invoked on the triage session.

    Implementation: wrap the session in a ``_Tracking`` shim that
    counts rollbacks. The fake ``extract_and_persist_structured``
    captures the rollback count at the moment of its first
    invocation. If PR #14 is correctly placed BEFORE the bucket
    runs, the count is ≥ 1.
    """
    _ = client
    _seed(4)
    seen_lock = threading.Lock()
    capture_lock = threading.Lock()

    def _capture(session, *, document, tier):
        with capture_lock:
            if tracking.rollback_count_at_first_worker_call is None:
                tracking.rollback_count_at_first_worker_call = (
                    len(tracking.rollback_calls)
                )
        with seen_lock:
            seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    seen: list[str] = []
    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)

    factory = get_session_factory()
    real_session = factory()
    tracking = _Tracking(real_session)
    try:
        mod._structured_pass(
            tracking, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=(1990, 2025), concurrency=2,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )
    finally:
        real_session.close()

    # rollback was called at least once before the first worker.
    assert tracking.rollback_count_at_first_worker_call is not None, (
        "no worker was invoked — buckets came out empty"
    )
    assert tracking.rollback_count_at_first_worker_call >= 1, (
        f"workers ran before rollback (rollback count at first worker call = "
        f"{tracking.rollback_count_at_first_worker_call})"
    )
    # close() was NOT called by _structured_pass — caller owns the
    # session lifecycle. The test's own .close() in the finally
    # block doesn't go through _Tracking.close.
    assert tracking.close_calls == 0


def test_sequential_mode_does_not_rollback_triage_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sequential mode reuses the SAME session for the worker
    ``extract_and_persist_structured`` calls and explicit
    ``session.commit()`` between docs. Releasing the triage
    transaction here would either flush stale state or break the
    commit cadence. Pin that PR #14 is concurrency-gated."""
    _ = client
    _seed(3)
    seen: list[str] = []

    def _capture(session, *, document, tier):
        seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)

    factory = get_session_factory()
    real_session = factory()
    tracking = _Tracking(real_session)
    try:
        mod._structured_pass(
            tracking, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=(1990, 2025), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )
    finally:
        real_session.close()

    # 3 docs processed.
    assert len(seen) == 3
    # No rollback fired — sequential mode preserves the prior behaviour.
    assert tracking.rollback_calls == []
    assert tracking.close_calls == 0


def test_concurrent_mode_uses_rollback_not_close(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller owns the session via ``with SessionFactory() as session:``
    in ``run()``. Closing it inside ``_structured_pass`` would
    invalidate the context manager. Pin that we use ``rollback()``
    not ``close()``."""
    _ = client
    _seed(2)

    def _capture(session, *, document, tier):
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)

    factory = get_session_factory()
    real_session = factory()
    tracking = _Tracking(real_session)
    try:
        mod._structured_pass(
            tracking, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=(1990, 2025), concurrency=4,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )
        # Caller can still use the session after _structured_pass returns.
        # If close() had been called, this raises.
        from caseops_api.db.models import AuthorityDocument as _AD
        n = real_session.query(_AD).count()
        assert n >= 2  # the 2 docs we seeded are still readable
    finally:
        real_session.close()

    assert tracking.close_calls == 0
    assert len(tracking.rollback_calls) >= 1


def test_triage_only_does_not_rollback_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--triage-only`` returns BEFORE the rollback gate. The flag
    is for diagnostic candidate-selection runs (no LLM, no workers)
    so the session lifecycle doesn't matter — but pinning that
    triage_only and the rollback gate don't interact protects
    against a future re-ordering bug."""
    _ = client
    _seed(2)

    factory = get_session_factory()
    real_session = factory()
    tracking = _Tracking(real_session)
    try:
        totals = mod._structured_pass(
            tracking, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=(1990, 2025), concurrency=4,
            english_only=True, forums=mod._DEFAULT_FORUMS,
            triage_only=True,
        )
    finally:
        real_session.close()

    assert totals.get("triage_only") is True
    # Triage-only path returns before the rollback gate.
    assert tracking.rollback_calls == []
