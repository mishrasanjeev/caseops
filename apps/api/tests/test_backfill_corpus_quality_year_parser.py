"""Coverage for the multi-source year extractor on the Layer-2
backfill candidate selector.

Anchor: 2026-05-04 ingest VM probe revealed the original year parser
was 100 % broken on HC docs. ``DLHC010000672024_1_2024-02-08.pdf``
and every other HC filename starts with the court code, not the
year, so the SC-shaped regex ``(?:^|/)(\\d{4})_`` matched zero of
the 45,392 HC docs. Default ``--english-only`` invocation rejected
all 45 K HC docs as "year unparseable" — exactly the docs the
operator wanted in scope.

This file pins the three-source extractor (``sc_filename``,
``hc_trailing_date``, ``decision_date``) and the per-source
counters reported at triage time.
"""
from __future__ import annotations

import threading
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import backfill_corpus_quality as mod
from caseops_api.services.corpus_structured import StructuredExtractionSummary

# ---------- _year_and_source_for_doc unit tests -------------------


def _doc(
    *,
    source_ref: str | None = None,
    decision_date: date | None = None,
    forum: str = "supreme_court",
) -> AuthorityDocument:
    return AuthorityDocument(
        id=f"unit-{uuid.uuid4().hex[:8]}",
        source="ecourts",
        adapter_name="corpus-ingest",
        court_name="Test Court",
        forum_level=forum,
        document_type="judgment",
        title="English title v. State",
        canonical_key=f"k-{uuid.uuid4().hex[:8]}",
        source_reference=source_ref,
        summary="",
        document_text="The petitioner appeals.",
        extracted_char_count=20,
        structured_version=None,
        decision_date=decision_date,
    )


def test_sc_filename_pattern_returns_sc_filename_source() -> None:
    """SC ecourts pattern: ``YYYY_X_Y_Z_LANG.pdf``."""
    doc = _doc(source_ref="sc/2024/2011_8_723_724_EN.pdf")
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2011
    assert src == "sc_filename"


def test_sc_filename_at_root_no_path_prefix() -> None:
    doc = _doc(source_ref="2025_1_1_5_EN.pdf")
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2025
    assert src == "sc_filename"


def test_hc_trailing_date_pattern_returns_hc_source() -> None:
    """HC pattern: ``DLHC<id><year>_<n>_<yyyy>-<mm>-<dd>.pdf``."""
    doc = _doc(source_ref="DLHC010000672024_1_2024-02-08.pdf", forum="high_court")
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2024
    assert src == "hc_trailing_date"


def test_hc_trailing_date_strips_path_prefix() -> None:
    """Path-prefixed HC filenames still resolve via the trailing-date
    pattern; the prefix doesn't fool the regex."""
    doc = _doc(
        source_ref="hc/delhi/2024/DLHC010113452025_1_2025-11-26.pdf",
        forum="high_court",
    )
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2025
    assert src == "hc_trailing_date"


def test_hc_trailing_date_without_pdf_extension_still_matches() -> None:
    """Some HC drops omit the ``.pdf`` suffix in source_reference;
    the regex tolerates either."""
    doc = _doc(
        source_ref="DLHC010113452025_1_2025-11-26",
        forum="high_court",
    )
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2025
    assert src == "hc_trailing_date"


def test_decision_date_fallback_when_filename_unparseable() -> None:
    """No-year filename + ``decision_date`` populated → use
    decision_date.year."""
    doc = _doc(
        source_ref="weird-format-no-year.pdf",
        decision_date=date(2020, 1, 2),
    )
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2020
    assert src == "decision_date"


def test_decision_date_fallback_when_source_reference_null() -> None:
    doc = _doc(source_ref=None, decision_date=date(2018, 6, 15))
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2018
    assert src == "decision_date"


def test_unparseable_returns_none_with_unparseable_label() -> None:
    """All three sources fail → return ``(None, "unparseable")``.
    Non-None source label so the counter still attributes the doc."""
    doc = _doc(source_ref="weird-format-no-year.pdf", decision_date=None)
    year, src = mod._year_and_source_for_doc(doc)
    assert year is None
    assert src == "unparseable"


