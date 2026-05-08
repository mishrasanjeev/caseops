"""Coverage for the EN-only / forum / year filter on the Layer-2
backfill candidate selector.

Anchor: 2026-05-04 ingest VM probe showed 37 % of the haiku candidate
pool was Devanagari-content SC docs that always fail Layer-2 with
malformed JSON. The fix filters them out at triage time and reduces
the realistic candidate count to ~14K English SC docs + remaining
HC docs in [1990, 2025]. These tests pin the detector behaviour so
the filter can't silently regress and resurrect non-EN noise into a
future sweep.
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

# -- _doc_appears_english unit tests -------------------------------


def _doc(
    *,
    title: str = "Some English Title v. State",
    text: str = "x" * 200,
    source_ref: str | None = None,
    forum: str = "supreme_court",
) -> AuthorityDocument:
    """Build an AuthorityDocument in memory (no DB session needed for
    pure-detector tests)."""
    return AuthorityDocument(
        id=f"unit-{uuid.uuid4().hex[:8]}",
        source="ecourts-sc",
        adapter_name="corpus-ingest",
        court_name="Supreme Court of India",
        forum_level=forum,
        document_type="judgment",
        title=title,
        canonical_key=f"k-{uuid.uuid4().hex[:8]}",
        source_reference=source_ref,
        summary="",
        document_text=text,
        extracted_char_count=len(text),
        structured_version=None,
    )


def test_appears_english_when_suffix_is_en_pdf() -> None:
    doc = _doc(source_ref="sc/2024/2024_5_123_140_EN.pdf")
    assert mod._doc_appears_english(doc) is True


def test_appears_english_case_insensitive_suffix() -> None:
    doc = _doc(source_ref="sc/2024/2024_5_123_140_en.PDF".lower())
    assert mod._doc_appears_english(doc) is True


def test_rejects_explicit_non_en_file_suffixes() -> None:
    for tag in ("HIN", "PUN", "BEN", "GUJ", "TAM", "TEL", "KAN",
                "MAL", "ORI", "NEP", "SAN", "URD", "ASM", "MAR"):
        doc = _doc(source_ref=f"sc/2024/2024_5_123_140_{tag}.pdf")
        assert mod._doc_appears_english(doc) is False, f"failed for {tag}"


def test_rejects_devanagari_in_title_when_no_suffix() -> None:
    doc = _doc(
        title="राज्य Government v. Sharma",
        source_ref="sc/2024/2024_5_123_140.pdf",
    )
    assert mod._doc_appears_english(doc) is False


def test_rejects_tamil_in_document_text_head() -> None:
    # Tamil U+0BAE U+0BBE U+0BA9 = "மான்" — three Tamil characters
    # in the first 2000 chars are sufficient for rejection.
    doc = _doc(
        title="Clean English Title",
        text="Clean English head text மான mixed in.",
        source_ref="sc/2024/2024_5_123_140.pdf",
    )
    assert mod._doc_appears_english(doc) is False


def test_accepts_when_no_suffix_and_no_indic() -> None:
    doc = _doc(
        title="Clean English Title",
        text="The petitioner challenges the order of the High Court.",
        source_ref="sc/2024/2024_5_123_140.pdf",
    )
    assert mod._doc_appears_english(doc) is True


def test_appears_english_handles_null_source_reference() -> None:
    doc = _doc(source_ref=None)
    assert mod._doc_appears_english(doc) is True


def test_indic_beyond_probe_window_is_ignored() -> None:
    """A doc with English head and Devanagari deep in the body is
    accepted — we only probe the first ``_LANG_PROBE_CHARS``. This
    matches the Layer-2 prompt which truncates anyway."""
    head = "x" * (mod._LANG_PROBE_CHARS + 100)
    tail = "राज्य"  # Devanagari "rajya"
    doc = _doc(text=head + tail, source_ref="sc/2024/2024.pdf")
    assert mod._doc_appears_english(doc) is True


# -- _structured_pass integration with the filter -------------------


def _seed_mixed(n_en_suffix: int, n_devanagari: int, n_hin_suffix: int) -> dict[str, list[str]]:
    """Seed three groups and return ids by group so tests can assert
    which were processed."""
    factory = get_session_factory()
    s = factory()
    out: dict[str, list[str]] = {"en": [], "devanagari": [], "hin": []}
    try:
        for i in range(n_en_suffix):
            doc_id = f"en-{i:02d}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts-sc", adapter_name="corpus-ingest",
                court_name="Supreme Court of India", forum_level="supreme_court",
                document_type="judgment", title="Clean English v. State",
                canonical_key=f"k-{doc_id}",
                source_reference=f"sc/2024/2024_1_{i}_5_EN.pdf",
                summary="", document_text="The petitioner appeals.",
                extracted_char_count=20, structured_version=None,
            ))
            out["en"].append(doc_id)
        for i in range(n_devanagari):
            doc_id = f"dev-{i:02d}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts-sc", adapter_name="corpus-ingest",
                court_name="Supreme Court of India", forum_level="supreme_court",
                document_type="judgment",
                title="राज्य v. शर्मा",
                canonical_key=f"k-{doc_id}",
                source_reference=f"sc/2024/2024_2_{i}_5.pdf",
                summary="",
                document_text="देवनागरी text body",
                extracted_char_count=20, structured_version=None,
            ))
            out["devanagari"].append(doc_id)
        for i in range(n_hin_suffix):
            doc_id = f"hin-{i:02d}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts-sc", adapter_name="corpus-ingest",
                court_name="Supreme Court of India", forum_level="supreme_court",
                document_type="judgment", title="Title (Hindi parallel)",
                canonical_key=f"k-{doc_id}",
                source_reference=f"sc/2024/2024_3_{i}_5_HIN.pdf",
                summary="", document_text="ascii head, hindi body elsewhere",
                extracted_char_count=30, structured_version=None,
            ))
            out["hin"].append(doc_id)
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


def test_english_only_filter_drops_devanagari_and_hin_suffix(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seed 3 EN + 2 Devanagari + 2 _HIN.pdf docs; with ``english_only``
    the run sees ONLY the 3 EN docs. The 4 non-EN docs never reach
    extract_and_persist_structured — no tokens spent."""
    _ = client
    seeded = _seed_mixed(n_en_suffix=3, n_devanagari=2, n_hin_suffix=2)
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
            force_tier="haiku", year_range=None, concurrency=1,
            english_only=True, forums=None,
        )
    assert sorted(seen) == sorted(seeded["en"])
    assert totals["haiku"]["candidates"] == 3
    # No spend on the 4 rejected docs.
    assert totals["spent_usd"] == pytest.approx(0.03, abs=1e-9)


