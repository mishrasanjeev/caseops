from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    false,
    text,
    true,
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
    # lives in services/capability_catalog.CAPABILITY_ROLES; the frontend mirror
    # is in apps/web/lib/capabilities.ts.
    OWNER = "owner"
    ADMIN = "admin"
    PARTNER = "partner"
    MEMBER = "member"
    PARALEGAL = "paralegal"
    VIEWER = "viewer"


class EmployeeEmploymentStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    INACTIVE = "inactive"
    OFFBOARDING = "offboarding"


class AccountSetupTokenPurpose(StrEnum):
    ACCOUNT_SETUP = "account_setup"
    PASSWORD_RESET = "password_reset"


class EmployeeImportJobStatus(StrEnum):
    PREVIEWED = "previewed"
    COMMITTING = "committing"
    COMMITTED = "committed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class EmployeeImportRowStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    CREATED = "created"
    FAILED = "failed"


class MatterImportJobStatus(StrEnum):
    VALIDATED = "validated"
    IMPORTING = "importing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class MatterImportRowStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    # A row whose only problem is that the matter already exists (in this file
    # or in the tenant). Excluded from the submission rather than blocking it.
    DUPLICATE = "duplicate"
    CREATED = "created"
    FAILED = "failed"


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
    DISPOSED = "disposed"


# Product-wide creation policy. Intake promotion deliberately passes
# ``MatterStatus.INTAKE`` explicitly; every producer that omits a status must
# create an operational matter. Keep both the ORM and database defaults tied to
# this value so background scripts and direct SQL cannot silently resurrect the
# retired Intake-by-default behavior.
DEFAULT_MATTER_STATUS = MatterStatus.ACTIVE


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
    CANCELLED = "cancelled"


class MatterTaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MatterTaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class MatterConflictCheckStatus(StrEnum):
    # PG-001 conflict-review states. These describe the advisory review record
    # and do not control Matter lifecycle transitions.
    #   pending     — check ran, ≥1 candidate flagged, awaiting partner review
    #   cleared     — no overlap OR partner reviewed and cleared
    #   conflicted  — partner reviewed and confirms a conflict for follow-up
    #   waived      — partner reviewed and explicitly waived (must record reason)
    PENDING = "pending"
    CLEARED = "cleared"
    CONFLICTED = "conflicted"
    WAIVED = "waived"


class MatterCourtSyncStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class MatterCourtOrderKind(StrEnum):
    DAILY_ORDER = "daily_order"
    INTERIM_ORDER = "interim_order"
    STAY_ORDER = "stay_order"
    FINAL_JUDGMENT = "final_judgment"
    OTHER = "other"


class MatterStayStatus(StrEnum):
    NONE = "none"
    GRANTED = "granted"
    CONTINUED = "continued"
    MODIFIED = "modified"
    VACATED = "vacated"
    UNKNOWN = "unknown"


class MatterProceedingSignalType(StrEnum):
    NEXT_HEARING = "next_hearing"
    FILING_DEFECT = "filing_defect"
    COMPLIANCE_DIRECTION = "compliance_direction"
    REPLY_AFFIDAVIT_DEADLINE = "reply_affidavit_deadline"
    COUNSEL_APPEARANCE = "counsel_appearance"
    INTERIM_OBSERVATION = "interim_observation"
    ORDER_KIND = "order_kind"
    ACTION_REQUIRED = "action_required"


class MatterProceedingConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MatterProceedingReviewStatus(StrEnum):
    REVIEW_REQUIRED = "review_required"
    REVIEWED = "reviewed"
    AUTO_PROMOTED = "auto_promoted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class MatterComplianceExtractionStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class MatterComplianceSourceType(StrEnum):
    AUTO_FETCHED_ORDER = "auto_fetched_order"
    MANUAL_ORDER = "manual_order"
    MANUAL_UPLOAD = "manual_upload"


class MatterComplianceTrigger(StrEnum):
    CASE_TRACKING = "case_tracking"
    COURT_SYNC = "court_sync"
    MANUAL_ORDER_CREATE = "manual_order_create"
    ATTACHMENT_PROCESSED = "attachment_processed"
    MANUAL_RETRY = "manual_retry"


class MatterComplianceStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WAIVED = "waived"
    NOT_APPLICABLE = "not_applicable"


class MatterComplianceReviewStatus(StrEnum):
    REVIEW_REQUIRED = "review_required"
    CONFIRMED = "confirmed"
    EDITED = "edited"
    REJECTED = "rejected"


class MatterBillingMode(StrEnum):
    HOURLY = "hourly"
    FIXED_FEE = "fixed_fee"
    MILESTONE = "milestone"
    MIXED = "mixed"


class MatterBillingRateScope(StrEnum):
    USER = "user"
    ROLE = "role"
    PRACTICE_AREA = "practice_area"
    DEFAULT = "default"


class MatterNextHearingSource(StrEnum):
    MANUAL = "manual"
    CASE_TRACKING = "case_tracking"
    COURT_SYNC = "court_sync"
    PROCEEDING_INTELLIGENCE = "proceeding_intelligence"
    CAUSE_LIST = "cause_list"
    UNKNOWN = "unknown"


class MatterNextHearingSuggestionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class MatterDocumentType(StrEnum):
    COMPLAINT_PETITION = "complaint_petition"
    NOTICE = "notice"
    VAKALATNAMA = "vakalatnama"
    PLEADING_REPLY = "pleading_reply"
    AFFIDAVIT = "affidavit"
    CHIEF_AFFIDAVIT = "chief_affidavit"
    COUNTER_AFFIDAVIT = "counter_affidavit"
    EVIDENCE = "evidence"
    WRITTEN_SUBMISSION = "written_submission"
    INTERIM_APPLICATION = "interim_application"
    ORDER_JUDGMENT = "order_judgment"
    CORRESPONDENCE = "correspondence"
    RESEARCH = "research"
    BILLING = "billing"
    OTHER = "other"


class MatterDocumentLifecycleStage(StrEnum):
    INITIATION = "initiation"
    PLEADINGS = "pleadings"
    INTERIM_APPLICATIONS = "interim_applications"
    EVIDENCE = "evidence"
    ARGUMENTS = "arguments"
    ORDERS = "orders"
    POST_ORDER = "post_order"
    ADMINISTRATIVE = "administrative"
    OTHER = "other"


class AffidavitIntelligenceRunStatus(StrEnum):
    COMPLETED = "completed"
    INSUFFICIENT_SOURCE_TEXT = "insufficient_source_text"
    NO_FINDINGS = "no_findings"


class AffidavitStatementType(StrEnum):
    KEY_STATEMENT = "key_statement"
    FACT_ASSERTION = "fact_assertion"
    TIMELINE_POINT = "timeline_point"
    MONETARY_FIGURE = "monetary_figure"
    NAMED_ENTITY = "named_entity"
    EXHIBIT_REFERENCE = "exhibit_reference"
    EVIDENCE_GAP = "evidence_gap"
    CONTRADICTION = "contradiction"


class AffidavitQuestionCategory(StrEnum):
    FACT_BASED = "fact_based"
    TIMELINE_INCONSISTENCY = "timeline_inconsistency"
    FINANCIAL_SCRUTINY = "financial_scrutiny"
    EVIDENCE_CONTRADICTION = "evidence_contradiction"
    DOCUMENT_SUPPORT = "document_support"
    INTENT_MOTIVE = "intent_motive"


class AffidavitIntelligenceReviewStatus(StrEnum):
    REVIEW_REQUIRED = "review_required"
    REVIEWED = "reviewed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class MockHearingMode(StrEnum):
    CLIENT_PREPARATION = "client_preparation"
    COUNSEL_PRACTICE = "counsel_practice"
    WITNESS_PREPARATION = "witness_preparation"


class MockHearingSessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MockHearingQuestionStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"


class MockHearingReviewStatus(StrEnum):
    REVIEW_REQUIRED = "review_required"
    REVIEWED = "reviewed"


class LegalKnowledgeGraphRunStatus(StrEnum):
    COMPLETED = "completed"
    NO_SOURCE_RECORDS = "no_source_records"


class LegalKnowledgeGraphNodeType(StrEnum):
    MATTER = "matter"
    PROCEEDING_SIGNAL = "proceeding_signal"
    AFFIDAVIT_STATEMENT = "affidavit_statement"
    AFFIDAVIT_QUESTION = "affidavit_question"
    MOCK_HEARING_QUESTION = "mock_hearing_question"
    MOCK_HEARING_RESPONSE = "mock_hearing_response"
    PREDICTIVE_SIGNAL = "predictive_signal"
    BENCH_CONTEXT = "bench_context"
    LEGAL_SOURCE = "legal_source"
    STATUTE_OR_ISSUE = "statute_or_issue"
    REVIEW_ACTION = "review_action"


class LegalKnowledgeGraphEdgeType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    REFERENCES = "references"
    DERIVED_FROM = "derived_from"
    PROMPTS = "prompts"
    RELATES_TO = "relates_to"
    HAS_LIMITATION = "has_limitation"


class LegalKnowledgeGraphSourceType(StrEnum):
    MATTER = "matter"
    MATTER_COURT_ORDER = "matter_court_order"
    MATTER_PROCEEDING_SIGNAL = "matter_proceeding_signal"
    MATTER_DOCUMENT = "matter_document"
    MATTER_ATTACHMENT_CHUNK = "matter_attachment_chunk"
    AFFIDAVIT_STATEMENT = "affidavit_statement"
    AFFIDAVIT_QUESTION = "affidavit_question"
    MOCK_HEARING_SESSION = "mock_hearing_session"
    MOCK_HEARING_QUESTION = "mock_hearing_question"
    MOCK_HEARING_RESPONSE = "mock_hearing_response"
    PREDICTIVE_SIGNAL_ITEM = "predictive_signal_item"
    PREDICTIVE_SIGNAL_RUN = "predictive_signal_run"
    AUTHORITY_DOCUMENT = "authority_document"
    AGGREGATE_SNAPSHOT = "aggregate_snapshot"
    LITIGATION_INTELLIGENCE_REVIEW_ACTION = "litigation_intelligence_review_action"
    UNAVAILABLE = "unavailable"


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
    # EH-SGR-02: services/pine_labs.py maps a refund_processed webhook to
    # "refunded", which services/payments.py assigns to attempt.status. Without
    # this member the value was storable but unreadable, and the owning matter
    # returned 500 on every subsequent load.
    REFUNDED = "refunded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class BillingSubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    CHECKOUT_STARTED = "checkout_started"
    PAYMENT_PENDING = "payment_pending"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    GRACE = "grace"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    MANUAL_ACTIVE = "manual_active"


class BillingCheckoutStatus(StrEnum):
    CREATED = "created"
    PROVIDER_DISABLED = "provider_disabled"
    PAYMENT_PENDING = "payment_pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BillingPaymentOrderStatus(StrEnum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    UNKNOWN = "unknown"


class BillingCreditLedgerEventType(StrEnum):
    INCLUDED_MONTHLY_GRANT = "included_monthly_grant"
    TOPUP_PURCHASE = "topup_purchase"
    MANUAL_ADMIN_GRANT = "manual_admin_grant"
    USAGE_DEBIT = "usage_debit"
    USAGE_REFUND = "usage_refund"
    EXPIRY = "expiry"
    PLAN_CHANGE_ADJUSTMENT = "plan_change_adjustment"


class ProviderCostCategory(StrEnum):
    CASE_REFRESH = "case_refresh"
    BULK_CASE_REFRESH = "bulk_case_refresh"
    LLM = "llm"
    LLM_INPUT = "llm_input"
    LLM_OUTPUT = "llm_output"
    EMBEDDING = "embedding"
    DOCUMENT_PROCESSING = "document_processing"
    OCR_PAGE = "ocr_page"
    STORAGE = "storage"
    BANDWIDTH_EXPORT = "bandwidth_export"
    PAYMENT_MDR = "payment_mdr"
    PAYMENT_FIXED_FEE = "payment_fixed_fee"
    PAYMENT_REFUND_FEE = "payment_refund_fee"
    PAYMENT_CHARGEBACK_FEE = "payment_chargeback_fee"
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    MANUAL_SUPPORT = "manual_support"


class DocumentProcessingStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    NEEDS_OCR = "needs_ocr"
    FAILED = "failed"


class DocumentProcessingTargetType(StrEnum):
    MATTER_ATTACHMENT = "matter_attachment"
    CONTRACT_ATTACHMENT = "contract_attachment"
    IP_DOCUMENT_VERSION = "ip_document_version"


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


class ContractTypeKey(StrEnum):
    AGREEMENT = "agreement"
    NDA = "nda"
    ADDENDUM = "addendum"
    PURCHASE_ORDER = "purchase_order"
    MASTER_SERVICES_AGREEMENT = "master_services_agreement"
    STATEMENT_OF_WORK = "statement_of_work"
    LEASE = "lease"
    EMPLOYMENT = "employment"
    SETTLEMENT = "settlement"
    AMENDMENT = "amendment"
    OTHER = "other"


class ContractLegalReferenceSource(StrEnum):
    MANUAL = "manual"
    AI_SUGGESTED = "ai_suggested"
    IMPORTED = "imported"


class ContractReviewStatus(StrEnum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ContractAttachmentRole(StrEnum):
    PRIMARY_CONTRACT = "primary_contract"
    AMENDMENT = "amendment"
    ADDENDUM = "addendum"
    ANNEXURE = "annexure"
    EMAIL_APPROVAL = "email_approval"
    BOARD_RESOLUTION = "board_resolution"
    PURCHASE_ORDER = "purchase_order"
    STATEMENT_OF_WORK = "statement_of_work"
    SUPPORTING_DOCUMENT = "supporting_document"
    OTHER = "other"


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


class AuthorityCitationTreatment(StrEnum):
    """Good-law signal — how a citing case treats a cited authority.

    Values follow the standard citator vocabulary used by Westlaw /
    Manupatra / SCC OnLine, narrowed to seven categories that map onto
    cue-verb heuristics in Indian judgments:

    - ``followed``      — citing case applies / approves / relies on the
                          authority. Positive treatment.
    - ``distinguished`` — citing case sets the authority aside on the
                          facts. Mildly negative — still good law, but
                          not on point.
    - ``overruled``     — later case explicitly overrules. Bad law.
    - ``doubted``       — citing case expresses doubt or reservation.
                          Caution.
    - ``reversed``      — appellate reversal of the cited decision. Bad
                          law for the original holding.
    - ``dissented``     — cited only in a dissent (not majority). Weak
                          authority.
    - ``considered``    — discussed without applying or rejecting.
                          Default fallback when cues are weak.
    - ``neutral``       — no cue verb detected; pure citation reference.
    """

    FOLLOWED = "followed"
    DISTINGUISHED = "distinguished"
    OVERRULED = "overruled"
    DOUBTED = "doubted"
    REVERSED = "reversed"
    DISSENTED = "dissented"
    CONSIDERED = "considered"
    NEUTRAL = "neutral"


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
    # ADP-01 storage governance. Null means no firm quota is enforced;
    # this preserves legacy tenants until an admin sets a limit.
    storage_quota_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Sprint 8c: when true, matter visibility for non-owners is gated
    # on team membership (plus existing ethical-wall + grant rules).
    # Default false means teams are metadata-only; flipping this on is
    # a deliberate governance decision per-tenant.
    team_scoping_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    employee_import_jobs: Mapped[list[EmployeeBulkImportJob]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    matter_import_jobs: Mapped[list[MatterBulkImportJob]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    custom_roles: Mapped[list[CustomRole]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        foreign_keys="CustomRole.company_id",
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
    __table_args__ = (
        UniqueConstraint("company_id", "user_id", name="uq_company_membership"),
        UniqueConstraint(
            "id",
            "company_id",
            name="uq_company_memberships_id_company_id",
        ),
    )

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
    custom_role_id: Mapped[str | None] = mapped_column(
        ForeignKey("custom_roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    responsible_matters: Mapped[list[Matter]] = relationship(
        back_populates="responsible_lawyer_membership",
        foreign_keys="Matter.responsible_lawyer_membership_id",
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
    created_outside_counsel_assignments: Mapped[list[MatterOutsideCounselAssignment]] = (
        relationship(
            back_populates="assigned_by_membership",
            foreign_keys="MatterOutsideCounselAssignment.assigned_by_membership_id",
        )
    )
    recorded_outside_counsel_spend_records: Mapped[list[OutsideCounselSpendRecord]] = relationship(
        back_populates="recorded_by_membership",
        foreign_keys="OutsideCounselSpendRecord.recorded_by_membership_id",
    )
    employee_profile: Mapped[EmployeeProfile | None] = relationship(
        back_populates="membership",
        uselist=False,
        foreign_keys="EmployeeProfile.membership_id",
    )
    custom_role: Mapped[CustomRole | None] = relationship(
        back_populates="assigned_memberships",
        foreign_keys=[custom_role_id],
    )


class CustomRole(Base):
    """Tenant-scoped custom role template over approved server capabilities."""

    __tablename__ = "custom_roles"
    __table_args__ = (UniqueConstraint("company_id", "slug", name="uq_custom_roles_company_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    permissions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship(
        back_populates="custom_roles",
        foreign_keys=[company_id],
    )
    assigned_memberships: Mapped[list[CompanyMembership]] = relationship(
        back_populates="custom_role",
        foreign_keys="CompanyMembership.custom_role_id",
    )
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )
    updated_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[updated_by_membership_id],
    )


class EmployeeProfile(Base):
    """Tenant-scoped employee metadata layered beside CompanyMembership.

    Membership remains the auth/RBAC object. This profile stores HR-facing
    directory fields and account setup state without changing the canonical
    fixed-role membership model.
    """

    __tablename__ = "employee_profiles"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "membership_id",
            name="uq_employee_profiles_company_membership",
        ),
        UniqueConstraint(
            "company_id",
            "employee_code",
            name="uq_employee_profiles_company_employee_code",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mobile: Mapped[str | None] = mapped_column(String(40), nullable=True)
    designation: Mapped[str | None] = mapped_column(String(160), nullable=True)
    department: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    employee_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    manager_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    joined_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    employment_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=EmployeeEmploymentStatus.INVITED,
        index=True,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    setup_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    setup_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    password_reset_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    force_password_change: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
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

    company: Mapped[Company] = relationship()
    membership: Mapped[CompanyMembership] = relationship(
        back_populates="employee_profile",
        foreign_keys=[membership_id],
    )
    manager_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[manager_membership_id],
    )


class AccountSetupToken(Base):
    """Single-use account setup/reset token.

    Only the SHA-256 hash is stored. The plaintext token is returned once to
    the mailer/debug response path and cannot be reconstructed from this row.
    """

    __tablename__ = "account_setup_tokens"

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
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship()
    user: Mapped[User] = relationship()
    membership: Mapped[CompanyMembership] = relationship(
        foreign_keys=[membership_id],
    )
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )


class EmployeeBulkImportJob(Base):
    """Tenant-scoped employee import preview/commit job."""

    __tablename__ = "employee_bulk_import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=EmployeeImportJobStatus.PREVIEWED,
        index=True,
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: utcnow() + timedelta(hours=24),
        nullable=False,
    )
    committed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    company: Mapped[Company] = relationship(back_populates="employee_import_jobs")
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )
    rows: Mapped[list[EmployeeBulkImportRow]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="EmployeeBulkImportRow.row_number",
    )


class EmployeeBulkImportRow(Base):
    """One parsed row in a tenant-scoped employee import job."""

    __tablename__ = "employee_bulk_import_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("employee_bulk_import_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    normalized_json: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    errors_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=EmployeeImportRowStatus.INVALID,
        index=True,
    )
    created_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship()
    job: Mapped[EmployeeBulkImportJob] = relationship(back_populates="rows")
    created_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_membership_id],
    )


class MatterBulkImportJob(Base):
    """Persistent, tenant-scoped validation and commit record for matter imports."""

    __tablename__ = "matter_bulk_import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    manifest_format: Mapped[str] = mapped_column(String(12), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MatterImportJobStatus.VALIDATED,
        index=True,
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: utcnow() + timedelta(hours=24),
        nullable=False,
        index=True,
    )
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship(back_populates="matter_import_jobs")
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )
    rows: Mapped[list[MatterBulkImportRow]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="MatterBulkImportRow.row_number",
    )


