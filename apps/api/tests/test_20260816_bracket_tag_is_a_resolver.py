"""EH-SGR-07 part 2: the bracket tag resolves a source; it is not a verdict.

`_bracket_tag_lookup` used to short-circuit straight to `verified=True`, skipping
both the fuzzy match and the proposition gate. Because both production prompts
*hard-require* the tag - "The bracket tag is required, it is how the verifier
resolves the citation" - that short-circuit was the only path production ever
took. "Citation verified" meant "the model emitted an in-range list index". A
citation of the form `[1] <anything>` passed unconditionally.

The tag now does what its name says: it resolves which retrieved source is being
cited, and that source then goes through the same gate as any other match.

Two deliberate non-changes:

- A claim with no proposition is still `bare_citation`. That is drafting's case,
  where the guarantee is "we hold this authority", not "this authority supports
  the sentence". Forcing a proposition there would mean feeding a whole draft
  body to a bag-of-words check, which would pass trivially and mean nothing.
- The gate remains a topicality filter. See
  test_20260816_proposition_gate_hardening.py.
"""

from __future__ import annotations

from caseops_api.services.citations import Claim, SourceDoc, verify_citations

_HOLDING = (
    "The Supreme Court held that patent illegality is a ground for setting aside "
    "an arbitral award under Section 34 of the Arbitration and Conciliation Act."
)
_UNRELATED = (
    "The Tribunal considered the valuation of imported machinery for customs duty "
    "and remanded the classification dispute."
)


def _sources() -> list[SourceDoc]:
    return [
        SourceDoc(identifier="Ssangyong v. NHAI (2019)", text=_HOLDING),
        SourceDoc(identifier="Customs Ref (2020)", text=_UNRELATED),
    ]


def _check(citation: str, proposition: str | None):
    report = verify_citations(
        [Claim(citation=citation, proposition=proposition)], _sources()
    )
    return report.checks[0]


class TestTagNoLongerBypassesTheGate:
    def test_tagged_citation_with_an_ungrounded_proposition_fails(self) -> None:
        check = _check("[1] paraphrased title that does not match", "customs duty valuation")
        assert check.verified is False, (
            "a bracket tag used to grant verification unconditionally; the "
            "proposition must now be checked against the resolved source"
        )
        assert check.reason == "proposition_not_supported"

    def test_tag_pointing_at_the_wrong_source_fails(self) -> None:
        # [2] indexes the customs authority and the citation text is too short
        # to match anything, so nothing grounds the s.34 proposition.
        check = _check("[2] Ssang", "patent illegality under Section 34")
        assert check.verified is False

    def test_out_of_range_tag_is_not_a_source(self) -> None:
        check = _check("[9] something", "patent illegality under Section 34")
        assert check.verified is False
        assert check.reason == "unknown_source"


class TestTagStillResolvesTheRightSource:
    def test_tagged_citation_with_a_grounded_proposition_verifies(self) -> None:
        check = _check("[1] Ssangyong v. NHAI", "patent illegality under Section 34")
        assert check.verified is True
        assert check.reason == "proposition_supported"
        assert check.source is not None
        assert check.source.identifier == "Ssangyong v. NHAI (2019)"

    def test_the_tag_selects_by_index_when_the_text_is_unmatchable(self) -> None:
        """The tag's actual purpose: a title paraphrased past recognition."""
        check = _check("[2] some paraphrase", "customs duty valuation of machinery")
        assert check.verified is True
        assert check.source is not None
        assert check.source.identifier == "Customs Ref (2020)"

