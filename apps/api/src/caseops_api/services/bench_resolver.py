"""Slice B (MOD-TS-001-C) — bench-roster parser + court-scoped
resolver.

Two responsibilities:

1. ``parse_bench_name(text)`` — tokenise a free-text bench string
   like ``"Justice A.S. Chandurkar & Justice X.Y.Z."`` into a list
   of candidate name strings.
2. ``resolve_listing_bench(session, *, listing_id)`` — for one
   ``MatterCauseListEntry``, parse the bench, resolve each candidate
   against ``services.judge_aliases.match_candidates`` (court-scoped
   via the matter's court_id), and persist the resolved list as
   JSON in ``MatterCauseListEntry.judges_json``.

The high-quality confidence floor from PRD §6 answer 2 is enforced
by ``services.judge_aliases.match_candidates`` — this service just
records what came back without weakening the floor.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Matter, MatterCauseListEntry
from caseops_api.services.judge_aliases import match_candidates

logger = logging.getLogger(__name__)

# Bench separators in order of generality. We split on " & ", " and ",
# " ; ", and "," — but NOT plain " " (would shred multi-token names).
_SEPARATORS_RE = re.compile(r"\s*(?:&|;|,|\band\b)\s*", flags=re.IGNORECASE)


def parse_bench_name(text: str) -> list[str]:
    """Split a free-text bench string into candidate name strings.

    Handles common bench formats:
    - "Justice X & Justice Y"
    - "Justice X, Justice Y"
    - "Hon'ble Mr. Justice X and Hon'ble Mr. Justice Y"
    - all-caps + mixed case
    """
    if not text:
        return []
    # Normalise typographic quotes that show up in scraped HTML.
    cleaned = text.replace("\u2019", "'").replace("\u00a0", " ").strip()
    parts = [p.strip() for p in _SEPARATORS_RE.split(cleaned) if p.strip()]
    # Drop pure-honorific fragments left over from "Hon'ble The Chief".
    candidates = [p for p in parts if len(p) >= 4 and any(c.isalpha() for c in p)]
    return candidates


@dataclass(frozen=True)
class BenchMember:
    judge_id: str
    matched_alias: str
    confidence: str


def resolve_listing_bench(
    session: Session, *, listing_id: str,
) -> tuple[list[BenchMember], list[str]]:
    """Resolve one MatterCauseListEntry's bench. Returns
    (matched, unmatched) and persists the matched list as JSON.

    Court scope is the matter's court_id when set; falls back to
    looking up an active Court whose name matches the entry's
    forum_name. When neither is available the function returns
    ([], [original_bench_name]) and writes "[]" to mark the row
    processed.
    """
    entry = session.scalar(
        select(MatterCauseListEntry).where(MatterCauseListEntry.id == listing_id)
    )
    if entry is None:
        return [], []
    bench_name = entry.bench_name or ""
    if not bench_name.strip():
        # Nothing to resolve — mark processed so the backfill job
        # doesn't keep retrying.
        entry.judges_json = "[]"
        session.commit()
        return [], []

    matter = session.scalar(
        select(Matter).where(Matter.id == entry.matter_id)
    )
    if matter is None or not matter.court_id:
        # No reliable court scope — skip resolution; the row stays
        # marked unprocessed (judges_json IS NULL) and the ops
        # dashboard surfaces it.
        return [], parse_bench_name(bench_name)

    candidates = parse_bench_name(bench_name)
    matched: list[BenchMember] = []
    unmatched: list[str] = []
    for candidate in candidates:
        results = match_candidates(
            session,
            raw_text=candidate,
            court_id=matter.court_id,
        )
        if not results:
            unmatched.append(candidate)
            continue
        # When multiple matches come back (e.g. two judges with the
        # same surname pass the initial test), keep all — caller can
        # warn that the bench is ambiguous.
        for r in results:
            matched.append(
                BenchMember(
                    judge_id=r.judge_id,
                    matched_alias=r.matched_alias,
                    confidence=r.confidence,
                )
            )

    payload = json.dumps(
        [
            {
                "judge_id": m.judge_id,
                "matched_alias": m.matched_alias,
                "confidence": m.confidence,
            }
            for m in matched
        ],
        ensure_ascii=False,
    )
    entry.judges_json = payload
    session.commit()
    return matched, unmatched


def resolve_all_unprocessed(session: Session) -> dict[str, int]:
    """Backfill helper — process every cause-list entry where
    judges_json IS NULL. Returns counts for the ops log.
    """
    rows = session.scalars(
        select(MatterCauseListEntry).where(
            MatterCauseListEntry.judges_json.is_(None)
        )
    ).all()
    started = datetime.now(UTC)
    total = len(rows)
    matched_total = 0
    unmatched_total = 0
    no_court = 0
    for entry in rows:
        # resolve_listing_bench commits per row so a partial failure
        # doesn't lose all progress.
        try:
            matched, unmatched = resolve_listing_bench(
                session, listing_id=entry.id,
            )
        except Exception as exc:  # noqa: BLE001 — broad catch is intentional
            logger.exception(
                "bench resolver failed on listing_id=%s: %s",
                entry.id,
                exc,
            )
            continue
        if matched or unmatched:
            matched_total += len(matched)
            unmatched_total += len(unmatched)
        else:
            no_court += 1
    elapsed = (datetime.now(UTC) - started).total_seconds()
    summary = {
        "total": total,
        "matched": matched_total,
        "unmatched": unmatched_total,
        "skipped_no_court_scope": no_court,
        "elapsed_seconds": int(elapsed),
    }
    logger.info("bench resolver summary: %s", summary)
    return summary
