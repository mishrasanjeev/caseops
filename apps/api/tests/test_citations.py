from __future__ import annotations

from caseops_api.services.citations import (
    Claim,
    SourceDoc,
    verify_citations,
)

SSANGYONG = SourceDoc(
    identifier="Ssangyong Engg v. NHAI (2019)",
    aliases=("Ssangyong Engg. v. NHAI",),
    text=(
        "The Supreme Court held that patent illegality is a ground for setting aside "
        "an arbitral award under Section 34 of the Arbitration and Conciliation Act, "
        "1996, where the award is fundamentally opposed to Indian law or public policy."
    ),
)
PATEL = SourceDoc(
    identifier="Patel Engg v. Union of India (2008)",
    text=(
        "The Court reiterated that an arbitrator's finding that is perverse or based on "
        "no evidence at all can be set aside for patent illegality."
    ),
)


def test_matched_citation_with_supported_proposition_is_verified() -> None:
    claims = [
        Claim(
            citation="Ssangyong Engg v. NHAI (2019)",
            proposition="patent illegality is a ground under Section 34",
        ),
    ]
    report = verify_citations(claims, [SSANGYONG, PATEL])
    assert report.all_verified
    assert report.checks[0].reason == "proposition_supported"


def test_matched_citation_without_proposition_counts_as_bare() -> None:
    report = verify_citations(
        [Claim(citation="Ssangyong Engg v. NHAI (2019)")],
        [SSANGYONG],
    )
    assert report.all_verified
    assert report.checks[0].reason == "bare_citation"


def test_unknown_citation_is_marked() -> None:
    report = verify_citations(
        [Claim(citation="Fictional v. Nobody (1999)", proposition="anything")],
        [SSANGYONG],
    )
    assert not report.all_verified
    assert report.checks[0].reason == "unknown_source"
    assert report.checks[0].source is None


def test_matched_citation_with_unsupported_proposition_is_rejected() -> None:
    report = verify_citations(
        [
            Claim(
                citation="Ssangyong Engg v. NHAI (2019)",
                proposition="taxation of non-resident shipping companies",
            )
        ],
        [SSANGYONG],
    )
    assert not report.all_verified
    assert report.checks[0].reason == "proposition_not_supported"


def test_aliases_are_accepted() -> None:
    report = verify_citations(
        [
            Claim(
                citation="Ssangyong Engg. v. NHAI",
                proposition="patent illegality under Section 34",
            )
        ],
        [SSANGYONG],
    )
    assert report.all_verified
    assert report.checks[0].reason == "proposition_supported"


def test_case_and_punctuation_variations_match() -> None:
    report = verify_citations(
        [
            Claim(
                citation="  ssangyong   engg v nhai  (2019)",
                proposition="Section 34 patent illegality",
            )
        ],
        [SSANGYONG],
    )
    assert report.all_verified


def test_bracket_tag_resolves_to_indexed_source() -> None:
    """Grounding fast path: model emits "[1] ..." → verifier resolves by index
    and skips the proposition gate. Deterministic, even when the rationale
    shares no tokens with the source text."""
    report = verify_citations(
        [
            Claim(
                citation="[1] paraphrased title that does not match the source",
                proposition="entirely unrelated proposition tokens xyz qrs",
            ),
        ],
        [SSANGYONG, PATEL],
    )
    assert report.all_verified
    assert report.checks[0].reason == "bracket_tag_match"
    assert report.checks[0].source is SSANGYONG


def test_bracket_tag_out_of_range_falls_through_to_fuzzy() -> None:
    """[7] when only 2 sources exist: bracket lookup returns None, fuzzy path
    runs. With a citation that has no token overlap the claim stays unverified."""
    report = verify_citations(
        [Claim(citation="[7] Fictional v. Nobody (1999)", proposition="anything")],
        [SSANGYONG, PATEL],
    )
    assert not report.all_verified
    assert report.checks[0].reason == "unknown_source"


def test_bracket_tag_with_leading_whitespace_still_resolves() -> None:
    report = verify_citations(
        [Claim(citation="   [2] Patel Engg")],
        [SSANGYONG, PATEL],
    )
    assert report.all_verified
    assert report.checks[0].source is PATEL


def test_report_counters() -> None:
    claims = [
        Claim(
            citation="Ssangyong Engg v. NHAI (2019)",
            proposition="patent illegality under Section 34",
        ),
        Claim(citation="Fictional v. Nobody (1999)", proposition="anything"),
        Claim(citation="Patel Engg v. Union of India (2008)"),
    ]
    report = verify_citations(claims, [SSANGYONG, PATEL])
    assert report.verified_count == 2
    assert report.unverified_count == 1
    assert report.has_any_verified
    assert not report.all_verified