def test_unparseable_when_both_sources_missing() -> None:
    doc = _doc(source_ref=None, decision_date=None)
    year, src = mod._year_and_source_for_doc(doc)
    assert year is None
    assert src == "unparseable"


def test_sc_filename_takes_precedence_over_decision_date() -> None:
    """When SC filename has a year AND decision_date is set, the
    filename year wins. Empirically more reliable than ingest-time
    date guessing on cover-page text."""
    doc = _doc(
        source_ref="sc/2024/2011_8_723_724_EN.pdf",
        decision_date=date(2099, 1, 1),
    )
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2011
    assert src == "sc_filename"


def test_hc_trailing_date_takes_precedence_over_decision_date() -> None:
    doc = _doc(
        source_ref="DLHC010000672024_1_2024-02-08.pdf",
        forum="high_court",
        decision_date=date(2099, 1, 1),
    )
    year, src = mod._year_and_source_for_doc(doc)
    assert year == 2024
    assert src == "hc_trailing_date"


def test_legacy_year_for_doc_returns_int_only() -> None:
    """Backward-compat: existing callers (sort keys etc.) still get
    an ``int | None``."""
    doc = _doc(source_ref="2011_1_1_5_EN.pdf")
    assert mod._year_for_doc(doc) == 2011
    assert mod._year_for_doc(_doc(source_ref=None)) is None


# ---------- Integration: HC 1990-2025 now in pool ------------------


def _seed_hc_and_sc_mix(
    *, n_hc_in_range: int, n_hc_out_of_range: int,
    n_sc_in_range: int, n_sc_devanagari: int,
) -> dict[str, list[str]]:
    """Seed HC docs (with trailing-date filenames) and SC docs (with
    ecourts ``YYYY_..._EN.pdf`` and Devanagari content respectively).
    Returns ids by group for assertions."""
    factory = get_session_factory()
    s = factory()
    out: dict[str, list[str]] = {
        "hc_in": [], "hc_out": [], "sc_en": [], "sc_dev": [],
    }
    try:
        for i in range(n_hc_in_range):
            doc_id = f"hc-in-{i:02d}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts-hc", adapter_name="corpus-ingest",
                court_name="Delhi High Court", forum_level="high_court",
                document_type="judgment", title="HC English Case v. State",
                canonical_key=f"k-{doc_id}",
                source_reference=f"DLHC0100006720{i:02d}_1_2024-02-08.pdf",
                summary="", document_text="The petitioner appeals.",
                extracted_char_count=20, structured_version=None,
            ))
            out["hc_in"].append(doc_id)
        for i in range(n_hc_out_of_range):
            doc_id = f"hc-out-{i:02d}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts-hc", adapter_name="corpus-ingest",
                court_name="Delhi High Court", forum_level="high_court",
                document_type="judgment", title="HC Pre-1990 Case",
                canonical_key=f"k-{doc_id}",
                source_reference=f"DLHC0100006719{i:02d}_1_1985-02-08.pdf",
                summary="", document_text="Old HC case.",
                extracted_char_count=20, structured_version=None,
            ))
            out["hc_out"].append(doc_id)
        for i in range(n_sc_in_range):
            doc_id = f"sc-en-{i:02d}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts-sc", adapter_name="corpus-ingest",
                court_name="Supreme Court of India",
                forum_level="supreme_court",
                document_type="judgment", title="SC English Case v. State",
                canonical_key=f"k-{doc_id}",
                source_reference=f"sc/2024/2024_1_{i}_5_EN.pdf",
                summary="", document_text="The petitioner appeals.",
                extracted_char_count=20, structured_version=None,
            ))
            out["sc_en"].append(doc_id)
        for i in range(n_sc_devanagari):
            doc_id = f"sc-dev-{i:02d}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts-sc", adapter_name="corpus-ingest",
                court_name="Supreme Court of India",
                forum_level="supreme_court",
                document_type="judgment", title="राज्य v. शर्मा",
                canonical_key=f"k-{doc_id}",
                source_reference=f"sc/2024/2024_2_{i}_5.pdf",
                summary="", document_text="देवनागरी text body",
                extracted_char_count=20, structured_version=None,
            ))
            out["sc_dev"].append(doc_id)
        s.commit()
    finally:
        s.close()
    return out


