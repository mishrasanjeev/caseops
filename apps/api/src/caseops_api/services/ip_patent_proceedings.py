"""Pre-grant proceedings use canonical identities and patent application locks."""

from sqlalchemy import and_, select

from caseops_api.db.models import (
    IpIdentifier,
    IpPartyAndRole,
    IpPatentEvidenceVersion,
    IpPatentProceedingDetail,
    IpPatentProceedingEvent,
    IpProceeding,
)
from caseops_api.schemas.ip_patent_proceedings import (
    PatentProceedingEventRecord,
    PatentProceedingHistory,
    PatentProceedingPage,
    PatentProceedingPreview,
    PatentProceedingRecord,
)
from caseops_api.services.idempotency import IdempotencyClaimOutcome, canonical_json_sha256
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.ip_patent_applications import (
    _application,
    _source,
    _source_columns,
    get_patent_application,
)
from caseops_api.services.ip_patent_families import _error, _link_disclosure_source, _source_version
from caseops_api.services.ip_patent_prosecution import (
    _assert_sources,
    _aware,
    _claim,
    _evidence_records,
    _finish,
    _lock_work,
    _preconditions,
    _version_id,
    get_patent_evidence,
)

KIND = "patent_pre_grant_opposition"
STAGES = {
    "notice_recorded": ("response_preparation", "withdrawn"),
    "response_preparation": ("response_filed", "withdrawn"),
    "response_filed": ("hearing_recorded", "decided", "withdrawn"),
    "hearing_recorded": ("hearing_recorded", "response_preparation", "decided", "withdrawn"),
    "decided": (),
    "withdrawn": (),
}
HISTORY_LIMIT = 100
PROCEEDING_LIMIT = 100


def _events(session, context, rows):
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
            raise _error("patent_proceeding_integrity", "A retained manifest cannot be resolved.")
        _evidence_records(session, context, evidence)
    return [
        PatentProceedingEventRecord(
            id=row.id,
            revision=row.revision,
            sequence=row.sequence,
            anchor_version=row.anchor_version,
            lifecycle_version=row.lifecycle_version,
            before_stage=row.before_stage,
            after_stage=row.after_stage,
            source=_source(row),
            received_on=row.received_on,
            effective_on=row.effective_on,
            proceeding_number=row.proceeding_number,
            evidence_id=row.evidence_id,
            reason=row.reason,
            outcome=row.outcome,
            exceptional_transition_reason=row.exceptional_transition_reason,
            impact=PatentProceedingPreview.model_validate(row.impact_json)
            if row.impact_json
            else None,
            created_at=_aware(row.created_at),
        )
        for row in rows
    ]


def _statement(context, application_id):
    return (
        select(IpPatentProceedingDetail, IpProceeding, IpPatentProceedingEvent)
        .join(
            IpProceeding,
            and_(
                IpProceeding.id == IpPatentProceedingDetail.id,
                IpProceeding.company_id == IpPatentProceedingDetail.company_id,
            ),
        )
        .outerjoin(
            IpPatentProceedingEvent,
            and_(
                IpPatentProceedingEvent.proceeding_id == IpProceeding.id,
                IpPatentProceedingEvent.company_id == IpProceeding.company_id,
                IpPatentProceedingEvent.revision == IpProceeding.version,
            ),
        )
        .where(
            IpPatentProceedingDetail.company_id == context.company.id,
            IpPatentProceedingDetail.application_id == application_id,
        )
    )


