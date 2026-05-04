"""Coverage for the daily-cap / upstream-quota stop signal in
``_structured_pass``.

Anchor: 2026-05-04 c=16 run hit ``OpenAI insufficient_quota`` at
``08:23Z``. The previous worker code path caught the
``LLMQuotaExhaustedError`` as a generic Exception and returned
``"FAILED"``; the outer driver only watches ``totals['spent_usd']``
against ``--budget-usd``, which never advances on FAILED returns.
The script would have spun every remaining doc through the same
quota wall (at the per-minute openai retry budget) until manually
stopped — a predictable control-flow bug, not an intermittent
nuisance.

PR #15 fix: distinguish two **stop signals** from per-doc failures:

- ``LLMDailyCapReachedError`` (typed subclass) — raised by
  ``ensure_daily_cap_not_exceeded`` when our operator-configured
  daily cap fires.
- ``LLMQuotaExhaustedError`` — raised by ``OpenAIProvider`` /
  ``AnthropicProvider`` when the upstream account hits its credit
  / paid-quota wall.

Both drain in-flight workers and exit the bucket without marking
docs as failures.

These tests pin the new control flow so the spin can't return.
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
from caseops_api.services.llm import (
    LLMDailyCapReachedError,
    LLMProviderError,
    LLMQuotaExhaustedError,
)


def _seed(n: int) -> list[str]:
    factory = get_session_factory()
    s = factory()
    ids: list[str] = []
    try:
        for i in range(n):
            doc_id = f"q15-{i:02d}-{uuid.uuid4().hex[:6]}"
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


def _ok_summary(document) -> StructuredExtractionSummary:
    return StructuredExtractionSummary(
        document_id=document.id,
        chunks_annotated=0,
        provider="openai", model="gpt-5-mini",
        prompt_tokens=100, completion_tokens=20,
        cost_usd=0.01, quality_score=0.9, quality_issues=(),
    )


# ---------- Type hierarchy: typed subclass beats string-match -----


def test_llm_daily_cap_reached_is_subclass_of_provider_error() -> None:
    """The driver's existing fallback catch on ``LLMProviderError``
    must still fire if a future change reverts the typed-subclass
    pattern. ``LLMDailyCapReachedError`` MUST inherit from
    ``LLMProviderError`` (and from ``Exception`` transitively)."""
    assert issubclass(LLMDailyCapReachedError, LLMProviderError)
    assert issubclass(LLMQuotaExhaustedError, LLMProviderError)
    # And the two siblings must be distinct so the worker can tell
    # them apart for logging context if it ever needs to.
    assert not issubclass(LLMDailyCapReachedError, LLMQuotaExhaustedError)
    assert not issubclass(LLMQuotaExhaustedError, LLMDailyCapReachedError)


# ---------- Concurrent path: daily cap stops cleanly --------------


def test_concurrent_daily_cap_drains_without_marking_failures(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anchor regression. Seed 8 docs; the fake extractor processes
    the first 3 OK, then raises ``LLMDailyCapReachedError`` for
    every subsequent call. The driver MUST:
    - drain in-flight without submitting more
    - return False from the bucket
    - NOT increment ``totals['failures']`` for the cap-stopped docs
    - NOT process the remaining docs (no spin)"""
    _ = client
    _seed(8)
    call_lock = threading.Lock()
    call_counter = {"n": 0}

    def _fake_extract(session, *, document, tier):
        with call_lock:
            call_counter["n"] += 1
            n = call_counter["n"]
        if n <= 3:
            return _ok_summary(document)
        raise LLMDailyCapReachedError(
            "Layer 2 daily cap reached: $40.00 spent today (cap $40.00)."
        )

    monkeypatch.setattr(mod, "extract_and_persist_structured", _fake_extract)
    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=(1990, 2025), concurrency=4,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )

    # 3 docs went through cleanly.
    assert totals["haiku"]["done"] == 3
    # 5 remaining docs: the cap-fired ones must NOT be counted as
    # failures. With concurrency=4 and a prime-then-as-completed
    # scheduler, some additional docs may have been in-flight when
    # the stop fired and also raised — those also must NOT count
    # toward failures. The key invariant: failures stays at 0 for
    # cap-class exceptions.
    assert totals["failures"] == 0
    # Spend recorded matches the 3 successful calls only.
    assert totals["spent_usd"] == pytest.approx(0.03, abs=1e-9)


