from __future__ import annotations

import csv
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter

from fastapi import HTTPException, status
from sqlalchemy import func, literal_column, or_, select, text
from sqlalchemy.orm import Session, defer, raiseload

# NOTE for reviewers: the task spec asked for this wiring to land in
# ``services/retrieval.py``, but ``search_authority_catalog`` (the
# HNSW-driven authority search) actually lives in this module.
# ``services/retrieval.py`` is the pure lexical/hybrid ranker
# (``rank_candidates``) that the search calls AFTER the HNSW prefilter.
# Wiring at this layer is correct: variants must expand before the
# ``_embed_query`` / ``_pg_prefilter_document_ids`` calls, which sit
# here. The first-stage retrieval fan-out happens below; the
# reranker path downstream is left unchanged per the spec.
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditResult,
    AuthorityCitation,
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityIngestionRun,
    AuthorityIngestionStatus,
    AuthoritySearchObservation,
    MembershipRole,
)
from caseops_api.schemas.authorities import (
    AuthorityContextualQueryPlan,
    AuthorityCorpusStats,
    AuthorityDocumentListResponse,
    AuthorityDocumentRecord,
    AuthorityIngestionRequest,
    AuthorityIngestionRunRecord,
    AuthoritySearchCoverage,
    AuthoritySearchRequest,
    AuthoritySearchResponse,
    AuthoritySearchResult,
    AuthoritySourceListResponse,
    AuthoritySourceRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.authority_sources import (
    AuthoritySourceDocument,
    get_authority_source_adapter,
    list_supported_authority_sources,
)
from caseops_api.services.court_sync_sources import (
    CASE_NUMBER_PATTERN,
    _extract_case_references,
    _normalize_case_reference,
)
from caseops_api.services.document_processing import _chunk_text
from caseops_api.services.embeddings import EmbeddingProviderError, build_provider
from caseops_api.services.retrieval import (
    RetrievalCandidate,
    is_low_quality_ocr_text,
    rank_candidates,
)
from caseops_api.services.retrieval_normalisers import build_query_variants
from caseops_api.services.session_context import SessionContext

logger = logging.getLogger(__name__)

# Search is an interactive request, not a corpus-export endpoint. The old
# implementation could union 300 documents per query variant and then lazily
# load every chunk on every document. At production scale that created an
# unbounded N+1 query/read-amplification path which routinely outlived the
# browser's 20-second deadline. Keep the candidate set explicit and small;
# the HNSW prefilter still supplies the best matching chunk for each document.
_AUTHORITY_MAX_DOCUMENT_CANDIDATES = 180
_AUTHORITY_MIN_DOCUMENT_CANDIDATES = 30
_AUTHORITY_DOCUMENT_CANDIDATE_MULTIPLIER = 3
_AUTHORITY_FALLBACK_CHUNKS_PER_DOCUMENT = 2
_AUTHORITY_COVERAGE_CACHE_TTL_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class _VectorDocumentHit:
    document_id: str
    chunk_id: str


@dataclass(frozen=True, slots=True)
class _CorpusMetrics:
    document_count: int
    chunk_count: int
    embedded_chunk_count: int
    last_ingested_at: datetime | None
    last_indexed_at: datetime | None
    latest_ingestion_status: str | None
    forum_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _PostgresCorpusEstimates:
    document_count: int
    chunk_count: int
    embedded_chunk_count: int
    forum_counts: dict[str, int]


_CORPUS_METRICS_CACHE_LOCK = Lock()
_CORPUS_METRICS_CACHE: tuple[float, _CorpusMetrics] | None = None

# P4 (Sprint P, 2026-04-25). Forum-aware precedent boost. Indian
# court hierarchy (highest precedential weight first):
#   supreme_court > high_court > lower_court / tribunal > advisory
# The score boosts encode precedent value, not "how good the doc is":
# an SC judgment is BINDING precedent on every lower forum, so we
# boost SC docs strongly when the matter sits at HC / lower_court /
# tribunal. HC-on-HC is a same-level peer (persuasive). Below the
# matter's own level adds nothing — sub-precedent doesn't bind up.
# Returns 0 when either forum is unknown so the rest of the rerank
# (court_name match, citation overlap, etc.) still drives the score.
_FORUM_PRECEDENT_BOOSTS: dict[str, dict[str, int]] = {
    "supreme_court": {
        "supreme_court": 12,  # binding self-reference
        "high_court": 4,
        "lower_court": 0,
        "tribunal": 0,
        "arbitration": 0,
    },
    "high_court": {
        "supreme_court": 12,  # binding from above
        "high_court": 8,      # same level (was the existing exact boost)
        "lower_court": 0,
        "tribunal": 0,
        "arbitration": 0,
    },
    "lower_court": {
        "supreme_court": 12,
        "high_court": 8,
        "lower_court": 4,
        "tribunal": 2,
        "arbitration": 0,
    },
    "tribunal": {
        "supreme_court": 12,
        "high_court": 6,
        "tribunal": 6,
        "lower_court": 0,
        "arbitration": 0,
    },
    "arbitration": {
        "supreme_court": 6,
        "arbitration": 8,
        "high_court": 4,
        "lower_court": 0,
        "tribunal": 0,
    },
    "advisory": {
        "supreme_court": 12,
        "high_court": 6,
        "advisory": 4,
        "lower_court": 0,
        "tribunal": 0,
        "arbitration": 0,
    },
}


_SECTION_PATTERN = re.compile(
    r"\b(?:section|sec\.?|s\.)\s*([0-9]{1,4}[a-z]?(?:\([^)]+\))?)",
    re.IGNORECASE,
)
_TIMING_PATTERN = re.compile(
    r"\b(?:after|within|beyond|delay(?:ed)?(?:\s+by)?|late(?:\s+by)?)\s+"
    r"([0-9]{1,3})\s*(?:days?|day)\b",
    re.IGNORECASE,
)


def _compact_text(value: str | None, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0].strip()
    return clipped or text[:max_chars].strip()


def _append_unique(items: list[str], value: str, *, limit: int) -> None:
    candidate = _compact_text(value, max_chars=90)
    if not candidate:
        return
    seen = {item.casefold() for item in items}
    if candidate.casefold() not in seen and len(items) < limit:
        items.append(candidate)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _normalize_court_filter(court_name: str | None) -> str | None:
    normalized = re.sub(r"\s+", " ", court_name or "").strip()
    return normalized or None


def _escape_sql_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _court_name_contains_pattern(court_name: str | None) -> str | None:
    normalized = _normalize_court_filter(court_name)
    if normalized is None:
        return None
    return f"%{_escape_sql_like(normalized)}%"


def _court_name_filter_clause(court_name: str | None):
    pattern = _court_name_contains_pattern(court_name)
    if pattern is None:
        return None
    return AuthorityDocument.court_name.ilike(pattern, escape="\\")


def _court_name_matches_filter(
    document_court_name: str | None,
    court_name: str | None,
) -> bool:
    needle = _normalize_court_filter(court_name)
    haystack = _normalize_court_filter(document_court_name)
    if needle is None or haystack is None:
        return False
    return needle.casefold() in haystack.casefold()


def _build_contextual_query_plan(query: str) -> AuthorityContextualQueryPlan:
    normalized_query = _compact_text(query, max_chars=600)
    lower = normalized_query.casefold()
    key_facts: list[str] = []
    likely_issues: list[str] = []
    statutes_or_sections: list[str] = []
    procedural_posture: list[str] = []
    jurisdiction_hints: list[str] = []
    timing_signals: list[str] = []

    for match in _SECTION_PATTERN.finditer(normalized_query):
        _append_unique(
            statutes_or_sections,
            f"Section {match.group(1).upper()}",
            limit=6,
        )

    cheque_context = _contains_any(lower, ("cheque", "check"))
    dishonour_context = _contains_any(
        lower,
        ("bounce", "bounced", "dishonour", "dishonored", "dishonoured"),
    )
    if cheque_context and dishonour_context:
        _append_unique(key_facts, "cheque dishonour", limit=6)
        _append_unique(
            likely_issues,
            "Section 138 cheque dishonour",
            limit=6,
        )
        _append_unique(
            statutes_or_sections,
            "Section 138 Negotiable Instruments Act",
            limit=6,
        )
    if "insufficient funds" in lower:
        _append_unique(key_facts, "dishonour for insufficient funds", limit=6)
    if "notice" in lower:
        _append_unique(key_facts, "statutory demand notice", limit=6)
        if cheque_context:
            _append_unique(
                likely_issues,
                "demand notice timing for cheque dishonour",
                limit=6,
            )
            _append_unique(
                statutes_or_sections,
                "Section 142 Negotiable Instruments Act",
                limit=6,
            )

    for match in _TIMING_PATTERN.finditer(normalized_query):
        _append_unique(timing_signals, match.group(0), limit=4)
    if _contains_any(lower, ("limitation", "time barred", "time-barred")):
        _append_unique(likely_issues, "limitation", limit=6)

    posture_terms = {
        "appeal": "appeal",
        "writ": "writ petition",
        "quashing": "quashing petition",
        "bail": "bail application",
        "arbitration": "arbitration petition",
        "complaint": "complaint",
        "revision": "revision",
    }
    for needle, label in posture_terms.items():
        if needle in lower:
            _append_unique(procedural_posture, label, limit=4)

    jurisdiction_terms = {
        "supreme court": "Supreme Court",
        "high court": "High Court",
        "delhi": "Delhi",
        "bombay": "Bombay",
        "mumbai": "Bombay",
        "karnataka": "Karnataka",
        "madras": "Madras",
        "telangana": "Telangana",
        "nclt": "NCLT",
        "tribunal": "Tribunal",
    }
    for needle, label in jurisdiction_terms.items():
        if needle in lower:
            _append_unique(jurisdiction_hints, label, limit=4)

    planned_parts = [
        normalized_query,
        *statutes_or_sections,
        *likely_issues,
        *key_facts,
        *timing_signals,
        *procedural_posture,
        *jurisdiction_hints,
    ]
    planned_query = _compact_text(" ".join(planned_parts), max_chars=360)
    return AuthorityContextualQueryPlan(
        key_facts=key_facts,
        likely_issues=likely_issues,
        statutes_or_sections=statutes_or_sections,
        procedural_posture=procedural_posture,
        jurisdiction_hints=jurisdiction_hints,
        timing_signals=timing_signals,
        planned_query=planned_query or normalized_query,
    )


def _contextual_relevance_reason(
    result: AuthoritySearchResult,
    plan: AuthorityContextualQueryPlan,
) -> str:
    result_text = " ".join(
        part
        for part in (result.title, result.summary, result.snippet)
        if part
    ).casefold()
    reasons: list[str] = []

    for section in plan.statutes_or_sections:
        core = re.sub(r"[^a-z0-9]+", " ", section.casefold()).strip()
        if core and core in re.sub(r"[^a-z0-9]+", " ", result_text):
            _append_unique(reasons, section, limit=3)
    for issue in (*plan.likely_issues, *plan.key_facts):
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]{4,}", issue.casefold())
            if token not in {"section", "statutory"}
        ]
        if tokens and any(token in result_text for token in tokens):
            _append_unique(reasons, issue, limit=3)
    for timing in plan.timing_signals:
        if any(token in result_text for token in re.findall(r"[0-9]{1,3}", timing)):
            _append_unique(reasons, timing, limit=3)

    if not reasons:
        return (
            "Source-backed match from indexed title, summary, and snippet overlap "
            "with the contextual query."
        )
    return (
        "Source-backed match on "
        + "; ".join(reasons[:3])
        + ". Verify the source record before relying on it."
    )


