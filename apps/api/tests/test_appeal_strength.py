"""MOD-TS-001-A (Sprint P, 2026-04-25) — Appeal Strength Analyzer.

Tests:
- foreign tenant matter returns 404 (tenancy)
- no draft → "weak" overall + clear "no draft" path explanation
- per-ground citation coverage classification (supported/partial/uncited)
- weak grounds surface in weak_evidence_paths + recommended_edits
- bench history match count is set when ground text contains a
  recurring phrase
- structural no-favorability test: scan EVERY string the analyzer
  emits in suggestions / weak_evidence_paths / recommended_edits
  against the forbidden tokens (win, lose, favourable, tendency,
  probability, predict, outcome, …)
- route returns 200 with the expected shape
"""
from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    Draft,
    DraftStatus,
    DraftVersion,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.appeal_strength import (
    _FORBIDDEN_PATTERN,
    _FORBIDDEN_PHRASES,
    analyze_appeal_strength,
)
from tests.test_bench_strategy_context import (
    _ctx_for,
    _seed_authority,
    _seed_court,
    bootstrap_company,
)
from tests.test_bench_strategy_context import (
    _seed_matter as _bench_seed_matter,
)


def _seed_appeal_draft(
    session,
    *,
    matter_id: str,
    body: str,
) -> str:
    """Create an appeal_memorandum draft + a single version with the
    supplied body, mirroring how generate_draft_version persists."""
    draft_id = str(uuid4())
    session.add(
        Draft(
            id=draft_id,
            matter_id=matter_id,
            template_type="appeal_memorandum",
            draft_type="brief",
            title="Test Appeal",
            status=DraftStatus.DRAFT,
        )
    )
    session.flush()
    version_id = str(uuid4())
    session.add(
        DraftVersion(
            id=version_id,
            draft_id=draft_id,
            revision=1,
            body=body,
            citations_json=json.dumps([]),
            summary="",
        )
    )
    session.flush()
    # Wire current_version_id pointer.
    draft = session.get(Draft, draft_id)
    if draft is not None:
        draft.current_version_id = version_id
    session.commit()
    return draft_id


# ---------- tenancy ----------


def test_foreign_tenant_matter_returns_404(client: TestClient) -> None:
    boot_a = bootstrap_company(client, slug_seed="ase-a")
    boot_b = bootstrap_company(client, slug_seed="ase-b")
    Session = get_session_factory()
    with Session() as session:
        m = _bench_seed_matter(
            session, company_id=boot_a["company"]["id"], code="ASE-A-1",
        )
    with Session() as session:
        import pytest
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            analyze_appeal_strength(
                session=session,
                context=_ctx_for(boot_b),
                matter_id=m.id,
            )
        assert exc.value.status_code == 404


# ---------- no draft path ----------


