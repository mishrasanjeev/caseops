"""Slice D (MOD-TS-001-E) — judge alias normaliser + tolerant matcher.

Used by:
- Slice B (`services/bench_resolver.py`) — resolves a parsed bench
  name string to one or more `Judge.id` values.
- Slice C (`services/bench_strategy_context.py`) — replaces the prior
  ILIKE-on-judges_json fragility with FK-based lookups.

The normaliser is intentionally conservative:
- lowercase, strip punctuation, collapse whitespace
- "Justice A.K. Sikri" → "justice a k sikri"
- "Justice Adarsh Kumar Sikri" → "justice adarsh kumar sikri"

These two normalised forms are different. The tolerant matcher's job
is to recognise initial-overlap (a -> adarsh, k -> kumar) AND surname
match (sikri -> sikri) — that's where `match_candidates` comes in.

Per the user's high-quality confidence floor (PRD §6 answer 2), a
single common surname alone is NOT enough — the matcher requires:
- (initial+surname AND court-scope match), OR
- (full name AND court-scope match)
Below that floor, return no match (caller decides what to do).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Judge, JudgeAlias

logger = logging.getLogger(__name__)

_STRIP_PUNCT_RE = re.compile(r"[^\w\s]")
_HONORIFIC_RE = re.compile(
    r"^(?:hon[\u2019']?ble\s+)?(?:mr\.?|ms\.?|mrs\.?|the\s+)?\s*"
    r"(?:chief\s+justice|justice|j\.\s+|j\.|j)\s*",
    flags=re.IGNORECASE,
)


def normalise(text: str) -> str:
    """Canonical form for alias lookup. Idempotent."""
    if not text:
        return ""
    cleaned = text.replace("\u00a0", " ").strip()
    cleaned = _STRIP_PUNCT_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower()


def _strip_honorific_loose(text: str) -> str:
    """Honorific-stripped + punctuation-preserved (so initials stay)."""
    return _HONORIFIC_RE.sub("", text or "").strip()


def canonical_aliases_for(judge: Judge) -> list[str]:
    """Generate the standard alias surface for a judge.

    Output is human-friendly text (NOT normalised). Caller normalises
    via `normalise()` when persisting/looking up.
    """
    name = (judge.full_name or "").strip()
    if not name:
        return []
    parts = name.split()
    aliases: list[str] = []

    # 1. The full name as stored.
    aliases.append(name)

    # 2. With "Justice " prefix (the most common bench-roster format).
    aliases.append(f"Justice {name}")

    # 3. With the judge's stored honorific.
    if judge.honorific:
        aliases.append(f"{judge.honorific} {name}")

    # 4. Initial + surname forms when name has ≥ 2 tokens.
    if len(parts) >= 2:
        surname = parts[-1]
        first_initials = ".".join(p[0].upper() for p in parts[:-1]) + "."
        aliases.append(f"{first_initials} {surname}")
        aliases.append(f"Justice {first_initials} {surname}")

    # 5. Compact initial + surname (no dots).
    if len(parts) >= 2:
        surname = parts[-1]
        compact = "".join(p[0].upper() for p in parts[:-1])
        aliases.append(f"Justice {compact} {surname}")

    # Dedupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for a in aliases:
        norm = normalise(a)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(a)
    return out


@dataclass(frozen=True)
class MatchResult:
    judge_id: str
    judge_full_name: str
    confidence: str  # "exact" | "initial_surname" | "surname_only"
    matched_alias: str


def _tokens(text: str) -> list[str]:
    return [t for t in normalise(text).split() if t]


def match_candidates(
    session: Session,
    *,
    raw_text: str,
    court_id: str,
) -> list[MatchResult]:
    """Tolerant judge match scoped to one court.

    Returns only matches at or above the user's confidence floor:
    - "exact" — alias_normalised matches exactly
    - "initial_surname" — surname matches AND first-token-initial
      matches the candidate's first-name initial.
    Surname-only matches are EXCLUDED — too ambiguous.

    The list is empty when no candidate clears the floor; callers
    surface that as "unresolved" rather than guessing.
    """
    if not raw_text or not court_id:
        return []
    cleaned = _strip_honorific_loose(raw_text)
    needle = normalise(cleaned)
    if not needle:
        return []
    tokens = _tokens(cleaned)
    if not tokens:
        return []

    # 1. Exact alias hit (highest confidence).
    exact_rows = session.execute(
        select(JudgeAlias.judge_id, Judge.full_name, JudgeAlias.alias_text)
        .join(Judge, Judge.id == JudgeAlias.judge_id)
        .where(JudgeAlias.alias_normalised == needle)
        .where(Judge.court_id == court_id)
        .where(Judge.is_active.is_(True))
    ).all()
    out: list[MatchResult] = [
        MatchResult(
            judge_id=row.judge_id,
            judge_full_name=row.full_name,
            confidence="exact",
            matched_alias=row.alias_text,
        )
        for row in exact_rows
    ]
    if out:
        return out

    # 2. Initial + surname fallback. Pull every Judge in the court,
    # compare structurally. Court-scope keeps the candidate set tiny
    # (typically 30-60 judges) so an in-Python loop is fine.
    if len(tokens) < 2:
        # High-quality confidence floor (PRD §6 answer 2): a single-
        # token input like "Singh" is JUST a surname — too ambiguous
        # to confidently resolve even within a single court. Caller
        # surfaces this as unresolved.
        return []
    surname = tokens[-1]
    if len(surname) < 4:
        # Too short to be a stable surname (e.g. "rai" / "raj") — be
        # conservative; the caller can re-query with a broader hint.
        return []
    first_initial = tokens[0][0] if tokens and tokens[0] else ""
    judges = session.scalars(
        select(Judge)
        .where(Judge.court_id == court_id)
        .where(Judge.is_active.is_(True))
    ).all()
    for j in judges:
        j_tokens = _tokens(j.full_name or "")
        if len(j_tokens) < 2:
            # Symmetric: a Judge stored as just one token has no
            # initial separable from surname; cannot satisfy the floor.
            continue
        j_surname = j_tokens[-1]
        if j_surname != surname:
            continue
        # Surname matches AND we know we have a needle initial that
        # is from a SEPARATE token than the surname (guarded above).
        # Require it to overlap with one of the judge's first-name
        # initials.
        j_first_initials = {t[0] for t in j_tokens[:-1] if t}
        if not first_initial:
            continue
        if first_initial in j_first_initials:
            out.append(
                MatchResult(
                    judge_id=j.id,
                    judge_full_name=j.full_name,
                    confidence="initial_surname",
                    matched_alias=j.full_name,
                )
            )
    return out


def backfill_canonical_aliases(
    session: Session, *, source: str = "auto_extract",
) -> tuple[int, int]:
    """Generate canonical aliases for every Judge in DB. Idempotent —
    on re-run, existing rows are left alone.

    Returns ``(inserted, skipped_existing)``.
    """
    judges = session.scalars(select(Judge)).all()
    inserted = 0
    skipped = 0
    now = datetime.now(UTC)
    # Pre-load existing aliases as (judge_id, alias_normalised) set.
    existing_pairs = {
        (a.judge_id, a.alias_normalised)
        for a in session.scalars(select(JudgeAlias)).all()
    }
    for judge in judges:
        for alias_text in canonical_aliases_for(judge):
            norm = normalise(alias_text)
            key = (judge.id, norm)
            if key in existing_pairs:
                skipped += 1
                continue
            session.add(
                JudgeAlias(
                    judge_id=judge.id,
                    alias_text=alias_text,
                    alias_normalised=norm,
                    source=source,
                    created_at=now,
                    updated_at=now,
                )
            )
            existing_pairs.add(key)
            inserted += 1
    session.commit()
    return inserted, skipped
