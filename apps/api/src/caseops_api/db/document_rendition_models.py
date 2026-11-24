"""OCR text and legal translations derived from an existing matter attachment.

A rendition never replaces its source. The original upload, its storage object
and its retrieval chunks stay untouched; each OCR or translation run is a new,
numbered version linked to the same company, matter and attachment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class RenditionKind(StrEnum):
    OCR = "ocr"
    TRANSLATION = "translation"


class RenditionStatus(StrEnum):
    QUEUED = "queued"
    INSPECTING = "inspecting"
    OCR_PROCESSING = "ocr_processing"
    OCR_COMPLETED = "ocr_completed"
    TRANSLATION_PROCESSING = "translation_processing"
    TRANSLATION_COMPLETED = "translation_completed"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class RenditionReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    NEEDS_CORRECTION = "needs_correction"


ACTIVE_RENDITION_STATUSES = (
    RenditionStatus.QUEUED,
    RenditionStatus.INSPECTING,
    RenditionStatus.OCR_PROCESSING,
    RenditionStatus.TRANSLATION_PROCESSING,
)
_ACTIVE_SQL = "status IN ('queued', 'inspecting', 'ocr_processing', 'translation_processing')"


class MatterAttachmentRendition(Base):
    __tablename__ = "matter_attachment_renditions"
    __table_args__ = (
        UniqueConstraint(
            "attachment_id", "kind", "version", name="uq_matter_attachment_rendition_version",
        ),
        # One running OCR and one running translation per attachment. A second
        # click (or a second tab) reuses the open run instead of paying twice.
        Index(
            "uq_matter_attachment_rendition_active",
            "attachment_id",
            "kind",
            unique=True,
            postgresql_where=text(_ACTIVE_SQL),
            sqlite_where=text(_ACTIVE_SQL),
        ),
        UniqueConstraint(
            "output_storage_key", name="uq_matter_attachment_renditions_output_storage_key",
        ),
        CheckConstraint("kind IN ('ocr', 'translation')", name="ck_matter_rendition_kind"),
        CheckConstraint(
            "review_status IN ('unreviewed', 'reviewed', 'needs_correction')",
            name="ck_matter_rendition_review_status",
        ),
        CheckConstraint("version >= 1", name="ck_matter_rendition_version"),
        CheckConstraint(
            "kind = 'ocr' OR (source_rendition_id IS NOT NULL AND target_language IS NOT NULL)",
            name="ck_matter_rendition_translation_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    matter_id: Mapped[str] = mapped_column(
        ForeignKey("matters.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("matter_attachments.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    source_rendition_id: Mapped[str | None] = mapped_column(
        ForeignKey("matter_attachment_renditions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=RenditionStatus.QUEUED,
    )
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=RenditionReviewStatus.UNREVIEWED,
    )
    source_language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # OCR runs started from "OCR & Translate" queue this translation on success.
    chain_target_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_review: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Page-level text, structure, flags and provenance (JSON list).
    pages_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provider job ledger: batch pages, provider job ids, spend holds (JSON list).
    provider_jobs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
