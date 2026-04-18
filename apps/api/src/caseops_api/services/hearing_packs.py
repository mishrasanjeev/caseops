"""Hearing pack assembly (PRD §9.6, §4.5).

A HearingPack is a lawyer-facing brief for a specific hearing: chronology,
last order summary, pending compliance items, issues, opposition points,
authority cards, and oral points. The service:

1. Loads the matter + the hearing + recent court orders, cause-list entries,
   tasks, and notes — all tenant-scoped by matter_id.
2. Calls the configured ``LLMProvider`` with a structured prompt; response
   is validated as JSON.
3. Persists a ``HearingPack`` (``review_required=True`` always) plus one
   row per item. The pack stays in ``draft`` status until a human reviews
   it — matching the §17.4 "no final client-facing AI answer" rule.

The LLM call is deterministic when ``CASEOPS_LLM_PROVIDER=mock``, so the
test suite can assert full pack shapes without a live API key.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    AuthorityDocument,
    HearingPack,
    HearingPackItem,
    HearingPackItemKind,
    HearingPackStatus,
    Matter,
    MatterActivity,
    MatterCauseListEntry,
    MatterCourtOrder,
    MatterHearing,
    MatterTask,
    ModelRun,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.llm import (
    PURPOSE_HEARING_PACK,
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMResponseFormatError,
    build_provider,
    generate_structured,
    max_tokens_for_purpose,
)
from caseops_api.services.matter_access import assert_access

logger = logging.getLogger(__name__)


PURPOSE = "hearing_pack"

# The item kinds we accept from the model. Anything else is dropped.
_ALLOWED_KINDS = {kind.value for kind in HearingPackItemKind}


class _LLMItem(BaseModel):
    item_type: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=255)
    body: str = Field(min_length=2, max_length=4000)
    rank: int = Field(default=0, ge=0, le=500)
    source_ref: str | None = Field(default=None, max_length=500)


class _LLMPackResponse(BaseModel):
    summary: str = Field(min_length=10, max_length=4000)
    items: list[_LLMItem] = Field(min_length=1, max_length=40)


def _load_matter(session: Session, context: SessionContext, matter_id: str) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id, Matter.company_id == context.company.id
        )
    )
    if not matter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found."
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _load_hearing(
    session: Session, matter: Matter, hearing_id: str
) -> MatterHearing:
    hearing = session.scalar(
        select(MatterHearing).where(
            MatterHearing.id == hearing_id, MatterHearing.matter_id == matter.id
        )
    )
    if not hearing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hearing not found."
        )
    return hearing


def _build_messages(
    matter: Matter,
    hearing: MatterHearing | None,
    recent_orders: list[MatterCourtOrder],
    recent_cause_list: list[MatterCauseListEntry],
    open_tasks: list[MatterTask],
    recent_activity: list[MatterActivity],
) -> list[LLMMessage]:
    system = (
        "You are preparing a hearing pack for an Indian litigation matter. "
        "Output strictly valid JSON matching the provided schema. Every "
        "item must tie back to the matter facts below — do not invent "
        "orders, parties, or authorities. Keep each `body` to at most "
        "2-3 sentences. Prefer concrete dates and references over vague "
        "summaries."
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
    if hearing:
        parts.append(
            f"Upcoming hearing: {hearing.hearing_on} at {hearing.forum_name}"
            f" — purpose: {hearing.purpose}"
        )
    if recent_orders:
        parts.append("Recent court orders:")
        for o in recent_orders:
            parts.append(f"  - {o.order_date} — {o.title}: {o.summary}")
    if recent_cause_list:
        parts.append("Recent cause-list entries:")
        for e in recent_cause_list:
            parts.append(
                f"  - {e.listing_date} at {e.forum_name}"
                + (f", stage: {e.stage}" if e.stage else "")
            )
    if open_tasks:
        parts.append("Open tasks:")
        for t in open_tasks:
            due = f" (due {t.due_on})" if t.due_on else ""
            parts.append(f"  - {t.title}{due}")
    if recent_activity:
        parts.append("Recent activity:")
        for a in recent_activity[:6]:
            parts.append(f"  - {a.event_type}: {a.title}")

    instruction = (
        "Produce a hearing pack with these keys: summary, items. Each item "
        "has {item_type, title, body, rank, source_ref?}. Allowed item_type "
        "values: " + ", ".join(sorted(_ALLOWED_KINDS)) + ". "
        "Use item_type='chronology' for matter history, 'last_order' for "
        "the most recent order summary, 'pending_compliance' for compliance "
        "still due, 'issue' for live legal issues, 'opposition_point' for "
        "anticipated opposition arguments, 'authority_card' for supporting "
        "authorities (include neutral citation in source_ref), and "
        "'oral_point' for bullet points the lawyer should raise in court. "
        "Rank items from 0 upward in the order a partner would read them."
    )

    user = "\n".join(parts) + "\n\n" + instruction

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
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


def _normalise_items(items: list[_LLMItem]) -> list[_LLMItem]:
    # Drop any item_type we don't recognise — it's safer than letting a
    # rogue string pollute the UI grouping.
    filtered = [item for item in items if item.item_type in _ALLOWED_KINDS]
    # Deterministic rank if the model was lazy.
    for idx, item in enumerate(filtered):
        if item.rank == 0:
            filtered[idx] = item.model_copy(update={"rank": idx + 1})
    filtered.sort(key=lambda i: i.rank)
    return filtered


def _verify_authority_sources(
    session: Session, items: list[_LLMItem]
) -> list[_LLMItem]:
    """PRD §6.1 / §17.4: citations in a hearing pack must be grounded.

    The LLM emits ``authority_card`` items with a ``source_ref`` that
    is supposed to identify a judgment in the corpus. The earlier
    pipeline persisted these unverified — so a hallucinated citation
    could land in the pack and mislead a reviewing partner. We now
    check every ``authority_card`` against
    ``authority_documents.{neutral_citation, case_reference, id}`` and
    drop any item whose ``source_ref`` is unknown. Non-authority items
    (chronology, last_order, pending_compliance, issue,
    opposition_point, oral_point) are matter-derived and pass through.
    """
    cards = [item for item in items if item.item_type == "authority_card"]
    needles = {(c.source_ref or "").strip() for c in cards}
    needles.discard("")
    if not needles:
        return items

    known: set[str] = set()
    docs = session.scalars(
        select(AuthorityDocument).where(
            (AuthorityDocument.neutral_citation.in_(needles))
            | (AuthorityDocument.case_reference.in_(needles))
            | (AuthorityDocument.id.in_(needles))
        )
    )
    for doc in docs:
        if doc.neutral_citation:
            known.add(doc.neutral_citation)
        if doc.case_reference:
            known.add(doc.case_reference)
        known.add(doc.id)

    out: list[_LLMItem] = []
    dropped = 0
    for item in items:
        if item.item_type != "authority_card":
            out.append(item)
            continue
        ref = (item.source_ref or "").strip()
        if ref and ref in known:
            out.append(item)
        else:
            dropped += 1
    if dropped:
        logger.info(
            "hearing pack: dropped %d authority_card item(s) with "
            "unverifiable source_ref", dropped,
        )
    return out


def generate_hearing_pack(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    hearing_id: str | None = None,
    provider: LLMProvider | None = None,
) -> HearingPack:
    matter = _load_matter(session, context, matter_id)
    hearing: MatterHearing | None = None
    if hearing_id:
        hearing = _load_hearing(session, matter, hearing_id)

    recent_orders = (
        session.scalars(
            select(MatterCourtOrder)
            .where(MatterCourtOrder.matter_id == matter.id)
            .order_by(MatterCourtOrder.order_date.desc())
            .limit(5)
        ).all()
        if hasattr(MatterCourtOrder, "matter_id")
        else []
    )
    recent_cause_list = session.scalars(
        select(MatterCauseListEntry)
        .where(MatterCauseListEntry.matter_id == matter.id)
        .order_by(MatterCauseListEntry.listing_date.desc())
        .limit(5)
    ).all()
    open_tasks = session.scalars(
        select(MatterTask)
        .where(
            MatterTask.matter_id == matter.id,
            MatterTask.status != "completed",
        )
        .order_by(MatterTask.due_on.asc().nullslast())
        .limit(10)
    ).all()
    recent_activity = session.scalars(
        select(MatterActivity)
        .where(MatterActivity.matter_id == matter.id)
        .order_by(MatterActivity.created_at.desc())
        .limit(10)
    ).all()

    messages = _build_messages(
        matter,
        hearing,
        list(recent_orders),
        list(recent_cause_list),
        list(open_tasks),
        list(recent_activity),
    )
    prompt_hash = _prompt_hash(messages)
    llm = provider or build_provider(purpose=PURPOSE_HEARING_PACK)
    llm_context = LLMCallContext(
        tenant_id=context.company.id,
        matter_id=matter.id,
        purpose=PURPOSE,
    )
    try:
        response, completion = generate_structured(
            llm,
            schema=_LLMPackResponse,
            messages=messages,
            context=llm_context,
            max_tokens=max_tokens_for_purpose(PURPOSE_HEARING_PACK),
        )
    except LLMResponseFormatError as exc:
        logger.warning("Hearing pack LLM refused / malformed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not assemble a valid hearing pack.",
        ) from exc

    model_run = _write_model_run(
        session,
        context=context,
        matter_id=matter.id,
        completion=completion,
        prompt_hash=prompt_hash,
    )

    items = _normalise_items(response.items)
    # Fail closed on unverifiable authority citations — this is the
    # gap earlier pipelines had (no validation against the corpus).
    items = _verify_authority_sources(session, items)
    if not items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Hearing pack generation produced no usable items.",
        )

    pack = HearingPack(
        matter_id=matter.id,
        hearing_id=hearing.id if hearing else None,
        generated_by_membership_id=context.membership.id,
        model_run_id=model_run.id,
        status=HearingPackStatus.DRAFT,
        summary=response.summary,
        review_required=True,
        generated_at=datetime.now(UTC),
    )
    session.add(pack)
    session.flush()
    for item in items:
        session.add(
            HearingPackItem(
                pack_id=pack.id,
                item_type=item.item_type,
                title=item.title,
                body=item.body,
                rank=item.rank,
                source_ref=item.source_ref,
            )
        )
    record_from_context(
        session,
        context,
        action="hearing_pack.generated",
        target_type="hearing_pack",
        target_id=pack.id,
        matter_id=matter.id,
        metadata={
            "hearing_id": hearing.id if hearing else None,
            "item_count": len(items),
        },
    )
    session.commit()
    session.refresh(pack)
    return pack


def get_latest_hearing_pack(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    hearing_id: str | None = None,
) -> HearingPack | None:
    matter = _load_matter(session, context, matter_id)
    query = (
        select(HearingPack)
        .where(HearingPack.matter_id == matter.id)
        .options(selectinload(HearingPack.items))
        .order_by(HearingPack.generated_at.desc())
        .limit(1)
    )
    if hearing_id is not None:
        query = query.where(HearingPack.hearing_id == hearing_id)
    return session.scalar(query)


def mark_hearing_pack_reviewed(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    pack_id: str,
) -> HearingPack:
    matter = _load_matter(session, context, matter_id)
    pack = session.scalar(
        select(HearingPack)
        .where(HearingPack.id == pack_id, HearingPack.matter_id == matter.id)
        .options(selectinload(HearingPack.items))
    )
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hearing pack not found."
        )
    pack.status = HearingPackStatus.REVIEWED
    pack.review_required = False
    pack.reviewed_at = datetime.now(UTC)
    pack.reviewed_by_membership_id = context.membership.id
    session.flush()
    record_from_context(
        session,
        context,
        action="hearing_pack.reviewed",
        target_type="hearing_pack",
        target_id=pack.id,
        matter_id=matter.id,
    )
    session.commit()
    session.refresh(pack)
    return pack