def test_concurrent_quota_exhausted_drains_without_marking_failures(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same shape as the cap test, but with the upstream-provider
    error (``LLMQuotaExhaustedError``) instead of the
    operator-configured cap. Both must take the same drain path."""
    _ = client
    _seed(8)
    call_lock = threading.Lock()
    call_counter = {"n": 0}

    def _fake_extract(session, *, document, tier):
        with call_lock:
            call_counter["n"] += 1
            n = call_counter["n"]
        if n <= 2:
            return _ok_summary(document)
        raise LLMQuotaExhaustedError(
            "OpenAI quota exhausted: Error code: 429 - insufficient_quota"
        )

    monkeypatch.setattr(mod, "extract_and_persist_structured", _fake_extract)
    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=(1990, 2025), concurrency=4,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )

    assert totals["haiku"]["done"] == 2
    assert totals["failures"] == 0
    assert totals["spent_usd"] == pytest.approx(0.02, abs=1e-9)


def test_concurrent_ordinary_exception_still_marks_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression fence: a non-stop-signal exception (e.g. JSON
    parse error, network blip) must STILL be caught as a per-doc
    ``"FAILED"`` and counted in ``totals['failures']``. The PR #15
    behaviour change is targeted at the two cap exceptions only."""
    _ = client
    _seed(5)
    call_lock = threading.Lock()
    call_counter = {"n": 0}

    def _fake_extract(session, *, document, tier):
        with call_lock:
            call_counter["n"] += 1
            n = call_counter["n"]
        if n in (2, 4):
            # Generic exception — neither cap nor quota subclass.
            raise RuntimeError("oops, transient blip")
        return _ok_summary(document)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _fake_extract)
    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=(1990, 2025), concurrency=2,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )

    # 5 seeded - 2 failures = 3 successful.
    assert totals["haiku"]["done"] == 3
    # Two failures from the RuntimeError-emitting calls (positions 2 and 4).
    assert totals["failures"] == 2
    # Spend matches 3 successful calls.
    assert totals["spent_usd"] == pytest.approx(0.03, abs=1e-9)


# ---------- Sequential path: cap exits the bucket immediately -----


def test_sequential_daily_cap_exits_bucket_without_failures(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sequential mode (``concurrency=1``) hits the cap on doc N
    and must break out of the bucket loop — NOT continue iterating
    and counting subsequent docs as failures."""
    _ = client
    _seed(6)
    call_counter = {"n": 0}

    def _fake_extract(session, *, document, tier):
        call_counter["n"] += 1
        if call_counter["n"] <= 2:
            return _ok_summary(document)
        raise LLMDailyCapReachedError(
            "Layer 2 daily cap reached: $40.00 spent today."
        )

    monkeypatch.setattr(mod, "extract_and_persist_structured", _fake_extract)
    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=(1990, 2025), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )

    # 2 successful, then cap fires on call 3 — we exit.
    assert totals["haiku"]["done"] == 2
    assert totals["failures"] == 0
    # Critical: total calls made == 3 (2 OK + 1 cap-failure). The
    # remaining 3 docs were NOT attempted (no spin).
    assert call_counter["n"] == 3


def test_sequential_quota_exhausted_exits_bucket_without_failures(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same shape with the upstream-provider quota exception."""
    _ = client
    _seed(6)
    call_counter = {"n": 0}

    def _fake_extract(session, *, document, tier):
        call_counter["n"] += 1
        if call_counter["n"] <= 1:
            return _ok_summary(document)
        raise LLMQuotaExhaustedError(
            "OpenAI quota exhausted: insufficient_quota"
        )

    monkeypatch.setattr(mod, "extract_and_persist_structured", _fake_extract)
    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=(1990, 2025), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )

    assert totals["haiku"]["done"] == 1
    assert totals["failures"] == 0
    # 1 OK + 1 cap-failure = 2 calls made; remaining 4 docs not attempted.
    assert call_counter["n"] == 2


def test_sequential_ordinary_exception_still_marks_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression fence for sequential mode: ordinary exceptions
    still count as per-doc failures and the loop continues."""
    _ = client
    _seed(4)
    call_counter = {"n": 0}

    def _fake_extract(session, *, document, tier):
        call_counter["n"] += 1
        if call_counter["n"] == 2:
            raise RuntimeError("transient")
        return _ok_summary(document)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _fake_extract)
    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=(1990, 2025), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )

    # 3 OK + 1 failure; loop continued past the failure.
    assert totals["haiku"]["done"] == 3
    assert totals["failures"] == 1
    assert call_counter["n"] == 4


# ---------- ensure_daily_cap raises the typed subclass ------------


def test_ensure_daily_cap_raises_typed_subclass_when_over(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap helper must raise ``LLMDailyCapReachedError``
    specifically — not the generic ``LLMProviderError`` — so the
    worker can distinguish it from per-doc failures."""
    _ = client
    from sqlalchemy import text

    from caseops_api.core.settings import get_settings
    from caseops_api.services.corpus_structured import (
        ensure_daily_cap_not_exceeded,
    )
    monkeypatch.setenv("CASEOPS_LAYER2_DAILY_CAP_USD", "0.01")
    get_settings.cache_clear()
    factory = get_session_factory()
    s = factory()
    try:
        # Seed a metadata_extract row that exceeds the tiny cap.
        s.execute(
            text(
                "INSERT INTO model_runs "
                "(id, purpose, provider, model, prompt_tokens, "
                " completion_tokens, latency_ms, status, created_at) "
                "VALUES (:id, :p, :pv, :m, :pt, :ct, 0, 'ok', CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(uuid.uuid4()), "p": "metadata_extract",
                "pv": "openai", "m": "gpt-5.1",
                "pt": 5_000, "ct": 1_000,
            },
        )
        s.commit()
        with pytest.raises(LLMDailyCapReachedError) as exc:
            ensure_daily_cap_not_exceeded(s)
        # Defence in depth: it's still a LLMProviderError (parent).
        assert isinstance(exc.value, LLMProviderError)
    finally:
        s.close()
