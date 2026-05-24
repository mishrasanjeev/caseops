"""PG-005 Sprint 3 (2026-05-01) — court format profile tests.

The profile resolver picks the right page-layout spec for a draft's
PDF export based on either an explicit caller-supplied key or a fuzzy
match against the matter's ``court_name``. Both paths are covered
plus a few render-shape sanity checks on ``render_pdf_bytes``.
"""
from __future__ import annotations

import pytest

from caseops_api.services.court_format_profiles import (
    format_cause_title,
    list_profiles,
    resolve_profile,
    validate_required_fields,
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
    profile = resolve_profile(court_name="Metaverse Forum, Pune")
    assert profile.key == "generic"
    profile2 = resolve_profile(court_name=None)
    assert profile2.key == "generic"


def test_list_profiles_returns_adp16_profiles_in_stable_order() -> None:
    """PG-005 Sprint 5 (2026-05-01): expanded from 4 to 10 profiles —
    SC → HC (Delhi / Bombay / Madras / Calcutta / Karnataka) →
    tribunals (NCLT / NCLAT / DRT) → generic."""
    keys = [p.key for p in list_profiles()]
    assert keys == [
        "supreme_court",
        "high_court",
        "delhi_hc",
        "bombay_hc",
        "madras_hc",
        "calcutta_hc",
        "karnataka_hc",
        "district_court",
        "tribunal",
        "nclt",
        "nclat",
        "drt",
        "generic",
    ]
    categories = {p.category for p in list_profiles()}
    assert {
        "district_court",
        "high_court",
        "supreme_court",
        "tribunal",
        "generic",
    }.issubset(categories)


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


# ---------------------------------------------------------------
# PG-005 Sprint 5 (2026-05-01): expanded court profiles + cause-title
# formatting helper.
# ---------------------------------------------------------------


def test_madras_hc_resolves_from_court_name() -> None:
    profile = resolve_profile(court_name="High Court of Judicature at Madras")
    assert profile.key == "madras_hc"
    assert "MADRAS" in (profile.court_header_text or "")


def test_calcutta_hc_resolves_from_court_name() -> None:
    profile = resolve_profile(court_name="High Court at Calcutta (Original Side)")
    assert profile.key == "calcutta_hc"
    assert "CALCUTTA" in (profile.court_header_text or "")


def test_karnataka_hc_resolves_from_court_name() -> None:
    profile = resolve_profile(court_name="High Court of Karnataka, Bengaluru")
    assert profile.key == "karnataka_hc"
    assert "KARNATAKA" in (profile.court_header_text or "")


def test_nclat_resolves_before_nclt_substring() -> None:
    """NCLAT contains 'NCLT' as a substring — fuzzy match must route
    'National Company Law Appellate Tribunal' to NCLAT, not NCLT."""
    profile = resolve_profile(court_name="National Company Law Appellate Tribunal, Principal Bench")
    assert profile.key == "nclat"
    profile_short = resolve_profile(court_name="NCLAT")
    assert profile_short.key == "nclat"


def test_nclt_resolves_from_court_name() -> None:
    profile = resolve_profile(court_name="National Company Law Tribunal, Mumbai Bench")
    assert profile.key == "nclt"
    profile_short = resolve_profile(court_name="NCLT, New Delhi")
    assert profile_short.key == "nclt"


def test_drt_resolves_from_court_name() -> None:
    profile = resolve_profile(court_name="Debts Recovery Tribunal, Mumbai")
    assert profile.key == "drt"
    profile_short = resolve_profile(court_name="DRT-III, Delhi")
    assert profile_short.key == "drt"


def test_adp16_category_profiles_resolve_from_general_court_names() -> None:
    assert resolve_profile(court_name="High Court of Rajasthan").key == "high_court"
    assert resolve_profile(court_name="Sessions Court, Pune").key == "district_court"
    assert resolve_profile(court_name="State Transport Appellate Tribunal").key == "tribunal"


def test_adp16_required_fields_are_profile_and_template_aware() -> None:
    district = resolve_profile(explicit_key="district_court")
    findings = validate_required_fields(
        district,
        template_type="bail",
        facts={
            "complainant_name": "State",
            "accused_name": "Amit Rao",
            "fir_number": "145/2026",
        },
        matter_court_name="Sessions Court, Pune",
    )

    by_key = {finding.key: finding for finding in findings}
    assert by_key["court_or_forum_name"].satisfied is True
    assert by_key["party_names"].satisfied is True
    assert by_key["fir_number"].satisfied is True
    assert by_key["police_station"].satisfied is False
    assert by_key["police_station"].source is None
    assert by_key["case_number"].satisfied is False


def test_adp16_supreme_court_template_fields_include_order_and_limitation() -> None:
    profile = resolve_profile(explicit_key="supreme_court")
    findings = validate_required_fields(
        profile,
        template_type="special_leave_petition",
        facts={
            "petitioner_name": "Anil Sharma",
            "respondent_name": "Union of India",
            "impugned_order_date": "2026-04-01",
        },
        matter_court_name=None,
    )

    by_key = {finding.key: finding for finding in findings}
    assert by_key["petitioner_or_appellant"].satisfied is True
    assert by_key["respondent_name"].satisfied is True
    assert by_key["impugned_order_details"].satisfied is True
    assert by_key["limitation_or_certification"].satisfied is False


def test_adp16_generic_profile_has_no_required_field_findings() -> None:
    profile = resolve_profile(explicit_key="generic")
    assert validate_required_fields(
        profile,
        template_type="bail",
        facts={},
        matter_court_name=None,
    ) == []


def test_format_cause_title_supreme_court_uses_uppercase_versus() -> None:
    """SC profile: ALL CAPS, numbered when multi-party, 'VERSUS'
    separator. The classic SC cause-title style."""
    profile = resolve_profile(explicit_key="supreme_court")
    title = format_cause_title(
        profile=profile,
        petitioner_names=["Anil Sharma"],
        respondent_names=["Union of India", "State of Maharashtra"],
    )
    assert "ANIL SHARMA" in title
    assert "VERSUS" in title
    assert "1. UNION OF INDIA" in title
    assert "2. STATE OF MAHARASHTRA" in title
    assert "Petitioner" in title
    assert "Respondent(s)" in title


def test_format_cause_title_generic_uses_title_case_v_dot() -> None:
    """Generic profile: title case, 'v.' separator, no numbering."""
    profile = resolve_profile(explicit_key="generic")
    title = format_cause_title(
        profile=profile,
        petitioner_names=["John Doe"],
        respondent_names=["Acme Corp"],
    )
    assert "John Doe" in title
    assert "Acme Corp" in title
    assert "v." in title
    # Single party → not numbered.
    assert "1." not in title


def test_format_cause_title_handles_empty_party_lists() -> None:
    """Caller may invoke before the matter has parties filled in —
    the helper returns a placeholder rather than crashing."""
    profile = resolve_profile(explicit_key="delhi_hc")
    title = format_cause_title(
        profile=profile,
        petitioner_names=[],
        respondent_names=["State of Delhi"],
    )
    assert "to be filled in" in title.lower()
    assert "STATE OF DELHI" in title


def test_tribunal_profiles_use_smaller_body_font() -> None:
    """Tribunals (NCLT / NCLAT / DRT) use 11pt body font like the
    generic profile — they are less rigid than SC / HC."""
    for key in ("nclt", "nclat", "drt"):
        profile = resolve_profile(explicit_key=key)
        assert profile.body_font_size_pt == 11, (
            f"{key} expected 11pt body font, got {profile.body_font_size_pt}"
        )
