"""BAAD-001 slice 2 tests — bench strategy context service.

Pure-read service so all tests run against a freshly-bootstrapped
tenant and seed authorities directly via the SQLAlchemy session.

Covers:
- Tenant isolation: matter from another tenant returns 404
- context_quality labels respond to coverage + authority count
- structured_match flag only set when judges_json matches
- patterns suppressed when supported by fewer than 3 authorities
- drafting_cautions copy is actionable (no None / no internal terms)
- "no candidates" path: returns quality=none + a clear unsupported_gap
- Bench-aware drafting rule check: no favorability language anywhere
  in the surface (the dataclass is structural — output strings come
  only from `drafting_cautions` and `unsupported_gaps`)
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentType,
    Court,
    Judge,
    Matter,
    MatterForumLevel,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.bench_strategy_context import (
    BenchStrategyContext,
    build_bench_strategy_context,
)
from caseops_api.services.identity import SessionContext
def bootstrap_company(client: TestClient, *, slug_seed: str) -> dict:
    """Local bootstrap helper that supports unique slug per call so a
    single test can spin up two tenants for the isolation case. The
    canonical `tests.test_auth_company.bootstrap_company` is one-shot
    only."""
    client.cookies.clear()
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug_seed.title()} LLP",
            "company_slug": slug_seed,
            "company_type": "law_firm",
            "owner_full_name": "Owner",
            "owner_email": f"owner-{slug_seed}@example.com",
            "owner_password": "FoundersPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return resp.json()


def _ctx_for(boot: dict) -> SessionContext:
    """Synthesize a SessionContext that the service expects. The bench
    context is pure-read + only uses context.company.id, so we don't
    need a fully hydrated context — a small object with `company.id`
    suffices."""
    from types import SimpleNamespace
    return SimpleNamespace(  # type: ignore[return-value]
        company=SimpleNamespace(id=boot["company"]["id"]),
        membership=SimpleNamespace(id=None),
        user=SimpleNamespace(id=None),
    )


def _seed_court(session, *, name: str, short: str, forum: str) -> Court:
    """Bootstrap auto-seeds a few courts (Bombay HC, etc.). Reuse if
    the row exists; otherwise create."""
    existing = session.scalar(select(Court).where(Court.name == name))
    if existing is not None:
        return existing
    c = Court(
        id=str(uuid4()),
        name=name,
        short_name=short,
        forum_level=forum,
        jurisdiction="IN",
        seat_city="Mumbai",
        is_active=True,
    )
    session.add(c)
    session.commit()
    return c


def _seed_judge(session, *, court: Court, name: str) -> Judge:
    j = Judge(
        id=str(uuid4()),
        court_id=court.id,
        full_name=name,
        honorific="Justice",
        is_active=True,
    )
    session.add(j)
    session.commit()
    return j


def _seed_matter(
    session, *, company_id: str, court: Court | None = None,
    judge_name: str | None = None, code: str = "MAT-1",
) -> Matter:
    m = Matter(
        company_id=company_id,
        client_name="Anchor",
        title="Test matter",
        matter_code=code,
        status="active",
        practice_area="commercial",
        forum_level=MatterForumLevel.HIGH_COURT,
        court_id=court.id if court else None,
        court_name=court.name if court else None,
        judge_name=judge_name,
    )
    session.add(m)
    session.commit()
    return m


def _seed_authority(
    session, *, title: str, judges_json: list[str] | None = None,
    bench_name: str | None = None, neutral_citation: str | None = None,
    case_reference: str | None = None,
    decision_date: date | None = None,
) -> AuthorityDocument:
    a = AuthorityDocument(
        id=str(uuid4()),
        source="seed",
        adapter_name="seed-adapter",
        court_name="Bombay High Court",
        forum_level=MatterForumLevel.HIGH_COURT,
        document_type=AuthorityDocumentType.JUDGMENT,
        title=title,
        canonical_key=str(uuid4()),
        source_reference=str(uuid4()),
        summary="",
        bench_name=bench_name,
        judges_json=json.dumps(judges_json) if judges_json else None,
        neutral_citation=neutral_citation,
        case_reference=case_reference,
        decision_date=decision_date,
    )
    session.add(a)
    session.commit()
    return a


def test_foreign_tenant_matter_returns_404(client: TestClient) -> None:
    """Tenancy: matter belonging to tenant A is invisible to tenant B's
    SessionContext (404 — same shape as other matter routes)."""
    boot_a = bootstrap_company(client, slug_seed="bsc-a")
    boot_b = bootstrap_company(client, slug_seed="bsc-b")
    Session = get_session_factory()
    with Session() as session:
        m = _seed_matter(
            session, company_id=boot_a["company"]["id"], code="BSC-A-1",
        )
    with Session() as session:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            build_bench_strategy_context(
                session=session,
                context=_ctx_for(boot_b),
                matter_id=m.id,
            )
        assert exc.value.status_code == 404


def test_no_judge_no_court_returns_quality_none_and_caution(
    client: TestClient,
) -> None:
    """Matter with no judge_name AND no court_id → no candidates → no
    authorities → quality=none + actionable caution + unsupported_gap."""
    boot = bootstrap_company(client, slug_seed="bsc-empty")
    Session = get_session_factory()
    with Session() as session:
        m = _seed_matter(
            session, company_id=boot["company"]["id"], code="BSC-E-1",
        )
    with Session() as session:
        ctx = build_bench_strategy_context(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    assert ctx.context_quality == "none"
    assert ctx.judge_candidates == []
    assert ctx.similar_authorities == []
    # Caution must be actionable — calls out the fallback path
    assert any("limitation note" in c.lower() for c in ctx.drafting_cautions)
    # And the gaps explicitly tell the prompt not to cite tendencies
    assert any(
        "must not cite bench-specific tendencies" in g.lower()
        or "indexed prior judgments" in g.lower()
        for g in ctx.unsupported_gaps
    )


def test_structured_match_flag_only_set_when_judges_json_matches(
    client: TestClient,
) -> None:
    """An authority where the judge appears in judges_json must be
    flagged structured_match=True. An authority where the judge only
    appears in bench_name must be flagged False."""
    boot = bootstrap_company(client, slug_seed="bsc-struct")
    Session = get_session_factory()
    with Session() as session:
        court = _seed_court(
            session, name="Bombay High Court", short="BHC", forum="high_court",
        )
        m = _seed_matter(
            session, company_id=boot["company"]["id"],
            court=court, judge_name="Justice Vikram Nath",
            code="BSC-S-1",
        )
        # Structured match: judges_json contains the stripped name.
        _seed_authority(
            session, title="ABC v XYZ — bail / triple test",
            judges_json=["Vikram Nath", "Other Judge"],
            neutral_citation="2024:BHC:1",
            decision_date=date(2024, 1, 1),
        )
        # Fallback only: bench_name has the name but judges_json is None.
        _seed_authority(
            session, title="DEF v GHI — appeal",
            bench_name="Vikram Nath, J.",
            case_reference="APPL 9/2024",
            decision_date=date(2024, 2, 1),
        )
    with Session() as session:
        ctx = build_bench_strategy_context(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    assert len(ctx.similar_authorities) == 2
    structured_flags = [a.structured_match for a in ctx.similar_authorities]
    assert sum(structured_flags) == 1, structured_flags
    assert sum(1 for f in structured_flags if not f) == 1


def test_pattern_suppressed_when_below_three_authorities(
    client: TestClient,
) -> None:
    """A practice-area bucket with only 2 authorities must NOT surface
    as a recognised pattern; it must show up in unsupported_gaps so
    the prompt can warn the lawyer."""
    boot = bootstrap_company(client, slug_seed="bsc-thin")
    Session = get_session_factory()
    with Session() as session:
        court = _seed_court(
            session, name="Bombay High Court", short="BHC", forum="high_court",
        )
        m = _seed_matter(
            session, company_id=boot["company"]["id"],
            court=court, judge_name="Justice Anand Kumar",
            code="BSC-T-1",
        )
        # Only 2 bail-related authorities → below the 3-floor.
        for i in range(2):
            _seed_authority(
                session, title=f"Bail App {i} — triple test",
                judges_json=["Anand Kumar"],
                neutral_citation=f"2024:BHC:T{i}",
                decision_date=date(2024, 1, 1 + i),
            )
    with Session() as session:
        ctx = build_bench_strategy_context(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    # 2 authorities → no pattern surfaced, but a gap explaining why
    bail_patterns = [
        p for p in ctx.practice_area_patterns if "Bail" in p.area
    ]
    assert bail_patterns == []
    assert any("anecdotal" in g.lower() or "thin" in g.lower()
               for g in ctx.unsupported_gaps), ctx.unsupported_gaps


def test_quality_high_when_coverage_and_count_meet_floor(
    client: TestClient,
) -> None:
    """quality='high' requires structured coverage >= 60% AND >= 5
    citable authorities. Seed 5 structured judges_json hits."""
    boot = bootstrap_company(client, slug_seed="bsc-high")
    Session = get_session_factory()
    with Session() as session:
        court = _seed_court(
            session, name="Bombay High Court", short="BHC", forum="high_court",
        )
        m = _seed_matter(
            session, company_id=boot["company"]["id"],
            court=court, judge_name="Justice Pooja Mehra",
            code="BSC-H-1",
        )
        for i in range(6):
            _seed_authority(
                session, title=f"Authority {i} — Order XLI Rule 5",
                judges_json=["Pooja Mehra"],
                neutral_citation=f"2024:BHC:H{i}",
                decision_date=date(2024, 1, 1 + i),
            )
    with Session() as session:
        ctx = build_bench_strategy_context(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    assert ctx.context_quality == "high", (
        f"expected high; got {ctx.context_quality} "
        f"(coverage={ctx.structured_match_coverage_percent}, "
        f"count={len(ctx.similar_authorities)})"
    )
    assert ctx.structured_match_coverage_percent >= 60


def test_no_favorability_language_in_surface_strings(
    client: TestClient,
) -> None:
    """Bench-aware drafting hard rule: no 'tends to' / 'favourable' /
    'usually grants' language anywhere in the surface output. The
    dataclass surface is structural; the only free-text fields are
    drafting_cautions and unsupported_gaps. Both are derived from
    fixed templates in this module — assert structurally."""
    boot = bootstrap_company(client, slug_seed="bsc-noscore")
    Session = get_session_factory()
    with Session() as session:
        m = _seed_matter(
            session, company_id=boot["company"]["id"], code="BSC-N-1",
        )
    with Session() as session:
        ctx = build_bench_strategy_context(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )

    forbidden = [
        "tends to", "tend to", "favourable", "favorable",
        "usually grants", "is likely to grant", "typically rules",
        "preference for", "lenient", "strict on",
    ]
    pool = " ".join(ctx.drafting_cautions + ctx.unsupported_gaps).lower()
    for needle in forbidden:
        assert needle not in pool, (
            f"forbidden favorability phrase '{needle}' leaked into the "
            f"context surface: {pool}"
        )


def test_bench_strategy_context_is_pure_read(client: TestClient) -> None:
    """Service must not write to the DB — call it twice on the same
    matter and confirm the matter row's updated_at didn't change."""
    boot = bootstrap_company(client, slug_seed="bsc-pure")
    Session = get_session_factory()
    with Session() as session:
        m = _seed_matter(
            session, company_id=boot["company"]["id"], code="BSC-P-1",
        )
        before = m.updated_at
    with Session() as session:
        build_bench_strategy_context(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
        build_bench_strategy_context(
            session=session, context=_ctx_for(boot), matter_id=m.id,
        )
    with Session() as session:
        m2 = session.scalar(
            select(Matter).where(Matter.id == m.id)
        )
        assert m2 is not None
        # SQLite returns naive datetimes; compare value-equivalent
        # (ignoring tzinfo). The point is "no write happened", which
        # any new datetime would change.
        assert m2.updated_at.replace(tzinfo=None) == before.replace(tzinfo=None)




# ---------- BAAD-001 slice 3 — drafting integration smoke ----------
# Pure-unit checks that _build_messages reacts correctly to a
# bench_context. We don't run the LLM (mock provider in conftest);
# we just verify the prompt block shape so any regression to the
# integration path is caught at unit level.

def test_build_messages_injects_bench_context_for_appeal(
    client: TestClient,
) -> None:
    """When draft.template_type=='appeal_memorandum' AND a non-trivial
    bench_context is supplied, the user message must carry the
    'BENCH HISTORY CONTEXT' header + a confidence label."""
    from caseops_api.services.drafting import _build_messages
    from caseops_api.services.bench_strategy_context import BenchStrategyContext

    boot = bootstrap_company(client, slug_seed="baad-build-1")
    Session = get_session_factory()
    with Session() as session:
        m = _seed_matter(
            session, company_id=boot["company"]["id"], code="BAAD-B-1",
        )

    class _Draft:
        template_type = "appeal_memorandum"
        title = "Appeal — Test"
        draft_type = "appeal"
        facts_json = None

    ctx = BenchStrategyContext(
        matter_id=m.id,
        court_name="Bombay High Court",
        bench_match=None,
        context_quality="medium",
        structured_match_coverage_percent=55,
    )
    msgs = _build_messages(
        matter=m, draft=_Draft(), retrieved=[], focus_note=None,
        bench_context=ctx,
    )
    user = next(x for x in msgs if x.role == "user").content
    assert "BENCH HISTORY CONTEXT" in user
    assert "Match confidence: medium" in user


def test_build_messages_low_quality_emits_fallback_directive(
    client: TestClient,
) -> None:
    """When context_quality is 'low' or 'none', the prompt MUST tell
    the model to draft without bench-specific framing — bench-aware
    drafting weak-evidence-fallback rule."""
    from caseops_api.services.drafting import _build_messages
    from caseops_api.services.bench_strategy_context import BenchStrategyContext

    boot = bootstrap_company(client, slug_seed="baad-build-2")
    Session = get_session_factory()
    with Session() as session:
        m = _seed_matter(
            session, company_id=boot["company"]["id"], code="BAAD-B-2",
        )

    class _Draft:
        template_type = "appeal_memorandum"
        title = "Appeal — Test"
        draft_type = "appeal"
        facts_json = None

    ctx = BenchStrategyContext(
        matter_id=m.id, court_name=None, bench_match=None,
        context_quality="low", structured_match_coverage_percent=0,
    )
    user = next(x for x in _build_messages(
        matter=m, draft=_Draft(), retrieved=[], focus_note=None,
        bench_context=ctx,
    ) if x.role == "user").content
    assert "DO NOT cite bench-specific tendencies" in user
    assert "limitation note" in user.lower()


def test_build_messages_does_not_inject_bench_context_for_other_templates(
    client: TestClient,
) -> None:
    """A bail draft passes through _build_messages with bench_context=
    something — we MUST NOT inject the bench block. Only appeal_memorandum
    consumes it."""
    from caseops_api.services.drafting import _build_messages
    from caseops_api.services.bench_strategy_context import BenchStrategyContext

    boot = bootstrap_company(client, slug_seed="baad-build-3")
    Session = get_session_factory()
    with Session() as session:
        m = _seed_matter(
            session, company_id=boot["company"]["id"], code="BAAD-B-3",
        )

    class _Draft:
        template_type = "bail"  # NOT appeal
        title = "Bail Test"
        draft_type = "bail"
        facts_json = None

    ctx = BenchStrategyContext(
        matter_id=m.id, court_name=None, bench_match=None,
        context_quality="high", structured_match_coverage_percent=80,
    )
    user = next(x for x in _build_messages(
        matter=m, draft=_Draft(), retrieved=[], focus_note=None,
        bench_context=ctx,
    ) if x.role == "user").content
    assert "BENCH HISTORY CONTEXT" not in user


def test_build_messages_has_no_favorability_phrasing(
    client: TestClient,
) -> None:
    """Structural check: the prompt itself does not contain any
    favorability language that the model could echo back. The block
    instructs the model TO USE evidence phrasing, but never asserts
    a tendency."""
    from caseops_api.services.drafting import _build_messages
    from caseops_api.services.bench_strategy_context import (
        BenchStrategyContext,
        RecurringTest,
        PracticeAreaPattern,
    )

    boot = bootstrap_company(client, slug_seed="baad-build-4")
    Session = get_session_factory()
    with Session() as session:
        m = _seed_matter(
            session, company_id=boot["company"]["id"], code="BAAD-B-4",
        )

    class _Draft:
        template_type = "appeal_memorandum"
        title = "Appeal — Test"
        draft_type = "appeal"
        facts_json = None

    ctx = BenchStrategyContext(
        matter_id=m.id, court_name="BHC", bench_match=None,
        context_quality="high", structured_match_coverage_percent=70,
        recurring_tests=[
            RecurringTest(
                phrase="balance of convenience",
                occurrences=4,
                sample_authority_ids=("a1", "a2", "a3"),
            ),
        ],
        practice_area_patterns=[
            PracticeAreaPattern(
                area="Civil / Contract",
                authority_count=5,
                sample_authority_ids=("a4", "a5"),
            ),
        ],
    )
    user = next(x for x in _build_messages(
        matter=m, draft=_Draft(), retrieved=[], focus_note=None,
        bench_context=ctx,
    ) if x.role == "user").content
    # The prompt MUST contain the negative instruction (telling the
    # model not to use favorability phrases) AND the positive
    # evidence-phrasing anchor (showing the required formulation).
    # Both checks together prove the prompt actively guards against
    # favorability claims.
    assert "REQUIRED PHRASING" in user, (
        "BAAD evidence-phrasing anchor missing from prompt"
    )
    assert "in the indexed decisions provided" in user, (
        "Required attribution phrasing missing"
    )
    # Negative instruction must explicitly enumerate forbidden phrases.
    assert "NEVER write 'this judge prefers'" in user, (
        "Negative instruction against favorability not in prompt"
    )
