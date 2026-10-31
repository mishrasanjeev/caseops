"""Dense task read pages. Source Tasks remain authoritative and unmodified.

No parent FKs: refresh takes only queue-group advisory locks, never an extra
Matter/Member row lock. Nullable legacy source scope is retained in matter_tasks
and excluded from this tenant-scoped projection, exactly as the canonical read.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)

from caseops_api.db.base import Base

SLOTS = 25
TASK_FIELDS = ("id", "title", "status", "priority", "due_on", "created_at", "updated_at")


class MatterTaskQueueGroup(Base):
    __tablename__ = "matter_task_queue_groups"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "matter_id",
            "owner_is_null",
            "owner_key",
            name="uq_matter_task_queue_group_scope",
        ),
        CheckConstraint(
            "(owner_is_null AND owner_key = '') OR NOT owner_is_null",
            name="ck_matter_task_queue_group_owner_key",
        ),
    )
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    company_id = Column(String(36), nullable=False)
    matter_id = Column(String(36), nullable=False)
    owner_is_null = Column(Boolean, nullable=False)
    owner_key = Column(String(36), nullable=False)


# Fixed scalar columns, not JSON or a hidden SQL unpacking function. Text avoids
# introducing a new truncation/rejection boundary for retained SQLite strings.
_types = {
    "id": String(36),
    "title": Text(),
    "status": Text(),
    "priority": Text(),
    "due_on": Date(),
    "created_at": DateTime(timezone=True),
    "updated_at": DateTime(timezone=True),
}
_attrs = {
    "__tablename__": "matter_task_queue_pages",
    "group_id": Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
    "page_no": Column(Integer, primary_key=True),
    "entry_count": Column(Integer, nullable=False),
    "has_dated": Column(Boolean, nullable=False),
    "has_undated": Column(Boolean, nullable=False),
    "min_dated": Column(Date),
    "max_dated": Column(Date),
    "last_null": Column(Boolean, nullable=False),
    "last_date": Column(Date, nullable=False),
    "last_created": Column(DateTime(timezone=True), nullable=False),
    "last_id": Column(String(36), nullable=False),
    "__table_args__": (
        PrimaryKeyConstraint(name="pk_matter_task_queue_pages"),
        CheckConstraint("entry_count BETWEEN 1 AND 25", name="ck_matter_task_queue_page_size"),
        CheckConstraint("page_no >= 0", name="ck_matter_task_queue_page_number"),
    ),
}
for _slot in range(SLOTS):
    for _name, _type in _types.items():
        _attrs[f"s{_slot}_{_name}"] = Column(_type)
MatterTaskQueuePage = type("MatterTaskQueuePage", (Base,), _attrs)


class MatterTaskQueueDirty(Base):
    """Private transaction-local scope collection; rows are removed at finalize."""

    __tablename__ = "matter_task_queue_dirty"
    transaction_id = Column(BigInteger, primary_key=True)
    company_id = Column(String(36), primary_key=True)
    matter_id = Column(String(36), primary_key=True)
    owner_is_null = Column(Boolean, primary_key=True)
    owner_key = Column(String(36), primary_key=True)
