"""Typed rectification, cancellation, and non-use proceeding workspace."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import IpDocketEvent, IpIdentifier, IpProceeding
from caseops_api.schemas.ip_lifecycle import IpDocketEventCreateRequest, IpDocketEventResponse
from caseops_api.schemas.ip_post_registration import (
    IpPostRegistrationActionRequest,
    IpPostRegistrationProfile,
    IpPostRegistrationWorkspaceResponse,
    IpPostRegistrationWorkspaceUpsertRequest,
)
from caseops_api.schemas.ip_records import IpIdentifierResponse, IpProceedingResponse
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.session_context import SessionContext

POST_REGISTRATION_KINDS = frozenset({"rectification", "cancellation", "non_use_removal"})
POST_REGISTRATION_STAGES = {
    kind: frozenset(
        {
            "draft",
            "petition_filed",
            "service_pending",
            "counterstatement_due",
            "counterstatement_filed",
            "claimant_evidence_due",
            "claimant_evidence_filed",
            "respondent_evidence_due",
            "respondent_evidence_filed",
            "reply_evidence_due",
            "reply_evidence_filed",
            "hearing_pending",
            "hearing_scheduled",
            "reserved_for_order",
            "decided",
            "compliance_pending",
            "appeal_pending",
            "withdrawn",
            "settled",
            "closed",
        }
    )
    for kind in POST_REGISTRATION_KINDS
}
POST_REGISTRATION_DISPOSITIONS = {
    "rectification": frozenset({"rectify_registration", "no_change"}),
    "cancellation": frozenset({"cancel_registration", "no_change"}),
    "non_use_removal": frozenset({"remove_for_non_use", "no_change"}),
}


def _proceeding_or_404(
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
        IpProceeding.proceeding_kind.in_(POST_REGISTRATION_KINDS),
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    proceeding = session.scalar(statement)
    if proceeding is None:
        raise HTTPException(
            status_code=404,
            detail="Post-registration proceeding not found.",
        )
    return proceeding


def _events(session: Session, *, proceeding: IpProceeding) -> list[IpDocketEvent]:
    return list(
        session.scalars(
            select(IpDocketEvent)
            .where(
                IpDocketEvent.company_id == proceeding.company_id,
                IpDocketEvent.docket_id == proceeding.docket_id,
                IpDocketEvent.proceeding_id == proceeding.id,
                IpDocketEvent.event_kind.in_(
                    ("post_registration_profile", "post_registration_action")
                ),
                IpDocketEvent.candidate_status.in_(("confirmed", "reconciled")),
            )
            .order_by(IpDocketEvent.sequence)
        )
    )


def _active_stay(events: list[IpDocketEvent]) -> bool:
    active = False
    for event in events:
        if event.event_kind != "post_registration_action":
            continue
        action_kind = event.payload_json.get("action_kind")
        if action_kind == "interim_stay":
            active = True
        elif action_kind == "stay_lifted":
            active = False
    return active


def _profile_from_event(event: IpDocketEvent | None) -> IpPostRegistrationProfile | None:
    if event is None:
        return None
    raw = event.payload_json.get("post_registration_profile")
    return IpPostRegistrationProfile.model_validate(raw) if isinstance(raw, dict) else None


def _workspace_response(
    session: Session,
    *,
    proceeding: IpProceeding,
) -> IpPostRegistrationWorkspaceResponse:
    events = _events(session, proceeding=proceeding)
    profile_events = [row for row in events if row.event_kind == "post_registration_profile"]
    action_events = [row for row in events if row.event_kind == "post_registration_action"]
    profile_event = profile_events[-1] if profile_events else None
    profile = _profile_from_event(profile_event)
    identifiers = list(
        session.scalars(
            select(IpIdentifier)
            .where(
                IpIdentifier.company_id == proceeding.company_id,
                IpIdentifier.proceeding_id == proceeding.id,
                IpIdentifier.superseded_by_identifier_id.is_(None),
            )
            .order_by(IpIdentifier.effective_from.desc(), IpIdentifier.created_at.desc())
        )
    )
    gaps: list[str] = []
    if profile is None:
        gaps.append("post_registration_profile_required")
    if not identifiers and not proceeding.source_pending_identifier_allocation:
        gaps.append("typed_proceeding_identifier_or_pending_allocation_required")
    return IpPostRegistrationWorkspaceResponse(
        proceeding=IpProceedingResponse.model_validate(proceeding),
        profile=profile,
        profile_event=(
            IpDocketEventResponse.model_validate(profile_event) if profile_event else None
        ),
        profile_revision_count=len(profile_events),
        identifiers=[IpIdentifierResponse.model_validate(row) for row in identifiers],
        action_events=[IpDocketEventResponse.model_validate(row) for row in action_events],
        active_stay=_active_stay(events),
        ready_for_stage_progression=not gaps,
        readiness_gaps=gaps,
    )


def get_post_registration_workspace(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
) -> IpPostRegistrationWorkspaceResponse:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        required_capability="ip:read",
    )
    proceeding = _proceeding_or_404(
        session,
        company_id=docket.company_id,
        docket_id=docket.id,
        proceeding_id=proceeding_id,
        for_update=False,
    )
    return _workspace_response(session, proceeding=proceeding)


def save_post_registration_workspace(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpPostRegistrationWorkspaceUpsertRequest,
) -> IpPostRegistrationWorkspaceResponse:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    proceeding = _proceeding_or_404(
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
    if payload.profile.proceeding_type != proceeding.proceeding_kind:
        raise HTTPException(
            status_code=422,
            detail="Profile type must match the canonical proceeding type.",
        )
    expected_template = f"post-registration/{proceeding.proceeding_kind}"
    if payload.profile.rule_map.template_key != expected_template:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{proceeding.proceeding_kind} requires its own {expected_template!r} "
                "rule template; opposition templates cannot be reused."
            ),
        )

    existing = _events(session, proceeding=proceeding)
    profiles = [row for row in existing if row.event_kind == "post_registration_profile"]
    prior = profiles[-1] if profiles else None
    if payload.expected_profile_event_id != (prior.id if prior else None):
        raise HTTPException(
            status_code=409,
            detail="Post-registration profile changed; reload before saving.",
        )

    confirmed_profile = payload.profile.model_copy(
        update={"lawyer_confirmed_by_membership_id": context.membership.id}
    )
    from caseops_api.services.ip_lifecycle import append_ip_docket_event

    append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            proceeding_id=proceeding.id,
            event_kind="post_registration_profile",
            source=payload.source,
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            supersedes_event_id=(prior.id if prior else None),
            correction_reason=(payload.reason if prior else None),
            payload={
                "post_registration_profile_revision": True,
                "post_registration_profile": confirmed_profile.model_dump(mode="json"),
            },
        ),
        commit=False,
    )
    session.commit()
    session.refresh(proceeding)
    return _workspace_response(session, proceeding=proceeding)


def record_post_registration_action(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpPostRegistrationActionRequest,
) -> IpPostRegistrationWorkspaceResponse:
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:approve",
    )
    proceeding = _proceeding_or_404(
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

    events = _events(session, proceeding=proceeding)
    if not any(row.event_kind == "post_registration_profile" for row in events):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_post_registration_workspace_incomplete",
                "message": "Confirm the post-registration profile before recording actions.",
            },
        )
    active_stay = _active_stay(events)
    if payload.action_kind == "stay_lifted" and not active_stay:
        raise HTTPException(status_code=409, detail="There is no active interim stay to lift.")
    if (
        payload.action_kind == "stage_update"
        and payload.stage not in POST_REGISTRATION_STAGES[proceeding.proceeding_kind]
    ):
        raise HTTPException(
            status_code=422,
            detail="Stage is not part of this post-registration rule template.",
        )
    if payload.action_kind == "parallel_proceeding_link":
        if payload.parallel_proceeding_id == proceeding.id:
            raise HTTPException(status_code=422, detail="A proceeding cannot link to itself.")
        parallel = session.scalar(
            select(IpProceeding).where(
                IpProceeding.id == payload.parallel_proceeding_id,
                IpProceeding.company_id == docket.company_id,
                IpProceeding.docket_id == docket.id,
            )
        )
        if parallel is None:
            raise HTTPException(status_code=404, detail="Parallel proceeding not found.")
    if payload.action_kind == "disposition_candidate" and active_stay:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_post_registration_stay_blocks_disposition",
                "message": "Lift the active interim stay before proposing a disposition.",
            },
        )
    if (
        payload.action_kind == "disposition_candidate"
        and payload.candidate_disposition
        not in POST_REGISTRATION_DISPOSITIONS[proceeding.proceeding_kind]
    ):
        raise HTTPException(
            status_code=422,
            detail="Candidate disposition does not match the proceeding type.",
        )
    if payload.action_kind == "disposition_review":
        candidate = next(
            (
                row
                for row in events
                if row.id == payload.candidate_event_id
                and row.payload_json.get("action_kind") == "disposition_candidate"
            ),
            None,
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="Disposition candidate not found.")
        if any(
            row.payload_json.get("action_kind") == "disposition_review"
            and row.payload_json.get("candidate_event_id") == candidate.id
            for row in events
        ):
            raise HTTPException(status_code=409, detail="Disposition candidate already reviewed.")
        if active_stay and payload.review_decision == "approved":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ip_post_registration_stay_blocks_disposition",
                    "message": "An active interim stay blocks disposition approval.",
                },
            )

    resulting_stage = payload.stage if payload.action_kind in {"stage_update", "closure"} else None
    from caseops_api.services.ip_lifecycle import append_ip_docket_event

    append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            proceeding_id=proceeding.id,
            event_kind="post_registration_action",
            source=payload.source,
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            resulting_stage=resulting_stage,
            payload={
                "action_kind": payload.action_kind,
                "action_identity": next(
                    (
                        str(value)
                        for value in (
                            payload.stage,
                            payload.parallel_proceeding_id,
                            payload.candidate_event_id,
                            payload.candidate_disposition,
                            payload.authority_reference,
                            payload.legal_effect,
                        )
                        if value
                    ),
                    payload.action_kind,
                ),
                "proceeding_type": proceeding.proceeding_kind,
                "rule_template_key": f"post-registration/{proceeding.proceeding_kind}",
                "authority_reference": payload.authority_reference,
                "parallel_proceeding_id": payload.parallel_proceeding_id,
                "legal_effect": payload.legal_effect,
                "legal_effective_date": (
                    payload.legal_effective_date.isoformat()
                    if payload.legal_effective_date
                    else None
                ),
                "candidate_disposition": payload.candidate_disposition,
                "candidate_event_id": payload.candidate_event_id,
                "review_decision": payload.review_decision,
                "authorized_confirmation": payload.authorized_confirmation,
                "registration_disposition_applied": False,
            },
        ),
        commit=False,
    )
    session.commit()
    session.refresh(proceeding)
    return _workspace_response(session, proceeding=proceeding)
