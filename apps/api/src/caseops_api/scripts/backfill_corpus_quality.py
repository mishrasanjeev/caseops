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
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

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

# Year extraction has three sources, tried in order:
#
# 1. SC filename pattern: ``2025_12_593_610_EN.pdf`` — ecourts SC
#    adapter packs the year into the leading 4 digits of the filename
#    stem. Matches against ``(?:^|/)(\d{4})_`` so paths like
#    ``sc/2024/2025_X_Y_Z.pdf`` still resolve to 2025.
# 2. HC trailing-date pattern: ``DLHC010000672024_1_2024-02-08.pdf`` —
#    Delhi HC and other state HCs prefix the filename with the court
#    code + case ID, then append ``_YYYY-MM-DD.pdf`` for the decision
#    date. The 2026-05-04 corpus probe showed 100 % (45,392 / 45,392)
#    of HC docs match this pattern; the SC regex above misses every
#    one of them.
# 3. ``decision_date`` column fallback. ~60 % of HC docs and most
#    older SC docs have ``decision_date`` populated by the ingest
#    adapter even when the filename year is unparseable. This catches
#    the long tail (notably old SC ``S_1995_...`` outliers).
#
# Returns ``None`` only when ALL three sources fail. Callers track
# the source label for the per-source counter line at triage time so
# operators can see which patterns the corpus is actually hitting.
_SC_FILENAME_YEAR_RE = re.compile(r"(?:^|/)(\d{4})_")
_HC_TRAILING_DATE_RE = re.compile(r"_(\d{4})-\d{2}-\d{2}(?:\.pdf)?$", re.IGNORECASE)
# Legacy alias retained so any external import doesn't break.
_YEAR_RE = _SC_FILENAME_YEAR_RE

YearSource = Literal[
    "sc_filename", "hc_trailing_date", "decision_date", "unparseable",
]
_BUDGET_LOG_PATH = Path("tmp/structured_budget.json")

# Default forum scope for the EN-only backfill.
_DEFAULT_FORUMS: frozenset[str] = frozenset({"supreme_court", "high_court"})

# Default year window when ``--english-only`` is on and no explicit
# ``--year-range`` was passed. Covers SC 1990-2025 + all HC 1990-2025
# per the 2026-05-04 EN-only Layer-2 directive — older judgments are
# both lower-quality OCR and rarely-cited authority.
_DEFAULT_EN_YEAR_RANGE: tuple[int, int] = (1990, 2025)

# Indic scripts in the Unicode plane. We use a single bracketed
# character class instead of nine separate `\u` escapes because
# `re.compile` interprets each range cleanly. A doc is rejected if its
# title or its first ``_LANG_PROBE_CHARS`` contain ANY character in
# this class — partial matches dominate Devanagari OCR output (each
# vowel sign is its own codepoint).
#
# Coverage:
#   U+0900-U+097F  Devanagari   (Hindi, Marathi, Sanskrit, Nepali)
#   U+0980-U+09FF  Bengali / Assamese
#   U+0A00-U+0A7F  Gurmukhi     (Punjabi)
#   U+0A80-U+0AFF  Gujarati
#   U+0B00-U+0B7F  Oriya
#   U+0B80-U+0BFF  Tamil
#   U+0C00-U+0C7F  Telugu
#   U+0C80-U+0CFF  Kannada
#   U+0D00-U+0D7F  Malayalam
_INDIC_SCRIPT_RE = re.compile(
    "["
    "ऀ-ॿ"
    "ঀ-৿"
    "਀-੿"
    "઀-૿"
    "଀-୿"
    "஀-௿"
    "ఀ-౿"
    "ಀ-೿"
    "ഀ-ൿ"
    "]"
)
_LANG_PROBE_CHARS = 2_000

# SC corpus filename suffixes that explicitly mark a non-English
# transcript (the SCI publishes parallel translations with these
# language codes). A definitive non-EN suffix is a hard reject — the
# Layer-2 prompt + ``_ExtractionPayload`` schema are English-shaped and
# every observed call on a non-EN doc has produced malformed JSON
# (Devanagari content gets emitted with invalid ``\\`` escape
# sequences). Empirical evidence (2026-05-04 ingest VM corpus):
#   _EN.pdf:  14 594 docs, 1 with Devanagari content  (clean signal)
#   _NEP.pdf:    25 docs, 25 with Devanagari content  (clean signal)
#   no-suffix: 87 242 docs, 38 132 with Devanagari    (mixed; needs
#                                                       content probe)
_NON_EN_FILE_SUFFIXES: tuple[str, ...] = (
    "_hin.pdf",   # Hindi
    "_pun.pdf",   # Punjabi
    "_ben.pdf",   # Bengali
    "_guj.pdf",   # Gujarati
    "_tam.pdf",   # Tamil
    "_tel.pdf",   # Telugu
    "_kan.pdf",   # Kannada
    "_mal.pdf",   # Malayalam
    "_ori.pdf",   # Oriya
    "_nep.pdf",   # Nepali
    "_san.pdf",   # Sanskrit
    "_urd.pdf",   # Urdu
    "_asm.pdf",   # Assamese
    "_mar.pdf",   # Marathi (where the SCI labels it explicitly)
)
_EN_FILE_SUFFIX = "_en.pdf"


