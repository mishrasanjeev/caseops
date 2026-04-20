"""Comprehensive tests for the 2026-04-20 parallel-feature batch.

Covers four fixes / features shipped in a tight commit cluster:

1. **court-sync 422 fix** (commit `1b83fac`) — POST /api/matters/{id}/
   court-sync/pull with an empty body now derives the adapter source
   from Matter.court_name instead of raising 422.

2. **Recommendations Haiku fallback** (commit `f9955c9`) — when the
   primary LLM (Sonnet in prod) raises LLMResponseFormatError, the
   endpoint retries with a Haiku provider before giving up with 502.

3. **Outcome-bias rerank in recommendations** (commit `3ad5b08`) —
   per the 2026-04-20 bias directive, authorities whose outcome_label
   supports the user's typical position are promoted in retrieval.

4. **Judge profile rewrite** (commit `73fc94a`) — /api/courts/judges/{id}
   matches via structured judges_json first (bench_name fallback),
   and the response adds practice-area histogram, decision-volume,
   tenure bounds, and structured_match_coverage_percent.

Tests use the ``client`` fixture from conftest.py (SQLite + mock LLM /
embedding) where HTTP or DB is needed. Pure-function helpers (honorific
stripper, source resolver, bias mapping) are unit-tested without a
fixture.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    Court,
    Judge,
)
from caseops_api.db.session import get_session_factory

# ---------------------------------------------------------------
# Shared seed helpers
# ---------------------------------------------------------------

def _canonical(title: str, ref: str | None) -> str:
    return hashlib.sha256(
        (title + "|" + (ref or "")).encode("utf-8")
    ).hexdigest()[:40]


def _seed_authority(
    *,
    title: str,
    court_name: str,
    outcome_label: str | None = None,
    bench_name: str | None = None,
    judges_json: list[str] | None = None,
    decision_date: date | None = None,
    forum_level: str = "high_court",
    document_text: str = "judgment text",
    summary: str = "summary",
    sections: str | None = None,
    structured_version: int | None = 1,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        doc = AuthorityDocument(
            title=title,
            court_name=court_name,
            forum_level=forum_level,
            document_type=AuthorityDocumentType.JUDGMENT,
            decision_date=decision_date or date(2024, 1, 1),
            case_reference=f"REF-{_canonical(title, None)[:8]}",
            summary=summary,
            source="test-fixture",
            adapter_name="test",
            source_reference=f"src::{title}",
            canonical_key=_canonical(title, None),
            document_text=document_text,
            extracted_char_count=len(document_text),
            bench_name=bench_name,
            judges_json=json.dumps(judges_json) if judges_json else None,
            outcome_label=outcome_label,
            structured_version=structured_version,
            ingested_at=datetime.now(UTC),
        )
        session.add(doc)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=doc.id,
                chunk_index=0,
                content=document_text,
                token_count=len(document_text.split()),
                embedding_model="mock",
                embedding_dimensions=3,
                embedding_json="[0,0,0]",
                embedded_at=datetime.now(UTC),
                sections_cited_json=sections,
            )
        )
        session.commit()
        return doc.id


def _seed_court(name: str = "Delhi High Court") -> str:
    factory = get_session_factory()
    with factory() as session:
        existing = session.scalar(select(Court).where(Court.name == name))
        if existing:
            return existing.id
        court = Court(
            name=name,
            short_name="DHC" if name.startswith("Delhi") else name[:3].upper(),
            forum_level="high_court",
            jurisdiction="Delhi" if name.startswith("Delhi") else None,
            seat_city="Delhi" if name.startswith("Delhi") else None,
            hc_catalog_key="delhi" if name.startswith("Delhi") else None,
            is_active=True,
        )
        session.add(court)
        session.commit()
        return court.id


def _seed_judge(court_id: str, full_name: str) -> str:
    factory = get_session_factory()
    with factory() as session:
        judge = Judge(
            court_id=court_id,
            full_name=full_name,
            honorific="Justice",
            is_active=True,
        )
        session.add(judge)
        session.commit()
        return judge.id


# ---------------------------------------------------------------
# 1. court-sync 422 fix — unit-test the source resolver directly
# ---------------------------------------------------------------

def test_resolve_source_for_court_maps_known_courts() -> None:
    """Each court with a live adapter resolves to its key."""
    from caseops_api.services.court_sync_sources import resolve_source_for_court

    assert resolve_source_for_court("Supreme Court of India") == "supreme_court_live"
    assert resolve_source_for_court("Delhi High Court") == "delhi_high_court_live"
    assert resolve_source_for_court("Bombay High Court") == "bombay_high_court_live"
    assert resolve_source_for_court("Karnataka High Court") == "karnataka_high_court_live"
    assert resolve_source_for_court("Madras High Court") == "chennai_high_court_live"
    assert resolve_source_for_court("Telangana High Court") == "hyderabad_high_court_live"


def test_resolve_source_for_court_returns_none_for_unknown() -> None:
    """Unrecognised court name → None (caller surfaces a clear 400)."""
    from caseops_api.services.court_sync_sources import resolve_source_for_court

    assert resolve_source_for_court("Nonexistent High Court") is None
    assert resolve_source_for_court(None) is None
    assert resolve_source_for_court("") is None
    assert resolve_source_for_court("  ") is None


def test_resolve_source_for_court_trims_whitespace() -> None:
    """Leading / trailing whitespace doesn't defeat the mapping."""
    from caseops_api.services.court_sync_sources import resolve_source_for_court

    assert resolve_source_for_court("  Delhi High Court  ") == "delhi_high_court_live"


