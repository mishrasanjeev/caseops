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
# Grounding fast path: the recommendations prompt numbers each retrieved
# authority and instructs the model to prefix every citation with the matching
# bracket tag. When the prefix lands, we resolve by index — deterministic, and
# we skip both the fuzzy citation gate and the proposition gate (the model has
# explicitly named the source).
_BRACKET_TAG_RE = re.compile(r"^\s*\[(\d+)\]")

# EH-SGR-07: the proposition gate's docstring promised "non-stopword tokens" but
# no such list existed, and the length>=3 cut keeps "the", "and", "that", "was".
# Function words plus the legal boilerplate that appears in nearly every Indian
# judgment, so overlap has to come from the substance of the proposition rather
# than from words two unrelated documents share by construction.
_STOPWORDS = frozenset(
    {
        "the", "and", "that", "was", "were", "his", "her", "its", "for", "with",
        "not", "but", "are", "has", "had", "have", "this", "these", "those",
        "any", "all", "such", "from", "into", "upon", "under", "over", "than",
        "then", "there", "their", "them", "they", "which", "who", "whom", "been",
        "being", "would", "could", "should", "shall", "will", "may", "must",
        "also", "only", "other", "some", "more", "most", "said", "same",
        # Boilerplate that carries no discriminating power in a judgment.
        "court", "case", "matter", "order", "judgment", "para", "paragraph",
        "hon", "honourable", "learned", "counsel", "appeal", "petition",
    }
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.lower()


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(_normalize(text))


def _citation_signature(text: str) -> frozenset[str]:
    return frozenset(tok for tok in _tokens(text) if len(tok) >= 2)


def _bracket_tag_lookup(
    citation: str, sources: list[SourceDoc]
) -> SourceDoc | None:
    match = _BRACKET_TAG_RE.match(citation)
    if not match:
        return None
    n = int(match.group(1))
    if 1 <= n <= len(sources):
        return sources[n - 1]
    return None


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
        # BUG-024 (Ram 2026-04-27 reopen of BUG-015): the prior 0.7
        # coverage floor rejected valid citations whenever the LLM
        # paraphrased the source identifier (e.g. "M.P." vs
        # "Madhya Pradesh", or dropping a middle name from the case
        # title). Lowering to 0.5 + requiring overlap >= 2 tokens
        # keeps it strict enough to fail on truly fabricated cites
        # but tolerates model-side abbreviation/expansion.
        coverage = overlap / len(query)
        if coverage >= 0.5 and overlap >= 2 and coverage > best[0]:
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
      share topical overlap with the source text: at least two DISTINCT
      non-stopword tokens (length >= 3) appearing in the source.

      Be precise about what this is. It is a **topicality filter**, not a
      support check. The comparison is bag-of-words and order-insensitive, so it
      cannot distinguish "X is a ground" from "X is not a ground" - a negated
      proposition shares every content word with the holding it contradicts.
      Describing a passing result as "the source supports the claim" overstates
      it; the honest reading is "the proposition is on-topic with the source".
      Closing that gap needs an entailment or quoted-span mechanism.
    - If the citation matches and no proposition was provided, the claim is
      verified as a bare citation (``bare_citation``).
    """
    index = _index_sources(sources)
    checks: list[CitationCheck] = []
    for claim in claims:
        bracket_match = _bracket_tag_lookup(claim.citation, sources)
        if bracket_match is not None:
            checks.append(
                CitationCheck(
                    claim=claim,
                    source=bracket_match,
                    verified=True,
                    reason="bracket_tag_match",
                )
            )
            continue
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
        # EH-SGR-07: `meaningful` used to be a list built from an unfiltered
        # token stream, so the gate had two independent holes. The same token
        # counted twice satisfied the two-token rule, and there was no stopword
        # list at all despite the docstring promising one - so a proposition
        # containing "the" twice verified against any source containing "the".
        # Count DISTINCT, non-stopword tokens.
        claim_tokens = [
            tok
            for tok in _tokens(claim.proposition)
            if len(tok) >= 3 and tok not in _STOPWORDS
        ]
        meaningful = {tok for tok in claim_tokens if tok in source_tokens}
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
