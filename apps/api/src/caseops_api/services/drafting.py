"""Drafting studio pipeline (PRD §9.5, §10.3).

Owns the full state machine for a legal draft:

    draft (empty)  ── generate ──>  draft (v1)
                                      │
                                      ▼
                                   in_review  ── request_changes ──> changes_requested
                                      │                                      │
                                      │                         regenerate ──┘
                                      ▼
                                   approved  ── finalize ──> finalized (terminal)

Rules that ship with v1:

- Every new or regenerated version must emit at least one citation that
  survives the citation verifier (``services/citations.verify_citations``).
  ``approve`` fails closed when the current version has zero verified
  citations — no silent "approved without sources".
- Only a draft in ``in_review`` may transition to ``approved``; only
  ``approved`` can finalize. All transitions are recorded as a
  ``DraftReview`` row so the audit trail shows who moved it.
- ``finalized`` is terminal. Regeneration and submission are refused.
- ``review_required`` stays ``True`` on every status except ``approved``
  and ``finalized``. The UI uses this to lock external-share actions.

The LLM call is the same provider abstraction the recommendation and
hearing-pack services use. ``MockProvider`` emits a deterministic
drafting JSON so the full pipeline is exercisable offline.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    AuthorityDocument,
    Draft,
    DraftReview,
    DraftReviewAction,
    DraftStatus,
    DraftType,
    DraftVersion,
    Matter,
    ModelRun,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.authorities import search_authority_catalog
from caseops_api.services.citations import (
    Claim,
    SourceDoc,
    VerificationReport,
    verify_citations,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.llm import (
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMResponseFormatError,
    build_provider,
    generate_structured,
)

logger = logging.getLogger(__name__)

PURPOSE = "draft"


class _LLMDraftResponse(BaseModel):
    body: str = Field(min_length=20, max_length=20000)
    citations: list[str] = Field(default_factory=list, max_length=30)
    summary: str | None = Field(default=None, max_length=1200)


def _load_matter(session: Session, context: SessionContext, matter_id: str) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id, Matter.company_id == context.company.id
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found."
        )
    return matter


def _load_draft(
    session: Session, matter: Matter, draft_id: str, *, include_children: bool = True
) -> Draft:
    query = select(Draft).where(
        Draft.id == draft_id, Draft.matter_id == matter.id
    )
    if include_children:
        query = query.options(
            selectinload(Draft.versions),
            selectinload(Draft.reviews),
        )
    draft = session.scalar(query)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found."
        )
    return draft


def create_draft(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    title: str,
    draft_type: str = DraftType.BRIEF,
) -> Draft:
    matter = _load_matter(session, context, matter_id)
    draft = Draft(
        matter_id=matter.id,
        created_by_membership_id=context.membership.id,
        title=title.strip(),
        draft_type=draft_type,
        status=DraftStatus.DRAFT,
        review_required=True,
    )
    session.add(draft)
    session.flush()
    record_from_context(
        session,
        context,
        action="draft.created",
        target_type="draft",
        target_id=draft.id,
        matter_id=matter.id,
        metadata={"title": draft.title, "draft_type": draft.draft_type},
    )
    session.commit()
    session.refresh(draft)
    return draft


def list_drafts(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> list[Draft]:
    matter = _load_matter(session, context, matter_id)
    return list(
        session.scalars(
            select(Draft)
            .where(Draft.matter_id == matter.id)
            .options(selectinload(Draft.versions), selectinload(Draft.reviews))
            .order_by(Draft.updated_at.desc(), Draft.id.desc())
        )
    )


def get_draft(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    draft_id: str,
) -> Draft:
    matter = _load_matter(session, context, matter_id)
    return _load_draft(session, matter, draft_id)


def _build_messages(
    matter: Matter,
    draft: Draft,
    retrieved: list[AuthorityDocument],
    focus_note: str | None,
) -> list[LLMMessage]:
    system = (
        "You are drafting a legal document for an Indian litigation "
        "matter. Output strictly valid JSON. The `body` must be a "
        "complete document, not an outline. Every substantive legal "
        "claim should cite one of the provided authorities by its "
        "identifier in square brackets — for example [2021 SCC OnLine "
        "SC 123]. Do not invent authorities; only use those listed "
        "below. Keep language formal, paragraphs short, and preserve "
        "Indian-English conventions. Respond with JSON shaped as "
        "{\"body\": string, \"citations\": string[], \"summary\": string?}."
    )

    parts: list[str] = []
    parts.append(f"Matter: {matter.title} ({matter.matter_code})")
    parts.append(f"Practice area: {matter.practice_area}")
    parts.append(f"Forum: {matter.forum_level}")
    if matter.court_name:
        parts.append(f"Court: {matter.court_name}")
    if matter.judge_name:
        parts.append(f"Judge: {matter.judge_name}")
    if matter.client_name:
        parts.append(f"Client: {matter.client_name}")
    if matter.opposing_party:
        parts.append(f"Opposing party: {matter.opposing_party}")
    if matter.description:
        parts.append(f"Background: {matter.description}")
    parts.append(f"Draft title: {draft.title}")
    parts.append(f"Draft type: {draft.draft_type}")
    if focus_note:
        parts.append(f"Focus: {focus_note}")

    if retrieved:
        parts.append("Retrieved authorities (cite by identifier):")
        for doc in retrieved:
            # Format used by the mock provider to pick up identifiers.
            ident = doc.neutral_citation or doc.id
            parts.append(f"- CITATION: {ident}")
            if doc.summary:
                excerpt = doc.summary.strip().splitlines()[0][:300]
                parts.append(f"  EXCERPT: {excerpt}")
    else:
        parts.append(
            "No authorities retrieved. Produce a draft that flags "
            "`missing authorities` in the summary rather than inventing "
            "sources."
        )

    parts.append(
        "Respond with json. Emit the draft body and citations list."
    )

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content="\n".join(parts)),
    ]


def _prompt_hash(messages: list[LLMMessage]) -> str:
    digest = hashlib.sha256()
    for m in messages:
        digest.update(m.role.encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(m.content.encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


def _write_model_run(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    completion: LLMCompletion,
    prompt_hash: str,
    status_label: str = "ok",
    error: str | None = None,
) -> ModelRun:
    run = ModelRun(
        company_id=context.company.id,
        matter_id=matter_id,
        actor_membership_id=context.membership.id,
        purpose=PURPOSE,
        provider=completion.provider,
        model=completion.model,
        prompt_hash=prompt_hash,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
        status=status_label,
        error=error,
    )
    session.add(run)
    session.flush()
    return run


def _verify_version_citations(
    session: Session,
    citations: list[str],
) -> tuple[list[str], int]:
    """Verify that each citation is an authority we actually hold.
    Returns (surviving_citations, verified_count)."""
    unique = list(dict.fromkeys(c.strip() for c in citations if c and c.strip()))
    if not unique:
        return [], 0
    docs = list(
        session.scalars(
            select(AuthorityDocument).where(
                (AuthorityDocument.neutral_citation.in_(unique))
                | (AuthorityDocument.id.in_(unique))
            )
        )
    )
    sources: list[SourceDoc] = []
    known: set[str] = set()
    for doc in docs:
        identifier = doc.neutral_citation or doc.id
        aliases = tuple({doc.id, doc.neutral_citation or doc.id})
        sources.append(
            SourceDoc(identifier=identifier, aliases=aliases, text=doc.summary or "")
        )
        known.add(identifier)
        known.add(doc.id)
        if doc.neutral_citation:
            known.add(doc.neutral_citation)
    claims = [Claim(citation=c) for c in unique]
    report: VerificationReport = verify_citations(claims, sources)
    surviving = [c for c in unique if c in known]
    return surviving, report.verified_count


def generate_draft_version(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    draft_id: str,
    focus_note: str | None = None,
    template_key: str | None = None,
    provider: LLMProvider | None = None,
) -> Draft:
    del template_key  # reserved for future template selection
    matter = _load_matter(session, context, matter_id)
    draft = _load_draft(session, matter, draft_id)

    if draft.status == DraftStatus.FINALIZED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finalized drafts cannot be regenerated.",
        )

    retrieved_hits = search_authority_catalog(
        session, query=f"{matter.title} {matter.description or ''}", limit=5
    )
    retrieved_docs: list[AuthorityDocument] = []
    for hit in retrieved_hits:
        doc = session.get(AuthorityDocument, hit.authority_document_id)
        if doc is not None:
            retrieved_docs.append(doc)

    messages = _build_messages(matter, draft, retrieved_docs, focus_note)
    prompt_hash = _prompt_hash(messages)
    llm = provider or build_provider()
    llm_context = LLMCallContext(
        tenant_id=context.company.id, matter_id=matter.id, purpose=PURPOSE
    )
    try:
        response, completion = generate_structured(
            llm,
            schema=_LLMDraftResponse,
            messages=messages,
            context=llm_context,
        )
    except (LLMResponseFormatError, ValidationError) as exc:
        logger.warning("Draft LLM refused / malformed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not assemble a valid draft.",
        ) from exc

    surviving, verified_count = _verify_version_citations(session, response.citations)
    if verified_count == 0 and response.citations:
        logger.info(
            "Draft %s generated with %d citations, 0 verified.",
            draft.id,
            len(response.citations),
        )

    model_run = _write_model_run(
        session,
        context=context,
        matter_id=matter.id,
        completion=completion,
        prompt_hash=prompt_hash,
    )

    next_revision = 1
    if draft.versions:
        next_revision = max(v.revision for v in draft.versions) + 1

    version = DraftVersion(
        draft_id=draft.id,
        generated_by_membership_id=context.membership.id,
        model_run_id=model_run.id,
        revision=next_revision,
        body=response.body,
        citations_json=json.dumps(surviving),
        verified_citation_count=verified_count,
        summary=response.summary,
    )
    session.add(version)
    session.flush()

    draft.current_version_id = version.id
    draft.status = DraftStatus.DRAFT  # fresh version always resets to draft
    draft.review_required = True
    draft.updated_at = datetime.now(UTC)
    session.flush()
    record_from_context(
        session,
        context,
        action="draft.version_generated",
        target_type="draft",
        target_id=draft.id,
        matter_id=matter.id,
        metadata={
            "revision": version.revision,
            "verified_citation_count": version.verified_citation_count,
            "cited_count": len(surviving),
        },
    )
    session.commit()
    session.refresh(draft)
    return draft


def _record_review(
    session: Session,
    *,
    draft: Draft,
    version_id: str | None,
    action: str,
    context: SessionContext,
    notes: str | None,
) -> DraftReview:
    review = DraftReview(
        draft_id=draft.id,
        version_id=version_id,
        actor_membership_id=context.membership.id,
        action=action,
        notes=notes,
    )
    session.add(review)
    session.flush()
    return review


def _assert_current_version(draft: Draft) -> DraftVersion:
    if draft.current_version_id is None or not draft.versions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft has no generated version yet. Generate one first.",
        )
    current = next(
        (v for v in draft.versions if v.id == draft.current_version_id), None
    )
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft's current version is missing.",
        )
    return current


def transition_draft(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    draft_id: str,
    action: Literal["submit", "request_changes", "approve", "finalize"],
    notes: str | None = None,
) -> Draft:
    matter = _load_matter(session, context, matter_id)
    draft = _load_draft(session, matter, draft_id)

    if draft.status == DraftStatus.FINALIZED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft is finalized; no further transitions allowed.",
        )

    current = _assert_current_version(draft)

    if action == DraftReviewAction.SUBMIT:
        if draft.status not in {DraftStatus.DRAFT, DraftStatus.CHANGES_REQUESTED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot submit from status {draft.status!r}.",
            )
        draft.status = DraftStatus.IN_REVIEW
        draft.review_required = True
    elif action == DraftReviewAction.REQUEST_CHANGES:
        if draft.status != DraftStatus.IN_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only in-review drafts can have changes requested.",
            )
        draft.status = DraftStatus.CHANGES_REQUESTED
        draft.review_required = True
    elif action == DraftReviewAction.APPROVE:
        if draft.status != DraftStatus.IN_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only in-review drafts can be approved.",
            )
        if current.verified_citation_count <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Cannot approve a draft with zero verified citations. "
                    "Regenerate with grounded authorities first."
                ),
            )
        draft.status = DraftStatus.APPROVED
        draft.review_required = False
    elif action == DraftReviewAction.FINALIZE:
        if draft.status != DraftStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only approved drafts can be finalized.",
            )
        draft.status = DraftStatus.FINALIZED
        draft.review_required = False
    else:  # pragma: no cover — guarded by literal type
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action {action!r}.",
        )

    _record_review(
        session,
        draft=draft,
        version_id=current.id,
        action=action,
        context=context,
        notes=notes,
    )
    draft.updated_at = datetime.now(UTC)
    session.flush()
    record_from_context(
        session,
        context,
        action=f"draft.{action}",
        target_type="draft",
        target_id=draft.id,
        matter_id=matter.id,
        metadata={
            "status_after": draft.status,
            "version_id": current.id,
            "notes_len": len(notes) if notes else 0,
        },
    )
    session.commit()
    session.refresh(draft)
    return draft


def render_version_docx(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    draft_id: str,
    version_id: str | None = None,
) -> tuple[bytes, str]:
    """Return (docx_bytes, suggested_filename). Falls back to the
    draft's current version when version_id is not supplied."""
    matter = _load_matter(session, context, matter_id)
    draft = _load_draft(session, matter, draft_id)
    target_id = version_id or draft.current_version_id
    if not target_id or not draft.versions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft has no version to export. Generate one first.",
        )
    version = next((v for v in draft.versions if v.id == target_id), None)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft version not found.",
        )

    # Import inline to avoid pulling python-docx into the process when
    # the export route is never hit (keeps cold start slim).
    from docx import Document  # type: ignore
    from docx.shared import Pt

    doc = Document()
    title = doc.add_heading(draft.title, level=1)
    for run in title.runs:
        run.font.size = Pt(18)

    meta = doc.add_paragraph()
    meta.add_run(f"Matter: {matter.title} ({matter.matter_code}) · ")
    meta.add_run(f"Draft type: {draft.draft_type} · ")
    meta.add_run(f"Revision {version.revision} · ")
    meta.add_run(f"Status: {draft.status}")
    meta.runs[-1].italic = True

    doc.add_paragraph()  # spacer

    # Body — split on blank lines to produce readable paragraphs.
    for block in version.body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        para = doc.add_paragraph()
        for line_idx, line in enumerate(block.split("\n")):
            if line_idx:
                para.add_run().add_break()
            para.add_run(line)

    try:
        citations = json.loads(version.citations_json) if version.citations_json else []
    except json.JSONDecodeError:
        citations = []
    if citations:
        doc.add_heading("Authorities cited", level=2)
        for c in citations:
            doc.add_paragraph(c, style="List Bullet")

    if draft.review_required:
        doc.add_paragraph(
            "Review required — this draft has not been approved by a partner.",
        ).runs[-1].italic = True

    buffer = io.BytesIO()
    doc.save(buffer)
    safe_title = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in draft.title
    ).strip("-")[:60] or "draft"
    filename = f"{safe_title}-r{version.revision}.docx"
    return buffer.getvalue(), filename


