"""Tests for the corpus-derived HC judge backfill.

Per docs/PRD_BENCH_STRATEGY_2026-04-26.md §4.2 prereq. Exercises the
honorific-strip + non-name reject + court-resolution + dedup logic so
parser noise doesn't pollute the registry.
"""
from __future__ import annotations

from caseops_api.scripts.backfill_hc_judges_from_corpus import (
    _is_real_name,
    _resolve_court_id,
    _strip_honorifics,
)


def test_strip_honorifics_drops_leading_titles() -> None:
    assert _strip_honorifics("Hon'ble Mr. Justice Yashwant Varma") == "Yashwant Varma"
    assert _strip_honorifics("Hon'ble Ms. Justice Neena Bansal Krishna") == "Neena Bansal Krishna"
    assert _strip_honorifics("Justice V. Kameswar Rao") == "V. Kameswar Rao"
    assert _strip_honorifics("Mr. Justice Anoop Kumar") == "Anoop Kumar"


def test_strip_honorifics_drops_trailing_J_marker() -> None:
    assert _strip_honorifics("V. Kameswar Rao, J") == "V. Kameswar Rao"
    assert _strip_honorifics("V. Kameswar Rao, J.") == "V. Kameswar Rao"
    assert _strip_honorifics("Subramonium Prasad J") == "Subramonium Prasad"
    assert _strip_honorifics("YASHWANT VARMA, J.") == "Yashwant Varma"


def test_strip_honorifics_titlecases_all_caps() -> None:
    assert _strip_honorifics("DHARMESH SHARMA, J.") == "Dharmesh Sharma"
    assert _strip_honorifics("PURUSHAINDRA KUMAR KAURAV") == "Purushaindra Kumar Kaurav"


def test_strip_honorifics_passthrough_on_clean_input() -> None:
    assert _strip_honorifics("Saurabh Banerjee") == "Saurabh Banerjee"
    assert _strip_honorifics("V. Kameswar Rao") == "V. Kameswar Rao"


def test_is_real_name_rejects_role_only_strings() -> None:
    """The corpus has standalone role markers in the bench list
    ('Acting Chief Justice', 'Bench', 'Per:', 'The Court', 'Coram')
    that are NOT actual judge names. They must be rejected."""
    assert _is_real_name("Acting Chief Justice") is False
    assert _is_real_name("Chief Justice") is False
    assert _is_real_name("Bench") is False
    assert _is_real_name("Per:") is False
    assert _is_real_name("The Court") is False
    assert _is_real_name("Coram") is False
    assert _is_real_name("Honble") is False


def test_is_real_name_requires_two_tokens_with_letters() -> None:
    """A single-token entry is almost always a parser artefact
    (a court name fragment, a punctuation residue, etc.)."""
    assert _is_real_name("Yashwant") is False  # only first name
    assert _is_real_name("Yashwant Varma") is True
    assert _is_real_name("V. Kameswar Rao") is True
    assert _is_real_name("") is False
    assert _is_real_name("---") is False  # no letters


def test_resolve_court_id_maps_substring_to_court_id() -> None:
    assert _resolve_court_id("Delhi High Court") == "delhi-hc"
    assert _resolve_court_id("High Court of Bombay") == "bombay-hc"
    assert _resolve_court_id("Karnataka High Court") == "karnataka-hc"
    assert _resolve_court_id("Telangana High Court") == "telangana-hc"
    assert _resolve_court_id("Allahabad High Court") == "allahabad-hc"
    assert _resolve_court_id("Calcutta High Court") == "calcutta-hc"
    assert _resolve_court_id("High Court of Madras") == "madras-hc"


def test_resolve_court_id_returns_none_for_unknown() -> None:
    assert _resolve_court_id("Sikkim High Court") is None  # not in scope
    assert _resolve_court_id("Supreme Court of India") is None  # not HC
    assert _resolve_court_id("") is None
    assert _resolve_court_id(None) is None
