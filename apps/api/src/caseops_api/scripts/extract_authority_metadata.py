"""CLI: LLM-extract structured metadata over the authority corpus.

Backfills neutral_citation, case_reference, bench_name, parties, and a
corrected decision_date on rows where these are missing. Safe to re-run
— rows whose neutral_citation OR case_reference is already populated
are skipped unless ``--force`` is set.

Usage::

    uv run caseops-extract-authority-metadata --limit 5          # trial
    uv run caseops-extract-authority-metadata --concurrency 8    # full run

Network, cost, and time:

- Each row sends ~3 KB of document text to the configured LLM provider
  (``CASEOPS_LLM_PROVIDER``) — default Haiku.
- Rows are processed concurrently (``--concurrency``, default 6).
- A failed extraction logs and moves on; the row is left untouched so
  a re-run will pick it up.

The per-document JSON contract is defined by ``_Extracted`` below; any
response that fails validation is recorded as an error, not silently
forced into the row.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select

from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory
from caseops_api.services.llm import (
    PURPOSE_METADATA_EXTRACT,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    build_provider,
)

logger = logging.getLogger("extract_authority_metadata")

HEAD_CHARS = 2800
TAIL_CHARS = 1600
MAX_PARTIES = 6


class _Extracted(BaseModel):
    neutral_citation: str | None = Field(default=None, max_length=200)
    case_reference: str | None = Field(default=None, max_length=200)
    bench: list[str] = Field(default_factory=list, max_length=8)
    parties: list[str] = Field(default_factory=list, max_length=MAX_PARTIES)
    decision_date: str | None = Field(default=None, max_length=20)  # YYYY-MM-DD


SYSTEM = (
    "You extract structured metadata from Indian High Court and Supreme "
    "Court judgment texts. Respond with strict JSON only, no prose, no "
    "markdown fences. Fields you do not find MUST be null (or an empty "
    "list for array fields). Do not invent. Only emit values that appear "
    "verbatim or nearly verbatim in the supplied text."
)

USER_RULES = (
    'Extract the following fields and return JSON:\n'
    '{\n'
    '  "neutral_citation": string | null,  // e.g. "2023:DHC:8921" or "(2022) 10 SCC 51"\n'  # noqa: E501
    '  "case_reference":   string | null,  // e.g. "ITA No.7/2023", "CRL.M.C. 1234/2024"\n'  # noqa: E501
    '  "bench":            string[],       // judge names without titles; up to 8\n'
    f'  "parties":          string[],       // up to {MAX_PARTIES} names, petitioner first\n'  # noqa: E501
    '  "decision_date":    string | null   // ISO YYYY-MM-DD; judgment or order date\n'  # noqa: E501
    '}\n\n'
    'Rules:\n'
    '- neutral_citation is the court stamp (e.g. 2024:DHC:NNNN or 2023 INSC NNN); null if not present.\n'  # noqa: E501
    '- case_reference is the internal case number (ITA, CRL.M.C., W.P.(C), SLP, etc.).\n'
    '- bench: only the judges who authored or concurred. Omit counsel.\n'
    '- parties: the core entity names, not addresses or epithets like "Petitioner".\n'
    '- decision_date is the pronouncement date. Prefer explicit dates over "Signing Date" footers.\n'  # noqa: E501
    '- Do not include advocates, clerks, or court staff.\n'
)


def _build_user_prompt(head: str, tail: str) -> str:
    return (
        USER_RULES
        + "\n=== DOCUMENT HEAD ===\n"
        + head
        + "\n\n=== DOCUMENT TAIL ===\n"
        + tail
        + "\n"
    )


_stats_lock = threading.Lock()
_stats = {
    "processed": 0,
    "updated": 0,
    "skipped_no_text": 0,
    "llm_error": 0,
    "parse_error": 0,
    "nothing_to_set": 0,
    "started_at": 0.0,
}


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("\n", 1)[0]
    return cleaned.strip("`").strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", value)
    if match:
        y, m, d = (int(g) for g in match.groups())
        try:
            return date(y, m, d)
        except ValueError:
            return None
    return None


def _fetch_targets(
    limit: int | None, force: bool, only_missing: str | None
) -> list[str]:
    """Returns a list of document ids. We fetch ids only so the big
    document_text payload is not kept in memory for the worker pool."""
    Session = get_session_factory()
    with Session() as s:
        stmt = select(AuthorityDocument.id).order_by(AuthorityDocument.created_at)
        if not force:
            if only_missing == "citation":
                stmt = stmt.where(AuthorityDocument.neutral_citation.is_(None))
            else:
                stmt = stmt.where(
                    or_(
                        AuthorityDocument.neutral_citation.is_(None),
                        AuthorityDocument.case_reference.is_(None),
                    )
                )
        if limit is not None:
            stmt = stmt.limit(limit)
        return [row[0] for row in s.execute(stmt).all()]


def _extract_one(doc_id: str, provider: LLMProvider) -> dict:
    Session = get_session_factory()
    with Session() as s:
        doc = s.get(AuthorityDocument, doc_id)
        if doc is None:
            return {"ok": False, "reason": "doc_gone"}
        text = doc.document_text or ""
        if len(text) < 200:
            with _stats_lock:
                _stats["skipped_no_text"] += 1
            return {"ok": False, "reason": "no_text"}
        head = text[:HEAD_CHARS]
        tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
        prompt = _build_user_prompt(head, tail)

        try:
            completion = provider.generate(
                messages=[
                    LLMMessage(role="system", content=SYSTEM),
                    LLMMessage(role="user", content=prompt),
                ],
                temperature=0.0,
                max_tokens=512,
            )
        except LLMProviderError as exc:
            with _stats_lock:
                _stats["llm_error"] += 1
            logger.warning("llm error on %s: %s", doc_id, exc)
            return {"ok": False, "reason": "llm_error"}

        raw = _strip_code_fence(completion.text)
        try:
            payload = json.loads(raw)
            parsed = _Extracted.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            with _stats_lock:
                _stats["parse_error"] += 1
            logger.warning("parse error on %s: %s", doc_id, exc)
            return {"ok": False, "reason": "parse_error"}

        updates: dict = {}
        if parsed.neutral_citation and not doc.neutral_citation:
            updates["neutral_citation"] = parsed.neutral_citation.strip()[:250]
        if parsed.case_reference and not doc.case_reference:
            updates["case_reference"] = parsed.case_reference.strip()[:250]
        bench_joined = ", ".join(parsed.bench).strip()
        if bench_joined and not doc.bench_name:
            updates["bench_name"] = bench_joined[:250]
        parsed_date = _parse_date(parsed.decision_date)
        if parsed_date is not None and (
            doc.decision_date is None or doc.decision_date.year == 3100  # known bad
        ):
            updates["decision_date"] = parsed_date

        parties_title: str | None = None
        if parsed.parties:
            parties_title = " vs ".join(p.strip() for p in parsed.parties[:2] if p.strip())
        if parties_title and (
            not doc.title
            or doc.title.strip().lower().startswith("in the high court")
            or doc.title.strip().lower().startswith("in  the  high  court")
            or doc.title.strip() == "This is a digitally signed order."
        ):
            updates["title"] = parties_title[:250]

        if not updates:
            with _stats_lock:
                _stats["nothing_to_set"] += 1
            return {"ok": True, "updated": False}

        for key, value in updates.items():
            setattr(doc, key, value)
        s.commit()
        with _stats_lock:
            _stats["updated"] += 1
        return {"ok": True, "updated": True, "fields": list(updates.keys())}


def _progress_ticker(total: int) -> None:
    while True:
        time.sleep(15)
        with _stats_lock:
            done = _stats["processed"]
            updated = _stats["updated"]
            errs = _stats["llm_error"] + _stats["parse_error"]
            elapsed = time.time() - _stats["started_at"]
        if done >= total:
            return
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else float("inf")
        logger.info(
            "progress: %d/%d (%.1f%%) updated=%d err=%d rate=%.2f/s eta=%.0fs",
            done, total, 100.0 * done / total, updated, errs, rate, eta,
        )


def run(
    *,
    limit: int | None,
    concurrency: int,
    force: bool,
    only_missing: str | None,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ids = _fetch_targets(limit=limit, force=force, only_missing=only_missing)
    total = len(ids)
    logger.info("targets: %d documents", total)
    if total == 0:
        return 0

    provider = build_provider(purpose=PURPOSE_METADATA_EXTRACT)
    logger.info("provider: %s model=%s", provider.name, provider.model)

    with _stats_lock:
        _stats["started_at"] = time.time()

    ticker = threading.Thread(target=_progress_ticker, args=(total,), daemon=True)
    ticker.start()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_extract_one, doc_id, provider) for doc_id in ids]
        for fut in as_completed(futures):
            with _stats_lock:
                _stats["processed"] += 1
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.exception("unexpected failure: %s", exc)

    elapsed = time.time() - _stats["started_at"]
    logger.info(
        "done: processed=%d updated=%d no_text=%d llm_err=%d parse_err=%d "
        "nothing_to_set=%d elapsed=%.0fs",
        _stats["processed"],
        _stats["updated"],
        _stats["skipped_no_text"],
        _stats["llm_error"],
        _stats["parse_error"],
        _stats["nothing_to_set"],
        elapsed,
    )
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-extract-authority-metadata")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N rows.")
    parser.add_argument(
        "--concurrency", type=int, default=6, help="Parallel LLM calls (default 6)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if neutral_citation is already set.",
    )
    parser.add_argument(
        "--only-missing",
        choices=["citation", "any"],
        default="any",
        help=(
            "Filter target rows: only those missing the citation field, "
            "or any of citation/case_ref."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        limit=args.limit,
        concurrency=args.concurrency,
        force=args.force,
        only_missing=args.only_missing,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
