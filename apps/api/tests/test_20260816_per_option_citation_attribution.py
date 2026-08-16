"""EH-SGR-07 part 3: a failing option must not inherit another option's verdict.

Both `recommendations._filter_and_verify_options` and
`litigation_strategy._verify_routes` build one `Claim` per (option, citation)
pair, each carrying that option's own rationale as the proposition — correct.
Both then collapsed the verdicts through a flat
``canonical_for[check.claim.citation] -> identifier`` map, which throws that
attribution away.

While the bracket-tag fast path was in place this was harmless: every claim for
a given citation string verified, so every option read back the same answer.
Once the proposition is actually checked, two options citing the *same* string
get *different* verdicts, and the flat map lets whichever option verified first
write a key that a failing option then reads back.

That matters most in `litigation_strategy`, where it silently defeats the
`rejected_primary_route_uncited` refusal — the guard whose entire purpose is
that "a primary route with zero verified citations cannot ride on an
alternative's authority". The bypass this change removed would have re-entered
one layer up, through the caller.
"""

from __future__ import annotations

import pytest

from caseops_api.services.citations import Claim, SourceDoc, verify_citations

_ARBITRATION = (
    "The Supreme Court held that patent illegality is a ground for setting "
    "aside an arbitral award under Section 34 of the Arbitration and "
    "Conciliation Act."
)


def _sources() -> list[SourceDoc]:
    return [SourceDoc(identifier="Ssangyong Engg v. NHAI (2019)", text=_ARBITRATION)]


def _verdicts(propositions: list[str], citation: str) -> list[bool]:
    """Verify one claim per proposition, all citing the same raw string."""
    claims = [Claim(citation=citation, proposition=p) for p in propositions]
    report = verify_citations(claims, _sources())
    return [c.verified for c in report.checks]


class TestTheVerifierItselfDistinguishesThem:
    """Precondition: the two claims really do get different verdicts."""

    def test_same_citation_different_propositions_diverge(self) -> None:
        grounded = "patent illegality under Section 34 of the Arbitration Act"
        ungrounded = "customs valuation of imported machinery and tariff heading"
        assert _verdicts([grounded, ungrounded], "[1] Ssangyong") == [True, False]

    def test_order_does_not_change_the_verdicts(self) -> None:
        grounded = "patent illegality under Section 34 of the Arbitration Act"
        ungrounded = "customs valuation of imported machinery and tariff heading"
        assert _verdicts([ungrounded, grounded], "[1] Ssangyong") == [False, True]


class TestCollapseKeepsAttribution:
    """The regression: reproduce the flat-map collapse and prove it is gone.

    This mirrors the exact shape of the collapse step in both services rather
    than importing private helpers, so it stays honest if either is refactored:
    the old code is reproduced here and shown to be wrong, and the new rule is
    asserted against the same inputs.
    """

    CITATION = "[1] Ssangyong Engg v. NHAI (2019)"
    GROUNDED = "patent illegality under Section 34 of the Arbitration Act"
    UNGROUNDED = "customs valuation of imported machinery and tariff heading"

    def _report_and_owners(self, propositions: list[str]):
        claims = [Claim(citation=self.CITATION, proposition=p) for p in propositions]
        report = verify_citations(claims, _sources())
        return report, list(range(len(propositions)))

    def test_the_old_flat_map_leaks_and_is_not_what_we_do(self) -> None:
        """Documents the defect. If this ever stops leaking, delete this test."""
        report, _ = self._report_and_owners([self.GROUNDED, self.UNGROUNDED])
        canonical_for: dict[str, str] = {}
        for check in report.checks:
            if check.verified and check.source is not None:
                canonical_for[check.claim.citation] = check.source.identifier
        # Option 1's proposition failed, yet the flat map still answers for it.
        assert canonical_for.get(self.CITATION) == "Ssangyong Engg v. NHAI (2019)"

    @pytest.mark.parametrize(
        "propositions,expected",
        [
            ([GROUNDED, UNGROUNDED], {0: ["Ssangyong Engg v. NHAI (2019)"], 1: []}),
            ([UNGROUNDED, GROUNDED], {0: [], 1: ["Ssangyong Engg v. NHAI (2019)"]}),
            ([UNGROUNDED, UNGROUNDED], {0: [], 1: []}),
            (
                [GROUNDED, GROUNDED],
                {
                    0: ["Ssangyong Engg v. NHAI (2019)"],
                    1: ["Ssangyong Engg v. NHAI (2019)"],
                },
            ),
        ],
    )
    def test_zip_attribution_credits_only_the_option_that_earned_it(
        self, propositions: list[str], expected: dict[int, list[str]]
    ) -> None:
        report, owners = self._report_and_owners(propositions)
        per_option: dict[int, list[str]] = {i: [] for i in range(len(propositions))}
        seen: dict[int, set[str]] = {i: set() for i in range(len(propositions))}
        for check, idx in zip(report.checks, owners, strict=True):
            if not check.verified or check.source is None:
                continue
            canonical = check.source.identifier
            if canonical in seen[idx]:
                continue
            per_option[idx].append(canonical)
            seen[idx].add(canonical)
        assert per_option == expected


