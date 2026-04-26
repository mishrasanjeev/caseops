"""Tests for the citation-extraction service."""
from __future__ import annotations

from caseops_api.services.citation_extraction import (
    extract_citations_from_text,
)


def test_extract_scc_simple() -> None:
    body = "As held in (2018) 6 SCC 1, the petitioner..."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    norm, ctext, reporter = cites[0]
    assert reporter == "scc"
    assert ctext == "(2018) 6 SCC 1"
    assert norm == "scc:2018:6:1"


def test_extract_air_sc() -> None:
    body = "Following AIR 2020 SC 145, the court held..."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    _, ctext, reporter = cites[0]
    assert reporter == "air_sc"
    assert ctext == "AIR 2020 SC 145"


def test_extract_scc_online_sc() -> None:
    body = "See 2023 SCC OnLine SC 1234 for the full discussion."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    _, ctext, reporter = cites[0]
    assert reporter == "scc_online_sc"
    assert ctext == "2023 SCC OnLine SC 1234"


def test_extract_multiple_distinct() -> None:
    body = (
        "As held in (2018) 6 SCC 1, and earlier in AIR 2015 SC 234, "
        "and most recently in 2024 SCC OnLine SC 99..."
    )
    cites = extract_citations_from_text(body)
    assert len(cites) == 3
    reporters = {c[2] for c in cites}
    assert reporters == {"scc", "air_sc", "scc_online_sc"}


def test_dedupe_within_one_doc() -> None:
    """Same citation appearing twice in one judgment yields one row."""
    body = (
        "(2018) 6 SCC 1 holds that... Per (2018) 6 SCC 1, the rule is..."
    )
    cites = extract_citations_from_text(body)
    assert len(cites) == 1


def test_reject_implausible_year() -> None:
    """Citations with year < 1860 or > 2030 are rejected (almost
    certainly parser noise — page numbers being read as years)."""
    body = "(1850) 6 SCC 1 should not match. Nor (2050) 1 SCC 1."
    cites = extract_citations_from_text(body)
    assert cites == []


def test_reject_implausible_page() -> None:
    """Page < 1 or > 99999 rejected."""
    body = "(2018) 6 SCC 0 should not match. (2018) 6 SCC 999999 either."
    cites = extract_citations_from_text(body)
    assert cites == []


def test_handle_punctuation_variants() -> None:
    """S.C.C. with periods + extra spaces should still match."""
    body = "(2018) 6 S.C.C. 1 is binding."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    assert cites[0][2] == "scc"


def test_empty_text_returns_empty() -> None:
    assert extract_citations_from_text("") == []
    assert extract_citations_from_text(None) == []  # type: ignore[arg-type]


def test_extract_scr() -> None:
    body = "See (2018) 13 SCR 1 for context."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    assert cites[0][2] == "scr"
    assert cites[0][1] == "(2018) 13 SCR 1"


def test_extract_crlj() -> None:
    body = "(2017) 4 CrLJ 5421 was followed."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    assert cites[0][2] == "crlj"
