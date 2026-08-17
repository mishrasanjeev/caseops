"""Measure what a mandatory proposition gate would do to real recommendations.

EH-SGR-07 cannot be flipped blind. Today `services/citations.py` short-circuits on
a bracket tag, so "verified" in production means "the model emitted an in-range
list index". Making the proposition gate mandatory is the right end state, but
three of the four callers cannot satisfy it as they stand, and
`recommendations.py` raises HTTP 422 for the WHOLE generation when zero citations
verify. Tightening blind could therefore start refusing correct work at scale.

This script answers the only question that decides whether the flip can ship:

    of the recommendation options already persisted, how many would still have at
    least one verified citation if the bracket short-circuit were removed?

It is READ ONLY. It opens a session, reads `recommendation_options`, re-runs the
verification logic in both modes, and prints a comparison. It writes nothing,
calls no provider, and creates no tenant.

Usage:
    PYTHONPATH=apps/api/src python scripts/replay_citation_gate.py [--limit N]

Caveat that must travel with the number: the proposition available to replay is
the option-level rationale, which is what production passes today. An option
citing three authorities has citations 2 and 3 judged against text written about
citation 1. That is a systematic false-negative built into the data shape, so the
measured yield is a LOWER BOUND on what a per-citation proposition would achieve.

Second caveat, and the sharper one. `supporting_citations_json` stores what
`_filter_and_verify_options` already canonicalised -- `check.source.identifier`,
not the model's raw string -- so no `[N]` prefix survives into the table this
script reads. The bracket short-circuit therefore cannot be *observed* here even
though it is faithfully reconstructed below: rows that were verified by bracket
alone were rewritten as canonical identifiers before being persisted, and rows
whose citations never verified were dropped from the list entirely. What this
replay measures is the surviving population, which is already the post-filter
one. Read `would NEWLY 422` as a floor, not an estimate. Sizing the bracket-only
population needs the raw model output, which is not persisted.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

from sqlalchemy import select

from caseops_api.db.models import AuthorityDocument, RecommendationOption
from caseops_api.db.session import get_session_factory
from caseops_api.services.citations import (
    Claim,
    SourceDoc,
    _bracket_tag_lookup,
    verify_citations,
)


@dataclass
class Tally:
    options: int = 0
    options_with_citations: int = 0
    verified_today: int = 0
    verified_if_mandatory: int = 0
    would_newly_fail: int = 0
    citations_seen: int = 0
    citations_verified_if_mandatory: int = 0


def _sources_for(session, citations: list[str]) -> list[SourceDoc]:
    """Resolve cited identifiers to their stored text, as the live path does."""
    docs: list[SourceDoc] = []
    for citation in citations:
        row = session.scalar(
            select(AuthorityDocument)
            .where(AuthorityDocument.case_reference == citation)
            .limit(1)
        ) or session.scalar(
            select(AuthorityDocument)
            .where(AuthorityDocument.neutral_citation == citation)
            .limit(1)
        )
        if row is None:
            continue
        text = " ".join(
            part for part in (row.title, getattr(row, "summary", None)) if part
        )
        docs.append(SourceDoc(identifier=citation, text=text))
    return docs


def _verified_count(claims: list[Claim], sources: list[SourceDoc], *, mandatory: bool) -> int:
    """Count verified citations under the old gate (``mandatory=False``) or the new one.

    The "before" arm must NOT simply call ``verify_citations`` and read
    ``verified_count``. This change removed the bracket short-circuit from that
    function, so both arms would run identical logic, differ only by
    ``bare_citation``, and the replay could never report a loss attributable to
    the flip -- the one number the script exists to produce. The pre-change gate
    treated a resolvable bracket tag as a verdict in itself, skipping the
    proposition gate, so that behaviour is reconstructed here explicitly.
    """
    report = verify_citations(claims, sources)
    if mandatory:
        # New gate: only genuine proposition support counts.
        return sum(
            1
            for check in report.checks
            if check.verified and check.reason == "proposition_supported"
        )
    return sum(
        1
        for check in report.checks
        if check.verified
        or _bracket_tag_lookup(check.claim.citation, sources) is not None
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()

    tally = Tally()
    with get_session_factory()() as session:
        options = list(
            session.scalars(select(RecommendationOption).limit(args.limit)).all()
        )
        for option in options:
            tally.options += 1
            # Stored as a JSON-encoded Text column, not a list.
            raw = getattr(option, "supporting_citations_json", None) or "[]"
            try:
                citations = [str(c) for c in json.loads(raw)]
            except (ValueError, TypeError):
                citations = []
            if not citations:
                continue
            tally.options_with_citations += 1
            tally.citations_seen += len(citations)

            rationale = (getattr(option, "rationale", None) or "")[:400]
            sources = _sources_for(session, citations)
            claims = [Claim(citation=c, proposition=rationale or None) for c in citations]

            today = _verified_count(claims, sources, mandatory=False)
            strict = _verified_count(claims, sources, mandatory=True)
            tally.citations_verified_if_mandatory += strict
            if today > 0:
                tally.verified_today += 1
            if strict > 0:
                tally.verified_if_mandatory += 1
            elif today > 0:
                tally.would_newly_fail += 1

    print("=== citation gate replay (read only) ===")
    print(f"recommendation options scanned      : {tally.options}")
    print(f"  with at least one citation        : {tally.options_with_citations}")
    print(f"  verified TODAY (bracket allowed)  : {tally.verified_today}")
    print(f"  verified if gate MANDATORY        : {tally.verified_if_mandatory}")
    print(f"  would NEWLY 422                   : {tally.would_newly_fail}")
    print(f"citations seen                      : {tally.citations_seen}")
    print(f"  verified if gate MANDATORY        : {tally.citations_verified_if_mandatory}")
    if tally.verified_today:
        retained = 100.0 * tally.verified_if_mandatory / tally.verified_today
        print(f"option-level retention              : {retained:.1f}%")
    print()
    print(
        "FLOOR, not an estimate: stored citations are post-filter canonical\n"
        "identifiers, so citations that only ever verified by bracket tag were\n"
        "either rewritten or dropped before reaching this table. The bracket-only\n"
        "population cannot be sized from persisted data."
    )
    if tally.options_with_citations == 0:
        print(
            "\nNO DATA. No persisted option carries citations, so the flip cannot be "
            "measured from this environment. Treat EH-SGR-07 as Inconclusive and "
            "run this against an environment that has real recommendation history."
        )
    print(
        "\nCaveat: the proposition replayed is the option-level rationale, which is "
        "what production passes today. An option citing several authorities judges "
        "citations 2..n against text written about citation 1, so this retention "
        "figure is a LOWER BOUND."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
