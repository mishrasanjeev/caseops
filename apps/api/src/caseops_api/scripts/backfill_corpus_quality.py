"""Corpus quality backfill for pre-Layer-2 documents.

Three jobs:

1. ``clean`` — rewrite stale titles and blank fake Jan-1 dates on the
   existing ~13.9 K authority_documents. No LLM cost.

2. ``structured`` — run the Layer-2 structured extraction pass with a
   budget-aware triage router:

   - Route SC 1990-2025 English-only judgments (~2,100 docs) to
     Sonnet 4.6 (premium tier, ~$0.07/doc).
   - Route everything else (~11,800 docs) to Haiku 4.5 (budget tier,
     ~$0.023/doc).
   - Abort the run when cumulative USD spend crosses ``--budget-usd``.

3. ``all`` — run ``clean`` then ``structured`` in one shot.

Run modes::

    # Pure-code pass (no LLM cost) — title + date cleanup
    caseops-backfill-corpus-quality --stage clean

    # Triage router — Sonnet on SC 1990+ EN, Haiku everywhere else
    caseops-backfill-corpus-quality --stage structured --budget-usd 468

    # Force a single tier (debug / manual top-ups)
    caseops-backfill-corpus-quality --stage structured --force-tier haiku
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_ingest import (
    _derive_title,
    _guess_decision_date,
)
from caseops_api.services.corpus_structured import (
    HAIKU_VERSION,
    SONNET_VERSION,
    extract_and_persist_structured,
)

logger = logging.getLogger("caseops.backfill")

# Year encoded as the leading 4 digits of the filename stem, produced
# by the ecourts adapter (e.g. ``2025_12_593_610_EN.pdf``).
_YEAR_RE = re.compile(r"(?:^|/)(\d{4})_")
_BUDGET_LOG_PATH = Path("tmp/structured_budget.json")


def _clean_titles_and_dates(session: Session, *, dry_run: bool) -> tuple[int, int]:
    """Rewrite titles/dates on every doc whose text is available.

    Returns (titles_updated, dates_blanked).
    """
    titles_updated = 0
    dates_blanked = 0
    stmt = (
        select(AuthorityDocument)
        .where(AuthorityDocument.document_text.is_not(None))
    )
    docs = session.scalars(stmt).all()
    logger.info("scanning %d docs for title/date cleanup", len(docs))
    for doc in docs:
        text = doc.document_text or ""
        new_title = _derive_title(_FakePath(doc.source_reference or doc.id), text)
        if new_title and new_title != doc.title:
            doc.title = new_title[:255]
            titles_updated += 1
        dd = doc.decision_date
        if dd is not None and dd.month == 1 and dd.day == 1:
            default_year = dd.year
            parsed = _guess_decision_date(text, default_year=default_year)
            if parsed is None or (
                parsed.month == 1 and parsed.day == 1 and parsed.year == default_year
            ):
                doc.decision_date = None
                dates_blanked += 1
            else:
                doc.decision_date = parsed
    if not dry_run:
        session.flush()
    return titles_updated, dates_blanked


class _FakePath:
    """Shim so ``_derive_title`` (which expects a ``Path``) works with
    just a ``source_reference`` string. We only need ``stem``."""

    def __init__(self, reference: str) -> None:
        self._ref = reference

    @property
    def stem(self) -> str:
        name = self._ref.rsplit("/", 1)[-1]
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        return name


def _year_for_doc(doc: AuthorityDocument) -> int | None:
    """Decode the filename year from ``source_reference`` (e.g.
    ``2025_12_593_610_EN.pdf`` → 2025). Returns None if absent."""
    ref = doc.source_reference or ""
    m = _YEAR_RE.search("/" + ref)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _tier_for_doc(doc: AuthorityDocument) -> str:
    """Default-route every document to Haiku.

    The previous Sonnet-tier promotion (SC + English + 1980-2025) was
    burning ~$120/day during sweeps and accounted for $855 of the
    Apr 18-26 Anthropic bill — without a measurable retrieval-quality
    delta in the eval probes. Haiku is now the default; pass
    ``--force-tier sonnet`` to re-enable premium routing for an
    explicit, time-boxed run.
    """
    return "haiku"


def _already_covered_at_tier(doc: AuthorityDocument, tier: str) -> bool:
    v = doc.structured_version
    if v is None:
        return False
    if tier == "sonnet":
        return v >= SONNET_VERSION
    return v >= HAIKU_VERSION


def _emit_budget_snapshot(totals: dict) -> None:
    try:
        _BUDGET_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BUDGET_LOG_PATH.write_text(
            json.dumps(totals, indent=2, default=str), encoding="utf-8"
        )
    except OSError:
        pass


def _structured_pass(
    session: Session,
    *,
    limit: int | None,
    dry_run: bool,
    budget_usd: float,
    force_tier: str | None,
    year_range: tuple[int, int] | None,
) -> dict:
    """Triage router over every doc that still needs structured data.

    Order: Sonnet-tier candidates first (they carry the most value per
    dollar), then the Haiku tier. Within each tier, descending
    chronological order so recent judgments are covered before older
    ones if the budget runs out.

    ``year_range`` (lo, hi inclusive): when set, only Sonnet candidates
    whose filename year falls in [lo, hi] are processed, and the Haiku
    bucket is skipped entirely. This is the per-bucket workflow — run
    SC 2020-2025 first, audit, then SC 2015-2019, etc.
    """
    # Candidate set: anything below the target tier's stamp.
    stmt = (
        select(AuthorityDocument)
        .where(
            (AuthorityDocument.structured_version.is_(None))
            | (AuthorityDocument.structured_version < SONNET_VERSION)
        )
        # Skip monster judgments whose structured-extraction output
        # reliably exceeds Haiku / Sonnet max_tokens (16384) — they
        # return malformed JSON on every attempt, burn tokens, and
        # never persist. 80,000 chars ≈ 20k input tokens + ~25 chunks,
        # which is the point where we see >90 % JSON-parse failures on
        # both models. These docs need a chunked-output extractor;
        # queueing them here just wastes budget.
        .where(
            (AuthorityDocument.extracted_char_count.is_(None))
            | (AuthorityDocument.extracted_char_count < 80000)
        )
        .order_by(
            AuthorityDocument.decision_date.desc().nulls_last(),
            AuthorityDocument.ingested_at.desc(),
        )
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    all_docs = session.scalars(stmt).all()

    # Partition into buckets. Sonnet first — premium budget is the
    # binding constraint, so we spend that ink deliberately and in
    # chronological-priority order.
    sonnet_bucket: list[AuthorityDocument] = []
    haiku_bucket: list[AuthorityDocument] = []
    for doc in all_docs:
        tier = force_tier or _tier_for_doc(doc)
        if _already_covered_at_tier(doc, tier):
            continue
        if tier == "sonnet":
            if year_range is not None:
                year = _year_for_doc(doc)
                if year is None or not (year_range[0] <= year <= year_range[1]):
                    continue
            sonnet_bucket.append(doc)
        else:
            haiku_bucket.append(doc)

    # Sort sonnet bucket by filename year DESC so 2025 lands before
    # 2020 inside a multi-year bucket. NULL-dated docs without a
    # filename year are dropped to the end via -inf.
    sonnet_bucket.sort(
        key=lambda d: _year_for_doc(d) or -1,
        reverse=True,
    )

    if year_range is not None:
        logger.info(
            "year-range %d-%d: %d sonnet candidates (Haiku bucket skipped), budget=$%.2f",
            year_range[0], year_range[1], len(sonnet_bucket), budget_usd,
        )
        haiku_bucket = []
    else:
        logger.info(
            "triage: %d sonnet candidates, %d haiku candidates, budget=$%.2f",
            len(sonnet_bucket), len(haiku_bucket), budget_usd,
        )

    totals = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "budget_usd": budget_usd,
        "spent_usd": 0.0,
        "sonnet": {"done": 0, "cost_usd": 0.0, "candidates": len(sonnet_bucket)},
        "haiku": {"done": 0, "cost_usd": 0.0, "candidates": len(haiku_bucket)},
        "failures": 0,
        "quality_low": 0,
    }

    def _run_bucket(bucket: list[AuthorityDocument], tier: str) -> bool:
        """Returns True if the bucket finished, False if budget was hit."""
        t0 = time.time()
        for i, doc in enumerate(bucket, start=1):
            if totals["spent_usd"] >= budget_usd:
                logger.warning(
                    "budget ceiling $%.2f reached; stopping %s tier at %d/%d",
                    budget_usd, tier, i - 1, len(bucket),
                )
                return False
            try:
                summary = extract_and_persist_structured(
                    session, document=doc, tier=tier,
                )
            except Exception:
                logger.exception(
                    "structured extraction failed for %s (tier=%s)",
                    doc.id, tier,
                )
                session.rollback()
                totals["failures"] += 1
                continue
            if not dry_run:
                session.commit()
            totals[tier]["done"] += 1
            totals[tier]["cost_usd"] += summary.cost_usd
            totals["spent_usd"] += summary.cost_usd
            if summary.quality_score < 0.5:
                totals["quality_low"] += 1
                logger.info(
                    "low quality (%.2f) on %s: %s",
                    summary.quality_score, doc.id, list(summary.quality_issues),
                )
            if i % 10 == 0:
                rate = i / max(time.time() - t0, 1e-6)
                logger.info(
                    "[%s] %d/%d done  spent=$%.2f  %.2f/s  last_model=%s",
                    tier, i, len(bucket), totals["spent_usd"], rate, summary.model,
                )
                _emit_budget_snapshot(totals)
        _emit_budget_snapshot(totals)
        return True

    finished = True
    if sonnet_bucket:
        finished = _run_bucket(sonnet_bucket, "sonnet")
    if finished and haiku_bucket:
        _run_bucket(haiku_bucket, "haiku")

    totals["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _emit_budget_snapshot(totals)
    return totals


def _parse_year_range(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    parts = value.replace(":", "-").split("-")
    if len(parts) != 2:
        raise SystemExit(f"--year-range must be YYYY-YYYY (got {value!r})")
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise SystemExit(f"--year-range must be YYYY-YYYY (got {value!r})") from exc
    lo, hi = (a, b) if a <= b else (b, a)
    return lo, hi


def run(
    *,
    stage: str,
    limit: int | None,
    dry_run: bool,
    budget_usd: float,
    force_tier: str | None,
    year_range: tuple[int, int] | None,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        if stage in ("clean", "all"):
            titles, dates = _clean_titles_and_dates(session, dry_run=dry_run)
            sys.stdout.write(
                f"clean-pass: titles_updated={titles} dates_blanked={dates}\n"
            )
            if not dry_run:
                session.commit()
        if stage in ("structured", "all"):
            totals = _structured_pass(
                session,
                limit=limit, dry_run=dry_run,
                budget_usd=budget_usd, force_tier=force_tier,
                year_range=year_range,
            )
            sys.stdout.write(
                "structured-pass: "
                f"sonnet_done={totals['sonnet']['done']}/{totals['sonnet']['candidates']} "
                f"(${totals['sonnet']['cost_usd']:.2f}) "
                f"haiku_done={totals['haiku']['done']}/{totals['haiku']['candidates']} "
                f"(${totals['haiku']['cost_usd']:.2f}) "
                f"total=${totals['spent_usd']:.2f} "
                f"failures={totals['failures']} quality_low={totals['quality_low']}\n"
            )
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-backfill-corpus-quality")
    parser.add_argument(
        "--stage",
        choices=["clean", "structured", "all"],
        default="all",
        help=(
            "clean = rewrite titles + blank fake dates (no LLM). "
            "structured = run the triage structured-extraction pass. "
            "all = both, in order."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap the structured pass to N candidate docs.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute rewrites / annotations but do not commit.",
    )
    parser.add_argument(
        "--budget-usd", type=float, default=468.0,
        help="Hard USD ceiling for the structured pass (default $468).",
    )
    parser.add_argument(
        "--force-tier", choices=["haiku", "sonnet"], default=None,
        help="Override the triage router and run every doc at this tier.",
    )
    parser.add_argument(
        "--year-range", default=None,
        help=(
            "Restrict the Sonnet pass to filename-year YYYY-YYYY (inclusive); "
            "Haiku bucket is skipped. Use for per-bucket workflow, e.g. "
            "--year-range 2020-2025."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        stage=args.stage, limit=args.limit, dry_run=args.dry_run,
        budget_usd=args.budget_usd, force_tier=args.force_tier,
        year_range=_parse_year_range(args.year_range),
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
