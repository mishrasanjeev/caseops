"""Sourced patent priority versions extend the canonical IP relationship owner."""

from __future__ import annotations

from collections import deque
from datetime import UTC, date
from hmac import compare_digest

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from caseops_api.db.models import (
    IpDocketRecord,
    IpPatentApplication,
    IpPatentPriorityDetail,
    IpRelationship,
)
from caseops_api.schemas.ip_patents import (
    PatentApplicationFacts,
    PatentApplicationRecord,
    PatentDocumentSource,
    PatentFamilyGraphResponse,
    PatentPriorityCreateRequest,
    PatentPriorityListResponse,
    PatentPriorityRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.idempotency import (
    IdempotencyClaimOutcome,
    canonical_json_sha256,
    claim_idempotency,
    complete_idempotency,
)
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.ip_patent_applications import (
    _application,
    _checked_source_ids,
    _lock_application_identity_writer,
    _normalized,
    _source_columns,
    _source_key,
    get_patent_application,
    list_patent_applications,
)
from caseops_api.services.ip_patent_applications import (
    _records as application_records,
)
from caseops_api.services.ip_patent_families import (
    _error,
    _link_disclosure_source,
    _lock_sources_and_dockets,
    get_patent_family,
)
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

MAX_ANCESTORS = 1000
MAX_ANCESTRY_ROWS = 2000
MAX_ANCESTRY_QUERIES = 32
ANCESTRY_BATCH_SIZE = 100
MAX_CORRECTION_RELATIONSHIPS = 2000
RELATION_KINDS = {"priority", "divisional_parent", "addition_parent", "national_phase_parent"}


def _sequence(session: Session, context: SessionContext, docket_id: str | None = None) -> int:
    statement = select(IpPatentPriorityDetail.sequence).where(
        IpPatentPriorityDetail.company_id == context.company.id
    )
    if docket_id:
        statement = statement.where(IpPatentPriorityDetail.source_docket_id == docket_id)
    return session.scalar(statement.order_by(IpPatentPriorityDetail.sequence.desc()).limit(1)) or 0


def _rows(context: SessionContext, sequence: int):
    successor = aliased(IpPatentPriorityDetail)
    replaced = (
        select(successor.id)
        .where(
            successor.company_id == IpPatentPriorityDetail.company_id,
            successor.supersedes_priority_id == IpPatentPriorityDetail.id,
            successor.sequence <= sequence,
        )
        .correlate(IpPatentPriorityDetail)
        .exists()
    )
    statement = (
        select(IpPatentPriorityDetail, IpRelationship, replaced)
        .join(
            IpRelationship,
            (IpRelationship.id == IpPatentPriorityDetail.relationship_id)
            & (IpRelationship.company_id == IpPatentPriorityDetail.company_id)
            & (IpRelationship.source_docket_id == IpPatentPriorityDetail.source_docket_id)
            & (IpRelationship.target_docket_id == IpPatentPriorityDetail.target_docket_id),
        )
        .where(
            IpPatentPriorityDetail.company_id == context.company.id,
            IpPatentPriorityDetail.sequence <= sequence,
        )
    )
    return statement, replaced


def _visible_docket_ids(session: Session, context: SessionContext):
    return select(IpDocketRecord.id).where(
        IpDocketRecord.company_id == context.company.id,
        IpDocketRecord.record_type == "patent_application",
        IpDocketRecord.restricted,
        ~IpDocketRecord.archived_by_matter_disposal,
        visible_ip_dockets_filter(session, context=context),
    )


def _applications(
    session: Session, context: SessionContext, docket_ids: set[str]
) -> dict[str, PatentApplicationRecord]:
    if len(docket_ids) > 2 * MAX_CORRECTION_RELATIONSHIPS:
        raise _error("patent_priority_scope_limit", "The linked application set exceeds its bound.")
    if not docket_ids:
        return {}
    dockets = {
        row.id: row
        for row in session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_(docket_ids),
                IpDocketRecord.id.in_(_visible_docket_ids(session, context)),
            )
        )
    }
    applications = list(
        session.scalars(
            select(IpPatentApplication)
            .where(
                IpPatentApplication.company_id == context.company.id,
                IpPatentApplication.docket_id.in_(dockets),
            )
            .order_by(IpPatentApplication.id)
        )
    )
    if set(dockets) != docket_ids or len(applications) != len(docket_ids):
        raise _error(
            "patent_priority_target_unavailable", "A linked application is unavailable.", 404
        )
    result = {}
    for offset in range(0, len(applications), 100):
        for record in application_records(
            session, context, applications[offset : offset + 100], dockets
        ):
            result[str(record.docket_id)] = record
    if set(result) != docket_ids:
        raise _error(
            "patent_priority_target_unavailable",
            "A linked application or its source is unavailable.",
            404,
        )
    return result


