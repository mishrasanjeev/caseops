"""Patent document and prosecution commands under canonical access/lifecycle locks."""

from datetime import UTC
from hmac import compare_digest
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDeadline,
    IpPatentApplication,
    IpPatentApplicationVersion,
    IpPatentEvidenceDocument,
    IpPatentEvidenceVersion,
    IpPatentProsecutionEvent,
)
from caseops_api.schemas.ip_patent_prosecution import (
    PatentEvidenceCreateRequest,
    PatentEvidencePage,
    PatentEvidenceRecord,
    PatentManifestItem,
    PatentProsecutionCreateRequest,
    PatentProsecutionPage,
    PatentProsecutionPreview,
    PatentProsecutionRecord,
)
from caseops_api.schemas.ip_patents import PatentDocumentSource
from caseops_api.services.audit import record_from_context
from caseops_api.services.idempotency import (
    IdempotencyClaimOutcome,
    canonical_json_sha256,
    claim_idempotency,
    complete_idempotency,
)
from caseops_api.services.ip_domain_catalog import assert_domain_operation
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.ip_patent_applications import (
    _application,
    _checked_source_ids,
    _source,
    _source_columns,
    _source_key,
    get_patent_application,
)
from caseops_api.services.ip_patent_families import (
    _error,
    _link_disclosure_source,
    _lock_sources_and_dockets,
    _source_version,
)
from caseops_api.services.session_context import SessionContext

EDITION_LIMIT = 1000
PHASES = {
    "filing_preparation": ("filing_preparation", {"disclosure"}),
    "filing": ("filed", {"disclosure", "filing_preparation"}),
    "publication": ("published", {"filed", "examination_requested"}),
    "examination_request": ("examination_requested", {"filed", "published"}),
    "office_action": (
        "examination",
        {"filed", "published", "examination_requested", "examination", "response_filed"},
    ),
    "response": ("response_filed", {"examination", "hearing"}),
    "hearing": ("hearing", {"examination", "response_filed", "hearing"}),
    "amendment": (
        None,
        {"filed", "published", "examination_requested", "examination", "response_filed", "hearing"},
    ),
    "grant": ("granted", {"examination", "response_filed", "hearing"}),
    "restoration": ("filing_preparation", set()),
}
PACKAGE_EVENTS = frozenset({"filing", "response", "amendment", "grant"})


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _manifest_digest(title, kind, source, documents):
    return canonical_json_sha256(
        {
            "schema": "caseops.patent-manifest/v1",
            "title": title,
            "document_kind": kind,
            "source": source.model_dump(mode="json"),
            "documents": [item.model_dump(mode="json") for item in documents],
        }
    )


def _assert_sources(session, context, sources):
    available = _checked_source_ids(session, context, sources)
    if any(_source_key(pin) not in available for pin in sources):
        raise _error(
            "patent_work_source_unavailable", "A retained source is no longer accessible.", 404
        )