def _doc_appears_english(doc: AuthorityDocument) -> bool:
    """Decide whether a document is in English.

    Cheap path: file-suffix dispatch. Both ``_EN.pdf`` and the
    explicit non-EN suffixes are decisive on their own.

    Fallback: probe the first ``_LANG_PROBE_CHARS`` of ``title`` and
    ``document_text`` for any Indic-script character. Even one
    Devanagari / Tamil / etc. codepoint in the head of a judgment is
    enough to fail the English check on this corpus — we have not
    observed false positives where a head with Indic letters parsed
    cleanly through Layer-2.

    Returns True when the doc is English, False otherwise.
    """
    src = (doc.source_reference or "").lower()
    if src.endswith(_EN_FILE_SUFFIX):
        return True
    for suffix in _NON_EN_FILE_SUFFIXES:
        if src.endswith(suffix):
            return False
    title = doc.title or ""
    if _INDIC_SCRIPT_RE.search(title[:_LANG_PROBE_CHARS]):
        return False
    text = doc.document_text or ""
    if _INDIC_SCRIPT_RE.search(text[:_LANG_PROBE_CHARS]):
        return False
    return True


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


def _year_and_source_for_doc(
    doc: AuthorityDocument,
) -> tuple[int | None, YearSource]:
    """Return ``(year, source)`` for a doc using three sources in order.

    See ``_SC_FILENAME_YEAR_RE`` / ``_HC_TRAILING_DATE_RE`` /
    ``AuthorityDocument.decision_date`` block comment above for the
    rationale of each source. ``source`` is always a non-None label so
    triage counters can attribute every doc to exactly one bucket
    (including ``"unparseable"`` for the rejected tail).
    """
    ref = doc.source_reference or ""
    if ref:
        m = _SC_FILENAME_YEAR_RE.search("/" + ref)
        if m:
            try:
                return int(m.group(1)), "sc_filename"
            except ValueError:
                pass
        m = _HC_TRAILING_DATE_RE.search(ref)
        if m:
            try:
                return int(m.group(1)), "hc_trailing_date"
            except ValueError:
                pass
    dd = doc.decision_date
    if dd is not None:
        return dd.year, "decision_date"
    return None, "unparseable"


