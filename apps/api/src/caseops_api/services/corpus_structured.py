"""Structured extraction for authority documents (Corpus Layer 2).

One Haiku call per judgment produces a rich, typed shape that beats
flat-paragraph chunks on legal retrieval:

- Document-level: case_title, judges, parties, advocates, case_number,
  sections_cited, outcome.
- Per-chunk: chunk_role (facts / arguments / reasoning / directions /
  ratio / obiter / procedural / metadata / other), sections_cited,
  authorities_cited, outcome_tag, related_chunk_ids.

The prompt deliberately asks the model to assign a role to every
existing chunk (by ``chunk_index``) rather than re-chunking the text.
That preserves the vector embeddings we've already paid for — we add
typed metadata on top of them, not in place of them.

Idempotent: ``structured_version`` on each row records which pipeline
revision produced the payload. Bumping the version lets a future
prompt tweak invalidate exactly the rows that need re-extraction,
without flushing the entire 13 K corpus.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.services.llm import (
    PURPOSE_METADATA_EXTRACT,
    LLMCallContext,
    LLMMessage,
    LLMProvider,
    LLMResponseFormatError,
    build_provider,
    generate_structured,
)

logger = logging.getLogger(__name__)

STRUCTURED_VERSION = 1


ChunkRole = Literal[
    "metadata",
    "facts",
    "arguments",
    "reasoning",
    "directions",
    "ratio",
    "obiter",
    "procedural",
    "other",
]


class _Parties(BaseModel):
    appellant: str | None = Field(default=None, max_length=400)
    respondents: list[str] = Field(default_factory=list, max_length=30)


class _Advocates(BaseModel):
    appellant_side: list[str] = Field(default_factory=list, max_length=30)
    respondent_side: list[str] = Field(default_factory=list, max_length=30)


class _ChunkAnnotation(BaseModel):
    # Role is validated as a plain string; service-level ``_clamp_role``
    # normalises it after parsing. Keeping the LLM schema lenient
    # means a slight wording drift (e.g. "fact" vs "facts") doesn't
    # blow up the whole payload for what is a trivial alias.
    chunk_index: int
    role: str = Field(default="other", max_length=40)
    sections_cited: list[str] = Field(default_factory=list, max_length=80)
    authorities_cited: list[str] = Field(default_factory=list, max_length=80)
    outcome_tag: str | None = Field(default=None, max_length=240)
    related_chunk_indexes: list[int] = Field(default_factory=list, max_length=40)


class _ExtractionPayload(BaseModel):
    """Shape we ask Haiku to emit. Field constraints stay permissive
    so a slightly long judge name / citation list doesn't blow up
    the whole payload; we truncate at persist-time instead."""

    case_title: str | None = Field(default=None, max_length=800)
    judges: list[str] = Field(default_factory=list, max_length=40)
    parties: _Parties = Field(default_factory=_Parties)
    advocates: _Advocates = Field(default_factory=_Advocates)
    case_number: str | None = Field(default=None, max_length=480)
    sections_cited: list[str] = Field(default_factory=list, max_length=120)
    outcome: str | None = Field(default=None, max_length=240)
    chunks: list[_ChunkAnnotation] = Field(default_factory=list, max_length=600)


_VALID_ROLES: frozenset[str] = frozenset(
    {
        "metadata", "facts", "arguments", "reasoning", "directions",
        "ratio", "obiter", "procedural", "other",
    }
)


def _clamp_role(raw: str | None) -> str:
    if not raw:
        return "other"
    lowered = raw.strip().lower()
    if lowered in _VALID_ROLES:
        return lowered
    # Common near-misses from model drift.
    alias = {
        "fact": "facts", "argument": "arguments", "analysis": "reasoning",
        "holding": "ratio", "order": "directions", "disposition": "directions",
        "cover": "metadata", "caption": "metadata", "background": "facts",
        "submissions": "arguments", "contentions": "arguments",
        "conclusion": "reasoning", "prayer": "arguments",
    }
    return alias.get(lowered, "other")


@dataclass
class StructuredExtractionSummary:
    document_id: str
    chunks_annotated: int
    provider: str
    model: str


def _build_prompt(
    *, document: AuthorityDocument, chunks: list[AuthorityDocumentChunk]
) -> list[LLMMessage]:
    system = (
        "You label Indian court judgments. You must respond with valid "
        "JSON matching the caller's schema.\n\n"
        "CRITICAL OUTPUT REQUIREMENT: the `chunks` array MUST contain "
        "one object per input chunk — if the input has N chunks, you "
        "emit exactly N chunk annotations with chunk_index 0..N-1. "
        "This is not optional. Empty chunks[] is a defect.\n\n"
        "Do not invent facts. When a doc-level field is not knowable "
        "from the text, leave it null or empty."
    )

    # Cap each chunk excerpt so a 300-chunk judgment fits in the
    # prompt budget. Haiku context is 200K tokens; we keep plenty of
    # headroom.
    chunk_block_lines: list[str] = []
    for chunk in chunks:
        excerpt = (chunk.content or "")[:1200]
        chunk_block_lines.append(
            f"[chunk_index={chunk.chunk_index}]\n{excerpt}\n"
        )
    chunk_block = "\n---\n".join(chunk_block_lines)

    n_chunks = len(chunks)
    user = (
        f"This judgment has exactly {n_chunks} chunks (indexes 0 to "
        f"{n_chunks - 1}). Return JSON with:\n"
        "  - doc-level fields: case_title, judges, parties, advocates, "
        "case_number, sections_cited, outcome\n"
        f"  - chunks: array of EXACTLY {n_chunks} annotations, one per "
        f"input chunk, with chunk_index 0 to {n_chunks - 1}.\n\n"
        f"Known: court_name={document.court_name!r}, forum_level="
        f"{document.forum_level!r}, source_reference="
        f"{document.source_reference!r}.\n\n"
        "ROLE (pick one per chunk): metadata, facts, arguments, "
        "reasoning, ratio, obiter, directions, procedural, other.\n"
        "  - metadata    = cover/caption/bench line\n"
        "  - facts       = factual matrix, pleadings\n"
        "  - arguments   = counsel submissions, prayers\n"
        "  - reasoning   = court's analysis\n"
        "  - ratio       = decisive principle\n"
        "  - obiter      = asides not load-bearing\n"
        "  - directions  = operative order / relief\n"
        "  - procedural  = listings, adjournments\n"
        "  - other       = none of the above\n\n"
        "PER-CHUNK fields:\n"
        "  - sections_cited: statute sections referenced (e.g. "
        "'BNS s.318', 'BNSS s.483', 'CrPC s.438', 'CPC O.47 r.1', "
        "'Art. 226'). Normalise obvious variants.\n"
        "  - authorities_cited: case citations referenced "
        "(e.g. 'Gian Singh v. State of Punjab (2012) 10 SCC 303'). "
        "Verbatim — do not invent.\n"
        "  - outcome_tag: fill only when the chunk itself records a "
        "procedural outcome; otherwise null.\n"
        "  - related_chunk_indexes: up to 3 other chunk_index values "
        "topically linked (e.g. reasoning → facts it analyses).\n\n"
        "DOC-LEVEL OUTCOME: short label ('Disposed', 'Appeal allowed', "
        "'Petition dismissed', 'Bail granted', etc.).\n\n"
        "INPUT CHUNKS:\n"
        f"{chunk_block}\n"
        f"Remember: emit exactly {n_chunks} chunk annotations."
    )

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]


def extract_and_persist_structured(
    session: Session,
    *,
    document: AuthorityDocument,
    provider: LLMProvider | None = None,
) -> StructuredExtractionSummary:
    """Run the extractor on a single document and persist the payload.

    Safe to call repeatedly; the second call overwrites the first. The
    caller owns the transaction — we only ``flush``, not ``commit``.
    """
    chunks = list(
        session.scalars(
            select(AuthorityDocumentChunk)
            .where(AuthorityDocumentChunk.authority_document_id == document.id)
            .order_by(AuthorityDocumentChunk.chunk_index.asc())
        )
    )
    if not chunks:
        logger.warning(
            "document %s has zero chunks; nothing to structure", document.id
        )
        return StructuredExtractionSummary(
            document_id=document.id,
            chunks_annotated=0,
            provider="caseops-skip",
            model="none",
        )

    llm = provider or build_provider(purpose=PURPOSE_METADATA_EXTRACT)
    messages = _build_prompt(document=document, chunks=chunks)

    try:
        payload, completion = generate_structured(
            llm,
            schema=_ExtractionPayload,
            messages=messages,
            context=LLMCallContext(
                tenant_id=None,
                matter_id=None,
                purpose="authority.structured_extraction",
            ),
            temperature=0.0,
            max_tokens=8192,
        )
    except LLMResponseFormatError:
        logger.exception("structured extraction returned malformed JSON for %s", document.id)
        raise

    # Doc-level fields — only overwrite if the new value is non-empty;
    # preserve any values set by earlier passes (e.g. metadata_extract
    # pulled neutral_citation already).
    if payload.case_title and payload.case_title.strip():
        document.title = payload.case_title.strip()[:255]
    if payload.judges:
        document.judges_json = json.dumps(payload.judges, ensure_ascii=False)
        if not document.bench_name:
            document.bench_name = ", ".join(payload.judges)[:255]
    document.parties_json = json.dumps(
        payload.parties.model_dump(), ensure_ascii=False
    )
    document.advocates_json = json.dumps(
        payload.advocates.model_dump(), ensure_ascii=False
    )
    if payload.case_number and not document.case_reference:
        document.case_reference = payload.case_number[:255]
    if payload.case_number:
        document.case_number = payload.case_number[:255]
    if payload.sections_cited:
        document.sections_cited_json = json.dumps(
            payload.sections_cited, ensure_ascii=False
        )
    if payload.outcome:
        document.outcome_label = payload.outcome[:120]
    document.structured_version = STRUCTURED_VERSION
    session.add(document)

    # Per-chunk annotations. Primary match: LLM emits chunk_index that
    # lines up with the DB chunk_index. Fallback: if fewer annotations
    # than chunks, or the indexes are off-by-one (some models count
    # from 1), fall back to positional matching — pair the i-th
    # annotation with the i-th chunk. Silent drop was leaving 100%
    # of chunks unrolled on one model's output; positional fallback
    # recovers it cleanly.
    by_index: dict[int, _ChunkAnnotation] = {
        a.chunk_index: a for a in payload.chunks
    }
    ordered_annotations = sorted(payload.chunks, key=lambda a: a.chunk_index)
    matched_via_index = sum(
        1 for c in chunks if c.chunk_index in by_index
    )
    use_positional = (
        len(payload.chunks) > 0
        and matched_via_index < len(chunks) // 2
    )
    logger.info(
        "document %s: %d chunks, %d annotations returned, "
        "%d matched via chunk_index, positional_fallback=%s",
        document.id,
        len(chunks),
        len(payload.chunks),
        matched_via_index,
        use_positional,
    )
    annotated = 0
    for i, chunk in enumerate(chunks):
        ann = by_index.get(chunk.chunk_index)
        if ann is None and use_positional and i < len(ordered_annotations):
            ann = ordered_annotations[i]
        if ann is None:
            continue
        chunk.chunk_role = _clamp_role(ann.role)
        if ann.sections_cited:
            chunk.sections_cited_json = json.dumps(
                ann.sections_cited, ensure_ascii=False
            )
        if ann.authorities_cited:
            chunk.authorities_cited_json = json.dumps(
                ann.authorities_cited, ensure_ascii=False
            )
        if ann.outcome_tag:
            chunk.outcome_tag = ann.outcome_tag[:120]
        if ann.related_chunk_indexes:
            chunk.related_chunk_ids_json = json.dumps(
                ann.related_chunk_indexes, ensure_ascii=False
            )
        session.add(chunk)
        annotated += 1
    session.flush()

    return StructuredExtractionSummary(
        document_id=document.id,
        chunks_annotated=annotated,
        provider=completion.provider,
        model=completion.model,
    )


__all__ = [
    "STRUCTURED_VERSION",
    "StructuredExtractionSummary",
    "extract_and_persist_structured",
]
