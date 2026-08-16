from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.password_policy import WeakPasswordError, enforce_password_policy
from caseops_api.core.security import hash_password
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AccountSetupToken,
    AccountSetupTokenPurpose,
    AuditActorType,
    AuditEvent,
    AuditResult,
    Company,
    CompanyMembership,
    Contract,
    ContractObligation,
    Draft,
    DraftReview,
    EmployeeEmploymentStatus,
    EmployeeProfile,
    EthicalWall,
    HearingPack,
    HearingReminder,
    IpDeadlineCoverage,
    IpDocketQueue,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterTask,
    MembershipRole,
    Team,
    TeamMembership,
    User,
)
from caseops_api.schemas.employees import (
    AccountSetupCompleteRequest,
    EmployeeAuditEventRecord,
    EmployeeAuditResponse,
    EmployeeCreateRequest,
    EmployeeCreateResponse,
    EmployeeListResponse,
    EmployeeMatterAccessResponse,
    EmployeeMatterAccessRow,
    EmployeeOffboardingCommitResponse,
    EmployeeOffboardingObject,
    EmployeeOffboardingPreviewResponse,
    EmployeeOffboardingRequest,
    EmployeeRecord,
    EmployeeTokenDelivery,
    EmployeeUpdateRequest,
    PasswordResetStartResponse,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.employee_mailer import send_employee_account_link
from caseops_api.services.session_context import SessionContext

logger = logging.getLogger(__name__)

ACCOUNT_SETUP_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(minutes=60)
DEBUG_TOKEN_ENVS = {"local", "test"}
OFFBOARDING_SUPPORTED_TYPES = (
    "matters",
    "restricted_access_grants",
    "team_memberships",
    "contracts",
    "contract_obligations",
    "matter_tasks",
    "matter_deadlines",
    "ip_deadline_coverages",
    "ip_docket_queues",
    "hearing_reminders",
)
OFFBOARDING_UNSUPPORTED_TYPES = (
    "drafts",
    "draft_reviews",
    "hearing_packs",
    "portal_grants",
    "email_templates",
)


@dataclass
class IssuedAccountToken:
    token: str
    expires_at: datetime
    delivered: bool
    delivery_error: str | None

    def delivery_response(self) -> EmployeeTokenDelivery:
        return EmployeeTokenDelivery(
            delivered=self.delivered,
            delivery_error=self.delivery_error,
            expires_at=self.expires_at,
            debug_token=self.token if _debug_tokens_allowed() else None,
        )


@dataclass
class PendingEmployeeCreate:
    membership: CompanyMembership
    user: User
    profile: EmployeeProfile
    setup: IssuedAccountToken


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _debug_tokens_allowed() -> bool:
    env = (get_settings().env or "").lower()
    return env in DEBUG_TOKEN_ENVS


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _raise_conflict(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def _raise_bad_request(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _raise_forbidden(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def _load_employee_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> CompanyMembership:
    membership = session.scalar(
        select(CompanyMembership)
        .options(
            joinedload(CompanyMembership.user),
            joinedload(CompanyMembership.employee_profile),
            joinedload(CompanyMembership.custom_role),
        )
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.id == membership_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found.",
        )
    return membership


def _get_or_create_profile(
    session: Session,
    *,
    membership: CompanyMembership,
    status_value: str | None = None,
) -> EmployeeProfile:
    profile = membership.employee_profile
    if profile is not None:
        return profile
    now = _utcnow()
    profile = EmployeeProfile(
        company_id=membership.company_id,
        membership_id=membership.id,
        employment_status=(
            status_value
            or (
                EmployeeEmploymentStatus.ACTIVE
                if membership.is_active and membership.user.is_active
                else EmployeeEmploymentStatus.INACTIVE
            )
        ),
        force_password_change=False,
        setup_completed_at=membership.created_at,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.flush()
    membership.employee_profile = profile
    return profile


def _employee_status(
    membership: CompanyMembership,
    profile: EmployeeProfile | None,
) -> str:
    if profile is not None:
        return profile.employment_status
    return (
        EmployeeEmploymentStatus.ACTIVE
        if membership.is_active and membership.user.is_active
        else EmployeeEmploymentStatus.INACTIVE
    )


def _manager_name(
    session: Session,
    manager_membership_id: str | None,
) -> str | None:
    if not manager_membership_id:
        return None
    row = session.scalar(
        select(User.full_name)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(CompanyMembership.id == manager_membership_id)
    )
    return row


def _employee_record(
    session: Session,
    membership: CompanyMembership,
) -> EmployeeRecord:
    profile = membership.employee_profile
    return EmployeeRecord(
        company_id=membership.company_id,
        membership_id=membership.id,
        user_id=membership.user.id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role,  # type: ignore[arg-type]
        custom_role_id=membership.custom_role_id,
        custom_role_name=(
            membership.custom_role.name
            if membership.custom_role
            and membership.custom_role.is_active
            and membership.custom_role.revoked_at is None
            else None
        ),
        membership_active=membership.is_active,
        user_active=membership.user.is_active,
        mobile=profile.mobile if profile else None,
        designation=profile.designation if profile else None,
        department=profile.department if profile else None,
        employee_code=profile.employee_code if profile else None,
        manager_membership_id=profile.manager_membership_id if profile else None,
        manager_name=_manager_name(
            session,
            profile.manager_membership_id if profile else None,
        ),
        joined_on=profile.joined_on if profile else None,
        employment_status=_employee_status(membership, profile),  # type: ignore[arg-type]
        last_login_at=profile.last_login_at if profile else None,
        setup_sent_at=profile.setup_sent_at if profile else None,
        setup_completed_at=profile.setup_completed_at if profile else None,
        password_reset_sent_at=profile.password_reset_sent_at if profile else None,
        force_password_change=bool(profile.force_password_change) if profile else False,
        created_at=profile.created_at if profile else membership.created_at,
        updated_at=profile.updated_at if profile else membership.created_at,
    )


def _offboarding_object(
    object_type: str,
    object_id: str,
    *,
    label: str,
    relation: str,
    supported: bool,
    matter_id: str | None = None,
) -> EmployeeOffboardingObject:
    return EmployeeOffboardingObject(
        object_type=object_type,
        id=object_id,
        label=label,
        relation=relation,
        supported=supported,
        matter_id=matter_id,
    )


def _object_counts(
    rows: list[EmployeeOffboardingObject],
    *,
    known_types: tuple[str, ...],
) -> dict[str, int]:
    counts = {object_type: 0 for object_type in known_types}
    for row in rows:
        counts[row.object_type] = counts.get(row.object_type, 0) + 1
    return counts


def _active_owner_count(session: Session, *, company_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(CompanyMembership.id))
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.role == MembershipRole.OWNER,
                CompanyMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        or 0
    )


def _load_reassignment_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str | None,
) -> CompanyMembership | None:
    if membership_id is None:
        return None
    membership = _load_employee_membership(
        session,
        company_id=company_id,
        membership_id=membership_id,
    )
    if not membership.is_active or not membership.user.is_active:
        _raise_bad_request("Replacement employee must be active.")
    return membership


def _has_other_active_memberships(
    session: Session,
    *,
    membership: CompanyMembership,
) -> bool:
    return (
        session.scalar(
            select(CompanyMembership.id)
            .join(Company, Company.id == CompanyMembership.company_id)
            .where(
                CompanyMembership.user_id == membership.user_id,
                CompanyMembership.id != membership.id,
                CompanyMembership.is_active.is_(True),
                Company.is_active.is_(True),
            )
            .limit(1)
        )
        is not None
    )


def _collect_offboarding_objects(
    session: Session,
    *,
    company_id: str,
    target: CompanyMembership,
) -> tuple[list[EmployeeOffboardingObject], list[EmployeeOffboardingObject], set[str]]:
    supported: list[EmployeeOffboardingObject] = []
    unsupported: list[EmployeeOffboardingObject] = []
    affected_matter_ids: set[str] = set()

    matters = list(
        session.scalars(
            select(Matter)
            .where(
                Matter.company_id == company_id,
                Matter.assignee_membership_id == target.id,
            )
            .order_by(Matter.matter_code.asc(), Matter.id.asc())
        )
    )
    for matter in matters:
        affected_matter_ids.add(matter.id)
        supported.append(
            _offboarding_object(
                "matters",
                matter.id,
                label=f"{matter.matter_code} - {matter.title}",
                relation="assignee",
                supported=True,
                matter_id=matter.id,
            )
        )

    grant_rows = list(
        session.execute(
            select(MatterAccessGrant, Matter)
            .join(Matter, Matter.id == MatterAccessGrant.matter_id)
            .where(
                Matter.company_id == company_id,
                MatterAccessGrant.membership_id == target.id,
            )
            .order_by(Matter.matter_code.asc(), MatterAccessGrant.id.asc())
        ).all()
    )
    for grant, matter in grant_rows:
        affected_matter_ids.add(matter.id)
        supported.append(
            _offboarding_object(
                "restricted_access_grants",
                grant.id,
                label=f"{matter.matter_code} - {matter.title}",
                relation="restricted access grant",
                supported=True,
                matter_id=matter.id,
            )
        )

    team_rows = list(
        session.execute(
            select(TeamMembership, Team)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(
                Team.company_id == company_id,
                TeamMembership.membership_id == target.id,
            )
            .order_by(Team.name.asc(), TeamMembership.id.asc())
        ).all()
    )
    for team_membership, team in team_rows:
        supported.append(
            _offboarding_object(
                "team_memberships",
                team_membership.id,
                label=team.name,
                relation="team lead" if team_membership.is_lead else "team member",
                supported=True,
            )
        )

    contracts = list(
        session.scalars(
            select(Contract)
            .where(
                Contract.company_id == company_id,
                Contract.owner_membership_id == target.id,
            )
            .order_by(Contract.contract_code.asc(), Contract.id.asc())
        )
    )
    for contract in contracts:
        if contract.linked_matter_id:
            affected_matter_ids.add(contract.linked_matter_id)
        supported.append(
            _offboarding_object(
                "contracts",
                contract.id,
                label=f"{contract.contract_code} - {contract.title}",
                relation="owner",
                supported=True,
                matter_id=contract.linked_matter_id,
            )
        )

    obligation_rows = list(
        session.execute(
            select(ContractObligation, Contract)
            .join(Contract, Contract.id == ContractObligation.contract_id)
            .where(
                Contract.company_id == company_id,
                ContractObligation.owner_membership_id == target.id,
            )
            .order_by(Contract.contract_code.asc(), ContractObligation.title.asc())
        ).all()
    )
    for obligation, contract in obligation_rows:
        if contract.linked_matter_id:
            affected_matter_ids.add(contract.linked_matter_id)
        supported.append(
            _offboarding_object(
                "contract_obligations",
                obligation.id,
                label=f"{contract.contract_code} - {obligation.title}",
                relation="owner",
                supported=True,
                matter_id=contract.linked_matter_id,
            )
        )

    task_rows = list(
        session.execute(
            select(MatterTask, Matter)
            .join(Matter, Matter.id == MatterTask.matter_id)
            .where(
                Matter.company_id == company_id,
                MatterTask.owner_membership_id == target.id,
            )
            .order_by(Matter.matter_code.asc(), MatterTask.title.asc())
        ).all()
    )
    for task, matter in task_rows:
        affected_matter_ids.add(matter.id)
        supported.append(
            _offboarding_object(
                "matter_tasks",
                task.id,
                label=f"{matter.matter_code} - {task.title}",
                relation="owner",
                supported=True,
                matter_id=matter.id,
            )
        )

    deadline_rows = list(
        session.execute(
            select(MatterDeadline, Matter)
            .join(Matter, Matter.id == MatterDeadline.matter_id)
            .where(
                Matter.company_id == company_id,
                MatterDeadline.assignee_membership_id == target.id,
            )
            .order_by(Matter.matter_code.asc(), MatterDeadline.due_on.asc())
        ).all()
    )
    for deadline, matter in deadline_rows:
        affected_matter_ids.add(matter.id)
        supported.append(
            _offboarding_object(
                "matter_deadlines",
                deadline.id,
                label=f"{matter.matter_code} - {deadline.title}",
                relation="assignee",
                supported=True,
                matter_id=matter.id,
            )
        )

    ip_coverage_rows = list(
        session.execute(
            select(IpDeadlineCoverage, MatterDeadline, Matter)
            .join(MatterDeadline, MatterDeadline.id == IpDeadlineCoverage.matter_deadline_id)
            .join(Matter, Matter.id == MatterDeadline.matter_id)
            .where(
                IpDeadlineCoverage.company_id == company_id,
                or_(
                    IpDeadlineCoverage.responsible_membership_id == target.id,
                    IpDeadlineCoverage.backup_membership_id == target.id,
                ),
            )
            .order_by(Matter.matter_code.asc(), MatterDeadline.due_on.asc())
        ).all()
    )
    for coverage, deadline, matter in ip_coverage_rows:
        affected_matter_ids.add(matter.id)
        relations: list[str] = []
        if coverage.responsible_membership_id == target.id:
            relations.append("responsible")
        if coverage.backup_membership_id == target.id:
            relations.append("backup")
        supported.append(
            _offboarding_object(
                "ip_deadline_coverages",
                coverage.id,
                label=f"{matter.matter_code} - {deadline.title}",
                relation="IP deadline " + "/".join(relations),
                supported=True,
                matter_id=matter.id,
            )
        )

    personal_queues = list(
        session.scalars(
            select(IpDocketQueue)
            .where(
                IpDocketQueue.company_id == company_id,
                IpDocketQueue.team_id.is_(None),
                IpDocketQueue.owner_membership_id == target.id,
            )
            .order_by(IpDocketQueue.name.asc(), IpDocketQueue.id.asc())
        )
    )
    for queue in personal_queues:
        supported.append(
            _offboarding_object(
                "ip_docket_queues",
                queue.id,
                label=queue.name,
                relation="personal docket queue owner",
                supported=True,
            )
        )

    reminder_rows = list(
        session.execute(
            select(HearingReminder, Matter)
            .join(Matter, Matter.id == HearingReminder.matter_id)
            .where(
                HearingReminder.company_id == company_id,
                HearingReminder.recipient_membership_id == target.id,
            )
            .order_by(Matter.matter_code.asc(), HearingReminder.scheduled_for.asc())
        ).all()
    )
    for reminder, matter in reminder_rows:
        affected_matter_ids.add(matter.id)
        supported.append(
            _offboarding_object(
                "hearing_reminders",
                reminder.id,
                label=f"{matter.matter_code} - {reminder.channel} reminder",
                relation="recipient",
                supported=True,
                matter_id=matter.id,
            )
        )

    draft_rows = list(
        session.execute(
            select(Draft, Matter)
            .join(Matter, Matter.id == Draft.matter_id)
            .where(
                Matter.company_id == company_id,
                Draft.created_by_membership_id == target.id,
            )
            .order_by(Matter.matter_code.asc(), Draft.title.asc())
        ).all()
    )
    for draft, matter in draft_rows:
        affected_matter_ids.add(matter.id)
        unsupported.append(
            _offboarding_object(
                "drafts",
                draft.id,
                label=f"{matter.matter_code} - {draft.title}",
                relation="creator",
                supported=False,
                matter_id=matter.id,
            )
        )

    draft_review_rows = list(
        session.execute(
            select(DraftReview, Draft, Matter)
            .join(Draft, Draft.id == DraftReview.draft_id)
            .join(Matter, Matter.id == Draft.matter_id)
            .where(
                Matter.company_id == company_id,
                DraftReview.actor_membership_id == target.id,
            )
            .order_by(Matter.matter_code.asc(), Draft.title.asc(), DraftReview.id.asc())
        ).all()
    )
    for review, draft, matter in draft_review_rows:
        affected_matter_ids.add(matter.id)
        unsupported.append(
            _offboarding_object(
                "draft_reviews",
                review.id,
                label=f"{matter.matter_code} - {draft.title}",
                relation="review actor",
                supported=False,
                matter_id=matter.id,
            )
        )

    hearing_pack_rows = list(
        session.execute(
            select(HearingPack, Matter)
            .join(Matter, Matter.id == HearingPack.matter_id)
            .where(
                Matter.company_id == company_id,
                or_(
                    HearingPack.generated_by_membership_id == target.id,
                    HearingPack.reviewed_by_membership_id == target.id,
                ),
            )
            .order_by(Matter.matter_code.asc(), HearingPack.generated_at.asc())
        ).all()
    )
    for pack, matter in hearing_pack_rows:
        affected_matter_ids.add(matter.id)
        relation = "generator" if pack.generated_by_membership_id == target.id else "reviewer"
        unsupported.append(
            _offboarding_object(
                "hearing_packs",
                pack.id,
                label=f"{matter.matter_code} - hearing pack",
                relation=relation,
                supported=False,
                matter_id=matter.id,
            )
        )

    return supported, unsupported, affected_matter_ids


def _ethical_wall_conflict_count(
    session: Session,
    *,
    reassign_to_membership_id: str,
    matter_ids: set[str],
) -> int:
    if not matter_ids:
        return 0
    return int(
        session.scalar(
            select(func.count(EthicalWall.id)).where(
                EthicalWall.excluded_membership_id == reassign_to_membership_id,
                EthicalWall.matter_id.in_(matter_ids),
            )
        )
        or 0
    )


def _build_offboarding_preview(
    session: Session,
    *,
    context: SessionContext,
    target: CompanyMembership,
    reassign_to: CompanyMembership | None,
) -> EmployeeOffboardingPreviewResponse:
    supported, unsupported, affected_matter_ids = _collect_offboarding_objects(
        session,
        company_id=context.company.id,
        target=target,
    )
    blockers: list[str] = []

    if target.id == context.membership.id:
        blockers.append("You cannot offboard your own active session membership.")
    if target.role == MembershipRole.OWNER:
        if _active_owner_count(session, company_id=context.company.id) <= 1:
            blockers.append("Cannot offboard the last active owner.")
        else:
            blockers.append("Owner memberships cannot be offboarded through this flow.")
    if not target.is_active or not target.user.is_active:
        blockers.append("Employee is already inactive.")
    if reassign_to is None:
        blockers.append("Choose an active replacement employee before commit.")
    else:
        if reassign_to.id == target.id:
            blockers.append(
                "Replacement employee must be different from the employee being offboarded."
            )
        if reassign_to.company_id != context.company.id:
            blockers.append("Replacement employee must belong to this company.")
        if not reassign_to.is_active or not reassign_to.user.is_active:
            blockers.append("Replacement employee must be active.")
        backup_conflicts = int(
            session.scalar(
                select(func.count(IpDeadlineCoverage.id)).where(
                    IpDeadlineCoverage.company_id == context.company.id,
                    or_(
                        and_(
                            IpDeadlineCoverage.backup_membership_id == target.id,
                            IpDeadlineCoverage.responsible_membership_id
                            == reassign_to.id,
                        ),
                        and_(
                            IpDeadlineCoverage.responsible_membership_id == target.id,
                            IpDeadlineCoverage.backup_membership_id == reassign_to.id,
                        ),
                        and_(
                            IpDeadlineCoverage.responsible_membership_id == target.id,
                            IpDeadlineCoverage.backup_membership_id
                            == context.membership.id,
                        ),
                    ),
                )
            )
            or 0
        )
        if backup_conflicts:
            blockers.append(
                "Choose a distinct IP deadline backup; the replacement or "
                "decline-escalation owner already holds the other coverage role."
            )
        conflicts = _ethical_wall_conflict_count(
            session,
            reassign_to_membership_id=reassign_to.id,
            matter_ids=affected_matter_ids,
        )
        if conflicts:
            blockers.append("Replacement employee is ethically walled from affected matters.")

    return EmployeeOffboardingPreviewResponse(
        employee=_employee_record(session, target),
        reassign_to=_employee_record(session, reassign_to) if reassign_to else None,
        supported_objects=supported,
        unsupported_objects=unsupported,
        supported_counts=_object_counts(
            supported,
            known_types=OFFBOARDING_SUPPORTED_TYPES,
        ),
        unsupported_counts=_object_counts(
            unsupported,
            known_types=OFFBOARDING_UNSUPPORTED_TYPES,
        ),
        blockers=blockers,
        can_commit=not blockers and reassign_to is not None,
    )


def _validate_manager(
    session: Session,
    *,
    company_id: str,
    target_membership_id: str,
    manager_membership_id: str | None,
) -> None:
    if manager_membership_id is None:
        return
    if manager_membership_id == target_membership_id:
        _raise_bad_request("An employee cannot be their own manager.")
    manager = session.scalar(
        select(CompanyMembership.id).where(
            CompanyMembership.id == manager_membership_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if manager is None:
        _raise_bad_request("Manager membership must belong to this company.")


def _ensure_employee_code_available(
    session: Session,
    *,
    company_id: str,
    employee_code: str | None,
    current_profile_id: str | None,
) -> None:
    if employee_code is None:
        return
    existing = session.scalar(
        select(EmployeeProfile).where(
            EmployeeProfile.company_id == company_id,
            EmployeeProfile.employee_code == employee_code,
        )
    )
    if existing is not None and existing.id != current_profile_id:
        _raise_conflict("Employee code is already in use in this company.")


def _apply_status(
    session: Session,
    *,
    membership: CompanyMembership,
    profile: EmployeeProfile,
    status_value: str,
) -> None:
    profile.employment_status = EmployeeEmploymentStatus(status_value)
    if status_value == EmployeeEmploymentStatus.INACTIVE:
        membership.is_active = False
        membership.sessions_valid_after = _utcnow()
        if not _has_other_active_memberships(session, membership=membership):
            membership.user.is_active = False
    elif status_value in {
        EmployeeEmploymentStatus.ACTIVE,
        EmployeeEmploymentStatus.INVITED,
    }:
        membership.is_active = True
        membership.user.is_active = True


def _assert_role_assignment_allowed(
    *,
    context: SessionContext,
    target_membership: CompanyMembership | None,
    role: str | None,
) -> None:
    if role is None:
        return
    if target_membership is not None and target_membership.role == MembershipRole.OWNER:
        _raise_forbidden("Owner memberships cannot be modified here.")
    if context.membership.role != MembershipRole.OWNER and role != MembershipRole.MEMBER:
        _raise_forbidden("Only owners can assign elevated employee roles.")


def _issue_account_token(
    session: Session,
    *,
    company: Company,
    membership: CompanyMembership,
    purpose: AccountSetupTokenPurpose,
    created_by_membership_id: str | None,
    actor_context: SessionContext | None,
) -> IssuedAccountToken:
    token = _generate_token()
    now = _utcnow()
    ttl = (
        ACCOUNT_SETUP_TTL
        if purpose == AccountSetupTokenPurpose.ACCOUNT_SETUP
        else PASSWORD_RESET_TTL
    )
    expires_at = now + ttl
    row = AccountSetupToken(
        company_id=company.id,
        user_id=membership.user.id,
        membership_id=membership.id,
        token_hash=_hash_token(token),
        purpose=purpose,
        expires_at=expires_at,
        created_by_membership_id=created_by_membership_id,
        created_at=now,
    )
    session.add(row)
    profile = _get_or_create_profile(
        session,
        membership=membership,
        status_value=(
            EmployeeEmploymentStatus.INVITED
            if purpose == AccountSetupTokenPurpose.ACCOUNT_SETUP
            else None
        ),
    )
    if purpose == AccountSetupTokenPurpose.ACCOUNT_SETUP:
        profile.setup_sent_at = now
        profile.force_password_change = True
    else:
        profile.password_reset_sent_at = now
    session.flush()

    delivered, error = send_employee_account_link(
        to_email=membership.user.email,
        full_name=membership.user.full_name,
        company_display_name=company.name,
        token=token,
        purpose=purpose.value,
    )
    metadata = {
        "purpose": purpose.value,
        "expires_at": expires_at.isoformat(),
        "delivered": delivered,
        "delivery_error": error,
    }
    if actor_context is not None:
        record_from_context(
            session,
            actor_context,
            action=(
                "employee.setup_token.created"
                if purpose == AccountSetupTokenPurpose.ACCOUNT_SETUP
                else "employee.password_reset_token.created"
            ),
            target_type="employee",
            target_id=membership.id,
            metadata=metadata,
        )
    else:
        record_audit(
            session,
            company_id=company.id,
            actor_type=AuditActorType.SYSTEM,
            actor_label="employee-account-token",
            action=(
                "employee.setup_token.created"
                if purpose == AccountSetupTokenPurpose.ACCOUNT_SETUP
                else "employee.password_reset_token.created"
            ),
            target_type="employee",
            target_id=membership.id,
            result=AuditResult.SUCCESS,
            metadata=metadata,
        )
    return IssuedAccountToken(
        token=token,
        expires_at=expires_at,
        delivered=delivered,
        delivery_error=error,
    )


def list_employees(
    session: Session,
    *,
    context: SessionContext,
    q: str | None = None,
    role: str | None = None,
    status_filter: str | None = None,
    department: str | None = None,
) -> EmployeeListResponse:
    rows = list(
        session.scalars(
            select(CompanyMembership)
            .options(
                joinedload(CompanyMembership.user),
                joinedload(CompanyMembership.employee_profile),
                joinedload(CompanyMembership.custom_role),
            )
            .where(CompanyMembership.company_id == context.company.id)
            .order_by(CompanyMembership.created_at.asc())
        )
    )
    q_clean = (q or "").strip().lower()
    department_clean = (department or "").strip().lower()

    filtered: list[CompanyMembership] = []
    for membership in rows:
        profile = membership.employee_profile
        if role and membership.role != role:
            continue
        if status_filter and _employee_status(membership, profile) != status_filter:
            continue
        if department_clean:
            if not profile or (profile.department or "").strip().lower() != department_clean:
                continue
        if q_clean:
            haystack = f"{membership.user.full_name} {membership.user.email}".lower()
            if q_clean not in haystack:
                continue
        filtered.append(membership)

    filtered.sort(
        key=lambda m: (
            (m.employee_profile.department or "") if m.employee_profile else "",
            m.user.full_name.lower(),
            m.user.email.lower(),
        )
    )
    return EmployeeListResponse(
        employees=[_employee_record(session, membership) for membership in filtered]
    )


def get_employee(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
) -> EmployeeRecord:
    membership = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    return _employee_record(session, membership)


def list_employee_matter_access(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
) -> EmployeeMatterAccessResponse:
    """BUG-048 (Hari 2026-05-11): admin view of one employee's matter
    access fan-out.

    Lists every matter in the company and labels it with whether the
    target employee:
      - has restricted_access turned on (then access requires a grant);
      - already holds an explicit grant;
      - is the assignee (auto-visible);
      - is on an ethical wall (forced-out, overrides any grant).

    The Admin > Employees Edit dialog uses this to show a per-matter
    toggle. Mutations still go through the per-matter access endpoints
    (POST /api/matters/{id}/access/grants, DELETE …/{grant_id}) so
    audit + RBAC + validation paths are reused.
    """
    from caseops_api.db.models import EthicalWall, Matter, MatterAccessGrant

    # Confirm the target membership belongs to the caller's company.
    target = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )

    matters = list(
        session.scalars(
            select(Matter)
            .where(Matter.company_id == context.company.id)
            .order_by(Matter.matter_code.asc(), Matter.id.asc())
        )
    )
    if not matters:
        return EmployeeMatterAccessResponse(
            membership_id=target.id,
            matters=[],
        )

    matter_ids = [m.id for m in matters]
    grant_rows = session.execute(
        select(MatterAccessGrant.matter_id, MatterAccessGrant.id).where(
            MatterAccessGrant.membership_id == target.id,
            MatterAccessGrant.matter_id.in_(matter_ids),
        )
    ).all()
    grants_by_matter: dict[str, str] = {row[0]: row[1] for row in grant_rows}

    wall_rows = session.execute(
        select(EthicalWall.matter_id).where(
            EthicalWall.excluded_membership_id == target.id,
            EthicalWall.matter_id.in_(matter_ids),
        )
    ).all()
    walled_matters = {row[0] for row in wall_rows}

    rows = [
        EmployeeMatterAccessRow(
            matter_id=matter.id,
            matter_code=matter.matter_code,
            matter_title=matter.title,
            restricted_access=bool(matter.restricted_access),
            has_grant=matter.id in grants_by_matter,
            grant_id=grants_by_matter.get(matter.id),
            is_assignee=matter.assignee_membership_id == target.id,
            is_walled=matter.id in walled_matters,
        )
        for matter in matters
    ]
    return EmployeeMatterAccessResponse(
        membership_id=target.id,
        matters=rows,
    )


def create_employee(
    session: Session,
    *,
    context: SessionContext,
    payload: EmployeeCreateRequest,
) -> EmployeeCreateResponse:
    created = _create_employee_without_commit(
        session,
        context=context,
        payload=payload,
    )
    session.commit()
    session.refresh(created.membership)
    session.refresh(created.user)
    session.refresh(created.profile)
    return EmployeeCreateResponse(
        employee=_employee_record(session, created.membership),
        setup=created.setup.delivery_response(),
    )


def _create_employee_without_commit(
    session: Session,
    *,
    context: SessionContext,
    payload: EmployeeCreateRequest,
    reuse_existing_global_user: bool = False,
) -> PendingEmployeeCreate:
    _assert_role_assignment_allowed(
        context=context,
        target_membership=None,
        role=payload.role,
    )

    email = str(payload.email).lower()
    existing_user = session.scalar(select(User).where(User.email == email))
    if existing_user:
        if not reuse_existing_global_user:
            _raise_conflict("An account with this email already exists.")
        existing_membership = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.user_id == existing_user.id,
            )
        )
        if existing_membership is not None:
            _raise_conflict("An account with this email already exists.")
        user = existing_user
    else:
        user = User(
            email=email,
            full_name=payload.full_name.strip(),
            password_hash=hash_password(secrets.token_urlsafe(64)),
            is_active=True,
        )
    membership = CompanyMembership(
        company_id=context.company.id,
        role=MembershipRole(payload.role),
        is_active=True,
    )
    membership.user = user
    session.add_all([user, membership])
    session.flush()

    _validate_manager(
        session,
        company_id=context.company.id,
        target_membership_id=membership.id,
        manager_membership_id=payload.manager_membership_id,
    )
    _ensure_employee_code_available(
        session,
        company_id=context.company.id,
        employee_code=payload.employee_code,
        current_profile_id=None,
    )
    profile = EmployeeProfile(
        company_id=context.company.id,
        membership_id=membership.id,
        mobile=payload.mobile,
        designation=payload.designation,
        department=payload.department,
        employee_code=payload.employee_code,
        manager_membership_id=payload.manager_membership_id,
        joined_on=payload.joined_on,
        employment_status=EmployeeEmploymentStatus.INVITED,
        force_password_change=True,
    )
    session.add(profile)
    session.flush()
    membership.employee_profile = profile

    record_from_context(
        session,
        context,
        action="employee.created",
        target_type="employee",
        target_id=membership.id,
        metadata={
            "email": user.email,
            "role": membership.role,
            "department": profile.department,
            "designation": profile.designation,
            "employee_code": profile.employee_code,
        },
    )
    setup = _issue_account_token(
        session,
        company=context.company,
        membership=membership,
        purpose=AccountSetupTokenPurpose.ACCOUNT_SETUP,
        created_by_membership_id=context.membership.id,
        actor_context=context,
    )
    return PendingEmployeeCreate(
        membership=membership,
        user=user,
        profile=profile,
        setup=setup,
    )


def update_employee(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    payload: EmployeeUpdateRequest,
) -> EmployeeRecord:
    membership = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    profile = _get_or_create_profile(session, membership=membership)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _employee_record(session, membership)

    if "role" in updates:
        _assert_role_assignment_allowed(
            context=context,
            target_membership=membership,
            role=payload.role,
        )
    elif context.membership.role == MembershipRole.ADMIN:
        # Admins may edit directory metadata, but role and lifecycle
        # changes stay owner-only to preserve the old membership rules.
        pass

    if (
        "employment_status" in updates
        and updates["employment_status"] == EmployeeEmploymentStatus.INACTIVE
        and membership.id == context.membership.id
    ):
        _raise_bad_request("You cannot mark your own employee record inactive.")
    if membership.role == MembershipRole.OWNER and (
        "role" in updates or "employment_status" in updates
    ):
        _raise_forbidden("Owner memberships cannot be modified here.")
    if context.membership.role != MembershipRole.OWNER and (
        "role" in updates or "employment_status" in updates
    ):
        _raise_forbidden("Only owners can change employee role or status.")

    before = _employee_record(session, membership).model_dump(mode="json")

    if payload.full_name is not None:
        membership.user.full_name = payload.full_name.strip()
    if payload.role is not None:
        membership.role = MembershipRole(payload.role)
    if "mobile" in updates:
        profile.mobile = payload.mobile
    if "designation" in updates:
        profile.designation = payload.designation
    if "department" in updates:
        profile.department = payload.department
    if "employee_code" in updates:
        _ensure_employee_code_available(
            session,
            company_id=context.company.id,
            employee_code=payload.employee_code,
            current_profile_id=profile.id,
        )
        profile.employee_code = payload.employee_code
    if "manager_membership_id" in updates:
        _validate_manager(
            session,
            company_id=context.company.id,
            target_membership_id=membership.id,
            manager_membership_id=payload.manager_membership_id,
        )
        profile.manager_membership_id = payload.manager_membership_id
    if "joined_on" in updates:
        profile.joined_on = payload.joined_on
    if payload.employment_status is not None:
        _apply_status(
            session,
            membership=membership,
            profile=profile,
            status_value=payload.employment_status,
        )

    profile.updated_at = _utcnow()
    session.flush()
    after = _employee_record(session, membership).model_dump(mode="json")
    changed = {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in sorted(after)
        if before.get(key) != after.get(key)
        and key
        in {
            "full_name",
            "role",
            "membership_active",
            "user_active",
            "mobile",
            "designation",
            "department",
            "employee_code",
            "manager_membership_id",
            "joined_on",
            "employment_status",
            "force_password_change",
        }
    }
    if changed:
        record_from_context(
            session,
            context,
            action="employee.updated",
            target_type="employee",
            target_id=membership.id,
            metadata={"changes": changed},
        )
    session.commit()
    session.refresh(membership)
    session.refresh(membership.user)
    session.refresh(profile)
    return _employee_record(session, membership)


def preview_employee_offboarding(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    payload: EmployeeOffboardingRequest,
) -> EmployeeOffboardingPreviewResponse:
    target = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    reassign_to = _load_reassignment_membership(
        session,
        company_id=context.company.id,
        membership_id=payload.reassign_to_membership_id,
    )
    preview = _build_offboarding_preview(
        session,
        context=context,
        target=target,
        reassign_to=reassign_to,
    )
    record_from_context(
        session,
        context,
        action="employee.offboarding.previewed",
        target_type="employee",
        target_id=target.id,
        metadata={
            "reassign_to_membership_id": payload.reassign_to_membership_id,
            "supported_counts": preview.supported_counts,
            "unsupported_counts": preview.unsupported_counts,
            "blockers": preview.blockers,
            "notes": payload.notes,
        },
    )
    session.commit()
    return preview


def _merge_or_reassign_matter_grants(
    session: Session,
    *,
    company_id: str,
    target_id: str,
    replacement_id: str,
) -> int:
    grant_rows = list(
        session.execute(
            select(MatterAccessGrant, Matter)
            .join(Matter, Matter.id == MatterAccessGrant.matter_id)
            .where(
                Matter.company_id == company_id,
                MatterAccessGrant.membership_id == target_id,
            )
            .order_by(MatterAccessGrant.id.asc())
        ).all()
    )
    changed = 0
    for grant, _matter in grant_rows:
        existing = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.matter_id == grant.matter_id,
                MatterAccessGrant.membership_id == replacement_id,
            )
        )
        if existing is not None:
            session.delete(grant)
        else:
            grant.membership_id = replacement_id
        changed += 1
    return changed


