"""Restricted disclosure intake; no patent prosecution or legal-rule activation."""

from __future__ import annotations

from datetime import UTC, datetime
from hmac import compare_digest
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    IpAsset,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
    IpPatentFamily,
    IpPatentFamilyVersion,
)
from caseops_api.schemas.ip_documents import IpDocumentLinkTarget
from caseops_api.schemas.ip_patents import (
    PatentDocumentSource,
    PatentFamilyCorrectionRequest,
    PatentFamilyCreateRequest,
    PatentFamilyFacts,
    PatentFamilyLifecycleEvent,
    PatentFamilyLifecycleHistory,
    PatentFamilyListResponse,
    PatentFamilyRecord,
    PatentSourcePin,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.idempotency import (
    IdempotencyClaimOutcome,
    canonical_json_sha256,
    claim_idempotency,
    complete_idempotency,
)
from caseops_api.services.ip_document_workflow import (
    _create_link,
    _propagate_private_document_change,
    _require_document_capability,
    _target_docket_id,
    get_accessible_ip_document_ids,
)
from caseops_api.services.ip_lifecycle import (
    TERMINAL_IP_DOCKET_STATUSES,
    _authorized_lifecycle_docket,
)
from caseops_api.services.ip_operations import (
    _docket_or_404,
    _lock_ip_dockets_in_stable_order,
    _lock_ip_writer_context,
)
from caseops_api.services.matter_access import (
    seed_restricted_ip_creator_access,
    visible_ip_dockets_filter,
)
from caseops_api.services.private_retrieval import (
    private_source_version,
    propagate_private_source_creation,
)
from caseops_api.services.session_context import SessionContext


def _error(code: str, message: str, status: int = 409) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _source_version(
    session: Session,
    context: SessionContext,
    source: PatentSourcePin | None,
) -> IpDocumentVersion | None:
    if source is None:
        return None
    if not isinstance(source, PatentDocumentSource):
        raise _error(
            "patent_registry_source_unavailable",
            "Patent registry observation is not enabled. Use an uploaded source document.",
        )
    version = session.scalar(
        select(IpDocumentVersion).where(
            IpDocumentVersion.id == str(source.document_version_id),
            IpDocumentVersion.document_id == str(source.document_id),
            IpDocumentVersion.company_id == context.company.id,
        )
    )
    if version is None:
        raise _error("patent_source_not_found", "Source document version not found.", 404)
    if version.document_id not in get_accessible_ip_document_ids(
        session,
        context=context,
        document_ids={version.document_id},
    ):
        raise _error("patent_source_not_found", "Source document version not found.", 404)
    if not compare_digest(version.sha256_hex, source.content_sha256):
        raise _error("patent_source_changed", "The source hash changed. Select the source again.")
    return version


def _source_parents(
    session: Session,
    context: SessionContext,
    version: IpDocumentVersion | None,
) -> set[str]:
    if version is None:
        return set()
    links = list(
        session.scalars(
            select(IpDocumentLink)
            .where(
                IpDocumentLink.company_id == context.company.id,
                IpDocumentLink.document_id == version.document_id,
            )
            .order_by(IpDocumentLink.id)
            .limit(101)
        )
    )
    if len(links) > 100:
        raise _error("patent_source_link_limit", "Select a source with at most 100 record links.")
    return {
        _target_docket_id(
            session,
            company_id=context.company.id,
            target=IpDocumentLinkTarget(target_type=row.target_type, target_id=row.target_id),
        )
        for row in links
    }


def _lock_source_and_dockets(
    session: Session,
    context: SessionContext,
    source: PatentSourcePin | None,
    docket_ids: set[str],
) -> dict[str, IpDocketRecord]:
    return _lock_sources_and_dockets(session, context, [source] if source else [], docket_ids)


def _lock_sources_and_dockets(
    session: Session,
    context: SessionContext,
    sources: list[PatentSourcePin],
    docket_ids: set[str],
    *,
    read_only_reference_docket_ids: frozenset[str] = frozenset(),
) -> dict[str, IpDocketRecord]:
    if len(sources) > 21:
        raise _error("patent_source_limit", "An application may pin at most 21 sources.", 422)
    versions = {}
    for source in sources:
        version = _source_version(session, context, source)
        assert version is not None
        versions[version.id] = version
    source_parents = (
        set().union(*(_source_parents(session, context, version) for version in versions.values()))
        if versions
        else set()
    )
    reference_parents = source_parents | set(read_only_reference_docket_ids)
    if len(reference_parents | docket_ids) > 100:
        raise _error("patent_source_link_limit", "Select sources linked to at most 100 records.")
    dockets = _lock_ip_dockets_in_stable_order(
        session,
        context=context,
        docket_ids=docket_ids | reference_parents,
        required_capability="ip:write",
        read_only_patent_source_docket_ids=frozenset(reference_parents - docket_ids),
    )
    for document_id in sorted({version.document_id for version in versions.values()}):
        session.scalar(
            select(IpDocument)
            .where(
                IpDocument.company_id == context.company.id,
                IpDocument.id == document_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    for version_id in sorted(versions):
        session.scalar(
            select(IpDocumentVersion)
            .where(
                IpDocumentVersion.company_id == context.company.id,
                IpDocumentVersion.id == version_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    fresh_parents = (
        set().union(*(_source_parents(session, context, version) for version in versions.values()))
        if versions
        else set()
    )
    if fresh_parents != source_parents:
        raise _error("patent_source_links_changed", "Source access changed. Reload and retry.")
    for source in sources:
        _source_version(session, context, source)
    return dockets


def _client(session: Session, context: SessionContext, client_id: UUID) -> Client:
    row = session.scalar(
        select(Client)
        .where(
            Client.company_id == context.company.id,
            Client.id == str(client_id),
            Client.is_active,
        )
        .with_for_update(read=True, key_share=True)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _error("patent_client_not_found", "Select an active client in this firm.", 404)
    return row


def _link_disclosure_source(
    session: Session,
    context: SessionContext,
    docket: IpDocketRecord,
    source: PatentSourcePin | None,
) -> None:
    if source is None:
        return
    assert isinstance(source, PatentDocumentSource)
    existing = session.scalar(
        select(IpDocumentLink.id).where(
            IpDocumentLink.company_id == context.company.id,
            IpDocumentLink.document_id == str(source.document_id),
            IpDocumentLink.target_type == "docket",
            IpDocumentLink.target_id == docket.id,
        )
    )
    if existing is not None:
        return
    _require_document_capability(session, context=context, capability="documents:manage")
    # The caller holds the document and all scope-parent locks. Retain the link
    # after later corrections so historical disclosure evidence stays restricted.
    document = session.get(IpDocument, str(source.document_id))
    assert document is not None and document.company_id == context.company.id
    link = _create_link(
        session,
        context=context,
        document=document,
        version_id=None,
        target=IpDocumentLinkTarget(target_type="docket", target_id=docket.id),
    )
    _propagate_private_document_change(
        session,
        context=context,
        document=document,
        event_type="access_changed",
        reason_code="patent_disclosure_source_linked",
        idempotency_key=f"patent-disclosure-source:{link.id}",
    )
    record_from_context(
        session,
        context,
        action="ip_document.links_added",
        target_type="ip_document",
        target_id=document.id,
        ip_docket_id=docket.id,
        metadata={"link_ids": [link.id], "version_id": str(source.document_version_id)},
    )


def _family(session: Session, context: SessionContext, family_id: str) -> IpPatentFamily:
    row = session.scalar(
        select(IpPatentFamily).where(
            IpPatentFamily.company_id == context.company.id,
            IpPatentFamily.id == family_id,
        )
    )
    if row is None:
        raise _error("patent_family_not_found", "Patent family not found.", 404)
    return row


def _version_source(version: IpPatentFamilyVersion) -> PatentDocumentSource | None:
    if version.source_registry_snapshot_id is not None:
        raise _error(
            "patent_registry_source_unavailable", "Patent registry observation is not enabled."
        )
    if version.source_document_version_id is None:
        return None
    return PatentDocumentSource(
        document_id=version.source_document_id,
        document_version_id=version.source_document_version_id,
        content_sha256=version.source_sha256,
    )


def _record(
    family: IpPatentFamily,
    docket: IpDocketRecord,
    version: IpPatentFamilyVersion,
) -> PatentFamilyRecord:
    def aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    return PatentFamilyRecord(
        id=family.id,
        docket_id=docket.id,
        asset_id=family.asset_id,
        version=version.version,
        lifecycle_version=docket.lifecycle_version,
        lifecycle_status=docket.status,
        is_active=docket.is_active,
        created_at=aware(docket.created_at),
        updated_at=aware(version.created_at),
        facts=PatentFamilyFacts(
            title=version.title,
            client_id=version.client_id,
            disclosure_date=version.disclosure_date,
            disclosure_narrative=version.disclosure_narrative,
            source=_version_source(version),
        ),
    )


def list_patent_family_lifecycle_history(
    session: Session,
    *,
    context: SessionContext,
    family_id: str,
    limit: int = 50,
    cursor: int | None = None,
) -> PatentFamilyLifecycleHistory:
    family = get_patent_family(session, context=context, family_id=family_id)
    return _patent_docket_lifecycle_history(
        session,
        context=context,
        docket_id=str(family.docket_id),
        limit=limit,
        cursor=cursor,
    )


def _patent_docket_lifecycle_history(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    limit: int = 50,
    cursor: int | None = None,
) -> PatentFamilyLifecycleHistory:
    """Read the canonical event page after the typed record owner authorizes it."""
    if not 1 <= limit <= 100 or (cursor is not None and cursor < 1):
        raise _error("patent_history_page_invalid", "Reload lifecycle history.", 422)
    statement = select(IpDocketEvent).where(
        IpDocketEvent.company_id == context.company.id,
        IpDocketEvent.docket_id == docket_id,
    )
    if cursor is not None:
        statement = statement.where(IpDocketEvent.sequence < cursor)
    # Page the indexed canonical sequence before filtering event kinds so future
    # prosecution traffic cannot turn a sparse history page into an unbounded scan.
    rows = list(session.scalars(statement.order_by(IpDocketEvent.sequence.desc()).limit(limit + 1)))
    return PatentFamilyLifecycleHistory(
        events=[
            PatentFamilyLifecycleEvent(
                id=row.id,
                sequence=row.sequence,
                from_status=row.before_phase,
                to_status=row.after_phase,
                effective_at=row.effective_at.replace(tzinfo=UTC)
                if row.effective_at.tzinfo is None
                else row.effective_at,
                entered_at=row.entered_at.replace(tzinfo=UTC)
                if row.entered_at.tzinfo is None
                else row.entered_at,
                reason=row.reason,
                evidence_refs=row.evidence_refs_json,
            )
            for row in rows[:limit]
            if row.event_kind == "lifecycle_transition"
        ],
        next_cursor=rows[limit - 1].sequence if len(rows) > limit else None,
    )


def get_patent_family(
    session: Session,
    *,
    context: SessionContext,
    family_id: str,
    version_number: int | None = None,
) -> PatentFamilyRecord:
    family = _family(session, context, family_id)
    docket = _authorized_lifecycle_docket(
        session, context=context, docket_id=family.docket_id, for_update=False
    )
    if docket.record_type != "patent_family" or not docket.restricted:
        raise _error(
            "patent_family_integrity", "Patent family access configuration requires repair."
        )
    version = session.scalar(
        select(IpPatentFamilyVersion).where(
            IpPatentFamilyVersion.company_id == context.company.id,
            IpPatentFamilyVersion.family_id == family.id,
            IpPatentFamilyVersion.version == (version_number or docket.current_version),
        )
    )
    if version is None:
        raise _error("patent_family_version_not_found", "Disclosure version not found.", 404)
    _source_version(session, context, _version_source(version))
    return _record(family, docket, version)


def list_patent_families(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 50,
    cursor: str | None = None,
    query: str | None = None,
    status_scope: Literal["active", "terminal", "all"] = "active",
) -> PatentFamilyListResponse:
    if not 1 <= limit <= 100:
        raise _error("patent_page_limit", "Page size must be between 1 and 100.", 422)
    if cursor is not None:
        try:
            cursor = str(UUID(cursor))
        except ValueError as exc:
            raise _error("patent_cursor_invalid", "Reload the family list.", 422) from exc
    if status_scope not in {"active", "terminal", "all"}:
        raise _error("patent_status_scope_invalid", "Select a valid lifecycle filter.", 422)
    lifecycle_filter = (
        IpDocketRecord.is_active & IpDocketRecord.status.notin_(TERMINAL_IP_DOCKET_STATUSES)
        if status_scope == "active"
        else ~IpDocketRecord.is_active & IpDocketRecord.status.in_(TERMINAL_IP_DOCKET_STATUSES)
        if status_scope == "terminal"
        else (
            (IpDocketRecord.is_active & IpDocketRecord.status.notin_(TERMINAL_IP_DOCKET_STATUSES))
            | (~IpDocketRecord.is_active & IpDocketRecord.status.in_(TERMINAL_IP_DOCKET_STATUSES))
        )
    )
    visible_docket = (
        select(IpDocketRecord.id)
        .where(
            IpDocketRecord.id == IpPatentFamily.docket_id,
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.record_type == "patent_family",
            IpDocketRecord.restricted,
            lifecycle_filter,
            ~IpDocketRecord.archived_by_matter_disposal,
            visible_ip_dockets_filter(session, context=context),
        )
        .correlate(IpPatentFamily)
        .limit(1)
    )
    if query:
        if len(query) > 200:
            raise _error("patent_query_limit", "Search text is too long.", 422)
        visible_docket = visible_docket.where(
            IpDocketRecord.title.icontains(query, autoescape=True)
        )
    # A scalar lookup cannot be flattened into a stale-statistics join that
    # repeatedly scans a whole imported tenant. Authorization still precedes LIMIT.
    statement = select(IpPatentFamily).where(
        IpPatentFamily.company_id == context.company.id,
        visible_docket.scalar_subquery().is_not(None),
    )
    if cursor:
        statement = statement.where(IpPatentFamily.id > cursor)
    rows = list(session.scalars(statement.order_by(IpPatentFamily.id).limit(limit + 1)))
    families = rows[:limit]
    dockets = (
        {
            docket.id: docket
            for docket in session.scalars(
                select(IpDocketRecord).where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.id.in_([family.docket_id for family in families]),
                    IpDocketRecord.record_type == "patent_family",
                    IpDocketRecord.restricted,
                    lifecycle_filter,
                    ~IpDocketRecord.archived_by_matter_disposal,
                    visible_ip_dockets_filter(session, context=context),
                )
            )
        }
        if families
        else {}
    )
    if len(dockets) != len(families):
        raise _error("patent_family_access_changed", "Family access changed. Reload the list.")
    admitted = [(family, dockets[family.docket_id]) for family in families]
    # Bound the history join before loading any disclosure content. Fresh imports
    # can have stale planner statistics; a LIMIT above a three-table join did not
    # bound the executor's intermediate work on PostgreSQL.
    versions = (
        {
            (row.family_id, row.version): row
            for row in session.scalars(
                select(IpPatentFamilyVersion).where(
                    IpPatentFamilyVersion.company_id == context.company.id,
                    tuple_(IpPatentFamilyVersion.family_id, IpPatentFamilyVersion.version).in_(
                        [(family.id, docket.current_version) for family, docket in admitted]
                    ),
                )
            )
        }
        if admitted
        else {}
    )
    if len(versions) != len(admitted):
        raise _error("patent_family_integrity", "A disclosure version requires repair.")
    page = [
        (family, docket, versions[(family.id, docket.current_version)])
        for family, docket in admitted
    ]
    source_ids = {v.source_document_version_id for _, _, v in page if v.source_document_version_id}
    documents = (
        {
            row.id: (row.document_id, row.sha256_hex)
            for row in session.execute(
                select(
                    IpDocumentVersion.id,
                    IpDocumentVersion.document_id,
                    IpDocumentVersion.sha256_hex,
                ).where(
                    IpDocumentVersion.company_id == context.company.id,
                    IpDocumentVersion.id.in_(source_ids),
                )
            )
        }
        if source_ids
        else {}
    )
    accessible = (
        get_accessible_ip_document_ids(
            session,
            context=context,
            document_ids={document_id for document_id, _ in documents.values()},
        )
        if documents
        else set()
    )
    results = [
        _record(family, docket, version)
        for family, docket, version in page
        if version.source_registry_snapshot_id is None
        and (
            version.source_document_version_id is None
            or (
                version.source_document_version_id in documents
                and documents[version.source_document_version_id][0] in accessible
                and compare_digest(
                    documents[version.source_document_version_id][1], version.source_sha256
                )
            )
        )
    ]
    return PatentFamilyListResponse(
        families=results,
        next_cursor=page[-1][0].id if len(rows) > limit else None,
    )


def _append_version(
    session: Session,
    context: SessionContext,
    family: IpPatentFamily,
    docket: IpDocketRecord,
    facts: PatentFamilyFacts,
    reason: str,
) -> None:
    source = facts.source
    if source is not None and not isinstance(source, PatentDocumentSource):
        raise _error(
            "patent_registry_source_unavailable", "Patent registry observation is not enabled."
        )
    session.add(
        IpPatentFamilyVersion(
            company_id=context.company.id,
            family_id=family.id,
            version=docket.current_version,
            client_id=str(facts.client_id),
            title=facts.title,
            disclosure_date=facts.disclosure_date,
            disclosure_narrative=facts.disclosure_narrative,
            source_document_id=str(source.document_id) if source else None,
            source_document_version_id=str(source.document_version_id) if source else None,
            source_sha256=source.content_sha256 if source else None,
            created_by_membership_id=context.membership.id,
            reason=reason,
        )
    )
    session.flush()


def create_patent_family(
    session: Session,
    *,
    context: SessionContext,
    payload: PatentFamilyCreateRequest,
    idempotency_key: str,
) -> PatentFamilyRecord:
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    claim = claim_idempotency(
        session,
        company_id=context.company.id,
        actor_scope=f"membership:{context.membership.id}",
        actor_membership_id=context.membership.id,
        http_method="POST",
        operation="ip.patent.family.create",
        idempotency_key=idempotency_key,
        request_hash=canonical_json_sha256(payload.model_dump(mode="json")),
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        if claim.record.result_type != "ip_patent_family" or not claim.record.result_id:
            raise _error("patent_replay_integrity", "The saved creation result cannot be resolved.")
        retained = _family(session, context, claim.record.result_id)
        _docket_or_404(session, context=context, docket_id=retained.docket_id)
        return get_patent_family(session, context=context, family_id=claim.record.result_id)
    if claim.outcome != IdempotencyClaimOutcome.CLAIMED:
        raise _error(
            "patent_creation_conflict", "This creation key is in use. Reload before retrying."
        )
    _client(session, context, payload.client_id)
    _lock_source_and_dockets(session, context, payload.source, set())
    docket = IpDocketRecord(
        company_id=context.company.id,
        record_type="patent_family",
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
        asset_kind="patent",
        jurisdiction="UNSPECIFIED",
        title=payload.title,
    )
    session.add(asset)
    session.flush()
    family = IpPatentFamily(
        company_id=context.company.id,
        docket_id=docket.id,
        asset_id=asset.id,
        client_id=str(payload.client_id),
    )
    session.add(family)
    session.flush()
    _link_disclosure_source(session, context, docket, payload.source)
    _append_version(session, context, family, docket, payload, "Initial inventor disclosure.")
    record_from_context(
        session,
        context,
        action="ip_patent_family.created",
        target_type="ip_patent_family",
        target_id=family.id,
        ip_docket_id=docket.id,
        metadata={
            "version": 1,
            "source_kind": payload.source.kind if payload.source else "user_entered",
        },
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
    complete_idempotency(
        session,
        company_id=context.company.id,
        record_id=claim.record.id,
        claim_token=claim.claim_token,
        claim_generation=claim.claim_generation,
        response_status=201,
        result_type="ip_patent_family",
        result_id=family.id,
    )
    result = get_patent_family(session, context=context, family_id=family.id)
    session.commit()
    return result


def correct_patent_family(
    session: Session,
    *,
    context: SessionContext,
    family_id: str,
    payload: PatentFamilyCorrectionRequest,
) -> PatentFamilyRecord:
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    family = _family(session, context, family_id)
    _client(session, context, payload.facts.client_id)
    dockets = _lock_source_and_dockets(session, context, payload.facts.source, {family.docket_id})
    docket = dockets[family.docket_id]
    if docket.record_type != "patent_family" or not docket.restricted:
        raise _error(
            "patent_family_integrity", "Patent family access configuration requires repair."
        )
    if (
        docket.current_version != payload.expected_version
        or docket.lifecycle_version != payload.expected_lifecycle_version
    ):
        raise _error("patent_family_stale", "This disclosure changed. Reload before correcting it.")
    # Client transfer is a separate title/access workflow, never a metadata correction.
    if str(payload.facts.client_id) != family.client_id:
        raise _error(
            "patent_client_transfer_required",
            "Client ownership cannot change in a disclosure correction.",
        )
    docket.current_version += 1
    docket.title = payload.facts.title
    asset = session.scalar(
        select(IpAsset)
        .where(
            IpAsset.id == family.asset_id,
            IpAsset.company_id == context.company.id,
            IpAsset.docket_id == docket.id,
            IpAsset.asset_kind == "patent",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if asset is None:
        raise _error("patent_family_integrity", "Patent family asset requires repair.")
    asset.title = payload.facts.title
    asset.version += 1
    _link_disclosure_source(session, context, docket, payload.facts.source)
    _append_version(session, context, family, docket, payload.facts, payload.reason)
    record_from_context(
        session,
        context,
        action="ip_patent_family.corrected",
        target_type="ip_patent_family",
        target_id=family.id,
        ip_docket_id=docket.id,
        metadata={"version": docket.current_version, "reason": payload.reason},
    )
    result = get_patent_family(session, context=context, family_id=family.id)
    session.commit()
    return result
