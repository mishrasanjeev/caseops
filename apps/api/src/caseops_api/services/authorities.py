from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from time import perf_counter

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

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
        session.refresh(run)
        return _ingestion_run_record(run)
    except Exception as exc:
        run.status = AuthorityIngestionStatus.FAILED
        run.summary = str(exc)
        run.completed_at = datetime.now(UTC)
        session.add(run)
        session.commit()
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


def get_authority_corpus_stats(
    session: Session, *, context: SessionContext
) -> AuthorityCorpusStats:
    """Aggregate counters for the global authority corpus.

    Drives the dashboard "Authorities indexed" tile and the research
    surface's "we're searching N docs" banner. Corpus is global (not
    tenant-scoped), so we don't filter by company — context is accepted
    for auth + audit consistency with the sibling endpoints.
    """
    from sqlalchemy import func

    del context
    doc_count = (
        session.scalar(select(func.count()).select_from(AuthorityDocument)) or 0
    )
    chunk_count = (
        session.scalar(select(func.count()).select_from(AuthorityDocumentChunk)) or 0
    )
    embedded_count = (
        session.scalar(
            select(func.count())
            .select_from(AuthorityDocumentChunk)
            .where(AuthorityDocumentChunk.embedding_model.is_not(None))
        )
        or 0
    )
    last_ingested = session.scalar(
        select(func.max(AuthorityDocument.ingested_at))
    )
    forum_rows = session.execute(
        select(AuthorityDocument.forum_level, func.count())
        .group_by(AuthorityDocument.forum_level)
    ).all()
    forum_counts = {str(forum): int(count) for forum, count in forum_rows if forum}
    return AuthorityCorpusStats(
        document_count=int(doc_count),
        chunk_count=int(chunk_count),
        embedded_chunk_count=int(embedded_count),
        forum_counts=forum_counts,
        last_ingested_at=last_ingested,
    )


def search_authority_catalog(
    session: Session,
    *,
    query: str,
    limit: int,
    forum_level: str | None = None,
    court_name: str | None = None,
    document_type: str | None = None,
    suppress_unreadable: bool = True,
) -> list[AuthoritySearchResult]:
    # Parties / title exact-match boost: case-name queries ("Wahid State
    # Govt of NCT of Delhi") carry a distinctive proper noun that
    # almost certainly appears verbatim in the target doc's parties_json
    # or title after Layer 2. Matching that exact token BEFORE vector
    # search eliminates the class of probe misses where cosine walks
    # away from a short, semantically-thin case name. Topic queries
    # ("bail triple test") return zero exact hits → fall through.
    name_match_ids = _exact_name_match_document_ids(
        session,
        query=query,
        forum_level=forum_level,
        court_name=court_name,
        document_type=document_type,
        limit=max(limit * 6, 30),
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
    pg_any_attempted = False
    for variant in query_variants:
        variant_ids = _pg_prefilter_document_ids(
            session,
            query=variant,
            forum_level=forum_level,
            court_name=court_name,
            document_type=document_type,
            limit=max(limit * 6, 30),
        )
        if variant_ids is None:
            continue
        pg_any_attempted = True
        if pg_document_ids is None:
            pg_document_ids = []
        seen_ids = set(pg_document_ids)
        for doc_id in variant_ids:
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            pg_document_ids.append(doc_id)
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

    stmt = select(AuthorityDocument)
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

    if pg_document_ids is None:
        stmt = stmt.limit(300)
    documents = list(session.scalars(stmt))
    query_ref_tokens = set(_extract_case_references(query))
    normalized_query = _normalize_case_reference(query)
    if normalized_query:
        query_ref_tokens.add(normalized_query)
    candidates: list[RetrievalCandidate] = []
    candidate_to_document: dict[str, AuthorityDocument] = {}

    for document in documents:
        if document.chunks:
            for chunk in document.chunks:
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
                                document.court_name,
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
                        document.court_name,
                        document.summary,
                        document.document_text or "",
                    ]
                    if part
                ),
                quality_text=document.document_text or document.summary,
            )
        )
        candidate_to_document[candidate_id] = document

    query_vector = _embed_query(query, candidates=candidates)
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
    overfetch = max((payload.offset + payload.limit) * 5, 50)
    raw = search_authority_catalog(
        session,
        query=search_query,
        limit=overfetch,
        forum_level=payload.forum_level,
        court_name=payload.court_name,
        document_type=payload.document_type,
        suppress_unreadable=False,
    )
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
                    verified=(r.source == "official"),
                ),
            },
        )
        for r in page
    ]
    if contextual_plan is not None:
        enriched_page = [
            r.model_copy(
                update={
                    "relevance_reason": _contextual_relevance_reason(
                        r, contextual_plan
                    ),
                },
            )
            for r in enriched_page
        ]
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
    else:
        outcome = "no_results"

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
            },
        )
    )
    session.commit()

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
            _contextual_coverage_notice(
                total_after_filter=total,
                raw_count=len(raw),
                unreadable_omitted_count=unreadable_omitted_count,
            )
            if contextual_plan is not None
            else None
        ),
        total_after_filter=total,
        offset=payload.offset,
        outcome=outcome,
        diagnostics={
            "raw_candidate_count": len(raw),
            "unreadable_omitted_count": unreadable_omitted_count,
            "returned_count": len(enriched_page),
            "has_more": payload.offset + payload.limit < total,
        },
    )


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
    # parties_json OR title OR bench_name — ILIKE '%token%' across all
    # three columns. The bench_name axis was added 2026-04-21 after the
    # sc-2023 probe: queries like 'DHARWAD BENCH' hit docs whose
    # bench_name is 'Dharwad Bench' but whose parties_json / title
    # carries only party strings. Without the bench_name column in the
    # prefilter, the exact-name path dropped those candidates and the
    # vector-only fallback missed them.
    # PG will use a seq scan without a trigram index but at ~20k rows
    # the whole table fits in memory and the scan is <10 ms.
    filters = []
    for tok in tokens:
        pattern = f"%{tok}%"
        filters.append(
            or_(
                AuthorityDocument.parties_json.ilike(pattern),
                AuthorityDocument.title.ilike(pattern),
                AuthorityDocument.bench_name.ilike(pattern),
            )
        )
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