def _records(session, context, anchor, rows):
    for detail, owner, event in rows:
        if (
            event is None
            or owner.proceeding_kind != KIND
            or owner.application_id is not None
            or owner.stage != event.after_stage
            or event.application_id != detail.application_id
            or detail.docket_id != owner.docket_id
            or owner.docket_id != str(anchor.docket_id)
            or owner.stage_template_version != "patent-pre-grant-v1"
            or detail.lifecycle_version != event.lifecycle_version
        ):
            raise _error("patent_proceeding_integrity", "The proceeding requires reconciliation.")
    # Intake controls the identity labels even when a later stage has a different source.
    initial = (
        list(
            session.scalars(
                select(IpPatentProceedingEvent)
                .where(
                    IpPatentProceedingEvent.company_id == context.company.id,
                    IpPatentProceedingEvent.proceeding_id.in_([detail.id for detail, _, _ in rows]),
                    IpPatentProceedingEvent.revision == 1,
                )
                .limit(101)
            )
        )
        if rows
        else []
    )
    if len(initial) != len(rows):
        raise _error("patent_proceeding_integrity", "A proceeding intake cannot be resolved.")
    _assert_sources(session, context, [_source(row) for row in initial])
    events = _events(session, context, [event for _, _, event in rows])
    results = []
    for (detail, owner, _), event in zip(rows, events, strict=True):
        operational = (
            anchor.is_active
            and anchor.lifecycle_version == detail.lifecycle_version
            and anchor.lifecycle_status
            not in {"closed", "archived", "abandoned", "transferred", "retired"}
            and bool(STAGES[owner.stage])
        )
        results.append(
            PatentProceedingRecord(
                id=owner.id,
                application_id=detail.application_id,
                docket_id=owner.docket_id,
                proceeding_kind=KIND,
                title=detail.title,
                counterparty=detail.counterparty,
                side=owner.side,
                office=owner.office,
                jurisdiction=owner.jurisdiction,
                version=owner.version,
                stage=owner.stage,
                lifecycle_version=detail.lifecycle_version,
                operational=operational,
                allowed_stages=STAGES[owner.stage] if operational else (),
                latest=event,
            )
        )
    return results


