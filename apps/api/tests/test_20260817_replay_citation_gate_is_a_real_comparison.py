"""The blast-radius replay must actually compare two different gates.

`scripts/replay_citation_gate.py` exists to answer one question before EH-SGR-07
is flipped: how many persisted recommendation options would lose their last
verified citation if a bracket tag stopped counting as a verdict?

Its "before" arm originally called `verify_citations` and read
`report.verified_count`. But the same change removed the bracket short-circuit
from that function, so both arms ran identical logic and differed only by
`bare_citation`. A measurement whose two sides are computed the same way cannot
report a loss, so the script would have reported a reassuring zero no matter what
the flip actually cost -- the most dangerous possible output for a script whose
whole purpose is to authorise a risky change.

These tests assert the comparison is non-degenerate: a citation that verifies
ONLY by bracket tag must count under the old gate and not under the new one.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from caseops_api.services.citations import Claim, SourceDoc

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "replay_citation_gate.py"
SPEC = importlib.util.spec_from_file_location("replay_citation_gate", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
replay_citation_gate = importlib.util.module_from_spec(SPEC)
# Registered before exec: the script defines a @dataclass, and dataclasses
# resolves annotations through sys.modules[cls.__module__].
sys.modules["replay_citation_gate"] = replay_citation_gate
SPEC.loader.exec_module(replay_citation_gate)


# A source whose text shares no substantive token with the proposition below, so
# the proposition gate cannot pass it. The only thing that can verify this claim
# is the bracket tag.
_SOURCE = SourceDoc(
    identifier="State of Punjab v. Davinder Singh",
    text="Reservation in promotion and the creamy layer within scheduled castes.",
)
_BRACKET_ONLY = Claim(
    citation="[1] State of Punjab v. Davinder Singh",
    proposition="Arbitration clauses survive novation of the underlying contract.",
)


def test_bracket_only_citation_counts_under_the_old_gate() -> None:
    old = replay_citation_gate._verified_count(
        [_BRACKET_ONLY], [_SOURCE], mandatory=False
    )
    assert old == 1, (
        "the pre-change gate treated a resolvable bracket tag as a verdict; the "
        "replay's 'before' arm has to reproduce that or it measures nothing"
    )


def test_bracket_only_citation_does_not_count_under_the_new_gate() -> None:
    new = replay_citation_gate._verified_count(
        [_BRACKET_ONLY], [_SOURCE], mandatory=True
    )
    assert new == 0, "a bracket tag resolves a source; it is not proposition support"


def test_the_two_arms_are_not_the_same_measurement() -> None:
    # The regression guard proper. If someone re-points the "before" arm at
    # verify_citations' own verified_count, these collapse to the same number and
    # the script silently returns to reporting zero loss forever.
    old = replay_citation_gate._verified_count(
        [_BRACKET_ONLY], [_SOURCE], mandatory=False
    )
    new = replay_citation_gate._verified_count(
        [_BRACKET_ONLY], [_SOURCE], mandatory=True
    )
    assert old > new, "before and after must be able to differ, or the replay is vacuous"


def test_a_genuinely_supported_citation_counts_under_both_gates() -> None:
    # The flip must not be measured as costing options it does not cost.
    supported = Claim(
        citation="[1] State of Punjab v. Davinder Singh",
        proposition="The creamy layer principle applies to scheduled castes in promotion.",
    )

    assert replay_citation_gate._verified_count([supported], [_SOURCE], mandatory=False) == 1
    assert replay_citation_gate._verified_count([supported], [_SOURCE], mandatory=True) == 1
