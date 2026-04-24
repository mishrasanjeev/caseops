from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from caseops_api.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class CompanyType(StrEnum):
    LAW_FIRM = "law_firm"
    CORPORATE_LEGAL = "corporate_legal"
    SOLO = "solo"


class MembershipRole(StrEnum):
    # Sprint 8b: three roles added (partner / paralegal / viewer) to
    # let firms map real-world responsibilities without either
    # over-provisioning (everyone is admin) or under-provisioning
    # (everyone is member with no read-only option). Capability mapping
    # lives in api/dependencies.CAPABILITY_ROLES; the frontend mirror
    # is in apps/web/lib/capabilities.ts.
    OWNER = "owner"
    ADMIN = "admin"
    PARTNER = "partner"
    MEMBER = "member"
    PARALEGAL = "paralegal"
    VIEWER = "viewer"


class MatterIntakeStatus(StrEnum):
    # GC intake queue (BG-025). Status machine:
    #   new -> triaging -> in_progress -> (completed | rejected)
    # triaging is the legal team reviewing; in_progress means work is
    # scoped (often as a matter); completed / rejected are terminal.
    NEW = "new"
    TRIAGING = "triaging"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


class MatterIntakePriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class MatterStatus(StrEnum):
    INTAKE = "intake"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CLOSED = "closed"


class MatterForumLevel(StrEnum):
    LOWER_COURT = "lower_court"
    HIGH_COURT = "high_court"
    SUPREME_COURT = "supreme_court"
    TRIBUNAL = "tribunal"
    ARBITRATION = "arbitration"
    ADVISORY = "advisory"