def _merge_or_reassign_team_memberships(
    session: Session,
    *,
    company_id: str,
    target_id: str,
    replacement_id: str,
) -> int:
    rows = list(
        session.execute(
            select(TeamMembership, Team)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(
                Team.company_id == company_id,
                TeamMembership.membership_id == target_id,
            )
            .order_by(TeamMembership.id.asc())
        ).all()
    )
    changed = 0
    for team_membership, _team in rows:
        existing = session.scalar(
            select(TeamMembership).where(
                TeamMembership.team_id == team_membership.team_id,
                TeamMembership.membership_id == replacement_id,
            )
        )
        if existing is not None:
            existing.is_lead = bool(existing.is_lead or team_membership.is_lead)
            session.delete(team_membership)
        else:
            team_membership.membership_id = replacement_id
        changed += 1
    return changed


def _reassign_offboarding_objects(
    session: Session,
    *,
    context: SessionContext,
    company_id: str,
    target_id: str,
    replacement_id: str,
) -> dict[str, int]:
    counts = {object_type: 0 for object_type in OFFBOARDING_SUPPORTED_TYPES}

    matters = list(
        session.scalars(
            select(Matter).where(
                Matter.company_id == company_id,
                Matter.assignee_membership_id == target_id,
            )
        )
    )
    for matter in matters:
        matter.assignee_membership_id = replacement_id
    counts["matters"] = len(matters)

    counts["restricted_access_grants"] = _merge_or_reassign_matter_grants(
        session,
        company_id=company_id,
        target_id=target_id,
        replacement_id=replacement_id,
    )
    counts["team_memberships"] = _merge_or_reassign_team_memberships(
        session,
        company_id=company_id,
        target_id=target_id,
        replacement_id=replacement_id,
    )

    contracts = list(
        session.scalars(
            select(Contract).where(
                Contract.company_id == company_id,
                Contract.owner_membership_id == target_id,
            )
        )
    )
    for contract in contracts:
        contract.owner_membership_id = replacement_id
    counts["contracts"] = len(contracts)

    obligations = list(
        session.scalars(
            select(ContractObligation)
            .join(Contract, Contract.id == ContractObligation.contract_id)
            .where(
                Contract.company_id == company_id,
                ContractObligation.owner_membership_id == target_id,
            )
        )
    )
    for obligation in obligations:
        obligation.owner_membership_id = replacement_id
    counts["contract_obligations"] = len(obligations)

    tasks = list(
        session.scalars(
            select(MatterTask)
            .join(Matter, Matter.id == MatterTask.matter_id)
            .where(
                Matter.company_id == company_id,
                MatterTask.owner_membership_id == target_id,
            )
        )
    )
    for task in tasks:
        task.owner_membership_id = replacement_id
    counts["matter_tasks"] = len(tasks)

    deadlines = list(
        session.scalars(
            select(MatterDeadline)
            .join(Matter, Matter.id == MatterDeadline.matter_id)
            .where(
                Matter.company_id == company_id,
                MatterDeadline.assignee_membership_id == target_id,
            )
        )
    )
    for deadline in deadlines:
        deadline.assignee_membership_id = replacement_id
    counts["matter_deadlines"] = len(deadlines)

    from caseops_api.schemas.ip_operations import IpCoverageBulkReassignRequest
    from caseops_api.services.ip_operations import bulk_reassign_ip_deadline_coverages

    ip_reassignment = bulk_reassign_ip_deadline_coverages(
        session,
        context=context,
        payload=IpCoverageBulkReassignRequest(
            from_membership_id=target_id,
            to_membership_id=replacement_id,
            reason="Employee offboarding coverage transfer",
            # The departing person cannot be waited on, so responsibility moves
            # now. It is still recorded as awaiting the replacement's
            # acknowledgement rather than as an acceptance they never gave, and
            # the admin running the offboarding is who a decline escalates to.
            transfer_mode="immediate",
            escalation_membership_id=context.membership.id,
        ),
        commit=False,
    )
    counts["ip_deadline_coverages"] = ip_reassignment.reassigned_count

    personal_queues = list(
        session.scalars(
            select(IpDocketQueue).where(
                IpDocketQueue.company_id == company_id,
                IpDocketQueue.team_id.is_(None),
                IpDocketQueue.owner_membership_id == target_id,
            )
        )
    )
    for queue in personal_queues:
        queue.owner_membership_id = replacement_id
    counts["ip_docket_queues"] = len(personal_queues)

    reminders = list(
        session.scalars(
            select(HearingReminder).where(
                HearingReminder.company_id == company_id,
                HearingReminder.recipient_membership_id == target_id,
            )
        )
    )
    for reminder in reminders:
        reminder.recipient_membership_id = replacement_id
    counts["hearing_reminders"] = len(reminders)

    return counts