def test_english_only_filter_off_processes_everything(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``english_only=False`` the filter is bypassed and every
    seeded doc enters the bucket — proves the flag isn't latched on."""
    _ = client
    seeded = _seed_mixed(n_en_suffix=2, n_devanagari=2, n_hin_suffix=1)
    seen: list[str] = []

    def _capture(session, *, document, tier):
        seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)
    factory = get_session_factory()
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=None, concurrency=1,
            english_only=False, forums=None,
        )
    expected = set(seeded["en"]) | set(seeded["devanagari"]) | set(seeded["hin"])
    assert set(seen) == expected
    assert totals["haiku"]["candidates"] == 5


def test_forum_filter_excludes_district_court(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default forum allowlist is {supreme_court, high_court}. Seed
    one of each forum; the district_court doc must not enter the bucket
    even though it's English and in-year."""
    _ = client
    factory = get_session_factory()
    s = factory()
    kept: list[str] = []
    dropped: list[str] = []
    try:
        for forum, bucket in (
            ("supreme_court", kept),
            ("high_court", kept),
            ("district_court", dropped),
            ("tribunal", dropped),
        ):
            doc_id = f"{forum}-{uuid.uuid4().hex[:6]}"
            s.add(AuthorityDocument(
                id=doc_id, source="ecourts", adapter_name="corpus-ingest",
                court_name=forum.replace("_", " ").title(), forum_level=forum,
                document_type="judgment", title="English Title v. State",
                canonical_key=f"k-{doc_id}",
                source_reference=f"{forum}/2024/2024_1_1_5_EN.pdf",
                summary="", document_text="The appellant submits.",
                extracted_char_count=20, structured_version=None,
            ))
            bucket.append(doc_id)
        s.commit()
    finally:
        s.close()

    seen: list[str] = []

    def _capture(session, *, document, tier):
        seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)
    with factory() as session:
        mod._structured_pass(
            session, limit=None, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=None, concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )
    assert set(seen) == set(kept)
    for d in dropped:
        assert d not in seen