class MatterHearingStatus(StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    ADJOURNED = "adjourned"


class MatterTaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class MatterTaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class MatterCourtSyncStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class MatterCourtSyncJobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"


class PaymentAttemptStatus(StrEnum):
    PENDING = "pending"
    CREATED = "created"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class DocumentProcessingStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    NEEDS_OCR = "needs_ocr"
    FAILED = "failed"


class DocumentProcessingTargetType(StrEnum):
    MATTER_ATTACHMENT = "matter_attachment"
    CONTRACT_ATTACHMENT = "contract_attachment"


class DocumentProcessingAction(StrEnum):
    INITIAL_INDEX = "initial_index"
    RETRY = "retry"
    REINDEX = "reindex"


class DocumentProcessingJobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    NEGOTIATION = "negotiation"
    EXECUTED = "executed"
    EXPIRED = "expired"
    TERMINATED = "terminated"


class ContractClauseRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContractObligationStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WAIVED = "waived"


class ContractObligationPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContractPlaybookSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OutsideCounselPanelStatus(StrEnum):
    ACTIVE = "active"
    PREFERRED = "preferred"
    INACTIVE = "inactive"


class OutsideCounselAssignmentStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    CLOSED = "closed"


class OutsideCounselSpendStatus(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    DISPUTED = "disputed"
    PAID = "paid"


class AuthorityDocumentType(StrEnum):
    JUDGMENT = "judgment"
    ORDER = "order"
    PRACTICE_DIRECTION = "practice_direction"
    NOTICE = "notice"


class AuthorityIngestionStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    company_type: Mapped[str] = mapped_column(String(40), nullable=False)
    tenant_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    primary_contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    billing_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    headquarters: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Calcutta", nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    practice_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # Sprint 8c: when true, matter visibility for non-owners is gated
    # on team membership (plus existing ethical-wall + grant rules).
    # Default false means teams are metadata-only; flipping this on is
    # a deliberate governance decision per-tenant.
    team_scoping_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    memberships: Mapped[list[CompanyMembership]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    matters: Mapped[list[Matter]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    contracts: Mapped[list[Contract]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    outside_counsel_profiles: Mapped[list[OutsideCounsel]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    clients: Mapped[list[Client]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    outside_counsel_assignments: Mapped[list[MatterOutsideCounselAssignment]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    outside_counsel_spend_records: Mapped[list[OutsideCounselSpendRecord]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    court_sync_jobs: Mapped[list[MatterCourtSyncJob]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    document_processing_jobs: Mapped[list[DocumentProcessingJob]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    memberships: Mapped[list[CompanyMembership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class CompanyMembership(Base):
    __tablename__ = "company_memberships"
    __table_args__ = (UniqueConstraint("company_id", "user_id", name="uq_company_membership"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    sessions_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
    assigned_matters: Mapped[list[Matter]] = relationship(
        back_populates="assignee_membership",
        foreign_keys="Matter.assignee_membership_id",
    )
    created_tasks: Mapped[list[MatterTask]] = relationship(
        back_populates="created_by_membership",
        foreign_keys="MatterTask.created_by_membership_id",
    )
    owned_tasks: Mapped[list[MatterTask]] = relationship(
        back_populates="owner_membership",
        foreign_keys="MatterTask.owner_membership_id",
    )
    authored_notes: Mapped[list[MatterNote]] = relationship(back_populates="author_membership")
    activity_events: Mapped[list[MatterActivity]] = relationship(back_populates="actor_membership")
    court_sync_runs: Mapped[list[MatterCourtSyncRun]] = relationship(
        back_populates="triggered_by_membership",
        foreign_keys="MatterCourtSyncRun.triggered_by_membership_id",
    )
    requested_court_sync_jobs: Mapped[list[MatterCourtSyncJob]] = relationship(
        back_populates="requested_by_membership",
        foreign_keys="MatterCourtSyncJob.requested_by_membership_id",
    )
    uploaded_attachments: Mapped[list[MatterAttachment]] = relationship(
        back_populates="uploaded_by_membership"
    )
    logged_time_entries: Mapped[list[MatterTimeEntry]] = relationship(
        back_populates="author_membership"
    )
    issued_invoices: Mapped[list[MatterInvoice]] = relationship(
        back_populates="issued_by_membership"
    )
    initiated_payment_attempts: Mapped[list[MatterInvoicePaymentAttempt]] = relationship(
        back_populates="initiated_by_membership"
    )
    owned_contracts: Mapped[list[Contract]] = relationship(
        back_populates="owner_membership",
        foreign_keys="Contract.owner_membership_id",
    )
    contract_obligations: Mapped[list[ContractObligation]] = relationship(
        back_populates="owner_membership",
        foreign_keys="ContractObligation.owner_membership_id",
    )
    authored_contract_clauses: Mapped[list[ContractClause]] = relationship(
        back_populates="created_by_membership",
        foreign_keys="ContractClause.created_by_membership_id",
    )
    authored_contract_playbook_rules: Mapped[list[ContractPlaybookRule]] = relationship(
        back_populates="created_by_membership",
        foreign_keys="ContractPlaybookRule.created_by_membership_id",
    )
    uploaded_contract_attachments: Mapped[list[ContractAttachment]] = relationship(
        back_populates="uploaded_by_membership",
        foreign_keys="ContractAttachment.uploaded_by_membership_id",
    )
    contract_activity_events: Mapped[list[ContractActivity]] = relationship(
        back_populates="actor_membership",
        foreign_keys="ContractActivity.actor_membership_id",
    )
    requested_document_processing_jobs: Mapped[list[DocumentProcessingJob]] = relationship(
        back_populates="requested_by_membership",
        foreign_keys="DocumentProcessingJob.requested_by_membership_id",
    )
    created_outside_counsel_assignments: Mapped[
        list[MatterOutsideCounselAssignment]
    ] = relationship(
        back_populates="assigned_by_membership",
        foreign_keys="MatterOutsideCounselAssignment.assigned_by_membership_id",
    )
    recorded_outside_counsel_spend_records: Mapped[
        list[OutsideCounselSpendRecord]
    ] = relationship(
        back_populates="recorded_by_membership",
        foreign_keys="OutsideCounselSpendRecord.recorded_by_membership_id",
    )


class Matter(Base):
    __tablename__ = "matters"
    __table_args__ = (UniqueConstraint("company_id", "matter_code", name="uq_company_matter_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignee_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    matter_code: Mapped[str] = mapped_column(String(80), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opposing_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=MatterStatus.INTAKE)
    practice_area: Mapped[str] = mapped_column(String(120), nullable=False)
    forum_level: Mapped[str] = mapped_column(String(40), nullable=False)
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    judge_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_hearing_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # PRD §13.4 / §5.6: when True, only explicit matter_access_grants
    # open the matter; when False (default) every company member with
    # the company-level role can see it. Ethical walls always apply
    # regardless of this flag.
    restricted_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase C-3 (MOD-TS-016): when False (default), an outside-counsel
    # portal user only sees their OWN work-product, time entries, and
    # invoice submissions on this matter. When True, every OC on the
    # matter sees every other OC's submissions. Internal users (firm
    # side) always see everything regardless of this flag.
    oc_cross_visibility_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false(),
    )
    # PRD §7.1: nullable FK to the master Court table. `court_name`
    # stays as the freeform fallback for courts we haven't catalogued
    # yet, so old matters keep working without a data backfill.
    court_id: Mapped[str | None] = mapped_column(
        ForeignKey("courts.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Sprint 8c: optional team ownership. When the tenant has
    # team_scoping_enabled=True, visibility for non-owners is gated on
    # team membership. Null means firm-wide (visible to every member
    # with matter access); always null on legacy rows.
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # EG-005 (2026-04-23) — cached executive summary so every GET /
    # DOCX / PDF on the summary endpoint stops costing a Haiku call.
    # ``executive_summary_json`` holds the serialised
    # MatterExecutiveSummary; ``generated_at`` lets the cache decide
    # if a stale entry is still acceptable; ``model_run_id`` ties the
    # cache row back to the LLM call that produced it for audit.
    executive_summary_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    executive_summary_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    executive_summary_model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="matters")
    assignee_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="assigned_matters",
        foreign_keys=[assignee_membership_id],
    )
    tasks: Mapped[list[MatterTask]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
    )
    notes: Mapped[list[MatterNote]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
    )
    hearings: Mapped[list[MatterHearing]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
    )
    activity_events: Mapped[list[MatterActivity]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterActivity.created_at)",
    )
    cause_list_entries: Mapped[list[MatterCauseListEntry]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterCauseListEntry.listing_date), desc(MatterCauseListEntry.created_at)",
    )
    court_orders: Mapped[list[MatterCourtOrder]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterCourtOrder.order_date), desc(MatterCourtOrder.created_at)",
    )
    court_sync_runs: Mapped[list[MatterCourtSyncRun]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterCourtSyncRun.started_at)",
    )
    court_sync_jobs: Mapped[list[MatterCourtSyncJob]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterCourtSyncJob.queued_at)",
    )
    attachments: Mapped[list[MatterAttachment]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterAttachment.created_at)",
    )
    time_entries: Mapped[list[MatterTimeEntry]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterTimeEntry.work_date), desc(MatterTimeEntry.created_at)",
    )
    invoices: Mapped[list[MatterInvoice]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterInvoice.created_at)",
    )
    linked_contracts: Mapped[list[Contract]] = relationship(
        back_populates="linked_matter",
    )
    client_assignments: Mapped[list[MatterClientAssignment]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
    )
    outside_counsel_assignments: Mapped[list[MatterOutsideCounselAssignment]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterOutsideCounselAssignment.updated_at)",
    )
    outside_counsel_spend_records: Mapped[list[OutsideCounselSpendRecord]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(OutsideCounselSpendRecord.updated_at)",
    )


class MatterNote(Base):
    __tablename__ = "matter_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="notes")
    author_membership: Mapped[CompanyMembership] = relationship(back_populates="authored_notes")


class MatterTask(Base):
    __tablename__ = "matter_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterTaskStatus.TODO,
    )
    priority: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterTaskPriority.MEDIUM,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="tasks")
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="created_tasks",
        foreign_keys=[created_by_membership_id],
    )
    owner_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="owned_tasks",
        foreign_keys=[owner_membership_id],
    )


class MatterHearing(Base):
    __tablename__ = "matter_hearings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hearing_on: Mapped[date] = mapped_column(Date, nullable=False)
    forum_name: Mapped[str] = mapped_column(String(255), nullable=False)
    judge_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterHearingStatus.SCHEDULED,
    )
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="hearings")
    reminders: Mapped[list[HearingReminder]] = relationship(
        back_populates="hearing",
        cascade="all, delete-orphan",
        order_by="HearingReminder.scheduled_for",
    )


class HearingReminderChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    IN_APP = "in_app"


class HearingReminderStatus(StrEnum):
    # Persisted at hearing-create time, waiting for ``scheduled_for``
    # to fall inside the worker's "due now" window.
    QUEUED = "queued"
    # Worker picked it up, handed off to the provider, provider returned
    # a message-id (message delivered to provider, not yet delivered to
    # recipient).
    SENT = "sent"
    # Provider confirmed delivery (via webhook) to the recipient.
    DELIVERED = "delivered"
    # Provider reported a permanent failure; won't retry.
    FAILED = "failed"
    # Operator cancelled before send (hearing moved / cancelled).
    CANCELLED = "cancelled"


class HearingReminder(Base):
    """Durable record of one reminder we intend to send for a hearing.

    Rows are created by ``services.hearing_reminders.schedule_reminders``
    when a ``MatterHearing`` is inserted or rescheduled. A worker
    (``caseops-send-hearing-reminders``) polls for ``QUEUED`` rows
    whose ``scheduled_for`` has passed and dispatches them via the
    configured channel.

    Persisting the intent separately from the delivery lets us
    dark-launch the feature: rows accumulate in production even when
    the provider isn't configured, so flipping the feature flag on
    starts delivering immediately without a backfill. See
    ``memory/feedback_fix_vs_mitigation.md`` for why this is the
    shape we want — reminders the user CAN'T yet receive are still
    reminders the system intends to send.
    """
    __tablename__ = "hearing_reminders"
    __table_args__ = (
        UniqueConstraint(
            "hearing_id", "channel", "scheduled_for",
            name="uq_hearing_reminders_channel_time",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hearing_id: Mapped[str] = mapped_column(
        ForeignKey("matter_hearings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    channel: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=HearingReminderChannel.EMAIL,
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=HearingReminderStatus.QUEUED,
        index=True,
    )
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    hearing: Mapped[MatterHearing] = relationship(back_populates="reminders")


class MatterActivity(Base):
    __tablename__ = "matter_activity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="activity_events")
    actor_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="activity_events",
    )


class MatterCauseListEntry(Base):
    __tablename__ = "matter_cause_list_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_court_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    listing_date: Mapped[date] = mapped_column(Date, nullable=False)
    forum_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bench_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    courtroom: Mapped[str | None] = mapped_column(String(120), nullable=True)
    item_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="cause_list_entries")
    sync_run: Mapped[MatterCourtSyncRun | None] = relationship(
        back_populates="cause_list_entries"
    )


class MatterCourtOrder(Base):
    __tablename__ = "matter_court_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_court_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    order_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="court_orders")
    sync_run: Mapped[MatterCourtSyncRun | None] = relationship(back_populates="court_orders")


class MatterCourtSyncRun(Base):
    __tablename__ = "matter_court_sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggered_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterCourtSyncStatus.COMPLETED,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_cause_list_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="court_sync_runs")
    triggered_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="court_sync_runs",
        foreign_keys=[triggered_by_membership_id],
    )
    cause_list_entries: Mapped[list[MatterCauseListEntry]] = relationship(
        back_populates="sync_run",
    )
    court_orders: Mapped[list[MatterCourtOrder]] = relationship(back_populates="sync_run")
    jobs: Mapped[list[MatterCourtSyncJob]] = relationship(back_populates="sync_run")


class MatterCourtSyncJob(Base):
    __tablename__ = "matter_court_sync_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_court_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    adapter_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterCourtSyncJobStatus.QUEUED,
    )
    imported_cause_list_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="court_sync_jobs")
    matter: Mapped[Matter] = relationship(back_populates="court_sync_jobs")
    requested_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="requested_court_sync_jobs",
        foreign_keys=[requested_by_membership_id],
    )
    sync_run: Mapped[MatterCourtSyncRun | None] = relationship(back_populates="jobs")