def _evidence_records(session, context, rows):
    if len(rows) > 100:
        raise _error("patent_work_page_limit", "A work page contains at most 100 records.")
    if not rows:
        return []
    items = list(
        session.scalars(
            select(IpPatentEvidenceDocument)
            .where(
                IpPatentEvidenceDocument.company_id == context.company.id,
                IpPatentEvidenceDocument.evidence_id.in_([row.id for row in rows]),
            )
            .order_by(IpPatentEvidenceDocument.evidence_id, IpPatentEvidenceDocument.ordinal)
            .limit(2001)
        )
    )
    if len(items) > 2000:
        raise _error("patent_manifest_limit", "The retained manifest exceeds its bound.")
    grouped = {row.id: [] for row in rows}
    replaced = set(
        session.scalars(
            select(IpPatentEvidenceVersion.predecessor_id)
            .where(
                IpPatentEvidenceVersion.company_id == context.company.id,
                IpPatentEvidenceVersion.predecessor_id.in_(grouped),
            )
            .limit(101)
        )
    )
    for item in items:
        grouped[item.evidence_id].append(item)
    pins = [_source(row) for row in rows]
    pins.extend(
        PatentDocumentSource(
            document_id=item.document_id,
            document_version_id=item.document_version_id,
            content_sha256=item.content_sha256,
        )
        for item in items
    )
    _assert_sources(session, context, pins)
    results = []
    for row in rows:
        members = grouped[row.id]
        if not 1 <= len(members) == row.document_count <= 20 or [
            item.ordinal for item in members
        ] != list(range(len(members))):
            raise _error(
                "patent_manifest_integrity", "The retained manifest requires reconciliation."
            )
        documents = tuple(
            PatentManifestItem(
                document_kind=item.document_kind,
                source=PatentDocumentSource(
                    document_id=item.document_id,
                    document_version_id=item.document_version_id,
                    content_sha256=item.content_sha256,
                ),
            )
            for item in members
        )
        if not compare_digest(
            row.manifest_sha256,
            _manifest_digest(row.title, row.document_kind, _source(row), documents),
        ):
            raise _error("patent_manifest_integrity", "The retained manifest hash does not match.")
        results.append(
            PatentEvidenceRecord(
                id=row.id,
                application_id=row.application_id,
                root_id=row.root_id,
                predecessor_id=row.predecessor_id,
                sequence=row.sequence,
                edition=row.edition,
                is_current=row.id not in replaced,
                anchor_version=row.anchor_version,
                lifecycle_version=row.lifecycle_version,
                title=row.title,
                document_kind=row.document_kind,
                source=_source(row),
                documents=documents,
                manifest_sha256=row.manifest_sha256,
                reason=row.reason,
                created_at=_aware(row.created_at),
            )
        )
    return results


def get_patent_evidence(session, *, context, application_id, evidence_id):
    get_patent_application(session, context=context, application_id=application_id)
    row = session.scalar(
        select(IpPatentEvidenceVersion).where(
            IpPatentEvidenceVersion.company_id == context.company.id,
            IpPatentEvidenceVersion.application_id == application_id,
            IpPatentEvidenceVersion.id == evidence_id,
        )
    )
    if row is None:
        raise _error("patent_evidence_not_found", "Patent work product not found.", 404)
    return _evidence_records(session, context, [row])[0]


def _page(session, context, application_id, model, limit, cursor, snapshot_sequence):
    if not 1 <= limit <= 100 or (cursor is not None and (cursor < 1 or snapshot_sequence is None)):
        raise _error("patent_work_page_invalid", "Reload the first work page.", 422)
    get_patent_application(session, context=context, application_id=application_id)
    application = _application(session, context, application_id)
    if snapshot_sequence is not None and snapshot_sequence != application.work_sequence:
        raise _error("patent_work_stale", "Patent work changed. Reload the first page.")
    statement = select(model).where(
        model.company_id == context.company.id, model.application_id == application_id
    )
    if cursor is not None:
        statement = statement.where(model.sequence < cursor)
    rows = list(session.scalars(statement.order_by(model.sequence.desc()).limit(limit + 1)))
    return (
        application.work_sequence,
        rows[:limit],
        rows[limit - 1].sequence if len(rows) > limit else None,
    )


def list_patent_evidence(
    session, *, context, application_id, limit=25, cursor=None, snapshot_sequence=None
):
    sequence, rows, next_cursor = _page(
        session, context, application_id, IpPatentEvidenceVersion, limit, cursor, snapshot_sequence
    )
    return PatentEvidencePage(
        application_id=application_id,
        work_sequence=sequence,
        records=_evidence_records(session, context, rows),
        next_cursor=next_cursor,
    )


def _lock_work(session, context, application_id, sources):
    assert_domain_operation("patent", session=session)
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    application = _application(session, context, application_id)
    docket = _lock_sources_and_dockets(session, context, sources, {application.docket_id})[
        application.docket_id
    ]
    application = session.scalar(
        select(IpPatentApplication)
        .where(
            IpPatentApplication.company_id == context.company.id,
            IpPatentApplication.id == application_id,
        )
        .execution_options(populate_existing=True)
    )
    anchor = get_patent_application(session, context=context, application_id=application_id)
    return context, application, docket, anchor