def get_patent_proceeding(session, *, context, application_id, proceeding_id):
    anchor = get_patent_application(session, context=context, application_id=application_id)
    row = session.execute(
        _statement(context, application_id)
        .where(
            IpPatentProceedingDetail.id == proceeding_id,
        )
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise _error("patent_proceeding_not_found", "Patent proceeding not found.", 404)
    return _records(session, context, anchor, [row])[0]


def list_patent_proceedings(
    session, *, context, application_id, limit=25, cursor=None, snapshot_sequence=None
):
    anchor = get_patent_application(session, context=context, application_id=application_id)
    sequence = _application(session, context, application_id).work_sequence
    if not 1 <= limit <= 100 or (cursor and snapshot_sequence is None):
        raise _error("patent_proceeding_page_invalid", "Reload the first proceeding page.", 422)
    if snapshot_sequence is not None and snapshot_sequence != sequence:
        raise _error("patent_work_stale", "Patent work changed. Reload the first page.")
    statement = _statement(context, application_id)
    if cursor:
        statement = statement.where(IpPatentProceedingDetail.id > cursor)
    rows = list(session.execute(statement.order_by(IpPatentProceedingDetail.id).limit(limit + 1)))
    return PatentProceedingPage(
        application_id=application_id,
        work_sequence=sequence,
        records=_records(session, context, anchor, rows[:limit]),
        next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
    )


def get_patent_proceeding_history(session, *, context, application_id, proceeding_id):
    record = get_patent_proceeding(
        session, context=context, application_id=application_id, proceeding_id=proceeding_id
    )
    rows = list(
        session.scalars(
            select(IpPatentProceedingEvent)
            .where(
                IpPatentProceedingEvent.company_id == context.company.id,
                IpPatentProceedingEvent.application_id == application_id,
                IpPatentProceedingEvent.proceeding_id == proceeding_id,
            )
            .order_by(IpPatentProceedingEvent.revision)
            .limit(HISTORY_LIMIT + 1)
        )
    )
    if (
        len(rows) != record.version
        or len(rows) > HISTORY_LIMIT
        or [row.revision for row in rows] != list(range(1, record.version + 1))
    ):
        raise _error(
            "patent_proceeding_history_bound", "The proceeding history requires reconciliation."
        )
    return PatentProceedingHistory(proceeding=record, events=_events(session, context, rows))


def _number(session, context, owner, payload, prior=None):
    number = payload.proceeding_number or prior
    if prior and number != prior:
        raise _error(
            "patent_proceeding_number_immutable",
            "Retain the assigned proceeding number; correction requires "
            "a separate sourced identity workflow.",
        )
    if number and not prior:
        existing = session.scalar(
            select(IpIdentifier.id)
            .where(
                IpIdentifier.company_id == context.company.id,
                IpIdentifier.identifier_kind == KIND,
                IpIdentifier.office == owner.office,
                IpIdentifier.jurisdiction == owner.jurisdiction,
                IpIdentifier.normalized_value == normalize_ip_identifier(number),
                IpIdentifier.effective_until.is_(None),
            )
            .limit(1)
        )
        if existing:
            raise _error(
                "patent_proceeding_duplicate_number",
                "This proceeding number already has a retained identity.",
            )
        session.add(
            IpIdentifier(
                company_id=context.company.id,
                docket_id=owner.docket_id,
                proceeding_id=owner.id,
                identifier_kind=KIND,
                raw_value=number,
                normalized_value=normalize_ip_identifier(number),
                office=owner.office,
                jurisdiction=owner.jurisdiction,
                source=f"document-version:{payload.source.document_version_id}",
                effective_from=payload.effective_on,
                is_primary=True,
            )
        )
        owner.source_pending_identifier_allocation = False
    return number


def _append(
    session,
    context,
    application,
    docket,
    anchor,
    owner,
    payload,
    claim,
    *,
    before=None,
    impact=None,
    prior_number=None,
):
    number = _number(session, context, owner, payload, prior_number)
    application.work_sequence += 1
    event = IpPatentProceedingEvent(
        company_id=context.company.id,
        application_id=application.id,
        proceeding_id=owner.id,
        anchor_version_id=_version_id(session, context, application.id, anchor.version),
        anchor_version=anchor.version,
        lifecycle_version=anchor.lifecycle_version,
        sequence=application.work_sequence,
        revision=owner.version,
        before_stage=before,
        after_stage=owner.stage,
        **_source_columns(payload.source),
        received_on=payload.received_on,
        effective_on=payload.effective_on,
        proceeding_number=number,
        evidence_id=str(payload.evidence_id) if getattr(payload, "evidence_id", None) else None,
        reason=payload.reason,
        outcome=getattr(payload, "outcome", None),
        exceptional_transition_reason=getattr(payload, "exceptional_transition_reason", None),
        impact_json=impact.model_dump(mode="json") if impact else None,
        created_by_membership_id=context.membership.id,
    )
    session.add(event)
    session.flush()
    _link_disclosure_source(session, context, docket, payload.source)
    _finish(
        session,
        context,
        application,
        docket,
        claim,
        event,
        "ip_patent_proceeding_event",
        "ip_patent_proceeding.transitioned" if before else "ip_patent_proceeding.created",
    )
    result = get_patent_proceeding(
        session, context=context, application_id=application.id, proceeding_id=owner.id
    )
    session.commit()
    return result


def _replay(session, context, application_id, anchor, payload, claim):
    if payload.expected_lifecycle_version != anchor.lifecycle_version:
        raise _error("patent_work_stale", "A prior lifecycle command cannot be replayed.")
    event = (
        session.scalar(
            select(IpPatentProceedingEvent).where(
                IpPatentProceedingEvent.id == claim.record.result_id,
                IpPatentProceedingEvent.company_id == context.company.id,
                IpPatentProceedingEvent.application_id == application_id,
            )
        )
        if claim.record.result_type == "ip_patent_proceeding_event"
        else None
    )
    if event is None:
        raise _error("patent_work_replay_integrity", "The saved command cannot be resolved.")
    record = get_patent_proceeding(
        session, context=context, application_id=application_id, proceeding_id=event.proceeding_id
    )
    if not record.operational:
        raise _error("patent_proceeding_terminal", "This proceeding retains read-only evidence.")
    return record


def create_patent_proceeding(session, *, context, application_id, payload, idempotency_key):
    context, application, docket, anchor = _lock_work(
        session, context, application_id, [payload.source]
    )
    claim = _claim(
        session, context, application_id, payload, idempotency_key, "ip.patent.proceeding.create"
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        return _replay(session, context, application_id, anchor, payload, claim)
    _preconditions(application, anchor, payload)
    if (anchor.facts.jurisdiction, anchor.facts.office) != ("IN", "IP India"):
        raise _error(
            "patent_proceeding_office_unimplemented",
            "Pre-grant proceedings are implemented only for the IP India application scope.",
        )
    retained = list(
        session.scalars(
            select(IpPatentProceedingDetail.id)
            .where(
                IpPatentProceedingDetail.company_id == context.company.id,
                IpPatentProceedingDetail.application_id == application_id,
            )
            .limit(PROCEEDING_LIMIT + 1)
        )
    )
    if len(retained) >= PROCEEDING_LIMIT:
        raise _error(
            "patent_proceeding_limit", "This application reached its 100 proceeding bound."
        )
    if application.prosecution_phase == "granted":
        raise _error(
            "patent_pre_grant_required",
            "A granted application cannot start a pre-grant opposition.",
        )
    owner = IpProceeding(
        company_id=context.company.id,
        docket_id=docket.id,
        application_id=None,
        proceeding_kind=KIND,
        side=payload.side,
        office=anchor.facts.office,
        jurisdiction=anchor.facts.jurisdiction,
        stage="notice_recorded",
        origin_kind="linked_application",
        stage_template_version="patent-pre-grant-v1",
        source_pending_identifier_allocation=payload.source_pending_identifier_allocation,
    )
    session.add(owner)
    session.flush()
    session.add(
        IpPatentProceedingDetail(
            id=owner.id,
            company_id=context.company.id,
            application_id=application_id,
            docket_id=docket.id,
            title=payload.title,
            counterparty=payload.counterparty,
            lifecycle_version=anchor.lifecycle_version,
        )
    )
    session.add(
        IpPartyAndRole(
            company_id=context.company.id,
            docket_id=docket.id,
            proceeding_id=owner.id,
            party_name=payload.counterparty,
            role_kind="opponent" if payload.side == "applicant" else "applicant",
            effective_from=payload.effective_on,
            source=f"document-version:{payload.source.document_version_id}",
        )
    )
    session.flush()
    return _append(session, context, application, docket, anchor, owner, payload, claim)


def _preview(session, context, application_id, proceeding_id, payload):
    anchor = get_patent_application(session, context=context, application_id=application_id)
    application = _application(session, context, application_id)
    _preconditions(application, anchor, payload)
    record = get_patent_proceeding(
        session, context=context, application_id=application_id, proceeding_id=proceeding_id
    )
    if not record.operational:
        raise _error(
            "patent_proceeding_terminal",
            "This proceeding retains read-only evidence, including after application reopening.",
        )
    if (record.jurisdiction, record.office) != (anchor.facts.jurisdiction, anchor.facts.office):
        raise _error(
            "patent_proceeding_office_changed",
            "The application's office scope changed; retain this proceeding for reconciliation.",
        )
    if payload.expected_proceeding_version != record.version:
        raise _error("patent_proceeding_stale", "The proceeding changed. Reload before saving.")
    if record.version >= HISTORY_LIMIT:
        raise _error(
            "patent_proceeding_history_bound", "This proceeding reached its 100 event bound."
        )
    if payload.to_stage == "notice_recorded":
        raise _error(
            "patent_proceeding_stage_invalid", "A retained proceeding cannot return to intake."
        )
    _source_version(session, context, payload.source)
    if (
        payload.proceeding_number
        and record.latest.proceeding_number
        and payload.proceeding_number != record.latest.proceeding_number
    ):
        raise _error("patent_proceeding_number_immutable", "Retain the assigned proceeding number.")
    required = []
    if payload.to_stage not in STAGES[record.stage]:
        if not payload.exceptional_transition_reason:
            raise _error(
                "patent_proceeding_exception_required",
                "Explain the sourced exceptional stage before previewing.",
            )
        required.append("exceptional_stage_review")
    latest_date = session.scalar(
        select(IpPatentProceedingEvent.effective_on)
        .where(
            IpPatentProceedingEvent.company_id == context.company.id,
            IpPatentProceedingEvent.proceeding_id == proceeding_id,
        )
        .order_by(IpPatentProceedingEvent.effective_on.desc())
        .limit(1)
    )
    if payload.effective_on < latest_date:
        required.append("backdated_source_review")
    evidence = None
    if payload.evidence_id:
        evidence = get_patent_evidence(
            session,
            context=context,
            application_id=application_id,
            evidence_id=str(payload.evidence_id),
        )
        if (
            not evidence.is_current
            or evidence.anchor_version != anchor.version
            or evidence.lifecycle_version != anchor.lifecycle_version
            or evidence.document_kind not in {"response", "filing_package"}
        ):
            raise _error(
                "patent_proceeding_response_stale",
                "Select a current response or filing manifest for this application lifecycle.",
            )
    digest = canonical_json_sha256(
        {
            "proceeding": record.model_dump(mode="json"),
            "payload": payload.model_dump(
                mode="json", exclude={"preview_sha256", "acknowledged_exception_codes"}
            ),
            "manifest": evidence.manifest_sha256 if evidence else None,
            "required": required,
        }
    )
    return PatentProceedingPreview(
        proceeding_id=proceeding_id,
        current_stage=record.stage,
        proposed_stage=payload.to_stage,
        required_acknowledgements=tuple(required),
        preview_sha256=digest,
    )


def preview_patent_proceeding(session, *, context, application_id, proceeding_id, payload):
    return _preview(session, context, application_id, proceeding_id, payload)


def transition_patent_proceeding(
    session, *, context, application_id, proceeding_id, payload, idempotency_key
):
    get_patent_proceeding(
        session, context=context, application_id=application_id, proceeding_id=proceeding_id
    )
    sources = [payload.source]
    if payload.evidence_id:
        evidence = get_patent_evidence(
            session,
            context=context,
            application_id=application_id,
            evidence_id=str(payload.evidence_id),
        )
        sources.extend([evidence.source, *(item.source for item in evidence.documents)])
    # The source-lock helper bounds distinct source parents and rechecks current ACLs.
    sources = list({str(source.document_version_id): source for source in sources}.values())
    context, application, docket, anchor = _lock_work(session, context, application_id, sources)
    claim = _claim(
        session,
        context,
        application_id,
        payload,
        idempotency_key,
        f"ip.patent.proceeding.{proceeding_id}.transition",
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        return _replay(session, context, application_id, anchor, payload, claim)
    impact = _preview(session, context, application_id, proceeding_id, payload)
    if payload.preview_sha256 != impact.preview_sha256:
        raise _error(
            "patent_proceeding_preview_changed", "Review a fresh proceeding preview before saving."
        )
    if set(payload.acknowledged_exception_codes) != set(impact.required_acknowledgements):
        raise _error(
            "patent_proceeding_acknowledgement_required",
            "Acknowledge the current proceeding impact before saving.",
        )
    owner = session.scalar(
        select(IpProceeding)
        .where(IpProceeding.id == proceeding_id, IpProceeding.company_id == context.company.id)
        .execution_options(populate_existing=True)
    )
    latest = session.scalar(
        select(IpPatentProceedingEvent).where(
            IpPatentProceedingEvent.proceeding_id == proceeding_id,
            IpPatentProceedingEvent.company_id == context.company.id,
            IpPatentProceedingEvent.revision == owner.version,
        )
    )
    before = owner.stage
    owner.stage = payload.to_stage
    owner.version += 1
    return _append(
        session,
        context,
        application,
        docket,
        anchor,
        owner,
        payload,
        claim,
        before=before,
        impact=impact,
        prior_number=latest.proceeding_number,
    )
