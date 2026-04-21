"""Pure-function tests for the SC-2023 retrieval-quality query normalisers.

Each of the five canonical 2026-04-20 HNSW misses feeds through the
matching normaliser and the expected variant appears in the output.
Non-matching queries are asserted to pass through untouched so the
retrieval fan-out does not waste an embedding call on a topical query.
"""

from __future__ import annotations

from caseops_api.services.retrieval_normalisers import (
    build_query_variants,
    is_non_english_script,
    normalise_bench_query,
    normalise_citation_query,
)

# ---------------------------------------------------------------------------
# normalise_citation_query
# ---------------------------------------------------------------------------


def test_normalise_citation_bracketed_scr_2019() -> None:
    variants = normalise_citation_query("[2019] 1 S.C.R. 1001")
    assert "2019 1 SCR 1001" in variants
    assert "[2019] 1 SCR 1001" in variants
    assert "[2019] 1 S.C.R. 1001" in variants


def test_normalise_citation_bracketed_scr_2021() -> None:
    variants = normalise_citation_query("[2021] 1 S.C.R. 694")
    assert "2021 1 SCR 694" in variants
    assert "[2021] 1 SCR 694" in variants


def test_normalise_citation_pure_numeric() -> None:
    variants = normalise_citation_query("2022 15 827")
    assert "2022 15 827" in variants
    # At least one wrapped variant must appear so the corpus's
    # "[2022] 15 SCR 827" encoding has something to hit.
    wrapped = [v for v in variants if v.startswith("[") or v.startswith("(")]
    assert wrapped, f"expected wrapped variants, got {variants!r}"


def test_normalise_citation_alpha_query_passes_through() -> None:
    # Topical queries must NOT be rewritten — that would waste an
    # embedding call and pollute the union.
    assert normalise_citation_query("bail application") == ["bail application"]


def test_normalise_citation_mixed_alpha_numeric_passes_through() -> None:
    # The pure-numeric rule must skip queries that carry any alpha.
    assert normalise_citation_query("bail 2022 15 827") == ["bail 2022 15 827"]


def test_normalise_citation_variants_are_deduplicated() -> None:
    variants = normalise_citation_query("2019 1 SCR 1001")
    assert len(variants) == len(set(variants))


# ---------------------------------------------------------------------------
# normalise_bench_query
# ---------------------------------------------------------------------------


def test_normalise_bench_drops_bench_suffix() -> None:
    assert normalise_bench_query("DHARWAD BENCH") == "Dharwad"


def test_normalise_bench_drops_court_suffix() -> None:
    assert normalise_bench_query("BOMBAY HIGH COURT") == "Bombay High"


def test_normalise_bench_returns_none_for_mixed_case() -> None:
    assert normalise_bench_query("Dharwad bench") is None


def test_normalise_bench_returns_none_when_suffix_absent() -> None:
    assert normalise_bench_query("DHARWAD KARNATAKA") is None


def test_normalise_bench_returns_none_for_long_query() -> None:
    # Rule requires ≤ 4 tokens; topical queries never trigger.
    assert (
        normalise_bench_query("FIVE TOKEN ALL CAPS QUERY TEST")
        is None
    )


# ---------------------------------------------------------------------------
# is_non_english_script
# ---------------------------------------------------------------------------


def test_is_non_english_script_detects_gurmukhi() -> None:
    assert is_non_english_script(
        "ਐਮ/ਐਸ ਏਪੈਕਸ ਲੈਬੋਰੇਟਰੀਜ਼ ਪ੍ਰਾਈਵੇਟ ਿਲਿਮਟੇਡ"
    )


def test_is_non_english_script_false_for_english_legal_query() -> None:
    assert not is_non_english_script("bail BNSS 483 triple test")


def test_is_non_english_script_false_for_empty() -> None:
    assert not is_non_english_script("")


# ---------------------------------------------------------------------------
# build_query_variants (aggregator)
# ---------------------------------------------------------------------------


def test_build_query_variants_always_includes_original() -> None:
    variants = build_query_variants("[2019] 1 S.C.R. 1001")
    assert "[2019] 1 S.C.R. 1001" in variants
    assert variants[0] == "[2019] 1 S.C.R. 1001"


def test_build_query_variants_topical_query_is_singleton() -> None:
    assert build_query_variants("bail application") == ["bail application"]


def test_build_query_variants_bench_appends_stem() -> None:
    variants = build_query_variants("DHARWAD BENCH")
    assert "DHARWAD BENCH" in variants
    assert "Dharwad" in variants
