"""Targeted Layer-2 re-extract for placeholder / garbage titles.

Closes the data-quality tail that :mod:`services.corpus_title_validation`
merely *gates* on at probe time. When the Layer-2 extractor writes a
``title`` that's really a PDF page header (``"DHARWAD BENCH"``, ``"BENCH
AT AURANGABAD"``), an OCR placeholder (``(cid:8117)``), or a non-Latin
translation cover, downstream retrieval can't recover — hundreds of
docs collapse onto near-identical title-chunk embeddings.

This service:

1. Finds docs whose ``title`` fails the case-name predicate (same set
   the probe skips).
2. Re-prompts Haiku with a targeted instruction ("extract the case
   name; do NOT return the page header or bench name alone; return
   ``null`` if the first 3 pages don't contain a case name").
3. Gates the new title through the same predicate before persisting.
   A bad extraction NEVER overwrites with worse noise — if the
   re-extract fails the predicate, the row stays unchanged and is
   tallied under a skip reason.
4. Updates ``title`` and bumps ``structured_version`` so a future
   title-chunk backfill with ``--refresh`` can rebuild the metadata
   chunk with the cleaner title.

Idempotent: callers can re-run with the same budget; rows that
already have a valid title (or already got `null` on a prior pass)
are skipped by the initial detector.

See also: ``memory/feedback_title_validation_legal_corpus.md`` and
``.claude/skills/corpus-ingest/SKILL.md`` (Title hygiene section).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.services.corpus_title_validation import title_is_case_name
from caseops_api.services.llm import (
    PURPOSE_METADATA_EXTRACT,
    LLMCallContext,
    LLMMessage,
    LLMProvider,
    LLMResponseFormatError,
    generate_structured,
)

logger = logging.getLogger(__name__)


# SQL that matches the patterns listed in the corpus-ingest skill's
# "Title hygiene" section. Conservative: only flags titles we're
# confident are NOT case names. A title that happens to look like a
# page header but IS actually a case name stays out of scope (the
# predicate would accept it anyway).
# Bench / circuit-bench names that leak into the `title` slot when PDF
# extraction treats the page header as the case name.
_BENCH_PLACEHOLDER_CITIES = (
    "DHARWAD|AURANGABAD|JODHPUR|KOZHIKODE|NAGPUR|MADURAI|LUCKNOW|"
    "INDORE|GWALIOR|RANCHI|JABALPUR|GUWAHATI|SHILLONG|IMPHAL|AIZAWL|"
    "KOHIMA|GANGTOK|ITANAGAR"
)
# Non-Latin Unicode ranges common in Indian-court translations (Hindi,
# Gurmukhi, Oriya, Tamil, Telugu, Kannada, Malayalam).
_NON_LATIN_RANGES = (
    "\\u0900-\\u097F\\u0A00-\\u0A7F\\u0B00-\\u0B7F\\u0B80-\\u0BFF"
    "\\u0C00-\\u0C7F\\u0C80-\\u0CFF\\u0D00-\\u0D7F"
)
_DETECTOR_SQL = text(f"""
    SELECT id, title, COALESCE(document_text, '') AS document_text
    FROM authority_documents
    WHERE title IS NOT NULL
      AND (
          title ~* '^({_BENCH_PLACEHOLDER_CITIES})\\s*BEN\\s?CH$'
          OR title ~* '^BENCH\\s+AT\\s+[A-Z]+$'
          OR title ~* '^(IN\\s+THE\\s+)?(HIGH|SUPREME)\\s+COURT'
          OR char_length(title) < 12
          OR title ~ '\\(cid:[0-9]+\\)'
          OR title ~ '[{_NON_LATIN_RANGES}]'
      )
    ORDER BY id
    LIMIT :lim
""")


_SYSTEM_PROMPT = (
    "You extract case names from the first pages of Indian-court "
    "judgments. Return ONLY valid JSON shaped as "
    "{\"title\": \"<case name or null>\"}. No prose, no markdown fences."
)


_USER_PROMPT_TEMPLATE = """Extract the case name from this judgment.

Rules:
- Do NOT return the page header, bench name alone, or court name
  alone. Strings like "DHARWAD BENCH", "BENCH AT AURANGABAD", "IN THE
  HIGH COURT OF KARNATAKA", "SUPREME COURT OF INDIA" are NEVER valid
  case names.