def commit_employee_offboarding(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    payload: EmployeeOffboardingRequest,
) -> EmployeeOffboardingCommitResponse:
    if context.membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        _raise_forbidden("Only fixed owners or admins can commit employee offboarding.")
    if not payload.deactivate or not payload.revoke_sessions:
        _raise_bad_request("Offboarding commit must deactivate and revoke sessions.")
    target = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    reassign_to = _load_reassignment_membership(
        session,
        company_id=context.company.id,
        membership_id=payload.reassign_to_membership_id,
    )
    if reassign_to is None:
        _raise_bad_request("Choose an active replacement employee before commit.")
    preview = _build_offboarding_preview(
        session,
        context=context,
        target=target,
        reassign_to=reassign_to,
    )
    if preview.blockers:
        _raise_bad_request("; ".join(preview.blockers))

    before = _employee_record(session, target).model_dump(mode="json")
    reassigned_counts = _reassign_offboarding_objects(
        session,
        context=context,
        company_id=context.company.id,
        target_id=target.id,
        replacement_id=reassign_to.id,
    )
    profile = _get_or_create_profile(session, membership=target)
    now = _utcnow()
    profile.employment_status = EmployeeEmploymentStatus.INACTIVE
    profile.updated_at = now
    target.is_active = False
    target.sessions_valid_after = now
    user_deactivated = False
    if not _has_other_active_memberships(session, membership=target):
        target.user.is_active = False
        user_deactivated = True
    session.flush()
    after = _employee_record(session, target).model_dump(mode="json")
    metadata = {
        "before": before,
        "after": after,
        "reassign_to_membership_id": reassign_to.id,
        "reassign_to_email": reassign_to.user.email,
        "reassigned_counts": reassigned_counts,
        "unsupported_counts": preview.unsupported_counts,
        "unsupported_object_ids": [
            {"object_type": row.object_type, "id": row.id} for row in preview.unsupported_objects
        ],
        "notes": payload.notes,
        "sessions_revoked": True,
    }
    record_from_context(
        session,
        context,
        action="employee.deactivated",
        target_type="employee",
        target_id=target.id,
        metadata={
            "email": target.user.email,
            "sessions_valid_after": now.isoformat(),
            "via": "offboarding",
            "global_user_deactivated": user_deactivated,
        },
    )
    record_from_context(
        session,
        context,
        action="employee.session_revoked",
        target_type="employee",
        target_id=target.id,
        metadata={
            "email": target.user.email,
            "sessions_valid_after": now.isoformat(),
            "via": "offboarding",
            "membership_scoped": True,
        },
    )
    record_from_context(
        session,
        context,
        action="employee.offboarding.committed",
        target_type="employee",
        target_id=target.id,
        metadata=metadata,
    )
    session.commit()
    session.refresh(target)
    session.refresh(target.user)
    session.refresh(profile)
    return EmployeeOffboardingCommitResponse(
        employee=_employee_record(session, target),
        reassigned_to=_employee_record(session, reassign_to),
        preview=preview,
        deactivated=True,
        sessions_revoked=True,
    )