class MatterAttachment(Base):
    __tablename__ = "matter_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitted_by_portal_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DocumentProcessingStatus.PENDING,
    )
    extracted_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="attachments")
    uploaded_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="uploaded_attachments"
    )
    chunks: Mapped[list[MatterAttachmentChunk]] = relationship(
        back_populates="attachment",
        cascade="all, delete-orphan",
        order_by="MatterAttachmentChunk.chunk_index.asc()",
    )


class MatterAttachmentChunk(Base):
    __tablename__ = "matter_attachment_chunks"
    __table_args__ = (
        UniqueConstraint("attachment_id", "chunk_index", name="uq_matter_attachment_chunk_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    attachment: Mapped[MatterAttachment] = relationship(back_populates="chunks")


class MatterTimeEntry(Base):
    __tablename__ = "matter_time_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitted_by_portal_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    billable: Mapped[bool] = mapped_column(default=True, nullable=False)
    rate_currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    rate_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="time_entries")
    author_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="logged_time_entries"
    )
    invoice_line_item: Mapped[MatterInvoiceLineItem | None] = relationship(
        back_populates="time_entry"
    )


class MatterInvoice(Base):
    __tablename__ = "matter_invoices"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "invoice_number",
            name="uq_company_invoice_number",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issued_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitted_by_portal_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=InvoiceStatus.DRAFT)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    subtotal_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_received_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance_due_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pine_labs_payment_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    pine_labs_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="invoices")
    issued_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="issued_invoices"
    )
    line_items: Mapped[list[MatterInvoiceLineItem]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="MatterInvoiceLineItem.created_at.asc()",
    )
    payment_attempts: Mapped[list[MatterInvoicePaymentAttempt]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="desc(MatterInvoicePaymentAttempt.created_at)",
    )


