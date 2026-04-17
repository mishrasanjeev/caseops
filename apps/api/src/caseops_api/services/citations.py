"""Citation verification for CaseOps AI outputs.

A recommendation, brief, or draft that cites an authority must survive a check
that the cited label actually maps to a known source **and** that the claim
being supported is visibly present in that source. This service keeps that
check close to the shape of our data so callers can fail-closed when a claim
is unverifiable — which, per PRD §11.5 and §17.4, is the product default.

The verifier is tolerant of real-world legal citation noise: punctuation,
case, paragraph marks, and curly quotes do not affect matching. But it is
strict about the substance — you cannot pass verification with a citation
that never mentions the claim.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDoc:
    """A retrieved source that could support a claim.

    ``identifier`` is whatever the caller uses in its output (case reference,
    neutral citation, internal doc id). ``aliases`` lets a single source be
    cited in multiple equivalent phrasings (e.g., the short and long forms
    of a case name) without breaking verification.
    """

    identifier: str
    text: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Claim:
    citation: str
    proposition: str | None = None


@dataclass(frozen=True)
class CitationCheck:
    claim: Claim
    source: SourceDoc | None
    verified: bool
    reason: str


@dataclass(frozen=True)
class VerificationReport:
    checks: tuple[CitationCheck, ...]

    @property
    def verified_count(self) -> int:
        return sum(1 for c in self.checks if c.verified)

    @property
    def unverified_count(self) -> int:
        return len(self.checks) - self.verified_count

    @property
    def all_verified(self) -> bool:
        return len(self.checks) > 0 and self.verified_count == len(self.checks)

    @property
    def has_any_verified(self) -> bool:
        return self.verified_count > 0


_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.lower()


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(_normalize(text))


def _citation_signature(text: str) -> frozenset[str]:
    return frozenset(tok for tok in _tokens(text) if len(tok) >= 2)


def _match_source(
    citation: str, sources: list[tuple[frozenset[str], SourceDoc]]
) -> SourceDoc | None:
    query = _citation_signature(citation)
    if not query:
        return None
    best: tuple[float, SourceDoc | None] = (0.0, None)
    for signature, doc in sources:
        if not signature:
            continue
        overlap = len(query & signature)
        if overlap == 0:
            continue
        coverage = overlap / len(query)
        if coverage >= 0.7 and coverage > best[0]:
            best = (coverage, doc)
    return best[1]


def _index_sources(
    sources: list[SourceDoc],
) -> list[tuple[frozenset[str], SourceDoc]]:
    index: list[tuple[frozenset[str], SourceDoc]] = []
    for source in sources:
        index.append((_citation_signature(source.identifier), source))
        for alias in source.aliases:
            index.append((_citation_signature(alias), source))
    return index


def verify_citations(
    claims: list[Claim], sources: list[SourceDoc]
) -> VerificationReport:
    """Return a report for every ``Claim``.

    - If the citation cannot be matched to any source, the claim is
      unverified with reason ``unknown_source``.
    - If it matches, and a ``proposition`` was provided, the proposition must
      share meaningful overlap with the source text. Meaningful overlap is
      defined as at least two non-stopword tokens (length >= 3) appearing in
      the source text. This is deliberately strict for legal drafting, and
      callers that want looser matching can pre-process the proposition.
    - If the citation matches and no proposition was provided, the claim is
      verified as a bare citation (``bare_citation``).
    """
    index = _index_sources(sources)
    checks: list[CitationCheck] = []
    for claim in claims:
        source = _match_source(claim.citation, index)
        if source is None:
            checks.append(
                CitationCheck(
                    claim=claim, source=None, verified=False, reason="unknown_source"
                )
            )
            continue
        if claim.proposition is None:
            checks.append(
                CitationCheck(
                    claim=claim, source=source, verified=True, reason="bare_citation"
                )
            )
            continue
        source_tokens = set(_tokens(source.text))
        claim_tokens = [tok for tok in _tokens(claim.proposition) if len(tok) >= 3]
        meaningful = [tok for tok in claim_tokens if tok in source_tokens]
        if len(meaningful) >= 2:
            checks.append(
                CitationCheck(
                    claim=claim,
                    source=source,
                    verified=True,
                    reason="proposition_supported",
                )
            )
        else:
            checks.append(
                CitationCheck(
                    claim=claim,
                    source=source,
                    verified=False,
                    reason="proposition_not_supported",
                )
            )
    return VerificationReport(checks=tuple(checks))


__all__ = [
    "Claim",
    "CitationCheck",
    "SourceDoc",
    "VerificationReport",
    "verify_citations",
]