def _audit_metadata(event: AuditEvent) -> dict[str, object]:
    if not event.metadata_json:
        return {}
    try:
        value = json.loads(event.metadata_json)
    except json.JSONDecodeError:
        return {"raw": event.metadata_json}
    return value if isinstance(value, dict) else {"value": value}


def list_employee_audit(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    limit: int = 100,
) -> EmployeeAuditResponse:
    membership = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    clamped_limit = max(1, min(limit, 200))
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.company_id == context.company.id,
                or_(
                    (AuditEvent.target_type == "employee")
                    & (AuditEvent.target_id == membership.id),
                    (AuditEvent.target_type == "company_membership")
                    & (AuditEvent.target_id == membership.id),
                ),
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(clamped_limit)
        )
    )
    return EmployeeAuditResponse(
        employee=_employee_record(session, membership),
        events=[
            EmployeeAuditEventRecord(
                id=event.id,
                action=event.action,
                actor_membership_id=event.actor_membership_id,
                actor_label=event.actor_label,
                target_type=event.target_type,
                target_id=event.target_id,
                result=event.result,
                metadata=_audit_metadata(event),
                created_at=event.created_at,
            )
            for event in events
        ],
    )


def resend_employee_setup(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
) -> EmployeeTokenDelivery:
    membership = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    profile = _get_or_create_profile(
        session,
        membership=membership,
        status_value=EmployeeEmploymentStatus.INVITED,
    )
    if (
        profile.setup_completed_at is not None
        and profile.employment_status == EmployeeEmploymentStatus.ACTIVE
    ):
        _raise_bad_request("This employee has already completed account setup.")
    if not membership.is_active or not membership.user.is_active:
        _raise_bad_request("Inactive employees cannot receive setup links.")
    issued = _issue_account_token(
        session,
        company=context.company,
        membership=membership,
        purpose=AccountSetupTokenPurpose.ACCOUNT_SETUP,
        created_by_membership_id=context.membership.id,
        actor_context=context,
    )
    session.commit()
    return issued.delivery_response()