class MatterInvoiceLineItem(Base):
    __tablename__ = "matter_invoice_line_items"
    __table_args__ = (UniqueConstraint("time_entry_id", name="uq_invoice_line_item_time_entry"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("matter_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    time_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_time_entries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_rate_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_total_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    invoice: Mapped[MatterInvoice] = relationship(back_populates="line_items")
    time_entry: Mapped[MatterTimeEntry | None] = relationship(back_populates="invoice_line_item")


class MatterInvoicePaymentAttempt(Base):
    __tablename__ = "matter_invoice_payment_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("matter_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    initiated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="pine_labs")
    merchant_order_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=PaymentAttemptStatus.PENDING,
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_received_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payment_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    invoice: Mapped[MatterInvoice] = relationship(back_populates="payment_attempts")
    initiated_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="initiated_payment_attempts"
    )


class ClientType(StrEnum):
    INDIVIDUAL = "individual"
    CORPORATE = "corporate"
    GOVERNMENT = "government"
    NONPROFIT = "nonprofit"


class ClientKycStatus(StrEnum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class Client(Base):
    """A law-firm client (MOD-TS-009). Tenant-scoped by ``company_id``.

    The legacy ``Matter.client_name`` free-text column is kept in
    place for back-compat; new matters should link via
    :class:`MatterClientAssignment` instead. Neither is authoritative
    by itself — the cockpit renders the linked client if present,
    falling back to the free-text name.
    """
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "name", "client_type",
            name="uq_clients_tenant_name_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_type: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=ClientType.INDIVIDUAL,
    )
    primary_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    primary_contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Strict Ledger #4 (BUG-022, 2026-04-22): full street address.
    # Hari's bug said "address" — the original schema only had
    # city/state/country, so a typed door-no + street was silently
    # discarded. Optional + nullable to preserve back-compat.
    address_line_1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True, default="India")
    pan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    kyc_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=ClientKycStatus.NOT_STARTED,
    )
    # Phase B M11 slice 3 — KYC audit trail. Without these the
    # status badge has no provenance: under a compliance audit the
    # workspace owner needs to point at WHO verified the client and
    # WHEN. Documents stored as JSON so a later "secure storage URL
    # per doc" extension does not need another migration.
    kyc_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    kyc_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    kyc_verified_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    kyc_rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    kyc_documents_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="clients")
    assignments: Mapped[list[MatterClientAssignment]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
    )


class MatterClientAssignment(Base):
    """Link between a matter and a client. Most matters link to
    exactly one client, but corporate-defence / multi-party cases can
    link N clients — hence a full N-N association rather than a
    direct FK on ``Matter``. Role captures whether the client is the
    plaintiff / respondent / etc. on that matter."""
    __tablename__ = "matter_client_assignments"
    __table_args__ = (
        UniqueConstraint(
            "matter_id", "client_id",
            name="uq_matter_client_assignment",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="client_assignments")
    client: Mapped[Client] = relationship(back_populates="assignments")


class OutsideCounsel(Base):
    __tablename__ = "outside_counsel"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_outside_counsel_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    primary_contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    firm_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jurisdictions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    practice_areas_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    panel_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=OutsideCounselPanelStatus.ACTIVE,
    )
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="outside_counsel_profiles")
    assignments: Mapped[list[MatterOutsideCounselAssignment]] = relationship(
        back_populates="counsel",
        cascade="all, delete-orphan",
        order_by="desc(MatterOutsideCounselAssignment.updated_at)",
    )
    spend_records: Mapped[list[OutsideCounselSpendRecord]] = relationship(
        back_populates="counsel",
        cascade="all, delete-orphan",
        order_by="desc(OutsideCounselSpendRecord.updated_at)",
    )


class MatterOutsideCounselAssignment(Base):
    __tablename__ = "matter_outside_counsel_assignments"
    __table_args__ = (
        UniqueConstraint(
            "matter_id",
            "counsel_id",
            name="uq_matter_outside_counsel_assignment",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    counsel_id: Mapped[str] = mapped_column(
        ForeignKey("outside_counsel.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    role_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    budget_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=OutsideCounselAssignmentStatus.APPROVED,
    )
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="outside_counsel_assignments")
    matter: Mapped[Matter] = relationship(back_populates="outside_counsel_assignments")
    counsel: Mapped[OutsideCounsel] = relationship(back_populates="assignments")
    assigned_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="created_outside_counsel_assignments",
        foreign_keys=[assigned_by_membership_id],
    )
    spend_records: Mapped[list[OutsideCounselSpendRecord]] = relationship(
        back_populates="assignment"
    )


class OutsideCounselSpendRecord(Base):
    __tablename__ = "outside_counsel_spend_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    counsel_id: Mapped[str] = mapped_column(
        ForeignKey("outside_counsel.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_outside_counsel_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recorded_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoice_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stage_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=OutsideCounselSpendStatus.SUBMITTED,
    )
    billed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="outside_counsel_spend_records")
    matter: Mapped[Matter] = relationship(back_populates="outside_counsel_spend_records")
    counsel: Mapped[OutsideCounsel] = relationship(back_populates="spend_records")
    assignment: Mapped[MatterOutsideCounselAssignment | None] = relationship(
        back_populates="spend_records"
    )
    recorded_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="recorded_outside_counsel_spend_records",
        foreign_keys=[recorded_by_membership_id],
    )


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("company_id", "contract_code", name="uq_company_contract_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    linked_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    contract_code: Mapped[str] = mapped_column(String(80), nullable=False)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=ContractStatus.DRAFT)
    jurisdiction: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    renewal_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    auto_renewal: Mapped[bool] = mapped_column(default=False, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    total_value_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="contracts")
    linked_matter: Mapped[Matter | None] = relationship(back_populates="linked_contracts")
    owner_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="owned_contracts",
        foreign_keys=[owner_membership_id],
    )
    clauses: Mapped[list[ContractClause]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="desc(ContractClause.created_at)",
    )
    obligations: Mapped[list[ContractObligation]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="ContractObligation.due_on.asc(), ContractObligation.created_at.asc()",
    )
    playbook_rules: Mapped[list[ContractPlaybookRule]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="desc(ContractPlaybookRule.created_at)",
    )
    attachments: Mapped[list[ContractAttachment]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="desc(ContractAttachment.created_at)",
    )
    activity_events: Mapped[list[ContractActivity]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="desc(ContractActivity.created_at)",
    )


