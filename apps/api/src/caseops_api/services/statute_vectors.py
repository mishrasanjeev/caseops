"""Section-level vector index and retrieval over verified statute text.

J05/M04 and MOD-TS-017 (US-010, US-011; FT-117..FT-122, SEC-034, NFT-026).

One policy for every Act. Only sections that pass the canonical
selectability predicate (``services/statute_selection.py``) are chunked and
embedded; a section that later stops passing it (retired, quarantined,
withheld, unverified) loses its chunks on the next index run, and retrieval
re-checks the predicate and the section's source identity on every read, so a
stale chunk can never surface text that is no longer verified.

Chunks are verbatim slices of ``section_text`` cut at sub-section, clause,
proviso, Explanation and Illustration boundaries with a bounded size. Each
chunk records the section's ``source_sha256`` and ``source_version`` and the
hash of the exact text that was embedded, so a text, label or chunking change
re-embeds and a citation resolves to the exact verified provision.

Retrieval is hybrid: an exact section reference parsed from the question is
always ranked first; semantic neighbours follow, scored with the shared
lexical/vector blend from ``services/retrieval.py`` and reordered by the
configured reranker exactly as the judgment path does. A neighbour below the
embedding model's similarity floor is not evidence, so an unrelated question
gets no statute source rather than the nearest unrelated provision.

The index job mirrors the judgment title-chunk backfill: state-based (each run
compares what should be embedded with what is stored), committed per batch,
safe to re-run and to resume after an interruption, and it never holds a
database transaction across a provider call.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import Statute, StatuteSection, StatuteSectionChunk
from caseops_api.services.embeddings import (
    EmbeddingMoneyBudgetError,
    EmbeddingProvider,
    build_provider,
    cosine_similarity,
)
from caseops_api.services.matter_write_fence import require_read_only_upload_session
from caseops_api.services.retrieval import (
    HYBRID_LEXICAL_WEIGHT,
    HYBRID_VECTOR_WEIGHT,
    RetrievalCandidate,
    rank_candidates,
)
from caseops_api.services.statute_resolver import parse_section_string
from caseops_api.services.statute_selection import (
    is_selectable_statute_section,
    selectable_statute_section_sql,
)

logger = logging.getLogger(__name__)

CHUNKER_VERSION = "statute-chunker-v1"
# ~375 tokens of English statute text: one sub-section with its provisos in the
# common case, small enough that a long Schedule never becomes one vector.
MAX_CHUNK_CHARS = 1500
# pgvector's default ``hnsw.ef_search`` is 40; asking HNSW for more rows than
# that silently returns at most 40, so the candidate pool is pinned to it.
SEMANTIC_CANDIDATE_CHUNKS = 40
# SQLite (tests and offline development) scores in Python; bound the scan.
_SQLITE_MAX_CHUNKS = 20_000
_MAX_QUERY_CHARS = 600
# Cosine similarity below which a neighbour is not evidence of relevance.
# Similarity scales differ between embedding spaces, so the floor is per model.
# The voyage-4-large value is provisional until the production benchmark's
# negative queries confirm it (docs/runbooks/statute-vector-index-2026-11-26.md).
_MIN_SIMILARITY_BY_MODEL = {"voyage-4-large": 0.30}
_DEFAULT_MIN_SIMILARITY = 0.10

# A new unit starts at a line that opens a sub-section "(1)", a clause "(a)" or
# "(iv)", a proviso, an Explanation, Illustrations, a Schedule form, or a
# numbered section heading.
_BOUNDARY_RE = re.compile(
    r"^[ \t]*(?:\(\d+[A-Z]*\)|\([a-z]{1,4}\)|Provided\b|Explanation\b|"
    r"Illustrations?\b|FORM\s+No\b|\d+[A-Z]*\.\s)",
    re.MULTILINE,
)

MatchKind = Literal["exact_reference", "semantic"]


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #


def _trim(text_value: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text_value[start].isspace():
        start += 1
    while end > start and text_value[end - 1].isspace():
        end -= 1
    return start, end


def _split_long(text_value: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split one oversized unit at line breaks, then at spaces."""
    pieces: list[tuple[int, int]] = []
    line_start = start
    for match in re.finditer(r"\n", text_value[start:end]):
        cut = start + match.end()
        pieces.append((line_start, cut))
        line_start = cut
    pieces.append((line_start, end))
    bounded: list[tuple[int, int]] = []
    for piece_start, piece_end in pieces:
        while piece_end - piece_start > MAX_CHUNK_CHARS:
            cut = text_value.rfind(
                " ", piece_start + MAX_CHUNK_CHARS // 2, piece_start + MAX_CHUNK_CHARS
            )
            if cut <= piece_start:
                cut = piece_start + MAX_CHUNK_CHARS
            bounded.append((piece_start, cut))
            piece_start = cut
        if piece_end > piece_start:
            bounded.append((piece_start, piece_end))
    return bounded