def issue_employee_password_reset(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
) -> EmployeeTokenDelivery:
    membership = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    if not membership.is_active or not membership.user.is_active:
        _raise_bad_request("Inactive employees cannot receive password reset links.")
    issued = _issue_account_token(
        session,
        company=context.company,
        membership=membership,
        purpose=AccountSetupTokenPurpose.PASSWORD_RESET,
        created_by_membership_id=context.membership.id,
        actor_context=context,
    )
    session.commit()
    return issued.delivery_response()


class InvalidAccountToken(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account link is invalid or expired.",
        )


def _consume_token(
    session: Session,
    *,
    token: str,
    purpose: AccountSetupTokenPurpose,
) -> tuple[AccountSetupToken, CompanyMembership]:
    if not token:
        raise InvalidAccountToken()
    token_hash = _hash_token(token)
    now = _utcnow()
    claim_result = session.execute(
        update(AccountSetupToken)
        .where(
            AccountSetupToken.token_hash == token_hash,
            AccountSetupToken.purpose == purpose,
            AccountSetupToken.used_at.is_(None),
            AccountSetupToken.expires_at > now,
        )
        .values(used_at=now)
    )
    if claim_result.rowcount != 1:
        raise InvalidAccountToken()
    row = session.scalar(
        select(AccountSetupToken).where(
            AccountSetupToken.token_hash == token_hash,
            AccountSetupToken.purpose == purpose,
        )
    )
    if row is None:
        raise InvalidAccountToken()
    membership = session.scalar(
        select(CompanyMembership)
        .options(
            joinedload(CompanyMembership.company),
            joinedload(CompanyMembership.user),
            joinedload(CompanyMembership.employee_profile),
        )
        .where(
            CompanyMembership.id == row.membership_id,
            CompanyMembership.company_id == row.company_id,
        )
    )
    if membership is None:
        raise InvalidAccountToken()
    if not membership.is_active or not membership.user.is_active:
        raise InvalidAccountToken()
    if purpose == AccountSetupTokenPurpose.ACCOUNT_SETUP:
        profile = membership.employee_profile
        if (
            profile is None
            or profile.employment_status != EmployeeEmploymentStatus.INVITED
            or profile.setup_completed_at is not None
        ):
            raise InvalidAccountToken()
    return row, membership


