"""Slice D (MOD-TS-001-E) — tolerant judge name matcher tests.

Maps to FT-024F-1 .. FT-024F-4 in
``docs/PRD_BENCH_MAPPING_2026-04-25.md`` §3 Slice D.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import Judge, JudgeAlias
from caseops_api.services.judge_aliases import (
    backfill_canonical_aliases,
    canonical_aliases_for,
    match_candidates,
    normalise,
)
from tests.test_auth_company import bootstrap_company


def _seed_judge(s, *, court_id, name, honorific="Justice"):
    j = Judge(
        court_id=court_id, full_name=name, honorific=honorific,
        current_position=f"Judge of {court_id}", is_active=True,
    )
    s.add(j)
    s.flush()
    return j


def test_normalise_is_idempotent_and_strips_punctuation() -> None:
    assert normalise("Justice A.K. Sikri") == "justice a k sikri"
    # Idempotent.
    assert normalise(normalise("Justice A.K. Sikri")) == "justice a k sikri"
    # Whitespace collapse.
    assert normalise("  Justice    Sikri  ") == "justice sikri"


def test_canonical_aliases_for_includes_initial_form(client: TestClient) -> None:
    """Slice D backfill must produce both full and initial+surname
    aliases — that's how 'Justice A.K. Sikri' will resolve later."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        judge = _seed_judge(
            s, court_id="supreme-court-india",
            name="Adarsh Kumar Sikri",
        )
        s.commit()
        aliases = canonical_aliases_for(judge)
    norms = {normalise(a) for a in aliases}
    assert "adarsh kumar sikri" in norms
    assert "justice adarsh kumar sikri" in norms
    assert "a k sikri" in norms
    assert "justice a k sikri" in norms


def test_ft_024f_1_initial_and_full_resolve_to_same_judge(
    client: TestClient,
) -> None:
    """'Justice A.K. Sikri' AND 'Justice Adarsh Kumar Sikri' must
    both resolve to the same Judge.id."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        judge = _seed_judge(
            s, court_id="supreme-court-india",
            name="Adarsh Kumar Sikri",
        )
        s.commit()
        backfill_canonical_aliases(s, source="auto_extract")

        m1 = match_candidates(
            s, raw_text="Justice A.K. Sikri",
            court_id="supreme-court-india",
        )
        m2 = match_candidates(
            s, raw_text="Justice Adarsh Kumar Sikri",
            court_id="supreme-court-india",
        )
    ids1 = {m.judge_id for m in m1}
    ids2 = {m.judge_id for m in m2}
    assert ids1 == ids2
    assert judge.id in ids1


def test_ft_024f_2_single_common_surname_does_not_match(
    client: TestClient,
) -> None:
    """High-quality confidence floor: 'Justice Singh' alone is too
    ambiguous when multiple judges share that surname. Match must
    require initial+surname OR full name. Otherwise return empty."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        # Two SC judges named '... Singh'.
        _seed_judge(s, court_id="supreme-court-india", name="Manjit Singh")
        _seed_judge(s, court_id="supreme-court-india", name="Aftab Singh")
        s.commit()
        backfill_canonical_aliases(s)

        # 'Singh' alone — no initial, no full first name.
        matches = match_candidates(
            s, raw_text="Justice Singh",
            court_id="supreme-court-india",
        )
    assert matches == [], (
        "single-surname-only resolver MUST be empty per the high-"
        "quality confidence floor; it leaked: "
        + repr([(m.judge_full_name, m.confidence) for m in matches])
    )


def test_ft_024f_3_backfill_produces_4plus_aliases_per_judge(
    client: TestClient,
) -> None:
    """Backfill produces ≥ 4 aliases for a multi-token name (full,
    Justice+full, initial+surname, Justice+initial+surname)."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        judge = _seed_judge(
            s, court_id="supreme-court-india",
            name="Devendra Kumar Upadhyaya",
        )
        s.commit()
        ins, _skip = backfill_canonical_aliases(s)
        assert ins >= 4
        rows = list(
            s.scalars(
                select(JudgeAlias).where(JudgeAlias.judge_id == judge.id)
            ).all()
        )
        assert len(rows) >= 4


def test_ft_024f_4_backfill_is_idempotent(client: TestClient) -> None:
    """Re-running the backfill against the same DB inserts 0 and
    skips all existing rows."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        _seed_judge(
            s, court_id="supreme-court-india",
            name="Idempotent Test Judge",
        )
        s.commit()
        ins1, _ = backfill_canonical_aliases(s)
        assert ins1 > 0
        ins2, skipped2 = backfill_canonical_aliases(s)
        assert ins2 == 0
        assert skipped2 == ins1


def test_court_scope_blocks_cross_court_match(client: TestClient) -> None:
    """Resolver is court-scoped — a Bombay HC bench string must not
    resolve to an SC judge with the same name."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        _seed_judge(
            s, court_id="supreme-court-india", name="Common Name",
        )
        _seed_judge(
            s, court_id="bombay-hc", name="Common Name",
        )
        s.commit()
        backfill_canonical_aliases(s)

        sc_matches = match_candidates(
            s, raw_text="Common Name", court_id="supreme-court-india",
        )
        bom_matches = match_candidates(
            s, raw_text="Common Name", court_id="bombay-hc",
        )
    sc_ids = {m.judge_id for m in sc_matches}
    bom_ids = {m.judge_id for m in bom_matches}
    assert len(sc_matches) == 1
    assert len(bom_matches) == 1
    assert sc_ids.isdisjoint(bom_ids)
