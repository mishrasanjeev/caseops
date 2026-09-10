"""One typed owner for specialist intake, not a legal-status or filing engine."""

from __future__ import annotations

from datetime import UTC
from hmac import compare_digest

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    Company,
    IpAsset,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
    IpSpecialistObservation,
    IpSpecialistRecord,
    IpSpecialistVersion,
)
from caseops_api.schemas.ip_specialist import (
    SpecialistContract,
    SpecialistCorrection,
    SpecialistFacts,
    SpecialistList,
    SpecialistObservation,
    SpecialistObservationList,
    SpecialistObservationRecord,
    SpecialistRecord,
    SpecialistSource,
    SpecialistSummary,
)
from caseops_api.services import ip_domain_catalog
from caseops_api.services.audit import record_from_context
from caseops_api.services.idempotency import (
    IdempotencyClaimOutcome,
    canonical_json_sha256,
    claim_idempotency,
    complete_idempotency,
)
from caseops_api.services.ip_document_workflow import get_accessible_ip_document_ids
from caseops_api.services.ip_lifecycle import (
    TERMINAL_IP_DOCKET_STATUSES,
    _authorized_lifecycle_docket,
)
from caseops_api.services.ip_operations import (
    _lock_ip_dockets_in_stable_order,
    _lock_ip_writer_context,
)
from caseops_api.services.ip_specialist_contracts import (
    CHILD_PRD_HASHES,
    FACT_MODELS,
    LABELS,
    OBSERVATION_KINDS,
    contract_fields,
    contract_path,
    contract_version,
)
from caseops_api.services.matter_access import (
    seed_restricted_ip_creator_access,
    visible_ip_dockets_filter,
)
from caseops_api.services.private_retrieval import (
    private_source_version,
    propagate_private_projection_change,
    propagate_private_source_creation,
)
from caseops_api.services.session_context import SessionContext


def _error(code: str, message: str, status: int = 409):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _registered(domain: str) -> bool:
    definition = ip_domain_catalog.DOMAIN_BY_ID.get(domain)
    return bool(
        definition
        and definition.contract_version == contract_version(domain)
        and definition.contract_path == contract_path(domain)
        and definition.child_prd_sha256 == CHILD_PRD_HASHES.get(domain)
    )


def contracts(session: Session) -> list[SpecialistContract]:
    decisions = {row.domain: row for row in ip_domain_catalog.domain_catalogue(session).domains}
    return [
        SpecialistContract(
            domain=domain,
            label=LABELS[domain],
            contract_version=contract_version(domain),
            contract_path=contract_path(domain),
            child_prd_sha256=CHILD_PRD_HASHES[domain],
            intake_available=bool(
                _registered(domain) and domain in decisions and decisions[domain].intake_available
            ),
            fields=contract_fields(domain),
            observation_kinds=list(OBSERVATION_KINDS[domain]),
            blockers=(decisions[domain].blockers if domain in decisions else ["unknown_domain"])
            + ([] if _registered(domain) else ["specialist_contract_unregistered"]),
        )
        for domain in FACT_MODELS
    ]


def _writer(session: Session, context: SessionContext, domain: str) -> SessionContext:
    # Tenant first: ACL/lifecycle writers and private-generation transitions use
    # this same tenant fence before taking any source-parent locks.
    session.scalar(select(Company).where(Company.id == context.company.id).with_for_update())
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    ip_domain_catalog.assert_domain_operation(domain, session=session)
    if not _registered(domain):
        raise _error(
            "specialist_contract_unregistered", "This domain's intake contract is not registered."
        )
    return context


