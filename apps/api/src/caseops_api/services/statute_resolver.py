"""Slice S3 (MOD-TS-017) — tolerant section-string parser + resolver.

Used by:
- ``services/recommendations.py`` / drafting / hearing-pack flows that
  need to know "this matter cites Section 482 CrPC" with a structured
  FK, not a free-text ILIKE.
- The Cloud Run Job ``caseops-resolve-authority-statutes`` that walks
  every ``AuthorityDocument.sections_cited_json`` and writes
  ``authority_statute_references`` rows.

Format Layer-2 emits today (see services/corpus_structured.py): a JSON
list of strings like ``["BNSS Section 483", "CrPC §439", "Article 226"]``.

Parsing strategy:
1. Scan for an Act token. Longest-match wins (BNSS before BNS).
2. Find the section / article number — supports
   ``Section X``, ``Sec. X``, ``S. X``, ``§X``, ``Article X``, ``Art. X``,
   bare ``X`` (only if Act token is unambiguous).
3. Format the lookup key as it appears in the seed
   (``"Section 482"`` or ``"Article 226"``).
4. Return ``(statute_id, section_number_str)`` or ``None`` when we
   cannot reach the high-confidence floor.

Bench-aware drafting hard rules: this resolver's output is structured
evidence, not favorability — same provenance discipline as the
JudgeAlias resolver. Source attribution stays in the
``authority_statute_references.source`` column ('layer2_extract' or
'manual').
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityStatuteReference,
    Statute,
    StatuteSection,
)

logger = logging.getLogger(__name__)


# Map Act-text variants to our statute_id catalog. Order matters —
# longest needles first so 'BNSS' resolves before 'BNS' on
# 'BNSS Section 483'.
_ACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bBNSS\b", re.IGNORECASE), "bnss-2023"),
    (re.compile(r"\bBSA\b", re.IGNORECASE), "bsa-2023"),
    (re.compile(r"\bBNS\b", re.IGNORECASE), "bns-2023"),
    (re.compile(r"\bCr\.?\s*P\.?\s*C\.?\b", re.IGNORECASE), "crpc-1973"),
    (re.compile(r"\bI\.?\s*P\.?\s*C\.?\b", re.IGNORECASE), "ipc-1860"),
    (
        re.compile(
            r"\b(?:N\.?I\.?\s*Act|Negotiable\s+Instruments\s+Act)\b",
            re.IGNORECASE,
        ),
        "ni-act-1881",
    ),
    (
        re.compile(
            r"\b(?:Constitution(?:\s+of\s+India)?|Indian\s+Constitution)\b",
            re.IGNORECASE,
        ),
        "constitution-india",
    ),
]

_SECTION_RE = re.compile(
    r"(?:Section|Sec\.?|S\.?)\s*([0-9]+[A-Za-z]*(?:\([0-9a-z]+\))?)",
    re.IGNORECASE,
)
_SECTION_SYMBOL_RE = re.compile(r"§\s*([0-9]+[A-Za-z]*(?:\([0-9a-z]+\))?)")
_ARTICLE_RE = re.compile(
    r"(?:Article|Art\.?)\s*([0-9]+[A-Za-z]*)", re.IGNORECASE,
)
_BARE_NUMBER_RE = re.compile(r"\b([0-9]{1,4}[A-Za-z]?)\b")


def _detect_act(text: str) -> str | None:
    """Return the statute_id the text references, or None when
    ambiguous / absent."""
    matches = []
    for pattern, statute_id in _ACT_PATTERNS:
        m = pattern.search(text)
        if m:
            matches.append((m.start(), m.end() - m.start(), statute_id))
    if not matches:
        return None
    # Prefer the longest matching token (BNSS over BNS); tie-break on
    # earliest occurrence.
    matches.sort(key=lambda t: (-t[1], t[0]))
    return matches[0][2]


def parse_section_string(text: str) -> tuple[str, str] | None:
    """Parse a free-text section reference into (statute_id, section_number).

    Returns ``None`` when the parser can't reach the confidence floor:
    - no Act detected, OR
    - no section/article number found, OR
    - bare number alone (no act context — too ambiguous to guess).
    """
    if not text or not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None

    statute_id = _detect_act(cleaned)

    # "Article X" is unambiguous in Indian legal practice — only the
    # Constitution uses Articles. Default to constitution-india when
    # the text contains an Article reference and no conflicting Act
    # token. This catches the common Layer-2 output "Article 226"
    # (no parent qualifier).
    article_match = _ARTICLE_RE.search(cleaned)
    if article_match and statute_id in (None, "constitution-india"):
        return "constitution-india", f"Article {article_match.group(1)}"

    if statute_id is None:
        return None

    # Constitution explicitly named but with a Section ref — caller's
    # input is malformed; bail rather than guess.
    if statute_id == "constitution-india":
        return None

    for pattern in (_SECTION_RE, _SECTION_SYMBOL_RE):
        m = pattern.search(cleaned)
        if m:
            return statute_id, f"Section {m.group(1)}"

    # Last-ditch: a bare number when an Act is unambiguous (e.g.
    # "BNSS 483" with no Section/Sec/§ prefix). Cap at 4 digits to
    # avoid catching years.
    m = _BARE_NUMBER_RE.search(cleaned)
    if m:
        return statute_id, f"Section {m.group(1)}"
    return None


def parse_section_strings(items: Iterable[str]) -> list[tuple[str, str]]:
    """Vectorised parse_section_string. Drops None and dedupes
    (statute_id, section_number) pairs while preserving first-seen
    order."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for raw in items:
        result = parse_section_string(raw)
        if result is None or result in seen:
            continue
        seen.add(result)
        out.append(result)
    return out


