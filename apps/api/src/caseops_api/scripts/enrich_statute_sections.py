"""Backfill statute_sections.section_text via the hybrid scrape →
Haiku-fallback pipeline.

Per docs/PRD_STATUTE_MODEL_2026-04-25.md + 2026-04-26 user decision.

CLI:
    python -m caseops_api.scripts.enrich_statute_sections
    python -m caseops_api.scripts.enrich_statute_sections --statute ipc-1860
    python -m caseops_api.scripts.enrich_statute_sections \\
        --statute ipc-1860 --budget-usd 5 --no-haiku
    python -m caseops_api.scripts.enrich_statute_sections --dry-run

Per-Act ``--budget-usd`` cap (default $5/Act) gates the Haiku fallback
to prevent a single bad-prompt run from burning the entire monthly
budget. The cap is enforced via ``ModelRun`` SUM of completion+prompt
tokens × the configured price; when the cap is reached, remaining
sections in that Act are left NULL and the loop moves to the next
Act.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from caseops_api.db.models import ModelRun, Statute, StatuteSection
from caseops_api.db.session import get_session_factory
from caseops_api.services.llm import PURPOSE_METADATA_EXTRACT
from caseops_api.services.statute_enrichment import (
    SOURCE_HAIKU,
    SOURCE_INDIACODE,
    enrich_section,
)

logger = logging.getLogger("enrich_statute_sections")

# Approximate per-token cost for the Haiku 4.5 budget gate. Calibrated
# against Anthropic's published Apr-2026 pricing of $0.80/M input +
# $4/M output. We blend at $1.20/M as a coarse single-rate so the cap
# math stays one-line.
_HAIKU_BLENDED_USD_PER_M_TOKENS = 1.2


def _haiku_spend_today_for_purpose(session, purpose: str) -> float:
    day_start = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    total_tokens = session.scalar(
        select(
            func.coalesce(
                func.sum(ModelRun.prompt_tokens + ModelRun.completion_tokens),
                0,
            )
        )
        .where(ModelRun.purpose == purpose)
        .where(ModelRun.created_at >= day_start)
    ) or 0
    return float(total_tokens) / 1_000_000.0 * _HAIKU_BLENDED_USD_PER_M_TOKENS


def _haiku_spend_window(session, purpose: str, *, hours: int) -> float:
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    total_tokens = session.scalar(
        select(
            func.coalesce(
                func.sum(ModelRun.prompt_tokens + ModelRun.completion_tokens),
                0,
            )
        )
        .where(ModelRun.purpose == purpose)
        .where(ModelRun.created_at >= cutoff)
    ) or 0
    return float(total_tokens) / 1_000_000.0 * _HAIKU_BLENDED_USD_PER_M_TOKENS


def run(
    *,
    statute_filter: list[str] | None,
    budget_usd: float,
    allow_haiku: bool,
    dry_run: bool,
    limit_per_statute: int | None,
) -> int:
    factory = get_session_factory()
    counters: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "scraped": 0, "haiku": 0, "skipped_budget": 0,
            "failed": 0, "already_filled": 0,
        }
    )
    with factory() as session:
        statutes_q = select(Statute).order_by(Statute.id)
        if statute_filter:
            statutes_q = statutes_q.where(Statute.id.in_(statute_filter))
        statutes = list(session.scalars(statutes_q))
        if not statutes:
            print("no statutes match the filter", file=sys.stderr)
            return 2

        with httpx.Client(
            timeout=15.0,
            headers={"User-Agent": "CaseOps/1.0 (statute-enrichment)"},
            follow_redirects=True,
        ) as client:
            for st in statutes:
                act_label = f"{st.id} ({st.short_name})"
                # Per-Act window spend. Reset by treating each Act run
                # in its own slot of the global ModelRun ledger; we
                # snapshot the spend at the start so within-Act burn
                # is easy to compute.
                spend_at_act_start = _haiku_spend_today_for_purpose(
                    session, PURPOSE_METADATA_EXTRACT,
                )
                logger.info(
                    "ACT START %s (today's metadata_extract spend so far: "
                    "$%.4f, this-Act budget: $%.2f)",
                    act_label, spend_at_act_start, budget_usd,
                )

                sections_q = (
                    select(StatuteSection)
                    .where(StatuteSection.statute_id == st.id)
                    .where(StatuteSection.is_active.is_(True))
                    .where(StatuteSection.section_text.is_(None))
                    .order_by(StatuteSection.ordinal, StatuteSection.section_number)
                )
                if limit_per_statute is not None:
                    sections_q = sections_q.limit(limit_per_statute)
                sections = list(session.scalars(sections_q))
                logger.info(
                    "ACT %s: %d sections need enrichment",
                    act_label, len(sections),
                )

                for sec in sections:
                    # Per-Act budget gate (Haiku side). Scrape is free;
                    # check budget only when we'd fall through to Haiku.
                    spend_now = _haiku_spend_today_for_purpose(
                        session, PURPOSE_METADATA_EXTRACT,
                    )
                    spent_this_act = spend_now - spend_at_act_start
                    if allow_haiku and spent_this_act >= budget_usd:
                        counters[st.id]["skipped_budget"] += 1
                        logger.info(
                            "BUDGET-CAP %s sec=%s — this-Act haiku spend $%.4f >= cap $%.2f",
                            act_label, sec.section_number,
                            spent_this_act, budget_usd,
                        )
                        # Keep iterating in case a later section
                        # scrapes (free); only Haiku is gated.
                        result = enrich_section(
                            session, sec, statute=st, http_client=client,
                            allow_haiku=False,
                        )
                    else:
                        if dry_run:
                            logger.info(
                                "DRY-RUN would enrich %s sec=%s",
                                act_label, sec.section_number,
                            )
                            continue
                        result = enrich_section(
                            session, sec, statute=st, http_client=client,
                            allow_haiku=allow_haiku,
                        )

                    if result.source == SOURCE_INDIACODE:
                        counters[st.id]["scraped"] += 1
                    elif result.source == SOURCE_HAIKU:
                        counters[st.id]["haiku"] += 1
                    elif result.source is None:
                        counters[st.id]["failed"] += 1
                    logger.info(
                        "  sec=%s → %s (%s)",
                        sec.section_number,
                        result.source or "FAILED",
                        result.notes or "",
                    )

                spend_after_act = _haiku_spend_today_for_purpose(
                    session, PURPOSE_METADATA_EXTRACT,
                )
                logger.info(
                    "ACT END %s — scraped=%d haiku=%d skipped_budget=%d "
                    "failed=%d (this-Act haiku spend: $%.4f)",
                    act_label,
                    counters[st.id]["scraped"],
                    counters[st.id]["haiku"],
                    counters[st.id]["skipped_budget"],
                    counters[st.id]["failed"],
                    spend_after_act - spend_at_act_start,
                )

    # Summary table
    print()
    print("=" * 78)
    print("Statute enrichment summary")
    print("=" * 78)
    widths = [22, 10, 10, 16, 10]
    header = ["statute_id", "scraped", "haiku", "skipped_budget", "failed"]
    print("  ".join(c.ljust(w) for c, w in zip(header, widths, strict=False)))
    print("-" * sum(widths))
    grand = {"scraped": 0, "haiku": 0, "skipped_budget": 0, "failed": 0}
    for sid, c in counters.items():
        cells = [
            sid,
            f"{c['scraped']:>6}",
            f"{c['haiku']:>6}",
            f"{c['skipped_budget']:>6}",
            f"{c['failed']:>6}",
        ]
        print("  ".join(s.ljust(w) for s, w in zip(cells, widths, strict=False)))
        for k in grand:
            grand[k] += c[k]
    print("-" * sum(widths))
    cells = [
        "TOTAL",
        f"{grand['scraped']:>6}",
        f"{grand['haiku']:>6}",
        f"{grand['skipped_budget']:>6}",
        f"{grand['failed']:>6}",
    ]
    print("  ".join(s.ljust(w) for s, w in zip(cells, widths, strict=False)))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(prog="caseops-enrich-statute-sections")
    parser.add_argument(
        "--statute", action="append", default=None,
        help=(
            "Restrict to a specific statute id (e.g. ipc-1860). Repeat "
            "to enrich multiple Acts. Default: all 7 Acts."
        ),
    )
    parser.add_argument(
        "--budget-usd", type=float, default=5.0,
        help="Per-Act USD ceiling for Haiku fallback (default $5).",
    )
    parser.add_argument(
        "--no-haiku", action="store_true",
        help="Scrape only; never call Haiku. Useful for a first pass.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Plan output without modifying any rows.",
    )
    parser.add_argument(
        "--limit-per-statute", type=int, default=None,
        help="Cap number of sections per Act (testing aid).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        statute_filter=args.statute,
        budget_usd=args.budget_usd,
        allow_haiku=not args.no_haiku,
        dry_run=args.dry_run,
        limit_per_statute=args.limit_per_statute,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
