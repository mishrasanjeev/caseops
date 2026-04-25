"""Slice C (MOD-TS-001-D) — bench-specific BAAD context tests.

Maps to FT-024E-1 .. FT-024E-6 in
``docs/PRD_BENCH_MAPPING_2026-04-25.md`` §3 Slice C.

Bench-aware drafting hard rules + advocate-bias rules (§2.1) are
both verified here:
- bench_specific_authorities are selected to support the matter's
  practice area when possible (advocate-bias)
- no favorability copy leaks into any field of the response
  (structural test sweep)
"""
from __future__ import annotations

import json
import re
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuthorityDocument,
    Court,
    Judge,
    Matter,
    MatterCauseListEntry,
)
from caseops_api.services.bench_resolver import resolve_listing_bench
from caseops_api.services.bench_strategy_context import (
    build_bench_strategy_context,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.judge_aliases import backfill_canonical_aliases
from tests.test_auth_company import bootstrap_company

# Reuse the same forbidden-token regex pattern from MOD-TS-001-A.
_FORBIDDEN = re.compile(
    r"(?:^|\W)(?:" + "|".join(
        re.escape(p) for p in [
            "win", "lose", "loss", "winnable", "winnability",
            "favourable", "favorable", "favour", "favor",
            "tendency", "tends to", "usually grants", "usually rules",
            "probability", "chance of success", "likely to succeed",
            "predict", "prediction", "outcome",
        ]
    ) + r")(?=$|\W)",
    re.IGNORECASE,
)


def _make_session_context(membership):
    return SessionContext(
        membership=membership,
        company=membership.company,
        user=membership.user,
    )


def _seed_judges_with_aliases(s, court_id, names):
    out = []
    for n in names:
        j = Judge(
            court_id=court_id, full_name=n, honorific="Justice",
            current_position=f"Judge of {court_id}", is_active=True,
        )
        s.add(j)
        out.append(j)
    s.flush()
    backfill_canonical_aliases(s)
    return out


def _seed_matter(s, *, company_id, court_id, practice_area="Commercial",
                 code=None):
    m = Matter(
        company_id=company_id,
        title="Test matter",
        matter_code=code or f"X-{uuid4().hex[:6]}",
        client_name="Client",
        opposing_party="OP",
        status="active",
        practice_area=practice_area,
        forum_level="high_court",
        court_id=court_id,
        is_active=True,
    )
    s.add(m)
    s.flush()
    return m


def _seed_listing(s, *, matter_id, bench_name):
    e = MatterCauseListEntry(
        matter_id=matter_id,
        listing_date=date(2026, 6, 1),
        forum_name="HC bench, courtroom 12",
        bench_name=bench_name,
        source="test",
    )
    s.add(e)
    s.flush()
    return e


def _seed_authority_authored_by(s, *, court_name, judge_full_name,
                                title, summary, decision_year=2024):
    """Create an AuthorityDocument whose judges_json includes the
    judge's name (the structured-match path the bench-specific
    lookup uses)."""
    a = AuthorityDocument(
        source="test_corpus",
        adapter_name="test",
        court_name=court_name,
        forum_level="high_court",
        document_type="judgment",
        title=title,
        case_reference=f"TEST/{uuid4().hex[:6]}",
        bench_name=judge_full_name,
        neutral_citation=None,
        decision_date=date(decision_year, 1, 1),
        canonical_key=uuid4().hex,
        summary=summary,
        document_text=summary,
        extracted_char_count=len(summary),
        judges_json=json.dumps([judge_full_name]),
        parties_json="[]",
        advocates_json="[]",
    )
    s.add(a)
    s.flush()
    return a


def _ctx_for(session, company_id):
    """Pull a SessionContext-shaped namespace for the bootstrapped
    company. Uses the first membership we find."""
    from caseops_api.db.models import CompanyMembership
    membership = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.company_id == company_id
        )
    )
    return _make_session_context(membership)