def _preconditions(application, anchor, payload):
    if (anchor.version, anchor.lifecycle_version, application.work_sequence) != (
        payload.expected_version,
        payload.expected_lifecycle_version,
        payload.expected_work_sequence,
    ):
        raise _error(
            "patent_work_stale", "Application or patent work changed. Reload before saving."
        )


def _claim(session, context, application_id, payload, key, operation):
    claim = claim_idempotency(
        session,
        company_id=context.company.id,
        actor_scope=f"membership:{context.membership.id}",
        actor_membership_id=context.membership.id,
        http_method="POST",
        operation=operation,
        idempotency_key=key,
        request_hash=canonical_json_sha256(
            {"application_id": application_id, **payload.model_dump(mode="json")}
        ),
    )
    if claim.outcome not in {IdempotencyClaimOutcome.CLAIMED, IdempotencyClaimOutcome.REPLAY}:
        raise _error(
            "patent_work_command_conflict", "This command key is in use. Reload before retrying."
        )
    return claim


def _finish(session, context, application, docket, claim, row, result_type, action):
    record_from_context(
        session,
        context,
        action=action,
        target_type=result_type,
        target_id=row.id,
        ip_docket_id=docket.id,
        metadata={
            "application_id": application.id,
            "sequence": row.sequence,
            "lifecycle_version": row.lifecycle_version,
        },
    )
    complete_idempotency(
        session,
        company_id=context.company.id,
        record_id=claim.record.id,
        claim_token=claim.claim_token,
        claim_generation=claim.claim_generation,
        response_status=201,
        result_type=result_type,
        result_id=row.id,
    )


def _version_id(session, context, application_id, version):
    identifier = session.scalar(
        select(IpPatentApplicationVersion.id).where(
            IpPatentApplicationVersion.company_id == context.company.id,
            IpPatentApplicationVersion.application_id == application_id,
            IpPatentApplicationVersion.version == version,
        )
    )
    if identifier is None:
        raise _error("patent_application_version_not_found", "Application version not found.", 404)
    return identifier


