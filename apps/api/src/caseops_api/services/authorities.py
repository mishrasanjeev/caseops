from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityCitation,
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityIngestionRun,
    AuthorityIngestionStatus,
    MembershipRole,
)
from caseops_api.schemas.authorities import (
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
from caseops_api.services.identity import SessionContext
from caseops_api.services.retrieval import RetrievalCandidate, rank_candidates


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


def search_authority_catalog(
    session: Session,
    *,
    query: str,
    limit: int,
    forum_level: str | None = None,
    court_name: str | None = None,
    document_type: str | None = None,
) -> list[AuthoritySearchResult]:
    # Fast path: when running on Postgres + we have embeddings in the column
    # AND we can build a query vector, ask pgvector to pick top-K chunks via
    # the HNSW index, then load only those documents. At any real corpus
    # scale this is dramatically faster than the 300-row scan below.
    pg_document_ids = _pg_prefilter_document_ids(
        session,
        query=query,
        forum_level=forum_level,
        court_name=court_name,
        document_type=document_type,
        limit=max(limit * 6, 30),
    )

    stmt = select(AuthorityDocument)
    if pg_document_ids is not None:
        if not pg_document_ids:
            return []
        stmt = stmt.where(AuthorityDocument.id.in_(pg_document_ids))
    else:
        stmt = stmt.order_by(
            AuthorityDocument.decision_date.desc(),
            AuthorityDocument.updated_at.desc(),
        )
    if forum_level:
        stmt = stmt.where(AuthorityDocument.forum_level == forum_level)
    if court_name:
        stmt = stmt.where(AuthorityDocument.court_name == court_name)
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
        if court_name and document.court_name == court_name:
            adjusted_score += 16
        if forum_level and document.forum_level == forum_level:
            adjusted_score += 8
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
    return results[:limit]


def search_authorities(
    session: Session,
    *,
    context: SessionContext,
    payload: AuthoritySearchRequest,
) -> AuthoritySearchResponse:
    del context
    return AuthoritySearchResponse(
        query=payload.query,
        provider="caseops-authority-search-v2",
        generated_at=datetime.now(UTC),
        results=search_authority_catalog(
            session,
            query=payload.query,
            limit=payload.limit,
            forum_level=payload.forum_level,
            court_name=payload.court_name,
            document_type=payload.document_type,
        ),
    )


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

    try:
        probe = session.execute(
            text(
                "SELECT 1 FROM authority_document_chunks c "
                "JOIN authority_documents d ON d.id = c.authority_document_id "
                "WHERE c.embedding_vector IS NOT NULL "
                "AND (cast(:forum as text) IS NULL OR d.forum_level = :forum) "
                "AND (cast(:court as text) IS NULL OR d.court_name = :court) "
                "AND (cast(:dtype as text) IS NULL OR d.document_type = :dtype) "
                "LIMIT 1"
            ),
            {
                "forum": forum_level,
                "court": court_name,
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
        result = provider.embed([query])
    except Exception:
        return None
    if not result.vectors:
        return None

    vector = result.vectors[0]
    vec_literal = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
    try:
        rows = session.execute(
            text(
                "WITH candidates AS ("
                " SELECT c.authority_document_id AS id, "
                "        MIN(c.embedding_vector <=> cast(:q as vector)) AS distance"
                " FROM authority_document_chunks c "
                " JOIN authority_documents d ON d.id = c.authority_document_id "
                " WHERE c.embedding_vector IS NOT NULL "
                " AND (cast(:forum as text) IS NULL OR d.forum_level = :forum) "
                " AND (cast(:court as text) IS NULL OR d.court_name = :court) "
                " AND (cast(:dtype as text) IS NULL OR d.document_type = :dtype) "
                " GROUP BY c.authority_document_id"
                ") "
                "SELECT id FROM candidates ORDER BY distance LIMIT :limit"
            ),
            {
                "q": vec_literal,
                "forum": forum_level,
                "court": court_name,
                "dtype": document_type,
                "limit": limit,
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
        result = provider.embed([query])
    except Exception:
        return None
    if not result.vectors:
        return None
    return result.vectors[0]
