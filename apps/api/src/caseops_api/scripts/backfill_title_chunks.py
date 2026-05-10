"""CLI: retrofit title-header chunks onto existing authority documents.

For every ``authority_documents`` row that lacks a chunk with
``chunk_role='metadata'``, build a compact header (title + case_reference
+ court_name + neutral_citation + bench_name + decision_date), embed it,
and insert it as a new chunk. Case-name queries (short, proper-noun
heavy) benefit enormously: first-stage HNSW gets a dense target that is
the case name, rather than hunting through prose that happens to mention
``"state"`` and ``"bail"``.

Idempotent: presence of a chunk with ``chunk_role='metadata'`` is the
skip signal. Safe to re-run after partial runs.

Usage::

    uv run caseops-backfill-title-chunks --limit 50       # trial
    uv run caseops-backfill-title-chunks                  # full run
    uv run caseops-backfill-title-chunks --batch-size 32  # tune Voyage batch
    uv run caseops-backfill-title-chunks --refresh        # rebuild after Layer 2
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, extract, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_ingest import (
    _apply_pgvector_batch,
    _encode_vector,
    _postgres_backend,
)
from caseops_api.services.corpus_title_validation import title_is_case_name
from caseops_api.services.embeddings import EmbeddingProvider, build_provider

logger = logging.getLogger("backfill_title_chunks")

_UNSAFE_DETAIL_RE = re.compile(
    r"\(cid:\d+\)|"
    "[\u0900-\u097F\u0A00-\u0A7F\u0B00-\u0B7F\u0B80-\u0BFF"
    "\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F]"
)


@dataclass
class _Summary:
    scanned: int = 0
    skipped_already_done: int = 0
    skipped_no_header_data: int = 0
    inserted: int = 0
    refreshed_dropped: int = 0
    errors: int = 0


def _title_is_case_name(title: str | None) -> bool:
    """True when the shared corpus predicate accepts this title signal."""
    ok, _reason = title_is_case_name(title)
    return ok


def _parties_from_json(parties_json: str | None) -> list[str]:
    if not parties_json:
        return []
    try:
        parsed = json.loads(parties_json)
    except json.JSONDecodeError:
        return []
    out: list[str] = []
    if isinstance(parsed, list):
        out.extend(str(p) for p in parsed if isinstance(p, str) and p.strip())
    elif isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, str) and v.strip():
                out.append(v)
            elif isinstance(v, list):
                out.extend(str(p) for p in v if isinstance(p, str) and p.strip())
    return [s for s in (p.strip() for p in out) if s]


def _valid_signal(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    ok, _reason = title_is_case_name(value)
    return value if ok else None


def _safe_detail(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if _UNSAFE_DETAIL_RE.search(value):
        return None
    _ok, reason = title_is_case_name(value)
    if reason == "cid_marker":
        return None
    return value


def _party_case_name(parties: Sequence[str]) -> str | None:
    """Return a valid party-case title synthesized from parties_json."""
    clean = [p.strip() for p in parties if p and p.strip()]
    for party in clean:
        if valid := _valid_signal(party):
            return valid
    if len(clean) < 2:
        return None
    candidate = f"{clean[0]} v. {clean[1]}"
    return _valid_signal(candidate)


def _source_reference_matches_year(source_reference: str | None, year: int) -> bool:
    ref = (source_reference or "").lower()
    year_text = str(year)
    return (
        f"/{year_text}/" in ref
        or f"\\{year_text}\\" in ref
        or f"{year_text}_" in ref
        or f"_{year_text}" in ref
    )


def _doc_has_dirty_metadata_chunk(doc: AuthorityDocument) -> bool:
    return any(
        chunk.chunk_role == "metadata" and _UNSAFE_DETAIL_RE.search(chunk.content)
        for chunk in doc.chunks
    )


def _build_header_from_row(doc: AuthorityDocument) -> str:
    """Build a metadata header from every useful DB column.

    Quality gate: returns ``""`` (→ caller skips the chunk) when the
    only available signal is a citation-only / placeholder title AND
    parties_json is empty. Better to have a missing metadata row
    (auditable via chunk_role IS NULL) than to embed a worthless header
    that pollutes top-K. See north-star rule in SKILL.md: "best
    quality, no dummy or incorrect rows".
    """
    parties = _parties_from_json(doc.parties_json)
    valid_title = _valid_signal(doc.title)
    valid_parties_title = _party_case_name(parties)
    valid_case_reference = _valid_signal(doc.case_reference)
    valid_neutral_citation = _valid_signal(doc.neutral_citation)
    primary = (
        valid_title
        or valid_parties_title
        or valid_case_reference
        or valid_neutral_citation
    )

    # Quality gate — reject headers that carry no party-level signal.
    if not primary:
        return ""

    parts: list[str | None] = [
        primary,
        valid_case_reference if valid_case_reference != primary else None,
        valid_neutral_citation if valid_neutral_citation != primary else None,
        doc.court_name,
        _safe_detail(doc.bench_name),
        doc.decision_date.isoformat() if doc.decision_date else None,
    ]
    parts.extend(p for p in (_safe_detail(p) for p in parties) if p)
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _docs_needing_header(
    session: Session,
    *,
    limit: int | None = None,
    refresh: bool = False,
    forum_levels: Sequence[str] | None = None,
    court_name: str | None = None,
    year: int | None = None,
    document_ids: Sequence[str] | None = None,
    invalid_titles_only: bool = False,
    dirty_metadata_only: bool = False,
) -> list[AuthorityDocument]:
    """Docs needing a metadata chunk, ordered by ingested_at desc.

    Default mode: only docs that have *no* chunk with ``chunk_role='metadata'``.
    When ``refresh=True``: every doc qualifies (caller is expected to delete
    the stale metadata chunks per doc right before re-embedding).
    """
    stmt = select(AuthorityDocument).order_by(AuthorityDocument.ingested_at.desc())
    if document_ids:
        stmt = stmt.where(AuthorityDocument.id.in_(list(document_ids)))
    if forum_levels:
        stmt = stmt.where(AuthorityDocument.forum_level.in_(list(forum_levels)))
    if court_name:
        stmt = stmt.where(AuthorityDocument.court_name == court_name)
    if year is not None:
        year_text = str(year)
        stmt = stmt.where(
            or_(
                extract("year", AuthorityDocument.decision_date) == year,
                AuthorityDocument.source_reference.ilike(f"%/{year_text}/%"),
                AuthorityDocument.source_reference.ilike(f"%\\{year_text}\\%"),
                AuthorityDocument.source_reference.ilike(f"%{year_text}_%"),
                AuthorityDocument.source_reference.ilike(f"%_{year_text}%"),
            )
        )
    if not refresh:
        has_header_subq = (
            select(AuthorityDocumentChunk.authority_document_id)
            .where(AuthorityDocumentChunk.chunk_role == "metadata")
            .distinct()
            .subquery()
        )
        stmt = stmt.where(AuthorityDocument.id.not_in(select(has_header_subq)))
    needs_python_filter = invalid_titles_only or dirty_metadata_only
    if limit is not None and not needs_python_filter:
        stmt = stmt.limit(limit)
    docs = list(session.execute(stmt).scalars())
    if needs_python_filter:
        docs = [
            doc for doc in docs
            if (
                invalid_titles_only
                and not _title_is_case_name(doc.title)
            )
            or (
                dirty_metadata_only
                and _doc_has_dirty_metadata_chunk(doc)
            )
        ]
        if year is not None:
            docs = [
                doc for doc in docs
                if (doc.decision_date and doc.decision_date.year == year)
                or _source_reference_matches_year(doc.source_reference, year)
            ]
        if limit is not None:
            docs = docs[:limit]
    return docs


def _drop_existing_metadata_chunks(session: Session, *, document_id: str) -> int:
    """Delete this doc's existing metadata chunks (Voyage embeddings too).

    Returns count removed. Used by --refresh after Layer 2 populates richer
    title/parties/citation; the previous header embedding no longer matches
    the newer, better metadata.
    """
    result = session.execute(
        delete(AuthorityDocumentChunk)
        .where(AuthorityDocumentChunk.authority_document_id == document_id)
        .where(AuthorityDocumentChunk.chunk_role == "metadata")
    )
    return result.rowcount or 0


def _next_chunk_index(session: Session, *, document_id: str) -> int:
    """Max existing chunk_index + 1 (so we never collide with prose chunks)."""
    result = session.execute(
        select(func.coalesce(func.max(AuthorityDocumentChunk.chunk_index), -1))
        .where(AuthorityDocumentChunk.authority_document_id == document_id)
    ).scalar_one()
    return int(result) + 1


def _run(
    session: Session,
    *,
    embedder: EmbeddingProvider,
    limit: int | None,
    batch_size: int,
    refresh: bool = False,
    forum_levels: Sequence[str] | None = None,
    court_name: str | None = None,
    year: int | None = None,
    document_ids: Sequence[str] | None = None,
    invalid_titles_only: bool = False,
    dirty_metadata_only: bool = False,
) -> _Summary:
    summary = _Summary()
    docs = _docs_needing_header(
        session,
        limit=limit,
        refresh=refresh,
        forum_levels=forum_levels,
        court_name=court_name,
        year=year,
        document_ids=document_ids,
        invalid_titles_only=invalid_titles_only,
        dirty_metadata_only=dirty_metadata_only,
    )
    summary.scanned = len(docs)
    logger.info(
        "docs %s title-header chunk: %d",
        "to refresh" if refresh else "needing",
        summary.scanned,
    )

    # Build (doc, header) pairs, skipping docs with no usable header text.
    # In --refresh mode, docs that fail the quality gate have their old
    # metadata chunk DELETED with no replacement — a stale placeholder
    # embedding is worse than a missing row.
    pending: list[tuple[AuthorityDocument, str]] = []
    for doc in docs:
        header = _build_header_from_row(doc)
        if not header:
            summary.skipped_no_header_data += 1
            if refresh:
                summary.refreshed_dropped += _drop_existing_metadata_chunks(
                    session, document_id=doc.id
                )
            continue
        pending.append((doc, header))
    if refresh and summary.skipped_no_header_data:
        session.commit()

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        headers = [h for _, h in batch]
        try:
            embed_result = embedder.embed(headers)
        except Exception as exc:  # noqa: BLE001
            logger.exception("embed batch failed at offset %d: %s", start, exc)
            summary.errors += len(batch)
            continue

        chunk_rows: list[AuthorityDocumentChunk] = []
        for (doc, header), vector in zip(
            batch, embed_result.vectors, strict=False
        ):
            if refresh:
                summary.refreshed_dropped += _drop_existing_metadata_chunks(
                    session, document_id=doc.id
                )
            idx = _next_chunk_index(session, document_id=doc.id)
            chunk = AuthorityDocumentChunk(
                authority_document_id=doc.id,
                chunk_index=idx,
                content=header,
                token_count=len(header.split()),
                embedding_model=embed_result.model,
                embedding_dimensions=embed_result.dimensions,
                embedding_json=_encode_vector(vector),
                embedded_at=datetime.now(UTC),
                chunk_role="metadata",
            )
            session.add(chunk)
            chunk_rows.append(chunk)

        session.flush()
        if _postgres_backend(session):
            _apply_pgvector_batch(
                session, chunks=chunk_rows, vectors=embed_result.vectors
            )
        session.commit()
        summary.inserted += len(chunk_rows)
        logger.info(
            "batch %d-%d: inserted=%d (running total inserted=%d)",
            start,
            start + len(batch),
            len(chunk_rows),
            summary.inserted,
        )

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Headers per Voyage embed call. Default 32.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Rebuild metadata chunks for every doc — drop existing "
            "chunk_role='metadata' rows and re-embed with current metadata. "
            "Use this after Layer 2 extraction fills richer title / parties / "
            "neutral_citation, because the previous header was built from "
            "filename-derived placeholders."
        ),
    )
    parser.add_argument(
        "--forum-level",
        action="append",
        default=None,
        help="Restrict to a forum_level. Repeat for multiple values.",
    )
    parser.add_argument(
        "--court-name",
        default=None,
        help="Restrict to one exact court_name, e.g. 'Delhi High Court'.",
    )
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument(
        "--ids-file",
        type=Path,
        default=None,
        help="Restrict to document IDs listed one per line.",
    )
    parser.add_argument(
        "--invalid-titles-only",
        action="store_true",
        help=(
            "Only process rows whose canonical title fails the shared "
            "case-name predicate. Intended for targeted hygiene repair."
        ),
    )
    parser.add_argument(
        "--dirty-metadata-only",
        action="store_true",
        help=(
            "Only process rows whose existing metadata chunk contains "
            "unsafe non-Latin or CID-marker text."
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    embedder = build_provider()
    document_ids = None
    if args.ids_file is not None:
        document_ids = tuple(
            line.strip()
            for line in args.ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    session_factory = get_session_factory()
    with session_factory() as session:
        summary = _run(
            session,
            embedder=embedder,
            limit=args.limit,
            batch_size=args.batch_size,
            refresh=args.refresh,
            forum_levels=tuple(args.forum_level) if args.forum_level else None,
            court_name=args.court_name,
            year=args.year,
            document_ids=document_ids,
            invalid_titles_only=args.invalid_titles_only,
            dirty_metadata_only=args.dirty_metadata_only,
        )

    print(
        "title-chunk backfill: "
        f"mode={'refresh' if args.refresh else 'insert'} "
        f"scanned={summary.scanned} "
        f"inserted={summary.inserted} "
        f"refreshed_dropped={summary.refreshed_dropped} "
        f"skipped_no_header_data={summary.skipped_no_header_data} "
        f"errors={summary.errors}"
    )
    return 0 if summary.errors == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
