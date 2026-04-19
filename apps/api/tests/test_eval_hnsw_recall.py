"""Sprint 11 — HNSW recall@k benchmark plumbing."""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from datetime import date

import pytest
from sqlalchemy import select

from caseops_api.db.models import (
    AuthorityDocument,
    EvaluationCase,
    EvaluationRun,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.eval_hnsw_recall import (
    _build_query,
    _Probe,
    _sample_probes,
    main,
)
from tests.test_auth_company import bootstrap_company

# Tests that seed AuthorityDocument rows via a separate Session leak
# a SQLite file handle on Windows that the conftest's
# os.remove(database_path) at teardown can't clear, even with explicit
# session.close() + bind.dispose(). The skip is platform-only — these
# pass cleanly on POSIX (macOS / Linux / CI). The dry-run, helper, and
# unknown-tenant tests below give us full plumbing coverage on Windows
# without touching the AuthorityDocument table directly.
_skip_seed_on_windows = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Windows SQLite file-lock race on tmp_path teardown — covered on POSIX CI",
)


def _slug(client) -> str:
    return str(bootstrap_company(client)["company"]["slug"])


def _seed_doc(
    *,
    title: str,
    structured_version: int | None = 1,
    decision_date: date | None = None,
) -> str:
    """Drop a synthetic AuthorityDocument into the test DB and return
    its id. Layer-2 docs (``structured_version IS NOT NULL``) are
    eligible for sampling."""
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
            canonical_key=f"test::{title}",
            summary=f"Test fixture summary for {title}",
            decision_date=decision_date,
            structured_version=structured_version,
            ingested_at=utcnow(),
        )
        session.add(doc)
        session.commit()
        return doc.id
    finally:
        # Force handle release on Windows SQLite — without this, the
        # tmp_path teardown's os.remove(db_path) hits WinError 32 from
        # a still-open connection. Disposing the bound engine drops
        # all pooled connections deterministically.
        session.close()
        if session.bind is not None:
            session.bind.dispose()


def test_build_query_strips_noise_and_punctuation() -> None:
    out = _build_query("M/s. Bharat Textiles vs. State of Karnataka, AIR 2024 SC 1042")
    # Noise like "vs." and punctuation gone; meaningful tokens kept.
    assert "Bharat" in out
    assert "Textiles" in out
    assert "Karnataka" in out
    assert "vs." not in out
    assert "AIR" in out  # still useful for retrieval
    # Caps to 10 words.
    assert len(out.split()) <= 10


def test_build_query_falls_back_when_only_noise() -> None:
    out = _build_query("In the Hon'ble Supreme Court of India")
    # Falls back to original (truncated) — never empty.
    assert out
    assert len(out) <= 120


def test_build_query_handles_empty_or_none() -> None:
    assert _build_query("") == "judgment"
    assert _build_query("   ") == "judgment"


@_skip_seed_on_windows
def test_sample_probes_only_pulls_layer_2_docs(client) -> None:
    bootstrap_company(client)
    layer2_id = _seed_doc(title="Tata Sons v Siva Industries", structured_version=2)
    _seed_doc(title="Some Pre-Layer-2 Doc", structured_version=None)

    Session = get_session_factory()
    with Session() as session:
        probes = _sample_probes(session, sample_size=10, seed=0)
    ids = {p.document_id for p in probes}
    assert layer2_id in ids
    # The pre-layer-2 doc must NOT be sampled.
    pre = session.query(AuthorityDocument).filter_by(
        title="Some Pre-Layer-2 Doc"
    ).one()
    assert pre.id not in ids


@_skip_seed_on_windows
def test_sample_probes_respects_seed_for_reproducibility(client) -> None:
    bootstrap_company(client)
    for i in range(20):
        _seed_doc(title=f"Doc number {i}", structured_version=1)
    Session = get_session_factory()
    with Session() as session:
        a = _sample_probes(session, sample_size=5, seed=123)
        b = _sample_probes(session, sample_size=5, seed=123)
    assert [p.document_id for p in a] == [p.document_id for p in b]


def test_dry_run_records_empty_run(client) -> None:
    slug = _slug(client)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--tenant", slug, "--dry-run"])
    assert rc == 0
    Session = get_session_factory()
    with Session() as session:
        run = session.scalars(
            select(EvaluationRun).where(EvaluationRun.suite_name == "hnsw-recall")
        ).first()
        assert run is not None
        assert run.case_count == 0  # dry-run records no probes


def test_run_returns_1_when_corpus_has_no_layer_2_docs(client, capsys) -> None:
    """If nobody has run the structured backfill yet, the eval can't
    pick a sample. Surface that as exit=1 with a stderr hint instead
    of silently passing."""
    slug = _slug(client)
    rc = main(["--tenant", slug])
    assert rc == 1
    captured = capsys.readouterr()
    assert "no Layer-2 docs" in captured.err


def test_unknown_tenant_exits_clean(client) -> None:
    bootstrap_company(client)
    with pytest.raises(SystemExit) as exc:
        main(["--tenant", "no-such-tenant"])
    assert "company" in str(exc.value).lower()


@_skip_seed_on_windows
def test_full_path_records_per_doc_metrics(client) -> None:
    """End-to-end: seed a Layer-2 doc, run with sample_size=1, verify
    a case row exists with the expected per-probe metrics shape."""
    slug = _slug(client)
    _seed_doc(
        title="Self-consistency Probe Doc",
        structured_version=1,
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--tenant", slug, "--sample-size", "1"])
    # Likely a miss (no chunks indexed for the synthetic doc), so
    # rc == 1 is expected. We only assert the plumbing.
    assert rc in (0, 1)
    Session = get_session_factory()
    with Session() as session:
        run = session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.suite_name == "hnsw-recall")
            .order_by(EvaluationRun.created_at.desc())
        ).first()
        assert run is not None
        cases = list(session.scalars(
            select(EvaluationCase).where(EvaluationCase.run_id == run.id)
        ))
        assert len(cases) == 1
        import json
        payload = json.loads(cases[0].findings_json)
        extra = payload["extra"]
        assert "rank" in extra
        assert "found" in extra
        assert "result_count" in extra
        assert "query" in extra


def test_probe_dataclass_is_immutable() -> None:
    from dataclasses import FrozenInstanceError
    p = _Probe(document_id="x", title="t", query="q")
    with pytest.raises(FrozenInstanceError):
        p.document_id = "y"  # type: ignore[misc]