def complete_account_setup(
    session: Session,
    *,
    payload: AccountSetupCompleteRequest,
) -> SessionContext:
    return _complete_account_token(
        session,
        payload=payload,
        purpose=AccountSetupTokenPurpose.ACCOUNT_SETUP,
    )


def complete_password_reset(
    session: Session,
    *,
    payload: AccountSetupCompleteRequest,
) -> SessionContext:
    return _complete_account_token(
        session,
        payload=payload,
        purpose=AccountSetupTokenPurpose.PASSWORD_RESET,
    )


def _complete_account_token(
    session: Session,
    *,
    payload: AccountSetupCompleteRequest,
    purpose: AccountSetupTokenPurpose,
) -> SessionContext:
    try:
        enforce_password_policy(payload.password)
    except WeakPasswordError as exc:
        _raise_bad_request(str(exc))
    row, membership = _consume_token(session, token=payload.token, purpose=purpose)
    profile = _get_or_create_profile(session, membership=membership)
    now = _utcnow()
    membership.user.password_hash = hash_password(payload.password)
    profile.force_password_change = False
    if purpose == AccountSetupTokenPurpose.ACCOUNT_SETUP:
        profile.setup_completed_at = now
        profile.employment_status = EmployeeEmploymentStatus.ACTIVE
        action = "employee.account_setup.completed"
    else:
        membership.sessions_valid_after = now
        action = "employee.password_reset.completed"
    profile.updated_at = now
    session.flush()
    record_audit(
        session,
        company_id=membership.company_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label=f"employee:{membership.user.email}",
        action=action,
        target_type="employee",
        target_id=membership.id,
        result=AuditResult.SUCCESS,
        metadata={"token_id": row.id, "purpose": purpose.value},
    )
    session.commit()
    session.refresh(membership)
    session.refresh(membership.company)
    session.refresh(membership.user)
    return SessionContext(
        company=membership.company,
        user=membership.user,
        membership=membership,
    )