def _fact(
    parent_id: str,
    kind: str,
    priority_date: date,
    source: PatentDocumentSource,
    withdrawn: bool,
    review_flags,
):
    return {
        "parent_application_id": parent_id,
        "relation_kind": kind,
        "priority_date": priority_date.isoformat(),
        "source": source.model_dump(mode="json"),
        "withdrawn": withdrawn,
        "review_flags": list(review_flags),
    }


def _records(
    session: Session, context: SessionContext, rows, *, applications=None
) -> list[PatentPriorityRecord]:
    if len(rows) > 500:
        raise _error("patent_priority_page_limit", "A relationship page contains at most 500 rows.")
    applications = (
        applications
        if applications is not None
        else _applications(
            session,
            context,
            {
                docket_id
                for detail, _, _ in rows
                for docket_id in (detail.source_docket_id, detail.target_docket_id)
            },
        )
    )
    sources = [
        PatentDocumentSource(
            document_id=detail.source_document_id,
            document_version_id=detail.source_document_version_id,
            content_sha256=detail.source_sha256,
        )
        for detail, _, _ in rows
    ]
    available = _checked_source_ids(session, context, sources)
    if any(_source_key(pin) not in available for pin in sources):
        raise _error(
            "patent_priority_source_unavailable",
            "A retained relationship source is unavailable.",
            404,
        )
    result = []
    for (detail, relation, replaced), source in zip(rows, sources, strict=True):
        child = applications[detail.source_docket_id]
        parent = applications[detail.target_docket_id]
        fact = _fact(
            str(parent.id),
            relation.relationship_kind,
            relation.effective_from,
            source,
            detail.withdrawn,
            detail.review_flags_json,
        )
        if (
            relation.relationship_kind not in RELATION_KINDS
            or relation.source != "patent_priority"
            or relation.effective_until is not None
            or not compare_digest(detail.fact_sha256, canonical_json_sha256(fact))
        ):
            raise _error(
                "patent_priority_integrity", "The retained relationship requires reconciliation."
            )
        result.append(
            PatentPriorityRecord(
                id=detail.id,
                canonical_relationship_id=relation.id,
                application_id=child.id,
                parent_application_id=parent.id,
                current_application_title=child.facts.title,
                current_parent_title=parent.facts.title,
                sequence=detail.sequence,
                application_version=detail.application_version,
                parent_version=detail.parent_version,
                lifecycle_version=detail.lifecycle_version,
                parent_lifecycle_version=detail.parent_lifecycle_version,
                supersedes_priority_id=detail.supersedes_priority_id,
                withdrawn=detail.withdrawn,
                is_current=not replaced and not detail.withdrawn,
                review_flags=detail.review_flags_json,
                relation_kind=relation.relationship_kind,
                priority_date=relation.effective_from,
                source=source,
                reason=detail.reason,
                created_at=detail.created_at
                if detail.created_at.tzinfo
                else detail.created_at.replace(tzinfo=UTC),
            )
        )
    return result


def get_patent_priority(
    session: Session, *, context: SessionContext, application_id: str, priority_id: str
) -> PatentPriorityRecord:
    application = get_patent_application(session, context=context, application_id=application_id)
    statement, _ = _rows(context, _sequence(session, context))
    rows = session.execute(
        statement.where(
            IpPatentPriorityDetail.source_docket_id == str(application.docket_id),
            IpPatentPriorityDetail.id == priority_id,
        )
    ).all()
    if not rows:
        raise _error("patent_priority_not_found", "Recorded relationship not found.", 404)
    return _records(session, context, rows)[0]