def chunk_section_text(section_text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` spans; ``section_text[start:end]`` is each chunk.

    Spans are trimmed of surrounding whitespace, never overlap, appear in
    order and are at most ``MAX_CHUNK_CHARS`` long.
    """
    start, end = _trim(section_text, 0, len(section_text))
    if start >= end:
        return []
    if end - start <= MAX_CHUNK_CHARS:
        return [(start, end)]
    inner = {match.start() for match in _BOUNDARY_RE.finditer(section_text)}
    boundaries = sorted({start} | {offset for offset in inner if start < offset < end})
    units = list(zip(boundaries, [*boundaries[1:], end], strict=True))
    pieces: list[tuple[int, int]] = []
    for unit_start, unit_end in units:
        if unit_end - unit_start <= MAX_CHUNK_CHARS:
            pieces.append((unit_start, unit_end))
        else:
            pieces.extend(_split_long(section_text, unit_start, unit_end))
    spans: list[tuple[int, int]] = []
    current: tuple[int, int] | None = None
    for piece_start, piece_end in pieces:
        if current is None:
            current = (piece_start, piece_end)
        elif piece_end - current[0] <= MAX_CHUNK_CHARS:
            current = (current[0], piece_end)
        else:
            spans.append(current)
            current = (piece_start, piece_end)
    if current is not None:
        spans.append(current)
    trimmed = [_trim(section_text, span_start, span_end) for span_start, span_end in spans]
    return [(span_start, span_end) for span_start, span_end in trimmed if span_end > span_start]


def _section_heading(statute: Statute, section: StatuteSection) -> str:
    act = (statute.long_name or statute.short_name).strip()
    label = (section.section_label or "").strip()
    heading = f"{act} - {section.section_number}"
    return f"{heading}: {label}" if label else heading


def embedding_text(statute: Statute, section: StatuteSection, content: str) -> str:
    """The exact text sent to the provider: a citation heading, then the passage."""
    return f"{_section_heading(statute, section)}\n{content}"


@dataclass(frozen=True)
class PlannedChunk:
    chunk_index: int
    char_start: int
    char_end: int
    content: str
    embedded_text: str
    embedded_text_sha256: str


@dataclass(frozen=True)
class SectionPlan:
    section_id: str
    statute_id: str
    section_number: str
    section_label: str | None
    source_sha256: str
    source_version: int
    exact_source_version: str
    chunks: tuple[PlannedChunk, ...]

    def fingerprint(self, *, model: str, dimensions: int) -> tuple:
        return (
            self.source_sha256,
            self.source_version,
            model,
            dimensions,
            CHUNKER_VERSION,
            tuple((chunk.chunk_index, chunk.embedded_text_sha256) for chunk in self.chunks),
        )


def plan_section(section: StatuteSection, statute: Statute) -> SectionPlan:
    section_text = section.section_text or ""
    chunks = []
    for index, (start, end) in enumerate(chunk_section_text(section_text)):
        content = section_text[start:end]
        embedded = embedding_text(statute, section, content)
        chunks.append(
            PlannedChunk(
                chunk_index=index,
                char_start=start,
                char_end=end,
                content=content,
                embedded_text=embedded,
                embedded_text_sha256=hashlib.sha256(embedded.encode("utf-8")).hexdigest(),
            )
        )
    return SectionPlan(
        section_id=section.id,
        statute_id=section.statute_id,
        section_number=section.section_number,
        section_label=section.section_label,
        source_sha256=section.source_sha256 or "",
        source_version=section.source_version,
        exact_source_version=section.exact_source_version or "",
        chunks=tuple(chunks),
    )


# --------------------------------------------------------------------------- #
# Index job
# --------------------------------------------------------------------------- #


@dataclass
class StatuteIndexSummary:
    model: str
    dimensions: int
    selectable_sections: int = 0
    up_to_date_sections: int = 0
    sections_to_embed: int = 0
    chunks_to_embed: int = 0
    estimated_tokens: int = 0
    embedded_sections: int = 0
    embedded_chunks: int = 0
    removed_sections: int = 0
    removed_chunks: int = 0
    changed_during_embedding: int = 0
    errors: int = 0
    stop_reason: str | None = None
    dry_run: bool = False

    def as_line(self) -> str:
        return (
            "statute index: "
            f"mode={'dry-run' if self.dry_run else 'sync'} model={self.model} "
            f"dimensions={self.dimensions} selectable_sections={self.selectable_sections} "
            f"up_to_date={self.up_to_date_sections} to_embed_sections={self.sections_to_embed} "
            f"to_embed_chunks={self.chunks_to_embed} estimated_tokens={self.estimated_tokens} "
            f"embedded_sections={self.embedded_sections} embedded_chunks={self.embedded_chunks} "
            f"removed_sections={self.removed_sections} removed_chunks={self.removed_chunks} "
            f"changed_during_embedding={self.changed_during_embedding} errors={self.errors} "
            f"stop_reason={self.stop_reason or 'none'}"
        )


def _selectable_rows(session: Session, section_ids: Sequence[str] | None = None):
    statement = (
        select(StatuteSection, Statute)
        .join(Statute, Statute.id == StatuteSection.statute_id)
        .where(selectable_statute_section_sql())
        .order_by(StatuteSection.statute_id, StatuteSection.ordinal, StatuteSection.id)
    )
    if section_ids is not None:
        statement = statement.where(StatuteSection.id.in_(section_ids))
    return session.execute(statement).all()


def _stored_fingerprints(session: Session) -> dict[str, tuple]:
    rows = session.execute(
        select(
            StatuteSectionChunk.section_id,
            StatuteSectionChunk.chunk_index,
            StatuteSectionChunk.embedded_text_sha256,
            StatuteSectionChunk.source_sha256,
            StatuteSectionChunk.source_version,
            StatuteSectionChunk.embedding_model,
            StatuteSectionChunk.embedding_dimensions,
            StatuteSectionChunk.chunker_version,
        ).order_by(StatuteSectionChunk.section_id, StatuteSectionChunk.chunk_index)
    ).all()
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row.section_id].append(row)
    stored: dict[str, tuple] = {}
    for section_id, chunks in grouped.items():
        first = chunks[0]
        uniform = all(
            (
                chunk.source_sha256,
                chunk.source_version,
                chunk.embedding_model,
                chunk.embedding_dimensions,
                chunk.chunker_version,
            )
            == (
                first.source_sha256,
                first.source_version,
                first.embedding_model,
                first.embedding_dimensions,
                first.chunker_version,
            )
            for chunk in chunks
        )
        stored[section_id] = (
            (
                first.source_sha256,
                first.source_version,
                first.embedding_model,
                first.embedding_dimensions,
                first.chunker_version,
                tuple((chunk.chunk_index, chunk.embedded_text_sha256) for chunk in chunks),
            )
            if uniform
            else ("mixed",)
        )
    return stored


def _estimate_tokens(texts: Iterable[str]) -> int:
    # The same ~4 characters per token heuristic the Voyage batcher uses.
    return sum(max(1, len(value) // 4) for value in texts)


def _encode_vector(vector: Sequence[float]) -> str:
    return json.dumps([round(float(value), 6) for value in vector], separators=(",", ":"))


def _postgres(session: Session) -> bool:
    bind = session.get_bind()
    return bind.dialect.name == "postgresql"


def _batches(plans: list[SectionPlan], batch_size: int) -> list[list[SectionPlan]]:
    batches: list[list[SectionPlan]] = []
    current: list[SectionPlan] = []
    count = 0
    for plan in plans:
        size = len(plan.chunks)
        if current and count + size > batch_size:
            batches.append(current)
            current, count = [], 0
        current.append(plan)
        count += size
    if current:
        batches.append(current)
    return batches


def sync_statute_section_chunks(
    session: Session,
    *,
    embedder: EmbeddingProvider,
    batch_size: int = 64,
    limit: int | None = None,
    dry_run: bool = False,
) -> StatuteIndexSummary:
    """Bring ``statute_section_chunks`` in line with the selectable sections.

    Removes chunks of sections that are no longer selectable, then embeds every
    selectable section whose stored chunks do not match its current text, label,
    source identity, chunking rule or the provider's model and dimensions.
    ``limit`` caps the number of sections embedded in this run.
    """
    require_read_only_upload_session(
        session, detail="The statute index requires a session without caller-owned writes."
    )
    summary = StatuteIndexSummary(
        model=embedder.model, dimensions=embedder.dimensions, dry_run=dry_run
    )
    plans = {
        section.id: plan_section(section, statute) for section, statute in _selectable_rows(session)
    }
    summary.selectable_sections = len(plans)
    stored = _stored_fingerprints(session)
    # Chunks of a section that is no longer selectable (or has no text left)
    # are removed.
    stale_ids = sorted(
        set(stored) - {section_id for section_id, plan in plans.items() if plan.chunks}
    )
    pending: list[SectionPlan] = []
    for plan in plans.values():
        if not plan.chunks:
            continue
        if stored.get(plan.section_id) == plan.fingerprint(
            model=embedder.model, dimensions=embedder.dimensions
        ):
            summary.up_to_date_sections += 1
        else:
            pending.append(plan)
    if limit is not None:
        pending = pending[: max(0, limit)]
    summary.sections_to_embed = len(pending)
    summary.chunks_to_embed = sum(len(plan.chunks) for plan in pending)
    summary.estimated_tokens = _estimate_tokens(
        chunk.embedded_text for plan in pending for chunk in plan.chunks
    )
    summary.removed_sections = len(stale_ids)
    if dry_run:
        summary.removed_chunks = 0
        session.rollback()
        return summary

    for offset in range(0, len(stale_ids), 200):
        result = session.execute(
            delete(StatuteSectionChunk).where(
                StatuteSectionChunk.section_id.in_(stale_ids[offset : offset + 200])
            )
        )
        summary.removed_chunks += result.rowcount or 0
    session.commit()

    for batch in _batches(pending, max(1, batch_size)):
        texts = [chunk.embedded_text for plan in batch for chunk in plan.chunks]
        try:
            result = embedder.embed(texts, input_type="document")
        except EmbeddingMoneyBudgetError:
            summary.stop_reason = "ai_money_budget_denied"
            logger.warning("Statute index stopped: the AI money budget denied further submission.")
            break
        except Exception:  # noqa: BLE001 - one failed batch must not end the run.
            logger.exception("statute index embedding batch failed")
            summary.errors += len(batch)
            continue
        if len(result.vectors) != len(texts) or result.dimensions != embedder.dimensions:
            summary.errors += len(batch)
            logger.warning("statute index provider returned an unexpected vector shape")
            continue

        # Lock the sections, in ID order, and re-plan from the current rows: a
        # section whose text, label or status changed while the provider was
        # working is skipped and picked up by the next run.
        batch_ids = sorted(plan.section_id for plan in batch)
        current_rows = session.execute(
            select(StatuteSection, Statute)
            .join(Statute, Statute.id == StatuteSection.statute_id)
            .where(StatuteSection.id.in_(batch_ids))
            .order_by(StatuteSection.id)
            .with_for_update(of=StatuteSection)
            .execution_options(populate_existing=True)
        ).all()
        current = {
            section.id: plan_section(section, statute)
            for section, statute in current_rows
            if is_selectable_statute_section(section)
        }
        vectors = iter(result.vectors)
        now = datetime.now(UTC)
        written: list[tuple[StatuteSectionChunk, list[float]]] = []
        for plan in batch:
            plan_vectors = [next(vectors) for _ in plan.chunks]
            fresh = current.get(plan.section_id)
            if fresh is None or fresh != plan:
                summary.changed_during_embedding += 1
                continue
            session.execute(
                delete(StatuteSectionChunk).where(StatuteSectionChunk.section_id == plan.section_id)
            )
            for chunk, vector in zip(plan.chunks, plan_vectors, strict=True):
                row = StatuteSectionChunk(
                    statute_id=plan.statute_id,
                    section_id=plan.section_id,
                    section_number=plan.section_number,
                    section_label=plan.section_label,
                    chunk_index=chunk.chunk_index,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    content=chunk.content,
                    source_sha256=plan.source_sha256,
                    source_version=plan.source_version,
                    exact_source_version=plan.exact_source_version,
                    chunker_version=CHUNKER_VERSION,
                    embedded_text_sha256=chunk.embedded_text_sha256,
                    embedding_model=result.model,
                    embedding_dimensions=result.dimensions,
                    embedding_json=_encode_vector(vector),
                    embedded_at=now,
                )
                session.add(row)
                written.append((row, vector))
            summary.embedded_sections += 1
            summary.embedded_chunks += len(plan.chunks)
        session.flush()
        if written and _postgres(session):
            for row, vector in written:
                session.execute(
                    text(
                        "UPDATE statute_section_chunks "
                        "SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"
                    ),
                    {"vec": _encode_vector(vector), "id": row.id},
                )
        session.commit()
        logger.info(
            "statute index batch: sections=%d chunks=%d (running total sections=%d)",
            len(batch),
            len(texts),
            summary.embedded_sections,
        )
    return summary


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StatuteSectionHit:
    section: StatuteSection
    statute: Statute
    match: MatchKind
    score: float
    similarity: float | None = None
    # Verbatim span of ``section.section_text`` that matched (whole text for an
    # exact reference).
    char_start: int = 0
    char_end: int = 0
    chunk_ids: tuple[str, ...] = field(default_factory=tuple)


def min_similarity_for(model: str) -> float:
    return _MIN_SIMILARITY_BY_MODEL.get(model, _DEFAULT_MIN_SIMILARITY)


def _exact_hit(session: Session, query: str) -> StatuteSectionHit | None:
    reference = parse_section_string(query)
    if reference is None:
        return None
    row = session.execute(
        select(StatuteSection, Statute)
        .join(Statute, Statute.id == StatuteSection.statute_id)
        .where(
            StatuteSection.statute_id == reference[0],
            StatuteSection.section_number == reference[1],
        )
    ).first()
    if row is None or not is_selectable_statute_section(row[0]):
        return None
    section, statute = row
    return StatuteSectionHit(
        section=section,
        statute=statute,
        match="exact_reference",
        score=float("inf"),
        char_start=0,
        char_end=len(section.section_text or ""),
    )


def _nearest_chunks(
    session: Session, *, query_vector: list[float], model: str, dimensions: int
) -> list[tuple[str, float]]:
    """``(chunk_id, cosine similarity)`` of the nearest chunks of this model."""
    if _postgres(session):
        # The model filter is applied after the index scan: with it in the WHERE
        # clause PostgreSQL prefers the embedding_model btree plus a full sort
        # over the HNSW index. Every chunk normally carries one model, because
        # the index job re-embeds all sections when the model changes.
        literal = "[" + ",".join(f"{value:.6f}" for value in query_vector) + "]"
        rows = session.execute(
            text(
                "SELECT id, embedding_model, embedding_dimensions, "
                "1 - (embedding_vector <=> CAST(:query AS vector)) AS similarity "
                "FROM statute_section_chunks WHERE embedding_vector IS NOT NULL "
                "ORDER BY embedding_vector <=> CAST(:query AS vector) LIMIT :limit"
            ),
            {"query": literal, "limit": SEMANTIC_CANDIDATE_CHUNKS},
        ).all()
        return [
            (str(row.id), float(row.similarity))
            for row in rows
            if row.embedding_model == model and row.embedding_dimensions == dimensions
        ]
    rows = session.execute(
        select(StatuteSectionChunk.id, StatuteSectionChunk.embedding_json)
        .where(
            StatuteSectionChunk.embedding_model == model,
            StatuteSectionChunk.embedding_dimensions == dimensions,
        )
        .limit(_SQLITE_MAX_CHUNKS)
    ).all()
    scored = []
    for chunk_id, raw in rows:
        try:
            vector = [float(value) for value in json.loads(raw)]
        except (TypeError, ValueError):
            continue
        scored.append((chunk_id, cosine_similarity(query_vector, vector)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:SEMANTIC_CANDIDATE_CHUNKS]


def _semantic_hits(
    session: Session,
    query: str,
    *,
    limit: int,
    exclude: set[str],
    embedder: EmbeddingProvider | None,
    min_similarity: float | None,
) -> list[StatuteSectionHit]:
    cleaned = " ".join(query.split())[:_MAX_QUERY_CHARS]
    if not cleaned or session.scalar(select(StatuteSectionChunk.id).limit(1)) is None:
        return []
    try:
        provider = embedder or build_provider()
        embedded = provider.embed([cleaned], input_type="query")
    except Exception:  # noqa: BLE001 - retrieval degrades to the exact path.
        logger.warning("statute query embedding unavailable; semantic statute retrieval skipped")
        return []
    if len(embedded.vectors) != 1:
        return []
    floor = min_similarity_for(embedded.model) if min_similarity is None else min_similarity
    neighbours = [
        (chunk_id, similarity)
        for chunk_id, similarity in _nearest_chunks(
            session,
            query_vector=embedded.vectors[0],
            model=embedded.model,
            dimensions=embedded.dimensions,
        )
        if similarity >= floor
    ]
    if not neighbours:
        return []
    similarity_by_chunk = dict(neighbours)
    chunks = {
        chunk.id: chunk
        for chunk in session.scalars(
            select(StatuteSectionChunk).where(StatuteSectionChunk.id.in_(similarity_by_chunk))
        )
    }
    sections = {
        section.id: (section, statute)
        for section, statute in session.execute(
            select(StatuteSection, Statute)
            .join(Statute, Statute.id == StatuteSection.statute_id)
            .where(StatuteSection.id.in_({chunk.section_id for chunk in chunks.values()}))
        ).all()
    }
    usable: list[tuple[StatuteSectionChunk, StatuteSection, Statute]] = []
    for chunk_id, _similarity in neighbours:
        chunk = chunks.get(chunk_id)
        if chunk is None or chunk.section_id in exclude:
            continue
        section, statute = sections.get(chunk.section_id, (None, None))
        # Re-check on read: the section must still be selectable and the chunk
        # must still be the verbatim text of the same source edition.
        if (
            section is None
            or not is_selectable_statute_section(section)
            or chunk.source_sha256 != section.source_sha256
            or chunk.source_version != section.source_version
            or (section.section_text or "")[chunk.char_start : chunk.char_end] != chunk.content
        ):
            continue
        usable.append((chunk, section, statute))
    if not usable:
        return []

    lexical = {
        result.attachment_id: result.score
        for result in rank_candidates(
            query=cleaned,
            candidates=[
                RetrievalCandidate(
                    attachment_id=chunk.id,
                    attachment_name=_section_heading(statute, section),
                    content=chunk.content,
                )
                for chunk, section, statute in usable
            ],
            limit=len(usable),
        )
    }
    best: dict[str, StatuteSectionHit] = {}
    for chunk, section, statute in usable:
        similarity = similarity_by_chunk[chunk.id]
        score = (HYBRID_LEXICAL_WEIGHT * lexical.get(chunk.id, 0)) + (
            HYBRID_VECTOR_WEIGHT * similarity * 240
        )
        current = best.get(section.id)
        if current is not None and current.score >= score:
            continue
        best[section.id] = StatuteSectionHit(
            section=section,
            statute=statute,
            match="semantic",
            score=score,
            similarity=similarity,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            chunk_ids=(chunk.id,),
        )
    ordered = sorted(best.values(), key=lambda hit: hit.score, reverse=True)
    if len(ordered) > limit:
        # Same contract as the judgment path: the reranker reorders the
        # over-fetched candidates; any reranker failure keeps first-stage order.
        try:
            from caseops_api.services.reranker import RerankerCandidate, build_reranker

            by_id = {hit.section.id: hit for hit in ordered}
            reranked = build_reranker().rerank(
                cleaned,
                [
                    RerankerCandidate(
                        identifier=hit.section.id,
                        title=_section_heading(hit.statute, hit.section),
                        text=(hit.section.section_text or "")[hit.char_start : hit.char_end][:500],
                    )
                    for hit in ordered[: limit * 3]
                ],
                top_k=limit,
            )
            reordered = [by_id[item.identifier] for item in reranked if item.identifier in by_id]
            if reordered:
                ordered = reordered
        except Exception:  # noqa: BLE001 - reranking never breaks retrieval.
            logger.warning("statute reranker unavailable; first-stage order kept")
    return ordered[:limit]


def search_statute_sections(
    session: Session,
    query: str,
    *,
    limit: int = 10,
    embedder: EmbeddingProvider | None = None,
    min_similarity: float | None = None,
) -> list[StatuteSectionHit]:
    """Verified statute sections for a question, exact reference first.

    Reads only the global statute tables. The exact section a question names
    always ranks first; semantic neighbours follow. Every returned section
    passes the canonical selectability predicate at read time.
    ``min_similarity`` overrides the model's floor for benchmark calibration
    only; product callers leave it unset.
    """
    hits: list[StatuteSectionHit] = []
    exact = _exact_hit(session, query)
    if exact is not None:
        hits.append(exact)
    remaining = limit - len(hits)
    if remaining > 0:
        hits.extend(
            _semantic_hits(
                session,
                query,
                limit=remaining,
                exclude={hit.section.id for hit in hits},
                embedder=embedder,
                min_similarity=min_similarity,
            )
        )
    return hits[:limit]


__all__ = [
    "CHUNKER_VERSION",
    "MAX_CHUNK_CHARS",
    "PlannedChunk",
    "SectionPlan",
    "StatuteIndexSummary",
    "StatuteSectionHit",
    "chunk_section_text",
    "embedding_text",
    "min_similarity_for",
    "plan_section",
    "search_statute_sections",
    "sync_statute_section_chunks",
]
