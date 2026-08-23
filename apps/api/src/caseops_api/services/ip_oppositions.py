"""Role-aware, evidence-backed opposition proceeding transitions."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import IpDocketEvent, IpIdentifier, IpProceeding
from caseops_api.schemas.ip_lifecycle import IpDocketEventCreateRequest
from caseops_api.schemas.ip_records import IpOppositionStageTransitionRequest
from caseops_api.services.session_context import SessionContext

OPPOSITION_STAGES = (
    "draft",
    "notice_filed",
    "service_pending",
    "counterstatement_due",
    "counterstatement_filed",
    "opponent_evidence_due",
    "opponent_evidence_filed",
    "applicant_evidence_due",
    "applicant_evidence_filed",
    "reply_evidence_due",
    "reply_evidence_filed",
    "hearing_pending",
    "hearing_scheduled",
    "reserved_for_order",
    "decided",
    "appeal_pending",
    "appealed",
    "withdrawn",
    "closed",
)

_NORMAL_TRANSITIONS = {
    "draft": {"notice_filed", "withdrawn"},
    "notice_filed": {"service_pending", "counterstatement_due", "withdrawn"},
    "service_pending": {"counterstatement_due", "withdrawn"},
    "counterstatement_due": {"counterstatement_filed", "withdrawn", "closed"},
    "counterstatement_filed": {"opponent_evidence_due", "withdrawn"},
    "opponent_evidence_due": {"opponent_evidence_filed", "withdrawn", "closed"},
    "opponent_evidence_filed": {"applicant_evidence_due", "withdrawn"},
    "applicant_evidence_due": {"applicant_evidence_filed", "withdrawn", "closed"},
    "applicant_evidence_filed": {"reply_evidence_due", "hearing_pending", "withdrawn"},
    "reply_evidence_due": {"reply_evidence_filed", "hearing_pending", "withdrawn"},
    "reply_evidence_filed": {"hearing_pending", "withdrawn"},
    "hearing_pending": {"hearing_scheduled", "withdrawn"},
    "hearing_scheduled": {"reserved_for_order", "hearing_pending", "withdrawn"},
    "reserved_for_order": {"decided", "hearing_scheduled"},
    "decided": {"appeal_pending", "closed"},
    "appeal_pending": {"appealed", "closed"},
    "appealed": {"closed"},
    "withdrawn": {"closed"},
    "closed": set(),
}


def assert_proceeding_can_enter_filed_stage(
    proceeding: IpProceeding,
    identifiers: Iterable[IpIdentifier],
) -> None:
    has_current_opposition_number = any(
        row.identifier_kind == "opposition"
        and row.proceeding_id == proceeding.id
        and row.effective_until is None
        and row.reconciliation_status == "confirmed"
        for row in identifiers
    )
    if not has_current_opposition_number:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_opposition_identifier_required",
                "message": (
                    "A confirmed current opposition number is required before the "
                    "proceeding can leave draft stage. Pending allocation remains "
                    "explicit and fail-closed."
                ),
            },
        )


def validate_opposition_stage_event(
    session: Session,
    *,
    proceeding: IpProceeding,
    to_stage: str,
    transition_kind: str,
    expected_proceeding_version: object,
    authority_reference: object,
    reason: str | None,
    source_reference: str | None,
    evidence_refs: Iterable[str],
    document_refs: Iterable[str],
    outcome: object,
    outcome_effective_date: object,
    authorized_confirmation: object,
) -> None:
    if proceeding.proceeding_kind != "opposition":
        return
    if expected_proceeding_version != proceeding.version:
        raise HTTPException(status_code=409, detail="Proceeding version changed; reload.")
    if to_stage not in OPPOSITION_STAGES:
        raise HTTPException(status_code=422, detail="Unknown canonical opposition stage.")
    if proceeding.stage == "closed":
        raise HTTPException(status_code=409, detail="Closed opposition proceedings are immutable.")
    if proceeding.application_id is None and to_stage != "draft":
        raise HTTPException(
            status_code=409,
            detail="An opposed trademark application is required before stage progression.",
        )
    if to_stage != "draft":
        identifiers = list(
            session.scalars(
                select(IpIdentifier).where(
                    IpIdentifier.company_id == proceeding.company_id,
                    IpIdentifier.proceeding_id == proceeding.id,
                )
            )
        )
        assert_proceeding_can_enter_filed_stage(proceeding, identifiers)
        from caseops_api.services.ip_opposition_workspace import (
            assert_opposition_workspace_ready,
        )

        assert_opposition_workspace_ready(session, proceeding=proceeding)

    if transition_kind == "extended":
        valid_transition = to_stage == proceeding.stage
    elif transition_kind == "normal":
        valid_transition = to_stage in _NORMAL_TRANSITIONS.get(proceeding.stage, set())
    elif transition_kind in {"skipped", "waived", "superseded"}:
        current_index = OPPOSITION_STAGES.index(proceeding.stage)
        valid_transition = OPPOSITION_STAGES.index(to_stage) > current_index
    else:
        valid_transition = False
    if not valid_transition:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Opposition stage transition {proceeding.stage!r} -> {to_stage!r} "
                f"is not allowed for {transition_kind!r}."
            ),
        )
    if not (reason or "").strip():
        raise HTTPException(status_code=422, detail="Opposition transitions require a reason.")
    if transition_kind != "normal" and not str(authority_reference or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Exceptional opposition transitions require authority.",
        )
    if transition_kind != "normal" and not all(
        (
            (source_reference or "").strip(),
            list(evidence_refs) or list(document_refs),
            str(authorized_confirmation or "").strip(),
        )
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Exceptional opposition transitions require source, evidence, "
                "authority, and authorized confirmation."
            ),
        )
    if transition_kind == "normal":
        from caseops_api.services.ip_opposition_applicant import (
            assert_applicant_stage_prerequisites,
        )
        from caseops_api.services.ip_opposition_opponent import (
            assert_opponent_stage_prerequisites,
        )

        assert_applicant_stage_prerequisites(
            session,
            proceeding=proceeding,
            to_stage=to_stage,
        )
        assert_opponent_stage_prerequisites(
            session,
            proceeding=proceeding,
            to_stage=to_stage,
        )
    if to_stage == "closed" and not all(
        (
            str(outcome or "").strip(),
            outcome_effective_date,
            (source_reference or "").strip(),
            list(evidence_refs) or list(document_refs),
            str(authorized_confirmation or "").strip(),
        )
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Opposition closure requires outcome, effective date, source, "
                "evidence, and authorized confirmation."
            ),
        )


def transition_opposition_stage(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    payload: IpOppositionStageTransitionRequest,
) -> tuple[IpProceeding, IpDocketEvent]:
    # Imported here to keep the generic lifecycle owner independent of this
    # typed adapter while still using its one append/lock/audit transaction.
    from caseops_api.services.ip_lifecycle import append_ip_docket_event

    event = append_ip_docket_event(
        session,
        context=context,
        docket_id=docket_id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=payload.expected_lifecycle_version,
            proceeding_id=proceeding_id,
            event_kind="lifecycle_transition",
            source=payload.source,
            source_reference=payload.source_reference,
            effective_at=payload.effective_at,
            responsible_membership_id=payload.responsible_membership_id,
            reason=payload.reason,
            evidence_refs=payload.evidence_refs,
            document_refs=payload.document_refs,
            resulting_stage=payload.to_stage,
            payload={
                "opposition_stage_transition": True,
                "transition_kind": payload.transition_kind,
                "expected_proceeding_version": payload.expected_proceeding_version,
                "authority_reference": payload.authority_reference,
                "outcome": payload.outcome,
                "outcome_effective_date": (
                    payload.outcome_effective_date.isoformat()
                    if payload.outcome_effective_date
                    else None
                ),
                "authorized_confirmation": payload.authorized_confirmation,
            },
        ),
    )
    proceeding = session.scalar(
        select(IpProceeding).where(
            IpProceeding.id == proceeding_id,
            IpProceeding.company_id == context.company.id,
            IpProceeding.docket_id == docket_id,
        )
    )
    if proceeding is None:  # pragma: no cover - guarded by the lifecycle writer
        raise HTTPException(status_code=404, detail="IP proceeding not found.")
    return proceeding, event