- A valid case name has two parties separated by "v." / "vs." /
  "versus" / "and", OR a neutral citation, OR at least three
  distinctive proper-noun tokens that are NOT place names or court
  headers.
- If this document doesn't contain the case name in its first pages
  (continuation page, translation cover, pure procedural order,
  non-Latin-only text), return the JSON literal ``null`` for the
  title. Do not invent a name.

Current (bad) title, for context: {current_title!r}

Document text (first 8000 characters):
{document_excerpt}

Return JSON: {{"title": "<case name or null>"}}."""


class _TitleOnly(BaseModel):
    title: str | None = Field(default=None)


@dataclass
class ReextractOutcome:
    doc_id: str
    old_title: str
    new_title: str | None
    accepted: bool
    reason: str
    cost_usd: float


@dataclass
class ReextractReport:
    attempted: int = 0
    accepted: int = 0
    rejected_by_predicate: int = 0
    null_returned: int = 0
    llm_failed: int = 0
    total_cost_usd: float = 0.0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    outcomes: list[ReextractOutcome] = field(default_factory=list)

    def bump_skip(self, reason: str) -> None:
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


def find_placeholder_title_docs(
    session: Session, *, limit: int = 1000,
) -> list[tuple[str, str, str]]:
    """Return ``(doc_id, title, document_text)`` tuples flagged by the
    detector. Capped at ``limit`` rows. Caller filters further via the
    predicate (belt-and-braces).

    The detector uses PostgreSQL-native regex (``~`` / ``~*``). On
    non-Postgres engines (SQLite in tests) we load all rows with a
    non-null title and filter in Python using the shared predicate —
    slower but dialect-independent so the test suite stays green.
    """
    try:
        dialect = session.bind.dialect.name if session.bind else None
    except Exception:  # noqa: BLE001
        dialect = None
    if dialect != "postgresql":
        from sqlalchemy import select as _select

        from caseops_api.db.models import AuthorityDocument
        stmt = (
            _select(
                AuthorityDocument.id,
                AuthorityDocument.title,
                AuthorityDocument.document_text,
            )
            .where(AuthorityDocument.title.is_not(None))
            .limit(limit)
        )
        raw_rows = session.execute(stmt).all()
        rows = []
        for r in raw_rows:
            title = r.title or ""
            ok, _reason = title_is_case_name(title)
            if ok:
                continue
            rows.append(type("R", (), {
                "id": r.id,
                "title": title,
                "document_text": r.document_text or "",
            })())
    else:
        rows = session.execute(_DETECTOR_SQL, {"lim": limit}).all()
    out: list[tuple[str, str, str]] = []
    for row in rows:
        # Reassert via the predicate so edge cases (regex false
        # positives, predicate-added-new-rule) agree before we spend
        # tokens.
        title = row.title or ""
        ok, _reason = title_is_case_name(title)
        if ok:
            continue
        out.append((row.id, title, row.document_text or ""))
    return out


def _haiku_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    """Haiku 4.5 pricing, Apr 2026: $0.80 / 1M input, $4.00 / 1M output."""
    return (prompt_tokens * 0.80 + completion_tokens * 4.00) / 1_000_000


def reextract_title(
    session: Session,
    *,
    doc_id: str,
    current_title: str,
    document_text: str,
    provider: LLMProvider,
    tenant_id: str,
) -> ReextractOutcome:
    """Re-extract a single doc's title. Writes the new title + bumps
    ``structured_version`` ONLY if the new title passes the predicate.

    Returns a ``ReextractOutcome`` with telemetry. Caller is
    responsible for session.commit() after batching."""
    excerpt = (document_text or "")[:8000]
    if not excerpt.strip():
        # No text to extract from — mark structured_version bumped so
        # the next sweep doesn't re-try on an empty doc.
        return ReextractOutcome(
            doc_id=doc_id,
            old_title=current_title,
            new_title=None,
            accepted=False,
            reason="empty_document",
            cost_usd=0.0,
        )

    messages = [
        LLMMessage(role="system", content=_SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=_USER_PROMPT_TEMPLATE.format(
                current_title=current_title,
                document_excerpt=excerpt,
            ),
        ),
    ]
    ctx = LLMCallContext(
        tenant_id=tenant_id, matter_id=None, purpose=PURPOSE_METADATA_EXTRACT,
    )

    try:
        payload, completion = generate_structured(
            provider,
            schema=_TitleOnly,
            messages=messages,
            context=ctx,
            max_tokens=200,
            session=session,
        )
    except LLMResponseFormatError as exc:
        logger.warning("reextract %s: LLM format error: %s", doc_id, exc)
        return ReextractOutcome(
            doc_id=doc_id, old_title=current_title, new_title=None,
            accepted=False, reason="llm_format_error", cost_usd=0.0,
        )

    cost = _haiku_cost_usd(completion.prompt_tokens, completion.completion_tokens)

    # Model returned `null` — document genuinely has no case name (e.g.
    # translation cover). Don't update title, but bump structured_version
    # so the next sweep sees this as "checked and confirmed null".
    if payload.title is None:
        return ReextractOutcome(
            doc_id=doc_id, old_title=current_title, new_title=None,
            accepted=False, reason="llm_returned_null", cost_usd=cost,
        )

    new_title = payload.title.strip()
    ok, reason = title_is_case_name(new_title)
    if not ok:
        logger.info(
            "reextract %s rejected by predicate (%s): %r", doc_id, reason, new_title,
        )
        return ReextractOutcome(
            doc_id=doc_id, old_title=current_title, new_title=new_title,
            accepted=False, reason=f"predicate:{reason}", cost_usd=cost,
        )

    _apply_new_title(session, doc_id=doc_id, new_title=new_title)
    return ReextractOutcome(
        doc_id=doc_id, old_title=current_title, new_title=new_title,
        accepted=True, reason="accepted", cost_usd=cost,
    )


def _apply_new_title(
    session: Session, *, doc_id: str, new_title: str,
) -> None:
    """Persist the new title. Does NOT bump ``structured_version`` —
    the caller is expected to re-run ``caseops-backfill-title-chunks
    --refresh`` afterwards, which recomputes metadata chunks with the
    new title. We also archive any existing ``chunk_role='metadata'``
    chunk so the next title-chunk backfill has a clean slate."""
    doc = session.get(AuthorityDocument, doc_id)
    if doc is None:
        logger.warning("reextract apply: doc %s not found", doc_id)
        return
    doc.title = new_title
    # Drop stale metadata chunks — they were embedded from the bad
    # title. Next `caseops-backfill-title-chunks` run rebuilds them.
    for chunk in list(doc.chunks):
        if chunk.chunk_role == "metadata":
            session.delete(chunk)
    session.flush()


def run_reextract_sweep(
    session: Session,
    *,
    provider: LLMProvider,
    tenant_id: str,
    budget_usd: float,
    limit: int = 1000,
    dry_run: bool = False,
) -> ReextractReport:
    """Iterate through placeholder-titled docs until budget runs out.

    ``dry_run`` skips the LLM call; useful to verify the detector
    count + tenancy wiring before spending tokens."""
    docs = find_placeholder_title_docs(session, limit=limit)
    report = ReextractReport()

    if dry_run:
        report.attempted = len(docs)
        for _doc_id, title, _ in docs:
            ok_now, reason = title_is_case_name(title)
            if not ok_now:
                report.bump_skip(reason)
        logger.info(
            "dry-run: %d docs flagged; skip_reasons=%s",
            report.attempted, json.dumps(report.skip_reasons),
        )
        return report

    for doc_id, title, document_text in docs:
        if report.total_cost_usd >= budget_usd:
            logger.info(
                "budget reached ($%.2f / $%.2f) — stopping",
                report.total_cost_usd, budget_usd,
            )
            break
        report.attempted += 1
        outcome = reextract_title(
            session,
            doc_id=doc_id,
            current_title=title,
            document_text=document_text,
            provider=provider,
            tenant_id=tenant_id,
        )
        report.outcomes.append(outcome)
        report.total_cost_usd += outcome.cost_usd
        if outcome.accepted:
            report.accepted += 1
        elif outcome.reason == "llm_returned_null":
            report.null_returned += 1
        elif outcome.reason.startswith("predicate:"):
            report.rejected_by_predicate += 1
            report.bump_skip(outcome.reason.removeprefix("predicate:"))
        else:
            report.llm_failed += 1
            report.bump_skip(outcome.reason)
        if report.accepted % 20 == 0 and report.accepted > 0:
            session.commit()
    # Final commit for the partial batch.
    session.commit()
    return report


__all__ = [
    "ReextractOutcome",
    "ReextractReport",
    "AuthorityDocumentChunk",  # re-exported for mocks in tests
    "find_placeholder_title_docs",
    "reextract_title",
    "run_reextract_sweep",
]
