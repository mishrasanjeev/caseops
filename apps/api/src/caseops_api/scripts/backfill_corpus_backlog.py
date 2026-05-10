"""Drain existing authority-document Layer-2 backlog by priority.

This script intentionally does not ingest from S3. It claims existing
``authority_documents`` rows with ``FOR UPDATE SKIP LOCKED``, runs the
structured metadata extractor, commits one row at a time, and exits on
time, document, or spend limits.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_structured import (
    HAIKU_VERSION,
    LLMProviderError,
    extract_and_persist_structured,
)
from caseops_api.services.llm import LLMDailyCapReachedError, LLMQuotaExhaustedError

logger = logging.getLogger("caseops.backlog")

_INDIC_RE_SQL = (
    r"[\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF"
    r"\u0B00-\u0B7F\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F]"
)
_NON_EN_SUFFIX_RE = (
    r"(_hin|_pun|_ben|_guj|_tam|_tel|_kan|_mal|_ori|_nep|_san|_urd|_asm|_mar)\.pdf$"
)
_CID_RE_SQL = r"\(cid:[0-9]+\)"


PRIORITY_BUCKETS: tuple[tuple[str, str | None, int, str], ...] = (
    ("supreme_court", None, 2024, "sc-2024"),
    ("supreme_court", None, 2023, "sc-2023"),
    ("supreme_court", None, 2022, "sc-2022"),
    ("high_court", "Delhi High Court", 2024, "delhi-hc-2024"),
    ("high_court", "Delhi High Court", 2023, "delhi-hc-2023"),
    ("high_court", "Delhi High Court", 2022, "delhi-hc-2022"),
    ("high_court", "Bombay High Court", 2024, "bombay-hc-2024"),
    ("high_court", "Karnataka High Court", 2024, "karnataka-hc-2024"),
    ("high_court", "Madras High Court", 2024, "madras-hc-2024"),
    ("high_court", "Telangana High Court", 2024, "telangana-hc-2024"),
    ("high_court", "Bombay High Court", 2023, "bombay-hc-2023"),
    ("high_court", "Karnataka High Court", 2023, "karnataka-hc-2023"),
    ("high_court", "Madras High Court", 2023, "madras-hc-2023"),
    ("high_court", "Telangana High Court", 2023, "telangana-hc-2023"),
)


def _priority_case_sql() -> str:
    parts: list[str] = []
    for index, (forum, court, year, _label) in enumerate(PRIORITY_BUCKETS, start=1):
        court_expr = (
            "TRUE"
            if court is None
            else f"court_name = '{court}'"
        )
        parts.append(
            f"WHEN forum_level = '{forum}' AND {court_expr} AND doc_year = {year} THEN {index}"
        )
    return "CASE " + " ".join(parts) + " ELSE NULL END"


def _bucket_label_case_sql() -> str:
    parts: list[str] = []
    for forum, court, year, label in PRIORITY_BUCKETS:
        court_expr = (
            "TRUE"
            if court is None
            else f"court_name = '{court}'"
        )
        parts.append(
            f"WHEN forum_level = '{forum}' AND {court_expr} AND doc_year = {year} THEN '{label}'"
        )
    return "CASE " + " ".join(parts) + " ELSE NULL END"


def _claim_sql() -> str:
    priority_case = _priority_case_sql()
    label_case = _bucket_label_case_sql()
    return f"""