def _year_for_doc(doc: AuthorityDocument) -> int | None:
    """Backward-compatible single-int accessor.

    Kept so existing callers (sort keys, etc.) don't change. New
    code that needs to count per-source uses
    ``_year_and_source_for_doc``.
    """
    year, _ = _year_and_source_for_doc(doc)
    return year


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
    concurrency: int = 1,
    english_only: bool = True,
    forums: frozenset[str] | None = None,
    triage_only: bool = False,
) -> dict:
    """Triage router over every doc that still needs structured data.

    Order: Sonnet-tier candidates first (they carry the most value per
    dollar), then the Haiku tier. Within each tier, descending
    chronological order so recent judgments are covered before older
    ones if the budget runs out.

    ``year_range`` (lo, hi inclusive): when set, BOTH tiers are
    filtered — only docs whose extracted year (per
    ``_year_and_source_for_doc``) falls in [lo, hi] are processed.
    The 2026-05-02 fix corrected the prior Sonnet-only behaviour
    that turned per-bucket haiku invocations into no-ops for ~9 days.
    Use for per-bucket workflow, e.g. SC 2020-2025 first, audit,
    then SC 2015-2019, etc.
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
    # chronological-priority order. When `year_range` is set, the filter
    # applies to BOTH tiers so per-bucket sweeps that route to haiku
    # (the launcher's normal mode) actually process docs — the prior
    # year-range-only-on-sonnet behavior turned every per-bucket Layer-2
    # invocation into a no-op for ~9 days (2026-04-23 → 2026-05-02).
    sonnet_bucket: list[AuthorityDocument] = []
    haiku_bucket: list[AuthorityDocument] = []
    forums_filter = forums if forums is not None else _DEFAULT_FORUMS
    skipped_non_en = 0
    skipped_forum = 0
    skipped_year = 0
    # Per-source counters: how many docs got a year from each of the
    # three sources, vs how many were rejected as unparseable. Reported
    # alongside the triage line so a future ingest format change is
    # caught at scan time rather than at structured-extraction time.
    year_source_counts: dict[YearSource, int] = {
        "sc_filename": 0,
        "hc_trailing_date": 0,
        "decision_date": 0,
        "unparseable": 0,
    }
    for doc in all_docs:
        tier = force_tier or _tier_for_doc(doc)
        if _already_covered_at_tier(doc, tier):
            continue
        if forums_filter and doc.forum_level not in forums_filter:
            skipped_forum += 1
            continue
        if year_range is not None:
            year, year_src = _year_and_source_for_doc(doc)
            year_source_counts[year_src] += 1
            if year is None or not (year_range[0] <= year <= year_range[1]):
                skipped_year += 1
                continue
        if english_only and not _doc_appears_english(doc):
            skipped_non_en += 1
            continue
        if tier == "sonnet":
            sonnet_bucket.append(doc)
        else:
            haiku_bucket.append(doc)
    if english_only or forums_filter or year_range is not None:
        logger.info(
            "filter rejections: forum=%d  year=%d  non_english=%d",
            skipped_forum, skipped_year, skipped_non_en,
        )
        if year_range is not None:
            logger.info(
                "year sources: sc_filename=%d  hc_trailing_date=%d  "
                "decision_date=%d  unparseable=%d",
                year_source_counts["sc_filename"],
                year_source_counts["hc_trailing_date"],
                year_source_counts["decision_date"],
                year_source_counts["unparseable"],
            )

    # Sort each bucket by filename year DESC so newest lands before
    # oldest inside a multi-year bucket. NULL-dated docs without a
    # filename year drop to the end via -1.
    sonnet_bucket.sort(key=lambda d: _year_for_doc(d) or -1, reverse=True)
    haiku_bucket.sort(key=lambda d: _year_for_doc(d) or -1, reverse=True)

    if year_range is not None:
        logger.info(
            "year-range %d-%d: %d sonnet, %d haiku candidates, budget=$%.2f",
            year_range[0], year_range[1],
            len(sonnet_bucket), len(haiku_bucket), budget_usd,
        )
    else:
        logger.info(
            "triage: %d sonnet candidates, %d haiku candidates, budget=$%.2f",
            len(sonnet_bucket), len(haiku_bucket), budget_usd,
        )

    if triage_only:
        # Diagnostic mode: print the candidate counts + per-source
        # breakdown, then exit before any LLM call. Used to validate
        # candidate-selection changes (year parser, EN filter, forum
        # filter) without burning OpenAI tokens.
        return {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "budget_usd": budget_usd,
            "spent_usd": 0.0,
            "sonnet": {"done": 0, "cost_usd": 0.0, "candidates": len(sonnet_bucket)},
            "haiku": {"done": 0, "cost_usd": 0.0, "candidates": len(haiku_bucket)},
            "failures": 0,
            "quality_low": 0,
            "year_sources": dict(year_source_counts),
            "skipped_forum": skipped_forum,
            "skipped_year": skipped_year,
            "skipped_non_english": skipped_non_en,
            "triage_only": True,
        }

    if concurrency > 1:
        # Release the read-only triage transaction so the long-lived
        # connection isn't held idle-in-transaction for the duration
        # of the worker run. Workers in ``_run_bucket_concurrent`` use
        # their own sessions opened via ``SessionFactory()``; this
        # ``session`` is not used again by ``_structured_pass``.
        #
        # Anchor: 2026-05-04 c=16 run on the ingest VM held the
        # triage connection idle-in-transaction for 30+ minutes
        # (state=idle in transaction, wait_event=Client/ClientRead)
        # because the SELECT loaded 43,984 candidate rows then
        # ``all_docs.all()`` returned but no COMMIT/ROLLBACK was
        # issued. With Cloud SQL ``max_connections=100`` and
        # several other VM jobs alive, every held connection
        # matters.
        #
        # We use ``rollback()`` not ``close()`` because the caller
        # owns the session via ``with SessionFactory() as session:``
        # in ``run()``. Closing here would invalidate the caller's
        # context manager. ``rollback()`` ends the current
        # transaction and returns the connection to the pool while
        # leaving the session object usable. ``expire_on_commit``
        # is False on the engine (see ``db/session.py``) so any
        # ORM attribute access on the in-memory bucket docs that
        # remains (e.g. ``_year_for_doc(d)`` was already called for
        # the sort above) does not trigger a re-query.
        #
        # Sequential mode (``concurrency == 1``) keeps the prior
        # behaviour: ``_run_bucket_sequential`` reuses the SAME
        # ``session`` to call ``extract_and_persist_structured``
        # and ``session.commit()``, so releasing the transaction
        # here would flush a stale state on the very next
        # statement.
        session.rollback()

    totals = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "budget_usd": budget_usd,
        "spent_usd": 0.0,
        "sonnet": {"done": 0, "cost_usd": 0.0, "candidates": len(sonnet_bucket)},
        "haiku": {"done": 0, "cost_usd": 0.0, "candidates": len(haiku_bucket)},
        "failures": 0,
        "quality_low": 0,
    }

    totals_lock = threading.Lock()

    def _run_bucket(bucket: list[AuthorityDocument], tier: str) -> bool:
        """Returns True if the bucket finished, False if budget was hit."""
        if concurrency <= 1:
            return _run_bucket_sequential(bucket, tier)
        return _run_bucket_concurrent(bucket, tier)

    def _run_bucket_sequential(bucket: list[AuthorityDocument], tier: str) -> bool:
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

    def _run_bucket_concurrent(bucket: list[AuthorityDocument], tier: str) -> bool:
        """ThreadPool variant. Each worker opens its own SA session because
        SA sessions are not thread-safe. Budget is checked under
        ``totals_lock`` between submissions, so a budget-cap stops the run
        cleanly without leaving in-flight workers orphaned."""
        SessionFactory = get_session_factory()
        doc_ids = [doc.id for doc in bucket]

        def _process(doc_id: str) -> object | None:
            with SessionFactory() as worker_session:
                doc = worker_session.get(AuthorityDocument, doc_id)
                if doc is None:
                    return None
                try:
                    summary = extract_and_persist_structured(
                        worker_session, document=doc, tier=tier,
                    )
                except Exception:
                    logger.exception(
                        "structured extraction failed for %s (tier=%s)",
                        doc_id, tier,
                    )
                    worker_session.rollback()
                    return "FAILED"
                if not dry_run:
                    worker_session.commit()
                return summary

        t0 = time.time()
        idx = 0
        in_flight: dict[object, str] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            # prime the pool
            while idx < min(concurrency, len(doc_ids)):
                fut = ex.submit(_process, doc_ids[idx])
                in_flight[fut] = doc_ids[idx]
                idx += 1

            while in_flight:
                # wait for at least one completion
                done_iter = as_completed(list(in_flight.keys()), timeout=None)
                fut = next(done_iter)
                doc_id = in_flight.pop(fut)
                try:
                    summary = fut.result()
                except Exception:
                    logger.exception(
                        "worker raised for %s (tier=%s)", doc_id, tier,
                    )
                    summary = "FAILED"

                with totals_lock:
                    if summary == "FAILED":
                        totals["failures"] += 1
                    elif summary is not None:
                        totals[tier]["done"] += 1
                        totals[tier]["cost_usd"] += summary.cost_usd
                        totals["spent_usd"] += summary.cost_usd
                        if summary.quality_score < 0.5:
                            totals["quality_low"] += 1
                            logger.info(
                                "low quality (%.2f) on %s: %s",
                                summary.quality_score, doc_id,
                                list(summary.quality_issues),
                            )
                    done_count = totals[tier]["done"]
                    over_budget = totals["spent_usd"] >= budget_usd
                    if done_count and done_count % 10 == 0:
                        rate = done_count / max(time.time() - t0, 1e-6)
                        last_model = (
                            summary.model
                            if summary not in (None, "FAILED")
                            else "?"
                        )
                        logger.info(
                            "[%s] %d/%d done  spent=$%.2f  %.2f/s  "
                            "concurrency=%d  last_model=%s",
                            tier, done_count, len(bucket),
                            totals["spent_usd"], rate, concurrency, last_model,
                        )
                        _emit_budget_snapshot(totals)

                if over_budget:
                    logger.warning(
                        "budget ceiling $%.2f reached; stopping %s tier "
                        "(submitted=%d, in_flight=%d)",
                        budget_usd, tier, idx, len(in_flight),
                    )
                    # let already-in-flight workers finish; do not submit more
                    for pending_fut in as_completed(list(in_flight.keys())):
                        pending_id = in_flight.pop(pending_fut)
                        try:
                            pending_summary = pending_fut.result()
                        except Exception:
                            logger.exception(
                                "drain worker raised for %s", pending_id,
                            )
                            with totals_lock:
                                totals["failures"] += 1
                            continue
                        if pending_summary not in (None, "FAILED"):
                            with totals_lock:
                                totals[tier]["done"] += 1
                                totals[tier]["cost_usd"] += pending_summary.cost_usd
                                totals["spent_usd"] += pending_summary.cost_usd
                                if pending_summary.quality_score < 0.5:
                                    totals["quality_low"] += 1
                    _emit_budget_snapshot(totals)
                    return False

                # submit next if any remain
                if idx < len(doc_ids):
                    fut = ex.submit(_process, doc_ids[idx])
                    in_flight[fut] = doc_ids[idx]
                    idx += 1

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
    concurrency: int = 1,
    english_only: bool = True,
    forums: frozenset[str] | None = None,
    triage_only: bool = False,
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
                concurrency=concurrency,
                english_only=english_only,
                forums=forums,
                triage_only=triage_only,
            )
            if totals.get("triage_only"):
                ys = totals.get("year_sources", {})
                sys.stdout.write(
                    "triage-only: "
                    f"sonnet_candidates={totals['sonnet']['candidates']} "
                    f"haiku_candidates={totals['haiku']['candidates']} "
                    f"skipped_forum={totals.get('skipped_forum', 0)} "
                    f"skipped_year={totals.get('skipped_year', 0)} "
                    f"skipped_non_english={totals.get('skipped_non_english', 0)} "
                    f"year_sources(sc={ys.get('sc_filename', 0)}, "
                    f"hc={ys.get('hc_trailing_date', 0)}, "
                    f"dd={ys.get('decision_date', 0)}, "
                    f"unparseable={ys.get('unparseable', 0)})\n"
                )
            else:
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
            "Restrict BOTH tiers to documents whose extracted year falls "
            "in YYYY-YYYY (inclusive). Year is read from the SC filename "
            "pattern, the HC trailing-date pattern, or the decision_date "
            "column — whichever resolves first. With --english-only on, "
            "the default is 1990-2025 (SC + all HC). Use for per-bucket "
            "workflow, e.g. --year-range 2020-2025."
        ),
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help=(
            "Run extraction with N parallel worker threads (each opens its "
            "own SA session). Default 1 = sequential. Recommended 8 for the "
            "104K-doc backfill on the ingest VM; budget is still enforced "
            "atomically across workers and the run stops cleanly when the "
            "ceiling is hit."
        ),
    )
    parser.add_argument(
        "--english-only", dest="english_only", action="store_true",
        default=True,
        help=(
            "Skip non-English documents (default ON). Detection: filename "
            "suffix ``_EN.pdf`` is a hard accept; ``_HIN/_PUN/_BEN/_TAM/...`` "
            "is a hard reject; otherwise probe the title + first 2K chars of "
            "document_text for any Devanagari/Tamil/Telugu/Kannada/Malayalam/"
            "Bengali/Gurmukhi/Gujarati/Oriya character. Pass "
            "``--no-english-only`` to disable."
        ),
    )
    parser.add_argument(
        "--no-english-only", dest="english_only", action="store_false",
        help="Disable the English-only filter (process every language).",
    )
    parser.add_argument(
        "--triage-only", dest="triage_only", action="store_true",
        help=(
            "Print the candidate counts + per-source year-extraction "
            "breakdown and exit before any LLM call. Used to validate "
            "candidate-selection changes (year parser, EN filter, forum "
            "filter) without burning OpenAI tokens."
        ),
    )
    parser.add_argument(
        "--forums",
        default=",".join(sorted(_DEFAULT_FORUMS)),
        help=(
            "Comma-separated allowlist of ``forum_level`` values to process. "
            f"Default {sorted(_DEFAULT_FORUMS)} (SC + all HC). Pass "
            "``--forums all`` to drop the filter entirely."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    forums: frozenset[str] | None
    if args.forums.strip().lower() == "all":
        forums = None
    else:
        forums = frozenset(
            v.strip() for v in args.forums.split(",") if v.strip()
        )
    year_range = _parse_year_range(args.year_range)
    if year_range is None and args.english_only:
        # User-stated scope (2026-05-04): SC 2025-1990 + all HC 2025-1990,
        # English only. When ``--english-only`` is on and no explicit range
        # was passed, default to 1990-2025 so a bare invocation matches
        # what the operator expects.
        year_range = _DEFAULT_EN_YEAR_RANGE
    return run(
        stage=args.stage, limit=args.limit, dry_run=args.dry_run,
        budget_usd=args.budget_usd, force_tier=args.force_tier,
        year_range=year_range,
        concurrency=max(1, args.concurrency),
        english_only=args.english_only,
        forums=forums,
        triage_only=args.triage_only,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
