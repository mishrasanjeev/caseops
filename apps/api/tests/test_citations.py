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
