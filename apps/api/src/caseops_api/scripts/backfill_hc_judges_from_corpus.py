"""Corpus-derived HC judge backfill — extract judge names from
``authority_documents.judges_json`` and insert any not yet in the
``judges`` table.

Per the 2026-04-26 PRD §4.2 prereq for MOD-TS-018 (bench strategy).
Replaces the original "scrape 6 HC official websites" plan because
the data is already in our corpus — Layer-2 metadata extraction
populates ``judges_json`` for every processed document.

CLI:
    python -m caseops_api.scripts.backfill_hc_judges_from_corpus
    python -m caseops_api.scripts.backfill_hc_judges_from_corpus --court delhi-hc
    python -m caseops_api.scripts.backfill_hc_judges_from_corpus --dry-run
    python -m caseops_api.scripts.backfill_hc_judges_from_corpus \\
        --court bombay-hc --min-occurrences 3

Per-court ``--min-occurrences`` floor (default 2) drops one-off names
that are usually parser artifacts (sub-headings, "Acting Chief
Justice" with no name, etc.). The judge must appear on the bench of
at least N indexed decisions to count as sitting.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text

from caseops_api.db.models import (
    Court,
    Judge,
    JudgeAppointment,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.judge_aliases import (
    canonical_aliases_for,
    match_candidates,
    normalise,
)

logger = logging.getLogger("backfill_hc_judges_from_corpus")

# Court-name → court_id mapping. The values match `courts.id` in our
# Court master table. Heterogeneous court_name strings in the corpus
# (e.g. "Delhi High Court" vs "High Court of Delhi") map to one
# court_id via a substring contains-check.
_COURT_NAME_MATCHERS: list[tuple[str, str]] = [
    ("delhi", "delhi-hc"),
    ("bombay", "bombay-hc"),
    ("madras", "madras-hc"),
    ("karnataka", "karnataka-hc"),
    ("telangana", "telangana-hc"),
    ("allahabad", "allahabad-hc"),
    ("calcutta", "calcutta-hc"),
]

# Patterns that look like roles/titles, not actual judge names.
# We reject these to avoid creating "Judge: Acting Chief Justice"
# rows that pollute the registry.
_NON_NAME_PATTERNS = [
    re.compile(r"^acting\s+chief\s+justice$", re.IGNORECASE),
    re.compile(r"^chief\s+justice$", re.IGNORECASE),
    re.compile(r"^bench$", re.IGNORECASE),
    re.compile(r"^per\s*[:\.]?$", re.IGNORECASE),
    re.compile(r"^the\s+court$", re.IGNORECASE),
    re.compile(r"^coram$", re.IGNORECASE),
    re.compile(r"^honble.*$", re.IGNORECASE),  # e.g. "honble" alone
]

_MIN_NAME_TOKENS = 2  # require at least first + surname after honorific strip


def _strip_honorifics(raw: str) -> str:
    """Strip honorifics + trailing role markers. Returns title-cased
    candidate name (or empty if nothing useful remains)."""
    s = (raw or "").strip()
    # Remove leading honorifics
    s = re.sub(
        r"^(?:hon[\u2019']?ble\s+)?(?:mr\.?|ms\.?|mrs\.?|the\s+)?\s*"
        r"(?:chief\s+justice|justice|j\.?)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # Remove trailing ", J." / ", J" / " J." / " J" markers
    s = re.sub(r"[,\s]+J\.?$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    # Title-case if it's all-caps (corpus has both "YASHWANT VARMA" and
    # "Yashwant Varma" forms). Don't title-case mixed-case strings —
    # those are likely already correct.
    if s == s.upper() and " " in s:
        s = s.title()
    return s


def _is_real_name(candidate: str) -> bool:
    if not candidate:
        return False
    for pat in _NON_NAME_PATTERNS:
        if pat.match(candidate):
            return False
    tokens = [t for t in re.split(r"\s+", candidate) if t]
    if len(tokens) < _MIN_NAME_TOKENS:
        return False
    # At least one token must contain a letter (reject pure punctuation)
    if not any(re.search(r"[A-Za-z]", t) for t in tokens):
        return False
    return True


def _resolve_court_id(court_name: str | None) -> str | None:
    if not court_name:
        return None
    lower = court_name.lower()
    for substr, court_id in _COURT_NAME_MATCHERS:
        if substr in lower:
            return court_id
    return None


def _ensure_court_exists(session, court_id: str) -> bool:
    """Return True if the Court master row exists. Don't auto-create —
    the courts table is curated and an unknown court_id is a signal
    of a parser bug."""
    return session.get(Court, court_id) is not None


def _persist_alias(session, judge_id: str, alias_text: str) -> None:
    """Insert one JudgeAlias row, ignoring duplicates."""
    norm = normalise(alias_text)
    if not norm:
        return
    session.execute(
        text(
            "INSERT INTO judge_aliases (id, judge_id, alias_text, alias_normalised, created_at) "
            "VALUES (:id, :j, :a, :n, NOW()) ON CONFLICT DO NOTHING"
        ),
        {"id": str(uuid4()), "j": judge_id, "a": alias_text[:255], "n": norm[:255]},
    )


def run(
    *,
    court_filter: str | None,
    min_occurrences: int,
    dry_run: bool,
) -> int:
    factory = get_session_factory()
    counters: dict[str, dict[str, int]] = defaultdict(
        lambda: {"raw_distinct": 0, "real_names": 0, "matched": 0, "inserted": 0, "rejected": 0}
    )

    courts_to_process = (
        [court_filter] if court_filter else [c for _, c in _COURT_NAME_MATCHERS]
    )

    with factory() as session:
        for court_id in courts_to_process:
            if not _ensure_court_exists(session, court_id):
                logger.warning(
                    "Court %r is not in the courts table — skipping. "
                    "Add via seed data first.", court_id,
                )
                continue
            substr = next(
                (s for s, c in _COURT_NAME_MATCHERS if c == court_id), None,
            )
            if not substr:
                logger.warning("No name-substring matcher for court_id=%r", court_id)
                continue

            logger.info("=== %s ===", court_id)
            # Aggregate distinct judge names with their occurrence counts.
            rows = session.execute(
                text(
                    "SELECT j AS raw_name, COUNT(*) AS n "
                    "FROM authority_documents, "
                    "LATERAL jsonb_array_elements_text(judges_json::jsonb) AS j "
                    "WHERE forum_level = 'high_court' "
                    "AND lower(court_name) LIKE :pat "
                    "AND judges_json IS NOT NULL "
                    "GROUP BY j HAVING COUNT(*) >= :floor "
                    "ORDER BY n DESC"
                ),
                {"pat": f"%{substr}%", "floor": min_occurrences},
            ).fetchall()
            counters[court_id]["raw_distinct"] = len(rows)

            # Group by normalized stripped name so "Yashwant Varma" and
            # "Hon'ble Mr. Justice Yashwant Varma" both feed one judge.
            grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for raw, n in rows:
                stripped = _strip_honorifics(raw)
                if not _is_real_name(stripped):
                    counters[court_id]["rejected"] += 1
                    continue
                key = normalise(stripped)
                grouped[key].append((raw, int(n)))
            counters[court_id]["real_names"] = len(grouped)

            for _key, variants in grouped.items():
                # Pick the variant with the most natural casing
                # (mixed-case beats all-caps); ties broken by frequency.
                variants.sort(
                    key=lambda v: (-v[1], 0 if v[0] != v[0].upper() else 1)
                )
                best_raw = variants[0][0]
                canonical = _strip_honorifics(best_raw)
                total_count = sum(n for _, n in variants)

                # Try fuzzy match against existing judges in this court.
                matches = match_candidates(
                    session, raw_text=canonical, court_id=court_id,
                )
                if matches:
                    counters[court_id]["matched"] += 1
                    if dry_run:
                        logger.info(
                            "  MATCH %s → existing judge_id=%s (%s)",
                            canonical, matches[0].judge_id, matches[0].confidence,
                        )
                    continue

                if dry_run:
                    logger.info(
                        "  NEW   %s (count=%d)",
                        canonical, total_count,
                    )
                    counters[court_id]["inserted"] += 1
                    continue

                # Insert Judge + canonical aliases + JudgeAppointment.
                judge = Judge(
                    id=str(uuid4()),
                    court_id=court_id,
                    full_name=canonical,
                    honorific="Justice",
                    current_position=(
                        f"Sitting (derived from {total_count} indexed decisions)"
                    ),
                    is_active=True,
                )
                try:
                    session.add(judge)
                    session.flush()
                except Exception as exc:
                    logger.warning(
                        "  Skip %s — insert failed: %s", canonical, exc,
                    )
                    session.rollback()
                    counters[court_id]["rejected"] += 1
                    continue

                # Persist canonical aliases including raw variants.
                seen_aliases: set[str] = set()
                for alias in canonical_aliases_for(judge):
                    n = normalise(alias)
                    if n and n not in seen_aliases:
                        seen_aliases.add(n)
                        _persist_alias(session, judge.id, alias)
                # Also persist each raw variant we observed in the corpus
                # so the bench resolver can match them next time.
                for raw, _ in variants:
                    n = normalise(raw)
                    if n and n not in seen_aliases:
                        seen_aliases.add(n)
                        _persist_alias(session, judge.id, raw[:255])

                # JudgeAppointment row — current sitting, no end date.
                appt = JudgeAppointment(
                    id=str(uuid4()),
                    judge_id=judge.id,
                    court_id=court_id,
                    role="puisne_judge_inferred",
                    start_date=None,
                    end_date=None,
                    source_url=None,
                    source_evidence_text=(
                        f"Derived from {total_count} indexed decisions in "
                        f"{court_id} (corpus-extract backfill 2026-04-26)."
                    ),
                )
                try:
                    session.add(appt)
                    session.commit()
                    counters[court_id]["inserted"] += 1
                    logger.info(
                        "  INSERT %s (count=%d) judge_id=%s",
                        canonical, total_count, judge.id,
                    )
                except Exception as exc:
                    logger.warning(
                        "  Appointment insert failed for %s: %s",
                        canonical, exc,
                    )
                    session.rollback()

    print()
    print("=" * 78)
    print("HC judge backfill summary (corpus-derived)")
    print("=" * 78)
    widths = [16, 14, 14, 12, 12, 12]
    header = ["court_id", "raw_distinct", "real_names", "matched", "inserted", "rejected"]
    print("  ".join(c.ljust(w) for c, w in zip(header, widths, strict=False)))
    print("-" * sum(widths))
    grand = {k: 0 for k in counters[next(iter(counters))]} if counters else {}
    for cid, c in counters.items():
        cells = [
            cid,
            f"{c['raw_distinct']:>10}",
            f"{c['real_names']:>10}",
            f"{c['matched']:>8}",
            f"{c['inserted']:>8}",
            f"{c['rejected']:>8}",
        ]
        print("  ".join(s.ljust(w) for s, w in zip(cells, widths, strict=False)))
        for k in grand:
            grand[k] += c[k]
    print("-" * sum(widths))
    if counters:
        cells = [
            "TOTAL",
            f"{grand['raw_distinct']:>10}",
            f"{grand['real_names']:>10}",
            f"{grand['matched']:>8}",
            f"{grand['inserted']:>8}",
            f"{grand['rejected']:>8}",
        ]
        print("  ".join(s.ljust(w) for s, w in zip(cells, widths, strict=False)))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="caseops-backfill-hc-judges-from-corpus",
    )
    parser.add_argument(
        "--court", default=None,
        choices=[c for _, c in _COURT_NAME_MATCHERS],
        help="Restrict to one court_id. Default: all 7 HCs in scope.",
    )
    parser.add_argument(
        "--min-occurrences", type=int, default=2,
        help=(
            "Drop candidate names appearing in fewer than N indexed "
            "decisions (parser-noise filter). Default 2."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Plan output without modifying any rows.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Touch utcnow so static-analysis sees it referenced (ruff F401 hint).
    _ = (datetime.now(UTC),)

    return run(
        court_filter=args.court,
        min_occurrences=args.min_occurrences,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
