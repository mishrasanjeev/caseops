"""Distinct specialist workflows on canonical IP and shared-work owners."""

from datetime import UTC, datetime
from hmac import compare_digest

from pydantic import TypeAdapter
from sqlalchemy import select

from caseops_api.db.ip_specialist_models import (
    IpSpecialistObligationEvent,
    IpSpecialistObligationLink,
    IpSpecialistWorkflow,
    IpSpecialistWorkflowSource,
    IpSpecialistWorkflowVersion,
)
from caseops_api.db.models import (
    IpCostItem,
    IpCostItemCorrection,
    IpDocumentLink,
    IpDocumentVersion,
    IpProceeding,
    IpRelatedRightObligation,
    IpTitleInterest,
)
from caseops_api.schemas.ip_operations import IpCostItemCreateRequest
from caseops_api.schemas.ip_specialist import SpecialistSource
from caseops_api.schemas.ip_specialist_workflows import (
    ContractObligationRecord,
    ContractPerformanceRecord,
    CopyrightRegistration,
    DesignApplication,
    LayoutApplication,
    Licence,
    RightsClaim,
    SourceSet,
    SpecialistProceeding,
    WorkflowFacts,
    WorkflowList,
    WorkflowRecord,
)
from caseops_api.schemas.shared_work import (
    IpOperationalDeadlineCreateRequest,
    IpOperationalDeadlineUpdateRequest,
    IpSharedTaskCreateRequest,
    IpSharedTaskUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.idempotency import IdempotencyClaimOutcome, canonical_json_sha256
from caseops_api.services.ip_cost_lineage import active_ip_cost_predicate
from caseops_api.services.ip_document_workflow import get_accessible_ip_document_ids
from caseops_api.services.ip_operations import (
    _apply_cost_reconciliation,
    _may_read_confidential_rates,
    _new_cost_item,
)
from caseops_api.services.ip_specialist import (
    _claim,
    _complete,
    _docket,
    _error,
    _header,
    _source,
    _writer,
)
from caseops_api.services.private_retrieval import (
    private_source_version,
    propagate_private_projection_change,
)
from caseops_api.services.shared_work import (
    create_ip_operational_deadline,
    create_ip_shared_task,
    update_ip_operational_deadline,
    update_ip_shared_task,
)

FACTS = TypeAdapter(WorkflowFacts)
KINDS = {
    "design": {"source_set", "design_application", "rights_claim", "proceeding"},
    "copyright": {"source_set", "copyright_registration", "rights_claim", "proceeding"},
    "licensing": {"source_set", "licence", "proceeding"},
    "semiconductor_layout": {
        "source_set",
        "layout_application",
        "rights_claim",
        "licence",
        "proceeding",
    },
}
CONTRACT_WORK_KINDS = {
    "royalty",
    "reporting",
    "audit",
    "quality_control",
    "recordal",
    "notice",
    "renewal",
    "termination",
}
LAYOUT_WORK_KINDS = {"filing", "office_response", "hearing", "notice", "renewal"}
LAYOUT_PROCEEDING_CHANNELS = {"layout_opposition", "layout_cancellation", "layout_infringement"}
LAYOUT_TRANSITIONS = {
    "prepared": {"filed", "withdrawn"},
    "filed": {"examination", "objection", "hearing", "registered", "refused", "withdrawn"},
    "examination": {"objection", "response", "hearing", "registered", "refused", "withdrawn"},
    "objection": {"response", "hearing", "refused", "withdrawn"},
    "response": {"examination", "objection", "hearing", "registered", "refused", "withdrawn"},
    "hearing": {"response", "registered", "refused", "withdrawn"},
    "registered": set(),
    "refused": set(),
    "withdrawn": set(),
}
LAYOUT_PROCEEDING_TRANSITIONS = {
    "opened": {"notice", "response", "hearing", "decision", "closed"},
    "notice": {"response", "hearing", "decision", "closed"},
    "response": {"notice", "hearing", "decision", "closed"},
    "hearing": {"response", "decision", "closed"},
    "decision": {"appeal", "closed"},
    "appeal": {"hearing", "decision", "closed"},
    "closed": set(),
}
# These are repository command transitions, not statutory requirements or legal conclusions.
DESIGN_TRANSITIONS = {
    "prepared": {"filed"},
    "filed": {"examination", "objection", "accepted", "registered", "refused", "withdrawn"},
    "examination": {
        "objection",
        "response",
        "hearing",
        "accepted",
        "registered",
        "refused",
        "withdrawn",
    },
    "objection": {"response", "hearing", "refused", "withdrawn"},
    "response": {
        "examination",
        "objection",
        "hearing",
        "accepted",
        "registered",
        "refused",
        "withdrawn",
    },
    "hearing": {"objection", "response", "accepted", "registered", "refused", "withdrawn"},
    "accepted": {"registered", "withdrawn"},
    "registered": set(),
    "refused": set(),
    "withdrawn": set(),
}
COPYRIGHT_TRANSITIONS = {
    "prepared": {"filed"},
    "filed": {"deficiency", "objection", "hearing", "registered", "refused", "withdrawn"},
    "deficiency": {"response", "withdrawn", "refused"},
    "objection": {"response", "hearing", "withdrawn", "refused"},
    "response": {"deficiency", "objection", "hearing", "registered", "refused", "withdrawn"},
    "hearing": {"response", "registered", "refused", "withdrawn"},
    "registered": {"correction", "expunged"},
    "correction": {"registered", "expunged"},
    "expunged": set(),
    "refused": set(),
    "withdrawn": set(),
}


def _workflow(session, context, record, workflow_id):
    row = session.scalar(
        select(IpSpecialistWorkflow)
        .where(
            IpSpecialistWorkflow.id == str(workflow_id),
            IpSpecialistWorkflow.company_id == context.company.id,
            IpSpecialistWorkflow.record_id == record.id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _error("specialist_workflow_missing", "Workflow not found.", 404)
    return row


def _revision(session, context, workflow, version=None):
    revision = session.scalar(
        select(IpSpecialistWorkflowVersion).where(
            IpSpecialistWorkflowVersion.workflow_id == workflow.id,
            IpSpecialistWorkflowVersion.company_id == context.company.id,
            IpSpecialistWorkflowVersion.version == (version or workflow.version),
        )
    )
    if revision is None:
        raise _error("specialist_workflow_version_missing", "Workflow version not found.", 404)
    if not compare_digest(revision.facts_sha256, canonical_json_sha256(revision.facts_json)):
        raise _error("specialist_workflow_integrity", "Retained workflow evidence requires repair.")
    facts = FACTS.validate_python(revision.facts_json)
    if facts.kind != workflow.kind:
        raise _error("specialist_workflow_integrity", "Workflow identity requires repair.")
    return revision, facts


def _read_sources(session, context, revisions):
    pins = list(
        session.scalars(
            select(IpSpecialistWorkflowSource)
            .where(
                IpSpecialistWorkflowSource.company_id == context.company.id,
                IpSpecialistWorkflowSource.revision_id.in_([r.id for r in revisions]),
            )
            .limit(521)
        )
    )
    if len(pins) > 520:
        raise _error("specialist_source_budget", "Select a smaller workflow page.")
    ids = {p.document_id for p in pins}
    links = (
        list(
            session.scalars(
                select(IpDocumentLink.id)
                .where(
                    IpDocumentLink.company_id == context.company.id,
                    IpDocumentLink.document_id.in_(ids),
                )
                .limit(521)
            )
        )
        if ids
        else []
    )
    if len(links) > 520:
        raise _error("specialist_source_budget", "Source-link work exceeds this page's budget.")
    accessible = (
        get_accessible_ip_document_ids(session, context=context, document_ids=ids) if ids else set()
    )
    versions = (
        {
            v.id: v
            for v in session.scalars(
                select(IpDocumentVersion).where(
                    IpDocumentVersion.company_id == context.company.id,
                    IpDocumentVersion.id.in_({p.document_version_id for p in pins}),
                )
            )
        }
        if pins
        else {}
    )
    for pin in pins:
        version = versions.get(pin.document_version_id)
        if pin.document_id not in accessible or version is None:
            raise _error(
                "specialist_source_unavailable", "A retained source is no longer accessible.", 404
            )
        if version.document_id != pin.document_id or not compare_digest(
            version.sha256_hex, pin.content_sha256
        ):
            raise _error(
                "specialist_source_changed", "A retained source requires integrity repair."
            )


def _dto(workflow, revision, facts, docket, may_read_finance):
    if isinstance(facts, Licence) and not may_read_finance:
        # Do not mutate the validated retained snapshot or leak financial clause issues.
        facts = facts.model_copy(
            deep=True,
            update={
                "financial_terms": None,
                "financial_terms_withheld": facts.financial_terms is not None,
                "issues": [],
                "review_reason": "Restricted review evidence" if facts.review_reason else None,
                "account": "Restricted instrument evidence",
            },
        )
    return WorkflowRecord(
        id=workflow.id,
        record_id=workflow.record_id,
        version=revision.version,
        lifecycle_version=docket.lifecycle_version,
        canonical_proceeding_id=workflow.proceeding_id,
        canonical_title_interest_id=workflow.title_interest_id,
        recorded_at=revision.created_at.replace(tzinfo=UTC)
        if revision.created_at.tzinfo is None
        else revision.created_at,
        facts=facts,
    )


def get_workflow(session, *, context, record_id, workflow_id, version=None):
    record = _header(session, context, record_id)
    docket = _docket(session, context, record)
    workflow = _workflow(session, context, record, workflow_id)
    revision, facts = _revision(session, context, workflow, version)
    _read_sources(session, context, [revision])
    return _dto(
        workflow, revision, facts, docket, _may_read_confidential_rates(session, context=context)
    )


def list_workflows(session, *, context, record_id, limit=10, cursor=None):
    record = _header(session, context, record_id)
    docket = _docket(session, context, record)
    statement = (
        select(IpSpecialistWorkflow, IpSpecialistWorkflowVersion)
        .join(
            IpSpecialistWorkflowVersion,
            (IpSpecialistWorkflowVersion.workflow_id == IpSpecialistWorkflow.id)
            & (IpSpecialistWorkflowVersion.company_id == IpSpecialistWorkflow.company_id)
            & (IpSpecialistWorkflowVersion.version == IpSpecialistWorkflow.version),
        )
        .where(
            IpSpecialistWorkflow.company_id == context.company.id,
            IpSpecialistWorkflow.record_id == record.id,
        )
    )
    if cursor:
        statement = statement.where(IpSpecialistWorkflow.id > str(cursor))
    rows = session.execute(statement.order_by(IpSpecialistWorkflow.id).limit(limit + 1)).all()
    selected = rows[:limit]
    _read_sources(session, context, [r for _, r in selected])
    may_read = _may_read_confidential_rates(session, context=context)
    results = []
    for workflow, revision in selected:
        if not compare_digest(revision.facts_sha256, canonical_json_sha256(revision.facts_json)):
            raise _error(
                "specialist_workflow_integrity", "Retained workflow evidence requires repair."
            )
        results.append(
            _dto(workflow, revision, FACTS.validate_python(revision.facts_json), docket, may_read)
        )
    return WorkflowList(
        records=results, next_cursor=selected[-1][0].id if len(rows) > limit else None
    )


def _sources(session, context, record, facts, *, validate_cost=True):
    if isinstance(facts, SourceSet):
        allowed = {
            "design": {"representations", "instrument", "proceeding_evidence"},
            "copyright": {"deposit", "instrument", "proceeding_evidence"},
            "licensing": {"instrument", "proceeding_evidence"},
            "semiconductor_layout": {"layout_deposit", "instrument", "proceeding_evidence"},
        }
        if facts.purpose not in allowed[record.domain]:
            raise _error(
                "specialist_source_set_purpose", "Select a source-set purpose for this domain.", 422
            )
        pins = [m.source for m in facts.members]
        if facts.purpose == "layout_deposit" and facts.confidentiality != "restricted":
            raise _error(
                "layout_deposit_restricted",
                "Registry publication does not authorize disclosure of the layout deposit.",
            )
    else:
        source_set = _workflow(session, context, record, facts.source_set.id)
        if source_set.kind != "source_set" or source_set.version != facts.source_set.version:
            raise _error("specialist_source_set_stale", "Select the current source-set revision.")
        _, source_facts = _revision(session, context, source_set)
        expected = {
            "design_application": "representations",
            "copyright_registration": "deposit",
            "layout_application": "layout_deposit",
            "licence": "instrument",
            "rights_claim": "instrument",
            "proceeding": "proceeding_evidence",
        }
        if source_facts.purpose != expected[facts.kind]:
            raise _error(
                "specialist_source_set_purpose",
                "This workflow requires a different source-set purpose.",
                422,
            )
        if (
            isinstance(facts, DesignApplication)
            and facts.publication == "published"
            and source_facts.confidentiality != "publication_authorized"
        ):
            raise _error(
                "design_publication_instruction",
                "Retain explicit publication instructions with the representation set.",
            )
        pins = [m.source for m in source_facts.members]
    if isinstance(facts, DesignApplication) and facts.variant_basis:
        pins.append(facts.variant_basis)
    if isinstance(facts, Licence):
        pins.extend(i.source for i in facts.issues)
    if isinstance(facts, LayoutApplication):
        if facts.registry_source:
            if any(
                (pin.document_version_id, pin.locator)
                == (facts.registry_source.document_version_id, facts.registry_source.locator)
                for pin in pins
            ):
                raise _error(
                    "layout_registry_evidence",
                    "Retain distinct registry publication evidence, "
                    "not the layout deposit locator.",
                )
            pins.append(facts.registry_source)
        if validate_cost:
            _active_cost(session, context, record.docket_id, facts.cost_item_id)
    for pin in sorted(pins, key=lambda p: (str(p.document_id), str(p.document_version_id))):
        _source(session, context, record, pin, write=True)
    return pins


def _reviewer(session, context):
    if not membership_has_capability(session, context.membership, "ip:approve"):
        raise _error("specialist_review_permission", "The IP review capability is required.", 403)


def _validate_transition(session, context, record, workflow, old, facts):
    if old is not None and old.kind != facts.kind:
        raise _error("specialist_workflow_identity", "A workflow's kind cannot change.")
    if isinstance(facts, SourceSet):
        if old and old.purpose != facts.purpose:
            raise _error("specialist_workflow_identity", "A source set's purpose cannot change.")
    elif isinstance(facts, (DesignApplication, CopyrightRegistration, LayoutApplication)):
        transitions = (
            LAYOUT_TRANSITIONS
            if isinstance(facts, LayoutApplication)
            else DESIGN_TRANSITIONS
            if isinstance(facts, DesignApplication)
            else COPYRIGHT_TRANSITIONS
        )
        if old is None and facts.stage != "prepared":
            raise _error(
                "specialist_application_start",
                "Prepare the source-backed application before recording filing.",
            )
        if old and facts.stage != old.stage and facts.stage not in transitions[old.stage]:
            raise _error(
                "specialist_application_transition", "This application transition is not available."
            )
        if old and (facts.registry, facts.jurisdiction) != (old.registry, old.jurisdiction):
            raise _error(
                "specialist_application_identity",
                "Create a separate application for a different registry or jurisdiction.",
            )
        if isinstance(facts, LayoutApplication):
            if old and old.cost_item_id and not facts.cost_item_id:
                raise _error(
                    "layout_cost_replacement",
                    "Select an explicit active replacement for the retained cost reference.",
                )
            if old and old.stage in {"refused", "withdrawn"}:
                raise _error(
                    "layout_application_terminal",
                    "Retain the terminal application; create a separate later application.",
                )
            if facts.stage in {"refused", "withdrawn"}:
                open_work = session.scalar(
                    select(IpRelatedRightObligation.id)
                    .join(
                        IpSpecialistObligationLink,
                        (IpSpecialistObligationLink.obligation_id == IpRelatedRightObligation.id)
                        & (
                            IpSpecialistObligationLink.company_id
                            == IpRelatedRightObligation.company_id
                        )
                        & (
                            IpSpecialistObligationLink.docket_id
                            == IpRelatedRightObligation.docket_id
                        ),
                    )
                    .where(
                        IpSpecialistObligationLink.company_id == context.company.id,
                        IpSpecialistObligationLink.workflow_id == workflow.id,
                        IpRelatedRightObligation.status == "open",
                    )
                    .limit(1)
                )
                if open_work:
                    raise _error(
                        "layout_open_work",
                        "Complete or cancel the application's open work "
                        "before recording refusal or withdrawal.",
                    )
        if isinstance(facts, DesignApplication) and facts.variant_of:
            parent = _workflow(session, context, record, facts.variant_of)
            if parent.kind != "design_application" or parent.id == workflow.id:
                raise _error(
                    "design_variant_parent",
                    "Select a distinct design application as the variant parent.",
                )
            _, parent_facts = _revision(session, context, parent)
            if (
                parent_facts.jurisdiction != facts.jurisdiction
                or parent_facts.variant_of is not None
            ):
                raise _error(
                    "design_variant_basis",
                    "Use a root application in this jurisdiction "
                    "and retain the applicable source basis.",
                )
    elif isinstance(facts, RightsClaim):
        if facts.review in {"supported", "rejected"}:
            _reviewer(session, context)
        if old and (facts.claimant, facts.interest, facts.predecessor, facts.effective_from) != (
            old.claimant,
            old.interest,
            old.predecessor,
            old.effective_from,
        ):
            raise _error(
                "specialist_claim_identity",
                "Create a successor claim to change the party, interest or start period.",
            )
        if facts.predecessor:
            prior = _workflow(session, context, record, facts.predecessor)
            _, prior_facts = _revision(session, context, prior)
            if (
                prior.kind != "rights_claim"
                or prior.id == workflow.id
                or prior_facts.review != "supported"
            ):
                raise _error(
                    "specialist_rights_chain", "Select a distinct reviewed predecessor claim."
                )
            if facts.effective_from < prior_facts.effective_from:
                raise _error(
                    "specialist_rights_chain",
                    "The successor precedes the retained predecessor period.",
                )
        for claim_id in facts.competing_claims:
            other = _workflow(session, context, record, claim_id)
            if other.kind != "rights_claim" or other.id == workflow.id:
                raise _error("specialist_competing_claim", "Select a distinct rights claim.")
        if facts.competing_claims and facts.review == "unreviewed":
            raise _error(
                "specialist_competing_claim", "Mark competing claims unresolved pending review."
            )
    elif isinstance(facts, Licence):
        if facts.financial_terms_withheld:
            raise _error(
                "licence_redacted_write", "A redacted view cannot replace the retained instrument."
            )
        # Interpretation can itself contain financial clauses. Restrict complete instrument writes.
        if not _may_read_confidential_rates(session, context=context):
            raise _error(
                "licence_financial_permission",
                "The confidential financial-terms capability is required.",
                403,
            )
        if facts.interpretation == "reviewed":
            _reviewer(session, context)
        if old is None and facts.status != "draft":
            raise _error("licence_start", "Retain the draft instrument and extracted terms first.")
        if old and old.status == "terminated":
            raise _error(
                "licence_terminal",
                "The terminated instrument is retained; create a new grant for a later period.",
            )
        if old and old.status == "active":
            if facts.status == "draft" or any(
                getattr(old, f) != getattr(facts, f)
                for f in (
                    "grantor",
                    "grantee",
                    "transaction",
                    "effective_from",
                    "rights",
                    "territory",
                    "field_of_use",
                    "exclusivity",
                )
            ):
                raise _error(
                    "licence_period_immutable",
                    "Create a new effective-dated grant to change active rights or parties.",
                )
        if old and facts.status == "terminated" and old.status != "active":
            raise _error("licence_termination", "Only an active grant can be terminated.")
    elif isinstance(facts, SpecialistProceeding):
        allowed = {
            "design": {"design_cancellation", "court", "settlement"},
            "copyright": {"copyright_registry", "platform_takedown", "court", "settlement"},
            "licensing": {"court", "settlement"},
            "semiconductor_layout": LAYOUT_PROCEEDING_CHANNELS | {"court", "settlement"},
        }
        if facts.channel not in allowed[record.domain]:
            raise _error(
                "specialist_proceeding_channel", "Select a proceeding channel for this domain.", 422
            )
        if old and (facts.channel, facts.authority, facts.jurisdiction, facts.related_workflow) != (
            old.channel,
            old.authority,
            old.jurisdiction,
            old.related_workflow,
        ):
            raise _error(
                "specialist_proceeding_identity",
                "Start a separate proceeding for a different channel or target.",
            )
        if old and old.stage == "closed":
            raise _error(
                "specialist_proceeding_terminal",
                "Retain the closed proceeding; an appeal is a separate proceeding.",
            )
        if record.domain == "semiconductor_layout":
            if old is None and facts.stage != "opened":
                raise _error(
                    "layout_proceeding_start", "Open the separately sourced proceeding first."
                )
            if (
                old
                and facts.stage != old.stage
                and facts.stage not in LAYOUT_PROCEEDING_TRANSITIONS[old.stage]
            ):
                raise _error(
                    "layout_proceeding_transition", "This proceeding transition is not available."
                )
            if facts.stage in {"decision", "closed"} and facts.disposition == "pending":
                raise _error(
                    "layout_proceeding_outcome",
                    "Retain the source-reported outcome before decision or closure.",
                )
        if facts.related_workflow:
            target = _workflow(session, context, record, facts.related_workflow)
            if (
                target.id == workflow.id
                or (facts.channel == "design_cancellation" and target.kind != "design_application")
                or (
                    facts.channel in LAYOUT_PROCEEDING_CHANNELS
                    and target.kind != "layout_application"
                )
            ):
                raise _error(
                    "specialist_proceeding_target",
                    "Select the application or workflow under challenge.",
                )
            if facts.channel in LAYOUT_PROCEEDING_CHANNELS:
                _, target_facts = _revision(session, context, target)
                _sources(session, context, record, target_facts)


def _project_canonical(session, context, record, docket, workflow, facts):
    if isinstance(facts, SpecialistProceeding):
        proceeding = (
            session.get(IpProceeding, workflow.proceeding_id) if workflow.proceeding_id else None
        )
        if proceeding is None:
            proceeding = IpProceeding(
                company_id=context.company.id,
                docket_id=docket.id,
                proceeding_kind=facts.channel,
                side="applicant",
                office=facts.authority,
                jurisdiction=facts.jurisdiction,
                stage=facts.stage,
                origin_kind="manual_intake",
                stage_template_version=f"specialist-{facts.channel}-20260909",
                source_pending_identifier_allocation=False,
            )
            session.add(proceeding)
            session.flush()
            workflow.proceeding_id = proceeding.id
        else:
            if proceeding.company_id != context.company.id or proceeding.docket_id != docket.id:
                raise _error(
                    "specialist_canonical_integrity", "Proceeding ownership requires repair."
                )
            proceeding.stage = facts.stage
            proceeding.version += 1
    if isinstance(facts, RightsClaim) or (isinstance(facts, Licence) and facts.status != "draft"):
        interest = (
            session.get(IpTitleInterest, workflow.title_interest_id)
            if workflow.title_interest_id
            else None
        )
        is_claim = isinstance(facts, RightsClaim)
        until = facts.effective_until
        if isinstance(facts, Licence) and facts.termination_on:
            until = min(until, facts.termination_on) if until else facts.termination_on
        values = dict(
            interest_type=facts.interest if is_claim else facts.transaction,
            party_name=facts.claimant if is_claim else facts.grantee,
            party_role="claimant" if is_claim else "grantee",
            effective_from=facts.effective_from,
            effective_until=until,
            scope_json={
                "workflow_id": workflow.id,
                "domain": record.domain,
                "rights": facts.rights,
                "territory": facts.territory,
                "review": facts.review if is_claim else facts.interpretation,
            },
            evidence_reference=f"specialist:{workflow.id}:v{workflow.version}",
            recordal_status="not_determined" if is_claim else facts.recordal,
            registry_recorded_on=None if is_claim else facts.recordal_on,
            conflict_flags_json=["unresolved_claim"]
            if is_claim and facts.review in {"unreviewed", "unresolved"}
            else [],
        )
        if interest is None:
            interest = IpTitleInterest(company_id=context.company.id, docket_id=docket.id, **values)
            session.add(interest)
            session.flush()
            workflow.title_interest_id = interest.id
        else:
            if interest.company_id != context.company.id or interest.docket_id != docket.id:
                raise _error(
                    "specialist_canonical_integrity", "Title-interest ownership requires repair."
                )
            for key, value in values.items():
                setattr(interest, key, value)
            interest.version += 1


def save_workflow(session, *, context, record_id, payload, idempotency_key, workflow_id=None):
    record = _header(session, context, record_id)
    context = _writer(session, context, record.domain)
    docket = _docket(session, context, record, write=True)
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise _error("specialist_stale", "The parent lifecycle changed. Reload before saving.")
    if payload.facts.kind not in KINDS.get(record.domain, set()):
        raise _error(
            "specialist_workflow_domain", "This workflow is not enabled for this domain.", 422
        )
    scope = f"ip.specialist.workflow:{record.id}:{workflow_id or 'new'}"
    claim = _claim(session, context, scope, payload, idempotency_key)
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        result = get_workflow(
            session, context=context, record_id=record.id, workflow_id=claim.record.result_id
        )
        if result.version != payload.expected_version + 1:
            raise _error(
                "specialist_stale", "The saved workflow has advanced; reload its current version."
            )
        if record.domain == "semiconductor_layout":
            _sources(session, context, record, result.facts)
        session.commit()
        return result
    workflow = _workflow(session, context, record, workflow_id) if workflow_id else None
    if payload.expected_version != (workflow.version if workflow else 0):
        raise _error("specialist_stale", "The workflow changed. Reload before saving.")
    old = _revision(session, context, workflow)[1] if workflow else None
    if workflow is None:
        workflow = IpSpecialistWorkflow(
            company_id=context.company.id, record_id=record.id, kind=payload.facts.kind, version=1
        )
        session.add(workflow)
        session.flush()
    else:
        workflow.version += 1
    facts = payload.facts
    _validate_transition(session, context, record, workflow, old, facts)
    pins = _sources(session, context, record, facts)
    _project_canonical(session, context, record, docket, workflow, facts)
    data = facts.model_dump(mode="json")
    revision = IpSpecialistWorkflowVersion(
        company_id=context.company.id,
        workflow_id=workflow.id,
        version=workflow.version,
        facts_json=data,
        facts_sha256=canonical_json_sha256(data),
        actor_id=context.membership.id,
        reason=payload.reason,
    )
    session.add(revision)
    session.flush()
    for ordinal, source in enumerate(pins):
        session.add(
            IpSpecialistWorkflowSource(
                company_id=context.company.id,
                revision_id=revision.id,
                ordinal=ordinal,
                document_id=str(source.document_id),
                document_version_id=str(source.document_version_id),
                content_sha256=source.content_sha256,
                locator=source.locator,
            )
        )
    propagate_private_projection_change(
        session,
        company_id=context.company.id,
        actor_membership_id=context.membership.id,
        idempotency_key=f"specialist-workflow:{workflow.id}:{workflow.version}",
        event_type="source_changed",
        target_type="ip_docket",
        target_id=docket.id,
        target_version=private_source_version(docket),
        reason_code="ip_specialist_workflow_changed",
    )
    record_from_context(
        session,
        context,
        action="ip_specialist.workflow_version_recorded",
        target_type="ip_specialist_workflow",
        target_id=workflow.id,
        ip_docket_id=docket.id,
        metadata={"kind": workflow.kind, "version": workflow.version, "source_count": len(pins)},
    )
    _complete(session, context, claim, "ip_specialist_workflow", workflow.id)
    session.flush()
    result = get_workflow(session, context=context, record_id=record.id, workflow_id=workflow.id)
    session.commit()
    return result


def _active_cost(session, context, docket_id, cost_id):
    if cost_id is None:
        return
    cost = session.scalar(
        select(IpCostItem)
        .where(
            IpCostItem.id == str(cost_id),
            IpCostItem.company_id == context.company.id,
            IpCostItem.docket_id == str(docket_id),
        )
        .with_for_update()
    )
    correction = session.scalar(
        select(IpCostItemCorrection.id)
        .where(
            IpCostItemCorrection.company_id == context.company.id,
            IpCostItemCorrection.source_cost_item_id == str(cost_id),
        )
        .limit(1)
    )
    if cost is None or correction:
        raise _error("specialist_cost_inactive", "Select current cost evidence from this docket.")
    if cost.rate_confidential and not _may_read_confidential_rates(session, context=context):
        raise _error(
            "specialist_cost_permission", "This cost evidence requires financial access.", 403
        )


def cost_options(session, *, context, record_id, workflow_id, cursor=None):
    record = _header(session, context, record_id)
    docket = _docket(session, context, record)
    workflow = _workflow(session, context, record, workflow_id)
    if workflow.kind not in {"licence", "layout_application"}:
        raise _error(
            "specialist_obligation_contract", "Select a licensing instrument or layout application."
        )
    statement = select(IpCostItem.id, IpCostItem.description).where(
        IpCostItem.company_id == context.company.id,
        IpCostItem.docket_id == docket.id,
        active_ip_cost_predicate(),
    )
    if not _may_read_confidential_rates(session, context=context):
        statement = statement.where(IpCostItem.rate_confidential.is_(False))
    if cursor:
        statement = statement.where(IpCostItem.id > str(cursor))
    rows = session.execute(statement.order_by(IpCostItem.id).limit(11)).all()
    return {
        "records": [{"id": row.id, "description": row.description} for row in rows[:10]],
        "next_cursor": rows[9].id if len(rows) > 10 else None,
    }


def record_cost(
    session, *, context, record_id, workflow_id, payload, idempotency_key, cost_id=None
):
    record = _header(session, context, record_id)
    context = _writer(session, context, record.domain)
    docket = _docket(session, context, record, write=True)
    if not _may_read_confidential_rates(session, context=context):
        raise _error(
            "specialist_cost_permission",
            "Financial access is required to record cost evidence.",
            403,
        )
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise _error("specialist_stale", "The parent lifecycle changed.")
    workflow = _workflow(session, context, record, workflow_id)
    if workflow.kind not in {"licence", "layout_application"}:
        raise _error(
            "specialist_obligation_contract", "Select a licensing instrument or layout application."
        )
    if workflow.kind == "layout_application":
        _, layout = _revision(session, context, workflow)
        if layout.stage in {"refused", "withdrawn"}:
            raise _error(
                "layout_application_terminal",
                "The terminal layout application cannot record new cost commands.",
            )
        _sources(session, context, record, layout, validate_cost=False)
    _source(session, context, record, payload.source, write=True)
    claim = _claim(
        session,
        context,
        f"ip.specialist.cost:{workflow.id}:{cost_id or 'new'}",
        payload,
        idempotency_key,
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        saved = session.scalar(
            select(IpCostItem).where(
                IpCostItem.id == claim.record.result_id,
                IpCostItem.company_id == context.company.id,
                IpCostItem.docket_id == docket.id,
            )
        )
        if saved is None:
            raise _error("specialist_cost_inactive", "Retained cost evidence requires repair.")
        result = {"id": saved.id, "description": saved.description}
        session.commit()
        return result
    reference = f"{payload.source.document_version_id}:{payload.source.locator}"[:500]
    if cost_id is None:
        cost = _new_cost_item(
            context=context,
            docket=docket,
            payload=IpCostItemCreateRequest(
                category="other",
                description=payload.description,
                amount_minor=payload.amount_minor,
                currency=payload.currency,
                cost_nature=payload.cost_nature,
                billable=False,
                rate_confidential=True,
                evidence_reference=reference,
            ),
        )
        session.add(cost)
        session.flush()
        _apply_cost_reconciliation(session, context=context, cost=cost)
        action = "ip_cost_item.created"
    else:
        _active_cost(session, context, docket.id, cost_id)
        cost = session.get(IpCostItem, str(cost_id))
        session.add(
            IpCostItemCorrection(
                company_id=context.company.id,
                docket_id=docket.id,
                source_cost_item_id=cost.id,
                action="void",
                reason=payload.reason,
                evidence_reference=reference,
                created_by_membership_id=context.membership.id,
            )
        )
        action = "ip_cost_item.voided"
    record_from_context(
        session,
        context,
        action=action,
        target_type="ip_cost_item",
        target_id=cost.id,
        ip_docket_id=docket.id,
        metadata={
            "workflow_id": workflow.id,
            "source_version_id": str(payload.source.document_version_id),
        },
    )
    _complete(session, context, claim, "ip_cost_item", cost.id)
    session.flush()
    result = {"id": cost.id, "description": cost.description}
    session.commit()
    return result


def create_obligation(session, *, context, record_id, workflow_id, payload, idempotency_key):
    record = _header(session, context, record_id)
    context = _writer(session, context, record.domain)
    docket = _docket(session, context, record, write=True)
    workflow = _workflow(session, context, record, workflow_id)
    if (workflow.version, docket.lifecycle_version) != (
        payload.expected_version,
        payload.expected_lifecycle_version,
    ):
        raise _error("specialist_stale", "The contract or parent lifecycle changed.")
    _, facts = _revision(session, context, workflow)
    layout = isinstance(facts, LayoutApplication)
    if layout:
        if facts.stage in {"refused", "withdrawn"} or payload.kind not in LAYOUT_WORK_KINDS:
            raise _error(
                "layout_operational_work",
                "Select supported work on an operational layout application.",
            )
    elif (
        not isinstance(facts, Licence)
        or facts.status != "active"
        or payload.kind not in CONTRACT_WORK_KINDS
    ):
        raise _error("specialist_obligation_contract", "Select an active, reviewed contract.")
    _sources(session, context, record, facts)
    _source(session, context, record, payload.source, write=True)
    _active_cost(session, context, docket.id, payload.cost_item_id)
    claim = _claim(
        session, context, f"ip.specialist.obligation:{workflow.id}", payload, idempotency_key
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        result = get_obligation(
            session,
            context=context,
            record_id=record.id,
            workflow_id=workflow.id,
            obligation_id=claim.record.result_id,
        )
        session.commit()
        return result
    owner = context.membership.id
    task = create_ip_shared_task(
        session,
        context=context,
        commit=False,
        payload=IpSharedTaskCreateRequest(
            docket_id=docket.id,
            title=payload.title,
            due_on=payload.due_on_as_supplied,
            owner_membership_id=owner,
            description="Source-reported layout work; not a statutory deadline."
            if layout
            else "Source-reported contractual obligation; not a statutory deadline.",
        ),
    )
    deadline = create_ip_operational_deadline(
        session,
        context=context,
        commit=False,
        payload=IpOperationalDeadlineCreateRequest(
            docket_id=docket.id,
            title=payload.title,
            due_on=payload.due_on_as_supplied,
            kind=f"layout_{payload.kind}" if layout else f"contract_{payload.kind}",
            source="custom",
            assignee_membership_id=owner,
            notes="Source-reported layout date; no legal deadline calculation."
            if layout
            else "Source-reported contractual date; no legal deadline calculation.",
        ),
    )
    obligation = IpRelatedRightObligation(
        company_id=context.company.id,
        docket_id=docket.id,
        title_interest_id=workflow.title_interest_id,
        obligation_type=payload.kind,
        title=payload.title,
        due_on=payload.due_on_as_supplied,
        owner_membership_id=owner,
        matter_deadline_id=deadline.id,
        status="open",
        evidence_reference=f"specialist:{workflow.id}:v{workflow.version}",
    )
    session.add(obligation)
    session.flush()
    session.add(
        IpSpecialistObligationLink(
            obligation_id=obligation.id,
            docket_id=docket.id,
            company_id=context.company.id,
            workflow_id=workflow.id,
            task_id=task.id,
            document_id=str(payload.source.document_id),
            document_version_id=str(payload.source.document_version_id),
            content_sha256=payload.source.content_sha256,
            locator=payload.source.locator,
            cost_item_id=str(payload.cost_item_id) if payload.cost_item_id else None,
        )
    )
    _complete(session, context, claim, "ip_specialist_obligation", obligation.id)
    session.flush()
    result = get_obligation(
        session,
        context=context,
        record_id=record.id,
        workflow_id=workflow.id,
        obligation_id=obligation.id,
    )
    session.commit()
    return result


def get_obligation(session, *, context, record_id, workflow_id, obligation_id):
    record = _header(session, context, record_id)
    _docket(session, context, record)
    _workflow(session, context, record, workflow_id)
    link = session.scalar(
        select(IpSpecialistObligationLink).where(
            IpSpecialistObligationLink.company_id == context.company.id,
            IpSpecialistObligationLink.workflow_id == str(workflow_id),
            IpSpecialistObligationLink.obligation_id == str(obligation_id),
        )
    )
    obligation = session.get(IpRelatedRightObligation, str(obligation_id)) if link else None
    if (
        obligation is None
        or obligation.company_id != context.company.id
        or obligation.docket_id != record.docket_id
    ):
        raise _error("specialist_obligation_missing", "Contract obligation not found.", 404)
    source = SpecialistSource(
        document_id=link.document_id,
        document_version_id=link.document_version_id,
        content_sha256=link.content_sha256,
        locator=link.locator,
    )
    _source(session, context, record, source, write=False)
    return ContractObligationRecord(
        id=obligation.id,
        task_id=link.task_id,
        deadline_id=obligation.matter_deadline_id,
        due_on=obligation.due_on,
        kind=obligation.obligation_type,
        title=obligation.title,
        status=obligation.status,
        source=source,
        cost_item_id=link.cost_item_id,
    )


def list_obligations(session, *, context, record_id, workflow_id, cursor=None):
    record = _header(session, context, record_id)
    _docket(session, context, record)
    _workflow(session, context, record, workflow_id)
    query = select(IpSpecialistObligationLink.obligation_id).where(
        IpSpecialistObligationLink.company_id == context.company.id,
        IpSpecialistObligationLink.workflow_id == str(workflow_id),
    )
    if cursor:
        query = query.where(IpSpecialistObligationLink.obligation_id > str(cursor))
    ids = list(session.scalars(query.order_by(IpSpecialistObligationLink.obligation_id).limit(11)))
    return {
        "records": [
            get_obligation(
                session,
                context=context,
                record_id=record.id,
                workflow_id=str(workflow_id),
                obligation_id=oid,
            )
            for oid in ids[:10]
        ],
        "next_cursor": ids[9] if len(ids) > 10 else None,
    }


def _performance_dto(event):
    return ContractPerformanceRecord(
        id=event.id,
        obligation_id=event.obligation_id,
        action=event.action,
        occurred_on=event.occurred_on,
        account=event.account,
        source=SpecialistSource(
            document_id=event.document_id,
            document_version_id=event.document_version_id,
            content_sha256=event.content_sha256,
            locator=event.locator,
        ),
        cost_item_id=event.cost_item_id,
        recorded_at=event.created_at.replace(tzinfo=UTC)
        if event.created_at.tzinfo is None
        else event.created_at,
    )


def record_performance(
    session, *, context, record_id, workflow_id, obligation_id, payload, idempotency_key
):
    record = _header(session, context, record_id)
    context = _writer(session, context, record.domain)
    docket = _docket(session, context, record, write=True)
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise _error("specialist_stale", "The parent lifecycle changed.")
    workflow = _workflow(session, context, record, workflow_id)
    _, facts = _revision(session, context, workflow)
    if not isinstance(facts, (Licence, LayoutApplication)):
        raise _error(
            "specialist_obligation_contract", "Select a licensing instrument or layout application."
        )
    _sources(session, context, record, facts)
    current = get_obligation(
        session,
        context=context,
        record_id=record.id,
        workflow_id=workflow.id,
        obligation_id=obligation_id,
    )
    _source(session, context, record, payload.source, write=True)
    _source(session, context, record, current.source, write=True)
    cost_id = payload.replacement_cost_item_id or current.cost_item_id
    _active_cost(session, context, docket.id, cost_id)
    claim = _claim(
        session, context, f"ip.specialist.performance:{obligation_id}", payload, idempotency_key
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        event = session.scalar(
            select(IpSpecialistObligationEvent).where(
                IpSpecialistObligationEvent.id == claim.record.result_id,
                IpSpecialistObligationEvent.company_id == context.company.id,
                IpSpecialistObligationEvent.obligation_id == str(obligation_id),
            )
        )
        if event is None:
            raise _error(
                "specialist_performance_integrity", "Retained performance evidence requires repair."
            )
        result = _performance_dto(event)
        session.commit()
        return result
    obligation = session.scalar(
        select(IpRelatedRightObligation)
        .where(
            IpRelatedRightObligation.id == str(obligation_id),
            IpRelatedRightObligation.company_id == context.company.id,
            IpRelatedRightObligation.docket_id == docket.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if obligation.status != payload.expected_status:
        raise _error("specialist_obligation_stale", "This obligation is no longer open.")
    if payload.action == "notice_recorded" and obligation.obligation_type != "notice":
        raise _error("specialist_notice_kind", "Notice evidence belongs to a notice obligation.")
    # Shared owners retain their own lifecycle/assignment guards. Commit only after all
    # three canonical work records and the exact performance evidence are durable.
    if payload.action in {"complete", "cancel"}:
        update_ip_shared_task(
            session,
            context=context,
            task_id=str(current.task_id),
            commit=False,
            payload=IpSharedTaskUpdateRequest(
                docket_id=docket.id,
                status="completed" if payload.action == "complete" else "cancelled",
            ),
        )
        update_ip_operational_deadline(
            session,
            context=context,
            deadline_id=str(current.deadline_id),
            commit=False,
            payload=IpOperationalDeadlineUpdateRequest(
                docket_id=docket.id, status="done" if payload.action == "complete" else "cancelled"
            ),
        )
        obligation.status = "completed" if payload.action == "complete" else "cancelled"
        obligation.completed_at = datetime.now(UTC)
        obligation.completion_evidence_reference = (
            f"{payload.source.document_version_id}:{payload.source.locator}"[:500]
        )
    event = IpSpecialistObligationEvent(
        company_id=context.company.id,
        obligation_id=obligation.id,
        docket_id=docket.id,
        actor_id=context.membership.id,
        action=payload.action,
        occurred_on=payload.occurred_on,
        account=payload.account,
        document_id=str(payload.source.document_id),
        document_version_id=str(payload.source.document_version_id),
        content_sha256=payload.source.content_sha256,
        locator=payload.source.locator,
        cost_item_id=str(cost_id) if cost_id else None,
    )
    session.add(event)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_specialist.layout_performance_recorded"
        if isinstance(facts, LayoutApplication)
        else "ip_specialist.contract_performance_recorded",
        target_type="ip_specialist_obligation_event",
        target_id=event.id,
        ip_docket_id=docket.id,
        metadata={"obligation_id": obligation.id, "action": payload.action},
    )
    _complete(session, context, claim, "ip_specialist_obligation_event", event.id)
    result = _performance_dto(event)
    session.commit()
    return result


def performance_history(session, *, context, record_id, workflow_id, obligation_id, cursor=None):
    record = _header(session, context, record_id)
    get_obligation(
        session,
        context=context,
        record_id=record.id,
        workflow_id=workflow_id,
        obligation_id=obligation_id,
    )
    query = select(IpSpecialistObligationEvent).where(
        IpSpecialistObligationEvent.company_id == context.company.id,
        IpSpecialistObligationEvent.obligation_id == str(obligation_id),
    )
    if cursor:
        query = query.where(IpSpecialistObligationEvent.id > str(cursor))
    events = list(session.scalars(query.order_by(IpSpecialistObligationEvent.id).limit(11)))
    for event in events[:10]:
        _source(session, context, record, _performance_dto(event).source, write=False)
    return {
        "records": [_performance_dto(event) for event in events[:10]],
        "next_cursor": events[9].id if len(events) > 10 else None,
    }