def test_court_filter_accepts_hc_alias_and_limit_applies_after_court_filter(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--courts delhi --limit 1`` must process one Delhi candidate, not
    stop on an earlier same-year non-Delhi row.

    This keeps proof buckets strict by court. The previous selector had no
    court filter, so a Delhi HC proof could mutate other HC rows in the same
    forum/year cohort.
    """
    _ = client
    factory = get_session_factory()
    madras_id = f"madras-{uuid.uuid4().hex[:6]}"
    delhi_id = f"delhi-{uuid.uuid4().hex[:6]}"
    with factory() as s:
        s.add(AuthorityDocument(
            id=madras_id, source="ecourts-hc", adapter_name="corpus-ingest",
            court_name="Madras High Court", forum_level="high_court",
            document_type="judgment", title="Madras Candidate v. State",
            canonical_key=f"k-{madras_id}",
            source_reference="MADHC000000000001_1_2023-12-31.pdf",
            summary="", document_text="The Madras judgment.",
            extracted_char_count=2000, structured_version=None,
            decision_date=date(2023, 12, 31),
        ))
        s.add(AuthorityDocument(
            id=delhi_id, source="ecourts-hc", adapter_name="corpus-ingest",
            court_name="High Court of Delhi", forum_level="high_court",
            document_type="judgment", title="Delhi Candidate v. State",
            canonical_key=f"k-{delhi_id}",
            source_reference="DLHC000000000001_1_2023-01-01.pdf",
            summary="", document_text="The Delhi judgment.",
            extracted_char_count=2000, structured_version=None,
            decision_date=date(2023, 1, 1),
        ))
        s.commit()

    seen: list[str] = []

    def _capture(session, *, document, tier):
        seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=1, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=(2023, 2023), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
            court_names=mod._parse_court_filter("delhi"),
        )

    assert seen == [delhi_id]
    assert totals["haiku"]["candidates"] == 1
    assert totals["skipped_court"] == 1


def test_limit_applies_after_year_and_coverage_filters(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A safe proof limit must cap real candidates, not the raw DB scan.

    Regression: ``--limit 1 --year-range 2023-2023`` used to stop on a newer
    already-covered row, skip it, and process zero rows even though a matching
    2023 pending document existed later in chronological order.
    """
    _ = client
    factory = get_session_factory()
    covered_id = f"covered-{uuid.uuid4().hex[:6]}"
    pending_id = f"pending-{uuid.uuid4().hex[:6]}"
    with factory() as s:
        s.add(AuthorityDocument(
            id=covered_id, source="ecourts-hc", adapter_name="corpus-ingest",
            court_name="Delhi High Court", forum_level="high_court",
            document_type="judgment", title="Covered v. State",
            canonical_key=f"k-{covered_id}",
            source_reference="DLHC000000000000_1_2025-01-01.pdf",
            summary="", document_text="The covered judgment.",
            extracted_char_count=2000, structured_version=mod.HAIKU_VERSION,
            decision_date=date(2025, 1, 1),
        ))
        s.add(AuthorityDocument(
            id=pending_id, source="ecourts-hc", adapter_name="corpus-ingest",
            court_name="Delhi High Court", forum_level="high_court",
            document_type="judgment", title="Pending v. State",
            canonical_key=f"k-{pending_id}",
            source_reference="DLHC000000000001_1_2023-01-01.pdf",
            summary="", document_text="The pending judgment.",
            extracted_char_count=2000, structured_version=None,
            decision_date=date(2023, 1, 1),
        ))
        s.commit()

    seen: list[str] = []

    def _capture(session, *, document, tier):
        seen.append(document.id)
        return _fake_summary(session, document=document, tier=tier)

    monkeypatch.setattr(mod, "extract_and_persist_structured", _capture)
    with factory() as session:
        totals = mod._structured_pass(
            session, limit=1, dry_run=False, budget_usd=10.0,
            force_tier="haiku", year_range=(2023, 2023), concurrency=1,
            english_only=True, forums=mod._DEFAULT_FORUMS,
        )

    assert seen == [pending_id]
    assert totals["haiku"]["candidates"] == 1


def test_year_range_default_is_1990_2025_with_english_only() -> None:
    """The CLI defaults to ``year_range=(1990, 2025)`` when
    ``--english-only`` is on and no explicit range was passed.
    Pinning this so a future config change doesn't silently widen the
    sweep window past the user-stated scope."""
    assert mod._DEFAULT_EN_YEAR_RANGE == (1990, 2025)


def test_main_no_english_only_drops_default_year_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--no-english-only must not silently apply the EN year window —
    operators turning the filter off expect everything in scope."""
    captured: dict = {}

    def _spy_run(**kwargs) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "run", _spy_run)
    mod.main(["--stage", "structured", "--no-english-only"])
    assert captured["english_only"] is False
    assert captured["year_range"] is None


def test_main_english_only_default_applies_year_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _spy_run(**kwargs) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "run", _spy_run)
    mod.main(["--stage", "structured"])
    assert captured["english_only"] is True
    assert captured["year_range"] == (1990, 2025)


def test_main_parses_court_alias_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _spy_run(**kwargs) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "run", _spy_run)
    mod.main([
        "--stage", "structured",
        "--year-range", "2023-2023",
        "--courts", "delhi,madras",
    ])
    assert captured["court_names"] is not None
    assert "delhi" in captured["court_names"]
    assert "madras" in captured["court_names"]


def test_main_explicit_year_range_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _spy_run(**kwargs) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "run", _spy_run)
    mod.main(["--stage", "structured", "--year-range", "2020-2025"])
    assert captured["year_range"] == (2020, 2025)


def test_main_forums_all_disables_forum_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _spy_run(**kwargs) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "run", _spy_run)
    mod.main(["--stage", "structured", "--forums", "all"])
    assert captured["forums"] is None


def test_main_forums_default_is_sc_plus_hc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def _spy_run(**kwargs) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "run", _spy_run)
    mod.main(["--stage", "structured"])
    assert captured["forums"] == frozenset({"supreme_court", "high_court"})
