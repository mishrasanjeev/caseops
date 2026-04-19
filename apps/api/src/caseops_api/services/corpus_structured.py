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

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.services.llm import (
    PURPOSE_METADATA_EXTRACT,
    AnthropicProvider,
    LLMCallContext,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponseFormatError,
    build_provider,
    generate_structured,
)

logger = logging.getLogger(__name__)


def _coerce_str_list(v):  # noqa: ANN001 — pydantic validator signature
    """Accept either a list or a single scalar; return a list of strs.

    Sonnet sometimes emits ``"M/s X & Ors."`` (a bare string) where the
    schema asks for ``list[str]`` because the model decides "there is
    only one respondent so I don't need a list". We coerce instead of
    rejecting — losing the doc to a list-vs-string nit costs more than
    accepting a one-element list."""
    if v is None or v == "":
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x) for x in v if x is not None]
    return [str(v)]


def _coerce_int_list(v):  # noqa: ANN001
    if v is None or v == "":
        return []
    if isinstance(v, int):
        return [v]
    if isinstance(v, list):
        out: list[int] = []
        for x in v:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out
    try:
        return [int(v)]
    except (TypeError, ValueError):
        return []


def _coerce_to_dict(v):  # noqa: ANN001
    """Coerce nullish / list / non-dict inputs to ``{}``.

    Sonnet sometimes emits ``advocates: []`` (an empty list) when no
    advocates were named, instead of the expected object/dict. Same
    pattern applies to ``parties``. Treat the empty-container case as
    "no data" and let the nested model populate its defaults."""
    if v is None or v == "":
        return {}
    if isinstance(v, list):
        return {}
    if isinstance(v, dict):
        return v
    return {}

# Version stamp encodes extraction tier so we never downgrade a
# Sonnet-annotated doc with a later Haiku pass:
#   1 = Haiku 4.5 (the budget tier)
#   2 = Sonnet 4.6 (the premium tier reserved for SC 1990-2025 English)
HAIKU_VERSION = 1
SONNET_VERSION = 2
STRUCTURED_VERSION = HAIKU_VERSION  # legacy alias; prefer tier-specific constants

_TIER_MODEL: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
}
_TIER_VERSION: dict[str, int] = {
    "haiku": HAIKU_VERSION,
    "sonnet": SONNET_VERSION,
}

# Anthropic pricing as of 2026-04 (USD per 1M tokens). Cache-hit reads
# are 10% of the input rate but we bill pessimistically since the
# corpus extraction sees no repeated system prompts across docs.
_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
}


def build_tier_provider(tier: str) -> LLMProvider:
    """Explicit provider for a named tier. Bypasses the per-purpose
    model routing in ``build_provider`` so the triage router can pick
    Sonnet on one doc and Haiku on the next within a single run."""
    settings = get_settings()
    model = _TIER_MODEL.get(tier)
    if not model:
        raise ValueError(f"unknown tier: {tier!r}")
    provider_name = (settings.llm_provider or "").lower()
    if provider_name in {"mock", "noop", "off"}:
        return build_provider(purpose=PURPOSE_METADATA_EXTRACT)
    if provider_name != "anthropic":
        raise LLMProviderError(
            "Tiered structured extraction requires CASEOPS_LLM_PROVIDER=anthropic; "
            f"got {provider_name!r}"
        )
    if not settings.llm_api_key:
        raise LLMProviderError("CASEOPS_LLM_API_KEY must be set for tiered extraction")
    return AnthropicProvider(
        model=model,
        api_key=settings.llm_api_key,
        prompt_cache=bool(getattr(settings, "llm_prompt_cache_enabled", True)),
    )


def completion_cost_usd(completion_provider: str, completion_model: str,
                        prompt_tokens: int, completion_tokens: int) -> float:
    rates = _PRICING_USD_PER_MTOK.get(completion_model)
    if not rates or completion_provider not in {"anthropic"}:
        return 0.0
    input_rate, output_rate = rates
    return (
        prompt_tokens * input_rate / 1_000_000
        + completion_tokens * output_rate / 1_000_000
    )


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

    _coerce_respondents = field_validator("respondents", mode="before")(_coerce_str_list)


