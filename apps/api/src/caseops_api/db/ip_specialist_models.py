"""Restricted specialist facts and immutable source observations."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


class IpSpecialistRecord(Base):
    __tablename__ = "ip_specialist_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["asset_id", "company_id"],
            ["ip_assets.id", "ip_assets.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["client_id", "company_id"], ["clients.id", "clients.company_id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("id", "company_id", name="uq_specialist_record_company"),
        UniqueConstraint("docket_id", "company_id", name="uq_specialist_docket_company"),
        UniqueConstraint("asset_id", "company_id", name="uq_specialist_asset_company"),
        CheckConstraint(
            "domain IN ('design','copyright','domain_name','licensing','enforcement',"
            "'geographical_indication','plant_variety','semiconductor_layout','trade_secret',"
            "'customs_enforcement')",
            name="ck_specialist_domain",
        ),
        CheckConstraint("observation_sequence >= 0", name="ck_specialist_sequence"),
        Index("ix_specialist_domain_cursor", "company_id", "domain", "id"),
        Index("ix_specialist_client", "client_id", "company_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    domain: Mapped[str] = mapped_column(String(40), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IpSpecialistVersion(Base):
    __tablename__ = "ip_specialist_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["record_id", "company_id"],
            ["ip_specialist_records.id", "ip_specialist_records.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("record_id", "company_id", "version", name="uq_specialist_version"),
        CheckConstraint("version > 0", name="ck_specialist_version_positive"),
        CheckConstraint("length(facts_sha256) = 64", name="ck_specialist_facts_hash"),
        Index("ix_specialist_version_actor", "actor_id", "company_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    facts_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    facts_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class IpSpecialistObservation(Base):
    __tablename__ = "ip_specialist_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["record_id", "company_id"],
            ["ip_specialist_records.id", "ip_specialist_records.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_version_id", "company_id", "source_document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_id", "company_id", "record_id"],
            [
                "ip_specialist_observations.id",
                "ip_specialist_observations.company_id",
                "ip_specialist_observations.record_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "company_id", "record_id", name="uq_specialist_observation_identity"
        ),
        UniqueConstraint(
            "record_id", "company_id", "sequence", name="uq_specialist_observation_sequence"
        ),
        UniqueConstraint("supersedes_id", "company_id", name="uq_specialist_observation_successor"),
        CheckConstraint("sequence > 0", name="ck_specialist_observation_sequence"),
        CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id", name="ck_specialist_not_self"
        ),
        CheckConstraint("length(source_sha256) = 64", name="ck_specialist_source_hash"),
        Index("ix_specialist_observation_actor", "actor_id", "company_id"),
        Index("ix_specialist_observation_prior", "supersedes_id", "company_id", "record_id"),
        Index(
            "ix_specialist_observation_source",
            "source_version_id",
            "company_id",
            "source_document_id",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    account: Mapped[str] = mapped_column(Text, nullable=False)
    source_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[str] = mapped_column(String(500), nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(String(36))
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class IpSpecialistWorkflow(Base):
    __tablename__ = "ip_specialist_workflows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["record_id", "company_id"],
            ["ip_specialist_records.id", "ip_specialist_records.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["title_interest_id", "company_id"],
            ["ip_title_interests.id", "ip_title_interests.company_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", name="uq_specialist_workflow_company"),
        CheckConstraint("version > 0", name="ck_specialist_workflow_version"),
        CheckConstraint(
            "kind IN ('source_set','design_application','copyright_registration',"
            "'rights_claim','licence','proceeding','layout_application')",
            name="ck_specialist_workflow_kind",
        ),
        Index("ix_specialist_workflow_record", "record_id", "company_id", "id"),
        Index("ix_specialist_workflow_proceeding", "proceeding_id", "company_id"),
        Index("ix_specialist_workflow_interest", "title_interest_id", "company_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    proceeding_id: Mapped[str | None] = mapped_column(String(36))
    title_interest_id: Mapped[str | None] = mapped_column(String(36))


class IpSpecialistWorkflowVersion(Base):
    __tablename__ = "ip_specialist_workflow_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "company_id"],
            ["ip_specialist_workflows.id", "ip_specialist_workflows.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workflow_id", "company_id", "version", name="uq_specialist_workflow_revision"
        ),
        UniqueConstraint("id", "company_id", name="uq_specialist_workflow_version_company"),
        CheckConstraint("version > 0", name="ck_specialist_workflow_revision"),
        CheckConstraint("length(facts_sha256) = 64", name="ck_specialist_workflow_hash"),
        Index("ix_specialist_workflow_version_actor", "actor_id", "company_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    facts_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    facts_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class IpSpecialistWorkflowSource(Base):
    __tablename__ = "ip_specialist_workflow_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "company_id"],
            ["ip_specialist_workflow_versions.id", "ip_specialist_workflow_versions.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("revision_id", "ordinal", name="uq_specialist_workflow_source_ordinal"),
        CheckConstraint(
            "ordinal >= 0 AND ordinal < 52", name="ck_specialist_workflow_source_bound"
        ),
        CheckConstraint("length(content_sha256) = 64", name="ck_specialist_workflow_source_hash"),
        Index("ix_specialist_workflow_source_revision", "revision_id", "company_id"),
        Index(
            "ix_specialist_workflow_source_document",
            "document_version_id",
            "company_id",
            "document_id",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[str] = mapped_column(String(500), nullable=False)


class IpSpecialistObligationLink(Base):
    __tablename__ = "ip_specialist_obligation_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "company_id"],
            ["ip_specialist_workflows.id", "ip_specialist_workflows.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["obligation_id", "company_id", "docket_id"],
            [
                "ip_related_right_obligations.id",
                "ip_related_right_obligations.company_id",
                "ip_related_right_obligations.docket_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "company_id"],
            ["matter_tasks.id", "matter_tasks.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["cost_item_id", "company_id", "docket_id"],
            ["ip_cost_items.id", "ip_cost_items.company_id", "ip_cost_items.docket_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "obligation_id", "company_id", "docket_id", name="uq_specialist_obligation_scope"
        ),
        Index("ix_specialist_obligation_workflow", "workflow_id", "company_id"),
        Index("ix_specialist_obligation_task", "task_id", "company_id"),
        Index(
            "ix_specialist_obligation_source", "document_version_id", "company_id", "document_id"
        ),
        Index("ix_specialist_obligation_cost", "cost_item_id", "company_id", "docket_id"),
    )
    obligation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[str] = mapped_column(String(500), nullable=False)
    cost_item_id: Mapped[str | None] = mapped_column(String(36))


class IpSpecialistObligationEvent(Base):
    __tablename__ = "ip_specialist_obligation_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["obligation_id", "company_id", "docket_id"],
            [
                "ip_specialist_obligation_links.obligation_id",
                "ip_specialist_obligation_links.company_id",
                "ip_specialist_obligation_links.docket_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["cost_item_id", "company_id", "docket_id"],
            ["ip_cost_items.id", "ip_cost_items.company_id", "ip_cost_items.docket_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "action IN ('complete','cancel','notice_recorded')",
            name="ck_specialist_obligation_action",
        ),
        Index(
            "ix_specialist_obligation_event_parent",
            "obligation_id",
            "company_id",
            "docket_id",
            "id",
        ),
        Index("ix_specialist_obligation_event_actor", "actor_id", "company_id"),
        Index(
            "ix_specialist_obligation_event_source",
            "document_version_id",
            "company_id",
            "document_id",
        ),
        Index("ix_specialist_obligation_event_cost", "cost_item_id", "company_id", "docket_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    obligation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    account: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[str] = mapped_column(String(500), nullable=False)
    cost_item_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
