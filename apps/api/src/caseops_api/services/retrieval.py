from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "with",
}
SEMANTIC_GROUPS = [
    {"appeal", "challenge", "petition", "revision", "writ"},
    {"case", "claim", "lawsuit", "litigation", "matter", "suit"},
    {"adjournment", "appearance", "hearing", "listing", "mention", "oral"},
    {"breach", "confidentiality", "nda", "non-disclosure", "privacy", "security"},
    {"agreement", "arrangement", "contract", "msa"},
    {"amount", "billing", "fees", "invoice", "payment", "pricing"},
    {"compliance", "inspection", "investigation", "notice", "regulator"},
    {"counterparty", "opponent", "opposing", "respondent"},
    {"damages", "indemnify", "indemnity", "liability"},
    {"court", "forum", "judge", "tribunal"},
]
SEMANTIC_LOOKUP = {
    term: sorted(group - {term}) for group in SEMANTIC_GROUPS for term in group
}


@dataclass(slots=True)
class RetrievalCandidate:
    attachment_id: str
    attachment_name: str
    content: str
    # Optional per-chunk embedding. When present, and when the caller passes
    # a query vector, the hybrid scorer blends cosine similarity with the
    # existing lexical score.
    embedding: list[float] | None = None


@dataclass(slots=True)
class RetrievalResult:
    attachment_id: str
    attachment_name: str
    content: str
    snippet: str
    score: int
    matched_terms: list[str]


# Hybrid scoring weight: alpha is the weight on the lexical score. A value
# of 0.4 means vector similarity is the bigger signal when available, which
# matches how legal retrieval usually works (semantic matches carry the
# authority, keyword hits prove the link).
HYBRID_LEXICAL_WEIGHT = 0.4
HYBRID_VECTOR_WEIGHT = 1.0 - HYBRID_LEXICAL_WEIGHT


@dataclass(slots=True)
class _PreparedCandidate:
    candidate: RetrievalCandidate
    raw_tokens: list[str]
    raw_token_counts: Counter[str]
    stems: list[str]
    stem_counts: Counter[str]
    unique_stems: set[str]
    normalized_text: str
    trigrams: set[str]
    attachment_tokens: set[str]


def rank_candidates(
    *,
    query: str,
    candidates: list[RetrievalCandidate],
    limit: int,
    query_vector: list[float] | None = None,
) -> list[RetrievalResult]:
    normalized_query = _normalize_text(query)
    query_tokens = [token for token in _tokenize(normalized_query) if token not in STOPWORDS]
    if not query_tokens or not candidates:
        return []

    expanded_terms = _expand_terms(query_tokens)
    query_stems = {_stem(token) for token in query_tokens}
    expanded_stems = {_stem(token) for token in expanded_terms}
    query_trigrams = _char_trigrams(normalized_query)
    prepared_candidates = [_prepare_candidate(candidate) for candidate in candidates]
    document_count = len(prepared_candidates)

    document_frequency: Counter[str] = Counter()
    for candidate in prepared_candidates:
        for stem in candidate.unique_stems:
            document_frequency[stem] += 1

    results: list[RetrievalResult] = []
    for candidate in prepared_candidates:
        exact_hits = sorted(
            {token for token in query_tokens if token in candidate.raw_token_counts}
        )
        semantic_hits = sorted(
            {
                term
                for term in expanded_terms
                if _stem(term) in candidate.unique_stems or term in candidate.attachment_tokens
            }
        )
        if not exact_hits and not semantic_hits:
            continue

        exact_overlap = sum(candidate.raw_token_counts[token] for token in exact_hits)
        semantic_overlap = sum(
            candidate.stem_counts[_stem(term)]
            for term in semantic_hits
            if _stem(term) in candidate.stem_counts
        )
        idf_score = sum(
            math.log((document_count + 1) / (document_frequency[stem] + 1)) + 1
            for stem in expanded_stems
            if stem in candidate.unique_stems
        )
        attachment_bonus = sum(
            1 for token in expanded_terms if token in candidate.attachment_tokens
        )
        phrase_bonus = (
            3 if normalized_query and normalized_query in candidate.normalized_text else 0
        )
        coverage = len(query_stems & candidate.unique_stems) / max(len(query_stems), 1)
        trigram_similarity = _dice_similarity(query_trigrams, candidate.trigrams)

        lexical_score = (
            (idf_score * 24)
            + (exact_overlap * 22)
            + (semantic_overlap * 11)
            + (attachment_bonus * 8)
            + (phrase_bonus * 12)
            + (coverage * 30)
            + (trigram_similarity * 18)
        )

        # Hybrid blend: cosine similarity is mapped into the same rough scale
        # as the lexical score (max ~250) so the blend is meaningful.
        vector_component = 0.0
        if query_vector is not None and candidate.candidate.embedding is not None:
            vector_component = _cosine(query_vector, candidate.candidate.embedding) * 240

        if vector_component > 0:
            score = (HYBRID_LEXICAL_WEIGHT * lexical_score) + (
                HYBRID_VECTOR_WEIGHT * vector_component
            )
        else:
            score = lexical_score

        if score <= 0:
            continue

        matched_terms = list(dict.fromkeys([*exact_hits, *semantic_hits]))
        results.append(
            RetrievalResult(
                attachment_id=candidate.candidate.attachment_id,
                attachment_name=candidate.candidate.attachment_name,
                content=candidate.candidate.content,
                snippet=_best_snippet(
                    candidate.candidate.content,
                    query_tokens=query_tokens,
                    semantic_terms=semantic_hits,
                ),
                score=max(int(round(score)), 1),
                matched_terms=matched_terms[:8],
            )
        )

    results.sort(key=lambda item: item.score, reverse=True)
    return results[:limit]


