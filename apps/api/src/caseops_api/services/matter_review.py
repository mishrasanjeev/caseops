from __future__ import annotations

import re
from datetime import UTC, datetime

from caseops_api.schemas.ai import (
    MatterDocumentReviewGenerateRequest,
    MatterDocumentReviewResponse,
    MatterDocumentSearchRequest,
    MatterDocumentSearchResponse,
    MatterDocumentSearchResult,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.matters import _get_matter_model, get_matter_workspace
from caseops_api.services.retrieval import RetrievalCandidate, rank_candidates

DATE_PATTERN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)

FACT_KEYWORDS: tuple[str, ...] = (
    "petition",
    "appeal",
    "application",
    "notice",
    "reply",
    "order",
    "hearing",
    "affidavit",
    "agreement",
    "invoice",
    "fir",
    "complaint",
    "counter",
)


def _normalize_chunks(text: str) -> list[str]:
    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n+", text) if chunk.strip()]
    if paragraphs:
        return paragraphs
    return [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", text) if chunk.strip()]


def _preview(value: str, limit: int = 220) -> str:
    compact = " ".join(value.split())
    return compact[:limit]


def _matter_retrieval_candidates(matter_model) -> list[RetrievalCandidate]:
    candidates: list[RetrievalCandidate] = []
    for attachment in matter_model.attachments:
        if attachment.chunks:
            for chunk in attachment.chunks:
                candidates.append(
                    RetrievalCandidate(
                        attachment_id=attachment.id,
                        attachment_name=attachment.original_filename,
                        content=chunk.content,
                    )
                )
            continue
        if attachment.extracted_text:
            candidates.append(
                RetrievalCandidate(
                    attachment_id=attachment.id,
                    attachment_name=attachment.original_filename,
                    content=attachment.extracted_text,
                )
            )
    return candidates


def _extract_facts(chunks: list[str]) -> list[str]:
    facts: list[str] = []
    seen: set[str] = set()
    prioritized = sorted(
        chunks,
        key=lambda chunk: (
            0 if any(keyword in chunk.lower() for keyword in FACT_KEYWORDS) else 1,
            len(chunk),
        ),
    )
    for chunk in prioritized:
        preview = _preview(chunk)
        lowered = preview.lower()
        if not preview or lowered in seen:
            continue
        facts.append(preview)
        seen.add(lowered)
        if len(facts) >= 5:
            break
    return facts


def _extract_chronology(chunks: list[str]) -> list[str]:
    chronology: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        if not DATE_PATTERN.search(chunk):
            continue
        preview = _preview(chunk)
        lowered = preview.lower()
        if lowered in seen:
            continue
        chronology.append(preview)
        seen.add(lowered)
        if len(chronology) >= 5:
            break
    return chronology


def _build_focus_query(matter_model, payload: MatterDocumentReviewGenerateRequest) -> str:
    if payload.focus:
        return payload.focus.strip()
    parts = [
        matter_model.title,
        matter_model.practice_area,
        matter_model.description or "",
        matter_model.client_name or "",
        matter_model.opposing_party or "",
        matter_model.court_name or "",
        matter_model.judge_name or "",
        "hearing chronology filing notice petition",
    ]
    return " ".join(part for part in parts if part).strip()


def generate_matter_document_review(
    session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterDocumentReviewGenerateRequest,
) -> MatterDocumentReviewResponse:
    workspace = get_matter_workspace(session, context=context, matter_id=matter_id)
    matter_model = _get_matter_model(session, context=context, matter_id=matter_id)

    source_attachments: list[str] = []
    readable_attachment_count = 0
    needs_ocr_count = 0
    for attachment in matter_model.attachments:
        if attachment.extracted_text:
            readable_attachment_count += 1
            source_attachments.append(attachment.original_filename)
        elif attachment.processing_status == "needs_ocr":
            needs_ocr_count += 1

    if not source_attachments:
        source_attachments = [attachment.original_filename for attachment in workspace.attachments]

    retrieval_candidates = _matter_retrieval_candidates(matter_model)
    retrieved = rank_candidates(
        query=_build_focus_query(matter_model, payload),
        candidates=retrieval_candidates,
        limit=8,
    )
    retrieved_chunks = [result.content for result in retrieved]

    all_chunks = [
        candidate.content
        for candidate in retrieval_candidates
    ]
    extracted_facts = _extract_facts(retrieved_chunks or all_chunks)
    chronology = _extract_chronology(retrieved_chunks + all_chunks)

    summary = (
        f"{workspace.matter.title} currently has {len(workspace.attachments)} uploaded matter "
        f"documents, with {readable_attachment_count} readable text attachment(s) used for the "
        "review. "
    )
    if chronology:
        summary += "A provisional chronology could be assembled from the uploaded record."
    elif all_chunks:
        summary += (
            "The uploaded text is readable, but date-based chronology extraction is still sparse."
        )
    else:
        summary += (
            "The review is relying on workspace metadata because no readable text "
            "attachment was found."
        )

    risks: list[str] = []
    if not workspace.attachments:
        risks.append("No matter documents have been uploaded yet.")
    elif not retrieval_candidates:
        risks.append("Uploaded matter files are present, but no readable text was extracted yet.")
    if needs_ocr_count > 0:
        risks.append(f"{needs_ocr_count} uploaded attachment(s) still require OCR processing.")
    if not chronology:
        risks.append("No chronology-ready dates were extracted from the current uploaded record.")
    if workspace.matter.status == "active" and not workspace.matter.next_hearing_on:
        risks.append("The matter is active, but no next hearing date is recorded in the workspace.")
    if not workspace.notes:
        risks.append("No internal note captures current strategy or document gaps.")
    if not risks:
        risks.append("No critical workspace or document coverage issues were detected.")

    recommended_actions = [
        "Validate the extracted chronology against filed pleadings and the latest court order.",
        "Review the top-ranked snippets before generating a hearing note or client update.",
        "Convert gaps in the extracted record into matter notes or hearing checklist items.",
    ]
    if payload.focus:
        recommended_actions.insert(0, f"Reviewer focus requested: {payload.focus.strip()}.")
    if workspace.matter.next_hearing_on:
        recommended_actions.append(
            f"Prepare the next hearing pack for {workspace.matter.next_hearing_on} "
            "using the uploaded record."
        )

    return MatterDocumentReviewResponse(
        matter_id=workspace.matter.id,
        review_type=payload.review_type,
        provider="caseops-matter-review-retrieval-v1",
        generated_at=datetime.now(UTC),
        headline=f"Document review for {workspace.matter.matter_code}",
        summary=summary,
        source_attachments=source_attachments or ["No matter attachments uploaded yet."],
        extracted_facts=extracted_facts
        or ["No matter facts could be extracted from uploaded text yet."],
        chronology=chronology or ["No document chronology could be extracted yet."],
        risks=risks[:5],
        recommended_actions=recommended_actions[:5],
    )


def search_matter_documents(
    session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterDocumentSearchRequest,
) -> MatterDocumentSearchResponse:
    matter_model = _get_matter_model(session, context=context, matter_id=matter_id)
    query = payload.query.strip()
    results = rank_candidates(
        query=query,
        candidates=_matter_retrieval_candidates(matter_model),
        limit=payload.limit,
    )

    return MatterDocumentSearchResponse(
        matter_id=matter_id,
        query=query,
        provider="caseops-matter-search-retrieval-v1",
        generated_at=datetime.now(UTC),
        results=[
            MatterDocumentSearchResult(
                attachment_id=result.attachment_id,
                attachment_name=result.attachment_name,
                snippet=result.snippet,
                score=result.score,
                matched_terms=result.matched_terms,
            )
            for result in results
        ],
    )