def create_patent_evidence(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    payload: PatentEvidenceCreateRequest,
    idempotency_key: str,
) -> PatentEvidenceRecord:
    sources = [payload.source, *(item.source for item in payload.documents)]
    context, application, docket, anchor = _lock_work(session, context, application_id, sources)
    claim = _claim(
        session, context, application_id, payload, idempotency_key, "ip.patent.evidence.create"
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        if claim.record.result_type != "ip_patent_evidence" or not claim.record.result_id:
            raise _error("patent_work_replay_integrity", "The saved command cannot be resolved.")
        if payload.expected_lifecycle_version != anchor.lifecycle_version:
            raise _error("patent_work_stale", "A prior lifecycle command cannot be replayed.")
        return get_patent_evidence(
            session,
            context=context,
            application_id=application_id,
            evidence_id=claim.record.result_id,
        )
    _preconditions(application, anchor, payload)
    predecessor = None
    if payload.predecessor_id:
        predecessor = get_patent_evidence(
            session,
            context=context,
            application_id=application_id,
            evidence_id=str(payload.predecessor_id),
        )
        successor = session.scalar(
            select(IpPatentEvidenceVersion.id)
            .where(
                IpPatentEvidenceVersion.company_id == context.company.id,
                IpPatentEvidenceVersion.predecessor_id == str(predecessor.id),
            )
            .limit(1)
        )
        retained = list(
            session.scalars(
                select(IpPatentEvidenceVersion.id)
                .where(
                    IpPatentEvidenceVersion.company_id == context.company.id,
                    IpPatentEvidenceVersion.application_id == application_id,
                    IpPatentEvidenceVersion.root_id == str(predecessor.root_id),
                )
                .limit(EDITION_LIMIT + 1)
            )
        )
        if len(retained) >= EDITION_LIMIT:
            raise _error(
                "patent_evidence_history_limit",
                "This document lineage reached its retained-version bound.",
            )
        if (
            successor
            or predecessor.document_kind != payload.document_kind
            or predecessor.lifecycle_version != anchor.lifecycle_version
        ):
            raise _error(
                "patent_evidence_predecessor_invalid",
                "Select the current edition in this lifecycle.",
            )
    digest = _manifest_digest(
        payload.title, payload.document_kind, payload.source, payload.documents
    )
    if predecessor and compare_digest(predecessor.manifest_sha256, digest):
        raise _error(
            "patent_evidence_unchanged",
            "The selected edition already contains this exact manifest.",
        )
    identifier = str(uuid4())
    application.work_sequence += 1
    row = IpPatentEvidenceVersion(
        id=identifier,
        company_id=context.company.id,
        application_id=application_id,
        anchor_version_id=_version_id(session, context, application_id, anchor.version),
        anchor_version=anchor.version,
        lifecycle_version=anchor.lifecycle_version,
        sequence=application.work_sequence,
        root_id=str(predecessor.root_id) if predecessor else identifier,
        predecessor_id=str(predecessor.id) if predecessor else None,
        edition=predecessor.edition + 1 if predecessor else 1,
        title=payload.title,
        document_kind=payload.document_kind,
        **_source_columns(payload.source),
        manifest_sha256=digest,
        document_count=len(payload.documents),
        created_by_membership_id=context.membership.id,
        reason=payload.reason,
    )
    session.add(row)
    session.flush()
    for ordinal, item in enumerate(payload.documents):
        session.add(
            IpPatentEvidenceDocument(
                company_id=context.company.id,
                application_id=application_id,
                evidence_id=row.id,
                ordinal=ordinal,
                document_kind=item.document_kind,
                document_id=str(item.source.document_id),
                document_version_id=str(item.source.document_version_id),
                content_sha256=item.source.content_sha256,
            )
        )
    session.flush()
    for pin in {_source_key(pin): pin for pin in sources}.values():
        _link_disclosure_source(session, context, docket, pin)
    _finish(
        session,
        context,
        application,
        docket,
        claim,
        row,
        "ip_patent_evidence",
        "ip_patent_evidence.created",
    )
    result = get_patent_evidence(
        session, context=context, application_id=application_id, evidence_id=row.id
    )
    session.commit()
    return result


def _preview(session, context, application_id, payload):
    anchor = get_patent_application(session, context=context, application_id=application_id)
    application = _application(session, context, application_id)
    _preconditions(application, anchor, payload)
    if not anchor.is_active or anchor.lifecycle_status in {
        "archived",
        "abandoned",
        "transferred",
        "retired",
        "closed",
    }:
        raise _error("patent_work_terminal", "Closed applications retain read-only evidence.")
    if payload.expected_phase != application.prosecution_phase:
        raise _error(
            "patent_prosecution_stale", "The prosecution phase changed. Reload before saving."
        )
    _source_version(session, context, payload.source)
    target, allowed = PHASES[payload.event_kind]
    target = target or application.prosecution_phase
    exceptional = application.prosecution_phase not in allowed
    if exceptional and not payload.exceptional_transition_reason:
        raise _error(
            "patent_transition_source_required",
            "Explain the exceptional sourced transition before previewing.",
        )
    if payload.event_kind == "restoration" and anchor.lifecycle_version == 0:
        raise _error(
            "patent_restoration_requires_reopen",
            "Record explicit lifecycle reopening before restoration.",
        )
    evidence = None
    if payload.event_kind in PACKAGE_EVENTS and payload.evidence_id is None:
        raise _error(
            "patent_filing_manifest_required", "Select the exact document manifest for this event."
        )
    if payload.evidence_id:
        evidence = get_patent_evidence(
            session,
            context=context,
            application_id=application_id,
            evidence_id=str(payload.evidence_id),
        )
        successor = session.scalar(
            select(IpPatentEvidenceVersion.id)
            .where(
                IpPatentEvidenceVersion.company_id == context.company.id,
                IpPatentEvidenceVersion.predecessor_id == str(evidence.id),
            )
            .limit(1)
        )
        if successor or (evidence.anchor_version, evidence.lifecycle_version) != (
            anchor.version,
            anchor.lifecycle_version,
        ):
            raise _error(
                "patent_filing_manifest_stale",
                "Prepare a current application manifest before recording this event.",
            )
        if payload.event_kind == "filing" and evidence.document_kind != "filing_package":
            raise _error(
                "patent_filing_manifest_required", "Filing requires an exact filing package."
            )
    latest = session.scalar(
        select(IpPatentProsecutionEvent.effective_on)
        .where(
            IpPatentProsecutionEvent.company_id == context.company.id,
            IpPatentProsecutionEvent.application_id == application_id,
        )
        .order_by(IpPatentProsecutionEvent.effective_on.desc())
        .limit(1)
    )
    backdated = latest is not None and payload.effective_on < latest
    deadlines = (
        list(
            session.execute(
                select(
                    IpDeadline.id,
                    IpDeadline.version,
                    IpDeadline.state,
                    IpDeadline.result_on,
                    IpDeadline.result_at,
                )
                .where(
                    IpDeadline.company_id == context.company.id,
                    IpDeadline.docket_id == str(anchor.docket_id),
                    IpDeadline.state.in_(("provisional", "candidate", "confirmed", "overdue")),
                )
                .order_by(IpDeadline.id)
                .limit(101)
            )
        )
        if backdated
        else []
    )
    if len(deadlines) > 100:
        raise _error(
            "patent_impact_limit",
            "More than 100 open legal deadlines require bounded reconciliation first.",
        )
    required = []
    if backdated:
        required.append("backdated_recalculation_review_required")
    if exceptional:
        required.append("exceptional_transition_review_required")
    digest = canonical_json_sha256(
        {
            "application_id": application_id,
            "version": anchor.version,
            "lifecycle_version": anchor.lifecycle_version,
            "sequence": application.work_sequence,
            "payload": payload.model_dump(
                mode="json", exclude={"preview_sha256", "acknowledged_exception_codes"}
            ),
            "phase": application.prosecution_phase,
            "target": target,
            "manifest_sha256": evidence.manifest_sha256 if evidence else None,
            "deadlines": [
                [value.isoformat() if hasattr(value, "isoformat") else value for value in row]
                for row in deadlines
            ],
            "required": required,
        }
    )
    return PatentProsecutionPreview(
        application_id=application_id,
        work_sequence=application.work_sequence,
        current_phase=application.prosecution_phase,
        proposed_phase=target,
        backdated=backdated,
        affected_deadline_ids=tuple(row.id for row in deadlines),
        required_acknowledgements=tuple(required),
        preview_sha256=digest,
    )


def preview_patent_prosecution(session, *, context, application_id, payload):
    return _preview(session, context, application_id, payload)


def _event_records(session, context, rows):
    _assert_sources(session, context, [_source(row) for row in rows])
    evidence_ids = {row.evidence_id for row in rows if row.evidence_id}
    if evidence_ids:
        evidence = list(
            session.scalars(
                select(IpPatentEvidenceVersion)
                .where(
                    IpPatentEvidenceVersion.company_id == context.company.id,
                    IpPatentEvidenceVersion.id.in_(evidence_ids),
                )
                .limit(101)
            )
        )
        if {row.id for row in evidence} != evidence_ids:
            raise _error(
                "patent_manifest_integrity", "A retained event manifest cannot be resolved."
            )
        _evidence_records(session, context, evidence)
    return [
        PatentProsecutionRecord(
            id=row.id,
            application_id=row.application_id,
            sequence=row.sequence,
            anchor_version=row.anchor_version,
            lifecycle_version=row.lifecycle_version,
            event_kind=row.event_kind,
            received_on=row.received_on,
            effective_on=row.effective_on,
            source=_source(row),
            evidence_id=row.evidence_id,
            before_phase=row.before_phase,
            after_phase=row.after_phase,
            reason=row.reason,
            exceptional_transition_reason=row.exceptional_transition_reason,
            impact=PatentProsecutionPreview.model_validate(row.impact_json),
            created_at=_aware(row.created_at),
        )
        for row in rows
    ]


def get_patent_prosecution_event(session, *, context, application_id, event_id):
    get_patent_application(session, context=context, application_id=application_id)
    row = session.scalar(
        select(IpPatentProsecutionEvent).where(
            IpPatentProsecutionEvent.company_id == context.company.id,
            IpPatentProsecutionEvent.application_id == application_id,
            IpPatentProsecutionEvent.id == event_id,
        )
    )
    if row is None:
        raise _error("patent_prosecution_not_found", "Patent prosecution event not found.", 404)
    return _event_records(session, context, [row])[0]


def list_patent_prosecution(
    session, *, context, application_id, limit=25, cursor=None, snapshot_sequence=None
):
    sequence, rows, next_cursor = _page(
        session, context, application_id, IpPatentProsecutionEvent, limit, cursor, snapshot_sequence
    )
    return PatentProsecutionPage(
        application_id=application_id,
        work_sequence=sequence,
        records=_event_records(session, context, rows),
        next_cursor=next_cursor,
    )


def create_patent_prosecution(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    payload: PatentProsecutionCreateRequest,
    idempotency_key: str,
) -> PatentProsecutionRecord:
    sources = [payload.source]
    if payload.evidence_id:
        evidence = get_patent_evidence(
            session,
            context=context,
            application_id=application_id,
            evidence_id=str(payload.evidence_id),
        )
        sources.extend([evidence.source, *(item.source for item in evidence.documents)])
    sources = list({_source_key(pin): pin for pin in sources}.values())
    if len(sources) > 21:
        raise _error("patent_source_limit", "An event can retain at most 21 distinct sources.", 422)
    context, application, docket, anchor = _lock_work(session, context, application_id, sources)
    claim = _claim(
        session, context, application_id, payload, idempotency_key, "ip.patent.prosecution.create"
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        if claim.record.result_type != "ip_patent_prosecution" or not claim.record.result_id:
            raise _error("patent_work_replay_integrity", "The saved command cannot be resolved.")
        if payload.expected_lifecycle_version != anchor.lifecycle_version:
            raise _error("patent_work_stale", "A prior lifecycle command cannot be replayed.")
        return get_patent_prosecution_event(
            session, context=context, application_id=application_id, event_id=claim.record.result_id
        )
    impact = _preview(session, context, application_id, payload)
    if payload.preview_sha256 != impact.preview_sha256:
        raise _error(
            "patent_prosecution_preview_changed",
            "Review a fresh prosecution preview before saving.",
        )
    if set(payload.acknowledged_exception_codes) != set(impact.required_acknowledgements):
        raise _error(
            "patent_prosecution_acknowledgement_required",
            "Acknowledge the current prosecution impact before saving.",
        )
    application.work_sequence += 1
    row = IpPatentProsecutionEvent(
        company_id=context.company.id,
        application_id=application_id,
        anchor_version_id=_version_id(session, context, application_id, anchor.version),
        anchor_version=anchor.version,
        lifecycle_version=anchor.lifecycle_version,
        sequence=application.work_sequence,
        event_kind=payload.event_kind,
        received_on=payload.received_on,
        effective_on=payload.effective_on,
        **_source_columns(payload.source),
        evidence_id=str(payload.evidence_id) if payload.evidence_id else None,
        before_phase=impact.current_phase,
        after_phase=impact.proposed_phase,
        impact_json=impact.model_dump(mode="json"),
        exceptional_transition_reason=payload.exceptional_transition_reason,
        created_by_membership_id=context.membership.id,
        reason=payload.reason,
    )
    session.add(row)
    application.prosecution_phase = impact.proposed_phase
    session.flush()
    _link_disclosure_source(session, context, docket, payload.source)
    _finish(
        session,
        context,
        application,
        docket,
        claim,
        row,
        "ip_patent_prosecution",
        "ip_patent_prosecution.recorded",
    )
    result = get_patent_prosecution_event(
        session, context=context, application_id=application_id, event_id=row.id
    )
    session.commit()
    return result
