"""CLI: re-extract Layer-2 titles that leaked PDF page headers.

Usage::

    caseops-reextract-placeholder-titles --tenant aster-demo --budget-usd 5
    caseops-reextract-placeholder-titles --tenant aster-demo --dry-run
    caseops-reextract-placeholder-titles --tenant aster-demo --budget-usd 2 --limit 50

Budget is Haiku spend only. ~$0.006/doc observed in prior passes, so
$5 covers ~800 docs — more than the detector's typical flag count.
Re-running is idempotent; the detector re-reads the current ``title``
each call.

Pipeline this CLI slots into (see the ``corpus-ingest`` skill):

    caseops-reextract-placeholder-titles   ← THIS
    caseops-backfill-title-chunks --refresh  ← rebuilds metadata chunks
    caseops-eval-hnsw-recall ...             ← confirm lift
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Iterable

from sqlalchemy import select

from caseops_api.db.models import Company
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_title_reextract import (
    ReextractReport,
    run_reextract_sweep,
)
from caseops_api.services.llm import AnthropicProvider, build_provider

logger = logging.getLogger("caseops.corpus.reextract")


_HAIKU_MODEL = "claude-haiku-4-5-20251001"


def _resolve_tenant_id(*, slug: str) -> str:
    SessionFactory = get_session_factory()
    with SessionFactory() as s:
        company = s.scalar(select(Company).where(Company.slug == slug))
        if company is None:
            raise SystemExit(f"no company with slug={slug!r}")
        return company.id


def _format_report(report: ReextractReport) -> str:
    lines: list[str] = []
    lines.append("# Placeholder-title re-extract")
    lines.append("")
    lines.append(f"- **attempted**: {report.attempted}")
    lines.append(f"- **accepted**: {report.accepted} (title updated)")
    lines.append(f"- **null returned**: {report.null_returned} (no case name in doc)")
    lines.append(
        f"- **rejected by predicate**: {report.rejected_by_predicate} "
        "(LLM output wasn't a valid case name)"
    )
    lines.append(f"- **llm failed**: {report.llm_failed}")
    lines.append(f"- **total cost**: ${report.total_cost_usd:.3f}")
    if report.skip_reasons:
        lines.append("")
        lines.append("## Skip reasons")
        for reason, count in sorted(report.skip_reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{reason}`: {count}")
    if report.outcomes:
        lines.append("")
        lines.append("## Sample of accepted (first 5)")
        accepted = [o for o in report.outcomes if o.accepted][:5]
        if accepted:
            for o in accepted:
                lines.append(
                    f"- `{o.doc_id[:8]}` · {o.old_title!r} → {o.new_title!r}"
                )
        else:
            lines.append("_none_")
    return "\n".join(lines) + "\n"


def run(
    *,
    tenant_slug: str,
    budget_usd: float,
    limit: int,
    dry_run: bool,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    tenant_id = _resolve_tenant_id(slug=tenant_slug)

    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        if dry_run:
            report = run_reextract_sweep(
                session,
                provider=None,  # type: ignore[arg-type] -- unused in dry-run
                tenant_id=tenant_id,
                budget_usd=0.0,
                limit=limit,
                dry_run=True,
            )
        else:
            # Always Haiku for this pass — metadata extraction is cheap
            # and reliable on short inputs; Sonnet is overkill.
            from caseops_api.core.settings import get_settings
            settings = get_settings()
            if (settings.llm_provider or "").lower() != "anthropic":
                raise SystemExit(
                    "re-extract needs CASEOPS_LLM_PROVIDER=anthropic + api key"
                )
            if not settings.llm_api_key:
                # Belt-and-braces: build_provider would complain too.
                raise SystemExit("CASEOPS_LLM_API_KEY is not set")
            provider = AnthropicProvider(
                model=_HAIKU_MODEL,
                api_key=settings.llm_api_key,
                prompt_cache=bool(
                    getattr(settings, "llm_prompt_cache_enabled", True)
                ),
            )
            _ = build_provider  # silence unused-import; handy to keep for callers
            report = run_reextract_sweep(
                session,
                provider=provider,
                tenant_id=tenant_id,
                budget_usd=budget_usd,
                limit=limit,
                dry_run=False,
            )

    sys.stdout.write(_format_report(report))
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-reextract-placeholder-titles")
    parser.add_argument(
        "--tenant", required=True,
        help="Company slug for attribution (not a tenancy filter — the "
             "corpus is global).",
    )
    parser.add_argument(
        "--budget-usd", type=float, default=5.0,
        help="Haiku spend cap (default $5). Sweep stops when reached.",
    )
    parser.add_argument(
        "--limit", type=int, default=1000,
        help="Max docs to consider in a single run (default 1000). "
             "The detector is cheap; this is a safety rail.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count flagged docs + reason breakdown without spending tokens.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    _ = json  # silence unused-import (used by service logging).
    return run(
        tenant_slug=args.tenant,
        budget_usd=args.budget_usd,
        limit=args.limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