def test_ft_024e_1_bench_specific_authorities_returned_when_resolved(
    client: TestClient,
) -> None:
    """When next_listing_id resolves to a bench AND that bench has
    authored ≥ 1 indexed authority, the response surfaces it."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        court = s.scalar(select(Court).where(Court.id == "bombay-hc"))
        _seed_judges_with_aliases(
            s, "bombay-hc",
            ["Aalia Banerjee", "Brijesh Karandikar", "Chitra Desai"],
        )
        m = _seed_matter(
            s, company_id=company_id, court_id="bombay-hc",
            practice_area="Commercial",
        )
        listing = _seed_listing(
            s, matter_id=m.id,
            bench_name="Justice Aalia Banerjee & Justice Brijesh Karandikar",
        )
        # Authorities authored by Justice Aalia Banerjee.
        for i in range(3):
            _seed_authority_authored_by(
                s, court_name=court.name,
                judge_full_name="Aalia Banerjee",
                title=f"Acme v Bharat #{i}",
                summary="Commercial appeal under Order XLI Rule 5.",
            )
        # An authority authored by a NON-bench judge — must NOT
        # appear in bench_specific_authorities.
        _seed_authority_authored_by(
            s, court_name=court.name,
            judge_full_name="Chitra Desai",
            title="Off-bench v Other",
            summary="Different bench, should not surface.",
        )
        s.commit()

        resolve_listing_bench(s, listing_id=listing.id)
        ctx = _ctx_for(s, company_id)
        result = build_bench_strategy_context(
            session=s, context=ctx, matter_id=m.id,
            next_listing_id=listing.id,
        )

    assert result.bench_specific_limitation_note is None
    assert len(result.bench_specific_authorities) >= 1
    titles = [a.title for a in result.bench_specific_authorities]
    assert all("Acme v Bharat" in t for t in titles), (
        f"off-bench authority leaked: {titles}"
    )


def test_ft_024e_2_no_listing_id_returns_empty_no_note(
    client: TestClient,
) -> None:
    """Calling without next_listing_id leaves the field empty AND
    sets no limitation note (this isn't a failure — the caller chose
    not to ask)."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        m = _seed_matter(s, company_id=company_id, court_id="bombay-hc")
        s.commit()
        ctx = _ctx_for(s, company_id)
        result = build_bench_strategy_context(
            session=s, context=ctx, matter_id=m.id,
        )
    assert result.bench_specific_authorities == []
    assert result.bench_specific_limitation_note is None


def test_ft_024e_3_unresolved_bench_emits_limitation_note(
    client: TestClient,
) -> None:
    """When next_listing_id points to a listing whose judges_json is
    NULL (resolver hasn't run / no high-quality match), the response
    has empty bench_specific_authorities AND a non-null limitation
    note explaining why."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        m = _seed_matter(s, company_id=company_id, court_id="bombay-hc")
        listing = _seed_listing(
            s, matter_id=m.id,
            bench_name="Some unresolvable bench string",
        )
        # Note: do NOT call resolve_listing_bench → judges_json stays NULL.
        s.commit()
        ctx = _ctx_for(s, company_id)
        result = build_bench_strategy_context(
            session=s, context=ctx, matter_id=m.id,
            next_listing_id=listing.id,
        )
    assert result.bench_specific_authorities == []
    assert result.bench_specific_limitation_note is not None
    assert "resolved" in result.bench_specific_limitation_note.lower()


def test_ft_024e_4_advocate_bias_prefers_practice_area_match(
    client: TestClient,
) -> None:
    """When the matter has a practice_area, authorities whose title
    or summary mentions that area rank ABOVE general bench
    authorities. Per PRD §2.1 — advocate-bias selection."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        court = s.scalar(select(Court).where(Court.id == "bombay-hc"))
        _seed_judges_with_aliases(
            s, "bombay-hc", ["Hema Bench"],
        )
        m = _seed_matter(
            s, company_id=company_id, court_id="bombay-hc",
            practice_area="Family",
        )
        listing = _seed_listing(
            s, matter_id=m.id, bench_name="Justice Hema Bench",
        )
        # General authority — older, no practice area mention.
        _seed_authority_authored_by(
            s, court_name=court.name, judge_full_name="Hema Bench",
            title="General Constitutional Matter",
            summary="Article 226 review.",
            decision_year=2018,
        )
        # Advocate-bias target — newer + matches practice area.
        _seed_authority_authored_by(
            s, court_name=court.name, judge_full_name="Hema Bench",
            title="Custody Dispute Family Petition",
            summary="Family law appeal under section 13.",
            decision_year=2024,
        )
        s.commit()
        resolve_listing_bench(s, listing_id=listing.id)
        ctx = _ctx_for(s, company_id)
        result = build_bench_strategy_context(
            session=s, context=ctx, matter_id=m.id,
            next_listing_id=listing.id,
        )
    titles = [a.title for a in result.bench_specific_authorities]
    relevances = [a.relevance for a in result.bench_specific_authorities]
    # Family authority must be FIRST.
    assert titles[0] == "Custody Dispute Family Petition"
    assert relevances[0] == "practice_area"


def test_ft_024e_5_no_favorability_copy_in_response(
    client: TestClient,
) -> None:
    """Structural sweep — every string field in the BenchStrategyContext
    output must be free of the forbidden token list."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        court = s.scalar(select(Court).where(Court.id == "bombay-hc"))
        _seed_judges_with_aliases(s, "bombay-hc", ["Test Judge"])
        m = _seed_matter(s, company_id=company_id, court_id="bombay-hc")
        listing = _seed_listing(
            s, matter_id=m.id, bench_name="Justice Test Judge",
        )
        _seed_authority_authored_by(
            s, court_name=court.name, judge_full_name="Test Judge",
            title="Some Authority", summary="Some summary text.",
        )
        s.commit()
        resolve_listing_bench(s, listing_id=listing.id)
        ctx = _ctx_for(s, company_id)
        result = build_bench_strategy_context(
            session=s, context=ctx, matter_id=m.id,
            next_listing_id=listing.id,
        )

    # Sweep every string field on every BenchSpecificAuthority + the
    # limitation note + drafting cautions + unsupported gaps.
    strings_to_sweep: list[str] = []
    for a in result.bench_specific_authorities:
        for v in (a.title, a.bench_name, a.relevance):
            if v:
                strings_to_sweep.append(v)
    if result.bench_specific_limitation_note:
        strings_to_sweep.append(result.bench_specific_limitation_note)
    strings_to_sweep.extend(result.drafting_cautions)
    strings_to_sweep.extend(result.unsupported_gaps)

    for probe in strings_to_sweep:
        assert not _FORBIDDEN.search(probe), (
            f"forbidden favorability token leaked into bench-specific "
            f"surface: {probe!r}"
        )


def test_ft_024e_6_cost_ceiling_capped_at_5(client: TestClient) -> None:
    """bench_specific_authorities respects the 5-authority cap (per
    Claude's self-decided ceiling in PRD §6 answer 3)."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        court = s.scalar(select(Court).where(Court.id == "bombay-hc"))
        _seed_judges_with_aliases(s, "bombay-hc", ["Cap Judge"])
        m = _seed_matter(s, company_id=company_id, court_id="bombay-hc")
        listing = _seed_listing(
            s, matter_id=m.id, bench_name="Justice Cap Judge",
        )
        # 12 authorities — well over the cap.
        for i in range(12):
            _seed_authority_authored_by(
                s, court_name=court.name, judge_full_name="Cap Judge",
                title=f"Authority {i}",
                summary="Some text.",
                decision_year=2020 + (i % 5),
            )
        s.commit()
        resolve_listing_bench(s, listing_id=listing.id)
        ctx = _ctx_for(s, company_id)
        result = build_bench_strategy_context(
            session=s, context=ctx, matter_id=m.id,
            next_listing_id=listing.id,
        )
    assert len(result.bench_specific_authorities) <= 5