def start_password_reset(
    session: Session,
    *,
    company_slug: str,
    email: str,
) -> PasswordResetStartResponse:
    company = session.scalar(select(Company).where(Company.slug == company_slug.strip().lower()))
    debug_token: str | None = None
    if company is not None:
        membership = session.scalar(
            select(CompanyMembership)
            .options(
                joinedload(CompanyMembership.user),
                joinedload(CompanyMembership.employee_profile),
            )
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == company.id,
                CompanyMembership.is_active.is_(True),
                User.email == email.strip().lower(),
                User.is_active.is_(True),
            )
        )
        if membership is not None:
            issued = _issue_account_token(
                session,
                company=company,
                membership=membership,
                purpose=AccountSetupTokenPurpose.PASSWORD_RESET,
                created_by_membership_id=None,
                actor_context=None,
            )
            session.commit()
            debug_token = issued.token if _debug_tokens_allowed() else None
    return PasswordResetStartResponse(delivered=True, debug_token=debug_token)


def record_employee_login(
    session: Session,
    *,
    membership: CompanyMembership,
) -> None:
    profile = membership.employee_profile
    if profile is None:
        return
    now = _utcnow()
    profile.last_login_at = now
    profile.updated_at = now
    record_audit(
        session,
        company_id=membership.company_id,
        actor_type=AuditActorType.HUMAN,
        actor_membership_id=membership.id,
        actor_label=membership.user.full_name or membership.user.email,
        action="employee.login",
        target_type="employee",
        target_id=membership.id,
        result=AuditResult.SUCCESS,
        metadata={"email": membership.user.email},
    )
    session.commit()


