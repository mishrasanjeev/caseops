"""Aggregate and version the baseline opposition workspace."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDocketEvent,
    IpIdentifier,
    IpPartyAndRole,
    IpProceeding,
)
from caseops_api.schemas.ip_lifecycle import (
    IpDocketEventCreateRequest,
    IpDocketEventResponse,
)
from caseops_api.schemas.ip_oppositions import (
    IpOppositionPartyRecord,
    IpOppositionProfile,
    IpOppositionWorkspaceResponse,
    IpOppositionWorkspaceUpsertRequest,
)
from caseops_api.schemas.ip_records import IpIdentifierResponse, IpProceedingResponse
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.session_context import SessionContext


def _opposition_or_404(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    proceeding_id: str,
    for_update: bool,
) -> IpProceeding:
    statement = select(IpProceeding).where(
        IpProceeding.id == proceeding_id,
        IpProceeding.company_id == company_id,
        IpProceeding.docket_id == docket_id,
        IpProceeding.proceeding_kind == "opposition",
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    proceeding = session.scalar(statement)
    if proceeding is None:
        raise HTTPException(status_code=404, detail="Opposition proceeding not found.")
    return proceeding


def _profile_events(
    session: Session,
    *,
    proceeding: IpProceeding,
) -> list[IpDocketEvent]:
    return list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == proceeding.company_id,
                IpDocketEvent.docket_id == proceeding.docket_id,
                IpDocketEvent.proceeding_id == proceeding.id,
                IpDocketEvent.event_kind == "opposition_profile",
                IpDocketEvent.candidate_status.in_(("confirmed", "reconciled")),
            )
            .order_by(IpDocketEvent.sequence)
        )
    )


def _current_parties(
    session: Session,
    *,
    proceeding: IpProceeding,
) -> list[IpPartyAndRole]:
    return list(
        session.scalars(
            select(IpPartyAndRole)
            .where(
                IpPartyAndRole.company_id == proceeding.company_id,
                IpPartyAndRole.docket_id == proceeding.docket_id,
                IpPartyAndRole.proceeding_id == proceeding.id,
                IpPartyAndRole.effective_until.is_(None),
            )
            .order_by(IpPartyAndRole.role_kind, IpPartyAndRole.party_name)
        )
    )


def _current_identifiers(
    session: Session,
    *,
    proceeding: IpProceeding,
) -> tuple[list[IpIdentifier], list[IpIdentifier]]:
    rows = list(
        session.scalars(
            select(IpIdentifier)
            .where(
                IpIdentifier.company_id == proceeding.company_id,
                IpIdentifier.docket_id == proceeding.docket_id,
                IpIdentifier.effective_until.is_(None),
                IpIdentifier.reconciliation_status == "confirmed",
            )
            .order_by(IpIdentifier.is_primary.desc(), IpIdentifier.created_at)
        )
    )
    application = [
        row
        for row in rows
        if row.application_id == proceeding.application_id
        and row.identifier_kind == "application"
    ]
    opposition = [
        row
        for row in rows
        if row.proceeding_id == proceeding.id and row.identifier_kind == "opposition"
    ]
    return application, opposition


def _profile_from_event(event: IpDocketEvent | None) -> IpOppositionProfile | None:
    if event is None:
        return None
    profile = event.payload_json.get("opposition_profile")
    return IpOppositionProfile.model_validate(profile) if profile else None


def _readiness_gaps(
    *,
    proceeding: IpProceeding,
    profile: IpOppositionProfile | None,
    parties: list[IpPartyAndRole],
    application_identifiers: list[IpIdentifier],
    opposition_identifiers: list[IpIdentifier],
) -> list[str]:
    gaps: list[str] = []
    if proceeding.application_id is None:
        gaps.append("linked_application_required")
    if not application_identifiers:
        gaps.append("confirmed_application_identifier_required")
    if not opposition_identifiers:
        gaps.append("confirmed_opposition_identifier_required")
    roles = {row.role_kind for row in parties}
    if "applicant" not in roles:
        gaps.append("applicant_party_required")
    if "opponent" not in roles:
        gaps.append("opponent_party_required")
    if profile is None:
        gaps.append("opposition_profile_required")
        return gaps
    if not profile.applicable_rule_version.strip():
        gaps.append("applicable_rule_version_required")
    if not profile.forum.strip():
        gaps.append("forum_required")
    if not (profile.source_notice_reference or profile.source_notice_document_ref):
        gaps.append("source_notice_required")
    if not profile.grounds:
        gaps.append("grounds_required")
    if not profile.challenged_scope:
        gaps.append("challenged_scope_required")
    if proceeding.side == "applicant" and profile.service is None:
        gaps.append("service_fact_required")
    if proceeding.side == "opponent":
        if profile.client_instruction_state != "confirmed":
            gaps.append("confirmed_client_instruction_required")
        if profile.limitation_date is None:
            gaps.append("limitation_date_required")
        if not profile.relied_on_rights:
            gaps.append("relied_on_right_required")
    return gaps


def assert_opposition_workspace_ready(
    session: Session,
    *,
    proceeding: IpProceeding,
) -> None:
    profile_events = _profile_events(session, proceeding=proceeding)
    parties = _current_parties(session, proceeding=proceeding)
    application_identifiers, opposition_identifiers = _current_identifiers(
        session, proceeding=proceeding
    )
    gaps = _readiness_gaps(
        proceeding=proceeding,
        profile=_profile_from_event(profile_events[-1] if profile_events else None),
        parties=parties,
        application_identifiers=application_identifiers,
        opposition_identifiers=opposition_identifiers,
    )
    if gaps:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_opposition_workspace_incomplete",
                "message": "Complete the opposition workspace before stage progression.",
                "readiness_gaps": gaps,
            },
        )


def get_opposition_workspace(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
) -> IpOppositionWorkspaceResponse:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        required_capability="ip:read",
    )
    proceeding = _opposition_or_404(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        proceeding_id=proceeding_id,
        for_update=False,
    )
    profile_events = _profile_events(session, proceeding=proceeding)
    profile_event = profile_events[-1] if profile_events else None
    profile = _profile_from_event(profile_event)
    parties = _current_parties(session, proceeding=proceeding)
    application_identifiers, opposition_identifiers = _current_identifiers(
        session, proceeding=proceeding
    )
    stage_events = list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == proceeding.company_id,
                IpDocketEvent.docket_id == proceeding.docket_id,
                IpDocketEvent.proceeding_id == proceeding.id,
                IpDocketEvent.event_kind == "lifecycle_transition",
            )
            .order_by(IpDocketEvent.sequence)
        )
    )
    gaps = _readiness_gaps(
        proceeding=proceeding,
        profile=profile,
        parties=parties,
        application_identifiers=application_identifiers,
        opposition_identifiers=opposition_identifiers,
    )
    return IpOppositionWorkspaceResponse(
        proceeding=IpProceedingResponse.model_validate(proceeding),
        profile=profile,
        profile_event=(
            IpDocketEventResponse.model_validate(profile_event) if profile_event else None
        ),
        profile_revision_count=len(profile_events),
        parties=[IpOppositionPartyRecord.model_validate(row) for row in parties],
        application_identifiers=[
            IpIdentifierResponse.model_validate(row) for row in application_identifiers
        ],
        opposition_identifiers=[
            IpIdentifierResponse.model_validate(row) for row in opposition_identifiers
        ],
        linked_matter_id=docket.matter_id,
        stage_events=[IpDocketEventResponse.model_validate(row) for row in stage_events],
        ready_for_stage_progression=not gaps,
        readiness_gaps=gaps,
    )


def save_opposition_workspace(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionWorkspaceUpsertRequest,
) -> IpOppositionWorkspaceResponse:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    proceeding = _opposition_or_404(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        proceeding_id=proceeding_id,
        for_update=True,
    )
    if docket.lifecycle_version != payload.expected_lifecycle_version:
        raise HTTPException(status_code=409, detail="IP lifecycle version changed; reload.")
    if proceeding.version != payload.expected_proceeding_version:
        raise HTTPException(status_code=409, detail="Proceeding version changed; reload.")

    prior_events = _profile_events(session, proceeding=proceeding)
    prior_event = prior_events[-1] if prior_events else None
    prior_event_id = prior_event.id if prior_event else None
    if payload.expected_profile_event_id != prior_event_id:
        raise HTTPException(
            status_code=409,
            detail="Opposition profile changed; reload before saving.",
        )
    profile = IpOppositionProfile(
        applicable_rule_version=payload.applicable_rule_version.strip(),
        forum=payload.forum.strip(),
        client_instruction_state=payload.client_instruction_state,
        client_instruction_reference=payload.client_instruction_reference,
        limitation_date=payload.limitation_date,
        source_notice_reference=payload.source_notice_reference,
        source_notice_document_ref=payload.source_notice_document_ref,
        grounds=payload.grounds,
        challenged_scope=payload.challenged_scope,
        relied_on_rights=payload.relied_on_rights,
        service=payload.service,
        lawyer_confirmed_by_membership_id=context.membership.id,
    )

    from caseops_api.services.ip_lifecycle import append_ip_docket_event

    append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            proceeding_id=proceeding.id,
            event_kind="opposition_profile",
            source=payload.source,
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            supersedes_event_id=prior_event_id,
            correction_reason=(payload.reason if prior_event else None),
            payload={
                "opposition_profile_revision": True,
                "opposition_profile": profile.model_dump(mode="json"),
            },
        ),
        commit=False,
    )

    effective_date = payload.effective_at.date()
    current = _current_parties(session, proceeding=proceeding)
    desired = {
        (row.role, row.party_name.strip().casefold(), row.source.strip().casefold()): row
        for row in payload.parties
    }
    retained: set[tuple[str, str, str]] = set()
    for row in current:
        key = (row.role_kind, row.party_name.strip().casefold(), row.source.strip().casefold())
        if key in desired:
            retained.add(key)
        else:
            row.effective_until = max(effective_date, row.effective_from)
    for key, party in desired.items():
        if key in retained:
            continue
        session.add(
            IpPartyAndRole(
                company_id=docket.company_id,
                docket_id=docket.id,
                proceeding_id=proceeding.id,
                client_id=None,
                party_name=party.party_name.strip(),
                role_kind=party.role,
                effective_from=effective_date,
                source=party.source.strip(),
            )
        )
    session.commit()
    return get_opposition_workspace(
        session,
        context=context,
        docket_id=docket.id,
        proceeding_id=proceeding.id,
    )