def load_draft_record(draft: Draft) -> dict:
    """Shape the Draft for pydantic serialisation with parsed citations."""
    versions = sorted(draft.versions, key=lambda v: v.revision)
    versions_payload = []
    for v in versions:
        try:
            cites = json.loads(v.citations_json) if v.citations_json else []
        except json.JSONDecodeError:
            cites = []
        versions_payload.append(
            {
                "id": v.id,
                "draft_id": v.draft_id,
                "revision": v.revision,
                "body": v.body,
                "citations": cites,
                "verified_citation_count": v.verified_citation_count,
                "summary": v.summary,
                "generated_by_membership_id": v.generated_by_membership_id,
                "model_run_id": v.model_run_id,
                "created_at": v.created_at,
            }
        )
    return {
        "id": draft.id,
        "matter_id": draft.matter_id,
        "created_by_membership_id": draft.created_by_membership_id,
        "title": draft.title,
        "draft_type": draft.draft_type,
        "status": draft.status,
        "review_required": draft.review_required,
        "current_version_id": draft.current_version_id,
        "versions": versions_payload,
        "reviews": [
            {
                "id": r.id,
                "draft_id": r.draft_id,
                "version_id": r.version_id,
                "actor_membership_id": r.actor_membership_id,
                "action": r.action,
                "notes": r.notes,
                "created_at": r.created_at,
            }
            for r in sorted(draft.reviews, key=lambda r: r.created_at)
        ],
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }
