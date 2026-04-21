"""Targeted Layer-2 re-extract — predicate gate + detector + sweep."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_title_reextract import (
    ReextractOutcome,
    ReextractReport,
    find_placeholder_title_docs,
    reextract_title,
    run_reextract_sweep,
)
from caseops_api.services.corpus_title_validation import title_is_case_name

# Windows SQLite teardown leaks a file handle on the seed path when
# tests go through AuthorityDocument directly — mirrors the guard in
# `test_eval_hnsw_recall.py`.
_skip_seed_on_windows = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Windows SQLite tmp_path teardown leaks — covered on POSIX CI",
)


def _seed_doc(*, title: str, document_text: str = "") -> str:
    from caseops_api.db.models import utcnow
    Session = get_session_factory()
    session = Session()
    try:
        doc = AuthorityDocument(
            source="test-fixture",
            adapter_name="test",
            court_name="Supreme Court of India",
            forum_level="supreme_court",
            document_type="judgment",
            title=title,
            canonical_key=f"test::reextract::{title}::{document_text[:20]}",
            summary=f"fixture summary for {title}",
            structured_version=1,
            document_text=document_text,
            ingested_at=utcnow(),
        )
        session.add(doc)
        session.flush()
        # Seed an existing metadata chunk so we can prove _apply_new_title
        # archives it on accept.
        chunk = AuthorityDocumentChunk(
            authority_document_id=doc.id,
            chunk_index=0,
            chunk_role="metadata",
            content=f"OLD TITLE CHUNK: {title}",
            created_at=datetime.now(UTC),
        )
        session.add(chunk)
        session.commit()
        return doc.id
    finally:
        session.close()
        if session.bind is not None:
            session.bind.dispose()


@dataclass
class _FakeCompletion:
    prompt_tokens: int
    completion_tokens: int
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    latency_ms: int = 10


class _StubProvider:
    """Provider stub — bypasses generate_structured by monkey-patching."""
    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model


# ---------------------------------------------------------------
# Detector (the SQL filter matches the skill's hygiene patterns).
# ---------------------------------------------------------------


@_skip_seed_on_windows
def test_detector_flags_bench_placeholder_only_by_default(client) -> None:
    """The detector flags docs whose `title` is a bench placeholder,
    OCR gibberish, non-Latin, court-header, or too-short. Valid case
    names pass through untouched."""
    from tests.test_auth_company import bootstrap_company
    bootstrap_company(client)
    good_id = _seed_doc(
        title="Basavaraj Bagewadi v. State of Karnataka",
        document_text="IN THE SUPREME COURT OF INDIA ...",
    )
    bench_id = _seed_doc(title="DHARWAD BENCH", document_text="...")
    short_id = _seed_doc(title="Order", document_text="...")
    court_id = _seed_doc(
        title="IN THE HIGH COURT OF KARNATAKA", document_text="...",
    )

    Session = get_session_factory()
    with Session() as session:
        flagged = find_placeholder_title_docs(session, limit=50)
    flagged_ids = {row[0] for row in flagged}
    assert good_id not in flagged_ids
    assert bench_id in flagged_ids
    assert short_id in flagged_ids
    assert court_id in flagged_ids


# ---------------------------------------------------------------
# Predicate gate on reextract_title — bad model output NEVER
# overwrites the existing title.
# ---------------------------------------------------------------


@_skip_seed_on_windows
def test_reextract_accepts_valid_case_name(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_auth_company import bootstrap_company
    bootstrap_company(client)
    doc_id = _seed_doc(
        title="DHARWAD BENCH",
        document_text="In the matter of Arun Kumar v. State of Karnataka...",
    )

    # Stub generate_structured so no real LLM call happens.
    def _fake_generate_structured(
        provider, *, schema, messages, context, max_tokens, session,
    ):
        return (
            schema(title="Arun Kumar v. State of Karnataka"),
            _FakeCompletion(prompt_tokens=500, completion_tokens=20),
        )
    monkeypatch.setattr(
        "caseops_api.services.corpus_title_reextract.generate_structured",
        _fake_generate_structured,
    )

    Session = get_session_factory()
    with Session() as session:
        outcome = reextract_title(
            session,
            doc_id=doc_id,
            current_title="DHARWAD BENCH",
            document_text="Some text",
            provider=_StubProvider(),  # type: ignore[arg-type]
            tenant_id="test-tenant",
        )
        session.commit()

    assert outcome.accepted is True
    assert outcome.reason == "accepted"
    assert outcome.new_title == "Arun Kumar v. State of Karnataka"
    assert outcome.cost_usd > 0

    # Title was persisted; stale metadata chunk was dropped.
    with Session() as session:
        doc = session.get(AuthorityDocument, doc_id)
        assert doc.title == "Arun Kumar v. State of Karnataka"
        metadata_chunks = [c for c in doc.chunks if c.chunk_role == "metadata"]
        assert metadata_chunks == []


@_skip_seed_on_windows
def test_reextract_rejects_placeholder_from_llm(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the LLM returns another placeholder string (say ``"DHARWAD
    BENCH"`` again because the page-header dominates the input), the
    predicate must reject and the doc's title must NOT be overwritten."""
    from tests.test_auth_company import bootstrap_company
    bootstrap_company(client)
    doc_id = _seed_doc(title="DHARWAD BENCH", document_text="text")

    def _fake_generate_structured(
        provider, *, schema, messages, context, max_tokens, session,
    ):
        return (
            schema(title="DHARWAD BEN CH"),  # still a placeholder
            _FakeCompletion(prompt_tokens=500, completion_tokens=20),
        )
    monkeypatch.setattr(
        "caseops_api.services.corpus_title_reextract.generate_structured",
        _fake_generate_structured,
    )

    Session = get_session_factory()
    with Session() as session:
        outcome = reextract_title(
            session,
            doc_id=doc_id,
            current_title="DHARWAD BENCH",
            document_text="text",
            provider=_StubProvider(),  # type: ignore[arg-type]
            tenant_id="test-tenant",
        )

    assert outcome.accepted is False
    assert outcome.reason.startswith("predicate:")
    # Original title is untouched.
    with Session() as session:
        doc = session.get(AuthorityDocument, doc_id)
        assert doc.title == "DHARWAD BENCH"


