"""Query-side normalisers for the authority-catalog HNSW search.

The 2026-04-20 SC-2023 HNSW probe hit recall@10 = 83.3 % (25/30), and the
five misses clustered on query shapes that the corpus clearly contains but
whose embeddings do not match:

1. ``2022 15 827`` — pure-numeric SC citation. No alpha content for Voyage
   to latch onto; the query vector drifts toward random-numeric neighbours.
2. ``DHARWAD BENCH`` — all-caps bench-name query. The ingested title-chunk
   embeds ``Dharwad`` (Title Case); caps-only queries collide with
   abbreviation / statute-code neighbours.
3. ``[2019] 1 S.C.R. 1001`` / ``[2021] 1 S.C.R. 694`` — SC citation with
   punctuation. The corpus stores the same citation as ``2019 1 SCR 1001``
   (no brackets, no dots), and the bracketed form embeds to a different
   slice of the latent space than the plain form.
5. Punjabi-script party name. The Voyage multilingual model does encode
   Gurmukhi, but the corpus was ingested on English-translated headings,
   so the query and doc vectors live in different clusters.

Fix strategy (this module): generate English / unpunctuated variants of
the query BEFORE embedding, embed each variant, union the top-k per
variant, and let the re-scorer pick the winner. No re-ingest, no
re-embed, no index change.

Every helper here is a pure function — no DB, no network — except
``translate_query_to_english`` which is a thin optional wrapper over the
``metadata_extract`` LLM provider. The Haiku path is guarded by
``settings.retrieval_non_english_translate`` (default OFF) so it stays
zero-cost until operators opt in after measuring.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Citation normaliser
# ---------------------------------------------------------------------------

# SC-style citation with optional bracket / paren wrapping and dots inside
# ``S.C.R.``. Matches ``[2019] 1 S.C.R. 1001``, ``(2021) 1 SCR 694``,
# ``2019 1 SCR 1001``. Year → volume → reporter-tag → page.
_SCR_CITATION_RE = re.compile(
    r"^\s*[\[\(]?\s*(?P<year>\d{4})\s*[\]\)]?\s*"
    r"(?P<volume>\d+)\s*"
    r"S\.?\s*C\.?\s*R\.?\s*"
    r"(?P<page>\d+)\s*$",
    re.IGNORECASE,
)

# Pure-numeric ``YYYY N NNN`` citation (SC INSC / cause-title shorthand).
# Year + 2-3 digit case number + 2-4 digit page / order number.
_NUMERIC_CITATION_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s+(?P<volume>\d{1,3})\s+(?P<page>\d{1,5})\s*$",
)

# Alpha detector — if any Latin / Indic letter appears, the numeric-only
# rule must not fire (protects topical queries like "bail 2022 15 827").
_ANY_ALPHA_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def normalise_citation_query(q: str) -> list[str]:
    """Return citation variants for ``q``, most-specific first.

    When ``q`` looks like a bracketed SC reporter citation
    (``[2019] 1 S.C.R. 1001``) or a pure-numeric shorthand
    (``2022 15 827`` with no alpha content), emit a deduplicated list of
    variants covering the common forms in the corpus: bare spaces, wrapped
    brackets, wrapped parens, and reporter-tag dropped. The original
    query is always the last element so callers can safely treat the
    return value as an ordered variant list that includes the input.

    Queries that do not match either pattern are returned as
    ``[q]`` — callers pass this straight through to the embedder.
    """
    stripped = q.strip()
    if not stripped:
        return [q]

    scr_match = _SCR_CITATION_RE.match(stripped)
    if scr_match:
        year = scr_match.group("year")
        volume = scr_match.group("volume")
        page = scr_match.group("page")
        variants = [
            f"{year} {volume} SCR {page}",
            f"[{year}] {volume} SCR {page}",
            f"({year}) {volume} SCR {page}",
            f"{year} SCR {page}",
            stripped,
        ]
        return _dedupe_preserve_order(variants)

    # Pure-numeric only if the query has no alpha at all. This stops
    # "bail 2022 15 827" from being rewritten as a citation probe.
    if _NUMERIC_CITATION_RE.match(stripped) and not _ANY_ALPHA_RE.search(stripped):
        numeric_match = _NUMERIC_CITATION_RE.match(stripped)
        assert numeric_match is not None  # narrowing for type checker
        year = numeric_match.group("year")
        volume = numeric_match.group("volume")
        page = numeric_match.group("page")
        variants = [
            f"{year} {volume} {page}",
            f"{year} {volume} SCR {page}",
            f"[{year}] {volume} SCR {page}",
            f"({year}) {volume} SCR {page}",
            stripped,
        ]
        return _dedupe_preserve_order(variants)

    return [q]


# ---------------------------------------------------------------------------
# Bench normaliser
# ---------------------------------------------------------------------------

_BENCH_SUFFIXES = ("BENCH", "COURT", "HC")


def normalise_bench_query(q: str) -> str | None:
    """Collapse all-caps bench-name queries to their Title-Case stem.

    ``DHARWAD BENCH`` → ``Dharwad``. ``BOMBAY HIGH COURT`` → ``Bombay High``.

    Rule: query is ≤ 4 tokens, mostly uppercase (≥ 80 % of alpha tokens
    are fully upper), and one of the ``_BENCH_SUFFIXES`` appears at the
    head or tail of the token stream. Returns None when the rule does
    not match — caller then uses the original query.
    """
    stripped = q.strip()
    if not stripped:
        return None
    tokens = stripped.split()
    if not (1 <= len(tokens) <= 4):
        return None

    alpha_tokens = [t for t in tokens if any(ch.isalpha() for ch in t)]
    if not alpha_tokens:
        return None
    upper_count = sum(1 for t in alpha_tokens if t.isupper())
    if upper_count / len(alpha_tokens) < 0.8:
        return None

    first_upper = tokens[0].upper()
    last_upper = tokens[-1].upper()
    if last_upper in _BENCH_SUFFIXES:
        stem_tokens = tokens[:-1]
    elif first_upper in _BENCH_SUFFIXES:
        stem_tokens = tokens[1:]
    else:
        return None

    if not stem_tokens:
        return None

    return " ".join(t.capitalize() for t in stem_tokens)


# ---------------------------------------------------------------------------
# Non-English script detector
# ---------------------------------------------------------------------------

# (inclusive-start, inclusive-end) Unicode ranges for Indic scripts we
# expect in party names / cause titles. Gurmukhi = Punjabi.
_INDIC_SCRIPT_RANGES: tuple[tuple[int, int], ...] = (
    (0x0900, 0x097F),  # Devanagari
    (0x0980, 0x09FF),  # Bengali
    (0x0A00, 0x0A7F),  # Gurmukhi (Punjabi)
    (0x0B80, 0x0BFF),  # Tamil
    (0x0C00, 0x0C7F),  # Telugu
    (0x0C80, 0x0CFF),  # Kannada
)


def _is_indic(ch: str) -> bool:
    cp = ord(ch)
    for lo, hi in _INDIC_SCRIPT_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def is_non_english_script(q: str) -> bool:
    """True when ≥ 30 % of alphabetic code points live in a supported
    Indic script.

    Short queries with a handful of Indic characters still trip the
    threshold — that's intentional, the downstream action is only a
    translation attempt, not a destructive rewrite.
    """
    if not q:
        return False
    alpha_chars = [ch for ch in q if ch.isalpha()]
    if not alpha_chars:
        return False
    indic_count = sum(1 for ch in alpha_chars if _is_indic(ch))
    return (indic_count / len(alpha_chars)) >= 0.30


# ---------------------------------------------------------------------------
# Optional LLM translation
# ---------------------------------------------------------------------------

_TRANSLATE_SYSTEM_PROMPT = (
    "Translate this Indian legal case heading / party name to English, "
    "preserving proper nouns in transliteration. "
    "Output ONLY the translation, no explanation."
)


def translate_query_to_english(q: str) -> str | None:
    """Translate a non-English query via the ``metadata_extract`` LLM.

    Returns the translation on success, or None when:
    - ``settings.retrieval_non_english_translate`` is False (default),
    - the LLM provider errors for any reason,
    - the provider returns an empty string.

    Guarded because every call costs tokens and the quality gain is
    still being measured; operators flip the flag to True once the
    probe confirms the variant outperforms the raw query.
    """
    from caseops_api.core.settings import get_settings

    settings = get_settings()
    if not getattr(settings, "retrieval_non_english_translate", False):
        return None

    stripped = q.strip()
    if not stripped:
        return None

    try:
        from caseops_api.services.llm import (
            LLMCallContext,
            LLMMessage,
            build_provider,
        )

        provider = build_provider("metadata_extract")
        messages = [
            LLMMessage(role="system", content=_TRANSLATE_SYSTEM_PROMPT),
            LLMMessage(role="user", content=stripped),
        ]
        _ = LLMCallContext  # reserved for downstream audit wiring
        completion = provider.generate(
            messages,
            temperature=0.0,
            max_tokens=40,
        )
    except Exception:  # noqa: BLE001 - translation is best-effort
        logger.debug("translate_query_to_english failed", exc_info=True)
        return None

    text = (completion.text or "").strip()
    if not text or text == stripped:
        return None
    return text


# ---------------------------------------------------------------------------
# Aggregator used by retrieval
# ---------------------------------------------------------------------------


def build_query_variants(q: str) -> list[str]:
    """Return the ordered variant list for ``q``.

    The original query is always included (and always first in the
    citation / bench fall-through paths). Callers embed every variant,
    run HNSW per variant, and union the results.
    """
    stripped = q.strip()
    if not stripped:
        return [q]

    variants: list[str] = [q]

    citation_variants = normalise_citation_query(q)
    for variant in citation_variants:
        if variant not in variants:
            variants.append(variant)

    bench_variant = normalise_bench_query(q)
    if bench_variant and bench_variant not in variants:
        variants.append(bench_variant)

    if is_non_english_script(q):
        translated = translate_query_to_english(q)
        if translated and translated not in variants:
            variants.append(translated)

    return variants


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
