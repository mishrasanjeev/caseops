"""Language-suffix filter for SC corpus ingest.

Anchored to the 2026-04-26 SC-2000 sweep where the run burned ~30 min
of CPU iterating Hindi/Bengali/Telugu PDFs that all skip at the
OCR-unavailable fallback. The filter drops them BEFORE PDF parse so
the per-doc cost goes from ~5-10s to ~0s.
"""
from __future__ import annotations

from pathlib import Path

from caseops_api.services.corpus_ingest import _matches_language_filter


def _p(name: str) -> Path:
    return Path("/tmp/fake") / name


def test_no_filter_keeps_everything() -> None:
    assert _matches_language_filter(_p("S_2000_5_249_275_EN.pdf"), None) is True
    assert _matches_language_filter(_p("S_2000_5_249_275_HIN.pdf"), None) is True
    assert _matches_language_filter(_p("WP_1234_of_2019.pdf"), None) is True
    assert _matches_language_filter(_p("S_2000_5_249_275_EN.pdf"), ()) is True


def test_en_filter_keeps_english_drops_others() -> None:
    f = ("EN",)
    assert _matches_language_filter(_p("S_2000_5_249_275_EN.pdf"), f) is True
    assert _matches_language_filter(_p("S_2000_5_249_275_HIN.pdf"), f) is False
    assert _matches_language_filter(_p("S_2000_5_249_275_BEN.pdf"), f) is False
    assert _matches_language_filter(_p("S_2000_5_249_275_TEL.pdf"), f) is False
    assert _matches_language_filter(_p("S_2000_5_249_275_TAM.pdf"), f) is False


def test_filter_passes_files_without_language_tag() -> None:
    """HC convention has no _<LANG>.pdf suffix. The filter must not
    drop them — otherwise enabling --language-suffix EN on a mixed
    SC+HC sweep would silently kill all HC files."""
    f = ("EN",)
    assert _matches_language_filter(_p("WP_1234_of_2019.pdf"), f) is True
    assert _matches_language_filter(_p("CRA_50_2018.pdf"), f) is True
    assert _matches_language_filter(_p("Civil_Appeal_42_of_2020.pdf"), f) is True


def test_filter_is_case_insensitive_on_input() -> None:
    """``--language-suffix en`` should behave the same as ``EN``."""
    assert _matches_language_filter(_p("S_2000_5_249_275_EN.pdf"), ("en",)) is True
    assert _matches_language_filter(_p("S_2000_5_249_275_EN.pdf"), ("En",)) is True


def test_multi_language_filter_keeps_each() -> None:
    f = ("EN", "HIN")
    assert _matches_language_filter(_p("S_2000_5_249_275_EN.pdf"), f) is True
    assert _matches_language_filter(_p("S_2000_5_249_275_HIN.pdf"), f) is True
    assert _matches_language_filter(_p("S_2000_5_249_275_BEN.pdf"), f) is False


def test_filter_does_not_match_non_pdf_extension() -> None:
    """A txt file accidentally landing in the workdir shouldn't be
    parsed as a language-tagged PDF."""
    assert _matches_language_filter(_p("S_2000_5_249_275_EN.txt"), ("EN",)) is True
    # The filter only inspects ``_<LANG>.pdf`` patterns.


def test_filter_handles_uppercase_suffix() -> None:
    """The S3 convention uses uppercase, but defensive: ensure either
    case matches when looking at filename."""
    assert _matches_language_filter(_p("S_2000_5_249_275_en.pdf"), ("EN",)) is True
    assert _matches_language_filter(_p("S_2000_5_249_275_hin.pdf"), ("EN",)) is False
