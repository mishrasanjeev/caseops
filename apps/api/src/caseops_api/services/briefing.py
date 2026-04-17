from __future__ import annotations

from datetime import UTC, datetime

from caseops_api.schemas.ai import MatterBriefGenerateRequest, MatterBriefResponse
from caseops_api.services.authorities import (
    search_authority_catalog,
    summarize_authority_relationships,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.matters import _get_matter_model, get_matter_workspace
from caseops_api.services.retrieval import RetrievalCandidate, rank_candidates


def _format_currency_minor(amount_minor: int, currency: str = "INR") -> str:
    major = amount_minor / 100
    return f"{currency} {major:,.2f}"


def _preview(value: str, limit: int = 220) -> str:
    compact = " ".join(value.split())
    return compact[:limit]


def _build_brief_query(
    *,
    matter,
    payload: MatterBriefGenerateRequest,
    latest_order,
    latest_cause_list,
) -> str:
    parts = [
        payload.focus or "",
        matter.title,
        matter.matter_code,
        matter.practice_area,
        matter.client_name or "",
        matter.opposing_party or "",
        matter.court_name or "",
        matter.judge_name or "",
        latest_order.title if latest_order else "",
        latest_order.summary if latest_order else "",
        latest_cause_list.stage if latest_cause_list else "",
        latest_cause_list.bench_name if latest_cause_list else "",
    ]
    return " ".join(part for part in parts if part).strip()


def _brief_retrieval_candidates(matter_model) -> list[RetrievalCandidate]:
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
    for order in matter_model.court_orders:
        order_content = order.order_text or order.summary
        if not order_content:
            continue
        candidates.append(
            RetrievalCandidate(
                attachment_id=order.id,
                attachment_name=order.title,
                content=order_content,
            )
        )
    return candidates


def generate_matter_brief(
    session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterBriefGenerateRequest,
) -> MatterBriefResponse:
    workspace = get_matter_workspace(session, context=context, matter_id=matter_id)
    matter_model = _get_matter_model(session, context=context, matter_id=matter_id)
    matter = workspace.matter

    note_count = len(workspace.notes)
    hearing_count = len(workspace.hearings)
    attachment_count = len(workspace.attachments)
    invoice_count = len(workspace.invoices)
    cause_list_count = len(workspace.cause_list_entries)
    order_count = len(workspace.court_orders)
    total_open_fees_minor = sum(invoice.balance_due_minor for invoice in workspace.invoices)

    latest_hearing = workspace.hearings[0] if workspace.hearings else None
    latest_note = workspace.notes[0] if workspace.notes else None
    latest_invoice = workspace.invoices[0] if workspace.invoices else None
    latest_cause_list = workspace.cause_list_entries[0] if workspace.cause_list_entries else None
    latest_order = workspace.court_orders[0] if workspace.court_orders else None
    indexed_attachment_count = sum(
        1 for attachment in workspace.attachments if attachment.processing_status == "indexed"
    )
    pending_attachment_count = sum(
        1
        for attachment in workspace.attachments
        if attachment.processing_status in {"pending", "needs_ocr", "failed"}
    )

    court_posture: list[str] = []
    source_provenance: list[str] = []
    authority_highlights: list[str] = []
    authority_relationships: list[str] = []

    brief_query = _build_brief_query(
        matter=matter,
        payload=payload,
        latest_order=latest_order,
        latest_cause_list=latest_cause_list,
    )
    retrieval_results = rank_candidates(
        query=brief_query,
        candidates=_brief_retrieval_candidates(matter_model),
        limit=4,
    )
    authority_results = search_authority_catalog(
        session,
        query=brief_query,
        limit=3,
        forum_level=matter.forum_level,
        court_name=matter.court_name,
    )

    if latest_cause_list:
        bench_detail = (
            f" before {latest_cause_list.bench_name}"
            if latest_cause_list.bench_name
            else ""
        )
        item_detail = (
            f", item {latest_cause_list.item_number}"
            if latest_cause_list.item_number
            else ""
        )
        stage_detail = f", stage {latest_cause_list.stage}" if latest_cause_list.stage else ""
        court_posture.append(
            f"Latest listing is in {latest_cause_list.forum_name} on "
            f"{latest_cause_list.listing_date}{bench_detail}{item_detail}{stage_detail}."
        )
        source_provenance.append(
            f"Cause list source: {latest_cause_list.source} "
            f"({latest_cause_list.source_reference or 'official source reference unavailable'})."
        )
    elif matter.next_hearing_on:
        court_posture.append(f"Next recorded hearing date is {matter.next_hearing_on}.")

    if latest_order:
        order_detail = latest_order.order_text or latest_order.summary
        court_posture.append(
            f"Latest court order dated {latest_order.order_date} is {latest_order.title}: "
            f"{order_detail[:220]}"
        )
        source_provenance.append(
            f"Order source: {latest_order.source} "
            f"({latest_order.source_reference or 'official source reference unavailable'})."
        )

    if latest_hearing:
        court_posture.append(
            f"Latest internal hearing entry records {latest_hearing.hearing_on} for "
            f"{latest_hearing.purpose} at {latest_hearing.forum_name}."
        )

    if latest_note:
        source_provenance.append(
            f"Latest internal note by {latest_note.author_name}: {latest_note.body}"
        )

    source_provenance.append(
        f"Workspace documents: {indexed_attachment_count} indexed / "
        f"{pending_attachment_count} pending-or-needing-OCR out of {attachment_count}."
    )

    if latest_order:
        authority_highlights.append(
            f"{latest_order.title} ({latest_order.order_date}): "
            f"{_preview(latest_order.order_text or latest_order.summary)}"
        )

    seen_authority_names = {latest_order.title} if latest_order else set()
    for result in authority_results:
        seen_key = f"{result.court_name}:{result.title}"
        if seen_key in seen_authority_names:
            continue
        seen_authority_names.add(seen_key)
        matched_terms = (
            f" Matched terms: {', '.join(result.matched_terms[:4])}."
            if result.matched_terms
            else ""
        )
        authority_highlights.append(
            f"{result.title} [{result.court_name}, {result.decision_date}]: "
            f"{result.snippet}{matched_terms}"
        )
    if authority_results:
        source_provenance.append(
            "Authority corpus hits: "
            + "; ".join(
                f"{result.court_name} - {result.title}"
                for result in authority_results[:3]
            )
            + "."
        )
        authority_relationships = summarize_authority_relationships(
            session,
            authority_document_ids=[
                result.authority_document_id for result in authority_results
            ],
            limit=5,
        )
        if authority_relationships:
            source_provenance.append(
                f"Authority graph relationships identified: {len(authority_relationships)}."
            )
    for result in retrieval_results:
        if result.attachment_name in seen_authority_names:
            continue
        seen_authority_names.add(result.attachment_name)
        matched_terms = (
            f" Matched terms: {', '.join(result.matched_terms[:4])}."
            if result.matched_terms
            else ""
        )
        authority_highlights.append(
            f"{result.attachment_name}: {result.snippet}{matched_terms}"
        )
        if len(authority_highlights) >= 5:
            break

    if payload.brief_type == "hearing_prep":
        headline = f"Hearing prep for {matter.title}"
        summary = (
            f"{matter.title} is currently {matter.status.replace('_', ' ')} in "
            f"{matter.court_name or matter.forum_level.replace('_', ' ')}. "
            f"The workspace currently contains {note_count} notes, {attachment_count} documents, "
            f"{hearing_count} hearing entries, {cause_list_count} cause list item(s), "
            f"and {order_count} synced order(s). "
            f"{court_posture[0] if court_posture else 'No current court posture was inferred.'}"
        )
        recommended_actions = [
            (
                "Verify the latest order and convert every operative direction "
                "into a hearing checklist."
            ),
            (
                "Confirm the bench, forum, item number, and hearing purpose "
                "before circulating the brief."
            ),
            (
                "Review indexed documents and ensure the chronology, annexures, "
                "and compliance record are complete."
            ),
        ]
        upcoming_items = []
        if latest_cause_list:
            listing_bench_detail = (
                f" before {latest_cause_list.bench_name}"
                if latest_cause_list.bench_name
                else ""
            )
            listing_item_detail = (
                f", item {latest_cause_list.item_number}"
                if latest_cause_list.item_number
                else ""
            )
            upcoming_items.append(
                f"Cause list shows {latest_cause_list.forum_name} on "
                f"{latest_cause_list.listing_date}"
                f"{listing_bench_detail}{listing_item_detail}."
            )
        elif latest_hearing:
            upcoming_items.append(
                f"Upcoming hearing on {latest_hearing.hearing_on} at {latest_hearing.forum_name} "
                f"for {latest_hearing.purpose}."
            )
        elif matter.next_hearing_on:
            upcoming_items.append(
                f"Matter record shows next hearing on {matter.next_hearing_on}."
            )
        else:
            upcoming_items.append("No hearing date is currently recorded.")
        if latest_order:
            upcoming_items.append(
                f"Last operative order is dated {latest_order.order_date}: {latest_order.title}."
            )
    else:
        headline = f"Matter summary for {matter.title}"
        summary = (
            f"{matter.title} is a {matter.practice_area} matter tracked as "
            f"{matter.status.replace('_', ' ')}. The workspace currently holds "
            f"{attachment_count} documents, {note_count} notes, {hearing_count} hearings, "
            f"{cause_list_count} cause list item(s), {order_count} court order(s), "
            f"and {invoice_count} invoices. "
            f"{court_posture[0] if court_posture else 'No current court posture was inferred.'}"
        )
        recommended_actions = [
            "Keep the matter status, assignee, and next hearing date current.",
            (
                "Use the note stream to capture partner direction, operative court "
                "directions, and next steps."
            ),
            (
                "Review billing and fee collection against the current matter posture "
                "and client-update cadence."
            ),
            (
                "Tie each major update back to a verifiable court or workspace "
                "source before external circulation."
            ),
        ]
        upcoming_items = []
        if matter.next_hearing_on:
            upcoming_items.append(f"Next hearing recorded for {matter.next_hearing_on}.")
        if latest_invoice:
            invoice_balance = _format_currency_minor(
                latest_invoice.balance_due_minor,
                latest_invoice.currency,
            )
            upcoming_items.append(
                f"Latest invoice {latest_invoice.invoice_number} is {latest_invoice.status} "
                f"with balance due {invoice_balance}."
            )
        if latest_order:
            upcoming_items.append(
                f"Latest synced order dated {latest_order.order_date}: {latest_order.title}."
            )
        if not upcoming_items:
            upcoming_items.append("No immediate hearing or billing milestones are recorded yet.")

    key_points = [
        f"Client: {matter.client_name or 'Not set'}",
        f"Opposing party: {matter.opposing_party or 'Not set'}",
        f"Assignee: {workspace.assignee.full_name if workspace.assignee else 'Unassigned'}",
        f"Documents in workspace: {attachment_count}",
    ]
    if latest_note:
        key_points.append(f"Latest note: {latest_note.body}")
    if latest_hearing:
        key_points.append(
            f"Latest hearing entry: {latest_hearing.hearing_on} - {latest_hearing.purpose}"
        )
    if latest_order:
        key_points.append(f"Latest order: {latest_order.order_date} - {latest_order.title}")

    risks = []
    if not workspace.assignee:
        risks.append("No assignee is set for the matter.")
    if attachment_count == 0:
        risks.append("No source documents have been uploaded yet.")
    elif indexed_attachment_count == 0:
        risks.append("Documents exist, but none are fully indexed for reliable retrieval yet.")
    if note_count == 0:
        risks.append("No internal notes capture current strategy or open questions.")
    if (
        matter.status == "active"
        and not matter.next_hearing_on
        and payload.brief_type == "hearing_prep"
    ):
        risks.append("The matter is active, but no next hearing date is recorded.")
    if payload.brief_type == "hearing_prep" and order_count == 0:
        risks.append("No synced court order is available to anchor the hearing strategy.")
    if payload.brief_type == "hearing_prep" and cause_list_count == 0:
        risks.append("No synced cause list entry is available to confirm current listing posture.")
    if not authority_highlights:
        risks.append("No authority-grade source text was retrieved for the current brief.")
    if total_open_fees_minor > 0:
        risks.append(
            "Outstanding fee collection remains open at "
            f"{_format_currency_minor(total_open_fees_minor)}."
        )
    if not risks:
        risks.append(
            "No critical data-quality gaps were detected from the current workspace snapshot."
        )

    billing_snapshot = (
        f"{invoice_count} invoices tracked with total open balance "
        f"{_format_currency_minor(total_open_fees_minor)}."
    )

    if payload.focus:
        recommended_actions.insert(0, f"Focus requested: {payload.focus.strip()}.")

    return MatterBriefResponse(
        matter_id=matter.id,
        brief_type=payload.brief_type,
        provider="caseops-briefing-court-sync-v4",
        generated_at=datetime.now(UTC),
        headline=headline,
        summary=summary,
        authority_highlights=authority_highlights
        or ["No authority-grade highlights were retrieved yet."],
        authority_relationships=authority_relationships
        or ["No authority graph relationships were resolved yet."],
        court_posture=court_posture or ["No court posture signals are available yet."],
        key_points=key_points,
        risks=risks,
        recommended_actions=recommended_actions,
        upcoming_items=upcoming_items,
        source_provenance=source_provenance,
        billing_snapshot=billing_snapshot,
    )
