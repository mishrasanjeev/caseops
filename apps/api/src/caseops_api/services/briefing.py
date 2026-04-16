from __future__ import annotations

from datetime import UTC, datetime

from caseops_api.schemas.ai import MatterBriefGenerateRequest, MatterBriefResponse
from caseops_api.services.identity import SessionContext
from caseops_api.services.matters import get_matter_workspace


def _format_currency_minor(amount_minor: int, currency: str = "INR") -> str:
    major = amount_minor / 100
    return f"{currency} {major:,.2f}"


def generate_matter_brief(
    session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterBriefGenerateRequest,
) -> MatterBriefResponse:
    workspace = get_matter_workspace(session, context=context, matter_id=matter_id)
    matter = workspace.matter

    note_count = len(workspace.notes)
    hearing_count = len(workspace.hearings)
    attachment_count = len(workspace.attachments)
    invoice_count = len(workspace.invoices)
    total_open_fees_minor = sum(invoice.balance_due_minor for invoice in workspace.invoices)

    latest_hearing = workspace.hearings[0] if workspace.hearings else None
    latest_note = workspace.notes[0] if workspace.notes else None
    latest_invoice = workspace.invoices[0] if workspace.invoices else None

    if payload.brief_type == "hearing_prep":
        headline = f"Hearing prep for {matter.title}"
        summary = (
            f"{matter.title} is currently {matter.status.replace('_', ' ')} in "
            f"{matter.court_name or matter.forum_level.replace('_', ' ')}. "
            f"The workspace currently contains {note_count} notes, {attachment_count} documents, "
            f"and {hearing_count} hearing entries."
        )
        recommended_actions = [
            "Verify the latest note and convert it into a hearing checklist.",
            "Confirm the bench, forum, and hearing purpose before circulating the brief.",
            "Review uploaded documents and ensure the chronology and annexures are complete.",
        ]
        upcoming_items = []
        if latest_hearing:
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
    else:
        headline = f"Matter summary for {matter.title}"
        summary = (
            f"{matter.title} is a {matter.practice_area} matter tracked as "
            f"{matter.status.replace('_', ' ')}. The workspace currently holds "
            f"{attachment_count} documents, {note_count} notes, {hearing_count} hearings, "
            f"and {invoice_count} invoices."
        )
        recommended_actions = [
            "Keep the matter status, assignee, and next hearing date current.",
            "Use the note stream to capture partner direction and immediate next steps.",
            "Review billing and fee collection against the current matter posture.",
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

    risks = []
    if not workspace.assignee:
        risks.append("No assignee is set for the matter.")
    if attachment_count == 0:
        risks.append("No source documents have been uploaded yet.")
    if note_count == 0:
        risks.append("No internal notes capture current strategy or open questions.")
    if (
        matter.status == "active"
        and not matter.next_hearing_on
        and payload.brief_type == "hearing_prep"
    ):
        risks.append("The matter is active, but no next hearing date is recorded.")
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
        provider="caseops-heuristic-v1",
        generated_at=datetime.now(UTC),
        headline=headline,
        summary=summary,
        key_points=key_points,
        risks=risks,
        recommended_actions=recommended_actions,
        upcoming_items=upcoming_items,
        billing_snapshot=billing_snapshot,
    )
