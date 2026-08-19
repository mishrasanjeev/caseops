"""Where a purge has to reach, and what it cannot reach by itself (DATA-GOV-09).

The requirement: "Purge and revocation propagate to current/old object
versions, temporary files, exports, search/vector/chunk rows, caches,
AI/session stores, queued work, analytics and provider-held data where
contractually supported; every subsystem reports completion or explicit
exception."

The last clause is the whole design. A subsystem a purge cannot reach must
produce an EXPLICIT EXCEPTION - a named item an operator has to discharge - not
silence. Silence is what makes a database purge look like a complete one while
object versions, caches and provider copies survive.

Three reachability classes, and the middle one is the interesting one:

    tenant_scoped   the table carries company_id; a purge can scope it directly
    via_parent      no company_id, reachable only by joining its owning record
    external        not in this database at all - object store, cache, provider

And two dispositions that are NOT the same thing:

    purge            tenant data, remove it
    preserve_global  shared corpus that merely LOOKS reachable

``authority_document_chunks`` is the case that matters for the second.  It has
no ``company_id`` and hangs off ``authority_documents``, so a naive
"purge every chunk row this tenant touched" would delete shared judgment corpus
for every other firm on the platform. It is preserved on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import Base

Reachability = Literal["tenant_scoped", "via_parent", "external"]
Disposition = Literal["purge", "preserve_global", "manual_exception"]


@dataclass(frozen=True)
class PropagationTarget:
    subsystem: str
    reachability: Reachability
    disposition: Disposition
    record_count: int | None
    detail: str


# (subsystem, table, detail) - verified to carry company_id.
_TENANT_SCOPED: tuple[tuple[str, str, str], ...] = (
    ("queued_work", "domain_outbox_events", "undelivered domain events"),
    ("notification_queue", "notification_delivery_intents", "pending delivery intents"),
    ("exports", "audit_export_jobs", "generated export artifacts and their jobs"),
    ("ai_stores", "model_runs", "recorded model runs and their metadata"),
    ("analytics", "billing_usage_events", "usage attribution rows"),
)
# Reachable only through the owning record, and it is TWO hops, not one: the
# chunk's immediate parent has no company_id either. Verified rather than
# assumed - a first version joined chunks straight to attachments and produced
# no scope at all. A purge that skipped these would leave searchable text
# behind after the document it came from is gone.
# (subsystem, child, parent, grandparent carrying company_id, detail)
_VIA_PARENT: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "matter_attachment_chunks",
        "matter_attachment_chunks",
        "matter_attachments",
        "matters",
        "chunked matter attachment text backing search",
    ),
    (
        "contract_attachment_chunks",
        "contract_attachment_chunks",
        "contract_attachments",
        "contracts",
        "chunked contract attachment text backing search",
    ),
)
# Not in this database. Each is an explicit exception an operator discharges.
_EXTERNAL: tuple[tuple[str, str], ...] = (
    (
        "object_versions",
        "current and non-current object versions in the storage bucket, including "
        "soft-deleted generations retained by lifecycle policy",
    ),
    (
        "temporary_files",
        "scratch files written during document processing outside the database",
    ),
    ("caches", "in-process and edge caches hold no tenant-scoped registry to sweep"),
    (
        "provider_held_data",
        "copies retained by LLM, embedding and mail providers, removable only "
        "where the contract supports deletion",
    ),
)


def _tenant_count(session: Session, table_name: str, company_id: str) -> int | None:
    table = Base.metadata.tables.get(table_name)
    if table is None or "company_id" not in table.columns:
        return None
    return int(
        session.scalar(
            select(func.count()).select_from(table).where(table.c.company_id == company_id)
        )
        or 0
    )


def _join_column(child_table, parent_name: str):
    """The column on ``child_table`` whose foreign key points at ``parent_name``."""
    return next(
        (
            column
            for column in child_table.columns
            for foreign_key in column.foreign_keys
            if foreign_key.column.table.name == parent_name
        ),
        None,
    )


def _via_parent_count(
    session: Session,
    child_table: str,
    parent_table: str,
    grandparent_table: str,
    company_id: str,
) -> int | None:
    child = Base.metadata.tables.get(child_table)
    parent = Base.metadata.tables.get(parent_table)
    grandparent = Base.metadata.tables.get(grandparent_table)
    if child is None or parent is None or grandparent is None:
        return None
    if "company_id" not in grandparent.columns:
        return None
    to_parent = _join_column(child, parent_table)
    to_grandparent = _join_column(parent, grandparent_table)
    if to_parent is None or to_grandparent is None:
        return None
    statement = (
        select(func.count())
        .select_from(
            child.join(parent, to_parent == parent.c.id).join(
                grandparent, to_grandparent == grandparent.c.id
            )
        )
        .where(grandparent.c.company_id == company_id)
    )
    return int(session.scalar(statement) or 0)


def build_propagation_plan(
    session: Session, *, company_id: str
) -> tuple[PropagationTarget, ...]:
    """Every subsystem a purge must reach, with its reachability and disposition."""
    targets: list[PropagationTarget] = []

    for subsystem, table_name, detail in _TENANT_SCOPED:
        targets.append(
            PropagationTarget(
                subsystem=subsystem,
                reachability="tenant_scoped",
                disposition="purge",
                record_count=_tenant_count(session, table_name, company_id),
                detail=detail,
            )
        )

    for subsystem, child, parent, grandparent, detail in _VIA_PARENT:
        targets.append(
            PropagationTarget(
                subsystem=subsystem,
                reachability="via_parent",
                disposition="purge",
                record_count=_via_parent_count(
                    session, child, parent, grandparent, company_id
                ),
                detail=detail,
            )
        )

    # Shared corpus that looks reachable and must not be touched.
    targets.append(
        PropagationTarget(
            subsystem="authority_corpus_chunks",
            reachability="via_parent",
            disposition="preserve_global",
            record_count=None,
            detail=(
                "authority_document_chunks belong to the shared judgment corpus, "
                "not to any tenant; purging what a tenant merely searched would "
                "destroy corpus for every other firm"
            ),
        )
    )

    for subsystem, detail in _EXTERNAL:
        targets.append(
            PropagationTarget(
                subsystem=subsystem,
                reachability="external",
                disposition="manual_exception",
                record_count=None,
                detail=detail,
            )
        )
    return tuple(targets)


def unresolved_exceptions(targets: tuple[PropagationTarget, ...]) -> tuple[str, ...]:
    """Subsystems a purge cannot complete on its own.

    DATA-GOV-09 requires every subsystem to report completion OR an explicit
    exception. These are the exceptions, and an operator has to discharge each
    one before a purge can honestly be called complete.
    """
    return tuple(
        target.subsystem for target in targets if target.disposition == "manual_exception"
    )