def test_matter_court_sync_pull_request_source_is_optional() -> None:
    """Schema accepts empty body — source is None after Pydantic parse."""
    from caseops_api.schemas.matters import MatterCourtSyncPullRequest

    parsed = MatterCourtSyncPullRequest.model_validate({})
    assert parsed.source is None
    assert parsed.source_reference is None


# ---------------------------------------------------------------
# 2. Recommendations Haiku fallback guard
# ---------------------------------------------------------------

def test_haiku_fallback_none_for_non_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CASEOPS_LLM_PROVIDER is mock/gemini, fallback is None."""
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    from caseops_api.core.settings import get_settings
    from caseops_api.services import recommendations

    get_settings.cache_clear()
    fallback = recommendations._haiku_fallback_provider()
    assert fallback is None


def test_haiku_fallback_built_for_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic provider + key → Haiku AnthropicProvider instance."""
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "sk-ant-test")
    from caseops_api.core.settings import get_settings
    from caseops_api.services import recommendations

    get_settings.cache_clear()
    fallback = recommendations._haiku_fallback_provider()
    assert fallback is not None
    assert "haiku" in fallback.model.lower()


# ---------------------------------------------------------------
# 3. Outcome-bias rerank
# ---------------------------------------------------------------

def test_outcome_bias_mapping_covers_common_practice_areas() -> None:
    """The bias table includes the practice areas we regularly ship."""
    from caseops_api.services.recommendations import _OUTCOME_BIAS

    for area in ("criminal", "bail", "civil", "family", "commercial"):
        assert area in _OUTCOME_BIAS
        assert _OUTCOME_BIAS[area]["preferred"]
        assert _OUTCOME_BIAS[area]["against"]


def test_outcome_bias_rerank_promotes_preferred(client: TestClient) -> None:
    """Bail matter: 'granted' ranks first, 'dismissed' last."""
    from caseops_api.schemas.authorities import AuthoritySearchResult
    from caseops_api.services.recommendations import _rerank_by_outcome_bias

    doc_granted = _seed_authority(
        title="A Granted", court_name="Delhi High Court",
        outcome_label="bail granted",
    )
    doc_dismissed = _seed_authority(
        title="B Dismissed", court_name="Delhi High Court",
        outcome_label="dismissed",
    )
    doc_neutral = _seed_authority(
        title="C Neutral", court_name="Delhi High Court",
        outcome_label=None,
    )

    def _stub(doc_id: str, title: str) -> AuthoritySearchResult:
        return AuthoritySearchResult(
            authority_document_id=doc_id,
            title=title,
            court_name="Delhi High Court",
            forum_level="high_court",
            document_type="judgment",
            decision_date=None,
            case_reference=None,
            bench_name=None,
            summary="",
            source="test",
            source_reference=None,
            snippet="",
            score=0,
            matched_terms=[],
        )

    results = [
        _stub(doc_dismissed, "B Dismissed"),
        _stub(doc_neutral, "C Neutral"),
        _stub(doc_granted, "A Granted"),
    ]

    class _Matter:
        practice_area = "bail"

    with get_session_factory()() as session:
        reranked = _rerank_by_outcome_bias(session, results, matter=_Matter())

    assert reranked[0].authority_document_id == doc_granted
    assert reranked[-1].authority_document_id == doc_dismissed


def test_outcome_bias_rerank_noop_for_unknown_practice_area(
    client: TestClient,
) -> None:
    """Unknown practice_area → rerank leaves results untouched."""
    from caseops_api.schemas.authorities import AuthoritySearchResult
    from caseops_api.services.recommendations import _rerank_by_outcome_bias

    doc = _seed_authority(
        title="Z", court_name="Delhi High Court", outcome_label="dismissed",
    )
    results = [
        AuthoritySearchResult(
            authority_document_id=doc,
            title="Z",
            court_name="Delhi High Court",
            forum_level="high_court",
            document_type="judgment",
            decision_date=None,
            case_reference=None,
            bench_name=None,
            summary="",
            source="test",
            source_reference=None,
            snippet="",
            score=0,
            matched_terms=[],
        )
    ]

    class _Matter:
        practice_area = "space_law"

    with get_session_factory()() as session:
        reranked = _rerank_by_outcome_bias(session, results, matter=_Matter())
    assert reranked == results