class _Advocates(BaseModel):
    appellant_side: list[str] = Field(default_factory=list, max_length=30)
    respondent_side: list[str] = Field(default_factory=list, max_length=30)

    _coerce_a = field_validator("appellant_side", mode="before")(_coerce_str_list)
    _coerce_r = field_validator("respondent_side", mode="before")(_coerce_str_list)


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

    _coerce_secs = field_validator("sections_cited", mode="before")(_coerce_str_list)
    _coerce_auths = field_validator("authorities_cited", mode="before")(_coerce_str_list)
    _coerce_rel = field_validator("related_chunk_indexes", mode="before")(_coerce_int_list)


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

    _coerce_judges = field_validator("judges", mode="before")(_coerce_str_list)
    _coerce_doc_secs = field_validator("sections_cited", mode="before")(_coerce_str_list)
    _coerce_parties = field_validator("parties", mode="before")(_coerce_to_dict)
    _coerce_advocates = field_validator("advocates", mode="before")(_coerce_to_dict)
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
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    quality_score: float = 0.0
    quality_issues: tuple[str, ...] = ()
    tier: str = "haiku"


def _validate_quality(
    *,
    document: AuthorityDocument,
    payload: _ExtractionPayload,
    chunk_count: int,
    annotated: int,
) -> tuple[float, list[str]]:
    """Cheap structural validator: judge names appear in source text,
    chunk coverage is complete, case_number shape is plausible, title
    is non-empty. No LLM calls. Returns (score 0..1, issues)."""
    issues: list[str] = []
    text = (document.document_text or "")
    text_lower = text.lower()
    if payload.judges:
        missing = [
            j for j in payload.judges
            if j and j.strip().lower().split(",")[0].split()[0] not in text_lower
        ]
        if missing and len(missing) == len(payload.judges):
            issues.append(f"judges_not_in_text:{len(missing)}")
    if chunk_count and annotated < chunk_count:
        issues.append(f"chunks_incomplete:{annotated}/{chunk_count}")
    title = (payload.case_title or "").strip()
    if not title or title.lower().startswith("unknown"):
        issues.append("case_title_missing")
    cn = (payload.case_number or "").strip()
    if cn:
        import re as _re
        if not _re.search(r"(no\.?\s*\d|appeal|petition|writ|sp\b|civ|crl|slp|w\.p\.)",
                         cn.lower()):
            issues.append("case_number_shape")
    checks = 4
    score = max(0.0, (checks - len(issues)) / checks)
    return score, issues


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
    tier: str = "haiku",
) -> StructuredExtractionSummary:
    """Run the extractor on a single document and persist the payload.

    ``tier`` selects Haiku 4.5 (budget) vs Sonnet 4.6 (premium). The
    resolved tier stamps ``structured_version`` so a later run of the
    same tier skips this doc and a higher tier can still upgrade it.

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
            tier=tier,
        )

    if provider is None:
        try:
            llm = build_tier_provider(tier)
        except (ValueError, LLMProviderError):
            llm = build_provider(purpose=PURPOSE_METADATA_EXTRACT)
    else:
        llm = provider
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
    document.structured_version = _TIER_VERSION.get(tier, HAIKU_VERSION)
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

    cost = completion_cost_usd(
        completion.provider, completion.model,
        completion.prompt_tokens, completion.completion_tokens,
    )
    score, issues = _validate_quality(
        document=document, payload=payload,
        chunk_count=len(chunks), annotated=annotated,
    )
    return StructuredExtractionSummary(
        document_id=document.id,
        chunks_annotated=annotated,
        provider=completion.provider,
        model=completion.model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        cost_usd=cost,
        quality_score=score,
        quality_issues=tuple(issues),
        tier=tier,
    )


__all__ = [
    "HAIKU_VERSION",
    "SONNET_VERSION",
    "STRUCTURED_VERSION",
    "StructuredExtractionSummary",
    "build_tier_provider",
    "completion_cost_usd",
    "extract_and_persist_structured",
]