def _fake_summary(session, *, document, tier: str) -> StructuredExtractionSummary:
    _ = (session, tier)
    return StructuredExtractionSummary(
        document_id=document.id,
        chunks_annotated=0,
        provider="openai", model="gpt-5-mini",
        prompt_tokens=100, completion_tokens=20,
        cost_usd=0.01, quality_score=0.9, quality_issues=(),
    )


def test_year_filter_includes_hc_docs_after_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PR #12 anchor: HC docs in [1990, 2025] previously dropped
    100 % at the year filter because the SC regex never matched. With
    the trailing-date fallback they now enter the bucket. SC EN docs
    in range still process, Devanagari SC docs still get filtered,
    pre-1990 HC docs still get filtered."""
    _ = client
    seeded = _seed_hc_and_sc_mix(
        n_hc_in_range=4, n_hc_out_of_range=2,
        n_sc_in_range=3, n_sc_devanagari=2,
    )
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
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=(1990, 2025), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )
    expected = set(seeded["hc_in"]) | set(seeded["sc_en"])
    assert set(seen) == expected, (
        f"missing: {expected - set(seen)}  unexpected: {set(seen) - expected}"
    )
    assert totals["standard"]["candidates"] == len(expected)


def test_non_english_filter_still_excludes_devanagari_after_year_pass(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression fence: PR #10's EN filter must still work after PR
    #12's year-parser change. Devanagari SC docs whose filenames pass
    the SC year regex (``2024_2_X_5.pdf``) must still be rejected by
    the non-EN content probe."""
    _ = client
    seeded = _seed_hc_and_sc_mix(
        n_hc_in_range=0, n_hc_out_of_range=0,
        n_sc_in_range=2, n_sc_devanagari=3,
    )
    seen: list[str] = []

    def _capture(session, *, document, tier):
        seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)
    factory = get_session_factory()
    with factory() as session:
        mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=(1990, 2025), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )
    assert set(seen) == set(seeded["sc_en"])
    for d in seeded["sc_dev"]:
        assert d not in seen


# ---------- Triage-only mode ---------------------------------------


def test_triage_only_returns_counts_without_calling_llm(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``triage_only=True`` prints the counts and returns BEFORE any
    LLM call. The fake provider would record entries in ``seen`` if it
    were called; we assert ``seen`` stays empty."""
    _ = client
    seeded = _seed_hc_and_sc_mix(
        n_hc_in_range=2, n_hc_out_of_range=1,
        n_sc_in_range=2, n_sc_devanagari=1,
    )
    _ = seeded  # only used for the seed call's side effect
    seen: list[str] = []

    def _capture(session, *, document, tier):
        seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)
    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="standard", year_range=(1990, 2025), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
            triage_only=True,
        )
    # No LLM calls made.
    assert seen == []
    # Triage payload is shaped for the `triage-only:` stdout line.
    assert totals.get("triage_only") is True
    assert totals["standard"]["candidates"] == 4  # 2 HC in-range + 2 SC EN
    assert totals["premium"]["candidates"] == 0
    ys = totals["year_sources"]
    # 2 HC in-range + 1 HC out-of-range = 3 hc_trailing_date matches
    # 2 SC EN + 1 SC Devanagari = 3 sc_filename matches
    assert ys["hc_trailing_date"] == 3
    assert ys["sc_filename"] == 3
    # Pre-1990 HC doc is rejected by year_range, but year_source still
    # increments because the year was extracted successfully.
    assert ys["unparseable"] == 0


def test_main_triage_only_flag_threads_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _spy_run(**kwargs) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "run", _spy_run)
    mod.main(["--stage", "structured", "--triage-only"])
    assert captured["triage_only"] is True


def test_main_triage_only_default_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _spy_run(**kwargs) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "run", _spy_run)
    mod.main(["--stage", "structured"])
    assert captured["triage_only"] is False
