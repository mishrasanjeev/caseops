"""Synchronous derived counsel pages; these rows grant no read authority."""

from sqlalchemy import JSON, BigInteger, CheckConstraint, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


class CounselReadPage(Base):
    """PostgreSQL physical leaf; unbounded source notes stay native TEXT."""

    __tablename__ = "counsel_read_pages"
    __table_args__ = (
        CheckConstraint("record_kind IN ('assignment', 'spend')", name="ck_counsel_page_kind"),
        CheckConstraint("page_number >= 0", name="ck_counsel_page_number"),
        CheckConstraint("record_count BETWEEN 1 AND 25", name="ck_counsel_page_capacity"),
        Index("ix_counsel_read_pages_matter_id", "matter_id"),
    )
    # Deliberately no parent FK/parent row lock: a profile writer may hold its
    # Counsel/Membership key while a source writer already holds Matter. Taking
    # another Matter key lock from profile propagation would invert that order.
    # Source/parent cleanup triggers own these derived rows; they grant no ACL.
    company_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    matter_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    record_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    max_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    min_id: Mapped[str] = mapped_column(String(36), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)


# A source Text datum must not be forced into a25record JSON/array datum or
# rejected by a new projection byte limit. Each slot retains its original
# independently TOAST-able value. The rest of the PostgreSQL source/name fields
# have existing bounded VARCHAR/numeric/date types. No new source constraint is
# introduced here. Service code accesses these columns through __table__.c.
for _slot in range(25):
    setattr(CounselReadPage, f"note_{_slot:02}", mapped_column(Text, nullable=True))


class CounselReadPageMember(Base):
    """SQLite native key/rank projection; its canonical reader stays unchanged.

    SQLite does not enforce VARCHAR widths, so aggregating legacy field values
    into a page can reject a write that its source table accepts. Native source
    keys and dense page/slot ranks avoid JSON expansion and never duplicate or
    aggregate unbounded notes. A logical leaf is (scope,page_number), capacity25.
    PostgreSQL uses CounselReadPage instead; neither table is an ACL source.
    """

    __tablename__ = "counsel_read_page_members"
    __table_args__ = (
        CheckConstraint("record_kind IN ('assignment', 'spend')", name="ck_counsel_member_kind"),
        CheckConstraint("page_number >= 0", name="ck_counsel_member_page_number"),
        CheckConstraint("slot_number BETWEEN 0 AND 24", name="ck_counsel_member_slot"),
        Index("ix_counsel_page_members_matter_id", "matter_id"),
    )
    company_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    matter_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    record_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)


class CounselReadPageDirty(Base):
    """Private current-transaction scopes; the deferred finalizer empties them.

    No parent/source FK or source-phase shared projection lock. A committed
    scope is rebuilt in the same source transaction, after all source/audit FKs.
    """

    __tablename__ = "counsel_read_page_dirty"
    __table_args__ = (
        CheckConstraint(
            "record_kind IN ('assignment', 'spend', 'user')", name="ck_counsel_dirty_kind"
        ),
        CheckConstraint(
            "(record_kind = 'user' AND company_id = '' AND matter_id = '' "
            ") OR (record_kind IN ('assignment', 'spend') AND source_user_id = '')",
            name="ck_counsel_dirty_scope",
        ),
    )
    transaction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    record_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    matter_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