def _header(session: Session, context: SessionContext, record_id: str) -> IpSpecialistRecord:
    row = session.scalar(
        select(IpSpecialistRecord)
        .where(
            IpSpecialistRecord.company_id == context.company.id,
            IpSpecialistRecord.id == record_id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _error("specialist_not_found", "Specialist record not found.", 404)
    _authorized_lifecycle_docket(
        session, context=context, docket_id=row.docket_id, for_update=False
    )
    return row


def _docket(session: Session, context: SessionContext, row: IpSpecialistRecord, *, write=False):
    docket = (
        _lock_ip_dockets_in_stable_order(
            session, context=context, docket_ids={row.docket_id}, required_capability="ip:write"
        )[row.docket_id]
        if write
        else _authorized_lifecycle_docket(
            session, context=context, docket_id=row.docket_id, for_update=False
        )
    )
    if docket.record_type != f"{row.domain}_intake" or not docket.restricted:
        raise _error("specialist_integrity", "Specialist record access requires repair.")
    return docket


def _stale(docket: IpDocketRecord, version: int, lifecycle_version: int):
    if docket.current_version != version or docket.lifecycle_version != lifecycle_version:
        raise _error("specialist_stale", "The record changed. Reload before saving.")


def _append_facts(
    session: Session,
    context: SessionContext,
    row: IpSpecialistRecord,
    docket: IpDocketRecord,
    facts: SpecialistFacts,
    reason: str,
):
    data = facts.model_dump(mode="json")
    session.add(
        IpSpecialistVersion(
            company_id=context.company.id,
            record_id=row.id,
            version=docket.current_version,
            facts_json=data,
            facts_sha256=canonical_json_sha256(data),
            actor_id=context.membership.id,
            reason=reason,
        )
    )
    session.flush()


def get_record(
    session: Session, *, context: SessionContext, record_id: str, version: int | None = None
) -> SpecialistRecord:
    row = _header(session, context, record_id)
    docket = _docket(session, context, row)
    facts = session.scalar(
        select(IpSpecialistVersion).where(
            IpSpecialistVersion.company_id == context.company.id,
            IpSpecialistVersion.record_id == row.id,
            IpSpecialistVersion.version
            == (version if version is not None else docket.current_version),
        )
    )
    if facts is None:
        raise _error("specialist_version_missing", "Intake version not found.", 404)
    if not compare_digest(facts.facts_sha256, canonical_json_sha256(facts.facts_json)):
        raise _error("specialist_version_integrity", "Intake version integrity requires repair.")
    payload = SpecialistFacts.model_validate(facts.facts_json)
    if payload.details.domain != row.domain or str(payload.client_id) != row.client_id:
        raise _error("specialist_version_integrity", "Intake identity requires repair.")
    return SpecialistRecord(
        id=row.id,
        docket_id=docket.id,
        asset_id=row.asset_id,
        contract_version=row.contract_version,
        version=facts.version,
        lifecycle_version=docket.lifecycle_version,
        lifecycle_status=docket.status,
        is_active=docket.is_active,
        created_at=facts.created_at.replace(tzinfo=UTC)
        if facts.created_at.tzinfo is None
        else facts.created_at,
        facts=payload,
    )


def list_records(
    session: Session,
    *,
    context: SessionContext,
    domain: str,
    limit: int = 25,
    cursor: str | None = None,
    include_closed: bool = False,
):
    if domain not in FACT_MODELS or not 1 <= limit <= 50:
        raise _error("specialist_list_invalid", "Select a domain and a page size up to 50.", 422)
    statement = (
        select(
            IpSpecialistRecord.id,
            IpSpecialistRecord.domain,
            IpDocketRecord.title,
            IpDocketRecord.status,
            IpDocketRecord.current_version,
        )
        .join(
            IpDocketRecord,
            (IpDocketRecord.id == IpSpecialistRecord.docket_id)
            & (IpDocketRecord.company_id == IpSpecialistRecord.company_id),
        )
        .where(
            IpSpecialistRecord.company_id == context.company.id,
            IpSpecialistRecord.domain == domain,
            IpDocketRecord.record_type == f"{domain}_intake",
            IpDocketRecord.restricted,
            ~IpDocketRecord.archived_by_matter_disposal,
            visible_ip_dockets_filter(session, context=context),
        )
    )
    if not include_closed:
        statement = statement.where(
            IpDocketRecord.is_active, IpDocketRecord.status.notin_(TERMINAL_IP_DOCKET_STATUSES)
        )
    if cursor:
        statement = statement.where(IpSpecialistRecord.id > cursor)
    rows = session.execute(statement.order_by(IpSpecialistRecord.id).limit(limit + 1)).all()
    return SpecialistList(
        records=[
            SpecialistSummary(
                id=row.id,
                domain=row.domain,
                title=row.title,
                lifecycle_status=row.status,
                version=row.current_version,
            )
            for row in rows[:limit]
        ],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


def _claim(session: Session, context: SessionContext, operation: str, payload, key: str):
    claim = claim_idempotency(
        session,
        company_id=context.company.id,
        actor_scope=f"membership:{context.membership.id}",
        actor_membership_id=context.membership.id,
        http_method="POST",
        operation=operation,
        idempotency_key=key,
        request_hash=canonical_json_sha256(payload.model_dump(mode="json")),
    )
    if claim.outcome not in {IdempotencyClaimOutcome.CLAIMED, IdempotencyClaimOutcome.REPLAY}:
        raise _error(
            "specialist_idempotency_conflict",
            "This operation key has a different or pending request.",
        )
    return claim


def _complete(session: Session, context: SessionContext, claim, result_type: str, result_id: str):
    complete_idempotency(
        session,
        company_id=context.company.id,
        record_id=claim.record.id,
        claim_token=claim.claim_token,
        claim_generation=claim.claim_generation,
        response_status=201,
        result_type=result_type,
        result_id=result_id,
    )


def create_record(
    session: Session, *, context: SessionContext, payload: SpecialistFacts, idempotency_key: str
) -> SpecialistRecord:
    domain = payload.details.domain
    context = _writer(session, context, domain)
    claim = _claim(session, context, "ip.specialist.create", payload, idempotency_key)
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        if claim.record.result_type != "ip_specialist" or not claim.record.result_id:
            raise _error("specialist_replay_integrity", "The saved result requires repair.")
        row = _header(session, context, claim.record.result_id)
        docket = _docket(session, context, row, write=True)
        if docket.lifecycle_version != 0:
            raise _error("specialist_stale", "A lifecycle change retired this creation request.")
        result = get_record(session, context=context, record_id=row.id)
        session.commit()
        return result
    client = session.scalar(
        select(Client)
        .where(
            Client.id == str(payload.client_id),
            Client.company_id == context.company.id,
            Client.is_active,
        )
        .with_for_update(read=True, key_share=True)
    )
    if client is None:
        raise _error("specialist_client_missing", "Select an active client in this firm.", 404)
    docket = IpDocketRecord(
        company_id=context.company.id,
        record_type=f"{domain}_intake",
        title=payload.title,
        status="draft",
        restricted=True,
        current_version=1,
        created_by_membership_id=context.membership.id,
    )
    session.add(docket)
    session.flush()
    seed_restricted_ip_creator_access(session, context=context, docket=docket)
    asset = IpAsset(
        company_id=context.company.id,
        docket_id=docket.id,
        asset_kind=domain,
        jurisdiction="UNSPECIFIED",
        title=payload.title,
    )
    session.add(asset)
    session.flush()
    row = IpSpecialistRecord(
        company_id=context.company.id,
        docket_id=docket.id,
        asset_id=asset.id,
        client_id=client.id,
        domain=domain,
        contract_version=contract_version(domain),
    )
    session.add(row)
    session.flush()
    _append_facts(session, context, row, docket, payload, "Initial specialist intake.")
    record_from_context(
        session,
        context,
        action="ip_specialist.created",
        target_type="ip_specialist",
        target_id=row.id,
        ip_docket_id=docket.id,
        metadata={"domain": domain, "version": 1},
    )
    propagate_private_source_creation(
        session,
        company_id=context.company.id,
        actor_membership_id=context.membership.id,
        idempotency_key=f"ip-docket-created:{docket.id}",
        target_type="ip_docket",
        target_id=docket.id,
        target_version=private_source_version(docket),
        reason_code="ip_docket_created",
    )
    _complete(session, context, claim, "ip_specialist", row.id)
    result = get_record(session, context=context, record_id=row.id)
    session.commit()
    return result


def correct_record(
    session: Session, *, context: SessionContext, record_id: str, payload: SpecialistCorrection
):
    row = _header(session, context, record_id)
    context = _writer(session, context, row.domain)
    docket = _docket(session, context, row, write=True)
    _stale(docket, payload.expected_version, payload.expected_lifecycle_version)
    if payload.facts.details.domain != row.domain or str(payload.facts.client_id) != row.client_id:
        raise _error(
            "specialist_identity_immutable",
            "Domain and client changes require an independent record.",
        )
    docket.current_version += 1
    docket.title = payload.facts.title
    asset = session.scalar(
        select(IpAsset)
        .where(
            IpAsset.id == row.asset_id,
            IpAsset.company_id == context.company.id,
            IpAsset.docket_id == docket.id,
            IpAsset.asset_kind == row.domain,
        )
        .with_for_update()
    )
    if asset is None:
        raise _error("specialist_asset_missing", "The independent asset requires repair.")
    asset.title = payload.facts.title
    asset.version += 1
    _append_facts(session, context, row, docket, payload.facts, payload.reason)
    propagate_private_projection_change(
        session,
        company_id=context.company.id,
        actor_membership_id=context.membership.id,
        idempotency_key=f"ip-specialist-corrected:{row.id}:{docket.current_version}",
        event_type="source_changed",
        target_type="ip_docket",
        target_id=docket.id,
        target_version=private_source_version(docket),
        reason_code="ip_specialist_facts_corrected",
    )
    record_from_context(
        session,
        context,
        action="ip_specialist.corrected",
        target_type="ip_specialist",
        target_id=row.id,
        ip_docket_id=docket.id,
        metadata={"version": docket.current_version},
    )
    result = get_record(session, context=context, record_id=row.id)
    session.commit()
    return result


def _source(
    session: Session,
    context: SessionContext,
    row: IpSpecialistRecord,
    source: SpecialistSource,
    *,
    write: bool,
):
    document_stmt = select(IpDocument).where(
        IpDocument.id == str(source.document_id), IpDocument.company_id == context.company.id
    )
    document = session.scalar(document_stmt.with_for_update() if write else document_stmt)
    version_stmt = select(IpDocumentVersion).where(
        IpDocumentVersion.id == str(source.document_version_id),
        IpDocumentVersion.document_id == str(source.document_id),
        IpDocumentVersion.company_id == context.company.id,
    )
    version = session.scalar(version_stmt.with_for_update() if write else version_stmt)
    if document is None or version is None:
        raise _error("specialist_source_missing", "Source document version not found.", 404)
    links = session.scalars(
        select(IpDocumentLink)
        .where(
            IpDocumentLink.company_id == context.company.id,
            IpDocumentLink.document_id == document.id,
        )
        .limit(2)
    ).all()
    # A single owned source link keeps writes bounded and avoids taking arbitrary
    # parent locks after this record. Cross-record source reuse needs its own flow.
    if len(links) != 1 or links[0].target_type != "docket" or links[0].target_id != row.docket_id:
        raise _error(
            "specialist_source_scope", "Select evidence uploaded only to this specialist record."
        )
    if not compare_digest(version.sha256_hex, source.content_sha256):
        raise _error(
            "specialist_source_changed", "Source hash changed. Select the exact version again."
        )
    if write and version.state in {"rejected", "superseded"}:
        raise _error(
            "specialist_source_retired", "Select evidence that has not been rejected or superseded."
        )
    return version


def _observation(row: IpSpecialistObservation) -> SpecialistObservationRecord:
    return SpecialistObservationRecord(
        id=row.id,
        sequence=row.sequence,
        kind=row.kind,
        occurred_on=row.occurred_on,
        account=row.account,
        source=SpecialistSource(
            document_id=row.source_document_id,
            document_version_id=row.source_version_id,
            content_sha256=row.source_sha256,
            locator=row.locator,
        ),
        supersedes_id=row.supersedes_id,
        recorded_at=row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
    )


def list_observations(
    session: Session,
    *,
    context: SessionContext,
    record_id: str,
    limit: int = 25,
    cursor: int | None = None,
):
    row = _header(session, context, record_id)
    _docket(session, context, row)
    if not 1 <= limit <= 50 or (cursor is not None and cursor < 1):
        raise _error("specialist_history_page", "Select a valid history page.", 422)
    statement = select(IpSpecialistObservation).where(
        IpSpecialistObservation.company_id == context.company.id,
        IpSpecialistObservation.record_id == row.id,
    )
    if cursor is not None:
        statement = statement.where(IpSpecialistObservation.sequence < cursor)
    rows = list(
        session.scalars(
            statement.order_by(IpSpecialistObservation.sequence.desc()).limit(limit + 1)
        )
    )
    selected = rows[:limit]
    ids = {item.source_document_id for item in selected}
    # Bound retained link work before the shared all-linked-target authorization.
    link_count = (
        len(
            session.scalars(
                select(IpDocumentLink.id)
                .where(
                    IpDocumentLink.company_id == context.company.id,
                    IpDocumentLink.document_id.in_(ids),
                )
                .limit(101)
            ).all()
        )
        if ids
        else 0
    )
    if link_count > 100:
        raise _error(
            "specialist_source_link_limit", "This evidence page exceeds the source-link budget."
        )
    accessible = (
        get_accessible_ip_document_ids(session, context=context, document_ids=ids) if ids else set()
    )
    versions = (
        {
            v.id: v
            for v in session.scalars(
                select(IpDocumentVersion).where(
                    IpDocumentVersion.company_id == context.company.id,
                    IpDocumentVersion.id.in_([item.source_version_id for item in selected]),
                )
            )
        }
        if selected
        else {}
    )
    for item in selected:
        version = versions.get(item.source_version_id)
        if item.source_document_id not in accessible or version is None:
            raise _error(
                "specialist_source_unavailable", "A retained source is no longer accessible.", 404
            )
        if version.document_id != item.source_document_id or not compare_digest(
            version.sha256_hex, item.source_sha256
        ):
            raise _error(
                "specialist_source_changed", "A retained source requires integrity repair."
            )
    return SpecialistObservationList(
        observations=[_observation(item) for item in selected],
        next_cursor=selected[-1].sequence if len(rows) > limit else None,
    )


def add_observation(
    session: Session,
    *,
    context: SessionContext,
    record_id: str,
    payload: SpecialistObservation,
    idempotency_key: str,
):
    row = _header(session, context, record_id)
    context = _writer(session, context, row.domain)
    docket = _docket(session, context, row, write=True)
    if payload.kind not in OBSERVATION_KINDS[row.domain]:
        raise _error(
            "specialist_observation_kind", "Select an observation type for this domain.", 422
        )
    claim = _claim(
        session, context, f"ip.specialist.observation:{row.id}", payload, idempotency_key
    )
    _source(session, context, row, payload.source, write=True)
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        # Replay is bound to the same current lifecycle, even after reopening.
        if docket.lifecycle_version != payload.expected_lifecycle_version:
            raise _error("specialist_stale", "The record lifecycle changed. Reload before saving.")
        retained = session.scalar(
            select(IpSpecialistObservation).where(
                IpSpecialistObservation.id == claim.record.result_id,
                IpSpecialistObservation.company_id == context.company.id,
                IpSpecialistObservation.record_id == row.id,
            )
        )
        if retained is None or claim.record.result_type != "ip_specialist_observation":
            raise _error("specialist_replay_integrity", "The saved observation requires repair.")
        result = _observation(retained)
        session.commit()
        return result
    _stale(docket, payload.expected_version, payload.expected_lifecycle_version)
    if payload.supersedes_id:
        prior = session.scalar(
            select(IpSpecialistObservation).where(
                IpSpecialistObservation.id == str(payload.supersedes_id),
                IpSpecialistObservation.record_id == row.id,
                IpSpecialistObservation.company_id == context.company.id,
            )
        )
        successor = session.scalar(
            select(IpSpecialistObservation.id)
            .where(
                IpSpecialistObservation.supersedes_id == str(payload.supersedes_id),
                IpSpecialistObservation.company_id == context.company.id,
            )
            .limit(1)
        )
        if prior is None or prior.kind != payload.kind or successor is not None:
            raise _error(
                "specialist_supersession_invalid",
                "Select the current observation of the same type.",
            )
    session.refresh(row)
    row.observation_sequence += 1
    observation = IpSpecialistObservation(
        company_id=context.company.id,
        record_id=row.id,
        sequence=row.observation_sequence,
        kind=payload.kind,
        occurred_on=payload.occurred_on,
        account=payload.account,
        source_version_id=str(payload.source.document_version_id),
        source_document_id=str(payload.source.document_id),
        source_sha256=payload.source.content_sha256,
        locator=payload.source.locator,
        supersedes_id=str(payload.supersedes_id) if payload.supersedes_id else None,
        actor_id=context.membership.id,
    )
    session.add(observation)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_specialist.observation_recorded",
        target_type="ip_specialist",
        target_id=row.id,
        ip_docket_id=docket.id,
        metadata={
            "observation_id": observation.id,
            "sequence": observation.sequence,
            "kind": observation.kind,
            "legal_effect": "not_determined",
        },
    )
    _complete(session, context, claim, "ip_specialist_observation", observation.id)
    result = _observation(observation)
    session.commit()
    return result
