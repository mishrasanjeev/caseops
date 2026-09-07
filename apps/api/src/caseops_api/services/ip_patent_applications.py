"""Independent patent facts; no inferred prosecution, filing or legal deadlines."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpAsset,
    IpDocketRecord,
    IpDocumentVersion,
    IpPatentApplication,
    IpPatentApplicationIdentifier,
    IpPatentApplicationIdentity,
    IpPatentApplicationVersion,
)
from caseops_api.schemas.ip_patents import (
    PatentApplicationCorrectionRequest,
    PatentApplicationCreateRequest,
    PatentApplicationFacts,
    PatentApplicationListResponse,
    PatentApplicationRecord,
    PatentDocumentSource,
    PatentFamilyLifecycleHistory,
    PatentIdentifierFact,
    PatentSourcePin,
)
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
from caseops_api.services.ip_operations import _docket_or_404, _lock_ip_writer_context
from caseops_api.services.ip_patent_families import (
    _client,
    _error,
    _family,
    _link_disclosure_source,
    _lock_sources_and_dockets,
    _patent_docket_lifecycle_history,
    get_patent_family,
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


def _lock_application_identity_writer(session: Session, context: SessionContext) -> None:
    # Take this before actor, parent or document locks. It serializes identifier
    # swaps between unrelated families without locking another tenant's writers.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:resource, 0))"),
            {"resource": f"ip-patent-identities:{context.company.id}"},
        )


def _normalized(value: str, limit: int) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not normalized or len(normalized) > limit:
        raise _error(
            "patent_identifier_invalid", "The normalized identifier or office is too long.", 422
        )
    return normalized


def _identity_scope(
    facts: PatentApplicationFacts, identifier: PatentIdentifierFact
) -> dict[str, str]:
    return {
        "jurisdiction": facts.jurisdiction,
        "office_key": _normalized(facts.office, 320),
        "identifier_kind": identifier.identifier_kind,
        "value_key": _normalized(identifier.raw_value, 480),
    }


def _sources(facts: PatentApplicationFacts) -> list[PatentSourcePin]:
    return [facts.source, *(row.source for row in facts.identifiers)]


def _source_columns(source: PatentSourcePin) -> dict[str, str]:
    if not isinstance(source, PatentDocumentSource):
        raise _error(
            "patent_registry_source_unavailable", "Use an uploaded patent source document."
        )
    return {
        "source_document_id": str(source.document_id),
        "source_document_version_id": str(source.document_version_id),
        "source_sha256": source.content_sha256,
    }


def _source(
    row: IpPatentApplicationVersion | IpPatentApplicationIdentifier,
) -> PatentDocumentSource:
    return PatentDocumentSource(
        document_id=row.source_document_id,
        document_version_id=row.source_document_version_id,
        content_sha256=row.source_sha256,
    )


def _application(
    session: Session, context: SessionContext, application_id: str
) -> IpPatentApplication:
    row = session.scalar(
        select(IpPatentApplication).where(
            IpPatentApplication.company_id == context.company.id,
            IpPatentApplication.id == application_id,
        )
    )
    if row is None:
        raise _error("patent_application_not_found", "Patent application not found.", 404)
    return row


def _check_anchor(docket: IpDocketRecord) -> None:
    if docket.record_type != "patent_application" or not docket.restricted:
        raise _error(
            "patent_application_integrity", "Application access configuration requires repair."
        )


def _checked_source_ids(
    session: Session,
    context: SessionContext,
    sources: list[PatentDocumentSource],
) -> set[tuple[str, str, str]]:
    # A page contains at most 100 applications, each with one main and 20 identifier sources.
    if len(sources) > 2100:
        raise _error("patent_source_limit", "The application source page exceeds its bound.")
    version_ids = {str(pin.document_version_id) for pin in sources}
    rows = (
        list(
            session.execute(
                select(
                    IpDocumentVersion.id,
                    IpDocumentVersion.document_id,
                    IpDocumentVersion.sha256_hex,
                ).where(
                    IpDocumentVersion.company_id == context.company.id,
                    IpDocumentVersion.id.in_(version_ids),
                )
            )
        )
        if version_ids
        else []
    )
    accessible = (
        get_accessible_ip_document_ids(
            session,
            context=context,
            document_ids={row.document_id for row in rows},
        )
        if rows
        else set()
    )
    return {
        (row.id, row.document_id, row.sha256_hex) for row in rows if row.document_id in accessible
    }


def _source_key(source: PatentDocumentSource) -> tuple[str, str, str]:
    return str(source.document_version_id), str(source.document_id), source.content_sha256


def _records(
    session: Session,
    context: SessionContext,
    applications: list[IpPatentApplication],
    dockets: dict[str, IpDocketRecord],
    version_numbers: dict[str, int] | None = None,
) -> list[PatentApplicationRecord]:
    if not applications:
        return []
    if len(applications) > 100:
        raise _error("patent_page_limit", "Application pages contain at most 100 records.")
    keys = [
        (app.id, (version_numbers or {}).get(app.id, dockets[app.docket_id].current_version))
        for app in applications
    ]
    versions = {
        (row.application_id, row.version): row
        for row in session.scalars(
            select(IpPatentApplicationVersion).where(
                IpPatentApplicationVersion.company_id == context.company.id,
                tuple_(
                    IpPatentApplicationVersion.application_id, IpPatentApplicationVersion.version
                ).in_(keys),
            )
        )
    }
    if len(versions) != len(applications):
        raise _error("patent_application_version_not_found", "Application version not found.", 404)
    identifiers: dict[str, list[IpPatentApplicationIdentifier]] = {
        row.id: [] for row in versions.values()
    }
    identifier_rows = list(
        session.scalars(
            select(IpPatentApplicationIdentifier)
            .where(
                IpPatentApplicationIdentifier.company_id == context.company.id,
                IpPatentApplicationIdentifier.application_version_id.in_(identifiers),
            )
            .order_by(
                IpPatentApplicationIdentifier.application_version_id,
                IpPatentApplicationIdentifier.ordinal,
            )
            .limit(2001)
        )
    )
    if len(identifier_rows) > 2000:
        raise _error(
            "patent_identifier_integrity", "The identifier history exceeds its verified bound."
        )
    for row in identifier_rows:
        identifiers[row.application_version_id].append(row)
    sources = [_source(row) for row in [*versions.values(), *identifier_rows]]
    accessible = _checked_source_ids(session, context, sources)
    results = []
    for application, key in zip(applications, keys, strict=True):
        docket = dockets[application.docket_id]
        _check_anchor(docket)
        version = versions[key]
        rows = identifiers[version.id]
        if len(rows) > 20 or [row.ordinal for row in rows] != list(range(len(rows))):
            raise _error(
                "patent_identifier_integrity", "The identifier source sequence requires repair."
            )
        pins = [_source(version), *(_source(row) for row in rows)]
        if any(_source_key(pin) not in accessible for pin in pins):
            continue

        def aware(value: datetime) -> datetime:
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value

        results.append(
            PatentApplicationRecord(
                id=application.id,
                docket_id=docket.id,
                family_id=application.family_id,
                version=version.version,
                lifecycle_version=docket.lifecycle_version,
                lifecycle_status=docket.status,
                is_active=docket.is_active,
                prosecution_phase=application.prosecution_phase,
                created_at=aware(docket.created_at),
                updated_at=aware(version.created_at),
                facts=PatentApplicationFacts(
                    title=version.title,
                    application_kind=version.application_kind,
                    jurisdiction=version.jurisdiction,
                    office=version.office,
                    filing_date=version.filing_date,
                    publication_date=version.publication_date,
                    source_pending_identifier_allocation=version.source_pending_identifier_allocation,
                    source=_source(version),
                    identifiers=[
                        PatentIdentifierFact(
                            identifier_kind=row.identifier_kind,
                            raw_value=row.raw_value,
                            source=_source(row),
                        )
                        for row in rows
                    ],
                ),
            )
        )
    return results


def get_patent_application(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    version_number: int | None = None,
) -> PatentApplicationRecord:
    application = _application(session, context, application_id)
    docket = _authorized_lifecycle_docket(
        session, context=context, docket_id=application.docket_id, for_update=False
    )
    _check_anchor(docket)
    records = _records(
        session,
        context,
        [application],
        {docket.id: docket},
        {application.id: version_number} if version_number else None,
    )
    if not records:
        raise _error(
            "patent_source_not_found", "Application source evidence is not accessible.", 404
        )
    return records[0]


def list_patent_applications(
    session: Session,
    *,
    context: SessionContext,
    family_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    query: str | None = None,
    status_scope: Literal["active", "terminal", "all"] = "active",
) -> PatentApplicationListResponse:
    if not 1 <= limit <= 100 or status_scope not in {"active", "terminal", "all"}:
        raise _error("patent_page_invalid", "Select a valid page size and lifecycle filter.", 422)
    if family_id:
        get_patent_family(session, context=context, family_id=family_id)
    if cursor:
        try:
            cursor = str(UUID(cursor))
        except ValueError as exc:
            raise _error("patent_cursor_invalid", "Reload the application list.", 422) from exc
    active = IpDocketRecord.is_active & IpDocketRecord.status.notin_(TERMINAL_IP_DOCKET_STATUSES)
    terminal = ~IpDocketRecord.is_active & IpDocketRecord.status.in_(TERMINAL_IP_DOCKET_STATUSES)
    lifecycle = (
        active
        if status_scope == "active"
        else terminal
        if status_scope == "terminal"
        else active | terminal
    )
    filters = (
        IpDocketRecord.company_id == context.company.id,
        IpDocketRecord.record_type == "patent_application",
        IpDocketRecord.restricted,
        lifecycle,
        ~IpDocketRecord.archived_by_matter_disposal,
        visible_ip_dockets_filter(session, context=context),
    )
    visible = (
        select(IpDocketRecord.id)
        .where(
            IpDocketRecord.id == IpPatentApplication.docket_id,
            *filters,
        )
        .correlate(IpPatentApplication)
        .limit(1)
    )
    if query:
        if len(query) > 200:
            raise _error("patent_query_limit", "Search text is too long.", 422)
        exact_identifier = select(IpPatentApplicationIdentity.application_id).where(
            IpPatentApplicationIdentity.company_id == context.company.id,
            IpPatentApplicationIdentity.value_key == _normalized(query, 800),
        )
        visible = visible.where(
            or_(
                IpDocketRecord.title.icontains(query, autoescape=True),
                IpPatentApplication.id.in_(exact_identifier),
            )
        )
    statement = select(IpPatentApplication).where(
        IpPatentApplication.company_id == context.company.id,
        visible.scalar_subquery().is_not(None),
    )
    if family_id:
        statement = statement.where(IpPatentApplication.family_id == family_id)
    if cursor:
        statement = statement.where(IpPatentApplication.id > cursor)
    rows = list(session.scalars(statement.order_by(IpPatentApplication.id).limit(limit + 1)))
    page = rows[:limit]
    dockets = (
        {
            row.id: row
            for row in session.scalars(
                select(IpDocketRecord).where(
                    IpDocketRecord.id.in_([app.docket_id for app in page]),
                    *filters,
                )
            )
        }
        if page
        else {}
    )
    if len(page) != len(dockets):
        raise _error(
            "patent_application_access_changed", "Application access changed. Reload the list."
        )
    return PatentApplicationListResponse(
        applications=_records(session, context, page, dockets),
        next_cursor=page[-1].id if len(rows) > limit else None,
    )


def list_patent_application_lifecycle_history(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    limit: int = 50,
    cursor: int | None = None,
) -> PatentFamilyLifecycleHistory:
    application = get_patent_application(session, context=context, application_id=application_id)
    return _patent_docket_lifecycle_history(
        session,
        context=context,
        docket_id=str(application.docket_id),
        limit=limit,
        cursor=cursor,
    )


def _append_version(
    session: Session,
    context: SessionContext,
    application: IpPatentApplication,
    docket: IpDocketRecord,
    facts: PatentApplicationFacts,
    reason: str,
) -> IpPatentApplicationVersion:
    scopes = [_identity_scope(facts, row) for row in facts.identifiers]
    hashes = [canonical_json_sha256(scope) for scope in scopes]
    if len(set(hashes)) != len(hashes):
        raise _error(
            "patent_identifier_duplicate",
            "An identifier appears more than once after normalization.",
            422,
        )
    version = IpPatentApplicationVersion(
        company_id=context.company.id,
        application_id=application.id,
        version=docket.current_version,
        title=facts.title,
        application_kind=facts.application_kind,
        jurisdiction=facts.jurisdiction,
        office=facts.office,
        filing_date=facts.filing_date,
        publication_date=facts.publication_date,
        source_pending_identifier_allocation=facts.source_pending_identifier_allocation,
        created_by_membership_id=context.membership.id,
        reason=reason,
        **_source_columns(facts.source),
    )
    session.add(version)
    session.flush()
    session.execute(
        delete(IpPatentApplicationIdentity).where(
            IpPatentApplicationIdentity.company_id == context.company.id,
            IpPatentApplicationIdentity.application_id == application.id,
        )
    )
    dialect = session.get_bind().dialect.name
    insert = (
        pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    )
    if insert is None:
        raise _error(
            "patent_database_unsupported",
            "This database does not support atomic patent identity admission.",
        )
    for ordinal, (identifier, scope, identity_hash) in enumerate(
        zip(facts.identifiers, scopes, hashes, strict=True)
    ):
        statement = (
            insert(IpPatentApplicationIdentity)
            .values(
                id=str(uuid4()),
                company_id=context.company.id,
                application_id=application.id,
                application_version_id=version.id,
                identity_sha256=identity_hash,
                **scope,
            )
            .on_conflict_do_nothing(index_elements=["company_id", "identity_sha256"])
            .returning(IpPatentApplicationIdentity.id)
        )
        if session.scalar(statement) is None:
            existing = session.scalar(
                select(IpPatentApplicationIdentity).where(
                    IpPatentApplicationIdentity.company_id == context.company.id,
                    IpPatentApplicationIdentity.identity_sha256 == identity_hash,
                )
            )
            if existing is not None and any(
                getattr(existing, key) != value for key, value in scope.items()
            ):
                raise _error(
                    "patent_identifier_integrity",
                    "Identifier identity evidence requires reconciliation.",
                )
            raise _error(
                "patent_identifier_exists",
                "An application already uses this identifier in the same jurisdiction and office. "
                "Review the existing record.",
            )
        session.add(
            IpPatentApplicationIdentifier(
                company_id=context.company.id,
                application_id=application.id,
                application_version_id=version.id,
                ordinal=ordinal,
                identifier_kind=identifier.identifier_kind,
                raw_value=identifier.raw_value,
                **_source_columns(identifier.source),
            )
        )
    session.flush()
    return version


def _link_sources(
    session: Session, context: SessionContext, docket: IpDocketRecord, facts: PatentApplicationFacts
) -> None:
    linked: set[str] = set()
    for source in _sources(facts):
        columns = _source_columns(source)
        if columns["source_document_id"] not in linked:
            _link_disclosure_source(session, context, docket, source)
            linked.add(columns["source_document_id"])


def create_patent_application(
    session: Session,
    *,
    context: SessionContext,
    payload: PatentApplicationCreateRequest,
    idempotency_key: str,
) -> PatentApplicationRecord:
    _lock_application_identity_writer(session, context)
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    claim = claim_idempotency(
        session,
        company_id=context.company.id,
        actor_scope=f"membership:{context.membership.id}",
        actor_membership_id=context.membership.id,
        http_method="POST",
        operation="ip.patent.application.create",
        idempotency_key=idempotency_key,
        request_hash=canonical_json_sha256(payload.model_dump(mode="json")),
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        if claim.record.result_type != "ip_patent_application" or not claim.record.result_id:
            raise _error(
                "patent_replay_integrity", "The saved application result cannot be resolved."
            )
        retained = _application(session, context, claim.record.result_id)
        _docket_or_404(session, context=context, docket_id=retained.docket_id)
        return get_patent_application(session, context=context, application_id=retained.id)
    if claim.outcome != IdempotencyClaimOutcome.CLAIMED:
        raise _error(
            "patent_creation_conflict", "This creation key is in use. Reload before retrying."
        )
    family = _family(session, context, str(payload.family_id))
    _client(session, context, UUID(family.client_id))
    dockets = _lock_sources_and_dockets(
        session, context, _sources(payload.facts), {family.docket_id}
    )
    parent = dockets[family.docket_id]
    get_patent_family(session, context=context, family_id=family.id)
    if (
        parent.current_version != payload.expected_family_version
        or parent.lifecycle_version != payload.expected_family_lifecycle_version
    ):
        raise _error(
            "patent_family_stale", "The family changed. Reload before adding an application."
        )
    docket = IpDocketRecord(
        company_id=context.company.id,
        record_type="patent_application",
        title=payload.facts.title,
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
        jurisdiction=payload.facts.jurisdiction,
        title=payload.facts.title,
    )
    session.add(asset)
    session.flush()
    application = IpPatentApplication(
        company_id=context.company.id,
        docket_id=docket.id,
        asset_id=asset.id,
        family_id=family.id,
        prosecution_phase="disclosure",
    )
    session.add(application)
    session.flush()
    _append_version(
        session, context, application, docket, payload.facts, "Initial sourced application facts."
    )
    _link_sources(session, context, docket, payload.facts)
    record_from_context(
        session,
        context,
        action="ip_patent_application.created",
        target_type="ip_patent_application",
        target_id=application.id,
        ip_docket_id=docket.id,
        metadata={
            "version": 1,
            "family_id": family.id,
            "identifier_count": len(payload.facts.identifiers),
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
        result_type="ip_patent_application",
        result_id=application.id,
    )
    result = get_patent_application(session, context=context, application_id=application.id)
    session.commit()
    return result


def correct_patent_application(
    session: Session,
    *,
    context: SessionContext,
    application_id: str,
    payload: PatentApplicationCorrectionRequest,
) -> PatentApplicationRecord:
    from caseops_api.services.ip_patent_priorities import validate_application_priority_correction

    _lock_application_identity_writer(session, context)
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    application = _application(session, context, application_id)
    dockets = _lock_sources_and_dockets(
        session, context, _sources(payload.facts), {application.docket_id}
    )
    docket = dockets[application.docket_id]
    _check_anchor(docket)
    if (
        docket.current_version != payload.expected_version
        or docket.lifecycle_version != payload.expected_lifecycle_version
    ):
        raise _error(
            "patent_application_stale", "The application changed. Reload before correcting it."
        )
    get_patent_application(session, context=context, application_id=application.id)
    validate_application_priority_correction(
        session,
        context=context,
        application=application,
        facts=payload.facts,
    )
    asset = session.scalar(
        select(IpAsset)
        .where(
            IpAsset.company_id == context.company.id,
            IpAsset.id == application.asset_id,
            IpAsset.docket_id == docket.id,
            IpAsset.asset_kind == "patent",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if asset is None:
        raise _error("patent_application_integrity", "The application asset requires repair.")
    docket.current_version += 1
    docket.title = payload.facts.title
    asset.title = payload.facts.title
    asset.jurisdiction = payload.facts.jurisdiction
    asset.version += 1
    _append_version(session, context, application, docket, payload.facts, payload.reason)
    _link_sources(session, context, docket, payload.facts)
    record_from_context(
        session,
        context,
        action="ip_patent_application.corrected",
        target_type="ip_patent_application",
        target_id=application.id,
        ip_docket_id=docket.id,
        metadata={"version": docket.current_version, "reason": payload.reason},
    )
    result = get_patent_application(session, context=context, application_id=application.id)
    session.commit()
    return result
