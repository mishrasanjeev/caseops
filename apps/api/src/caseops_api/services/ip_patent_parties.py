"""Sourced patent parties extend canonical IP parties without implying title."""

from __future__ import annotations

from datetime import UTC
from hmac import compare_digest

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from caseops_api.db.models import (
    IpPartyAndRole,
    IpPatentApplication,
    IpPatentFamily,
    IpPatentPartyDetail,
)
from caseops_api.schemas.ip_patents import (
    PatentAddressSnapshot,
    PatentApplicationRecord,
    PatentDocumentSource,
    PatentFamilyRecord,
    PatentPartyCreateRequest,
    PatentPartyFact,
    PatentPartyListResponse,
    PatentPartyRecord,
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
    _checked_source_ids,
    _source_columns,
    _source_key,
    get_patent_application,
)
from caseops_api.services.ip_patent_families import (
    _client,
    _error,
    _link_disclosure_source,
    _lock_sources_and_dockets,
    get_patent_family,
)
from caseops_api.services.session_context import SessionContext


def _anchor(
    session: Session,
    context: SessionContext,
    docket_id: str,
) -> PatentFamilyRecord | PatentApplicationRecord:
    for model, getter, key in (
        (IpPatentFamily, get_patent_family, "family_id"),
        (IpPatentApplication, get_patent_application, "application_id"),
    ):
        identifier = session.scalar(
            select(model.id).where(
                model.company_id == context.company.id,
                model.docket_id == docket_id,
            )
        )
        if identifier is not None:
            return getter(session, context=context, **{key: identifier})
    raise _error("patent_record_not_found", "Patent record not found.", 404)


def _sequence(session: Session, context: SessionContext, docket_id: str) -> int:
    return (
        session.scalar(
            select(IpPatentPartyDetail.sequence)
            .where(
                IpPatentPartyDetail.company_id == context.company.id,
                IpPatentPartyDetail.docket_id == docket_id,
            )
            .order_by(IpPatentPartyDetail.sequence.desc())
            .limit(1)
        )
        or 0
    )


def _rows(context: SessionContext, docket_id: str, sequence: int):
    successor = aliased(IpPatentPartyDetail)
    replaced = (
        select(successor.id)
        .where(
            successor.company_id == IpPatentPartyDetail.company_id,
            successor.docket_id == IpPatentPartyDetail.docket_id,
            successor.supersedes_party_id == IpPatentPartyDetail.id,
            successor.sequence <= sequence,
        )
        .correlate(IpPatentPartyDetail)
        .exists()
    )
    statement = (
        select(IpPatentPartyDetail, IpPartyAndRole, replaced)
        .join(
            IpPartyAndRole,
            (IpPartyAndRole.id == IpPatentPartyDetail.id)
            & (IpPartyAndRole.company_id == IpPatentPartyDetail.company_id)
            & (IpPartyAndRole.docket_id == IpPatentPartyDetail.docket_id),
        )
        .where(
            IpPatentPartyDetail.company_id == context.company.id,
            IpPatentPartyDetail.docket_id == docket_id,
            IpPatentPartyDetail.sequence <= sequence,
        )
    )
    return statement, replaced


def _records(session: Session, context: SessionContext, rows) -> list[PatentPartyRecord]:
    if len(rows) > 100:
        raise _error("patent_party_page_limit", "Party pages contain at most 100 records.")
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
            "patent_party_source_unavailable",
            "A party source is no longer accessible. Refresh your record access.",
            404,
        )
    result = []
    for (detail, party, replaced), pin in zip(rows, sources, strict=True):
        fact = PatentPartyFact(
            role=party.role_kind,
            name=party.party_name,
            client_id=party.client_id,
            address=PatentAddressSnapshot.model_validate(detail.address_json),
            effective_from=party.effective_from,
            effective_until=party.effective_until,
            source=pin,
        )
        if party.proceeding_id is not None or not compare_digest(
            detail.fact_sha256,
            canonical_json_sha256(fact.model_dump(mode="json")),
        ):
            raise _error(
                "patent_party_integrity", "The retained party evidence requires reconciliation."
            )
        result.append(
            PatentPartyRecord(
                id=party.id,
                docket_id=party.docket_id,
                sequence=detail.sequence,
                anchor_version=detail.anchor_version,
                lifecycle_version=detail.lifecycle_version,
                supersedes_party_id=detail.supersedes_party_id,
                is_current=not replaced,
                fact=fact,
                reason=detail.reason,
                created_at=party.created_at
                if party.created_at.tzinfo
                else party.created_at.replace(tzinfo=UTC),
            )
        )
    return result


def get_patent_party(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    party_id: str,
) -> PatentPartyRecord:
    _anchor(session, context, docket_id)
    statement, _ = _rows(context, docket_id, _sequence(session, context, docket_id))
    rows = session.execute(statement.where(IpPatentPartyDetail.id == party_id)).all()
    if not rows:
        raise _error("patent_party_not_found", "Patent party not found.", 404)
    return _records(session, context, rows)[0]


