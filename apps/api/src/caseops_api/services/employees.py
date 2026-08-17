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
    HearingReminderStatus,
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketQueue,
    IpDocketRecord,
    IpRelatedRightObligation,
    IpResponsibilityAssignment,
    IpWorkspaceConfiguration,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterHearing,
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
from caseops_api.services.assignment_memberships import (
    has_other_active_company_memberships,
    lock_company_memberships_for_assignment,
    lock_user_for_membership_deactivation,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.employee_deactivation import (
    assert_no_operational_ip_work_before_deactivation,
    operational_ip_docket_deadlines_for_membership,
    operational_ip_live_reference_counts,
    operational_ip_notification_intents_for_membership,
    tombstone_membership_calendar_syncs_before_deactivation,
)
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
    "ip_related_right_obligations",
    "ip_docket_queues",
    # Retained as a response-count compatibility key. Historical reminders are
    # never retargeted in place; operational IP reminders are blockers below.
    "hearing_reminders",
)
OFFBOARDING_UNSUPPORTED_TYPES = (
    "drafts",
    "draft_reviews",
    "hearing_packs",
    "portal_grants",
    "email_templates",
    "ip_coverage_pending_replacements",
    "ip_coverage_emergency_escalations",
    "ip_coverage_backup_assignments",
    "ip_coverage_shared_deadlines",
    "ip_deadline_projection_repairs",
    "ip_responsibility_assignments",
    "ip_docket_hearings",
    "ip_hearing_reminders",
    "ip_notification_deliveries",
    "ip_workspace_configuration",
)
OFFBOARDING_TERMINAL_COVERAGE_STATUSES = ("inactive_lifecycle", "completed")
OFFBOARDING_TERMINAL_DOCKET_STATUSES = (
    "archived",
    "abandoned",
    "transferred",
    "retired",
    "closed",
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


def _lock_employee_memberships_for_offboarding(
    session: Session,
    *,
    company_id: str,
    membership_ids: set[str],
) -> dict[str, CompanyMembership]:
    """Lock offboarding participants in stable order before assignment work."""

    memberships_by_id = lock_company_memberships_for_assignment(
        session,
        company_id=company_id,
        membership_ids=membership_ids,
    )
    for membership in memberships_by_id.values():
        session.expire(
            membership,
            ["employee_profile", "custom_role"],
        )
    return memberships_by_id


def _lock_employee_writer_context(
    session: Session,
    *,
    context: SessionContext,
    membership_ids: set[str | None] | None = None,
) -> tuple[SessionContext, dict[str, CompanyMembership]]:
    """Fence a directory actor and affected employees before child writes."""

    requested_ids = {
        membership_id
        for membership_id in (membership_ids or set()) | {context.membership.id}
        if membership_id
    }
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=requested_ids,
    )
    actor = memberships.get(context.membership.id)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active company membership is required for this employee mutation.",
        )
    actor = require_locked_membership_capability(
        session,
        actor,
        "company:manage_users",
    )
    if set(memberships) != requested_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found.",
        )
    for membership in memberships.values():
        session.expire(membership, ["employee_profile", "custom_role"])
    return (
        SessionContext(
            company=context.company,
            membership=actor,
            user=actor.user,
        ),
        memberships,
    )


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
    return has_other_active_company_memberships(session, membership=membership)


def _operational_offboarding_ip_coverage_rows(
    session: Session,
    *,
    context: SessionContext,
    target: CompanyMembership,
) -> list[tuple[IpDeadlineCoverage, MatterDeadline, IpDocketRecord, Matter | None]]:
    """Load the exact operational coverage set that the commit path can move.

    The canonical coverage query understands both Matter-backed dockets and
    standalone IP dockets. Reusing it keeps preview and commit fidelity while
    the second pass only hydrates labels and revalidates each tenant/target
    relationship.
    """

    from caseops_api.services.ip_operations import _coverages_for_member

    coverages = _coverages_for_member(
        session,
        context=context,
        membership_id=target.id,
        include_auxiliary_roles=True,
    )
    if not coverages:
        return []

    dockets = {
        docket.id: docket
        for docket in session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.company_id == context.company.id,
                IpDocketRecord.id.in_({row.docket_id for row in coverages}),
            )
        ).all()
    }
    deadlines = {
        deadline.id: deadline
        for deadline in session.scalars(
            select(MatterDeadline).where(
                MatterDeadline.company_id == context.company.id,
                MatterDeadline.id.in_({row.matter_deadline_id for row in coverages}),
            )
        ).all()
    }
    matter_ids = {docket.matter_id for docket in dockets.values() if docket.matter_id}
    matters = {
        matter.id: matter
        for matter in session.scalars(
            select(Matter).where(
                Matter.company_id == context.company.id,
                Matter.id.in_(matter_ids or {""}),
            )
        ).all()
    }

    rows: list[tuple[IpDeadlineCoverage, MatterDeadline, IpDocketRecord, Matter | None]] = []
    for coverage in coverages:
        docket = dockets.get(coverage.docket_id)
        deadline = deadlines.get(coverage.matter_deadline_id)
        if docket is None or deadline is None:
            continue
        docket_owned = deadline.matter_id is None and deadline.ip_docket_id == docket.id
        matter_owned = (
            docket.matter_id is not None
            and deadline.matter_id == docket.matter_id
            and deadline.ip_docket_id is None
        )
        if not docket_owned and not matter_owned:
            continue
        matter = matters.get(docket.matter_id) if docket.matter_id else None
        if docket.matter_id is not None and matter is None:
            continue
        rows.append((coverage, deadline, docket, matter))
    return rows