WITH base AS (
  SELECT
    d.id,
    d.forum_level,
    d.court_name,
    d.decision_date,
    d.ingested_at,
    CASE
      WHEN d.source_reference ~ '(?:^|/)([0-9]{{4}})_' THEN
        substring(d.source_reference from '(?:^|/)([0-9]{{4}})_')::int
      WHEN d.source_reference ~ '_([0-9]{{4}})-[0-9]{{2}}-[0-9]{{2}}(?:\\.pdf)?$' THEN
        substring(d.source_reference from '_([0-9]{{4}})-[0-9]{{2}}-[0-9]{{2}}(?:\\.pdf)?$')::int
      WHEN d.decision_date IS NOT NULL THEN extract(year from d.decision_date)::int
      ELSE NULL
    END AS doc_year
  FROM authority_documents d
  WHERE (d.structured_version IS NULL OR d.structured_version < :target_version)
    AND (d.extracted_char_count IS NULL OR d.extracted_char_count < 80000)
    AND EXISTS (
      SELECT 1 FROM authority_document_chunks c
      WHERE c.authority_document_id = d.id
    )
    AND NOT (
      lower(coalesce(d.source_reference, '')) ~ :non_en_suffix
      OR coalesce(d.title, '') ~ :indic_re
      OR substring(coalesce(d.document_text, '') from 1 for 2000) ~ :indic_re
      OR coalesce(d.title, '') ~ :cid_re
      OR substring(coalesce(d.document_text, '') from 1 for 2000) ~ :cid_re
    )
),
candidates AS (
  SELECT
    id,
    {priority_case} AS priority_rank,
    {label_case} AS bucket_label
  FROM base
)
SELECT d.id, c.bucket_label
FROM authority_documents d
JOIN candidates c ON c.id = d.id
WHERE c.priority_rank IS NOT NULL
ORDER BY c.priority_rank ASC, d.decision_date DESC NULLS LAST, d.ingested_at DESC
LIMIT 1
FOR UPDATE OF d SKIP LOCKED
"""


@dataclass
class _WorkerStats:
    done: int = 0
    failures: int = 0
    stop_signals: int = 0
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class _Totals:
    started_at: float
    max_docs: int
    budget_usd: float
    max_runtime_seconds: float
    done: int = 0
    failures: int = 0
    quality_low: int = 0
    spent_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    no_candidate_workers: int = 0
    buckets: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    workers: dict[str, _WorkerStats] = field(default_factory=dict)
    stop_reason: str | None = None


def _claim_next(session: Session) -> tuple[AuthorityDocument, str] | None:
    row = session.execute(
        text(_claim_sql()),
        {
            "target_version": HAIKU_VERSION,
            "indic_re": _INDIC_RE_SQL,
            "non_en_suffix": _NON_EN_SUFFIX_RE,
            "cid_re": _CID_RE_SQL,
        },
    ).first()
    if row is None:
        return None
    doc = session.get(AuthorityDocument, row.id)
    if doc is None:
        return None
    return doc, str(row.bucket_label)


def _time_exhausted(totals: _Totals) -> bool:
    return (time.time() - totals.started_at) >= totals.max_runtime_seconds


def _run_worker(name: str, totals: _Totals, lock: threading.Lock, *, dry_run: bool) -> None:
    SessionFactory = get_session_factory()
    stats = _WorkerStats()
    with lock:
        totals.workers[name] = stats

    while True:
        with lock:
            if totals.stop_reason:
                return
            if totals.done >= totals.max_docs:
                totals.stop_reason = "max_docs"
                return
            if totals.spent_usd >= totals.budget_usd:
                totals.stop_reason = "budget"
                return
            if _time_exhausted(totals):
                totals.stop_reason = "runtime"
                return

        with SessionFactory() as session:
            claimed = _claim_next(session)
            if claimed is None:
                session.rollback()
                with lock:
                    totals.no_candidate_workers += 1
                    if totals.no_candidate_workers >= max(len(totals.workers), 1):
                        totals.stop_reason = "no_candidates"
                return
            doc, bucket_label = claimed
            try:
                summary = extract_and_persist_structured(
                    session, document=doc, tier="haiku"
                )
                if dry_run:
                    session.rollback()
                else:
                    session.commit()
            except (LLMDailyCapReachedError, LLMQuotaExhaustedError, LLMProviderError) as exc:
                logger.warning("worker %s stop signal on %s: %s", name, doc.id, exc)
                session.rollback()
                with lock:
                    stats.stop_signals += 1
                    totals.stop_reason = type(exc).__name__
                return
            except Exception:
                logger.exception("worker %s failed document %s", name, doc.id)
                session.rollback()
                with lock:
                    stats.failures += 1
                    totals.failures += 1
                continue

        with lock:
            stats.done += 1
            stats.cost_usd += summary.cost_usd
            stats.prompt_tokens += summary.prompt_tokens
            stats.completion_tokens += summary.completion_tokens
            totals.done += 1
            totals.spent_usd += summary.cost_usd
            totals.prompt_tokens += summary.prompt_tokens
            totals.completion_tokens += summary.completion_tokens
            totals.buckets[bucket_label] += 1
            if summary.quality_score < 0.5:
                totals.quality_low += 1
            if totals.done % 25 == 0:
                elapsed = max(time.time() - totals.started_at, 1)
                logger.info(
                    "backlog progress: done=%d spent=$%.4f rate=%.2f docs/min buckets=%s",
                    totals.done,
                    totals.spent_usd,
                    totals.done / elapsed * 60,
                    dict(totals.buckets),
                )


def run(*, concurrency: int, max_docs: int, budget_usd: float,
        max_runtime_minutes: float, dry_run: bool = False) -> dict[str, Any]:
    logging.info(
        "starting backlog drain: concurrency=%d max_docs=%d budget=$%.2f runtime=%.1fm dry_run=%s",
        concurrency, max_docs, budget_usd, max_runtime_minutes, dry_run,
    )
    totals = _Totals(
        started_at=time.time(),
        max_docs=max_docs,
        budget_usd=budget_usd,
        max_runtime_seconds=max_runtime_minutes * 60,
    )
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(_run_worker, f"worker-{i+1}", totals, lock, dry_run=dry_run)
            for i in range(concurrency)
        ]
        for future in as_completed(futures):
            future.result()

    elapsed = max(time.time() - totals.started_at, 1)
    return {
        "done": totals.done,
        "failures": totals.failures,
        "quality_low": totals.quality_low,
        "spent_usd": round(totals.spent_usd, 6),
        "prompt_tokens": totals.prompt_tokens,
        "completion_tokens": totals.completion_tokens,
        "docs_per_hour": round(totals.done / elapsed * 3600, 2),
        "cost_per_hour": round(totals.spent_usd / elapsed * 3600, 6),
        "buckets": dict(totals.buckets),
        "stop_reason": totals.stop_reason or "completed",
        "workers": {
            name: {
                "done": stats.done,
                "failures": stats.failures,
                "stop_signals": stats.stop_signals,
                "cost_usd": round(stats.cost_usd, 6),
                "prompt_tokens": stats.prompt_tokens,
                "completion_tokens": stats.completion_tokens,
            }
            for name, stats in sorted(totals.workers.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-backfill-corpus-backlog")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-docs", type=int, default=500)
    parser.add_argument("--budget-usd", type=float, default=50.0)
    parser.add_argument("--max-runtime-minutes", type=float, default=90.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = run(
        concurrency=args.concurrency,
        max_docs=args.max_docs,
        budget_usd=args.budget_usd,
        max_runtime_minutes=args.max_runtime_minutes,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["failures"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