def list_patent_priorities(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    limit: int = 25,
    cursor: int | None = None,
    snapshot_sequence: int | None = None,
    history: bool = False,
) -> PatentPriorityListResponse:
    if not 1 <= limit <= 100 or (cursor is not None and cursor < 1):
        raise _error("patent_priority_page_invalid", "Select a valid relationship page.", 422)
    if cursor is not None and snapshot_sequence is None:
        raise _error(
            "patent_priority_snapshot_required", "Reload the first relationship page.", 422
        )
    application = get_patent_application(session, context=context, application_id=application_id)
    sequence = _sequence(session, context, str(application.docket_id))
    if snapshot_sequence is not None and snapshot_sequence != sequence:
        raise _error("patent_priorities_stale", "Relationships changed. Reload the first page.")
    statement, replaced = _rows(context, sequence)
    statement = statement.where(
        IpPatentPriorityDetail.source_docket_id == str(application.docket_id)
    )
    if not history:
        statement = statement.where(~replaced, ~IpPatentPriorityDetail.withdrawn)
    if cursor is not None:
        statement = statement.where(IpPatentPriorityDetail.sequence < cursor)
    rows = session.execute(
        statement.order_by(IpPatentPriorityDetail.sequence.desc()).limit(limit + 1)
    ).all()
    return PatentPriorityListResponse(
        application_id=application.id,
        collection_sequence=sequence,
        priorities=_records(session, context, rows[:limit]),
        next_cursor=rows[limit - 1][0].sequence if len(rows) > limit else None,
    )


def _validate_facts(
    child: PatentApplicationFacts, parent: PatentApplicationFacts, kind: str, priority_date: date
) -> None:
    child_kind = {
        "divisional_parent": "divisional",
        "addition_parent": "patent_of_addition",
        "national_phase_parent": "national_phase",
    }.get(kind)
    if child_kind is not None and child.application_kind != child_kind:
        raise _error(
            "patent_priority_kind_conflict",
            "The relationship conflicts with the recorded application kind.",
            422,
        )
    if kind == "national_phase_parent" and parent.application_kind != "pct_international":
        raise _error(
            "patent_priority_kind_conflict",
            "A national-phase parent must be recorded as a PCT international application.",
            422,
        )
    if child.filing_date is not None and (
        priority_date > child.filing_date
        or (parent.filing_date is not None and parent.filing_date > child.filing_date)
    ):
        raise _error(
            "patent_priority_chronology",
            "The recorded priority or parent filing date follows the child filing date.",
            422,
        )


def _review_flags(
    child: PatentApplicationFacts, parent: PatentApplicationFacts, kind: str, priority_date: date
) -> list[str]:
    flags = []
    if kind in {"divisional_parent", "addition_parent"}:
        if child.jurisdiction != parent.jurisdiction:
            flags.append("jurisdictions_differ")
        if _normalized(child.office, 320) != _normalized(parent.office, 320):
            flags.append("office_names_differ")
    if child.filing_date is None or parent.filing_date is None:
        flags.append("filing_dates_incomplete")
    if parent.filing_date is not None and priority_date < parent.filing_date:
        flags.append("priority_date_precedes_parent_filing")
    return flags


