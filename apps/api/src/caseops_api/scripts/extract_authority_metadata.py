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
from sqlalchemy import or_, select, text

from caseops_api.db.models import AuthorityDocument, ModelRun
from caseops_api.db.session import get_session_factory
from caseops_api.services.llm import (
    PURPOSE_METADATA_EXTRACT,
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    build_provider,
)

logger = logging.getLogger("extract_authority_metadata")

HEAD_CHARS = 2800
TAIL_CHARS = 1600
MAX_PARTIES = 6

# Phase B audit gap (2026-04-23): every Anthropic Opus call is now
# recorded as a ``ModelRun`` row so corpus spend is finally visible
# on the same audit table the production AI surfaces use. Cost cap:
# the worker periodically sums the last 24h of metadata-extract
# spend and halts if it exceeds CASEOPS_LAYER2_DAILY_USD_CAP
# (default $100). Bypasses are explicit:
#
#   CASEOPS_LAYER2_DAILY_USD_CAP=0   # disable cap entirely (unsafe)
#   CASEOPS_LAYER2_DAILY_USD_CAP=200 # raise to $200
#
# Anthropic public Opus pricing per million tokens (no prompt-cache
# discount applied — the cap is conservative on purpose). Update
# these constants if Anthropic changes pricing.
_OPUS_USD_PER_M_INPUT = 15.0
_OPUS_USD_PER_M_OUTPUT = 75.0
# Sonnet / Haiku rates roughly an order of magnitude lower; the
# default model for this purpose is Haiku per
# CASEOPS_LLM_MODEL_METADATA_EXTRACT, but the live corpus sweep
# uses Opus. Falling back to Opus rates means the cap is on the
# safe side regardless of actual model.
_DEFAULT_DAILY_USD_CAP = 100.0
_HALT_FLAG = threading.Event()
# Re-check the cap every N completed extractions so a runaway cannot
# overshoot by more than a few seconds of throughput.
_CAP_CHECK_EVERY_N = 50
_processed_since_cap_check = 0
_cap_check_lock = threading.Lock()


def _layer2_daily_cap_usd() -> float:
    raw = (
        # Allow ops to override without redeploying.
        __import__("os").environ.get("CASEOPS_LAYER2_DAILY_USD_CAP")
    )
    if raw is None:
        return _DEFAULT_DAILY_USD_CAP
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "CASEOPS_LAYER2_DAILY_USD_CAP=%r is not numeric; using default $%.2f",
            raw, _DEFAULT_DAILY_USD_CAP,
        )
        return _DEFAULT_DAILY_USD_CAP


def _spend_last_24h_usd(session) -> float:
    """Sum tokens from model_runs for purpose='metadata_extract' in
    the last 24 hours and convert to USD at Opus rates. Returns 0.0
    if the query fails (DB blip should not crash the cap check)."""
    try:
        row = session.execute(text(
            "SELECT COALESCE(SUM(prompt_tokens), 0) AS pin, "
            "       COALESCE(SUM(completion_tokens), 0) AS cout "
            "FROM model_runs WHERE purpose = :purpose "
            "AND created_at > NOW() - INTERVAL '24 hours'"
        ), {"purpose": "metadata_extract"}).one()
        in_usd = (row.pin or 0) * _OPUS_USD_PER_M_INPUT / 1_000_000
        out_usd = (row.cout or 0) * _OPUS_USD_PER_M_OUTPUT / 1_000_000
        return in_usd + out_usd
    except Exception as exc:  # noqa: BLE001 — cap is best-effort
        logger.warning("daily-cap query failed (ignoring): %s", exc)
        return 0.0


def _record_model_run(
    session,
    *,
    completion: LLMCompletion,
    status: str = "ok",
    error: str | None = None,
) -> None:
    """Persist one ModelRun row. company_id / matter_id /
    actor_membership_id are all NULL — corpus extraction is a global
    ops process, not tied to a tenant."""
    run = ModelRun(
        company_id=None,
        matter_id=None,
        actor_membership_id=None,
        purpose="metadata_extract",
        provider=completion.provider,
        model=completion.model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
        status=status,
        error=error,
    )
    session.add(run)
    session.flush()


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

        # Cap check — fast-path bail before spending tokens.
        if _HALT_FLAG.is_set():
            return {"ok": False, "reason": "daily_cap_halt"}

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
            # Record the failed call for spend visibility too — tokens
            # billed by the provider on a 4xx are still real charges.
            try:
                _record_model_run(
                    s,
                    completion=LLMCompletion(
                        text="",
                        provider=getattr(provider, "name", "unknown"),
                        model=getattr(provider, "model", "unknown"),
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=0,
                    ),
                    status="error",
                    error=str(exc)[:500],
                )
                s.commit()
            except Exception:  # noqa: BLE001
                logger.exception("failed to record error ModelRun")
            return {"ok": False, "reason": "llm_error"}

        # Record the successful Opus call so corpus spend is finally
        # visible in model_runs alongside production AI usage. The
        # _maybe_check_cap below uses this same table to decide if
        # the day's $100 ceiling has been reached.
        try:
            _record_model_run(s, completion=completion, status="ok")
            s.commit()
        except Exception:
            logger.exception("failed to record ok ModelRun for %s", doc_id)
        _maybe_check_cap()

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


def _maybe_check_cap() -> None:
    """Re-poll the daily-spend cap every ``_CAP_CHECK_EVERY_N``
    successful completions. Called from worker threads so the cap
    is enforced even if no progress ticker is running. Sets
    ``_HALT_FLAG`` once the cap is reached; subsequent extractions
    bail at the start of ``_extract_one``."""
    global _processed_since_cap_check
    cap = _layer2_daily_cap_usd()
    if cap <= 0:  # operator opted out
        return
    if _HALT_FLAG.is_set():
        return
    with _cap_check_lock:
        _processed_since_cap_check += 1
        if _processed_since_cap_check < _CAP_CHECK_EVERY_N:
            return
        _processed_since_cap_check = 0
    factory = get_session_factory()
    with factory() as s:
        spend = _spend_last_24h_usd(s)
    if spend >= cap:
        _HALT_FLAG.set()
        logger.error(
            "daily Layer-2 spend cap reached: $%.2f >= $%.2f. "
            "Setting HALT flag — remaining extractions will short-circuit. "
            "Override via CASEOPS_LAYER2_DAILY_USD_CAP.",
            spend, cap,
        )
    else:
        logger.info(
            "daily Layer-2 spend so far: $%.2f / $%.2f cap (%.0f%% used)",
            spend, cap, 100.0 * spend / cap,
        )


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

    # Pre-flight cap gate so a no-op start when the cap is already
    # blown is quiet — the worker would otherwise burn one full doc
    # before noticing.
    cap = _layer2_daily_cap_usd()
    if cap > 0:
        factory = get_session_factory()
        with factory() as s:
            spend = _spend_last_24h_usd(s)
        if spend >= cap:
            logger.error(
                "Refusing to start: Layer-2 spend in the last 24h is "
                "$%.2f, at or above the $%.2f cap. Wait, raise "
                "CASEOPS_LAYER2_DAILY_USD_CAP, or set it to 0 to disable.",
                spend, cap,
            )
            return 2
        logger.info(
            "spend pre-flight: $%.2f / $%.2f cap used so far in the last 24h",
            spend, cap,
        )

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