def resolve_authority_sections(
    session: Session, *, authority_id: str,
) -> dict[str, int]:
    """Walk one AuthorityDocument's ``sections_cited_json``, parse each
    string, look up the matching StatuteSection row, and insert /
    update ``authority_statute_references`` rows.

    Returns ``{"matched": int, "unmatched": int, "skipped_existing": int}``.
    Idempotent — re-running against the same authority increments
    occurrence_count rather than appending duplicates.
    """
    doc = session.scalar(
        select(AuthorityDocument).where(AuthorityDocument.id == authority_id)
    )
    if doc is None or not doc.sections_cited_json:
        return {"matched": 0, "unmatched": 0, "skipped_existing": 0}

    try:
        raw = json.loads(doc.sections_cited_json)
    except (ValueError, TypeError):
        return {"matched": 0, "unmatched": 0, "skipped_existing": 0}
    if not isinstance(raw, list):
        return {"matched": 0, "unmatched": 0, "skipped_existing": 0}
    items: list[str] = [s for s in raw if isinstance(s, str) and s.strip()]
    if not items:
        return {"matched": 0, "unmatched": 0, "skipped_existing": 0}

    parsed = parse_section_strings(items)
    unmatched = max(0, len(items) - len(parsed))

    if not parsed:
        return {"matched": 0, "unmatched": unmatched, "skipped_existing": 0}

    # One DB lookup per (statute_id, section_number) — small N, no
    # need to bulk-fetch.
    now = datetime.now(UTC)
    matched = 0
    skipped = 0
    for statute_id, section_number in parsed:
        section = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == statute_id,
                StatuteSection.section_number == section_number,
                StatuteSection.is_active.is_(True),
            )
        )
        if section is None:
            # Parsed correctly but section isn't in our v1 catalog
            # (e.g. CrPC s.299 not in the seed). Count as unmatched
            # so the dashboard can flag the gap.
            unmatched += 1
            continue
        existing = session.scalar(
            select(AuthorityStatuteReference).where(
                AuthorityStatuteReference.authority_id == doc.id,
                AuthorityStatuteReference.section_id == section.id,
            )
        )
        if existing is not None:
            existing.occurrence_count = (existing.occurrence_count or 1) + 1
            existing.updated_at = now
            skipped += 1
            continue
        session.add(
            AuthorityStatuteReference(
                authority_id=doc.id,
                section_id=section.id,
                occurrence_count=1,
                source="layer2_extract",
                created_at=now,
                updated_at=now,
            ),
        )
        matched += 1
    session.commit()
    return {
        "matched": matched,
        "unmatched": unmatched,
        "skipped_existing": skipped,
    }


def resolve_all_unprocessed_authorities(
    session: Session, *, batch_size: int = 200,
) -> dict[str, int]:
    """Backfill helper — walk every authority that has
    ``sections_cited_json`` but no ``authority_statute_references``
    rows yet. Commits per-authority so partial failure doesn't lose
    all progress. Returns aggregate counters for the ops log."""
    started = datetime.now(UTC)
    summary = {
        "authorities_seen": 0,
        "matched": 0,
        "unmatched": 0,
        "skipped_existing": 0,
        "errors": 0,
        "elapsed_seconds": 0,
    }

    # Pull authority IDs that have sections_cited_json AND no
    # corresponding refs yet. Subquery keeps the candidate set small.
    candidate_ids = list(
        session.scalars(
            select(AuthorityDocument.id)
            .where(AuthorityDocument.sections_cited_json.is_not(None))
            .where(
                ~select(AuthorityStatuteReference.id)
                .where(AuthorityStatuteReference.authority_id == AuthorityDocument.id)
                .exists()
            )
            .limit(batch_size)
        ).all()
    )
    summary["authorities_seen"] = len(candidate_ids)

    for aid in candidate_ids:
        try:
            stats = resolve_authority_sections(session, authority_id=aid)
        except Exception as exc:  # noqa: BLE001 — broad catch is intentional
            logger.exception(
                "statute resolver failed on authority_id=%s: %s", aid, exc,
            )
            summary["errors"] += 1
            continue
        summary["matched"] += stats["matched"]
        summary["unmatched"] += stats["unmatched"]
        summary["skipped_existing"] += stats["skipped_existing"]

    summary["elapsed_seconds"] = int(
        (datetime.now(UTC) - started).total_seconds()
    )
    logger.info("resolve_all_unprocessed_authorities: %s", summary)
    return summary


def _ensure_loaded() -> None:
    """No-op import-side-effect guard. Used by tests to assert the
    module is importable without raising on missing deps."""
    _ = Statute, StatuteSection, AuthorityStatuteReference, AuthorityDocument