def _reject_cycle(
    session: Session,
    context: SessionContext,
    child_docket_id: str,
    parent_docket_id: str,
    supersedes_priority_id: str | None,
) -> None:
    if child_docket_id == parent_docket_id:
        raise _error("patent_priority_self_link", "An application cannot link to itself.", 422)
    statement, replaced = _rows(context, _sequence(session, context))
    statement = statement.with_only_columns(
        IpPatentPriorityDetail.target_docket_id,
        IpPatentPriorityDetail.withdrawn,
        replaced,
    )
    if supersedes_priority_id:
        statement = statement.where(IpPatentPriorityDetail.id != supersedes_priority_id)
    pending = deque([parent_docket_id])
    visited = {parent_docket_id}
    remaining_rows = MAX_ANCESTRY_ROWS
    queries = 0
    while pending:
        if queries >= MAX_ANCESTRY_QUERIES:
            raise _error(
                "patent_priority_graph_bound",
                "The relationship exceeds the safe ancestry validation bound.",
            )
        batch = [pending.popleft() for _ in range(min(len(pending), ANCESTRY_BATCH_SIZE))]
        # Charge retained versions before filtering current edges. A recursive
        # DISTINCT/node limit does not bound dense edges or superseded history.
        rows = session.execute(
            statement.where(
                IpPatentPriorityDetail.source_docket_id.in_(batch),
            ).limit(remaining_rows + 1)
        ).all()
        queries += 1
        if len(rows) > remaining_rows:
            raise _error(
                "patent_priority_graph_bound",
                "The relationship exceeds the safe ancestry validation bound.",
            )
        remaining_rows -= len(rows)
        for parent_id, withdrawn, is_replaced in rows:
            if withdrawn or is_replaced:
                continue
            if parent_id == child_docket_id:
                raise _error(
                    "patent_priority_cycle", "This relationship would create a cycle.", 422
                )
            if parent_id not in visited:
                visited.add(parent_id)
                if len(visited) > MAX_ANCESTORS:
                    raise _error(
                        "patent_priority_graph_bound",
                        "The relationship exceeds the safe ancestry validation bound.",
                    )
                pending.append(parent_id)