@_skip_seed_on_windows
def test_reextract_handles_null_return(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the LLM returns ``null`` (no case name in the first pages
    — e.g. translation cover), the row stays unchanged but the outcome
    tallies as ``llm_returned_null``."""
    from tests.test_auth_company import bootstrap_company
    bootstrap_company(client)
    doc_id = _seed_doc(title="Translation Cover", document_text="...")

    def _fake_generate_structured(
        provider, *, schema, messages, context, max_tokens, session,
    ):
        return (
            schema(title=None),
            _FakeCompletion(prompt_tokens=300, completion_tokens=10),
        )
    monkeypatch.setattr(
        "caseops_api.services.corpus_title_reextract.generate_structured",
        _fake_generate_structured,
    )

    Session = get_session_factory()
    with Session() as session:
        outcome = reextract_title(
            session,
            doc_id=doc_id,
            current_title="Translation Cover",
            document_text="...",
            provider=_StubProvider(),  # type: ignore[arg-type]
            tenant_id="test-tenant",
        )

    assert outcome.accepted is False
    assert outcome.reason == "llm_returned_null"
    assert outcome.new_title is None


def test_reextract_skips_empty_document_text(client) -> None:
    """A doc with no text to extract from can't be improved by the LLM.
    Return an ``empty_document`` outcome without spending tokens."""
    Session = get_session_factory()
    with Session() as session:
        outcome = reextract_title(
            session,
            doc_id="no-such-id",
            current_title="DHARWAD BENCH",
            document_text="",
            provider=_StubProvider(),  # type: ignore[arg-type]
            tenant_id="test-tenant",
        )
    assert outcome.accepted is False
    assert outcome.reason == "empty_document"
    assert outcome.cost_usd == 0.0


# ---------------------------------------------------------------
# Sweep orchestration — dry-run + budget cap.
# ---------------------------------------------------------------


@_skip_seed_on_windows
def test_dry_run_counts_without_spending(client) -> None:
    from tests.test_auth_company import bootstrap_company
    bootstrap_company(client)
    _seed_doc(title="DHARWAD BENCH", document_text="x")
    _seed_doc(title="BENCH AT AURANGABAD", document_text="x")
    _seed_doc(title="Arun Kumar v. State of Karnataka", document_text="x")

    Session = get_session_factory()
    with Session() as session:
        report = run_reextract_sweep(
            session,
            provider=None,  # type: ignore[arg-type]
            tenant_id="test-tenant",
            budget_usd=0.0,
            limit=10,
            dry_run=True,
        )
    assert report.attempted >= 2  # the two placeholder docs
    assert report.accepted == 0
    assert report.total_cost_usd == 0.0
    assert report.skip_reasons.get("bench_header_or_thin", 0) >= 2


@_skip_seed_on_windows
def test_sweep_stops_at_budget_cap(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep must stop once ``total_cost_usd`` crosses the cap —
    protects against runaway LLM spend."""
    from tests.test_auth_company import bootstrap_company
    bootstrap_company(client)
    for i in range(5):
        _seed_doc(title=f"DHARWAD BEN CH {i}", document_text="some text")

    # Each call costs $0.10 — 3 calls is $0.30 which exceeds our $0.20 cap.
    call_count = {"n": 0}

    def _fake_generate_structured(
        provider, *, schema, messages, context, max_tokens, session,
    ):
        call_count["n"] += 1
        return (
            schema(title="Arun Kumar v. State"),
            # Roughly $0.10 — 125000 prompt tokens * 0.80/1M = $0.10.
            _FakeCompletion(prompt_tokens=125_000, completion_tokens=0),
        )
    monkeypatch.setattr(
        "caseops_api.services.corpus_title_reextract.generate_structured",
        _fake_generate_structured,
    )

    Session = get_session_factory()
    with Session() as session:
        report = run_reextract_sweep(
            session,
            provider=_StubProvider(),  # type: ignore[arg-type]
            tenant_id="test-tenant",
            budget_usd=0.20,
            limit=10,
            dry_run=False,
        )

    assert report.total_cost_usd >= 0.20
    assert report.total_cost_usd < 0.40  # stopped within one call of the cap
    # Did NOT attempt all 5 docs.
    assert call_count["n"] < 5


# ---------------------------------------------------------------
# Predicate import surface — sanity.
# ---------------------------------------------------------------


def test_predicate_is_shared_module() -> None:
    """Both the probe and the re-extract must pull the predicate from
    the shared service — if someone copies it back into either script
    we lose the 'fix at the source' guarantee."""
    from caseops_api.scripts import eval_hnsw_recall
    assert eval_hnsw_recall._title_is_case_name is title_is_case_name


def test_report_dataclass_starts_empty() -> None:
    r = ReextractReport()
    assert r.attempted == 0
    assert r.accepted == 0
    assert r.total_cost_usd == 0.0
    assert r.skip_reasons == {}
    assert r.outcomes == []


def test_outcome_dataclass_fields() -> None:
    o = ReextractOutcome(
        doc_id="x", old_title="old", new_title="new",
        accepted=True, reason="accepted", cost_usd=0.01,
    )
    assert o.accepted is True
    assert o.cost_usd == 0.01