class MatterBulkImportRow(Base):
    """One sanitized and normalized row in a matter import job."""

    __tablename__ = "matter_bulk_import_rows"
    __table_args__ = (UniqueConstraint("job_id", "row_number", name="uq_matter_import_job_row"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("matter_bulk_import_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    normalized_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    errors_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterImportRowStatus.INVALID,
        index=True,
    )
    created_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship()
    job: Mapped[MatterBulkImportJob] = relationship(back_populates="rows")
    created_matter: Mapped[Matter | None] = relationship(foreign_keys=[created_matter_id])


class Matter(Base):
    __tablename__ = "matters"
    __table_args__ = (
        UniqueConstraint("company_id", "matter_code", name="uq_company_matter_code"),
        UniqueConstraint("id", "company_id", name="uq_matters_id_company_id"),
        CheckConstraint(
            "(status IN ('disposed', 'closed') AND is_active = false) OR "
            "(status NOT IN ('disposed', 'closed') AND is_active = true)",
            name="ck_matters_status_active_consistent",
        ),
        CheckConstraint(
            "lifecycle_version >= 0",
            name="ck_matters_lifecycle_version_nonnegative",
        ),
        CheckConstraint(
            "access_policy_version >= 0",
            name="ck_matters_access_policy_version_nonnegative",
        ),
    )

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
    responsible_lawyer_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    matter_code: Mapped[str] = mapped_column(String(80), nullable=False)
    matter_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    client_contact_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    client_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    opposing_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opposing_counsel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DEFAULT_MATTER_STATUS,
        server_default=DEFAULT_MATTER_STATUS,
    )
    practice_area: Mapped[str] = mapped_column(String(120), nullable=False)
    forum_level: Mapped[str] = mapped_column(String(40), nullable=False)
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    court_forum_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    judge_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    case_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    filing_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cnr_number: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_hearing_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_hearing_source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=MatterNextHearingSource.UNKNOWN,
        server_default=MatterNextHearingSource.UNKNOWN,
    )
    next_hearing_source_ref_type: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    next_hearing_source_ref_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    next_hearing_updated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    next_hearing_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_hearing_manual_lock: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    billing_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_billing_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    claim_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    claim_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    claim_amount_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    lifecycle_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # PRD §13.4 / §5.6: when True, only explicit matter_access_grants
    # open the matter; when False (default) every company member with
    # the company-level role can see it. Ethical walls always apply
    # regardless of this flag.
    restricted_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_policy_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Phase C-3 (MOD-TS-016): when False (default), an outside-counsel
    # portal user only sees their OWN work-product, time entries, and
    # invoice submissions on this matter. When True, every OC on the
    # matter sees every other OC's submissions. Internal users (firm
    # side) always see everything regardless of this flag.
    oc_cross_visibility_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    # PRD §7.1: nullable FK to the master Court table. `court_name`
    # stays as the freeform fallback for courts we haven't catalogued
    # yet, so old matters keep working without a data backfill.
    court_id: Mapped[str | None] = mapped_column(
        ForeignKey("courts.id", ondelete="SET NULL"),
        nullable=True,
    )
    forum_catalog_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("forum_catalog_entries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    forum_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    forum_district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    forum_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    forum_consumer_level: Mapped[str | None] = mapped_column(String(24), nullable=True)
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
    responsible_lawyer_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[responsible_lawyer_membership_id],
    )
    next_hearing_updated_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[next_hearing_updated_by_membership_id],
    )
    billing_profile: Mapped[MatterBillingProfile | None] = relationship(
        foreign_keys=[billing_profile_id],
    )
    forum_catalog_entry: Mapped[ForumCatalogEntry | None] = relationship(
        foreign_keys=[forum_catalog_entry_id]
    )
    tasks: Mapped[list[MatterTask]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        foreign_keys="MatterTask.matter_id",
    )
    notes: Mapped[list[MatterNote]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
    )
    hearings: Mapped[list[MatterHearing]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        foreign_keys="MatterHearing.matter_id",
    )
    conflict_checks: Mapped[list[MatterConflictCheck]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
    )
    activity_events: Mapped[list[MatterActivity]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterActivity.created_at)",
    )
    tag_assignments: Mapped[list[MatterTagAssignment]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="asc(MatterTagAssignment.created_at)",
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
    compliance_extraction_runs: Mapped[list[MatterComplianceExtractionRun]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="desc(MatterComplianceExtractionRun.created_at)",
    )
    compliance_items: Mapped[list[MatterComplianceItem]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by=(
            "MatterComplianceItem.due_on.asc().nulls_last(), MatterComplianceItem.created_at.desc()"
        ),
    )
    next_hearing_history: Mapped[list[MatterNextHearingHistory]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        foreign_keys="MatterNextHearingHistory.matter_id",
        order_by="desc(MatterNextHearingHistory.created_at)",
    )
    next_hearing_suggestions: Mapped[list[MatterNextHearingSuggestion]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        foreign_keys="MatterNextHearingSuggestion.matter_id",
        order_by="desc(MatterNextHearingSuggestion.created_at)",
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
    drafting_data_fields: Mapped[list[DraftingDataExtractionField]] = relationship(
        back_populates="matter",
        cascade="all, delete-orphan",
        order_by="DraftingDataExtractionField.created_at.desc()",
    )


class MatterTag(Base):
    __tablename__ = "matter_tags"
    __table_args__ = (UniqueConstraint("company_id", "slug", name="uq_matter_tags_company_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    color_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship()
    assignments: Mapped[list[MatterTagAssignment]] = relationship(
        back_populates="tag",
        cascade="all, delete-orphan",
    )


class MatterTagAssignment(Base):
    __tablename__ = "matter_tag_assignments"
    __table_args__ = (UniqueConstraint("matter_id", "tag_id", name="uq_matter_tag_assignment"),)

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
    tag_id: Mapped[str] = mapped_column(
        ForeignKey("matter_tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship()
    matter: Mapped[Matter] = relationship(back_populates="tag_assignments")
    tag: Mapped[MatterTag] = relationship(back_populates="assignments")
    created_by_membership: Mapped[CompanyMembership | None] = relationship()


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


class MatterFileQAEntry(Base):
    __tablename__ = "matter_file_qa_entries"
    __table_args__ = (
        CheckConstraint(
            "answer_status IN ("
            "'answered', 'partial_answer', 'insufficient_evidence', "
            "'processing_required', 'no_documents', 'error'"
            ")",
            name="ck_matter_file_qa_entries_answer_status",
        ),
        CheckConstraint(
            "answer_mode IN ("
            "'direct', 'summary', 'sections', 'allegations', "
            "'evidence', 'chronology', 'gaps'"
            ")",
            name="ck_matter_file_qa_entries_answer_mode",
        ),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low', 'insufficient')",
            name="ck_matter_file_qa_entries_confidence",
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
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    answer_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sources_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    structured_items_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    limitations_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    exported_note_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_notes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        index=True,
    )


class MatterTask(Base):
    __tablename__ = "matter_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_matter_task_matter_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_matter_task_ip_docket_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "company_id", name="uq_matter_task_id_company"),
        CheckConstraint(
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_matter_task_exactly_one_target",
        ),
        ForeignKeyConstraint(
            [
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                "ip_docket_id",
                "neutralized_by_ip_lifecycle_version",
            ],
            [
                "ip_docket_events.id",
                "ip_docket_events.company_id",
                "ip_docket_events.docket_id",
                "ip_docket_events.resulting_lifecycle_version",
            ],
            name="fk_matter_task_neutralized_event_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_by_ip_lifecycle_version IS NULL AND neutralized_at IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_by_ip_lifecycle_version IS NOT NULL AND neutralized_at IS NOT NULL "
            "AND company_id IS NOT NULL)",
            name="ck_matter_task_ip_lifecycle_provenance_complete",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_version IS NULL OR "
            "neutralized_by_ip_lifecycle_version > 0",
            name="ck_matter_task_ip_lifecycle_version_positive",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR status = 'cancelled'",
            name="ck_matter_task_ip_lifecycle_terminal_state",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR ip_docket_id IS NOT NULL",
            name="ck_matter_task_ip_lifecycle_provenance_target",
        ),
        Index(
            "ix_matter_tasks_ip_lifecycle_event",
            "neutralized_by_ip_lifecycle_event_id",
            "company_id",
            "ip_docket_id",
            "neutralized_by_ip_lifecycle_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="CASCADE"),
        nullable=True,
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
    cancelled_by_matter_disposal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    neutralized_by_ip_lifecycle_event_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    neutralized_by_ip_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    neutralized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    matter: Mapped[Matter | None] = relationship(
        back_populates="tasks", foreign_keys=[matter_id]
    )
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="created_tasks",
        foreign_keys=[created_by_membership_id],
    )
    owner_membership: Mapped[CompanyMembership | None] = relationship(
        back_populates="owned_tasks",
        foreign_keys=[owner_membership_id],
    )


class MatterConflictCheck(Base):
    """Optional conflict-of-interest review for a matter (PG-001).

    May be run when a matter is created or during a client engagement.
    Service scans existing client names and matter client/opposing-party
    names for overlap and persists candidate matches as a JSON column.
    Partner reviews and records `cleared`, `conflicted`, or `waived`. The
    matter cockpit presents the latest result as an advisory workflow;
    conflict-check state does not control the Matter lifecycle.
    """

    __tablename__ = "matter_conflict_checks"

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
    ran_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    matter_lifecycle_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    opposing_party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    related_party_names_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    candidates_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterConflictCheckStatus.PENDING,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter] = relationship(back_populates="conflict_checks")


class MatterHearing(Base):
    __tablename__ = "matter_hearings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_matter_hearing_matter_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_matter_hearing_ip_docket_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "company_id", name="uq_matter_hearing_id_company"),
        CheckConstraint(
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_matter_hearing_exactly_one_target",
        ),
        ForeignKeyConstraint(
            [
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                "ip_docket_id",
                "neutralized_by_ip_lifecycle_version",
            ],
            [
                "ip_docket_events.id",
                "ip_docket_events.company_id",
                "ip_docket_events.docket_id",
                "ip_docket_events.resulting_lifecycle_version",
            ],
            name="fk_matter_hearing_neutralized_event_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_by_ip_lifecycle_version IS NULL AND neutralized_at IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_by_ip_lifecycle_version IS NOT NULL AND neutralized_at IS NOT NULL "
            "AND company_id IS NOT NULL)",
            name="ck_matter_hearing_ip_lifecycle_provenance_complete",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_version IS NULL OR "
            "neutralized_by_ip_lifecycle_version > 0",
            name="ck_matter_hearing_ip_lifecycle_version_positive",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR status = 'cancelled'",
            name="ck_matter_hearing_ip_lifecycle_terminal_state",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR ip_docket_id IS NOT NULL",
            name="ck_matter_hearing_ip_lifecycle_provenance_target",
        ),
        Index(
            "ix_matter_hearings_ip_lifecycle_event",
            "neutralized_by_ip_lifecycle_event_id",
            "company_id",
            "ip_docket_id",
            "neutralized_by_ip_lifecycle_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    hearing_on: Mapped[date] = mapped_column(Date, nullable=False)
    time_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="time_not_published"
    )
    hearing_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    session_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    reminder_policy_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hearing_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    attendee_membership_ids_json: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    source_ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    responsible_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    forum_name: Mapped[str] = mapped_column(String(255), nullable=False)
    judge_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterHearingStatus.SCHEDULED,
    )
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by_matter_disposal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    neutralized_by_ip_lifecycle_event_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    neutralized_by_ip_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    neutralized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter | None] = relationship(
        back_populates="hearings", foreign_keys=[matter_id]
    )
    reminders: Mapped[list[HearingReminder]] = relationship(
        back_populates="hearing",
        cascade="all, delete-orphan",
        order_by="HearingReminder.scheduled_for",
    )


class HearingReminderChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    # MOD-TS-007 (2026-04-26) — WhatsApp via Meta Cloud API. Adapter
    # returns "provider not configured" until CASEOPS_WHATSAPP_ENABLED=true
    # AND template approval is in place. Solo-lawyer pitch surfaces it
    # as a roadmap channel; today only EMAIL + SMS are wired.
    WHATSAPP = "whatsapp"
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


class CalendarProvider(StrEnum):
    OUTLOOK = "outlook"
    GOOGLE_CALENDAR = "google_calendar"


class CalendarConnectionStatus(StrEnum):
    CONNECTED = "connected"
    REVOKED = "revoked"
    ERROR = "error"


class CalendarSyncSourceType(StrEnum):
    MATTER_HEARING = "matter_hearing"
    MATTER_DEADLINE = "matter_deadline"
    MATTER_TASK = "matter_task"


class CalendarEventSyncStatus(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD_LETTER = "dead_letter"
    DELETED = "deleted"
    DELETE_PENDING = "delete_pending"


class MailboxProvider(StrEnum):
    GMAIL = "gmail"
    OUTLOOK_MAIL = "outlook_mail"


class DriveProvider(StrEnum):
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE_SHAREPOINT = "onedrive_sharepoint"


class MailboxConnectionStatus(StrEnum):
    CONNECTED = "connected"
    REVOKED = "revoked"
    ERROR = "error"


class DriveConnectionStatus(StrEnum):
    CONNECTED = "connected"
    REVOKED = "revoked"
    ERROR = "error"


class MailboxImportStatus(StrEnum):
    QUEUED = "queued"
    NEW = "new"
    IMPORTED = "imported"
    UNMATCHED = "unmatched"
    DUPLICATE = "duplicate"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    IGNORED = "ignored"
    RESOLVED = "resolved"
    LINKED_METADATA = "linked_metadata"
    CONTENT_IMPORT_REQUESTED = "content_import_requested"
    CONTENT_IMPORTED = "content_imported"


class MailboxAttachmentCandidateStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    APPROVED_IMPORTED = "approved_imported"
    REJECTED = "rejected"
    DUPLICATE_SKIPPED = "duplicate_skipped"


class MailboxWebhookStatus(StrEnum):
    QUEUED = "queued"
    PROCESSED = "processed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class ConnectorHealthProvider(StrEnum):
    CASE_TRACKING = "case_tracking"
    GOOGLE_WORKSPACE = "google_workspace"
    GMAIL = "gmail"
    GOOGLE_DRIVE = "google_drive"
    GOOGLE_CALENDAR = "google_calendar"
    MICROSOFT_365 = "microsoft_365"
    OUTLOOK_MAIL = "outlook_mail"
    OUTLOOK_CALENDAR = "outlook_calendar"
    ONEDRIVE_SHAREPOINT = "onedrive_sharepoint"
    EMAIL_DELIVERY = "email_delivery"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class ConnectorHealthStatus(StrEnum):
    DISABLED = "disabled"
    MISSING_CONFIG = "missing_config"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    TOKEN_EXPIRED = "token_expired"
    SCOPE_MISSING = "scope_missing"
    RATE_LIMITED = "rate_limited"
    PROVIDER_OUTAGE = "provider_outage"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class ReviewCandidateStatus(StrEnum):
    NEW = "new"
    IGNORED = "ignored"
    LINKED_METADATA = "linked_metadata"
    CONTENT_IMPORT_REQUESTED = "content_import_requested"
    CONTENT_IMPORTED = "content_imported"
    FAILED = "failed"


class CalendarEventCandidateStatus(StrEnum):
    NEW = "new"
    CONFLICT = "conflict"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"
    FAILED = "failed"


class InboundEmailAliasStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class InboundEmailEventStatus(StrEnum):
    NEW = "new"
    LINKED_METADATA = "linked_metadata"
    CONTENT_IMPORT_REQUESTED = "content_import_requested"
    CONTENT_IMPORTED = "content_imported"
    IGNORED = "ignored"
    REJECTED = "rejected"
    FAILED = "failed"


class NotificationDigestFrequency(StrEnum):
    IMMEDIATE = "immediate"
    DAILY = "daily"
    WEEKLY = "weekly"
    DISABLED = "disabled"


class NotificationRuleScopeType(StrEnum):
    COMPANY = "company"
    MATTER = "matter"
    USER = "user"


class NotificationRuleEventType(StrEnum):
    HEARING_UPCOMING = "hearing_upcoming"
    NEW_ORDER_UPLOADED = "new_order_uploaded"
    STAY_STATUS_CHANGED = "stay_status_changed"


class InAppNotificationStatus(StrEnum):
    UNREAD = "unread"
    READ = "read"


class NotificationDeliveryChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class NotificationDeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    RETRY_SCHEDULED = "retry_scheduled"
    BLOCKED = "blocked"
    SUPPRESSED = "suppressed"
    BOUNCED = "bounced"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


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
            "hearing_id",
            "recipient_membership_id",
            "channel",
            "scheduled_for",
            "schedule_generation",
            name="uq_hearing_reminders_recipient_channel_time_generation",
        ),
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_hearing_reminder_matter_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_hearing_reminder_ip_docket_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_hearing_reminder_exactly_one_target",
        ),
        ForeignKeyConstraint(
            [
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                "ip_docket_id",
                "neutralized_by_ip_lifecycle_version",
            ],
            [
                "ip_docket_events.id",
                "ip_docket_events.company_id",
                "ip_docket_events.docket_id",
                "ip_docket_events.resulting_lifecycle_version",
            ],
            name="fk_hearing_reminder_neutralized_event_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_by_ip_lifecycle_version IS NULL AND neutralized_at IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_by_ip_lifecycle_version IS NOT NULL AND neutralized_at IS NOT NULL "
            "AND company_id IS NOT NULL)",
            name="ck_hearing_reminder_ip_lifecycle_provenance_complete",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_version IS NULL OR "
            "neutralized_by_ip_lifecycle_version > 0",
            name="ck_hearing_reminder_ip_lifecycle_version_positive",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR status = 'cancelled'",
            name="ck_hearing_reminder_ip_lifecycle_terminal_state",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR ip_docket_id IS NOT NULL",
            name="ck_hearing_reminder_ip_lifecycle_provenance_target",
        ),
        Index(
            "ix_hearing_reminders_ip_lifecycle_event",
            "neutralized_by_ip_lifecycle_event_id",
            "company_id",
            "ip_docket_id",
            "neutralized_by_ip_lifecycle_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="CASCADE"),
        nullable=True,
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
    schedule_generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
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
    neutralized_by_ip_lifecycle_event_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    neutralized_by_ip_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    neutralized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    hearing: Mapped[MatterHearing] = relationship(back_populates="reminders")


class EmailSuppressionReason(StrEnum):
    """Why a tenant-scoped email address must not receive further mail.

    These mirror the SendGrid event names (sans hyphens) so the
    webhook handler can map directly. ``manual`` covers admin-driven
    insertions if/when an admin tool surfaces this list.
    """

    BOUNCE = "bounce"
    DROPPED = "dropped"
    SPAM_REPORT = "spam_report"
    UNSUBSCRIBE = "unsubscribe"
    GROUP_UNSUBSCRIBE = "group_unsubscribe"
    MANUAL = "manual"


class EmailSuppression(Base):
    """Tenant-scoped suppression list, populated by SendGrid webhook
    events (bounce / dropped / spam_report / unsubscribe /
    group_unsubscribe) and consulted before every outbound matter email
    or hearing-reminder send. The auth-flow mailers (account setup,
    password reset, portal access) explicitly DO NOT consult this list:
    a user who unsubscribed from matter mail must still be able to
    reset their password.

    Tenant scoping rationale: a recipient who hard-bounced or
    unsubscribed inside one law firm's mail flow has not necessarily
    opted out of another firm's. Each ``company_id`` keeps its own
    list. SendGrid maintains a global suppression too, but trusting
    only the global list crosses tenant boundaries — the app-level
    list is what gates `services.communications.send_matter_email`
    and the hearing-reminder worker.

    Idempotency: ``(company_id, recipient_email)`` is unique, so
    re-applying a webhook event for the same address is a no-op (the
    handler upserts ``last_event_at`` + reason).
    """

    __tablename__ = "email_suppressions"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "recipient_email",
            name="uq_email_suppressions_tenant_address",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stored lowercase to match SendGrid event payloads; the upsert
    # path normalises before insert/lookup.
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    # Free-text excerpt of the SendGrid `reason` / `response` fields
    # so an admin tool can show "why" without reaching into raw event
    # JSON. Capped at 500 chars to keep the table light.
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # `sg_message_id` of the event that introduced the suppression.
    # Useful for audit + dedupe; nullable for `manual` insertions.
    source_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="sendgrid")
    first_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    recovery_action: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovered_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    fallback_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class UserCalendarConnection(Base):
    __tablename__ = "user_calendar_connections"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "membership_id",
            "provider",
            name="uq_calendar_connections_company_membership_provider",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=CalendarProvider.OUTLOOK,
    )
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=CalendarConnectionStatus.CONNECTED,
        index=True,
    )
    encrypted_token_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    company: Mapped[Company] = relationship()
    membership: Mapped[CompanyMembership] = relationship()
    event_syncs: Mapped[list[CalendarEventSync]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
    )


class TenantOutlookConfiguration(Base):
    __tablename__ = "tenant_outlook_configurations"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "provider",
            name="uq_tenant_outlook_configurations_company_provider",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=CalendarProvider.OUTLOOK,
    )
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_client_secret_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="organizations",
    )
    redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scopes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    oauth_consent_model_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    scopes_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    durable_runbook_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rollback_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redaction_rules_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="not_run",
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )
    updated_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[updated_by_membership_id],
    )


class TenantGoogleWorkspaceConfiguration(Base):
    __tablename__ = "tenant_google_workspace_configurations"
    __table_args__ = (
        Index("ix_tgws_config_company", "company_id"),
        Index("ix_tgws_config_created_by", "created_by_membership_id"),
        Index("ix_tgws_config_updated_by", "updated_by_membership_id"),
        UniqueConstraint(
            "company_id",
            name="uq_tenant_google_workspace_configurations_company",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_client_secret_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    calendar_redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gmail_redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    drive_redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scopes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    oauth_consent_model_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    scopes_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    webhook_runbook_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redaction_rules_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calendar_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gmail_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    drive_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="not_run",
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_membership_id: Mapped[str | None] = mapped_column(
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

    company: Mapped[Company] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )
    updated_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[updated_by_membership_id],
    )


class CalendarEventSync(Base):
    __tablename__ = "calendar_event_syncs"
    __table_args__ = (
        UniqueConstraint(
            "calendar_connection_id",
            "source_type",
            "source_id",
            name="uq_calendar_event_sync_connection_source",
        ),
        ForeignKeyConstraint(
            [
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                "neutralized_ip_docket_id",
                "neutralized_by_ip_lifecycle_version",
            ],
            [
                "ip_docket_events.id",
                "ip_docket_events.company_id",
                "ip_docket_events.docket_id",
                "ip_docket_events.resulting_lifecycle_version",
            ],
            name="fk_calendar_event_sync_neutralized_event_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_by_ip_lifecycle_version IS NULL AND neutralized_at IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_by_ip_lifecycle_version IS NOT NULL AND neutralized_at IS NOT NULL "
            "AND company_id IS NOT NULL)",
            name="ck_calendar_event_sync_ip_lifecycle_provenance_complete",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_version IS NULL OR "
            "neutralized_by_ip_lifecycle_version > 0",
            name="ck_calendar_event_sync_ip_lifecycle_version_positive",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR "
            "sync_status IN ('delete_pending', 'deleted')",
            name="ck_calendar_event_sync_ip_lifecycle_terminal_state",
        ),
        CheckConstraint(
            "drift_status IN ('unchecked', 'matches', 'moved', 'missing', 'unknown')",
            name="ck_calendar_event_sync_drift_status",
        ),
        CheckConstraint(
            "(reconciliation_candidate_id IS NULL AND "
            "reconciliation_snapshot_sha256 IS NULL AND "
            "reconciliation_provider_revision IS NULL) OR "
            "(reconciliation_candidate_id IS NOT NULL AND "
            "reconciliation_snapshot_sha256 IS NOT NULL AND "
            "reconciliation_provider_revision IS NOT NULL)",
            name="ck_calendar_event_sync_reconciliation_claim_complete",
        ),
        CheckConstraint(
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_ip_docket_id IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_ip_docket_id IS NOT NULL)",
            name="ck_calendar_event_sync_ip_lifecycle_provenance_target",
        ),
        Index(
            "ix_calendar_event_syncs_ip_lifecycle_event",
            "neutralized_by_ip_lifecycle_event_id",
            "company_id",
            "neutralized_ip_docket_id",
            "neutralized_by_ip_lifecycle_version",
        ),
        Index(
            "ix_calendar_event_syncs_reconciliation_candidate_id",
            "reconciliation_candidate_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    calendar_connection_id: Mapped[str] = mapped_column(
        ForeignKey("user_calendar_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sync_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=CalendarEventSyncStatus.PENDING,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_letter_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # UJ-62-EXC-03: whether the projected copy still matches the CaseOps source.
    # `unknown` exists on purpose — when the provider cannot be read we must not
    # report `matches`, because unverified is not verified.
    drift_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unchecked", server_default="unchecked"
    )
    drift_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Content-free: a reason, never a title or a date from the record.
    drift_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reconciliation_candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "calendar_projection_reconciliation_candidates.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_calendar_event_sync_reconciliation_candidate",
        ),
        nullable=True,
    )
    reconciliation_snapshot_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    reconciliation_provider_revision: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    durable_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    neutralized_by_ip_lifecycle_event_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    neutralized_ip_docket_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    neutralized_by_ip_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    neutralized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    company: Mapped[Company] = relationship()
    connection: Mapped[UserCalendarConnection] = relationship(back_populates="event_syncs")


class CalendarProjectionReconciliationCandidate(Base):
    """Immutable, content-minimised evidence for one external calendar drift.

    CaseOps remains authoritative for the underlying deadline/hearing/task.
    This row records only the projected event identity, its expected date and
    the provider's observable state; it never stores the provider event title,
    body, attendees or location.  A later human decision is therefore tied to
    exactly what the checker observed, rather than a mutable sync-row detail.
    """

    __tablename__ = "calendar_projection_reconciliation_candidates"
    __table_args__ = (
        UniqueConstraint(
            "calendar_event_sync_id",
            "snapshot_sha256",
            name="uq_calendar_projection_reconciliation_snapshot",
        ),
        CheckConstraint(
            "drift_status IN ('moved', 'missing', 'unknown')",
            name="ck_calendar_projection_reconciliation_drift_status",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'superseded')",
            name="ck_calendar_projection_reconciliation_status",
        ),
        CheckConstraint(
            "snapshot_schema_version > 0 AND length(snapshot_sha256) = 64",
            name="ck_calendar_projection_reconciliation_snapshot_identity",
        ),
        CheckConstraint(
            "(status IN ('pending', 'superseded') AND decided_at IS NULL "
            "AND decided_by_membership_id IS NULL AND decision_evidence_reference IS NULL) OR "
            "(status IN ('accepted', 'rejected') AND decided_at IS NOT NULL "
            "AND decided_by_membership_id IS NOT NULL AND decision_evidence_reference IS NOT NULL)",
            name="ck_calendar_projection_reconciliation_decision_evidence",
        ),
        Index(
            "ix_calendar_projection_reconciliation_company_status",
            "company_id",
            "status",
        ),
        Index(
            "ix_calendar_projection_reconciliation_sync",
            "calendar_event_sync_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    calendar_event_sync_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_event_syncs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    calendar_connection_id: Mapped[str] = mapped_column(
        ForeignKey("user_calendar_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ip_docket_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    drift_status: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expected_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    observed_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    detected_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    decided_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    decision_evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    calendar_event_sync: Mapped[CalendarEventSync] = relationship(
        foreign_keys=[calendar_event_sync_id]
    )


class UserMailboxConnection(Base):
    __tablename__ = "user_mailbox_connections"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "membership_id",
            "provider",
            name="uq_mailbox_connections_company_membership_provider",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MailboxProvider.GMAIL,
    )
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MailboxConnectionStatus.CONNECTED,
        index=True,
    )
    encrypted_token_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    last_history_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    watch_resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    watch_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_import_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    company: Mapped[Company] = relationship()
    membership: Mapped[CompanyMembership] = relationship()
    message_imports: Mapped[list[MailboxMessageImport]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
    )


class UserDriveConnection(Base):
    __tablename__ = "user_drive_connections"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "membership_id",
            "provider",
            name="uq_drive_connections_company_membership_provider",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DriveProvider.GOOGLE_DRIVE,
    )
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DriveConnectionStatus.CONNECTED,
        index=True,
    )
    encrypted_token_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_list_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    company: Mapped[Company] = relationship()
    membership: Mapped[CompanyMembership] = relationship()


