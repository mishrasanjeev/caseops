"""Case-name predicate for Layer-2-extracted titles.

Shared by the HNSW probe (`scripts.eval_hnsw_recall`) and the
placeholder-title re-extract pipeline (`services.corpus_title_reextract`).
See `.claude/skills/corpus-ingest/SKILL.md` and
`memory/feedback_title_validation_legal_corpus.md` for the principle —
"field non-empty is never enough: the predicate stage N+1 actually
needs must be enforced at the write, or reasserted at the read".

The predicate returns ``(is_valid, reason)`` so callers can either
reject or tally a reason tag for telemetry.
"""
from __future__ import annotations

import re

__all__ = [
    "title_is_case_name",
    "BENCH_HEADER_TOKENS",
]


# Known bench / court-header tokens that PDF page-header extraction
# leaks into the `title` slot. A title composed only of these is never
# a case name.
BENCH_HEADER_TOKENS = frozenset({
    "DHARWAD", "AURANGABAD", "JODHPUR", "KOZHIKODE", "NAGPUR",
    "MADURAI", "LUCKNOW", "INDORE", "GWALIOR", "RANCHI",
    "JABALPUR", "GUWAHATI", "SHILLONG", "IMPHAL", "AIZAWL",
    "KOHIMA", "GANGTOK", "ITANAGAR", "PORT BLAIR", "KOLKATA",
    "BENCH", "AT", "CIRCUIT", "HIGH", "SUPREME", "COURT", "OF",
    "INDIA", "STATE", "UNION", "THE", "HON", "HONBLE",
})

# Party-role labels. Presence of one is a strong positive signal.
_PARTY_ROLE_RE = re.compile(
    r"\b(petitioner|respondent|appellant|applicant|accused|"
    r"complainant|plaintiff|defendant)s?\b",
    re.IGNORECASE,
)
# Party separator with alphabetic chars on each side.
_PARTY_SEPARATOR_RE = re.compile(
    r"\b[A-Za-z]{3,}[\w\s]*\s+(?:v\.?|vs\.?|versus|and)\s+[A-Za-z]{3,}",
    re.IGNORECASE,
)
# Neutral citation / case reference patterns common in Indian law.
_CITATION_RE = re.compile(
    r"\[\d{4}\]|\b(?:SCC|AIR|INSC|DHC|SCR|BOM|MAD|CAL|KHC|MHC|KER)\b|"
    r"\d{4}[:_-][A-Z]{2,6}[:_-]?\d+",
    re.IGNORECASE,
)
# PDF OCR placeholder glyphs seen in the corpus.
_CID_MARKER_RE = re.compile(r"\(cid:\d+\)")
# Non-Latin script ranges common in Indian-court PDFs (Devanagari,
# Gurmukhi, Tamil, Telugu, Kannada, Malayalam, Bengali).
_NON_LATIN_RE = re.compile(
    "[\u0900-\u097F\u0A00-\u0A7F\u0B00-\u0B7F\u0B80-\u0BFF"
    "\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F]"
)


def title_is_case_name(title: str | None) -> tuple[bool, str]:
    """Return ``(is_valid, reason)`` for a Layer-2 ``title`` string.

    Valid iff at least one of:

    - party-separator form (``X v. Y`` / ``X and Y``)
    - contains a neutral citation / case-reference token
    - contains a party-role label (Petitioner / Respondent / …)
    - has ≥ 3 distinctive proper-noun tokens NOT in
      :data:`BENCH_HEADER_TOKENS`

    Otherwise it's probably a PDF page header like ``"DHARWAD BENCH"``,
    an OCR placeholder, or a non-Latin translation cover. Reason tags
    are stable strings for telemetry; do not treat them as user-facing.
    """
    if not title or not title.strip():
        return False, "empty"
    s = title.strip()
    if len(s) < 12:
        return False, "too_short"
    if _CID_MARKER_RE.search(s):
        return False, "cid_marker"
    if _NON_LATIN_RE.search(s):
        return False, "non_latin"
    if _PARTY_SEPARATOR_RE.search(s):
        return True, "party_separator"
    if _CITATION_RE.search(s):
        return True, "citation"
    if _PARTY_ROLE_RE.search(s):
        return True, "party_role"
    proper = [
        t for t in re.findall(r"[A-Za-z]{3,}", s)
        if t[0].isupper() and t.upper() not in BENCH_HEADER_TOKENS
    ]
    if len({t.lower() for t in proper}) >= 3:
        return True, "proper_nouns"
    return False, "bench_header_or_thin"