def test_no_draft_yet_returns_weak_with_clear_explanation(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client, slug_seed="ase-nodraft")
    Session = get_session_factory()
    with Session() as session:
        m = _bench_seed_matter(
            session, company_id=boot["company"]["id"], code="ASE-N-1",
        )
    with Session() as session:
        rep = analyze_appeal_strength(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    assert rep.has_draft is False
    assert rep.overall_strength == "weak"
    assert rep.ground_assessments == []
    assert any("No appeal-memorandum draft" in p for p in rep.weak_evidence_paths)


# ---------- per-ground coverage ----------


def test_supported_ground_with_known_authority(
    client: TestClient,
) -> None:
    """A ground with one inline citation that resolves to a seeded
    authority must score citation_coverage='supported' AND populate
    supporting_authorities with the resolved row."""
    boot = bootstrap_company(client, slug_seed="ase-sup")
    Session = get_session_factory()
    with Session() as session:
        court = _seed_court(
            session, name="Bombay High Court", short="BHC", forum="high_court",
        )
        m = _bench_seed_matter(
            session, company_id=boot["company"]["id"],
            court=court, judge_name="Justice X",
            code="ASE-SUP-1",
        )
        # Seed an authority the ground will cite. Note: the strength
        # tag depends on the authority's forum_level; HC seed → "peer".
        _seed_authority(
            session,
            title="Test v Seed — appeal stay",
            judges_json=["X"],
            neutral_citation="2024:BHC:99",
            decision_date=date(2024, 1, 1),
        )
        body = (
            "GROUNDS OF APPEAL\n"
            "1. The lower court overlooked the controlling authority "
            "[2024:BHC:99] which holds that stay must be granted on "
            "balance of convenience.\n"
            "2. The order is contrary to record at p.47.\n"
        )
        _seed_appeal_draft(session, matter_id=m.id, body=body)

    with Session() as session:
        rep = analyze_appeal_strength(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    assert rep.has_draft is True
    assert len(rep.ground_assessments) == 2
    g1 = rep.ground_assessments[0]
    assert g1.ordinal == 1
    assert g1.citation_coverage == "supported"
    assert len(g1.supporting_authorities) == 1
    assert g1.supporting_authorities[0].citation == "2024:BHC:99"
    assert g1.supporting_authorities[0].resolved_authority_id is not None
    # HC forum → "peer" precedent strength
    assert g1.supporting_authorities[0].strength_label == "peer"


def test_uncited_ground_classified_uncited_and_in_weak_paths(
    client: TestClient,
) -> None:
    """A ground with no inline citations and no [citation needed]
    markers MUST classify as 'uncited' and appear in
    weak_evidence_paths."""
    boot = bootstrap_company(client, slug_seed="ase-unc")
    Session = get_session_factory()
    with Session() as session:
        m = _bench_seed_matter(
            session, company_id=boot["company"]["id"], code="ASE-U-1",
        )
        body = (
            "GROUNDS OF APPEAL\n"
            "1. The lower court was wrong on the merits because "
            "everyone knows that this kind of order cannot stand.\n"
        )
        _seed_appeal_draft(session, matter_id=m.id, body=body)
    with Session() as session:
        rep = analyze_appeal_strength(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    g1 = rep.ground_assessments[0]
    assert g1.citation_coverage == "uncited"
    assert any("Ground 1" in p for p in rep.weak_evidence_paths)
    # Overall must be "weak" because at least one ground is uncited.
    assert rep.overall_strength == "weak"


def test_partial_ground_with_gap_marker(client: TestClient) -> None:
    """Ground with one citation AND one [citation needed] marker
    classifies 'partial'."""
    boot = bootstrap_company(client, slug_seed="ase-par")
    Session = get_session_factory()
    with Session() as session:
        m = _bench_seed_matter(
            session, company_id=boot["company"]["id"], code="ASE-P-1",
        )
        body = (
            "GROUNDS\n"
            "1. The lower court erred [2024:BHC:99] on the law as "
            "settled in [citation needed].\n"
        )
        _seed_appeal_draft(session, matter_id=m.id, body=body)
    with Session() as session:
        rep = analyze_appeal_strength(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    g1 = rep.ground_assessments[0]
    assert g1.citation_coverage == "partial"


# ---------- structural no-favorability rule ----------


def test_no_favorability_language_anywhere_in_output(
    client: TestClient,
) -> None:
    """Hard rule: scan EVERY suggestion / weak_evidence_paths /
    recommended_edits string against the forbidden-token list. The
    structural test is the second layer of defense; the in-service
    `_check_phrase` assertion is the first.
    """
    boot = bootstrap_company(client, slug_seed="ase-nofav")
    Session = get_session_factory()
    with Session() as session:
        court = _seed_court(
            session, name="Bombay High Court", short="BHC", forum="high_court",
        )
        m = _bench_seed_matter(
            session, company_id=boot["company"]["id"],
            court=court, judge_name="Justice Y",
            code="ASE-NF-1",
        )
        body = (
            "GROUNDS OF APPEAL\n"
            "1. Some unsupported claim with no citation.\n"
            "2. Another claim with [citation needed] gap.\n"
            "3. Cited [2024:BHC:1] but unresolved.\n"
        )
        _seed_appeal_draft(session, matter_id=m.id, body=body)

    with Session() as session:
        rep = analyze_appeal_strength(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )

    pool: list[str] = []
    for g in rep.ground_assessments:
        pool.extend(g.suggestions)
        pool.append(g.summary)
    pool.extend(rep.weak_evidence_paths)
    pool.extend(rep.recommended_edits)
    # Word-boundary match — uses the same pattern the in-service
    # `_check_phrase` uses, so tests + service stay aligned. Don't
    # use plain substring matching here: "closed" would trip "lose",
    # "predicate" would trip "predict", etc. The intent is to forbid
    # the WORDS, not the byte sequences.
    for line in pool:
        m = _FORBIDDEN_PATTERN.search(line)
        assert m is None, (
            f"forbidden token {m.group(0).strip()!r} leaked into "
            f"analyzer surface: {line!r}"
        )
    # Sanity: the pattern actually triggers on every forbidden phrase
    # listed in _FORBIDDEN_PHRASES (so adding a phrase to one doesn't
    # silently miss the other). Check by feeding the phrase into the
    # pattern with surrounding word-boundaries.
    for phrase in _FORBIDDEN_PHRASES:
        probe = f"x {phrase} y"
        assert _FORBIDDEN_PATTERN.search(probe) is not None, (
            f"_FORBIDDEN_PHRASES contains {phrase!r} but the runtime "
            f"_FORBIDDEN_PATTERN does not match it"
        )


# ---------- route ----------


def test_route_returns_200_and_expected_shape(client: TestClient) -> None:
    boot = bootstrap_company(client, slug_seed="ase-route-1")
    token = str(boot["access_token"])
    Session = get_session_factory()
    with Session() as session:
        m = _bench_seed_matter(
            session, company_id=boot["company"]["id"], code="ASE-R-1",
        )
    resp = client.get(
        f"/api/matters/{m.id}/appeal-strength",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matter_id"] == m.id
    assert body["overall_strength"] in ("strong", "moderate", "weak")
    assert body["has_draft"] is False
    for key in (
        "ground_assessments",
        "weak_evidence_paths",
        "recommended_edits",
    ):
        assert isinstance(body[key], list), key


def test_route_404_on_cross_tenant(client: TestClient) -> None:
    boot_a = bootstrap_company(client, slug_seed="ase-route-a")
    boot_b = bootstrap_company(client, slug_seed="ase-route-b")
    Session = get_session_factory()
    with Session() as session:
        m = _bench_seed_matter(
            session, company_id=boot_a["company"]["id"], code="ASE-R-X",
        )
    token_b = str(boot_b["access_token"])
    resp = client.get(
        f"/api/matters/{m.id}/appeal-strength",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 404