class MailboxMessageImport(Base):
    __tablename__ = "mailbox_message_imports"
    __table_args__ = (
        UniqueConstraint(
            "mailbox_connection_id",
            "provider_message_id",
            name="uq_mailbox_message_import_connection_message",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mailbox_connection_id: Mapped[str] = mapped_column(
        ForeignKey("user_mailbox_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    communication_id: Mapped[str | None] = mapped_column(
        ForeignKey("communications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    history_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sender_email_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snippet: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    labels_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MailboxImportStatus.UNMATCHED,
        index=True,
    )
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_letter_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
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

    company: Mapped[Company] = relationship()
    connection: Mapped[UserMailboxConnection] = relationship(back_populates="message_imports")
    matter: Mapped[Matter | None] = relationship()
    communication: Mapped[Communication | None] = relationship()
    attachment_candidates: Mapped[list[MailboxAttachmentCandidate]] = relationship(
        back_populates="message_import",
        cascade="all, delete-orphan",
    )


class MailboxAttachmentCandidate(Base):
    __tablename__ = "mailbox_attachment_candidates"
    __table_args__ = (
        UniqueConstraint(
            "message_import_id",
            "provider_attachment_ref_hash",
            name="uq_mailbox_attachment_candidate_message_ref",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_import_id: Mapped[str] = mapped_column(
        ForeignKey("mailbox_message_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_attachment_ref_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_provider_attachment_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imported_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MailboxAttachmentCandidateStatus.NEEDS_REVIEW,
        index=True,
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

    message_import: Mapped[MailboxMessageImport] = relationship(
        back_populates="attachment_candidates"
    )
    matter: Mapped[Matter | None] = relationship()
    imported_attachment: Mapped[MatterAttachment | None] = relationship()


class MailboxWebhookEvent(Base):
    __tablename__ = "mailbox_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "history_id",
            "email_address_hash",
            name="uq_mailbox_webhook_provider_history_address",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    mailbox_connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_mailbox_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MailboxProvider.GMAIL,
        index=True,
    )
    history_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    email_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MailboxWebhookStatus.QUEUED,
        index=True,
    )
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    company: Mapped[Company | None] = relationship()
    connection: Mapped[UserMailboxConnection | None] = relationship()


class ConnectorHealthRecord(Base):
    __tablename__ = "connector_health_records"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "provider",
            "account_ref_hash",
            name="uq_connector_health_tenant_provider_account",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account_ref_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="tenant")
    account_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    configured_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectorHealthStatus.MISSING_CONFIG,
        index=True,
    )
    connected_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectorHealthStatus.DISABLED,
        index=True,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    required_scopes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    granted_scopes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    token_refresh_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    webhook_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    polling_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rate_limit_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operational_alerts_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    setup_actions_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
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

    company: Mapped[Company] = relationship()


class TenantMicrosoft365Configuration(Base):
    __tablename__ = "tenant_microsoft365_configurations"
    __table_args__ = (UniqueConstraint("company_id", name="uq_tenant_microsoft365_config_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_client_secret_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scopes_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    admin_consent_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scopes_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mail_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    calendar_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    drive_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_run")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship()


class DriveSyncControl(Base):
    __tablename__ = "drive_sync_controls"
    __table_args__ = (
        UniqueConstraint("company_id", "provider", name="uq_drive_sync_controls_tenant_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DriveProvider.GOOGLE_DRIVE,
        index=True,
    )
    allowed_folders_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    blocked_folders_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    max_file_size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=25 * 1024 * 1024
    )
    allowed_mime_types_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="review_import")
    auto_import_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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

    company: Mapped[Company] = relationship()


class DriveFileCandidate(Base):
    __tablename__ = "drive_file_candidates"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "provider",
            "provider_file_id",
            "provider_version",
            name="uq_drive_file_candidates_provider_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    drive_connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_drive_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DriveProvider.GOOGLE_DRIVE,
        index=True,
    )
    provider_file_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider_version: Mapped[str] = mapped_column(String(120), nullable=False, default="metadata")
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_display: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    folder_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    web_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    suggested_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ReviewCandidateStatus.NEW,
        index=True,
    )
    imported_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    linked_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    company: Mapped[Company] = relationship()
    connection: Mapped[UserDriveConnection | None] = relationship()
    suggested_matter: Mapped[Matter | None] = relationship(foreign_keys=[suggested_matter_id])
    linked_matter: Mapped[Matter | None] = relationship(foreign_keys=[linked_matter_id])
    imported_attachment: Mapped[MatterAttachment | None] = relationship()


class CalendarEventCandidate(Base):
    __tablename__ = "calendar_event_candidates"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "provider",
            "provider_event_id",
            name="uq_calendar_event_candidates_provider_event",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    calendar_connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_calendar_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    i_cal_uid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    organizer_display: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    suggested_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    linked_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    linked_hearing_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_hearings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CalendarEventCandidateStatus.NEW,
        index=True,
    )
    conflict_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sync_history_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    company: Mapped[Company] = relationship()
    connection: Mapped[UserCalendarConnection | None] = relationship()
    suggested_matter: Mapped[Matter | None] = relationship(foreign_keys=[suggested_matter_id])
    linked_matter: Mapped[Matter | None] = relationship(foreign_keys=[linked_matter_id])
    linked_hearing: Mapped[MatterHearing | None] = relationship()
    reviewed_by_membership: Mapped[CompanyMembership | None] = relationship()


class InboundEmailAlias(Base):
    __tablename__ = "inbound_email_aliases"
    __table_args__ = (
        UniqueConstraint("company_id", "alias_address", name="uq_inbound_alias_tenant_address"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    alias_type: Mapped[str] = mapped_column(String(24), nullable=False, default="tenant")
    alias_address: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=InboundEmailAliasStatus.DISABLED,
        index=True,
    )
    allowed_senders_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    allowed_domains_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    spam_security_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="provider_unverified"
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship()
    matter: Mapped[Matter | None] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship()


class InboundEmailEvent(Base):
    __tablename__ = "inbound_email_events"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "provider_message_id",
            name="uq_inbound_email_event_tenant_provider_message",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias_id: Mapped[str | None] = mapped_column(
        ForeignKey("inbound_email_aliases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    matched_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="local_safe")
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    from_address_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    from_display: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_addresses_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    cc_addresses_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snippet: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attachment_metadata_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=InboundEmailEventStatus.NEW,
        index=True,
    )
    redacted_failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    communication_id: Mapped[str | None] = mapped_column(
        ForeignKey("communications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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

    company: Mapped[Company] = relationship()
    alias: Mapped[InboundEmailAlias | None] = relationship()
    matched_matter: Mapped[Matter | None] = relationship(foreign_keys=[matched_matter_id])
    linked_matter: Mapped[Matter | None] = relationship(foreign_keys=[linked_matter_id])
    communication: Mapped[Communication | None] = relationship()


class TenantNotificationPreference(Base):
    __tablename__ = "tenant_notification_preferences"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_tenant_notification_preferences_company"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channels_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    event_categories_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    digest_frequency: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=NotificationDigestFrequency.IMMEDIATE,
    )
    quiet_hours_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    escalation_rules_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    external_delivery_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="disabled_until_configured"
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

    company: Mapped[Company] = relationship()


class UserNotificationPreference(Base):
    __tablename__ = "user_notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "membership_id",
            name="uq_user_notification_preferences_membership",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channels_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    event_categories_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    digest_frequency: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=NotificationDigestFrequency.IMMEDIATE,
    )
    quiet_hours_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    escalation_rules_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    opt_out_categories_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
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

    company: Mapped[Company] = relationship()
    membership: Mapped[CompanyMembership] = relationship()


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    channels_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship()


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_membership_id",
            "event_type",
            "source_type",
            "source_id",
            name="uq_in_app_notification_recipient_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=InAppNotificationStatus.UNREAD,
        index=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship()
    recipient_membership: Mapped[CompanyMembership] = relationship()
    matter: Mapped[Matter | None] = relationship()


class NotificationDeliveryIntent(Base):
    __tablename__ = "notification_delivery_intents"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "idempotency_key",
            name="uq_notification_delivery_intent_idempotency",
        ),
        CheckConstraint(
            "(CASE WHEN recipient_membership_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN recipient_portal_user_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN recipient_external_ref IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_notification_delivery_exactly_one_recipient",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_notification_delivery_ip_docket_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "matter_id IS NULL OR ip_docket_id IS NULL",
            name="ck_notification_delivery_at_most_one_work_target",
        ),
        ForeignKeyConstraint(
            [
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                "ip_docket_id",
                "neutralized_by_ip_lifecycle_version",
            ],
            [
                "ip_docket_events.id",
                "ip_docket_events.company_id",
                "ip_docket_events.docket_id",
                "ip_docket_events.resulting_lifecycle_version",
            ],
            name="fk_notification_delivery_neutralized_event_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_by_ip_lifecycle_version IS NULL AND neutralized_at IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_by_ip_lifecycle_version IS NOT NULL AND neutralized_at IS NOT NULL "
            "AND company_id IS NOT NULL)",
            name="ck_notification_delivery_ip_lifecycle_provenance_complete",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_version IS NULL OR "
            "neutralized_by_ip_lifecycle_version > 0",
            name="ck_notification_delivery_ip_lifecycle_version_positive",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR status IN ('blocked', 'cancelled')",
            name="ck_notification_delivery_ip_lifecycle_terminal_state",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR ip_docket_id IS NOT NULL",
            name="ck_notification_delivery_ip_lifecycle_provenance_target",
        ),
        Index(
            "ix_notification_intents_ip_lifecycle_event",
            "neutralized_by_ip_lifecycle_event_id",
            "company_id",
            "ip_docket_id",
            "neutralized_by_ip_lifecycle_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recipient_portal_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipient_external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    destination_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notification_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("notification_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    in_app_notification_id: Mapped[str | None] = mapped_column(
        ForeignKey("in_app_notifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=NotificationDeliveryStatus.QUEUED,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    critical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    escalation_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    confidentiality_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="minimal")
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_letter_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    schedule_source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    schedule_source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recipient_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dispatch_owner: Mapped[str] = mapped_column(
        String(32), nullable=False, default="durable_intent"
    )
    comparison_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_run")
    suppression_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    fallback_intent_id: Mapped[str | None] = mapped_column(
        ForeignKey("notification_delivery_intents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    superseded_by_intent_id: Mapped[str | None] = mapped_column(
        ForeignKey("notification_delivery_intents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recovery_of_intent_id: Mapped[str | None] = mapped_column(
        ForeignKey("notification_delivery_intents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider_state_occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    neutralized_by_ip_lifecycle_event_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    neutralized_by_ip_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    neutralized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    company: Mapped[Company] = relationship()
    recipient_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[recipient_membership_id]
    )
    matter: Mapped[Matter | None] = relationship()
    notification_rule: Mapped[NotificationRule | None] = relationship()
    in_app_notification: Mapped[InAppNotification | None] = relationship()


class NotificationDeliveryEvent(Base):
    __tablename__ = "notification_delivery_events"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "provider",
            "provider_event_id",
            name="uq_notification_delivery_provider_event",
        ),
        Index("ix_notification_delivery_events_intent_time", "intent_id", "occurred_at"),
        UniqueConstraint(
            "company_id",
            "provider",
            "idempotency_key",
            name="uq_notification_delivery_event_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("notification_delivery_intents.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    applied_to_state: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    error_redacted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class HearingReminderDeliveryIntent(Base):
    """Compatibility lineage from a legacy schedule row to durable delivery truth."""

    __tablename__ = "hearing_reminder_delivery_intents"
    __table_args__ = (
        UniqueConstraint("hearing_reminder_id", "intent_id", name="uq_hearing_reminder_intent"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    hearing_reminder_id: Mapped[str] = mapped_column(
        ForeignKey("hearing_reminders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("notification_delivery_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class JudgmentAlertRule(Base):
    __tablename__ = "judgment_alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    query_terms_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    forum_level: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    judge_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    practice_area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    statute_terms_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    document_types_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    since_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    until_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    company: Mapped[Company] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship()
    alerts: Mapped[list[JudgmentAlert]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
    )


class JudgmentAlert(Base):
    __tablename__ = "judgment_alerts"
    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "authority_document_id",
            name="uq_judgment_alert_rule_authority",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("judgment_alert_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    authority_document_id: Mapped[str] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    match_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    snippet: Mapped[str | None] = mapped_column(String(280), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    company: Mapped[Company] = relationship()
    rule: Mapped[JudgmentAlertRule] = relationship(back_populates="alerts")
    authority_document: Mapped[AuthorityDocument] = relationship()


class LegalUpdateWatchlist(Base):
    __tablename__ = "legal_update_watchlists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    practice_area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    statute_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("statutes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    jurisdiction: Mapped[str | None] = mapped_column(String(120), nullable=True)
    statute_terms_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    source_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    source_category: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    update_types_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    since_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    until_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contract_id: Mapped[str | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    company: Mapped[Company] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship()
    statute: Mapped[Statute | None] = relationship("Statute")
    matter: Mapped[Matter | None] = relationship("Matter")
    contract: Mapped[Contract | None] = relationship("Contract")
    alerts: Mapped[list[LegalUpdateAlert]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
    )


class LegalUpdateAlert(Base):
    __tablename__ = "legal_update_alerts"
    __table_args__ = (
        UniqueConstraint(
            "watchlist_id",
            "source_record_key",
            name="uq_legal_update_watchlist_source_record",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    watchlist_id: Mapped[str] = mapped_column(
        ForeignKey("legal_update_watchlists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_record_key: Mapped[str] = mapped_column(String(160), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("legal_update_source_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    update_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    statute_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("statutes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    statute_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("statute_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    authority_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contract_id: Mapped[str | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    statute_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provenance_status: Mapped[str] = mapped_column(String(80), nullable=False)
    relevance_explanation: Mapped[str] = mapped_column(String(500), nullable=False)
    snippet: Mapped[str | None] = mapped_column(String(280), nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    decision_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    company: Mapped[Company] = relationship()
    watchlist: Mapped[LegalUpdateWatchlist] = relationship(back_populates="alerts")
    source_record: Mapped[LegalUpdateSourceRecord | None] = relationship("LegalUpdateSourceRecord")
    statute: Mapped[Statute | None] = relationship("Statute")
    statute_section: Mapped[StatuteSection | None] = relationship("StatuteSection")
    authority_document: Mapped[AuthorityDocument | None] = relationship("AuthorityDocument")
    matter: Mapped[Matter | None] = relationship("Matter")
    contract: Mapped[Contract | None] = relationship("Contract")


class LegalUpdateSourceRun(Base):
    __tablename__ = "legal_update_source_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LegalUpdateSourceRecord(Base):
    __tablename__ = "legal_update_source_records"
    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "source_record_key",
            name="uq_legal_update_source_records_source_record",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_record_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    update_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String(800), nullable=False)
    source_document_url: Mapped[str | None] = mapped_column(String(800), nullable=True)
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    act_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    statute_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("statutes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    statute_section_ids_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    sections_changed_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    source_category: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    provenance_status: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        index=True,
    )
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
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

    statute: Mapped[Statute | None] = relationship("Statute")
    model_run: Mapped[ModelRun | None] = relationship("ModelRun")


class StatuteChangeEvent(Base):
    __tablename__ = "statute_change_events"
    __table_args__ = (
        UniqueConstraint(
            "statute_id",
            "source_record_id",
            "change_type",
            name="uq_statute_change_events_source_change",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    statute_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("statutes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_record_id: Mapped[str] = mapped_column(
        ForeignKey("legal_update_source_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    change_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    sections_changed_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    comparison_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(String(800), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    statute: Mapped[Statute] = relationship("Statute")
    source_record: Mapped[LegalUpdateSourceRecord] = relationship("LegalUpdateSourceRecord")


class TrackedCase(Base):
    __tablename__ = "tracked_cases"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "provider",
            "identity_key",
            name="uq_tracked_cases_provider_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    identity_key: Mapped[str] = mapped_column(String(260), nullable=False, index=True)
    cnr_number: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    normalized_cnr_number: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    case_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalized_case_number: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        index=True,
    )
    court_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    case_title: Mapped[str] = mapped_column(String(500), nullable=False)
    party_names_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    current_status: Mapped[str | None] = mapped_column(String(160), nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(160), nullable=True)
    next_hearing_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_provider_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_provider_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_provider_successful_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    next_provider_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    provider_freshness_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="never_succeeded", index=True
    )
    last_response_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_reason_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_provider_refresh_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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

    company: Mapped[Company] = relationship()
    bookmarks: Mapped[list[TrackedCaseBookmark]] = relationship(
        back_populates="tracked_case",
        cascade="all, delete-orphan",
    )
    updates: Mapped[list[TrackedCaseUpdate]] = relationship(
        back_populates="tracked_case",
        cascade="all, delete-orphan",
    )
    provider_operations: Mapped[list[TrackedCaseProviderOperation]] = relationship(
        back_populates="tracked_case", cascade="all, delete-orphan"
    )
    provider_snapshots: Mapped[list[TrackedCaseProviderSnapshot]] = relationship(
        back_populates="tracked_case", cascade="all, delete-orphan"
    )


class TrackedCaseBookmark(Base):
    __tablename__ = "tracked_case_bookmarks"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "tracked_case_id",
            "created_by_membership_id",
            "active_scope_key",
            name="uq_tracked_case_bookmarks_active_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tracked_case_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scope_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    active_scope_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notification_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship()
    tracked_case: Mapped[TrackedCase] = relationship(back_populates="bookmarks")
    created_by_membership: Mapped[CompanyMembership] = relationship()
    matter: Mapped[Matter | None] = relationship("Matter")


class TrackedCaseUpdate(Base):
    __tablename__ = "tracked_case_updates"
    __table_args__ = (
        UniqueConstraint(
            "tracked_case_id",
            "source_record_key",
            "update_type",
            name="uq_tracked_case_updates_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tracked_case_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    update_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_record_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(800), nullable=True)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    hearing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship()
    tracked_case: Mapped[TrackedCase] = relationship(back_populates="updates")
    model_run: Mapped[ModelRun | None] = relationship("ModelRun")


class TrackedCasePollRun(Base):
    __tablename__ = "tracked_case_poll_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    update_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backlog_remaining_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    company: Mapped[Company | None] = relationship()


class TrackedCaseProviderOperation(Base):
    """Durable, tenant-scoped provider work for one tracked case."""

    __tablename__ = "tracked_case_provider_operations"
    __table_args__ = (
        UniqueConstraint("company_id", "correlation_id", name="uq_tracking_operation_correlation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracked_case_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    poll_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("tracked_case_poll_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requested_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    response_class: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_reason_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    tracked_case: Mapped[TrackedCase] = relationship(back_populates="provider_operations")
    snapshots: Mapped[list[TrackedCaseProviderSnapshot]] = relationship(
        back_populates="operation", cascade="all, delete-orphan"
    )


class TrackedCaseProviderSnapshot(Base):
    """Append-only provider evidence and normalized diff for one operation."""

    __tablename__ = "tracked_case_provider_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracked_case_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("tracked_case_provider_operations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    normalized_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    diff_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(800), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    tracked_case: Mapped[TrackedCase] = relationship(back_populates="provider_snapshots")
    operation: Mapped[TrackedCaseProviderOperation] = relationship(back_populates="snapshots")


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
    # Slice B (MOD-TS-001-C, 2026-04-25). JSON array of resolved
    # bench members produced by services.bench_resolver. Shape:
    #   [{"judge_id": "...", "matched_alias": "...", "confidence": "..."}, ...]
    # NULL = not yet processed by the resolver. "[]" = processed but
    # no judge in the catalog matched at the high-quality floor —
    # surfaces in the ops dashboard for review.
    judges_json: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    sync_run: Mapped[MatterCourtSyncRun | None] = relationship(back_populates="cause_list_entries")


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
    bench_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    judge_names_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    order_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    order_kind: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        default=MatterCourtOrderKind.DAILY_ORDER,
    )
    is_interim_order: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    stay_status: Mapped[str | None] = mapped_column(
        String(24),
        nullable=True,
        index=True,
        default=MatterStayStatus.NONE,
    )
    stay_effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
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
    order_attachment: Mapped[MatterAttachment | None] = relationship(
        foreign_keys=[order_attachment_id]
    )
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


class MatterProceedingSignal(Base):
    """Structured proceeding/order-sheet extraction tied to a source order.

    LI-S1 keeps this matter-native: source lineage remains on
    ``MatterCourtOrder``/``MatterCourtSyncRun`` and generated work lands in
    the existing task/deadline tables.
    """

    __tablename__ = "matter_proceeding_signals"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "matter_id",
            "court_order_id",
            "dedupe_key",
            name="uq_matter_proceeding_signal_order_key",
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
    court_order_id: Mapped[str] = mapped_column(
        ForeignKey("matter_court_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_court_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signal_text: Mapped[str] = mapped_column(Text, nullable=False)
    action_required: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    hearing_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    order_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence_label: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MatterProceedingConfidence.LOW,
    )
    source_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MatterProceedingReviewStatus.REVIEW_REQUIRED,
        index=True,
    )
    generated_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generated_deadline_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_deadlines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    extraction_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="deterministic",
    )
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
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


class MatterComplianceExtractionRun(Base):
    __tablename__ = "matter_compliance_extraction_runs"

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
    court_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_court_orders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterComplianceExtractionStatus.QUEUED,
        index=True,
    )
    skip_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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

    matter: Mapped[Matter] = relationship(back_populates="compliance_extraction_runs")
    court_order: Mapped[MatterCourtOrder | None] = relationship()
    attachment: Mapped[MatterAttachment | None] = relationship()
    model_run: Mapped[ModelRun | None] = relationship("ModelRun")
    created_by_membership: Mapped[CompanyMembership | None] = relationship()
    items: Mapped[list[MatterComplianceItem]] = relationship(
        back_populates="extraction_run",
        cascade="all, delete-orphan",
        order_by="MatterComplianceItem.created_at.asc()",
    )


class MatterComplianceItem(Base):
    __tablename__ = "matter_compliance_items"
    __table_args__ = (
        UniqueConstraint(
            "matter_id",
            "court_order_id",
            "dedupe_key",
            name="uq_matter_compliance_order_key",
        ),
        UniqueConstraint(
            "matter_id",
            "attachment_id",
            "dedupe_key",
            name="uq_matter_compliance_attachment_key",
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
    court_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_court_orders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("matter_compliance_extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    timeline_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filing_requirement: Mapped[str | None] = mapped_column(String(500), nullable=True)
    court_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_paragraph: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confidence_label: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MatterProceedingConfidence.LOW,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterComplianceStatus.PENDING,
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MatterComplianceReviewStatus.REVIEW_REQUIRED,
        index=True,
    )
    generated_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generated_deadline_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_deadlines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dedupe_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    waived_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    matter: Mapped[Matter] = relationship(back_populates="compliance_items")
    court_order: Mapped[MatterCourtOrder | None] = relationship()
    attachment: Mapped[MatterAttachment | None] = relationship()
    extraction_run: Mapped[MatterComplianceExtractionRun] = relationship(back_populates="items")
    generated_task: Mapped[MatterTask | None] = relationship(foreign_keys=[generated_task_id])
    generated_deadline: Mapped[MatterDeadline | None] = relationship(
        foreign_keys=[generated_deadline_id],
    )
    reviewed_by_membership: Mapped[CompanyMembership | None] = relationship()


class MatterNextHearingHistory(Base):
    __tablename__ = "matter_next_hearing_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_next_hearing_history_matter_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_next_hearing_history_ip_docket_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_next_hearing_history_exactly_one_target",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    old_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    new_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_lock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter | None] = relationship(
        back_populates="next_hearing_history", foreign_keys=[matter_id]
    )
    changed_by_membership: Mapped[CompanyMembership | None] = relationship()


class MatterNextHearingSuggestion(Base):
    __tablename__ = "matter_next_hearing_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "matter_id",
            "suggested_date",
            "source",
            "source_ref_type",
            "source_ref_id",
            name="uq_matter_next_hearing_suggestion_source",
        ),
        UniqueConstraint(
            "ip_docket_id",
            "suggested_date",
            "source",
            "source_ref_type",
            "source_ref_id",
            name="uq_ip_next_hearing_suggestion_source",
        ),
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_next_hearing_suggestion_matter_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_next_hearing_suggestion_ip_docket_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_next_hearing_suggestion_exactly_one_target",
        ),
        ForeignKeyConstraint(
            [
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                "ip_docket_id",
                "neutralized_by_ip_lifecycle_version",
            ],
            [
                "ip_docket_events.id",
                "ip_docket_events.company_id",
                "ip_docket_events.docket_id",
                "ip_docket_events.resulting_lifecycle_version",
            ],
            name="fk_next_hearing_suggestion_neutralized_event_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_by_ip_lifecycle_version IS NULL AND neutralized_at IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_by_ip_lifecycle_version IS NOT NULL AND neutralized_at IS NOT NULL "
            "AND company_id IS NOT NULL)",
            name="ck_next_hearing_suggestion_ip_lifecycle_provenance_complete",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_version IS NULL OR "
            "neutralized_by_ip_lifecycle_version > 0",
            name="ck_next_hearing_suggestion_ip_lifecycle_version_positive",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR status = 'rejected'",
            name="ck_next_hearing_suggestion_ip_lifecycle_terminal_state",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR ip_docket_id IS NOT NULL",
            name="ck_next_hearing_suggestion_ip_lifecycle_provenance_target",
        ),
        Index(
            "ix_next_hearing_suggestions_ip_lifecycle_event",
            "neutralized_by_ip_lifecycle_event_id",
            "company_id",
            "ip_docket_id",
            "neutralized_by_ip_lifecycle_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    suggested_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    existing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence_label: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterNextHearingSuggestionStatus.PENDING,
        index=True,
    )
    decided_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    neutralized_by_ip_lifecycle_event_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    neutralized_by_ip_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    neutralized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    matter: Mapped[Matter | None] = relationship(
        back_populates="next_hearing_suggestions", foreign_keys=[matter_id]
    )
    decided_by_membership: Mapped[CompanyMembership | None] = relationship()


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
    document_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    notice_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notice_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notice_received_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    notice_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_direction: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    notice_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notice_mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notice_authority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notice_received_from: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notice_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notice_department: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notice_internal_spoc: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notice_internal_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notice_dispute_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notice_recovered_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notice_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    notice_reply_due_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    notice_reply_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notice_reply_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notice_reply_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_counsel_engaged: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notice_parent_attachment_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    notice_document_role: Mapped[str] = mapped_column(String(24), nullable=False, default="notice")
    notice_reply_deadline_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    notice_reminder_offsets_json: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    sequence_index: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    linked_court_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_court_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # BUG-045 (Hari 2026-05-11): link evidence to a specific hearing.
    # Nullable + SET NULL so legacy attachments are unaffected and
    # deleting a hearing doesn't cascade-delete its evidence.
    hearing_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_hearings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    linked_court_order: Mapped[MatterCourtOrder | None] = relationship(
        foreign_keys=[linked_court_order_id]
    )
    hearing: Mapped[MatterHearing | None] = relationship(foreign_keys=[hearing_id])


class CompanyNotice(Base):
    """Tenant-owned notice metadata with an optional document.

    Notices used to exist only as ``MatterAttachment`` rows, which made both a
    matter and a file mandatory.  This model is the standalone source of truth
    for the company-wide notice register; legacy attachment notices remain
    readable through the notice service during the transition.
    """

    __tablename__ = "company_notices"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('received', 'sent')",
            name="ck_company_notices_direction",
        ),
        CheckConstraint(
            "amount_minor IS NULL OR amount_minor >= 0",
            name="ck_company_notices_amount_nonnegative",
        ),
        CheckConstraint(
            "dispute_amount_minor IS NULL OR dispute_amount_minor >= 0",
            name="ck_company_notices_dispute_amount_nonnegative",
        ),
        CheckConstraint(
            "recovered_amount_minor IS NULL OR recovered_amount_minor >= 0",
            name="ck_company_notices_recovered_amount_nonnegative",
        ),
        CheckConstraint(
            "length(currency) = 3",
            name="ck_company_notices_currency_length",
        ),
        CheckConstraint(
            "reply_sent_on IS NULL OR (reply_sent = true AND reply_required = true)",
            name="ck_company_notices_reply_sent_date_state",
        ),
        CheckConstraint(
            "(direction = 'received' AND sent_on IS NULL) OR "
            "(direction = 'sent' AND received_on IS NULL "
            "AND received_from IS NULL AND reply_due_on IS NULL "
            "AND reply_required = false AND reply_sent = false "
            "AND reply_sent_on IS NULL)",
            name="ck_company_notices_direction_fields_consistent",
        ),
        CheckConstraint(
            "reply_sent = false OR reply_required = true",
            name="ck_company_notices_reply_sent_requires_required",
        ),
        CheckConstraint(
            "reply_due_on IS NULL OR reply_required = true",
            name="ck_company_notices_reply_due_requires_required",
        ),
        CheckConstraint(
            "(storage_key IS NULL AND original_filename IS NULL "
            "AND content_type IS NULL AND size_bytes IS NULL "
            "AND sha256_hex IS NULL) OR "
            "(storage_key IS NOT NULL AND original_filename IS NOT NULL "
            "AND size_bytes IS NOT NULL AND size_bytes >= 0 "
            "AND sha256_hex IS NOT NULL)",
            name="ck_company_notices_file_metadata_state",
        ),
        ForeignKeyConstraint(
            ["owner_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_company_notices_owner_membership_company",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_company_notices_creator_membership_company",
        ),
        UniqueConstraint(
            "id",
            "company_id",
            name="uq_company_notices_id_company_id",
        ),
        UniqueConstraint("storage_key", name="uq_company_notices_storage_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_by_membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    direction: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="received",
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    notice_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, default="Open", index=True)
    authority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(160), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    internal_spoc: Mapped[str | None] = mapped_column(String(160), nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    counsel_engaged: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    sent_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    reply_due_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    reply_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    reply_sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    reply_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dispute_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recovered_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256_hex: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship()
    owner_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[owner_membership_id]
    )
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id]
    )
    matter_links: Mapped[list[CompanyNoticeMatterLink]] = relationship(
        back_populates="notice",
        cascade="all, delete-orphan",
        order_by="CompanyNoticeMatterLink.created_at.asc()",
        overlaps="company,matter",
    )


class CompanyNoticeMatterLink(Base):
    """Many-to-many link between a standalone notice and tenant matters."""

    __tablename__ = "company_notice_matter_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["notice_id", "company_id"],
            ["company_notices.id", "company_notices.company_id"],
            name="fk_company_notice_links_notice_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_company_notice_links_matter_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "notice_id",
            "matter_id",
            name="uq_company_notice_matter_link",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notice_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    company: Mapped[Company] = relationship(
        overlaps="matter,matter_links,notice",
    )
    notice: Mapped[CompanyNotice] = relationship(
        back_populates="matter_links",
        overlaps="company,matter",
    )
    matter: Mapped[Matter] = relationship(
        overlaps="company,matter_links,notice",
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


class AffidavitIntelligenceRun(Base):
    """Matter-private affidavit hearing-prep extraction run.

    LI-S2 keeps every output anchored to a matter attachment and, where
    available, its raw extracted chunks. Runs are versioned so re-analysis does
    not mutate historical reviewer context.
    """

    __tablename__ = "affidavit_intelligence_runs"

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
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AffidavitIntelligenceRunStatus.NO_FINDINGS,
        index=True,
    )
    extraction_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="deterministic",
    )
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_data_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)
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

    statements: Mapped[list[AffidavitStatement]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AffidavitStatement.created_at.asc()",
    )
    questions: Mapped[list[AffidavitQuestion]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AffidavitQuestion.created_at.asc()",
    )


class AffidavitStatement(Base):
    __tablename__ = "affidavit_statements"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "dedupe_key",
            name="uq_affidavit_statement_run_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("affidavit_intelligence_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachment_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    statement_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    statement_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_label: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MatterProceedingConfidence.LOW,
    )
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AffidavitIntelligenceReviewStatus.REVIEW_REQUIRED,
        index=True,
    )
    dedupe_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
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

    run: Mapped[AffidavitIntelligenceRun] = relationship(back_populates="statements")


class AffidavitQuestion(Base):
    __tablename__ = "affidavit_questions"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "dedupe_key",
            name="uq_affidavit_question_run_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("affidavit_intelligence_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statement_id: Mapped[str | None] = mapped_column(
        ForeignKey("affidavit_statements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachment_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_label: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MatterProceedingConfidence.LOW,
    )
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AffidavitIntelligenceReviewStatus.REVIEW_REQUIRED,
        index=True,
    )
    dedupe_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
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

    run: Mapped[AffidavitIntelligenceRun] = relationship(back_populates="questions")


class MockHearingSession(Base):
    """Text-first mock hearing session built from source-backed affidavit questions."""

    __tablename__ = "mock_hearing_sessions"

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
    source_affidavit_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("affidavit_intelligence_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=MockHearingMode.CLIENT_PREPARATION,
        index=True,
    )
    participant_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MockHearingSessionStatus.ACTIVE,
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MockHearingReviewStatus.REVIEW_REQUIRED,
        index=True,
    )
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)
    scorecard_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answered_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_assertion_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    missing_document_reference_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_required_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_response_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    questions: Mapped[list[MockHearingQuestion]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MockHearingQuestion.turn_index.asc()",
    )
    responses: Mapped[list[MockHearingResponse]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MockHearingResponse.created_at.asc()",
    )


class MockHearingQuestion(Base):
    __tablename__ = "mock_hearing_questions"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "turn_index",
            name="uq_mock_hearing_question_session_turn",
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
    session_id: Mapped[str] = mapped_column(
        ForeignKey("mock_hearing_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_affidavit_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("affidavit_intelligence_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_affidavit_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("affidavit_questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_affidavit_statement_id: Mapped[str | None] = mapped_column(
        ForeignKey("affidavit_statements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachment_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty_label: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MockHearingQuestionStatus.PENDING,
        index=True,
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

    session: Mapped[MockHearingSession] = relationship(back_populates="questions")
    responses: Mapped[list[MockHearingResponse]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="MockHearingResponse.created_at.asc()",
    )


class MockHearingResponse(Base):
    __tablename__ = "mock_hearing_responses"

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
    session_id: Mapped[str] = mapped_column(
        ForeignKey("mock_hearing_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[str] = mapped_column(
        ForeignKey("mock_hearing_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_affidavit_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("affidavit_questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answered_question: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consistency_with_affidavit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    unsupported_assertion_added: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    missing_document_reference: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    contradiction_with_source: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    response_completeness: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    confidence_label: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MockHearingReviewStatus.REVIEW_REQUIRED,
        index=True,
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

    session: Mapped[MockHearingSession] = relationship(back_populates="responses")
    question: Mapped[MockHearingQuestion] = relationship(back_populates="responses")


class LitigationIntelligenceReviewAction(Base):
    """Human review action for an LI review-queue item.

    LI-S9 keeps source records authoritative and stores the lawyer's queue
    action as a tenant/matter-scoped ledger so predictive/bench items that do
    not have their own review_status column can still be marked reviewed.
    """

    __tablename__ = "litigation_intelligence_review_actions"
    __table_args__ = (
        CheckConstraint(
            "item_type in ("
            "'proceeding_signal', 'affidavit_statement', 'affidavit_question', "
            "'mock_hearing_session', 'mock_hearing_response', 'predictive_signal', "
            "'bench_context'"
            ")",
            name="ck_li_review_actions_item_type",
        ),
        CheckConstraint(
            "source_type in ("
            "'matter_proceeding_signal', 'affidavit_statement', 'affidavit_question', "
            "'mock_hearing_session', 'mock_hearing_response', 'predictive_signal_item', "
            "'predictive_signal_run'"
            ")",
            name="ck_li_review_actions_source_type",
        ),
        CheckConstraint(
            "action in ('mark_reviewed', 'accept', 'reject', 'edit_note')",
            name="ck_li_review_actions_action",
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
    item_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_before: Mapped[str] = mapped_column(String(64), nullable=False)
    status_after: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        index=True,
    )


class LegalKnowledgeGraphRun(Base):
    """Matter-scoped source-backed legal knowledge graph materialization run."""

    __tablename__ = "legal_knowledge_graph_runs"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "matter_id",
            name="uq_legal_knowledge_graph_run_matter",
        ),
        CheckConstraint(
            "status in ('completed', 'no_source_records')",
            name="ck_legal_knowledge_graph_runs_status",
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
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=LegalKnowledgeGraphRunStatus.NO_SOURCE_RECORDS,
        index=True,
    )
    source_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_data_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    limitation_note: Mapped[str] = mapped_column(Text, nullable=False)
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)
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

    nodes: Mapped[list[LegalKnowledgeGraphNode]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="LegalKnowledgeGraphNode.created_at.asc()",
    )
    edges: Mapped[list[LegalKnowledgeGraphEdge]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="LegalKnowledgeGraphEdge.created_at.asc()",
    )


class LegalKnowledgeGraphNode(Base):
    __tablename__ = "legal_knowledge_graph_nodes"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "node_key",
            name="uq_legal_knowledge_graph_node_run_key",
        ),
        CheckConstraint(
            "node_type in ("
            "'matter', 'proceeding_signal', 'affidavit_statement', "
            "'affidavit_question', 'mock_hearing_question', 'mock_hearing_response', "
            "'predictive_signal', 'bench_context', 'legal_source', "
            "'statute_or_issue', 'review_action'"
            ")",
            name="ck_legal_knowledge_graph_nodes_node_type",
        ),
        CheckConstraint(
            "source_type in ("
            "'matter', 'matter_court_order', 'matter_proceeding_signal', "
            "'matter_document', 'matter_attachment_chunk', 'affidavit_statement', "
            "'affidavit_question', 'mock_hearing_session', 'mock_hearing_question', "
            "'mock_hearing_response', 'predictive_signal_item', 'predictive_signal_run', "
            "'authority_document', 'aggregate_snapshot', "
            "'litigation_intelligence_review_action', 'unavailable'"
            ")",
            name="ck_legal_knowledge_graph_nodes_source_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("legal_knowledge_graph_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    node_key: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    limitation_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    run: Mapped[LegalKnowledgeGraphRun] = relationship(back_populates="nodes")


class LegalKnowledgeGraphEdge(Base):
    __tablename__ = "legal_knowledge_graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "from_node_id",
            "to_node_id",
            "edge_type",
            "source_type",
            "source_id",
            name="uq_legal_knowledge_graph_edge_identity",
        ),
        CheckConstraint(
            "edge_type in ("
            "'supports', 'contradicts', 'references', 'derived_from', "
            "'prompts', 'relates_to', 'has_limitation'"
            ")",
            name="ck_legal_knowledge_graph_edges_edge_type",
        ),
        CheckConstraint(
            "source_type in ("
            "'matter', 'matter_court_order', 'matter_proceeding_signal', "
            "'matter_document', 'matter_attachment_chunk', 'affidavit_statement', "
            "'affidavit_question', 'mock_hearing_session', 'mock_hearing_question', "
            "'mock_hearing_response', 'predictive_signal_item', 'predictive_signal_run', "
            "'authority_document', 'aggregate_snapshot', "
            "'litigation_intelligence_review_action', 'unavailable'"
            ")",
            name="ck_legal_knowledge_graph_edges_source_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("legal_knowledge_graph_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    from_node_id: Mapped[str] = mapped_column(
        ForeignKey("legal_knowledge_graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_node_id: Mapped[str] = mapped_column(
        ForeignKey("legal_knowledge_graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    edge_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    limitation_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    run: Mapped[LegalKnowledgeGraphRun] = relationship(back_populates="edges")


class MatterBillingProfile(Base):
    __tablename__ = "matter_billing_profiles"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_matter_billing_profile_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    firm_legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    firm_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    firm_gstin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    firm_pan: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_place_of_supply: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_sac_hsn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gst_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gstin_state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    cgst_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sgst_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    igst_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invoice_prefix: Mapped[str] = mapped_column(String(40), nullable=False, default="INV")
    next_invoice_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    billing_mode: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=MatterBillingMode.HOURLY,
        index=True,
    )
    default_rate_minor_per_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    footer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_template_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expense_categories_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    retainer_adjustments_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
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

    rates: Mapped[list[MatterBillingRate]] = relationship(
        back_populates="billing_profile",
        cascade="all, delete-orphan",
        order_by="MatterBillingRate.created_at.desc()",
    )


class MatterBillingRate(Base):
    __tablename__ = "matter_billing_rates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    billing_profile_id: Mapped[str] = mapped_column(
        ForeignKey("matter_billing_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rate_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    role: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    practice_area: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    amount_minor_per_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
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

    billing_profile: Mapped[MatterBillingProfile] = relationship(back_populates="rates")
    membership: Mapped[CompanyMembership | None] = relationship()


class MatterInvoiceExport(Base):
    __tablename__ = "matter_invoice_exports"

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
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("matter_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="pdf")
    generated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    template_version: Mapped[str] = mapped_column(String(40), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    invoice: Mapped[MatterInvoice] = relationship()
    generated_by_membership: Mapped[CompanyMembership | None] = relationship()


class CauseListExport(Base):
    __tablename__ = "cause_list_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    date_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    date_to: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    filters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="pdf")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    generated_by_membership: Mapped[CompanyMembership | None] = relationship()


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
    billing_rate_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_billing_rates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rate_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
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
    billing_rate: Mapped[MatterBillingRate | None] = relationship()


class MatterInvoice(Base):
    __tablename__ = "matter_invoices"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "invoice_number",
            name="uq_company_invoice_number",
        ),
        # EH-SGR-04: a blank number is not a number. Declared here as well as
        # in 20260820_0002 so the model and the database agree, and so the
        # SQLite test databases enforce it too. The companion immutability
        # trigger is PostgreSQL-only and lives in that migration.
        CheckConstraint(
            "trim(invoice_number) <> ''",
            name="ck_matter_invoice_number_not_blank",
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
    billing_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_billing_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_billing_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_gstin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    place_of_supply: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sac_hsn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    firm_legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    firm_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    firm_gstin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    firm_pan: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=InvoiceStatus.DRAFT)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    subtotal_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    taxable_value_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cgst_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sgst_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    igst_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tds_deducted_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payment_adjustment_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    billing_profile: Mapped[MatterBillingProfile | None] = relationship()
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
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sac_hsn: Mapped[str | None] = mapped_column(String(32), nullable=True)
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


class BillingPlanVersion(Base):
    __tablename__ = "billing_plan_versions"
    __table_args__ = (
        UniqueConstraint("plan_code", "version", name="uq_billing_plan_versions_code_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    plan_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    segment: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    publicly_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trial_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feature_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    prices: Mapped[list[BillingPlanPrice]] = relationship(
        back_populates="plan_version",
        cascade="all, delete-orphan",
    )
    entitlements: Mapped[list[BillingPlanEntitlement]] = relationship(
        back_populates="plan_version",
        cascade="all, delete-orphan",
    )


class BillingPlanPrice(Base):
    __tablename__ = "billing_plan_prices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    plan_version_id: Mapped[str] = mapped_column(
        ForeignKey("billing_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    tax_behavior: Mapped[str] = mapped_column(String(24), nullable=False, default="exclusive")
    tax_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    provider_plan_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider_plan_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan_version: Mapped[BillingPlanVersion] = relationship(back_populates="prices")


class BillingPlanEntitlement(Base):
    __tablename__ = "billing_plan_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "plan_version_id",
            "entitlement_key",
            name="uq_billing_plan_entitlements_plan_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    plan_version_id: Mapped[str] = mapped_column(
        ForeignKey("billing_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entitlement_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value_type: Mapped[str] = mapped_column(String(24), nullable=False)
    value_json: Mapped[object] = mapped_column(JSON, nullable=False)

    plan_version: Mapped[BillingPlanVersion] = relationship(back_populates="entitlements")


class BillingAccount(Base):
    __tablename__ = "billing_accounts"
    __table_args__ = (UniqueConstraint("company_id", name="uq_billing_accounts_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    billing_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    billing_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    billing_address_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tax_treatment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()


class BillingSubscription(Base):
    __tablename__ = "billing_subscriptions"
    __table_args__ = (
        Index(
            "uq_billing_subscriptions_company_active",
            "company_id",
            unique=True,
            sqlite_where=text("status IN ('active', 'trialing', 'grace', 'manual_active')"),
            postgresql_where=text("status IN ('active', 'trialing', 'grace', 'manual_active')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    billing_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=BillingSubscriptionStatus.MANUAL_ACTIVE,
        index=True,
    )
    segment: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    billing_interval: Mapped[str] = mapped_column(String(24), nullable=False, default="month")
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    provider_mandate_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="migration", index=True)
    externally_billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    entitlement_overrides_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    billing_account: Mapped[BillingAccount | None] = relationship()
    plan_version: Mapped[BillingPlanVersion | None] = relationship()
    items: Mapped[list[BillingSubscriptionItem]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
    )


class BillingSubscriptionItem(Base):
    __tablename__ = "billing_subscription_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    interval: Mapped[str] = mapped_column(String(24), nullable=False, default="month")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    provider_item_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    subscription: Mapped[BillingSubscription] = relationship(back_populates="items")


class BillingCheckoutSession(Base):
    __tablename__ = "billing_checkout_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    billing_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    checkout_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=BillingCheckoutStatus.CREATED,
        index=True,
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    success_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancel_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_checkout_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    subscription: Mapped[BillingSubscription | None] = relationship()
    plan_version: Mapped[BillingPlanVersion | None] = relationship()


class BillingPaymentOrder(Base):
    __tablename__ = "billing_payment_orders"
    __table_args__ = (
        UniqueConstraint("merchant_reference", name="uq_billing_payment_orders_merchant_ref"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    checkout_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_checkout_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="pine_labs")
    merchant_reference: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_link_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=BillingPaymentOrderStatus.CREATED,
        index=True,
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_paid_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    payment_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    return_signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    checkout_session: Mapped[BillingCheckoutSession | None] = relationship()
    subscription: Mapped[BillingSubscription | None] = relationship()


class BillingProviderEvent(Base):
    __tablename__ = "billing_provider_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_billing_provider_event"),
        UniqueConstraint("provider", "webhook_id", name="uq_billing_provider_webhook"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    webhook_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signature_digest: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BillingCreditLedger(Base):
    __tablename__ = "billing_credit_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    credit_bucket: Mapped[str] = mapped_column(String(40), nullable=False, default="included")
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_object_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_object_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class BillingUsageEvent(Base):
    __tablename__ = "billing_usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    usage_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    estimated_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    source_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class BillingUsageAttribution(Base):
    __tablename__ = "billing_usage_attribution"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    billing_usage_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_usage_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tracked_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("tracked_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    feature_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    purpose: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    display_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credits_debited: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_internal_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tenant_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class BillingUsageRollup(Base):
    __tablename__ = "billing_usage_rollups"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "period_start",
            "period_end",
            "usage_type",
            name="uq_billing_usage_rollup_period_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    usage_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revenue_allocated_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_margin_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class BillingProfitRollup(Base):
    __tablename__ = "billing_profit_rollups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    recognized_revenue_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_revenue_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_collected_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payment_gateway_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    case_refresh_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_processing_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_support_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_research_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_variable_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_profit_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_margin_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="estimated")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class BillingEnrollment(Base):
    __tablename__ = "billing_enrollments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    contact_mobile: Mapped[str | None] = mapped_column(String(40), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    segment: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    selected_plan: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="pricing_page")
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="lead_created", index=True
    )
    utm_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bar_council_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    coupon_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sales_owner_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_timestamps_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class BillingAdminNote(Base):
    __tablename__ = "billing_admin_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    enrollment_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_enrollments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    note_type: Mapped[str] = mapped_column(String(40), nullable=False, default="general")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class BillingManualInvoice(Base):
    __tablename__ = "billing_manual_invoices"
    __table_args__ = (UniqueConstraint("invoice_number", name="uq_billing_manual_invoice_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False)
    po_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tds_deducted_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount_received_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="issued", index=True)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class BillingCoupon(Base):
    __tablename__ = "billing_coupons"
    __table_args__ = (UniqueConstraint("code", name="uq_billing_coupons_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_type: Mapped[str] = mapped_column(String(24), nullable=False)
    discount_value: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    duration: Mapped[str] = mapped_column(String(24), nullable=False, default="once")
    duration_periods: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redeemed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    segment_scope_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    plan_scope_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class BillingCouponRedemption(Base):
    __tablename__ = "billing_coupon_redemptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    coupon_id: Mapped[str] = mapped_column(
        ForeignKey("billing_coupons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    checkout_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_checkout_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    discount_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    redeemed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class PlatformAdminMembership(Base):
    __tablename__ = "platform_admin_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_platform_admin_memberships_user"),
        Index(
            "uq_platform_admin_memberships_one_active",
            "status",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="super_admin")
    capabilities_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    mfa_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_enforced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped[User] = relationship()


class PlatformAdminAuditEvent(Base):
    __tablename__ = "platform_admin_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    result: Mapped[str] = mapped_column(String(24), nullable=False, default="success")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ConnectorSecretRotationEvidence(Base):
    __tablename__ = "connector_secret_rotation_evidence"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "affected_app",
            "credential_label",
            name="uq_connector_secret_rotation_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    affected_app: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    credential_label: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="blocked", index=True)
    old_credential_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_performed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rotation_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    residual_risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_evidence_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    recorded_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    recorded_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class PlatformOperationalReadinessEvidence(Base):
    __tablename__ = "platform_operational_readiness_evidence"
    __table_args__ = (UniqueConstraint("category", "gate_code", name="uq_platform_readiness_gate"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    gate_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="blocked", index=True)
    readiness_classification: Mapped[str] = mapped_column(
        String(40), nullable=False, default="founder-only"
    )
    blocker_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_evidence_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    owner_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    recorded_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    recorded_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class UserMFASetting(Base):
    __tablename__ = "user_mfa_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_mfa_settings_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_enrolled")
    encrypted_totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_displayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_challenge_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_codes_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped[User] = relationship()


class UserMFARecoveryCode(Base):
    __tablename__ = "user_mfa_recovery_codes"
    __table_args__ = (
        UniqueConstraint("user_id", "code_hash", name="uq_user_mfa_recovery_code_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship()


class UserMFAStepUp(Base):
    __tablename__ = "user_mfa_step_ups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship()
    membership: Mapped[CompanyMembership] = relationship()


class TenantSecurityPolicy(Base):
    __tablename__ = "tenant_security_policies"
    __table_args__ = (UniqueConstraint("company_id", name="uq_tenant_security_policy_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_admin_mfa_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    all_users_mfa_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_grace_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    mfa_enforced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    updated_by_membership: Mapped[CompanyMembership | None] = relationship()


class TenantEnterpriseIdentityConfiguration(Base):
    __tablename__ = "tenant_enterprise_identity_configurations"
    __table_args__ = (UniqueConstraint("company_id", name="uq_tenant_enterprise_identity_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idp_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    oidc_status: Mapped[str] = mapped_column(String(32), nullable=False, default="disabled")
    saml_status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    scim_status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    sso_enforcement_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="disabled"
    )
    domains_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required_evidence_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    last_test_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_run")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    not_enabled_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="SSO, SAML, and SCIM are readiness-only until an IdP UAT pass is recorded.",
    )
    updated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    updated_by_membership: Mapped[CompanyMembership | None] = relationship()


class AgentGrant(Base):
    __tablename__ = "agent_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    principal_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scopes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tool_budget_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="disabled", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    principal_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[principal_membership_id]
    )
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id]
    )


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_grants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workflow_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="blocked", index=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audit_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    grant: Mapped[AgentGrant | None] = relationship()
    started_by_membership: Mapped[CompanyMembership | None] = relationship()


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    scope: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="blocked", index=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="required")
    redacted_input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    redacted_output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    execution: Mapped[AgentExecution] = relationship()


class AIGovernanceApproval(Base):
    __tablename__ = "ai_governance_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    artifact_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    eval_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    regression_gate_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_run"
    )
    safety_gate_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_run")
    hallucination_gate_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_run"
    )
    legal_disclaimer_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approved_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    eval_run: Mapped[EvaluationRun | None] = relationship()
    approved_by_membership: Mapped[CompanyMembership | None] = relationship()


class PineLabsUATRun(Base):
    __tablename__ = "pine_labs_uat_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    environment: Mapped[str] = mapped_column(String(24), nullable=False, default="uat", index=True)
    provider_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="mock")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="in_progress")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operator_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    operator_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class PineLabsUATScenarioEvidence(Base):
    __tablename__ = "pine_labs_uat_scenario_evidence"
    __table_args__ = (
        UniqueConstraint("run_id", "scenario_code", name="uq_pine_labs_uat_run_scenario"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("pine_labs_uat_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scenario_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    webhook_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    redacted_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    run: Mapped[PineLabsUATRun] = relationship()
    created_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship(
        foreign_keys=[created_by_platform_admin_id],
    )


class PineLabsProductionActivationDecision(Base):
    __tablename__ = "pine_labs_production_activation_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("pine_labs_uat_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    missing_scenarios_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    founder_go_no_go: Mapped[str | None] = mapped_column(String(24), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    run: Mapped[PineLabsUATRun | None] = relationship()
    decided_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class ProductionBillingSignoff(Base):
    __tablename__ = "production_billing_signoffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="in_progress")
    signed_off_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    signed_off_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class ProductionBillingSignoffEvidence(Base):
    __tablename__ = "production_billing_signoff_evidence"
    __table_args__ = (
        UniqueConstraint("signoff_id", "check_code", name="uq_prod_billing_signoff_check"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    signoff_id: Mapped[str] = mapped_column(
        ForeignKey("production_billing_signoffs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    check_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    result_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    signoff: Mapped[ProductionBillingSignoff] = relationship()
    recorded_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class BillingSettlementImport(Base):
    __tablename__ = "billing_settlement_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="pine_labs_plural")
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settlement_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    settlement_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="imported", index=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exception_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    imported_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class BillingSettlementRow(Base):
    __tablename__ = "billing_settlement_rows"
    __table_args__ = (
        UniqueConstraint("settlement_import_id", "row_hash", name="uq_settlement_import_row_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    settlement_import_id: Mapped[str] = mapped_column(
        ForeignKey("billing_settlement_imports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="pine_labs_plural")
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payment_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    settlement_status: Mapped[str] = mapped_column(String(40), nullable=False, default="received")
    reconciliation_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="unmatched", index=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    net_settlement_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    settled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    raw_row_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    settlement_import: Mapped[BillingSettlementImport] = relationship()
    payment_order: Mapped[BillingPaymentOrder | None] = relationship()


class BillingReconciliationException(Base):
    __tablename__ = "billing_reconciliation_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    settlement_import_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_settlement_imports.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    settlement_row_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_settlement_rows.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    payment_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    exception_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="warning")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    amount_delta_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    settlement_import: Mapped[BillingSettlementImport | None] = relationship()
    settlement_row: Mapped[BillingSettlementRow | None] = relationship()
    payment_order: Mapped[BillingPaymentOrder | None] = relationship()
    resolved_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class BillingRefundRecord(Base):
    __tablename__ = "billing_refund_records"
    __table_args__ = (
        UniqueConstraint("provider", "provider_refund_id", name="uq_billing_refund_provider_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="pine_labs_plural")
    provider_refund_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payment_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="recorded", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_reversal_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    payment_order: Mapped[BillingPaymentOrder | None] = relationship()
    company: Mapped[Company | None] = relationship()
    subscription: Mapped[BillingSubscription | None] = relationship()
    created_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship(
        foreign_keys=[created_by_platform_admin_id],
    )


class BillingCreditNote(Base):
    __tablename__ = "billing_credit_notes"
    __table_args__ = (UniqueConstraint("credit_note_number", name="uq_billing_credit_note_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payment_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    refund_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_refund_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    credit_note_number: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="issued", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tax_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tds_adjustment_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    attachment_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company] = relationship()
    subscription: Mapped[BillingSubscription | None] = relationship()
    payment_order: Mapped[BillingPaymentOrder | None] = relationship()
    refund_record: Mapped[BillingRefundRecord | None] = relationship()
    created_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class BillingChargebackDispute(Base):
    __tablename__ = "billing_chargeback_disputes"
    __table_args__ = (
        UniqueConstraint("provider", "provider_dispute_id", name="uq_billing_dispute_provider_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="pine_labs_plural")
    provider_dispute_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payment_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    payment_order: Mapped[BillingPaymentOrder | None] = relationship()
    company: Mapped[Company | None] = relationship()
    created_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class BillingProviderFeeReconciliation(Base):
    __tablename__ = "billing_provider_fee_reconciliations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="pine_labs_plural")
    settlement_row_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_settlement_rows.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    payment_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    expected_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delta_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    settlement_row: Mapped[BillingSettlementRow | None] = relationship()
    payment_order: Mapped[BillingPaymentOrder | None] = relationship()


class BillingTDSReconciliationRow(Base):
    __tablename__ = "billing_tds_reconciliation_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_manual_invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    credit_note_id: Mapped[str | None] = mapped_column(
        ForeignKey("billing_credit_notes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payer_pan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    certificate_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    financial_year: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    gross_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tds_deducted_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tds_deposited_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    company: Mapped[Company | None] = relationship()
    subscription: Mapped[BillingSubscription | None] = relationship()
    invoice: Mapped[BillingManualInvoice | None] = relationship()
    credit_note: Mapped[BillingCreditNote | None] = relationship()
    created_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship()


class CaseTrackingSupportMatrix(Base):
    __tablename__ = "case_tracking_support_matrix"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "court",
            "bench_jurisdiction",
            "lookup_method",
            name="uq_case_tracking_support_matrix_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    court: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    bench_jurisdiction: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    lookup_method: Mapped[str] = mapped_column(String(120), nullable=False)
    refresh_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bulk_refresh_cost_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    rate_limit: Mapped[str | None] = mapped_column(String(160), nullable=True)
    freshness_sla: Mapped[str | None] = mapped_column(String(160), nullable=True)
    legal_tos_status: Mapped[str] = mapped_column(String(80), nullable=False, default="unknown")
    failure_code_mapping_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    tenant_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    status_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    created_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship(
        foreign_keys=[created_by_platform_admin_id],
    )
    updated_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship(
        foreign_keys=[updated_by_platform_admin_id],
    )


class BillingOveragePolicy(Base):
    __tablename__ = "billing_overage_policies"
    __table_args__ = (UniqueConstraint("company_id", name="uq_billing_overage_policies_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    overage_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unit_prices_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cap_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ProviderCostProfile(Base):
    __tablename__ = "provider_cost_profiles"
    __table_args__ = (
        CheckConstraint(
            "unit_amount_minor IS NOT NULL OR unit_amount_bps IS NOT NULL",
            name="ck_provider_cost_profiles_amount_present",
        ),
        Index(
            "ix_provider_cost_profiles_lookup",
            "category",
            "provider",
            "currency",
            "effective_from",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="default", index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR", index=True)
    unit_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_amount_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tax_fee_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_basis: Mapped[str] = mapped_column(String(24), nullable=False, default="estimated")
    confidence_level: Mapped[str] = mapped_column(String(24), nullable=False, default="low")
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    founder_approval_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending"
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    created_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship(
        foreign_keys=[created_by_platform_admin_id],
    )
    approved_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship(
        foreign_keys=[approved_by_platform_admin_id],
    )


class BillingMarginSimulation(Base):
    __tablename__ = "billing_margin_simulations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scenario_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    plan_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    scenario_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR", index=True)
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    warnings_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    minimum_gross_margin_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=7000)
    uses_unapproved_estimated_costs: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    readiness_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    founder_approval_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending"
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    run_by_platform_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    run_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship(
        foreign_keys=[run_by_platform_admin_id],
    )
    approved_by_platform_admin: Mapped[PlatformAdminMembership | None] = relationship(
        foreign_keys=[approved_by_platform_admin_id],
    )


class ClientType(StrEnum):
    INDIVIDUAL = "individual"
    CORPORATE = "corporate"
    GOVERNMENT = "government"
    NONPROFIT = "nonprofit"


class ClientKycStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    REQUESTED = "requested"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"


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
            "company_id",
            "name",
            "client_type",
            name="uq_clients_tenant_name_type",
        ),
        UniqueConstraint("id", "company_id", name="uq_clients_id_company"),
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
        default=ClientKycStatus.NOT_REQUIRED,
    )
    # Phase B M11 slice 3 — KYC audit trail. Without these the
    # status badge has no provenance: under a compliance audit the
    # workspace owner needs to point at WHO verified the client and
    # WHEN. Documents stored as JSON so a later "secure storage URL
    # per doc" extension does not need another migration.
    kyc_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    kyc_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
            "matter_id",
            "client_id",
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
    contract_type_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_type_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    legal_references: Mapped[list[ContractLegalReference]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="desc(ContractLegalReference.created_at)",
    )
    term_suggestions: Mapped[list[ContractTermSuggestion]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="desc(ContractTermSuggestion.created_at)",
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


class ContractLegalReference(Base):
    __tablename__ = "contract_legal_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    act_name: Mapped[str] = mapped_column(String(255), nullable=False)
    section_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    clause_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    authority_id: Mapped[str | None] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    statute_id: Mapped[str | None] = mapped_column(
        ForeignKey("statutes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=ContractLegalReferenceSource.MANUAL,
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    evidence_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("contract_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=ContractReviewStatus.ACCEPTED,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    contract: Mapped[Contract] = relationship(back_populates="legal_references")
    evidence_attachment: Mapped[ContractAttachment | None] = relationship(
        foreign_keys=[evidence_attachment_id],
    )
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )
    reviewed_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[reviewed_by_membership_id],
    )


class ContractTermSuggestion(Base):
    __tablename__ = "contract_term_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("contract_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    suggested_effective_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    suggested_expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    suggested_renewal_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    suggested_duration_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=ContractReviewStatus.SUGGESTED,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    contract: Mapped[Contract] = relationship(back_populates="term_suggestions")
    source_attachment: Mapped[ContractAttachment | None] = relationship(
        foreign_keys=[source_attachment_id],
    )
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )
    reviewed_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[reviewed_by_membership_id],
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
    attachment_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    parent_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("contract_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    parent_attachment: Mapped[ContractAttachment | None] = relationship(
        remote_side=[id],
        foreign_keys=[parent_attachment_id],
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


class AuthoritySearchObservation(Base):
    """Search health telemetry that intentionally excludes raw query text."""

    __tablename__ = "authority_search_observations"
    __table_args__ = (
        Index(
            "ix_authority_search_observations_company_created",
            "company_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    query_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unreadable_omitted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    filters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AuthorityResearchReport(Base):
    """Tenant-owned immutable snapshot of a user-selected research result set.

    The shared authority corpus remains canonical.  A report freezes only the
    identifiers and source metadata that were visible when the lawyer saved it,
    together with the search-analysis version.  Reports are never silently
    refreshed when the global corpus changes.
    """

    __tablename__ = "authority_research_reports"
    __table_args__ = (
        Index(
            "ix_authority_research_reports_company_created",
            "company_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    query: Mapped[str] = mapped_column(String(600), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    criteria_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_snapshot_json: Mapped[list] = mapped_column(JSON, nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(80), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
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
    decision_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
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
    structured_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # PG-006 (2026-05-01) — good-law / treatment signal. Populated by the
    # heuristic classifier in services/citation_treatment.py at
    # extraction time, and (later) revisited by an LLM-assisted pass for
    # uncertain rows. Stored as String to match the codebase convention
    # for StrEnum columns; defaults to NEUTRAL so existing rows still
    # parse cleanly after the alembic backfill.
    treatment: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=AuthorityCitationTreatment.NEUTRAL,
        server_default=AuthorityCitationTreatment.NEUTRAL.value,
        index=True,
    )
    treatment_evidence_text: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    treatment_confidence: Mapped[float | None] = mapped_column(
        Numeric(4, 3),
        nullable=True,
    )
    treatment_classified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
    webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    webhook_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
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


class VoyageUsage(Base):
    """Auditable record of every Voyage embedding call.

    Mirror of ``ModelRun`` for the embedding-spend leg. Without this
    table, the only spend signal was the Voyage console — which is
    why the Apr 18-26 SC ingest burned $343 before anyone noticed.
    """

    __tablename__ = "voyage_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_type: Mapped[str] = mapped_column(String(16), default="document", nullable=False)
    texts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="ok", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class JudgeDecisionIndex(Base):
    """L-A (MOD-TS-018, 2026-04-26): per-(judge, judgment) row.

    Materialized so bench-strategy panels can list a judge's history
    in O(N) joins instead of recomputing from authority_documents.
    judges_json on every query. Refreshed by
    services/bench_analysis_layers.refresh_judge_decision_index.
    """

    __tablename__ = "judge_decision_index"
    __table_args__ = (
        UniqueConstraint(
            "judge_id",
            "authority_document_id",
            name="uq_judge_decision_index_unique",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    judge_id: Mapped[str] = mapped_column(
        ForeignKey("judges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    authority_document_id: Mapped[str] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(24), default="sat_on", nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matched_alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    match_confidence: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class JudgeAuthorityAffinity(Base):
    """L-B (MOD-TS-018, 2026-04-26): per-(judge, cited authority) row.

    Powers "this bench cites X N times" surfaces in bench-strategy.
    Refreshed nightly by services/bench_analysis_layers.
    """

    __tablename__ = "judge_authority_affinity"
    __table_args__ = (
        UniqueConstraint(
            "judge_id",
            "cited_authority_document_id",
            name="uq_judge_authority_affinity_unique",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    judge_id: Mapped[str] = mapped_column(
        ForeignKey("judges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cited_authority_document_id: Mapped[str] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    citation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_judgment_id: Mapped[str | None] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class JudgeStatuteFocus(Base):
    """L-C (MOD-TS-018, 2026-04-26): per-(judge, statute_section) row.

    Powers "this bench engages this statute N times" surfaces.
    """

    __tablename__ = "judge_statute_focus"
    __table_args__ = (
        UniqueConstraint(
            "judge_id",
            "statute_section_id",
            name="uq_judge_statute_focus_unique",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    judge_id: Mapped[str] = mapped_column(
        ForeignKey("judges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statute_section_id: Mapped[str] = mapped_column(
        ForeignKey("statute_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    citation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_judgment_id: Mapped[str | None] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class PredictiveSignalRun(Base):
    """Controlled predictive-intelligence run.

    LI-S7A stores the deterministic data-contract output separately
    from recommendations because prediction surfaces need stricter
    source lineage, confidence, policy, and audit guarantees.
    """

    __tablename__ = "predictive_signal_runs"

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
    actor_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="predictive")
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_quality: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)
    limitation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    items: Mapped[list[PredictiveSignalItem]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="PredictiveSignalItem.created_at.asc()",
    )
    evidence_rows: Mapped[list[PredictiveSignalEvidence]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="PredictiveSignalEvidence.created_at.asc()",
    )


class PredictiveSignalItem(Base):
    """One controlled predictive signal within a run."""

    __tablename__ = "predictive_signal_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("predictive_signal_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    estimate_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence_label: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_band_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_band_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    limitation_note: Mapped[str] = mapped_column(Text, nullable=False)
    features_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    missing_data_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    run: Mapped[PredictiveSignalRun] = relationship(back_populates="items")
    evidence_rows: Mapped[list[PredictiveSignalEvidence]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="PredictiveSignalEvidence.created_at.asc()",
    )


class PredictiveSignalEvidence(Base):
    """Source lineage for a controlled predictive signal."""

    __tablename__ = "predictive_signal_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("predictive_signal_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("predictive_signal_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    run: Mapped[PredictiveSignalRun] = relationship(back_populates="evidence_rows")
    item: Mapped[PredictiveSignalItem] = relationship(back_populates="evidence_rows")


class PredictiveOutcomeClassification(Base):
    """Source-bound outcome label used by predictive-intelligence aggregates.

    Public authority classifications keep company_id/matter_id null. Private
    matter-order classifications must carry both scope columns and are excluded
    from public aggregate jobs by default.
    """

    __tablename__ = "predictive_outcome_classifications"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "classification_label",
            "signal_type",
            name="uq_predictive_outcome_classification_source_label_signal",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    classification_label: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    forum_level: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    judge_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    matter_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    party_side: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    decision_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    rationale_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(String(40), nullable=False, default="deterministic")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="classified",
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class PredictiveOutcomeAggregateSnapshot(Base):
    """Reusable aggregate backing controlled predictive-intelligence signals."""

    __tablename__ = "predictive_outcome_aggregate_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            name="uq_predictive_outcome_aggregate_scope_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(700), nullable=False, index=True)
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    forum_level: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    judge_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    matter_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    party_side: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    year_start: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    year_end: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    positive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consistency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_label: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="insufficient",
    )
    confidence_band_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_band_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    feature_summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="insufficient_evidence",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
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
    # PG-109 (2026-05-01) — source-used / source-ignored panel.
    # JSON list of retrieved authority identifiers the LLM was given
    # for this recommendation. UI computes cited-vs-considered by
    # intersecting with options[*].supporting_citations. Empty by
    # default for legacy rows that pre-date PG-109.
    retrieved_authorities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # MOD-LSE-1 (2026-05-03) — litigation strategy payload. Populated
    # only for rows where ``type='litigation_strategy'``; null on every
    # other recommendation row. Holds the JSON-serialised
    # ``LitigationStrategyPayload`` (forum sequence, recommended
    # drafts, limitation flags, etc.). The Pydantic schema on the
    # strategy service validates the shape on read/write — the column
    # itself is opaque JSON to the database.
    strategy_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class MatterStrategyEntry(Base):
    """Lawyer-owned strategy work product for a matter.

    Distinct from ``Recommendation`` rows, which remain system-generated
    decision support. This table holds human-authored plan/decision notes.
    """

    __tablename__ = "matter_strategy_entries"

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
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False, default="plan")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    owner_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_recommendation_id: Mapped[str | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    company: Mapped[Company] = relationship()
    matter: Mapped[Matter] = relationship()
    owner_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[owner_membership_id]
    )
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id]
    )
    updated_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[updated_by_membership_id]
    )
    source_recommendation: Mapped[Recommendation | None] = relationship()


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
    EDIT = "edit"
    SUBMIT = "submit"
    REQUEST_CHANGES = "request_changes"
    APPROVE = "approve"
    FINALIZE = "finalize"


class DraftingDataExtractionStatus(StrEnum):
    SUGGESTED = "suggested"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    OVERRIDDEN = "overridden"
    REJECTED = "rejected"


class DraftingDataConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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


class DraftingDataExtractionField(Base):
    """Matter-scoped, lawyer-reviewable facts proposed from uploaded documents.

    The row stores only bounded drafting metadata and a short source snippet.
    It never stores raw prompts, LLM answers, OCR payloads, storage keys, or
    attachment payloads.
    """

    __tablename__ = "drafting_data_extraction_fields"

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
    source_attachment_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    field_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    proposed_value: Mapped[str] = mapped_column(String(500), nullable=False)
    reviewed_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence_band: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DraftingDataConfidenceBand.LOW,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DraftingDataExtractionStatus.NEEDS_REVIEW,
        index=True,
    )
    source_snippet: Mapped[str | None] = mapped_column(String(280), nullable=True)
    source_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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

    company: Mapped[Company] = relationship()
    matter: Mapped[Matter] = relationship(back_populates="drafting_data_fields")
    source_attachment: Mapped[MatterAttachment | None] = relationship()
    created_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[created_by_membership_id],
    )
    reviewed_by_membership: Mapped[CompanyMembership | None] = relationship(
        foreign_keys=[reviewed_by_membership_id],
    )


class DraftVersion(Base):
    __tablename__ = "draft_versions"
    __table_args__ = (UniqueConstraint("draft_id", "revision", name="uq_draft_versions_revision"),)

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
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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


class SourceLinkReport(Base):
    """Tenant-scoped defect report and health-check request for a canonical source.

    The referenced legal record remains authoritative. This row stores only the
    operational workflow plus a one-way reference hash, never provider credentials
    or the raw destination URL.
    """

    __tablename__ = "source_link_reports"
    __table_args__ = (
        CheckConstraint(
            "target_type in ('authority_document', 'statute_section', "
            "'judge_appointment', 'matter_attachment', 'ip_document_version')",
            name="ck_source_link_reports_target_type",
        ),
        CheckConstraint(
            "issue_type in ('broken', 'wrong_document', 'access_denied', 'stale', 'other')",
            name="ck_source_link_reports_issue_type",
        ),
        CheckConstraint(
            "status in ('queued', 'investigating', 'resolved', 'dismissed')",
            name="ck_source_link_reports_status",
        ),
        Index(
            "ix_source_link_reports_target_created",
            "target_type",
            "target_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reported_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(120), nullable=False)
    origin_surface: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_reference_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_class: Mapped[str] = mapped_column(String(40), nullable=False)
    source_state: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
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
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_access_grant_matter_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_access_grant_ip_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_access_grant_membership_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["team_id", "company_id"],
            ["teams.id", "teams.company_id"],
            name="fk_access_grant_team_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_access_grant_exactly_one_target",
        ),
        CheckConstraint(
            "(CASE WHEN membership_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN team_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_access_grant_exactly_one_subject",
        ),
        CheckConstraint(
            "record_version >= 0",
            name="ck_access_grant_record_version_nonnegative",
        ),
        CheckConstraint(
            "expires_at IS NULL OR effective_from IS NULL OR expires_at > effective_from",
            name="ck_access_grant_effective_window",
        ),
        Index(
            "uq_access_grant_active_matter_membership",
            "matter_id",
            "membership_id",
            unique=True,
            sqlite_where=text(
                "revoked_at IS NULL AND matter_id IS NOT NULL AND membership_id IS NOT NULL"
            ),
            postgresql_where=text(
                "revoked_at IS NULL AND matter_id IS NOT NULL AND membership_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_access_grant_active_matter_team",
            "matter_id",
            "team_id",
            unique=True,
            sqlite_where=text(
                "revoked_at IS NULL AND matter_id IS NOT NULL AND team_id IS NOT NULL"
            ),
            postgresql_where=text(
                "revoked_at IS NULL AND matter_id IS NOT NULL AND team_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_access_grant_active_ip_membership",
            "ip_docket_id",
            "membership_id",
            unique=True,
            sqlite_where=text(
                "revoked_at IS NULL AND ip_docket_id IS NOT NULL AND membership_id IS NOT NULL"
            ),
            postgresql_where=text(
                "revoked_at IS NULL AND ip_docket_id IS NOT NULL AND membership_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_access_grant_active_ip_team",
            "ip_docket_id",
            "team_id",
            unique=True,
            sqlite_where=text(
                "revoked_at IS NULL AND ip_docket_id IS NOT NULL AND team_id IS NOT NULL"
            ),
            postgresql_where=text(
                "revoked_at IS NULL AND ip_docket_id IS NOT NULL AND team_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    access_level: Mapped[str] = mapped_column(
        String(24), nullable=False, default=MatterAccessLevel.MEMBER
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    granted_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=True, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    record_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_ethical_wall_matter_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ethical_wall_ip_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["excluded_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ethical_wall_membership_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["excluded_team_id", "company_id"],
            ["teams.id", "teams.company_id"],
            name="fk_ethical_wall_team_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_ethical_wall_exactly_one_target",
        ),
        CheckConstraint(
            "(CASE WHEN excluded_membership_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN excluded_team_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_ethical_wall_exactly_one_subject",
        ),
        CheckConstraint(
            "record_version >= 0",
            name="ck_ethical_wall_record_version_nonnegative",
        ),
        CheckConstraint(
            "expires_at IS NULL OR effective_from IS NULL OR expires_at > effective_from",
            name="ck_ethical_wall_effective_window",
        ),
        Index(
            "uq_ethical_wall_active_matter_membership",
            "matter_id",
            "excluded_membership_id",
            unique=True,
            sqlite_where=text(
                "revoked_at IS NULL AND matter_id IS NOT NULL "
                "AND excluded_membership_id IS NOT NULL"
            ),
            postgresql_where=text(
                "revoked_at IS NULL AND matter_id IS NOT NULL "
                "AND excluded_membership_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_ethical_wall_active_matter_team",
            "matter_id",
            "excluded_team_id",
            unique=True,
            sqlite_where=text(
                "revoked_at IS NULL AND matter_id IS NOT NULL AND excluded_team_id IS NOT NULL"
            ),
            postgresql_where=text(
                "revoked_at IS NULL AND matter_id IS NOT NULL AND excluded_team_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_ethical_wall_active_ip_membership",
            "ip_docket_id",
            "excluded_membership_id",
            unique=True,
            sqlite_where=text(
                "revoked_at IS NULL AND ip_docket_id IS NOT NULL "
                "AND excluded_membership_id IS NOT NULL"
            ),
            postgresql_where=text(
                "revoked_at IS NULL AND ip_docket_id IS NOT NULL "
                "AND excluded_membership_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_ethical_wall_active_ip_team",
            "ip_docket_id",
            "excluded_team_id",
            unique=True,
            sqlite_where=text(
                "revoked_at IS NULL AND ip_docket_id IS NOT NULL "
                "AND excluded_team_id IS NOT NULL"
            ),
            postgresql_where=text(
                "revoked_at IS NULL AND ip_docket_id IS NOT NULL "
                "AND excluded_team_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    excluded_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    excluded_team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=True, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    record_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
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


class ForumCatalogEntry(Base):
    """Public court/forum selector catalog.

    This table intentionally has no company_id: it is a shared legal forum
    taxonomy, not tenant data. Matter rows copy the selected metadata so legacy
    free-text court_name values continue to render if a catalog entry changes.
    """

    __tablename__ = "forum_catalog_entries"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("forum_catalog_entries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    court_id: Mapped[str | None] = mapped_column(
        ForeignKey("courts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    forum_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    forum_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    consumer_level: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lineage: Mapped[str] = mapped_column(String(500), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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

    parent: Mapped[ForumCatalogEntry | None] = relationship(
        remote_side=[id],
        foreign_keys=[parent_id],
    )
    court: Mapped[Court | None] = relationship(foreign_keys=[court_id])


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
    """Judge master record.

    Use this for profile pages, citation trends, cause-list dedup, and
    controlled predictive intelligence only through source-backed LI-S7
    contracts. Do not build opaque judge favorability scoring on top of it.
    """

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


class JudgeAlias(Base):
    """Slice D (MOD-TS-001-E, 2026-04-25) — alternate spellings for a
    judge's name so the bench-name resolver can match
    'Justice A.K. Sikri' to 'Justice Adarsh Kumar Sikri'. Replaces
    the prior ILIKE-on-judges_json fragility.

    alias_text is the human-friendly form; alias_normalised is
    lowercase + punctuation-stripped + collapsed-whitespace for
    O(1) lookup.
    """

    __tablename__ = "judge_aliases"
    __table_args__ = (
        UniqueConstraint(
            "judge_id",
            "alias_normalised",
            name="uq_judge_aliases_unique",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    judge_id: Mapped[str] = mapped_column(
        ForeignKey("judges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias_text: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias_normalised: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    # One of: sci_gov_in, hc_scrape, manual, auto_extract.
    source: Mapped[str] = mapped_column(String(64), nullable=False)
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


class JudgeAppointment(Base):
    """Career history per judge — every court a judge has served on.

    MOD-TS-001-B (Slice A, 2026-04-25). The Judge.court_id FK only
    captures the current appointment; this table captures the full
    timeline so a judge profile page can render the elevations + prior
    courts. Source-attributed per the bench-aware drafting hard rules
    (no rows without source_url).
    """

    __tablename__ = "judge_appointments"
    __table_args__ = (
        UniqueConstraint(
            "judge_id",
            "court_id",
            "role",
            "start_date",
            name="uq_judge_appointments_unique",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    judge_id: Mapped[str] = mapped_column(
        ForeignKey("judges.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    court_id: Mapped[str] = mapped_column(
        ForeignKey("courts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Free string rather than enum so HCs can introduce roles
    # ("acting_chief_justice", "additional_judge") without a migration.
    # Loader / backfill code is responsible for normalising input.
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Active appointment = end_date IS NULL. The seeder leaves NULL on
    # the current appointment row + sets a real date on prior rows
    # when the source provides one.
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class Statute(Base):
    """MOD-TS-017 (Slice S1, 2026-04-25). Master act roster — one row
    per Indian Act we ship a structured-section catalog for. v1: 7
    central acts (BNSS, BNS, BSA, CrPC, IPC, Constitution, NI Act).
    """

    __tablename__ = "statutes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    short_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    long_name: Mapped[str] = mapped_column(String(255), nullable=False)
    enacted_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False, default="india")
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    issuing_body: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="consolidated_statute"
    )
    source_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    legal_status: Mapped[str] = mapped_column(String(24), nullable=False, default="enacted")
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unverified", index=True
    )
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exact_source_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    history_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="current_text_only"
    )
    source_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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


class StatuteSection(Base):
    """One Section / Article / Order-Rule under an Act. section_text
    nullable so the seed can ship section numbers + labels first;
    bare text fetched lazily by the enrich script."""

    __tablename__ = "statute_sections"
    __table_args__ = (
        UniqueConstraint(
            "statute_id",
            "section_number",
            name="uq_statute_sections_unique",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    statute_id: Mapped[str] = mapped_column(
        ForeignKey("statutes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_number: Mapped[str] = mapped_column(String(64), nullable=False)
    section_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    section_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_text_source: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    editorial_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_annotations: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_text_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_provisional: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unverified", index=True
    )
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_publisher: Mapped[str | None] = mapped_column(String(160), nullable=True)
    issuing_body: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="consolidated_statute"
    )
    source_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    legal_status: Mapped[str] = mapped_column(String(24), nullable=False, default="enacted")
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    amendment_metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    history_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="current_text_only"
    )
    exact_source_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_locator_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unavailable"
    )
    source_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    link_health_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_checked"
    )
    link_last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    link_last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    section_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parent_section_id: Mapped[str | None] = mapped_column(
        ForeignKey("statute_sections.id", ondelete="CASCADE"),
        nullable=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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


class StatuteSourceVersion(Base):
    """Immutable candidate/review record for a statute provision source."""

    __tablename__ = "statute_source_versions"
    __table_args__ = (
        UniqueConstraint(
            "section_id",
            "proposed_source_version",
            name="uq_statute_source_versions_section_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    section_id: Mapped[str] = mapped_column(
        ForeignKey("statute_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    proposed_source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_text: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_publisher: Mapped[str] = mapped_column(String(160), nullable=False)
    issuing_body: Mapped[str] = mapped_column(String(160), nullable=False)
    source_category: Mapped[str] = mapped_column(String(32), nullable=False)
    source_status: Mapped[str] = mapped_column(String(24), nullable=False)
    legal_status: Mapped[str] = mapped_column(String(24), nullable=False)
    source_locator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    exact_source_version: Mapped[str] = mapped_column(String(160), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    amendment_metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    diff_unified: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    proposed_by_membership_id: Mapped[str] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class StatuteSourceConflict(Base):
    """Fail-closed record for disputed statute source facts and impact review."""

    __tablename__ = "statute_source_conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    section_id: Mapped[str] = mapped_column(
        ForeignKey("statute_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    disputed_facts_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_versions_json: Mapped[list] = mapped_column(JSON, nullable=False)
    authority_rank_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    affected_records_json: Mapped[list] = mapped_column(JSON, nullable=False)
    impact_scan_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class MatterStatuteReference(Base):
    """Matter → StatuteSection link with relevance label."""

    __tablename__ = "matter_statute_references"
    __table_args__ = (
        UniqueConstraint(
            "matter_id",
            "section_id",
            "relevance",
            name="uq_matter_statute_references_unique",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[str] = mapped_column(
        ForeignKey("statute_sections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # 'cited' (we rely on it) | 'opposing' (other side relies on it)
    # | 'context' (in scope but not load-bearing). Free string so we
    # can extend without a migration.
    relevance: Mapped[str] = mapped_column(String(32), nullable=False, default="cited")
    added_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
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


class AuthorityStatuteReference(Base):
    """AuthorityDocument → StatuteSection link populated by Slice S3's
    resolver (services/statute_resolver.py walks
    AuthorityDocument.sections_cited_json + writes structured FKs)."""

    __tablename__ = "authority_statute_references"
    __table_args__ = (
        UniqueConstraint(
            "authority_id",
            "section_id",
            name="uq_authority_statute_references_unique",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    authority_id: Mapped[str] = mapped_column(
        ForeignKey("authority_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[str] = mapped_column(
        ForeignKey("statute_sections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="layer2_extract")
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    __table_args__ = (UniqueConstraint("run_id", "case_key", name="uq_eval_case_key_per_run"),)

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
    since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_filter: Mapped[str | None] = mapped_column(String(120), nullable=True)
    row_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    __table_args__ = (
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_matter_deadline_matter_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_matter_deadline_ip_docket_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "company_id", name="uq_matter_deadline_id_company"),
        CheckConstraint(
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_matter_deadline_exactly_one_target",
        ),
        ForeignKeyConstraint(
            [
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                "ip_docket_id",
                "neutralized_by_ip_lifecycle_version",
            ],
            [
                "ip_docket_events.id",
                "ip_docket_events.company_id",
                "ip_docket_events.docket_id",
                "ip_docket_events.resulting_lifecycle_version",
            ],
            name="fk_matter_deadline_neutralized_event_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_by_ip_lifecycle_version IS NULL AND neutralized_at IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_by_ip_lifecycle_version IS NOT NULL AND neutralized_at IS NOT NULL "
            "AND company_id IS NOT NULL)",
            name="ck_matter_deadline_ip_lifecycle_provenance_complete",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_version IS NULL OR "
            "neutralized_by_ip_lifecycle_version > 0",
            name="ck_matter_deadline_ip_lifecycle_version_positive",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR status = 'cancelled'",
            name="ck_matter_deadline_ip_lifecycle_terminal_state",
        ),
        CheckConstraint(
            "neutralized_by_ip_lifecycle_event_id IS NULL OR ip_docket_id IS NOT NULL",
            name="ck_matter_deadline_ip_lifecycle_provenance_target",
        ),
        Index(
            "ix_matter_deadlines_ip_lifecycle_event",
            "neutralized_by_ip_lifecycle_event_id",
            "company_id",
            "ip_docket_id",
            "neutralized_by_ip_lifecycle_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    ip_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="CASCADE"),
        nullable=True,
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by_matter_disposal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    neutralized_by_ip_lifecycle_event_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    neutralized_by_ip_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    neutralized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TenantAIPolicy(Base):
    """Per-tenant AI policy (Sprint 15 partial / BG-046 schema).

    One row per company; the LLM provider factory reads
    ``allowed_models_*`` to refuse a request that violates the policy
    before any call is billed. Monthly token budgets use nullable
    columns: NULL means unlimited so existing tenants keep current AI
    behaviour until an admin sets a cap.
    """

    __tablename__ = "tenant_ai_policies"
    __table_args__ = (UniqueConstraint("company_id", name="uq_tenant_ai_policy_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    allowed_models_drafting_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    allowed_models_recommendations_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    allowed_models_hearing_pack_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    max_tokens_per_session: Mapped[int] = mapped_column(Integer, nullable=False, default=16384)
    monthly_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_monthly_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_warning_threshold_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90
    )
    external_share_requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    training_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # PG-107 (2026-05-01) / LI-S7A (2026-05-11) — opt-in controlled
    # predictive bench/litigation intelligence. Default false:
    # evidence-only output. Owner/admin can flip per workspace; source
    # IDs, sample-size guard, confidence bands, audit, and mandatory
    # not-legal-advice disclaimer remain enforced server-side.
    predictive_bench_strategy_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # PG-005 Sprint 11 (2026-05-01) — template governance. JSON list of
    # DraftTemplateType values the admin has hidden from this workspace
    # (e.g. a corporate-only firm hiding "bail" / "criminal_complaint").
    # The /api/drafting/templates endpoint filters its response on this
    # list; the recommender matrix also drops disabled types from its
    # output. Default empty = every template visible.
    disabled_template_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
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
    linked_matter: Mapped[Matter | None] = relationship(foreign_keys=[linked_matter_id])


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
        UniqueConstraint("id", "company_id", name="uq_teams_id_company_id"),
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
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default=TeamKind.TEAM)
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
    __table_args__ = (UniqueConstraint("team_id", "membership_id", name="uq_team_membership"),)

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
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "matter_id",
            "external_message_id",
            name="uq_communications_message_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str | None] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    direction: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default=CommunicationDirection.OUTBOUND,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(400), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=CommunicationStatus.LOGGED,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    external_message_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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


class EmailCalendarCandidateStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    APPROVED_CREATED = "approved_created"
    REJECTED = "rejected"
    DUPLICATE_SKIPPED = "duplicate_skipped"


class EmailCalendarCandidate(Base):
    """Reviewable calendar-event candidate detected from imported email metadata.

    ADP-19 keeps this durable and matter-scoped so extraction remains
    idempotent and approval can create an internal CaseOps calendar item
    without touching any provider calendar.
    """

    __tablename__ = "email_calendar_candidates"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "matter_id",
            "communication_id",
            "normalized_key",
            name="uq_email_calendar_candidate_source_key",
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
    communication_id: Mapped[str] = mapped_column(
        ForeignKey("communications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_key: Mapped[str | None] = mapped_column(String(180), nullable=True)
    normalized_key: Mapped[str] = mapped_column(String(96), nullable=False)
    detected_title: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    detected_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    detected_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_preview: Mapped[str | None] = mapped_column(String(280), nullable=True)
    confidence_band: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EmailCalendarCandidateStatus.NEEDS_REVIEW,
        index=True,
    )
    duplicate_of_candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("email_calendar_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_deadline_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_deadlines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    subject_template: Mapped[str] = mapped_column(String(400), nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "name",
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
            "company_id",
            "email",
            name="uq_portal_user_company_email",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    sessions_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    invited_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    last_signed_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    company: Mapped[Company] = relationship()
    magic_links: Mapped[list[PortalMagicLink]] = relationship(
        back_populates="portal_user",
        cascade="all, delete-orphan",
    )
    grants: Mapped[list[MatterPortalGrant]] = relationship(
        back_populates="portal_user",
        cascade="all, delete-orphan",
    )


class PortalMagicLink(Base):
    """One-shot, hash-only magic-link token bound to a PortalUser.

    The plaintext token is returned to the caller exactly once (when
    the link is generated for AutoMail dispatch); only the SHA-256
    hash lives in the DB so a hot dump cannot replay sessions.
    """

    __tablename__ = "portal_magic_links"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    portal_user_id: Mapped[str] = mapped_column(
        ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    requested_ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    requested_user_agent: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
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
            "portal_user_id",
            "matter_id",
            name="uq_matter_portal_grant_user_matter",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    portal_user_id: Mapped[str] = mapped_column(
        ForeignKey("portal_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    granted_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    portal_user: Mapped[PortalUser] = relationship(back_populates="grants")


# ---------------------------------------------------------------------------
# ADP-14: tenant-managed contract playbooks (company-scoped) and rules.
# Distinct from the per-contract ContractPlaybookRule above, which stays
# in place for backward compatibility with /clauses/extract + the
# existing LLM-backed compare_playbook flow.
# ---------------------------------------------------------------------------


class TenantContractPlaybook(Base):
    __tablename__ = "tenant_contract_playbooks"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "name",
            name="uq_tenant_contract_playbook_company_name",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_type_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(120), nullable=True)
    party_perspective: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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

    rules: Mapped[list[TenantContractPlaybookRule]] = relationship(
        back_populates="playbook",
        cascade="all, delete-orphan",
        order_by="TenantContractPlaybookRule.created_at.asc()",
    )


class TenantContractPlaybookRule(Base):
    __tablename__ = "tenant_contract_playbook_rules"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    playbook_id: Mapped[str] = mapped_column(
        ForeignKey("tenant_contract_playbooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    clause_type: Mapped[str] = mapped_column(String(120), nullable=False)
    expected_position: Mapped[str] = mapped_column(Text, nullable=False)
    fallback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContractPlaybookSeverity.MEDIUM,
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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

    playbook: Mapped[TenantContractPlaybook] = relationship(back_populates="rules")


class ApiIdempotencyState(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ApiIdempotencyRecord(Base):
    """Shared HTTP mutation replay record.

    The record retains only a canonical request digest and a stable result
    reference.  Response bodies, uploaded bytes, and other confidential request
    content do not belong in this table.
    """

    __tablename__ = "api_idempotency_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_membership_id", "actor_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_api_idempotency_actor_company",
            ondelete="SET NULL",
        ),
        UniqueConstraint("id", "company_id", name="uq_api_idempotency_id_company"),
        UniqueConstraint(
            "company_id",
            "actor_scope",
            "http_method",
            "operation",
            "idempotency_key",
            name="uq_api_idempotency_scope_key",
        ),
        Index(
            "ix_api_idempotency_scope_lookup",
            "company_id",
            "actor_scope",
            "operation",
            "idempotency_key",
        ),
        Index("ix_api_idempotency_expiry", "expires_at", "state"),
        Index(
            "ix_api_idempotency_actor_membership",
            "actor_membership_id",
            "actor_company_id",
            "created_at",
        ),
        Index(
            "ix_api_idempotency_actor_company",
            "actor_company_id",
            "actor_membership_id",
        ),
        CheckConstraint(
            "state IN ('processing', 'completed', 'failed')",
            name="ck_api_idempotency_state",
        ),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_api_idempotency_request_hash_length",
        ),
        CheckConstraint(
            "claim_generation > 0",
            name="ck_api_idempotency_claim_generation_positive",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_api_idempotency_expiry_after_create",
        ),
        CheckConstraint(
            "(actor_membership_id IS NULL AND actor_company_id IS NULL) OR "
            "(actor_membership_id IS NOT NULL AND actor_company_id = company_id)",
            name="ck_api_idempotency_actor_company",
        ),
        CheckConstraint(
            "(state = 'processing' AND claim_token IS NOT NULL AND "
            "claim_expires_at IS NOT NULL AND finished_at IS NULL) OR "
            "(state IN ('completed', 'failed') AND claim_token IS NULL AND "
            "claim_expires_at IS NULL AND finished_at IS NOT NULL)",
            name="ck_api_idempotency_claim_state",
        ),
        CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 100 AND 599",
            name="ck_api_idempotency_response_status",
        ),
        CheckConstraint(
            "(result_type IS NULL AND result_id IS NULL) OR "
            "(result_type IS NOT NULL AND result_id IS NOT NULL)",
            name="ck_api_idempotency_result_reference",
        ),
        CheckConstraint(
            "state <> 'completed' OR response_status IS NOT NULL",
            name="ck_api_idempotency_completed_response",
        ),
        CheckConstraint(
            "(actor_scope LIKE 'membership:%' OR actor_scope LIKE 'system:%') "
            "AND actor_scope NOT IN ('membership:', 'system:')",
            name="ck_api_idempotency_actor_scope_kind",
        ),
        CheckConstraint(
            "actor_membership_id IS NULL OR "
            "actor_scope = 'membership:' || actor_membership_id",
            name="ck_api_idempotency_actor_scope_membership",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    actor_scope: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_company_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    http_method: Mapped[str] = mapped_column(String(12), nullable=False)
    operation: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ApiIdempotencyState.PROCESSING
    )
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class DomainOutboxState(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"


class DomainOutboxEvent(Base):
    """Neutral transactional event plus bounded delivery-control state."""

    __tablename__ = "domain_outbox_events"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_domain_outbox_id_company"),
        UniqueConstraint(
            "company_id", "event_key", name="uq_domain_outbox_company_event_key"
        ),
        Index(
            "ix_domain_outbox_claim",
            "state",
            "next_attempt_at",
            "lease_expires_at",
            "created_at",
        ),
        Index(
            "ix_domain_outbox_company_state",
            "company_id",
            "state",
            "created_at",
        ),
        Index(
            "ix_domain_outbox_dead_letter_resolution",
            "company_id",
            "state",
            "dead_letter_resolution",
            "dead_lettered_at",
        ),
        Index(
            "ix_domain_outbox_aggregate",
            "company_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
        ),
        Index(
            "ix_domain_outbox_correlation",
            "company_id",
            "correlation_id",
        ),
        CheckConstraint(
            "state IN ('queued', 'processing', 'retry_scheduled', "
            "'succeeded', 'dead_letter')",
            name="ck_domain_outbox_state",
        ),
        CheckConstraint(
            "confidentiality IN ('internal', 'confidential', 'privileged')",
            name="ck_domain_outbox_confidentiality",
        ),
        CheckConstraint(
            "schema_version > 0",
            name="ck_domain_outbox_schema_version_positive",
        ),
        CheckConstraint(
            "aggregate_version >= 0",
            name="ck_domain_outbox_aggregate_version_nonnegative",
        ),
        CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_domain_outbox_payload_hash_length",
        ),
        CheckConstraint(
            "source_command_id IS NOT NULL OR source_event_id IS NOT NULL",
            name="ck_domain_outbox_source_reference",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_domain_outbox_attempts",
        ),
        CheckConstraint(
            "fence_version >= 0",
            name="ck_domain_outbox_fence_nonnegative",
        ),
        CheckConstraint(
            "(state = 'processing' AND lease_owner IS NOT NULL AND "
            "lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'processing' AND lease_owner IS NULL AND "
            "lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_domain_outbox_lease_state",
        ),
        CheckConstraint(
            "state <> 'retry_scheduled' OR next_attempt_at IS NOT NULL",
            name="ck_domain_outbox_retry_time",
        ),
        CheckConstraint(
            "(state = 'succeeded' AND completed_at IS NOT NULL) OR "
            "(state <> 'succeeded' AND completed_at IS NULL)",
            name="ck_domain_outbox_completed_state",
        ),
        CheckConstraint(
            "(state = 'dead_letter' AND dead_lettered_at IS NOT NULL AND "
            "dead_letter_reason IS NOT NULL) OR "
            "(state <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name="ck_domain_outbox_dead_letter_state",
        ),
        CheckConstraint(
            "json_array_length(expected_consumers_json) > 0",
            name="ck_domain_outbox_expected_consumers_nonempty",
        ),
        CheckConstraint(
            "(state = 'dead_letter' AND dead_letter_resolution IN "
            "('pending', 'ignored', 'resolved')) OR "
            "(state <> 'dead_letter' AND dead_letter_resolution IS NULL)",
            name="ck_domain_outbox_dead_letter_resolution_state",
        ),
        CheckConstraint(
            "(dead_letter_resolution = 'pending' AND "
            "dead_letter_resolved_at IS NULL) OR "
            "(dead_letter_resolution IN ('ignored', 'resolved') AND "
            "dead_letter_resolved_at IS NOT NULL) OR "
            "dead_letter_resolution IS NULL",
            name="ck_domain_outbox_dead_letter_resolution_time",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    event_key: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_command_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    producer: Mapped[str] = mapped_column(String(120), nullable=False)
    producer_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidentiality: Mapped[str] = mapped_column(String(24), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_consumers_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, default=DomainOutboxState.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fence_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_redacted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dead_letter_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    dead_letter_resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    dead_letter_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class DomainConsumerEffectState(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DomainConsumerEffect(Base):
    """Per-consumer idempotency/checkpoint state for one outbox event."""

    __tablename__ = "domain_consumer_effects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["outbox_event_id", "company_id"],
            ["domain_outbox_events.id", "domain_outbox_events.company_id"],
            name="fk_domain_consumer_effect_outbox_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_domain_consumer_effect_id_company"),
        UniqueConstraint(
            "company_id",
            "outbox_event_id",
            "consumer_name",
            name="uq_domain_consumer_effect_event_consumer",
        ),
        UniqueConstraint(
            "company_id",
            "consumer_name",
            "effect_key",
            name="uq_domain_consumer_effect_key",
        ),
        Index(
            "ix_domain_consumer_effect_claim",
            "state",
            "lease_expires_at",
            "updated_at",
        ),
        Index(
            "ix_domain_consumer_effect_company_consumer",
            "company_id",
            "consumer_name",
            "state",
        ),
        Index(
            "ix_domain_consumer_effect_event",
            "outbox_event_id",
            "company_id",
            "state",
        ),
        CheckConstraint(
            "state IN ('processing', 'completed', 'failed')",
            name="ck_domain_consumer_effect_state",
        ),
        CheckConstraint(
            "attempts > 0",
            name="ck_domain_consumer_effect_attempts_positive",
        ),
        CheckConstraint(
            "fence_version > 0 AND outbox_fence_version > 0",
            name="ck_domain_consumer_effect_fences_positive",
        ),
        CheckConstraint(
            "(state = 'processing' AND lease_owner IS NOT NULL AND "
            "lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND "
            "completed_at IS NULL AND failed_at IS NULL) OR "
            "(state = 'completed' AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL AND completed_at IS NOT NULL AND "
            "failed_at IS NULL) OR "
            "(state = 'failed' AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL AND completed_at IS NULL AND "
            "failed_at IS NOT NULL)",
            name="ck_domain_consumer_effect_lease_state",
        ),
        CheckConstraint(
            "(result_type IS NULL AND result_id IS NULL) OR "
            "(result_type IS NOT NULL AND result_id IS NOT NULL)",
            name="ck_domain_consumer_effect_result_reference",
        ),
        CheckConstraint(
            "result_hash IS NULL OR length(result_hash) = 64",
            name="ck_domain_consumer_effect_result_hash_length",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    outbox_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    consumer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    consumer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    effect_key: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DomainConsumerEffectState.PROCESSING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    outbox_fence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fence_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_redacted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class IpWorkflowDefinition(Base):
    """Company-owned identity for an inert, versioned IP lifecycle workflow."""

    __tablename__ = "ip_workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "id", "company_id", name="uq_ip_workflow_definition_id_company"
        ),
        UniqueConstraint(
            "company_id", "key", name="uq_ip_workflow_definition_company_key"
        ),
        CheckConstraint(
            "aggregate_type = 'ip_docket_record'",
            name="ck_ip_workflow_definition_aggregate_type",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aggregate_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="ip_docket_record"
    )
    initial_state: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class IpWorkflowVersion(Base):
    """Immutable workflow contract shape; IPLF-027B owns activation and UX."""

    __tablename__ = "ip_workflow_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["definition_id", "company_id"],
            ["ip_workflow_definitions.id", "ip_workflow_definitions.company_id"],
            name="fk_ip_workflow_version_definition_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proposed_by_membership_id", "proposed_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workflow_version_proposer_company",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["reviewed_by_membership_id", "reviewed_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workflow_version_reviewer_company",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            [
                "legal_approved_by_membership_id",
                "legal_approved_by_membership_company_id",
            ],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workflow_version_legal_approver_company",
            ondelete="SET NULL",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_workflow_version_id_company"),
        UniqueConstraint(
            "definition_id",
            "company_id",
            "version",
            name="uq_ip_workflow_version_definition_company_number",
        ),
        UniqueConstraint(
            "id",
            "company_id",
            "definition_id",
            "version",
            name="uq_ip_workflow_version_pin",
        ),
        CheckConstraint("version > 0", name="ck_ip_workflow_version_positive"),
        CheckConstraint(
            "schema_version > 0", name="ck_ip_workflow_schema_version_positive"
        ),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'active', 'retired', 'disabled')",
            name="ck_ip_workflow_version_status",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR "
            "effective_until >= effective_from",
            name="ck_ip_workflow_version_effective_range",
        ),
        CheckConstraint(
            "proposed_by_membership_id IS NULL OR reviewed_by_membership_id IS NULL "
            "OR proposed_by_membership_id <> reviewed_by_membership_id",
            name="ck_ip_workflow_version_reviewer_distinct",
        ),
        CheckConstraint(
            "proposed_by_membership_id IS NULL OR legal_approved_by_membership_id IS NULL "
            "OR proposed_by_membership_id <> legal_approved_by_membership_id",
            name="ck_ip_workflow_version_legal_approver_distinct",
        ),
        CheckConstraint(
            "(proposed_by_membership_id IS NULL AND "
            "proposed_by_membership_company_id IS NULL) OR "
            "(proposed_by_membership_id IS NOT NULL AND "
            "proposed_by_membership_company_id = company_id)",
            name="ck_ip_workflow_version_proposer_company_complete",
        ),
        CheckConstraint(
            "(reviewed_by_membership_id IS NULL AND "
            "reviewed_by_membership_company_id IS NULL) OR "
            "(reviewed_by_membership_id IS NOT NULL AND "
            "reviewed_by_membership_company_id = company_id)",
            name="ck_ip_workflow_version_reviewer_company_complete",
        ),
        CheckConstraint(
            "(legal_approved_by_membership_id IS NULL AND "
            "legal_approved_by_membership_company_id IS NULL) OR "
            "(legal_approved_by_membership_id IS NOT NULL AND "
            "legal_approved_by_membership_company_id = company_id)",
            name="ck_ip_workflow_version_legal_approver_company_complete",
        ),
        CheckConstraint(
            "length(content_hash) = 64 AND length(source_hash) = 64",
            name="ck_ip_workflow_version_hash_lengths",
        ),
        CheckConstraint(
            "(status = 'candidate' AND approved_at IS NULL AND activated_at IS NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'approved' AND approved_at IS NOT NULL AND activated_at IS NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'active' AND approved_at IS NOT NULL AND activated_at IS NOT NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'retired' AND approved_at IS NOT NULL AND retired_at IS NOT NULL) OR "
            "(status = 'disabled' AND retired_at IS NOT NULL)",
            name="ck_ip_workflow_version_status_timestamps",
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'active', 'retired') OR "
            "(proposer_membership_id_snapshot IS NOT NULL AND "
            "proposer_user_id_snapshot IS NOT NULL AND proposer_label_snapshot IS NOT NULL "
            "AND proposer_authority_snapshot_json IS NOT NULL AND "
            "reviewer_membership_id_snapshot IS NOT NULL AND "
            "reviewer_user_id_snapshot IS NOT NULL AND reviewer_label_snapshot IS NOT NULL "
            "AND reviewer_authority_snapshot_json IS NOT NULL AND "
            "legal_approver_membership_id_snapshot IS NOT NULL AND "
            "legal_approver_user_id_snapshot IS NOT NULL "
            "AND legal_approver_label_snapshot IS NOT NULL "
            "AND legal_approver_authority_snapshot_json IS NOT NULL "
            "AND fixtures_passed_at IS NOT NULL)",
            name="ck_ip_workflow_version_approved_evidence",
        ),
        Index("ix_ip_workflow_versions_company_status", "company_id", "status"),
        Index(
            "ix_ip_workflow_versions_proposed_by_membership_id",
            "proposed_by_membership_id",
            "proposed_by_membership_company_id",
        ),
        Index(
            "ix_ip_workflow_versions_reviewed_by_membership_id",
            "reviewed_by_membership_id",
            "reviewed_by_membership_company_id",
        ),
        Index(
            "ix_ip_workflow_versions_legal_approved_by_membership_id",
            "legal_approved_by_membership_id",
            "legal_approved_by_membership_company_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    definition_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    transition_table_json: Mapped[list | dict] = mapped_column(JSON, nullable=False)
    fixture_set_json: Mapped[list | dict] = mapped_column(JSON, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_compatibility: Mapped[str] = mapped_column(String(80), nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    proposed_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    proposed_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    proposer_membership_id_snapshot: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    proposer_user_id_snapshot: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    proposer_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proposer_authority_snapshot_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    reviewed_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    reviewer_membership_id_snapshot: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    reviewer_user_id_snapshot: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    reviewer_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewer_authority_snapshot_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    legal_approved_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    legal_approved_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    legal_approver_membership_id_snapshot: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    legal_approver_user_id_snapshot: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    legal_approver_label_snapshot: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    legal_approver_authority_snapshot_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    fixtures_passed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpPortfolioSavedView(Base):
    __tablename__ = "ip_portfolio_saved_views"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_portfolio_view_membership_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_portfolio_view_id_company"),
        ForeignKeyConstraint(
            ["team_id", "company_id"],
            ["teams.id", "teams.company_id"],
            name="fk_ip_portfolio_view_team_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "membership_id",
            "name",
            name="uq_ip_portfolio_view_member_name",
        ),
        Index(
            "ix_ip_portfolio_views_company_member",
            "company_id",
            "membership_id",
        ),
        Index("ix_ip_portfolio_views_membership", "membership_id"),
        Index("ix_ip_portfolio_views_team", "team_id"),
        CheckConstraint(
            "(scope = 'personal' AND team_id IS NULL) OR "
            "(scope = 'team' AND team_id IS NOT NULL)",
            name="ck_ip_portfolio_view_scope_owner",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    team_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filters_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    columns_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpPortfolioExportJob(Base):
    __tablename__ = "ip_portfolio_export_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["requested_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_portfolio_export_requester_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_portfolio_export_id_company"),
        Index(
            "ix_ip_portfolio_exports_company_requester_created",
            "company_id",
            "requested_by_membership_id",
            "created_at",
        ),
        Index("ix_ip_portfolio_exports_requester", "requested_by_membership_id"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_ip_portfolio_export_status",
        ),
        CheckConstraint("format IN ('csv')", name="ck_ip_portfolio_export_format"),
        CheckConstraint(
            "row_limit > 0 AND row_limit <= 50000",
            name="ck_ip_portfolio_export_row_limit",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    format: Mapped[str] = mapped_column(String(12), nullable=False, default="csv")
    filters_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    columns_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    row_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDocketRecord(Base):
    __tablename__ = "ip_docket_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_ip_docket_matter_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_docket_creator_company",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["successor_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_docket_successor_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workflow_definition_id", "company_id"],
            ["ip_workflow_definitions.id", "ip_workflow_definitions.company_id"],
            name="fk_ip_docket_workflow_definition_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workflow_version_id",
                "company_id",
                "workflow_definition_id",
                "workflow_version_number",
            ],
            [
                "ip_workflow_versions.id",
                "ip_workflow_versions.company_id",
                "ip_workflow_versions.definition_id",
                "ip_workflow_versions.version",
            ],
            name="fk_ip_docket_workflow_version_pin",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_docket_id_company"),
        UniqueConstraint(
            "company_id",
            "primary_identifier",
            name="uq_ip_docket_company_identifier",
        ),
        Index("ix_ip_docket_company_status", "company_id", "status"),
        CheckConstraint(
            "(status IN ('archived', 'abandoned', 'transferred', 'retired', 'closed') "
            "AND is_active = false) OR "
            "(status NOT IN ('archived', 'abandoned', 'transferred', 'retired', "
            "'closed') AND is_active = true)",
            name="ck_ip_docket_status_active_consistent",
        ),
        CheckConstraint(
            "lifecycle_version >= 0",
            name="ck_ip_docket_lifecycle_version_nonnegative",
        ),
        CheckConstraint(
            "access_policy_version >= 0",
            name="ck_ip_docket_access_policy_version_nonnegative",
        ),
        CheckConstraint(
            "successor_docket_id IS NULL OR successor_docket_id <> id",
            name="ck_ip_docket_successor_not_self",
        ),
        CheckConstraint(
            "(workflow_definition_id IS NULL AND workflow_version_id IS NULL AND "
            "workflow_version_number IS NULL) OR "
            "(workflow_definition_id IS NOT NULL AND workflow_version_id IS NOT NULL "
            "AND workflow_version_number IS NOT NULL)",
            name="ck_ip_docket_workflow_pin_complete",
        ),
        CheckConstraint(
            "workflow_version_number IS NULL OR workflow_version_number > 0",
            name="ck_ip_docket_workflow_version_positive",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    matter_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    lifecycle_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    lifecycle_effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifecycle_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_outcome: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lifecycle_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lifecycle_evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    successor_docket_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    workflow_definition_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    workflow_version_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    workflow_version_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    archived_by_matter_disposal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_policy_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpDocketEvent(Base):
    """Append-only legal event; delivery/audit state remains with shared owners."""

    __tablename__ = "ip_docket_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_docket_event_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_docket_event_application_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_docket_event_proceeding_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["responsible_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_docket_event_responsible_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["entered_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_docket_event_entered_by_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_docket_event_supersedes_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reconciles_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_docket_event_reconciles_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_docket_event_id_company"),
        UniqueConstraint(
            "id",
            "company_id",
            "docket_id",
            "resulting_lifecycle_version",
            name="uq_ip_docket_event_lifecycle_provenance",
        ),
        UniqueConstraint(
            "company_id",
            "docket_id",
            "sequence",
            name="uq_ip_docket_event_company_docket_sequence",
        ),
        Index(
            "ix_ip_docket_events_company_effective",
            "company_id",
            "docket_id",
            "effective_at",
        ),
        Index(
            "ix_ip_docket_events_company_candidate",
            "company_id",
            "candidate_status",
        ),
        CheckConstraint(
            "NOT (application_id IS NOT NULL AND proceeding_id IS NOT NULL)",
            name="ck_ip_docket_event_single_legal_target",
        ),
        CheckConstraint(
            "sequence > 0",
            name="ck_ip_docket_event_sequence_positive",
        ),
        CheckConstraint(
            "source <> 'manual' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_ip_docket_event_manual_reason",
        ),
        CheckConstraint(
            "supersedes_event_id IS NULL OR "
            "(correction_reason IS NOT NULL AND length(trim(correction_reason)) > 0)",
            name="ck_ip_docket_event_correction_reason",
        ),
        CheckConstraint(
            "supersedes_event_id IS NULL OR supersedes_event_id <> id",
            name="ck_ip_docket_event_supersedes_not_self",
        ),
        CheckConstraint(
            "reconciles_event_id IS NULL OR reconciles_event_id <> id",
            name="ck_ip_docket_event_reconciles_not_self",
        ),
        CheckConstraint(
            "resulting_lifecycle_version IS NULL OR "
            "(resulting_lifecycle_version > 0 AND "
            "event_kind = 'lifecycle_transition' AND candidate_status = 'confirmed')",
            name="ck_ip_docket_event_lifecycle_provenance_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    application_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    proceeding_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    responsible_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entered_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    document_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    resulting_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resulting_deadline_refs_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    before_phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resulting_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    candidate_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="confirmed", server_default="confirmed"
    )
    supersedes_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciles_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    reconciliation_decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpMatterLink(Base):
    """Effective-dated reference between independently owned IP and Matter lifecycles."""

    __tablename__ = "ip_matter_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_matter_link_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_ip_matter_link_matter_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_matter_link_creator_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["retired_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_matter_link_retirer_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_matter_link_id_company"),
        Index(
            "uq_ip_matter_links_active_role",
            "company_id",
            "docket_id",
            "matter_id",
            "relation_role",
            unique=True,
            postgresql_where=text("retired_at IS NULL"),
            sqlite_where=text("retired_at IS NULL"),
        ),
        Index(
            "uq_ip_matter_links_active_operational",
            "company_id",
            "docket_id",
            unique=True,
            postgresql_where=text(
                "retired_at IS NULL AND relation_role = 'operational'"
            ),
            sqlite_where=text("retired_at IS NULL AND relation_role = 'operational'"),
        ),
        Index(
            "ix_ip_matter_links_company_docket_effective",
            "company_id",
            "docket_id",
            "effective_from",
        ),
        Index(
            "ix_ip_matter_links_company_matter_effective",
            "company_id",
            "matter_id",
            "effective_from",
        ),
        CheckConstraint(
            "relation_role IN ('operational', 'litigation', 'advisory', 'appeal', "
            "'enforcement', 'billing', 'other')",
            name="ck_ip_matter_link_relation_role",
        ),
        CheckConstraint(
            "source IN ('manual', 'system', 'migration')",
            name="ck_ip_matter_link_source",
        ),
        CheckConstraint(
            "retired_at IS NULL OR retired_at >= effective_from",
            name="ck_ip_matter_link_effective_range",
        ),
        CheckConstraint(
            "(retired_at IS NULL AND retired_by_membership_id IS NULL AND "
            "retirement_reason IS NULL) OR "
            "(retired_at IS NOT NULL AND retired_by_membership_id IS NOT NULL AND "
            "retirement_reason IS NOT NULL)",
            name="ck_ip_matter_link_retirement_contract",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    matter_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    relation_role: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    retirement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    retired_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpAsset(Base):
    __tablename__ = "ip_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_asset_docket_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_asset_id_company"),
        UniqueConstraint("company_id", "docket_id", name="uq_ip_asset_company_docket"),
        Index("ix_ip_assets_company_kind", "company_id", "asset_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    asset_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class TrademarkApplication(Base):
    __tablename__ = "trademark_applications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_tm_application_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["asset_id", "company_id"],
            ["ip_assets.id", "ip_assets.company_id"],
            name="fk_tm_application_asset_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "company_id", name="uq_tm_application_id_company"),
        Index("ix_tm_applications_company_phase", "company_id", "filing_phase"),
        Index("ix_tm_applications_company_asset", "company_id", "asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    office: Mapped[str] = mapped_column(String(80), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(40), nullable=False)
    filing_phase: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    lifecycle_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    source_pending_identifier_allocation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class TrademarkApplicationScope(Base):
    __tablename__ = "trademark_application_scopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_tm_scope_application_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_tm_scope_effective_range",
        ),
        UniqueConstraint(
            "application_id",
            "class_number",
            "effective_from",
            name="uq_tm_scope_application_class_effective",
        ),
        Index("ix_tm_scopes_company_application", "company_id", "application_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    class_number: Mapped[int] = mapped_column(Integer, nullable=False)
    specification: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class TrademarkRepresentation(Base):
    __tablename__ = "trademark_representations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_tm_representation_application_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint("application_id", "version", name="uq_tm_representation_version"),
        Index("ix_tm_representations_company_application", "company_id", "application_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    representation_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    display_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpProceeding(Base):
    __tablename__ = "ip_proceedings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_proceeding_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_proceeding_application_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_proceeding_id_company"),
        Index("ix_ip_proceedings_company_kind", "company_id", "proceeding_kind"),
        CheckConstraint(
            "origin_kind IN ('linked_application', 'registry_event', 'watch_hit', "
            "'manual_intake')",
            name="ck_ip_proceeding_origin_kind",
        ),
        CheckConstraint(
            "proceeding_kind <> 'opposition' OR side IN ('applicant', 'opponent')",
            name="ck_ip_opposition_represented_side",
        ),
        CheckConstraint(
            "proceeding_kind <> 'opposition' OR stage IN ("
            "'draft', 'notice_filed', 'service_pending', 'counterstatement_due', "
            "'counterstatement_filed', 'opponent_evidence_due', "
            "'opponent_evidence_filed', 'applicant_evidence_due', "
            "'applicant_evidence_filed', 'reply_evidence_due', "
            "'reply_evidence_filed', 'hearing_pending', 'hearing_scheduled', "
            "'reserved_for_order', 'decided', 'appeal_pending', 'appealed', "
            "'withdrawn', 'closed')",
            name="ck_ip_opposition_canonical_stage",
        ),
        CheckConstraint(
            "length(trim(stage_template_version)) > 0",
            name="ck_ip_proceeding_stage_template_version",
        ),
        CheckConstraint(
            "proceeding_kind <> 'opposition' OR "
            "(side = 'applicant' AND "
            "stage_template_version = 'opposition-applicant-v1') OR "
            "(side = 'opponent' AND "
            "stage_template_version = 'opposition-opponent-v1')",
            name="ck_ip_opposition_role_stage_template",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    application_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    proceeding_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    side: Mapped[str] = mapped_column(String(24), nullable=False)
    office: Mapped[str] = mapped_column(String(80), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    origin_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual_intake", server_default="manual_intake"
    )
    stage_template_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="generic-v1", server_default="generic-v1"
    )
    source_pending_identifier_allocation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpIdentifier(Base):
    __tablename__ = "ip_identifiers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_identifier_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_identifier_application_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_identifier_proceeding_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["supersedes_identifier_id", "company_id"],
            ["ip_identifiers.id", "ip_identifiers.company_id"],
            name="fk_ip_identifier_supersedes_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["superseded_by_identifier_id", "company_id"],
            ["ip_identifiers.id", "ip_identifiers.company_id"],
            name="fk_ip_identifier_superseded_by_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(application_id IS NOT NULL AND proceeding_id IS NULL) OR "
            "(application_id IS NULL AND proceeding_id IS NOT NULL)",
            name="ck_ip_identifier_single_owner",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_identifier_effective_range",
        ),
        CheckConstraint(
            "superseded_by_identifier_id IS NULL OR superseded_by_identifier_id <> id",
            name="ck_ip_identifier_superseded_by_not_self",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_identifier_id_company"),
        Index(
            "ix_ip_identifiers_company_search",
            "company_id",
            "identifier_kind",
            "normalized_value",
        ),
        Index("ix_ip_identifiers_company_docket", "company_id", "docket_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    application_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    proceeding_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    identifier_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_value: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(160), nullable=False)
    office: Mapped[str] = mapped_column(String(80), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconciliation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="confirmed"
    )
    supersedes_identifier_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_identifiers.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Direction matters: ``supersedes_identifier_id`` belongs on a new
    # correction and points backward. This field belongs on the retired row
    # and points forward to the surviving identifier selected by reconciliation.
    superseded_by_identifier_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    correction_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpPartyAndRole(Base):
    __tablename__ = "ip_parties_and_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_party_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["client_id", "company_id"],
            ["clients.id", "clients.company_id"],
            name="fk_ip_party_client_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_party_proceeding_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_party_effective_range",
        ),
        Index("ix_ip_parties_company_docket", "company_id", "docket_id"),
        Index("ix_ip_parties_proceeding_company", "proceeding_id", "company_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    proceeding_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpRelationship(Base):
    __tablename__ = "ip_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_relationship_source_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_relationship_target_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "source_docket_id <> target_docket_id",
            name="ck_ip_relationship_distinct_dockets",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_relationship_effective_range",
        ),
        UniqueConstraint(
            "company_id",
            "source_docket_id",
            "target_docket_id",
            "relationship_kind",
            "effective_from",
            name="uq_ip_relationship_effective",
        ),
        Index("ix_ip_relationships_company_source", "company_id", "source_docket_id"),
        Index("ix_ip_relationships_company_target", "company_id", "target_docket_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    relationship_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpWorkspaceConfiguration(Base):
    __tablename__ = "ip_workspace_configurations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workspace_config_updater_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["provider_terms_accepted_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workspace_config_terms_actor_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["escalation_owner_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workspace_config_escalation_owner_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_workspace_config_id_company"),
        UniqueConstraint("company_id", name="uq_ip_workspace_config_company"),
        Index(
            "ix_ip_workspace_config_terms_actor",
            "provider_terms_accepted_by_membership_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled_asset_types_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    jurisdictions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    offices_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    holiday_calendar_key: Mapped[str] = mapped_column(String(120), nullable=False)
    working_day_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    document_taxonomy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    event_catalog_version: Mapped[str] = mapped_column(String(80), nullable=False)
    deadline_rule_versions_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notification_channels_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    critical_event_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    escalation_owner_membership_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    provider_keys_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provider_terms_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_terms_accepted_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    provider_terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enabled_automations_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    workspace_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpWorkspaceTestResult(Base):
    __tablename__ = "ip_workspace_test_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["configuration_id", "company_id"],
            ["ip_workspace_configurations.id", "ip_workspace_configurations.company_id"],
            name="fk_ip_workspace_test_config_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["performed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workspace_test_actor_company",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_ip_workspace_tests_company_config",
            "company_id",
            "configuration_id",
            "config_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    configuration_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    test_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    performed_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDocumentTaxonomyEntry(Base):
    """Tenant-owned controlled vocabulary for IP documents."""

    __tablename__ = "ip_document_taxonomy_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_doc_taxonomy_updater_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_doc_taxonomy_id_company"),
        UniqueConstraint("company_id", "key", name="uq_ip_doc_taxonomy_company_key"),
        CheckConstraint("version > 0", name="ck_ip_doc_taxonomy_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_seeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpDocumentTaxonomyAlias(Base):
    """Normalized import/search alias resolving to one tenant taxonomy entry."""

    __tablename__ = "ip_document_taxonomy_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy_entry_id", "company_id"],
            ["ip_document_taxonomy_entries.id", "ip_document_taxonomy_entries.company_id"],
            name="fk_ip_doc_taxonomy_alias_entry_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_doc_taxonomy_alias_creator_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id", "normalized_alias", name="uq_ip_doc_taxonomy_alias_company"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    taxonomy_entry_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="tenant")
    created_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDocument(Base):
    """Stable document identity; binary content is held by immutable versions."""

    __tablename__ = "ip_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["taxonomy_entry_id", "company_id"],
            ["ip_document_taxonomy_entries.id", "ip_document_taxonomy_entries.company_id"],
            name="fk_ip_document_taxonomy_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_document_creator_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_document_id_company"),
        CheckConstraint("current_version > 0", name="ck_ip_document_current_version_positive"),
        CheckConstraint(
            "confidentiality IN ('internal', 'confidential', 'restricted')",
            name="ck_ip_document_confidentiality",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    taxonomy_entry_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    confidentiality: Mapped[str] = mapped_column(String(24), nullable=False, default="internal")
    is_privileged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpDocumentVersion(Base):
    """Immutable binary identity and processing evidence for an IP document version."""

    __tablename__ = "ip_document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "company_id"],
            ["ip_documents.id", "ip_documents.company_id"],
            name="fk_ip_document_version_document_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["uploaded_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_document_version_uploader_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["locked_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_document_version_locker_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_document_version_id_company"),
        UniqueConstraint(
            "id",
            "company_id",
            "document_id",
            name="uq_ip_document_version_id_company_document",
        ),
        UniqueConstraint("document_id", "version", name="uq_ip_document_version_number"),
        UniqueConstraint("storage_key", name="uq_ip_document_version_storage_key"),
        CheckConstraint("version > 0", name="ck_ip_document_version_positive"),
        CheckConstraint("size_bytes >= 0", name="ck_ip_document_version_size_nonnegative"),
        CheckConstraint(
            "length(sha256_hex) = 64", name="ck_ip_document_version_sha256_length"
        ),
        CheckConstraint(
            "extracted_char_count >= 0",
            name="ck_ip_document_version_extracted_chars_nonnegative",
        ),
        CheckConstraint(
            "ocr_quality_score IS NULL OR "
            "(ocr_quality_score >= 0 AND ocr_quality_score <= 1)",
            name="ck_ip_document_version_ocr_quality_range",
        ),
        CheckConstraint(
            "state IN ('draft', 'review', 'approved', 'filed', 'served', 'accepted', "
            "'rejected', 'superseded')",
            name="ck_ip_document_version_state",
        ),
        CheckConstraint(
            "(state IN ('approved', 'filed') AND locked_at IS NOT NULL "
            "AND locked_by_membership_id IS NOT NULL) OR "
            "(state NOT IN ('approved', 'filed'))",
            name="ck_ip_document_version_approval_lock",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    processing_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=DocumentProcessingStatus.PENDING
    )
    extracted_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ocr_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    uploaded_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    locked_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDocumentLink(Base):
    """Typed, tenant-safe links without duplicating an IP document binary."""

    __tablename__ = "ip_document_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "company_id"],
            ["ip_documents.id", "ip_documents.company_id"],
            name="fk_ip_document_link_document_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            name="fk_ip_document_link_version_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_document_link_docket_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_document_link_application_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_document_link_proceeding_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_document_link_event_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_document_link_deadline_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_document_link_creator_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "document_id", "target_type", "target_id", name="uq_ip_document_link_target"
        ),
        CheckConstraint(
            "(CASE WHEN docket_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN application_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN proceeding_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN event_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN deadline_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_ip_document_link_exactly_one_target",
        ),
        CheckConstraint(
            "CASE target_type "
            "WHEN 'docket' THEN CASE WHEN docket_id = target_id THEN 1 ELSE 0 END "
            "WHEN 'application' THEN CASE WHEN application_id = target_id THEN 1 ELSE 0 END "
            "WHEN 'proceeding' THEN CASE WHEN proceeding_id = target_id THEN 1 ELSE 0 END "
            "WHEN 'event' THEN CASE WHEN event_id = target_id THEN 1 ELSE 0 END "
            "WHEN 'deadline' THEN CASE WHEN deadline_id = target_id THEN 1 ELSE 0 END "
            "ELSE 0 END = 1",
            name="ck_ip_document_link_target_consistent",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    application_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    proceeding_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    deadline_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpTrademarkParticularVersion(Base):
    __tablename__ = "ip_trademark_particular_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_tm_version_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_tm_version_creator_company",
            ondelete="SET NULL",
        ),
        UniqueConstraint("docket_id", "version", name="uq_ip_tm_docket_version"),
        Index("ix_ip_tm_versions_company_docket", "company_id", "docket_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    form_key: Mapped[str] = mapped_column(String(80), nullable=False)
    form_version: Mapped[str] = mapped_column(String(40), nullable=False)
    mark_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    representation_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    classes_json: Mapped[list] = mapped_column(JSON, nullable=False)
    use_priority_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parties_json: Mapped[list] = mapped_column(JSON, nullable=False)
    agent_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    filing_manifest_json: Mapped[list] = mapped_column(JSON, nullable=False)
    readiness_status: Mapped[str] = mapped_column(String(24), nullable=False)
    readiness_errors_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CompanyNoticeIpLink(Base):
    __tablename__ = "company_notice_ip_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_notice_ip_link_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["notice_id", "company_id"],
            ["company_notices.id", "company_notices.company_id"],
            name="fk_notice_ip_link_notice_company",
            ondelete="CASCADE",
        ),
        UniqueConstraint("notice_id", "docket_id", name="uq_notice_ip_link"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    notice_id: Mapped[str] = mapped_column(String(36), nullable=False)
    link_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted_effect: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpEvidenceCandidate(Base):
    """Reviewable projection of existing evidence into an IP docket.

    The source row remains owned by Notice, Communication, Drive, or Matter
    Attachment.  This table is only the permission-scoped triage/link record;
    it never copies document bodies or provider credentials.
    """

    __tablename__ = "ip_evidence_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_evidence_candidate_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["reviewed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_evidence_candidate_reviewer_company",
            ondelete="SET NULL",
        ),
        UniqueConstraint(
            "company_id",
            "docket_id",
            "source_type",
            "source_id",
            name="uq_ip_evidence_candidate_source",
        ),
        Index(
            "ix_ip_evidence_candidates_company_status",
            "company_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    suggested_link_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="needs_review")
    accepted_effect: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duplicate_of_candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_evidence_candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDeadlineCoverage(Base):
    __tablename__ = "ip_deadline_coverages"
    __table_args__ = (
        CheckConstraint(
            "replacement_decision IN ('none', 'pending', 'accepted', 'rejected')",
            name="ck_ip_coverage_replacement_decision",
        ),
        CheckConstraint(
            "replacement_decision <> 'pending' OR pending_replacement_membership_id IS NOT NULL",
            name="ck_ip_coverage_pending_has_subject",
        ),
        CheckConstraint(
            "emergency_until IS NULL OR emergency_escalation_membership_id IS NOT NULL",
            name="ck_ip_coverage_emergency_is_time_boxed",
        ),
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_deadline_coverage_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["pending_replacement_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_coverage_pending_replacement_company",
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["emergency_escalation_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_coverage_emergency_escalation_company",
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("docket_id", "matter_deadline_id", name="uq_ip_deadline_coverage"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    matter_deadline_id: Mapped[str] = mapped_column(
        ForeignKey("matter_deadlines.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    responsible_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    backup_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    coverage_status: Mapped[str] = mapped_column(String(24), nullable=False, default="accepted")
    calendar_projection_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending"
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # CAL-OPS-08: a transfer is proposed, then accepted or rejected. Ownership
    # does not move until it is accepted, or until time-boxed emergency cover
    # is approved.
    pending_replacement_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    replacement_decision: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none"
    )
    replacement_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replacement_decision_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    emergency_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    emergency_escalation_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reassignment_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpDeadlineIncident(Base):
    __tablename__ = "ip_deadline_incidents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_deadline_incident_docket_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_deadline_incident_creator_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["impact_scan_completed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_deadline_incident_impact_actor_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["resolved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_deadline_incident_resolver_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["verified_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_deadline_incident_verifier_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('open', 'contained', 'impact_assessed', 'disproved', 'verified')",
            name="ck_ip_deadline_incident_status",
        ),
        CheckConstraint(
            "defect_scope IN ('record_specific', 'shared_rule', 'shared_source', 'platform_wide')",
            name="ck_ip_deadline_incident_defect_scope",
        ),
        CheckConstraint(
            "status NOT IN ('disproved', 'verified') OR "
            "(resolved_by_membership_id IS NOT NULL AND resolved_at IS NOT NULL "
            "AND resolution_evidence_reference IS NOT NULL)",
            name="ck_ip_deadline_incident_terminal_evidence",
        ),
        Index("ix_ip_deadline_incidents_company_status", "company_id", "status"),
        Index("ix_ip_deadline_incident_creator", "created_by_membership_id"),
        Index(
            "ix_ip_deadline_incident_impact_completed_actor",
            "impact_scan_completed_by_membership_id",
        ),
        Index("ix_ip_deadline_incident_resolver", "resolved_by_membership_id"),
        Index("ix_ip_deadline_incident_verifier", "verified_by_membership_id"),
        UniqueConstraint("id", "company_id", name="uq_ip_deadline_incident_id_company"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    matter_deadline_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_deadlines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    impact_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    preservation_manifest_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="0000000000000000000000000000000000000000000000000000000000000000",
        server_default="0000000000000000000000000000000000000000000000000000000000000000",
    )
    defect_scope: Mapped[str] = mapped_column(
        String(24), nullable=False, default="record_specific"
    )
    defect_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    containment: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction_deadline_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_deadlines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    impact_scan_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    impact_scan_completed_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    preventive_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    prevention_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_evidence_reference: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Nullable only for rows created before UJ-58 actor evidence existed. The
    # command service always sets this for new incidents.
    created_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDeadlineIncidentImpact(Base):
    """Append-only affected-record result from an incident impact scan."""

    __tablename__ = "ip_deadline_incident_impacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "company_id"],
            ["ip_deadline_incidents.id", "ip_deadline_incidents.company_id"],
            name="fk_ip_deadline_incident_impact_incident_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assessed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_deadline_incident_impact_actor_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "assessment IN ('affected', 'not_affected', 'pending')",
            name="ck_ip_deadline_incident_impact_assessment",
        ),
        UniqueConstraint(
            "incident_id",
            "record_type",
            "record_reference_sha256",
            name="uq_ip_deadline_incident_impact_record",
        ),
        Index("ix_ip_deadline_incident_impact_incident", "incident_id", "assessed_at"),
        Index("ix_ip_deadline_incident_impact_actor", "assessed_by_membership_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    record_type: Mapped[str] = mapped_column(String(40), nullable=False)
    record_reference_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    relationship: Mapped[str] = mapped_column(String(120), nullable=False)
    assessment: Mapped[str] = mapped_column(String(20), nullable=False)
    scan_method: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    assessed_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDeadlineIncidentAction(Base):
    """Append-only containment, correction, advice, or prevention action."""

    __tablename__ = "ip_deadline_incident_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "company_id"],
            ["ip_deadline_incidents.id", "ip_deadline_incidents.company_id"],
            name="fk_ip_deadline_incident_action_incident_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recorded_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_deadline_incident_action_actor_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "action_status IN ('planned', 'completed', 'not_available')",
            name="ck_ip_deadline_incident_action_status",
        ),
        Index("ix_ip_deadline_incident_action_incident", "incident_id", "recorded_at"),
        Index("ix_ip_deadline_incident_action_actor", "recorded_by_membership_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    action_status: Mapped[str] = mapped_column(String(20), nullable=False)
    action_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    recorded_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDeadlineIncidentNotificationDecision(Base):
    """Append-only recipient-specific communication decision history."""

    __tablename__ = "ip_deadline_incident_notification_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "company_id"],
            ["ip_deadline_incidents.id", "ip_deadline_incidents.company_id"],
            name="fk_ip_deadline_incident_notice_incident_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["decided_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_deadline_incident_notice_actor_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "recipient_type IN ('client', 'insurer', 'regulator', 'court', 'external_counsel')",
            name="ck_ip_deadline_incident_notice_recipient_type",
        ),
        CheckConstraint(
            "decision IN ('pending', 'notify', 'do_not_notify', 'not_applicable')",
            name="ck_ip_deadline_incident_notice_decision",
        ),
        UniqueConstraint(
            "incident_id",
            "recipient_type",
            "recipient_reference_sha256",
            "decision_version",
            name="uq_ip_deadline_incident_notice_version",
        ),
        Index("ix_ip_deadline_incident_notice_incident", "incident_id", "decided_at"),
        Index("ix_ip_deadline_incident_notice_actor", "decided_by_membership_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recipient_type: Mapped[str] = mapped_column(String(24), nullable=False)
    recipient_reference_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    approval_evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    communication_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpIncidentKillSwitch(Base):
    """Tenant-level automated-feature stop linked to a platform-wide incident."""

    __tablename__ = "ip_incident_kill_switches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "company_id"],
            ["ip_deadline_incidents.id", "ip_deadline_incidents.company_id"],
            name="fk_ip_incident_kill_switch_incident_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["activated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_incident_kill_switch_activator_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["released_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_incident_kill_switch_releaser_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('active', 'released')",
            name="ck_ip_incident_kill_switch_status",
        ),
        UniqueConstraint(
            "incident_id", "feature_id", name="uq_ip_incident_kill_switch_incident_feature"
        ),
        Index(
            "uq_ip_incident_kill_switch_active_feature",
            "company_id",
            "feature_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_ip_incident_kill_switch_incident", "incident_id"),
        Index("ix_ip_incident_kill_switch_activator", "activated_by_membership_id"),
        Index("ix_ip_incident_kill_switch_releaser", "released_by_membership_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    feature_id: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    activation_evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    activated_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    released_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class IpTitleInterest(Base):
    __tablename__ = "ip_title_interests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_title_interest_docket_company",
            ondelete="CASCADE",
        ),
        Index("ix_ip_title_interests_company_docket", "company_id", "docket_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    interest_type: Mapped[str] = mapped_column(String(32), nullable=False)
    party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    related_docket_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    recordal_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_required")
    conflict_flags_json: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpRelatedRightObligation(Base):
    __tablename__ = "ip_related_right_obligations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_related_obligation_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_related_obligation_owner_company",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_ip_related_obligations_company_status_due",
            "company_id",
            "status",
            "due_on",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title_interest_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_title_interests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    obligation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    owner_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    matter_deadline_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_deadlines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    completion_evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpCostItem(Base):
    __tablename__ = "ip_cost_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_cost_item_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_ip_cost_item_matter_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount_minor >= 0", name="ck_ip_cost_item_amount_nonnegative"),
        CheckConstraint("length(currency) = 3", name="ck_ip_cost_item_currency"),
        CheckConstraint(
            "cost_nature IN ('actual', 'estimate')",
            name="ck_ip_cost_item_cost_nature",
        ),
        CheckConstraint(
            "(billing_link_type IS NULL) = (billing_link_id IS NULL)",
            name="ck_ip_cost_item_billing_link_pair",
        ),
        # UJ-52-EXC-01: a docket with no billing Matter may still record the
        # cost, but only as nonbillable evidence with nothing to link to.
        CheckConstraint(
            "matter_id IS NOT NULL OR (billable = false AND billing_link_type IS NULL)",
            name="ck_ip_cost_item_matterless_is_nonbillable",
        ),
        CheckConstraint(
            "billable = true OR billing_link_type IS NULL",
            name="ck_ip_cost_item_nonbillable_has_no_billing_link",
        ),
        # UJ-52-EXC-04: an estimate is not an expense and cannot reconcile.
        CheckConstraint(
            "cost_nature = 'actual' OR billing_link_type IS NULL",
            name="ck_ip_cost_item_estimate_has_no_billing_link",
        ),
        # UJ-52-EXC-02: preserve original amount/rate/source/time, or none.
        CheckConstraint(
            "(fx_rate IS NULL AND fx_rate_source IS NULL AND fx_converted_at IS NULL"
            " AND base_amount_minor IS NULL AND base_currency IS NULL)"
            " OR (fx_rate IS NOT NULL AND fx_rate_source IS NOT NULL"
            " AND fx_converted_at IS NOT NULL AND base_amount_minor IS NOT NULL"
            " AND base_currency IS NOT NULL)",
            name="ck_ip_cost_item_fx_complete",
        ),
        CheckConstraint(
            "fx_rate IS NULL OR fx_rate > 0",
            name="ck_ip_cost_item_fx_rate_positive",
        ),
        CheckConstraint(
            "base_amount_minor IS NULL OR base_amount_minor >= 0",
            name="ck_ip_cost_item_base_amount_nonnegative",
        ),
        CheckConstraint(
            "base_currency IS NULL OR length(base_currency) = 3",
            name="ck_ip_cost_item_base_currency",
        ),
        CheckConstraint(
            "base_currency IS NULL OR base_currency <> currency",
            name="ck_ip_cost_item_fx_distinct_currency",
        ),
        Index("ix_ip_cost_items_company_docket", "company_id", "docket_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # Nullable since IPLF-039F: UJ-52-EXC-01 requires nonbillable legal-cost
    # capture to survive the absence of a billing Matter.
    matter_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    # The amount exactly as incurred. When the FX columns below are set this
    # stays the ORIGINAL amount and currency; the conversion is recorded
    # beside it rather than replacing it.
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cost_nature: Mapped[str] = mapped_column(String(16), nullable=False, default="actual")
    rate_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    fx_rate_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fx_converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    base_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    base_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    billing_link_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    billing_link_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reconciliation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unlinked"
    )
    canonical_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reconciliation_difference_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class LegalWorkingCalendar(Base):
    """Shared calendar identity; immutable dated facts live in version rows."""

    __tablename__ = "legal_working_calendars"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_legal_working_calendar_id_company"),
        UniqueConstraint("company_id", "key", name="uq_legal_working_calendar_company_key"),
        Index(
            "ix_legal_working_calendars_scope",
            "company_id",
            "jurisdiction",
            "office",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(40), nullable=False)
    office: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class LegalWorkingCalendarVersion(Base):
    """Append-only legal calendar facts used by reproducible calculations."""

    __tablename__ = "legal_working_calendar_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["calendar_id", "company_id"],
            ["legal_working_calendars.id", "legal_working_calendars.company_id"],
            name="fk_legal_calendar_version_calendar_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["proposed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_legal_calendar_version_proposer_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["approved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_legal_calendar_version_approver_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_legal_calendar_version_id_company"),
        UniqueConstraint("calendar_id", "version", name="uq_legal_calendar_version_number"),
        CheckConstraint("version > 0", name="ck_legal_calendar_version_positive"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_legal_calendar_version_effective_range",
        ),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'active', 'retired', 'disabled')",
            name="ck_legal_calendar_version_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    calendar_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    weekend_days_json: Mapped[list] = mapped_column(JSON, nullable=False)
    holidays_json: Mapped[list] = mapped_column(JSON, nullable=False)
    exceptional_working_days_json: Mapped[list] = mapped_column(JSON, nullable=False)
    source_priority_json: Mapped[list] = mapped_column(JSON, nullable=False)
    source_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    proposed_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    proposer_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    approver_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpRuleSet(Base):
    """Stable identity for a scoped legal deadline rule."""

    __tablename__ = "ip_rule_sets"
    __table_args__ = (
        UniqueConstraint("key", name="uq_ip_rule_set_key"),
        CheckConstraint("rule_kind IN ('deadline', 'form', 'fee')", name="ck_ip_rule_set_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(40), nullable=False)
    office: Mapped[str | None] = mapped_column(String(120), nullable=True)
    right_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    proceeding_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stage: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpRuleVersion(Base):
    """Immutable proposal/approval evidence for one legal rule version."""

    __tablename__ = "ip_rule_versions"
    __table_args__ = (
        UniqueConstraint("id", "rule_set_id", name="uq_ip_rule_version_id_set"),
        UniqueConstraint("rule_set_id", "version", name="uq_ip_rule_version_number"),
        CheckConstraint("version > 0", name="ck_ip_rule_version_positive"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_rule_version_effective_range",
        ),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'active', 'retired', 'disabled')",
            name="ck_ip_rule_version_status",
        ),
        CheckConstraint(
            "proposed_by_membership_id IS NULL OR legal_approved_by_membership_id IS NULL "
            "OR proposed_by_membership_id <> legal_approved_by_membership_id",
            name="ck_ip_rule_version_legal_approver_distinct",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    rule_set_id: Mapped[str] = mapped_column(
        ForeignKey("ip_rule_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")
    source_record_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    engine_compatibility: Mapped[str] = mapped_column(String(80), nullable=False)
    fixture_set_json: Mapped[list] = mapped_column(JSON, nullable=False)
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    proposed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    proposer_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewer_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_approved_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    legal_approver_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fixtures_passed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CompanyIpRulePolicy(Base):
    """Tenant selection policy; cannot make an unapproved rule authoritative."""

    __tablename__ = "company_ip_rule_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["active_rule_version_id", "rule_set_id"],
            ["ip_rule_versions.id", "ip_rule_versions.rule_set_id"],
            name="fk_company_ip_policy_version_set",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "rule_set_id", name="uq_company_ip_rule_policy"),
        CheckConstraint("version > 0", name="ck_company_ip_rule_policy_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_set_id: Mapped[str] = mapped_column(
        ForeignKey("ip_rule_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    active_rule_version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    auto_confirm_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    internal_target_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updater_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpDeadline(Base):
    """Authoritative legal calculation evidence, not an operational deadline."""

    __tablename__ = "ip_deadlines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_deadline_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["trigger_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_deadline_trigger_event_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["calendar_version_id", "company_id"],
            ["legal_working_calendar_versions.id", "legal_working_calendar_versions.company_id"],
            name="fk_ip_deadline_calendar_version_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_deadline_supersedes_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_deadline_id_company"),
        UniqueConstraint("matter_deadline_id", name="uq_ip_deadline_operational_projection"),
        CheckConstraint("version > 0", name="ck_ip_deadline_version_positive"),
        CheckConstraint(
            "state IN ('provisional', 'candidate', 'confirmed', 'overdue', 'completed', "
            "'superseded', 'cancelled')",
            name="ck_ip_deadline_state",
        ),
        CheckConstraint(
            "date_precision IN ('unknown', 'date', 'datetime', 'session')",
            name="ck_ip_deadline_precision",
        ),
        CheckConstraint(
            "state = 'provisional' OR result_on IS NOT NULL OR result_at IS NOT NULL",
            name="ck_ip_deadline_nonprovisional_result",
        ),
        Index("ix_ip_deadlines_company_state_result", "company_id", "state", "result_on"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    trigger_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    rule_version_id: Mapped[str] = mapped_column(
        ForeignKey("ip_rule_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    calendar_version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    matter_deadline_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_deadlines.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    supersedes_deadline_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    deadline_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    trigger_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    base_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    calendar_method: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    date_precision: Mapped[str] = mapped_column(String(16), nullable=False, default="date")
    certainty: Mapped[str] = mapped_column(String(24), nullable=False)
    result_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    result_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calculation_inputs_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    calculation_trace_json: Mapped[list] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    rule_citation: Mapped[str] = mapped_column(String(512), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    source_version: Mapped[str] = mapped_column(String(120), nullable=False)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confirmer_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    completed_evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    creator_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpRenewalTerm(Base):
    """Canonical renewal state linked to existing legal and platform owners."""

    __tablename__ = "ip_renewal_terms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_renewal_term_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["registration_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_renewal_term_registration_event_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["renewal_deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_renewal_term_deadline_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["grace_deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_renewal_term_grace_deadline_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["filing_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_renewal_term_filing_event_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["acceptance_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_renewal_term_acceptance_event_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["next_term_deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_renewal_term_next_deadline_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["certificate_document_id", "company_id"],
            ["ip_documents.id", "ip_documents.company_id"],
            name="fk_ip_renewal_term_certificate_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_renewal_term_creator_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_renewal_term_updater_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_renewal_term_id_company"),
        UniqueConstraint(
            "company_id",
            "docket_id",
            "registration_event_id",
            "renewal_deadline_id",
            name="uq_ip_renewal_term_legal_basis",
        ),
        CheckConstraint("term_sequence > 0", name="ck_ip_renewal_term_sequence_positive"),
        CheckConstraint("version > 0", name="ck_ip_renewal_term_version_positive"),
        CheckConstraint(
            "state IN ('due', 'instructed', 'filing_in_progress', 'filed', "
            "'accepted', 'grace', 'overdue', 'completed', 'cancelled')",
            name="ck_ip_renewal_term_state",
        ),
        CheckConstraint(
            "state NOT IN ('filed', 'accepted', 'completed') OR filing_event_id IS NOT NULL",
            name="ck_ip_renewal_term_filed_evidence",
        ),
        CheckConstraint(
            "state NOT IN ('accepted', 'completed') OR acceptance_event_id IS NOT NULL",
            name="ck_ip_renewal_term_acceptance_evidence",
        ),
        CheckConstraint(
            "state <> 'completed' OR (certificate_document_id IS NOT NULL "
            "AND next_term_deadline_id IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_ip_renewal_term_completion_evidence",
        ),
        Index(
            "ix_ip_renewal_terms_company_state_deadline",
            "company_id",
            "state",
            "renewal_deadline_id",
        ),
        Index("ix_ip_renewal_terms_docket_id", "docket_id", "company_id"),
        Index(
            "ix_ip_renewal_terms_registration_event_id",
            "registration_event_id",
            "company_id",
        ),
        Index(
            "ix_ip_renewal_terms_renewal_deadline_id",
            "renewal_deadline_id",
            "company_id",
        ),
        Index(
            "ix_ip_renewal_terms_grace_deadline_id",
            "grace_deadline_id",
            "company_id",
        ),
        Index(
            "ix_ip_renewal_terms_fee_cost_item_id", "fee_cost_item_id", "company_id"
        ),
        Index(
            "ix_ip_renewal_terms_filing_event_id", "filing_event_id", "company_id"
        ),
        Index(
            "ix_ip_renewal_terms_acceptance_event_id",
            "acceptance_event_id",
            "company_id",
        ),
        Index(
            "ix_ip_renewal_terms_certificate_document_id",
            "certificate_document_id",
            "company_id",
        ),
        Index(
            "ix_ip_renewal_terms_next_term_deadline_id",
            "next_term_deadline_id",
            "company_id",
        ),
        Index(
            "ix_ip_renewal_terms_created_by_membership_id",
            "created_by_membership_id",
            "company_id",
        ),
        Index(
            "ix_ip_renewal_terms_updated_by_membership_id",
            "updated_by_membership_id",
            "company_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    term_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    registration_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    renewal_deadline_id: Mapped[str] = mapped_column(String(36), nullable=False)
    grace_deadline_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fee_cost_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_cost_items.id", ondelete="RESTRICT"), nullable=True
    )
    filing_initiated_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filing_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acceptance_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    certificate_document_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    next_term_deadline_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="due")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpClientInstruction(Base):
    """Versioned client authorization; channel evidence stays on Communication."""

    __tablename__ = "ip_client_instructions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_client_instruction_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["renewal_term_id", "company_id"],
            ["ip_renewal_terms.id", "ip_renewal_terms.company_id"],
            name="fk_ip_client_instruction_renewal_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["supersedes_instruction_id", "company_id"],
            ["ip_client_instructions.id", "ip_client_instructions.company_id"],
            name="fk_ip_client_instruction_supersedes_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["resulting_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_client_instruction_result_event_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_client_instruction_creator_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["acknowledged_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_client_instruction_acknowledger_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_client_instruction_id_company"),
        UniqueConstraint(
            "renewal_term_id",
            "instruction_version",
            name="uq_ip_client_instruction_term_version",
        ),
        CheckConstraint(
            "instruction_version > 0",
            name="ck_ip_client_instruction_version_positive",
        ),
        CheckConstraint("row_version > 0", name="ck_ip_client_instruction_row_version_positive"),
        CheckConstraint(
            "decision IN ('renew', 'do_not_renew', 'defer', 'clarification_required')",
            name="ck_ip_client_instruction_decision",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'clarification_required', "
            "'superseded')",
            name="ck_ip_client_instruction_status",
        ),
        CheckConstraint(
            "supersedes_instruction_id IS NULL OR supersedes_instruction_id <> id",
            name="ck_ip_client_instruction_supersedes_not_self",
        ),
        CheckConstraint(
            "status NOT IN ('accepted', 'rejected', 'clarification_required') OR "
            "(acknowledged_at IS NOT NULL AND acknowledged_by_membership_id IS NOT NULL)",
            name="ck_ip_client_instruction_acknowledged",
        ),
        CheckConstraint(
            "resulting_event_id IS NULL OR status = 'accepted'",
            name="ck_ip_client_instruction_result_requires_acceptance",
        ),
        Index(
            "ix_ip_client_instructions_company_term_status",
            "company_id",
            "renewal_term_id",
            "status",
        ),
        Index("ix_ip_client_instructions_docket_id", "docket_id", "company_id"),
        Index(
            "ix_ip_client_instructions_source_communication_id",
            "source_communication_id",
            "company_id",
        ),
        Index(
            "ix_ip_client_instructions_acknowledged_by_membership_id",
            "acknowledged_by_membership_id",
            "company_id",
        ),
        Index(
            "ix_ip_client_instructions_supersedes_instruction_id",
            "supersedes_instruction_id",
            "company_id",
        ),
        Index(
            "ix_ip_client_instructions_resulting_event_id",
            "resulting_event_id",
            "company_id",
        ),
        Index(
            "ix_ip_client_instructions_created_by_membership_id",
            "created_by_membership_id",
            "company_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    renewal_term_id: Mapped[str] = mapped_column(String(36), nullable=False)
    instruction_version: Mapped[int] = mapped_column(Integer, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    scope_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    options_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    instruction_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_channel: Mapped[str] = mapped_column(String(40), nullable=False)
    source_communication_id: Mapped[str | None] = mapped_column(
        ForeignKey("communications.id", ondelete="RESTRICT"), nullable=True
    )
    authority_name: Mapped[str] = mapped_column(String(255), nullable=False)
    authority_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by_membership_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    acknowledgement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_instruction_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    resulting_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpResponsibilityAssignment(Base):
    """Effective-dated legal responsibility and acknowledgement evidence."""

    __tablename__ = "ip_responsibility_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_responsibility_docket_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_responsibility_deadline_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_responsibility_membership_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "role IN ('primary', 'backup', 'supervisor', 'docketing')",
            name="ck_ip_responsibility_role",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_responsibility_effective_range",
        ),
        CheckConstraint("version > 0", name="ck_ip_responsibility_version_positive"),
        Index(
            "ix_ip_responsibility_active_deadline_role",
            "deadline_id",
            "role",
            "effective_until",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    deadline_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    membership_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delegation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    replacement_source: Mapped[str] = mapped_column(String(120), nullable=False)
    escalation_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    creator_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# IPLF-028A — shared records-governance foundations.  These tables are
# intentionally additive and dry-run-only.  They record policy, preservation,
# and scoped-operation evidence without exposing a real export, purge,
# offboarding, restore, or provider action.


class DataRetentionPolicyStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class DataRetentionPolicyVersionStatus(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    ACTIVE = "active"
    RETIRED = "retired"
    DISABLED = "disabled"


class LegalHoldStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RELEASED = "released"
    CANCELLED = "cancelled"


class TenantDataOperationStatus(StrEnum):
    PLANNED = "planned"
    DRY_RUN_COMPLETE = "dry_run_complete"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class DataRetentionPolicy(Base):
    """Tenant-scoped identity for a versioned shared retention policy."""

    __tablename__ = "data_retention_policies"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_data_retention_policy_id_company"),
        UniqueConstraint("company_id", "key", name="uq_data_retention_policy_company_key"),
        CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_data_retention_policy_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DataRetentionPolicyStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataRetentionPolicyVersion(Base):
    """Immutable policy terms once they leave the candidate state."""

    __tablename__ = "data_retention_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["policy_id", "company_id"],
            ["data_retention_policies.id", "data_retention_policies.company_id"],
            name="fk_data_retention_version_policy_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proposed_by_membership_id", "proposed_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_data_retention_version_proposer_company",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["reviewed_by_membership_id", "reviewed_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_data_retention_version_reviewer_company",
            ondelete="SET NULL",
        ),
        UniqueConstraint("id", "company_id", name="uq_data_retention_version_id_company"),
        UniqueConstraint(
            "policy_id",
            "company_id",
            "version",
            name="uq_data_retention_version_policy_company_number",
        ),
        CheckConstraint("version > 0", name="ck_data_retention_version_positive"),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'active', 'retired', 'disabled')",
            name="ck_data_retention_version_status",
        ),
        CheckConstraint(
            "sensitivity IN ('internal', 'confidential', 'privileged')",
            name="ck_data_retention_version_sensitivity",
        ),
        CheckConstraint(
            "retention_days IS NULL OR retention_days > 0",
            name="ck_data_retention_version_retention_days_positive",
        ),
        CheckConstraint(
            "(retention_days IS NOT NULL AND "
            "indefinite_retention_approval_ref IS NULL) OR "
            "(retention_days IS NULL AND "
            "indefinite_retention_approval_ref IS NOT NULL)",
            name="ck_data_retention_version_explicit_indefinite_approval",
        ),
        CheckConstraint(
            "length(policy_hash) = 64",
            name="ck_data_retention_version_policy_hash_length",
        ),
        CheckConstraint(
            "proposed_by_membership_id IS NULL OR reviewed_by_membership_id IS NULL "
            "OR proposed_by_membership_id <> reviewed_by_membership_id",
            name="ck_data_retention_version_reviewer_distinct",
        ),
        CheckConstraint(
            "(proposed_by_membership_id IS NULL AND "
            "proposed_by_membership_company_id IS NULL) OR "
            "(proposed_by_membership_id IS NOT NULL AND "
            "proposed_by_membership_company_id = company_id)",
            name="ck_data_retention_version_proposer_company_complete",
        ),
        CheckConstraint(
            "(reviewed_by_membership_id IS NULL AND "
            "reviewed_by_membership_company_id IS NULL) OR "
            "(reviewed_by_membership_id IS NOT NULL AND "
            "reviewed_by_membership_company_id = company_id)",
            name="ck_data_retention_version_reviewer_company_complete",
        ),
        Index(
            "ix_data_retention_versions_company_status",
            "company_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_data_retention_versions_proposer_company",
            "proposed_by_membership_id",
            "proposed_by_membership_company_id",
        ),
        Index(
            "ix_data_retention_versions_reviewer_company",
            "reviewed_by_membership_id",
            "reviewed_by_membership_company_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DataRetentionPolicyVersionStatus.CANDIDATE
    )
    data_class_selector_json: Mapped[list] = mapped_column(JSON, nullable=False)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_policy_basis: Mapped[str] = mapped_column(String(512), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(24), nullable=False)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indefinite_retention_approval_ref: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    disposition: Mapped[str] = mapped_column(String(80), nullable=False)
    hold_behavior: Mapped[str] = mapped_column(String(80), nullable=False)
    source_license_limits: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    subprocessor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    proposed_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    proposer_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    reviewer_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class LegalHold(Base):
    """Preservation state; release never deletes the original hold record."""

    __tablename__ = "legal_holds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["created_by_membership_id", "created_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_legal_hold_creator_company",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["approved_by_membership_id", "approved_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_legal_hold_approver_company",
            ondelete="SET NULL",
        ),
        UniqueConstraint("id", "company_id", name="uq_legal_hold_id_company"),
        UniqueConstraint("company_id", "key", name="uq_legal_hold_company_key"),
        CheckConstraint(
            "status IN ('draft', 'active', 'released', 'cancelled')",
            name="ck_legal_hold_status",
        ),
        CheckConstraint(
            "(status = 'active' AND activated_at IS NOT NULL AND "
            "created_by_membership_id IS NOT NULL AND "
            "created_by_membership_company_id = company_id AND "
            "approved_by_membership_id IS NOT NULL AND "
            "approved_by_membership_company_id = company_id) OR "
            "status <> 'active'",
            name="ck_legal_hold_activation_approval",
        ),
        CheckConstraint(
            "(status = 'released' AND released_at IS NOT NULL) OR "
            "status <> 'released'",
            name="ck_legal_hold_release_state",
        ),
        CheckConstraint(
            "created_by_membership_id IS NULL OR approved_by_membership_id IS NULL "
            "OR created_by_membership_id <> approved_by_membership_id",
            name="ck_legal_hold_approver_distinct",
        ),
        CheckConstraint(
            "(created_by_membership_id IS NULL AND "
            "created_by_membership_company_id IS NULL) OR "
            "(created_by_membership_id IS NOT NULL AND "
            "created_by_membership_company_id = company_id)",
            name="ck_legal_hold_creator_company_complete",
        ),
        CheckConstraint(
            "(approved_by_membership_id IS NULL AND "
            "approved_by_membership_company_id IS NULL) OR "
            "(approved_by_membership_id IS NOT NULL AND "
            "approved_by_membership_company_id = company_id)",
            name="ck_legal_hold_approver_company_complete",
        ),
        Index("ix_legal_holds_company_status", "company_id", "status", "created_at"),
        Index(
            "ix_legal_holds_creator_company",
            "created_by_membership_id",
            "created_by_membership_company_id",
        ),
        Index(
            "ix_legal_holds_approver_company",
            "approved_by_membership_id",
            "approved_by_membership_company_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    authority_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    reason_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=LegalHoldStatus.DRAFT
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    creator_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    approver_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class LegalHoldItem(Base):
    """An opaque target selector belonging to a legal hold."""

    __tablename__ = "legal_hold_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["legal_hold_id", "company_id"],
            ["legal_holds.id", "legal_holds.company_id"],
            name="fk_legal_hold_item_hold_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_legal_hold_item_id_company"),
        UniqueConstraint(
            "legal_hold_id",
            "company_id",
            "data_class_id",
            "target_type",
            "target_reference_hash",
            name="uq_legal_hold_item_target",
        ),
        CheckConstraint(
            "length(target_reference_hash) = 64",
            name="ck_legal_hold_item_target_hash_length",
        ),
        Index(
            "ix_legal_hold_items_company_target",
            "company_id",
            "data_class_id",
            "target_type",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    legal_hold_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    data_class_id: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_label_redacted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class TenantDataOperation(Base):
    """Immutable manifest identity for an explicitly dry-run-only operation."""

    __tablename__ = "tenant_data_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["requested_by_membership_id", "requested_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_tenant_data_operation_requester_company",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["retention_policy_version_id", "company_id"],
            ["data_retention_versions.id", "data_retention_versions.company_id"],
            name="fk_tenant_data_operation_policy_version_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["approves_operation_id", "company_id"],
            ["tenant_data_operations.id", "tenant_data_operations.company_id"],
            name="fk_tenant_data_operation_approves_operation_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_tenant_data_operation_id_company"),
        # NULLs do not collide, so every dry run is unaffected; two execute rows
        # citing one manifest do collide, which is the point.
        UniqueConstraint(
            "approves_operation_id",
            "company_id",
            name="uq_tenant_data_operation_approves_operation",
        ),
        CheckConstraint(
            "operation_type IN ('tenant_export', 'retention_purge', "
            "'tenant_offboarding', 'restore_validation')",
            name="ck_tenant_data_operation_type",
        ),
        CheckConstraint(
            "execution_mode IN ('dry_run', 'execute')",
            name="ck_tenant_data_operation_execution_mode",
        ),
        # Replaces the former dry-run-only fence. Dropping that constraint
        # outright would have removed the last-resort guarantee on the one table
        # that governs export and purge, leaving every control in application
        # code. Execute is instead expressible only with a second person's
        # recorded approval - the same rule ck_legal_hold_activation_approval
        # already enforces for holds.
        # A dry run may never be APPROVED - that is what stops an approved
        # execute being relabelled a simulation while keeping its signature.
        # It MAY be 'requested' or 'rejected': that is where an approval request
        # lives. The first version of this predicate forbade those too, which
        # made both states unreachable by any row and left a rejection with
        # nowhere to go except deleting the manifest.
        CheckConstraint(
            "execution_mode <> 'dry_run' "
            "OR approval_status IN ('not_requested', 'requested', 'rejected')",
            name="ck_tenant_data_operation_dry_run_unapproved",
        ),
        CheckConstraint(
            "execution_mode <> 'execute' OR ("
            "approval_status = 'approved' "
            "AND approved_at IS NOT NULL "
            "AND approved_by_membership_id IS NOT NULL "
            "AND approved_by_membership_company_id = company_id "
            "AND requested_by_membership_id IS NOT NULL "
            "AND requested_by_membership_company_id = company_id)",
            name="ck_tenant_data_operation_execute_requires_approval",
        ),
        # An execute row must name the dry run whose manifest was reviewed.
        # Without this an execute row could exist with no originating manifest
        # at all, bypassing review entirely, and no approval could be traced to
        # what its approver actually saw.
        CheckConstraint(
            "execution_mode <> 'execute' OR approves_operation_id IS NOT NULL",
            name="ck_tenant_data_operation_execute_cites_manifest",
        ),
        CheckConstraint(
            "execution_mode <> 'dry_run' OR approves_operation_id IS NULL",
            name="ck_tenant_data_operation_dry_run_approves_nothing",
        ),
        CheckConstraint(
            "requested_by_membership_id IS NULL "
            "OR approved_by_membership_id IS NULL "
            "OR requested_by_membership_id <> approved_by_membership_id",
            name="ck_tenant_data_operation_approver_distinct",
        ),
        CheckConstraint(
            "(approved_by_membership_id IS NULL AND approved_by_membership_company_id IS NULL) "
            "OR (approved_by_membership_id IS NOT NULL "
            "AND approved_by_membership_company_id = company_id)",
            name="ck_tenant_data_operation_approver_company_complete",
        ),
        CheckConstraint(
            "status IN ('planned', 'dry_run_complete', 'blocked', 'cancelled')",
            name="ck_tenant_data_operation_status",
        ),
        CheckConstraint(
            "approval_status IN ('not_requested', 'requested', 'approved', 'rejected')",
            name="ck_tenant_data_operation_approval_status",
        ),
        # A refusal that does not say why is not evidence of anything. Tying
        # the reason to the state in both directions also stops a stale reason
        # from an earlier refusal riding along on a row that is no longer
        # rejected.
        CheckConstraint(
            "(approval_status = 'rejected' AND rejection_reason IS NOT NULL) "
            "OR (approval_status <> 'rejected' AND rejection_reason IS NULL)",
            name="ck_tenant_data_operation_rejection_reason",
        ),
        CheckConstraint(
            "length(request_scope_hash) = 64",
            name="ck_tenant_data_operation_scope_hash_length",
        ),
        CheckConstraint(
            "manifest_hash IS NULL OR length(manifest_hash) = 64",
            name="ck_tenant_data_operation_manifest_hash_length",
        ),
        CheckConstraint(
            "(status = 'dry_run_complete' AND dry_run_completed_at IS NOT NULL "
            "AND manifest_hash IS NOT NULL) OR status <> 'dry_run_complete'",
            name="ck_tenant_data_operation_completion_manifest",
        ),
        CheckConstraint(
            "(requested_by_membership_id IS NULL AND "
            "requested_by_membership_company_id IS NULL) OR "
            "(requested_by_membership_id IS NOT NULL AND "
            "requested_by_membership_company_id = company_id)",
            name="ck_tenant_data_operation_requester_company_complete",
        ),
        Index(
            "ix_tenant_data_operations_company_status",
            "company_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_tenant_data_operations_requester_company",
            "requested_by_membership_id",
            "requested_by_membership_company_id",
        ),
        Index(
            "ix_tenant_data_operations_retention_policy_version_id",
            "retention_policy_version_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="dry_run")
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=TenantDataOperationStatus.PLANNED
    )
    approval_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_requested"
    )
    request_scope_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_evidence_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    retention_policy_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    manifest_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    requester_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by_membership_company_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    approver_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dry_run_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    blocked_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Distinct from blocked_reason: "a legal hold stopped this" and "a human
    # refused this" are different states with different remedies, and a single
    # column would let one overwrite the other.
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approves_operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class TenantDataOperationItem(Base):
    """Opaque dry-run item/checkpoint; it can never authorize execution."""

    __tablename__ = "tenant_data_operation_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "company_id"],
            ["tenant_data_operations.id", "tenant_data_operations.company_id"],
            name="fk_tenant_data_operation_item_operation_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["legal_hold_id", "company_id"],
            ["legal_holds.id", "legal_holds.company_id"],
            name="fk_tenant_data_operation_item_hold_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_tenant_data_operation_item_id_company"),
        UniqueConstraint(
            "operation_id",
            "company_id",
            "data_class_id",
            "target_type",
            "target_reference_hash",
            name="uq_tenant_data_operation_item_target",
        ),
        CheckConstraint(
            "item_status IN ('pending', 'eligible', 'held', 'blocked')",
            name="ck_tenant_data_operation_item_status",
        ),
        CheckConstraint(
            "length(target_reference_hash) = 64",
            name="ck_tenant_data_operation_item_target_hash_length",
        ),
        CheckConstraint(
            "candidate_record_count >= 0 AND estimated_bytes >= 0",
            name="ck_tenant_data_operation_item_counts_nonnegative",
        ),
        CheckConstraint(
            "safe_to_execute = false",
            name="ck_tenant_data_operation_item_never_execute",
        ),
        CheckConstraint(
            "(item_status = 'held' AND legal_hold_id IS NOT NULL) OR "
            "item_status <> 'held'",
            name="ck_tenant_data_operation_item_hold_evidence",
        ),
        Index(
            "ix_tenant_data_operation_items_company_operation",
            "company_id",
            "operation_id",
            "item_status",
        ),
        Index("ix_tenant_data_operation_items_legal_hold_id", "legal_hold_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    data_class_id: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    item_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    candidate_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    legal_hold_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    safe_to_execute: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detail_redacted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class BulkImportJob(Base):
    """Neutral, domain-tagged bulk import owner (ARCH-OPS-23).

    Deliberately not IP-specific: `domain` selects the typed row table. The
    legacy `matter_bulk_import_jobs` and `employee_bulk_import_jobs` owners stay
    canonical for their domains and are not migrated here.
    """

    __tablename__ = "bulk_import_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_bulk_import_job_creator_company",
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("id", "company_id", name="uq_bulk_import_job_company"),
        UniqueConstraint(
            "company_id", "domain", "idempotency_key", name="uq_bulk_import_job_idempotency"
        ),
        CheckConstraint("domain IN ('ip_trademark')", name="ck_bulk_import_job_domain"),
        CheckConstraint(
            "status IN ('staged', 'preview_ready', 'committed', "
            "'committed_with_errors', 'failed', 'cancelled')",
            name="ck_bulk_import_job_status",
        ),
        CheckConstraint("total_rows >= 0", name="ck_bulk_import_job_total_rows"),
        Index("ix_bulk_import_jobs_company_domain", "company_id", "domain"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="staged")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    committed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    preview_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preview_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    creator_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpImportRow(Base):
    """Typed IP staging row for one `bulk_import_jobs` entry."""

    __tablename__ = "ip_import_rows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "company_id"],
            ["bulk_import_jobs.id", "bulk_import_jobs.company_id"],
            name="fk_ip_import_row_job_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["created_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_import_row_created_docket_company",
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["reconciled_target_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_import_row_reconciled_docket_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("job_id", "row_number", name="uq_ip_import_row_number"),
        CheckConstraint("row_number > 0", name="ck_ip_import_row_number_positive"),
        CheckConstraint(
            "validation_status IN ('valid', 'invalid')",
            name="ck_ip_import_row_validation_status",
        ),
        CheckConstraint(
            "commit_status IN ('pending', 'committed', 'failed', 'skipped')",
            name="ck_ip_import_row_commit_status",
        ),
        CheckConstraint(
            "reconciliation_decision IS NULL OR reconciliation_decision IN "
            "('create_separate', 'link_existing', 'skip')",
            name="ck_ip_import_row_reconciliation_decision",
        ),
        Index("ix_ip_import_rows_job_commit", "job_id", "commit_status"),
        Index(
            "ix_ip_import_rows_reconciled_target",
            "reconciled_target_docket_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    normalized_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="valid")
    errors_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    duplicate_candidates_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reconciliation_decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reconciled_target_docket_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    commit_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    commit_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_docket_id: Mapped[str | None] = mapped_column(
        ForeignKey("ip_docket_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpDocketControlReview(Base):
    """A daily docket control report that can be signed off (CAL-OPS-09).

    The report is materialized as a hash-bound canonical snapshot: query/schema
    versions, timezone and hidden-count policy, included record IDs/hashes,
    freshness, exceptions and aggregate output all remain exactly as reviewed.
    Check constraints refuse a sign-off on an incomplete or export-failed
    review so the database enforces the same rule as the service.
    """

    __tablename__ = "ip_docket_control_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["signed_off_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_control_review_signer_company",
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_control_review_creator_company",
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "completeness_status IN ('complete', 'incomplete')",
            name="ck_ip_control_review_completeness",
        ),
        CheckConstraint(
            "export_status IN ('not_requested', 'generated', 'failed')",
            name="ck_ip_control_review_export_status",
        ),
        CheckConstraint(
            "signed_off_at IS NULL OR "
            "(completeness_status = 'complete' AND export_status <> 'failed')",
            name="ck_ip_control_review_signoff_requires_clean",
        ),
        CheckConstraint(
            "signed_off_at IS NULL OR signed_off_by_membership_id IS NOT NULL",
            name="ck_ip_control_review_signoff_has_signer",
        ),
        CheckConstraint(
            "required_signature_count IN (1, 2) AND required_sample_size BETWEEN 0 AND 20",
            name="ck_ip_control_review_policy_bounds",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_control_review_id_company"),
        UniqueConstraint(
            "id",
            "company_id",
            "manifest_sha256",
            name="uq_ip_control_review_id_company_manifest",
        ),
        ForeignKeyConstraint(
            ["predecessor_review_id", "company_id"],
            ["ip_docket_control_reviews.id", "ip_docket_control_reviews.company_id"],
            name="fk_ip_control_review_predecessor_company",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_ip_docket_control_reviews_company_generated", "company_id", "generated_at"),
        Index("ix_ip_control_review_predecessor", "predecessor_review_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    filters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    freshness_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    completeness_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="complete"
    )
    incompleteness_reasons_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    mandatory_exception_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    query_version: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    report_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    required_signature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    required_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    predecessor_review_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    delta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    export_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="not_requested"
    )
    export_error_redacted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signed_off_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    signer_label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signed_off_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IpControlReviewExceptionDecision(Base):
    """Append-only resolution or annotation for one frozen report exception."""

    __tablename__ = "ip_control_review_exception_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id", "company_id"],
            ["ip_docket_control_reviews.id", "ip_docket_control_reviews.company_id"],
            name="fk_ip_control_exception_decision_review_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["decided_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_control_exception_decision_actor_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "disposition IN ('resolved', 'annotated')",
            name="ck_ip_control_exception_decision_disposition",
        ),
        UniqueConstraint(
            "review_id",
            "docket_id",
            "exception_kind",
            name="uq_ip_control_exception_decision",
        ),
        Index("ix_ip_control_exception_decision_review", "review_id", "decided_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    exception_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    annotation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    decided_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpControlReviewSampleEvidence(Base):
    """Append-only second-reviewer sample against one included docket."""

    __tablename__ = "ip_control_review_sample_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id", "company_id"],
            ["ip_docket_control_reviews.id", "ip_docket_control_reviews.company_id"],
            name="fk_ip_control_sample_review_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reviewer_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_control_sample_reviewer_company",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "review_id",
            "docket_id",
            "reviewer_membership_id",
            name="uq_ip_control_sample_reviewer_docket",
        ),
        Index("ix_ip_control_sample_review", "review_id", "sampled_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reviewer_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    calculation_evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    coverage_evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sampled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpControlReviewSignature(Base):
    """One immutable signature bound to the exact report manifest."""

    __tablename__ = "ip_control_review_signatures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_id", "company_id"],
            ["ip_docket_control_reviews.id", "ip_docket_control_reviews.company_id"],
            name="fk_ip_control_signature_review_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["review_id", "company_id", "manifest_sha256"],
            [
                "ip_docket_control_reviews.id",
                "ip_docket_control_reviews.company_id",
                "ip_docket_control_reviews.manifest_sha256",
            ],
            name="fk_ip_control_signature_manifest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["signer_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_control_signature_signer_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(signer_role = 'preparer' AND sequence = 1) OR "
            "(signer_role = 'reviewer' AND sequence = 2)",
            name="ck_ip_control_signature_role_sequence",
        ),
        UniqueConstraint("review_id", "signer_membership_id", name="uq_ip_control_signature_actor"),
        UniqueConstraint("review_id", "sequence", name="uq_ip_control_signature_sequence"),
        UniqueConstraint("review_id", "signer_role", name="uq_ip_control_signature_role"),
        Index("ix_ip_control_signature_review", "review_id", "sequence"),
        Index("ix_ip_control_signature_manifest_sha256", "manifest_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    review_id: Mapped[str] = mapped_column(String(36), nullable=False)
    signer_membership_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    signer_role: Mapped[str] = mapped_column(String(16), nullable=False)
    signer_label_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    attestation: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IpDocketQueue(Base):
    """A saved daily-docket queue (CAL-OPS-09).

    A queue is a named, reusable set of daily-docket filters. Scoping is
    explicit: a queue with ``team_id`` is shared with that team, and one
    without it belongs to the member who saved it. There is no company-wide
    tier, because a queue that everyone can edit is a queue nobody owns.
    """

    __tablename__ = "ip_docket_queues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["team_id", "company_id"],
            ["teams.id", "teams.company_id"],
            name="fk_ip_docket_queue_team_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_docket_queue_owner_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_docket_queue_creator_company",
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("company_id", "name", name="uq_ip_docket_queue_company_name"),
        CheckConstraint(
            "team_id IS NOT NULL OR owner_membership_id IS NOT NULL",
            name="ck_ip_docket_queue_has_scope",
        ),
        Index("ix_ip_docket_queues_company_team", "company_id", "team_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    filters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    owner_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
