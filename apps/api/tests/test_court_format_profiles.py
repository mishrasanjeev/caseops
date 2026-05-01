"""PG-005 Sprint 3 (2026-05-01) — court format profile tests.

The profile resolver picks the right page-layout spec for a draft's
PDF export based on either an explicit caller-supplied key or a fuzzy
match against the matter's ``court_name``. Both paths are covered
plus a few render-shape sanity checks on ``render_pdf_bytes``.
"""
from __future__ import annotations

import pytest

from caseops_api.services.court_format_profiles import (
    list_profiles,
    resolve_profile,
)
from caseops_api.services.draft_pdf_export import render_pdf_bytes


def test_explicit_supreme_court_key_wins() -> None:
    profile = resolve_profile(explicit_key="supreme_court", court_name="Delhi HC")
    assert profile.key == "supreme_court"
    # SC margins are 1.5 inches (38.1 mm) — bigger than the HC default.
    assert profile.margin_left_mm > 30


def test_unknown_explicit_key_raises() -> None:
    with pytest.raises(ValueError) as exc:
        resolve_profile(explicit_key="mars_high_court")
    assert "mars_high_court" in str(exc.value)


def test_court_name_fuzzy_match_resolves_delhi_hc() -> None:
    profile = resolve_profile(court_name="High Court of Delhi at New Delhi")
    assert profile.key == "delhi_hc"


def test_court_name_fuzzy_match_resolves_bombay_hc() -> None:
    profile = resolve_profile(
        court_name="High Court of Judicature at Bombay (Original Side)",
    )
    assert profile.key == "bombay_hc"


def test_court_name_fuzzy_match_resolves_supreme_court() -> None:
    profile = resolve_profile(court_name="Hon'ble Supreme Court of India")
    assert profile.key == "supreme_court"


def test_unknown_court_name_falls_through_to_generic() -> None:
    profile = resolve_profile(court_name="Sessions Court, Pune")
    assert profile.key == "generic"
    profile2 = resolve_profile(court_name=None)
    assert profile2.key == "generic"


def test_list_profiles_returns_four_in_stable_order() -> None:
    keys = [p.key for p in list_profiles()]
    assert keys == ["supreme_court", "delhi_hc", "bombay_hc", "generic"]


def test_render_pdf_bytes_produces_valid_pdf() -> None:
    """Pure-function render must produce a real PDF with the magic
    bytes prefix; non-empty body; >1KB sanity bulk."""
    profile = resolve_profile(explicit_key="delhi_hc")
    data = render_pdf_bytes(
        profile=profile,
        title="Bail Application — Sharma",
        matter_title="State v. Sharma",
        matter_code="MTR-001",
        draft_type="brief",
        revision=1,
        status_label="draft",
        body=(
            "1. The applicant is in custody since 1 March 2026 in FIR "
            "No. 145/2025 registered at Police Station Khar.\n\n"
            "2. The applicant has roots in the local community and is "
            "not a flight risk; the triple test under Sushila Aggarwal "
            "is satisfied."
        ),
        citations=[
            "Sushila Aggarwal v. State (NCT of Delhi) (2020) 5 SCC 1",
            "Gurbaksh Singh Sibbia v. State of Punjab (1980) 2 SCC 565",
        ],
        review_required=True,
    )
    assert data[:5] == b"%PDF-"
    assert data.endswith(b"%%EOF\n") or data.endswith(b"%%EOF")
    assert len(data) > 1000  # sanity — meaningful body, not a stub


def test_render_pdf_bytes_handles_unicode_dashes() -> None:
    """Em-dashes / smart quotes appear in LLM output. The renderer must
    strip them rather than crashing the fpdf2 writer."""
    profile = resolve_profile(explicit_key="generic")
    data = render_pdf_bytes(
        profile=profile,
        title="Title — with em dash",
        matter_title="Foo — Bar",
        matter_code="MTR-002",
        draft_type="brief",
        revision=1,
        status_label="draft",
        body="Para 1 — 'curly quotes' and an ellipsis…",
        citations=["Smith v. Jones [2020] 1 All ER 100"],
        review_required=False,
    )
    assert data[:5] == b"%PDF-"


def test_supreme_court_profile_uses_double_spacing_and_centered_pages() -> None:
    profile = resolve_profile(explicit_key="supreme_court")
    # SC court rules — double spacing (~7mm at 12pt) + center page numbers.
    assert profile.body_line_height_mm >= 6.5
    assert profile.page_number_position == "center"
    assert profile.court_header_text == "IN THE SUPREME COURT OF INDIA"


def test_generic_profile_does_not_inject_court_header() -> None:
    """Generic profile is the catch-all when court_name is unknown —
    must NOT inject a wrong court header."""
    profile = resolve_profile(explicit_key="generic")
    assert profile.show_court_header_first_page is False
    assert profile.court_header_text is None