def create_patent_priority(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    payload: PatentPriorityCreateRequest,
    idempotency_key: str,
) -> PatentPriorityRecord:
    _lock_application_identity_writer(session, context)
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    claim = claim_idempotency(
        session,
        company_id=context.company.id,
        actor_scope=f"membership:{context.membership.id}",
        actor_membership_id=context.membership.id,
        http_method="POST",
        operation="ip.patent.priority.create",
        idempotency_key=idempotency_key,
        request_hash=canonical_json_sha256(
            {"application_id": application_id, **payload.model_dump(mode="json")}
        ),
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        if claim.record.result_type != "ip_patent_priority" or not claim.record.result_id:
            raise _error(
                "patent_priority_replay_integrity", "The saved relationship cannot be resolved."
            )
        return get_patent_priority(
            session,
            context=context,
            application_id=application_id,
            priority_id=claim.record.result_id,
        )
    if claim.outcome != IdempotencyClaimOutcome.CLAIMED:
        raise _error("patent_priority_idempotency_conflict", "This command key is already in use.")
    child_row = _application(session, context, application_id)
    parent_row = _application(session, context, str(payload.parent_application_id))
    source_columns = _source_columns(payload.source)
    predecessor = None
    old_relation = None
    statement, replaced = _rows(context, _sequence(session, context))
    if payload.supersedes_priority_id is not None:
        previous = session.execute(
            statement.where(
                IpPatentPriorityDetail.id == str(payload.supersedes_priority_id),
                IpPatentPriorityDetail.source_docket_id == child_row.docket_id,
                ~replaced,
            )
        ).first()
        if previous is None:
            raise _error(
                "patent_priority_predecessor_unavailable",
                "Reload the current relationship before replacing it.",
            )
        predecessor, old_relation, _ = previous
        _records(session, context, [previous])
        if predecessor.withdrawn:
            raise _error(
                "patent_priority_already_withdrawn",
                "This record is withdrawn. Record a new sourced relationship instead.",
            )
    same_relationship = old_relation is not None and (
        old_relation.target_docket_id == parent_row.docket_id
        and old_relation.relationship_kind == payload.relation_kind
        and old_relation.effective_from == payload.priority_date
    )
    if payload.withdrawn and not same_relationship:
        raise _error(
            "patent_priority_withdrawal_changed",
            "A withdrawal must retain the original parent, kind and date.",
            422,
        )
    targets = {child_row.docket_id}
    references = frozenset({parent_row.docket_id}) if same_relationship else frozenset()
    if not same_relationship:
        targets.add(parent_row.docket_id)
    dockets = _lock_sources_and_dockets(
        session,
        context,
        [payload.source],
        targets,
        read_only_reference_docket_ids=references,
    )
    child_docket, parent_docket = dockets[child_row.docket_id], dockets[parent_row.docket_id]
    if (
        child_docket.current_version != payload.expected_application_version
        or parent_docket.current_version != payload.expected_parent_version
        or child_docket.lifecycle_version != payload.expected_lifecycle_version
        or parent_docket.lifecycle_version != payload.expected_parent_lifecycle_version
        or _sequence(session, context, child_row.docket_id) != payload.expected_priority_sequence
    ):
        raise _error(
            "patent_priorities_stale",
            "The application, parent or relationships changed. Reload before saving.",
        )
    current = _applications(session, context, {child_row.docket_id, parent_row.docket_id})
    child, parent = current[child_row.docket_id], current[parent_row.docket_id]
    if not payload.withdrawn:
        _validate_facts(child.facts, parent.facts, payload.relation_kind, payload.priority_date)
        _reject_cycle(
            session,
            context,
            child_row.docket_id,
            parent_row.docket_id,
            str(payload.supersedes_priority_id) if payload.supersedes_priority_id else None,
        )
    relationship = session.scalar(
        select(IpRelationship).where(
            IpRelationship.company_id == context.company.id,
            IpRelationship.source_docket_id == child_row.docket_id,
            IpRelationship.target_docket_id == parent_row.docket_id,
            IpRelationship.relationship_kind == payload.relation_kind,
            IpRelationship.effective_from == payload.priority_date,
        )
    )
    if relationship is not None:
        if relationship.source != "patent_priority" or relationship.effective_until is not None:
            raise _error(
                "patent_priority_integrity", "The existing relationship requires reconciliation."
            )
        active, superseded = _rows(context, _sequence(session, context))
        active = active.where(
            IpPatentPriorityDetail.relationship_id == relationship.id,
            ~superseded,
            ~IpPatentPriorityDetail.withdrawn,
        )
        if predecessor is not None:
            active = active.where(IpPatentPriorityDetail.id != predecessor.id)
        if session.execute(active.limit(1)).first() is not None:
            raise _error(
                "patent_priority_exists",
                "This relationship is already recorded. Open its current evidence.",
            )
    else:
        relationship = IpRelationship(
            company_id=context.company.id,
            source_docket_id=child_row.docket_id,
            target_docket_id=parent_row.docket_id,
            relationship_kind=payload.relation_kind,
            effective_from=payload.priority_date,
            source="patent_priority",
        )
        session.add(relationship)
        session.flush()
    flags = _review_flags(child.facts, parent.facts, payload.relation_kind, payload.priority_date)
    detail = IpPatentPriorityDetail(
        company_id=context.company.id,
        relationship_id=relationship.id,
        source_docket_id=child_row.docket_id,
        target_docket_id=parent_row.docket_id,
        sequence=_sequence(session, context) + 1,
        application_version=child.version,
        parent_version=parent.version,
        lifecycle_version=child.lifecycle_version,
        parent_lifecycle_version=parent.lifecycle_version,
        supersedes_priority_id=predecessor.id if predecessor is not None else None,
        withdrawn=payload.withdrawn,
        review_flags_json=flags,
        **source_columns,
        fact_sha256=canonical_json_sha256(
            _fact(
                str(parent.id),
                payload.relation_kind,
                payload.priority_date,
                payload.source,
                payload.withdrawn,
                flags,
            )
        ),
        created_by_membership_id=context.membership.id,
        reason=payload.reason,
    )
    session.add(detail)
    session.flush()
    _link_disclosure_source(session, context, child_docket, payload.source)
    record_from_context(
        session,
        context,
        action="ip_patent_priority.recorded",
        target_type="ip_patent_priority",
        target_id=detail.id,
        ip_docket_id=child_row.docket_id,
        metadata={
            "relationship_id": relationship.id,
            "sequence": detail.sequence,
            "supersedes_priority_id": detail.supersedes_priority_id,
            "withdrawn": detail.withdrawn,
            "review_flags": flags,
            "reason": payload.reason,
        },
    )
    complete_idempotency(
        session,
        company_id=context.company.id,
        record_id=claim.record.id,
        claim_token=claim.claim_token,
        claim_generation=claim.claim_generation,
        response_status=201,
        result_type="ip_patent_priority",
        result_id=detail.id,
    )
    result = get_patent_priority(
        session, context=context, application_id=application_id, priority_id=detail.id
    )
    session.commit()
    return result


def validate_application_priority_correction(
    session: Session,
    *,
    context: SessionContext,
    application: IpPatentApplication,
    facts: PatentApplicationFacts,
) -> None:
    # The caller owns the application identity fence, so linked fact versions
    # cannot change while the correction is checked. Counterparts are read-only.
    statement, replaced = _rows(context, _sequence(session, context))
    rows = session.execute(
        statement.where(
            or_(
                IpPatentPriorityDetail.source_docket_id == application.docket_id,
                IpPatentPriorityDetail.target_docket_id == application.docket_id,
            ),
            ~replaced,
            ~IpPatentPriorityDetail.withdrawn,
        ).limit(MAX_CORRECTION_RELATIONSHIPS + 1)
    ).all()
    if len(rows) > MAX_CORRECTION_RELATIONSHIPS:
        raise _error(
            "patent_priority_correction_bound",
            "This correction exceeds the safe relationship validation bound.",
        )
    related = _applications(
        session,
        context,
        {
            docket_id
            for detail, _, _ in rows
            for docket_id in (detail.source_docket_id, detail.target_docket_id)
        },
    )
    for offset in range(0, len(rows), 500):
        _records(session, context, rows[offset : offset + 500], applications=related)
    for detail, relation, _ in rows:
        child = (
            facts
            if detail.source_docket_id == application.docket_id
            else related[detail.source_docket_id].facts
        )
        parent = (
            facts
            if detail.target_docket_id == application.docket_id
            else related[detail.target_docket_id].facts
        )
        _validate_facts(child, parent, relation.relationship_kind, relation.effective_from)


def get_patent_family_graph(
    session: Session,
    *,
    context: SessionContext,
    family_id: str,
    application_limit: int = 50,
    priority_limit: int = 100,
    applications_cursor: str | None = None,
    priorities_cursor: str | None = None,
) -> PatentFamilyGraphResponse:
    if not 1 <= priority_limit <= 500:
        raise _error(
            "patent_priority_page_invalid", "Select a relationship page size from 1 to 500.", 422
        )
    get_patent_family(session, context=context, family_id=family_id)
    sequence = _sequence(session, context)
    cursor = None
    if priorities_cursor is not None:
        parts = priorities_cursor.split(":")
        if len(parts) != 2 or any(
            not part.isascii() or not part.isdecimal() or len(part) > 10 for part in parts
        ):
            raise _error("patent_priority_cursor_invalid", "Reload the family graph.", 422)
        snapshot, cursor = map(int, parts)
        if cursor < 1 or snapshot < cursor:
            raise _error("patent_priority_cursor_invalid", "Reload the family graph.", 422)
        if snapshot != sequence:
            raise _error(
                "patent_priorities_stale", "Relationships changed. Reload the family graph."
            )
    applications = list_patent_applications(
        session,
        context=context,
        family_id=family_id,
        limit=application_limit,
        cursor=applications_cursor,
        status_scope="all",
    )
    family_dockets = select(IpPatentApplication.docket_id).where(
        IpPatentApplication.company_id == context.company.id,
        IpPatentApplication.family_id == family_id,
    )
    visible = _visible_docket_ids(session, context)
    statement, replaced = _rows(context, sequence)
    statement = statement.where(
        ~replaced,
        ~IpPatentPriorityDetail.withdrawn,
        or_(
            IpPatentPriorityDetail.source_docket_id.in_(family_dockets),
            IpPatentPriorityDetail.target_docket_id.in_(family_dockets),
        ),
        IpPatentPriorityDetail.source_docket_id.in_(visible),
        IpPatentPriorityDetail.target_docket_id.in_(visible),
    )
    if cursor is not None:
        statement = statement.where(IpPatentPriorityDetail.sequence < cursor)
    rows = session.execute(
        statement.order_by(IpPatentPriorityDetail.sequence.desc()).limit(priority_limit + 1)
    ).all()
    next_cursor = (
        f"{sequence}:{rows[priority_limit - 1][0].sequence}" if len(rows) > priority_limit else None
    )
    return PatentFamilyGraphResponse(
        family_id=family_id,
        applications=applications.applications,
        priorities=_records(session, context, rows[:priority_limit]),
        applications_next_cursor=applications.next_cursor,
        priorities_next_cursor=next_cursor,
        has_more_applications=applications.next_cursor is not None,
        has_more_relationships=next_cursor is not None,
    )