def record_employee_login_async(membership_id: str) -> None:
    """Background-task entrypoint for the deferred employee.login write.

    P1-1: the login route (auth.login) schedules this via FastAPI
    BackgroundTasks so the audit INSERT + last_login UPDATE + commit no
    longer sit on the login critical path.

    The request that triggered login has already returned and its
    request-scoped session is closed — so this opens a FRESH session
    via get_session_factory() and never touches the request session.
    Best-effort: a failure to record the login audit must never affect
    the (already-sent) login response, so exceptions are swallowed
    after a rollback. session.commit() is preserved (inside
    record_employee_login) — it is not dropped.
    """
    from caseops_api.db.session import get_session_factory

    session = get_session_factory()()
    try:
        membership = session.scalar(
            select(CompanyMembership)
            .options(
                joinedload(CompanyMembership.user),
                joinedload(CompanyMembership.employee_profile),
            )
            .where(CompanyMembership.id == membership_id)
        )
        if membership is not None:
            record_employee_login(session, membership=membership)
    except Exception:  # noqa: BLE001 - fire-and-forget; never propagate to the worker
        # Best-effort, but NOT silent: a dropped login audit is a gap in
        # the security audit trail, so emit a WARNING + full traceback
        # for ops. The auth-derived membership id is deliberately NOT
        # interpolated — CodeQL py/clear-text-logging-sensitive-data
        # treats values flowing from the authentication path as
        # sensitive. The traceback plus the request-scoped tenant/user
        # logging context (set_tenant_context) are sufficient to
        # diagnose which login dropped its audit.
        logger.warning("deferred employee.login audit write failed", exc_info=True)
        session.rollback()
    finally:
        session.close()


__all__ = [
    "commit_employee_offboarding",
    "complete_account_setup",
    "complete_password_reset",
    "create_employee",
    "get_employee",
    "issue_employee_password_reset",
    "list_employee_audit",
    "list_employees",
    "preview_employee_offboarding",
    "record_employee_login",
    "record_employee_login_async",
    "resend_employee_setup",
    "start_password_reset",
    "update_employee",
]