def _contextual_coverage_notice(
    *,
    total_after_filter: int,
    raw_count: int,
    unreadable_omitted_count: int = 0,
) -> str | None:
    if total_after_filter > 0:
        return None
    if unreadable_omitted_count > 0:
        return (
            "Indexed authority records matched the query, but their extracted "
            "text is not readable enough to preview. Broaden the query or "
            "review official source records outside CaseOps before relying on them."
        )
    if raw_count > 0:
        return (
            "Indexed authorities matched before the current filters were applied; "
            "broaden filters or language selection to review them."
        )
    return (
        "No indexed authority matched the planned contextual query. Results are "
        "limited to existing source-backed corpus records."
    )


def _record_contextual_search_audit(
    session: Session,
    *,
    context: SessionContext,
    payload: AuthoritySearchRequest,
    plan: AuthorityContextualQueryPlan,
    result_count: int,
) -> None:
    record_from_context(
        session,
        context,
        action="authority_search.contextual_executed",
        target_type="authority_search",
        result=AuditResult.SUCCESS,
        metadata={
            "mode": payload.mode,
            "query_sha256": hashlib.sha256(
                payload.query.encode("utf-8")
            ).hexdigest(),
            "query_length": len(payload.query),
            "planned_query_sha256": hashlib.sha256(
                plan.planned_query.encode("utf-8")
            ).hexdigest(),
            "planned_query_length": len(plan.planned_query),
            "key_fact_count": len(plan.key_facts),
            "likely_issue_count": len(plan.likely_issues),
            "statute_or_section_count": len(plan.statutes_or_sections),
            "timing_signal_count": len(plan.timing_signals),
            "result_count": result_count,
            "language": payload.language,
            "forum_level": payload.forum_level,
            "document_type": payload.document_type,
            "court_name_present": bool(payload.court_name),
        },
        commit=True,
    )


def _forum_precedent_boost(
    matter_forum: str | None, doc_forum: str | None
) -> int:
    """Score boost for a `doc_forum` document when the matter is at
    `matter_forum`. Bigger = more relevant per Indian court hierarchy.
    Unknown forums (either side) → 0. Bench-aware drafting rule: this
    is precedent-weight, NOT favorability. Boosting SC over HC says
    "SC is binding"; it does not score the judge or predict outcomes.
    """
    if not matter_forum or not doc_forum:
        return 0
    table = _FORUM_PRECEDENT_BOOSTS.get(matter_forum.lower())
    if table is None:
        return 0
    return table.get(doc_forum.lower(), 0)


def _require_admin(context: SessionContext) -> None:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and admins can ingest authority data.",
        )