class ContractClause(Base):
    __tablename__ = "contract_clauses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    clause_type: Mapped[str] = mapped_column(String(120), nullable=False)
    clause_text: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContractClauseRiskLevel.MEDIUM,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    contract: Mapped[Contract] = relationship(back_populates="clauses")
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="authored_contract_clauses",
        foreign_keys=[created_by_membership_id],
    )


class ContractObligation(Base):
    __tablename__ = "contract_obligations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=ContractObligationStatus.PENDING,
    )
    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContractObligationPriority.MEDIUM,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    contract: Mapped[Contract] = relationship(back_populates="obligations")
    owner_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="contract_obligations",
        foreign_keys=[owner_membership_id],
    )


class ContractPlaybookRule(Base):
    __tablename__ = "contract_playbook_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    clause_type: Mapped[str] = mapped_column(String(120), nullable=False)
    expected_position: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContractPlaybookSeverity.MEDIUM,
    )
    keyword_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fallback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    contract: Mapped[Contract] = relationship(back_populates="playbook_rules")
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="authored_contract_playbook_rules",
        foreign_keys=[created_by_membership_id],
    )


class ContractActivity(Base):
    __tablename__ = "contract_activity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    contract: Mapped[Contract] = relationship(back_populates="activity_events")
    actor_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="contract_activity_events",
        foreign_keys=[actor_membership_id],
    )


class ContractAttachment(Base):
    __tablename__ = "contract_attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DocumentProcessingStatus.PENDING,
    )
    extracted_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    contract: Mapped[Contract] = relationship(back_populates="attachments")
    uploaded_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="uploaded_contract_attachments",
        foreign_keys=[uploaded_by_membership_id],
    )
    chunks: Mapped[list[ContractAttachmentChunk]] = relationship(
        back_populates="attachment",
        cascade="all, delete-orphan",
        order_by="ContractAttachmentChunk.chunk_index.asc()",
    )


class ContractAttachmentChunk(Base):
    __tablename__ = "contract_attachment_chunks"
    __table_args__ = (
        UniqueConstraint(
            "attachment_id",
            "chunk_index",
            name="uq_contract_attachment_chunk_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("contract_attachments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    attachment: Mapped[ContractAttachment] = relationship(back_populates="chunks")


class DocumentProcessingJob(Base):
    __tablename__ = "document_processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    attachment_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DocumentProcessingJobStatus.QUEUED,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(back_populates="document_processing_jobs")
    requested_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="requested_document_processing_jobs",
        foreign_keys=[requested_by_membership_id],
    )


class AuthorityDocument(Base):
    __tablename__ = "authority_documents"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_authority_document_canonical_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    adapter_name: Mapped[str] = mapped_column(String(120), nullable=False)
    court_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    forum_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    case_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    bench_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    neutral_citation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Nullable as of the corpus-quality fix: when the PDF text has no
    # parseable date we store NULL rather than synthesising Jan 1 of
    # the S3-prefix year (which produced 73% fake dates before).
    decision_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, index=True
    )
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    document_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Layer 2 structured extraction — JSON blobs populated by the
    # Haiku structured-extraction pass. ``structured_version`` tracks
    # which pipeline revision produced the payload so a future prompt
    # tweak can be rolled out without re-extracting everything.
    case_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    judges_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    parties_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    advocates_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sections_cited_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    structured_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    chunks: Mapped[list[AuthorityDocumentChunk]] = relationship(
        back_populates="authority_document",
        cascade="all, delete-orphan",
        order_by="AuthorityDocumentChunk.chunk_index.asc()",
    )
    outgoing_citations: Mapped[list[AuthorityCitation]] = relationship(
        "AuthorityCitation",
        back_populates="source_authority_document",
        cascade="all, delete-orphan",
        foreign_keys="AuthorityCitation.source_authority_document_id",
        order_by="AuthorityCitation.created_at.asc()",
    )
    incoming_citations: Mapped[list[AuthorityCitation]] = relationship(
        "AuthorityCitation",
        back_populates="cited_authority_document",
        foreign_keys="AuthorityCitation.cited_authority_document_id",
    )


class AuthorityDocumentChunk(Base):
    __tablename__ = "authority_document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "authority_document_id",
            "chunk_index",
            name="uq_authority_document_chunk_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    authority_document_id: Mapped[str] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Embedding is stored per-chunk. On Postgres this column is migrated to
    # pgvector's `vector(N)` type and queried with cosine distance; on
    # SQLite (tests only) it stays as a JSON-encoded array so retrieval
    # code has a uniform shape.
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Layer 2 structured extraction — typed chunks.
    #   chunk_role ∈ {metadata, facts, arguments, reasoning, directions,
    #                  ratio, obiter, procedural, other}.
    #   sections_cited_json / authorities_cited_json are JSON-encoded
    #   lists; kept as TEXT for portability across SQLite (tests) and
    #   Postgres (prod). related_chunk_ids_json is a JSON array of
    #   sibling chunk_index ints that are topically linked.
    chunk_role: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    sections_cited_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorities_cited_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_tag: Mapped[str | None] = mapped_column(String(120), nullable=True)
    related_chunk_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    authority_document: Mapped[AuthorityDocument] = relationship(back_populates="chunks")