def list_patent_parties(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    limit: int = 25,
    cursor: int | None = None,
    snapshot_sequence: int | None = None,
    history: bool = False,
) -> PatentPartyListResponse:
    if not 1 <= limit <= 100 or (cursor is not None and cursor < 1):
        raise _error("patent_party_page_invalid", "Select a valid party page.", 422)
    if cursor is not None and snapshot_sequence is None:
        raise _error("patent_party_snapshot_required", "Reload the first party page.", 422)
    _anchor(session, context, docket_id)
    sequence = _sequence(session, context, docket_id)
    if snapshot_sequence is not None and snapshot_sequence != sequence:
        raise _error("patent_parties_stale", "Parties changed. Reload the first page.")
    statement, replaced = _rows(context, docket_id, sequence)
    if not history:
        statement = statement.where(~replaced)
    if cursor is not None:
        statement = statement.where(IpPatentPartyDetail.sequence < cursor)
    rows = session.execute(
        statement.order_by(IpPatentPartyDetail.sequence.desc()).limit(limit + 1)
    ).all()
    return PatentPartyListResponse(
        docket_id=docket_id,
        collection_sequence=sequence,
        parties=_records(session, context, rows[:limit]),
        next_cursor=rows[limit - 1][0].sequence if len(rows) > limit else None,
    )


def create_patent_party(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: PatentPartyCreateRequest,
    idempotency_key: str,
) -> PatentPartyRecord:
    context = _lock_ip_writer_context(session, context=context, required_capability="ip:write")
    claim = claim_idempotency(
        session,
        company_id=context.company.id,
        actor_scope=f"membership:{context.membership.id}",
        actor_membership_id=context.membership.id,
        http_method="POST",
        operation="ip.patent.party.create",
        idempotency_key=idempotency_key,
        request_hash=canonical_json_sha256(
            {"docket_id": docket_id, **payload.model_dump(mode="json")}
        ),
    )
    if claim.outcome == IdempotencyClaimOutcome.REPLAY:
        if claim.record.result_type != "ip_patent_party" or not claim.record.result_id:
            raise _error(
                "patent_party_replay_integrity", "The saved party result cannot be resolved."
            )
        _lock_sources_and_dockets(session, context, [payload.fact.source], {docket_id})
        return get_patent_party(
            session, context=context, docket_id=docket_id, party_id=claim.record.result_id
        )
    if claim.outcome != IdempotencyClaimOutcome.CLAIMED:
        raise _error(
            "patent_party_creation_conflict", "This creation key is in use. Reload before retrying."
        )
    if payload.fact.client_id is not None:
        _client(session, context, payload.fact.client_id)
    docket = _lock_sources_and_dockets(session, context, [payload.fact.source], {docket_id})[
        docket_id
    ]
    anchor = _anchor(session, context, docket_id)
    sequence = _sequence(session, context, docket_id)
    if (
        anchor.version != payload.expected_version
        or anchor.lifecycle_version != payload.expected_lifecycle_version
        or sequence != payload.expected_party_sequence
    ):
        raise _error("patent_parties_stale", "The record or parties changed. Reload before saving.")
    statement, replaced = _rows(context, docket_id, sequence)
    if payload.supersedes_party_id is not None:
        predecessor = session.execute(
            statement.where(
                IpPatentPartyDetail.id == str(payload.supersedes_party_id),
                ~replaced,
            )
        ).all()
        if not predecessor:
            raise _error(
                "patent_party_not_current", "Select a current party on this patent record.", 409
            )
        _records(session, context, predecessor)
    digest = canonical_json_sha256(payload.fact.model_dump(mode="json"))
    duplicate = session.execute(
        statement.where(IpPatentPartyDetail.fact_sha256 == digest, ~replaced).limit(1)
    ).first()
    if duplicate is not None:
        raise _error("patent_party_exists", "These exact party facts are already recorded.")
    party = IpPartyAndRole(
        company_id=context.company.id,
        docket_id=docket_id,
        proceeding_id=None,
        client_id=str(payload.fact.client_id) if payload.fact.client_id else None,
        party_name=payload.fact.name,
        role_kind=payload.fact.role,
        effective_from=payload.fact.effective_from,
        effective_until=payload.fact.effective_until,
        source="patent_document_version",
    )
    session.add(party)
    session.flush()
    session.add(
        IpPatentPartyDetail(
            id=party.id,
            company_id=context.company.id,
            docket_id=docket_id,
            sequence=sequence + 1,
            anchor_version=anchor.version,
            lifecycle_version=anchor.lifecycle_version,
            supersedes_party_id=str(payload.supersedes_party_id)
            if payload.supersedes_party_id
            else None,
            address_json=payload.fact.address.model_dump(mode="json"),
            **_source_columns(payload.fact.source),
            fact_sha256=digest,
            created_by_membership_id=context.membership.id,
            reason=payload.reason,
        )
    )
    session.flush()
    _link_disclosure_source(session, context, docket, payload.fact.source)
    record_from_context(
        session,
        context,
        action="ip_patent_party.superseded"
        if payload.supersedes_party_id
        else "ip_patent_party.created",
        target_type="ip_patent_party",
        target_id=party.id,
        ip_docket_id=docket_id,
        metadata={
            "sequence": sequence + 1,
            "supersedes_party_id": str(payload.supersedes_party_id)
            if payload.supersedes_party_id
            else None,
        },
    )
    complete_idempotency(
        session,
        company_id=context.company.id,
        record_id=claim.record.id,
        claim_token=claim.claim_token,
        claim_generation=claim.claim_generation,
        response_status=201,
        result_type="ip_patent_party",
        result_id=party.id,
    )
    result = get_patent_party(session, context=context, docket_id=docket_id, party_id=party.id)
    session.commit()
    return result