class TestAnItemWithNoPropositionCannotVerify:
    """The bypass, reopened through a different door.

    `item_proposition` returns None exactly when the model emitted no
    description, rationale, label, stage_label, mitigation or action. That is
    model-controlled input. Passing None through to the verifier lands on
    `bare_citation` - verified-by-existence, which is right for drafting and
    wrong for a strategy item - so a model could clear the gate on any item
    simply by omitting its prose, exactly as it previously could by emitting a
    bracket tag.
    """

    def test_item_with_citations_but_no_prose_verifies_nothing(self) -> None:
        from caseops_api.services.litigation_strategy import (
            RetrievedAuthority,
            _verify_item_citations,
            item_proposition,
        )

        retrieved = [
            RetrievedAuthority(
                identifier="Ssangyong Engg v. NHAI (2019)", text=_ARBITRATION
            )
        ]
        raw = {"supporting_citations": ["[1] anything at all"]}
        assert item_proposition(raw) is None
        assert (
            _verify_item_citations(
                raw["supporting_citations"], retrieved, item_proposition(raw)
            )
            == []
        )

    def test_the_same_item_verifies_once_it_asserts_something_grounded(self) -> None:
        from caseops_api.services.litigation_strategy import (
            RetrievedAuthority,
            _verify_item_citations,
            item_proposition,
        )

        retrieved = [
            RetrievedAuthority(
                identifier="Ssangyong Engg v. NHAI (2019)", text=_ARBITRATION
            )
        ]
        raw = {
            "supporting_citations": ["[1] Ssangyong"],
            "description": "patent illegality is a ground under Section 34",
        }
        assert _verify_item_citations(
            raw["supporting_citations"], retrieved, item_proposition(raw)
        ) == ["Ssangyong Engg v. NHAI (2019)"]

    def test_the_parameter_has_no_default(self) -> None:
        """A default is how a future caller silently opts out of the gate."""
        import inspect

        from caseops_api.services.litigation_strategy import _verify_item_citations

        param = inspect.signature(_verify_item_citations).parameters["proposition"]
        assert param.default is inspect.Parameter.empty


class TestServicesUseAttributedCollapse:
    """Pin the services themselves, so this cannot silently regress."""

    @pytest.mark.parametrize(
        "module,func",
        [
            ("caseops_api.services.recommendations", "_filter_and_verify_options"),
            ("caseops_api.services.litigation_strategy", "_verify_routes"),
        ],
    )
    def test_cross_option_collapse_is_attributed(self, module: str, func: str) -> None:
        """Scope matters: only the functions that verify MULTIPLE options at
        once can leak. ``litigation_strategy._verify_item_citations`` also uses a
        flat map, but every claim it builds carries the same single item's
        proposition, so duplicate citation strings cannot diverge. Asserting
        module-wide would flag that benign case and the explanatory comments."""
        import importlib
        import inspect

        raw = inspect.getsource(getattr(importlib.import_module(module), func))
        # Check executable lines only. The comment above the fix names the old
        # flat-map expression on purpose, to explain why it was wrong.
        source = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("#")
        )
        assert "canonical_for" not in source, (
            f"{module}.{func} collapses verdicts through a flat citation-string "
            "map; an option whose proposition failed will inherit another's"
        )
        assert "zip(report.checks, claim_option, strict=True)" in source, (
            f"{module}.{func} must attribute each verdict to the option that "
            "emitted it"
        )