def _prepare_candidate(candidate: RetrievalCandidate) -> _PreparedCandidate:
    normalized_text = _normalize_text(candidate.content)
    raw_tokens = [token for token in _tokenize(normalized_text) if token not in STOPWORDS]
    stems = [_stem(token) for token in raw_tokens]
    attachment_tokens = {
        token
        for token in _tokenize(_normalize_text(candidate.attachment_name))
        if token not in STOPWORDS
    }
    return _PreparedCandidate(
        candidate=candidate,
        raw_tokens=raw_tokens,
        raw_token_counts=Counter(raw_tokens),
        stems=stems,
        stem_counts=Counter(stems),
        unique_stems=set(stems),
        normalized_text=normalized_text,
        trigrams=_char_trigrams(normalized_text),
        attachment_tokens=attachment_tokens,
    )


def _tokenize(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(value.lower())


def _normalize_text(value: str) -> str:
    return " ".join(_tokenize(value))


def _stem(token: str) -> str:
    for suffix in (
        "ations",
        "ation",
        "ments",
        "ment",
        "edly",
        "iness",
        "ities",
        "fully",
        "less",
        "ness",
        "tion",
        "sion",
        "ings",
        "ized",
        "ises",
        "ises",
        "ance",
        "ence",
        "ment",
        "ing",
        "edly",
        "ed",
        "ies",
        "es",
        "s",
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            if suffix == "ies":
                return token[:-3] + "y"
            return token[: -len(suffix)]
    return token


def _expand_terms(query_tokens: list[str]) -> list[str]:
    expanded = set(query_tokens)
    for token in query_tokens:
        expanded.update(SEMANTIC_LOOKUP.get(token, []))
    return sorted(expanded)


def _char_trigrams(value: str) -> set[str]:
    compact = value.replace(" ", "")
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[index : index + 3] for index in range(len(compact) - 2)}


def _dice_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    return (2 * intersection) / (len(left) + len(right))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(size):
        dot += a[i] * b[i]
        norm_a += a[i] * a[i]
        norm_b += b[i] * b[i]
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _best_snippet(content: str, *, query_tokens: list[str], semantic_terms: list[str]) -> str:
    segments = [
        segment.strip()
        for segment in SENTENCE_SPLIT_PATTERN.split(content)
        if segment and segment.strip()
    ]
    if not segments:
        return _preview(content)

    expanded_terms = sorted(set(query_tokens) | set(semantic_terms))
    best_segment = segments[0]
    best_score = -1.0
    for segment in segments:
        lowered = segment.lower()
        exact_hits = sum(lowered.count(token) for token in query_tokens)
        semantic_hits = sum(
            lowered.count(term) for term in expanded_terms if term not in query_tokens
        )
        trigram_similarity = _dice_similarity(
            _char_trigrams(_normalize_text(" ".join(query_tokens))),
            _char_trigrams(_normalize_text(segment)),
        )
        score = (exact_hits * 3) + semantic_hits + (trigram_similarity * 2)
        if score > best_score:
            best_score = score
            best_segment = segment
    return _preview(best_segment)


def _preview(value: str, limit: int = 260) -> str:
    compact = " ".join(value.split())
    return compact[:limit]
