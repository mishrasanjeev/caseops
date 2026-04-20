"""Matter executive summary — AI-generated case overview (Sprint Q5).

Given a matter, produce a structured summary: overview, key facts,
timeline, legal issues, statutes cited. Computed on demand via the
existing LLM pipeline; the persistence of generated summaries is a
follow-up (would live on a new ``Matter.executive_summary`` JSONB
column plus a regeneration button).

Design choices:

- Uses ``generate_structured`` with Haiku fallback (already wired in
  ``services.recommendations``) so a Sonnet JSON malformation never
  502s this endpoint.
- Concatenates matter text from: matter title + description,
  attached-document text (first 4 k chars each, capped at 6 sources),
  hearings, and latest 3 draft versions. Skips any empty field.
- Returns a typed Pydantic model so the web can render stable tiles.
- Budget: one LLM call per request. At ~$0.006 Haiku × ~30 summaries
  per active user per week ≈ $0.20 / user / month. Order-of-magnitude
  cheap.
- Holds PRD §6.3 grounding rule: every statute / authority the
  summary cites must trace to a doc attached to the matter. No
  hallucinated precedents — we ask the model for only `sections_cited`
  (statutes) on the matter's own docs, not external citations.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Draft,
    DraftVersion,
    Matter,
    MatterAttachment,
    MatterHearing,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.llm import (
    AnthropicProvider,
    LLMCallContext,
    LLMMessage,
    LLMProvider,
    LLMResponseFormatError,
    build_provider,
    generate_structured,
)
from caseops_api.services.matters import _get_matter_model

logger = logging.getLogger(__name__)


# Same constant as services.recommendations — keep in sync. The
# duplication is intentional (low cost, avoids cross-module coupling
# between two domain services) until a shared llm_fallbacks module
# justifies itself.
_HAIKU_FALLBACK_MODEL = "claude-haiku-4-5-20251001"

# Cap per-doc input so a 500 KB attachment doesn't single-handedly
# saturate the prompt. 4 k chars is roughly 2 pages of reasoned text.
_MAX_ATTACHMENT_CHARS = 4000
_MAX_ATTACHMENTS = 6
_MAX_DRAFT_VERSIONS = 3


class MatterSummaryTimelineEvent(BaseModel):
    date: str | None = Field(
        default=None,
        description=(
            "ISO yyyy-mm-dd. None when a document references an event "
            "with no specific date."
        ),
    )
    label: str = Field(min_length=2, max_length=240)


class MatterExecutiveSummary(BaseModel):
    """Structured overview of a matter for the cockpit summary tile.

    Every field is optional in the sense that an empty matter might
    produce short / blank tiles — but the schema is fixed so the UI
    always knows the keys.
    """

    overview: str = Field(min_length=0, max_length=4000)
    key_facts: list[str] = Field(default_factory=list, max_length=20)
    timeline: list[MatterSummaryTimelineEvent] = Field(
        default_factory=list, max_length=30
    )
    legal_issues: list[str] = Field(default_factory=list, max_length=12)
    sections_cited: list[str] = Field(default_factory=list, max_length=25)
    generated_at: datetime


def _haiku_fallback_provider() -> LLMProvider | None:
    from caseops_api.core.settings import get_settings

    settings = get_settings()
    if (settings.llm_provider or "").lower() != "anthropic":
        return None
    return AnthropicProvider(
        model=_HAIKU_FALLBACK_MODEL,
        api_key=settings.llm_api_key,
        prompt_cache=bool(getattr(settings, "llm_prompt_cache_enabled", True)),
    )


def _load_matter_context(session: Session, matter: Matter) -> str:
    """Concatenate everything the model needs to see for a given matter.

    Capped at each input type to keep the prompt bounded; we'd rather
    generate a tight summary on 25 k chars of the most signal than a
    lossy one on 200 k chars of the whole attachment library.
    """
    parts: list[str] = []
    parts.append("# Matter")
    parts.append(f"Title: {matter.title or ''}")
    if matter.matter_code:
        parts.append(f"Matter code: {matter.matter_code}")
    if matter.practice_area:
        parts.append(f"Practice area: {matter.practice_area}")
    if matter.forum_level:
        parts.append(f"Forum: {matter.forum_level}")
    if matter.court_name:
        parts.append(f"Court: {matter.court_name}")
    if matter.client_name:
        parts.append(f"Client: {matter.client_name}")
    if matter.opposing_party:
        parts.append(f"Opposing: {matter.opposing_party}")
    if matter.description:
        parts.append(f"\n## Description\n{matter.description}")

    # Attachments — most recent first, per-doc capped
    attachments = list(
        session.scalars(
            select(MatterAttachment)
            .where(MatterAttachment.matter_id == matter.id)
            .where(MatterAttachment.extracted_text.is_not(None))
            .order_by(MatterAttachment.created_at.desc())
            .limit(_MAX_ATTACHMENTS)
        )
    )
    if attachments:
        parts.append("\n## Attached documents")
        for a in attachments:
            text = (a.extracted_text or "").strip()[:_MAX_ATTACHMENT_CHARS]
            if not text:
                continue
            parts.append(f"\n### {a.display_name or a.filename}")
            parts.append(text)

    # Hearings — chronological
    hearings = list(
        session.scalars(
            select(MatterHearing)
            .where(MatterHearing.matter_id == matter.id)
            .order_by(MatterHearing.scheduled_at.asc().nulls_last())
        )
    )
    if hearings:
        parts.append("\n## Hearings")
        for h in hearings:
            dt = h.scheduled_at.isoformat() if h.scheduled_at else "(undated)"
            purpose = h.purpose or "(no purpose set)"
            status_str = (h.status.value if h.status else "scheduled")
            parts.append(f"- {dt} | {status_str} | {purpose}")

    # Latest draft versions across all drafts on the matter
    draft_versions = list(
        session.execute(
            select(DraftVersion, Draft)
            .join(Draft, Draft.id == DraftVersion.draft_id)
            .where(Draft.matter_id == matter.id)
            .order_by(DraftVersion.created_at.desc())
            .limit(_MAX_DRAFT_VERSIONS)
        ).all()
    )
    if draft_versions:
        parts.append("\n## Latest drafts")
        for ver, drft in draft_versions:
            parts.append(f"\n### {drft.title or drft.draft_type or 'Draft'}")
            body = (ver.body or "").strip()[:_MAX_ATTACHMENT_CHARS]
            parts.append(body)

    return "\n".join(parts)


_SYSTEM_PROMPT = (
    "You are an Indian litigation assistant. Given the matter dossier "
    "below, return ONLY valid JSON matching this shape:\n"
    "{\n"
    '  "overview": str,              # 2-4 sentences, plain prose\n'
    '  "key_facts": [str, ...],       # 3-10 short bullets, each <= 200 chars\n'
    '  "timeline": [{"date": "yyyy-mm-dd" | null, "label": str}, ...],  # <= 20 entries\n'
    '  "legal_issues": [str, ...],    # 2-6 short bullets, each <= 160 chars\n'
    '  "sections_cited": [str, ...]  # exact statute tokens as they'
    " appear in the dossier, <= 15 entries\n"
    "}\n\n"
    "Hard rules:\n"
    "- Facts, dates, names come ONLY from the dossier. If the dossier "
    "is silent, use `[____]` placeholders or leave the field empty.\n"
    "- Do NOT invent authorities, parties, or citations.\n"
    "- `sections_cited` MUST quote the statute string as it appears in "
    "the dossier — do not rephrase. BNSS vs BNS matters: section 483 "
    "of BNSS (bail) is distinct from section 483 of BNS (kidnap).\n"
    "- Output a single JSON object. No preamble, no code fences."
)


class _LLMSummary(BaseModel):
    """LLM output schema. Mirrors MatterExecutiveSummary minus
    generated_at which we stamp server-side."""

    overview: str = Field(default="", max_length=4000)
    key_facts: list[str] = Field(default_factory=list, max_length=20)
    timeline: list[MatterSummaryTimelineEvent] = Field(
        default_factory=list, max_length=30
    )
    legal_issues: list[str] = Field(default_factory=list, max_length=12)
    sections_cited: list[str] = Field(default_factory=list, max_length=25)


def generate_matter_summary(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    provider: LLMProvider | None = None,
) -> MatterExecutiveSummary:
    """Produce a fresh executive summary for a matter.

    Uses Haiku by default for cost + JSON reliability. The caller's
    matter must be tenant-scoped — ``_get_matter_model`` raises 404
    when the matter does not belong to the caller's company.
    """
    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    dossier = _load_matter_context(session, matter)
    messages = [
        LLMMessage(role="system", content=_SYSTEM_PROMPT),
        LLMMessage(role="user", content=dossier),
    ]
    llm = provider or build_provider(purpose="metadata_extract")

    call_ctx = LLMCallContext(
        tenant_id=context.company.id,
        matter_id=matter.id,
        purpose="matter_summary",
    )

    def _call(p: LLMProvider) -> Any:
        return generate_structured(
            p,
            session=session,
            schema=_LLMSummary,
            messages=messages,
            context=call_ctx,
            temperature=0.0,
            max_tokens=4096,
        )

    try:
        parsed, _completion = _call(llm)
    except LLMResponseFormatError as exc:
        # Same fallback pattern as services.recommendations — one retry
        # with Haiku when the primary returned malformed JSON.
        fallback = _haiku_fallback_provider()
        if fallback is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        logger.warning(
            "matter summary: primary LLM %s returned invalid JSON; retrying Haiku",
            getattr(llm, "model", "<unknown>"),
        )
        try:
            parsed, _completion = _call(fallback)
        except LLMResponseFormatError as retry_exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"Both primary and Haiku fallback returned invalid "
                    f"JSON. Primary: {exc}. Fallback: {retry_exc}"
                ),
            ) from retry_exc

    return MatterExecutiveSummary(
        overview=parsed.overview,
        key_facts=parsed.key_facts,
        timeline=parsed.timeline,
        legal_issues=parsed.legal_issues,
        sections_cited=parsed.sections_cited,
        generated_at=datetime.now(UTC),
    )


__all__ = [
    "MatterExecutiveSummary",
    "MatterSummaryTimelineEvent",
    "generate_matter_summary",
]
