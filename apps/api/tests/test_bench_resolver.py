"""Slice B (MOD-TS-001-C) — bench parser + resolver tests.

Maps to FT-024D-1 .. FT-024D-6 in
``docs/PRD_BENCH_MAPPING_2026-04-25.md`` §3 Slice B.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    Judge,
    Matter,
    MatterCauseListEntry,
)
from caseops_api.services.bench_resolver import (
    parse_bench_name,
    resolve_listing_bench,
)
from caseops_api.services.judge_aliases import backfill_canonical_aliases
from tests.test_auth_company import bootstrap_company


def _seed_judges(s, court_id, names):
    out = []
    for n in names:
        j = Judge(
            court_id=court_id, full_name=n, honorific="Justice",
            current_position=f"Judge of {court_id}", is_active=True,
        )
        s.add(j)
        out.append(j)
    s.flush()
    return out


def _seed_matter(s, *, company_id, court_id, code="X-1"):
    m = Matter(
        company_id=company_id,
        title="Test matter",
        matter_code=code,
        client_name="Client",
        opposing_party="OP",
        status="active",
        practice_area="Commercial",
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
        listing_date=date(2026, 5, 1),
        forum_name="Bombay HC, Mumbai PB",
        bench_name=bench_name,
        source="cause_list_scrape",
    )
    s.add(e)
    s.flush()
    return e


def test_ft_024d_1_parse_bench_name_happy_paths() -> None:
    """1 judge / 2 judges with & / 3 judges with , and and."""
    assert parse_bench_name("Justice A. K. Sikri") == ["Justice A. K. Sikri"]
    assert parse_bench_name("Justice X & Justice Y") == [
        "Justice X", "Justice Y",
    ]
    assert parse_bench_name(
        "Hon'ble Mr. Justice X, Hon'ble Mr. Justice Y and Hon'ble Mr. Justice Z"
    ) == [
        "Hon'ble Mr. Justice X",
        "Hon'ble Mr. Justice Y",
        "Hon'ble Mr. Justice Z",
    ]


def test_ft_024d_2_parse_bench_name_edge_cases() -> None:
    """typos, missing dots, ALL CAPS, mixed case, semicolons."""
    # ALL CAPS.
    assert parse_bench_name("JUSTICE X & JUSTICE Y") == [
        "JUSTICE X", "JUSTICE Y",
    ]
    # Semicolon separator.
    assert parse_bench_name("Justice A ; Justice B") == [
        "Justice A", "Justice B",
    ]
    # Missing dots in initials.
    assert parse_bench_name("Justice AK Sikri & Justice JB Pardiwala") == [
        "Justice AK Sikri", "Justice JB Pardiwala",
    ]
    # Empty / None.
    assert parse_bench_name("") == []
    assert parse_bench_name("   ") == []


def test_ft_024d_3_court_scope_blocks_cross_court_resolution(
    client: TestClient,
) -> None:
    """A Bombay HC bench string MUST NOT resolve to an SC judge,
    even on perfect name match. The resolver scopes by the matter's
    court_id."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        # Same name in two courts.
        _seed_judges(s, "supreme-court-india", ["Common Name"])
        _seed_judges(s, "bombay-hc", ["Common Name"])
        s.commit()
        backfill_canonical_aliases(s)
        # Matter is in Bombay HC.
        m = _seed_matter(s, company_id=company_id, court_id="bombay-hc")
        listing = _seed_listing(s, matter_id=m.id, bench_name="Justice Common Name")
        s.commit()
        listing_id = listing.id

    with get_session_factory()() as s:
        matched, unmatched = resolve_listing_bench(s, listing_id=listing_id)
        # Should resolve to the BOMBAY judge, not the SC one.
        assert len(matched) == 1
        bombay_judge_id = s.scalar(
            select(Judge.id).where(
                Judge.court_id == "bombay-hc",
                Judge.full_name == "Common Name",
            )
        )
        sc_judge_id = s.scalar(
            select(Judge.id).where(
                Judge.court_id == "supreme-court-india",
                Judge.full_name == "Common Name",
            )
        )
        assert matched[0].judge_id == bombay_judge_id
        assert matched[0].judge_id != sc_judge_id


def test_ft_024d_4_tolerant_match_resolves_initial_to_full_name(
    client: TestClient,
) -> None:
    """'A.K. Sikri' resolves to 'Adarsh Kumar Sikri' Judge.id."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        _seed_judges(s, "supreme-court-india", ["Adarsh Kumar Sikri"])
        s.commit()
        backfill_canonical_aliases(s)
        m = _seed_matter(
            s, company_id=company_id, court_id="supreme-court-india",
            code="X-2",
        )
        listing = _seed_listing(
            s, matter_id=m.id, bench_name="Justice A.K. Sikri",
        )
        s.commit()
        listing_id = listing.id
        expected_judge_id = s.scalar(
            select(Judge.id).where(
                Judge.full_name == "Adarsh Kumar Sikri"
            )
        )

    with get_session_factory()() as s:
        matched, _unmatched = resolve_listing_bench(s, listing_id=listing_id)
    assert len(matched) >= 1
    assert any(m.judge_id == expected_judge_id for m in matched)


def test_ft_024d_5_idempotent_persists_resolved_payload(
    client: TestClient,
) -> None:
    """Re-resolving a row with a known mapping produces no duplicates
    and persists the same JSON payload."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        _seed_judges(s, "supreme-court-india", ["Test Justice"])
        s.commit()
        backfill_canonical_aliases(s)
        m = _seed_matter(
            s, company_id=company_id, court_id="supreme-court-india",
            code="X-3",
        )
        listing = _seed_listing(
            s, matter_id=m.id, bench_name="Justice Test Justice",
        )
        s.commit()
        listing_id = listing.id

    with get_session_factory()() as s:
        m1, _ = resolve_listing_bench(s, listing_id=listing_id)
        m2, _ = resolve_listing_bench(s, listing_id=listing_id)
        # Re-read the row.
        row = s.scalar(
            select(MatterCauseListEntry).where(
                MatterCauseListEntry.id == listing_id
            )
        )
    assert len(m1) == len(m2)
    parsed = json.loads(row.judges_json)
    assert parsed[0]["judge_id"] == m1[0].judge_id


def test_ft_024d_6_unmatched_rate_is_returned_as_metric(
    client: TestClient,
) -> None:
    """The resolver returns counts as a structured tuple/dict so the
    backfill job logs unmatched-rate as a numeric metric, not just
    free-text WARN."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        _seed_judges(s, "supreme-court-india", ["Real Judge"])
        s.commit()
        backfill_canonical_aliases(s)
        m = _seed_matter(
            s, company_id=company_id, court_id="supreme-court-india",
            code="X-4",
        )
        # Unknown name in the bench string — should land in unmatched.
        listing = _seed_listing(
            s, matter_id=m.id,
            bench_name="Justice Real Judge & Justice Unknown Name",
        )
        s.commit()
        listing_id = listing.id

    with get_session_factory()() as s:
        matched, unmatched = resolve_listing_bench(s, listing_id=listing_id)
    assert isinstance(unmatched, list)
    assert len(unmatched) == 1
    assert "Unknown Name" in unmatched[0]
    # Matched still includes the real one.
    assert len(matched) == 1


def test_resolve_listing_bench_no_court_scope_returns_unprocessed(
    client: TestClient,
) -> None:
    """Matter without court_id → resolver leaves the row unprocessed
    (judges_json IS NULL) so the ops dashboard surfaces it for fix."""
    from caseops_api.db.session import get_session_factory

    boot = bootstrap_company(client)
    company_id = boot["company"]["id"]
    with get_session_factory()() as s:
        m = Matter(
            company_id=company_id, title="No court matter",
            matter_code="NC-1", client_name="C", opposing_party="O",
            status="active", practice_area="X",
            forum_level="high_court", court_id=None, is_active=True,
        )
        s.add(m)
        s.flush()
        listing = _seed_listing(s, matter_id=m.id, bench_name="Justice X")
        s.commit()
        listing_id = listing.id

    with get_session_factory()() as s:
        matched, unmatched = resolve_listing_bench(s, listing_id=listing_id)
        row = s.scalar(
            select(MatterCauseListEntry).where(
                MatterCauseListEntry.id == listing_id
            )
        )
    assert matched == []
    assert unmatched, "should surface the unparsed candidate"
    assert row.judges_json is None, (
        "no court scope means we leave judges_json NULL so the "
        "row is still discoverable by the backfill job"
    )