class AuthorityCitation(Base):
    __tablename__ = "authority_citations"
    __table_args__ = (
        UniqueConstraint(
            "source_authority_document_id",
            "normalized_reference",
            name="uq_authority_citation_reference",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_authority_document_id: Mapped[str] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cited_authority_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    citation_text: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_reference: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    source_authority_document: Mapped[AuthorityDocument] = relationship(
        back_populates="outgoing_citations",
        foreign_keys=[source_authority_document_id],
    )
    cited_authority_document: Mapped[AuthorityDocument | None] = relationship(
        back_populates="incoming_citations",
        foreign_keys=[cited_authority_document_id],
    )


class AuthorityIngestionRun(Base):
    __tablename__ = "authority_ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requested_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    adapter_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=AuthorityIngestionStatus.COMPLETED,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    requested_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[requested_by_membership_id]
    )


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_event_id", name="uq_payment_webhook_event_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    event_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(24), nullable=False, default="received")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class ModelRun(Base):
    """Auditable record of every LLM / embedding call made on behalf of a tenant."""

    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Widened to 64 because status labels like
    # "rejected_no_verified_citations" don't fit in 24. Kept as
    # VARCHAR rather than an enum because the taxonomy is still
    # evolving and enum migrations on Postgres are painful.
    status: Mapped[str] = mapped_column(String(64), default="ok", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class Recommendation(Base):
    """Explainable decision-support output for a matter (PRD §11, §23.1)."""

    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    primary_option_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    missing_facts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    review_required: Mapped[bool] = mapped_column(default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    options: Mapped[list[RecommendationOption]] = relationship(
        back_populates="recommendation",
        cascade="all, delete-orphan",
        order_by="RecommendationOption.rank",
    )
    decisions: Mapped[list[RecommendationDecision]] = relationship(
        back_populates="recommendation",
        cascade="all, delete-orphan",
        order_by="RecommendationDecision.created_at",
    )


class RecommendationOption(Base):
    __tablename__ = "recommendation_options"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(String(400), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    supporting_citations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    recommendation: Mapped[Recommendation] = relationship(back_populates="options")


class RecommendationDecision(Base):
    __tablename__ = "recommendation_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)  # accepted|rejected|edited
    selected_option_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    recommendation: Mapped[Recommendation] = relationship(back_populates="decisions")


class HearingPackStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"


class HearingPackItemKind(StrEnum):
    CHRONOLOGY = "chronology"
    LAST_ORDER = "last_order"
    PENDING_COMPLIANCE = "pending_compliance"
    ISSUE = "issue"
    OPPOSITION_POINT = "opposition_point"
    AUTHORITY_CARD = "authority_card"
    ORAL_POINT = "oral_point"


class HearingPack(Base):
    """Assembled hearing brief. Always tenant-scoped via matter_id and
    always review_required until a partner reviews it (PRD §17.4)."""

    __tablename__ = "hearing_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hearing_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_hearings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=HearingPackStatus.DRAFT)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[HearingPackItem]] = relationship(
        back_populates="pack",
        cascade="all, delete-orphan",
        order_by="HearingPackItem.rank",
    )


class HearingPackItem(Base):
    __tablename__ = "hearing_pack_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    pack_id: Mapped[str] = mapped_column(
        ForeignKey("hearing_packs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    pack: Mapped[HearingPack] = relationship(back_populates="items")


class DraftStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    FINALIZED = "finalized"


class DraftType(StrEnum):
    BRIEF = "brief"
    NOTICE = "notice"
    REPLY = "reply"
    MEMO = "memo"
    OTHER = "other"


class DraftReviewAction(StrEnum):
    SUBMIT = "submit"
    REQUEST_CHANGES = "request_changes"
    APPROVE = "approve"
    FINALIZE = "finalize"


class Draft(Base):
    """A long-lived legal document draft. The matter is the tenant
    boundary; versions roll forward; status advances through a strict
    state machine enforced by the service layer."""

    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    draft_type: Mapped[str] = mapped_column(String(40), nullable=False, default=DraftType.BRIEF)
    template_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=DraftStatus.DRAFT)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Stepper-collected facts keyed by field name, persisted as JSON
    # text so the generator can ground the body on structured facts
    # instead of a free-form focus note. Optional — drafts created
    # without the stepper stay at NULL.
    facts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    versions: Mapped[list[DraftVersion]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="DraftVersion.revision",
    )
    reviews: Mapped[list[DraftReview]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="DraftReview.created_at",
    )


class DraftVersion(Base):
    __tablename__ = "draft_versions"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision", name="uq_draft_versions_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Stored as JSON text on both Postgres and SQLite so the model
    # doesn't diverge between test and prod engines.
    citations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    verified_citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    draft: Mapped[Draft] = relationship(back_populates="versions")


class DraftReview(Base):
    __tablename__ = "draft_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("draft_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    draft: Mapped[Draft] = relationship(back_populates="reviews")


class AuditActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SERVICE = "service"
    SYSTEM = "system"


class AuditResult(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


class AuditEvent(Base):
    """Append-only tenant audit trail (PRD §15.4, §17.2).

    The application NEVER updates or deletes rows in this table. Cloud SQL
    / Postgres can add a role-level restriction on top, but at the code
    level the invariant holds via discipline: only `services/audit.py`
    writes here, and it only INSERTs.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    result: Mapped[str] = mapped_column(String(24), nullable=False, default=AuditResult.SUCCESS)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class MatterAccessLevel(StrEnum):
    # Single-level v1: if the grant exists, the membership gets full
    # access to the matter. Finer gradation (read-only, billing-only,
    # etc.) can land behind this enum without a migration.
    MEMBER = "member"


class MatterAccessGrant(Base):
    """Explicit per-user grant on a matter. Only consulted when the
    matter has `restricted_access=True`; otherwise company role rules
    the decision."""

    __tablename__ = "matter_access_grants"
    __table_args__ = (
        UniqueConstraint(
            "matter_id", "membership_id", name="uq_matter_access_grants_matter_membership"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    access_level: Mapped[str] = mapped_column(
        String(24), nullable=False, default=MatterAccessLevel.MEMBER
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    granted_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class EthicalWall(Base):
    """Exclusion list. An `excluded_membership_id` row blocks that
    membership from accessing the matter even if they have a grant
    or (in unrestricted mode) would see it by default.

    The matter's own assignee and company owners bypass walls in the
    enforcement helper — a firm shouldn't accidentally lock its own
    partners out of a matter they own."""

    __tablename__ = "ethical_walls"
    __table_args__ = (
        UniqueConstraint(
            "matter_id", "excluded_membership_id", name="uq_ethical_walls_matter_excluded"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    excluded_membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class Court(Base):
    """Master record for a court. FK target for `Matter.court_id`. The
    freeform `Matter.court_name` column stays as a fallback for courts
    we haven't catalogued — migrations do not backfill `court_id`, so
    old rows keep working."""

    __tablename__ = "courts"
    __table_args__ = (UniqueConstraint("name", name="uq_courts_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str] = mapped_column(String(80), nullable=False)
    forum_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(120), nullable=True)
    seat_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The key used by the corpus ingester's HC_COURT_CATALOG, so we
    # can join court rows to S3-partitioned authorities.
    hc_catalog_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class Bench(Base):
    __tablename__ = "benches"
    __table_args__ = (UniqueConstraint("court_id", "name", name="uq_benches_court_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    court_id: Mapped[str] = mapped_column(
        ForeignKey("courts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    seat_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class Judge(Base):
    """Judge master record. PRD §10.6 is adamant that we do NOT build
    favorability scoring on top of this — use it for profile pages,
    citation trends, cause-list dedup, and recommendation context only."""

    __tablename__ = "judges"
    __table_args__ = (UniqueConstraint("court_id", "full_name", name="uq_judges_court_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    court_id: Mapped[str] = mapped_column(
        ForeignKey("courts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    honorific: Mapped[str | None] = mapped_column(String(80), nullable=True)
    current_position: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class EvaluationRun(Base):
    """One invocation of a named evaluation suite against one model
    configuration. Aggregate counts land here; per-case detail lives
    in ``evaluation_cases``."""

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    suite_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    git_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    cases: Mapped[list[EvaluationCase]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="EvaluationCase.created_at.asc()",
    )


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (
        UniqueConstraint("run_id", "case_key", name="uq_eval_case_key_per_run"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    blocker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    run: Mapped[EvaluationRun] = relationship(back_populates="cases")


class AuditExportJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AuditExportJob(Base):
    """Background job row for async audit exports (§10.4).

    The sync streaming endpoint still ships small exports inline. For
    large tenants — millions of rows — the client POSTs to
    ``/api/admin/audit/export/async`` which enqueues a job; a worker
    writes the artifact to storage; the client polls ``jobs/{id}``
    and downloads once ``status == completed``.
    """

    __tablename__ = "audit_export_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=AuditExportJobStatus.PENDING
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="jsonl")
    since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    action_filter: Mapped[str | None] = mapped_column(String(120), nullable=True)
    row_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuthorityAnnotationKind(StrEnum):
    NOTE = "note"
    FLAG = "flag"
    TAG = "tag"


class AuthorityAnnotation(Base):
    """Per-tenant overlay on a shared ``AuthorityDocument``.

    The authority corpus itself is global (public law). Each firm can
    attach their own notes, flags, and tags without mutating the
    shared record. Every query MUST filter on ``company_id`` — the
    service layer enforces this.
    """

    __tablename__ = "authority_annotations"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "authority_document_id",
            "kind",
            "title",
            name="uq_authority_annotation_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    authority_document_id: Mapped[str] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class MatterAttachmentAnnotationKind(StrEnum):
    """Annotation on an uploaded matter document. Scoped to the
    matter, not to the shared authority corpus — ``AuthorityAnnotation``
    exists separately for per-tenant overlays on the public-law index.
    """

    HIGHLIGHT = "highlight"
    NOTE = "note"
    FLAG = "flag"


class MatterAttachmentAnnotation(Base):
    """Sprint Q10 — per-matter annotations on an uploaded attachment.

    Rendered as an overlay by the PDF viewer at
    ``/app/matters/{id}/documents/{attachment_id}/view``. Scoped to
    the owning matter's company_id; callers MUST filter by
    company_id + matter_id before writing / reading.

    ``page`` is 1-based. ``bbox`` is stored as a JSON array
    ``[x0, y0, x1, y1]`` in pdfjs text-layer coordinates (pre-zoom);
    the viewer scales at render time. Nullable when the annotation
    is "about the page" rather than a specific rectangle (plain
    page-level note).
    """

    __tablename__ = "matter_attachment_annotations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_attachment_id: Mapped[str] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterAttachmentAnnotationKind.HIGHLIGHT,
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    quoted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(24), nullable=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class MatterDeadlineStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"
    MISSED = "missed"


class MatterDeadline(Base):
    """Generic deadline on a matter (Sprint 13 partial / BG-041).

    Hearings, drafts, contracts, intake, and post-hearing follow-ups
    all write to this single table so "what is due this week for
    tenant X" is one query, not four joined ones.
    """

    __tablename__ = "matter_deadlines"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=MatterDeadlineStatus.OPEN
    )
    assignee_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TenantAIPolicy(Base):
    """Per-tenant AI policy (Sprint 15 partial / BG-046 schema).

    One row per company; the LLM provider factory reads
    ``allowed_models_*`` to refuse a request that violates the policy
    before any call is billed. Enforcement of token_budget and
    external_share_requires_approval will wire into the drafting +
    export pipelines in a follow-on.
    """

    __tablename__ = "tenant_ai_policies"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_tenant_ai_policy_company"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    allowed_models_drafting_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    allowed_models_recommendations_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    allowed_models_hearing_pack_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    max_tokens_per_session: Mapped[int] = mapped_column(
        Integer, nullable=False, default=16384
    )
    monthly_token_budget: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    external_share_requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    training_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


# ---------------------------------------------------------------------------
# Sprint 8b BG-025: GC intake queue
# Inbound legal requests from business units, tracked before they become
# matters. Lives in its own table so the intake→matter lifecycle stays
# explicit; promote_intake_to_matter() creates a Matter and links back.
# ---------------------------------------------------------------------------


class MatterIntakeRequest(Base):
    __tablename__ = "matter_intake_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submitted_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_to_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    linked_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MatterIntakePriority.MEDIUM
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=MatterIntakeStatus.NEW, index=True
    )

    requester_name: Mapped[str] = mapped_column(String(255), nullable=False)
    requester_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    business_unit: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    desired_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    triage_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    company: Mapped[Company] = relationship()
    submitted_by: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[submitted_by_membership_id]
    )
    assigned_to: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[assigned_to_membership_id]
    )
    linked_matter: Mapped[Matter | None] = relationship(
        foreign_keys=[linked_matter_id]
    )


# ---------------------------------------------------------------------------
# Sprint 8c BG-026: teams / departments / practice areas
# A "team" is just a named group of memberships inside one company. The
# `kind` field lets firms label a group as "team", "department", or
# "practice_area" for UI purposes; the model treats all three the same.
# ---------------------------------------------------------------------------


class TeamKind(StrEnum):
    TEAM = "team"
    DEPARTMENT = "department"
    PRACTICE_AREA = "practice_area"


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("company_id", "slug", name="uq_team_company_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default=TeamKind.TEAM
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    memberships: Mapped[list[TeamMembership]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
    )


class TeamMembership(Base):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint(
            "team_id", "membership_id", name="uq_team_membership"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_lead: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    team: Mapped[Team] = relationship(back_populates="memberships")
    membership: Mapped[CompanyMembership] = relationship()


# ---------------------------------------------------------------
# Phase B / J12 / M11 — communications log
# ---------------------------------------------------------------


class CommunicationDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class CommunicationChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PHONE = "phone"
    MEETING = "meeting"
    NOTE = "note"


class CommunicationStatus(StrEnum):
    """Lifecycle covers both the manual-log path (slice 1, terminal
    at LOGGED) and the future SendGrid pipeline (slice 2: queued →
    sent → delivered / opened / bounced / failed)."""

    LOGGED = "logged"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    BOUNCED = "bounced"
    FAILED = "failed"


class Communication(Base):
    """One row per recorded communication event with a client or
    matter contact. Slice 1 supports manual logging via the
    matter cockpit's Communications tab; slice 2 will add the
    SendGrid send + template + delivery webhook on the same row."""

    __tablename__ = "communications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    direction: Mapped[str] = mapped_column(
        String(12), nullable=False, default=CommunicationDirection.OUTBOUND,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(400), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=CommunicationStatus.LOGGED,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    external_message_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False,
    )


# ---------------------------------------------------------------
# Phase B M11 slice 2 — AutoMail email templates
# ---------------------------------------------------------------


class EmailTemplate(Base):
    """Per-tenant email template catalogue.

    The Compose & send action on the matter Communications tab picks
    a template here, fills its declared variables, renders subject +
    body via simple ``{{var}}`` substitution, and dispatches via
    SendGrid. The resulting communications row carries
    ``external_message_id`` so the SendGrid event webhook can update
    its ``status`` from QUEUED → SENT → DELIVERED / OPENED / BOUNCED.
    """

    __tablename__ = "email_templates"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    subject_template: Mapped[str] = mapped_column(String(400), nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "company_id", "name",
            name="uq_email_templates_company_name",
        ),
    )


# ---------------------------------------------------------------
# MOD-TS-014 — Portal persona model (Phase C-1, 2026-04-24)
# ---------------------------------------------------------------


class PortalUserRole(StrEnum):
    CLIENT = "client"
    OUTSIDE_COUNSEL = "outside_counsel"


class PortalUser(Base):
    """A non-Membership identity scoped to one tenant.

    Distinct from ``CompanyMembership``: portal users never inherit a
    role-based capability and never get a /app session. Their access is
    gated entirely through ``MatterPortalGrant`` rows.
    """

    __tablename__ = "portal_users"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "email", name="uq_portal_user_company_email",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    sessions_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    invited_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    last_signed_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    company: Mapped[Company] = relationship()
    magic_links: Mapped[list[PortalMagicLink]] = relationship(
        back_populates="portal_user", cascade="all, delete-orphan",
    )
    grants: Mapped[list[MatterPortalGrant]] = relationship(
        back_populates="portal_user", cascade="all, delete-orphan",
    )


class PortalMagicLink(Base):
    """One-shot, hash-only magic-link token bound to a PortalUser.

    The plaintext token is returned to the caller exactly once (when
    the link is generated for AutoMail dispatch); only the SHA-256
    hash lives in the DB so a hot dump cannot replay sessions.
    """

    __tablename__ = "portal_magic_links"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    portal_user_id: Mapped[str] = mapped_column(
        ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    requested_ip: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )
    requested_user_agent: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )

    portal_user: Mapped[PortalUser] = relationship(back_populates="magic_links")


class MatterPortalGrant(Base):
    """Explicit per-matter scope for a PortalUser.

    Without a live (non-revoked) grant for a given matter, the
    PortalUser sees nothing on it — even if the matter belongs to the
    PortalUser's company. The role on the grant must match the parent
    PortalUser's role; service code enforces this.
    """

    __tablename__ = "matter_portal_grants"
    __table_args__ = (
        UniqueConstraint(
            "portal_user_id", "matter_id",
            name="uq_matter_portal_grant_user_matter",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    portal_user_id: Mapped[str] = mapped_column(
        ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    granted_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    portal_user: Mapped[PortalUser] = relationship(back_populates="grants")