class TestTagWinsOverAnAmbiguousName:
    """Tag before text, and the asymmetry that decides it.

    An earlier draft of this change resolved text-first, on the reasoning that a
    correctly-named but miscounted citation should not be checked against
    another judgment. That is the wrong trade, because the two failures are not
    symmetric: a miscounted tag REJECTS (the proposition fails against the wrong
    source), while a name collision can PASS against a sibling judgment that
    shares subject matter - and the caller then republishes the claim under the
    wrong case name.
    """

    _HC = SourceDoc(
        identifier="State of Punjab v. Rakesh Kumar (2018)",
        text=(
            "The High Court quashed the proceeding as an abuse of process, "
            "holding that the allegations did not disclose a cognizable offence."
        ),
    )
    _SC = SourceDoc(
        identifier="State of Punjab v. Rakesh Kumar (2021)",
        text=(
            "The Supreme Court set aside the quashing and held that the "
            "allegations disclose a cognizable offence and the proceeding "
            "must continue."
        ),
    )

    def test_same_party_names_resolve_by_tag_not_by_text(self) -> None:
        """The regression this replaces.

        Both identifiers tokenise identically once the year is dropped, so the
        text matcher scores 1.0 coverage on each and the tie goes to whichever
        was retrieved first. Only the tag distinguishes them.
        """
        report = verify_citations(
            [
                Claim(
                    citation="[2] State of Punjab v. Rakesh Kumar",
                    proposition=(
                        "the allegations disclose a cognizable offence and the "
                        "proceeding must continue"
                    ),
                )
            ],
            [self._HC, self._SC],
        )
        check = report.checks[0]
        assert check.source is not None
        assert check.source.identifier == "State of Punjab v. Rakesh Kumar (2021)", (
            "resolved to the overturned judgment; the tag is the only "
            "disambiguator when sibling judgments share party names"
        )
        assert check.verified is True
        assert check.reason == "proposition_supported"

    def test_the_overturned_sibling_is_not_substituted_as_the_source(self) -> None:
        """Resolution is the contract here, not the verdict.

        Under text-first this resolved to [1], and the caller then republishes
        the claim under ``source.identifier`` - so the option would have carried
        the 2018 citation, the judgment that was set aside.
        """
        report = verify_citations(
            [
                Claim(
                    citation="[2] State of Punjab v. Rakesh Kumar",
                    proposition="the allegations did not disclose a cognizable offence",
                )
            ],
            [self._HC, self._SC],
        )
        check = report.checks[0]
        assert check.source is not None
        assert check.source.identifier == "State of Punjab v. Rakesh Kumar (2021)"

    def test_a_miscounted_tag_mis_attributes_and_still_verifies(self) -> None:
        """The cost of tag-first, measured rather than assumed.

        An earlier version of this test asserted ``verified is False`` here, on
        the theory that a wrongly-resolved source would reject the proposition.
        It does not. Sibling judgments share nearly all their vocabulary, and
        the gate is polarity-blind, so the proposition clears against the very
        judgment that was overturned.

        This is pinned as a KNOWN LIMIT, not as desired behaviour. If an
        entailment or quoted-span mechanism ever lands, this test should start
        failing - that is the signal the limit is closed, and the assertion
        should then be inverted rather than deleted.
        """
        report = verify_citations(
            [
                Claim(
                    citation="[1] State of Punjab v. Rakesh Kumar (2021)",
                    proposition=(
                        "the allegations disclose a cognizable offence and the "
                        "proceeding must continue"
                    ),
                )
            ],
            [self._HC, self._SC],
        )
        check = report.checks[0]
        assert check.source is not None
        assert check.source.identifier == "State of Punjab v. Rakesh Kumar (2018)"
        assert check.verified is True, (
            "documented limit: bag-of-words cannot separate a holding from the "
            "holding that reversed it. Neither resolution order fixes this."
        )


class TestTextlessSourceIsNamedHonestly:
    """The flip makes the gate load-bearing, so misattributed failures matter.

    A retrieved source with no title/summary/snippet cannot be checked. That is a
    gap on our side, not an ungrounded claim, and reporting it as
    `proposition_not_supported` would hide a retrieval regression behind a wall
    of apparently-fabricated citations.
    """

    def test_empty_source_text_fails_closed_under_its_own_reason(self) -> None:
        report = verify_citations(
            [Claim(citation="[1] Ssangyong", proposition="patent illegality")],
            [SourceDoc(identifier="Ssangyong v. NHAI (2019)", text="")],
        )
        check = report.checks[0]
        assert check.verified is False
        assert check.reason == "source_text_unavailable"
        assert check.source is not None

    def test_punctuation_only_source_text_counts_as_unavailable(self) -> None:
        report = verify_citations(
            [Claim(citation="[1] Ssangyong", proposition="patent illegality")],
            [SourceDoc(identifier="Ssangyong v. NHAI (2019)", text="—  ...  —")],
        )
        assert report.checks[0].reason == "source_text_unavailable"

    def test_a_textless_source_does_not_block_a_bare_citation(self) -> None:
        """Drafting cites by existence; it never needed the source text."""
        report = verify_citations(
            [Claim(citation="[1] Ssangyong")],
            [SourceDoc(identifier="Ssangyong v. NHAI (2019)", text="")],
        )
        assert report.checks[0].verified is True
        assert report.checks[0].reason == "bare_citation"


class TestBareCitationIsUnchanged:
    """Drafting's contract: 'we hold this authority', not 'it supports this'."""

    def test_no_proposition_still_verifies_as_bare(self) -> None:
        check = _check("Ssangyong v. NHAI (2019)", None)
        assert check.verified is True
        assert check.reason == "bare_citation"

    def test_tagged_citation_without_a_proposition_is_bare(self) -> None:
        check = _check("[1] Ssangyong", None)
        assert check.verified is True
        assert check.reason == "bare_citation"
        assert check.source is not None
        assert check.source.identifier == "Ssangyong v. NHAI (2019)"


class TestNoCallerPassesAPlaceholderProposition:
    def test_litigation_strategy_builds_a_real_proposition(self) -> None:
        from caseops_api.services.litigation_strategy import item_proposition

        assert item_proposition({"label": "Limitation", "description": "60 days to file SLP"}) == (
            "60 days to file SLP Limitation"
        )
        assert item_proposition({}) is None
        assert item_proposition("File SLP within 60 days") == "File SLP within 60 days"

    def test_the_placeholder_constant_is_gone(self) -> None:
        import inspect

        from caseops_api.services import litigation_strategy

        source = inspect.getsource(litigation_strategy)
        # It may survive in a comment explaining the defect, but never as a value.
        assert 'proposition="strategy item citation"' not in source