def _collect_offboarding_objects(
    session: Session,
    *,
    context: SessionContext,
    target: CompanyMembership,
) -> tuple[
    list[EmployeeOffboardingObject],
    list[EmployeeOffboardingObject],
    set[str],
    list[IpDeadlineCoverage],
    list[IpDocketRecord],
]:
    from caseops_api.services.ip_operations import (
        _coverage_has_live_escalation,
        _membership_can_cover_docket,
        _operational_coverage_ids_for_deadline,
    )

    company_id = context.company.id
    supported: list[EmployeeOffboardingObject] = []
    unsupported: list[EmployeeOffboardingObject] = []
    affected_matter_ids: set[str] = set()
    affected_operational_dockets: dict[str, IpDocketRecord] = {}

    matters = list(
        session.scalars(
            select(Matter)
            .where(
                Matter.company_id == company_id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("disposed", "closed")),
                or_(
                    Matter.assignee_membership_id == target.id,
                    Matter.responsible_lawyer_membership_id == target.id,
                ),
            )
            .order_by(Matter.matter_code.asc(), Matter.id.asc())
        )
    )
    for matter in matters:
        relations: list[str] = []
        if matter.assignee_membership_id == target.id:
            relations.append("assignee")
        if matter.responsible_lawyer_membership_id == target.id:
            relations.append("responsible lawyer")
        affected_matter_ids.add(matter.id)
        supported.append(
            _offboarding_object(
                "matters",
                matter.id,
                label=f"{matter.matter_code} - {matter.title}",
                relation="/".join(relations),
                supported=True,
                matter_id=matter.id,
            )
        )
    linked_role_dockets = list(
        session.scalars(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.company_id == company_id,
                IpDocketRecord.matter_id.in_({matter.id for matter in matters} or {""}),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
            )
            .order_by(IpDocketRecord.id)
        )
    )
    affected_operational_dockets.update(
        {docket.id: docket for docket in linked_role_dockets}
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
                Matter.is_active.is_(True),
                Matter.status.notin_(("disposed", "closed")),
                MatterTask.owner_membership_id == target.id,
                MatterTask.status.notin_(("completed", "cancelled")),
                MatterTask.neutralized_at.is_(None),
                MatterTask.cancelled_by_matter_disposal.is_(False),
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
                Matter.is_active.is_(True),
                Matter.status.notin_(("disposed", "closed")),
                MatterDeadline.assignee_membership_id == target.id,
                MatterDeadline.status.in_(
                    (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                ),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
            )
            .order_by(Matter.matter_code.asc(), MatterDeadline.due_on.asc())
        ).all()
    )
    shared_deadline_ids: set[str] = set()
    shared_coverage_object_ids: set[str] = set()
    projection_repair_coverage_ids: set[str] = set()

    def add_shared_coverage_blockers(
        deadline: MatterDeadline,
        *,
        label: str,
        matter_id: str | None,
    ) -> bool:
        coverage_ids = _operational_coverage_ids_for_deadline(
            session,
            company_id=company_id,
            deadline=deadline,
        )
        if len(coverage_ids) <= 1:
            return False
        shared_deadline_ids.add(deadline.id)
        for coverage_id in coverage_ids:
            if coverage_id in shared_coverage_object_ids:
                continue
            shared_coverage_object_ids.add(coverage_id)
            unsupported.append(
                _offboarding_object(
                    "ip_coverage_shared_deadlines",
                    coverage_id,
                    label=label,
                    relation="shared deadline; group handoff workflow required",
                    supported=False,
                    matter_id=matter_id,
                )
            )
        return True

    def has_uncovered_legal_projection(deadline: MatterDeadline) -> bool:
        coverage_ids = _operational_coverage_ids_for_deadline(
            session,
            company_id=company_id,
            deadline=deadline,
        )
        if coverage_ids:
            return False
        return (
            session.scalar(
                select(IpDeadline.id).where(
                    IpDeadline.company_id == company_id,
                    IpDeadline.matter_deadline_id == deadline.id,
                    IpDeadline.state.in_(("confirmed", "overdue")),
                )
            )
            is not None
        )

    def has_invalid_retained_coverage_role(
        deadline: MatterDeadline,
        *,
        label: str,
        matter_id: str | None,
    ) -> bool:
        coverage_ids = _operational_coverage_ids_for_deadline(
            session,
            company_id=company_id,
            deadline=deadline,
        )
        if len(coverage_ids) != 1:
            return False
        coverage = session.get(IpDeadlineCoverage, coverage_ids[0])
        docket = (
            session.get(IpDocketRecord, coverage.docket_id)
            if coverage is not None
            else None
        )
        if coverage is None or docket is None:
            invalid = True
        else:
            retained_ids = {
                membership_id
                for membership_id in (
                    coverage.responsible_membership_id,
                    coverage.backup_membership_id,
                )
                if membership_id is not None and membership_id != target.id
            }
            memberships = {
                membership_id: session.get(CompanyMembership, membership_id)
                for membership_id in retained_ids
            }
            invalid = (
                coverage.responsible_membership_id
                == coverage.backup_membership_id
                or any(
                    membership is None
                    or not membership.is_active
                    or not membership.user.is_active
                    or not _membership_can_cover_docket(
                        session,
                        context=context,
                        membership=membership,
                        docket=docket,
                    )
                    for membership in memberships.values()
                )
            )
        if not invalid:
            return False
        if coverage_ids[0] not in projection_repair_coverage_ids:
            projection_repair_coverage_ids.add(coverage_ids[0])
            unsupported.append(
                _offboarding_object(
                    "ip_deadline_projection_repairs",
                    coverage_ids[0],
                    label=label,
                    relation=(
                        "authoritative coverage owner or backup is inactive, "
                        "inaccessible, or role-collapsed; repair required"
                    ),
                    supported=False,
                    matter_id=matter_id,
                )
            )
        return True

    for deadline, matter in deadline_rows:
        affected_matter_ids.add(matter.id)
        label = f"{matter.matter_code} - {deadline.title}"
        if add_shared_coverage_blockers(
            deadline,
            label=label,
            matter_id=matter.id,
        ):
            continue
        if has_invalid_retained_coverage_role(
            deadline,
            label=label,
            matter_id=matter.id,
        ):
            continue
        if has_uncovered_legal_projection(deadline):
            unsupported.append(
                _offboarding_object(
                    "ip_deadline_projection_repairs",
                    deadline.id,
                    label=label,
                    relation="legal projection without coverage; repair required",
                    supported=False,
                    matter_id=matter.id,
                )
            )
            continue
        supported.append(
            _offboarding_object(
                "matter_deadlines",
                deadline.id,
                label=label,
                relation="assignee",
                supported=True,
                matter_id=matter.id,
            )
        )
    linked_task_dockets = list(
        session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.company_id == company_id,
                IpDocketRecord.matter_id.in_(
                    {matter.id for _task, matter in task_rows} or {""}
                ),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
            )
        )
    )
    affected_operational_dockets.update(
        {docket.id: docket for docket in linked_task_dockets}
    )
    supported_deadline_ids = {deadline.id for deadline, _matter in deadline_rows}

    docket_deadline_rows = operational_ip_docket_deadlines_for_membership(
        session,
        company_id=company_id,
        membership_id=target.id,
    )
    for deadline, docket in docket_deadline_rows:
        affected_operational_dockets[docket.id] = docket
        if docket.matter_id is not None:
            affected_matter_ids.add(docket.matter_id)
        if deadline.id in supported_deadline_ids or deadline.id in shared_deadline_ids:
            continue
        label = f"{docket.primary_identifier or docket.title} - {deadline.title}"
        if add_shared_coverage_blockers(
            deadline,
            label=label,
            matter_id=docket.matter_id,
        ):
            continue
        if has_invalid_retained_coverage_role(
            deadline,
            label=label,
            matter_id=docket.matter_id,
        ):
            continue
        if has_uncovered_legal_projection(deadline):
            unsupported.append(
                _offboarding_object(
                    "ip_deadline_projection_repairs",
                    deadline.id,
                    label=label,
                    relation="legal projection without coverage; repair required",
                    supported=False,
                    matter_id=docket.matter_id,
                )
            )
            continue
        supported.append(
            _offboarding_object(
                "matter_deadlines",
                deadline.id,
                label=label,
                relation="assignee",
                supported=True,
                matter_id=docket.matter_id,
            )
        )

    ip_coverage_rows = _operational_offboarding_ip_coverage_rows(
        session,
        context=context,
        target=target,
    )
    for coverage, deadline, docket, matter in ip_coverage_rows:
        if matter is not None:
            label = f"{matter.matter_code} - {deadline.title}"
            matter_id = matter.id
        else:
            label = f"{docket.primary_identifier or docket.title} - {deadline.title}"
            matter_id = None
        if (
            coverage.pending_replacement_membership_id == target.id
            and coverage.replacement_decision == "pending"
        ):
            unsupported.append(
                _offboarding_object(
                    "ip_coverage_pending_replacements",
                    coverage.id,
                    label=label,
                    relation="pending replacement; resolve before offboarding",
                    supported=False,
                    matter_id=matter_id,
                )
            )
        if (
            coverage.emergency_escalation_membership_id == target.id
            and _coverage_has_live_escalation(coverage)
        ):
            unsupported.append(
                _offboarding_object(
                    "ip_coverage_emergency_escalations",
                    coverage.id,
                    label=label,
                    relation="decline escalation; reassign before offboarding",
                    supported=False,
                    matter_id=matter_id,
                )
            )
        if coverage.backup_membership_id == target.id:
            unsupported.append(
                _offboarding_object(
                    "ip_coverage_backup_assignments",
                    coverage.id,
                    label=label,
                    relation="backup; accepted backup handoff is required",
                    supported=False,
                    matter_id=matter_id,
                )
            )
        shared_coverage_ids = _operational_coverage_ids_for_deadline(
            session,
            company_id=company_id,
            deadline=deadline,
        )
        if len(shared_coverage_ids) > 1:
            add_shared_coverage_blockers(
                deadline,
                label=label,
                matter_id=matter_id,
            )
            continue
        if has_invalid_retained_coverage_role(
            deadline,
            label=label,
            matter_id=matter_id,
        ):
            continue
        relations: list[str] = []
        if coverage.responsible_membership_id == target.id:
            relations.append("responsible")
        # Backup ownership has no accepted/pending discriminator in the
        # schema, so it is a fail-closed manual blocker rather than a transfer.
        if not relations:
            continue
        if matter is not None:
            affected_matter_ids.add(matter.id)
        affected_operational_dockets[docket.id] = docket
        supported.append(
            _offboarding_object(
                "ip_deadline_coverages",
                coverage.id,
                label=label,
                relation="IP deadline " + "/".join(relations),
                supported=True,
                matter_id=matter_id,
            )
        )

    docket_task_rows = list(
        session.execute(
            select(MatterTask, IpDocketRecord, Matter)
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.id == MatterTask.ip_docket_id,
                    IpDocketRecord.company_id == MatterTask.company_id,
                ),
            )
            .outerjoin(Matter, Matter.id == IpDocketRecord.matter_id)
            .where(
                MatterTask.company_id == company_id,
                MatterTask.matter_id.is_(None),
                MatterTask.owner_membership_id == target.id,
                MatterTask.status.notin_(("completed", "cancelled")),
                MatterTask.neutralized_at.is_(None),
                MatterTask.cancelled_by_matter_disposal.is_(False),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
            )
            .order_by(IpDocketRecord.id, MatterTask.title, MatterTask.id)
        ).all()
    )
    for task, docket, matter in docket_task_rows:
        affected_operational_dockets[docket.id] = docket
        if matter is not None:
            affected_matter_ids.add(matter.id)
        supported.append(
            _offboarding_object(
                "matter_tasks",
                task.id,
                label=f"{docket.primary_identifier or docket.title} - {task.title}",
                relation="IP docket task owner",
                supported=True,
                matter_id=docket.matter_id,
            )
        )

    obligation_rows = list(
        session.execute(
            select(IpRelatedRightObligation, IpDocketRecord, Matter)
            .join(IpDocketRecord, IpDocketRecord.id == IpRelatedRightObligation.docket_id)
            .outerjoin(Matter, Matter.id == IpDocketRecord.matter_id)
            .outerjoin(
                MatterDeadline,
                MatterDeadline.id == IpRelatedRightObligation.matter_deadline_id,
            )
            .where(
                IpRelatedRightObligation.company_id == company_id,
                IpRelatedRightObligation.owner_membership_id == target.id,
                IpRelatedRightObligation.status == "open",
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
                or_(
                    IpRelatedRightObligation.matter_deadline_id.is_(None),
                    and_(
                        MatterDeadline.status.in_(
                            (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                        ),
                        MatterDeadline.neutralized_at.is_(None),
                        MatterDeadline.cancelled_by_matter_disposal.is_(False),
                    ),
                ),
            )
            .order_by(IpDocketRecord.id, IpRelatedRightObligation.id)
        ).all()
    )
    for obligation, docket, matter in obligation_rows:
        affected_operational_dockets[docket.id] = docket
        if matter is not None:
            affected_matter_ids.add(matter.id)
        supported.append(
            _offboarding_object(
                "ip_related_right_obligations",
                obligation.id,
                label=f"{docket.primary_identifier or docket.title} - {obligation.title}",
                relation="related-right obligation owner",
                supported=True,
                matter_id=docket.matter_id,
            )
        )

    def active_hearing_relations(hearing: MatterHearing) -> list[str]:
        relations: list[str] = []
        if hearing.responsible_membership_id == target.id:
            relations.append("responsible")
        if target.id in (hearing.attendee_membership_ids_json or []):
            relations.append("attendee")
        policy = hearing.reminder_policy_json or {}
        if target.id in (policy.get("recipient_membership_ids") or []):
            relations.append("reminder recipient")
        if policy.get("escalation_membership_id") == target.id:
            relations.append("reminder escalation")
        return relations

    hearing_rows = list(
        session.execute(
            select(MatterHearing, IpDocketRecord, Matter)
            .join(IpDocketRecord, IpDocketRecord.id == MatterHearing.ip_docket_id)
            .outerjoin(Matter, Matter.id == IpDocketRecord.matter_id)
            .where(
                MatterHearing.company_id == company_id,
                MatterHearing.matter_id.is_(None),
                MatterHearing.status.in_(("scheduled", "adjourned")),
                MatterHearing.neutralized_at.is_(None),
                MatterHearing.cancelled_by_matter_disposal.is_(False),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
            )
            .order_by(IpDocketRecord.id, MatterHearing.hearing_on, MatterHearing.id)
        ).all()
    )
    for hearing, docket, matter in hearing_rows:
        relations = active_hearing_relations(hearing)
        if not relations:
            continue
        affected_operational_dockets[docket.id] = docket
        if matter is not None:
            affected_matter_ids.add(matter.id)
        unsupported.append(
            _offboarding_object(
                "ip_docket_hearings",
                hearing.id,
                label=f"{docket.primary_identifier or docket.title} - {hearing.purpose}",
                relation="/".join(relations) + "; update the hearing first",
                supported=False,
                matter_id=docket.matter_id,
            )
        )

    linked_matter_hearing_rows = list(
        session.execute(
            select(MatterHearing, Matter, IpDocketRecord)
            .join(
                Matter,
                and_(
                    Matter.id == MatterHearing.matter_id,
                    Matter.company_id == MatterHearing.company_id,
                ),
            )
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.matter_id == Matter.id,
                    IpDocketRecord.company_id == Matter.company_id,
                ),
            )
            .where(
                MatterHearing.company_id == company_id,
                MatterHearing.matter_id.is_not(None),
                MatterHearing.status.in_(("scheduled", "adjourned")),
                MatterHearing.neutralized_at.is_(None),
                MatterHearing.cancelled_by_matter_disposal.is_(False),
                Matter.is_active.is_(True),
                Matter.status.notin_(("disposed", "closed")),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
            )
            .order_by(
                MatterHearing.id,
                IpDocketRecord.id,
            )
        ).all()
    )
    linked_hearings: dict[str, tuple[MatterHearing, Matter]] = {}
    for hearing, matter, docket in linked_matter_hearing_rows:
        if not active_hearing_relations(hearing):
            continue
        linked_hearings[hearing.id] = (hearing, matter)
        affected_operational_dockets[docket.id] = docket
    for hearing, matter in linked_hearings.values():
        relations = active_hearing_relations(hearing)
        if not relations:
            continue
        affected_matter_ids.add(matter.id)
        unsupported.append(
            _offboarding_object(
                "ip_docket_hearings",
                hearing.id,
                label=f"{matter.matter_code} - {hearing.purpose}",
                relation=(
                    "/".join(relations)
                    + "; update the linked-IP Matter hearing first"
                ),
                supported=False,
                matter_id=matter.id,
            )
        )

    queued_reminders = list(
        session.scalars(
            select(HearingReminder)
            .join(MatterHearing, MatterHearing.id == HearingReminder.hearing_id)
            .join(IpDocketRecord, IpDocketRecord.id == HearingReminder.ip_docket_id)
            .outerjoin(Matter, Matter.id == IpDocketRecord.matter_id)
            .where(
                HearingReminder.company_id == company_id,
                HearingReminder.recipient_membership_id == target.id,
                HearingReminder.status == HearingReminderStatus.QUEUED,
                HearingReminder.neutralized_at.is_(None),
                MatterHearing.status.in_(("scheduled", "adjourned")),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
            )
            .order_by(HearingReminder.scheduled_for, HearingReminder.id)
        )
    )
    for reminder in queued_reminders:
        unsupported.append(
            _offboarding_object(
                "ip_hearing_reminders",
                reminder.id,
                label=f"{reminder.channel} reminder scheduled {reminder.scheduled_for.isoformat()}",
                relation="queued recipient; update the hearing to regenerate safely",
                supported=False,
                matter_id=reminder.matter_id,
            )
        )

    coverage_responsible_by_deadline = {
        coverage.matter_deadline_id
        for coverage, _deadline, _docket, _matter in ip_coverage_rows
        if coverage.responsible_membership_id == target.id
    }
    queued_intents = operational_ip_notification_intents_for_membership(
        session,
        company_id=company_id,
        membership_id=target.id,
    )
    helper_owned_legal_deadline_ids = set(
        session.scalars(
            select(IpDeadline.id).where(
                IpDeadline.company_id == company_id,
                IpDeadline.matter_deadline_id.in_(
                    coverage_responsible_by_deadline or {""}
                ),
            )
        ).all()
    )
    for intent, docket in queued_intents:
        if (
            intent.recipient_membership_id == target.id
            and intent.schedule_source_type == "ip_deadline"
            and intent.schedule_source_id in helper_owned_legal_deadline_ids
        ):
            continue
        affected_operational_dockets[docket.id] = docket
        unsupported.append(
            _offboarding_object(
                "ip_notification_deliveries",
                intent.id,
                label=intent.title or intent.event_type,
                relation="queued recipient/escalation; cancel or regenerate before offboarding",
                supported=False,
                matter_id=intent.matter_id,
            )
        )

    live_responsibilities = list(
        session.execute(
            select(IpResponsibilityAssignment, IpDeadline, MatterDeadline, IpDocketRecord)
            .join(IpDeadline, IpDeadline.id == IpResponsibilityAssignment.deadline_id)
            .outerjoin(MatterDeadline, MatterDeadline.id == IpDeadline.matter_deadline_id)
            .join(IpDocketRecord, IpDocketRecord.id == IpResponsibilityAssignment.docket_id)
            .outerjoin(Matter, Matter.id == IpDocketRecord.matter_id)
            .where(
                IpResponsibilityAssignment.company_id == company_id,
                IpResponsibilityAssignment.membership_id == target.id,
                IpResponsibilityAssignment.effective_until.is_(None),
                IpDeadline.state.in_(("confirmed", "overdue")),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
            )
            .order_by(IpDeadline.id, IpResponsibilityAssignment.role)
        ).all()
    )
    for responsibility, legal_deadline, deadline, docket in live_responsibilities:
        if (
            responsibility.role == "primary"
            and deadline is not None
            and deadline.id in coverage_responsible_by_deadline
        ):
            continue
        unsupported.append(
            _offboarding_object(
                "ip_responsibility_assignments",
                responsibility.id,
                label=f"{docket.primary_identifier or docket.title} - {legal_deadline.title}",
                relation=f"live {responsibility.role} legal responsibility",
                supported=False,
                matter_id=docket.matter_id,
            )
        )

    workspace_config = session.scalar(
        select(IpWorkspaceConfiguration).where(
            IpWorkspaceConfiguration.company_id == company_id,
            IpWorkspaceConfiguration.escalation_owner_membership_id == target.id,
        )
    )
    if workspace_config is not None:
        unsupported.append(
            _offboarding_object(
                "ip_workspace_configuration",
                workspace_config.id,
                label="IP workspace configuration",
                relation="escalation owner; update the configuration first",
                supported=False,
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

    return (
        supported,
        unsupported,
        affected_matter_ids,
        [coverage for coverage, _deadline, _docket, _matter in ip_coverage_rows],
        list(affected_operational_dockets.values()),
    )


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
    from caseops_api.services.ip_operations import (
        _coverage_has_live_escalation,
        _membership_can_cover_docket,
    )

    (
        supported,
        unsupported,
        affected_matter_ids,
        operational_coverages,
        operational_dockets,
    ) = _collect_offboarding_objects(
        session,
        context=context,
        target=target,
    )
    blockers: list[str] = []
    unsupported_type_counts = _object_counts(
        unsupported,
        known_types=OFFBOARDING_UNSUPPORTED_TYPES,
    )

    pending_coverage_count = sum(
        coverage.pending_replacement_membership_id == target.id
        and coverage.replacement_decision == "pending"
        for coverage in operational_coverages
    )
    if pending_coverage_count:
        blockers.append(
            "Resolve pending IP coverage replacement proposals naming this employee "
            "before offboarding."
        )
    escalation_coverage_count = sum(
        coverage.emergency_escalation_membership_id == target.id
        and _coverage_has_live_escalation(coverage)
        for coverage in operational_coverages
    )
    if escalation_coverage_count:
        blockers.append(
            "Reassign active IP coverage decline-escalation duties before offboarding."
        )
    if unsupported_type_counts["ip_coverage_backup_assignments"]:
        blockers.append(
            "Complete an accepted IP coverage backup handoff before offboarding."
        )
    if unsupported_type_counts["ip_coverage_shared_deadlines"]:
        blockers.append(
            "Use the group handoff workflow for shared IP coverage deadlines "
            "before offboarding."
        )
    if unsupported_type_counts["ip_deadline_projection_repairs"]:
        blockers.append(
            "Repair inconsistent IP legal-deadline responsibility projections "
            "before offboarding."
        )
    if unsupported_type_counts["ip_responsibility_assignments"]:
        blockers.append(
            "Reassign active auxiliary IP legal responsibilities before offboarding."
        )
    if unsupported_type_counts["ip_docket_hearings"]:
        blockers.append(
            "Update scheduled IP hearings to remove this employee from active roles."
        )
    if unsupported_type_counts["ip_hearing_reminders"]:
        blockers.append(
            "Regenerate queued IP hearing reminders before offboarding."
        )
    if unsupported_type_counts["ip_notification_deliveries"]:
        blockers.append(
            "Cancel or regenerate queued IP notification deliveries before offboarding."
        )
    if unsupported_type_counts["ip_workspace_configuration"]:
        blockers.append(
            "Choose a new IP workspace escalation owner before offboarding."
        )

    if target.id == context.membership.id:
        blockers.append("You cannot offboard your own active session membership.")
    if target.role == MembershipRole.OWNER:
        if _active_owner_count(session, company_id=context.company.id) <= 1:
            blockers.append("Cannot offboard the last active owner.")
        else:
            blockers.append("Owner memberships cannot be offboarded through this flow.")
    # Pre-guard deployments can contain an inactive membership that still owns
    # operational IP work. Keep the privileged repair path reachable for that
    # exact legacy state; an ordinary already-inactive employee remains a
    # no-op/idempotency blocker.
    has_operational_ip_work = bool(
        operational_ip_live_reference_counts(
            session,
            company_id=context.company.id,
            membership_id=target.id,
        )
    )
    if (not target.is_active or not target.user.is_active) and not has_operational_ip_work:
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
        if any(
            not _membership_can_cover_docket(
                session,
                context=context,
                membership=reassign_to,
                docket=docket,
            )
            for docket in operational_dockets
        ):
            blockers.append("Replacement employee cannot access every affected IP docket.")
        if reassign_to.id == context.membership.id and any(
            coverage.responsible_membership_id == target.id
            for coverage in operational_coverages
        ):
            blockers.append(
                "Choose a replacement different from the IP coverage "
                "decline-escalation owner."
            )
        responsible_docket_ids = {
            coverage.docket_id
            for coverage in operational_coverages
            if coverage.responsible_membership_id == target.id
        }
        if any(
            docket.id in responsible_docket_ids
            and not _membership_can_cover_docket(
                session,
                context=context,
                membership=context.membership,
                docket=docket,
            )
            for docket in operational_dockets
        ):
            blockers.append(
                "The decline-escalation owner cannot access every affected IP docket."
            )
        backup_conflicts = sum(
            1
            for coverage in operational_coverages
            if (
                coverage.responsible_membership_id == target.id
                and coverage.backup_membership_id == target.id
            )
            or (
                coverage.backup_membership_id == target.id
                and coverage.responsible_membership_id == reassign_to.id
            )
            or (
                coverage.responsible_membership_id == target.id
                and coverage.backup_membership_id in {reassign_to.id, context.membership.id}
            )
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
    context, _memberships = _lock_employee_writer_context(
        session,
        context=context,
    )
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
    candidate_membership = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    context, locked_memberships = _lock_employee_writer_context(
        session,
        context=context,
        membership_ids={candidate_membership.id},
    )
    membership = locked_memberships[candidate_membership.id]
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _employee_record(session, membership)

    authorization_context = context

    if "role" in updates:
        _assert_role_assignment_allowed(
            context=authorization_context,
            target_membership=membership,
            role=payload.role,
        )
    elif authorization_context.membership.role == MembershipRole.ADMIN:
        # Admins may edit directory metadata, but role and lifecycle
        # changes stay owner-only to preserve the old membership rules.
        pass

    if (
        "employment_status" in updates
        and updates["employment_status"] == EmployeeEmploymentStatus.INACTIVE
        and membership.id == authorization_context.membership.id
    ):
        _raise_bad_request("You cannot mark your own employee record inactive.")
    if membership.role == MembershipRole.OWNER and (
        "role" in updates or "employment_status" in updates
    ):
        _raise_forbidden("Owner memberships cannot be modified here.")
    if authorization_context.membership.role != MembershipRole.OWNER and (
        "role" in updates or "employment_status" in updates
    ):
        _raise_forbidden("Only owners can change employee role or status.")

    if updates.get("employment_status") == EmployeeEmploymentStatus.INACTIVE:
        lock_user_for_membership_deactivation(session, membership=membership)
        assert_no_operational_ip_work_before_deactivation(
            session,
            context=authorization_context,
            membership=membership,
        )
        tombstone_membership_calendar_syncs_before_deactivation(
            session,
            company_id=context.company.id,
            membership_id=membership.id,
        )

    profile = _get_or_create_profile(session, membership=membership)

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
    context, locked_memberships = _lock_employee_writer_context(
        session,
        context=context,
        membership_ids={membership_id, payload.reassign_to_membership_id},
    )
    target = locked_memberships[membership_id]
    reassign_to = (
        locked_memberships[payload.reassign_to_membership_id]
        if payload.reassign_to_membership_id
        else None
    )
    if reassign_to is not None and (
        not reassign_to.is_active or not reassign_to.user.is_active
    ):
        _raise_bad_request("Replacement employee must be active.")
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


def _lock_offboarding_ip_work(
    session: Session,
    *,
    company_id: str,
    target_id: str,
) -> tuple[list[MatterDeadline], list[IpDocketRecord]]:
    """Prelock the complete IP work set in canonical lifecycle order.

    Candidate discovery is lock-free and identifiers only. The authoritative
    pass locks every candidate Matter, then docket, then deadline; the coverage
    service runs next and acquires coverage locks last. Docket-owned deadlines
    are revalidated after their parent/child locks and can be returned even
    when they have no coverage row.
    """

    coverage_candidates = list(
        session.execute(
            select(
                IpDeadlineCoverage.docket_id,
                IpDeadlineCoverage.matter_deadline_id,
            )
            .where(
                IpDeadlineCoverage.company_id == company_id,
                or_(
                    IpDeadlineCoverage.responsible_membership_id == target_id,
                    IpDeadlineCoverage.backup_membership_id == target_id,
                ),
                IpDeadlineCoverage.coverage_status.notin_(OFFBOARDING_TERMINAL_COVERAGE_STATUSES),
            )
            .order_by(IpDeadlineCoverage.id)
        ).all()
    )
    docket_deadline_candidates = list(
        session.execute(
            select(MatterDeadline.id, MatterDeadline.ip_docket_id)
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.id == MatterDeadline.ip_docket_id,
                    IpDocketRecord.company_id == MatterDeadline.company_id,
                ),
            )
            .where(
                MatterDeadline.company_id == company_id,
                MatterDeadline.matter_id.is_(None),
                MatterDeadline.assignee_membership_id == target_id,
                IpDocketRecord.company_id == company_id,
            )
            .order_by(IpDocketRecord.id, MatterDeadline.id)
        ).all()
    )
    task_docket_ids = set(
        session.scalars(
            select(MatterTask.ip_docket_id).where(
                MatterTask.company_id == company_id,
                MatterTask.matter_id.is_(None),
                MatterTask.owner_membership_id == target_id,
                MatterTask.ip_docket_id.is_not(None),
            )
        ).all()
    )
    obligation_docket_ids = set(
        session.scalars(
            select(IpRelatedRightObligation.docket_id).where(
                IpRelatedRightObligation.company_id == company_id,
                IpRelatedRightObligation.owner_membership_id == target_id,
            )
        ).all()
    )
    linked_matter_docket_ids = set(
        session.scalars(
            select(IpDocketRecord.id)
            .join(Matter, Matter.id == IpDocketRecord.matter_id)
            .where(
                IpDocketRecord.company_id == company_id,
                or_(
                    Matter.assignee_membership_id == target_id,
                    Matter.responsible_lawyer_membership_id == target_id,
                ),
            )
        ).all()
    )
    generic_matter_ids = set(
        session.scalars(
            select(Matter.id).where(
                Matter.company_id == company_id,
                or_(
                    Matter.assignee_membership_id == target_id,
                    Matter.responsible_lawyer_membership_id == target_id,
                ),
            )
        ).all()
    )
    generic_matter_ids.update(
        session.scalars(
            select(MatterTask.matter_id).where(
                MatterTask.company_id == company_id,
                MatterTask.owner_membership_id == target_id,
                MatterTask.matter_id.is_not(None),
            )
        ).all()
    )
    generic_deadline_candidates = list(
        session.execute(
            select(MatterDeadline.id, MatterDeadline.matter_id).where(
                MatterDeadline.company_id == company_id,
                MatterDeadline.assignee_membership_id == target_id,
                MatterDeadline.matter_id.is_not(None),
            )
        ).all()
    )
    generic_deadline_matter_ids = sorted(
        {
            matter_id
            for _deadline_id, matter_id in generic_deadline_candidates
            if matter_id is not None
        }
    )
    generic_matter_ids.update(
        generic_deadline_matter_ids
    )
    generic_deadline_docket_family = (
        tuple(
            session.execute(
                select(
                    IpDocketRecord.id,
                    IpDocketRecord.matter_id,
                    IpDocketRecord.status,
                    IpDocketRecord.is_active,
                    IpDocketRecord.archived_by_matter_disposal,
                    IpDocketRecord.access_policy_version,
                )
                .where(
                    IpDocketRecord.company_id == company_id,
                    IpDocketRecord.matter_id.in_(generic_deadline_matter_ids),
                    IpDocketRecord.is_active.is_(True),
                    IpDocketRecord.archived_by_matter_disposal.is_(False),
                    IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                )
                .order_by(IpDocketRecord.id)
            ).all()
        )
        if generic_deadline_matter_ids
        else ()
    )
    assignee_deadline_ids = {
        deadline_id for deadline_id, _docket_id in docket_deadline_candidates
    } | {
        deadline_id for deadline_id, _matter_id in generic_deadline_candidates
    }
    projection_coverage_candidates = list(
        session.execute(
            select(
                IpDeadlineCoverage.id,
                IpDeadlineCoverage.docket_id,
                IpDeadlineCoverage.matter_deadline_id,
            ).where(
                IpDeadlineCoverage.company_id == company_id,
                IpDeadlineCoverage.matter_deadline_id.in_(
                    assignee_deadline_ids or {""}
                ),
                IpDeadlineCoverage.coverage_status.notin_(
                    OFFBOARDING_TERMINAL_COVERAGE_STATUSES
                ),
            )
        ).all()
    )
    legal_projection_candidates = list(
        session.execute(
            select(
                IpDeadline.id,
                IpDeadline.docket_id,
                IpDeadline.matter_deadline_id,
            ).where(
                IpDeadline.company_id == company_id,
                IpDeadline.matter_deadline_id.in_(assignee_deadline_ids or {""}),
                IpDeadline.state.in_(("confirmed", "overdue")),
            )
        ).all()
    )
    docket_ids = sorted(
        {docket_id for docket_id, _deadline_id in coverage_candidates}
        | {
            docket_id
            for _deadline_id, docket_id in docket_deadline_candidates
            if docket_id is not None
        }
        | {docket_id for docket_id in task_docket_ids if docket_id is not None}
        | obligation_docket_ids
        | linked_matter_docket_ids
        | {
            docket_id
            for _coverage_id, docket_id, _deadline_id in projection_coverage_candidates
        }
        | {
            docket_id
            for _legal_id, docket_id, _deadline_id in legal_projection_candidates
        }
        | {
            docket_id
            for (
                docket_id,
                _matter_id,
                _docket_status,
                _is_active,
                _archived,
                _access_policy_version,
            ) in generic_deadline_docket_family
        }
    )
    deadline_ids = sorted(
        {deadline_id for _docket_id, deadline_id in coverage_candidates}
        | {deadline_id for deadline_id, _docket_id in docket_deadline_candidates}
        | {deadline_id for deadline_id, _matter_id in generic_deadline_candidates}
    )
    if not docket_ids and not generic_matter_ids:
        return [], []

    docket_parents = (
        list(
            session.execute(
                select(IpDocketRecord.id, IpDocketRecord.matter_id).where(
                    IpDocketRecord.company_id == company_id,
                    IpDocketRecord.id.in_(docket_ids),
                )
            ).all()
        )
        if docket_ids
        else []
    )
    matter_ids = sorted(
        {matter_id for _docket_id, matter_id in docket_parents if matter_id is not None}
        | {matter_id for matter_id in generic_matter_ids if matter_id is not None}
    )
    locked_matters = (
        list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == company_id,
                    Matter.id.in_(matter_ids),
                )
                .order_by(Matter.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        if matter_ids
        else []
    )
    refreshed_generic_deadline_docket_family = (
        tuple(
            session.execute(
                select(
                    IpDocketRecord.id,
                    IpDocketRecord.matter_id,
                    IpDocketRecord.status,
                    IpDocketRecord.is_active,
                    IpDocketRecord.archived_by_matter_disposal,
                    IpDocketRecord.access_policy_version,
                )
                .where(
                    IpDocketRecord.company_id == company_id,
                    IpDocketRecord.matter_id.in_(generic_deadline_matter_ids),
                    IpDocketRecord.is_active.is_(True),
                    IpDocketRecord.archived_by_matter_disposal.is_(False),
                    IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                )
                .order_by(IpDocketRecord.id)
                .execution_options(populate_existing=True)
            ).all()
        )
        if generic_deadline_matter_ids
        else ()
    )
    if refreshed_generic_deadline_docket_family != generic_deadline_docket_family:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_linked_docket_family_changed",
                "message": (
                    "Linked IP records or their access policy changed; preview "
                    "offboarding again."
                ),
            },
        )
    docket_ids = sorted(
        set(docket_ids)
        | {
            docket_id
            for (
                docket_id,
                _matter_id,
                _docket_status,
                _is_active,
                _archived,
                _access_policy_version,
            ) in refreshed_generic_deadline_docket_family
        }
    )
    locked_dockets = (
        list(
            session.scalars(
                select(IpDocketRecord)
                .where(
                    IpDocketRecord.company_id == company_id,
                    IpDocketRecord.id.in_(docket_ids),
                )
                .order_by(IpDocketRecord.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        if docket_ids
        else []
    )
    from caseops_api.services.ip_operations import (
        _lock_legal_deadlines_for_operational_deadlines,
    )

    legal_deadlines = _lock_legal_deadlines_for_operational_deadlines(
        session,
        company_id=company_id,
        matter_deadline_ids=deadline_ids,
    )
    if any(
        legal_deadline.docket_id not in docket_ids
        for legal_deadline in legal_deadlines.values()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IP legal-deadline projection changed; reload and retry.",
        )
    locked_deadlines = (
        list(
            session.scalars(
                select(MatterDeadline)
                .where(
                    MatterDeadline.company_id == company_id,
                    MatterDeadline.id.in_(deadline_ids),
                )
                .order_by(MatterDeadline.id)
                .with_for_update(of=MatterDeadline)
                .execution_options(populate_existing=True)
            ).all()
        )
        if deadline_ids
        else []
    )
    projection_coverage_ids = sorted(
        {
            coverage_id
            for coverage_id, _docket_id, _deadline_id in projection_coverage_candidates
        }
    )
    if projection_coverage_ids:
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == company_id,
                IpDeadlineCoverage.id.in_(projection_coverage_ids),
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update(of=IpDeadlineCoverage)
            .execution_options(populate_existing=True)
        ).all()
    dockets_by_id = {docket.id: docket for docket in locked_dockets}
    deadlines_by_id = {deadline.id: deadline for deadline in locked_deadlines}
    matters_by_id = {matter.id: matter for matter in locked_matters}
    operational_deadlines: dict[str, MatterDeadline] = {}
    operational_dockets: dict[str, IpDocketRecord] = {}
    for docket in locked_dockets:
        matter = matters_by_id.get(docket.matter_id) if docket.matter_id else None
        if (
            docket.is_active
            and not docket.archived_by_matter_disposal
            and docket.status not in OFFBOARDING_TERMINAL_DOCKET_STATUSES
            and (
                docket.matter_id is None
                or (
                    matter is not None
                    and matter.is_active
                    and matter.status not in {"disposed", "closed"}
                )
            )
        ):
            operational_dockets[docket.id] = docket
    for deadline_id, docket_id in docket_deadline_candidates:
        if docket_id is None:
            continue
        docket = dockets_by_id.get(docket_id)
        deadline = deadlines_by_id.get(deadline_id)
        if docket is None or deadline is None:
            continue
        matter = matters_by_id.get(docket.matter_id) if docket.matter_id else None
        if (
            not docket.is_active
            or docket.archived_by_matter_disposal
            or docket.status in OFFBOARDING_TERMINAL_DOCKET_STATUSES
            or (
                docket.matter_id is not None
                and (
                    matter is None
                    or not matter.is_active
                    or matter.status in {"disposed", "closed"}
                )
            )
            or deadline.company_id != company_id
            or deadline.matter_id is not None
            or deadline.ip_docket_id != docket.id
            or deadline.assignee_membership_id != target_id
            or deadline.status not in (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
            or deadline.neutralized_at is not None
            or deadline.cancelled_by_matter_disposal
        ):
            continue
        operational_deadlines[deadline.id] = deadline
    return list(operational_deadlines.values()), list(operational_dockets.values())


def _reassign_offboarding_objects(
    session: Session,
    *,
    context: SessionContext,
    company_id: str,
    target_id: str,
    replacement_id: str,
) -> dict[str, int]:
    counts = {object_type: 0 for object_type in OFFBOARDING_SUPPORTED_TYPES}

    from caseops_api.schemas.ip_operations import IpCoverageBulkReassignRequest
    from caseops_api.services.ip_coverage_projection import (
        cutover_ip_coverage_projection,
    )
    from caseops_api.services.ip_operations import (
        _membership_can_cover_docket,
        _operational_coverage_ids_for_deadline,
        bulk_reassign_ip_deadline_coverages,
    )

    docket_deadlines, docket_deadline_dockets = _lock_offboarding_ip_work(
        session,
        company_id=company_id,
        target_id=target_id,
    )
    replacement = _load_employee_membership(
        session,
        company_id=company_id,
        membership_id=replacement_id,
    )
    if any(
        not _membership_can_cover_docket(
            session,
            context=context,
            membership=replacement,
            docket=docket,
        )
        for docket in docket_deadline_dockets
    ):
        _raise_bad_request("Replacement employee cannot access every affected IP docket.")

    # The prelock owns Matter -> docket -> deadline. Coverage now locks its
    # children last and revalidates its exact operational row set before any
    # assignment is changed.
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
        replacement_source="employee_offboarding",
    )
    counts["ip_deadline_coverages"] = ip_reassignment.reassigned_count

    def reassign_or_repair_deadline(deadline: MatterDeadline) -> None:
        if deadline.assignee_membership_id != target_id:
            return
        operational_coverage_ids = _operational_coverage_ids_for_deadline(
            session,
            company_id=company_id,
            deadline=deadline,
        )
        if len(operational_coverage_ids) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_coverage_shared_deadline_handoff_required",
                    "message": "Shared IP deadline responsibility requires a group handoff.",
                    "matter_deadline_id": deadline.id,
                },
            )
        if operational_coverage_ids:
            coverage = session.get(IpDeadlineCoverage, operational_coverage_ids[0])
            if coverage is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Coverage projection changed; reload before offboarding.",
                )
            docket = session.get(IpDocketRecord, coverage.docket_id)
            if docket is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="IP docket projection changed; reload before offboarding.",
                )
            # Repair a legacy split-brain assignee to the already-authoritative
            # coverage owner. Never invent a third owner from the offboarding
            # request. The projection helper reconciles every calendar row.
            authoritative_id = coverage.responsible_membership_id
            resulting_role_ids = {
                membership_id
                for membership_id in (
                    authoritative_id,
                    coverage.backup_membership_id,
                )
                if membership_id is not None
            }
            resulting_memberships = {
                membership_id: session.get(CompanyMembership, membership_id)
                for membership_id in resulting_role_ids
            }
            if any(
                membership is None
                or not membership.is_active
                or not membership.user.is_active
                or not _membership_can_cover_docket(
                    session,
                    context=context,
                    membership=membership,
                    docket=docket,
                )
                for membership in resulting_memberships.values()
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ip_coverage_projection_owner_invalid",
                        "message": (
                            "The authoritative coverage owner or backup is inactive "
                            "or cannot access the linked record; repair coverage first."
                        ),
                        "matter_deadline_id": deadline.id,
                    },
                )
            deadline.assignee_membership_id = authoritative_id
            session.flush()
            cutover_ip_coverage_projection(
                session,
                context=context,
                docket=docket,
                coverage=coverage,
                previous_responsible_membership_id=authoritative_id,
                previous_backup_membership_id=coverage.backup_membership_id,
                reason="Employee offboarding projection repair",
                replacement_source="offboarding_projection_repair",
                responsible_accepted_at=coverage.accepted_at,
            )
            return
        legal_projection = session.scalar(
            select(IpDeadline.id).where(
                IpDeadline.company_id == company_id,
                IpDeadline.matter_deadline_id == deadline.id,
                IpDeadline.state.in_(("confirmed", "overdue")),
            )
        )
        if legal_projection is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_deadline_projection_repair_required",
                    "message": (
                        "A legal deadline without canonical coverage must be repaired "
                        "before this employee can be offboarded."
                    ),
                    "matter_deadline_id": deadline.id,
                },
            )
        deadline.assignee_membership_id = replacement_id

    for deadline in docket_deadlines:
        reassign_or_repair_deadline(deadline)
    docket_deadline_count = len(docket_deadlines)

    matters = list(
        session.scalars(
            select(Matter).where(
                Matter.company_id == company_id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("disposed", "closed")),
                or_(
                    Matter.assignee_membership_id == target_id,
                    Matter.responsible_lawyer_membership_id == target_id,
                ),
            )
        )
    )
    for matter in matters:
        if matter.assignee_membership_id == target_id:
            matter.assignee_membership_id = replacement_id
        if matter.responsible_lawyer_membership_id == target_id:
            matter.responsible_lawyer_membership_id = replacement_id
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
                Matter.is_active.is_(True),
                Matter.status.notin_(("disposed", "closed")),
                MatterTask.owner_membership_id == target_id,
                MatterTask.status.notin_(("completed", "cancelled")),
                MatterTask.neutralized_at.is_(None),
                MatterTask.cancelled_by_matter_disposal.is_(False),
            )
        )
    )
    for task in tasks:
        task.owner_membership_id = replacement_id
    docket_tasks = list(
        session.scalars(
            select(MatterTask)
            .join(IpDocketRecord, IpDocketRecord.id == MatterTask.ip_docket_id)
            .outerjoin(Matter, Matter.id == IpDocketRecord.matter_id)
            .where(
                MatterTask.company_id == company_id,
                MatterTask.matter_id.is_(None),
                MatterTask.owner_membership_id == target_id,
                MatterTask.status.notin_(("completed", "cancelled")),
                MatterTask.neutralized_at.is_(None),
                MatterTask.cancelled_by_matter_disposal.is_(False),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
            )
        )
    )
    for task in docket_tasks:
        task.owner_membership_id = replacement_id
    counts["matter_tasks"] = len(tasks) + len(docket_tasks)

    deadlines = list(
        session.scalars(
            select(MatterDeadline)
            .join(Matter, Matter.id == MatterDeadline.matter_id)
            .where(
                Matter.company_id == company_id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("disposed", "closed")),
                MatterDeadline.assignee_membership_id == target_id,
                MatterDeadline.status.in_(
                    (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                ),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
            )
        )
    )
    for deadline in deadlines:
        reassign_or_repair_deadline(deadline)
    counts["matter_deadlines"] = len(deadlines) + docket_deadline_count

    ip_obligations = list(
        session.scalars(
            select(IpRelatedRightObligation)
            .join(IpDocketRecord, IpDocketRecord.id == IpRelatedRightObligation.docket_id)
            .outerjoin(Matter, Matter.id == IpDocketRecord.matter_id)
            .outerjoin(
                MatterDeadline,
                MatterDeadline.id == IpRelatedRightObligation.matter_deadline_id,
            )
            .where(
                IpRelatedRightObligation.company_id == company_id,
                IpRelatedRightObligation.owner_membership_id == target_id,
                IpRelatedRightObligation.status == "open",
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(OFFBOARDING_TERMINAL_DOCKET_STATUSES),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
                or_(
                    IpRelatedRightObligation.matter_deadline_id.is_(None),
                    and_(
                        MatterDeadline.status.in_(
                            (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                        ),
                        MatterDeadline.neutralized_at.is_(None),
                        MatterDeadline.cancelled_by_matter_disposal.is_(False),
                    ),
                ),
            )
        )
    )
    for obligation in ip_obligations:
        obligation.owner_membership_id = replacement_id
    counts["ip_related_right_obligations"] = len(ip_obligations)

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
    if payload.reassign_to_membership_id is None:
        _raise_bad_request("Choose an active replacement employee before commit.")
    coverage_participants = session.execute(
        select(
            IpDeadlineCoverage.responsible_membership_id,
            IpDeadlineCoverage.backup_membership_id,
            IpDeadlineCoverage.pending_replacement_membership_id,
            IpDeadlineCoverage.emergency_escalation_membership_id,
        ).where(
            IpDeadlineCoverage.company_id == context.company.id,
            or_(
                IpDeadlineCoverage.responsible_membership_id == membership_id,
                IpDeadlineCoverage.backup_membership_id == membership_id,
            ),
            IpDeadlineCoverage.coverage_status.notin_(
                OFFBOARDING_TERMINAL_COVERAGE_STATUSES
            ),
        )
    ).all()
    coverage_participants.extend(
        session.execute(
            select(
                IpDeadlineCoverage.responsible_membership_id,
                IpDeadlineCoverage.backup_membership_id,
                IpDeadlineCoverage.pending_replacement_membership_id,
                IpDeadlineCoverage.emergency_escalation_membership_id,
            )
            .join(
                MatterDeadline,
                MatterDeadline.id == IpDeadlineCoverage.matter_deadline_id,
            )
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                MatterDeadline.company_id == context.company.id,
                MatterDeadline.assignee_membership_id == membership_id,
                IpDeadlineCoverage.coverage_status.notin_(
                    OFFBOARDING_TERMINAL_COVERAGE_STATUSES
                ),
            )
        ).all()
    )
    participant_ids = {
        participant_id
        for row in coverage_participants
        for participant_id in row
        if participant_id is not None
    }
    participant_ids.update(
        {
            membership_id,
            payload.reassign_to_membership_id,
            context.membership.id,
        }
    )
    locked_memberships = _lock_employee_memberships_for_offboarding(
        session,
        company_id=context.company.id,
        membership_ids=participant_ids,
    )
    target = locked_memberships.get(membership_id)
    reassign_to = locked_memberships.get(payload.reassign_to_membership_id)
    locked_actor = locked_memberships.get(context.membership.id)
    if target is None or reassign_to is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found.",
        )
    if (
        locked_actor is None
        or not locked_actor.is_active
        or not locked_actor.user.is_active
        or locked_actor.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}
    ):
        _raise_forbidden("Only active owners or admins can commit employee offboarding.")
    lock_user_for_membership_deactivation(session, membership=target)
    if not reassign_to.is_active or not reassign_to.user.is_active:
        _raise_bad_request("Replacement employee must be active.")
    legacy_inactive_ip_repair = not target.is_active or not target.user.is_active
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
    tombstone_membership_calendar_syncs_before_deactivation(
        session,
        company_id=context.company.id,
        membership_id=target.id,
    )
    session.flush()
    remaining_ip_references = operational_ip_live_reference_counts(
        session,
        company_id=context.company.id,
        membership_id=target.id,
    )
    if remaining_ip_references:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "employee_offboarding_incomplete",
                "message": (
                    "Operational IP responsibilities remain assigned to this employee; "
                    "reload the preview and resolve every blocker before deactivation."
                ),
                "live_reference_counts": remaining_ip_references,
            },
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
        "legacy_inactive_ip_repair": legacy_inactive_ip_repair,
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
            "legacy_inactive_ip_repair": legacy_inactive_ip_repair,
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
    candidate_membership = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    context, memberships = _lock_employee_writer_context(
        session,
        context=context,
        membership_ids={candidate_membership.id},
    )
    membership = memberships[candidate_membership.id]
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
    candidate_membership = _load_employee_membership(
        session,
        company_id=context.company.id,
        membership_id=membership_id,
    )
    context, memberships = _lock_employee_writer_context(
        session,
        context=context,
        membership_ids={candidate_membership.id},
    )
    membership = memberships[candidate_membership.id]
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
    membership = lock_company_memberships_for_assignment(
        session,
        company_id=membership.company_id,
        membership_ids=(membership.id,),
    ).get(membership.id)
    if membership is None or not membership.is_active or not membership.user.is_active:
        raise InvalidAccountToken()
    lock_user_for_membership_deactivation(session, membership=membership)
    if not membership.is_active or not membership.user.is_active:
        raise InvalidAccountToken()
    # The token lookup above is intentionally lock-free with respect to the
    # membership. Re-read the setup lifecycle after the shared membership ->
    # User fence so a concurrent offboarding cannot be followed by a stale
    # setup completion that resurrects the employee profile.
    session.expire(membership, ["employee_profile", "company"])
    if purpose == AccountSetupTokenPurpose.ACCOUNT_SETUP:
        locked_profile = membership.employee_profile
        if (
            locked_profile is None
            or locked_profile.employment_status != EmployeeEmploymentStatus.INVITED
            or locked_profile.setup_completed_at is not None
        ):
            raise InvalidAccountToken()
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