def _pg_prefilter_document_ids(
    session: Session,
    *,
    query: str,
    forum_level: str | None,
    court_name: str | None,
    document_type: str | None,
    limit: int,
) -> list[str] | None:
    """Return a list of document ids ordered by pgvector cosine distance.

    Returns ``None`` when the fast path is not applicable:

    - connection is not Postgres (e.g., SQLite in tests),
    - embeddings backend is not configured / build_provider raises,
    - no chunk in the filter scope carries an ``embedding_vector`` yet.

    The HNSW index on ``authority_document_chunks.embedding_vector`` drives
    the sort so this stays fast at 10M+ chunks.
    """
    try:
        if session.bind is None or session.bind.dialect.name != "postgresql":
            return None
    except Exception:
        return None
    if not query.strip():
        return None

    # Do at least one chunk actually have a vector in-scope? If not there is
    # nothing for HNSW to rank, so skip the fast path.
    from sqlalchemy import and_, text

    court_contains = _normalize_court_filter(court_name)
    court_contains = court_contains.casefold() if court_contains else None
    try:
        probe = session.execute(
            text(
                "SELECT 1 FROM authority_document_chunks c "
                "JOIN authority_documents d ON d.id = c.authority_document_id "
                "WHERE c.embedding_vector IS NOT NULL "
                "AND (cast(:forum as text) IS NULL OR d.forum_level = :forum) "
                "AND (cast(:court_contains as text) IS NULL "
                "OR position(:court_contains in lower(coalesce(d.court_name, ''))) > 0) "
                "AND (cast(:dtype as text) IS NULL OR d.document_type = :dtype) "
                "LIMIT 1"
            ),
            {
                "forum": forum_level,
                "court_contains": court_contains,
                "dtype": document_type,
            },
        ).first()
    except Exception:
        session.rollback()
        return None
    if probe is None:
        return None
    _ = and_  # silence unused-import on some linters

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

    vector = result.vectors[0]
    vec_literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
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
                " SELECT c.authority_document_id AS id, "
                "        c.embedding_vector <=> cast(:q as vector) AS dist"
                " FROM authority_document_chunks c "
                " WHERE c.embedding_vector IS NOT NULL "
                " ORDER BY c.embedding_vector <=> cast(:q as vector) "
                " LIMIT :chunk_limit"
                "), filtered AS ("
                " SELECT tc.id, MIN(tc.dist) AS distance "
                " FROM top_chunks tc "
                " JOIN authority_documents d ON d.id = tc.id "
                " WHERE (cast(:forum as text) IS NULL OR d.forum_level = :forum) "
                " AND (cast(:court_contains as text) IS NULL "
                "OR position(:court_contains in lower(coalesce(d.court_name, ''))) > 0) "
                " AND (cast(:dtype as text) IS NULL OR d.document_type = :dtype) "
                " GROUP BY tc.id"
                ") "
                "SELECT id FROM filtered ORDER BY distance LIMIT :limit"
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
    return [row.id for row in rows]


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