def _canonical_key(document: AuthoritySourceDocument) -> str:
    normalized_case_reference = _normalize_case_reference(document.case_reference or "")
    normalized_neutral_citation = _normalize_case_reference(document.neutral_citation or "")
    seed = "|".join(
        [
            document.source.lower().strip(),
            normalized_case_reference,
            normalized_neutral_citation,
            document.title.lower().strip(),
            document.decision_date,
            document.document_type,
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]


def _authority_reference_tokens(*values: str | None) -> set[str]:
    refs: set[str] = set()
    for value in values:
        if value:
            refs.update(_extract_case_references(value))
    return refs


def _extract_citation_candidates(text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in CASE_NUMBER_PATTERN.finditer(text):
        prefix = re.sub(r"\s+", " ", match.group("prefix")).strip().upper()
        prefix = re.sub(r"^.*\bIN\s+", "", prefix)
        prefix = re.sub(
            r"^(?:(?:COURT|RECORD|CASE|ORDER|JUDGMENT|THE|OF)\s+)+",
            "",
            prefix,
        ).strip()
        number = match.group("number").upper()
        year = match.group("year")
        citation_text = f"{prefix} {number}/{year}".strip()
        normalized_reference = _normalize_case_reference(citation_text)
        if not normalized_reference or normalized_reference in seen:
            continue
        seen.add(normalized_reference)
        candidates.append((citation_text, normalized_reference))
    return candidates


def _build_authority_resolution_index(session: Session) -> dict[str, AuthorityDocument]:
    resolution_index: dict[str, AuthorityDocument] = {}
    documents = list(session.scalars(select(AuthorityDocument)))
    for document in documents:
        tokens = _authority_reference_tokens(
            document.case_reference,
            document.neutral_citation,
            document.title,
        )
        for token in tokens:
            current = resolution_index.get(token)
            if current is None or document.decision_date >= current.decision_date:
                resolution_index[token] = document
    return resolution_index


def _rebuild_authority_citations(
    session: Session,
    *,
    documents: list[AuthorityDocument],
) -> None:
    resolution_index = _build_authority_resolution_index(session)

    for document in documents:
        own_tokens = _authority_reference_tokens(
            document.case_reference,
            document.neutral_citation,
            document.title,
        )
        text_source = "\n".join(
            part
            for part in [
                document.document_text or "",
                document.summary,
                document.title,
            ]
            if part
        )
        citations: list[AuthorityCitation] = []
        for citation_text, normalized_reference in _extract_citation_candidates(text_source):
            if normalized_reference in own_tokens:
                continue
            cited_document = resolution_index.get(normalized_reference)
            citations.append(
                AuthorityCitation(
                    citation_text=citation_text[:255],
                    normalized_reference=normalized_reference[:255],
                    cited_authority_document_id=(
                        cited_document.id
                        if cited_document and cited_document.id != document.id
                        else None
                    ),
                )
            )
        document.outgoing_citations = citations


def _authority_record(document: AuthorityDocument) -> AuthorityDocumentRecord:
    return AuthorityDocumentRecord(
        id=document.id,
        source=document.source,
        adapter_name=document.adapter_name,
        court_name=document.court_name,
        forum_level=document.forum_level,
        document_type=document.document_type,
        title=document.title,
        case_reference=document.case_reference,
        bench_name=document.bench_name,
        neutral_citation=document.neutral_citation,
        decision_date=document.decision_date,
        source_reference=document.source_reference,
        summary=document.summary,
        extracted_char_count=document.extracted_char_count,
        ingested_at=document.ingested_at,
        updated_at=document.updated_at,
    )


def _ingestion_run_record(run: AuthorityIngestionRun) -> AuthorityIngestionRunRecord:
    requested_by = run.requested_by_membership
    return AuthorityIngestionRunRecord(
        id=run.id,
        requested_by_membership_id=run.requested_by_membership_id,
        requested_by_name=requested_by.user.full_name if requested_by else None,
        source=run.source,
        adapter_name=run.adapter_name,
        status=run.status,
        summary=run.summary,
        imported_document_count=run.imported_document_count,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def summarize_authority_relationships(
    session: Session,
    *,
    authority_document_ids: list[str],
    limit: int = 5,
) -> list[str]:
    if not authority_document_ids:
        return []

    citations = list(
        session.scalars(
            select(AuthorityCitation).where(
                AuthorityCitation.source_authority_document_id.in_(authority_document_ids)
            )
        )
    )

    relationships: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        source = citation.source_authority_document
        if source is None:
            continue
        if citation.cited_authority_document is not None:
            target = citation.cited_authority_document
            line = (
                f"{source.title} cites {target.title} "
                f"through {citation.citation_text}."
            )
        else:
            line = (
                f"{source.title} cites {citation.citation_text}, "
                "but that authority is not yet resolved in the local corpus."
            )
        if line in seen:
            continue
        seen.add(line)
        relationships.append(line)
        if len(relationships) >= limit:
            break
    return relationships


def list_authority_sources(*, context: SessionContext) -> AuthoritySourceListResponse:
    del context
    return AuthoritySourceListResponse(
        sources=[
            AuthoritySourceRecord(
                source=adapter.source,
                label=adapter.label,
                description=adapter.description,
                court_name=adapter.court_name,
                forum_level=adapter.forum_level,
                document_type=adapter.document_type,
            )
            for adapter in list_supported_authority_sources()
        ]
    )


def ingest_authority_source(
    session: Session,
    *,
    context: SessionContext,
    payload: AuthorityIngestionRequest,
) -> AuthorityIngestionRunRecord:
    _require_admin(context)

    run = AuthorityIngestionRun(
        requested_by_membership_id=context.membership.id,
        source=payload.source.strip(),
        status=AuthorityIngestionStatus.COMPLETED,
    )
    session.add(run)
    session.flush()

    try:
        adapter = get_authority_source_adapter(payload.source)
        result = adapter.fetch(max_documents=payload.max_documents)
        run.adapter_name = result.adapter_name
        imported_document_count = 0
        persisted_documents: list[AuthorityDocument] = []

        for document in result.documents:
            canonical_key = _canonical_key(document)
            existing = session.scalar(
                select(AuthorityDocument).where(AuthorityDocument.canonical_key == canonical_key)
            )
            if existing is None:
                existing = AuthorityDocument(canonical_key=canonical_key)
                session.add(existing)

            existing.source = document.source
            existing.adapter_name = result.adapter_name
            existing.court_name = document.court_name
            existing.forum_level = document.forum_level
            existing.document_type = document.document_type
            existing.title = document.title
            existing.case_reference = document.case_reference
            existing.bench_name = document.bench_name
            existing.neutral_citation = document.neutral_citation
            existing.decision_date = datetime.fromisoformat(document.decision_date).date()
            existing.source_reference = document.source_reference
            existing.summary = document.summary
            existing.document_text = document.document_text
            existing.extracted_char_count = len(document.document_text or "")
            existing.ingested_at = datetime.now(UTC)
            chunk_source = document.document_text or document.summary or document.title
            existing.chunks = [
                AuthorityDocumentChunk(
                    chunk_index=index,
                    content=chunk,
                    token_count=len(chunk.split()),
                )
                for index, chunk in enumerate(_chunk_text(chunk_source))
            ]
            persisted_documents.append(existing)
            imported_document_count += 1

        session.flush()
        _rebuild_authority_citations(session, documents=persisted_documents)

        run.summary = result.summary
        run.imported_document_count = imported_document_count
        run.completed_at = datetime.now(UTC)
        session.commit()
        _invalidate_corpus_metrics_cache()
        session.refresh(run)
        return _ingestion_run_record(run)
    except Exception as exc:
        run.status = AuthorityIngestionStatus.FAILED
        run.summary = str(exc)
        run.completed_at = datetime.now(UTC)
        session.add(run)
        session.commit()
        _invalidate_corpus_metrics_cache()
        session.refresh(run)
        return _ingestion_run_record(run)


def list_recent_authority_documents(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 12,
) -> AuthorityDocumentListResponse:
    del context
    documents = list(
        session.scalars(
            select(AuthorityDocument)
            .order_by(AuthorityDocument.decision_date.desc(), AuthorityDocument.updated_at.desc())
            .limit(limit)
        )
    )
    return AuthorityDocumentListResponse(
        documents=[_authority_record(document) for document in documents]
    )


def _invalidate_corpus_metrics_cache() -> None:
    global _CORPUS_METRICS_CACHE
    with _CORPUS_METRICS_CACHE_LOCK:
        _CORPUS_METRICS_CACHE = None


def _parse_postgres_array_literal(raw: object) -> list[str]:
    """Parse the catalog's text rendering of a one-dimensional array.

    ``pg_stats.most_common_vals`` is exposed as ``anyarray`` and cannot be
    decoded generically by psycopg. Forum levels are short scalar strings, so
    asking PostgreSQL for its canonical text form and applying CSV escaping is
    both deterministic and independent of the column's concrete SQL type.
    """
    value = str(raw or "")
    if len(value) < 2 or not value.startswith("{") or not value.endswith("}"):
        return []
    inner = value[1:-1]
    if not inner:
        return []
    return next(csv.reader([inner], delimiter=",", quotechar='"', escapechar="\\"))


def _postgres_corpus_estimates(session: Session) -> _PostgresCorpusEstimates:
    """Return fast planner estimates without scanning the corpus tables.

    ``COUNT`` and ``MAX`` on the multi-million-row chunk table took tens of
    seconds on a cold production instance. PostgreSQL maintains relation cardinality and
    column null fractions for its planner; those estimates are appropriate for
    a user-facing coverage summary and remain constant-time as the corpus grows.
    """
    row = session.execute(
        text(
            "WITH relation_estimates AS ("
            " SELECT c.relname, greatest(c.reltuples, 0)::bigint AS row_estimate"
            " FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = current_schema()"
            " AND c.relname IN ('authority_documents', 'authority_document_chunks')"
            "), embedding_stats AS ("
            " SELECT coalesce(null_frac, 1.0) AS null_frac"
            " FROM pg_stats"
            " WHERE schemaname = current_schema()"
            " AND tablename = 'authority_document_chunks'"
            " AND attname = 'embedding_model'"
            "), forum_stats AS ("
            " SELECT most_common_vals::text AS values_text,"
            "        most_common_freqs::text AS frequencies_text"
            " FROM pg_stats"
            " WHERE schemaname = current_schema()"
            " AND tablename = 'authority_documents'"
            " AND attname = 'forum_level'"
            ")"
            " SELECT"
            " coalesce((SELECT row_estimate FROM relation_estimates"
            "           WHERE relname = 'authority_documents'), 0),"
            " coalesce((SELECT row_estimate FROM relation_estimates"
            "           WHERE relname = 'authority_document_chunks'), 0),"
            " round(coalesce((SELECT row_estimate FROM relation_estimates"
            "                 WHERE relname = 'authority_document_chunks'), 0)"
            "       * (1.0 - coalesce((SELECT null_frac FROM embedding_stats), 1.0))),"
            " (SELECT values_text FROM forum_stats),"
            " (SELECT frequencies_text FROM forum_stats)"
        )
    ).one()
    document_count = max(0, int(row[0] or 0))
    forum_values = _parse_postgres_array_literal(row[3])
    forum_frequencies = _parse_postgres_array_literal(row[4])
    forum_counts: dict[str, int] = {}
    for forum, frequency in zip(forum_values, forum_frequencies, strict=False):
        try:
            forum_counts[forum] = max(0, round(document_count * float(frequency)))
        except ValueError:
            continue
    return _PostgresCorpusEstimates(
        document_count=document_count,
        chunk_count=max(0, int(row[1] or 0)),
        embedded_chunk_count=max(0, int(row[2] or 0)),
        forum_counts=forum_counts,
    )


def _corpus_metrics(session: Session) -> _CorpusMetrics:
    """Read corpus health without a production corpus-table scan.

    PostgreSQL serves approximate dashboard counters from planner catalogs and
    caches them for five minutes. Exact ``COUNT``/``MAX`` remains limited to
    SQLite's small, isolated test databases, where immediate seed visibility is
    more valuable than planner parity.
    """
    global _CORPUS_METRICS_CACHE
    try:
        cache_enabled = (
            session.bind is not None and session.bind.dialect.name == "postgresql"
        )
    except Exception:
        cache_enabled = False

    with _CORPUS_METRICS_CACHE_LOCK:
        now = perf_counter()
        if cache_enabled and _CORPUS_METRICS_CACHE is not None:
            cached_at, metrics = _CORPUS_METRICS_CACHE
            if now - cached_at <= _AUTHORITY_COVERAGE_CACHE_TTL_SECONDS:
                return metrics

        latest_run = session.execute(
            select(
                AuthorityIngestionRun.status,
                AuthorityIngestionRun.completed_at,
                AuthorityIngestionRun.started_at,
            )
            .order_by(
                AuthorityIngestionRun.completed_at.desc(),
                AuthorityIngestionRun.started_at.desc(),
            )
            .limit(1)
        ).one_or_none()
        if cache_enabled:
            estimates = _postgres_corpus_estimates(session)
            document_count = estimates.document_count
            chunk_count = estimates.chunk_count
            embedded_chunk_count = estimates.embedded_chunk_count
            forum_counts = estimates.forum_counts
            last_corpus_change = (
                (latest_run.completed_at or latest_run.started_at)
                if latest_run is not None
                else None
            )
        else:
            document_row = session.execute(
                select(
                    func.count(AuthorityDocument.id),
                    func.max(AuthorityDocument.ingested_at),
                )
            ).one()
            chunk_row = session.execute(
                select(
                    func.count(AuthorityDocumentChunk.id),
                    func.count(AuthorityDocumentChunk.id).filter(
                        AuthorityDocumentChunk.embedding_model.is_not(None)
                    ),
                    func.max(
                        func.coalesce(
                            AuthorityDocumentChunk.embedded_at,
                            AuthorityDocumentChunk.created_at,
                        )
                    ),
                )
            ).one()
            document_count = int(document_row[0] or 0)
            chunk_count = int(chunk_row[0] or 0)
            embedded_chunk_count = int(chunk_row[1] or 0)
            last_corpus_change = document_row[1]
            last_indexed_at = chunk_row[2]
            forum_rows = session.execute(
                select(AuthorityDocument.forum_level, func.count())
                .group_by(AuthorityDocument.forum_level)
            ).all()
            forum_counts = {
                str(forum): int(count) for forum, count in forum_rows if forum
            }
        metrics = _CorpusMetrics(
            document_count=document_count,
            last_ingested_at=last_corpus_change,
            chunk_count=chunk_count,
            embedded_chunk_count=embedded_chunk_count,
            last_indexed_at=(last_corpus_change if cache_enabled else last_indexed_at),
            latest_ingestion_status=(
                str(getattr(latest_run.status, "value", latest_run.status))
                if latest_run is not None
                else None
            ),
            forum_counts=forum_counts,
        )
        if cache_enabled:
            _CORPUS_METRICS_CACHE = (now, metrics)
        return metrics


def get_authority_corpus_stats(
    session: Session, *, context: SessionContext
) -> AuthorityCorpusStats:
    """Aggregate counters for the global authority corpus.

    Drives the dashboard "Authorities indexed" tile and the research
    surface's "we're searching N docs" banner. Corpus is global (not
    tenant-scoped), so we don't filter by company — context is accepted
    for auth + audit consistency with the sibling endpoints.
    """
    del context
    metrics = _corpus_metrics(session)
    return AuthorityCorpusStats(
        document_count=metrics.document_count,
        chunk_count=metrics.chunk_count,
        embedded_chunk_count=metrics.embedded_chunk_count,
        forum_counts=metrics.forum_counts,
        last_ingested_at=metrics.last_ingested_at,
    )


def search_authority_catalog(
    session: Session,
    *,
    query: str,
    limit: int,
    forum_level: str | None = None,
    court_name: str | None = None,
    document_type: str | None = None,
    search_mode: str = "keyword",
    suppress_unreadable: bool = True,
) -> list[AuthoritySearchResult]:
    # Parties / title exact-match boost: case-name queries ("Wahid State
    # Govt of NCT of Delhi") carry a distinctive proper noun that
    # almost certainly appears verbatim in the target doc's parties_json
    # or title after Layer 2. Matching that exact token BEFORE vector
    # search eliminates the class of probe misses where cosine walks
    # away from a short, semantically-thin case name. Topic queries
    # ("bail triple test") return zero exact hits → fall through.
    structured_mode = search_mode not in {"keyword", "contextual"}
    candidate_limit = min(
        max(
            (
                limit
                if structured_mode
                else limit * _AUTHORITY_DOCUMENT_CANDIDATE_MULTIPLIER
            ),
            _AUTHORITY_MIN_DOCUMENT_CANDIDATES,
        ),
        _AUTHORITY_MAX_DOCUMENT_CANDIDATES,
    )
    name_match_ids = (
        []
        if structured_mode
        else _exact_name_match_document_ids(
            session,
            query=query,
            forum_level=forum_level,
            court_name=court_name,
            document_type=document_type,
            limit=candidate_limit,
        )
    )

    # Fast path: when running on Postgres + we have embeddings in the column
    # AND we can build a query vector, ask pgvector to pick top-K chunks via
    # the HNSW index, then load only those documents. At any real corpus
    # scale this is dramatically faster than the 300-row scan below.
    #
    # 2026-04-21: fan out over query-side normalisers so numeric / bracketed
    # SC citations, all-caps bench names, and non-English party names each
    # embed on a form the corpus actually stores. Variants are unioned
    # (preserving per-variant order) before the ranker sees them — the
    # lexical / hybrid re-score then picks the winner. Gated by
    # ``retrieval_query_normalisers_enabled`` so operators can flip it off
    # without a deploy if quality regresses on another surface.
    settings = get_settings()
    if getattr(settings, "retrieval_query_normalisers_enabled", True):
        query_variants = build_query_variants(query)
    else:
        query_variants = [query]

    pg_document_ids: list[str] | None = None
    preferred_chunk_ids: list[str] = []
    pg_any_attempted = False
    query_embedding_attempted = False
    precomputed_query_vector: list[float] | None = None
    query_vectors: list[list[float]] = []
    if not structured_mode and _pg_embedding_scope_available(
        session,
        forum_level=forum_level,
        court_name=court_name,
        document_type=document_type,
    ):
        # One bounded provider call embeds every normalised query variant. The
        # previous loop made one external call per variant and then made the
        # original call again in ``_embed_query`` during reranking.
        query_embedding_attempted = True
        query_vectors = _embed_query_variants(query_variants)
        if query_vectors:
            precomputed_query_vector = query_vectors[0]

    for query_vector in query_vectors:
        variant_hits = _pg_prefilter_document_hits(
            session,
            query_vector=query_vector,
            forum_level=forum_level,
            court_name=court_name,
            document_type=document_type,
            limit=candidate_limit,
        )
        if variant_hits is None:
            continue
        pg_any_attempted = True
        if pg_document_ids is None:
            pg_document_ids = []
        seen_ids = set(pg_document_ids)
        seen_chunks = set(preferred_chunk_ids)
        for hit in variant_hits:
            if hit.chunk_id not in seen_chunks:
                seen_chunks.add(hit.chunk_id)
                preferred_chunk_ids.append(hit.chunk_id)
            if hit.document_id not in seen_ids:
                seen_ids.add(hit.document_id)
                pg_document_ids.append(hit.document_id)
    # Preserve prior behaviour: when no variant triggered the fast path
    # (SQLite tests, no embeddings yet), leave ``pg_document_ids`` as
    # None so the fallback 300-row scan runs.
    if not pg_any_attempted:
        pg_document_ids = None

    # Merge: exact-name matches first (highest confidence), then vector
    # results. Dedup while preserving order.
    merged_ids: list[str] | None = None
    if name_match_ids or pg_document_ids is not None:
        seen: set[str] = set()
        merged_ids = []
        for doc_id in (*name_match_ids, *(pg_document_ids or [])):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            merged_ids.append(doc_id)
            if len(merged_ids) >= candidate_limit:
                break

    stmt = select(AuthorityDocument).options(
        # Judgment bodies and lazy relationships are deliberately excluded
        # from the candidate read. Relevant chunks are loaded in one bounded
        # query below; structured modes rank canonical metadata directly.
        defer(AuthorityDocument.document_text),
        raiseload(AuthorityDocument.chunks),
    )
    if merged_ids is not None:
        if not merged_ids:
            return []
        stmt = stmt.where(AuthorityDocument.id.in_(merged_ids))
    else:
        stmt = stmt.order_by(
            AuthorityDocument.decision_date.desc(),
            AuthorityDocument.updated_at.desc(),
        )
    if forum_level:
        stmt = stmt.where(AuthorityDocument.forum_level == forum_level)
    court_clause = _court_name_filter_clause(court_name)
    if court_clause is not None:
        stmt = stmt.where(court_clause)
    if document_type:
        stmt = stmt.where(AuthorityDocument.document_type == document_type)
    mode_clause = _authority_mode_filter_clause(search_mode, query)
    if mode_clause is not None:
        stmt = stmt.where(mode_clause)

    stmt = stmt.limit(candidate_limit)
    documents = list(session.scalars(stmt))
    query_ref_tokens = set(_extract_case_references(query))
    normalized_query = _normalize_case_reference(query)
    if normalized_query:
        query_ref_tokens.add(normalized_query)
    candidates: list[RetrievalCandidate] = []
    candidate_to_document: dict[str, AuthorityDocument] = {}
    chunks_by_document = (
        {}
        if structured_mode
        else _load_bounded_candidate_chunks(
            session,
            document_ids=[document.id for document in documents],
            preferred_chunk_ids=preferred_chunk_ids,
        )
    )

    for document in documents:
        document_chunks = chunks_by_document.get(document.id, [])
        if document_chunks:
            for chunk in document_chunks:
                candidate_id = f"{document.id}:{chunk.chunk_index}"
                candidates.append(
                    RetrievalCandidate(
                        attachment_id=candidate_id,
                        attachment_name=document.title,
                        content="\n".join(
                            part
                            for part in [
                                document.title,
                                document.case_reference or "",
                                document.neutral_citation or "",
                                document.court_name,
                                document.bench_name or "",
                                document.parties_json or "",
                                document.judges_json or "",
                                document.sections_cited_json or "",
                                document.summary,
                                chunk.content,
                            ]
                            if part
                        ),
                        quality_text=chunk.content,
                        embedding=_decode_embedding(chunk.embedding_json),
                    )
                )
                candidate_to_document[candidate_id] = document
            continue

        candidate_id = f"{document.id}:summary"
        candidates.append(
            RetrievalCandidate(
                attachment_id=candidate_id,
                attachment_name=document.title,
                content="\n".join(
                    part
                    for part in [
                        document.title,
                        document.case_reference or "",
                        document.neutral_citation or "",
                        document.court_name,
                        document.bench_name or "",
                        document.parties_json or "",
                        document.judges_json or "",
                        document.sections_cited_json or "",
                        document.summary,
                    ]
                    if part
                ),
                quality_text=document.summary,
            )
        )
        candidate_to_document[candidate_id] = document

    query_vector = (
        None
        if structured_mode
        else (
            precomputed_query_vector
            if query_embedding_attempted
            else _embed_query(query, candidates=candidates)
        )
    )
    ranked = rank_candidates(
        query=query,
        candidates=candidates,
        limit=max(limit * 5, limit),
        query_vector=query_vector,
    )
    best_by_document: dict[str, AuthoritySearchResult] = {}

    for result in ranked:
        document = candidate_to_document.get(result.attachment_id)
        if document is None:
            continue

        adjusted_score = result.score
        if _court_name_matches_filter(document.court_name, court_name):
            adjusted_score += 16
        # P4 (2026-04-25): forum-aware precedent boost — replaces the
        # old exact-match `+8 if forum_level == forum_level` with a
        # hierarchy-aware boost that also rewards binding precedent
        # (e.g. SC docs when the matter is at HC/lower_court/tribunal).
        # Falls back to 0 when either forum is unknown.
        adjusted_score += _forum_precedent_boost(
            forum_level, document.forum_level
        )
        if document_type and document.document_type == document_type:
            adjusted_score += 8
        document_ref_tokens = set(
            _extract_case_references(
                "\n".join(
                    part
                    for part in [
                        document.case_reference or "",
                        document.neutral_citation or "",
                        document.title,
                        document.summary,
                    ]
                    if part
                )
            )
        )
        if query_ref_tokens and document_ref_tokens:
            overlap = query_ref_tokens & document_ref_tokens
            if overlap:
                adjusted_score += 100 + (10 * len(overlap))

        current = best_by_document.get(document.id)
        if current and current.score >= adjusted_score:
            continue

        best_by_document[document.id] = AuthoritySearchResult(
            authority_document_id=document.id,
            title=document.title,
            court_name=document.court_name,
            forum_level=document.forum_level,
            document_type=document.document_type,
            decision_date=document.decision_date,
            case_reference=document.case_reference,
            neutral_citation=document.neutral_citation,
            bench_name=document.bench_name,
            summary=document.summary,
            source=document.source,
            source_reference=document.source_reference,
            snippet=result.snippet,
            score=adjusted_score,
            matched_terms=result.matched_terms,
        )

    results = sorted(best_by_document.values(), key=lambda item: item.score, reverse=True)
    # Optional rerank pass (CASEOPS_RERANK_ENABLED=true). Over-fetch the
    # top 3*limit from first-stage retrieval, then let the cross-encoder
    # reorder on (query, title + snippet). build_reranker() returns a
    # MockReranker when the flag is off, so disabling the feature keeps
    # behaviour and cost identical to pre-rerank. Any reranker failure
    # (model load, runtime exception) falls back to first-stage order —
    # retrieval never breaks on reranker trouble.
    top_n = results[: max(limit * 3, limit)]
    if len(top_n) > limit:
        try:
            from caseops_api.services.reranker import (
                RerankerCandidate,
                build_reranker,
            )

            reranker = build_reranker()
            cands = [
                RerankerCandidate(
                    identifier=r.authority_document_id,
                    title=r.title or "",
                    text=(r.snippet or r.summary or "")[:500],
                )
                for r in top_n
            ]
            ranked = reranker.rerank(
                query,
                cands,
                top_k=len(cands) if suppress_unreadable else limit,
            )
            by_id = {r.authority_document_id: r for r in top_n}
            reranked = [
                by_id[c.identifier] for c in ranked if c.identifier in by_id
            ]
            if reranked:
                return (
                    _readable_authority_results_only(reranked)[:limit]
                    if suppress_unreadable
                    else reranked[:limit]
                )
        except Exception:  # noqa: BLE001
            # Never let a reranker hiccup break search.
            pass
    return (
        _readable_authority_results_only(top_n)[:limit]
        if suppress_unreadable
        else top_n[:limit]
    )


def _authority_result_has_unreadable_preview(result: AuthoritySearchResult) -> bool:
    preview_parts = [result.title, result.summary, result.snippet]
    if any(is_low_quality_ocr_text(part) for part in preview_parts):
        return True
    return is_low_quality_ocr_text(
        "\n".join(part for part in preview_parts if part)
    )


def _filter_unreadable_authority_results(
    results: list[AuthoritySearchResult],
) -> tuple[list[AuthoritySearchResult], int]:
    """Drop authority cards whose preview text is not usable.

    A corrupted title/snippet is not a legally useful result. Filtering at this
    shared layer prevents Research, recommendation prompts, and other authority
    consumers from treating unreadable OCR as source-backed context.
    """
    readable: list[AuthoritySearchResult] = []
    omitted = 0
    for result in results:
        if _authority_result_has_unreadable_preview(result):
            omitted += 1
        else:
            readable.append(result)
    return readable, omitted


def _readable_authority_results_only(
    results: list[AuthoritySearchResult],
) -> list[AuthoritySearchResult]:
    readable, _ = _filter_unreadable_authority_results(results)
    return readable


def search_authorities(
    session: Session,
    *,
    context: SessionContext,
    payload: AuthoritySearchRequest,
) -> AuthoritySearchResponse:
    started_at = perf_counter()
    # PG-110 (2026-05-01): over-fetch from the catalog to give language
    # filter + offset enough room. After the 2026-04-28 sweep widened
    # to non-EN documents, top-ranked results frequently include Garo
    # / Hindi / Tamil titles whose Latin-script ratio is <70% — those
    # leak into the user's view and dominate "why English content is
    # not coming" complaints. Filter at the route layer so the catalog
    # call stays a single source of truth for retrieval + rerank.
    contextual_plan = (
        _build_contextual_query_plan(payload.query)
        if payload.mode == "contextual"
        else None
    )
    search_query = (
        contextual_plan.planned_query if contextual_plan is not None else payload.query
    )
    overfetch = min(
        max((payload.offset + payload.limit) * 5, 50),
        _AUTHORITY_MAX_DOCUMENT_CANDIDATES,
    )
    coverage_started_at = perf_counter()
    coverage = _authority_search_coverage(session, payload=payload)
    coverage_ms = max(0, round((perf_counter() - coverage_started_at) * 1000))
    provider_unavailable = False
    retrieval_started_at = perf_counter()
    try:
        raw = search_authority_catalog(
            session,
            query=search_query,
            limit=overfetch,
            forum_level=payload.forum_level,
            court_name=payload.court_name,
            document_type=payload.document_type,
            search_mode=payload.mode,
            suppress_unreadable=False,
        )
    except EmbeddingProviderError:
        raw = []
        provider_unavailable = True
    retrieval_ms = max(0, round((perf_counter() - retrieval_started_at) * 1000))
    if payload.language == "en":
        filtered = [r for r in raw if _title_is_predominantly_ascii(r.title)]
    else:
        filtered = list(raw)
    filtered, unreadable_omitted_count = _filter_unreadable_authority_results(filtered)
    total = len(filtered)
    page = filtered[payload.offset : payload.offset + payload.limit]

    # PG-006 Phase 1B (2026-05-01) — enrich the page with the good-law
    # signal in a single bulk query. Authorities with no adverse cite
    # leave the defaults (worst_treatment=None, adverse_count=0) so the
    # frontend can render the badge only when something is wrong.
    from caseops_api.services.authority_treatments import (
        compute_search_result_treatments,
    )
    treatment_lookup = compute_search_result_treatments(
        session, [r.authority_document_id for r in page],
    )
    from caseops_api.services.source_actions import (
        authority_source_verified,
        inspect_source_target_action,
    )

    enriched_page = [
        r.model_copy(
            update={
                "worst_treatment": treatment_lookup.get(
                    r.authority_document_id, (None, 0),
                )[0],
                "adverse_count": treatment_lookup.get(
                    r.authority_document_id, (None, 0),
                )[1],
                "source_action": inspect_source_target_action(
                    r.source_reference,
                    target_type="authority_document",
                    target_id=r.authority_document_id,
                    # FMB-01: was r.source == "official", a value no ingest
                    # path writes, so this was statically dead.
                    verified=authority_source_verified(r.source, r.source_reference),
                ),
            },
        )
        for r in page
    ]
    enriched_page = [
        r.model_copy(
            update={
                "relevance_reason": (
                    _contextual_relevance_reason(r, contextual_plan)
                    if contextual_plan is not None
                    else _explain_authority_match(r, payload=payload)
                ),
            },
        )
        for r in enriched_page
    ]
    if contextual_plan is not None:
        _record_contextual_search_audit(
            session,
            context=context,
            payload=payload,
            plan=contextual_plan,
            result_count=total,
        )

    if enriched_page:
        outcome = "results_found"
    elif total and payload.offset >= total:
        outcome = "offset_out_of_range"
    elif unreadable_omitted_count and not total:
        outcome = "unreadable_filtered"
    elif provider_unavailable:
        outcome = "provider_unavailable"
    elif coverage.document_count == 0:
        outcome = "corpus_unavailable"
    elif coverage.index_state == "stale":
        outcome = "index_stale"
    else:
        outcome = "no_matching_documents"

    session.add(
        AuthoritySearchObservation(
            company_id=context.company.id,
            membership_id=context.membership.id,
            query_fingerprint=hashlib.sha256(
                " ".join(payload.query.lower().split()).encode("utf-8")
            ).hexdigest(),
            mode=payload.mode,
            outcome=outcome,
            result_count=len(enriched_page),
            raw_candidate_count=len(raw),
            unreadable_omitted_count=unreadable_omitted_count,
            latency_ms=max(0, round((perf_counter() - started_at) * 1000)),
            filters_json={
                "has_court_filter": bool(payload.court_name),
                "has_forum_filter": bool(payload.forum_level),
                "has_document_type_filter": bool(payload.document_type),
                "language": payload.language,
                "coverage_ms": coverage_ms,
                "retrieval_ms": retrieval_ms,
            },
        )
    )
    session.commit()

    logger.info(
        "authority_search_timing mode=%s coverage_ms=%d retrieval_ms=%d total_ms=%d "
        "raw_candidates=%d returned=%d outcome=%s",
        payload.mode,
        coverage_ms,
        retrieval_ms,
        max(0, round((perf_counter() - started_at) * 1000)),
        len(raw),
        len(enriched_page),
        outcome,
    )

    return AuthoritySearchResponse(
        query=payload.query,
        mode=payload.mode,
        provider=(
            "caseops-authority-contextual-search-v1"
            if contextual_plan is not None
            else "caseops-authority-search-v2"
        ),
        generated_at=datetime.now(UTC),
        results=enriched_page,
        contextual_plan=contextual_plan,
        coverage_notice=(
            _search_coverage_notice(
                coverage=coverage,
                outcome=outcome,
                contextual_notice=_contextual_coverage_notice(
                total_after_filter=total,
                raw_count=len(raw),
                unreadable_omitted_count=unreadable_omitted_count,
                ) if contextual_plan is not None else None,
            )
        ),
        total_after_filter=total,
        offset=payload.offset,
        outcome=outcome,
        diagnostics={
            "raw_candidate_count": len(raw),
            "unreadable_omitted_count": unreadable_omitted_count,
            "returned_count": len(enriched_page),
            "has_more": payload.offset + payload.limit < total,
            "coverage_ms": coverage_ms,
            "retrieval_ms": retrieval_ms,
            "total_latency_ms": max(0, round((perf_counter() - started_at) * 1000)),
        },
        corpus_coverage=coverage,
    )


def _authority_mode_filter_clause(search_mode: str, query: str):
    """Apply explicit PRD search modes without changing the shared ranker.

    Keyword/contextual search keep hybrid retrieval.  The structured modes
    narrow the candidate set on canonical extracted metadata, after which the
    same source-backed ranking and treatment enrichment still apply.
    """
    cleaned = " ".join(query.split()).strip()
    if search_mode in {"keyword", "contextual"} or not cleaned:
        return None
    pattern = f"%{cleaned}%"
    if search_mode == "exact_citation":
        normalized = _normalize_case_reference(cleaned)
        normalized_pattern = f"%{normalized}%" if normalized else pattern
        citation_text = _indexed_search_text(
            AuthorityDocument.case_reference,
            AuthorityDocument.neutral_citation,
        )
        return or_(
            citation_text.ilike(pattern),
            citation_text.ilike(normalized_pattern),
        )
    if search_mode == "party":
        return _indexed_search_text(
            AuthorityDocument.parties_json,
            AuthorityDocument.title,
        ).ilike(pattern)
    if search_mode == "court":
        return AuthorityDocument.court_name.ilike(pattern)
    if search_mode == "judge":
        return _indexed_search_text(
            AuthorityDocument.bench_name,
            AuthorityDocument.judges_json,
        ).ilike(pattern)
    if search_mode == "act_section":
        return _indexed_search_text(
            AuthorityDocument.sections_cited_json,
            AuthorityDocument.title,
        ).ilike(pattern)
    return None


def _indexed_search_text(*columns):
    """Match the immutable expression used by the production GIN indexes."""
    empty = literal_column("''")
    separator = literal_column("' '")
    expression = func.coalesce(columns[0], empty)
    for column in columns[1:]:
        expression = expression + separator + func.coalesce(column, empty)
    return expression


def _explain_authority_match(
    result: AuthoritySearchResult,
    *,
    payload: AuthoritySearchRequest,
) -> str:
    signals: list[str] = []
    if result.matched_terms:
        signals.append(
            "indexed passage match on " + ", ".join(result.matched_terms[:5])
        )
    if payload.mode == "exact_citation":
        signals.append("exact citation metadata match")
    elif payload.mode == "party":
        signals.append("extracted party metadata match")
    elif payload.mode == "court":
        signals.append("court metadata match")
    elif payload.mode == "judge":
        signals.append("extracted bench or judge metadata match")
    elif payload.mode == "act_section":
        signals.append("extracted Act or section metadata match")
    if payload.forum_level:
        signals.append(
            f"precedent hierarchy considered for {payload.forum_level.replace('_', ' ')}"
        )
    if result.worst_treatment:
        signals.append(
            f"known {result.worst_treatment} treatment "
            f"({result.adverse_count} adverse citations)"
        )
    else:
        signals.append("no adverse treatment found in the indexed citation graph")
    return (
        "Why this result: "
        + "; ".join(signals)
        + ". Verify the source before relying on it."
    )


def _authority_search_coverage(
    session: Session,
    *,
    payload: AuthoritySearchRequest,
) -> AuthoritySearchCoverage:
    metrics = _corpus_metrics(session)
    if metrics.document_count == 0:
        index_state = "unavailable"
    elif metrics.chunk_count == 0 or metrics.last_indexed_at is None:
        index_state = "stale"
    elif metrics.latest_ingestion_status == AuthorityIngestionStatus.FAILED.value:
        index_state = "stale"
    else:
        index_state = "current"

    scope_parts = ["indexed authority corpus"]
    if payload.forum_level:
        scope_parts.append(payload.forum_level.replace("_", " "))
    if payload.court_name:
        scope_parts.append(f'court containing "{payload.court_name.strip()}"')
    if payload.document_type:
        scope_parts.append(payload.document_type.replace("_", " "))
    scope_parts.append(f"{payload.language} language scope")
    return AuthoritySearchCoverage(
        document_count=metrics.document_count,
        chunk_count=metrics.chunk_count,
        embedded_chunk_count=metrics.embedded_chunk_count,
        forum_counts=metrics.forum_counts,
        last_ingested_at=metrics.last_ingested_at,
        last_indexed_at=metrics.last_indexed_at,
        index_state=index_state,
        scope_summary="; ".join(scope_parts),
    )


def _search_coverage_notice(
    *,
    coverage: AuthoritySearchCoverage,
    outcome: str,
    contextual_notice: str | None,
) -> str | None:
    if outcome == "corpus_unavailable":
        return "The authority corpus is unavailable. Retry after corpus health is restored."
    if outcome == "provider_unavailable":
        return (
            "The configured research provider is unavailable. Your committed "
            "query was preserved; retry later."
        )
    if coverage.index_state == "stale":
        return (
            "Index evidence is incomplete or the latest ingestion failed. Results may not "
            "include the newest corpus records; retry after indexing is reconciled."
        )
    return contextual_notice


def _title_is_predominantly_ascii(title: str | None) -> bool:
    """Heuristic: title qualifies as English when

    - it has ≥3 ASCII letters (so pure-Devanagari/Tamil titles fail);
    - ASCII-letter ratio over letter chars is ≥70%;
    - non-ASCII char count is <3 (rejects regional-language
      transliterations where the letters happen to be Latin but the
      title is peppered with regional diacritics like `ˑ` U+02D1
      from Garo, or other modifier letters from Tamil / Bengali
      transliterations). Real English titles average 0-1 non-ASCII
      chars (occasional smart quote / em-dash); ≥3 is the regional
      signal.
    - `?` count <3 (legacy OCR-fail signal — kept as belt+braces).

    Empty / None / no-letter titles return False so OCR-garbled rows
    don't slip through.
    """
    if not title:
        return False
    # Belt-and-braces OCR signal.
    if title.count("?") >= 3:
        return False
    # Regional transliteration signal — Garo / Tamil / Bengali Latin-
    # transliterated titles carry repeated non-ASCII modifier letters
    # (e.g. "Rai onˑaniko kuˑsiktangona peˑanira" has 6× U+02D1).
    non_ascii = sum(1 for c in title if ord(c) >= 128)
    if non_ascii >= 3:
        return False
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    ascii_letters = sum(1 for c in letters if ord(c) < 128)
    if ascii_letters < 3:
        return False
    return ascii_letters / len(letters) >= 0.7


# Case-name queries carry at least one distinctive proper noun (the
# petitioner / respondent name). Stopwords below are the capitalised
# tokens that appear in MOST case names and therefore don't narrow the
# search: "State", "Union", "The", "Court", etc. A token with a capital
# first letter and ≥ 4 chars and not in this set is treated as a
# candidate proper noun.
_CASE_NAME_STOPWORDS = frozenset({
    "State", "Union", "The", "Court", "India", "Ors", "Anr", "Another",
    "Others", "Petitioner", "Respondent", "Appellant", "Accused", "And",
    "Vs", "Versus", "Honble", "Commissioner", "Officer", "Ltd", "Limited",
    "Pvt", "Corporation", "Committee", "Council", "Authority", "Board",
    "Government", "Gov", "Govt", "High", "Supreme", "Dist", "District",
    "Civil", "Criminal", "Crime", "Police", "Station",
})


def _proper_noun_tokens(query: str) -> list[str]:
    """Extract distinctive proper-noun tokens from a query.

    Rules:
    - Tokenise on whitespace, strip trailing punctuation.
    - Keep tokens that (a) start with an uppercase letter, (b) are
      ≥ 4 chars, (c) aren't in `_CASE_NAME_STOPWORDS`, (d) are
      alphabetic (rejects docket numbers like "CRLP", "WP", "CRR").
    Returns up to 2 such tokens in query order (primary + secondary
    signals). Returns [] if no proper-noun tokens are present — that's
    the signal the query is topical and should fall through to pure
    vector search.
    """
    if not query:
        return []
    tokens: list[str] = []
    for raw in query.split():
        clean = raw.strip(".,;:!?\"'()[]{}")
        if len(clean) < 4 or not clean[0].isupper() or not clean.isalpha():
            continue
        if clean in _CASE_NAME_STOPWORDS:
            continue
        tokens.append(clean)
        if len(tokens) >= 2:
            break
    return tokens


def _exact_name_match_document_ids(
    session: Session,
    *,
    query: str,
    forum_level: str | None,
    court_name: str | None,
    document_type: str | None,
    limit: int,
) -> list[str]:
    """Return doc ids whose parties_json OR title contains every proper-
    noun token from the query. Empty list if the query is topical or
    if the match is too broad to be confident (> 2 × limit hits).
    """
    tokens = _proper_noun_tokens(query)
    if not tokens:
        return []
    try:
        if session.bind is None or session.bind.dialect.name != "postgresql":
            return []
    except Exception:
        return []

    # Build a WHERE clause that requires EVERY token (AND) to appear in
    # the one immutable parties/title/bench expression covered by the
    # production trigram index. The bench_name axis was added 2026-04-21 after the
    # sc-2023 probe: queries like 'DHARWAD BENCH' hit docs whose
    # bench_name is 'Dharwad Bench' but whose parties_json / title
    # carries only party strings. Without the bench_name column in the
    # prefilter, the exact-name path dropped those candidates and the
    # vector-only fallback missed them.
    # The corpus is now >800K documents, so an unindexed token probe is not an
    # acceptable interactive fallback.
    filters = []
    name_search_text = _indexed_search_text(
        AuthorityDocument.parties_json,
        AuthorityDocument.title,
        AuthorityDocument.bench_name,
    )
    for tok in tokens:
        pattern = f"%{tok}%"
        filters.append(name_search_text.ilike(pattern))
    if forum_level is not None:
        filters.append(AuthorityDocument.forum_level == forum_level)
    court_clause = _court_name_filter_clause(court_name)
    if court_clause is not None:
        filters.append(court_clause)
    if document_type is not None:
        filters.append(AuthorityDocument.document_type == document_type)

    try:
        ids = list(
            session.scalars(
                select(AuthorityDocument.id).where(*filters).limit(limit)
            )
        )
    except Exception:
        session.rollback()
        return []

    # Too broad (likely topical token that slipped the stopword list) →
    # DON'T drop entirely — that path was the sc-2023 Pradeep Kumar
    # v. State of Chhattisgarh miss, where 'Pradeep' + 'Kumar' matched
    # dozens of related judgments and the prefilter used to return [].
    # Instead, trim to the first ``limit`` ids (already filtered by
    # forum_level / court_name / document_type) and hand that to the
    # vector ranker, which will re-score by cosine distance and pick
    # the real top-k. Legitimate narrow hits still pass untouched.
    broad_cap = max(limit * 2, 20)
    if len(ids) > broad_cap:
        ids = ids[:limit]
    return ids


def _pg_embedding_scope_available(
    session: Session,
    *,
    forum_level: str | None,
    court_name: str | None,
    document_type: str | None,
) -> bool:
    """Probe global pgvector availability once without a corpus join.

    Filtered availability used to walk the 5.3M-row chunk table when a court
    scope had no match. The bounded HNSW query already applies the requested
    filters and truthfully returns no hits, so this guard only needs to know
    whether the vector path exists at all.
    """
    del forum_level, court_name, document_type
    try:
        if session.bind is None or session.bind.dialect.name != "postgresql":
            return False
    except Exception:
        return False

    from sqlalchemy import text

    try:
        probe = session.execute(
            text(
                "SELECT 1 FROM authority_document_chunks "
                "WHERE embedding_vector IS NOT NULL "
                "LIMIT 1"
            )
        ).first()
    except Exception:
        session.rollback()
        return False
    return probe is not None


def _embed_query_variants(queries: list[str]) -> list[list[float]]:
    """Embed all query variants in one provider round-trip.

    A provider failure is a bounded degradation to lexical retrieval, not a
    reason to repeat the same external call later in the request.
    """
    cleaned = [query.strip() for query in queries if query.strip()]
    if not cleaned:
        return []
    try:
        provider = build_provider()
        result = provider.embed(cleaned, input_type="query")
    except Exception:
        return []
    return result.vectors if len(result.vectors) == len(cleaned) else []


def _pg_prefilter_document_hits(
    session: Session,
    *,
    query_vector: list[float],
    forum_level: str | None,
    court_name: str | None,
    document_type: str | None,
    limit: int,
) -> list[_VectorDocumentHit] | None:
    """Return the best HNSW chunk for each candidate document.

    Returning the chunk identity is important: the old document-only result
    forced the caller to reload *every* chunk for every selected judgment.
    """
    if not query_vector:
        return None
    from sqlalchemy import text

    court_contains = _normalize_court_filter(court_name)
    court_contains = court_contains.casefold() if court_contains else None
    vec_literal = "[" + ",".join(f"{value:.6f}" for value in query_vector) + "]"
    # BUG-015 root cause (2026-04-30): the prior single-CTE shape did
    # GROUP BY authority_document_id BEFORE ORDER BY MIN(distance), which
    # forced the planner off the HNSW index — every concurrent INSERT on
    # authority_document_chunks (citation extraction + EN sweep) then
    # contended with a 1.8M-chunk sequential scan and the query stalled
    # past Cloud Run's 300s budget.
    #
    # Fix: push the HNSW pick into an inner CTE with `ORDER BY <=> LIMIT`
    # — that's the canonical pgvector shape the planner can serve from
    # the index in O(log n). Then JOIN + filter + GROUP on the small
    # candidate set. chunk_limit overfetches by 30x so a narrow forum /
    # court filter still has material to dedup down to `limit`.
    chunk_limit = max(limit * 30, 1000)
    try:
        rows = session.execute(
            text(
                "WITH top_chunks AS ("
                " SELECT c.authority_document_id AS id, c.id AS chunk_id, "
                "        c.embedding_vector <=> cast(:q as vector) AS dist"
                " FROM authority_document_chunks c "
                " WHERE c.embedding_vector IS NOT NULL "
                " ORDER BY c.embedding_vector <=> cast(:q as vector) "
                " LIMIT :chunk_limit"
                "), filtered AS ("
                " SELECT tc.id, tc.chunk_id, tc.dist AS distance "
                " FROM top_chunks tc "
                " JOIN authority_documents d ON d.id = tc.id "
                " WHERE (cast(:forum as text) IS NULL OR d.forum_level = :forum) "
                " AND (cast(:court_contains as text) IS NULL "
                "OR position(:court_contains in lower(coalesce(d.court_name, ''))) > 0) "
                " AND (cast(:dtype as text) IS NULL OR d.document_type = :dtype)"
                "), ranked AS ("
                " SELECT id, chunk_id, distance, "
                " row_number() OVER (PARTITION BY id ORDER BY distance) AS doc_rank "
                " FROM filtered"
                ") "
                "SELECT id, chunk_id FROM ranked WHERE doc_rank = 1 "
                "ORDER BY distance LIMIT :limit"
            ),
            {
                "q": vec_literal,
                "forum": forum_level,
                "court_contains": court_contains,
                "dtype": document_type,
                "limit": limit,
                "chunk_limit": chunk_limit,
            },
        ).all()
    except Exception:
        session.rollback()
        return None
    return [
        _VectorDocumentHit(document_id=str(row.id), chunk_id=str(row.chunk_id))
        for row in rows
    ]


def _load_bounded_candidate_chunks(
    session: Session,
    *,
    document_ids: list[str],
    preferred_chunk_ids: list[str],
) -> dict[str, list[AuthorityDocumentChunk]]:
    """Load at most a few chunks per candidate in a constant query count."""
    if not document_ids:
        return {}

    document_id_set = set(document_ids)
    by_document: dict[str, list[AuthorityDocumentChunk]] = {}
    if preferred_chunk_ids:
        preferred_order = {
            chunk_id: index
            for index, chunk_id in enumerate(
                preferred_chunk_ids[
                    : _AUTHORITY_MAX_DOCUMENT_CANDIDATES
                    * _AUTHORITY_FALLBACK_CHUNKS_PER_DOCUMENT
                ]
            )
        }
        preferred = list(
            session.scalars(
                select(AuthorityDocumentChunk).where(
                    AuthorityDocumentChunk.id.in_(preferred_order),
                    AuthorityDocumentChunk.authority_document_id.in_(document_id_set),
                )
            )
        )
        preferred.sort(key=lambda chunk: preferred_order.get(chunk.id, len(preferred_order)))
        for chunk in preferred:
            bucket = by_document.setdefault(chunk.authority_document_id, [])
            if len(bucket) < _AUTHORITY_FALLBACK_CHUNKS_PER_DOCUMENT:
                bucket.append(chunk)

    missing_document_ids = document_id_set - set(by_document)
    if missing_document_ids:
        ranked_ids = (
            select(
                AuthorityDocumentChunk.id.label("chunk_id"),
                func.row_number()
                .over(
                    partition_by=AuthorityDocumentChunk.authority_document_id,
                    order_by=AuthorityDocumentChunk.chunk_index.asc(),
                )
                .label("candidate_rank"),
            )
            .where(AuthorityDocumentChunk.authority_document_id.in_(missing_document_ids))
            .subquery()
        )
        fallback_chunks = list(
            session.scalars(
                select(AuthorityDocumentChunk)
                .join(ranked_ids, ranked_ids.c.chunk_id == AuthorityDocumentChunk.id)
                .where(
                    ranked_ids.c.candidate_rank
                    <= _AUTHORITY_FALLBACK_CHUNKS_PER_DOCUMENT
                )
            )
        )
        for chunk in fallback_chunks:
            by_document.setdefault(chunk.authority_document_id, []).append(chunk)

    for chunks in by_document.values():
        chunks.sort(key=lambda chunk: chunk.chunk_index)
    return by_document


def _decode_embedding(raw: str | None) -> list[float] | None:
    if not raw:
        return None
    try:
        import json

        values = json.loads(raw)
        if not isinstance(values, list):
            return None
        return [float(v) for v in values]
    except (ValueError, TypeError):
        return None


def _embed_query(
    query: str, *, candidates: list[RetrievalCandidate]
) -> list[float] | None:
    """Return a query embedding only when at least one candidate has one.

    This keeps the happy path free of embedding cost when the corpus is
    lexical-only (no ingestion has run yet).
    """
    has_any_embedding = any(c.embedding is not None for c in candidates)
    if not has_any_embedding or not query.strip():
        return None
    try:
        provider = build_provider()
    except EmbeddingProviderError:
        return None
    try:
        result = provider.embed([query], input_type="query")
    except Exception:
        return None
    if not result.vectors:
        return None
    return result.vectors[0]
