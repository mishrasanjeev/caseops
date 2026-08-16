"""EH-SGR-07 (part 1): the proposition gate was near-vacuous on its own terms.

`verify_citations` documents its proposition check as requiring "at least two
non-stopword tokens (length >= 3) appearing in the source text". Neither half of
that was true:

1. `meaningful` was a LIST, so the SAME token counted twice satisfied
   `len(meaningful) >= 2`. A proposition containing "the" twice verified against
   any source containing "the".
2. There was no stopword list anywhere in the module. The length>=3 cut keeps
   "the", "and", "that", "was", "his".

This commit closes both.

SUPERSEDED IN THE SAME PR: this file originally continued "It does NOT make the
proposition gate mandatory - the bracket-tag path still short-circuits ahead of
it - so production paths that route through a bracket tag are unaffected." That
was true when written and is now false. Once the callers passed real
propositions, the tag was demoted to a source resolver and the gate became
mandatory; see test_20260816_bracket_tag_is_a_resolver.py. The
`test_bracket_tag_no_longer_short_circuits` case below is the inverted original.

What this gate is, honestly, even after hardening: a topicality filter. It is
bag-of-words and order-insensitive, so it cannot separate "X is a ground" from
"X is not a ground". The docstring is corrected to say so rather than continue
to claim support checking it does not perform.
"""

from __future__ import annotations

import pytest

from caseops_api.services.citations import Claim, SourceDoc, verify_citations

_SOURCE_TEXT = (
    "The Supreme Court held that patent illegality is a ground for setting aside "
    "an arbitral award under Section 34 of the Arbitration and Conciliation Act."
)


def _sources() -> list[SourceDoc]:
    return [SourceDoc(identifier="2021 SCC 1", text=_SOURCE_TEXT)]


def _verify(proposition: str, citation: str = "2021 SCC 1"):
    report = verify_citations(
        [Claim(citation=citation, proposition=proposition)],
        _sources(),
    )
    return report.checks[0]


class TestDuplicateTokensNoLongerCount:
    def test_the_same_stopword_twice_does_not_verify(self) -> None:
        check = _verify("the award the award")
        assert check.verified is False, (
            "`meaningful` was a list, so one repeated token satisfied the "
            "two-token rule; a proposition of pure function words verified "
            "against any source sharing them"
        )

    def test_a_single_distinct_content_word_is_not_enough(self) -> None:
        check = _verify("illegality illegality illegality")
        assert check.verified is False

    def test_two_distinct_content_words_still_verify(self) -> None:
        check = _verify("patent illegality is a ground under Section 34")
        assert check.verified is True
        assert check.reason == "proposition_supported"


class TestStopwordsAreExcluded:
    @pytest.mark.parametrize(
        "proposition",
        [
            "the and that was his",
            "the court and the award",
            "that was the one",
        ],
    )
    def test_function_words_alone_do_not_verify(self, proposition: str) -> None:
        assert _verify(proposition).verified is False

    def test_content_words_survive_stopword_filtering(self) -> None:
        # "the" and "under" are dropped; "arbitral" and "award" remain.
        assert _verify("the arbitral award under review").verified is True


class TestUnchangedBehaviour:
    """Guard the properties that must not move in this commit."""

    def test_bracket_tag_no_longer_short_circuits(self) -> None:
        """Superseded in the same PR: the tag became a resolver, not a verdict.

        This assertion originally read `verified is True` / `bracket_tag_match`
        and was labelled "this commit hardens the gate; it does not make it
        mandatory". Making it mandatory was the follow-up, once the callers
        passed real propositions. See test_20260816_bracket_tag_is_a_resolver.py.
        """
        check = _verify("wholly unrelated subject matter", citation="[1] anything")
        assert check.verified is False
        assert check.reason == "proposition_not_supported"

    def test_no_proposition_is_still_a_bare_citation(self) -> None:
        report = verify_citations([Claim(citation="2021 SCC 1")], _sources())
        assert report.checks[0].reason == "bare_citation"

    def test_unrelated_proposition_still_fails(self) -> None:
        check = _verify("taxation of non-resident shipping companies")
        assert check.verified is False
        assert check.reason == "proposition_not_supported"

    def test_unknown_citation_still_fails(self) -> None:
        check = _verify("patent illegality is a ground", citation="1999 XYZ 9")
        assert check.verified is False
        assert check.reason == "unknown_source"


class TestKnownLimitIsDocumented:
    """The gate stays order- and polarity-blind. Record it rather than imply otherwise."""

    def test_negation_is_still_not_detected(self) -> None:
        check = _verify("patent illegality is NOT a ground under Section 34")
        assert check.verified is True, (
            "this is a KNOWN LIMIT, asserted so it cannot be mistaken for a "
            "support check: the gate is bag-of-words and cannot separate "
            "'X is a ground' from 'X is not a ground'. Closing it needs an "
            "entailment or quoted-span mechanism, which is a separate change."
        )

    def test_docstring_does_not_overclaim(self) -> None:
        from caseops_api.services import citations

        doc = citations.verify_citations.__doc__ or ""
        assert "topical" in doc.lower() or "topicality" in doc.lower(), (
            "the docstring must describe what the gate does (topical overlap) "
            "rather than imply it verifies that the source supports the claim"
        )