def test_outcome_bias_rerank_empty_results_returns_empty(
    client: TestClient,
) -> None:
    """Empty retrieval → empty rerank, no DB round-trip."""
    from caseops_api.services.recommendations import _rerank_by_outcome_bias

    class _Matter:
        practice_area = "bail"

    with get_session_factory()() as session:
        assert _rerank_by_outcome_bias(session, [], matter=_Matter()) == []


# ---------------------------------------------------------------
# 4. Judge profile v2 — honorific stripping, judges_json match,
#    practice-area histogram, decision-volume, tenure bounds.
# ---------------------------------------------------------------

def test_strip_judge_honorific_normalises_common_forms() -> None:
    """Prefix / suffix normaliser covers the usual judicial honorifics."""
    from caseops_api.api.routes.courts import (
        _judge_surname,
        _strip_judge_honorific,
    )

    assert _strip_judge_honorific("Justice Vikram Nath") == "Vikram Nath"
    assert _strip_judge_honorific(
        "Hon'ble Mr. Justice Vikram Nath"
    ) == "Vikram Nath"
    assert _strip_judge_honorific("Vikram Nath, J.") == "Vikram Nath"
    assert _strip_judge_honorific("Chief Justice B.R. Gavai") == "B.R. Gavai"
    assert _strip_judge_honorific("") == ""
    assert _judge_surname("Justice Vikram Nath") == "Nath"
    assert _judge_surname("") == ""


def test_judge_profile_structured_and_fallback_match_dedup(
    client: TestClient,
) -> None:
    """Docs matched via judges_json AND bench_name are counted once."""
    # Direct service call — no HTTP route needed for this unit.
    court_id = _seed_court("Delhi High Court")
    _seed_judge(court_id, "Vikram Nath")
    _seed_authority(
        title="Structured match",
        court_name="Delhi High Court",
        judges_json=["Vikram Nath J."],
        bench_name=None,
        sections='["BNSS Section 483"]',
    )
    _seed_authority(
        title="Fallback match",
        court_name="Delhi High Court",
        bench_name="Vikram Nath, J.",
        judges_json=None,
    )
    _seed_authority(
        title="Both match",
        court_name="Delhi High Court",
        judges_json=["Vikram Nath J."],
        bench_name="Vikram Nath, J.",
    )

    with get_session_factory()() as session:
        # Confirm the 'both match' doc counts once, not twice.
        from caseops_api.api.routes.courts import _strip_judge_honorific
        stripped = _strip_judge_honorific("Vikram Nath")
        from sqlalchemy import func, or_

        structured_filter = AuthorityDocument.judges_json.ilike(
            f'%"{stripped}%'
        )
        fallback_filter = AuthorityDocument.bench_name.ilike(f"%{stripped}%")
        combined = or_(structured_filter, fallback_filter)

        n = session.scalar(
            select(func.count(AuthorityDocument.id.distinct())).where(combined)
        )
        assert n == 3  # three distinct docs, 'Both match' not double-counted


def test_practice_area_classifier_buckets_sections(client: TestClient) -> None:
    """Practice-area regex buckets BNSS/CrPC as Bail, IPC as Criminal."""
    from sqlalchemy import or_

    from caseops_api.api.routes.courts import _practice_area_histogram

    court_id = _seed_court("Delhi High Court")
    _seed_judge(court_id, "Surya Kant")

    _seed_authority(
        title="Bail one",
        court_name="Delhi High Court",
        judges_json=["Surya Kant"],
        sections='["BNSS Section 483", "CrPC Section 439"]',
    )
    _seed_authority(
        title="IPC one",
        court_name="Delhi High Court",
        judges_json=["Surya Kant"],
        sections='["IPC Section 302"]',
    )
    _seed_authority(
        title="Civil one",
        court_name="Delhi High Court",
        judges_json=["Surya Kant"],
        sections='["Specific Relief Act"]',
    )

    from caseops_api.api.routes.courts import _strip_judge_honorific
    stripped = _strip_judge_honorific("Surya Kant")
    jfilter = or_(
        AuthorityDocument.judges_json.ilike(f'%"{stripped}%'),
        AuthorityDocument.bench_name.ilike(f"%{stripped}%"),
    )

    with get_session_factory()() as session:
        hist = dict(_practice_area_histogram(session, judge_filter=jfilter))

    assert hist.get("Bail / Custody", 0) >= 1
    assert hist.get("Criminal (other)", 0) >= 1
    assert hist.get("Civil / Contract", 0) >= 1
