from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from caseops_api.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class CompanyType(StrEnum):
    LAW_FIRM = "law_firm"
    CORPORATE_LEGAL = "corporate_legal"


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


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


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
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
    authored_notes: Mapped[list[MatterNote]] = relationship(back_populates="author_membership")
    activity_events: Mapped[list[MatterActivity]] = relationship(back_populates="actor_membership")
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
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="attachments")
    uploaded_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="uploaded_attachments"
    )


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


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
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
