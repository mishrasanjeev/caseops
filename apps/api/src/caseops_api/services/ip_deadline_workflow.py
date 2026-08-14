"""Authenticated IPLF-023B rule, calendar, and legal-deadline workflow.

Legal calculations and their immutable evidence live in ``ip_deadlines``.
Operational work is delegated atomically to the existing ``matter_deadlines``
writer.  External delivery remains disabled; reminder policies create durable
in-app intents only.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    CompanyIpRulePolicy,
    CompanyMembership,
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketEvent,
    IpDocketRecord,
    IpResponsibilityAssignment,
    IpRuleSet,
    IpRuleVersion,
    LegalWorkingCalendar,
    LegalWorkingCalendarVersion,
    Matter,
    MatterDeadline,
    NotificationDeliveryIntent,
)
from caseops_api.schemas.ip_deadlines import (
    IpCompanyRulePolicyRecord,
    IpCompanyRuleSelectionRequest,
    IpDeadlineCalculationRequest,
    IpDeadlineCompleteRequest,
    IpDeadlineConfirmRequest,
    IpDeadlineDependencyNode,
    IpDeadlineDependencyResponse,
    IpDeadlineExceptionRecord,
    IpDeadlineImpactResponse,
    IpDeadlineOverrideRequest,
    IpDeadlineProposalRequest,
    IpDeadlineRecalculateRequest,
    IpDeadlineRecord,
    IpDeadlineRuleDefinition,
    IpDeadlineWorkspaceResponse,
    IpNotificationPlanEntry,
    IpNotificationPreviewRequest,
    IpNotificationPreviewResponse,
    IpNotificationStatusEntry,
    IpNotificationStatusResponse,
    IpResponsibilityInput,
    IpRuleActivationRequest,
    IpRuleImpactResponse,
    IpRuleTransitionRequest,
    IpRuleVersionProposalRequest,
    IpRuleVersionRecord,
    LegalCalendarActivationRequest,
    LegalCalendarSnapshot,
    LegalCalendarVersionProposalRequest,
    LegalCalendarVersionRecord,
    ResponsibilityEvidence,
)
from caseops_api.schemas.matters import MatterDeadlineUpdateRequest
from caseops_api.services.audit import record_from_context
from caseops_api.services.deadlines import create_deadline, update_deadline
from caseops_api.services.ip_deadlines import (
    assert_critical_deadline_coverage,
    assert_rule_can_activate,
    calculate_ip_deadline,
    operational_projection_reference,
)
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.matter_access import can_access
from caseops_api.services.notification_delivery import (
    _recipient_context,
    cancel_pending_notification_intents,
    enqueue_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext


def _now() -> datetime:
    return datetime.now(UTC)


def _actor_label(context: SessionContext) -> str:
    return context.user.full_name or context.user.email


def _membership(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
) -> CompanyMembership:
    row = session.scalar(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user))
        .where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == context.company.id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if row is None or not row.user.is_active:
        raise HTTPException(status_code=400, detail="Active company membership not found.")
    return row


def _assert_rule_governance_access(
    session: Session,
    *,
    context: SessionContext,
    row: IpRuleVersion,
) -> None:
    proposer_company_id = session.scalar(
        select(CompanyMembership.company_id).where(
            CompanyMembership.id == row.proposed_by_membership_id
        )
    )
    if proposer_company_id != context.company.id:
        raise HTTPException(status_code=404, detail="Rule version not found.")


def _rule_record(rule_set: IpRuleSet, row: IpRuleVersion) -> IpRuleVersionRecord:
    return IpRuleVersionRecord(
        id=row.id,
        rule_set_id=rule_set.id,
        key=rule_set.key,
        rule_kind=rule_set.rule_kind,
        jurisdiction=rule_set.jurisdiction,
        office=rule_set.office,
        right_kind=rule_set.right_kind,
        proceeding_kind=rule_set.proceeding_kind,
        role=rule_set.role,
        stage=rule_set.stage,
        version=row.version,
        status=row.status,
        source_record_id=row.source_record_id,
        source_hash=row.source_hash,
        source_reference=row.source_reference,
        effective_from=row.effective_from,
        effective_until=row.effective_until,
        engine_compatibility=row.engine_compatibility,
        definition=row.definition_json,
        fixtures=row.fixture_set_json,
        proposer_label_snapshot=row.proposer_label_snapshot,
        reviewer_label_snapshot=row.reviewer_label_snapshot,
        legal_approver_label_snapshot=row.legal_approver_label_snapshot,
        fixtures_passed_at=row.fixtures_passed_at,
        activated_at=row.activated_at,
        disabled_at=row.disabled_at,
        created_at=row.created_at,
    )


def _calendar_record(
    calendar: LegalWorkingCalendar,
    row: LegalWorkingCalendarVersion,
) -> LegalCalendarVersionRecord:
    return LegalCalendarVersionRecord(
        id=row.id,
        calendar_id=calendar.id,
        key=calendar.key,
        name=calendar.name,
        jurisdiction=calendar.jurisdiction,
        office=calendar.office,
        version=row.version,
        status=row.status,
        timezone=row.timezone,
        weekend_days=list(row.weekend_days_json),
        holidays=list(row.holidays_json),
        exceptional_working_days=list(row.exceptional_working_days_json),
        source_priority=list(row.source_priority_json),
        source_reference=row.source_reference,
        source_hash=row.source_hash,
        effective_from=row.effective_from,
        effective_until=row.effective_until,
        proposer_label_snapshot=row.proposer_label_snapshot,
        approver_label_snapshot=row.approver_label_snapshot,
        approved_at=row.approved_at,
        created_at=row.created_at,
    )


def _responsibility_dict(row: IpResponsibilityAssignment) -> dict:
    return {
        "id": row.id,
        "membership_id": row.membership_id,
        "membership_label_snapshot": row.membership_label_snapshot,
        "role": row.role,
        "effective_from": row.effective_from,
        "effective_until": row.effective_until,
        "accepted_at": row.accepted_at,
        "replacement_source": row.replacement_source,
        "escalation_policy": row.escalation_policy_json,
        "version": row.version,
    }


def _deadline_record(session: Session, row: IpDeadline) -> IpDeadlineRecord:
    responsibilities = list(
        session.scalars(
            select(IpResponsibilityAssignment)
            .where(IpResponsibilityAssignment.deadline_id == row.id)
            .order_by(IpResponsibilityAssignment.created_at)
        ).all()
    )
    return IpDeadlineRecord(
        id=row.id,
        docket_id=row.docket_id,
        trigger_event_id=row.trigger_event_id,
        rule_version_id=row.rule_version_id,
        calendar_version_id=row.calendar_version_id,
        matter_deadline_id=row.matter_deadline_id,
        supersedes_deadline_id=row.supersedes_deadline_id,
        deadline_kind=row.deadline_kind,
        title=row.title,
        trigger_kind=row.trigger_kind,
        base_date=row.base_date,
        date_precision=row.date_precision,
        certainty=row.certainty,
        result_on=row.result_on,
        calculation_inputs=row.calculation_inputs_json,
        calculation_trace=row.calculation_trace_json,
        explanation=row.explanation,
        rule_citation=row.rule_citation,
        engine_version=row.engine_version,
        source_version=row.source_version,
        is_critical=row.is_critical,
        state=row.state,
        version=row.version,
        confirmed_at=row.confirmed_at,
        override_reason=row.override_reason,
        override_evidence_ref=row.override_evidence_ref,
        completed_evidence_ref=row.completed_evidence_ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
        responsibilities=[_responsibility_dict(item) for item in responsibilities],
    )


def propose_rule_version(
    session: Session,
    *,
    context: SessionContext,
    payload: IpRuleVersionProposalRequest,
) -> IpRuleVersionRecord:
    key = payload.key.strip().lower()
    rule_set = session.scalar(select(IpRuleSet).where(IpRuleSet.key == key).with_for_update())
    if rule_set is None:
        rule_set = IpRuleSet(
            key=key,
            rule_kind=payload.rule_kind,
            jurisdiction=payload.jurisdiction.strip().upper(),
            office=payload.office.strip() if payload.office else None,
            right_kind=payload.right_kind.strip().lower(),
            proceeding_kind=(
                payload.proceeding_kind.strip().lower() if payload.proceeding_kind else None
            ),
            role=payload.role.strip().lower() if payload.role else None,
            stage=payload.stage.strip().lower(),
        )
        session.add(rule_set)
        session.flush()
    elif (
        rule_set.rule_kind != payload.rule_kind
        or rule_set.jurisdiction != payload.jurisdiction.strip().upper()
        or rule_set.office != (payload.office.strip() if payload.office else None)
        or rule_set.right_kind != payload.right_kind.strip().lower()
        or rule_set.proceeding_kind
        != (payload.proceeding_kind.strip().lower() if payload.proceeding_kind else None)
        or rule_set.role != (payload.role.strip().lower() if payload.role else None)
        or rule_set.stage != payload.stage.strip().lower()
    ):
        raise HTTPException(status_code=409, detail="Rule key already exists with another scope.")

    next_version = (
        int(
            session.scalar(
                select(func.coalesce(func.max(IpRuleVersion.version), 0)).where(
                    IpRuleVersion.rule_set_id == rule_set.id
                )
            )
            or 0
        )
        + 1
    )
    row = IpRuleVersion(
        rule_set_id=rule_set.id,
        version=next_version,
        status="candidate",
        source_record_id=payload.source_record_id,
        source_hash=payload.source_hash.lower(),
        source_reference=payload.source_reference,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        engine_compatibility=payload.engine_compatibility,
        fixture_set_json=[item.model_dump(mode="json") for item in payload.fixtures],
        definition_json=payload.definition,
        proposed_by_membership_id=context.membership.id,
        proposer_label_snapshot=_actor_label(context),
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip.rule_version.proposed",
        target_type="ip_rule_version",
        target_id=row.id,
        metadata={"rule_set_id": rule_set.id, "version": next_version, "kind": rule_set.rule_kind},
    )
    session.commit()
    session.refresh(row)
    return _rule_record(rule_set, row)


def _ranges_overlap(
    left_from: date,
    left_until: date | None,
    right_from: date,
    right_until: date | None,
) -> bool:
    """Half-open-free inclusive overlap; ``None`` means open ended."""

    if left_until is not None and right_from > left_until:
        return False
    if right_until is not None and left_from > right_until:
        return False
    return True


def _overlapping_active_versions(
    session: Session,
    *,
    row: IpRuleVersion,
) -> list[IpRuleVersion]:
    """Active sibling versions whose effective range collides with ``row``."""

    siblings = session.scalars(
        select(IpRuleVersion).where(
            IpRuleVersion.rule_set_id == row.rule_set_id,
            IpRuleVersion.status == "active",
            IpRuleVersion.id != row.id,
        )
    ).all()
    return [
        sibling
        for sibling in siblings
        if _ranges_overlap(
            row.effective_from,
            row.effective_until,
            sibling.effective_from,
            sibling.effective_until,
        )
    ]


def _rule_fixture_results(row: IpRuleVersion, rule_set: IpRuleSet) -> tuple[list[str], list[str]]:
    fixture_ids: list[str] = []
    passed_ids: list[str] = []
    for fixture in row.fixture_set_json:
        fixture_id = str(fixture.get("id") or "")
        if not fixture_id:
            continue
        fixture_ids.append(fixture_id)
        if rule_set.rule_kind == "deadline":
            calculation = fixture.get("calculation")
            if not calculation:
                continue
            result = calculate_ip_deadline(IpDeadlineCalculationRequest.model_validate(calculation))
            expected_date = fixture.get("expected_result_on")
            if (
                result.state == fixture.get("expected_state")
                and (result.result_on.isoformat() if result.result_on else None) == expected_date
            ):
                passed_ids.append(fixture_id)
        elif fixture.get("expected_outcome") == fixture.get("observed_outcome"):
            passed_ids.append(fixture_id)
    return fixture_ids, passed_ids


def rule_impact(
    session: Session,
    *,
    context: SessionContext,
    rule_version_id: str,
) -> IpRuleImpactResponse:
    row = session.get(IpRuleVersion, rule_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Rule version not found.")
    _assert_rule_governance_access(session, context=context, row=row)

    # RULE-GOV-05: the preview must describe what acting on this version will
    # affect.  Activating a candidate supersedes the active versions whose
    # effective range it collides with, so their open records are in scope.
    # Retiring or disabling an already-active version affects only itself.
    scoped_ids = [row.id]
    if row.status == "candidate":
        scoped_ids.extend(item.id for item in _overlapping_active_versions(session, row=row))

    policy_count = int(
        session.scalar(
            select(func.count())
            .select_from(CompanyIpRulePolicy)
            .where(CompanyIpRulePolicy.active_rule_version_id.in_(scoped_ids))
        )
        or 0
    )
    open_count = int(
        session.scalar(
            select(func.count())
            .select_from(IpDeadline)
            .where(
                IpDeadline.rule_version_id.in_(scoped_ids),
                IpDeadline.state.in_(["confirmed", "overdue"]),
            )
        )
        or 0
    )
    candidate_count = int(
        session.scalar(
            select(func.count())
            .select_from(IpDeadline)
            .where(
                IpDeadline.rule_version_id.in_(scoped_ids),
                IpDeadline.state.in_(["candidate", "provisional"]),
            )
        )
        or 0
    )
    token = sha256(
        "|".join(
            [
                row.id,
                row.status,
                ",".join(sorted(scoped_ids)),
                str(policy_count),
                str(open_count),
                str(candidate_count),
            ]
        ).encode()
    ).hexdigest()
    return IpRuleImpactResponse(
        rule_version_id=row.id,
        impact_token=token,
        company_policy_count=policy_count,
        open_deadline_count=open_count,
        candidate_deadline_count=candidate_count,
    )


def activate_rule_version(
    session: Session,
    *,
    context: SessionContext,
    rule_version_id: str,
    payload: IpRuleActivationRequest,
) -> IpRuleVersionRecord:
    row = session.scalar(
        select(IpRuleVersion).where(IpRuleVersion.id == rule_version_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Rule version not found.")
    _assert_rule_governance_access(session, context=context, row=row)
    if row.status != "candidate":
        raise HTTPException(status_code=409, detail="Only a candidate rule can be activated.")
    rule_set = session.get(IpRuleSet, row.rule_set_id)
    assert rule_set is not None
    proposer = _membership(
        session, context=context, membership_id=str(row.proposed_by_membership_id)
    )
    reviewer = _membership(session, context=context, membership_id=payload.reviewer_membership_id)
    fixture_ids, passed_ids = _rule_fixture_results(row, rule_set)
    assert_rule_can_activate(
        proposer_membership_id=proposer.id,
        reviewer_membership_id=reviewer.id,
        legal_approver_membership_id=context.membership.id,
        fixture_ids=fixture_ids,
        passed_fixture_ids=passed_ids,
    )
    overlapping = _overlapping_active_versions(session, row=row)
    if overlapping and not payload.supersede_overlapping:
        collided = ", ".join(
            str(item.version) for item in sorted(overlapping, key=lambda x: x.version)
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Effective range overlaps active version(s) {collided}; "
                "confirm supersession or correct the effective range."
            ),
        )

    impact = rule_impact(session, context=context, rule_version_id=row.id)
    if (impact.company_policy_count or impact.open_deadline_count) and not (
        payload.impact_acknowledged and len(payload.impact_reason.strip()) >= 5
    ):
        raise HTTPException(
            status_code=409,
            detail="Rule impact must be reviewed before activation.",
        )
    if (
        impact.company_policy_count or impact.open_deadline_count
    ) and payload.impact_token != impact.impact_token:
        raise HTTPException(status_code=409, detail="Rule impact changed; preview again.")

    now = _now()
    for prior in overlapping:
        prior.status = "retired"
    row.status = "active"
    row.reviewed_by_membership_id = reviewer.id
    row.reviewer_label_snapshot = reviewer.user.full_name or reviewer.user.email
    row.legal_approved_by_membership_id = context.membership.id
    row.legal_approver_label_snapshot = _actor_label(context)
    row.fixtures_passed_at = now
    row.activated_at = now

    if payload.select_for_company:
        policy = session.scalar(
            select(CompanyIpRulePolicy)
            .where(
                CompanyIpRulePolicy.company_id == context.company.id,
                CompanyIpRulePolicy.rule_set_id == row.rule_set_id,
            )
            .with_for_update()
        )
        if policy is None:
            policy = CompanyIpRulePolicy(
                company_id=context.company.id,
                rule_set_id=row.rule_set_id,
                active_rule_version_id=row.id,
                auto_confirm_eligible=payload.auto_confirm_eligible,
                internal_target_policy_json=payload.internal_target_policy,
                version=1,
                updated_by_membership_id=context.membership.id,
                updater_label_snapshot=_actor_label(context),
            )
            session.add(policy)
        else:
            policy.active_rule_version_id = row.id
            policy.auto_confirm_eligible = payload.auto_confirm_eligible
            policy.internal_target_policy_json = payload.internal_target_policy
            policy.version += 1
            policy.updated_by_membership_id = context.membership.id
            policy.updater_label_snapshot = _actor_label(context)

    record_from_context(
        session,
        context,
        action="ip.rule_version.activated",
        target_type="ip_rule_version",
        target_id=row.id,
        metadata={
            "reviewer_membership_id": reviewer.id,
            "fixture_ids": fixture_ids,
            "impact_token": impact.impact_token,
            "auto_confirm_eligible": payload.auto_confirm_eligible,
            "superseded_version_ids": [item.id for item in overlapping],
            "confirmed_deadlines_preserved": True,
        },
    )
    session.commit()
    session.refresh(row)
    return _rule_record(rule_set, row)


def transition_rule_version(
    session: Session,
    *,
    context: SessionContext,
    rule_version_id: str,
    payload: IpRuleTransitionRequest,
) -> IpRuleVersionRecord:
    row = session.scalar(
        select(IpRuleVersion).where(IpRuleVersion.id == rule_version_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Rule version not found.")
    _assert_rule_governance_access(session, context=context, row=row)
    impact = rule_impact(session, context=context, rule_version_id=row.id)
    if payload.impact_token != impact.impact_token:
        raise HTTPException(status_code=409, detail="Rule impact changed; preview again.")
    if row.status not in {"active", "approved"}:
        raise HTTPException(status_code=409, detail="Rule version is not active or approved.")
    row.status = "disabled" if payload.emergency_disable else "retired"
    row.disabled_at = _now() if payload.emergency_disable else None

    # RULE-GOV-07: disabling must stop future auto-confirmation for every tenant
    # that selected this version.  Confirmed legal evidence is never rewritten;
    # dependent candidates surface as a ``rule_disabled`` workspace exception.
    suspended_company_ids: list[str] = []
    alerted_membership_ids: list[str] = []
    if payload.emergency_disable:
        affected_policies = list(
            session.scalars(
                select(CompanyIpRulePolicy)
                .where(CompanyIpRulePolicy.active_rule_version_id == row.id)
                .with_for_update()
            ).all()
        )
        for policy in affected_policies:
            suspended_company_ids.append(policy.company_id)
            if policy.auto_confirm_eligible:
                policy.auto_confirm_eligible = False
                policy.version += 1
                policy.updated_by_membership_id = context.membership.id
                policy.updater_label_snapshot = _actor_label(context)
        alerted_membership_ids = _alert_rule_disable(
            session, context=context, row=row, reason=payload.reason
        )

    record_from_context(
        session,
        context,
        action=(
            "ip.rule_version.disabled" if payload.emergency_disable else "ip.rule_version.retired"
        ),
        target_type="ip_rule_version",
        target_id=row.id,
        metadata={
            "reason": payload.reason,
            "impact_token": impact.impact_token,
            "auto_confirm_suspended_company_ids": suspended_company_ids,
            "alerted_membership_ids": alerted_membership_ids,
            "open_deadline_count": impact.open_deadline_count,
            "candidate_deadline_count": impact.candidate_deadline_count,
            "confirmed_deadlines_preserved": True,
        },
    )
    session.commit()
    session.refresh(row)
    rule_set = session.get(IpRuleSet, row.rule_set_id)
    assert rule_set is not None
    return _rule_record(rule_set, row)


def _alert_rule_disable(
    session: Session,
    *,
    context: SessionContext,
    row: IpRuleVersion,
    reason: str,
) -> list[str]:
    """RULE-GOV-07: alert the owners of every record the disabled rule produced.

    This reuses the existing notification dispatcher; it does not create a second
    delivery owner.  Intents are in-app only and keyed by rule/deadline/member so
    a repeated disable cannot duplicate a send.
    """

    affected = list(
        session.scalars(
            select(IpDeadline).where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.rule_version_id == row.id,
                IpDeadline.state.in_(["candidate", "provisional", "confirmed", "overdue"]),
            )
        ).all()
    )
    alerted: list[str] = []
    for deadline in affected:
        matter_id = session.scalar(
            select(IpDocketRecord.matter_id).where(IpDocketRecord.id == deadline.docket_id)
        )
        matter = session.get(Matter, matter_id) if matter_id else None
        assignments = list(
            session.scalars(
                select(IpResponsibilityAssignment).where(
                    IpResponsibilityAssignment.deadline_id == deadline.id,
                    IpResponsibilityAssignment.effective_until.is_(None),
                )
            ).all()
        )
        recipient_ids = {item.membership_id for item in assignments if item.membership_id}
        if not recipient_ids:
            # Nobody owns the record yet; alert the actor so it is not lost.
            recipient_ids = {context.membership.id}
        for membership_id in sorted(recipient_ids):
            member = session.get(CompanyMembership, membership_id)
            if member is None or member.company_id != context.company.id:
                continue
            intent = enqueue_notification_delivery_intent(
                session,
                context=context,
                recipient_membership=member,
                channel="in_app",
                event_type="ip_rule_version_disabled",
                source_type="ip_rule_version",
                source_id=f"{row.id}:{deadline.id}:{member.id}",
                matter=matter,
                title="Legal rule disabled",
                body=(
                    f"The rule version behind '{deadline.title}' was disabled and "
                    f"auto-confirmation is suspended. Reason: {reason}"
                ),
                critical=deadline.is_critical,
                confidentiality_mode="minimal",
                schedule_source_type="ip_rule_version",
                schedule_source_id=row.id,
            )
            if intent is not None:
                alerted.append(member.id)
    return alerted


def _policy_record(
    policy: CompanyIpRulePolicy,
    rule_set: IpRuleSet,
    version: IpRuleVersion,
) -> IpCompanyRulePolicyRecord:
    return IpCompanyRulePolicyRecord(
        id=policy.id,
        rule_set_id=rule_set.id,
        rule_set_key=rule_set.key,
        rule_kind=rule_set.rule_kind,
        active_rule_version_id=version.id,
        active_rule_version=version.version,
        active_rule_status=version.status,
        auto_confirm_eligible=policy.auto_confirm_eligible,
        auto_confirm_suspended_reason=(
            "rule_disabled"
            if version.status == "disabled"
            else ("rule_retired" if version.status == "retired" else None)
        ),
        internal_target_policy=policy.internal_target_policy_json,
        version=policy.version,
        updater_label_snapshot=policy.updater_label_snapshot,
        updated_at=policy.updated_at,
    )


def select_company_rule_version(
    session: Session,
    *,
    context: SessionContext,
    payload: IpCompanyRuleSelectionRequest,
) -> IpCompanyRulePolicyRecord:
    """RULE-GOV-04: select an approved platform rule version for this company.

    A tenant policy can only point at a version the platform already activated;
    it can never make a candidate, retired, or disabled version authoritative.
    """

    version = session.get(IpRuleVersion, payload.rule_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Rule version not found.")
    _assert_rule_governance_access(session, context=context, row=version)
    if version.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Only an active approved rule version can be selected by a company.",
        )
    rule_set = session.get(IpRuleSet, version.rule_set_id)
    assert rule_set is not None

    policy = session.scalar(
        select(CompanyIpRulePolicy)
        .where(
            CompanyIpRulePolicy.company_id == context.company.id,
            CompanyIpRulePolicy.rule_set_id == version.rule_set_id,
        )
        .with_for_update()
    )
    if policy is None:
        if payload.expected_policy_version is not None:
            raise HTTPException(status_code=409, detail="Company policy no longer matches.")
        policy = CompanyIpRulePolicy(
            company_id=context.company.id,
            rule_set_id=version.rule_set_id,
            active_rule_version_id=version.id,
            auto_confirm_eligible=payload.auto_confirm_eligible,
            internal_target_policy_json=payload.internal_target_policy,
            version=1,
            updated_by_membership_id=context.membership.id,
            updater_label_snapshot=_actor_label(context),
        )
        session.add(policy)
    else:
        if (
            payload.expected_policy_version is not None
            and payload.expected_policy_version != policy.version
        ):
            raise HTTPException(status_code=409, detail="Company policy no longer matches.")
        policy.active_rule_version_id = version.id
        policy.auto_confirm_eligible = payload.auto_confirm_eligible
        policy.internal_target_policy_json = payload.internal_target_policy
        policy.version += 1
        policy.updated_by_membership_id = context.membership.id
        policy.updater_label_snapshot = _actor_label(context)

    session.flush()
    record_from_context(
        session,
        context,
        action="ip.rule_policy.selected",
        target_type="company_ip_rule_policy",
        target_id=policy.id,
        metadata={
            "rule_set_id": rule_set.id,
            "rule_version_id": version.id,
            "rule_version": version.version,
            "auto_confirm_eligible": policy.auto_confirm_eligible,
            "policy_version": policy.version,
        },
    )
    session.commit()
    session.refresh(policy)
    return _policy_record(policy, rule_set, version)


def list_company_rule_policies(
    session: Session,
    *,
    context: SessionContext,
) -> list[IpCompanyRulePolicyRecord]:
    rows = list(
        session.execute(
            select(CompanyIpRulePolicy, IpRuleSet, IpRuleVersion)
            .join(IpRuleSet, IpRuleSet.id == CompanyIpRulePolicy.rule_set_id)
            .join(IpRuleVersion, IpRuleVersion.id == CompanyIpRulePolicy.active_rule_version_id)
            .where(CompanyIpRulePolicy.company_id == context.company.id)
            .order_by(IpRuleSet.key)
        ).all()
    )
    return [_policy_record(policy, rule_set, version) for policy, rule_set, version in rows]


def propose_calendar_version(
    session: Session,
    *,
    context: SessionContext,
    payload: LegalCalendarVersionProposalRequest,
) -> LegalCalendarVersionRecord:
    key = payload.key.strip().lower()
    calendar = session.scalar(
        select(LegalWorkingCalendar)
        .where(
            LegalWorkingCalendar.company_id == context.company.id,
            LegalWorkingCalendar.key == key,
        )
        .with_for_update()
    )
    if calendar is None:
        calendar = LegalWorkingCalendar(
            company_id=context.company.id,
            key=key,
            name=payload.name,
            jurisdiction=payload.jurisdiction.strip().upper(),
            office=payload.office.strip() if payload.office else None,
            created_by_membership_id=context.membership.id,
        )
        session.add(calendar)
        session.flush()
    elif calendar.jurisdiction != payload.jurisdiction.strip().upper() or calendar.office != (
        payload.office.strip() if payload.office else None
    ):
        raise HTTPException(status_code=409, detail="Calendar key already has another scope.")
    next_version = (
        int(
            session.scalar(
                select(func.coalesce(func.max(LegalWorkingCalendarVersion.version), 0)).where(
                    LegalWorkingCalendarVersion.calendar_id == calendar.id
                )
            )
            or 0
        )
        + 1
    )
    row = LegalWorkingCalendarVersion(
        company_id=context.company.id,
        calendar_id=calendar.id,
        version=next_version,
        status="candidate",
        timezone=payload.timezone,
        weekend_days_json=payload.weekend_days,
        holidays_json=[value.isoformat() for value in payload.holidays],
        exceptional_working_days_json=[
            value.isoformat() for value in payload.exceptional_working_days
        ],
        source_priority_json=payload.source_priority,
        source_reference=payload.source_reference,
        source_hash=payload.source_hash.lower(),
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        proposed_by_membership_id=context.membership.id,
        proposer_label_snapshot=_actor_label(context),
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip.working_calendar.proposed",
        target_type="legal_working_calendar_version",
        target_id=row.id,
        metadata={"calendar_id": calendar.id, "version": next_version},
    )
    session.commit()
    session.refresh(row)
    return _calendar_record(calendar, row)


def activate_calendar_version(
    session: Session,
    *,
    context: SessionContext,
    calendar_version_id: str,
    payload: LegalCalendarActivationRequest,
) -> LegalCalendarVersionRecord:
    row = session.scalar(
        select(LegalWorkingCalendarVersion)
        .where(
            LegalWorkingCalendarVersion.id == calendar_version_id,
            LegalWorkingCalendarVersion.company_id == context.company.id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Calendar version not found.")
    if row.status != "candidate":
        raise HTTPException(status_code=409, detail="Only a candidate calendar can activate.")
    if row.proposed_by_membership_id == context.membership.id:
        raise HTTPException(status_code=409, detail="Calendar proposer cannot self-approve.")
    prior_active = list(
        session.scalars(
            select(LegalWorkingCalendarVersion).where(
                LegalWorkingCalendarVersion.calendar_id == row.calendar_id,
                LegalWorkingCalendarVersion.status == "active",
                LegalWorkingCalendarVersion.id != row.id,
            )
        ).all()
    )
    if prior_active and not payload.conflict_reviewed:
        raise HTTPException(status_code=409, detail="Calendar source conflict review is required.")
    for prior in prior_active:
        prior.status = "retired"
    row.status = "active"
    row.approved_by_membership_id = context.membership.id
    row.approver_label_snapshot = _actor_label(context)
    row.approved_at = _now()
    record_from_context(
        session,
        context,
        action="ip.working_calendar.activated",
        target_type="legal_working_calendar_version",
        target_id=row.id,
        metadata={"reason": payload.reason, "prior_active_ids": [item.id for item in prior_active]},
    )
    session.commit()
    session.refresh(row)
    calendar = session.get(LegalWorkingCalendar, row.calendar_id)
    assert calendar is not None
    return _calendar_record(calendar, row)


def _calendar_snapshot(row: LegalWorkingCalendarVersion) -> LegalCalendarSnapshot:
    return LegalCalendarSnapshot(
        calendar_version_id=row.id,
        timezone=row.timezone,
        weekend_days=list(row.weekend_days_json),
        holidays=[date.fromisoformat(value) for value in row.holidays_json],
        exceptional_working_days=[
            date.fromisoformat(value) for value in row.exceptional_working_days_json
        ],
        source_reference=row.source_reference,
        source_hash=row.source_hash,
    )


def propose_deadline(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpDeadlineProposalRequest,
) -> IpDeadlineRecord:
    docket = _docket_or_404(session, context=context, docket_id=docket_id, for_update=True)
    rule = session.get(IpRuleVersion, payload.rule_version_id)
    if rule is None or rule.status != "active":
        raise HTTPException(status_code=409, detail="An active rule version is required.")
    rule_set = session.get(IpRuleSet, rule.rule_set_id)
    assert rule_set is not None
    if rule_set.rule_kind != "deadline":
        raise HTTPException(status_code=409, detail="Selected rule is not a deadline rule.")
    policy = session.scalar(
        select(CompanyIpRulePolicy).where(
            CompanyIpRulePolicy.company_id == context.company.id,
            CompanyIpRulePolicy.rule_set_id == rule.rule_set_id,
            CompanyIpRulePolicy.active_rule_version_id == rule.id,
        )
    )
    if policy is None:
        raise HTTPException(status_code=409, detail="Company policy has not selected this rule.")
    calendar = session.scalar(
        select(LegalWorkingCalendarVersion).where(
            LegalWorkingCalendarVersion.id == payload.calendar_version_id,
            LegalWorkingCalendarVersion.company_id == context.company.id,
            LegalWorkingCalendarVersion.status == "active",
        )
    )
    if calendar is None:
        raise HTTPException(status_code=409, detail="An active company calendar is required.")
    if payload.trigger_event_id:
        trigger = session.scalar(
            select(IpDocketEvent.id).where(
                IpDocketEvent.id == payload.trigger_event_id,
                IpDocketEvent.docket_id == docket.id,
                IpDocketEvent.company_id == context.company.id,
            )
        )
        if trigger is None:
            raise HTTPException(status_code=404, detail="Trigger event not found.")
    definition = IpDeadlineRuleDefinition.model_validate(rule.definition_json)
    calculation_payload = IpDeadlineCalculationRequest(
        deadline_kind=definition.deadline_kind,
        trigger_kind=definition.trigger_kind,
        base_date=payload.base_date,
        base_date_certainty=payload.base_date_certainty,
        duration_value=definition.duration_value,
        duration_unit=definition.duration_unit,
        calendar_method=definition.calendar_method,
        direction=definition.direction,
        include_base_date=definition.include_base_date,
        next_working_day=definition.next_working_day,
        extension_days=definition.extension_days,
        rule_version_id=rule.id,
        rule_citation=definition.rule_citation,
        source_version=rule.source_record_id,
        engine_version=rule.engine_compatibility,
        calendar=_calendar_snapshot(calendar),
    )
    result = calculate_ip_deadline(calculation_payload)
    row = IpDeadline(
        company_id=context.company.id,
        docket_id=docket.id,
        trigger_event_id=payload.trigger_event_id,
        rule_version_id=rule.id,
        calendar_version_id=calendar.id,
        deadline_kind=definition.deadline_kind,
        title=payload.title,
        trigger_kind=definition.trigger_kind,
        base_date=payload.base_date,
        duration_value=definition.duration_value,
        duration_unit=definition.duration_unit,
        calendar_method=definition.calendar_method,
        timezone=calendar.timezone,
        date_precision=payload.date_precision,
        certainty=result.certainty,
        result_on=result.result_on,
        calculation_inputs_json=result.inputs,
        calculation_trace_json=result.trace,
        explanation=result.explanation,
        rule_citation=definition.rule_citation,
        engine_version=rule.engine_compatibility,
        source_version=rule.source_record_id,
        is_critical=payload.is_critical,
        state=result.state,
        version=1,
        created_by_membership_id=context.membership.id,
        creator_label_snapshot=_actor_label(context),
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip.deadline.proposed",
        target_type="ip_deadline",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"state": row.state, "result_on": row.result_on, "rule_version_id": rule.id},
    )
    session.commit()
    session.refresh(row)
    return _deadline_record(session, row)


def deadline_impact(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
) -> IpDeadlineImpactResponse:
    row = session.scalar(
        select(IpDeadline).where(
            IpDeadline.id == deadline_id,
            IpDeadline.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="IP deadline not found.")
    _docket_or_404(session, context=context, docket_id=row.docket_id)
    operational_ids = list(
        session.scalars(
            select(MatterDeadline.id).where(
                MatterDeadline.source_ref_id == row.id,
                MatterDeadline.source_ref_type.in_(["ip_deadline", "ip_deadline_internal_target"]),
            )
        ).all()
    )
    intent_ids = list(
        session.scalars(
            select(NotificationDeliveryIntent.id).where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.schedule_source_type == "ip_deadline",
                NotificationDeliveryIntent.schedule_source_id == row.id,
                NotificationDeliveryIntent.status.in_(["queued", "retry_scheduled"]),
            )
        ).all()
    )
    responsibility_ids = list(
        session.scalars(
            select(IpResponsibilityAssignment.id).where(
                IpResponsibilityAssignment.deadline_id == row.id,
                IpResponsibilityAssignment.effective_until.is_(None),
            )
        ).all()
    )
    token = sha256(
        "|".join(
            [
                row.id,
                str(row.version),
                *sorted(operational_ids),
                *sorted(intent_ids),
                *sorted(responsibility_ids),
            ]
        ).encode()
    ).hexdigest()
    return IpDeadlineImpactResponse(
        deadline_id=row.id,
        expected_version=row.version,
        impact_token=token,
        operational_deadline_ids=operational_ids,
        notification_intent_ids=intent_ids,
        active_responsibility_ids=responsibility_ids,
    )


def _lock_deadline(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
    expected_version: int,
) -> tuple[IpDeadline, object]:
    row = session.scalar(
        select(IpDeadline)
        .where(IpDeadline.id == deadline_id, IpDeadline.company_id == context.company.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="IP deadline not found.")
    if row.version != expected_version:
        raise HTTPException(status_code=409, detail="Deadline changed; reload and retry.")
    docket = _docket_or_404(session, context=context, docket_id=row.docket_id, for_update=True)
    return row, docket


def _validate_responsibilities(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    values: list[IpResponsibilityInput],
    critical: bool,
) -> tuple[
    list[tuple[IpResponsibilityInput, CompanyMembership]],
    CompanyMembership,
    CompanyMembership | None,
]:
    if len({(item.membership_id, item.role) for item in values}) != len(values):
        raise HTTPException(
            status_code=409,
            detail="Responsibility assignments contain duplicates.",
        )
    if sum(item.role == "primary" for item in values) != 1:
        raise HTTPException(
            status_code=409,
            detail="Exactly one primary responsibility is required.",
        )
    resolved: list[tuple[IpResponsibilityInput, CompanyMembership]] = []
    for item in values:
        member = _membership(session, context=context, membership_id=item.membership_id)
        member_context = SessionContext(
            company=context.company, user=member.user, membership=member
        )
        if not can_access(session, context=member_context, matter=matter):
            raise HTTPException(
                status_code=409,
                detail="Responsible user cannot access the Matter.",
            )
        resolved.append((item, member))
    evidence = [
        ResponsibilityEvidence(
            membership_id=item.membership_id,
            role=item.role,
            accepted=item.accepted,
        )
        for item, _ in resolved
    ]
    if critical:
        assert_critical_deadline_coverage(evidence)
    primary = next(member for item, member in resolved if item.role == "primary")
    backup = next(
        (member for item, member in resolved if item.role in {"backup", "supervisor", "docketing"}),
        None,
    )
    return resolved, primary, backup


def _cancel_deadline_impacts(
    session: Session,
    *,
    context: SessionContext,
    row: IpDeadline,
) -> None:
    children = list(
        session.scalars(
            select(MatterDeadline).where(
                MatterDeadline.source_ref_id == row.id,
                MatterDeadline.source_ref_type.in_(["ip_deadline", "ip_deadline_internal_target"]),
                MatterDeadline.status.in_(["open", "missed"]),
            )
        ).all()
    )
    for child in children:
        update_deadline(
            session,
            context=context,
            matter_id=child.matter_id,
            deadline_id=child.id,
            payload=MatterDeadlineUpdateRequest(status="cancelled"),
            commit=False,
        )
    cancel_pending_notification_intents(
        session,
        company_id=context.company.id,
        schedule_source_type="ip_deadline",
        schedule_source_id=row.id,
    )


def _copy_deadline(
    source: IpDeadline,
    *,
    result_on: date | None,
    state: str,
    reason: str,
    evidence_reference: str,
    context: SessionContext,
    trigger_event_id: str | None = None,
    calculation_inputs: dict | None = None,
    calculation_trace: list[dict] | None = None,
    explanation: str | None = None,
) -> IpDeadline:
    return IpDeadline(
        company_id=source.company_id,
        docket_id=source.docket_id,
        trigger_event_id=(
            trigger_event_id if trigger_event_id is not None else source.trigger_event_id
        ),
        rule_version_id=source.rule_version_id,
        calendar_version_id=source.calendar_version_id,
        supersedes_deadline_id=source.id,
        deadline_kind=source.deadline_kind,
        title=source.title,
        trigger_kind=source.trigger_kind,
        base_date=source.base_date,
        duration_value=source.duration_value,
        duration_unit=source.duration_unit,
        calendar_method=source.calendar_method,
        timezone=source.timezone,
        date_precision=source.date_precision,
        certainty="certain" if result_on else source.certainty,
        result_on=result_on,
        calculation_inputs_json=calculation_inputs or dict(source.calculation_inputs_json),
        calculation_trace_json=calculation_trace or list(source.calculation_trace_json),
        explanation=explanation or source.explanation,
        rule_citation=source.rule_citation,
        engine_version=source.engine_version,
        source_version=source.source_version,
        is_critical=source.is_critical,
        state=state,
        version=1,
        override_reason=reason,
        override_evidence_ref=evidence_reference,
        created_by_membership_id=context.membership.id,
        creator_label_snapshot=_actor_label(context),
    )


def _confirm_row(
    session: Session,
    *,
    context: SessionContext,
    row: IpDeadline,
    docket: object,
    responsibilities: list[IpResponsibilityInput],
    internal_target_on: date | None,
    reminder_offsets_days: list[int],
) -> None:
    if row.result_on is None:
        raise HTTPException(
            status_code=409,
            detail="A provisional deadline needs a sourced correction.",
        )
    matter_id = getattr(docket, "matter_id", None)
    if not matter_id:
        raise HTTPException(
            status_code=409,
            detail="Link an operational Matter before confirmation.",
        )
    matter = session.get(Matter, matter_id)
    if matter is None:
        raise HTTPException(status_code=409, detail="Linked Matter is unavailable.")
    resolved, primary, backup = _validate_responsibilities(
        session,
        context=context,
        matter=matter,
        values=responsibilities,
        critical=row.is_critical,
    )
    source_type, source_id = operational_projection_reference(row.id)
    operational = create_deadline(
        session,
        context=context,
        matter_id=matter.id,
        source="ip_deadline",
        kind="legal_deadline",
        title=row.title,
        due_on=row.result_on,
        notes=f"{row.rule_citation} | legal evidence {row.id}",
        assignee_membership_id=primary.id,
        source_ref_type=source_type,
        source_ref_id=source_id,
        commit=False,
    )
    row.matter_deadline_id = operational.id
    now = _now()
    for item, member in resolved:
        session.add(
            IpResponsibilityAssignment(
                company_id=context.company.id,
                docket_id=row.docket_id,
                deadline_id=row.id,
                membership_id=member.id,
                membership_label_snapshot=member.user.full_name or member.user.email,
                role=item.role,
                effective_from=now,
                accepted_at=now if item.accepted else None,
                replacement_source=item.replacement_source,
                escalation_policy_json=item.escalation_policy,
                version=1,
                created_by_membership_id=context.membership.id,
                creator_label_snapshot=_actor_label(context),
            )
        )
    session.add(
        IpDeadlineCoverage(
            company_id=context.company.id,
            docket_id=row.docket_id,
            matter_deadline_id=operational.id,
            responsible_membership_id=primary.id,
            backup_membership_id=backup.id if backup else None,
            coverage_status="accepted",
            calendar_projection_status="projected",
            accepted_at=now,
            reassignment_version=1,
        )
    )
    if internal_target_on is not None:
        create_deadline(
            session,
            context=context,
            matter_id=matter.id,
            source="ip_deadline",
            kind="internal_target",
            title=f"Internal target: {row.title}",
            due_on=internal_target_on,
            notes=f"Dependent on legal deadline {row.id}",
            assignee_membership_id=primary.id,
            source_ref_type="ip_deadline_internal_target",
            source_ref_id=row.id,
            commit=False,
        )
    zone = ZoneInfo(row.timezone)
    for item, member in resolved:
        if not item.accepted:
            continue
        for offset in sorted(set(reminder_offsets_days), reverse=True):
            scheduled = datetime.combine(
                row.result_on - timedelta(days=offset), time(hour=9), tzinfo=zone
            ).astimezone(UTC)
            enqueue_notification_delivery_intent(
                session,
                context=context,
                recipient_membership=member,
                channel="in_app",
                event_type="ip_deadline_reminder",
                source_type="ip_deadline",
                source_id=f"{row.id}:{member.id}:{offset}",
                matter=matter,
                title=f"IP deadline: {row.title}",
                body=f"Due {row.result_on.isoformat()}; {row.explanation}",
                scheduled_for=scheduled,
                critical=row.is_critical,
                escalation_membership=backup,
                schedule_source_type="ip_deadline",
                schedule_source_id=row.id,
            )
    row.state = "confirmed"
    row.version += 1
    row.confirmed_by_membership_id = context.membership.id
    row.confirmer_label_snapshot = _actor_label(context)
    row.confirmed_at = now


def confirm_deadline(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
    payload: IpDeadlineConfirmRequest,
) -> IpDeadlineRecord:
    row, docket = _lock_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        expected_version=payload.expected_version,
    )
    if row.state not in {"candidate", "provisional"}:
        raise HTTPException(status_code=409, detail="Only a proposed deadline can be confirmed.")
    rule = session.get(IpRuleVersion, row.rule_version_id)
    if rule is None or rule.status != "active":
        raise HTTPException(status_code=409, detail="The governing rule is not active.")
    if row.supersedes_deadline_id:
        prior = session.scalar(
            select(IpDeadline).where(IpDeadline.id == row.supersedes_deadline_id).with_for_update()
        )
        if prior and prior.state in {"confirmed", "overdue"}:
            impact = deadline_impact(session, context=context, deadline_id=prior.id)
            if payload.impact_token != impact.impact_token:
                raise HTTPException(
                    status_code=409,
                    detail="Deadline impact changed; preview again.",
                )
            _cancel_deadline_impacts(session, context=context, row=prior)
            prior.state = "superseded"
            prior.version += 1
    if payload.corrected_result_on and payload.corrected_result_on != row.result_on:
        corrected = _copy_deadline(
            row,
            result_on=payload.corrected_result_on,
            state="candidate",
            reason=payload.correction_reason or "Sourced correction",
            evidence_reference=payload.correction_evidence_reference or "required",
            context=context,
            calculation_inputs={
                **row.calculation_inputs_json,
                "confirmed_correction": payload.corrected_result_on.isoformat(),
            },
            calculation_trace=[
                *row.calculation_trace_json,
                {
                    "operation": "sourced_confirmation_correction",
                    "date": payload.corrected_result_on.isoformat(),
                    "evidence_reference": payload.correction_evidence_reference,
                },
            ],
            explanation=(
                f"{row.explanation} Confirmed correction to "
                f"{payload.corrected_result_on.isoformat()} with retained evidence."
            ),
        )
        row.state = "superseded"
        row.version += 1
        session.add(corrected)
        session.flush()
        row = corrected
    _confirm_row(
        session,
        context=context,
        row=row,
        docket=docket,
        responsibilities=payload.responsibilities,
        internal_target_on=payload.internal_target_on,
        reminder_offsets_days=payload.reminder_offsets_days,
    )
    record_from_context(
        session,
        context,
        action="ip.deadline.confirmed",
        target_type="ip_deadline",
        target_id=row.id,
        matter_id=getattr(docket, "matter_id", None),
        metadata={
            "result_on": row.result_on,
            "matter_deadline_id": row.matter_deadline_id,
            "reminder_offsets_days": payload.reminder_offsets_days,
        },
    )
    session.commit()
    session.refresh(row)
    return _deadline_record(session, row)


def override_deadline(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
    payload: IpDeadlineOverrideRequest,
) -> IpDeadlineRecord:
    row, docket = _lock_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        expected_version=payload.expected_version,
    )
    if row.state not in {"confirmed", "overdue"}:
        raise HTTPException(status_code=409, detail="Only an active deadline can be overridden.")
    impact = deadline_impact(session, context=context, deadline_id=row.id)
    if payload.impact_token != impact.impact_token:
        raise HTTPException(status_code=409, detail="Deadline impact changed; preview again.")
    _cancel_deadline_impacts(session, context=context, row=row)
    row.state = "superseded"
    row.version += 1
    replacement = _copy_deadline(
        row,
        result_on=payload.new_result_on,
        state="candidate",
        reason=payload.reason,
        evidence_reference=payload.evidence_reference,
        context=context,
        calculation_inputs={
            **row.calculation_inputs_json,
            "override_result_on": payload.new_result_on.isoformat(),
        },
        calculation_trace=[
            *row.calculation_trace_json,
            {
                "operation": "approved_override",
                "date": payload.new_result_on.isoformat(),
                "evidence_reference": payload.evidence_reference,
            },
        ],
        explanation=(
            f"{row.explanation} Authorized override to {payload.new_result_on.isoformat()} "
            "with the original calculation retained."
        ),
    )
    session.add(replacement)
    session.flush()
    _confirm_row(
        session,
        context=context,
        row=replacement,
        docket=docket,
        responsibilities=payload.responsibilities,
        internal_target_on=payload.internal_target_on,
        reminder_offsets_days=payload.reminder_offsets_days,
    )
    record_from_context(
        session,
        context,
        action="ip.deadline.overridden",
        target_type="ip_deadline",
        target_id=replacement.id,
        matter_id=getattr(docket, "matter_id", None),
        metadata={
            "superseded_deadline_id": row.id,
            "impact_token": impact.impact_token,
            "evidence_reference": payload.evidence_reference,
        },
    )
    session.commit()
    session.refresh(replacement)
    return _deadline_record(session, replacement)


def recalculate_deadline(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
    payload: IpDeadlineRecalculateRequest,
) -> IpDeadlineRecord:
    row, docket = _lock_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        expected_version=payload.expected_version,
    )
    if row.state not in {"confirmed", "overdue", "candidate", "provisional"}:
        raise HTTPException(
            status_code=409,
            detail="Deadline cannot be recalculated in this state.",
        )
    rule = session.get(IpRuleVersion, row.rule_version_id)
    calendar = session.get(LegalWorkingCalendarVersion, row.calendar_version_id)
    if rule is None or rule.status != "active" or calendar is None or calendar.status != "active":
        raise HTTPException(status_code=409, detail="Active rule and calendar are required.")
    definition = IpDeadlineRuleDefinition.model_validate(rule.definition_json)
    request = IpDeadlineCalculationRequest(
        deadline_kind=definition.deadline_kind,
        trigger_kind=definition.trigger_kind,
        base_date=payload.base_date,
        base_date_certainty=payload.base_date_certainty,
        duration_value=definition.duration_value,
        duration_unit=definition.duration_unit,
        calendar_method=definition.calendar_method,
        direction=definition.direction,
        include_base_date=definition.include_base_date,
        next_working_day=definition.next_working_day,
        extension_days=definition.extension_days,
        rule_version_id=rule.id,
        rule_citation=definition.rule_citation,
        source_version=rule.source_record_id,
        engine_version=rule.engine_compatibility,
        calendar=_calendar_snapshot(calendar),
    )
    result = calculate_ip_deadline(request)
    replacement = _copy_deadline(
        row,
        result_on=result.result_on,
        state=result.state,
        reason=payload.reason,
        evidence_reference=payload.evidence_reference,
        context=context,
        trigger_event_id=payload.trigger_event_id,
        calculation_inputs=result.inputs,
        calculation_trace=result.trace,
        explanation=result.explanation,
    )
    replacement.base_date = payload.base_date
    replacement.certainty = result.certainty
    session.add(replacement)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip.deadline.recalculation_proposed",
        target_type="ip_deadline",
        target_id=replacement.id,
        matter_id=getattr(docket, "matter_id", None),
        metadata={
            "predecessor_id": row.id,
            "state": replacement.state,
            "evidence_reference": payload.evidence_reference,
        },
    )
    session.commit()
    session.refresh(replacement)
    return _deadline_record(session, replacement)


def complete_deadline(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
    payload: IpDeadlineCompleteRequest,
) -> IpDeadlineRecord:
    row, docket = _lock_deadline(
        session,
        context=context,
        deadline_id=deadline_id,
        expected_version=payload.expected_version,
    )
    if row.state not in {"confirmed", "overdue"}:
        raise HTTPException(status_code=409, detail="Only an active legal deadline can complete.")
    if row.matter_deadline_id:
        operational = session.get(MatterDeadline, row.matter_deadline_id)
        if operational is None:
            raise HTTPException(status_code=409, detail="Operational deadline evidence is missing.")
        update_deadline(
            session,
            context=context,
            matter_id=operational.matter_id,
            deadline_id=operational.id,
            payload=MatterDeadlineUpdateRequest(status="done"),
            commit=False,
        )
    row.state = "completed"
    row.version += 1
    row.completed_evidence_ref = payload.evidence_reference
    cancel_pending_notification_intents(
        session,
        company_id=context.company.id,
        schedule_source_type="ip_deadline",
        schedule_source_id=row.id,
    )
    record_from_context(
        session,
        context,
        action="ip.deadline.completed",
        target_type="ip_deadline",
        target_id=row.id,
        matter_id=getattr(docket, "matter_id", None),
        metadata={
            "evidence_reference": payload.evidence_reference,
            "attestation": payload.attestation,
        },
    )
    session.commit()
    session.refresh(row)
    return _deadline_record(session, row)


def deadline_workspace(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> IpDeadlineWorkspaceResponse:
    _docket_or_404(session, context=context, docket_id=docket_id)
    company_member_ids = select(CompanyMembership.id).where(
        CompanyMembership.company_id == context.company.id
    )
    company_selected_rule_ids = select(CompanyIpRulePolicy.active_rule_version_id).where(
        CompanyIpRulePolicy.company_id == context.company.id
    )
    rule_rows = list(
        session.execute(
            select(IpRuleSet, IpRuleVersion)
            .join(IpRuleVersion, IpRuleVersion.rule_set_id == IpRuleSet.id)
            .where(
                or_(
                    IpRuleVersion.id.in_(company_selected_rule_ids),
                    IpRuleVersion.proposed_by_membership_id.in_(company_member_ids),
                )
            )
            .order_by(IpRuleSet.key, IpRuleVersion.version.desc())
        ).all()
    )
    calendar_rows = list(
        session.execute(
            select(LegalWorkingCalendar, LegalWorkingCalendarVersion)
            .join(
                LegalWorkingCalendarVersion,
                LegalWorkingCalendarVersion.calendar_id == LegalWorkingCalendar.id,
            )
            .where(LegalWorkingCalendar.company_id == context.company.id)
            .order_by(LegalWorkingCalendar.key, LegalWorkingCalendarVersion.version.desc())
        ).all()
    )
    deadlines = list(
        session.scalars(
            select(IpDeadline)
            .where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.docket_id == docket_id,
            )
            .order_by(IpDeadline.created_at.desc())
        ).all()
    )
    today = date.today()
    exceptions: list[IpDeadlineExceptionRecord] = []
    for row in deadlines:
        if row.state in {"completed", "superseded", "cancelled"}:
            continue
        assignments = list(
            session.scalars(
                select(IpResponsibilityAssignment).where(
                    IpResponsibilityAssignment.deadline_id == row.id,
                    IpResponsibilityAssignment.effective_until.is_(None),
                )
            ).all()
        )
        kinds: list[str] = []
        if (
            row.is_critical
            and row.result_on
            and row.result_on < today
            and row.state in {"confirmed", "candidate"}
        ):
            kinds.append("overdue")
        if row.is_critical and not assignments:
            kinds.append("unowned")
        if row.is_critical and assignments and not any(item.accepted_at for item in assignments):
            kinds.append("unacknowledged")
        if row.certainty == "conflicting":
            kinds.append("conflicting")
        elif row.certainty in {"uncertain", "unknown"}:
            kinds.append("uncertain")
        rule = session.get(IpRuleVersion, row.rule_version_id)
        calendar = session.get(LegalWorkingCalendarVersion, row.calendar_version_id)
        if rule is None or rule.status == "disabled":
            kinds.append("rule_disabled")
        if (
            rule is None
            or (rule.effective_until and rule.effective_until < today)
            or calendar is None
            or (calendar.effective_until and calendar.effective_until < today)
        ):
            kinds.append("source_stale")
        if kinds:
            exceptions.append(
                IpDeadlineExceptionRecord(
                    deadline_id=row.id,
                    docket_id=row.docket_id,
                    exception_kinds=kinds,
                    critical=row.is_critical,
                    result_on=row.result_on,
                )
            )
    return IpDeadlineWorkspaceResponse(
        docket_id=docket_id,
        rules=[_rule_record(rule_set, row) for rule_set, row in rule_rows],
        calendars=[_calendar_record(calendar, row) for calendar, row in calendar_rows],
        deadlines=[_deadline_record(session, row) for row in deadlines],
        exceptions=exceptions,
    )


def deadline_dependencies(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
) -> IpDeadlineDependencyResponse:
    """CAL-OPS-06 - explain which inputs produced this deadline's current date.

    Pure read over stored evidence. It never recomputes the date, so a rule or
    calendar that has since changed cannot silently rewrite the explanation. An
    input that can no longer be resolved is reported as unavailable rather than
    omitted, so an incomplete chain is visible instead of looking complete.
    """

    row = session.scalar(
        select(IpDeadline).where(
            IpDeadline.id == deadline_id,
            IpDeadline.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Deadline not found.")
    _docket_or_404(session, context=context, docket_id=row.docket_id)

    nodes: list[IpDeadlineDependencyNode] = []
    unavailable: list[str] = []

    def add(kind: str, reference_id, label: str, detail: str | None, available: bool) -> None:
        nodes.append(
            IpDeadlineDependencyNode(
                kind=kind,
                reference_id=reference_id,
                label=label,
                detail=detail,
                available=available,
            )
        )
        if not available:
            unavailable.append(kind)

    # Trigger event
    if row.trigger_event_id:
        event = session.get(IpDocketEvent, row.trigger_event_id)
        if event is None:
            add("trigger_event", row.trigger_event_id, "Trigger event", None, False)
        else:
            add(
                "trigger_event",
                event.id,
                f"{event.event_kind} ({event.source})",
                f"effective {event.effective_at.date().isoformat()}",
                True,
            )
    else:
        add(
            "trigger_event",
            None,
            f"Manual base date ({row.trigger_kind})",
            row.base_date.isoformat() if row.base_date else "no base date recorded",
            row.base_date is not None,
        )

    # Rule version
    rule = session.get(IpRuleVersion, row.rule_version_id)
    if rule is None:
        add("rule_version", row.rule_version_id, "Rule version", None, False)
    else:
        rule_set = session.get(IpRuleSet, rule.rule_set_id)
        add(
            "rule_version",
            rule.id,
            f"{rule_set.key} v{rule.version}" if rule_set else f"rule v{rule.version}",
            f"status {rule.status}; {row.rule_citation}",
            True,
        )

    # Calendar version
    calendar = session.get(LegalWorkingCalendarVersion, row.calendar_version_id)
    if calendar is None:
        add("calendar_version", row.calendar_version_id, "Working calendar", None, False)
    else:
        add(
            "calendar_version",
            calendar.id,
            f"calendar v{calendar.version} ({calendar.timezone})",
            f"status {calendar.status}; {len(calendar.holidays_json or [])} holidays",
            True,
        )

    # Extension, when the stored inputs recorded one
    inputs = row.calculation_inputs_json or {}
    extension_days = inputs.get("extension_days") or 0
    if extension_days:
        add(
            "extension",
            None,
            f"Extension of {extension_days} day(s)",
            "recorded in the stored calculation inputs",
            True,
        )

    # Predecessor deadline chain
    chain: list[str] = []
    seen: set[str] = {row.id}
    cursor = row.supersedes_deadline_id
    while cursor and cursor not in seen:
        seen.add(cursor)
        predecessor = session.get(IpDeadline, cursor)
        if predecessor is None or predecessor.company_id != context.company.id:
            add("predecessor_deadline", cursor, "Superseded deadline", None, False)
            break
        chain.append(predecessor.id)
        add(
            "predecessor_deadline",
            predecessor.id,
            f"Superseded: {predecessor.title}",
            (
                f"was {predecessor.result_on.isoformat()}"
                if predecessor.result_on
                else "no date"
            ),
            True,
        )
        cursor = predecessor.supersedes_deadline_id

    if row.override_reason:
        add(
            "override",
            None,
            "Manual override",
            row.override_reason,
            True,
        )

    return IpDeadlineDependencyResponse(
        deadline_id=row.id,
        docket_id=row.docket_id,
        state=row.state,
        result_on=row.result_on,
        certainty=row.certainty,
        is_critical=row.is_critical,
        engine_version=row.engine_version,
        source_version=row.source_version,
        rule_citation=row.rule_citation,
        explanation=row.explanation,
        nodes=nodes,
        calculation_trace=list(row.calculation_trace_json or []),
        unavailable_inputs=sorted(set(unavailable)),
        superseded_chain=chain,
    )


def preview_deadline_notifications(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
    payload: IpNotificationPreviewRequest,
) -> IpNotificationPreviewResponse:
    """NOTIF preview - show the reminder plan without creating any intent.

    The schedule mirrors ``confirm_deadline`` exactly (09:00 in the deadline's
    timezone, ``offset`` days before the result date) so the preview cannot
    drift from what confirmation would actually enqueue. Recipient eligibility
    is re-derived here rather than assumed, so a member who has lost access
    shows as withheld before anyone relies on the reminder.
    """

    row = session.scalar(
        select(IpDeadline).where(
            IpDeadline.id == deadline_id,
            IpDeadline.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Deadline not found.")
    docket = _docket_or_404(session, context=context, docket_id=row.docket_id)

    matter = session.get(Matter, docket.matter_id) if docket.matter_id else None
    zone = ZoneInfo(row.timezone)
    offsets = sorted({int(value) for value in payload.reminder_offsets_days if value >= 0})

    planned: list[IpNotificationPlanEntry] = []
    withheld = 0
    for item in payload.responsibilities:
        member = session.scalar(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.id == item.membership_id,
                CompanyMembership.company_id == context.company.id,
            )
        )
        label = ""
        withheld_reason: str | None = None
        if member is None:
            withheld_reason = "membership_not_found"
        else:
            label = member.user.full_name or member.user.email
            if not member.is_active or not member.user.is_active:
                withheld_reason = "membership_inactive"
            elif not item.accepted:
                withheld_reason = "responsibility_not_acknowledged"
            elif matter is not None and not can_access(
                session,
                context=_recipient_context(actor_context=context, membership=member),
                matter=matter,
            ):
                # UJ-10-EXC-03: a permission change is visible before dispatch.
                withheld_reason = "recipient_lost_access"

        for offset in offsets:
            if row.result_on is None:
                continue
            scheduled = datetime.combine(
                row.result_on - timedelta(days=offset), time(hour=9), tzinfo=zone
            ).astimezone(UTC)
            planned.append(
                IpNotificationPlanEntry(
                    recipient_membership_id=item.membership_id,
                    recipient_label=label,
                    role=item.role,
                    channel="in_app",
                    event_type="ip_deadline_reminder",
                    offset_days=offset,
                    scheduled_for=scheduled,
                    critical=row.is_critical,
                    would_deliver=withheld_reason is None,
                    withheld_reason=withheld_reason,
                )
            )
            if withheld_reason is not None:
                withheld += 1

    planned.sort(key=lambda entry: (entry.scheduled_for, entry.recipient_membership_id))
    return IpNotificationPreviewResponse(
        deadline_id=row.id,
        result_on=row.result_on,
        planned=planned,
        withheld_count=withheld,
    )


def _utc(value: datetime | None) -> datetime | None:
    """Normalize a persisted timestamp to aware UTC.

    ``DateTime(timezone=True)`` round-trips naive on SQLite, so without this the
    status surface would emit a different shape from the preview for the same
    instant. The API contract should not leak backend timezone behaviour.
    """

    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def deadline_notification_status(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
) -> IpNotificationStatusResponse:
    """NOTIF status - the intents that exist for this deadline and their state."""

    row = session.scalar(
        select(IpDeadline).where(
            IpDeadline.id == deadline_id,
            IpDeadline.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Deadline not found.")
    _docket_or_404(session, context=context, docket_id=row.docket_id)

    intents = list(
        session.scalars(
            select(NotificationDeliveryIntent)
            .where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.schedule_source_type == "ip_deadline",
                NotificationDeliveryIntent.schedule_source_id == row.id,
            )
            .order_by(
                NotificationDeliveryIntent.scheduled_for,
                NotificationDeliveryIntent.id,
            )
        ).all()
    )
    entries = [
        IpNotificationStatusEntry(
            intent_id=intent.id,
            recipient_membership_id=intent.recipient_membership_id,
            channel=intent.channel,
            event_type=intent.event_type,
            status=intent.status,
            scheduled_for=_utc(intent.scheduled_for),
            delivered_at=_utc(intent.delivered_at),
            attempts=intent.attempts,
            critical=bool(intent.critical),
            suppression_reason=intent.suppression_reason,
            superseded_by_intent_id=intent.superseded_by_intent_id,
        )
        for intent in intents
    ]
    return IpNotificationStatusResponse(
        deadline_id=row.id,
        intents=entries,
        pending_count=sum(1 for e in entries if e.status in {"pending", "queued", "scheduled"}),
        delivered_count=sum(1 for e in entries if e.delivered_at is not None),
        suppressed_count=sum(1 for e in entries if e.suppression_reason),
    )


__all__ = [
    "activate_calendar_version",
    "activate_rule_version",
    "complete_deadline",
    "confirm_deadline",
    "deadline_impact",
    "deadline_dependencies",
    "deadline_notification_status",
    "deadline_workspace",
    "list_company_rule_policies",
    "override_deadline",
    "preview_deadline_notifications",
    "propose_calendar_version",
    "propose_deadline",
    "propose_rule_version",
    "recalculate_deadline",
    "rule_impact",
    "select_company_rule_version",
    "transition_rule_version",
]
