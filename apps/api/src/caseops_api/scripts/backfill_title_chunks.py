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
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_ingest import (
    _apply_pgvector_batch,
    _encode_vector,
    _postgres_backend,
)
from caseops_api.services.embeddings import EmbeddingProvider, build_provider

logger = logging.getLogger("backfill_title_chunks")


@dataclass
class _Summary:
    scanned: int = 0
    skipped_already_done: int = 0
    skipped_no_header_data: int = 0
    inserted: int = 0
    refreshed_dropped: int = 0
    errors: int = 0


def _build_header_from_row(doc: AuthorityDocument) -> str:
    """Same shape as services.corpus_ingest._build_title_header but
    drawn from the DB row (richer — post-Layer-2 metadata is available)."""
    parts = [
        doc.title,
        doc.case_reference,
        doc.neutral_citation,
        doc.court_name,
        doc.bench_name,
        doc.decision_date.isoformat() if doc.decision_date else None,
    ]
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _docs_needing_header(
    session: Session, *, limit: int | None = None, refresh: bool = False
) -> list[AuthorityDocument]:
    """Docs needing a metadata chunk, ordered by ingested_at desc.

    Default mode: only docs that have *no* chunk with ``chunk_role='metadata'``.
    When ``refresh=True``: every doc qualifies (caller is expected to delete
    the stale metadata chunks per doc right before re-embedding).
    """
    stmt = select(AuthorityDocument).order_by(AuthorityDocument.ingested_at.desc())
    if not refresh:
        has_header_subq = (
            select(AuthorityDocumentChunk.authority_document_id)
            .where(AuthorityDocumentChunk.chunk_role == "metadata")
            .distinct()
            .subquery()
        )
        stmt = stmt.where(AuthorityDocument.id.not_in(select(has_header_subq)))
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars())


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
) -> _Summary:
    summary = _Summary()
    docs = _docs_needing_header(session, limit=limit, refresh=refresh)
    summary.scanned = len(docs)
    logger.info(
        "docs %s title-header chunk: %d",
        "to refresh" if refresh else "needing",
        summary.scanned,
    )

    # Build (doc, header) pairs, skipping docs with no usable header text.
    pending: list[tuple[AuthorityDocument, str]] = []
    for doc in docs:
        header = _build_header_from_row(doc)
        if not header:
            summary.skipped_no_header_data += 1
            continue
        pending.append((doc, header))

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
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    embedder = build_provider()
    session_factory = get_session_factory()
    with session_factory() as session:
        summary = _run(
            session,
            embedder=embedder,
            limit=args.limit,
            batch_size=args.batch_size,
            refresh=args.refresh,
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
