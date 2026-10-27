"""Typed packed-page reads; canonical parent authorization/serializers stay outside."""

from datetime import date, datetime
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import Integer, case, column, exists, func, select, true, union_all, values

from caseops_api.db.counsel_page_models import (
    CounselReadPage,
    CounselReadPageDirty,
)

CAPACITY = 25
KINDS = {
    "matter_outside_counsel_assignments": "assignment",
    "outside_counsel_spend_records": "spend",
}


def _committed_page_statement(model, *, company_id, matter_id, after, limit):
    """Only two physical25slot leaves; never hydrate a hidden source relation."""
    if model.__tablename__ not in KINDS or type(limit) is not int or not 1 <= limit <= CAPACITY:
        raise ValueError("Unsupported counsel page read.")
    page = CounselReadPage.__table__
    kind = KINDS[model.__tablename__]
    candidate = (
        select(page)
        .where(
            page.c.company_id == company_id,
            page.c.matter_id == matter_id,
            page.c.record_kind == kind,
        )
        .order_by(page.c.max_id)
        .limit(2)
    )
    if after is not None:
        candidate = candidate.where(page.c.max_id > after)
    candidate = candidate.cte("counsel_candidate_pages").prefix_with(
        "MATERIALIZED", dialect="postgresql"
    )
    slots = values(column("slot", Integer), name="counsel_slots").data(
        [(n,) for n in range(CAPACITY)]
    )
    entry = candidate.c.payload[slots.c.slot]
    source_id = entry["id"].as_string()
    note = case(*[(slots.c.slot == n, candidate.c[f"note_{n:02}"]) for n in range(CAPACITY)])
    source = (
        select(entry.label("source_payload"), note.label("source_note"))
        .select_from(candidate.join(slots, true()))
        .where(
            candidate.c.company_id == company_id,
            candidate.c.matter_id == matter_id,
            candidate.c.record_kind == kind,
            slots.c.slot < candidate.c.record_count,
            entry.is_not(None),
            source_id.is_not(None),
            entry["company_id"].as_string() == company_id,
            entry["matter_id"].as_string() == matter_id,
        )
        .order_by(source_id)
        .limit(limit + 1)
    )
    if after is not None:
        source = source.where(source_id > after)
    # Names are now in the same atomic packed payload. The former directory
    # join no longer needs a second materialized source/re-sort boundary.
    # Keep the candidate-page barrier, exact slot/tenant filters and page limit.
    return source.add_columns(entry["actor_name"].as_string().label("actor_name"))


def counsel_page_statement(model, *, company_id, matter_id, after, limit):
    """Packed committed reads, with execution-time canonical own-write fallback.

    The same retained Select checks this transaction's dirty rows on every
    execution. No read acquires projection locks or flushes deferred triggers.
    Statement-local parent/tenant admission remains the caller's authority.
    """
    if model.__tablename__ not in KINDS or type(limit) is not int or not 1 <= limit <= CAPACITY:
        raise ValueError("Unsupported counsel page read.")
    # Import only after models has registered all source and projection tables.
    from caseops_api.db.models import CompanyMembership, OutsideCounsel, User

    source = model.__table__
    counsel = OutsideCounsel.__table__
    member = CompanyMembership.__table__
    user = User.__table__
    note_field = "internal_notes" if KINDS[model.__tablename__] == "assignment" else "notes"
    actor_field = (
        "assigned_by_membership_id"
        if note_field == "internal_notes"
        else "recorded_by_membership_id"
    )
    parts = []
    for name in source.columns.keys():
        if name != note_field:
            parts.extend((name, source.c[name]))
    parts.extend(
        (
            "counsel_name",
            counsel.c.name,
            "actor_user_id",
            member.c.user_id,
            "actor_name",
            user.c.full_name,
        )
    )
    dirty = exists(
        select(CounselReadPageDirty.transaction_id).where(
            CounselReadPageDirty.transaction_id == func.txid_current_if_assigned()
        )
    )
    logical = (
        select(
            func.jsonb_build_object(*parts).label("source_payload"),
            source.c[note_field].label("source_note"),
            user.c.full_name.label("actor_name"),
        )
        .select_from(
            source.join(
                counsel,
                (counsel.c.id == source.c.counsel_id)
                & (counsel.c.company_id == source.c.company_id),
            )
            .outerjoin(
                member,
                (member.c.id == source.c[actor_field])
                & (member.c.company_id == source.c.company_id),
            )
            .outerjoin(user, user.c.id == member.c.user_id)
        )
        .where(
            dirty,
            source.c.company_id == company_id,
            source.c.matter_id == matter_id,
            counsel.c.company_id == company_id,
        )
        .order_by(source.c.id)
        .limit(limit + 1)
    )
    if after is not None:
        logical = logical.where(source.c.id > after)
    canonical = logical.subquery("counsel_own_write_rows")
    committed = _committed_page_statement(
        model, company_id=company_id, matter_id=matter_id, after=after, limit=limit
    ).subquery("counsel_committed_rows")
    current = union_all(
        select(committed.c.source_payload, committed.c.source_note, committed.c.actor_name).where(
            ~dirty
        ),
        select(canonical.c.source_payload, canonical.c.source_note, canonical.c.actor_name),
    ).subquery("counsel_current_transaction_rows")
    return select(*current.c).order_by(current.c.source_payload["id"].as_string()).limit(limit + 1)


def source_row_from_page(model, payload, note, actor_name, *, company_id, matter_id):
    """A pure serializer input, never attached to the ORM or used as authority."""
    try:
        fields = dict(payload)
        note_field = (
            "internal_notes"
            if model.__tablename__ == "matter_outside_counsel_assignments"
            else "notes"
        )
        expected = (set(model.__table__.columns.keys()) - {note_field}) | {
            "counsel_name",
            "actor_user_id",
            "actor_name",
        }
        if set(fields) != expected or (note is not None and not isinstance(note, str)):
            raise ValueError("shape")
        if fields["company_id"] != company_id or fields["matter_id"] != matter_id:
            raise ValueError("scope")
        counsel_name = fields.pop("counsel_name")
        actor_id = fields.pop("actor_user_id")
        retained_actor_name = fields.pop("actor_name")
        if (
            (actor_id is None and actor_name is not None)
            or (actor_id is not None and not isinstance(actor_id, str))
            or retained_actor_name != actor_name
        ):
            raise ValueError("actor scope")
        if not isinstance(counsel_name, str) or not isinstance(fields["id"], str):
            raise ValueError("identity")
        if actor_name is not None and not isinstance(actor_name, str):
            raise ValueError("actor")
        for key in ("created_at", "updated_at"):
            fields[key] = datetime.fromisoformat(fields[key])
        if model.__tablename__ == "matter_outside_counsel_assignments":
            fields["internal_notes"] = note
        elif model.__tablename__ == "outside_counsel_spend_records":
            fields["notes"] = note
            for key in ("billed_on", "due_on", "paid_on"):
                fields[key] = date.fromisoformat(fields[key]) if fields[key] is not None else None
        else:
            raise ValueError("kind")
        return SimpleNamespace(**fields, counsel=SimpleNamespace(name=counsel_name)), actor_name
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(503, detail="Counsel read projection is unavailable.") from error
