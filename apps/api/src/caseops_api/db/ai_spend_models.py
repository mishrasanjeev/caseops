from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


class AiProviderSpendMonth(Base):
    """One platform account budget shared by every tenant and AI provider."""

    __tablename__ = "ai_provider_spend_months"
    __table_args__ = (
        CheckConstraint(
            "limit_minor > 0 AND limit_minor <= 1000000",
            name="ck_ai_spend_limit_owner_ceiling",
        ),
        CheckConstraint(
            "opening_spend_minor >= 0 AND admitted_minor >= opening_spend_minor",
            name="ck_ai_spend_nonnegative",
        ),
        CheckConstraint("inr_per_usd_all_in > 0", name="ck_ai_spend_fx_positive"),
    )

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    limit_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_spend_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    admitted_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    inr_per_usd_all_in: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    pricing_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    opening_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reconciled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AiProviderSpendAdmission(Base):
    """Content-free conservative charge; uncertain dispatches are not refunded."""

    __tablename__ = "ai_provider_spend_admissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    month: Mapped[str] = mapped_column(
        ForeignKey("ai_provider_spend_months.month", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    upper_bound_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        CheckConstraint("upper_bound_minor > 0", name="ck_ai_spend_admission_positive"),
    )
